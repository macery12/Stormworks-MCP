"""Optional style rule sets: habits taken from the player's own fixes, checked only on request.

None of these are game rules. A vehicle that breaks them still loads and works; preflight reports
them as warnings when the caller names the rule set. Frame: integer blocks, +y up, +z forward.
"""
from collections import defaultdict

from .land import category
from .part_policy import PREBUILT_ENGINES
from .pieces import BY_NAME, add, apply

RULE_SETS = {
    "boat_engine_room": "engines enclosed by the hull below a deck; propellers and rudders not behind the "
                        "transom (from the player's fix of 'Mini Speedboat')",
    "bow_tip": "a near-symmetric hull is an exact mirror image and its stem ends three wide, not on a "
               "one-wide stub (from the player's fix of 'Slim Speedboat')",
    "pipe_colours": "exposed pipes painted by contents in ISO 14726 colours (fuel brown, fresh water blue, sea "
                    "water green, exhaust black, air maroon, oil and shafts orange)",
}
MARINE_PROPELLERS = ("propeller", "large_propeller", "giga_prop_small")
RUDDERS = ("rudder", "rudder_surface")
SIDES = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


def check(parts, rule_sets):
    """Warnings for each requested rule set; an empty list when every habit is followed."""
    unknown = [name for name in rule_sets if name not in RULE_SETS]
    if unknown:
        raise ValueError(f"unknown style rule set {unknown[0]!r}; choose from {', '.join(RULE_SETS)}")
    out = []
    for name in dict.fromkeys(rule_sets):
        out += [{"rule_set": name, "severity": "warning", **row} for row in _CHECKS[name](parts)]
    return out


def _structure(parts):
    return {v for p in parts if p.piece.d in BY_NAME for v in p.voxels()}


def _engine(d):
    return d in PREBUILT_ENGINES or (d.startswith("modular_engine") and category(d) == "propulsion")


def engine_room(parts):
    structure = _structure(parts)
    if not structure:
        return []
    lo = [min(v[i] for v in structure) for i in range(3)]
    hi = [max(v[i] for v in structure) for i in range(3)]

    def walled(v, d):
        while all(lo[i] <= v[i] <= hi[i] for i in range(3)):
            v = add(v, d)
            if v in structure:
                return True
        return False

    stern = lo[2]
    rows = []
    for p in parts:
        cells, label = p.voxels(), p.name or p.piece.d
        if _engine(p.piece.d):
            open_sides = sorted({d for v in cells for d in SIDES if not walled(v, d)})
            if open_sides:
                rows.append({"part_id": p.uid, "message": f"engine '{label}' is not enclosed by the hull "
                             f"(open toward {open_sides[0]}); this habit keeps engines below a deck"})
        elif p.piece.d in MARINE_PROPELLERS and min(v[2] for v in cells) < stern - 1:
            rows.append({"part_id": p.uid, "message": f"propeller '{label}' hangs "
                         f"{stern - 1 - min(v[2] for v in cells)} block(s) behind the transom; this habit sets "
                         "the hub into the transom with only the blades aft"})
        elif p.piece.d in RUDDERS and min(v[2] for v in cells) < stern:
            rows.append({"part_id": p.uid, "message": f"rudder '{label}' reaches {stern - min(v[2] for v in cells)} "
                         "block(s) behind the transom; this habit keeps it under the hull"})
    return rows


def _shape(p):
    return frozenset(tuple(round(2 * c) for c in add(p.origin, apply(p.Q, v))) for v in p.piece.verts)


def bow_tip(parts):
    hull = [p for p in parts if p.piece.d in BY_NAME]
    if not hull:
        return []
    xs = [v[0] for p in hull for v in p.voxels()]
    x2 = 2 * (min(xs) + max(xs))
    shapes = {_shape(p) for p in hull}
    lonely = [p for p in hull if frozenset((x2 - x, y, z) for x, y, z in _shape(p)) not in shapes]
    rows = []
    # Under 90% mirrored, the vehicle is asymmetric on purpose and the habit does not apply.
    if lonely and len(lonely) <= 0.1 * len(hull):
        rows.append({"part_ids": [p.uid for p in lonely[:20]],
                     "message": f"{len(lonely)} of {len(hull)} hull pieces have no mirror-image partner across "
                                f"x = {x2 / 4:g}; this habit mirrors one side onto the other"})
    owner = {v: p for p in hull for v in p.voxels()}
    tip = max(v[2] for v in owner)
    row_by_layer = defaultdict(list)
    for v, p in owner.items():
        if v[2] == tip:
            row_by_layer[v[1]].append((v[0], p))
    for y, row in sorted(row_by_layer.items()):
        if len(row) == 1 and not _forefoot(row[0][1]):
            rows.append({"part_ids": [row[0][1].uid], "message": f"the stem ends one block wide at y={y}; "
                         "this habit ends it on wedge, block, wedge"})
    return rows


def _forefoot(p):
    """A single slope under the nose that faces down and forward is a forefoot, not a stub."""
    from .smooth import _slope  # noqa: PLC0415
    try:
        normal = apply(p.Q, _slope(p.piece)[0])
    except (IndexError, KeyError, TypeError, ValueError):
        return False
    return normal[1] < -0.4 and normal[2] > 0


def pipe_colours(parts):
    from .networks import physical_graph  # noqa: PLC0415
    from .pipe_colours import COLOURS, medium  # noqa: PLC0415
    graph, faces = physical_graph(parts)
    by_id = {p.uid: p for p in parts}
    face = {(f["part_id"], f["surface_index"]): f for f in faces}
    own = defaultdict(list)
    for key in face:
        own[key[0]].append(key)
    pipe = {uid for uid, p in by_id.items() if p.piece.d.startswith("trans_")}
    seen, rows = set(), []
    for start in face:
        if start[0] not in pipe or start in seen:
            continue
        network, ends, stack = set(), [], [start]
        while stack:
            key = stack.pop()
            if key in seen:
                continue
            seen.add(key)
            if key[0] not in pipe:
                ends.append(face[key])
                continue
            network.add(key[0])
            stack.extend(n for n in graph[key] if n not in seen)
            stack.extend(k for k in own[key[0]] if k not in seen)
        contents = {medium(parts, e, e) for e in ends} - {None}
        if len(contents) != 1:
            continue
        wanted = COLOURS[contents.pop()]
        wrong = [uid for uid in sorted(network) if not by_id[uid].piece.d.startswith("trans_block_")
                 and str(by_id[uid].color).upper() != wanted]
        if wrong:
            rows.append({"part_ids": wrong[:20], "message": f"{len(wrong)} exposed pipe(s) are not painted "
                         f"{wanted}, the ISO 14726 colour for what this network carries"})
    return rows


_CHECKS = {"boat_engine_room": engine_room, "bow_tip": bow_tip, "pipe_colours": pipe_colours}
