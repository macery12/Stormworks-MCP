"""The desktop app's update check: version comparison, the GitHub answer and the startup setting."""
import io
import json

import pytest

from swhull import updates


@pytest.mark.parametrize("text, parsed", [("v0.3.0", (0, 3, 0)), ("0.3", (0, 3, 0)), ("v1.12.4", (1, 12, 4)),
                                          ("v0.3.0-beta", None), ("latest", None)])
def test_release_versions_parse_like_release_tags(text, parsed):
    assert updates.parse(text) == parsed


def test_only_a_higher_release_is_newer():
    assert updates.newer("v0.3.1", "0.3.0") and updates.newer("v1.0", "0.9.9")
    assert not updates.newer("v0.3.0", "0.3.0") and not updates.newer("v0.2.9", "0.3.0")
    assert not updates.newer("nightly", "0.3.0")


def test_latest_reads_the_tag_and_page_of_the_published_release(monkeypatch):
    seen = {}

    def fake(req, timeout):
        seen["url"], seen["agent"] = req.full_url, req.get_header("User-agent")
        return io.BytesIO(json.dumps({"tag_name": "v0.4", "html_url": "https://example.test/r"}).encode())

    monkeypatch.setattr(updates.urllib.request, "urlopen", fake)
    assert updates.latest() == {"version": "0.4.0", "url": "https://example.test/r"}
    assert seen["url"] == updates.LATEST and seen["agent"].startswith("stormworks-mcp/")


def test_startup_check_setting_is_remembered(tmp_path, monkeypatch):
    monkeypatch.setenv("SW_MCP_RUNTIME_DIR", str(tmp_path / "runtime"))
    assert updates.check_at_startup()
    updates.set_check_at_startup(False)
    assert not updates.check_at_startup()
    assert json.loads((tmp_path / "settings.json").read_text())["check_updates"] is False
    monkeypatch.setenv("SW_MCP_NO_UPDATE_CHECK", "1")
    assert updates.disabled_by_environment()
