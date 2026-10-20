import pytest

from trinetra.core.behaviours import AttackRun, StraightLine
from trinetra.core.world import ACTIVE, GONE, PENDING, Entity, SimClock, World


def make_entity(eid="E", pos=(0.0, 1000.0, 50.0), behaviour=None, spawn_s=0.0):
    return Entity(id=eid, label="quad", hostile=True, spawn_s=spawn_s, pos=pos,
                  behaviour=behaviour or StraightLine(heading_deg=90.0, speed_mps=10.0))


def test_clock_has_no_float_drift():
    clock = SimClock(tick_hz=10.0)
    for _ in range(600):
        clock.step()
    assert clock.t == 60.0
    assert clock.dt == pytest.approx(0.1)


def test_geometry_bearing_range_and_radial_speed():
    e = make_entity(pos=(1000.0, 0.0, 0.0))
    assert e.bearing_deg == pytest.approx(90.0)
    assert e.ground_range_m == pytest.approx(1000.0)
    e.vel = (-10.0, 0.0, 0.0)          # flying west, straight at the post
    assert e.radial_speed_mps == pytest.approx(10.0)
    e.vel = (10.0, 0.0, 0.0)
    assert e.radial_speed_mps == pytest.approx(-10.0)


def test_straight_line_moves_along_heading():
    e = make_entity(pos=(0.0, 1000.0, 50.0), behaviour=StraightLine(heading_deg=90.0, speed_mps=10.0))
    world = World([e], tick_hz=10.0)
    world.start()
    for _ in range(100):               # 10 s
        world.step()
    east, north, up = e.pos
    assert east == pytest.approx(100.0)
    assert north == pytest.approx(1000.0)
    assert up == 50.0


def test_spawn_waits_for_spawn_time():
    e = make_entity(spawn_s=0.3)
    world = World([e], tick_hz=10.0)
    assert world.start() == []
    assert e.state == PENDING
    world.step()
    world.step()
    assert e.state == PENDING
    changes = world.step()
    assert world.t == pytest.approx(0.3)
    assert [(c.kind, c.entity.id) for c in changes] == [("spawn", "E")]
    assert e.state == ACTIVE


def test_attack_run_closes_on_post_and_despawns_on_arrival():
    e = make_entity(pos=(300.0, 400.0, 60.0), behaviour=AttackRun(speed_mps=50.0))   # 500 m out
    world = World([e], tick_hz=10.0)
    world.start()
    despawn = None
    for _ in range(200):
        for c in world.step():
            if c.kind == "despawn":
                despawn = (world.t, c.reason)
        if despawn:
            break
    assert despawn is not None
    t, reason = despawn
    assert reason == "arrived"
    assert t == pytest.approx(10.0, abs=0.25)     # 500 m at 50 m/s
    assert e.state == GONE


def test_entity_leaving_area_is_despawned():
    e = make_entity(pos=(0.0, 990.0, 0.0), behaviour=StraightLine(heading_deg=0.0, speed_mps=100.0))
    world = World([e], tick_hz=10.0, area_radius_m=1000.0)
    world.start()
    world.step()
    changes = world.step()
    assert [(c.kind, c.reason) for c in changes] == [("despawn", "out_of_area")]


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError):
        World([make_entity("A"), make_entity("A")])
