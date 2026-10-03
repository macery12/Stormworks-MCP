"""Read-only runtime diagnostics, usable before connecting an MCP client."""

import os
import sys
from pathlib import Path

from ._version import __version__
from .cache import cache_dir
from .definitions import definitions_dir
from .vehicle import vehicles_dir


def runtime_status():
    from .desktop_runtime import port, runtime_dir  # noqa: PLC0415

    appdata = Path(os.environ.get("APPDATA") or Path.home() / ".local" / "share")
    definitions = definitions_dir()
    return {
        "version": __version__,
        "packaged": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "python": sys.version.split()[0],
        "desktop_runtime_dir": str(runtime_dir()),
        "shared_endpoint": f"http://127.0.0.1:{port()}/mcp",
        "vehicles_dir": str(vehicles_dir()),
        "designs_dir": str(Path(os.environ.get("SW_DESIGNS_DIR", appdata / "stormworks-hull-mcp" / "designs"))),
        "definitions_dir": definitions,
        "installed_components_available": definitions is not None,
        "build_cache_dir": str(cache_dir()),
        "build_cache_enabled": os.environ.get("SW_BUILD_CACHE", "1") != "0",
        "tool_timeout_seconds": float(os.environ.get("SW_TOOL_TIMEOUT", "300")),
        "notes": ["Blocks and built-in slopes work without game definitions.",
                  "Installed components need your local Stormworks definitions.",
                  "Client tool timeouts should allow at least 300 seconds for large builds."]
    }
