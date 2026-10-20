"""Composition root: the one place that wires the layers together."""

import os
import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from schemeup import __version__
from schemeup.application.editor import EditorSession
from schemeup.application.ports import MemoryAssetStore
from schemeup.domain.document import Document
from schemeup.infrastructure.platform.motion import wants_reduced_motion
from schemeup.rendering.fonts import register_fonts
from schemeup.rendering.text import QtTextMeasurer
from schemeup.ui.main_window import MainWindow
from schemeup.ui.theme import LIGHT, stylesheet


def main(argv: Sequence[str] | None = None) -> int:
    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("SchemeUp")
    app.setOrganizationName("SchemeUp")
    app.setApplicationVersion(__version__)
    register_fonts()
    app.setStyleSheet(stylesheet(LIGHT))

    session = EditorSession(Document(), QtTextMeasurer())
    reduce_motion = wants_reduced_motion(os.environ.get("SCHEMEUP_MOTION"))
    window = MainWindow(session, LIGHT, assets=MemoryAssetStore(), reduce_motion=reduce_motion)
    window.show()
    return app.exec()
