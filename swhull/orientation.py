"""Semantic rotation constraints and conservative rudder motion derived from definitions."""
import math
from itertools import product

from . import definitions
from .pieces import DIRS, IDENTITY, add, apply, find_rotation, r_attr

RUDDERS = ("rudder", "rudder_surface")


def profile(d):
    """Separate attachment direction from blade direction, hinge and functional axes."""
    data = definitions.metadata(d)
    if data is None:
        raise ValueError(f"definition {d!r} unavailable")
    axes = {key: tuple(value) for key, value in data["directions"].items()
            if tuple(value) in DIRS and key not in ("dynamic_body_position", "voxel_location_child")}
    axes = {key: value for key, value in axes.items()
            if (not key.startswith("seat_") or d.startswith("seat"))
            and (not key.startswith("door_") or d.startswith("door"))
            and (not key.startswith("dynamic_") or any(v["flags"] & 4 for v in data.get("voxels", [])))}
    evidence = {key: "installed definition" for key in axes}
    for i, surface in enumerate(data["attachment_surfaces"]):
        if surface["trans_type"] > 0 and 0 <= surface["orientation"] < 6:
            key = f"port_{i}_normal"
            axes[key] = DIRS[surface["orientation"]]
            evidence[key] = f"installed surface {i}, trans_type={surface['trans_type']}"
    defaults = {}
    if d in RUDDERS:
        # Both rudder definitions have a fixed base at local y=0 and flag-4 blade cells at +y.
        # Do not confuse the many attachable base sides with the intended hull mounting face.
        axes.update(mount_normal=(0, -1, 0), blade_direction=(0, 1, 0), span_axis=(0, 0, 1))
        evidence.update(dict.fromkeys(("mount_normal", "blade_direction", "span_axis"),
                                     "rudder base/blade convention; verify with in-game calibration"))
        if "dynamic_rotation_axes" in axes:
            axes["hinge_axis"] = axes["dynamic_rotation_axes"]
            evidence["hinge_axis"] = "installed dynamic_rotation_axes"
        if "dynamic_side_axis" in axes:
            axes["side_axis"] = axes["dynamic_side_axis"]
            evidence["side_axis"] = "installed dynamic_side_axis"
        defaults = ({"mount_normal": (0, 1, 0), "span_axis": (0, 0, 1)} if d == "rudder" else
                    {"mount_normal": (0, 0, 1), "span_axis": (0, 1, 0)})
    return {"definition": d, "axes": axes, "evidence": evidence, "default_targets": defaults,
            "coordinates": "body-local blocks; +y up, generated boats +z bow",
            "limitations": ["An axis observation does not prove thrust, steering sign or mounting in game."]}


def solve(d, targets):
    if not isinstance(targets, dict) or not targets:
        raise ValueError("orientation must be a nonempty object of semantic axes and target unit vectors")
    axes = profile(d)["axes"]
    pairs = []
    for key, value in targets.items():
        if key not in axes:
            raise ValueError(f"unknown orientation axis {key!r} for {d}; available: {', '.join(axes)}")
        if not isinstance(value, (list, tuple)) or len(value) != 3 or any(
                isinstance(n, bool) or not isinstance(n, (int, float)) for n in value) or tuple(value) not in DIRS:
            raise ValueError(f"orientation {key} must be an axis-aligned unit vector")
        pairs.append((axes[key], tuple(value)))
    return find_rotation(pairs)


def describe(d, targets=None):
    result = profile(d)
    q = solve(d, targets) if targets is not None else (
        solve(d, result["default_targets"]) if result["default_targets"] else IDENTITY)
    return {**result, "rotation": q, "r": r_attr(q),
            "world_axes": {key: apply(q, value) for key, value in result["axes"].items()}}


def _arc_bounds(a, b, low, high):
    """Exact extrema of a*cos(theta)+b*sin(theta) across a bounded angular interval."""
    angles = [low, high]
    stationary = math.atan2(b, a)
    for k in range(math.floor((low - stationary) / math.pi), math.ceil((high - stationary) / math.pi) + 1):
        angle = stationary + k * math.pi
        if low <= angle <= high:
            angles.append(angle)
    values = [a * math.cos(t) + b * math.sin(t) for t in angles]
    return min(values), max(values)


def rudder_clearance(p):
    """Swept voxel bounds, including interior angular extrema; transform after local motion.

    Editor voxels approximate meshes. Bounds are conservative, never evidence of exact physics.
    """
    data = definitions.metadata(p.piece.d) or {}
    moving = [tuple(v["position"]) for v in data.get("voxels", []) if v["flags"] & 4]
    directions = data.get("directions", {})
    hinge = tuple(directions.get("dynamic_rotation_axes", (0, 0, 0)))
    if not moving or hinge not in DIRS:
        return {add(v, apply(p.Q, d)) for v in p.voxels() for d in ((1, 0, 0), (-1, 0, 0))} - set(p.voxels())
    axis = next(i for i, n in enumerate(hinge) if n)
    a, b = ((1, 2), (2, 0), (0, 1))[axis]
    pivot = tuple(directions.get("dynamic_body_position", (0, 0, 0)))
    props = data.get("properties", {})
    low, high = sorted((float(props.get("dynamic_min_rotation", -math.pi / 4)),
                        float(props.get("dynamic_max_rotation", math.pi / 4))))
    if hinge[axis] < 0:
        low, high = -high, -low
    swept = set()
    for cell in moving:
        bounds = [[math.inf, -math.inf] for _ in range(3)]
        for corner in product((-.5, .5), repeat=3):
            v = [cell[i] + corner[i] - pivot[i] for i in range(3)]
            ranges = {axis: (v[axis], v[axis]), a: _arc_bounds(v[a], -v[b], low, high),
                      b: _arc_bounds(v[b], v[a], low, high)}
            for i in range(3):
                bounds[i][0] = min(bounds[i][0], ranges[i][0] + pivot[i])
                bounds[i][1] = max(bounds[i][1], ranges[i][1] + pivot[i])
        swept.update(product(*(range(math.ceil(lo - .5 + 1e-8), math.floor(hi + .5 - 1e-8) + 1)
                               for lo, hi in bounds)))
    return {add(p.origin, apply(p.Q, v)) for v in swept} - set(p.voxels())
