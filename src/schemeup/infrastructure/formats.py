"""Reading notes from files: SchemeUp's own `.schemeup` and Excalidraw's `.excalidraw`."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
from typing import Any

from schemeup.application.export import ImportedNote
from schemeup.domain.document import CanvasSettings, Document
from schemeup.domain.elements import (
    Arrow,
    Binding,
    Diamond,
    Element,
    Ellipse,
    Frame,
    Freedraw,
    Image,
    Line,
    Rectangle,
    Text,
    new_seed,
    with_world_points,
)
from schemeup.domain.errors import UnsupportedFormatError
from schemeup.domain.geometry import Point
from schemeup.domain.serialization import FORMAT as CANVAS_FORMAT
from schemeup.domain.serialization import document_from_dict
from schemeup.domain.style import (
    Arrowhead,
    FillStyle,
    FontFamily,
    Roundness,
    StrokeStyle,
    Style,
    TextAlign,
    VerticalAlign,
)
from schemeup.infrastructure.export import NOTE_FORMAT

EXCALIDRAW_FONTS = {
    1: FontFamily.HAND,
    2: FontFamily.NORMAL,
    3: FontFamily.CODE,
    5: FontFamily.HAND,
    6: FontFamily.NORMAL,
    8: FontFamily.CODE,
}
EXCALIDRAW_FILLS = {
    "hachure": FillStyle.HACHURE,
    "cross-hatch": FillStyle.CROSS_HATCH,
    "solid": FillStyle.SOLID,
}
EXCALIDRAW_HEADS = {
    "arrow": Arrowhead.ARROW,
    "triangle": Arrowhead.TRIANGLE,
    "triangle_outline": Arrowhead.TRIANGLE,
    "dot": Arrowhead.DOT,
    "circle": Arrowhead.DOT,
    "circle_outline": Arrowhead.DOT,
    "bar": Arrowhead.BAR,
    "diamond": Arrowhead.TRIANGLE,
    "diamond_outline": Arrowhead.TRIANGLE,
}


class FileImporter:
    def read(self, path: Path) -> ImportedNote:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise UnsupportedFormatError(f"{path.name} is not a readable note file") from error
        if not isinstance(data, dict):
            raise UnsupportedFormatError(f"{path.name} is not a note file")
        kind = data.get("type") or data.get("format")
        if kind == "excalidraw":
            return excalidraw_note(data, path.stem)
        if kind == NOTE_FORMAT:
            return schemeup_note(data, path.stem)
        if kind == CANVAS_FORMAT:
            return ImportedNote(path.stem, document_from_dict(data), {})
        raise UnsupportedFormatError(f"{path.name} isn't a SchemeUp or Excalidraw file")


def schemeup_note(data: dict[str, Any], fallback_title: str) -> ImportedNote:
    note = data.get("note", {})
    files: dict[str, bytes] = {}
    for asset_id, encoded in data.get("files", {}).items():
        try:
            files[str(asset_id)] = base64.b64decode(encoded)
        except (binascii.Error, TypeError):
            continue
    return ImportedNote(
        title=str(note.get("title") or fallback_title),
        document=document_from_dict(data.get("document", {})),
        files=files,
        tags=tuple(str(t) for t in note.get("tags", [])),
    )


def _width(value: float) -> float:
    return min((1.0, 2.0, 4.0), key=lambda w: abs(w - value))


def _style(el: dict[str, Any], text: dict[str, Any] | None = None) -> Style:
    source = text or el
    return Style(
        stroke_color=str(el.get("strokeColor", "#1e1e1e")),
        fill_color=str(el.get("backgroundColor", "transparent")),
        fill_style=EXCALIDRAW_FILLS.get(str(el.get("fillStyle")), FillStyle.HACHURE),
        stroke_width=_width(float(el.get("strokeWidth", 2))),
        stroke_style=StrokeStyle(el.get("strokeStyle", "solid"))
        if el.get("strokeStyle") in ("solid", "dashed", "dotted")
        else StrokeStyle.SOLID,
        roughness=min(max(int(el.get("roughness", 1)), 0), 2),
        opacity=min(max(int(el.get("opacity", 100)), 0), 100),
        roundness=Roundness.ROUND if el.get("roundness") else Roundness.SHARP,
        font_family=EXCALIDRAW_FONTS.get(int(source.get("fontFamily", 5) or 5), FontFamily.HAND),
        font_size=float(source.get("fontSize", 20)),
        text_align=TextAlign(source.get("textAlign", "center"))
        if source.get("textAlign") in ("left", "center", "right")
        else TextAlign.CENTER,
        vertical_align=VerticalAlign(source.get("verticalAlign", "middle"))
        if source.get("verticalAlign") in ("top", "middle", "bottom")
        else VerticalAlign.MIDDLE,
        start_head=EXCALIDRAW_HEADS.get(str(el.get("startArrowhead")), Arrowhead.NONE),
        end_head=EXCALIDRAW_HEADS.get(str(el.get("endArrowhead")), Arrowhead.NONE),
    )


def _binding(data: dict[str, Any] | None) -> Binding | None:
    if not data or not data.get("elementId"):
        return None
    return Binding(
        element_id=str(data["elementId"]), anchor=Point(0.5, 0.5), gap=float(data.get("gap", 6))
    )


def excalidraw_note(data: dict[str, Any], title: str) -> ImportedNote:
    raw = [e for e in data.get("elements", []) if isinstance(e, dict) and not e.get("isDeleted")]
    labels = {
        str(e["containerId"]): e for e in raw if e.get("type") == "text" and e.get("containerId")
    }
    files: dict[str, bytes] = {}
    file_ids: dict[str, str] = {}
    for file_id, entry in (data.get("files") or {}).items():
        url = str(entry.get("dataURL", ""))
        if "," in url:
            try:
                content = base64.b64decode(url.split(",", 1)[1])
            except (binascii.Error, ValueError):
                continue
            asset_id = hashlib.sha256(content).hexdigest()
            files[asset_id] = content
            file_ids[str(file_id)] = asset_id

    elements: list[Element] = []
    for el in raw:
        kind = el.get("type")
        if kind == "text" and el.get("containerId"):
            continue  # becomes the label of its container
        label_source = labels.get(str(el.get("id")))
        common: dict[str, Any] = {
            "id": str(el.get("id")),
            "x": float(el.get("x", 0)),
            "y": float(el.get("y", 0)),
            "width": abs(float(el.get("width", 0))),
            "height": abs(float(el.get("height", 0))),
            "angle": float(el.get("angle", 0)),
            "style": _style(el, label_source),
            "seed": int(el.get("seed") or new_seed()),
            "locked": bool(el.get("locked", False)),
            "group_ids": tuple(str(g) for g in el.get("groupIds", [])),
            "frame_id": el.get("frameId"),
        }
        label = str(label_source.get("text", "")) if label_source else ""
        if kind == "rectangle":
            elements.append(Rectangle(**common, label=label))
        elif kind == "diamond":
            elements.append(Diamond(**common, label=label))
        elif kind == "ellipse":
            elements.append(Ellipse(**common, label=label))
        elif kind in ("line", "arrow"):
            points = [
                Point(common["x"] + float(p[0]), common["y"] + float(p[1]))
                for p in el.get("points", [[0, 0]])
            ]
            base: Line | Arrow
            if kind == "arrow":
                base = Arrow(
                    **common,
                    label=label,
                    start_binding=_binding(el.get("startBinding")),
                    end_binding=_binding(el.get("endBinding")),
                )
            else:
                base = Line(**common, label=label)
            elements.append(with_world_points(base, points))
        elif kind == "freedraw":
            points = [
                Point(common["x"] + float(p[0]), common["y"] + float(p[1]))
                for p in el.get("points", [[0, 0]])
            ]
            stroke = Freedraw(
                **common,
                pressures=tuple(float(p) for p in el.get("pressures", [])),
                simulate_pressure=bool(el.get("simulatePressure", True)),
            )
            elements.append(with_world_points(stroke, points))
        elif kind == "text":
            elements.append(
                Text(
                    **common,
                    text=str(el.get("text", "")),
                    auto_width=bool(el.get("autoResize", True)),
                )
            )
        elif kind == "image":
            elements.append(Image(**common, asset_id=file_ids.get(str(el.get("fileId")), "")))
        elif kind in ("frame", "magicframe"):
            elements.append(Frame(**common, name=str(el.get("name") or "Frame")))
    background = str((data.get("appState") or {}).get("viewBackgroundColor", "#ffffff"))
    settings = CanvasSettings(
        background=background if background.startswith("#") else "#ffffff", sheet="plain"
    )
    return ImportedNote(title, Document.of(elements, settings), files)
