# Road and land vehicles

For diagnosis, repair suggestions, reusable controls, diagnostic overlays and versioned
in-game checks, see [Diagnose, repair and verify a vehicle](vehicle-repair.md).

## Workflow

Start with `find_land_vehicles` to locate the player's saved wheel-based examples. Names are
not reliable: unfinished experiments can contain useful wheel mounts, seats or lighting.
`kind="tracked"` finds track-wheel examples separately. Aircraft and boats with road wheels
can also match; a saved arrangement is an observation, not a design rule.

Installed workshop vehicles are also supported: `find_land_vehicles(source="workshop")`,
then `analyze_land_vehicle(name="3812797708", source="workshop")`. Names for workshop
references are numeric item IDs, not file paths. Discovery checks every Steam library;
`SW_WORKSHOP_DIR` can point to a `workshop/content/573090` directory. This reads installed
content without downloading, modifying or copying it into the repository.

Use `analyze_land_vehicle(name="example")` for the actual body-local layout. Preview with
`preview_game_vehicle` or `inspect_view`. Multi-body analysis keeps each body's coordinates
separate; the current general saved-vehicle renderer does not solve articulated transforms.
For an existing single-body v3 vehicle, use `import_vehicle` to make a separate editable draft.
`import_vehicle(name="3812797708", source="workshop", design="quad study")` preserves the
original component settings, nested controllers and links. Multi-body editing is unsupported.
Configured or linked original components remain protected from geometric edits.

For a new vehicle, call `create_land_vehicle(design="road draft", spec={...})`, then
`query_parts` → `edit_parts` preview → `edit_parts` with `commit=true` and the same revision.
`preview_vehicle` supports close-ups; `analyze_land_vehicle(design="road draft")` checks the
draft before saving. `save_vehicle` writes the game vehicle when ready. New drafts default to
the utility buggy below; select `preset="chassis"` for the bare parametric chassis. Both are
placement drafts. `preset="humvee_4x4"` is the preferred four-seat example; it leaves doors
open for custom fitting. `humvee_4x4` and the older `utility_4x4` include connected engine, radiator, drivetrain and
control/electric systems. Use the connection tools below for custom builds and run preflight
before saving. Connected geometry still needs testing in game.

## Component previews

Image previews and `open_in_viewer` read the player's installed version-7 component meshes. Tyres, seats, engines,
premade tanks, batteries and lights are drawn as their component shapes rather than editor
footprint cubes. Missing or unsupported assets fall back to footprint geometry and are named
in the returned preview note. Meshes never change collision, mounting or sealing geometry.

Use `preview_vehicle(design="buggy", layer="components", yaw=35, pitch=25)` to hide bodywork
and inspect its equipment. `layer="structure"` isolates building blocks and slopes. Queries
and edits still refer to the complete assembly. Paint/material mapping is approximate;
spotlights are shown in a neutral pose, wheel tyres at default size and neutral suspension.
Manual doors include their moving leaf. `preview_vehicle(..., door_state="closed")` is the
default; `door_state="open"` gives an approximate open inspection pose. Missing moving meshes
are reported. Sliding leaves are aligned to the declared moving voxels. Paint is approximate.
This is a geometry preview, not proof of illumination, tyre scaling or game physics.
The interactive viewer receives these meshes from the local MCP worker. A standalone viewer
opened without MCP cannot read the installed assets; it reports its component fallbacks.
`open_in_viewer(design="buggy")` supports land drafts and `source="workshop"` supports references.

`preview_game_vehicle(name="3812797708", source="workshop")` and `inspect_view` also read
installed workshop items. For an articulated vehicle, previews show its largest body alone
unless `body_id` selects another body; they do not concatenate unrelated body-local frames.
Read-only previews display finite XML-scaled component transforms. Analysis reports these
components as omitted from footprint/mounting checks; editing still requires standard rotations.

## Humvee example

```json
{"preset": "humvee_4x4", "bench": "S", "color": "C5AF7A", "accent": "343B3F"}
```

This original four-seat layout keeps all four side door bays empty for the user to fit
custom doors. Choose proportions and seat access before picking a door: a stock sliding
assembly is 1.75 m tall and includes a storage pocket, which is much larger than its usable
opening. Do not enlarge the cabin to accommodate it. The example uses smaller 3x2x2 angled
windshield/rear panes and 2x2 quarter windows, a low hardtop, raked rear, sloped hood,
recessed grille, wheel arches and narrow supported sills. Its four 5x5 suspension wheels
mount close to the centreline; a rear spare is mounted separately. Road wheelbase is 3.5 m.

The prebuilt small engine faces its shaft directly into an inline clutch and cube Gearbox 1x1.
Their connections require no intermediate pipe pieces. Short isolated engine-bay hoses
join the radiator, air filter and exhaust. Fuel runs from a filled premade medium tank
behind the rear axle. The underfloor driveline and fuel channel use enclosed pipe blocks;
the air intake also passes through an enclosed block in the cowl. No pipe blocks share
an occupant bay, and unrelated fluids remain separate. The default example contains
44 pipe pieces (33 enclosed) and 23 typed control/electric links. Run preflight after edits.

Controls match the connected utility example below. Supported options are `preset`,
`bench`, `color`, `accent`, `wheel_settings`, `components` and `edits`; dimensions are fixed.
Door bays remain open and are not sealed compartments. Preview from both sides, front,
rear and below before export; then test tyre clearance through steering and suspension,
seat entry, visibility, starter/reverse and cooling in game. The preview shows neutral
wheels rather than a swept suspension model.

## Connected utility 4x4 preset

```json
{"preset": "utility_4x4", "bench": "S", "color": "C5AF7A", "accent": "343B3F"}
```

This original layout plans the cabin around four actual seats, supported side entries and
larger `wheel_advanced_5_sus` tyres. It has a raked windshield, a low roof with beveled edges,
four full sliding-door assemblies, step boards, fenders, bumpers and a hinged hood service
panel. The starter battery sits in an accessible rear service bay. The engine bay has a
prebuilt small diesel engine, radiator, air intake and exhaust; fuel comes from a filled
premade diesel tank. All four wheels connect through a clutch and gearbox. Required physical
pipe exits stay clear and separate fluid circuits do not share pipes.

The template includes typed electrical and control links. Axis 1 steers (the left input is
inverted), Axis 2 supplies nonnegative throttle and clutch engagement, trigger applies the
brakes, hotkey 1 operates the starter while held, hotkey 2 toggles lights, and hotkey 3 switches
the gearbox for reverse. Check steering signs, reverse ratio, starting and cooling in game.
The template uses a standalone cube `modular_engine_gearbox_1x1` and simple function gates; it does not
simulate engine load or implement an automatic transmission/governor.

Supported options: `preset`, `bench`, `color`, `accent`, `wheel_settings`, `components` and
`edits`. Layout dimensions are fixed; use `chassis` for custom dimensions. This is a connected
utility layout, not a licensed Humvee replica. Game assets and workshop vehicles are never
copied into it. Run `preflight_vehicle` after changes.

## Utility buggy preset

```json
{"preset": "utility_buggy", "bench": "S", "color": "D5A928", "accent": "303840"}
```

This original layout uses four `wheel_advanced_3_sus` components, a `seat_saddle`, two
`searchlight_small_2` headlights, two `small_light` rear markers, two `fluid_tank_small`
premade tanks, an `engine`, a `battery_small` and a `fluid_radiator`. It has a narrow chassis,
axle crossmembers, supported side footboards, beveled wheel fenders, a sloped nose, bumpers
and a rear engine cover with an opening for the engine's power connection. Its editor footprint
is 4.25 m long, 2.25 m wide and 1.75 m tall,
with a 2 m wheelbase; it fits S. All components must be available, fit and mount before a
draft is written. The builder never silently drops a required component.

The layout has fixed dimensions. Supported options are `preset`, `bench`, `color`, `accent`,
`engine_cover` (boolean; default true), `wheel_settings`, `components` and `edits`.
`wheel_definition` currently only accepts `wheel_advanced_3_sus`; use the chassis for other
wheel sizes and axle layouts. The saddle faces +z using the observed workshop convention
because its installed definition leaves the seat vectors unset. Side access is checked as
a supported 0.75 m passage. The small battery needs clear service space above it.

Tank settings request `fluid_type=1` and `fluid_fill=1`; verify the diesel selection/fill in
game. The parts are mounted but unconnected. Complete fuel, air, exhaust, cooling, clutch,
gearbox and wheel RPS paths plus electrical/control links before calling it a working vehicle.
Preset variants and added bodywork must be checked again through steering and suspension travel.

## Parts

`search_land_parts(category=...)` exposes installed footprints, masses and actual ports:

| Category | Useful components |
| --- | --- |
| wheels | Road wheels with/without suspension, older wheels and unpowered landing wheels |
| tracks | Track wheels and drive wheels; separate from the road chassis builder |
| controls | Driver seats, passenger seats, buttons and instruments |
| lights | Marker lights, RGB lights and spotlights |
| propulsion | Electric motors and the small/medium/large prebuilt diesel engines |
| transmission | Clutches, gearboxes, torque sensors and pipes |
| power | Batteries, generators and electrical parts |
| fuel / cooling | Premade tanks, fuel/fluid parts, pumps and radiators |
| body / utility / logic | Blocks, windows, doors, pivots, winches, connectors and control parts |

These are family filters. Use `search_parts` for the permitted catalogue, then
`get_part_definition` to inspect the exact installed part. No game definitions or personal
vehicle XML belong in the repository.

New placement only offers prebuilt engines: `engine` (small), `aircraft_engine` (medium),
`engine_diesel` (large). Modular engines are disabled. Standalone cube gearboxes are allowed
despite their `modular_engine_gearbox_` IDs; use `modular_engine_gearbox_1x1` for compact road
vehicles. Deprecated `torque_gearbox`/`torque_gearbox_2` remain readable in references but are
excluded from new placement. Cooling only offers `fluid_radiator`,
`fluid_radiator_electric` and installed electric radiator sizes. Heat exchangers and heat sinks
are disabled. These restrictions apply to catalogue choices, component placement and exact
add/replace edits. Existing vehicles and workshop references remain readable, including their
restricted parts; reading a reference does not offer those parts for new placement.

All new prebuilt engines explicitly write `max_force_scale=1`, meaning **100% power**.
The player confirmed that omitting this setting made a fully connected Humvee crank without
starting; their corrected `humveeai` save supplies `max_force_scale="1"`. Explicit numeric
derating from 0 to 1 remains available. Preflight reports missing/zero/invalid imported power
without changing the imported vehicle. When diagnosing a crank-only engine, inspect its
settings as well as fuel, air, exhaust, cooling, electrical supply and controls.

New gearboxes explicitly use `gear_ratio_1=1` (**1:1 forward with Gear Switch off**) and
`gear_ratio_2=0` (**1:-1 reverse with Gear Switch on**). The player confirmed that the old
off/on indices 0/1 made W drive backward despite corrected wheel placement. These are editor
ratio indices, not literal gear ratios. Explicit alternate editor indices remain available;
only indices 0/1 have a decoded ratio here. `get_part_definition` exposes both setting
defaults, and `preflight_vehicle` reports `gearbox_configuration_checks` with saved off/on
states and warnings for missing/invalid settings or a reverse off ratio. Imports are unchanged.
These checks describe each gearbox's stored state; check actual shaft direction and any
control inversions in game, especially with multiple gearboxes.

Use `get_part_orientation` before choosing a rotation. Powered road wheels expose `axle_axis`,
`mount_normal`, `wheel_reference_up`, `wheel_forward` and `wheel_positive_steering`.
The reference up/forward describe the neutral editor arrow frame, rather than suspension
travel. Mount direction alone cannot determine drive direction. Constrain all three:

```json
{"axle_axis": [1,0,0], "wheel_reference_up": [0,1,0], "wheel_forward": [0,0,1]}
```

For the right wheel in a +z-forward body this needs a mirrored placement. The solver returns
an effective matrix plus proper `r` and `mirror=2` (local axle/y reflection), matching the
provided workshop quad. New wheels write `r` explicitly, even where the game editor omits it.
All four drive arrows then point forward. Seat Axis 1 is A=-1, D=+1; Axis 2 is W=+1, S=-1.
The installed steering arrows and workshop quad call for **left steering inverted, right
steering direct** with this frame. Mirroring the axle aligns drive arrows, but does not by
itself align both positive steering arrows. A different observed in-game pairing can be
calibrated separately; do not infer signal signs from mounting alone.

`query_parts` includes scalar settings, a proper `rotation` string, a local `mirror` bitmask
and the effective `transform` matrix. Added parts accept either the effective matrix or
proper rotation plus mirror. `analyze_land_vehicle` includes per-wheel direction checks;
`preflight_vehicle` checks the arrow frame and traces simple direct/inverting steering paths.
Unknown controller/function logic stays unknown. These checks assume positive wheel RPS;
they do not simulate gearbox sign, tyres or suspension. Check W forward, A left and D right
in game after changing rotation or wiring. Tests cover all eight advanced wheel variants
in 24 vehicle frames on both sides, and a connected Humvee at all four horizontal headings.

A wheel's `dynamic_rotation_axes` describes its axle, not a suspension steering hinge.
Mounted spotlights expose `light_forward` from the definition and `mount_normal` from their
attachment surface. Ordinary omnidirectional marker lights have no meaningful narrow beam.
Some spotlights omit an explicit beam vector; their reported direction remains unknown until calibrated.
Generic definitions often contain unused default direction fields; irrelevant seat, door,
light and dynamic axes are filtered.

## Chassis spec

Land dimensions are actual game metres on the **0.25 m grid**, without hull scaling. The fixed
build frame is **+y up, +z forward, x lateral**, with the chassis top at y=0. Query/edit tools
use integer blocks in that frame. Export is centred on the workbench; those shifted export
positions should not be fed back into the draft editor.

```json
{
  "preset": "chassis",
  "length": 4.25,
  "width": 1.25,
  "thickness": 0.25,
  "color": "4B5563",
  "bench": "S",
  "wheel_definition": "wheel_advanced_3_sus",
  "axles": [{"z": -1.25}, {"z": 1.25}],
  "driver": true,
  "headlights": true,
  "tail_lights": true
}
```

Width is the chassis plate width, not the overall vehicle width: wheels extend outside it.
The default assembly uses `seat_racing`, `searchlight_small_2` and `small_light`, loaded from
the installed game. `driver`, `headlights` and `tail_lights` can be false to omit them or objects
with `definition` and scalar `settings`; `driver` also accepts a `position` in metres.
Each axle can override its wheel `definition` and scalar `settings`. There must be 2–8 distinct
axle stations inside the chassis. Footprint collisions and missing mounts fail the build.
Small dimensions can prevent the driver/access area or component pairs from fitting.

`components` accepts additional named parts with `definition`, `position` in metres, `color`,
scalar `settings`, and either `rotation` or semantic `orientation`. Components must fit their
installed footprints and mounting/access requirements. Settings are serialized, not inferred
or proven valid by their appearance in someone else's save. Use edits for additional bodywork,
window openings, complete door assemblies and powertrain mounting blocks.

To change chassis dimensions or axle stations, create another draft from the revised spec.
For changes to individual pieces use the existing part editor, including batch additions,
fills, replacements, copies and undo. New drafts never overwrite existing drafts or saves.
Land records made before presets were introduced keep their original bare chassis layout.

## Layout evidence

`analyze_land_vehicle` groups road wheels at equal longitudinal mounting stations per body.
It reports wheelbase between the outer stations, mounting span and heights, wheel orientations,
contact samples, saved settings, lighting axes and component ports. Select `section="lights"`,
`"controls"`, `"equipment"` or `"issues"` for focused, paginated evidence; `body_id` selects a body.
Forward comes from a unique driver-seat facing, or an explicit fallback to +z. Override with
`forward=[0,0,-1]` (or ±x) when the vehicle frame differs. Read the reported `forward_source`.
Inventory includes spares and excluded wheels, but axle measurements only include road roles.
Names containing `spare` provide a reported default; other wheels default to road. Override
with `wheel_roles={"part_id":"spare"}` (values: `road`, `spare`, `excluded`) or
`exclude_wheel_ids=["part_id"]`. Use IDs returned by the wheel inventory; draft analysis also
accepts the stable IDs from `query_parts`. Invalid/stale/non-wheel IDs are rejected.

Mount span is **not tyre-centre track width**. Editor bounds are not ground clearance.
Articulated transforms, steering sweep, suspension travel and XML-scaled wheel meshes are not
modeled. A geometry report cannot establish roadworthiness or whether the power/control
connections function. Use `analyze_vehicle` for link and controller evidence.

## Seats and access

All land builds and land edit paths use the same access rules, including passenger seats.
A seat needs mounting contact and either a supported side passage or supported rear approach.
The side entry model is 0.75 m wide, with at least 1.25 m vertical clearance (or the installed
seat's full height if taller) for a seated/ducked entry. It requires a supported 0.75 m threshold,
rather than a 0.75 m deep boarding platform outside the body. The approach beyond that sill
stays clear; terrain and character movement are not simulated. The generic rear approach
uses 2 m clearance. Manual door leaves are treated as open for access checks,
while their frames remain obstacles. This is a conservative placement envelope, not a
simulation of the character entering the seat. Fit doors and steps to the actual access cells.
Failures report blocked cells, obstructing part IDs/definitions and missing floor support.
Small batteries need two clear blocks above their footprint for service access.

## Connections and subsystem preflight

`query_connections(design="road draft")` returns the revision, installed/configured wire
ports and physical transmission faces. It supports configured controller node IDs and
reports unresolvable original links without silently assigning a different port.

Wire endpoints use `{part_id, port}`. `edit_connections` accepts atomic operations:

```json
[
  {"op":"connect", "from":{"part_id":"output-id","port":0},
   "to":{"part_id":"input-id","port":1}},
  {"op":"disconnect", "link_id":"source:0"}
]
```

Port types must match. Signals connect output to input, with one source per input; electrical
links are bidirectional. Duplicate connections are rejected. Physical RPS/fluid nodes cannot
be drawn as wires. New links serialize transformed voxel positions and follow later moves of
generated components. Disconnect links before deleting an endpoint. Import settings, nested
controllers and untouched original links remain lossless.

Mechanical power, diesel, air, exhaust and coolant use actual pipes. The developers' [advanced
vehicle update](https://store.steampowered.com/news/posts/?appids=573090&enddate=1540567947)
documents physical pipes replacing power/fluid logic links. `route_connections` takes a list:

```json
[
  {"from":{"part_id":"engine-id","surface_index":12},
   "to":{"part_id":"clutch-id","surface_index":0},
   "bounds":[[-5,-3,-12],[5,6,14]], "name":"engine shaft"}
]
```

Read the actual surface indices from `query_connections`; example indices are placeholders.
Bounds and optional `waypoints` are integer blocks in the draft frame. The bounded router
avoids component footprints, occupied structure, access/service cells and unused equipment
port exits. It minimizes route length first, then bends including the equipment-facing end
bends. It chooses straight/corner pieces with exactly the required facing ports. `pipe_style`
can be `exposed`, `enclosed` or `auto` (default). Enclosed variants provide full attachment
and sealing faces around the pipe, useful in floors and chassis rails. Auto uses exposed
hoses in free space and enclosed pieces at explicitly selected wall crossings.

To cross an existing wall, query its blocks and supply `through_blocks=["block-id", ...]`.
Only those unconfigured, unlinked `01_block` parts can be replaced, with their paint retained.
All selected blocks must be on the final path; add their positions as `waypoints` when needed.
Other walls remain obstacles. Preview shows the replacements before commit, and removing
the route restores the original blocks. Never use omni pieces to hide a port-direction mistake.
For a branch, place a real T-piece
and route to its free faces. Blocked exits report the cell and obstructing part ID. Routes
can be removed with `{op:"remove",route_id:"route:0"}` using IDs from the query, then rerouted.

Both editing tools default to preview. Use `commit=true` with the same revision to persist;
`undo_edits` restores the previous part, wiring or routing batch. Stale revisions fail before
writing. Export preserves imported originals and resolves new links in the centred export frame.

`preflight_vehicle` checks engine-to-wheel paths through clutch/gearbox, fuel from a filled
premade diesel tank, intake and exhaust, a closed radiator circuit without a bypass, electrical
power and required controls. It also checks fluid circuit isolation and reports blocked
transmission faces. Radiator and tank passages are modeled internally; distinct engine ports
are never merged just because they belong to the same part. Clutch/gearbox traversal is
conditional on control state. `connected geometry` establishes topology; it does not establish
cooling capacity, braking or game operation. Engine power, saved gearbox states and supported
wheel/steering paths are reported separately; they do not simulate the running powertrain. Named spare wheels
are excluded from driving requirements; a spare's face mounted against bodywork is reported
separately rather than as a blocked road-wheel drive port.

## Seal coverage

`get_part_definition` returns `seal_coverage` before placement. Angled windows using calibrated
45-degree shape-6 surface frames are modeled as thin planes splitting air cells, including
rotations/reflections. They do not become solid footprint cubes. Other unsupported surface
frames or moving geometry stay `indeterminate`. Use `check_seal` with cabin seeds after
bodywork edits, then verify the game's compartment behavior.

## In-game checks

Load a separate test copy and check these before extending the build:

1. Every wheel faces outward, attaches to the intended body, and supports the chassis.
2. Front/rear axle spacing and tyre clearance still work through full steering and suspension travel.
3. Steering turns both sides correctly; determine control signs in game before connecting them.
4. Complete motor/engine → clutch/gearbox → wheel RPS routing, power, braking and reverse controls.
5. The driver is accessible; visibility and doors work with the added bodywork.
6. Connect light switch/electric inputs. Check headlight beam direction, illumination and rear
   light colour; red paint alone does not establish red emitted light.

Keep failures and successful calibration results separate from saved examples.
