import math

def splice_dovetails(poly, seam_x, centres, D=6.5, h=3.4, F=2.0, clr=0.0, tol=0.08):
    """Insert dovetail features where the outline runs along x == seam_x.
       Material on the right of travel -> socket; on the left -> tail.
       Same point sequence produces both; winding decides which."""
    out=[]; n=len(poly)
    for i in range(n):
        a=poly[i]; b=poly[(i+1)%n]
        out.append(a)
        if abs(a[0]-seam_x)>tol or abs(b[0]-seam_x)>tol: continue
        up = b[1] > a[1]
        lo,hi = (a[1],b[1]) if up else (b[1],a[1])
        cs=[c for c in centres if lo+h+F+2 < c < hi-h-F-2]
        cs.sort(reverse=not up)
        hh=h-clr; DD=D-clr; FF=F
        for c in cs:
            if up:
                out += [(seam_x, c-hh), (seam_x+DD, c-hh-FF),
                        (seam_x+DD, c+hh+FF), (seam_x, c+hh)]
            else:
                out += [(seam_x, c+hh), (seam_x+DD, c+hh+FF),
                        (seam_x+DD, c-hh-FF), (seam_x, c-hh)]
    return out
