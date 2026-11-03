# Building any Stormworks vehicle

This server reads and writes Stormworks vehicle files. It can build whatever the player asks
for: a boat, car, truck, plane, jet, helicopter, flying car, or one assembly such as an engine.
Build it the way the player describes it. The habits below under "Style rule sets" are optional
checks, never requirements.

## Workflow

1. **Talk it through.** Ask what the vehicle is for, its rough size, and which workbench the
   player builds at (`list_workbenches`) when size matters.
2. **Start a draft.** Pick whichever fits:
   - `create_vehicle(design, preset="empty")` for a blank draft (one block at the origin).
   - `create_vehicle(design, preset=...)` with a land preset (`chassis`, `utility_buggy`,
     `humvee_4x4`, `utility_4x4`) as a starting point. `get_guide(topic="land")` explains them.
   - `import_vehicle(name, design)` to copy any saved vehicle, with all its bodies. The
     original file is never changed; XML-edited (stretched) parts come along protected and unchanged.
   - The boat hull generator: `preview_hull`, `store_design`, `save_hull` (`topic="hull"`).
3. **Find parts.** `search_parts(search, category)` lists installed parts by family (body,
   wheels, surfaces, propulsion, transmission, fuel, cooling, power, controls, lights, sensors,
   logic, mechanics, weapons, utility). `get_part_definition` gives one part's voxels,
   surfaces and ports, and `get_part_orientation` solves the rotation for a mounting direction.
4. **Edit.** `query_parts` gives ids and the revision. Then `edit_parts` previews a batch, and
   `edit_parts(..., commit=true, revision=...)` applies it as one undo step (`undo_edits`).
   Reuse finished pieces as prefabs (see "Prefabs" below): `paste_prefab` places one.
5. **Connect.** `query_connections` lists ports. `edit_connections` adds wires,
   `route_connections` lays pipes and shafts, and `apply_vehicle_assembly` wires a whole
   starter, clutch, brake or light set-up.
6. **Check.** `preflight_vehicle` checks connected systems and lists parts it cannot check yet
   as `unchecked`. `check_seal` tests watertightness. `analyze_physics` estimates mass, centre of
   mass, how it floats with tanks empty and full, thrust-to-weight and wing lift. `preview_vehicle` and `inspect_view`
   render the draft: look at the image yourself.
7. **Save.** `save_vehicle(name, design)` writes a new file to the player's vehicles folder.
   `prepare_vehicle_validation` exports a test copy with an in-game checklist.

The game is the only real test. Tell the player what to check in game for anything you changed.

## Game facts

These come from the game and its file format, and the server follows them on every write:

- One block is 0.25 m. Edits use integer blocks. Draft frame: x across, +y up, +z forward.
- The game's axes are left-handed; previews mirror x for display.
- Every component gets a rotation `r`, and every surface gets a paint colour.
- Parts must attach to the vehicle. A group that touches nothing splits off in game, and
  builds warn about it.
- The two gearboxes the game deprecated (`torque_gearbox`, `torque_gearbox_2`) cannot be
  placed. Use `modular_engine_gearbox_1x1`, `3x3` or `5x5`.

Useful settings and controls:

- Gearbox: off uses `gear_ratio_1` (1 = 1:1 forward), on uses `gear_ratio_2` (0 = 1:-1
  reverse). Prebuilt engines use `max_force_scale` (1 = 100% power).
- Seat Axis 1 is A = -1, D = +1. Axis 2 is W = +1, S = -1.
- Wheels steer themselves. Their drive direction needs `wheel_forward` and
  `wheel_reference_up` targets (`get_part_orientation`), so check preflight
  `wheel_direction_checks` after rotating or wiring wheels.
- A Fluid Spawner saved without `fluid_type` fills its sealed pocket with diesel.

## What preflight checks

Preflight follows wires and physical pipes for prebuilt engines (fuel, air, exhaust, cooling),
drivelines to wheels or propellers, electric power, gearbox ratios and wheel directions.

Modular engines are checked through the couplings the game joins them with: cylinders on the
crankshaft, each cylinder's manifolds reaching an air, a fuel and an exhaust manifold, a starter
on a drive belt, a clutch on the crankshaft line and what its shaft reaches, throttle, starter
and clutch wires, the air intake and exhaust outlet, and a fuel line into a tank holding diesel
(block-built tanks count). An engine without a coolant manifold is noted: it is not liquid
cooled. `modular_engines` in the report summarises each engine.

Jet engines, rockets, steam power and heat exchangers are placed normally but listed under
`unchecked`, because preflight does not model them yet.

## Prefabs

Any saved vehicle can be a prefab, so a prefab can be loaded and tested in game on its own.

- `create_prefab(name)` registers the vehicle called `name`. `create_prefab(name, vehicle,
  bounds, follow)` cuts every part reaching into a box out of `vehicle` into a new vehicle file
  `name` (the source is never changed). `follow=["pipes"]` also takes the pipe and shaft pieces
  joined to the cut; `follow=["wires"]` takes the parts wired straight to it, such as its
  microcontroller. Wires inside the cut are kept.
- A prefab's connection points are its logic nodes with no wire and its open pipe and shaft
  ends. They get names such as `throttle`, `fuel_line` or `rps_shaft`; `rename` changes them.
  The names live in a side file in the server's data folder, with the file's hash, so a
  changed vehicle file is noticed.
- `paste_prefab(design, prefab, position, rotation?)` puts the prefab's lowest corner at
  `position`. Parts are copied exactly, microcontrollers included, and the wires move with
  them. Its main body joins the body it touches; its other bodies become new bodies. An
  overlap is refused unless `replace=true`. The result lists the connection points as draft
  part IDs with ports or surface indices, for `edit_connections` and `route_connections`,
  and any pasted groups that touch nothing else (they would fall off in game).

## Tanks

`edit_parts` with `{op:"tank", seed:[x,y,z]}` turns the closed space around an empty cell into
a tank: it adds a Fluid Spawner on its floor set to `fluid` (water, diesel or jet_fuel) and
`fill` (0-1). `{op:"tank", bounds:[[lo],[hi]]}` first builds a box of blocks with those outer
corners. Either way the tank must seal, and the reply gives its litres (one empty block holds
15.625 L). `import_vehicle` lists every tank of the copied vehicle with its litres.

## Bodies (hinges, pivots, pistons)

A vehicle can have several bodies on one shared grid. `query_parts` shows each part's body and
`select` takes `body`. A new part joins the one body it touches; give `body` (an ID or `"new"`)
when it touches two, or to start a separate body such as a missile on a hardpoint. Placing the
parent half of a hinge, pivot or piston (the `_a` or `base` part) adds its child half in a new
body at the right spot; build the moving part onto that child half. Edits that would separate
the two halves are refused. `preview_vehicle(view="bodies")` colours each body, like the game's
bodies view; `bodies=[...]` shows only some.

## Physics estimates

`analyze_physics` works on any draft or saved vehicle, including multi-body ones at their editor pose.
It uses the base game's constants (gravity 10, water density 1000, air density 1.225) and never
changes them. Floating weight is `mass x (10 + 10 x ramp)` kg, where the ramp grows from 0 at
mass 2,000 to 1 at mass 25,000. Sealed air and solid material both displace water; slope pieces
count by their exact shape. A sealed pocket with a Fluid Spawner is a tank, and tank fluid weighs
0.1 mass per litre. Lift counts wing and control-surface parts only: the game also lifts block
surfaces, so block-built wings are not included. The report lists every provisional value; treat
the numbers as estimates until they are checked in game.

## Style rule sets (optional)

These habits come from the player's own fixes to earlier boats. They are off by default.
Pass them as `preflight_vehicle(style=[...])`, or as `style` in a hull spec, to get warnings:

- `boat_engine_room`: engines enclosed by the hull below a deck, propellers and rudders not
  behind the transom.
- `bow_tip`: a near-symmetric hull is an exact mirror image, and its stem ends three wide.
- `pipe_colours`: exposed pipes painted by contents in ISO 14726 colours.

`get_guide(topic="style_rules")` lists them with their sources.

## Other topics

`get_guide(topic="topics")` lists every topic, including the boat hull generator (`hull`,
`hull_spec`, `hull_smoothing`, ...), land vehicles (`land`), exact edits (`edits`) and what
has been tested in game (`testing`).
