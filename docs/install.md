# Install and set up

Stormworks MCP runs on the same Windows PC as Stormworks and your AI client. You can install it
(recommended), use the portable zip, or run it from source. In every case your AI client starts
the server by itself in the background when it opens and stops it when it closes. There is no
window to keep open and nothing to start first.

## What you need

- Windows 10 or 11 (x64).
- Stormworks: Build and Rescue installed through Steam. The server reads part definitions from
  your install; it never changes game files.
- An MCP client on the same PC: Claude Desktop, the ChatGPT / Codex Windows app, Codex CLI or
  the Codex IDE extension, or any other client that can launch a local MCP server.

## Installer

The download includes Python and every dependency. You do not need Python, uv or Git.

1. Close your AI client.
2. Open [Releases](https://github.com/macery12/Stormworks-MCP/releases/latest) and download the
   installer (the file ending in `-setup.exe`).
3. Run it. By default it installs for you only and needs no admin rights; choose all users on
   the first page if you want that (asks for admin). If it finds Claude Desktop or Codex, it
   offers to add itself to them. Keep those ticked.
4. Open your AI client. It starts Stormworks MCP by itself.

If you skipped that step or use another client, open **Stormworks MCP** from the Start menu.
It opens a small menu:

```
  1  Add to Claude Desktop (not set up)
  2  Add to ChatGPT / Codex (not set up)
  3  Open the log
  4  Check for updates
  5  Exit
```

Close the client, type its number and confirm. Your other client settings are kept and the
file is backed up first. Then open the client again.

### Portable zip

Download the `-portable.zip`, extract it into a folder you will keep (for example
`Documents\Stormworks MCP`) and double-click `stormworks-mcp.exe` inside it for the same menu.
The client entry records where the folder is; if you move it, open the menu again and add it
again.

### Upgrading

Close your AI clients, then run a newer installer over the old one: it finds the existing
install and offers to upgrade or repair it in place (same folder, same client entries) or to
uninstall it. Client entries from v0.3 keep working; you do not need to set them up again.

The server checks GitHub for a newer release at most once a day. When there is one, your AI
tells you, with the download link. Nothing installs by itself. **Check for updates** in the menu
asks straight away; set `SW_MCP_NO_UPDATE_CHECK=1` to turn the check off.

If your client still has an older Stormworks entry that you added by hand (one that runs
`server.py` or an extension), remove it. Two entries for the same server give the AI two copies
of every tool.

### Other clients

The client should start `stormworks-mcp.exe` with the argument `--stdio`. From a terminal in the
install folder, print the exact configuration:

```powershell
.\stormworks-mcp.exe --config json | Out-String      # MCP JSON
.\stormworks-mcp.exe --config toml | Out-String      # Codex TOML
.\stormworks-mcp.exe --config command | Out-String   # codex mcp add command
.\stormworks-mcp.exe --doctor | Out-String           # check paths and game assets
```

The same configuration serves Codex CLI and the IDE extension on that PC. ChatGPT on the web and
cloud tasks connect differently and are not set up by this app; see
[OpenAI's MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=app). To check that a
download was built from this repository, see [verify a download](releases.md#verify-a-download).

## Run from source

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), which installs Python
and the dependencies for you.

```bash
git clone https://github.com/macery12/Stormworks-MCP.git
cd Stormworks-MCP
uv sync --locked
```

Open the setup menu from the repository root, or print the configuration for this checkout:

```powershell
uv run python launcher.py                    # the setup menu
uv run python launcher.py --config json      # MCP JSON
uv run python launcher.py --config toml      # Codex TOML
uv run python launcher.py --config command   # codex mcp add command
uv run python launcher.py --doctor           # check paths and game assets without changing files
```

For Claude Desktop by hand, open **Settings > Developer > Edit Config** and add a `stormworks`
entry under `mcpServers`, using the folder you cloned into:

```json
{
  "mcpServers": {
    "stormworks": {
      "command": "C:\\path\\to\\Stormworks-MCP\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\Stormworks-MCP\\launcher.py", "--stdio"]
    }
  }
}
```

Quit and reopen the client after changing its configuration: for Claude Desktop, right-click the
tray icon and choose **Quit**; in the ChatGPT / Codex app, check the entry under
**Settings > MCP servers** and restart its connection.

## Check that it works

Start a new chat and ask:

> List the Stormworks hull presets.

The assistant should call `list_hull_presets` and list the hull archetypes. If the tool is
missing:

- Check the server entry in your client (Claude: **Settings > Developer**; ChatGPT / Codex:
  **Settings > MCP servers**), or open the menu and add it again. Then fully quit and reopen the
  client.
- Read the log: menu option 3, or `%LOCALAPPDATA%\Stormworks MCP\logs\log.txt`. Every server
  writes there, each line tagged with the client that started it. Send this file with a bug
  report.
- Run `--doctor` to see which game folder and vehicles folder the server found.

## Configuration

A standard Windows and Steam install needs no configuration. To override a default, set these
environment variables (in the client's server entry under `env`, or for your Windows account):

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
| `SW_MCP_DATA_DIR` | `%LOCALAPPDATA%\Stormworks MCP` | The log (`logs\log.txt`) and the remembered update check. |
| `SW_MCP_NO_UPDATE_CHECK` | unset | Set to `1` to skip the daily update check. |

Without game definitions, plain blocks, slopes and structural editing still work. Installed
parts need definitions: automatic fit-out reports what it skipped, and a seal check that meets
unknown part geometry reports the result as indeterminate.
