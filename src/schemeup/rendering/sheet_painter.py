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


LIGHT_SHEET_STYLE = SheetStyle(
    minor=QColor("#e1e1e8"),
    major=QColor("#c8c8d2"),
    accent=QColor("#f2a7a7"),
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
