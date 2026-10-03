"""Desktop entry point and quiet client connector, sharing one GUI-owned MCP server."""

if __name__ == "__main__":
    # PyInstaller workers re-enter this executable. Dispatch them before argparse or GUI imports.
    import multiprocessing

    multiprocessing.freeze_support()


def main():
    import argparse  # noqa: PLC0415
    import json  # noqa: PLC0415

    from swhull._version import __version__  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Stormworks MCP server and client setup")
    parser.add_argument("--version", action="version", version=__version__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--setup", action="store_true", help="open the desktop window (also the default)")
    mode.add_argument("--connect", action="store_true", help="connect MCP stdio to the running desktop server")
    mode.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument("--gui-smoke", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument("--config", choices=("json", "toml", "command"), help="print client configuration")
    mode.add_argument("--doctor", action="store_true", help="report runtime paths without modifying files")
    parser.add_argument("--parent-pid", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.config:
        from swhull.client_config import raw_config  # noqa: PLC0415

        print(raw_config(args.config))
    elif args.doctor:
        from swhull.diagnostics import runtime_status  # noqa: PLC0415

        print(json.dumps(runtime_status(), indent=2))
    elif args.serve:
        from swhull.desktop_runtime import run_server  # noqa: PLC0415

        run_server(args.parent_pid)
    elif args.connect:
        import anyio  # noqa: PLC0415

        from swhull.desktop_runtime import bridge  # noqa: PLC0415

        try:
            anyio.run(bridge)
        except Exception as exc:  # noqa: BLE001 - never open a GUI or write an error onto MCP stdout
            import sys  # noqa: PLC0415

            print(f"Stormworks MCP connection failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
    else:
        from swhull.setup_gui import main as desktop  # noqa: PLC0415

        desktop(smoke=args.gui_smoke)


if __name__ == "__main__":
    main()
