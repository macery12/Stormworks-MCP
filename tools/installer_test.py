"""Smoke-test the Windows installer: silent per-user install into a folder with spaces,
upgrade over a running copy (the desktop host and an orphaned --connect bridge), then
uninstall. Refuses to run when Stormworks MCP is already installed, so a real install is
never replaced; CI runners start clean."""
import argparse
import os
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{20748683-2FB1-4BC7-9C12-7CA37ABA71FF}_is1"
QUIET = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER"]


def installed():
    for root, view in ((winreg.HKEY_CURRENT_USER, 0), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                       (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY)):
        try:
            with winreg.OpenKey(root, KEY, 0, winreg.KEY_READ | view) as key:
                return {name: winreg.QueryValueEx(key, name)[0] for name in ("InstallLocation", "DisplayVersion")}
        except OSError:
            continue
    return None


def run(installer, target, log):
    subprocess.run([str(installer), *QUIET, f"/DIR={target}", f"/LOG={log}"], check=True, timeout=300)


def wait(condition, seconds, what):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return
        time.sleep(0.5)
    raise SystemExit(f"timed out waiting for {what}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", default="dist/stormworks-mcp-setup.exe")
    args = parser.parse_args()
    installer = Path(args.installer).resolve()
    if installed():
        raise SystemExit("Stormworks MCP is already installed on this account; uninstall it or run this on a clean machine")
    with tempfile.TemporaryDirectory() as scratch:
        target = Path(scratch) / "Stormworks MCP install"
        exe = target / "stormworks-mcp.exe"
        run(installer, target, Path(scratch) / "install.log")
        record = installed()
        if not exe.is_file() or not record or Path(record["InstallLocation"]).resolve() != target.resolve():
            raise SystemExit(f"install did not land in {target}: {record}")
        version = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60,
                                 check=True).stdout.strip()
        if version != record["DisplayVersion"]:
            raise SystemExit(f"installed EXE reports {version!r}, the uninstall entry {record['DisplayVersion']!r}")
        shortcut = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Stormworks MCP.lnk"
        if not shortcut.is_file():
            raise SystemExit(f"no Start menu shortcut at {shortcut}")
        # A running host and a bridge whose client has gone must not block an upgrade.
        env = {**os.environ, "SW_MCP_RUNTIME_DIR": str(Path(scratch) / "runtime"), "SW_MCP_PORT": "38491"}
        host = subprocess.Popen([str(exe), "--serve"], env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(5)
        bridge = subprocess.Popen([str(exe), "--connect"], env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        running = [p for p in (host, bridge) if p.poll() is None]
        run(installer, target, Path(scratch) / "upgrade.log")
        wait(lambda: all(p.poll() is not None for p in running), 30, "running copies to stop during the upgrade")
        if not exe.is_file():
            raise SystemExit("upgrade removed the EXE")
        subprocess.run([str(target / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                       check=True, timeout=300)
        wait(lambda: not exe.exists() and installed() is None, 60, "the uninstaller to remove the EXE and its entry")
        if shortcut.exists():
            raise SystemExit("uninstall left the Start menu shortcut")
    print(f"Installer smoke passed: install to a path with spaces, version {version}, Start menu shortcut, "
          f"upgrade over {len(running)} running copies, uninstall")


if __name__ == "__main__" and sys.platform == "win32":
    main()
