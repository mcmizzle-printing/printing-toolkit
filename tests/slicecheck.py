#!/usr/bin/env python3
"""Slice each STL headlessly with Bambu Studio and report what the slicer thinks.

The other two checks are our own opinion about the geometry. This one is the
slicer's, from the same engine that flagged the rib3 cantilever after
check_all.py and islands.py had both passed it.

Supports are forced OFF, deliberately. The question this answers is not "can
this be printed" -- with enough support material anything can. It is "does this
print unsupported", which is the actual design constraint.

Two signals, in order of trust:

  warning_message  -- Bambu's own floating-region detector, e.g. "It seems object
                      X has floating regions. Please re-orient the object or
                      enable support generation." Always a hard fail. This is
                      what named rib3's female channel after both of the other
                      two checks passed it.

  Overhang wall    -- seconds of perimeter laid over air, as a share of extrusion
                      time. A chamfer or a detent produces a little; a protrusion
                      starting in mid-air produces roughly thirty times as much.

Bridge time is reported but never fails a part: a bridge is anchored at both ends
and prints fine. Lumping it in with overhang flags the full-thickness jigsaw,
which is one of the few joints on this project that has actually been printed,
handled, and judged good.

Bundled Bambu profiles are stubs chained together by an "inherits" key, and the
CLI does NOT resolve that chain -- hand it "0.12mm High Quality @BBL P2S.json"
and it silently slices at the 0.20 mm default. Every profile here is flattened
before use, which is why this script exists at all rather than being one line of
shell.
"""
import argparse, glob, json, os, shutil, subprocess, sys, tempfile

STUDIO = "/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"
PROFILES = "/Applications/BambuStudio.app/Contents/Resources/profiles/BBL"

MACHINE  = "Bambu Lab P2S 0.4 nozzle"
PROCESS  = "0.12mm High Quality @BBL P2S"
FILAMENT = "Bambu PETG Translucent @BBL P2S 0.4 nozzle"

# The profiles default to Cool Plate, which PETG is not compatible with -- the
# slice aborts with return_code -61 before producing any geometry report.
BED_TYPE = "Textured PEI Plate"

# The CLI's config validator rejects sparse_infill_density of 100 (and "100%")
# with a bare return_code -18 and no indication of which key was at fault; 99 is
# accepted. Tiles still print at 100 % in the GUI -- this cap applies only to the
# check run, where infill density does not affect the overhang measurement.
MAX_INFILL = 99

# Share of extrusion time spent on overhang perimeter that trips a failure.
# Calibrated against four parts on 2026-08-04: butterfly keys 0.02 %, the jigsaw
# that actually printed 0.00 %, rib3's female channel 0.00 % (caught instead by
# the floating-region warning), rib3's cantilevered male rail 0.79 %. Bridge time
# is deliberately excluded -- a bridge is anchored at both ends and prints fine;
# the jigsaw spends 70 s bridging its pocket and is one of the few joints here
# that has been printed and handled successfully.
OVERHANG_PCT = 0.30


def flatten(kind, name, _seen=None):
    """Resolve a profile's `inherits` chain into one flat dict.

    Child keys win over parent keys. Returns the merged config with the
    bookkeeping fields stripped, since the CLI rejects a dangling `inherits`.
    """
    _seen = _seen or set()
    if name in _seen:
        raise SystemExit(f"circular inherits at {name}")
    _seen.add(name)

    path = os.path.join(PROFILES, kind, f"{name}.json")
    if not os.path.exists(path):
        raise SystemExit(f"no {kind} profile named {name!r} under {PROFILES}")
    with open(path) as f:
        cfg = json.load(f)

    parent_name = cfg.pop("inherits", None)
    if parent_name:
        parent = flatten(kind, parent_name, _seen)
        parent.update(cfg)
        cfg = parent
    return cfg


def write_profile(cfg, path, **overrides):
    cfg = dict(cfg)
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    cfg.pop("inherits", None)
    with open(path, "w") as f:
        json.dump(cfg, f)
    return path


# Bambu Studio's CLI crashes intermittently in
# Slic3r::convert_filament_preset_name while parsing --load-filaments, BEFORE
# slicing starts, leaving no result.json and no gcode.
#
# Diagnosed 2026-08-10 from two macOS crash reports on BambuStudio 02.07.01.62,
# arm64: identical stack every time --
#
#     _platform_memmove
#     std::basic_string::basic_string(const&)
#     Slic3r::convert_filament_preset_name(std::string&, std::string&)
#     Slic3r::CLI::run(int, char**)
#
# EXC_BAD_ACCESS, KERN_INVALID_ADDRESS at 0x0. Same code path, different signals
# across runs (SIGSEGV and SIGBUS observed back to back), which is the signature
# of an UNINITIALISED READ rather than a race in the caller. Roughly 1 run in 4
# on the multi-filament path; the single-filament path is far less exposed.
#
# Nothing in the config prevents it. `filament_settings_id` arrives as [''] and
# looked like the culprit; setting it to the preset name made no difference
# across trials. Treat it as an upstream defect.
#
# A crash is distinguishable from a real failure BY THE RETURN CODE: negative
# means killed by a signal. Retry those and only those. A non-negative exit with
# no output is a genuine error -- a bad profile, an unsliceable model -- and must
# be reported rather than retried, or this helper becomes the thing that hides
# real breakage.
CRASH_RETRIES = 5


def run_slice(cmd, gcode_path, cwd=None, retries=CRASH_RETRIES, log=None):
    """Run the Bambu CLI until it emits `gcode_path`, retrying ONLY crashes.

    Returns (proc, attempts). Raises SystemExit, carrying the slicer's own
    output, if the CLI exits cleanly without producing anything -- that is a
    real failure and is not retried.
    """
    for attempt in range(1, retries + 1):
        if os.path.exists(gcode_path):
            os.remove(gcode_path)
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        if os.path.exists(gcode_path):
            return proc, attempt
        if proc.returncode < 0:
            if log:
                log(f"    Bambu CLI crashed (signal {-proc.returncode}) in "
                    f"convert_filament_preset_name -- upstream, retrying "
                    f"({attempt}/{retries})")
            continue
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        raise SystemExit(
            f"slicer exited {proc.returncode} without producing "
            f"{os.path.basename(gcode_path)}\n    " +
            ("  ".join(tail) or "(slicer produced no output)"))
    raise SystemExit(
        f"Bambu CLI crashed {retries} times running the same command. That is "
        f"far above the ~1-in-4 rate of the known upstream segfault, so treat "
        f"it as a real problem rather than the usual flake.")


def slice_one(stl, workdir, layer, infill, supports):
    machine  = flatten("machine",  MACHINE)
    process  = flatten("process",  PROCESS)
    filament = flatten("filament", FILAMENT)

    mp = write_profile(machine, os.path.join(workdir, "machine.json"))
    pp = write_profile(process, os.path.join(workdir, "process.json"),
                       layer_height=str(layer),
                       sparse_infill_density=f"{min(infill, MAX_INFILL)}%",
                       curr_bed_type=BED_TYPE,
                       enable_support="0" if not supports else "1")
    fp = write_profile(filament, os.path.join(workdir, "filament.json"))

    out = os.path.join(workdir, "out")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)

    cmd = [STUDIO, "--load-settings", f"{mp};{pp}", "--load-filaments", fp,
           "--slice", "0", "--outputdir", out,
           "--export-3mf", os.path.basename(stl) + ".3mf", stl]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    rj = os.path.join(out, "result.json")
    if not os.path.exists(rj):
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return None, "  ".join(tail) or "slicer produced no result.json"
    with open(rj) as f:
        return json.load(f), None


def report(name, res):
    """Return (ok, lines). Non-fatal findings still print."""
    if res.get("return_code", 0) != 0:
        return False, [f"    SLICER ERROR  {res.get('error_string','?')}"]

    got_layer = round(res.get("layer_height", 0), 3)
    plates = res.get("sliced_plates") or []
    if not plates:
        return False, ["    no plates sliced"]

    ok = True
    lines = []
    for p in plates:
        t = p.get("feature_type_times", {}) or {}
        over = t.get("Overhang wall", 0.0)
        bridge = t.get("Bridge", 0.0)
        total = sum(v for k, v in t.items() if k != "Travel") or 1.0
        pct = 100.0 * over / total
        warn = (p.get("warning_message") or "").strip()

        lines.append(f"    layer {got_layer:.2f} mm   overhang {over:6.1f} s "
                     f"({pct:5.2f} % of extrusion)   bridge {bridge:6.1f} s")

        # Bambu's own floating-region detector. This is the check that matters:
        # it named the rib3 female channel that check_all.py and islands.py both
        # passed. Never downgrade it to a warning.
        if warn:
            ok = False
            lines.append(f"    <-- {warn}")
        if pct >= OVERHANG_PCT:
            ok = False
            lines.append(f"    <-- {pct:.2f} % of extrusion is overhang wall "
                         f"(threshold {OVERHANG_PCT:.2f} %)  perimeter laid over air")
    return ok, lines


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--layer", type=float, default=0.12)
    ap.add_argument("--infill", type=int, default=100,
                    help="percent; tiles and panes need 100 or they leak light")
    ap.add_argument("--supports", action="store_true",
                    help="allow supports (defeats the point; for comparison only)")
    a = ap.parse_args()

    if not os.path.exists(STUDIO):
        raise SystemExit(f"Bambu Studio not found at {STUDIO}")

    paths = a.paths or sorted(glob.glob("out/*.stl"))
    if not paths:
        raise SystemExit("no STLs given and out/*.stl is empty")

    bad = 0
    with tempfile.TemporaryDirectory() as wd:
        for p in paths:
            name = os.path.basename(p)
            res, err = slice_one(p, wd, a.layer, a.infill, a.supports)
            if err:
                bad += 1
                print(f"{name:34s}  <-- {err}")
                continue
            ok, lines = report(name, res)
            print(f"{name:34s}  {'ok' if ok else '<-- see below'}")
            for l in lines:
                print(l)
            if not ok:
                bad += 1

    print(f"\n{len(paths)} files, {bad} with problems   "
          f"(layer {a.layer} mm, infill {min(a.infill, MAX_INFILL)} %, "
          f"supports {'on' if a.supports else 'OFF'}, "
          f"overhang threshold {OVERHANG_PCT:.2f} %)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
