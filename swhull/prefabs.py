"""Prefabs: any saved vehicle reused as a piece of another vehicle.

Every vehicle file can be a prefab, so a prefab can be loaded and tested in game on its own. A
side file in the server's data folder (`prefabs/<name>.json`) names the prefab's connection
points (logic nodes without a wire, open pipe and shaft ends) and stores the vehicle file's
hash, so a changed file is noticed; names given to points that still exist are kept.

Placing a prefab copies every part exactly, microcontrollers included, and moves its wires with
it. Its main body joins the body it is placed against; each other body becomes a new body.
"""
import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path

from .connections import adjacency
from .editing import VehicleDocument, _geometry, _move_raw, bounds as read_bounds, rotation, vector
from .pieces import IDENTITY, add, apply

PIPE_KINDS = {1: "shaft", 2: "pipe"}
NAME_RE = re.compile(r"^[A-Za-z0-9 _\-()]{1,64}$")
_LINK = re.compile(r"<logic_node_link\b([^>]*?)(?:/>|>(.*?)</logic_node_link>)", re.S)


def prefabs_dir():
    """The server's prefab side files. SW_PREFABS_DIR overrides; otherwise next to the drafts."""
    if os.environ.get("SW_PREFABS_DIR"):
        return Path(os.environ["SW_PREFABS_DIR"])
    if os.environ.get("SW_DESIGNS_DIR"):
        return Path(os.environ["SW_DESIGNS_DIR"]).parent / "prefabs"
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return Path(base) / "stormworks-hull-mcp" / "prefabs"


def file_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def links(text):
    """Saved wires as (type, end 0, end 1)."""
    container = re.search(r"<logic_node_links\b[^>]*(?:/>|>(.*?)</logic_node_links>)", text, re.S)
    out = []
    for m in _LINK.finditer(container[1] or "" if container else ""):
        typ = re.search(r'\btype="(\d+)"', m[1])
        ends = []
        for e in (0, 1):
            vp = re.search(rf"<voxel_pos_{e}\b([^>]*)/?>", m[2] or "")
            attrs = dict(re.findall(r'\b([xyz])="(-?\d+)"', vp[1])) if vp else {}
            ends.append(tuple(int(attrs.get(a, 0)) for a in "xyz"))
        out.append((int(typ[1]) if typ else 0, ends[0], ends[1]))
    return out


def link_xml(typ, a, b):
    t = f' type="{typ}"' if typ else ""
    pos = "".join(f"<voxel_pos_{e}" + "".join(f' {k}="{v}"' for k, v in zip("xyz", p) if v) + "/>"
                  for e, p in enumerate((a, b)))
    return f"<logic_node_link{t}>{pos}</logic_node_link>"


@lru_cache(maxsize=16)
def _document(text):
    return VehicleDocument.parse(text)


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "point"


def points(text):
    """Connection points of a vehicle file: logic nodes no wire reaches, and pipe or shaft faces
    that open onto empty space. Each point has a stable key and a default name."""
    from .networks import TYPE_NAMES, ports  # noqa: PLC0415
    doc = _document(text)
    wired = set()
    for typ, a, b in links(text):
        wired.update({(typ, a, 0), (typ, b, 1)} if typ in (0, 1, 5, 6, 7) else {(typ, a, None), (typ, b, None)})
    index = {p.uid: i for i, p in enumerate(doc.parts)}
    owner = {v: p for p in doc.parts for v in p.voxels()}
    out = []
    for p in doc.parts:
        for n in ports(p):
            if n["type"] in (2, 3):
                continue  # pipes and shafts: their faces are listed below
            mode = n["mode"] if n["type"] in (0, 1, 5, 6, 7) else None
            if (n["type"], n["position"], mode) in wired:
                continue
            out.append({"key": f"wire:{p.piece.d}:{_xyz(n['position'])}:{n['index']}", "kind": "wire",
                        "label": n["label"], "type": TYPE_NAMES.get(n["type"], str(n["type"])),
                        "direction": "output" if n["mode"] == 0 else "input",
                        "definition": p.piece.d, "part": index[p.uid], "port": n["index"],
                        "position": n["position"]})
    pairs, open_faces = adjacency(doc.parts, "prefab")
    by_uid = {p.uid: p for p in doc.parts}
    labels = {}
    for p in doc.parts:
        for n in ports(p):
            if n["type"] in (2, 3):
                labels[(p.uid, n["position"])] = (n["label"], "shaft" if n["type"] == 2 else "pipe")
    joined = {}
    for pair in pairs:
        a, b = pair["ports"]
        joined.setdefault(a["part_id"], []).append(b)
        joined.setdefault(b["part_id"], []).append(a)

    def carried(uid):
        """What a pipe run carries: the node at the component face it reaches in the prefab."""
        seen, stack = {uid}, [uid]
        while stack:
            for face in joined.get(stack.pop(), ()):
                q = by_uid[face["part_id"]]
                if q.uid in seen:
                    continue
                seen.add(q.uid)
                if not q.piece.d.startswith("trans_"):
                    return labels.get((q.uid, face["position"]))
                stack.append(q.uid)
        return None

    for f in open_faces:
        if add(f["position"], f["normal"]) in owner:
            continue  # pressed against another part: not an open end
        p = by_uid[f["part_id"]]
        if p.piece.d.startswith("trans_"):
            label, kind = carried(p.uid) or ("open", "pipe")
            label = f"{label} line"
        else:
            label, kind = labels.get((p.uid, f["position"]), ("open", PIPE_KINDS.get(f["trans_type"], "pipe")))
            label = f"{label} {kind}"
        out.append({"key": f"{kind}:{p.piece.d}:{_xyz(f['position'])}:{f['surface_index']}",
                    "kind": kind, "label": label, "definition": p.piece.d, "part": index[p.uid],
                    "face": f["surface_index"], "position": f["position"], "facing": f["normal"]})
    used = {}
    for row in out:
        base = _slug(row["label"])
        used[base] = used.get(base, 0) + 1
        row["name"] = base if used[base] == 1 else f"{base}_{used[base]}"
    return out


def _xyz(v):
    return ",".join(str(c) for c in v)


def summary(text):
    doc = _document(text)
    cells = [v for p in doc.parts for v in p.voxels()]
    lo = [min(v[i] for v in cells) for i in range(3)]
    hi = [max(v[i] for v in cells) for i in range(3)]
    return {"parts": len(doc.parts), "bodies": len(doc.bodies),
            "size_blocks": [hi[i] - lo[i] + 1 for i in range(3)], "bounds": [lo, hi],
            "microcontrollers": sum(p.piece.d == "microprocessor" for p in doc.parts),
            "wires": len(links(text))}


# --- side files ------------------------------------------------------------------------------

def _side(name):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError("prefab name must be 1-64 letters, digits, spaces, _ - ( )")
    return prefabs_dir() / f"{name}.json"


def make_record(name, file, text, old=None, rename=None, cut_from=None):
    """A prefab side-file record for vehicle `file` (its text given), keeping the names `old`
    gave points that still exist, then applying `rename` {current name: new name}."""
    old = old or {}
    if old and old.get("file") != file:
        raise ValueError(f"prefab '{name}' already names vehicle '{old.get('file')}'; choose another name")
    names = {k: v for k, v in old.get("names", {}).items()}
    by_name = {names.get(row["key"], row["name"]): row for row in points(text)}
    for old_name, new_name in (rename or {}).items():
        if not isinstance(new_name, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", new_name):
            raise ValueError("connection point names are 1-40 letters, digits, _ or -")
        if old_name not in by_name:
            raise ValueError(f"no connection point '{old_name}'; points are {', '.join(sorted(by_name)) or 'none'}")
        if new_name in by_name and new_name != old_name:
            raise ValueError(f"connection point name '{new_name}' is taken")
        row = by_name.pop(old_name)
        names[row["key"]] = new_name
        by_name[new_name] = row
    live = {row["key"] for row in by_name.values()}
    record = {"name": name, "file": file, "hash": file_hash(text),
              "names": {k: v for k, v in names.items() if k in live}}
    if cut_from or old.get("cut_from"):
        record["cut_from"] = cut_from or old["cut_from"]
    return record


def write(record):
    path = _side(record["name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def read(name):
    path = _side(name)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def describe(record, text, detail=True):
    """A prefab with its status against the vehicle file and its named connection points."""
    if text is None:
        return {"name": record["name"], "file": record["file"], "status": "missing: the vehicle file is gone"}
    rows = points(text)
    for row in rows:
        row["name"] = record.get("names", {}).get(row["key"], row["name"])
    status = "ok" if file_hash(text) == record.get("hash") else (
        "changed since it was registered; connection points were found again")
    out = {"name": record["name"], "file": record["file"], "status": status, **summary(text),
           "connection_points": len(rows)}
    if record.get("cut_from"):
        out["cut_from"] = record["cut_from"]
    if detail:
        out["points"] = [{k: v for k, v in row.items() if k not in ("key", "part")} for row in rows]
    return out


def all_records():
    folder = prefabs_dir()
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


# --- moving a prefab -------------------------------------------------------------------------

def placed(text, position, q=IDENTITY, prefix="paste"):
    """Copies of a prefab's parts and wires, rotated by q and moved so the lowest corner of the
    rotated prefab lands on `position`. Parts keep their saved XML, rewritten only where it
    holds a position or rotation; bodies keep the prefab's IDs (the caller renumbers them)."""
    import copy  # noqa: PLC0415
    doc = _document(text)
    if q != IDENTITY:
        stretched = [p for p in doc.parts if p.raw_xml and _geometry(p.raw_xml)[1]]
        if stretched:
            raise ValueError(f"this prefab has {len(stretched)} XML-edited (stretched) part(s); it can be "
                             "moved but not rotated")
    move = _mover(doc, position, q)

    out = []
    for i, p in enumerate(doc.parts):
        c = copy.copy(p)
        c.settings = copy.deepcopy(p.settings)
        c.origin = move(p.origin)
        c.Q = tuple(tuple(sum(q[r][k] * p.Q[k][s] for k in range(3)) for s in range(3)) for r in range(3))
        c.uid = f"{prefix}:{i}"
        if c.raw_xml:
            if _geometry(c.raw_xml)[1]:
                vp = "<vp" + "".join(f' {k}="{v}"' for k, v in zip("xyz", c.origin) if v) + "/>"
                c.raw_xml = re.sub(r"<vp\b[^>]*/>", lambda _m, vp=vp: vp, c.raw_xml, count=1)
            else:
                _move_raw(c)
        out.append(c)
    wires = [(typ, move(a), move(b)) for typ, a, b in links(text)]
    return out, wires, doc


def _mover(doc, position, q):
    cells = [apply(q, v) for p in doc.parts for v in p.voxels()]
    lo = tuple(min(v[i] for v in cells) for i in range(3))
    shift = tuple(position[i] - lo[i] for i in range(3))
    return lambda v: add(apply(q, v), shift)


def moved_wires(text, position, q=IDENTITY):
    """The prefab's wires where `placed` puts them, without copying its parts."""
    move = _mover(_document(text), position, q)
    return [(typ, move(a), move(b)) for typ, a, b in links(text)]


def resolve(parts, wires, prefix):
    """Wire rows for moved prefab wires whose two ends are on parts that still exist."""
    from .networks import SIGNALS, _ref, ports  # noqa: PLC0415
    at = {}
    for p in parts:
        for n in ports(p):
            at.setdefault((n["type"], n["position"]), []).append(n)
    rows = []
    for j, (typ, a, b) in enumerate(wires):
        ends = [at.get((typ, a), []), at.get((typ, b), [])]
        if typ in SIGNALS:
            ends = [[n for n in nodes if n["mode"] == e] for e, nodes in enumerate(ends)]
        if all(len(n) == 1 for n in ends):
            rows.append({"link_id": f"{prefix}:{j}", "type": typ, "from": _ref(ends[0][0]), "to": _ref(ends[1][0])})
    return rows


# --- cutting a prefab out of a vehicle -------------------------------------------------------

def cut(text, box, follow=()):
    """A new vehicle file holding the parts of `text` inside box ([[lo],[hi]], whole parts that
    reach into it), optionally following pipes and shafts (through every connected pipe part)
    and wires (one step, to the parts directly wired to the cut). Wires inside the cut are
    kept; the cut is centred on the workbench. Returns (xml, report)."""
    from .networks import ports  # noqa: PLC0415
    doc = VehicleDocument.parse(text)
    lo, hi = read_bounds(box)
    if set(follow) - {"pipes", "wires"}:
        raise ValueError("follow takes 'pipes' and/or 'wires'")
    chosen = {p.uid for p in doc.parts if any(all(lo[i] <= v[i] <= hi[i] for i in range(3)) for v in p.voxels())}
    if not chosen:
        raise ValueError("no parts inside the box")
    in_box = len(chosen)
    by_id = {p.uid: p for p in doc.parts}
    added = {"pipes": 0, "wires": 0}
    if "pipes" in follow:
        pairs, _ = adjacency(doc.parts, "cut")
        neighbours = {}
        for pair in pairs:
            a, b = (port["part_id"] for port in pair["ports"])
            neighbours.setdefault(a, set()).add(b)
            neighbours.setdefault(b, set()).add(a)
        queue = list(chosen)
        while queue:
            # Follow along pipe and shaft pieces; the component at the far end stays behind,
            # so its pipe becomes an open end (a connection point) of the prefab.
            for n in neighbours.get(queue.pop(), ()):
                if n not in chosen and by_id[n].piece.d.startswith("trans_"):
                    chosen.add(n)
                    added["pipes"] += 1
                    queue.append(n)
    if "wires" in follow:
        at = {}
        for p in doc.parts:
            for n in ports(p):
                at.setdefault(n["position"], set()).add(p.uid)
        extra = set()
        for _typ, a, b in links(text):
            ends = at.get(a, set()), at.get(b, set())
            if ends[0] & chosen and not ends[1] & chosen:
                extra |= ends[1]
            elif ends[1] & chosen and not ends[0] & chosen:
                extra |= ends[0]
        added["wires"] = len(extra - chosen)
        chosen |= extra
    kept = [p for p in doc.parts if p.uid in chosen]
    from . import bodies  # noqa: PLC0415
    broken = sorted(bodies.problems(kept) - bodies.problems(doc.parts))
    if broken:
        raise ValueError(f"the box splits a hinge, pivot or piston pair: {broken[0]}; widen the box")
    # Keep the wires whose two ends are inside the cut.
    keep_wires = []
    at = {}
    for p in kept:
        for n in ports(p):
            at.setdefault((n["type"], n["position"]), []).append(p.uid)
    for typ, a, b in links(text):
        if at.get((typ, a)) and at.get((typ, b)):
            keep_wires.append((typ, a, b))
    cells = [v for p in kept for v in p.voxels()]
    c_lo = [min(v[i] for v in cells) for i in range(3)]
    c_hi = [max(v[i] for v in cells) for i in range(3)]
    centre = tuple((c_lo[i] + c_hi[i]) // 2 for i in range(3))
    sub_text = _subset_xml(doc, kept)
    moved, wires, _ = placed(sub_text, tuple(c_lo[i] - centre[i] for i in range(3)), prefix="cut")
    xml = _write(moved, wires)
    return xml, {"parts": len(kept), "in_box": in_box, "followed_pipes": added["pipes"],
                 "followed_wires": added["wires"], "wires": len(keep_wires),
                 "bodies": len({p.body for p in kept})}


def _subset_xml(doc, kept):
    """The source file reduced to `kept`, with only the wires between kept parts."""
    from .networks import ports  # noqa: PLC0415
    xml = doc.to_xml(kept)
    at = set()
    for p in kept:
        for n in ports(p):
            at.add((n["type"], n["position"]))
    wires = [w for w in links(xml) if (w[0], w[1]) in at and (w[0], w[2]) in at]
    return _with_links(xml, wires)


def _with_links(xml, wires):
    body = "".join(link_xml(*w) for w in wires)
    new = f"<logic_node_links>{body}</logic_node_links>" if body else "<logic_node_links/>"
    out, n = re.subn(r"<logic_node_links\b[^>]*(?:/>|>.*?</logic_node_links>)", lambda _m: new, xml, count=1, flags=re.S)
    if not n:
        raise ValueError("vehicle has no logic_node_links container")
    return out


def _write(parts, wires):
    """A fresh vehicle file; bodies renumbered 1, 2, ... in order, the main body first."""
    from .vehicle import to_xml  # noqa: PLC0415
    numbers = {}
    for p in parts:
        numbers.setdefault(p.body, str(len(numbers) + 1))
    import copy  # noqa: PLC0415
    out = []
    for p in parts:
        c = copy.copy(p)
        c.body = numbers[p.body]
        out.append(c)
    return _with_links(to_xml(out), wires)


def paste_operation(text, position, rotation_value=None, replace=False, body=None, name=""):
    """The edit_parts operation that places a prefab (its file text travels with the draft)."""
    op = {"op": "paste", "xml": text, "position": list(vector(position, "position"))}
    if rotation_value is not None:
        rotation(rotation_value)
        op["rotation"] = rotation_value
    if replace:
        op["replace"] = True
    if body is not None:
        op["body"] = body
    if name:
        op["prefab"] = name
    return op
