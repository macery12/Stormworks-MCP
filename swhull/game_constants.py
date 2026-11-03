"""Base-game physics constants, copied by hand from the Stormworks install.

Source: sdk/data/game_constants.xml (the documented defaults; the shipped game has no override
file, so these are what it uses) and rom/data/realtime_values/general_debug.txt. They are
hardcoded on purpose: this server never reads, writes or overrides the game's constants, and
mods that change them are out of scope.

Values marked provisional in PROVISIONAL are not confirmed by an in-game measurement yet.
"""

GAME_CONSTANTS = {
    # World
    "gravity": 10.0,
    "vehicle_linear_damping": 0.1,
    "vehicle_angular_damping": 0.1,
    "vehicle_friction": 0.8,
    # Aerodynamics
    "air_drag_factor_linear_pressure": 0.05,
    "air_drag_factor_quadratic_pressure": 0.1,
    "air_falloff_power_pressure": 0.6,
    "air_drag_factor_linear_suction": 0.025,
    "air_drag_factor_quadratic_suction": 0.05,
    "air_falloff_power_suction": 0.4,
    "air_drag_factor": 0.2,
    "air_speed_threshold": 15.0,
    "air_high_speed_threshold": 50.0,
    "air_high_speed_factor_scale": 8.0,
    "air_density": 1.225,
    "viscous_air_resistance": 0.25,
    "lift_force": 0.25,
    # Hydrodynamics
    "drag_factor_linear_pressure": 15.0,
    "drag_factor_quadratic_pressure": 17.0,
    "falloff_power_pressure": 2.5,
    "drag_factor_linear_suction": 12.0,
    "drag_factor_quadratic_suction": 5.0,
    "falloff_power_suction": 0.3,
    "water_drag_factor": 1.0,
    "water_drag_weight_factor_multiplier": 4.0,
    "water_density": 1000.0,
    "wave_velocity_factor": 0.5,
    "wave_velocity_factor_reverse": 0.3,
    "viscous_resistance_factor": 0.5,
    "slamming_force_multiplier": 100.0,
    "buoyancy_damping": 0.05,
    "buoyancy_damping_submerged": 0.92,
    "buoyancy_mass_multiplier": 10.0,
    "buoyancy_mass_modifier": 10.0,
    "buoyancy_mass_modifier_lower": 2000.0,
    "buoyancy_mass_modifier_upper": 23000.0,
    "buoyancy_mass_modifier_pow": 1.0,
}

# Grid and fluid facts used by the calculator.
BLOCK_METRES = 0.25
CELL_M3 = BLOCK_METRES ** 3            # 0.015625 m3 per block
CELL_LITRES = CELL_M3 * 1000           # 15.625 L per block
FLUID_MASS_PER_LITRE = 0.1             # game mass units per litre of tank fluid

# Settled by the player (2026-11-03): use game_constants.xml's 10, not general_debug.txt's 12.
BUOYANCY_MULTIPLIER_NOTE = ("10, from game_constants.xml and matching the community flotation formula; "
                            "general_debug.txt's 12 is not used.")

PROVISIONAL = {
    "buoyancy_mass_modifier_range": "the modifier ramps over (mass - lower) / upper, capped at 1, as the "
                                    "community formula does; (mass - lower) / (upper - lower) is also possible.",
    "fluid_mass": "0.1 mass per litre for every fluid; not yet measured in game.",
    "premade_tank_capacity": "a premade tank holds its voxel volume (15.625 L per block).",
    "component_volume": "a component's voxels displace water as solid blocks when they sit outside "
                        "a sealed space.",
    "lift": "wing area is rudder_surface_area x 0.0625 m2 and lift = 0.5 x air density x v2 x area x "
            "lift coefficient, for wing and control-surface parts only; the game also lifts block surfaces "
            "and its own lift model is not known yet.",
    "thrust": "force_emitter_max_force is a cap on what a propeller or rotor can push, not the thrust "
              "at a given speed or RPS.",
    "mass_units": "weight in air is mass x gravity, treating one game mass unit as one kilogram.",
}
