# Engine telemetry captures

These CSVs are copies of the local logger output from the project's generated engine test boats.
The full throttle sweeps were run on 2026-10-24; the two single-step boats were run on
2026-10-30. The logger writes a game-time second (`s`) and tank-content reading once a second.
`wall` is the local capture timestamp. The engine test boats use different hulls.

The table records SHA-256 of the corresponding XML files found in the player's Stormworks
vehicle folder on 2026-10-30. It identifies the files present after the runs; the game did not
record an XML hash at spawn time. Generated vehicle XML and game assets are not included here.

| CSV | Vehicle XML | SHA-256 |
| --- | --- | --- |
| [small.csv](small.csv) | `engine test small.xml` | `A71E159095555DB795B039CC406F9748B41BD81D0E440D2ADA05F0D28E85CB43` |
| [medium.csv](medium.csv) | `engine test medium.xml` | `C077F47BE791E183CB5D20A40D5EC078DF83D4DE6FB8196591BBD709FDB63CE4` |
| [large.csv](large.csv) | `engine test large.xml` | `6408E911D51BCD7EF46B59FF222B157777D0C840A5D5DD05929C2583C41DB69E` |
| [medium_s8.csv](medium_s8.csv) | `engine test medium_s8.xml` | `507F81AA390002378D0E9961C0C677992F7E3D4C083018631940859AED7BD69C` |
| [large_s5.csv](large_s5.csv) | `engine test large_s5.xml` | `A2EC3833DD498D3C0A415E946220008244A29106043929FE2E8DA0BD6A5D6EB5` |

See [in-game testing](../../in-game-testing.md#engine-telemetry) for the method, summaries and
remaining validation limits.
