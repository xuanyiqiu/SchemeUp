"""Camera for the infinite canvas.

World coordinates are canvas units, where one unit is one logical pixel at
100% zoom. The camera stores the world point shown at the top-left corner
of the viewport plus the zoom factor, so  screen = (world - origin) * zoom.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from schemeup.domain.geometry import Point, Rect, Size

MIN_ZOOM = 0.1
MAX_ZOOM = 30.0


def clamp_zoom(zoom: float) -> float:
    return min(max(zoom, MIN_ZOOM), MAX_ZOOM)


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

    def zoomed_at(self, anchor: Point, factor: float) -> Camera:
        """Scale by `factor`, keeping the world point under `anchor` (screen) in place."""
        zoom = clamp_zoom(self.zoom * factor)
        world = self.to_world(anchor)
        return Camera(world.x - anchor.x / zoom, world.y - anchor.y / zoom, zoom)

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

    def interpolate(self, target: Camera, t: float, viewport: Size) -> Camera:
        """Camera at fraction `t` of an animated move towards `target`.

        Zoom is interpolated in log space so zooming in and out feel equally fast,
        and the point in the middle of the viewport moves in a straight line.
        """
        zoom = math.exp((1 - t) * math.log(self.zoom) + t * math.log(target.zoom))
        middle = Point(viewport.width / 2, viewport.height / 2)
        start = self.to_world(middle)
        end = target.to_world(middle)
        return self.centered_on(start + (end - start) * t, viewport, zoom)
