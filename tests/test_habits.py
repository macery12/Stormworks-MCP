"""Veteran finishing: chamfered corners, bevelled roof edges and pyramid caps that meet exactly."""
from types import SimpleNamespace

import pytest

from swhull import definitions, habits
from swhull.build import build, resolve_spec
from swhull.pieces import BLOCK, PYRAMID, WEDGE, Placed, _det, add, apply


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


# --- railings ----------------------------------------------------------------------------------

def rails_of(parts):
    return {p.origin: p for p in parts if p.piece.d.startswith("railing")}


def kinds(parts):
    out = {}
    for p in rails_of(parts).values():
        out[p.piece.d] = out.get(p.piece.d, 0) + 1
    return out


@pytest.mark.parametrize("kind", sorted(habits.RAILS))
def test_railing_pieces_match_the_game_definitions(kind):
    piece = habits.RAILS[kind]
    data = definitions.metadata(piece.d)
    if data is None or definitions.definitions_dir() is None:
        pytest.skip("game definitions not installed")
    assert piece.surfaces == len(data["attachment_surfaces"])
    assert piece.mass == data["mass"]
    assert list(piece.footprint) == [tuple(v) for v in data["footprint"]]


def test_a_box_deck_gets_a_closed_railing_with_corner_posts_and_even_spacing():
    region, placed = box_hull(width=9, height=8, length=40)
    out, report = habits.railings(placed, region, no_rooms(), [])
    rails = rails_of(out)
    assert kinds(out)["railing_segment_corner"] == 4 and "railing_segment_end" not in kinds(out)
    assert len(rails) == 2 * (9 + 40) - 4 == report["pieces"]
    assert all(y == 8 for _, y, _ in rails)                         # standing on the deck
    assert sorted(x for x, _, _ in rails) == sorted(-x for x, _, _ in rails)
    for x in (-4, 4):                                                # posts along each side
        posts = sorted(z for (px, _, z), p in rails.items() if px == x
                       and p.piece.d in ("railing_segment_middle", "railing_segment_corner"))
        assert posts[0] == 0 and posts[-1] == 39
        assert max(b - a for a, b in zip(posts, posts[1:])) <= habits.RAIL_SPACING


def test_railings_skip_short_edges_blocked_cells_and_none_mode():
    region, placed = box_hull(width=5, height=4, length=7)           # every edge under 2 m
    out, report = habits.railings(placed, region, no_rooms(), [])
    assert report["pieces"] == 0 and out == placed
    region, placed = box_hull()
    reserved = {(4, 8, z) for z in range(10, 13)}                    # an access path at the side
    interior = SimpleNamespace(reserved=reserved, carve=set(), rooms=[])
    out, _ = habits.railings(placed, region, interior, [])
    rails = rails_of(out)
    assert not {(4, 8, z) for z in range(10, 13)} & set(rails)
    assert rails[(4, 8, 9)].piece.d == rails[(4, 8, 13)].piece.d == "railing_segment_end"
    out, report = habits.railings(placed, region, no_rooms(), [], mode="none")
    assert out == placed and report["pieces"] == 0


def test_a_one_block_deck_step_carries_the_railing_up_an_incline():
    region, placed = box_hull(width=9, height=8, length=40)
    for x in range(-4, 5):                                           # forward half one block higher
        for z in range(20, 40):
            region[(x, 8, z)] = "hull"
            placed.append(Placed(BLOCK, (x, 8, z)))
    out, _ = habits.railings(placed, region, no_rooms(), [])
    rails = rails_of(out)
    incline = rails[(4, 9, 19)]                                      # over the lower run's last cell
    assert incline.piece.d == "railing_extension_angle"
    assert apply(incline.Q, (0, 0, -1)) == (0, 0, 1)                 # high end toward the upper run
    assert rails[(4, 9, 20)].piece.d == "railing_segment_middle"     # the upper run starts on a post
    assert (4, 8, 19) not in rails and (4, 8, 18) in rails


def test_a_cut_deck_corner_is_bridged_by_a_mirrored_pair_of_diagonal_pieces():
    region, placed = box_hull(width=13, height=8, length=40)
    corners = {(x, 7, z) for x in (-6, 6) for z in (0, 39)}
    placed = [p for p in placed if p.origin not in corners]
    for x, y, z in corners:
        placed.append(Placed(WEDGE, (x, y, z), habits._chamfer(1 if x > 0 else -1, 1 if z > 0 else -1)))
    out, _ = habits.railings(placed, region, no_rooms(), [])
    diag = [p for p in rails_of(out).values() if p.piece.d == "railing_segment_corner_diag"]
    assert len(diag) == 8 and not any(p.piece.d == "railing_segment_corner" for p in out)
    assert sorted(_det(p.Q) for p in diag) == [-1] * 4 + [1] * 4     # chiral: half are mirrored
    for p in diag:                                                   # each pair is diagonal neighbours
        x, y, z = p.origin
        assert sum((x + dx, y, z + dz) in rails_of(out) and rails_of(out)[(x + dx, y, z + dz)].piece.d
                   == p.piece.d for dx in (-1, 1) for dz in (-1, 1)) == 1


def test_preset_railings_follow_the_reference_ships():
    tug, info = build(resolve_spec({"smoothing": "wedges"}, "tugboat"))
    assert info["railings"]["pieces"] == len(rails_of(tug))
    assert sum(p.origin[0] for p in rails_of(tug).values()) == 0
    # The deckhouse carries the wheelhouse: its roof is railed all round, ending only at walls.
    deckhouse = max(p.origin[1] for p in rails_of(tug).values())
    roof = [p for p in rails_of(tug).values() if p.origin[1] == deckhouse]
    assert len([p for p in roof if p.piece.d == "railing_segment_corner"]) == 4
    # The patrol boat's bridge is tapered and raked: no roof railings, main deck only.
    boat, info = build(resolve_spec({"smoothing": "wedges"}, "patrol_boat"))
    assert {p.origin[1] for p in rails_of(boat).values()} == {min(p.origin[1] for p in rails_of(boat).values())}
    spec = resolve_spec({"smoothing": "wedges", "railings": "none"}, "patrol_boat")
    parts, info = build(spec)
    assert not rails_of(parts) and info["railings"]["pieces"] == 0


def test_railings_spec_is_validated():
    with pytest.raises(ValueError, match="railings must be"):
        build(resolve_spec({"railings": "yes"}, "barge"))
    with pytest.raises(ValueError, match="colors.rail"):
        build(resolve_spec({"colors": {"rail": "white"}}, "barge"))
    parts, _ = build(resolve_spec({"colors": {"rail": "1a1a1a"}}, "barge"))
    assert {p.color for p in rails_of(parts).values()} == {"1A1A1A"}


# --- mooring cleats ----------------------------------------------------------------------------

def test_rope_anchor_matches_the_game_definition():
    data = definitions.metadata("rope_hook")
    if data is None or definitions.definitions_dir() is None:
        pytest.skip("game definitions not installed")
    assert habits.CLEAT.surfaces == len(data["attachment_surfaces"]) and habits.CLEAT.mass == data["mass"]
    assert list(habits.CLEAT.footprint) == [tuple(v) for v in data["footprint"]]
    # Its base is a sealed block, so it can take a deck block's place.
    assert all(s["shape"] == 1 for s in data["sealing_surfaces"]) and len(data["sealing_surfaces"]) == 6


def test_anchors_replace_deck_edge_blocks_in_mirrored_pairs():
    region, placed = box_hull(width=9, height=8, length=40)
    out, report = habits.cleats(placed, region, no_rooms())
    anchors = [p for p in out if p.piece.d == "rope_hook"]
    assert report["anchors"] == len(anchors) == 12 and len(report["stations"]) == 3
    cells = {p.origin for p in anchors}
    assert all((-x, y, z) in cells for x, y, z in cells) and all(y == 7 for _, y, _ in cells)
    assert all(abs(x) == 4 for x, _, _ in cells)                     # at the deck edge
    blocks = {p.origin for p in out if p.piece.d == "01_block"}
    assert not cells & blocks and len(out) == len(placed)            # each took a block's place
    out, _ = habits.railings(placed, region, no_rooms(), [])
    out, _ = habits.cleats(out, region, no_rooms())
    assert all(abs(p.origin[0]) == 3 for p in out if p.piece.d == "rope_hook")   # inboard of the rail
    out, report = habits.cleats(placed, region, no_rooms(), mode="none")
    assert out == placed and report["anchors"] == 0


def test_presets_moor_unless_turned_off():
    parts, info = build(resolve_spec({"smoothing": "wedges"}, "patrol_boat"))
    anchors = [p for p in parts if p.piece.d == "rope_hook"]
    assert len(anchors) == info["mooring"]["anchors"] == 12
    assert sum(p.origin[0] for p in anchors) == 0
    parts, info = build(resolve_spec({"smoothing": "wedges", "mooring": "none"}, "patrol_boat"))
    assert not any(p.piece.d == "rope_hook" for p in parts)
    with pytest.raises(ValueError, match="mooring must be"):
        build(resolve_spec({"mooring": "yes"}, "barge"))
