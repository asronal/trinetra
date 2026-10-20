from dataclasses import dataclass

import numpy as np
import pytest

from trinetra.config import RadarConfig
from trinetra.core.behaviours import StraightLine
from trinetra.core.scenario import Degradation
from trinetra.core.world import Entity, World
from trinetra.sensors.radar import EmulatedRadar, RadarPlot


def world_with(range_m, bearing_deg=0.0, label="quad"):
    import math
    rad = math.radians(bearing_deg)
    e = Entity(id="T", label=label, hostile=True, spawn_s=0.0,
               pos=(range_m * math.sin(rad), range_m * math.cos(rad), 0.0),
               behaviour=StraightLine(heading_deg=0.0, speed_mps=0.0))
    w = World([e])
    w.start()
    return w


def scans(radar, world, n, period):
    return [radar.read(world, i * period) for i in range(n)]


def test_pd_falls_with_range_and_is_half_at_coverage_edge():
    cfg = RadarConfig()
    radar = EmulatedRadar(cfg, np.random.default_rng(0))
    r50 = radar.coverage_range_m(cfg.ref_rcs_m2)
    assert r50 == pytest.approx(cfg.ref_range_m)
    assert radar.detection_probability(0.01, 500) > 0.9
    assert radar.detection_probability(0.01, r50) == pytest.approx(cfg.pd_max / 2)
    assert radar.detection_probability(0.01, 5000) < 1e-3
    assert radar.detection_probability(0.01, 10) == 0.0          # blind zone
    # Bigger targets are seen further away: 16x RCS -> 2x range
    assert radar.coverage_range_m(0.16) == pytest.approx(2 * r50)


def test_scans_only_on_scan_period():
    cfg = RadarConfig(scan_period_s=1.0)
    radar = EmulatedRadar(cfg, np.random.default_rng(0))
    w = world_with(500)
    results = [radar.read(w, i / 10) for i in range(21)]
    assert [i for i, r in enumerate(results) if r is not None] == [0, 10, 20]


def test_close_target_is_detected_with_small_error():
    cfg = RadarConfig(clutter_per_scan=0.0)
    radar = EmulatedRadar(cfg, np.random.default_rng(1))
    w = world_with(800, bearing_deg=40)
    plots = [p for s in scans(radar, w, 200, cfg.scan_period_s) for p in s.plots]
    assert 0.9 < len(plots) / 200 <= 1.0
    ranges = np.array([p.range_m for p in plots])
    bearings = np.array([p.bearing_deg for p in plots])
    assert abs(ranges.mean() - 800) < 3 and 5 < ranges.std() < 11
    assert abs(bearings.mean() - 40) < 0.5
    assert all(p.truth_id == "T" for p in plots)


def test_same_seed_gives_same_scans():
    cfg = RadarConfig()
    a = scans(EmulatedRadar(cfg, np.random.default_rng(7)), world_with(2400), 50, 1.0)
    b = scans(EmulatedRadar(cfg, np.random.default_rng(7)), world_with(2400), 50, 1.0)
    assert [s.plots for s in a] == [s.plots for s in b]


def test_jamming_cuts_detections_and_adds_clutter():
    cfg = RadarConfig()
    jam = [Degradation(at_s=0, sensor="radar", kind="jamming", duration_s=1e6)]
    clear = scans(EmulatedRadar(cfg, np.random.default_rng(3)), world_with(1500), 300, 1.0)
    jammed = scans(EmulatedRadar(cfg, np.random.default_rng(3), jam), world_with(1500), 300, 1.0)

    def hits(ss):
        return sum(p.truth_id == "T" for s in ss for p in s.plots)

    def clutter(ss):
        return sum(p.truth_id is None for s in ss for p in s.plots)

    assert all(s.status == "jammed" for s in jammed)
    assert hits(clear) > 250 and hits(jammed) < 10
    assert clutter(jammed) > 4 * clutter(clear)


def test_dropout_blanks_scans_and_ignores_other_sensors():
    degs = [Degradation(0, "radar", "dropout", 2.5), Degradation(0, "eo", "jamming", 100)]
    radar = EmulatedRadar(RadarConfig(), np.random.default_rng(0), degs)
    ss = scans(radar, world_with(500), 4, 1.0)
    assert [s.status for s in ss] == ["dropout", "dropout", "dropout", "ok"]
    assert ss[0].plots == []


def test_in_coverage_ignores_jamming():
    jam = [Degradation(0, "radar", "jamming", 100)]
    radar = EmulatedRadar(RadarConfig(), np.random.default_rng(0), jam)
    assert radar.in_coverage(world_with(2000).entities[0])
    assert not radar.in_coverage(world_with(2600).entities[0])
    assert not radar.in_coverage(world_with(10).entities[0])


@dataclass
class FakeLD2450Target:
    x_mm: int
    y_mm: int
    speed_cm_s: int
    resolution: int = 360


def test_plot_matches_ld2450_target_fields_both_ways():
    p = RadarPlot(range_m=5.0, bearing_deg=90.0, radial_speed_mps=1.5)
    assert (p.x_mm, p.y_mm, p.speed_cm_s, p.distance_cm) == (5000, 0, 150, 500.0)

    live = RadarPlot.from_ld2450(FakeLD2450Target(x_mm=3000, y_mm=4000, speed_cm_s=-20), boresight_deg=10.0)
    assert live.range_m == pytest.approx(5.0)
    assert live.bearing_deg == pytest.approx(10.0 + 36.8699, abs=1e-3)
    assert live.radial_speed_mps == pytest.approx(-0.2)
    assert live.truth_id is None
