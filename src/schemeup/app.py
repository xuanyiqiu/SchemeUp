"""Composition root: the one place that wires the layers together."""

import os
import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from schemeup import __version__
from schemeup.domain.sheets import GridSheet
from schemeup.infrastructure.platform.motion import wants_reduced_motion
from schemeup.ui.main_window import MainWindow


def main(argv: Sequence[str] | None = None) -> int:
    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("SchemeUp")
    app.setOrganizationName("SchemeUp")
    app.setApplicationVersion(__version__)

    reduce_motion = wants_reduced_motion(os.environ.get("SCHEMEUP_MOTION"))
    window = MainWindow(sheet=GridSheet(cell_mm=5), reduce_motion=reduce_motion)
    window.show()
    return app.exec()
