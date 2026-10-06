"""Stormworks hull designer: MCP server for Claude Desktop.

Generates boat hulls from a parametric spec, renders previews for the model to review,
and writes vehicle XML straight into the Stormworks vehicles folder.
"""
import functools
import inspect
import json
import logging
import os
import re
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from swhull.benches import describe as describe_benches
from swhull._version import __version__
from swhull.build import deck_profile as _deck_profile, resolve_spec
from swhull.hull import merge
from swhull.editing import revision as _revision
from swhull import definitions
from swhull.jobs import run_job
from swhull.presets import PRESETS
from swhull.vehicle import vehicles_dir
from swhull.tool_schemas import (AssemblyBindings, AssemblyOptions, AssemblyReport, ChangeReport,
                                 ConnectionBatch, DiagnosticReport, EditBatch, PreflightReport,
                                 RepairPlan, RouteBatch, Selection, plain)
from swhull.validation import Observation, ValidationRun

HERE = Path(__file__).resolve().parent
GUIDE = (HERE / "swhull" / "guide.md").read_text(encoding="utf-8")
NAME_RE = re.compile(r"^[A-Za-z0-9 _\-()]{1,64}$")
DESIGN_LOCK = threading.RLock()
LOG = logging.getLogger("stormworks.tools")


def designs_dir():
    """Where saved design specs live (outside the repo, per user). SW_DESIGNS_DIR overrides."""
    if os.environ.get("SW_DESIGNS_DIR"):
        return Path(os.environ["SW_DESIGNS_DIR"])
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "stormworks-hull-mcp" / "designs"


INSTRUCTIONS = """\
Design Stormworks vehicles. Read hull_design_guide(topic="workflow") first. Ask for the bench;
preview and inspect before saving. Hull dimensions use metres; exact edits use integer blocks
(0.25 m each). Components stay game-sized when scaling. Query revisions before committing edits.
Import into a draft and save a separate copy. Report skipped placements and uncertain seals;
use connection tools to complete wiring/plumbing; operation is verified in game.
For road/land vehicles, read land_vehicle_guide first. Use find_land_vehicles to locate wheel or
track references, search_land_parts for chassis/control/lighting/powertrain families, and
analyze_land_vehicle for body-local axle layouts, mounting, lights and saved settings.
create_land_vehicle defaults to a utility buggy with bodywork, real suspension wheels, saddle,
spotlights, premade tanks, engine, battery and radiator. preset=chassis selects a bare chassis.
Choose preset=humvee_4x4 for a four-seat Humvee-shaped example with open custom-door bays,
compact windows, a sloped hood, prebuilt diesel and enclosed chassis pipework. Fit the body
proportions first; do not enlarge the cabin merely to fit a stock door/window. utility_4x4
retains the older layout with large sliding doors. Connected examples include prebuilt diesel,
premade fuel tank, radiator and drivetrain. Only prebuilt diesel engines and radiator cooling
are offered for new placement. Modular engines and heat exchangers are disabled.
Use modular_engine_gearbox_1x1 (the standalone Gearbox 1x1); its name does not make
it a modular engine. Deprecated torque_gearbox/torque_gearbox_2 are excluded from new
placement. Gear Switch off uses gear_ratio_1=1 (1:1 forward); on uses gear_ratio_2=0
(1:-1 reverse). New gearboxes explicitly use these defaults. Inspect
preflight gearbox_configuration_checks rather than assuming ratio index 0 is forward.
New prebuilt engines explicitly use max_force_scale=1 (100% power); if an engine only
cranks, inspect its configuration as well as external connections. Seat Axis 1 is A=-1,
D=+1 and Axis 2 is W=+1, S=-1. Wheel mount/axle direction alone does not determine drive
direction: constrain wheel_forward and wheel_reference_up too. Mirrored right road wheels
keep drive arrows forward; this reference pairing inverts left steering and uses direct
right steering. Inspect preflight wheel_direction_checks after rotation/wiring changes.
Read workshop references with source=workshop and a numeric item ID. Previews use installed
component meshes; layer=components exposes equipment inside the body. Extend with
query_parts/edit_parts, preview_vehicle and save_vehicle. Land specs use actual metres.
Use query_connections for wire nodes and physical transmission faces. edit_connections adds
or removes typed control/electric links; route_connections adds physical pipes while preserving
structure/access. Both support preview, revision checks, commit and undo. Run preflight_vehicle
to check required subsystem paths, engine power, gearbox states and supported wheel/control directions.
Use plan_vehicle_repairs to get tested suggestions, then repair_vehicle with revision, plan_id
and selected available finding IDs: preview first, then commit and rerun preflight. Manual
findings need a design choice; never remove blocked structure automatically. Use
list_vehicle_assemblies/apply_vehicle_assembly for reusable starter/idle, clutch, brake/reverse
and lamp controls. Bind current queried IDs; idle throttle and clutch require separate gates.
preview_vehicle_diagnostics and open_in_viewer(design=...,diagnostics=true) show faults and
steering arrows; repair previews show proposed wires/routes in green. prepare_vehicle_validation
exports a test copy with an exact XML hash and seven pending game checks. Record actual human
observations using record_vehicle_validation; a connected preflight is never game-test evidence.
Wheel roles road/spare/excluded keep spares out of axle
measurements. Manual-door previews include the leaf, with door_state=closed/open.
For realistic hulls read hull_design_guide(topic="smoothing"). Use analyze_hull to measure
keel, walking floor and rim separately; a part's footprint is not its solid material.
Use suggest_hull_blocks for slope families, then check position, orientation and neighboring
faces. Try smoothing="wedges_v2" for guarded continuous-surface fitting; compare the previews.
For superstructure corners, choose corner_chamfer for a deliberate facet or corner_radius for
a round footprint; roof_radius rounds the roof edge. Preview compound curves close up. Prefer
block-friendly slope ratios (1:1, 1:2, 1:4) when dimensions allow, then inspect their joins.
For a deliberate inward-and-outward wall indentation, use a waist with from/peak/to/inset;
0.25 m inset over each 0.5 m rise gives 1x2 wedge and inverse-pyramid opportunities.
Loop: pick a preset or write a
spec -> `preview_hull` (and `preview_interior` for rooms) -> look at the image and critique it
against the player's brief -> adjust -> `save_hull`. For big designs, keep the spec on the
server with `store_design` and send only changes: every tool takes `design` (a stored name)
plus `patch` (JSON-Patch ops). The player loads the saved vehicle from a workbench's Load menu.
Before designing, ask the player which bench size they will build at (S, M, L, XL, XXL or MAX;
`list_workbenches` gives sizes) and set `bench` in the spec; the summary checks the fit.
Build in stages and stop/save wherever the player prefers: hull -> structure -> core ->
access -> propulsion parts -> custom tanks. Geometry is plain blocks unless wedges are requested.
Optional fitout.stage places real game-sized batteries and a helm/seat; access adds complete
manual doors and requested hatch/ladder assemblies; propulsion adds propellers/rudders.
Named components/tanks remain in game metres when the hull is scaled. Report every automatic
choice and skipped placement. Never carve a hatch without its complete fitted assembly.
For exact edits use query_parts -> edit_parts preview -> edit_parts commit with the same revision;
these tools use integer blocks in the fixed build frame, not centred export coordinates.
Import single-body v3 vehicles into a draft and save a separate copy; configured originals
remain in place. Use check_seal after edits, including explicit seed points for imports.
Unknown sealing geometry is indeterminate. Invalid custom tanks cannot be exported.
Use search_parts/get_part_definition for installed footprints/surfaces and seal coverage.
Heavy tools use cancellable workers and a
shared geometry cache. Read docs/staged-builder.md through the design guide for examples.
Use complaint to record encountered bugs, confusing behavior or missing capabilities with
expected/actual behavior, reproduction steps and relevant tool arguments/errors. The report is
saved locally for review; reporting an issue does not fix it. Continue useful work where possible."""

mcp = MCPServer("stormworks-hulls", instructions=INSTRUCTIONS, version=__version__)


def _user_errors(fn):
    """Surface expected failures (bad spec, name clash, missing file) to the model verbatim."""
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def awrapper(*args, **kwargs):
            started = time.monotonic()
            LOG.info("Tool %s started", fn.__name__)
            try:
                result = await fn(*args, **kwargs)
            except (ValueError, OSError) as exc:
                LOG.warning("Tool %s failed after %.2fs: %s", fn.__name__, time.monotonic() - started, exc)
                raise ToolError(str(exc)) from exc
            except BaseException:
                LOG.warning("Tool %s interrupted after %.2fs", fn.__name__, time.monotonic() - started)
                raise
            LOG.info("Tool %s completed in %.2fs", fn.__name__, time.monotonic() - started)
            return result
        return awrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        started = time.monotonic()
        LOG.info("Tool %s started", fn.__name__)
        try:
            result = fn(*args, **kwargs)
        except (ValueError, OSError) as exc:
            LOG.warning("Tool %s failed after %.2fs: %s", fn.__name__, time.monotonic() - started, exc)
            raise ToolError(str(exc)) from exc
        LOG.info("Tool %s completed in %.2fs", fn.__name__, time.monotonic() - started)
        return result
    return wrapper


def _check_name(name):
    if not NAME_RE.match(name or "") or name.strip() != name:
        raise ValueError("name may use letters, digits, spaces, _ - ( ) and be at most 64 characters")


def _design_path(name):
    _check_name(name)
    return designs_dir() / f"{name}.json"


def _read_design(name):
    path = _design_path(name)
    if not path.is_file():
        raise ValueError(f"no stored design named '{name}' (see list_designs)")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_spec_file(path):
    """A spec from a JSON file: a bare spec, or a stored design ({"spec": ...})."""
    p = Path(path).expanduser()
    if p.suffix.lower() != ".json":
        raise ValueError("spec_path must be a .json file")
    if not p.is_file():
        raise ValueError(f"spec_path not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("spec"), dict):
        data = data["spec"]
    if not isinstance(data, dict):
        raise ValueError("spec_path must hold a JSON object (a spec)")
    return data


def _spec(spec=None, preset=None, design=None, patch=None, spec_path=None):
    """Resolve the spec a tool works on: preset or stored design, then spec_path, then spec,
    then patch."""
    record = _read_design(design) if design else None
    if record and record.get("kind") in ("imported", "land"):
        label = "an imported" if record["kind"] == "imported" else "a land"
        raise ValueError(f"this is {label} draft; use preview_vehicle, query_parts, edit_parts and save_vehicle")
    base = record["spec"] if record else None
    if spec_path:
        base = merge(base or {}, _read_spec_file(spec_path))
    return resolve_spec(spec, preset, base=base, patch=patch)


def _atomic_design(name, record):
    path = _design_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as f:
            temporary = Path(f.name)
            json.dump(record, f, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _commit_record(name, proposed, expected):
    with DESIGN_LOCK:
        current = _read_design(name)
        if _revision(current) != expected:
            raise ValueError("stale revision; query_parts again before editing")
        # Imported source bytes are immutable and can be megabytes; store them once.
        history = current.get("history", [])[-9:] + [
            {k: v for k, v in current.items() if k not in ("history", "source_xml")}]
        proposed = {**proposed, "history": history, "generation": current.get("generation", 0) + 1,
                    "vehicle": current.get("vehicle", False)}
        _atomic_design(name, proposed)
        return proposed


def _save_target(name, record, overwrite):
    _check_name(name)
    if record.get("kind") == "imported" and name.casefold() == record["source"].casefold():
        raise ValueError("cannot overwrite the imported original; choose a different vehicle name")
    target = Path(vehicles_dir()) / f"{name}.xml"
    if target.exists():
        owned = _design_path(name).exists() and _read_design(name).get("vehicle", False)
        if not owned:
            raise ValueError("target was not made by this tool; choose another name")
        if not overwrite:
            raise ValueError("target exists; pass overwrite=true")
        stat = target.stat()
        return target, (stat.st_mtime_ns, stat.st_size)
    return target, None


def _write_vehicle(target, xml, previous):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, suffix=".tmp", delete=False) as f:
            temporary = Path(f.name)
            f.write(xml.encode("utf-8"))  # Preserve imported newlines and UTF-8 bytes.
        now = target.stat() if target.exists() else None
        stamp = (now.st_mtime_ns, now.st_size) if now else None
        if stamp != previous:
            raise ValueError("target changed while building; choose another name")
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _title(preset, design):
    return design or preset or "design"


def _vehicle_path(name):
    """Path of a vehicle in the game's vehicles folder; refuses anything outside it."""
    base = Path(vehicles_dir()).resolve()
    path = (base / f"{name}.xml").resolve()
    if path.parent != base:
        raise ValueError("invalid vehicle name")
    if not path.is_file():
        raise ValueError(f"no vehicle named '{name}' (see list_game_vehicles)")
    return path


def _reference_path(name, source="vehicles"):
    if source == "vehicles":
        return _vehicle_path(name)
    if source != "workshop":
        raise ValueError("source must be vehicles or workshop")
    if not isinstance(name, str) or not re.fullmatch(r"[0-9]{1,20}", name):
        raise ValueError("workshop name must be its numeric item ID")
    for directory in definitions.workshop_dirs():
        root = Path(directory).resolve()
        path = (root / name / "vehicle.xml").resolve()
        if path.is_relative_to(root) and path.is_file():
            return path
    raise ValueError(f"workshop vehicle {name} not installed (set SW_WORKSHOP_DIR if needed)")


@mcp.tool()
@_user_errors
def hull_design_guide(topic: Literal["full", "workflow", "units", "spec", "interior", "archetypes", "style",
                                    "limits", "staged", "building", "testing", "smoothing", "edits", "topics"] = "full") -> str:
    """Read first. Topics: full, workflow, units, spec, interior, archetypes, style, limits,
    staged, building, testing, smoothing. Focused topics avoid resending the entire spec reference."""
    if topic == "full":
        return GUIDE
    if topic == "topics":
        return "Topics: full, workflow, units, spec, interior, archetypes, style, limits, staged, building, testing, smoothing, edits. Land vehicles: land_vehicle_guide."
    files = {"staged": "staged-builder.md", "building": "building.md", "testing": "in-game-testing.md",
             "smoothing": "hull-smoothing.md", "edits": "building.md"}
    if topic in files:
        return (HERE / "docs" / files[topic]).read_text(encoding="utf-8")
    headings = {"workflow": "Workflow", "units": "Units and axes", "spec": "Spec reference",
                "interior": "Interior design", "archetypes": "Archetype proportions (starting points)",
                "style": "Making it look good", "limits": "Limits"}
    if topic not in headings:
        raise ValueError("unknown guide topic; choose full, workflow, units, spec, interior, "
                         "archetypes, style, limits, staged, building, testing, smoothing, edits or topics")
    section = GUIDE.split(f"\n## {headings[topic]}\n", 1)[1].split("\n## ", 1)[0]
    return f"## {headings[topic]}\n{section}"


@mcp.tool()
@_user_errors
def get_runtime_status() -> dict[str, Any]:
    """Diagnose version, runtime paths, game definitions and timeout without writing files."""
    from swhull.diagnostics import runtime_status  # noqa: PLC0415
    return runtime_status()


@mcp.tool()
@_user_errors
def list_hull_presets() -> str:
    """List built-in hull archetypes with a one-line description and main dimensions."""
    lines = []
    for name, p in PRESETS.items():
        s = p["spec"]
        lines.append(f"- {name}: {p['about']} ({s.get('length')} m x {s.get('beam')} m, "
                     f"depth {s.get('depth')} m{', with interior' if s.get('interior') else ''})")
    return "\n".join(lines)


@mcp.tool()
@_user_errors
def list_workbenches() -> str:
    """Bench size keywords (S, M, L, XL, XXL, MAX) with their size in metres and the edit areas
    in the player's game (including workbench mods) that are at least that big. Set one as
    `bench` in a spec; preview summaries then say whether the design fits and by how much not."""
    return describe_benches()


@mcp.tool()
@_user_errors
def get_hull_spec(preset: str | None = None) -> dict[str, Any]:
    """Full resolved spec (every parameter) for a preset, or the defaults. Use as a starting point."""
    return resolve_spec(preset=preset)


@mcp.tool()
@_user_errors
async def preview_hull(spec: dict[str, Any] | None = None, preset: str | None = None,
                       design: str | None = None, patch: list[dict[str, Any]] | None = None,
                       spec_path: str | None = None) -> list:
    """Build a hull and return a preview image (3/4 above and below, front, side, top) plus stats.

    spec: partial or full hull spec (see hull_design_guide); merged over the preset if given.
    preset: optional preset name to start from.
    design: a stored design (store_design / save_hull) to start from instead of a preset.
    patch: JSON-Patch ops applied last, e.g. [{"op": "replace", "path":
        "/superstructure/bridge/height", "value": 2.5}]. List items can be named instead of indexed.
    spec_path: a .json file holding a spec (or a stored design), read before `spec` and `patch`.
    """
    full = _spec(spec, preset, design, patch, spec_path)
    png, text = await run_job("preview", full, _title(preset, design))
    return [Image(data=png, format="png"), text]


@mcp.tool()
@_user_errors
async def preview_interior(spec: dict[str, Any] | None = None, preset: str | None = None,
                           design: str | None = None, patch: list[dict[str, Any]] | None = None,
                           spec_path: str | None = None) -> list:
    """Cutaway of the interior: a section on the centreline plus a labelled deck plan for
    every room level, and a per-room report (clear size, floor width, doors with sill heights
    and floor steps, engines, warnings). Use after adding `interior` to a spec (see
    hull_design_guide, "Interior design"). Floors above the main deck are drawn cropped to
    their rooms. design/patch/spec_path: as in preview_hull."""
    full = _spec(spec, preset, design, patch, spec_path)
    png, text = await run_job("interior", full, _title(preset, design))
    return [Image(data=png, format="png"), text]


@mcp.tool()
@_user_errors
def deck_profile(spec: dict[str, Any] | None = None, preset: str | None = None,
                 design: str | None = None, patch: list[dict[str, Any]] | None = None,
                 step: float = 1.0, spec_path: str | None = None) -> str:
    """Deck height above the keel, the `y` a box gets when left out, and the deck half-beam,
    every `step` metres from the transom. Use it to place turrets and deckhouses on a sheered
    deck. Lengths are in spec units (real-world metres when the spec has a `scale`)."""
    return _deck_profile(_spec(spec, preset, design, patch, spec_path), step)


@mcp.tool()
@_user_errors
async def save_hull(name: str, spec: dict[str, Any] | None = None, preset: str | None = None,
                    overwrite: bool = False, design: str | None = None,
                    patch: list[dict[str, Any]] | None = None, spec_path: str | None = None) -> str:
    """Save a hull into the Stormworks vehicles folder so it can be loaded at a workbench.

    name: vehicle name shown in the game's Load menu. The spec is also stored as a design of
    the same name.
    overwrite: replace an earlier design saved by this tool under the same name. Vehicles
    not made by this tool are never overwritten.
    design/patch: as in preview_hull, e.g. save_hull(name="Iowa", design="Iowa").
    """
    full = _spec(spec, preset, design, patch, spec_path)
    record = {"preset": preset, "vehicle": True, "spec": full}
    target, stamp = _save_target(name, record, overwrite)
    xml, parts, text = await run_job("vehicle_xml", full)
    with DESIGN_LOCK:
        _write_vehicle(target, xml, stamp)
        previous = _read_design(name) if _design_path(name).exists() else {}
        _atomic_design(name, {**record, "generation": previous.get("generation", 0) + 1})
    return (f"Saved {parts} parts to {target}\n{text}\n"
            f"In game: open a workbench, press Load, choose '{name}'.")


@mcp.tool()
@_user_errors
def store_design(name: str, spec: dict[str, Any] | None = None, preset: str | None = None,
                 design: str | None = None, patch: list[dict[str, Any]] | None = None,
                 spec_path: str | None = None) -> str:
    """Keep a design spec on the server without writing a vehicle, so later calls can send
    only changes. Typical loop: store_design("Iowa", spec=...) once, then
    preview_hull(design="Iowa", patch=[...]) to try a change and
    store_design("Iowa", design="Iowa", patch=[...]) to keep it. Replaces any stored design
    of that name; save_hull(name, design=name) writes the vehicle when ready.
    spec_path: read the spec from a .json file instead of sending it. Stored designs are
    plain JSON files that every call re-reads, so editing one on disk takes effect at once.
    """
    full = _spec(spec, preset, design, patch, spec_path)
    path = _design_path(name)
    with DESIGN_LOCK:
        previous = _read_design(name) if path.is_file() else {}
        _atomic_design(name, {"preset": preset, "vehicle": previous.get("vehicle", False),
                              "spec": full, "generation": previous.get("generation", 0) + 1})
    boxes = len(full.get("superstructure") or [])
    return (f"Stored design '{name}' ({full['length']} m, {boxes} superstructure entries) at "
            f"{path}. Use design=\"{name}\" with patch=[...] in any tool; edits to that file "
            "on disk apply to the next call.")


@mcp.tool()
@_user_errors
def list_designs() -> list[str]:
    """Names of stored hull, land and imported drafts."""
    d = designs_dir()
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


@mcp.tool()
@_user_errors
def load_design(name: str) -> dict[str, Any]:
    """Hull spec, or land/import draft metadata and revision. Use part tools to edit land/imports."""
    record = _read_design(name)
    if record.get("kind") == "land":
        return {"kind": "land", "spec": record["spec"], "revision": _revision(record),
                "coordinates": "build-frame integer blocks; +y up, +z forward, chassis top y=0"}
    if record.get("kind") == "imported":
        return {"kind": "imported", "source": record["source"], "revision": _revision(record),
                "edits": record.get("edits", []), "coordinates": "original body-local integer blocks"}
    return record["spec"]


@mcp.tool()
@_user_errors
def search_parts(search: str = "", offset: int = 0, limit: int = 50) -> dict[str, Any]:
    """Search installed part definitions by name/id; returns actual sizes, mass and pagination."""
    return definitions.catalogue(search, offset, limit)


@mcp.tool()
@_user_errors
def get_part_definition(definition: str) -> dict[str, Any]:
    """Installed footprint, attachment/sealing surfaces and relevant part settings."""
    result = definitions.metadata(definition)
    if result is None:
        raise ValueError(definitions.unavailable(definition))
    from swhull.seal import coverage  # noqa: PLC0415
    from swhull.part_policy import allowed, restriction  # noqa: PLC0415
    return {**result, "seal_coverage": coverage(definition), "placement_allowed": allowed(definition),
            "placement_restriction": restriction(definition)}


@mcp.tool()
@_user_errors
def get_part_orientation(definition: str, targets: dict[str, list[int]] | None = None) -> dict[str, Any]:
    """Explain local mounting/motion/function axes and solve their requested world directions.
    Example Fin Rudder targets: mount_normal=[0,0,1], span_axis=[0,1,0]. Road wheel targets should
    include axle_axis, wheel_reference_up and wheel_forward; right placements can require mirror.
    Returns effective rotation plus proper r/mirror for XML. Arrow signs still need game checks."""
    from swhull.orientation import describe  # noqa: PLC0415
    return describe(definition, targets)


@mcp.tool()
@_user_errors
def get_calibration_observations(definition: str) -> dict[str, Any]:
    """Read recorded in-game checks for a part; expose stale evidence and contradictory reports."""
    from swhull.calibration import observations  # noqa: PLC0415
    directory = os.environ.get("SW_CALIBRATION_DIR", str(Path(__file__).parent / "out/advanced-suite/calibration"))
    return observations(definition, directory)


@mcp.tool()
@_user_errors
def complaint(title: str, description: str,
              category: Literal["placement", "rotation", "smoothing", "connections", "definitions", "performance",
                                "tool_error", "usability", "missing_feature", "analysis", "other"] = "other",
              severity: Literal["low", "medium", "high", "blocker"] = "medium",
              tool: str = "", expected: str = "", actual: str = "", steps: list[str] | None = None,
              context: dict[str, Any] | None = None, design: str = "", vehicle: str = "",
              definition: str = "", suggestion: str = "") -> dict[str, Any]:
    """Report an encountered problem or improvement request; save local JSON and Markdown reports.
    Required: title and description. Include failing tool/arguments, expected vs actual behavior,
    error messages, steps, affected design/vehicle/definition and a suggested improvement if known.
    Categories: placement, rotation, smoothing, connections, definitions, performance, tool_error,
    usability, missing_feature, other. Severity: low, medium, high, blocker.
    Returns a report id and file paths; no external issue is published."""
    from swhull.complaints import create  # noqa: PLC0415
    return create(title, description, category, severity, tool, expected, actual, steps, context,
                  design, vehicle, definition, suggestion)


@mcp.tool()
@_user_errors
def list_complaints(search: str = "", category: str = "", severity: str = "",
                    offset: int = 0, limit: int = 50) -> dict[str, Any]:
    """List locally recorded complaints newest first; filter by text, category or severity."""
    from swhull.complaints import catalogue  # noqa: PLC0415
    return catalogue(search, category, severity, offset, limit)


@mcp.tool()
@_user_errors
def get_complaint(complaint_id: str) -> dict[str, Any]:
    """Read a complaint's complete reproduction evidence and Markdown report by its id."""
    from swhull.complaints import read  # noqa: PLC0415
    return read(complaint_id)


@mcp.tool()
@_user_errors
def land_vehicle_guide() -> str:
    """Road vehicle workflow, installed parts, chassis spec, units, layout limits and game checks."""
    return (HERE / "docs" / "land-vehicles.md").read_text(encoding="utf-8")


@mcp.tool()
@_user_errors
async def search_land_parts(category: Literal["", "wheels", "tracks", "lights", "controls", "propulsion", "transmission",
                                            "power", "fuel", "cooling", "body", "logic", "utility"] = "",
                            search: str = "", offset: int = 0,
                            limit: int = 50) -> dict[str, Any]:
    """Installed components useful for land builds, with footprints and actual connection ports.
    Categories: wheels, tracks, lights, controls, propulsion, transmission, power, fuel,
    cooling, body, logic, utility. Use get_part_definition/get_part_orientation for details.
    Family filters are a convenience; search_parts exposes the full installed catalogue."""
    return await run_job("land_parts", category, search, offset, limit)


@mcp.tool()
@_user_errors
async def find_land_vehicles(search: str = "", kind: str = "wheeled", offset: int = 0,
                             limit: int = 50, source: str = "vehicles") -> dict[str, Any]:
    """Read the player's saves for wheel/track examples, including unnamed experiments.
    kind=wheeled/tracked/all. Counts only vehicle body components, not controller internals.
    Wheel-based boats/aircraft can match; this does not establish vehicle purpose or quality."""
    if source not in ("vehicles", "workshop"):
        raise ValueError("source must be vehicles or workshop")
    directories = definitions.workshop_dirs() if source == "workshop" else [vehicles_dir()]
    return await run_job("land_library", directories, search, kind, offset, limit, source)


@mcp.tool()
@_user_errors
async def analyze_land_vehicle(name: str | None = None, design: str | None = None,
                               body_id: str | None = None, forward: list[int] | None = None,
                               section: str = "wheels", offset: int = 0, limit: int = 50,
                               source: str = "vehicles", wheel_roles: dict[str, Literal["road", "spare", "excluded"]] | None = None,
                               exclude_wheel_ids: list[str] | None = None) -> dict[str, Any]:
    """Analyze a saved v3 vehicle or draft: body-local axles, wheelbase, mounts and light axes.
    Sections: wheels, lights, controls, equipment, issues. All component rows are paginated.
    forward is a horizontal unit vector; otherwise infer each body's driver-seat facing,
    falling back to +z explicitly. Axle span measures mounting origins, not tyre-centre track.
    Multi-body references stay separate. Suspension/steering sweep and mesh edits need game checks."""
    if (name is None) == (design is None):
        raise ValueError("choose exactly one saved vehicle name or draft design")
    if design is not None and source != "vehicles":
        raise ValueError("source applies only to a reference name")
    path = str(_reference_path(name, source)) if name is not None else None
    record = _read_design(design) if design is not None else None
    return await run_job("land_layout", path, record, body_id, forward, section, offset, limit, wheel_roles, exclude_wheel_ids)


@mcp.tool()
@_user_errors
async def create_land_vehicle(design: str, spec: dict[str, Any] | None = None) -> list:
    """Create a land draft: default utility_buggy, or preset=chassis for a custom bare layout.
    Read land_vehicle_guide for the spec. Dimensions/positions are game metres on the 0.25 m
    grid. Buggy includes bodywork, four suspension wheels, saddle, premade fuel tanks, engine,
    battery, radiator and actual lights. Parts must fit, mount and leave driver/service access.
    preset=humvee_4x4 has open custom-door bays, compact glass and enclosed chassis pipes.
    humvee_4x4 and utility_4x4 include radiator/fuel/air/exhaust/driveline pipes and typed links.
    Use query_connections/edit_connections/route_connections/preflight_vehicle to complete custom
    layouts. Extend through query_parts/edit_parts/preview_vehicle, then save_vehicle."""
    _check_name(design)
    if _design_path(design).exists():
        raise ValueError("draft already exists; choose a new design name")
    record, png, note = await run_job("land_draft", spec, design)
    with DESIGN_LOCK:
        if _design_path(design).exists():
            raise ValueError("draft already exists; choose a new design name")
        _atomic_design(design, record)
    return [Image(data=png, format="png"), note,
            {"design": design, "kind": "land", "revision": _revision(record)}]


@mcp.tool()
@_user_errors
async def analyze_vehicle(name: str, search: str = "", offset: int = 0, limit: int = 50,
                          section: str = "parts", source: str = "vehicles") -> dict[str, Any]:
    """Read saved-vehicle examples, body groups, link coverage and rudder mounting/motion issues.
    Supports multi-body references without editing them. Observations are not game verification.
    Search rudder/propeller/engine/trans to focus evidence. Sections: parts, links, controllers,
    bodies, placement_issues, connection_candidates, open_transmission_ports. All are paginated."""
    return await run_job("analyze_reference", str(_reference_path(name, source)), search, offset, limit, section)


@mcp.tool()
@_user_errors
def suggest_hull_blocks(normal: list[float], limit: int = 6) -> dict[str, Any]:
    """Rank real block slope families by an outward x/y/z normal. Read the selection rules:
    the angle alone cannot choose pyramid vs inverse, location, or a watertight joint."""
    from swhull.hull_analysis import block_choices  # noqa: PLC0415
    return block_choices(normal, limit)


@mcp.tool()
@_user_errors
async def analyze_hull(name: str | None = None, spec: dict[str, Any] | None = None,
                       preset: str | None = None, design: str | None = None,
                       patch: list[dict[str, Any]] | None = None,
                       body_id: str | None = None, stations: list[int] | None = None,
                       x: int = 0, source: str = "vehicles") -> dict[str, Any]:
    """Measure actual hull material, floor gaps, and partial-face seams at z stations.
    x/stations are integer BLOCK coordinates. name reads a saved v3 vehicle (one body at
    a time); otherwise build spec/preset/design in the fixed build frame. Procedural reports
    include floor height above keel and drop from rim, so verify depth before saving.
    Imported saved vehicles use their original body-local frame; choose body_id explicitly
    when the largest structural body isn't the hull. source="backups" reads data/backups/vehicles,
    e.g. name="autosave9". This is read-only geometry, not a seal test."""
    if source not in ("vehicles", "backups"):
        raise ValueError('source must be "vehicles" or "backups"')
    if name is not None:
        if any(v is not None for v in (spec, preset, design, patch)):
            raise ValueError("choose name or procedural spec/preset/design, not both")
        path = _vehicle_path(name) if source == "vehicles" else (
            Path(vehicles_dir()).parent / "backups" / "vehicles" / f"{name}.xml")
        _check_name(name)
        return await run_job("hull_analysis", None, str(path), body_id, stations, x)
    if source != "vehicles":
        raise ValueError("source applies only to a saved vehicle name")
    if body_id is not None:
        raise ValueError("body_id applies only to a saved vehicle name")
    return await run_job("hull_analysis", _spec(spec, preset, design, patch), None, None, stations, x)


@mcp.tool()
@_user_errors
async def import_vehicle(name: str, design: str, source: str = "vehicles") -> str:
    """Import an existing single-body version-3 vehicle into a new draft; never changes the source.
    Existing configured/wired parts are protected. Use query_parts/edit_parts and save_vehicle."""
    _check_name(design)
    if _design_path(design).exists():
        raise ValueError("draft already exists; choose a new design name")
    path = _reference_path(name, source)
    record, count = await run_job("import_draft", path.read_bytes().decode("utf-8"), name)
    with DESIGN_LOCK:
        if _design_path(design).exists():
            raise ValueError("draft already exists; choose a new design name")
        _atomic_design(design, record)
    return f"Imported {count} parts into '{design}'. Source '{name}' remains untouched."


@mcp.tool()
@_user_errors
async def query_parts(design: str, select: Selection | None = None,
                      offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """Parts and revision for precise editing. select: ids, name, definition or inclusive bounds
    [[min_x,min_y,min_z],[max_x,max_y,max_z]]. Coordinates are integer blocks (0.25 m), in the
    uncentred build frame for generated hulls/land drafts and original body-local frame for imports.
    Rows include scalar settings, proper rotation plus a local mirror bitmask, and the effective
    transform matrix. Partial multi-voxel selections are rejected; select an id to target the whole component."""
    return await run_job("query_draft", _read_design(design), plain(select, Selection) if select is not None else None, offset, limit)


@mcp.tool()
@_user_errors
async def edit_parts(design: str, operations: EditBatch, revision: str,
                     commit: bool = False) -> list:
    """Atomic part edits; defaults to preview only. Pass the revision from query_parts.
    Ops: add(part/parts), fill(bounds,color), remove/replace/move/rotate/paint/copy/mirror/repeat.
    Selection ops need select={ids/bounds/name/definition}. move/copy/repeat use delta in blocks;
    repeat count is additional copies; rotate uses a local-to-world matrix or r string and pivot;
    mirror uses axis and plane. replace needs part; paint needs color. Added parts use definition,
    position in blocks, rotation, optional mirror (1=x, 2=y, 4=z), color, name and scalar settings.
    Placement rotation accepts an effective mirrored matrix; use that or proper rotation plus
    mirror. Prebuilt engines default to max_force_scale=1 (100%). commit=true keeps one undo step."""
    record = _read_design(design)
    if _revision(record) != revision:
        raise ValueError("stale revision; query_parts again before editing")
    proposed, png, note = await run_job("edit_draft", record, plain(operations, EditBatch), design)
    if commit:
        proposed = _commit_record(design, proposed, revision)
    return [Image(data=png, format="png"), note,
            {"committed": commit, "revision": _revision(proposed),
             "base_revision": revision, "operations": len(operations)}]


@mcp.tool()
@_user_errors
def undo_edits(design: str, revision: str) -> dict[str, Any]:
    """Restore the previous committed edit batch. Keeps up to ten batches of undo history."""
    with DESIGN_LOCK:
        record = _read_design(design)
        if _revision(record) != revision:
            raise ValueError("stale revision; query_parts again")
        history = record.get("history", [])
        if not history:
            raise ValueError("no committed edits to undo")
        restored = {**{k: v for k, v in record.items() if k not in ("history", "edits", "connection_edits", "route_edits")},
                    **history[-1], "history": history[:-1],
                    "generation": record.get("generation", 0) + 1, "vehicle": record.get("vehicle", False)}
        _atomic_design(design, restored)
        return {"revision": _revision(restored), "remaining_undo": len(history) - 1}


@mcp.tool()
@_user_errors
async def query_connections(design: str, offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """Installed/configured node indices, transmission surface indices, wires and draft revision.
    Wire endpoints: {part_id,port}; pipe endpoints: {part_id,surface_index}. Coordinates are
    uncentred integer blocks. Paginate components; links retain stable IDs for disconnect."""
    return await run_job("query_connections", _read_design(design), offset, limit)


@mcp.tool()
@_user_errors
async def edit_connections(design: str, operations: ConnectionBatch, revision: str,
                           commit: bool = False) -> list:
    """Preview/commit typed control and electrical wires. Uses the query_connections revision.
    Ops: {op:'connect',from:{part_id,port},to:{part_id,port}} or {op:'disconnect',link_id}.
    Signal outputs connect to inputs; electricity is bidirectional. One driver per signal input.
    Power/fluid use route_connections. Original XML/settings remain lossless; commit has undo."""
    record = _read_design(design)
    if _revision(record) != revision:
        raise ValueError("stale revision; query_connections again")
    proposed, png, note = await run_job("edit_connections", record, plain(operations, ConnectionBatch), design)
    if commit:
        proposed = _commit_record(design, proposed, revision)
    return [Image(data=png, format="png"), note,
            {"committed": commit, "revision": _revision(proposed), "base_revision": revision}]


@mcp.tool()
@_user_errors
async def route_connections(design: str, routes: RouteBatch, revision: str,
                            commit: bool = False) -> list:
    """Preview/commit actual pipes between transmission faces, preserving access and structure.
    Each route: {from:{part_id,surface_index},to:{part_id,surface_index},bounds?:[[lo],[hi]],
    waypoints?:[[x,y,z],...],name?:str,pipe_style?:auto|exposed|enclosed,through_blocks?:[part_id,...]}.
    Bounds/waypoints use integer blocks. Routes minimize length, then bends. Default auto uses
    enclosed pipes for explicitly selected through_blocks; other cells use exposed pipes.
    through_blocks replaces only selected unconfigured/unlinked 01_block parts, retaining paint.
    All selected blocks must lie on the route (use waypoints if needed); removal restores them.
    Other structure and access are preserved; routes never join unrelated pipe networks.
    Clutch/gearbox ports may use several routes; create an explicit T-piece for a branch.
    Remove an added route with {op:'remove',route_id} from query_connections, then reroute."""
    record = _read_design(design)
    if _revision(record) != revision:
        raise ValueError("stale revision; query_connections again")
    proposed, png, note = await run_job("route_connections", record, plain(routes, RouteBatch), design)
    if commit:
        proposed = _commit_record(design, proposed, revision)
    return [Image(data=png, format="png"), note,
            {"committed": commit, "revision": _revision(proposed), "base_revision": revision}]


@mcp.tool()
@_user_errors
async def preflight_vehicle(design: str) -> PreflightReport:
    """Check engine fuel/air/exhaust/radiator paths, driveline, electrical power and controls.
    Reports configuration_checks (explicit engine power), gearbox_configuration_checks (saved
    off/on ratio indices, including reverse-off warnings) and wheel_direction_checks (drive
    arrows and steering signs for supported direct/inverting paths). Unknown logic stays unknown.
    Includes blocked transmission exits. Separates physical pipes from typed wires and keeps
    functional component circuits distinct. Connected geometry still needs in-game testing."""
    return await run_job("preflight_vehicle", _read_design(design))


def _image_report(png, report):
    return CallToolResult(content=[Image(data=png, format="png").to_image_content(),
                                   TextContent(type="text", text=json.dumps(report))], structured_content=report)


@mcp.tool()
@_user_errors
async def plan_vehicle_repairs(design: str) -> RepairPlan:
    """Diagnose faults and test suggested edits/wires/pipes without changing the draft.
    Returns severity, affected IDs, explanations, concrete operations and manual-review reasons.
    Use the returned revision, plan_id and available finding IDs with repair_vehicle."""
    return await run_job("plan_vehicle_repairs", _read_design(design))


@mcp.tool()
@_user_errors
async def repair_vehicle(design: str, revision: str, plan_id: str, finding_ids: list[str],
                         commit: bool = False) -> ChangeReport:
    """Preview selected repairs with overlays and before/after preflight. commit=true applies
    the whole batch as one undo step. Revision/plan guards reject stale suggestions and conflicting repairs."""
    record = _read_design(design)
    if _revision(record) != revision:
        raise ValueError("stale revision; plan_vehicle_repairs again")
    proposed, png, report = await run_job("repair_vehicle", record, plan_id, finding_ids, design)
    if commit:
        proposed = _commit_record(design, proposed, revision)
    report.update(committed=commit, revision=_revision(proposed))
    report["after"]["revision"] = report["revision"]
    return _image_report(png, report)


@mcp.tool()
@_user_errors
def list_vehicle_assemblies() -> dict[str, Any]:
    """Reusable controls, required ID bindings and gate definitions. Place any required gates
    using edit_parts, then bind queried IDs with apply_vehicle_assembly; geometry is not preset-specific."""
    from swhull.assemblies import CATALOGUE  # noqa: PLC0415
    return {"assemblies": CATALOGUE, "workflow": "query -> place gates if needed -> bind -> preview -> commit -> preflight -> game test"}


@mcp.tool()
@_user_errors
async def apply_vehicle_assembly(design: str, assembly: Literal["engine_start_idle", "clutch_engagement", "brake_reverse", "lighting"],
                                 bindings: AssemblyBindings, revision: str, options: AssemblyOptions | None = None,
                                 commit: bool = False) -> AssemblyReport:
    """Configure/wire reusable controls using explicit current part IDs. Existing target drivers
    are replaced atomically. Clutch needs its own gate, separate from the idle throttle gate.
    Starter is manual/hold; idle is open-loop, and reverse must be selected while stopped.
    Preview includes diagnostics. commit=true creates one undo step; tune behavior in game."""
    record = _read_design(design)
    if _revision(record) != revision:
        raise ValueError("stale revision; query_connections again")
    proposed, png, report = await run_job("assemble_vehicle", record, assembly, plain(bindings, AssemblyBindings),
                                        plain(options, AssemblyOptions) if options is not None else None, design)
    if commit:
        proposed = _commit_record(design, proposed, revision)
    report.update(committed=commit, revision=_revision(proposed), base_revision=revision)
    report["preflight"]["revision"] = report["revision"]
    return _image_report(png, report)


@mcp.tool()
@_user_errors
async def preview_vehicle_diagnostics(design: str, yaw: float = 35, pitch: float = 25,
                                      layer: Literal["all", "components", "structure"] = "components") -> DiagnosticReport:
    """Show red fault parts, amber blocked exits and blue wheel/steering arrows over geometry.
    Repair and assembly previews additionally show proposed green wires/pipes. Uses draft block coordinates."""
    png, report = await run_job("diagnostic_preview", _read_design(design), design, yaw, pitch, layer)
    return _image_report(png, report)


def _validation_path(run_id):
    if not re.fullmatch(r"[0-9a-f]{24}", run_id):
        raise ValueError("invalid validation run ID")
    return designs_dir() / "validation" / f"{run_id}.json"


def _write_validation(report):
    path = _validation_path(report["run_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as f:
        temporary = Path(f.name)
        json.dump(report, f, indent=2)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@mcp.tool()
@_user_errors
async def prepare_vehicle_validation(name: str, design: str, overwrite: bool = False) -> ValidationRun:
    """Export a separate test vehicle and create a seven-check in-game checklist tied to its
    exact XML SHA-256 and draft revision. Starts pending; topology never counts as game evidence."""
    record = _read_design(design)
    target, stamp = _save_target(name, record, overwrite)
    xml, report = await run_job("prepare_validation", record, design, name, str(target))
    with DESIGN_LOCK:
        if _revision(_read_design(design)) != _revision(record):
            raise ValueError("draft changed while exporting; prepare validation again")
        path = _validation_path(report["run_id"])
        if path.exists():
            raise ValueError("validation run already exists; get_vehicle_validation to review it")
        _write_vehicle(target, xml, stamp)
        _atomic_design(name, {**record, "vehicle": True})
        _write_validation(report)
    return report


@mcp.tool()
@_user_errors
def get_vehicle_validation(run_id: str) -> dict[str, Any]:
    """Read game-test evidence and report whether the export bytes and draft revision still match."""
    from swhull.validation import sha  # noqa: PLC0415
    path = _validation_path(run_id)
    if not path.is_file():
        raise ValueError("validation run not found")
    report = json.loads(path.read_text(encoding="utf-8"))
    exported = Path(report["vehicle_path"])
    return {**report, "export_matches": exported.is_file() and sha(exported.read_bytes()) == report["export_sha256"],
            "draft_matches": _design_path(report["design"]).exists() and
            _revision(_read_design(report["design"])) == report["revision"]}


@mcp.tool()
@_user_errors
def record_vehicle_validation(run_id: str, export_sha256: str, observations: list[Observation],
                              game_version: str, tester: str) -> ValidationRun:
    """Record human-observed pass/fail/skipped results with evidence and measurements.
    Refuses a changed export or mismatched hash. All seven checks need pass evidence for a passed run."""
    from swhull.validation import record_results, sha  # noqa: PLC0415
    with DESIGN_LOCK:
        current = get_vehicle_validation(run_id)
        if export_sha256 != current["export_sha256"] or not current["export_matches"]:
            raise ValueError("export changed or hash mismatch; prepare a new validation run")
        result = record_results({k: v for k, v in current.items() if k not in ("export_matches", "draft_matches")},
                                [plain(o, Observation) for o in observations], game_version, tester)
        if sha(Path(current["vehicle_path"]).read_bytes()) != export_sha256:
            raise ValueError("export changed while recording results")
        _write_validation(result)
    return result


@mcp.tool()
@_user_errors
async def preview_vehicle(design: str, yaw: float | None = None, pitch: float = 25,
                          zoom: float = 1, focus: list[float] | None = None, layer: str = "all",
                          door_state: Literal["closed", "open"] = "closed") -> list:
    """Preview a draft using installed meshes. yaw/pitch/zoom/focus gives a close-up.
    layer=all/components/structure; components hides bodywork to inspect seats/tanks/powertrain.
    Paint and wheel neutral poses are approximate; the image is not an in-game screenshot."""
    if focus is not None and len(focus) != 3:
        raise ValueError("focus must contain three fractions")
    png, note = await run_job("preview_draft", _read_design(design), design, yaw, pitch, zoom, focus, layer, door_state)
    return [Image(data=png, format="png"), note]


@mcp.tool()
@_user_errors
async def save_vehicle(name: str, design: str, overwrite: bool = False) -> str:
    """Save any draft. Imported originals are never overwritten, even with overwrite=true."""
    record = _read_design(design)
    target, stamp = _save_target(name, record, overwrite)
    xml, count, note = await run_job("export_draft", record)
    # Recheck after the worker to avoid an external file created while building.
    with DESIGN_LOCK:
        if _revision(_read_design(design)) != _revision(record):
            raise ValueError("draft changed while building; save the new revision")
        _write_vehicle(target, xml, stamp)
        _atomic_design(name, {**record, "vehicle": True})
    return f"Saved {count} parts to {target}\n{note}"


@mcp.tool()
@_user_errors
async def check_seal(design: str, seeds: list[Any] | None = None, door_state: str = "closed") -> list:
    """Trace finished geometry from interior to outside: sealed, leaking or indeterminate.
    Generated drafts choose room/hull seeds automatically. Imported drafts require seeds:
    [[x,y,z],...] or [{name,position:[x,y,z]}], in integer blocks in their original body frame.
    door_state=closed/open models supported doors. Returns connected compartments and a
    highlighted escape path. Unsupported nearby sealing geometry prevents a confident pass."""
    png, report = await run_job("seal_draft", _read_design(design), seeds, door_state, design)
    return [Image(data=png, format="png"), report]


@mcp.tool()
@_user_errors
def list_game_vehicles(search: str = "") -> list[str]:
    """Vehicles in the player's Stormworks vehicles folder, optionally filtered by a substring."""
    d = Path(vehicles_dir())
    if not d.is_dir():
        raise ValueError(f"vehicles folder not found: {d} (set SW_VEHICLES_DIR)")
    names = sorted(p.stem for p in d.iterdir() if p.suffix.lower() == ".xml")
    return [n for n in names if search.lower() in n.lower()]


@mcp.tool()
@_user_errors
async def preview_game_vehicle(name: str, source: str = "vehicles", body_id: str | None = None) -> list:
    """Render any vehicle from the player's vehicles folder, e.g. to study their existing boats.

    Uses installed component meshes, with reported footprint fallbacks. source=workshop
    reads an installed numeric item ID. For articulated vehicles choose body_id; by default
    show the largest body alone, without pretending unrelated local frames line up.
    """
    png, text = await run_job("game_vehicle", str(_reference_path(name, source)), name, body_id)
    return [Image(data=png, format="png"), text]


@mcp.tool()
@_user_errors
async def inspect_view(name: str | None = None, spec: dict[str, Any] | None = None,
                       preset: str | None = None, yaw: float = 35.0, pitch: float = 25.0,
                       zoom: float = 1.0, focus: list[float] | None = None, design: str | None = None,
                       patch: list[dict[str, Any]] | None = None, highlight: str | None = None,
                       spec_path: str | None = None, source: str = "vehicles", body_id: str | None = None) -> list:
    """Render one large view of a hull design or saved vehicle from any angle, like a
    camera you can point. Use it to check details the fixed previews hide.

    name: a vehicle in the player's vehicles folder, or pass spec/preset/design(+patch).
    yaw: 0 = side view with bow to the right, 90 = from the bow, 180 = other side, 270 = stern.
    pitch: degrees above (+) or below (-) the horizon; -30 shows the hull bottom.
    zoom: 1 = whole vehicle, 2-6 = close-up. focus: [fx, fy, fz] fractions of the bounding
    box to centre on (x across, y up, z stern to bow), e.g. [0.5, 0.3, 0.9] = low on the bow.
    highlight: a superstructure box name (designs only): painted magenta and labelled, and
    its position is reported in spec units and as game-metre heights above the keel. Views at pitch 0 or +-90 get metre rulers in spec units
    (z from the transom, y from the keel, x from the centreline).
    """
    if focus is not None and len(focus) != 3:
        raise ValueError("focus must be [fx, fy, fz]")
    zoom = max(0.2, min(zoom, 12.0))
    if name:
        if highlight:
            raise ValueError("highlight works on designs, not saved vehicles")
        png, note = await run_job("inspect_vehicle", str(_reference_path(name, source)), name, yaw, pitch,
                                  zoom, focus, body_id)
        title = name
    else:
        if source != "vehicles" or body_id is not None:
            raise ValueError("source/body_id apply only to a reference name")
        full = _spec(spec, preset, design, patch, spec_path)
        title = _title(preset, design)
        png, note = await run_job("inspect_design", full, title, yaw, pitch, zoom, focus, highlight)
    return [Image(data=png, format="png"), f"{title}: yaw {yaw}, pitch {pitch}, zoom {zoom}{note}"]


def _viewer_page(xml, name, geometry=None):
    """Copy of viewer/index.html with a vehicle embedded, written to the temp folder."""
    page = (HERE / "viewer" / "index.html").read_text(encoding="utf-8")
    data = json.dumps({"xml": xml, "name": name, "geometry": geometry}).replace("</", "<\\/")
    inject = f"<script>window.EMBEDDED_VEHICLE = {data};</script>\n"
    page = page.replace('<script type="importmap">', inject + '<script type="importmap">', 1)
    path = Path(tempfile.gettempdir()) / "stormworks-hull-mcp-view.html"
    path.write_text(page, encoding="utf-8")
    return path


@mcp.tool()
@_user_errors
async def open_in_viewer(name: str | None = None, spec: dict[str, Any] | None = None,
                         preset: str | None = None, design: str | None = None,
                         patch: list[dict[str, Any]] | None = None, spec_path: str | None = None,
                         source: str = "vehicles", body_id: str | None = None,
                         diagnostics: bool = False) -> str:
    """Open a vehicle in the interactive 3D viewer in the player's web browser.

    name: saved vehicle or installed numeric workshop item (source=workshop). design supports
    hull/land/imported drafts. Uses installed component meshes, with explicit fallbacks.
    For articulated references choose body_id; otherwise shows the largest body alone.
    """
    if diagnostics:
        if design is None or any(v is not None for v in (name, spec, preset, patch, spec_path, body_id)) or source != "vehicles":
            raise ValueError("diagnostics requires only a stored design")
        xml, geometry = await run_job("diagnostic_geometry", _read_design(design))
        page = _viewer_page(xml, design, geometry)
        webbrowser.open(page.as_uri())
        return f"Opened '{design}' with diagnostic overlays in the 3D viewer ({page})."
    if name:
        xml = _reference_path(name, source).read_text(encoding="utf-8-sig", errors="replace")
        title = name
    else:
        if source != "vehicles" or body_id is not None:
            raise ValueError("source/body_id apply only to a reference name")
        if design is not None and _read_design(design).get("kind") in ("land", "imported"):
            if any(value is not None for value in (spec, preset, patch, spec_path)):
                raise ValueError("choose a land/imported design without hull spec/preset/patch")
            xml, _, _ = await run_job("export_draft", _read_design(design))
        else:
            xml, _, _ = await run_job("vehicle_xml", _spec(spec, preset, design, patch, spec_path))
        title = design or preset or "design preview"
    geometry = await run_job("viewer_geometry", xml, body_id)
    page = _viewer_page(xml, title, geometry)
    webbrowser.open(page.as_uri())
    return f"Opened '{title}' in the 3D viewer ({page})."


if __name__ == "__main__":
    import multiprocessing  # noqa: PLC0415
    multiprocessing.freeze_support()
    mcp.run()
