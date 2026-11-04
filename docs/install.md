# Install and set up

Stormworks MCP runs on the same Windows PC as Stormworks and your AI client. You can install the
desktop app (recommended) or run it from source. Either way, one shared server runs in the
desktop window and every client connects to it.

## What you need

- Windows 10 or 11 (x64).
- Stormworks: Build and Rescue installed through Steam. The server reads part definitions from
  your install; it never changes game files.
- An MCP client on the same PC: Claude Desktop, the ChatGPT / Codex Windows app, Codex CLI or
  the Codex IDE extension, or any other client that can launch a local MCP server.

## Desktop app

The download includes Python and every dependency. You do not need Python, uv or Git.

1. Open [Releases](https://github.com/macery12/Stormworks-MCP/releases/latest) and download the
   installer (the file ending in `-setup.exe`). If you would rather not install anything, take
   the portable `.exe` instead and keep it in a permanent folder.
2. Run the installer. By default it installs for you only and needs no admin rights; choose
   all users on the first page if you want that (asks for admin). If it finds Claude Desktop or
   Codex, it offers to add itself to them.
3. Open **Stormworks MCP** from the Start menu and press **Start server**.
4. Restart your AI client.

If the installer did not add the server to your client, close the client, open
**MCP > Set up Claude Desktop** or **MCP > Set up ChatGPT / Codex** in the app, check the
configuration path it shows, and press **Add to client**. Your other client settings are kept
and the file is backed up first. Tick the replacement checkbox to replace an existing
`stormworks` entry.

Keep the window open while you build. Closing it stops the server and disconnects every client;
after you start it again, reconnect or restart your client. A second copy of the app refuses to
start.

### Upgrading

Run a newer installer over the old one: it finds the existing install and offers to upgrade or
repair it in place (same folder, same client entries) or to uninstall it. The app checks GitHub
for a newer release when it starts and shows a download link when there is one (**Help > Check
for updates**; untick **Check for updates at startup** to turn it off).

If your client still has an older Stormworks entry that you added by hand (one that runs
`server.py`, an extension, or an old portable EXE), remove it first. Two entries for the same
server fight over the connection.

The portable EXE records its own location in each client entry. If you move it, open it again
and replace its client entries from the **MCP** menu.

### Other clients

**MCP > Custom client / raw configuration** copies MCP JSON, Codex TOML or a PowerShell add
command. The same configuration serves Codex CLI and the IDE extension on that PC. ChatGPT on
the web and cloud tasks connect differently and are not set up by this app; see
[OpenAI's MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=app).

The **View** menu shows diagnostics and lets you copy or clear the log. To check that a download
was built from this repository, see [verify a download](releases.md#verify-a-download).

## Run from source

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), which installs Python
and the dependencies for you.

```bash
git clone https://github.com/macery12/Stormworks-MCP.git
cd Stormworks-MCP
uv sync --locked
```

Open the desktop window from the repository root, set up your client from the **MCP** menu, and
press **Start server**:

```powershell
uv run python launcher.py
```

To configure a client yourself, print the exact configuration for this checkout:

```powershell
uv run python launcher.py --config json      # MCP JSON
uv run python launcher.py --config toml      # Codex TOML
uv run python launcher.py --config command   # codex mcp add command
uv run python launcher.py --doctor           # check paths and game assets without changing files
```

For Claude Desktop, open **Settings > Developer > Edit Config** and add a `stormworks` entry
under `mcpServers`, using the folder you cloned into:

```json
{
  "mcpServers": {
    "stormworks": {
      "command": "C:\\path\\to\\Stormworks-MCP\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\Stormworks-MCP\\launcher.py", "--connect"]
    }
  }
}
```

`--connect` relays to the running desktop server and never starts one, so keep the window open
with the server running. Quit and reopen the client after changing its configuration: for
Claude Desktop, right-click the tray icon and choose **Quit**; in the ChatGPT / Codex app, check
the entry under **Settings > MCP servers** and restart its connection.

## Check that it works

Start a new chat and ask:

> List the Stormworks hull presets.

The assistant should call `list_hull_presets` and list the hull archetypes. If the tool is
missing:

- Check that the desktop window says the server is running, and read its log.
- Check the server entry in your client (Claude: **Settings > Developer**; ChatGPT / Codex:
  **Settings > MCP servers**) and restart the client.
- Run `--doctor` (from source) or **View > Diagnostics** (desktop app) to see which game folder
  and vehicles folder the server found.

## Configuration

A standard Windows and Steam install needs no configuration. To override a default, set these
environment variables before starting the desktop app:

| Variable | Default | Used for |
| --- | --- | --- |
| `SW_VEHICLES_DIR` | `%APPDATA%\Stormworks\data\vehicles` | Where vehicles are read and saved. |
| `SW_GAME_DIR` | Found through your Steam libraries | Stormworks install, for part definitions and workbench locations. |
| `SW_DEFINITIONS_DIR` | `<game>\rom\data\definitions` | Part definitions directly. |
| `SW_WORKSHOP_DIR` | Found through your Steam libraries | Installed workshop vehicles used as references. |
| `SW_DESIGNS_DIR` | `%APPDATA%\stormworks-hull-mcp\designs` | Stored designs and drafts. |
| `SW_PREFABS_DIR` | `prefabs` next to the designs folder | Prefab side files. |
| `SW_TOOL_TIMEOUT` | `300` | Seconds a build or render may run before the server stops it. |
| `SW_BUILD_CACHE` | `1` | Set to `0` to turn off geometry caching. |
| `SW_BUILD_CACHE_DIR` | `%TEMP%\stormworks-mcp-builds` | Shared geometry cache. |
| `SW_RENDERER` | `auto` | Preview lighting: `auto` (GPU, else CPU), `gpu`, `cpu`, or `flat` (unlit, fastest). |
| `SW_MCP_PORT` | `38473` | Loopback port of the shared desktop server (1024 to 65535). |
| `SW_MCP_RUNTIME_DIR` | `%LOCALAPPDATA%\stormworks-hull-mcp\runtime` | Runtime files of the shared desktop server. |
| `SW_MCP_NO_UPDATE_CHECK` | unset | Set to `1` to skip the update check at startup. |

Without game definitions, plain blocks, slopes and structural editing still work. Installed
parts need definitions: automatic fit-out reports what it skipped, and a seal check that meets
unknown part geometry reports the result as indeterminate.
