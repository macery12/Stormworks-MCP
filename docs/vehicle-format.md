# Stormworks vehicle file format

This page describes the parts of the Stormworks vehicle XML format that this project relies on.
Use it to read or write vehicle files from your own tools.

Everything here was worked out from 331 saved vehicles (303 in `data_version="3"`) and the 759 part
definitions shipped with the game (September 2026 build), then checked in game where noted. The
format is not officially documented, so treat anything marked **unknown** as unknown.

## Where the files are

| File | Location |
| --- | --- |
| Saved vehicles | `%APPDATA%\Stormworks\data\vehicles\<name>.xml`. An optional `<name>.png` thumbnail sits next to it; vehicles without one still load. |
| Part definitions | `<game install>\rom\data\definitions\<definition>.xml`. The file name without `.xml` is the `d` value used in vehicles. |

## Parsing: not quite XML

The game writes attribute names that start with digits, for example
`<local_transform 00="1" 01="0" ...>`. Standard XML parsers reject these. Either rename the
attributes before parsing (`re.sub(r' (\d\d)=', r' m\1=', text)`) or read the file with regular
expressions, as [swhull/vehicle.py](../swhull/vehicle.py) does.

## Structure (data_version 3)

```xml
<vehicle data_version="3" bodies_id="1">
  <authors/>
  <bodies>
    <body unique_id="1">
      <components>
        <c d="02_wedge"><o r="1,0,0,0,0,1,0,-1,0" sc="5,A52A2A,A52A2A,A52A2A,A52A2A,A52A2A"><vp x="3" y="-2" z="10"/></o></c>
        ...
      </components>
    </body>
  </bodies>
  <logic_node_links>
    <logic_node_link type="0"><voxel_pos_0 x=".." y=".." z=".."/><voxel_pos_1 .../></logic_node_link>
  </logic_node_links>
</vehicle>
```

Version 3 leaves defaults out: a missing `d` means `01_block`, a missing `x`, `y` or `z` on `vp`
means 0, and `<vp/>` is the origin. Version 2 files write every attribute (`bc`, `ac`, `t="0"`, ...).

**A missing `r` is not the identity rotation.** Multi-voxel wedges with no `r` extend along +y,
while an explicit `r="1,0,0,0,1,0,0,0,1"` extends along -z as the definition says. The default
behaves like `0,0,1,-1,0,0,0,-1,0`. A generator that omits `r` for unrotated parts gets every one
of them turned 90 degrees in game, so always write `r`.

## Component fields

| Field | Meaning |
| --- | --- |
| `c@d` | Part definition name. |
| `c@t` | **Mirror flags**: a bit per axis of the part's own frame (1 x, 2 y, 4 z), flipped before `r` rotates it, so `world = Mᵀ · F · local`. Confirmed from saves made with mirror mode (2026-10-01): mirrored across the centreline, an unrotated Pyramid 2x4 gets `t="1"` and one turned 90 degrees (`r="0,0,-1,0,1,0,1,0,0"`) gets `t="4"`, both keeping the original `r`, and each lands as the exact reflection of the original (footprint included). Blocks get it too. In code a mirrored part has an improper Q (`pieces.with_mirror`, `split_mirror`); the generator writes `t="1"` for those. It only matters for Pyramid 2x4 and Inverse Pyramid 2x4: every other piece's mirror image is one of its rotations. |
| `o@r` | Rotation: 9 integers, a row-major matrix M. `world = Mᵀ · local` (see [Rotation](#rotation)). |
| `o@sc` | Paint: `<surface count>,<colour or x>,...` with one entry per surface. **`x` means unpainted** (confirmed in game: `6,C,x,x,x,x,x` paints only surface 0). The count must match the part: block 6, wedge 5, pyramid 4, inverse pyramid 7, Wedge 1x2 9, Wedge 1x4 17, Small Engine 15, Large Engine 70. |
| `o@bc`, `o@ac`, `o@gc` | Base, additional and glow colours seen on some parts. Optional. |
| `vp` | Voxel position of the part's origin. 1 voxel = 0.25 m. |
| Other `o` attributes and children | Per-part settings such as `custom_name`, `logic_slots` and gear ratios. |
| `body` extras | Multi-body vehicles (hinges, pistons) add `initial_local_transform`, `local_transform` and compartment fire state. |

## Axes

Y is up, +Z is the bow, X is lateral. Every boat checked has its propellers at -Z. The workbench
origin is the centre of the build volume, as measured by the Coop Workbench mod, so this project
centres generated vehicles on (0, 0, 0).

The game's axes are **left-handed**. A renderer that assumes right-handed axes shows every
vehicle mirrored port to starboard unless it flips one axis. The renderers in this project negate x.

## Rotation

`r` is stored row-major as M, and a part's local vector maps to the world as `Mᵀ · local`.

Unrotated shapes, from the definition files:

| Part | Unrotated shape |
| --- | --- |
| `02_wedge` | Full faces at -y and +z; the slope faces +y/-z. |
| `05_wedge_2`, `08_wedge_4` | The same ramp stretched over local z = 0..-1 and 0..-3; the tall end is at z = 0 (the origin). |
| `03_pyramid` | Corner tetrahedron with its solid corner at (+x, -y, +z). |
| `04_invpyramid` | A cube with the (-x, +y, -z) corner cut off. |

Evidence from the saved vehicles, counting only parts with an explicit `r`:

- The footprint of Wedge 1x2 and 1x4 (local -z) never collides with other parts under
  `Mᵀ · local` for 11 of 12 well-sampled rotations; under `M · local` about 21% collide.
- In that frame, a wedge's sloped sides (+y, -z) touch a neighbour 11-13% of the time, its
  triangle ends (±x) 91%, and its full faces about 55%.
- In staircases, the voxel beyond the tall end of a Wedge 1x2 / 1x4 is filled 41% / 63% of the
  time; the voxel beyond the low end, 7%.
- Surface orientation codes in the definition files (0..5 = +x, -x, +y, -y, +z, -z) agree.

**Confirmed in game:** all 40 orientations in the `hull test orientations` vehicle sat flush:
every rotation of the Wedge (12), Pyramid (8) and Inverse Pyramid (8), and 6 each of the
Wedge 1x2 and 1x4. See [In-game testing](in-game-testing.md).

## Part definitions

Each definition has `mass`, a voxel footprint (`voxels`), paintable `surfaces`, and
`logic_nodes` with a label, type (0 on/off, 1 number, 5 composite, 6 video, 7 audio, ...),
mode (0 output, 1 input), description and voxel position. That is enough to place parts and to
wire them with `logic_node_links`. Wiring is not implemented in this project yet.
