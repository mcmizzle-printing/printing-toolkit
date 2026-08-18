#!/usr/bin/env python3
"""Measure what a multi-colour plate actually WASTES, instead of estimating it.

WHY THIS EXISTS (issue #11). Every purge figure this project has quoted was
arithmetic: ~0.6 g per tool change, ~106 g per plate at full-thickness colour,
~34 g with a 0.60 mm skin. Those numbers are the entire justification for the
clear-base scheme -- print a tile as clear with a thin skin of colour on top,
accepting ~23 % of the saturation, in exchange for far fewer tool changes.

That is a large design decision resting on a number nobody has measured.

WHAT IT MEASURES, off the real gcode:

  purge     extrusion between "; FLUSH_START" and "; FLUSH_END" -- filament
            pushed through purely to change colour. This is the waste.
  tower     the prime tower. Also waste, and #16 claims front-loading the
            colour shrinks it because the tower stops at the last tool change.
  part      everything else. The thing you actually wanted.

All three in grams, from summed extruder moves, cross-checked against the
slicer's own "total filament weight [g]" header. If those disagree by more than
a few percent the parser is wrong and the run says so rather than reporting a
confident wrong number.

THE PROPERTY THAT MATTERS. Purge is per-layer-per-colour and INDEPENDENT of how
many copies are on the plate: changing from red to blue costs the same whether
one tile needs it or forty do. That is the whole argument for filling the plate,
and `--copies` tests it directly rather than taking it on trust.

    python3 tests/purgecheck.py 'out/colour-ladder/*.stl'
    python3 tests/purgecheck.py 'out/colour-ladder/*.stl' --copies 4

Levels are one file per filament, sorted by name, exactly as stackcheck.py takes
them -- the two tools slice the same way, so their numbers are comparable.
"""
import argparse, atexit, glob, os, re, shutil, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "printing-toolkit", "tests")))
from slicecheck import (flatten, write_profile, run_slice, STUDIO, MACHINE,
                        PROCESS, FILAMENT, BED_TYPE)
from stackcheck import assemble, one_filament_per_part, initial_tool

# THE PURGE PER CHANGE IS AN INPUT, NOT A MEASUREMENT -- read this before
# quoting any gram figure from this tool.
#
# stackcheck.py rewrites flush_volumes_matrix to 280 mm^3 so that flushing is
# visible at all. Slice with that and the reported purge comes back as
# changes x 280 mm^3 x density, exactly: 17 changes gave 6.05 g, and
# 280 mm^3 x 1.25 g/cm^3 = 0.350 g/change. That is our own setting handed back
# to us, which is the same shape of defect as a check that examines nothing.
#
# Bambu computes the real matrix from the COLOUR PAIR -- black into clear costs
# far more than red into orange -- and the CLI has no access to that, so it has
# to be supplied. It is therefore surfaced as --flush and printed in the header
# of every run.
#
# What this tool genuinely measures is the TOOL-CHANGE COUNT, the part mass and
# the tower mass. Since purge = changes x flush x density, and the two schemes
# under test differ only in how many changes they need, the change count is the
# decision variable -- and that is real.
FLUSH_MM3 = 280

# Grams per mm of filament is NOT hardcoded. The gcode header carries both
# "total filament length [mm]" and "total filament weight [g]", so the true
# figure is derivable from the run itself -- which also picks up the profile's
# own density rather than an assumed 1.27 g/cm^3. Assuming it was 1.6 % off.
G_PER_MM_FALLBACK = 0.003055

# Above this disagreement with the slicer's own header total, refuse to report.
TOLERANCE = 0.05


def measure(path, n=None):
    """-> dict of grams by category, tool changes, and the header's own totals.

    E is relative (M83), so every bucket is a NET sum -- retractions included.
    Counting only positive E overshoots the slicer's own total by ~9 %, because
    every deretraction is added back while the matching retraction is ignored;
    the filament never actually left the nozzle. Both parser bugs found here
    were caught by the header cross-check, which is the whole reason it exists:

      G0/G1 only          -8.3 %   Bambu emits G2/G3 arcs by default
      positive E only     +9.4 %   retract/deretract pairs counted once each

    Pass `n` (the number of filaments) to also get the PER-EXTRUDER split, which
    is what says which colour is eating a spool rather than how much the plate
    costs in total. It needs to know which tool is loaded before the first tool
    change -- see stackcheck.initial_tool, and issue #23 for what assuming that
    costs. Without `n` the aggregate figures are unchanged and `by_tool` is None.
    """
    purge_mm = tower_mm = part_mm = 0.0
    changes = 0
    in_flush = False
    feature = ""
    header_g, header_mm, used = [], [], []

    tool = None
    if n is not None:
        tool, _why = initial_tool(path, n)
    by_tool = {} if n is not None else None

    for line in open(path):
        if line.startswith(";"):
            s = line.strip()
            if s == "; FLUSH_START":
                in_flush = True
            elif s == "; FLUSH_END":
                in_flush = False
            elif s.upper().startswith(("; FEATURE:", ";TYPE:")):
                feature = s.split(":", 1)[1].strip().lower()
            elif "total filament weight [g]" in s:
                header_g = [float(v) for v in s.split(":", 1)[1].split(",")]
            elif "total filament length [mm]" in s:
                header_mm = [float(v) for v in s.split(":", 1)[1].split(",")]
            elif s.startswith("; filament:"):
                used = [int(v) - 1 for v in s.split(":", 1)[1].split(",")]
            continue

        code = line.split(";")[0].strip()
        if re.fullmatch(r"T\d+", code):
            if code != "T255":
                changes += 1
                tool = int(code[1:])
            continue
        if not code.startswith(("G1", "G0", "G2", "G3")):
            continue
        e = None
        for tok in code.split()[1:]:
            if tok[:1] == "E":
                try:
                    e = float(tok[1:])
                except ValueError:
                    pass
        if e is None:
            continue
        if in_flush:
            purge_mm += e
            bucket = "purge"
        elif "prime tower" in feature or "wipe tower" in feature:
            tower_mm += e
            bucket = "tower"
        else:
            part_mm += e
            bucket = "part"
        if by_tool is not None:
            by_tool.setdefault(tool, {"part": 0.0, "purge": 0.0, "tower": 0.0})
            by_tool[tool][bucket] += e

    gpm = (sum(header_g) / sum(header_mm)) if (header_g and header_mm
                                               and sum(header_mm)) else G_PER_MM_FALLBACK
    if by_tool is not None:
        by_tool = {t: {k: v * gpm for k, v in d.items()} for t, d in by_tool.items()}
    return {
        "purge": purge_mm * gpm,
        "tower": tower_mm * gpm,
        "part":  part_mm * gpm,
        "changes": changes,
        "g_per_mm": gpm,
        "header_total": sum(header_g) if header_g else None,
        "by_tool": by_tool,
        "header_by_tool": header_by_tool(used, header_g),
    }


def header_by_tool(used, header_g):
    """Pair the header's per-extruder weights with the extruders they belong to.

    THE HEADER ONLY LISTS EXTRUDERS THAT PRINTED, so the k-th weight is not
    extruder k. A two-filament plate whose second part slices to nothing emits

        ; filament: 1
        ; total filament weight [g] : 1.21

    -- one value for two filaments. Indexing that list positionally silently
    attributes every gram to the wrong spool the moment any filament goes
    unused, which on this project is not an edge case: it is what a level that
    prints nothing looks like, and catching those is why these tools exist.

    "; filament:" is 1-indexed and ascending, so zipping the two is exact.
    """
    if not used or not header_g or len(used) != len(header_g):
        return None
    return dict(zip(sorted(used), header_g))


def slice_levels(stls, copies, layer, infill, flush=FLUSH_MM3):
    # One working directory per slice, and there are two slices per run
    # (1 copy and N). Registered at creation for the same reason stackcheck does
    # it: the caller reads the gcode out of here afterwards, so it cannot be
    # removed on the way out of this function.
    wd = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, wd, ignore_errors=True)
    out = os.path.join(wd, "out"); os.makedirs(out)
    n = len(stls)
    mp = write_profile(flatten("machine", MACHINE), os.path.join(wd, "m.json"))
    pp = write_profile(flatten("process", PROCESS), os.path.join(wd, "p.json"),
                       layer_height=str(layer), sparse_infill_density=f"{infill}%",
                       curr_bed_type=BED_TYPE, enable_support="0")
    fil = flatten("filament", FILAMENT)
    fps = [write_profile(fil, os.path.join(wd, f"f{i+1}.json")) for i in range(n)]

    src = assemble(stls, wd, out, mp, pp, fps[0])
    if not src:
        raise SystemExit("--assemble produced no 3mf")
    edited = os.path.join(wd, "multi.3mf")
    one_filament_per_part(src, edited, n)
    _set_flush(edited, n, flush)

    for fn in os.listdir(out):
        os.remove(os.path.join(out, fn))
    g = os.path.join(out, "plate_1.gcode")
    # --repetitions is rejected alongside "--slice 0" (slice all plates):
    #   "Invalid params: can not set repetitions when slice all"
    # so the multi-copy runs target plate 1 explicitly. There is only ever one
    # plate here, so the two forms are equivalent apart from that restriction.
    plate = "1" if copies > 1 else "0"
    cmd = [STUDIO, "--load-settings", f"{mp};{pp}",
           "--load-filaments", ";".join(fps)]
    if copies > 1:
        cmd += ["--repetitions", str(copies)]
    cmd += ["--slice", plate, "--outputdir", out, edited]
    run_slice(cmd, g, cwd=wd)
    return g


def _set_flush(path, n, mm3):
    """Overwrite the flush matrix so the assumption is this tool's, not stackcheck's."""
    import zipfile, json as _json, shutil
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            data = zin.read(name)
            if name.endswith("project_settings.config"):
                cfg = _json.loads(data)
                cfg["flush_volumes_matrix"] = ["0" if i // n == i % n else str(mm3)
                                               for i in range(n * n)]
                cfg["flush_volumes_vector"] = [str(mm3 // 2)] * n
                data = _json.dumps(cfg).encode()
            zout.writestr(name, data)
    shutil.move(tmp, path)


def report(tag, m, names=None):
    waste = m["purge"] + m["tower"]
    total = waste + m["part"]
    print(f"  {tag:22s} part {m['part']:7.2f} g   purge {m['purge']:7.2f} g   "
          f"tower {m['tower']:6.2f} g   waste {waste:7.2f} g "
          f"({100*waste/total if total else 0:5.1f} %)   {m['changes']:4d} changes")
    if m["header_total"] is not None:
        err = abs(total - m["header_total"]) / max(m["header_total"], 1e-9)
        if err > TOLERANCE:
            print(f"      <-- PARSER DISAGREES with the slicer: summed {total:.2f} g "
                  f"vs header {m['header_total']:.2f} g ({100*err:.1f} %). "
                  f"Do not trust the split above.")
    per_extruder(m, names)
    return m


def per_extruder(m, names=None):
    """Which SPOOL each gram came off, not just what the plate cost.

    The aggregate answers "is the clear-base scheme worth it". This answers
    "which colour do I have to buy two of" -- on a small production run a 1 kg
    spool can last years, so the only colour that can break that rule is one
    carrying far more than its share.

    Cross-checked per extruder against the slicer's own header, not just in
    total: a summed figure can be right while the split is wrong, and the split
    is the part being added here.
    """
    by = m.get("by_tool")
    if not by:
        return
    hdr = m.get("header_by_tool") or {}
    print()
    for t in sorted(k for k in by if k is not None):
        d = by[t]
        tot = d["part"] + d["purge"] + d["tower"]
        nm = ""
        if names and t < len(names):
            nm = os.path.basename(names[t])[:30]
        line = (f"      T{t}  {nm:32s} part {d['part']:6.2f} g  "
                f"purge {d['purge']:6.2f} g  tower {d['tower']:5.2f} g  "
                f"= {tot:6.2f} g")
        if t in hdr:
            err = abs(tot - hdr[t]) / max(hdr[t], 1e-9)
            line += f"   (header {hdr[t]:6.2f} g{'' if err <= TOLERANCE else '  <-- MISMATCH'})"
        print(line)
    if None in by:
        d = by[None]
        print(f"      T?  {'UNATTRIBUTED':32s} part {d['part']:6.2f} g  "
              f"purge {d['purge']:6.2f} g  tower {d['tower']:5.2f} g"
              f"   <-- opening tool unresolved, see stackcheck.initial_tool")
    if not hdr:
        print("      (no per-extruder header totals to check the split against)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pattern")
    ap.add_argument("--copies", type=int, default=1)
    ap.add_argument("--layer", type=float, default=0.12)
    ap.add_argument("--infill", type=int, default=99)
    ap.add_argument("--flush", type=int, default=FLUSH_MM3,
                    help="mm^3 purged per colour change. AN ASSUMPTION, not a "
                         "measurement -- purge scales linearly with it")
    a = ap.parse_args()

    stls = [os.path.abspath(p) for p in sorted(glob.glob(a.pattern))]
    if len(stls) < 2:
        raise SystemExit(f"need at least two levels, matched {len(stls)}")
    if not os.path.exists(STUDIO):
        raise SystemExit(f"Bambu Studio not found at {STUDIO}")

    print(f"{len(stls)} filaments, {a.layer} mm, {a.infill} % infill, "
          f"flush {a.flush} mm^3 per change (ASSUMED -- purge scales linearly with it)\n")
    rows = []
    for c in sorted({1, a.copies}):
        m = measure(slice_levels(stls, c, a.layer, a.infill, a.flush), len(stls))
        report(f"{c} cop{'y' if c == 1 else 'ies'}", m, stls)
        rows.append((c, m))
    print()
    for c, m in rows:
        w = m["purge"] + m["tower"]
        print(f"  {c:3d} cop{'y ' if c == 1 else 'ies'}  {m['changes']:4d} changes   "
              f"waste {w:6.2f} g total = {w/c:5.2f} g per copy   "
              f"part {m['part']/c:5.2f} g per copy")
    if len(rows) > 1:
        c0, m0 = rows[0]; c1, m1 = rows[-1]
        same = abs(m1["changes"] - m0["changes"]) <= max(1, 0.05 * m0["changes"])
        print(f"\n  Tool changes {'DID NOT scale' if same else 'SCALED'} with copy count "
              f"({m0['changes']} -> {m1['changes']} for {c0} -> {c1} copies).")
        print("  " + ("Purge is per-layer-per-colour, so filling the plate is free. Confirmed."
                      if same else
                      "That contradicts the per-layer-per-colour assumption -- investigate."))


if __name__ == "__main__":
    main()
