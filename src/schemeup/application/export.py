"""What an export is, independently of how each format writes it."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from schemeup.domain.document import Document
from schemeup.domain.export_layout import PageLayout


class ExportFormat(StrEnum):
    PNG = "png"
    SVG = "svg"
    PDF = "pdf"
    DOCX = "docx"
    SCHEMEUP = "schemeup"

    @property
    def paged(self) -> bool:
        return self in (ExportFormat.PDF, ExportFormat.DOCX)

    @property
    def extension(self) -> str:
        return self.value


class ExportScope(StrEnum):
    ALL = "all"
    SELECTION = "selection"


@dataclass(frozen=True, slots=True)
class ExportRequest:
    format: ExportFormat
    scope: ExportScope = ExportScope.ALL
    layout: PageLayout = PageLayout.FIT
    page: str = "A4"
    landscape: bool = False
    background: bool = True
    dark: bool = False
    scale: float = 2.0  # PNG pixel density
    text_as_paths: bool = True  # SVG: outlines so the file looks the same without the fonts
    text_appendix: bool = True  # DOCX: the note's text as editable paragraphs after the drawings
    title: str = "Untitled"
    tags: tuple[str, ...] = field(default_factory=tuple)


class Exporter(Protocol):
    def export(
        self, document: Document, request: ExportRequest, selection: frozenset[str], path: Path
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ImportedNote:
    title: str
    document: Document
    files: dict[str, bytes]  # asset id -> content
    tags: tuple[str, ...] = ()


class Importer(Protocol):
    def read(self, path: Path) -> ImportedNote: ...
