from pathlib import Path

import pytest

from trinetra.config import Config
from trinetra.core.events import read_events
from trinetra.core.scenario import load_scenario, parse_scenario
from trinetra.core.session import EFFECT_RANGE_M, ActionError, Session

SCN = Path(__file__).resolve().parents[1] / "scenarios"


def run_until(s, pred, limit_s=200):
    while not pred(s) and s.t < limit_s and not s.done:
        s.step()
    assert pred(s), f"condition not reached by t={s.t}"


def uav_track(s, truth_id="UAV-01"):
    return next((t for t in s.tracker.confirmed if t.truth_id == truth_id), None)


def test_actions_need_a_confirmed_selected_track(tmp_path):
    s = Session(load_scenario(SCN / "scn01_day_single.yaml"), Config(), tmp_path / "a.jsonl")
    with pytest.raises(ActionError):
        s.classify("quad", True)
    with pytest.raises(ActionError):
        s.select(999)
    with pytest.raises(ActionError):
        s.respond("fire")
    s.finish()


def test_trainee_events_carry_resolved_truth_and_are_scored(tmp_path):
    s = Session(load_scenario(SCN / "scn01_day_single.yaml"), Config(), tmp_path / "b.jsonl")
    run_until(s, lambda s: uav_track(s) is not None)
    tr = uav_track(s)
    s.select(tr.id)
    s.classify("quad", True)
    s.respond("alert_qrt")
    score = s.finish()
    trainee = [e for e in read_events(s.log_path) if e["type"].startswith("trainee_")]
    assert [e["type"] for e in trainee] == ["trainee_select", "trainee_classify", "trainee_respond"]
    assert all(e["truth_id"] == "UAV-01" for e in trainee)
    assert score.classify == 1.0
    assert s.finish() is score                       # idempotent


def test_kill_out_of_range_has_no_effect_and_in_range_can_neutralise(tmp_path):
    s = Session(load_scenario(SCN / "scn01_day_single.yaml"), Config(), tmp_path / "c.jsonl")
    run_until(s, lambda s: uav_track(s) is not None)
    s.select(uav_track(s).id)
    assert "out of effect range" in s.respond("simulated_soft_kill").message

    run_until(s, lambda s: uav_track(s) is not None and uav_track(s).range_m < EFFECT_RANGE_M - 300)
    s.select(uav_track(s).id)
    for _ in range(5):                               # p = 0.9 each; seeded, so deterministic
        msg = s.respond("simulated_hard_kill").message
        if "target down" in msg:
            break
        t_next = s.t + 3.1                           # wait out the repeat guard
        run_until(s, lambda s: s.t >= t_next)
    assert "target down" in msg
    with pytest.raises(ActionError, match="already down"):
        s.respond("simulated_soft_kill")
    s.finish()
    ev = read_events(s.log_path)
    assert any(e["type"] == "truth_despawn" and e["reason"] == "neutralised_simulated" for e in ev)
    assert any(e["type"] == "truth_exit_coverage" and e["truth_id"] == "UAV-01" for e in ev)


def test_camera_does_not_change_what_the_radar_sees(tmp_path):
    def plots(with_ir, name):
        s = Session(load_scenario(SCN / "smoke.yaml"), Config(), tmp_path / name, duration_s=20, with_ir=with_ir)
        while not s.done:
            s.step()
        s.finish()
        return [e for e in read_events(s.log_path) if e["type"] == "sensor_plot"]
    assert plots(False, "x.jsonl") == plots(True, "y.jsonl")


def test_scenario_duration_and_briefing_load():
    sc = load_scenario(SCN / "scn02_dusk_decoys.yaml")
    assert sc.duration_s == 140 and "friendly" in sc.briefing and sc.title.startswith("SCN-02")


@pytest.mark.parametrize("name", ["smoke", "scn01_day_single", "scn02_dusk_decoys", "scn03_night_jam"])
def test_every_scenario_runs_headless(tmp_path, name):
    s = Session(load_scenario(SCN / f"{name}.yaml"), Config(), tmp_path / f"{name}.jsonl")
    while not s.done:
        s.step()
    score = s.finish()
    assert read_events(s.log_path)[-1]["type"] == "run_end"
    assert 0.0 <= score.total <= 1.0


def test_same_order_twice_within_guard_is_refused(tmp_path):
    s = Session(load_scenario(SCN / "scn01_day_single.yaml"), Config(), tmp_path / "g.jsonl")
    run_until(s, lambda s: uav_track(s) is not None)
    s.select(uav_track(s).id)
    s.respond("monitor")
    with pytest.raises(ActionError, match="already ordered"):
        s.respond("monitor")
    s.respond("alert_qrt")                           # a different order is fine
    t_next = s.t + 3.1
    run_until(s, lambda s: s.t >= t_next)
    s.respond("monitor")                             # and the same one again after the guard
    s.finish()
    assert [e["action"] for e in read_events(s.log_path) if e["type"] == "trainee_respond"] == \
        ["monitor", "alert_qrt", "monitor"]
