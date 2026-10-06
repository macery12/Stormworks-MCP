"""Conservative, reproducible repair suggestions and revision-bound transactions."""
import copy
import hashlib
import json

from .configuration import settings_of
from .connections import transmission_ports
from .drafts import edited, materialize
from .editing import revision
from .networks import _key, _reachable, _ref, physical_graph, ports, preflight, wires
from .pieces import add
from .tool_schemas import ConnectionBatch, EditBatch, RouteBatch, plain


def operations(edits=None, connections=None, routes=None):
    return {"edits": edits or [], "connections": connections or [], "routes": routes or []}


def apply_operations(record, batch):
    proposed = copy.deepcopy(record)
    proposed.pop("history", None)
    if batch["edits"]:
        proposed = edited(proposed, plain(batch["edits"], EditBatch))
    for key, contract, storage in (("connections", ConnectionBatch, "connection_edits"),
                                   ("routes", RouteBatch, "route_edits")):
        if batch[key]:
            proposed.setdefault(storage, []).extend(plain(batch[key], contract))
    parts, _ = materialize(proposed)
    wires(proposed, parts)
    # Check coordinate-addressability before offering a repair that cannot be saved.
    from .drafts import export  # noqa: PLC0415
    export(proposed)
    return proposed


def node(parts, uid, label, typ, mode=None):
    nodes = [n for p in parts if p.uid == uid for n in ports(p)
             if n["label"].startswith(label) and n["type"] == typ and (mode is None or n["mode"] == mode)]
    return nodes[0] if len(nodes) == 1 else None


def replace_driver(links, source, target):
    result = [{"op": "disconnect", "link_id": link["link_id"]} for link in links
              if link.get("to") == _ref(target)]
    return [*result, {"op": "connect", "from": _ref(source), "to": _ref(target)}]


def _drivers(parts, links):
    seats = [p for p in parts if p.piece.d.startswith("seat") and node(parts, p.uid, "Axis 1", 1, 0)]
    connected = {link["from"]["part_id"] for link in links if "from" in link and link["type"] in (0, 1)}
    used = [p for p in seats if p.uid in connected]
    return used or [p for p in seats if p.name.lower() == "driver"] or seats


def _control(parts, links, p, label):
    target = node(parts, p.uid, label, 0 if label in ("Starter", "Gear Switch", "Brake", "Light Switch", "On/Off") else 1, 1)
    if target is None:
        return operations()
    seats = _drivers(parts, links)
    if len(seats) != 1:
        return operations()
    mapping = {"Starter": ("Hotkey 1", 0), "Gear Switch": ("Hotkey 3", 0),
               "Brake": ("Trigger", 0), "Light Switch": ("Hotkey 2", 0), "On/Off": ("Hotkey 2", 0)}
    if label not in mapping:
        return operations()
    source = node(parts, seats[0].uid, *mapping[label], 0)
    return operations(connections=replace_driver(links, source, target)) if source else operations()


def _steering(parts, links, row):
    target = node(parts, row["part_id"], "Steering", 1, 1)
    seats = _drivers(parts, links)
    if target is None or len(seats) != 1 or row["required_steering_sign"] is None:
        return operations()
    seat = node(parts, seats[0].uid, "Axis 1", 1, 0)
    if row["required_steering_sign"] == 1:
        return operations(connections=replace_driver(links, seat, target))
    candidates = []
    for p in parts:
        if p.piece.d == "gate_float_invert" or (p.piece.d == "gate_function_small"
                                                and str(settings_of(p).get("property_text", "")).replace(" ", "") == "-x"):
            inputs = [n for n in ports(p) if n["type"] == 1 and n["mode"] == 1]
            outputs = [n for n in ports(p) if n["type"] == 1 and n["mode"] == 0]
            if len(inputs) == len(outputs) == 1 and any(link.get("from") == _ref(seat)
                                                      and link.get("to") == _ref(inputs[0]) for link in links):
                candidates.append(outputs[0])
    return operations(connections=replace_driver(links, candidates[0], target)) if len(candidates) == 1 else operations()


def _physical(parts, report, p, system):
    """Join open boundaries of the two intended circuits; never select a foreign circuit."""
    labels = {"fuel": ("Fuel", "fluid_tank_", "Stored Fluid"),
              "air": ("Air", "air_filter", "Fluid"), "exhaust": ("Exhaust", "fluid_exhaust", "Fluid")}
    if system not in labels:
        return operations()
    label, family, destination = labels[system]
    targets = [q for q in parts if q.piece.d.startswith(family)]
    if len(targets) != 1:
        return operations()
    graph, _ = physical_graph(parts)

    def circuit(component, port_label):
        positions = {n["position"] for n in ports(component) if n["label"] == port_label and n["type"] == 3}
        return _reachable(graph, [_key(f) for f in transmission_ports(component) if f["position"] in positions])

    a, b = circuit(p, label), circuit(targets[0], destination)
    occupied = {v for q in parts for v in q.voxels()}
    opened = report["open_transmission_faces"]
    left = [f for f in opened if _key(f) in a and add(f["position"], f["normal"]) not in occupied]
    right = [f for f in opened if _key(f) in b and add(f["position"], f["normal"]) not in occupied]
    pairs = sorted(((f, g) for f in left for g in right),
                   key=lambda pair: (sum(abs(pair[0]["position"][i] - pair[1]["position"][i]) for i in range(3)),
                                     _key(pair[0]), _key(pair[1])))
    if not pairs:
        return operations()
    f, g = pairs[0]
    return operations(routes=[{"op": "route", "from": {"part_id": f["part_id"], "surface_index": f["surface_index"]},
                               "to": {"part_id": g["part_id"], "surface_index": g["surface_index"]},
                               "name": f"repair {system}", "pipe_style": "auto"}])


def findings(report, parts, links):
    by_id = {p.uid: p for p in parts}
    rows = []

    def finding(code, ids, explanation, batch=None, severity="error", reason="Inspect the geometry and choose the intended parts/ports.", identity_detail=None):
        batch = batch or operations()
        available = any(batch.values())
        identity = json.dumps([code, ids, identity_detail], sort_keys=True)
        rows.append({"finding_id": hashlib.sha256(identity.encode()).hexdigest()[:16], "code": code,
                     "severity": severity, "part_ids": ids, "explanation": explanation,
                     "suggested_operations": batch, "repair_status": "available" if available else "manual",
                     "reason": "Preview this suggestion and inspect the resulting preflight." if available else reason})

    for check in report["checks"]:
        if check["status"] != "missing":
            continue
        p, system, detail = by_id[check["part_id"]], check["system"], check["detail"]
        batch = _control(parts, links, p, detail) if system == "control" else _physical(parts, report, p, system)
        if system == "electric":
            batteries = [q for q in parts if q.piece.d.startswith("battery")]
            if len(batteries) == 1:
                source = [n for n in ports(batteries[0]) if n["type"] == 4]
                target = [n for n in ports(p) if n["type"] == 4 and n["label"] == detail]
                if len(source) == len(target) == 1:
                    batch = operations(connections=[{"op": "connect", "from": _ref(source[0]), "to": _ref(target[0])}])
        identity_detail = detail if system in ("control", "electric", "drivetrain control parts", "drivetrain isolation", "fluid circuit isolation") else None
        finding(f"missing_{system.replace(' ', '_')}", [p.uid], f"{p.name or p.uid}: missing {system}: {detail}", batch,
                identity_detail=identity_detail)
    for row in report["issues"]:
        uid = row.get("part_id")
        batch = operations()
        message = row["issue"]
        if message == "engine power is missing, zero or invalid":
            batch = operations(edits=[{"op": "configure", "select": {"ids": [uid]}, "settings": {"max_force_scale": 1}}])
        if message == "wheel arrows need review" and row["detail"]["steering_status"] == "opposes arrows":
            batch = _steering(parts, links, row["detail"])
        ids = [value for value in (uid, row.get("obstructing_part_id")) if value]
        finding(message.replace(" ", "_"), ids, message, batch,
                "warning" if message.startswith(("no prebuilt", "gearbox off")) else "error",
                identity_detail={key: row[key] for key in ("link_id", "surface_index") if key in row})
    return rows


def plan(record):
    parts, _ = materialize(record)
    report = preflight(record, parts)
    rows = copy.deepcopy(report["findings"])
    for row in rows:
        if row["repair_status"] == "available":
            try:
                proposed = apply_operations(record, row["suggested_operations"])
                candidate, _ = materialize(proposed)
                after = preflight(proposed, candidate)
                old = {f["finding_id"] for f in report["findings"]}
                new = {f["finding_id"] for f in after["findings"]}
                if row["finding_id"] in new or new - old:
                    raise ValueError("suggestion leaves this fault or introduces another finding")
            except ValueError as exc:
                row.update(repair_status="manual", reason=str(exc), suggested_operations=operations())
    result = {"revision": revision(record), "findings": rows, "verification": report["verification"]}
    result["plan_id"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:20]
    return result


def repair(record, plan_id, finding_ids):
    current = plan(record)
    if current["plan_id"] != plan_id:
        raise ValueError("stale repair plan; plan_vehicle_repairs again")
    if not finding_ids or len(finding_ids) != len(set(finding_ids)):
        raise ValueError("select distinct available finding IDs")
    selected = [f for f in current["findings"] if f["finding_id"] in finding_ids]
    if len(selected) != len(finding_ids) or any(f["repair_status"] != "available" for f in selected):
        raise ValueError("unknown or manual finding; choose available repairs from this plan")
    batch = operations()
    for f in selected:
        for key in batch:
            for op in f["suggested_operations"][key]:
                if op not in batch[key]:
                    batch[key].append(op)
    proposed = apply_operations(record, batch)
    before_parts, _ = materialize(record)
    after_parts, _ = materialize(proposed)
    before, after = preflight(record, before_parts), preflight(proposed, after_parts)
    old, new = ({f["finding_id"] for f in r["findings"]} for r in (before, after))
    if set(finding_ids) & new or new - old:
        raise ValueError("combined repairs conflict; preview individual repairs")
    return proposed, {"committed": False, "base_revision": revision(record), "revision": revision(proposed),
                      "before": {**before, "revision": revision(record)},
                      "after": {**after, "revision": revision(proposed)},
                      "resolved_finding_ids": sorted(old - new), "remaining_finding_ids": sorted(new)}
