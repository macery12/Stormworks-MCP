"""Original compact utility 4x4: prebuilt diesel, radiator, actual doors and connected systems."""
from itertools import product

from . import definitions
from .components import validate_placement
from .editing import apply_edits, color, identify, part
from .land_build import _part, _position
from .orientation import solve
from .pieces import BLOCK, BY_NAME, Placed, WEDGE, find_rotation, wedge_rotation, with_mirror
from .routing import route, tree


def build(spec):
    allowed = {"preset", "bench", "color", "accent", "wheel_settings", "components", "edits"}
    if set(spec) - allowed:
        raise ValueError("utility_4x4 has a fixed layout; use chassis for custom dimensions. Unknown fields: "
                         + ", ".join(sorted(set(spec) - allowed)))
    paint, trim = color(spec.get("color", "C5AF7A")), color(spec.get("accent", "343B3F"))
    items = []

    def component(d, name, pos, targets=None, settings=None, colour="687681"):
        items.append(_part(d, name, pos, targets, settings, colour))

    for axle, z in (("rear", -8), ("front", 8)):
        for side, sign in (("left", -1), ("right", 1)):
            component("wheel_advanced_5_sus", f"{axle} {side} wheel", [sign * 3, -1, z],
                      {"axle_axis": [sign, 0, 0], "wheel_reference_up": [0, 1, 0],
                       "wheel_forward": [0, 0, 1]}, spec.get("wheel_settings"), "303030")
    component("seat_racing", "driver", [-2, 1, 2], settings={
        "control_mode_0_label": "Steering", "control_mode_1_label": "Throttle",
        "trigger_label": "Brake", "hotkey_0_label": "Starter (hold)", "hotkey_1_label": "Lights",
        "hotkey_1": 1, "hotkey_2_label": "Reverse", "hotkey_2": 1}, colour=trim)
    for name, x, z in (("front passenger", 2, 2), ("rear left passenger", -2, -4), ("rear right passenger", 2, -4)):
        component("seat_passenger", name, [x, 1, z], colour=trim)
    component("engine", "diesel engine", [0, 0, 9])
    q = find_rotation([((0, 1, 0), (0, 0, 1)), ((1, 0, 0), (1, 0, 0))])
    component("torque_clutch", "clutch", [0, 0, 5])
    items[-1]["rotation"] = q
    component("modular_engine_gearbox_1x1", "gearbox", [0, -2, 3])
    items[-1]["rotation"] = q
    component("fluid_tank_medium", "premade diesel tank", [-1, 1, -10], settings={"fluid_type": 1, "fluid_fill": 1})
    component("battery_small", "starter battery", [2, 1, -10], colour=trim)
    component("fluid_radiator", "engine radiator", [0, 1, 12])
    component("air_filter", "engine air intake", [0, 2, 11])
    items[-1]["rotation"] = q  # Intake face -z, directly facing the engine's air outlet.
    component("fluid_exhaust", "engine exhaust", [3, 1, 11])
    for side, x in (("left", -3), ("right", 3)):
        component("searchlight_small_2", f"{side} headlight", [x, 1, 13],
                  {"light_forward": [0, 0, 1], "mount_normal": [0, -1, 0]}, colour="ECE7D6")
        component("small_light", f"{side} tail light", [x, 1, -11], colour="FF3322")
    component("gate_function_small", "throttle limiter", [-1, -1, 4], settings={"property_text": "max(0,min(1,x))"})
    component("gate_function_small", "left steering inverter", [1, -1, 4], settings={"property_text": "-x"})
    for side, x in (("left", -4), ("right", 4)):
        for row, z in (("front", 0), ("rear", -6)):
            component("door_manual", f"{row} {side} entry", [x, 4, z],
                      {"door_normal": [-1, 0, 0], "door_up": [0, 1, 0],
                       "door_side": [0, 0, 1]}, colour=paint)
    for side, x in (("left", -2), ("right", 2)):
        component("window_angle_xl_3x4x4", f"{side} raked windshield", [x, 4, 6], colour="687681")
        items[-1]["rotation"] = ((0, 0, 1), (0, 1, 0), (-1, 0, 0))
    component("door_manual_large", "hood service panel", [0, 4, 10],
              {"door_normal": [0, 1, 0], "door_side": [1, 0, 0], "door_up": [0, 0, -1]}, colour=paint)
    parts = identify([part(item, f"4x4:{i}") for i, item in enumerate(items)])
    for p in parts:
        # The installed sliding frame's painted pocket face points along +x,
        # opposite its door_normal. Point that face out of the cabin on both sides.
        if p.name.endswith("left entry"):
            p.Q = with_mirror(p.Q, 1)
    by_name = {p.name: p for p in parts}

    def endpoint(name, label, typ, *, face_normal=None):
        p = by_name[name]
        data = definitions.metadata(p.piece.d)
        nodes = [n for n in data["logic_nodes"] if n["type"] == typ and n["label"] == label
                 and (face_normal is None or any(f["position"] == n["position"] and f["orientation"] == face_normal
                      and f["trans_type"] > 0 for f in data["attachment_surfaces"]))]
        if len(nodes) != 1:
            raise ValueError(f"installed port {name}/{label} unavailable")
        node = nodes[0]
        faces = [i for i, f in enumerate(data["attachment_surfaces"]) if f["trans_type"] > 0
                 and f["position"] == node["position"] and (face_normal is None or f["orientation"] == face_normal)]
        if len(faces) != 1:
            raise ValueError(f"installed transmission face {name}/{label} ambiguous")
        return {"part_id": p.uid, "surface_index": faces[0]}

    # Reserve occupant space before routing; pipes use the central tunnel/underfloor and engine bay.
    reserved = set(product(range(-6, 7), range(1, 8), range(-8, 5)))
    reserved.update(v for p in parts if p.name == "hood service panel" for v in p.voxels())
    extent = [[-4, -2, -12], [4, 5, 14]]
    enclosed = set(product(range(-3, 4), (-1, 0), range(-11, 14)))
    enclosed.update(product(range(-1, 2), (-2,), (4, 5)))
    requests = [
        (endpoint("diesel engine", "RPS", 2), endpoint("clutch", "RPS B", 2)),
        (endpoint("clutch", "RPS A", 2), endpoint("gearbox", "RPS B", 2, face_normal=2)),
        (endpoint("diesel engine", "In Coolant", 3), endpoint("engine radiator", "Fluid B", 3)),
        (endpoint("diesel engine", "Out Coolant", 3), endpoint("engine radiator", "Fluid A", 3)),
        (endpoint("diesel engine", "Fuel", 3), endpoint("premade diesel tank", "Stored Fluid", 3, face_normal=2)),
        (endpoint("diesel engine", "Exhaust", 3), endpoint("engine exhaust", "Fluid", 3)),
    ]
    for i, (a, b) in enumerate(requests):
        parts, _ = route(parts, a, b, extent=extent, reserved=reserved, enclosed_cells=enclosed,
                         prefix=f"4x4-pipe:{i}", name="engine pipework")
    shaft_endpoints = [endpoint("gearbox", "RPS A", 2, face_normal=3)]
    shaft_endpoints += [endpoint(f"{axle} {side} wheel", "RPS", 2)
                       for axle in ("front", "rear") for side in ("left", "right")]
    parts = tree(parts, shaft_endpoints, extent=extent, reserved=reserved, enclosed_cells=enclosed, prefix="4x4-shaft")
    for p in parts:
        if p.piece.d.startswith("trans_block_"):
            p.color = trim
    occupied = {v for p in parts for v in p.voxels()}
    structure = {}

    def fill(lo, hi, name, colour=paint):
        for v in product(*(range(lo[i], hi[i] + 1) for i in range(3))):
            if v not in occupied:
                structure[v] = Placed(BLOCK, v, color=colour, name=name)

    fill((-3, 0, -11), (3, 0, 13), "chassis floor", trim)
    fill((-3, -1, -11), (3, -1, 13), "chassis rails", trim)
    fill((-1, -2, 4), (1, -2, 5), "controller mounting tray", trim)
    # Step boards line up with the doors' actual 0.75 m openings, between the tyres.
    for side in (-1, 1):
        lo, hi = sorted((side * 4, side * 6))
        for z in (2, -4):
            fill((lo, 0, z - 1), (hi, 0, z + 1), "entry step", trim)
        for z in (-8, 8):
            lo, hi = sorted((side * 3, side * 6))
            fill((lo, 2, z - 2), (hi, 2, z + 2), "wheel fender")
    fill((-4, 7, -8), (4, 7, 4), "low cabin roof")
    fill((-4, 1, -8), (4, 6, -8), "rear cabin wall")
    fill((-4, 1, 5), (4, 2, 5), "lower firewall")
    fill((-4, 0, 13), (4, 0, 13), "front bumper", trim)
    fill((-4, 0, -12), (4, 0, -12), "rear bumper", trim)
    fill((-3, 4, 8), (3, 4, 12), "hood surround")
    for x in (-3, 3):
        fill((x, 1, 8), (x, 3, 12), "hood side")
    fill((-2, 1, 13), (2, 2, 13), "radiator grille", trim)
    for y, z in ((3, 7), (4, 6), (5, 5), (6, 4)):
        for x in (-4, 0, 4):
            fill((x, y, z - 1), (x, y, z), "windshield pillar")
    # Close door-frame/roof edges, while preserving the moving leaf and full entry opening.
    for x in (-4, 4):
        fill((x, 0, -8), (x, 0, 4), "door sill", trim)
        fill((x, 1, 4), (x, 6, 4), "front cabin pillar")
    parts.extend(structure.values())
    # Bevel the outer fender edge instead of making a tall slab above each wheel.
    for p in parts:
        if p.name == "wheel fender" and abs(p.origin[0]) == 6:
            p.piece, p.Q = WEDGE, wedge_rotation((0, 1, 0), (1 if p.origin[0] > 0 else -1, 0, 0))
        elif p.name == "windshield pillar" and p.origin[1] + p.origin[2] == 10:
            p.piece, p.Q = WEDGE, wedge_rotation((0, 1, 0), (0, 0, 1))
        elif p.name == "low cabin roof" and abs(p.origin[0]) == 4:
            p.piece, p.Q = WEDGE, wedge_rotation((0, 1, 0), (1 if p.origin[0] > 0 else -1, 0, 0))
    extra = spec.get("components", [])
    if not isinstance(extra, list) or len(extra) > 200:
        raise ValueError("components must be a list of at most 200 objects")
    for i, cfg in enumerate(extra):
        if not isinstance(cfg, dict) or "position" not in cfg:
            raise ValueError("each extra component needs position in metres")
        data = {**cfg, "position": _position(cfg["position"])}
        if "orientation" in data:
            if "rotation" in data:
                raise ValueError("use orientation or rotation, not both")
            data["rotation"] = solve(data.get("definition", "01_block"), data.pop("orientation"))
        parts.append(part(data, f"4x4-extra:{i}"))
    parts = apply_edits(parts, spec.get("edits", []), prefix="land-edit", placement_context={"vehicle_kind": "land"})
    owner = {}
    for p in parts:
        for v in p.voxels():
            if v in owner:
                raise ValueError(f"4x4 overlap at {v}: {p.name} / {owner[v].name}")
            owner[v] = p
    for p in parts:
        if p.piece.d not in BY_NAME:
            validate_placement(p, {"vehicle_kind": "land"}, {v: q for v, q in owner.items() if q is not p})
    return identify(parts)
