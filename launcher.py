"""Entry point of the EXE. An MCP client starts it hidden with --stdio and talks over stdin and
stdout; double-clicking it opens a short console menu for client setup, the log and updates.

The packaged EXE is a windowed program, so no client ever flashes a console window. It opens a
console of its own only for the menu, and attaches to the caller's console for CLI output.
"""

if __name__ == "__main__":
    # PyInstaller workers re-enter this executable. Dispatch them before argparse or other imports.
    import multiprocessing

    multiprocessing.freeze_support()


def _stdin_is_stream():
    """True when a client (or a test) handed us a pipe or file as stdin, so it wants the server."""
    import sys  # noqa: PLC0415

    if sys.stdin is None:
        return False
    import ctypes  # noqa: PLC0415

    kernel = ctypes.WinDLL("kernel32")
    kernel.GetStdHandle.restype = ctypes.c_void_p
    handle = kernel.GetStdHandle(-10)  # STD_INPUT_HANDLE
    if not handle or handle == ctypes.c_void_p(-1).value:
        return False
    kernel.GetFileType.argtypes = (ctypes.c_void_p,)
    return kernel.GetFileType(handle) in (1, 3)  # FILE_TYPE_DISK, FILE_TYPE_PIPE


def _console(new):
    """Give a windowed EXE a console: a new window for the menu, or the terminal that started
    it for CLI output. Does nothing when the streams already work (source runs, redirection)."""
    import sys  # noqa: PLC0415

    if sys.stdout is not None and (not new or sys.stdin is not None):
        return
    import ctypes  # noqa: PLC0415

    kernel = ctypes.WinDLL("kernel32")
    if kernel.GetConsoleWindow():
        pass
    elif new:
        kernel.AllocConsole()
        kernel.SetConsoleTitleW("Stormworks MCP")
    elif not kernel.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
        return
    sys.stdout = sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")  # noqa: SIM115
    if new:
        sys.stdin = open("CONIN$", encoding="utf-8", errors="replace")  # noqa: SIM115


def main():
    import argparse  # noqa: PLC0415
    import json  # noqa: PLC0415
    import sys  # noqa: PLC0415

    from swhull._version import __version__  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Stormworks MCP server")
    parser.add_argument("--version", action="version", version=__version__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--stdio", action="store_true",
                      help="run the MCP server over stdin/stdout (what AI clients start)")
    # v0.3 client entries ran --connect; it now starts the server the same way.
    mode.add_argument("--connect", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument("--menu", action="store_true", help="open the setup menu (also what a double-click does)")
    mode.add_argument("--setup", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument("--config", choices=("json", "toml", "command"), help="print client configuration")
    mode.add_argument("--doctor", action="store_true", help="report runtime paths without modifying files")
    mode.add_argument("--add-client", choices=("claude", "codex"),
                      help="add this EXE to a client's MCP settings (the installer uses this)")
    parser.add_argument("--replace", action="store_true",
                        help="with --add-client: replace an existing Stormworks entry (a backup is kept)")
    serve = "--stdio" in sys.argv[1:] or "--connect" in sys.argv[1:] or (len(sys.argv) == 1 and _stdin_is_stream())
    if serve:
        parser.parse_args()  # rejects unknown arguments before the server starts
        from swhull.runtime import run_stdio  # noqa: PLC0415

        run_stdio()
        return
    menu = len(sys.argv) == 1 or bool({"--menu", "--setup"} & set(sys.argv[1:]))
    _console(new=menu)
    args = parser.parse_args()
    if args.config:
        from swhull.client_config import raw_config  # noqa: PLC0415

        print(raw_config(args.config))
    elif args.add_client:
        from swhull.client_config import add_client  # noqa: PLC0415

        try:
            target, backup = add_client(args.add_client, replace=args.replace)
        except (OSError, ValueError) as exc:
            print(f"Could not set up {args.add_client}: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"Configured {target}; backup: {backup or 'new file'}")
    elif args.doctor:
        from swhull.diagnostics import runtime_status  # noqa: PLC0415

        print(json.dumps(runtime_status(), indent=2))
    else:
        from swhull.console_menu import main as menu_main  # noqa: PLC0415

        menu_main()


if __name__ == "__main__":
    main()
