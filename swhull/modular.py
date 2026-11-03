"""Modular engines: parts joined by the game's couplings, and checks of each complete engine.

Modular engine parts join through couplings in their definitions (crankshaft to cylinder,
cylinder to manifold, drive belt to starter), not through pipes. Two couplings join when they
face each other across one block face, have the same type and fit: two neutral (0) ends, or a
male (1) and a female (2) end.
"""
from collections import defaultdict
from functools import cache

from . import definitions
from .pieces import DIRS, add, apply, neg

CRANKSHAFT = "modular_engine_crankshaft"
CYLINDERS = ("modular_engine_piston", "modular_engine_cylinder")
# The part on a manifold network that decides what it carries.
FEEDS = {"modular_engine_air_manifold": "air", "modular_engine_intake_manifold": "fuel",
         "modular_engine_exhaust_manifold_corner": "exhaust",
         "modular_engine_exhaust_manifold_straight": "exhaust", "modular_engine_coolant_manifold": "coolant"}
PLAIN_MANIFOLDS = frozenset(f"modular_engine_manifold_{k}" for k in ("corner", "straight", "t"))
AIR_SOURCES = frozenset(("air_filter", "water_inlet", "fluid_intake", "modular_engine_air_ram", "scoop_intake"))
EXHAUST_OUTLETS = frozenset(("fluid_exhaust", "water_inlet", "fluid_intake"))
FLUID_PORTS = frozenset(("water_inlet", "fluid_intake"))


@cache
def _local(d):
    out = []
    for c in (definitions.metadata(d) or {}).get("couplings", []):
        a = c["attributes"]
        orientation = int(a.get("orientation", "-1"))
        if 0 <= orientation < 6 and a.get("coupling_type"):
            out.append((a["coupling_type"], a.get("coupling_name", ""), int(a.get("coupling_gender", "0")),
                        tuple(int(round(v)) for v in c["position"]), orientation))
    return tuple(out)


def couplings(p):
    """World couplings of one part: (type, name, gender, cell, outward normal)."""
    return [(t, name, g, add(p.origin, apply(p.Q, pos)), apply(p.Q, DIRS[o]))
            for t, name, g, pos, o in _local(p.piece.d)]


def _fits(a, b):
    return a == b == 0 or {a, b} == {1, 2}


def joins(parts):
    """Coupled pairs: (part a, coupling name on a, part b, coupling name on b, type)."""
    index = defaultdict(list)
    for p in parts:
        if p.piece.d.startswith("modular_engine"):
            for c in couplings(p):
                index[(c[3], c[4])].append((p, c))
    out = []
    for (cell, normal), items in index.items():
        for p, (t, name, g, _, _) in items:
            for q, (t2, name2, g2, _, _) in index.get((add(cell, normal), neg(normal)), ()):
                if p is not q and t == t2 and _fits(g, g2) and id(p) < id(q):
                    out.append((p, name, q, name2, t))
    return out


def engines(parts):
    """Each modular engine (coupled parts holding a crankshaft) and the coupled pairs."""
    pairs = joins(parts)
    graph = defaultdict(list)
    for p, _, q, _, _ in pairs:
        graph[id(p)].append(q)
        graph[id(q)].append(p)
    seen, groups = set(), []
    for p in parts:
        if not p.piece.d.startswith(CRANKSHAFT) or id(p) in seen:
            continue
        group, stack = [], [p]
        seen.add(id(p))
        while stack:
            cur = stack.pop()
            group.append(cur)
            for n in graph[id(cur)]:
                if id(n) not in seen:
                    seen.add(id(n))
                    stack.append(n)
        groups.append(group)
    return groups, pairs


def _feeds(group, pairs):
    """What each cylinder's manifolds carry: the network of manifold couplings it is on, named
    by the air, fuel, exhaust or coolant manifolds on that network."""
    members = {id(p) for p in group}
    graph = defaultdict(list)
    for p, _, q, _, t in pairs:
        if t == "manifold" and id(p) in members and id(q) in members:
            graph[id(p)].append(q)
            graph[id(q)].append(p)
    out = {}
    for cylinder in group:
        if not cylinder.piece.d.startswith(CYLINDERS):
            continue
        found, stack, seen = set(), [cylinder], set()
        while stack:
            cur = stack.pop()
            if id(cur) in seen:
                continue
            seen.add(id(cur))
            if cur.piece.d in FEEDS:
                found.add(FEEDS[cur.piece.d])
            stack.extend(graph[id(cur)])
        out[cylinder.uid] = found
    return out


def through_valves(graph, parts, transmission_ports):
    """The pipe graph with fluid passing through valves and pumps (parts whose pipe faces are
    all fluid), so an air line with a relief valve still reaches its intake."""
    out = defaultdict(set, {k: set(v) for k, v in graph.items()})
    for p in parts:
        faces = transmission_ports(p)
        if len(faces) < 2 or p.piece.d.startswith("modular_engine") or any(f["trans_type"] != 2 for f in faces):
            continue
        keys = [(f["part_id"], f["surface_index"]) for f in faces]
        for k in keys:
            out[k].update(o for o in keys if o != k)
    return out


def check(parts, report, links, graph, by_id, ports, starts, reachable, tank_cells):
    """Add modular engine checks to a preflight report's `checks` and return engine summaries.

    `starts(p, label, typ)` gives a part's pipe faces for a node, `reachable(starts)` follows
    pipes, `tank_cells()` returns {cell: tank row} for block-built tanks."""
    groups, pairs = engines(parts)
    if not groups:
        return []
    driven_inputs = {(link["to"]["part_id"], str(link["to"]["port"])) for link in links if "to" in link}
    electric = defaultdict(set)
    for link in links:
        if link.get("type") == 4 and "from" in link:
            a, b = ((link[k]["part_id"], str(link[k]["port"])) for k in ("from", "to"))
            electric[a].add(b)
            electric[b].add(a)
    batteries = [(p.uid, str(n["index"])) for p in parts if p.piece.d.startswith("battery")
                 for n in ports(p) if n["type"] == 4]
    powered, queue = set(batteries), list(batteries)
    while queue:
        for n in electric[queue.pop()]:
            if n not in powered:
                powered.add(n)
                queue.append(n)

    def add_check(p, system, ok, detail):
        report["checks"].append({"part_id": p.uid, "system": system,
                                 "status": "connected" if ok else "missing", "detail": detail})

    def node(p, label):
        return next((n for n in ports(p) if n["label"] == label), None)

    def wired(p, label):
        n = node(p, label)
        return n is not None and (p.uid, str(n["index"])) in driven_inputs

    def reaches(p, label):
        return [by_id[uid] for uid in {k[0] for k in reachable(starts(p, label, 3))} if uid != p.uid]

    summaries = []
    for group in groups:
        crank = next(p for p in group if p.piece.d.startswith(CRANKSHAFT))
        cylinders = [p for p in group if p.piece.d.startswith(CYLINDERS)]
        feeds = _feeds(group, pairs)
        add_check(crank, "modular engine cylinders", bool(cylinders),
                  f"{len(cylinders)} cylinder(s) coupled to the crankshaft")
        for c in cylinders:
            missing = sorted({"air", "fuel", "exhaust"} - feeds[c.uid])
            add_check(c, "modular engine manifolds", not missing,
                      {"feeds": sorted(feeds[c.uid]), "missing": missing})
        starters = [p for p in group if p.piece.d == "modular_engine_starter"]
        add_check(crank, "modular engine starter", bool(starters),
                  "a starter on a drive belt" if starters else "no starter coupled to a drive belt")
        for s in starters:
            add_check(s, "control", wired(s, "Starter"), "Starter")
            n = node(s, "Electric")
            add_check(s, "electric", n is not None and (s.uid, str(n["index"])) in powered, "Electric")
        for p in group:
            if p.piece.d in ("modular_engine_air_manifold", "modular_engine_intake_manifold"):
                add_check(p, "control", wired(p, "Throttle"), "Throttle")
            if p.piece.d.startswith("modular_engine_clutch"):
                add_check(p, "control", wired(p, "Clutch Pressure"), "Clutch Pressure")
            if p.piece.d == "modular_engine_air_manifold":
                got = reaches(p, "Air")
                ok = any(q.piece.d in AIR_SOURCES for q in got)
                add_check(p, "air", ok, sorted({q.piece.d for q in got}) or "nothing: the air port is open")
            if p.piece.d.startswith("modular_engine_exhaust_manifold"):
                got = reaches(p, "Exhaust")
                ok = any(q.piece.d in EXHAUST_OUTLETS for q in got)
                add_check(p, "exhaust", ok, sorted({q.piece.d for q in got}) or "nothing: the exhaust port is open")
            if p.piece.d == "modular_engine_intake_manifold":
                got = reaches(p, "Fuel")
                tanks = [q for q in got if q.piece.d.startswith("fluid_tank_")]
                rows = {}
                if any(q.piece.d in FLUID_PORTS for q in got):
                    cells = tank_cells()
                    for q in got:
                        if q.piece.d in FLUID_PORTS:
                            for v in q.voxels():
                                if v in cells:
                                    rows[cells[v]["name"]] = cells[v]
                fluids = sorted({t["fluid"] for t in rows.values()}
                                | {"premade tank" for _ in tanks})
                add_check(p, "fuel", bool(tanks or rows),
                          {"tanks": sorted(rows) + [q.uid for q in tanks], "fluids": fluids}
                          if tanks or rows else "the fuel port does not reach a tank")
                if rows:
                    add_check(p, "diesel supply", any(t["fluid"] == "diesel" and t["saved_fill"] > 0
                                                      for t in rows.values()),
                              "a block-built tank on the fuel line holds diesel with a nonzero fill")
        clutches = [p for p in group if p.piece.d.startswith("modular_engine_clutch")]
        add_check(crank, "modular engine clutch", bool(clutches),
                  "power leaves the engine through a clutch on the crankshaft line")
        for c in clutches:
            got = {by_id[k[0]].piece.d for k in reachable(starts(c, "RPS", 2)) if k[0] != c.uid}
            add_check(c, "drivetrain", bool(got), sorted(got) or "nothing: the clutch output is open")
        coolant = [p for p in group if p.piece.d == "modular_engine_coolant_manifold"]
        for p in coolant:
            got = reaches(p, "Coolant A") + reaches(p, "Coolant B")
            add_check(p, "cooling loop", any(q.piece.d.startswith(("fluid_radiator", "heat_exchanger"))
                                             for q in got), sorted({q.piece.d for q in got}) or "open")
        notes = []
        if not coolant:
            notes.append("no coolant manifold: the engine is not liquid cooled; watch its temperature in game")
        summaries.append({"crankshaft_id": crank.uid, "parts": len(group), "cylinders": len(cylinders),
                          "starters": len(starters), "clutches": len(clutches),
                          "alternators": sum(p.piece.d == "modular_engine_alternator" for p in group),
                          "notes": notes})
    return summaries
