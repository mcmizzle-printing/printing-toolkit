import re, math

# ---------- full path flattener: abs+rel, M L H V C Q A Z ----------
def subpaths(d, seg=14):
    out=[]; cur=[0.0,0.0]; start=[0.0,0.0]; pts=[]; prev_c=None
    def flush(closed):
        nonlocal pts
        if len(pts)>1: out.append((pts, closed))
        pts=[]
    toks=re.findall(r'([MmLlHhVvCcSsQqTtAaZz])([^MmLlHhVvCcSsQqTtAaZz]*)', d)
    for cmd,arg in toks:
        C=cmd.upper(); rel=cmd.islower()
        if C=='A':
            n=[]
            for g in re.finditer(r'(-?[\d.]+)[\s,]*(-?[\d.]+)[\s,]*(-?[\d.]+)[\s,]*([01])[\s,]*([01])[\s,]*(-?[\d.]+)[\s,]*(-?[\d.]+)', arg):
                n+=[float(v) for v in g.groups()]
        else:
            n=[float(x) for x in re.findall(r'-?\d*\.?\d+(?:[eE]-?\d+)?', arg)]
        i=0
        if C=='Z':
            flush(True); cur=start[:]; continue
        while i<len(n):
            if C=='M':
                flush(False)
                x,y=n[i],n[i+1]; i+=2
                cur=[cur[0]+x,cur[1]+y] if rel else [x,y]
                start=cur[:]; pts=[tuple(cur)]; C='L'
            elif C=='L':
                x,y=n[i],n[i+1]; i+=2
                cur=[cur[0]+x,cur[1]+y] if rel else [x,y]; pts.append(tuple(cur))
            elif C=='H':
                x=n[i]; i+=1; cur=[cur[0]+x if rel else x, cur[1]]; pts.append(tuple(cur))
            elif C=='V':
                y=n[i]; i+=1; cur=[cur[0], cur[1]+y if rel else y]; pts.append(tuple(cur))
            elif C in 'CS':
                if C=='C': x1,y1,x2,y2,x3,y3=n[i:i+6]; i+=6
                else:
                    x2,y2,x3,y3=n[i:i+4]; i+=4
                    x1,y1=(2*cur[0]-prev_c[0]-cur[0], 2*cur[1]-prev_c[1]-cur[1]) if prev_c else (0,0)
                    if not rel: x1,y1=2*cur[0]-prev_c[0] if prev_c else cur[0], 2*cur[1]-prev_c[1] if prev_c else cur[1]
                p0=tuple(cur)
                P1=(cur[0]+x1,cur[1]+y1) if rel else (x1,y1)
                P2=(cur[0]+x2,cur[1]+y2) if rel else (x2,y2)
                P3=(cur[0]+x3,cur[1]+y3) if rel else (x3,y3)
                for k in range(1,seg+1):
                    t=k/seg; u=1-t
                    pts.append((u**3*p0[0]+3*u*u*t*P1[0]+3*u*t*t*P2[0]+t**3*P3[0],
                                u**3*p0[1]+3*u*u*t*P1[1]+3*u*t*t*P2[1]+t**3*P3[1]))
                prev_c=P2; cur=list(P3)
            elif C in 'QT':
                if C=='Q': x1,y1,x2,y2=n[i:i+4]; i+=4
                else:
                    x2,y2=n[i:i+2]; i+=2; x1,y1=cur[0],cur[1]
                p0=tuple(cur)
                P1=(cur[0]+x1,cur[1]+y1) if rel else (x1,y1)
                P2=(cur[0]+x2,cur[1]+y2) if rel else (x2,y2)
                for k in range(1,seg+1):
                    t=k/seg; u=1-t
                    pts.append((u*u*p0[0]+2*u*t*P1[0]+t*t*P2[0], u*u*p0[1]+2*u*t*P1[1]+t*t*P2[1]))
                cur=list(P2)
            elif C=='A':
                rx,ry,rot,laf,sf,ex,ey=n[i:i+7]; i+=7
                x0,y0=cur
                x1,y1=(x0+ex,y0+ey) if rel else (ex,ey)
                dx2,dy2=(x0-x1)/2,(y0-y1)/2
                l=(dx2*dx2)/(rx*rx)+(dy2*dy2)/(ry*ry)
                if l>1: s=math.sqrt(l); rx*=s; ry*=s
                num=rx*rx*ry*ry-rx*rx*dy2*dy2-ry*ry*dx2*dx2
                den=rx*rx*dy2*dy2+ry*ry*dx2*dx2
                co=math.sqrt(max(0,num/den))*(-1 if laf==sf else 1)
                cx=co*rx*dy2/ry+(x0+x1)/2; cy=-co*ry*dx2/rx+(y0+y1)/2
                t1=math.atan2((y0-cy)/ry,(x0-cx)/rx); t2=math.atan2((y1-cy)/ry,(x1-cx)/rx)
                dt=t2-t1
                if not sf and dt>0: dt-=2*math.pi
                if sf and dt<0: dt+=2*math.pi
                steps=max(8,int(abs(dt)/0.15))
                for k in range(1,steps+1):
                    t=t1+dt*k/steps
                    pts.append((cx+rx*math.cos(t), cy+ry*math.sin(t)))
                cur=[x1,y1]
            else: i+=1
    flush(False)
    return out

# ---------- stroke -> filled stadiums (nonzero union) ----------
def stadium(a,b,r,n=10):
    dx,dy=b[0]-a[0],b[1]-a[1]; L=math.hypot(dx,dy)
    if L<1e-9: 
        return [(a[0]+r*math.cos(2*math.pi*i/(2*n)), a[1]+r*math.sin(2*math.pi*i/(2*n))) for i in range(2*n)]
    ux,uy=dx/L,dy/L; px,py=-uy,ux
    p=[]
    a0=math.atan2(py,px)
    for i in range(n+1): 
        t=a0-math.pi*i/n; p.append((b[0]+r*math.cos(t), b[1]+r*math.sin(t)))
    a1=math.atan2(-py,-px)
    for i in range(n+1):
        t=a1-math.pi*i/n; p.append((a[0]+r*math.cos(t), a[1]+r*math.sin(t)))
    return p

def dashify(poly, dash):
    if not dash: return [poly]
    segs=[]; cur=[poly[0]]; di=0; rem=dash[0]; on=True
    for i in range(1,len(poly)):
        a,b=poly[i-1],poly[i]; L=math.hypot(b[0]-a[0],b[1]-a[1]); t0=0
        while L-t0>rem:
            t0+=rem; f=t0/L
            p=(a[0]+(b[0]-a[0])*f, a[1]+(b[1]-a[1])*f)
            cur.append(p)
            if on and len(cur)>1: segs.append(cur)
            on=not on; cur=[p]; di=(di+1)%len(dash); rem=dash[di]
        rem-=(L-t0); cur.append(b)
    if on and len(cur)>1: segs.append(cur)
    return segs

def stroke_to_polys(sp, w, dash=None):
    out=[]
    for poly,closed in sp:
        p=poly+[poly[0]] if closed else poly
        for piece in dashify(p, dash):
            for i in range(1,len(piece)):
                out.append(stadium(piece[i-1],piece[i],w/2))
    return out

def polys_to_d(polys):
    return " ".join("M"+" L".join(f"{x:.3f} {y:.3f}" for x,y in p)+" Z" for p in polys if len(p)>2)

# ---------- convert one ART markup string to fills only ----------
XIV = ("M32 76 h5 l4 7 l4 -7 h5 l-6.5 10 l6.5 10 h-5 l-4 -7 l-4 7 h-5 l6.5 -10 Z "
       "M48 76 h5 v20 h-5 Z M56 76 h5 l4 13 l4 -13 h5 l-6.5 20 h-5 Z")

def convert(markup, default_w=1.0):
    polys=[]; fills=[]
    for m in re.finditer(r'<(path|circle|ellipse|text)\b([^>]*)/?>', markup):
        tag, attrs = m.group(1), m.group(2)
        def A(k, dflt=None):
            mm=re.search(rf'{k}="([^"]*)"', attrs); return mm.group(1) if mm else dflt
        if tag=='text':
            fills.append(XIV); continue
        if tag=='circle':
            cx,cy,r=float(A('cx')),float(A('cy')),float(A('r'))
            d="M"+" L".join(f"{cx+r*math.cos(2*math.pi*i/64):.3f} {cy+r*math.sin(2*math.pi*i/64):.3f}" for i in range(64))+" Z"
        elif tag=='ellipse':
            cx,cy,rx,ry=float(A('cx')),float(A('cy')),float(A('rx')),float(A('ry'))
            d="M"+" L".join(f"{cx+rx*math.cos(2*math.pi*i/64):.3f} {cy+ry*math.sin(2*math.pi*i/64):.3f}" for i in range(64))+" Z"
        else:
            d=A('d','')
        if not d: continue
        f=A('fill'); s=A('stroke'); sw=A('stroke-width'); da=A('stroke-dasharray')
        w=float(sw) if sw else default_w
        dash=[float(v) for v in re.split(r'[\s,]+', da.strip())] if da else None
        if f!='none': fills.append(d)
        if s!='none':
            polys += stroke_to_polys(subpaths(d), w, dash)
    return " ".join(fills) + " " + polys_to_d(polys)
