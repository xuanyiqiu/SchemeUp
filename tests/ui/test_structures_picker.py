from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from schemeup.domain.elements import Arrow, Ellipse, Rectangle, Text, element_bounds
from schemeup.domain.geometry import Point
from schemeup.domain.structures import EXAMPLES, StructureKind
from schemeup.ui.canvas.structures_picker import StructurePicker
from schemeup.ui.main_window import MainWindow
from schemeup.ui.theme import LIGHT
from tests.ui.conftest import press


def picker(qtbot: QtBot) -> StructurePicker:
    widget = StructurePicker(LIGHT)
    qtbot.addWidget(widget)
    return widget


def test_an_empty_field_previews_and_inserts_the_example(qtbot: QtBot) -> None:
    widget = picker(qtbot)
    assert widget.text() == EXAMPLES[StructureKind.ARRAY]
    assert widget._insert_button.isEnabled()
    assert widget._preview.pixmap() is not None and not widget._preview.pixmap().isNull()


def test_choosing_a_kind_changes_the_example_and_hint(qtbot: QtBot) -> None:
    widget = picker(qtbot)
    widget.choose(StructureKind.TREE)
    assert widget.kind == StructureKind.TREE
    assert widget._field.placeholderText() == EXAMPLES[StructureKind.TREE]
    assert "null" in widget._hint.text()


def test_bad_input_says_why_and_cannot_be_inserted(qtbot: QtBot) -> None:
    widget = picker(qtbot)
    widget.choose(StructureKind.TREE)
    widget._field.setText("null, 1, 2")
    assert not widget._insert_button.isEnabled()
    assert "root" in widget._preview.text()
    widget._field.setText("1, 2, 3")
    assert widget._insert_button.isEnabled()


def test_enter_emits_the_kind_and_text(qtbot: QtBot) -> None:
    widget = picker(qtbot)
    widget.choose(StructureKind.QUEUE)
    widget._field.setText("5, 6")
    with qtbot.waitSignal(widget.insert_requested) as signal:
        widget._field.returnPressed.emit()
    assert signal.args == [StructureKind.QUEUE, "5, 6"]


def test_every_kind_has_a_name_and_a_working_example(qtbot: QtBot) -> None:
    widget = picker(qtbot)
    for kind in StructureKind:
        widget.choose(kind)
        assert widget.name(kind)
        assert widget._insert_button.isEnabled(), kind


def test_inserting_draws_one_group_in_the_middle_of_the_view(window: MainWindow) -> None:
    window.new_note(None, "blank")
    canvas = window.editor.canvas
    before = len(canvas.session.document)
    assert canvas.insert_structure(StructureKind.LINKED_LIST, "1 -> 2 -> 3")
    document = canvas.session.document
    added = document.ordered()[before:]
    assert any(isinstance(e, Rectangle) for e in added)
    assert any(isinstance(e, Arrow) for e in added)
    assert {e.group_ids for e in added} == {added[0].group_ids}
    assert canvas.session.selection == {e.id for e in added}

    box = element_bounds(added[0])
    for element in added[1:]:
        box = box.union(element_bounds(element))
    middle = canvas.camera.to_world(Point(canvas.width() / 2, canvas.height() / 2))
    assert abs(box.center.x - middle.x) < 2 and abs(box.center.y - middle.y) < 2


def test_inserting_is_one_undo_step(window: MainWindow) -> None:
    window.new_note(None, "blank")
    canvas = window.editor.canvas
    canvas.insert_structure(StructureKind.TREE, "1, 2, 3")
    assert len(canvas.session.document) > 0
    canvas.session.undo()
    assert len(canvas.session.document) == 0


def test_a_tree_is_circles_and_links(window: MainWindow) -> None:
    window.new_note(None, "blank")
    canvas = window.editor.canvas
    canvas.insert_structure(StructureKind.TREE, "1, 2, 3")
    kinds = [type(e) for e in canvas.session.document.ordered()]
    assert kinds.count(Ellipse) == 3 and kinds.count(Arrow) == 2


def test_text_that_is_not_a_structure_inserts_nothing(window: MainWindow) -> None:
    window.new_note(None, "blank")
    canvas = window.editor.canvas
    assert not canvas.insert_structure(StructureKind.TREE, "null")
    assert not canvas.insert_structure(StructureKind.ARRAY, "")
    assert len(canvas.session.document) == 0


def test_the_toolbar_button_opens_the_picker_and_inserting_returns_focus(
    qtbot: QtBot, window: MainWindow
) -> None:
    window.new_note(None, "blank")
    page = window.editor
    page.toolbar.structures_button.click()
    assert page.structures.isVisible()
    page.structures.choose(StructureKind.STACK)
    page.structures._field.setText("7, 8, 9")
    page.structures._field.returnPressed.emit()
    assert not page.structures.isVisible()
    texts = [e for e in page.canvas.session.document.ordered() if isinstance(e, Text)]
    assert any(t.text == "top" for t in texts)


def test_the_palette_lists_the_structures(window: MainWindow) -> None:
    window.new_note(None, "blank")
    titles = [c.title for c in window._commands()]
    assert "Draw a data structure…" in titles
    assert "Data structure: Binary tree" in titles
    assert sum(t.startswith("Data structure:") for t in titles) == len(StructureKind)


def test_tab_cycles_through_the_kinds_from_the_text_field(qtbot: QtBot) -> None:
    widget = picker(qtbot)
    widget.show()
    widget._field.setFocus()
    press(widget._field, Qt.Key.Key_Tab)
    assert widget.kind == StructureKind.MATRIX
    press(widget._field, Qt.Key.Key_Backtab)
    assert widget.kind.value == StructureKind.ARRAY.value


def test_node_circles_stay_circles_after_the_editor_fits_their_labels(window: MainWindow) -> None:
    window.new_note(None, "blank")
    canvas = window.editor.canvas
    canvas.insert_structure(StructureKind.TREE, "10, 20, 30")
    canvas.insert_structure(StructureKind.GRAPH, "A-B, B-C")
    circles = [e for e in canvas.session.document.ordered() if isinstance(e, Ellipse)]
    assert len(circles) == 6
    assert all(abs(c.width - c.height) < 1e-6 for c in circles)


def test_boxes_keep_their_size_after_the_editor_fits_their_labels(window: MainWindow) -> None:
    window.new_note(None, "blank")
    canvas = window.editor.canvas
    canvas.insert_structure(StructureKind.ARRAY, "1, 2, 3")
    boxes = [e for e in canvas.session.document.ordered() if isinstance(e, Rectangle)]
    assert {round(b.height) for b in boxes} == {44}
