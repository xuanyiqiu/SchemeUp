from datetime import date, timedelta

import pytest

from schemeup.domain.streaks import LEVELS, Streaks, level, streaks

TODAY = date(2026, 10, 21)


def days_ago(*offsets: int) -> list[date]:
    return [TODAY - timedelta(days=n) for n in offsets]


def test_no_activity_has_no_streak() -> None:
    assert streaks([], TODAY) == Streaks(0, 0)


def test_current_streak_counts_back_from_today() -> None:
    assert streaks(days_ago(0, 1, 2, 5), TODAY) == Streaks(3, 3)


def test_an_empty_today_does_not_break_the_streak_yet() -> None:
    assert streaks(days_ago(1, 2, 3), TODAY) == Streaks(3, 3)


def test_two_empty_days_break_the_streak() -> None:
    assert streaks(days_ago(2, 3, 4), TODAY) == Streaks(0, 3)


def test_the_longest_streak_can_be_in_the_past() -> None:
    assert streaks(days_ago(0, 10, 11, 12, 13, 14), TODAY) == Streaks(1, 5)


def test_duplicates_and_order_do_not_matter() -> None:
    assert streaks(days_ago(2, 0, 1, 1, 0), TODAY) == Streaks(3, 3)


@pytest.mark.parametrize(
    ("count", "peak", "expected"),
    [(0, 10, 0), (1, 10, 1), (3, 10, 2), (5, 10, 2), (6, 10, 3), (10, 10, 4), (1, 1, 4), (4, 0, 0)],
)
def test_level_is_relative_to_the_busiest_day(count: int, peak: int, expected: int) -> None:
    assert level(count, peak) == expected
    assert 0 <= level(count, peak) <= LEVELS
