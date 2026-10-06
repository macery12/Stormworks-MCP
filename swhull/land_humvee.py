"""Humvee-shaped road example with open door bays and an enclosed underfloor driveline."""
from itertools import product

from . import definitions
from .editing import apply_edits, color, identify, part
from .land_build import _part, _position
from .land_presets import _complete
from .orientation import solve
from .pieces import BLOCK, BY_NAME, Placed, WEDGE, find_rotation, wedge_rotation
from .routing import route, tree


def build(spec):
    allowed = {"preset", "bench", "color", "accent", "wheel_settings", "components", "edits"}
    if set(spec) - allowed:
        raise ValueError("humvee_4x4 has a fixed layout; use chassis for custom dimensions. Unknown fields: "
                         + ", ".join(sorted(set(spec) - allowed)))
    paint, trim = color(spec.get("color", "C5AF7A")), color(spec.get("accent", "343B3F"))
    items = []

    def component(d, name, pos, targets=None, settings=None, colour=None, q=None):
        data = _part(d, name, pos, targets, settings, colour or trim)
        if q is not None:
            data["rotation"] = q
        items.append(data)

    shaft_q = find_rotation([((0, 1, 0), (0, 0, 1)), ((1, 0, 0), (1, 0, 0))])
    engine_q = find_rotation([((0, 1, 0), (0, 0, -1)), ((1, 0, 0), (1, 0, 0))])
    for axle, z in (("rear", -7), ("front", 7)):
        for side, sign in (("left", -1), ("right", 1)):
            component("wheel_advanced_5_sus", f"{axle} {side} wheel", [sign, -2, z],
                      {"axle_axis": [sign, 0, 0], "wheel_reference_up": [0, 1, 0],
                       "wheel_forward": [0, 0, 1]}, spec.get("wheel_settings"), "303030")
    component("seat_racing", "driver", [-2, 0, 1], settings={
        "control_mode_0_label": "Steering", "control_mode_1_label": "Throttle",
        "trigger_label": "Brake", "hotkey_0_label": "Starter (hold)", "hotkey_1_label": "Lights",
        "hotkey_1": 1, "hotkey_2_label": "Reverse", "hotkey_2": 1})
    for name, x, z in (("front passenger", 2, 1), ("rear left passenger", -2, -3), ("rear right passenger", 2, -3)):
        component("seat_compact", name, [x, 0, z])
    # Turn the prebuilt engine so its shaft faces the clutch, instead of routing
    # up, around and down from an upright engine's roof-facing power outlet.
    component("engine", "diesel engine", [0, 0, 7], q=engine_q)
    component("torque_clutch", "clutch", [0, 0, 3], q=shaft_q)
    component("modular_engine_gearbox_1x1", "gearbox", [0, 0, 2], q=shaft_q)
    component("fluid_tank_medium", "premade diesel tank", [-2, -2, -9], q=shaft_q,
              settings={"fluid_type": 1, "fluid_fill": 1})
    component("battery_small", "starter battery", [2, 0, -8])
    radiator_q = find_rotation([((0, 0, 1), (0, 0, -1)), ((0, 1, 0), (0, 1, 0))])
    component("fluid_radiator", "engine radiator", [0, 1, 9], q=radiator_q)
    component("air_filter", "engine air intake", [0, 3, 5])
    exhaust_q = find_rotation([((0, -1, 0), (-1, 0, 0)), ((0, 0, 1), (0, 0, 1))])
    component("fluid_exhaust", "engine exhaust", [3, 2, 6], q=exhaust_q)
    for side, x in (("left", -3), ("right", 3)):
        component("searchlight_small_2", f"{side} headlight", [x, 1, 10],
                  {"light_forward": [0, 0, 1], "mount_normal": [0, -1, 0]}, colour="ECE7D6")
        component("small_light", f"{side} tail light", [x, 0, -10], colour="FF3322")
    component("wheel_advanced_5", "rear spare tyre", [0, 1, -10],
              {"axle_axis": [0, 0, -1], "wheel_reference_up": [0, 1, 0]}, colour="303030")
    component("gate_function_small", "throttle limiter", [-1, -2, 2], settings={"property_text": "max(0,min(1,x))"})
    component("gate_function_small", "left steering inverter", [1, -2, 2], settings={"property_text": "-x"})
    for side, x in (("left", -2), ("right", 2)):
        component("window_angle_m_3x2x2", f"{side} windshield", [x, 4, 3], colour=paint,
                  q=((0, 0, 1), (0, 1, 0), (-1, 0, 0)))
    for side, x in (("left", -2), ("right", 2)):
        component("window_angle_m_3x2x2", f"{side} rear window", [x, 4, -8], colour=paint,
                  q=((0, 0, -1), (0, 1, 0), (1, 0, 0)))
        component("window_2x2", f"{side} quarter window", [-4 if side == "left" else 4, 4, -6], colour=paint)
    parts = identify([part(item, f"humvee:{i}") for i, item in enumerate(items)])
    by_name = {p.name: p for p in parts}

    def endpoint(name, label, typ, face_normal=None):
        p = by_name[name]
        data = definitions.metadata(p.piece.d)
        nodes = [n for n in data["logic_nodes"] if n["type"] == typ and n["label"] == label
                 and (face_normal is None or any(f["position"] == n["position"] and f["orientation"] == face_normal
                      and f["trans_type"] > 0 for f in data["attachment_surfaces"]))]
        if len(nodes) != 1:
            raise ValueError(f"installed port {name}/{label} unavailable")
        faces = [i for i, f in enumerate(data["attachment_surfaces"]) if f["trans_type"] > 0
                 and f["position"] == nodes[0]["position"] and (face_normal is None or f["orientation"] == face_normal)]
        if len(faces) != 1:
            raise ValueError(f"installed transmission face {name}/{label} ambiguous")
        return {"part_id": p.uid, "surface_index": faces[0]}

    reserved = set(product(range(-6, 7), range(0, 5), range(-4, 4)))
    # Reuse the old gearbox's shaft corridor; keep the occupant bays reserved.
    reserved.discard((0, 0, 1))
    extent = [[-3, -3, -10], [3, 3, 10]]
    # Chassis and floor channels use sealed pipe blocks; the small engine bay
    # hoses remain visible. No route is allowed through occupants or door bays.
    enclosed = set(product(range(-3, 4), range(-3, 0), range(-9, 11)))
    enclosed.update(product(range(-3, 4), (2,), (5,)))  # intake crosses the cowl
    requests = [
        ("engine shaft", endpoint("diesel engine", "RPS", 2), endpoint("clutch", "RPS B", 2)),
        ("clutch shaft", endpoint("clutch", "RPS A", 2), endpoint("gearbox", "RPS B", 2, 2)),
        ("coolant return", endpoint("diesel engine", "In Coolant", 3), endpoint("engine radiator", "Fluid A", 3)),
        ("coolant supply", endpoint("diesel engine", "Out Coolant", 3), endpoint("engine radiator", "Fluid B", 3)),
        ("fuel line", endpoint("diesel engine", "Fuel", 3), endpoint("premade diesel tank", "Stored Fluid", 3, 2)),
        ("exhaust pipe", endpoint("diesel engine", "Exhaust", 3), endpoint("engine exhaust", "Fluid", 3)),
        ("intake pipe", endpoint("diesel engine", "Air", 3), endpoint("engine air intake", "Air", 3)),
    ]
    for i, (name, a, b) in enumerate(requests):
        parts, _ = route(parts, a, b, extent=extent, reserved=reserved, enclosed_cells=enclosed,
                         prefix=f"humvee-pipe:{i}", name=name)
    wheel_faces = [endpoint("gearbox", "RPS A", 2, 3)]
    wheel_faces += [endpoint(f"{axle} {side} wheel", "RPS", 2)
                    for axle in ("front", "rear") for side in ("left", "right")]
    parts = tree(parts, wheel_faces, extent=extent, reserved=reserved, enclosed_cells=enclosed, prefix="humvee-shaft")
    for p in parts:
        if p.piece.d.startswith("trans_block_"):
            p.color = paint if p.origin[1] >= 0 else trim
    occupied = {v for p in parts for v in p.voxels()}
    structure = {}

    def fill(lo, hi, name, colour=paint, piece=BLOCK, q=None):
        for v in product(*(range(lo[i], hi[i] + 1) for i in range(3))):
            if v not in occupied:
                structure[v] = Placed(piece, v, q or ((1, 0, 0), (0, 1, 0), (0, 0, 1)), colour, name=name)

    fill((-3, -1, -9), (3, -1, 10), "cabin floor", trim)
    fill((-1, -2, -9), (1, -2, 10), "chassis rails", trim)
    fill((-1, -3, 2), (1, -3, 2), "controller mounting tray", trim)
    for side in (-1, 1):
        lo = hi = side * 4
        for z in (1, -3):
            fill((lo, -1, z - 1), (hi, -1, z + 1), "entry step", trim)
        xlo, xhi = sorted((side * 3, side * 5))
        for z in (-7, 7):
            fill((xlo, 2, z - 2), (xhi, 2, z + 2), "wheel arch crown")
        x = side * 4
        for z in (-5, -1):
            fill((x, 0, z), (x, 4, z), "cabin pillar")
        fill((x, -1, -9), (x, -1, 3), "door sill", trim)
        fill((x, 0, -9), (x, 2, -5), "rear quarter")
        fill((x, 3, -6), (x, 4, -6), "rear quarter pillar")
        fill((x, 3, -8), (x, 3, -8), "rear quarter corner backing")
        fill((x, 0, 5), (x, 0, 5), "front arch rear edge")
        fill((x, 0, 9), (x, 0, 9), "front arch front edge")
    fill((-4, 5, -8), (4, 5, 3), "low cabin roof")
    fill((-4, 0, -9), (4, 2, -9), "rear cabin wall")
    fill((-3, -1, -10), (3, -1, -10), "rear bumper", trim)
    fill((-4, -1, 11), (4, -1, 11), "front bumper", trim)
    fill((-3, 0, 4), (3, 1, 4), "firewall")
    fill((-3, 2, 5), (3, 2, 5), "windshield cowl")
    fill((-3, 2, 4), (3, 2, 4), "windshield lower frame")
    for x in (-4, 0, 4):
        fill((x, 4, 3), (x, 4, 3), "windshield frame", piece=WEDGE,
             q=wedge_rotation((0, 1, 0), (0, 0, 1)))
        fill((x, 3, 4), (x, 3, 4), "windshield frame", piece=WEDGE,
             q=wedge_rotation((0, 1, 0), (0, 0, 1)))
        fill((x, 1, 4), (x, 2, 4), "windshield pedestal")
        for y, z in ((4, -8), (3, -9)):
            fill((x, y, z), (x, y, z), "raked rear frame", piece=WEDGE,
                 q=wedge_rotation((0, 1, 0), (0, 0, -1)))
    fill((-3, 3, 6), (3, 3, 8), "low hood")
    # The front lip falls one block over two, instead of standing up as a tall
    # rectangular grille or using a stock hatch as an oversized hood.
    nose_q = find_rotation([((0, 1, 0), (0, 1, 0)), ((0, 0, -1), (0, 0, 1))])
    for x in range(-3, 4):
        structure[(x, 3, 9)] = Placed(BY_NAME["05_wedge_2"], (x, 3, 9), nose_q, paint, name="sloped hood nose")
    fill((-4, 0, 10), (4, 2, 10), "front fascia")
    for x in (-2, 0, 2):
        fill((x, 0, 10), (x, 1, 10), "recessed grille", trim)
    for x in (-3, 3):
        fill((x, 0, 5), (x, 2, 9), "hood side")
    for p in structure.values():
        if (p.name == "low cabin roof" and abs(p.origin[0]) == 4
                or p.name == "wheel arch crown" and abs(p.origin[0]) == 5):
            p.piece, p.Q = WEDGE, wedge_rotation((0, 1, 0), (1 if p.origin[0] > 0 else -1, 0, 0))
    parts.extend(structure.values())
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
        parts.append(part(data, f"humvee-extra:{i}"))
    return _complete(apply_edits(identify(parts), spec.get("edits", []), prefix="land-edit",
                                 placement_context={"vehicle_kind": "land"}))
