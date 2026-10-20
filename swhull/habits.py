"""Finishing passes that experienced Stormworks builders apply to a block shape.

Each pass changes only whole pieces after the shape is fitted, keeps every voxel's colour,
and reports what it did, so a model and the player can check it against the brief.
"""
import math

import numpy as np

from .pieces import IDENTITY, PYRAMID, ROTATIONS, WEDGE, WEIGHT, Placed, apply

# Single-voxel pieces a finished edge may replace: plain blocks, and the 1x1 closeouts the
# fitter leaves on boxes that are not a whole number of blocks wide.
_EDGE_PIECES = {"01_block", "02_wedge", "03_pyramid", "04_invpyramid"}
_ROTATIONS = {}


def _rotation(piece, verts):
    """The rotation that puts `piece` exactly on `verts` (voxel-centred, in half blocks)."""
    key = (piece.d, frozenset(verts))
    if key not in _ROTATIONS:
        want = {tuple(round(c, 3) for c in v) for v in verts}
        _ROTATIONS[key] = next(Q for Q in ROTATIONS
                               if {tuple(round(c, 3) for c in apply(Q, v)) for v in piece.verts} == want)
    return _ROTATIONS[key]


def _chamfer(sx, sz):
    """Vertical 1x1 wedge cutting the (sx, sz) corner of a voxel."""
    return _rotation(WEDGE, [(a * .5, y, b * .5) for a, b in ((-sx, -sz), (sx, -sz), (-sx, sz))
                             for y in (-.5, .5)])


def _bevel(n):
    """1x1 wedge sloping up and out toward horizontal direction n along a roof edge."""
    t = (abs(n[2]), 0, abs(n[0]))   # along the edge
    return _rotation(WEDGE, [(n[0] * a * .5 + t[0] * c * .5, b * .5, n[2] * a * .5 + t[2] * c * .5)
                             for a, b in ((-1, -1), (1, -1), (-1, 1)) for c in (-1, 1)])


def _corner_cap(sx, sz):
    """1x1 pyramid closing a bevelled roof corner above a chamfer column."""
    o = (-sx * .5, -.5, -sz * .5)
    return _rotation(PYRAMID, [o, (sx * .5, -.5, -sz * .5), (-sx * .5, .5, -sz * .5), (-sx * .5, -.5, sz * .5)])


def _eligible(box):
    """Plain, straight-walled boxes at least 1 x 1 m and 0.75 m tall that leave edges to us."""
    spec = box.spec
    return (box.shape == "box" and not box.rotated and "corner_chamfer" not in spec
            and "corner_radius" not in spec and 2 * box.hw >= 4 and box.zl >= 4 and box.h >= 3
            and not (box.taper or box.rake_f or box.rake_b or box.waist or box.roof_radius))


def _plan(tag, cells, region, occupied, fixed):
    """{voxel: (piece, rotation)} finishing a box, or a reason it stays square."""
    top = max(v[1] for v in cells)
    roof = {(x, z) for x, y, z in cells if y == top}
    x0, x1 = min(x for x, _ in roof), max(x for x, _ in roof)
    z0, z1 = min(z for _, z in roof), max(z for _, z in roof)
    if len(roof) != (x1 - x0 + 1) * (z1 - z0 + 1):
        return None, "its roof is not a rectangle"

    def free(v):
        return v not in occupied

    def mine(v):
        return region.get(v) == tag and v not in fixed

    plan = {}
    for x, z in roof:
        sx = 1 if x == x1 else -1 if x == x0 else 0
        sz = 1 if z == z1 else -1 if z == z0 else 0
        if not (sx or sz):
            continue
        v = (x, top, z)
        out = [(x + sx, top, z)] if sx else []
        out += [(x, top, z + sz)] if sz else []
        if sx and sz:
            out.append((x + sx, top, z + sz))
        if not mine(v) or not free((x, top + 1, z)) or not all(free(c) and free((c[0], top + 1, c[2]))
                                                                 for c in out):
            return None, f"its roof edge at {v} is covered or joined to something"
        plan[v] = (PYRAMID, _corner_cap(sx, sz)) if sx and sz else (WEDGE, _bevel((sx, 0, sz)))
        if not (sx and sz):
            continue
        # The corner column, from under the roof down to the deck or whatever the box stands on.
        y = top - 1
        while True:
            c = (x, y, z)
            exposed = free((x + sx, y, z)) and free((x, y, z + sz)) and free((x + sx, y, z + sz))
            if not mine(c) or not exposed:
                break
            if not all(cell in occupied for cell in (
                    (x - sx, y, z), (x - 2 * sx, y, z), (x, y, z - sz), (x, y, z - 2 * sz))):
                return None, f"its corner at {c} has an opening next to it"
            plan[c] = (WEDGE, _chamfer(sx, sz))
            y -= 1
        if y == top - 1:
            return None, f"its corner below {v} meets another part"
        below = (x, y, z)
        if region.get(below) == tag and (free((x + sx, y, z)) or free((x, y, z + sz))):
            return None, f"its corner at {below} is half buried, so a chamfer would stop short"
    return plan, None


def finish_boxes(placed, boxes, box_vox, region, fixed=()):
    """Chamfer exposed vertical corners and bevel roof edges of superstructure boxes.

    Veterans run a column of 1x1 wedges up nearly every free vertical corner (66-85% of the
    vertical slopes on the reference ships), bevel roof edges with 1x1 wedges and close each
    roof corner with a pyramid. A box is finished completely or not at all: every corner
    column must reach the deck, the box below or a buried layer, and no other part may touch a
    finished edge. Fitted slopes that lie wholly on those edges are replaced; one that reaches
    past them keeps the box square. Returns (pieces, report: finished boxes, why others are
    square).
    """
    piece_at = {}
    for p in placed:
        for v in p.voxels():
            piece_at[tuple(v)] = p
    occupied = set(piece_at)
    removed, added, finished, square = set(), [], [], {}
    fixed = set(fixed)
    for i, b in enumerate(boxes):
        if not _eligible(b):
            continue
        tag = f"box{i}"
        cells = {v for v in box_vox.get(b.name, ()) if region.get(v) == tag}
        if not cells:
            continue
        plan, reason = _plan(tag, cells, region, occupied, fixed)
        if plan is not None:
            old = {id(p): p for v in plan if (p := piece_at.get(v)) is not None}
            if any(not all(tuple(c) in plan for c in p.voxels()) for p in old.values()):
                plan, reason = None, "a fitted slope runs across one of its edges"
        if plan is None:
            square[b.name] = reason
            continue
        for v, (piece, Q) in plan.items():
            source = piece_at.get(v) or next(
                (piece_at[n] for n in ((v[0], v[1] - 1, v[2]), (v[0], v[1], v[2] - 1), (v[0], v[1], v[2] + 1),
                                       (v[0] - 1, v[1], v[2]), (v[0] + 1, v[1], v[2])) if n in piece_at), None)
            added.append(Placed(piece, v, Q, color=source.color if source else b.spec.get("color", "C2C3C7")))
        removed.update(old)
        finished.append(b.name)
    out = [p for p in placed if id(p) not in removed] + added
    return out, {"finished": finished, "square": square}


# --- ballast ---------------------------------------------------------------------------------

# Mass per submerged hull voxel at the painted waterline of the reference ships (Hawk 1.47,
# Artemis 1.6-2.2, Shard 1.1-1.6). A band from players' builds, not a game constant: drafts
# are estimates until an in-game check pins it down. Trim and stability barely depend on it,
# because the same constant scales weight and buoyancy.
K_ESTIMATE = 1.5
K_RANGE = (1.3, 1.8)
BALLAST_LIMIT = 40     # weight blocks per 1,000 structural parts: the most the references carry
TRIM_TOLERANCE = 1.0   # voxels the bow or stern may sit low before ballast levels it,
TRIM_ANGLE = 1.0       # or this many degrees on a longer hull, whichever is more
MAX_LAYERS = 3         # ballast stands at most this many blocks deep on the bottom skin
LOW_BAND = 0.25        # and within the bottom quarter of the hull (references: median 0-21%)
STABILITY = 0.1        # metacentric height wanted, as a fraction of the waterline beam


class Hull:
    """The hull envelope as per-layer sums: draft, centre of buoyancy and waterplane moments."""

    def __init__(self, cells):
        arr = np.array(list(cells), np.float64).reshape(-1, 3)
        self.lo = int(arr[:, 1].min())
        layers = int(arr[:, 1].max()) - self.lo + 1
        idx = arr[:, 1].astype(np.int64) - self.lo
        self.n = np.bincount(idx, minlength=layers).astype(np.float64)
        self.sx = np.bincount(idx, arr[:, 0], layers)
        self.sx2 = np.bincount(idx, arr[:, 0] ** 2, layers)
        self.sz = np.bincount(idx, arr[:, 2], layers)
        self.sz2 = np.bincount(idx, arr[:, 2] ** 2, layers)
        order = np.argsort(idx, kind="stable")
        bounds = np.searchsorted(idx[order], np.arange(layers + 1))
        self.zspan, self.xspan = np.zeros(layers), np.zeros(layers)
        for i in range(layers):
            sel = arr[order[bounds[i]:bounds[i + 1]]]
            if len(sel):
                self.zspan[i] = np.ptp(sel[:, 2]) + 1
                self.xspan[i] = np.ptp(sel[:, 0]) + 1

    def float(self, mass, k=K_ESTIMATE):
        """Floating plane y, volume, centre of buoyancy (z, y), waterplane IT, IL, length, beam."""
        need, V, mz, my = mass / k, 0.0, 0.0, 0.0
        for i, a in enumerate(self.n):
            if not a:
                continue
            y = self.lo + i
            if V + a >= need:
                f = (need - V) / a
                V, mz, my = V + a * f, mz + self.sz[i] * f, my + a * f * (y - 0.5 + f / 2)
                it = self.sx2[i] - self.sx[i] ** 2 / a + a / 12
                il = self.sz2[i] - self.sz[i] ** 2 / a + a / 12
                return {"plane": y - 0.5 + f, "volume": V, "lcb": mz / V, "kb": my / V,
                        "it": it, "il": il, "length": self.zspan[i], "beam": self.xspan[i]}
            V, mz, my = V + a, mz + self.sz[i], my + a * y
        return None

    def assess(self, mass, centre, k=K_ESTIMATE):
        f = self.float(mass, k)
        if f is None:
            return None
        gm = f["kb"] + f["it"] / f["volume"] - centre[1]
        # The bow (+) or stern (-) sinks this far at the ends: trim angle = lever * V / IL.
        end = (centre[2] - f["lcb"]) * f["volume"] / f["il"] * f["length"] / 2
        return {**f, "gm": gm, "end": end}


def _stacks(hull_cells, occupied, blocked, ceiling):
    """Free cells on the bottom skin per (x, z) column, at most MAX_LAYERS deep, under a deck
    and below `ceiling`, so weight stays low where a V-shaped stern lifts the bottom."""
    columns = {}
    for x, y, z in hull_cells:
        columns.setdefault((x, z), []).append(y)
    stacks = {}
    for (x, z), ys in columns.items():
        ys.sort()
        y = ys[0]
        while (x, y, z) in occupied:
            y += 1
        if y == ys[0] or not any((x, top, z) in occupied for top in range(y + 1, ys[-1] + 1)):
            continue    # nothing to stand on, or open to the sky (a cockpit floor)
        hull, cells = set(ys), []
        while (len(cells) < MAX_LAYERS and y < ceiling and y in hull and (x, y, z) not in occupied
               and (x, y, z) not in blocked):
            cells.append((x, y, z))
            y += 1
        if cells:
            stacks[(x, z)] = cells
    return stacks


def ballast(placed, region, interior, waterline, structural, mode="auto"):
    """Add weight blocks low in the hull the way veterans do, and estimate how it floats.

    Levels the trim (moves the centre of mass over the centre of buoyancy), weighs down a hull
    that floats more than a block above its painted waterline, and keeps the metacentric height
    at least STABILITY times the beam. Blocks go in port/starboard pairs on the bottom skin,
    under a deck, away from rooms and access paths, never more than BALLAST_LIMIT per 1,000
    structural parts. `waterline` is the painted waterline as a y plane in voxels. Returns
    (pieces, report); mode "none" only reports.
    """
    hull_cells = [v for v, tag in region.items() if tag == "hull"]
    if not hull_cells:
        return placed, None
    hull = Hull(hull_cells)
    mass = sum(p.piece.mass for p in placed)
    moment = np.zeros(3)
    for p in placed:
        moment += p.piece.mass * np.mean(p.voxels(), axis=0)
    before = hull.assess(mass, moment / mass)
    report = {"blocks": 0, "reasons": [], "shortfall": None, "before": before}
    added = []
    if mode == "auto" and before is not None:
        occupied = {tuple(v) for p in placed for v in p.voxels()}
        blocked = set(interior.reserved) | set(interior.carve)
        for room in interior.rooms:
            blocked |= room.air
        ceiling = hull.lo + max(MAX_LAYERS, round(LOW_BAND * len(hull.n)))
        stacks = _stacks(hull_cells, occupied, blocked, ceiling)
        slots = [((x, z), (-x, z)) if x else ((x, z),) for x, z in stacks
                 if x > 0 and (-x, z) in stacks or x == 0]
        depth = dict.fromkeys(slots, 0)
        limit = int(BALLAST_LIMIT * structural / 1000)
        tolerance = max(TRIM_TOLERANCE, math.tan(math.radians(TRIM_ANGLE)) * before["length"] / 2)
        levelling = abs(before["end"]) > tolerance

        def open_slots():
            return [s for s in slots if all(depth[s] < len(stacks[c]) for c in s)]

        while True:
            state = hull.assess(mass, moment / mass)
            if state is None:
                break
            high = state["plane"] < waterline - 1
            if levelling and abs(state["end"]) > tolerance / 2:
                goal = "level the trim"
                # Bow down: weight at the stern, aftmost and lowest first; stern down: the reverse.
                sign = 1 if state["end"] > 0 else -1
                pick = min(open_slots(), key=lambda s: (sign * s[0][1], depth[s]), default=None)
            elif high or state["gm"] < STABILITY * state["beam"]:
                goal = "bring it down to its painted waterline" if high else "lower the centre of mass"
                pick = min(open_slots(), key=lambda s: (stacks[s[0]][depth[s]][1], abs(s[0][1] - state["lcb"])),
                           default=None)
            else:
                break
            if len(added) + (len(pick) if pick else 1) > limit:
                report["shortfall"] = f"stopped at the limit of {limit} weight blocks before it could {goal}"
                break
            if pick is None:
                report["shortfall"] = f"no free bottom space left to {goal}"
                break
            if goal not in report["reasons"]:
                report["reasons"].append(goal)
            for column in pick:
                v = stacks[column][depth[pick]]
                added.append(Placed(WEIGHT, v, IDENTITY, color="4A4A4A", name="ballast"))
                mass += WEIGHT.mass
                moment += WEIGHT.mass * np.array(v, np.float64)
            depth[pick] += 1
    report.update(blocks=len(added), after=hull.assess(mass, moment / mass), waterline=waterline,
                  bottom=hull.lo - 0.5, drafts=[hull.float(mass, k) for k in K_RANGE])
    return placed + added, report
