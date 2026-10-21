"""Builds packaging/schemeup.ico from the app's SVG logo.

Run with `uv run python packaging/make_icon.py`. The icon file is committed, so this is
only needed when the logo changes. An .ico is a small directory of images; modern Windows
reads PNG-compressed entries, which keeps the file tiny and the edges sharp.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "src" / "schemeup" / "resources" / "icons" / "app.svg"
TARGET = Path(__file__).resolve().parent / "schemeup.ico"
ACCENT = "#6d5dfc"
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def render(svg: bytes, size: int) -> bytes:
    renderer = QSvgRenderer(QByteArray(svg))
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data().data())


def main() -> None:
    app = QGuiApplication([])
    svg = LOGO.read_text(encoding="utf-8").replace("currentColor", ACCENT).encode("utf-8")
    pictures = [(size, render(svg, size)) for size in SIZES]
    header = struct.pack("<HHH", 0, 1, len(pictures))
    offset = len(header) + 16 * len(pictures)
    entries = b""
    for size, data in pictures:
        side = 0 if size >= 256 else size  # 0 means 256 in the format
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    TARGET.write_bytes(header + entries + b"".join(data for _, data in pictures))
    print(f"wrote {TARGET} ({TARGET.stat().st_size} bytes, {len(pictures)} sizes)")
    del app


if __name__ == "__main__":
    main()
