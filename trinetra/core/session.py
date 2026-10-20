"""
TRINETRA — one training run.

A Session owns the world, the emulated sensors, the tracker and the event
log, and advances them one tick at a time. The headless runner and the
trainee console both drive a Session, so the logging rules live in one
place.

Trainee actions (select / classify / respond) are logged with the ground
truth behind the selected track, resolved here and never shown to the
trainee. Engagement outcomes are abstract: a simulated soft or hard kill
on a target within effect range removes it with a fixed probability. No
real effector is modelled.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from ..ai.tracker import Tracker
from ..config import Config
from ..scoring.roe import get_roe
from ..scoring.rubric import RunScore, score_run
from ..sensors.ir import EmulatedIR
from ..sensors.radar import EmulatedRadar
from .catalog import CLASSES, RESPONSE_ACTIONS
from .events import EventLog, read_events
from .scenario import Scenario, build_world
from .world import ACTIVE, GONE

# Simulated engagement outcomes (abstract training values)
EFFECT_RANGE_M = 1000.0
KILL_PROBABILITY = {"simulated_soft_kill": 0.7, "simulated_hard_kill": 0.9}
# The same order on the same track within this window is refused, so a held
# or mashed key cannot fire a burst of orders (seen in the first playtest).
REPEAT_GUARD_S = 3.0


class ActionError(ValueError):
    """A trainee action that cannot be applied (no track selected, unknown label, ...)."""


@dataclass
class ActionResult:
    event: dict
    message: str
    outcome: Optional[str] = None     # kills only: "down" | "no_effect" | "out_of_range"


@dataclass
class Contact:
    """The trainee's own record of a track: what they called it and what they ordered."""
    label: Optional[str] = None
    hostile: Optional[bool] = None
    actions: List[str] = field(default_factory=list)


class Session:
    def __init__(self, scenario: Scenario, cfg: Config, log_path, difficulty: str = "standard",
                 seed: Optional[int] = None, duration_s: Optional[float] = None, with_ir: bool = False):
        self.scenario = scenario
        self.cfg = cfg
        self.difficulty = difficulty
        self.seed = scenario.seed if seed is None else seed
        self.duration_s = duration_s or scenario.duration_s or cfg.duration_s
        get_roe(scenario.roe)                   # fail before the run, not while scoring it

        # Separate random streams, so adding the camera or trainee actions never
        # changes what the radar sees for a given seed.
        self.world = build_world(scenario, tick_hz=cfg.tick_hz)
        self.radar = EmulatedRadar(cfg.radar, np.random.default_rng(self.seed), scenario.degradation)
        self.tracker = Tracker(cfg.tracker, cfg.radar.range_sigma_m, cfg.radar.bearing_sigma_deg)
        self.ir = (EmulatedIR(cfg.ir, np.random.default_rng(self.seed + 1), scenario.time_of_day,
                              scenario.terrain, fog=float(scenario.weather.get("fog", 0.0)),
                              degradations=scenario.degradation) if with_ir else None)
        self._effects_rng = np.random.default_rng(self.seed + 2)

        self.log = EventLog(log_path)
        self.n_ticks = round(self.duration_s * cfg.tick_hz)
        self._state_every = max(1, round(cfg.tick_hz / cfg.truth_state_hz))
        self._covered = set()
        self._degraded = set()
        self.last_scan = None
        self.last_ir = None
        self.selected: Optional[int] = None
        self.contacts: Dict[int, Contact] = {}
        self.downed: set = set()                # truth ids taken down by a simulated kill
        self._last_order: Dict[tuple, float] = {}
        self.finished = False
        self.score: Optional[RunScore] = None

        self.radar.initialize()
        self.log.emit(0.0, "run_start", scenario_id=scenario.id, seed=self.seed,
                      difficulty=difficulty, tick_hz=cfg.tick_hz, roe=scenario.roe)
        self._process(self.world.start())

    @property
    def t(self) -> float:
        return self.world.t

    @property
    def done(self) -> bool:
        return self.world.clock.tick >= self.n_ticks

    # ── Simulation ────────────────────────────────────────────────
    def step(self, sense_ir: bool = True) -> None:
        """Advance one tick (no-op once the run's duration is reached).

        sense_ir=False skips the thermal render, for catch-up ticks the
        console will not display anyway (fast-forward).
        """
        if self.done or self.finished:
            return
        self._process(self.world.step(), sense_ir)

    def _process(self, changes, sense_ir: bool = True) -> None:
        t, log, world = self.t, self.log, self.world
        for ch in changes:
            e = ch.entity
            if ch.kind == "spawn":
                log.emit(t, "truth_spawn", truth_id=e.id, label=e.label, hostile=e.hostile)
            else:
                log.emit(t, "truth_despawn", truth_id=e.id, reason=ch.reason)

        for i, d in enumerate(self.scenario.degradation):
            if d.active(t) and i not in self._degraded:
                self._degraded.add(i)
                log.emit(t, "degradation_start", sensor=d.sensor, kind=d.kind)
            elif not d.active(t) and i in self._degraded:
                self._degraded.discard(i)
                log.emit(t, "degradation_end", sensor=d.sensor, kind=d.kind)

        if world.clock.tick % self._state_every == 0:
            for e in world.active():
                log.emit(t, "truth_state", truth_id=e.id, east_m=round(e.pos[0], 1),
                         north_m=round(e.pos[1], 1), alt_m=round(e.pos[2], 1),
                         range_m=round(e.slant_range_m, 1), bearing_deg=round(e.bearing_deg, 2),
                         radial_speed_mps=round(e.radial_speed_mps, 2))

        self._update_coverage()

        scan = self.radar.read(world, t)
        if scan is not None:
            self.last_scan = scan
            for p in scan.plots:
                log.emit(t, "sensor_plot", sensor="radar", range_m=round(p.range_m, 1),
                         bearing_deg=round(p.bearing_deg, 2),
                         radial_speed_mps=round(p.radial_speed_mps, 2), truth_id=p.truth_id)
            upd = self.tracker.update(scan.plots, t)
            for tr in upd.confirmed:
                log.emit(t, "track_confirm", track_id=tr.id, truth_id=tr.truth_id)
            for tr in upd.dropped:
                log.emit(t, "track_drop", track_id=tr.id)
                if tr.id == self.selected:
                    self.selected = None

        if self.ir is not None and sense_ir:
            frame = self.ir.read(world, t)
            if frame is not None:
                self.last_ir = frame

    def _update_coverage(self) -> None:
        now = {e.id for e in self.world.active() if self.radar.in_coverage(e)}
        for tid in sorted(now - self._covered):
            self.log.emit(self.t, "truth_enter_coverage", truth_id=tid, sensor="radar")
        for tid in sorted(self._covered - now):
            self.log.emit(self.t, "truth_exit_coverage", truth_id=tid, sensor="radar")
        self._covered = now

    # ── Trainee actions ───────────────────────────────────────────
    def _track(self, track_id: Optional[int]):
        tr = self.tracker.get(track_id) if track_id is not None else None
        if tr is None or tr.status != "confirmed":
            raise ActionError("select a confirmed track first")
        return tr

    def select(self, track_id: int) -> ActionResult:
        tr = self._track(track_id)
        self.selected = tr.id
        ev = self.log.emit(self.t, "trainee_select", track_id=tr.id, truth_id=tr.truth_id)
        return ActionResult(ev, f"Track {tr.id} selected")

    def classify(self, label: str, hostile: bool) -> ActionResult:
        if label not in CLASSES:
            raise ActionError(f"unknown class {label!r}")
        tr = self._track(self.selected)
        ev = self.log.emit(self.t, "trainee_classify", track_id=tr.id, truth_id=tr.truth_id,
                           label=label, hostile=bool(hostile))
        c = self.contacts.setdefault(tr.id, Contact())
        c.label, c.hostile = label, bool(hostile)
        return ActionResult(ev, f"Track {tr.id}: {label.replace('_', ' ')}, {'hostile' if hostile else 'not hostile'}")

    def is_down(self, track_id: int) -> bool:
        tr = self.tracker.get(track_id)
        return tr is not None and tr.truth_id is not None and tr.truth_id in self.downed

    def respond(self, action: str) -> ActionResult:
        if action not in RESPONSE_ACTIONS:
            raise ActionError(f"unknown action {action!r}")
        tr = self._track(self.selected)
        if self.is_down(tr.id):
            raise ActionError(f"track {tr.id} is already down")
        last = self._last_order.get((tr.id, action))
        if last is not None and self.t - last < REPEAT_GUARD_S:
            raise ActionError(f"already ordered on track {tr.id}; wait for the result")
        self._last_order[(tr.id, action)] = self.t
        ev = self.log.emit(self.t, "trainee_respond", track_id=tr.id, truth_id=tr.truth_id, action=action)
        self.contacts.setdefault(tr.id, Contact()).actions.append(action)
        message = f"Track {tr.id}: {action.replace('_', ' ')}"
        outcome = None
        if action in KILL_PROBABILITY:
            outcome = self._apply_effect(tr, action)
            message += {"out_of_range": " (out of effect range, no effect)", "no_effect": " (no effect)",
                        "down": " (target down)"}[outcome]
        return ActionResult(ev, message, outcome)

    def _apply_effect(self, tr, action: str) -> str:
        if tr.range_m > EFFECT_RANGE_M:
            return "out_of_range"
        target = next((e for e in self.world.entities if e.id == tr.truth_id and e.state == ACTIVE), None)
        if target is None or self._effects_rng.random() >= KILL_PROBABILITY[action]:
            return "no_effect"
        target.state = GONE
        self.downed.add(target.id)
        self.log.emit(self.t, "truth_despawn", truth_id=target.id, reason="neutralised_simulated")
        self._update_coverage()
        return "down"

    # ── End ───────────────────────────────────────────────────────
    def finish(self) -> RunScore:
        """Close the log and score the run. Safe to call more than once."""
        if not self.finished:
            self.log.emit(self.t, "run_end", duration_s=self.t)
            self.log.close()
            self.radar.release()
            self.finished = True
            self.score = score_run(read_events(self.log.path))
        return self.score

    @property
    def log_path(self) -> Path:
        return self.log.path
