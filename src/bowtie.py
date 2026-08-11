"""Butterfly key: a two-flank dovetail carried by a separate part.

A moulded-in dovetail on a printed panel has to put its flare on one of two
caged axes. Through the thickness, it is floored by the panel's back face, so
it can only flare one way -- and the male tongue then protrudes past the panel's
footprint and begins in mid-air. Across the joint, it is capped by whatever
width the surrounding material allows. Either way the flare stays small and the
male side is the fragile part.

A separate key escapes both. It prints standing on the bed, every layer
identical, so the overhang rule does not apply to its plan shape at all and the
shoulders can be SQUARE -- no sloped flank means nothing to cam out of. The
flare runs along the joint line, which is normally the one unconstrained axis.
Both panels become female: sockets are constant cross-section voids opening
upward, so nothing bridges and nothing cantilevers.

    plan view, joint line running vertically through the waist

        ####|####          lobe   -- wide, trapped
        ####|####
          ##|##            neck   -- narrow, spans the joint
        ####|####
        ####|####          lobe

Retention against the panels separating is the square shoulder where lobe meets
neck. The two socket webs meet at the joint face and press into each other, so
they carry that load in compression rather than shear.

Z retention is a nipple/dimple detent on the lobe flanks: a nipple standing
proud of the key, a deeper dimple in the socket, held over a land tall enough to
give the shoulder something to catch.

The defaults below (0.55 / 0.70 / 1.20 / 0.22) came off a coupon and work, but
they are ONE consumer's proven numbers, not a property of butterfly keys. This
docstring used to call them "the same pair used for snap-in tiles"; that was
wrong -- the caller whose keys these are runs a quite different pair on its
tiles -- and naming another part of a consumer's design here was the boundary
error as much as the inaccuracy. Pass your own via profile().

This module supplies profile math only -- widths at a given height and the x
ranges -- and leaves meshing to the caller, the same split rib3.py uses.
"""

KEY_CLR = 0.20                              # clearance per side, proven fit
# Defaults only. A caller that cares should pass its own to profile() -- these
# are dimensions, and dimensions belong to the project, not to a shared library.
NIP, DIMP, LAND, RAMP = 0.55, 0.70, 1.20, 0.22


def profile(neck=3.0, lobe=6.0, reach=2.2, neck_half=1.2, height=7.5,
            clr=KEY_CLR, detent=True,
            nip=NIP, dimp=DIMP, land=LAND, ramp=RAMP):
    """Key and socket half-widths as a function of height up the key.

    neck       width of the waist, across the joint line
    lobe       width of each lobe -- the bite is (lobe-neck)/2 per side
    reach      how far each lobe extends from the joint line into its panel
    neck_half  half-length of the waist; sets the socket's shoulder web, which
               is what the lobe actually bears against. Keep it at two
               extrusion widths or more -- a thin web is the weak link, not the
               key, whose waist is loaded in tension and enormously strong.
    height     how tall the key stands in the socket

    Returns (key_hw, sock_hw, geom). Both take a height measured from the
    socket floor and return a lobe half-width.
    """
    dz = height/2.0
    lo, hi = dz - land/2, dz + land/2

    def band(zl):
        if lo <= zl < hi:                              return "full"
        if lo-ramp <= zl < lo or hi <= zl < hi+ramp:   return "ramp"
        return None

    def key_hw(zl):
        b = band(zl) if detent else None
        return lobe/2 + (nip if b == "full" else ramp if b == "ramp" else 0.0)

    def sock_hw(zl):
        b = band(zl) if detent else None
        return lobe/2 + clr + (dimp if b == "full" else ramp if b == "ramp" else 0.0)

    geom = dict(
        neck=neck, lobe=lobe, reach=reach, neck_half=neck_half,
        height=height, clr=clr, detent=detent,
        nip=nip, dimp=dimp, land=land, ramp=ramp,
        bite=(lobe-neck)/2.0,          # square shoulder depth, per side
        shoulder=neck_half-clr,        # socket web between cavity and joint face
        neck_hw=neck/2.0,              # key waist half-width
        sock_neck_hw=neck/2.0+clr,     # socket waist half-width
        sock_neck_x=neck_half-clr,     # socket waist runs out to here
        sock_lobe_x=(neck_half-clr, reach+clr),   # socket lobe cavity, in x
        key_lobe_x=(neck_half, reach),            # key lobe, in x
    )
    return key_hw, sock_hw, geom


def wall(came, geom):
    """Material left outboard of the socket in a came of the given width."""
    return came - geom["sock_lobe_x"][1]
