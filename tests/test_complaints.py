"""Issue evidence persists safely and remains retrievable through the MCP tools."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import server
from swhull import complaints


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    path = tmp_path / "complaints"
    monkeypatch.setenv("SW_COMPLAINTS_DIR", str(path))
    return path


def test_mcp_report_preserves_reproduction_evidence_and_markdown(report_dir):
    result = server.complaint(
        "Fin rudder mounted on the wrong side", "Placement used the blade-facing side as the mount.",
        category="placement", severity="high", tool="preview_hull",
        expected="Fixed base against the transom", actual="Blade touches the hull\nError: insufficient clearance",
        steps=["Request a fin rudder", "Preview the propulsion stage"], vehicle="attack boat",
        design="test boat", definition="rudder_surface", suggestion="Respect mount_normal separately from blade_direction",
        context={"arguments": {"fitout": {"stage": "propulsion"}}, "position": [0, 1, -2], "observed": True})
    report = server.get_complaint(result["id"])
    assert report["context"]["arguments"] == {"fitout": {"stage": "propulsion"}}
    assert report["references"] == {"design": "test boat", "vehicle": "attack boat", "definition": "rudder_surface"}
    assert report["actual"].endswith("Error: insufficient clearance")
    assert report["steps"] == ["Request a fin rudder", "Preview the propulsion stage"]
    assert "## Expected behavior" in report["report_markdown"]
    assert Path(result["report_path"]).read_text(encoding="utf-8") == report["report_markdown"]
    assert json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))["id"] == result["id"]
    assert result["saved_locally"] is True
    assert set(p.suffix for p in report_dir.iterdir()) == {".md", ".json"}


def test_minimal_reports_and_concurrent_same_titles_do_not_overwrite(report_dir):
    def submit(_number):
        return complaints.create("Confusing tool result", "The result does not explain how to recover.")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(8)))
    assert len({r["id"] for r in results}) == 8
    assert len(list(report_dir.glob("*.json"))) == len(list(report_dir.glob("*.md"))) == 8
    assert complaints.read(results[0]["id"])["steps"] == []


def test_search_filters_pagination_and_empty_collection(report_dir):
    assert server.list_complaints() == {"complaints": [], "total": 0, "next_offset": None}
    first = server.complaint("Unclear rotation", "Axis terminology is confusing", category="rotation", severity="high")
    second = server.complaint("Slow preview", "Large builds take too long", category="performance", severity="low")
    server.complaint("Second rotation issue", "Incorrect facing", category="rotation", severity="high")
    result = server.list_complaints(category="rotation", severity="high", limit=1)
    assert result["total"] == 2 and result["next_offset"] == 1
    assert len(server.list_complaints(category="rotation", offset=1)["complaints"]) == 1
    assert server.list_complaints(search="AXIS")["complaints"][0]["id"] == first["id"]
    assert server.list_complaints(category="performance")["complaints"][0]["id"] == second["id"]


@pytest.mark.parametrize("arguments", [
    {"title": " "}, {"description": ""}, {"category": "imaginary"}, {"severity": "urgent"},
    {"context": {"error": float("nan")}}, {"context": {"error": {1, 2}}},
    {"context": {"payload": "x" * 65536}}, {"steps": [""]}])
def test_invalid_reports_do_not_leave_files(report_dir, arguments):
    with pytest.raises(ToolError):
        server.complaint(**{"title": "Issue", "description": "Details", **arguments})
    assert not report_dir.exists()


@pytest.mark.parametrize("bad", ["../outside", "..\\outside", "complaint-deadbeef", "/absolute"])
def test_report_ids_cannot_select_arbitrary_files(report_dir, bad):
    with pytest.raises(ToolError, match="invalid complaint id"):
        server.get_complaint(bad)
    with pytest.raises(ToolError, match="no complaint"):
        server.get_complaint("complaint-" + "0" * 32)


def test_failed_markdown_publication_rolls_back_both_files(report_dir, monkeypatch):
    original = complaints.os.replace
    def failing_replace(source, destination):
        if Path(destination).suffix == ".md":
            raise OSError("disk full")
        original(source, destination)
    monkeypatch.setattr(complaints.os, "replace", failing_replace)
    with pytest.raises(ToolError, match="disk full"):
        server.complaint("Issue", "Details")
    assert list(report_dir.iterdir()) == []
