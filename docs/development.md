# Development

How to work on Stormworks MCP itself. To use it, see the [README](../README.md) and the
[install guide](install.md).

## Set up and check

```bash
uv sync --locked                  # install locked dependencies, including pytest and ruff
uv run pytest                     # unit tests; engine tests skip when the game is not installed
uv run ruff check .               # lint
```

Changes must pass lint and tests. The game is the only real test of a vehicle, so a change to
geometry also needs a rendered review and a specific in-game check (see
[CLAUDE.md](../CLAUDE.md) and [in-game testing](in-game-testing.md)).

## Other checks

```bash
uv run tools/smoke_test.py out    # build and render every hull preset, blocks and wedges, into ./out
uv run tools/client_test.py       # drive the server over MCP stdio, like a desktop client does
uv run tools/staged_builder_test.py out/staged-builder --benchmark
uv run tools/diagnostic_milestone.py out/diagnostic-review   # fault, repair and validation export
uv run python tools/package_test.py   # two clients, shared host, guide assets, workers, export and stop
```

Tool definitions are graded by Glama (TDQS). Check them without an API key:

```bash
npx mcp-tdqs lint --command "uv run server.py"
```

## README images

Every image in the README is a render, made by [tools/readme_images.py](../tools/readme_images.py):

```bash
uv run tools/readme_images.py                     # all of them, into docs/images
uv run tools/readme_images.py out/readme hero     # one image, somewhere else
```

Run it after a change that alters how vehicles look, open each PNG, and commit the ones that
changed. Some images need game definitions (the Humvee, the engines and the diagnostics).

## Windows builds

Build the portable desktop executable and the installer (needs Inno Setup 6:
`winget install JRSoftware.InnoSetup`):

```powershell
uv sync --locked --group build
uv run --group build python tools/build_windows.py
uv run python tools/package_test.py --exe dist/stormworks-mcp.exe
uv run python tools/desktop_test.py --exe dist/stormworks-mcp.exe
uv run python tools/build_installer.py
uv run python tools/installer_test.py   # refuses to run over a real install
```

Pushing a version tag (`vX.Y.Z`) runs the tests, builds and tests the executable and installer,
and uploads them to a draft GitHub release with checksums and signed build provenance. See
[releases](releases.md).

## Layout

| Path | Contents |
| --- | --- |
| [server.py](../server.py) | MCP tool definitions |
| [launcher.py](../launcher.py) | Desktop app entry point and the `--connect` client relay |
| [swhull/hull.py](../swhull/hull.py), [presets.py](../swhull/presets.py) | Hull spec to solid voxels; the hull archetypes |
| [swhull/smooth.py](../swhull/smooth.py), [habits.py](../swhull/habits.py) | Watertight skin and slope-piece fitting; veteran finishing (chamfers, ballast, railings) |
| [swhull/paint.py](../swhull/paint.py), [liveries.py](../swhull/liveries.py), [faces.py](../swhull/faces.py) | Paint items, named paint schemes, per-face colours |
| [swhull/interior.py](../swhull/interior.py), [access.py](../swhull/access.py) | Decks, rooms and doorways; complete doors and hatches |
| [swhull/components.py](../swhull/components.py), [powertrain.py](../swhull/powertrain.py), [tanks.py](../swhull/tanks.py) | Component fit-out; propellers, rudders and engine rooms; block-built tanks |
| [swhull/modular.py](../swhull/modular.py), [engine_builder.py](../swhull/engine_builder.py) | Modular engine couplings and checks; engine layouts |
| [swhull/prefabs.py](../swhull/prefabs.py), [bodies.py](../swhull/bodies.py) | Reusing vehicles inside vehicles; multi-body vehicles |
| [swhull/land_build.py](../swhull/land_build.py), [land_presets.py](../swhull/land_presets.py) | Land chassis and presets |
| [swhull/networks.py](../swhull/networks.py), [routing.py](../swhull/routing.py) | Typed wiring and preflight; pipe routing |
| [swhull/repairs.py](../swhull/repairs.py), [assemblies.py](../swhull/assemblies.py), [validation.py](../swhull/validation.py) | Repair suggestions, control assemblies and in-game test records |
| [swhull/editing.py](../swhull/editing.py), [drafts.py](../swhull/drafts.py) | Transactional part edits and lossless imports |
| [swhull/seal.py](../swhull/seal.py) | Compartment air connectivity |
| [swhull/physics.py](../swhull/physics.py), [game_constants.py](../swhull/game_constants.py) | Read-only physics estimates and the base-game constants they use |
| [swhull/style.py](../swhull/style.py) | Optional style rule sets checked by `preflight_vehicle(style=...)` |
| [swhull/pieces.py](../swhull/pieces.py), [vehicle.py](../swhull/vehicle.py) | Piece geometry and the rotation convention; vehicle XML |
| [swhull/render.py](../swhull/render.py), [raster.py](../swhull/raster.py), [meshes.py](../swhull/meshes.py) | Preview framing and overlays; lit GPU/CPU rendering; installed part meshes |
| [swhull/definitions.py](../swhull/definitions.py), [benches.py](../swhull/benches.py) | Game install detection, part definitions and workbench sizes |
| [swhull/jobs.py](../swhull/jobs.py), [cache.py](../swhull/cache.py) | Killable worker processes; shared geometry cache |
| [swhull/setup_gui.py](../swhull/setup_gui.py), [desktop_runtime.py](../swhull/desktop_runtime.py) | Desktop window and shared server |
| [docs/start.md](start.md), [swhull/guide.md](../swhull/guide.md) | Guides served by `get_guide` (any vehicle; hull generator) |
| [viewer/](../viewer) | Standalone 3D viewer |
| [tools/](../tools) | Smoke, client, package and desktop tests; in-game calibration vehicles; README images |

## How it works

A hull spec describes a continuous shape: plan-view taper, keel rise, sections with deadrise and
bilge radius, sheer, and superstructure. The server voxelizes that shape at 0.25 m per block,
hollows it to a watertight skin, adds interior structure, and can skin it with slope pieces.
Once stored, any design (hull, land, empty or imported) can be changed part by part: the editing,
connection and repair tools apply revision-checked batches with undo. The result is written as
Stormworks vehicle XML. Previews are drawn in Python from the same geometry, using the installed
part meshes.

Heavy builds and renders run in a child process that the server stops when a call is cancelled or
exceeds `SW_TOOL_TIMEOUT`, so one slow ship cannot stall later calls.
[Vehicle file format](vehicle-format.md) documents the XML, including the details that are easy
to get wrong: a missing `r` attribute is not the identity rotation, `x` in the paint string
means unpainted, and the game's axes are left-handed.

## Design notes

[Feature requests and bugs](feature-requests.md), [project audit](project-audit.md),
[hull smoothing research](hull-smoothing-research.md) and
[surface design plan](surface-design-plan.md).
