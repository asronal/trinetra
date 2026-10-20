"""
TRINETRA — event log (JSONL, one event per line).

Every score, replay and chart is computed from this log, never from UI
state (plan §6.2). The schema is therefore strict: unknown event types,
missing fields, unknown labels/actions and out-of-order timestamps are
rejected when written, not discovered later during scoring.
"""

import json
import math
from pathlib import Path
from typing import Dict, List, Tuple

from .catalog import CLASSES, RESPONSE_ACTIONS, SENSORS

# event type -> required fields (besides "t" and "type")
SCHEMA: Dict[str, Tuple[str, ...]] = {
    "run_start":            ("scenario_id", "seed", "difficulty", "tick_hz"),
    "run_end":              ("duration_s",),
    "truth_spawn":          ("truth_id", "label", "hostile"),
    "truth_despawn":        ("truth_id", "reason"),
    "truth_state":          ("truth_id", "east_m", "north_m", "alt_m", "range_m", "bearing_deg", "radial_speed_mps"),
    "truth_enter_coverage": ("truth_id", "sensor"),
    "truth_exit_coverage":  ("truth_id", "sensor"),
    "degradation_start":    ("sensor", "kind"),
    "degradation_end":      ("sensor", "kind"),
    "sensor_plot":          ("sensor", "range_m", "bearing_deg", "radial_speed_mps", "truth_id"),
    "track_confirm":        ("track_id", "truth_id"),
    "track_drop":           ("track_id",),
    # truth_id on trainee events is resolved by the simulator (None = clutter track)
    "trainee_select":       ("track_id", "truth_id"),
    "trainee_classify":     ("track_id", "truth_id", "label", "hostile"),
    "trainee_respond":      ("track_id", "truth_id", "action"),
    "ai_assessment":        ("track_id", "label", "conf"),
}

_LABELLED = ("truth_spawn", "trainee_classify", "ai_assessment")


class EventError(ValueError):
    """An event does not match the schema."""


def validate_event(event: dict) -> None:
    etype = event.get("type")
    if etype not in SCHEMA:
        raise EventError(f"unknown event type: {etype!r}")

    t = event.get("t")
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
        raise EventError(f"{etype}: 't' must be a finite, non-negative number, got {t!r}")

    missing = [f for f in SCHEMA[etype] if f not in event]
    if missing:
        raise EventError(f"{etype}: missing field(s) {', '.join(missing)}")

    if "sensor" in event and event["sensor"] not in SENSORS:
        raise EventError(f"{etype}: unknown sensor {event['sensor']!r}")
    if etype in _LABELLED and event["label"] not in CLASSES:
        raise EventError(f"{etype}: unknown label {event['label']!r}")
    if etype == "trainee_respond" and event["action"] not in RESPONSE_ACTIONS:
        raise EventError(f"trainee_respond: unknown action {event['action']!r}")


def make_event(t: float, etype: str, **fields) -> dict:
    event = {"t": round(float(t), 3), "type": etype, **fields}
    validate_event(event)
    return event


class EventLog:
    """Append-only JSONL writer. Use as a context manager."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", encoding="utf-8", newline="\n")
        self._last_t = 0.0
        self.count = 0

    def emit(self, t: float, etype: str, **fields) -> dict:
        event = make_event(t, etype, **fields)
        if event["t"] < self._last_t:
            raise EventError(f"{etype}: t={event['t']} is earlier than the previous event (t={self._last_t})")
        self._fh.write(json.dumps(event, separators=(",", ":")) + "\n")
        self._last_t = event["t"]
        self.count += 1
        return event

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def read_events(path) -> List[dict]:
    """Load and validate a JSONL event log."""
    events: List[dict] = []
    last_t = 0.0
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                validate_event(event)
            except (json.JSONDecodeError, EventError) as e:
                raise EventError(f"{path}:{lineno}: {e}") from None
            if event["t"] < last_t:
                raise EventError(f"{path}:{lineno}: events are out of time order")
            last_t = event["t"]
            events.append(event)
    return events
