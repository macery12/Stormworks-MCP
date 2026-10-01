"""Transactional, body-local part overlays and lossless single-body vehicle imports."""
import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from itertools import product

from . import definitions
from .pieces import (BLOCK, BY_NAME, IDENTITY, ROTATIONS, Placed, add, apply, parse_r, r_attr,
                     split_mirror, sub)
from .vehicle import component_xml, components_from_text

MAX_BATCH_PARTS = 250000


def revision(record):
    data = {k: v for k, v in record.items() if k not in ("history", "vehicle", "preset")}
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]


def vector(value, label="position", integer=True):
    if not isinstance(value, (list, tuple)) or len(value) != 3 or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value):
        raise ValueError(f"{label} must be three finite numbers")
    if integer and any(int(x) != x for x in value):
        raise ValueError(f"{label} uses integer blocks (one block = 0.25 m)")
    return tuple(int(x) if integer else float(x) for x in value)


def rotation(value=None):
    if value is None:
        return IDENTITY
    try:
        q = parse_r(value) if isinstance(value, str) else tuple(tuple(row) for row in value)
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError("rotation must be an r string or 3x3 local-to-world matrix") from exc
    if q not in ROTATIONS:
        raise ValueError("rotation must be one of the 24 axis-aligned proper rotations")
    return q


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        raise ValueError("color must be six hexadecimal digits")
    return value.upper()


def part(data, uid="", default_origin=None):
    if not isinstance(data, dict):
        raise ValueError("part must be an object")
    d = data.get("definition", "01_block")
    if not isinstance(d, str):
        raise ValueError("definition must be a string")
    piece = BY_NAME.get(d) or definitions.load(d)
    if piece is None:
        raise ValueError(f"definition {d!r} unavailable; install Stormworks or set SW_DEFINITIONS_DIR")
    settings, name = data.get("settings", {}), data.get("name", "")
    if not isinstance(settings, dict) or not isinstance(name, str):
        raise ValueError("settings must be an object and name must be a string")
    out = Placed(piece, vector(data.get("position", default_origin)), rotation(data.get("rotation")),
                 color(data.get("color", "C2C3C7")), uid, name, copy.deepcopy(settings))
    component_xml(out)
    return out


def identify(parts):
    for p in parts:
        if not p.uid:
            raw = f"{p.piece.d}:{p.origin}:{p.Q}:{p.name}"
            p.uid = "g:" + hashlib.sha256(raw.encode()).hexdigest()[:20]
    return parts


def _component_spans(text):
    """Balance c tags; configured microcontrollers may contain nested c elements."""
    depth, start = 0, None
    for match in re.finditer(r"<(/?)c\b[^>]*>", text):
        token = match.group()
        if match.group(1):
            depth -= 1
            if depth == 0:
                yield start, match.end()
        elif token.endswith("/>"):
            if depth == 0:
                yield match.start(), match.end()
        else:
            if depth == 0:
                start = match.start()
            depth += 1
        if depth < 0:
            raise ValueError("unbalanced component XML")
    if depth:
        raise ValueError("unbalanced component XML")


@dataclass
class VehicleDocument:
    prefix: str
    suffix: str
    gaps: dict
    parts: list
    tail: str = ""

    @classmethod
    def parse(cls, text):
        head = re.search(r'<vehicle\b[^>]*\bdata_version="(\d+)"', text)
        if head is None or head[1] != "3":
            raise ValueError("editing requires data_version 3")
        if len(re.findall(r"<body\b", text)) != 1:
            raise ValueError("editing requires a single-body vehicle; multi-body editing is unsupported")
        container = re.search(r"<components\b[^>]*>(.*?)</components>", text, re.S)
        if container is None:
            raise ValueError("vehicle has no components container")
        body = container[1]
        gaps, parts, end = {}, [], 0
        for i, (start, stop) in enumerate(_component_spans(body)):
            raw = body[start:stop]
            geom = list(components_from_text(raw))
            if not geom:
                raise ValueError("unsupported component without readable geometry")
            d, origin, q, paint = geom[0]
            piece = BY_NAME.get(d) or definitions.load(d)
            if piece is None:
                piece = type(BLOCK)(d, 6, 0.0, BLOCK.footprint, BLOCK.verts, BLOCK.faces)
            uid = f"original:{i}"
            extras = re.sub(r'<vp\b[^>]*/>|</?c\b[^>]*>|</?o\b[^>]*>', "", raw).strip()
            attrs = re.search(r"<o\b([^>]*)>", raw)
            attr_names = set(re.findall(r"\b(\w+)=", attrs[1])) if attrs else set()
            protected = d not in BY_NAME or bool(extras) or bool(attr_names - {"r", "sc", "bc", "ac", "gc"})
            parts.append(Placed(piece, origin, q, paint, uid, raw_xml=raw, protected=protected))
            gaps[uid] = body[end:start]
            end = stop
        if not parts:
            raise ValueError("vehicle has no readable components")
        endpoints = set()
        for m in re.finditer(r"<voxel_pos_[01]\b([^>]*)/?>", text[container.end():]):
            attrs = dict(re.findall(r'\b([xyz])="(-?\d+)"', m[1]))
            endpoints.add(tuple(int(attrs.get(axis, 0)) for axis in "xyz"))
        for p in parts:
            p.protected |= p.origin in endpoints
        return cls(text[:container.start(1)], text[container.end(1):], gaps, parts, body[end:])

    def to_xml(self, parts):
        remaining = {p.uid: p for p in parts}
        chunks = [self.prefix]
        for original in self.parts:
            chunks.append(self.gaps[original.uid])
            if original.uid in remaining:
                chunks.append(component_xml(remaining.pop(original.uid)))
        chunks.extend(component_xml(p) for p in remaining.values())
        chunks.extend((self.tail, self.suffix))
        return "".join(chunks)


def bounds(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("bounds must be [[min_x,min_y,min_z],[max_x,max_y,max_z]] in blocks, inclusive")
    lo, hi = (vector(v, "bounds") for v in value)
    if any(lo[i] > hi[i] for i in range(3)):
        raise ValueError("bounds minima must not exceed maxima")
    return lo, hi


def select(parts, selector):
    if not isinstance(selector, dict) or not selector:
        raise ValueError("select needs ids, bounds, name or definition")
    if set(selector) - {"ids", "bounds", "name", "definition"}:
        raise ValueError("unknown selection field")
    ids = selector.get("ids")
    if ids is not None and (not isinstance(ids, list) or not ids):
        raise ValueError("ids must be a nonempty list")
    if ids is not None and set(ids) - {p.uid for p in parts}:
        raise ValueError("stale or missing part identifiers; query_parts again")
    extent = bounds(selector["bounds"]) if "bounds" in selector else None
    out = []
    for p in parts:
        if ids is not None and p.uid not in ids:
            continue
        if "name" in selector and p.name != selector["name"]:
            continue
        if "definition" in selector and p.piece.d != selector["definition"]:
            continue
        if extent:
            lo, hi = extent
            hits = [all(lo[i] <= v[i] <= hi[i] for i in range(3)) for v in p.voxels()]
            if any(hits) and not all(hits):
                raise ValueError(f"selection partially intersects {p.uid}; select its id to edit the whole part")
            if not any(hits):
                continue
        out.append(p)
    if not out:
        raise ValueError("selection contains no parts")
    return out


def query(parts, selector=None, offset=0, limit=100):
    if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("offset must be nonnegative and limit must be 1-1000")
    chosen = select(parts, selector) if selector else parts
    rows = []
    for p in chosen[offset:offset + limit]:
        cells = p.voxels()
        rows.append({"id": p.uid, "body": 1, "name": p.name, "definition": p.piece.d,
                     "position": p.origin, "rotation": r_attr(p.Q), "color": p.color,
                     "bounds": [[min(v[i] for v in cells) for i in range(3)],
                                [max(v[i] for v in cells) for i in range(3)]],
                     "footprint": list(cells), "protected": p.protected})
    return {"parts": rows, "total": len(chosen),
            "next_offset": offset + len(rows) if offset + len(rows) < len(chosen) else None,
            "coordinates": "integer blocks; uncentred hull build frame, or original imported body-local frame"}


def _paint(p, paint):
    p.color = color(paint)
    if p.raw_xml:
        def recolor(match):
            count = int(match[1].split(",")[0])
            return f'sc="{count}' + f",{p.color}" * count + '"'
        p.raw_xml, n = re.subn(r'sc="([^"]*)"', recolor, p.raw_xml, count=1)
        if not n:
            p.raw_xml = re.sub(r"<o\b", f'<o sc="{p.piece.surfaces}'
                              + f",{p.color}" * p.piece.surfaces + '"', p.raw_xml, count=1)


def _move_raw(p):
    if not p.raw_xml:
        return
    vp = "<vp" + "".join(f' {k}="{v}"' for k, v in zip("xyz", p.origin) if v) + "/>"
    p.raw_xml = re.sub(r"<vp\b[^>]*/>", lambda _m: vp, p.raw_xml, count=1)
    if not re.search(r"<vp\b", p.raw_xml):
        if "</o>" in p.raw_xml:
            p.raw_xml = p.raw_xml.replace("</o>", vp + "</o>", 1)
        else:
            p.raw_xml = re.sub(r"<o\b([^>]*?)/>", lambda m: "<o" + m[1] + ">" + vp + "</o>",
                              p.raw_xml, count=1)
    q, mirror = split_mirror(p.Q)
    if ' r="' in p.raw_xml:
        p.raw_xml = re.sub(r' r="[^"]*"', f' r="{r_attr(q)}"', p.raw_xml, count=1)
    else:
        p.raw_xml = re.sub(r"<o\b", f'<o r="{r_attr(q)}"', p.raw_xml, count=1)
    p.raw_xml = re.sub(r'(<c\b[^>]*?) t="[^"]*"', r"\1", p.raw_xml, count=1)
    if mirror:
        p.raw_xml = re.sub(r"<c\b", f'<c t="{mirror}"', p.raw_xml, count=1)


def _collisions(parts):
    owner, pairs = {}, set()
    for p in parts:
        for v in p.voxels():
            for uid in owner.get(v, ()):
                pairs.add(tuple(sorted((uid, p.uid))))
            owner.setdefault(v, []).append(p.uid)
    return pairs


def apply_edits(parts, operations, prefix="edit"):
    """Return a new list; failures never change the input or stored draft."""
    if not isinstance(operations, list) or any(not isinstance(op, dict) for op in operations):
        raise ValueError("operations must be a list of objects")
    out = identify(copy.deepcopy(parts))
    previous = _collisions(out)
    for index, op in enumerate(operations):
        kind, key = op.get("op"), f"{prefix}:{index}"
        if kind == "add":
            data = op.get("parts", [op.get("part")])
            if not isinstance(data, list) or len(data) > MAX_BATCH_PARTS:
                raise ValueError("parts must be a bounded list")
            out.extend(part(d, f"{key}:{i}") for i, d in enumerate(data))
        elif kind == "fill":
            lo, hi = bounds(op.get("bounds"))
            if math.prod(hi[i] - lo[i] + 1 for i in range(3)) > MAX_BATCH_PARTS:
                raise ValueError(f"fill exceeds {MAX_BATCH_PARTS} parts")
            for i, v in enumerate(product(*(range(lo[a], hi[a] + 1) for a in range(3)))):
                out.append(part({"position": v, "color": op.get("color", "C2C3C7")}, f"{key}:{i}"))
        elif kind in ("remove", "replace", "move", "rotate", "paint", "copy", "mirror", "repeat"):
            chosen = select(out, op.get("select"))
            if kind != "paint" and any(p.protected for p in chosen):
                raise ValueError("configured or linked original components are protected; repaint them or add new parts")
            if kind == "remove":
                ids = {p.uid for p in chosen}
                out = [p for p in out if p.uid not in ids]
            elif kind == "replace":
                for p in chosen:
                    out[out.index(p)] = part(op.get("part"), p.uid, p.origin)
            elif kind == "paint":
                for p in chosen:
                    _paint(p, op.get("color"))
            elif kind in ("move", "copy", "repeat"):
                delta = vector(op.get("delta"), "delta")
                count = op.get("count", 1) if kind == "repeat" else 1
                if not isinstance(count, int) or not 1 <= count <= 1000:
                    raise ValueError("repeat count must be 1-1000 additional copies")
                if len(chosen) * count > MAX_BATCH_PARTS:
                    raise ValueError("repeat exceeds batch part limit")
                for k in range(1, count + 1):
                    for i, source in enumerate(chosen):
                        p = source if kind == "move" else copy.deepcopy(source)
                        p.origin = add(source.origin, tuple(k * d for d in delta))
                        if kind != "move":
                            p.uid, p.name = f"{key}:{k}:{i}", f"{source.name}_{k}" if source.name else ""
                            out.append(p)
                        _move_raw(p)
            elif kind == "rotate":
                q, pivot = rotation(op.get("rotation")), vector(op.get("pivot", [0, 0, 0]), "pivot")
                for p in chosen:
                    p.origin = add(pivot, apply(q, sub(p.origin, pivot)))
                    p.Q = tuple(tuple(sum(q[i][k] * p.Q[k][j] for k in range(3))
                                     for j in range(3)) for i in range(3))
                    _move_raw(p)
            else:
                axis, plane = op.get("axis", "x"), op.get("plane", 0)
                if axis not in ("x", "y", "z"):
                    raise ValueError("mirror axis must be x, y or z")
                if not isinstance(plane, (int, float)) or not math.isfinite(plane) or 2 * plane != int(2 * plane):
                    raise ValueError("mirror plane must be a whole or half block")
                a = "xyz".index(axis)
                for i, source in enumerate(chosen):
                    p = copy.deepcopy(source)
                    p.origin = tuple(int(2 * plane - v) if k == a else v for k, v in enumerate(p.origin))
                    p.Q = tuple(tuple(-v if k == a else v for v in row) for k, row in enumerate(p.Q))
                    p.uid = f"{key}:{i}"
                    p.name = f"{p.name}_mirror" if p.name else ""
                    _move_raw(p)
                    out.append(p)
        else:
            raise ValueError(f"unsupported edit operation {kind!r}")
        if not out:
            raise ValueError("an edit cannot remove every part")
        collisions = _collisions(out)
        if collisions - previous:
            raise ValueError(f"edit {index}: part footprint collision {next(iter(collisions - previous))}")
        previous = collisions
    return out
