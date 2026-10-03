# Project audit: 2026-10-02

Scope: repository architecture, hull/vehicle building workflow, model guidance, local setup,
portable tests and Windows release delivery. This review does not simulate Stormworks or
claim new in-game verification.

## Findings and changes

| Priority | Finding / evidence | Result |
| --- | --- | --- |
| High | The repository had test CI but no desktop app, frozen entry point or tag release workflow (`pyproject.toml`, `.github/workflows/ci.yml`). Users needed Git, uv and manual config. | Added a source-built portable desktop EXE with MCP setup menus, shared-server controls/logs, reusable build CI and draft release uploads. |
| High | `jobs.run_job` uses multiprocessing spawn. A frozen entry point without early `freeze_support` can recursively re-enter startup. | Added an early hook in `launcher.py` and verified preview/export workers over the packaged MCP transport. |
| High | Shape parameters were merged without rejecting unknown keys. For example `{"lenght": 8}` retained the default length without an error (`build.resolve_spec`, `hull.validate`). Malformed nested containers could raise internal exceptions. | Added actionable typo suggestions for root/hull-shape groups, container preflight and rejection of nonfinite numbers, with regressions. |
| Medium | `hull_design_guide` returned roughly 26 KB on every read; staged material was described in separate repository docs. Models connected to an installed binary cannot follow local repo links automatically. | Added focused guide topics and direct retrieval of the building, staged and testing references, bundled offline. Kept no-argument compatibility. |
| Medium | Cross-tool guidance mixed units and workflows deep in a long initialization message. Current OpenAI guidance calls for a useful first 512 characters. | Moved bench choice, preview-before-save, units, revisions, separate imported copies and uncertainty into the opening instructions. |
| Medium | Clients could cancel at their default timeout before the server's 300-second worker deadline. Save/game-definition locations were difficult to diagnose. | Codex setup config sets a 300-second tool timeout; added `get_runtime_status` and `--doctor`. Other clients may need their own timeout settings. |
| Medium | Cache keys hashed loose Python sources; that assumption is fragile in frozen packaging and across upgrades (`cache.key`). | Added the release version to cache identity. Packaged smoke checks reuse across preview and export workers. |
| Medium | Quick-add could damage user settings or point at a temporary extraction path. | Client config uses the final `sys.executable` with `--connect`, preserves unrelated servers/options and TOML comments, makes unique backups, refuses invalid config and requires opt-in replacement. |
| Medium | Each stdio client normally starts a separate server. Start/Stop in a desktop app would not control those servers. | Both client entries launch connectors to one authenticated loopback host. Only the GUI starts it. OS-held locks prevent duplicate windows/hosts; closing the GUI stops its host. |
| Medium | Existing CI checked only Python 3.12 despite declaring Python >=3.10. Binary startup and GUI controls were untested. | Added the minimum supported Python, source/frozen two-client protocol smoke, and packaged Tk Start/Stop/restart/close tests from a path with spaces. |
| Medium | A downloadable binary without origin evidence does not demonstrate a source build. | Added commit-pinned actions, locked build dependencies, release checksums, build metadata and signed GitHub provenance. |

## What is already strong

The builder separates parametric geometry, shells/slopes, runtime definitions, interior
planning, exact editing, sealing and export. Heavy operations run in cancellable child
processes. Generated geometry has a bounded JSON/NumPy cache with atomic publication.
Exact edits are batched and revision-checked; imported originals receive separate draft
exports. Access assemblies are checked before cutting openings, and invalid custom tanks
cannot be exported. Local synthetic fixtures cover many mounting, reflection, orientation,
attachment and XML preservation regressions.

The baseline lint passed and the baseline suite reported **1,265 passed, 1 skipped** on this
Windows/Python 3.12 workspace. Installed-game and reference coverage depends on local assets
and environment; passing portable tests is not proof of game physics or every catalogue entry.

## Recommended next work

1. **Build planning and explanation.** Add a compact structured plan/report of stages,
   automatic selections, skipped requests and the next useful fix. Summaries currently
   contain valuable evidence mostly in prose (`build.summary`, `components`, `access`).
   Keep geometric validation distinct from operating readiness; define acceptance criteria
   on a small tug before broadening the planner.
2. **Complete schema coverage.** Root/shape typo checks now help, but complex room, box,
   component and edit dictionaries remain only partly described by MCP `dict` schemas.
   Publish versioned JSON schemas or typed request models with nested ranges, examples and
   migration rules. Reject or explain unsupported nested options consistently.
3. **Human in-game validation.** Run the staged calibration vehicles through attachment,
   doors/hatches, tank fill, sealing and rudder/propeller behavior. Record observations with
   game version and reference evidence. The current docs identify those as unverified.
4. **Performance from measured profiles.** Re-run `tools/staged_builder_test.py --benchmark`
   on representative big room layouts. Reports/rendering repeatedly expand footprints into
   Python voxel lists; cache decoding and render startup remain costs. Optimize from fresh
   measurements while preserving exact XML and seal results.
5. **Installed catalogue/reference CI.** Continue the synthetic portable suite, then add
   an opt-in local/private runner for licensed game assets and explicit reference vehicles.
   Never distribute the game definitions with the executable.
6. **Windows distribution polish.** Add Authenticode signing when a publisher certificate
   is available, test upgrades and setup in actual Claude Desktop and ChatGPT/Codex.
   Test Windows ARM64 separately before claiming native support.

## Verification boundaries

Local checks cover source/frozen two-client protocol startup, config preservation/backups,
MCP workers and guide assets, duplicate host refusal, request authentication, logs and
shutdown. GUI tests exercise real Tk menus/dialogs, Start/Stop/restart and close-to-stop;
CI repeats those against the portable EXE from a path with spaces. A hosted Actions run,
GitHub attestation issuance and actual Claude/ChatGPT UI activation require the
committed/pushed workflow and client interaction; those must not be inferred from local tests.

After the desktop changes, the local suite reported **1,319 passed, 1 skipped**, Ruff passed, and
Actionlint 1.7.12 accepted all workflows. The README structural audit passed; its paragraph
length warning applies to existing lists/tables rather than a long prose paragraph.

The first release is Windows x64, with stdio client connectors to a shared local HTTP host.
Wire/plumb and verify your finished
vehicle in game. See [building](building.md), [release operations](releases.md),
[advanced testing](advanced-testing.md) and [the in-game checklist](in-game-testing.md).
