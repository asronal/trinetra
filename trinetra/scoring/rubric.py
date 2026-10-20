"""
TRINETRA — scoring rubric (plan §6.3).

Phase 0 implements time to detect. Everything is computed from the event
log; nothing is read from UI state.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, Optional

# Instructors can edit these.
WEIGHTS = {"detect": 0.30, "classify": 0.25, "respond": 0.30, "false_alarms": 0.15}

# (full-marks time, zero-marks time) in seconds. Harder levels allow more
# time, so scores stay comparable as the adaptive difficulty ramps up.
DETECT_TARGETS_S = {
    "guided":   (3.0, 15.0),
    "standard": (5.0, 25.0),
    "stress":   (8.0, 40.0),
    "swarm":    (8.0, 40.0),
}


@dataclass
class DetectionResult:
    truth_id: str
    label: str
    entered_s: Optional[float] = None    # first truth_enter_coverage, any sensor
    selected_s: Optional[float] = None   # first trainee_select of this truth

    @property
    def ttd_s(self) -> Optional[float]:
        if self.entered_s is None or self.selected_s is None:
            return None
        # Selected before the sensors could see it (e.g. a visual call) counts as instant.
        return max(0.0, self.selected_s - self.entered_s)


def time_to_detect(events: Iterable[dict]) -> Dict[str, DetectionResult]:
    """Per-hostile detection timing, keyed by truth_id."""
    results: Dict[str, DetectionResult] = {}
    for ev in events:
        etype = ev["type"]
        if etype == "truth_spawn" and ev["hostile"]:
            results[ev["truth_id"]] = DetectionResult(ev["truth_id"], ev["label"])
        elif etype == "truth_enter_coverage":
            r = results.get(ev["truth_id"])
            if r is not None and r.entered_s is None:
                r.entered_s = ev["t"]
        elif etype == "trainee_select":
            r = results.get(ev["truth_id"])
            if r is not None and r.selected_s is None:
                r.selected_s = ev["t"]
    return results


def detection_score(ttd_s: Optional[float], difficulty: str = "standard") -> float:
    """1.0 at or under the full-marks time, 0.0 at the zero-marks time or if never detected."""
    if ttd_s is None:
        return 0.0
    good, bad = DETECT_TARGETS_S[difficulty]
    if ttd_s <= good:
        return 1.0
    if ttd_s >= bad:
        return 0.0
    return 1.0 - (ttd_s - good) / (bad - good)


def score_detection(events: Iterable[dict], difficulty: Optional[str] = None) -> Optional[float]:
    """Mean detection score over hostiles that entered coverage.

    Hostiles that never entered coverage are not scored (the trainee could
    not have seen them). Returns None if no hostile was scorable.
    """
    events = list(events)
    if difficulty is None:
        start = next((e for e in events if e["type"] == "run_start"), None)
        difficulty = start["difficulty"] if start else "standard"
    scorable = [r for r in time_to_detect(events).values() if r.entered_s is not None]
    if not scorable:
        return None
    return sum(detection_score(r.ttd_s, difficulty) for r in scorable) / len(scorable)
