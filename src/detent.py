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

def detent_sites(poly, k=2):
    """Left-most and right-most points of the outline."""
    lo=min(poly,key=lambda p:p[0]); hi=max(poly,key=lambda p:p[0])
    return [lo,hi]

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
