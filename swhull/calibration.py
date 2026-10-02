"""Versioned, numbered orientation exhibits and observations bound to their source evidence."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import definitions
from .components import full_faces
from .orientation import RUDDERS, profile, rudder_clearance
from .pieces import BLOCK, BY_NAME, IDENTITY, MIRRORED, ROTATIONS, Placed, add, apply, r_attr, split_mirror, sub
from .vehicle import centre, to_xml

CHECKS = ("mounting", "orientation", "motion", "connections", "spawn")


def _definition_hash(d):
    if not isinstance(d, str) or not re.fullmatch(r"[\w.-]+", d):
        raise ValueError("definition must be a part id")
    base = definitions.definitions_dir()
    path = Path(base) / f"{d}.xml" if base else None
    if path is not None and path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(definitions.metadata(d), sort_keys=True).encode()).hexdigest()


def generate(d, mirrors=True):
    # Evidence hashes refer to files now, rather than cached metadata from before a game update.
    definitions.metadata.cache_clear()
    definitions.load.cache_clear()
    full_faces.cache_clear()
    piece = BY_NAME.get(d) or definitions.load(d)
    if piece is None:
        raise ValueError(f"definition {d!r} unavailable")
    fingerprint = _definition_hash(d)
    axes = profile(d)["axes"]
    placed, cases = [], []
    context_faces = sorted(full_faces(d, IDENTITY, attachment=True))
    # Select the intended rudder base or one geometric face.
    if d in RUDDERS:
        context_faces = [f for f in context_faces if f[1] == (0, -1, 0)]
    local_support = sorted({add(v, n) for v, n in context_faces if add(v, n) not in piece.footprint})
    if d not in RUDDERS:
        local_support = local_support[:1]
    for number, q in enumerate([*ROTATIONS, *(MIRRORED if mirrors else [])], 1):
        p = Placed(piece, (0, 0, 0), q, color="F0F0F0", name=f"case {number}")
        support = {apply(q, v) for v in local_support}
        bounds = set(p.voxels()) | support
        if d in RUDDERS:
            bounds |= rudder_clearance(p)
        lo = tuple(min(v[i] for v in bounds) for i in range(3))
        hi = tuple(max(v[i] for v in bounds) for i in range(3))
        cases.append({"number": number, "rotation": q, "lo": lo, "hi": hi, "support": support})
    spacing = [max(c["hi"][i] - c["lo"][i] + 1 for c in cases) + 7 for i in range(3)]
    legend = []
    for c in cases:
        number, q = c["number"], c["rotation"]
        anchor = ((number - 1) % 6 * spacing[0], 0, (number - 1) // 6 * spacing[2])
        origin = sub(anchor, c["lo"])
        placed.append(Placed(piece, origin, q, color="F0F0F0", name=f"case {number}"))
        placed.extend(Placed(BLOCK, add(origin, v), color="2DBE78") for v in sorted(c["support"]))
        # Binary marker gives each case an unambiguous number even without paint/text labels.
        placed.extend(Placed(BLOCK, add(anchor, (-3, bit, 0)), color="F2AA3B" if number >> bit & 1 else "222222")
                      for bit in range(6))
        rot, mirror = split_mirror(q)
        case_id = hashlib.sha256(f"{d}:{fingerprint}:{r_attr(rot)}:{mirror}:v1".encode()).hexdigest()[:20]
        legend.append({"case_id": case_id, "number": number, "definition": d, "origin": origin,
                       "r": r_attr(rot), "mirror": mirror, "definition_sha256": fingerprint,
                       "world_axes": {key: apply(q, value) for key, value in axes.items()},
                       "support_cells": [add(origin, v) for v in sorted(c["support"])],
                       "mount_model": ("intended rudder base" if d in RUDDERS else "one declared attachment face")
                       if local_support else "no modeled attachment face; orientation exhibit only",
                       "status": "pending_in_game", "checks": list(CHECKS)})
    before = placed[0].origin
    centre(placed)
    shift = sub(placed[0].origin, before)
    for case in legend:
        case["origin"] = add(case["origin"], shift)
        case["support_cells"] = [add(v, shift) for v in case["support_cells"]]
    occupied = {v for p in placed for v in p.voxels()}
    extent = [(max(v[i] for v in occupied) - min(v[i] for v in occupied) + 1) / 4 for i in range(3)]
    xml = to_xml(placed)
    return placed, xml, {"schema_version": 1, "definition": d, "definition_sha256": fingerprint,
                         "vehicle_sha256": hashlib.sha256(xml.encode()).hexdigest(), "cases": legend,
                         "extent_metres_xyz": extent,
                         "instructions": ["Rows contain six cases, increasing in body x then z; pillars identify numbers.",
                                          "Choose a workbench that contains extent_metres_xyz; exhibits are centred.",
                                          "Orange/black pillar encodes the case number in binary, least significant bit at bottom.",
                                          "White is the tested part; green blocks touch its intended/declared mount.",
                                          "Inspect base contact and axes in the editor before powered motion/spawn checks.",
                                          "Powered checks require suitable power/controls and connections added in game.",
                                          "Disconnected exhibits are for editor inspection; test one supported assembly when spawning.",
                                          "No case passes until the player records an observation."]}


def record_observation(manifest_path, case_id, check, result, note=""):
    if check not in CHECKS or result not in ("pass", "fail", "uncertain"):
        raise ValueError("check/result must be a documented calibration check and pass/fail/uncertain")
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case = next((c for c in manifest["cases"] if c["case_id"] == case_id), None)
    if case is None:
        raise ValueError("case_id not found in this manifest")
    current = _definition_hash(case["definition"])
    if current != case["definition_sha256"]:
        raise ValueError("installed definition changed; regenerate the calibration before recording evidence")
    vehicle_path = manifest_path.with_suffix(".xml")
    if not vehicle_path.is_file() or hashlib.sha256(vehicle_path.read_bytes()).hexdigest() != manifest["vehicle_sha256"]:
        raise ValueError("calibration XML changed or is missing; record evidence against the original exhibit")
    observation = {"case_id": case_id, "definition": case["definition"], "check": check, "result": result,
                   "note": note, "definition_sha256": current, "vehicle_sha256": manifest["vehicle_sha256"],
                   "observed_at": datetime.now(timezone.utc).isoformat(), "evidence_level": "user_reported_in_game"}
    path = manifest_path.with_suffix(".observations.jsonl")
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(observation) + "\n")
    return observation


def observations(d, directory):
    """Latest player evidence per case/check, retaining conflicting reports and stale hashes."""
    current = _definition_hash(d)
    path = Path(directory) / f"calibration-{d}.observations.jsonl"
    history = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []
    vehicle = Path(directory) / f"calibration-{d}.xml"
    vehicle_hash = hashlib.sha256(vehicle.read_bytes()).hexdigest() if vehicle.is_file() else None
    latest, results, stale = {}, {}, 0
    for row in history:
        if row.get("definition") != d or row.get("definition_sha256") != current or row.get("vehicle_sha256") != vehicle_hash:
            stale += 1
            continue
        key = (row["case_id"], row["check"])
        latest[key] = row
        results.setdefault(key, set()).add(row["result"])
    return {"definition": d, "evidence_level": "user_reported_in_game", "observation_count": len(history),
            "stale_observation_count": stale, "checks": [latest[key] for key in sorted(latest)],
            "conflicting_checks": [{"case_id": key[0], "check": key[1], "results": sorted(values)}
                                   for key, values in results.items() if len(values) > 1],
            "limitations": ["Player observations support reasoning; they do not alter model weights or prove untested configurations."]}
