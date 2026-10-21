"""The canvas settings popover: background color, sheet type, page mode, snapping."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from schemeup.application.editor import Change, EditorSession
from schemeup.domain.camera import Camera
from schemeup.domain.geometry import Point, Size
from schemeup.domain.palette import PickerKind, dark_variant
from schemeup.domain.sheets import SHEET_PRESETS
from schemeup.rendering.sheet_painter import DARK_SHEET_STYLE, LIGHT_SHEET_STYLE, paint_sheet
from schemeup.ui.theme import Theme
from schemeup.ui.widgets.color_picker import ColorRow, RecentColors

THUMB = QSize(58, 42)


def sheet_thumbnail(preset_id: str, spacing_mm: float, background: str, dark: bool) -> QIcon:
    preset = next(p for p in SHEET_PRESETS if p.id == preset_id)
    sheet = preset.build(spacing_mm)
    pixmap = QPixmap(THUMB)
    fill = QColor(dark_variant(background) if dark else background)
    pixmap.fill(fill)
    painter = QPainter(pixmap)
    camera = Camera().centered_on(Point(0, 0), Size(THUMB.width(), THUMB.height()), zoom=0.55)
    paint_sheet(
        painter,
        sheet,
        camera,
        Size(THUMB.width(), THUMB.height()),
        DARK_SHEET_STYLE if dark else LIGHT_SHEET_STYLE,
        fill,
    )
    painter.end()
    return QIcon(pixmap)


class CanvasMenu(QFrame):
    snapping_toggled = Signal(bool, bool)  # objects, grid

    def __init__(self, session: EditorSession, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self._session = session
        self._theme = theme
        self._updating = False
        self.setObjectName("canvasMenu")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)

        def header(text: str) -> QLabel:
            label = QLabel(text.upper())
            label.setObjectName("section")
            return label

        layout.addWidget(header(self.tr("Canvas background")))
        self._background = ColorRow(PickerKind.BACKGROUND, RecentColors(), theme)
        self._background.color_chosen.connect(self._set_background)
        layout.addWidget(self._background)

        layout.addWidget(header(self.tr("Sheet")))
        grid = QGridLayout()
        grid.setSpacing(4)
        self._sheet_group = QButtonGroup(self)
        self._sheet_buttons: dict[str, QToolButton] = {}
        for i, preset in enumerate(SHEET_PRESETS):
            button = QToolButton()
            button.setCheckable(True)
            button.setToolTip(self.tr(preset.name))
            button.setIconSize(THUMB)
            button.setFixedSize(QSize(THUMB.width() + 8, THUMB.height() + 8))
            button.clicked.connect(lambda _c=False, pid=preset.id: self._set_sheet(pid))
            self._sheet_group.addButton(button)
            self._sheet_buttons[preset.id] = button
            grid.addWidget(button, i // 4, i % 4)
        layout.addLayout(grid)

        spacing_row = QHBoxLayout()
        spacing_row.addWidget(QLabel(self.tr("Line spacing")))
        self._spacing = QDoubleSpinBox()
        self._spacing.setRange(3.0, 40.0)
        self._spacing.setSingleStep(0.5)
        self._spacing.setSuffix(" mm")
        self._spacing.valueChanged.connect(self._set_spacing)
        spacing_row.addWidget(self._spacing)
        spacing_row.addStretch(1)
        layout.addLayout(spacing_row)

        layout.addWidget(header(self.tr("Page")))
        page_row = QHBoxLayout()
        self._page = QComboBox()
        self._page.addItem(self.tr("Infinite canvas"), None)
        for name in ("A4", "A5", "Letter"):
            self._page.addItem(name, name)
        self._page.currentIndexChanged.connect(self._set_page)
        self._landscape = QCheckBox(self.tr("Landscape"))
        self._landscape.toggled.connect(self._set_page)
        page_row.addWidget(self._page, 1)
        page_row.addWidget(self._landscape)
        layout.addLayout(page_row)

        layout.addWidget(header(self.tr("Snapping")))
        self._snap_objects = QCheckBox(self.tr("Snap to shapes") + "  (Alt+S)")
        self._snap_grid = QCheckBox(self.tr("Snap to sheet") + "  (Ctrl+')")
        self._snap_objects.toggled.connect(self._emit_snapping)
        self._snap_grid.toggled.connect(self._emit_snapping)
        layout.addWidget(self._snap_objects)
        layout.addWidget(self._snap_grid)
        self.set_theme(theme)
        session.subscribe(self._on_change)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.setStyleSheet(
            f"#canvasMenu {{ background: {theme.panel}; border: 1px solid {theme.border};"
            " border-radius: 12px; }"
        )
        self._background.set_theme(theme)
        self.refresh()

    def open_at(self, anchor: QPoint, snap_objects: bool, snap_grid: bool) -> None:
        self._updating = True
        self._snap_objects.setChecked(snap_objects)
        self._snap_grid.setChecked(snap_grid)
        self._updating = False
        self.refresh()
        self.adjustSize()
        self.move(anchor)
        self.show()

    def _on_change(self, change: Change) -> None:
        if change == Change.DOCUMENT and self.isVisible():
            self.refresh()

    def refresh(self) -> None:
        settings = self._session.document.settings
        self._updating = True
        self._background.set_color(settings.background)
        for preset_id, button in self._sheet_buttons.items():
            button.setIcon(
                sheet_thumbnail(
                    preset_id, settings.line_spacing_mm, settings.background, self._theme.dark
                )
            )
            button.setChecked(preset_id == settings.sheet)
        self._spacing.setValue(settings.line_spacing_mm)
        self._spacing.setEnabled(settings.sheet == "lines")
        index = self._page.findData(settings.page_size)
        self._page.setCurrentIndex(max(index, 0))
        self._landscape.setChecked(settings.page_landscape)
        self._landscape.setEnabled(settings.page_size is not None)
        self._updating = False

    def _update(self, **changes: object) -> None:
        if self._updating:
            return
        settings = replace(self._session.document.settings, **changes)  # type: ignore[arg-type]
        self._session.set_canvas_settings(settings)

    def _set_background(self, color: str) -> None:
        self._update(background=color)

    def _set_sheet(self, preset_id: str) -> None:
        self._update(sheet=preset_id)

    def _set_spacing(self, value: float) -> None:
        self._update(line_spacing_mm=float(value))

    def _set_page(self) -> None:
        self._update(page_size=self._page.currentData(), page_landscape=self._landscape.isChecked())

    def _emit_snapping(self) -> None:
        if not self._updating:
            self.snapping_toggled.emit(self._snap_objects.isChecked(), self._snap_grid.isChecked())
