"""One per-user loopback host; client connectors relay MCP without starting a host."""

import contextlib
import hmac
import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from ._version import __version__

LOG = logging.getLogger("stormworks.desktop")
HOST = "127.0.0.1"
DEFAULT_PORT = 38473


def runtime_dir():
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home() / ".local" / "share")
    return Path(os.environ.get("SW_MCP_RUNTIME_DIR", Path(base) / "stormworks-hull-mcp" / "runtime"))


def port():
    value = int(os.environ.get("SW_MCP_PORT", str(DEFAULT_PORT)))
    if not 1024 <= value <= 65535:
        raise ValueError("SW_MCP_PORT must be between 1024 and 65535")
    return value


def launch_command(*args):
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, str(Path(__file__).resolve().parent.parent / "launcher.py"), *args]


class InstanceLock:
    """OS-held lock is released on a crash; leftover files never prevent a restart."""

    def __init__(self, name):
        self.path = runtime_dir() / f"{name}.lock"
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open("a+b")
        if file.tell() == 0:
            file.write(b"0")
            file.flush()
        file.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt  # noqa: PLC0415

                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl  # noqa: PLC0415

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            file.close()
            raise ValueError("Stormworks MCP is already running. Use the existing window.") from None
        self.file = file
        return self

    def close(self):
        if self.file is not None:
            self.file.close()
            self.file = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.close()


def read_connection():
    try:
        record = json.loads((runtime_dir() / "connection.json").read_text(encoding="utf-8"))
        # Discovery never permits redirecting a connector outside this machine.
        if record["host"] != HOST or not 1024 <= record["port"] <= 65535 or not record["token"]:
            raise ValueError("Invalid local server record")
        return record
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("Open Stormworks MCP, press Start, then reconnect your MCP client.") from exc


def request(record, path, *, method="GET", timeout=0.5):
    url = f"http://{HOST}:{record['port']}{path}"
    req = urllib.request.Request(url, method=method, headers={"Authorization": f"Bearer {record['token']}"})
    # A user/system HTTP proxy must never receive the local bearer token.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as response:
        return json.loads(response.read())


def running_connection():
    record = read_connection()
    try:
        status = request(record, "/health")
        if status.get("instance") != record["instance"]:
            raise ValueError("Server instance changed")
    except (OSError, ValueError, KeyError) as exc:
        raise ValueError("The desktop server is stopped. Open Stormworks MCP, press Start, then reconnect your client.") from exc
    return record


def _watch_parent(parent_pid, stop):
    if sys.platform == "win32":
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x00100000, False, parent_pid)  # SYNCHRONIZE
        if handle:
            try:
                kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
            finally:
                kernel.CloseHandle(handle)
        stop()
    else:
        while os.getppid() == parent_pid:
            time.sleep(0.5)
        stop()


def run_server(parent_pid=None):
    """Bind only loopback, authenticate all requests, and publish ephemeral connection details."""
    import uvicorn  # noqa: PLC0415
    from starlette.responses import JSONResponse  # noqa: PLC0415

    from server import mcp  # noqa: PLC0415

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    record = {"host": HOST, "port": port(), "token": secrets.token_urlsafe(32),
              "instance": os.environ.get("SW_MCP_INSTANCE") or secrets.token_hex(16),
              "pid": os.getpid(), "version": __version__}
    with InstanceLock("server"):
        app = mcp.streamable_http_app(host=HOST)
        host_server = None

        async def authenticated(scope, receive, send):
            if scope["type"] != "http":
                return await app(scope, receive, send)
            headers = dict(scope["headers"])
            supplied = headers.get(b"authorization", b"")
            valid = hmac.compare_digest(supplied, f"Bearer {record['token']}".encode())
            # Health/shutdown routes need the same rebinding/origin checks as /mcp.
            host = headers.get(b"host", b"")
            origin = headers.get(b"origin")
            expected_host = f"{HOST}:{record['port']}".encode()
            if not valid or host != expected_host or (origin and origin != b"http://" + expected_host):
                return await JSONResponse({"error": "Unauthorized local request"}, status_code=403)(scope, receive, send)
            path = scope["path"]
            if path == "/health" and scope["method"] == "GET":
                return await JSONResponse({"instance": record["instance"], "version": __version__})(scope, receive, send)
            if path == "/shutdown" and scope["method"] == "POST":
                LOG.info("Stop requested; disconnecting clients")
                host_server.should_exit = True
                return await JSONResponse({"stopping": True})(scope, receive, send)
            return await app(scope, receive, send)

        host_server = uvicorn.Server(uvicorn.Config(authenticated, host=HOST, port=record["port"],
                                                  log_level="info", timeout_graceful_shutdown=3))
        connection_path = runtime_dir() / "connection.json"
        temporary = runtime_dir() / f"connection-{record['instance']}.tmp"
        try:
            # Publish after the listener has been bound, so a port conflict never publishes a host.
            with socket.socket() as listener:
                if sys.platform == "win32":
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind((HOST, record["port"]))
                temporary.touch(mode=0o600)
                temporary.write_text(json.dumps(record), encoding="utf-8")
                os.replace(temporary, connection_path)
                if parent_pid:
                    threading.Thread(target=_watch_parent, args=(parent_pid, lambda: setattr(host_server, "should_exit", True)),
                                     daemon=True).start()
                LOG.info("Starting shared server %s at http://%s:%s/mcp", __version__, HOST, record["port"])
                host_server.run(sockets=[listener])
        finally:
            temporary.unlink(missing_ok=True)
            with contextlib.suppress(OSError, ValueError):
                if json.loads(connection_path.read_text())["instance"] == record["instance"]:
                    connection_path.unlink(missing_ok=True)
            LOG.info("Shared server stopped")


async def bridge():
    """Relay whole protocol messages, retaining IDs, cancellation, errors and notifications."""
    import anyio  # noqa: PLC0415
    import httpx2  # noqa: PLC0415
    from mcp.client.streamable_http import streamable_http_client  # noqa: PLC0415
    from mcp.server.stdio import stdio_server  # noqa: PLC0415
    from mcp.shared.message import ClientMessageMetadata  # noqa: PLC0415
    from mcp_types import JSONRPCRequest, JSONRPCResponse  # noqa: PLC0415

    record = await anyio.to_thread.run_sync(running_connection)
    url = f"http://{HOST}:{record['port']}/mcp"
    protocol_version, initialize_id = None, None
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {record['token']}"},
                          timeout=httpx2.Timeout(330, connect=5), trust_env=False) as http,
        streamable_http_client(url, http_client=http) as (remote_read, remote_write),
        stdio_server() as (local_read, local_write),
        anyio.create_task_group() as group,
    ):
        async def to_host():
            nonlocal initialize_id
            try:
                async for item in local_read:
                    if isinstance(item, Exception):
                        raise item
                    if isinstance(item.message, JSONRPCRequest) and item.message.method == "initialize":
                        initialize_id = item.message.id
                    elif protocol_version:
                        item.metadata = ClientMessageMetadata(headers={"MCP-Protocol-Version": protocol_version})
                    await remote_write.send(item)
            finally:
                group.cancel_scope.cancel()

        async def to_client():
            nonlocal protocol_version
            try:
                async for item in remote_read:
                    if isinstance(item, Exception):
                        raise item
                    if isinstance(item.message, JSONRPCResponse) and item.message.id == initialize_id:
                        protocol_version = item.message.result.get("protocolVersion")
                    await local_write.send(item)
            finally:
                group.cancel_scope.cancel()

        group.start_soon(to_host)
        group.start_soon(to_client)


class ServerController:
    """Nonblocking GUI lifecycle; queued logs contain bounded text, never tool arguments."""

    def __init__(self, command=None):
        import queue  # noqa: PLC0415

        self.logs = queue.Queue(maxsize=2000)
        self.command = command if command is not None else launch_command()
        self.process = None
        self.state = "Stopped"
        self.record = None
        self.instance = None

    def log(self, message):
        import queue  # noqa: PLC0415

        with contextlib.suppress(queue.Full):
            self.logs.put_nowait(message.rstrip())

    def start(self):
        if self.state != "Stopped":
            return
        self.state = "Starting"
        self.record = None
        self.instance = secrets.token_hex(16)
        try:
            self.process = subprocess.Popen([*self.command, "--serve", "--parent-pid", str(os.getpid())],
                                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                                            env={**os.environ, "PYTHONUNBUFFERED": "1", "SW_MCP_INSTANCE": self.instance})
        except OSError as exc:
            self.state = "Stopped"
            self.log(f"Could not start server: {exc}")
            return
        threading.Thread(target=self._read_logs, args=(self.process,), daemon=True).start()
        threading.Thread(target=self._wait_ready, args=(self.process,), daemon=True).start()

    def _read_logs(self, process):
        with process.stdout:
            for line in process.stdout:
                self.log(line)
        code = process.wait()
        self.log(f"Server exited (code {code}).")
        if self.process is process:
            self.state = "Stopped"

    def _wait_ready(self, process):
        deadline = time.monotonic() + 30
        while self.process is process and self.state == "Starting" and process.poll() is None:
            try:
                record = running_connection()
                if record["instance"] != self.instance:
                    raise ValueError("Another server owns the listener")
                # PyInstaller one-file bootloader is the Popen PID; its Python child owns the host.
                self.record = record
                if self.state == "Starting":
                    self.state = "Running"
                    self.log("Ready. Connect or restart your MCP client.")
                return
            except ValueError:
                if time.monotonic() > deadline:
                    self.log("Startup timed out. See the server error above.")
                    self.stop()
                    return
                time.sleep(0.15)

    def stop(self):
        if self.state in ("Stopped", "Stopping"):
            return
        self.state = "Stopping"
        threading.Thread(target=self._stop, args=(self.process, self.record), daemon=True).start()

    def _stop(self, process, record):
        if process is None:
            self.state = "Stopped"
            return
        if record:
            with contextlib.suppress(OSError, ValueError):
                request(record, "/shutdown", method="POST")
        try:
            process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            self.log("Stopping the server process after the shutdown timeout.")
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
            else:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        if self.process is process:
            self.state = "Stopped"
