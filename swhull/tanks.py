"""Named block-built fluid enclosures with local ports and independently checked boundaries."""
import math
from itertools import product

from . import definitions
from .components import full_faces, mounted, owners
from .editing import color, vector
from .pieces import BLOCK, DIRS, IDENTITY, Placed, add, find_rotation, neg, sub
from .seal import MANUAL_DOORS, check

# Vehicle settings seen in saves: 0 water, 1 diesel, 2 jet fuel. Gases are intentionally
# excluded: compressed-gas presets need a different pressure/fill model.
FLUIDS = {"water": 0, "diesel": 1, "jet_fuel": 2}


def validate_config(spec):
    tanks = spec.get("tanks", [])
    if not isinstance(tanks, list):
        raise ValueError("tanks must be a list")
    names = set()
    for cfg in tanks:
        if not isinstance(cfg, dict) or not isinstance(cfg.get("name"), str) or not cfg["name"]:
            raise ValueError("each tank needs a nonempty name")
        if cfg["name"] in names:
            raise ValueError("tank names must be unique")
        names.add(cfg["name"])
        vector(cfg.get("position"), "tank.position", integer=False)
        size = vector(cfg.get("size"), "tank.size", integer=False)
        if any(v < 1.5 or not math.isclose(v * 4, round(v * 4), abs_tol=1e-8) for v in size):
            raise ValueError("tank.size uses outer dimensions in 0.25 m increments, at least 1.5 m per axis")
        if cfg.get("fluid", "diesel") not in FLUIDS:
            raise ValueError("tank fluid must be water, diesel or jet_fuel")
        fill = cfg.get("fill", 1)
        if isinstance(fill, bool) or not isinstance(fill, (int, float)) or not math.isfinite(fill) or not 0 <= fill <= 1:
            raise ValueError("tank.fill must be a fraction from 0 to 1")
        color(cfg.get("color", "7A5C2E"))
        if cfg.get("doors") or cfg.get("hatches"):
            raise ValueError("tank boundaries cannot contain ordinary doors or access openings")
        if math.prod(round(v * 4) for v in size) > 1000000:
            raise ValueError("tank exceeds the one-million-voxel construction budget")


def _load(d):
    piece = definitions.load(d)
    if piece is None:
        raise ValueError(f"custom tanks require definition {d!r}; install Stormworks or set SW_DEFINITIONS_DIR")
    return piece


def place(parts, info, spec):
    validate_config(spec)
    owner = owners(parts)
    info["tanks"], info["tank_reserved"] = [], set()
    for cfg in spec.get("tanks", []):
        name = cfg["name"]
        lo = tuple(round(v * 4) for v in cfg["position"])
        size = tuple(round(v * 4) for v in cfg["size"])
        hi = tuple(lo[i] + size[i] - 1 for i in range(3))
        volume = set(product(*(range(lo[i], hi[i] + 1) for i in range(3))))
        air = set(product(*(range(lo[i] + 1, hi[i]) for i in range(3))))
        walls = volume - air
        interior = info.get("interior")
        if interior and volume & interior.reserved:
            raise ValueError(f"tank '{name}' intersects a reserved access passage")
        if any(v in owner for v in air) or volume & info["tank_reserved"]:
            raise ValueError(f"tank '{name}' interior collides with existing structure/components")
        if any(v in owner and owner[v].piece.d != "01_block" for v in walls):
            raise ValueError(f"tank '{name}' boundary intersects a slope or component")
        if not any(v in owner or any(
                add(v, d) in owner and (sub(add(v, d), owner[add(v, d)].origin), neg(d))
                in full_faces(owner[add(v, d)].piece.d, owner[add(v, d)].Q) for d in DIRS) for v in walls):
            raise ValueError(f"tank '{name}' needs mounting contact with the vehicle")
        centre_x = lo[0] + size[0] // 2
        vent_z = hi[2] - 2
        pipe_q = find_rotation([((1, 0, 0), (0, 1, 0)), ((0, 1, 0), (1, 0, 0))])
        outlet_q = find_rotation([((0, -1, 0), (0, 0, -1)), ((1, 0, 0), (1, 0, 0))])
        outlet_pipe_q = find_rotation([((1, 0, 0), (0, 0, 1)), ((0, 1, 0), (0, 1, 0))])
        vent_q = ((1, 0, 0), (0, -1, 0), (0, 0, -1))
        kits = [
            Placed(_load("water_spawner"), (lo[0] + 1, lo[1] + 1, lo[2] + 1), IDENTITY,
                   "7A5C2E", f"tank:{name}:marker", f"{name} fluid marker",
                   {"fluid_type": FLUIDS[cfg.get("fluid", "diesel")], "fluid_fill": cfg.get("fill", 1),
                    "fluid_filter": 4294967295}),
            Placed(_load("fluid_intake"), (centre_x, lo[1] + 2, lo[2] + 1), outlet_q,
                   "7A5C2E", f"tank:{name}:outlet", f"{name} outlet"),
            Placed(_load("trans_block_straight"), (centre_x, lo[1] + 2, lo[2]), outlet_pipe_q,
                   "7A5C2E", f"tank:{name}:outlet_pipe", f"{name} outlet penetration"),
            Placed(_load("fluid_intake"), (centre_x, hi[1] - 1, vent_z), vent_q,
                   "7A5C2E", f"tank:{name}:vent_port", f"{name} vent port"),
            Placed(_load("trans_block_straight"), (centre_x, hi[1], vent_z), pipe_q,
                   "7A5C2E", f"tank:{name}:vent_pipe", f"{name} vent penetration"),
            Placed(_load("relief_valve_gas"), (centre_x, hi[1] + 1, vent_z), IDENTITY,
                   "7A5C2E", f"tank:{name}:vent", f"{name} gas relief"),
        ]
        replace = {kits[2].origin, kits[4].origin}
        if add(kits[2].origin, (0, 0, -1)) in owner or add(kits[5].origin, (0, 1, 0)) in owner:
            raise ValueError(f"tank '{name}' external outlet/vent connections are obstructed")
        kit_cells = set()
        for p in kits:
            cells = set(p.voxels())
            if cells & kit_cells or any(v in owner and v not in replace for v in cells):
                raise ValueError(f"tank '{name}' fluid kit does not fit without collisions")
            if p.piece.d not in ("relief_valve_gas", "trans_block_straight") and not cells <= air:
                raise ValueError(f"tank '{name}' is too small for the fluid kit")
            kit_cells.update(cells)
        new_walls = [Placed(BLOCK, v, color=cfg.get("color", "7A5C2E"),
                            uid=f"tank:{name}:wall:{v}", name=f"{name} wall")
                     for v in sorted(walls - replace) if v not in owner]
        retained = [p for p in parts if p.origin not in replace]
        trial = [*retained, *new_walls, *kits]
        trial_owner = owners(trial)
        for p in kits:
            without_self = {v: owner_p for v, owner_p in trial_owner.items() if owner_p is not p}
            if not mounted(p, without_self):
                raise ValueError(f"tank '{name}' part '{p.name}' has no mounting contact")
        parts[:] = trial
        owner = trial_owner
        free = air - kit_cells
        if not free:
            raise ValueError(f"tank '{name}' has no usable interior volume")
        info["tank_reserved"].update(volume | kit_cells)
        info["tanks"].append({"name": name, "seed": min(free),
                              "bounds": [tuple(n + 1 for n in lo), tuple(n - 1 for n in hi)],
                              "usable_litres": len(free) / 64 * 1000,
                              "fluid": cfg.get("fluid", "diesel"), "fill": cfg.get("fill", 1),
                              "outlet_connection": kits[2].origin,
                              "outlet_direction": (0, 0, -1),
                              "vent_connection": kits[5].origin, "vent_direction": (0, 1, 0),
                              "coordinates": "integer blocks, uncentred build frame",
                              "required_parts": [{"id": p.uid, "definition": p.piece.d,
                                                  "position": p.origin, "rotation": p.Q,
                                                  "settings": p.settings} for p in kits]})
    return parts


def verify(parts, info):
    results = []
    by_id = {p.uid: p for p in parts}
    occupied = {v for p in parts for v in p.voxels()}
    for tank in info.get("tanks", []):
        lo, hi = tank["bounds"]
        outer_lo, outer_hi = tuple(n - 1 for n in lo), tuple(n + 1 for n in hi)
        ordinary_access = [p.uid for p in parts if (
            p.piece.d in MANUAL_DOORS or p.piece.d.startswith(("door_", "hatch")))
            and any(all(outer_lo[i] <= v[i] <= outer_hi[i] for i in range(3))
                    and any(v[i] in (outer_lo[i], outer_hi[i]) for i in range(3)) for v in p.voxels())]
        air = set(product(*(range(lo[i], hi[i] + 1) for i in range(3)))) - occupied
        tank["usable_litres"] = len(air) / 64 * 1000
        missing = []
        for required in tank["required_parts"]:
            p = by_id.get(required["id"])
            if p is None or (p.piece.d, p.origin, p.Q, p.settings) != (
                    required["definition"], required["position"], required["rotation"], required["settings"]):
                missing.append(required["id"])
        if air:
            tank["seed"] = min(air)
            report = check(parts, [{"name": tank["name"], "position": tank["seed"]}],
                           containment=tank["bounds"])
        else:
            report = {"status": "indeterminate", "compartments": [], "reason": "no usable interior air"}
        if missing:
            report = {**report, "status": "indeterminate",
                      "reason": "required fluid kit changed or removed: " + ", ".join(missing)}
        if ordinary_access:
            report = {**report, "status": "indeterminate",
                      "reason": "ordinary doors/hatches are prohibited through tank boundaries"}
        public = {k: v for k, v in tank.items() if k != "required_parts"}
        results.append({**public, **report})
        if report["status"] != "sealed":
            info["warnings"].append(f"tank '{tank['name']}' is {report['status']}; export blocked until repaired")
    info["tank_validation"] = results


def ensure_valid(info):
    for result in (info or {}).get("tank_validation", []):
        if result["status"] != "sealed":
            paths = [r["escape_path"] for r in result.get("compartments", []) if r["escape_path"]]
            detail = f"; escape path in build blocks: {paths[0][:12]}" if paths else f"; {result.get('reason', 'unknown sealing geometry')}"
            raise ValueError(f"tank '{result['name']}' is {result['status']}; cannot export an invalid enclosure{detail}")
