"""Geometry handed to the browser must agree with component placement and PNG previews."""
from swhull import definitions
from swhull.pieces import BLOCK, IDENTITY, Placed, apply, with_mirror
from swhull.vehicle import to_xml
from swhull.viewer import geometry


def test_viewer_does_not_concatenate_bodies_or_controller_internals():
    nested = '<c d="controller"><o><vp x="5"/><group><components><c><o><vp x="99"/></o></c></components></group></o></c>'
    text = ('<vehicle data_version="3"><bodies><body unique_id="1"><components>' + nested +
            '<c><o r="1,0,0,0,1,0,0,0,1"><vp/></o></c></components></body>'
            '<body unique_id="2"><components><c><o><vp x="20"/></o></c></components></body></bodies></vehicle>')
    payload = geometry(text)
    assert len(payload["parts"]) == 2
    assert {tuple(p["origin"]) for p in payload["parts"]} == {(5, 0, 0), (0, 0, 0)}
    assert len(geometry(text, body_id="2")["parts"]) == 1
    assert payload["coverage"]["footprint_fallbacks"] == {"controller": 1}


def test_viewer_transform_retains_mirror_and_block_geometry():
    q = with_mirror(IDENTITY, 1)
    p = Placed(BLOCK, (2, 3, 4), q, "123456")
    data = geometry(to_xml([p]))
    assert data["assets"]["01_block"]["faces"] and not data["assets"]["01_block"]["native"]
    row = data["parts"][0]
    local = (.5, .5, .5)
    world = tuple(sum(row["M"][j * 3 + i] * local[j] for j in range(3)) for i in range(3))
    assert world == apply(q, local) and row["colour"] == "123456"


def test_viewer_unknown_mesh_keeps_full_footprint(tmp_path, monkeypatch):
    (tmp_path / "test.xml").write_text('<definition><voxels><voxel><position/></voxel><voxel><position x="1"/></voxel></voxels></definition>')
    monkeypatch.setattr(definitions, "definitions_dir", lambda: str(tmp_path))
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    try:
        data = geometry(to_xml([Placed(definitions.load("test"), (0, 0, 0))]))
        asset = data["assets"]["test"]
        assert not asset["native"] and max(v[0] for face in asset["faces"] for v in face) == 1.5
        assert data["coverage"]["footprint_fallbacks"] == {"test": 1}
    finally:
        definitions.load.cache_clear()
        definitions.metadata.cache_clear()
