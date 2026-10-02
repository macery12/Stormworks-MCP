"""Stormworks building pieces used for hulls, and the rotation convention.

Rotation convention (verified statistically against ~300 saved vehicles, see FORMAT.md):
the `r` attribute is a row-major 3x3 matrix M, and world_vector = M^T @ local_vector.
Internally we work with Q = M^T (local -> world) and convert on write.

Local piece geometry (unit voxel centred on the origin, derived from the surfaces and voxels
in rom/data/definitions). Every slope piece is one of three shapes, sized in whole voxels and
grown from the origin voxel toward -x, +y and -z:
  ramp(n)          solid toward -y and +z; the sloped face looks up/back (+y, -z) and
                   falls 1 voxel over n along -z (02_wedge, 05_wedge_2, 08_wedge_4)
  tetra(a, b, c)   corner tetrahedron with its right-angled corner at (+x, -y, +z) and legs
                   a, b, c voxels along -x, +y, -z (03, 06, 09 pyramids: 1x1x1, 1x1x2, 1x1x4;
                   11, 12, 13: flat 2x2, 2x4, 4x4 corners one voxel tall)
  inv(a, b, c)     the a x b x c box with that tetrahedron cut from its (-x, +y, -z) corner
                   (04, 07, 10, 14, 15, 16 inverse pyramids)
"""
import math
from dataclasses import dataclass, field
from itertools import permutations, product

DIRS = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
UP = (0, 1, 0)


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def neg(a):
    return (-a[0], -a[1], -a[2])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def apply(Q, v):
    return tuple(Q[i][0] * v[0] + Q[i][1] * v[1] + Q[i][2] * v[2] for i in range(3))


def _det(Q):
    return (Q[0][0] * (Q[1][1] * Q[2][2] - Q[1][2] * Q[2][1])
            - Q[0][1] * (Q[1][0] * Q[2][2] - Q[1][2] * Q[2][0])
            + Q[0][2] * (Q[1][0] * Q[2][1] - Q[1][1] * Q[2][0]))


def _all_rotations():
    rots = []
    for perm in permutations(range(3)):
        for signs in product((1, -1), repeat=3):
            Q = [[0, 0, 0] for _ in range(3)]
            for row, col in enumerate(perm):
                Q[row][col] = signs[row]
            Q = tuple(tuple(r) for r in Q)
            if _det(Q) == 1:
                rots.append(Q)
    return rots


ROTATIONS = _all_rotations()          # the 24 proper axis-aligned rotations
IDENTITY = ((1, 0, 0), (0, 1, 0), (0, 0, 1))


def find_rotation(pairs):
    """First rotation Q with Q @ local == world for every (local, world) pair."""
    for Q in ROTATIONS:
        if all(apply(Q, loc) == w for loc, w in pairs):
            return Q
    raise ValueError(f"no rotation satisfies {pairs}")


def find_rotation_for_set(local_dirs, world_dirs):
    """Rotation mapping a set of local directions onto a set of world directions."""
    target = set(world_dirs)
    for Q in ROTATIONS:
        if {apply(Q, loc) for loc in local_dirs} == target:
            return Q
    raise ValueError(f"no rotation maps {local_dirs} -> {world_dirs}")


def r_attr(Q):
    """Stormworks `r` string for local->world rotation Q (stored as M = Q^T, row-major)."""
    return ",".join(str(Q[i][j]) for j in range(3) for i in range(3))


def parse_r(r):
    """Inverse of r_attr: `r` string -> Q (local -> world)."""
    try:
        values = [float(x) for x in r.split(",")]
        if len(values) != 9 or any(not math.isfinite(x) or x not in (-1, 0, 1) for x in values):
            raise ValueError
        v = [int(x) for x in values]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("r must contain nine axis-aligned rotation entries") from exc
    M = (v[0:3], v[3:6], v[6:9])
    q = tuple(tuple(M[j][i] for j in range(3)) for i in range(3))
    if q not in ROTATIONS:
        raise ValueError("r must be one of the 24 proper axis-aligned rotations")
    return q


# Mirroring. The game stores a part placed in mirror mode as `t` on the component: a bit per
# axis of the part's own frame, flipped before `r` rotates it (1 x, 2 y, 4 z; seen in game
# 2026-10-01: a Pyramid 2x4 mirrored across the centreline is t="1" unrotated and t="4" when
# turned 90 degrees). Here a mirrored part simply has an improper Q (determinant -1), so
# footprints and shape tests need nothing special; only reading and writing split it.
def with_mirror(Q, t):
    """Q (a rotation from `r`) with the local flips of `t` applied first."""
    s = [-1 if t >> a & 1 else 1 for a in range(3)]
    return tuple(tuple(Q[i][j] * s[j] for j in range(3)) for i in range(3))


def split_mirror(Q):
    """(rotation, t) to write for Q: t = 0 for a rotation, else the local x flip."""
    return (Q, 0) if _det(Q) > 0 else (with_mirror(Q, 1), 1)


MIRRORED = [with_mirror(Q, 1) for Q in ROTATIONS]    # the 24 improper ones


@dataclass(frozen=True)
class Piece:
    d: str                  # definition name written to the vehicle file
    surfaces: int           # paintable surface count, first field of `sc`
    mass: float
    footprint: tuple        # local voxel offsets occupied
    verts: tuple            # local vertices (voxel centred at 0, half-size 0.5)
    faces: tuple            # vertex index loops (winding fixed at render time)


def _box_faces(verts):
    """Faces of a convex polytope made of box corners: one per box side with 3+ corners."""
    faces = []
    for axis in range(3):
        vals = [v[axis] for v in verts]
        for s in (min(vals), max(vals)):
            idx = [i for i, v in enumerate(verts) if v[axis] == s]
            if len(idx) >= 3:
                faces.append(tuple(_order_planar(verts, idx)))
    return faces


def _order_planar(verts, idx):
    """Order the vertices of a planar convex polygon around its centroid."""
    pts = [verts[i] for i in idx]
    c = tuple(sum(p[k] for p in pts) / len(pts) for k in range(3))
    # pick the two axes with the largest spread as the projection plane
    spread = [max(p[k] for p in pts) - min(p[k] for p in pts) for k in range(3)]
    ax = sorted(range(3), key=lambda k: -spread[k])[:2]
    return [i for _, i in sorted(
        (math.atan2(verts[i][ax[1]] - c[ax[1]], verts[i][ax[0]] - c[ax[0]]), i) for i in idx)]


def _uvw(a, b, c):
    """Local point -> fractions (u, v, w) across an a x b x c box grown toward -x, +y, -z."""
    return lambda p: ((0.5 - p[0]) / a, (p[1] + 0.5) / b, (0.5 - p[2]) / c)


def _in_unit(u, v, w):
    eps = 1e-9
    return -eps <= u <= 1 + eps and -eps <= v <= 1 + eps and -eps <= w <= 1 + eps


def _ramp(_a, _b, n):
    to = _uvw(1, 1, n)
    verts = ((-.5, -.5, .5 - n), (.5, -.5, .5 - n), (.5, -.5, .5), (-.5, -.5, .5),
             (-.5, .5, .5), (.5, .5, .5))
    faces = ((0, 1, 2, 3), (3, 2, 5, 4), (0, 4, 5, 1), (0, 3, 4), (1, 5, 2))

    def inside(p):
        u, v, w = to(p)
        return _in_unit(u, v, w) and v + w <= 1 + 1e-9
    return verts, faces, inside


def _tetra(a, b, c):
    to = _uvw(a, b, c)
    verts = ((.5, -.5, .5), (.5 - a, -.5, .5), (.5, -.5 + b, .5), (.5, -.5, .5 - c))
    faces = ((0, 1, 2), (0, 2, 3), (0, 3, 1), (1, 3, 2))

    def inside(p):
        u, v, w = to(p)
        return _in_unit(u, v, w) and u + v + w <= 1 + 1e-9
    return verts, faces, inside


def _inv(a, b, c):
    to = _uvw(a, b, c)
    cut = (.5 - a, -.5 + b, .5 - c)
    verts = tuple(v for v in product((.5 - a, .5), (-.5, -.5 + b), (.5 - c, .5)) if v != cut)
    faces = _box_faces(verts)
    slope = [i for i, v in enumerate(verts) if sum(x != y for x, y in zip(v, cut)) == 1]
    faces.append(tuple(slope))

    def inside(p):
        u, v, w = to(p)
        return _in_unit(u, v, w) and u + v + w <= 2 + 1e-9
    return verts, tuple(faces), inside


def _footprint(inside, size):
    """Voxels the shape reaches into at all, even a sliver (as the game counts them)."""
    a, b, c = size
    pts = (-0.45, 0.0, 0.45)
    out = []
    for i in range(a):
        for j in range(b):
            for k in range(c):
                cell = (-i, j, -k)
                if sum(inside(add(cell, (x, y, z))) for x in pts for y in pts for z in pts) >= 1:
                    out.append(cell)
    return tuple(out)


CONTAINS = {}    # definition name -> point-in-piece test in local coordinates


def _piece(d, surfaces, mass, shape, size):
    verts, faces, inside = shape(*size)
    CONTAINS[d] = inside
    return Piece(d, surfaces, mass, _footprint(inside, size), verts, faces)


_CUBE_V = tuple((x, y, z) for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5))
BLOCK = Piece("01_block", 6, 1.0, ((0, 0, 0),), _CUBE_V, tuple(_box_faces(_CUBE_V)))
CONTAINS["01_block"] = lambda p: all(-0.5 <= c <= 0.5 for c in p)
# surface counts (the `sc` length) and masses are read from the game's definition files
WEDGE = _piece("02_wedge", 5, 0.5, _ramp, (1, 1, 1))
WEDGE2 = _piece("05_wedge_2", 9, 1.0, _ramp, (1, 1, 2))
WEDGE4 = _piece("08_wedge_4", 17, 2.0, _ramp, (1, 1, 4))
PYRAMID = _piece("03_pyramid", 4, 0.25, _tetra, (1, 1, 1))
PYRAMID2 = _piece("06_pyramid_2", 7, 0.5, _tetra, (1, 1, 2))
PYRAMID4 = _piece("09_pyramid_4", 13, 1.0, _tetra, (1, 1, 4))
PYRAMID2X2 = _piece("11_pyramid_2x2", 10, 1.0, _tetra, (2, 1, 2))
PYRAMID2X4 = _piece("12_pyramid_2x4", 18, 2.0, _tetra, (2, 1, 4))
PYRAMID4X4 = _piece("13_pyramid_4x4", 28, 4.0, _tetra, (4, 1, 4))
INVPYRAMID = _piece("04_invpyramid", 7, 0.75, _inv, (1, 1, 1))
INVPYRAMID2 = _piece("07_invpyramid_2", 12, 1.5, _inv, (1, 1, 2))
INVPYRAMID4 = _piece("10_invpyramid_4", 22, 3.0, _inv, (1, 1, 4))
INVPYRAMID2X2 = _piece("14_invpyramid_2x2", 18, 3.0, _inv, (2, 1, 2))
INVPYRAMID2X4 = _piece("15_invpyramid_2x4", 32, 6.0, _inv, (2, 1, 4))
INVPYRAMID4X4 = _piece("16_invpyramid_4x4", 52, 12.0, _inv, (4, 1, 4))

# every slope piece in the game's block catalogue, smallest first
SLOPES = (WEDGE, PYRAMID, INVPYRAMID, WEDGE2, PYRAMID2, INVPYRAMID2, PYRAMID2X2, INVPYRAMID2X2,
          WEDGE4, PYRAMID4, INVPYRAMID4, PYRAMID2X4, INVPYRAMID2X4, PYRAMID4X4, INVPYRAMID4X4)
BY_NAME = {p.d: p for p in (BLOCK, *SLOPES)}


def wedge_rotation(tread, riser):
    """Wedge whose sloped face looks toward `tread` (up) and descends toward `riser`."""
    return find_rotation([((0, 1, 0), tread), ((0, 0, -1), riser)])


@dataclass
class Placed:
    piece: Piece
    origin: tuple
    Q: tuple = IDENTITY
    color: str = "C2C3C7"
    uid: str = ""
    name: str = ""
    settings: dict = field(default_factory=dict)
    raw_xml: str = ""
    protected: bool = False

    def voxels(self):
        return [add(self.origin, apply(self.Q, f)) for f in self.piece.footprint]
