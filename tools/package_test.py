"""Exercise the source or frozen server the way clients use it: each client starts its own
server over stdio, servers share one log file and one design lock, and no server outlives its
client. Also drives the double-click console menu."""

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Implementation

ROOT = Path(__file__).resolve().parent.parent


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


def orphaned_server(command, args, env, cwd):
    """A client that dies without closing the server's stdin (another process still holds the
    pipe) must not leave the server running: it exits when its parent does."""
    code = ("import subprocess, sys, time; "
            "child = subprocess.Popen(sys.argv[1:], stdin=sys.stdin, stdout=subprocess.DEVNULL); "
            "print(child.pid, flush=True); "
            "time.sleep(600)")
    # The base interpreter, so the stand-in client is one process (a venv's python.exe is a
    # launcher plus a child, and killing the launcher would leave the client running).
    client = getattr(sys, "_base_executable", None) or sys.executable
    parent = subprocess.Popen([client, "-c", code, command, *args, "--stdio"], env=env, cwd=cwd,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    pid = int(parent.stdout.readline())
    try:
        time.sleep(3)
        assert alive(pid), "the server exited before its client did"
        parent.kill()
        parent.wait()
        assert wait_gone(pid, 15), "the server outlived its client"
    finally:
        parent.stdin.close()
        if alive(pid):
            subprocess.run(["taskkill", "/F", "/PID", str(pid)] if sys.platform == "win32" else ["kill", "-9", str(pid)],
                           capture_output=True, check=False)


def menu(command, args, env, cwd, keys):
    result = subprocess.run([command, *args, "--menu"], input=keys, capture_output=True, text=True,
                            env=env, cwd=cwd, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert "Stormworks MCP" in result.stdout and "starts this server" in result.stdout, result.stdout
    return result.stdout


async def full_session(session, second, temporary):
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
    assert status.structured_content["log_file"].endswith("log.txt")
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
    # Two servers write the same design at once; the shared lock keeps both writes.
    await asyncio.gather(*(s.call_tool("store_design", {"name": "shared", "preset": "rowboat"})
                           for s in (session, second)))
    stored = json.loads((temporary / "designs" / "shared.json").read_text(encoding="utf-8"))
    assert stored["generation"] == 2, stored


async def exercise(command, args):
    with tempfile.TemporaryDirectory(prefix="stormworks-package-test-") as folder:
        temporary = Path(folder)
        clients = temporary / "clients"
        (clients / "Claude").mkdir(parents=True)
        env = {**os.environ, "SW_VEHICLES_DIR": str(temporary / "vehicles"),
               "SW_DESIGNS_DIR": str(temporary / "designs"),
               "SW_BUILD_CACHE_DIR": str(temporary / "cache"), "SW_DEFINITIONS_DIR": str(temporary / "no-game"),
               "SW_MCP_DATA_DIR": str(temporary / "data"), "SW_MCP_NO_UPDATE_CHECK": "1",
               "APPDATA": str(clients), "CODEX_HOME": str(clients / "codex")}
        log = temporary / "data" / "logs" / "log.txt"
        # Configuration targets the actual executable, also when invoked from another cwd.
        config = subprocess.run([command, *args, "--config", "json"], check=True, capture_output=True,
                                text=True, env=env, cwd=temporary, timeout=60)
        entry = json.loads(config.stdout)["mcpServers"]["stormworks"]
        assert Path(entry["command"]).resolve() == Path(command).resolve()
        assert entry["args"][-1] == "--stdio"
        try:
            # Each client starts its own server; neither needs anything else running first.
            first = StdioServerParameters(command=command, args=[*args, "--stdio"], env=env, cwd=str(temporary))
            # v0.3 entries ran --connect; that now starts the server too.
            legacy = StdioServerParameters(command=command, args=[*args, "--connect"], env=env, cwd=str(temporary))
            async with (stdio_client(legacy) as (read2, write2),
                        ClientSession(read2, write2, client_info=Implementation(name="legacy-client", version="1"))
                        as second):
                await second.initialize()
                async with (stdio_client(first) as (read, write),
                            ClientSession(read, write, client_info=Implementation(name="first-client", version="1"))
                            as session):
                    await full_session(session, second, temporary)
                # Closing one client leaves the other's server working.
                assert not (await second.call_tool("get_runtime_status", {})).is_error
            # A client that gives no arguments but a pipe still gets the server.
            bare = StdioServerParameters(command=command, args=args, env=env, cwd=str(temporary))
            async with stdio_client(bare) as (read, write), ClientSession(read, write) as session:
                await session.initialize()
                assert (await session.list_tools()).tools
            await asyncio.to_thread(orphaned_server, command, args, env, temporary)
            await asyncio.sleep(1)
            text = log.read_text(encoding="utf-8")
            for expected in ("first-client[", "legacy-client[", "Tool preview_hull completed",
                             "Connected to first-client", "Server stopped (client disconnected)",
                             "Server stopped (client exited)"):
                assert expected in text, f"log.txt lacks {expected!r}"
            # The double-click menu: exit, then add Claude Desktop through it.
            menu(command, args, env, temporary, "5\n")
            output = menu(command, args, env, temporary, "1\ny\n5\n")
            claude = json.loads((clients / "Claude" / "claude_desktop_config.json").read_text(encoding="utf-8"))
            assert claude["mcpServers"]["stormworks"]["args"][-1] == "--stdio", claude
            assert "Done." in output and "Add to Claude Desktop (set up)" in output, output
        except BaseException:
            if log.is_file():
                print(log.read_text(encoding="utf-8"), file=sys.stderr)
            raise
        print("Stdio MCP smoke passed: two clients with their own servers, legacy --connect entries, bare "
              "pipe start, shared log and design lock, no server left behind by a dead client, console menu")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    command, argv = (str(args.exe.resolve()), []) if args.exe else (sys.executable, [str(ROOT / "launcher.py")])
    asyncio.run(asyncio.wait_for(exercise(command, argv), timeout=240))


if __name__ == "__main__":
    main()
