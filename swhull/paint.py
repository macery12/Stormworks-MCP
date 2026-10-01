"""Paint on the outside of a design: rectangles, circles and block-letter text.

Paint recolours the outermost solid voxel under each painted spot: on the deck that is the
topmost voxel of the column (deck, or a box roof), on a side the outermost voxel of the row.
Text on a side reads toward the bow on starboard (+x) and toward the stern on port, so it is
readable from outside on both. Deck text reads from port to starboard with its top toward
the bow.
"""
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


def _m(coord):
    """Voxel centre (y or z) -> metres in spec units."""
    return (coord + 0.5) / VOX


def _hit(item, a, b):
    """Does the point (a, b) in metres fall in the painted shape? For sides a is z and b is y;
    for the deck a is z and b is x."""
    shape = item.get("shape", "rect")
    if shape == "rect":
        if item.get("on", "sides") == "deck":
            lo, hi = item.get("x", 0.0) - item.get("width", 1.0) / 2, item.get("x", 0.0) + item.get("width", 1.0) / 2
        else:
            lo, hi = item.get("y", 0.0), item.get("y", 0.0) + item.get("height", 1.0)
        return item["z"] <= a <= item["z"] + item.get("length", 1.0) and lo <= b <= hi
    if shape == "circle":
        cb = item.get("x", 0.0) if item.get("on", "sides") == "deck" else item.get("y", 0.0)
        r = item.get("radius", 1.0)
        d2 = (a - item["z"]) ** 2 + (b - cb) ** 2
        t = item.get("thickness")
        return d2 <= r * r and (not t or d2 >= (r - t) ** 2)
    return False


def paint_map(spec, solid, warnings):
    """{voxel: colour} for every paint item, applied in list order (later wins)."""
    items = spec.get("paint") or []
    if not items:
        return {}
    top, xmin, xmax = {}, {}, {}
    for (x, y, z) in solid:
        if y > top.get((x, z), -10**6):
            top[(x, z)] = y
        if x < xmin.get((y, z), 10**6):
            xmin[(y, z)] = x
        if x > xmax.get((y, z), -10**6):
            xmax[(y, z)] = x
    out = {}
    for i, item in enumerate(items):
        colour = item.get("color", "F0F0F0")
        on = item.get("on", "sides")
        hit = _text_hit(item, warnings, i) if item.get("shape") == "text" else (lambda a, b, s, it=item: _hit(it, a, b))
        n = 0
        if on == "deck":
            for (x, z), y in top.items():
                if hit(_m(z), x / VOX, 1):
                    out[(x, y, z)] = colour
                    n += 1
        else:
            sides = {"port": (xmin, -1), "starboard": (xmax, 1)}
            for name in (("port", "starboard") if on == "sides" else (on,)):
                table, sign = sides[name]
                for (y, z), x in table.items():
                    if hit(_m(z), _m(y), sign):
                        out[(x, y, z)] = colour
                        n += 1
        if not n:
            warnings.append(f"paint[{i}] ({item.get('shape', 'rect')} on {on}) touches no surface; "
                            "check its z, y/x and size")
    return out


def _text_hit(item, warnings, i):
    """Point test for block-letter text. `z` is the centre of the text along the hull; `y`
    (sides) is the bottom of the letters, `x` (deck) the centre across."""
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
        else:                # reads toward the bow on starboard, toward the stern on port
            along = (a - item["z"]) * sign
            col = int((along + half) // px)
            row = int((b - item.get("y", 0.0)) // px)
        return (col, row) in lit

    return hit
