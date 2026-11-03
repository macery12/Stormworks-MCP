"""Placement defaults and read-only configuration evidence from saved components."""
import copy
import math
import re
from html import unescape
from xml.sax.saxutils import escape

from .part_policy import GEARBOXES, PREBUILT_ENGINES


def defaults(d):
    # Confirmed by the player's crank-only engine and corrected autosave. Omitting
    # this attribute loads the generated prebuilt engine at 0% power in game.
    if d in PREBUILT_ENGINES:
        return {"max_force_scale": 1}
    # The player's road test confirms index 0 is 1:-1, not forward.
    if d in GEARBOXES:
        return {"gear_ratio_1": 1, "gear_ratio_2": 0}
    return {}


def new_settings(d, settings):
    result = {**defaults(d), **copy.deepcopy(settings)}
    if d in PREBUILT_ENGINES:
        power = result["max_force_scale"]
        if isinstance(power, bool) or not isinstance(power, (int, float)) or not 0 <= power <= 1:
            raise ValueError("engine max_force_scale must be a number from 0 to 1 (1 = 100% power)")
    if d in GEARBOXES:
        for key in ("gear_ratio_1", "gear_ratio_2"):
            if isinstance(result[key], bool) or not isinstance(result[key], int) or result[key] < 0:
                raise ValueError(f"{key} must be a nonnegative integer index (1 = 1:1, 0 = 1:-1)")
    return result


def settings_of(p):
    """Read imports as saved; placement defaults must never conceal a missing setting."""
    if not p.raw_xml:
        return new_settings(p.piece.d, p.settings)
    match = re.search(r"<o\b([^>]*)", p.raw_xml)
    return {k: unescape(v) for k, v in re.findall(r'\b([A-Za-z_]\w*)="([^"]*)"', match[1])} if match else {}


def configure(p, settings):
    """Edit known non-geometric settings without rewriting imported component XML."""
    allowed = set(defaults(p.piece.d))
    if p.piece.d.startswith("fluid_tank_"):
        allowed.update(("fluid_type", "fluid_fill"))
    if p.piece.d == "gate_function_small":
        allowed.add("property_text")
    if not isinstance(settings, dict) or not settings or set(settings) - allowed:
        raise ValueError(f"configure supports only {sorted(allowed)} for {p.piece.d}")
    if any(not isinstance(v, (str, int, float, bool)) or isinstance(v, float) and not math.isfinite(v)
           for v in settings.values()):
        raise ValueError("settings must be finite scalar values")
    # Validate changed numeric fields without applying defaults to untouched imports.
    new_settings(p.piece.d, {**defaults(p.piece.d), **settings})
    if "fluid_type" in settings and (type(settings["fluid_type"]) is not int or not 0 <= settings["fluid_type"] <= 6):
        raise ValueError("fluid_type must be an integer from 0 to 6 (diesel = 1)")
    if "fluid_fill" in settings and (isinstance(settings["fluid_fill"], bool)
                                    or not isinstance(settings["fluid_fill"], (int, float))
                                    or not 0 <= settings["fluid_fill"] <= 1):
        raise ValueError("fluid_fill must be between 0 and 1")
    if "property_text" in settings and (not isinstance(settings["property_text"], str)
                                        or not 1 <= len(settings["property_text"]) <= 512):
        raise ValueError("property_text must contain 1-512 characters")
    p.settings.update(settings)
    if p.raw_xml:
        match = re.search(r"<o\b[^>]*", p.raw_xml)
        if match is None:
            raise ValueError("component has no configuration object")
        tag = match[0]
        for key, value in settings.items():
            attr = f'{key}="{escape(str(value), {chr(34): "&quot;"})}"'
            pattern = rf'(?<!\w){key}="[^"]*"'
            tag = re.sub(pattern, lambda _m, replacement=attr: replacement, tag) if re.search(pattern, tag) else tag + " " + attr
        p.raw_xml = p.raw_xml[:match.start()] + tag + p.raw_xml[match.end():]


def engine_power(p):
    value = settings_of(p).get("max_force_scale")
    try:
        power = float(value)
    except (ValueError, TypeError):
        power = None
    ok = power is not None and 0 < power <= 1
    return {"part_id": p.uid, "setting": "max_force_scale", "value": value,
            "status": "configured" if ok else "invalid", "power_percent": power * 100 if ok else None,
            "detail": "Prebuilt engine power must be explicitly positive; use max_force_scale=1 for 100% power."}


# Modular gearbox ratio indices, input:output with power entering RPS A. Decoded from the
# player's engine tester (each output switches one gearbox whose overall ratio it labels) and
# 886 saved gearboxes: the game never saves off=1 or on=5, so those are the omitted defaults.
# Power entering RPS B gives the inverse (index 7 is then 1:3). Index 0 is reverse (road test).
MODULAR_RATIOS = {0: "1:-1", 1: "1:1", 2: "6:5", 3: "3:2", 4: "9:5", 5: "2:1", 6: "5:2", 7: "3:1"}
MODULAR_DEFAULTS = {"gear_ratio_1": 1, "gear_ratio_2": 5}


def gearbox_ratios(p):
    """Saved switch states with their ratios; a modular gearbox's omitted setting is the game default."""
    settings, states = settings_of(p), {}
    modular = p.piece.d.startswith("modular_engine_gearbox")
    for state, key in (("off", "gear_ratio_1"), ("on", "gear_ratio_2")):
        value = settings.get(key)
        default = value is None and modular
        if default:
            value = MODULAR_DEFAULTS[key]
        try:
            index = int(str(value))
        except (TypeError, ValueError):
            index = None
        valid = index is not None and index >= 0
        ratio = (MODULAR_RATIOS if modular else {0: "1:-1", 1: "1:1"}).get(index)
        states[state] = {"setting": key, "value": value, "index": index if valid else None,
                         "ratio": ratio, "saved_default": default,
                         "direction": "invalid" if not valid else
                         "reverse" if index == 0 else "forward" if ratio else "unverified"}
    return {"part_id": p.uid, "definition": p.piece.d, **states,
            "status": "invalid" if any(s["direction"] == "invalid" for s in states.values()) else "configured",
            "detail": "Gear Switch off uses gear_ratio_1; on uses gear_ratio_2 (an unwired gearbox stays at its off "
                      "ratio). Ratios are input:output with power entering RPS A; entering RPS B inverts them. "
                      "Modular indices: " + ", ".join(f"{k}={v}" for k, v in MODULAR_RATIOS.items())
                      + "; a save without a setting uses off 1:1, on 2:1. Placement writes off 1:1, on 1:-1."}
