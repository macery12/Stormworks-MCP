"""Versioned human game-test evidence. Never infer operation from a topology pass."""
import hashlib
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import Field, field_validator
from typing_extensions import TypedDict

from .drafts import export
from .editing import revision
from .tool_schemas import Request

CHECKS = {
    "starting": "Hold starter, then release: engine keeps running; record RPS and start time.",
    "forward": "Reverse off: W moves forward from rest; record engine RPS and speed.",
    "steering": "At low forward speed, A turns left and D right; check both front wheels.",
    "reverse": "Stop, select reverse, then W moves backward; return to forward while stopped.",
    "braking": "Trigger brings the vehicle to a stop in forward and reverse; record stopping distance.",
    "cooling": "Drive under sustained load for at least five minutes; record duration and peak/stable temperature.",
    "suspension_clearance": "At full steering and suspension compression, tyres avoid bodywork; check steps/fenders on bumps.",
}


class Observation(Request):
    check: Literal["starting", "forward", "steering", "reverse", "braking", "cooling", "suspension_clearance"]
    result: Literal["pass", "fail", "skipped"]
    evidence: Annotated[str, Field(min_length=1, max_length=4000)]
    measurements: dict[str, float] = Field(default_factory=dict)

    @field_validator("evidence")
    @classmethod
    def substantive_evidence(cls, value):
        if not value.strip():
            raise ValueError("evidence must describe an observation")
        return value.strip()


class ValidationRun(TypedDict):
    run_id: str
    design: str
    revision: str
    export_sha256: str
    vehicle_name: str
    vehicle_path: str
    part_count: int
    created_at: str
    game_version: str
    tester: str
    checks: list[dict]
    status: str
    evidence_level: str


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(record, design, name, path):
    xml, count, _ = export(record)
    digest = sha(xml.encode("utf-8"))
    manifest = {"run_id": sha(f"{design}:{revision(record)}:{name}:{digest}".encode())[:24],
                "design": design, "revision": revision(record), "export_sha256": digest,
                "vehicle_name": name, "vehicle_path": str(path), "part_count": count,
                "created_at": datetime.now(timezone.utc).isoformat(), "game_version": "", "tester": "",
                "checks": [{"check": key, "instruction": instruction, "result": "pending", "evidence": "",
                            "measurements": {}} for key, instruction in CHECKS.items()],
                "status": "pending", "evidence_level": "untested_export"}
    return xml, manifest


def record_results(manifest, observations, game_version, tester):
    import copy  # noqa: PLC0415
    values = [Observation.model_validate(o).model_dump() for o in observations]
    if not values or len({v["check"] for v in values}) != len(values):
        raise ValueError("provide distinct checklist observations")
    game_version, tester = game_version.strip(), tester.strip()
    if not game_version or not tester:
        raise ValueError("game_version and tester are required for in-game evidence")
    out = copy.deepcopy(manifest)
    if out.get("game_version") and out["game_version"] != game_version:
        raise ValueError("game version changed; prepare a new validation copy/run")
    out.update(game_version=game_version, tester=tester, evidence_level="human_reported_in_game")
    for value in values:
        row = next(r for r in out["checks"] if r["check"] == value["check"])
        row.update(value, recorded_at=datetime.now(timezone.utc).isoformat(), tester=tester, game_version=game_version)
    results = {row["result"] for row in out["checks"]}
    out["status"] = "failed" if "fail" in results else "passed" if results == {"pass"} else "incomplete"
    return out
