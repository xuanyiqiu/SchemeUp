from PySide6.QtCore import QPointF

from schemeup.domain.elements import Arrow, Ellipse, Rectangle
from schemeup.domain.geometry import Point
from schemeup.domain.structure_edit import Control, StructureOp
from schemeup.domain.structures import StructureKind
from schemeup.ui.canvas.structure_buttons import tip
from schemeup.ui.canvas.tools import ToolKind
from schemeup.ui.canvas.view import CanvasView
from schemeup.ui.main_window import MainWindow
from tests.ui.conftest import Mouse


def array_note(window: MainWindow, text: str = "1, 2, 3") -> CanvasView:
    window.new_note(None, "blank")
    canvas = window.editor.canvas
    canvas.insert_structure(StructureKind.ARRAY, text)
    canvas.fit_content()
    return canvas


def cells(canvas: CanvasView) -> list[Rectangle]:
    found = [e for e in canvas.session.document.ordered() if e.structure == "array"]
    return sorted((e for e in found if isinstance(e, Rectangle)), key=lambda c: c.x)


def centre_of(canvas: CanvasView, control: Control) -> QPointF:
    shown = canvas._structure_buttons.shown()
    assert shown is not None
    return next(p for c, p in canvas._structure_buttons._placed(shown) if c == control)


def button(canvas: CanvasView, label: str, op: StructureOp) -> Control:
    shown = canvas._structure_buttons.shown()
    assert shown is not None
    cell = next(c for c in cells(canvas) if c.label == label)
    return next(c for c in shown.controls if c.node_id == cell.id and c.op is op)


def click(canvas: CanvasView, control: Control) -> None:
    point = centre_of(canvas, control)
    Mouse(canvas).press(point.x(), point.y())
    Mouse(canvas).release(point.x(), point.y())


def test_a_fresh_structure_shows_its_buttons(window: MainWindow) -> None:
    canvas = array_note(window)
    shown = canvas._structure_buttons.shown()
    assert shown is not None
    ops = [c.op for c in shown.controls]
    assert ops.count(StructureOp.INSERT_AFTER) == 3
    assert ops.count(StructureOp.DELETE) == 3
    assert ops.count(StructureOp.INSERT_BEFORE) == 1  # only before the first cell


def test_nothing_else_gets_buttons(window: MainWindow) -> None:
    window.new_note(None, "blank")
    canvas = window.editor.canvas
    canvas.set_tool(ToolKind.RECTANGLE)
    Mouse(canvas).drag(200, 200, 320, 280)
    assert canvas._structure_buttons.shown() is None


def test_the_plus_adds_a_cell_after_and_opens_it_for_typing(window: MainWindow) -> None:
    canvas = array_note(window)
    click(canvas, button(canvas, "1", StructureOp.INSERT_AFTER))
    assert [c.label for c in cells(canvas)] == ["1", "", "2", "3"]
    assert canvas.text_editor.element_id is not None
    new = canvas.session.document.get(canvas.text_editor.element_id)
    assert isinstance(new, Rectangle) and new.label == ""


def test_typing_into_the_new_cell_keeps_the_value(window: MainWindow) -> None:
    canvas = array_note(window)
    click(canvas, button(canvas, "1", StructureOp.INSERT_AFTER))
    canvas.text_editor.insertPlainText("9")
    canvas.text_editor.commit()
    assert [c.label for c in cells(canvas)] == ["1", "9", "2", "3"]
    # and the buttons keep working on what was typed
    click(canvas, button(canvas, "9", StructureOp.DELETE))
    assert [c.label for c in cells(canvas)] == ["1", "2", "3"]


def test_the_minus_deletes_that_cell(window: MainWindow) -> None:
    canvas = array_note(window)
    click(canvas, button(canvas, "2", StructureOp.DELETE))
    assert [c.label for c in cells(canvas)] == ["1", "3"]
    assert canvas.text_editor.element_id is None


def test_a_button_press_is_one_undo_step(window: MainWindow) -> None:
    canvas = array_note(window)
    before = [c.label for c in cells(canvas)]
    click(canvas, button(canvas, "2", StructureOp.DELETE))
    canvas.session.undo()
    assert [c.label for c in cells(canvas)] == before


def test_the_buttons_follow_the_structure_after_each_edit(window: MainWindow) -> None:
    canvas = array_note(window, "1")
    for _ in range(3):
        click(canvas, button(canvas, "1", StructureOp.INSERT_AFTER))
        canvas.text_editor.commit()
    assert len(cells(canvas)) == 4
    shown = canvas._structure_buttons.shown()
    assert shown is not None and len(shown.controls) > 4


def test_hovering_a_structure_shows_its_buttons_without_selecting_it(window: MainWindow) -> None:
    canvas = array_note(window)
    canvas.session.select(())
    assert canvas._structure_buttons.shown() is None
    middle = cells(canvas)[1].center
    screen = canvas.camera.to_screen(Point(middle.x, middle.y))
    Mouse(canvas).move(screen.x, screen.y)
    assert canvas._structure_buttons.shown() is not None
    Mouse(canvas).move(5, 5)  # far away again
    assert canvas._structure_buttons.shown() is None


def test_the_buttons_hide_while_drawing_and_while_presenting(window: MainWindow) -> None:
    canvas = array_note(window)
    canvas.session.select([cells(canvas)[0].id])
    assert canvas._structure_buttons.shown() is not None

    canvas.set_tool(ToolKind.ARROW)
    assert canvas._structure_buttons.shown() is None
    canvas.set_tool(ToolKind.SELECT)
    canvas.session.select([cells(canvas)[0].id])
    assert canvas._structure_buttons.shown() is not None

    canvas.set_presenting(True)
    assert canvas._structure_buttons.shown() is None


def test_a_click_beside_the_buttons_still_selects_as_usual(window: MainWindow) -> None:
    canvas = array_note(window)
    canvas.session.select(())
    middle = cells(canvas)[1].center
    screen = canvas.camera.to_screen(Point(middle.x, middle.y))
    Mouse(canvas).press(screen.x, screen.y)
    Mouse(canvas).release(screen.x, screen.y)
    assert canvas.session.selection  # the cell, with its group
    assert len(cells(canvas)) == 3


def test_tree_buttons_add_children_and_remove_nodes(window: MainWindow) -> None:
    window.new_note(None, "blank")
    canvas = window.editor.canvas
    canvas.insert_structure(StructureKind.TREE, "1, 2")
    canvas.fit_content()
    shown = canvas._structure_buttons.shown()
    assert shown is not None
    root = next(
        e for e in canvas.session.document.ordered() if isinstance(e, Ellipse) and e.label == "1"
    )
    add = next(c for c in shown.controls if c.node_id == root.id and c.op is StructureOp.ADD_RIGHT)
    click(canvas, add)
    labels = sorted(e.label for e in canvas.session.document.ordered() if isinstance(e, Ellipse))
    assert labels == ["", "1", "2"]
    assert len([e for e in canvas.session.document.ordered() if isinstance(e, Arrow)]) == 2


def test_every_button_has_a_tooltip() -> None:
    for kind in StructureKind:
        for op in StructureOp:
            assert tip(Control("x", op, Point(0, 0)), kind)
