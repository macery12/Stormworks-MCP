# Hull smoothing and depth: choosing the right blocks

The goal is a coherent surface with the intended depth. Count neither more wedges nor
more parts as an improvement. Inspect the underside, bow, stern, and cross sections.

## Measure before choosing pieces

1. Establish length, beam, keel baseline, main deck/rim, walking floor and cabin floor.
   Hull `depth` is keel-to-midship-deck; it is not cockpit depth, draft or total ship height.
   `sheer` raises the local rim, so a level floor can have a much deeper bow well.
2. Use `analyze_hull` at stern, midship, bow and slope transitions. Procedural `stations`
   and `x` are integer blocks in the uncentred build frame. Saved vehicles use their own
   body-local frame. Returned material intervals describe actual solid surfaces, not the
   bounding boxes of wedges. Convert a build surface y to height above keel with `(y+0.5)/4`.
3. For an open hull, set `interior.decks` explicitly if the walking floor should be above
   the bottom skin. Its heights are top-of-floor metres above keel, in game units by default.
   Specify the intended drop from the rim and bottom-to-floor depth separately. Do not
   fill the whole bilge solid to raise a floor: add a one-block plate at the requested height.
   On open decks with explicit walking floors, fixture bases get minimal vertical supports
   at their outboard edges when needed. Read their reported choices and inspect clearance.
4. Look at both transverse sections and the longitudinal profile. A top view can hide a
   deep bottom, an excessively raised bow, or an unsupported floor. A geometric gap alone
   does not establish headroom, access, watertightness or buoyancy.

## Choose a surface family, then its position

| Desired local surface | Use | Avoid |
| --- | --- | --- |
| Flat floor, roof, vertical wall, intentional chine | Blocks and preserved plate edges | Chamfering a sharp edge because an averaged normal looks diagonal |
| A face slopes in one direction | Wedge 1x1, 1x2 or 1x4 | Pyramids alternating sideways to imitate a simple wedge run |
| A face slopes in two directions | Pyramid and inverse-pyramid family, joined on matching partial faces | An isolated pyramid against full blocks, or mismatched triangle edges |
| Two sloped wedge runs meet at a convex corner | Test a pyramid of the matching run size and orientation against both adjoining faces | Extending one side's wedge through the corner or leaving a protruding cube |
| Long shallow uniform run | Longer pieces if the full footprint fits | A 1x4 piece across a rapidly changing bow curve |
| The side edge of a 1x4 run | Matching pyramid/inverse closeout or a shorter wedge run | An exposed partial side face repeated down the edge |
| Changing curvature or a transition | Progressively different slope families, checked from both axes | Jumping between opposite rotations to gain a few volume samples |
| Walking floor or clearance next to the skin | Full floor cells and solid backing | Letting the large corner of an inverse pyramid cut into the floor |

Wedges provide slopes 1:1, 1:2 and 1:4 (45°, 26.565°, 14.036°), in any axis-aligned
rotation. For a plane `y = c - x/a - z/b`, the normal is proportional to `(1/a, 1, 1/b)`.
The corner catalogue includes a/b combinations 1/1, 1/2, 1/4, 2/2, 2/4 and 4/4,
including exchanged axes. Call `suggest_hull_blocks` with the **outward** normal.

For example, `{"normal":[0,1,0.25]}` selects the 1x4 wedge family; `[0.5,1,0.25]`
selects the 2x4 pyramid/inverse family. The tool supplies representative rotations, mirror
flags, footprints and plane offsets. A normal describes an angle; **the plane intercept
and material side determine which piece and which origin fits**. Pyramid and inverse
can have the same outward normal but different material volume and plane position.
Chiral 2x4 corners sometimes require mirror flags, not just another rotation.

Matching angles alone do not make a smooth joint. Compare the same world face on both
parts, including rotation and mirror. A pyramid can join an inverse of the same family
to continue one plane; smaller/larger families can meet where their triangular coverage
agrees. Leave a deliberate crease when the target has one. Never force a longer part
through a differently coloured patch, functional plate, opening, or empty target cell.

## V2 and its guard

Use `"smoothing":"wedges_v2"` for the optional V2 path. It bisects continuous boundary
crossings within each partial voxel and fits a local plane, including its position.
Uncertain or creased cells keep the original normal logic. V2 weights shape volume more
strongly, considers more candidate fits, and penalizes mismatched joins more strongly.
Both slope modes protect interior plates and their immediate backing.

V2 builds both final skins, including their seal backing, and measures partial-face seams
and wrong shape samples on identical target cells. It chooses the refined skin only if
one metric improves, seams do not increase, and sampled partial-cell volume error increases
by no more than **0.5 percentage points**. Otherwise it returns the original skin.

After that selection, V2 checks measured creases and their neighbouring partial cells.
It tests complete replacement footprints, including pyramid and inverse families of
the appropriate size. The score includes wedge ends facing empty air, which an occupied
joint count alone misses. Each accepted closeout reduces exposed-face error without
increasing either sampled volume error or occupied joint mismatches. Required backing is
included in that comparison. Floors, painted boundaries and carved openings stay protected.
The build summary reports accepted corner replacements and the final joint count.

Two wedge runs meeting at a corner are distinct from one plane sloping in two axes.
Preserve the intended intersection and test the actual neighbour coverage; a pyramid's
name or angle alone does not prove that its size, rotation and depth fit that corner.
The summary states which result was selected. This costs additional build time.

For a deckhouse, `corner_chamfer` creates a straight diagonal corner face, while
`corner_radius` makes a round plan-view corner. `roof_radius` rolls the top edge. These
geometry controls can give the fitter a more intentional surface, but combining a large
roof radius with tapered and raked walls is still difficult to tile cleanly. Review those
corners in a close-up preview. A long wedge should be selected with its side closeout in
mind; a good volume fit alone does not make its edge coherent.

These are approximation metrics. A seam can be an intentional edge, and a sample cannot
prove a subvoxel seal. Neither metric is a percentage of visual correctness. Keep reviewing
the preview and run geometric seal diagnostics and an in-game check before calling a ship finished.

## Study a saved reference without changing it

```json
{"name":"autosave9","source":"backups"}
```

Pass this to `analyze_hull` to read `Stormworks/data/backups/vehicles/autosave9.xml`.
The largest structural body is selected by default; use `body_id` for a different body.
Saved bodies are never merged into one coordinate system. Other components are excluded
and counted explicitly. Regular saves use `source:"vehicles"`, the default.

Use the returned block families, actual floor surfaces and joint examples to inform the
new design. Do not assume the reference's total part frequencies describe its exterior hull:
floors, superstructure, articulated bodies and machinery also contribute to those counts.

For repeatable comparisons run `uv run tools/smoothing_benchmark.py out/smoothing` or pass
`--preset NAME` / `--spec PATH`. It writes both images, section views and a JSON comparison.

## Research behind these rules

- [Building Better Boats: How to Design Hulls](https://steamcommunity.com/sharedfiles/filedetails/?id=3520606018)
  is a first-hand Stormworks construction guide with wedge curves, alternating pyramid/inverse
  runs and matching wedge/pyramid transitions. Its physics claims are not used as geometry proof.
- [US Naval Academy EN400 course notes](https://usna.edu/NAOE/_files/documents/Courses/EN400/EN400_Course_Notes_Summer_2020June.pdf)
  distinguish depth, draft, freeboard and the body, sheer and half-breadth plans. This motivates
  measuring more than one view and separating rim height from walking-floor height.
- [Official Benchy features](https://www.3dbenchy.com/features/) describe a smooth curved hull,
  bilateral symmetry and horizontal deck surfaces; its [multipart breakdown](https://www.3dbenchy.com/3dbenchy-for-dual-and-multi-part-color-3d-printing/)
  treats hull, deck and gunwale as separate features. Overall dimensions do not fix cockpit depth.
- Local read-only research inspected Benchy, its blocks version, USS Zumwalt, astras 3rd boat,
  README/MIRRORED calibration saves, and the player's nominated autosave9 reference. Large older
  non-v3 saves were skipped. No game assets or private vehicle XML belong in this repository.

See [the research results](hull-smoothing-research.md) for the measured comparisons and limitations.
