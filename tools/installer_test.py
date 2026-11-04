"""Smoke-test the Windows installer: silent per-user install into a folder with spaces,
upgrade over running copies (two servers started the way clients start them), then
uninstall. Refuses to run when Stormworks MCP is already installed, so a real install is
never replaced; CI runners start clean."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
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


def run(installer, target, log, tasks="", env=None):
    subprocess.run([str(installer), *QUIET, f"/DIR={target}", f"/LOG={log}", f"/TASKS={tasks}"],
                   check=True, timeout=300, env=env)


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
        # Client set-up writes to stand-in client folders: the installer and the EXE both read
        # APPDATA and CODEX_HOME, so the real client settings are never touched.
        clients = Path(scratch) / "clients"
        (clients / "Claude").mkdir(parents=True)
        (clients / "codex").mkdir()
        client_env = {**os.environ, "APPDATA": str(clients), "CODEX_HOME": str(clients / "codex")}
        run(installer, target, Path(scratch) / "install.log", "clientclaude,clientcodex", client_env)
        record = installed()
        if not (target / "_internal").is_dir():
            raise SystemExit(f"the server's libraries are missing from {target}")
        if not exe.is_file() or not record or Path(record["InstallLocation"]).resolve() != target.resolve():
            raise SystemExit(f"install did not land in {target}: {record}")
        version = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60,
                                 check=True).stdout.strip()
        if version != record["DisplayVersion"]:
            raise SystemExit(f"installed EXE reports {version!r}, the uninstall entry {record['DisplayVersion']!r}")
        claude = json.loads((clients / "Claude" / "claude_desktop_config.json").read_text(encoding="utf-8"))
        entry = claude["mcpServers"]["stormworks"]
        if Path(entry["command"]).resolve() != exe.resolve() or entry["args"] != ["--stdio"]:
            raise SystemExit(f"Claude Desktop entry does not run the installed EXE: {entry}")
        codex = tomllib.loads((clients / "codex" / "config.toml").read_text(encoding="utf-8"))
        command = codex["mcp_servers"]["stormworks"]["command"]
        # Compare resolved paths: a runner's temp folder can be a short (8.3) path.
        if Path(command).resolve() != exe.resolve():
            raise SystemExit(f"the Codex entry does not run the installed EXE: {command}")
        shortcut = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Stormworks MCP.lnk"
        if not shortcut.is_file():
            raise SystemExit(f"no Start menu shortcut at {shortcut}")
        # Servers that clients left running (one from a v0.3 --connect entry) must not block an upgrade.
        env = {**os.environ, "SW_MCP_DATA_DIR": str(Path(scratch) / "data"), "SW_MCP_NO_UPDATE_CHECK": "1"}
        servers = [subprocess.Popen([str(exe), mode], env=env, stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                   for mode in ("--stdio", "--connect")]
        time.sleep(5)
        running = [p for p in servers if p.poll() is None]
        if len(running) != len(servers):
            raise SystemExit("a server started like a client starts it exited on its own")
        run(installer, target, Path(scratch) / "upgrade.log")
        wait(lambda: all(p.poll() is not None for p in running), 30, "running copies to stop during the upgrade")
        if not exe.is_file() or not (target / "_internal").is_dir():
            raise SystemExit("upgrade removed the server")
        subprocess.run([str(target / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                       check=True, timeout=300)
        wait(lambda: not exe.exists() and not (target / "_internal").exists() and installed() is None, 60,
             "the uninstaller to remove the server and its entry")
        if shortcut.exists():
            raise SystemExit("uninstall left the Start menu shortcut")
    print(f"Installer smoke passed: install to a path with spaces, version {version}, Start menu shortcut, "
          f"Claude Desktop and Codex entries, "
          f"upgrade over {len(running)} running copies, uninstall")


if __name__ == "__main__" and sys.platform == "win32":
    main()
