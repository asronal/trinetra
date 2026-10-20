"""Web trainer: the simulation runner and the local HTTP server."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from trinetra.server.runner import LOCK_RANGE_M, SimRunner, list_scenarios
from trinetra.server.web import make_server


@pytest.fixture
def runner(tmp_path):
    r = SimRunner(log_dir=tmp_path, realtime=False)
    yield r
    r.close()


def play_to_contact(r, truth_id="UAV-01", scenario="scn01_day_single.yaml"):
    assert r.act({"type": "start", "scenario": scenario, "mode": "guided"})["ok"]
    r.act({"type": "begin"})
    for _ in range(200):
        tr = next((t for t in r.session.tracker.confirmed if t.truth_id == truth_id), None)
        if tr:
            return tr
        r.act({"type": "skip", "seconds": 1})
    raise AssertionError("contact never appeared")


def test_scenario_list_has_the_missions_but_not_the_smoke_test():
    files = [s["file"] for s in list_scenarios()]
    assert files == ["scn01_day_single.yaml", "scn02_dusk_decoys.yaml", "scn03_night_jam.yaml"]


def test_start_rejects_unknown_or_escaping_scenarios(runner):
    assert not runner.act({"type": "start", "scenario": "../app.py"})["ok"]
    assert not runner.act({"type": "start", "scenario": "nope.yaml"})["ok"]
    assert not runner.act({"type": "start", "scenario": "scn01_day_single.yaml", "mode": "easy"})["ok"]


def test_guided_flow_end_to_end(runner):
    tr = play_to_contact(runner)
    assert runner.act({"type": "select", "track_id": tr.id})["ok"]
    assert runner.act({"type": "classify", "label": "quad", "hostile": True})["ok"]
    res = runner.act({"type": "respond", "action": "alert_qrt"})
    assert res["ok"] and "Reaction team alerted" in res["message"]
    again = runner.act({"type": "respond", "action": "alert_qrt"})        # held key / double click
    assert not again["ok"] and "already ordered" in again["error"].lower()
    st = runner.state()
    c = next(t for t in st["tracks"] if t["id"] == tr.id)
    assert c["status"] == "hostile" and c["label"] == "quad" and c["actions"] == ["alert_qrt"]
    runner.act({"type": "end"})
    st = runner.state()
    assert st["status"] == "done" and 0 <= st["score"]["total"] <= 1 and st["log"].endswith(".jsonl")


def test_page_never_gets_true_identity_unless_instructor(runner):
    play_to_contact(runner)
    assert all(e["hostile"] is None for e in runner.state()["entities"])
    runner.act({"type": "instructor", "on": True})
    assert {e["id"]: e["hostile"] for e in runner.state()["entities"]}["UAV-01"] is True


def test_camera_locks_on_inside_lock_range_and_follows_radar_outside(runner):
    # Night: the lock range is short (1.2 km) and UAV-02 first appears ~2.4 km out.
    tr = play_to_contact(runner, "UAV-02", "scn03_night_jam.yaml")
    runner.act({"type": "select", "track_id": tr.id})
    assert tr.range_m > LOCK_RANGE_M["night"] and not runner.state()["camera"]["locked"]
    while True:
        cur = runner.session.tracker.get(runner.session.selected) if runner.session.selected else None
        if cur is None:                                  # jamming dropped the track: reselect
            cur = next((t for t in runner.session.tracker.confirmed if t.truth_id == "UAV-02"), None)
            if cur is not None:
                runner.act({"type": "select", "track_id": cur.id})
        if cur is not None and cur.range_m < LOCK_RANGE_M["night"] - 200:
            break
        runner.act({"type": "skip", "seconds": 1})
    runner.act({"type": "skip", "seconds": 0.2})
    cam = runner.state()["camera"]
    uav = next(e for e in runner.session.world.active() if e.id == "UAV-02")
    assert cam["locked"]
    assert cam["az"] == pytest.approx(uav.bearing_deg, abs=0.5)


def test_downed_target_refuses_more_orders(runner):
    tr = play_to_contact(runner)
    runner.act({"type": "select", "track_id": tr.id})
    while runner.session.tracker.get(tr.id).range_m > 800:
        runner.act({"type": "skip", "seconds": 1})
    for _ in range(6):
        res = runner.act({"type": "respond", "action": "simulated_hard_kill"})
        if res["ok"] and "target down" in res["message"]:
            break
        runner.act({"type": "skip", "seconds": 3.1})
    assert "target down" in res["message"]
    assert next(t for t in runner.state()["tracks"] if t["id"] == tr.id)["status"] == "down"
    res = runner.act({"type": "respond", "action": "simulated_soft_kill"})
    assert not res["ok"] and "already down" in res["error"]


def test_thermal_frame_is_a_jpeg(runner):
    play_to_contact(runner)
    jpg = runner.thermal_jpeg()
    assert jpg[:2] == b"\xff\xd8"


@pytest.fixture
def server(runner):
    srv = make_server(runner, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def post(url, body: bytes):
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_server_serves_page_scripts_and_offline_three_js(server):
    status, ctype, body = get(server + "/")
    assert status == 200 and "text/html" in ctype and b"TRINETRA" in body
    for path in ("/static/js/app.js", "/static/js/world3d.js", "/static/js/radar.js", "/static/vendor/three.module.min.js"):
        status, ctype, _ = get(server + path)
        assert status == 200 and "javascript" in ctype


def test_server_blocks_path_escape(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(server + "/static/..%2F..%2Fapp.py")
    assert e.value.code == 404


def test_server_actions_and_state(server):
    assert post(server + "/api/action", b"not json")[0] == 400
    status, res = post(server + "/api/action", json.dumps({"type": "start", "scenario": "scn01_day_single.yaml"}).encode())
    assert status == 200 and res["ok"]
    status, _, body = get(server + "/api/state")
    assert json.loads(body)["status"] == "briefing"


def test_stream_sends_state_events(server):
    with urllib.request.urlopen(server + "/api/stream", timeout=5) as r:
        line = r.readline().decode()
    assert line.startswith("data: ") and json.loads(line[6:])["status"] == "menu"
