import math
"""Half-dovetail seam: SQUARE shelf at the bottom, undercut only on top.

READ THIS BEFORE USING IT. **This joint cannot print without supports**, and it
is kept here as a worked example and for the span maths, not as a
recommendation. Two floating regions, both of which scale with depth:

  * the male rail is a 1.02-2.22 mm CANTILEVER off the panel wall, running the
    full length of the seam, with nothing beneath its first layer
  * the female roof begins as a 0.11 mm sliver -- roughly a quarter of one
    extrusion width -- over the open channel, and does not reach a full
    extrusion until 0.84 mm higher

It was designed to fix an earlier failure where the male rail started as a
detached sliver, by making its first layer full-width and rooted at the panel
edge. That fix does not work: **rooted sideways is not supported.** It traded a
detached sliver for an unsupported shelf and kept the mid-air start. The mesh is
watertight and sits on the bed, which is exactly why that pair of checks is not
enough -- run a cantilever check as well.

If you want a hidden joint that does print unsupported, see `bowtie.py`: a
separate two-flank key spanning the seam, with sockets only on both panels, so
nothing protrudes past a panel's footprint and nothing begins in air.

THE CONSTANTS BELOW ARE EXAMPLE VALUES, NOT YOURS. They are the dimensions of
the window this module was extracted from -- a 3.4 mm panel with a 10.9 mm rib.
A consuming project should define its own geometry and pass it to `spans()`,
which builds the same shape at any depth. Do not import Z_PLATE from a shared
library to find out how thick your own panel is.
"""
Z_PLATE = 3.4      # example: panel thickness of the originating project
Z_LO    = 3.4      # shelf = the back face of the panel; the front stays unbroken
Z_HI    = 6.9      # top of the rail at its root -- 3.5 mm tall
DEPTH   = 1.2
RIB_TOP = 1.6      # plain rib carried above the undercut
Z_FHI   = Z_HI + 2*DEPTH      # 9.3 -- undercut rises 2 for every 1 it reaches
Z_RIB   = 10.9                # 1.6 mm of rib above the undercut
STOP    = 5.0      # solid at the bottom of the channel: the panel edge lands here
STOP_CLR= 0.30


def spans(depth=DEPTH, z_lo=Z_LO, z_hi=Z_HI, rib_top=RIB_TOP):
    """Half-dovetail span functions at an arbitrary undercut depth.

    Shelf height (z_lo..z_hi) and the 2:1 undercut slope are held fixed, so
    varying `depth` alone isolates engagement depth as the single variable.
    Returns (channel_span, rail_span, geom) where geom carries the derived
    heights the caller needs to size a coupon.
    """
    z_fhi = z_hi + 2*depth
    z_rib = z_fhi + rib_top

    def channel_span(z):
        if z < z_lo or z > z_fhi: return None
        if z <= z_hi: return (0.0, depth)
        return (depth*(z-z_hi)/(z_fhi-z_hi), depth)

    def rail_span(z, clr=0.18):
        lo, hi, fhi = z_lo+0.10, z_hi-0.10, z_fhi-0.25
        d = depth-clr
        if z < lo or z > fhi: return None
        if z <= hi: return (0.0, d)
        return (d*(z-hi)/(fhi-hi), d)

    geom = dict(depth=depth, z_lo=z_lo, z_hi=z_hi, z_fhi=z_fhi, z_rib=z_rib,
                rib_top=rib_top, shelf=z_hi-z_lo)
    return channel_span, rail_span, geom


channel_span, rail_span, _GEOM = spans()
