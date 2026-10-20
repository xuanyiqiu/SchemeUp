"""The canvas document format: plain dicts that map 1:1 to JSON.

Used for storage, `.schemeup` files and the clipboard. Every document carries
its format version; older versions are upgraded by a chain of migration
functions, and newer ones are refused instead of half-loaded.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from enum import Enum
from typing import Any

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
)
from schemeup.domain.errors import UnsupportedFormatError
from schemeup.domain.geometry import Point
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

FORMAT = "schemeup.canvas"
CURRENT_VERSION = 1

# version N -> version N + 1
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}

_ENUM_FIELDS: dict[str, type[Enum]] = {
    "fill_style": FillStyle,
    "stroke_style": StrokeStyle,
    "roundness": Roundness,
    "font_family": FontFamily,
    "text_align": TextAlign,
    "vertical_align": VerticalAlign,
    "start_head": Arrowhead,
    "end_head": Arrowhead,
}

_TYPES: dict[type, str] = {
    Rectangle: "rectangle",
    Diamond: "diamond",
    Ellipse: "ellipse",
    Line: "line",
    Arrow: "arrow",
    Freedraw: "freedraw",
    Text: "text",
    Image: "image",
    Frame: "frame",
}
_CLASSES = {name: cls for cls, name in _TYPES.items()}


def style_to_dict(style: Style) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for f in fields(Style):
        value = getattr(style, f.name)
        result[f.name] = value.value if isinstance(value, Enum) else value
    return result


def style_from_dict(data: dict[str, Any]) -> Style:
    known = {f.name for f in fields(Style)}
    values: dict[str, Any] = {}
    for key, value in data.items():
        if key not in known:
            continue
        enum_type = _ENUM_FIELDS.get(key)
        if enum_type is not None:
            try:
                value = enum_type(value)
            except ValueError:
                continue
        values[key] = value
    return Style(**values)


def _points_to_list(points: tuple[Point, ...]) -> list[list[float]]:
    return [[round(p.x, 3), round(p.y, 3)] for p in points]


def _points_from_list(data: list[list[float]]) -> tuple[Point, ...]:
    return tuple(Point(float(x), float(y)) for x, y in data) or (Point(0.0, 0.0),)


def _binding_to_dict(binding: Binding | None) -> dict[str, Any] | None:
    if binding is None:
        return None
    return {
        "element_id": binding.element_id,
        "anchor": [binding.anchor.x, binding.anchor.y],
        "gap": binding.gap,
    }


def _binding_from_dict(data: dict[str, Any] | None) -> Binding | None:
    if not data:
        return None
    u, v = data.get("anchor", [0.5, 0.5])
    return Binding(
        element_id=str(data["element_id"]),
        anchor=Point(float(u), float(v)),
        gap=float(data.get("gap", 6.0)),
    )


def element_to_dict(element: Element) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": element.id,
        "type": _TYPES[type(element)],
        "x": element.x,
        "y": element.y,
        "width": element.width,
        "height": element.height,
        "angle": element.angle,
        "seed": element.seed,
        "version": element.version,
        "locked": element.locked,
        "group_ids": list(element.group_ids),
        "frame_id": element.frame_id,
        "style": style_to_dict(element.style),
    }
    match element:
        case Rectangle() | Diamond() | Ellipse():
            data["label"] = element.label
        case Line():
            data["label"] = element.label
            data["points"] = _points_to_list(element.points)
        case Arrow():
            data["label"] = element.label
            data["points"] = _points_to_list(element.points)
            data["start_binding"] = _binding_to_dict(element.start_binding)
            data["end_binding"] = _binding_to_dict(element.end_binding)
        case Freedraw():
            data["points"] = _points_to_list(element.points)
            data["pressures"] = [round(p, 3) for p in element.pressures]
            data["simulate_pressure"] = element.simulate_pressure
        case Text():
            data["text"] = element.text
            data["auto_width"] = element.auto_width
        case Image():
            data["asset_id"] = element.asset_id
        case Frame():
            data["name"] = element.name
    return data


def element_from_dict(data: dict[str, Any]) -> Element:
    cls = _CLASSES.get(str(data.get("type")))
    if cls is None:
        raise UnsupportedFormatError(f"unknown element type {data.get('type')!r}")
    common: dict[str, Any] = {
        "id": str(data["id"]),
        "x": float(data.get("x", 0.0)),
        "y": float(data.get("y", 0.0)),
        "width": float(data.get("width", 0.0)),
        "height": float(data.get("height", 0.0)),
        "angle": float(data.get("angle", 0.0)),
        "seed": int(data.get("seed", 1)),
        "version": int(data.get("version", 1)),
        "locked": bool(data.get("locked", False)),
        "group_ids": tuple(str(g) for g in data.get("group_ids", ())),
        "frame_id": data.get("frame_id"),
        "style": style_from_dict(data.get("style", {})),
    }
    if cls in (Rectangle, Diamond, Ellipse):
        return cls(**common, label=str(data.get("label", "")))
    if cls is Line:
        return Line(
            **common,
            label=str(data.get("label", "")),
            points=_points_from_list(data.get("points", [])),
        )
    if cls is Arrow:
        return Arrow(
            **common,
            label=str(data.get("label", "")),
            points=_points_from_list(data.get("points", [])),
            start_binding=_binding_from_dict(data.get("start_binding")),
            end_binding=_binding_from_dict(data.get("end_binding")),
        )
    if cls is Freedraw:
        return Freedraw(
            **common,
            points=_points_from_list(data.get("points", [])),
            pressures=tuple(float(p) for p in data.get("pressures", ())),
            simulate_pressure=bool(data.get("simulate_pressure", True)),
        )
    if cls is Text:
        return Text(
            **common, text=str(data.get("text", "")), auto_width=bool(data.get("auto_width", True))
        )
    if cls is Image:
        return Image(**common, asset_id=str(data.get("asset_id", "")))
    return Frame(**common, name=str(data.get("name", "Frame")))


def settings_to_dict(settings: CanvasSettings) -> dict[str, Any]:
    return {
        "background": settings.background,
        "sheet": settings.sheet,
        "line_spacing_mm": settings.line_spacing_mm,
        "page_size": settings.page_size,
        "page_landscape": settings.page_landscape,
    }


def settings_from_dict(data: dict[str, Any]) -> CanvasSettings:
    defaults = CanvasSettings()
    return CanvasSettings(
        background=str(data.get("background", defaults.background)),
        sheet=str(data.get("sheet", defaults.sheet)),
        line_spacing_mm=float(data.get("line_spacing_mm", defaults.line_spacing_mm)),
        page_size=data.get("page_size"),
        page_landscape=bool(data.get("page_landscape", False)),
    )


def document_to_dict(document: Document) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "version": CURRENT_VERSION,
        "settings": settings_to_dict(document.settings),
        "elements": [element_to_dict(e) for e in document.ordered()],
    }


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("format") != FORMAT:
        raise UnsupportedFormatError("not a SchemeUp canvas")
    version = int(data.get("version", 0))
    if version > CURRENT_VERSION:
        raise UnsupportedFormatError(
            f"this note was saved by a newer version of SchemeUp (format {version})"
        )
    while version < CURRENT_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise UnsupportedFormatError(f"no migration from format {version}")
        data = step(data)
        version += 1
        data["version"] = version
    return data


def document_from_dict(data: dict[str, Any]) -> Document:
    data = migrate(data)
    elements = [element_from_dict(e) for e in data.get("elements", [])]
    return Document.of(elements, settings_from_dict(data.get("settings", {})))
