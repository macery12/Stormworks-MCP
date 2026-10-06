# Building a vehicle you can understand and check

Start with a small blocks-only design and a named draft. Decide the workbench and target
dimensions before adding detail; the rendered outline alone cannot prove fit, attachment,
sealing, or operation. See [the staged reference](staged-builder.md) for placement options.

## First build

These are MCP tool names and JSON arguments; ask your client to make the calls.

1. Read `hull_design_guide({"topic": "workflow"})` and call `list_workbenches({})`.
2. Call `store_design({"name": "First tug", "preset": "tugboat", "spec": {"bench": "S", "scale": "fit", "smoothing": "blocks"}})`.
3. Call `preview_hull({"design": "First tug"})`. Compare the bow, stern, beam and deck to the
   brief. Read the fit, loose-part and component-limit warnings.
4. If you need rooms, use `preview_interior({"design": "First tug"})`. Check usable headroom,
   floor steps and door sills before adding components. Call `deck_profile` to measure where a
   deckhouse should sit; use `inspect_view` to examine anything ambiguous.
5. Use `store_design` with the same name, `design` and a `patch` to keep a change. A patch sent
   only to a preview is temporary. For example:

   ```json
   {"name": "First tug", "design": "First tug", "patch": [
     {"op": "replace", "path": "/fitout", "value": {"stage": "core"}}
   ]}
   ```

6. Review every automatic selection and skipped placement. Progress through `access`,
   `propulsion`, and `tanks` only as needed. Definitions from your installed game are required
   for real parts; `get_runtime_status` shows whether they were found. A scaled-down bridge
   can be too small for a game-sized helm or door even when the hull fits the bench.
7. Call `check_seal({"design": "First tug"})`; inspect any magenta escape path. An
   `indeterminate` result needs investigation. Previewing an invalid tank is allowed; saving it fails.
8. Call `save_vehicle({"name": "First tug export", "design": "First tug"})`, then load the
   export in Stormworks. Verify attachment, access, flotation and trim. Wire controls, connect
   power and plumbing, and test propulsion in game.

## Keep the units straight

| Input or report | Units and frame |
| --- | --- |
| Hull, superstructure, skegs, spec paint | Spec metres; multiplied by `scale` |
| Components and custom tanks | Game metres; remain game-sized when hull is scaled |
| Rooms and interior decks | Game metres by default; `interior_units: "spec"` opts into scaling |
| `query_parts` / `edit_parts` | Integer blocks; 4 blocks = 1 m, in the uncentred build frame |
| Imported part edits and seal seeds | Original body-local integer blocks |
| Exported XML | Re-centred workbench coordinates; do not copy them into build-frame edits |

The generated build frame is x across (+ starboard), y above the keel, and z from transom
to bow. Query actual positions before editing. Never infer an edit coordinate from a
centred preview or exported XML.

## Exact edits and existing vehicles

Use `query_parts` to obtain stable IDs and the current revision. Preview an `edit_parts`
batch with `commit: false`, inspect it, then commit the same batch with the same revision.
If another change made the revision stale, query again. Use `undo_edits` for the last ten
committed batches. Editing part footprints partially is rejected; select the complete part.

Use `import_vehicle` to create a separate draft from an existing single-body version-3
vehicle. Repaint configured originals in place and edit supported structural/new parts.
Save under a new vehicle name. Use explicit interior seed coordinates for imported seal
checks; automatic generated-room seeds do not apply to imports.

Use `query_connections` to discover wire nodes and transmission faces. `edit_connections`
adds/removes typed signal/electric links; `route_connections` adds/removes actual pipe routes.
Use enclosed pipes in bodywork and `through_blocks` for explicitly selected wall crossings.
Both use the draft revision and support preview, commit and undo. `preflight_vehicle` checks
required subsystem paths. See [the land vehicle guide](land-vehicles.md#connections-and-subsystem-preflight)
for endpoint formats, examples and topology limits. Engine choices are prebuilt diesels and
cooling choices are radiators.

## Diagnose a result

| Symptom | Next useful action |
| --- | --- |
| Parts were skipped | Read the reason; use `search_parts` and `get_part_definition` to compare footprint and mounting requirements |
| Part is rotated incorrectly | Use `get_part_orientation`, then inspect mounting and functional axes separately |
| Box disappeared | Read hidden/overlap warnings and inspect the named box with `highlight` |
| A preview change disappeared later | Persist its patch with `store_design`; previews do not update the draft |
| Ship fits the editor but truncates on spawn | Read the part-count warning; the suspected 131,072-component spawn cap needs further in-game confirmation |
| Tool cancelled or timed out | Workers stop; reduce size/detail, preview blocks first, or increase the client timeout and `SW_TOOL_TIMEOUT` together |
| Cannot place installed components | Call `get_runtime_status`; check `SW_GAME_DIR` or `SW_DEFINITIONS_DIR` |
| Geometry passes but vehicle fails in game | Record exact expected/actual behavior using `complaint`, with arguments and an in-game reproduction |

[In-game testing](in-game-testing.md) distinguishes verified behavior from geometric checks.
Tests do not simulate Stormworks physics, buoyancy, fluid flow or working controls.
