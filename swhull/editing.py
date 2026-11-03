"""Transactional, body-local part overlays and lossless single-body vehicle imports."""
import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from itertools import product

from . import definitions
from .configuration import configure, new_settings, settings_of
from .pieces import (BLOCK, BY_NAME, IDENTITY, MIRRORED, ROTATIONS, Placed, add, apply, parse_r, r_attr,
                     sub, with_mirror)
from .vehicle import component_transform, component_xml, components_from_text

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


def rotation(value=None, allow_mirror=False):
    if value is None:
        return IDENTITY
    try:
        q = parse_r(value) if isinstance(value, str) else tuple(tuple(row) for row in value)
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError("rotation must be an r string or 3x3 local-to-world matrix") from exc
    if q not in ROTATIONS and not (allow_mirror and q in MIRRORED):
        raise ValueError("rotation must be an axis-aligned proper rotation"
                         + (" or mirrored placement matrix" if allow_mirror else ""))
    return tuple(tuple(int(n) for n in row) for row in q)


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
    from .part_policy import ensure_allowed  # noqa: PLC0415
    ensure_allowed(d)
    piece = BY_NAME.get(d) or definitions.load(d)
    if piece is None:
        raise ValueError(definitions.unavailable(d))
    settings, name = data.get("settings", {}), data.get("name", "")
    if not isinstance(settings, dict) or not isinstance(name, str):
        raise ValueError("settings must be an object and name must be a string")
    q = rotation(data.get("rotation"), allow_mirror=True)
    mirror = data.get("mirror", 0)
    if isinstance(mirror, bool) or not isinstance(mirror, int) or not 0 <= mirror <= 7:
        raise ValueError("mirror must be a local-axis bitmask from 0 to 7 (1=x, 2=y, 4=z)")
    if mirror:
        if q in MIRRORED:
            raise ValueError("use a mirrored placement matrix or rotation plus mirror, not both")
        q = with_mirror(q, mirror)
    out = Placed(piece, vector(data.get("position", default_origin)), q,
                 color(data.get("color", "C2C3C7")), uid, name, new_settings(d, settings))
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


def _components_content(text):
    """Content bounds of the outer components container, including controller containers."""
    depth, start = 0, None
    for token in re.finditer(r"<(/?)components\b[^>]*>", text):
        if token[1]:
            depth -= 1
            if depth == 0 and start is not None:
                return start, token.start()
        elif not token[0].endswith("/>"):
            if depth == 0:
                start = token.end()
            depth += 1
        if depth < 0:
            break
    raise ValueError("vehicle has no balanced components container")


@dataclass
class VehicleDocument:
    """A saved vehicle split so unchanged bytes are written back exactly.

    Every body keeps the text around its components (`lead` before the body element, `open` up
    to the component content, `tail` after the last component, `close` to the end of the body);
    each original component keeps the text before it in `gaps`."""
    prefix: str          # everything before the first body element
    suffix: str          # from </bodies> on: wires and the rest
    gaps: dict
    parts: list
    bodies: list
    floor: int = 0       # the vehicle's bodies_id counter
    stretched: int = 0   # XML-edited parts with a non-grid `r`, kept as saved

    @classmethod
    def parse(cls, text):
        head = re.search(r'<vehicle\b[^>]*\bdata_version="(\d+)"', text)
        if head is None or head[1] != "3":
            raise ValueError("editing requires data_version 3")
        opening = re.search(r"<bodies\b[^>]*>", text)
        closing = text.rfind("</bodies>")
        if opening is None or closing < opening.end():
            raise ValueError("vehicle has no bodies container")
        gaps, parts, bodies, cursor, count, seen, stretched = {}, [], [], opening.end(), 0, {}, 0
        from html import unescape  # noqa: PLC0415
        for match in re.finditer(r"<body\b[^>]*?(/?)>", text[:closing]):
            if match.start() < cursor:
                continue
            bid = (re.search(r'\bunique_id="([^"]*)"', match[0]) or [None, str(len(bodies) + 1)])[1]
            # Some saves repeat a unique_id; keep such bodies apart under an alias (the tag is kept as saved).
            seen[bid] = seen.get(bid, 0) + 1
            if seen[bid] > 1:
                bid = f"{bid}#{seen[bid]}"
            lead = text[cursor:match.start()]
            if match[1]:  # <body .../>: no components
                bodies.append({"id": bid, "lead": lead, "raw": match[0], "open": f'<body unique_id="{bid}"><components>',
                               "tail": "", "close": "</components></body>"})
                cursor = match.end()
                continue
            end = text.index("</body>", match.end()) + len("</body>")
            raw_element = element = text[match.start():end]
            empty = re.search(r"<components\s*/>", element)
            if empty and "</components>" not in element:
                element = element[:empty.start()] + "<components></components>" + element[empty.end():]
            content_start, content_end = _components_content(element)
            content = element[content_start:content_end]
            last = 0
            for start, stop in _component_spans(content):
                raw = content[start:stop]
                geom, skewed = _geometry(raw)
                stretched += skewed
                d, origin, q, paint = geom
                piece = BY_NAME.get(d) or definitions.load(d)
                if piece is None:
                    piece = type(BLOCK)(d, 6, 0.0, BLOCK.footprint, BLOCK.verts, BLOCK.faces)
                uid = f"original:{count}"
                count += 1
                extras = re.sub(r'<vp\b[^>]*/>|</?c\b[^>]*>|</?o\b[^>]*>', "", raw).strip()
                attrs = re.search(r"<o\b([^>]*)>", raw)
                attr_names = set(re.findall(r"\b(\w+)=", attrs[1])) if attrs else set()
                protected = (skewed or d not in BY_NAME or bool(extras)
                             or bool(attr_names - {"r", "sc", "bc", "ac", "gc"}))
                named = re.search(r'\bcustom_name="([^"]*)"', raw)
                parts.append(Placed(piece, origin, q, paint, uid, unescape(named[1]) if named else "",
                                    raw_xml=raw, protected=protected, body=bid))
                gaps[uid] = content[last:start]
                last = stop
            bodies.append({"id": bid, "lead": lead, "raw": raw_element, "open": element[:content_start],
                           "tail": content[last:], "close": element[content_end:]})
            cursor = end
        if not parts:
            raise ValueError("vehicle has no readable components")
        suffix = text[cursor:]
        endpoints = set()
        for m in re.finditer(r"<voxel_pos_[01]\b([^>]*)/?>", text[closing:]):
            attrs = dict(re.findall(r'\b([xyz])="(-?\d+)"', m[1]))
            endpoints.add(tuple(int(attrs.get(axis, 0)) for axis in "xyz"))
        for p in parts:
            p.protected |= p.origin in endpoints
        floor = re.search(r'<vehicle\b[^>]*\bbodies_id="(\d+)"', text)
        return cls(text[:opening.end()], suffix, gaps, parts, bodies, int(floor[1]) if floor else 0, stretched)

    @property
    def main(self):
        return self.bodies[0]["id"] if self.bodies else "1"

    def to_xml(self, parts):
        main = self.main
        remaining = {p.uid: p for p in parts}
        originals = {p.uid for p in self.parts}
        added = {}
        for p in parts:
            if p.uid not in originals:
                added.setdefault(p.body or main, []).append(p)
        existing = {b["id"] for b in self.bodies}
        new_ids = [int(b) for b in added if b.isdigit() and b not in existing]
        # Only a new body moves the counter, so an unedited file is written back as saved.
        prefix = re.sub(r'(<vehicle\b[^>]*\bbodies_id=")(\d+)(")',
                        lambda m: f"{m[1]}{max([int(m[2]), *new_ids])}{m[3]}", self.prefix, count=1)
        chunks = [prefix]
        by_body = {}
        for original in self.parts:
            by_body.setdefault(original.body, []).append(original)
        for body in self.bodies:
            content = []
            for original in by_body.get(body["id"], []):
                if original.uid in remaining:
                    content.append(self.gaps[original.uid] + component_xml(remaining.pop(original.uid)))
            content.extend(component_xml(p) for p in added.pop(body["id"], []))
            if not content:
                if body["id"] not in by_body:
                    chunks.append(body["lead"] + body["raw"])  # empty in the original: keep it as saved
                elif body["id"] == main:
                    chunks.append(body["lead"] + body["open"] + body["tail"] + body["close"])
                continue  # otherwise every part of this body was removed: drop the body
            chunks.append(body["lead"] + body["open"] + "".join(content) + body["tail"] + body["close"])
        for bid in sorted(added, key=lambda b: (not b.isdigit(), int(b) if b.isdigit() else 0, b)):
            chunks.append(f'<body unique_id="{bid}"><components>' + "".join(component_xml(p) for p in added[bid])
                          + "</components></body>")
        chunks.append(self.suffix)
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
        raise ValueError("select needs ids, bounds, name, definition or body")
    if set(selector) - {"ids", "bounds", "name", "definition", "body"}:
        raise ValueError("unknown selection field")
    ids = selector.get("ids")
    if ids is not None and (not isinstance(ids, list) or not ids):
        raise ValueError("ids must be a nonempty list")
    if ids is not None and set(ids) - {p.uid for p in parts}:
        raise ValueError("stale or missing part identifiers; query_parts again")
    extent = bounds(selector["bounds"]) if "bounds" in selector else None
    main = parts[0].body if parts and parts[0].body else "1"
    out = []
    for p in parts:
        if "body" in selector and (p.body or main) != str(selector["body"]):
            continue
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
    main = parts[0].body if parts and parts[0].body else "1"
    rows = []
    for p in chosen[offset:offset + limit]:
        cells = p.voxels()
        rot, mirror = component_transform(p)
        rows.append({"id": p.uid, "body": p.body or main, "name": p.name, "definition": p.piece.d,
                     "position": p.origin, "rotation": r_attr(rot), "mirror": mirror,
                     "transform": p.Q, "color": p.color,
                     "settings": {k: v for k, v in settings_of(p).items()
                                  if k not in ("r", "sc", "bc", "bc2", "bc3", "ac", "gc", "custom_name")},
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
        if "</microprocessor_definition>" in p.raw_xml:  # the game writes vp right after the logic
            p.raw_xml = p.raw_xml.replace("</microprocessor_definition>", "</microprocessor_definition>" + vp, 1)
        elif re.search(r"<o\b[^>]*?(?<!/)>", p.raw_xml):
            p.raw_xml = re.sub(r"(<o\b[^>]*?(?<!/)>)", lambda m: m[1] + vp, p.raw_xml, count=1)
        elif "</o>" in p.raw_xml:
            p.raw_xml = p.raw_xml.replace("</o>", vp + "</o>", 1)
        else:
            p.raw_xml = re.sub(r"<o\b([^>]*?)/>", lambda m: "<o" + m[1] + ">" + vp + "</o>",
                              p.raw_xml, count=1)
    q, mirror = component_transform(p)
    if ' r="' in p.raw_xml:
        p.raw_xml = re.sub(r' r="[^"]*"', f' r="{r_attr(q)}"', p.raw_xml, count=1)
    else:
        p.raw_xml = re.sub(r"<o\b", f'<o r="{r_attr(q)}"', p.raw_xml, count=1)
    p.raw_xml = re.sub(r'(<c\b[^>]*?) t="[^"]*"', r"\1", p.raw_xml, count=1)
    if mirror:
        p.raw_xml = re.sub(r"<c\b", f'<c t="{mirror}"', p.raw_xml, count=1)


def _geometry(raw):
    """(definition, origin, Q, colour) of one saved component, and whether its `r` was XML-edited.

    A stretched or sheared `r` (a community XML-editing trick) gets the nearest grid rotation for
    geometry; the component itself stays protected and is written back exactly as saved."""
    try:
        geom = next(components_from_text(raw), None)
        skewed = False
    except ValueError:
        tag = re.search(r'<o\b[^>]*?\br="([^"]*)"', raw)
        if tag is None:
            raise
        from .pieces import nearest_rotation  # noqa: PLC0415
        q = nearest_rotation(tag[1])
        start, end = tag.span(1)
        geom = next(components_from_text(raw[:start] + r_attr(q) + raw[end:]), None)
        skewed = True
    if geom is None:
        raise ValueError("unsupported component without readable geometry")
    return geom, skewed


def _body_choice(value, known, fresh=None):
    """An explicit body: an existing ID, or "new" for a new body shared by this operation."""
    if value is None:
        return None
    if str(value) == "new" and fresh is not None:
        return fresh
    if str(value) not in known:
        raise ValueError(f"no body {value!r}; bodies are {', '.join(sorted(known))}")
    return str(value)


PASTE_FIELDS = frozenset(("op", "xml", "position", "rotation", "replace", "body", "prefab"))


def _paste(out, op, key, known, body_floor):
    """Place a prefab (paste_prefab builds this operation). Its main body joins the body it is
    placed against (or `body`); each of its other bodies becomes a new body."""
    from . import bodies  # noqa: PLC0415
    from .pieces import DIRS  # noqa: PLC0415
    from .prefabs import placed  # noqa: PLC0415
    if set(op) - PASTE_FIELDS or not isinstance(op.get("xml"), str):
        raise ValueError("paste needs the prefab file text; use paste_prefab")
    created, _, _ = placed(op["xml"], vector(op.get("position")), rotation(op.get("rotation")), key)
    footprint = {v for p in created for v in p.voxels()}
    hit = [p for p in out if any(v in footprint for v in p.voxels())]
    if hit and not op.get("replace"):
        raise ValueError(f"the prefab overlaps {len(hit)} part(s), first {hit[0].uid} ({hit[0].piece.d}) at "
                         f"{list(hit[0].origin)}; move it, or set replace to remove those parts")
    if any(p.protected for p in hit):
        raise ValueError("the prefab would replace configured or wired parts; move it instead")
    gone = {p.uid for p in hit}
    out = [p for p in out if p.uid not in gone]
    main = bodies.root(out)
    prefab_main = created[0].body
    target = _body_choice(op.get("body"), known, bodies.next_id(out, body_floor))
    if target is None:
        at = {v: p.body or main for p in out for v in p.voxels()}
        touching = {at[add(v, d)] for p in created if p.body == prefab_main for v in p.voxels()
                    for d in DIRS if add(v, d) in at}
        if len(touching) > 1:
            raise ValueError(f"the prefab touches bodies {', '.join(sorted(touching))}; give it a body")
        target = touching.pop() if touching else main
    counter = int(bodies.next_id(out, body_floor))
    numbers = {prefab_main: target}
    for p in created:
        if p.body not in numbers:
            if str(counter) == target:
                counter += 1
            numbers[p.body] = str(counter)
            counter += 1
    for p in created:
        p.body = numbers[p.body]
    return out + created, created


def _collisions(parts):
    owner, pairs = {}, set()
    for p in parts:
        for v in p.voxels():
            for uid in owner.get(v, ()):
                pairs.add((v, *sorted((uid, p.uid))))
            owner.setdefault(v, []).append(p.uid)
    return pairs


def apply_edits(parts, operations, prefix="edit", reserved=frozenset(), placement_context=None, body_floor=0):
    """Return a new list; failures never change the input or stored draft.

    New parts join a body (see bodies.assign); a new hinge, pivot or piston parent half adds its
    child half in a new body; an edit that splits a pair or orphans a body is refused."""
    from . import bodies  # noqa: PLC0415
    if not isinstance(operations, list) or any(not isinstance(op, dict) for op in operations):
        raise ValueError("operations must be a list of objects")
    out = []
    for p in parts:
        clone = copy.copy(p)  # Piece geometry, tuples and raw XML are immutable.
        clone.settings = copy.deepcopy(p.settings)
        out.append(clone)
    identify(out)
    original = {p.uid: (p.piece.d, p.origin, p.Q) for p in out}
    geometric = any(op.get("op") not in ("paint", "configure") for op in operations)
    previous = _collisions(out) if geometric else set()
    broken = bodies.problems(out) if geometric else set()
    pasted = set()
    for index, op in enumerate(operations):
        kind, key = op.get("op"), f"{prefix}:{index}"
        created, explicit = [], {}
        main = bodies.root(out)
        known = {p.body or main for p in out}
        fresh = bodies.next_id(out, body_floor)
        if kind == "add":
            data = op.get("parts", [op.get("part")])
            if not isinstance(data, list) or len(data) > MAX_BATCH_PARTS:
                raise ValueError("parts must be a bounded list")
            for i, d in enumerate(data):
                created.append(part(d, f"{key}:{i}"))
                if isinstance(d, dict) and d.get("body") is not None:
                    explicit[id(created[-1])] = _body_choice(d["body"], known, fresh)
        elif kind == "fill":
            lo, hi = bounds(op.get("bounds"))
            if math.prod(hi[i] - lo[i] + 1 for i in range(3)) > MAX_BATCH_PARTS:
                raise ValueError(f"fill exceeds {MAX_BATCH_PARTS} parts")
            body = _body_choice(op.get("body"), known, fresh)
            for i, v in enumerate(product(*(range(lo[a], hi[a] + 1) for a in range(3)))):
                created.append(part({"position": v, "color": op.get("color", "C2C3C7")}, f"{key}:{i}"))
                if body:
                    explicit[id(created[-1])] = body
        elif kind in ("remove", "replace", "move", "rotate", "paint", "copy", "mirror", "repeat", "configure"):
            chosen = select(out, op.get("select"))
            if kind not in ("paint", "configure") and any(p.protected for p in chosen):
                raise ValueError("configured or linked original components are protected; repaint them or add new parts")
            if kind == "remove":
                ids = {p.uid for p in chosen}
                out = [p for p in out if p.uid not in ids]
            elif kind == "replace":
                for p in chosen:
                    replacement = part(op.get("part"), p.uid, p.origin)
                    replacement.body = p.body
                    out[next(i for i, q in enumerate(out) if q is p)] = replacement
            elif kind == "paint":
                for p in chosen:
                    _paint(p, op.get("color"))
            elif kind == "configure":
                for p in chosen:
                    configure(p, op.get("settings"))
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
                            p.body = ""
                            out.append(p)
                            created.append(p)
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
                    p.body = ""
                    _move_raw(p)
                    out.append(p)
                    created.append(p)
        elif kind == "paste":
            out, created = _paste(out, op, key, known, body_floor)
            pasted.update(p.uid for p in created)
        elif kind == "tank":
            from .tanks import custom  # noqa: PLC0415
            created = custom(out, op, key)
        else:
            raise ValueError(f"unsupported edit operation {kind!r}")
        if kind in ("add", "fill", "tank"):
            bodies.assign(out + created, created, explicit)
            out.extend(created)
        elif kind in ("copy", "repeat", "mirror"):
            bodies.assign(out, created)
        if kind != "paste":  # a prefab brings its own child halves
            out.extend(bodies.spawn_children(out, created, body_floor))
        if not out:
            raise ValueError("an edit cannot remove every part")
        if kind not in ("paint", "configure"):
            collisions = _collisions(out)
            if collisions - previous:
                raise ValueError(f"edit {index}: part footprint collision {next(iter(collisions - previous))}")
            previous = collisions
    if geometric:
        new_problems = bodies.problems(out) - broken
        if new_problems:
            raise ValueError(sorted(new_problems)[0])
    # Validate the completed batch so a caller can add a component before its mounting blocks.
    # Untouched configured imports remain in place; their game settings are not reinterpreted.
    from .components import owners, validate_placement  # noqa: PLC0415
    # A child half hangs on its parent half's joint, which bodies.problems already checked.
    # Pasted prefab parts are mounted inside their prefab; paste_prefab reports loose ones.
    changed = [p for p in out if p.piece.d not in BY_NAME and p.piece.d not in bodies.CHILDREN
               and p.uid not in pasted and original.get(p.uid) != (p.piece.d, p.origin, p.Q)]
    owner = owners(out) if changed else {}
    for p in changed:
        without_self = {v: other for v, other in owner.items() if other is not p}
        validate_placement(p, placement_context or {}, without_self, reserved)
    if reserved:
        for p in out:
            if original.get(p.uid) != (p.piece.d, p.origin, p.Q) and any(v in reserved for v in p.voxels()):
                raise ValueError("edit blocks a reserved access passage")
    return out
