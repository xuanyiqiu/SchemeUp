from datetime import date, timedelta

from PySide6.QtCore import QPointF

from schemeup.application.library import LibraryService
from schemeup.ui.heatmap import WEEKS, ActivityHeatmap, first_day
from schemeup.ui.main_window import MainWindow
from schemeup.ui.theme import DARK, LIGHT

TODAY = date(2026, 10, 21)  # a Wednesday


def heatmap(counts: dict[date, int] | None = None) -> ActivityHeatmap:
    widget = ActivityHeatmap(LIGHT)
    widget.set_data(counts or {}, TODAY)
    return widget


def test_the_grid_starts_on_a_monday_and_ends_this_week() -> None:
    start = first_day(TODAY)
    assert start.weekday() == 0
    assert (TODAY - start).days // 7 == WEEKS - 1


def test_cells_sit_in_week_columns_with_monday_first() -> None:
    widget = heatmap()
    monday = widget.cell_rect(widget.start)
    tuesday = widget.cell_rect(widget.start + timedelta(days=1))
    next_week = widget.cell_rect(widget.start + timedelta(days=7))
    assert monday is not None and tuesday is not None and next_week is not None
    assert tuesday.x() == monday.x() and tuesday.y() > monday.y()
    assert next_week.y() == monday.y() and next_week.x() > monday.x()


def test_there_are_no_cells_for_the_future_or_before_the_grid() -> None:
    widget = heatmap()
    assert widget.cell_rect(TODAY) is not None
    assert widget.cell_rect(TODAY + timedelta(days=1)) is None
    assert widget.cell_rect(widget.start - timedelta(days=1)) is None


def test_a_click_position_maps_back_to_its_day() -> None:
    widget = heatmap()
    for day in (widget.start, TODAY, TODAY - timedelta(days=100)):
        rect = widget.cell_rect(day)
        assert rect is not None
        assert widget.day_at(rect.center()) == day
    assert widget.day_at(QPointF(2, 2)) is None
    assert widget.day_at(QPointF(500, 500)) is None


def test_busier_days_get_a_stronger_color() -> None:
    widget = heatmap({TODAY: 1, TODAY - timedelta(days=1): 8})
    quiet = widget.level_color(1)
    busy = widget.level_color(4)
    empty = widget.level_color(0)
    assert empty != quiet != busy
    assert busy.saturation() > quiet.saturation() > empty.saturation()


def test_both_themes_have_visible_empty_cells() -> None:
    for theme in (LIGHT, DARK):
        widget = ActivityHeatmap(theme)
        assert widget.level_color(0).name() != theme.panel


def test_tooltip_text_says_how_many_notes_and_when() -> None:
    widget = heatmap({TODAY: 3, TODAY - timedelta(days=1): 1})
    assert widget.describe(TODAY).startswith("3 notes on")
    assert widget.describe(TODAY - timedelta(days=1)).startswith("1 note on")
    assert widget.describe(TODAY - timedelta(days=2)).startswith("Nothing on")


def test_the_welcome_page_summarises_the_year(window: MainWindow, library: LibraryService) -> None:
    window.welcome.refresh()
    assert "Nothing yet" in window.welcome.year_label.text()

    library.create_note(None, "blank")
    window.welcome.refresh()
    assert window.welcome.year_label.text() == "1 note touched in the last year"
    assert window.welcome.streak_label.text() == "Current streak 1 day, longest 1 day"
    today = date.today()
    assert window.welcome.heatmap.describe(today).startswith("1 note on")
