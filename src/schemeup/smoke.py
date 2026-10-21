"""`schemeup --smoke-test`: start up, draw a frame, export every format, and report.

Packaged builds run this so a missing font, icon or library shows up as a failed build
instead of as a broken program on someone's desktop. It writes into a temporary folder
and never touches the user's notes, hotkey or running copy of the app.
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from schemeup.application.export import Exporter, ExportFormat, ExportRequest
from schemeup.application.library import fit_document
from schemeup.domain.templates import architecture
from schemeup.rendering.text import QtTextMeasurer
from schemeup.ui.main_window import MainWindow
from schemeup.ui.theme import icon

REQUIRED_FONTS = ("Shantell Sans", "Inter", "JetBrains Mono")


def problems(window: MainWindow, exporter: Exporter) -> list[str]:
    """Everything that is wrong with this build, as sentences; empty when it is healthy."""
    found: list[str] = []
    families = set(QFontDatabase.families())
    found += [f"font missing: {name}" for name in REQUIRED_FONTS if name not in families]
    if icon("app", "#000000").isNull():
        found.append("icon missing: app")
    if window.grab().isNull():
        found.append("the window drew nothing")

    document = fit_document(architecture(datetime(2026, 1, 1)), QtTextMeasurer())
    with tempfile.TemporaryDirectory(prefix="schemeup-smoke-") as folder:
        for fmt in ExportFormat:
            path = Path(folder) / f"export.{fmt.value}"
            try:
                exporter.export(document, ExportRequest(fmt), frozenset(), path)
            except Exception as error:  # report any failure, whatever its type
                found.append(f"export to {fmt.value} failed: {error}")
                continue
            if not path.exists() or path.stat().st_size == 0:
                found.append(f"export to {fmt.value} wrote nothing")
    return found


def finish(app: QApplication, window: MainWindow, exporter: Exporter, report: Path) -> None:
    """Run the checks, write the result next to `report`, and quit with 0 or 1."""
    issues = problems(window, exporter)
    report.write_text("\n".join(issues) if issues else "ok", encoding="utf-8")
    if window.tray is not None:
        window.tray.hide()  # or its icon lingers in the tray after the process is gone
    app.exit(1 if issues else 0)
