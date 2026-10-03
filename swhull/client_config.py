"""Client configuration with backups, comment-preserving TOML and atomic publication."""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import tomlkit
from tomlkit.exceptions import ParseError

SERVER_NAME = "stormworks-hulls"
ROOT = Path(__file__).resolve().parent.parent


def server_entry():
    """Use the final executable location, never a working directory or temporary extraction path."""
    if getattr(sys, "frozen", False):
        return {"command": str(Path(sys.executable).resolve()), "args": ["--connect"]}
    return {"command": str(Path(sys.executable).resolve()), "args": [str(ROOT / "launcher.py"), "--connect"]}


def default_config_path(client):
    if client == "claude":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise ValueError("APPDATA is unavailable; choose Claude's config file manually")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    if client == "codex":
        return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"
    raise ValueError(f"unknown client: {client}")


def codex_snippet(entry):
    document = tomlkit.document()
    document["mcp_servers"] = {SERVER_NAME: {**entry, "startup_timeout_sec": 30, "tool_timeout_sec": 300}}
    return tomlkit.dumps(document)


def raw_config(kind, entry=None):
    entry = server_entry() if entry is None else entry
    if kind == "json":
        return json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2)
    if kind == "toml":
        return codex_snippet(entry)
    if kind == "command":
        command = ["codex", "mcp", "add", SERVER_NAME, "--", entry["command"], *entry["args"]]
        # PowerShell single-quoted arguments safely preserve spaces, $, backticks and apostrophes.
        return "& " + " ".join("'" + arg.replace("'", "''") + "'" for arg in command)
    raise ValueError(f"unknown config format: {kind}")


def _updated_config(original, client, entry, replace):
    try:
        data = json.loads(original) if client == "claude" and original else (
            {} if client == "claude" else tomlkit.parse(original))
    except (ValueError, ParseError) as exc:
        raise ValueError("The existing config is invalid; fix it before adding the server") from exc
    if not isinstance(data, dict):
        raise ValueError("The config must be an object/table")
    key = "mcpServers" if client == "claude" else "mcp_servers"
    servers = data.get(key)
    if servers is None:
        data[key] = {}
        servers = data[key]
    if not isinstance(servers, dict):
        raise ValueError(f"{key} must be an object/table")
    if SERVER_NAME in servers and not replace:
        raise ValueError("This server already exists. Select 'Replace existing Stormworks entry' to update it.")
    # Preserve custom environment, disabled-tool settings and other options on an existing entry.
    current = servers.get(SERVER_NAME, {})
    if not isinstance(current, dict):
        raise ValueError("The existing Stormworks entry must be an object/table")
    incompatible = ("url", "http_headers", "bearer_token_env_var", "oauth", "http_headers_helper")
    for field in incompatible:
        if field in current:
            del current[field]
    current.update(entry)
    if client == "codex":
        current["startup_timeout_sec"] = 30
        current["tool_timeout_sec"] = 300
    servers[SERVER_NAME] = current
    return json.dumps(data, indent=2) + "\n" if client == "claude" else tomlkit.dumps(data)


def add_client(client, path=None, *, entry=None, replace=False):
    """Only update the chosen file after parsing; preserve original bytes in a unique backup."""
    if client not in ("claude", "codex"):
        raise ValueError(f"unknown client: {client}")
    path = Path(path) if path is not None else default_config_path(client)
    original = path.read_bytes() if path.exists() else None
    updated = _updated_config((original or b"").decode("utf-8-sig"), client,
                              server_entry() if entry is None else entry, replace)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary, backup = None, None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(updated.encode("utf-8"))
        # Refuse a concurrent change instead of replacing a client's newly written settings.
        now = path.read_bytes() if path.exists() else None
        if now != original:
            raise ValueError("Config changed during setup; close the client and try again")
        if original is not None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = path.with_name(f"{path.name}.{stamp}.bak")
            with backup.open("xb") as file:
                file.write(original)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path, backup
