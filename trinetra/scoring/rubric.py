"""
TRINETRA — scoring rubric (plan §6.3).

Everything is computed from the event log; nothing is read from UI state.

  detect        time from a hostile entering coverage to the trainee selecting it
  classify      last classification of each target: half for the label, half for the hostile flag
  respond       mean ROE credit of the responses on each hostile (scoring/roe.py)
  false_alarms  penalty per non-hostile declared hostile or engaged, and per hostile never responded to
"""

import bisect
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from .roe import HOSTILE_ACTIONS, get_roe, response_credit, threat_state

# Instructors can edit these.
WEIGHTS = {"detect": 0.30, "classify": 0.25, "respond": 0.30, "false_alarms": 0.15}
FALSE_ALARM_PENALTY = 0.25      # per false alarm or missed hostile

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


# ── Full run score ───────────────────────────────────────────────────

@dataclass
class RunScore:
    detect: Optional[float]
    classify: Optional[float]
    respond: Optional[float]
    false_alarms: float
    total: float
    false_alarm_count: int = 0
    missed_hostiles: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)     # plain-language reasons, for the AAR

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ("detect", "classify", "respond", "false_alarms", "total",
                 "false_alarm_count", "missed_hostiles", "notes")}


class _TruthHistory:
    """Latest truth_state at or before a time, per truth id."""

    def __init__(self, events: List[dict]):
        self._t: Dict[str, List[float]] = {}
        self._s: Dict[str, List[dict]] = {}
        for ev in events:
            if ev["type"] == "truth_state":
                self._t.setdefault(ev["truth_id"], []).append(ev["t"])
                self._s.setdefault(ev["truth_id"], []).append(ev)

    def at(self, truth_id: str, t: float) -> Optional[dict]:
        times = self._t.get(truth_id)
        if not times:
            return None
        i = bisect.bisect_right(times, t) - 1
        return self._s[truth_id][max(i, 0)]


def score_run(events: Iterable[dict], difficulty: Optional[str] = None,
              roe_name: Optional[str] = None) -> RunScore:
    events = list(events)
    start = next((e for e in events if e["type"] == "run_start"), None)
    difficulty = difficulty or (start["difficulty"] if start else "standard")
    roe = get_roe(roe_name or (start or {}).get("roe", "standard"))

    truths = {e["truth_id"]: e for e in events if e["type"] == "truth_spawn"}
    detections = time_to_detect(events)
    in_coverage = [tid for tid, r in detections.items() if r.entered_s is not None]
    history = _TruthHistory(events)
    notes: List[str] = []

    # ── Detect ──
    detect = score_detection(events, difficulty)
    for tid in in_coverage:
        r = detections[tid]
        if r.ttd_s is None:
            notes.append(f"{tid}: never selected after entering coverage at {r.entered_s:.1f} s")
        elif detection_score(r.ttd_s, difficulty) < 1.0:
            notes.append(f"{tid}: selected {r.ttd_s:.1f} s after it became detectable")

    # ── Classify (last classification per target wins) ──
    last_class: Dict[str, dict] = {}
    false_alarm_targets = set()
    for ev in events:
        if ev["type"] != "trainee_classify":
            continue
        tid = ev["truth_id"]
        if tid is None:
            if ev["hostile"]:
                false_alarm_targets.add(("track", ev["track_id"]))
                notes.append(f"track {ev['track_id']}: clutter declared hostile at {ev['t']:.1f} s")
            continue
        last_class[tid] = ev

    class_scores = []
    for tid in sorted(set(in_coverage) | set(last_class)):
        truth = truths.get(tid)
        if truth is None:
            continue
        ev = last_class.get(tid)
        if ev is None:
            class_scores.append(0.0)
            notes.append(f"{tid}: hostile never classified")
            continue
        s = 0.5 * (ev["label"] == truth["label"]) + 0.5 * (ev["hostile"] == truth["hostile"])
        class_scores.append(s)
        if ev["label"] != truth["label"]:
            notes.append(f"{tid}: classified as {ev['label']}, was {truth['label']}")
        if ev["hostile"] and not truth["hostile"]:
            false_alarm_targets.add(("truth", tid))
            notes.append(f"{tid}: {truth['label']} declared hostile")
        elif not ev["hostile"] and truth["hostile"]:
            notes.append(f"{tid}: hostile {truth['label']} declared not hostile")
    classify = sum(class_scores) / len(class_scores) if class_scores else None

    # ── Respond ──
    credits: Dict[str, List[float]] = {}
    soft_tried = set()
    wrong_orders: Dict[tuple, List[float]] = {}     # (name, action, what) -> times; one note each
    for ev in events:
        if ev["type"] != "trainee_respond":
            continue
        tid, action = ev["truth_id"], ev["action"]
        truth = truths.get(tid) if tid is not None else None
        if truth is None or not truth["hostile"]:
            if action in HOSTILE_ACTIONS:
                key = ("truth", tid) if tid is not None else ("track", ev["track_id"])
                false_alarm_targets.add(key)
                what = truth["label"] if truth else "clutter"
                name = tid or f"track {ev['track_id']}"
                wrong_orders.setdefault((name, action, what), []).append(ev["t"])
            continue
        state = history.at(tid, ev["t"])
        rng, closing = (state["range_m"], state["radial_speed_mps"]) if state else (float("inf"), 0.0)
        ts = threat_state(True, rng, closing, roe)
        c = response_credit(ts, action, tid in soft_tried)
        credits.setdefault(tid, []).append(c)
        if c < 1.0:
            notes.append(f"{tid}: {action} at {ev['t']:.1f} s ({ts.replace('_', ' ')}, {rng:.0f} m) earned {c:.2f}")
        if action == "simulated_soft_kill":
            soft_tried.add(tid)

    for (name, action, what), times in wrong_orders.items():
        if len(times) == 1:
            notes.append(f"{name}: {action} on {what} at {times[0]:.1f} s")
        else:
            notes.append(f"{name}: {action} on {what} x{len(times)} ({times[0]:.1f}-{times[-1]:.1f} s)")

    missed = [tid for tid in in_coverage if tid not in credits]
    for tid in missed:
        notes.append(f"{tid}: hostile in coverage but never responded to")
    respond_scores = [sum(credits[t]) / len(credits[t]) if t in credits else 0.0 for t in in_coverage]
    respond = sum(respond_scores) / len(respond_scores) if respond_scores else None

    # ── False alarms & misses ──
    fa_count = len(false_alarm_targets)
    false_alarms = max(0.0, 1.0 - FALSE_ALARM_PENALTY * (fa_count + len(missed)))

    parts = {"detect": detect, "classify": classify, "respond": respond, "false_alarms": false_alarms}
    used = {k: v for k, v in parts.items() if v is not None}
    total = sum(WEIGHTS[k] * v for k, v in used.items()) / sum(WEIGHTS[k] for k in used)
    return RunScore(detect, classify, respond, false_alarms, total, fa_count, missed, notes)
