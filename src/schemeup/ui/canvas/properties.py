"""The properties panel on the left of the canvas.

It shows only the sections that make sense for the selection (or for the
active tool when nothing is selected), like Excalidraw. Every change goes
through `EditorSession.set_style`, which also sets the style for new elements.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from schemeup.application.editor import Change, EditorSession
from schemeup.domain.commands import AlignEdge, LayerMove
from schemeup.domain.elements import (
    LABELED,
    LINEAR,
    SHAPES,
    Arrow,
    Diamond,
    Ellipse,
    Freedraw,
    Image,
    Line,
    Rectangle,
    Text,
)
from schemeup.domain.palette import PickerKind
from schemeup.domain.style import (
    FONT_SIZES,
    MAX_FONT_SIZE,
    MIN_FONT_SIZE,
    STROKE_WIDTHS,
    TRANSPARENT,
    Arrowhead,
    FillStyle,
    FontFamily,
    Roundness,
    StrokeStyle,
    Style,
    TextAlign,
    VerticalAlign,
)
from schemeup.rendering.fonts import family_name
from schemeup.ui.canvas.tools import ToolKind
from schemeup.ui.theme import Island, Theme, icon, painted_icon
from schemeup.ui.widgets.color_picker import ColorRow, RecentColors

TOOL_TYPES: dict[ToolKind, type] = {
    ToolKind.RECTANGLE: Rectangle,
    ToolKind.DIAMOND: Diamond,
    ToolKind.ELLIPSE: Ellipse,
    ToolKind.ARROW: Arrow,
    ToolKind.LINE: Line,
    ToolKind.DRAW: Freedraw,
    ToolKind.TEXT: Text,
}

type Draw = Callable[[QPainter, int, QColor], None]


# Little preview icons, drawn so they always match the current theme.


def _box(size: int) -> QRectF:
    m = size * 0.2
    return QRectF(m, m, size - 2 * m, size - 2 * m)


def _fill_icon(style: FillStyle) -> Draw:
    def draw(p: QPainter, size: int, color: QColor) -> None:
        box = _box(size)
        path = QPainterPath()
        path.addRoundedRect(box, 4, 4)
        p.setPen(QPen(color, 1.6))
        if style == FillStyle.SOLID:
            p.fillPath(path, color)
        else:
            p.save()
            p.setClipPath(path)
            step = size / 6
            k = float(-size)
            while k < size * 2:
                p.drawLine(QPointF(k, size), QPointF(k + size, 0))
                if style == FillStyle.CROSS_HATCH:
                    p.drawLine(QPointF(k, 0), QPointF(k + size, size))
                k += step
            p.restore()
        p.drawPath(path)

    return draw


def _width_icon(width: float) -> Draw:
    def draw(p: QPainter, size: int, color: QColor) -> None:
        pen = QPen(color, width * 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(size * 0.22, size / 2), QPointF(size * 0.78, size / 2))

    return draw


def _stroke_style_icon(style: StrokeStyle) -> Draw:
    def draw(p: QPainter, size: int, color: QColor) -> None:
        pen = QPen(color, 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if style == StrokeStyle.DASHED:
            pen.setDashPattern([2.5, 2.5])
        elif style == StrokeStyle.DOTTED:
            pen.setDashPattern([0.01, 2.6])
        p.setPen(pen)
        p.drawLine(QPointF(size * 0.2, size / 2), QPointF(size * 0.8, size / 2))

    return draw


def _sloppiness_icon(level: int) -> Draw:
    def draw(p: QPainter, size: int, color: QColor) -> None:
        pen = QPen(color, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        path = QPainterPath(QPointF(size * 0.18, size * 0.62))
        if level == 0:
            path.cubicTo(size * 0.4, size * 0.62, size * 0.5, size * 0.38, size * 0.82, size * 0.38)
        elif level == 1:
            path.cubicTo(
                size * 0.35, size * 0.2, size * 0.55, size * 0.85, size * 0.82, size * 0.35
            )
        else:
            path.cubicTo(size * 0.3, size * 0.1, size * 0.4, size * 0.95, size * 0.55, size * 0.4)
            path.cubicTo(
                size * 0.62, size * 0.15, size * 0.75, size * 0.7, size * 0.84, size * 0.36
            )
        p.drawPath(path)

    return draw


def _edge_icon(roundness: Roundness) -> Draw:
    def draw(p: QPainter, size: int, color: QColor) -> None:
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        a, b = size * 0.28, size * 0.75
        path = QPainterPath(QPointF(a, b))
        if roundness == Roundness.SHARP:
            path.lineTo(a, a)
            path.lineTo(b, a)
        else:
            path.lineTo(a, a + size * 0.2)
            path.quadTo(a, a, a + size * 0.2, a)
            path.lineTo(b, a)
        p.drawPath(path)

    return draw


def _head_icon(head: Arrowhead, start: bool) -> Draw:
    def draw(p: QPainter, size: int, color: QColor) -> None:
        pen = QPen(color, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        y = size / 2
        left, right = size * 0.2, size * 0.8
        tip = QPointF(left, y) if start else QPointF(right, y)
        direction = -1 if start else 1
        p.drawLine(QPointF(left, y), QPointF(right, y))
        back = tip.x() - direction * size * 0.22
        if head == Arrowhead.ARROW:
            p.drawLine(tip, QPointF(back, y - size * 0.14))
            p.drawLine(tip, QPointF(back, y + size * 0.14))
        elif head == Arrowhead.TRIANGLE:
            p.setBrush(color)
            p.drawPolygon(
                QPolygonF([tip, QPointF(back, y - size * 0.14), QPointF(back, y + size * 0.14)])
            )
        elif head == Arrowhead.DOT:
            p.setBrush(color)
            p.drawEllipse(QPointF(tip.x() - direction * size * 0.07, y), size * 0.08, size * 0.08)
        elif head == Arrowhead.BAR:
            p.drawLine(QPointF(tip.x(), y - size * 0.15), QPointF(tip.x(), y + size * 0.15))

    return draw


def _position_icon(align: TextAlign, valign: VerticalAlign) -> Draw:
    def draw(p: QPainter, size: int, color: QColor) -> None:
        box = _box(size)
        faint = QColor(color)
        faint.setAlpha(80)
        p.setPen(QPen(faint, 1))
        p.drawRoundedRect(box, 3, 3)
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        widths = (box.width() * 0.6, box.width() * 0.4)
        if valign == VerticalAlign.TOP:
            y0 = box.top() + box.height() * 0.22
        elif valign == VerticalAlign.BOTTOM:
            y0 = box.bottom() - box.height() * 0.42
        else:
            y0 = box.center().y() - box.height() * 0.1
        for i, w in enumerate(widths):
            y = y0 + i * box.height() * 0.2
            if align == TextAlign.LEFT:
                x = box.left() + box.width() * 0.14
            elif align == TextAlign.RIGHT:
                x = box.right() - box.width() * 0.14 - w
            else:
                x = box.center().x() - w / 2
            p.drawLine(QPointF(x, y), QPointF(x + w, y))

    return draw


class OptionRow(QWidget):
    """A row of mutually exclusive option buttons."""

    chosen = Signal(object)

    def __init__(
        self, options: list[tuple[Any, str]], columns: int = 0, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        layout: QGridLayout | QHBoxLayout
        if columns:
            layout = QGridLayout(self)
            layout.setSpacing(2)
        else:
            layout = QHBoxLayout(self)
            layout.setSpacing(2)
        layout.setContentsMargins(0, 0, 0, 0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[Any, QToolButton] = {}
        for i, (value, tooltip) in enumerate(options):
            button = QToolButton()
            button.setCheckable(True)
            button.setToolTip(tooltip)
            button.setFixedSize(QSize(32, 32))
            button.setIconSize(QSize(24, 24))
            button.clicked.connect(lambda _c=False, v=value: self.chosen.emit(v))
            self._group.addButton(button)
            self._buttons[value] = button
            if isinstance(layout, QGridLayout):
                layout.addWidget(button, i // columns, i % columns)
            else:
                layout.addWidget(button)
        if isinstance(layout, QHBoxLayout):
            layout.addStretch(1)

    def button(self, value: Any) -> QToolButton:
        return self._buttons[value]

    def set_value(self, value: Any) -> None:
        button = self._buttons.get(value)
        if button is not None:
            button.setChecked(True)
        else:
            self._group.setExclusive(False)
            for b in self._buttons.values():
                b.setChecked(False)
            self._group.setExclusive(True)


class Section(QWidget):
    def __init__(self, title: str, body: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(4)
        label = QLabel(title.upper())
        label.setObjectName("section")
        layout.addWidget(label)
        layout.addWidget(body)


class PropertiesPanel(Island):
    resized = Signal()

    def __init__(self, session: EditorSession, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent, radius=10)
        self._session = session
        self._tool = ToolKind.SELECT
        self._updating = False
        self._suppressed = False
        self._recent = RecentColors()
        self.setFixedWidth(236)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; }"
            " QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        self._scroll = scroll
        outer.addWidget(scroll)
        content = QWidget()
        self._content = content
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 6)
        layout.setSpacing(4)
        scroll.setWidget(content)

        tr = self.tr
        self.stroke = ColorRow(PickerKind.STROKE, self._recent, theme)
        self.stroke.color_chosen.connect(lambda c: self._set(stroke_color=c))
        self.background = ColorRow(PickerKind.FILL, self._recent, theme)
        self.background.color_chosen.connect(self._set_background)
        self.fill = OptionRow(
            [
                (FillStyle.HACHURE, tr("Hachure")),
                (FillStyle.CROSS_HATCH, tr("Cross-hatch")),
                (FillStyle.SOLID, tr("Solid")),
            ]
        )
        self.fill.chosen.connect(lambda v: self._set(fill_style=v))
        self.width_row = OptionRow(
            [
                (STROKE_WIDTHS[0], tr("Thin")),
                (STROKE_WIDTHS[1], tr("Bold")),
                (STROKE_WIDTHS[2], tr("Extra bold")),
            ]
        )
        self.width_row.chosen.connect(lambda v: self._set(stroke_width=v))
        self.stroke_style = OptionRow(
            [
                (StrokeStyle.SOLID, tr("Solid")),
                (StrokeStyle.DASHED, tr("Dashed")),
                (StrokeStyle.DOTTED, tr("Dotted")),
            ]
        )
        self.stroke_style.chosen.connect(lambda v: self._set(stroke_style=v))
        self.sloppiness = OptionRow(
            [(0, tr("Architect (clean)")), (1, tr("Artist")), (2, tr("Cartoonist"))]
        )
        self.sloppiness.chosen.connect(lambda v: self._set(roughness=v))
        self.edges = OptionRow([(Roundness.SHARP, tr("Sharp")), (Roundness.ROUND, tr("Round"))])
        self.edges.chosen.connect(lambda v: self._set(roundness=v))
        heads = [
            (Arrowhead.NONE, tr("None")),
            (Arrowhead.ARROW, tr("Arrow")),
            (Arrowhead.TRIANGLE, tr("Triangle")),
            (Arrowhead.DOT, tr("Dot")),
            (Arrowhead.BAR, tr("Bar")),
        ]
        self.start_head = OptionRow(heads)
        self.start_head.chosen.connect(lambda v: self._set(start_head=v))
        self.end_head = OptionRow(heads)
        self.end_head.chosen.connect(lambda v: self._set(end_head=v))
        heads_box = QWidget()
        heads_layout = QVBoxLayout(heads_box)
        heads_layout.setContentsMargins(0, 0, 0, 0)
        heads_layout.setSpacing(2)
        heads_layout.addWidget(self.start_head)
        heads_layout.addWidget(self.end_head)

        self.font_family = OptionRow(
            [
                (FontFamily.HAND, tr("Hand-drawn")),
                (FontFamily.NORMAL, tr("Normal")),
                (FontFamily.CODE, tr("Code")),
            ]
        )
        self.font_family.chosen.connect(lambda v: self._set(font_family=v))
        size_box = QWidget()
        size_layout = QHBoxLayout(size_box)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.setSpacing(2)
        self.font_size = OptionRow(
            [
                (FONT_SIZES[0], tr("Small")),
                (FONT_SIZES[1], tr("Medium")),
                (FONT_SIZES[2], tr("Large")),
                (FONT_SIZES[3], tr("Extra large")),
            ]
        )
        for value, text in zip(FONT_SIZES, ("S", "M", "L", "XL"), strict=True):
            self.font_size.button(value).setText(text)
        self.font_size.chosen.connect(lambda v: self._set(font_size=v))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(int(MIN_FONT_SIZE), int(MAX_FONT_SIZE))
        self.size_spin.setSuffix(" px")
        self.size_spin.setToolTip(tr("Custom font size"))
        self.size_spin.setFixedWidth(70)
        self.size_spin.valueChanged.connect(lambda v: self._set(font_size=float(v)))
        size_layout.addWidget(self.font_size, 1)
        size_layout.addWidget(self.size_spin)

        positions = [
            ((a, v), tr("Text position"))
            for v in (VerticalAlign.TOP, VerticalAlign.MIDDLE, VerticalAlign.BOTTOM)
            for a in (TextAlign.LEFT, TextAlign.CENTER, TextAlign.RIGHT)
        ]
        self.position = OptionRow(positions, columns=3)
        self.position.chosen.connect(lambda v: self._set(text_align=v[0], vertical_align=v[1]))
        self.align_text = OptionRow(
            [
                (TextAlign.LEFT, tr("Left")),
                (TextAlign.CENTER, tr("Center")),
                (TextAlign.RIGHT, tr("Right")),
            ]
        )
        self.align_text.chosen.connect(lambda v: self._set(text_align=v))

        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.valueChanged.connect(lambda v: self._set(opacity=int(v)))

        self.layers = self._action_row(
            [
                (
                    "arrow-bar-to-down",
                    tr("Send to back") + " — Ctrl+Shift+[",
                    lambda: session.reorder_selection(LayerMove.BACK),
                ),
                (
                    "arrow-down",
                    tr("Send backward") + " — Ctrl+[",
                    lambda: session.reorder_selection(LayerMove.BACKWARD),
                ),
                (
                    "arrow-up",
                    tr("Bring forward") + " — Ctrl+]",
                    lambda: session.reorder_selection(LayerMove.FORWARD),
                ),
                (
                    "arrow-bar-to-up",
                    tr("Bring to front") + " — Ctrl+Shift+]",
                    lambda: session.reorder_selection(LayerMove.FRONT),
                ),
            ]
        )
        self.align = self._action_row(
            [
                (
                    "layout-align-left",
                    tr("Align left"),
                    lambda: session.align_selection(AlignEdge.LEFT),
                ),
                (
                    "layout-align-center",
                    tr("Center horizontally"),
                    lambda: session.align_selection(AlignEdge.CENTER),
                ),
                (
                    "layout-align-right",
                    tr("Align right"),
                    lambda: session.align_selection(AlignEdge.RIGHT),
                ),
                (
                    "layout-align-top",
                    tr("Align top"),
                    lambda: session.align_selection(AlignEdge.TOP),
                ),
                (
                    "layout-align-middle",
                    tr("Center vertically"),
                    lambda: session.align_selection(AlignEdge.MIDDLE),
                ),
                (
                    "layout-align-bottom",
                    tr("Align bottom"),
                    lambda: session.align_selection(AlignEdge.BOTTOM),
                ),
            ]
        )
        self.distribute = self._action_row(
            [
                (
                    "layout-distribute-horizontal",
                    tr("Distribute horizontally"),
                    lambda: session.distribute_selection(True),
                ),
                (
                    "layout-distribute-vertical",
                    tr("Distribute vertically"),
                    lambda: session.distribute_selection(False),
                ),
            ]
        )
        self.action_buttons_row = self._action_row(
            [
                ("copy", tr("Duplicate") + " — Ctrl+D", session.duplicate_selection),
                ("trash", tr("Delete") + " — Del", session.delete_selection),
                ("box-multiple", tr("Group / ungroup") + " — Ctrl+G", self._toggle_group),
                ("lock", tr("Lock") + " — Ctrl+Shift+L", session.toggle_lock_selection),
            ]
        )

        self._sections: dict[str, Section] = {}
        for key, title, widget in (
            ("stroke", tr("Stroke"), self.stroke),
            ("background", tr("Background"), self.background),
            ("fill", tr("Fill"), self.fill),
            ("width", tr("Stroke width"), self.width_row),
            ("stroke_style", tr("Stroke style"), self.stroke_style),
            ("sloppiness", tr("Sloppiness"), self.sloppiness),
            ("edges", tr("Edges"), self.edges),
            ("heads", tr("Arrowheads"), heads_box),
            ("font_family", tr("Font family"), self.font_family),
            ("font_size", tr("Font size"), size_box),
            ("position", tr("Text position"), self.position),
            ("align_text", tr("Text align"), self.align_text),
            ("opacity", tr("Opacity"), self.opacity),
            ("layers", tr("Layers"), self.layers),
            ("align", tr("Align"), self.align),
            ("distribute", tr("Distribute"), self.distribute),
            ("actions", tr("Actions"), self.action_buttons_row),
        ):
            section = Section(title, widget)
            self._sections[key] = section
            layout.addWidget(section)
        layout.addStretch(1)

        self.set_theme(theme)
        session.subscribe(self._on_change)
        self.refresh()

    def _action_row(self, actions: list[tuple[str, str, Callable[[], None]]]) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        buttons: list[tuple[QToolButton, str]] = getattr(self, "_action_buttons", [])
        for icon_name, tooltip, slot in actions:
            button = QToolButton()
            button.setToolTip(tooltip)
            button.setFixedSize(QSize(32, 32))
            button.setIconSize(QSize(18, 18))
            button.clicked.connect(slot)
            layout.addWidget(button)
            buttons.append((button, icon_name))
        layout.addStretch(1)
        self._action_buttons = buttons
        return row

    def set_theme(self, theme: Theme) -> None:
        super().set_theme(theme)
        color = theme.text
        for value, button in self.fill._buttons.items():
            button.setIcon(painted_icon(_fill_icon(value), color))
        for value, button in self.width_row._buttons.items():
            button.setIcon(painted_icon(_width_icon(value), color))
        for value, button in self.stroke_style._buttons.items():
            button.setIcon(painted_icon(_stroke_style_icon(value), color))
        for value, button in self.sloppiness._buttons.items():
            button.setIcon(painted_icon(_sloppiness_icon(value), color))
        for value, button in self.edges._buttons.items():
            button.setIcon(painted_icon(_edge_icon(value), color))
        for value, button in self.start_head._buttons.items():
            button.setIcon(painted_icon(_head_icon(value, True), color))
        for value, button in self.end_head._buttons.items():
            button.setIcon(painted_icon(_head_icon(value, False), color))
        for value, button in self.position._buttons.items():
            button.setIcon(painted_icon(_position_icon(value[0], value[1]), color))
        for value, button in self.align_text._buttons.items():
            button.setIcon(painted_icon(_position_icon(value, VerticalAlign.MIDDLE), color))
        for value, button in self.font_family._buttons.items():
            button.setText("Aa")
            font = QFont(family_name(value))
            font.setPixelSize(14)
            button.setFont(font)
        for button, icon_name in self._action_buttons:
            button.setIcon(icon(icon_name, color))
        self.stroke.set_theme(theme)
        self.background.set_theme(theme)

    def set_tool(self, tool: ToolKind) -> None:
        self._tool = tool
        self.refresh()

    def set_suppressed(self, suppressed: bool) -> None:
        """Keep the panel out of the way (focus mode, presenting) whatever is selected."""
        self._suppressed = suppressed
        self.refresh()

    def _on_change(self, change: Change) -> None:
        if change in (Change.SELECTION, Change.DOCUMENT, Change.STYLE):
            self.refresh()

    def _set(self, **fields: Any) -> None:
        if not self._updating:
            self._session.set_style(**fields)

    def _set_background(self, color: str) -> None:
        if self._updating:
            return
        self._session.set_style(fill_color=color)

    def _toggle_group(self) -> None:
        elements = self._session.selected_elements()
        group_ids = {e.group_ids[-1] if e.group_ids else None for e in elements}
        if len(group_ids) == 1 and None not in group_ids:
            self._session.ungroup_selection()
        else:
            self._session.group_selection()

    def _context(self) -> tuple[set[type], Style, bool] | None:
        selected = self._session.selected_elements()
        if selected:
            labeled = any(isinstance(e, LABELED) and e.label for e in selected)
            return {type(e) for e in selected}, selected[0].style, labeled
        kind = TOOL_TYPES.get(self._tool)
        if kind is None:
            return None
        return {kind}, self._session.style, False

    def _context_style(self) -> Style | None:
        context = self._context()
        return context[1] if context else None

    def refresh(self) -> None:
        context = None if self._suppressed else self._context()
        if context is None:
            self.hide()
            return
        types, style, labeled = context
        count = len(self._session.selection)
        shapes = bool(types & set(SHAPES))
        linear = bool(types & set(LINEAR))
        text = Text in types
        drawable = shapes or linear or Freedraw in types
        visible = {
            "stroke": bool(types - {Image}),
            "background": shapes,
            "fill": shapes and style.fill_color != TRANSPARENT,
            "width": drawable,
            "stroke_style": shapes or linear,
            "sloppiness": shapes or linear,
            "edges": bool(types & {Rectangle, Diamond, Line, Arrow}),
            "heads": Arrow in types,
            "font_family": text or labeled,
            "font_size": text or labeled,
            "position": labeled and shapes and not text,
            "align_text": text or (labeled and linear and not shapes),
            "opacity": True,
            "layers": count > 0,
            "align": count > 1,
            "distribute": count > 2,
            "actions": count > 0,
        }
        for key, section in self._sections.items():
            section.setVisible(visible[key])

        self._updating = True
        self.stroke.set_color(style.stroke_color)
        self.background.set_color(style.fill_color)
        self.fill.set_value(style.fill_style)
        self.width_row.set_value(style.stroke_width)
        self.stroke_style.set_value(style.stroke_style)
        self.sloppiness.set_value(style.roughness)
        self.edges.set_value(style.roundness)
        self.start_head.set_value(style.start_head)
        self.end_head.set_value(style.end_head)
        self.font_family.set_value(style.font_family)
        self.font_size.set_value(style.font_size)
        self.size_spin.setValue(round(style.font_size))
        self.position.set_value((style.text_align, style.vertical_align))
        self.align_text.set_value(style.text_align)
        self.opacity.setValue(style.opacity)
        self._updating = False

        self.show()
        self._content.adjustSize()
        wanted = self._content.sizeHint().height() + 2 * self.SHADOW + 4
        parent = self.parentWidget()
        limit = max(parent.height() - 120, 200) if parent is not None else wanted
        self.setFixedHeight(min(wanted, limit))
        self.resized.emit()
