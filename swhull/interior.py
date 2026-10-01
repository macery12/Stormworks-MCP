"""Interior layout: internal decks, bulkheads, rooms with doors, hatches, placeholder engines.

Everything here is plain blocks placed inside the hollow hull. Coordinates follow hull.py:
x lateral (0 = centreline), y voxel layer above the keel, z from the transom; specs use metres.

Levels: `interior.decks` lists internal floor heights in metres above the keel (top surface of
the floor). A room's `level` is an index into that list, or "main" for rooms standing on the
main deck (inside superstructure boxes).
"""
from dataclasses import dataclass, field

from . import definitions
from .hull import VOX
from .pieces import UP, Placed, add

WALL = "B5BCC4"
PLATE = "8A8F96"
ENGINE_COLOUR = "E67E22"
ROOM_COLOURS = {
    "engine": "4A4F55", "machinery": "5A5F66", "tank": "7A5C2E", "fuel": "7A5C2E",
    "quarters": "9C7A54", "cabin": "9C7A54", "galley": "C9C2B5", "mess": "B8A88A",
    "bridge": "4F6272", "storage": "6E6250", "cargo": "6E6250", "corridor": "8A8F96",
    "medical": "D8DEE3", "workshop": "6B6B5A",
}
DOOR_W, DOOR_H = 3, 8          # 0.75 m x 2.0 m walk-through opening
SIDES = {"fore": (0, 0, 1), "aft": (0, 0, -1), "port": (-1, 0, 0), "starboard": (1, 0, 0)}


def _v(m):
    return int(round(m * VOX))


@dataclass
class Room:
    name: str
    kind: str
    xlo: int
    xhi: int
    ylo: int      # first air layer (floor plate is ylo - 1)
    yhi: int      # last air layer (ceiling plate is yhi + 1)
    zlo: int
    zhi: int
    air: set = field(default_factory=set)
    doors: list = field(default_factory=list)
    engines: list = field(default_factory=list)

    def centre(self):
        return ((self.xlo + self.xhi) / 2, self.ylo, (self.zlo + self.zhi) / 2)


@dataclass
class InteriorPlan:
    blocks: dict = field(default_factory=dict)       # voxel -> colour
    carve: set = field(default_factory=set)           # hull skin voxels to open (doors/hatches)
    components: list = field(default_factory=list)    # Placed parts (engines)
    rooms: list = field(default_factory=list)
    levels: list = field(default_factory=list)        # (label, floor layer) for deck plans
    warnings: list = field(default_factory=list)


def plan_interior(spec, shape, solid, region, skin):
    cfg = spec.get("interior") or {}
    inside = solid - skin
    plan = InteriorPlan()

    tops = {}
    for (x, y, z), tag in region.items():
        if tag == "hull" and y > tops.get((x, z), -10**6):
            tops[(x, z)] = y

    def top_hull(x, z):
        return tops.get((x, z))

    # a floor wherever one section stands on another: the main deck under superstructure,
    # and between stacked superstructure boxes
    for v in inside:
        above = region.get(add(v, UP))
        if above is not None and above != region.get(v):
            plan.blocks[v] = PLATE

    deck_layers = sorted(_v(h) - 1 for h in cfg.get("decks") or [])
    for y in deck_layers:
        for v in inside:
            if v[1] == y and region.get(v) == "hull":
                plan.blocks[v] = PLATE
    for zb in cfg.get("bulkheads") or []:
        z = _v(zb)
        for v in inside:
            if v[2] == z and region.get(v) == "hull":
                plan.blocks[v] = WALL

    L = shape.form.L
    mid = min(L - 1, max(0, L // 2))
    plan.levels = [(f"deck {i} ({h:.2f} m)", _v(h)) for i, h in enumerate(sorted(cfg.get("decks") or []))]
    main_y = top_hull(0, mid)
    if main_y is not None:
        plan.levels.append(("main deck", main_y + 1))

    made = []
    for spec_room in cfg.get("rooms") or []:
        room = _make_room(spec_room, cfg, shape, top_hull, plan, inside)
        if room is None:
            continue
        colour = ROOM_COLOURS.get(room.kind, "A0A6AD")
        for x in range(room.xlo, room.xhi + 1):
            for z in range(room.zlo, room.zhi + 1):
                for y in (room.ylo - 1, room.yhi + 1):          # floor and ceiling
                    v = (x, y, z)
                    if v in inside:
                        plan.blocks[v] = colour if y == room.ylo - 1 else plan.blocks.get(v, PLATE)
                for y in range(room.ylo, room.yhi + 1):
                    v = (x, y, z)
                    if v not in inside:
                        continue
                    edge = x in (room.xlo, room.xhi) or z in (room.zlo, room.zhi)
                    if edge:
                        plan.blocks.setdefault(v, WALL)
                    else:
                        room.air.add(v)
                        plan.blocks.pop(v, None)   # rooms clear bulkheads/plates inside them
        if not room.air:
            plan.warnings.append(f"room '{room.name}' has no space inside the hull; check its z/level/width")
            continue
        plan.rooms.append(room)
        made.append((spec_room, room))

    for _, room in made:
        room.air = {v for v in room.air if v not in plan.blocks}   # later rooms' walls
    for spec_room, room in made:
        for side in spec_room.get("doors") or []:
            _add_door(room, side, solid, skin, region, top_hull, plan)
        eng = spec_room.get("engine")
        if eng:
            _add_engines(room, eng, int(spec_room.get("engine_count", 1)), plan)

    for h in cfg.get("hatches") or []:
        _add_hatch(h, deck_layers, cfg, skin, region, top_hull, plan)
    return plan


def _make_room(r, cfg, shape, top_hull, plan, inside):
    name = r.get("name", "room")
    decks = sorted(cfg.get("decks") or [])
    level = r.get("level", 0)
    zlo = _v(r["z"])
    zhi = _v(r["z"] + r["length"])
    zc = min(shape.form.L - 1, max(0, (zlo + zhi) // 2))
    xc = _v(r.get("x", 0.0))
    if r.get("floor") is not None:     # explicit floor height, e.g. an upper superstructure level
        ylo = _v(r["floor"])
        if r.get("height"):
            ceiling = ylo + _v(r["height"])
        else:
            ceiling = ylo
            while (xc, ceiling, zc) in inside and (xc, ceiling, zc) not in plan.blocks:
                ceiling += 1
    elif level == "main":
        t = top_hull(xc, zc)
        if t is None:
            plan.warnings.append(f"room '{name}': no hull under it for a main-deck room")
            return None
        ylo = t + 1
        if r.get("height"):
            ceiling = ylo + _v(r["height"])
        else:   # up to the first floor or roof above the room's centre
            ceiling = ylo
            while (xc, ceiling, zc) in inside and (xc, ceiling, zc) not in plan.blocks:
                ceiling += 1
    else:
        try:
            floor_h = decks[int(level)]
        except (ValueError, IndexError):
            plan.warnings.append(f"room '{name}': level {level!r} is not an index into interior.decks")
            return None
        ylo = _v(floor_h)
        above = [_v(h) - 1 for h in decks if _v(h) - 1 > ylo]
        t = top_hull(xc, zc)
        ceiling = min(above) if above else t
        if r.get("height"):
            ceiling = ylo + _v(r["height"])
    if ceiling is None:
        ceiling = ylo + 60   # up to whatever roof (superstructure top) closes the room
    width = r.get("width")
    if width:
        half = _v(width) / 2
        xlo, xhi = int(round(xc - half)), int(round(xc + half))
    else:
        xlo, xhi = -500, 500
    return Room(name, r.get("type", "room"), xlo, xhi, ylo, ceiling - 1, zlo, zhi)


def _add_door(room, side, solid, skin, region, top_hull, plan):
    """Cut a doorway (0.75 m wide, 2 m tall, down to 1.5 m where space is tight) at the lowest,
    most central spot on that side. Each row is bored from the room's last air voxel through
    1-2 wall blocks into free space; exterior doors bore through the hull skin to the outside
    and are only allowed above the main deck."""
    d = SIDES.get(side)
    if d is None:
        plan.warnings.append(f"room '{room.name}': door side {side!r} must be fore/aft/port/starboard")
        return
    air = room.air
    if not air:
        return
    axis = 2 if d[2] else 0
    lat = 0 if axis == 2 else 2
    sign = sum(d)
    edge = {}
    for v in air:
        key = (v[lat], v[1])
        if key not in edge or v[axis] * sign > edge[key][axis] * sign:
            edge[key] = v
    lats = sorted({k[0] for k in edge})
    centre = (lats[0] + lats[-1]) / 2

    def bore(u, y):
        """('open'|'interior'|'exterior', path) for one doorway cell, or None."""
        a = edge.get((u, y))
        if a is None:
            return None
        path, v = [], add(a, d)
        for _ in range(3):
            if v in plan.blocks or v in skin:
                path.append(v)
                v = add(v, d)
            else:
                break
        if v in solid and v not in plan.blocks and v not in skin:
            if any(p in skin for p in path) or len(path) > 2:
                return None
            return ("interior" if path else "open", path)
        if v not in solid and any(p in skin for p in path):
            return ("exterior", path)
        return None

    for height in range(min(DOOR_H, room.yhi - room.ylo + 1), 5, -1):
        for y0 in range(room.ylo, room.yhi - height + 2):
            for u in sorted(lats, key=lambda u: (abs(u - centre), u)):
                rows = [bore(uu, y) for uu in range(u - DOOR_W // 2, u + DOOR_W // 2 + 1)
                        for y in range(y0, y0 + height)]
                if any(r is None for r in rows):
                    continue
                kinds = {r[0] for r in rows}
                if "exterior" in kinds:
                    if kinds != {"exterior"}:
                        continue
                    cells = [c for r in rows for c in r[1]]
                    if any((t := top_hull(c[0], c[2])) is not None and y0 <= t for c in cells):
                        continue
                    for c in cells:
                        plan.blocks.pop(c, None)
                        if c in skin:
                            plan.carve.add(c)
                    notes = ["exterior"] + _step_notes(room, side, u, y0, edge, d, solid, skin, plan)
                    room.doors.append(f"{side} ({', '.join(notes)})")
                    return
                for r in rows:
                    for c in r[1]:
                        plan.blocks.pop(c, None)
                notes = [] if height == DOOR_H else [f"{height / VOX:.2f} m tall"]
                notes += _step_notes(room, side, u, y0, edge, d, solid, skin, plan)
                room.doors.append(f"{side} ({', '.join(notes)})" if notes else side)
                return
    plan.warnings.append(f"room '{room.name}': no spot for a {side} door (needs 0.75 m x 1.5 m+ of "
                         "wall with space on the other side; exterior doors only above the main deck)")


LADDER = 3   # a rise of more than 0.5 m gets flagged as needing a ladder


def _step_notes(room, side, u, y0, edge, d, solid, skin, plan):
    """Sill height above the room floor, and how far the floor on the other side drops below
    the sill."""
    def free(c):
        return c not in solid or (c not in plan.blocks and (c not in skin or c in plan.carve))

    notes = []
    sill = y0 - room.ylo
    if sill:
        notes.append(f"sill {sill / VOX:.2f} m above the floor" + (", ladder" if sill > LADDER else ""))
    c = add(edge[(u, y0)], d)
    for _ in range(4):
        if free(c):
            break
        c = add(c, d)
    else:
        return notes
    drop = 0
    while drop < 60 and free((c[0], c[1] - drop - 1, c[2])):
        drop += 1
    if drop >= 60:
        notes.append("no floor on the other side")
    elif drop:
        notes.append(f"other side {drop / VOX:.2f} m lower" + (", ladder" if drop > LADDER else ""))
    return notes


def _add_engines(room, size, count, plan):
    d = definitions.ENGINES.get(size)
    piece = definitions.load(d) if d else None
    if piece is None:
        plan.warnings.append(f"room '{room.name}': engine size {size!r} unknown or definitions missing")
        return
    fx = [v[0] for v in piece.footprint]
    fy = [v[1] for v in piece.footprint]
    fz = [v[2] for v in piece.footprint]
    width = max(fx) - min(fx) + 1
    xs = sorted({v[0] for v in room.air})
    cx = (xs[0] + xs[-1]) / 2
    zs = sorted({v[2] for v in room.air})
    cz = int(round((zs[0] + zs[-1]) / 2 - (max(fz) + min(fz)) / 2))
    gap = 3
    span = count * width + (count - 1) * gap
    first = cx - span / 2 + width / 2
    for i in range(count):
        ox = int(round(first + i * (width + gap) - (max(fx) + min(fx)) / 2))
        origin = (ox, room.ylo - min(fy), cz)
        cells = [add(origin, f) for f in piece.footprint]
        if not all(c in room.air for c in cells):
            plan.warnings.append(f"room '{room.name}': {size} engine {i + 1} does not fit "
                                 f"(needs {width / VOX:.2f} x {(max(fy) - min(fy) + 1) / VOX:.2f} x "
                                 f"{(max(fz) - min(fz) + 1) / VOX:.2f} m clear, W x H x L)")
            continue
        plan.components.append(Placed(piece, origin, color=ENGINE_COLOUR))
        room.engines.append(size)
        for c in cells:
            room.air.discard(c)


def _add_hatch(h, deck_layers, cfg, skin, region, top_hull, plan):
    """Never make an unfinished access opening. Complete assemblies are installed later."""
    name = h.get("name", f"access at z={h['z']:g} m")
    plan.warnings.append(f"{name}: floor left sealed; no complete ladder/hatch assembly installed")
