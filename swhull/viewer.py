"""Runtime geometry payload for the interactive viewer, using the same meshes as PNGs."""
import copy

from .meshes import coverage, world_triangles
from .pieces import IDENTITY, r_attr, split_mirror
from .vehicle import placed_from_text


def geometry(text, body_id=None):
    parts, _ = placed_from_text(text, body_id)
    if not parts:
        raise ValueError("vehicle has no components to view")
    assets, rows = {}, []
    for p in parts:
        d = p.piece.d
        if d not in assets:
            local = copy.copy(p)
            local.origin, local.Q, local.color = (0, 0, 0), IDENTITY, "FF7D00"
            native = world_triangles(local)
            # Geometry is stored per definition, not duplicated for every instance.
            assets[d] = ({"triangles": [[[[round(c, 6) for c in v] for v in pts], list(rgb)]
                                         for pts, rgb in native], "native": True} if native is not None else
                         {"faces": [[list(p.piece.verts[i]) for i in f] for f in p.piece.faces], "native": False})
        rot, flip = split_mirror(p.Q)
        # The browser transform uses the complete Q, including any mirror/scaling.
        rows.append({"d": d, "origin": list(p.origin), "M": [p.Q[i][j] for j in range(3) for i in range(3)],
                     "colour": p.color, "r": r_attr(rot), "mirror": flip})
    return {"parts": rows, "assets": assets, "coverage": coverage(parts),
            "frame": "one body-local frame; articulated transforms are not solved"}
