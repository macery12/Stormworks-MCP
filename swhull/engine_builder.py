"""Modular engine builder: one complete coupled engine for edit_parts' "engine" operation.

Layouts follow the player's examples ("example_modular_engines", "claude_example" and the
compact 1x1 prefabs):

- One crankshaft piece per slice along the crank line, with a cylinder on each chosen side
  (bank). Cylinders touching in a row share their manifold network through the holes that
  face each other; separate banks are bridged by the shortest run of manifold parts. On a
  1x1 crank two neighbouring banks meet in the corner cell of the 3x3 cross-section, so a
  single corner manifold joins them (the player's compact ring).
- Drive belt with starters and alternators at the front, then optionally a flywheel and the
  clutch at the back; the clutch's RPS face is the power output.
- Air, fuel, exhaust and (by default) coolant manifolds on free cylinder holes, with their
  pipe faces left open for route_connections. When the holes run out, one empty crank slice
  next to the belt gives them room, as in the player's "even smaller engine prefab".

Nothing is wired: the player fits their own ECU. The result is checked with modular's
coupling model before it is returned.
"""
import math
from collections import deque

from . import definitions, modular
from .pieces import DIRS, ROTATIONS, Placed, add, apply, neg, sub

AXIS = (0, 0, 1)   # engine frame: the crank line runs +z from the drive belt to the clutch
UP = (0, 1, 0)
BANKS = {"top": (0, 1, 0), "right": (1, 0, 0), "bottom": (0, -1, 0), "left": (-1, 0, 0)}
DIRECTIONS = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0),
              "+z": (0, 0, 1), "-z": (0, 0, -1)}
SIZES = {
    1: {"crank": "modular_engine_crankshaft", "cylinder": "modular_engine_cylinder_straight",
        "cylinder_coupling": "cylinder_straight", "inline": "manifold_a",
        "belt": "modular_engine_drive_belt", "flywheel": "modular_engine_flywheel",
        "clutch": "modular_engine_clutch", "step": 1},
    3: {"crank": "modular_engine_crankshaft_3x3", "cylinder": "modular_engine_piston_3x3",
        "cylinder_coupling": "cylinder", "inline": "manifold_x",
        "belt": "modular_engine_power_manifold_3x3", "flywheel": "modular_engine_flywheel_3x3",
        "clutch": "modular_engine_clutch_3x3", "step": 3},
    5: {"crank": "modular_engine_crankshaft_5x5", "cylinder": "modular_engine_piston_5x5",
        "cylinder_coupling": "cylinder", "inline": "manifold_x",
        "belt": "modular_engine_power_manifold_5x5", "flywheel": "modular_engine_flywheel_5x5",
        "clutch": "modular_engine_clutch_5x5", "step": 5},
}
# The player's minimum starters per size.
MIN_STARTERS = {1: 1, 3: 2, 5: 3}
MAX_CYLINDERS = 64
FEEDS = (("air", "modular_engine_air_manifold"), ("fuel", "modular_engine_intake_manifold"),
         ("exhaust", "modular_engine_exhaust_manifold_straight"), ("coolant", "modular_engine_coolant_manifold"))
EXHAUST_CORNER = "modular_engine_exhaust_manifold_corner"
ENGINE_FIELDS = frozenset(("op", "size", "cylinders", "banks", "position", "output", "top", "starters",
                           "alternators", "flywheel", "coolant", "temperature_sensor", "air_rams",
                           "color", "name", "body"))


class _NoRoom(ValueError):
    pass


def _rotation(pairs):
    for Q in ROTATIONS:
        if all(apply(Q, local) == world for local, world in pairs):
            return Q
    return None


def _coupling(d, name):
    for _, n, _, pos, o in modular._local(d):
        if n == name:
            return pos, DIRS[o]
    raise KeyError(f"{d} has no coupling {name}")


def _pipe_faces(d):
    data = definitions.metadata(d) or {}
    return [(s["position"], DIRS[s["orientation"]]) for s in data.get("attachment_surfaces", [])
            if s["trans_type"] > 0 and 0 <= s["orientation"] < 6]


class _Layout:
    def __init__(self):
        self.rows = []      # (definition, origin, Q, label)
        self.cells = {}     # cell -> row index
        self.reserved = set()

    def footprint(self, d, origin, Q):
        piece = definitions.load(d)
        return Placed(piece, origin, Q).voxels()

    def free(self, cells):
        return all(c not in self.cells and c not in self.reserved for c in cells)

    def place(self, d, origin, Q, label, allow_reserved=False):
        cells = self.footprint(d, origin, Q)
        if any(c in self.cells or (c in self.reserved and not allow_reserved) for c in cells):
            raise _NoRoom(f"no room for the {label}")
        self.rows.append((d, origin, Q, label))
        for c in cells:
            self.cells[c] = len(self.rows) - 1
        return len(self.rows) - 1

    def attach(self, d, name, cell, normal, label, extra=()):
        """Place d so its coupling `name` faces the coupling at (cell, normal)."""
        pos, direction = _coupling(d, name)
        Q = _rotation([(direction, neg(normal)), *extra]) or _rotation([(direction, neg(normal))])
        origin = sub(add(cell, normal), apply(Q, pos))
        return self.place(d, origin, Q, label)

    def couplings(self, i):
        d, origin, Q, _ = self.rows[i]
        return [(t, n, add(origin, apply(Q, pos)), apply(Q, DIRS[o])) for t, n, _, pos, o in modular._local(d)]

    def pipes(self, i):
        d, origin, Q, _ = self.rows[i]
        return [(add(origin, apply(Q, pos)), apply(Q, n)) for pos, n in _pipe_faces(d)]


def _spec(op):
    if set(op) - ENGINE_FIELDS:
        raise ValueError(f"unknown engine field(s): {', '.join(sorted(set(op) - ENGINE_FIELDS))}")
    size = op.get("size", 1)
    if size not in SIZES:
        raise ValueError("engine size must be 1, 3 or 5 (the 1x1, 3x3 or 5x5 modular parts)")
    cylinders = op.get("cylinders", 4)
    if isinstance(cylinders, bool) or not isinstance(cylinders, int) or not 1 <= cylinders <= MAX_CYLINDERS:
        raise ValueError(f"cylinders must be a whole number from 1 to {MAX_CYLINDERS}")
    banks = op.get("banks", ["top"])
    if (not isinstance(banks, list) or not banks or len(set(banks)) != len(banks)
            or any(b not in BANKS for b in banks)):
        raise ValueError("banks must list distinct crank sides: top, right, bottom, left")
    if cylinders < len(banks):
        raise ValueError(f"{len(banks)} banks need at least {len(banks)} cylinders (one per bank)")
    out = {}
    for key, default in (("starters", MIN_STARTERS[size]), ("alternators", 0)):
        value = op.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{key} must be a whole number of 0 or more")
        out[key] = value
    for key, default in (("flywheel", False), ("coolant", True), ("temperature_sensor", False), ("air_rams", False)):
        value = op.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        out[key] = value
    output, top = op.get("output", "+z"), op.get("top", "+y")
    if output not in DIRECTIONS or top not in DIRECTIONS:
        raise ValueError("output and top must each be one of +x, -x, +y, -y, +z, -z")
    R = _rotation([(AXIS, DIRECTIONS[output]), (UP, DIRECTIONS[top])])
    if R is None:
        raise ValueError("output and top must be perpendicular directions")
    name = op.get("name", "engine")
    if not isinstance(name, str) or len(name) > 60:
        raise ValueError("name must be a short string")
    return {"size": size, "cylinders": cylinders, "banks": banks, "R": R, "name": name, **out}


def _layout(s, spacer):
    size, sz = s["size"], SIZES[s["size"]]
    L = _Layout()
    per_slice = len(s["banks"])
    slices = spacer + math.ceil(s["cylinders"] / per_slice)
    crank_q = _rotation([((0, 1, 0), AXIS), ((0, 0, 1), UP)])
    cranks = [L.place(sz["crank"], (0, 0, k * sz["step"]), crank_q, f"crankshaft {k + 1}") for k in range(slices)]
    # Cylinders, slice by slice, one per bank, in the order the banks are listed.
    cyl_pos, cyl_dir = _coupling(sz["cylinder"], sz["cylinder_coupling"])
    inline = _coupling(sz["cylinder"], sz["inline"])[1]
    bank_of, placed = {}, 0
    for k in range(spacer, slices):
        for bank in s["banks"]:
            if placed == s["cylinders"]:
                break
            u = BANKS[bank]
            socket = next(c for c in L.couplings(cranks[k]) if c[0].startswith("cylinder") and c[3] == u)
            i = L.attach(sz["cylinder"], sz["cylinder_coupling"], socket[2], u,
                         f"cylinder {placed + 1} ({bank})", [(inline, AXIS)])
            bank_of[i] = bank
            placed += 1
    # Drive belt at the front, then flywheel and clutch at the back.
    front = next(c for c in L.couplings(cranks[0]) if c[1] == "crankshaft_a")
    belt = L.attach(sz["belt"], "drive_belt", front[2], front[3], "drive belt", [((0, 0, 1), UP)])
    back = next(c for c in L.couplings(cranks[-1]) if c[1] == "crankshaft_b")
    if s["flywheel"]:
        fly = L.attach(sz["flywheel"], "crankshaft_a", back[2], back[3], "flywheel", [((0, 0, 1), UP)])
        back = next(c for c in L.couplings(fly) if c[1] == "crankshaft_b")
    clutch = L.attach(sz["clutch"], "clutch", back[2], back[3], "clutch", [((0, 0, 1), UP)])
    for cell, normal in L.pipes(clutch):
        L.reserved.add(add(cell, normal))
    # Starters and alternators on the belt sockets.
    sockets = sorted((c for c in L.couplings(belt) if c[0] == "belt"), key=lambda c: c[1])
    wanted = [("modular_engine_starter", "starter", f"starter {n + 1}") for n in range(s["starters"])]
    wanted += [("modular_engine_alternator", "alternator", f"alternator {n + 1}") for n in range(s["alternators"])]
    for d, name, label in wanted:
        for socket in sockets:
            try:
                L.attach(d, name, socket[2], socket[3], label, [((0, 0, 1), AXIS)])
                sockets.remove(socket)
                break
            except _NoRoom:
                continue
        else:
            raise ValueError(f"the {size}x{size} drive belt has no free socket for {label}; "
                             "use fewer starters and alternators")
    _bridge(L, bank_of, s["banks"])
    feeds = _feeds(L, s)
    if s["temperature_sensor"]:
        hole = next(iter(_holes(L)), None)
        if hole is None:
            raise _NoRoom("no free cylinder hole for the temperature sensor")
        L.attach("modular_engine_sensor_temperature", "cylinder", hole[0], hole[1], "temperature sensor")
    return L, feeds, clutch


def _holes(L):
    """Free manifold holes on cylinders: (cell, outward normal), in a stable order."""
    out = []
    for i, (d, _, _, _) in enumerate(L.rows):
        if d.startswith(modular.CYLINDERS):
            for t, _, cell, normal in L.couplings(i):
                if t == "manifold" and L.free([add(cell, normal)]):
                    out.append((cell, normal, i))
    return out


def _bridge(L, bank_of, banks):
    """Join every bank into one manifold network with the shortest runs of manifold parts."""
    linked = {banks[0]}
    for bank in banks[1:]:
        holes = _holes(L)
        starts = {}
        for cell, normal, i in holes:
            if bank_of.get(i) in linked:
                starts.setdefault(add(cell, normal), normal)
        goals = {}
        for cell, normal, i in holes:
            if bank_of.get(i) == bank:
                goals.setdefault(add(cell, normal), normal)
        cells = list(L.cells)
        lo = tuple(min(c[a] for c in cells) - 1 for a in range(3))
        hi = tuple(max(c[a] for c in cells) + 1 for a in range(3))
        prev, queue, end = {}, deque(sorted(starts)), None
        seen = set(starts)
        while queue:
            cur = queue.popleft()
            if cur in goals:
                end = cur
                break
            for d in DIRS:
                n = add(cur, d)
                if n not in seen and L.free([n]) and all(lo[a] <= n[a] <= hi[a] for a in range(3)):
                    seen.add(n)
                    prev[n] = cur
                    queue.append(n)
        if end is None:
            raise _NoRoom(f"no room to bridge the {bank} bank to the others")
        path = [end]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path.reverse()
        for k, c in enumerate(path):
            d_in = neg(starts[c]) if k == 0 else sub(path[k - 1], c)
            d_out = neg(goals[c]) if k == len(path) - 1 else sub(path[k + 1], c)
            d = "modular_engine_manifold_straight" if d_in == neg(d_out) else "modular_engine_manifold_corner"
            a, b = _coupling(d, "manifold_a")[1], _coupling(d, "manifold_b")[1]
            L.place(d, c, _rotation([(a, d_in), (b, d_out)]), f"{bank} bank bridge manifold")
        linked.add(bank)


def _feeds(L, s):
    """Air, fuel, exhaust and coolant manifolds on free holes, pipe faces open and outward."""
    wanted = [f for f in FEEDS if f[0] != "coolant" or s["coolant"]]
    out = {}
    for kind, d in wanted:
        choices = [d, EXHAUST_CORNER] if kind == "exhaust" else [d]
        best = None
        for cell, normal, _ in _holes(L):
            spot = add(cell, normal)
            if not L.free([spot]):
                continue
            for definition in choices:
                _, direction = _coupling(definition, modular._local(definition)[0][1])
                for Q in ROTATIONS:
                    if apply(Q, direction) != neg(normal):
                        continue
                    exits = [(add(spot, apply(Q, n)), apply(Q, n)) for _, n in _pipe_faces(definition)]
                    if not L.free([e for e, _ in exits]):
                        continue
                    if s["air_rams"] and kind in ("air", "exhaust") and not L.free([exits[0][0]]):
                        continue
                    # Prefer pipe ends far from the crank line, so they are easy to reach.
                    score = min(e[0] ** 2 + e[1] ** 2 for e, _ in exits)
                    key = (score, -choices.index(definition))
                    if best is None or key > best[0]:
                        best = (key, definition, spot, Q, exits)
        if best is None:
            raise _NoRoom(f"no free cylinder hole for the {kind} manifold")
        _, definition, spot, Q, exits = best
        i = L.place(definition, spot, Q, f"{kind} manifold")
        for e, _ in exits:
            L.reserved.add(e)
        if s["air_rams"] and kind in ("air", "exhaust"):
            e, n = exits[0]
            ram = "modular_engine_air_ram"
            ram_dir = _pipe_faces(ram)[0][1]
            L.place(ram, e, _rotation([(ram_dir, neg(n))]), f"{kind} air ram", allow_reserved=True)
        out[kind] = i
    return out


def build(op):
    """Engine parts in the engine frame turned by the op's output/top directions, as
    (rows, report) where rows are (definition, origin, Q, label) with origin before the shift
    to `position`."""
    s = _spec(op)
    error = None
    for spacer in (0, 1):
        try:
            L, feeds, clutch = _layout(s, spacer)
            break
        except _NoRoom as exc:
            error = exc
    else:
        raise ValueError(f"{error}; try fewer banks, more cylinders per bank or a larger size")
    R = s["R"]
    rows = [(d, apply(R, origin), tuple(tuple(sum(R[i][k] * Q[k][j] for k in range(3)) for j in range(3))
                                        for i in range(3)), label) for d, origin, Q, label in L.rows]
    return s, rows, {"feeds": feeds, "clutch": clutch}


def place(out, op, key):
    """The engine's parts as new draft parts with IDs `{key}:{n}`, its lowest corner at `position`."""
    from .editing import color, part, vector  # noqa: PLC0415
    s, rows, _ = build(op)
    position = vector(op.get("position"))
    paint = color(op.get("color", "C2C3C7"))
    created = [part({"definition": d, "position": origin, "rotation": Q, "color": paint,
                     "name": f"{s['name']} {label}"}, f"{key}:{n}") for n, (d, origin, Q, label) in enumerate(rows)]
    cells = [v for p in created for v in p.voxels()]
    shift = sub(position, tuple(min(v[a] for v in cells) for a in range(3)))
    for p in created:
        p.origin = add(p.origin, shift)
    _verify(created, s)
    footprint = {v for p in created for v in p.voxels()}
    hit = [p for p in out if any(v in footprint for v in p.voxels())]
    if hit:
        raise ValueError(f"the engine overlaps {len(hit)} part(s), first {hit[0].uid} ({hit[0].piece.d}) at "
                         f"{list(hit[0].origin)}; move it or clear the space")
    return created


def _verify(parts, s):
    groups, pairs = modular.engines(parts)
    engine = [p for p in parts if p.piece.d != "modular_engine_air_ram"]
    if len(groups) != 1 or {id(p) for p in groups[0]} != {id(p) for p in engine}:
        raise ValueError("internal: the generated engine is not one coupled assembly")
    need = {"air", "fuel", "exhaust"} | ({"coolant"} if s["coolant"] else set())
    feeds = modular._feeds(groups[0], pairs)
    if len(feeds) != s["cylinders"] or any(need - f for f in feeds.values()):
        raise ValueError("internal: a generated cylinder is not on the manifold network")


def points(parts):
    """Connection points of a placed engine, by draft part ID: pipe faces to route and logic
    nodes to wire."""
    from .connections import transmission_ports  # noqa: PLC0415
    from .networks import ports  # noqa: PLC0415
    pipes = {"modular_engine_air_manifold": "air in", "modular_engine_intake_manifold": "fuel in",
             "modular_engine_exhaust_manifold_straight": "exhaust out",
             "modular_engine_exhaust_manifold_corner": "exhaust out", "modular_engine_coolant_manifold": "coolant",
             "modular_engine_air_ram": "air ram (open to outside air)"}
    rams = {p.uid for p in parts if p.piece.d == "modular_engine_air_ram"}
    out = []
    for p in parts:
        if p.piece.d.startswith("modular_engine_clutch"):
            for f in transmission_ports(p):
                out.append({"name": "power output (RPS)", "part_id": p.uid, "surface_index": f["surface_index"],
                            "position": f["position"], "facing": f["normal"]})
        elif p.piece.d in pipes and p.piece.d != "modular_engine_air_ram":
            for f in transmission_ports(p):
                covered = any(add(f["position"], f["normal"]) in q.voxels() for q in parts if q.uid in rams)
                if not covered:
                    # Coolant A (in) and B (out) share one cell; either face can take either end of the loop.
                    name = pipes[p.piece.d] if p.piece.d != "modular_engine_coolant_manifold" else "coolant loop end"
                    out.append({"name": name, "part_id": p.uid, "surface_index": f["surface_index"],
                                "position": f["position"], "facing": f["normal"]})
        for n in ports(p):
            if n["type"] in (2, 3):
                continue
            if (p.piece.d in ("modular_engine_air_manifold", "modular_engine_intake_manifold") and n["label"] == "Throttle"
                    or p.piece.d.startswith(("modular_engine_starter", "modular_engine_clutch", "modular_engine_alternator",
                                             "modular_engine_sensor"))
                    or p.piece.d.startswith("modular_engine_crankshaft") and p.name.endswith("crankshaft 1")
                    or p.piece.d.startswith(modular.CYLINDERS) and p.name.split(" (")[0].endswith("cylinder 1")):
                out.append({"name": f"{p.name}: {n['label']}", "part_id": p.uid, "port": n["index"],
                            "type": n["type"], "direction": "input" if n["mode"] == 1 else "output"})
    return out
