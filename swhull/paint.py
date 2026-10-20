"""Paint on the outside of a design, face by face.

Each item is a flat design projected onto the faces that point one way: the deck (up), a side
(port -x, starboard +x), the bow end (front, +z) or the transom end (back, -z), optionally on
one superstructure box only. It paints the outermost voxel on each line of sight, and only that
voxel's faces pointing the item's way (slopes included), so side paint never runs onto the deck.

Shapes set a colour (rect, circle, text, polygon, line, stripes, camo) or shade what is already
there (panels). Text on a side reads toward the bow on starboard and toward the stern on port;
on the transom toward starboard and on the bow toward port; on the deck from port to
starboard with its top toward the bow.
"""
import math
import random

from .hull import VOX

# 3 x 5 block font; "#" is a lit pixel
FONT = {
    "0": ("###", "#.#", "#.#", "#.#", "###"), "1": (".#.", "##.", ".#.", ".#.", "###"),
    "2": ("###", "..#", "###", "#..", "###"), "3": ("###", "..#", ".##", "..#", "###"),
    "4": ("#.#", "#.#", "###", "..#", "..#"), "5": ("###", "#..", "###", "..#", "###"),
    "6": ("###", "#..", "###", "#.#", "###"), "7": ("###", "..#", ".#.", ".#.", ".#."),
    "8": ("###", "#.#", "###", "#.#", "###"), "9": ("###", "#.#", "###", "..#", "###"),
    "A": (".#.", "#.#", "###", "#.#", "#.#"), "B": ("##.", "#.#", "##.", "#.#", "##."),
    "C": (".##", "#..", "#..", "#..", ".##"), "D": ("##.", "#.#", "#.#", "#.#", "##."),
    "E": ("###", "#..", "##.", "#..", "###"), "F": ("###", "#..", "##.", "#..", "#.."),
    "G": (".##", "#..", "#.#", "#.#", ".##"), "H": ("#.#", "#.#", "###", "#.#", "#.#"),
    "I": ("###", ".#.", ".#.", ".#.", "###"), "J": ("..#", "..#", "..#", "#.#", ".#."),
    "K": ("#.#", "#.#", "##.", "#.#", "#.#"), "L": ("#..", "#..", "#..", "#..", "###"),
    "M": ("#.#", "###", "###", "#.#", "#.#"), "N": ("##.", "#.#", "#.#", "#.#", "#.#"),
    "O": (".#.", "#.#", "#.#", "#.#", ".#."), "P": ("##.", "#.#", "##.", "#..", "#.."),
    "Q": (".#.", "#.#", "#.#", "##.", ".##"), "R": ("##.", "#.#", "##.", "#.#", "#.#"),
    "S": (".##", "#..", ".#.", "..#", "##."), "T": ("###", ".#.", ".#.", ".#.", ".#."),
    "U": ("#.#", "#.#", "#.#", "#.#", "###"), "V": ("#.#", "#.#", "#.#", "#.#", ".#."),
    "W": ("#.#", "#.#", "###", "###", "#.#"), "X": ("#.#", "#.#", ".#.", "#.#", "#.#"),
    "Y": ("#.#", "#.#", ".#.", ".#.", ".#."), "Z": ("###", "..#", ".#.", "#..", "###"),
    "-": ("...", "...", "###", "...", "..."), ".": ("...", "...", "...", "...", ".#."),
    "/": ("..#", "..#", ".#.", "#..", "#.."), "#": ("#.#", "###", "#.#", "###", "#.#"),
    " ": ("...", "...", "...", "...", "..."),
}


def text_pixels(text):
    """Lit pixels (column, row from the bottom) and the total width in pixels."""
    out, col = [], 0
    for ch in text.upper():
        glyph = FONT.get(ch, FONT["#"])
        for r, row in enumerate(glyph):
            for c, cell in enumerate(row):
                if cell == "#":
                    out.append((col + c, 4 - r))
        col += 4
    return out, max(0, col - 1)


TARGETS = {"deck": ((0, 1, 0),), "port": ((-1, 0, 0),), "starboard": ((1, 0, 0),),
           "sides": ((-1, 0, 0), (1, 0, 0)), "front": ((0, 0, 1),), "back": ((0, 0, -1),)}
SHAPES = ("rect", "circle", "text", "polygon", "line", "stripes", "panels", "camo")
CAMO = ("dazzle", "splinter", "blotch")


def _plane(direction, v):
    """(a, b) design coordinates in metres of voxel v on a target facing `direction`: deck
    (z, x), sides (z, y), front and back (x, y). z and y run from the transom and keel (voxel
    centres), x from the centreline."""
    x, y, z = v[0] / VOX, (v[1] + 0.5) / VOX, (v[2] + 0.5) / VOX
    if direction[1]:
        return z, x
    if direction[0]:
        return z, y
    return x, y


def _seeded(*key):
    return random.Random(hash(key) & 0xFFFFFFFF).random()


def _inside(points, a, b):
    hit = False
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        if (y1 > b) != (y2 > b) and a < x1 + (b - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def _segment(p, q, a, b):
    dx, dy = q[0] - p[0], q[1] - p[1]
    t = max(0.0, min(1.0, ((a - p[0]) * dx + (b - p[1]) * dy) / (dx * dx + dy * dy or 1.0)))
    return math.hypot(a - p[0] - t * dx, b - p[1] - t * dy)


def _rect(item, on, a, b):
    if on in ("front", "back"):
        x, w = item.get("x", 0.0), item.get("width", 1.0)
        return x - w / 2 <= a <= x + w / 2 and item.get("y", 0.0) <= b <= item.get("y", 0.0) + item.get("height", 1.0)
    if not item["z"] <= a <= item["z"] + item.get("length", 1.0):
        return False
    if on == "deck":
        x, w = item.get("x", 0.0), item.get("width", 1.0)
        return x - w / 2 <= b <= x + w / 2
    return item.get("y", 0.0) <= b <= item.get("y", 0.0) + item.get("height", 1.0)


def _bounded(item, on, a, b):
    """Patterns cover their whole target unless the item also gives a rectangle."""
    key = "x" if on in ("front", "back") else "z"
    return key not in item or _rect(item, on, a, b)


def _centre(item, on):
    if on in ("front", "back"):
        return item.get("x", 0.0), item.get("y", 0.0)
    return item["z"], item.get("x", 0.0) if on == "deck" else item.get("y", 0.0)


def _camo(item, bounds):
    """Colour at (a, b) of a seeded camouflage pattern: dazzle (bold angular bands cut by
    straight lines), splinter (sharp-edged angular patches) or blotch (soft rounded patches)."""
    seed, colours = int(item.get("seed", 1)), item["colors"]
    scale, style = item.get("scale", 3.0), item.get("style", "splinter")
    if style == "dazzle":
        (a0, a1), (b0, b1) = bounds
        rng = random.Random(seed)
        lines = []
        for _ in range(int(item.get("lines", max(6, round(2.5 * (a1 - a0) / scale))))):
            ang = rng.uniform(0.15, math.pi - 0.15)
            ca, cb = rng.uniform(a0, a1), rng.uniform(b0, b1)
            lines.append((math.cos(ang), math.sin(ang), ca * math.cos(ang) + cb * math.sin(ang)))

        def dazzle(a, b):
            return colours[sum(1 for c, s, off in lines if a * c + b * s > off) % len(colours)]
        return dazzle
    if style == "blotch":
        def node(i, j):
            return _seeded(seed, i, j)

        def blotch(a, b):
            u, v = a / scale, b / scale * 1.6
            i, j = math.floor(u), math.floor(v)
            fu, fv = u - i, v - j
            fu, fv = fu * fu * (3 - 2 * fu), fv * fv * (3 - 2 * fv)
            top = node(i, j) * (1 - fu) + node(i + 1, j) * fu
            bot = node(i, j + 1) * (1 - fu) + node(i + 1, j + 1) * fu
            n = top * (1 - fv) + bot * fv
            return colours[min(len(colours) - 1, int(n * len(colours)))]
        return blotch

    def site(i, j):
        r = random.Random(hash((seed, i, j)) & 0xFFFFFFFF)
        return i + r.random(), j + r.random(), colours[r.randrange(len(colours))]

    def splinter(a, b):
        # Manhattan-distance Voronoi on slanted axes: straight edges at a rake, like splinter camo
        u, v = (a + 0.6 * b) / scale, b / (scale * 0.6)
        i, j = math.floor(u), math.floor(v)
        return min((abs(su - u) + abs(sv - v), c) for di in (-1, 0, 1) for dj in (-1, 0, 1)
                   for su, sv, c in [site(i + di, j + dj)])[1]
    return splinter


def _panels(item):
    """Shade at (a, b): staggered rectangular panels, about `share` of them shaded, the way
    builders break up a large flat wall with a second tone."""
    w, h = item.get("size", [2.0, 1.0])
    shade, share, seed = item.get("shade", -0.08), item.get("share", 0.45), int(item.get("seed", 1))

    def panel(a, b):
        j = math.floor(b / h)
        i = math.floor(a / w + (0.5 if j % 2 else 0.0))
        return shade if _seeded(seed, i, j) < share else None
    return panel


def designer(item, warnings, index, bounds):
    """op(a, b, sign) -> ("set", colour), ("shade", fraction) or None, for one paint item."""
    shape, on = item.get("shape", "rect"), item.get("on", "sides")
    colour = item.get("color", "F0F0F0")
    if shape == "text":
        hit = _text_hit(item, warnings, index)
        return lambda a, b, s: ("set", colour) if hit(a, b, s) else None
    if shape == "rect":
        return lambda a, b, s: ("set", colour) if _rect(item, on, a, b) else None
    if shape == "circle":
        ca, cb = _centre(item, on)
        r, t = item.get("radius", 1.0), item.get("thickness")

        def circle(a, b, s):
            d2 = (a - ca) ** 2 + (b - cb) ** 2
            return ("set", colour) if d2 <= r * r and (not t or d2 >= (r - t) ** 2) else None
        return circle
    if shape == "polygon":
        pts = [tuple(p) for p in item["points"]]
        return lambda a, b, s: ("set", colour) if _inside(pts, a, b) else None
    if shape == "line":
        p, q, w = tuple(item["from"]), tuple(item["to"]), item.get("width", 0.5)
        return lambda a, b, s: ("set", colour) if _segment(p, q, a, b) <= w / 2 else None
    if shape == "stripes":
        cols, width = item.get("colors", ["F2B705", "1A1A1A"]), item.get("stripe", 0.25)
        ang = math.radians(item.get("angle", 45))

        def stripes(a, b, s):
            if not _bounded(item, on, a, b):
                return None
            return ("set", cols[math.floor((a * math.cos(ang) + b * math.sin(ang)) / width) % len(cols)])
        return stripes
    if shape == "panels":
        shade = _panels(item)

        def panels(a, b, s):
            f = shade(a, b) if _bounded(item, on, a, b) else None
            return ("shade", f) if f is not None else None
        return panels
    pattern = _camo(item, bounds)
    return lambda a, b, s: ("set", pattern(a, b)) if _bounded(item, on, a, b) else None


def validate(items):
    """Problems with the paint list, as messages."""
    problems = []
    for i, item in enumerate(items or []):
        if not isinstance(item, dict):
            problems.append(f"paint[{i}] must be an object")
            continue
        shape, on = item.get("shape", "rect"), item.get("on", "sides")
        if shape not in SHAPES:
            problems.append(f"paint[{i}].shape must be one of {', '.join(SHAPES)}")
            continue
        if on not in TARGETS:
            problems.append(f"paint[{i}].on must be one of {', '.join(TARGETS)}")
            continue
        if item.get("box") is not None and not isinstance(item["box"], str):
            problems.append(f"paint[{i}].box must be a superstructure box name")
        position = ("x",) if on in ("front", "back") else ("z",)
        if shape in ("rect", "circle", "text") and not all(_num(item.get(k, 0 if k == "x" else None)) for k in position):
            problems.append(f"paint[{i}].{position[0]} is required (metres)")
        if shape == "text" and not isinstance(item.get("text"), str):
            problems.append(f"paint[{i}].text must be a string")
        if shape == "polygon" and not _points(item.get("points"), 3):
            problems.append(f"paint[{i}].points must be at least three [a, b] pairs in metres")
        if shape == "line" and not (_points([item.get("from"), item.get("to")], 2)):
            problems.append(f"paint[{i}] line needs from and to, each [a, b] in metres")
        if shape in ("stripes", "camo"):
            cols = item.get("colors", ["F2B705", "1A1A1A"] if shape == "stripes" else None)
            if not (isinstance(cols, list) and len(cols) >= 2 and all(_hex(c) for c in cols)):
                problems.append(f"paint[{i}].colors must list two or more hex colours")
        if shape == "camo" and item.get("style", "splinter") not in CAMO:
            problems.append(f"paint[{i}].style must be one of {', '.join(CAMO)}")
        if shape == "panels" and not (_num(item.get("shade", -0.08)) and -0.5 <= item.get("shade", -0.08) <= 0.5):
            problems.append(f"paint[{i}].shade must be -0.5 to 0.5 (negative darkens)")
        if "color" in item and not _hex(item["color"]):
            problems.append(f"paint[{i}].color must be a 6-digit hex colour")
    return problems


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _hex(c):
    return isinstance(c, str) and len(c) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in c)


def _points(points, n):
    return (isinstance(points, list) and len(points) >= n
            and all(isinstance(p, (list, tuple)) and len(p) == 2 and all(_num(c) for c in p) for p in points))


def paint_map(spec, cells, warnings, tag_of=None, boxes=None):
    """{(voxel, outward direction): [op, ...]}; each op is (item index, "set", colour) or
    (item index, "shade", fraction). `cells` are the occupied voxels (the placed parts,
    slope pieces outside the shape included); `tag_of(v)` gives "hull" or "boxN" and `boxes`
    maps box names to those tags."""
    items = spec.get("paint") or []
    out = {}
    if not items:
        return out
    extremes = {}

    def surface(direction, tag):
        """Voxels facing `direction` on each line of sight, within one box if set: the outermost
        and any up to DEPTH blocks behind it, whose faces show past slopes that only partly
        cover them (under a flare, at a chine)."""
        key = (direction, tag)
        if key not in extremes:
            axis = next(i for i in range(3) if direction[i])
            sign = direction[axis]
            lines = {}
            for v in cells:
                if tag is not None and tag_of(v) != tag:
                    continue
                line = (v[0], v[2]) if axis == 1 else (v[1], v[2]) if axis == 0 else (v[0], v[1])
                lines.setdefault(line, []).append(v)
            out = []
            for members in lines.values():
                front = max(v[axis] * sign for v in members)
                out += [v for v in members if front - v[axis] * sign <= DEPTH]
            extremes[key] = out
        return extremes[key]

    for i, item in enumerate(items):
        on = item.get("on", "sides")
        tag = None
        if item.get("box") is not None:
            tag = {**(boxes or {}), "hull": "hull"}.get(item["box"])
            if tag is None:
                warnings.append(f"paint[{i}]: no superstructure box named {item['box']!r}")
                continue
        n = 0
        for direction in TARGETS[on]:
            cells_seen = surface(direction, tag)
            if not cells_seen:
                continue
            plane = [_plane(direction, v) for v in cells_seen]
            bounds = ((min(p[0] for p in plane), max(p[0] for p in plane)),
                      (min(p[1] for p in plane), max(p[1] for p in plane)))
            op = designer(item, warnings, i, bounds)
            sign = direction[0] or direction[2] or 1
            pattern = item.get("shape") in ("panels", "camo", "stripes") and "z" not in item and "x" not in item
            n += len(cells_seen) if pattern else 0
            for v, (a, b) in zip(cells_seen, plane):
                result = op(a, b, sign)
                if result is not None:
                    out.setdefault((v, direction), []).append((i, *result))
                    n += 1
        if not n:
            warnings.append(f"paint[{i}] ({item.get('shape', 'rect')} on {on}) touches no surface; "
                            "check its position and size")
    return out


def _text_hit(item, warnings, i):
    """Point test for block-letter text. Sides: `z` is the centre along the hull and `y` the
    bottom of the letters; deck: `z` the centre along and `x` across; front and back: `x` the
    centre across and `y` the bottom."""
    text = item["text"]
    height = item.get("height", 1.25)
    px = height / 5
    if px < 1 / VOX - 1e-9:
        warnings.append(f"paint[{i}] text '{text}': letters under {5 / VOX:g} m tall lose pixels "
                        "(one block per pixel needs 1.25 m)")
    lit, width = text_pixels(text)
    lit = set(lit)
    half = width * px / 2
    on = item.get("on", "sides")

    def hit(a, b, sign):
        if on == "deck":     # columns run port -> starboard, rows toward the bow
            col = int((b - (item.get("x", 0.0) - half)) // px)
            row = int((a - (item["z"] - 2.5 * px)) // px)
        elif on in ("front", "back"):   # the transom reads toward starboard, the bow toward port
            col = int(((a - item.get("x", 0.0)) * -sign + half) // px)
            row = int((b - item.get("y", 0.0)) // px)
        else:                # reads toward the bow on starboard, toward the stern on port
            col = int(((a - item["z"]) * sign + half) // px)
            row = int((b - item.get("y", 0.0)) // px)
        return (col, row) in lit

    return hit


def shaded(colour, fraction):
    """colour lightened (fraction > 0) or darkened (< 0) by that share of the way to white or
    black."""
    rgb = [int(colour[i:i + 2], 16) for i in (0, 2, 4)]
    target = 255 if fraction > 0 else 0
    return "".join(f"{round(c + (target - c) * abs(fraction)):02X}" for c in rgb)


REACH = 0.4   # a face takes an item's paint when it leans at least this far toward the item
DEPTH = 3     # blocks behind the outermost voxel of a line of sight that paint still reaches


def face_ops(painted, v, n):
    """Paint ops for the face of voxel v with outward normal n, in item order: every target
    direction the face leans toward (a bow face that is half side, half forward takes side paint)."""
    ops = []
    for d in ((0, 1, 0), (1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1)):
        if n[0] * d[0] + n[1] * d[1] + n[2] * d[2] >= REACH:
            ops += painted.get((v, d), ())
    return sorted(ops, key=lambda op: op[0])


def resolve(base, ops):
    """Apply paint ops (index, kind, value) in order to a base colour."""
    colour = base
    for _i, kind, value in ops:
        colour = value if kind == "set" else shaded(colour, value)
    return colour.upper()
