"""Merge a stack of per-filament STLs into the single solid that goes on the bed.

A multi-colour part is authored as one file per filament, but it prints as ONE
object -- the levels are stacked IN PLACE, not laid out side by side. Checking a
level on its own tells you almost nothing: a level starting at z=2.60 floats in
mid air because the body it stands on lives in a different file, so islands.py
reports cantilevers that do not exist, and reports nothing about the ones that
do. Merge first, then check.

That distinction hid ten cantilevers, up to 3.50 mm, in the project this came
from -- every one of them invisible while the levels were checked separately.

    python3 tests/assemble_stl.py 'out/PART-*.stl' /tmp/assembled.stl
    python3 tests/islands.py /tmp/assembled.stl

The output is a union of interpenetrating solids, so it is deliberately NOT
watertight -- run check_all.py on the source files, not on this.
"""
import glob, struct, sys

def load(p):
    f=open(p,'rb'); f.read(80); n=struct.unpack('<I',f.read(4))[0]; T=[]
    for _ in range(n):
        f.read(12)
        v=[struct.unpack('<3f',f.read(12)) for _ in range(3)]; f.read(2)
        T.append(tuple(v))
    return T

# NO DEFAULT GLOB. It used to fall back to one project's own file names, which
# in a shared tool means a bare run silently assembles somebody else's parts --
# or, more often, nothing at all, and reports success.
if len(sys.argv) < 2:
    sys.exit("usage: assemble_stl.py '<glob>' [out.stl]\n"
             "       assemble_stl.py 'out/PART-*.stl' /tmp/assembled.stl")
src=sorted(glob.glob(sys.argv[1]))
if not src:
    sys.exit(f"no files match {sys.argv[1]!r}")
out=sys.argv[2] if len(sys.argv)>2 else "/tmp/assembled.stl"
T=[]
for p in src:
    t=load(p); T+=t
    print(f"  {p:32s} {len(t):6d} tris")

def norm(a,b,c):
    u=(b[0]-a[0],b[1]-a[1],b[2]-a[2]); v=(c[0]-a[0],c[1]-a[1],c[2]-a[2])
    n=(u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
    L=(n[0]**2+n[1]**2+n[2]**2)**0.5 or 1.0
    return (n[0]/L,n[1]/L,n[2]/L)

with open(out,'wb') as f:
    f.write(b'\0'*80); f.write(struct.pack('<I',len(T)))
    for a,b,c in T:
        f.write(struct.pack('<3f',*norm(a,b,c)))
        for v in (a,b,c): f.write(struct.pack('<3f',*v))
        f.write(b'\0\0')
print(f"-> {out}  {len(T)} tris from {len(src)} levels")
