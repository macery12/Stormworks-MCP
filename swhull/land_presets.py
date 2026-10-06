"""Original land layouts assembled from installed parts, not copied workshop XML."""
import copy
from itertools import product

from .components import validate_placement
from .editing import apply_edits, color, identify, part
from .land_build import _part, _position
from .orientation import solve
from .pieces import BLOCK, BY_NAME, Placed, WEDGE, find_rotation, wedge_rotation

PRESETS = {"utility_buggy": "Open utility buggy: suspension wheels, saddle, diesel engine, premade tanks, battery, radiator and lights.",
           "humvee_4x4": "Connected Humvee example: open custom-door bays, small windshields, sloped hood and enclosed chassis pipework.",
           "utility_4x4": "Connected utility 4x4: prebuilt diesel, radiator, premade tank, four seats, full side doors, larger suspension tyres and lights.",
           "chassis": "Bare configurable chassis for custom layouts; no finished body or power system."}


def _complete(parts):
    identify(parts)
    owner = {}
    for p in parts:
        for v in p.voxels():
            if v in owner:
                raise ValueError(f"land assembly collision at {v}: {p.name} / {owner[v].name}")
            owner[v] = p
    for p in parts:
        if p.piece.d not in BY_NAME:
            validate_placement(p, {"vehicle_kind": "land"},
                               {v: other for v, other in owner.items() if other is not p})
    return parts


def buggy(spec):
    allowed = {"preset", "color", "accent", "bench", "wheel_definition", "wheel_settings", "components", "edits",
               "engine_cover"}
    if set(spec) - allowed:
        raise ValueError(f"utility_buggy has a fixed layout; unknown fields: {', '.join(sorted(set(spec) - allowed))}. "
                         "Use preset=chassis for dimension/axle parameters.")
    paint, trim = color(spec.get("color", "D5A928")), color(spec.get("accent", "303840"))
    blocks = {}

    def fill(lo, hi, name, colour):
        for v in product(*(range(lo[i], hi[i] + 1) for i in range(3))):
            blocks[v] = Placed(BLOCK, v, color=colour, name=name)

    # Narrow backbone, axle crossmembers, side footboards and clear tyre envelopes.
    fill((-1, 0, -7), (1, 0, 7), "chassis backbone", trim)
    for z in (-4, 4):
        fill((-1, -1, z), (1, -1, z), "axle crossmember", trim)
    for side in (-1, 1):
        lo, hi = sorted((side * 2, side * 4))
        fill((lo, 0, 0), (hi, 0, 2), "side footboard", trim)
        for z in (-4, 4):
            lo, hi = sorted((side * 2, side * 4))
            fill((lo, 1, z - 1), (hi, 1, z + 1), "wheel fender", paint)
            fill((side * 2, 0, z), (side * 2, 0, z), "fender support", trim)
    fill((-2, 0, 6), (2, 0, 7), "front deck", trim)
    fill((-2, 1, 6), (2, 1, 6), "front cowl", paint)
    fill((-1, 1, 3), (1, 1, 4), "handlebar support", paint)
    fill((-4, 0, 8), (4, 0, 8), "front bumper", trim)
    fill((-4, 0, -8), (4, 0, -8), "rear bumper", trim)
    fill((-2, 0, -6), (2, 0, -2), "engine bay floor", trim)
    # A sloped nose replaces blunt hood cubes; the fenders remain above the wheels.
    parts = list(blocks.values())
    bevel = {v for v, p in blocks.items() if p.name == "wheel fender" and abs(v[0]) == 4}
    parts = [p for p in parts if p.origin not in bevel]
    parts += [Placed(WEDGE, v, wedge_rotation((0, 1, 0), (1 if v[0] > 0 else -1, 0, 0)),
                     paint, name="fender bevel") for v in sorted(bevel)]
    parts += [Placed(WEDGE, (x, 1, 7), wedge_rotation((0, 1, 0), (0, 0, 1)), paint, name="sloped nose")
              for x in range(-2, 3)]
    cover = spec.get("engine_cover", True)
    if not isinstance(cover, bool):
        raise ValueError("engine_cover must be boolean")
    if cover:
        fill((-1, 4, -4), (1, 4, -2), "rear engine cover", paint)
        # Keep the built-in engine's upward RPS port open for transmission routing.
        blocks.pop((0, 4, -3))
        for side in (-1, 1):
            fill((side * 2, 2, -4), (side * 2, 3, -2), "engine bay side", paint)
            parts += [Placed(WEDGE, (side * 2, 4, z),
                             wedge_rotation((0, 1, 0), (side, 0, 0)), paint, name="rear cover bevel")
                      for z in range(-4, -1)]
        # Include the newly added cover cells without duplicating existing structure.
        known = {p.origin for p in parts}
        parts.extend(p for v, p in blocks.items() if v not in known)
    items = []
    wheel = spec.get("wheel_definition", "wheel_advanced_3_sus")
    if wheel != "wheel_advanced_3_sus":
        raise ValueError("utility_buggy currently supports wheel_advanced_3_sus; use chassis for other wheel envelopes")
    for axle, z in (("rear", -4), ("front", 4)):
        for side, sign in (("left", -1), ("right", 1)):
            items.append(_part(wheel, f"{axle} {side} wheel", [sign * 2, -1, z],
                               {"axle_axis": [sign, 0, 0], "wheel_reference_up": [0, 1, 0],
                                "wheel_forward": [0, 0, 1]},
                               spec.get("wheel_settings"), "454545"))
    items.append(_part("seat_saddle", "driver", [0, 1, 1],
                       {"seat_front": [0, 0, 1], "seat_up": [0, 1, 0]},
                       {"control_mode_0_label": "Steering", "control_mode_1_label": "Throttle",
                        "trigger_label": "Brake", "hotkey_0_label": "Ignition", "hotkey_1_label": "Headlights"}, trim))
    items.append(_part("engine", "diesel engine", [0, 1, -3], paint="7C858D"))
    for side, x in (("left", -2), ("right", 2)):
        items.append(_part("fluid_tank_small", f"{side} premade fuel tank", [x, 1, -1],
                           settings={"fluid_type": 1, "fluid_fill": 1}, paint="8A9299"))
        items.append(_part("searchlight_small_2", f"{side} headlight", [x, 2, 6],
                           {"light_forward": [0, 0, 1], "mount_normal": [0, -1, 0]}, paint="ECE7D6"))
        items.append(_part("small_light", f"{side} rear marker", [x, 1, -8], paint="FF3322"))
    items.append(_part("battery_small", "starter battery", [0, 1, 5], paint="454545"))
    items.append(_part("fluid_radiator", "engine radiator", [0, 1, -6], paint="89959D"))
    items[-1]["rotation"] = find_rotation([((0, 0, 1), (0, 1, 0)), ((1, 0, 0), (1, 0, 0))])
    extra = spec.get("components", [])
    if not isinstance(extra, list) or len(extra) > 200:
        raise ValueError("components must be a list of at most 200 objects")
    for item in extra:
        if not isinstance(item, dict) or "position" not in item:
            raise ValueError("each extra component needs a position in game metres")
        if "rotation" in item and "orientation" in item:
            raise ValueError("use orientation or rotation, not both")
        out = copy.deepcopy(item)
        out["position"] = _position(out["position"])
        if "orientation" in out:
            out["rotation"] = solve(out.get("definition", "01_block"), out.pop("orientation"))
        items.append(out)
    parts.extend(part(item) for item in items)
    _complete(parts)
    return _complete(apply_edits(parts, spec.get("edits", []), prefix="land-edit",
                                 placement_context={"vehicle_kind": "land"}))


def build_land(spec=None):
    from .land_build import build_chassis  # noqa: PLC0415
    if spec is None:
        spec = {}
    if not isinstance(spec, dict):
        raise ValueError("land vehicle spec must be an object")
    name = spec.get("preset", "utility_buggy")
    if name == "chassis":
        return build_chassis({k: v for k, v in spec.items() if k != "preset"})
    if name == "utility_buggy":
        return buggy(spec)
    if name == "utility_4x4":
        from .land_4x4 import build  # noqa: PLC0415
        return build(spec)
    if name == "humvee_4x4":
        from .land_humvee import build  # noqa: PLC0415
        return build(spec)
    raise ValueError(f"unknown land preset {name!r}; choose {', '.join(PRESETS)}")
