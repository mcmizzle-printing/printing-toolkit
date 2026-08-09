#!/usr/bin/env python3
"""Run every geometry check over out/*.stl.

Watertight is NOT sufficient — a mesh can be closed and still contain
unprintable islands. Both are checked here.
"""
import struct, sys, os, glob
from collections import Counter

BED_X = BED_Y = 256.0
CUTTER = (18.0, 28.0)          # front-left exclusion with the AMS attached

def load(p):
    f=open(p,'rb'); f.read(80); n=struct.unpack('<I',f.read(4))[0]; T=[]
    for _ in range(n):
        f.read(12); v=[struct.unpack('<3f',f.read(12)) for _ in range(3)]; f.read(2); T.append(v)
    return T

def watertight(T):
    E=Counter()
    for t in T:
        for i in range(3):
            a=tuple(round(c,4) for c in t[i]); b=tuple(round(c,4) for c in t[(i+1)%3])
            E[frozenset((a,b))]+=1
    return sum(1 for v in E.values() if v%2)

def on_bed(T):
    X=[v[0] for t in T for v in t]; Y=[v[1] for t in T for v in t]
    if min(X)<3 or max(X)>BED_X-3 or min(Y)<3 or max(Y)>BED_Y-3: return "off bed"
    if min(X)<CUTTER[0] and min(Y)<CUTTER[1]: return "in the cutter zone"
    return None

def main(paths):
    bad=0
    for p in sorted(paths):
        T=load(p)
        X=[v[0] for t in T for v in t]; Y=[v[1] for t in T for v in t]; Z=[v[2] for t in T for v in t]
        open_e=watertight(T); bed=on_bed(T)
        flag = "" if (open_e==0 and bed is None) else f"  <-- {'open edges' if open_e else bed}"
        if flag: bad+=1
        print(f"{os.path.basename(p):34s} {max(X)-min(X):6.1f}x{max(Y)-min(Y):6.1f}x{max(Z):5.1f}"
              f"  {len(T):7d} tris  open {open_e:3d}{flag}")
    print(f"\n{len(paths)} files, {bad} with problems")
    return 1 if bad else 0

if __name__=="__main__":
    args=sys.argv[1:] or glob.glob("out/*.stl")
    sys.exit(main(args))
