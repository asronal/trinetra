"""
TRINETRA — entity behaviours.

A behaviour moves one entity by one tick. update() returns a despawn
reason (e.g. "arrived") or None to keep the entity alive.

Phase 0: straight line and attack run. Loiter, boids swarm, wander,
patrol and evasive arrive in later phases.
"""

import math
from dataclasses import dataclass
from typing import Optional


def heading_vector(heading_deg: float):
    """Unit (east, north) vector for a compass heading (0 = north, 90 = east)."""
    rad = math.radians(heading_deg)
    return math.sin(rad), math.cos(rad)


@dataclass
class StraightLine:
    """Constant speed along a fixed compass heading."""
    heading_deg: float
    speed_mps: float

    def update(self, entity, dt: float) -> Optional[str]:
        de, dn = heading_vector(self.heading_deg)
        entity.vel = (de * self.speed_mps, dn * self.speed_mps, 0.0)
        entity.advance(dt)
        return None


@dataclass
class AttackRun:
    """Fly straight at the post (the origin) at constant altitude; despawn on arrival."""
    speed_mps: float
    arrive_radius_m: float = 10.0

    def update(self, entity, dt: float) -> Optional[str]:
        e, n, _ = entity.pos
        dist = math.hypot(e, n)
        step = self.speed_mps * dt
        if dist <= max(step, self.arrive_radius_m):
            entity.vel = (0.0, 0.0, 0.0)
            entity.pos = (0.0, 0.0, entity.pos[2])
            return "arrived"
        entity.vel = (-e / dist * self.speed_mps, -n / dist * self.speed_mps, 0.0)
        entity.advance(dt)
        return None
