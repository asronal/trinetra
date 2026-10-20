from pathlib import Path

import pytest

from trinetra.core.events import read_events
from trinetra.scoring.roe import (HOSTILE_CLOSE_APPROACHING, HOSTILE_CLOSE_HOLDING, HOSTILE_FAR, NON_HOSTILE,
                                  RoeSet, get_roe, response_credit, threat_state)
from trinetra.scoring.rubric import WEIGHTS, score_run

HAND = Path(__file__).resolve().parent / "data" / "hand_scored.jsonl"
ROE = RoeSet(engage_range_m=1000.0, approach_mps=1.0)


@pytest.mark.parametrize("hostile, rng, closing, state", [
    (False, 200, 20, NON_HOSTILE),
    (True, 1500, 20, HOSTILE_FAR),
    (True, 800, 20, HOSTILE_CLOSE_APPROACHING),
    (True, 800, -5, HOSTILE_CLOSE_HOLDING),
])
def test_threat_state_tree(hostile, rng, closing, state):
    assert threat_state(hostile, rng, closing, ROE) == state


def test_credits():
    assert response_credit(HOSTILE_FAR, "alert_qrt") == 1.0
    assert response_credit(HOSTILE_FAR, "simulated_soft_kill") == 0.0          # premature engagement
    assert response_credit(HOSTILE_CLOSE_APPROACHING, "simulated_hard_kill") == 0.5
    assert response_credit(HOSTILE_CLOSE_APPROACHING, "simulated_hard_kill", soft_kill_tried=True) == 1.0
    assert response_credit(HOSTILE_CLOSE_HOLDING, "hand_off") == 1.0
    assert response_credit(NON_HOSTILE, "simulated_hard_kill") == 0.0


def test_unknown_roe_set_names_known_ones():
    with pytest.raises(KeyError, match="standard-forward-post"):
        get_roe("wild-west")


def test_score_run_on_hand_log():
    s = score_run(read_events(HAND))
    # detect: UAV-01 3 s (1.0), UAV-02 15 s (0.5)
    assert s.detect == pytest.approx(0.75)
    # classify: UAV-01 1.0, UAV-02 0.5 (wrong label), BIRD-1 0.0 (wrong label and declared hostile)
    assert s.classify == pytest.approx(1.5 / 3)
    # respond: UAV-01 alert_qrt far (1.0), hard kill before soft (0.5), soft (1.0), hard after soft (1.0)
    #          UAV-02 never responded to (0.0)
    assert s.respond == pytest.approx((3.5 / 4 + 0.0) / 2)
    # false alarms: bird declared hostile (1) + UAV-02 missed (1)
    assert s.false_alarm_count == 1 and s.missed_hostiles == ["UAV-02"]
    assert s.false_alarms == pytest.approx(0.5)
    expected = sum(WEIGHTS[k] * v for k, v in
                   {"detect": 0.75, "classify": 0.5, "respond": 3.5 / 8, "false_alarms": 0.5}.items())
    assert s.total == pytest.approx(expected)


def test_score_run_explains_itself():
    notes = "\n".join(score_run(read_events(HAND)).notes)
    assert "BIRD-1: bird declared hostile" in notes
    assert "UAV-02: classified as quad, was fixed_wing" in notes
    assert "UAV-01: simulated_hard_kill at 61.0 s" in notes
    assert "UAV-02: hostile in coverage but never responded to" in notes


def test_engaging_clutter_is_a_false_alarm():
    events = read_events(HAND) + [
        {"t": 95.0, "type": "trainee_respond", "track_id": 9, "truth_id": None, "action": "simulated_soft_kill"}]
    assert score_run(events).false_alarm_count == 2


def test_repeated_wrong_orders_collapse_into_one_note():
    events = read_events(HAND) + [
        {"t": 95.0 + i * 0.3, "type": "trainee_respond", "track_id": 2, "truth_id": "BIRD-1",
         "action": "simulated_soft_kill"} for i in range(18)]
    notes = [n for n in score_run(events).notes if "soft_kill on bird" in n]
    assert notes == ["BIRD-1: simulated_soft_kill on bird x18 (95.0-100.1 s)"]


def test_aar_timeline_grades_each_decision():
    from trinetra.scoring.aar import timeline
    tl = timeline(read_events(HAND))
    rows = {r["id"]: r for r in tl["rows"]}
    assert tl["duration"] == 90.0 and set(rows) == {"UAV-01", "UAV-02", "BIRD-1"}
    uav = rows["UAV-01"]
    assert uav["detectable"] == 3.0 and uav["time_to_detect_s"] == 3.0
    grades = [(m["kind"], m["grade"]) for m in uav["marks"]]
    # select, classify right, alert far (right), hard kill before soft (partly), soft kill (right), hard after soft (right)
    assert grades == [("select", "info"), ("classify", "good"), ("respond", "good"),
                      ("respond", "partial"), ("respond", "good"), ("respond", "good")]
    bird = rows["BIRD-1"]
    assert [m["grade"] for m in bird["marks"] if m["kind"] == "classify"] == ["bad"]
    assert "it was a bird, not hostile" in bird["marks"][-1]["text"]
    assert rows["UAV-02"]["marks"][-1]["grade"] == "partial"           # right threat, wrong type
