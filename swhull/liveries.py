"""Named paint schemes in the style of the reference builds.

Measured on the reference ships: four to six colours cover 90% of the visible faces, on a
neutral base; decks are a mid grey; walls are broken up by panels in a second, slightly darker
tone; and a few accents (1-3% each) carry the identity: a slanted bow flash, a funnel cap, hull
numbers, hazard stripes. A livery sets the hull, deck, superstructure and roof colours and adds
paint items sized to the hull, ahead of the spec's own `paint` (which paints over them).
"""
import copy
import math


# name -> scheme. Colours: bottom (below the waterline), stripe (boot-top), topsides, deck,
# box (superstructure walls), roof, trim (bevels; None keeps the wall colour), accents.
LIVERIES = {
    "navy": {
        "about": "Warship haze grey like the Hawk and Artemis: light grey hull and superstructure in "
                 "panelled tones, dark grey bottom, mid-grey deck, black funnel caps.",
        "colors": {"bottom": "454545", "stripe": "454545", "topsides": "B4BAC2", "deck": "787878",
                   "box": "B4BAC2", "roof": "A1ACB6", "trim": None, "number": "454545"},
        "panels": {"hull": -0.04, "boxes": -0.08, "deck": -0.06}, "caps": "1A1A1A",
    },
    "coast_guard": {
        "about": "White patrol scheme with the red and navy slanted bow flash, black bottom, grey deck.",
        "colors": {"bottom": "1A1A1A", "stripe": "1A1A1A", "topsides": "F0F0F0", "deck": "787878",
                   "box": "F0F0F0", "roof": "B4BAC2", "trim": None, "number": "243C55"},
        "panels": {"boxes": -0.05, "deck": -0.06}, "caps": "1A1A1A",
        "flash": ("BB4242", "243C55"),
    },
    "workboat": {
        "about": "Harbour working colours: black hull over red antifouling, red-brown deck, white "
                 "wheelhouse, yellow and black hazard stripes on the transom edge.",
        "colors": {"bottom": "8B1A1A", "stripe": "F0F0F0", "topsides": "1A1A1A", "deck": "8C2A1C",
                   "box": "F0F0F0", "roof": "C2C3C7", "trim": None, "number": "F0F0F0"},
        "panels": {"deck": -0.08}, "caps": "1A1A1A", "hazard": ("F2B705", "1A1A1A"),
    },
    "research": {
        "about": "Research-vessel scheme like the RSV Almus: navy hull, light grey superstructure, "
                 "blue deck, orange accents on the roofs.",
        "colors": {"bottom": "8B1A1A", "stripe": "F0F0F0", "topsides": "20337B", "deck": "324D6C",
                   "box": "C2C3C7", "roof": "969696", "trim": None, "number": "F0F0F0"},
        "panels": {"boxes": -0.06}, "caps": "FDA502",
    },
    "yacht": {
        "about": "Motor-yacht white with a navy boot-top, teak deck and dark window bands.",
        "colors": {"bottom": "1E3A5F", "stripe": "C9A227", "topsides": "F4F4F2", "deck": "B08050",
                   "box": "F4F4F2", "roof": "F4F4F2", "trim": None, "number": "1E3A5F",
                   "sheer_stripe": "1E3A5F"},
        "panels": {"deck": -0.1}, "caps": None,
    },
    "dazzle": {
        "about": "First World War dazzle camouflage: bold black, white, grey and blue angular bands "
                 "across hull and superstructure sides.",
        "colors": {"bottom": "2B2B2B", "stripe": "2B2B2B", "topsides": "E8E8E8", "deck": "6E6E6E",
                   "box": "E8E8E8", "roof": "8A8F96", "trim": None, "number": "1A1A1A"},
        "camo": {"style": "dazzle", "colors": ["1A1A1A", "E8E8E8", "6E7F8F", "2F4F6F", "E8E8E8"]},
        "caps": "1A1A1A",
    },
    "splinter": {
        "about": "Splinter camouflage: sharp-edged patches in four greys over hull and superstructure.",
        "colors": {"bottom": "2E3338", "stripe": "2E3338", "topsides": "B4BAC2", "deck": "5A5F66",
                   "box": "B4BAC2", "roof": "7F8890", "trim": None, "number": "1A1A1A"},
        "camo": {"style": "splinter", "colors": ["B4BAC2", "7F8890", "4A5058", "2E3338"]},
        "caps": "2E3338",
    },
}
FUNNEL = ("funnel", "stack", "exhaust", "mast")


def validate(livery):
    """Problems with a `livery` value."""
    if livery is None:
        return []
    name = livery.get("name") if isinstance(livery, dict) else livery
    if name not in LIVERIES:
        return [f"livery must be one of {', '.join(LIVERIES)} (or an object with name, colors, number, seed)"]
    if isinstance(livery, dict):
        extra = set(livery) - {"name", "colors", "number", "seed", "panels"}
        if extra:
            return [f"unknown livery field(s) {', '.join(sorted(extra))}"]
        colors = livery.get("colors", {})
        if not isinstance(colors, dict) or any(
                k not in LIVERIES[name]["colors"] or not (v is None or isinstance(v, str) and len(v) == 6)
                for k, v in colors.items()):
            return [f"livery.colors may set {', '.join(LIVERIES[name]['colors'])} (hex colours)"]
        if livery.get("number") is not None and not isinstance(livery["number"], str):
            return ["livery.number must be text, such as \"61\""]
    return []


def apply(spec):
    """Spec with its livery expanded into colours, box colours and paint items."""
    livery = spec.get("livery")
    if not livery:
        return spec
    options = livery if isinstance(livery, dict) else {"name": livery}
    scheme = LIVERIES[options["name"]]
    colours = {**scheme["colors"], **(options.get("colors") or {})}
    seed = int(options.get("seed", 1))
    out = copy.deepcopy(spec)
    out["colors"] = {**out["colors"], **{k: colours.get(k) for k in (
        "bottom", "stripe", "topsides", "deck", "roof", "trim", "sheer_stripe")}}
    for box in out.get("superstructure") or []:
        box["color"] = colours["box"]
        box.pop("roof_color", None)
        if scheme.get("caps") and any(word in str(box.get("name", "")).lower() for word in FUNNEL):
            box.setdefault("cap", {"height": min(0.75, box.get("height", 1.0) * 0.25), "color": scheme["caps"]})
    length, depth = spec["length"], spec["depth"]
    waterline = spec["colors"].get("waterline")
    waterline = waterline if waterline is not None else depth * 0.45
    out["colors"]["waterline"] = waterline
    items = []
    panels = scheme.get("panels", {}) if options.get("panels", True) else {}
    if "hull" in panels:
        items.append({"shape": "panels", "on": "sides", "box": "hull", "shade": panels["hull"],
                      "size": [length / 8, depth / 3], "seed": seed})
    if "boxes" in panels:
        for box in out.get("superstructure") or []:
            for on in ("sides", "front", "back"):
                items.append({"shape": "panels", "on": on, "box": box["name"], "shade": panels["boxes"],
                              "size": [1.5, 1.0], "seed": seed})
    if "deck" in panels:
        items.append({"shape": "panels", "on": "deck", "shade": panels["deck"], "size": [2.0, 1.0],
                      "share": 0.35, "seed": seed})
    if scheme.get("camo"):
        # Above the boot-top only: veterans keep the bottom plain antifouling.
        camo = {**scheme["camo"], "shape": "camo", "seed": seed, "scale": max(1.0, length / 8),
                "y": waterline + spec["colors"].get("stripe_height", 0.25), "height": 1000.0}
        items.append({**camo, "on": "sides", "z": -1000.0, "length": 3000.0})
        items.append({**camo, "on": "front", "x": 0.0, "width": 3000.0})
        items.append({**camo, "on": "back", "x": 0.0, "width": 3000.0})
    if scheme.get("flash"):
        items += _flash(scheme["flash"], length, depth + spec["sheer"]["bow"], waterline)
    if scheme.get("hazard"):
        top = depth + spec["sheer"]["stern"]
        items.append({"shape": "stripes", "on": "back", "box": "hull", "x": 0, "width": spec["beam"] * 2,
                      "y": top - 0.5, "height": 0.5, "colors": list(scheme["hazard"]), "stripe": 0.25})
    number = options.get("number")
    if number:
        items.append({"shape": "text", "on": "sides", "box": "hull", "text": number, "z": length * 0.72,
                      "y": max(waterline + 0.5, depth - 1.75), "height": 1.25, "color": colours["number"]})
    out["paint"] = items + list(spec.get("paint") or [])
    return out


def _flash(colours, length, top, waterline):
    """Slanted bow flash: a wide band and a narrower one forward of it, rising toward the bow at
    about 64 degrees, from the waterline to above the sheer (the hull clips it)."""
    lean = (top + 1 - waterline) / math.tan(math.radians(64))
    out, z = [], length * 0.78
    for colour, width in zip(colours, (max(0.5, length * 0.045), max(0.375, length * 0.03))):
        out.append({"shape": "polygon", "on": "sides", "box": "hull", "color": colour, "points": [
            [z, waterline], [z + width, waterline], [z + width + lean, top + 1], [z + lean, top + 1]]})
        z += width
    return out
