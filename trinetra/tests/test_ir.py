import numpy as np
import pytest

from trinetra.config import IRConfig
from trinetra.core.behaviours import StraightLine
from trinetra.core.scenario import Degradation
from trinetra.core.world import Entity, World
from trinetra.sensors.ir import CAMERA_HEIGHT_M, EmulatedIR, PercentileAGC, build_palette


def world_with(*specs):
    """specs: (id, label, east, north, up)"""
    ents = [Entity(id=i, label=lab, hostile=True, spawn_s=0.0, pos=(e, n, u),
                   behaviour=StraightLine(0.0, 0.0)) for i, lab, e, n, u in specs]
    w = World(ents)
    w.start()
    return w


def camera(**kw):
    cfg = IRConfig(**kw)
    ir = EmulatedIR(cfg, np.random.default_rng(0), time_of_day="day")
    ir.point(0.0, 3.0)
    return ir


def peak_excess(temps, u, v, r=3):
    """Hottest pixel near (u, v) minus the median of the frame."""
    h, w = temps.shape
    patch = temps[max(0, int(v) - r):min(h, int(v) + r + 1), max(0, int(u) - r):min(w, int(u) + r + 1)]
    return float(patch.max() - np.median(temps))


def test_palettes_are_256_bgr_and_rescue_matches_skynetics_endpoints():
    for name in ("white_hot", "black_hot", "ironbow", "rescue"):
        lut = build_palette(name)
        assert lut.shape == (256, 3) and lut.dtype == np.uint8
    rescue = build_palette("rescue")
    assert tuple(rescue[0]) == (80, 10, 5)        # BGR of SkyNetics (r=5, g=10, b=80)
    assert tuple(build_palette("white_hot")[255]) == (255, 255, 255)


def test_agc_enforces_min_span_and_smooths():
    agc = PercentileAGC(min_span_c=5.0, alpha=0.5)
    flat = np.full((10, 10), 20.0)
    agc(flat)
    lo, hi = agc.limits
    assert hi - lo == pytest.approx(5.0)
    agc(flat + 10.0)                 # scene warms by 10 °C: limits move halfway
    assert agc.limits[0] == pytest.approx(lo + 5.0)


def test_target_ahead_projects_to_frame_centre():
    ir = camera()
    ir.point(0.0, 0.0)
    u, v, z = ir.project((0.0, 1000.0, CAMERA_HEIGHT_M))
    assert (u, v) == pytest.approx((ir.cfg.width / 2, ir.cfg.height / 2))
    assert z == pytest.approx(1000.0)
    assert ir.project((0.0, -1000.0, CAMERA_HEIGHT_M)) is None      # behind the camera


def test_drone_contrast_falls_with_range():
    ir = camera()
    excess = []
    for rng in (300, 800, 2000):
        temps, truth = ir.render(world_with(("Q", "quad", 0.0, rng, rng * np.tan(np.radians(3.0)) + 5)))
        assert len(truth) == 1
        excess.append(peak_excess(temps, truth[0].u, truth[0].v))
    assert excess[0] > excess[1] > excess[2] > 0.05
    assert truth[0].size_px < 1.0            # sub-pixel at 2 km


def test_fog_reduces_contrast():
    pos = ("Q", "quad", 0.0, 800.0, 800 * np.tan(np.radians(3.0)) + 5)
    clear = EmulatedIR(IRConfig(), np.random.default_rng(0), fog=0.0)
    foggy = EmulatedIR(IRConfig(), np.random.default_rng(0), fog=0.8)
    for ir in (clear, foggy):
        ir.point(0.0, 3.0)
    t1, tr1 = clear.render(world_with(pos))
    t2, tr2 = foggy.render(world_with(pos))
    assert peak_excess(t2, tr2[0].u, tr2[0].v) < 0.5 * peak_excess(t1, tr1[0].u, tr1[0].v)


def test_read_produces_image_and_dropout_blanks():
    degs = [Degradation(1.0, "ir", "dropout", 1.0), Degradation(0.0, "radar", "jamming", 100.0)]
    ir = EmulatedIR(IRConfig(width=64, height=48, frame_hz=1.0), np.random.default_rng(0), degradations=degs)
    w = world_with(("Q", "quad", 0.0, 500.0, 30.0))
    f0, f1, f2 = (ir.read(w, t) for t in (0.0, 1.0, 2.0))
    assert f0.status == "ok" and f0.image.shape == (48, 64, 3) and f0.image.dtype == np.uint8
    assert f1.status == "dropout" and f1.image is None
    assert f2.status == "ok"                  # radar jamming does not touch the passive IR camera
    assert ir.read(w, 2.5) is None            # not due yet at 1 Hz


def test_targets_out_of_view_are_not_rendered():
    ir = camera()
    _, truth = ir.render(world_with(("E", "quad", 1000.0, 0.0, 50.0)))    # due east, camera looks north
    assert truth == []


def test_detail_enhancement_makes_small_drone_stand_out_over_hot_ground():
    """Regression: with only the global stretch, hot ground ate the grey range (26 levels)."""
    w = world_with(("Q", "quad", -8.0, 400.0, 25.0))

    def target_minus_sky(dde_gain):
        ir = EmulatedIR(IRConfig(dde_gain_per_c=dde_gain), np.random.default_rng(3), time_of_day="day")
        ir.point(0.0, 2.0)
        for k in range(15):
            f = ir.read(w, k / 10)
        u, v = int(f.truth[0].u), int(f.truth[0].v)
        patch = f.image[v - 3:v + 4, u - 3:u + 4, 0].astype(int)
        return patch.max() - np.median(patch)

    plain, enhanced = target_minus_sky(0.0), target_minus_sky(20.0)
    assert plain < 40
    assert enhanced > 2 * plain and enhanced > 60
