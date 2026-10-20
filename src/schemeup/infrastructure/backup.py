"""Daily backups of the library with SQLite's online backup API."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from schemeup.infrastructure.database import Database

PREFIX = "library-"
SUFFIX = ".sqlite3"


class Backups:
    def __init__(self, db: Database, directory: Path, keep: int = 10) -> None:
        self._db = db
        self.directory = directory
        self._keep = keep

    def existing(self) -> list[Path]:
        if not self.directory.exists():
            return []
        return sorted(self.directory.glob(f"{PREFIX}*{SUFFIX}"))

    def run_if_due(self, now: datetime, every: timedelta = timedelta(hours=24)) -> Path | None:
        backups = self.existing()
        if backups:
            last = datetime.fromtimestamp(backups[-1].stat().st_mtime)
            if now.replace(tzinfo=None) - last < every:
                return None
        return self.run(now)

    def run(self, now: datetime) -> Path:
        target = self.directory / f"{PREFIX}{now.strftime('%Y%m%d-%H%M%S')}{SUFFIX}"
        self._db.backup_to(target)
        for old in self.existing()[: -self._keep]:
            old.unlink(missing_ok=True)
        return target
