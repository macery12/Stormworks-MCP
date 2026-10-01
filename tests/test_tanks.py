from itertools import product

import pytest

from swhull import definitions
from swhull.components import full_faces
from swhull.editing import apply_edits, identify
from swhull.pieces import BLOCK, Piece, Placed
from swhull.seal import check
from swhull.tanks import ensure_valid, place, verify
from swhull.vehicle import to_xml


@pytest.fixture
def tank_definitions(monkeypatch):
    footprints = {"water_spawner": [(0, 0, 0), (0, 1, 0)],
                  "fluid_intake": list(product(range(-1, 2), range(2), [0])),
                  "trans_block_straight": [(0, 0, 0)], "relief_valve_gas": [(0, 0, 0)]}
    pieces = {}
    for d, cells in footprints.items():
        verts, faces = definitions._cube_union(cells)
        pieces[d] = Piece(d, 6, 1, tuple(cells), verts, faces)
    def metadata(d):
        if d not in pieces:
            return None
        faces = [{"position": v, "orientation": i, "shape": 1, "trans_type": 0}
                 for v in footprints[d] for i in range(6)]
        return {"attachment_surfaces": faces, "sealing_surfaces": faces,
                "voxels": [{"position": v, "flags": 1} for v in footprints[d]]}
    monkeypatch.setattr(definitions, "load", pieces.get)
    monkeypatch.setattr(definitions, "metadata", metadata)
    full_faces.cache_clear()
    yield
    full_faces.cache_clear()


def floor():
    return identify([Placed(BLOCK, (x, 0, z)) for x in range(-5, 15) for z in range(-5, 15)])


def spec(**over):
    return {"tanks": [{"name": "diesel", "position": [0, .25, 0], "size": [2, 1.5, 2], **over}]}


def test_sealed_custom_tank_marker_ports_and_volume(tank_definitions):
    parts, info = floor(), {"warnings": []}
    place(parts, info, spec())
    verify(parts, info)
    ensure_valid(info)
    assert info["tank_validation"][0]["status"] == "sealed"
    assert info["tanks"][0]["usable_litres"] == (6 * 4 * 6 - 14) * 15.625
    markers = [p for p in parts if p.piece.d == "water_spawner"]
    assert markers[0].settings["fluid_type"] == 1
    assert markers[0].settings["fluid_fill"] == 1
    assert 'fluid_type="1"' in to_xml(parts)
    assert any(p.piece.d == "relief_valve_gas" for p in parts)


def test_tank_leak_blocks_export(tank_definitions):
    parts, info = floor(), {"warnings": []}
    place(parts, info, spec())
    wall = next(p for p in parts if p.name == "diesel wall" and p.origin == (0, 3, 3))
    parts = apply_edits(parts, [{"op": "remove", "select": {"ids": [wall.uid]}}])
    verify(parts, info)
    assert info["tank_validation"][0]["status"] == "leaking"
    with pytest.raises(ValueError, match="cannot export"):
        ensure_valid(info)


def test_containment_detects_leak_into_otherwise_sealed_space():
    outer = [Placed(BLOCK, (x, y, z)) for x in range(9) for y in range(9) for z in range(9)
             if x in (0, 8) or y in (0, 8) or z in (0, 8)]
    inner = [Placed(BLOCK, (x, y, z)) for x in range(2, 7) for y in range(2, 7) for z in range(2, 7)
             if x in (2, 6) or y in (2, 6) or z in (2, 6)]
    parts = outer + [p for p in inner if p.origin != (2, 4, 4)]
    assert check(parts, [[4, 4, 4]])["status"] == "sealed"
    assert check(parts, [[4, 4, 4]], containment=[[3, 3, 3], [5, 5, 5]])["status"] == "leaking"


@pytest.mark.parametrize("over", [{"fill": 2}, {"fluid": "hydrogen"}, {"size": [1, 1, 1]}, {"doors": ["fore"]}])
def test_invalid_tanks_fail(tank_definitions, over):
    with pytest.raises(ValueError):
        place(floor(), {"warnings": []}, spec(**over))


def test_tank_interior_collision_and_unmounted_tank(tank_definitions):
    parts = floor() + [Placed(BLOCK, (2, 3, 3))]
    with pytest.raises(ValueError, match="interior collides"):
        place(parts, {"warnings": []}, spec())
    with pytest.raises(ValueError, match="mounting contact"):
        place(floor(), {"warnings": []}, spec(position=[0, 1, 0]))


def test_fluid_override_and_missing_definitions(tank_definitions, monkeypatch):
    parts, info = floor(), {"warnings": []}
    place(parts, info, spec(fluid="jet_fuel", fill=.5))
    marker = next(p for p in parts if p.piece.d == "water_spawner")
    assert marker.settings["fluid_type"] == 2 and marker.settings["fluid_fill"] == .5
    monkeypatch.setattr(definitions, "load", lambda _d: None)
    with pytest.raises(ValueError, match="require definition"):
        place(floor(), {"warnings": []}, spec())


def test_removed_marker_and_filled_interior_cannot_export(tank_definitions):
    parts, info = floor(), {"warnings": []}
    place(parts, info, spec())
    removed = apply_edits(parts, [{"op": "remove", "select": {"ids": ["tank:diesel:marker"]}}])
    verify(removed, info)
    assert info["tank_validation"][0]["status"] == "indeterminate"
    assert "required fluid kit" in info["tank_validation"][0]["reason"]
    with pytest.raises(ValueError, match="cannot export"):
        ensure_valid(info)
    lo, hi = info["tanks"][0]["bounds"]
    occupied = {v for p in parts for v in p.voxels()}
    parts += [Placed(BLOCK, v) for v in product(*(range(lo[i], hi[i] + 1) for i in range(3)))
              if v not in occupied]
    verify(parts, info)
    assert info["tank_validation"][0]["usable_litres"] == 0
    assert info["tank_validation"][0]["status"] == "indeterminate"


def test_edits_cannot_add_ordinary_access_through_tank_boundary(tank_definitions):
    parts, info = floor(), {"warnings": []}
    place(parts, info, spec())
    wall = next(p for p in parts if p.origin == (0, 3, 3))
    door = Piece("door_manual_small", 6, 1, BLOCK.footprint, BLOCK.verts, BLOCK.faces)
    parts[parts.index(wall)] = Placed(door, wall.origin, uid=wall.uid)
    verify(parts, info)
    assert "prohibited" in info["tank_validation"][0]["reason"]
    with pytest.raises(ValueError, match="cannot export"):
        ensure_valid(info)
