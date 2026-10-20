"""
TRINETRA — simulation runner for the web interface.

SimRunner owns the current Session and advances it in real time on a
background thread. The web server reads `state()` about ten times a second
and passes trainee actions to `act()`. Everything shared goes through one
lock, so the simulation thread and the request threads never see a
half-updated session.
"""

import math
import threading
import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional

import cv2

from ..config import Config
from ..core.catalog import CLASSES, RESPONSE_ACTIONS
from ..core.events import read_events
from ..core.scenario import load_scenario
from ..scoring.aar import timeline
from ..core.session import EFFECT_RANGE_M, ActionError, Session
from ..scoring.roe import get_roe
from ..sensors.ir import CAMERA_HEIGHT_M

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "scenarios"
ASSUMED_ALT_M = 60.0          # the radar gives no height; the cameras assume this
SPEEDS = (1, 2, 4)
# Video tracker: within this range the cameras lock on to the target itself
# instead of pointing where the radar says (radar bearing is only good to ~1°,
# a lot at high zoom). Emulator values.
LOCK_RANGE_M = {"day": 2500.0, "dusk": 1800.0, "night": 1200.0}
MODES = ("guided", "standard")

COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]

ACTION_TEXT = {
    "monitor": "Keeping watch on Contact {id}",
    "alert_qrt": "Reaction team alerted for Contact {id}",
    "hand_off": "Contact {id} handed over to the next unit",
    "ignore": "Ignoring Contact {id}",
    "simulated_soft_kill": "Soft kill (simulated) on Contact {id}",
    "simulated_hard_kill": "Hard kill (simulated) on Contact {id}",
}
OUTCOME_TEXT = {"down": ": target down", "no_effect": ": no effect, try again or escalate",
                "out_of_range": ": too far, no effect (must be inside 1 km)"}
LABEL_TEXT = {"quad": "quadcopter", "hexa": "hexacopter", "fixed_wing": "fixed-wing drone",
              "fpv": "FPV racing drone", "bird": "bird", "aircraft": "aircraft"}


def compass(bearing_deg: float) -> str:
    return COMPASS[int(((bearing_deg % 360) + 22.5) // 45) % 8]


def list_scenarios() -> List[dict]:
    out = []
    for path in sorted(SCENARIO_DIR.glob("*.yaml")):
        if path.stem == "smoke":
            continue
        sc = load_scenario(path)
        out.append({"file": path.name, "id": sc.id, "title": sc.title or sc.id, "briefing": sc.briefing,
                    "terrain": sc.terrain, "time_of_day": sc.time_of_day, "duration_s": sc.duration_s})
    return out


class SimRunner:
    def __init__(self, cfg: Optional[Config] = None, log_dir="output/trinetra", realtime: bool = True):
        self.cfg = cfg or Config()
        self.log_dir = Path(log_dir)
        self.lock = threading.RLock()
        self.session: Optional[Session] = None
        self.status = "menu"                 # menu | briefing | running | paused | done
        self.mode = "guided"
        self.instructor = False
        self.speed = 1
        self.trim = [0.0, 0.0]               # camera trim (az, el) relative to the cue, degrees
        self.locked = False                  # cameras locked on to the selected target
        self.messages: deque = deque(maxlen=8)
        self._msg_id = 0
        self._seen_tracks: set = set()
        self._scans: deque = deque(maxlen=3)
        self._ir_cache = (None, b"")
        self._ticks = 0
        self._stop = threading.Event()
        self._thread = None
        if realtime:
            self._thread = threading.Thread(target=self._loop, name="trinetra-sim", daemon=True)
            self._thread.start()

    # ── Lifecycle ─────────────────────────────────────────────────
    def close(self) -> None:
        self._stop.set()
        with self.lock:
            if self.session is not None and not self.session.finished:
                self.session.finish()

    def say(self, text: str, kind: str = "info") -> None:
        self._msg_id += 1
        t = self.session.t if self.session else 0.0
        self.messages.append({"id": self._msg_id, "t": round(t, 1), "text": text, "kind": kind})

    def _loop(self) -> None:
        tick = 1.0 / self.cfg.tick_hz
        next_t = time.perf_counter()
        while not self._stop.is_set():
            now = time.perf_counter()
            if now < next_t:
                time.sleep(min(next_t - now, 0.02))
                continue
            next_t = max(next_t + tick, now - 0.5)          # never try to catch up more than 0.5 s
            with self.lock:
                if self.status == "running":
                    self.advance(self.speed)

    def advance(self, ticks: int) -> None:
        """Advance the simulation by `ticks` ticks (caller holds no lock or the lock)."""
        with self.lock:
            s = self.session
            for i in range(ticks):
                if s is None or s.done:
                    break
                self._aim()
                before = s.selected
                last_scan = s.last_scan
                # Thermal at 5 Hz, and only on the last tick of a fast-forward batch
                s.step(sense_ir=(i == ticks - 1 and self._ticks % 2 == 0))
                self._ticks += 1
                if s.last_scan is not last_scan and s.last_scan is not None:
                    self._scans.append(s.last_scan)
                if before is not None and s.selected is None:
                    self.say(f"Lost Contact {before} on radar. Select it again when it comes back.", "warn")
                for tr in s.tracker.confirmed:
                    if tr.id not in self._seen_tracks:
                        self._seen_tracks.add(tr.id)
                        self.say(f"New contact: Contact {tr.id}, {tr.range_m / 1000:.1f} km {compass(tr.bearing_deg)}",
                                 "new")
            if s is not None and s.done and self.status in ("running", "paused"):
                self._finish()

    def _aim(self) -> None:
        s = self.session
        if s is None or s.ir is None:
            return
        tr = s.tracker.get(s.selected) if s.selected else None
        self.locked = False
        if tr is None:
            return
        target = self._lock_target(tr)
        if target is not None:
            self.locked = True
            el = math.degrees(math.atan2(target.pos[2] - CAMERA_HEIGHT_M, max(target.ground_range_m, 1.0)))
            s.ir.point(target.bearing_deg + self.trim[0], el + self.trim[1])
        else:
            el = math.degrees(math.atan2(ASSUMED_ALT_M - CAMERA_HEIGHT_M, max(tr.range_m, 1.0)))
            s.ir.point(tr.bearing_deg + self.trim[0], el + self.trim[1])

    def _lock_target(self, tr):
        """The entity the video tracker can lock on to for this track, or None."""
        s = self.session
        if tr.truth_id is None:                  # clutter: nothing there to lock on to
            return None
        if any(d.sensor in ("eo", "ir") and d.kind in ("dropout", "jamming") and d.active(s.t)
               for d in s.scenario.degradation):
            return None
        ent = next((e for e in s.world.active() if e.id == tr.truth_id), None)
        if ent is None or ent.slant_range_m > LOCK_RANGE_M[s.scenario.time_of_day]:
            return None
        return ent

    def _finish(self) -> None:
        self.session.finish()
        self.status = "done"
        self.say("Run complete", "good")

    # ── Actions ───────────────────────────────────────────────────
    def act(self, a: dict) -> dict:
        kind = a.get("type")
        with self.lock:
            try:
                msg = self._act(kind, a)
                return {"ok": True, "message": msg}
            except ActionError as e:
                text = str(e)
                text = text[0].upper() + text[1:]
                text = text.replace("track ", "Contact ")
                self.say(text, "error")
                return {"ok": False, "error": text}

    def _act(self, kind: str, a: dict) -> Optional[str]:
        if kind == "start":
            return self._start(a.get("scenario", ""), a.get("mode", "guided"))
        if kind == "menu":
            if self.session is not None and not self.session.finished:
                self.session.finish()
            self.status = "menu"
            return None
        s = self._need_session()
        if kind == "begin":
            if self.status == "briefing":
                self.status = "running"
                self.say("Run started. Watch the radar for contacts.", "good")
            return None
        if kind == "pause":
            if self.status == "running":
                self.status = "paused"
            elif self.status == "paused":
                self.status = "running"
            return None
        if kind == "speed":
            v = int(a.get("value", 1))
            if v not in SPEEDS:
                raise ActionError(f"speed must be one of {SPEEDS}")
            self.speed = v
            return None
        if kind == "instructor":
            self.instructor = bool(a.get("on"))
            return None
        if kind == "end":
            if self.status in ("running", "paused", "briefing"):
                self._finish()
            return None
        if kind == "skip":                       # fast-forward (demos and tests)
            self.advance(int(round(float(a.get("seconds", 0)) * self.cfg.tick_hz)))
            return None
        if kind == "camera":
            self._camera(float(a.get("daz", 0.0)), float(a.get("del", 0.0)))
            return None
        if kind == "camera_reset":
            self.trim = [0.0, 0.0]
            return None
        if self.status not in ("running", "paused"):
            raise ActionError("the run is not in progress")
        if kind == "select":
            res = s.select(int(a.get("track_id", -1)))
            self.trim = [0.0, 0.0]
            self._aim()
            msg = f"Contact {res.event['track_id']} selected. The cameras are turning to it."
        elif kind == "classify":
            label = a.get("label")
            if label not in CLASSES:
                raise ActionError(f"unknown type {label!r}")
            res = s.classify(label, bool(a.get("hostile")))
            msg = (f"Contact {res.event['track_id']} marked as {LABEL_TEXT[label]}, "
                   f"{'hostile' if res.event['hostile'] else 'not hostile'}")
        elif kind == "respond":
            action = a.get("action")
            if action not in RESPONSE_ACTIONS:
                raise ActionError(f"unknown response {action!r}")
            res = s.respond(action)
            msg = ACTION_TEXT[action].format(id=res.event["track_id"]) + OUTCOME_TEXT.get(res.outcome, "")
        else:
            raise ActionError(f"unknown action {kind!r}")
        kind_ = "good" if getattr(res, "outcome", None) == "down" else "info"
        self.say(msg, kind_)
        return msg

    def _need_session(self) -> Session:
        if self.session is None:
            raise ActionError("start a scenario first")
        return self.session

    def _start(self, file: str, mode: str) -> str:
        path = (SCENARIO_DIR / file).resolve()
        if path.parent != SCENARIO_DIR or not path.exists():
            raise ActionError(f"unknown scenario {file!r}")
        if mode not in MODES:
            raise ActionError(f"mode must be one of {MODES}")
        if self.session is not None and not self.session.finished:
            self.session.finish()
        sc = load_scenario(path)
        out = self.log_dir / f"{sc.id}_{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        self.session = Session(sc, self.cfg, out, "guided" if mode == "guided" else "standard", with_ir=True)
        self.mode = mode
        self.status = "briefing"
        self.speed = 1
        self.trim = [0.0, 0.0]
        self.messages.clear()
        self._seen_tracks = set()
        self._scans.clear()
        self._ir_cache = (None, b"")
        self._ticks = 0
        self.session.step()                      # render a first thermal frame for the briefing
        return f"Loaded {sc.title or sc.id}"

    def _camera(self, daz: float, del_: float) -> None:
        s = self._need_session()
        if s.ir is None:
            return
        if s.selected is not None and s.tracker.get(s.selected) is not None:
            self.trim = [self.trim[0] + daz, max(-20.0, min(40.0, self.trim[1] + del_))]
            self._aim()
        else:
            s.ir.point(s.ir.az_deg + daz, s.ir.el_deg + del_)

    # ── Views ─────────────────────────────────────────────────────
    def aar(self) -> Optional[dict]:
        """After-action timeline of the finished mission, or None while one is running."""
        with self.lock:
            s = self.session
            if s is None or not s.finished:
                return None
            return timeline(read_events(s.log_path))

    def thermal_jpeg(self) -> Optional[bytes]:
        with self.lock:
            s = self.session
            if s is None or s.last_ir is None or s.last_ir.image is None:
                return None
            if self._ir_cache[0] != s.last_ir.t:
                ok, buf = cv2.imencode(".jpg", s.last_ir.image, [cv2.IMWRITE_JPEG_QUALITY, 85])
                self._ir_cache = (s.last_ir.t, buf.tobytes() if ok else b"")
            return self._ir_cache[1]

    def state(self) -> dict:
        with self.lock:
            s = self.session
            base = {"status": self.status, "mode": self.mode, "instructor": self.instructor,
                    "speed": self.speed, "speeds": list(SPEEDS), "messages": list(self.messages)}
            if s is None:
                return base
            sc = s.scenario
            roe = get_roe(sc.roe)
            active_deg = [{"sensor": d.sensor, "kind": d.kind} for d in sc.degradation if d.active(s.t)]
            tracks = []
            for tr in s.tracker.confirmed:
                c = s.contacts.get(tr.id)
                closing = -(tr.x[0] * tr.x[2] + tr.x[1] * tr.x[3]) / max(tr.range_m, 1.0)
                if s.is_down(tr.id):
                    status = "down"
                elif c is not None and c.hostile is not None:
                    status = "hostile" if c.hostile else "not_hostile"
                else:
                    status = "unknown"
                tracks.append({
                    "id": tr.id, "e": round(tr.east, 1), "n": round(tr.north, 1),
                    "ve": round(float(tr.x[2]), 2), "vn": round(float(tr.x[3]), 2),
                    "range": round(tr.range_m), "bearing": round(tr.bearing_deg, 1),
                    "direction": compass(tr.bearing_deg), "speed": round(tr.speed_mps, 1),
                    "closing": round(closing, 1), "status": status,
                    "label": c.label if c else None, "hostile": c.hostile if c else None,
                    "actions": list(c.actions) if c else [],
                })
            entities = [{"id": e.id, "label": e.label, "e": round(e.pos[0], 2), "n": round(e.pos[1], 2),
                         "u": round(e.pos[2], 2), "ve": round(e.vel[0], 2), "vn": round(e.vel[1], 2),
                         "vu": round(e.vel[2], 2),
                         "hostile": e.hostile if self.instructor or self.status == "done" else None}
                        for e in s.world.active()]
            plots = [[round(p.range_m * math.sin(math.radians(p.bearing_deg)), 1),
                      round(p.range_m * math.cos(math.radians(p.bearing_deg)), 1), round(s.t - sc_.t, 1)]
                     for sc_ in self._scans for p in sc_.plots]
            ir = s.ir
            state = {
                **base,
                "t": round(s.t, 2), "duration": s.duration_s,
                "scenario": {"id": sc.id, "title": sc.title or sc.id, "briefing": sc.briefing,
                             "terrain": sc.terrain, "time_of_day": sc.time_of_day,
                             "fog": float(sc.weather.get("fog", 0.0)), "roe": sc.roe},
                "rules": {"engage_m": roe.engage_range_m, "effect_m": EFFECT_RANGE_M,
                          "approach_mps": roe.approach_mps},
                "radar": {"status": s.last_scan.status if s.last_scan else "ok", "plots": plots,
                          "scan_s": self.cfg.radar.scan_period_s, "r50_m": self.cfg.radar.ref_range_m},
                "camera": {"az": round(ir.az_deg, 2) if ir else 0.0, "el": round(ir.el_deg, 2) if ir else 0.0,
                           "height_m": CAMERA_HEIGHT_M, "assumed_alt_m": ASSUMED_ALT_M,
                           "locked": self.locked and s.selected is not None,
                           "lock_range_m": LOCK_RANGE_M[sc.time_of_day],
                           "ir_t": s.last_ir.t if s.last_ir else None,
                           "ir_status": s.last_ir.status if s.last_ir else "starting",
                           "ir_hfov": self.cfg.ir.hfov_deg},
                "degradations": active_deg,
                "tracks": tracks,
                "selected": s.selected,
                "entities": entities,
            }
            if self.status == "done" and s.score is not None:
                state["score"] = s.score.as_dict()
                state["log"] = str(s.log_path)
            return state
