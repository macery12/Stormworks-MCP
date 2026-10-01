"""Read Stormworks part definitions (rom/data/definitions/*.xml) for footprints and paint slots.

Only what placement and previews need: the voxel footprint, surface count, mass and display
name. Parts are drawn as a union of cubes over their footprint.
"""
import os
import re
import sys
from functools import cache

from .pieces import Piece

# placeholder engines by size; the prebuilt engine parts in the game
ENGINES = {"small": "engine", "medium": "aircraft_engine", "large": "engine_diesel"}
_REL = os.path.join("rom", "data", "definitions")


def _steam_roots():
    roots = []
    if sys.platform == "win32":
        try:
            import winreg  # noqa: PLC0415 - Windows-only module
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                roots.append(winreg.QueryValueEx(key, "SteamPath")[0])
        except OSError:
            pass
        roots += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    else:
        home = os.path.expanduser("~")
        roots += [os.path.join(home, ".steam", "steam"), os.path.join(home, ".local", "share", "Steam"),
                  os.path.join(home, "Library", "Application Support", "Steam")]
    return roots


def _steam_libraries():
    """Every Steam library folder listed in libraryfolders.vdf."""
    libs = []
    for root in _steam_roots():
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        libs.append(root)
        try:
            with open(vdf, encoding="utf-8", errors="replace") as f:
                libs += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', f.read())]
        except OSError:
            pass
    return list(dict.fromkeys(os.path.normpath(p) for p in libs))


@cache
def definitions_dir():
    """Stormworks part definitions: SW_DEFINITIONS_DIR, then SW_GAME_DIR, then Steam libraries.

    Returns None when the game cannot be found; engine placeholders are then unavailable.
    """
    if os.environ.get("SW_DEFINITIONS_DIR"):
        path = os.environ["SW_DEFINITIONS_DIR"]
        return path if os.path.isdir(path) else None
    if os.environ.get("SW_GAME_DIR"):
        path = os.path.join(os.environ["SW_GAME_DIR"], _REL)
        return path if os.path.isdir(path) else None
    for lib in _steam_libraries():
        path = os.path.join(lib, "steamapps", "common", "Stormworks", _REL)
        if os.path.isdir(path):
            return path
    return None


def _cube_union(voxels):
    verts, faces = [], []
    for (x, y, z) in voxels:
        base = len(verts)
        verts += [(x + dx, y + dy, z + dz) for dx in (-.5, .5) for dy in (-.5, .5) for dz in (-.5, .5)]
        # corner index = 4*ix + 2*iy + iz
        faces += [tuple(base + i for i in q) for q in (
            (4, 6, 7, 5), (0, 1, 3, 2), (2, 3, 7, 6), (0, 4, 5, 1), (1, 5, 7, 3), (0, 2, 6, 4))]
    return tuple(verts), tuple(faces)


@cache
def load(d):
    """Piece for definition `d`, or None when the file is not available."""
    base = definitions_dir()
    if base is None or not re.fullmatch(r"[\w.-]+", d):
        return None
    path = os.path.join(base, f"{d}.xml")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    head = text.split("<buoyancy_surfaces", 1)[0]
    surfaces = len(re.findall(r"<surface\b", head.split("<surfaces", 1)[-1])) if "<surfaces" in head else 0
    block = re.search(r"<voxels>(.*?)</voxels>", text, re.S)
    voxels = []
    if block:
        for m in re.finditer(r"<voxel\b[^>]*>\s*<position\s+([^/]*)/>", block.group(1)):
            a = dict(re.findall(r'\b([xyz])="(-?\d+)"', m.group(1)))
            voxels.append((int(a.get("x", 0)), int(a.get("y", 0)), int(a.get("z", 0))))
    voxels = voxels or [(0, 0, 0)]
    mass = float((re.search(r'\bmass="([^"]*)"', text) or [None, "0"])[1])
    verts, faces = _cube_union(voxels)
    return Piece(d, max(1, surfaces), mass, tuple(voxels), verts, faces)


def display_name(d):
    base = definitions_dir()
    if base is None:
        return d
    path = os.path.join(base, f"{d}.xml")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            m = re.search(r'<definition\s+name="([^"]*)"', f.read(2000))
        return m.group(1) if m else d
    except OSError:
        return d
