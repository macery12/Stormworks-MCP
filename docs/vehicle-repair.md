# Diagnose, repair and verify a vehicle

Start with a stored hull, land or single-body imported draft. Read installed node and face
indices using `query_connections`; exact edits and routes use integer blocks (0.25 m).
New nested MCP schemas require operation-specific fields, reject unknown fields and expose
coordinate shapes, port indices, colors, mirror masks, repeat counts and pipe style choices.

## Repair workflow

1. Run `preflight_vehicle(design="my vehicle")`. Each `findings` row includes a stable
   `finding_id`, code, severity, affected `part_ids`, explanation, suggested operations,
   repair status and reason. Existing checks/issues remain available.
2. Call `plan_vehicle_repairs(design="my vehicle")`. This materializes and export-checks
   each suggestion independently. A suggestion becomes manual if it cannot remove its
   finding without introducing another finding. Nothing is saved.
3. Select **available** finding IDs and preview:

   ```json
   {"design":"my vehicle", "revision":"<plan revision>", "plan_id":"<plan ID>",
    "finding_ids":["<available finding ID>"], "commit":false}
   ```

   Pass this object to `repair_vehicle`. It returns an image plus structured before/after
   preflight, resolved and remaining IDs, and revisions. Green lines show proposed wires;
   green markers show new pipes. The draft remains unchanged.
4. Inspect the preview, then repeat with `commit:true` and the **original** plan/revision.
   The combined batch must still resolve the selected findings without creating new ones.
   It commits once, with a fresh revision and one `undo_edits` step. Rerun preflight.

Suggestions currently cover missing standard seat starter, reverse, brake and lamp controls,
electrical supply from a single battery, explicit engine power, supported inverted steering
paths, and reconnection of fuel/air/exhaust circuits to a unique intended component.
The pipe suggestion joins open faces on the two intended circuit boundaries; it preserves
existing equipment, mounting/access constraints and unrelated circuits. If the closest
candidate is blocked, ambiguous or unsafe, choose endpoints and route bounds manually.

Missing or ambiguous equipment, unknown controller logic, blocked bodywork, cooling/driveline
redesign and wheel orientation changes require explicit design decisions. Manual findings
include the reason. A suggestion in raw preflight is provisional; use the tested repair plan
before applying it. No repair tool silently deletes obstructing structure.

`edit_parts` also supports `configure`:

```json
{"op":"configure", "select":{"ids":["<engine ID>"]}, "settings":{"max_force_scale":1}}
```

Supported settings are engine power, gearbox ratio indices, premade tank fluid/fill, and the
small function gate expression. This preserves imported XML, unrelated settings and links;
it cannot change geometry, node layout or arbitrary component settings. Engine power uses
0–1, tank fill 0–1, diesel type 1, and saved gearbox off/on defaults 1/0.

## Reusable control assemblies

Call `list_vehicle_assemblies` for required roles. Place missing gates and mounting blocks
with `edit_parts`; query the new revision and bind explicit current IDs using
`apply_vehicle_assembly`. Assemblies configure existing parts and replace only selected
target input drivers. They use preview, revision checks, atomic commit and undo.

| Assembly | Required bindings | Behavior |
| --- | --- | --- |
| `engine_start_idle` | driver, engine, throttle_gate | Hold Hotkey 1 to start; throttle is `max(idle,min(1,W))` |
| `clutch_engagement` | driver, clutch, clutch_gate | Disengaged at rest; engagement rises from the positive-W deadband to full W |
| `brake_reverse` | driver, gearbox, wheels | Trigger brakes selected wheels; Hotkey 3 switches off=forward/on=reverse |
| `lighting` | driver, battery, lights | Hotkey 2 switches selected lamps; selected battery supplies their electricity |

Both gate roles require `gate_function_small`. **Use separate throttle and clutch gates.**
Changing a gate that also drives another subsystem is rejected. The existing 4x4 presets
share a throttle/clutch limiter: add and bind a separate clutch gate first, then apply the
idle assembly to the existing throttle gate. Bindings can be used on custom and imported
vehicles; they do not depend on preset component names or coordinates.

Example after placing a separate clutch gate:

```json
{"design":"my vehicle", "assembly":"clutch_engagement", "revision":"<queried revision>",
 "bindings":{"driver":"<seat ID>", "clutch":"<clutch ID>", "clutch_gate":"<new gate ID>"},
 "options":{"clutch_deadband":0.15}, "commit":false}
```

Options: `idle_throttle` 0–0.5 (default .08), `clutch_deadband` 0–<1 (default .15),
`starter_hotkey`/`lights_hotkey`/`reverse_hotkey` 1–6 (defaults 1/2/3). Configure seat hotkeys
in the editor to the intended hold/toggle mode. The starter is manual, idle throttle is
open-loop and reverse has no speed interlock: release the starter after ignition and shift
while stopped. Tune idle, clutch response and braking in game. The assembly report includes
preflight and operations; it does not claim working engine control or vehicle dynamics.

## Diagnostic views

`preview_vehicle_diagnostics(design="my vehicle", layer="components")` draws faults over
the current geometry. `layer="all"` keeps the bodywork. Red marks affected parts, amber marks
blocked exits, and blue arrows show wheel forward and the supported steering signal direction.
Rear wheels without steering inputs show `fixed`. Labels expose actual/required steering signs.
Repair/assembly previews add green proposed wiring and pipe markers.

`open_in_viewer(design="my vehicle", diagnostics=true)` opens the same fault/steering
primitives in the browser viewer. Toggle Diagnostics to compare geometry and overlays;
loading a different XML clears the diagnostics. X is negated for display, consistently with
the standard previews. Unknown sign paths stay unknown; these arrows are static evidence.

## Exact-version in-game evidence

Call `prepare_vehicle_validation(name="Humvee road test", design="my Humvee")` to export
a separate test copy and create a pending checklist. It records the exact UTF-8 XML SHA-256,
source draft revision, part count and export path. Existing files retain overwrite protection.
Validation manifests live in `SW_DESIGNS_DIR/validation` (the normal per-user designs folder
when unset), independently of edit/undo history.

Load **that copy** at the selected workbench and test starting, W forward, A/D steering,
reverse, braking, at least five minutes of loaded cooling, and full-steer/compressed suspension
clearance. Record game version, tester, observed evidence and numerical measurements:

```json
{"run_id":"<run ID>", "export_sha256":"<manifest SHA-256>", "game_version":"<actual version>",
 "tester":"<player>", "observations":[{"check":"starting", "result":"pass",
 "evidence":"<what you actually observed>", "measurements":{"idle_rps":7}}]}
```

Pass this to `record_vehicle_validation`; do not copy the example as observed evidence.
Each observation is pass/fail/skipped. A run passes only with pass evidence for all seven
checks. `get_vehicle_validation` reports whether export bytes and current draft still match.
Modified exports cannot receive results under the old hash: create a new test copy/run.
Results are explicitly human-reported evidence, never a simulated or automatic game pass.

## Reproduce the first acceptance milestone

```powershell
uv run tools/diagnostic_milestone.py out/diagnostic-review
```

With installed definitions, this creates **separate** fuel, starter and steering fault drafts,
plans repairs, checks they remove all findings, renders three annotated previews and writes
JSON reports. It also exports an unchanged Humvee baseline and a seven-check **pending**
manifest in the output directory. Generated vehicle XML and local evidence stay out of Git.
Automated acceptance tests cover this workflow, stale plans/revisions, preview isolation,
atomic commit/undo, nested schemas, imported settings preservation, assemblies and export hashes.
Driving, cooling and suspension checks still require a player in Stormworks.
