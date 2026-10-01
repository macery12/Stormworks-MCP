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
