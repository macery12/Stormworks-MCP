"""Client configuration with backups, comment-preserving TOML and atomic publication."""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import tomlkit
from tomlkit.exceptions import ParseError

SERVER_NAME = "stormworks"
# Earlier releases registered the server under these names; setup moves them to SERVER_NAME.
LEGACY_NAMES = ("stormworks-hulls",)
ROOT = Path(__file__).resolve().parent.parent


def server_entry():
    """The client starts this exact executable with --stdio, from wherever it is installed."""
    if getattr(sys, "frozen", False):
        return {"command": str(Path(sys.executable).resolve()), "args": ["--stdio"]}
    return {"command": str(Path(sys.executable).resolve()), "args": [str(ROOT / "launcher.py"), "--stdio"]}


def configured(client, path=None):
    """'yes' when the client's Stormworks entry runs this copy, 'other' when it runs another
    copy, 'no' when there is no entry or no readable config."""
    try:
        path = Path(path) if path is not None else default_config_path(client)
        text = path.read_text(encoding="utf-8-sig")
        data = json.loads(text) if client == "claude" else tomlkit.parse(text)
        servers = data.get("mcpServers" if client == "claude" else "mcp_servers") or {}
        entry = servers.get(SERVER_NAME) or next((servers[n] for n in LEGACY_NAMES if n in servers), None)
    except (OSError, ValueError, ParseError, AttributeError):
        return "no"
    if not isinstance(entry, dict) or "command" not in entry:
        return "no"
    mine = server_entry()["command"]
    try:
        same = Path(str(entry["command"])).resolve() == Path(mine).resolve()
    except OSError:
        same = False
    return "yes" if same else "other"


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
    legacy = [name for name in LEGACY_NAMES if name in servers]
    if (SERVER_NAME in servers or legacy) and not replace:
        raise ValueError("This server already exists. Select 'Replace existing Stormworks entry' to update it.")
    # Preserve custom environment, disabled-tool settings and other options on an existing entry,
    # including one saved under an earlier name, which is renamed rather than left as a duplicate.
    current = servers.get(SERVER_NAME) or (servers[legacy[0]] if legacy else {})
    if not isinstance(current, dict):
        raise ValueError("The existing Stormworks entry must be an object/table")
    for name in legacy:
        del servers[name]
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
            # Windows clocks can return the same microsecond twice; never reuse a backup name.
            for attempt in range(1000):
                backup = path.with_name(f"{path.name}.{stamp}{f'-{attempt}' if attempt else ''}.bak")
                try:
                    with backup.open("xb") as file:
                        file.write(original)
                    break
                except FileExistsError:
                    continue
            else:
                raise ValueError("Could not create a unique backup of the config; clean up old .bak files")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path, backup
