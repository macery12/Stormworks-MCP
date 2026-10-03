"""Portable desktop controller; importing this module does not initialize Tk."""

import json
import queue
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from ._version import __version__
from .client_config import add_client, default_config_path, raw_config, server_entry
from .desktop_runtime import InstanceLock, ServerController, port
from .diagnostics import runtime_status


class DesktopApp:
    def __init__(self, window, controller=None):
        self.window = window
        self.controller = controller if controller is not None else ServerController()
        self.closing = False
        self.dialogs = {}
        window.title(f"Stormworks MCP {__version__}")
        window.geometry("880x560")
        window.minsize(640, 400)
        window.protocol("WM_DELETE_WINDOW", self.close)

        menu = tk.Menu(window)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Exit", command=self.close)
        menu.add_cascade(label="File", menu=file_menu)
        mcp_menu = tk.Menu(menu, tearoff=False)
        mcp_menu.add_command(label="Set up Claude Desktop...", command=lambda: self.client_setup("claude"))
        mcp_menu.add_command(label="Set up ChatGPT / Codex...", command=lambda: self.client_setup("codex"))
        mcp_menu.add_separator()
        mcp_menu.add_command(label="Custom client / raw configuration...", command=self.configuration)
        menu.add_cascade(label="MCP", menu=mcp_menu)
        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_command(label="Copy logs", command=self.copy_logs)
        view_menu.add_command(label="Clear logs", command=self.clear_logs)
        view_menu.add_separator()
        view_menu.add_command(label="Diagnostics...", command=lambda: self.configuration(diagnostics=True))
        menu.add_cascade(label="View", menu=view_menu)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="About", command=lambda: messagebox.showinfo(
            "Stormworks MCP", f"Stormworks MCP {__version__}\nLocal vehicle-building tools for Stormworks.\n"
            "MIT license. Unofficial fan project.\n\nUse MCP > Set up to connect your client, then press Start.", parent=window))
        menu.add_cascade(label="Help", menu=help_menu)
        window.configure(menu=menu)

        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Stormworks MCP", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Set up clients from the MCP menu. Start the shared server before connecting.",
                  wraplength=810).pack(anchor="w", pady=(6, 12))
        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        self.start_button = ttk.Button(controls, text="Start server", command=self.controller.start)
        self.start_button.pack(side="left", padx=(0, 8))
        self.stop_button = ttk.Button(controls, text="Stop server", command=self.controller.stop)
        self.stop_button.pack(side="left", padx=(0, 16))
        self.status = tk.StringVar(value="Stopped")
        ttk.Label(controls, textvariable=self.status, font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Label(frame, text=f"Local endpoint: http://127.0.0.1:{port()}/mcp", foreground="#555555").pack(anchor="w", pady=8)

        log_frame = ttk.LabelFrame(frame, text="Server logs", padding=8)
        log_frame.pack(fill="both", expand=True, pady=(4, 8))
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap="word", height=14, font=("Consolas", 10),
                                                state="disabled", background="#171d26", foreground="#e0e7ef")
        self.log_text.pack(fill="both", expand=True)
        ttk.Label(frame, text="One server for all clients. Closing this window stops the server and disconnects clients.",
                  wraplength=810).pack(anchor="w")
        self.controller.log(f"Stormworks MCP {__version__} ready to start.")
        self.controller.log(f"Executable: {server_entry()['command']}")
        self._poll()

    def _append(self, line):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 2000:
            self.log_text.delete("1.0", f"{lines - 2000}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll(self):
        for _ in range(200):
            try:
                self._append(self.controller.logs.get_nowait())
            except queue.Empty:
                break
        state = self.controller.state
        self.status.set(state)
        self.start_button.configure(state="normal" if state == "Stopped" and not self.closing else "disabled")
        self.stop_button.configure(state="normal" if state in ("Starting", "Running") and not self.closing else "disabled")
        if self.closing and state == "Stopped":
            self.window.destroy()
            return
        self.window.after(150, self._poll)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.controller.log("Closing window; stopping the shared server...")
        self.controller.stop()

    def copy(self, content):
        self.window.clipboard_clear()
        self.window.clipboard_append(content)

    def copy_logs(self):
        self.copy(self.log_text.get("1.0", "end-1c"))

    def clear_logs(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _dialog(self, key, title, geometry):
        previous = self.dialogs.get(key)
        if previous and previous.winfo_exists():
            previous.lift()
            previous.focus_set()
            return None
        dialog = tk.Toplevel(self.window)
        self.dialogs[key] = dialog
        dialog.title(title)
        dialog.geometry(geometry)
        dialog.transient(self.window)
        return dialog

    def client_setup(self, client):
        label = "Claude Desktop" if client == "claude" else "ChatGPT / Codex Windows app"
        dialog = self._dialog(client, f"Set up {label}", "760x350")
        if dialog is None:
            return
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"Connect {label}", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Close the client before updating its settings, then restart it.\n"
                  "The client connects to this window's server; it never starts another server.",
                  wraplength=710).pack(anchor="w", pady=10)
        try:
            default_path = str(default_config_path(client))
        except ValueError:
            default_path = ""
        path = tk.StringVar(value=default_path)
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=6)
        ttk.Entry(row, textvariable=path).pack(side="left", fill="x", expand=True, padx=(0, 8))

        def browse():
            chosen = filedialog.asksaveasfilename(parent=dialog, title="Choose the client's configuration file",
                                                 initialfile="claude_desktop_config.json" if client == "claude" else "config.toml",
                                                 confirmoverwrite=False)
            if chosen:
                path.set(chosen)

        ttk.Button(row, text="Browse", command=browse).pack(side="left")
        replace = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Replace existing Stormworks entry (keep a backup)", variable=replace).pack(anchor="w", pady=8)
        ttk.Label(frame, text=f"Executable: {server_entry()['command']}", wraplength=710).pack(anchor="w", pady=6)

        def add():
            try:
                chosen = path.get().strip()
                if not chosen:
                    raise ValueError("Choose a config file first")
                target, backup = add_client(client, chosen, replace=replace.get())
            except (OSError, ValueError) as exc:
                messagebox.showerror("Could not add server", str(exc), parent=dialog)
                return
            self.controller.log(f"Configured {label}: {target}")
            messagebox.showinfo("Server added", f"Updated {target}\nBackup: {backup or 'new file'}\n\n"
                                "Press Start in Stormworks MCP, then restart the client.\n"
                                "Ask: List the Stormworks hull presets.", parent=dialog)

        ttk.Button(frame, text="Add to client", command=add).pack(anchor="e", pady=8)

    def configuration(self, diagnostics=False):
        dialog = self._dialog("config", "Configuration and diagnostics", "850x560")
        if dialog is None:
            return
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Keep this EXE in a permanent folder. After moving it, update your client entry.\n"
                  "These commands connect to the shared server. Keep the desktop window open and press Start.",
                  wraplength=800).pack(anchor="w", pady=(0, 8))
        notebook = ttk.Notebook(frame)
        notebook.pack(fill="both", expand=True)
        for label, content in (("MCP JSON", raw_config("json")), ("Codex TOML", raw_config("toml")),
                               ("PowerShell command", raw_config("command")),
                               ("Diagnostics", json.dumps(runtime_status(), indent=2))):
            tab = ttk.Frame(notebook, padding=8)
            notebook.add(tab, text=label)
            text = scrolledtext.ScrolledText(tab, wrap="word", font=("Consolas", 10))
            text.pack(fill="both", expand=True)
            text.insert("1.0", content)
            text.configure(state="disabled")
            ttk.Button(tab, text="Copy", command=lambda value=content: self.copy(value)).pack(anchor="e", pady=(6, 0))
        if diagnostics:
            notebook.select(3)


def _smoke(app):
    """Drive the packaged GUI itself during Windows CI; callers isolate runtime folders."""
    stage, deadline = 0, time.monotonic() + 50
    errors = []

    def advance():
        nonlocal stage
        try:
            if time.monotonic() > deadline:
                raise TimeoutError("Packaged GUI smoke timed out")
            if stage == 0:
                app.client_setup("claude")
                app.client_setup("codex")
                app.configuration()
                for dialog in app.dialogs.values():
                    dialog.withdraw()
                app.start_button.invoke()
                stage = 1
            elif stage == 1 and app.status.get() == "Running":
                app.stop_button.invoke()
                stage = 2
            elif stage == 2 and app.status.get() == "Stopped":
                app.start_button.invoke()
                stage = 3
            elif stage == 3 and app.status.get() == "Running":
                app.close()
                return
        except Exception as exc:  # noqa: BLE001 - propagate Tk callback failures to CI after cleanup
            errors.append(exc)
            app.close()
            return
        app.window.after(50, advance)

    app.window.after(50, advance)
    return errors


def main(smoke=False):
    window = tk.Tk()
    window.withdraw()
    lock = InstanceLock("desktop")
    try:
        lock.acquire()
    except (OSError, ValueError) as exc:
        messagebox.showinfo("Stormworks MCP", str(exc), parent=window)
        window.destroy()
        return
    try:
        app = DesktopApp(window)
        errors = _smoke(app) if smoke else []
        if not smoke:
            window.deiconify()
        window.mainloop()
        if errors:
            raise errors[0]
        if smoke:
            print("Packaged GUI smoke passed: Tk, setup menus, raw config, Start, Stop, restart and close-stop")
    finally:
        lock.close()
