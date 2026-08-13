import math

def local_bulge(poly, cx, cy, radius, depth):
    """Push the run of vertices near (cx,cy) outward along their own normal,
       with a smooth falloff — a nipple on a tile, a dimple in a pocket wall."""
    n=len(poly); out=[]
    # polygon centroid, used to decide which way is 'outward'
    gx=sum(p[0] for p in poly)/n; gy=sum(p[1] for p in poly)/n
    for i,(x,y) in enumerate(poly):
        d=math.hypot(x-cx, y-cy)
        if d>=radius: out.append((x,y)); continue
        t=1.0-(d/radius)
        w=t*t*(3-2*t)                      # smoothstep
        a=poly[i-1]; b=poly[(i+1)%n]
        tx,ty=b[0]-a[0], b[1]-a[1]
        L=math.hypot(tx,ty) or 1.0
        nx,ny=ty/L,-tx/L
        if (x-gx)*nx+(y-gy)*ny < 0: nx,ny=-nx,-ny     # point away from centre
        out.append((x+nx*depth*w, y+ny*depth*w))
    return out

def detent_sites(poly, k=2, band=None, steep=False):
    """Two opposed sites on the outline: left-most and right-most.

    `band` is (lo, hi) as fractions of the part's height, restricting the search
    to that horizontal slice. `steep` additionally prefers a point whose local
    wall is close to PERPENDICULAR to the push direction.

    Without either, the global extremes are used -- the original behaviour, and
    correct for a roughly rectangular part where both extremes sit at mid-height
    on opposite walls.

    TWO WAYS THAT GOES WRONG, both found on real parts:

      THE EXTREMES COINCIDE VERTICALLY. A gable's leftmost and rightmost points
      are both at the base, so both nipples land in the bottom corners and the
      top has no contact. Reported from a printed tile: "the top feels like there
      is no nip contact and the nips on the bottom are so far into the corners
      that I struggle to get them snapped into place."

      THE WALL THERE IS SLOPED. Fixing the first with a band alone moved that
      gable's sites onto its 41.5-degree sloping edge, which is worse: a nipple
      on a slope CAMS OUT instead of snapping. It is the same reason a butterfly
      key's shoulders are square rather than tapered.

    So a site wants to be away from the corners AND on a wall the nipple can push
    square against. `steep` scores candidates on local wall angle and takes the
    best on each side; ties go to the more extreme point, preserving the old
    answer on a rectangle.
    """
    pts = poly
    if band is not None:
        ys = [p[1] for p in poly]
        y0, y1 = min(ys), max(ys)
        lo_y = y0 + (y1 - y0) * band[0]
        hi_y = y0 + (y1 - y0) * band[1]
        inband = [p for p in poly if lo_y <= p[1] <= hi_y]
        if len(inband) >= 2:
            pts = inband
    if not steep:
        return [min(pts, key=lambda p: p[0]), max(pts, key=lambda p: p[0])]

    n = len(poly)
    idx = {p: i for i, p in enumerate(poly)}

    def verticality(p):
        """1.0 when the wall is vertical (ideal for a sideways push), 0 when flat."""
        i = idx.get(p)
        if i is None:
            return 0.0
        a = poly[(i - 3) % n]; b = poly[(i + 3) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        return abs(dy) / L

    xs = [p[0] for p in pts]
    mid = (min(xs) + max(xs)) / 2.0
    span = (max(xs) - min(xs)) or 1.0
    out = []
    for side in (-1, +1):
        cand = [p for p in pts if (p[0] - mid) * side > 0]
        if not cand:
            cand = pts
        # reward a steep wall, and reward being far out toward that side
        out.append(max(cand, key=lambda p: verticality(p)
                       + 0.35 * (side * (p[0] - mid) / span)))
    return out


def resample(poly, step=0.35):
    """Uniformly re-point a polygon so local features always have vertices to work with."""
    out=[]; n=len(poly)
    for i in range(n):
        a=poly[i]; b=poly[(i+1)%n]
        L=math.hypot(b[0]-a[0], b[1]-a[1])
        k=max(1,int(L/step))
        for j in range(k):
            t=j/k
            out.append((a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t))
    return out
