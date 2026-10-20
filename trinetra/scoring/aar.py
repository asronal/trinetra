"""
TRINETRA — after-action review timeline.

Turns a run's event log into one row per real air entity: when it was in
the air, when it became detectable, and each trainee decision on it graded
right, partly right or wrong against the truth and the ROE. Like the score,
it is computed only from the log.
"""

from typing import Dict, Iterable, List

from .roe import HOSTILE_ACTIONS, get_roe, response_credit, threat_state
from .rubric import _TruthHistory, time_to_detect

LABEL = {"quad": "quadcopter", "hexa": "hexacopter", "fixed_wing": "fixed-wing drone",
         "fpv": "FPV drone", "bird": "bird", "aircraft": "aircraft"}
ACTION = {"monitor": "Keep watching", "alert_qrt": "Alert reaction team", "hand_off": "Hand over",
          "ignore": "Ignore", "simulated_soft_kill": "Soft kill", "simulated_hard_kill": "Hard kill"}


def timeline(events: Iterable[dict]) -> dict:
    events = list(events)
    start = next((e for e in events if e["type"] == "run_start"), {})
    end_t = next((e["t"] for e in events if e["type"] == "run_end"), events[-1]["t"] if events else 0.0)
    roe = get_roe(start.get("roe", "standard"))
    history = _TruthHistory(events)
    ttd = time_to_detect(events)
    rows: Dict[str, dict] = {}
    clutter: List[dict] = []
    soft_tried = set()

    for ev in events:
        etype, tid, t = ev["type"], ev.get("truth_id"), ev["t"]
        if etype == "truth_spawn":
            rows[tid] = {"id": tid, "label": ev["label"], "name": LABEL[ev["label"]], "hostile": ev["hostile"],
                         "start": t, "end": None, "end_reason": None, "detectable": None, "marks": []}
            continue
        row = rows.get(tid)
        if etype == "truth_despawn" and row:
            row["end"], row["end_reason"] = t, ev["reason"]
        elif etype == "truth_enter_coverage" and row and row["detectable"] is None:
            row["detectable"] = t
        elif etype.startswith("trainee_"):
            mark = _grade(ev, row, history, roe, soft_tried)
            (row["marks"] if row else clutter).append(mark)

    out = []
    for row in rows.values():
        r = ttd.get(row["id"])
        row["time_to_detect_s"] = r.ttd_s if r else None
        if row["end"] is None:
            row["end"] = end_t
        out.append(row)
    return {"duration": end_t, "rows": out, "clutter": clutter}


def _grade(ev: dict, row, history, roe, soft_tried: set) -> dict:
    t, etype = ev["t"], ev["type"]
    who = f"contact {ev['track_id']}"
    if etype == "trainee_select":
        return {"t": t, "kind": "select", "grade": "info", "text": f"Selected {who}"}
    if etype == "trainee_classify":
        said = f"Called it a {LABEL[ev['label']]}, {'hostile' if ev['hostile'] else 'not hostile'}"
        if row is None:
            return {"t": t, "kind": "classify", "grade": "bad" if ev["hostile"] else "info",
                    "text": said + " (it was radar clutter)"}
        right = (ev["label"] == row["label"]) + (ev["hostile"] == row["hostile"])
        grade = "good" if right == 2 else "partial" if right == 1 else "bad"
        truth = f"it was a {row['name']}, {'hostile' if row['hostile'] else 'not hostile'}"
        return {"t": t, "kind": "classify", "grade": grade, "text": said if grade == "good" else f"{said}; {truth}"}
    # trainee_respond
    action = ev["action"]
    text = ACTION[action]
    if row is None or not row["hostile"]:
        bad = action in HOSTILE_ACTIONS
        what = "radar clutter" if row is None else f"a {row['name']} (not hostile)"
        return {"t": t, "kind": "respond", "grade": "bad" if bad else "good",
                "text": f"{text} on {what}" if bad else text}
    state = history.at(row["id"], t)
    rng, closing = (state["range_m"], state["radial_speed_mps"]) if state else (float("inf"), 0.0)
    ts = threat_state(True, rng, closing, roe)
    credit = response_credit(ts, action, row["id"] in soft_tried)
    if action == "simulated_soft_kill":
        soft_tried.add(row["id"])
    grade = "good" if credit >= 1.0 else "partial" if credit > 0 else "bad"
    situation = {"hostile_far": "more than 1 km away", "hostile_close_approaching": "inside 1 km, coming closer",
                 "hostile_close_holding": "inside 1 km, not closing"}[ts]
    return {"t": t, "kind": "respond", "grade": grade, "text": f"{text} at {rng / 1000:.1f} km ({situation})"}
