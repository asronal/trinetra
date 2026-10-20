"""Console logic and rendering, without opening a window."""
from pathlib import Path

import numpy as np
import pytest

from trinetra.config import Config
from trinetra.console.console import ConsoleUI, H, W
from trinetra.console import views as V
from trinetra.core.events import read_events
from trinetra.core.scenario import load_scenario
from trinetra.core.session import Session

SCN = Path(__file__).resolve().parents[1] / "scenarios" / "scn01_day_single.yaml"


@pytest.fixture
def ui(tmp_path):
    s = Session(load_scenario(SCN), Config(), tmp_path / "c.jsonl", with_ir=True)
    u = ConsoleUI(s)
    yield u
    s.finish()


def advance_to_uav_track(ui):
    ui.key(32)                                   # leave the briefing
    while not any(t.truth_id == "UAV-01" for t in ui.s.tracker.confirmed):
        ui.tick()
    return next(t for t in ui.s.tracker.confirmed if t.truth_id == "UAV-01")


def test_renders_briefing_then_console(ui):
    img = ui.render()
    assert img.shape == (H, W, 3) and img.dtype == np.uint8
    assert ui.briefing and ui.paused
    ui.key(32)
    assert not ui.briefing and not ui.paused
    for _ in range(25):
        ui.tick()
    assert ui.render().shape == (H, W, 3)


def test_click_on_track_selects_it_and_cues_camera(ui):
    tr = advance_to_uav_track(ui)
    px, py = ui.ppi.to_px(tr.east, tr.north)
    ui.click(px + 3, py - 2)
    assert ui.s.selected == tr.id
    ui.tick()
    assert ui.s.ir.az_deg == pytest.approx(tr.bearing_deg, abs=2.0)


def test_class_then_hostile_key_logs_a_classification(ui):
    tr = advance_to_uav_track(ui)
    ui.s.select(tr.id)
    ui.key(ord("h"))                             # no class picked yet
    assert "Pick a class" in ui.messages[-1][1]
    ui.key(ord("1"))
    ui.key(ord("h"))
    assert ui.pending_class is None
    ui.s.finish()
    ev = [e for e in read_events(ui.s.log_path) if e["type"] == "trainee_classify"]
    assert ev and ev[0]["label"] == "quad" and ev[0]["hostile"] is True


def test_hard_kill_needs_two_presses(ui):
    tr = advance_to_uav_track(ui)
    ui.s.select(tr.id)
    ui.key(ord("x"))
    assert "again" in ui.messages[-1][1]
    ui.key(ord("x"))
    ui.s.finish()
    assert any(e["type"] == "trainee_respond" and e["action"] == "simulated_hard_kill"
               for e in read_events(ui.s.log_path))


def test_special_keys_are_ignored(ui):
    ui.key(32)
    speed = ui.speed
    for k in (2490368, 2621440, 2424832, 2555904):     # arrow keys from waitKeyEx on Windows
        ui.key(k)
    assert ui.speed == speed and not ui.paused


def test_tab_cycles_tracks_and_escape_quits(ui):
    advance_to_uav_track(ui)
    ui.key(9)
    assert ui.s.selected is not None
    ui.key(27)
    assert ui.quit


def test_score_screen_renders():
    from trinetra.scoring.rubric import RunScore
    img = np.zeros((H, W, 3), np.uint8)
    V.draw_score(img, RunScore(0.8, 0.5, None, 0.75, 0.68, 1, [], ["UAV-01: example note"]), "out/x.jsonl")
    assert img.any()
