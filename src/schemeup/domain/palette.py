"""Color palettes and color math (contrast, dark mode transform).

Stroke and fill use the same four hues in two tones: deep tones for strokes
and text (readable on light and dark canvases), pastels for fills. Values
come from Open Color, the palette Excalidraw uses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from schemeup.domain.style import TRANSPARENT


class PickerKind(StrEnum):
    STROKE = "stroke"
    FILL = "fill"
    BACKGROUND = "background"


@dataclass(frozen=True, slots=True)
class Swatch:
    name: str
    color: str


STROKE_SWATCHES = (
    Swatch("Black", "#1e1e1e"),
    Swatch("Blue", "#1971c2"),
    Swatch("Green", "#2b8a3e"),
    Swatch("Yellow", "#b35c00"),
    Swatch("Red", "#c92a2a"),
)

FILL_SWATCHES = (
    Swatch("Transparent", TRANSPARENT),
    Swatch("Blue", "#a5d8ff"),
    Swatch("Green", "#b2f2bb"),
    Swatch("Yellow", "#ffec99"),
    Swatch("Red", "#ffc9c9"),
)

BACKGROUND_SWATCHES = (
    Swatch("White", "#ffffff"),
    Swatch("Blue", "#e7f5ff"),
    Swatch("Green", "#ebfbee"),
    Swatch("Yellow", "#fff9db"),
    Swatch("Red", "#fff5f5"),
)

SWATCHES = {
    PickerKind.STROKE: STROKE_SWATCHES,
    PickerKind.FILL: FILL_SWATCHES,
    PickerKind.BACKGROUND: BACKGROUND_SWATCHES,
}


def parse_hex(color: str) -> tuple[float, float, float]:
    """'#rrggbb' or '#rgb' to channels in 0..1."""
    value = color.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) != 6:
        raise ValueError(f"not a hex color: {color!r}")
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(min(max(c, 0.0), 1.0) * 255):02x}" for c in rgb)


def is_valid_hex(color: str) -> bool:
    try:
        parse_hex(color)
    except ValueError:
        return False
    return True


def relative_luminance(color: str) -> float:
    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in parse_hex(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def dark_variant(color: str) -> str:
    """The color as shown on a dark canvas.

    Same math as the CSS filter `invert(93%) hue-rotate(180deg)` that Excalidraw
    uses: lightness flips, hue stays. White becomes #121212.
    """
    if color == TRANSPARENT:
        return color
    p = 0.93
    inverted = [c * (1 - p) + (1 - c) * p for c in parse_hex(color)]
    angle = math.radians(180)
    co, si = math.cos(angle), math.sin(angle)
    matrix = (
        (
            0.213 + co * 0.787 - si * 0.213,
            0.715 - co * 0.715 - si * 0.715,
            0.072 - co * 0.072 + si * 0.928,
        ),
        (
            0.213 - co * 0.213 + si * 0.143,
            0.715 + co * 0.285 + si * 0.140,
            0.072 - co * 0.072 - si * 0.283,
        ),
        (
            0.213 - co * 0.213 - si * 0.787,
            0.715 - co * 0.715 + si * 0.715,
            0.072 + co * 0.928 + si * 0.072,
        ),
    )
    r, g, b = (sum(row[j] * inverted[j] for j in range(3)) for row in matrix)
    return to_hex((r, g, b))
