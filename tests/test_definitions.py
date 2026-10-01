import pytest

from swhull import definitions


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    monkeypatch.setattr(definitions, "definitions_dir", lambda: str(tmp_path))
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    yield tmp_path
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()


def test_float_serialized_grid_voxels_have_correct_footprint(catalogue):
    (catalogue / "synthetic.xml").write_text(
        '<definition name="Synthetic Part" mass="2" 00="1"><surfaces>'
        '<surface orientation="3" shape="1"><position y="2.0"/></surface></surfaces>'
        '<voxels><voxel flags="1"><position x="-1.000000" y="2.0" z="3"/></voxel>'
        '<voxel flags="0"><position x="0" y="2" z="3"/></voxel></voxels></definition>', encoding="utf-8")
    piece = definitions.load("synthetic")
    data = definitions.metadata("synthetic")
    assert piece.footprint == ((-1, 2, 3), (0, 2, 3))
    assert data["footprint"] == list(piece.footprint)
    result = definitions.catalogue("Synthetic Part")
    assert result["parts"][0]["size_blocks"] == [2, 1, 1]
    assert result["parts"][0]["mass"] == 2


def test_non_grid_component_and_missing_definition(catalogue):
    (catalogue / "offgrid.xml").write_text(
        '<definition><voxels><voxel><position x="0.5"/></voxel></voxels></definition>', encoding="utf-8")
    with pytest.raises(ValueError, match="non-grid"):
        definitions.load("offgrid")
    assert definitions.load("../outside") is None
    assert definitions.metadata("no_such_part") is None


def test_builtin_details_work_without_game(catalogue):
    data = definitions.metadata("01_block")
    assert data["footprint"] == [(0, 0, 0)] and len(data["sealing_surfaces"]) == 6
