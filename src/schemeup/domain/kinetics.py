"""Motion physics: inertia, springs and rubber banding.

When a drag is released, the view keeps gliding with the release velocity
and slows down exponentially, the way scrolling works on a phone. Things
that move to a target use springs, because a spring can change target at
any moment without a jump in position or speed.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, replace

from schemeup.domain.geometry import Point

# UIScrollView's normal deceleration keeps 0.998 of the speed every millisecond,
# which is an exponential decay with a time constant of about half a second.
SCROLL_TIME_CONSTANT = -0.001 / math.log(0.998)


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
    time_constant: float = SCROLL_TIME_CONSTANT
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


@dataclass(frozen=True, slots=True)
class Spring:
    """A damped spring pulling `value` towards `target`, described the way Apple does.

    `response` is the period of the undamped oscillation in seconds (lower is
    snappier). `damping_ratio` controls overshoot: 1.0 settles without bouncing,
    lower values bounce. Re-targeting keeps the current value and velocity, so
    an interrupted spring carries on smoothly instead of restarting.
    """

    value: float
    target: float
    velocity: float = 0.0
    response: float = 0.4
    damping_ratio: float = 1.0
    rest_distance: float = 1e-3
    rest_speed: float = 1e-2

    def __post_init__(self) -> None:
        if self.response <= 0:
            raise ValueError(f"response must be positive, got {self.response}")
        if not 0 < self.damping_ratio <= 1:
            raise ValueError(f"damping ratio must be in (0, 1], got {self.damping_ratio}")

    @property
    def at_rest(self) -> bool:
        return (
            abs(self.target - self.value) < self.rest_distance
            and abs(self.velocity) < self.rest_speed
        )

    def retargeted(self, target: float) -> Spring:
        return replace(self, target=target)

    def settled(self) -> Spring:
        return replace(self, value=self.target, velocity=0.0)

    def step(self, dt: float) -> Spring:
        """State after `dt` seconds.

        Uses the closed-form solution of the damped oscillator, so the motion is
        the same at any frame rate.
        """
        omega = 2 * math.pi / self.response
        zeta = self.damping_ratio
        x0 = self.value - self.target
        v0 = self.velocity
        if zeta == 1.0:
            b = v0 + omega * x0
            decay = math.exp(-omega * dt)
            x = (x0 + b * dt) * decay
            v = (b - omega * (x0 + b * dt)) * decay
        else:
            damped = omega * math.sqrt(1 - zeta * zeta)
            b = (v0 + zeta * omega * x0) / damped
            decay = math.exp(-zeta * omega * dt)
            cos, sin = math.cos(damped * dt), math.sin(damped * dt)
            x = decay * (x0 * cos + b * sin)
            v = decay * (
                (b * damped - zeta * omega * x0) * cos - (x0 * damped + zeta * omega * b) * sin
            )
        return replace(self, value=self.target + x, velocity=v)


def rubber_band(overshoot: float, dimension: float, constant: float = 0.55) -> float:
    """How far to actually move when input goes `overshoot` past a boundary.

    It follows at `constant` times the overshoot at first and flattens out so
    it never passes `dimension`. 0.55 is the constant iOS uses for scroll views.
    """
    return overshoot * dimension * constant / (dimension + constant * abs(overshoot))
