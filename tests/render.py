#!/usr/bin/env python3
"""Render STLs to PNG so geometry can be looked at, not just reasoned about.

Nothing else in this toolkit shows you the shape. check_all, islands and
slicecheck all return numbers, and numbers are exactly what let a 0.60 mm
shoulder web and a socket straddling a plate join both survive review on this
project -- each was caught by hand-drawing a cross-section, not by a check.

Two modes:

  overview   whole part, isometric. Confirms it is the shape you meant.
  focus      camera pointed at one feature at a stated working distance.
             A 3 mm socket in a 228 mm plate is invisible in an overview;
             --focus is how you actually inspect a joint.

Needs f3d (`brew install f3d`). Rendering is offscreen -- no window opens.
"""
import argparse, glob, os, subprocess, sys

F3D = "f3d"
VIEWS = {                      # name -> (camera direction, view up)
    "iso":   ((-1, -1, -0.8), (0, 0, 1)),
    "top":   ((0, 0, -1),     (0, 1, 0)),
    "front": ((0, -1, 0),     (0, 0, 1)),
    "right": ((-1, 0, 0),     (0, 0, 1)),
}


def render(stl, out, view="iso", focus=None, dist=None, res=(1400, 900), grid=False):
    """One PNG. `focus` is an (x,y,z) in model space; `dist` the camera's
       distance from it in mm -- smaller means a tighter look at the feature."""
    d, up = VIEWS[view]
    cmd = [F3D, stl, "--output", out, "--resolution", f"{res[0]},{res[1]}",
           "--camera-view-up", ",".join(map(str, up))]
    if grid: cmd.append("--grid")
    if focus is not None:
        dist = dist or 40.0
        n = sum(c*c for c in d) ** 0.5
        pos = [focus[i] - d[i]/n*dist for i in range(3)]
        cmd += ["--camera-focal-point", ",".join(f"{c:.3f}" for c in focus),
                "--camera-position",    ",".join(f"{c:.3f}" for c in pos)]
    else:
        cmd += ["--camera-direction", ",".join(map(str, d))]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(out):
        return (p.stderr or p.stdout or "f3d produced no output").strip().splitlines()[-1:]
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--out", default="renders", help="output directory")
    ap.add_argument("--views", default="iso",
                    help=f"comma-separated, from {sorted(VIEWS)}; 'all' for every one")
    ap.add_argument("--focus", help="X,Y,Z in model space to point the camera at")
    ap.add_argument("--dist", type=float, help="camera distance from focus, mm")
    ap.add_argument("--res", default="1400,900")
    ap.add_argument("--grid", action="store_true")
    a = ap.parse_args()

    if not shutil_which(F3D):
        raise SystemExit("f3d not found -- brew install f3d")
    paths = a.paths or sorted(glob.glob("out/*.stl"))
    if not paths:
        raise SystemExit("no STLs given and out/*.stl is empty")

    views = sorted(VIEWS) if a.views == "all" else [v.strip() for v in a.views.split(",")]
    for v in views:
        if v not in VIEWS: raise SystemExit(f"unknown view {v!r}; have {sorted(VIEWS)}")
    focus = tuple(float(c) for c in a.focus.split(",")) if a.focus else None
    res = tuple(int(c) for c in a.res.split(","))
    os.makedirs(a.out, exist_ok=True)

    bad = 0
    for p in paths:
        stem = os.path.splitext(os.path.basename(p))[0]
        for v in views:
            tag = f"{stem}-{v}" + ("-focus" if focus else "")
            dst = os.path.join(a.out, tag + ".png")
            err = render(p, dst, v, focus, a.dist, res, a.grid)
            if err:
                bad += 1; print(f"{tag:44s}  <-- {' '.join(err)}")
            else:
                print(f"{tag:44s}  {dst}")
    print(f"\n{len(paths)*len(views)} renders, {bad} failed")
    return 1 if bad else 0


def shutil_which(x):
    from shutil import which
    return which(x)


if __name__ == "__main__":
    sys.exit(main())
