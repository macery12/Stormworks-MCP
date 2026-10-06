"""Synthetic native-mesh fixtures; no installed game mesh bytes are distributed."""
import struct

import pytest

from swhull import definitions, meshes
from swhull.pieces import IDENTITY, Placed, apply, with_mirror
from swhull.render import _newell, _world_faces


def triangle(colour=(255, 125, 0, 255)):
    vertices = [struct.pack("<3f4B3f", *point, *colour, 0, 0, 1)
                for point in ((0, 0, 0), (.25, 0, 0), (0, .25, 0))]
    return b"mesh\x07\x00\x01\x00" + struct.pack("<HI", 3, 19) + b"".join(vertices) + struct.pack("<I3H", 3, 0, 1, 2)


@pytest.fixture
def assets(tmp_path, monkeypatch):
    folder = tmp_path / "rom" / "data" / "definitions"
    folder.mkdir(parents=True)
    mesh_dir = tmp_path / "rom" / "meshes"
    mesh_dir.mkdir()
    (mesh_dir / "body.mesh").write_bytes(triangle())
    (mesh_dir / "rubber_l.mesh").write_bytes(triangle((40, 40, 40, 255)))
    for d, attributes in (("test_part", 'mesh_data_name="meshes/body.mesh"'),
                          ("wheel_advanced_3_sus", 'mesh_data_name="meshes/body.mesh" mesh_0_name="meshes/rubber" wheel_suspension_height="0.5"'),
                          ("seat_racing", 'mesh_data_name="meshes/body.mesh" mesh_0_name="meshes/nonexistent_hat.mesh"'),
                          ("missing_mesh", 'mesh_data_name="meshes/missing.mesh"'),
                          ("outside", 'mesh_data_name="../outside.mesh"')):
        (folder / f"{d}.xml").write_text(f'<definition {attributes}><voxels><voxel><position x="3"/></voxel></voxels></definition>')
    monkeypatch.setattr(definitions, "definitions_dir", lambda: str(folder))
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    meshes._read.cache_clear()
    yield mesh_dir
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    meshes._read.cache_clear()


def test_native_mesh_uses_metres_and_preserves_editor_footprint(assets):
    piece = definitions.load("test_part")
    p = Placed(piece, (2, 3, 4), color="123456")
    assert p.voxels() == [(5, 3, 4)]
    [(pts, normal, rgb)] = meshes.triangles(p)
    assert pts == ((0, 0, 0), (1, 0, 0), (0, 1, 0)) and rgb == (18, 52, 86)
    [(world, colour)] = meshes.world_triangles(p)
    assert world == ((2, 3, 4), (3, 3, 4), (2, 4, 4)) and colour == rgb
    faces = _world_faces([p])
    assert len(faces) == 1 and faces[0][1] == pytest.approx((0, 0, 1))


def test_mirror_preserves_outward_normals_and_fixed_rubber_colour(assets):
    p = Placed(definitions.load("wheel_advanced_3_sus"), (0, 0, 0), with_mirror(IDENTITY, 1), "FF0000")
    local = meshes.triangles(p)
    assert len(local) == 2 and local[1][2] == (40, 40, 40)
    assert local[1][0][0] == (0, 2, 0)  # Neutral dynamic tyre offset, in blocks.
    for pts, _ in meshes.world_triangles(p):
        assert _newell(pts) == pytest.approx(apply(p.Q, (0, 0, 1)))


def test_browser_payload_reuses_native_shape_with_per_instance_paint(assets):
    from swhull.vehicle import to_xml  # noqa: PLC0415
    from swhull.viewer import geometry  # noqa: PLC0415
    piece = definitions.load("test_part")
    data = geometry(to_xml([Placed(piece, (0, 0, 0), color="FF0000"),
                            Placed(piece, (2, 0, 0), color="0000FF")]))
    assert len(data["assets"]) == 1 and data["assets"]["test_part"]["native"]
    [(points, rgb)] = data["assets"]["test_part"]["triangles"]
    assert points == [[0, 0, 0], [1, 0, 0], [0, 1, 0]] and rgb == [255, 125, 0]
    assert [p["colour"] for p in data["parts"]] == ["FF0000", "0000FF"]


def test_asset_fallbacks_are_explicit_and_seat_hats_are_not_components(assets):
    parts = [Placed(definitions.load(d), (0, 0, 0)) for d in ("seat_racing", "missing_mesh", "outside")]
    report = meshes.coverage(parts)
    assert report["native_components"] == {"seat_racing": 1}
    assert report["footprint_fallbacks"] == {"missing_mesh": 1, "outside": 1}
    assert meshes.triangles(parts[1]) is None
    wheel = Placed(definitions.load("wheel_advanced_3_sus"), (0, 0, 0))
    (assets / "rubber_l.mesh").unlink()
    meshes._read.cache_clear()
    assert meshes.triangles(wheel) is None  # Do not claim a wheel render when its tyre is missing.


@pytest.mark.parametrize("data", [b"", b"mesh\x08" + triangle()[5:], triangle()[:-2],
                                  triangle()[:-2] + struct.pack("<H", 5)])
def test_unknown_truncated_and_invalid_meshes_are_rejected(data):
    with pytest.raises(ValueError):
        meshes.decode(data)


def test_nonfinite_mesh_vertex_is_rejected():
    bad = bytearray(triangle())
    struct.pack_into("<f", bad, 14, float("nan"))
    with pytest.raises(ValueError, match="nonfinite"):
        meshes.decode(bad)


@pytest.mark.installed
def test_installed_wheels_seat_tank_engine_and_lights_have_native_meshes():
    names = ["wheel_advanced_3_sus", "seat_saddle", "fluid_tank_small", "engine", "battery_small", "searchlight_small_2"]
    if not definitions.definitions_dir():
        pytest.skip("Stormworks installation unavailable")
    parts = [Placed(definitions.load(d), (0, 0, 0)) for d in names]
    report = meshes.coverage(parts)
    assert not report["footprint_fallbacks"]
    assert set(report["native_components"]) == set(names)
    for p in parts:
        faces = meshes.world_triangles(p)
        assert faces and len(faces) > len(p.piece.faces)


@pytest.mark.installed
def test_installed_hatch_has_frame_and_moving_leaf_with_selected_pose():
    if not definitions.definitions_dir():
        pytest.skip("Stormworks installation unavailable")
    p = Placed(definitions.load("door_manual_small"), (0, 0, 0))
    assets = meshes._assets(p)
    assert len(assets) >= 2
    closed = meshes.triangles(p, "closed")
    opened = meshes.triangles(p, "open")
    assert len(closed) == len(opened) and len(closed) > len(assets[0][0])
    assert closed != opened
    assert not meshes.coverage([p])["omitted_moving_geometry"]
