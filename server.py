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
from typing import Any

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from swhull.benches import describe as describe_benches
from swhull._version import __version__
from swhull.build import deck_profile as _deck_profile, resolve_spec
from swhull.hull import merge
from swhull.editing import revision as _revision
from swhull import definitions
from swhull.jobs import run_job
from swhull.presets import PRESETS
from swhull.vehicle import vehicles_dir

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
wiring/plumbing and in-game verification are player work.
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
Use search_parts/get_part_definition for installed footprints/surfaces. Wiring, complete power
systems and external plumbing remain player work. Heavy tools use cancellable workers and a
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
    if record and record.get("kind") == "imported":
        raise ValueError("this is an imported draft; use preview_vehicle, query_parts, edit_parts and save_vehicle")
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


@mcp.tool()
@_user_errors
def hull_design_guide(topic: str = "full") -> str:
    """Read first. Topics: full, workflow, units, spec, interior, archetypes, style, limits,
    staged, building, testing. Focused topics avoid resending the entire spec reference."""
    if topic == "full":
        return GUIDE
    files = {"staged": "staged-builder.md", "building": "building.md", "testing": "in-game-testing.md"}
    if topic in files:
        return (HERE / "docs" / files[topic]).read_text(encoding="utf-8")
    headings = {"workflow": "Workflow", "units": "Units and axes", "spec": "Spec reference",
                "interior": "Interior design", "archetypes": "Archetype proportions (starting points)",
                "style": "Making it look good", "limits": "Limits"}
    if topic not in headings:
        raise ValueError("unknown guide topic; choose full, workflow, units, spec, interior, "
                         "archetypes, style, limits, staged, building or testing")
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
    """Names of designs stored by this tool (save_hull or store_design)."""
    d = designs_dir()
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


@mcp.tool()
@_user_errors
def load_design(name: str) -> dict[str, Any]:
    """Full spec of a stored design. To edit, prefer design=name plus a patch over resending it."""
    record = _read_design(name)
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
        raise ValueError(f"definition {definition!r} unavailable; set SW_DEFINITIONS_DIR")
    return result


@mcp.tool()
@_user_errors
def get_part_orientation(definition: str, targets: dict[str, list[int]] | None = None) -> dict[str, Any]:
    """Explain local mounting/motion/function axes and solve their requested world directions.
    Example Fin Rudder targets: mount_normal=[0,0,1], span_axis=[0,1,0]."""
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
def complaint(title: str, description: str, category: str = "other", severity: str = "medium",
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
async def analyze_vehicle(name: str, search: str = "", offset: int = 0, limit: int = 50,
                          section: str = "parts") -> dict[str, Any]:
    """Read saved-vehicle examples, body groups, link coverage and rudder mounting/motion issues.
    Supports multi-body references without editing them. Observations are not game verification.
    Search rudder/propeller/engine/trans to focus evidence. Sections: parts, links, controllers,
    bodies, placement_issues, connection_candidates, open_transmission_ports. All are paginated."""
    return await run_job("analyze_reference", str(_vehicle_path(name)), search, offset, limit, section)


@mcp.tool()
@_user_errors
async def import_vehicle(name: str, design: str) -> str:
    """Import an existing single-body version-3 vehicle into a new draft; never changes the source.
    Existing configured/wired parts are protected. Use query_parts/edit_parts and save_vehicle."""
    _check_name(design)
    if _design_path(design).exists():
        raise ValueError("draft already exists; choose a new design name")
    path = _vehicle_path(name)
    record, count = await run_job("import_draft", path.read_bytes().decode("utf-8"), name)
    with DESIGN_LOCK:
        if _design_path(design).exists():
            raise ValueError("draft already exists; choose a new design name")
        _atomic_design(design, record)
    return f"Imported {count} parts into '{design}'. Source '{name}' remains untouched."


@mcp.tool()
@_user_errors
async def query_parts(design: str, select: dict[str, Any] | None = None,
                      offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """Parts and revision for precise editing. select: ids, name, definition or inclusive bounds
    [[min_x,min_y,min_z],[max_x,max_y,max_z]]. Coordinates are integer blocks (0.25 m), in the
    uncentred build frame for generated hulls and original body-local frame for imports.
    Partial multi-voxel selections are rejected; select an id to target the whole component."""
    return await run_job("query_draft", _read_design(design), select, offset, limit)


@mcp.tool()
@_user_errors
async def edit_parts(design: str, operations: list[dict[str, Any]], revision: str,
                     commit: bool = False) -> list:
    """Atomic part edits; defaults to preview only. Pass the revision from query_parts.
    Ops: add(part/parts), fill(bounds,color), remove/replace/move/rotate/paint/copy/mirror/repeat.
    Selection ops need select={ids/bounds/name/definition}. move/copy/repeat use delta in blocks;
    repeat count is additional copies; rotate uses a local-to-world matrix or r string and pivot;
    mirror uses axis and plane. replace needs part; paint needs color. Added parts use definition,
    position in blocks, rotation, color, name and scalar settings. commit=true keeps one undo step."""
    record = _read_design(design)
    if _revision(record) != revision:
        raise ValueError("stale revision; query_parts again before editing")
    proposed, png, note = await run_job("edit_draft", record, operations, design)
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
        restored = {**{k: v for k, v in record.items() if k not in ("history", "edits")},
                    **history[-1], "history": history[:-1],
                    "generation": record.get("generation", 0) + 1, "vehicle": record.get("vehicle", False)}
        _atomic_design(design, restored)
        return {"revision": _revision(restored), "remaining_undo": len(history) - 1}


@mcp.tool()
@_user_errors
async def preview_vehicle(design: str, yaw: float | None = None, pitch: float = 25,
                          zoom: float = 1, focus: list[float] | None = None) -> list:
    """Preview a generated or imported draft; optional yaw/pitch/zoom/focus gives a close-up."""
    if focus is not None and len(focus) != 3:
        raise ValueError("focus must contain three fractions")
    png, note = await run_job("preview_draft", _read_design(design), design, yaw, pitch, zoom, focus)
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
async def preview_game_vehicle(name: str) -> list:
    """Render any vehicle from the player's vehicles folder, e.g. to study their existing boats.

    Parts are drawn at their true footprint when the game's part definitions are found, and
    as a single cube otherwise.
    """
    png, text = await run_job("game_vehicle", str(_vehicle_path(name)), name)
    return [Image(data=png, format="png"), text]


@mcp.tool()
@_user_errors
async def inspect_view(name: str | None = None, spec: dict[str, Any] | None = None,
                       preset: str | None = None, yaw: float = 35.0, pitch: float = 25.0,
                       zoom: float = 1.0, focus: list[float] | None = None, design: str | None = None,
                       patch: list[dict[str, Any]] | None = None, highlight: str | None = None,
                       spec_path: str | None = None) -> list:
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
        png, note = await run_job("inspect_vehicle", str(_vehicle_path(name)), name, yaw, pitch,
                                  zoom, focus)
        title = name
    else:
        full = _spec(spec, preset, design, patch, spec_path)
        title = _title(preset, design)
        png, note = await run_job("inspect_design", full, title, yaw, pitch, zoom, focus, highlight)
    return [Image(data=png, format="png"), f"{title}: yaw {yaw}, pitch {pitch}, zoom {zoom}{note}"]


def _viewer_page(xml, name):
    """Copy of viewer/index.html with a vehicle embedded, written to the temp folder."""
    page = (HERE / "viewer" / "index.html").read_text(encoding="utf-8")
    data = json.dumps({"xml": xml, "name": name}).replace("</", "<\\/")
    inject = f"<script>window.EMBEDDED_VEHICLE = {data};</script>\n"
    page = page.replace('<script type="importmap">', inject + '<script type="importmap">', 1)
    path = Path(tempfile.gettempdir()) / "stormworks-hull-mcp-view.html"
    path.write_text(page, encoding="utf-8")
    return path


@mcp.tool()
@_user_errors
async def open_in_viewer(name: str | None = None, spec: dict[str, Any] | None = None,
                         preset: str | None = None, design: str | None = None,
                         patch: list[dict[str, Any]] | None = None, spec_path: str | None = None) -> str:
    """Open a vehicle in the interactive 3D viewer in the player's web browser.

    name: a vehicle from the player's vehicles folder. Or pass spec/preset to view a hull
    design without saving it.
    """
    if name:
        xml = _vehicle_path(name).read_text(encoding="utf-8", errors="replace")
        title = name
    else:
        xml, _, _ = await run_job("vehicle_xml", _spec(spec, preset, design, patch, spec_path))
        title = design or preset or "design preview"
    page = _viewer_page(xml, title)
    webbrowser.open(page.as_uri())
    return f"Opened '{title}' in the 3D viewer ({page})."


if __name__ == "__main__":
    import multiprocessing  # noqa: PLC0415
    multiprocessing.freeze_support()
    mcp.run()
