"""Wedge smoothing: the piece catalogue matches the game, and the fitter picks the right pieces."""
import os
import re
from collections import Counter

import pytest
import numpy as np

from swhull.build import build, resolve_spec
from swhull.definitions import definitions_dir, load
from swhull.pieces import BY_NAME, CONTAINS, DIRS, SLOPES, Placed, _inv, _tetra, add, apply
from swhull.smooth import (SAMPLES, _face_bits, _full_faces, _placements,
                          _refined_planes, _slope, fit_pieces, to_pieces, _prefer_refined,
                          _catalogue, _corner_closeouts, _diagonal_corner_templates,
                          deck_plates, shell)

ORIENT = {0: (1, 0, 0), 1: (-1, 0, 0), 2: (0, 1, 0), 3: (0, -1, 0), 4: (0, 0, 1), 5: (0, 0, -1)}


def _coverage(test, cell, d):
    axis = [i for i in range(3) if d[i]][0]
    a, b = [i for i in range(3) if i != axis]
    hits = 0
    for i in range(10):
        for j in range(10):
            p = list(cell)
            p[axis] += 0.4999 * d[axis]
            p[a] += -0.45 + 0.1 * i
            p[b] += -0.45 + 0.1 * j
            hits += test(tuple(p))
    return hits / 100


@pytest.mark.skipif(definitions_dir() is None, reason="Stormworks is not installed")
@pytest.mark.parametrize("d", sorted(BY_NAME))
def test_piece_matches_game_definition(d):
    """Footprint, paint slots, mass, and which faces are full squares, against rom/data."""
    piece, game = BY_NAME[d], load(d)
    assert sorted(piece.footprint) == sorted(game.footprint)
    assert (piece.surfaces, piece.mass) == (game.surfaces, game.mass)
    with open(os.path.join(definitions_dir(), f"{d}.xml"), encoding="utf-8") as f:
        surfaces = f.read().split("<buoyancy_surfaces")[0].split("<surfaces")[1]
    full = set()
    for m in re.finditer(r'<surface orientation="(\d)" rotation="\d+" shape="(\d+)"[^>]*>\s*'
                         r'<position ([^/]*)/>', surfaces):
        pos = dict(re.findall(r'([xyz])="(-?\d+)"', m.group(3)))
        if m.group(2) == "1":
            full.add((tuple(int(pos.get(k, 0)) for k in "xyz"), ORIENT[int(m.group(1))]))
    test = CONTAINS[d]
    mine = {(c, n) for c in piece.footprint for n in DIRS
            if add(c, n) not in piece.footprint and _coverage(test, c, n) > 0.999}
    assert mine == full


def test_catalogue_is_every_slope_piece():
    assert len(SLOPES) == 15 and len(BY_NAME) == 16
    counts = {p.d: len(_placements(p)) for p in SLOPES}
    assert counts["02_wedge"] == 12 and counts["03_pyramid"] == counts["04_invpyramid"] == 8
    # the 2x4 pieces have three different sides: their mirror images are new shapes
    assert counts["12_pyramid_2x4"] == counts["15_invpyramid_2x4"] == 48
    assert all(n == 24 for d, n in counts.items()
               if d not in ("02_wedge", "03_pyramid", "04_invpyramid", "12_pyramid_2x4", "15_invpyramid_2x4"))


@pytest.mark.parametrize("piece", SLOPES, ids=lambda p: p.d)
def test_slope_area_adds_up(piece):
    _, area = _slope(piece)
    xs = [v[0] for v in piece.verts]
    ys = [v[1] for v in piece.verts]
    zs = [v[2] for v in piece.verts]
    a, b, c = max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)
    if "wedge" in piece.d:
        expect = a * (b * b + c * c) ** 0.5
    else:                                        # the triangle across a corner of the box
        expect = 0.5 * ((a * b) ** 2 + (b * c) ** 2 + (c * a) ** 2) ** 0.5
    assert sum(area.values()) == pytest.approx(expect, rel=1e-3)
    assert set(area) <= set(piece.footprint)


def _on_plate(raised, size=10):
    """A shape standing on a solid plate, as it would on a hull, and its voxels."""
    def inside(p):
        return raised(p) or (-1.5 <= p[1] <= -0.5 and abs(p[0]) <= size + 0.5 and abs(p[2]) <= size + 0.5)
    solid = {(x, y, z) for x in range(-size, size + 1) for y in range(-1, 8)
             for z in range(-size, size + 1) if inside((x, y, z))}
    return solid, inside


def _hip_roof(extent, run):
    def inside(p):
        m = max(abs(p[0]), abs(p[2]))
        return m <= extent and 0 <= p[1] + 0.5 <= (extent - m) / run
    return inside


@pytest.mark.parametrize("run, piece", [(4, "08_wedge_4"), (2, "05_wedge_2")])
def test_hip_roof_gets_the_matching_wedge(run, piece):
    # a 1:4 roof must be laid in Wedge 1x4 and a 1:2 roof in Wedge 1x2, all four sides
    solid, inside = _on_plate(_hip_roof(6.5 if run == 4 else 4.5, run))
    plan = fit_pieces(solid, inside)
    used = Counter(e[0].d for c, e in plan.items() if c == e[1])
    assert set(used) == {piece}
    sides = Counter((o[0] > 0) - (o[0] < 0) + 3 * ((o[2] > 0) - (o[2] < 0))
                    for c, (_p, o, _q, _) in plan.items() if c == o)
    assert len(sides) >= 4


def _corner_plane(a, c, E=5.5):
    """A slab on a plate whose top falls 1 per `a` along x and 1 per `c` along z: a face
    that pyramids and inverse pyramids of that size tile exactly, stacked in pairs."""
    def raised(p):
        return (abs(p[0]) <= E and abs(p[2]) <= E
                and 0 <= p[1] + 0.5 <= 1 + (E - p[0]) / a + (E - p[2]) / c)

    def inside(p):
        return raised(p) or (-1.5 <= p[1] <= -0.5 and abs(p[0]) <= E + 1.5 and abs(p[2]) <= E + 1.5)
    top = int(4 + 2 * E / a + 2 * E / c)
    r = int(E) + 2
    solid = {(x, y, z) for x in range(-r, r + 1) for y in range(-1, top) for z in range(-r, r + 1)
             if inside((x, y, z))}
    return solid, inside


@pytest.mark.parametrize("a, c, pair", [
    (1, 1, ("03_pyramid", "04_invpyramid")),
    (1, 2, ("06_pyramid_2", "07_invpyramid_2")),
    (4, 1, ("09_pyramid_4", "10_invpyramid_4")),
    (2, 2, ("11_pyramid_2x2", "14_invpyramid_2x2")),
    (2, 4, ("12_pyramid_2x4", "15_invpyramid_2x4")),
    (4, 2, ("12_pyramid_2x4", "15_invpyramid_2x4")),        # only possible mirrored
    (4, 4, ("13_pyramid_4x4", "16_invpyramid_4x4")),
])
def test_corner_plane_is_laid_in_pyramid_pairs(a, c, pair):
    # how players build a face sloping two ways: a pyramid stacked on an inverse pyramid of
    # the same size, repeated, gives one flat face; lone pyramids on blocks leave hard edges
    solid, inside = _corner_plane(a, c)
    plan = fit_pieces(solid, inside)
    covered = Counter(e[0].d in pair for e in plan.values())
    assert covered[True] >= 0.55 * (covered[True] + covered[False])


@pytest.mark.parametrize("dims", [(1, 1, 1), (1, 1, 2), (2, 1, 4), (4, 1, 4)])
def test_pyramid_and_inverse_faces_agree_where_they_meet(dims):
    # across each back face of a pyramid, an inverse pyramid of the same size continues the
    # slope; both sides must sample that shared face the same, or the perfect joint scores
    # as a step (the sample grid once had points exactly on the diagonal)
    a, b, c = dims
    pyr, inv = _tetra(*dims)[2], _inv(*dims)[2]
    for shift, d in (((a, 0, 0), (1, 0, 0)), ((0, -b, 0), (0, -1, 0)), ((0, 0, c), (0, 0, 1))):
        for cell in [(-i, j, -k) for i in range(a) for j in range(b) for k in range(c)]:
            if cell[0] != 0 and d[0] or cell[1] != 0 and d[1] or cell[2] != 0 and d[2]:
                continue                            # not on that back face
            mine = _face_bits(pyr, cell, d)
            other = _face_bits(lambda p, s=shift: inv(tuple(p[i] - s[i] for i in range(3))),
                               add(cell, d), tuple(-x for x in d))
            assert mine == other, (dims, d, cell)


@pytest.mark.parametrize("wedge,pyramid,inverse", [
    ("02_wedge", "03_pyramid", "04_invpyramid"),
    ("05_wedge_2", "06_pyramid_2", "07_invpyramid_2"),
    ("08_wedge_4", "09_pyramid_4", "10_invpyramid_4"),
])
def test_green_test_diagonal_corner_faces_match(wedge, pyramid, inverse):
    # Relative positions and orientation measured from the hand-built Green_Test.xml.
    # The 1x2 example has a wedge, then pyramid/inverse/pyramid/inverse
    # stepping diagonally; the same joints work for 1x1 and 1x4.
    Q = ((0, -1, 0), (0, 0, -1), (1, 0, 0))
    back = tuple(zip(*Q))
    A, B, lead = (apply(Q, v) for v in ((0, -1, 0), (-1, 0, 0), (1, 0, 0)))
    parts = [Placed(BY_NAME[d], o, Q) for d, o in (
        (wedge, lead), (pyramid, (0, 0, 0)), (inverse, A),
        (pyramid, add(A, B)), (inverse, add(add(A, A), B)))]
    owner = {v: part for part in parts for v in part.voxels()}
    assert len(owner) == sum(len(part.piece.footprint) for part in parts)
    checked = 0
    for v, part in owner.items():
        for d in DIRS:
            q = add(v, d)
            other = owner.get(q)
            if other is None or other is part:
                continue
            def face(piece, cell, direction):
                def test(p):
                    return CONTAINS[piece.piece.d](apply(back, p))
                return _face_bits(test, tuple(cell[k] - piece.origin[k] for k in range(3)),
                                  direction)
            assert face(part, v, d) == face(other, q, tuple(-x for x in d))
            checked += 1
    assert checked >= 6


@pytest.mark.parametrize("wedge,pyramid,inverse", [
    ("05_wedge_2", "06_pyramid_2", "07_invpyramid_2"),
    ("08_wedge_4", "09_pyramid_4", "10_invpyramid_4"),
])
def test_corner_closeout_can_replace_a_whole_diagonal_chain(wedge, pyramid, inverse):
    Q = ((0, -1, 0), (0, 0, -1), (1, 0, 0))
    back = tuple(zip(*Q))
    A, B, lead = (apply(Q, v) for v in ((0, -1, 0), (-1, 0, 0), (1, 0, 0)))
    target = [Placed(BY_NAME[d], o, Q, "00ff00") for d, o in (
        (wedge, lead), (pyramid, (0, 0, 0)), (inverse, A),
        (pyramid, add(A, B)), (inverse, add(add(A, A), B)))]
    solid = {v for part in target for v in part.voxels()}

    def inside(point):
        return any(CONTAINS[part.piece.d](apply(back, tuple(
            point[k] - part.origin[k] for k in range(3)))) for part in target)

    cells = sorted(solid)
    masks = {v: sum(1 << j for j, s in enumerate(SAMPLES) if inside(add(v, s)))
             for v in cells}
    initial = [target[0]] + [Placed(BY_NAME["01_block"], v, color="00ff00")
                             for v in cells if v not in set(target[0].voxels())]
    templates = _diagonal_corner_templates(_catalogue()["placements"])
    assert any(len(template) == 5 for template in templates)
    after, changes = _corner_closeouts(initial, solid, cells, masks, inside, set(),
                                       lambda _: "00ff00")
    assert changes
    assert sum(part.piece.d == pyramid for part in after) == 2
    assert sum(part.piece.d == inverse for part in after) == 2


@pytest.mark.parametrize("run,inverse", [(1, "04_invpyramid"),
                                          (2, "07_invpyramid_2"),
                                          (4, "10_invpyramid_4")])
def test_green_test_01_stacked_inverse_faces_match(run, inverse):
    # The pink inverse sits above the green inverse in Green_Test_01.xml.
    lower_q = ((0, 1, 0), (0, 0, -1), (-1, 0, 0))
    upper_q = ((-1, 0, 0), (0, 0, 1), (0, 1, 0))
    lower = Placed(BY_NAME[inverse], (0, 0, 0), lower_q)
    upper = Placed(BY_NAME[inverse], (0, 2 * run - 1, 0), upper_q)
    touching = [(v, add(v, (0, 1, 0))) for v in lower.voxels()
                if add(v, (0, 1, 0)) in upper.voxels()]
    assert touching
    for v, q in touching:
        def face(part, cell, direction):
            back = tuple(zip(*part.Q))
            def contains(p):
                return CONTAINS[part.piece.d](apply(back, p))
            return _face_bits(contains,
                              tuple(cell[k] - part.origin[k] for k in range(3)), direction)
        assert face(lower, v, (0, 1, 0)) == face(upper, q, (0, -1, 0))


@pytest.mark.parametrize("wedge", ["02_wedge", "05_wedge_2", "08_wedge_4"])
@pytest.mark.parametrize("steps", [2, 3])
def test_complete_corner_run_joins_both_wedge_sides(wedge, steps):
    cat = _catalogue()["placements"]
    template = next(t for t in _diagonal_corner_templates(cat)
                    if len(t) == 2 * steps + 1 and cat[t[0][0]]["piece"].d == wedge
                    and cat[t[-1][0]]["piece"].d == wedge)
    parts = [Placed(cat[t]["piece"], origin, cat[t]["Q"])
             for t, origin in template]
    owner = {v: p for p in parts for v in p.voxels()}
    assert len(owner) == sum(len(p.piece.footprint) for p in parts)
    contacts = 0
    for v, part in owner.items():
        for d in DIRS:
            q = add(v, d)
            other = owner.get(q)
            if other is None or other is part:
                continue
            def face(p, cell, direction):
                back = tuple(zip(*p.Q))
                def contains(point):
                    return CONTAINS[p.piece.d](apply(back, point))
                return _face_bits(contains,
                                  tuple(cell[k] - p.origin[k] for k in range(3)), direction)
            assert face(part, v, d) == face(other, q, tuple(-x for x in d))
            contacts += 1
    assert contacts >= 2 * steps


def test_vertical_deckhouse_chamfer_uses_sideways_wedges(monkeypatch):
    monkeypatch.setenv("SW_BUILD_CACHE", "0")
    box = {"x": 0, "z": 0, "length": 5, "width": 4, "height": 1,
           "corner_chamfer": 0.25}
    parts, info = build(resolve_spec({"length": 9, "beam": 5, "depth": 2,
                                      "smoothing": "wedges_v2",
                                      "superstructure": [box]}))
    shift = info["shift"]
    vertical = []
    for part in parts:
        if part.piece.d != "02_wedge":
            continue
        v = add(part.origin, shift)
        if info["region"].get(v) != "box0":
            continue
        normal, _ = _slope(part.piece)
        if abs(apply(part.Q, normal)[1]) < 1e-9:
            vertical.append(part)
    assert len(vertical) >= 4


def test_deckhouse_waist_stacks_matching_inverse_pyramids(monkeypatch):
    monkeypatch.setenv("SW_BUILD_CACHE", "0")
    box = {"x": 0, "z": 0, "length": 5, "width": 4, "height": 1,
           "corner_chamfer": 0.5,
           "waist": {"from": 0, "peak": 0.5, "to": 1, "inset": 0.25}}
    parts, _ = build(resolve_spec({"length": 9, "beam": 5, "depth": 2,
                                   "smoothing": "wedges_v2",
                                   "superstructure": [box]}))
    inverses = [p for p in parts if p.piece.d == "07_invpyramid_2"]
    owner = {v: part for part in inverses for v in part.voxels()}
    pairs = []
    for lower in inverses:
        normal, _ = _slope(lower.piece)
        if apply(lower.Q, normal)[1] <= 0:
            continue
        top = max(lower.voxels(), key=lambda v: v[1])
        upper = owner.get(add(top, (0, 1, 0)))
        if upper is None or upper is lower:
            continue
        other_normal, _ = _slope(upper.piece)
        if apply(upper.Q, other_normal)[1] >= 0:
            continue
        def face(part, cell, direction):
            back = tuple(zip(*part.Q))
            def contains(p):
                return CONTAINS[part.piece.d](apply(back, p))
            offset = tuple(cell[k] - part.origin[k] for k in range(3))
            return _face_bits(contains, offset, direction)
        assert face(lower, top, (0, 1, 0)) == face(
            upper, add(top, (0, 1, 0)), (0, -1, 0))
        pairs.append((lower, upper))
    assert len(pairs) >= 4


def test_mirror_images_fit_alike():
    # the fit must not depend on which way a face looks (tie-breaks, sample offsets)
    solid, inside = _on_plate(_hip_roof(6.5, 4))
    plan = fit_pieces(solid, inside)
    origins = {e[1] for e in plan.values()}
    mirrored = {(-x, y, z) for x, y, z in origins}
    assert len(origins ^ mirrored) <= len(origins) // 4


@pytest.mark.parametrize("mode", ["wedges", "wedges_v2"])
@pytest.mark.parametrize("preset", ["fishing_trawler", "runabout"])
def test_no_material_where_the_shape_is_empty(preset, mode):
    # a piece may reach a sliver into an empty voxel only if the shape reaches it too:
    # otherwise its tip reads as a spike sticking out of the hull
    placed, info = build(resolve_spec({"smoothing": mode}, preset=preset))
    shape, shift = info["shape"], info["shift"]
    for p in placed:
        if p.piece.d not in BY_NAME or p.piece.d == "01_block":
            continue
        test, back = CONTAINS[p.piece.d], tuple(zip(*p.Q))          # world -> local
        for v in p.voxels():
            local = apply(back, tuple(v[i] - p.origin[i] for i in range(3)))
            if not any(test(add(local, apply(back, s))) for s in SAMPLES):
                continue                                 # a sliver too thin to see
            w = tuple(v[i] + shift[i] for i in range(3))
            assert shape.sample_mask(w, SAMPLES) or w in info["region"], (p.piece.d, w)


@pytest.mark.parametrize("mode", ["wedges", "wedges_v2"])
@pytest.mark.parametrize("preset", ["tugboat", "fishing_trawler"])
def test_wedge_skin_is_watertight(preset, mode):
    # every face of a slope piece toward the hollow inside of the hull is a full face
    placed, info = build(resolve_spec({"smoothing": mode}, preset=preset))
    shift = info["shift"]
    solid = {tuple(v[i] - shift[i] for i in range(3)) for v in info["region"]}
    taken = {v for p in placed for v in p.voxels()}
    doors = {tuple(v[i] - shift[i] for i in range(3)) for v in info["interior"].carve}
    hollow = solid - taken - doors                  # doors and hatches are meant to be open
    checked = 0
    for p in placed:
        if p.piece.d == "01_block" or p.piece.d not in BY_NAME:
            continue
        full = _full_faces(p.piece, p.Q)
        for f in p.piece.footprint:
            w = apply(p.Q, f)
            cell = add(p.origin, w)
            for d in DIRS:
                if add(cell, d) in hollow:
                    checked += 1
                    assert (w, d) in full, (p.piece.d, cell, d)
    assert checked


@pytest.mark.parametrize("normal", [(0.0, 1.0, 0.25), (0.5, -1.0, 0.25), (-1.0, 0.25, -0.5)])
def test_refined_planes_recover_off_grid_angle_and_depth(normal):
    # Occupancy gradients quantize these offsets; continuous intersections should recover
    # the actual plane, even upside down or facing another axis.
    unit = np.array(normal) / np.linalg.norm(normal)
    offset = 0.071
    def inside(p):
        return np.dot(unit, p) <= offset
    mask = sum(1 << i for i, p in enumerate(SAMPLES) if inside(p))
    normals, confidence, offsets = _refined_planes([(0, 0, 0)], np.array([mask], dtype=np.uint64),
                                                  unit[None, :], inside, np.array([True]))
    assert normals[0] == pytest.approx(unit, abs=0.002)
    assert confidence[0] == 1
    assert offsets[0] == pytest.approx(offset, abs=0.002)


def test_refined_corner_is_not_a_diagonal_plane():
    def inside(p):
        return p[0] <= 0.11 and p[1] <= 0.07
    mask = sum(1 << i for i, p in enumerate(SAMPLES) if inside(p))
    _, confidence, _ = _refined_planes([(0, 0, 0)], np.array([mask], dtype=np.uint64),
                                      np.array([[1, 1, 0]]), inside, np.array([True]))
    assert confidence[0] < 0.5


@pytest.mark.parametrize("mode", ["wedges", "wedges_v2"])
def test_floor_at_sloped_skin_remains_full_blocks(mode):
    solid, inside = _on_plate(_hip_roof(6.5, 4))
    floor = {v: "112233" for v in solid if v[1] == 0}
    parts = to_pieces(solid, lambda _: "334455", inside=inside, smoothing=mode, extra=floor)
    owner = {v: p for p in parts for v in p.voxels()}
    assert floor
    for v in floor:
        assert owner[v].piece.d == "01_block"
        assert owner[v].color == "112233"


@pytest.mark.parametrize("run,piece", [(1, "02_wedge"), (2, "05_wedge_2"), (4, "08_wedge_4")])
def test_v2_still_uses_matching_wedge_for_exact_planes(run, piece):
    solid, inside = _on_plate(_hip_roof(6.5 if run == 4 else 4.5, run))
    plan = fit_pieces(solid, inside, refined=True)
    allowed = {piece, "03_pyramid"} if run == 1 else {piece}
    assert {entry[0].d for entry in plan.values()} <= allowed
    assert any(entry[0].d == piece for entry in plan.values())


def test_v2_guard_rejects_more_seams_and_excess_shape_loss():
    original = {"wrong_samples": 100, "tested_samples": 1000, "mismatched_joints": 40}
    assert _prefer_refined(original, {**original, "wrong_samples": 102, "mismatched_joints": 30})
    assert not _prefer_refined(original, {**original, "wrong_samples": 110, "mismatched_joints": 20})
    assert not _prefer_refined(original, {**original, "wrong_samples": 80, "mismatched_joints": 41})
    assert not _prefer_refined(original, original)


def test_open_deck_removes_lower_skin_ribs_under_height_steps():
    solid = {(x, y, z) for x in range(-5, 6) for z in range(12)
             for y in range(5 + z // 3)}
    skin = shell(solid)
    removed = deck_plates(solid, skin)
    # These cells have a solid voxel directly above, but are retained in the shell
    # because the diagonal above is outside. They used to become cockpit stripes.
    lower_ribs = {v for v in skin if v[0] == 0 and 1 <= v[2] <= 10
                  and (v[0], v[1] + 1, v[2]) in solid and v[1] >= 4}
    assert lower_ribs
    assert lower_ribs <= removed
    assert not any(v in removed for v in skin if abs(v[0]) == 5)


@pytest.mark.parametrize("mode", ["blocks", "wedges", "wedges_v2"])
def test_sheered_cockpit_has_no_skin_above_walking_floor(mode):
    parts, info = build(resolve_spec({"length": 8, "beam": 4, "depth": 2,
                                     "deck": "open", "smoothing": mode,
                                     "sheer": {"bow": 1, "stern": 0},
                                     "interior": {"decks": [1.5]}}))
    owner = {tuple(v[i] + info["shift"][i] for i in range(3)): p
             for p in parts for v in p.voxels()}
    # A centreline walking path must be air from its floor up through the opening.
    for z in range(4, 26):
        for y in range(6, 12):
            assert (0, y, z) not in owner, (mode, y, z)
