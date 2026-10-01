from types import SimpleNamespace

import pytest

from swhull import definitions
from swhull.components import full_faces, mounted, place
from swhull.build import resolve_spec
from swhull.hull import game_units
from swhull.interior import InteriorPlan, Room
from swhull.pieces import BLOCK, Piece, Placed, apply
from swhull.vehicle import to_xml
from swhull.editing import apply_edits, identify


@pytest.fixture
def component_definitions(monkeypatch):
    pieces = {}
    sizes = {"battery_small": (2, 1, 1), "battery_medium": (3, 2, 2), "battery_large": (7, 5, 5),
             "seat_helm": (3, 7, 5), "seat_compact": (3, 5, 3), "propeller": (1, 3, 1),
             "rudder": (1, 4, 1)}
    def footprint(size):
        return tuple((x, y, z) for x in range(size[0]) for y in range(size[1]) for z in range(size[2]))
    for d, size in sizes.items():
        cells = footprint(size)
        verts, faces = definitions._cube_union(cells)
        pieces[d] = Piece(d, 6, 10, cells, verts, faces)
    def metadata(d):
        if d not in pieces:
            return None
        cells = pieces[d].footprint
        surfaces = [{"position": v, "orientation": i, "shape": 1, "trans_type": 0}
                    for v in cells for i in range(6)]
        return {"attachment_surfaces": surfaces, "sealing_surfaces": surfaces,
                "footprint": cells, "voxels": [{"position": v, "flags": 1, "physics_shape": 0} for v in cells],
                "properties": {}, "directions": {"seat_front": (0, 0, 1), "force_dir": (0, -1, 0)}}
    monkeypatch.setattr(definitions, "load", pieces.get)
    monkeypatch.setattr(definitions, "metadata", metadata)
    full_faces.cache_clear()
    yield pieces
    full_faces.cache_clear()


def cabin(width=25, height=12):
    xs = range(-width // 2, width // 2 + 1)
    solid = {(x, y, z) for x in xs for y in range(height + 2) for z in range(25)}
    shell = {v for v in solid if v[0] in (min(xs), max(xs)) or v[1] in (0, height + 1) or v[2] in (0, 24)}
    parts = [Placed(BLOCK, v) for v in sorted(shell)]
    room = Room("bridge", "bridge", min(xs), max(xs), 1, height, 0, 24, solid - shell)
    info = {"region": {v: "hull" for v in solid}, "interior": InteriorPlan(rooms=[room]),
            "warnings": [], "form": SimpleNamespace(L=25, depth=height)}
    return parts, info


def test_automatic_control_and_largest_fitting_battery(component_definitions):
    parts, info = cabin()
    place(parts, info, {"fitout": {"stage": "core"}})
    assert [p.piece.d for p in parts if p.name] == ["seat_helm", "battery_large"]
    assert len(info["components"]) == 2
    assert not info["warnings"]


@pytest.mark.parametrize("size", ["small", "medium", "large"])
def test_explicit_battery_sizes_and_named_placement(component_definitions, size):
    parts, info = cabin()
    spec = {"components": [{"name": "store", "kind": "battery", "size": size, "position": [-1, 0.25, 2]}]}
    place(parts, info, spec)
    assert parts[-1].piece.d == f"battery_{size}"
    assert parts[-1].origin == (-4, 1, 8)
    assert 'custom_name="store"' in to_xml(parts[-1:])


def test_helm_fallback_and_no_room_skip(component_definitions):
    parts, info = cabin(height=6)
    place(parts, info, {"fitout": {"stage": "core"}})
    # Standing access height is required, so neither control fits a low ceiling.
    assert any("control" in w and "skipped" in w for w in info["warnings"])
    parts, info = cabin()
    component_definitions.pop("seat_helm")
    place(parts, info, {"fitout": {"stage": "core"}})
    assert any(p.piece.d == "seat_compact" for p in parts)


def test_collision_and_missing_mount_are_errors(component_definitions):
    parts, info = cabin()
    with pytest.raises(ValueError, match="collides"):
        place(parts, info, {"components": [{"name": "bad", "kind": "battery", "size": "small",
                                          "position": [0, 0, 2]}]})
    with pytest.raises(ValueError, match="mounting"):
        place(parts, info, {"components": [{"name": "bad", "kind": "battery", "size": "small",
                                          "position": [0, 1, 2]}]})


def test_components_remain_game_sized_under_scale():
    spec = {"scale": 0.25, "length": 48, "beam": 16, "depth": 8,
            "components": [{"name": "battery", "kind": "battery", "position": [1, 1, 2]}]}
    assert game_units(resolve_spec(spec))["components"] == spec["components"]


def test_propeller_direction_and_mirrored_pairs(component_definitions):
    parts = [Placed(BLOCK, (x, y, 0)) for x in range(-8, 9) for y in range(8)]
    info = {"region": {}, "interior": InteriorPlan(), "warnings": [],
            "form": SimpleNamespace(L=40, depth=8)}
    cfg = {"name": "screw", "kind": "propeller", "size": "small",
           "position": [1, 1, -0.25], "mirror_x": True}
    place(parts, info, {"components": [cfg]})
    props = [p for p in parts if p.name]
    assert len(props) == 2
    assert all(apply(p.Q, (0, -1, 0)) == (0, 0, 1) for p in props)
    assert sorted((-x, y, z) for x, y, z in props[0].voxels()) == sorted(props[1].voxels())


def test_repeat_and_invalid_size(component_definitions):
    parts, info = cabin()
    place(parts, info, {"components": [{"name": "stores", "kind": "battery", "size": "small",
                                      "position": [-2, 0.25, 1], "repeat": {"count": 2, "step": [0, 0, 3]}}]})
    assert {p.name for p in parts if p.name} == {"stores_1", "stores_2"}
    with pytest.raises(ValueError, match="size"):
        place(*cabin(), {"components": [{"name": "bad", "kind": "battery", "size": "huge"}]})


def test_edit_batch_checks_final_mount_and_access(component_definitions):
    parts, _ = cabin()
    parts = identify(parts)
    with pytest.raises(ValueError, match="mounting"):
        apply_edits(parts, [{"op": "add", "part": {"definition": "battery_small",
                                                  "position": [0, 4, 8]}}])
    # The support can follow the component in the same atomic batch.
    edited = apply_edits(parts, [
        {"op": "add", "part": {"definition": "propeller", "position": [0, 15, 4]}},
        {"op": "fill", "bounds": [[0, 14, 4], [0, 14, 4]]},
    ])
    assert any(p.piece.d == "propeller" for p in edited)
    with pytest.raises(ValueError, match="finite"):
        place(*cabin(), {"components": [{"name": "bad", "kind": "battery",
                                         "settings": {"fill": float("nan")}}]})


def test_declared_point_mount_does_not_become_sealing_surface(component_definitions, monkeypatch):
    original = definitions.metadata
    def metadata(d):
        data = original(d)
        data["attachment_surfaces"] = [{**s, "shape": 0} for s in data["attachment_surfaces"]]
        data["sealing_surfaces"] = []
        return data
    monkeypatch.setattr(definitions, "metadata", metadata)
    full_faces.cache_clear()
    p = Placed(component_definitions["seat_compact"], (0, 1, 0))
    assert mounted(p, {(0, 0, 0): Placed(BLOCK, (0, 0, 0))})
    assert not full_faces(p.piece.d, p.Q)


def test_automatic_count_finds_distinct_locations(component_definitions):
    parts, info = cabin()
    place(parts, info, {"components": [{"name": "stores", "kind": "battery", "size": "small", "count": 2}]})
    batteries = [p for p in parts if p.piece.d == "battery_small"]
    assert len(batteries) == 2 and batteries[0].origin != batteries[1].origin
    assert {p.name for p in batteries} == {"stores_1", "stores_2"}
