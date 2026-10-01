"""Write in-game tests of the piece orientations the smoother can use.

Each test is one slope piece (white) nested in a small bracket of coloured blocks placed
against the faces the model says are solid. Correct: the piece reads as a clean ramp or a
chamfered corner flush with its bracket. Wrong: it sticks out, floats, or leaves a hole.

The black marker pillar at the start of a row is N blocks tall for row N.

"hull test orientations" (every orientation of the first five pieces):
  1 Wedge (all 12)   2 Pyramid (all 8)   3 Inverse Pyramid (all 8)
  4 Wedge 1x2 (6)    5 Wedge 1x4 (6)
"hull test orientations 2" (six orientations of each larger corner piece):
  1 Pyramid 1x2   2 Inverse Pyramid 1x2   3 Pyramid 1x4   4 Inverse Pyramid 1x4
  5 Pyramid 2x2   6 Inverse Pyramid 2x2   7 Pyramid 2x4   8 Inverse Pyramid 2x4
  9 Pyramid 4x4  10 Inverse Pyramid 4x4
Within a row the bracket colours run: red, orange, yellow, lime, green, teal, cyan, blue,
indigo, purple, pink, brown (starting next to the marker pillar).

    uv run tools/orientation_test.py [--preview out_prefix]
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from swhull.pieces import (BLOCK, CONTAINS, INVPYRAMID, INVPYRAMID2, INVPYRAMID2X2,  # noqa: E402
                           INVPYRAMID2X4, INVPYRAMID4, INVPYRAMID4X4, PYRAMID, PYRAMID2,
                           PYRAMID2X2, PYRAMID2X4, PYRAMID4, PYRAMID4X4, WEDGE, WEDGE2, WEDGE4,
                           Placed, _det, add, apply, r_attr, sub)
from swhull.render import render_png  # noqa: E402
from swhull.smooth import _placements  # noqa: E402
from swhull.vehicle import centre, to_xml, vehicles_dir  # noqa: E402

PALETTE = [("red", "E53935"), ("orange", "FB8C00"), ("yellow", "FDD835"), ("lime", "7CB342"),
           ("green", "2E7D32"), ("teal", "00897B"), ("cyan", "00ACC1"), ("blue", "1E88E5"),
           ("indigo", "3949AB"), ("purple", "8E24AA"), ("pink", "D81B60"), ("brown", "6D4C41")]
CORNER = [(1, 0, 0), (0, -1, 0), (0, 0, 1), (1, -1, 0), (1, 0, 1), (0, -1, 1), (1, -1, 1)]
RAMPS = (WEDGE, WEDGE2, WEDGE4)


def context(piece):
    """Local cells that should sit flush against the piece's solid side."""
    if piece in (PYRAMID, INVPYRAMID):
        return CORNER
    n = len(piece.footprint)
    if piece in RAMPS:
        cells = [(0, -1, -k) for k in range(n)]      # floor under the ramp
        return cells + [(0, 0, 1), (0, -1, 1)]       # wall behind the tall end
    # larger corner pieces: a block against every face the piece touches on its solid sides
    # (+x, -y, +z), plus the edge and corner blocks that close the bracket
    test, foot = CONTAINS[piece.d], set(piece.footprint)
    cells = set()
    for f in foot:
        for d in ((1, 0, 0), (0, -1, 0), (0, 0, 1)):
            n_ = add(f, d)
            centre = tuple(f[i] + 0.49 * d[i] for i in range(3))
            if n_ not in foot and test(centre):
                cells.add(n_)
    closed = set(cells)
    for c in cells:
        for d in ((1, 0, 0), (0, -1, 0), (0, 0, 1)):
            n_ = add(c, d)
            if n_ not in foot and any(add(n_, e) in cells for e in ((-1, 0, 0), (0, 1, 0), (0, 0, -1))):
                closed.add(n_)
    return sorted(closed)


def extra_width(piece):
    """Ramps are shown two wide along their triangle axis so the profile is easy to see."""
    return [(0, 0, 0), (1, 0, 0)] if piece in RAMPS else [(0, 0, 0)]


def pick(piece, limit=None):
    # rotations only: mirrored 2x4 pieces (`t`) were checked from a save made in game
    rots = [Q for Q, _ in _placements(piece) if _det(Q) > 0]
    if limit is None:
        return rots
    up = [Q for Q in rots if apply(Q, (0, 1, 0)) == (0, 1, 0)]          # on the floor
    wall = [Q for Q in rots if apply(Q, (0, 1, 0)) == (1, 0, 0)][:1]     # on a wall
    ceiling = [Q for Q in rots if apply(Q, (0, 1, 0)) == (0, -1, 0)][:1]  # hanging
    return (up + wall + ceiling)[:limit]


SETS = {
    "hull test orientations": [(WEDGE, None, 3), (PYRAMID, None, 3), (INVPYRAMID, None, 3),
                               (WEDGE2, 6, 4), (WEDGE4, 6, 6)],
    "hull test orientations 2": [(PYRAMID2, 6, 4), (INVPYRAMID2, 6, 4), (PYRAMID4, 6, 6),
                                 (INVPYRAMID4, 6, 6), (PYRAMID2X2, 6, 4), (INVPYRAMID2X2, 6, 4),
                                 (PYRAMID2X4, 6, 6), (INVPYRAMID2X4, 6, 6), (PYRAMID4X4, 6, 6),
                                 (INVPYRAMID4X4, 6, 6)],
}


def build(rows):
    placed, legend, x0 = [], [], 0
    for row, (piece, limit, size) in enumerate(rows, start=1):
        for k in range(row):                                   # marker pillar
            placed.append(Placed(BLOCK, (x0, k, -3), color="111111"))
        for col, Q in enumerate(pick(piece, limit)):
            name, colour = PALETTE[col]
            parts = []
            for w in extra_width(piece):
                parts.append((piece, w, Q, "F0F0F0"))
                for c in context(piece):
                    parts.append((BLOCK, add(w, c), None, colour))
            cells = []
            for p, offs, _, _ in parts:
                foot = p.footprint if p is piece else [(0, 0, 0)]
                cells += [apply(Q, add(offs, f)) for f in foot]
            lo = [min(c[i] for c in cells) for i in range(3)]
            base = (x0, 0, col * (size + 1))
            for p, offs, _, colour_ in parts:
                origin = add(sub(apply(Q, offs), tuple(lo)), base)
                if p is piece:
                    placed.append(Placed(p, origin, Q, colour_))
                else:
                    placed.append(Placed(BLOCK, origin, color=colour_))
            legend.append({"row": row, "piece": piece.d, "colour": name, "r": r_attr(Q)})
        x0 += size + 1
    occupied = {v for p in placed for v in p.voxels()}
    xs = [v[0] for v in occupied]
    zs = [v[2] for v in occupied]
    for x in range(min(xs), max(xs) + 1):
        for z in range(min(zs), max(zs) + 1):
            if (x, -1, z) not in occupied:
                placed.append(Placed(BLOCK, (x, -1, z), color="3C4148"))
    return centre(placed), legend


if __name__ == "__main__":
    args = sys.argv[1:]
    preview = args[args.index("--preview") + 1] if "--preview" in args else None
    legends = {}
    for name, rows in SETS.items():
        placed, legend = build(rows)
        seen = set()
        for p in placed:
            for v in p.voxels():
                assert v not in seen, f"overlap at {v}"
                seen.add(v)
        path = os.path.join(vehicles_dir(), f"{name}.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(to_xml(placed))
        legends[name] = legend
        lo = [min(v[i] for v in seen) for i in range(3)]
        hi = [max(v[i] for v in seen) for i in range(3)]
        print(f"wrote {path}: {len(legend)} tests, extent {lo} .. {hi}")
        if preview:
            with open(f"{preview}_{name.replace(' ', '_')}.png", "wb") as f:
                f.write(render_png(placed, title=name))
    with open(os.path.join(os.path.dirname(__file__), "orientation_legend.json"), "w") as f:
        json.dump(legends, f, indent=1)
