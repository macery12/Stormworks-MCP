"""Reusable controls bound to queried part IDs, independent of vehicle presets."""
from .repairs import apply_operations, node, operations, replace_driver
from .drafts import materialize
from .networks import _ref, ports, preflight, wires
from .part_policy import CURRENT_GEARBOXES, PREBUILT_ENGINES
from .tool_schemas import AssemblyBindings, AssemblyOptions, plain

CATALOGUE = {
    "engine_start_idle": {"roles": ["driver", "engine", "throttle_gate"],
                          "description": "Hold the starter hotkey; W sets throttle above a configurable idle floor. engine may be a list: twins share the gate and starter.",
                          "definitions": {"throttle_gate": "gate_function_small"}},
    "clutch_engagement": {"roles": ["driver", "clutch", "clutch_gate"],
                          "description": "Disengage at rest; progressively engage as positive W input exceeds the deadband.",
                          "definitions": {"clutch_gate": "gate_function_small"}},
    "brake_reverse": {"roles": ["driver", "gearbox", "wheels"],
                      "description": "Trigger brakes every selected wheel; reverse hotkey selects the saved reverse ratio. Shift while stopped.",
                      "definitions": {}},
    "lighting": {"roles": ["driver", "lights", "battery"],
                 "description": "Light hotkey drives selected lamps and connects them to the selected battery.",
                 "definitions": {}},
}


def assemble(record, assembly, bindings, options=None):
    if assembly not in CATALOGUE:
        raise ValueError("unknown assembly")
    roles = plain(bindings, AssemblyBindings)
    opts = AssemblyOptions.model_validate(options or {}).model_dump()
    parts, _ = materialize(record)
    links = wires(record, parts)
    by_id = {p.uid: p for p in parts}
    for role in CATALOGUE[assembly]["roles"]:
        if not roles.get(role):
            raise ValueError(f"assembly {assembly} requires {role}")
    used = [uid for role in CATALOGUE[assembly]["roles"] for uid in
            (roles[role] if isinstance(roles[role], list) else [roles[role]])]
    unknown = sorted({uid for uid in used if uid not in by_id})
    if unknown:
        raise ValueError(f"no part with id {', '.join(unknown)} in this draft; query_connections lists current ids")
    repeated = sorted({uid for uid in used if used.count(uid) > 1})
    if repeated:
        raise ValueError(f"each role needs its own part, but {', '.join(repeated)} is bound to more than one role")
    engines = roles["engine"] if isinstance(roles.get("engine"), list) else [roles["engine"]] if roles.get("engine") else []
    if not by_id[roles["driver"]].piece.d.startswith("seat"):
        raise ValueError("driver must be a control seat")
    if assembly == "engine_start_idle" and any(by_id[uid].piece.d not in PREBUILT_ENGINES for uid in engines):
        raise ValueError("every engine must be a prebuilt diesel (small, medium or large)")
    if assembly == "clutch_engagement" and by_id[roles["clutch"]].piece.d != "torque_clutch":
        raise ValueError("clutch must be torque_clutch")
    for role, definition in CATALOGUE[assembly]["definitions"].items():
        if by_id[roles[role]].piece.d != definition:
            raise ValueError(f"{role} must be {definition}; add it with edit_parts first")
    batch = operations()

    def port(role, label, typ, mode, uid=None):
        result = node(parts, uid or roles[role], label, typ, mode)
        if result is None:
            raise ValueError(f"{role} needs an unambiguous {label} port of type {typ}")
        return result

    def connect(source, target):
        if any(link.get("from") == _ref(source) and link.get("to") == _ref(target) for link in links):
            return
        batch["connections"].extend(replace_driver(links, source, target))

    def gate(role, expression):
        output = port(role, "f(x)", 1, 0)
        target_role = "engine" if role == "throttle_gate" else "clutch"
        consumers = [link["to"]["part_id"] for link in links if link.get("from") == _ref(output) and "to" in link]
        allowed = engines if target_role == "engine" else [roles[target_role]]
        if any(uid not in allowed for uid in consumers):
            raise ValueError(f"{role} also drives another subsystem; bind a separate gate before changing its expression")
        batch["edits"].append({"op": "configure", "select": {"ids": [roles[role]]},
                               "settings": {"property_text": expression}})
        connect(port("driver", "Axis 2", 1, 0), port(role, "Input 1", 1, 1))
        return output

    if assembly == "engine_start_idle":
        value = opts["idle_throttle"]
        # Twins share one throttle gate and starter hotkey.
        throttle = gate("throttle_gate", f"max({value:g},min(1,x))")
        starter = port("driver", f"Hotkey {opts['starter_hotkey']}", 0, 0)
        for uid in engines:
            connect(throttle, port("engine", "Throttle", 1, 1, uid))
            connect(starter, port("engine", "Starter", 0, 1, uid))
    elif assembly == "clutch_engagement":
        d = opts["clutch_deadband"]
        connect(gate("clutch_gate", f"max(0,min(1,(x-{d:g})/{1-d:g}))"), port("clutch", "Clutch Pressure", 1, 1))
    elif assembly == "brake_reverse":
        if by_id[roles["gearbox"]].piece.d not in CURRENT_GEARBOXES:
            raise ValueError("brake_reverse requires a current standalone gearbox")
        batch["edits"].append({"op": "configure", "select": {"ids": [roles["gearbox"]]},
                               "settings": {"gear_ratio_1": 1, "gear_ratio_2": 0}})
        connect(port("driver", f"Hotkey {opts['reverse_hotkey']}", 0, 0), port("gearbox", "Gear Switch", 0, 1))
        for uid in roles["wheels"]:
            if not by_id[uid].piece.d.startswith("wheel_"):
                raise ValueError("wheels must reference road wheels")
            connect(port("driver", "Trigger", 0, 0), port("wheels", "Brake", 0, 1, uid))
    else:
        if not by_id[roles["battery"]].piece.d.startswith("battery"):
            raise ValueError("battery must reference a battery")
        electric = [n for n in ports(by_id[roles["battery"]]) if n["type"] == 4]
        if len(electric) != 1:
            raise ValueError("battery electric port is ambiguous")
        for uid in roles["lights"]:
            switches = [n for n in ports(by_id[uid]) if n["type"] == 0 and n["mode"] == 1
                        and n["label"] in ("Light Switch", "On/Off")]
            if len(switches) != 1 or not by_id[uid].piece.d.startswith(("searchlight", "small_light")):
                raise ValueError("lights need supported lamp switch inputs")
            connect(port("driver", f"Hotkey {opts['lights_hotkey']}", 0, 0), switches[0])
            for target in [n for n in ports(by_id[uid]) if n["type"] == 4]:
                if not any(link["type"] == 4 and {_ref(electric[0])["part_id"], uid} ==
                           {link.get("from", {}).get("part_id"), link.get("to", {}).get("part_id")} for link in links):
                    batch["connections"].append({"op": "connect", "from": _ref(electric[0]), "to": _ref(target)})
    proposed = apply_operations(record, batch)
    current, _ = materialize(proposed)
    return proposed, {"assembly": assembly, "bindings": roles, "operations": batch,
                      "preflight": preflight(proposed, current),
                      "verification": "Manual starter, open-loop idle throttle and clutch mapping; tune in game. Reverse has no speed interlock."}
