"""Write `paint faces test.xml`: settles which face each `sc` colour paints, in game.

A block and a wedge stand on grey plinths, every surface a different colour. Each has an orange
marker block three blocks away along +x and a black one three blocks away along +z. In game,
note the colour of each test piece's face looking at each marker (and the face opposite);
compare with the expectation printed below. If they match, set faces.PAIRS_CONFIRMED = True.

    uv run tools/paint_faces_exhibit.py            # into the Stormworks vehicles folder
    uv run tools/paint_faces_exhibit.py out/x.xml  # anywhere else
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from swhull.faces import SURFACES, entries  # noqa: E402
from swhull.pieces import BLOCK, IDENTITY, WEDGE, Placed  # noqa: E402
from swhull.vehicle import centre, to_xml, vehicles_dir  # noqa: E402

PALETTE = [("red", "E02020"), ("green", "20B020"), ("blue", "2040E0"), ("yellow", "F0D020"),
           ("magenta", "D020D0"), ("cyan", "20D0D0")]
NAMES = {(1, 0, 0): "face looking at the orange marker", (-1, 0, 0): "face opposite the orange marker",
         (0, 1, 0): "top", (0, -1, 0): "bottom", (0, 0, 1): "face looking at the black marker",
         (0, 0, -1): "face opposite the black marker"}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(vehicles_dir(), "paint faces test.xml")
    parts = []
    for x0 in (0, 8):                     # one plinth per test piece, with its two markers
        parts += [Placed(BLOCK, (x, 0, z), color="808080") for x in range(x0, x0 + 4) for z in range(0, 4)]
        parts += [Placed(BLOCK, (x0 + 3, 1, 0), color="F28C28"), Placed(BLOCK, (x0, 1, 3), color="1A1A1A")]
    for piece, origin in ((BLOCK, (0, 1, 0)), (WEDGE, (8, 1, 0))):
        n = len(SURFACES[piece.d])
        parts.append(Placed(piece, origin, IDENTITY, PALETTE[0][1], faces=tuple(c for _, c in PALETTE[:n])))
        print(f"{piece.d} at {origin}: if `sc` follows the definition order you should see")
        for (_cell, normal), (name, _hex) in zip(entries(piece.d), PALETTE):
            where = NAMES.get(tuple(round(c) for c in normal)) if max(abs(c) for c in normal) > 0.99 else \
                "slope"
            print(f"   {name:8s} on the {where}")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_xml(centre(parts)))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
