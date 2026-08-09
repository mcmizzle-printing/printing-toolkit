import re, math, numpy as np

# ---------- 1. true bounding box of each icon inside its 100x100 box ----------
def path_pts(d):
    pts=[]; cur=[0.0,0.0]; start=[0.0,0.0]
    toks=re.findall(r'([MmLlHhVvCcSsQqTtAaZz])([^MmLlHhVvCcSsQqTtAaZz]*)', d)
    for cmd,arg in toks:
        rel=cmd.islower(); C=cmd.upper()
        if C=='A':
            # arc flags may be written without separators (e.g. "0 0176 0")
            n=[]
            for g in re.finditer(r'(-?[\d.]+)[\s,]*(-?[\d.]+)[\s,]*(-?[\d.]+)[\s,]*([01])[\s,]*([01])[\s,]*(-?[\d.]+)[\s,]*(-?[\d.]+)', arg):
                n += [float(v) for v in g.groups()]
        else:
            n=[float(x) for x in re.findall(r'-?\d*\.?\d+(?:e-?\d+)?', arg)]
        i=0
        if C=='Z': cur=start[:]; continue
        while i < len(n):
            if C=='M':
                x,y=n[i],n[i+1]; i+=2
                cur=[cur[0]+x,cur[1]+y] if rel else [x,y]
                start=cur[:]; pts.append(tuple(cur)); C='L'
            elif C=='L':
                x,y=n[i],n[i+1]; i+=2
                cur=[cur[0]+x,cur[1]+y] if rel else [x,y]; pts.append(tuple(cur))
            elif C=='H':
                x=n[i]; i+=1; cur=[cur[0]+x if rel else x, cur[1]]; pts.append(tuple(cur))
            elif C=='V':
                y=n[i]; i+=1; cur=[cur[0], cur[1]+y if rel else y]; pts.append(tuple(cur))
            elif C in 'CS':
                k=6 if C=='C' else 4
                seg=n[i:i+k]; i+=k
                for j in range(0,len(seg),2):
                    p=(cur[0]+seg[j],cur[1]+seg[j+1]) if rel else (seg[j],seg[j+1]); pts.append(p)
                cur=list(pts[-1])
            elif C in 'QT':
                k=4 if C=='Q' else 2
                seg=n[i:i+k]; i+=k
                for j in range(0,len(seg),2):
                    p=(cur[0]+seg[j],cur[1]+seg[j+1]) if rel else (seg[j],seg[j+1]); pts.append(p)
                cur=list(pts[-1])
            elif C=='A':
                seg=n[i:i+7]; i+=7
                rx,ry=seg[0],seg[1]
                p=(cur[0]+seg[5],cur[1]+seg[6]) if rel else (seg[5],seg[6])
                pts += [(min(cur[0],p[0])-rx*.3, min(cur[1],p[1])-ry*.3),
                        (max(cur[0],p[0])+rx*.3, max(cur[1],p[1])+ry*.3), p]
                cur=list(p)
            else: i+=1
    return pts

def art_bbox(markup):
    pts=[]
    for d in re.findall(r'\sd="([^"]+)"', markup): pts += path_pts(d)
    for cx,cy,r in re.findall(r'<circle cx="([-\d.]+)" cy="([-\d.]+)" r="([-\d.]+)"', markup):
        cx,cy,r=float(cx),float(cy),float(r); pts += [(cx-r,cy-r),(cx+r,cy+r)]
    for m in re.finditer(r'<ellipse cx="([-\d.]+)" cy="([-\d.]+)" rx="([-\d.]+)" ry="([-\d.]+)"', markup):
        cx,cy,rx,ry=map(float,m.groups()); pts += [(cx-rx,cy-ry),(cx+rx,cy+ry)]
    if '<text' in markup: pts += [(28,74),(72,97)]
    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
    pad=2.2   # allow for stroke width
    return min(xs)-pad, min(ys)-pad, max(xs)+pad, max(ys)+pad

# ---------- 2. rasterise a panel, find the largest inscribed rect of a given aspect ----------
def flatten(d):
    pts=[];cur=None;start=None
    for cmd,arg in re.findall(r'([MLAVHQCZ])([^MLAVHQCZ]*)',d):
        n=[float(x) for x in re.findall(r'-?\d*\.?\d+',arg)]
        if cmd=='M': cur=(n[0],n[1]);start=cur;pts.append(cur)
        elif cmd=='L':
            for i in range(0,len(n),2): cur=(n[i],n[i+1]);pts.append(cur)
        elif cmd=='V': cur=(cur[0],n[0]);pts.append(cur)
        elif cmd=='H': cur=(n[0],cur[1]);pts.append(cur)
        elif cmd=='Q':
            for i in range(0,len(n),4):
                x1,y1,x2,y2=n[i:i+4]
                for t in [k/20 for k in range(1,21)]:
                    pts.append(((1-t)**2*cur[0]+2*(1-t)*t*x1+t*t*x2,
                                (1-t)**2*cur[1]+2*(1-t)*t*y1+t*t*y2))
                cur=(x2,y2)
        elif cmd=='A':
            x0,y0=cur
            for i in range(0,len(n),7):
                rx,ry,rot,laf,sf,x1,y1=n[i:i+7]
                dx2,dy2=(x0-x1)/2,(y0-y1)/2
                num=rx*rx*ry*ry-rx*rx*dy2*dy2-ry*ry*dx2*dx2; den=rx*rx*dy2*dy2+ry*ry*dx2*dx2
                co=math.sqrt(max(0,num/den))*(-1 if laf==sf else 1)
                cx,cy=co*rx*dy2/ry+(x0+x1)/2,-co*ry*dx2/rx+(y0+y1)/2
                t1=math.atan2((y0-cy)/ry,(x0-cx)/rx);t2=math.atan2((y1-cy)/ry,(x1-cx)/rx);dt=t2-t1
                if not sf and dt>0: dt-=2*math.pi
                if sf and dt<0: dt+=2*math.pi
                for k in range(1,33): pts.append((cx+rx*math.cos(t1+dt*k/32),cy+ry*math.sin(t1+dt*k/32)))
                cur=(x1,y1);x0,y0=cur
        elif cmd=='Z': cur=start
    return pts

def mask_of(poly, x0,y0,W,H):
    from PIL import Image, ImageDraw
    im=Image.new("1",(W,H),0)
    ImageDraw.Draw(im).polygon([(px-x0,py-y0) for px,py in poly], fill=1)
    return np.array(im, dtype=np.int32)

def best_rect(poly, aspect, inset=5.0):
    """aspect = w/h. Returns (cx, cy, w, h) of the largest inset-safe rect of that aspect."""
    xs=[p[0] for p in poly]; ys=[p[1] for p in poly]
    x0,y0=int(min(xs))-2, int(min(ys))-2
    W,H=int(max(xs)-min(xs))+5, int(max(ys)-min(ys))+5
    m=mask_of(poly,x0,y0,W,H)
    # erode by `inset` so icons never touch the lead line
    k=int(round(inset))
    if k>0:
        e=m.copy()
        for dx in range(-k,k+1):
            for dy in range(-k,k+1):
                if dx*dx+dy*dy>k*k: continue
                e=np.minimum(e, np.roll(np.roll(m,dx,axis=1),dy,axis=0))
        m=e
    ii=np.pad(m,((1,0),(1,0))).cumsum(0).cumsum(1)
    ys_,xs_=np.nonzero(m)
    if len(xs_)==0: return None
    tx,ty=xs_.mean(), ys_.mean()-0.04*H          # aim just above centre of mass
    best=None
    for h in range(int(min(W,H)),5,-1):
        w=int(round(h*aspect))
        if w<4 or w>=W or h>=H: continue
        S=ii[h:,w:]-ii[:-h,w:]-ii[h:,:-w]+ii[:-h,:-w]
        hit=np.argwhere(S==w*h)
        if len(hit)==0: continue
        cxs=hit[:,1]+w/2; cys=hit[:,0]+h/2
        d=(cxs-tx)**2+(cys-ty)**2
        j=int(np.argmin(d))
        best=(cxs[j]+x0, cys[j]+y0, w, h)
        break
    return best
