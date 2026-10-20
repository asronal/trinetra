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

## Run

```powershell
python -m trinetra.app --scenario trinetra/scenarios/smoke.yaml --headless
python -m pytest trinetra -q
```

The run writes an event log to `output/trinetra/<scenario>_<time>.jsonl`. Options: `--difficulty guided|standard|stress|swarm`, `--duration 60`, `--seed N`, `--out path.jsonl`.

## Layout (Phase 0)

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
| `trinetra/scoring/rubric.py` | Time to detect and its score |
| `trinetra/scenarios/` | Scenario packs |
