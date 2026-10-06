"""Heavy tool work, run in a child process so it can be stopped.

The MCP SDK runs a synchronous tool in a thread, and a thread cannot be stopped: a call the
client gave up on kept the CPU (and Python's GIL) for minutes and slowed every later call.
Each job here runs in its own process instead (`run_job`), which the server kills when the
client cancels, when the job passes its deadline, or when the server exits. The child also
exits by itself if the server process disappears.

Every job takes and returns plain data (specs, bytes, strings) so it crosses the process
boundary.
"""
import multiprocessing
import os
import threading
import time
import traceback

from .build import build, summary
from .render import VEHICLE_RULER, design_ruler, render_interior, render_png, render_view
from .vehicle import load_placed, to_xml
from .drafts import describe, edited, export, materialize
from .editing import query, revision

HIGHLIGHT = "FF2BD6"


def preview(full, title):
    placed, info = build(full)
    png = render_png(placed, title=title, ruler=design_ruler(info, info["scale"]))
    return png, summary(full, placed, info)


def interior(full, title):
    placed, info = build(full)
    if not info["interior"].rooms:
        raise ValueError("this spec has no interior.rooms; add some first (see hull_design_guide)")
    png = render_interior(placed, info, title=title, ruler=design_ruler(info, info["scale"]))
    return png, summary(full, placed, info)


def inspect_design(full, title, yaw, pitch, zoom, focus, highlight):
    placed, info = build(full)
    labels, note = (), ""
    if highlight:
        labels, note = _highlight(placed, info, highlight, info["scale"])
    png = render_view(placed, yaw=yaw, pitch=pitch, zoom=zoom, focus=focus, title=title,
                      ruler=design_ruler(info, info["scale"]), labels=labels)
    return png, note


def inspect_vehicle(path, title, yaw, pitch, zoom, focus, body_id=None):
    placed, _ = load_placed(path, body_id=body_id)
    return render_view(placed, yaw=yaw, pitch=pitch, zoom=zoom, focus=focus, title=title,
                       ruler=VEHICLE_RULER), "\n" + _mesh_note(placed)


def _mesh_note(parts):
    from .meshes import coverage  # noqa: PLC0415
    report = coverage(parts)
    return (f"Native component meshes: {sum(report['native_components'].values())}; "
            f"footprint fallbacks: {report['footprint_fallbacks'] or 'none'}; "
            f"omitted moving geometry: {report['omitted_moving_geometry'] or 'none'}.\n{report['note']}")


def game_vehicle(path, name, body_id=None):
    from pathlib import Path  # noqa: PLC0415
    from .reference import xml_root  # noqa: PLC0415
    bodies = xml_root(Path(path).read_text(encoding="utf-8-sig")).findall("bodies/body")
    if body_id is None:
        body_id = max(bodies, key=lambda b: len(b.findall("components/c"))).get("unique_id")
    placed, other = load_placed(path, body_id=body_id)
    if not placed:
        raise ValueError(f"no components found in {name}")
    vox = [v for p in placed for v in p.voxels()]
    size = [(max(v[i] for v in vox) - min(v[i] for v in vox) + 1) / 4 for i in range(3)]
    top = ", ".join(f"{k} {v}" for k, v in sorted(other.items(), key=lambda kv: -kv[1])[:12])
    text = (f"{name}: {len(placed)} parts, about {size[2]:.2f} m long x {size[0]:.2f} m wide x "
            f"{size[1]:.2f} m tall. Body {body_id} of {len(bodies)} (body-local view).\n"
            f"Missing definitions: {top or 'none'}.\n" + _mesh_note(placed))
    return render_png(placed, title=name, nautical=False), text


def vehicle_xml(full):
    """(vehicle XML, part count, summary) for a spec."""
    placed, info = build(full)
    from .tanks import ensure_valid  # noqa: PLC0415
    ensure_valid(info)
    return to_xml(placed), len(placed), summary(full, placed, info)


def query_draft(record, selector, offset, limit):
    parts, _ = materialize(record)
    return {**query(parts, selector, offset, limit), "revision": revision(record)}


def preview_draft(record, title, yaw=None, pitch=25, zoom=1, focus=None, layer="all", door_state="closed"):
    parts, info = materialize(record, centred=True)
    from .networks import wires  # noqa: PLC0415
    wires(record, parts)  # Fail before persisting edits that leave dangling generated connections.
    if layer not in ("all", "components", "structure"):
        raise ValueError("layer must be all, components or structure")
    from .pieces import BY_NAME  # noqa: PLC0415
    shown = [p for p in parts if layer == "all" or (p.piece.d in BY_NAME) == (layer == "structure")]
    if not shown:
        raise ValueError(f"no parts in {layer} layer")
    ruler = design_ruler(info, info["scale"]) if info else VEHICLE_RULER
    title = f"{title} [{layer}]" if layer != "all" else title
    png = (render_png(shown, title=title, ruler=ruler, nautical=record.get("kind") != "land", door_state=door_state) if yaw is None else
           render_view(shown, title=title, ruler=ruler, yaw=yaw, pitch=pitch, zoom=zoom, focus=focus, door_state=door_state))
    return png, describe(record, parts, info) + "\n" + _mesh_note(shown)


def edit_draft(record, operations, title):
    proposed = edited(record, operations)
    png, text = preview_draft(proposed, title)
    return proposed, png, text


def import_draft(xml, source):
    # Parse/validate in a cancellable worker; imports may contain hundreds of thousands of parts.
    from .editing import VehicleDocument  # noqa: PLC0415
    document = VehicleDocument.parse(xml)
    return {"kind": "imported", "source": source, "source_xml": xml, "edits": [],
            "vehicle": False, "generation": 0}, len(document.parts)


def analyze_reference(path, search, offset, limit, section="parts"):
    from .reference import audit_file  # noqa: PLC0415
    return audit_file(path, search, offset, limit, section)


def land_parts(category, search, offset, limit):
    from .land import catalogue  # noqa: PLC0415
    return catalogue(category, search, offset, limit)


def land_library(directories, search, kind, offset, limit, source):
    from .land import _page, scan_library  # noqa: PLC0415
    _page(offset, limit)
    if kind not in ("wheeled", "tracked", "all"):
        raise ValueError("kind must be wheeled, tracked or all")
    reports = [scan_library(d, search, kind, 0, 200, workshop=source == "workshop") for d in directories]
    # Scan each library fully before applying the shared page, including libraries with >200 entries.
    rows, skipped = [], []
    for d, report in zip(directories, reports):
        rows.extend(report["vehicles"])
        cursor = report["next_offset"]
        while cursor is not None:
            page = scan_library(d, search, kind, cursor, 200, workshop=source == "workshop")
            rows.extend(page["vehicles"])
            cursor = page["next_offset"]
        skipped.extend(report["skipped_samples"])
    rows.sort(key=lambda r: r["name"])
    return {"vehicles": rows[offset:offset + limit], "total": len(rows), "source": source,
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "files_considered": sum(r["files_considered"] for r in reports),
            "skipped_count": sum(r["skipped_count"] for r in reports), "skipped_samples": skipped[:10],
            "evidence_level": "observed_saved_vehicle",
            "limitations": ["Wheel parts can occur on boats, aircraft, trailers or experiments.",
                            "Saved arrangements are observations; roadworthiness is not inferred."]}


def land_layout(path, record, body_id, forward, section, offset, limit, wheel_roles=None, exclude_wheel_ids=None):
    from .land import layout_file, layout_text  # noqa: PLC0415
    if path:
        return layout_file(path, body_id, forward, section, offset, limit, wheel_roles, exclude_wheel_ids)
    parts, _ = materialize(record)
    from .editing import VehicleDocument  # noqa: PLC0415
    xml = (VehicleDocument.parse(record["source_xml"]).to_xml(parts)
           if record.get("kind") == "imported" else to_xml(parts))
    from .networks import write_xml  # noqa: PLC0415
    xml = write_xml(xml, record, parts)
    from .reference import xml_root  # noqa: PLC0415
    body = xml_root(xml).find("bodies/body").get("unique_id")
    forward_ids = {p.uid: f"body:{body}:part:{i}" for i, p in enumerate(parts)}
    roles = {forward_ids.get(key, key): value for key, value in (wheel_roles or {}).items()}
    excluded = [forward_ids.get(key, key) for key in (exclude_wheel_ids or [])]
    report = layout_text(xml, "draft", body_id, forward, section, offset, limit, roles, excluded)
    original_ids = {value: key for key, value in forward_ids.items()}

    def restore(value):
        if isinstance(value, dict):
            return {key: restore(item) for key, item in value.items()}
        if isinstance(value, list):
            return [restore(item) for item in value]
        return original_ids.get(value, value) if isinstance(value, str) else value

    report = restore(report)
    report["evidence_level"] = "draft_geometry"
    return report


def land_draft(spec, title):
    if spec is not None and not isinstance(spec, dict):
        raise ValueError("land vehicle spec must be an object")
    record = {"kind": "land", "spec": {"preset": "utility_buggy", **(spec or {})},
              "vehicle": False, "generation": 0}
    if record["spec"]["preset"] in ("utility_4x4", "humvee_4x4"):
        from .networks import template_wires  # noqa: PLC0415
        parts, _ = materialize(record)
        record["base_connections"] = template_wires(record, parts)
    png, note = preview_draft(record, title)
    return record, png, note


def viewer_geometry(xml, body_id=None):
    from .viewer import geometry  # noqa: PLC0415
    return geometry(xml, body_id)


def query_connections(record, offset, limit):
    from .networks import query  # noqa: PLC0415
    parts, _ = materialize(record)
    return {**query(record, parts, offset, limit), "revision": revision(record)}


def edit_connections(record, operations, title):
    from .networks import edited as connection_edit  # noqa: PLC0415
    parts, _ = materialize(record)
    proposed = connection_edit(record, operations, parts)
    png, note = preview_draft(proposed, title)
    return proposed, png, note


def route_connections(record, operations, title):
    import copy  # noqa: PLC0415
    if not isinstance(operations, list) or not operations or len(operations) > 100:
        raise ValueError("routes must be a nonempty list of at most 100 objects")
    proposed = copy.deepcopy(record)
    proposed.pop("history", None)
    proposed.setdefault("route_edits", []).extend(copy.deepcopy(operations))
    png, note = preview_draft(proposed, title)
    return proposed, png, note


def preflight_vehicle(record):
    from .networks import preflight  # noqa: PLC0415
    parts, _ = materialize(record)
    return {**preflight(record, parts), "revision": revision(record)}


def plan_vehicle_repairs(record):
    from .repairs import plan  # noqa: PLC0415
    return plan(record)


def repair_vehicle(record, plan_id, finding_ids, title):
    from .repairs import repair  # noqa: PLC0415
    from .diagnostic_view import preview  # noqa: PLC0415
    proposed, report = repair(record, plan_id, finding_ids)
    png, _ = preview(record, title, proposed)
    return proposed, png, report


def assemble_vehicle(record, assembly, bindings, options, title):
    from .assemblies import assemble  # noqa: PLC0415
    from .diagnostic_view import preview  # noqa: PLC0415
    proposed, report = assemble(record, assembly, bindings, options)
    png, _ = preview(record, title, proposed)
    return proposed, png, report


def diagnostic_preview(record, title, yaw=35, pitch=25, layer="components"):
    from .diagnostic_view import preview  # noqa: PLC0415
    png, data = preview(record, title, yaw=yaw, pitch=pitch, layer=layer)
    data["preflight"]["revision"] = revision(record)
    return png, {**data, "revision": revision(record)}


def prepare_validation(record, design, name, path):
    from .validation import prepare  # noqa: PLC0415
    return prepare(record, design, name, path)


def diagnostic_geometry(record):
    from .diagnostic_view import overlay  # noqa: PLC0415
    from .editing import VehicleDocument  # noqa: PLC0415
    from .viewer import geometry  # noqa: PLC0415
    parts, _ = materialize(record)
    xml = (VehicleDocument.parse(record["source_xml"]).to_xml(parts) if record.get("kind") == "imported"
           else to_xml(parts))
    return xml, {**geometry(xml), "diagnostics": overlay(record, parts)}


def hull_analysis(full, path, body_id, stations, x):
    from pathlib import Path  # noqa: PLC0415
    from .hull_analysis import design_depths, reference_structure, structural_report  # noqa: PLC0415
    from .pieces import add  # noqa: PLC0415

    if path:
        parts, context = reference_structure(Path(path).read_text(encoding="utf-8-sig"), body_id)
        return {**context, **structural_report(parts, stations, x)}
    parts, info = build(full)
    for p in parts:
        p.origin = add(p.origin, info["shift"])
    report = structural_report(parts, stations, x)
    zs = [row["z_blocks"] for row in report["sections"]]
    return {**report, "frame": "build blocks: x centreline, y keel layer, z from transom",
            "metres_per_block": 0.25, "depths": design_depths(info, zs)}


def export_draft(record):
    return export(record)


def seal_draft(record, seeds, door_state, title):
    import copy  # noqa: PLC0415
    from .seal import auto_seeds, check  # noqa: PLC0415
    from .pieces import BLOCK, Placed  # noqa: PLC0415
    parts, info = materialize(record)
    if seeds is None:
        if info is None:
            raise ValueError("imported drafts require explicit interior seed positions in blocks")
        seeds = auto_seeds(parts, info)
    report = check(parts, seeds, door_state)
    if info and info.get("tank_validation"):
        report["tanks"] = info["tank_validation"]
        if any(t["status"] == "leaking" for t in report["tanks"]):
            report["status"] = "leaking"
        elif any(t["status"] == "indeterminate" for t in report["tanks"]) and report["status"] == "sealed":
            report["status"] = "indeterminate"
    shown = copy.deepcopy(parts)
    path = next((r["escape_path"] for r in report["compartments"] if r["escape_path"]), [])
    if not path:
        path = next((r["escape_path"] for t in report.get("tanks", [])
                     for r in t.get("compartments", []) if r["escape_path"]), [])
    # Path markers and a labelled exit help locate the repair in the preview.
    shown.extend(Placed(BLOCK, v, color=HIGHLIGHT) for v in path[:256])
    labels = [((-path[-1][0], path[-1][1], path[-1][2]), "escape")] if path else ()
    png = render_view(shown, title=f"{title}: {report['status']}", labels=labels, yaw=35, pitch=-20,
                      ruler=design_ruler(info, info["scale"]) if info else VEHICLE_RULER, door_state=door_state)
    return png, report


def _highlight(placed, info, box_name, scale):
    """Paint one box's pieces magenta; return its label and a position note."""
    shape, region, (sx, sy, sz) = info["shape"], info["region"], info["shift"]
    names = [b.name for b in shape.boxes]
    if box_name not in names:
        close = [n for n in names if box_name.lower() in n.lower()][:8]
        raise ValueError(f"no superstructure box named '{box_name}'"
                         + (f"; did you mean {', '.join(close)}?" if close else ""))
    i = names.index(box_name)
    box = shape.boxes[i]
    n = 0
    for p in placed:
        o = p.origin
        if region.get((o[0] + sx, o[1] + sy, o[2] + sz)) == f"box{i}":
            p.color = HIGHLIGHT
            n += 1
    (x0, x1), (_y0, y1), (z0, z1) = box.bounds()
    point = (-((x0 + x1) / 2 - sx), y1 + 2 - sy, (z0 + z1) / 2 - sz)
    k = 4 * scale
    note = (f"\n{box_name}: {n} visible blocks; z {box.z0 / k:.2f}-{(box.z0 + box.zl) / k:.2f}, "
            f"y {box.y0 / k:.2f}-{box.top() / k:.2f}, x {box.xc / k:.2f} (spec metres); "
            f"base {box.y0 / 4:.2f} m, top {box.top() / 4:.2f} m above the keel in game metres")
    if not n:
        note += "; hidden: every block is inside the hull or an earlier box"
    return [(point, box_name)], note


JOBS = {f.__name__: f for f in (preview, interior, inspect_design, inspect_vehicle, game_vehicle,
                                vehicle_xml, query_draft, preview_draft, edit_draft, import_draft,
                                export_draft, seal_draft, analyze_reference, hull_analysis,
                                land_parts, land_library, land_layout, land_draft, viewer_geometry,
                                query_connections, edit_connections, route_connections, preflight_vehicle,
                                plan_vehicle_repairs, repair_vehicle, assemble_vehicle, diagnostic_preview,
                                prepare_validation, diagnostic_geometry)}


def _watch_parent():
    parent = multiprocessing.parent_process()
    while parent is not None and parent.is_alive():
        time.sleep(1.0)
    os._exit(1)


def _child(conn, name, args):
    threading.Thread(target=_watch_parent, daemon=True).start()
    try:
        conn.send((True, JOBS[name](*args)))
    except (ValueError, OSError) as exc:
        conn.send((False, str(exc)))
    except Exception as exc:  # noqa: BLE001 - report anything else to the model too
        conn.send((False, f"internal error: {exc!r}\n{traceback.format_exc(limit=4)}"))
    finally:
        conn.close()


async def run_job(name, *args, timeout=None):
    """Run JOBS[name](*args) in a child process and return its result.

    Raises ValueError with the job's message on an expected failure, or when the job runs past
    `timeout` seconds (default SW_TOOL_TIMEOUT, 300). Cancelling the awaiting task (the client
    gave up) kills the child at once.
    """
    import anyio  # noqa: PLC0415 - only the server needs it

    timeout = timeout or float(os.environ.get("SW_TOOL_TIMEOUT", "300"))
    ctx = multiprocessing.get_context("spawn")
    recv, send = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(send, name, args), daemon=True)
    proc.start()
    send.close()
    deadline = time.monotonic() + timeout
    completed = False
    try:
        while not recv.poll():
            if not proc.is_alive() and not recv.poll():
                raise ValueError(f"the {name} job stopped unexpectedly (exit code {proc.exitcode})")
            if time.monotonic() > deadline:
                raise ValueError(f"gave up after {timeout:.0f} s. Very large designs are slow, "
                                 "above all with smoothing \"wedges\"; preview with blocks, or "
                                 "raise SW_TOOL_TIMEOUT")
            await anyio.sleep(0.05)
        ok, value = recv.recv()
        completed = True
    finally:
        try:
            if completed:
                # The result is complete. Let Python finish shutdown instead of racing a
                # Windows TerminateProcess call against an already exiting child.
                proc.join(5)
            if proc.is_alive():
                try:
                    proc.kill()
                except PermissionError:
                    # Windows can deny TerminateProcess when the child exits between the
                    # alive check and kill. Ignore only a confirmed completed exit.
                    proc.join(5)
                    if proc.is_alive():
                        raise
            proc.join(5)
        finally:
            recv.close()
            if not proc.is_alive():
                from .cache import discard_worker  # noqa: PLC0415
                discard_worker(proc.pid)
    if not ok:
        raise ValueError(value)
    return value
