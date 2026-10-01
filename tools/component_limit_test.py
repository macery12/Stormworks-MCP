"""Write an in-game test of how many components the game spawns.

A flat plate 36 m wide, 0.5 m thick and 117.5 m long: 135,360 blocks written in the same order
as a hull (stern to bow). Components come in bands of 8,192 that alternate light and dark grey;
everything after component 131,072 (2**17, `vehicle.SPAWN_LIMIT`) is red, a 3.7 m strip at the
bow end.

In game, load it at a bench of size XL or larger (Echo's Bigger Workbenches) and spawn it:
- red strip still there after spawn: no limit at 131,072;
- red strip gone, grey whole: the limit is exactly 131,072;
- cut somewhere else: count the grey bands that survive (8,192 components each).

    uv run tools/component_limit_test.py [vehicle name]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from swhull.pieces import BLOCK, Placed  # noqa: E402
from swhull.vehicle import SPAWN_LIMIT, centre, to_xml, vehicles_dir  # noqa: E402

WIDTH, THICK, LENGTH = 144, 2, 470      # blocks: 36 m x 0.5 m x 117.5 m
BAND = 8192
COLOURS = ("B0B4BA", "5C6066")
RED = "E53935"


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "hull test component limit"
    placed = []
    for z in range(LENGTH):
        for y in range(THICK):
            for x in range(WIDTH):
                i = len(placed)
                colour = RED if i >= SPAWN_LIMIT else COLOURS[(i // BAND) % 2]
                placed.append(Placed(BLOCK, (x, y, z), color=colour))
    centre(placed)
    path = os.path.join(vehicles_dir(), f"{name}.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_xml(placed))
    red = len(placed) - SPAWN_LIMIT
    print(f"Wrote {len(placed)} blocks to {path}\n"
          f"{SPAWN_LIMIT // BAND} grey bands of {BAND}, then {red} red blocks "
          f"({red / (WIDTH * THICK) / 4:.1f} m at the far end).")


if __name__ == "__main__":
    main()
