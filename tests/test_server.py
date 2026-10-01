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
    assert {"hull_design_guide", "preview_hull", "preview_interior", "save_hull", "inspect_view",
            "open_in_viewer", "preview_game_vehicle", "store_design", "deck_profile"} <= names


def test_preview_returns_image_and_text():
    image, text = call(server.preview_hull, preset="rowboat")
    assert image.data[:8] == b"\x89PNG\r\n\x1a\n"
    assert "Overall:" in text


def test_save_and_overwrite_protection(dirs):
    vehicles, _ = dirs
    call(server.save_hull, "test boat", preset="rowboat")
    assert (vehicles / "test boat.xml").is_file()
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
    image, text = call(server.preview_hull, design="draft", patch=patch)
    assert image.data[:4] == b"\x89PNG" and "Overall:" in text
    server.store_design("draft", design="draft", patch=patch)
    boxes = {b["name"]: b for b in server.load_design("draft")["superstructure"]}
    assert boxes["wheelhouse"]["height"] == 3.0
    assert "deck" in server.deck_profile(design="draft")
    with pytest.raises(ToolError, match="no stored design"):
        call(server.preview_hull, design="missing")


def test_draft_does_not_unlock_foreign_vehicle(dirs):
    vehicles, _ = dirs
    (vehicles / "theirs.xml").write_text("<vehicle/>", encoding="utf-8")
    server.store_design("theirs", preset="rowboat")
    with pytest.raises(ToolError, match="not made by this tool"):
        call(server.save_hull, "theirs", design="theirs", overwrite=True)
    assert (vehicles / "theirs.xml").read_text(encoding="utf-8") == "<vehicle/>"


def test_inspect_highlight():
    image, text = call(server.inspect_view, preset="tugboat", highlight="wheelhouse", yaw=0, pitch=0)
    assert image.data[:4] == b"\x89PNG" and "wheelhouse:" in text
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
    _, _, report = call(server.edit_parts, "editable", change, query["revision"])
    assert not report["committed"]
    assert server.load_design("editable") == before
    _, _, report = call(server.edit_parts, "editable", change, query["revision"], commit=True)
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
