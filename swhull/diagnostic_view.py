"""Diagnostic primitives shared by PNG previews and the browser viewer."""
import copy

from .drafts import materialize
from .networks import endpoint, preflight, wires
from .pieces import add
from .render import VEHICLE_RULER, render_view

COLORS = {"fault": "FF5252", "blocked": "FFB347", "steering": "62B5FF", "proposed": "52E39C"}


def overlay(record, parts, report=None, proposed=None):
    report = report or preflight(record, parts)
    by_id = {p.uid: p for p in parts}
    markers, segments = [], []
    for f in report["findings"][:100]:
        for uid in f["part_ids"]:
            if uid in by_id:
                markers.append({"position": list(by_id[uid].origin), "label": f["explanation"],
                                "color": COLORS["fault"], "part_id": uid, "kind": "fault"})
    for row in report["issues"]:
        if row["issue"] == "blocked transmission face":
            markers.append({"position": list(row["exit_cell"]), "label": "blocked port",
                            "color": COLORS["blocked"], "part_id": row["part_id"], "kind": "blocked"})
    for row in report["wheel_direction_checks"]:
        p = by_id[row["part_id"]]
        direction = row["wheel_forward"]
        short_name = p.name.replace("front", "F").replace("rear", "R").replace("left", "L").replace("right", "R")
        sign = row["steering_signal_sign"]
        detail = "fixed" if sign is None else f"steer {sign:+d}, need {row['required_steering_sign']:+d}" if row["required_steering_sign"] is not None else "review arrows"
        segments.append({"start": list(p.origin), "end": list(add(p.origin, tuple(3 * c for c in direction))),
                         "color": COLORS["steering"], "arrow": True, "kind": "steering",
                         "label": f"{short_name}: {detail}"})
        if sign is not None:
            segments.append({"start": list(add(p.origin, (0, 1, 0))),
                             "end": list(add(add(p.origin, (0, 1, 0)), tuple(2 * sign * c for c in row["wheel_positive_steering"]))),
                             "color": COLORS["steering"], "arrow": True, "kind": "steering", "label": ""})
    if proposed:
        new_parts, _ = materialize(proposed)
        old_ids = set(by_id)
        for p in new_parts:
            if p.uid not in old_ids:
                markers.append({"position": list(p.origin), "label": "proposed pipe",
                                "color": COLORS["proposed"], "part_id": p.uid, "kind": "proposed"})
        old_links = {(str(link.get("from")), str(link.get("to"))) for link in wires(record, parts)}
        for link in wires(proposed, new_parts):
            if "from" in link and (str(link["from"]), str(link["to"])) not in old_links:
                a, b = (endpoint(new_parts, link[key])["position"] for key in ("from", "to"))
                segments.append({"start": list(a), "end": list(b), "color": COLORS["proposed"],
                                 "arrow": link["type"] != 4, "label": "proposed wire", "kind": "proposed"})
    return {"markers": markers, "segments": segments, "legend": COLORS,
            "frame": "draft integer blocks; display negates x; overlays are drawn over geometry"}


def preview(record, title, proposed=None, yaw=35, pitch=25, layer="components"):
    from .pieces import BY_NAME  # noqa: PLC0415
    parts, _ = materialize(record)
    report = preflight(record, parts)
    data = overlay(record, parts, report, proposed)
    if layer not in ("all", "components", "structure"):
        raise ValueError("layer must be all, components or structure")
    shown = copy.deepcopy([p for p in parts if layer == "all" or (p.piece.d in BY_NAME) == (layer == "structure")])
    if not shown:
        raise ValueError(f"no parts in {layer} layer")
    highlighted = {m["part_id"] for m in data["markers"] if m["kind"] == "fault"}
    for p in shown:
        if p.uid in highlighted:
            p.color = COLORS["fault"]
    label_by_part = {}
    part_ids = {p.uid for p in parts}
    for finding in report["findings"]:
        for uid in finding["part_ids"]:
            if uid in part_ids:
                label_by_part.setdefault(uid, []).append(finding["code"].replace("_", " "))
    labels = [(display(by.origin), f"{by.name or by.uid}: {', '.join(label_by_part[by.uid])}"[:65])
              for by in parts if by.uid in label_by_part]
    labels.extend((display(m["position"]), "blocked port") for m in data["markers"] if m["kind"] == "blocked")
    for m in data["markers"]:
        v = m["position"]
        for axis in (0, 1):
            a, b = list(v), list(v)
            a[axis] -= .35
            b[axis] += .35
            data["segments"].append({"start": a, "end": b, "color": m["color"],
                                     "arrow": False, "label": "", "kind": m["kind"]})
    segments = [{**s, "start": display(s["start"]), "end": display(s["end"])} for s in data["segments"]]
    png = render_view(shown, title=f"{title}: red faults / amber blocked / blue steering / green proposed",
                      yaw=yaw, pitch=pitch, labels=labels, segments=segments, ruler=VEHICLE_RULER)
    return png, {"preflight": report, "overlay": data}


def display(v):
    return (-v[0], v[1], v[2])
