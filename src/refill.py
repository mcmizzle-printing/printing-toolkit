#!/usr/bin/env python3
"""Recolour ONE lead-bounded region of a finished art PNG.

WHY THIS EXISTS RATHER THAN A COLOUR REPLACE. A field drawn as TWO shades of one
hue -- #171B6B over most of it, #222A8E in a small lobe, a deliberate tonal step
-- cannot be recoloured by matching a colour with a tolerance. The window caught
the darker shade and missed the lighter one, so the lobe kept its old interior
and picked up a rim of confetti in the new colour: its anti-aliased edge pixels,
which are darker, were the only part of it that fell inside the window.

THAT FAILS QUIETLY IN BOTH DIRECTIONS. By eye it reads as a texture rather than
a miss. Downstream it is worse, and NOT because anything is dropped: a region is
bounded by lead, and the confetti has no lead around it, so the lobe stays ONE
region and takes the colour of its MEDIAN pixel. 80 % old beats 20 % new, the
recolour that half-happened counts for nothing at all, and the region prints in
the colour nobody chose -- spending a filament slot on 9 mm2 of it. Fixing one
such region took a part from 7 filaments to 6.

So a region is identified by WHERE IT IS, not by what colour it currently is.
The lead already encloses it; seed a point inside and take the whole component.
A shade the fill did not expect cannot be missed, because colour is not what is
being matched.

Anti-aliasing is preserved rather than flattened. Every pixel in the region is
some fraction of the region's own flat colour blended toward the black lead, so
the fraction is measured against the modal colour and re-applied to the new one.
A pixel that was already recoloured comes out over 1.0 and clips, which is what
turns the confetti back into flat field.

    python3 -m refill in.png out.png --at 895,390 --to 112,60,150
"""
import argparse
import sys
from collections import Counter

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

LEAD = 90       # a channel max under this is lead, not glass


def refill(a, at, to):
    """`a` HxWx3 uint8, `at` an (x, y) seed, `to` the new RGB. Returns a copy."""
    lab, _n = ndi.label(a.max(2) >= LEAD)
    v = int(lab[at[1], at[0]])
    if v == 0:
        raise SystemExit(f"({at[0]}, {at[1]}) is on the lead, not in a region")
    m = lab == v
    flat = np.array(Counter(map(tuple, a[m])).most_common(1)[0][0], np.float32)
    px = a[m].astype(np.float32)
    # One alpha per pixel, from all three channels -- per channel it would drift
    # the hue on anything the blend is not exactly proportional in.
    alpha = np.clip(px.sum(1) / max(float(flat.sum()), 1.0), 0.0, 1.0)
    out = a.copy()
    out[m] = np.clip(alpha[:, None] * np.array(to, np.float32), 0, 255).astype(np.uint8)
    return out, int(m.sum()), tuple(int(c) for c in flat)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--at", required=True, help="x,y inside the region")
    ap.add_argument("--to", required=True, help="R,G,B")
    a = ap.parse_args()
    at = tuple(int(v) for v in a.at.split(","))
    to = tuple(int(v) for v in a.to.split(","))
    img = np.asarray(Image.open(a.src).convert("RGB"))
    out, n, flat = refill(img, at, to)
    Image.fromarray(out).save(a.dst)
    print(f"  region at {at}: {n} px, {flat} -> {to}")
    print(f"  wrote {a.dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
