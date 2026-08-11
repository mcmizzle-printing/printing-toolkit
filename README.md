# printing-toolkit

Shared Python geometry/STL primitives for 3D-printing projects — no CAD, meshes built and
written directly from code. Split out of `faith-window` (a private project of mine) so it isn't
reinvented in the next printing project.

This is a library, not a standalone tool: it has no `out/` and nothing to run on its own.
Consuming project repos install it editable and import from it directly.

---

## Layout

| | |
|---|---|
| `src/` | the primitives: `mesh`, `icons`, `stroke2fill`, `detent`, `seamjoint`, `rib3`, `bowtie`, `linetrace` |
| `tests/` | `check_all.py` (watertight + on-bed), `islands.py` (islands + cantilevers), `slicecheck.py` (headless Bambu slice), `render.py` (STL → PNG) — run against a consuming project's `out/*.stl` |

---

## Using this from another project

```bash
# in the consuming repo
python3 -m venv .venv
source .venv/bin/activate
pip install -e ../printing-toolkit
```

Then, from that repo:

```python
from mesh import extrude, write_stl, band_prisms
from icons import flatten
```

And to check generated STLs before they go anywhere near a printer:

```bash
python3 ../printing-toolkit/tests/check_all.py     # watertight + on-bed
python3 ../printing-toolkit/tests/islands.py       # islands + cantilevers — always run this
python3 ../printing-toolkit/tests/slicecheck.py    # what Bambu Studio thinks, supports OFF
python3 ../printing-toolkit/tests/render.py        # STL -> PNG, to actually look at it
```

All four default to `out/*.stl` in the current directory, or take explicit paths.

- `islands.py` — `--reach MM` (cantilever threshold, default 1.0) and `--res MM` (raster,
  default 0.35). A full 29-file `out/` runs in under 30 seconds.
- `slicecheck.py` — `--layer`, `--infill`, `--supports`. Needs Bambu Studio; macOS paths are
  constants at the top of the file.
- `render.py` — `--views`, or `--focus X,Y,Z --dist MM` to inspect one feature. Needs `f3d`.

---

### Why the imports are flat

`pyproject.toml` declares `src/*.py` as flat top-level modules (`package-dir` +
`py-modules`, not a `printing_toolkit/` package), specifically so consuming code can write
`from mesh import ...` rather than `from printing_toolkit.mesh import ...`. Don't restructure
this into a proper package without updating every consumer's imports at the same time.

Dependencies (`numpy`, `Pillow`) are declared there too and come in with the editable install.

---

## Module inventory

`src/` — importable as plain top-level modules (`from mesh import ...`), not a package:

| Module | What it does |
|---|---|
| `mesh.py` | Core mesh kit: `area`/`ccw`/`cw` polygon winding, `ear_clip`/`extrude` (ear-clipping extrusion — simple polygons only), `band_prisms`/`band_shell` (scanline box decomposition — robust with many holes, what the frames actually use), `bridge` (hole-to-outer-boundary bridging for ear clipping), `offset_poly`, `loft`, `write_stl` |
| `icons.py` | SVG path → usable geometry: `path_pts` (flatten a path `d` string to points), `art_bbox`, `flatten`, `mask_of`, `best_rect` |
| `stroke2fill.py` | Turns stroked SVG paths into filled polygons: `subpaths`, `stroke_to_polys`, `dashify`, `convert` |
| `detent.py` | Printable snap retention: `local_bulge` (push a run of polygon vertices outward/inward along their normal — the nipple/dimple primitive), `detent_sites`, `resample` |
| `seamjoint.py` | `splice_dovetails` — inserts dovetail tail/socket features into a polygon outline where it runs along a seam line |
| `rib3.py` | A half-dovetail seam profile (square shelf, undercut only on top): `spans(depth)` builds the pair at any undercut depth; `channel_span`/`rail_span` and the z-height constants are that factory at the shipping depth. **Its male rail cannot print unsupported** — see below |
| `linetrace.py` | Scanned line art → printable strokes: `thin` (ink mask to a 1-px skeleton), `prune`, `polylines`, `resample_run`, `smooth_run` (blur a stroke *along its own length*, so the shape stays where it was drawn and only the wobble goes), and `region_widths` (largest inscribed circle per region — the width test that an area filter gets wrong). Knows nothing about panes or tiles; the registration and clipping live in the consuming project |
| `bowtie.py` | Butterfly key: a two-flank dovetail carried by a *separate* part, so both panels get sockets only and nothing protrudes into air. `profile()` returns key/socket half-widths by height plus the derived x ranges; `wall()` reports material left outboard. Profile math only — the caller meshes it, same split as `rib3` |

`tests/` — standalone scripts, run directly against a consuming project's `out/*.stl`, not
installed as part of the package:

| Script | What it does |
|---|---|
| `check_all.py` | Watertight (odd-count edge check) + on-bed (P2S 256×256, AMS cutter exclusion) audit over a glob of STLs. `python3 check_all.py [paths...]`, defaults to `out/*.stl` in the caller's cwd |
| `islands.py` | Layer-by-layer printability: **islands** (a region with nothing beneath it and no connection to anything supported — it detaches) and **cantilevers** (a region joined sideways to supported material but reaching out over nothing — it droops). `python3 islands.py [paths...] [--reach MM] [--res MM]`, same default. Catches "material starting in mid-air," which watertight and on-bed both miss. **Prismatic geometry only — see the limitation below before relying on it** |
| `slicecheck.py` | Headless Bambu Studio slice with supports forced **off**, reporting Bambu's own floating-region warning and overhang-perimeter share of extrusion time. `python3 slicecheck.py [paths...] [--layer MM] [--infill PCT] [--supports]`, same default. macOS-only, needs Bambu Studio installed; the P2S/PETG profile names and thresholds are constants at the top of the file. Also exports **`run_slice`** and **`flatten`**/**`write_profile`** for consumers driving the CLI themselves — see below |
| `render.py` | STL → PNG, so geometry can be *looked at* rather than only reasoned about. `--views iso,top,front,right`, or `--focus X,Y,Z --dist MM` to point the camera at one feature — a 3 mm socket in a 228 mm plate is invisible in an overview. Needs `brew install f3d`. Not a check: nothing it produces passes or fails, but two defects on this project were caught by drawing a cross-section and none by a number |

---

## `islands.py` cannot see curved geometry

**It reports curved overhangs as clean.** Not as an error — as a pass. Found 2026-08-10 while
adding a printability check to `peggify`, whose hook geometry is entirely cylinders and spheres.
Tracked in [#1](https://github.com/mcmizzle-printing/printing-toolkit/issues/1).

Two parts, each an 8×8×20 mm pillar seated on the bed with a branch springing sideways at
z = 5 mm and reaching 12 mm over open air. Only the branch geometry differs:

```
branch_box.stl    <-- 1 cantilever(s)          # box shelf: caught
branch_rod.stl    clean   (worst reach 0.00 mm) # cylindrical rod: missed
```

The occupancy mask is built by ray-casting through *perfectly horizontal* cap triangles only. A
horizontal cylinder has no perfectly horizontal side facet — a side quad spans angles `t1` and
`t2`, and its z values are `r·sin(t1)` and `r·sin(t2)`, equal only in the degenerate case — so the
rod contributes no caps, never enters the mask, and the scan looks straight through it. The same
applies to spheres, fillets, bosses and chamfered edges.

This is structural, not resolution: `--res 0.35`, `0.20` and `0.12` all report clean. Dropping
`--res` is the documented remedy for thin features and **will not help here.**

So: extruded prisms bounded by flat top and bottom caps — which is nearly all of `faith-window` —
are checked correctly. Anything curved is not checked at all. Until #1 is fixed, treat a clean
`islands.py` result on curved geometry as *no information*, and verify it another way.

`peggify` carries a voxel-based support scan (`peggify/validate.py`) that gets both parts above
right and does not care how the surface is tessellated. Whether that moves in here is part of #1 —
it needs a mesh library the toolkit does not currently depend on.

---

## Two things about driving Bambu Studio's CLI

Both cost real time to find, and both bite any project that slices headlessly.

**It does not resolve a profile's `inherits` chain.** Hand the CLI a stock profile stub like
`0.12mm High Quality @BBL P2S.json` and it silently falls back to the **0.20 mm default** — no
warning, no error, just the wrong layer height. `flatten()` resolves the chain and
`write_profile()` writes the merged result; that is the only reason `slicecheck.py` exists rather
than being one line of shell. The CLI also takes whole JSON files only — there is no per-key
override, no `--layer-height`.

**It segfaults intermittently while parsing `--load-filaments`.** Confirmed on
BambuStudio **02.07.01.62** (macOS, arm64) from crash reports: identical stack every time —
`convert_filament_preset_name` → `basic_string` copy → `_platform_memmove`, EXC_BAD_ACCESS
reading address 0 — but *different signals* across runs (SIGSEGV and SIGBUS back to back), which
is an uninitialised read rather than a race in the caller. Roughly **1 run in 4** on the
multi-filament path; the single-filament path is far less exposed. Nothing in the config prevents
it.

**`run_slice(cmd, gcode_path, cwd=, retries=, log=)`** handles it: it retries on a **negative
return code** — killed by a signal — and *only* that. A non-negative exit with no output is a
real failure and is raised with the slicer's own last lines, never retried, so the helper cannot
become the thing that hides genuine breakage. It returns `(proc, attempts)` so callers can report
that a retry happened instead of smoothing it away.

If you drive the CLI directly for multi-filament work, use it.

---

## Versioning

None yet — `pyproject.toml` version is a placeholder (`0.1.0`), and the only integration
mechanism is an editable install against a local sibling checkout. Fine for a single consumer
on one machine. Revisit if/when there's a second consuming project or a second machine, since
editable installs won't survive that on their own.

---

## Current consumers

- `faith-window` — the original, and the project this was split out of. Extruded prism geometry
  built with `mesh`/`icons`/`detent`/`seamjoint`/`bowtie`/`linetrace`.
- `peggify` — converts wall-mount STL models to pegboard-mount. Uses the **verification scripts
  only**, not `src/`: its geometry is built with `trimesh` and `manifold3d` rather than this
  toolkit's primitives, so the shared value is the checks. Note that `islands.py` cannot currently
  see its geometry at all — see the limitation above.

A second consumer means the versioning note above is now live rather than hypothetical: two
projects pin nothing and both depend on a local sibling checkout being present and current.
