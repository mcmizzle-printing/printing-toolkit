"""Turn scanned or photographed line art into printable centreline paths.

Extracted from faith-window's tile tracer, because none of it knows anything
about that project: it takes an image of a drawing, finds the ink, reduces each
stroke to a one-pixel centreline, and hands back polylines you can re-stroke at
whatever width your process can actually lay down.

Why centrelines rather than tracing the ink as filled outlines. Filled outlines
keep the artist's exact line WEIGHT, which sounds better and is usually worse:
a closed shape drawn as an outline (a heart, a ring) traces as an ANNULUS, and
most relief pipelines extrude a subpath without holes -- so the ring fills in
solid. Centrelines are open strokes; re-stroking them yields positive shapes
only. It also lets a line finer than one extrusion come up to something the
printer can hold.

Typical use:

    d    = contrast(img)                      # ink below its own local background
    comp, box = drawn_border(d, hint)         # the frame the artist drew, if any
    art  = despeckle(fill_pinholes(mask))     # clean the graphite up
    sk   = thin(art)                          # 1-px skeleton
    runs = polylines(sk)                      # continuous strokes
    runs = [straighten(smooth_run(resample_run(r), 6), 4) for r in runs]
"""
import math

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

LINE_W_MM = 0.42     # one extrusion at a 0.4 mm nozzle; below this a feature prints nothing
RED_THR = 20         # redness above this is a coloured registration border, not artwork

_OFF = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]


# ---------- ink ----------

def contrast(img, blur=60):
    """How far below its own LOCAL background each pixel sits.

    The sheet is a phone photo with a lighting gradient, so a global threshold
    picks up the shadowed corner and loses the lightly-drawn side."""
    g = np.asarray(img.convert("L"), float)
    bg = np.asarray(img.convert("L").filter(ImageFilter.GaussianBlur(blur)), float)
    return bg - g

def redness(img):
    """How red each pixel is. If the artist draws the registration border in a
       different colour from the artwork, hue separates the two exactly -- far
       better than any darkness-and-connectivity heuristic."""
    a = np.asarray(img.convert("RGB"), float)
    return a[..., 0] - np.maximum(a[..., 1], a[..., 2])

def drawn_border(d, select, thr=0.40, close=9, mask=None):
    """Her drawn tile border and its bounding box, from the heavy pen alone.

    DETECT ON THE WHOLE SHEET, THEN SELECT. Tiles are drawn touching, so inside
    a tight crop the biggest connected run of pen is the neighbour's border
    fused to this one -- which is how a neighbour's border ends up
    defining this drawing's bounding box. Across the full sheet the borders do
    separate into one component per tile, so the component is chosen by overlap
    with `select` (x0, y0, x1, y1) rather than by being the largest.

    The artwork is not a risk here even where she presses hard enough to pass
    the same threshold -- her olive leaves are nearly solid -- because only a
    border is one long connected run."""
    hard = mask if mask is not None else \
        ndimage.binary_closing(d > d.max() * thr, np.ones((close, close)))
    lab, n = ndimage.label(hard, np.ones((3, 3)))
    if not n:
        raise SystemExit("no tile border found")
    x0, y0, x1, y1 = select
    best, comp = -1, None
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        r0, r1 = sl[0].start, sl[0].stop
        c0, c1 = sl[1].start, sl[1].stop
        if (r1 - r0) * (c1 - c0) < 10000:
            continue
        ov = max(0, min(c1, x1) - max(c0, x0)) * max(0, min(r1, y1) - max(r0, y0))
        frac = ov / float((c1 - c0) * (r1 - r0))     # how much of IT lies in the hint
        if frac > best:
            best, comp, bbox = frac, lab == i, (r0, r1 - 1, c0, c1 - 1)
    if comp is None:
        raise SystemExit("no tile border overlapping the selection")
    return comp, bbox

def fill_pinholes(m, max_area=900):
    """Patchy graphite leaves specks of white inside a stroke; thinning turns
       each one into a little loop, and a run of them into a bead chain."""
    holes = ndimage.binary_fill_holes(m) & ~m
    lab, n = ndimage.label(holes)
    if not n:
        return m
    small = np.zeros(n + 1, bool)
    small[1:] = ndimage.sum(holes, lab, range(1, n + 1)) <= max_area
    return m | small[lab]

def despeckle(m, min_px):
    lab, n = ndimage.label(m, np.ones((3, 3)))
    if not n:
        return m
    keep = np.zeros(n + 1, bool)
    keep[1:] = ndimage.sum(m, lab, range(1, n + 1)) >= min_px
    return keep[lab]


# ---------- centreline ----------

def _nb(a):
    return [np.roll(np.roll(a, -dy, 0), -dx, 1) for dy, dx in _OFF]

def thin(mask):
    """Zhang-Suen thinning to a 1-px skeleton."""
    img = mask.astype(np.uint8)
    while True:
        removed = False
        for step in (0, 1):
            P = _nb(img)
            B = sum(P)
            seq = P + [P[0]]
            A = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.uint8) for i in range(8))
            c = ((P[0] * P[2] * P[4] == 0) & (P[2] * P[4] * P[6] == 0)) if step == 0 else \
                ((P[0] * P[2] * P[6] == 0) & (P[0] * P[4] * P[6] == 0))
            rem = (img == 1) & (B >= 2) & (B <= 6) & (A == 1) & c
            if rem.any():
                img[rem] = 0
                removed = True
        if not removed:
            return img.astype(bool)

def prune(sk, n=10):
    """Shave the hairs thinning leaves on a rough pencil edge."""
    for _ in range(n):
        tips = sk & (sum(_nb(sk.astype(np.uint8))) == 1)
        if not tips.any():
            break
        sk = sk & ~tips
    return sk

def polylines(sk, min_len=8):
    """Skeleton -> continuous point runs.

    Split on the CROSSING NUMBER, not the neighbour count. Zhang-Suen leaves
    staircase pixels with three 8-neighbours sitting mid-line; on the first tile
    traced, 1075 of 2616 skeleton pixels looked like junctions that way and the
    drawing came out as 345 crumbs instead of 28 strokes. Counting 0->1
    transitions around the ring collapses those back to 2."""
    pts = {(int(r), int(c)) for r, c in zip(*np.nonzero(sk))}
    nbrs = {p: [(p[0] + dy, p[1] + dx) for dy, dx in _OFF
                if (p[0] + dy, p[1] + dx) in pts] for p in pts}

    def cross(p):
        v = [1 if (p[0] + dy, p[1] + dx) in pts else 0 for dy, dx in _OFF]
        return sum(1 for i in range(8) if v[i] == 0 and v[(i + 1) % 8] == 1)

    xn = {p: cross(p) for p in pts}
    used, out = set(), []

    def step(prev, cur):
        cand = [q for q in nbrs[cur] if q != prev and frozenset((cur, q)) not in used]
        if not cand:
            return None
        if prev is not None:                    # never take the diagonal short-cut back
            cand.sort(key=lambda q: -((q[0] - prev[0]) ** 2 + (q[1] - prev[1]) ** 2))
        return cand[0]

    def walk(a, b):
        run = [a, b]
        used.add(frozenset((a, b)))
        while xn.get(run[-1], 0) == 2:
            n = step(run[-2], run[-1])
            if n is None:
                break
            used.add(frozenset((run[-1], n)))
            run.append(n)
        return run

    for p in sorted(pts):
        if xn[p] != 2:                          # endpoint or a real junction
            for q in nbrs[p]:
                if frozenset((p, q)) not in used:
                    out.append(walk(p, q))
    for p in sorted(pts):                       # closed loops have neither
        for q in nbrs[p]:
            if frozenset((p, q)) not in used:
                out.append(walk(p, q))
    return [r for r in out if len(r) >= min_len]

def rdp(pts, eps):
    if len(pts) < 3:
        return [list(p) for p in pts]
    a = np.array(pts, float)
    d = a[-1] - a[0]
    n = float(np.hypot(*d))
    v = a - a[0]
    dist = np.hypot(*v.T) if n < 1e-9 else np.abs(d[0] * v[:, 1] - d[1] * v[:, 0]) / n
    i = int(np.argmax(dist))
    if dist[i] <= eps:
        return [list(pts[0]), list(pts[-1])]
    return rdp(pts[:i + 1], eps)[:-1] + rdp(pts[i:], eps)


# ---------- clean up a drawn line ----------

def resample_run(pts, step=2.0):
    """Uniform arc-length resampling -- smoothing is meaningless on points that
       are unevenly spaced, which skeleton pixels always are."""
    out = [tuple(pts[0])]
    acc = 0.0
    for a, b in zip(pts, pts[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        if d < 1e-9:
            continue
        t = 0.0
        while acc + (d - t) >= step:
            t += step - acc
            f = t / d
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            acc = 0.0
        acc += d - t
    if out[-1] != tuple(pts[-1]):
        out.append(tuple(pts[-1]))
    return out

def smooth_run(pts, sigma):
    """Gaussian blur along the curve. This is what takes the hand-drawn wobble
       out while leaving the shape exactly where she put it."""
    if sigma <= 0 or len(pts) < 3:
        return pts
    a = np.array(pts, float)
    closed = math.hypot(a[0][0] - a[-1][0], a[0][1] - a[-1][1]) < 3.0
    r = max(1, int(sigma * 2.5))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / float(sigma)) ** 2)
    k /= k.sum()
    mode = "wrap" if closed else "nearest"
    return list(zip(ndimage.convolve1d(a[:, 0], k, mode=mode),
                    ndimage.convolve1d(a[:, 1], k, mode=mode)))

def straighten(pts, tol):
    """A run that never departs its own chord by more than `tol` becomes that
       chord. Ruled lines in the original come back as ruled lines."""
    if tol <= 0 or len(pts) < 3:
        return pts
    a = np.array(pts, float)
    d = a[-1] - a[0]
    n = float(np.hypot(d[0], d[1]))
    if n < 1e-9:
        return pts
    v = a - a[0]
    dev = np.abs(d[0] * v[:, 1] - d[1] * v[:, 0]) / n
    return [pts[0], pts[-1]] if dev.max() <= tol else pts

def catmull(pts):
    """Points -> smooth cubic segments (Catmull-Rom converted to Bezier)."""
    P = [pts[0]] + list(pts) + [pts[-1]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        out.append(((p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0),
                    (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0),
                    p2))
    return out


# ---------- locate ----------

def find_drawings(img, min_px=20000):
    """Every tile border on the sheet, as --select boxes.

    Saves hunting bounding boxes by hand, which is how the first two sheets were
    done. Prefers the red border if she drew one."""
    d = contrast(img)
    red = redness(img)
    mask = (red > RED_THR) if (red > RED_THR).sum() > 20000 else \
        ndimage.binary_closing(d > d.max() * 0.40, np.ones((9, 9)))
    lab, n = ndimage.label(mask, np.ones((3, 3)))
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        if int((lab[sl] == i).sum()) < min_px:
            continue
        r0, r1 = sl[0].start, sl[0].stop
        c0, c1 = sl[1].start, sl[1].stop
        out.append((c0, r0, c1, r1))
    return sorted(out)

# ---------- measure ----------

def region_widths(labels, floor_px=None):
    """Widest circle that fits inside each labelled region, in PIXELS.

    Returns {label: width}. Unit-free on purpose -- the caller knows its own
    scale, and a shared library has no business deciding what is too small.

    This exists because a region can be perfectly well-formed and still be
    unmanufacturable: in a multi-material part, a sliver narrower than the
    process can lay down simply is not there, and the usual repair -- merging it
    into a neighbour -- removes it SILENTLY. Nothing downstream notices, because
    the mesh that results is completely valid. Measure the regions before you
    trust them.

    Area is the wrong test and a tempting one. A long thin region can have plenty
    of area and no width at all; an area filter set from a typical piece's size
    will delete narrow pieces that were perfectly printable and keep slivers that
    are not. Width is what the process actually limits.

    With `floor_px`, returns only the regions below it -- the failures.
    """
    out = {}
    for v in np.unique(labels):
        if v == 0:
            continue
        m = labels == v
        # the distance transform's peak is the inscribed radius; double it
        w = 2.0 * ndimage.distance_transform_edt(m).max()
        if floor_px is None or w < floor_px:
            out[int(v)] = float(w)
    return out
