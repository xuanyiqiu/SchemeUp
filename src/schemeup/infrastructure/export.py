"""Writes notes to PNG, SVG, PDF, Word and .schemeup files.

Every format draws with the same scene renderer as the screen, so exports look
like what you see. Word can't represent hand-drawn shapes, so drawings go in
as high-resolution images and the note's text follows as editable paragraphs.
"""

from __future__ import annotations

import base64
import io
import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF, QRect, QRectF, QSize
from PySide6.QtGui import QImage, QImageWriter, QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtSvg import QSvgGenerator

from schemeup.application.export import ExportFormat, ExportRequest, ExportScope
from schemeup.application.ports import AssetStore
from schemeup.domain.document import Document
from schemeup.domain.elements import Image, Text
from schemeup.domain.errors import ExportError
from schemeup.domain.export_layout import MARGIN_MM, PageLayout, export_regions
from schemeup.domain.geometry import Rect
from schemeup.domain.serialization import document_to_dict
from schemeup.domain.sheets import MM
from schemeup.domain.style import FontFamily
from schemeup.rendering.export_render import export_region, render_image, render_region
from schemeup.rendering.images import AssetImages
from schemeup.rendering.scene import SceneRenderer

PAGE_IDS = {
    "A4": QPageSize.PageSizeId.A4,
    "A5": QPageSize.PageSizeId.A5,
    "Letter": QPageSize.PageSizeId.Letter,
}
WORD_DPI = 300
NOTE_FORMAT = "schemeup.note"


def image_bytes(image: QImage, fmt: bytes = b"PNG") -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    QImageWriter(buffer, fmt).write(image)
    buffer.close()
    return bytes(data.data())


def text_only(document: Document) -> bool:
    """A note made only of text, like most meeting notes."""
    elements = document.ordered()
    return bool(elements) and all(isinstance(e, Text) for e in elements)


class FileExporter:
    def __init__(self, assets: AssetStore | None) -> None:
        self._renderer = SceneRenderer(AssetImages(assets))
        self._assets = assets

    def export(
        self, document: Document, request: ExportRequest, selection: frozenset[str], path: Path
    ) -> None:
        only = selection if request.scope == ExportScope.SELECTION and selection else None
        try:
            match request.format:
                case ExportFormat.PNG:
                    self._png(document, request, only, path)
                case ExportFormat.SVG:
                    self._svg(document, request, only, path)
                case ExportFormat.PDF:
                    self._pdf(document, request, only, path)
                case ExportFormat.DOCX:
                    self._docx(document, request, only, path)
                case ExportFormat.SCHEMEUP:
                    self._note_file(document, request, path)
        except OSError as error:
            raise ExportError(f"couldn't write {path.name}: {error}") from error

    def _region(self, document: Document, only: frozenset[str] | None) -> Rect:
        region = export_region(document, only or frozenset())
        if region is None:
            raise ExportError("there is nothing to export: the note is empty")
        return region

    def _png(
        self, document: Document, request: ExportRequest, only: frozenset[str] | None, path: Path
    ) -> None:
        image = render_image(
            document,
            self._region(document, only),
            self._renderer,
            request.scale,
            dark=request.dark,
            background=request.background,
            only=only,
        )
        if not image.save(str(path)):
            raise ExportError(f"couldn't write {path.name}")

    def _svg(
        self, document: Document, request: ExportRequest, only: frozenset[str] | None, path: Path
    ) -> None:
        region = self._region(document, only)
        generator = QSvgGenerator()
        generator.setFileName(str(path))
        generator.setSize(QSize(round(region.width), round(region.height)))
        generator.setViewBox(QRect(0, 0, round(region.width), round(region.height)))
        generator.setTitle(request.title)
        generator.setDescription("Exported from SchemeUp")
        painter = QPainter(generator)
        self._renderer.text_as_paths = request.text_as_paths
        try:
            render_region(
                painter,
                document,
                region,
                self._renderer,
                QRectF(0, 0, region.width, region.height),
                dark=request.dark,
                background=request.background,
                only=only,
            )
        finally:
            self._renderer.text_as_paths = False
            painter.end()

    def _pages(
        self, document: Document, request: ExportRequest, only: frozenset[str] | None
    ) -> list[Rect]:
        region = (
            None
            if request.layout in (PageLayout.FRAMES, PageLayout.PAGES)
            else self._region(document, only)
        )
        regions = export_regions(document, request.layout, region, request.page, request.landscape)
        if not regions:
            raise ExportError("there is nothing to export with this page layout")
        return regions

    def _pdf(
        self, document: Document, request: ExportRequest, only: frozenset[str] | None, path: Path
    ) -> None:
        writer = QPdfWriter(str(path))
        writer.setTitle(request.title)
        writer.setCreator("SchemeUp")
        writer.setResolution(300)
        writer.setPageSize(QPageSize(PAGE_IDS.get(request.page, QPageSize.PageSizeId.A4)))
        writer.setPageOrientation(
            QPageLayout.Orientation.Landscape
            if request.landscape
            else QPageLayout.Orientation.Portrait
        )
        margins = 0.0 if request.layout == PageLayout.PAGES else MARGIN_MM
        writer.setPageMargins(
            QMarginsF(margins, margins, margins, margins), QPageLayout.Unit.Millimeter
        )
        regions = self._pages(document, request, only)
        painter = QPainter(writer)
        try:
            for i, region in enumerate(regions):
                if i:
                    writer.newPage()
                paint = writer.pageLayout().paintRectPixels(writer.resolution())
                target = QRectF(0, 0, paint.width(), paint.height())
                if request.layout in (PageLayout.TILES, PageLayout.PAGES):
                    # True size: one canvas unit is 1/96 inch on paper.
                    scale = writer.resolution() / 96
                    target = QRectF(0, 0, region.width * scale, region.height * scale)
                render_region(
                    painter,
                    document,
                    region,
                    self._renderer,
                    target,
                    dark=request.dark,
                    background=request.background,
                    only=only,
                )
        finally:
            painter.end()

    def _docx(
        self, document: Document, request: ExportRequest, only: frozenset[str] | None, path: Path
    ) -> None:
        from docx import Document as WordDocument
        from docx.enum.section import WD_ORIENT
        from docx.shared import Mm, Pt, RGBColor

        word = WordDocument()
        section = word.sections[0]
        w_mm, h_mm = {"A4": (210, 297), "A5": (148, 210), "Letter": (215.9, 279.4)}.get(
            request.page, (210, 297)
        )
        if request.landscape:
            w_mm, h_mm = h_mm, w_mm
            section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = Mm(w_mm), Mm(h_mm)
        margin = Mm(18)
        section.left_margin = section.right_margin = section.top_margin = section.bottom_margin = (
            margin
        )
        word.add_heading(request.title, level=1)
        meta = word.add_paragraph()
        details = datetime.now().strftime("Exported %d %B %Y")
        if request.tags:
            details += "  ·  " + "  ".join(f"#{t}" for t in request.tags)
        run = meta.add_run(details)
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x86, 0x8E, 0x96)

        if text_only(document) and only is None:
            # Pure text notes stay editable text in Word.
            for element in sorted(document.ordered(), key=lambda e: (round(e.y / 24), e.x)):
                assert isinstance(element, Text)
                for paragraph_text in element.text.split("\n"):
                    paragraph = word.add_paragraph()
                    run = paragraph.add_run(paragraph_text)
                    if element.style.font_family == FontFamily.CODE:
                        run.font.name = "Consolas"
                        run.font.size = Pt(10)
        else:
            usable = (w_mm - 36) * MM
            for i, region in enumerate(self._pages(document, request, only)):
                image = render_image(
                    document,
                    region,
                    self._renderer,
                    WORD_DPI / 96,
                    dark=request.dark,
                    background=True,
                    only=only,
                )
                width_mm = min(region.width, usable) / MM
                word.add_picture(io.BytesIO(image_bytes(image)), width=Mm(width_mm))
                frames = document.frames()
                if request.layout == PageLayout.FRAMES and i < len(frames):
                    caption = word.add_paragraph(frames[i].name)
                    caption.runs[0].font.size = Pt(9)
            text = document.plain_text()
            if request.text_appendix and text.strip():
                word.add_heading("Text in this note", level=2)
                for line in text.split("\n"):
                    word.add_paragraph(line)
        word.save(str(path))

    def _note_file(self, document: Document, request: ExportRequest, path: Path) -> None:
        files: dict[str, str] = {}
        for element in document.ordered():
            if isinstance(element, Image) and element.asset_id and self._assets is not None:
                data = self._assets.get(element.asset_id)
                if data:
                    files[element.asset_id] = base64.b64encode(data).decode("ascii")
        payload = {
            "format": NOTE_FORMAT,
            "version": 1,
            "note": {"title": request.title, "tags": list(request.tags)},
            "document": document_to_dict(document),
            "files": files,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
