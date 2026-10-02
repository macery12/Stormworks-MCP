"""Reference evidence retains body and controller boundaries and exposes uncertainty."""
import json

import pytest

from swhull import definitions
from swhull.calibration import generate, observations, record_observation
from swhull.components import full_faces
from swhull.reference import audit_file, audit_text


@pytest.fixture
def reference_definitions(tmp_path, monkeypatch):
    (tmp_path / "sensor.xml").write_text(
        '<definition name="Test Sensor" mass="3"><voxels><voxel flags="1">'
        '<physics_shape_rotation/><position/></voxel><voxel flags="4"><position y="1"/></voxel></voxels>'
        '<surfaces><surface orientation="3" shape="1"><position/></surface></surfaces>'
        '<logic_nodes><logic_node label="Signal" type="1"><position/></logic_node></logic_nodes>'
        '<couplings><coupling type="2"><position z="1"/><direction z="1"/></coupling></couplings></definition>', encoding="utf-8")
    monkeypatch.setattr(definitions, "definitions_dir", lambda: str(tmp_path))
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    full_faces.cache_clear()
    yield
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    full_faces.cache_clear()


def vehicle(bodies, links=""):
    return f'<vehicle data_version="3"><bodies>{bodies}</bodies><logic_node_links>{links}</logic_node_links></vehicle>'


def sensor(x=0):
    return f'<c d="sensor"><o r="1,0,0,0,1,0,0,0,1"><vp x="{x}"/></o></c>'


def test_parser_keeps_zero_voxel_and_reordered_children(reference_definitions):
    piece, data = definitions.load("sensor"), definitions.metadata("sensor")
    assert set(piece.footprint) == {(0, 0, 0), (0, 1, 0)}
    assert len(data["logic_nodes"]) == 1
    assert data["logic_nodes"][0]["position"] == (0, 0, 0)
    assert data["couplings"][0]["children"][1] == {"tag": "direction", "attributes": {"z": "1"}}


def test_body_positions_do_not_collide_and_links_stay_ambiguous(reference_definitions):
    text = vehicle(f'<body unique_id="1">{ "<components>" + sensor() + "</components>" }</body>'
                   f'<body unique_id="2"><initial_local_transform 00="1"/><components>{sensor()}</components></body>',
                   '<logic_node_link type="1"><voxel_pos_0/><voxel_pos_1 x="99"/></logic_node_link>')
    report = audit_text(text)
    assert report["part_count"] == 2 and report["body_count"] == 2
    assert all(b["overlap_count"] == 0 for b in report["bodies"])
    first, second = report["links"][0]["endpoints"]
    assert first["status"] == "ambiguous"
    assert {p["body_id"] for p in first["port_candidates"]} == {"1", "2"}
    assert second["status"] == "no_candidate"
    assert report["bodies"][1]["extras"][0]["attributes"]["sw_00"] == "1"


def test_controller_groups_are_not_vehicle_components(reference_definitions):
    nested = ('<c d="sensor"><o r="1,0,0,0,1,0,0,0,1"><vp/><microprocessor_definition name="Example">'
              '<nodes><n id="8"><node label="Configured" type="5" mode="1"><position z="1"/></node></n></nodes>'
              '<group><components><c type="42"><object id="3"><pos/><in1 component_id="4"/></object></c></components>'
              '<groups><group><components><c type="29"><object id="4"><pos/></object></c></components></group></groups>'
              '</group></microprocessor_definition></o></c>')
    report = audit_text(vehicle(f'<body unique_id="5"><components>{nested}</components></body>'))
    assert report["part_count"] == 1
    controller = report["controllers"][0]
    assert controller["group_count"] == 2
    assert controller["internal_component_count"] == 2
    assert controller["internal_input_count"] == 1
    assert report["parts"][0]["samples"][0]["ports"][0]["type"] == 5


def test_unknown_definitions_and_missing_endpoints_are_reported(reference_definitions):
    report = audit_text(vehicle('<body unique_id="1"><components><c d="unknown"><o><vp/></o></c></components></body>',
                               '<logic_node_link><voxel_pos_0/></logic_node_link>'))
    assert report["unknown_definitions"] == {"unknown": 1}
    assert report["parts"][0]["samples"][0]["mounting_contacts"] == []
    assert report["links"][0]["endpoints"][1]["status"] == "missing_position"


def test_audit_is_read_only_and_paginated(reference_definitions, tmp_path):
    path = tmp_path / "reference.xml"
    text = vehicle(f'<body unique_id="1"><components>{sensor()}<c><o><vp x="8"/></o></c></components></body>')
    path.write_text(text, encoding="utf-8")
    result = audit_file(path, "sensor", 0, 1)
    assert len(result["parts"]) == result["total_matching_definitions"] == 1
    assert path.read_text(encoding="utf-8") == text
    assert audit_file(path, section="bodies")["total_matching"] == 1
    with pytest.raises(ValueError, match="section"):
        audit_file(path, section="unknown")


def test_examples_cover_distinct_conditions_before_repeated_instances(reference_definitions):
    third = sensor(6).replace('1,0,0,0,1,0,0,0,1', '0,0,-1,0,1,0,1,0,0')
    text = vehicle(f'<body unique_id="1"><components>{sensor()}{sensor(3)}{third}</components></body>')
    row = audit_text(text, sample_limit=2)["parts"][0]
    assert row["observed_condition_count"] == row["sampled_condition_count"] == 2
    assert row["unsampled_condition_count"] == 0
    assert len(row["samples"]) == 2
    assert audit_text(text, sample_limit=1)["parts"][0]["unsampled_condition_count"] == 1


def test_calibration_has_all_rotations_and_no_overlaps(reference_definitions):
    parts, _, manifest = generate("sensor")
    seen = set()
    for p in parts:
        assert not (set(p.voxels()) & seen)
        seen.update(p.voxels())
    assert len(manifest["cases"]) == 48
    assert len({c["case_id"] for c in manifest["cases"]}) == 48
    assert all(c["status"] == "pending_in_game" for c in manifest["cases"])


def test_observations_cannot_be_assigned_to_changed_or_unknown_cases(reference_definitions, tmp_path):
    _, xml, manifest = generate("sensor")
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    path.with_suffix(".xml").write_bytes(xml.encode())
    case_id = manifest["cases"][0]["case_id"]
    observation = record_observation(path, case_id, "mounting", "fail", "Base floats")
    assert observation["evidence_level"] == "user_reported_in_game"
    assert observation["result"] == "fail"
    assert path.with_suffix(".observations.jsonl").is_file()
    with pytest.raises(ValueError, match="not found"):
        record_observation(path, "unknown", "mounting", "pass")
    path.with_suffix(".xml").write_text(xml + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="XML changed"):
        record_observation(path, case_id, "mounting", "pass")
    path.with_suffix(".xml").write_bytes(xml.encode())
    (tmp_path / "sensor.xml").write_text('<definition mass="999"/>', encoding="utf-8")
    definitions.metadata.cache_clear()
    with pytest.raises(ValueError, match="definition changed"):
        record_observation(path, case_id, "mounting", "pass")


def test_observations_keep_failures_conflicts_and_stale_evidence(reference_definitions, tmp_path):
    _, xml, manifest = generate("sensor")
    path = tmp_path / "calibration-sensor.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    path.with_suffix(".xml").write_bytes(xml.encode())
    case_id = manifest["cases"][0]["case_id"]
    record_observation(path, case_id, "mounting", "fail")
    record_observation(path, case_id, "mounting", "pass", "Retested")
    result = observations("sensor", tmp_path)
    assert result["checks"][0]["result"] == "pass"
    assert result["conflicting_checks"][0]["results"] == ["fail", "pass"]
    path.with_suffix(".xml").write_bytes((xml + " ").encode())
    assert observations("sensor", tmp_path)["stale_observation_count"] == 2
    path.with_suffix(".xml").write_bytes(xml.encode())
    (tmp_path / "sensor.xml").write_text('<definition mass="123"/>', encoding="utf-8")
    definitions.metadata.cache_clear()
    result = observations("sensor", tmp_path)
    assert result["stale_observation_count"] == 2 and result["checks"] == []


@pytest.mark.parametrize("bad", ["../outside", "..\\outside", "a/b"])
def test_observation_paths_cannot_escape(bad, tmp_path):
    with pytest.raises(ValueError):
        observations(bad, tmp_path)
