"""How the server runs: an MCP client starts it hidden over stdio and stops it when it closes.

Every running copy (one per client) appends to the same log file, tagging each line with the
client that started it, so a player can send one file when something goes wrong.
"""

import contextlib
import logging
import os
import sys
import threading
import time
from pathlib import Path

from ._version import __version__

LOG = logging.getLogger("stormworks.runtime")
# log.txt moves to log.old.txt once it passes this size, so it never grows without bound.
LOG_LIMIT = 5 * 1024 * 1024
# How many lines a server writes between size checks.
ROLL_CHECK_EVERY = 200
# The client that started this server, from its MCP initialize request.
CLIENT = {"name": "starting"}


def data_dir():
    """Logs and update state; SW_MCP_DATA_DIR overrides %LOCALAPPDATA%\\Stormworks MCP."""
    if os.environ.get("SW_MCP_DATA_DIR"):
        return Path(os.environ["SW_MCP_DATA_DIR"])
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "Stormworks MCP"


def log_path():
    return data_dir() / "logs" / "log.txt"


class _ClientTag(logging.Filter):
    def filter(self, record):
        record.client = CLIENT["name"]
        return True


class SharedLogFile(logging.FileHandler):
    """Appends to log.txt alongside the other running servers. Whoever finds it over the
    limit moves it to log.old.txt; Windows refuses the move while another server has the
    file open, and that server tries again later."""

    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lines = 0
        _roll(path)
        super().__init__(path, mode="a", encoding="utf-8")

    def emit(self, record):
        super().emit(record)
        self.lines += 1
        if self.lines % ROLL_CHECK_EVERY == 0:
            self.acquire()
            try:
                if _size(self.baseFilename) > LOG_LIMIT:
                    if self.stream:
                        self.stream.close()
                        self.stream = None
                    _roll(Path(self.baseFilename))
            finally:
                self.release()


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _roll(path):
    if _size(path) <= LOG_LIMIT:
        return
    # Fails while another server has it open; that server rolls the file later.
    with contextlib.suppress(OSError):
        os.replace(path, path.with_name("log.old.txt"))


def configure_logging():
    """Log to stderr (clients keep their own copy) and to the shared log.txt."""
    formatter = logging.Formatter("%(asctime)s %(client)s[%(process)d] %(levelname)s %(name)s: %(message)s")
    handlers = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    try:
        handlers.append(SharedLogFile(log_path()))
    except OSError as exc:
        if sys.stderr is not None:
            print(f"Stormworks MCP cannot write {log_path()}: {exc}", file=sys.stderr)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(_ClientTag())
        root.addHandler(handler)
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


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


def _windows_parents():
    """{pid: parent pid} for every process, from a Toolhelp snapshot."""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    parents = {}
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return parents
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        ok = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            ok = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return parents


def _windows_image(pid):
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value
    finally:
        kernel.CloseHandle(handle)


def client_pid():
    """The process that started this server. A venv's python.exe is a launcher plus a child
    running the same executable; skip such layers and watch the client above them."""
    pid = os.getppid()
    if sys.platform != "win32":
        return pid
    me = os.path.normcase(os.path.abspath(sys.executable))
    parents = None
    for _ in range(4):
        image = _windows_image(pid)
        if image is None or os.path.normcase(os.path.abspath(image)) != me:
            return pid
        parents = parents if parents is not None else _windows_parents()
        if not parents.get(pid):
            return pid
        pid = parents[pid]
    return pid


def _leave(reason):
    LOG.info("Server stopped (%s)", reason)
    logging.shutdown()
    # The stdin reader thread cannot be cancelled, so a normal exit could wait on it forever.
    os._exit(0)


def run_stdio(mcp=None):
    """Serve MCP over stdin/stdout until the client closes the pipe or exits."""
    import anyio  # noqa: PLC0415
    import mcp_types  # noqa: PLC0415

    configure_logging()
    if mcp is None:
        from server import mcp  # noqa: PLC0415
    from . import updates  # noqa: PLC0415

    async def initialized(ctx, _params):
        info = ctx.session.client_params.client_info if ctx.session.client_params else None
        if info is not None:
            CLIENT["name"] = info.name
            LOG.info("Connected to %s %s", info.name, info.version)

    mcp._lowlevel_server.add_notification_handler("notifications/initialized", mcp_types.NotificationParams,
                                                  initialized)
    CLIENT["name"] = "client"
    parent = client_pid()
    LOG.info("Stormworks MCP %s started by process %s (%s)", __version__, parent, sys.executable)
    # A client that dies without closing our stdin (another process still holds the pipe)
    # would leave this server running; leave when the client process is gone.
    threading.Thread(target=_watch_parent, args=(parent, lambda: _leave("client exited")),
                     daemon=True, name="client watcher").start()
    updates.check_in_background()
    try:
        anyio.run(mcp.run_stdio_async)
    except Exception:
        LOG.exception("Server failed")
        logging.shutdown()
        os._exit(1)
    _leave("client disconnected")
