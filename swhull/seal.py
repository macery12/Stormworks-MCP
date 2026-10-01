"""Independent face-aware air connectivity on the finished vehicle.

Building-piece apertures use convex polygon clipping, not footprint occupancy or sampled
points. Runtime component surfaces are accepted only when their sealing shape is understood.
Unsupported geometry near the checked space produces indeterminate, never a confident pass.
"""
from collections import deque
from functools import lru_cache
from itertools import product

import numpy as np

from . import definitions
from .editing import bounds, vector
from .pieces import BY_NAME, DIRS, add, apply, dot, neg, sub

MANUAL_DOORS = {"door_manual", "door_manual_small", "door_manual_large", "door_manual_sliding_small", "hatch", "door"}
MAX_CELLS = 8000000
EPS = 1e-9


@lru_cache(maxsize=512)
def _planes(d, q):
    piece = BY_NAME[d]
    verts = [apply(q, v) for v in piece.verts]
    centre = tuple(sum(v[i] for v in verts) / len(verts) for i in range(3))
    planes = []
    for face in piece.faces:
        a = verts[face[0]]
        normal = None
        for i in range(1, len(face) - 1):
            u, v = sub(verts[face[i]], a), sub(verts[face[i + 1]], a)
            n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            if dot(n, n) > EPS:
                normal = n
                break
        if normal is None:
            continue
        if dot(normal, sub(centre, a)) > 0:
            normal = neg(normal)
        planes.append((normal, dot(normal, a)))
    return tuple(planes)


def _clip(poly, normal, offset):
    out = []
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        da, db = dot(normal, a) - offset, dot(normal, b) - offset
        if da <= EPS:
            out.append(a)
        if (da < -EPS and db > EPS) or (da > EPS and db < -EPS):
            t = da / (da - db)
            out.append(tuple(a[k] + (b[k] - a[k]) * t for k in range(3)))
    return out


def _area(poly, axis):
    if len(poly) < 3:
        return 0.0
    a, b = [i for i in range(3) if i != axis]
    return abs(sum(p[a] * poly[(i + 1) % len(poly)][b]
                   - poly[(i + 1) % len(poly)][a] * p[b] for i, p in enumerate(poly))) / 2


def _face(cell, direction):
    axis = next(i for i, n in enumerate(direction) if n)
    a, b = [i for i in range(3) if i != axis]
    square = []
    for x, y in ((-.5, -.5), (.5, -.5), (.5, .5), (-.5, .5)):
        p = list(cell)
        p[axis] += direction[axis] * .5
        p[a] += x
        p[b] += y
        square.append(tuple(p))
    return square, axis


def _section(square, parts):
    poly = square
    for p in parts:
        for normal, offset in _planes(p.piece.d, p.Q):
            poly = _clip(poly, normal, offset + dot(normal, p.origin))
            if not poly:
                return []
    return poly


def _fully_solid(p, cell):
    corners = [add(sub(cell, p.origin), v) for v in product((-.5, .5), repeat=3)]
    return all(dot(n, v) <= c + EPS for n, c in _planes(p.piece.d, p.Q) for v in corners)


class Geometry:
    def __init__(self, parts, door_state):
        if door_state not in ("closed", "open"):
            raise ValueError("door_state must be closed or open")
        self.solid, self.partial, self.barriers, self.unknown = set(), {}, set(), {}
        self.global_unknown = set()
        self.footprint = {v for p in parts for v in p.voxels()}
        self.portal_cache = {}
        for p in parts:
            if p.piece.d in BY_NAME:
                for cell in p.voxels():
                    if p.piece.d == "01_block" or _fully_solid(p, cell):
                        self.solid.add(cell)
                    else:
                        if cell in self.partial:
                            self.unknown[cell] = "overlapping slope geometry"
                        self.partial[cell] = p
                continue
            data = definitions.metadata(p.piece.d)
            if data is None:
                self.global_unknown.add(p.piece.d)
                continue
            voxels = {tuple(v["position"]): v for v in data["voxels"]}
            dynamic = {v for v, cfg in voxels.items() if cfg["flags"] & 4}
            unsupported = any(s["shape"] != 1 for s in data["sealing_surfaces"])
            if dynamic and p.piece.d not in MANUAL_DOORS:
                unsupported = True
            if unsupported:
                self.unknown.update({v: p.piece.d for v in p.voxels()})
            for surface in data["sealing_surfaces"]:
                if surface["shape"] != 1 or not 0 <= surface["orientation"] < 6:
                    continue
                if door_state == "open" and p.piece.d in MANUAL_DOORS and tuple(surface["position"]) in dynamic:
                    continue
                cell = add(p.origin, apply(p.Q, surface["position"]))
                direction = apply(p.Q, DIRS[surface["orientation"]])
                self.barriers.add((cell, direction))
            if door_state == "closed" and p.piece.d in MANUAL_DOORS:
                # Known door cells close their plane. The open check removes only the leaf.
                self.solid.update(add(p.origin, apply(p.Q, v)) for v in dynamic)

    def passable(self, cell, direction):
        neighbour = add(cell, direction)
        if neighbour in self.solid or (cell, direction) in self.barriers or (neighbour, neg(direction)) in self.barriers:
            return False
        a, b = self.partial.get(cell), self.partial.get(neighbour)
        if a is None and b is None:
            return True
        axis = next(i for i, n in enumerate(direction) if n)
        lower = cell if direction[axis] > 0 else neighbour
        key = (lower, axis)
        if key in self.portal_cache:
            return self.portal_cache[key]
        square, axis = _face(cell, direction)
        area_a = _area(_section(square, [a]), axis) if a else 0
        area_b = _area(_section(square, [b]), axis) if b else 0
        overlap = _area(_section(square, [a, b]), axis) if a and b else 0
        result = area_a + area_b - overlap < 1 - EPS
        self.portal_cache[key] = result
        return result


def auto_seeds(parts, info):
    occupied = {v for p in parts for v in p.voxels()}
    seeds = []
    for room in info["interior"].rooms:
        candidates = room.air - occupied
        if candidates:
            centre = room.centre()
            v = min(candidates, key=lambda v: (sum((v[i] - centre[i]) ** 2 for i in range(3)), v))
            seeds.append({"name": room.name, "position": v})
    if not seeds:
        candidates = {v for v, tag in info["region"].items() if tag == "hull"} - occupied
        if candidates:
            seeds.append({"name": "hull", "position": min(candidates, key=lambda v: (v[1], v[2], v[0]))})
    return seeds


def check(parts, seeds, door_state="closed", max_cells=MAX_CELLS, containment=None):
    if not seeds:
        return {"status": "indeterminate", "compartments": [], "reason": "no interior seeds; provide seed positions"}
    parsed = []
    for i, seed in enumerate(seeds):
        if isinstance(seed, dict):
            parsed.append({"name": str(seed.get("name", f"space {i + 1}")),
                           "position": vector(seed.get("position"), "seed")})
        else:
            parsed.append({"name": f"space {i + 1}", "position": vector(seed, "seed")})
    geometry = Geometry(parts, door_state)
    extent = geometry.footprint | {s["position"] for s in parsed}
    lo = tuple(min(v[i] for v in extent) - 1 for i in range(3))
    hi = tuple(max(v[i] for v in extent) + 1 for i in range(3))
    allowed = bounds(containment) if containment is not None else None
    if allowed:
        lo = tuple(n - 1 for n in allowed[0])
        hi = tuple(n + 1 for n in allowed[1])
    size = tuple(hi[i] - lo[i] + 1 for i in range(3))
    count = int(np.prod(size))
    if count > max_cells:
        return {"status": "indeterminate", "compartments": [], "reason":
                f"check needs {count} cells, above the {max_cells} cell budget; check a smaller draft"}
    strides = (size[1] * size[2], size[2], 1)

    def index(v):
        return sum((v[i] - lo[i]) * strides[i] for i in range(3))

    def position(n):
        x, rem = divmod(n, strides[0])
        y, z = divmod(rem, strides[1])
        return (x + lo[0], y + lo[1], z + lo[2])

    visited = np.zeros(count, dtype=np.int32)
    parents = np.full(count, -1, dtype=np.int32)
    groups, results = [], []
    for seed in parsed:
        start = seed["position"]
        if allowed and not all(allowed[0][i] <= start[i] <= allowed[1][i] for i in range(3)):
            raise ValueError("seed must be inside the containment bounds")
        if start in geometry.solid:
            raise ValueError(f"seed '{seed['name']}' is inside solid material")
        start_index = index(start)
        existing = int(visited[start_index])
        if existing:
            group = groups[existing - 1]
        else:
            group_id = len(groups) + 1
            queue = deque([start_index])
            visited[start_index] = group_id
            unknown, exit_index, air = set(geometry.global_unknown), None, 0
            while queue:
                n = queue.popleft()
                cell = position(n)
                air += 1
                if cell in geometry.unknown:
                    unknown.add(geometry.unknown[cell])
                if exit_index is None and any(cell[i] in (lo[i], hi[i]) for i in range(3)):
                    exit_index = n
                    if allowed:
                        break
                for direction in DIRS:
                    neighbour = add(cell, direction)
                    if neighbour in geometry.unknown:
                        unknown.add(geometry.unknown[neighbour])
                    if any(neighbour[i] < lo[i] or neighbour[i] > hi[i] for i in range(3)):
                        continue
                    nn = n + sum(direction[i] * strides[i] for i in range(3))
                    if not visited[nn] and geometry.passable(cell, direction):
                        visited[nn] = group_id
                        parents[nn] = n
                        queue.append(nn)
            path = []
            if exit_index is not None:
                n = exit_index
                while n >= 0:
                    path.append(position(n))
                    n = int(parents[n])
                path.reverse()
            group = {"status": "indeterminate" if unknown else "leaking" if path else "sealed",
                     "unknown_geometry": sorted(unknown), "escape_path": path,
                     "escape_path_start": seed["name"], "reachable_air_cells": air, "connected": []}
            groups.append(group)
        group["connected"].append(seed["name"])
        results.append({"name": seed["name"], "seed": start, "group": group})
    rows = [{**{k: v for k, v in r.items() if k != "group"}, **r["group"]} for r in results]
    status = ("leaking" if any(r["status"] == "leaking" for r in rows) else
              "indeterminate" if any(r["status"] == "indeterminate" for r in rows) else "sealed")
    return {"status": status, "door_state": door_state, "compartments": rows,
            "method": "finished-geometry face connectivity; exact building-piece aperture clipping",
            "verification": "geometric validation; confirm game compartment behavior in Stormworks"}
