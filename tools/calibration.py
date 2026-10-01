"""Write in-game calibration vehicles for the slope pieces.

"hull test calibration": five shapes on one base plate, in two columns: a 45-degree hip
roof and a 45-degree funnel (Wedges on convex and concave slopes), a 1:2 hip roof (Wedge 1x2),
a 1:4 hip roof (Wedge 1x4), and a diamond whose 3-axis diagonal faces need Pyramids and
Inverse Pyramids.

"hull test calibration corners": five low diamonds whose faces need the larger corner
pieces: 1:2 and 1:4 in both directions (Pyramid / Inverse Pyramid 2x2 and 4x4), 1:2 one
way and 1:4 the other (2x4), and steep faces stretched along one axis (1x2 and 1x4).

Every piece type has its own colour, so a wrong rotation shows up as one colour looking
wrong. The base plate is part of the shape while fitting, as a hull would be.

    uv run tools/calibration.py [--preview out_prefix]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from swhull.pieces import BLOCK, Placed, add, apply  # noqa: E402
from swhull.render import render_png  # noqa: E402
from swhull.smooth import fit_pieces  # noqa: E402
from swhull.vehicle import centre, to_xml, vehicles_dir  # noqa: E402

COLOURS = {"01_block": "8A8F96", "02_wedge": "2FA84F", "05_wedge_2": "2F6FD6",
           "08_wedge_4": "8E44AD", "03_pyramid": "F2C318", "04_invpyramid": "E8702A",
           "06_pyramid_2": "F7E07A", "09_pyramid_4": "C9A800", "07_invpyramid_2": "F4A26B",
           "10_invpyramid_4": "B04A0C", "11_pyramid_2x2": "7FE0E0", "12_pyramid_2x4": "1FB5B5",
           "13_pyramid_4x4": "0B6E6E", "14_invpyramid_2x2": "FF8FC8",
           "15_invpyramid_2x4": "E0337F", "16_invpyramid_4x4": "8A0F4A"}
PLATE = "3C4148"


def roof(cx, cz, E, k):
    def inside(p):
        m = max(abs(p[0] - cx), abs(p[2] - cz))
        return m <= E and 0 <= p[1] + 0.5 <= (E - m) / k
    return inside


def funnel(cx, cz, E):
    def inside(p):
        m = max(abs(p[0] - cx), abs(p[2] - cz))
        return m <= E and 0 <= p[1] + 0.5 <= max(1.0, m + 0.5)
    return inside


def diamond(cx, cz, R):
    def inside(p):
        return p[1] >= -0.5 and abs(p[0] - cx) + abs(p[1]) + abs(p[2] - cz) <= R
    return inside


def octa(cx, cz, R, a, c):
    """Diamond with faces falling 1 block per `a` along x and per `c` along z."""
    def inside(p):
        return p[1] >= -0.5 and abs(p[0] - cx) / a + p[1] + 0.5 + abs(p[2] - cz) / c <= R
    return inside


SETS = {
    # two columns so each fits the starter workbench (about +-13 x +-28 voxels)
    "hull test calibration": [roof(-6, -16, 4.5, 1), funnel(-6, -4, 4.5), roof(-6, 8, 4.5, 2),
                              roof(6, -13, 6.5, 4), diamond(6, 4, 4.5)],
    "hull test calibration corners": [octa(-6, -19, 1.75, 4, 4), octa(-6, -4, 2.5, 2, 2),
                                      octa(-6, 10, 3.5, 1, 2), octa(6, -15, 3.0, 1, 4),
                                      octa(6, 7, 2.0, 2, 4)],
}


def build(shapes):
    def raised(p):
        return any(s(p) for s in shapes)

    above = {(x, y, z) for x in range(-13, 14) for y in range(0, 8) for z in range(-28, 29)
             if raised((x, y, z))}
    xs, zs = [p[0] for p in above], [p[2] for p in above]
    x0, x1, z0, z1 = min(xs) - 1, max(xs) + 1, min(zs) - 1, max(zs) + 1

    def inside(p):    # the plate joining everything is part of the shape
        return raised(p) or (-1.5 <= p[1] <= -0.5 and x0 - 0.5 <= p[0] <= x1 + 0.5
                             and z0 - 0.5 <= p[2] <= z1 + 0.5)

    plate = {(x, -1, z) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)}
    solid = above | plate
    plan = fit_pieces(solid, inside)
    placed, done = [], set()
    for v in sorted(solid | set(plan), key=lambda p: (p[2], p[1], p[0])):
        if v in done:
            continue
        if v in plan:
            piece, origin, Q, _ = plan[v]
            placed.append(Placed(piece, origin, Q, COLOURS[piece.d]))
            done.update(add(origin, apply(Q, f)) for f in piece.footprint)
        else:
            placed.append(Placed(BLOCK, v, color=PLATE if v in plate else COLOURS["01_block"]))
            done.add(v)
    return centre(placed)


if __name__ == "__main__":
    args = sys.argv[1:]
    preview = args[args.index("--preview") + 1] if "--preview" in args else None
    for name, shapes in SETS.items():
        placed = build(shapes)
        path = os.path.join(vehicles_dir(), f"{name}.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(to_xml(placed))
        counts = {}
        for p in placed:
            counts[p.piece.d] = counts.get(p.piece.d, 0) + 1
        print(f"wrote {path}: {counts}")
        if preview:
            with open(f"{preview}_{name.replace(' ', '_')}.png", "wb") as f:
                f.write(render_png(placed, title=name))
