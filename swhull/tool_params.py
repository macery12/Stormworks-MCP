"""Shared tool parameter descriptions and behaviour annotations.

Clients show the model these schema descriptions and MCP annotations next to each tool's
description, so a parameter documented here is documented the same way everywhere it is used.
"""
from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field


def _hints(read_only, destructive, idempotent):
    return ToolAnnotations(read_only_hint=read_only, destructive_hint=destructive,
                           idempotent_hint=idempotent, open_world_hint=False)


READ = _hints(True, False, True)          # reads and renders only
CREATE = _hints(False, False, False)      # adds new local records, never replaces any
REPLACE = _hints(False, True, True)       # replaces a same-name local record
EDIT = _hints(False, True, False)         # changes a draft (commit) or a game file (overwrite)
VIEWER = _hints(False, False, True)       # opens the player's browser on a temporary page


def _d(description, **constraints):
    return Field(description=description, **constraints)


Renderer = Literal["auto", "gpu", "cpu", "flat"]

Spec = Annotated[dict[str, Any] | None, _d(
    "Hull spec, partial or full (fields: get_guide topic=hull_spec); merged over preset or "
    "design. Lengths in metres.")]
Preset = Annotated[str | None, _d(
    "Built-in hull preset to start from, e.g. 'runabout'; names from list_hull_presets.")]
Design = Annotated[str | None, _d(
    "Stored design to start from instead of a preset; names from list_designs.")]
Patch = Annotated[list[dict[str, Any]] | None, _d(
    'JSON-Patch ops applied last, e.g. [{"op": "replace", "path": "/superstructure/bridge/height", '
    '"value": 2.5}]; list items can be named instead of indexed.')]
SpecPath = Annotated[str | None, _d(
    "Path to a .json file holding a spec or a stored design, read before spec and patch.")]
RendererChoice = Annotated[Renderer | None, _d(
    '"auto" (default) lights the scene like the game, on the GPU when available; "gpu"/"cpu" '
    'force one; "flat" is fastest and unlit, with block outlines for counting blocks.')]

Draft = Annotated[str, _d(
    "Stored draft name (from create_vehicle, import_vehicle, store_design or save_hull; "
    "see list_designs).")]
Revision = Annotated[str, _d(
    "The draft's current revision from query_parts or query_connections; a stale one is rejected.")]
EditRevision = Annotated[str | None, _d(
    "The draft's current revision from query_parts or query_connections. Required with "
    "commit=true; a preview may omit it. A stale one is rejected.")]
Commit = Annotated[bool, _d(
    "false (default) previews without changing the draft; true applies it as one undo step.")]
Offset = Annotated[int, _d("Rows to skip, for paging; use next_offset from the previous page.", ge=0)]
Preview = Annotated[bool, _d(
    "true also returns the rendered preview image and the full build notes; false (default) returns "
    "a compact list of what changed, warnings and the new revision.")]
Detail = Annotated[bool, _d(
    "true lists every check and each finding's repair operations; false (default) lists only "
    "faults, each once.")]

VehicleName = Annotated[str, _d(
    "Vehicle file name without .xml in the player's vehicles folder (see list_game_vehicles); "
    "with source=workshop, the numeric Steam Workshop item ID.")]
OptionalVehicleName = Annotated[str | None, _d(
    "Saved vehicle file name without .xml (see list_game_vehicles); with source=workshop, the "
    "numeric Workshop item ID. Give this or a design, not both.")]
Source = Annotated[str, _d(
    '"vehicles" (default) reads the player\'s vehicles folder; "workshop" reads an installed '
    "Workshop item by numeric ID.")]
BodyId = Annotated[str | None, _d(
    "unique_id of one body of a multi-body vehicle; default is the largest body. Saved "
    "vehicles only.")]
NewVehicleName = Annotated[str, _d(
    "Name for the file in the vehicles folder and the game's Load menu: letters, digits, "
    "spaces, _ - ( ), at most 64 characters.")]
Overwrite = Annotated[bool, _d(
    "Replace an earlier vehicle of this name written by this tool. Files this tool did not "
    "write are never replaced.")]

Yaw = Annotated[float, _d("Camera heading in degrees: 0 = side with bow right, 90 = bow, "
                          "180 = other side, 270 = stern.")]
Pitch = Annotated[float, _d("Camera degrees above (+) or below (-) the horizon; -30 shows the bottom.")]
Zoom = Annotated[float, _d("1 = whole vehicle, 2-6 = close-up.")]
Focus = Annotated[list[float] | None, _d(
    "[fx, fy, fz] fractions of the bounding box to centre on (x across, y up, z stern to bow), "
    "e.g. [0.5, 0.3, 0.9] = low on the bow.")]
Layer = Annotated[str, _d('"all", "components" (hides bodywork to show seats, tanks, '
                          'powertrain) or "structure".')]
DoorState = Annotated[str, _d('"closed" or "open": models supported doors in that state.')]


def Limit(maximum, what="Rows per page"):  # noqa: N802 - reads like a type at the call site
    return Annotated[int, _d(f"{what}, 1-{maximum}.", ge=1, le=maximum)]
