"""
TRINETRA — target classes and response actions.

Kept in one place so the scenario loader, the sensor emulators and the
event-log schema all agree on the same names.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ClassProfile:
    rcs_m2: float              # radar cross-section (order of magnitude, emulator only)
    typical_speed_mps: float   # used when a scenario omits speed_mps
    default_alt_m: float       # used when a scenario omits alt_m


CLASS_PROFILES = {
    "quad":       ClassProfile(rcs_m2=0.01,  typical_speed_mps=12.0, default_alt_m=60.0),
    "hexa":       ClassProfile(rcs_m2=0.03,  typical_speed_mps=10.0, default_alt_m=80.0),
    "fixed_wing": ClassProfile(rcs_m2=0.10,  typical_speed_mps=25.0, default_alt_m=150.0),
    "fpv":        ClassProfile(rcs_m2=0.005, typical_speed_mps=30.0, default_alt_m=20.0),
    "bird":       ClassProfile(rcs_m2=0.01,  typical_speed_mps=10.0, default_alt_m=40.0),
    "aircraft":   ClassProfile(rcs_m2=5.0,   typical_speed_mps=60.0, default_alt_m=500.0),
}

CLASSES = tuple(CLASS_PROFILES)

# Abstract, simulated decisions only. TRINETRA has no real effector interfaces.
RESPONSE_ACTIONS = (
    "monitor",
    "alert_qrt",
    "hand_off",
    "simulated_soft_kill",
    "simulated_hard_kill",
    "ignore",
)

SENSORS = ("eo", "ir", "radar")
