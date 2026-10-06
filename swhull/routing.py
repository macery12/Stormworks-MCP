"""Bounded, collision-free physical pipe routing between declared component faces."""
import copy
import heapq
from itertools import count

from . import definitions
from .connections import transmission_ports
from .editing import bounds, identify, vector
from .pieces import DIRS, Placed, add, apply, neg, sub

PIPE_DEFINITIONS = ("trans_straight", "trans_angle", "trans_t", "trans_corner", "trans_cross",
                    "trans_t_corner", "trans_cross_corner", "trans_omni")
MAX_ROUTE_CELLS = 200000


def compatible(a, b):
    if a["trans_type"] == b["trans_type"]:
        return True
    # Installed transmission pipes carry mechanical power or fluid. A mismatched
    # pair of two functional components still cannot silently convert the medium.
    return ({a["trans_type"], b["trans_type"]} == {1, 2}
            and any(p["definition"].startswith("trans_") for p in (a, b)))


def face(parts, endpoint):
    if not isinstance(endpoint, dict) or set(endpoint) != {"part_id", "surface_index"}:
        raise ValueError("route endpoint needs part_id and surface_index from query_connections")
    if (not isinstance(endpoint["part_id"], str) or not isinstance(endpoint["surface_index"], int)
            or isinstance(endpoint["surface_index"], bool)):
        raise ValueError("route part_id must be text and surface_index an integer")
    found = [p for p in parts if p.uid == endpoint["part_id"]]
    if len(found) != 1:
        raise ValueError("stale route part ID; query_connections again")
    ports = [p for p in transmission_ports(found[0]) if p["surface_index"] == endpoint["surface_index"]]
    if len(ports) != 1:
        raise ValueError("surface_index is not a transmission face; query_connections again")
    return ports[0]


def _distance(a, b):
    return sum(abs(a[i] - b[i]) for i in range(3))


def _path(start, end, occupied, reserved, extent, *, initial_direction=None, final_direction=None):
    """Shortest path, then fewest bends, including the equipment-facing end bends.

    Heading is part of the search state: two arrivals at the same cell may have
    different continuation costs. A set of targets finds the closest reachable
    branch, rather than choosing an inaccessible target by Manhattan distance.
    """
    targets = {end} if isinstance(end, tuple) else set(end)
    lo, hi = extent
    for v in (start, *sorted(targets)):
        if v in occupied or v in reserved:
            p = occupied.get(v)
            raise ValueError(f"pipe exit blocked at {v}; part_id={p.uid if p else None}, "
                             f"definition={p.piece.d if p else 'reserved access'}; move the part or clear its port exit")
        if any(v[i] < lo[i] or v[i] > hi[i] for i in range(3)):
            raise ValueError(f"pipe endpoint {v} is outside route bounds")
    def heuristic(cell):
        return min(_distance(cell, v) for v in targets)

    initial = (start, initial_direction)
    queue, serial, previous, scores = [], count(), {initial: None}, {initial: (0, 0)}
    heapq.heappush(queue, ((heuristic(start), 0), (0, 0), next(serial), initial))
    while queue:
        _, cost, _, state = heapq.heappop(queue)
        cell, heading = state
        if cost != scores[state]:
            continue
        if cell in targets:
            result = []
            while state is not None:
                result.append(state[0])
                state = previous[state]
            return list(reversed(result))
        for direction in DIRS:
            v = add(cell, direction)
            if (heading is not None and direction == neg(heading) or v in occupied or v in reserved
                    or any(v[i] < lo[i] or v[i] > hi[i] for i in range(3))):
                continue
            bend = int(heading is not None and direction != heading)
            if v in targets and final_direction is not None:
                if direction == neg(final_direction):
                    continue
                bend += int(direction != final_direction)
            value, nxt = (cost[0] + 1, cost[1] + bend), (v, direction)
            if value >= scores.get(nxt, (float("inf"), float("inf"))):
                continue
            scores[nxt], previous[nxt] = value, state
            heapq.heappush(queue, ((value[0] + heuristic(v), value[1]), value, next(serial), nxt))
        if len(scores) > MAX_ROUTE_CELLS:
            raise ValueError("pipe search exceeds 200000 cells; supply tighter route bounds/waypoints")
    raise ValueError("no unobstructed pipe route inside the bounds; move equipment or provide waypoints")


def pipe_piece(directions, style="exposed"):
    if style not in ("exposed", "enclosed"):
        raise ValueError("pipe style must be exposed or enclosed")
    directions = set(directions)
    for base in PIPE_DEFINITIONS:
        d = base.replace("trans_", "trans_block_", 1) if style == "enclosed" else base
        data = definitions.metadata(d)
        if data is None:
            continue
        normals = [DIRS[s["orientation"]] for s in data["attachment_surfaces"] if s["trans_type"] > 0]
        if len(normals) != len(directions):
            continue
        # Six-port pieces need no combinatorial permutation search.
        from .pieces import ROTATIONS  # noqa: PLC0415
        for q in ROTATIONS:
            if {apply(q, v) for v in normals} == directions:
                return definitions.load(d), q
    raise ValueError(f"no installed {style} pipe matches directions {sorted(directions)}")


def route(parts, start, end, *, extent=None, waypoints=None, reserved=frozenset(), prefix="route", name="pipe route",
          pipe_style="auto", through_blocks=None, enclosed_cells=frozenset()):
    """Route exact ports; only explicitly selected plain blocks can become enclosed pipes."""
    if pipe_style not in ("auto", "exposed", "enclosed"):
        raise ValueError("pipe_style must be auto, exposed or enclosed")
    parts = identify(copy.deepcopy(parts))
    a, b = face(parts, start), face(parts, end)
    if a["part_id"] == b["part_id"] and a["surface_index"] == b["surface_index"]:
        raise ValueError("route endpoints must differ")
    if not compatible(a, b):
        raise ValueError("route faces have incompatible transmission types")
    occupied = {v: p for p in parts for v in p.voxels()}
    through_blocks = [] if through_blocks is None else through_blocks
    if (not isinstance(through_blocks, list) or len(through_blocks) > 100
            or any(not isinstance(uid, str) for uid in through_blocks)
            or len(set(through_blocks)) != len(through_blocks)):
        raise ValueError("through_blocks must be a list of at most 100 distinct plain block IDs")
    replacements = {}
    for uid in through_blocks:
        found = [p for p in parts if p.uid == uid]
        if len(found) != 1:
            raise ValueError("stale through_blocks ID; query_parts again")
        p = found[0]
        if p.piece.d != "01_block" or p.protected or p.settings:
            raise ValueError(f"through_blocks only replaces unconfigured, unlinked 01_block parts: {uid}")
        replacements[p.origin] = p
        del occupied[p.origin]
    if extent is None:
        extent = [[min(v[i] for v in occupied) - 4 for i in range(3)],
                  [max(v[i] for v in occupied) + 4 for i in range(3)]]
    extent = bounds(extent)
    entry, exit_cell = add(a["position"], a["normal"]), add(b["position"], b["normal"])
    port_exits = {add(f["position"], f["normal"]) for p in parts for f in transmission_ports(p)
                  if _face_id(f) not in {_face_id(a), _face_id(b)}}
    reserved = set(reserved) | (port_exits - {entry, exit_cell})
    if a["position"] == exit_cell and b["position"] == entry and a["normal"] == neg(b["normal"]):
        if replacements:
            raise ValueError("directly adjacent ports do not pass through the selected blocks")
        return copy.deepcopy(parts), []
    targets = [entry, *(vector(v, "waypoint") for v in (waypoints or [])), exit_cell]
    cells = []
    for i in range(len(targets) - 1):
        segment = _path(targets[i], targets[i + 1], occupied, reserved, extent,
                        initial_direction=a["normal"] if i == 0 else sub(cells[-1], cells[-2]) if len(cells) > 1 else None,
                        final_direction=neg(b["normal"]) if i + 2 == len(targets) else None)
        cells.extend(segment if not cells else segment[1:])
        # A subsequent segment cannot cross an earlier segment and create a fluid junction.
        for v in segment[:-1]:
            occupied[v] = parts[0]
    if len(set(cells)) != len(cells):
        raise ValueError("route waypoints create a loop or self intersection")
    unused = set(replacements) - set(cells)
    if unused:
        raise ValueError(f"route does not use selected wall blocks at {sorted(unused)}; add waypoints through them")
    result, added = [p for p in parts if p.uid not in through_blocks], []
    for i, v in enumerate(cells):
        before = sub(cells[i - 1], v) if i else neg(a["normal"])
        after = sub(cells[i + 1], v) if i + 1 < len(cells) else neg(b["normal"])
        style = "enclosed" if v in replacements or pipe_style == "enclosed" or pipe_style == "auto" and v in enclosed_cells else "exposed"
        piece, q = pipe_piece((before, after), style)
        paint = replacements[v].color if v in replacements else "687681"
        p = Placed(piece, v, q, paint, f"{prefix}:{i}", name)
        added.append(p)
    result.extend(added)
    return result, added


def _face_id(port):
    return port["part_id"], port["surface_index"]


def tree(parts, endpoints, *, extent, reserved=frozenset(), prefix="driveline", enclosed_cells=frozenset()):
    """Build a mechanical branch network with exact T/corner faces, without open outlets."""
    ports = [face(parts, e) for e in endpoints]
    if len(ports) < 2 or len({_face_id(p) for p in ports}) != len(ports):
        raise ValueError("tree needs at least two distinct mechanical faces")
    if any(p["trans_type"] != 1 for p in ports):
        raise ValueError("tree routing is for mechanical-power faces only")
    occupied = {v: p for p in parts for v in p.voxels()}
    entries = {add(p["position"], p["normal"]) for p in ports}
    reserved = set(reserved) | ({add(p["position"], p["normal"]) for item in parts
                                for p in transmission_ports(item) if _face_id(p) not in {_face_id(q) for q in ports}} - entries)
    extent, cells, directions = bounds(extent), set(), {}
    for port in ports:
        entry = add(port["position"], port["normal"])
        if not cells:
            if entry in occupied or entry in reserved:
                raise ValueError(f"driveshaft port exit blocked at {entry}")
            cells.add(entry)
            directions[entry] = {neg(port["normal"])}
            continue
        path = _path(entry, cells, occupied, reserved, extent, initial_direction=port["normal"])
        # Connect at the first touched cell; no cycles or unused pipe faces.
        for j, v in enumerate(path):
            directions.setdefault(v, set()).add(neg(port["normal"]) if j == 0 else sub(path[j - 1], v))
            if v in cells:
                break
            cells.add(v)
            if j + 1 < len(path):
                directions[v].add(sub(path[j + 1], v))
    added = []
    for i, v in enumerate(sorted(cells)):
        piece, q = pipe_piece(directions[v], "enclosed" if v in enclosed_cells else "exposed")
        added.append(Placed(piece, v, q, "687681", f"{prefix}:{i}", "wheel driveshaft"))
    return [*parts, *added]


def active_routes(record):
    active = {}
    for i, op in enumerate(record.get("route_edits", [])):
        if isinstance(op, dict) and op.get("op") == "remove":
            if set(op) != {"op", "route_id"} or op["route_id"] not in active:
                raise ValueError("stale route_id; query_connections again")
            del active[op["route_id"]]
        else:
            active[f"route:{i}"] = op
    return active


def apply_routes(record, parts, info=None):
    active = active_routes(record)
    if not active:
        return parts
    from .components import owners, validate_placement  # noqa: PLC0415
    from .pieces import BY_NAME  # noqa: PLC0415
    reserved = set(info["interior"].reserved) if info else set()
    if record.get("kind") == "land":
        owner = owners(parts)
        for p in parts:
            if p.piece.d.startswith("seat") or p.piece.d.startswith("battery"):
                reserved.update(validate_placement(p, {"vehicle_kind": "land"},
                                                  {v: q for v, q in owner.items() if q is not p}))
    for route_id, op in active.items():
        if (not isinstance(op, dict) or set(op) - {"op", "from", "to", "bounds", "waypoints", "name", "pipe_style", "through_blocks"}
                or op.get("op", "route") != "route"):
            raise ValueError("route needs from/to face endpoints and optional bounds, waypoints, name, pipe_style, through_blocks")
        parts, _ = route(parts, op.get("from"), op.get("to"), extent=op.get("bounds"),
                         waypoints=op.get("waypoints"), reserved=reserved, prefix=route_id,
                         name=op.get("name", route_id), pipe_style=op.get("pipe_style", "auto"),
                         through_blocks=op.get("through_blocks"))
    owner = owners(parts)
    for p in parts:
        if p.uid.startswith("route:") and p.piece.d not in BY_NAME:
            validate_placement(p, {}, {v: q for v, q in owner.items() if q is not p})
    return parts
