# Surface design plan

## Reference observations

The player's three hand-built boats and the MCP-generated Zumwalt and LPD-17 were inspected
read-only. The screenshots show long wedge runs terminating in repeated notches, stepped
bands along curved hull surfaces, and weak transitions at tapered deckhouse corners. The
Zumwalt structural body contains 6,961 1x4 wedges; 6,893 are below its upper hull layers.
Its 1x4 side-face mismatches are concentrated in the hull, not the superstructure. Counts
alone do not prove a seam is bad: some partial faces are intentional edges.

The hand-built `Green_Test.xml` isolates a useful 1x2 corner: a wedge joins a pyramid,
then pyramid/inverse/pyramid/inverse pieces alternate one cell at a time diagonally.
Every shared partial face in that green run matches. The same relative placement and
rotation also makes valid 1x1 and 1x4 runs. Four green-to-orange floor joints are partial
face mismatches; they are outside the green corner itself.

`Green_Test_01.xml` adds two structure options. The red vertical chamfer is made from
sideways 1x1 wedges. The pink corner places vertically flipped 1x2 inverse pyramids
above the green inverse pyramids; all three inverse-to-inverse height joins have matching
partial faces. The two pyramid-to-pyramid height joins are also matched. This suggests
a deliberate inward-and-outward wall profile, not arbitrary corner repair.

## Working design

1. **AI chooses features.** Specify stations, chines, sheer, structure footprint, corner
   treatment, roof treatment, and which edges should be faceted. The MCP should show the
   proposed dimensions and block families before final export.
2. **MCP lays out compatible runs.** Partition each continuous surface into planes or curved
   bands. Choose a wedge family for each run and solve both side closeouts with compatible
   pyramid/inverse pairs. A 1x4 wedge should not win solely because its four-cell volume
   error is low.
3. **MCP verifies complete joins.** Check actual rotated partial faces, exposed run edges,
   sampled silhouette error, colour boundaries, floors, openings, and seal backing. Reject
   a replacement that introduces a gap or consumes protected interior space.
4. **AI critiques previews.** Show close-ups of bow, stern, underside, chine, deckhouse
   corners, and roof edges. The AI adjusts design features and reruns the fitter. Exact part
   edits remain available for local finishing.

## Current implementation

- `corner_radius`, `corner_chamfer`, and `roof_radius` give the AI explicit structure design
  options. Defaults remain sharp and compatible with existing specs.
- `waist` gives a box a specified inward-and-outward wall indentation. A 0.25 m inset with
  its peak 0.5 m above the start and 0.5 m below the end produces four matched stacked
  1x2 inverse-pyramid pairs in a generated chamfered deckhouse test. A 0.25 m vertical
  chamfer also produces sideways 1x1 wedges.
- The V2 corner pass also considers mismatched occupied joins and exposed 1x4 wedge faces,
  with a bounded candidate set and the existing shape and joint guards.
- The corner pass can now propose a complete wedge/pyramid/inverse diagonal as one
  replacement. A focused 1x2 and 1x4 test recovers the whole intended pattern from a
  wedge with block-filled corner cells. It does not yet change the tugboat, runabout, or a
  rounded sample cabin because their sampled target surfaces do not closely fit that exact
  pattern at the candidate sites. This is a useful template, not a general corner planner.
- A stronger edge cost for 1x4 wedges discourages a long run when its side does not attach.

## Remaining work and acceptance

The local repair pass improves measured joins, but close-up renders still show repeated
notches where a long wedge run meets a changing corner. The next change is a run-level
planner that lays out the corner profile and wedge rows before fitting individual parts.
It should choose the profile first, then place the compatible pyramid/inverse closeouts
as a unit; exact hand-built patterns will otherwise be rejected against a different
continuous shape. Regenerate Zumwalt and LPD-17 from saved design specs and compare the
same camera angles in game, alongside part counts, mismatched partial faces, sampled
shape error, and seal results. Preserve an explicit faceted edge choice for hull designs
where the stepped silhouette is intentional.
