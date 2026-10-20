from pathlib import Path

import pytest

from trinetra.app import main, run_headless
from trinetra.config import Config
from trinetra.core.events import read_events
from trinetra.core.scenario import load_scenario

SMOKE = Path(__file__).resolve().parents[1] / "scenarios" / "smoke.yaml"


@pytest.fixture
def smoke_log(tmp_path):
    return read_events(run_headless(load_scenario(SMOKE), Config(), tmp_path / "smoke.jsonl"))


def test_headless_smoke_run_writes_valid_log(smoke_log):
    types = [e["type"] for e in smoke_log]
    assert types[0] == "run_start" and types[-1] == "run_end"
    assert smoke_log[-1]["t"] == 60.0
    spawns = {e["truth_id"]: e for e in smoke_log if e["type"] == "truth_spawn"}
    assert spawns["UAV-01"]["t"] == 5.0 and spawns["UAV-01"]["hostile"] is True
    assert spawns["BIRD-1"]["t"] == 12.0 and spawns["BIRD-1"]["hostile"] is False


def test_smoke_run_has_coverage_plots_and_jamming(smoke_log):
    enter = {e["truth_id"]: e["t"] for e in smoke_log if e["type"] == "truth_enter_coverage"}
    # UAV-01 starts 3000 m out at 20 m/s; 50 % Pd range is 2500 m -> enters ~25 s after spawn
    assert 28.0 <= enter["UAV-01"] <= 32.0
    assert enter["BIRD-1"] == 12.0

    plots = [e for e in smoke_log if e["type"] == "sensor_plot"]
    assert any(p["truth_id"] == "UAV-01" for p in plots)
    assert any(p["truth_id"] is None for p in plots)            # clutter

    degr = [(e["type"], e["t"]) for e in smoke_log if e["type"].startswith("degradation_")]
    assert degr == [("degradation_start", 40.0), ("degradation_end", 48.0)]


def test_same_seed_same_log(tmp_path):
    sc, cfg = load_scenario(SMOKE), Config()
    a = run_headless(sc, cfg, tmp_path / "a.jsonl").read_text()
    b = run_headless(load_scenario(SMOKE), cfg, tmp_path / "b.jsonl").read_text()
    c = run_headless(load_scenario(SMOKE), cfg, tmp_path / "c.jsonl", seed=99).read_text()
    assert a == b
    assert a != c


def test_cli_rejects_hil_until_phase_3(capsys):
    with pytest.raises(SystemExit):
        main(["--scenario", str(SMOKE), "--hil"])
    assert "Phase 3" in capsys.readouterr().err


def test_cli_writes_log(tmp_path, capsys):
    out = tmp_path / "cli.jsonl"
    assert main(["--scenario", str(SMOKE), "--headless", "--duration", "10", "--out", str(out)]) == 0
    events = read_events(out)
    assert events[-1]["t"] == 10.0


def test_cli_reports_bad_scenario(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: X\nseed: 1\nterrain: moon\ntime_of_day: day\nentities: []\n")
    assert main(["--scenario", str(bad), "--headless"]) == 2
    assert "terrain" in capsys.readouterr().err
