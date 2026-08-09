import math
# Half-dovetail: SQUARE shelf at the bottom, undercut only on top.
# The rail's first layer is a full-width tongue rooted at the plate edge —
# an ordinary 1.2 mm ledge, not a detached sliver.
#
# The module-level constants below are the shipping joint. `spans()` builds the
# same geometry at any depth, so a coupon ladder exercises this exact span math
# instead of a re-derived copy of it — the module-level functions are themselves
# just `spans()` at DEPTH, and the plate STLs are byte-identical either way.
Z_PLATE = 3.4
Z_LO    = 3.4      # shelf = the back face of the plate; front stays unbroken
Z_HI    = 6.9      # top of the rail at its root — 3.5 mm tall
DEPTH   = 1.2
RIB_TOP = 1.6      # plain rib carried above the undercut
Z_FHI   = Z_HI + 2*DEPTH      # 9.3 — undercut rises 2 for every 1 it reaches
Z_RIB   = 10.9                # 1.6 mm of rib above the undercut
STOP    = 5.0      # solid at the bottom of the channel: the wing lands on this
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
