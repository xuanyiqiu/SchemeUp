"""User preferences. The JSON file that stores them lives in infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class Settings:
    theme: str = "system"  # system | light | dark
    language: str = "system"  # system | en | es
    hotkey: str = "Ctrl+Alt+N"
    close_to_tray: bool = True
    motion: str = "system"  # system | full | reduced
    snap_objects: bool = False
    snap_grid: bool = False
    last_note_id: int | None = None
    sidebar_visible: bool = True
    window_geometry: str = ""
    backups_dir: str = ""  # empty means the default folder next to the library
    clean_exit: bool = True
    welcome_seen: bool = False


class SettingsStore(Protocol):
    def load(self) -> Settings: ...

    def save(self, settings: Settings) -> None: ...


class MemorySettingsStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()

    def load(self) -> Settings:
        return self._settings

    def save(self, settings: Settings) -> None:
        self._settings = settings
