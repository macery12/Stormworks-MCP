"""Read and write Stormworks vehicle XML (data_version 3).

The game writes attribute names such as `00="1"`, which is not valid XML, so this module
works on the text with regular expressions instead of an XML parser.
"""
import os
import re
import math
from xml.sax.saxutils import quoteattr

from . import definitions
from .configuration import new_settings
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


def component_transform(p):
    from .land import road_wheel  # noqa: PLC0415
    # Match saved workshop road wheels: mirror the local axle (y), retaining
    # their drive/steering arrow frame. Imports keep their original raw XML.
    return split_mirror(p.Q, 2 if road_wheel(p.piece.d) else 1)


def _simple_xml(placed):
    parts = []
    for p in placed:
        d = "" if p.piece.d == "01_block" else f' d="{p.piece.d}"'
        rot, flip = component_transform(p)
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
    yield from components_from_text(text)


def components_from_text(text):
    """Geometry view only; use editing.VehicleDocument for lossless rewriting."""
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


def component_xml(p):
    """Write a new part, or retain an imported component byte for byte."""
    if p.raw_xml:
        return p.raw_xml
    xml = _simple_xml([p]).split("<components>", 1)[1].split("</components>", 1)[0]
    settings = new_settings(p.piece.d, p.settings)
    if p.name:
        settings.setdefault("custom_name", p.name)
    attrs = ""
    for key, value in settings.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_]\w*", key) or key in ("r", "sc"):
            raise ValueError(f"invalid component setting {key!r}")
        if not isinstance(value, (str, int, float, bool)):
            raise ValueError(f"component setting {key} must be a scalar")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"component setting {key} must be finite")
        attrs += f" {key}={quoteattr(str(value).lower() if isinstance(value, bool) else str(value))}"
    return xml.replace("><vp", attrs + "><vp", 1)


def to_xml(placed):
    return _simple_xml([]).replace("<components></components>",
                                  "<components>" + "".join(component_xml(p) for p in placed)
                                  + "</components>")


def load_placed(path, body_id=None):
    """Read one selected body (largest by default), with settings for native previews.
    Placement footprints remain definition cubes; missing definitions are counted in `other`.
    This display reader accepts finite scaled transforms, unlike the editing parser."""
    with open(path, encoding="utf-8-sig") as f:
        return placed_from_text(f.read(), body_id)


def placed_from_text(text, body_id=None):
    """One body's read-only display geometry; controller internals are never vehicle parts."""
    from .reference import xml_root  # noqa: PLC0415
    from .pieces import _det  # noqa: PLC0415
    bodies = xml_root(text).findall("bodies/body")
    if not bodies:
        raise ValueError("vehicle has no bodies")
    selected = ([b for b in bodies if b.get("unique_id") == body_id] if body_id is not None else
                [max(bodies, key=lambda b: len(b.findall("components/c")))])
    if not selected:
        raise ValueError(f"no body {body_id!r} in vehicle")
    out, other = [], {}
    for component in selected[0].findall("components/c"):
        o = component.find("o")
        if o is None:
            continue
        d = component.get("d", "01_block")
        vp = o.find("vp")
        origin = tuple(int(vp.get(a, "0")) for a in "xyz") if vp is not None else (0, 0, 0)
        if "r" not in o.attrib:
            Q = MISSING_R
        else:
            # Read-only display of modded meshes. Editing and placement keep the strict parser.
            try:
                v = [float(n) for n in o.get("r").split(",")]
                if len(v) != 9 or any(not math.isfinite(n) or abs(n) > 1000 for n in v):
                    raise ValueError
                Q = tuple(tuple(v[j * 3 + i] for j in range(3)) for i in range(3))
                if abs(_det(Q)) < 1e-9:
                    raise ValueError
            except ValueError as exc:
                raise ValueError("invalid transform in read-only vehicle preview") from exc
        flip = int(component.get("t", "0"))
        if not 0 <= flip <= 7:
            raise ValueError("mirror flags must be 0..7")
        Q = with_mirror(Q, flip)
        colours = o.get("sc", "").split(",")[1:]
        colour = next((c for c in colours if re.fullmatch(r"[0-9a-fA-F]{6}", c)), o.get("bc", DEFAULT_COLOR))
        if not re.fullmatch(r"[0-9a-fA-F]{6}", colour):
            colour = DEFAULT_COLOR
        piece = BY_NAME.get(d) or definitions.load(d)
        if piece is None:
            other[d] = other.get(d, 0) + 1
            piece = Piece(d, BLOCK.surfaces, 0.0, BLOCK.footprint, BLOCK.verts, BLOCK.faces)
        out.append(Placed(piece, origin, Q, colour, name=o.get("custom_name", ""),
                          settings={k: v for k, v in o.attrib.items() if k not in ("r", "sc")}))
    return out, other
