"""Fault-to-repair acceptance tests plus revision, schema and evidence safety."""
import copy
import functools
import json

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import TypeAdapter, ValidationError

import server
from swhull import definitions
from swhull.assemblies import assemble
from swhull.configuration import configure, settings_of
from swhull.diagnostic_view import overlay, preview
from swhull.repairs import plan, repair
from swhull.drafts import edited, export, materialize
from swhull.editing import VehicleDocument
from swhull.networks import edited as wire_edit, ports, preflight, template_wires, wires
from swhull.pieces import BLOCK, Piece, Placed
from swhull.vehicle import to_xml
from swhull.tool_schemas import ConnectionBatch, EditBatch, PreflightReport, RouteBatch, plain
from swhull.validation import CHECKS, record_results, sha


def call(fn, *args, **kwargs):
    return anyio.run(functools.partial(fn, *args, **kwargs))


@pytest.fixture
def humvee():
    if not definitions.definitions_dir():
        pytest.skip("installed land components required")
    record = {"kind": "land", "spec": {"preset": "humvee_4x4", "bench": "S"}, "generation": 0}
    parts, _ = materialize(record)
    record["base_connections"] = template_wires(record, parts)
    assert not preflight(record, parts)["findings"]
    return record


def fault(record, kind):
    parts, _ = materialize(record)
    if kind == "fuel":
        pipe = next(p for p in parts if p.name == "fuel line")
        return edited(record, [{"op": "remove", "select": {"ids": [pipe.uid]}}])
    driver = next(p for p in parts if p.name == "driver")
    target = next(p for p in parts if p.name == ("diesel engine" if kind == "starter" else "front left wheel"))
    label = "Starter" if kind == "starter" else "Steering"
    port = next(n for n in ports(target) if n["label"] == label)
    link = next(link for link in wires(record, parts) if link.get("to") == {"part_id": target.uid, "port": port["index"]})
    ops = [{"op": "disconnect", "link_id": link["link_id"]}]
    if kind == "steering":
        source = next(n for n in ports(driver) if n["label"].startswith("Axis 1"))
        ops.append({"op": "connect", "from": {"part_id": driver.uid, "port": source["index"]}, "to": link["to"]})
    return wire_edit(record, ops, parts)


@pytest.mark.installed
@pytest.mark.parametrize("kind", ["fuel", "starter", "steering"])
def test_deliberate_fault_has_previewable_repair_and_clean_export(humvee, kind):
    broken = fault(humvee, kind)
    snapshot = copy.deepcopy(broken)
    proposal = plan(broken)
    available = [f for f in proposal["findings"] if f["repair_status"] == "available"]
    assert available, proposal
    fixed, report = repair(broken, proposal["plan_id"], [available[0]["finding_id"]])
    assert broken == snapshot
    assert not report["after"]["findings"]
    png, data = preview(broken, kind, fixed)
    assert png.startswith(b"\x89PNG") and data["overlay"]["markers"]
    assert any(s["kind"] == "proposed" for s in data["overlay"]["segments"]) or any(
        m["kind"] == "proposed" for m in data["overlay"]["markers"])
    xml, _, _ = export(fixed)
    assert VehicleDocument.parse(xml).parts
    with pytest.raises(ValueError, match="stale repair plan"):
        repair({**broken, "generation": 99}, proposal["plan_id"], [available[0]["finding_id"]])
    with pytest.raises(ValueError, match="distinct"):
        repair(broken, proposal["plan_id"], [available[0]["finding_id"]] * 2)


@pytest.mark.parametrize("contract,value", [
    (EditBatch, [{"op": "move", "select": {"ids": ["a"]}}]),
    (EditBatch, [{"op": "repeat", "select": {"ids": ["a"]}, "delta": [0, 0, 0], "count": 0}]),
    (EditBatch, [{"op": "add", "part": {"position": [0.5, 0, 0]}}]),
    (EditBatch, [{"op": "paint", "select": {"ids": ["a"]}, "color": "red"}]),
    (ConnectionBatch, [{"op": "connect", "from": {"part_id": "a", "port": True}, "to": {"part_id": "b", "port": 0}}]),
    (ConnectionBatch, [{"op": "disconnect", "link_id": "a", "ignored": 1}]),
    (RouteBatch, [{"from": {"part_id": "a", "surface_index": 0}, "to": {"part_id": "b", "surface_index": 0}, "pipe_style": "guess"}]),
    (RouteBatch, []),
])
def test_nested_contracts_reject_malformed_calls(contract, value):
    with pytest.raises(ValidationError):
        plain(value, contract)


def test_schema_requires_operation_specific_fields_and_publishes_results():
    tools = {t.name: t for t in server.mcp._tool_manager.list_tools()}
    for name in ("edit_parts", "edit_connections", "route_connections"):
        assert "$defs" in tools[name].parameters
    assert "delta" in tools["edit_parts"].parameters["$defs"]["Translate"]["required"]
    assert tools["edit_connections"].parameters["$defs"]["WireEndpoint"]["properties"]["port"]["minimum"] == 0
    for name in ("preflight_vehicle", "plan_vehicle_repairs", "repair_vehicle", "apply_vehicle_assembly", "preview_vehicle_diagnostics", "prepare_vehicle_validation"):
        assert tools[name].output_schema["type"] == "object"


def test_configure_preserves_protected_import_structure_and_rejects_geometry():
    xml = ('<vehicle data_version="3"><bodies><body unique_id="1"><components>'
           '<c d="engine"><o r="1,0,0,0,1,0,0,0,1" max_force_scale="0" mystery="abc"><vp/>'
           '<extra value="same"/></o></c></components></body></bodies><logic_node_links/></vehicle>')
    raw = xml.split("<components>", 1)[1].split("</components>", 1)[0]
    p = Placed(Piece("engine", 6, 1, BLOCK.footprint, BLOCK.verts, BLOCK.faces), (0, 0, 0),
               raw_xml=raw, protected=True)
    before = p.raw_xml
    configure(p, {"max_force_scale": 1})
    assert p.raw_xml == before.replace('max_force_scale="0"', 'max_force_scale="1"')
    assert settings_of(p)["max_force_scale"] == "1"
    with pytest.raises(ValueError, match="supports only"):
        configure(p, {"r": "bad"})
    with pytest.raises(ValueError):
        configure(p, {"max_force_scale": float("nan")})


def test_synthetic_starter_repair_without_game_install(monkeypatch):
    data = {
        "engine": {"logic_nodes": [{"index": 0, "label": "Starter", "mode": 1, "type": 0, "position": (0, 0, 0)}]},
        "seat_racing": {"logic_nodes": [
            {"index": 0, "label": "Hotkey 1", "mode": 0, "type": 0, "position": (0, 0, 0)},
            {"index": 1, "label": "Axis 1", "mode": 0, "type": 1, "position": (0, 0, 0)}]},
    }
    for definition in data.values():
        definition.update(directions={"seat_front": (0, 0, 1)}, attachment_surfaces=[], settings={},
                          properties={}, footprint=[(0, 0, 0)], voxels=[])
    monkeypatch.setattr(definitions, "metadata", data.get)
    monkeypatch.setattr(definitions, "load", lambda d: Piece(d, 6, 1, BLOCK.footprint, BLOCK.verts, BLOCK.faces) if d in data else None)
    parts = [Placed(definitions.load("engine"), (3, 0, 0)), Placed(definitions.load("seat_racing"), (0, 0, 0), name="driver")]
    record = {"kind": "imported", "source_xml": to_xml(parts)}
    proposal = plan(record)
    available = [f for f in proposal["findings"] if f["repair_status"] == "available"]
    assert len(available) == 1
    fixed, result = repair(record, proposal["plan_id"], [available[0]["finding_id"]])
    assert len(result["resolved_finding_ids"]) == 1 and result["remaining_finding_ids"]
    assert "connection_edits" not in record and wires(fixed, materialize(fixed)[0])


@pytest.mark.installed
def test_repair_mcp_preview_commit_stale_and_undo(humvee, tmp_path, monkeypatch):
    monkeypatch.setenv("SW_DESIGNS_DIR", str(tmp_path))
    broken = fault(humvee, "starter")
    server._atomic_design("broken", broken)
    p = call(server.plan_vehicle_repairs, "broken")
    ids = [f["finding_id"] for f in p["findings"] if f["repair_status"] == "available"]
    previewed = call(server.repair_vehicle, "broken", p["revision"], p["plan_id"], ids)
    assert previewed.content[0].type == "image" and not previewed.structured_content["committed"]
    assert server._read_design("broken") == broken
    result = call(server.repair_vehicle, "broken", p["revision"], p["plan_id"], ids, commit=True)
    report = result.structured_content
    tool = next(t for t in server.mcp._tool_manager.list_tools() if t.name == "repair_vehicle")
    assert tool.fn_metadata.convert_result(result).structured_content == report
    TypeAdapter(PreflightReport).validate_python(report["after"])
    assert report["committed"] and not call(server.preflight_vehicle, "broken")["findings"]
    with pytest.raises(ToolError, match="stale"):
        call(server.repair_vehicle, "broken", p["revision"], p["plan_id"], ids, commit=True)
    server.undo_edits("broken", report["revision"])
    assert call(server.preflight_vehicle, "broken")["findings"]


@pytest.mark.installed
def test_assemblies_work_on_explicit_bindings(humvee):
    parts, _ = materialize(humvee)
    ids = {p.name: p.uid for p in parts}
    # Import a synthetic control bench with a separate gate to avoid changing shared preset logic.
    gate = Placed(definitions.load("gate_function_small"), (20, 0, 0), uid="clutch gate")
    parts.extend([gate, Placed(BLOCK, (20, -1, 0))])
    from swhull.networks import write_xml  # noqa: PLC0415
    source = write_xml(to_xml(parts), humvee, parts)
    bench = {"kind": "imported", "source_xml": source}
    imported, _ = materialize(bench)
    mapped = {p.uid: imported[i].uid for i, p in enumerate(parts)}
    proposed, report = assemble(bench, "clutch_engagement", {"driver": mapped[ids["driver"]], "clutch": mapped[ids["clutch"]],
                                                          "clutch_gate": mapped["clutch gate"]})
    assert report["operations"]["edits"]
    assert bench != proposed and not preflight(proposed, materialize(proposed)[0])["findings"]
    idle, idle_report = assemble(proposed, "engine_start_idle", {"driver": mapped[ids["driver"]], "engine": mapped[ids["diesel engine"]],
                                                              "throttle_gate": mapped[ids["throttle limiter"]]}, {"idle_throttle": .12})
    assert idle_report["operations"]["edits"][0]["settings"]["property_text"] == "max(0.12,min(1,x))"
    assert not preflight(idle, materialize(idle)[0])["findings"]
    with pytest.raises(ValueError, match="another subsystem"):
        assemble(humvee, "engine_start_idle", {"driver": ids["driver"], "engine": ids["diesel engine"],
                                              "throttle_gate": ids["throttle limiter"]})
    for assembly, roles in (("brake_reverse", {"driver": ids["driver"], "gearbox": ids["gearbox"],
                                             "wheels": [ids[name] for name in ids if name.endswith("wheel") and "spare" not in name]}),
                            ("lighting", {"driver": ids["driver"], "battery": ids["starter battery"],
                                          "lights": [ids[name] for name in ids if "headlight" in name or "tail light" in name]})):
        current, _ = assemble(humvee, assembly, roles)
        assert not preflight(current, materialize(current)[0])["findings"]
    with pytest.raises(ValueError, match="distinct"):
        assemble(humvee, "engine_start_idle", {"driver": ids["driver"], "engine": ids["driver"], "throttle_gate": ids["throttle limiter"]})


def test_validation_requires_all_seven_observations_and_keeps_pending_evidence():
    manifest = {"checks": [{"check": key, "result": "pending", "instruction": value} for key, value in CHECKS.items()]}
    result = record_results(manifest, [{"check": "starting", "result": "pass", "evidence": "Observed stable 7 RPS"}], "test-version", "player")
    assert result["status"] == "incomplete" and manifest["checks"][0]["result"] == "pending"
    observations = [{"check": key, "result": "pass", "evidence": "Test fixture observation"} for key in CHECKS]
    assert record_results(manifest, observations, "test-version", "player")["status"] == "passed"
    observations[0]["result"] = "fail"
    assert record_results(manifest, observations, "test-version", "player")["status"] == "failed"
    with pytest.raises(ValueError):
        record_results(manifest, [observations[0]] * 2, "test-version", "player")
    with pytest.raises(ValueError, match="observation"):
        record_results(manifest, [{"check": "starting", "result": "pass", "evidence": " "}], "test-version", "player")
    with pytest.raises(ValueError, match="game version changed"):
        record_results(result, observations, "different-version", "player")


def test_validation_mcp_detects_modified_export(tmp_path, monkeypatch):
    monkeypatch.setenv("SW_DESIGNS_DIR", str(tmp_path / "designs"))
    monkeypatch.setenv("SW_VEHICLES_DIR", str(tmp_path / "vehicles"))
    server.store_design("draft", preset="rowboat")
    run = call(server.prepare_vehicle_validation, "test copy", "draft")
    path = tmp_path / "vehicles" / "test copy.xml"
    assert run["export_sha256"] == sha(path.read_bytes()) and run["status"] == "pending"
    assert server.get_vehicle_validation(run["run_id"])["export_matches"]
    observations = [{"check": "starting", "result": "skipped", "evidence": "Unit test, game unavailable"}]
    result = server.record_vehicle_validation(run["run_id"], run["export_sha256"], observations, "fixture", "tests")
    assert result["status"] == "incomplete"
    path.write_text("changed")
    assert not server.get_vehicle_validation(run["run_id"])["export_matches"]
    with pytest.raises(ToolError, match="export changed"):
        server.record_vehicle_validation(run["run_id"], run["export_sha256"], observations, "fixture", "tests")
    assert json.loads(server._validation_path(run["run_id"]).read_text())["status"] == "incomplete"


@pytest.mark.installed
def test_overlay_does_not_change_geometry_and_uses_draft_coordinates(humvee):
    broken = fault(humvee, "steering")
    parts, _ = materialize(broken)
    before = [(p.origin, p.color, p.Q) for p in parts]
    data = overlay(broken, parts)
    assert data["segments"] and data["markers"]
    assert before == [(p.origin, p.color, p.Q) for p in parts]
