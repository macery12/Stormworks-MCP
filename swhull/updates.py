"""Check GitHub for a newer published release (one HTTPS request; no data about the user is sent).

The desktop app checks once at startup unless the player turned it off (Help menu), and on
Help > Check for updates. Set SW_MCP_NO_UPDATE_CHECK=1 to disable it entirely.
"""
import json
import os
import re
import urllib.request
from pathlib import Path

from ._version import __version__

REPOSITORY = "macery12/Stormworks-MCP"
LATEST = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES = f"https://github.com/{REPOSITORY}/releases"


def parse(version):
    """'v0.3', '0.3.0' or 'v1.2.3' -> (0, 3, 0); None when it is not a plain release version."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)(?:\.(\d+))?", str(version).strip())
    return (int(match[1]), int(match[2]), int(match[3] or 0)) if match else None


def newer(candidate, current=__version__):
    a, b = parse(candidate), parse(current)
    return a is not None and b is not None and a > b


def latest(timeout=5.0):
    """{'version', 'url'} of the latest published release; raises OSError or ValueError."""
    req = urllib.request.Request(LATEST, headers={"Accept": "application/vnd.github+json",
                                                  "User-Agent": f"stormworks-mcp/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - fixed https URL
        data = json.loads(response.read())
    version = parse(data.get("tag_name", ""))
    if version is None:
        raise ValueError(f"unexpected release tag {data.get('tag_name')!r}")
    return {"version": ".".join(map(str, version)), "url": data.get("html_url") or RELEASES}


def disabled_by_environment():
    return os.environ.get("SW_MCP_NO_UPDATE_CHECK", "").strip() not in ("", "0")


def _settings_path():
    from .desktop_runtime import runtime_dir  # noqa: PLC0415
    return Path(runtime_dir()).parent / "settings.json"


def check_at_startup():
    """The player's choice, default on."""
    try:
        return bool(json.loads(_settings_path().read_text(encoding="utf-8")).get("check_updates", True))
    except (OSError, ValueError, AttributeError):
        return True


def set_check_at_startup(value):
    path = _settings_path()
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            settings = {}
    except (OSError, ValueError):
        settings = {}
    settings["check_updates"] = bool(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
