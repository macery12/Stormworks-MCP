"""Stormworks hull designer: MCP server for Claude Desktop.

Generates boat hulls from a parametric spec, renders previews for the model to review,
and writes vehicle XML straight into the Stormworks vehicles folder.
"""
import functools
import inspect
import json
import os
import re
import tempfile
import webbrowser
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from swhull.benches import describe as describe_benches
from swhull.build import deck_profile as _deck_profile, resolve_spec
from swhull.hull import merge
from swhull.jobs import run_job
from swhull.presets import PRESETS
from swhull.vehicle import vehicles_dir

HERE = Path(__file__).resolve().parent
GUIDE = (HERE / "swhull" / "guide.md").read_text(encoding="utf-8")
NAME_RE = re.compile(r"^[A-Za-z0-9 _\-()]{1,64}$")


def designs_dir():
    """Where saved design specs live (outside the repo, per user). SW_DESIGNS_DIR overrides."""
    if os.environ.get("SW_DESIGNS_DIR"):
        return Path(os.environ["SW_DESIGNS_DIR"])
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "stormworks-hull-mcp" / "designs"


INSTRUCTIONS = """\
Designs Stormworks boats (hull, superstructure, interior rooms) and saves them where the game
can load them. Read `hull_design_guide` once before designing. Loop: pick a preset or write a
spec -> `preview_hull` (and `preview_interior` for rooms) -> look at the image and critique it
against the player's brief -> adjust -> `save_hull`. For big designs, keep the spec on the
server with `store_design` and send only changes: every tool takes `design` (a stored name)
plus `patch` (JSON-Patch ops). The player loads the saved vehicle from a workbench's Load menu.
Before designing, ask the player which bench size they will build at (S, M, L, XL, XXL or MAX;
`list_workbenches` gives sizes) and set `bench` in the spec; the summary checks the fit.
Everything is plain blocks unless the player asks for wedge smoothing; engines are optional
placeholders, and the player adds propulsion and wiring. Heavy tools run in a worker process
that stops when a call is cancelled; very large designs with wedges take about a minute."""

mcp = MCPServer("stormworks-hulls", instructions=INSTRUCTIONS)


def _user_errors(fn):
    """Surface expected failures (bad spec, name clash, missing file) to the model verbatim."""
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def awrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except (ValueError, OSError) as exc:
                raise ToolError(str(exc)) from exc
        return awrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, OSError) as exc:
            raise ToolError(str(exc)) from exc
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
    base = _read_design(design)["spec"] if design else None
    if spec_path:
        base = merge(base or {}, _read_spec_file(spec_path))
    return resolve_spec(spec, preset, base=base, patch=patch)


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
def hull_design_guide() -> str:
    """Design guide: workflow, full spec reference, archetype proportions, style tips. Read first."""
    return GUIDE


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
    _check_name(name)
    full = _spec(spec, preset, design, patch, spec_path)
    target = Path(vehicles_dir()) / f"{name}.xml"
    design_path = _design_path(name)
    if target.exists():
        made_here = design_path.exists() and _read_design(name).get("vehicle", True)
        if not made_here:
            raise ValueError(f"'{name}' already exists in the vehicles folder and was not made by "
                             "this tool; choose another name")
        if not overwrite:
            raise ValueError(f"'{name}' exists; pass overwrite=true to replace it")
    xml, parts, text = await run_job("vehicle_xml", full)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(xml, encoding="utf-8")
    design_path.parent.mkdir(parents=True, exist_ok=True)
    design_path.write_text(json.dumps({"preset": preset, "vehicle": True, "spec": full}, indent=2),
                           encoding="utf-8")
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
    vehicle = path.is_file() and _read_design(name).get("vehicle", True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"preset": preset, "vehicle": vehicle, "spec": full}, indent=2),
                    encoding="utf-8")
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
    return _read_design(name)["spec"]


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
    mcp.run()
