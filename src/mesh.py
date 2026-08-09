import struct, math

def area(p):
    return 0.5*sum(p[i][0]*p[(i+1)%len(p)][1]-p[(i+1)%len(p)][0]*p[i][1] for i in range(len(p)))

def ccw(p):  return p if area(p)>0 else p[::-1]
def cw(p):   return p if area(p)<0 else p[::-1]

def seg_int(a,b,c,d):
    def o(p,q,r): 
        v=(q[1]-p[1])*(r[0]-q[0])-(q[0]-p[0])*(r[1]-q[1])
        return 0 if abs(v)<1e-12 else (1 if v>0 else 2)
    o1,o2,o3,o4=o(a,b,c),o(a,b,d),o(c,d,a),o(c,d,b)
    return o1!=o2 and o3!=o4

def bridge(outer, holes):
    """Splice each hole into the outer ring with a bridge edge."""
    poly=list(ccw(outer))
    # standard order: rightmost hole first
    holes=sorted(holes, key=lambda h: -max(p[0] for p in h))
    for h in holes:
        hole=list(cw(h))
        edges=[(poly[i],poly[(i+1)%len(poly)]) for i in range(len(poly))]
        for hh in holes:
            if hh is h: continue
            r=list(cw(hh))
            edges+=[(r[i],r[(i+1)%len(r)]) for i in range(len(r))]
        cands=[]
        for hi,hp in enumerate(hole):
            for oi,op in enumerate(poly):
                cands.append((( hp[0]-op[0])**2+(hp[1]-op[1])**2, hi, oi))
        cands.sort()
        placed=False
        for _,hi,oi in cands[:4000]:
            a,b=hole[hi],poly[oi]
            bad=False
            for c,d in edges:
                if c in (a,b) or d in (a,b): continue
                if seg_int(a,b,c,d): bad=True; break
            if bad: continue
            poly = poly[:oi+1] + hole[hi:] + hole[:hi+1] + poly[oi:]
            placed=True; break
        if not placed:
            raise RuntimeError("could not bridge hole at x=%.1f y=%.1f"
                               % (sum(p[0] for p in hole)/len(hole),
                                  sum(p[1] for p in hole)/len(hole)))
    return poly

def in_tri(p,a,b,c):
    d1=(p[0]-b[0])*(a[1]-b[1])-(a[0]-b[0])*(p[1]-b[1])
    d2=(p[0]-c[0])*(b[1]-c[1])-(b[0]-c[0])*(p[1]-c[1])
    d3=(p[0]-a[0])*(c[1]-a[1])-(c[0]-a[0])*(p[1]-a[1])
    neg=(d1<0)or(d2<0)or(d3<0); pos=(d1>0)or(d2>0)or(d3>0)
    return not(neg and pos)

def ear_clip(poly):
    p=list(ccw(poly))
    # drop duplicate consecutive points
    q=[p[0]]
    for v in p[1:]:
        if abs(v[0]-q[-1][0])>1e-9 or abs(v[1]-q[-1][1])>1e-9: q.append(v)
    p=q
    idx=list(range(len(p))); tris=[]; guard=0
    stalled=0
    while len(idx)>3 and guard<40000:
        guard+=1
        for k in range(len(idx)):
            i0,i1,i2=idx[k-1],idx[k],idx[(k+1)%len(idx)]
            a,b,c=p[i0],p[i1],p[i2]
            cr=(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
            if cr<=1e-12: continue
            ok=True
            for j in idx:
                if j in (i0,i1,i2): continue
                v=p[j]
                # a vertex that coincides with a corner is not "inside"
                if ((abs(v[0]-a[0])<1e-9 and abs(v[1]-a[1])<1e-9) or
                    (abs(v[0]-b[0])<1e-9 and abs(v[1]-b[1])<1e-9) or
                    (abs(v[0]-c[0])<1e-9 and abs(v[1]-c[1])<1e-9)): continue
                if in_tri(v,a,b,c): ok=False; break
            if ok:
                tris.append((a,b,c)); idx.pop(k); break
        else:
            break
    if len(idx)==3: tris.append((p[idx[0]],p[idx[1]],p[idx[2]]))
    elif len(idx)>3:
        for k in range(1,len(idx)-1):
            tris.append((p[idx[0]],p[idx[k]],p[idx[k+1]]))
    return tris

def extrude(outer, holes, z0, z1):
    tris=ear_clip(bridge(outer,holes) if holes else outer)
    F=[]
    for a,b,c in tris:
        F.append(((a[0],a[1],z1),(b[0],b[1],z1),(c[0],c[1],z1)))
        F.append(((c[0],c[1],z0),(b[0],b[1],z0),(a[0],a[1],z0)))
    for ring,orient in [(ccw(outer),1)]+[(cw(h),1) for h in holes]:
        n=len(ring)
        for i in range(n):
            a,b=ring[i],ring[(i+1)%n]
            F.append(((a[0],a[1],z0),(b[0],b[1],z0),(b[0],b[1],z1)))
            F.append(((a[0],a[1],z0),(b[0],b[1],z1),(a[0],a[1],z1)))
    return F

def write_stl(path, faces):
    with open(path,'wb') as f:
        f.write(b'\0'*80); f.write(struct.pack('<I',len(faces)))
        for t in faces:
            ux,uy,uz=(t[1][0]-t[0][0],t[1][1]-t[0][1],t[1][2]-t[0][2])
            vx,vy,vz=(t[2][0]-t[0][0],t[2][1]-t[0][1],t[2][2]-t[0][2])
            nx,ny,nz=uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
            L=math.sqrt(nx*nx+ny*ny+nz*nz) or 1
            f.write(struct.pack('<3f',nx/L,ny/L,nz/L))
            for v in t: f.write(struct.pack('<3f',*v))
            f.write(b'\0\0')

def offset_poly(poly, d):
    """Offset a polygon inward by d. Miter joins with a bevel fallback."""
    n=len(poly)
    if n<3: return poly
    a0=abs(area(poly))
    best=None
    for sgn in (1.0,-1.0):
        out=[]
        for i in range(n):
            p0,p1,p2 = poly[i-1], poly[i], poly[(i+1)%n]
            e1=(p1[0]-p0[0], p1[1]-p0[1]); e2=(p2[0]-p1[0], p2[1]-p1[1])
            l1=math.hypot(*e1) or 1e-9; l2=math.hypot(*e2) or 1e-9
            n1=(-e1[1]/l1*sgn, e1[0]/l1*sgn); n2=(-e2[1]/l2*sgn, e2[0]/l2*sgn)
            bx,by=n1[0]+n2[0], n1[1]+n2[1]
            bl=math.hypot(bx,by)
            if bl<1e-9:
                out.append((p1[0]+n1[0]*d, p1[1]+n1[1]*d)); continue
            bx,by=bx/bl,by/bl
            cosh=max(0.2, (n1[0]*bx+n1[1]*by))     # miter limit
            out.append((p1[0]+bx*d/cosh, p1[1]+by*d/cosh))
        aa=abs(area(out))
        if aa<a0 and (best is None or aa>abs(area(best))):
            best=out
    return best if best else poly

def band_prisms(outer, holes, z0, z1, step=0.15):
    """Scanline decomposition: the region becomes a stack of exact-width boxes.
       Immune to the triangulation failures that plague polygons with many holes."""
    rings=[outer]+list(holes)
    edges=[]
    for r in rings:
        for i in range(len(r)):
            a,b=r[i],r[(i+1)%len(r)]
            if abs(a[1]-b[1])>1e-12: edges.append((a,b))
    ys=[p[1] for r in rings for p in r]
    y0,y1=min(ys),max(ys)
    F=[]; y=y0
    while y < y1-1e-9:
        yt=min(y+step, y1); ym=(y+yt)/2
        xs=[]
        for a,b in edges:
            if (a[1]<=ym<b[1]) or (b[1]<=ym<a[1]):
                xs.append(a[0]+(ym-a[1])*(b[0]-a[0])/(b[1]-a[1]))
        xs.sort()
        for i in range(0,len(xs)-1,2):
            xa,xb=xs[i],xs[i+1]
            if xb-xa<1e-6: continue
            F+=box(xa,y,xb,yt,z0,z1)
        y=yt
    return F

def box(x0,y0,x1,y1,z0,z1):
    v=[(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),
       (x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
    q=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    F=[]
    for a,b,c,d in q:
        F.append((v[a],v[b],v[c])); F.append((v[a],v[c],v[d]))
    return F

def _spans(rings, ym):
    xs=[]
    for r in rings:
        for i in range(len(r)):
            a,b=r[i],r[(i+1)%len(r)]
            if abs(a[1]-b[1])<1e-12: continue
            if (a[1]<=ym<b[1]) or (b[1]<=ym<a[1]):
                xs.append(a[0]+(ym-a[1])*(b[0]-a[0])/(b[1]-a[1]))
    xs.sort()
    return [(xs[i],xs[i+1]) for i in range(0,len(xs)-1,2) if xs[i+1]-xs[i]>1e-7]

def _diff(A,B):
    """intervals in A not covered by B"""
    out=[]
    for a0,a1 in A:
        cur=[(a0,a1)]
        for b0,b1 in B:
            nxt=[]
            for c0,c1 in cur:
                if b1<=c0 or b0>=c1: nxt.append((c0,c1)); continue
                if c0<b0: nxt.append((c0,b0))
                if b1<c1: nxt.append((b1,c1))
            cur=nxt
        out+=cur
    return [(a,b) for a,b in out if b-a>1e-7]

def band_shell(outer, holes, z0, z1, step=0.15):
    """Closed manifold shell for a region, built rectilinearly. No internal faces."""
    rings=[outer]+list(holes)
    ys=[p[1] for r in rings for p in r]
    y0,y1=min(ys),max(ys)
    n=max(1,int(math.ceil((y1-y0)/step)))
    h=(y1-y0)/n
    rows=[_spans(rings, y0+h*(i+0.5)) for i in range(n)]
    # split every span at the breakpoints of its neighbours so cap edges conform
    def split(sp, cuts):
        out=[]
        for a,b in sp:
            pts=sorted({a,b} | {c for c in cuts if a<c<b})
            out += [(pts[k],pts[k+1]) for k in range(len(pts)-1)]
        return out
    conformed=[]
    for i,sp in enumerate(rows):
        cuts=set()
        for j in (i-1,i+1):
            if 0<=j<n:
                for a,b in rows[j]: cuts.add(a); cuts.add(b)
        conformed.append(split(sp,cuts))
    rows=conformed
    F=[]
    def quad(a,b,c,d): F.append((a,b,c)); F.append((a,c,d))
    for i,sp in enumerate(rows):
        ya, yb = y0+h*i, y0+h*(i+1)
        for xa,xb in sp:
            quad((xa,ya,z0),(xa,yb,z0),(xb,yb,z0),(xb,ya,z0))          # bottom
            quad((xa,ya,z1),(xb,ya,z1),(xb,yb,z1),(xa,yb,z1))          # top
            quad((xa,ya,z0),(xa,ya,z1),(xa,yb,z1),(xa,yb,z0))          # -x wall
            quad((xb,ya,z0),(xb,yb,z0),(xb,yb,z1),(xb,ya,z1))          # +x wall
        prev = rows[i-1] if i>0 else []
        for xa,xb in _diff(sp, prev):                                   # -y wall
            quad((xa,ya,z0),(xb,ya,z0),(xb,ya,z1),(xa,ya,z1))
        nxt = rows[i+1] if i<n-1 else []
        for xa,xb in _diff(sp, nxt):                                    # +y wall
            quad((xa,yb,z0),(xa,yb,z1),(xb,yb,z1),(xb,yb,z0))
    return F

def loft(levels):
    """levels = [(z, outer_ring, [hole_rings]), ...]
       All levels must share vertex counts, ring for ring.
       Produces ONE closed skin: cap, walls, cap.  No buried faces."""
    def dd(r, eps=1e-7):
        out=[r[0]]
        for v in r[1:]:
            if abs(v[0]-out[-1][0])>eps or abs(v[1]-out[-1][1])>eps: out.append(v)
        if len(out)>1 and abs(out[0][0]-out[-1][0])<eps and abs(out[0][1]-out[-1][1])<eps: out.pop()
        return out
    F=[]
    z0,o0,h0 = levels[0]; o0=dd(o0); h0=[dd(h) for h in h0]
    for a,b,c in ear_clip(bridge(ccw(o0), [cw(h) for h in h0]) if h0 else ccw(o0)):
        F.append(((a[0],a[1],z0),(c[0],c[1],z0),(b[0],b[1],z0)))       # bottom, facing -z
    zN,oN,hN = levels[-1]; oN=dd(oN); hN=[dd(h) for h in hN]
    for a,b,c in ear_clip(bridge(ccw(oN), [cw(h) for h in hN]) if hN else ccw(oN)):
        F.append(((a[0],a[1],zN),(b[0],b[1],zN),(c[0],c[1],zN)))       # top, facing +z
    def same(A,B):
        return len(A)==len(B) and all(abs(a[0]-b[0])<1e-9 and abs(a[1]-b[1])<1e-9 for a,b in zip(A,B))
    def tri_ok(a,b,c):
        ux,uy,uz=(b[0]-a[0],b[1]-a[1],b[2]-a[2]); vx,vy,vz=(c[0]-a[0],c[1]-a[1],c[2]-a[2])
        nx,ny,nz=uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
        return (nx*nx+ny*ny+nz*nz) > 1e-14
    for k in range(len(levels)-1):
        za,oa,ha = levels[k]; zb,ob,hb = levels[k+1]
        flat = abs(zb-za) < 1e-9
        for A,B in [(ccw(oa),ccw(ob))] + [(cw(x),cw(y)) for x,y in zip(ha,hb)]:
            if len(B)!=len(A): raise RuntimeError("loft: ring vertex counts differ")
            if flat and same(A,B): continue          # nothing changes: no wall to build
            n=len(A)
            for i in range(n):
                p,q = A[i], A[(i+1)%n]; r,s = B[i], B[(i+1)%n]
                dead_a = abs(p[0]-q[0])<1e-7 and abs(p[1]-q[1])<1e-7
                dead_b = abs(r[0]-s[0])<1e-7 and abs(r[1]-s[1])<1e-7
                if dead_a and dead_b: continue          # zero-length edge on both rings
                P=(p[0],p[1],za); Q=(q[0],q[1],za); R=(r[0],r[1],zb); S=(s[0],s[1],zb)
                if tri_ok(P,Q,S): F.append((P,Q,S))
                if tri_ok(P,S,R): F.append((P,S,R))
    return F
