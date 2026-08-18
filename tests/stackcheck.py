#!/usr/bin/env python3
"""Slice a multi-part colour stack and report who owns what.

Two questions the other five checks cannot answer, both specific to a part that
is authored as several interpenetrating STLs printed as one object:

  1. DOES EVERY LEVEL PRINT?  A feature thinner than one extrusion width slices
     to nothing. It is watertight, on the bed, island-free, cantilever-free, and
     Bambu reports no overhang -- because there is nothing there to overhang.
     Every check in the gate passes a part that has silently vanished.

  2. WHO WINS AN OVERLAP?  Once the levels are pedestalled to a common floor
     they interpenetrate, and in a shared volume only one filament can be laid.
     The medallion is backlit, so that choice is the transmitted colour.

Measured answer to (2), from the two-box probe in this script's history and
confirmed on the medallion: THE LATER PART WINS. Part k is clipped by every
part after it, so the last level covering an (x, y) owns the whole column
beneath it.

Usage:
    python3 tests/stackcheck.py 'out/MED-*.stl'
    python3 tests/stackcheck.py 'out/MED-*.stl' --layers 2.5:3.2

Levels are loaded in sorted filename order, which is the order the slicer sees
and therefore the order that decides overlaps. Name them so sorting matches the
intended bottom-to-top stack.

Tool numbering: Bambu emits tool `k-1` for part `k`.

THE FIRST BLOCK OF LAYER 1 IS UNLABELLED, AND IT IS NOT NECESSARILY TOOL 0.
This docstring used to say the machine starts with slot 1 loaded, so a parser
could default to tool 0 and mislabel nothing. That is wrong. Layer 1's tool
order is the slicer's to choose -- the profiles ship `first_layer_print_sequence
= 0`, which means auto -- and no T command is emitted for whichever tool it
decides to open with, so every extrusion before the first explicit T belongs to
an unknown filament.

Defaulting that block to tool 0 credits one part's whole first layer to another.
It filed issue #23: on the pane-7 glass tile Bambu started with the came (part
8), so the came's first layer was booked to cornflower and the came was reported
absent from layer 1 -- on the tile's viewing face. Nothing was wrong with the
slicer or the mesh. See `initial_tool` below for how it is resolved instead.

The failure mode that made it worth fixing rather than working around is the
opposite one: because the unlabelled block was always credited to tool 0, part 1
ALWAYS looked like it printed. A vanishing part 1 -- the exact thing this check
exists to catch -- could not have been detected.
"""
import argparse, atexit, glob, json, math, os, re, shutil, subprocess, sys, tempfile, zipfile

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "printing-toolkit", "tests")))
from slicecheck import (flatten, write_profile, run_slice, CRASH_RETRIES,
                        STUDIO, MACHINE, PROCESS, FILAMENT, BED_TYPE)

PALETTE = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF", "#00FFFF",
           "#FF8000", "#8000FF"]


# Seconds before a wedged --assemble is given up on and retried. The CLI can
# HANG as well as crash: observed 2026-08-11 on the 8-part glass tile, a single
# invocation running 16 minutes and producing nothing, where a successful one
# takes well under a minute. The crash retry below cannot see that, because it
# waits on a process that never exits -- so the check simply never returns,
# which on a pre-print gate is worse than failing.
#
# Do NOT diagnose this by CPU usage. `ps` reported 0.0 % throughout the hung
# run, which looked conclusive -- and then reported 0.0 % throughout a run that
# completed normally minutes later. Elapsed time on one invocation is the
# signal; the CPU reading is not.
ASSEMBLE_TIMEOUT = 300


def assemble(stls, wd, out, mp, pp, fp, timeout=ASSEMBLE_TIMEOUT):
    """Merge the levels into one multi-part object and return the 3mf path.

    Retries the same upstream CLI segfault run_slice handles -- --assemble goes
    through the identical --load-filaments parsing, so it can die before doing
    any work. Less exposed than the slice, because it is handed one filament
    profile rather than N, but it is the same defect and a bare
    "--assemble produced no 3mf" is just as undiagnosable.

    A HANG is retried on the same budget -- see ASSEMBLE_TIMEOUT.
    """
    p = os.path.join(out, "asm.3mf")
    for attempt in range(1, CRASH_RETRIES + 1):
        if os.path.exists(p):
            os.remove(p)
        try:
            proc = subprocess.run(
                [STUDIO, "--load-settings", f"{mp};{pp}", "--load-filaments", fp,
                 "--assemble", "--outputdir", out, "--export-3mf", "asm.3mf"] + stls,
                capture_output=True, text=True, cwd=wd, timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"    Bambu CLI HUNG in --assemble ({timeout}s, no output) -- "
                  f"killed, retrying ({attempt}/{CRASH_RETRIES})")
            continue
        if os.path.exists(p):
            return p
        if proc.returncode >= 0:
            return None                      # a real failure, not the crash
    return None


def one_filament_per_part(src, dst, n):
    """Rewrite the 3mf so part k prints in filament k.

    --assemble puts every part on extruder 1 and declares a single filament, so
    editing the per-part extruder alone gets clamped straight back to 1. Both
    halves of the project have to agree.
    """
    order = []
    with zipfile.ZipFile(src) as zin, \
         zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            data = zin.read(name)
            if name.endswith("model_settings.config"):
                chunks = re.split(r'(<part\b)', data.decode())
                k = 0
                for i in range(1, len(chunks), 2):
                    body = chunks[i + 1]; k += 1
                    nm = re.search(r'key="name" value="([^"]+)"', body)
                    order.append(nm.group(1) if nm else f"part{k}")
                    chunks[i + 1] = re.sub(r'(key="extruder" value=")\d+(")',
                                           rf'\g<1>{k}\g<2>', body, count=1)
                data = "".join(chunks).encode()
            elif name.endswith("project_settings.config"):
                cfg = json.loads(data)
                for key, val in list(cfg.items()):
                    if key.startswith("filament_") and isinstance(val, list) and len(val) == 1:
                        cfg[key] = val * n
                cfg["filament_colour"] = PALETTE[:n]
                cfg["filament_self_index"] = [str(i + 1) for i in range(n)]
                cfg["filament_map"] = ["1"] * n
                cfg["filament_map_mode"] = "Manual"
                if isinstance(cfg.get("flush_volumes_matrix"), list):
                    cfg["flush_volumes_matrix"] = ["0" if i // n == i % n else "280"
                                                   for i in range(n * n)]
                if isinstance(cfg.get("flush_volumes_vector"), list):
                    cfg["flush_volumes_vector"] = ["140"] * n
                data = json.dumps(cfg).encode()
            zout.writestr(name, data)
    return order


def used_filaments(path):
    """The slicer's own list of which filaments extruded, 0-indexed, or None.

    Bambu writes "; filament: 1,3,4" in the header block -- 1-indexed, ascending,
    and only the ones that actually laid material. It is an answer to this
    script's central question arrived at independently of anything measured
    here, which is precisely what makes it worth comparing against.
    """
    for line in open(path):
        s = line.strip()
        if s.startswith("; filament:"):
            try:
                return {int(v) - 1 for v in s.split(":", 1)[1].split(",")}
            except ValueError:
                return None
        if s.startswith("; EXECUTABLE_BLOCK_START"):
            break                                 # past the header, stop reading
    return None


def initial_tool(path, n):
    """Which filament is loaded before the first explicit T command.

    NOT necessarily tool 0 -- see the note at the top of this file. Resolved
    rather than assumed, and without looking at any geometry:

    Within one layer Bambu emits an explicit T for every tool it uses EXCEPT
    the one already loaded. So the tool loaded at the start of layer 1 is the
    one missing from layer 1's explicit selections.

    If a part prints nothing it is missing from those selections too, so two
    candidates can survive. Three further facts separate them, in order:

      the header's `; filament:` line -- the slicer's own list of which
      filaments it actually used, 1-indexed. A part that laid nothing cannot
      own the opening block. This is the only signal left when NO tool change
      happens at all: a two-part stack whose second part vanishes never changes
      tool, and then `; filament: 1` is the whole story. (It is sorted
      ascending, not print order, so it narrows the field but never names the
      opener by itself.)

      a tool that PRINTED but is never named by any T command -- this one is
      exact rather than a heuristic. The only way extrusions can exist for a
      tool that was never selected is for it to have been loaded from the
      start, and only one tool can be. It is what resolves the medallion, whose
      body prints the first forty layers alone and is finished before the first
      tool change ever happens, so it is never named.

      failing both, ARITHMETIC ON THE SLICER'S OWN TOTALS. Sum the extrusion
      per tool, leaving the opening block unattributed, and exactly one
      candidate's shortfall against its header total is the size of that block.
      This is the colour ladder's case and it is the general one: layer 1 there
      has no tool change at all (only the clear base prints that low), and the
      base IS named on later layers, so neither rule above fires.

    All three are exact rather than heuristics -- the third compares against
    figures Bambu computed independently of anything measured here. A fourth was
    written and deleted: rasterise the opening block and match it against each
    candidate's labelled extrusions, which scores 0.98 for the came and 0.00 for
    everything else on the pane-7 tile. The mass rule covers the same cases with
    no thresholds to tune, so the raster is in this file's history if it is ever
    wanted again.

    One rule was tried here and removed as unsound: "narrow to tools named
    somewhere in the file, since the opener gets named again as the order
    rotates." It is false whenever the opening part finishes before the first
    tool change, and it does not merely fail to help -- it eliminates the right
    answer. On the medallion it discarded T0, the body, which is the opener.

    -> (tool, why) or (None, why) when it genuinely cannot be told.
    """
    layer1, everywhere, used, total_mm = set(), set(), None, []
    layer = 0
    for line in open(path):
        s = line.strip()
        if s.startswith(";"):
            if s.startswith("; filament:"):
                try:
                    used = {int(v) - 1 for v in s.split(":", 1)[1].split(",")}
                except ValueError:
                    used = None
            elif "total filament length [mm]" in s:
                try:
                    total_mm = [float(v) for v in s.split(":", 1)[1].split(",")]
                except ValueError:
                    total_mm = []
            elif s.startswith("; CHANGE_LAYER"):
                layer += 1
            continue
        m = re.fullmatch(r"T(\d+)", s.split(";")[0].strip())
        if not m:
            continue
        t = int(m.group(1))
        if t == 255:                          # 255 is "no tool", not a filament
            continue
        everywhere.add(t)
        if layer <= 1:
            layer1.add(t)

    if used is not None:
        unnamed = used - everywhere
        if len(unnamed) == 1:
            t = unnamed.pop()
            return t, (f"T{t} printed but is never named by a T command, so it "
                       f"was loaded from the start")

    cand = set(range(n)) - layer1
    if len(cand) > 1 and used and (cand & used):
        cand &= used
    if len(cand) == 1:
        return cand.pop(), ""

    if used is not None and total_mm:
        got, note = _owner_by_mass(path, cand or set(used), used, total_mm)
        if got is not None:
            return got, note

    return None, (f"cannot tell which filament is loaded before the first tool "
                  f"change: candidates {sorted(cand) or 'none'}")


# How far a candidate's accounted filament may miss its header total and still
# count as a match, as a fraction. Generous: the question is which of several
# tools is short by the size of a whole opening layer, not a precision audit.
MASS_TOL = 0.02


def _owner_by_mass(path, cand, used, total_mm, tol=MASS_TOL):
    """Whose books balance only if the opening block is theirs.

    Sum extrusion per tool with the opening block left unattributed, then ask
    which candidate's labelled total falls short of the slicer's own header
    figure by exactly that block. On the colour ladder the clear base measures
    3.68 g against a header 9.92 g, and the unattributed block is 6.25 g -- the
    other two tools balance already and adding the block to either overshoots
    by threefold.

    E is relative (M83) so these are NET sums, retractions included, and G2/G3
    arcs count: Bambu emits them by default and ignoring them loses 8 % (both
    lessons are purgecheck's, learned against this same header).
    """
    by, unlabelled, tool = {}, 0.0, None
    for line in open(path):
        code = line.split(";")[0].strip()
        m = re.fullmatch(r"T(\d+)", code)
        if m:
            t = int(m.group(1))
            if t != 255:
                tool = t
            continue
        if not code.startswith(("G1", "G0", "G2", "G3")):
            continue
        for tok in code.split()[1:]:
            if tok[:1] == "E":
                try:
                    e = float(tok[1:])
                except ValueError:
                    continue
                if tool is None:
                    unlabelled += e
                else:
                    by[tool] = by.get(tool, 0.0) + e
    if unlabelled <= 0:
        return None, ""

    header = dict(zip(sorted(used), total_mm)) if len(used) == len(total_mm) else {}
    if not header:
        return None, ""

    scored = []
    for t in sorted(cand):
        if t not in header or header[t] <= 0:
            continue
        scored.append((abs(by.get(t, 0.0) + unlabelled - header[t]) / header[t], t))
    scored.sort()
    if not scored:
        return None, ""
    best = scored[0]
    runner = scored[1] if len(scored) > 1 else (float("inf"), None)
    if best[0] <= tol and runner[0] > tol:
        return best[1], (f"T{best[1]}'s accounted filament is short by exactly the "
                         f"unlabelled opening block ({unlabelled:.0f} mm); it balances "
                         f"to {best[0]:.1%} where the next best misses by {runner[0]:.0%}")
    return None, ""


def read_gcode(path, centre, initial=0):
    """-> {z: {tool: [points, rmin, rmax]}}, tools_seen.

    `initial` is the tool loaded before the first explicit T -- resolve it with
    initial_tool() rather than passing 0, which is a guess that is often wrong.
    Pass None and the unlabelled extrusions bucket under a None key instead of
    being silently attributed to a filament that did not lay them.
    """
    tool, x, y, z = initial, 0.0, 0.0, 0.0
    per, seen = {}, set()
    for line in open(path):
        s = line.split(";")[0].strip()
        m = re.fullmatch(r"T(\d+)", s)
        if m:
            t = int(m.group(1))
            if t != 255:
                tool = t; seen.add(t)
            continue
        if not s.startswith(("G1", "G0")):
            continue
        nx, ny, nz, e = x, y, z, None
        for p in s.split()[1:]:
            c, v = p[:1], p[1:]
            try:
                if c == "X": nx = float(v)
                elif c == "Y": ny = float(v)
                elif c == "Z": nz = float(v)
                elif c == "E": e = float(v)
            except ValueError:
                pass
        if e is not None and e > 0 and (nx != x or ny != y):
            r0 = math.hypot(x - centre[0], y - centre[1])
            r1 = math.hypot(nx - centre[0], ny - centre[1])
            if min(r0, r1) < 60.0:          # ignore the prime tower / purge
                d = per.setdefault(round(nz, 2), {}).setdefault(tool, [0, 1e9, -1e9])
                for r in (r0, r1):
                    d[0] += 1
                    d[1] = min(d[1], r); d[2] = max(d[2], r)
                seen.add(tool)
        x, y, z = nx, ny, nz
    return per, seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern")
    ap.add_argument("--layers", default=None, help="zmin:zmax layer dump")
    ap.add_argument("--centre", default="128,128")
    a = ap.parse_args()

    stls = [os.path.abspath(p) for p in sorted(glob.glob(a.pattern))]
    if len(stls) < 2:
        raise SystemExit(f"need at least two levels, matched {len(stls)}")
    if not os.path.exists(STUDIO):
        raise SystemExit(f"Bambu Studio not found at {STUDIO}")
    centre = tuple(float(v) for v in a.centre.split(","))
    n = len(stls)

    # Registered at creation rather than removed at the end: this function exits
    # through several SystemExits (slicer error, refusing to report) and each one
    # used to leak the whole working directory. 113 of them, 333 MB, by
    # 2026-08-11. atexit covers every path including the raises.
    wd = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, wd, ignore_errors=True)
    out = os.path.join(wd, "out"); os.makedirs(out)
    mp = write_profile(flatten("machine", MACHINE), os.path.join(wd, "m.json"))
    pp = write_profile(flatten("process", PROCESS), os.path.join(wd, "p.json"),
                       layer_height="0.12", sparse_infill_density="99%",
                       curr_bed_type=BED_TYPE, enable_support="0")
    fil = flatten("filament", FILAMENT)
    fps = [write_profile(fil, os.path.join(wd, f"f{i+1}.json")) for i in range(n)]

    src = assemble(stls, wd, out, mp, pp, fps[0])
    if not src:
        raise SystemExit("--assemble produced no 3mf")
    edited = os.path.join(wd, "multi.3mf")
    order = one_filament_per_part(src, edited, n)

    for fn in os.listdir(out):
        os.remove(os.path.join(out, fn))
    g = os.path.join(out, "plate_1.gcode")
    # run_slice retries the upstream CLI segfault and ONLY that -- see the note
    # above it in slicecheck.py. Before 2026-08-10 this call was a bare
    # subprocess.run whose output was discarded, so the crash surfaced as a bare
    # "no gcode produced" about one run in four, with nothing to diagnose it by.
    _proc, attempts = run_slice(
        [STUDIO, "--load-settings", f"{mp};{pp}",
         "--load-filaments", ";".join(fps),
         "--slice", "0", "--outputdir", out, edited],
        g, cwd=wd, log=print)
    if attempts > 1:
        print(f"    (sliced on attempt {attempts} -- upstream CLI crash, not this part)")

    rj = os.path.join(out, "result.json")
    if os.path.exists(rj):
        j = json.load(open(rj))
        if j.get("return_code", 0) != 0:
            raise SystemExit(f"slicer error: {j.get('error_string','?')}")

    init, why = initial_tool(g, n)
    per, seen = read_gcode(g, centre, init)
    if init is None:
        if any(None in v for v in per.values()):
            raise SystemExit(
                f"REFUSING TO REPORT -- {why}.\n"
                "Everything before the first tool change belongs to an unknown\n"
                "filament. Booking it to filament 1 is exactly what made #23\n"
                "read as a came missing from the tile's viewing face, so a\n"
                "confident wrong answer here is worse than no answer.")
    else:
        print(f"layer 1 opens on filament {init + 1} (T{init}), before any tool "
              f"change -- Bambu chooses this, it is not always filament 1")
        if why:
            print(f"  ({why})")

    # The slicer's own verdict on this script's central question, reached
    # independently of anything measured here. Ours is a raster of extrusion
    # points inside r < 60 of the plate centre; a level printing only outside
    # that ring, or lost to a parsing slip, would read as vanished. Bambu's
    # "; filament:" cannot be wrong about whether a filament extruded, so a
    # disagreement means OUR answer is suspect -- and this script exists
    # because a check that quietly examines nothing is this project's
    # characteristic failure.
    used = used_filaments(g)

    print(f"\n{n} levels, in the order the slicer resolves overlaps "
          f"(later wins):\n")
    bad, disputed = 0, []
    for k, nm in enumerate(order, start=1):
        tool = k - 1
        pts = sum(v[tool][0] for v in per.values() if tool in v)
        if used is not None and (pts == 0) != (tool not in used):
            disputed.append((k, nm, tool, pts))
        if pts == 0:
            bad += 1
            print(f"  {k}. {nm:26s}  T{tool}   <-- PRINTS NOTHING")
        else:
            zs = [z for z, v in per.items() if tool in v]
            rs = [v[tool] for v in per.values() if tool in v]
            print(f"  {k}. {nm:26s}  T{tool}   {pts:6d} pts   "
                  f"z {min(zs):5.2f}..{max(zs):5.2f}   "
                  f"r {min(r[1] for r in rs):5.2f}..{max(r[2] for r in rs):5.2f}")

    if a.layers:
        z0, z1 = (float(v) for v in a.layers.split(":"))
        print(f"\nlayers {z0}..{z1}:")
        for z in sorted(per):
            if z0 <= z <= z1:
                cells = "  ".join(
                    f"T{t}:{v[0]:4d}pts r={v[1]:5.2f}..{v[2]:5.2f}"
                    for t, v in sorted(per[z].items()))
                print(f"  z={z:5.2f}   {cells}")

    if disputed:
        print("\n  !! THE SLICER DISAGREES WITH THIS CHECK, so do not trust the "
              "lines above:")
        for k, nm, tool, pts in disputed:
            ours = "nothing" if pts == 0 else f"{pts} pts"
            theirs = "extruded" if tool in used else "did not extrude"
            print(f"       {k}. {nm:26s} T{tool}  we found {ours}, "
                  f"the header says it {theirs}")
        print("     \"; filament:\" cannot be wrong about whether a filament laid\n"
              "     material, so the fault is here -- most likely the r < 60 mm\n"
              "     window in read_gcode, which is meant to exclude only the\n"
              "     prime tower.")
    elif used is not None:
        print(f"\n  (agrees with the slicer's own \"; filament:\" list)")

    print(f"\n{n} levels, {bad} printing nothing")
    if bad:
        print("A level that slices to nothing passes watertight, on-bed, island,\n"
              "cantilever and overhang checks alike. Check its narrowest feature\n"
              "against the extrusion width.")
    # A dispute fails the run too. It does not mean the geometry is wrong -- it
    # means this script's answer about the geometry cannot be relied on, which
    # is the more dangerous of the two to pass green.
    return 1 if (bad or disputed) else 0


if __name__ == "__main__":
    sys.exit(main())
