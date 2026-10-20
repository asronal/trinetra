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

## Play

```powershell
.venv\Scripts\python.exe -m trinetra.app
```

Your browser opens the trainer (it runs on this computer only, at http://127.0.0.1:8765; no internet needed). Pick a mission, choose **Guided** for the first time, and follow the green instruction bar:

1. **Spot.** Contacts appear on the radar as numbered circles. Click one (or click it in the Contacts list or the camera view).
2. **Identify.** The cameras turn to it. Inside camera range they lock on and keep it in the middle; zoom in (×40, ×100) to see it. Pick what it is, then Hostile or Not hostile.
3. **Respond.** Pick a response. Guided mode shows the rule that applies.

**Camera at the post** is the day camera; **Overview map** shows the whole area from above (aircraft drawn larger than life). **Show everything** reveals what each contact really is, for instructors and demos. At the end you get a score with what to improve, and the full record is saved under `output/trinetra/`. Stop the trainer with Ctrl+C in the terminal.

| Scenario | What it trains |
|---|---|
| `scn01_day_single.yaml` | The basic loop: one quad by day, one bird |
| `scn02_dusk_decoys.yaml` | A fast FPV among a friendly hexacopter and birds; radar dropout |
| `scn03_night_jam.yaml` | Recce fixed-wing to hand off, then a quad attack under radar jamming |
| `smoke.yaml` | CI smoke test |

Other ways to run: `--headless --scenario <file>` runs without any interface as fast as possible and only writes the log; `--opencv --scenario <file>` opens the older OpenCV console; `--port N` and `--no-browser` change how the trainer starts.

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
| `trinetra/server/` | Local web server and the real-time simulation runner behind the browser trainer |
| `trinetra/web/` | Browser trainer: 3D day camera and overview (three.js, vendored), radar, heat camera, guided actions |
| `trinetra/console/` | Older OpenCV console (`--opencv`) |
| `trinetra/scenarios/` | Scenario packs |
