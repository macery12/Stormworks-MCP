"""Semantic rotation constraints and conservative rudder motion derived from definitions."""
import math
from itertools import product

from . import definitions
from .land import category, road_wheel
from .pieces import DIRS, IDENTITY, MIRRORED, add, apply, find_rotation, r_attr, split_mirror

RUDDERS = ("rudder", "rudder_surface")


def profile(d):
    """Separate attachment direction from blade direction, hinge and functional axes."""
    data = definitions.metadata(d)
    if data is None:
        raise ValueError(definitions.unavailable(d))
    axes = {key: tuple(value) for key, value in data["directions"].items()
            if tuple(value) in DIRS and key not in ("dynamic_body_position", "voxel_location_child")}
    axes = {key: value for key, value in axes.items()
            if (not key.startswith("seat_") or d.startswith("seat"))
            and (not key.startswith("door_") or d.startswith("door"))
            and (not key.startswith("dynamic_") or road_wheel(d)
                 or any(v["flags"] & 4 for v in data.get("voxels", [])))
            and (key != "light_forward" or category(d) == "lights")}
    evidence = {key: "installed definition" for key in axes}
    for i, surface in enumerate(data["attachment_surfaces"]):
        if surface["trans_type"] > 0 and 0 <= surface["orientation"] < 6:
            key = f"port_{i}_normal"
            axes[key] = DIRS[surface["orientation"]]
            evidence[key] = f"installed surface {i}, trans_type={surface['trans_type']}"
    defaults = {}
    if d == "seat_saddle":
        # The installed definition leaves these at zero. Ordinary identity saddle
        # placements in the supplied workshop quad face +z with +y up.
        axes.update(seat_front=(0, 0, 1), seat_up=(0, 1, 0))
        evidence.update(dict.fromkeys(("seat_front", "seat_up"),
                                      "observed saddle placement convention; verify in game"))
    if road_wheel(d):
        axle = tuple(data["directions"].get("dynamic_rotation_axes", (0, 0, 0)))
        if axle in DIRS:
            axes["axle_axis"] = axle
            evidence["axle_axis"] = "installed dynamic_rotation_axes; wheel axle, not steering hinge"
        normals = {DIRS[s["orientation"]] for s in data["attachment_surfaces"]
                   if s["trans_type"] > 0 and 0 <= s["orientation"] < 6}
        if len(normals) == 1:
            axes["mount_normal"] = next(iter(normals))
            evidence["mount_normal"] = "installed wheel transmission/mount surface"
        # Radial reference used by the ordinary upright wheels observed in saved road vehicles.
        # This is a placement convention, not a solver for suspension/steering physics.
        axes["wheel_reference_up"] = (0, 0, -1)
        evidence["wheel_reference_up"] = "saved road-wheel placement convention; verify suspension in game"
        if d.startswith("wheel_advanced_") or d in ("wheel_small", "wheel_medium"):
            axes["wheel_forward"] = (1, 0, 0)
            axes["wheel_positive_steering"] = (0, 1, 0)
            evidence["wheel_forward"] = "installed editor drive arrow at reference-up; saved workshop mirrored pair"
            evidence["wheel_positive_steering"] = (
                "installed positive steering arrow tangent at wheel_forward; workshop quad inverts left steering")
    if category(d) == "lights":
        normals = {DIRS[s["orientation"]] for s in data["attachment_surfaces"]
                   if 0 <= s["orientation"] < 6}
        if len(normals) == 1:
            axes["mount_normal"] = next(iter(normals))
            evidence["mount_normal"] = "installed light attachment surface"
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
            "coordinates": "body-local blocks; +y up, generated vehicles +z forward",
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
    try:
        return find_rotation(pairs)
    except ValueError:
        if road_wheel(d):
            for q in MIRRORED:
                if all(apply(q, local) == world for local, world in pairs):
                    return q
        raise


def describe(d, targets=None):
    result = profile(d)
    q = solve(d, targets) if targets is not None else (
        solve(d, result["default_targets"]) if result["default_targets"] else IDENTITY)
    rot, mirror = split_mirror(q, 2 if road_wheel(d) else 1)
    return {**result, "rotation": q, "r": r_attr(rot), "mirror": mirror,
            "world_axes": {key: apply(q, value) for key, value in result["axes"].items()}}


def wheel_directions(p, forward=(0, 0, 1), up=(0, 1, 0)):
    """Arrow-frame evidence, not tyre/contact physics or signed gearbox simulation."""
    axes = profile(p.piece.d)["axes"]
    if "wheel_forward" not in axes:
        return None
    world = {key: apply(p.Q, axes[key]) for key in
             ("wheel_forward", "wheel_reference_up", "wheel_positive_steering")}
    # Left-handed game coordinates: +z forward and +y up gives +x right.
    right = (up[1]*forward[2]-up[2]*forward[1], up[2]*forward[0]-up[0]*forward[2],
             up[0]*forward[1]-up[1]*forward[0])
    drive = sum(a*b for a, b in zip(world["wheel_forward"], forward))
    upright = sum(a*b for a, b in zip(world["wheel_reference_up"], up))
    tangent = sum(a*b for a, b in zip(world["wheel_positive_steering"], right))
    return {"part_id": p.uid, **world, "forward_dot": drive, "up_dot": upright,
            "positive_steering_right_dot": tangent,
            "required_steering_sign": tangent if drive == upright == 1 and abs(tangent) == 1 else None,
            "basis": "positive wheel RPS; Axis 1 A=-1, D=+1; arrow convention from installed mesh/workshop quad",
            "verification": "Does not simulate gearbox sign, tyre contact or suspension. Confirm W forward and D right in game."}


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
