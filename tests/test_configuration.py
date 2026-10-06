"""Engine settings follow the player's crank-only failure and saved correction."""
import copy

import pytest

from swhull import definitions
from swhull.configuration import engine_power
from swhull.editing import VehicleDocument, part
from swhull.networks import preflight
from swhull.part_policy import PREBUILT_ENGINES
from swhull.pieces import BLOCK, ROTATIONS, Placed, r_attr
from swhull.reference import xml_root
from swhull.vehicle import component_xml, to_xml


@pytest.fixture
def engines(tmp_path, monkeypatch):
    for d in PREBUILT_ENGINES:
        (tmp_path / f"{d}.xml").write_text(
            '<definition><voxels><voxel flags="1"><position/></voxel></voxels></definition>')
    monkeypatch.setattr(definitions, "definitions_dir", lambda: str(tmp_path))
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    yield
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()


@pytest.mark.parametrize("d", sorted(PREBUILT_ENGINES))
@pytest.mark.parametrize("q", ROTATIONS)
def test_every_new_prebuilt_engine_exports_full_power_in_every_rotation(engines, d, q):
    # Cover both direct Placed (boat room placeholders) and editable placement
    # (land templates/add/replace). Check the actual vehicle XML, not only state.
    for p in (Placed(definitions.load(d), (0, 0, 0), q),
              part({"definition": d, "position": [0, 0, 0], "rotation": q})):
        o = xml_root(to_xml([p])).find("bodies/body/components/c/o")
        assert o.get("max_force_scale") == "1"
        assert o.get("r") == r_attr(q)
        assert engine_power(p)["power_percent"] == 100
    schema = definitions.metadata(d)["settings"]["max_force_scale"]
    assert schema["default"] == 1 and schema["max"] == 1


def test_explicit_derating_survives_without_mutating_input(engines):
    cfg = {"definition": "engine", "position": [0, 0, 0], "settings": {"max_force_scale": .6}}
    before = copy.deepcopy(cfg)
    p = part(cfg)
    assert cfg == before and p.settings == {"max_force_scale": .6}
    assert 'max_force_scale="0.6"' in component_xml(p)
    assert engine_power(p)["power_percent"] == 60
    assert "max_force_scale" not in component_xml(Placed(BLOCK, (0, 0, 0)))


@pytest.mark.parametrize("value", [True, -1, 1.1, "100%", float("nan"), float("inf")])
def test_new_engine_rejects_bad_power_values(engines, value):
    with pytest.raises(ValueError, match="max_force_scale"):
        part({"definition": "engine", "position": [0, 0, 0], "settings": {"max_force_scale": value}})


@pytest.mark.parametrize("setting,ok,percentage", [
    ("", False, None), (' max_force_scale="0"', False, None),
    (' max_force_scale="garbage"', False, None), (' max_force_scale="nan"', False, None),
    (' max_force_scale="1.5"', False, None), (' max_force_scale="1"', True, 100),
    (' max_force_scale="0.3"', True, 30),
])
def test_imported_missing_or_disabled_engine_is_reported_without_rewriting_it(engines, setting, ok, percentage):
    xml = to_xml([]).replace('<components></components>',
                            '<components><c d="engine"><o r="1,0,0,0,1,0,0,0,1"'
                            + setting + '><vp/></o></c></components>')
    document = VehicleDocument.parse(xml)
    report = preflight({"kind": "imported", "source_xml": xml}, document.parts)
    row = report["configuration_checks"][0]
    assert (row["status"] == "configured") == ok
    assert row["power_percent"] == percentage
    assert any(i["issue"] == "engine power is missing, zero or invalid" for i in report["issues"]) != ok
    assert document.to_xml(document.parts) == xml


def test_explicit_zero_is_visible_to_preflight(engines):
    p = part({"definition": "engine", "position": [0, 0, 0], "settings": {"max_force_scale": 0}})
    assert 'max_force_scale="0"' in component_xml(p)
    assert preflight({}, [p])["configuration_checks"][0]["status"] == "invalid"
