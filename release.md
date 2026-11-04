Title: Stormworks MCP v0.3.0: build any vehicle, modular engines and an installer

---

> **Upgrading from a version before v0.3? Remove the old Stormworks MCP from your AI client first.**
> In Claude Desktop, ChatGPT / Codex or whichever client you use, delete the old Stormworks server
> entry (it may be called `stormworks-hulls` or `stormworks`) and any older `server.py`, extension or
> portable-EXE setup. Close the client, then add v0.3 with the installer's "Add to ..." option or the
> app's **MCP > Set up** menu. Two entries for the same server will fight over the connection.

## Highlights

- **Build any vehicle**, not just boats: land vehicles, aircraft, helicopters and single assemblies.
  Every installed part can be placed, and the old boat habits are now optional style checks instead
  of rules.
- **Modular engines of any size**: build, check and drop them into any vehicle (details below).
- **Windows installer**: install for just you (no admin) or for all users, Start menu shortcut,
  optional automatic Claude Desktop / ChatGPT / Codex setup, and in-place upgrades. The portable EXE
  is still available.
- **Update check**: the app tells you when a newer release is out.

## Modular engines

- New `place_modular_engine` tool builds a complete engine from the game's own modular parts:
  - 1x1, 3x3 or 5x5 parts, any number of cylinders.
  - In-line, boxer (opposed) or multi-bank layouts. A 1x1 engine with cylinders on all four
    sides packs into a compact ring only three blocks wide.
  - Manifolds that join the cylinder banks are routed automatically, using the shortest run of
    corner and straight manifolds.
  - Air, fuel, exhaust and coolant manifolds are placed on free cylinder holes, with their pipe
    ends left open and facing outward.
  - Drive belt with starters (sensible minimums per size) and alternators, an optional flywheel,
    and a clutch for the power output.
  - Optional temperature sensor and air rams for the most compact intake and exhaust.
  - It reports every connection point (air in, fuel in, exhaust out, coolant, power output,
    throttles, starters, clutch) ready to pipe and wire.
- Preflight checks modular engines the way the game connects them, through their couplings:
  - Every cylinder reaches air, fuel and exhaust; starters sit on the drive belt; a clutch is on
    the crankshaft.
  - Throttle, starter and clutch wiring; air intake, exhaust outlet, fuel tank and cooling loop.
- Layouts and rules come from real player-built engines, including diesel-electric set-ups (engine
  to generator, battery, electric motors to propeller).
- Modular gearbox ratios are decoded (1:1, 6:5, 3:2, 9:5, 2:1, 5:2, 3:1 and reverse). A gearbox
  with no wires counts as a fixed ratio, for example to match a generator to its engine.
- Engines aren't wired yet; a custom ECU is coming in a later release.

## Building

- **Prefabs**: reuse any saved vehicle, or a box cut out of one, inside another vehicle. Wires and
  microcontrollers come with it.
- **Block-built tanks** from any closed space or a new box, with fluid, fill and litres reported.
- **Multi-body vehicles**: every body is shown, coloured and editable.
- **Physics estimates** (read-only): mass, flotation and waterline, thrust and lift.

## Fixes

- Closing your AI client no longer leaves `stormworks-mcp.exe` running in the background, and
  connections now close cleanly when the server stops.
- Preflight now passes power through circuit breakers, relays and diodes, and fluid through
  impeller pumps and catalytic converters.
- Tanks without a saved fluid now count as diesel, matching the game.
- Decorative pipe ends are now notes instead of errors.
- Microcontrollers keep their position when a vehicle is imported.
- The server is now named `stormworks` (it was `stormworks-hulls`); see the note at the top.

## Downloads

- `stormworks-mcp-0.3.0-windows-x64-setup.exe`: the installer (recommended).
- `stormworks-mcp-0.3.0-windows-x64.exe`: portable, no install.
- `SHA256SUMS.txt`, `build-info.json` and `provenance.sigstore.json` let you verify that a
  download was built from this repository.
