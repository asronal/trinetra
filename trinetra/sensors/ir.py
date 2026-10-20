"""
TRINETRA — emulated thermal (LWIR) camera.

Pipeline per frame (plan §6.5):
  1. render scene temperatures at `supersample`x resolution: sky gradient,
     ground, and each entity as a warm body with a hot core (motors,
     bird core, exhaust), blended towards air temperature with range
  2. area-average to sensor resolution, so small or far drones become
     faint sub-pixel blobs, as they do on a real sensor
  3. optical blur, column fixed-pattern noise, temporal noise
  4. percentile auto-contrast with EMA smoothing, plus detail enhancement,
     then a palette

The auto-contrast and the "rescue" palette are ported from the SkyNetics
rescue-drone ThermalCamera. Detail enhancement is new: with only a global
stretch, warm ground takes most of the grey range and a drone 3 °C above
the sky shows as a faint smudge. The camera is passive, so radar jamming
does not affect it.
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

from ..config import IRConfig
from ..core.catalog import CLASS_PROFILES
from .base import Sensor

# Emulator values for Indian plains, °C
AMBIENT_C = {"day": 30.0, "dusk": 24.0, "night": 16.0}
GROUND_DC = {"day": 8.0, "dusk": 2.0, "night": -3.0}            # sun-heated by day, cools at night
TERRAIN_DC = {"urban": 3.0, "rural": 0.0, "mountain": -4.0, "coastal": -2.0}
SKY_HORIZON_DC = -12.0      # clear sky at the horizon, relative to ambient
SKY_ZENITH_DC = -45.0
FOG_SKY_FACTOR = 3.0        # fog hides the cold sky behind fog at air temperature
CAMERA_HEIGHT_M = 5.0       # mast height, used to find ground distance below the horizon
SILHOUETTE_ASPECT = 0.4     # height / span of a target seen side-on


# ── Palettes ─────────────────────────────────────────────────────────

def _bgr(r, g, b):
    return (b, g, r)


PALETTE_STOPS = {
    "white_hot": [(0.0, _bgr(0, 0, 0)), (1.0, _bgr(255, 255, 255))],
    "black_hot": [(0.0, _bgr(255, 255, 255)), (1.0, _bgr(0, 0, 0))],
    "ironbow": [(0.0, _bgr(0, 0, 0)), (0.25, _bgr(40, 0, 140)), (0.50, _bgr(185, 0, 150)),
                (0.72, _bgr(240, 110, 0)), (0.88, _bgr(255, 210, 0)), (1.0, _bgr(255, 255, 235))],
    # SkyNetics build_rescue_colormap(): blue-cold / orange-hot
    "rescue": [(0.0, _bgr(5, 10, 80)), (0.30, _bgr(30, 60, 180)), (0.55, _bgr(20, 180, 200)),
               (0.75, _bgr(200, 180, 20)), (0.90, _bgr(255, 100, 0)), (1.0, _bgr(255, 255, 220))],
}


def build_palette(name: str) -> np.ndarray:
    """256 x 3 uint8 lookup table in OpenCV BGR order."""
    stops = PALETTE_STOPS[name]
    pos = [p for p, _ in stops]
    x = np.arange(256) / 255.0
    lut = np.stack([np.interp(x, pos, [c[ch] for _, c in stops]) for ch in range(3)], axis=1)
    return lut.astype(np.uint8)


class PercentileAGC:
    """Percentile stretch with EMA-smoothed limits (from SkyNetics ThermalCamera._to_visual).

    Unlike the original it does not write its limits into the global config;
    read them from .limits instead.
    """

    def __init__(self, low_pct=2.0, high_pct=99.0, min_span_c=5.0, alpha=0.15):
        self.low_pct, self.high_pct = low_pct, high_pct
        self.min_span_c, self.alpha = min_span_c, alpha
        self._lo: Optional[float] = None
        self._hi: Optional[float] = None

    @property
    def limits(self) -> Tuple[Optional[float], Optional[float]]:
        return self._lo, self._hi

    def stretch(self, temps: np.ndarray) -> np.ndarray:
        """Update the limits and return grey levels as float (0..255, unclipped)."""
        lo, hi = (float(v) for v in np.percentile(temps, [self.low_pct, self.high_pct]))
        if hi - lo < self.min_span_c:       # avoid stretching noise on a flat scene
            hi = lo + self.min_span_c
        if self._lo is None:
            self._lo, self._hi = lo, hi
        else:
            a = self.alpha
            self._lo = (1 - a) * self._lo + a * lo
            self._hi = (1 - a) * self._hi + a * hi
        return (temps - self._lo) / (self._hi - self._lo) * 255.0

    def __call__(self, temps: np.ndarray) -> np.ndarray:
        return np.clip(self.stretch(temps), 0, 255).astype(np.uint8)


def gaussian_blur(img: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return img
    r = max(1, int(math.ceil(3 * sigma)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    h, w = img.shape
    p = np.pad(img, r, mode="edge")
    rows = sum(k[i] * p[:, i:i + w] for i in range(2 * r + 1))
    return sum(k[i] * rows[i:i + h, :] for i in range(2 * r + 1))


# ── Camera ───────────────────────────────────────────────────────────

@dataclass
class IRTruth:
    """Where an entity landed in the frame. Free labels for classifier training."""
    truth_id: str
    label: str
    u: float            # sensor pixels, column
    v: float            # sensor pixels, row
    size_px: float      # span in sensor pixels
    range_m: float


@dataclass
class IRFrame:
    t: float
    status: str                                # "ok" | "dropout"
    az_deg: float
    el_deg: float
    temps: Optional[np.ndarray] = None         # H x W float32, °C as measured (with noise)
    image: Optional[np.ndarray] = None         # H x W x 3 uint8, BGR
    truth: List[IRTruth] = field(default_factory=list)


class EmulatedIR(Sensor):
    name = "ir"

    def __init__(self, cfg: IRConfig, rng, time_of_day: str = "day", terrain: str = "rural",
                 fog: float = 0.0, degradations: Sequence = ()):
        self.cfg = cfg
        self.rng = rng
        self.ambient_c = AMBIENT_C[time_of_day]
        self.ground_c = self.ambient_c + GROUND_DC[time_of_day] + TERRAIN_DC[terrain]
        self.fog = fog
        self.degradations = [d for d in degradations if d.sensor == "ir"]
        self.f_px = (cfg.width / 2) / math.tan(math.radians(cfg.hfov_deg / 2))
        self.agc = PercentileAGC(cfg.agc_low_pct, cfg.agc_high_pct, cfg.agc_min_span_c, cfg.agc_ema_alpha)
        self.lut = build_palette(cfg.palette)
        self._fpn = rng.normal(0.0, cfg.column_fpn_c, cfg.width).astype(np.float32)
        # World-fixed ground texture: a few random low-frequency ripples in azimuth / depression
        self._tex = [(rng.uniform(2, 12), rng.uniform(0, 2 * np.pi),
                      rng.uniform(20, 120), rng.uniform(0, 2 * np.pi)) for _ in range(4)]
        self._bg_cache = None
        self._next_t = 0.0
        self.az_deg, self.el_deg = 0.0, 2.0

    # ── Pointing and projection ───────────────────────────────────
    def point(self, az_deg: float, el_deg: float) -> None:
        self.az_deg = az_deg % 360.0
        self.el_deg = max(-30.0, min(60.0, el_deg))

    def _basis(self):
        az, el = math.radians(self.az_deg), math.radians(self.el_deg)
        fwd = np.array([math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)])
        right = np.array([math.cos(az), -math.sin(az), 0.0])
        up = np.cross(right, fwd)
        return fwd, right, up

    def project(self, pos) -> Optional[Tuple[float, float, float]]:
        """World position -> (u, v, depth) in sensor pixels, or None if behind the camera."""
        fwd, right, up = self._basis()
        d = np.asarray(pos, dtype=float) - np.array([0.0, 0.0, CAMERA_HEIGHT_M])
        z = float(d @ fwd)
        if z <= 1.0:
            return None
        u = self.cfg.width / 2 + self.f_px * float(d @ right) / z
        v = self.cfg.height / 2 - self.f_px * float(d @ up) / z
        return u, v, z

    # ── Rendering ─────────────────────────────────────────────────
    def _fog_level(self, t: float) -> float:
        if any(d.kind == "fog" and d.active(t) for d in self.degradations):
            return max(self.fog, 0.6)
        return self.fog

    def _transmission(self, range_m: float, fog: float) -> float:
        k = self.cfg.atten_per_km + fog * self.cfg.fog_atten_per_km
        return math.exp(-k * range_m / 1000.0)

    def _background(self, fog: float) -> np.ndarray:
        """Sky and ground at sensor resolution (smooth, so no supersampling needed)."""
        key = (self.az_deg, self.el_deg, fog)
        if self._bg_cache is not None and self._bg_cache[0] == key:
            return self._bg_cache[1]
        cfg = self.cfg
        W, H, f = cfg.width, cfg.height, self.f_px
        fwd, right, up = self._basis()
        x = (np.arange(W) + 0.5 - W / 2) / f
        y = (H / 2 - (np.arange(H) + 0.5)) / f
        d = fwd[None, None, :] + x[None, :, None] * right[None, None, :] + y[:, None, None] * up[None, None, :]
        horiz = np.hypot(d[..., 0], d[..., 1])
        elev = np.arctan2(d[..., 2], horiz)
        azim = np.arctan2(d[..., 0], d[..., 1])

        sky = (self.ambient_c + SKY_HORIZON_DC
               + (SKY_ZENITH_DC - SKY_HORIZON_DC) * np.sqrt(np.clip(np.sin(elev), 0, 1)))
        fog_mix = 1.0 - math.exp(-FOG_SKY_FACTOR * fog)
        sky = (1 - fog_mix) * sky + fog_mix * self.ambient_c
        depression = np.clip(-elev, 1e-4, None)
        tex = sum(np.sin(a * azim + pa) * np.sin(b * depression + pb) for a, pa, b, pb in self._tex)
        ground_dist_km = CAMERA_HEIGHT_M / np.tan(depression) / 1000.0
        k = cfg.atten_per_km + fog * cfg.fog_atten_per_km
        tau = np.exp(-k * np.minimum(ground_dist_km, 50.0))
        ground = tau * (self.ground_c + 1.5 * tex) + (1 - tau) * self.ambient_c
        bg = np.where(elev >= 0, sky, ground).astype(np.float32)
        self._bg_cache = (key, bg)
        return bg

    def _splat(self, img, u, v, rx, ry, temp) -> None:
        """Draw a filled ellipse; targets smaller than a pixel blend in by their area."""
        H, W = img.shape
        area = math.pi * rx * ry
        if rx < 1.0 or ry < 1.0:
            c, r = int(math.floor(u)), int(math.floor(v))
            if 0 <= r < H and 0 <= c < W:
                frac = min(1.0, area)
                img[r, c] += frac * (temp - img[r, c])
            return
        c0, c1 = max(0, int(u - rx)), min(W, int(u + rx) + 1)
        r0, r1 = max(0, int(v - ry)), min(H, int(v + ry) + 1)
        if c0 >= c1 or r0 >= r1:
            return
        cc = np.arange(c0, c1) + 0.5
        rr = np.arange(r0, r1) + 0.5
        mask = ((cc[None, :] - u) / rx) ** 2 + ((rr[:, None] - v) / ry) ** 2 <= 1.0
        img[r0:r1, c0:c1][mask] = temp

    def render(self, world, t: float = 0.0) -> Tuple[np.ndarray, List[IRTruth]]:
        """Noise-free scene temperatures at sensor resolution, plus where each entity landed.

        Each entity is drawn into a small supersampled patch cut from the
        background and area-averaged back, so sub-pixel targets keep their
        partial coverage without supersampling the whole frame.
        """
        cfg, ss = self.cfg, self.cfg.supersample
        fog = self._fog_level(t)
        img = self._background(fog).copy()
        truth = []
        # Far to near, so nearer targets draw over farther ones
        for e in sorted(world.active(), key=lambda e: -e.slant_range_m):
            p = self.project(e.pos)
            if p is None:
                continue
            u, v, z = p
            prof = CLASS_PROFILES[e.label]
            size_px = prof.span_m * self.f_px / z
            if not (-size_px <= u <= cfg.width + size_px and -size_px <= v <= cfg.height + size_px):
                continue
            tau = self._transmission(e.slant_range_m, fog)
            body = tau * (self.ambient_c + prof.body_dc) + (1 - tau) * self.ambient_c
            hot = tau * prof.hot_c + (1 - tau) * self.ambient_c
            truth.append(IRTruth(e.id, e.label, u, v, size_px, e.slant_range_m))

            half = int(math.ceil(size_px / 2)) + 1
            c0, c1 = max(0, int(u) - half), min(cfg.width, int(u) + half + 1)
            r0, r1 = max(0, int(v) - half), min(cfg.height, int(v) + half + 1)
            if c0 >= c1 or r0 >= r1:
                continue
            patch = np.repeat(np.repeat(img[r0:r1, c0:c1], ss, axis=0), ss, axis=1)
            pu, pv = (u - c0) * ss, (v - r0) * ss
            rx = size_px * ss / 2
            ry = rx * SILHOUETTE_ASPECT
            k = math.sqrt(prof.hot_frac)
            self._splat(patch, pu, pv, rx, ry, body)
            self._splat(patch, pu, pv, rx * k, ry * k, hot)
            img[r0:r1, c0:c1] = patch.reshape(r1 - r0, ss, c1 - c0, ss).mean(axis=(1, 3))

        return gaussian_blur(img, cfg.blur_sigma_px).astype(np.float32), truth

    # ── Sensor interface ─────────────────────────────────────────
    def read(self, world, t: float) -> Optional[IRFrame]:
        if t + 1e-9 < self._next_t:
            return None
        self._next_t += 1.0 / self.cfg.frame_hz
        if any(d.kind == "dropout" and d.active(t) for d in self.degradations):
            return IRFrame(t, "dropout", self.az_deg, self.el_deg)

        temps, truth = self.render(world, t)
        noisy = any(d.kind == "noise" and d.active(t) for d in self.degradations)
        netd = self.cfg.netd_c * (self.cfg.noise_degrade_factor if noisy else 1.0)
        temps = temps + self._fpn[None, :] + self.rng.normal(0.0, netd, temps.shape).astype(np.float32)
        return IRFrame(t, "ok", self.az_deg, self.el_deg, temps, self.to_image(temps), truth)

    def to_image(self, temps: np.ndarray) -> np.ndarray:
        grey = self.agc.stretch(temps)
        if self.cfg.dde_gain_per_c > 0:
            detail = temps - gaussian_blur(temps, self.cfg.dde_sigma_px)
            grey = grey + self.cfg.dde_gain_per_c * detail
        return self.lut[np.clip(grey, 0, 255).astype(np.uint8)]
