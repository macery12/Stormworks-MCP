"""Simple equipment choices for generated vehicles; imports remain readable."""

PREBUILT_ENGINES = frozenset(("engine", "aircraft_engine", "engine_diesel"))
CURRENT_GEARBOXES = frozenset(f"modular_engine_gearbox_{size}x{size}" for size in (1, 3, 5))
LEGACY_GEARBOXES = frozenset(("torque_gearbox", "torque_gearbox_2"))
GEARBOXES = CURRENT_GEARBOXES | LEGACY_GEARBOXES


def restriction(d):
    # These are standalone transmission parts despite their internal prefix.
    if d in CURRENT_GEARBOXES:
        return None
    if d in LEGACY_GEARBOXES:
        return "Deprecated gearbox placement is disabled. Choose modular_engine_gearbox_1x1 (Gearbox 1x1)."
    if d.startswith("modular_engine"):
        return "Modular engines are disabled. Choose engine (small), aircraft_engine (medium) or engine_diesel (large)."
    if (d.startswith(("engine", "jet_")) or d == "aircraft_engine") and d not in PREBUILT_ENGINES:
        return "Only prebuilt diesel engines are supported: engine, aircraft_engine, engine_diesel."
    if d.startswith(("heat_exchanger", "heatsink", "heat_sink", "fluid_heat", "coolant", "radiator")):
        return "Cooling placement is restricted to radiators: search_land_parts(category='cooling')."
    return None


def allowed(d):
    return restriction(d) is None


def ensure_allowed(d):
    message = restriction(d)
    if message:
        raise ValueError(f"Cannot place {d!r}. {message}")
