"""Check GitHub for a newer published release (one HTTPS request; no data about the player is sent).

A running server checks at most once a day, in the background, and remembers the answer in
update.json. When a newer release exists, the AI is told in the server instructions, the start
guide and get_runtime_status, so it can pass the download link on. Nothing installs itself.
Set SW_MCP_NO_UPDATE_CHECK=1 to turn the check off.
"""
import json
import logging
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

from ._version import __version__

REPOSITORY = "macery12/Stormworks-MCP"
LATEST = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES = f"https://github.com/{REPOSITORY}/releases"
CHECK_INTERVAL = 24 * 3600
LOG = logging.getLogger("stormworks.updates")


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


def _state_path():
    from .runtime import data_dir  # noqa: PLC0415
    return data_dir() / "update.json"


def _legacy_opt_out():
    """v0.3's desktop app saved 'check for updates at startup' here; keep honouring an opt-out."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        return False
    try:
        settings = json.loads((Path(base) / "stormworks-hull-mcp" / "settings.json").read_text(encoding="utf-8"))
        return settings.get("check_updates", True) is False
    except (OSError, ValueError, AttributeError):
        return False


def disabled():
    return os.environ.get("SW_MCP_NO_UPDATE_CHECK", "").strip() not in ("", "0") or _legacy_opt_out()


def cached():
    """The last answer, {'checked', 'version', 'url'}, or None."""
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
        float(state["checked"])
        return state if isinstance(state.get("version"), str) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def remember(found, now=None):
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Several servers may check at once; each replaces the file whole.
    temporary = path.with_name(f"update-{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"checked": now or time.time(), **found}), encoding="utf-8")
    os.replace(temporary, path)


def check(now=None):
    """Ask GitHub unless the last answer is under a day old; returns the answer."""
    now = now or time.time()
    state = cached()
    if state and 0 <= now - state["checked"] < CHECK_INTERVAL:
        return state
    found = latest()
    remember(found, now)
    if newer(found["version"]):
        LOG.info("Stormworks MCP %s is available (this is %s): %s", found["version"], __version__, found["url"])
    return {"checked": now, **found}


def check_in_background():
    if disabled():
        return

    def work():
        try:
            check()
        except (OSError, ValueError) as exc:
            LOG.info("Update check failed: %s", exc)

    threading.Thread(target=work, daemon=True, name="update check").start()


def notice():
    """One line for the AI to pass on when a newer release is known, else None."""
    state = None if disabled() else cached()
    if not state or not newer(state["version"]):
        return None
    return (f"Stormworks MCP {state['version']} is available (this is {__version__}). Tell the player once: "
            f"download the installer from {state.get('url') or RELEASES}, close the AI client, run it "
            "(it upgrades in place), then reopen the client.")
