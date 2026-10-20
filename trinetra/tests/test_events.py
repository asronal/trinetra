import json

import pytest

from trinetra.core.events import EventError, EventLog, make_event, read_events, validate_event


def test_make_event_rounds_time_and_keeps_fields():
    ev = make_event(0.30000000000000004, "trainee_select", track_id=3, truth_id="UAV-01")
    assert ev == {"t": 0.3, "type": "trainee_select", "track_id": 3, "truth_id": "UAV-01"}


@pytest.mark.parametrize("event, msg", [
    ({"t": 1.0, "type": "teleport"}, "unknown event type"),
    ({"t": -1.0, "type": "run_end", "duration_s": 1}, "non-negative"),
    ({"t": True, "type": "run_end", "duration_s": 1}, "non-negative"),
    ({"t": 1.0, "type": "trainee_select", "track_id": 3}, "missing field"),
    ({"t": 1.0, "type": "truth_enter_coverage", "truth_id": "A", "sensor": "sonar"}, "unknown sensor"),
    ({"t": 1.0, "type": "trainee_classify", "track_id": 1, "truth_id": "A", "label": "ufo", "hostile": True},
     "unknown label"),
])
def test_invalid_events_are_rejected(event, msg):
    with pytest.raises(EventError, match=msg):
        validate_event(event)


def test_only_simulated_response_actions_are_allowed():
    validate_event({"t": 1.0, "type": "trainee_respond", "track_id": 1, "truth_id": None,
                    "action": "simulated_soft_kill"})
    with pytest.raises(EventError, match="unknown action"):
        validate_event({"t": 1.0, "type": "trainee_respond", "track_id": 1, "truth_id": None, "action": "fire"})


def test_log_writes_one_json_object_per_line_and_reads_back(tmp_path):
    path = tmp_path / "run.jsonl"
    with EventLog(path) as log:
        log.emit(0.0, "run_start", scenario_id="S", seed=1, difficulty="standard", tick_hz=10)
        log.emit(1.5, "trainee_select", track_id=1, truth_id="UAV-01")
        log.emit(2.0, "run_end", duration_s=2.0)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert all(isinstance(json.loads(line), dict) for line in lines)
    assert [e["type"] for e in read_events(path)] == ["run_start", "trainee_select", "run_end"]


def test_log_rejects_events_out_of_time_order(tmp_path):
    with EventLog(tmp_path / "run.jsonl") as log:
        log.emit(5.0, "run_end", duration_s=5.0)
        with pytest.raises(EventError, match="earlier"):
            log.emit(4.0, "run_end", duration_s=4.0)


def test_read_events_reports_file_and_line(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"t": 0, "type": "run_end", "duration_s": 0}\n{"t": 1, "type": "nope"}\n', encoding="utf-8")
    with pytest.raises(EventError, match=r"bad\.jsonl:2"):
        read_events(path)
