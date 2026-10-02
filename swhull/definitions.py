"""Read Stormworks part definitions (rom/data/definitions/*.xml) for footprints and paint slots.

Footprints, surfaces, directional axes and connection nodes stay local to the installed game.
Parts are drawn as a union of cubes over their editor footprint.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET
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
    data = metadata(d)
    voxels = data["footprint"]
    if not all(float(v).is_integer() for cell in voxels for v in cell):
        raise ValueError(f"definition {d} has a non-grid voxel footprint")
    voxels = [tuple(int(v) for v in cell) for cell in voxels]
    surfaces, mass = len(data["attachment_surfaces"]), data["mass"]
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


@cache
def metadata(d):
    """Runtime catalogue data; game assets never leave the player's installation."""
    base = definitions_dir()
    if not isinstance(d, str) or not re.fullmatch(r"[\w.-]+", d):
        return None
    try:
        if base is None:
            raise FileNotFoundError
        with open(os.path.join(base, f"{d}.xml"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        from .pieces import BY_NAME, IDENTITY, DIRS  # noqa: PLC0415
        from .smooth import _full_faces  # noqa: PLC0415
        piece = BY_NAME.get(d)
        if piece:
            faces = [{"position": v, "orientation": DIRS.index(direction), "shape": 1, "trans_type": 0}
                     for v, direction in _full_faces(piece, IDENTITY)]
            return {"definition": d, "name": d, "mass": piece.mass, "description": "Built-in building geometry",
                    "footprint": list(piece.footprint), "voxels": [
                        {"position": v, "flags": 1, "physics_shape": None} for v in piece.footprint],
                    "attachment_surfaces": faces, "sealing_surfaces": faces, "properties": {},
                    "directions": {}, "logic_nodes": [], "couplings": [],
                    "settings": {"custom_name": {"type": "string"}},
                    "source": "built-in geometry; exact slope meshes used by seal checker"}
        return None
    try:
        root = ET.fromstring(re.sub(r'(\s)(\d\w*)=', r'\1sw_\2=', text))
    except ET.ParseError as exc:
        raise ValueError(f"cannot read definition {d}: {exc}") from exc

    def position(node):
        values = [float(node.get(a, "0")) for a in "xyz"] if node is not None else [0.0] * 3
        return tuple(int(v) if v.is_integer() else v for v in values)

    def surfaces(tag):
        return [{"position": position(s.find("position")), "orientation": int(s.get("orientation", "0")),
                 "shape": int(s.get("shape", "0")), "trans_type": int(s.get("trans_type", "0")),
                 "rotation": int(s.get("rotation", "0"))}
                for s in root.findall(f"{tag}/surface")]

    voxels = [{"position": position(v.find("position")), "flags": int(v.get("flags", "0")),
               "physics_shape": int(v.get("physics_shape", "0")),
               "buoy_pipes": int(v.get("buoy_pipes", "0"))} for v in root.findall("voxels/voxel")]
    tooltip = root.find("tooltip_properties")
    return {"definition": d, "name": root.get("name", d), "mass": float(root.get("mass", "0")),
            "description": tooltip.get("short_description", "") if tooltip is not None else "",
            "footprint": [v["position"] for v in voxels] or [(0, 0, 0)], "voxels": voxels,
            "attachment_surfaces": surfaces("surfaces"), "sealing_surfaces": surfaces("buoyancy_surfaces"),
            "properties": dict(root.attrib),
            "directions": {tag: position(root.find(tag)) for tag in (
                "force_dir", "seat_front", "seat_up", "door_normal", "door_side", "door_up",
                "dynamic_body_position", "dynamic_rotation_axes", "dynamic_side_axis",
                "connector_axis", "connector_up", "voxel_location_child")},
            "logic_nodes": [{"index": i, "label": n.get("label", ""),
                             "type": int(n.get("type", "0")), "mode": int(n.get("mode", "0")),
                             "description": n.get("description", ""), "position": position(n.find("position"))}
                            for i, n in enumerate(root.findall("logic_nodes/logic_node"))],
            "couplings": [{"attributes": dict(n.attrib), "position": position(n.find("position")),
                           "children": [{"tag": c.tag, "attributes": dict(c.attrib)} for c in n]}
                          for n in root.findall("couplings/*")],
            "settings": {"custom_name": {"type": "string"}, **({
                "fluid_type": {"type": "integer", "supported": {"water": 0, "diesel": 1, "jet_fuel": 2}},
                "fluid_fill": {"type": "number", "min": 0, "max": 1, "default": 1},
                "fluid_filter": {"type": "integer", "default": 4294967295}
            } if d == "water_spawner" else {})}}


def catalogue(search="", offset=0, limit=50):
    from .pieces import BY_NAME  # noqa: PLC0415
    if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("offset must be nonnegative and limit must be 1-200")
    base = definitions_dir()
    names = sorted(p[:-4] for p in os.listdir(base) if p.endswith(".xml")) if base else sorted(BY_NAME)
    rows = []
    for d in names:
        name = display_name(d)
        if search.lower() not in f"{d} {name}".lower():
            continue
        piece = BY_NAME.get(d) or load(d)
        if piece:
            size = [max(v[i] for v in piece.footprint) - min(v[i] for v in piece.footprint) + 1
                    for i in range(3)]
            rows.append({"definition": d, "name": name, "size_blocks": size,
                         "size_metres": [n / 4 for n in size], "mass": piece.mass})
    return {"parts": rows[offset:offset + limit], "total": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "definitions_available": base is not None}
