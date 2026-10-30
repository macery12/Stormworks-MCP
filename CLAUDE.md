# Notes for AI coding assistants

MCP server (Python, `mcp` SDK 2.x `MCPServer`, managed with uv) that designs Stormworks boats and
writes vehicle XML. Humans: start with [README.md](README.md).

## Commands

```bash
uv sync
uv run pytest            # must pass; engine tests skip without a Stormworks install
uv run ruff check .      # must pass
uv run tools/smoke_test.py out   # renders every preset to ./out; look at the PNGs after geometry changes
```

## Rules learned in game (do not regress)

These were each found by loading generated files in Stormworks; tests guard them.

- **Always write `r`** on every component. A missing `r` is not identity; the game applies a
  different default rotation.
- **`world = Mᵀ · local`**, with `r` read row-major as M. `pieces.r_attr` / `parse_r` handle it.
- **Paint every surface in `sc`.** `x` means unpainted, not "same as the previous surface".
- **The game's axes are left-handed.** The renderers negate x for display; keep that when
  adding views.
- Never cut the hull skin below the main deck (doors and hatches in `interior.py` check this).
  A propeller hub or rudder plate may replace the blocks it sits in; nothing is left open.
- **A symmetric hull gets a mirror-image skin**, and a sharp stem ends on a three-wide nose
  (wedge, block, wedge), never a one-wide stub (from the player's hand fix of "Slim
  Speedboat"; `tests/test_symmetry.py`).
- **Engines go inside the hull below the deck; propellers and rudders stay inside the hull's
  outline** (hub in the transom with only the blades aft, rudder plate in the bottom row, never
  past the transom). Air comes in through a deck fluid port, exhaust leaves through the transom
  above the propeller. Exposed pipes are colour-coded by contents; pipes inside blocks keep the
  hull colour (from the player's fix of "Mini Speedboat"; `tests/test_powertrain.py`).

## Testing reality

The game is the only real test. You cannot run Stormworks, so after a geometry change, render
it (`inspect_view`, `tools/smoke_test.py`), look at the image yourself, and give the human a
specific in-game check. [docs/in-game-testing.md](docs/in-game-testing.md) lists what is
verified.

## Layout

- `server.py`: tools. Expected failures raise `ValueError`/`OSError`, which `_user_errors` turns
  into `ToolError` so the model sees the message. Any tool that builds or renders must be
  `async` and go through `jobs.run_job`: a build in a sync tool runs in a thread that cannot be
  stopped, and on big ships it outlived the client's timeout and stalled every later call.
  Every tool declares MCP annotations and describes every parameter (shared ones live in
  `swhull/tool_params.py`); its docstring opens with a verb, names the sibling to use instead
  where two could be confused, and says what it writes and returns. Glama grades these
  definitions (TDQS); `npx mcp-tdqs lint --command "uv run server.py"` checks them without a key.
- `swhull/`: `hull` (shape, boxes, scale), `build` (spec resolution, patches, colours, summary),
  `smooth` (skin + wedge fit), `habits` (veteran finishing: box chamfers, ballast, railings),
  `interior`, `powertrain` (inset propellers/rudders, engine room layout, engine size),
  `pipe_colours`, `telemetry` (in-game engine logger microcontroller; tools/engine_test_boats.py,
  tools/telemetry_logger.py),
  `paint` (paint items), `faces` (which `sc` colour paints which face), `liveries` (named paint
  schemes), `jobs` (heavy tool work in a child process the server kills on cancel or
  timeout), `pieces` (geometry and rotations), `vehicle` (XML), `render` (framing, overlays,
  flat painting), `raster` (lit rendering: GPU or CPU rasterizing, one shared NumPy lighting
  pass), `definitions` (game install detection).
- `swhull/guide.md` is served to Claude by `hull_design_guide`; keep it in sync with the spec.
- Wedge fit (`smooth.py`): after changing it, render the calibration shapes (1:1, 1:2, 1:4 hip
  roofs must come out in Wedge, Wedge 1x2, Wedge 1x4) and a few presets. `tests/test_smooth.py`
  guards the piece catalogue against the game files, symmetry, spike tips and watertightness.
- Never commit game files (`rom/`), users' vehicles, or saved designs.
- Do not add `Co-Authored-By` lines or other AI attribution to commit messages or PR descriptions.
