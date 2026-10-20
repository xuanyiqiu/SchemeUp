"""Inertial panning.

When a drag is released, the view keeps gliding with the release velocity
and slows down exponentially, the way scrolling works on a phone.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, replace

from schemeup.domain.geometry import Point


class VelocityTracker:
    """Estimates pointer velocity from the samples of the last `window` seconds.

    Only recent samples count, so stopping the mouse before releasing it gives
    zero velocity instead of a surprise fling.
    """

    def __init__(self, window: float = 0.08) -> None:
        self._window = window
        self._samples: deque[tuple[float, Point]] = deque()

    def reset(self) -> None:
        self._samples.clear()

    def add(self, t: float, position: Point) -> None:
        self._samples.append((t, position))
        self._drop_older_than(t - self._window)

    def velocity(self, now: float) -> Point:
        """Average velocity over the window, in units per second."""
        self._drop_older_than(now - self._window)
        if len(self._samples) < 2:
            return Point(0.0, 0.0)
        (t0, p0), (t1, p1) = self._samples[0], self._samples[-1]
        if t1 <= t0:
            return Point(0.0, 0.0)
        return (p1 - p0) * (1.0 / (t1 - t0))

    def _drop_older_than(self, t: float) -> None:
        while self._samples and self._samples[0][0] < t:
            self._samples.popleft()


@dataclass(frozen=True, slots=True)
class Inertia:
    velocity: Point  # screen pixels per second
    time_constant: float = 0.325  # seconds, close to the deceleration of iOS scroll views
    stop_speed: float = 20.0

    @classmethod
    def launch(cls, velocity: Point, max_speed: float = 6000.0) -> Inertia:
        speed = velocity.length()
        if speed > max_speed:
            velocity = velocity * (max_speed / speed)
        return cls(velocity)

    @property
    def active(self) -> bool:
        return self.velocity.length() > self.stop_speed

    def step(self, dt: float) -> tuple[Point, Inertia]:
        """Displacement over the next `dt` seconds and the slowed-down inertia.

        This is the exact integral of v * exp(-t / tau), so the total distance
        doesn't depend on the frame rate.
        """
        decay = math.exp(-dt / self.time_constant)
        displacement = self.velocity * (self.time_constant * (1.0 - decay))
        return displacement, replace(self, velocity=self.velocity * decay)
