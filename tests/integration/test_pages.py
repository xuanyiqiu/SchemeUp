"""Paged notes: pages grow with the content, and only what is on a page counts."""

import itertools
import json
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from schemeup.application.editor import EditorSession
from schemeup.application.export import ExportFormat, ExportRequest
from schemeup.application.ports import MemoryAssetStore
from schemeup.domain import commands
from schemeup.domain.commands import ShapeKind
from schemeup.domain.document import CanvasSettings, Document
from schemeup.domain.elements import Element, Rectangle
from schemeup.domain.export_layout import (
    off_page_ids,
    page_rects,
    pages_of,
    searchable_text,
)
from schemeup.domain.geometry import Rect
from schemeup.domain.serialization import document_from_dict, document_to_dict
from schemeup.domain.style import Style
from schemeup.infrastructure.export import FileExporter
from schemeup.rendering.fonts import register_fonts
from schemeup.rendering.text import QtTextMeasurer

A4 = CanvasSettings(page_size="A4")


def box(x: float, y: float, label: str = "") -> Rectangle:
    element = commands.make_shape(ShapeKind.RECTANGLE, Rect(x, y, 100, 60), Style())
    assert isinstance(element, Rectangle)
    return replace(element, label=label)


def note(*elements: Element, settings: CanvasSettings = A4) -> Document:
    return Document.of(elements, settings)


def test_every_page_lines_up_with_the_first() -> None:
    pages = page_rects("A4", False, 5000)
    assert len({page.left for page in pages}) == 1
    assert all(b.top > a.bottom for a, b in itertools.pairwise(pages))


def test_an_empty_paged_note_has_one_page() -> None:
    assert len(pages_of(Document(settings=A4))) == 1
    assert pages_of(Document()) == []  # an infinite canvas has none


def test_content_past_the_last_page_adds_a_page() -> None:
    first = pages_of(Document(settings=A4))[0]
    document = note(box(0, first.bottom + 100))
    assert len(pages_of(document)) == 2


def test_content_beside_the_pages_does_not_add_pages() -> None:
    first = pages_of(Document(settings=A4))[0]
    assert len(pages_of(note(box(first.right + 500, 5000)))) == 1


def test_text_being_typed_can_reach_into_a_new_page() -> None:
    document = Document(settings=A4)
    first = pages_of(document)[0]
    assert len(pages_of(document, extra_bottom=first.bottom + 10)) == 2
    assert len(pages_of(document, extra_bottom=first.bottom - 10)) == 1


def test_add_page_appends_an_empty_page_and_can_be_undone() -> None:
    session = EditorSession(Document(settings=A4), QtTextMeasurer())
    page = session.add_page()
    assert page is not None
    assert len(pages_of(session.document)) == 2
    assert page == pages_of(session.document)[-1]
    session.add_page()
    assert len(pages_of(session.document)) == 3
    session.undo()
    assert len(pages_of(session.document)) == 2


def test_add_page_does_nothing_on_an_infinite_canvas() -> None:
    session = EditorSession(Document(), QtTextMeasurer())
    assert session.add_page() is None
    assert not session.can_undo


def test_the_page_count_survives_saving() -> None:
    document = Document(settings=replace(A4, page_count=4))
    restored = document_from_dict(json.loads(json.dumps(document_to_dict(document))))
    assert restored.settings.page_count == 4
    assert len(pages_of(restored)) == 4


def test_old_notes_without_a_page_count_still_open() -> None:
    data = document_to_dict(Document(settings=A4))
    del data["settings"]["page_count"]
    assert document_from_dict(data).settings.page_count == 1


def test_only_the_pages_are_searchable() -> None:
    first = pages_of(Document(settings=A4))[0]
    on_page = box(0, 0, "inside the sheet")
    beside = box(first.right + 300, 0, "scribble beside it")
    document = note(on_page, beside)
    assert off_page_ids(document) == {beside.id}
    assert "inside the sheet" in searchable_text(document)
    assert "scribble" not in searchable_text(document)
    # An infinite canvas keeps everything.
    assert "scribble" in searchable_text(Document.of([on_page, beside]))


@pytest.fixture
def exporter(qapp: QApplication) -> FileExporter:
    register_fonts()
    return FileExporter(MemoryAssetStore())


def test_png_of_a_paged_note_is_its_pages(
    exporter: FileExporter, tmp_path: Path, qapp: QApplication
) -> None:
    pages = pages_of(Document(settings=A4))
    document = note(box(0, 0, "one"), box(pages[0].right + 2000, 0, "far away"))
    path = tmp_path / "paged.png"
    exporter.export(document, ExportRequest(ExportFormat.PNG, scale=1.0), frozenset(), path)
    image = QImage(str(path))
    assert image.width() == pytest.approx(pages[0].width, abs=2)
    assert image.height() == pytest.approx(pages[0].height, abs=2)


def test_an_infinite_note_still_exports_all_its_content(
    exporter: FileExporter, tmp_path: Path
) -> None:
    document = Document.of([box(0, 0), box(2000, 0)])
    path = tmp_path / "infinite.png"
    exporter.export(document, ExportRequest(ExportFormat.PNG, scale=1.0), frozenset(), path)
    assert QImage(str(path)).width() > 2000


def test_exports_do_not_disturb_later_exports(exporter: FileExporter, tmp_path: Path) -> None:
    paged = note(box(0, 0))
    infinite = Document.of([box(0, 0), box(2000, 0)])
    request = ExportRequest(ExportFormat.PNG, scale=1.0)
    exporter.export(paged, request, frozenset(), tmp_path / "a.png")
    exporter.export(infinite, request, frozenset(), tmp_path / "b.png")
    assert QImage(str(tmp_path / "b.png")).width() > 2000
