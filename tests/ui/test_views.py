from datetime import date, datetime

import pytest
from pytestqt.qtbot import QtBot

from schemeup.application.library import LibraryService
from schemeup.infrastructure.database import Database
from schemeup.infrastructure.library_store import SqliteLibrary
from schemeup.rendering.text import QtTextMeasurer
from schemeup.ui.board_view import BoardView, ColumnWidget
from schemeup.ui.calendar_view import CalendarView, month_grid, week_days
from schemeup.ui.theme import LIGHT


@pytest.fixture
def library() -> LibraryService:
    return LibraryService(SqliteLibrary(Database(":memory:")), QtTextMeasurer())


def test_board_shows_columns_and_moves_cards(qtbot: QtBot, library: LibraryService) -> None:
    board = library.create_board("Prep", ["Todo", "Done"])
    todo, done = library.columns(board.id)
    note = library.create_note(title="Two Sum")
    library.place_card(board.id, note.id, todo.id)
    view = BoardView(library, LIGHT)
    qtbot.addWidget(view)
    view.show()
    view.show_board(board.id)
    columns = view.findChildren(ColumnWidget)
    assert [c.column.name for c in columns] == ["Todo", "Done"]
    assert columns[0].cards.count() == 1
    view.card_dropped(note.id, done.id, 0)
    assert library.cards(board.id)[0].column_id == done.id
    columns = view.findChildren(ColumnWidget)
    assert [c.cards.count() for c in columns if not c.isHidden()][-1] == 1


def test_month_grid_starts_on_monday_and_covers_six_weeks() -> None:
    days = month_grid(2026, 10)
    assert len(days) == 42
    assert days[0] == date(2026, 9, 28) and days[0].weekday() == 0
    assert date(2026, 10, 31) in days
    assert week_days(date(2026, 10, 21))[0] == date(2026, 10, 19)


def test_calendar_lists_the_notes_of_a_day(qtbot: QtBot, library: LibraryService) -> None:
    library.create_note(title="Today's meeting", template_id="meeting")
    view = CalendarView(library, LIGHT)
    qtbot.addWidget(view)
    view.show()
    view.refresh()
    today = datetime.now().date()
    assert today in view.grid.data
    view._show_day(today)
    titles = [view.day_list.item(i).text() for i in range(view.day_list.count())]
    assert "Today's meeting" in titles


def test_calendar_empty_day(qtbot: QtBot, library: LibraryService) -> None:
    view = CalendarView(library, LIGHT)
    qtbot.addWidget(view)
    view._show_day(date(2020, 1, 1))
    assert view.day_list.count() == 1
