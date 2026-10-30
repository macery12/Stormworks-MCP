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
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import Field

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
                                 ReferenceVehicle, RepairPlan, RouteBatch, Selection, plain)
from swhull.study import ranges as reference_ranges
from swhull.tool_params import (CREATE, EDIT, READ, REPLACE, VIEWER, BodyId, Commit, Design, Detail, DoorState,
                                Draft, Focus, Layer, Limit, NewVehicleName, Offset, OptionalVehicleName, Overwrite,
                                Patch, Pitch, Preset, Preview, RendererChoice, Revision, Source, Spec, SpecPath,
                                VehicleName, Yaw, Zoom)
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


def references_dir():
    """Local reference sets (studies of vehicles the player rates). SW_REFERENCES_DIR overrides."""
    if os.environ.get("SW_REFERENCES_DIR"):
        return Path(os.environ["SW_REFERENCES_DIR"])
    return designs_dir().parent / "reference_sets"


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
study_references stores how the player's favourite builds are made; score_vehicle compares a
design with them and names the habits it misses (slope sizes, ballast, detail, paint, logic).
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
access -> propulsion -> tanks -> powertrain. Use smoothing="wedges_v2" for hulls; plain blocks
(the default) look stepped in game, so use them only when the player asks for blocks.
Optional fitout.stage places real game-sized batteries and a helm/seat; access adds complete
manual doors and requested hatch/ladder assemblies; propulsion sets the propeller hub into the
transom and the rudder into the bottom; powertrain adds a small diesel low inside the hull with
radiator, fuel tank, deck air intake and transom exhaust, all piped (fitout.engines 1 or 2;
fitout.engine_size auto/small/medium/large; aircraft_engine is the game's Medium Engine, a diesel).
Edit tools reply compactly with what changed; pass preview=true for images.
Never put an engine on the deck or hang a propeller/rudder behind the transom; builds warn.
Named components/tanks remain in game metres when the hull is scaled. Report every automatic
choice and skipped placement. Never carve a hatch without its complete fitted assembly.
For exact edits use query_parts -> edit_parts preview -> edit_parts commit with the same revision;
these tools use integer blocks in the fixed build frame, not centred export coordinates.
Import single-body v3 vehicles into a draft and save a separate copy; configured originals
remain in place. Use check_seal after edits, including explicit seed points for imports.
Unknown sealing geometry is indeterminate. Invalid custom tanks cannot be exported.
Use search_parts/get_part_definition for installed footprints/surfaces and seal coverage.
Heavy tools use cancellable workers and a
shared geometry cache. Read docs/staged-builder.md through the design guide for examples."""

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
    _atomic_json(_design_path(name), record)


def _atomic_json(path, record):
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


def _write_vehicle(target, xml, previous, thumbnail=None):
    """Write the vehicle XML, and its Load-menu thumbnail (same name, .png) when given."""
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
    if thumbnail:
        _write_thumbnail(target.with_suffix(".png"), thumbnail)


def _write_thumbnail(path, png):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, suffix=".tmp", delete=False) as f:
            temporary = Path(f.name)
            f.write(png)
        os.replace(temporary, path)
    except OSError:
        pass  # the vehicle is saved; the game shows a blank tile without its thumbnail
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def _thumbnail(xml):
    """The game only draws a thumbnail when the player saves at a workbench, so vehicles
    written here had a blank tile in the Load menu. A failed drawing never stops a save."""
    try:
        return await run_job("thumbnail", xml, timeout=120)
    except ValueError:
        return None


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


@mcp.tool(annotations=READ)
@_user_errors
def hull_design_guide(topic: Annotated[Literal["full", "workflow", "units", "spec", "interior", "archetypes", "style",
                                               "limits", "staged", "building", "testing", "smoothing", "edits",
                                               "topics"], Field(description=(
        "Section to return: full (everything), workflow (start here), units, spec (every field), "
        "interior, archetypes (starting proportions), style, limits, staged (staged builder), "
        "building and edits (building step by step, exact edits), testing (what is verified in game), "
        "smoothing (wedge skins), topics (list the topics)."))] = "full") -> str:
    """Return the boat design guide as Markdown: workflow, units, every spec field, style rules
    and lessons from in-game testing. Read topic="workflow" before designing a boat, then fetch
    focused topics as needed instead of resending the full guide. Road and land vehicles have
    their own guide (land_vehicle_guide). Read-only."""
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


@mcp.tool(annotations=READ)
@_user_errors
def get_runtime_status() -> dict[str, Any]:
    """Report the server version and the paths it uses: Stormworks vehicles folder, game part
    definitions, stored designs, build cache, and the tool timeout, with notes on anything missing.
    Use it when a tool cannot find the game, its parts or the player's vehicles. Read-only; it
    never creates folders."""
    from swhull.diagnostics import runtime_status  # noqa: PLC0415
    return runtime_status()


@mcp.tool(annotations=READ)
@_user_errors
def list_hull_presets() -> str:
    """List the built-in boat hull presets: name, one-line description, length x beam x depth
    in metres, and whether it has an interior. Pass a name as `preset` to preview_hull or
    save_hull, or to get_hull_spec to see every value it sets. Stored designs are listed by
    list_designs and the player's saved vehicles by list_game_vehicles. Read-only."""
    lines = []
    for name, p in PRESETS.items():
        s = p["spec"]
        lines.append(f"- {name}: {p['about']} ({s.get('length')} m x {s.get('beam')} m, "
                     f"depth {s.get('depth')} m{', with interior' if s.get('interior') else ''})")
    return "\n".join(lines)


@mcp.tool(annotations=READ)
@_user_errors
def list_workbenches() -> str:
    """List the workbench size keywords (S, M, L, XL, XXL, MAX) with each size in metres and
    the edit areas in the player's game, including workbench mods, that are at least that big.
    Ask the player which bench they will build at, then set it as `bench` in the spec; preview
    summaries then say whether the design fits and by how much it misses. Read-only."""
    return describe_benches()


@mcp.tool(annotations=READ)
@_user_errors
def get_hull_spec(preset: Annotated[str | None, Field(description=(
        "Preset name from list_hull_presets; omit for the plain defaults."))] = None) -> dict[str, Any]:
    """Return the fully resolved hull spec, every parameter with its value, for a preset or for
    the defaults. Use it to see what a preset sets or as a starting spec to copy and change;
    hull_design_guide(topic="spec") explains each field. Read-only."""
    return resolve_spec(preset=preset)


@mcp.tool(annotations=READ)
@_user_errors
async def preview_hull(spec: Spec = None, preset: Preset = None, design: Design = None, patch: Patch = None,
                       spec_path: SpecPath = None, renderer: RendererChoice = None) -> list:
    """Build a hull and return a preview image (3/4 views from above and below, front, side,
    top) plus a text summary: size, part counts, deck heights, flotation estimate, bench fit and
    warnings. This is the design loop: preview, compare the image with the player's brief,
    adjust, repeat, then save_hull. Use inspect_view for one large close-up from any angle and
    preview_interior for rooms. Nothing is written. Spec sources apply in order: preset or
    design, spec_path, spec, patch."""
    full = _spec(spec, preset, design, patch, spec_path)
    png, text = await run_job("preview", full, _title(preset, design), renderer)
    return [Image(data=png, format="png"), text]


@mcp.tool(annotations=READ)
@_user_errors
async def preview_interior(spec: Spec = None, preset: Preset = None, design: Design = None, patch: Patch = None,
                           spec_path: SpecPath = None) -> list:
    """Render an interior cutaway: a centreline section plus a labelled deck plan for every room
    level, and a per-room report (clear size, floor width, doors with sill heights and floor
    steps, engines, warnings). Use it after adding `interior` to a spec (hull_design_guide
    topic=interior); preview_hull shows the outside. Floors above the main deck are cropped to
    their rooms. Nothing is written."""
    full = _spec(spec, preset, design, patch, spec_path)
    png, text = await run_job("interior", full, _title(preset, design))
    return [Image(data=png, format="png"), text]


@mcp.tool(annotations=READ)
@_user_errors
def deck_profile(spec: Spec = None, preset: Preset = None, design: Design = None, patch: Patch = None,
                 step: Annotated[float, Field(description="Station spacing in spec units (metres), "
                                              "measured forward from the transom.", gt=0)] = 1.0,
                 spec_path: SpecPath = None) -> str:
    """Tabulate the deck at stations from the transom: deck height above the keel, the `y` a
    superstructure box gets when y is left out, and the deck half-beam. Use it to place turrets
    and deckhouses on a sheered deck instead of guessing heights. Lengths are in spec units
    (real-world metres when the spec has a `scale`). Read-only; returns a text table."""
    return _deck_profile(_spec(spec, preset, design, patch, spec_path), step)


@mcp.tool(annotations=EDIT)
@_user_errors
async def save_hull(name: NewVehicleName, spec: Spec = None, preset: Preset = None,
                    overwrite: Overwrite = False, design: Design = None,
                    patch: Patch = None, spec_path: SpecPath = None) -> str:
    """Write a hull into the Stormworks vehicles folder as <name>.xml with its Load-menu
    thumbnail, and store the spec as a design of the same name. Use it once the preview is
    approved, e.g. save_hull(name="Iowa", design="Iowa"); drafts edited part by part (imports,
    land vehicles) use save_vehicle. Refuses a name already used by a vehicle this tool did not
    write, and replaces its own earlier save only with overwrite=true. Returns the file path, part
    count and summary; the player loads it from a workbench's Load menu."""
    full = _spec(spec, preset, design, patch, spec_path)
    record = {"preset": preset, "vehicle": True, "spec": full}
    target, stamp = _save_target(name, record, overwrite)
    xml, parts, text = await run_job("vehicle_xml", full)
    thumbnail = await _thumbnail(xml)
    with DESIGN_LOCK:
        _write_vehicle(target, xml, stamp, thumbnail)
        previous = _read_design(name) if _design_path(name).exists() else {}
        _atomic_design(name, {**record, "generation": previous.get("generation", 0) + 1})
    return (f"Saved {parts} parts to {target}\n{text}\n"
            f"In game: open a workbench, press Load, choose '{name}'.")


@mcp.tool(annotations=REPLACE)
@_user_errors
def store_design(name: Annotated[str, Field(description=(
                     "Name to store the spec under (letters, digits, spaces, _ - ( ), at most 64); "
                     "replaces any stored design of that name."))],
                 spec: Spec = None, preset: Preset = None, design: Design = None, patch: Patch = None,
                 spec_path: SpecPath = None) -> str:
    """Keep a design spec on the server without writing a vehicle, so later calls can send
    only changes. Typical loop: store_design("Iowa", spec=...) once, then
    preview_hull(design="Iowa", patch=[...]) to try a change and
    store_design("Iowa", design="Iowa", patch=[...]) to keep it. Replaces any stored design
    of that name; save_hull(name, design=name) writes the vehicle when ready.
    design=X copies all of draft X: its spec, the parts added with edit_parts, and its wires and
    pipes (a patch that removes a part they use makes later calls ask you to reconnect it).
    Undo history is not copied. Stored designs are plain JSON files that every call re-reads,
    so editing one on disk takes effect at once. Returns the stored file's path."""
    full = _spec(spec, preset, design, patch, spec_path)
    path = _design_path(name)
    with DESIGN_LOCK:
        previous = _read_design(name) if path.is_file() else {}
        source = _read_design(design) if design else {}
        # Wires and pipes live beside the spec; a copy without them strands hand-placed parts.
        carried = {k: source[k] for k in ("connection_edits", "route_edits") if source.get(k)}
        _atomic_design(name, {"preset": preset, "vehicle": previous.get("vehicle", False),
                              "spec": full, "generation": previous.get("generation", 0) + 1, **carried})
    boxes = len(full.get("superstructure") or [])
    return (f"Stored design '{name}' ({full['length']} m, {boxes} superstructure entries) at "
            f"{path}. Use design=\"{name}\" with patch=[...] in any tool; edits to that file "
            "on disk apply to the next call.")


@mcp.tool(annotations=READ)
@_user_errors
def list_designs() -> list[str]:
    """List the names of drafts stored on this server, sorted: hull designs (store_design,
    save_hull), imported vehicles (import_vehicle) and land drafts (create_land_vehicle). Pass a
    name as `design` to other tools, or to load_design to read it. Vehicles in the game's folder
    are listed by list_game_vehicles instead. Read-only."""
    d = designs_dir()
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


@mcp.tool(annotations=READ)
@_user_errors
def load_design(name: Annotated[str, Field(description="Stored draft name from list_designs.")]) -> dict[str, Any]:
    """Read a stored draft. A hull design returns its full spec; to change it, prefer
    design=name with patch=[...] in preview_hull or store_design over resending the spec. An
    imported or land draft returns its kind, source, current revision, coordinate frame and edit
    log; change those with query_parts and edit_parts, not a spec. Read-only; fails when no
    draft has that name."""
    record = _read_design(name)
    if record.get("kind") == "land":
        return {"kind": "land", "spec": record["spec"], "revision": _revision(record),
                "coordinates": "build-frame integer blocks; +y up, +z forward, chassis top y=0"}
    if record.get("kind") == "imported":
        return {"kind": "imported", "source": record["source"], "revision": _revision(record),
                "edits": record.get("edits", []), "coordinates": "original body-local integer blocks"}
    return record["spec"]


@mcp.tool(annotations=READ)
@_user_errors
def search_parts(search: Annotated[str, Field(description=(
                     "Case-insensitive text in the definition id or display name; empty lists every part."))] = "",
                 offset: Offset = 0, limit: Limit(200) = 50) -> dict[str, Any]:
    """Search the installed Stormworks part catalogue by definition id or display name. Each
    row gives the id, display name, size in blocks and metres, and mass, with the total and
    next_offset for paging. Use it to find a definition id, then get_part_definition for
    surfaces and sealing or get_part_orientation for mounting axes. search_land_parts groups
    land-build families; query_parts lists the parts inside a draft. Read-only."""
    return definitions.catalogue(search, offset, limit)


@mcp.tool(annotations=READ)
@_user_errors
def get_part_definition(definition: Annotated[str, Field(description=(
        'Definition id: the game file name without .xml, e.g. "01_block"; find ids with search_parts.'))]
        ) -> dict[str, Any]:
    """Return one installed part's definition: footprint voxels, attachment and sealing
    surfaces, logic nodes, settings, mass, seal coverage, and whether new placement is allowed
    (with the reason when it is not). Use it after search_parts to check how a part mounts,
    connects or seals; get_part_orientation solves its rotation. Read-only; fails when the
    definition is not installed."""
    result = definitions.metadata(definition)
    if result is None:
        raise ValueError(definitions.unavailable(definition))
    from swhull.seal import coverage  # noqa: PLC0415
    from swhull.part_policy import allowed, restriction  # noqa: PLC0415
    return {**result, "seal_coverage": coverage(definition), "placement_allowed": allowed(definition),
            "placement_restriction": restriction(definition)}


@mcp.tool(annotations=READ)
@_user_errors
def get_part_orientation(definition: Annotated[str, Field(description=(
                             'Definition id, e.g. "rudder"; find ids with search_parts.'))],
                         targets: Annotated[dict[str, list[int]] | None, Field(description=(
                             "Wanted world direction per local axis, as integer unit vectors, e.g. "
                             '{"mount_normal": [0,0,1], "span_axis": [0,1,0]}; omit to see the axes '
                             "and the default solution."))] = None) -> dict[str, Any]:
    """Explain a part's local mounting, motion and function axes and solve the rotation that
    points them in the requested world directions. Example Fin Rudder targets:
    mount_normal=[0,0,1], span_axis=[0,1,0]. Road wheel targets should include axle_axis,
    wheel_reference_up and wheel_forward; right placements can require mirror. Returns the
    effective rotation plus the proper r and mirror for edit_parts or XML. Read-only; arrow
    signs still need checking in game."""
    from swhull.orientation import describe  # noqa: PLC0415
    return describe(definition, targets)


@mcp.tool(annotations=READ)
@_user_errors
def get_calibration_observations(definition: Annotated[str, Field(description=(
        'Definition id the player tested, e.g. "rudder".'))]) -> dict[str, Any]:
    """Read the player's recorded in-game checks for one part: the latest result per test case
    and check, the number of stale reports (the definition or test vehicle changed since), and
    checks with contradictory results. Use it before relying on an orientation or mounting rule
    for that part. It reports evidence and runs no test. Read-only; returns no checks when
    nothing was recorded."""
    from swhull.calibration import observations  # noqa: PLC0415
    directory = os.environ.get("SW_CALIBRATION_DIR", str(Path(__file__).parent / "out/advanced-suite/calibration"))
    return observations(definition, directory)


@mcp.tool(annotations=READ)
@_user_errors
def land_vehicle_guide() -> str:
    """Return the road and land vehicle guide as Markdown: workflow, installed parts, chassis
    spec, units, layout limits and the checks to do in game. Read it before create_land_vehicle
    or any land work; boats use hull_design_guide instead. Read-only."""
    return (HERE / "docs" / "land-vehicles.md").read_text(encoding="utf-8")


@mcp.tool(annotations=READ)
@_user_errors
async def search_land_parts(category: Annotated[Literal["", "wheels", "tracks", "lights", "controls", "propulsion",
                                                        "transmission", "power", "fuel", "cooling", "body", "logic",
                                                        "utility"], Field(description=(
                                "Land-build family to list; empty lists all families."))] = "",
                            search: Annotated[str, Field(description=(
                                "Case-insensitive text in the definition id or display name."))] = "",
                            offset: Offset = 0, limit: Limit(200) = 50) -> dict[str, Any]:
    """List installed components useful for land builds, by family, with footprints and their
    actual connection ports, with paging. Use it to choose parts for a land draft. search_parts
    covers the whole catalogue without families; get_part_definition and get_part_orientation
    give one part's detail. Read-only."""
    return await run_job("land_parts", category, search, offset, limit)


@mcp.tool(annotations=READ)
@_user_errors
async def find_land_vehicles(search: Annotated[str, Field(description="Text in the vehicle name; empty for all.")] = "",
                             kind: Annotated[str, Field(description='"wheeled" (default), "tracked" or "all".')] = "wheeled",
                             offset: Offset = 0, limit: Limit(200) = 50,
                             source: Source = "vehicles") -> dict[str, Any]:
    """Scan the player's saved vehicles, or installed Workshop items, for wheel or track
    layouts to use as land-build references, including unnamed experiments, with paging. Counts
    vehicle body components only, not controller internals; wheeled boats or aircraft can match,
    so a hit says nothing about a vehicle's purpose or quality. Follow up on a match with
    analyze_land_vehicle; list_game_vehicles only lists names. Read-only."""
    if source not in ("vehicles", "workshop"):
        raise ValueError("source must be vehicles or workshop")
    directories = definitions.workshop_dirs() if source == "workshop" else [vehicles_dir()]
    return await run_job("land_library", directories, search, kind, offset, limit, source)


@mcp.tool(annotations=READ)
@_user_errors
async def analyze_land_vehicle(name: OptionalVehicleName = None,
                               design: Annotated[str | None, Field(description=(
                                   "Stored land or imported draft to analyse instead of a saved vehicle."))] = None,
                               body_id: BodyId = None,
                               forward: Annotated[list[int] | None, Field(description=(
                                   "Horizontal unit vector for the vehicle's forward, body-local, e.g. "
                                   "[0,0,1]; default infers it from the driver seat, else +z."))] = None,
                               section: Annotated[str, Field(description=(
                                   '"wheels" (default), "lights", "controls", "equipment" or "issues".'))] = "wheels",
                               offset: Offset = 0, limit: Limit(200) = 50,
                               source: Source = "vehicles",
                               wheel_roles: Annotated[dict[str, Literal["road", "spare", "excluded"]] | None, Field(
                                   description="Role per wheel component id; spare and excluded wheels "
                                               "stay out of axle measurements.")] = None,
                               exclude_wheel_ids: Annotated[list[str] | None, Field(description=(
                                   "Wheel component ids to leave out of axle measurements."))] = None) -> dict[str, Any]:
    """Measure a saved vehicle or a land draft for land building: body-local axles, wheelbase,
    mounts, light axes, controls and equipment, one section per call with paging. Use it on
    references from find_land_vehicles or on your own draft before editing; general part audits
    of boats use analyze_vehicle. Axle span measures mounting origins, not tyre-centre track;
    multi-body vehicles stay separate; suspension, steering sweep and mesh fit still need game
    checks. Read-only."""
    if (name is None) == (design is None):
        raise ValueError("choose exactly one saved vehicle name or draft design")
    if design is not None and source != "vehicles":
        raise ValueError("source applies only to a reference name")
    path = str(_reference_path(name, source)) if name is not None else None
    record = _read_design(design) if design is not None else None
    return await run_job("land_layout", path, record, body_id, forward, section, offset, limit, wheel_roles, exclude_wheel_ids)


@mcp.tool(annotations=CREATE)
@_user_errors
async def create_land_vehicle(design: Annotated[str, Field(description=(
                                  "Name for the new draft; must not exist yet (see list_designs)."))],
                              spec: Annotated[dict[str, Any] | None, Field(description=(
                                  "Land spec (fields in land_vehicle_guide). spec.preset chooses utility_buggy "
                                  "(default), humvee_4x4, utility_4x4 or chassis (bare custom layout). "
                                  "Dimensions in game metres on the 0.25 m grid."))] = None) -> list:
    """Create a new land vehicle draft and return its preview image, notes and revision. The
    default utility buggy has bodywork, four suspension wheels, saddle, premade fuel tanks,
    engine, battery, radiator and lights; humvee_4x4 has four seats, open custom-door bays,
    compact glass and enclosed chassis pipework; utility_4x4 keeps the older sliding-door layout.
    Read land_vehicle_guide first. Writes only a stored draft, never a game file, and refuses
    an existing name. Then complete it with query_parts/edit_parts and the connection tools,
    check it with preflight_vehicle, and save it with save_vehicle."""
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


@mcp.tool(annotations=READ)
@_user_errors
async def analyze_vehicle(name: VehicleName,
                          search: Annotated[str, Field(description=(
                              "Filter rows by text, e.g. rudder, propeller, engine or trans."))] = "",
                          offset: Offset = 0, limit: Limit(200) = 50,
                          section: Annotated[str, Field(description=(
                              '"parts" (default), "links", "controllers", "bodies", "placement_issues", '
                              '"connection_candidates" or "open_transmission_ports".'))] = "parts",
                          source: Source = "vehicles") -> dict[str, Any]:
    """Audit how a saved vehicle is built: parts, logic links, controllers, bodies, placement
    issues such as rudder mounting and motion, connection candidates and open transmission
    ports, one section per call with paging. Use it to learn from the player's vehicles or to
    debug a save. Wheel layouts use analyze_land_vehicle, and hull material and floor gaps use
    analyze_hull. Handles multi-body vehicles. Read-only; findings are observations, not game
    verification."""
    return await run_job("analyze_reference", str(_reference_path(name, source)), search, offset, limit, section)


def _reference_set_path(name):
    _check_name(name)
    return references_dir() / f"{name}.json"


@mcp.tool(annotations=REPLACE)
@_user_errors
async def study_references(references: Annotated[list[ReferenceVehicle], Field(description=(
                               "Vehicles to study: name (saved vehicle or Workshop ID), source "
                               "(vehicles or workshop), optional kind (boat, land, other) and label."))],
                           save_as: Annotated[str | None, Field(description=(
                               "Store the set under this name for score_vehicle, replacing a set of the "
                               "same name; omit to only measure."))] = None) -> dict[str, Any]:
    """Measure how vehicles the player rates are built: slope piece sizes, pyramid/inverse
    pairing, ballast, sub-bodies, detail parts, paint and logic. kind (boat/land/other) is
    detected from road wheels and marine propulsion unless given; mark hovercraft, aircraft and
    unusual builds "other" so they don't widen the boat range. Returns per-vehicle metrics and
    the min-max range per kind. Writes nothing unless save_as is given. Measurements describe
    habits, not quality."""
    if not references:
        raise ValueError("give at least one reference vehicle")
    if save_as is not None:
        _check_name(save_as)
    entries = [(str(_reference_path(r.name, r.source)), r.kind) for r in references]
    studies = await run_job("study_references", entries)
    rows = [{"label": r.label or r.name, "name": r.name, "source": r.source, **s}
            for r, s in zip(references, studies)]
    out = {"references": [{"label": row["label"], "kind": row["kind"], "parts": row["counts"]["parts"],
                           "bodies": row["counts"]["bodies"], "metrics": row["metrics"]} for row in rows],
           "ranges": {kind: reference_ranges(studies, kind) for kind in sorted({s["kind"] for s in studies})}}
    if save_as is not None:
        path = _reference_set_path(save_as)
        _atomic_json(path, {"name": save_as, "references": rows})
        out["saved"] = str(path)
    return out


@mcp.tool(annotations=READ)
@_user_errors
async def score_vehicle(reference_set: Annotated[str, Field(description=(
                            "Reference set stored by study_references(save_as=...)."))],
                        name: OptionalVehicleName = None,
                        source: Annotated[Literal["vehicles", "workshop"], Field(description=(
                            "Where name is read from: the vehicles folder or a Workshop item."))] = "vehicles",
                        design: Design = None, spec: Spec = None, preset: Preset = None,
                        patch: Patch = None,
                        kind: Annotated[Literal["boat", "land", "other"] | None, Field(description=(
                            "Compare against references of this kind; default detects it."))] = None
                        ) -> dict[str, Any]:
    """Compare a saved vehicle (name), a draft or stored design, or a hull spec/preset with a
    reference set from study_references. Each construction metric is checked against the
    min-max of references of the same kind, with a hint where it falls outside. A miss says
    where to look, not that the vehicle is broken: references differ in size and purpose.
    Read-only."""
    path = _reference_set_path(reference_set)
    if not path.is_file():
        stored = sorted(p.stem for p in references_dir().glob("*.json")) if references_dir().is_dir() else []
        raise ValueError(f"no reference set named '{reference_set}'; " + (
            f"stored sets: {', '.join(stored)}" if stored else "create one with study_references(save_as=...)"))
    references = json.loads(path.read_text(encoding="utf-8"))["references"]
    if name is not None:
        if any(v is not None for v in (design, spec, preset, patch)):
            raise ValueError("choose a saved vehicle name or a design/spec, not both")
        return await run_job("score_vehicle", str(_reference_path(name, source)), None, references, kind)
    if all(v is None for v in (design, spec, preset)):
        raise ValueError("give a saved vehicle name, a design, a spec or a preset")
    record = _read_design(design) if design is not None else None
    if not (record and record.get("kind") in ("imported", "land") and patch is None and spec is None):
        record = {"spec": _spec(spec, preset, design, patch)}
    return await run_job("score_vehicle", None, record, references, kind)


@mcp.tool(annotations=READ)
@_user_errors
def suggest_hull_blocks(normal: Annotated[list[float], Field(description=(
                            "Outward surface normal as world [x, y, z] (y up, z forward); need not be unit length."))],
                        limit: Limit(20, "Families to return") = 6) -> dict[str, Any]:
    """Rank the game's slope block families (wedges, pyramids and inverse pyramids by slope
    ratio) by how closely they match a surface's outward normal, with the rules for choosing
    between them. Use it when placing hull slopes by hand. The angle alone cannot choose
    pyramid vs inverse, the position, or a watertight joint: check those with inspect_view and
    check_seal. Read-only."""
    from swhull.hull_analysis import block_choices  # noqa: PLC0415
    return block_choices(normal, limit)


@mcp.tool(annotations=READ)
@_user_errors
async def analyze_hull(name: Annotated[str | None, Field(description=(
                           "Saved vehicle to measure (one body at a time); omit to build spec/preset/design."))] = None,
                       spec: Spec = None, preset: Preset = None, design: Design = None, patch: Patch = None,
                       body_id: BodyId = None,
                       stations: Annotated[list[int] | None, Field(description=(
                           "z stations to report, in integer blocks; default picks representative ones."))] = None,
                       x: Annotated[int, Field(description="x column for the section, in integer blocks.")] = 0,
                       source: Annotated[str, Field(description=(
                           '"vehicles" (default) or "backups" (data/backups/vehicles, e.g. name="autosave9").'))]
                       = "vehicles") -> dict[str, Any]:
    """Measure actual hull material, floor gaps and partial-face seams at z stations: keel,
    walking floor and rim separately, since a part's footprint is not its solid material. Use it
    before saving to check depth and floor height, or to study a saved hull. Procedural reports
    use the fixed build frame and include floor height above keel and drop from the rim; saved
    vehicles use their own body-local frame, so pick body_id when the largest body is not the
    hull. Read-only geometry, not a seal test (use check_seal)."""
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


@mcp.tool(annotations=CREATE)
@_user_errors
async def import_vehicle(name: VehicleName,
                         design: Annotated[str, Field(description=(
                             "Name for the new draft; must not exist yet (see list_designs)."))],
                         source: Source = "vehicles") -> str:
    """Copy an existing single-body vehicle (data version 3) into a new editable draft; the
    source file is never changed. Use it to modify a vehicle the player already has, then
    query_parts/edit_parts, preview_vehicle, and save_vehicle under a different name. Configured
    and wired parts are protected. Fails when the draft name exists, the vehicle has several
    bodies or it uses an older data version. Returns the part count."""
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


@mcp.tool(annotations=READ)
@_user_errors
async def query_parts(design: Draft,
                      select: Annotated[Selection | None, Field(description=(
                          "Filter by ids, name, definition, or inclusive bounds [[min_x,min_y,min_z],"
                          "[max_x,max_y,max_z]] in blocks; omit for all parts."))] = None,
                      offset: Offset = 0, limit: Limit(1000) = 100) -> dict[str, Any]:
    """List a draft's parts and its current revision for exact editing. Rows include id,
    definition, position, scalar settings, proper rotation plus a local mirror bitmask, and the
    effective transform matrix. Coordinates are integer blocks (0.25 m): the uncentred build
    frame for generated hulls and land drafts, the original body-local frame for imports. Call it
    before edit_parts and pass its revision. A selection that cuts through a multi-voxel part is
    rejected; select its id instead. Read-only."""
    return await run_job("query_draft", _read_design(design), plain(select, Selection) if select is not None else None, offset, limit)


@mcp.tool(annotations=EDIT)
@_user_errors
async def edit_parts(design: Draft,
                     operations: Annotated[EditBatch, Field(description=(
                         "1-100 operations applied in order as one atomic batch; see the description."))],
                     revision: Revision, commit: Commit = False, preview: Preview = False) -> list:
    """Add, remove, move, rotate, paint or copy parts in a draft as one atomic batch. Pass the
    revision from query_parts.
    Ops: add(part/parts), fill(bounds,color), remove/replace/move/rotate/paint/copy/mirror/repeat.
    Selection ops need select={ids/bounds/name/definition}. move/copy/repeat use delta in blocks;
    repeat count is additional copies; rotate uses a local-to-world matrix or r string and pivot;
    mirror uses axis and plane. replace needs part; paint needs color. Added parts use definition,
    position in blocks, rotation, optional mirror (1=x, 2=y, 4=z), color, name and scalar settings.
    Placement rotation accepts an effective mirrored matrix; use that or proper rotation plus
    mirror. Prebuilt engines default to max_force_scale=1 (100%). Returns what changed (added
    parts with their new ids, such as edit:0:0, next to the names you gave), warnings and the new
    revision; preview=true adds the image and full notes. commit=true keeps one undo step
    (undo_edits). Wires and pipes use edit_connections and route_connections."""
    record = _read_design(design)
    if _revision(record) != revision:
        raise ValueError("stale revision; query_parts again before editing")
    proposed, png, note = await run_job("edit_draft", record, plain(operations, EditBatch), design, preview)
    if commit:
        proposed = _commit_record(design, proposed, revision)
    return [*_maybe_image(png), note,
            {"committed": commit, "revision": _revision(proposed),
             "base_revision": revision, "operations": len(operations)}]


def _maybe_image(png):
    return [Image(data=png, format="png")] if png else []


@mcp.tool(annotations=EDIT)
@_user_errors
def undo_edits(design: Draft, revision: Revision) -> dict[str, Any]:
    """Revert a draft to before its last committed batch from edit_parts, edit_connections,
    route_connections, repair_vehicle or apply_vehicle_assembly. Keeps up to ten batches; there
    is no redo. Fails when the revision is stale or nothing is left to undo. Returns the new
    revision and the number of undo steps remaining."""
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


@mcp.tool(annotations=READ)
@_user_errors
async def query_connections(design: Draft, offset: Offset = 0, limit: Limit(200, "Components per page") = 100
                            ) -> dict[str, Any]:
    """List a draft's connection points and links: each component's logic and electric node
    indices and its pipe/transmission surface indices, existing wires and routes with stable
    link ids, and the draft revision. Call it before edit_connections, route_connections or
    apply_vehicle_assembly. Wire endpoints are {part_id,port}; pipe endpoints are
    {part_id,surface_index}. Coordinates are uncentred integer blocks. Read-only, paged by
    component; query_parts lists geometry instead."""
    return await run_job("query_connections", _read_design(design), offset, limit)


@mcp.tool(annotations=EDIT)
@_user_errors
async def edit_connections(design: Draft,
                           operations: Annotated[ConnectionBatch, Field(description=(
                               "1-100 connect/disconnect operations applied as one atomic batch."))],
                           revision: Revision, commit: Commit = False, preview: Preview = False) -> list:
    """Add or remove typed control and electrical wires in a draft. Uses the
    query_connections revision.
    Ops: {op:'connect',from:{part_id,port},to:{part_id,port}} or {op:'disconnect',link_id}.
    Signal outputs connect to inputs; electricity is bidirectional. One driver per signal input.
    Pipes and shafts use route_connections; whole starter, clutch, brake or light set-ups use
    apply_vehicle_assembly. Original XML and settings stay lossless. Returns the wires added and
    removed, warnings and the new revision; preview=true adds the image and full notes.
    commit=true keeps one undo step."""
    record = _read_design(design)
    if _revision(record) != revision:
        raise ValueError("stale revision; query_connections again")
    proposed, png, note = await run_job("edit_connections", record, plain(operations, ConnectionBatch), design,
                                        preview)
    if commit:
        proposed = _commit_record(design, proposed, revision)
    return [*_maybe_image(png), note,
            {"committed": commit, "revision": _revision(proposed), "base_revision": revision}]


@mcp.tool(annotations=EDIT)
@_user_errors
async def route_connections(design: Draft,
                            routes: Annotated[RouteBatch, Field(description=(
                                "1-100 routes to add or {op:'remove',route_id} entries; see the description."))],
                            revision: Revision, commit: Commit = False, preview: Preview = False) -> list:
    """Lay physical pipes between transmission faces in a draft, preserving access and
    structure. Wires use edit_connections instead.
    Each route: {from:{part_id,surface_index},to:{part_id,surface_index},bounds?:[[lo],[hi]],
    waypoints?:[[x,y,z],...],name?:str,pipe_style?:auto|exposed|enclosed,through_blocks?:[part_id,...],
    color?:RRGGBB}. Bounds/waypoints use integer blocks. Routes minimize length, then bends. Default
    auto uses enclosed pipes for explicitly selected through_blocks; other cells use exposed pipes.
    through_blocks replaces only selected unconfigured/unlinked 01_block parts, retaining paint.
    Exposed pipes are colour-coded by contents (ISO 14726: fuel brown, cooling/fresh water blue,
    sea water green, exhaust black, air maroon, oil orange; shafts orange); color overrides it.
    Enclosed pipes keep the colour of the hull around them.
    All selected blocks must lie on the route (use waypoints if needed); removal restores them.
    Other structure and access are preserved; routes never join unrelated pipe networks.
    Clutch/gearbox ports may use several routes; create an explicit T-piece for a branch.
    Remove an added route with {op:'remove',route_id} from query_connections, then reroute.
    Returns the pipes added per route, warnings and the new revision; preview=true adds the image
    and full notes. commit=true keeps one undo step."""
    record = _read_design(design)
    if _revision(record) != revision:
        raise ValueError("stale revision; query_connections again")
    proposed, png, note = await run_job("route_connections", record, plain(routes, RouteBatch), design, preview)
    if commit:
        proposed = _commit_record(design, proposed, revision)
    return [*_maybe_image(png), note,
            {"committed": commit, "revision": _revision(proposed), "base_revision": revision}]


@mcp.tool(annotations=READ)
@_user_errors
async def preflight_vehicle(design: Draft, detail: Detail = False) -> PreflightReport:
    """Check that a draft's systems are connected: engine fuel/air/exhaust/radiator paths,
    driveline (to wheels, or straight to a propeller on boats: no clutch or gearbox needed),
    electrical power and controls. By default lists only the faults, each once; detail=true adds
    every passing check, configuration_checks (explicit engine power),
    gearbox_configuration_checks, wheel_direction_checks and repair operations. A missing check's
    detail names what it expected and what the port does reach. Run it after wiring or routing
    and before saving; plan_vehicle_repairs turns its findings into fixes. Read-only; connected
    geometry still needs testing in game."""
    return await run_job("preflight_vehicle", _read_design(design), detail)


def _image_report(png, report):
    return CallToolResult(content=[Image(data=png, format="png").to_image_content(),
                                   TextContent(type="text", text=json.dumps(report))], structured_content=report)


@mcp.tool(annotations=READ)
@_user_errors
async def plan_vehicle_repairs(design: Draft) -> RepairPlan:
    """Diagnose a draft's faults and test suggested edits, wires and pipes without changing it.
    Returns each finding's severity, affected ids, explanation, concrete operations, and whether
    it can be repaired automatically or needs a design choice. Pass the returned revision,
    plan_id and the ids of available findings to repair_vehicle. Read-only."""
    return await run_job("plan_vehicle_repairs", _read_design(design))


@mcp.tool(annotations=EDIT)
@_user_errors
async def repair_vehicle(design: Draft,
                         revision: Annotated[str, Field(description="Revision returned by plan_vehicle_repairs.")],
                         plan_id: Annotated[str, Field(description="plan_id returned by plan_vehicle_repairs.")],
                         finding_ids: Annotated[list[str], Field(description=(
                             "Ids of findings with repair_status=available to apply together."))],
                         commit: Commit = False) -> ChangeReport:
    """Apply chosen fixes from plan_vehicle_repairs to a draft; previews by default, with
    overlays and a before/after preflight. commit=true applies the batch as one undo step;
    rerun preflight_vehicle afterwards. Stale revisions or plans and conflicting repairs are
    rejected. Manual findings need a design choice and are never applied here."""
    record = _read_design(design)
    if _revision(record) != revision:
        raise ValueError("stale revision; plan_vehicle_repairs again")
    proposed, png, report = await run_job("repair_vehicle", record, plan_id, finding_ids, design)
    if commit:
        proposed = _commit_record(design, proposed, revision)
    report.update(committed=commit, revision=_revision(proposed))
    report["after"]["revision"] = report["revision"]
    return _image_report(png, report)


@mcp.tool(annotations=READ)
@_user_errors
def list_vehicle_assemblies() -> dict[str, Any]:
    """List the reusable control assemblies (engine start and idle, clutch engagement,
    brake/reverse, lighting) with the part ids each must be bound to and the logic gates it
    expects. Place any required gates with edit_parts, then bind the queried ids with
    apply_vehicle_assembly. Geometry is not preset-specific. Read-only."""
    from swhull.assemblies import CATALOGUE  # noqa: PLC0415
    return {"assemblies": CATALOGUE, "workflow": "query -> place gates if needed -> bind -> preview -> commit -> preflight -> game test"}


@mcp.tool(annotations=EDIT)
@_user_errors
async def apply_vehicle_assembly(design: Draft,
                                 assembly: Annotated[Literal["engine_start_idle", "clutch_engagement",
                                                             "brake_reverse", "lighting"], Field(description=(
                                     "Assembly to wire; list_vehicle_assemblies explains each."))],
                                 bindings: Annotated[AssemblyBindings, Field(description=(
                                     "Current part ids from query_connections: driver seat, and the engine, "
                                     "gates, clutch, gearbox, wheels, lights or battery the assembly needs."))],
                                 revision: Revision,
                                 options: Annotated[AssemblyOptions | None, Field(description=(
                                     "Idle throttle, clutch deadband and hotkeys; defaults suit most builds."))] = None,
                                 commit: Commit = False, preview: Preview = False,
                                 detail: Detail = False) -> AssemblyReport:
    """Configure and wire a reusable control set-up (starter and idle, clutch, brake/reverse or
    lights) using explicit current part ids, instead of wiring each link with edit_connections.
    Existing drivers of the target inputs are replaced atomically. Clutch needs its own gate,
    separate from the idle throttle gate. Starter is manual/hold; idle is open-loop, and reverse
    must be selected while stopped. engine_start_idle takes one engine id or a list (twins share
    the throttle gate and starter). Returns the operations and a compact preflight
    (detail=true for all of it, preview=true for the diagnostic image); commit=true creates one
    undo step. Tune behaviour in game."""
    record = _read_design(design)
    if _revision(record) != revision:
        raise ValueError("stale revision; query_connections again")
    proposed, png, report = await run_job("assemble_vehicle", record, assembly, plain(bindings, AssemblyBindings),
                                        plain(options, AssemblyOptions) if options is not None else None, design,
                                        preview, detail)
    if commit:
        proposed = _commit_record(design, proposed, revision)
    report.update(committed=commit, revision=_revision(proposed), base_revision=revision)
    report["preflight"]["revision"] = report["revision"]
    if png is None:
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(report))], structured_content=report)
    return _image_report(png, report)


@mcp.tool(annotations=READ)
@_user_errors
async def preview_vehicle_diagnostics(design: Draft, yaw: Yaw = 35, pitch: Pitch = 25,
                                      layer: Annotated[Literal["all", "components", "structure"], Field(description=(
                                          '"components" (default) hides bodywork; "all" or "structure".'))]
                                      = "components") -> DiagnosticReport:
    """Render a draft with its preflight faults drawn over it: red faulty parts, amber blocked
    exits, blue wheel and steering arrows. Returns the image and the preflight report. Use it to
    see where preflight_vehicle's findings are; open_in_viewer(design=..., diagnostics=true)
    gives the player an interactive version. Coordinates are draft blocks. Read-only."""
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


@mcp.tool(annotations=EDIT)
@_user_errors
async def prepare_vehicle_validation(name: NewVehicleName, design: Draft,
                                     overwrite: Overwrite = False) -> ValidationRun:
    """Export a draft as a separate test vehicle in the game folder and open a validation run:
    a seven-check in-game checklist tied to the file's exact SHA-256 and the draft revision.
    Use it when a draft is ready for the player to test; record their results with
    record_vehicle_validation and review them with get_vehicle_validation. Refuses vehicles this
    tool did not write and replaces its own only with overwrite=true. Checks start pending;
    connected geometry never counts as game evidence."""
    record = _read_design(design)
    target, stamp = _save_target(name, record, overwrite)
    xml, report = await run_job("prepare_validation", record, design, name, str(target))
    thumbnail = await _thumbnail(xml)
    with DESIGN_LOCK:
        if _revision(_read_design(design)) != _revision(record):
            raise ValueError("draft changed while exporting; prepare validation again")
        path = _validation_path(report["run_id"])
        if path.exists():
            raise ValueError("validation run already exists; get_vehicle_validation to review it")
        _write_vehicle(target, xml, stamp, thumbnail)
        _atomic_design(name, {**record, "vehicle": True})
        _write_validation(report)
    return report


@mcp.tool(annotations=READ)
@_user_errors
def get_vehicle_validation(run_id: Annotated[str, Field(description=(
        "24-character run id returned by prepare_vehicle_validation."))]) -> dict[str, Any]:
    """Read a validation run: the checklist with any recorded results and evidence, plus
    export_matches and draft_matches, which say whether the exported file and the draft are
    still the ones tested. Read-only; fails when the run id is unknown."""
    from swhull.validation import sha  # noqa: PLC0415
    path = _validation_path(run_id)
    if not path.is_file():
        raise ValueError("validation run not found")
    report = json.loads(path.read_text(encoding="utf-8"))
    exported = Path(report["vehicle_path"])
    return {**report, "export_matches": exported.is_file() and sha(exported.read_bytes()) == report["export_sha256"],
            "draft_matches": _design_path(report["design"]).exists() and
            _revision(_read_design(report["design"])) == report["revision"]}


@mcp.tool(annotations=EDIT)
@_user_errors
def record_vehicle_validation(run_id: Annotated[str, Field(description=(
                                  "Run id from prepare_vehicle_validation."))],
                              export_sha256: Annotated[str, Field(description=(
                                  "export_sha256 from the run; must still match the file on disk."))],
                              observations: Annotated[list[Observation], Field(description=(
                                  "One entry per checklist check the player did: result pass, fail or "
                                  "skipped, with evidence and measurements."))],
                              game_version: Annotated[str, Field(description="Stormworks version tested on.")],
                              tester: Annotated[str, Field(description="Who did the test.")]) -> ValidationRun:
    """Record what the player observed in game for a validation run. Only human observations
    belong here, never preflight output. Each observation replaces any earlier result for the
    same check. Refuses a changed export, a mismatched hash or a different game version. The run
    passes only when all seven checks pass with evidence."""
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


@mcp.tool(annotations=READ)
@_user_errors
async def preview_vehicle(design: Draft,
                          yaw: Annotated[float | None, Field(description=(
                              "Camera heading in degrees (0 = side, 90 = front); default is a 3/4 view."))] = None,
                          pitch: Pitch = 25, zoom: Zoom = 1, focus: Focus = None, layer: Layer = "all",
                          door_state: Annotated[Literal["closed", "open"], Field(description=(
                              "Show manual doors closed or open."))] = "closed",
                          renderer: RendererChoice = None) -> list:
    """Render a draft (imported, land or edited hull) with installed component meshes and
    return the image plus notes. yaw/pitch/zoom/focus give a close-up; layer=components hides
    bodywork to inspect seats, tanks and powertrain. Hull specs use preview_hull and vehicles in
    the game folder use preview_game_vehicle. Paint and wheel poses are approximate; the image
    is not an in-game screenshot. Read-only."""
    if focus is not None and len(focus) != 3:
        raise ValueError("focus must contain three fractions")
    png, note = await run_job("preview_draft", _read_design(design), design, yaw, pitch, zoom, focus, layer,
                              door_state, renderer)
    return [Image(data=png, format="png"), note]


@mcp.tool(annotations=EDIT)
@_user_errors
async def save_vehicle(name: NewVehicleName, design: Draft, overwrite: Overwrite = False) -> str:
    """Write a stored draft into the Stormworks vehicles folder as <name>.xml with its Load-menu
    thumbnail. Use it for drafts edited part by part (imports, land vehicles, edited hulls);
    save_hull is the shortcut for a hull spec. Refuses a name used by a vehicle this tool did
    not write and the imported original, even with overwrite=true; replaces its own earlier
    save only with overwrite=true. Returns the file path, part count and notes."""
    record = _read_design(design)
    target, stamp = _save_target(name, record, overwrite)
    xml, count, note = await run_job("export_draft", record)
    thumbnail = await _thumbnail(xml)
    # Recheck after the worker to avoid an external file created while building.
    with DESIGN_LOCK:
        if _revision(_read_design(design)) != _revision(record):
            raise ValueError("draft changed while building; save the new revision")
        _write_vehicle(target, xml, stamp, thumbnail)
        _atomic_design(name, {**record, "vehicle": True})
    return f"Saved {count} parts to {target}\n{note}"


@mcp.tool(annotations=READ)
@_user_errors
async def check_seal(design: Draft,
                     seeds: Annotated[list[Any] | None, Field(description=(
                         "Interior start points in integer blocks: [[x,y,z],...] or [{name, position:[x,y,z]}]. "
                         "Required for imported drafts (original body frame); generated drafts choose their own."))]
                     = None,
                     door_state: DoorState = "closed") -> list:
    """Test whether a draft is watertight by tracing from interior points to the outside:
    sealed, leaking or indeterminate per compartment. Returns an image with any escape path
    highlighted and a report of connected compartments. Use it after edits that touch the hull
    or doors. Unsupported sealing geometry nearby prevents a confident pass. Read-only."""
    png, report = await run_job("seal_draft", _read_design(design), seeds, door_state, design)
    return [Image(data=png, format="png"), report]


@mcp.tool(annotations=READ)
@_user_errors
def list_game_vehicles(search: Annotated[str, Field(description=(
        "Case-insensitive text in the vehicle name; empty lists all."))] = "") -> list[str]:
    """List the vehicle names in the player's Stormworks vehicles folder, sorted. Pass a name to
    preview_game_vehicle, inspect_view, analyze_vehicle or import_vehicle. Drafts stored on this
    server are listed by list_designs. Read-only; fails when the folder is missing (set
    SW_VEHICLES_DIR)."""
    d = Path(vehicles_dir())
    if not d.is_dir():
        raise ValueError(f"vehicles folder not found: {d} (set SW_VEHICLES_DIR)")
    names = sorted(p.stem for p in d.iterdir() if p.suffix.lower() == ".xml")
    return [n for n in names if search.lower() in n.lower()]


@mcp.tool(annotations=READ)
@_user_errors
async def preview_game_vehicle(name: VehicleName, source: Source = "vehicles", body_id: BodyId = None,
                               renderer: RendererChoice = None) -> list:
    """Render a vehicle from the player's vehicles folder or an installed Workshop item and
    return the image plus a size and part summary, e.g. to study the player's existing boats.
    Uses installed component meshes, reporting any footprint fallbacks. Articulated vehicles show
    the largest body alone unless body_id is given. inspect_view points a camera at one detail;
    drafts use preview_vehicle. Read-only."""
    png, text = await run_job("game_vehicle", str(_reference_path(name, source)), name, body_id, renderer)
    return [Image(data=png, format="png"), text]


@mcp.tool(annotations=READ)
@_user_errors
async def inspect_view(name: Annotated[str | None, Field(description=(
                           "Saved vehicle to view; omit to build spec/preset/design instead."))] = None,
                       spec: Spec = None, preset: Preset = None,
                       yaw: Yaw = 35.0, pitch: Pitch = 25.0, zoom: Zoom = 1.0, focus: Focus = None,
                       design: Design = None, patch: Patch = None,
                       highlight: Annotated[str | None, Field(description=(
                           "Superstructure box name to paint magenta, label and report the position of "
                           "(designs only)."))] = None,
                       spec_path: SpecPath = None, source: Source = "vehicles", body_id: BodyId = None,
                       renderer: RendererChoice = None) -> list:
    """Render one large view of a hull design or saved vehicle from any angle, like a camera
    you can point, to check details the fixed previews hide. Returns the image and a caption;
    with highlight, the box's position in spec units and as game-metre heights above the keel.
    Views at pitch 0 or +-90 get metre rulers in spec units (z from the transom, y from the keel,
    x from the centreline). Use preview_hull for the standard set of views. Read-only."""
    if focus is not None and len(focus) != 3:
        raise ValueError("focus must be [fx, fy, fz]")
    zoom = max(0.2, min(zoom, 12.0))
    if name:
        if highlight:
            raise ValueError("highlight works on designs, not saved vehicles")
        png, note = await run_job("inspect_vehicle", str(_reference_path(name, source)), name, yaw, pitch,
                                  zoom, focus, body_id, renderer)
        title = name
    else:
        if source != "vehicles" or body_id is not None:
            raise ValueError("source/body_id apply only to a reference name")
        full = _spec(spec, preset, design, patch, spec_path)
        title = _title(preset, design)
        png, note = await run_job("inspect_design", full, title, yaw, pitch, zoom, focus, highlight, renderer)
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


@mcp.tool(annotations=VIEWER)
@_user_errors
async def open_in_viewer(name: Annotated[str | None, Field(description=(
                             "Saved vehicle, or numeric Workshop item with source=workshop."))] = None,
                         spec: Spec = None, preset: Preset = None,
                         design: Annotated[str | None, Field(description=(
                             "Stored hull, land or imported draft to show."))] = None,
                         patch: Patch = None, spec_path: SpecPath = None,
                         source: Source = "vehicles", body_id: BodyId = None,
                         diagnostics: Annotated[bool, Field(description=(
                             "Overlay preflight faults and steering arrows; needs design alone."))] = False) -> str:
    """Open a vehicle or design in the interactive 3D viewer in the player's web browser so
    they can orbit and inspect it themselves. You cannot see that window: use inspect_view or
    the preview tools to look yourself. Writes one temporary HTML page, replaced on each call,
    and changes nothing else. Uses installed component meshes with explicit fallbacks;
    articulated vehicles show the largest body alone unless body_id is given."""
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
