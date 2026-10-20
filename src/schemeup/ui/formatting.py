"""Human-friendly dates and sizes for the UI."""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QCoreApplication


def _tr(text: str) -> str:
    return QCoreApplication.translate("Formatting", text)


def local(millis: int) -> datetime:
    return datetime.fromtimestamp(millis / 1000)


def relative_time(millis: int, now: datetime | None = None) -> str:
    """'14:32' today, 'Yesterday', 'Mon' this week, '12 Oct' this year, '12 Oct 2024' before."""
    moment = local(millis)
    now = now or datetime.now()
    if moment.date() == now.date():
        return moment.strftime("%H:%M")
    if moment.date() == (now - timedelta(days=1)).date():
        return _tr("Yesterday")
    if now - moment < timedelta(days=7):
        return moment.strftime("%a")
    if moment.year == now.year:
        return moment.strftime("%d %b").lstrip("0")
    return moment.strftime("%d %b %Y").lstrip("0")


def full_time(millis: int) -> str:
    return local(millis).strftime("%d %b %Y, %H:%M").lstrip("0")


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"
