"""Reader for LightBurn project files (.lbrn / .lbrn2).

Both are XML. The structure used here was observed in a real LightBurn 2.0 .lbrn2 file:

* ``<CutSetting type="Scan">`` / ``<CutSetting_Img type="Image">`` hold one layer each, with
  ``<index>``, ``<name>``, ``<maxPower>`` (percent), ``<speed>`` (mm/s), ``<frequency>`` (Hz),
  ``<QPulseWidth>`` and ``<interval>`` (mm) as ``Value`` attributes.
* ``<Shape Type=... CutIndex=...>`` elements reference a layer through ``CutIndex``.

The file does not record focus, material batch or passes (DEC-014, DEC-022); nothing here invents them.
Unreadable layer parameters are reported, never replaced by guesses (REQ-015).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

_NUM = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
_VERT = re.compile(rf"V({_NUM}) ({_NUM})")


class LightBurnError(ValueError):
    """The file is not a readable LightBurn project."""


@dataclass
class Region:
    """Fill geometry of one shape: axis-aligned bounding box in project millimetres."""
    kind: str
    x: float
    y: float
    width: float
    height: float
    # Outline in project mm. Rect/bitmap: the four corners. Path: the on-curve vertices only, so curved
    # edges are approximated by straight chords.
    polygon: list[tuple[float, float]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "x": self.x, "y": self.y, "width": self.width, "height": self.height,
                "polygon": [list(p) for p in self.polygon]}


@dataclass
class Layer:
    index: int
    name: str
    layer_type: str
    power: float | None
    frequency_hz: float | None
    speed: float | None
    pulse_width: float | None
    line_interval: float | None
    regions: list[Region] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)

    @property
    def readable(self) -> bool:
        return not self.unreadable

    @property
    def frequency_khz(self) -> float | None:
        return None if self.frequency_hz is None else self.frequency_hz / 1000.0

    def as_dict(self) -> dict:
        return {
            "index": self.index, "name": self.name, "type": self.layer_type,
            "power": self.power, "frequency_khz": self.frequency_khz, "speed": self.speed,
            "pulse_width": self.pulse_width, "line_interval": self.line_interval,
            "readable": self.readable, "unreadable": list(self.unreadable),
            "regions": [r.as_dict() for r in self.regions],
        }


@dataclass
class Project:
    app_version: str | None
    device_name: str | None
    layers: list[Layer]
    notes: str = ""

    @property
    def identifier(self) -> str | None:
        """Experiment/plan identifier written by this system as ``TCE1:<id>`` in the project notes."""
        m = re.search(r"TCE1:([A-Za-z0-9_-]+)", self.notes or "")
        return m.group(1) if m else None

    def layer(self, index: int) -> Layer | None:
        return next((l for l in self.layers if l.index == index), None)


def _value(el: ET.Element, tag: str) -> str | None:
    child = el.find(tag)
    return None if child is None else child.get("Value")


def _number(el: ET.Element, tag: str, missing: list[str], required: bool) -> float | None:
    raw = _value(el, tag)
    if raw is None:
        if required:
            missing.append(f"{tag}: missing")
        return None
    try:
        number = float(raw)
    except ValueError:
        missing.append(f"{tag}: not a number ({raw!r})")
        return None
    if number != number or number in (float("inf"), float("-inf")):
        missing.append(f"{tag}: not finite")
        return None
    return number


def _xform(shape: ET.Element) -> tuple[float, float, float, float, float, float]:
    text = (shape.findtext("XForm") or "1 0 0 1 0 0").split()
    try:
        a, b, c, d, e, f = (float(t) for t in text[:6])
    except ValueError as exc:
        raise LightBurnError(f"invalid XForm {text!r}") from exc
    return a, b, c, d, e, f


def _apply(m, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def _box(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _region(shape: ET.Element) -> Region | None:
    kind = shape.get("Type", "")
    m = _xform(shape)
    if kind in ("Rect", "Bitmap"):
        try:
            w, h = float(shape.get("W", "nan")), float(shape.get("H", "nan"))
        except ValueError:
            return None
        if w != w or h != h:
            return None
        corners = [_apply(m, sx * w / 2, sy * h / 2) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    elif kind == "Path":
        verts = [(float(x), float(y)) for x, y in _VERT.findall(shape.findtext("VertList") or "")]
        if not verts:
            return None
        corners = [_apply(m, x, y) for x, y in verts]
    else:
        return None
    x, y, w, h = _box(corners)
    return Region(kind.lower(), x, y, w, h, polygon=corners)


def parse_bytes(data: bytes) -> Project:
    """Parse the bytes of a .lbrn or .lbrn2 file."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise LightBurnError(f"not a LightBurn project (XML error: {exc})") from exc
    if root.tag != "LightBurnProject":
        raise LightBurnError(f"not a LightBurn project (root element is {root.tag!r})")

    layers: dict[int, Layer] = {}
    for el in root:
        if el.tag not in ("CutSetting", "CutSetting_Img"):
            continue
        problems: list[str] = []
        raw_index = _value(el, "index")
        try:
            index = int(raw_index) if raw_index is not None else None
        except ValueError:
            index = None
        if index is None:
            raise LightBurnError("a layer has no readable index")
        layers[index] = Layer(
            index=index,
            name=_value(el, "name") or f"C{index:02d}",
            layer_type=el.get("type", "Unknown"),
            power=_number(el, "maxPower", problems, True),
            frequency_hz=_number(el, "frequency", problems, True),
            speed=_number(el, "speed", problems, True),
            pulse_width=_number(el, "QPulseWidth", problems, False),
            line_interval=_number(el, "interval", problems, False),
            unreadable=problems,
        )

    for shape in root.iter("Shape"):
        raw = shape.get("CutIndex")
        try:
            idx = int(raw) if raw is not None else None
        except ValueError:
            idx = None
        layer = layers.get(idx) if idx is not None else None
        region = _region(shape)
        if layer is not None and region is not None:
            layer.regions.append(region)

    notes_el = root.find("Notes")
    notes = (notes_el.get("Notes") or "") if notes_el is not None else ""
    return Project(root.get("AppVersion"), root.get("DeviceName"), sorted(layers.values(), key=lambda l: l.index), notes)


def parse_file(path: str) -> Project:
    with open(path, "rb") as fh:
        return parse_bytes(fh.read())


def compare_with_profile(layer: Layer, pulse_width: float, line_interval: float, tol: float = 1e-9) -> list[str]:
    """DEC-022: differences between a layer's pulse width / line interval and the profile constants.

    Returns human-readable differences; an empty list means comparable. A value the file does not
    record is not a difference (the profile constant is then the only source).
    """
    diffs: list[str] = []
    if layer.pulse_width is not None and abs(layer.pulse_width - pulse_width) > tol:
        diffs.append(f"pulse width {layer.pulse_width:g} in file, {pulse_width:g} in profile")
    if layer.line_interval is not None and abs(layer.line_interval - line_interval) > tol:
        diffs.append(f"line interval {layer.line_interval:g} in file, {line_interval:g} in profile")
    return diffs
