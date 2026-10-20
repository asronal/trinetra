# TRINETRA

AI-Enabled Drone & Counter-Drone Threat Simulation Trainer. Smart India Hackathon 2026, PS SIH26247, Team SkyNetics.

Training simulator only: no real weapon, jammer, EW or C2 interfaces. See [TRINETRA_DEV_PLAN.md](TRINETRA_DEV_PLAN.md) for the full plan.

## Setup (Windows, PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

On Linux/macOS, activate with `source .venv/bin/activate`.

## Play a scenario

```powershell
python -m trinetra.app --scenario trinetra/scenarios/scn01_day_single.yaml
```

A window opens on the briefing; press Space to start. Click a track on the radar scope (or press Tab) and the thermal camera slews to it. At the end you get a score breakdown with the reasons points were lost, and the event log is saved under `output/trinetra/`.

| Keys | Action |
|---|---|
| Click / Tab | Select a track |
| 1–6, then H or N | Classify (quad, hexa, fixed wing, FPV, bird, aircraft) as hostile / not hostile |
| M Q O I | Monitor, alert QRT, hand off, ignore |
| K, X X | Simulated soft kill, simulated hard kill (press X twice) |
| W A S D, R | Trim the camera (the radar gives no height, so it assumes 60 m), reset |
| Space, + −, T, Esc | Pause, speed, instructor truth view, end run |

| Scenario | What it trains |
|---|---|
| `scn01_day_single.yaml` | The basic loop: one quad by day, one bird |
| `scn02_dusk_decoys.yaml` | A fast FPV among a friendly hexacopter and birds; radar dropout |
| `scn03_night_jam.yaml` | Recce fixed-wing to hand off, then a quad attack under radar jamming |
| `smoke.yaml` | CI smoke test |

`--instructor` starts with ground truth shown. `--headless` runs without a window as fast as possible and only writes the log. Other options: `--difficulty guided|standard|stress|swarm`, `--duration 60`, `--seed N`, `--out path.jsonl`.

```powershell
python -m pytest trinetra -q
```

## Layout

| Path | What it does |
|---|---|
| `trinetra/app.py` | Entry point; headless run loop |
| `trinetra/config.py` | Tick rate, run length, radar emulator settings |
| `trinetra/core/catalog.py` | Target classes (RCS, defaults) and the allowed simulated response actions |
| `trinetra/core/events.py` | Event-log schema, JSONL writer and reader |
| `trinetra/core/world.py` | World model: entities, geometry, 10 Hz clock |
| `trinetra/core/behaviours.py` | Straight line and attack run |
| `trinetra/core/scenario.py` | Scenario YAML loader and world builder |
| `trinetra/sensors/radar.py` | Emulated radar: Pd vs RCS/range, noise, clutter, jamming, dropout; LD2450-compatible plots |
| `trinetra/sensors/ir.py` | Emulated thermal camera: sky/ground, drone and bird signatures, fog, noise; auto-contrast and palettes ported from SkyNetics |
| `trinetra/ai/tracker.py` | Tracker on radar plots (Kalman, Hungarian, M-of-N confirmation) |
| `trinetra/scoring/roe.py` | Rules-of-engagement tree and credit per simulated action |
| `trinetra/scoring/rubric.py` | Run score: detect, classify, respond, false alarms, with plain-language notes |
| `trinetra/core/session.py` | One training run: world, sensors, tracker, log, trainee actions, simulated outcomes |
| `trinetra/console/` | OpenCV trainee console: radar scope, cued thermal view, briefing, score screen |
| `trinetra/scenarios/` | Scenario packs |
