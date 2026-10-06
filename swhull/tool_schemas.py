"""Request contracts shared by MCP schema generation and direct Python callers."""
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from typing_extensions import TypedDict

Block = Annotated[int, Field(strict=True)]
Vector = tuple[Block, Block, Block]
Bounds = tuple[Vector, Vector]
Rotation = str | tuple[Vector, Vector, Vector]
Scalar = str | int | float | bool
Hex = Annotated[str, Field(pattern=r"^[0-9A-Fa-f]{6}$")]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, allow_inf_nan=False)


class Selection(Request):
    ids: Annotated[list[str], Field(min_length=1, max_length=250000)] | None = None
    name: str | None = None
    definition: str | None = None
    bounds: Bounds | None = None


class Part(Request):
    definition: str = "01_block"
    position: Vector | None = None
    rotation: Rotation | None = None
    mirror: Annotated[int, Field(strict=True, ge=0, le=7)] = 0
    color: Hex = "C2C3C7"
    name: str = ""
    settings: dict[str, Scalar] = Field(default_factory=dict)


class Add(Request):
    op: Literal["add"]
    part: Part | None = None
    parts: Annotated[list[Part], Field(min_length=1, max_length=250000)] | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.part is None) == (self.parts is None):
            raise ValueError("add needs exactly one of part or parts")
        if any(p.position is None for p in self.parts or [self.part]):
            raise ValueError("added parts need position")
        return self


class Fill(Request):
    op: Literal["fill"]
    bounds: Bounds
    color: Hex = "C2C3C7"


class Selected(Request):
    select: Selection


class Remove(Selected):
    op: Literal["remove"]


class Replace(Selected):
    op: Literal["replace"]
    part: Part


class Translate(Selected):
    op: Literal["move", "copy"]
    delta: Vector


class Repeat(Selected):
    op: Literal["repeat"]
    delta: Vector
    count: Annotated[int, Field(strict=True, ge=1, le=1000)]


class Rotate(Selected):
    op: Literal["rotate"]
    rotation: Rotation
    pivot: Vector = (0, 0, 0)


class Paint(Selected):
    op: Literal["paint"]
    color: Hex


class Mirror(Selected):
    op: Literal["mirror"]
    axis: Literal["x", "y", "z"] = "x"
    plane: float = 0


class Configure(Selected):
    op: Literal["configure"]
    settings: dict[str, Scalar]


EditOperation = Annotated[Add | Fill | Remove | Replace | Translate | Repeat | Rotate | Paint | Mirror | Configure,
                          Field(discriminator="op")]
EditBatch = Annotated[list[EditOperation], Field(min_length=1, max_length=100)]


class WireEndpoint(Request):
    part_id: str
    port: Annotated[int, Field(strict=True, ge=0)]


class FaceEndpoint(Request):
    part_id: str
    surface_index: Annotated[int, Field(strict=True, ge=0)]


class Connect(Request):
    op: Literal["connect"]
    source: WireEndpoint = Field(alias="from")
    to: WireEndpoint


class Disconnect(Request):
    op: Literal["disconnect"]
    link_id: str


ConnectionOperation = Annotated[Connect | Disconnect, Field(discriminator="op")]
ConnectionBatch = Annotated[list[ConnectionOperation], Field(min_length=1, max_length=100)]


class Route(Request):
    op: Literal["route"] = "route"
    source: FaceEndpoint = Field(alias="from")
    to: FaceEndpoint
    bounds: Bounds | None = None
    waypoints: Annotated[list[Vector], Field(max_length=100)] | None = None
    name: str = "pipe route"
    pipe_style: Literal["auto", "exposed", "enclosed"] = "auto"
    through_blocks: Annotated[list[str], Field(max_length=100)] | None = None


class RemoveRoute(Request):
    op: Literal["remove"]
    route_id: str


RouteBatch = Annotated[list[Route | RemoveRoute], Field(min_length=1, max_length=100)]


def plain(value, contract):
    """Validate direct calls too; keep only explicitly supplied fields for legacy defaults."""
    return TypeAdapter(contract).dump_python(TypeAdapter(contract).validate_python(value),
                                             mode="json", by_alias=True, exclude_unset=True)


class Finding(TypedDict):
    finding_id: str
    code: str
    severity: Literal["error", "warning"]
    part_ids: list[str]
    explanation: str
    suggested_operations: dict[str, list[dict[str, Any]]]
    repair_status: Literal["available", "manual"]
    reason: str


class PreflightReport(TypedDict):
    status: str
    revision: str
    missing_count: int
    checks: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    findings: list[Finding]
    wire_count: int
    physical_face_pairs: int
    open_transmission_faces: list[dict[str, Any]]
    capped_unused_tank_faces: list[dict[str, Any]]
    non_driven_wheel_faces: list[dict[str, Any]]
    configuration_checks: list[dict[str, Any]]
    gearbox_configuration_checks: list[dict[str, Any]]
    wheel_direction_checks: list[dict[str, Any]]
    verification: str


class RepairPlan(TypedDict):
    revision: str
    plan_id: str
    findings: list[Finding]
    verification: str


class ChangeReport(TypedDict):
    committed: bool
    revision: str
    base_revision: str
    before: PreflightReport
    after: PreflightReport
    resolved_finding_ids: list[str]
    remaining_finding_ids: list[str]


class DiagnosticReport(TypedDict):
    revision: str
    preflight: PreflightReport
    overlay: dict[str, Any]


class AssemblyReport(TypedDict):
    assembly: str
    bindings: dict[str, Any]
    operations: dict[str, list[dict[str, Any]]]
    preflight: PreflightReport
    verification: str
    committed: bool
    revision: str
    base_revision: str


class AssemblyBindings(Request):
    driver: str
    engine: str | None = None
    throttle_gate: str | None = None
    clutch_gate: str | None = None
    clutch: str | None = None
    gearbox: str | None = None
    wheels: list[str] = Field(default_factory=list)
    lights: list[str] = Field(default_factory=list)
    battery: str | None = None


class AssemblyOptions(Request):
    idle_throttle: Annotated[float, Field(ge=0, le=0.5)] = 0.08
    clutch_deadband: Annotated[float, Field(ge=0, lt=1)] = 0.15
    starter_hotkey: Annotated[int, Field(strict=True, ge=1, le=6)] = 1
    lights_hotkey: Annotated[int, Field(strict=True, ge=1, le=6)] = 2
    reverse_hotkey: Annotated[int, Field(strict=True, ge=1, le=6)] = 3
