"""Bundled fonts and the QFont for each canvas font family."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

from schemeup.domain.style import FontFamily

RESOURCES = Path(__file__).resolve().parent.parent / "resources"

_FILES = {
    FontFamily.HAND: ("ShantellSans.ttf", "Shantell Sans"),
    FontFamily.NORMAL: ("Inter.ttf", "Inter"),
    FontFamily.CODE: ("JetBrainsMono.ttf", "JetBrains Mono"),
}
_families: dict[FontFamily, str] = {}


def register_fonts() -> None:
    """Load the bundled fonts. Needs a QGuiApplication; safe to call twice."""
    if _families:
        return
    for family, (file_name, fallback) in _FILES.items():
        font_id = QFontDatabase.addApplicationFont(str(RESOURCES / "fonts" / file_name))
        names = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        _families[family] = names[0] if names else fallback


def family_name(family: FontFamily) -> str:
    return _families.get(family, _FILES[family][1])


def canvas_font(family: FontFamily, size: float) -> QFont:
    """Font for canvas text, sized in canvas units (pixels at 100% zoom).

    Hinting is off so the layout is the same at every zoom level."""
    font = QFont(family_name(family))
    font.setPixelSize(max(1, round(size)))
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font
