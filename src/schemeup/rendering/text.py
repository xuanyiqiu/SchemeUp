"""Text layout with Qt, shared by measuring and drawing so they always agree."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from PySide6.QtCore import QPointF
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QTextLayout,
    QTextOption,
)

from schemeup.domain.geometry import Size
from schemeup.domain.style import FontFamily, TextAlign
from schemeup.rendering.fonts import canvas_font


@dataclass(frozen=True, slots=True)
class LaidOutLine:
    text: str
    x: float  # left edge inside the block
    baseline: float


@dataclass(frozen=True, slots=True)
class TextBlock:
    lines: tuple[LaidOutLine, ...]
    width: float
    height: float
    line_height: float
    family: FontFamily
    size: float
    # How far a plain text editor, which puts the first baseline one full font ascent
    # below its top, must be raised so its text lines up with the tight box above.
    inset: float = 0.0

    def font(self) -> QFont:
        return canvas_font(self.family, self.size)


ASCENDER_OVER_CAP = 1.1  # tall letters (l, d, b) rise this far over the capital height
DESCENDER = 0.18  # room under the baseline for g, y and p, in font sizes


def _wrap(paragraph: str, font: QFont, max_width: float) -> list[tuple[str, float]]:
    layout = QTextLayout(paragraph, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    lines: list[tuple[str, float]] = []
    layout.beginLayout()
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(max_width)
        start, length = line.textStart(), line.textLength()
        lines.append((paragraph[start : start + length].rstrip(" "), line.naturalTextWidth()))
    layout.endLayout()
    return lines or [("", 0.0)]


@lru_cache(maxsize=4096)
def layout_text(
    text: str, family: FontFamily, size: float, max_width: float | None, align: TextAlign
) -> TextBlock:
    font = canvas_font(family, size)
    metrics = QFontMetricsF(font)
    line_height = metrics.lineSpacing()
    # The box hugs the glyphs: from the tallest letters down to just under the baseline,
    # not the font's full ascent and descent, which leave a gap above and below.
    ink_top = metrics.capHeight() * ASCENDER_OVER_CAP
    ink_bottom = font.pixelSize() * DESCENDER
    raw: list[tuple[str, float]] = []
    for paragraph in text.split("\n"):
        if max_width is None or not paragraph:
            raw.append((paragraph, metrics.horizontalAdvance(paragraph)))
        else:
            raw += _wrap(paragraph, font, max(max_width, 1.0))
    natural = max((w for _, w in raw), default=0.0)
    width = natural if max_width is None else max(max_width, 1.0)
    lines: list[LaidOutLine] = []
    for i, (content, line_width) in enumerate(raw):
        if align == TextAlign.CENTER:
            x = (width - line_width) / 2
        elif align == TextAlign.RIGHT:
            x = width - line_width
        else:
            x = 0.0
        lines.append(LaidOutLine(content, x, i * line_height + ink_top))
    return TextBlock(
        tuple(lines),
        max(natural if max_width is None else width, 1.0),
        (len(raw) - 1) * line_height + ink_top + ink_bottom,
        line_height,
        family,
        size,
        metrics.ascent() - ink_top,
    )


class QtTextMeasurer:
    """`TextMeasurer` implementation backed by the same layout code as drawing."""

    def measure(self, text: str, family: FontFamily, size: float, max_width: float | None) -> Size:
        block = layout_text(text, family, size, max_width, TextAlign.LEFT)
        width = block.width if max_width is None else max(max_width, 1.0)
        return Size(width, block.height)


def draw_block(
    painter: QPainter, block: TextBlock, x: float, y: float, color: QColor, as_paths: bool = False
) -> None:
    """Draw laid-out text; `as_paths` turns glyphs into outlines (for portable SVG files)."""
    font = block.font()
    if as_paths:
        path = QPainterPath()
        for line in block.lines:
            if line.text:
                path.addText(QPointF(x + line.x, y + line.baseline), font, line.text)
        painter.fillPath(path, color)
        return
    painter.setFont(font)
    painter.setPen(color)
    for line in block.lines:
        if line.text:
            painter.drawText(QPointF(x + line.x, y + line.baseline), line.text)
