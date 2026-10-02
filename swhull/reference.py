"""Read-only, body-aware reference evidence. Saved observations never become game validation."""
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from . import definitions
from .components import mounting_contacts
from .connections import adjacency, transmission_ports
from .orientation import RUDDERS, profile, rudder_clearance
from .pieces import BLOCK, BY_NAME, Placed, add, apply, parse_r, r_attr, split_mirror, with_mirror
from .vehicle import MISSING_R


def xml_root(text):
    try:
        root = ET.fromstring(re.sub(r'(\s)(\d\w*)=', r'\1sw_\2=', text))
    except ET.ParseError as exc:
        raise ValueError(f"cannot read vehicle XML: {exc}") from exc
    if root.tag != "vehicle" or root.get("data_version") != "3":
        raise ValueError("reference analysis requires a data_version 3 vehicle")
    return root


def _position(node):
    return tuple(int(node.get(a, "0")) for a in "xyz") if node is not None else (0, 0, 0)


def _configuration(node):
    return {"tag": node.tag, "attributes": dict(node.attrib),
            **({"text": node.text.strip()} if node.text and node.text.strip() else {}),
            **({"children": [_configuration(c) for c in node]} if len(node) else {})}


def _ports(component, data):
    # Controller ports are configured per instance; the generic definition cannot describe them.
    processor = component.find("o/microprocessor_definition")
    if processor is None:
        return (data or {}).get("logic_nodes", [])
    return [{"index": n.get("id", str(i)), "label": node.get("label", ""),
             "type": int(node.get("type", "0")), "mode": int(node.get("mode", "0")),
             "position": _position(node.find("position"))}
            for i, n in enumerate(processor.findall("nodes/n"))
            if (node := n.find("node")) is not None]


def _controller(component):
    processor = component.find("o/microprocessor_definition")
    if processor is None:
        return None
    groups = list(processor.iter("group"))
    nodes = [n for group in groups for container in ("components", "components_bridge")
             for n in group.findall(f"{container}/c")]
    parents = {id(child): i for i, group in enumerate(groups) for child in group.findall("groups/group")}
    internal_links = [{"target_component_id": obj.get("id"), "input": child.tag,
                       "source_attributes": dict(child.attrib)} for n in nodes
                      for obj in n.findall("object") for child in obj if re.fullmatch(r"in\d+", child.tag)]
    return {"name": processor.get("name", ""), "port_count": len(processor.findall("nodes/n")),
            "group_count": len(groups), "internal_component_count": len(nodes),
            "internal_component_types": dict(Counter(n.get("type", "0") for n in nodes)),
            "internal_input_count": len(internal_links), "internal_links": internal_links,
            "internal_components": [_configuration(n) for n in nodes],
            "group_hierarchy": [{"group_index": i, "parent_group_index": parents.get(id(g)),
                                 "attributes": dict(g.attrib),
                                 "components": len(g.findall("components/c")),
                                 "bridge_components": len(g.findall("components_bridge/c")),
                                 "child_groups": len(g.findall("groups/group"))} for i, g in enumerate(groups)]}


def read_bodies(text):
    root = xml_root(text)
    bodies, unknown = [], Counter()
    seen = set()
    for body in root.findall("bodies/body"):
        body_id = body.get("unique_id", "")
        if not body_id or body_id in seen:
            raise ValueError("reference bodies need distinct unique_id values")
        seen.add(body_id)
        parts, details = [], {}
        for i, component in enumerate(body.findall("components/c")):
            o = component.find("o")
            if o is None:
                raise ValueError(f"body {body_id}, component {i} has no object geometry")
            d = component.get("d", "01_block")
            piece = BY_NAME.get(d) or definitions.load(d)
            data = definitions.metadata(d)
            if piece is None:
                unknown[d] += 1
                piece = BLOCK
            q = parse_r(o.get("r")) if "r" in o.attrib else MISSING_R
            flip = int(component.get("t", "0"))
            if not 0 <= flip <= 7:
                raise ValueError("mirror flags must be 0..7")
            q = with_mirror(q, flip)
            uid = f"body:{body_id}:part:{i}"
            p = Placed(piece, _position(o.find("vp")), q, uid=uid, name=o.get("custom_name", ""))
            parts.append(p)
            details[uid] = {"definition": d, "index": i, "definition_available": data is not None,
                            "settings": dict(o.attrib), "child_tags": dict(Counter(n.tag for n in o)),
                            "configuration": [_configuration(n) for n in o
                                              if n.tag not in ("vp", "logic_slots", "microprocessor_definition")],
                            "ports": _ports(component, data), "controller": _controller(component),
                            "component_attributes": dict(component.attrib)}
        bodies.append({"id": body_id, "parts": parts, "details": details,
                       "attributes": dict(body.attrib),
                       "extras": [_configuration(n) for n in body if n.tag != "components"]})
    if not bodies or not any(b["parts"] for b in bodies):
        raise ValueError("vehicle has no readable body components")
    return root, bodies, unknown


def audit_text(text, source="reference", sample_limit=3):
    if not isinstance(sample_limit, int) or not 1 <= sample_limit <= 100:
        raise ValueError("sample_limit must be 1-100")
    root, bodies, unknown = read_bodies(text)
    rows = {}
    port_index, origin_index = defaultdict(list), defaultdict(list)
    placement_issues, body_rows, controllers, connections, open_ports = [], [], [], [], []
    for body in bodies:
        parts, details = body["parts"], body["details"]
        # Body-local ownership: never merge positions from unrelated articulated bodies.
        owner, overlaps = {}, []
        for p in parts:
            for v in p.voxels():
                if v in owner:
                    overlaps.append({"position": v, "parts": [owner[v].uid, p.uid]})
                else:
                    owner[v] = p
        body_rows.append({"body_id": body["id"], "part_count": len(parts),
                          "overlap_count": len(overlaps), "overlap_samples": overlaps[:5],
                          "attributes": body["attributes"], "extras": body["extras"]})
        paired, unpaired = adjacency(parts, body["id"])
        connections.extend(paired)
        open_ports.extend(unpaired)
        for p in parts:
            detail = details[p.uid]
            d = detail["definition"]
            rot, mirror = split_mirror(p.Q)
            row = rows.setdefault(d, {"definition": d, "name": definitions.display_name(d), "count": 0,
                                      "rotations": Counter(), "bodies": set(), "samples": [],
                                      "conditions": set(), "sampled_conditions": set()})
            row["count"] += 1
            row["rotations"][(r_attr(rot), mirror)] += 1
            row["bodies"].add(body["id"])
            ports = []
            for node in detail["ports"]:
                pos = add(p.origin, apply(p.Q, node["position"]))
                port = {**node, "position": pos, "part_id": p.uid, "definition": d,
                        "body_id": body["id"]}
                ports.append(port)
                port_index[(node["type"], pos)].append(port)
            for typ in {n["type"] for n in ports}:
                origin_index[(typ, p.origin)].append({"part_id": p.uid, "definition": d,
                                                      "body_id": body["id"]})
            controller = detail["controller"]
            if controller:
                controllers.append({"part_id": p.uid, "body_id": body["id"], **controller})
            scalar_settings = {k: v for k, v in detail["settings"].items()
                               if k not in ("r", "sc", "bc", "ac", "gc", "custom_name")}
            condition = hashlib.sha256(json.dumps([r_attr(rot), mirror, scalar_settings,
                                                   detail["configuration"], controller], sort_keys=True).encode()).hexdigest()
            row["conditions"].add(condition)
            inspect = d in RUDDERS or len(row["samples"]) < sample_limit and condition not in row["sampled_conditions"]
            if not inspect:
                continue
            contacts = mounting_contacts(p, owner) if detail["definition_available"] else []
            roles = profile(d)["axes"] if detail["definition_available"] else {}
            sample = {"part_id": p.uid, "body_id": body["id"], "component_index": detail["index"],
                      "position": p.origin, "r": r_attr(rot), "mirror": mirror,
                      "world_axes": {key: apply(p.Q, v) for key, v in roles.items()},
                      "mounting_contacts": contacts[:32], "contact_count": len(contacts),
                      "settings_keys": sorted(detail["settings"]), "child_tags": detail["child_tags"],
                      "settings": scalar_settings, "condition_id": condition,
                      "configuration": detail["configuration"],
                      "component_attributes": detail["component_attributes"], "ports": ports,
                      "transmission_ports": transmission_ports(p) if detail["definition_available"] else [],
                      "controller": controller}
            if d in RUDDERS:
                base = mounting_contacts(p, owner, (0, -1, 0))
                blocked = sorted(v for v in rudder_clearance(p) if v in owner and owner[v] is not p)
                sample["rudder_inspection"] = {"base_contact_count": len(base), "base_contacts": base,
                                                "sweep_obstruction_count": len(blocked),
                                                "sweep_obstruction_samples": blocked[:20],
                                                "model": "conservative voxel sweep, body-local only"}
                if not base or blocked:
                    placement_issues.append({"part_id": p.uid, "definition": d, "body_id": body["id"],
                                             "base_contact_missing": not bool(base),
                                             "sweep_obstruction_count": len(blocked)})
            if len(row["samples"]) < sample_limit or d in RUDDERS:
                row["samples"].append(sample)
                row["sampled_conditions"].add(condition)
    links, link_types = [], Counter()
    for i, link in enumerate(root.findall("logic_node_links/logic_node_link")):
        typ = int(link.get("type", "0"))
        link_types[str(typ)] += 1
        endpoints = []
        for end in range(2):
            node = link.find(f"voxel_pos_{end}")
            if node is None:
                endpoints.append({"status": "missing_position", "port_candidates": [], "origin_candidates": []})
                continue
            pos = _position(node)
            candidates, origins = port_index[(typ, pos)], origin_index[(typ, pos)]
            ids = {p["part_id"] for p in [*candidates, *origins]}
            status = "no_candidate" if not ids else "unique_part_candidate" if len(ids) == 1 else "ambiguous"
            endpoints.append({"position": pos, "attributes": dict(node.attrib), "status": status,
                              "port_candidates": candidates, "origin_candidates": origins})
        links.append({"index": i, "type": typ, "attributes": dict(link.attrib), "endpoints": endpoints})
    for row in rows.values():
        row["bodies"] = sorted(row["bodies"])
        row["rotations"] = [{"r": r, "mirror": t, "count": count}
                            for (r, t), count in sorted(row["rotations"].items())]
        row["observed_condition_count"] = len(row.pop("conditions"))
        row["sampled_condition_count"] = len(row.pop("sampled_conditions"))
        row["unsampled_condition_count"] = row["observed_condition_count"] - row["sampled_condition_count"]
    base = definitions.definitions_dir()
    installed = sorted(p.stem for p in Path(base).glob("*.xml")) if base else sorted(BY_NAME)
    covered = set(installed) & rows.keys()
    return {"schema_version": 1, "source": source, "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "evidence_level": "observed_saved_vehicle", "part_count": sum(r["count"] for r in rows.values()),
            "body_count": len(bodies), "distinct_definitions": len(rows), "bodies": body_rows,
            "definition_coverage": {"installed": len(installed), "observed_installed": len(covered),
                                    "fraction": len(covered) / len(installed) if installed else 0,
                                    "missing": sorted(set(installed) - covered)},
            "unknown_definitions": dict(unknown), "parts": [rows[d] for d in sorted(rows)],
            "link_count": len(links), "link_types": dict(link_types), "links": links,
            "endpoint_statuses": dict(Counter(e["status"] for link in links for e in link["endpoints"])),
            "controllers": controllers, "placement_issues": placement_issues,
            "connection_candidates": connections, "open_transmission_ports": open_ports,
            "transmission_adjacency_count": len(connections), "open_transmission_port_count": len(open_ports),
            "limitations": ["Observed arrangements are examples, not verified build rules or model training.",
                            "All geometry and contacts are body-local. Articulated transforms are preserved as evidence, not solved.",
                            "Link coordinates are matched to port and origin candidates separately; ambiguous endpoints remain ambiguous.",
                            "Body IDs, controller groups and part attributes are preserved; no functional subsystem names are inferred.",
                            "Facing transmission ports show geometric adjacency; internal routing, conversion, flow and engine operation remain unverified.",
                            "Editor footprints and conservative motion bounds cannot establish exact game physics."]}


def audit_file(path, search="", offset=0, limit=50, section="parts"):
    if not isinstance(search, str) or not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("search must be text, offset nonnegative, and limit 1-200")
    report = audit_text(Path(path).read_text(encoding="utf-8"), Path(path).stem)
    sections = ("parts", "links", "controllers", "bodies", "placement_issues",
                "connection_candidates", "open_transmission_ports")
    if section not in sections:
        raise ValueError(f"section must be one of {', '.join(sections)}")
    rows = [r for r in report[section] if search.lower() in (
        f"{r['definition']} {r['name']}" if section == "parts" else json.dumps(r)).lower()]
    return {**{k: v for k, v in report.items() if k not in sections},
            section: rows[offset:offset + limit], "section": section, "total_matching": len(rows),
            **({"total_matching_definitions": len(rows)} if section == "parts" else {}),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "controller_count": len(report["controllers"])}
