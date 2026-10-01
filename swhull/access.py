"""Preflight complete manual doors and vertical access before carving any structure."""
from itertools import product

from . import definitions
from .components import mounted
from .pieces import BLOCK, IDENTITY, Placed, add, find_rotation


def _occupied(plan, skin):
    return (set(plan.blocks) | skin) - plan.carve


def _cut(plan, cells, skin):
    for v in cells:
        plan.blocks.pop(v, None)
        if v in skin:
            plan.carve.add(v)


def install_door(room, side, normal, anchor, skin, plan, top_hull=None):
    piece, data = definitions.load("door_manual"), definitions.metadata("door_manual")
    if piece is None or data is None:
        return False, "manual door definition missing"
    q = find_rotation([(tuple(data["directions"]["door_normal"]), normal),
                       (tuple(data["directions"]["door_up"]), (0, 1, 0))])
    relative = [tuple(sum(q[i][j] * v[j] for j in range(3)) for i in range(3)) for v in piece.footprint]
    origin = (anchor[0], anchor[1] - min(v[1] for v in relative), anchor[2])
    p = Placed(piece, origin, q, "B5BCC4", f"access:door:{room.name}:{side}", f"{room.name} {side} door")
    cells, occupied = set(p.voxels()), _occupied(plan, skin)
    if top_hull and any(v in skin and (t := top_hull(v[0], v[2])) is not None and v[1] <= t for v in cells):
        return False, "exterior openings below the main deck are prohibited"
    axis = next(i for i, n in enumerate(normal) if n)
    for existing in plan.components:
        if (existing.piece.d == "door_manual" and existing.origin[axis] == p.origin[axis]
                and len(cells & set(existing.voxels())) >= len(cells) // 2):
            return True, "shared existing manual door"
    component_cells = {v for item in plan.components for v in item.voxels()}
    if not cells <= occupied or cells & component_cells:
        return False, "complete manual frame does not fit the wall"
    lateral = 2 if axis == 0 else 0
    centre = (min(v[lateral] for v in cells) + max(v[lateral] for v in cells)) // 2
    approach = set()
    base = min(v[1] for v in cells)
    for offset, side_step, y in product(range(-1, 2), (-2, -1, 1, 2), range(base, base + 8)):
        v = [0, y, 0]
        v[axis], v[lateral] = p.origin[axis] + side_step, centre + offset
        approach.add(tuple(v))
    if approach & (occupied - cells | component_cells):
        return False, "manual door approach is obstructed"
    candidate_owner = {v: Placed(BLOCK, v) for v in occupied - cells}
    if not mounted(p, candidate_owner):
        return False, "manual frame lacks mounting contact"
    _cut(plan, cells, skin)
    plan.components.append(p)
    plan.reserved.update(approach)
    return True, "manual door installed"


def install_hatch(h, cfg, skin, region, top_hull, plan):
    name = h.get("name", f"access at z={h['z']:g} m")
    hatch, data = definitions.load("door_manual_small"), definitions.metadata("door_manual_small")
    ladder = definitions.load("ladder_small")
    if hatch is None or data is None or ladder is None:
        return False, "manual hatch/ladder definitions missing"
    if h.get("size", .75) != .75:
        return False, "standard manual access uses a 0.75 m opening; requested size unsupported"
    x, z = round(h.get("x", 0) * 4), round(h["z"] * 4)
    if h.get("floor") is not None:
        floor = round(h["floor"] * 4) - 1
    elif h.get("deck", "main") == "main":
        floor = top_hull(x, z)
    else:
        decks = sorted(cfg.get("decks", []))
        try:
            floor = round(decks[int(h["deck"])] * 4) - 1
        except (ValueError, IndexError, TypeError):
            return False, "unknown deck index"
    if floor is None:
        return False, "no deck below requested position"
    q = find_rotation([(tuple(data["directions"]["door_normal"]), (0, 1, 0)),
                       (tuple(data["directions"]["door_up"]), (0, 0, 1))])
    cap = Placed(hatch, (x, floor, z), q, "B5BCC4", f"access:{name}:hatch", f"{name} hatch")
    cut = set(cap.voxels())
    occupied = _occupied(plan, skin)
    existing_components = {v for p in plan.components for v in p.voxels()}
    if not cut <= occupied or cut & existing_components or any(v[1] != floor for v in cut):
        return False, "complete hatch frame needs a flat, unobstructed deck"
    if any(v in skin and (t := top_hull(v[0], v[2])) is not None and v[1] < t for v in cut):
        return False, "exterior openings below the main deck are prohibited"
    # Do not leave a second, uncut layer blocking the opening below the hatch.
    if any(add(v, (0, -1, 0)) in occupied for v in cut if v[2] >= z - 1):
        return False, "deck is too thick or the hatch opens onto a wall"
    if h.get("bottom") is not None:
        lower = round(h["bottom"] * 4)
    else:
        bottom = min(v[1] for v in region) if region else 0
        lower = next((y + 1 for y in range(floor - 1, bottom - 1, -1)
                      if (x, y, z) in occupied), None)
    if lower is None or floor - lower < 4:
        return False, "no lower landing with enough height"
    first = floor - ((floor - lower) // 4) * 4
    if first - lower > 2:
        return False, "lowest rung would be more than 0.5 m above the landing"
    # A rear shaft wall carries the rungs. Both landings need a supported 3x3 passage.
    backing = set(product(range(x - 1, x + 2), range(first, floor), [z - 2]))
    if not backing <= region.keys() or backing & existing_components or backing & skin:
        return False, "ladder backing cannot fit inside the structure"
    rungs = [Placed(ladder, (x, y, z - 1), IDENTITY, "8A8F96",
                    f"access:{name}:rung:{i}", f"{name} ladder {i + 1}")
             for i, y in enumerate(range(first, floor, 4))]
    rung_cells = {v for p in rungs for v in p.voxels()}
    if len(rung_cells) != sum(len(p.voxels()) for p in rungs) or rung_cells & (
            (occupied - cut - backing) | existing_components | cut):
        return False, "ladder/climbing space is obstructed"
    climbing = set(product(range(x - 1, x + 2), range(lower, floor + 9), range(z, z + 2)))
    if climbing & ((occupied - cut) | existing_components | backing | rung_cells):
        return False, "ladder/climbing space is obstructed"
    for landing_y in (lower, floor + 1):
        floor_cells = set(product(range(x - 1, x + 2), [landing_y - 1], range(z + 2, z + 5)))
        clear = set(product(range(x - 1, x + 2), range(landing_y, landing_y + 8), range(z + 2, z + 5)))
        if not floor_cells <= occupied or clear & ((occupied - cut) | existing_components | backing | rung_cells):
            return False, "landing needs 0.75 m supported passage and 2 m headroom"
    candidate_owner = {v: Placed(BLOCK, v) for v in (occupied - cut) | backing}
    if not mounted(cap, candidate_owner) or any(not mounted(p, candidate_owner) for p in rungs):
        return False, "hatch/ladder mounting contact is incomplete"
    # Commit all structural changes together only after the full assembly passes.
    _cut(plan, cut, skin)
    plan.blocks.update({v: "8A8F96" for v in backing})
    plan.components.extend([cap, *rungs])
    plan.reserved.update(climbing - cut)
    for landing_y in (lower, floor + 1):
        plan.reserved.update(product(range(x - 1, x + 2), range(landing_y, landing_y + 8),
                                     range(z + 2, z + 5)))
    for room in plan.rooms:
        room.air -= backing | rung_cells | cut
    return True, f"manual hatch and {len(rungs)} ladder segments installed"
