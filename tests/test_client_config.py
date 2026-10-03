import json
from pathlib import Path

import pytest
import tomlkit

from swhull import client_config

ENTRY = {"command": "C:\\Users\\Boat Builder\\Stormworks MCP\\stormworks-mcp.exe", "args": []}


def test_claude_add_preserves_other_servers_and_exact_backup(tmp_path):
    path = tmp_path / "config.json"
    original = b'{"preferences":{"theme":"dark"},"mcpServers":{"other":{"command":"other.exe"}}}\r\n'
    path.write_bytes(original)
    target, backup = client_config.add_client("claude", path, entry=ENTRY)
    assert target == path and backup.read_bytes() == original
    data = json.loads(path.read_text())
    assert data["mcpServers"]["other"]["command"] == "other.exe"
    assert data["mcpServers"]["stormworks-hulls"] == ENTRY
    assert data["preferences"]["theme"] == "dark"


def test_codex_preserves_comments_model_and_existing_server_options(tmp_path):
    path = tmp_path / "config.toml"
    original = ('# keep my preferences\nmodel = "my-model"\n'
                '[mcp_servers.other]\ncommand = "other.exe" # keep this too\n'
                '[mcp_servers.stormworks-hulls]\nurl = "https://example.com/mcp"\n'
                'disabled_tools = ["save_hull"]\n'
                '[mcp_servers.stormworks-hulls.env]\nSW_GAME_DIR = "D:/Steam/Stormworks"\n')
    path.write_text(original)
    client_config.add_client("codex", path, entry=ENTRY, replace=True)
    updated = path.read_text()
    assert "# keep my preferences" in updated and "# keep this too" in updated
    data = tomlkit.parse(updated)
    assert data["model"] == "my-model"
    server = data["mcp_servers"]["stormworks-hulls"]
    assert server["command"] == ENTRY["command"] and "url" not in server
    assert server["env"]["SW_GAME_DIR"] == "D:/Steam/Stormworks"
    assert server["disabled_tools"] == ["save_hull"]
    assert server["tool_timeout_sec"] == 300


@pytest.mark.parametrize("client,original", [("claude", "not json"), ("claude", "[]"),
                                           ("claude", '{"mcpServers":[] }'), ("codex", "not toml"),
                                           ("codex", "mcp_servers = 3")])
def test_invalid_existing_config_is_untouched(tmp_path, client, original):
    path = tmp_path / "config"
    path.write_text(original)
    with pytest.raises(ValueError):
        client_config.add_client(client, path, entry=ENTRY)
    assert path.read_text() == original and len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("client", ["claude", "codex"])
def test_replace_requires_explicit_opt_in_and_unique_backups(tmp_path, client):
    path = tmp_path / "client" / "config"
    _, backup = client_config.add_client(client, path, entry=ENTRY)
    assert backup is None
    original = path.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        client_config.add_client(client, path, entry=ENTRY)
    assert path.read_bytes() == original
    _, first = client_config.add_client(client, path, entry=ENTRY, replace=True)
    _, second = client_config.add_client(client, path, entry=ENTRY, replace=True)
    assert first != second and first.read_bytes() == second.read_bytes() == original


def test_frozen_config_uses_installed_executable(monkeypatch):
    monkeypatch.setattr(client_config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(client_config.sys, "executable", ENTRY["command"])
    assert client_config.server_entry() == {"command": str(Path(ENTRY["command"]).resolve()), "args": ["--connect"]}
    data = tomlkit.parse(client_config.raw_config("toml", ENTRY))
    assert data["mcp_servers"]["stormworks-hulls"]["command"] == ENTRY["command"]
    assert json.loads(client_config.raw_config("json", ENTRY))["mcpServers"]["stormworks-hulls"] == ENTRY


def test_client_paths_honor_appdata_and_codex_home(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "custom-codex"))
    assert client_config.default_config_path("claude") == tmp_path / "roaming" / "Claude" / "claude_desktop_config.json"
    assert client_config.default_config_path("codex") == tmp_path / "custom-codex" / "config.toml"


def test_concurrent_client_change_is_preserved(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text("{}")
    write_config = client_config._updated_config

    def race(*args):
        result = write_config(*args)
        path.write_text('{"new":true}')
        return result

    monkeypatch.setattr(client_config, "_updated_config", race)
    with pytest.raises(ValueError, match="changed during setup"):
        client_config.add_client("claude", path, entry=ENTRY)
    assert json.loads(path.read_text()) == {"new": True}
    assert len(list(tmp_path.iterdir())) == 1
