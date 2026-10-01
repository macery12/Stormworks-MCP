"""Workbench sizes: keyword ladder, fit checks, and the edit areas found in the game install.

Sizes are W x H x L in metres (vehicle x, y, z), end to end. A vehicle loads centred in the
edit area. The starter bench (7.5 x 7.5 x 15 m) was measured in game to reach about 2 blocks
less than half its size from the centre on each axis, so every fit check keeps that margin.

The keywords assume Echo's Bigger Workbenches (workshop 3357835209) is active: each one is an
envelope that real edit areas contain, and each contains the one before it. The mod caps edit
areas at 128 m; wherever a keyword reaches that cap it uses 120 m instead, leaving 4 m
(16 blocks) free on each side for parts that hang off the edge. MAX is the 128 m cube.
"""
import glob
import os
import re
from functools import cache

from .definitions import _steam_libraries, definitions_dir
from .hull import VOX

SIZES = {
    "S": (7.5, 7.5, 15.0),        # starter-bench size
    "M": (20.5, 20.5, 23.5),      # mod workbenches and small hangars
    "L": (22.5, 20.5, 120.0),     # mod submarine dock; every larger dock
    "XL": (40.0, 120.0, 120.0),   # mod space hangars
    "XXL": (75.0, 120.0, 120.0),  # mod multiplayer docks
    "MAX": (120.0, 120.0, 120.0),  # mod 128 m cube
}
MARGIN = 2                         # blocks short of half the size, per side (measured)
_SKIP_TILES = ("buoyancy_test", "test_tile")   # developer tiles players cannot reach
_EDIT = re.compile(r"<edit_area ([^>]*)>.*?<size ([^/]*)/>", re.S)


def parse_bench(value):
    """`bench` from a spec -> (label, (w, h, l)), or None when unset."""
    if value is None:
        return None
    if isinstance(value, str):
        key = value.strip().upper()
        if key not in SIZES:
            raise ValueError(f"bench must be one of {', '.join(SIZES)} or [width, height, length] "
                             f"in metres (got {value!r})")
        return key, SIZES[key]
    if (isinstance(value, (list, tuple)) and len(value) == 3
            and all(isinstance(v, (int, float)) and v > 0 for v in value)):
        w, h, length = (float(v) for v in value)
        return f"custom {w:g} x {h:g} x {length:g} m", (w, h, length)
    raise ValueError(f"bench must be one of {', '.join(SIZES)} or [width, height, length] in metres")


def reach(size):
    """Blocks from the centre a vehicle may extend on each axis."""
    return tuple(s * VOX / 2 - MARGIN for s in size)


def overflow(size, lo, hi):
    """Metres the vehicle sticks out of a bench, per axis (x, y, z); 0 where it fits."""
    r = reach(size)
    return tuple(max(0.0, max(abs(lo[i]), abs(hi[i])) - r[i]) / VOX for i in range(3))


def fits(size, lo, hi):
    return not any(overflow(size, lo, hi))


def fit_lines(bench, lo, hi):
    """Summary lines: the target bench (or a prompt to ask for one) and every size that fits."""
    ok = [k for k, s in SIZES.items() if fits(s, lo, hi)]
    lines = []
    target = parse_bench(bench)
    if target is None:
        lines.append("! No target bench set. Ask the player which bench size to build for ("
                     + ", ".join(SIZES) + "; list_workbenches shows sizes and where each is), "
                     "then set `bench` in the spec.")
    else:
        label, size = target
        over = overflow(size, lo, hi)
        dims = f"{size[0]:g} W x {size[1]:g} H x {size[2]:g} L m"
        if not any(over):
            lines.append(f"Fits bench {label} ({dims}).")
        else:
            parts = [f"{name} by {o:.2f} m" for name, o in zip(("too wide", "too tall", "too long"), over) if o]
            lines.append(f"! Does NOT fit bench {label} ({dims}): {', '.join(parts)}.")
    lines.append("Fits bench sizes: " + (", ".join(ok) if ok else "none, it is larger than MAX"))
    return lines


def _read_tiles(folder):
    out = {}
    for path in glob.glob(os.path.join(folder, "*.xml")):
        tile = os.path.basename(path)[:-4]
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for m in _EDIT.finditer(text):
            attrs = m.group(1)
            if 'is_static="true"' in attrs:
                continue
            ident = re.search(r'\bid="([^"]*)"', attrs)
            dims = dict(re.findall(r'\b([xyz])="(-?[\d.]+)"', m.group(2)))
            if ident:
                out[(tile, ident.group(1))] = tuple(float(dims.get(k, 0)) for k in "xyz")
    return out


def _mod_tile_dirs():
    """Workshop mods for Stormworks that replace tile files: [(mod name, tiles folder)]."""
    out, seen = [], set()
    for lib in _steam_libraries():
        for tiles in sorted(glob.glob(os.path.join(lib, "steamapps", "workshop", "content", "573090",
                                                   "*", "data", "tiles"))):
            key = os.path.normcase(os.path.realpath(tiles))   # one library can be listed twice
            if key in seen:
                continue
            seen.add(key)
            name = os.path.basename(os.path.dirname(os.path.dirname(tiles)))
            try:
                with open(os.path.join(os.path.dirname(os.path.dirname(tiles)), "mod.xml"),
                          encoding="utf-8", errors="replace") as f:
                    m = re.search(r'\bname="([^"]*)"', f.read())
                    name = m.group(1) if m else name
            except OSError:
                pass
            out.append((name, tiles))
    return out


@cache
def edit_areas():
    """({(tile, id): (w, h, l)}, [mod names applied]) from the game install plus tile mods."""
    defs = definitions_dir()
    areas = {}
    if defs:
        areas = _read_tiles(os.path.join(os.path.dirname(defs), "tiles"))
    mods = []
    for name, folder in _mod_tile_dirs():
        modded = _read_tiles(folder)
        if not modded:
            continue
        tiles = {t for t, _ in modded}
        areas = {k: v for k, v in areas.items() if k[0] not in tiles}
        areas.update(modded)
        mods.append(name)
    areas = {k: v for k, v in areas.items() if not k[0].startswith(_SKIP_TILES)}
    return areas, mods


def describe():
    """Text for list_workbenches."""
    areas, mods = edit_areas()
    lines = ["Bench sizes (W x H x L metres, end to end; a vehicle loads centred and may reach "
             f"{MARGIN} blocks short of each edge):"]
    for key, size in SIZES.items():
        where = sorted(f"{t}:{i}" for (t, i), s in areas.items()
                       if all(s[k] + 1e-6 >= size[k] for k in range(3)))
        dims = f"{size[0]:g} x {size[1]:g} x {size[2]:g}"
        if 120.0 in size:
            dims += " (120 = the mod's 128 m cap less 4 m each side)"
        place = (f"{len(where)} edit areas, e.g. {', '.join(where[:4])}" if where
                 else "no edit area this large was found")
        lines.append(f"- {key}: {dims}; {place}")
    if mods:
        lines.append("Tile mods applied: " + ", ".join(mods))
    elif areas:
        lines.append("No workbench mod found: sizes above M need Echo's Bigger Workbenches.")
    else:
        lines.append("Game files not found, so locations are unknown (set SW_GAME_DIR).")
    lines.append("Locations are tile file : edit area id from the game data. A spec can also use "
                 "`bench: [width, height, length]` for any other size.")
    return "\n".join(lines)
