"""Interfaces the application layer needs from the outside world.

Infrastructure implements them (SQLite, files, OS); tests use in-memory fakes.
"""

from __future__ import annotations

import hashlib
from typing import Protocol


class AssetStore(Protocol):
    """Binary files (images) stored once and referenced by the SHA-256 of their content."""

    def put(self, data: bytes, mime: str) -> str: ...

    def get(self, asset_id: str) -> bytes | None: ...


def asset_id_for(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class MemoryAssetStore:
    def __init__(self) -> None:
        self._data: dict[str, tuple[bytes, str]] = {}

    def put(self, data: bytes, mime: str) -> str:
        asset_id = asset_id_for(data)
        self._data.setdefault(asset_id, (data, mime))
        return asset_id

    def get(self, asset_id: str) -> bytes | None:
        item = self._data.get(asset_id)
        return item[0] if item else None
