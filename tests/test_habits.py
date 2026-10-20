"""Veteran finishing: chamfered corners, bevelled roof edges and pyramid caps that meet exactly."""
from types import SimpleNamespace

import pytest

from swhull import habits
from swhull.build import build, resolve_spec
from swhull.pieces import BLOCK, PYRAMID, WEDGE, Placed, add, apply


def faces_on(part, axis, value):
    """Vertex sets of a part's faces lying on the plane coordinate[axis] == value."""
    verts = [add(part.origin, apply(part.Q, v)) for v in part.piece.verts]
    out = set()
    for face in part.piece.faces:
        pts = [verts[i] for i in face]
        if all(abs(p[axis] - value) < 1e-9 for p in pts):
            out.add(frozenset(tuple(round(c, 6) for c in p) for p in pts))
    return out


@pytest.mark.parametrize("sx,sz", [(1, 1), (1, -1), (-1, 1), (-1, -1)])
def test_corner_pieces_meet_face_to_face(sx, sz):
    column = Placed(WEDGE, (0, 0, 0), habits._chamfer(sx, sz))
    cap = Placed(PYRAMID, (0, 1, 0), habits._corner_cap(sx, sz))
    bevel_x = Placed(WEDGE, (-sx, 1, 0), habits._bevel((0, 0, sz)))   # edge running along x
    bevel_z = Placed(WEDGE, (0, 1, -sz), habits._bevel((sx, 0, 0)))   # edge running along z
    # The cap sits exactly on the column's top triangle.
    assert faces_on(cap, 1, 0.5) == faces_on(column, 1, 0.5) and faces_on(cap, 1, 0.5)
    # Each bevel's end triangle matches the cap's side triangle.
    assert faces_on(cap, 0, -sx * 0.5) == faces_on(bevel_x, 0, -sx * 0.5) != set()
    assert faces_on(cap, 2, -sz * 0.5) == faces_on(bevel_z, 2, -sz * 0.5) != set()
    # The column keeps full square faces against the walls behind it.
    assert len(next(iter(faces_on(column, 0, -sx * 0.5)))) == 4
    assert len(next(iter(faces_on(column, 2, -sz * 0.5)))) == 4


def cabin(**extra):
    box = {"name": "cabin", "z": 6.0, "length": 3.0, "width": 2.5, "height": 2.0, **extra}
    return resolve_spec({"smoothing": "wedges", "superstructure": [box]}, "barge")


def by_cell(parts):
    return {tuple(v): p for p in parts for v in p.voxels()}


def test_a_free_cabin_is_finished_on_every_corner_and_roof_edge():
    parts, info = build(cabin())
    assert info["finish"] == {"finished": ["cabin"], "square": {}}
    counts = {}
    for p in parts:
        counts[p.piece.d] = counts.get(p.piece.d, 0) + 1
    # Four pyramid caps; the bevel and column wedges come on top of the hull's own slopes.
    pyramids = [p for p in parts if p.piece.d == "03_pyramid" and p.origin[1] == max(q.origin[1] for q in parts)]
    assert len(pyramids) == 4
    cells = by_cell(parts)
    for cap in pyramids:
        x, y, z = cap.origin
        below = cells[(x, y - 1, z)]
        assert below.piece.d == "02_wedge"  # every cap stands on a chamfer column


def test_explicit_corner_choice_keeps_the_box_square():
    _, info = build(cabin(corner_chamfer=0))
    assert info["finish"] == {"finished": [], "square": {}}


def test_boxes_touching_at_a_corner_stay_square_and_say_why():
    spec = resolve_spec({"smoothing": "wedges", "superstructure": [
        {"name": "cabin", "z": 6.0, "length": 3.0, "width": 2.5, "height": 2.0},
        {"name": "locker", "z": 9.0, "length": 1.5, "width": 2.5, "height": 1.0}]}, "barge")
    _, info = build(spec)
    assert "cabin" not in info["finish"]["finished"]
    assert "cabin" in info["finish"]["square"]


def test_blocks_smoothing_leaves_boxes_alone():
    spec = cabin()
    spec["smoothing"] = "blocks"
    parts, info = build(spec)
    assert info["finish"] == {"finished": [], "square": {}}
    assert not any(p.piece.d == "03_pyramid" for p in parts)


# --- ballast -----------------------------------------------------------------------------------

def box_hull(width=9, height=8, length=40, deck=True):
    """A closed box hull: skin pieces on the outside, air inside, every cell tagged hull."""
    half = width // 2
    region, placed = {}, []
    for x in range(-half, half + 1):
        for y in range(height):
            for z in range(length):
                region[(x, y, z)] = "hull"
                skin = x in (-half, half) or y == 0 or z in (0, length - 1) or (deck and y == height - 1)
                if skin:
                    placed.append(Placed(BLOCK, (x, y, z)))
    return region, placed


def no_rooms():
    return SimpleNamespace(reserved=set(), carve=set(), rooms=[])


def bow_load():
    """Heavy parts on the deck near the bow: stacked copies stand in for equipment."""
    return [Placed(BLOCK, (x, 7, z), name="bow load") for x in range(-3, 4) for z in range(30, 38)
            for _ in range(8)]


def test_box_hull_hydrostatics_match_the_textbook():
    region, _ = box_hull(width=9, height=8, length=40)
    hull = habits.Hull([v for v in region])
    area = 9 * 40
    f = hull.float(mass=area * 3 * habits.K_ESTIMATE)   # three layers under water
    assert f["plane"] == pytest.approx(2.5)
    assert f["volume"] == pytest.approx(area * 3)
    assert f["lcb"] == pytest.approx(19.5) and f["kb"] == pytest.approx(1.0)
    # Waterplane second moments of a 9 x 40 rectangle about its centre lines.
    assert f["it"] == pytest.approx(40 * 9 ** 3 / 12)
    assert f["il"] == pytest.approx(9 * 40 ** 3 / 12)


def test_bow_heavy_hull_is_levelled_with_low_weight_aft_in_pairs():
    region, placed = box_hull()
    placed += bow_load()
    out, report = habits.ballast(placed, region, no_rooms(), waterline=3.5, structural=10_000)
    weights = [p for p in out if p.piece.d == "01_block_weight"]
    assert report["before"]["end"] > habits.TRIM_TOLERANCE
    assert abs(report["after"]["end"]) <= habits.TRIM_TOLERANCE / 2
    assert report["reasons"][0] == "level the trim" and weights
    assert sum(p.origin[2] for p in weights) / len(weights) < 19.5       # mostly aft of midships
    assert all(p.origin[1] < 1 + max(habits.MAX_LAYERS, 2) for p in weights)  # low
    xs = sorted(p.origin[0] for p in weights)
    assert xs == sorted(-x for x in xs)                                  # port/starboard pairs


def test_ballast_avoids_rooms_access_and_open_cockpits():
    region, placed = box_hull(deck=False)          # light and open: wants weight, has no deck
    out, report = habits.ballast(placed, region, no_rooms(), waterline=3.5, structural=10_000)
    assert report["blocks"] == 0 and "no free bottom space" in report["shortfall"]
    region, placed = box_hull()
    placed += bow_load()
    room = SimpleNamespace(air={(x, 1, z) for x in range(-3, 4) for z in range(1, 20)})
    reserved = {(0, 1, z) for z in range(20, 39)}
    interior = SimpleNamespace(reserved=reserved, carve=set(), rooms=[room])
    out, _ = habits.ballast(placed, region, interior, waterline=3.5, structural=10_000)
    cells = {p.origin for p in out if p.piece.d == "01_block_weight"}
    assert cells and not cells & (room.air | reserved)


def test_ballast_limit_and_none_mode():
    region, placed = box_hull()
    placed += bow_load()
    out, report = habits.ballast(placed, region, no_rooms(), waterline=3.5, structural=100)
    assert report["blocks"] <= 4 and "limit" in report["shortfall"]
    out, report = habits.ballast(placed, region, no_rooms(), waterline=3.5, structural=10_000, mode="none")
    assert report["blocks"] == 0 and out == placed and report["after"] is not None


def test_presets_get_ballast_unless_turned_off():
    spec = resolve_spec({"smoothing": "wedges"}, "patrol_boat")
    parts, info = build(spec)
    weights = [p for p in parts if p.piece.d == "01_block_weight"]
    assert weights and info["ballast"]["blocks"] == len(weights)
    assert sum(p.origin[0] for p in weights) == 0
    spec["ballast"] = "none"
    parts, info = build(spec)
    assert not any(p.piece.d == "01_block_weight" for p in parts)
    assert info["ballast"]["after"] is not None
