"""Build the Windows server from locked dependencies into dist/stormworks-mcp/.

A folder build, not one file: a one-file EXE unpacks Python and every library into a temporary
folder on each start, which is slow enough for clients to give up on it. The EXE is windowed
(no console), so a client starting it never flashes a console window; launcher.py opens one
only for the double-click menu.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distpath", type=Path, default=ROOT / "dist",
                        help="Output directory; use a separate directory while the current EXE is running")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows executables must be built on Windows")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        # A crash must reach the log and the client, never a message box nobody is watching.
        "--disable-windowed-traceback", "--exclude-module", "tkinter",
        "--name", "stormworks-mcp", "--distpath", str(args.distpath.resolve()),
        "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
        "--collect-submodules", "mcp.server", "--exclude-module", "mcp.cli",
        "--collect-all", "mcp_types", "--collect-all", "swhull",
        "--collect-submodules", "glcontext", "--hidden-import", "moderngl",
        "--copy-metadata", "mcp",
        "--add-data", f"{ROOT / 'swhull' / 'guide.md'}:swhull",
        "--add-data", f"{ROOT / 'viewer' / 'index.html'}:viewer",
        "--add-data", f"{ROOT / 'docs'}:docs",
        "--add-data", f"{ROOT / 'LICENSE'}:.",
        str(ROOT / "launcher.py"),
    ], cwd=ROOT, check=True, env={**os.environ, "PYINSTALLER_CONFIG_DIR": str(ROOT / ".cache" / "pyinstaller")})


if __name__ == "__main__":
    main()
