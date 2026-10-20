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
class IRConfig:
    # Default: a cooled-class narrow-FOV LWIR camera. MLX90640 preset: 32x24, 55°.
    width: int = 320
    height: int = 256
    hfov_deg: float = 12.0
    frame_hz: float = 10.0
    supersample: int = 4            # render at 4x, then area-average (sub-pixel targets)
    blur_sigma_px: float = 0.6      # optics
    netd_c: float = 0.08            # temporal noise, 1 sigma
    column_fpn_c: float = 0.05      # fixed-pattern noise per column, 1 sigma
    atten_per_km: float = 0.15      # clear-air extinction
    fog_atten_per_km: float = 3.0   # extra extinction at fog = 1.0
    noise_degrade_factor: float = 6.0
    palette: str = "white_hot"      # white_hot | black_hot | ironbow | rescue
    # Auto-contrast (ported from SkyNetics ThermalCamera)
    agc_low_pct: float = 2.0
    agc_high_pct: float = 99.0
    agc_min_span_c: float = 5.0
    agc_ema_alpha: float = 0.15
    # Detail enhancement: boosts small, sharp features (point targets) on top of the
    # global stretch, as real C-UAS cameras do. 0 disables it.
    dde_gain_per_c: float = 20.0    # extra grey levels per °C of local detail
    dde_sigma_px: float = 3.0       # scale separating "detail" from "scene"


@dataclass
class TrackerConfig:
    min_hits: int = 3               # confirm after this many hits ...
    confirm_window: int = 5         # ... within this many scans of the track's birth
    max_misses: int = 3             # drop a confirmed track after this many missed scans in a row
    gate_chi2: float = 9.21         # 99 % gate, 2 degrees of freedom
    accel_sigma_mps2: float = 3.0   # process noise (constant-velocity model)
    init_speed_sigma_mps: float = 30.0


@dataclass
class Config:
    tick_hz: float = 10.0
    duration_s: float = 60.0
    log_dir: str = "output/trinetra"
    truth_state_hz: float = 1.0     # how often truth positions go into the event log (AAR replay)
    radar: RadarConfig = field(default_factory=RadarConfig)
    ir: IRConfig = field(default_factory=IRConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
