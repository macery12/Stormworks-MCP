"""The update check: version comparison, the GitHub answer, the daily cache and the AI notice."""
import io
import json

import pytest

from swhull import updates


@pytest.fixture(autouse=True)
def isolated_data(monkeypatch, tmp_path):
    monkeypatch.setenv("SW_MCP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("SW_MCP_NO_UPDATE_CHECK", raising=False)


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


def test_github_is_asked_at_most_once_a_day(monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "latest", lambda: calls.append(1) or {"version": "99.0.0", "url": "https://x.test"})
    updates.check(now=1000.0)
    updates.check(now=1000.0 + updates.CHECK_INTERVAL - 1)
    assert len(calls) == 1
    updates.check(now=1000.0 + updates.CHECK_INTERVAL + 1)
    assert len(calls) == 2


def test_notice_only_for_a_newer_release():
    assert updates.notice() is None
    updates.remember({"version": "0.0.1", "url": "https://x.test"})
    assert updates.notice() is None
    updates.remember({"version": "99.0.0", "url": "https://x.test/r"})
    assert "99.0.0" in updates.notice() and "https://x.test/r" in updates.notice()


def test_opt_outs_silence_the_check(monkeypatch, tmp_path):
    updates.remember({"version": "99.0.0", "url": "https://x.test"})
    monkeypatch.setenv("SW_MCP_NO_UPDATE_CHECK", "1")
    assert updates.disabled() and updates.notice() is None
    monkeypatch.delenv("SW_MCP_NO_UPDATE_CHECK")
    # The v0.3 desktop app's "check at startup" checkbox is still honoured.
    legacy = tmp_path / "local" / "stormworks-hull-mcp" / "settings.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"check_updates": False}))
    assert updates.disabled()
