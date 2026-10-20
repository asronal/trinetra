import math

import numpy as np
import pytest

from trinetra.ai.tracker import CONFIRMED, TENTATIVE, Tracker, assign
from trinetra.config import RadarConfig, TrackerConfig
from trinetra.sensors.radar import RadarPlot


def plot_at(east, north, truth_id="T", speed=0.0):
    return RadarPlot(math.hypot(east, north), math.degrees(math.atan2(east, north)) % 360.0, speed, truth_id)


def tracker(**kw):
    return Tracker(TrackerConfig(**kw), range_sigma_m=8.0, bearing_sigma_deg=1.0)


def test_track_confirms_after_min_hits_not_on_first_plot():
    """Regression for the SkyNetics streak bug: min_hits >= 2 must still confirm."""
    trk = tracker(min_hits=3)
    confirmed_at = None
    for scan in range(5):
        upd = trk.update([plot_at(0.0, 1000.0 - 10 * scan)], t=float(scan))
        if upd.confirmed:
            confirmed_at = scan
    assert confirmed_at == 2                  # third hit
    assert len(trk.confirmed) == 1


def test_track_velocity_is_unbiased():
    # 1° bearing noise at 2 km is ~35 m cross-range per scan, so one run's velocity
    # is noisy (~3 m/s); the mean over many runs must still be right.
    v = []
    for seed in range(40):
        rng = np.random.default_rng(seed)
        trk = tracker()
        for k in range(30):
            e, n = 500.0 + 15.0 * k, 2000.0 - 5.0 * k
            r = math.hypot(e, n) + rng.normal(0, 8)
            b = math.degrees(math.atan2(e, n)) + rng.normal(0, 1)
            trk.update([RadarPlot(r, b, 0.0, "T")], t=float(k))
        (tr,) = trk.confirmed
        assert tr.truth_id == "T"
        v.append(tr.x[2:4])
    mean = np.mean(v, axis=0)
    assert mean[0] == pytest.approx(15.0, abs=1.5)
    assert mean[1] == pytest.approx(-5.0, abs=1.5)


def test_two_crossing_targets_keep_their_ids():
    trk = tracker()
    for k in range(15):
        trk.update([plot_at(-300 + 40 * k, 1500.0, "A"), plot_at(300 - 40 * k, 1600.0, "B")], t=float(k))
    by_truth = {tr.truth_id: tr.id for tr in trk.confirmed}
    assert set(by_truth) == {"A", "B"}
    assert len(set(by_truth.values())) == 2


def test_confirmed_track_dropped_after_max_misses():
    trk = tracker(max_misses=3)
    for k in range(5):
        trk.update([plot_at(0.0, 1000.0)], t=float(k))
    dropped = []
    for k in range(5, 9):
        dropped += trk.update([], t=float(k)).dropped
    assert len(dropped) == 1 and trk.tracks == []


def test_single_clutter_plot_never_confirms():
    trk = tracker()
    rng = np.random.default_rng(1)
    confirmed = []
    for k in range(30):
        plots = [RadarPlot(rng.uniform(30, 6000), rng.uniform(0, 360), 0.0, None)]
        confirmed += trk.update(plots, t=float(k)).confirmed
    assert confirmed == []
    assert all(tr.status == TENTATIVE for tr in trk.tracks)


def test_track_ids_are_per_tracker():
    a, b = tracker(), tracker()
    a.update([plot_at(0, 1000)], 0.0)
    b.update([plot_at(0, 1000)], 0.0)
    assert a.tracks[0].id == b.tracks[0].id == 1


def test_assign_respects_gate():
    cost = np.array([[1.0, 50.0], [50.0, 2.0], [0.5, 0.4]])
    pairs = sorted(assign(cost, gate=9.21))
    assert len(pairs) == 2 and all(cost[r, c] <= 9.21 for r, c in pairs)
    assert assign(np.full((2, 2), 100.0), gate=9.21) == []


def test_tentative_track_cannot_steal_a_confirmed_tracks_plots():
    """Regression (SCN-01, t=68-72 s): a tentative track born beside a target took its
    plots in a single global assignment, starved the confirmed track and replaced its ID."""
    trk = tracker()
    for k in range(6):
        trk.update([plot_at(0.0, 1500.0 - 20 * k, "T")], t=float(k))
    (confirmed,) = trk.confirmed
    # A stray plot 40 m to the side starts a tentative track there ...
    trk.update([plot_at(0.0, 1380.0, "T"), plot_at(40.0, 1378.0, None)], t=6.0)
    # ... and the target's plots then shift 40 m east: still inside the confirmed track's
    # gate, but cheaper for the loose new tentative track. The confirmed track must keep them.
    for k in range(7, 15):
        trk.update([plot_at(40.0, 1500.0 - 20 * k, "T")], t=float(k))
    assert [t.id for t in trk.confirmed] == [confirmed.id]
    assert trk.get(confirmed.id).misses == 0


def test_scn01_drone_keeps_one_track_id():
    from pathlib import Path
    from trinetra.config import Config
    from trinetra.core.scenario import load_scenario
    from trinetra.core.session import Session
    import tempfile
    scn = Path(__file__).resolve().parents[1] / "scenarios" / "scn01_day_single.yaml"
    with tempfile.TemporaryDirectory() as d:
        s = Session(load_scenario(scn), Config(), Path(d) / "log.jsonl", duration_s=130)
        ids = set()
        while not s.done:
            s.step()
            ids |= {t.id for t in s.tracker.confirmed if t.truth_id == "UAV-01"}
        s.finish()
    assert len(ids) == 1
