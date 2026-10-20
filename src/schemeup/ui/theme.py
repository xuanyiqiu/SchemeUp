"""Colors, stylesheet, icons and the floating "island" panel used across the UI."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPaintEvent, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QWidget

from schemeup.rendering.fonts import RESOURCES

ACCENT = "#6d5dfc"


@dataclass(frozen=True, slots=True)
class Theme:
    dark: bool
    window: str
    panel: str
    border: str
    text: str
    muted: str
    accent: str
    accent_soft: str
    hover: str
    input: str
    selection: str
    shadow: int  # alpha of the darkest shadow layer


LIGHT = Theme(
    dark=False,
    window="#f6f6f8",
    panel="#ffffff",
    border="#e3e3ea",
    text="#1d1d22",
    muted="#6c6c78",
    accent=ACCENT,
    accent_soft="#e7e4ff",
    hover="#f2f1fb",
    input="#f4f4f7",
    selection=ACCENT,
    shadow=22,
)

DARK = Theme(
    dark=True,
    window="#151518",
    panel="#232328",
    border="#34343c",
    text="#e8e8ec",
    muted="#9b9ba6",
    accent="#a99fff",
    accent_soft="#3b3766",
    hover="#2d2c36",
    input="#2a2a31",
    selection="#a99fff",
    shadow=70,
)


def stylesheet(t: Theme) -> str:
    return f"""
    QWidget {{ color: {t.text}; font-size: 13px; }}
    QMainWindow, #page {{ background: {t.window}; }}
    QToolTip {{
        background: {t.panel}; color: {t.text}; border: 1px solid {t.border};
        border-radius: 6px; padding: 4px 8px;
    }}
    QToolButton {{
        background: transparent; border: none; border-radius: 7px; padding: 5px;
    }}
    QToolButton:hover {{ background: {t.hover}; }}
    QToolButton:pressed {{ background: {t.accent_soft}; }}
    QToolButton:checked {{ background: {t.accent_soft}; }}
    QToolButton:disabled {{ color: {t.muted}; }}
    QPushButton {{
        background: {t.input}; border: 1px solid {t.border}; border-radius: 7px; padding: 6px 12px;
    }}
    QPushButton:hover {{ background: {t.hover}; }}
    QPushButton:pressed {{ background: {t.accent_soft}; }}
    QPushButton#primary {{ background: {t.accent}; color: white; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {t.accent}; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QDateEdit {{
        background: {t.input}; border: 1px solid {t.border}; border-radius: 7px; padding: 5px 8px;
        selection-background-color: {t.accent}; selection-color: white;
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
        border: 1px solid {t.accent};
    }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background: {t.panel}; border: 1px solid {t.border};
        selection-background-color: {t.accent_soft};
        selection-color: {t.text}; outline: none;
    }}
    QMenu {{
        background: {t.panel}; border: 1px solid {t.border}; border-radius: 8px; padding: 6px;
    }}
    QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {t.hover}; }}
    QMenu::item:disabled {{ color: {t.muted}; }}
    QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 8px; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 4px; min-height: 30px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t.border}; border-radius: 4px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QTreeView, QListView, QListWidget {{
        background: transparent; border: none; outline: none;
    }}
    QTreeView::item, QListView::item {{ padding: 4px 2px; border-radius: 6px; }}
    QTreeView::item:hover, QListView::item:hover {{ background: {t.hover}; }}
    QTreeView::item:selected, QListView::item:selected {{
        background: {t.accent_soft}; color: {t.text};
    }}
    QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {t.panel}; border: 2px solid {t.accent}; width: 12px; height: 12px;
        margin: -6px 0; border-radius: 8px;
    }}
    QCheckBox::indicator {{ width: 16px; height: 16px; }}
    QLabel#muted {{ color: {t.muted}; }}
    QLabel#section {{ color: {t.muted}; font-size: 11px; font-weight: 600; }}
    QLabel#title {{ font-size: 18px; font-weight: 600; }}
    QDialog {{ background: {t.panel}; }}
    QTabBar::tab {{ padding: 6px 12px; border-radius: 6px; margin: 2px; }}
    QTabBar::tab:selected {{ background: {t.accent_soft}; }}
    QTabWidget::pane {{ border: none; }}
    """


class Island(QFrame):
    """A floating rounded panel with a soft shadow, drawn by hand.

    QGraphicsDropShadowEffect would re-render the panel offscreen every time
    the canvas under it repaints, which costs frames while panning."""

    SHADOW = 6

    def __init__(self, theme: Theme, parent: QWidget | None = None, radius: float = 10.0) -> None:
        super().__init__(parent)
        self._theme = theme
        self._radius = radius
        s = self.SHADOW
        self.setContentsMargins(s, s - 2, s, s + 2)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.SHADOW
        body = QRectF(self.rect()).adjusted(s, s - 2, -s, -s - 2)
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(s, 0, -1):
            alpha = int(self._theme.shadow * (1 - i / (s + 1)) / 2)
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(
                body.adjusted(-i, -i + 2, i, i + 2), self._radius + i, self._radius + i
            )
        painter.setBrush(QColor(self._theme.panel))
        painter.setPen(QPen(QColor(self._theme.border), 1))
        painter.drawRoundedRect(body, self._radius, self._radius)
        painter.end()


_SVG_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@lru_cache(maxsize=512)
def icon(name: str, color: str, stroke: float = 1.75) -> QIcon:
    """A Tabler icon recolored to `color`."""
    path = RESOURCES / "icons" / f"{name}.svg"
    try:
        svg = path.read_text(encoding="utf-8")
    except OSError:
        return QIcon()
    svg = _SVG_COMMENT.sub("", svg).replace("currentColor", color)
    svg = svg.replace('stroke-width="2"', f'stroke-width="{stroke}"')
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    result = QIcon()
    for size in (16, 20, 24, 32, 48):
        pixmap = QPixmap(QSize(size, size))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        result.addPixmap(pixmap)
    return result


def painted_icon(draw: object, color: str, size: int = 40) -> QIcon:
    """An icon drawn by a function `draw(painter, size, color)` (for style previews)."""
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw(painter, size, QColor(color))  # type: ignore[operator]
    painter.end()
    return QIcon(pixmap)


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path
