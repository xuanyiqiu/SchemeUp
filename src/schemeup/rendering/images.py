"""Decoding stored image assets for the renderer."""

from __future__ import annotations

from typing import Protocol

from PySide6.QtGui import QImage


class AssetSource(Protocol):
    def get(self, asset_id: str) -> bytes | None: ...


class AssetImages:
    """Decodes stored image assets once and keeps them for the renderer."""

    def __init__(self, assets: AssetSource | None) -> None:
        self._assets = assets
        self._cache: dict[str, QImage | None] = {}

    def image(self, asset_id: str) -> QImage | None:
        if asset_id not in self._cache:
            data = self._assets.get(asset_id) if self._assets else None
            image = QImage.fromData(data) if data else QImage()
            self._cache[asset_id] = None if image.isNull() else image
        return self._cache[asset_id]
