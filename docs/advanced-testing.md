# Advanced placement and reference testing

The priority is reliable vehicle generation, supported by inspection and reusable evidence.
Rudders come first, then propellers, engines and pipes. Analyze saved vehicles before asking
the player to verify generated calibration exhibits.

## What runs automatically

```powershell
uv run pytest -q --junitxml=out/pytest.xml
uv run ruff check .
```

| Layer | Coverage | Meaning of a pass |
| --- | --- | --- |
| Installed catalogue | Every installed definition, all 24 rotations and 24 reflections | Footprint agrees with independently parsed game XML; stored matrix/mirror transforms, mass, paint count and geometry round trip agree. Grid-aligned declared attachment faces are checked against a supporting block where available. |
| Portable building geometry | All 16 block/slope types, 24 rotations and every local mirror mask | Face geometry and serialized transforms agree, including asymmetric 2x4 corners. |
| Smoothing | Existing roof/corner calibration, symmetry, spike and watertightness regressions | Generated pieces satisfy the geometric checks; visual and game checks are still needed. |
| Rudders | Both standard and Fin Rudder, all 48 orientations/reflections | The intended base must touch support; touching a side alone fails. Obstructed blade sweeps fail. Independently sampled motion stays inside the reserved envelope. |
| Plumbing evidence | All 48 orientations/reflections of synthetic pipe assemblies | Opposing transmission faces remain adjacent after transforms; unrelated faces do not connect. Different declared types remain unverified. |
| Reference parsing | Multiple bodies, nested controller groups, configured ports, ambiguous/missing links | Body-local geometry remains separate. Internal controller components are not counted as vehicle blocks. Missing definitions and endpoint uncertainty remain visible. |
| Calibration evidence | Numbered exhibits, stable case IDs, unchanged XML/definition hashes | No overlapping exhibits; no automatic game passes; stale and contradictory observations remain visible. |
| Existing builder | Access, seals, tanks, edits, caching, MCP integration | Previous regressions continue to pass. |

Installed tests use the player's definitions at runtime. CI runs the portable fixtures and
skips installed/reference tests when their inputs are absent. No game assets or private vehicles
belong in the repository. Tests use `installed` and `reference` markers so coverage gaps are explicit.

## Analyze attack boat

```powershell
uv run tools/advanced_suite.py audit --vehicle "attack boat" --output out/advanced-suite
$env:SW_REFERENCE_VEHICLE = "$env:APPDATA/Stormworks/data/vehicles/attack boat.xml"
uv run pytest -q --junitxml=out/pytest.xml
```

An existing XML path also works with `--vehicle`. Analysis reads the source and writes reports
under the ignored `out/` directory:

- `reference-report.json`: every definition count, observed rotations, body groups, controller
  group hierarchy, connection nodes, raw saved links, rudder base/sweep inspection, facing
  transmission-port candidates and unmatched transmission ports.
- `examples.jsonl`: body-aware examples with local coordinates, mounting contacts, settings keys,
  instance-specific controller ports, functional axes and source hash. This is reference evidence
  for reasoning and regression work, not a fine-tuned model or proof of correct game behavior.

The audit samples up to 100 distinct rotation/settings/controller configurations per definition
(`--samples 1` through `100` overrides this). Counts and links cover the whole source; sampled and
unsampled condition counts expose where the example corpus is incomplete. Controller evidence
includes internal components, input links and group parents, without flattening them into blocks.

The local attack boat examined on October 1, 2026 had 31,580 placed parts, 228 distinct definitions,
48 bodies and 1,616 saved links. That is 30.0% of the 759 installed definitions; its six
`rudder_surface` placements provide a useful transom-mounted example. Coverage of block types is
different from coverage of mounting situations or complete operating systems. The report lists
every missing definition and preserves uncertainty rather than claiming 90% coverage.

MCP tools expose the same evidence:

```text
analyze_vehicle(name="attack boat", search="rudder", section="parts")
analyze_vehicle(name="attack boat", search="engine", section="connection_candidates")
analyze_vehicle(name="attack boat", section="links", offset=0, limit=50)
analyze_vehicle(name="attack boat", section="controllers")
```

Sections are `parts`, `links`, `controllers`, `bodies`, `placement_issues`,
`connection_candidates`, and `open_transmission_ports`. Search and pagination apply to each.
Analysis supports multiple bodies; editing imports still support only one body.

All contacts are body-local. Articulated body transforms, link coordinate conventions, fluid
compatibility and internal routing are not solved. A unique link candidate identifies a possible
part; it does not establish the selected pin, wire direction or a functioning circuit. Adjacent
transmission faces do not prove flow, shaft power, fuel supply or engine operation. Open ports
are inventory evidence, not automatically errors.

## Learn rotations by their role

`get_part_definition` now includes all voxel cells (including `<position/>`), voxel flags,
surface rotations, definition attributes, logic nodes, couplings and motion directions.

`get_part_orientation` explains local axes and solves desired body directions. Generated boats
use +y up and +z toward the bow. For a standard rudder, the local base faces -y while the blade
extends +y. Its default places that base upward against the hull and extends the blade downward.
For the Fin Rudder, its span/hinge runs along local z. The default matches the reference boat:
the base faces the bow (+z), the blade extends aft (-z), and the span is vertical (+y).

```text
get_part_orientation("rudder", targets={"mount_normal": [0,1,0], "span_axis": [0,0,1]})
get_part_orientation("rudder_surface", targets={"mount_normal": [0,0,1], "span_axis": [0,1,0]})
get_part_orientation("trans_straight", targets={"port_0_normal": [0,0,1]})
get_part_orientation("propeller", targets={"force_dir": [0,0,1]})
```

Named component requests accept the same constraints:

```json
{"components": [{"name": "steering fin", "kind": "rudder", "definition": "rudder_surface",
                 "orientation": {"mount_normal": [0,0,1], "span_axis": [0,1,0]}}]}
```

Use `orientation` or an explicit `rotation`. Contradictory axes fail. New rudder placements
require base contact; the Fin Rudder is also an automatic fallback if the standard rudder cannot
fit. Blade clearance uses conservative swept bounds of definition motion voxels, including angular
extrema, and transforms the envelope with the part. Those bounds approximate meshes and do not
simulate hydrodynamics, steering sign, buoyancy or exact collisions.

## Generate the next in-game checks

```powershell
uv run tools/advanced_suite.py calibrate --definition rudder --definition rudder_surface --preview
uv run tools/advanced_suite.py calibrate --preview
```

The second command generates the priority set: both rudders, small propeller, small engine,
straight/angle pipes and enclosed straight pipe. Each definition gets 48 numbered cases with
XML, a JSON manifest and an optional PNG under `out/advanced-suite/calibration`. Use `--all-parts`
to generate every installed definition. Existing slope calibration and smoke tools remain available.

Check the manifest's `extent_metres_xyz` and choose a suitable workbench. Copy an exhibit XML
into the Stormworks vehicles directory to load it. White parts are the subjects, green blocks
are supports, and each orange/black pillar encodes the case number in binary, with the lowest
bit at the bottom. Cases increase along body x and then z. The exhibit is centred.

First inspect mounting and orientation. For rudders, verify the green support meets the fixed
base rather than the blade. Add suitable power and controls in game before checking movement,
steering sign, thrust or connections. These disconnected exhibits are editor checks; isolate
one supported assembly for spawning and operating tests.

Record a player's result using the exact `case_id` from its manifest:

```powershell
uv run tools/advanced_suite.py observe out/advanced-suite/calibration/calibration-rudder_surface.json CASE_ID --check mounting --result pass --note "Base contacts the transom"
```

Checks: `mounting`, `orientation`, `motion`, `connections`, `spawn`. Results: `pass`, `fail`,
`uncertain`. The command appends `.observations.jsonl`; it never silently promotes a pending
case to verified. The installed definition and original exhibit XML must still match their
manifest hashes. Record changes made in game in the note and retain the original exhibit.

`get_calibration_observations(definition)` reads this evidence for the AI, including conflicting
results and stale definition hashes. Set `SW_CALIBRATION_DIR` when keeping exhibits elsewhere.
Observations do not automatically change placement rules: reproduce a failure, correct the model,
and add a regression before accepting the new behavior. A fully working boat propulsion system
still needs explicit routing, wiring, controls and game verification.

## Report friction and failures

The MCP AI can call `complaint` when it hits a bug, confusing behavior, a missing feature or an
unhelpful tool result. Only `title` and `description` are required. An actionable report includes
the affected tool, expected/actual behavior, error messages, reproduction steps and relevant
arguments in `context`:

```json
{"title": "Fin rudder placement cannot find a mount",
 "description": "A transom has free space but the requested fin was skipped.",
 "category": "placement", "severity": "high", "tool": "preview_hull",
 "expected": "Base against the transom, blade extending aft",
 "actual": "The summary reports no fitting mounted location",
 "steps": ["Request rudder_surface in the propulsion stage", "Preview the vehicle"],
 "definition": "rudder_surface", "design": "test boat",
 "context": {"orientation": {"mount_normal": [0,0,1], "span_axis": [0,1,0]}}}
```

Each report gets a unique ID, UTC timestamp, runtime details, structured JSON and a readable
Markdown file. Reports live in `%APPDATA%/stormworks-hull-mcp/complaints` on Windows, or
`~/.local/share/stormworks-hull-mcp/complaints` without APPDATA. `SW_COMPLAINTS_DIR` overrides
the location. References are recorded as supplied, so issues can also describe missing designs
or unsupported parts; reports do not automatically attach vehicle files or saved designs.

`list_complaints(search, category, severity, offset, limit)` returns newest-first summaries.
`get_complaint(complaint_id)` returns full evidence and the Markdown report. Creation returns
the ID and both file paths. Reports stay local and can guide a reproducible test or fix; they
do not automatically create a GitHub issue or change vehicle geometry.
