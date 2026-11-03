"""MCP tool wiring, file safety and overwrite protection."""
import functools
import multiprocessing
import time

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import server
from swhull.build import resolve_spec
from swhull.jobs import run_job
from tool_results import unpack


def call(tool, *args, **kwargs):
    """Run an async tool to completion (the heavy tools run in a worker process)."""
    return anyio.run(functools.partial(tool, *args, **kwargs))


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    vehicles, designs = tmp_path / "vehicles", tmp_path / "designs"
    vehicles.mkdir()
    monkeypatch.setenv("SW_VEHICLES_DIR", str(vehicles))
    monkeypatch.setenv("SW_DESIGNS_DIR", str(designs))
    return vehicles, designs


def test_tools_registered():
    names = {t.name for t in server.mcp._tool_manager.list_tools()}
    assert {"get_guide", "preview_hull", "preview_interior", "save_hull", "inspect_view",
            "open_in_viewer", "preview_game_vehicle", "store_design", "deck_profile",
            "search_parts", "get_part_definition", "import_vehicle", "query_parts", "edit_parts",
            "undo_edits", "preview_vehicle", "save_vehicle", "check_seal",
            "get_part_orientation", "analyze_vehicle", "get_calibration_observations",
            "analyze_hull", "suggest_hull_blocks",
            "analyze_land_vehicle", "list_game_vehicles", "create_vehicle", "query_connections",
            "edit_connections", "route_connections", "preflight_vehicle"} <= names
    assert not names & {"hull_design_guide", "land_vehicle_guide", "search_land_parts", "find_land_vehicles",
                        "create_land_vehicle", "study_references", "score_vehicle"}


def test_every_tool_declares_an_output_schema():
    for tool in server.mcp._tool_manager.list_tools():
        assert tool.output_schema, tool.name


def test_every_tool_documents_its_behaviour_and_parameters():
    """Graded by the Glama tool-definition review (TDQS): agents read only these definitions."""
    for tool in server.mcp._tool_manager.list_tools():
        hints = tool.annotations
        assert hints is not None and hints.read_only_hint is not None, tool.name
        assert hints.destructive_hint is not None and hints.open_world_hint is False, tool.name
        assert len(tool.description) >= 150, tool.name
        for name, schema in tool.parameters["properties"].items():
            assert schema.get("description"), f"{tool.name}.{name} has no description"
        if hints.read_only_hint:
            assert "Read-only" in tool.description or "Nothing is written" in tool.description, tool.name


def test_choices_are_exposed_in_tool_schemas():
    tools = {t.name: t for t in server.mcp._tool_manager.list_tools()}
    assert {"start", "edits", "land", "style_rules", "topics"} <= set(
        tools["get_guide"].parameters["properties"]["topic"]["enum"])
    assert tools["search_parts"].parameters["properties"]["category"]["enum"][0] == ""
    assert set(tools["preflight_vehicle"].parameters["properties"]["style"]["anyOf"][0]["items"]["enum"]) == {
        "boat_engine_room", "bow_tip", "pipe_colours"}
    assert tools["preview_vehicle"].parameters["properties"]["door_state"]["enum"] == ["closed", "open"]


def test_land_instructions_offer_open_door_examples_and_enclosed_wall_crossings():
    assert "create_vehicle" in server.INSTRUCTIONS and "never refused" in server.INSTRUCTIONS
    guide = server.get_guide("land")
    assert "through_blocks" in guide and "humvee_4x4" in guide and "1.25 m" in guide
    route_tool = next(t for t in server.mcp._tool_manager.list_tools() if t.name == "route_connections")
    assert "through_blocks" in route_tool.description and "enclosed" in route_tool.description


@pytest.mark.parametrize("topic", [t for t in server.GUIDE_TOPICS if t != "topics"])
def test_focused_guides_are_available_to_the_model(topic):
    assert server.get_guide(topic).startswith("#")
    assert server.get_guide("hull") == server.GUIDE
    assert server.get_guide().startswith("# Building any Stormworks vehicle")
    assert all(name in server.get_guide("topics") for name in server.GUIDE_TOPICS)
    with pytest.raises(ToolError, match="unknown guide topic"):
        server.get_guide("missing")


def test_runtime_status_explains_missing_game_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(server.definitions, "definitions_dir", lambda: None)
    monkeypatch.setenv("SW_VEHICLES_DIR", str(tmp_path / "vehicles"))
    status = server.get_runtime_status()
    assert status["version"] == server.mcp.version == server.__version__
    assert not status["installed_components_available"]
    assert status["vehicles_dir"] == str(tmp_path / "vehicles")
    assert not (tmp_path / "vehicles").exists()


def test_reference_analysis_supports_multiple_bodies(dirs):
    vehicles, _ = dirs
    xml = ('<vehicle data_version="3"><bodies><body unique_id="1"><components><c><o><vp/></o></c>'
           '</components></body><body unique_id="2"><components><c><o><vp/></o></c></components></body>'
           '</bodies><logic_node_links/></vehicle>')
    path = vehicles / "reference.xml"
    path.write_text(xml, encoding="utf-8")
    report = call(server.analyze_vehicle, "reference")
    assert report["part_count"] == report["body_count"] == 2
    assert path.read_text(encoding="utf-8") == xml
    with pytest.raises(ToolError):
        call(server.analyze_vehicle, "../secret")


def test_hull_analysis_reports_floor_depth_and_original_body_frame(dirs):
    from swhull.pieces import BLOCK, Placed  # noqa: PLC0415
    from swhull.vehicle import to_xml  # noqa: PLC0415
    vehicles, _ = dirs
    path = vehicles / "hull.xml"
    xml = to_xml([Placed(BLOCK, (0, 7, 9)), Placed(BLOCK, (0, 16, 9))])
    path.write_text(xml)
    report = call(server.analyze_hull, name="hull", stations=[9])
    assert report["sections"][0]["gaps"][0]["clear_height_m"] == 2
    assert report["body_id"] == "1"
    assert path.read_text() == xml
    backup_dir = vehicles.parent / "backups" / "vehicles"
    backup_dir.mkdir(parents=True)
    backup = backup_dir / "autosave9.xml"
    backup.write_text(xml)
    backup_report = call(server.analyze_hull, name="autosave9", source="backups", stations=[9])
    assert backup_report["sections"] == report["sections"]
    assert backup.read_text() == xml
    generated = call(server.analyze_hull, preset="rowboat", stations=[8])
    assert "depths" in generated
    assert "build blocks" in generated["frame"]
    with pytest.raises(ToolError, match="choose name"):
        call(server.analyze_hull, name="hull", preset="rowboat")
    with pytest.raises(ToolError):
        call(server.analyze_hull, name="../secret")
    with pytest.raises(ToolError):
        call(server.analyze_hull, name="../secret", source="backups")


def test_preview_returns_image_and_text():
    image, text, _ = unpack(call(server.preview_hull, preset="rowboat"))
    assert image[:8] == b"\x89PNG\r\n\x1a\n"
    assert "Overall:" in text


def test_save_and_overwrite_protection(dirs):
    vehicles, _ = dirs
    call(server.save_hull, "test boat", preset="rowboat")
    assert (vehicles / "test boat.xml").is_file()
    # the Load menu thumbnail the game would otherwise leave blank
    assert (vehicles / "test boat.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert server.list_designs() == ["test boat"]
    with pytest.raises(ToolError, match="overwrite"):
        call(server.save_hull, "test boat", preset="rowboat")
    call(server.save_hull, "test boat", preset="rowboat", overwrite=True)
    (vehicles / "someone else.xml").write_text("<vehicle/>", encoding="utf-8")
    with pytest.raises(ToolError, match="not made by this tool"):
        call(server.save_hull, "someone else", preset="rowboat", overwrite=True)


@pytest.mark.parametrize("name", ["../secret", "..\\secret", "a/b"])
def test_names_cannot_escape_folders(dirs, name):
    with pytest.raises(ToolError):
        call(server.save_hull, name, preset="rowboat")
    with pytest.raises(ToolError):
        call(server.preview_game_vehicle, name)


def test_store_design_and_patch(dirs):
    _, designs = dirs
    server.store_design("draft", preset="tugboat")
    assert (designs / "draft.json").is_file()
    patch = [{"op": "replace", "path": "/superstructure/wheelhouse/height", "value": 3.0}]
    image, text, _ = unpack(call(server.preview_hull, design="draft", patch=patch))
    assert image[:4] == b"\x89PNG" and "Overall:" in text
    server.store_design("draft", design="draft", patch=patch)
    boxes = {b["name"]: b for b in server.load_design("draft")["superstructure"]}
    assert boxes["wheelhouse"]["height"] == 3.0
    assert "deck" in server.deck_profile(design="draft")
    with pytest.raises(ToolError, match="no stored design"):
        call(server.preview_hull, design="missing")


def test_copying_a_design_keeps_its_wires_and_pipes(dirs):
    server.store_design("wired", preset="rowboat")
    record = server._read_design("wired")
    record["connection_edits"] = [{"op": "connect", "from": {"part_id": "a", "port": "0"},
                                   "to": {"part_id": "b", "port": "1"}}]
    record["route_edits"] = [{"from": {"part_id": "a", "surface_index": 1}, "to": {"part_id": "b", "surface_index": 2}}]
    server._atomic_design("wired", record)
    server.store_design("wired copy", design="wired", patch=[{"op": "replace", "path": "/length", "value": 5}])
    server.store_design("wired", design="wired")
    for name in ("wired copy", "wired"):
        copy = server._read_design(name)
        assert copy["connection_edits"] == record["connection_edits"] and copy["route_edits"] == record["route_edits"]


def test_draft_does_not_unlock_foreign_vehicle(dirs):
    vehicles, _ = dirs
    (vehicles / "theirs.xml").write_text("<vehicle/>", encoding="utf-8")
    server.store_design("theirs", preset="rowboat")
    with pytest.raises(ToolError, match="not made by this tool"):
        call(server.save_hull, "theirs", design="theirs", overwrite=True)
    assert (vehicles / "theirs.xml").read_text(encoding="utf-8") == "<vehicle/>"


def test_inspect_highlight():
    image, text, _ = unpack(call(server.inspect_view, preset="tugboat", highlight="wheelhouse", yaw=0, pitch=0))
    assert image[:4] == b"\x89PNG" and "wheelhouse:" in text
    with pytest.raises(ToolError, match="did you mean"):
        call(server.inspect_view, preset="tugboat", highlight="wheel")


def test_spec_path(dirs, tmp_path):
    path = tmp_path / "boat.json"
    path.write_text('{"length": 6.0, "beam": 2.0, "depth": 1.0}', encoding="utf-8")
    server.store_design("from file", spec_path=str(path))
    assert server.load_design("from file")["length"] == 6.0
    with pytest.raises(ToolError, match=".json"):
        server.store_design("bad", spec_path=str(tmp_path / "boat.txt"))


def test_job_deadline_and_cancel_kill_the_worker():
    big = resolve_spec({"length": 60, "beam": 12, "depth": 6, "smoothing": "wedges"})
    with pytest.raises(ValueError, match="gave up"):
        anyio.run(functools.partial(run_job, "preview", big, "x", timeout=1.0))

    async def cancelled():
        with anyio.move_on_after(1.0):
            await run_job("preview", big, "x")
    start = time.monotonic()
    anyio.run(cancelled)
    assert time.monotonic() - start < 10
    assert not multiprocessing.active_children()


def test_edit_preview_commit_undo_and_stale_revision(dirs):
    server.store_design("editable", preset="rowboat")
    query = call(server.query_parts, "editable", limit=1)
    change = [{"op": "paint", "select": {"ids": [query["parts"][0]["id"]]}, "color": "123456"}]
    before = server.load_design("editable")
    image, note, report = unpack(call(server.edit_parts, "editable", change, query["revision"]))
    assert image is None
    assert "Parts: 0 added, 0 removed, 1 changed" in note and "preview=true" in note
    image, _, _ = unpack(call(server.edit_parts, "editable", change, query["revision"], preview=True))
    assert image[:4] == b"\x89PNG"
    assert not report["committed"]
    assert server.load_design("editable") == before
    assert not unpack(call(server.edit_parts, "editable", change))[2]["committed"]   # previews need no revision
    with pytest.raises(ToolError, match="needs the revision"):
        call(server.edit_parts, "editable", change, commit=True)
    report = unpack(call(server.edit_parts, "editable", change, query["revision"], commit=True))[2]
    assert report["committed"]
    with pytest.raises(ToolError, match="stale"):
        call(server.edit_parts, "editable", change, query["revision"], commit=True)
    server.undo_edits("editable", report["revision"])
    assert server.load_design("editable") == before


def test_imported_draft_separate_save(dirs):
    from swhull.pieces import BLOCK, Placed  # noqa: PLC0415
    from swhull.vehicle import to_xml  # noqa: PLC0415
    vehicles, _ = dirs
    text = to_xml([Placed(BLOCK, (0, 0, 0)), Placed(BLOCK, (1, 0, 0))])
    (vehicles / "original.xml").write_text(text, encoding="utf-8")
    call(server.import_vehicle, "original", "imported")
    q = call(server.query_parts, "imported")
    call(server.edit_parts, "imported",
         [{"op": "paint", "select": {"ids": [q["parts"][0]["id"]]}, "color": "123456"}],
         q["revision"], commit=True)
    call(server.save_vehicle, "copy", "imported")
    assert (vehicles / "original.xml").read_text(encoding="utf-8") == text
    assert "123456" in (vehicles / "copy.xml").read_text(encoding="utf-8")
    with pytest.raises(ToolError, match="original"):
        call(server.save_vehicle, "original", "imported", overwrite=True)
    with pytest.raises(ToolError, match="already exists"):
        call(server.import_vehicle, "original", "imported")


def test_imported_newlines_and_undo_preserve_source_bytes(dirs):
    from swhull.pieces import BLOCK, Placed  # noqa: PLC0415
    from swhull.vehicle import to_xml  # noqa: PLC0415
    vehicles, _ = dirs
    source = to_xml([Placed(BLOCK, (0, 0, 0))]).replace("\n", "\r\n").encode()
    (vehicles / "original.xml").write_bytes(source)
    call(server.import_vehicle, "original", "draft")
    q = call(server.query_parts, "draft")
    report = unpack(call(server.edit_parts, "draft",
                         [{"op": "paint", "select": {"ids": [q["parts"][0]["id"]]}, "color": "123456"}],
                         q["revision"], commit=True))[2]
    record = server._read_design("draft")
    assert "source_xml" not in record["history"][0]
    server.undo_edits("draft", report["revision"])
    call(server.save_vehicle, "unchanged copy", "draft")
    assert (vehicles / "unchanged copy.xml").read_bytes() == source
    assert (vehicles / "original.xml").read_bytes() == source


def test_seal_tool_generated_and_imported_seed_requirement(dirs):
    from swhull.pieces import BLOCK, Placed  # noqa: PLC0415
    from swhull.vehicle import to_xml  # noqa: PLC0415
    vehicles, _ = dirs
    server.store_design("closed", preset="barge")
    image, _, report = unpack(call(server.check_seal, "closed"))
    assert image[:4] == b"\x89PNG" and report["status"] == "sealed"
    (vehicles / "plate.xml").write_text(to_xml([Placed(BLOCK, (0, 0, 0))]), encoding="utf-8")
    call(server.import_vehicle, "plate", "imported")
    with pytest.raises(ToolError, match="require explicit"):
        call(server.check_seal, "imported")
    report = unpack(call(server.check_seal, "imported", seeds=[[0, 1, 0]]))[2]
    assert report["status"] == "leaking"


def test_edited_tank_can_preview_but_cannot_save_until_undo(dirs):
    from swhull import definitions  # noqa: PLC0415
    if definitions.load("water_spawner") is None:
        pytest.skip("real-definition integration needs installed fluid parts")
    vehicles, _ = dirs
    server.store_design("tank draft", preset="barge",
                        spec={"tanks": [{"name": "fuel", "position": [-1, .25, 3], "size": [2, 1.5, 2]}]})
    q = call(server.query_parts, "tank draft", select={"bounds": [[-4, 3, 15], [-4, 3, 15]]})
    report = unpack(call(server.edit_parts, "tank draft",
                         [{"op": "remove", "select": {"ids": [q["parts"][0]["id"]]}}],
                         q["revision"], commit=True))[2]
    image, _, _ = unpack(call(server.preview_vehicle, "tank draft"))
    assert image[:4] == b"\x89PNG"
    seal = unpack(call(server.check_seal, "tank draft"))[2]
    assert seal["status"] == "leaking" and seal["tanks"][0]["status"] == "leaking"
    for tool in (server.save_vehicle, server.save_hull):
        with pytest.raises(ToolError, match="cannot export"):
            call(tool, "invalid tank", design="tank draft")
    assert not list(vehicles.iterdir())
    server.undo_edits("tank draft", report["revision"])
    call(server.save_vehicle, "valid tank", "tank draft")
    assert (vehicles / "valid tank.xml").exists()


def test_fast_worker_exit_keeps_result_and_leaves_no_children():
    from swhull.pieces import BLOCK, Placed  # noqa: PLC0415
    from swhull.vehicle import to_xml  # noqa: PLC0415
    text = to_xml([Placed(BLOCK, (0, 0, 0))])
    async def repeated():
        for _ in range(12):
            record, count = await run_job("import_draft", text, "original")
            assert record["source_xml"] == text and count == 1
    anyio.run(repeated)
    assert not multiprocessing.active_children()


def test_empty_draft_builds_anything_and_preflight_takes_optional_style(dirs):
    vehicles, _ = dirs
    image, notes, created = unpack(call(server.create_vehicle, "blank"))
    assert image[:4] == b"\x89PNG" and created["kind"] == "draft" and "Empty draft" in notes
    query = call(server.query_parts, "blank")
    assert [p["definition"] for p in query["parts"]] == ["01_block"]
    add = [{"op": "add", "parts": [{"definition": "01_block", "position": [0, 0, z]} for z in (1, 2)]}]
    report = unpack(call(server.edit_parts, "blank", add, query["revision"], commit=True))[2]
    assert report["committed"] and call(server.query_parts, "blank")["total"] == 3
    preflight = call(server.preflight_vehicle, "blank")
    assert preflight["unchecked"] == [] and "style_checks" not in preflight
    styled = call(server.preflight_vehicle, "blank", style=["bow_tip", "boat_engine_room"])
    assert all(row["severity"] == "warning" for row in styled["style_checks"])
    call(server.save_vehicle, "blank copy", "blank")
    assert (vehicles / "blank copy.xml").is_file()
    with pytest.raises(ToolError, match="only color and bench"):
        call(server.create_vehicle, "blank 2", spec={"length": 3})
