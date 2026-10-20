from PySide6.QtWidgets import QMainWindow

from schemeup.application.editor import EditorSession
from schemeup.application.ports import AssetStore
from schemeup.ui.editor_page import EditorPage
from schemeup.ui.theme import Theme


class MainWindow(QMainWindow):
    def __init__(
        self,
        session: EditorSession,
        theme: Theme,
        *,
        assets: AssetStore | None = None,
        reduce_motion: bool = False,
    ) -> None:
        super().__init__()
        self.setWindowTitle("SchemeUp")
        self.resize(1360, 860)
        self.editor = EditorPage(session, theme, assets=assets, reduce_motion=reduce_motion)
        self.setCentralWidget(self.editor)
        self.canvas = self.editor.canvas
