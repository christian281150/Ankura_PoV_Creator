"""Typed access to the slide-six layout data extracted from the Ankura master."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class LayoutSpecError(ValueError):
    """Raised when the declarative layout file is malformed."""


@dataclass(frozen=True)
class Rectangle:
    """A slide rectangle in inches."""

    x: float
    y: float
    width: float
    height: float

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> Rectangle:
        _require_keys(data, {"x", "y", "width", "height"}, "rectangle")
        return cls(**{key: float(data[key]) for key in ("x", "y", "width", "height")})

    def to_data(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class FontStyle:
    family: str
    size_pt: float
    weight: str
    color: str

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> FontStyle:
        _require_keys(data, {"family", "size_pt", "weight", "color"}, "font style")
        return cls(str(data["family"]), float(data["size_pt"]), str(data["weight"]), str(data["color"]))

    def to_data(self) -> dict[str, Any]:
        return {"family": self.family, "size_pt": self.size_pt, "weight": self.weight, "color": self.color}


@dataclass(frozen=True)
class Quadrant:
    rect: Rectangle
    header: Rectangle
    content: Rectangle

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> Quadrant:
        _require_keys(data, {"rect", "header", "content"}, "quadrant")
        return cls(*(Rectangle.from_data(_mapping(data[key], f"quadrant.{key}")) for key in ("rect", "header", "content")))

    def to_data(self) -> dict[str, dict[str, float]]:
        return {"rect": self.rect.to_data(), "header": self.header.to_data(), "content": self.content.to_data()}


@dataclass(frozen=True)
class Slide6Layout:
    """The complete declarative source-of-truth for the designated profile slide."""

    data: Mapping[str, Any]
    header: Mapping[str, Rectangle]
    quadrants: Mapping[str, Quadrant]
    products_picture_frames: Mapping[str, Rectangle]
    font_ramp: Mapping[str, FontStyle]
    palette: Mapping[str, str]
    header_rule: Rectangle
    logo_lockup: Rectangle
    footnote_band: Rectangle
    footnote_leading_mode: str

    def header_rect(self, name: str) -> Rectangle:
        return self._get(self.header, name, "header rectangle")

    def quadrant(self, name: str) -> Quadrant:
        return self._get(self.quadrants, name, "quadrant")

    def picture_frame(self, name: str) -> Rectangle:
        return self._get(self.products_picture_frames, name, "products picture frame")

    def font(self, role: str) -> FontStyle:
        return self._get(self.font_ramp, role, "font role")

    def color(self, name: str) -> str:
        return self._get(self.palette, name, "palette color")

    def to_data(self) -> dict[str, Any]:
        """Return the parsed layout using the JSON document's original shape."""
        return dict(self.data)

    @staticmethod
    def _get(values: Mapping[str, Any], name: str, kind: str) -> Any:
        try:
            return values[name]
        except KeyError as exc:
            raise LayoutSpecError(f"Unknown {kind}: {name!r}") from exc


def load_slide6_layout(path: str | Path | None = None) -> Slide6Layout:
    """Load the extracted slide-six specification without opening the template."""
    spec_path = Path(path) if path is not None else _default_spec_path()
    try:
        data = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LayoutSpecError(f"Cannot load slide layout spec at {spec_path}") from exc
    root = _mapping(data, "layout specification")
    _require_keys(
        root,
        {"version", "source", "canvas", "header", "quadrants", "products_picture_frames", "font_ramp", "palette", "header_rule", "logo_lockup", "footnote_band"},
        "layout specification",
    )
    header = {name: Rectangle.from_data(_mapping(value, f"header.{name}")) for name, value in _mapping(root["header"], "header").items()}
    quadrants = {name: Quadrant.from_data(_mapping(value, f"quadrants.{name}")) for name, value in _mapping(root["quadrants"], "quadrants").items()}
    frames = {name: Rectangle.from_data(_mapping(value, f"products_picture_frames.{name}")) for name, value in _mapping(root["products_picture_frames"], "products_picture_frames").items()}
    fonts = {name: FontStyle.from_data(_mapping(value, f"font_ramp.{name}")) for name, value in _mapping(root["font_ramp"], "font_ramp").items()}
    palette = {name: str(value) for name, value in _mapping(root["palette"], "palette").items()}
    return Slide6Layout(
        data=root,
        header=header,
        quadrants=quadrants,
        products_picture_frames=frames,
        font_ramp=fonts,
        palette=palette,
        header_rule=Rectangle.from_data(_mapping(root["header_rule"], "header_rule")["rect"]),
        logo_lockup=Rectangle.from_data(_mapping(root["logo_lockup"], "logo_lockup")["rect"]),
        footnote_band=Rectangle.from_data(_mapping(root["footnote_band"], "footnote_band")["rect"]),
        footnote_leading_mode=str(_mapping(root["footnote_band"], "footnote_band")["leading"]["mode"]),
    )


def _default_spec_path() -> Path:
    return Path(__file__).resolve().parents[2] / "render" / "templates" / "slide6_layout.json"


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LayoutSpecError(f"{name} must be an object")
    return value


def _require_keys(data: Mapping[str, Any], expected: set[str], name: str) -> None:
    keys = set(data)
    if keys != expected:
        raise LayoutSpecError(f"{name} keys must be {sorted(expected)!r}, got {sorted(keys)!r}")
