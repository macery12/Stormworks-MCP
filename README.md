# Stormworks MCP: AI boat designer

Describe a boat and Claude designs it for [Stormworks: Build and Rescue](https://store.steampowered.com/app/573090/).
This [MCP](https://modelcontextprotocol.io) server gives Claude tools to shape a hull, add
superstructure and interior rooms, check its work in rendered previews, and save the result as
a vehicle file you load from any workbench. The game itself is never modified.

![Preview of a 50 m battleship designed with this server: 3/4 views from above and below, front, side and top](docs/images/preview-battleship.png)

## What you can do

- **Design hulls from a description.** Claude sets naval-architecture parameters (length, beam,
  deadrise, bow shape, sheer, flare) and starts from 10 archetypes, such as a runabout, trawler,
  tug, patrol boat or catamaran.
- **Build detailed superstructure.** Boxes, cylinders, domes and lattice masts, angled with
  pitch and yaw, mirrored to both sides or repeated in rows, and stacked on each other by name.
  Add a bulbous bow, skegs, and paint: hull numbers, deck markings and painted panels.
- **Work at real-world scale.** Enter a real ship's dimensions with `scale: "1:4"`.
- **Build in stages.** Hull → structure → core parts → access → propulsion parts → custom
  block-built tanks. Preview and save after any stage.
- **Fit real parts.** Select batteries by footprint, fit a helm or compact seat, and install
  manual doors, complete hatch/ladder assemblies, propellers and rudders.
- **Edit individual blocks or whole regions.** Batch edits, preview before committing, undo,
  and work on a separate draft of an existing single-body vehicle.
- **Check seals independently.** Trace compartment leaks through finished blocks, slopes and
  supported component surfaces, with a highlighted escape path.
- **Review before loading.** Every change comes back as a picture that Claude critiques and
  refines. Claude can also point a camera at any detail, or open the boat in a 3D viewer in your
  browser.
- **Load it in game.** The server writes the vehicle XML into your Stormworks vehicles folder.
  Hulls are plain blocks by default. Optional fit-out places parts; you add wiring and plumbing.

## Quick start

### Prerequisites

- Windows with Stormworks installed through Steam (tested on Windows 11).
- [Claude Desktop](https://claude.ai/download).
- [uv](https://docs.astral.sh/uv/getting-started/installation/), the Python package manager.
  uv installs Python and the dependencies for you.

### 1. Get the code

```bash
git clone https://github.com/macery12/Stormworks-MCP.git
cd Stormworks-MCP
uv sync
```

### 2. Add the server to Claude Desktop

In Claude Desktop, open **Settings > Developer > Edit Config**. That opens
`claude_desktop_config.json`. Add a `stormworks-hulls` entry under `mcpServers`, using the folder
you cloned into:

```json
{
  "mcpServers": {
    "stormworks-hulls": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\path\\to\\Stormworks-MCP", "server.py"]
    }
  }
}
```

If Claude Desktop reports that it cannot find `uv`, replace `"uv"` with the full path, which is
usually `C:\\Users\\<you>\\.local\\bin\\uv.exe`.

### 3. Restart Claude Desktop

Quit Claude Desktop completely: right-click the tray icon and choose **Quit**. Then open it again.

### 4. Check that it works

Start a new chat and ask:

> List the Stormworks hull presets.

Claude calls `list_hull_presets` and lists 10 archetypes, from `runabout` to `barge`. If the tool
is missing, open **Settings > Developer**, which shows the server's status and error log.

### 5. Design a boat and load it

Ask for a boat, for example:

> Design me a chunky fishing boat for bench size S. Show me a preview, then save it.

Claude reads the design guide, previews and refines the hull, then saves it. In Stormworks, open
a workbench, choose **Load**, and pick the name Claude gave it.

## Example prompts

- "Give me three different 10 m rescue boat hulls and show them side by side."
- "Take the tugboat preset but make it longer and sleeker, like a pilot boat."
- "Add an interior: engine room aft with a large engine, crew quarters amidships, and a bridge."
- "Look at my vehicle 'Old Trawler' and design a new hull in the same style."
- "Try it with wedge smoothing" or "open it in the viewer".
- "Build the tugboat through the propulsion stage, show every automatic choice, then save it."
- "Import Old Trawler into a draft, repaint the bridge, and save a separate copy."
- "Add a block-built diesel tank, check its enclosure, and show the outlet and vent connections."

## Features

### Design loop

Claude previews each version, compares it against your brief, and adjusts. This battleship took
four passes:

![Four 3/4 previews of the same battleship: bare hull, first superstructure, tower and turrets, final](docs/images/battleship-iterations.png)

### Interior design

Rooms are built from plain blocks: floors, bulkheads, walls, and legacy 0.75 m × 2 m doorways.
The access stage installs actual manual frames wherever the complete frame fits; failed access
requests leave the wall or floor sealed. `preview_interior` shows a section down the centreline and a labelled plan of
every level. It also reports each room's clear size, floor width, headroom and doors, and warns
when something does not fit, such as an engine too tall for its room.

Vertical access requests leave floors sealed until a complete ladder/hatch assembly can be
installed. The tool never cuts an unfinished square hole for the player to fill later.

![Interior cutaway of the battleship: a centreline section with 20 labelled rooms and six deck plans](docs/images/interior-battleship.png)

### Close-up inspection

`inspect_view` renders any angle and zoom level, so Claude can check details the fixed previews
hide:

![Close-up of the battleship superstructure showing doorways](docs/images/inspect-closeup.png)

### Optional wedge smoothing

With `smoothing: "wedges"`, the hull is skinned with the game's whole slope catalogue: Wedge
1x1/1x2/1x4, and Pyramid and Inverse Pyramid in 1x1, 1x2, 1x4, 2x2, 2x4 and 4x4. Every piece is
tried in every rotation and scored on how well its surface follows the hull: the right volume, and
faces that point the way the hull does, so steps, spikes and zigzags lose to clean slopes. A face
sloping two ways is laid the way players build it, a pyramid stacked on an inverse pyramid of the
same size, repeated, and a slope that stops dead against blocks costs extra, so lone pyramids
with hard edges are rare. Sharp edges such as deck edges and box corners stay crisp, painted areas
stay blocks, and the skin stays watertight. This mode is still being checked in game (see [In-game testing](docs/in-game-testing.md)).

![A fishing boat hull smoothed with wedges](docs/images/preview-fishing-boat-wedges.png)

### 3D viewer

[viewer/index.html](viewer/index.html) is a standalone browser viewer for any vehicle file, yours or
generated. You can orbit, switch views, toggle outlines and a 1 m grid, and save a screenshot.
Claude can open it for you with `open_in_viewer`. It loads three.js from a CDN, so it needs
internet access.

![The 3D viewer showing the battleship](docs/images/viewer.png)

## Tools

The [staged builder guide](docs/staged-builder.md) covers precise block/region editing,
safe imports, undo, the installed-part catalogue, and geometry caching. New tools:

- **search_parts / get_part_definition**: installed footprints and surfaces.
- **import_vehicle / preview_vehicle / save_vehicle**: safe drafts of existing vehicles.
- **query_parts / edit_parts / undo_edits**: individual parts, regions, batches and undo.
- **check_seal**: independent compartment connectivity and highlighted escape paths.

Generated specs can also include **components** and optional **fitout** stages. The builder
selects batteries by available footprint, fits helms/seats, and places real propellers/rudders
with mounting and clearance checks. See the staged builder guide for units and overrides.

| Tool | What it does |
| --- | --- |
| `hull_design_guide` | Returns the design guide Claude reads first: workflow, spec reference, archetype proportions, interior rules ([swhull/guide.md](swhull/guide.md)). |
| `list_workbenches` | Bench size keywords (S, M, L, XL, XXL, MAX) and where each is in your game, read from the game files and tile mods such as Echo's Bigger Workbenches. |
| `list_hull_presets`, `get_hull_spec` | Lists the 10 archetypes; returns a full spec to start from. |
| `preview_hull` | Builds a spec and returns 5 views plus size, part count and a starter-workbench fit check. |
| `preview_interior` | Returns a cutaway section and labelled deck plans, with a per-room report including door sills and floor steps. |
| `inspect_view` | Renders one view from any angle and zoom, of a design or a saved vehicle, with metre rulers on straight-on views. Can highlight one named box. |
| `deck_profile` | Lists deck height, default box height and deck half-beam every metre along the hull. |
| `save_hull` | Writes the vehicle into the Stormworks vehicles folder. Never overwrites a vehicle it did not create. |
| `store_design` | Keeps a spec on the server so later parametric hull calls send only a JSON patch. |
| `list_designs`, `load_design` | Reopens designs stored earlier. |
| `list_game_vehicles`, `preview_game_vehicle` | Browses and renders your existing vehicles. |
| `open_in_viewer` | Opens a vehicle or unsaved design in the 3D viewer in your browser. |

## Configuration

Nothing needs configuring on a standard Windows and Steam install. These environment variables
override the defaults:

| Variable | Default | Used for |
| --- | --- | --- |
| `SW_VEHICLES_DIR` | `%APPDATA%\Stormworks\data\vehicles` | Where vehicles are read and saved. |
| `SW_GAME_DIR` | Found through your Steam libraries | Stormworks install, for part definitions and workbench locations. Workshop tile mods are found through Steam. |
| `SW_DEFINITIONS_DIR` | `<game>\rom\data\definitions` | Part definitions directly. |
| `SW_DESIGNS_DIR` | `%APPDATA%\stormworks-hull-mcp\designs` | Saved design specs. |
| `SW_TOOL_TIMEOUT` | `300` | Seconds a preview or save may run before the server stops it. |
| `SW_BUILD_CACHE` | `1` | Set to `0` to disable geometry caching. |
| `SW_BUILD_CACHE_DIR` | System temp / `stormworks-mcp-builds` | Shared cache, bounded to 20 entries / 512 MiB. |

Without game definitions, procedural blocks/slopes and structural editing work. Installed
components need definitions; automatic fit-out reports skipped placements. Unsupported
component sealing geometry produces an indeterminate seal check.

## Status and limitations

- **Verified in game:** vehicles load centred in the workbench, blocks-only hulls float, and every
  slope-piece rotation is correct. See [In-game testing](docs/in-game-testing.md).
- **Wedge smoothing:** the larger corner pieces (Pyramid 1x2 to 4x4 and their inverses) are not
  yet checked in game. Slopes with no matching piece (between 1:1 and 1:2, say) come out as a
  mix of pieces, and a ridge running through the middle of a block row stays stepped. Pyramid
  2x4 and Inverse Pyramid 2x4 are used mirrored (mirror mode, `t` in the file) where no rotation
  fits; the format was read from a save made in game, but a generated hull using them has not
  been loaded yet.
- **Large designs:** a 118 m, 184k-part ship previews in about 15 s, or about 35 s with wedge
  smoothing. Heavy tools run in a worker process that stops when the call is cancelled.
- **Not yet verified in game:** staged component placement, access, custom tanks, seal
  diagnostics, interiors, placeholder engines, and everything in
  [the feature list from the Iowa build](docs/feature-requests.md) (round and angled shapes,
  lattice masts, bulbous bows, skegs, paint).
- **Out of scope:** wiring, complete power systems, engine plumbing, external tank pipe
  connections and automatic control logic. Placement and geometric validation are automated;
  operating the finished vehicle must be checked in game.
- **Imports:** single-body version-3 editing only. Untouched XML/settings/connections are
  preserved; configured originals can be repainted, and structural blocks/new parts can be
  edited. Save under a different vehicle name.
- **Paint:** each block gets one colour, so hull blocks show their outside colour on the inside
  of rooms.

## How it works

A hull spec describes a continuous shape: plan-view taper, keel rise, sections with deadrise and
bilge radius, sheer, and superstructure boxes. The server voxelizes that shape at 0.25 m per block,
hollows it to a watertight skin, adds interior structure, and writes a Stormworks vehicle XML file.
Previews are drawn in Python with Pillow, from the same geometry the game uses.

[docs/vehicle-format.md](docs/vehicle-format.md) documents the vehicle file format, including the
details that are easy to get wrong: a missing `r` attribute is not the identity rotation, `x` in
the paint string means unpainted, and the game's axes are left-handed.

## Development

```bash
uv sync                           # install dependencies, including pytest and ruff
uv run pytest                     # unit tests; engine tests skip when the game is not installed
uv run ruff check .               # lint
uv run tools/smoke_test.py out    # build and render every preset in both modes into ./out
uv run tools/client_test.py       # drive the server over MCP stdio, like Claude Desktop does
uv run tools/staged_builder_test.py out/staged-builder --benchmark
```

| Path | Contents |
| --- | --- |
| [server.py](server.py) | MCP server and tool definitions |
| [swhull/hull.py](swhull/hull.py) | Hull spec to continuous shape and solid voxels |
| [swhull/smooth.py](swhull/smooth.py) | Hollowing, open decks, wedge fitting, leak sealing |
| [swhull/benches.py](swhull/benches.py) | Bench size keywords, fit checks, edit areas from game and mod tiles |
| [swhull/paint.py](swhull/paint.py) | Painted rectangles, circles and block-letter text |
| [swhull/jobs.py](swhull/jobs.py) | Heavy tool work in a killable worker process |
| [swhull/interior.py](swhull/interior.py) | Decks, bulkheads, rooms, doors, hatches, engines |
| [swhull/pieces.py](swhull/pieces.py) | Slope-piece geometry and the rotation convention |
| [swhull/vehicle.py](swhull/vehicle.py) | Vehicle XML reading and writing |
| [swhull/render.py](swhull/render.py) | Preview, close-up and cutaway rendering |
| [swhull/definitions.py](swhull/definitions.py) | Game install detection and part definitions |
| [swhull/editing.py](swhull/editing.py), [swhull/drafts.py](swhull/drafts.py) | Atomic part overlays and lossless imported drafts |
| [swhull/components.py](swhull/components.py), [swhull/access.py](swhull/access.py) | Mounted fit-out and complete access assemblies |
| [swhull/seal.py](swhull/seal.py), [swhull/tanks.py](swhull/tanks.py) | Independent seal diagnostics and checked block-built tanks |
| [swhull/cache.py](swhull/cache.py) | Versioned disk geometry cache shared by workers |
| [tools/](tools) | Smoke test, MCP client test, in-game calibration vehicles |

## License

[MIT](LICENSE). This is an unofficial fan project, not affiliated with or endorsed by Geometa,
the developer of Stormworks. It modifies no game files and ships no game assets; part
definitions are read from your own install at runtime.
