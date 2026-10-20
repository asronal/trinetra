"""
TRINETRA — world model.

The world is the single source of truth (plan §4): sensors, the AI and
the trainee each produce their own view of it, and scoring compares each
view with this one.

Coordinates are local east / north / up metres with the sensor post at
the origin. Bearings are compass degrees (0 = north, 90 = east).
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .catalog import CLASS_PROFILES

Vec3 = Tuple[float, float, float]

PENDING, ACTIVE, GONE = "pending", "active", "gone"


@dataclass
class SimClock:
    """Fixed-step clock. Time is derived from the tick count so it never drifts."""
    tick_hz: float = 10.0
    tick: int = 0

    @property
    def dt(self) -> float:
        return 1.0 / self.tick_hz

    @property
    def t(self) -> float:
        return self.tick / self.tick_hz

    def step(self) -> float:
        self.tick += 1
        return self.t


@dataclass
class Entity:
    id: str
    label: str
    hostile: bool
    spawn_s: float
    pos: Vec3
    behaviour: object
    iff: bool = False
    vel: Vec3 = (0.0, 0.0, 0.0)
    state: str = PENDING

    @property
    def rcs_m2(self) -> float:
        return CLASS_PROFILES[self.label].rcs_m2

    @property
    def ground_range_m(self) -> float:
        return math.hypot(self.pos[0], self.pos[1])

    @property
    def slant_range_m(self) -> float:
        return math.sqrt(self.pos[0] ** 2 + self.pos[1] ** 2 + self.pos[2] ** 2)

    @property
    def bearing_deg(self) -> float:
        return math.degrees(math.atan2(self.pos[0], self.pos[1])) % 360.0

    @property
    def radial_speed_mps(self) -> float:
        """Closing speed towards the post; positive = approaching (LD2450 convention)."""
        r = self.slant_range_m
        if r == 0.0:
            return 0.0
        return -sum(p * v for p, v in zip(self.pos, self.vel)) / r

    def advance(self, dt: float) -> None:
        self.pos = tuple(p + v * dt for p, v in zip(self.pos, self.vel))


@dataclass
class WorldEvent:
    kind: str           # "spawn" | "despawn"
    entity: Entity
    reason: Optional[str] = None


class World:
    def __init__(self, entities: List[Entity], tick_hz: float = 10.0, area_radius_m: float = 6000.0):
        ids = [e.id for e in entities]
        if len(ids) != len(set(ids)):
            raise ValueError("entity ids must be unique")
        self.entities = list(entities)
        self.clock = SimClock(tick_hz=tick_hz)
        self.area_radius_m = area_radius_m

    @property
    def t(self) -> float:
        return self.clock.t

    def active(self) -> List[Entity]:
        return [e for e in self.entities if e.state == ACTIVE]

    def start(self) -> List[WorldEvent]:
        """Spawn everything due at t = 0. Call once before the first step()."""
        return self._spawn_due()

    def step(self) -> List[WorldEvent]:
        """Advance one tick. Returns the spawns/despawns that happened, at the new time."""
        changes: List[WorldEvent] = []
        for e in self.active():
            reason = e.behaviour.update(e, self.clock.dt)
            if reason is None and e.ground_range_m > self.area_radius_m:
                reason = "out_of_area"
            if reason is not None:
                e.state = GONE
                changes.append(WorldEvent("despawn", e, reason))
        self.clock.step()
        changes.extend(self._spawn_due())
        return changes

    def _spawn_due(self) -> List[WorldEvent]:
        spawned = []
        for e in self.entities:
            # Small tolerance so spawn_s = 0.3 is not missed by float rounding of tick / hz.
            if e.state == PENDING and e.spawn_s <= self.clock.t + 1e-9:
                e.state = ACTIVE
                spawned.append(WorldEvent("spawn", e))
        return spawned
