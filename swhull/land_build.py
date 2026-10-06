"""A mounted chassis draft in game metres, extended through the existing part editor."""
import copy
import math
from itertools import product

from . import definitions
from .benches import fit_lines, parse_bench
from .components import owners, validate_placement
from .editing import MAX_BATCH_PARTS, apply_edits, color, vector
from .land import road_wheel
from .orientation import profile, solve
from .pieces import BLOCK, BY_NAME, Placed

DEFAULT_SPEC = {"length": 4.25, "width": 1.25, "thickness": 0.25,
                "wheel_definition": "wheel_advanced_3_sus",
                "axles": [{"z": -1.25}, {"z": 1.25}],
                "driver": True, "headlights": True, "tail_lights": True}


def _blocks(value, label, positive=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or value * 4 != round(value * 4) or positive and value <= 0):
        raise ValueError(f"{label} must be {'positive ' if positive else ''}metres on the 0.25 m grid")
    return round(value * 4)


def _position(value):
    return [_blocks(n, "position") for n in vector(value, integer=False)]


def _part(d, name, position, targets=None, settings=None, paint="C2C3C7"):
    from .part_policy import ensure_allowed  # noqa: PLC0415
    if isinstance(d, str):
        ensure_allowed(d)
    if not isinstance(d, str) or definitions.load(d) is None:
        raise ValueError(definitions.unavailable(d))
    return {"definition": d, "name": name, "position": position, "color": color(paint),
            "settings": settings if settings is not None else {},
            **({"rotation": solve(d, targets)} if targets else {})}


def _option(spec, key):
    value = spec.get(key, True)
    if value is False:
        return None
    if value is True:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be boolean or an object")
    return value


def build_chassis(spec=None):
    if spec is None:
        spec = {}
    if not isinstance(spec, dict):
        raise ValueError("land vehicle spec must be an object")
    allowed = {*DEFAULT_SPEC, "color", "bench", "components", "edits"}
    if set(spec) - allowed:
        raise ValueError(f"unknown land spec fields: {', '.join(sorted(set(spec) - allowed))}")
    cfg = {**copy.deepcopy(DEFAULT_SPEC), **copy.deepcopy(spec)}
    parse_bench(cfg.get("bench"))
    length, width, thickness = (_blocks(cfg[k], k, positive=True) for k in ("length", "width", "thickness"))
    if length * width * thickness > MAX_BATCH_PARTS:
        raise ValueError(f"chassis exceeds {MAX_BATCH_PARTS} blocks")
    xlo, zlo = -(width // 2), -(length // 2)
    xhi, zhi = xlo + width - 1, zlo + length - 1
    paint = color(cfg.get("color", "4B5563"))
    parts = [Placed(BLOCK, v, color=paint, name="chassis")
             for v in product(range(xlo, xhi + 1), range(1 - thickness, 1), range(zlo, zhi + 1))]
    axles = cfg["axles"]
    if not isinstance(axles, list) or not 2 <= len(axles) <= 8:
        raise ValueError("axles must contain 2-8 objects with z positions in metres")
    items, stations = [], set()
    for i, axle in enumerate(axles):
        if not isinstance(axle, dict) or set(axle) - {"z", "definition", "settings"}:
            raise ValueError("each axle needs z and optional definition/settings")
        z = _blocks(axle.get("z"), "axle.z")
        if z in stations or not zlo <= z <= zhi:
            raise ValueError("axle stations must be distinct and within the chassis length")
        stations.add(z)
        d = axle.get("definition", cfg["wheel_definition"])
        if not isinstance(d, str) or not road_wheel(d):
            raise ValueError("wheel_definition must be an installed road-wheel family, not a track/train wheel")
        for side, x, outward in (("left", xlo - 1, -1), ("right", xhi + 1, 1)):
            targets = {"axle_axis": [outward, 0, 0], "wheel_reference_up": [0, 1, 0]}
            if "wheel_forward" in profile(d)["axes"]:
                targets["wheel_forward"] = [0, 0, 1]
            items.append(_part(d, f"axle {i + 1} {side} wheel", [x, 0, z],
                               targets,
                               axle.get("settings"), "242424"))
    driver = _option(cfg, "driver")
    if driver is not None:
        d = driver.get("definition", "seat_racing")
        items.append(_part(d, "driver", _position(driver.get("position", [0, 0.25, 0.25])),
                           {"seat_front": [0, 0, 1], "seat_up": [0, 1, 0]}, driver.get("settings"), "64748B"))
    headlights = _option(cfg, "headlights")
    if headlights is not None:
        d = headlights.get("definition", "searchlight_small_2")
        targets = {"light_forward": [0, 0, 1], "mount_normal": [0, -1, 0]}
        for side, x in (("left", xlo), ("right", xhi)):
            items.append(_part(d, f"{side} headlight", [x, 1, zhi], targets,
                               headlights.get("settings"), "F8FAFC"))
    tail_lights = _option(cfg, "tail_lights")
    if tail_lights is not None:
        for side, x in (("left", xlo), ("right", xhi)):
            items.append(_part(tail_lights.get("definition", "small_light"), f"{side} rear marker",
                               [x, 1, zlo], settings=tail_lights.get("settings"), paint="FF3322"))
    extra = cfg.get("components", [])
    if not isinstance(extra, list) or len(extra) > 200:
        raise ValueError("components must be a list of at most 200 objects")
    for item in extra:
        if not isinstance(item, dict) or "position" not in item:
            raise ValueError("each extra component needs a position in game metres")
        if "rotation" in item and "orientation" in item:
            raise ValueError("use orientation or rotation, not both")
        out = {**item, "position": _position(item["position"])}
        targets = out.pop("orientation", None)
        if targets is not None:
            out["rotation"] = solve(out.get("definition", "01_block"), targets)
        items.append(out)
    context = {"vehicle_kind": "land"}
    parts = apply_edits(parts, [{"op": "add", "parts": items}], prefix="land", placement_context=context)
    parts = apply_edits(parts, cfg.get("edits", []), prefix="land-edit", placement_context=context)
    # Bodywork edits can remove a wheel's support or block an unchanged driver's access.
    # Check the completed assembly, including components the edit did not move.
    if cfg.get("edits"):
        owner = owners(parts)
        for p in parts:
            if p.piece.d not in BY_NAME:
                validate_placement(p, context, {v: other for v, other in owner.items() if other is not p})
    return parts


def summary(spec, parts):
    cells = [v for p in parts for v in p.voxels()]
    lo = [min(v[i] for v in cells) for i in range(3)]
    hi = [max(v[i] for v in cells) for i in range(3)]
    size = [(hi[i] - lo[i] + 1) / 4 for i in range(3)]
    wheels = sum(road_wheel(p.piece.d) for p in parts)
    centre = [(lo[i] + hi[i]) // 2 for i in range(3)]
    bench = fit_lines(spec.get("bench"), [lo[i] - centre[i] for i in range(3)],
                      [hi[i] - centre[i] for i in range(3)])
    preset = spec.get("preset", "chassis")
    label = "Land chassis draft" if preset == "chassis" else f"Land vehicle draft ({preset})"
    inventory = [f"{p.name}: {definitions.display_name(p.piece.d)} ({p.piece.d})"
                 for p in parts if p.piece.d not in BY_NAME]
    completion = "Assembly is unfinished: use query_connections, edit_connections, route_connections and preflight_vehicle to complete its systems."
    if preset in ("utility_4x4", "humvee_4x4"):
        completion = ("Connected template: fuel/air/exhaust/radiator pipework, engine-clutch-gearbox-four-wheel driveline, "
                      "electrical power and controls are included. Run preflight_vehicle after edits; operation needs game checks.\n"
                      "Controls: Axis 1 steering; Axis 2 throttle; trigger brake; hotkey 1 hold starter, 2 lights, 3 reverse. "
                      "Check W forward, A left, D right and the reverse ratio in game.")
    return "\n".join([f"{label}: {len(parts)} parts, {wheels} wheels.",
                      f"Overall editor footprint: {size[2]:.2f} m long x {size[0]:.2f} m wide x {size[1]:.2f} m tall.",
                      "Build frame: x lateral, +y up, +z forward; chassis top at y=0. Edits use 0.25 m blocks.",
                      *bench,
                      "Installed components: " + "; ".join(inventory[:40])
                      + (f"; {len(inventory) - 40} more (query_parts)" if len(inventory) > 40 else ""),
                      completion,
                      "Verify both steering signs, tyre size, suspension travel and ground clearance in game.",
                      "Rear markers are painted red; paint alone does not validate emitted light colour."])
