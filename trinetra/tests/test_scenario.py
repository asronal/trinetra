from pathlib import Path

import pytest

from trinetra.core.behaviours import AttackRun, StraightLine
from trinetra.core.scenario import ScenarioError, build_world, load_scenario, parse_scenario

SMOKE = Path(__file__).resolve().parents[1] / "scenarios" / "smoke.yaml"


def base(**overrides):
    data = {
        "id": "T", "seed": 1, "terrain": "rural", "time_of_day": "day",
        "entities": [{"id": "UAV-01", "class": "quad", "hostile": True, "path": "attack_run",
                      "from_bearing": 90, "range_m": 1000}],
    }
    data.update(overrides)
    return data


def test_smoke_scenario_loads_and_builds():
    sc = load_scenario(SMOKE)
    assert sc.id == "SCN-00-smoke"
    assert [e.id for e in sc.entities] == ["UAV-01", "BIRD-1"]
    assert sc.degradation[0].sensor == "radar" and sc.degradation[0].active(45.0)

    world = build_world(sc)
    uav, bird = world.entities
    assert isinstance(uav.behaviour, AttackRun)
    assert isinstance(bird.behaviour, StraightLine)
    assert uav.bearing_deg == pytest.approx(40.0)
    assert uav.ground_range_m == pytest.approx(3000.0)


def test_class_defaults_fill_missing_alt_and_speed():
    sc = parse_scenario(base())
    assert sc.entities[0].alt_m == 60.0
    assert sc.entities[0].speed_mps == 12.0


@pytest.mark.parametrize("overrides, msg", [
    ({"terrain": "moon"}, "terrain"),
    ({"entities": []}, "non-empty"),
    ({"entities": [{"id": "X", "class": "ufo", "hostile": True}]}, "class must be"),
    ({"entities": [{"id": "X", "class": "quad", "hostile": True, "path": "wander",
                    "from_bearing": 0, "range_m": 100}]}, "not implemented yet"),
    ({"entities": [{"id": "X", "class": "quad", "hostile": True, "swarm": {"size": 5}}]}, "swarms"),
    ({"entities": [{"id": "X", "class": "quad", "hostile": True, "path": "straight",
                    "from_bearing": 0, "range_m": 100}]}, "heading_deg"),
    ({"degradation": [{"at_s": 1, "sensor": "radar", "kind": "laser", "duration_s": 1}]}, "kind"),
])
def test_invalid_scenarios_name_the_problem(overrides, msg):
    with pytest.raises(ScenarioError, match=msg):
        parse_scenario(base(**overrides))


def test_duplicate_entity_ids_rejected():
    ent = base()["entities"][0]
    with pytest.raises(ScenarioError, match="duplicate"):
        parse_scenario(base(entities=[ent, dict(ent)]))
