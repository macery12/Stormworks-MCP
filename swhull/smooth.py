"""Turn a solid voxel set into a hollow, watertight skin of Stormworks pieces.

Two modes:

- "blocks": plain blocks only. Always watertight; the player smooths it by hand.
- "wedges": fits the game's whole slope catalogue (wedges 1x1/1x2/1x4, pyramids and inverse
  pyramids 1x1, 1x2, 1x4, 2x2, 2x4, 4x4) to the true continuous shape.

  1. Every surface voxel, the solid layer just under it (where the full corner of a large
     inverse pyramid sits), every empty voxel the shape still reaches, and the air around them
     is sampled at 64 points against the shape. From the samples each voxel gets the true
     surface normal (exact for a plane, counting sample pairs across voxel faces too) and a
     crease score (how far the samples are from one plane: high at a deck edge or box corner).
  2. Every piece in every rotation is scored at every cell at once (numpy) by an energy:
     samples it gets wrong (volume), plus surface error: each exposed bit of voxel face and
     each unit of sloped face, times how far it turns from the true surface. Volume alone
     cannot tell a stair-step or a thin spike from a good slope; the surface term can. Each
     voxel face where a sloped edge runs into a flat face or open air also costs W_EDGE: a
     slope should continue into a matching slope, as players build it (a pyramid stacked on
     an inverse pyramid of the same size, a pyramid closing the end of a wedge run), not stop
     dead against blocks.
  3. Pieces are placed greedily, best fitting first (least error left per voxel), as long as
     each beats the blocks it replaces. A face against a neighbour that is still to be decided
     counts only partly (OPTIMISM), else the first wedge on a broad slope would never pay off.
     A piece whose neighbours changed is re-scored and goes back in line, so a surface grows
     outward from its exact fits in one consistent pattern.
  4. Swap passes try each good piece in place of whatever overlaps it, refill the freed
     cells, and keep the change when the total energy drops (a straight wedge row beats a
     zigzag of long pieces, and a long piece beats a broken run).
  5. A clean-up at full cost removes any piece worse than the blocks it replaced. Then any
     face of a partial piece that would open into the hollow interior is backed by a block,
     so slopes never leak, and pieces left floating in the air are dropped.

  Hard rules: no piece puts material in a voxel the shape does not reach (no spike tips),
  painted voxels stay blocks, and a piece spanning voxels of different colours is not used.

Hollowing keeps every solid voxel that touches the outside on any of its 26 neighbours.
"""
import heapq

import numpy as np

from .pieces import BLOCK, CONTAINS, DIRS, MIRRORED, ROTATIONS, SLOPES, UP, Placed, add, apply, sub

NEIGHBOURS_26 = [(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)
                 if (x, y, z) != (0, 0, 0)]

# 4x4x4 sample points per voxel; small per-axis shifts keep samples off the 45-degree planes.
_OFF = (-0.375, -0.125, 0.125, 0.375)
SAMPLES = [(x, y + 0.02, z - 0.03) for x in _OFF for y in _OFF for z in _OFF]
FULL_MASK = (1 << len(SAMPLES)) - 1

# Fit energy. Volume error is in samples (64 per voxel); surface error is in face samples
# (16 per voxel face) times how far that bit of surface turns from the true surface normal,
# as the distance between the two unit normals (0 = facing the right way, 1.41 = at right
# angles, 2 = facing backwards).
W_SURF = 1.5      # weight of surface error: steps, fins and spikes read far worse than volume
W_PART = 1.0      # per part: prefer one long piece over several short ones on a tie
W_EDGE = 6.0      # per voxel face where a sloped edge runs into a flat face or open air (a
                  # lone pyramid on blocks, a sawtooth of wedge ends): a slope should join a
                  # matching slope (pyramid to inverse pyramid or wedge end) or not be there
W_TILT = 3.0      # per unit of slope area: a slope tilted along an axis the surface is not
                  # (it can only follow the surface as a zigzag of mirrored pieces)
MIN_GAIN = 6.0    # a piece must lower the energy by this much to replace blocks / empty space
CELL_MAX = 24     # quick reject: no single voxel of a piece may get more samples wrong than this
ALLOW = 24.0      # keep pieces this far from paying off against plain blocks for later passes
CREASE_FACE = 0.3  # in a creased cell, the share of the surface a direction needs to count
                  # as one of the cell's faces (a slope there is judged against the nearest)
OPTIMISM = 0.25   # while building, a face onto a cell still to be decided that the surface
                  # crosses costs this share: that cell will most likely get a matching piece
                  # (else the first wedge on a broad slope never pays off). Pieces are checked
                  # at full cost once everything is placed.
PASSES = 3        # later passes revisit pieces next to ones already placed (corners, joints)
SWAPS = 2         # rounds of trying each piece in place of the ones overlapping it
BORDER_STEPS = 2  # empty voxels this many steps out that the shape reaches may get a piece
FACE = 0xFFFF     # a full voxel face, 4 x 4 samples


def _transpose(Q):
    return tuple(tuple(Q[j][i] for j in range(3)) for i in range(3))


def _placements(piece):
    """Distinct (rotation, [(world cell offset, sample mask)]) for a piece. Mirrored placements
    (mirror mode in game) come after the rotations and are kept only where no rotation gives
    the same shape: for the Pyramid 2x4 and Inverse Pyramid 2x4, whose three sides all differ,
    so half of their corner directions exist only mirrored."""
    test = CONTAINS[piece.d]
    seen, out = set(), []
    for Q in ROTATIONS + MIRRORED:
        QT = _transpose(Q)
        cells = []
        for f in piece.footprint:
            w = apply(Q, f)
            mask = 0
            for i, s in enumerate(SAMPLES):
                if test(add(f, apply(QT, s))):
                    mask |= 1 << i
            cells.append((w, mask))
        key = tuple(sorted(cells))
        if key not in seen:
            seen.add(key)
            out.append((Q, cells))
    return out


def _full_faces(piece, Q):
    """Set of (world cell offset, world direction) faces this placement covers completely."""
    test = CONTAINS[piece.d]
    QT = _transpose(Q)
    grid = [(-0.45 + 0.9 * i / 4) for i in range(5)]
    out = set()
    for f in piece.footprint:
        for d in DIRS:
            ld = apply(QT, d)
            axis = [i for i in range(3) if ld[i] != 0][0]
            others = [i for i in range(3) if i != axis]
            pts = []
            for a in grid:
                for b in grid:
                    p = [0.0, 0.0, 0.0]
                    p[axis] = 0.49 * ld[axis]
                    p[others[0]], p[others[1]] = a, b
                    pts.append(add(f, tuple(p)))
            if all(test(p) for p in pts):
                out.add((apply(Q, f), d))
    return out


def _face_bits(test, centre, d):
    """16-bit coverage of the face of the voxel at `centre` on side d (world axes), sampled on
    a 4 x 4 grid just inside the voxel. Bit order depends only on the face's world position,
    so the two voxels sharing a face agree on it. The grid is nudged off the even quarters:
    on them, four points sit exactly on the diagonal where a pyramid meets its inverse
    pyramid, and the two sides of that perfect joint would disagree about all four."""
    axis = [i for i in range(3) if d[i]][0]
    a, b = [i for i in range(3) if i != axis]
    bits = 0
    for i, u in enumerate(_OFF):
        for j, v in enumerate(_OFF):
            p = list(centre)
            p[axis] += 0.4999 * d[axis]
            p[a] += u + 0.03
            p[b] += v + 0.01
            if test(tuple(p)):
                bits |= 1 << (i * 4 + j)
    return bits


def _slope(piece):
    """(outward unit normal, {local cell: area}) of the piece's one sloped face, in voxels."""
    verts = piece.verts
    centre = [sum(v[i] for v in verts) / len(verts) for i in range(3)]
    for f in piece.faces:
        pts = [verts[i] for i in f]
        n = [0.0, 0.0, 0.0]
        for i, p in enumerate(pts):
            q = pts[(i + 1) % len(pts)]
            n[0] += (p[1] - q[1]) * (p[2] + q[2])
            n[1] += (p[2] - q[2]) * (p[0] + q[0])
            n[2] += (p[0] - q[0]) * (p[1] + q[1])
        size = sum(c * c for c in n) ** 0.5
        n = [c / size for c in n]
        if max(abs(c) for c in n) > 0.999:
            continue
        fc = [sum(p[i] for p in pts) / len(pts) for i in range(3)]
        if sum(n[i] * (fc[i] - centre[i]) for i in range(3)) < 0:
            n = [-c for c in n]
        area, steps = {}, 24
        for k in range(1, len(pts) - 1):        # fan triangles, sampled at their sub-centres
            a, b, c = pts[0], pts[k], pts[k + 1]
            tri = 0.5 * sum(x * x for x in (
                (b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]),
                (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]),
                (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))) ** 0.5
            pts_in = [(i + 1 / 3, j + 1 / 3) for i in range(steps) for j in range(steps - i)]
            pts_in += [(i + 2 / 3, j + 2 / 3) for i in range(steps) for j in range(steps - i - 1)]
            for i, j in pts_in:
                u, v = i / steps, j / steps
                p = [a[m] + u * (b[m] - a[m]) + v * (c[m] - a[m]) - 1e-6 * n[m] for m in range(3)]
                cell = tuple(round(x) for x in p)
                area[cell] = area.get(cell, 0.0) + tri / (steps * steps)
        return tuple(n), area
    raise ValueError(f"{piece.d} has no sloped face")


_CACHE = {}


def _catalogue():
    """Every slope piece placement, as a dict per placement:
    piece, Q, offs (k, 3) world cell offsets, vol (k,) uint64 sample masks, face (k, 6)
    uint16 coverage of each cell face (DIRS order), inner (k, 6) faces shared with another
    cell of the same piece, area (k,) sloped-face area in each cell, normal (3,) of the slope.
    """
    if "placements" not in _CACHE:
        out = []
        for piece in SLOPES:
            test = CONTAINS[piece.d]
            n_local, area_local = _slope(piece)
            for Q, cells in _placements(piece):
                QT = _transpose(Q)
                offs = [w for w, _ in cells]
                local = [apply(QT, w) for w in offs]

                def world_test(p, QT=QT, test=test):
                    return test(apply(QT, p))
                out.append({
                    "piece": piece, "Q": Q,
                    "offs": np.array(offs, dtype=np.int64),
                    "vol": np.array([m for _, m in cells], dtype=np.uint64),
                    "face": np.array([[_face_bits(world_test, w, d) for d in DIRS] for w in offs],
                                     dtype=np.uint16),
                    "inner": np.array([[add(w, d) in offs for d in DIRS] for w in offs], dtype=bool),
                    "area": np.array([area_local.get(f, 0.0) for f in local], dtype=np.float64),
                    "normal": np.array(apply(Q, n_local), dtype=np.float64),
                })
        _CACHE["placements"] = out
        _CACHE["full"] = {}
    return _CACHE


def shell(S):
    """Voxels of S with any of their 26 neighbours missing. The full 3x3x3 test is separable,
    so the solid core is found with three 1-D erosions instead of 26 lookups per voxel."""
    ex = {v for v in S if (v[0] - 1, v[1], v[2]) in S and (v[0] + 1, v[1], v[2]) in S}
    exy = {v for v in ex if (v[0], v[1] - 1, v[2]) in ex and (v[0], v[1] + 1, v[2]) in ex}
    core = {v for v in exy if (v[0], v[1], v[2] - 1) in exy and (v[0], v[1], v[2] + 1) in exy}
    return S - core


def deck_plates(S, keep):
    """Voxels forming the top plate of the hull, removed for an open deck."""
    out = set()
    horiz = [(x, 0, z) for x in (-1, 0, 1) for z in (-1, 0, 1) if (x, z) != (0, 0)]
    for v in keep:
        if add(v, UP) in S:
            continue
        if sub(v, UP) in S and all(add(v, h) in S for h in horiz):
            out.add(v)
    return out


def _cells(S, inside, removed, sample_mask, fixed):
    """Cells a piece may cover, with their sample masks: surface voxels, empty voxels the shape
    reaches (up to BORDER_STEPS out), and the empty air touching those."""
    masks = {}

    def mask_of(v):
        m = masks.get(v)
        if m is None:
            if sample_mask is not None:
                m = sample_mask(v)
            else:
                m = 0
                for i, s in enumerate(SAMPLES):
                    if inside(add(v, s)):
                        m |= 1 << i
            masks[v] = m
        return m

    surface = {v for v in S if v not in removed and any(add(v, d) not in S for d in DIRS)}
    for v in surface:
        mask_of(v)
    border, frontier = set(), surface
    for _ in range(BORDER_STEPS):
        frontier = {n for v in frontier for d in DIRS for n in (add(v, d),)
                    if n not in S and n not in border and sub(n, UP) not in removed and mask_of(n)}
        border |= frontier
    air = {n for v in surface | border for d in DIRS for n in (add(v, d),)
           if n not in S and n not in border and sub(n, UP) not in removed}
    for v in air:
        mask_of(v)
    # solid voxels just under the surface: the full corner of an inverse pyramid sits there
    inner = {n for v in surface for d in DIRS for n in (add(v, d),) if n in S and n not in surface}
    for v in inner:          # only where a 26-neighbour is missing can the surface clip it
        if any(add(v, o) not in S for o in NEIGHBOURS_26):
            mask_of(v)
        else:
            masks[v] = FULL_MASK
    cells = (surface | inner | border | air) - set(fixed) - set(removed)
    return sorted(cells), masks


# Sample-grid helpers. SAMPLES index = 16 * ix + 4 * iy + iz.
_STRIDE = (16, 4, 1)
_LOW = (0x0000FFFFFFFFFFFF, 0x0FFF0FFF0FFF0FFF, 0x7777777777777777)    # i_axis < 3
_LAYER = (0xFFFF000000000000, 0x000000000000FFFF, 0xF000F000F000F000,  # outer layer per DIRS
          0x000F000F000F000F, 0x8888888888888888, 0x1111111111111111)


def _transitions(M, neighbour):
    """Per cell and DIRS direction, how many sample pairs step from inside to outside going
    that way: how much of the true surface in the cell faces that way. The samples of all
    cells form one lattice with even spacing, so pairs straddling a cell face count too, half
    to each cell; without them a shallow slope that leaves through a cell's floor reads far
    too steep. `neighbour(di)` gives the sample masks of the cells on side di."""
    out = np.zeros((len(M), 6))
    for a in range(3):
        s = np.uint64(_STRIDE[a])
        nxt = M >> s
        low = np.uint64(_LOW[a])
        out[:, 2 * a] = np.bitwise_count(M & ~nxt & low)
        out[:, 2 * a + 1] = np.bitwise_count(~M & nxt & low)
        top = np.uint64(_LAYER[2 * a + 1])            # the layer at index 0 along this axis
        shift = np.uint64(3 * _STRIDE[a])
        for lo_side, hi_side, plus, minus in (
                (M >> shift, neighbour(2 * a), 2 * a, 2 * a + 1),      # our layer 3 | its 0
                (neighbour(2 * a + 1) >> shift, M, 2 * a, 2 * a + 1)):  # its layer 3 | our 0
            lo_l, hi_l = lo_side & top, hi_side & top
            # a face lying exactly on the cell face (a box wall) is a separate face, not
            # part of the surface through the cell
            whole = ((lo_l == top) & (hi_l == 0)) | ((lo_l == 0) & (hi_l == top))
            keep = np.where(whole, 0.0, 0.5)
            out[:, plus] += keep * np.bitwise_count(lo_l & ~hi_l & top)
            out[:, minus] += keep * np.bitwise_count(~lo_l & hi_l & top)
    return out


def _mask_gradient(trans):
    """Outward normal of the surface inside each cell, from its own 64 samples. For a plane
    this is exactly proportional to its normal. Zero for full or empty cells."""
    return trans[:, 0::2] - trans[:, 1::2]


def _crease(M, g, chunk=65536):
    """How far each cell's samples are from being cut by a single plane: the samples the
    best cut along normal g puts on the wrong side, halved. 0 on a hull or a ramp, about 3 on
    a gentle hip, 6 or more where two faces meet at a right angle (a deck edge, a box corner)."""
    pts = np.array(SAMPLES)
    bits = np.arange(64, dtype=np.uint64)
    out = np.zeros(len(M))
    for s in range(0, len(M), chunk):
        m, gg = M[s:s + chunk], g[s:s + chunk]
        proj = gg @ pts.T                          # larger = further outside
        inside = ((m[:, None] >> bits[None, :]) & np.uint64(1)).astype(bool)
        count = inside.sum(axis=1)[:, None]
        order = np.argsort(proj, axis=1)
        srt = np.take_along_axis(proj, order, axis=1)
        cum = np.concatenate([np.zeros((len(m), 1), dtype=np.int64),
                              np.cumsum(np.take_along_axis(inside, order, axis=1), axis=1)], axis=1)
        j = np.arange(65)[None, :]
        wrong = (j - cum) + (count - cum)          # cutting after the j lowest samples
        # a cut can only fall between distinct values: samples level with each other go
        # together, so the answer does not depend on how ties were sorted
        gap = np.ones((len(m), 65), dtype=bool)
        gap[:, 1:64] = srt[:, 1:] - srt[:, :-1] > 1e-9
        out[s:s + chunk] = np.where(gap, wrong, 64).min(axis=1) / 2
    return out


def _sobel(xyz, fill_at):
    """Outward normal from how full the 3 x 3 x 3 neighbourhood is (blurs sharp edges)."""
    g = np.zeros((len(xyz), 3))
    weight = {-1: 1.0, 0: 2.0, 1: 1.0}
    for o in NEIGHBOURS_26:
        f = fill_at(xyz + np.array(o))
        for a in range(3):
            if o[a]:
                b, c = [i for i in range(3) if i != a]
                g[:, a] -= o[a] * weight[o[b]] * weight[o[c]] * f
    return g


def _unit(g, scale):
    """Unit vectors scaled by confidence: min(1, length / scale)."""
    size = np.linalg.norm(g, axis=1)
    conf = np.minimum(1.0, size / scale)
    return g * (conf / np.maximum(size, 1e-9))[:, None]


def _chord(conf, cos):
    """|n_true - conf * n| for a confidence-scaled true normal and a unit normal n at `cos`
    to it: grows with the angle (about 0.23 at 13 degrees, 1.41 at 90), unlike 1 - cos."""
    return np.sqrt(np.maximum(0.0, 2 * conf * (conf - cos)))


def _edge(a, b):
    """1 where two sides' face coverage disagree and at least one is partial: a sloped edge
    meeting a flat face, air, or a slope that does not line up."""
    flat_a = (a == 0) | (a == FACE)
    flat_b = (b == 0) | (b == FACE)
    return ((a != b) & ~(flat_a & flat_b)).astype(np.float64)


def _pen(a, b, pa, pb):
    """Surface error of one shared face: a and b are the two sides' 16-bit coverage. Bits
    only a covers are exposed facing +d (error pa each), bits only b covers face -d (pb)."""
    return np.bitwise_count(a & ~b) * pa + np.bitwise_count(b & ~a) * pb


def fit_pieces(S, inside, removed=frozenset(), sample_mask=None, fixed=frozenset(), colour=None):
    """Choose slope pieces. `inside(point)` tests the continuous shape; `sample_mask(voxel)`,
    when given, returns the SAMPLES bit mask for a whole voxel at once (much faster).
    `fixed` voxels never get a slope piece (painted areas stay crisp blocks). With `colour`,
    a piece covering more than one voxel is only used where every voxel has the same colour,
    because a piece takes the colour of one cell.

    Returns {cell: (piece, origin, Q, paint cell)} for every cell covered by a non-block
    piece; the paint cell is the one the piece fills most, whose colour it should take.
    """
    cells, mask_map = _cells(S, inside, removed, sample_mask, fixed)
    if not cells:
        return {}
    n = len(cells)
    xyz = np.array(cells, dtype=np.int64)
    M = np.array([mask_map[c] for c in cells], dtype=np.uint64)
    solid = np.array([c in S for c in cells], dtype=bool)
    base = np.where(solid, np.bitwise_count(M ^ np.uint64(FULL_MASK)),
                    np.bitwise_count(M)).astype(np.float64)
    if colour is not None:     # empty air takes any colour: a piece only has a sliver there
        ids = {}
        reach = (np.bitwise_count(M) > 0) | solid
        col = np.array([ids.setdefault(colour(c), len(ids)) if r else -1
                        for c, r in zip(cells, reach.tolist())], dtype=np.int32)

    # dense lookups over the cells' bounding box: cell index, kept solid, how full
    lo = xyz.min(axis=0) - 5
    dims = tuple(int(d) for d in xyz.max(axis=0) - lo + 6)
    grid = np.full(dims, -1, dtype=np.int32)
    grid[tuple((xyz - lo).T)] = np.arange(n, dtype=np.int32)
    kept = np.zeros(dims, dtype=bool)
    fill = np.zeros(dims, dtype=np.float32)
    inbox = [v for v in S if all(lo[i] <= v[i] < lo[i] + dims[i] for i in range(3))]
    if inbox:
        sv = np.array(inbox, dtype=np.int64) - lo
        kept[tuple(sv.T)] = True
        fill[tuple(sv.T)] = 1.0
    for v in removed:
        if all(lo[i] <= v[i] < lo[i] + dims[i] for i in range(3)):
            kept[tuple(int(v[i] - lo[i]) for i in range(3))] = False
    fill[tuple((xyz - lo).T)] = np.bitwise_count(M) / 64.0
    kept[tuple((xyz - lo).T)] = solid

    def at(arr, p):
        q = p - lo
        return arr[q[:, 0], q[:, 1], q[:, 2]]

    # True surface normal per cell, scaled by confidence: from the cell's own samples where
    # the surface passes through it (sharp: a deck edge stays an edge), else from the
    # neighbourhood. A sloped face in a cell the surface does not cross is wrong outright.
    count = np.bitwise_count(M)
    partial = (count > 0) & (count < len(SAMPLES))
    full = np.uint64(FULL_MASK)
    nb_masks = []
    for d in DIRS:
        p = xyz + d
        e = at(grid, p)
        nb_masks.append(np.where(e >= 0, M[np.maximum(e, 0)],
                                 np.where(at(fill, p) >= 1.0, full, np.uint64(0))))
    trans = _transitions(M, lambda di: nb_masks[di])
    grad = _mask_gradient(trans)
    # which ways the surface in each cell faces, 0..1 per DIRS direction (for creased cells)
    support = trans / np.maximum(trans.max(axis=1, keepdims=True), 1.0)
    own = _unit(grad, 4.0)
    near = _unit(_sobel(xyz, lambda p: at(fill, p)), 12.0)
    nrm = np.where(partial[:, None], own + 0.25 * near, near)
    nrm = _unit(nrm, 1.0)
    # where two faces meet inside a cell its single normal is a meaningless diagonal: trust
    # it less the sharper the crease, so a box edge is not "smoothed" into a chamfer
    flat = np.ones(n)
    if partial.any():
        crease = _crease(M[partial], grad[partial])
        flat[partial] = np.clip(1.0 - (crease - 2.0) / 3.0, 0.0, 1.0)
    nrm *= flat[:, None]
    conf = np.linalg.norm(nrm, axis=1)
    # Error per exposed bit of each cell face, in DIRS order: against the mean of the two
    # cells' normals, or the exact face direction where the shape's own face lies on the voxel
    # face (a box wall: all samples in on one side, none on the other).
    face_pa = np.zeros((n, 6))      # error per exposed bit facing +d
    face_pb = np.zeros((n, 6))      # and facing -d
    edge_w = np.full((n, 6), W_EDGE)   # cost of a hard edge on each cell face
    face_pp = np.zeros((n, 6))      # facing +d from a piece: a tip in empty air or a dent in
                                    # solid is wrong whatever the neighbourhood says
    for di, d in enumerate(DIRS):
        p = xyz + d
        e = at(grid, p)
        has = e >= 0
        other = np.where(has, M[np.maximum(e, 0)], np.where(at(kept, p), full, np.uint64(0)))
        n_f = np.where(has[:, None], 0.5 * (nrm + nrm[np.maximum(e, 0)]), nrm)
        lay, opp = np.uint64(_LAYER[di]), np.uint64(_LAYER[di ^ 1])
        out = ((M & lay) == lay) & ((other & opp) == 0)
        inn = ((M & lay) == 0) & ((other & opp) == opp)
        dn = np.where(out, 1.0, np.where(inn, -1.0, n_f @ np.array(d, dtype=float)))
        cf = np.where(out | inn, 1.0, np.linalg.norm(n_f, axis=1))
        face_pa[:, di] = _chord(cf, dn)
        face_pb[:, di] = _chord(cf, -dn)
        # where either cell holds a crease, judge an exposed face by whether the true
        # surface there faces that way at all (a box edge: top and side yes, ends no)
        ef = np.where(has, flat[np.maximum(e, 0)], 1.0)
        es = np.where(has[:, None], support[np.maximum(e, 0)], 0.0)
        w = np.where(out | inn, 0.0, 1.0 - np.minimum(flat, ef))
        sup_a = np.maximum(support[:, di], es[:, di])
        sup_b = np.maximum(support[:, di ^ 1], es[:, di ^ 1])
        face_pa[:, di] = (1 - w) * face_pa[:, di] + w * 1.41 * (1 - sup_a)
        face_pb[:, di] = (1 - w) * face_pb[:, di] + w * 1.41 * (1 - sup_b)
        face_pp[:, di] = np.where(~partial & ~(out | inn), np.maximum(face_pa[:, di], 1.0),
                                  face_pa[:, di])
        # a face onto an opened cell (open deck, door, hatch) is meant to show
        opened = ~has & (at(fill, p) >= 1.0) & ~at(kept, p)
        face_pa[opened, di] = face_pb[opened, di] = face_pp[opened, di] = 0.0
        edge_w[opened, di] = 0.0
    deflt = np.where(solid, FACE, 0).astype(np.uint16)   # each cell's face as a plain block

    # error of a sloped face per unit area: against the true normal where the surface
    # crosses the cell as one plane, outright wrong where it does not cross or creases
    slope_flat = np.where(partial, flat, 0.0)
    # a crease cell holds two or more faces: a slope may follow one of them (a ramp up a
    # sheered deck edge), but not cut across them (a chamfer, a pyramid tooth)
    faces_of = np.where(partial[:, None], support >= CREASE_FACE, False)
    dvec = np.array(DIRS, dtype=np.float64)

    # how far each axis of the true normal is from zero, for the tilt term
    tilt_ref = np.abs(nrm) + (1.0 - conf)[:, None]

    def slope_err(c, normal):
        f = slope_flat[c]
        tilt = np.maximum(0.0, np.abs(normal)[None, :] - tilt_ref[c] - 0.05).sum(axis=1)
        to_face = np.sqrt(np.maximum(0.0, 2 - 2 * (dvec @ normal)))     # chord to each axis
        crease = np.minimum(np.where(faces_of[c], to_face[None, :], 1.0).min(axis=1), 1.0)
        return (f * _chord(conf[c], nrm[c] @ normal) + (1.0 - f) * crease
                + W_TILT / W_SURF * tilt)

    # what is on the other side of each cell face as plain blocks, how much a mismatch there
    # counts while building, and what that face costs now
    nb_all = np.zeros((n, 6), dtype=np.uint16)
    w_all = np.ones((n, 6))
    for di, d in enumerate(DIRS):
        p = xyz + d
        e = at(grid, p)
        nb_all[:, di] = np.where(e >= 0, deflt[np.maximum(e, 0)], np.where(at(kept, p), FACE, 0))
        w_all[:, di] = np.where((e >= 0) & partial[np.maximum(e, 0)], OPTIMISM, 1.0)
    old_all = w_all * (W_SURF * _pen(deflt[:, None], nb_all, face_pa, face_pb)
                       + edge_w * _edge(deflt[:, None], nb_all))
    pp_w, pb_w, edge_ww = face_pp * w_all, face_pb * w_all, edge_w * w_all

    # 1. score every placement of every piece at every cell against plain blocks
    cat = _catalogue()["placements"]
    found = []    # (type, cell indices (m, k), energy change against plain blocks (m,),
                  #  error left once placed (m,))
    for t, pl in enumerate(cat):
        offs, vol = pl["offs"], pl["vol"]
        k_n = len(offs)
        anchors = np.arange(n)
        cols, costs = [], []
        for k in range(k_n):
            idx = anchors if not offs[k].any() else at(grid, xyz[anchors] + offs[k])
            ok = idx >= 0
            safe = np.where(ok, idx, 0)
            c = np.bitwise_count(M[safe] ^ vol[k]).astype(np.float64)
            ok &= c <= CELL_MAX
            if vol[k]:      # never put material where the design has none (a spike tip)
                ok &= (count[safe] > 0) | solid[safe]
            anchors, idx, c = anchors[ok], idx[ok], c[ok]
            cols = [x[ok] for x in cols] + [idx]
            costs = [x[ok] for x in costs] + [c]
            if not len(anchors):
                break
        if not len(anchors):
            continue
        cix = np.stack(cols, axis=1)
        if colour is not None and k_n > 1:
            cc = col[cix]
            ref = cc.max(axis=1, keepdims=True)
            same = ((cc == ref) | (cc < 0)).all(axis=1)
            cix, costs = cix[same], [x[same] for x in costs]
            if not len(cix):
                continue
        dE = W_PART * (1 - solid[cix].sum(axis=1))
        res = np.full(len(cix), W_PART)
        for k in range(k_n):
            c = cix[:, k]
            own = costs[k] + W_SURF * 16 * pl["area"][k] * slope_err(c, pl["normal"])
            dE += own - base[c]
            res += own
            for di in range(6):
                old = old_all[c, di]
                if pl["inner"][k, di]:
                    dE -= 0.5 * old               # face shared with another cell of this piece
                else:
                    nb = nb_all[c, di]
                    mine = pl["face"][k, di]
                    new = (W_SURF * _pen(mine, nb, pp_w[c, di], pb_w[c, di])
                           + edge_ww[c, di] * _edge(mine, nb))
                    dE += new - old
                    res += new
        keep = dE <= ALLOW
        if keep.any():
            found.append((t, cix[keep], dE[keep], res[keep]))
    if not found:
        return {}

    # 2. take pieces greedily, best first, re-scoring any piece whose neighbours changed
    index = {c: i for i, c in enumerate(cells)}
    solid_l, base_l, M_l = solid.tolist(), base.tolist(), M.tolist()
    nrm_l = nrm.tolist()
    conf_l, flat_l, tilt_l = conf.tolist(), slope_flat.tolist(), tilt_ref.tolist()
    faces_l = [[di for di in range(6) if row[di]] for row in faces_of.tolist()]
    partial_l = partial.tolist()
    pa_l, pb_l, pp_l = face_pa.tolist(), face_pb.tolist(), face_pp.tolist()
    edge_l = edge_w.tolist()
    face_l = [pl["face"].tolist() for pl in cat]
    inner_l = [pl["inner"].tolist() for pl in cat]
    area_l = [pl["area"].tolist() for pl in cat]
    pn_l = [pl["normal"].tolist() for pl in cat]
    vol_l = [pl["vol"].tolist() for pl in cat]
    label = [None] * n          # (type, position in footprint) once a piece covers the cell
    # neighbours of each cell, and when anything next to it last changed: a candidate scored
    # before that is stale
    nbr = [[index[q] for d in DIRS for q in ((x + d[0], y + d[1], z + d[2]),) if q in index]
           for x, y, z in cells]
    stamp = [0] * n
    clock = [0]

    def face_now(p, di, hope):
        """(face bits on side di of whatever is at p now, weight of a mismatch against it):
        `hope` for an undecided cell the surface crosses, else 1."""
        i = index.get(p)
        if i is None:
            q = (p[0] - lo[0], p[1] - lo[1], p[2] - lo[2])
            return (FACE if all(0 <= q[a] < dims[a] for a in range(3)) and kept[q] else 0), 1.0
        lab = label[i]
        if lab is None:
            return (FACE if solid_l[i] else 0), (hope if partial_l[i] else 1.0)
        return face_l[lab[0]][lab[1]][di], 1.0

    def delta(t, row, hope=OPTIMISM, both=False):
        """Energy change of placing type t on cells `row`, given what is placed now. With
        hope=1 the exact change; by default undecided neighbours are taken as likely to
        match (see OPTIMISM). With `both`, also the error the piece itself leaves."""
        faces, inner, area, pn, vol = face_l[t], inner_l[t], area_l[t], pn_l[t], vol_l[t]
        dE = W_PART * (1 - sum(solid_l[c] for c in row))
        res = W_PART
        for k, c in enumerate(row):
            v = (M_l[c] ^ vol[k]).bit_count()
            dE += v - base_l[c]
            res += v
            if area[k]:
                nc = nrm_l[c]
                cos = nc[0] * pn[0] + nc[1] * pn[1] + nc[2] * pn[2]
                f, tr = flat_l[c], tilt_l[c]
                crease = min([(max(0.0, 2 - 2 * pn[di >> 1] * (1 - 2 * (di & 1)))) ** 0.5
                              for di in faces_l[c]], default=1.0)
                err = f * max(0.0, 2 * conf_l[c] * (conf_l[c] - cos)) ** 0.5 + (1.0 - f) * min(crease, 1.0)
                err += W_TILT / W_SURF * (max(0.0, abs(pn[0]) - tr[0] - 0.05)
                                          + max(0.0, abs(pn[1]) - tr[1] - 0.05)
                                          + max(0.0, abs(pn[2]) - tr[2] - 0.05))
                dE += W_SURF * 16 * area[k] * err
                res += W_SURF * 16 * area[k] * err
            mine_old = FACE if solid_l[c] else 0
            x, y, z = cells[c]
            pas, pbs, pps, eds = pa_l[c], pb_l[c], pp_l[c], edge_l[c]
            nb_flat = (0, FACE)
            for di, d in enumerate(DIRS):
                nb, w = face_now((x + d[0], y + d[1], z + d[2]), di ^ 1, hope)
                pa, pb = pas[di] * w, pbs[di] * w
                old = W_SURF * ((mine_old & ~nb & FACE).bit_count() * pa
                                + (nb & ~mine_old & FACE).bit_count() * pb)
                if nb != mine_old and nb not in nb_flat:
                    old += eds[di] * w
                if inner[k][di]:
                    dE -= 0.5 * old
                else:
                    mine = faces[k][di]
                    new = W_SURF * ((mine & ~nb & FACE).bit_count() * pps[di] * w
                                    + (nb & ~mine & FACE).bit_count() * pb)
                    if mine != nb and (mine not in nb_flat or nb not in nb_flat):
                        new += eds[di] * w
                    dE += new - old
                    res += new
        return (dE, res) if both else dE

    def touch(c):
        stamp[c] = clock[0]
        for q in nbr[c]:
            stamp[q] = clock[0]

    chosen = {}                 # piece id -> (type, cells, energy against plain blocks)
    piece_of = [None] * n
    ids = iter(range(1 << 62))

    def place(t, row, e0):
        i = next(ids)
        clock[0] += 1
        for k, c in enumerate(row):
            label[c] = (t, k)
            piece_of[c] = i
            touch(c)
        chosen[i] = (t, row, e0)

    def remove(i):
        _t, row, _e = chosen.pop(i)
        clock[0] += 1
        for c in row:
            label[c] = None
            piece_of[c] = None
            touch(c)

    # greedy, most certain first: by the error a piece leaves per voxel it covers, not by
    # how much it gains over blocks. Gain favours whatever covers the half-full voxels where
    # blocks are worst (a 1x1 wedge), even where a longer piece fits exactly; taking exact
    # fits first and building out from them keeps one pattern across a surface. A piece must
    # still beat the blocks it replaces by MIN_GAIN. A candidate whose neighbourhood changed
    # since it was scored is scored again and goes back in line, so a plane laid in pyramids
    # and inverse pyramids grows outward from its best-fitting piece instead of several
    # patterns meeting in a seam.
    cand = [(e, t, row, r) for t, cix, dE, res in found
            for e, row, r in zip(dE.tolist(), cix.tolist(), res.tolist())]
    cand.sort(key=lambda c: (c[3] / len(c[2]), -len(c[2]), c[1]))
    size = [len(c[2]) for c in cand]
    heap = [(r / size[j], j, 0, e) for j, (e, _t, _row, r) in enumerate(cand)]
    cand = [c[:3] for c in cand]
    heapq.heapify(heap)
    for _pass in range(PASSES):
        parked = []             # not worth it when last scored; may become so later
        while heap:
            _k, j, when, e = heapq.heappop(heap)
            _e0, t, row = cand[j]
            if any(label[c] is not None for c in row):
                continue
            if any(stamp[c] > when for c in row):
                e, r = delta(t, row, both=True)
                heapq.heappush(heap, (r / size[j], j, clock[0], e))
                continue
            if e > -MIN_GAIN:
                parked.append((j, when))
                continue
            place(t, row, _e0)
        # only pieces next to something placed since can have changed
        heap = []
        for j, when in parked:
            row = cand[j][2]
            if all(label[c] is None for c in row) and any(stamp[c] > when for c in row):
                e, r = delta(cand[j][1], row, both=True)
                if e <= -MIN_GAIN:
                    heap.append((r / size[j], j, clock[0], e))
        if not heap:
            break
        heapq.heapify(heap)

    # swap passes: try each good piece in place of whatever overlaps it, refill the cells
    # that frees, and keep the result when the exact total energy goes down. This is what
    # lets a straight row of wedges replace a zigzag of long pieces, and the other way round.
    good = [c for c in cand if c[0] <= -MIN_GAIN]
    by_cell = {}
    for j, (_e, _t, row) in enumerate(good):
        for c in row:
            by_cell.setdefault(c, []).append(j)

    def refill(freed):
        """Greedily fill free cells around `freed`; returns (energy change, piece ids)."""
        opts = {j for c in freed for j in by_cell.get(c, ())}
        scored = []
        for j in opts:
            _e, t, row = good[j]
            if all(label[c] is None for c in row):
                scored.append((delta(t, row), j))
        scored.sort(key=lambda s: s[0] / len(good[s[1]][2]))
        total, added = 0.0, []
        for e_first, j in scored:
            e0, t, row = good[j]
            if e_first > -MIN_GAIN or any(label[c] is not None for c in row):
                continue
            e = delta(t, row) if added else e_first
            if e > -MIN_GAIN:
                continue
            place(t, row, e0)
            added.append(piece_of[row[0]])
            total += e
        return total, added

    for _round in range(SWAPS):
        swapped = 0
        for e0, t, row in good:
            here = {piece_of[c] for c in row}
            if here == {None}:                           # all free: a plain addition
                if delta(t, row) <= -MIN_GAIN:
                    place(t, row, e0)
                    swapped += 1
                continue
            here.discard(None)
            if len(here) == 1:
                i = next(iter(here))
                if chosen[i][0] == t and chosen[i][1] == row:
                    continue
            old = [chosen[i] for i in here]
            e_was = sum(o[2] for o in old)
            size_was = sum(len(o[1]) for o in old)
            # only worth trying if better in isolation, in total or per voxel
            if e0 >= e_was - 1.0 and e0 / len(row) >= e_was / size_was - 0.5:
                continue
            e_old = 0.0
            for i in here:                               # what the evicted pieces are worth
                remove(i)
            for ot, orow, oe in old:
                e_old += delta(ot, orow)
                place(ot, orow, oe)
            for i in {piece_of[c] for o in old for c in o[1]}:
                remove(i)
            e_new = delta(t, row)
            if e_new > -MIN_GAIN:
                for ot, orow, oe in old:
                    place(ot, orow, oe)
                continue
            place(t, row, e0)
            mine = piece_of[row[0]]
            freed = [c for o in old for c in o[1] if label[c] is None]
            e_fill, added = refill(freed)
            if e_new + e_fill < e_old - 1.0:
                swapped += 1
                continue
            for i in [mine, *added]:                     # no better: put it all back
                remove(i)
            for ot, orow, oe in old:
                place(ot, orow, oe)
        if not swapped:
            break
    # clean-up at full cost: drop any piece that, against its final neighbours, makes the
    # surface worse than the plain blocks it replaced (a lone wedge whose partner never came)
    for _round in range(3):
        bad = []
        for i, (t, row, e0) in list(chosen.items()):
            remove(i)
            e = delta(t, row, hope=1.0)
            place(t, row, e0)
            if e > 0:
                bad.append(piece_of[row[0]])
        for i in bad:
            remove(i)
        if not bad:
            break
    picked = [(t, row) for t, row, _e in chosen.values()]

    # 3. drop pieces in the air that touch neither the hull nor a piece that does
    owner = {}
    for i, (_t, row) in enumerate(picked):
        for r in row:
            owner[cells[r]] = i
    attached = {i for i, (_t, row) in enumerate(picked) if any(solid_l[r] for r in row)}
    stack = list(attached)
    while stack:
        i = stack.pop()
        for r in picked[i][1]:
            for d in DIRS:
                j = owner.get(add(cells[r], d))
                if j is not None and j not in attached:
                    attached.add(j)
                    stack.append(j)

    plan = {}
    for i, (t, row) in enumerate(picked):
        if i not in attached:
            continue
        pl = cat[t]
        origin = cells[row[0]]
        paint = cells[max(row, key=lambda r: (solid_l[r], M_l[r].bit_count()))]
        for r in row:
            plan[cells[r]] = (pl["piece"], origin, pl["Q"], paint)
    return plan


def to_pieces(S, color_of, inside=None, smoothing="blocks", open_deck=False, region=None,
              skin=None, extra=None, carve=frozenset(), sample_mask=None, fixed=frozenset()):
    """Skin of S as pieces. `extra` adds interior blocks {voxel: colour}; `carve` opens holes
    in the skin (doors, hatches)."""
    skin = set(skin if skin is not None else shell(S))
    extra = extra or {}
    removed = set()
    if open_deck:
        hull_only = {v for v in skin if region is None or region.get(v) == "hull"}
        removed = deck_plates(S, hull_only)
        skin -= removed
    skin -= carve
    plan = (fit_pieces(S, inside, removed | set(carve), sample_mask, fixed, color_of)
            if smoothing == "wedges" else {})
    plan = {c: e for c, e in plan.items()
            if not any(add(e[1], apply(e[2], f)) in carve for f in e[0].footprint)}
    keep = set(skin) | set(plan)

    # seal: a partial piece must not open into the hollow interior
    cache = _catalogue()["full"] if plan else None
    seen = set()
    for piece, origin, Q, _paint in plan.values():
        if (origin, Q, piece.d) in seen:
            continue
        seen.add((origin, Q, piece.d))
        key = (piece.d, Q)
        full = cache.get(key)
        if full is None:
            full = cache[key] = _full_faces(piece, Q)
        for f in piece.footprint:
            w = apply(Q, f)
            cell = add(origin, w)
            for d in DIRS:
                n = add(cell, d)
                if n in S and n not in keep and n not in removed and n not in carve \
                        and (w, d) not in full:
                    keep.add(n)
    keep |= set(extra) - set(plan)

    placed, done = [], set()
    for v in sorted(keep, key=lambda p: (p[2], p[1], p[0])):
        if v in done:
            continue
        entry = plan.get(v)
        if entry:
            piece, origin, Q, paint = entry
            placed.append(Placed(piece, origin, Q, color_of(paint)))
            done.update(add(origin, apply(Q, f)) for f in piece.footprint)
            continue
        placed.append(Placed(BLOCK, v, color=extra.get(v) or color_of(v)))
        done.add(v)
    return placed
