"""Built-in note templates: meeting, LeetCode problem, architecture sketch, quick note.

Templates are documents built in code, so they always use the current element
model and never need migrating.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from schemeup.domain import commands
from schemeup.domain.commands import ShapeKind
from schemeup.domain.document import CanvasSettings, Document
from schemeup.domain.elements import Element, Text, touched
from schemeup.domain.geometry import Point, Rect
from schemeup.domain.style import FillStyle, FontFamily, Style, TextAlign

QUICK_NOTE_WIDTH = 640.0

_HEADING = Style(font_size=28.0, text_align=TextAlign.LEFT, font_family=FontFamily.HAND)
_BODY = Style(font_size=20.0, text_align=TextAlign.LEFT, font_family=FontFamily.HAND)
_MUTED = Style(
    font_size=16.0, text_align=TextAlign.LEFT, stroke_color="#868e96", font_family=FontFamily.NORMAL
)


def _text(x: float, y: float, text: str, style: Style, width: float | None = None) -> Text:
    element = commands.make_text(Point(x, y), text, style)
    if width is not None:
        element = replace(element, width=width, auto_width=False)
    return element


def quick_note(body: str = "") -> Document:
    """A note that is just a block of text, ready to type into."""
    block = _text(0, 0, body, _BODY, QUICK_NOTE_WIDTH)
    return Document.of([block], CanvasSettings(sheet="lines"))


def meeting(now: datetime) -> Document:
    elements: list[Element] = [
        _text(0, 0, "Meeting", _HEADING),
        _text(0, 44, now.strftime("%A %d %B %Y, %H:%M"), _MUTED),
        _text(0, 100, "Attendees\n- ", _BODY, QUICK_NOTE_WIDTH),
        _text(0, 200, "Notes\n- ", _BODY, QUICK_NOTE_WIDTH),
        _text(0, 360, "Action items\n- [ ] ", _BODY, QUICK_NOTE_WIDTH),
    ]
    return Document.of(elements, CanvasSettings(sheet="lines"))


def leetcode(now: datetime) -> Document:
    code = Style(font_size=16.0, text_align=TextAlign.LEFT, font_family=FontFamily.CODE)
    frame = commands.make_shape(ShapeKind.FRAME, Rect(-40, 520, 760, 320), Style())
    frame = touched(frame, name="Sketch")
    elements: list[Element] = [
        _text(0, 0, "Problem", _HEADING),
        _text(0, 44, "Difficulty: Medium   ·   Pattern: ?   ·   Link: ", _MUTED),
        _text(0, 100, "Idea\n", _BODY, QUICK_NOTE_WIDTH),
        _text(0, 220, "Complexity\nTime O(?)   Space O(?)", _BODY, QUICK_NOTE_WIDTH),
        _text(0, 330, "def solve():\n    pass", code, QUICK_NOTE_WIDTH),
        frame,
    ]
    return Document.of(elements, CanvasSettings(sheet="grid-5"))


def architecture(now: datetime) -> Document:
    box = Style(fill_color="#a5d8ff", fill_style=FillStyle.HACHURE, stroke_color="#1971c2")
    store = Style(fill_color="#b2f2bb", fill_style=FillStyle.HACHURE, stroke_color="#2b8a3e")
    client = commands.make_shape(ShapeKind.RECTANGLE, Rect(0, 120, 180, 90), box)
    service = commands.make_shape(ShapeKind.RECTANGLE, Rect(320, 120, 200, 90), box)
    database = commands.make_shape(ShapeKind.ELLIPSE, Rect(660, 115, 180, 100), store)
    client = touched(client, label="Client")
    service = touched(service, label="Service")
    database = touched(database, label="Database")
    elements: list[Element] = [_text(0, 0, "Architecture", _HEADING), client, service, database]
    return Document.of(elements, CanvasSettings(sheet="grid-5"))


def welcome(now: datetime) -> Document:
    """The note created on first launch: a short tour drawn on the canvas itself."""
    blue = Style(fill_color="#a5d8ff", stroke_color="#1971c2")
    green = Style(fill_color="#b2f2bb", stroke_color="#2b8a3e")
    yellow = Style(fill_color="#ffec99", stroke_color="#b35c00")
    capture = touched(
        commands.make_shape(ShapeKind.RECTANGLE, Rect(0, 150, 220, 100), yellow),
        label="Ctrl+Alt+N\nquick note",
    )
    library = touched(
        commands.make_shape(ShapeKind.RECTANGLE, Rect(330, 150, 220, 100), blue),
        label="Folders, tags\nand search",
    )
    views = touched(
        commands.make_shape(ShapeKind.ELLIPSE, Rect(660, 140, 230, 120), green),
        label="Boards and\ncalendar",
    )
    first = commands.make_linear(True, [Point(225, 200), Point(325, 200)], Style())
    second = commands.make_linear(True, [Point(555, 200), Point(655, 200)], Style())
    elements: list[Element] = [
        _text(0, 0, "Welcome to SchemeUp", _HEADING),
        _text(0, 46, "Every note is an infinite canvas. Double-click anywhere to type.", _MUTED),
        capture,
        first,
        library,
        second,
        views,
        _text(
            0,
            330,
            "Tools: V select, R rectangle, D diamond, O ellipse, A arrow, L line,"
            " P draw, T text, E eraser.\n"
            "Hold Space and drag to pan, Ctrl + wheel to zoom, Ctrl+K for every command.",
            _BODY,
            QUICK_NOTE_WIDTH + 300,
        ),
    ]
    return Document.of(elements, CanvasSettings(sheet="grid-5"))


@dataclass(frozen=True, slots=True)
class Template:
    id: str
    name: str
    title: str  # strftime pattern for the default note title
    build: Callable[[datetime], Document]


TEMPLATES: tuple[Template, ...] = (
    Template("blank", "Blank note", "Note %Y-%m-%d %H:%M", lambda _now: Document()),
    Template("quick", "Quick note", "Quick note %Y-%m-%d %H:%M", lambda _now: quick_note()),
    Template("meeting", "Meeting", "Meeting %Y-%m-%d %H:%M", meeting),
    Template("leetcode", "LeetCode problem", "LeetCode %Y-%m-%d", leetcode),
    Template("architecture", "Architecture sketch", "Architecture %Y-%m-%d", architecture),
)
TEMPLATES_BY_ID = {t.id: t for t in TEMPLATES}
