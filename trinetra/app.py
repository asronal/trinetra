"""
TRINETRA — entry point.

    python -m trinetra.app                                                   # trainer in the browser
    python -m trinetra.app --scenario trinetra/scenarios/smoke.yaml --headless   # no window, log only

The browser trainer runs a local server (127.0.0.1 only) and opens the
page; missions are chosen on its start screen. Headless runs as fast as
the CPU allows and writes the event log. HIL arrives in Phase 3.
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from .config import Config
from .core.scenario import DIFFICULTIES, Scenario, ScenarioError, load_scenario
from .core.session import Session

logger = logging.getLogger("trinetra")


def run_headless(scenario: Scenario, cfg: Config, out_path, difficulty: str = "standard",
                 duration_s: Optional[float] = None, seed: Optional[int] = None,
                 on_tick: Optional[Callable] = None) -> Path:
    """Run one scenario without a console and write its event log. Deterministic for a given seed.

    on_tick(t, world, scan, tracker) is called once per tick after the sensors
    and tracker have run (scan is None on ticks without a radar scan). It must
    not change the world; it is for recording and display.
    """
    s = Session(scenario, cfg, out_path, difficulty, seed, duration_s or cfg.duration_s)
    while True:
        if on_tick is not None:
            scan = s.last_scan if s.last_scan is not None and s.last_scan.t == s.t else None
            on_tick(s.t, s.world, scan, s.tracker)
        if s.done:
            break
        s.step()
    s.finish()
    logger.info("wrote %d events to %s", s.log.count, s.log_path)
    return Path(out_path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="trinetra", description="TRINETRA counter-drone training simulator")
    parser.add_argument("--scenario", help="scenario YAML file (headless mode)")
    parser.add_argument("--difficulty", choices=DIFFICULTIES, default="standard")
    parser.add_argument("--headless", action="store_true", help="run without any interface and only write the log")
    parser.add_argument("--port", type=int, default=8765, help="browser trainer port (default 8765)")
    parser.add_argument("--no-browser", action="store_true", help="start the server without opening a browser")
    parser.add_argument("--hil", action="store_true", help="use live Pi sensors (Phase 3)")
    parser.add_argument("--duration", type=float, default=None, help="run length in seconds (default: scenario, else 60)")
    parser.add_argument("--seed", type=int, default=None, help="override the scenario seed")
    parser.add_argument("--out", default=None, help="event log path (default output/trinetra/<id>_<time>.jsonl)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.hil:
        parser.error("HIL mode arrives in Phase 3")
    if not args.headless:
        from .server.web import serve
        serve(port=args.port, open_browser=not args.no_browser)
        return 0
    if not args.scenario:
        parser.error("--scenario is required with --headless")

    cfg = Config()
    try:
        scenario = load_scenario(args.scenario)
    except (OSError, ScenarioError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    out = args.out or Path(cfg.log_dir) / f"{scenario.id}_{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    duration = args.duration or scenario.duration_s or cfg.duration_s
    print(run_headless(scenario, cfg, out, args.difficulty, duration, args.seed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
