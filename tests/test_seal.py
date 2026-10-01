import pytest

from swhull import definitions
from swhull.pieces import BLOCK, WEDGE, Piece, Placed, find_rotation
from swhull.seal import Geometry, check


def box(size=5):
    return [Placed(BLOCK, (x, y, z)) for x in range(size) for y in range(size) for z in range(size)
            if x in (0, size - 1) or y in (0, size - 1) or z in (0, size - 1)]


def test_sealed_box_and_missing_block_escape_path():
    parts = box()
    assert check(parts, [[2, 2, 2]])["status"] == "sealed"
    parts = [p for p in parts if p.origin != (2, 2, 0)]
    result = check(parts, [[2, 2, 2]])
    assert result["status"] == "leaking"
    path = result["compartments"][0]["escape_path"]
    assert path[0] == (2, 2, 2)
    assert (2, 2, 0) in path
    assert any(-1 in v or 5 in v for v in path)


def test_connected_seeds_share_compartment():
    result = check(box(), [{"name": "A", "position": [1, 1, 1]}, {"name": "B", "position": [3, 3, 3]}])
    assert all(r["connected"] == ["A", "B"] for r in result["compartments"])


def test_wedge_footprint_is_not_a_solid_block():
    parts = [p for p in box() if p.origin != (2, 2, 0)]
    q = find_rotation([((1, 0, 0), (0, 0, 1)), ((0, 1, 0), (0, 1, 0))])
    parts.append(Placed(WEDGE, (2, 2, 0), q))
    assert check(parts, [[2, 2, 2]])["status"] == "leaking"


def test_complementary_wedge_faces_have_no_air_aperture():
    q = ((1, 0, 0), (0, -1, 0), (0, 0, -1))
    geometry = Geometry([Placed(WEDGE, (0, 0, 0)), Placed(WEDGE, (1, 0, 0), q)], "closed")
    assert not geometry.passable((0, 0, 0), (1, 0, 0))


def test_unknown_definition_cannot_pass(monkeypatch):
    monkeypatch.setattr(definitions, "metadata", lambda _d: None)
    p = Piece("unknown", 6, 0, BLOCK.footprint, BLOCK.verts, BLOCK.faces)
    assert check([*box(), Placed(p, (2, 2, 2))], [[1, 1, 1]])["status"] == "indeterminate"


def test_partial_component_sealing_surfaces_are_not_footprint_blocks(monkeypatch):
    p = Piece("partial_part", 6, 0, BLOCK.footprint, BLOCK.verts, BLOCK.faces)
    monkeypatch.setattr(definitions, "metadata", lambda _d: {"voxels": [], "sealing_surfaces": [
        {"position": (0, 0, 0), "orientation": 2, "shape": 1}]})
    parts = [item for item in box() if item.origin != (2, 2, 0)]
    parts.append(Placed(p, (2, 2, 0)))
    assert check(parts, [[2, 2, 2]])["status"] == "leaking"


def test_door_open_and_closed(monkeypatch):
    p = Piece("door_manual_small", 6, 0, BLOCK.footprint, BLOCK.verts, BLOCK.faces)
    monkeypatch.setattr(definitions, "metadata", lambda _d: {"voxels": [
        {"position": (0, 0, 0), "flags": 4}], "sealing_surfaces": []})
    parts = [item for item in box() if item.origin != (2, 2, 0)]
    parts.append(Placed(p, (2, 2, 0)))
    assert check(parts, [[2, 2, 2]], "closed")["status"] == "sealed"
    assert check(parts, [[2, 2, 2]], "open")["status"] == "leaking"


def test_seed_and_resource_limits():
    with pytest.raises(ValueError, match="solid"):
        check(box(), [[0, 0, 0]])
    with pytest.raises(ValueError, match="door_state"):
        check(box(), [[2, 2, 2]], "invalid")
    assert check(box(), [[2, 2, 2]], max_cells=10)["status"] == "indeterminate"
    assert check(box(), [])["status"] == "indeterminate"


def test_unknown_geometry_on_boundary_prevents_confident_pass(monkeypatch):
    p = Piece("unknown_shape", 6, 0, BLOCK.footprint, BLOCK.verts, BLOCK.faces)
    monkeypatch.setattr(definitions, "metadata", lambda _d: {"voxels": [], "sealing_surfaces": [
        *({"position": (0, 0, 0), "orientation": i, "shape": 1} for i in range(6)),
        {"position": (0, 0, 0), "orientation": 4, "shape": 2}]})
    parts = [item for item in box() if item.origin != (2, 2, 0)] + [Placed(p, (2, 2, 0))]
    assert check(parts, [[2, 2, 2]])["status"] == "indeterminate"
