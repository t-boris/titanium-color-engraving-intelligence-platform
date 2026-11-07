"""The library of shapes, frames and icons of a titanium business card (feature-2, S1).

Every item is configurable (:data:`SHAPES`, :data:`FRAMES`, :data:`ICONS`: a label and the list of its parameters with their ranges) and
becomes shapely geometry in millimetres by :func:`geometry`:

* y points down, the geometry is centred on (0, 0) and unrotated; the work rotates it and puts it where the element stands;
* it fills the element's width x height box, the stroke included: the outer edge of a stroked outline touches the edge of the box and
  never crosses it. An icon is a square pictogram (the shorter side of the box) in the middle of the box;
* a filled shape ignores the stroke width; an unfilled shape, a frame and an icon are drawn with the line width ``stroke_mm``, which
  stays the same in mm however large the element is;
* curves are flattened to at most :data:`FLAT_MM` of chord error and the result never has more than :data:`MAX_VERTICES` vertices.

An icon is drawn on a 24 x 24 design grid: its centre-lines lie inside the live area 2..22, are scaled to the box and are given the line
width, so the pictogram fills the box up to the half of the line width on every side.

:func:`checked` validates the parameters of one item, :func:`default_size` gives the size a new element starts with, :func:`listing`
describes the whole library for a picker (with a path of every item for its thumbnail).
"""
from __future__ import annotations

import copy
import functools
import math
import numbers
from dataclasses import dataclass

import shapely
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box as shapely_box
from shapely.ops import unary_union
from shapely.validation import make_valid

from . import setup as su

GROUPS = ("shape", "frame", "icon")
FLAT_MM = 0.01                  # how far a flattened curve may stray from the true curve
MAX_VERTICES = 2500             # the most vertices one geometry has
MIN_SIZE_MM = 0.2               # the smallest and the largest side of an element
MAX_SIZE_MM = 500.0
MAX_DASHES = 480                # the most dashes one dashed frame has
MITRE = 5.0                     # mitre limit of the offsets of outlines
LIVE = 20.0                     # the live area of the icon grid is 2..22 (20 units); the grid is 24 units
THUMB = 24.0                    # the box of a thumbnail path
THUMB_FIT = 22.0                # the largest side of a drawing in it
MIN_AREA = 1e-9                 # mm2: smaller pieces are numerical dust


# -- the parameters ------------------------------------------------------------------------------------------------------------------
def _number(name: str, label: str, low: float, high: float, default: float, unit: str = "mm") -> dict:
    return {"name": name, "label": label, "type": "number", "min": float(low), "max": float(high), "default": float(default), "unit": unit}


def _whole(name: str, label: str, low: int, high: int, default: int) -> dict:
    return {"name": name, "label": label, "type": "int", "min": int(low), "max": int(high), "default": int(default), "unit": ""}


def _flag(name: str, label: str, default: bool = False) -> dict:
    return {"name": name, "label": label, "type": "bool", "min": None, "max": None, "default": default, "unit": ""}


def _item(label: str, *params: dict) -> dict:
    return {"label": label, "params": [dict(p) for p in params]}


FILLED = _flag("filled", "Filled")
STROKE = _number("stroke_mm", "Line width", 0.05, 3.0, 0.3)

SHAPES = {
    "rectangle": _item("Rectangle", FILLED, STROKE),
    "rounded_rectangle": _item("Rounded rectangle", _number("corner_mm", "Corner radius", 0, 30, 3), FILLED, STROKE),
    "ellipse": _item("Ellipse", FILLED, STROKE),
    "triangle": _item("Triangle", FILLED, STROKE),
    "diamond": _item("Diamond", FILLED, STROKE),
    "polygon": _item("Polygon", _whole("sides", "Sides", 3, 12, 6), FILLED, STROKE),
    "star": _item("Star", _whole("points", "Points", 3, 12, 5), _number("inner_pct", "Inner radius", 15, 90, 40, "%"), FILLED, STROKE),
    "line": _item("Line", STROKE),
    "arrow": _item("Arrow", FILLED, STROKE),
}
FRAMES = {
    "single": _item("Single line", STROKE),
    "double": _item("Double line", _number("gap_mm", "Gap between the lines", 0.1, 5, 0.6), STROKE),
    "rounded": _item("Rounded corners", _number("corner_mm", "Corner radius", 0, 30, 4), STROKE),
    "chamfered": _item("Chamfered corners", _number("corner_mm", "Corner cut", 0, 20, 3), STROKE),
    "notched": _item("Notched corners", _number("corner_mm", "Notch radius", 0, 20, 3), STROKE),
    "dashed": _item("Dashed", _number("dash_mm", "Dash length", 0.5, 20, 3), _number("gap_mm", "Gap between the dashes", 0.3, 20, 1.5), STROKE),
}
ICON_LABELS = {
    "phone": "Phone", "mail": "Mail", "globe": "Globe", "pin": "Location pin", "clock": "Clock", "star": "Star", "heart": "Heart",
    "check": "Check mark", "cross": "Cross", "arrow_right": "Arrow", "home": "House", "user": "Person", "briefcase": "Briefcase",
    "camera": "Camera", "leaf": "Leaf", "sun": "Sun", "moon": "Moon", "key": "Key", "lock": "Lock", "bolt": "Lightning bolt", "book": "Book",
    "cup": "Cup", "wrench": "Wrench", "bell": "Bell", "gear": "Gear", "tree": "Tree", "anchor": "Anchor",
}
ICONS = {name: _item(label, FILLED, STROKE) for name, label in ICON_LABELS.items()}

_GROUP = {"shape": SHAPES, "frame": FRAMES, "icon": ICONS}
_SIZES = {"shape": {"triangle": (16.0, 14.0), "diamond": (16.0, 14.0), "polygon": (14.0, 14.0), "star": (14.0, 14.0), "arrow": (20.0, 10.0),
                    "line": (20.0, 0.3)},
          "frame": {}, "icon": {}}
_SIZE = {"shape": (20.0, 12.0), "frame": (80.0, 49.0), "icon": (8.0, 8.0)}
_ARTICLE = {"shape": "a shape", "frame": "a frame", "icon": "an icon"}


def _article(group: str) -> str:
    return _ARTICLE[group]


def _lookup(group, name) -> dict:
    if group not in _GROUP:
        raise su.ValidationError(f"the library has no group {group!r}; its groups are {', '.join(GROUPS)}")
    item = _GROUP[group].get(name) if isinstance(name, str) else None
    if item is None:
        raise su.ValidationError(f"there is no {group} named {name!r} in the library")
    return item


def _out_of_range(group: str, spec: dict) -> su.ValidationError:
    unit = f" {spec['unit']}" if spec["unit"] else ""
    what = "a whole number" if spec["type"] == "int" else "a number"
    return su.ValidationError(f"the setting {spec['label'].lower()!r} of {_article(group)} must be {what} from {spec['min']:g} to {spec['max']:g}{unit}")


def _value(group: str, spec: dict, value):
    """One parameter checked against its spec (a bool is never a number); ValidationError names the parameter."""
    if spec["type"] == "bool":
        if not isinstance(value, bool):
            raise su.ValidationError(f"the setting {spec['label'].lower()!r} of {_article(group)} must be true or false")
        return value
    if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value):
        raise _out_of_range(group, spec)
    number = float(value)
    if spec["type"] == "int":
        if number != math.floor(number):
            raise _out_of_range(group, spec)
        number = int(number)
    else:
        number = round(number, 4)
    if not spec["min"] <= number <= spec["max"]:
        raise _out_of_range(group, spec)
    return number


def checked(group: str, name: str, params: dict | None = None) -> dict:
    """The parameters of one item with every one present (missing ones take the item's defaults) and in range; a parameter outside its range,
    of the wrong type (a bool is not a number) or not belonging to the item is refused with a ValidationError naming it."""
    item = _lookup(group, name)
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise su.ValidationError(f"the settings of {_article(group)} must be an object")
    specs = {p["name"]: p for p in item["params"]}
    unknown = sorted(str(k) for k in params if k not in specs)
    if unknown:
        raise su.ValidationError(f"the {group} {name!r} has no setting {unknown[0]!r}")
    return {key: _value(group, spec, params.get(key, spec["default"])) for key, spec in specs.items()}


def default_size(group: str, name: str) -> dict:
    """The width and height (mm) a new element of this item starts with."""
    _lookup(group, name)
    width, height = _SIZES[group].get(name, _SIZE[group])
    return {"width": width, "height": height}


def _side(value, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value) or not MIN_SIZE_MM <= value <= MAX_SIZE_MM:
        raise su.ValidationError(f"the {what} of an element must be a number from {MIN_SIZE_MM:g} to {MAX_SIZE_MM:g} mm")
    return round(float(value), 4)


# -- curves and cleaning -------------------------------------------------------------------------------------------------------------
def _step(radius: float) -> float:
    """The widest angle (radians) one chord of a circle of this radius may span with a chord error of FLAT_MM."""
    return math.pi / 2 if radius <= FLAT_MM else 2 * math.acos(1 - FLAT_MM / radius)


def _segments(radius: float, sweep_rad: float) -> int:
    return max(1, math.ceil(abs(sweep_rad) / _step(radius)))


def _quad(radius: float) -> int:
    """Segments per quarter of a circle for ``buffer(quad_segs=...)``."""
    return min(256, _segments(radius, math.pi / 2))


def _arc(cx: float, cy: float, r: float, a0: float, a1: float, scale: float = 1.0) -> list[tuple[float, float]]:
    """Points of the arc about (cx, cy) from a0 to a1 degrees (0 is +x, 90 is down), both ends included. ``scale`` is how many mm a unit of
    the coordinates is (the arc is flattened to FLAT_MM in mm)."""
    n = _segments(r * scale, math.radians(a1 - a0))
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
            for i in range(n + 1)]


def _dedupe(points, closed: bool = True):
    """The points without repeats of the same point one after another (and, for a ring, without the last one repeating the first)."""
    out = []
    for p in points:
        if not out or abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9:
            out.append(tuple(p))
    if closed and len(out) > 1 and abs(out[0][0] - out[-1][0]) <= 1e-9 and abs(out[0][1] - out[-1][1]) <= 1e-9:
        out.pop()
    return out


def _polygons(geom):
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield geom
    elif hasattr(geom, "geoms"):
        for part in geom.geoms:
            yield from _polygons(part)


def _polygonal(geom):
    """The areas of a geometry as a valid Polygon or MultiPolygon (empty when nothing is left)."""
    if not geom.is_valid:
        geom = make_valid(geom)
    parts = [p for p in _polygons(geom) if p.area > MIN_AREA]
    if not parts:
        return Polygon()
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def vertices(geom) -> int:
    return int(shapely.get_num_coordinates(geom))


def _capped(geom):
    """The geometry with fewer than MAX_VERTICES vertices: curves flattened finer than needed at a very large size are thinned (the error
    stays far below what a laser draws)."""
    tolerance = FLAT_MM / 2
    while vertices(geom) > MAX_VERTICES and tolerance < 5:
        geom = _polygonal(geom.simplify(tolerance, preserve_topology=True))
        tolerance *= 1.6
    return geom


def _finish(geom, group: str, name: str):
    geom = _polygonal(geom)
    if not geom.is_valid:
        geom = _polygonal(geom.buffer(0))
    geom = _capped(geom)
    if geom.is_empty or vertices(geom) > MAX_VERTICES:
        raise su.ValidationError(f"the {group} {name!r} cannot be drawn at this size with these settings")
    return geom


# -- solids: the area a shape or a frame fills ---------------------------------------------------------------------------------------
def _rect(w: float, h: float) -> Polygon:
    return shapely_box(-w / 2, -h / 2, w / 2, h / 2)


def _rounded(w: float, h: float, radius: float) -> Polygon:
    r = min(max(radius, 0.0), min(w, h) / 2)
    if r < 1e-6:
        return _rect(w, h)
    a, b = w / 2 - r, h / 2 - r
    points = (_arc(a, -b, r, -90, 0) + _arc(a, b, r, 0, 90) + _arc(-a, b, r, 90, 180) + _arc(-a, -b, r, 180, 270))
    return Polygon(_dedupe(points))


def _chamfered(w: float, h: float, cut: float) -> Polygon:
    c = min(max(cut, 0.0), min(w, h) / 2)
    if c < 1e-6:
        return _rect(w, h)
    x, y = w / 2, h / 2
    return Polygon(_dedupe([(-x + c, -y), (x - c, -y), (x, -y + c), (x, y - c), (x - c, y), (-x + c, y), (-x, y - c), (-x, -y + c)]))


def _notched(w: float, h: float, radius: float) -> Polygon:
    c = min(max(radius, 0.0), min(w, h) / 2)
    if c < 1e-6:
        return _rect(w, h)
    x, y = w / 2, h / 2
    points = (_arc(x, -y, c, 180, 90) + _arc(x, y, c, 270, 180) + _arc(-x, y, c, 0, -90) + _arc(-x, -y, c, 90, 0))
    return Polygon(_dedupe(points))


def _ellipse(w: float, h: float) -> Polygon:
    return affinity.scale(Point(0, 0).buffer(1.0, quad_segs=_quad(max(w, h) / 2)), w / 2, h / 2, origin=(0, 0))


def _fit(points, w: float, h: float) -> Polygon:
    """The polygon through the points stretched to fill the box w x h exactly."""
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return Polygon([((x - x0) / (x1 - x0) * w - w / 2, (y - y0) / (y1 - y0) * h - h / 2) for x, y in points])


def _regular(sides: int, w: float, h: float) -> Polygon:
    return _fit([(math.cos(math.radians(-90 + 360 * i / sides)), math.sin(math.radians(-90 + 360 * i / sides))) for i in range(sides)], w, h)


def _star(points: int, inner_pct: float, w: float, h: float) -> Polygon:
    ratio, out = inner_pct / 100.0, []
    for i in range(points):
        for radius, turn in ((1.0, 0.0), (ratio, 0.5)):
            angle = math.radians(-90 + 360 * (i + turn) / points)
            out.append((radius * math.cos(angle), radius * math.sin(angle)))
    return _fit(out, w, h)


def _arrow(w: float, h: float) -> Polygon:
    shaft, head = 0.4 * h, min(0.8 * h, 0.5 * w)
    x = w / 2 - head
    return Polygon([(-w / 2, -shaft / 2), (x, -shaft / 2), (x, -h / 2), (w / 2, 0), (x, h / 2), (x, shaft / 2), (-w / 2, shaft / 2)])


def _inset(solid, distance: float):
    return solid.buffer(-distance, join_style="mitre", mitre_limit=MITRE)


def _ring(solid, stroke: float):
    """The outline of an area, ``stroke`` wide and inside it (the whole area when the stroke is wider than it can hold)."""
    return solid.difference(_inset(solid, stroke))


# -- shapes --------------------------------------------------------------------------------------------------------------------------
def _shape(kind: str, w: float, h: float, p: dict):
    stroke = p["stroke_mm"]
    if kind == "line":
        thickness = min(stroke, h)
        return shapely_box(-w / 2, -thickness / 2, w / 2, thickness / 2)
    if kind == "rectangle":
        solid = _rect(w, h)
    elif kind == "rounded_rectangle":
        solid = _rounded(w, h, p["corner_mm"])
    elif kind == "ellipse":
        solid = _ellipse(w, h)
    elif kind == "triangle":
        solid = Polygon([(0, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)])
    elif kind == "diamond":
        solid = Polygon([(0, -h / 2), (w / 2, 0), (0, h / 2), (-w / 2, 0)])
    elif kind == "polygon":
        solid = _regular(p["sides"], w, h)
    elif kind == "star":
        solid = _star(p["points"], p["inner_pct"], w, h)
    else:
        solid = _arrow(w, h)
    return solid if p["filled"] else _ring(solid, stroke)


# -- frames --------------------------------------------------------------------------------------------------------------------------
def _side_dashes(a, b, arm: float, dash: float, gap: float) -> list[LineString]:
    """The dashes between the two half dashes that sit in the corners at the ends of the side a-b: whole dashes with the gaps spread
    evenly (never narrower than ``gap``)."""
    length = math.dist(a, b)
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    count = max(0, math.floor((length - dash - gap) / (dash + gap) + 1e-9))
    spread = (length - dash - count * dash) / (count + 1)
    out = []
    for i in range(count):
        start = arm + spread + i * (dash + spread)
        out.append(LineString([(a[0] + ux * start, a[1] + uy * start), (a[0] + ux * (start + dash), a[1] + uy * (start + dash))]))
    return out


def _dashed(w: float, h: float, stroke: float, dash: float, gap: float):
    half = stroke / 2
    x0, y0, x1, y1 = -w / 2 + half, -h / 2 + half, w / 2 - half, h / 2 - half
    if x1 - x0 < dash or y1 - y0 < dash:
        return _ring(_rect(w, h), stroke)                    # too small for dashes: a plain frame
    arm = dash / 2
    pieces = [LineString([(cx + sx * arm, cy), (cx, cy), (cx, cy + sy * arm)]) for sx, sy, cx, cy in
              ((1, 1, x0, y0), (-1, 1, x1, y0), (-1, -1, x1, y1), (1, -1, x0, y1))]
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        pieces += _side_dashes(a, b, arm, dash, gap)
    if len(pieces) > MAX_DASHES:
        raise su.ValidationError("the dashes of this frame would be too many; make them longer or the frame smaller")
    return unary_union([piece.buffer(half, cap_style="flat", join_style="mitre", mitre_limit=2.0) for piece in pieces])


def _frame(kind: str, w: float, h: float, p: dict):
    stroke = p["stroke_mm"]
    if kind == "single":
        return _ring(_rect(w, h), stroke)
    if kind == "double":
        outer = _rect(w, h)
        inner = _inset(outer, stroke + p["gap_mm"])
        return _ring(outer, stroke).union(_ring(inner, stroke)) if not inner.is_empty else _ring(outer, stroke)
    if kind == "rounded":
        return _ring(_rounded(w, h, p["corner_mm"]), stroke)
    if kind == "chamfered":
        return _ring(_chamfered(w, h, p["corner_mm"]), stroke)
    if kind == "notched":
        return _ring(_notched(w, h, p["corner_mm"]), stroke)
    return _dashed(w, h, stroke, p["dash_mm"], p["gap_mm"])


# -- icons: pictograms on a 24 x 24 grid ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class _Part:
    """One primitive of a pictogram, in grid units. ``kind`` is a path (``data`` is a tuple of ("M", x, y), ("L", x, y) and
    ("A", cx, cy, r, from_deg, to_deg) steps), a circle (``data`` is (cx, cy, r)) or a dot (a solid disc). ``detail`` is False for what is
    always drawn, True for a detail that is drawn in an outline icon and cut out of the solid parts in a filled icon, and "cut" for a
    detail that is only cut out of a filled icon."""
    kind: str
    data: tuple
    closed: bool = False
    detail: object = False


def _line(*points, detail=False) -> _Part:
    return _Part("path", (("M", *points[0]), *(("L", *p) for p in points[1:])), False, detail)


def _poly(*points, detail=False) -> _Part:
    return _Part("path", (("M", *points[0]), *(("L", *p) for p in points[1:])), True, detail)


def _path(*steps, closed=False, detail=False) -> _Part:
    return _Part("path", tuple(steps), closed, detail)


def _circle(cx, cy, r, detail=False) -> _Part:
    return _Part("circle", (cx, cy, r), True, detail)


def _dot(cx, cy, r, detail=False) -> _Part:
    return _Part("dot", (cx, cy, r), False, detail)


def _rrect(x0, y0, x1, y1, r, detail=False) -> _Part:
    return _path(("M", x0 + r, y0), ("L", x1 - r, y0), ("A", x1 - r, y0 + r, r, 270, 360), ("L", x1, y1 - r), ("A", x1 - r, y1 - r, r, 0, 90),
                 ("L", x0 + r, y1), ("A", x0 + r, y1 - r, r, 90, 180), ("L", x0, y0 + r), ("A", x0 + r, y0 + r, r, 180, 270), closed=True,
                 detail=detail)


def _pol(cx, cy, r, deg):
    return cx + r * math.cos(math.radians(deg)), cy + r * math.sin(math.radians(deg))


def _angle(cx, cy, point) -> float:
    return math.degrees(math.atan2(point[1] - cy, point[0] - cx))


def _sweep(cx, cy, start, end, through_deg) -> tuple[float, float]:
    """The angles (from, to) of the arc about (cx, cy) from one point to another that passes the direction ``through_deg``."""
    a0, a1 = _angle(cx, cy, start), _angle(cx, cy, end)
    forward, reach = (a1 - a0) % 360, (through_deg - a0) % 360
    return (a0, a0 + forward) if reach <= forward else (a0, a0 - (360 - forward))


def _rotate_steps(steps, deg, cx, cy):
    out = []
    for step in steps:
        if step[0] == "A":
            x, y = _rotated(step[1], step[2], deg, cx, cy)
            out.append(("A", x, y, step[3], step[4] + deg, step[5] + deg))
        else:
            out.append((step[0], *_rotated(step[1], step[2], deg, cx, cy)))
    return tuple(out)


def _rotated(x, y, deg, cx, cy):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c


def _icon_phone():
    return [_rrect(7, 2, 17, 22, 2.2), _line((10, 5.2), (14, 5.2), detail=True), _dot(12, 18.6, 1.0, detail=True)]


def _icon_mail():
    return [_rrect(2, 5, 22, 19, 1.5), _line((2.8, 6.2), (12, 13.2), (21.2, 6.2), detail=True)]


def _icon_globe():
    r, c = 14.5, 10.5                                         # meridians: arcs through the poles bulging to x = 8 and x = 16
    a = math.degrees(math.asin(10 / r))
    return [_circle(12, 12, 10), _arc_part(12 - c, 12, r, -a, a, True), _arc_part(12 + c, 12, r, 180 - a, 180 + a, True),
            _line((2, 12), (22, 12), detail=True)]


def _arc_part(cx, cy, r, a0, a1, detail=False) -> _Part:
    return _path(("A", cx, cy, r, a0, a1), detail=detail)


def _icon_pin():
    cx, cy, r, tip = 12.0, 9.0, 7.0, 22.0
    a = math.degrees(math.acos(r / (tip - cy)))
    return [_path(("M", 12, tip), ("L", *_pol(cx, cy, r, 90 + a)), ("A", cx, cy, r, 90 + a, 450 - a), closed=True), _circle(12, 9, 2.6, detail=True)]


def _icon_clock():
    return [_circle(12, 12, 10), _line((12, 6), (12, 12), (16.5, 14.5), detail=True)]


def _icon_star():
    cx, cy, r = 12.0, 12.5, 10.5
    pts = [_pol(cx, cy, r * (1 if i % 2 == 0 else 0.4), -90 + 36 * i) for i in range(10)]
    return [_poly(*pts)]


def _icon_heart():
    lx, ly, r, tip = 7.5, 8.0, 5.5, (12.0, 21.5)
    dy = math.sqrt(r * r - (12 - lx) ** 2)
    cleft = math.degrees(math.atan2(-dy, 12 - lx))
    t = math.degrees(math.atan2(tip[1] - ly, tip[0] - lx)) + math.degrees(math.acos(r / math.hypot(tip[0] - lx, tip[1] - ly)))
    return [_path(("M", 12, ly - dy), ("A", lx, ly, r, cleft, t - 360), ("L", *tip), ("A", 24 - lx, ly, r, 180 - t, 180 - cleft - 360), closed=True)]


def _icon_check():
    return [_line((2, 12.5), (8.5, 19), (22, 5))]


def _icon_cross():
    return [_line((2, 2), (22, 22)), _line((22, 2), (2, 22))]


def _icon_arrow_right():
    return [_line((2, 12), (22, 12)), _line((14, 4), (22, 12), (14, 20))]


def _icon_home():
    return [_poly((2, 11.5), (12, 2.5), (22, 11.5), (19.5, 11.5), (19.5, 21.5), (4.5, 21.5), (4.5, 11.5)),
            _line((9.5, 21.5), (9.5, 15), (14.5, 15), (14.5, 21.5), detail=True)]


def _icon_user():
    return [_circle(12, 6.5, 4.5), _path(("M", 2, 22), ("A", 12, 22, 10, 180, 360), closed=True)]


def _icon_briefcase():
    return [_rrect(2, 8, 22, 21, 2), _line((8.5, 8), (8.5, 4), (15.5, 4), (15.5, 8)), _line((2, 14), (22, 14), detail=True)]


def _icon_camera():
    return [_rrect(2, 7, 22, 20, 2), _line((7.5, 7), (9.2, 4), (14.8, 4), (16.5, 7)), _circle(12, 13.5, 3.8, detail=True)]


def _icon_leaf():
    ax, ay, bx, by, r = 2.0, 22.0, 22.0, 2.0, 22.0
    chord = math.hypot(bx - ax, by - ay)
    off = math.sqrt(r * r - (chord / 2) ** 2)
    nx, ny = (by - ay) / chord * -1, (bx - ax) / chord                  # unit normal of the chord (towards the lower right)
    c1, c2 = (12 + nx * off, 12 + ny * off), (12 - nx * off, 12 - ny * off)
    toward = math.degrees(math.atan2(ny, nx))
    a0, a1 = _sweep(*c2, (ax, ay), (bx, by), toward)
    b0, b1 = _sweep(*c1, (bx, by), (ax, ay), toward + 180)
    return [_path(("M", ax, ay), ("A", *c2, r, a0, a1), ("A", *c1, r, b0, b1), closed=True), _line((2, 22), (13, 11), detail=True)]


def _icon_sun():
    return [_circle(12, 12, 4.5)] + [_line(_pol(12, 12, 7.4, 45 * i), _pol(12, 12, 10, 45 * i)) for i in range(8)]


def _icon_moon():
    c1, r1, c2, r2 = (12.0, 12.0), 10.0, (17.5, 8.0), 8.5
    d = math.dist(c1, c2)
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(r1 * r1 - a * a)
    ex, ey = (c2[0] - c1[0]) / d, (c2[1] - c1[1]) / d
    mx, my = c1[0] + a * ex, c1[1] + a * ey
    p, q = (mx + h * ey, my - h * ex), (mx - h * ey, my + h * ex)
    if p[1] > q[1]:
        p, q = q, p                                                       # p is the upper tip
    a0, a1 = _sweep(*c1, p, q, 180)
    b0, b1 = _sweep(*c2, q, p, _angle(*c2, c1))
    return [_path(("M", *p), ("A", *c1, r1, a0, a1), ("A", *c2, r2, b0, b1), closed=True)]


def _icon_key():
    return [_circle(6.5, 12, 4.5), _dot(6.5, 12, 1.8, detail="cut"), _line((11, 12), (22, 12)), _line((17.5, 12), (17.5, 16.5)),
            _line((21.5, 12), (21.5, 15.5))]


def _icon_lock():
    return [_rrect(4.5, 11, 19.5, 22, 2), _path(("M", 7.5, 11), ("L", 7.5, 7), ("A", 12, 7, 4.5, 180, 360), ("L", 16.5, 11)),
            _dot(12, 16, 1.4, detail=True), _line((12, 16), (12, 19.2), detail=True)]


def _icon_bolt():
    return [_poly((14, 2), (5, 13.5), (11.2, 13.5), (10, 22), (19, 9.5), (12.8, 9.5))]


def _icon_book():
    return [_poly((2, 4), (11.5, 6), (11.5, 21), (2, 19)), _poly((22, 4), (12.5, 6), (12.5, 21), (22, 19))]


def _icon_cup():
    return [_path(("M", 3, 8), ("L", 17, 8), ("L", 17, 15), ("A", 13, 15, 4, 0, 90), ("L", 7, 19), ("A", 7, 15, 4, 90, 180), closed=True),
            _path(("M", 17, 9.5), ("L", 18, 9.5), ("A", 18, 13, 3.5, 270, 450), ("L", 17, 16.5)),
            _line((7, 2.5), (7, 5.5)), _line((11, 2.5), (11, 5.5)), _line((2, 21.5), (22, 21.5))]


def _icon_wrench():
    hx, cy, r, sw = 5.23, 12.0, 5.2, 1.9                                   # head circle, slot and handle half width, drawn along x
    s = math.sqrt(r * r - sw * sw)
    a = math.degrees(math.asin(sw / r))
    steps = (("M", hx - s, cy - sw), ("L", hx + 1.0, cy - sw), ("L", hx + 1.0, cy + sw), ("L", hx - s, cy + sw), ("A", hx, cy, r, 180 - a, a),
             ("L", 24.23, cy + sw), ("L", 24.23, cy - sw), ("L", hx + s, cy - sw), ("A", hx, cy, r, -a, -180 + a))
    return [_path(*_rotate_steps(steps, 135, 12, 12), closed=True)]


def _icon_bell():
    return [_path(("M", 2, 18.5), ("L", 5, 10), ("A", 12, 10, 7, 180, 360), ("L", 22, 18.5), closed=True), _arc_part(12, 18.5, 3, 0, 180)]


def _icon_gear():
    pts = []
    for i in range(8):
        for r, off in ((7.6, -17), (10.0, -9), (10.0, 9), (7.6, 17)):
            pts.append(_pol(12, 12, r, 45 * i + off))
    return [_poly(*pts), _circle(12, 12, 3, detail=True)]


def _icon_tree():
    return [_poly((12, 2), (18, 9), (15.5, 9), (21, 16), (13.5, 16), (13.5, 22), (10.5, 22), (10.5, 16), (3, 16), (8.5, 9), (6, 9))]


def _icon_anchor():
    return [_circle(12, 4.5, 2.5), _line((12, 7), (12, 22)), _line((8, 10.5), (16, 10.5)), _arc_part(12, 13, 9, 0, 180)]


_ICON_PARTS = {name: globals()[f"_icon_{name}"]() for name in ICON_LABELS}


def _flat(steps, k: float) -> list[tuple[float, float]]:
    """The points of a path in grid units, its arcs flattened for a scale of k mm per unit."""
    out = []
    for step in steps:
        if step[0] == "A":
            _, cx, cy, r, a0, a1 = step
            out += _arc(cx, cy, r, a0, a1, k)
        else:
            out.append((step[1], step[2]))
    return _dedupe(out, closed=False)


def _stroked(points, closed: bool, half: float, area: bool):
    """A path as the laser draws it: a line twice ``half`` wide (round ends and joins), or, for a closed path that is an area, the area
    widened by ``half``."""
    if closed and len(_dedupe(points)) >= 3:
        if area:
            return Polygon(_dedupe(points)).buffer(half, quad_segs=_quad(half))
        points = points + [points[0]]
    return LineString(points).buffer(half, quad_segs=_quad(half))


def _part(part: _Part, k: float, half: float, solid: bool):
    """One primitive as geometry in mm: its line, or, when ``solid``, the area it closes (a cut-out detail is always taken as that)."""
    mm = lambda x, y: ((x - 12) * k, (y - 12) * k)      # noqa: E731
    if part.kind == "dot":
        cx, cy, r = part.data
        radius = max(r * k, half)
        return Point(mm(cx, cy)).buffer(radius, quad_segs=_quad(radius))
    if part.kind == "circle":
        cx, cy, r = part.data
        c, radius = Point(mm(cx, cy)), r * k
        outer = c.buffer(radius + half, quad_segs=_quad(radius + half))
        return outer if solid or radius <= half else outer.difference(c.buffer(radius - half, quad_segs=_quad(radius - half)))
    return _stroked([mm(x, y) for x, y in _flat(part.data, k)], part.closed, half, solid)


def _icon(name: str, w: float, h: float, p: dict):
    parts = _ICON_PARTS[name]
    stroke = min(p["stroke_mm"], 0.5 * min(w, h))
    half, k, filled = stroke / 2, (min(w, h) - stroke) / LIVE, p["filled"]
    drawn, carved = [], []
    for part in parts:
        if part.detail and filled:
            carved.append(_part(part, k, half, True))
        elif part.detail != "cut":
            drawn.append(_part(part, k, half, filled))
    geom = unary_union(drawn)
    return geom.difference(unary_union(carved)) if carved else geom


# -- building ------------------------------------------------------------------------------------------------------------------------
def _make(group: str, name: str, w: float, h: float, p: dict):
    if group == "shape":
        return _shape(name, w, h, p)
    if group == "frame":
        return _frame(name, w, h, p)
    return _icon(name, w, h, p)


@functools.lru_cache(maxsize=512)
def _built(group: str, name: str, w: float, h: float, items: tuple):
    return _finish(_make(group, name, w, h, dict(items)), group, name)


def geometry(group: str, name: str, width_mm: float, height_mm: float, params: dict | None = None):
    """The item as a valid Polygon or MultiPolygon in mm (y down, centred on (0, 0), unrotated) filling the box ``width_mm`` x ``height_mm``.

    The box may have sides from MIN_SIZE_MM to MAX_SIZE_MM; the parameters are checked by :func:`checked`. A ``line`` is as thick as its
    ``stroke_mm`` but never thicker than the box is high. The result is cached and must not be changed (shapely geometries are immutable)."""
    w, h = _side(width_mm, "width"), _side(height_mm, "height")
    return _built(group, name, w, h, tuple(sorted(checked(group, name, params).items())))


# -- the listing for a picker --------------------------------------------------------------------------------------------------------
_PREVIEW_MIN = {"stroke_mm": 1.5, "gap_mm": 1.4, "dash_mm": 2.6, "corner_mm": 3.2}      # in thumbnail units (the box is 24 wide)


def _number_text(value: float) -> str:
    return f"{round(value, 2):g}"


def preview_path(geom) -> str:
    """SVG path data (even-odd) of a geometry scaled to fit the 24 x 24 thumbnail box, its bounding box centred at (12, 12)."""
    x0, y0, x1, y1 = geom.bounds
    scale = THUMB_FIT / max(x1 - x0, y1 - y0, 1e-9)
    ox, oy = THUMB / 2 - (x0 + x1) / 2 * scale, THUMB / 2 - (y0 + y1) / 2 * scale
    parts = []
    for poly in _polygons(geom):
        for ring in (poly.exterior, *poly.interiors):
            pts = ring.coords[:-1]
            if len(pts) >= 3:
                parts.append("M" + " L".join(f"{_number_text(x * scale + ox)} {_number_text(y * scale + oy)}" for x, y in pts) + " Z")
    return " ".join(parts)


def _preview(group: str, name: str) -> str:
    """The thumbnail of an item: its default parameters and proportions at thumbnail scale, the line widths, gaps and corners kept wide
    enough to be seen there (a 0.3 mm line on an 80 mm frame would be a hairline)."""
    size = default_size(group, name)
    scale = THUMB_FIT / max(size["width"], size["height"])
    p = {spec["name"]: spec["default"] for spec in _lookup(group, name)["params"]}
    for key in p:
        if key.endswith("_mm"):
            p[key] = max(p[key] * scale, _PREVIEW_MIN.get(key, 0.0))
    w, h = size["width"] * scale, size["height"] * scale
    if name == "line" and group == "shape":
        h = p["stroke_mm"]
    return preview_path(_finish(_make(group, name, w, h, p), group, name))


@functools.lru_cache(maxsize=1)
def _listing() -> dict:
    return {group: [{"name": name, "label": item["label"], "params": copy.deepcopy(item["params"]), "default_size": default_size(group, name),
                     "preview": _preview(group, name)} for name, item in _GROUP[group].items()] for group in GROUPS}


def listing() -> dict:
    """The whole library for a picker, JSON-serialisable: ``{"shape": [...], "frame": [...], "icon": [...]}``, every item with its
    ``name``, ``label``, ``params`` (the specs), ``default_size`` and ``preview`` (SVG path data of its thumbnail in a 24 x 24 box)."""
    return copy.deepcopy(_listing())
