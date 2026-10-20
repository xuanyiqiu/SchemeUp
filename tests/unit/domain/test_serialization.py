from dataclasses import replace

import pytest

from schemeup.domain import commands
from schemeup.domain.binding import binding_for
from schemeup.domain.commands import ShapeKind
from schemeup.domain.document import CanvasSettings, Document
from schemeup.domain.elements import Arrow, Diamond, Freedraw, Image, Text
from schemeup.domain.errors import UnsupportedFormatError
from schemeup.domain.geometry import Point, Rect
from schemeup.domain.serialization import CURRENT_VERSION, document_from_dict, document_to_dict
from schemeup.domain.style import Arrowhead, FillStyle, FontFamily, Style


def sample() -> Document:
    style = Style(stroke_color="#1971c2", fill_color="#a5d8ff", fill_style=FillStyle.CROSS_HATCH)
    shape = commands.make_shape(ShapeKind.DIAMOND, Rect(0, 0, 120, 80), style)
    assert isinstance(shape, Diamond)
    shape = replace(shape, label="decide", group_ids=("g1",), angle=0.5)
    arrow = commands.make_linear(
        True, [Point(120, 40), Point(300, 40), Point(320, 90)], Style(end_head=Arrowhead.DOT)
    )
    assert isinstance(arrow, Arrow)
    arrow = replace(arrow, start_binding=binding_for(shape, Point(120, 40), 8), label="yes")
    stroke = commands.make_freedraw(
        [Point(0, 0), Point(5, 5), Point(9, 2)], [0.2, 0.6, 0.4], Style(), False
    )
    text = commands.make_text(Point(10, 200), "hello\nworld", Style(font_family=FontFamily.CODE))
    image = commands.make_image(Rect(0, 300, 64, 64), "abc123", Style())
    frame = commands.make_shape(ShapeKind.FRAME, Rect(-50, -50, 600, 500), Style())
    settings = CanvasSettings(background="#fff9db", sheet="seyes", page_size="A4")
    return Document.of([frame, shape, arrow, stroke, text, image], settings)


def test_document_round_trips_through_dicts() -> None:
    document = sample()
    restored = document_from_dict(document_to_dict(document))
    assert restored.order == document.order
    assert restored.settings == document.settings
    for original, copy in zip(document.ordered(), restored.ordered(), strict=True):
        assert copy == original


def test_types_survive() -> None:
    restored = document_from_dict(document_to_dict(sample()))
    kinds = {type(e) for e in restored.ordered()}
    assert {Arrow, Freedraw, Text, Image} <= kinds


def test_newer_format_is_refused() -> None:
    data = document_to_dict(sample())
    data["version"] = CURRENT_VERSION + 1
    with pytest.raises(UnsupportedFormatError):
        document_from_dict(data)


def test_wrong_format_is_refused() -> None:
    with pytest.raises(UnsupportedFormatError):
        document_from_dict({"format": "excalidraw", "version": 2})


def test_unknown_style_values_fall_back_to_defaults() -> None:
    data = document_to_dict(sample())
    data["elements"][1]["style"]["fill_style"] = "zigzag"
    data["elements"][1]["style"]["something_new"] = 1
    restored = document_from_dict(data)
    assert restored.ordered()[1].style.fill_style == Style().fill_style
