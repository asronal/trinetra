"""
TRINETRA — sensor interface.

Emulated and live (HIL) sensors share this interface, so the console and
the AI engine do not care where a frame came from.
"""

from abc import ABC, abstractmethod


class Sensor(ABC):
    name: str = ""

    def initialize(self) -> None:
        pass

    @abstractmethod
    def read(self, world, t: float):
        """Return this sensor's view of the world at time t, or None if no new data."""

    def release(self) -> None:
        pass
