"""
TRINETRA — configuration.

Emulator settings describe a generic short-range counter-UAS sensor post.
They are training values, not the parameters of any real system.
"""

from dataclasses import dataclass, field


@dataclass
class RadarConfig:
    scan_period_s: float = 1.0
    # Detection model: 50 % Pd range scales with RCS^(1/4) (radar equation)
    ref_rcs_m2: float = 0.01        # small quadcopter
    ref_range_m: float = 2500.0     # 50 % Pd range for ref_rcs_m2
    pd_softness: float = 0.08       # width of the Pd roll-off, fraction of the 50 % range
    pd_max: float = 0.97
    min_range_m: float = 30.0       # blind zone around the post
    max_range_m: float = 6000.0     # instrumented range (clutter is drawn inside this)
    # Measurement noise (1 sigma)
    range_sigma_m: float = 8.0
    bearing_sigma_deg: float = 1.0
    speed_sigma_mps: float = 0.5
    # False alarms
    clutter_per_scan: float = 0.3   # Poisson mean
    # Jamming: shrinks the 50 % Pd range and raises the false-alarm rate
    jam_range_factor: float = 0.4
    jam_clutter_factor: float = 8.0


@dataclass
class Config:
    tick_hz: float = 10.0
    duration_s: float = 60.0
    log_dir: str = "output/trinetra"
    radar: RadarConfig = field(default_factory=RadarConfig)
