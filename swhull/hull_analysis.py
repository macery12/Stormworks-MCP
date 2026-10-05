"""Measured structural surfaces, slope choices and floor depths in explicit frames.

Editor footprints reserve cells; their boxes are not the material in those cells.
The convex polygons here describe the supported block/wedge/pyramid catalogue only.
"""
import math
from collections import Counter, defaultdict

import numpy as np

from .hull import VOX
from .pieces import (BY_NAME, DIRS, CONTAINS, Placed, add, apply, parse_r, with_mirror,
                     r_attr, split_mirror)
from .reference import xml_root
from .smooth import FACE, _catalogue, _face_bits, _transpose
from .vehicle import MISSING_R


def vertical_interval(part, x, z):
    """Exact material interval along a vertical ray through a convex structural piece."""
    verts = np.array([add(part.origin, apply(part.Q, v)) for v in part.piece.verts])
    centre = verts.mean(axis=0)
    lo, hi = -math.inf, math.inf
    for face in part.piece.faces:
        pts = verts[list(face)]
        normal = np.cross(pts[1] - pts[0], pts[2] - pts[0])
        if normal @ (pts.mean(axis=0) - centre) < 0:
            normal = -normal
        bound = float(normal @ pts[0] - normal[0] * x - normal[2] * z)
        if abs(normal[1]) < 1e-10:
            if bound < -1e-8:
                return None
        elif normal[1] > 0:
            hi = min(hi, bound / normal[1])
        else:
            lo = max(lo, bound / normal[1])
    return (float(lo), float(hi)) if hi - lo > 1e-8 else None


def _merged(intervals):
    result = []
    for lo, hi in sorted(intervals):
        if result and lo <= result[-1][1] + 1e-8:
            result[-1][1] = max(hi, result[-1][1])
        else:
            result.append([lo, hi])
    return [[round(lo, 5), round(hi, 5)] for lo, hi in result]


def block_choices(normal, limit=6):
    """Rank distinct plane families. A normal alone never selects pyramid vs inverse."""
    if (not isinstance(normal, (list, tuple)) or len(normal) != 3
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) for v in normal)):
        raise ValueError("normal must be three finite numbers in world x/y/z axes")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise ValueError("limit must be 1-20")
    vector = np.array(normal, dtype=float)
    size = np.linalg.norm(vector)
    if size < 1e-12:
        raise ValueError("normal must be nonzero")
    vector /= size
    families = {}
    for pl in _catalogue()["placements"]:
        key = tuple(round(float(v), 8) for v in pl["normal"])
        angle = math.degrees(math.acos(float(np.clip(vector @ pl["normal"], -1, 1))))
        row = families.setdefault(key, {"normal": key, "angle_error_degrees": round(angle, 3),
                                        "definitions": set(), "examples": {}})
        row["definitions"].add(pl["piece"].d)
        rotation, mirror = split_mirror(pl["Q"])
        row["examples"].setdefault(pl["piece"].d,
                                   {"rotation_r": r_attr(rotation), "mirror_flags": mirror,
                                    "footprint_offsets": pl["offs"].tolist(),
                                    "plane_offset_blocks": round(float(pl["normal"] @
                                                                       (pl["centre"][0] + pl["offs"][0])), 6)})
    for d in DIRS:
        angle = math.degrees(math.acos(float(np.clip(vector @ d, -1, 1))))
        families[d] = {"normal": d, "angle_error_degrees": round(angle, 3),
                       "definitions": {"01_block"}, "examples": {}}
    rows = sorted(families.values(), key=lambda r: (r["angle_error_degrees"], r["normal"]))[:limit]
    return {"target_normal": vector.tolist(),
            "choices": [{**r, "definitions": sorted(r["definitions"])} for r in rows],
            "selection_rules": [
                "One changing direction across a face: wedge; two changing directions: pyramid/inverse pair.",
                "Normal chooses angle only. Plane position and material side choose pyramid versus inverse.",
                "Examples are representative orientations at origin zero, not automatic placements; other rotations can have the same normal.",
                "Check the entire rotated footprint, colour, floor clearance and matching face coverage before placement.",
                "Flat plates and intentional chines stay crisp. Longer pieces need a consistent slope over their full run."]}


def structural_report(parts, stations=None, x=0):
    """Column material, open spaces and partial-face joints; never infer hull physics."""
    if isinstance(x, bool) or not isinstance(x, int):
        raise ValueError("x must be an integer block coordinate")
    structural = [p for p in parts if p.piece.d in BY_NAME]
    if not structural:
        raise ValueError("no supported structural blocks in this body")
    owner, columns, overlap_count = {}, defaultdict(list), 0
    for p in structural:
        seen_columns = set()
        for v in p.voxels():
            overlap_count += v in owner
            owner[v] = p
            seen_columns.add((v[0], v[2]))
        for column in seen_columns:
            columns[column].append(p)
    lo = [min(v[i] for v in owner) for i in range(3)]
    hi = [max(v[i] for v in owner) for i in range(3)]
    if stations is None:
        stations = sorted({lo[2] + round((hi[2] - lo[2]) * i / 8) for i in range(9)})
    if (not isinstance(stations, list) or not 1 <= len(stations) <= 64
            or any(isinstance(v, bool) or not isinstance(v, int) for v in stations)):
        raise ValueError("stations must be 1-64 integer z block coordinates")
    profiles = []
    for z in stations:
        material = _merged(interval for p in columns.get((x, z), ())
                           if (interval := vertical_interval(p, x, z)) is not None)
        spaces = [[a[1], b[0]] for a, b in zip(material, material[1:])]
        profiles.append({"z_blocks": z, "x_blocks": x, "material_y_blocks": material,
                         "gaps": [{"floor_surface_y_blocks": a, "ceiling_surface_y_blocks": b,
                                   "clear_height_m": round((b - a) / VOX, 5)} for a, b in spaces]})
    face_cache = {}

    def face(p, v, direction):
        key = (p.piece.d, p.Q, tuple(v[i] - p.origin[i] for i in range(3)), direction)
        if key not in face_cache:
            if p.piece.d == "01_block":
                face_cache[key] = FACE
            else:
                back = _transpose(p.Q)
                test = CONTAINS[p.piece.d]
                face_cache[key] = _face_bits(lambda pt: test(apply(back, pt)), key[2], direction)
        return face_cache[key]

    mismatches, checked, long_wedge_mismatches, examples = 0, 0, 0, []
    for v, p in owner.items():
        for direction in DIRS[::2]:
            n = add(v, direction)
            other = owner.get(n)
            if other is None or other is p or p.piece.d == other.piece.d == "01_block":
                continue
            a = face(p, v, direction)
            b = face(other, n, tuple(-c for c in direction))
            if a in (0, FACE) and b in (0, FACE):
                continue
            checked += 1
            if a != b:
                mismatches += 1
                if p.piece.d == "08_wedge_4" or other.piece.d == "08_wedge_4":
                    long_wedge_mismatches += 1
                if len(examples) < 12:
                    examples.append({"cell": v, "direction": direction,
                                     "definitions": [p.piece.d, other.piece.d],
                                     "different_face_samples": (a ^ b).bit_count()})
    return {"structural_part_count": len(structural), "bounds_blocks": [lo, hi],
            "part_counts": dict(Counter(p.piece.d for p in structural)),
            "footprint_overlap_count": overlap_count, "sections": profiles,
            "partial_joints": {"checked": checked, "mismatched": mismatches,
                               "long_wedge_mismatched": long_wedge_mismatches,
                               "examples": examples},
            "limitations": ["Material intervals are exact for supported convex structural pieces; other parts are excluded.",
                            "Floor surfaces use voxel coordinates; voxel layer y has its top at y+0.5.",
                            "Joint samples flag steps, including intentional edges; they are not a quality percentage or a seal test.",
                            "A gap is geometric space, not proof of a walkable room. Confirm access and fluid behavior in game."]}


def reference_structure(text, body_id=None):
    """Read only structural parts, keeping unrelated articulated bodies separate."""
    root = xml_root(text)
    bodies, excluded = {}, {}
    for body in root.findall("bodies/body"):
        bid = body.get("unique_id", "")
        if not bid or bid in bodies:
            raise ValueError("reference bodies need distinct unique_id values")
        parts, other = [], Counter()
        for c in body.findall("components/c"):
            d = c.get("d", "01_block")
            if d not in BY_NAME:
                other[d] += 1
                continue
            obj = c.find("o")
            if obj is None:
                raise ValueError(f"body {bid}: component has no object geometry")
            vp = obj.find("vp")
            pos = tuple(int(vp.get(a, "0")) if vp is not None else 0 for a in "xyz")
            rotation = parse_r(obj.get("r")) if "r" in obj.attrib else MISSING_R
            mirror = int(c.get("t", "0"))
            if not 0 <= mirror <= 7:
                raise ValueError("mirror flags must be 0..7")
            parts.append(Placed(BY_NAME[d], pos, with_mirror(rotation, mirror)))
        bodies[bid], excluded[bid] = parts, dict(other)
    if not bodies:
        raise ValueError("vehicle has no bodies")
    if body_id is None:
        body_id = max(bodies, key=lambda bid: len(bodies[bid]))
    if body_id not in bodies:
        raise ValueError(f"unknown body_id; choose from {', '.join(bodies)}")
    return bodies[body_id], {"body_id": body_id, "body_count": len(bodies),
                             "body_structural_counts": {bid: len(parts) for bid, parts in bodies.items()},
                             "excluded_definitions": excluded[body_id], "frame": "saved body-local blocks"}


def design_depths(info, stations):
    """Separate the outer hull depth, rim, keel and requested walking floors."""
    form, region, plan = info["form"], info["region"], info["interior"]
    floor_layers = {round(h * VOX) - 1 for h in ((info["spec"].get("interior") or {}).get("decks") or [])}
    rows = []
    for z in stations:
        if not 0 <= z < form.L:
            continue
        s = form.s(z)
        deck = form.deck(s) / VOX
        floors = []
        for y in sorted(floor_layers):
            xs = sorted(x for x, yy, zz in plan.blocks if yy == y and zz == z
                        and region.get((x, yy, zz)) == "hull")
            floor_top = (y + 1) / VOX
            floors.append({"height_above_keel_m": floor_top,
                           "drop_from_rim_m": round(deck - floor_top, 5),
                           "floor_plate_cells": len(xs),
                           "centreline_supported": (0, y, z) in plan.blocks,
                           "floor_width_m": round(len(xs) / VOX, 5)})
        rows.append({"z_from_transom_m": (z + 0.5) / VOX,
                     "local_keel_m": round(form.keel(s) / VOX, 5),
                     "rim_height_m": round(deck, 5), "floors": floors})
    return rows
