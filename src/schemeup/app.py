"""Composition root: the one place that wires the layers together."""

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from schemeup import __version__
from schemeup.domain.sheets import GridSheet
from schemeup.ui.main_window import MainWindow


def main(argv: Sequence[str] | None = None) -> int:
    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("SchemeUp")
    app.setOrganizationName("SchemeUp")
    app.setApplicationVersion(__version__)

    window = MainWindow(sheet=GridSheet(cell_mm=5))
    window.show()
    return app.exec()
