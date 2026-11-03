"""Exercise two stdio connectors against one source or frozen shared desktop host."""

import argparse
import asyncio
import base64
import contextlib
import json
import os
import subprocess
import sys
import socket
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from swhull.desktop_runtime import request, running_connection  # noqa: E402


def alive(pid):
    if sys.platform == "win32":
        import ctypes  # noqa: PLC0415

        kernel = ctypes.WinDLL("kernel32")
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_gone(pid, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not alive(pid):
            return True
        time.sleep(0.25)
    return False


def orphaned_bridge(command, args, env, cwd):
    """A client that dies without closing the bridge's stdin (another process still holds the
    pipe) must not leave the bridge running: it exits when its parent does."""
    code = ("import subprocess, sys, time; "
            "child = subprocess.Popen(sys.argv[1:], stdin=sys.stdin, stdout=subprocess.DEVNULL); "
            "print(child.pid, flush=True); "
            "time.sleep(600)")
    # The base interpreter, so the stand-in client is one process (a venv's python.exe is a
    # launcher plus a child, and killing the launcher would leave the client running).
    client = getattr(sys, "_base_executable", None) or sys.executable
    parent = subprocess.Popen([client, "-c", code, command, *args, "--connect"], env=env, cwd=cwd,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    pid = int(parent.stdout.readline())
    try:
        time.sleep(3)
        assert alive(pid), "the bridge exited before its client did"
        parent.kill()
        parent.wait()
        assert wait_gone(pid, 15), "the bridge outlived its client"
    finally:
        parent.stdin.close()
        if alive(pid):
            subprocess.run(["taskkill", "/F", "/PID", str(pid)] if sys.platform == "win32" else ["kill", "-9", str(pid)],
                           capture_output=True, check=False)


def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


async def wait_ready(process):
    for _ in range(200):
        if process.poll() is not None:
            raise RuntimeError(f"Shared server exited: {process.returncode}")
        try:
            return await asyncio.to_thread(running_connection)
        except ValueError:
            await asyncio.sleep(0.15)
    raise TimeoutError("Shared server did not become ready")


async def exercise(command, args):
    with tempfile.TemporaryDirectory(prefix="stormworks-package-test-") as folder:
        temporary = Path(folder)
        env = {**os.environ, "SW_VEHICLES_DIR": str(temporary / "vehicles"),
               "SW_DESIGNS_DIR": str(temporary / "designs"),
               "SW_BUILD_CACHE_DIR": str(temporary / "cache"), "SW_DEFINITIONS_DIR": str(temporary / "no-game"),
               "SW_MCP_RUNTIME_DIR": str(temporary / "runtime"), "SW_MCP_PORT": str(available_port())}
        # Prove configuration targets the actual executable, also when invoked from another cwd.
        config = subprocess.run([command, *args, "--config", "json"], check=True, capture_output=True,
                                text=True, env=env, cwd=temporary, timeout=60)
        entry = json.loads(config.stdout)["mcpServers"]["stormworks"]
        assert Path(entry["command"]).resolve() == Path(command).resolve()
        assert entry["args"][-1] == "--connect"
        parameters = StdioServerParameters(command=command, args=[*args, "--connect"], env=env, cwd=str(temporary))
        with patch.dict(os.environ, env), (temporary / "server.log").open("w", encoding="utf-8") as logs:
            host = subprocess.Popen([command, *args, "--serve", "--parent-pid", str(os.getpid())], env=env,
                                    cwd=temporary, stdin=subprocess.DEVNULL, stdout=logs, stderr=logs)
            try:
                record = await wait_ready(host)
                # Unauthenticated or foreign-origin callers cannot inspect or stop the host.
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for route, method, headers in (("/health", "GET", {}), ("/shutdown", "POST", {}),
                                                ("/health", "GET", {"Authorization": f"Bearer {record['token']}",
                                                                      "Origin": "https://example.com"})):
                    req = urllib.request.Request(f"http://127.0.0.1:{record['port']}{route}", method=method, headers=headers)
                    try:
                        opener.open(req, timeout=2)
                    except urllib.error.HTTPError as exc:
                        assert exc.code == 403
                    else:
                        raise AssertionError("Unauthenticated/cross-origin request was accepted")
                duplicate = await asyncio.to_thread(subprocess.run, [command, *args, "--serve"], env=env,
                                                    capture_output=True, text=True, timeout=60)
                assert duplicate.returncode != 0 and "already running" in duplicate.stderr
                assert running_connection()["instance"] == record["instance"]
                async with stdio_client(parameters) as (read2, write2), ClientSession(read2, write2) as second:
                    await second.initialize()
                    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
                        init = await session.initialize()
                        assert init.instructions and init.server_info.version
                        descriptors = {tool.name: tool for tool in (await session.list_tools()).tools}
                        tools = set(descriptors)
                        assert {"preview_hull", "save_hull", "get_runtime_status", "get_guide",
                                "analyze_hull", "suggest_hull_blocks", "create_vehicle", "search_parts", "query_connections",
                                "edit_connections", "route_connections", "preflight_vehicle", "plan_vehicle_repairs",
                                "repair_vehicle", "apply_vehicle_assembly", "preview_vehicle_diagnostics",
                                "prepare_vehicle_validation", "record_vehicle_validation"} <= tools
                        assert descriptors["repair_vehicle"].output_schema["type"] == "object"
                        assert all(tool.output_schema for tool in descriptors.values())
                        for topic in ("start", "hull_workflow", "hull_staged", "edits", "testing", "hull_smoothing",
                                      "style_rules", "topics"):
                            response = await session.call_tool("get_guide", {"topic": topic})
                            assert not response.is_error and response.content[0].text
                        response = await session.call_tool("get_guide", {"topic": "land"})
                        assert not response.is_error and "humvee_4x4" in response.content[0].text
                        assert "through_blocks" in response.content[0].text
                        response, status = await asyncio.gather(
                            session.call_tool("preview_hull", {"preset": "rowboat"}),
                            second.call_tool("get_runtime_status", {}))
                        assert not response.is_error and not status.is_error
                        image = next(part for part in response.content if part.type == "image")
                        assert base64.b64decode(image.data).startswith(b"\x89PNG\r\n\x1a\n")
                        response = await session.call_tool("save_hull", {"name": "packaged smoke test", "preset": "rowboat"})
                        assert not response.is_error, response.content
                        assert "cache reused" in response.content[0].text
                        assert (temporary / "vehicles" / "packaged smoke test.xml").is_file()
                        diagnosis = await session.call_tool("plan_vehicle_repairs", {"design": "packaged smoke test"})
                        assert not diagnosis.is_error and diagnosis.structured_content["plan_id"]
                        preflight = await session.call_tool("preflight_vehicle", {"design": "packaged smoke test"})
                        # A boat without an engine is not a fault: preflight checks what is there.
                        assert not preflight.is_error and preflight.structured_content["status"] == "connected geometry"
                        assert preflight.structured_content["unchecked"] == []
                        diagnostics = await session.call_tool("preview_vehicle_diagnostics", {"design": "packaged smoke test", "layer": "all"})
                        assert not diagnostics.is_error and diagnostics.structured_content["overlay"]["legend"]
                        assert any(part.type == "image" for part in diagnostics.content)
                        validation = await session.call_tool("prepare_vehicle_validation", {"design": "packaged smoke test", "name": "validation copy"})
                        assert not validation.is_error and validation.structured_content["status"] == "pending"
                        invalid = await session.call_tool("edit_parts", {"design": "packaged smoke test",
                            "revision": diagnosis.structured_content["revision"],
                            "operations": [{"op": "move", "select": {"ids": ["bad"]}}]})
                        assert invalid.is_error
                        choices = await session.call_tool("suggest_hull_blocks", {"normal": [0, 1, 0.25]})
                        assert not choices.is_error and "08_wedge_4" in choices.content[0].text
                        analysis = await session.call_tool("analyze_hull", {"preset": "rowboat", "stations": [8],
                                                                          "spec": {"smoothing": "wedges_v2"}})
                        assert not analysis.is_error and "material_y_blocks" in analysis.content[0].text
                        response = await session.call_tool("preview_hull", {"spec": {"length": 500}})
                        assert response.is_error
                    # Disconnecting one client must leave the shared host and another client alive.
                    assert not (await second.call_tool("get_runtime_status", {})).is_error
                    assert running_connection()["instance"] == record["instance"]
                await asyncio.to_thread(orphaned_bridge, command, args, env, temporary)
                # An idle bridge must exit when the desktop host stops (the GUI was closed).
                idle = subprocess.Popen([command, *args, "--connect"], env=env, cwd=temporary,
                                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                await asyncio.sleep(3)
                assert idle.poll() is None, "the idle bridge exited early"
                request(record, "/shutdown", method="POST")
                await asyncio.to_thread(host.wait, timeout=15)
                try:
                    await asyncio.to_thread(idle.wait, timeout=15)
                except subprocess.TimeoutExpired:
                    idle.kill()
                    raise AssertionError("an idle bridge kept running after the host stopped") from None
                finally:
                    idle.stdin.close()
                assert not (temporary / "runtime" / "connection.json").exists()
                stopped = await asyncio.to_thread(subprocess.run, [command, *args, "--connect"], env=env,
                                                  input="", capture_output=True, text=True, timeout=60)
                assert stopped.returncode != 0 and not stopped.stdout and "press Start" in stopped.stderr
                log_content = (temporary / "server.log").read_text(encoding="utf-8")
                assert "preview_hull completed" in log_content and "Stop requested" in log_content
            except BaseException:
                print((temporary / "server.log").read_text(encoding="utf-8"), file=sys.stderr)
                raise
            finally:
                if host.poll() is None:
                    with contextlib.suppress(OSError, ValueError):
                        request(running_connection(), "/shutdown", method="POST")
                    try:
                        await asyncio.to_thread(host.wait, timeout=10)
                    except subprocess.TimeoutExpired:
                        host.kill()
                        host.wait()
        print("Shared MCP smoke passed: two clients, one host, workers, cache/export, duplicate rejection, logs, stop, "
          "no bridge left behind by a dead client or a stopped host")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    command, argv = (str(args.exe.resolve()), []) if args.exe else (sys.executable, [str(ROOT / "launcher.py")])
    asyncio.run(asyncio.wait_for(exercise(command, argv), timeout=180))


if __name__ == "__main__":
    main()
