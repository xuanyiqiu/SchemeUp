from schemeup.domain import commands
from schemeup.domain.commands import ShapeKind
from schemeup.domain.document import CanvasSettings, Document
from schemeup.domain.geometry import Rect
from schemeup.domain.history import Changeset, History
from schemeup.domain.style import Style


def test_changeset_round_trip() -> None:
    shape = commands.make_shape(ShapeKind.RECTANGLE, Rect(0, 0, 10, 10), Style())
    empty = Document()
    change = Changeset.between("Add", empty, {shape.id: shape})
    after = change.apply(empty)
    assert after.order == (shape.id,)
    assert change.revert(after).order == ()


def test_undo_redo_restore_documents_and_selection() -> None:
    history = History()
    shape = commands.make_shape(ShapeKind.ELLIPSE, Rect(0, 0, 10, 10), Style())
    doc0 = Document()
    change = Changeset.between("Add", doc0, {shape.id: shape})
    doc1 = change.apply(doc0)
    history.record(change, frozenset(), frozenset({shape.id}))
    undone = history.undo(doc1)
    assert undone is not None
    assert undone[0].order == () and undone[1] == frozenset()
    redone = history.redo(undone[0])
    assert redone is not None
    assert redone[0].order == (shape.id,) and redone[1] == frozenset({shape.id})


def test_edits_with_the_same_key_merge_within_the_window() -> None:
    history = History(merge_window=1.0)
    shape = commands.make_shape(ShapeKind.RECTANGLE, Rect(0, 0, 10, 10), Style())
    doc = Document.of([shape])
    for i, opacity in enumerate((90, 80, 70)):
        change = Changeset.between(
            "Opacity", doc, commands.set_style(doc, [shape.id], opacity=opacity)
        )
        doc = change.apply(doc)
        history.record(change, frozenset(), frozenset(), merge_key="opacity", now=i * 0.3)
    undone = history.undo(doc)
    assert undone is not None
    assert undone[0].get(shape.id).style.opacity == 100  # type: ignore[union-attr]
    assert not history.can_undo


def test_settings_changes_are_undoable() -> None:
    doc = Document()
    change = Changeset.between("Sheet", doc, {}, settings=CanvasSettings(sheet="lines"))
    after = change.apply(doc)
    assert after.settings.sheet == "lines"
    assert change.revert(after).settings.sheet == CanvasSettings().sheet


def test_new_edit_clears_redo() -> None:
    history = History()
    shape = commands.make_shape(ShapeKind.RECTANGLE, Rect(0, 0, 10, 10), Style())
    doc = Document()
    change = Changeset.between("Add", doc, {shape.id: shape})
    history.record(change, frozenset(), frozenset())
    history.undo(change.apply(doc))
    history.record(change, frozenset(), frozenset())
    assert not history.can_redo
