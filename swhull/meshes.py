"""Read installed component meshes for previews; never use them as placement geometry.

Version-7 meshes store metre positions, RGBA colours and normals in 28-byte vertices,
followed by 16-bit triangle indices. Only the installed player's assets are read.
"""
import math
import struct
from collections import Counter
from functools import lru_cache
from pathlib import Path

from . import definitions
from .land import road_wheel
from .pieces import BY_NAME, _det, add, apply
from .seal import MANUAL_DOORS


def decode(data):
    """Return triangles of (position, colour, normal), rejecting incomplete/unknown formats."""
    if len(data) < 18 or data[:8] != b"mesh\x07\x00\x01\x00":
        raise ValueError("unsupported component mesh format")
    count, layout = struct.unpack_from("<HI", data, 8)
    end = 14 + count * 28
    if not count or layout != 19 or len(data) < end + 4:
        raise ValueError("invalid component mesh vertices")
    vertices = tuple(struct.iter_unpack("<3f4B3f", data[14:end]))
    if any(not all(math.isfinite(n) for n in (*v[:3], *v[7:])) for v in vertices):
        raise ValueError("nonfinite component mesh vertex")
    indices_count, = struct.unpack_from("<I", data, end)
    if not indices_count or indices_count % 3 or len(data) < end + 4 + indices_count * 2:
        raise ValueError("invalid component mesh indices")
    indices = struct.unpack_from(f"<{indices_count}H", data, end + 4)
    if max(indices) >= count:
        raise ValueError("component mesh index outside vertex array")
    return tuple(tuple((vertices[j][:3], vertices[j][3:7], vertices[j][7:])
                       for j in indices[i:i + 3]) for i in range(0, indices_count, 3))


@lru_cache(maxsize=256)
def _read(base, relative):
    root = Path(base).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path.suffix != ".mesh":
        return None
    try:
        return decode(path.read_bytes())
    except (OSError, ValueError):
        return None


def _assets(p):
    data = definitions.metadata(p.piece.d) or {}
    props = data.get("properties", {})
    base = definitions.definitions_dir()
    if not base or not props.get("mesh_data_name"):
        return []
    root = str(Path(base).parents[1])
    assets = [(props["mesh_data_name"], (0, 0, 0))]
    if road_wheel(p.piece.d) and props.get("mesh_0_name"):
        # The tyre is a separate dynamic mesh. Render its neutral editor position,
        # not a simulation of steering, suspension compression or customised tyre sizes.
        centre = float(props.get("wheel_suspension_height", ".25")) if p.piece.d.endswith("_sus") else .25
        assets.append((props["mesh_0_name"] + "_l.mesh", (0, centre, 0)))
    elif p.piece.d.startswith(("searchlight", "small_light")) or p.piece.d in MANUAL_DOORS:
        assets.extend((props[key], (0, 0, 0)) for key in ("mesh_0_name", "mesh_1_name")
                      if props.get(key, "").endswith(".mesh"))
    if p.piece.d in MANUAL_DOORS and "slide" in props.get("mesh_data_name", "") and len(assets) > 1:
        moving = [v["position"] for v in data["voxels"] if v["flags"] & 4]
        side = data["directions"].get("door_side", (0, 0, 1))
        centre = sum(sum(v[i] * side[i] for i in range(3)) for v in moving) / len(moving) / 4 if moving else 0
        assets[1] = (assets[1][0], tuple(centre * n for n in side))
    loaded = [(mesh, offset) for name, offset in assets if (mesh := _read(root, name)) is not None]
    if (not loaded or _read(root, assets[0][0]) is None
            or road_wheel(p.piece.d) and len(loaded) < len(assets)
            or p.piece.d in MANUAL_DOORS and (not props.get("mesh_0_name") or _read(root, props["mesh_0_name"]) is None)):
        return []
    return loaded


def _door_pose(p, point, normal, door_state):
    if door_state == "closed":
        return point, normal
    data = definitions.metadata(p.piece.d)
    props, directions = data["properties"], data["directions"]
    if "slide" in props.get("mesh_data_name", ""):
        side = directions.get("door_side", (1, 0, 0))
        distance = (float(props.get("door_side_dist", "2")) + 1) / 4
        return add(point, tuple(-v * distance for v in side)), normal
    axis = directions.get("door_side", (1, 0, 0))
    up = directions.get("door_up", (0, 1, 0))
    moving = [v["position"] for v in data["voxels"] if v["flags"] & 4]
    edge = (max(sum(v[i] * up[i] for i in range(3)) for v in moving) + .5) / 4
    pivot = tuple(v * edge for v in up)

    def rotate(v):
        cross = (axis[1]*v[2]-axis[2]*v[1], axis[2]*v[0]-axis[0]*v[2], axis[0]*v[1]-axis[1]*v[0])
        along = sum(v[i] * axis[i] for i in range(3))
        return tuple(cross[i] + axis[i] * along for i in range(3))

    return add(pivot, rotate(tuple(point[i] - pivot[i] for i in range(3)))), rotate(normal)


def triangles(p, door_state="closed"):
    """Native local triangles in block units with approximate material/paint colours."""
    if p.piece.d in BY_NAME:
        return None
    assets = _assets(p)
    if not assets:
        return None
    paint = tuple(int(p.color[i:i + 2], 16) for i in (0, 2, 4))
    out = []
    if door_state not in ("closed", "open"):
        raise ValueError("door_state must be closed or open")
    for index, (mesh, offset) in enumerate(assets):
        for source_tri in mesh:
            tri = source_tri
            if p.piece.d in MANUAL_DOORS and index == 1:
                tri = tuple((point, c, normal) for v, c, n in tri
                            for point, normal in [_door_pose(p, v, n, door_state)])
            points = tuple(tuple((v[i] + offset[i]) * 4 for i in range(3)) for v, _, _ in tri)
            rgb = tuple(round(sum(c[i] for _, c, _ in tri) / 3) for i in range(3))
            # Installed meshes mark paintable material in orange. Keep fixed rubber,
            # metal and upholstery colours; painting the footprint must not paint a tyre.
            if rgb in ((255, 125, 0), (55, 125, 0)):
                rgb = paint
            if p.piece.d == "small_light" and offset == (0, 0, 0) and rgb[0] > 200 and rgb[1] > 200:
                rgb = paint
            normal = tuple(sum(n[i] for _, _, n in tri) for i in range(3))
            out.append((points, normal, rgb))
    return out


def world_triangles(p, door_state="closed"):
    local = triangles(p, door_state)
    if local is None:
        return None
    # Derive transformed normals from the actual triangle, with source normals to
    # choose the outward side. This also handles mirrored or XML-scaled read-only previews.
    out = []
    for pts, normal, rgb in local:
        a, b, c = pts
        u, v = tuple(b[i] - a[i] for i in range(3)), tuple(c[i] - a[i] for i in range(3))
        cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
        ordered = tuple(reversed(pts)) if sum(cross[i] * normal[i] for i in range(3)) < 0 else pts
        world = tuple(add(p.origin, apply(p.Q, q)) for q in ordered)
        if _det(p.Q) < 0:
            world = tuple(reversed(world))
        out.append((world, rgb))
    return out


def coverage(parts):
    native, fallback = {}, {}
    counts = Counter(p.piece.d for p in parts)
    examples = {p.piece.d: p for p in parts if p.piece.d not in BY_NAME}
    for d, p in sorted(examples.items()):
        target = native if _assets(p) else fallback
        target[d] = counts[d]
    omitted = {}
    for d in examples:
        props = (definitions.metadata(d) or {}).get("properties", {})
        if d in MANUAL_DOORS and d in fallback:
            omitted[d] = "moving door panel unavailable; footprint fallback"
        elif props.get("mesh_0_name") and d not in MANUAL_DOORS and not road_wheel(d) and not d.startswith(("searchlight", "small_light", "seat")):
            omitted[d] = "additional moving geometry is not modeled"
    return {"native_components": native, "footprint_fallbacks": fallback, "omitted_moving_geometry": omitted,
            "note": "Installed meshes and closed manual-door panels; selected open poses are approximate. Wheels are neutral/default size. Not a game render."}
