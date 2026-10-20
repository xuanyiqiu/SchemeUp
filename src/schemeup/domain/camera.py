"""Camera for the infinite canvas.

World coordinates are canvas units, where one unit is one logical pixel at
100% zoom. The camera stores the world point shown at the top-left corner
of the viewport plus the zoom factor, so  screen = (world - origin) * zoom.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from schemeup.domain.geometry import Point, Rect, Size
from schemeup.domain.kinetics import Spring, rubber_band

MIN_ZOOM = 0.1
MAX_ZOOM = 30.0

# How far past a zoom limit a rubber-banded zoom can stretch, in log space.
# log(2) means it never goes more than 2x past the limit, whatever the input.
ZOOM_STRETCH = math.log(2)


def clamp_zoom(zoom: float) -> float:
    return min(max(zoom, MIN_ZOOM), MAX_ZOOM)


def soft_clamp_zoom(zoom: float) -> float:
    """Like `clamp_zoom`, but past a limit it gives a little instead of stopping dead."""
    log_zoom = math.log(zoom)
    low, high = math.log(MIN_ZOOM), math.log(MAX_ZOOM)
    if log_zoom > high:
        return math.exp(high + rubber_band(log_zoom - high, ZOOM_STRETCH))
    if log_zoom < low:
        return math.exp(low + rubber_band(log_zoom - low, ZOOM_STRETCH))
    return zoom


@dataclass(frozen=True, slots=True)
class Camera:
    x: float = 0.0
    y: float = 0.0
    zoom: float = 1.0

    def to_screen(self, p: Point) -> Point:
        return Point((p.x - self.x) * self.zoom, (p.y - self.y) * self.zoom)

    def to_world(self, p: Point) -> Point:
        return Point(p.x / self.zoom + self.x, p.y / self.zoom + self.y)

    def visible_rect(self, viewport: Size) -> Rect:
        return Rect(self.x, self.y, viewport.width / self.zoom, viewport.height / self.zoom)

    def panned_by(self, dx: float, dy: float) -> Camera:
        """Move the content by a screen-space delta, like dragging the paper."""
        return replace(self, x=self.x - dx / self.zoom, y=self.y - dy / self.zoom)

    def with_zoom_at(self, anchor: Point, zoom: float) -> Camera:
        """Set the zoom exactly, keeping the world point under `anchor` (screen) in place.

        No clamping here, so a rubber-banded zoom can go slightly past the limits.
        """
        if zoom <= 0:
            raise ValueError(f"zoom must be positive, got {zoom}")
        world = self.to_world(anchor)
        return Camera(world.x - anchor.x / zoom, world.y - anchor.y / zoom, zoom)

    def zoomed_at(self, anchor: Point, factor: float) -> Camera:
        """Scale by `factor` within the zoom limits, keeping `anchor` in place."""
        return self.with_zoom_at(anchor, clamp_zoom(self.zoom * factor))

    def centered_on(self, p: Point, viewport: Size, zoom: float | None = None) -> Camera:
        """Camera with `p` in the middle of the viewport, keeping the zoom unless given."""
        zoom = clamp_zoom(self.zoom if zoom is None else zoom)
        return Camera(p.x - viewport.width / (2 * zoom), p.y - viewport.height / (2 * zoom), zoom)

    def fitted_to(
        self, rect: Rect, viewport: Size, padding: float = 48.0, max_zoom: float = 1.0
    ) -> Camera:
        """Show all of `rect` with `padding` screen pixels around it, never zooming past
        `max_zoom` (so a tiny sketch isn't blown up to fill the screen)."""
        available_w = max(viewport.width - 2 * padding, 1.0)
        available_h = max(viewport.height - 2 * padding, 1.0)
        zooms = [max_zoom]
        if rect.width > 0:
            zooms.append(available_w / rect.width)
        if rect.height > 0:
            zooms.append(available_h / rect.height)
        return self.centered_on(rect.center, viewport, min(zooms))


@dataclass(frozen=True, slots=True)
class CameraSpring:
    """Moves a camera to a target with three independent springs: the world point
    in the middle of the viewport (x and y) and the zoom in log space.

    Zoom works in log space so zooming in and out feel equally fast.
    """

    x: Spring
    y: Spring
    log_zoom: Spring

    @classmethod
    def between(
        cls,
        start: Camera,
        target: Camera,
        viewport: Size,
        velocity: Point | None = None,
        zoom_velocity: float = 0.0,
        response: float = 0.4,
    ) -> CameraSpring:
        """`velocity` is how fast the content is already moving on screen (px/s) and
        `zoom_velocity` how fast the log zoom is changing, so motion in progress
        flows into the spring instead of stopping dead."""
        velocity = velocity if velocity is not None else Point(0.0, 0.0)
        middle = Point(viewport.width / 2, viewport.height / 2)
        a, b = start.to_world(middle), target.to_world(middle)
        # Tolerances are 0.1 px and 1 px/s on screen, converted to world units.
        rest_distance, rest_speed = 0.1 / target.zoom, 1.0 / target.zoom
        # Content moving right on screen means the world point in the middle moves left.
        return cls(
            x=Spring(a.x, b.x, -velocity.x / start.zoom, response, 1.0, rest_distance, rest_speed),
            y=Spring(a.y, b.y, -velocity.y / start.zoom, response, 1.0, rest_distance, rest_speed),
            log_zoom=Spring(
                math.log(start.zoom),
                math.log(target.zoom),
                zoom_velocity,
                response,
                1.0,
                1e-4,
                1e-3,
            ),
        )

    @property
    def at_rest(self) -> bool:
        return self.x.at_rest and self.y.at_rest and self.log_zoom.at_rest

    def step(self, dt: float) -> CameraSpring:
        return CameraSpring(self.x.step(dt), self.y.step(dt), self.log_zoom.step(dt))

    def settled(self) -> CameraSpring:
        return CameraSpring(self.x.settled(), self.y.settled(), self.log_zoom.settled())

    def camera(self, viewport: Size) -> Camera:
        zoom = math.exp(self.log_zoom.value)
        return Camera(
            self.x.value - viewport.width / (2 * zoom),
            self.y.value - viewport.height / (2 * zoom),
            zoom,
        )

    def screen_velocity(self) -> Point:
        """Current pan speed on screen in px/s, to hand over to inertia when interrupted."""
        zoom = math.exp(self.log_zoom.value)
        return Point(-self.x.velocity * zoom, -self.y.velocity * zoom)
