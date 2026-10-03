"""Every preset builds into a valid, overlap-free vehicle in both smoothing modes."""
import pytest

from swhull.build import build, resolve_spec
from swhull.presets import PRESETS
from swhull.vehicle import read_components, to_xml


def _check(placed, tmp_path):
    seen = set()
    for p in placed:
        for v in p.voxels():
            assert v not in seen, f"two parts share voxel {v}"
            seen.add(v)
    path = tmp_path / "v.xml"
    path.write_text(to_xml(placed), encoding="utf-8")
    back = list(read_components(path))
    assert [(d, o, Q) for d, o, Q, _ in back] == [(p.piece.d, p.origin, p.Q) for p in placed]


@pytest.mark.parametrize("preset", list(PRESETS))
def test_preset_blocks(preset, tmp_path):
    placed, _ = build(resolve_spec(preset=preset))
    assert {p.piece.d for p in placed} <= {"01_block", "engine", "aircraft_engine", "engine_diesel"}
    _check(placed, tmp_path)


@pytest.mark.parametrize("preset", ["runabout", "tugboat", "patrol_boat"])
def test_preset_wedges(preset, tmp_path):
    placed, _ = build(resolve_spec({"smoothing": "wedges"}, preset=preset))
    assert any(p.piece.d != "01_block" for p in placed)
    _check(placed, tmp_path)


@pytest.mark.parametrize("bad", [{"length": 500}, {"smoothing": "round"}, {"deck": "half"},
                                 {"hulls": 2, "hull_spacing": 0.5},
                                 {"interior": {"rooms": [{"name": "x"}]}}])
def test_invalid_specs_are_rejected(bad):
    with pytest.raises(ValueError):
        resolve_spec(bad)


def test_unknown_preset():
    with pytest.raises(ValueError, match="unknown preset"):
        resolve_spec(preset="submarine")


@pytest.mark.parametrize("bad,message", [
    ({"lenght": 8}, "did you mean 'length'"),
    ({"bow": {"fulness": 2}}, "did you mean 'fullness'"),
    ({"section": []}, "section must be an object"),
    ({"superstructure": {}}, "superstructure must be a list of objects"),
    ({"interior": {"rooms": ["bridge"]}}, "interior.rooms must be a list of objects"),
    ({"interior": {"hatches": [1]}}, "interior.hatches must be a list of objects"),
    ({"interior": {"decks": 2}}, "interior.decks must be a list of numbers"),
    ({"bow": {"flare": float("nan")}}, "spec.bow.flare must be finite"),
    ({"scale": "fit", "bench": "S", "length": float("inf")}, "spec.length must be finite"),
    ([], "spec must be a JSON object"),
])
def test_bad_shape_parameters_produce_actionable_errors(bad, message):
    with pytest.raises(ValueError, match=message):
        resolve_spec(bad)


def test_misspelled_patch_cannot_silently_leave_design_unchanged():
    with pytest.raises(ValueError, match="unknown field spec.lenght"):
        resolve_spec(patch=[{"op": "replace", "path": "/lenght", "value": 8}])
