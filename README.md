# TRINETRA

AI-Enabled Drone & Counter-Drone Threat Simulation Trainer. Smart India Hackathon 2026, PS **SIH26247** (Ministry of Defence, DSSC), Team **SkyNetics**.

A laptop simulator that trains personnel to spot, identify and respond to drone threats, by day and night, in different terrain and with degraded sensors. **Training only:** no real weapon, jammer, EW or C2 interfaces; every response is an abstract, simulated decision that gets scored.

The full plan, decisions and progress are in [TRINETRA_DEV_PLAN.md](TRINETRA_DEV_PLAN.md).

## Status (20 Oct 2026)

| Works now | Next |
|---|---|
| Browser trainer: 3D camera at the post with **Day / Thermal** switch and a camera HUD, overview map, radar with military-style symbols, guided steps | Playtest with a teammate and tune difficulty |
| Threat alert (banner and alarm) when something unidentified or hostile closes inside 1 km | Swarms and randomly generated missions |
| After-action review per mission: score, stats and a timeline of every decision, graded | Progress across sessions, adaptive difficulty |
| 3 missions (day / dusk / night) plus a smoke test; emulated radar and thermal sensor models | Drone/bird classifier (needs Vishal's training data) |
| Radar tracker, rules-of-engagement scoring; event log of every run; 104 automated tests | Live sensors from the Pi and the red-cell drone (Phase 3) |

## Setup (Windows, PowerShell)

Needs Python 3.11 or newer.

```powershell
cd C:\projects\SIH
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

On Linux/macOS use `.venv/bin/python` instead of `.venv\Scripts\python.exe`.

## Play

```powershell
.venv\Scripts\python.exe -m trinetra.app
```

Your browser opens the trainer at http://127.0.0.1:8765. It runs on this computer only and needs no internet. Stop it with **Ctrl+C** in the terminal.

Pick a mission, choose **Guided** the first time, and follow the green instruction bar:

1. **Spot.** Contacts appear on the radar as numbered circles. Click one, in the radar, the Contacts list or the camera view.
2. **Identify.** The cameras turn to it. Inside camera range they lock on and keep it in the middle (2.5 km by day, 1.8 km at dusk, 1.2 km at night); zoom in (×40, ×100) to see it. Pick what it is, then Hostile or Not hostile.
3. **Respond.** Pick a response. Guided mode shows the rule that applies:

| The contact is | Correct response |
|---|---|
| Not hostile (bird, friendly drone) | Keep watching, or Ignore |
| Hostile, more than 1 km away | Alert reaction team |
| Hostile, inside 1 km and coming closer | Soft kill; Hard kill only if the soft kill fails |
| Hostile, inside 1 km, not coming closer | Hand over |

Other controls: **Camera at the post** / **Overview map** switch views (drag to look or turn, scroll to zoom); **Day camera** / **Thermal** switch what the camera sees (thermal works at night and is not affected by radar jamming); **Show everything** reveals what each contact really is, for instructors and demos; **1× 2× 4×** speeds the mission up; **Space** pauses; **Sound** turns the threat alarm on or off.

After the mission, the **after-action review** shows the score, how many hostiles were stopped or reached the post, the average time to spot, and a timeline of every decision, coloured right, partly right or wrong. The full record is saved under `output/trinetra/`.

| Mission | What it trains |
|---|---|
| `scn01_day_single.yaml` | The basic loop: one quadcopter by day, one bird |
| `scn02_dusk_decoys.yaml` | A fast FPV drone among a friendly hexacopter and birds; radar dropout |
| `scn03_night_jam.yaml` | A recce fixed-wing to hand off, then a quadcopter attack under radar jamming |
| `smoke.yaml` | Automated smoke test (not shown in the trainer) |

### Other ways to run

```powershell
.venv\Scripts\python.exe -m trinetra.app --headless --scenario trinetra/scenarios/smoke.yaml   # no interface, log only
.venv\Scripts\python.exe -m trinetra.app --opencv --scenario trinetra/scenarios/scn01_day_single.yaml   # older OpenCV console
.venv\Scripts\python.exe -m trinetra.app --port 8800 --no-browser   # other port, don't open a browser
```

### Troubleshooting

| Problem | Fix |
|---|---|
| Browser didn't open | Open http://127.0.0.1:8765 yourself |
| `address already in use` | The trainer is already running in another terminal, or use `--port 8800` |
| `Activate.ps1 cannot be loaded` | Skip activation; call `.venv\Scripts\python.exe` directly as above |
| Page says it lost the connection | The terminal running the trainer was closed or stopped; start it again |
| 3D view is blank | The browser needs WebGL; use a current Chrome or Edge |

## How it fits together

```text
scenario YAML ─▶ world (truth, 10 Hz) ─▶ emulated radar ─▶ tracker ─▶ contacts ─┐
                         │              └▶ emulated heat camera ────────────────┤
                         │                                                       ▼
                         └──────────────▶ event log (JSONL) ◀── trainee decisions (browser)
                                                │
                                                ▼
                                       scoring vs truth + rules ─▶ score and notes
```

- The **world model is the single source of truth**. Sensors, the tracker and the trainee each see their own imperfect version of it, and scoring compares each with the truth.
- **Every score comes from the event log**, never from the screen. Logs are deterministic for a given seed.
- The browser only draws. `trinetra/server/` runs the simulation in real time and streams its state to the page about ten times a second; the page sends the trainee's decisions back. The page is never told what a contact really is unless "Show everything" is on.
- Code from the SkyNetics rescue drone (`C:\projects\drone`) is a **reference, not a dependency**: modules are copied in and fixed when needed (plan section 3.1.1).

## Writing a mission

Missions are YAML files in `trinetra/scenarios/`. A new file there appears on the start screen automatically.

```yaml
id: SCN-04-example
title: "SCN-04  Example"
briefing: >
  What the trainee is told before the mission starts.
seed: 404                  # same seed = same run
duration_s: 150
terrain: rural             # rural | urban | mountain | coastal
time_of_day: day           # day | dusk | night
weather: { fog: 0.1 }      # 0 = clear, 1 = thick
degradation:
  - { at_s: 60, sensor: radar, kind: jamming, duration_s: 10 }   # radar|ir|eo · jamming|dropout|noise|glare|fog
roe: standard-forward-post
entities:
  - { id: UAV-01, class: quad, hostile: true,  spawn_s: 5, path: attack_run, from_bearing: 60,  range_m: 2700, speed_mps: 20 }
  - { id: BIRD-1, class: bird, hostile: false, spawn_s: 0, path: straight,   from_bearing: 200, range_m: 1400, heading_deg: 80, speed_mps: 9 }
```

Classes: `quad`, `hexa`, `fixed_wing`, `fpv`, `bird`, `aircraft`. Paths: `attack_run` (straight at the post) and `straight` (needs `heading_deg`). Optional per entity: `alt_m`, `iff`. Check a new file quickly with `--headless --scenario <file>`.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest trinetra -q
```

CI runs the same tests plus the smoke mission on every push (`.github/workflows/tests.yml`), once the repo is on GitHub.

## Code map

| Path | What it does |
|---|---|
| `trinetra/app.py` | Entry point: browser trainer (default), headless runner, OpenCV console |
| `trinetra/config.py` | Tick rate, run length, radar / thermal / tracker emulator settings |
| `trinetra/core/scenario.py` | Mission YAML loader and validation; builds the world |
| `trinetra/core/world.py`, `behaviours.py` | World model: entities, geometry, 10 Hz clock, flight paths |
| `trinetra/core/catalog.py` | Target classes (size, radar and thermal signature) and the allowed simulated responses |
| `trinetra/core/session.py` | One training run: world, sensors, tracker, log, trainee actions, simulated outcomes |
| `trinetra/core/events.py` | Event-log schema, JSONL writer and reader |
| `trinetra/sensors/radar.py` | Emulated radar; plots share the LD2450 radar's fields for the later live-sensor path |
| `trinetra/sensors/ir.py` | Emulated thermal camera; auto-contrast and palettes ported from SkyNetics |
| `trinetra/ai/tracker.py` | Radar tracker: Kalman filter, Hungarian assignment, M-of-N confirmation |
| `trinetra/scoring/roe.py`, `rubric.py`, `aar.py` | Rules-of-engagement tree; run score and plain-language notes; after-action timeline |
| `trinetra/server/` | Local web server and the real-time simulation runner |
| `trinetra/web/` | Browser trainer: 3D day camera and overview (three.js r160, vendored), radar, heat camera, guided actions |
| `trinetra/console/` | Older OpenCV console (`--opencv`) |
| `trinetra/scenarios/` | Missions |
| `trinetra/tests/` | Automated tests |

## Team

| Member | Owns |
|---|---|
| Asronal (Hardware & Integrations) | Live sensor post, red-cell drone, telemetry |
| Anuj D (Software) | `core/`, the trainer interface, app loop, event log |
| Vishal (Model Training) | Drone/bird classifier: data, training, evaluation |
| Akilan S (Hardware Assembly) | Sensor post hardware, drone prep, range safety |
| Members 5 and 6 (to be named) | After-action dashboard; scoring rules and missions |

Third-party: three.js (MIT, `trinetra/web/vendor/THREE_LICENSE.txt`).
