"""Layer-by-layer printability check.

Two distinct failure modes, both of which have shipped unprintable geometry on
this project before:

  ISLAND     -- a region with NO material anywhere beneath it and no connection
                to anything supported. It lands on air and detaches.

  CANTILEVER -- a region connected in-plane to supported material, but reaching
                out over nothing. It does not detach, it droops. A 45 deg
                overhang advances one layer-height per layer and is fine; a
                horizontal shelf springing off a wall advances its full width
                in a single layer and is not.

The island test alone passed a joint whose male rail was a 2.2 mm shelf hanging
in free air for 44 mm, because the shelf touches the plate wall sideways and so
is never a separate component. Sideways contact is not support. Hence this file
now tests reach, not just connectivity.

Resolution caveat: everything is rasterised at `res` (0.35 mm default), so a
feature thinner than roughly one cell can fall between sample points and go
unseen entirely -- that is how a 0.11 mm sliver read as clean. Drop `--res` for
a slower, sharper pass when a feature is known to be fine.
"""
import glob, os, struct, sys
import numpy as np
from PIL import Image, ImageDraw

try:
    from scipy import ndimage as _ndimage
    _CROSS = np.array([[0,1,0],[1,1,1],[0,1,0]], dtype=bool)   # 4-connected
except ImportError:                                            # slow fallback
    _ndimage = None
    _CROSS = None

ISLAND_MIN = 3        # cells; ignore rasterisation speckle
REACH_MM   = 1.00     # unsupported reach that counts as a cantilever
REACH_MIN  = 3        # cells; ignore speckle along an ordinary sloped face


def load(p):
    f=open(p,'rb'); f.read(80); n=struct.unpack('<I',f.read(4))[0]; T=[]
    for _ in range(n):
        nx,ny,nz=struct.unpack('<3f',f.read(12))
        v=[struct.unpack('<3f',f.read(12)) for _ in range(3)]; f.read(2)
        T.append((v,nz))
    return T


def dilate(m):
    """4-connected growth by one cell."""
    o=m.copy()
    o[1:,:]  |= m[:-1,:]
    o[:-1,:] |= m[1:,:]
    o[:,1:]  |= m[:,:-1]
    o[:,:-1] |= m[:,1:]
    return o


def reach_map(prev, res, cap):
    """Distance in mm from each cell to the nearest cell supported from below.

    Multi-source growth outward from `prev`; a cell first reached on step s sits
    s*res away from anything holding it up. Cells still unreached at the cap are
    left at inf -- those are islands, which the other test owns."""
    d=np.full(prev.shape, np.inf)
    d[prev]=0.0
    grown=prev.copy()
    for s in range(1, cap+1):
        nxt=dilate(grown)
        new=nxt & ~grown
        if not new.any(): break
        d[new]=s*res
        grown=nxt
    return d


def analyse(path, res=0.35, layer=0.12, zmax=None, reach=REACH_MM):
    T=load(path)
    caps=[(round(v[0][2],3), (1 if nz>0.5 else -1), v) for v,nz in T
          if abs(v[0][2]-v[1][2])<1e-4 and abs(v[0][2]-v[2][2])<1e-4 and abs(nz)>0.5]
    xs=[p[0] for v,_ in T for p in v]; ys=[p[1] for v,_ in T for p in v]
    zs=[p[2] for v,_ in T for p in v]
    x0,y0=min(xs)-1,min(ys)-1
    W=int((max(xs)-x0+1)/res)+2; H=int((max(ys)-y0+1)/res)+2
    zmax = zmax or max(zs)
    # Search far enough to MEASURE a bad overhang, not merely trip on it --
    # capping at the threshold would report every deep cantilever as exactly
    # the threshold and hide how bad it is.
    cap=int(3.0*reach/res)+2
    prev=None; islands=[]; cants=[]; worst=0.0

    # Ray cast straight down: you ENTER solid through a down-facing cap (nz<0,
    # sgn -1) and LEAVE through an up-facing one (nz>0, sgn +1), so inside-ness
    # is the count of down-caps below z minus up-caps below z. This subtraction
    # used to be an addition tested with `acc>0`, which is the wrong sign -- the
    # mask came out empty on every well-formed solid and the file reported
    # "clean" without ever examining anything.
    #
    # `acc` is a running sum, so each layer only needs the caps that appeared
    # since the last one. Rebuilding it from every cap below z each time made
    # this O(layers x caps): 700k PIL allocations on a coupon, ~36M on a plate,
    # which is why a single frame ran 50 minutes without finishing. Each cap is
    # also drawn into a bounding-box-local sub-image rather than a full-plate
    # one -- a triangle covers a tiny fraction of a 228 mm plate.
    caps.sort(key=lambda c: c[0])
    acc=np.zeros((H,W),dtype=np.int32)
    nxt=0; seen_material=False
    z=layer/2
    while z < zmax:
        while nxt < len(caps) and caps[nxt][0] <= z:
            cz,sgn,v = caps[nxt]; nxt+=1
            px=[(p[0]-x0)/res for p in v]; py=[(p[1]-y0)/res for p in v]
            i0=max(0,int(min(px))-1); i1=min(W,int(max(px))+2)
            j0=max(0,int(min(py))-1); j1=min(H,int(max(py))+2)
            if i1<=i0 or j1<=j0: continue
            m=Image.new("1",(i1-i0,j1-j0),0)
            ImageDraw.Draw(m).polygon([(px[k]-i0,py[k]-j0) for k in range(3)], fill=1)
            acc[j0:j1,i0:i1] -= sgn*np.array(m,dtype=np.int32)
        cur = acc>0
        # A part's LOWEST layer is its seating surface, never an island -- it rests
        # on the bed, or on whatever it is stacked on. Only the first *sampled*
        # layer used to be skipped, which covered parts starting at z=0 and nothing
        # else: a multi-part colour stack is authored in place across several
        # files, so an upper level starts partway up z with its support living in
        # a DIFFERENT file. Checked alone, every feature in it reads as floating --
        # one such level reported 47 islands that do not exist. Merge the levels
        # before believing an island result. Note this skips only the first layer
        # with material --
        # if material reappears after a genuine gap, that is still an island.
        if prev is not None and seen_material:
            lbl=label(cur)
            for i in range(1,lbl.max()+1):
                comp = lbl==i
                if comp.sum()<ISLAND_MIN: continue
                if not (comp & prev).any():
                    ys_,xs_=np.nonzero(comp)
                    islands.append((z, comp.sum()*res*res,
                                    xs_.mean()*res+x0, ys_.mean()*res+y0))
            # cantilevers: material laid over nothing, still joined sideways
            unsup = cur & ~prev
            if unsup.any() and prev.any():
                d=reach_map(prev, res, cap)
                dm=np.where(np.isfinite(d), d, 0.0)      # inf == island, not ours
                if unsup.any():
                    seen=dm[unsup]
                    if seen.size: worst=max(worst, float(seen.max()))
                hot = unsup & (dm >= reach-1e-9)
                if hot.any():
                    hl=label(hot)
                    for i in range(1,hl.max()+1):
                        comp = hl==i
                        if comp.sum()<REACH_MIN: continue
                        ys_,xs_=np.nonzero(comp)
                        cants.append((z, float(dm[comp].max()), comp.sum()*res*res,
                                      xs_.mean()*res+x0, ys_.mean()*res+y0))
        if cur.any(): seen_material=True
        prev=cur; z+=layer
    return islands, cants, worst


def label(m):
    """4-connected component labelling.

    This was a pure-Python flood fill and it was the whole file's bottleneck:
    50 minutes on one 816k-triangle frame without finishing, which meant the
    check simply could not be run on real plates. scipy's is the same algorithm
    in C. Keep the fallback -- it makes scipy a soft dependency for anyone
    running the file standalone, and the two agree exactly."""
    if _ndimage is not None:
        return _ndimage.label(m, structure=_CROSS)[0]
    H,W=m.shape; lbl=np.zeros((H,W),dtype=np.int32); cur=0
    for j in range(H):
        for i in range(W):
            if m[j,i] and lbl[j,i]==0:
                cur+=1; stack=[(j,i)]; lbl[j,i]=cur
                while stack:
                    a,b=stack.pop()
                    for da,db in ((1,0),(-1,0),(0,1),(0,-1)):
                        p,q=a+da,b+db
                        if 0<=p<H and 0<=q<W and m[p,q] and lbl[p,q]==0:
                            lbl[p,q]=cur; stack.append((p,q))
    return lbl


def _merge(rows, key, tol=0.6):
    """Collapse a run of consecutive layers reporting the same feature."""
    out=[]
    for r in sorted(rows, key=lambda r:(round(r[key[0]],1), round(r[key[1]],1), r[0])):
        if out and abs(out[-1][key[0]]-r[key[0]])<tol and abs(out[-1][key[1]]-r[key[1]])<tol:
            out[-1]=out[-1][:-1]+(max(out[-1][-1], r[0]),)
            continue
        out.append(r+(r[0],))
    return out


if __name__=="__main__":
    args=[a for a in sys.argv[1:]]
    res, reach = 0.35, REACH_MM
    for f in ("--res","--reach"):
        if f in args:
            i=args.index(f); val=float(args[i+1]); del args[i:i+2]
            if f=="--res": res=val
            else: reach=val
    paths = args or glob.glob("out/*.stl")
    bad = 0
    for p in sorted(paths):
        isl, cants, worst = analyse(p, res=res, reach=reach)
        name=os.path.basename(p)
        if not isl and not cants:
            print(f"{name:34s}  clean   (worst unsupported reach {worst:.2f} mm)")
            continue
        bad += 1
        tags=[]
        if isl:   tags.append(f"{len(isl)} island(s)")
        if cants: tags.append(f"{len(cants)} cantilever(s)")
        print(f"{name:34s}  <-- {', '.join(tags)}")
        for z, sqmm, x, y in isl:
            print(f"    ISLAND      z={z:6.2f}  area={sqmm:6.2f} mm^2  at ({x:.1f}, {y:.1f})")
        for z, r, sqmm, x, y, zend in _merge(cants, (3,4)):
            span = f"z={z:.2f}" if abs(zend-z)<1e-6 else f"z={z:.2f}-{zend:.2f}"
            print(f"    CANTILEVER  {span:>16s}  reach={r:5.2f} mm  "
                  f"area={sqmm:6.2f} mm^2  at ({x:.1f}, {y:.1f})")
    print(f"\n{len(paths)} files, {bad} with problems   "
          f"(cantilever threshold {reach:.2f} mm, raster {res:.2f} mm)")
    sys.exit(1 if bad else 0)
