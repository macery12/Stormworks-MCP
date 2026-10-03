"""Build the portable desktop MCP executable from locked dependencies."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows executables must be built on Windows")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
        "--hide-console", "hide-early",
        "--name", "stormworks-mcp", "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
        "--collect-submodules", "mcp.server", "--exclude-module", "mcp.cli",
        "--collect-all", "mcp_types", "--collect-all", "swhull",
        "--copy-metadata", "mcp",
        "--add-data", f"{ROOT / 'swhull' / 'guide.md'}:swhull",
        "--add-data", f"{ROOT / 'viewer' / 'index.html'}:viewer",
        "--add-data", f"{ROOT / 'docs'}:docs",
        "--add-data", f"{ROOT / 'LICENSE'}:.",
        str(ROOT / "launcher.py"),
    ], cwd=ROOT, check=True, env={**os.environ, "PYINSTALLER_CONFIG_DIR": str(ROOT / ".cache" / "pyinstaller")})


if __name__ == "__main__":
    main()
