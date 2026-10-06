"""Game-sized component placement, actual mounting checks and optional staged fit-out."""
import copy
from collections import ChainMap
from functools import lru_cache
from itertools import product

from . import definitions
from .configuration import new_settings
from .editing import color, rotation, vector
from .land import control_seat
from .orientation import RUDDERS, profile, rudder_clearance, solve
from .pieces import (BY_NAME, DIRS, IDENTITY, Placed, add, apply, find_rotation, neg, sub)
from .smooth import _full_faces
from .vehicle import component_xml

BATTERIES = {"small": "battery_small", "medium": "battery_medium", "large": "battery_large"}
PROPELLERS = {"small": "propeller", "large": "large_propeller", "giant": "giga_prop_small"}
STAGES = ("structure", "core", "access", "propulsion", "tanks")


@lru_cache(maxsize=1024)
def full_faces(d, q, attachment=False):
    if d in BY_NAME:
        if d == "01_block":
            return frozenset((apply(q, v), apply(q, direction)) for v in BY_NAME[d].footprint
                             for direction in DIRS)
        return frozenset(_full_faces(BY_NAME[d], q))
    data = definitions.metadata(d)
    if data is None:
        return frozenset()
    surfaces = data["attachment_surfaces" if attachment else "sealing_surfaces"]
    return frozenset((apply(q, s["position"]), apply(q, DIRS[s["orientation"]]))
                     for s in surfaces if (s["shape"] == 1 or attachment and s["shape"] == 0
                                            or attachment and s["shape"] == 3
                                            and s["trans_type"] > 0) and 0 <= s["orientation"] < 6)


def owners(parts):
    return {v: p for p in parts for v in p.voxels()}


def mounting_contacts(p, owner, local_normal=None):
    contacts = []
    for cell, direction in full_faces(p.piece.d, p.Q, attachment=True):
        if local_normal is not None and direction != apply(p.Q, local_normal):
            continue
        neighbour = add(add(p.origin, cell), direction)
        other = owner.get(neighbour)
        if other and other is not p and (sub(neighbour, other.origin), neg(direction)) in full_faces(
                other.piece.d, other.Q, attachment=True):
            contacts.append({"position": add(p.origin, cell), "normal": direction,
                             "support_position": neighbour, "support_definition": other.piece.d,
                             "support_id": other.uid})
    return sorted(contacts, key=lambda c: (c["position"], c["normal"]))


def mounted(p, owner):
    normal = (0, -1, 0) if p.piece.d in RUDDERS else None
    return bool(mounting_contacts(p, owner, normal))


def _supported(cells, owner):
    return all(v in owner and (sub(v, owner[v].origin), (0, 1, 0))
               in full_faces(owner[v].piece.d, owner[v].Q) for v in cells)


def _obstructions(cells, owner, reserved=frozenset()):
    return [{"position": v, "part_id": owner[v].uid if v in owner else None,
             "definition": owner[v].piece.d if v in owner else "reserved access"}
            for v in sorted(cells) if v in owner or v in reserved][:12]


def _access_owner(owner):
    # Access is checked with manual doors open; their frames remain obstacles.
    from .seal import MANUAL_DOORS  # noqa: PLC0415
    return {v: p for v, p in owner.items() if p.piece.d not in MANUAL_DOORS or
            not any(n["flags"] & 4 and add(p.origin, apply(p.Q, n["position"])) == v
                    for n in (definitions.metadata(p.piece.d) or {}).get("voxels", []))}


def _land_access(p, owner, reserved=frozenset()):
    """Open vehicle seats use a supported side approach; small batteries are serviced above."""
    cells = p.voxels()
    lo = [min(v[i] for v in cells) for i in range(3)]
    hi = [max(v[i] for v in cells) for i in range(3)]
    if p.piece.d.startswith("seat"):
        owner = _access_owner(owner)
        front = apply(p.Q, profile(p.piece.d)["axes"].get("seat_front", (0, 0, 1)))
        if front not in DIRS or front[1]:
            raise ValueError("control position must face horizontally")
        longitudinal, lateral = (2, 0) if front[2] else (0, 2)
        mid = (lo[longitudinal] + hi[longitudinal]) // 2
        failures = []
        for side in (-1, 1):
            approach = lo[lateral] - 2 if side < 0 else hi[lateral] + 2
            space = set()
            # Entry into a vehicle seat is a seated/ducked approach, rather
            # than a standing ship aisle. Keep the installed seat's height,
            # with at least 1.25 m clearance at the threshold.
            height = max(5, hi[1] - lo[1] + 1)
            for a, b, y in product(range(-1, 2), range(-1, 2), range(lo[1], lo[1] + height)):
                v = [0, y, 0]
                v[lateral], v[longitudinal] = approach + a, mid + b
                space.add(tuple(v))
            threshold = lo[lateral] - 1 if side < 0 else hi[lateral] + 1
            floor = {add(v, (0, -1, 0)) for v in space if v[1] == lo[1] and v[lateral] == threshold}
            blocked = _obstructions(space, owner, reserved)
            missing = sorted(v for v in floor if not _supported({v}, owner))
            if not blocked and not missing:
                return space
            failures.append({"side": side, "obstructions": blocked, "missing_support_cells": missing[:12]})
        rear = _clearance(p, {})
        floor = {add(v, (0, -1, 0)) for v in rear if v[1] == lo[1]}
        blocked = _obstructions(rear, owner, reserved)
        missing = sorted(v for v in floor if not _supported({v}, owner))
        if rear and not blocked and not missing:
            return rear
        failures.append({"side": "rear", "obstructions": blocked, "missing_support_cells": missing[:12]})
        raise ValueError(f"component '{p.name}' needs unobstructed clearance and a supported 0.75 m side access passage or rear approach; "
                         f"access diagnostics={failures}")
    if p.piece.d == "battery_small":
        space = {(v[0], y, v[2]) for v in cells for y in range(hi[1] + 1, hi[1] + 3)}
        blocked = _obstructions(space, owner, reserved)
        if blocked:
            raise ValueError(f"component '{p.name}' needs open service access above the small battery; obstructions={blocked}")
        return space
    return _clearance(p, {})


def _clearance(p, cfg):
    cells = p.voxels()
    if (cfg.get("kind") in ("helm", "seat") or p.piece.d in ("seat_helm", "seat_compact", "seat")
            or p.piece.d.startswith("seat")
            or control_seat(p.piece.d, definitions.metadata(p.piece.d) or {})):
        # Three-block approach, eight-block standing height behind the control position.
        lo = [min(v[i] for v in cells) for i in range(3)]
        hi = [max(v[i] for v in cells) for i in range(3)]
        front = apply(p.Q, profile(p.piece.d)["axes"].get("seat_front", (0, 0, 1)))
        if front[1] or sum(abs(v) for v in front) != 1:
            raise ValueError("control position must face horizontally")
        axis = 2 if front[2] else 0
        lateral = 0 if axis == 2 else 2
        approach = lo[axis] - 2 if front[axis] > 0 else hi[axis] + 2
        centre = (lo[lateral] + hi[lateral]) // 2
        out = set()
        for a, b, y in product(range(-1, 2), range(-1, 2), range(lo[1], lo[1] + 8)):
            v = [0, y, 0]
            v[axis], v[lateral] = approach + a, centre + b
            out.add(tuple(v))
        return out
    if cfg.get("kind") == "propeller" or p.piece.d in PROPELLERS.values():
        # Blade rotation plane: keep a margin around the definition's editor footprint.
        margin = max(1, round(float((definitions.metadata(p.piece.d) or {}).get("properties", {})
                                    .get("force_emitter_blade_physics_length", 0.25)) * 4))
        lo, hi = ([min(v[i] for v in cells) for i in range(3)],
                  [max(v[i] for v in cells) for i in range(3)])
        force = apply(p.Q, tuple((definitions.metadata(p.piece.d) or {}).get("directions", {})
                                .get("force_dir", (0, -1, 0))))
        axis = next((i for i in range(3) if force[i]), 2)
        return set(product(*(range(lo[i] - (0 if i == axis else margin),
                                   hi[i] + (0 if i == axis else margin) + 1) for i in range(3)))) - set(cells)
    if p.piece.d in RUDDERS:
        return rudder_clearance(p)
    return set()


def validate_placement(p, cfg, owner, reserved=frozenset()):
    cells = set(p.voxels())
    if any(v in owner or v in reserved for v in cells):
        raise ValueError(f"component '{p.name}' footprint collides with structure or reserved access; "
                         f"obstructions={_obstructions(cells, owner, reserved)}")
    if not mounted(p, owner):
        raise ValueError(f"component '{p.name}' has no verified mounting contact")
    land = cfg.get("vehicle_kind") == "land"
    clearance = _land_access(p, owner, reserved) if land else _clearance(p, cfg)
    access_owner = _access_owner(owner) if land and p.piece.d.startswith("seat") else owner
    if any(v in access_owner or v in reserved for v in clearance):
        raise ValueError(f"component '{p.name}' has insufficient occupant/operating clearance; "
                         f"obstructions={_obstructions(clearance, access_owner, reserved)}")
    if p.piece.d.startswith("seat_") and not land:
        floor = {add(v, (0, -1, 0)) for v in clearance if v[1] == min(c[1] for c in clearance)}
        if not floor or not _supported(floor, owner):
            raise ValueError(f"component '{p.name}' needs a supported 0.75 m access passage")
    if p.piece.d in BATTERIES.values() and not (land and p.piece.d == "battery_small"):
        lo, hi = ([min(v[i] for v in cells) for i in range(3)],
                  [max(v[i] for v in cells) for i in range(3)])
        z = (lo[2] + hi[2]) // 2
        for x in (lo[0] - 2, hi[0] + 2):
            aisle = set(product(range(x - 1, x + 2), range(lo[1], lo[1] + 8), range(z - 1, z + 2)))
            floor = {add(v, (0, -1, 0)) for v in aisle if v[1] == lo[1]}
            if not any(v in owner or v in reserved for v in aisle) and _supported(floor, owner):
                clearance = aisle
                break
        else:
            raise ValueError(f"component '{p.name}' would block the 0.75 m access passage")
    return clearance


def _definitions(cfg, bridge=False):
    if cfg.get("definition"):
        return [cfg["definition"]]
    kind, size = cfg.get("kind"), cfg.get("size", "auto")
    if kind == "battery":
        return list(reversed(list(BATTERIES.values()))) if size == "auto" else [BATTERIES[size]]
    if kind == "propeller":
        return list(reversed(list(PROPELLERS.values()))) if size == "auto" else [PROPELLERS[size]]
    if kind in ("helm", "seat"):
        return ["seat_helm", "seat_compact"] if bridge and kind == "helm" else ["seat_compact"]
    if kind == "rudder":
        return ["rudder", "rudder_surface"]
    raise ValueError("component needs definition or kind=battery/helm/seat/propeller/rudder")


def _orientation(cfg, d):
    if "orientation" in cfg:
        return solve(d, cfg["orientation"])
    if "rotation" in cfg:
        return rotation(cfg["rotation"], allow_mirror=True)
    if d in RUDDERS:
        return solve(d, profile(d)["default_targets"])
    if d in PROPELLERS.values():
        direction = tuple(definitions.metadata(d)["directions"]["force_dir"])
        return find_rotation([(direction, (0, 0, 1)), ((1, 0, 0), (1, 0, 0))])
    return IDENTITY


def _candidates(piece, q, cfg, info, owner):
    if "position" in cfg:
        yield tuple(round(v * 4) for v in vector(cfg["position"], integer=False))
        return
    cells = [apply(q, v) for v in piece.footprint]
    rooms = info["interior"].rooms
    requested = cfg.get("room")
    if requested:
        rooms = [r for r in rooms if r.name == requested]
        if not rooms:
            raise ValueError(f"no room named {requested!r}")
    elif cfg.get("kind") in ("helm", "seat"):
        rooms = sorted(rooms, key=lambda r: r.kind != "bridge")
    else:
        rooms = sorted(rooms, key=lambda r: r.kind not in ("engine", "machinery"))
    if cfg.get("kind") in ("propeller", "rudder") or piece.d in (*PROPELLERS.values(), *RUDDERS):
        target = (0, round(info["form"].depth * 0.35), -2)
        mounting = full_faces(piece.d, q, attachment=True)
        candidates = set()
        for v in owner:
            if v[2] > info["form"].L * 0.2 or v[1] > info["form"].depth * 0.75:
                continue
            for cell, direction in mounting:
                candidates.add(sub(sub(v, direction), cell))
        yield from sorted(candidates, key=lambda v: (sum((v[i] - target[i]) ** 2 for i in range(3)), v))
        return
    regions = [r.air for r in rooms] if rooms else []
    if not requested:
        regions.append(info["region"])
    lo = hi = None
    if "bay" in cfg:
        bay = cfg["bay"]
        if not isinstance(bay, list) or len(bay) != 2:
            raise ValueError("bay must be two positions in game metres")
        lo, hi = (vector(v, integer=False) for v in bay)
        if any(lo[i] > hi[i] for i in range(3)):
            raise ValueError("bay bounds are reversed")
    def available(v, region):
        return v in region and v not in owner and (lo is None or all(
            lo[i] * 4 <= v[i] <= hi[i] * 4 for i in range(3)))
    min_y = min(v[1] for v in cells)
    for region in regions:
        if not region:
            continue
        # Search the exposed mounting surface, not every free voxel of a million-voxel hull.
        floor = [add(v, (0, 1, 0)) for v in owner if available(add(v, (0, 1, 0)), region)]
        if not floor:
            continue
        centre = tuple((min(v[i] for v in floor) + max(v[i] for v in floor)) / 2 for i in range(3))
        for v in sorted(floor, key=lambda v: (sum((v[i] - centre[i]) ** 2 for i in (0, 2)), v)):
            origin = (v[0], v[1] - min_y, v[2])
            if all(available(add(origin, cell), region) for cell in cells):
                yield origin


def validate_config(spec):
    components = spec.get("components", [])
    if not isinstance(components, list):
        raise ValueError("components must be a list")
    names = set()
    for cfg in components:
        if not isinstance(cfg, dict) or not isinstance(cfg.get("name"), str) or not cfg["name"]:
            raise ValueError("each component needs a nonempty name")
        if cfg["name"] in names:
            raise ValueError("component names must be unique")
        names.add(cfg["name"])
        if not isinstance(cfg.get("settings", {}), dict) or not isinstance(cfg.get("repeat", {}), dict):
            raise ValueError("component settings and repeat must be objects")
        component_xml(Placed(BY_NAME["01_block"], (0, 0, 0), settings=cfg.get("settings", {})))
        if cfg.get("definition") is not None and not isinstance(cfg["definition"], str):
            raise ValueError("component definition must be a string")
        if cfg.get("mirror_x") is not None and not isinstance(cfg["mirror_x"], bool):
            raise ValueError("mirror_x must be boolean")
        kind, size = cfg.get("kind"), cfg.get("size", "auto")
        sizes = BATTERIES if kind == "battery" else PROPELLERS if kind == "propeller" else {}
        if sizes and size not in ("auto", *sizes):
            raise ValueError(f"invalid {kind} size {size!r}")
        if "position" in cfg:
            vector(cfg["position"], integer=False)
        rotation(cfg.get("rotation"), allow_mirror=True)
        if "orientation" in cfg:
            if "rotation" in cfg:
                raise ValueError("use orientation or rotation, not both")
            if not isinstance(cfg["orientation"], dict) or not cfg["orientation"]:
                raise ValueError("orientation must be a nonempty object")
        if "color" in cfg:
            color(cfg["color"])
        count = cfg.get("repeat", {}).get("count", cfg.get("count", 1))
        if not isinstance(count, int) or not 1 <= count <= 100:
            raise ValueError("component repeat.count must be 1-100")
        if cfg.get("repeat"):
            vector(cfg["repeat"].get("step", [0, 0, 0]), "repeat.step", integer=False)
    fitout = spec.get("fitout")
    if fitout is not None and (not isinstance(fitout, dict) or fitout.get("stage", "core") not in STAGES):
        raise ValueError(f"fitout.stage must be one of {', '.join(STAGES)}")
    if fitout and any(not isinstance(fitout.get(k, {}), dict) for k in ("control", "battery", "propeller", "rudder")):
        raise ValueError("fitout overrides must be objects")


def place(parts, info, spec):
    """Place named components atomically; automatic requests skip with a clear report."""
    validate_config(spec)
    owner = owners(parts)
    reserved = set(info.get("tank_reserved", [])) | info["interior"].reserved
    report = []
    cfgs = copy.deepcopy(spec.get("components", []))
    fitout = spec.get("fitout") or {}
    stage = STAGES.index(fitout.get("stage", "structure"))
    bridge = any(r.kind == "bridge" for r in info["interior"].rooms)
    if stage >= STAGES.index("core"):
        defaults = [{"name": "control", "kind": "helm" if bridge else "seat", **fitout.get("control", {})},
                    {"name": "battery", "kind": "battery", **fitout.get("battery", {})}]
        if stage >= STAGES.index("propulsion"):
            defaults += [{"name": "propeller", "kind": "propeller", "size": "small", **fitout.get("propeller", {})},
                         {"name": "rudder", "kind": "rudder", **fitout.get("rudder", {})}]
        for cfg in defaults:
            if not any(c["name"] == cfg["name"] for c in cfgs):
                cfgs.append(cfg)
    # Occupant paths are reserved before batteries, irrespective of input order.
    validate_config({"components": cfgs})
    expanded = []
    for cfg in cfgs:
        count = cfg.get("count", 1)
        if count > 1 and not cfg.get("repeat"):
            if "position" in cfg:
                raise ValueError("count with an explicit position needs repeat.step for separate footprints")
            expanded.extend({**cfg, "name": f"{cfg['name']}_{i + 1}", "count": 1} for i in range(count))
        else:
            expanded.append(cfg)
    cfgs = expanded
    validate_config({"components": cfgs})
    cfgs.sort(key=lambda cfg: cfg.get("kind") not in ("helm", "seat"))
    for cfg in cfgs:
        automatic = "position" not in cfg and not cfg.get("definition")
        installed = False
        failure = "definitions missing or no fitting mounted location with access clearance"
        for d in _definitions(cfg, bridge):
            from .part_policy import ensure_allowed  # noqa: PLC0415
            ensure_allowed(d)
            piece = BY_NAME.get(d) or definitions.load(d)
            if piece is None:
                if not automatic:
                    raise ValueError(definitions.unavailable(d))
                continue
            q = _orientation(cfg, d)
            for origin in _candidates(piece, q, cfg, info, owner):
                p = Placed(piece, origin, q, cfg.get("color", "C2C3C7"),
                           f"component:{cfg['name']}", cfg["name"], new_settings(d, cfg.get("settings", {})))
                count = cfg.get("repeat", {}).get("count", cfg.get("count", 1))
                step = tuple(round(v * 4) for v in cfg.get("repeat", {}).get("step", [0, 0, 0]))
                group = []
                for i in range(count):
                    clone = copy.copy(p)
                    clone.settings = dict(p.settings)
                    clone.origin = add(origin, tuple(i * v for v in step))
                    if count > 1:
                        clone.uid, clone.name = f"{p.uid}:{i + 1}", f"{p.name}_{i + 1}"
                    if cfg.get("mirror_x"):
                        clone.name += "_stbd"
                        clone.uid += ":stbd"
                    group.append(clone)
                    if cfg.get("mirror_x"):
                        twin = copy.copy(clone)
                        twin.settings = dict(clone.settings)
                        twin.origin = (-clone.origin[0], clone.origin[1], clone.origin[2])
                        twin.Q = (tuple(-n for n in clone.Q[0]), *clone.Q[1:])
                        twin.uid, twin.name = clone.uid.replace(":stbd", ":port"), clone.name.replace("_stbd", "_port")
                        group.append(twin)
                local_owner, local_reserved = ChainMap({}, owner), set(reserved)
                try:
                    for item in group:
                        component_xml(item)
                        space = validate_placement(item, cfg, local_owner, local_reserved)
                        local_owner.update({v: item for v in item.voxels()})
                        local_reserved.update(space)
                except ValueError as exc:
                    failure = str(exc)
                    continue
                parts.extend(group)
                owner, reserved = local_owner, local_reserved
                report.extend(f"{item.name}: {definitions.display_name(d)} at "
                              f"{[v / 4 for v in item.origin]} game m" for item in group)
                installed = True
                break
            if installed:
                break
        if not installed:
            if not automatic:
                raise ValueError(failure)
            info["warnings"].append(f"component '{cfg['name']}' skipped: {failure}")
    info["components"] = report
    return parts
