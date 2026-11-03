"""Optional style rule sets warn only when asked, and never refuse a design."""
from itertools import product

import pytest

from swhull import definitions, style
from swhull.pieces import BLOCK, Piece, Placed


def fake(d):
    """A one-cell stand-in for an installed part; the checks only read its id and voxels."""
    return Piece(d, 6, 1.0, ((0, 0, 0),), BLOCK.verts, BLOCK.faces)


def box(x=(-2, 2), y=(0, 4), z=(0, 8), deck=True):
    """A hollow hull: walls, bottom and (optionally) a deck at the top layer."""
    cells = []
    for v in product(range(x[0], x[1] + 1), range(y[0], y[1] + 1), range(z[0], z[1] + 1)):
        if v[0] in x or v[2] in z or v[1] == y[0] or (deck and v[1] == y[1]):
            cells.append(Placed(BLOCK, v, uid=f"b{len(cells)}"))
    return cells


def test_engine_room_rule_wants_engines_enclosed_and_machinery_inside_the_transom():
    hull = box()
    engine = Placed(fake("engine"), (0, 2, 4), uid="engine", name="main")
    assert style.check(hull + [engine], ["boat_engine_room"]) == []
    open_top = [p for p in hull if p.origin[1] != 4]
    rows = style.check(open_top + [engine], ["boat_engine_room"])
    assert len(rows) == 1 and rows[0]["part_id"] == "engine" and rows[0]["severity"] == "warning"
    assert "open toward (0, 1, 0)" in rows[0]["message"]
    prop = Placed(fake("propeller"), (0, 1, -3), uid="prop")
    rudder = Placed(fake("rudder"), (0, 0, -1), uid="rudder")
    rows = style.check(hull + [prop, rudder], ["boat_engine_room"])
    assert {r["part_id"] for r in rows} == {"prop", "rudder"}


def test_bow_tip_rule_flags_one_wide_stems_and_lonely_pieces_of_a_symmetric_hull():
    hull = [Placed(BLOCK, v, uid=f"b{i}") for i, v in enumerate(product(range(-1, 2), range(3), range(10)))]
    assert style.check(hull, ["bow_tip"]) == []
    stub = hull + [Placed(BLOCK, (0, 1, 10), uid="stub")]
    rows = style.check(stub, ["bow_tip"])
    assert any("one block wide at y=1" in r["message"] for r in rows)
    lonely = [p for p in hull if p.origin != (1, 2, 5)]
    rows = style.check(lonely, ["bow_tip"])
    partner = next(p.uid for p in hull if p.origin == (-1, 2, 5))
    assert rows and rows[0]["part_ids"] == [partner] and "mirror-image" in rows[0]["message"]
    # An asymmetric design is the player's choice: the mirror habit does not apply.
    skewed = hull + [Placed(BLOCK, (2 + i % 3, 0, i // 3), uid=f"s{i}") for i in range(30)]
    assert not any("mirror-image" in r["message"] for r in style.check(skewed, ["bow_tip"]))


def test_unknown_rule_sets_are_rejected_and_none_are_checked_by_default():
    with pytest.raises(ValueError, match="unknown style rule set"):
        style.check([], ["tidy"])
    assert style.check(box(), []) == []


@pytest.mark.skipif(not definitions.definitions_dir(), reason="installed parts required")
def test_pipe_colour_rule_flags_repainted_exposed_pipes():
    from swhull.drafts import materialize  # noqa: PLC0415
    parts, _ = materialize({"kind": "land", "spec": {"preset": "humvee_4x4", "bench": "S"}})
    before = style.check(parts, ["pipe_colours"])
    for p in parts:
        if p.piece.d.startswith("trans_") and not p.piece.d.startswith("trans_block_"):
            p.color = "FF00FF"
    after = style.check(parts, ["pipe_colours"])
    assert len(after) > len(before) and all(r["rule_set"] == "pipe_colours" for r in after)


def test_fluid_spawner_without_a_fluid_type_holds_diesel():
    assert definitions.spawner_fluid({}) == 1
    assert definitions.spawner_fluid({"fluid_type": "0"}) == 0
    assert definitions.spawner_fluid({"fluid_type": "junk"}) == 1


def test_preflight_lists_unchecked_systems_instead_of_faulting_them():
    from swhull.networks import unchecked_parts  # noqa: PLC0415
    parts = [Placed(fake("modular_engine_crankshaft"), (0, 0, 0)), Placed(fake("modular_engine_piston_3x3"), (1, 0, 0)),
             Placed(fake("jet_engine_compressor"), (2, 0, 0)), Placed(fake("modular_engine_gearbox_1x1"), (3, 0, 0)),
             Placed(BLOCK, (4, 0, 0))]
    rows = unchecked_parts(parts)
    assert [(r["definition"], r["system"]) for r in rows] == [
        ("jet_engine_compressor", "jet engine"), ("modular_engine_crankshaft", "modular engine"),
        ("modular_engine_piston_3x3", "modular engine")]
