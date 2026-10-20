from pathlib import Path

import pytest

from trinetra.core.events import read_events
from trinetra.scoring.rubric import WEIGHTS, detection_score, score_detection, time_to_detect

HAND_LOG = Path(__file__).resolve().parent / "data" / "hand_written.jsonl"


@pytest.fixture
def events():
    return read_events(HAND_LOG)


def test_time_to_detect_per_hostile(events):
    r = time_to_detect(events)
    assert set(r) == {"UAV-01", "UAV-02", "UAV-03", "UAV-04"}       # bird is not a hostile
    assert r["UAV-01"].ttd_s == 4.0      # first coverage (10, radar) -> first select (14); re-select ignored
    assert r["UAV-02"].ttd_s == 0.0      # selected before coverage counts as instant
    assert r["UAV-03"].ttd_s == 15.0
    assert r["UAV-04"].entered_s is None and r["UAV-04"].ttd_s is None   # never in coverage


def test_detection_score_curve():
    assert detection_score(4.0, "standard") == 1.0
    assert detection_score(15.0, "standard") == pytest.approx(0.5)
    assert detection_score(25.0, "standard") == 0.0
    assert detection_score(None, "standard") == 0.0
    # Harder levels allow more time for the same score
    assert detection_score(15.0, "stress") > detection_score(15.0, "standard") > detection_score(15.0, "guided")


def test_score_detection_uses_run_difficulty_and_skips_unseen_hostiles(events):
    # UAV-01: 1.0, UAV-02: 1.0, UAV-03: 0.5; UAV-04 never in coverage -> not scored
    assert score_detection(events) == pytest.approx(2.5 / 3)


def test_hostile_in_coverage_but_never_selected_scores_zero(events):
    events = [e for e in events if not (e["type"] == "trainee_select" and e["truth_id"] == "UAV-03")]
    assert score_detection(events) == pytest.approx(2.0 / 3)


def test_no_scorable_hostiles_returns_none():
    assert score_detection([{"t": 0, "type": "run_start", "scenario_id": "S", "seed": 1,
                             "difficulty": "standard", "tick_hz": 10}]) is None


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
