"""The + and - buttons that appear on a data structure to add and remove its parts.

They show while the pointer is over a structure, or while it is selected, and sit on the
corners of its cells and nodes: a plus at the top right adds, a minus at the bottom left
removes. Where a corner does not make sense (matrix rows and columns, tree children)
the structure puts them where they are clearest; see `structure_edit.controls`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from schemeup.domain.document import Document
from schemeup.domain.geometry import Point, Rect
from schemeup.domain.structure_edit import (
    KINDS,
    Control,
    StructureOp,
    controls,
    read,
)
from schemeup.domain.structures import StructureKind, union_bounds
from schemeup.ui.canvas.tools import ToolKind

if TYPE_CHECKING:
    from schemeup.ui.canvas.view import CanvasView

RADIUS = 9.0  # screen pixels, whatever the zoom
GRAB = 11.0  # how close a click has to be to count
REACH = 30.0  # the buttons stay while the pointer is this far outside the structure
MIN_NODE_PX = 24.0  # on cells smaller than this on screen the buttons would cover them
REMOVE_COLOR = "#e03131"
ADDING = (
    StructureOp.INSERT_AFTER,
    StructureOp.INSERT_BEFORE,
    StructureOp.ADD_LEFT,
    StructureOp.ADD_RIGHT,
    StructureOp.ADD_NEIGHBOUR,
    StructureOp.ADD_ROW,
    StructureOp.ADD_COLUMN,
)


@dataclass(slots=True)
class _Shown:
    document: Document
    group: str
    kind: StructureKind | None
    controls: list[Control]
    bounds: Rect | None


def tip(control: Control, kind: StructureKind | None) -> str:
    """What a button does, in words, for its tooltip."""
    tr = QCoreApplication.translate
    ctx = "StructureButtons"
    match control.op:
        case StructureOp.INSERT_AFTER:
            if kind is StructureKind.STACK:
                return tr(ctx, "Push a value on top")
            return tr(ctx, "Insert a cell after this one")
        case StructureOp.INSERT_BEFORE:
            return tr(ctx, "Insert a cell before this one")
        case StructureOp.DELETE:
            if kind is StructureKind.TREE:
                return tr(ctx, "Delete this node and everything below it")
            if kind is StructureKind.GRAPH:
                return tr(ctx, "Delete this node and its edges")
            return tr(ctx, "Delete this cell")
        case StructureOp.ADD_LEFT:
            return tr(ctx, "Add a left child")
        case StructureOp.ADD_RIGHT:
            return tr(ctx, "Add a right child")
        case StructureOp.ADD_NEIGHBOUR:
            return tr(ctx, "Add a node linked to this one")
        case StructureOp.ADD_ROW:
            return tr(ctx, "Add a row below")
        case StructureOp.DELETE_ROW:
            return tr(ctx, "Delete this row")
        case StructureOp.ADD_COLUMN:
            return tr(ctx, "Add a column after")
        case StructureOp.DELETE_COLUMN:
            return tr(ctx, "Delete this column")


class StructureButtons:
    def __init__(self, view: CanvasView) -> None:
        self._view = view
        self._hover_group: str | None = None
        self._hover_control: Control | None = None
        self._cache: _Shown | None = None

    # Which structure has buttons

    def _selection_group(self) -> str | None:
        session = self._view.session
        groups: set[str | None] = set()
        for element_id in session.selection:
            element = session.document.get(element_id)
            groups.add(element.group_ids[0] if element is not None and element.group_ids else None)
        only = next(iter(groups)) if len(groups) == 1 else None
        return only

    def _available(self) -> bool:
        view = self._view
        return not view.presenting and view.tool == ToolKind.SELECT and not view.pointer_down

    def shown(self) -> _Shown | None:
        """The structure whose buttons are showing, if any."""
        if not self._available():
            return None
        group = self._hover_group or self._selection_group()
        if group is None:
            return None
        document = self._view.session.document
        cached = self._cache
        if cached is None or cached.group != group or cached.document is not document:
            cached = self._load(document, group)
            self._cache = cached
        return cached if cached.controls else None

    @staticmethod
    def _load(document: Document, group: str) -> _Shown:
        node = next(
            (
                e
                for e in document.ordered()
                if e.structure in KINDS and e.group_ids and e.group_ids[0] == group
            ),
            None,
        )
        reading = read(document, node.id) if node is not None else None
        if reading is None:
            return _Shown(document, group, None, [], None)
        return _Shown(
            document, group, reading.kind, controls(reading), union_bounds(reading.members)
        )

    # Pointer

    def update_hover(self, world: Point, screen: Point) -> bool:
        """Follow the pointer; returns True when something changed that needs a repaint."""
        changed = False
        if self._available():
            current = self.shown()
            reach = REACH / self._view.camera.zoom
            inside = current is not None and (
                current.bounds is not None and current.bounds.inflated(reach).contains(world)
            )
            if not inside:
                element = self._view.hit(world)
                group = element.group_ids[0] if element is not None and element.group_ids else None
                if group != self._hover_group:
                    self._hover_group = group
                    changed = True
        elif self._hover_group is not None:
            self._hover_group = None
            changed = True
        control = self.button_at(screen)
        if control != self._hover_control:
            self._hover_control = control
            changed = True
        return changed

    def clear_hover(self) -> None:
        if self._hover_group is not None or self._hover_control is not None:
            self._hover_group = None
            self._hover_control = None
            self._view.update()

    def hovered(self) -> Control | None:
        return self._hover_control

    def tip_for(self, control: Control) -> str:
        shown = self.shown()
        return tip(control, shown.kind if shown is not None else None)

    # Geometry

    def _placed(self, shown: _Shown) -> list[tuple[Control, QPointF]]:
        camera = self._view.camera
        placed: list[tuple[Control, QPointF]] = []
        for control in shown.controls:
            node = shown.document.get(control.node_id)
            if node is None or node.angle:
                continue
            width, height = node.width * camera.zoom, node.height * camera.zoom
            if min(width, height) < MIN_NODE_PX:
                continue
            origin = camera.to_screen(Point(node.x, node.y))
            placed.append(
                (
                    control,
                    QPointF(
                        origin.x + control.where.x * width, origin.y + control.where.y * height
                    ),
                )
            )
        return placed

    def button_at(self, screen: Point) -> Control | None:
        shown = self.shown()
        if shown is None:
            return None
        best: tuple[float, Control] | None = None
        for control, center in self._placed(shown):
            distance = math.hypot(center.x() - screen.x, center.y() - screen.y)
            if distance <= GRAB and (best is None or distance < best[0]):
                best = (distance, control)
        return best[1] if best is not None else None

    # Painting

    def paint(self, painter: QPainter, panel: str, accent: str) -> None:
        shown = self.shown()
        if shown is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for control, center in self._placed(shown):
            color = QColor(accent if control.op in ADDING else REMOVE_COLOR)
            hot = control == self._hover_control
            painter.setPen(QPen(color, 1.6))
            painter.setBrush(color if hot else QColor(panel))
            painter.drawEllipse(center, RADIUS, RADIUS)
            glyph = QPen(QColor("white") if hot else color, 1.8)
            glyph.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(glyph)
            arm = RADIUS * 0.45
            x, y = center.x(), center.y()
            painter.drawLine(QPointF(x - arm, y), QPointF(x + arm, y))
            if control.op in ADDING:
                painter.drawLine(QPointF(x, y - arm), QPointF(x, y + arm))
        painter.restore()
