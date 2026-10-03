"""Exercise real Tk controls and shared server lifecycle without touching client settings."""

import argparse
import contextlib
import os
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from swhull.desktop_runtime import ServerController, running_connection  # noqa: E402
from swhull.setup_gui import DesktopApp  # noqa: E402
from tools.package_test import available_port  # noqa: E402


def pump(window, predicate, timeout=40):
    deadline = time.monotonic() + timeout
    while not predicate():
        window.update()
        if time.monotonic() > deadline:
            raise TimeoutError("Desktop state did not settle")
        time.sleep(0.02)
    window.update()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--crash-parent", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, str(ROOT / "launcher.py")]
    if args.crash_parent:
        controller = ServerController(command)
        controller.start()
        deadline = time.monotonic() + 40
        while controller.state != "Running":
            if controller.state == "Stopped" or time.monotonic() > deadline:
                raise RuntimeError("Parent-crash smoke could not start its server")
            time.sleep(0.05)
        # Simulate a desktop crash: bypass controller cleanup and rely on the host's watcher.
        os._exit(0)
    with tempfile.TemporaryDirectory(prefix="stormworks-desktop-test-") as folder:
        env = {"SW_MCP_RUNTIME_DIR": str(Path(folder) / "runtime"), "SW_MCP_PORT": str(available_port()),
               "SW_BUILD_CACHE_DIR": str(Path(folder) / "cache"), "SW_DEFINITIONS_DIR": str(Path(folder) / "no-game")}
        with patch.dict(os.environ, env):
            crash_args = [sys.executable, str(Path(__file__).resolve()), "--crash-parent"]
            if args.exe:
                crash_args += ["--exe", str(args.exe.resolve())]
            subprocess.run(crash_args, check=True, capture_output=True, text=True, timeout=50)
            deadline = time.monotonic() + 12
            while (Path(folder) / "runtime" / "connection.json").exists():
                if time.monotonic() > deadline:
                    raise TimeoutError("Server survived its desktop parent's crash")
                time.sleep(0.05)
            packaged_gui = subprocess.run([*command, "--gui-smoke"], check=False, capture_output=True,
                                          text=True, timeout=70, env=os.environ.copy())
            if packaged_gui.returncode:
                print(packaged_gui.stdout, file=sys.stderr)
                print(packaged_gui.stderr, file=sys.stderr)
                raise RuntimeError(f"Packaged GUI failed: {packaged_gui.returncode}")
            assert "Packaged GUI smoke passed" in packaged_gui.stdout
            assert not (Path(folder) / "runtime" / "connection.json").exists()
            window = tk.Tk()
            window.withdraw()
            app = DesktopApp(window, ServerController(command))
            try:
                menu = window.nametowidget(window.cget("menu"))
                assert [menu.entrycget(index, "label") for index in range(menu.index("end") + 1)
                        if menu.type(index) == "cascade"] == ["File", "MCP", "View", "Help"]
                app.client_setup("claude")
                app.client_setup("codex")
                app.configuration()
                for dialog in app.dialogs.values():
                    dialog.withdraw()
                app.start_button.invoke()
                pump(window, lambda: app.controller.state == "Running" and str(app.stop_button.cget("state")) == "normal")
                first = running_connection()["instance"]
                app.start_button.invoke()
                assert running_connection()["instance"] == first
                app.stop_button.invoke()
                pump(window, lambda: app.controller.state == "Stopped")
                assert not (Path(folder) / "runtime" / "connection.json").exists()
                pump(window, lambda: str(app.start_button.cget("state")) == "normal")
                app.start_button.invoke()
                pump(window, lambda: app.controller.state == "Running" and str(app.stop_button.cget("state")) == "normal")
                assert running_connection()["instance"] != first
                app.close()
                # Closing uses the same stop path and waits for it before destroying the window.
                pump(window, lambda: app.controller.state == "Stopped")
                assert not (Path(folder) / "runtime" / "connection.json").exists()
                assert app.closing
                assert app.controller.process.poll() is not None
                print("Desktop smoke passed: packaged Tk, menus, Start/Stop/restart/close-stop and parent-crash cleanup")
            except BaseException:
                while not app.controller.logs.empty():
                    print(app.controller.logs.get_nowait(), file=sys.stderr)
                raise
            finally:
                app.controller.stop()
                if app.controller.process and app.controller.process.poll() is None:
                    app.controller.process.wait(timeout=15)
                with contextlib.suppress(tk.TclError):
                    window.destroy()


if __name__ == "__main__":
    main()
