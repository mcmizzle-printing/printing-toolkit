#!/usr/bin/env python3
"""Self-test for stackcheck.py, against synthetic parts with known answers.

The medallion's rays passed watertight, on-bed, island, cantilever and overhang
checks while slicing to literally nothing, so a green stackcheck run has to be
worth something before it is trusted. Two synthetic stacks, both with an answer
known in advance:

  vanishing   a normal disc plus a sliver far thinner than one extrusion
              -> the sliver must be reported as printing nothing, the disc must not

  overlap     a wide disc, then a narrow disc concentric inside it
              -> both must print, and if the LATER part wins the shared volume
                 the wide one is clipped to an annulus, so its inner radius
                 jumps from 0 to the narrow disc's edge

Plus a third case that needs no slicer: WHICH FILAMENT OPENS LAYER 1. Bambu emits
no T command for it, and it is not always filament 1 -- assuming it was is what
filed #23 as "the came does not print on layer 1" when the came in fact prints
first. Synthetic gcode is used deliberately: the two slicing cases above cannot
force Bambu to start on a late part, so the one condition that actually broke is
the one a real slice will not reproduce on demand.

Slow -- the first two cases are real headless slices. Run it when stackcheck.py
changes.
"""
import math, os, re, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stackcheck import initial_tool, read_gcode


def norm(a, b, c):
    u = (b[0]-a[0], b[1]-a[1], b[2]-a[2]); v = (c[0]-a[0], c[1]-a[1], c[2]-a[2])
    n = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
    L = math.sqrt(n[0]**2 + n[1]**2 + n[2]**2) or 1.0
    return (n[0]/L, n[1]/L, n[2]/L)


def save(tris, path):
    with open(path, "wb") as f:
        f.write(b"\0" * 80); f.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            f.write(struct.pack("<3f", *norm(a, b, c)))
            for p in (a, b, c):
                f.write(struct.pack("<3f", *p))
            f.write(b"\0\0")


def disc(cx, cy, r, z0, z1, seg=64):
    ring = [(cx + r*math.cos(2*math.pi*i/seg), cy + r*math.sin(2*math.pi*i/seg))
            for i in range(seg)]
    T = []
    for i in range(seg):
        x0, y0 = ring[i]; x1, y1 = ring[(i + 1) % seg]
        T += [((cx, cy, z0), (x1, y1, z0), (x0, y0, z0)),
              ((cx, cy, z1), (x0, y0, z1), (x1, y1, z1)),
              ((x0, y0, z0), (x1, y1, z0), (x1, y1, z1)),
              ((x0, y0, z0), (x1, y1, z1), (x0, y0, z1))]
    return T


def box(x0, x1, y0, y1, z0, z1):
    v = [(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),
         (x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
    T = []
    for a, b, c, d in [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]:
        T += [(v[a], v[b], v[c]), (v[a], v[c], v[d])]
    return T


def run(pattern):
    p = subprocess.run([sys.executable, os.path.join(HERE, "stackcheck.py"), pattern],
                       capture_output=True, text=True)
    return p.stdout + p.stderr


def level(out, name):
    for line in out.splitlines():
        if name in line:
            return line
    return ""


fails = []
wd = tempfile.mkdtemp()

# ---- case 1: a level thinner than one extrusion must be caught ---------------
save(disc(128, 128, 12, 0, 2), os.path.join(wd, "VAN-1-disc.stl"))
save(box(127.9, 128.1, 118, 138, 2, 2.5), os.path.join(wd, "VAN-2-sliver.stl"))
out = run(os.path.join(wd, "VAN-*.stl"))

if "PRINTS NOTHING" not in level(out, "VAN-2-sliver"):
    fails.append("a 0.2 mm sliver was NOT reported as printing nothing")
if "PRINTS NOTHING" in level(out, "VAN-1-disc"):
    fails.append("a solid 24 mm disc was wrongly reported as printing nothing")

# ---- case 2: the later part must win the shared volume ----------------------
save(disc(128, 128, 12, 0, 2), os.path.join(wd, "OVL-1-wide.stl"))
save(disc(128, 128, 6, 0, 2), os.path.join(wd, "OVL-2-narrow.stl"))
out2 = run(os.path.join(wd, "OVL-*.stl"))

wide, narrow = level(out2, "OVL-1-wide"), level(out2, "OVL-2-narrow")
if "PRINTS NOTHING" in wide or "PRINTS NOTHING" in narrow:
    fails.append("one of two solid overlapping discs printed nothing")
else:
    m = re.search(r"r\s+([0-9.]+)\.\.\s*([0-9.]+)", wide)
    if not m:
        fails.append(f"could not read the wide disc's radial extent from: {wide!r}")
    elif float(m.group(1)) < 4.0:
        fails.append(
            f"the earlier part reaches r={m.group(1)}, so it was NOT clipped by the "
            "later one -- the later-part-wins rule stackcheck documents is wrong")

# ---- case 3: which filament opens layer 1 (no slicer needed) ----------------
# Bambu emits no T for the tool already loaded, so layer 1 begins unlabelled.
# Real gcode from the pane-7 tile opened on T7, the came.

def gc(path, body, used, total_mm=None):
    """Synthetic gcode. `used` is the 0-indexed tools that laid material.

    The "; filament:" header is not decoration -- real Bambu gcode always
    carries it, it is 1-indexed, and it is the only thing that distinguishes a
    part that vanished from the part that opened the print. Omitting it here
    would make these cases easier than the real ones.

    `total_mm` is the per-extruder header total, listed for USED extruders only
    and in ascending order, exactly as Bambu writes it. Pass it to exercise the
    arithmetic rule; leave it off and the earlier rules have to carry the case.
    """
    head = "; HEADER\n; filament: " + ",".join(str(t + 1) for t in sorted(used)) + "\n"
    if total_mm is not None:
        head += "; total filament length [mm] : " + ",".join(
            f"{v:.4f}" for v in total_mm) + "\n"
    with open(path, "w") as f:
        f.write(head + body)
    return path


def moves(k, x0=128.0):
    """k extrusion moves near the bed centre, so read_gcode's radius filter keeps them."""
    return "".join(f"G1 X{x0 + 0.4 * i:.2f} Y128.00 E0.1\n" for i in range(1, k + 1))


c3 = []

# (a) the ordinary case: three of four tools named explicitly on layer 1, so
#     the fourth is the one already loaded. This is the pane-7 tile's shape.
p = gc(os.path.join(wd, "a.gcode"),
       "; CHANGE_LAYER\n" + moves(5) + "T2\n" + moves(3) + "T0\n" + moves(3) +
       "T1\n" + moves(3) + "; CHANGE_LAYER\n" + "T3\n" + moves(3), used={0, 1, 2, 3})
got, why = initial_tool(p, 4)
if got != 3:
    c3.append(f"(a) opening tool read as {got}, not T3 ({why})")

# (b) the case the old parser could not see: part 1 VANISHES and a different
#     tool opens. Both are absent from layer 1's selections, so elimination
#     alone is ambiguous -- only "; filament:" says which of the two printed.
p = gc(os.path.join(wd, "b.gcode"),
       "; CHANGE_LAYER\n" + moves(5) + "T1\n" + moves(3) + "T2\n" + moves(3) +
       "; CHANGE_LAYER\n" + "T3\n" + moves(3) + "T1\n" + moves(3), used={1, 2, 3})
got, why = initial_tool(p, 4)
if got != 3:
    c3.append(f"(b) with a vanished part 1 the opening tool read as {got}, not T3 ({why})")

# (c) genuinely ambiguous -> must say so, never fall back to tool 0
p = gc(os.path.join(wd, "c.gcode"),
       "; CHANGE_LAYER\n" + moves(5) + "T1\n" + moves(3), used={0, 1, 2, 3})
got, why = initial_tool(p, 4)
if got is not None:
    c3.append(f"(c) an ambiguous file resolved to T{got} instead of reporting why")

# (e) the MEDALLION's shape, and the one that caught an unsound rule: the
#     opening part finishes before the first tool change, so it is never named
#     by any T command at all. "Narrow to tools named somewhere" discards
#     precisely the right answer here.
p = gc(os.path.join(wd, "e.gcode"),
       "; CHANGE_LAYER\n" + moves(5) + "; CHANGE_LAYER\n" + moves(5) +
       "; CHANGE_LAYER\n" + "T1\n" + moves(3), used={0, 1})
got, why = initial_tool(p, 2)
if got != 0:
    c3.append(f"(e) an opener that is never named read as {got}, not T0 ({why})")

# (d) the attribution itself: the opening block must be booked to that tool
p = gc(os.path.join(wd, "d.gcode"),
       "; CHANGE_LAYER\n" + moves(4) + "T0\n" + moves(2), used={0, 1})
init, _ = initial_tool(p, 2)
per, _seen = read_gcode(p, (128.0, 128.0), init)
tot = {}
for v in per.values():
    for t, d in v.items():
        tot[t] = tot.get(t, 0) + d[0]
if init != 1:
    c3.append(f"(d) opening tool read as {init}, not T1")
elif tot.get(1, 0) <= tot.get(0, 0):
    c3.append(f"(d) the opening block was not credited to T1: {tot}")
# and the bug itself, stated as the property it violated
if tot.get(1, 0) == 0:
    c3.append("(d) T1 reported as printing nothing while it laid the first block "
              "-- this is issue #23 exactly")

# (f) the COLOUR LADDER's shape, which neither rule above reaches: layer 1 has
#     no tool change at all (only the clear base prints that low), and the base
#     IS named on later layers, so it is neither missing-from-layer-1 nor
#     never-named. Only arithmetic against the slicer's own per-extruder totals
#     resolves it -- T0 is short by exactly the unlabelled opening block.
#     Real figures: 3.68 g accounted against a 9.92 g header, block 6.25 g.
p = gc(os.path.join(wd, "f.gcode"),
       "; CHANGE_LAYER\n" + moves(5) +                       # 0.5 mm, unlabelled
       "; CHANGE_LAYER\n" + "T1\n" + moves(3) +               # 0.3 mm on T1
       "T0\n" + moves(2),                                     # 0.2 mm on T0
       used={0, 1}, total_mm=[0.7, 0.3])                      # so T0 owns the block
got, why = initial_tool(p, 2)
if got != 0:
    c3.append(f"(f) the arithmetic rule read the opener as {got}, not T0 ({why})")

# (g) ...and it must not fire when the books do NOT single anyone out. Same
#     shape, but a header that balances without the opening block belonging to
#     either tool -- guessing here would be the original bug in a new costume.
p = gc(os.path.join(wd, "g.gcode"),
       "; CHANGE_LAYER\n" + moves(5) +
       "; CHANGE_LAYER\n" + "T1\n" + moves(3) + "T0\n" + moves(2),
       used={0, 1}, total_mm=[9.9, 9.9])
got, why = initial_tool(p, 2)
if got is not None:
    c3.append(f"(g) books that single nobody out still resolved to T{got}")

fails += c3

print(out)
print(out2)
print(f"opening-filament cases: {'all passed' if not c3 else 'FAILED'}")
if fails:
    print("FAIL")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("stackcheck self-test: 2 slicing cases + 7 opening-filament cases, all passed")
