Title: Stormworks MCP v0.3.1: your AI client starts the server by itself

---

> **Upgrading from v0.3.0?** Close your AI clients and run the new installer; it upgrades in
> place. Your existing Claude Desktop and ChatGPT / Codex entries keep working, so there is
> nothing to set up again. The Stormworks MCP window is gone: you no longer open anything or
> press Start before building.

## Highlights

- **No more "Start server".** Claude Desktop, ChatGPT / Codex or any other MCP client now starts
  Stormworks MCP by itself in the background when it opens, and stops it when it closes. Opening
  the client before anything else works; there is no window to keep open.
- **No console window.** Nothing flashes up when your client starts the server.
- **Faster start.** The server starts about ten times faster, so clients no longer give up while
  it loads.
- **One log file.** Every server writes to `%LOCALAPPDATA%\Stormworks MCP\logs\log.txt`, each line
  marked with the client that started it. Send this file with a bug report.
- **Updates through your AI.** Once a day the server checks for a newer release. When there is
  one, your AI tells you and gives you the download link. Nothing installs by itself.

## Setting up

- The installer still offers to add Stormworks MCP to Claude Desktop and ChatGPT / Codex.
- Open **Stormworks MCP** from the Start menu (or double-click `stormworks-mcp.exe`) for a small
  menu: add it to Claude Desktop or ChatGPT / Codex, open the log, check for updates.
- The portable version is now a zip (`-portable.zip`). Extract it into a folder you will keep and
  double-click `stormworks-mcp.exe` to add it to your client.

## Other changes

- Two AI clients can be open at once; each gets its own server, and they never overwrite each
  other's designs.
- Removed: the desktop window, its Start / Stop buttons, the single-file portable EXE, and the
  `SW_MCP_PORT` and `SW_MCP_RUNTIME_DIR` settings. New: `SW_MCP_DATA_DIR` moves the log folder.
- Windows only: Linux is no longer tested or supported.

## Downloads

- `stormworks-mcp-0.3.1-windows-x64-setup.exe`: the installer (recommended).
- `stormworks-mcp-0.3.1-windows-x64-portable.zip`: portable, no install.
- `SHA256SUMS.txt`, `build-info.json` and `provenance.sigstore.json` let you verify that a
  download was built from this repository.
