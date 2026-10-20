from PySide6.QtWidgets import QMainWindow

from schemeup.domain.sheets import Sheet
from schemeup.ui.canvas_view import CanvasView


class MainWindow(QMainWindow):
    def __init__(self, sheet: Sheet, *, reduce_motion: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("SchemeUp")
        self.resize(1280, 800)
        self.canvas = CanvasView(sheet, reduce_motion=reduce_motion, parent=self)
        self.setCentralWidget(self.canvas)
