"""Paints sheet lines with QPainter.

Lines are 1 px wide rects in screen space, snapped to whole pixels, so they
stay crisp at any zoom instead of smearing over two pixels. Each color is
blended with the background up front and painted opaque: Qt's translucent
line path costs about 20 ms on a full-HD viewport, opaque rects about 1 ms.
"""

import math
from dataclasses import dataclass

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QPainter

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


def _over(color: QColor, alpha: float, background: QColor) -> QColor:
    """`color` at `alpha` laid over an opaque `background`, as an opaque color."""
    a = color.alphaF() * alpha
    return QColor.fromRgbF(
        color.redF() * a + background.redF() * (1 - a),
        color.greenF() * a + background.greenF() * (1 - a),
        color.blueF() * a + background.blueF() * (1 - a),
    )


def paint_sheet(
    painter: QPainter,
    sheet: Sheet,
    camera: Camera,
    viewport: Size,
    style: SheetStyle,
    background: QColor,
) -> None:
    """Paint the sheet lines over `background`, which must be what is already underneath."""
    width, height = math.ceil(viewport.width), math.ceil(viewport.height)
    painter.save()
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    for group in visible_lines(sheet, camera.visible_rect(viewport), camera.zoom):
        if not group.positions or group.opacity <= 0:
            continue
        color = _over(style.color_for(group.family.weight), group.opacity, background)
        if group.family.orientation is Orientation.VERTICAL:
            for x in group.positions:
                painter.fillRect(QRect(round((x - camera.x) * camera.zoom), 0, 1, height), color)
        else:
            for y in group.positions:
                painter.fillRect(QRect(0, round((y - camera.y) * camera.zoom), width, 1), color)
    painter.restore()
