"""Frame time of a camera pan at common screen sizes.

Run with `uv run python benchmarks/pan_bench.py [elements]`. It paints a note of
that many hand-drawn elements (50 is a busy page of notes) while the camera moves,
at full HD, 1440p and 4K, so a screen larger than the one I develop on still has a
number. The offscreen platform is used, so only compare runs with each other.
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from benchmarks.canvas_bench import scene
from schemeup.application.editor import EditorSession
from schemeup.domain.camera import Camera
from schemeup.domain.document import Document
from schemeup.rendering.fonts import register_fonts
from schemeup.rendering.text import QtTextMeasurer
from schemeup.ui.canvas.view import CanvasView

SIZES = ((1920, 1080), (2560, 1440), (3840, 2160))
FRAMES = 60


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    app = QApplication(sys.argv[:1])
    register_fonts()
    session = EditorSession(Document(), QtTextMeasurer())
    session.add(scene(count), select=False)
    view = CanvasView(session, reduce_motion=True)
    print(f"{count} elements, one pan step per frame")
    for width, height in SIZES:
        view.resize(width, height)
        view.show()
        app.processEvents()
        view.set_camera(Camera(0, 0, 1.0))
        view.repaint()
        start = time.perf_counter()
        for i in range(FRAMES):
            view.set_camera(Camera(i * 7.0, i * 3.0, 1.0))
            view.repaint()
        ms = (time.perf_counter() - start) / FRAMES * 1000
        print(f"  {width}x{height}: {ms:6.1f} ms per frame")


if __name__ == "__main__":
    main()
