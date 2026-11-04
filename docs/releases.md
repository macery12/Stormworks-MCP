# Windows builds and releases

The GitHub workflow builds the Windows server, its portable zip and its Inno Setup installer from a tag in
this repository, using locked dependencies. It uploads both with checksums and signed build
provenance. There is no locally supplied binary input.

## Publish a version

1. Update `pyproject.toml` and `swhull/_version.py` to the same `MAJOR.MINOR.PATCH` version.
   Run `uv lock` and include the lockfile.
2. Commit the reviewed implementation, tests and workflows. Keep your release-description
   draft separate if you do not want it committed.
3. Push that commit, then create and push its tag:

   ```powershell
   git tag v0.3.0
   git push origin v0.3.0
   ```

   `v0.3` is also accepted for version `0.3.0`. A version mismatch fails packaging.
4. Watch **Actions > Tagged release**. After successful checks, open the draft under
   **Releases**, paste the release description and publish it.

The workflow uses the repository's `GITHUB_TOKEN`; no personal access token is needed.
Artifact attestations work for public repositories on current GitHub plans; private
repositories require an eligible plan. See [GitHub's attestation action](https://github.com/actions/attest).
If organization policy prevents the workflow permissions, the release job fails visibly.
Re-running a failed release can replace assets on its draft. Published releases cannot
be replaced by this workflow; publish a new tag/version for a changed executable.

## What CI checks

- Ruff and portable tests on Linux/Python 3.10, Linux/Python 3.12 and Windows/Python 3.12.
- Two source clients, each starting its own server over stdio (one through a v0.3 `--connect`
  entry), and one with no arguments at all: initialization, guides, parallel calls,
  worker-rendered PNG, cache reuse, XML export, invalid-spec errors, the shared design lock, log
  lines tagged by client, and no server left running after its client dies.
- The console menu: exit, and adding Claude Desktop to stand-in client settings.
- A Windows x64 windowed folder build (Python, NumPy, Pillow, MCP and docs) and the same smoke
  against it, from a path with spaces. Client settings are never changed by the smoke.
- The installer: a silent per-user install into a path with spaces, the Start menu shortcut,
  an upgrade over two servers clients left running, and uninstall.
- Tag/version agreement, checksums and signed GitHub build attestations.

Push/PR CI also builds the Windows EXE after tests. **Actions > CI > Run workflow** produces
downloadable artifacts without creating a release. Tests isolate logs, update state,
vehicles, designs and caches in temporary folders.

## Download assets

| Asset | Description |
| --- | --- |
| `stormworks-mcp-<version>-windows-x64-setup.exe` | Installer: per-user by default, all users optional (admin); upgrades, repairs or uninstalls an existing install |
| `stormworks-mcp-<version>-windows-x64-portable.zip` | Portable: extract anywhere; double-click `stormworks-mcp.exe` for the setup menu |
| `build-info.json` | Version, source commit/tag, runtime, entry point and lockfile digest |
| `SHA256SUMS.txt` | SHA256 digests of the installer, the zip and build metadata |
| `provenance.sigstore.json` | GitHub's signed bundle tying the uploaded bytes to the workflow/tag |

The installer and the portable zip are the user downloads; the other files provide source-build
verification. Neither bundles game assets.

The installer puts the server in `%LOCALAPPDATA%\Programs\Stormworks MCP` (per user, no admin) or
`Program Files\Stormworks MCP` (all users, admin), or a folder you choose, and adds a Start menu
shortcut. Running a newer installer finds the earlier install and offers upgrade/repair (same
folder, same client entries) or uninstall. It closes running copies first: servers clients
started (those clients lose their tools until restarted) and the setup menu. Uninstall
(Settings > Apps) removes the program and shortcut and keeps designs, prefabs, logs and client
settings. Silent installs take Inno Setup's usual switches,
for example `/VERYSILENT /CURRENTUSER` or `/ALLUSERS`.

Extract the portable zip into a permanent folder and double-click `stormworks-mcp.exe` to add
it to your client. Moving the folder requires adding it again from the menu. Deleting the
folder preserves designs, vehicles and client settings; remove its client entry when you no
longer use it.

Attestations establish build origin. Windows Authenticode signing is not configured yet.
Local rebuilds can differ byte-for-byte; the claim is a traceable source build rather than
reproducible binary identity.

## Client set-up from the installer

When it finds Claude Desktop (`%APPDATA%\Claude`) or Codex (`CODEX_HOME` or `%USERPROFILE%\.codex`),
the installer offers "Add to ..." tasks, ticked on a first install. Each runs
`stormworks-mcp.exe --add-client claude|codex --replace` as the user who started setup, which
replaces an existing `stormworks` entry and keeps a timestamped backup. Tell users upgrading from
an older version to remove their old Stormworks MCP entry (and any `server.py` or extension
setup) before adding the new one. Silent installs select tasks with `/TASKS=` or `/MERGETASKS=`.

## Update check

A running server asks `api.github.com/repos/macery12/Stormworks-MCP/releases/latest` at most
once a day, in the background (no user data is sent), and keeps the answer in
`%LOCALAPPDATA%\Stormworks MCP\update.json`. When that published release is newer, the server
instructions, `get_guide(topic="start")` and `get_runtime_status` carry a one-line note with the
download link, so the AI tells the player; the line is also written to the log. Nothing
installs itself. Drafts and pre-releases are never offered. The menu's **Check for updates**
asks at once. `SW_MCP_NO_UPDATE_CHECK=1` disables the check, and so does having unticked v0.3's
**Check for updates at startup**.

## winget

CI writes winget manifests for the assembled installer (`tools/winget_manifest.py`, artifact
`winget-manifests`): package `macery12.StormworksMCP`, per-user and all-users installers, and
switches that skip client set-up (winget installs silently). After publishing a release,
submit them to [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs):

```powershell
winget validate --manifest .\0.3.0
wingetcreate submit --token <personal access token> .\0.3.0
```

The first submission is reviewed by the winget maintainers; later versions update the same
package. The manifests point at the release asset URL, so generate them from the exact
installer the release uploads.

## Verify a download

From the folder containing the download:

```powershell
Get-FileHash .\stormworks-mcp-0.3.0-windows-x64-setup.exe -Algorithm SHA256
gh attestation verify .\stormworks-mcp-0.3.0-windows-x64-setup.exe --repo macery12/Stormworks-MCP
```

Compare the hash with `SHA256SUMS.txt`. Compare the verified commit/ref with the intended
release tag and review the Actions run. See [GitHub's verification guide](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-artifact-attestations).

## Build locally

From the repository root on Windows:

```powershell
uv sync --locked --group build
uv run --group build python tools/build_windows.py
uv run python tools/package_test.py --exe dist/stormworks-mcp/stormworks-mcp.exe
uv run python tools/build_installer.py      # Inno Setup 6: winget install JRSoftware.InnoSetup
uv run python tools/installer_test.py       # refuses to run over a real install
uv run python tools/release_assets.py --tag v0.3.0 --commit local
```

Python packages are resolved by `uv.lock`. GitHub actions are pinned to commits and maintained
by Dependabot. The EXE is a windowed program, so a client starting it never shows a console;
it opens a console of its own only for the double-click menu.
Keep `dist/release` empty before assembling a new release; assembly refuses to mix old and
new assets. Build output is ignored by Git. Do not commit game assets or user designs.

## How clients run the server

Client settings start `stormworks-mcp.exe --stdio` (v0.3 entries with `--connect` do the same).
The server speaks MCP over stdin and stdout and exits when the client closes the pipe, or when
the client process disappears without closing it. Opening order never matters and nothing has
to be started first. With no arguments, the EXE serves MCP when stdin is a pipe and opens the
setup menu otherwise.

Each client gets its own server. They share the game paths, the geometry cache and the stored
designs; an OS lock on `<designs>\.lock` keeps two servers from writing designs at the same time
(and is released if a server crashes).

Every server appends to `%LOCALAPPDATA%\Stormworks MCP\logs\log.txt`, each line tagged with the
name the client gave and the process ID. Past 5 MB the file moves to `log.old.txt`. Servers also
log to stderr, which clients keep in their own logs. `SW_MCP_DATA_DIR` moves the log and update
state elsewhere (tests use it).
