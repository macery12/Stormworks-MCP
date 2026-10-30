"""Inset propellers and rudders, and the below-deck engine room (fitout stage "powertrain").

Copied from the player's fix of a generated Mini Speedboat (October 2026, see
docs/in-game-testing.md): the propeller hub replaces a transom block with its blades just aft;
the rudder's mounting plate replaces the bottom row, flush with the transom; the engine sits low
inside the hull facing aft, with the radiator behind it and the fuel tank ahead; the air intake
is a fluid port flush in the deck and the exhaust leaves through the transom above the
propeller. Exposed pipes are colour-coded by contents (pipe_colours); the pipe through the
transom is enclosed and keeps the hull colour.
"""
from collections import deque
from dataclasses import dataclass
from itertools import product

from . import definitions
from .configuration import new_settings
from .orientation import rudder_clearance
from .pieces import BY_NAME, DIRS, IDENTITY, Placed, add, apply, find_rotation, sub
from .routing import route

UP = (0, 1, 0)
PAINT = "C2C3C7"
ENGINE_Q = find_rotation([((0, 0, 1), (0, 0, -1)), ((0, 1, 0), (0, 1, 0))])     # small diesel: ports aft
YAWS = tuple(find_rotation([((0, 0, 1), d), (UP, UP)]) for d in ((0, 0, 1), (1, 0, 0), (0, 0, -1), (-1, 0, 0)))
RADIATOR_QS = tuple(find_rotation([((0, 0, 1), n), ((0, 1, 0), u)])
                    for n in ((0, 0, 1), (1, 0, 0), (0, 0, -1), (-1, 0, 0)) for u in ((0, -1, 0), UP))
# Prebuilt diesels by size. Power and cost from the game wiki (20/60/200 kW, $400/1000/3000);
# the medium one's internal id is aircraft_engine, but in game it is the "Medium Engine".
SIZES = {"small": "engine", "medium": "aircraft_engine", "large": "engine_diesel"}
ENGINE_KW = {"engine": 20, "aircraft_engine": 60, "engine_diesel": 200}
BED_PAINT = "4A4F55"
# Power wanted per 1,000 mass units of displacement. PROVISIONAL: the October 2026 telemetry
# measured speed, RPS and fuel use on three different hulls, not shaft power or matched-hull
# performance. The planing value still comes from the player's small-diesel Mini Speedboat
# (about 1,000 mass, runs well on 20 kW). Do not fit these values from unmatched boats.
KW_PER_1000 = {"planing": 20, "displacement": 8}
EXHAUST_Q = find_rotation([((0, 1, 0), (0, 0, -1)), ((1, 0, 0), (1, 0, 0))])    # outlet points aft
TANK_QS = (IDENTITY, find_rotation([((1, 0, 0), (0, 0, 1)), ((0, 1, 0), (0, 1, 0))]),
           ((0, 0, 1), (0, -1, 0), (1, 0, 0)))  # last: the player's, lying across the hull
ENGINE_TRIES, PORT_TRIES, TANK_TRIES, RADIATOR_TRIES = 24, 8, 10, 12
FUEL = {"fluid_type": 1, "fluid_fill": 1}


class LayoutError(ValueError):
    pass


class Room:
    """The hull being fitted: parts, which part owns each cell, reserved access, hull volume.
    Changes are made in place; snapshot/restore undo a failed layout attempt."""

    def __init__(self, parts, region, reserved):
        self.parts, self.region, self.reserved = parts, region, set(reserved)
        self.owner = {v: p for p in parts for v in p.voxels()}
        self.open_air = {}
        self.water = _flood(self.owner)

    def snapshot(self):
        return list(self.parts), dict(self.owner), set(self.reserved)

    def restore(self, state):
        self.parts[:], self.owner, self.reserved = list(state[0]), dict(state[1]), set(state[2])

    def cuttable(self, v):
        """A one-cell hull block the layout may replace."""
        p = self.owner.get(v)
        return (p is not None and p.piece.d in BY_NAME and len(p.piece.footprint) == 1 and not p.protected
                and not p.settings and self.region.get(v) == "hull")

    def inside(self, v):
        return self.region.get(v) == "hull" and v not in self.water.cells and self.water.within(v)

    def free(self, v):
        """Empty space inside the hull."""
        return v not in self.owner and v not in self.reserved and self.inside(v)

    def outside(self, v):
        """Open air or water around the hull."""
        return v not in self.owner and v not in self.reserved and (v in self.water.cells or not self.water.within(v))

    def structure(self, v):
        p = self.owner.get(v)
        return p is not None and p.piece.d in BY_NAME and self.region.get(v) == "hull"

    def cut(self, cells):
        doomed = {id(self.owner[v]) for v in cells if v in self.owner}
        self.parts[:] = [p for p in self.parts if id(p) not in doomed]
        self.owner = {v: p for v, p in self.owner.items() if id(p) not in doomed}

    def add(self, p):
        self.parts.append(p)
        self.owner.update({v: p for v in p.voxels()})

    def aft(self, x, y):
        """z of the transom (aft-most hull block) in row (x, y), or None."""
        zs = [v[2] for v in self.owner if v[0] == x and v[1] == y and self.structure(v)]
        return min(zs) if zs else None


class _Water:
    def __init__(self, cells, lo, hi):
        self.cells, self.lo, self.hi = cells, lo, hi

    def within(self, v):
        return all(self.lo[i] < v[i] < self.hi[i] for i in range(3))


def _flood(owner):
    """Cells reached from the sides and bottom of the bounding box without passing through a
    part or stepping down: the water and air around the hull. The hull region cannot say this:
    it marks the whole envelope, including cells outside a wedge skin or past the transom.
    Never stepping down keeps an open hull's cockpit inside."""
    lo = [min(v[i] for v in owner) - 1 for i in range(3)]
    hi = [max(v[i] for v in owner) + 1 for i in range(3)]
    seen = set()
    queue = deque()
    for v in product(*(range(lo[i], hi[i] + 1) for i in range(3))):
        if (v[0] in (lo[0], hi[0]) or v[2] in (lo[2], hi[2]) or v[1] == lo[1]) and v not in owner:
            seen.add(v)
            queue.append(v)
    steps = [d for d in DIRS if d != (0, -1, 0)]
    while queue:
        v = queue.popleft()
        for d in steps:
            n = (v[0] + d[0], v[1] + d[1], v[2] + d[2])
            if n not in seen and n not in owner and all(lo[i] <= n[i] <= hi[i] for i in range(3)):
                seen.add(n)
                queue.append(n)
    return _Water(seen, lo, hi)


def _face(d, q, *, label=None, kind=None):
    """(surface index, cell offset, outward normal) of one transmission face of a part."""
    data = definitions.metadata(d) or {}
    nodes = {tuple(n["position"]) for n in data.get("logic_nodes", [])
             if label is None or n["label"] == label}
    for i, s in enumerate(data.get("attachment_surfaces", [])):
        if (s["trans_type"] > 0 and 0 <= s["orientation"] < 6 and (kind is None or s["trans_type"] == kind)
                and tuple(s["position"]) in nodes):
            return i, apply(q, s["position"]), apply(q, DIRS[s["orientation"]])
    raise LayoutError(f"installed {d} has no {label or 'transmission'} face")


def _faces(d, q, label):
    data = definitions.metadata(d) or {}
    nodes = {tuple(n["position"]) for n in data.get("logic_nodes", []) if n["label"] == label}
    return [(i, apply(q, s["position"]), apply(q, DIRS[s["orientation"]]))
            for i, s in enumerate(data.get("attachment_surfaces", []))
            if s["trans_type"] > 0 and 0 <= s["orientation"] < 6 and tuple(s["position"]) in nodes]


def _load(d):
    piece = BY_NAME.get(d) or definitions.load(d)
    if piece is None:
        raise LayoutError(definitions.unavailable(d))
    return piece


def _mounted(p, room):
    from .components import mounted  # noqa: PLC0415 - components imports this module
    return mounted(p, room.owner)


# Propellers and rudders --------------------------------------------------------------------

def inset_propeller(room, d, q, x, uid, name, color=PAINT):
    """Set the hub into the transom on line x, blades one cell aft, as low as the blade
    sweep allows while staying above the bottom row. Returns (part, sweep cells, hub y)."""
    piece = _load(d)
    cells = [apply(q, c) for c in piece.footprint]
    _, port, normal = _face(d, q, kind=1)
    blade = max(cells, key=lambda c: abs(c[2] - port[2]))
    radius = float((definitions.metadata(d) or {}).get("properties", {}).get("force_emitter_blade_physics_length", 0.25))
    margin = max(1, round(radius * 4))
    ys = sorted({v[1] for v in room.owner if v[0] == x and room.structure(v)})
    for y in ys:
        zt = room.aft(x, y)
        bottom = min((v[1] for v in room.owner if v[0] == x and v[2] == zt and room.structure(v)), default=None)
        if zt is None or bottom is None or y - margin <= bottom:
            continue
        origin = sub((x, y, zt - 1), blade)
        p = Placed(piece, origin, q, color, uid, name)
        world = p.voxels()
        hub = [v for v in world if v != add(origin, blade)]
        sweep = {(x + i, y + j, zt - 1) for i, j in product(range(-margin, margin + 1), repeat=2)}
        exit_cell = add(add(origin, port), normal)
        if (not any(v[2] == zt and room.cuttable(v) for v in hub)
                or not all(room.cuttable(v) or room.free(v) for v in hub)
                or not all(room.outside(v) for v in sweep) or not room.free(exit_cell)):
            continue
        state = room.snapshot()
        room.cut(hub)
        room.add(p)
        if _mounted(p, room):
            return p, sweep, y
        room.restore(state)
    raise LayoutError(f"no transom row on line x={x / 4:g} m fits a {d} hub with blade clearance")


def inset_rudder(room, d, q, x, uid, name, avoid=frozenset(), color=PAINT):
    """Set the rudder's mounting plate into the bottom row on line x, flush with the transom
    (moving forward if needed); the blade hangs below the hull, never past the transom. Off the
    centreline of a V bottom the blade would swing into the keel, so the plate may sit up to two
    rows lower, hung under the hull."""
    piece = _load(d)
    cells = [apply(q, c) for c in piece.footprint]
    top = max(c[1] for c in cells)
    plate = [c for c in cells if c[1] == top]
    rear = min(c[2] for c in plate)
    column = [v for v in room.owner if v[0] == x and room.structure(v)]
    if not column:
        raise LayoutError(f"no hull on line x={x / 4:g} m for a rudder")
    stern = min(v[2] for v in column)
    keel = min(v[1] for v in column if v[2] <= stern + 3)
    zt = room.aft(x, keel)
    for level, z in product(range(keel, keel - 3, -1), range(zt, zt + 7)):
        origin = (x, level - top, z - rear)
        p = Placed(piece, origin, q, color, uid, name)
        world = p.voxels()
        top_cells = [v for v in world if v[1] == level]
        hang = [v for v in world if v[1] < level]
        if (not all(room.cuttable(v) or room.outside(v) for v in top_cells) or not all(room.outside(v) for v in hang)
                or any(v in room.owner and v not in world or v in avoid for v in rudder_clearance(p))):
            continue
        state = room.snapshot()
        room.cut(top_cells)
        room.add(p)
        if _mounted(p, room):
            return p
        room.restore(state)
    raise LayoutError(f"no bottom row near the transom on line x={x / 4:g} m fits a {d}")


def hulls(room):
    """Centre x of each hull (a monohull is [0]; a catamaran two), from the hull's x runs."""
    xs = sorted({v[0] for v, tag in room.region.items() if tag == "hull"})
    runs = []
    for x in xs:
        if runs and x == runs[-1][-1] + 1:
            runs[-1].append(x)
        else:
            runs.append([x])
    return [(r[0] + r[-1]) // 2 for r in runs]


def lines(room, count):
    """Shaft lines: one per hull of a catamaran, else the centreline or a symmetric twin
    pair as close together as fits."""
    centres = hulls(room)
    if len(centres) > 1:
        if count != len(centres):
            raise LayoutError(f"a {len(centres)}-hull boat needs fitout.engines={len(centres)}, one per hull")
        return [centres]
    if count == 1:
        return [[centres[0] if centres else 0]]
    xs = sorted({abs(v[0]) for v in room.owner if room.structure(v)})
    return [[-k, k] for k in range(2, (max(xs) if xs else 0))]


# Engine room -------------------------------------------------------------------------------

def _box(room, lo_z, hi_z):
    hull = [v for v in room.region if room.region[v] == "hull" and lo_z <= v[2] <= hi_z]
    lo = [min(v[i] for v in hull) - 1 for i in range(3)]
    hi = [max(v[i] for v in hull) + 2 for i in range(3)]
    lo[2], hi[2] = lo_z - 1, hi_z + 1
    return [lo, hi]


def _route(room, a, b, name, uid, box, through=None):
    """Route inside the hull only; pass route() just the parts near the box (speed)."""
    lo, hi = box
    def near(p):
        return any(all(lo[i] - 1 <= v[i] <= hi[i] + 1 for i in range(3)) for v in p.voxels())
    local = [p for p in room.parts if near(p)]
    key = (tuple(lo), tuple(hi))
    if key not in room.open_air:
        room.open_air[key] = {v for v in product(*(range(lo[i], hi[i] + 1) for i in range(3)))
                              if v not in room.owner and not room.inside(v)}
    open_air = room.open_air[key]
    try:
        result, added = route(local, a, b, extent=box, reserved=room.reserved | open_air, prefix=uid, name=name,
                              through_blocks=through, copy_parts=False)
    except ValueError as exc:
        # Bulkheads and inner decks: pass through them as enclosed pipes (hull colour).
        result = _through_partitions(room, local, a, b, box, open_air, uid, name, through)
        if result is None:
            raise LayoutError(f"{name}: {exc}") from exc
        result, added = result
    gone = {p.uid for p in local} - {p.uid for p in result}
    room.cut([v for v, p in room.owner.items() if p.uid in gone])
    for p in added:
        room.add(p)


def _partitions(room, box):
    """Plain inner blocks (bulkheads, decks, floors) with hull on every side: never the shell."""
    lo, hi = box
    return {v for v, p in room.owner.items() if p.piece.d == "01_block" and room.cuttable(v)
            and all(lo[i] <= v[i] <= hi[i] for i in range(3))
            and all(room.region.get(add(v, d)) == "hull" for d in DIRS)}


def _through_partitions(room, local, a, b, box, open_air, uid, name, through):
    from .routing import _path, face  # noqa: PLC0415
    walls = _partitions(room, box) - set(through or ())
    if not walls:
        return None
    start, end = face(local, a), face(local, b)
    occupied = {v: p for p in local for v in p.voxels() if v not in walls}
    through_cells = {v for v, p in room.owner.items() if p.uid in set(through or ())}
    for v in through_cells:
        occupied.pop(v, None)
    entry, exit_cell = add(start["position"], start["normal"]), add(end["position"], end["normal"])
    try:
        cells = _path(entry, exit_cell, occupied, room.reserved | open_air, box,
                      initial_direction=start["normal"], final_direction=tuple(-n for n in end["normal"]))
    except ValueError:
        return None
    crossed = [room.owner[v].uid for v in cells if v in walls]
    try:
        return route(local, a, b, extent=box, reserved=room.reserved | open_air, prefix=uid, name=name,
                     through_blocks=[*(through or ()), *crossed], waypoints=cells[1:-1] or None, copy_parts=False)
    except ValueError:
        return None


def _place(room, p, need_mount=True):
    if not all(room.free(v) for v in p.voxels()):
        raise LayoutError(f"{p.name} does not fit")
    room.add(p)
    if need_mount and not _mounted(p, room):
        raise LayoutError(f"{p.name} has no mounting contact")


def _yaws(d):
    """Facings to try, best first: shaft aft (straight to the propeller); an engine with its shaft on
    top (the small diesel) faces its ports aft, as the player built it."""
    def key(q):
        return (_face(d, q, label="RPS", kind=1)[2] != (0, 0, -1), _face(d, q, label="Fuel")[2] != (0, 0, -1))
    return sorted(YAWS, key=key)


def _engine_spots(room, d, x, prop_z, engine_rooms=()):
    """(origin, facing) for the engine on line x: the lowest free spot per frame and facing; inside
    an engine room first, then the best facing (an engine lying across the hull looks wrong), then
    aft first, leaving room between it and the propeller."""
    piece = _load(d)
    by_column = {}
    for v, tag in room.region.items():
        if tag == "hull" and v[0] == x:
            by_column.setdefault(v[2], set()).add(v[1])
    hull_z = sorted(by_column)
    limit = hull_z[0] + (hull_z[-1] - hull_z[0]) * 0.6 if hull_z else prop_z
    spots = []
    for rank, q in enumerate(_yaws(d)):
        cells = [apply(q, c) for c in piece.footprint]
        _, shaft, normal = _face(d, q, label="RPS", kind=1)
        low, aft = min(c[1] for c in cells), min(c[2] for c in cells)
        for z in range(prop_z + 5 - aft, int(limit) + 1):
            for y in sorted(by_column.get(z, ())):
                origin = (x, y - low, z)
                if all(room.free(add(origin, c)) for c in cells) and room.free(add(add(origin, shaft), normal)):
                    spots.append((origin, q, rank))
                    break

    def in_room(origin, q):
        return any(all(add(origin, apply(q, c)) in air for c in piece.footprint) for air in engine_rooms)
    return [(o, q) for o, q, rank in sorted(spots, key=lambda s: (not in_room(s[0], s[1]), s[2], s[0][2]))]


def _beds(room, p):
    """One-block engine beds under mount points that sit over a gap (the medium engine stands on a
    three-block foot); each bed rests on hull structure. Returns the beds to add."""
    beds = []
    for s in (definitions.metadata(p.piece.d) or {}).get("attachment_surfaces", []):
        if s["trans_type"] or not 0 <= s["orientation"] < 6 or apply(p.Q, DIRS[s["orientation"]]) != (0, -1, 0):
            continue
        under = add(add(p.origin, apply(p.Q, s["position"])), (0, -1, 0))
        if room.free(under) and room.structure(add(under, (0, -1, 0))):
            beds.append(Placed(BY_NAME["01_block"], under, IDENTITY, BED_PAINT, name="engine bed"))
    return beds


def _intake_spots(room, air_exit, prefer=None, outboard=0):
    """Deck cells (cut, port flush) then open-top cells near the engine's air port. Twins
    (outboard = side of the hull) look outboard first, away from the other engine's pipes, and
    break ties without favouring a side so both engines choose alike."""
    x0, y0, z0 = air_exit
    deck, open_top = [], []
    for cx, cz in product(range(x0 - 2, x0 + 3), range(z0 - 3, z0 + 4)):
        y = y0 + 1
        while room.free((cx, y, cz)):
            y += 1
        if y == y0 + 1:
            continue
        cell, above = (cx, y, cz), (cx, y + 1, cz)
        if room.cuttable(cell) and room.outside(above):
            deck.append(cell)
        elif room.outside(cell) and room.outside(above):
            open_top.append((cx, y - 1, cz))
    def key(v):
        mirrored = sum(abs(v[i] - prefer[i]) for i in range(3)) if prefer else 0
        inboard = int(outboard * (v[0] - x0) < 0)
        return mirrored, inboard, sum(abs(v[i] - air_exit[i]) for i in range(3)), abs(v[0] - x0), v[2], v[1]
    return [(v, True) for v in sorted(deck, key=key)] + [(v, False) for v in sorted(open_top, key=key)]


def _tank_spots(room, fuel_exit):
    """Medium tank spots near the engine's fuel port, nearest and lowest first."""
    piece = _load("fluid_tank_medium")
    x, y, z = fuel_exit
    spots = []
    for q in TANK_QS:
        cells = [apply(q, c) for c in piece.footprint]
        low = min(c[1] for c in cells)
        for cx, cz in product(range(x - 5, x + 6), range(z - 6, z + 7)):
            for cy in range(y - 6, y + 4):
                origin = (cx, cy - low, cz)
                if all(room.free(add(origin, c)) for c in cells):
                    spots.append((abs(cx - x) + abs(cz - z) + abs(cy - y), cy, origin, q))
                    break
    return [(o, q) for *_, o, q in sorted(spots, key=lambda s: s[:3])]


def _radiator_spots(room, engine):
    """Radiator spots: first square on the engine's coolant ports, one pipe away (the player's
    layout for the small diesel); then nearby."""
    piece = _load("fluid_radiator")
    ins, outs = (_face(engine.piece.d, engine.Q, label=label) for label in ("In Coolant", "Out Coolant"))
    a, b = (add(engine.origin, f[1]) for f in (ins, outs))
    n = ins[2]
    spots = []
    if outs[2] == n and a[1] == b[1] and sum(abs(a[i] - b[i]) for i in range(3)) == 2:
        mid = tuple((a[i] + b[i]) // 2 for i in range(3))
        for q in RADIATOR_QS:
            if apply(q, (0, 0, 1)) == tuple(-c for c in n):
                spots.append((sub(add(mid, tuple(2 * c for c in n)), apply(q, (0, 1, 0))), q))
    centre = add(tuple((a[i] + b[i]) // 2 for i in range(3)), tuple(3 * c for c in n))
    near = []
    for q in RADIATOR_QS:
        for dx, dy, dz in product(range(-3, 4), range(-2, 3), range(-3, 4)):
            origin = add(centre, (dx, dy, dz))
            if all(room.free(add(origin, apply(q, c))) for c in piece.footprint):
                near.append((abs(dx) + abs(dy) + abs(dz), origin, q))
    return spots + [(o, q) for _, o, q in sorted(near, key=lambda s: s[:2])[:RADIATOR_TRIES]]


def _part(d, origin, q, name, settings=None):
    return Placed(_load(d), origin, q, PAINT, f"component:{name}", name, new_settings(d, settings or {}))


def _exhausts(room, line, box, engine):
    """One outlet per exhaust port, pointing aft out of the transom just above the propeller hub
    (two side by side for the medium and large engines), each piped through the transom."""
    ports = sorted(_faces(engine.piece.d, engine.Q, "Exhaust"), key=lambda f: add(engine.origin, f[1])[0])
    offsets = [0] if len(ports) == 1 else [-1, 1]
    ye = line.prop_y + 1
    outlets = []
    for k, ((index, _, _), dx) in enumerate(zip(ports, offsets)):
        x = line.x + dx
        zt = room.aft(x, ye)
        if zt is None or not room.cuttable((x, ye, zt)) or room.owner[(x, ye, zt)].piece.d != "01_block":
            raise LayoutError("no plain transom block above the propeller for the exhaust")
        name = f"exhaust{line.suffix}" + (f" {'ab'[k]}" if len(ports) > 1 else "")
        outlet = _part("fluid_exhaust", (x, ye, zt - 1), EXHAUST_Q, name)
        if not all(room.outside(v) for v in outlet.voxels()):
            raise LayoutError("no open space aft of the transom for the exhaust")
        room.add(outlet)
        wall, z = [], zt  # a transom can be several blocks thick
        while room.cuttable((x, ye, z)) and room.owner[(x, ye, z)].piece.d == "01_block":
            wall.append(room.owner[(x, ye, z)].uid)
            z += 1
        face = _face("fluid_exhaust", EXHAUST_Q, label="Fluid")[0]
        _route(room, {"part_id": engine.uid, "surface_index": index}, {"part_id": outlet.uid, "surface_index": face},
               "exhaust", f"powertrain:{name}", box, through=wall)
        outlets.append(outlet)
    return outlets


def _end(p, label, kind=None):
    return {"part_id": p.uid, "surface_index": _face(p.piece.d, p.Q, label=label, kind=kind)[0]}


def _layout(room, line, d, engine_at, q, box, prefer_intake=None, skip_intakes=frozenset()):
    """One engine d at engine_at facing q, plumbed to the line's propeller; returns the parts it
    added. Raises LayoutError."""
    n = line.suffix
    engine = _part(d, engine_at, q, f"engine{n}")
    if not all(room.free(v) for v in engine.voxels()):
        raise LayoutError(f"{engine.name} does not fit")
    room.add(engine)
    beds = []
    if not _mounted(engine, room):
        beds = _beds(room, engine)
        for bed in beds:
            room.add(bed)
        if not _mounted(engine, room):
            raise LayoutError(f"{engine.name} has no hull block under its mount points")

    last = "no room for a radiator by the engine's coolant ports"
    for origin, rq in _radiator_spots(room, engine):
        state = room.snapshot()
        radiator = _part("fluid_radiator", origin, rq, f"radiator{n}")
        try:
            if not all(room.free(v) for v in radiator.voxels()):
                raise LayoutError("radiator does not fit")
            room.add(radiator)
            ports = _faces("fluid_radiator", rq, "Fluid A") + _faces("fluid_radiator", rq, "Fluid B")
            for label in ("In Coolant", "Out Coolant"):
                start = add(engine.origin, _face(d, q, label=label)[1])
                port = min(ports, key=lambda f: sum(abs(add(origin, f[1])[i] - start[i]) for i in range(3)))
                ports.remove(port)
                which = label.split()[0].lower()
                _route(room, _end(engine, label), {"part_id": radiator.uid, "surface_index": port[0]},
                       f"coolant {which}", f"powertrain:coolant-{which}{n}", box)
            break
        except LayoutError as exc:
            room.restore(state)
            last = str(exc)
    else:
        raise LayoutError(last)

    def shaft():
        _route(room, _end(engine, "RPS", 1), _end(line.prop, "RPS", 1), "prop shaft", f"powertrain:shaft{n}", box)

    placed = {}

    def exhaust_pipes():
        placed["exhausts"] = _exhausts(room, line, box, engine)

    state = room.snapshot()
    try:
        shaft()
        exhaust_pipes()
    except LayoutError as first:
        room.restore(state)
        try:  # the other order: the first pipe can take the only way past the other
            exhaust_pipes()
            shaft()
        except LayoutError:
            room.restore(state)
            raise first from None

    _, air, normal = _face(d, q, label="Air")
    last = "no deck or open space above the engine for an air intake"
    outboard = (line.x > 0) - (line.x < 0) if line.suffix else 0
    spots = [s for s in _intake_spots(room, add(add(engine_at, air), normal), prefer_intake, outboard)
             if s[0] not in skip_intakes]
    for cell, in_deck in spots[:PORT_TRIES]:
        state = room.snapshot()
        try:
            if in_deck:
                room.cut([cell])
            intake = _part("water_inlet", cell, IDENTITY, f"air intake{n}")
            if not all(room.free(v) or room.outside(v) for v in intake.voxels()):
                raise LayoutError("air intake does not fit")
            room.add(intake)
            _route(room, _end(engine, "Air"), _end(intake, "Fluid"), "air intake", f"powertrain:air{n}", box)
            break
        except LayoutError as exc:
            room.restore(state)
            last = str(exc)
    else:
        raise LayoutError(last)

    _, fuel, normal = _face(d, q, label="Fuel")
    last = "no room near the engine for a fuel tank"
    for origin, tq in _tank_spots(room, add(add(engine_at, fuel), normal))[:TANK_TRIES]:
        state = room.snapshot()
        tank = _part("fluid_tank_medium", origin, tq, f"fuel tank{n}", FUEL)
        try:
            _place(room, tank)
            for index, _, _ in _faces(tank.piece.d, tq, "Stored Fluid"):
                try:
                    _route(room, _end(engine, "Fuel"), {"part_id": tank.uid, "surface_index": index}, "fuel line",
                           f"powertrain:fuel{n}", box)
                    return [engine, *beds, radiator, *placed["exhausts"], intake, tank]
                except LayoutError as exc:
                    last = str(exc)
            raise LayoutError(last)
        except LayoutError as exc:
            room.restore(state)
            last = str(exc)
    raise LayoutError(last)


def _engines(room, installed, d, engine_rooms, skip):
    """Lay out one engine d per line; returns the report lines and the intake cells. Engines are
    all or nothing: on failure the room is restored and LayoutError raised."""
    before, lines_report, intakes = room.snapshot(), [], []
    previous = prefer = None
    reach = max(abs(c[2]) for c in _load(d).footprint) + 14
    for line in installed:
        spots = _engine_spots(room, d, line.x, line.prop.origin[2], engine_rooms)
        if previous is not None:  # twins: try the first engine's spot and facing first
            spots.sort(key=lambda s: (s[1] != previous[1],
                                      abs(s[0][2] - previous[0][2]) + abs(s[0][1] - previous[0][1])))
        stern = line.prop.origin[2]
        last = "no space inside the hull, below the deck, for the engine"
        for engine_at, q in spots[:ENGINE_TRIES]:
            state = room.snapshot()
            try:
                added = _layout(room, line, d, engine_at, q, _box(room, stern - 2, engine_at[2] + reach), prefer,
                                skip if previous is None else frozenset())
                previous = (engine_at, q)
                intake = next(p for p in added if p.piece.d == "water_inlet")
                intakes.append(intake.origin)
                # Twins: the second deck intake mirrors the first, since both show on deck.
                prefer = (-intake.origin[0], *intake.origin[1:])
                break
            except LayoutError as exc:
                room.restore(state)
                last = str(exc)
        else:
            room.restore(before)
            raise LayoutError(f"{definitions.display_name(d)}{line.suffix}: {last}")
        lines_report += [f"{p.name}: {definitions.display_name(p.piece.d)} at {[v / 4 for v in p.origin]} game m"
                         for p in added if p.name != "engine bed"]
        beds = sum(p.name == "engine bed" for p in added)
        if beds:
            lines_report.append(f"engine{line.suffix}: {beds} engine bed block(s) under its mount points")
    return lines_report, intakes


@dataclass
class Line:
    """One shaft line: its x, name suffix (" 1" for twins), propeller, hub row, rudder."""
    x: int
    suffix: str
    prop: Placed
    prop_y: int
    rudder: Placed


def install(parts, info, reserved, fitout, report):
    """Propellers and rudders set into the hull, plus engines when the stage is powertrain.
    Changes parts in place; returns the reserved cells (access and moving-part clearance).
    Raises LayoutError with the reason when it cannot; engines are all or nothing."""
    from .components import _orientation  # noqa: PLC0415
    count = fitout.get("engines", 1)
    room = Room(parts, info["region"], reserved)
    prop_cfg, rudder_cfg = fitout.get("propeller", {}), fitout.get("rudder", {})
    sizes = {"small": "propeller", "large": "large_propeller", "giant": "giga_prop_small"}
    prop_d = sizes.get(prop_cfg.get("size", "small"), "propeller")
    last = "hull too narrow for twin shaft lines"
    for xs in lines(room, count):
        state = room.snapshot()
        try:
            installed = []
            for i, x in enumerate(xs):
                suffix = f" {i + 1}" if count > 1 else ""
                prop, sweep, prop_y = inset_propeller(room, prop_d, _orientation(prop_cfg, prop_d), x,
                                                      f"component:propeller{suffix}", f"propeller{suffix}",
                                                      prop_cfg.get("color", PAINT))
                rudder = inset_rudder(room, "rudder", _orientation(rudder_cfg, "rudder"), x, f"component:rudder{suffix}",
                                      f"rudder{suffix}", sweep, rudder_cfg.get("color", PAINT))
                installed.append(Line(x, suffix, prop, prop_y, rudder))
            break
        except LayoutError as exc:
            room.restore(state)
            last = str(exc)
    else:
        raise LayoutError(last)
    for line in installed:
        report.append(f"{line.prop.name}: {definitions.display_name(line.prop.piece.d)} set into the transom at "
                      f"{[v / 4 for v in line.prop.origin]} game m")
        report.append(f"{line.rudder.name}: {definitions.display_name(line.rudder.piece.d)} set into the bottom at "
                      f"{[v / 4 for v in line.rudder.origin]} game m")
        room.reserved |= rudder_clearance(line.rudder) - set(room.owner)
    if fitout.get("stage") != "powertrain":
        for line in installed:
            _, port, normal = _face(line.prop.piece.d, line.prop.Q, kind=1)
            room.reserved.add(add(add(line.prop.origin, port), normal))  # keep ballast off the shaft port
        return room.reserved
    from .part_policy import PREBUILT_ENGINES  # noqa: PLC0415
    existing = [p for p in room.parts if p.piece.d in PREBUILT_ENGINES]
    if existing:
        raise LayoutError(f"the design already places {len(existing)} engine(s) (an engine room's engine or a "
                          "component); the powertrain stage lays out its own, so remove those or plumb them with "
                          "route_connections. Propellers and rudders were set into the hull")
    engine_rooms = [r.air for r in info["interior"].rooms if r.kind == "engine"]
    mass, hull_type, need = power_target(info)
    per_engine = need / len(installed)
    size = fitout.get("engine_size", "auto")
    if size == "auto":
        order = (sorted((d for d in ENGINE_KW if ENGINE_KW[d] >= per_engine), key=ENGINE_KW.get)
                 + sorted((d for d in ENGINE_KW if ENGINE_KW[d] < per_engine), key=ENGINE_KW.get, reverse=True))
    else:
        order = [SIZES[size]]
    failures = []
    for d in order:
        try:
            lines_report = _mirrored_engines(room, installed, d, engine_rooms)
            break
        except LayoutError as exc:
            failures.append(str(exc))
    else:
        raise LayoutError("; ".join(failures) + ". Propellers and rudders were set into the hull")
    total = ENGINE_KW[d] * len(installed)
    report.append(f"engine size: {len(installed)} x {definitions.display_name(d)} = {total} kW for a boat of about "
                  f"{mass:.0f} mass ({hull_type} hull: target {need:.0f} kW at {KW_PER_1000[hull_type]} kW per 1,000; "
                  "provisional: matched-hull performance and shaft power have not been measured)")
    if total < need:
        info["warnings"].append(f"underpowered: {total} kW against a {need:.0f} kW target; a bigger engine did not fit")
    elif size != "auto" and total > 3 * need:
        info["warnings"].append(f"{definitions.display_name(d)} gives {total} kW against a {need:.0f} kW target; "
                                "compare fuel use and speed on the same hull before choosing a larger engine")
    report.extend(lines_report)
    report.append("powertrain: wire the throttle, starter and battery (apply_vehicle_assembly engine_start_idle, "
                  "or edit_connections); pipes are routed and colour-coded")
    return room.reserved


def _mirrored_engines(room, installed, d, engine_rooms):
    """Engines d on every line; twins retry until their deck intakes mirror. Restores the room
    and raises LayoutError when they do not fit."""
    before = room.snapshot()
    skip = set()
    for _ in range(PORT_TRIES if len(installed) > 1 else 1):
        try:
            lines_report, intakes = _engines(room, installed, d, engine_rooms, skip)
        except LayoutError as exc:
            room.restore(before)
            if skip:
                raise LayoutError("twin deck air intakes could not be mirrored") from exc
            raise
        if len(intakes) < 2 or intakes[0] == (-intakes[1][0], *intakes[1][1:]):
            return lines_report
        # Twins whose deck intakes do not mirror: try the first engine's next intake.
        skip.add(intakes[0])
        room.restore(before)
    room.restore(before)
    raise LayoutError("twin deck air intakes could not be mirrored")


def power_target(info):
    """(design mass, hull type, kW wanted): the mass the hull floats at its painted waterline (in
    part-mass units, as the ballast estimate counts it) times a power-to-mass target by hull type."""
    from .habits import K_ESTIMATE  # noqa: PLC0415
    spec = info.get("spec") or {}
    waterline = (spec.get("colors") or {}).get("waterline")
    plane = waterline * 4 if waterline is not None else info["form"].depth * 0.45
    cells = sum(1 for v, tag in info["region"].items() if tag == "hull" and v[1] + 0.5 <= plane)
    mass = cells * K_ESTIMATE
    hull_type = "planing" if (spec.get("stern") or {}).get("flat_bottom", 0) > 0 else "displacement"
    return mass, hull_type, mass * KW_PER_1000[hull_type] / 1000
