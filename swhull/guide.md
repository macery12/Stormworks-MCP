# Stormworks hull design guide

Build Stormworks boats in stages: hull, structure, core parts, access, propulsion parts,
and custom block-built tanks. Preview and save at whichever stage the player wants.
Wiring, full power systems, engine plumbing and external pipe connections remain player work.

## Workflow

Ask which workbench the player will use; set `bench` before committing to dimensions.
For step-by-step tool calls, read `hull_design_guide(topic="building")`. The `staged` and
`testing` topics return the actual references inside the installed server, including offline.
Use `get_runtime_status` if game parts are missing or the save location is unclear.

1. Talk through the idea: role (fishing, rescue, speed, cargo, patrol, yacht), size, vibe.
2. Start from the closest preset (`list_hull_presets`), or from scratch.
3. `preview_hull` with your spec. **Always look at the image and critique it** against the
   brief: silhouette, bow shape, sheer line, proportions, colours. Iterate 2-4 times.
4. Offer the player 2-3 distinct variations when they are unsure. Different archetypes
   mixed together is where the interesting boats come from.
5. `save_hull` with a name. In game: open a workbench, press Load, pick the name.

### Big designs: store once, then send patches

A large spec (dozens of boxes) is expensive to resend on every call. Store it once with
`store_design(name, spec=...)`; after that parametric hull tools take `design=name` plus an optional
`patch`, a list of JSON-Patch ops applied on top:

```json
[{"op": "replace", "path": "/superstructure/funnel_fwd/height", "value": 3.5},
 {"op": "add", "path": "/superstructure/-", "value": {"name": "ciws_3", "z": 50, ...}},
 {"op": "remove", "path": "/superstructure/old_mast"}]
```

List items can be addressed by index or by `name`: boxes, rooms, and anything else you give
a `name`, hatches included (`{"name": "fwd_hatch", "z": 18, ...}`). `preview_hull(design=...,
patch=...)` tries a change; `store_design(name, design=name, patch=...)` keeps it;
`save_hull(name, design=name)` writes the vehicle.

Stored designs are plain JSON files (`store_design` prints the path), and every call re-reads
them, so an edit made to the file on disk applies to the next call. Parametric hull tools also take
`spec_path`, a .json file holding a spec, so a whole spec never has to go through a tool call.

Completed base geometry is cached on disk across workers. Camera changes and component/part
overlays reuse it; hull/room/smoothing changes rebuild it. If a call is cancelled, its work
stops. Keep workbench and component-limit warnings visible even when a preview is fast.

### Stages, exact edits and imported copies

Set **fitout.stage** to structure, core, access, propulsion or tanks. Stages are optional:
the original hull APIs remain usable without components. Core selects one control position
and the largest battery fitting its bay after access space is reserved. Access fits manual
door frames and requested complete hatch/ladder assemblies; propulsion requests a real small
propeller and rudder. Tanks require explicit named enclosures. Inspect every reported choice
and skipped placement; save_hull or save_vehicle can save any complete stage.

**components** holds named requests addressed by patches such as **/components/house battery/size**:

~~~json
{"fitout": {"stage": "core"},
 "components": [{"name": "house battery", "kind": "battery", "size": "medium",
                 "room": "machinery"}]}
~~~

Use **search_parts** / **get_part_definition** for installed names, footprints, mounting and
sealing surfaces. Override kind/definition, size, count (automatic locations) or repeat.count/repeat.step,
position, rotation, settings, color, bay or room. Set mirror_x for twins. Component positions
and repeat steps use **game metres**, independent of hull scale; full footprints, mounting,
occupant/operating space and a supported 0.75 m passage are checked. Explicit invalid placement
fails the build; automatic placement can skip with a reason.

Use **get_part_orientation(definition, targets)** to distinguish a part's mount, blade, hinge,
thrust and connection axes. Components accept **orientation** instead of rotation, for example
`{"definition":"rudder_surface", "orientation":{"mount_normal":[0,0,1], "span_axis":[0,1,0]}}`:
the Fin Rudder base faces the bow, its blade extends aft and its span is vertical. Standard
rudders default to a base facing upward against the hull and a blade extending downward.
Both require base contact and conservatively clear motion space. Check these placements in game.
**analyze_vehicle(name, search, section, offset, limit)** reads multi-body references without
editing them; sections expose parts, links, controllers, bodies, placement_issues,
connection_candidates and open_transmission_ports. Consult saved examples and missing coverage
before claiming a rule is verified. **get_calibration_observations(definition)** reads recorded
player checks and exposes stale or contradictory evidence. See `docs/advanced-testing.md`.

When you encounter a bug, confusing behavior, repeated placement failure or a missing capability,
use **complaint(title, description, ...)** to save a local report. Include category/severity,
the affected tool, expected/actual behavior, reproduction steps and relevant tool arguments/errors
in context. Optional design, vehicle and definition references identify the affected parts;
suggestion records a possible improvement. Reports include structured JSON and readable Markdown.
Use **list_complaints** to search/filter previous reports and **get_complaint(id)** for full evidence.
Report observed problems accurately; recording one does not fix it or publish an external issue.

For a single block or region: **query_parts(design, select)** returns stable ids, footprints
and revision. **edit_parts** accepts add, fill, remove, replace, move, rotate, paint, copy,
mirror and repeat batches. Preview with commit=false, inspect, then repeat with commit=true
and the original revision. Failed batches do not change the draft; **undo_edits** retains ten
steps. Query/edit coordinates are **integer blocks**, in the uncentred build frame (or the
original imported body frame). A partial multi-voxel region selection fails; select the whole
part by id. Geometry patches can invalidate earlier overlay targets; query again.

**import_vehicle(name, design)** copies a single-body v3 vehicle into a new draft.
Untouched XML, settings, paint, connections and body data stay intact. Configured/linked
original parts remain in place and may be repainted; structural edits and new parts are
supported. Unsupported versions and multi-body imports fail clearly. Use **preview_vehicle**
and **save_vehicle**; the original cannot be overwritten, even with overwrite=true.

After access/components/edits, use **check_seal(design)**. Generated room seeds are automatic;
imports need explicit interior integer-block seeds. Results are sealed, leaking or
indeterminate, with connected compartments and a highlighted escape path. Supported doors
are closed by default; door_state=open tests their openings. Footprints alone never count
as seals. Unsupported nearby geometry prevents a confident pass. These checks model geometry;
the player must still verify attachment, access, orientation and fluid behavior in Stormworks.

### Measuring

- `deck_profile` lists the deck height, the `y` a box gets by default, and the deck half-beam
  every metre (or any `step`). Use it instead of reading heights off a picture.
- Views at pitch 0 or ±90 (the side, top and front panels, and `inspect_view` at those angles)
  carry metre rulers in spec units: z from the transom, y from the keel, x from the centreline
  (+x is starboard).
- `inspect_view(highlight="box name")` paints one box magenta, labels it, and reports its
  extents.
- The summary lists every pair of overlapping superstructure boxes, boxes completely hidden
  inside others, and settings too small to change anything (for example a `taper` under half a
  block).

## Units and axes

Parametric dimensions use metres; query/edit tools use integer blocks.
1 Stormworks block = 0.25 m (4 blocks per metre).
`z` runs from the transom (0) to the bow (length). `x` is sideways (0 = centreline, + =
starboard). `y` is height above the lowest point of the keel. With `scale` set, every number
you enter for the hull, boxes, skegs and paint is in real-world metres. `interior` stays in
game metres, because rooms need game-sized headroom, unless you set `interior_units: "spec"`;
then room and deck positions are in the same units as the boxes and get scaled too (check
headroom in the report). `scale: "fit"` picks the largest scale at which everything, bulb and
masts included, fits `bench`; the summary reports the number it chose.

### Bench size

Ask the player which bench size they will build at before you design, and set `bench` in the
spec. The player has Echo's Bigger Workbenches, so the sizes are (W x H x L m, end to end):

| `bench` | size | typical place |
|---|---|---|
| `S` | 7.5 x 7.5 x 15 | starter-bench size |
| `M` | 20.5 x 20.5 x 23.5 | modded workbenches, small hangars |
| `L` | 22.5 x 20.5 x 120 | every modded dock |
| `XL` | 40 x 120 x 120 | space hangars and bigger |
| `XXL` | 75 x 120 x 120 | multiplayer docks and bigger |
| `MAX` | 120 x 120 x 120 | the mod's 128 m cube |

The mod caps areas at 128 m; every 120 above is that cap less 4 m (16 blocks) on each side, so
parts can hang off the edge.

`bench: [width, height, length]` sets any other size. A vehicle loads centred, so it must fit
in every direction from the middle. The summary says whether the design fits the target and
by how much it does not, and lists every size it fits. `list_workbenches` shows where each
size is available in the player's game. Hulls can be up to 120 m long.

## Spec reference

A spec is JSON. Anything you leave out comes from the preset, or from the defaults.

| key | meaning | typical |
|---|---|---|
| `length` | overall hull length, m (up to 120) | 4-40 |
| `bench` | target bench size: `S`, `M`, `L`, `XL`, `XXL`, `MAX` or `[w, h, l]` m, see "Bench size" | ask the player |
| `beam` | max width at deck, m (for multihulls: each hull's width) | L/B 2.3 (tug) to 5+ (patrol, catamaran hulls 7-10) |
| `depth` | keel to deck at midship, m | 0.6 (dinghy) to 4 |
| `deck` | `"closed"` (sealed, floats reliably) or `"open"` (cockpit/well deck) | |
| `smoothing` | `"blocks"` (default), `"wedges"` (original catalogue fit), or `"wedges_v2"` (continuous boundary angle/position measurement, protected floors, comparison guard) | use V2 when smoothing is requested; inspect the result |
| `hulls` / `hull_spacing` | 1 mono, 2 catamaran, 3 trimaran; spacing is centreline to centreline, m | |
| `bow.entry` | fraction of length over which the bow narrows | 0.1 blunt, 0.3 normal, 0.45 very fine |
| `bow.fullness` | plan shape of the bow: 1 = straight V, 2 = rounded, 3 = bluff | 1.2-2.3 |
| `bow.stem_width` | width at the very bow as a fraction of beam (0 = pointed) | 0; 0.8+ for barges/landing craft |
| `bow.rake` | how far the keel rises at the bow, m (raked/cutaway stem) | 0.3-2 |
| `bow.rake_curve` | 1 = straight raked stem, 2+ = curved spoon bow | 1-2.5 |
| `bow.flare` | extra topside flare at the bow (0-0.35) | 0.15-0.3 |
| `bow.deadrise` | V-angle of the bottom at the bow, degrees | 25-45 |
| `stern.run` | fraction of length over which the stern narrows | 0 (square) to 0.35 (double-ender) |
| `stern.transom_width` | transom width as fraction of beam (0 = canoe/pointed stern) | 0.5-1 |
| `stern.fullness` | plan shape of the stern taper (like bow.fullness) | 2 |
| `stern.keel_rise` | keel lift toward the stern, m | 0-0.5 |
| `sheer.bow` / `sheer.stern` | deck-line rise at bow/stern, m | bow 0.2-1.2 |
| `section.deadrise` | V-angle of the bottom amidships, degrees (0 = flat) | planing 16-24, workboat 8-14, barge 0 |
| `section.bilge_radius` | roundness where bottom meets side, m (0 = hard chine) | 0 speedboat, 0.3-1.2 round bilge |
| `section.flare` | how much narrower the waterline is than the deck (negative = tumblehome) | 0-0.15 |
| `section.keel_width` | width of the flat keel strip, m | 0.25-0.5 |
| `bow.bulb` | bulbous bow: `{length, width, height, y, protrude}` m; `y` is the bulb's centre height, `protrude` how far its tip passes the bow | warships, freighters |
| `colors` | hex RGB: `bottom`, `stripe` (boot-top), `topsides`, `deck`; `waterline` height m; `stripe_height` m | |
| `superstructure` | list of boxes, see below | |
| `skegs` | fins under the hull: `[{z, length, x, width, bottom, mirror_x}]`; each fills from `bottom` (m above the keel, may be negative) up to the hull | twin-screw sterns |
| `paint` | rectangles, circles and text on the deck or sides, see below | |
| `scale` | enter real-world sizes: `"1:4"` or `0.25` multiplies every hull, box, skeg and paint length; `"fit"` fills the `bench` | 1 |
| `interior_units` | `"game"` (default) or `"spec"`: whether room, deck and hatch positions are scaled like everything else | `"game"` |

### Superstructure boxes

```json
{"name": "wheelhouse", "z": 9.0, "length": 3.5, "width": 3.4, "height": 2.25,
 "x": 0, "y": null, "taper": 0.15, "rake_front": 0.4, "rake_back": 0.0,
 "color": "F0F0F0", "band": {"from": 1.25, "to": 1.9, "color": "1A2530"}}
```

- `z` is where the box starts, in metres from the transom. It extends toward the bow by `length`.
- `y` omitted = sits on the deck. Set `y` for stacked levels (flybridge, upper wheelhouse) or a
  catamaran bridge deck. The preview summary lists deck heights at stern/midship/bow.
- `taper` slopes all sides inward toward the top (m); `rake_front` slopes the front face back
  (raked windscreen); `rake_back` slopes the rear face.
- `band` paints a horizontal stripe (window band) between `from` and `to` metres above the box
  bottom. Taper and rakes under 0.25 m barely register at 0.25 m per block; the summary warns
  when one changes nothing.

Placing boxes:

- `y` can be a number (m above the keel), `"deck+0.25"` (relative to the deck under the box), or
  `"<box name>+0.5"` (relative to that box's top). `on: "deckhouse_02"` stacks a box directly on
  another's roof. References may point at boxes later in the list.
- `mirror_x: true` adds a copy at `-x` (names get `_port`/`_stbd`). `repeat: {count, dz, dx, dy}`
  makes a row (names get `_1`, `_2`, ...). A mirrored or repeated box stacked `on` another
  mirrored or repeated box lands on the matching copy.
- `y` offsets may be negative: `"foremast-2"` puts a box 2 m below the top of `foremast` (a yard
  part way down a mast).
- `floors: n` sets the height for `n` walkable floors: 2.5 game metres each (2.25 m headroom plus
  a 0.25 m floor or roof), whatever the `scale`, plus any layer the box loses to the deck under
  it. Use it for every box that has rooms in it.
- Names must be unique. Where boxes overlap, the earlier one in the list owns the shared blocks.
  The summary lists overlaps; mark a box `overlap_ok: true` when its overlap is intended
  (barrels in a turret house, a tower inside a deckhouse) so real mistakes stand out.

Shapes and angles:

| key | meaning |
|---|---|
| `shape` | `"box"` (default), `"cylinder"`, `"dome"` (half ellipsoid, flat side down), `"sphere"` (ellipsoid filling the box), `"lattice"` (corner posts plus rings, for masts) |
| `axis` | cylinders only: `"y"` upright (default; `taper` makes a cone), `"z"` along the hull (barrels; `taper` narrows the fore end), `"x"` across |
| `facing` | `"fore"` (default) or `"aft"`: turns the part end for end in its footprint, for guns that point astern |
| `pitch` | degrees; positive raises the part's front end (gun elevation; negative rakes a mast aft) |
| `yaw` | degrees; positive swings the front end to starboard (trained guns, splayed tripod legs) |
| `pivot` | point the rotation turns about: `"base"` (centre of the bottom, default), `"back"` / `"front"` (centre of the part's own end faces; `"back"` is the breech of a barrel whichever way it faces), `"centre"`. `"aft"`/`"fore"` mean the same as `"back"`/`"front"`. |

An aft-firing barrel is `facing: "aft"`, `pivot: "back"` and a positive `pitch`, exactly like a
forward one.
| `ring_every` | lattice ring spacing, m (default 1) |

`width` and `length` are the diameters of round shapes. Rotated parts thinner than about 0.4 m
are thickened slightly so a diagonal stays one connected piece. Round shapes under about 1 m
across come out square: at 0.25 m per block a circle needs room.

Appendages are boxes too: a prop shaft is a `cylinder` with `axis: "z"`, a small negative
`pitch` and a numeric `y` low on the hull; a rudder is a thin box behind it. These are
placeholder blocks. Use named components or the propulsion stage for real propellers/rudders.

### Paint

```json
"paint": [
  {"shape": "text", "text": "61", "on": "sides", "z": 62, "y": 2.5, "height": 1.25, "color": "F0F0F0"},
  {"shape": "circle", "on": "deck", "z": 4, "x": 0, "radius": 2.5, "thickness": 0.25, "color": "F0F0F0"},
  {"shape": "text", "text": "H", "on": "deck", "z": 4, "x": 0, "height": 2.5, "color": "F0F0F0"},
  {"shape": "rect", "on": "starboard", "z": 10, "length": 4, "y": 1.5, "height": 0.5, "color": "F2B705"}
]
```

- `on`: `"deck"` paints the topmost surface (deck or box roof); `"port"`, `"starboard"` or
  `"sides"` (both) paint the outermost surface on that side.
- Sides: `z` is where a `rect` starts and the centre of `text` and `circle`; `y` is the bottom
  (rect, text) or centre (circle). Deck: `x` is the centre across, `width` the rect's width.
- `text` uses 3 x 5 block letters (A-Z, 0-9, `- . / #`). `height` is the letter height;
  1.25 m gives one block per pixel, and anything smaller loses pixels. Side text reads
  correctly from outside on both sides; deck text reads with its top toward the bow.
- Later items paint over earlier ones. Each block takes one colour.

## Interior design

For precise local edits, use query_parts followed by edit_parts, passing its revision.
Those coordinates are integer blocks in the uncentred build frame. Batched operations include
fills, copies, mirrors, arrays, moves and paint. commit=false previews; commit=true persists.
Use undo_edits to revert a batch. import_vehicle supports safe copies of existing single-body
version-3 vehicles; use preview_vehicle and save_vehicle for those drafts.

Add an `interior` object to lay out rooms inside the hull and superstructure. It is all plain
blocks: floors, bulkheads, room walls, and legacy doorways. Optional staged fit-out places real
parts. The access stage replaces fitting walls with manual doors and complete hatch/ladder
assemblies. Check the result with `preview_interior` and **check_seal**.

```json
"interior": {
  "decks": [0.5],
  "bulkheads": [2.0, 7.5, 11.0, 16.5],
  "rooms": [
    {"name": "engine room", "type": "engine", "level": 0, "z": 2.0, "length": 5.5,
     "engine": "large", "engine_count": 1, "doors": ["fore"]},
    {"name": "crew quarters", "type": "quarters", "level": 0, "z": 11.0, "length": 5.5,
     "width": 3.0, "x": 0.0, "doors": ["aft", "fore"]},
    {"name": "bridge", "type": "bridge", "level": "main", "z": 11.25, "length": 5.0,
     "width": 3.25, "doors": ["port", "starboard"]},
    {"name": "radio room", "type": "bridge", "floor": 5.25, "z": 6.25, "length": 2.5}
  ],
  "hatches": [{"z": 12.5, "x": 0.0, "deck": "main"}, {"z": 7.0, "floor": 5.25}]
}
```

- **Decks and bulkheads.** `decks` lists internal floor heights in metres above the keel;
  `bulkheads` lists watertight transverse walls in metres from the transom.
- **Levels.** `level: 0` stands on `decks[0]`, `level: "main"` stands on the main deck (inside a
  superstructure box), and `floor: <m>` sets any floor height, e.g. an upper superstructure
  level. A room reaches up to the next deck, floor, or roof unless you give `height`.
- **Size.** `z` and `length` are measured wall to wall. Leave `width` out to use the full hull
  width at that spot. Put room ends on bulkhead positions so they share one wall.
- **Doors.** `fore`/`aft`/`port`/`starboard`. A doorway is 0.75 m wide and 2 m tall; it drops to
  1.5 m where space is tight and is placed at the lowest, most central spot that works.
  Exterior doors through the hull skin are only allowed above the main deck. The report gives
  each door's sill height above the room floor and how far the floor drops on the other side,
  and marks rises over 0.5 m "ladder".
- **Hatches.** Requests for vertical access: `deck` index, `"main"`, or `floor` metres.
  Floors stay sealed unless a complete fitted ladder/hatch assembly can be installed.
  Give a hatch a `name` to patch it by name.
  Set fitout.stage=access (or later), or assemble=true on the hatch. Assembly requires a flat
  one-block deck, a lower landing, correctly mounted ladder segments, a 0.75 m climbing/landing
  path and 2 m headroom. Unsupported sizes or any failed check leave the deck sealed.
- **Deck plans.** `preview_interior` draws one plan per floor height. Floors above the main deck
  (rooms inside superstructure) are drawn cropped to their rooms.
  Unfinished access requests are reported; they never create bare holes.
- **Engines.** `engine`: small (0.75 x 0.75 x 0.75 m), medium (0.75 x 1.0 x 1.75 m), or large
  (1.25 W x 2.0 H x 2.75 L m). `engine_count` places several side by side. If one does not fit,
  the report says so instead of placing it.
- **Room types** only set floor colour: engine, machinery, fuel, quarters, cabin, galley, mess,
  bridge, storage, cargo, corridor, medical, workshop.

Layout rules of thumb:
- Headroom: 2 m minimum (8 blocks) for walking. Leave 2.25 m or more for superstructure rooms,
  which means superstructure boxes about 2.5 m tall.
- The engine room goes aft, near the propeller shafts. Put fuel and machinery next to it.
- Bulkheads every 1/5 to 1/4 of the length make watertight compartments. There is always a
  forepeak (store/chain locker) behind the bow.
- Crew spaces go amidships (least motion); the bridge goes in the superstructure, forward of midships.
- V and round hulls are narrow low down: check "floor W" in the report. On deep-V hulls, raise
  the lowest deck or accept narrow floors.
- Every room needs a way in: a door chain to a hatch or an exterior door.

### Custom block-built tanks

Add named **tanks** with an explicit minimum corner and outer size, in game metres:

~~~json
{"tanks": [{"name": "aft diesel", "position": [-1, 0.25, 3],
            "size": [2, 1.5, 2], "fluid": "diesel", "fill": 1}]}
~~~

Sizes are 0.25 m increments, at least 1.5 m on each axis for the complete fluid kit.
The enclosure builds continuous block walls/floor/roof, with a configured fluid marker,
an aft outlet and an upper vent using enclosed pipe penetrations. No ordinary door/hatch
requests may cut the boundary. Existing plain walls may be shared; components/slopes and
occupied tank interiors fail fit checks. Diesel/full is the default; water and jet_fuel
and fill fractions 0–1 are supported.

The summary reports geometric usable litres after internal part footprints, fluid/fill,
and each tank's independent seal status. **check_seal** includes these tank checks and
connection coordinates. A leak into a neighbouring sealed room still fails the tank.
Edits that break the enclosure or remove/change its required fluid kit block vehicle export;
previews remain available for repair. Tanks are never silently repaired. External outlet/vent
plumbing and in-game confirmation of actual capacity and contents remain player work.

## Archetype proportions (starting points)

| type | L/B | deadrise | bow | stern | character |
|---|---|---|---|---|---|
| runabout / speedboat | 2.8 | 16-22 (bow 40+) | fine, raked, flared | wide transom | low, open cockpit |
| fishing trawler | 3.2 | 10-14, round bilge | high sheer, flared | transom or cruiser | wheelhouse forward, work deck aft |
| tug | 2.3-2.6 | 6-10, big round bilge | bluff, round | rounded, narrow | tall wheelhouse amidships |
| motor yacht | 3.5-4 | 14-18 | fine, strongly raked | wide transom | long stepped superstructure |
| patrol / fast attack | 4.5-6 | 18-24, hard chine | very fine, raked, knuckle flare | square transom | low bridge amidships, mast |
| lifeboat / pilot | 3 | 12-16 | fine | double-ended | domed cabin, bright orange |
| landing craft / barge | 3-3.5 | 0 | blunt ramp (stem_width 0.8+) | square | flat, open well deck |
| catamaran | hulls 7-10 each | 18-24 | fine | square | wide bridge deck, cabin |

## Making it look good

- A rising sheer toward the bow (`sheer.bow` 0.4-1.0) instantly makes a hull look seaworthy.
- Pair flare with deadrise at the bow: fine V below, wide flared topsides above.
- Contrast: dark bottom, thin stripe at the waterline, light topsides; the deck a mid tone.
- Keep superstructure narrower than the deck (0.6-0.8 of beam) and taper or rake it.
- Heavy workboats: blunt, tall, beamy. Fast boats: long, low, fine entry, raked everything.
- Anything under ~1.5 m wide gets blocky: at 0.25 m per block, small curves are coarse.

## Limits

- Hull shells, decks, block superstructure (boxes, cylinders, domes, lattices) and block
  interiors only. Engines are optional placeholders; props and rudders can only be block
  placeholders; no pipes or wiring.
- The hull is a hollow one-block-thick shell. Closed decks are sealed compartments.
- **The game spawns at most 131,072 parts** (seen in game). A bigger vehicle loads whole in the
  editor, but on spawn everything past that part is missing: the hull is cut straight across
  and sinks. The summary shows the count against the limit and where the cut would fall. Rooms
  are the expensive part (a 118 m ship: 110k parts for the hull, 74k more for 41 rooms), so on
  very large ships keep the interior to the rooms that matter, or lower the scale.
- Parts that do not touch the rest by a full face are split off as separate bodies and fall
  away. The summary lists every loose part; move it until it touches.
- Default output is plain blocks, stair-stepped. `smoothing: "wedges"` fits the game's slope
  pieces automatically (all 15, in every rotation), keeps deck edges and box corners sharp and
  painted areas as blocks, and stays watertight. Slopes of exactly 1:1, 1:2 and 1:4 (and their
  corners, laid as a pyramid on an inverse pyramid of the same size, repeated) come out
  perfectly smooth; slopes in between, and ridges running through the middle
  of a block row, come out as a mix of pieces. Look at the preview before saving. The larger
  corner pieces are not yet checked in game.
- `smoothing: "wedges_v2"` measures the continuous boundary within partial cells and checks
  where the sloped surface lies, as well as its angle. It compares both final skins after
  seal backing and retains the original fit if V2 adds seams or exceeds a small shape-error
  allowance. Interior floors/walls and their immediate backing stay full blocks in both modes.
  V2 takes longer. Read `hull_design_guide(topic="smoothing")`, call `analyze_hull` to check
  floor-to-rim depth, and use `suggest_hull_blocks` for real slope families. This does not
  make an arbitrary curve exactly representable by the game's limited block catalogue.
- Previews show a 3/4 view from below too; check the hull bottom there. For details, use
  `inspect_view` (any angle and zoom). `open_in_viewer` gives the player an interactive 3D view.
