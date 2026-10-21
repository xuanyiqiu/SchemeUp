from pathlib import Path

from schemeup import smoke
from schemeup.application.export import ExportFormat, ExportRequest
from schemeup.application.ports import MemoryAssetStore
from schemeup.domain.document import Document
from schemeup.infrastructure.export import FileExporter
from schemeup.ui.main_window import MainWindow


class FailingPdf:
    """An exporter whose PDF export is broken, as a packaged build with a missing file would be."""

    def __init__(self) -> None:
        self._real = FileExporter(MemoryAssetStore())

    def export(
        self, document: Document, request: ExportRequest, selection: frozenset[str], path: Path
    ) -> None:
        if request.format is ExportFormat.PDF:
            raise OSError("no pdf support")
        self._real.export(document, request, selection, path)


def test_a_healthy_build_reports_no_problems(window: MainWindow) -> None:
    assert smoke.problems(window, FileExporter(MemoryAssetStore())) == []


def test_a_broken_export_is_reported_by_name(window: MainWindow) -> None:
    issues = smoke.problems(window, FailingPdf())
    assert issues == ["export to pdf failed: no pdf support"]


def test_finishing_writes_the_verdict_and_exits_with_it(window: MainWindow, tmp_path: Path) -> None:
    class Recorder:
        code: int | None = None

        def exit(self, code: int) -> None:
            self.code = code

    app = Recorder()
    report = tmp_path / "report.txt"
    smoke.finish(app, window, FileExporter(MemoryAssetStore()), report)  # type: ignore[arg-type]
    assert report.read_text(encoding="utf-8") == "ok"
    assert app.code == 0
    smoke.finish(app, window, FailingPdf(), report)  # type: ignore[arg-type]
    assert "pdf" in report.read_text(encoding="utf-8")
    assert app.code == 1
