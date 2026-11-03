"""Read-only physics estimates for any vehicle: mass, flotation, lift and thrust.

Everything here is a static calculation from the vehicle's parts and the base-game constants in
game_constants.py; nothing is simulated and nothing is written. Coordinates are the draft or
vehicle grid in metres: x across, +y up, +z forward (bow). Bodies share one grid, so a
multi-body vehicle is measured at its editor rest pose.
"""
import math
from collections import defaultdict, deque

import numpy as np

from . import definitions
from .game_constants import (BLOCK_METRES, CELL_LITRES, CELL_M3, FLUID_MASS_PER_LITRE, GAME_CONSTANTS,
                             PROVISIONAL)
from .pieces import BY_NAME, DIRS, add

C = GAME_CONSTANTS
FLUIDS = {0: "water", 1: "diesel", 2: "jet fuel", 3: "air", 4: "exhaust", 5: "oil", 6: "sea water"}
MAX_CELLS = 4_000_000
AERO_SURFACES = ("wing_", "control_surface", "control_fin", "rudder_surface")
LIFT_SCOPE = ("Counts wing and control-surface parts only. The game also gives block surfaces lift and drag "
              "(lift_force applies to every surface), so wings built from blocks are not included and real "
              "lift can be much higher.")
THRUSTERS = ("propeller", "aircraft_propeller", "large_propeller", "giga_prop_small", "azimuth_thruster",
             "tail_rotor", "heavy_rotor", "huge_rotor", "large_rotor", "rotor_coaxial", "fan_")
UNRATED_THRUST = ("jet_engine", "solid_rocket", "liquid_rocket", "rcs_thruster", "water_jet")


def buoyancy_mass(mass):
    """The mass the game floats, in kg of water: mass x (multiplier + modifier x ramp)."""
    ramp = min(max(mass - C["buoyancy_mass_modifier_lower"], 0.0) / C["buoyancy_mass_modifier_upper"], 1.0)
    return mass * (C["buoyancy_mass_multiplier"] + C["buoyancy_mass_modifier"] * ramp ** C["buoyancy_mass_modifier_pow"])


# --- geometry -------------------------------------------------------------------------------

def _piece_volume(piece):
    """Exact volume of a convex building piece, in blocks."""
    verts = np.array(piece.verts, dtype=float)
    centre = verts.mean(axis=0)
    total = 0.0
    for face in piece.faces:
        pts = verts[list(face)]
        normal = np.zeros(3)
        for i in range(len(pts)):
            normal += np.cross(pts[i], pts[(i + 1) % len(pts)])
        area = np.linalg.norm(normal) / 2
        if area < 1e-12:
            continue
        unit = normal / np.linalg.norm(normal)
        total += area * abs(np.dot(unit, pts[0] - centre)) / 3
    return total


_VOLUMES = {}


def piece_volume(d):
    if d not in _VOLUMES:
        _VOLUMES[d] = _piece_volume(BY_NAME[d])
    return _VOLUMES[d]


def _offsets(n):
    # Uneven per-axis nudges keep sample points off the 45-degree planes of slope pieces.
    axis = (np.arange(n) + 0.5) / n - 0.5
    grid = np.array(np.meshgrid(axis, axis, axis, indexing="ij")).reshape(3, -1).T
    return grid + np.array([0.0113, 0.0071, 0.0037]) / n


def _exterior(geometry, lo, hi):
    """Cells the outside water reaches, flooding from the bounding shell through open faces."""
    size = tuple(hi[i] - lo[i] + 1 for i in range(3))
    if size[0] * size[1] * size[2] > MAX_CELLS:
        raise ValueError(f"vehicle spans {size[0] * size[1] * size[2]} cells, above the {MAX_CELLS} cell budget")
    seen = {lo}
    queue = deque([lo])
    while queue:
        cell = queue.popleft()
        for d in DIRS:
            n = add(cell, d)
            if n in seen or any(n[i] < lo[i] or n[i] > hi[i] for i in range(3)):
                continue
            if geometry.passable(cell, d):
                seen.add(n)
                queue.append(n)
    return seen


def _compartments(geometry, cells):
    """Group enclosed cells into connected air spaces."""
    left, groups = set(cells), []
    while left:
        start = min(left)
        left.discard(start)
        group, queue = [start], deque([start])
        while queue:
            cell = queue.popleft()
            for d in DIRS:
                n = add(cell, d)
                if n in left and geometry.passable(cell, d):
                    left.discard(n)
                    group.append(n)
                    queue.append(n)
        groups.append(group)
    return groups


class Model:
    """Buoyant volume samples, masses and tanks of one vehicle at its rest pose."""

    def __init__(self, bodies):
        from .seal import Geometry, _planes  # noqa: PLC0415
        self.bodies = bodies
        parts = [p for _, body in bodies for p in body]
        if not parts:
            raise ValueError("vehicle has no parts")
        self.parts = parts
        self.body_of = {id(p): bid for bid, body in bodies for p in body}
        geometry = Geometry(parts, "closed")
        footprint = geometry.footprint
        lo = tuple(min(v[i] for v in footprint) - 1 for i in range(3))
        hi = tuple(max(v[i] for v in footprint) + 1 for i in range(3))
        exterior = _exterior(geometry, lo, hi)
        building = defaultdict(list)
        components = defaultdict(list)
        for p in parts:
            target = building if p.piece.d in BY_NAME else components
            for v in p.voxels():
                target[v].append(p)
        inside = {v for v in footprint if v not in exterior and v not in geometry.solid}
        # Empty cells inside the hull: anything in the bounding box the water cannot reach.
        empty = {(x, y, z) for x in range(lo[0], hi[0] + 1) for y in range(lo[1], hi[1] + 1)
                 for z in range(lo[2], hi[2] + 1)} - exterior - geometry.solid
        enclosed = empty | inside
        self.compartments = _compartments(geometry, enclosed)
        cells = sum(len(g) for g in self.compartments) + len(building) + len(components)
        n = 4 if cells <= 40_000 else 3 if cells <= 150_000 else 2
        offsets = _offsets(n)
        points, volumes = [], []

        def add_points(cell, mask, volume):
            if volume <= 0 or not mask.any():
                return
            pts = np.asarray(cell, float) + offsets[mask]
            points.append(pts)
            volumes.append(np.full(len(pts), volume / len(pts)))

        solid_in_cell = defaultdict(float)
        inside_mask = {}
        for p in {id(p): p for ps in building.values() for p in ps}.values():
            planes = _planes(p.piece.d, p.Q)
            normals = np.array([n_ for n_, _ in planes], float)
            limits = np.array([c for _, c in planes], float)
            masks = {}
            for v in p.voxels():
                if p.piece.d == "01_block":
                    masks[v] = np.ones(len(offsets), bool)
                    continue
                rel = np.asarray(v, float) - np.asarray(p.origin, float) + offsets
                masks[v] = np.all(rel @ normals.T <= limits + 1e-9, axis=1)
            count = sum(int(m.sum()) for m in masks.values())
            if not count:
                continue
            each = piece_volume(p.piece.d) / count
            for v, mask in masks.items():
                volume = each * int(mask.sum())
                add_points(v, mask, volume)
                solid_in_cell[v] += volume
                inside_mask[v] = inside_mask[v] | mask if v in inside_mask else mask
        self.solid_in_cell = solid_in_cell
        self.solid_m3 = sum(solid_in_cell.values()) * CELL_M3
        # Components outside sealed spaces displace their own voxels; inside, the air already counts.
        component_cells = [v for v in components if v in exterior and v not in building]
        for v in component_cells:
            add_points(v, np.ones(len(offsets), bool), 1.0)
        self.component_m3 = len(component_cells) * CELL_M3
        air = 0.0
        for group in self.compartments:
            for v in group:
                mask = ~inside_mask[v] if v in inside_mask else np.ones(len(offsets), bool)
                volume = max(0.0, 1.0 - solid_in_cell.get(v, 0.0))
                add_points(v, mask, volume)
                air += volume
        self.air_m3 = air * CELL_M3
        self.points = np.concatenate(points) * BLOCK_METRES if points else np.zeros((0, 3))
        self.volumes = np.concatenate(volumes) * CELL_M3 if volumes else np.zeros(0)
        self.sample_spacing = BLOCK_METRES / n
        self._masses()
        self._tanks(geometry, building, components)

    def _masses(self):
        rows = []
        for bid, body in self.bodies:
            total, moment, missing = 0.0, np.zeros(3), 0
            for p in body:
                if p.piece.d not in BY_NAME and definitions.metadata(p.piece.d) is None:
                    missing += 1
                cells = np.array(p.voxels(), float)
                total += p.piece.mass
                moment += p.piece.mass * cells.mean(axis=0)
            rows.append({"body_id": bid, "parts": len(body), "mass": round(total, 3),
                         "centre_of_mass_m": _round3(moment / total * BLOCK_METRES) if total else None,
                         "parts_without_definitions": missing})
        self.body_rows = rows

    def _tanks(self, geometry, building, components):
        tanks = []
        cell_group = {v: i for i, g in enumerate(self.compartments) for v in g}
        used = set()
        for p in self.parts:
            if p.piece.d == "water_spawner":
                # The spawner's base cell seals itself and often sits in the tank wall; its other
                # voxel reaches into the pocket. The tank is every sealed space a spawner voxel is in,
                # less the spawner's own sealed cell.
                voxels = set(p.voxels())
                groups = {cell_group[v] for v in voxels if v in cell_group} - used
                pockets = {g for g in groups if not set(self.compartments[g]) <= voxels} or groups
                if not pockets:
                    continue
                used |= groups
                cells = [v for g in sorted(pockets) for v in self.compartments[g]]
                litres = sum(max(0.0, 1.0 - self.solid_in_cell.get(v, 0.0)) for v in cells) * CELL_LITRES
                tanks.append({"name": p.name or f"custom tank {len(tanks) + 1}", "kind": "custom",
                              "body_id": self.body_of[id(p)], "litres": round(litres, 1),
                              "fluid": FLUIDS.get(definitions.spawner_fluid(p.settings), "unknown"),
                              "saved_fill": _fill(p.settings), "cells": cells})
            elif p.piece.d.startswith("fluid_tank_"):
                cells = p.voxels()
                fluid = int(float(p.settings.get("fluid_type", 0) or 0))
                tanks.append({"name": p.name or definitions.display_name(p.piece.d), "kind": "premade",
                              "body_id": self.body_of[id(p)], "litres": round(len(cells) * CELL_LITRES, 1),
                              "fluid": FLUIDS.get(fluid, "unknown"), "saved_fill": _fill(p.settings),
                              "cells": cells})
        names = defaultdict(int)
        for t in tanks:
            names[t["name"]] += 1
            if names[t["name"]] > 1:
                t["name"] = f"{t['name']} ({names[t['name']]})"
        self.tanks = tanks

    # --- mass for a scenario ----------------------------------------------------------------

    def loading(self, fills):
        """Per-body mass and centre including tank fluid at the given fill fractions."""
        mass = defaultdict(float)
        moment = defaultdict(lambda: np.zeros(3))
        for bid, body in self.bodies:
            for p in body:
                cells = np.array(p.voxels(), float)
                mass[bid] += p.piece.mass
                moment[bid] += p.piece.mass * cells.mean(axis=0) * BLOCK_METRES
        for t in self.tanks:
            fill = fills.get(t["name"], 0.0)
            if fill <= 0:
                continue
            fluid = t["litres"] * fill * FLUID_MASS_PER_LITRE
            # Fluid settles to the bottom of the tank: take the lowest cells up to the fill level.
            cells = sorted(t["cells"], key=lambda v: (v[1], v[0], v[2]))
            low = np.array(cells[:max(1, round(len(cells) * fill))], float)
            mass[t["body_id"]] += fluid
            moment[t["body_id"]] += fluid * low.mean(axis=0) * BLOCK_METRES
        return mass, moment

    def solve(self, fills):
        mass, moment = self.loading(fills)
        total = sum(mass.values())
        effective = {b: buoyancy_mass(m) for b, m in mass.items()}
        weight_kg = sum(effective.values())
        # Each body floats its own scaled mass; balance buoyancy about the scaled centre.
        g = sum(effective[b] / mass[b] * moment[b] for b in mass if mass[b]) / weight_kg
        com = sum(moment.values()) / total
        needed = weight_kg / C["water_density"]
        result = {"mass": round(total, 3), "buoyancy_mass_kg": round(weight_kg, 1),
                  "displacement_needed_m3": round(needed, 3), "centre_of_mass_m": _round3(com),
                  "tank_fill": {t["name"]: fills.get(t["name"], 0.0) for t in self.tanks}}
        capacity = float(self.volumes.sum())
        result["reserve_buoyancy_pct"] = round((capacity / needed - 1) * 100, 1) if needed else None
        if capacity < needed:
            return {**result, "floats": False,
                    "summary": f"sinks: needs {needed:.2f} m3 of displacement but has {capacity:.2f} m3"}
        return {**result, **_equilibrium(self.points - g, self.volumes, needed, g, self.sample_spacing)}


def _fill(settings):
    try:
        return min(1.0, max(0.0, float(settings.get("fluid_fill", 1))))
    except (TypeError, ValueError):
        return 1.0


def _round3(v):
    return [round(float(c), 3) for c in v]


# --- flotation --------------------------------------------------------------------------------

def _rotation(pitch, roll):
    """Pitch about x (bow up positive), then roll about z (+x side down positive)."""
    cp, sp, cr, sr = math.cos(pitch), math.sin(pitch), math.cos(roll), math.sin(roll)
    rx = np.array([[1, 0, 0], [0, cp, sp], [0, -sp, cp]])
    rz = np.array([[cr, sr, 0], [-sr, cr, 0], [0, 0, 1]])
    return rz @ rx


def _float_at(points, volumes, needed, pitch, roll, spacing):
    """Water height and centre of buoyancy (world frame, centre of gravity at the origin).

    Each sample stands for a slab `spacing` tall, so it goes under gradually as the water
    rises; that keeps volume and centre continuous in height and angle."""
    world = points @ _rotation(pitch, roll).T
    order = np.argsort(world[:, 1])
    y, v, p = world[order, 1], volumes[order], world[order]
    cum_v = np.concatenate([[0.0], np.cumsum(v)])
    cum_p = np.vstack([np.zeros(3), np.cumsum(p * v[:, None], axis=0)])
    half = spacing / 2

    def wet(h):
        a = int(np.searchsorted(y, h - half))
        b = int(np.searchsorted(y, h + half))
        share = np.clip((h - y[a:b]) / spacing + 0.5, 0.0, 1.0) * v[a:b]
        return cum_v[a] + share.sum(), cum_p[a] + (p[a:b] * share[:, None]).sum(axis=0)

    lo, hi = float(y[0]) - spacing, float(y[-1]) + spacing
    for _ in range(60):
        mid = (lo + hi) / 2
        if wet(mid)[0] < needed:
            lo = mid
        else:
            hi = mid
    height = (lo + hi) / 2
    volume, moment = wet(height)
    return height, moment / volume, world


def _equilibrium(points, volumes, needed, g, spacing):
    pitch = roll = 0.0
    step = math.radians(0.5)
    converged = False
    for _ in range(40):
        _, centre, _ = _float_at(points, volumes, needed, pitch, roll, spacing)
        residual = np.array([centre[0], centre[2]])
        if np.abs(residual).max() < 1e-5:
            converged = True
            break
        jac = np.zeros((2, 2))
        for j, (dp, dr) in enumerate(((step, 0.0), (0.0, step))):
            _, moved, _ = _float_at(points, volumes, needed, pitch + dp, roll + dr, spacing)
            jac[:, j] = (np.array([moved[0], moved[2]]) - residual) / step
        try:
            delta = -np.linalg.solve(jac, residual)
        except np.linalg.LinAlgError:
            break
        delta = np.clip(delta, -math.radians(10), math.radians(10))
        pitch = float(np.clip(pitch + delta[0], -math.radians(80), math.radians(80)))
        roll = float(np.clip(roll + delta[1], -math.radians(80), math.radians(80)))
    height, centre, world = _float_at(points, volumes, needed, pitch, roll, spacing)
    draft = height - float(world[:, 1].min())
    tilt = math.radians(3)
    _, rolled, _ = _float_at(points, volumes, needed, pitch, roll + tilt, spacing)
    _, pitched, _ = _float_at(points, volumes, needed, pitch + tilt, roll, spacing)
    gm_t = (rolled[0] - centre[0]) / math.sin(tilt)
    gm_l = -(pitched[2] - centre[2]) / math.sin(tilt)
    rot = _rotation(pitch, roll)
    cob_local = rot.T @ centre + g
    trim, heel = math.degrees(pitch), math.degrees(roll)
    gm_t, gm_l = float(gm_t), float(gm_l)
    stable = bool(gm_t > 0 and gm_l > 0)
    summary = (f"floats with {draft:.2f} m draft, trim {abs(trim):.1f} deg {'bow (+z) up' if trim >= 0 else 'bow (+z) down'}, "
               f"heel {abs(heel):.1f} deg toward {'+x' if heel >= 0 else '-x'}; "
               f"GM {gm_t:.2f} m across, {gm_l:.2f} m along"
               + ("" if stable else "; UNSTABLE: it would roll or pitch away from this position")
               + ("" if converged else "; equilibrium search did not settle, treat the angles as rough"))
    return {"floats": True, "converged": converged, "draft_m": round(draft, 3),
            "trim_deg": round(trim, 2), "heel_deg": round(heel, 2),
            "gm_transverse_m": round(gm_t, 3), "gm_longitudinal_m": round(gm_l, 3), "stable": stable,
            "centre_of_buoyancy_m": _round3(cob_local),
            "waterline": {"height_m": height, "rotation": rot.tolist(), "origin_m": _round3(g)},
            "summary": summary}


# --- lift and thrust --------------------------------------------------------------------------

def _thin_axis(d):
    fp = definitions.metadata(d)["footprint"]
    size = [max(v[i] for v in fp) - min(v[i] for v in fp) + 1 for i in range(3)]
    axis = [0, 0, 0]
    axis[size.index(min(size))] = 1
    return axis


def lift(parts, total_mass, com, airspeed=None, lift_coefficient=1.0):
    from .pieces import apply  # noqa: PLC0415
    rows, area_sum, moment = [], 0.0, np.zeros(3)
    for p in parts:
        if not p.piece.d.startswith(AERO_SURFACES):
            continue
        data = definitions.metadata(p.piece.d) or {}
        area = float(data.get("properties", {}).get("rudder_surface_area", 0) or 0) * BLOCK_METRES ** 2
        if area <= 0:
            continue
        normal = apply(p.Q, _thin_axis(p.piece.d))
        lifting = area * abs(normal[1])
        centre = np.array(p.voxels(), float).mean(axis=0) * BLOCK_METRES
        rows.append({"part_id": p.uid, "definition": p.piece.d, "area_m2": round(area, 3),
                     "horizontal_share": round(abs(normal[1]), 3), "centre_m": _round3(centre)})
        area_sum += lifting
        moment += lifting * centre
    if not rows:
        return None
    out = {"scope": LIFT_SCOPE, "surfaces": rows[:40], "surface_count": len(rows),
           "lifting_area_m2": round(area_sum, 3)}
    if area_sum <= 0:
        out["summary"] = "no horizontal wing or control-surface parts (all are vertical); block surfaces are not modelled"
        return out
    col = moment / area_sum
    weight = total_mass * C["gravity"]
    per_v2 = 0.5 * C["air_density"] * area_sum * lift_coefficient
    out.update({"centre_of_lift_m": _round3(col),
                "centre_of_lift_ahead_of_mass_m": round(float(col[2] - com[2]), 3),
                "lift_coefficient": lift_coefficient, "weight_n": round(weight, 1),
                "speed_for_lift_equal_weight_m_s": round(math.sqrt(weight / per_v2), 1)})
    if airspeed is not None:
        force = per_v2 * airspeed ** 2
        out.update({"airspeed_m_s": airspeed, "lift_n": round(force, 1), "lift_to_weight": round(force / weight, 3)})
    ahead = out["centre_of_lift_ahead_of_mass_m"]
    out["summary"] = (f"wing and control-surface parts alone ({area_sum:.2f} m2) would carry the weight near "
                      f"{out['speed_for_lift_equal_weight_m_s']} m/s at lift coefficient {lift_coefficient}; their "
                      f"centre of lift is {abs(ahead):.2f} m {'ahead of' if ahead >= 0 else 'behind'} the centre of "
                      "mass (provisional; block surfaces also lift in game and are not counted)")
    return out


def thrust(parts, total_mass):
    rated, unrated = [], defaultdict(int)
    for p in parts:
        d = p.piece.d
        if d.startswith(UNRATED_THRUST):
            unrated[d] += 1
            continue
        if not d.startswith(THRUSTERS):
            continue
        props = (definitions.metadata(d) or {}).get("properties", {})
        force = float(props.get("force_emitter_max_force", 0) or 0)
        if force > 0:
            rated.append({"part_id": p.uid, "definition": d, "max_force_n": force})
    if not rated and not unrated:
        return None
    weight = total_mass * C["gravity"]
    total = sum(r["max_force_n"] for r in rated)
    out = {"rated": rated[:40], "rated_count": len(rated), "max_force_n": total,
           "max_thrust_to_weight": round(total / weight, 3) if weight else None,
           "unrated": dict(unrated)}
    out["summary"] = (f"at most {total:.0f} N from {len(rated)} propeller/rotor part(s), thrust-to-weight up to "
                      f"{out['max_thrust_to_weight']}" if rated else "no part with a rated force")
    if unrated:
        out["summary"] += f"; thrust of {', '.join(sorted(unrated))} is not given by their definitions"
    return out


# --- report -----------------------------------------------------------------------------------

def analyze(bodies, tank_fill=None, airspeed=None, lift_coefficient=1.0):
    if lift_coefficient <= 0 or not math.isfinite(lift_coefficient):
        raise ValueError("lift_coefficient must be a positive number")
    if airspeed is not None and (airspeed < 0 or not math.isfinite(airspeed)):
        raise ValueError("airspeed must be zero or more metres per second")
    model = Model(bodies)
    names = {t["name"] for t in model.tanks}
    unknown = sorted(set(tank_fill or {}) - names)
    if unknown:
        raise ValueError(f"no tank named {unknown[0]!r}; tanks: {', '.join(sorted(names)) or 'none'}")
    if any(not 0 <= f <= 1 for f in (tank_fill or {}).values()):
        raise ValueError("tank_fill fractions must be from 0 to 1")
    saved = {t["name"]: t["saved_fill"] for t in model.tanks}
    scenarios = {"empty": {}, "full": {n: 1.0 for n in names}, "as_saved": saved}
    if tank_fill:
        scenarios["custom"] = {**saved, **tank_fill}
    flotation = {k: model.solve(fills) for k, fills in scenarios.items()}
    base = flotation["empty"]
    total_mass = base["mass"]
    com = np.array(base["centre_of_mass_m"])
    report = {
        "frame": "metres in the vehicle grid: x across, +y up, +z forward; bodies at their editor rest pose",
        "mass": {"empty_mass": total_mass, "centre_of_mass_empty_m": base["centre_of_mass_m"],
                 "bodies": model.body_rows},
        "volume": {"solid_m3": round(model.solid_m3, 3), "component_m3": round(model.component_m3, 3),
                   "enclosed_air_m3": round(model.air_m3, 3),
                   "total_buoyant_m3": round(float(model.volumes.sum()), 3),
                   "sealed_spaces": len(model.compartments)},
        "tanks": [{k: v for k, v in t.items() if k != "cells"} for t in model.tanks],
        "flotation": flotation,
        "lift": lift(model.parts, total_mass, com, airspeed, lift_coefficient),
        "thrust": thrust(model.parts, total_mass),
        "constants": {k: C[k] for k in ("gravity", "water_density", "air_density", "buoyancy_mass_multiplier",
                                        "buoyancy_mass_modifier", "buoyancy_mass_modifier_lower",
                                        "buoyancy_mass_modifier_upper", "lift_force")},
        "provisional": PROVISIONAL,
        "verification": "Static estimate from parts and base-game constants; only the game confirms it.",
    }
    return model, report


def notes(title, report):
    lines = [f"{title}: empty mass {report['mass']['empty_mass']}, "
             f"{len(report['mass']['bodies'])} body(ies), buoyant volume {report['volume']['total_buoyant_m3']} m3 "
             f"({report['volume']['enclosed_air_m3']} m3 sealed air)."]
    for t in report["tanks"]:
        lines.append(f"Tank {t['name']}: {t['kind']}, {t['litres']} L of {t['fluid']}, saved fill {t['saved_fill']:.0%}.")
    for name, row in report["flotation"].items():
        lines.append(f"{name}: mass {row['mass']}, {row['summary']}.")
    for key in ("lift", "thrust"):
        if report[key]:
            lines.append(f"{key.capitalize()}: {report[key]['summary']}.")
    lines.append("Provisional values: see `provisional`. Check the waterline in game before relying on it.")
    return "\n".join(lines)


def picture(model, report, title, scenario="as_saved"):
    """Side view with the waterline and the centres of mass, buoyancy and lift."""
    from .diagnostic_view import display  # noqa: PLC0415
    from .render import VEHICLE_RULER, render_view  # noqa: PLC0415
    row = report["flotation"][scenario]
    segments, labels = [], []

    def blocks(v):
        return tuple(c / BLOCK_METRES for c in v)

    def cross(v, colour, text):
        b = blocks(v)
        for axis in (1, 2):
            a, c = list(b), list(b)
            a[axis] -= 0.6
            c[axis] += 0.6
            segments.append({"start": display(a), "end": display(c), "color": colour})
        labels.append((display((b[0], b[1] + 1.5, b[2])), text))

    pts = model.points
    if row.get("floats"):
        water = row["waterline"]
        rot, g, h = np.array(water["rotation"]), np.array(water["origin_m"]), water["height_m"]
        x = float(row["centre_of_mass_m"][0])
        zs = (float(pts[:, 2].min()) - 1, float(pts[:, 2].max()) + 1)
        line = []
        for z in zs:
            # Solve rot[1] . (p - g) = h for y at this x and z.
            y = g[1] + (h - rot[1, 0] * (x - g[0]) - rot[1, 2] * (z - g[2])) / rot[1, 1]
            line.append(display(blocks((x, y, z))))
        segments.append({"start": line[0], "end": line[1], "color": "2E86DE", "label": f"waterline ({scenario})"})
        cross(row["centre_of_buoyancy_m"], "27AE60", "CoB")
    cross(row["centre_of_mass_m"], "E74C3C", "CoM")
    if report["lift"] and report["lift"].get("centre_of_lift_m"):
        cross(report["lift"]["centre_of_lift_m"], "F39C12", "CoL")
    return render_view(model.parts, yaw=0, pitch=0, title=f"{title}: {scenario} loading", labels=labels,
                       segments=segments, ruler=VEHICLE_RULER)
