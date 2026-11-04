"""What a player sees after double-clicking the EXE: a short text menu, since the AI client
starts the server by itself and nothing has to stay open."""

import os
import sys
import webbrowser

from ._version import __version__
from .client_config import add_client, configured, default_config_path
from .runtime import log_path
from . import updates

CLIENTS = (("claude", "Claude Desktop"), ("codex", "ChatGPT / Codex"))
STATE = {"yes": "set up", "other": "set up for another copy", "no": "not set up"}


def _ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return None


def _yes(prompt, default=True):
    answer = _ask(f"{prompt} [{'Y/n' if default else 'y/N'}] ")
    if answer is None:
        return False
    return default if not answer else answer.lower().startswith("y")


def set_up(client, label):
    try:
        path = default_config_path(client)
    except ValueError as exc:
        print(f"  {exc}")
        return
    state = configured(client)
    print(f"\n  {label} settings: {path}")
    if state == "yes":
        print(f"  {label} already starts this copy of Stormworks MCP.")
        if not _yes("  Write the entry again anyway?", default=False):
            return
    elif state == "other":
        print(f"  {label} is set up for a different copy of Stormworks MCP. This replaces it.")
    print(f"  Close {label} completely first (for Claude: right-click its tray icon, Quit).")
    if not _yes("  Continue?"):
        return
    try:
        target, backup = add_client(client, replace=True)
    except (OSError, ValueError) as exc:
        print(f"  Could not update {label}: {exc}")
        return
    print(f"  Done. Updated {target}")
    if backup:
        print(f"  Your previous settings are backed up in {backup}")
    print(f"  Open {label} and ask: \"Read the Stormworks start guide, then build me a small boat.\"")


def open_log():
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
    except OSError as exc:
        print(f"  Could not create {path}: {exc}")
        return
    print(f"\n  {path}")
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - opens the log in the player's text editor


def check_updates():
    print("\n  Asking GitHub...")
    try:
        found = updates.latest()
        updates.remember(found)
    except (OSError, ValueError) as exc:
        print(f"  Could not reach GitHub: {exc}")
        return
    if not updates.newer(found["version"]):
        print(f"  {__version__} is the latest version.")
        return
    print(f"  Stormworks MCP {found['version']} is available (you have {__version__}).")
    print("  Close your AI clients, run the new installer (it upgrades in place), then reopen them.")
    if _yes("  Open the download page?"):
        webbrowser.open(found["url"])


def main():
    while True:
        print(f"\nStormworks MCP {__version__}\n")
        print("  Your AI client starts this server in the background by itself.")
        print("  You never need to keep this window open.\n")
        for number, (client, label) in enumerate(CLIENTS, 1):
            print(f"  {number}  Add to {label} ({STATE[configured(client)]})")
        print("  3  Open the log")
        print("  4  Check for updates")
        print("  5  Exit\n")
        choice = _ask("Choose 1-5: ")
        if choice is None or choice in ("5", "q", "exit"):
            return
        if choice in ("1", "2"):
            set_up(*CLIENTS[int(choice) - 1])
        elif choice == "3":
            open_log()
        elif choice == "4":
            check_updates()
        else:
            print("  Type a number from 1 to 5.")
