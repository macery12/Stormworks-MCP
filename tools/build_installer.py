"""Build the Windows installer (Inno Setup) around the dist/stormworks-mcp server folder.

Needs Inno Setup 6: set ISCC to its ISCC.exe, put it on PATH, or install it in the default
folder (winget install JRSoftware.InnoSetup). Writes dist/stormworks-mcp-setup.exe.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from swhull._version import __version__  # noqa: E402


def iscc():
    candidates = [os.environ.get("ISCC"), shutil.which("iscc")]
    for base, sub in ((os.environ.get("LOCALAPPDATA"), "Programs"), (os.environ.get("PROGRAMFILES(X86)"), ""),
                      (os.environ.get("PROGRAMFILES"), "")):
        if base:
            candidates.append(str(Path(base) / sub / "Inno Setup 6" / "ISCC.exe"))
    for path in candidates:
        if path and Path(path).is_file():
            return path
    raise SystemExit("Inno Setup 6 not found: install it (winget install JRSoftware.InnoSetup) or set ISCC")


def main():
    folder = ROOT / "dist" / "stormworks-mcp"
    if not (folder / "stormworks-mcp.exe").is_file():
        raise SystemExit(f"build the server first (tools/build_windows.py): {folder} is missing")
    subprocess.run([iscc(), "/Qp", f"/DAppVersion={__version__}", f"/DSourceDir={folder}",
                    f"/DOutputDir={ROOT / 'dist'}", str(ROOT / "installer" / "stormworks-mcp.iss")], check=True)
    print(ROOT / "dist" / "stormworks-mcp-setup.exe")


if __name__ == "__main__":
    main()
