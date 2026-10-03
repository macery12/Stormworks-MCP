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


def inspect_vehicle(path, title, yaw, pitch, zoom, focus):
    placed, _ = load_placed(path)
    return render_view(placed, yaw=yaw, pitch=pitch, zoom=zoom, focus=focus, title=title,
                       ruler=VEHICLE_RULER), ""


def game_vehicle(path, name):
    placed, other = load_placed(path)
    if not placed:
        raise ValueError(f"no components found in {name}")
    vox = [v for p in placed for v in p.voxels()]
    size = [(max(v[i] for v in vox) - min(v[i] for v in vox) + 1) / 4 for i in range(3)]
    top = ", ".join(f"{k} {v}" for k, v in sorted(other.items(), key=lambda kv: -kv[1])[:12])
    text = (f"{name}: {len(placed)} parts, about {size[2]:.2f} m long x {size[0]:.2f} m wide x "
            f"{size[1]:.2f} m tall.\nParts drawn as single cubes (no definition found): {top or 'none'}")
    return render_png(placed, title=name), text


def vehicle_xml(full):
    """(vehicle XML, part count, summary) for a spec."""
    placed, info = build(full)
    from .tanks import ensure_valid  # noqa: PLC0415
    ensure_valid(info)
    return to_xml(placed), len(placed), summary(full, placed, info)


def query_draft(record, selector, offset, limit):
    parts, _ = materialize(record)
    return {**query(parts, selector, offset, limit), "revision": revision(record)}


def preview_draft(record, title, yaw=None, pitch=25, zoom=1, focus=None):
    parts, info = materialize(record, centred=True)
    ruler = design_ruler(info, info["scale"]) if info else VEHICLE_RULER
    png = (render_png(parts, title=title, ruler=ruler) if yaw is None else
           render_view(parts, title=title, ruler=ruler, yaw=yaw, pitch=pitch, zoom=zoom, focus=focus))
    return png, describe(record, parts, info)


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
                      ruler=design_ruler(info, info["scale"]) if info else VEHICLE_RULER)
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
                                export_draft, seal_draft, analyze_reference, hull_analysis)}


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
