"""Streaks and shading levels for the activity heatmap."""

from __future__ import annotations

import math
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta

LEVELS = 4  # shades above "nothing happened"


@dataclass(frozen=True, slots=True)
class Streaks:
    current: int  # consecutive active days up to today (or yesterday, if today is still empty)
    longest: int


def streaks(active_days: Collection[date], today: date) -> Streaks:
    """Run lengths of consecutive days in `active_days`.

    A streak is not broken just because today has no activity yet: the current
    streak then counts back from yesterday, so opening the app in the morning
    doesn't show a zero."""
    active = set(active_days)
    longest = run = 0
    previous: date | None = None
    for day in sorted(active):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day

    current = 0
    cursor = today if today in active else today - timedelta(days=1)
    while cursor in active:
        current += 1
        cursor -= timedelta(days=1)
    return Streaks(current, longest)


def level(count: int, peak: int) -> int:
    """Shade from 0 (nothing) to LEVELS for `count` notes, relative to the busiest day."""
    if count <= 0 or peak <= 0:
        return 0
    return min(LEVELS, max(1, math.ceil(LEVELS * count / peak)))
