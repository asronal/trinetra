"""
TRINETRA — entry point.

    python -m trinetra.app --scenario trinetra/scenarios/smoke.yaml --headless

Phase 0 runs headless only: the world, the emulated radar and the event
log, as fast as the CPU allows. The trainee console arrives in Phase 1
and HIL in Phase 3.
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

from .ai.tracker import Tracker
from .config import Config
from .core.events import EventLog
from .core.scenario import DIFFICULTIES, Scenario, ScenarioError, build_world, load_scenario
from .scoring.roe import get_roe
from .sensors.radar import EmulatedRadar

logger = logging.getLogger("trinetra")


def run_headless(scenario: Scenario, cfg: Config, out_path, difficulty: str = "standard",
                 duration_s: Optional[float] = None, seed: Optional[int] = None) -> Path:
    """Run one scenario without a console and write its event log. Deterministic for a given seed."""
    seed = scenario.seed if seed is None else seed
    duration_s = cfg.duration_s if duration_s is None else duration_s
    rng = np.random.default_rng(seed)

    get_roe(scenario.roe)       # fail before the run, not while scoring it
    world = build_world(scenario, tick_hz=cfg.tick_hz)
    radar = EmulatedRadar(cfg.radar, rng, scenario.degradation)
    tracker = Tracker(cfg.tracker, cfg.radar.range_sigma_m, cfg.radar.bearing_sigma_deg)
    n_ticks = round(duration_s * cfg.tick_hz)
    state_every = max(1, round(cfg.tick_hz / cfg.truth_state_hz))
    covered = set()        # truth ids currently in radar coverage
    degraded = set()       # indices of active degradations

    radar.initialize()
    try:
        with EventLog(out_path) as log:
            log.emit(0.0, "run_start", scenario_id=scenario.id, seed=seed,
                     difficulty=difficulty, tick_hz=cfg.tick_hz, roe=scenario.roe)
            changes = world.start()
            while True:
                t = world.t

                for ch in changes:
                    e = ch.entity
                    if ch.kind == "spawn":
                        log.emit(t, "truth_spawn", truth_id=e.id, label=e.label, hostile=e.hostile)
                    else:
                        log.emit(t, "truth_despawn", truth_id=e.id, reason=ch.reason)

                for i, d in enumerate(scenario.degradation):
                    if d.active(t) and i not in degraded:
                        degraded.add(i)
                        log.emit(t, "degradation_start", sensor=d.sensor, kind=d.kind)
                    elif not d.active(t) and i in degraded:
                        degraded.discard(i)
                        log.emit(t, "degradation_end", sensor=d.sensor, kind=d.kind)

                if world.clock.tick % state_every == 0:
                    for e in world.active():
                        log.emit(t, "truth_state", truth_id=e.id, east_m=round(e.pos[0], 1),
                                 north_m=round(e.pos[1], 1), alt_m=round(e.pos[2], 1),
                                 range_m=round(e.slant_range_m, 1), bearing_deg=round(e.bearing_deg, 2),
                                 radial_speed_mps=round(e.radial_speed_mps, 2))

                now_covered = {e.id for e in world.active() if radar.in_coverage(e)}
                for tid in sorted(now_covered - covered):
                    log.emit(t, "truth_enter_coverage", truth_id=tid, sensor="radar")
                for tid in sorted(covered - now_covered):
                    log.emit(t, "truth_exit_coverage", truth_id=tid, sensor="radar")
                covered = now_covered

                scan = radar.read(world, t)
                if scan is not None:
                    for p in scan.plots:
                        log.emit(t, "sensor_plot", sensor="radar", range_m=round(p.range_m, 1),
                                 bearing_deg=round(p.bearing_deg, 2),
                                 radial_speed_mps=round(p.radial_speed_mps, 2), truth_id=p.truth_id)
                    upd = tracker.update(scan.plots, t)
                    for tr in upd.confirmed:
                        log.emit(t, "track_confirm", track_id=tr.id, truth_id=tr.truth_id)
                    for tr in upd.dropped:
                        log.emit(t, "track_drop", track_id=tr.id)

                if world.clock.tick >= n_ticks:
                    break
                changes = world.step()

            log.emit(t, "run_end", duration_s=t)
            logger.info("wrote %d events to %s", log.count, log.path)
    finally:
        radar.release()
    return Path(out_path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="trinetra", description="TRINETRA counter-drone training simulator")
    parser.add_argument("--scenario", required=True, help="scenario YAML file")
    parser.add_argument("--difficulty", choices=DIFFICULTIES, default="standard")
    parser.add_argument("--headless", action="store_true", help="run without the console (Phase 0: required)")
    parser.add_argument("--hil", action="store_true", help="use live Pi sensors (Phase 3)")
    parser.add_argument("--duration", type=float, default=None, help="run length in seconds (default 60)")
    parser.add_argument("--seed", type=int, default=None, help="override the scenario seed")
    parser.add_argument("--out", default=None, help="event log path (default output/trinetra/<id>_<time>.jsonl)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.hil:
        parser.error("HIL mode arrives in Phase 3")
    if not args.headless:
        parser.error("the trainee console arrives in Phase 1; run with --headless for now")

    cfg = Config()
    try:
        scenario = load_scenario(args.scenario)
    except (OSError, ScenarioError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    out = args.out or Path(cfg.log_dir) / f"{scenario.id}_{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    path = run_headless(scenario, cfg, out, args.difficulty, args.duration, args.seed)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
