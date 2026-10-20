from typing import Any

import pytest
from PySide6.QtCore import Qt

from schemeup.application.editor import EditorSession
from schemeup.domain.elements import (
    Arrow,
    Diamond,
    Ellipse,
    Freedraw,
    Rectangle,
    Text,
    element_bounds,
)
from schemeup.ui.canvas.tools import ToolKind
from schemeup.ui.canvas.view import CanvasView


def only(session: EditorSession, kind: type) -> Any:
    found = [e for e in session.document.ordered() if isinstance(e, kind)]
    assert len(found) == 1, found
    return found[0]


def test_drawing_shapes_with_the_tools(
    canvas: CanvasView, session: EditorSession, mouse: Any
) -> None:
    for tool, kind, (x, y) in (
        (ToolKind.RECTANGLE, Rectangle, (100, 100)),
        (ToolKind.DIAMOND, Diamond, (400, 100)),
        (ToolKind.ELLIPSE, Ellipse, (100, 400)),
    ):
        canvas.set_tool(tool)
        mouse.drag(x, y, x + 200, y + 100)
        bounds = element_bounds(only(session, kind))
        assert bounds.width == pytest.approx(200)
        assert bounds.height == pytest.approx(100)
    # After drawing, the tool goes back to selection and the new shape is selected.
    assert canvas.tool == ToolKind.SELECT
    assert len(session.selection) == 1


def test_shift_draws_a_square(canvas: CanvasView, session: EditorSession, mouse: Any) -> None:
    canvas.set_tool(ToolKind.RECTANGLE)
    mouse.drag(100, 100, 300, 160, Qt.KeyboardModifier.ShiftModifier)
    shape = only(session, Rectangle)
    assert shape.width == pytest.approx(shape.height)


def test_arrow_binds_to_the_shapes_it_connects(
    canvas: CanvasView, session: EditorSession, mouse: Any
) -> None:
    canvas.set_tool(ToolKind.RECTANGLE)
    mouse.drag(100, 100, 250, 200)
    canvas.set_tool(ToolKind.RECTANGLE)
    mouse.drag(500, 100, 650, 200)
    canvas.set_tool(ToolKind.ARROW)
    mouse.drag(255, 150, 495, 150)
    arrow = only(session, Arrow)
    assert arrow.start_binding is not None
    assert arrow.end_binding is not None


def test_freedraw_keeps_the_tool_active(
    canvas: CanvasView, session: EditorSession, mouse: Any
) -> None:
    canvas.set_tool(ToolKind.DRAW)
    mouse.drag(100, 100, 300, 180)
    assert len(only(session, Freedraw).points) > 3
    assert canvas.tool == ToolKind.DRAW


def test_double_click_inside_a_shape_types_its_label(
    canvas: CanvasView, session: EditorSession, mouse: Any
) -> None:
    canvas.set_tool(ToolKind.RECTANGLE)
    mouse.drag(100, 100, 300, 200)
    mouse.double_click(200, 150)
    assert canvas.text_editor.isVisible()
    canvas.text_editor.insertPlainText("API")
    canvas.text_editor.commit()
    assert only(session, Rectangle).label == "API"


def test_double_click_on_empty_canvas_creates_text(
    canvas: CanvasView, session: EditorSession, mouse: Any
) -> None:
    mouse.double_click(400, 300)
    canvas.text_editor.insertPlainText("meeting notes")
    canvas.text_editor.commit()
    text = only(session, Text)
    assert text.text == "meeting notes"
    assert text.width > 0


def test_empty_text_is_discarded(canvas: CanvasView, session: EditorSession, mouse: Any) -> None:
    mouse.double_click(400, 300)
    canvas.text_editor.commit()
    assert len(session.document) == 0


def test_move_selection_by_dragging_and_undo(
    canvas: CanvasView, session: EditorSession, mouse: Any
) -> None:
    canvas.set_tool(ToolKind.RECTANGLE)
    mouse.drag(100, 100, 300, 200)
    before = element_bounds(only(session, Rectangle))
    mouse.drag(100, 150, 160, 190)  # grab the left edge
    after = element_bounds(only(session, Rectangle))
    assert after.left - before.left == pytest.approx(60)
    session.undo()
    assert element_bounds(only(session, Rectangle)) == before


def test_rubber_band_selects_enclosed_elements(
    canvas: CanvasView, session: EditorSession, mouse: Any
) -> None:
    for x in (100, 300):
        canvas.set_tool(ToolKind.ELLIPSE)
        mouse.drag(x, 100, x + 100, 200)
    session.select(())
    mouse.drag(50, 50, 450, 260)
    assert len(session.selection) == 2


def test_eraser_removes_what_it_touches(
    canvas: CanvasView, session: EditorSession, mouse: Any
) -> None:
    canvas.set_tool(ToolKind.RECTANGLE)
    mouse.drag(100, 100, 300, 200)
    canvas.set_tool(ToolKind.ERASER)
    mouse.drag(80, 150, 120, 150)
    assert len(session.document) == 0


def test_copy_paste_and_duplicate(canvas: CanvasView, session: EditorSession, mouse: Any) -> None:
    canvas.set_tool(ToolKind.DIAMOND)
    mouse.drag(100, 100, 200, 200)
    canvas.copy()
    canvas.paste()
    assert len(session.document) == 2
    session.duplicate_selection()
    assert len(session.document) == 3
    assert len({e.id for e in session.document.ordered()}) == 3


def test_resize_handle_scales_the_shape(
    canvas: CanvasView, session: EditorSession, mouse: Any
) -> None:
    canvas.set_tool(ToolKind.RECTANGLE)
    mouse.drag(100, 100, 300, 200)
    corner = canvas.camera.to_screen(element_bounds(only(session, Rectangle)).corners()[2])
    # The handle sits 4 px outside the box.
    mouse.drag(corner.x + 4, corner.y + 4, corner.x + 104, corner.y + 54)
    resized = only(session, Rectangle)
    assert resized.width == pytest.approx(300, abs=1)
    assert resized.height == pytest.approx(150, abs=1)
