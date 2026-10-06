"""Typed wiring, physical subsystem preflight and lossless connection overlays."""
import copy
import re
from collections import defaultdict, deque
from itertools import combinations

from . import definitions
from .configuration import engine_power, gearbox_ratios, settings_of
from .connections import adjacency, transmission_ports
from .editing import identify
from .land import _frame, road_wheel
from .orientation import wheel_directions
from .part_policy import GEARBOXES, PREBUILT_ENGINES
from .pieces import add, apply
from .routing import compatible

SIGNALS = frozenset((0, 1, 5, 6, 7))
TYPE_NAMES = {0: "on/off", 1: "number", 2: "mechanical power (physical pipe)",
              3: "fluid (physical pipe)", 4: "electric", 5: "composite", 6: "video", 7: "audio"}


def ports(p):
    data = definitions.metadata(p.piece.d) or {}
    nodes = data.get("logic_nodes", [])
    if p.raw_xml:
        from .reference import _ports, xml_root  # noqa: PLC0415
        root = xml_root('<vehicle data_version="3"><bodies><body unique_id="1"><components>'
                        + p.raw_xml + '</components></body></bodies></vehicle>')
        nodes = _ports(root.find("bodies/body/components/c"), data)
    return [{**n, "part_id": p.uid, "definition": p.piece.d,
             "position": add(p.origin, apply(p.Q, n["position"])),
             "connection_method": "pipe" if n["type"] in (2, 3) else "wire"} for n in nodes]


def endpoint(parts, value):
    if not isinstance(value, dict) or set(value) != {"part_id", "port"}:
        raise ValueError("wire endpoint needs part_id and port (the installed or configured node index)")
    found = [p for p in parts if p.uid == value["part_id"]]
    if len(found) != 1:
        raise ValueError("stale connection part ID; query_connections again or disconnect links before removing the part")
    nodes = [n for n in ports(found[0]) if str(n["index"]) == str(value["port"])]
    if len(nodes) != 1:
        raise ValueError("unknown port index; query_connections again")
    return nodes[0]


def _ref(n):
    return {"part_id": n["part_id"], "port": n["index"]}


def wire(parts, source, target, link_id):
    a, b = endpoint(parts, source), endpoint(parts, target)
    if a["type"] != b["type"]:
        raise ValueError(f"connection type mismatch: {a['label']} ({TYPE_NAMES.get(a['type'])}) / {b['label']} ({TYPE_NAMES.get(b['type'])})")
    typ = a["type"]
    if typ in (2, 3):
        raise ValueError("mechanical power and fluid require physical pipes; use route_connections with transmission surface indices")
    if typ not in (*SIGNALS, 4):
        raise ValueError(f"unsupported wire type {typ}")
    if source == target:
        raise ValueError("connection endpoints must differ")
    if typ in SIGNALS and (a["mode"] != 0 or b["mode"] != 1):
        raise ValueError("signal connections require an output (mode=0) to an input (mode=1)")
    return {"link_id": link_id, "type": typ, "from": _ref(a), "to": _ref(b)}


def _source_links(record, parts):
    xml = record.get("source_xml", "")
    if not xml:
        return []
    from .reference import _position, xml_root  # noqa: PLC0415
    by_position = defaultdict(list)
    for p in parts:
        for n in ports(p):
            by_position[(n["type"], n["position"])].append(n)
    result = []
    for i, link in enumerate(xml_root(xml).findall("logic_node_links/logic_node_link")):
        typ = int(link.get("type", "0"))
        candidates = [by_position[(typ, _position(link.find(f"voxel_pos_{e}")))] for e in (0, 1)]
        # Mode removes same-position output/input ambiguity for signal nodes.
        if typ in SIGNALS:
            candidates = [[n for n in nodes if n["mode"] == e] for e, nodes in enumerate(candidates)]
        row = {"link_id": f"source:{i}", "type": typ, "source_index": i,
               "status": "resolved" if all(len(n) == 1 for n in candidates) else "unresolved original"}
        if row["status"] == "resolved":
            row.update({"from": _ref(candidates[0][0]), "to": _ref(candidates[1][0])})
        result.append(row)
    return result


def template_wires(record, parts):
    if record.get("kind") != "land" or record["spec"].get("preset") not in ("utility_4x4", "humvee_4x4"):
        return []
    by_name = {p.name: p for p in parts}
    links = []

    def node(name, label, typ):
        p = by_name.get(name)
        if p is None:
            raise ValueError(f"connected template component {name!r} missing; disconnect template links before removing it")
        found = [n for n in ports(p) if n["type"] == typ and n["label"].startswith(label)]
        if len(found) != 1:
            raise ValueError(f"template port {name}/{label} is unavailable or ambiguous in this installation")
        return _ref(found[0])

    def connect(a, b, typ):
        links.append(wire(parts, node(*a, typ), node(*b, typ), f"template:{len(links)}"))

    connect(("driver", "Axis 2"), ("throttle limiter", "Input 1"), 1)
    connect(("throttle limiter", "f(x)"), ("diesel engine", "Throttle"), 1)
    connect(("throttle limiter", "f(x)"), ("clutch", "Clutch Pressure"), 1)
    connect(("driver", "Hotkey 1"), ("diesel engine", "Starter"), 0)
    connect(("driver", "Hotkey 3"), ("gearbox", "Gear Switch"), 0)
    connect(("driver", "Axis 1"), ("left steering inverter", "Input 1"), 1)
    for side in ("left", "right"):
        steering = ("driver", "Axis 1") if side == "right" else ("left steering inverter", "f(x)")
        connect(steering, (f"front {side} wheel", "Steering"), 1)
        for axle in ("front", "rear"):
            connect(("driver", "Trigger"), (f"{axle} {side} wheel", "Brake"), 0)
        connect(("driver", "Hotkey 2"), (f"{side} headlight", "Light Switch"), 0)
        connect(("driver", "Hotkey 2"), (f"{side} tail light", "Light Switch"), 0)
    for p in parts:
        for n in ports(p):
            if n["type"] == 4 and p.name != "starter battery":
                links.append(wire(parts, node("starter battery", "Electric Store", 4), _ref(n), f"template:{len(links)}"))
    return links


def wires(record, parts):
    identify(parts)
    base = copy.deepcopy(record["base_connections"]) if "base_connections" in record else template_wires(record, parts)
    result = [*_source_links(record, parts), *base]
    for i, op in enumerate(record.get("connection_edits", [])):
        if op.get("op") == "connect":
            if set(op) != {"op", "from", "to"}:
                raise ValueError("connect needs op, from and to only")
            result.append({"link_id": f"connection:{i}", "from": op["from"], "to": op["to"]})
        elif op.get("op") == "disconnect":
            if set(op) != {"op", "link_id"}:
                raise ValueError("disconnect needs op and link_id only")
            found = [r for r in result if r["link_id"] == op.get("link_id")]
            if len(found) != 1:
                raise ValueError("stale connection ID; query_connections again")
            result.remove(found[0])
        else:
            raise ValueError("connection operation must be connect or disconnect")
    result = [row if "source_index" in row else wire(parts, row["from"], row["to"], row["link_id"]) for row in result]
    inputs, seen = {}, set()
    for row in result:
        if "from" in row:
            a, b = ((row[k]["part_id"], str(row[k]["port"])) for k in ("from", "to"))
            key = (row["type"], *sorted((a, b))) if row["type"] == 4 else (row["type"], a, b)
            if key in seen and "source_index" not in row:
                raise ValueError("duplicate connection")
            seen.add(key)
        if row["type"] in SIGNALS and "to" in row:
            key = (row["to"]["part_id"], str(row["to"]["port"]))
            if key in inputs:
                raise ValueError(f"input already driven by {inputs[key]}; disconnect it before connecting another source")
            inputs[key] = row["link_id"]
    return result


def edited(record, operations, parts):
    if not isinstance(operations, list) or not operations or any(not isinstance(op, dict) for op in operations):
        raise ValueError("connection operations must be a nonempty list of objects")
    proposed = copy.deepcopy(record)
    proposed.pop("history", None)
    proposed.setdefault("connection_edits", []).extend(copy.deepcopy(operations))
    wires(proposed, parts)
    return proposed


def write_xml(xml, record, parts):
    links = wires(record, parts)
    if not record.get("connection_edits") and not any(r["link_id"].startswith("template:") for r in links):
        return xml
    match = re.search(r"<logic_node_links\b[^>]*(?:/>|>.*?</logic_node_links>)", xml, re.S)
    if match is None:
        raise ValueError("vehicle has no logic_node_links container")
    spans = list(re.finditer(r"<logic_node_link\b[^>]*(?:/>|>.*?</logic_node_link>)", match[0], re.S))
    original = {r["source_index"] for r in links if "source_index" in r}
    chunks = [s[0] for i, s in enumerate(spans) if i in original]
    for row in links:
        if "source_index" in row:
            continue
        nodes = [endpoint(parts, row[key]) for key in ("from", "to")]
        if row["type"] in SIGNALS:
            # XML has only type+voxel coordinates. Never write an unaddressable node.
            for e, n in enumerate(nodes):
                candidates = [c for p in parts for c in ports(p) if c["type"] == n["type"]
                              and c["mode"] == e and c["position"] == n["position"]]
                if len(candidates) != 1:
                    raise ValueError("ambiguous wire coordinates; move the overlapping ports before saving")
        typ = f' type="{row["type"]}"' if row["type"] else ""
        positions = ''.join(f'<voxel_pos_{e}' + ''.join(f' {a}="{v}"' for a, v in zip("xyz", n["position"]) if v) + '/>'
                            for e, n in enumerate(nodes))
        chunks.append(f'<logic_node_link{typ}>{positions}</logic_node_link>')
    return xml[:match.start()] + '<logic_node_links>' + ''.join(chunks) + '</logic_node_links>' + xml[match.end():]


def query(record, parts, offset=0, limit=100):
    from .land import _page  # noqa: PLC0415
    _page(offset, limit)
    rows = [{"part_id": p.uid, "name": p.name, "definition": p.piece.d,
             "ports": ports(p), "transmission_faces": transmission_ports(p)} for p in parts
            if ports(p) or transmission_ports(p)]
    links = wires(record, parts)
    from .routing import active_routes  # noqa: PLC0415
    return {"components": rows[offset:offset + limit], "total": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "links": links, "type_names": TYPE_NAMES,
            "routes": [{"route_id": key, **op, "part_count": sum(p.uid.startswith(key + ":") for p in parts)}
                       for key, op in active_routes(record).items()],
            "coordinates": "integer blocks in the draft build frame; connections use stable part IDs"}


def _key(port):
    return port["part_id"], port["surface_index"]


def physical_graph(parts):
    graph = defaultdict(set)
    faces = [f for p in parts for f in transmission_ports(p)]
    for pair in adjacency(parts, "draft")[0]:
        a, b = pair["ports"]
        if compatible(a, b):
            graph[_key(a)].add(_key(b))
            graph[_key(b)].add(_key(a))
    for p in parts:
        ports_by_type = defaultdict(list)
        for f in transmission_ports(p):
            ports_by_type[f["trans_type"]].append(f)
        d = p.piece.d
        if d.startswith(("trans_", "fluid_radiator", "fluid_tank_")) or d == "torque_clutch" or d in GEARBOXES:
            for group in ports_by_type.values():
                for a, b in combinations(group, 2):
                    graph[_key(a)].add(_key(b))
                    graph[_key(b)].add(_key(a))
    return graph, faces


def _reachable(graph, starts):
    visited, queue = set(starts), deque(starts)
    while queue:
        for n in graph[queue.popleft()]:
            if n not in visited:
                visited.add(n)
                queue.append(n)
    return visited


def wheel_control_checks(parts, links):
    """Trace only known sign-preserving/inverting controls; unknown logic stays unknown."""
    forward, source = _frame(parts, None)
    if source != "driver seat":
        return []
    by_id = {p.uid: p for p in parts}
    incoming = defaultdict(list)
    for link in links:
        if link.get("type") == 1 and "from" in link and "to" in link:
            incoming[(link["to"]["part_id"], str(link["to"]["port"]))].append(
                (link["from"]["part_id"], str(link["from"]["port"])))

    def signal(key, seen=frozenset()):
        if key in seen or len(seen) > 32:
            return None
        p = by_id.get(key[0])
        if p is None:
            return None
        nodes = ports(p)
        node = next((n for n in nodes if str(n["index"]) == key[1]), None)
        if node is None:
            return None
        if node["mode"] == 1:
            drivers = incoming.get(key, [])
            return signal(drivers[0], seen | {key}) if len(drivers) == 1 else None
        if p.piece.d.startswith("seat") and node["label"].startswith("Axis 1"):
            return 1
        sign = -1 if p.piece.d == "gate_float_invert" else None
        if p.piece.d == "gate_function_small":
            expr = str(settings_of(p).get("property_text", "")).replace(" ", "")
            sign = {"x": 1, "-x": -1}.get(expr)
        inputs = [n for n in nodes if n["type"] == 1 and n["mode"] == 1]
        if sign is not None and len(inputs) == 1:
            value = signal((p.uid, str(inputs[0]["index"])), seen | {key})
            return value * sign if value is not None else None
        return None

    rows = []
    for p in parts:
        if not road_wheel(p.piece.d) or "spare" in p.name.lower():
            continue
        row = wheel_directions(p, forward)
        if row is None:
            continue
        steering = [n for n in ports(p) if n["type"] == 1 and n["label"] == "Steering"]
        value = signal((p.uid, str(steering[0]["index"]))) if len(steering) == 1 else None
        row.update(name=p.name, frame_source=source, steering_signal_sign=value,
                   steering_status="unknown" if value is None or row["required_steering_sign"] is None else
                   "matches arrows" if value == row["required_steering_sign"] else "opposes arrows")
        rows.append(row)
    return rows


def preflight(record, parts):
    identify(parts)
    links, issues, checks = wires(record, parts), [], []
    graph, faces = physical_graph(parts)
    by_id = {p.uid: p for p in parts}
    if not any(p.piece.d in PREBUILT_ENGINES for p in parts):
        issues.append({"issue": "no prebuilt diesel engine; powertrain completion is not assessed"})
    configuration = [engine_power(p) for p in parts if p.piece.d in PREBUILT_ENGINES]
    issues.extend({**row, "issue": "engine power is missing, zero or invalid"}
                  for row in configuration if row["status"] == "invalid")
    gearbox_checks = [gearbox_ratios(p) for p in parts if p.piece.d in GEARBOXES]
    issues.extend({**row, "issue": "gearbox ratios are missing or invalid"}
                  for row in gearbox_checks if row["status"] == "invalid")
    issues.extend({**row, "issue": "gearbox off ratio reverses the shaft; review default drive direction"}
                  for row in gearbox_checks if row["off"]["direction"] == "reverse")
    wheel_checks = wheel_control_checks(parts, links)
    issues.extend({"part_id": row["part_id"], "issue": "wheel arrows need review", "detail": row}
                  for row in wheel_checks if row["forward_dot"] != 1 or row["up_dot"] != 1
                  or row["steering_status"] == "opposes arrows")

    def starts(p, label, typ):
        positions = {n["position"] for n in ports(p) if n["label"] == label and n["type"] == typ}
        return [_key(f) for f in transmission_ports(p) if f["position"] in positions]

    def check(p, system, ok, detail):
        checks.append({"part_id": p.uid, "system": system, "status": "connected" if ok else "missing", "detail": detail})

    directed, electric = defaultdict(set), defaultdict(set)
    for link in links:
        if "from" not in link:
            issues.append({"link_id": link["link_id"], "issue": "unresolved original link"})
            continue
        a, b = ((link[k]["part_id"], str(link[k]["port"])) for k in ("from", "to"))
        directed[a].add(b)
        if link["type"] == 4:
            electric[a].add(b)
            electric[b].add(a)
    powered = _reachable(electric, [(p.uid, str(n["index"])) for p in parts if p.piece.d.startswith("battery")
                                    for n in ports(p) if n["type"] == 4])
    targets = {b for values in directed.values() for b in values}
    for p in parts:
        for n in ports(p):
            key = (p.uid, str(n["index"]))
            if n["type"] == 4 and not p.piece.d.startswith("battery"):
                check(p, "electric", key in powered, n["label"])
            required = (p.piece.d in PREBUILT_ENGINES and n["label"] in ("Throttle", "Starter")
                        or p.piece.d == "torque_clutch" and n["label"] == "Clutch Pressure"
                        or p.piece.d in GEARBOXES and n["label"] == "Gear Switch"
                        or road_wheel(p.piece.d) and "spare" not in p.name.lower() and (n["label"] == "Brake"
                            or "front" in p.name.lower() and n["label"] == "Steering")
                        or p.piece.d.startswith(("searchlight", "small_light")) and n["label"] in ("On/Off", "Light Switch")
                        or p.piece.d.startswith("gate_function") and n["mode"] == 1)
            if required:
                check(p, "control", key in targets, n["label"])
        if p.piece.d in PREBUILT_ENGINES:
            for label, system, target_defs in (
                ("RPS", "drivetrain", {p.piece.d for p in parts if road_wheel(p.piece.d)}),
                ("Fuel", "fuel", {p.piece.d for p in parts if p.piece.d.startswith("fluid_tank_")}),
                ("Air", "air", {"air_filter"}), ("Exhaust", "exhaust", {"fluid_exhaust"}),
                ("In Coolant", "cooling return", {p.piece.d for p in parts if p.piece.d.startswith("fluid_radiator")}),
                ("Out Coolant", "cooling supply", {p.piece.d for p in parts if p.piece.d.startswith("fluid_radiator")})):
                reachable = _reachable(graph, starts(p, label, 2 if label == "RPS" else 3))
                reached = {by_id[k[0]].piece.d for k in reachable if k[0] != p.uid}
                check(p, system, bool(reached & target_defs), sorted(reached))
            rps = _reachable(graph, starts(p, "RPS", 2))
            for wheel in parts:
                if road_wheel(wheel.piece.d) and "spare" not in wheel.name.lower():
                    check(wheel, "drivetrain", bool(set(starts(wheel, "RPS", 2)) & rps), "engine path through clutch/gearbox is conditional")
            for label, family in (("clutch", {"torque_clutch"}), ("gearbox", GEARBOXES)):
                check(p, "drivetrain control parts", any(by_id[k[0]].piece.d in family for k in rps), label)
                cut = {k for k in graph if by_id[k[0]].piece.d in family}
                without = defaultdict(set, {k: neighbours - cut for k, neighbours in graph.items() if k not in cut})
                bypass = _reachable(without, starts(p, "RPS", 2))
                check(p, "drivetrain isolation", not any(road_wheel(by_id[k[0]].piece.d) for k in bypass), f"no path bypassing {label}")
            circuits = {label: set(starts(p, label, 3)) for label in ("Fuel", "Air", "Exhaust", "In Coolant", "Out Coolant")}
            for label, initial in circuits.items():
                connected = _reachable(graph, initial)
                wrong = [other for other, keys in circuits.items() if other != label and keys & connected
                         and {label, other} != {"In Coolant", "Out Coolant"}]
                check(p, "fluid circuit isolation", not wrong, {"port": label, "incorrectly_joined_to": wrong})
            fuel_reached = _reachable(graph, circuits["Fuel"])
            tanks = {k[0] for k in fuel_reached if by_id[k[0]].piece.d.startswith("fluid_tank_")}
            diesel = False
            for uid in tanks:
                tank = by_id[uid]
                settings = tank.settings
                if tank.raw_xml:
                    from .reference import xml_root  # noqa: PLC0415
                    root = xml_root('<vehicle data_version="3"><bodies><body unique_id="1"><components>'
                                    + tank.raw_xml + '</components></body></bodies></vehicle>')
                    settings = root.find("bodies/body/components/c/o").attrib
                diesel |= str(settings.get("fluid_type", "0")) == "1" and float(settings.get("fluid_fill", "1")) > 0
            check(p, "diesel supply", diesel, "connected premade tank must select diesel and have nonzero fill")
            inlet, outlet = circuits["In Coolant"], circuits["Out Coolant"]
            cooling = _reachable(graph, inlet)
            check(p, "cooling loop", bool(outlet & cooling), "engine return and supply must join through a radiator")
            radiators = {k for k in graph if by_id[k[0]].piece.d.startswith("fluid_radiator")}
            without = defaultdict(set, {k: neighbours - radiators for k, neighbours in graph.items() if k not in radiators})
            check(p, "cooling isolation", not bool(outlet & _reachable(without, inlet)), "no pipe bypass around the radiator")
    owner = {v: p for p in parts for v in p.voxels()}
    pairs, open_faces = adjacency(parts, "draft")
    capped_unused, non_driven = [], []
    for f in open_faces:
        v = add(f["position"], f["normal"])
        if v in owner:
            row = {"part_id": f["part_id"], "surface_index": f["surface_index"],
                   "issue": "blocked transmission face", "exit_cell": v,
                   "obstructing_part_id": owner[v].uid, "definition": owner[v].piece.d}
            p = by_id[f["part_id"]]
            if road_wheel(p.piece.d) and "spare" in p.name.lower():
                non_driven.append({**row, "role": "spare", "issue": "non-driven spare mounted against bodywork"})
                continue
            destination = capped_unused if p.piece.d.startswith("fluid_tank_") and any(
                graph[_key(port)] for port in transmission_ports(p) if _key(port) != _key(f)) else issues
            destination.append(row)
    missing = sum(c["status"] == "missing" for c in checks)
    report = {"status": "incomplete" if missing or issues else "connected geometry", "missing_count": missing,
            "checks": checks, "issues": issues, "wire_count": len(links),
            "physical_face_pairs": len(pairs), "open_transmission_faces": open_faces,
            "capped_unused_tank_faces": capped_unused,
            "non_driven_wheel_faces": non_driven,
            "configuration_checks": configuration,
            "gearbox_configuration_checks": gearbox_checks,
            "wheel_direction_checks": wheel_checks,
            "verification": "Topology, engine-power and saved gearbox-state checks only. Clutch state, overall drivetrain direction/ratio, fluid flow, starter timing, steering signs and engine operation require in-game checks."}
    from .repairs import findings  # noqa: PLC0415
    report["findings"] = findings(report, parts, links)
    return report
