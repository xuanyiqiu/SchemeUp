from PySide6.QtGui import QColor, QImage, QPainter

from schemeup.domain.camera import Camera
from schemeup.domain.geometry import Size
from schemeup.domain.sheets import GridSheet
from schemeup.rendering.sheet_painter import LIGHT_SHEET_STYLE, paint_sheet

SIZE = Size(200, 120)


def painted(background: QColor, zoom: float = 1.0) -> QImage:
    image = QImage(int(SIZE.width), int(SIZE.height), QImage.Format.Format_RGB32)
    image.fill(background)
    painter = QPainter(image)
    paint_sheet(
        painter, GridSheet(cell_mm=5), Camera(0, 0, zoom), SIZE, LIGHT_SHEET_STYLE, background
    )
    painter.end()
    return image


def test_grid_lines_are_blended_with_the_background() -> None:
    white = QColor("white")
    image = painted(white)
    on_line = image.pixelColor(0, 60)  # x = 0 is a grid line
    off_line = image.pixelColor(5, 5)
    assert off_line == white
    assert on_line != white
    assert on_line.alpha() == 255  # opaque, so no per-frame blending cost
    assert on_line.lightness() > 200  # a faint line, not a black one


def test_grid_lines_follow_a_colored_background() -> None:
    cream = QColor("#fff3bf")
    image = painted(cream)
    assert image.pixelColor(5, 5) == cream
    assert image.pixelColor(0, 60).red() < cream.red()
