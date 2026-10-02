"""Body-local transmission-port adjacency evidence; no assumed flow or type conversion."""
from collections import defaultdict

from . import definitions
from .pieces import DIRS, add, apply, neg


def transmission_ports(p):
    data = definitions.metadata(p.piece.d) or {}
    return [{"part_id": p.uid, "definition": p.piece.d, "surface_index": i,
             "position": add(p.origin, apply(p.Q, surface["position"])),
             "normal": apply(p.Q, DIRS[surface["orientation"]]), "trans_type": surface["trans_type"]}
            for i, surface in enumerate(data.get("attachment_surfaces", []))
            if surface["trans_type"] > 0 and 0 <= surface["orientation"] < 6]


def adjacency(parts, body_id):
    ports = [port for p in parts for port in transmission_ports(p)]
    index = defaultdict(list)
    for port in ports:
        index[(port["position"], port["normal"])].append(port)
    connections, touched = [], set()
    for port in ports:
        pid = (port["part_id"], port["surface_index"])
        for other in index[(add(port["position"], port["normal"]), neg(port["normal"]))]:
            oid = (other["part_id"], other["surface_index"])
            if port["part_id"] == other["part_id"] or pid >= oid:
                continue
            touched.update((pid, oid))
            connections.append({"body_id": body_id, "ports": [port, other],
                                "compatibility": "same_declared_type" if port["trans_type"] == other["trans_type"]
                                else "requires_game_verification"})
    return connections, [{"body_id": body_id, **p} for p in ports
                         if (p["part_id"], p["surface_index"]) not in touched]
