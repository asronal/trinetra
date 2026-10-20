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
    # ── Thermal signature (plan §6.5) ──
    span_m: float              # largest dimension (rotor-tip span / wingspan)
    body_dc: float             # body temperature above ambient, °C
    hot_c: float               # hot-spot temperature (motors, core, exhaust), °C
    hot_frac: float            # fraction of the silhouette at hot_c


CLASS_PROFILES = {
    "quad":       ClassProfile(0.01,  12.0, 60.0,  span_m=0.35, body_dc=3.0, hot_c=50.0,  hot_frac=0.15),
    "hexa":       ClassProfile(0.03,  10.0, 80.0,  span_m=0.90, body_dc=3.0, hot_c=55.0,  hot_frac=0.12),
    "fixed_wing": ClassProfile(0.10,  25.0, 150.0, span_m=2.00, body_dc=2.0, hot_c=70.0,  hot_frac=0.05),
    "fpv":        ClassProfile(0.005, 30.0, 20.0,  span_m=0.25, body_dc=5.0, hot_c=60.0,  hot_frac=0.20),
    "bird":       ClassProfile(0.01,  10.0, 40.0,  span_m=0.60, body_dc=2.0, hot_c=40.0,  hot_frac=0.30),
    "aircraft":   ClassProfile(5.0,   60.0, 500.0, span_m=30.0, body_dc=5.0, hot_c=300.0, hot_frac=0.02),
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
