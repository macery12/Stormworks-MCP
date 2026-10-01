# Feature requests and bugs

Found while building real ships with the tools. Newest first.

## Wedge smoothing overhaul (2026-10-01)

| Problem | Status |
| --- | --- |
| Smoothing only really used 1x4 wedges and left most of the hull stair-stepped; it never used the rest of the game's slope pieces. | The fitter knew 6 of the 16 block-category pieces. All 16 are now built from three shapes (ramp, corner tetrahedron, inverse) and checked against the game's definition files. The old fit also rejected any voxel more than 6 of 64 samples off, which only exact 1:1, 1:2 and 1:4 slopes pass; on the trawler about 2,000 voxels that a slope improves stayed blocks. |
| Relaxing that limit gave spikes, fins and zigzags. | Volume error cannot tell a stair-step or a thin spike from a good slope. The fit now scores surface too: every exposed face and sloped face against the true surface normal (exact from the samples, with crease detection so deck edges and box corners stay sharp), then places pieces greedily, swaps and cleans up on the total. No piece may put material where the design has none. |
| Pyramids sat alone against blocks with hard edges; players stack a pyramid on an inverse pyramid of the same size to make one flat face (example vehicle "README"). | Three causes, all fixed. (1) Face coverage was sampled on a grid with points exactly on the diagonal where a pyramid meets its inverse, so every perfect joint scored as a step. (2) The greedy took pieces by gain over blocks, which favours a 1x1 wedge in a half-full voxel over an exact Pyramid 1x4 nearby; it now takes the best fit first and re-scores neighbours, so a face grows in one pattern. (3) The large inverse pyramids need the solid layer under the surface, which the fitter did not consider. A sloped edge running into a flat face or air now also costs extra. Corner planes of every pyramid size now come out in pairs (`test_corner_plane_is_laid_in_pyramid_pairs`); hard edges on the presets dropped by 25-45%. Pyramid 2x4 is chiral (three different sides), so half of its corner directions exist only mirrored; mirror mode saves that as `t` on the part (example vehicle "MIRRORED"), which the fitter, writer, reader and viewer now handle. |
| Speed | The 184k-part Iowa V2 builds with wedges in about 35 s (was about 45 s), placing about 10,000 slope pieces. |

## From spawning USS Iowa V2 (2026-10-01)

| Problem | Status |
| --- | --- |
| The ship loaded whole in the editor (with Echo's Bigger Workbenches), but on spawn everything forward of the tower vanished and the open hull sank. | Not a mod problem and not a gap in the hull (the hull is one connected piece). The cut sits exactly where component 131,072 (2**17) falls in the file, so the game appears to spawn only that many. The ship has 184,281 parts: 109,813 for the hull and superstructure and the rest for 41 rooms. The summary now shows the part count against the limit and where the cut would land; `tools/component_limit_test.py` writes a test vehicle to confirm the limit in game. |
| Three small parts were not attached (`mount5_guns_2_port`/`_stbd` barrels, `fm_yard`). | The summary now lists loose parts that would fall off on spawn. |

## From the USS Iowa V2 build (2026-10-01)

A scale 0.435 Iowa at the MAX bench (118.75 x 14.25 x 29.25 m, 47 box entries, 41 rooms on three
decks plus the tower, 183k parts), saved as `USS Iowa V2`. It used `scale`, `bench`, `store_design`
with patches, `deck_profile`, `mirror_x`, `repeat`, `on`, cylinders, domes, lattices, pitched
barrels, `bow.bulb`, `skegs` and `paint`. All of them worked. The problems were all about size.

Everything below is fixed or implemented. Timings are for this ship (184k parts) over MCP
stdio; none of the new options has been checked in the game yet.

### Bugs and limits hit

| Problem | Status |
| --- | --- |
| Tool calls time out on big designs (`preview_interior` always; `render_interior` took 119 s) | Fixed. Building the solid visits each part only inside its own bounds; blocks are rendered through a fast path; the interior render only draws faces toward the camera and pieces near each floor; the room report had a quadratic loop. `preview_hull` 15 s, `preview_interior` 12 s, `inspect_view` 11 s. |
| A timed-out call keeps the server busy | Fixed. Builds and renders run in a child process (`swhull/jobs.py`) that is killed when the client cancels, after `SW_TOOL_TIMEOUT` (300 s), or when the server exits. Checked: a wedge call abandoned at 8 s left no worker 2 s later, and the next preview took its normal 15 s. |
| `smoothing: "wedges"` times out at this size | Fixed: wedge fitting samples a voxel's 64 points in one pass and only tests nearby boxes. The full ship with wedges previews in about 45 s (was over 4 minutes). |
| Wedges damage paint | Fixed. Painted voxels and the cells in front of them stay blocks, and a Wedge 1x2 or 1x4 is only used where every cell it covers has one colour (a long wedge across the waterline used to paint its whole length one colour). Light streaks left in previews are slope faces catching the light, not paint. |
| Server instances pile up | Fixed with the worker processes: the server's own thread never blocks, so it exits when stdin closes, and workers exit when the server does (they also watch for it disappearing). |

### Missing tools and options

| Request | Status |
| --- | --- |
| Spec from a file | `spec_path` on every tool. Stored designs are re-read on every call, so editing the JSON on disk works too; `store_design` prints the file path. |
| Fit to bench | `scale: "fit"` with `bench`: the largest scale (4 decimals) at which everything fits, bulb and masts included. Iowa V2 at MAX gets 0.4346 and 118.75 m overall. |
| One unit for rooms | `interior_units: "spec"` scales decks, bulkheads, rooms and hatches like the boxes. `inspect_view(highlight=...)` also reports a box's base and top in game metres. |
| Patch hatches by name | Works: give a hatch a `name` (any list item with a `name` can be patched by it). |
| Room headroom from the box | `floors: n` on a box: 2.5 game metres per floor whatever the scale, plus any layer lost to the deck, so each floor has 2.25 m clear. |
| Negative offsets in `y` | Already parsed (`"foremast-2"`); now documented and tested. |
| Aft-pointing barrels | `facing: "aft"`, with `pivot: "back"`/`"front"` meaning the part's own ends; an aft gun is `facing: "aft"`, `pivot: "back"`, positive `pitch`. |
| Overlap report noise | `overlap_ok: true` on a box leaves it out of the overlap and hidden-box report. |
| Deck plans for rooms in boxes | Floors above the main deck are drawn cropped to their rooms. |

## From the USS Iowa build (2026-09-30)

A 1:4 scale Iowa (67.5 m, 59 superstructure boxes, hull interior), saved as `USS Iowa BB-61`.

Everything below is implemented. None of it has been checked in the
game yet; see [In-game testing](in-game-testing.md).

### Bugs

| Bug | Status |
| --- | --- |
| A `band` disappears or shifts when its box overlaps an earlier box (`funnel_fwd` inside `deckhouse_03` lost its black cap). `color_of` measured the band from the lowest voxel the box owned. | Fixed: bands are measured from the box's own `y`. |
| A `taper` under one block does nothing, silently (`taper: 0.1` on a 2 m funnel). | Fixed: the summary warns when `taper`, `rake_front` or `rake_back` changes nothing. The tugboat preset had one of these and no longer does. |

### Missing tools

| Request | Status |
| --- | --- |
| Deck height at any z | `deck_profile` tool (every metre or any `step`), plus `"y": "deck+0.25"`. |
| Patch a design instead of resending it | `store_design`, then `design` + `patch` (JSON-Patch, list items addressable by `name`) on every tool. |
| Overlap and collision report | The summary lists overlapping box pairs and boxes hidden completely inside others. |
| Rulers in `inspect_view` | Metre rulers in spec units on every view at pitch 0 or ±90, including the preview panels; `highlight` paints one box magenta and reports its extents. |
| Real-world scale helper | `scale: "1:4"` (or `0.25`) on the spec. The interior is never scaled. |
| Workbench targets | `bench` keyword (`S` to `MAX`, sized for Echo's Bigger Workbenches) or `[w, h, l]`; `list_workbenches` reads edit areas from the game and tile mods. |

### Missing spec features

| Request | Status |
| --- | --- |
| Mirrored pairs and arrays | `mirror_x: true`, `repeat: {count, dz, dx, dy}`. |
| Placing boxes on other boxes | `on: "deckhouse_02"` or `"y": "deckhouse_02+0.25"`; mirrored copies stack on the matching twin. |
| Cylinders and domes | `shape`: `cylinder` (axis y, z or x), `dome`, `sphere`. |
| Boxes with pitch and yaw | `pitch`, `yaw`, `pivot`. |
| Thin lattice mast | `shape: "lattice"` with `ring_every`. |
| Bulbous bow | `bow.bulb`. |
| Skegs | `skegs` list. |
| Prop shaft and rudder placeholders, more than one screw | Block placeholders through shapes (see the guide). Real propeller and rudder parts are not placed. |
| Hull numbers, deck markings, painted rectangles | `paint` list: `text`, `circle`, `rect` on the deck or sides. |
| Interior: floor-height changes at doors | Each door reports its sill height and the floor drop on the other side, and flags rises over 0.5 m. |
