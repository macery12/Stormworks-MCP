"""Bodies of a multi-body vehicle: hinge, pivot and piston pairs, and which body a part joins.

Every body shares one build grid. A robotic part comes as a pair: the `_a` half in the parent
body and the `_b` half in its own child body, placed at the `_a` origin plus its rotated
`voxel_location_child`, with the same rotation (measured on the player's saves).
"""
from . import definitions
from .pieces import DIRS, Placed, add, apply

# _a half -> _b half, where the name alone does not say.
_PAIRS = {
    "multibody_compact_pivot_robotic_a": "multibody_compact_pivot_b",
    "multibody_compact_pivot_velocity_a": "multibody_compact_pivot_b",
    "multibody_compact_pivot_torque_a": "multibody_compact_pivot_torque_b",
    "multibody_robotic_pivot_01_a_fluid": "multibody_robotic_pivot_01_b_fluid",
    "multibody_velocity_pivot_01_a_fluid": "multibody_velocity_pivot_01_b_fluid",
    "multibody_velocity_pivot_01_a_torque": "multibody_velocity_pivot_01_b_torque",
    "linear_base": "linear_head",
    "linear_compact_base": "linear_compact_head",
    "linear_matic_a": "linear_matic_b",
}
# Child offsets for when no definitions are installed (tests, fresh machines).
_CHILD = {
    "multibody_compact_pivot_robotic_a": (0, 1, 0), "multibody_compact_pivot_velocity_a": (0, 1, 0),
    "multibody_compact_pivot_torque_a": (0, 1, 0), "multibody_pivot_a": (0, 2, 0),
    "multibody_pivot_torque_a": (0, 2, 0), "multibody_door_hinge_a": (0, 2, 0),
    "multibody_robotic_hinge_01_a": (0, 2, 0), "multibody_piston_suspension_a": (0, 2, 0),
    "multibody_suspension_a": (0, 3, 0), "multibody_robotic_pivot_01_a": (0, 1, 0),
    "multibody_robotic_pivot_01_a_fluid": (0, 1, 0), "multibody_velocity_pivot_a": (0, 1, 0),
    "multibody_velocity_pivot_01_a_fluid": (0, 1, 0), "multibody_velocity_pivot_01_a_torque": (0, 1, 0),
    "multibody_turret_small_a": (0, 1, 0), "multibody_turret_medium_a": (0, 1, 0),
    "multibody_turret_large_a": (0, 1, 0), "linear_base": (0, 2, 0), "linear_compact_base": (0, 1, 0),
    "linear_matic_a": (0, 6, 0),
}
PARENTS = {**{d: d[:-2] + "_b" for d in _CHILD if d.endswith("_a") and d not in _PAIRS}, **_PAIRS}
CHILDREN = frozenset(PARENTS.values())


def child_half(d):
    """The `_b` definition that a parent half `d` creates, or None."""
    return PARENTS.get(d)


def child_offset(d):
    data = definitions.metadata(d) or {}
    offset = data.get("directions", {}).get("voxel_location_child")
    return tuple(offset) if offset and any(offset) else _CHILD[d]


def child_origin(p):
    return add(p.origin, apply(p.Q, child_offset(p.piece.d)))


def root(parts):
    """The main body: the first part's body ("1" when it has none, as in generated drafts)."""
    return (parts[0].body if parts else "") or "1"


def next_id(parts, floor=0):
    ids = [int(p.body) for p in parts if p.body.isdigit()]
    return str(max([floor, 1, *ids]) + 1)


def assign(parts, new, explicit=None):
    """Give each new part a body: its explicit one, else the single body it touches.

    Parts added together can attach to each other, so bodies spread through the batch until
    nothing changes. A part touching two bodies needs an explicit body; one touching nothing
    joins the main body (and builds warn that it is loose)."""
    explicit = explicit or {}
    fresh = {id(p) for p in new}
    old = [p for p in parts if id(p) not in fresh]
    main = root(old or parts)
    known = {v: p.body or main for p in old for v in p.voxels()}
    pending = []
    for p in new:
        if explicit.get(id(p)):
            p.body = str(explicit[id(p)])
            known.update({v: p.body for v in p.voxels()})
        else:
            pending.append(p)
    changed = True
    while pending and changed:
        changed = False
        for p in list(pending):
            touching = {known[add(v, d)] for v in p.voxels() for d in DIRS if add(v, d) in known}
            if len(touching) > 1:
                raise ValueError(f"part {p.name or p.piece.d} at {p.origin} touches bodies "
                                 f"{', '.join(sorted(touching))}; give it a body")
            if touching:
                p.body = touching.pop()
                known.update({v: p.body for v in p.voxels()})
                pending.remove(p)
                changed = True
    for p in pending:
        p.body = main


def problems(parts):
    """Broken hinge, pivot and piston pairs, as messages. Edits compare before and after, so an odd
    save that already breaks a rule can still be edited elsewhere."""
    main = root(parts)
    at = {}
    for p in parts:
        at.setdefault(p.origin, []).append(p)
    out, claimed = set(), set()
    for p in parts:
        want = child_half(p.piece.d)
        if want is None:
            continue
        spot = child_origin(p)
        match = [c for c in at.get(spot, []) if c.piece.d == want and c.Q == p.Q]
        if not match:
            out.add(f"{p.piece.d} at {p.origin} has lost its {want} at {spot}; move, rotate or remove both "
                    "halves together")
            continue
        claimed.add(id(match[0]))
        if (match[0].body or main) == (p.body or main):
            out.add(f"{want} at {spot} must be in its own body, not the body of its {p.piece.d}")
    for p in parts:
        if p.piece.d in CHILDREN and id(p) not in claimed:
            out.add(f"{p.piece.d} at {p.origin} has no parent half; place the parent half and its child half "
                    "is added for you")
    # Bodies without a pair are normal: payloads on hardpoints, rope hooks, magnets and loose parts.
    return out


def spawn_children(parts, new, floor=0):
    """Add the child half, in a new body, for every new parent half."""
    out = []
    for p in new:
        d = child_half(p.piece.d)
        if d is None:
            continue
        piece = definitions.load(d)
        if piece is None:
            raise ValueError(definitions.unavailable(d))
        child = Placed(piece, child_origin(p), p.Q, p.color, f"{p.uid}:child",
                       f"{p.name} child" if p.name else "", body=next_id(parts + out, floor))
        out.append(child)
    return out


def summary(parts):
    """Bodies with part counts, in first-seen order."""
    main = root(parts)
    counts = {}
    for p in parts:
        b = p.body or main
        counts[b] = counts.get(b, 0) + 1
    return counts
