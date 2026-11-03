"""Which parts may be placed, and which systems preflight can check.

Every installed part can be placed except the gearboxes the game itself has deprecated. Parts
whose systems preflight does not model yet are placed normally and reported as "unchecked".
"""

PREBUILT_ENGINES = frozenset(("engine", "aircraft_engine", "engine_diesel"))
CURRENT_GEARBOXES = frozenset(f"modular_engine_gearbox_{size}x{size}" for size in (1, 3, 5))
LEGACY_GEARBOXES = frozenset(("torque_gearbox", "torque_gearbox_2"))
GEARBOXES = CURRENT_GEARBOXES | LEGACY_GEARBOXES

# Prefix -> the system preflight cannot check yet.
_UNCHECKED = (
    ("jet_engine", "jet engine"),
    (("steam_", "turbine"), "steam power"),
    (("solid_rocket", "liquid_rocket", "rcs_thruster"), "rocket"),
    (("heat_exchanger", "fluid_heat_sink", "intercooler", "cryo_cooler", "air_exchanger", "heater"),
     "heat exchange"),
    (("turbocharger", "catalytic_converter"), "engine air handling"),
)


def restriction(d):
    """Why `d` cannot be placed, or None."""
    if d in LEGACY_GEARBOXES:
        return ("The game deprecated this gearbox. Choose modular_engine_gearbox_1x1 (Gearbox 1x1), "
                "3x3 or 5x5.")
    return None


def allowed(d):
    return restriction(d) is None


def ensure_allowed(d):
    message = restriction(d)
    if message:
        raise ValueError(f"Cannot place {d!r}. {message}")


def unchecked(d):
    """The system preflight cannot check for part `d` yet, or None when it is covered or inert."""
    if d in CURRENT_GEARBOXES:
        return None
    for prefixes, system in _UNCHECKED:
        if d.startswith(prefixes):
            return system
    return None
