# Hull smoothing V2 research and measured results

Date: 2026-10-02. These are geometric measurements and rendered checks, not in-game
validation or an estimate of the AI's overall correctness.

## Evidence and findings

The research combined the installed-piece geometry tests, the existing fitter and its
regressions, first-hand Stormworks construction examples, naval-architecture definitions,
the official Benchy geometry descriptions, and read-only inspection of local saves.
Sources and practical block-selection rules are in [the focused guide](hull-smoothing.md).

Saved files were ranked by byte size to find substantial references, then their actual
structural parts and body boundaries were examined. Byte size is a discovery aid, not a
quality measure: controllers and equipment can dominate a file. Older non-v3 saves were
skipped rather than interpreted using an incompatible format.

The player nominated `data/backups/vehicles/autosave9.xml` as the reference ship. Its main
structural body is `403`, with 26,629 catalogue structural parts, including 23,203 blocks,
668 Wedge 1x4, 623 Wedge 1x2 and 1,379 Wedge 1x1. Corner families include 118 Pyramid 4x4
and 124 Inverse Pyramid 4x4, 122 Pyramid 1x4 and 120 Inverse Pyramid 1x4. The near-balanced
counts support the construction examples' alternating corner-piece pattern, but do not
prove that every pair forms a correct exterior joint. Counts include floors and superstructure.
Other bodies were kept separate; their local positions are not hull coordinates.

Benchy's existing specification has a 4.5 m walking floor above the keel. Its rim heights
are 5.9 / 5.5 / 7.8 m at stern / midship / bow, producing drops of 1.4 / 1.0 / 3.3 m.
The original baseline had 3,776 interior plate cells and none were replaced by slopes.
Thus a missing floor or smoothing undercut was not established as Benchy's immediate cause.
Protecting all interior plates still fixes an otherwise unguarded case, now covered by tests.

The player clarified that there are lines through the walking area. The generated preview
showed transverse hull-coloured strips above the level walking plate. The hull skin uses
26-neighbour exposure, so it can be two layers thick at a deck-height step. The old open-deck
removal removed only the topmost cells, leaving both lower strips and vertical step faces.
The updated removal clears these while retaining side rims and transom/stem boundaries.

Opening those strips also exposed accidental structural dependencies: some fixture/cabin
bases rested on disconnected raised plates. Open hulls with specified walking floors now
retain the bases and add short vertical supports at their outboard edges, confined to the
existing hull volume and avoiding room air, reserved access and carvings. These choices are
reported. Benchy V2 adds 42 support blocks across its cabin, arch posts, bollard and rear-door
base. Its final footprint attachment report has no loose-part warnings. Functional in-game
attachment still requires review.

## Controlled fitter comparisons

Both modes below use the same continuous target, colours, plate protection, open-deck fix
and fixture supports. The benchmark measures the final skin after seal backing.

| Hull | Original partial-face mismatches | Guarded V2 mismatches | Sampled partial-cell shape error, original → V2 | Selected result |
| --- | ---: | ---: | --- | --- |
| Rowboat | 50 | 49 | 11.742% → 11.496% | Original plus corner closeouts |
| Runabout | 65 | 53 | 15.824% → 15.920% | Refined plus corner closeouts |
| Fishing trawler | 341 | 334 | 20.159% → 20.016% | Original plus corner closeouts |
| Player's Benchy specification | 799 | 612 | 19.383% → 19.190% | Refined plus corner closeouts |

After the screenshot-driven corner update, Benchy has approximately **23.4% fewer
mismatched partial-face joints** and Runabout has approximately **18.5% fewer**.
These are not percentages of visual improvement. The continuous-plane guard retains
the original fit on Rowboat and Fishing trawler, then applies accepted corner closeouts.

Volume error counts wrong inside/outside samples only in partial target cells, including
border slivers. It is not an error fraction of the whole ship, where most full cells would
hide surface defects, and does not describe the intentionally hollow interior. Joint counts
include deliberate edges. These metrics should be read alongside the images and sections.

Unrestricted continuous-normal refinement initially reduced some seams while increasing
shape error. This result was rejected. V2 now refines confident, uncreased cells; scores
continuous plane position as well as angle; weights volume more strongly; and compares both
completed skins. It accepts a refined skin only when a metric improves, seam count does not
rise, and partial-cell sampled shape error increases by at most 0.5 percentage points.

V2 has additional build cost: it measures boundary crossings and builds/evaluates both
candidates. Local uncached Benchy trials were roughly 14 seconds for the guarded build versus
roughly 4 seconds for the original. Timings vary with cache, hardware and target geometry;
the benchmark JSON identifies cache hits. The additional corner pass brought the latest
uncached Benchy run to roughly 24 seconds. The full 110 m Zumwalt build took roughly 134 seconds.

## Screenshot-driven corner follow-up

The player supplied an in-game image of the large sloped deckhouse in
`Zumwalt L110 - Exterior.xml`, confirming wedge-end notches and occasional protruding
cubes. They identified matching-size pyramids as the intended corner pieces. Its design
already selected V2; this was not an old-mode selection issue. The Benchy screenshot
also confirmed the raised deck strips described above.

The deckhouse combines 4 m taper over 10 m height with additional 1 m fore / 0.5 m aft
rake. Two wedge runs meet at its corners; that intersection is different from a single
diagonal plane. A smaller reproduction retaining those exact ratios exposed why whole-fit
fallback alone could retain bad corners. The original reproduction had 112 mismatched
joints; local closeouts reduced that to 88 while reducing sampled shape error.

V2 now evaluates corner replacements after selecting the main fit. It checks measured
creases and adjacent partial cells, tries complete catalogue footprints and compares both
adjoining faces, including wedge ends facing empty air. Each change must reduce unexpected
exposed-face bits without increasing total or partial-cell volume error or occupied seam
count. Necessary interior backing participates in the same comparison. The final result is
checked again after all replacements; paint, floor protection and openings are respected.

In the final integrated full-size Zumwalt build, **99 local replacements** reduced the
selected fit's mismatched joints from **4,683 to 4,650** and wrong partial-cell samples from
**361,975 to 360,939** on 3,947,584 tested samples. The older fitter had 4,763 mismatched joints.
The final Benchy build accepted 155 local replacements and reached the table's 612 joints.
These full-ship counts include unrelated hull transitions; they do not measure only the
visible corner. Corrected pyramids close some notches, while discretization steps and some
unresolved transitions remain. An in-game review is still required.

## Validation and remaining work

- Regression coverage checks off-grid continuous plane angles and positions in multiple axes,
  sharp corners, slope families, floor protection, no spike tips, partial-face skin backing,
  stepped open-cockpit walking paths and fixture attachment.
- The numerical analysis checks exact material heights inside long wedges, rotations, mirrored
  2x4 pieces, top-of-floor gaps, floor-to-rim drops and body-local reference coordinates.
- MCP checks cover worker dispatch, saved and backup sources, read-only reference behavior,
  focused guidance and invalid source/name combinations.
- Calibration roofs at 1:1, 1:2 and 1:4, multiple presets, the nominated reference and Benchy
  before/after previews were rendered and visually inspected. Local exported XML was checked
  for exact read-back and duplicate reserved cells.

The Benchy test copy retains the player's dimensions and floor height. It fixes the strips
and changes the smoothing; it does not guess a new depth from an ambiguous screenshot.
Its existing `bench:"M"` setting fails this project's fit report; the geometry requires at
least XL by that report. Do not shrink it silently: confirm the actual modded workbench or
choose a fitting bench/scale in the next building session.

The next in-game review should compare the same Zumwalt corner in the new test copy,
Benchy's walking-area lines, cabin/base attachment, bow and bottom seams, and remaining
floor-to-rim depth. Existing saved originals must be regenerated to show these changes.
Actual flotation, trim and fluid seals remain
unverified. The finite block catalogue cannot reproduce every smooth curve exactly.

Private saves, generated test vehicles, benchmark JSON and preview images stay in ignored
local output. No saved original was modified and no game geometry files were committed.
