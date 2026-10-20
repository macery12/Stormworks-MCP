"""Per-face paint: which surface of a part each colour in its `sc` list paints.

A part's `sc` holds one colour per surface, in the order its game definition lists them
(`<surfaces>`: a voxel position, an orientation 0..5 = +x, -x, +y, -y, +z, -z, and a shape code).
The order of the faces within the x and z pairs is not yet confirmed in game, so by default
paint gives both faces of those pairs the same colour (see `PAIRS_CONFIRMED`); a hull skin
only ever shows one face of a pair, so that loses nothing on a hull.
"""
from functools import cache

from .pieces import BY_NAME, DIRS, apply

# Set True once `paint faces` (tools/paint_faces_exhibit.py) is checked in game.
PAIRS_CONFIRMED = False

# Surface lists of the built-in pieces, copied from the game definitions (tests compare them).
SURFACES = {
    "01_block": (((0,0,0),4,1), ((0,0,0),5,1), ((0,0,0),2,1), ((0,0,0),3,1), ((0,0,0),1,1), ((0,0,0),0,1),),
    "01_block_weight": (((0,0,0),4,5), ((0,0,0),5,5), ((0,0,0),2,5), ((0,0,0),3,5), ((0,0,0),1,5), ((0,0,0),0,5),),
    "02_wedge": (((0,0,0),1,2), ((0,0,0),0,2), ((0,0,0),4,1), ((0,0,0),3,1), ((0,0,0),5,6),),
    "03_pyramid": (((0,0,0),0,2), ((0,0,0),4,2), ((0,0,0),3,2), ((0,0,0),5,7),),
    "04_invpyramid": (((0,0,0),0,1), ((0,0,0),4,1), ((0,0,0),3,1), ((0,0,0),2,2), ((0,0,0),1,2), ((0,0,0),5,2), ((0,0,0),5,8),),
    "05_wedge_2": (((0,0,0),1,9), ((0,0,0),0,11), ((0,0,0),4,1), ((0,0,0),3,1), ((0,0,0),5,21), ((0,0,-1),1,10), ((0,0,-1),5,22), ((0,0,-1),0,12), ((0,0,-1),3,1),),
    "06_pyramid_2": (((0,0,0),0,11), ((0,0,-1),0,12), ((0,0,0),3,9), ((0,0,-1),3,10), ((0,0,0),4,2), ((0,0,0),5,27), ((0,0,-1),5,28),),
    "07_invpyramid_2": (((0,0,0),0,1), ((0,0,0),4,1), ((0,0,0),3,1), ((0,0,0),2,11), ((0,0,0),1,9), ((0,0,0),5,47), ((0,0,-1),0,1), ((0,0,-1),3,1), ((0,0,-1),1,10), ((0,0,-1),2,12), ((0,0,-1),5,48), ((0,0,-1),5,2),),
    "11_pyramid_2x2": (((0,0,0),0,11), ((0,0,0),4,9), ((0,0,0),3,1), ((0,0,-1),0,12), ((-1,0,0),4,10), ((0,0,-1),3,2), ((-1,0,0),3,2), ((0,0,0),2,33), ((0,0,-1),2,34), ((-1,0,0),2,34),),
    "14_invpyramid_2x2": (((0,0,0),0,1), ((0,0,0),4,1), ((0,0,0),3,1), ((0,0,-1),0,1), ((-1,0,0),4,1), ((0,0,-1),3,1), ((-1,0,0),3,1), ((0,0,0),2,1), ((0,0,-1),2,54), ((0,0,-1),2,2), ((-1,0,0),2,54), ((-1,0,0),2,2), ((-1,0,-1),2,53), ((0,0,-1),5,11), ((-1,0,-1),5,12), ((-1,0,0),1,9), ((-1,0,-1),1,10), ((-1,0,-1),3,1),),
    "08_wedge_4": (((0,0,0),1,13), ((0,0,0),0,17), ((0,0,0),4,1), ((0,0,0),3,1), ((0,0,-1),1,14), ((0,0,-1),0,18), ((0,0,-1),3,1), ((0,0,-2),1,15), ((0,0,-3),1,16), ((0,0,-2),3,1), ((0,0,-3),3,1), ((0,0,-3),0,20), ((0,0,-2),0,19), ((0,0,0),5,23), ((0,0,-1),5,24), ((0,0,-2),5,25), ((0,0,-3),5,26),),
    "09_pyramid_4": (((0,0,0),0,17), ((0,0,0),4,2), ((0,0,0),3,13), ((0,0,0),5,29), ((0,0,-1),5,30), ((0,0,-2),5,31), ((0,0,-3),5,32), ((0,0,-1),0,18), ((0,0,-2),0,19), ((0,0,-3),0,20), ((0,0,-1),3,14), ((0,0,-2),3,15), ((0,0,-3),3,16),),
    "10_invpyramid_4": (((0,0,0),0,1), ((0,0,0),4,1), ((0,0,0),3,1), ((0,0,0),2,17), ((0,0,0),1,13), ((0,0,0),5,49), ((0,0,-1),5,50), ((0,0,-2),5,51), ((0,0,-3),5,52), ((0,0,-1),2,18), ((0,0,-2),2,19), ((0,0,-3),2,20), ((0,0,-3),0,1), ((0,0,-2),0,1), ((0,0,-1),0,1), ((0,0,-1),3,1), ((0,0,-2),3,1), ((0,0,-3),3,1), ((0,0,-1),1,14), ((0,0,-2),1,15), ((0,0,-3),1,16), ((0,0,-3),5,2),),
    "12_pyramid_2x4": (((0,0,0),0,17), ((0,0,0),4,9), ((0,0,0),3,1), ((0,0,-1),0,18), ((-1,0,0),4,10), ((0,0,-1),3,1), ((-1,0,0),3,9), ((0,0,-3),0,20), ((0,0,-2),0,19), ((0,0,-3),3,10), ((0,0,-2),3,9), ((-1,0,-1),3,10), ((0,0,-3),2,38), ((0,0,-2),2,37), ((0,0,-1),2,36), ((0,0,0),2,35), ((-1,0,0),2,37), ((-1,0,-1),2,38),),
    "15_invpyramid_2x4": (((0,0,0),0,1), ((0,0,-1),0,1), ((0,0,-2),0,1), ((0,0,-3),0,1), ((0,0,0),4,1), ((-1,0,0),4,1), ((0,0,0),2,1), ((0,0,-1),2,1), ((-1,0,0),2,11), ((-1,0,-1),2,12), ((0,0,-2),2,11), ((0,0,-3),2,12), ((0,0,-3),5,11), ((-1,0,-3),5,12), ((-1,0,0),1,13), ((-1,0,-1),1,14), ((-1,0,-2),1,15), ((-1,0,-3),1,16), ((-1,0,0),2,58), ((-1,0,-1),2,57), ((-1,0,-2),2,56), ((0,0,-2),2,58), ((-1,0,-3),2,55), ((0,0,-3),2,57), ((0,0,-3),3,1), ((0,0,-1),3,1), ((0,0,-2),3,1), ((0,0,0),3,1), ((-1,0,-3),3,1), ((-1,0,-2),3,1), ((-1,0,-1),3,1), ((-1,0,0),3,1),),
    "13_pyramid_4x4": (((0,0,0),0,17), ((0,0,0),4,13), ((0,0,0),3,1), ((0,0,-1),0,18), ((-1,0,0),4,14), ((0,0,-1),3,1), ((-1,0,0),3,1), ((-2,0,0),4,15), ((-3,0,0),4,16), ((0,0,-2),0,19), ((0,0,-3),0,20), ((-2,0,0),3,1), ((-1,0,-1),3,1), ((0,0,-2),3,1), ((0,0,-3),3,2), ((-1,0,-2),3,2), ((-2,0,-1),3,2), ((-3,0,0),3,2), ((0,0,-3),2,46), ((-1,0,-2),2,46), ((-2,0,-1),2,46), ((-3,0,0),2,46), ((0,0,-2),2,45), ((-1,0,-1),2,45), ((-2,0,0),2,45), ((0,0,-1),2,44), ((-1,0,0),2,44), ((0,0,0),2,43),),
    "16_invpyramid_4x4": (((0,0,0),3,1), ((0,0,-1),3,1), ((-1,0,0),3,1), ((-2,0,0),3,1), ((-1,0,-1),3,1), ((0,0,-2),3,1), ((0,0,0),0,1), ((0,0,-1),0,1), ((0,0,-2),0,1), ((0,0,-3),0,1), ((0,0,0),4,1), ((-1,0,0),4,1), ((-2,0,0),4,1), ((-3,0,0),4,1), ((0,0,0),2,1), ((0,0,-1),2,1), ((0,0,-2),2,1), ((-1,0,-1),2,1), ((-1,0,0),2,1), ((-2,0,0),2,1), ((-3,0,0),2,2), ((-2,0,-1),2,2), ((-1,0,-2),2,2), ((0,0,-3),2,2), ((0,0,-3),5,17), ((-1,0,-3),5,18), ((-2,0,-3),5,19), ((-3,0,-3),5,20), ((-3,0,0),1,13), ((-3,0,-1),1,14), ((-3,0,-2),1,15), ((-3,0,-3),1,16), ((-3,0,0),2,66), ((-2,0,-1),2,66), ((-1,0,-2),2,66), ((0,0,-3),2,66), ((-3,0,-1),2,65), ((-2,0,-2),2,65), ((-1,0,-3),2,65), ((-3,0,-2),2,64), ((-2,0,-3),2,64), ((-3,0,-3),2,63), ((-3,0,0),3,1), ((-2,0,-1),3,1), ((-3,0,-1),3,1), ((-1,0,-2),3,1), ((-2,0,-2),3,1), ((0,0,-3),3,1), ((-1,0,-3),3,1), ((-3,0,-2),3,1), ((-2,0,-3),3,1), ((-3,0,-3),3,1),),
}


def _sloped(shape):
    """Shape codes of sloped surfaces; 1 is a full square, 2 a triangle and 9-20 the partial
    triangles and trapezoids on the flat sides of long slopes."""
    return shape in (6, 7, 8) or shape >= 21


def _through(poly, cell):
    """Does the polygon pass through the voxel `cell` (sampled)?"""
    n = len(poly)
    pts = list(poly)
    for i in range(1, n - 1):
        a, b, c = poly[0], poly[i], poly[i + 1]
        for s in range(1, 8):
            for t in range(1, 8 - s):
                w = (s / 8, t / 8)
                pts.append(tuple(a[k] + w[0] * (b[k] - a[k]) + w[1] * (c[k] - a[k]) for k in range(3)))
    return any(all(abs(p[k] - cell[k]) < 0.5 - 1e-6 for k in range(3)) for p in pts)


def _normal(poly):
    n = [0.0, 0.0, 0.0]
    for p, q in zip(poly, poly[1:] + poly[:1]):
        n[0] += (p[1] - q[1]) * (p[2] + q[2])
        n[1] += (p[2] - q[2]) * (p[0] + q[0])
        n[2] += (p[0] - q[0]) * (p[1] + q[1])
    length = sum(c * c for c in n) ** 0.5 or 1.0
    return tuple(c / length for c in n)


@cache
def entries(d):
    """[(local cell, local outward normal)] in `sc` order for definition d. A flat surface's
    normal is its axis; a sloped one's is the sloped face of the piece through that cell."""
    piece = BY_NAME.get(d)
    surfaces = SURFACES.get(d)
    if surfaces is None:
        from . import definitions  # noqa: PLC0415
        data = definitions.metadata(d) or {}
        return tuple((tuple(s["position"]), DIRS[s["orientation"]]) for s in data.get("attachment_surfaces", [])
                     if isinstance(s["position"][0], int) and 0 <= s["orientation"] < 6)
    polys = []
    centre = tuple(sum(v[i] for v in piece.verts) / len(piece.verts) for i in range(3))
    for f in piece.faces:
        pts = [piece.verts[i] for i in f]
        n = _normal(pts)
        fc = tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))
        if sum(n[i] * (fc[i] - centre[i]) for i in range(3)) < 0:
            n = tuple(-c for c in n)
        polys.append((pts, n))
    out = []
    for cell, o, shape in surfaces:
        d_ = DIRS[o]
        if not _sloped(shape):
            out.append((cell, d_))
            continue
        # Every catalogue slope piece has one sloped plane; the sampled test only breaks ties.
        slopes = [n for pts, n in polys if max(abs(c) for c in n) < 0.999 and _through(pts, cell)] or [
            n for _pts, n in polys if max(abs(c) for c in n) < 0.999]
        slopes.sort(key=lambda n: -sum(n[i] * d_[i] for i in range(3)))
        out.append((cell, slopes[0] if slopes else d_))
    return tuple(out)


def world(p):
    """[(world cell, world normal)] for each `sc` entry of part p."""
    return [(tuple(p.origin[i] + c for i, c in enumerate(apply(p.Q, cell))), apply(p.Q, n))
            for cell, n in entries(p.piece.d)]


def paint(p, colour_at, exposed=None, painted=None):
    """Colours for every `sc` entry of p: colour_at(world cell, world normal) -> hex. Unless
    PAIRS_CONFIRMED, the two faces of a local x or z pair in one cell share a colour: the colour
    of the face `exposed(cell, normal)` says is visible; if both or neither are, the one
    `painted(cell, normal)` says carries a paint item (a marking beats the plain scheme)."""
    faces = world(p)
    cols = [colour_at(cell, n) for cell, n in faces]
    if PAIRS_CONFIRMED:
        return tuple(cols)
    local = entries(p.piece.d)
    for axis in (0, 2):
        groups = {}
        for i, (cell, n) in enumerate(local):
            if abs(n[axis]) == 1:
                groups.setdefault(cell, []).append(i)
        for idx in groups.values():
            if len(idx) == 2 and cols[idx[0]] != cols[idx[1]]:
                show = [i for i in idx if exposed is None or exposed(*faces[i])]
                if len(show) != 1 and painted is not None:
                    show = [i for i in idx if painted(*faces[i])] or show
                pick = cols[(show or idx)[0]]
                for i in idx:
                    cols[i] = pick
    return tuple(cols)


@cache
def lookup(d):
    """{(local cell, rounded local normal): sc index} for colouring rendered fragments."""
    return {(cell, tuple(round(c, 2) + 0.0 for c in n)): i for i, (cell, n) in enumerate(entries(d))}


def colour_of(p, cell, normal):
    """The colour p shows on its face at world `cell` facing world `normal`."""
    if not p.faces:
        return p.color
    QT = tuple(tuple(p.Q[j][i] for j in range(3)) for i in range(3))
    local = apply(QT, tuple(cell[i] - p.origin[i] for i in range(3)))
    n = tuple(round(c, 2) + 0.0 for c in apply(QT, normal))
    i = lookup(p.piece.d).get((tuple(round(c) for c in local), n))
    return p.faces[i] if i is not None and i < len(p.faces) else p.color
