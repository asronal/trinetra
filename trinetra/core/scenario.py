"""
TRINETRA — scenario loader.

Reads a scenario YAML (plan §6.1), validates it with error messages that
name the file and the entity, and builds a World from it.
"""

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .behaviours import AttackRun, StraightLine
from .catalog import CLASS_PROFILES, CLASSES, SENSORS
from .world import Entity, World

TERRAINS = ("urban", "rural", "mountain", "coastal")
TIMES_OF_DAY = ("day", "dusk", "night")
DIFFICULTIES = ("guided", "standard", "stress", "swarm")
DEGRADATION_KINDS = ("jamming", "dropout", "noise", "glare", "fog")

PATHS = ("straight", "attack_run")
PLANNED_PATHS = ("loiter", "wander", "patrol", "evasive")   # later phases


class ScenarioError(ValueError):
    """The scenario file is invalid."""


@dataclass
class Degradation:
    at_s: float
    sensor: str
    kind: str
    duration_s: float

    def active(self, t: float) -> bool:
        return self.at_s <= t < self.at_s + self.duration_s


@dataclass
class EntitySpec:
    id: str
    label: str
    hostile: bool
    spawn_s: float
    path: str
    from_bearing: float
    range_m: float
    alt_m: float
    speed_mps: float
    heading_deg: Optional[float] = None
    iff: bool = False


@dataclass
class Scenario:
    id: str
    seed: int
    terrain: str
    time_of_day: str
    entities: List[EntitySpec]
    weather: Dict = field(default_factory=dict)
    degradation: List[Degradation] = field(default_factory=list)
    post: Dict = field(default_factory=dict)
    roe: str = "standard"


def load_scenario(path) -> Scenario:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ScenarioError(f"{path}: invalid YAML: {e}") from None
    return parse_scenario(data, source=str(path))


def parse_scenario(data, source: str = "<scenario>") -> Scenario:
    def fail(msg):
        raise ScenarioError(f"{source}: {msg}")

    if not isinstance(data, dict):
        fail("top level must be a mapping")
    for key in ("id", "seed", "terrain", "time_of_day", "entities"):
        if key not in data:
            fail(f"missing required key '{key}'")
    if data["terrain"] not in TERRAINS:
        fail(f"terrain must be one of {TERRAINS}, got {data['terrain']!r}")
    if data["time_of_day"] not in TIMES_OF_DAY:
        fail(f"time_of_day must be one of {TIMES_OF_DAY}, got {data['time_of_day']!r}")
    if not isinstance(data["entities"], list) or not data["entities"]:
        fail("entities must be a non-empty list")

    degradation = []
    for i, d in enumerate(data.get("degradation") or []):
        try:
            deg = Degradation(float(d["at_s"]), d["sensor"], d["kind"], float(d["duration_s"]))
        except (KeyError, TypeError, ValueError):
            fail(f"degradation[{i}] needs at_s, sensor, kind and duration_s")
        if deg.sensor not in SENSORS:
            fail(f"degradation[{i}]: unknown sensor {deg.sensor!r}")
        if deg.kind not in DEGRADATION_KINDS:
            fail(f"degradation[{i}]: kind must be one of {DEGRADATION_KINDS}")
        degradation.append(deg)

    entities, seen = [], set()
    for i, raw in enumerate(data["entities"]):
        ent = _parse_entity(raw, f"{source}: entities[{i}]")
        if ent.id in seen:
            fail(f"duplicate entity id {ent.id!r}")
        seen.add(ent.id)
        entities.append(ent)

    return Scenario(
        id=str(data["id"]),
        seed=int(data["seed"]),
        terrain=data["terrain"],
        time_of_day=data["time_of_day"],
        entities=entities,
        weather=data.get("weather") or {},
        degradation=degradation,
        post=data.get("post") or {},
        roe=str(data.get("roe", "standard")),
    )


def _parse_entity(raw, where: str) -> EntitySpec:
    def fail(msg):
        raise ScenarioError(f"{where}: {msg}")

    if not isinstance(raw, dict):
        fail("must be a mapping")
    eid = raw.get("id")
    if not eid:
        fail("missing 'id'")
    where = f"{where} ({eid})"

    label = raw.get("class")
    if label not in CLASSES:
        fail(f"class must be one of {CLASSES}, got {label!r}")
    if "swarm" in raw:
        fail("swarms are not implemented yet (Phase 2)")
    if "hostile" not in raw:
        fail("missing 'hostile' (true/false)")

    path = raw.get("path")
    if path in PLANNED_PATHS:
        fail(f"path '{path}' is not implemented yet")
    if path not in PATHS:
        fail(f"path must be one of {PATHS}, got {path!r}")
    for key in ("from_bearing", "range_m"):
        if key not in raw:
            fail(f"missing '{key}' (spawn position)")
    if path == "straight" and "heading_deg" not in raw:
        fail("path 'straight' needs 'heading_deg'")

    profile = CLASS_PROFILES[label]
    spec = EntitySpec(
        id=str(eid),
        label=label,
        hostile=bool(raw["hostile"]),
        spawn_s=float(raw.get("spawn_s", 0.0)),
        path=path,
        from_bearing=float(raw["from_bearing"]),
        range_m=float(raw["range_m"]),
        alt_m=float(raw.get("alt_m", profile.default_alt_m)),
        speed_mps=float(raw.get("speed_mps", profile.typical_speed_mps)),
        heading_deg=float(raw["heading_deg"]) if "heading_deg" in raw else None,
        iff=bool(raw.get("iff", False)),
    )
    if spec.range_m <= 0 or spec.speed_mps <= 0 or spec.spawn_s < 0:
        fail("range_m and speed_mps must be > 0, spawn_s must be >= 0")
    return spec


def build_world(scenario: Scenario, tick_hz: float = 10.0) -> World:
    entities = []
    for spec in scenario.entities:
        rad = math.radians(spec.from_bearing)
        pos = (spec.range_m * math.sin(rad), spec.range_m * math.cos(rad), spec.alt_m)
        if spec.path == "attack_run":
            behaviour = AttackRun(speed_mps=spec.speed_mps)
        else:
            behaviour = StraightLine(heading_deg=spec.heading_deg, speed_mps=spec.speed_mps)
        entities.append(Entity(
            id=spec.id, label=spec.label, hostile=spec.hostile, spawn_s=spec.spawn_s,
            pos=pos, behaviour=behaviour, iff=spec.iff,
        ))
    return World(entities, tick_hz=tick_hz)
