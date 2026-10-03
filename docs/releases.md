# Windows builds and releases

The GitHub workflow builds the portable desktop EXE from a tag in this repository, using
locked dependencies. It uploads that actual executable with checksums and signed build
provenance. There is no installer or locally supplied binary input.

## Publish a version

1. Update `pyproject.toml` and `swhull/_version.py` to the same `MAJOR.MINOR.PATCH` version.
   Run `uv lock` and include the lockfile. Version 0.1.0 is already set.
2. Commit the reviewed implementation, tests and workflows. Keep your release-description
   draft separate if you do not want it committed.
3. Push that commit, then create and push its tag:

   ```powershell
   git tag v0.1.0
   git push origin v0.1.0
   ```

   `v0.1` is also accepted for version `0.1.0`. A version mismatch fails packaging.
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
- Two source client connectors against one shared host: initialization, guides, parallel
  calls, worker-rendered PNG, cache reuse, XML export, invalid-spec errors and shutdown.
- Duplicate-host refusal and a clear stopped-server error without a client spawning a host.
- A Windows x64 one-file desktop executable with Python, NumPy, Pillow, MCP, Tk and docs.
- The same protocol smoke against that frozen executable.
- Real Tk menu/dialog construction and Start, Stop, restart and close-stop controls against
  a copy of the EXE in a path with spaces. Client settings are never changed by the smoke.
- Tag/version agreement, checksums and signed GitHub build attestations.

Push/PR CI also builds the Windows EXE after tests. **Actions > CI > Run workflow** produces
downloadable artifacts without creating a release. Tests isolate runtime discovery,
vehicles, designs and caches in temporary folders.

## Download assets

| Asset | Description |
| --- | --- |
| `stormworks-mcp-<version>-windows-x64.exe` | Double-click for the GUI; `--connect` is the quiet client connector |
| `build-info.json` | Version, source commit/tag, runtime, entry point and lockfile digest |
| `SHA256SUMS.txt` | SHA256 digests of the executable and build metadata |
| `provenance.sigstore.json` | GitHub's signed bundle tying the uploaded bytes to the workflow/tag |

The single EXE is the user download; the other files provide source-build verification.
It has no install/uninstall step or bundled game assets. Keep it in a permanent folder,
use **MCP > Set up** for your client and press **Start server**. Closing the window stops
the server. Moving the EXE requires updating its path in each client through the setup menu.
Deleting the EXE preserves designs, vehicles and client settings; remove its client entry
when you no longer use it.

Attestations establish build origin. Windows Authenticode signing is not configured yet.
Local rebuilds can differ byte-for-byte; the claim is a traceable source build rather than
reproducible binary identity.

## Verify a download

From the folder containing the downloaded executable:

```powershell
Get-FileHash .\stormworks-mcp-0.1.0-windows-x64.exe -Algorithm SHA256
gh attestation verify .\stormworks-mcp-0.1.0-windows-x64.exe --repo macery12/Stormworks-MCP
```

Compare the hash with `SHA256SUMS.txt`. Compare the verified commit/ref with the intended
release tag and review the Actions run. See [GitHub's verification guide](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-artifact-attestations).

## Build locally

From the repository root on Windows:

```powershell
uv sync --locked --group build
uv run --group build python tools/build_windows.py
uv run python tools/package_test.py --exe dist/stormworks-mcp.exe
uv run python tools/desktop_test.py --exe dist/stormworks-mcp.exe
uv run python tools/release_assets.py --tag v0.1.0 --commit local
```

Python packages are resolved by `uv.lock`. GitHub actions are pinned to commits and maintained
by Dependabot. The EXE hides its console when opening the GUI while preserving stdio for MCP.
Keep `dist/release` empty before assembling a new release; assembly refuses to mix old and
new assets. Build output is ignored by Git. Do not commit game assets or user designs.

## Shared server behavior

The GUI starts one authenticated Streamable HTTP server on `127.0.0.1:38473`. Client settings
launch the same EXE with `--connect`; that small process relays stdio to the existing host
and cannot launch another host. Both clients use this connector so the authentication token
is never copied into their configuration. Each client has its own protocol session, while
the host, tools, design locks and game paths are shared.

OS-held locks prevent duplicate GUI/host instances for the same Windows user. Closing the
GUI requests shutdown, waits for the host, and terminates its own process tree if necessary.
A parent-lifetime watcher also stops the host if the GUI process disappears unexpectedly.
Logs remain in the window for the current session and can be copied through **View**.
Tokens and authenticated headers are not printed in the log panel.

The connection record and locks live under `%LOCALAPPDATA%\stormworks-hull-mcp\runtime`;
tokens change at every Start and the record is removed on normal shutdown. Local requests
require the token and a matching loopback Host/Origin. The connector bypasses HTTP proxies.
Runtime diagnostics show the endpoint and directories without exposing the token.

Advanced/test overrides are `SW_MCP_RUNTIME_DIR` and `SW_MCP_PORT` (1024–65535). Both the
desktop app and connectors must use the same runtime directory. The default port must be
free; an occupied port produces an error in the logs rather than silently switching hosts.

Older `server.py`/extension configurations start independent servers. Close those clients,
remove duplicate extensions and replace their Stormworks entry through the new setup menu
before using this shared mode. After Stop/Start, reconnect or restart clients to establish
new sessions.
