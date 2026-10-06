"""Placement defaults and read-only configuration evidence from saved components."""
import copy
import re
from html import unescape

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


def gearbox_ratios(p):
    """Expose saved switch states; other editor ratios remain unverified, not guessed."""
    settings, states = settings_of(p), {}
    for state, key in (("off", "gear_ratio_1"), ("on", "gear_ratio_2")):
        value = settings.get(key)
        try:
            index = int(str(value))
        except (TypeError, ValueError):
            index = None
        valid = index is not None and index >= 0
        states[state] = {"setting": key, "value": value, "index": index if valid else None,
                         "ratio": {0: "1:-1", 1: "1:1"}.get(index),
                         "direction": "invalid" if not valid else
                         {0: "reverse", 1: "forward"}.get(index, "unverified")}
    return {"part_id": p.uid, "definition": p.piece.d, **states,
            "status": "invalid" if any(s["direction"] == "invalid" for s in states.values()) else "configured",
            "detail": "Gear Switch off uses gear_ratio_1; on uses gear_ratio_2. Placement defaults: off 1:1, on 1:-1. Other ratio indices require editor/game checks."}
