# Staged vehicle building

Stop after any useful stage: hull, structure, core parts, access, propulsion placement,
or custom tanks. Save the draft at that point. Components are placed without automatic wiring.

## Focused editing

Store a procedural design with **store_design**, or copy an existing vehicle into a new draft
with **import_vehicle(name, design)**. Version-3 single-body imports retain untouched component
XML, settings, colours, body data, and connections. Configured or linked original parts stay
in place; they can be repainted. Multi-body and older-version imports are rejected.

**query_parts(design, select, offset, limit)** returns identifiers, complete footprints, and a
revision. Coordinates are **integer blocks** (one block is 0.25 m): the uncentred hull build
frame (x across, y above the keel, z from the transom), or original body-local coordinates for
imports. Query bounds are inclusive. A region partially crossing a multi-block piece is
rejected; use that piece's id to select it explicitly.

**edit_parts(design, operations, revision, commit=false)** previews an atomic batch:

~~~json
[
  {"op": "paint", "select": {"ids": ["id from query_parts"]}, "color": "FF8800"},
  {"op": "add", "part": {"definition": "01_block", "position": [0, 12, 20]}},
  {"op": "fill", "bounds": [[1, 12, 20], [3, 12, 24]], "color": "CCCCCC"}
]
~~~

Other operations: **remove**, **replace** with part, **move/copy** with delta, **repeat**
with delta and an additional-copy count, **mirror** with axis/plane, and **rotate**
with rotation/pivot. Rotations are axis-aligned local-to-world matrices or Stormworks
r strings. Selection supports ids, bounds, name, and definition.

Inspect the preview, then repeat with **commit=true** and the original revision.
**undo_edits(design, revision)** restores the previous batch (ten retained steps).
Stale identifiers/revisions, collisions, and failed operations do not change the draft.

**preview_vehicle** supports generated and imported drafts, including custom camera angles.
**save_vehicle(name, design)** exports a copy. Imported originals are never overwritten.
The original hull preview/save APIs continue to work for procedural designs.

## Large designs and catalogue

The server caches completed procedural geometry across worker processes. Camera changes and
part overlays reuse it; hull, room, paint-spec, or smoothing changes rebuild it. The cache uses
JSON/NumPy, atomic publication, source/definition fingerprints, and a 20-entry/512 MiB bound.
Set **SW_BUILD_CACHE=0** to disable it or **SW_BUILD_CACHE_DIR** to change its location.

**search_parts** returns installed part ids, names, actual sizes, and mass. Use
**get_part_definition** for footprint, attachment/sealing surfaces, and settings metadata.
Without game definitions, catalogue search still provides the built-in building pieces.

## Core parts and propulsion

An optional **fitout** object has a **stage**: structure, core, access, propulsion, or tanks.
Use **{"fitout": {"stage": "core"}}** for one helm/seat and one battery.
The control goes in a bridge when possible, with a compact-seat fallback. Batteries are tried
largest to smallest using installed footprints, mounting contact and a supported 0.75 m
passage. Missing definitions or unbuildable automatic placements are reported and skipped.

**components** is a list of named requests. Unlike edit operations, their **position** and
**repeat.step** use **game metres** and are not scaled down with the hull:

~~~json
{
  "components": [
    {"name": "house battery", "kind": "battery", "size": "medium", "room": "machinery"},
    {"name": "screws", "kind": "propeller", "size": "small",
     "position": [1.5, 1.0, -0.5], "mirror_x": true}
  ]
}
~~~

Kinds: battery (small/medium/large/auto), helm, seat, propeller (small/large/giant/auto),
and rudder. Or provide an installed **definition** explicitly. Other options are rotation,
color, scalar settings, room, bay (two corners in metres), mirror_x, count, and repeat (count/step).
An automatic count finds distinct mounted positions; explicit repeated positions need a step.
Explicit invalid placements fail; automatic choices explain why they were skipped.

The propulsion stage requests a small propeller and rudder. Propeller thrust axes face
forward, mirrored twins use the game's mirror convention, and moving parts reserve clearance.
These are placements: shafts, pipes, electrical connections and controls remain user work.

Use `orientation` constraints instead of a rotation matrix to specify mounting and functional
axes independently. Both standard and Fin Rudder placements require contact at the intended
base, and reserve a conservative, rotated blade sweep. `get_part_orientation` explains axes;
`analyze_vehicle` inspects multi-body saved references and pipe/engine connection candidates.
The [advanced testing guide](advanced-testing.md) covers the exhaustive installed catalogue,
saved examples, numbered calibration exhibits and recorded player observations.

## Complete access

At stage **access** or later, room door requests use the installed manual sliding door's real
frame size. A frame that cannot fit leaves the wall sealed. Exterior openings below the main
deck remain prohibited.

Legacy hatch requests remain sealed by default. Request **assemble=true**, or use the access
stage, for a complete manual hinged hatch and mounted ladder segments. Preflight checks the
entire frame, a flat one-block deck, lower/upper landings, climbing space and supported 0.75 m
passages with 2 m headroom. Only a successful complete assembly carves the deck.

## Independent seal diagnostics

**check_seal(design, seeds=null, door_state="closed")** checks the final geometry, including
all components, carving and edits. It floods connected free space toward a padded exterior
boundary. Generated room/hull seeds are automatic; imported drafts need explicit seed points
in original body-local integer blocks:

~~~json
[{"name": "engine room", "position": [0, 2, 12]}]
~~~

Results include **sealed**, **leaking**, or **indeterminate**, named compartment connectivity,
and an escape path highlighted in magenta. Doors/hatches supported by the checker are closed
by default; use **door_state="open"** to test openings.

Building slopes use exact convex clipping of face apertures. Runtime components use known
sealing surfaces; occupied editor footprints do not prove sealing. Unknown shapes near the
checked space, missing definitions or a check above the eight-million-cell budget prevent
a confident pass. A result describes the geometric model, not a tested game simulation.

## Block-built fluid tanks

**tanks** is a named list. Position is the minimum outer corner in game metres; size is the
outer dimension in 0.25 m increments, at least 1.5 m per axis:

~~~json
{"tanks": [{"name": "fuel", "position": [-1, 0.25, 3], "size": [2, 1.5, 2]}]}
~~~

Default fluid/fill: **diesel**, **1** (full). Override **fluid** with water/diesel/jet_fuel,
**fill** with a fraction from 0 to 1, and **color** with six hexadecimal digits.
Tank positions/sizes remain game-sized when the hull is scaled. Use named patches such as
**/tanks/fuel/fill**.

The builder creates block walls, floor and roof, a configured fluid spawner, an internal
outlet, an internal vent intake, enclosed pipe penetrations, and an external gas relief
valve. It reports aft outlet and upper vent connection coordinates/directions. Connect the
external pipes yourself. Ordinary access openings through tank walls are prohibited.

Each enclosure is checked against its own bounds, so a leak into a neighbouring room fails
even if the surrounding hull is sealed. Usable geometric volume subtracts internal part
footprints; actual game capacity must be confirmed. Previewing an invalid edited tank is
allowed, but export fails if it leaks, has unknown geometry, has no usable air, or its required
fluid kit was removed/changed. Repair explicitly or undo; no silent repair is performed.

## Verification and next stages

Run **uv run tools/staged_builder_test.py out/staged-builder --benchmark** for representative
core/propulsion, access and tank builds, XML/PNG calibration artifacts and cold/repeated/small-edit
timings for a 118 m ship. The output includes cache-reuse flags and geometry equivalence checks.
Use [the in-game checklist](in-game-testing.md) to check the exported calibrations.

Measured on this Windows/Python 3.12 workspace with a 118 × 20 × 8 m blocks-only hull
(98,945 parts), including fresh worker startup and rendering: cold preview 6.5 s, repeated
preview 5.8 s, camera-only preview 3.4 s, single-part repaint 6.3 s, and core-component preview
6.0 s. Cached/uncached XML matched exactly. Rendering and cache decoding still take time;
reuse avoids procedural regeneration and does not promise instant previews. Re-run the
benchmark for your machine and more detailed room layouts.

Further work, roughly easiest first: windows/lights, navigation equipment, reusable stairs/rooms,
anchors/winches, wheels/vehicle-specific seats, circulation planning, then buoyancy/trim estimates.
Wiring, complete power systems, engine plumbing and control logic are outside these stages.
