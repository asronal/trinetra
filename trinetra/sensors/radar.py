"""
TRINETRA — emulated surveillance radar.

Per scan, each active entity is detected with a probability that falls
off with range; the 50 % range scales with RCS^(1/4). Detections get
Gaussian range/bearing/speed error, Poisson clutter adds false plots, and
scenario degradations (jamming, dropout) shrink coverage or blank scans.

RadarPlot exposes the same fields as the SkyNetics LD2450 RadarTarget
(x_mm, y_mm, speed_cm_s, resolution), and RadarPlot.from_ld2450() turns
a live LD2450 target into a plot, so the HIL path plugs into the same
interface (plan §6.5).
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from ..config import RadarConfig
from .base import Sensor


@dataclass
class RadarPlot:
    range_m: float
    bearing_deg: float
    radial_speed_mps: float        # positive = approaching
    truth_id: Optional[str] = None  # None for clutter / live data
    resolution: int = 0

    # ── LD2450 RadarTarget-compatible view (x = east, y = north) ──
    @property
    def x_mm(self) -> int:
        return int(round(self.range_m * math.sin(math.radians(self.bearing_deg)) * 1000))

    @property
    def y_mm(self) -> int:
        return int(round(self.range_m * math.cos(math.radians(self.bearing_deg)) * 1000))

    @property
    def speed_cm_s(self) -> int:
        return int(round(self.radial_speed_mps * 100))

    @property
    def distance_cm(self) -> float:
        return self.range_m * 100.0

    @classmethod
    def from_ld2450(cls, target, boresight_deg: float = 0.0) -> "RadarPlot":
        """Convert a live LD2450 RadarTarget (x right, y ahead, mm) into a plot."""
        range_m = math.hypot(target.x_mm, target.y_mm) / 1000.0
        bearing = (boresight_deg + math.degrees(math.atan2(target.x_mm, target.y_mm))) % 360.0
        return cls(range_m, bearing, target.speed_cm_s / 100.0, None, target.resolution)


@dataclass
class RadarScan:
    t: float
    status: str                     # "ok" | "jammed" | "dropout"
    plots: List[RadarPlot] = field(default_factory=list)


class EmulatedRadar(Sensor):
    name = "radar"

    def __init__(self, cfg: RadarConfig, rng, degradations: Sequence = ()):
        self.cfg = cfg
        self.rng = rng
        self.degradations = [d for d in degradations if d.sensor == "radar"]
        self._next_scan_t = 0.0

    # ── Detection model ───────────────────────────────────────────
    def coverage_range_m(self, rcs_m2: float, jammed: bool = False) -> float:
        """Range at which Pd = 50 % for a target of this RCS."""
        r50 = self.cfg.ref_range_m * (rcs_m2 / self.cfg.ref_rcs_m2) ** 0.25
        return r50 * self.cfg.jam_range_factor if jammed else r50

    def detection_probability(self, rcs_m2: float, range_m: float, jammed: bool = False) -> float:
        if range_m < self.cfg.min_range_m:
            return 0.0
        r50 = self.coverage_range_m(rcs_m2, jammed)
        x = (range_m - r50) / (self.cfg.pd_softness * r50)
        if x > 50:   # far outside coverage; avoid overflow in exp
            return 0.0
        return self.cfg.pd_max / (1.0 + math.exp(x))

    def in_coverage(self, entity) -> bool:
        """Ground-truth coverage: the target is detectable (Pd >= 50 %) in clear conditions.

        Jamming is deliberately ignored here: time to detect is measured from
        when the target became detectable, so degraded runs are harder, not
        excused.
        """
        r = entity.slant_range_m
        return self.cfg.min_range_m <= r <= self.coverage_range_m(entity.rcs_m2)

    # ── Sensor interface ─────────────────────────────────────────
    def read(self, world, t: float) -> Optional[RadarScan]:
        if t + 1e-9 < self._next_scan_t:
            return None
        self._next_scan_t += self.cfg.scan_period_s

        active = {d.kind for d in self.degradations if d.active(t)}
        if "dropout" in active:
            return RadarScan(t, "dropout")
        jammed = "jamming" in active

        cfg, rng = self.cfg, self.rng
        plots = []
        for e in world.active():
            r = e.slant_range_m
            if rng.random() >= self.detection_probability(e.rcs_m2, r, jammed):
                continue
            plots.append(RadarPlot(
                range_m=max(0.0, r + rng.normal(0.0, cfg.range_sigma_m)),
                bearing_deg=(e.bearing_deg + rng.normal(0.0, cfg.bearing_sigma_deg)) % 360.0,
                radial_speed_mps=e.radial_speed_mps + rng.normal(0.0, cfg.speed_sigma_mps),
                truth_id=e.id,
            ))

        n_clutter = rng.poisson(cfg.clutter_per_scan * (cfg.jam_clutter_factor if jammed else 1.0))
        for _ in range(n_clutter):
            plots.append(RadarPlot(
                range_m=rng.uniform(cfg.min_range_m, cfg.max_range_m),
                bearing_deg=rng.uniform(0.0, 360.0),
                radial_speed_mps=rng.normal(0.0, 2.0),
            ))

        return RadarScan(t, "jammed" if jammed else "ok", plots)
