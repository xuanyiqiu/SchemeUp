"""The export dialog: format, pages and a live preview of what will be written."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from schemeup.application.export import Exporter, ExportFormat, ExportRequest, ExportScope
from schemeup.domain.document import Document
from schemeup.domain.errors import SchemeUpError
from schemeup.domain.export_layout import (
    PageLayout,
    export_regions,
    fit_scale,
    is_infinite,
    page_size,
    printable_size,
)
from schemeup.rendering.export_render import export_region, render_region
from schemeup.rendering.scene import SceneRenderer
from schemeup.ui.theme import Theme, icon

FORMAT_LABELS = (
    (ExportFormat.PNG, "PNG"),
    (ExportFormat.SVG, "SVG"),
    (ExportFormat.PDF, "PDF"),
    (ExportFormat.DOCX, "Word"),
    (ExportFormat.SCHEMEUP, "SchemeUp"),
)
FILTERS = {
    ExportFormat.PNG: "PNG image (*.png)",
    ExportFormat.SVG: "SVG drawing (*.svg)",
    ExportFormat.PDF: "PDF document (*.pdf)",
    ExportFormat.DOCX: "Word document (*.docx)",
    ExportFormat.SCHEMEUP: "SchemeUp note (*.schemeup)",
}
PREVIEW = QSize(360, 420)


def safe_filename(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", title).strip() or "note"


class ExportDialog(QDialog):
    last_format = ExportFormat.PNG

    def __init__(
        self,
        document: Document,
        selection: frozenset[str],
        title: str,
        tags: tuple[str, ...],
        renderer: SceneRenderer,
        exporter: Exporter,
        theme: Theme,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Export"))
        self._document = document
        self._selection = selection
        self._title = title
        self._tags = tags
        self._renderer = renderer
        self._exporter = exporter
        self._theme = theme
        self._page_index = 0
        self.exported_path: Path | None = None

        layout = QHBoxLayout(self)
        layout.setSpacing(18)
        left = QVBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(PREVIEW)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setObjectName("exportPreview")
        left.addWidget(self.preview)
        nav = QHBoxLayout()
        self.prev = QToolButton()
        self.prev.setIcon(icon("chevron-left", theme.text))
        self.prev.clicked.connect(lambda: self._turn(-1))
        self.page_label = QLabel()
        self.page_label.setObjectName("muted")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next = QToolButton()
        self.next.setIcon(icon("chevron-right", theme.text))
        self.next.clicked.connect(lambda: self._turn(1))
        nav.addWidget(self.prev)
        nav.addWidget(self.page_label, 1)
        nav.addWidget(self.next)
        left.addLayout(nav)
        layout.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(10)
        formats = QHBoxLayout()
        formats.setSpacing(4)
        self._format_group = QButtonGroup(self)
        self._format_buttons: dict[ExportFormat, QPushButton] = {}
        for fmt, label in FORMAT_LABELS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, f=fmt: self._set_format(f))
            self._format_group.addButton(button)
            self._format_buttons[fmt] = button
            formats.addWidget(button)
        right.addLayout(formats)

        self.warning = QLabel()
        self.warning.setObjectName("warning")
        self.warning.setWordWrap(True)
        right.addWidget(self.warning)

        form = QFormLayout()
        form.setSpacing(8)
        self._form = form
        self.scope = QComboBox()
        self.scope.addItem(self.tr("Everything on the canvas"), ExportScope.ALL)
        self.scope.addItem(self.tr("Only the selection"), ExportScope.SELECTION)
        self.scope.setEnabled(bool(selection))
        if selection:
            self.scope.setCurrentIndex(1)
        form.addRow(self.tr("What"), self.scope)
        self.layout_box = QComboBox()
        frames = len(document.frames())
        self.layout_box.addItem(self.tr("Fit everything on one page"), PageLayout.FIT)
        self.layout_box.addItem(
            self.tr("One page per frame (%1 frames)").replace("%1", str(frames)), PageLayout.FRAMES
        )
        self.layout_box.addItem(self.tr("Split across pages at real size"), PageLayout.TILES)
        self.layout_box.addItem(self.tr("The note's pages"), PageLayout.PAGES)
        model = self.layout_box.model()
        if not frames:
            model.item(1).setEnabled(False)  # type: ignore[attr-defined]
        if document.settings.page_size is None:
            model.item(3).setEnabled(False)  # type: ignore[attr-defined]
        default = (
            PageLayout.PAGES
            if document.settings.page_size
            else PageLayout.FRAMES
            if frames
            else PageLayout.FIT
        )
        self.layout_box.setCurrentIndex(self.layout_box.findData(default))
        form.addRow(self.tr("Pages"), self.layout_box)
        paper = QHBoxLayout()
        self.paper = QComboBox()
        for name in ("A4", "A5", "Letter"):
            self.paper.addItem(name, name)
        if document.settings.page_size:
            self.paper.setCurrentIndex(max(self.paper.findData(document.settings.page_size), 0))
        self.landscape = QCheckBox(self.tr("Landscape"))
        self.landscape.setChecked(document.settings.page_landscape)
        paper.addWidget(self.paper, 1)
        paper.addWidget(self.landscape)
        self._paper_row = QWidget()
        self._paper_row.setLayout(paper)
        form.addRow(self.tr("Paper"), self._paper_row)
        self.scale = QComboBox()
        for factor in (1, 2, 3, 4):
            self.scale.addItem(f"{factor}x", float(factor))
        self.scale.setCurrentIndex(1)
        form.addRow(self.tr("Resolution"), self.scale)
        self.background = QCheckBox(self.tr("Include the background color"))
        self.background.setChecked(True)
        form.addRow("", self.background)
        self.dark = QCheckBox(self.tr("Export in dark mode"))
        form.addRow("", self.dark)
        self.outlines = QCheckBox(
            self.tr("Convert text to outlines (looks the same without the fonts)")
        )
        self.outlines.setChecked(True)
        form.addRow("", self.outlines)
        self.appendix = QCheckBox(self.tr("Add the note's text as editable paragraphs"))
        self.appendix.setChecked(True)
        form.addRow("", self.appendix)
        right.addLayout(form)
        self.fit_note = QLabel()
        self.fit_note.setObjectName("muted")
        self.fit_note.setWordWrap(True)
        right.addWidget(self.fit_note)
        right.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(self.tr("Cancel"))
        cancel.clicked.connect(self.reject)
        self.export_button = QPushButton(self.tr("Export…"))
        self.export_button.setObjectName("primary")
        self.export_button.setDefault(True)
        self.export_button.clicked.connect(self._export)
        buttons.addWidget(cancel)
        buttons.addWidget(self.export_button)
        right.addLayout(buttons)
        holder = QFrame()
        holder.setLayout(right)
        holder.setFixedWidth(420)
        layout.addWidget(holder)

        for widget in (self.scope, self.layout_box, self.paper, self.scale):
            widget.currentIndexChanged.connect(self._update)
        for box in (self.landscape, self.background, self.dark, self.outlines, self.appendix):
            box.toggled.connect(self._update)
        self.setStyleSheet(
            f"#exportPreview {{ background: {theme.input}; border: 1px solid {theme.border};"
            " border-radius: 10px; }"
            f"#warning {{ background: {'#3b2f12' if theme.dark else '#fff4d6'}; border: 1px solid"
            f" {'#6b5520' if theme.dark else '#f0d48a'}; border-radius: 8px; padding: 8px 10px; }}"
            f"QPushButton:checked {{ background: {theme.accent_soft};"
            f" border-color: {theme.accent}; }}"
        )
        self._set_format(ExportDialog.last_format)

    # State

    def request(self) -> ExportRequest:
        fmt = next(f for f, b in self._format_buttons.items() if b.isChecked())
        return ExportRequest(
            format=fmt,
            scope=ExportScope(self.scope.currentData()),
            layout=PageLayout(self.layout_box.currentData()),
            page=str(self.paper.currentData()),
            landscape=self.landscape.isChecked(),
            background=self.background.isChecked(),
            dark=self.dark.isChecked(),
            scale=float(self.scale.currentData()),
            text_as_paths=self.outlines.isChecked(),
            text_appendix=self.appendix.isChecked(),
            title=self._title,
            tags=self._tags,
        )

    def _set_format(self, fmt: ExportFormat) -> None:
        self._format_buttons[fmt].setChecked(True)
        self._page_index = 0
        self._update()

    def _turn(self, delta: int) -> None:
        self._page_index += delta
        self._update()

    def _only(self) -> frozenset[str]:
        return self._selection if self.scope.currentData() == ExportScope.SELECTION else frozenset()

    def _regions(self, request: ExportRequest) -> list:  # type: ignore[type-arg]
        region = export_region(self._document, self._only())
        if not request.format.paged:
            return [region] if region is not None else []
        if request.layout in (PageLayout.FRAMES, PageLayout.PAGES):
            region = None
        return export_regions(
            self._document, request.layout, region, request.page, request.landscape
        )

    def _update(self) -> None:
        request = self.request()
        paged = request.format.paged
        rows = {
            self.layout_box: paged,
            self._paper_row: paged,
            self.scale: request.format == ExportFormat.PNG,
            self.background: request.format
            in (ExportFormat.PNG, ExportFormat.SVG, ExportFormat.PDF),
            self.dark: request.format != ExportFormat.SCHEMEUP,
            self.outlines: request.format == ExportFormat.SVG,
            self.appendix: request.format == ExportFormat.DOCX,
            self.scope: request.format != ExportFormat.SCHEMEUP,
        }
        for widget, visible in rows.items():
            self._form.setRowVisible(widget, visible)
        infinite = paged and is_infinite(self._document)
        self.warning.setVisible(infinite)
        self.warning.setText(
            self.tr(
                "This note is an infinite canvas, and %1 needs pages. Choose how: fit"
                " everything on one page, split it across pages at real size, or add frames (F)"
                " around the parts you want and export one page per frame."
            ).replace("%1", "Word" if request.format == ExportFormat.DOCX else "PDF")
        )
        regions = self._regions(request)
        self.export_button.setEnabled(bool(regions) or request.format == ExportFormat.SCHEMEUP)
        self.fit_note.setText("")
        if paged and request.layout == PageLayout.FIT and regions:
            scale = fit_scale(regions[0], printable_size(request.page, request.landscape))
            percent = round(min(scale, 1.0) * 100) if scale < 1 else round(scale * 100)
            if scale < 0.6:
                self.fit_note.setText(
                    self.tr(
                        "Everything fits at %1% of its size, so small text may be hard to read."
                    ).replace("%1", str(percent))
                )
            else:
                self.fit_note.setText(
                    self.tr("Everything fits at %1% of its size.").replace("%1", str(percent))
                )
        elif paged and request.layout == PageLayout.TILES:
            self.fit_note.setText(
                self.tr("%1 pages at real size.").replace("%1", str(len(regions)))
            )
        if request.format == ExportFormat.DOCX:
            self.fit_note.setText(
                (self.fit_note.text() + " " if self.fit_note.text() else "")
                + self.tr("Word gets the drawings as images; their shapes aren't editable in Word.")
            )
        self._page_index = max(0, min(self._page_index, len(regions) - 1))
        self.prev.setEnabled(self._page_index > 0)
        self.next.setEnabled(self._page_index < len(regions) - 1)
        self.page_label.setText(
            self.tr("Page %1 of %2")
            .replace("%1", str(self._page_index + 1))
            .replace("%2", str(len(regions)))
            if regions
            else self.tr("Nothing to export")
        )
        self._draw_preview(request, regions)

    def _draw_preview(self, request: ExportRequest, regions: list) -> None:  # type: ignore[type-arg]
        pixmap = QPixmap(PREVIEW)
        pixmap.fill(Qt.GlobalColor.transparent)
        if regions:
            region = regions[self._page_index]
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            area = QRectF(16, 16, PREVIEW.width() - 32, PREVIEW.height() - 32)
            if request.format.paged:
                paper = page_size(request.page, request.landscape)
                scale = min(area.width() / paper.width, area.height() / paper.height)
                sheet = QRectF(0, 0, paper.width * scale, paper.height * scale)
                sheet.moveCenter(area.center())
                painter.fillRect(sheet.translated(0, 2), QColor(0, 0, 0, 40))
                painter.fillRect(sheet, QColor("#ffffff"))
                painter.setPen(QPen(QColor(0, 0, 0, 40), 1))
                painter.drawRect(sheet)
                if request.layout == PageLayout.PAGES:
                    target = sheet
                else:
                    margin = (
                        (paper.width - printable_size(request.page, request.landscape).width)
                        / 2
                        * scale
                    )
                    target = sheet.adjusted(margin, margin, -margin, -margin)
                    if request.layout == PageLayout.TILES:
                        target = QRectF(
                            target.left(), target.top(), region.width * scale, region.height * scale
                        )
            else:
                target = area
            only = self._only() or None
            render_region(
                painter,
                self._document,
                region,
                self._renderer,
                target,
                dark=request.dark,
                background=request.background or request.format.paged,
                only=only,
            )
            painter.end()
        self.preview.setPixmap(pixmap)

    def _export(self) -> None:
        request = self.request()
        suggested = f"{safe_filename(self._title)}.{request.format.extension}"
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export"), suggested, FILTERS[request.format]
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != f".{request.format.extension}":
            target = target.with_suffix(f".{request.format.extension}")
        try:
            self._exporter.export(self._document, request, self._selection, target)
        except SchemeUpError as error:
            QMessageBox.warning(self, self.tr("Export failed"), str(error))
            return
        ExportDialog.last_format = request.format
        self.exported_path = target
        self.accept()
