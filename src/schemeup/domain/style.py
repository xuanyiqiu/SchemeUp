"""Visual style shared by every element type.

One style type covers everything (stroke, fill, text, arrowheads). Each
element only reads the fields that make sense for it, which keeps the
properties panel and the "apply to selection" logic simple.
"""

from dataclasses import dataclass
from enum import StrEnum

TRANSPARENT = "transparent"


class FillStyle(StrEnum):
    HACHURE = "hachure"
    CROSS_HATCH = "cross-hatch"
    SOLID = "solid"


class StrokeStyle(StrEnum):
    SOLID = "solid"
    DASHED = "dashed"
    DOTTED = "dotted"


class Roundness(StrEnum):
    SHARP = "sharp"
    ROUND = "round"


class Arrowhead(StrEnum):
    NONE = "none"
    ARROW = "arrow"
    TRIANGLE = "triangle"
    DOT = "dot"
    BAR = "bar"


class FontFamily(StrEnum):
    HAND = "hand"
    NORMAL = "normal"
    CODE = "code"


class TextAlign(StrEnum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class VerticalAlign(StrEnum):
    TOP = "top"
    MIDDLE = "middle"
    BOTTOM = "bottom"


STROKE_WIDTHS = (1.0, 2.0, 4.0)  # thin, bold, extra bold
ROUGHNESS_LEVELS = (0, 1, 2)  # architect (clean), artist, cartoonist
FONT_SIZES = (16.0, 20.0, 28.0, 36.0)  # S, M, L, XL
MIN_FONT_SIZE = 6.0
MAX_FONT_SIZE = 400.0


@dataclass(frozen=True, slots=True)
class Style:
    stroke_color: str = "#1e1e1e"
    fill_color: str = TRANSPARENT
    fill_style: FillStyle = FillStyle.HACHURE
    stroke_width: float = 2.0
    stroke_style: StrokeStyle = StrokeStyle.SOLID
    roughness: int = 1
    opacity: int = 100
    roundness: Roundness = Roundness.ROUND
    font_family: FontFamily = FontFamily.HAND
    font_size: float = 20.0
    text_align: TextAlign = TextAlign.CENTER
    vertical_align: VerticalAlign = VerticalAlign.MIDDLE
    start_head: Arrowhead = Arrowhead.NONE
    end_head: Arrowhead = Arrowhead.ARROW

    @property
    def has_fill(self) -> bool:
        return self.fill_color != TRANSPARENT


DEFAULT_STYLE = Style()
