import copy
from itertools import product
from types import SimpleNamespace

import pytest

from swhull import definitions
from swhull.access import install_door, install_hatch
from swhull.components import full_faces
from swhull.interior import InteriorPlan
from swhull.pieces import Piece


@pytest.fixture
def access_definitions(monkeypatch):
    footprints = {"door_manual": list(product(range(-3, 3), range(-3, 4), [0])),
                  "door_manual_small": list(product(range(-1, 2), range(-2, 2), [0])),
                  "ladder_small": list(product(range(-1, 2), range(4), [0]))}
    pieces = {}
    for d, cells in footprints.items():
        verts, faces = definitions._cube_union(cells)
        pieces[d] = Piece(d, 6, 10, tuple(cells), verts, faces)
    def metadata(d):
        if d not in pieces:
            return None
        faces = [{"position": v, "orientation": i, "shape": 1, "trans_type": 0}
                 for v in footprints[d] for i in range(6)]
        return {"directions": {"door_normal": (0, 0, 1), "door_up": (0, 1, 0)},
                "attachment_surfaces": faces, "sealing_surfaces": faces}
    monkeypatch.setattr(definitions, "load", pieces.get)
    monkeypatch.setattr(definitions, "metadata", metadata)
    full_faces.cache_clear()
    yield
    full_faces.cache_clear()


def two_decks():
    solid = set(product(range(-6, 7), range(20), range(17)))
    skin = {v for v in solid if v[0] in (-6, 6) or v[1] in (0, 19) or v[2] in (0, 16)}
    plan = InteriorPlan(blocks={v: "8A8F96" for v in solid - skin if v[1] == 9})
    region = {v: "hull" for v in solid}
    return plan, skin, region


def test_complete_access_before_carving(access_definitions):
    plan, skin, region = two_decks()
    ok, reason = install_hatch({"name": "stairs", "floor": 2.5, "z": 2}, {}, skin, region,
                               lambda _x, _z: 19, plan)
    assert ok, reason
    assert len(plan.components) == 3
    assert plan.components[0].piece.d == "door_manual_small"
    assert all(p.piece.d == "ladder_small" for p in plan.components[1:])
    assert (0, 9, 8) not in plan.blocks
    assert (0, 1, 6) in plan.blocks  # ladder has a continuous mounting wall
    assert (0, 1, 8) in plan.reserved and (0, 10, 11) in plan.reserved


def test_failed_access_preserves_floor(access_definitions):
    plan, skin, region = two_decks()
    plan.blocks[(0, 3, 7)] = "123456"
    before = copy.deepcopy(plan)
    ok, _ = install_hatch({"floor": 2.5, "z": 2}, {}, skin, region, lambda _x, _z: 19, plan)
    assert not ok
    assert plan == before


def test_missing_definitions_and_invalid_floor_leave_sealed(monkeypatch):
    monkeypatch.setattr(definitions, "load", lambda _d: None)
    plan, skin, region = two_decks()
    before = copy.deepcopy(plan)
    assert not install_hatch({"z": 2, "deck": 99}, {}, skin, region, lambda _x, _z: None, plan)[0]
    assert plan == before


def test_climbing_obstruction_with_explicit_bottom_leaves_sealed(access_definitions):
    plan, skin, region = two_decks()
    plan.blocks[(0, 4, 8)] = "123456"
    before = copy.deepcopy(plan)
    ok, reason = install_hatch({"floor": 2.5, "bottom": .25, "z": 2}, {}, skin, region,
                               lambda _x, _z: 19, plan)
    assert not ok and "climbing space" in reason
    assert plan == before


def test_manual_door_frame_and_failed_fit_leave_wall(access_definitions):
    wall = set(product(range(-5, 6), range(10), [0]))
    plan = InteriorPlan()
    room = SimpleNamespace(name="room")
    ok, reason = install_door(room, "fore", (0, 0, 1), (0, 1, 0), wall, plan)
    assert ok, reason
    assert len(plan.carve) == 42 and plan.components[0].piece.d == "door_manual"
    plan = InteriorPlan()
    before = copy.deepcopy(plan)
    ok, _ = install_door(room, "fore", (0, 0, 1), (0, 6, 0), wall, plan)
    assert not ok and plan == before


def test_complete_frame_cannot_cut_underwater_skin(access_definitions):
    plan, skin, region = two_decks()
    before = copy.deepcopy(plan)
    assert not install_hatch({"floor": .25, "z": 2, "bottom": -2}, {}, skin, region,
                             lambda _x, _z: 19, plan)[0]
    assert plan == before
    wall = set(product(range(-5, 6), range(10), [0]))
    ok, reason = install_door(SimpleNamespace(name="room"), "fore", (0, 0, 1), (0, 1, 0),
                             wall, plan, lambda _x, _z: 6)
    assert not ok and "below the main deck" in reason and plan == before
