---
name: mesh-preflight
description: Verification gate and printability rules for directly-authored STL geometry (no CAD). Use BEFORE designing any joint, tab, rail, channel, snap or overhang, and ALWAYS before saying a mesh is ready to print or slice. Covers the four checks in printing-toolkit/tests (watertight, on-bed, islands/cantilevers, headless Bambu slice), the mid-air-material rule that watertight checks do not catch, why sideways contact is not support, and Bambu P2S bed placement (author centred at 128,128; 228 mm usable with the AMS).
---

# Mesh preflight

Geometry here is written straight to STL from Python — no CAD, no slicer in the loop unless you
put it there. Nothing catches a bad feature except these checks. Run all four.

## The gate

Never call a mesh ready to print, ready to slice, or "done" without these passing. From the
consuming project's repo root, venv active:

```bash
python3 ../printing-toolkit/tests/check_all.py     # watertight + on-bed
python3 ../printing-toolkit/tests/islands.py       # islands + cantilevers
python3 ../printing-toolkit/tests/slicecheck.py    # what Bambu Studio thinks
```

All three default to `out/*.stl`, accept explicit paths, and exit non-zero on failure. Pass
just-changed files while iterating; run the lot before anything ships.

| Check | Catches | Does NOT catch |
|---|---|---|
| `check_all.py` watertight | open edges (odd edge-use count) | anything about printability |
| `check_all.py` on-bed | off the 256×256 bed, or inside the 18×28 mm front-left AMS cutter exclusion | anything about geometry validity |
| `islands.py` ISLAND | a region with no material beneath it — lands on air, detaches | features thinner than the raster |
| `islands.py` CANTILEVER | material joined sideways but reaching >1.00 mm over nothing in one layer — droops | features thinner than the raster |
| `slicecheck.py` | Bambu's floating-region warning; overhang perimeter as a share of extrusion | needs Bambu Studio installed; macOS paths hardcoded |

**These are four independent properties, not one.** A watertight mesh can be completely
unprintable. Three unprintable designs reached the printer because only two of the checks were
being run, and a fourth — rib3 — passed all three of the geometry checks and was caught by Bambu
Studio, which is why `slicecheck.py` now exists.

## The rule that keeps getting violated

*Material may not appear in mid-air with nothing beneath it.*

The 45° rule applies to a surface growing over material **already below it**. It does not apply to
a protrusion that starts from nothing. A tapering tab has nothing below it at any angle — no taper
angle rescues it.

Five features have failed this way:

1. Male dovetail rail starting as a point — first layers were 0.08 mm slivers, detached
2. Female channel's closing lintel — an island for 20 layers, 7 thinner than one extrusion
3. Tapered jigsaw — printed, but too little engagement to lock
4. Detent land only 0.3 mm tall — printed, but no shoulder to catch
5. `rib3`'s male rail — a 1.0–2.2 mm shelf springing off the plate wall with nothing under it,
   running the full seam

### Sideways contact is not support

This is the lesson from #5 and it is the one most easily got wrong. That rail was called "rooted"
because its first layer meets the plate wall edge-on. Meeting a wall **edge-on is not the same as
having material underneath**. The fix for #1 — make the first layer full width instead of a
tapering sliver — traded a detached sliver for an unsupported cantilever without ever removing the
mid-air start.

**Any male part protruding past the host's footprint must begin in air.** Widening it, chamfering
it, or rooting it into the wall does not change that; a chamfered start just reverts to #1. The
only real fixes are to stop protruding (a separate key or insert, engaging pockets on both sides)
or to reorient so the protrusion grows upward off the bed.

Applied before generating geometry:

- **A channel's floor stays solid** for the first few mm so the mating part lands on material.
- **Retention features need a shoulder**, not just a bump: ≥1.2 mm (10 layers) of land.
- **Prefer joints with no protruding male part at all.** A double-ended key dropped into pockets
  on both sides is printable flat; a tongue growing sideways out of a wall is not.

## Reading the output

`islands.py`

- `clean (worst unsupported reach N mm)` — the number matters even when clean. Creeping toward
  1.00 mm means the next tweak trips it.
- `ISLAND` — hard fail, always. `CANTILEVER` reports a z-span, so it shows how deep the problem runs.
- **Resolution caveat:** default raster 0.35 mm. A feature thinner than roughly one cell can fall
  between sample points and read as clean — a 0.11 mm sliver did exactly that. Re-run load-bearing
  thin features with `--res 0.12`. `--reach` sets the cantilever threshold; don't loosen it to make
  a failure go away.

`slicecheck.py`

- **`<-- It seems object X has floating regions…`** is Bambu's own detector and always a hard fail.
  It is the highest-trust signal in the whole gate.
- **Overhang wall %** — share of extrusion laid over air. Calibrated 2026-08-04: butterfly keys
  0.02 %, the jigsaw that actually printed 0.00 %, rib3's cantilevered male rail 0.79 %. Threshold
  0.30 %.
- **Bridge time is reported but never fails a part.** A bridge is anchored at both ends and prints
  fine — the working jigsaw spends 70 s bridging its pocket. Do not treat bridge as overhang.
- Supports are forced **off**. The question is not "can this be printed" but "does this print
  unsupported", which is the actual design constraint.

## Bed placement — Bambu P2S

- 256 × 256 nominal, but with the AMS attached an **18 × 28 mm front-left zone** is off limits
  (filament cutter lever). Full volume OR the AMS, not both.
- After purge lines, prime tower and margin, plan for **228 mm usable**.
- **Always author STLs centred at (128, 128).** Geometry near the origin gets flagged "Outside" and
  the plate silently slices to nothing. Builders do this with a `BED = 128.0` offset applied as the
  last transform before `write_stl`.

## Bambu Studio CLI gotchas

`slicecheck.py` wraps these, but they bite anyone driving the CLI directly:

- **Bundled profiles are stubs chained by `inherits`, and the CLI does not resolve the chain.**
  Hand it `0.12mm High Quality @BBL P2S.json` and it silently slices at the 0.20 mm default,
  reporting 0.20 in `result.json` with no warning. Flatten the chain first.
- **Default bed is Cool Plate, which PETG is incompatible with** — the slice aborts with
  `return_code -61` before producing any geometry report. Set `curr_bed_type`.
- **`sparse_infill_density` of 100 (or `"100%"`) is rejected** with a bare `return_code -18` and no
  indication of which key was at fault. 99 is accepted.
- `--debug` changes which lines reach stdout. **Never scrape the log for pass/fail** — read
  `return_code` out of `result.json`, which is written regardless.

## Meshing choices that bite

- `mesh.extrude()` is ear-clipping — **simple polygons only**. It fails on outlines with many
  holes. Frames with many holes use `mesh.band_prisms()` (scanline box decomposition), robust but
  15–30 MB. That size is expected, not a bug.
- Verify after *every* regeneration, not once at the end. A parameter change that looks cosmetic
  can reintroduce an island.
