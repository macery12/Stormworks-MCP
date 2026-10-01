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
- `swhull/`: `hull` (shape, boxes, scale), `build` (spec resolution, patches, colours, summary),
  `smooth` (skin + wedge fit), `interior`, `paint`, `jobs` (heavy tool work in a child process the
  server kills on cancel or timeout), `pieces` (geometry and rotations), `vehicle`
  (XML), `render`, `definitions` (game install detection).
- `swhull/guide.md` is served to Claude by `hull_design_guide`; keep it in sync with the spec.
- Wedge fit (`smooth.py`): after changing it, render the calibration shapes (1:1, 1:2, 1:4 hip
  roofs must come out in Wedge, Wedge 1x2, Wedge 1x4) and a few presets. `tests/test_smooth.py`
  guards the piece catalogue against the game files, symmetry, spike tips and watertightness.
- Never commit game files (`rom/`), users' vehicles, or saved designs.
