"""Installed land-vehicle parts and read-only, body-local layout evidence."""
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import definitions
from .pieces import DIRS, add, apply, r_attr, split_mirror

ROAD_WHEEL = re.compile(r"wheel_(?:advanced_[3579](?:_sus)?|small|medium|coaster(?:_large)?)$")
CATEGORIES = ("wheels", "tracks", "lights", "controls", "propulsion", "transmission",
              "power", "fuel", "cooling", "body", "logic", "utility")


def road_wheel(d):
    return bool(ROAD_WHEEL.fullmatch(d))


def category(d):
    """Part-family classification, not a claim about a vehicle's intended use."""
    if road_wheel(d):
        return "wheels"
    if d.startswith("wheel_tank") or d.startswith("track_"):
        return "tracks"
    if d.startswith(("small_light", "searchlight", "navigation_light", "light_")):
        return "lights"
    if d.startswith(("seat", "button", "toggle_button", "instrument", "dial", "gauge", "monitor")):
        return "controls"
    if d.startswith(("battery", "generator", "electric_", "circuit_breaker")):
        return "power"
    if d.startswith(("clutch", "gearbox", "torque", "differential", "rps_", "pipe", "trans_",
                     "modular_engine_clutch", "modular_engine_gearbox")):
        return "transmission"
    if d.startswith(("radiator", "heatsink", "heat_", "coolant", "fluid_radiator", "modular_engine_coolant")):
        return "cooling"
    if d.startswith(("fluid", "water_spawner", "pump", "fuel", "modular_engine_fuel", "modular_engine_air",
                     "modular_engine_exhaust")):
        return "fuel"
    if d.startswith(("motor_", "modular_engine", "engine")) or d in ("aircraft_engine",):
        return "propulsion"
    if d.startswith(("0", "window", "door", "ladder", "weight")):
        return "body"
    if d.startswith(("microprocessor", "logic", "gate_", "numerical", "composite", "function", "constant")):
        return "logic"
    if d.startswith(("winch", "connector", "hinge", "pivot", "piston", "velocity", "speed",
                     "distance", "tilt", "gps", "compass", "rope", "sensor_")):
        return "utility"
    return None


def _page(offset, limit):
    if (isinstance(offset, bool) or not isinstance(offset, int) or offset < 0
            or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200):
        raise ValueError("offset must be nonnegative and limit must be 1-200")


def catalogue(group="", search="", offset=0, limit=50):
    from .part_policy import allowed  # noqa: PLC0415
    _page(offset, limit)
    if group and group not in CATEGORIES:
        raise ValueError(f"category must be one of {', '.join(CATEGORIES)}")
    base = definitions.definitions_dir()
    rows = []
    names = sorted(p.stem for p in Path(base).glob("*.xml")) if base else []
    for d in names:
        if not allowed(d):
            continue
        role = category(d)
        if role is None or group and role != group:
            continue
        data = definitions.metadata(d)
        if search.lower() not in f"{d} {data['name']}".lower():
            continue
        size = [max(v[i] for v in data["footprint"]) - min(v[i] for v in data["footprint"]) + 1
                for i in range(3)]
        rows.append({"definition": d, "name": data["name"], "category": role,
                     "size_blocks": size, "size_metres": [n / 4 for n in size], "mass": data["mass"],
                     "ports": [{k: n[k] for k in ("index", "label", "type", "mode")}
                               for n in data["logic_nodes"]]})
    return {"parts": rows[offset:offset + limit], "total": len(rows), "categories": CATEGORIES,
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "definitions_available": base is not None,
            "equipment_policy": "Prebuilt diesel engines only; radiators only for cooling.",
            "limitations": ["Family categories include parts useful on land; use search_parts for the permitted catalogue."]}


def scan_library(directory, search="", kind="wheeled", offset=0, limit=50, workshop=False):
    """Identify wheel/track examples without merging bodies or parsing nested controller parts."""
    from .reference import xml_root  # noqa: PLC0415
    _page(offset, limit)
    if kind not in ("wheeled", "tracked", "all"):
        raise ValueError("kind must be wheeled, tracked or all")
    base = Path(directory)
    if not base.is_dir():
        raise ValueError(f"vehicles folder not found: {base} (set SW_VEHICLES_DIR)")
    rows, skipped = [], []
    files = sorted(base.glob("*/vehicle.xml")) if workshop else sorted(
        p for p in base.iterdir() if p.suffix.lower() == ".xml")
    for path in files:
        name = path.parent.name if workshop else path.stem
        if search.lower() not in name.lower():
            continue
        try:
            root = xml_root(path.read_text(encoding="utf-8-sig"))
        except (ValueError, OSError, UnicodeError) as exc:
            skipped.append({"name": name, "reason": str(exc)})
            continue
        bodies = root.findall("bodies/body")
        counts = Counter(c.get("d", "01_block") for b in bodies for c in b.findall("components/c"))
        wheels = {d: n for d, n in counts.items() if road_wheel(d)}
        tracks = {d: n for d, n in counts.items() if category(d) == "tracks"}
        if not (wheels if kind == "wheeled" else tracks if kind == "tracked" else wheels or tracks):
            continue
        roles = Counter()
        for d, count in counts.items():
            if role := category(d):
                roles[role] += count
        rows.append({"name": name, "source": "workshop" if workshop else "vehicles",
                     "body_count": len(bodies), "part_count": sum(counts.values()),
                     "wheel_count": sum(wheels.values()), "wheel_definitions": wheels,
                     "track_count": sum(tracks.values()), "track_definitions": tracks,
                     "categories": dict(roles), "link_count": len(root.findall("logic_node_links/logic_node_link"))})
    return {"vehicles": rows[offset:offset + limit], "total": len(rows), "files_considered": len(files),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "skipped_count": len(skipped), "skipped_samples": skipped[:10],
            "evidence_level": "observed_saved_vehicle",
            "limitations": ["Wheel parts can appear on aircraft, boats, trailers or experiments; this does not classify roadworthiness.",
                            "The index reads XML structure; analyze_land_vehicle checks supported geometry separately."]}


def control_seat(d, data):
    return d.startswith("seat") and any(n["mode"] == 0 and n["label"].startswith("Axis ")
                                        for n in data.get("logic_nodes", []))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _frame(parts, forward):
    from .orientation import profile  # noqa: PLC0415
    if forward is not None:
        if not isinstance(forward, (list, tuple)) or tuple(forward) not in DIRS or forward[1] or any(
                isinstance(v, bool) for v in forward):
            raise ValueError("forward must be a horizontal axis unit vector, e.g. [0,0,-1]")
        return tuple(forward), "caller"
    candidates = set()
    for p in parts:
        data = definitions.metadata(p.piece.d) or {}
        if control_seat(p.piece.d, data):
            front = apply(p.Q, profile(p.piece.d)["axes"].get("seat_front", (0, 0, 0)))
            if front in DIRS and not front[1]:
                candidates.add(front)
    return (next(iter(candidates)), "driver seat") if len(candidates) == 1 else (
        (0, 0, 1), "assumed +z; driver seats absent or disagree, specify forward")


def layout_text(text, source="reference", body_id=None, forward=None, section="wheels", offset=0, limit=50,
                wheel_roles=None, exclude_wheel_ids=None):
    from .components import mounting_contacts  # noqa: PLC0415
    from .orientation import profile, wheel_directions  # noqa: PLC0415
    from .reference import read_bodies  # noqa: PLC0415
    _page(offset, limit)
    sections = ("wheels", "lights", "controls", "equipment", "issues")
    if section not in sections:
        raise ValueError(f"section must be one of {', '.join(sections)}")
    root, bodies, unknown = read_bodies(text, tolerate_transforms=True)
    roles = dict(wheel_roles or {})
    excluded = exclude_wheel_ids or []
    if (not isinstance(wheel_roles, (dict, type(None))) or not isinstance(excluded, list)
            or any(not isinstance(k, str) or v not in ("road", "spare", "excluded") for k, v in roles.items())
            or any(not isinstance(k, str) for k in excluded)):
        raise ValueError("wheel_roles maps part IDs to road/spare/excluded; exclude_wheel_ids is a list of wheel IDs")
    if any(k in roles and roles[k] != "excluded" for k in excluded):
        raise ValueError("conflicting wheel role and exclusion")
    roles.update(dict.fromkeys(excluded, "excluded"))
    wheel_ids = {p.uid for b in bodies for p in b["parts"] if road_wheel(p.piece.d)}
    if roles.keys() - wheel_ids:
        raise ValueError(f"stale or non-wheel role IDs: {sorted(roles.keys() - wheel_ids)}; query wheel inventory again")
    if body_id is not None:
        bodies = [b for b in bodies if b["id"] == body_id]
        if not bodies:
            raise ValueError(f"no body {body_id!r} in vehicle")
    result = {key: [] for key in sections}
    body_rows = []
    for body in bodies:
        parts = body["parts"]
        if not parts:
            body_rows.append({"body_id": body["id"], "part_count": len(body["omitted_components"]),
                              "geometry_complete": False, "omitted_components": body["omitted_components"]})
            continue
        front, frame_source = _frame(parts, forward)
        lateral = (front[2], 0, -front[0])
        owner, overlap = {}, []
        for p in parts:
            for v in p.voxels():
                if v in owner:
                    overlap.append(v)
                else:
                    owner[v] = p
        lo = [min(v[i] for v in owner) for i in range(3)]
        hi = [max(v[i] for v in owner) for i in range(3)]
        axles = defaultdict(list)
        for p in parts:
            detail = body["details"][p.uid]
            d, data = detail["definition"], definitions.metadata(detail["definition"])
            role = category(d)
            if role not in CATEGORIES or role == "body":
                continue
            rot, mirror = split_mirror(p.Q)
            axes = profile(d)["axes"] if data else {}
            mount_normal = axes.get("mount_normal") if role == "wheels" else None
            contacts = mounting_contacts(p, owner, mount_normal) if data else []
            settings = {k: v for k, v in detail["settings"].items()
                        if k not in ("r", "sc", "bc", "ac", "gc", "custom_name")}
            row = {"part_id": p.uid, "body_id": body["id"], "definition": d, "category": role,
                   "name": definitions.display_name(d), "custom_name": p.name, "position_blocks": p.origin,
                   "position_metres": [v / 4 for v in p.origin], "r": r_attr(rot), "mirror": mirror,
                   "world_axes": {k: apply(p.Q, v) for k, v in axes.items()},
                   "mounting_contact_count": len(contacts), "mounting_contacts": contacts[:8],
                   "settings": settings, "ports": [{**n, "position": add(p.origin, apply(p.Q, n["position"]))}
                                                      for n in detail["ports"]]}
            destination = role if role in ("wheels", "lights", "controls") else "equipment"
            result[destination].append(row)
            if role == "wheels":
                wheel_role = roles.get(p.uid, "spare" if "spare" in p.name.lower() else "road")
                row["wheel_role"] = wheel_role
                row["role_source"] = "caller" if p.uid in roles else "saved name" if wheel_role == "spare" else "assumed road"
                if data and wheel_role == "road":
                    row["direction_check"] = wheel_directions(p, front)
                station = _dot(p.origin, front)
                if wheel_role == "road":
                    axles[station].append(p)
                axle = row["world_axes"].get("axle_axis")
                if axle is None:
                    row["orientation_note"] = "Wheel axle unavailable without its installed definition."
                elif wheel_role == "road" and abs(_dot(axle, lateral)) != 1:
                    result["issues"].append({"part_id": p.uid, "body_id": body["id"], "issue": "wheel_axle_not_lateral"})
                if not contacts and data:
                    result["issues"].append({"part_id": p.uid, "body_id": body["id"], "issue": "wheel_mount_contact_missing"})
                if "wheel_size" in settings:
                    row["clearance_note"] = "Saved wheel_size can change mesh extent; editor footprints do not model it."
            if role == "lights" and data and data["properties"].get("light_type") == "1":
                beam = row["world_axes"].get("light_forward")
                row["beam_forward_dot"] = _dot(beam, front) if beam is not None else None
                if beam is None:
                    row["beam_note"] = "No explicit axis-aligned light_forward; beam orientation needs calibration."
        axle_rows = []
        for station, wheels in sorted(axles.items()):
            mounts = [_dot(p.origin, lateral) for p in wheels]
            axle_rows.append({"station_blocks": station, "station_metres": station / 4,
                              "wheel_count": len(wheels), "wheel_ids": [p.uid for p in wheels],
                              "mount_span_metres": (max(mounts) - min(mounts)) / 4,
                              "mount_heights_metres": sorted({p.origin[1] / 4 for p in wheels}),
                              "definitions": dict(Counter(p.piece.d for p in wheels))})
        body_rows.append({"body_id": body["id"], "part_count": len(parts), "forward": front,
                          "geometry_complete": not body["omitted_components"] and not unknown,
                          "omitted_components": body["omitted_components"],
                          "forward_source": frame_source, "lateral": lateral,
                          "bounds_blocks": [lo, hi], "size_metres": [(hi[i] - lo[i] + 1) / 4 for i in range(3)],
                          "overlap_count": len(overlap), "overlap_samples": overlap[:5],
                          "axle_count": len(axle_rows), "axles": axle_rows[:100],
                          "axles_truncated": len(axle_rows) > 100,
                          "wheelbase_metres": (max(axles) - min(axles)) / 4 if len(axles) > 1 else None})
    rows = result[section]
    return {"schema_version": 1, "source": source, "evidence_level": "observed_saved_vehicle",
            "frame": "body-local blocks; +y up; forward inferred separately for each body or supplied",
            "bodies": body_rows, "unknown_definitions": dict(unknown),
            "counts": {key: len(value) for key, value in result.items()},
            "link_count": len(root.findall("logic_node_links/logic_node_link")),
            "section": section, section: rows[offset:offset + limit], "total": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "limitations": ["Axles group equal longitudinal mounting stations. Mount span is not tyre-centre track width.",
                            "Wheel inventory includes spares/exclusions. Axles use road roles only; unnamed wheels default to road. Override wheel_roles when needed.",
                            "Bodies remain separate; articulated transforms, suspension travel and steering sweep are not solved.",
                            "Editor bounds cannot establish tyre ground contact, ground clearance or scaled mesh clearance.",
                            "Unknown definitions use block placeholders; their bounds, axes and contacts are incomplete.",
                            "Nonstandard transforms are reported and omitted; nearby mounting/overlap conclusions may be incomplete.",
                            "Saved settings and links are evidence, not validation of braking, steering sign, lights or propulsion."]}


def layout_file(path, body_id=None, forward=None, section="wheels", offset=0, limit=50,
                wheel_roles=None, exclude_wheel_ids=None):
    path = Path(path)
    return layout_text(path.read_text(encoding="utf-8-sig"), path.stem, body_id, forward, section, offset, limit,
                       wheel_roles, exclude_wheel_ids)
