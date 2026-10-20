"""Paints sheet lines with QPainter.

Lines are drawn in screen space with a 1 px cosmetic pen and antialiasing
off, so they stay crisp at any zoom instead of smearing over two pixels.
"""

from dataclasses import dataclass

from PySide6.QtCore import QLineF
from PySide6.QtGui import QColor, QPainter, QPen

from schemeup.domain.camera import Camera
from schemeup.domain.geometry import Size
from schemeup.domain.sheets import Orientation, Sheet, Weight, visible_lines


@dataclass(frozen=True, eq=False)
class SheetStyle:
    minor: QColor
    major: QColor
    accent: QColor

    def color_for(self, weight: Weight) -> QColor:
        match weight:
            case Weight.MINOR:
                return self.minor
            case Weight.MAJOR:
                return self.major
            case Weight.ACCENT:
                return self.accent


# Translucent colors, so the lines look right on any background color.
LIGHT_SHEET_STYLE = SheetStyle(
    minor=QColor(30, 30, 60, 30),
    major=QColor(30, 30, 60, 58),
    accent=QColor(230, 70, 70, 150),
)

DARK_SHEET_STYLE = SheetStyle(
    minor=QColor(255, 255, 255, 22),
    major=QColor(255, 255, 255, 42),
    accent=QColor(255, 120, 120, 130),
)


def paint_sheet(
    painter: QPainter, sheet: Sheet, camera: Camera, viewport: Size, style: SheetStyle
) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    for group in visible_lines(sheet, camera.visible_rect(viewport), camera.zoom):
        if not group.positions or group.opacity <= 0:
            continue
        color = QColor(style.color_for(group.family.weight))
        color.setAlphaF(color.alphaF() * group.opacity)
        pen = QPen(color, 1.0)
        pen.setCosmetic(True)
        painter.setPen(pen)

        if group.family.orientation is Orientation.VERTICAL:
            xs = ((x - camera.x) * camera.zoom for x in group.positions)
            lines = [QLineF(x, 0, x, viewport.height) for x in xs]
        else:
            ys = ((y - camera.y) * camera.zoom for y in group.positions)
            lines = [QLineF(0, y, viewport.width, y) for y in ys]
        # One drawLines call per group keeps the Python side to a single C++ call.
        painter.drawLines(lines)
    painter.restore()
