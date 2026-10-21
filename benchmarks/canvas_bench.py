"""Frame times of the canvas with many elements.

Run with `uv run python benchmarks/canvas_bench.py [count]`. It fills a canvas
with a mix of hand-drawn shapes, arrows, text and freehand strokes, then times
real repaints while panning, zooming and dragging a selection.
"""

from __future__ import annotations

import math
import os
import random
import statistics
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from schemeup.application.editor import EditorSession
from schemeup.domain import commands
from schemeup.domain.camera import Camera
from schemeup.domain.commands import ShapeKind
from schemeup.domain.document import Document
from schemeup.domain.elements import Element
from schemeup.domain.geometry import Point, Rect
from schemeup.domain.style import FillStyle, Style
from schemeup.rendering.fonts import register_fonts
from schemeup.rendering.text import QtTextMeasurer
from schemeup.ui.canvas.view import CanvasView

COLORS = ("#1971c2", "#2b8a3e", "#b35c00", "#c92a2a", "#1e1e1e")
FILLS = ("#a5d8ff", "#b2f2bb", "#ffec99", "#ffc9c9", "transparent")


def scene(count: int, seed: int = 7) -> list[Element]:
    rng = random.Random(seed)
    side = int(math.sqrt(count)) + 1
    elements: list[Element] = []
    for i in range(count):
        x, y = (i % side) * 160.0, (i // side) * 120.0
        style = Style(
            stroke_color=rng.choice(COLORS),
            fill_color=rng.choice(FILLS),
            fill_style=rng.choice(list(FillStyle)),
            roughness=rng.choice((0, 1, 2)),
        )
        kind = i % 6
        if kind < 3:
            shape = (ShapeKind.RECTANGLE, ShapeKind.ELLIPSE, ShapeKind.DIAMOND)[kind]
            elements.append(commands.make_shape(shape, Rect(x, y, 120, 80), style))
        elif kind == 3:
            elements.append(
                commands.make_linear(True, [Point(x, y), Point(x + 120, y + 60)], style)
            )
        elif kind == 4:
            elements.append(commands.make_text(Point(x, y), f"note {i}", style))
        else:
            points = [Point(x + t * 4, y + 30 * math.sin(t / 4)) for t in range(30)]
            elements.append(commands.make_freedraw(points, [], style, True))
    return elements


def time_frames(view: CanvasView, app: QApplication, cameras: list[Camera]) -> list[float]:
    frames = []
    for camera in cameras:
        view.set_camera(camera)
        start = time.perf_counter()
        view.repaint()
        app.processEvents()
        frames.append((time.perf_counter() - start) * 1000)
    return frames


def report(name: str, frames: list[float]) -> None:
    frames = sorted(frames)
    p95 = frames[int(len(frames) * 0.95) - 1]
    print(f"{name:<28} median {statistics.median(frames):6.2f} ms   p95 {p95:6.2f} ms")


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    app = QApplication(sys.argv[:1])
    register_fonts()
    session = EditorSession(Document(), QtTextMeasurer())
    session.add(scene(count), select=False)
    view = CanvasView(session, reduce_motion=True)
    view.resize(1920, 1080)
    view.show()
    app.processEvents()
    bounds = session.document.content_bounds()
    assert bounds is not None
    print(f"{count} elements, viewport 1920x1080")

    # Zoomed to show about 2000 elements at once, as in the spike criteria.
    zoom = 0.45
    start = Camera(bounds.x, bounds.y, zoom)
    view.set_camera(start)
    for _ in range(3):  # warm the geometry caches
        view.repaint()
    visible = len(view.candidates(view.camera.visible_rect(view._viewport())))
    print(f"visible elements: {visible}")
    pan = [Camera(start.x + i * 8 / zoom, start.y + i * 3 / zoom, zoom) for i in range(60)]
    report("pan", time_frames(view, app, pan))
    zooms = [start.zoomed_at(Point(960, 540), 1.0 + i * 0.01) for i in range(60)]
    report("zoom", time_frames(view, app, zooms))

    view.set_camera(start)
    ids = [e.id for e in session.document.ordered()[:50]]
    session.select(ids)
    drags = []
    for i in range(60):
        moved = session.document.with_elements(
            commands.move(session.document, ids, i * 2.0, i * 1.0)
        )
        view.set_preview(moved, ids)
        t = time.perf_counter()
        view.repaint()
        drags.append((time.perf_counter() - t) * 1000)
    view.set_preview(None)
    report("drag 50 selected", drags)


if __name__ == "__main__":
    main()
