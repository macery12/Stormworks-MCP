"""Read and write Stormworks vehicle XML (data_version 3).

The game writes attribute names such as `00="1"`, which is not valid XML, so this module
works on the text with regular expressions instead of an XML parser.
"""
import os
import re

from . import definitions
from .pieces import BLOCK, BY_NAME, Piece, Placed, parse_r, r_attr, split_mirror, sub, with_mirror

DEFAULT_COLOR = "C2C3C7"
# Seen in game (USS Iowa V2, 184k parts): on spawn the vehicle was cut straight across where
# component number 2**17 sits in the file, and everything after it was missing. Not documented
# by the game; tools/component_limit_test.py checks it.
SPAWN_LIMIT = 131072
# A component with no `r` attribute is NOT unrotated. Measured from saved vehicles: its
# footprint extends along +y, matching this rotation. We always write `r` explicitly.
MISSING_R = parse_r("0,0,1,-1,0,0,0,-1,0")


def vehicles_dir():
    override = os.environ.get("SW_VEHICLES_DIR")
    if override:
        return override
    return os.path.join(os.environ.get("APPDATA", ""), "Stormworks", "data", "vehicles")


def centre(placed):
    """Shift pieces so the bounding box centre sits on the workbench origin."""
    vox = [v for p in placed for v in p.voxels()]
    lo = [min(v[i] for v in vox) for i in range(3)]
    hi = [max(v[i] for v in vox) for i in range(3)]
    c = tuple((lo[i] + hi[i]) // 2 for i in range(3))
    for p in placed:
        p.origin = sub(p.origin, c)
    return placed


def _vp(v):
    attrs = "".join(f' {k}="{val}"' for k, val in zip("xyz", v) if val)
    return f"<vp{attrs}/>"


def to_xml(placed):
    parts = []
    for p in placed:
        d = "" if p.piece.d == "01_block" else f' d="{p.piece.d}"'
        rot, flip = split_mirror(p.Q)
        if flip:
            d += f' t="{flip}"'
        r = f' r="{r_attr(rot)}"'
        n = p.piece.surfaces
        # every surface needs its colour: `x` in `sc` means "unpainted", not "same as before"
        sc = f"{n}" + f",{p.color.upper()}" * n
        parts.append(f'<c{d}><o{r} sc="{sc}">{_vp(p.origin)}</o></c>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<vehicle data_version="3" bodies_id="1"><authors/><bodies><body unique_id="1">'
            '<components>' + "".join(parts) + '</components></body></bodies>'
            '<logic_node_links/></vehicle>\n')


_COMP = re.compile(r'<c\b([^>]*)>\s*<o\b([^>]*?)(/?)>(?:\s*<vp\b([^>]*?)/>)?')


def read_components(path):
    """Yield (definition, origin, Q, colour) for every component in every body. A part placed
    in mirror mode (`t`) comes back with an improper Q (see pieces.with_mirror)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    for m in _COMP.finditer(text):
        dm = re.search(r'\bd="([^"]*)"', m.group(1))
        d = dm.group(1) if dm else "01_block"
        o_attrs = m.group(2)
        vp = "" if m.group(3) else (m.group(4) or "")
        a = dict(re.findall(r'\b([xyz])="(-?\d+)"', vp))
        origin = (int(a.get("x", 0)), int(a.get("y", 0)), int(a.get("z", 0)))
        rm = re.search(r'\br="([^"]*)"', o_attrs)
        Q = parse_r(rm.group(1)) if rm else MISSING_R
        tm = re.search(r'\bt="(\d+)"', m.group(1))
        if tm:
            Q = with_mirror(Q, int(tm.group(1)))
        colour = DEFAULT_COLOR
        scm = re.search(r'\bsc="\d+,([0-9A-Fa-f]{6})', o_attrs)
        bcm = re.search(r'\bbc="([0-9A-Fa-f]{6})', o_attrs)
        if scm:
            colour = scm.group(1)
        elif bcm:
            colour = bcm.group(1)
        yield d, origin, Q, colour


def load_placed(path):
    """Existing vehicle as Placed pieces. Parts without slope geometry use their definition
    footprint when the game is installed, else a single cube (counted in `other`)."""
    out, other = [], {}
    for d, origin, Q, colour in read_components(path):
        piece = BY_NAME.get(d) or definitions.load(d)
        if piece is None:
            other[d] = other.get(d, 0) + 1
            piece = Piece(d, BLOCK.surfaces, 0.0, BLOCK.footprint, BLOCK.verts, BLOCK.faces)
        out.append(Placed(piece, origin, Q, colour))
    return out, other
