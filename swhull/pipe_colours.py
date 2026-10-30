"""Colour-code exposed pipes by what they carry (ISO 14726 main colours, plus an orange shaft).

Pipes running through hull blocks keep the hull colour instead; routing.route decides that.
"""
from . import definitions
from .pieces import apply, sub

# ISO 14726:2008 Table 2 main colours. Drive shafts are not pipes, so ISO has no colour for
# them; the player's fixed Mini Speedboat paints them orange.
COLOURS = {
    "fuel": "7A4A23",         # brown
    "fresh_water": "1F5FBF",  # blue, includes engine cooling water
    "sea_water": "2E8B3A",    # green
    "exhaust": "141414",      # black: waste media
    "air": "7A1F2B",          # maroon: air and sounding pipes
    "oil": "FF7F27",          # orange: oils other than fuel
    "steam": "C0C0C0",        # silver
    "shaft": "FF7F27",        # not ISO
}
UNKNOWN = "687681"  # neutral grey when the contents cannot be told from either end
TANK_FLUIDS = {"0": "fresh_water", "1": "fuel", "2": "fuel"}


def _label(parts, port):
    """The logic node label at a transmission face, e.g. 'Fuel' or 'In Coolant'."""
    found = [p for p in parts if p.uid == port["part_id"]]
    if not found:
        return None, None
    p = found[0]
    local = apply(tuple(zip(*p.Q)), sub(port["position"], p.origin))  # Q is orthonormal: inverse = transpose
    for node in (definitions.metadata(p.piece.d) or {}).get("logic_nodes", []):
        if node["type"] in (2, 3) and tuple(node["position"]) == tuple(local):
            return p, node["label"]
    return p, None


def medium(parts, a, b):
    """What a route between faces a and b carries, or None when neither end says."""
    if a["trans_type"] == 1 or b["trans_type"] == 1:
        return "shaft"
    ends = [_label(parts, port) for port in (a, b)]
    labels = {label for _, label in ends if label}
    if "Exhaust" in labels:
        return "exhaust"
    if "Air" in labels:
        return "air"
    if labels & {"In Coolant", "Out Coolant"}:
        return "fresh_water"
    if "Fuel" in labels:
        return "fuel"
    found = {p.piece.d: p for p, _ in ends if p is not None}
    if "fluid_radiator" in found:
        return "fresh_water"
    for p, label in ends:
        if p is not None and label == "Stored Fluid":
            return TANK_FLUIDS.get(str(p.settings.get("fluid_type", "0")))
    if "water_inlet" in found:
        return "sea_water"
    return None


def colour(parts, a, b):
    return COLOURS.get(medium(parts, a, b), UNKNOWN)
