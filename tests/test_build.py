"""Every preset builds into a valid, overlap-free vehicle in both smoothing modes."""
import pytest

from swhull.build import build, resolve_spec
from swhull.hull import Box, game_units
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


def test_superstructure_corner_radius_rounds_footprint_and_scales():
    box = {"name": "wheelhouse", "z": 0, "length": 4, "width": 4, "height": 2,
           "corner_radius": 1, "taper": 0.25}
    square = Box({**box, "corner_radius": 0}, 0)
    rounded = Box(box, 0)
    assert square._solid(7, 0, 0.5)
    assert not rounded._solid(7, 0, 0.5)
    assert rounded._solid(0, 0, 0.5)
    assert rounded._solid(7, 0, 8)
    assert rounded._solid(-7, 0, 8)
    assert rounded._solid(0, 7, 8)
    assert not rounded._solid(7, 7, 0.5)

    spec = resolve_spec({"scale": "1:2", "superstructure": [box]})
    assert game_units(spec)["superstructure"][0]["corner_radius"] == 0.5


def test_superstructure_roof_radius_rounds_upper_edges():
    box = {"name": "wheelhouse", "z": 0, "length": 4, "width": 4, "height": 2,
           "roof_radius": 1}
    square = Box({**box, "roof_radius": 0}, 0)
    rounded = Box(box, 0)
    assert square._solid(6, 7.5, 8)
    assert not rounded._solid(6, 7.5, 8)
    assert rounded._solid(6, 3, 8)
    assert rounded._solid(0, 7.5, 8)
    assert not rounded._solid(0, 7.5, 1)

    spec = resolve_spec({"scale": "1:2", "superstructure": [box]})
    assert game_units(spec)["superstructure"][0]["roof_radius"] == 0.5


def test_superstructure_chamfer_has_a_straight_corner_face():
    box = {"name": "deckhouse", "z": 0, "length": 4, "width": 4, "height": 2}
    rounded = Box({**box, "corner_radius": 1}, 0)
    chamfered = Box({**box, "corner_chamfer": 1}, 0)
    assert rounded._solid(6, 0, 14.5)
    assert not chamfered._solid(6, 0, 14.5)
    assert chamfered._solid(7, 0, 8)
    assert chamfered._solid(-7, 0, 8)
    spec = resolve_spec({"scale": "1:2", "superstructure": [{**box, "corner_chamfer": 1}]})
    assert game_units(spec)["superstructure"][0]["corner_chamfer"] == 0.5


@pytest.mark.parametrize("key,radius", [("corner_radius", -0.25), ("corner_radius", 2.1),
                                        ("corner_chamfer", -0.25), ("corner_chamfer", 2.1),
                                        ("roof_radius", -0.25), ("roof_radius", 2.1)])
def test_invalid_superstructure_radius(key, radius):
    box = {"z": 0, "length": 4, "width": 4, "height": 2,
           key: radius}
    with pytest.raises(ValueError, match=key):
        resolve_spec({"superstructure": [box]})


def test_superstructure_cannot_request_round_and_chamfered_corners():
    with pytest.raises(ValueError, match="choose corner_radius or corner_chamfer"):
        resolve_spec({"superstructure": [{"z": 0, "length": 4, "width": 4, "height": 2,
                                           "corner_radius": 0.5, "corner_chamfer": 0.5}]})


def test_superstructure_waist_inset_returns_to_original_width_and_scales():
    box = {"name": "deckhouse", "z": 0, "length": 5, "width": 4, "height": 1,
           "corner_chamfer": 0.5,
           "waist": {"from": 0, "peak": 0.5, "to": 1, "inset": 0.25}}
    shape = Box(box, 0)
    assert shape._solid(7, 0.5, 10)
    assert not shape._solid(7, 2, 10)
    assert shape._solid(7, 3.5, 10)
    spec = resolve_spec({"scale": "1:2", "superstructure": [box]})
    assert game_units(spec)["superstructure"][0]["waist"] == {
        "from": 0, "peak": 0.25, "to": 0.5, "inset": 0.125}


@pytest.mark.parametrize("waist", [
    {"from": 0, "peak": 0.5, "to": 1},
    {"from": 0.5, "peak": 0.5, "to": 1, "inset": 0.25},
    {"from": 0, "peak": 0.5, "to": 1.5, "inset": 0.25},
    {"from": 0, "peak": 0.5, "to": 1, "inset": -0.25},
])
def test_invalid_superstructure_waist(waist):
    with pytest.raises(ValueError, match="waist"):
        resolve_spec({"superstructure": [{"z": 0, "length": 5, "width": 4,
                                           "height": 1, "waist": waist}]})


def test_chamfer_warns_when_taper_pinches_the_corner():
    shape = Box({"name": "narrow", "z": 0, "length": 5, "width": 3, "height": 2,
                 "taper": 1, "corner_chamfer": 1}, 0)
    assert any("corner_chamfer is wider" in warning for warning in shape.warnings())
