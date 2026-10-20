"""Settings as a small JSON file, written atomically."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, fields
from pathlib import Path

from schemeup.application.settings import Settings


class JsonSettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Settings:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Settings()
        if not isinstance(data, dict):
            return Settings()
        defaults = Settings()
        values = {}
        for field in fields(Settings):
            if field.name not in data:
                continue
            value, default = data[field.name], getattr(defaults, field.name)
            if default is None:
                ok = value is None or (isinstance(value, int) and not isinstance(value, bool))
            elif isinstance(default, bool):
                ok = isinstance(value, bool)
            else:
                ok = isinstance(value, type(default)) and not isinstance(value, bool)
            if ok:
                values[field.name] = value
        try:
            return Settings(**values)
        except TypeError:
            return Settings()

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(settings), indent=2)
        # Write to a temporary file in the same folder, then swap it in: a crash
        # mid-write leaves the old file intact instead of a truncated one.
        fd, temp = tempfile.mkstemp(dir=self.path.parent, prefix=".settings-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
        except OSError:
            Path(temp).unlink(missing_ok=True)
            raise
