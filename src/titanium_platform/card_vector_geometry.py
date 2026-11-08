"""Geometry and colour helpers shared by the readers of vector files (feature-3: ``card_vector_svg``, ``card_vector_ai``).

A reader turns the paths of a file into :class:`Shape` objects: shapely geometry in MILLIMETRES, y pointing down, with one design
colour each. This module holds what both readers need and nothing that belongs to one format:

* flattening of Bezier curves and SVG arcs into polylines (:func:`cubic`, :func:`quadratic`, :func:`arc`);
* the fill rules: a list of closed rings becomes one region (:func:`region`, "evenodd" or "nonzero");
* strokes: a polyline becomes the area the pen covers (:func:`stroke`);
* colours: ``#rrggbb`` strings, alpha laid on white, grey and CMYK to sRGB (:func:`hex_colour`, :func:`on_white`, :func:`cmyk`).

Nothing here reads a file or touches the work: the functions are pure, and every geometry they return is valid and polygonal.
"""
from __future__ import annotations

import math
from typing import NamedTuple, Sequence

import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry

FLATNESS_MM = 0.01             # a curve is flattened until its polyline is this near it
MAX_SEGMENTS = 200             # of one curve
MIN_AREA_MM2 = 1e-6            # a region smaller than this is nothing
Point2 = tuple[float, float]


class Shape(NamedTuple):
    """One painted area of a file: its geometry in millimetres (y down), its design colour and a name when the file gives one."""
    geometry: BaseGeometry
    fill: str                  # "#rrggbb"
    name: str | None = None


class Parsed(NamedTuple):
    """What a reader found: the shapes in painting order (the first is at the bottom), what could not be carried over (each note a whole
    sentence for the operator) and the kind of file ("svg" or "ai")."""
    shapes: list[Shape]
    notes: list[str]
    kind: str


# -- curves -----------------------------------------------------------------------------------------------------------------------------
def _segments(length: float, flatness: float) -> int:
    return max(2, min(MAX_SEGMENTS, int(math.ceil(math.sqrt(max(length, 0.0) / (4.0 * flatness))))))


def cubic(p0: Point2, p1: Point2, p2: Point2, p3: Point2, flatness: float = FLATNESS_MM) -> list[Point2]:
    """The points of a cubic Bezier curve after its start (the end included), as a polyline within ``flatness`` of the curve."""
    length = math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)
    count = _segments(length, flatness)
    out = []
    for i in range(1, count + 1):
        t = i / count
        u = 1.0 - t
        a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def quadratic(p0: Point2, p1: Point2, p2: Point2, flatness: float = FLATNESS_MM) -> list[Point2]:
    """A quadratic Bezier curve as the cubic that draws it."""
    c1 = (p0[0] + 2.0 * (p1[0] - p0[0]) / 3.0, p0[1] + 2.0 * (p1[1] - p0[1]) / 3.0)
    c2 = (p2[0] + 2.0 * (p1[0] - p2[0]) / 3.0, p2[1] + 2.0 * (p1[1] - p2[1]) / 3.0)
    return cubic(p0, c1, c2, p2, flatness)


def arc(p0: Point2, rx: float, ry: float, rotation_deg: float, large: bool, sweep: bool, p1: Point2, flatness: float = FLATNESS_MM) -> list[Point2]:
    """An SVG elliptical arc from ``p0`` to ``p1`` (the endpoint form of the path data), as the points after ``p0``. A zero radius or an
    arc that starts where it ends is a straight line to ``p1`` (or nothing), as the SVG specification says. The sweep flag follows SVG:
    on a y-down plane it turns clockwise on the screen."""
    if p0 == p1:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx < 1e-12 or ry < 1e-12:
        return [p1]
    phi = math.radians(rotation_deg % 360.0)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2.0, (p0[1] - p1[1]) / 2.0
    x1, y1 = cos_p * dx + sin_p * dy, -sin_p * dx + cos_p * dy
    scale = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if scale > 1.0:                                      # the radii are too small to reach: enlarge them just enough
        root = math.sqrt(scale)
        rx, ry = rx * root, ry * root
    sign = -1.0 if large == sweep else 1.0
    numerator = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    denominator = rx * rx * y1 * y1 + ry * ry * x1 * x1
    factor = sign * math.sqrt(max(0.0, numerator / denominator)) if denominator > 0 else 0.0
    cx1, cy1 = factor * rx * y1 / ry, -factor * ry * x1 / rx
    cx = cos_p * cx1 - sin_p * cy1 + (p0[0] + p1[0]) / 2.0
    cy = sin_p * cx1 + cos_p * cy1 + (p0[1] + p1[1]) / 2.0

    def angle(ux: float, uy: float, vx: float, vy: float) -> float:
        value = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return value

    theta = angle(1.0, 0.0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    delta = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and delta > 0:
        delta -= 2.0 * math.pi
    elif sweep and delta < 0:
        delta += 2.0 * math.pi
    length = abs(delta) * max(rx, ry)
    count = max(2, min(MAX_SEGMENTS, int(math.ceil(math.sqrt(length / (4.0 * flatness))))))
    out = []
    for i in range(1, count + 1):
        t = theta + delta * i / count
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append((cos_p * x - sin_p * y + cx, sin_p * x + cos_p * y + cy))
    out[-1] = p1
    return out


# -- regions ----------------------------------------------------------------------------------------------------------------------------
def _polygons(geometry) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [p for g in geometry.geoms for p in _polygons(g)]
    return []


def polygonal(geometry) -> BaseGeometry:
    """Only the areas of a geometry (lines and points dropped), made valid, as a Polygon, a MultiPolygon or an empty Polygon."""
    if geometry is None or geometry.is_empty:
        return Polygon()
    if not geometry.is_valid:
        geometry = shapely.make_valid(geometry)
    found = [p for p in _polygons(geometry) if p.area >= MIN_AREA_MM2]
    if not found:
        return Polygon()
    return found[0] if len(found) == 1 else MultiPolygon(found)


def signed_area(ring: Sequence[Point2]) -> float:
    """The area of a ring, positive when it runs counter-clockwise on a y-up plane (so clockwise on the screen's y-down plane)."""
    total = 0.0
    for (ax, ay), (bx, by) in zip(ring, list(ring[1:]) + [ring[0]]):
        total += ax * by - bx * ay
    return total / 2.0


def _ring_polygon(ring: Sequence[Point2]) -> BaseGeometry:
    if len(ring) < 3:
        return Polygon()
    try:
        return polygonal(Polygon(ring))
    except (ValueError, shapely.errors.ShapelyError):
        return Polygon()


def _balanced(items: list[BaseGeometry], operation) -> BaseGeometry:
    """``operation`` applied pairwise as a tree: a long chain of symmetric differences would cost the square of its length."""
    items = [g for g in items if not g.is_empty]
    if not items:
        return Polygon()
    while len(items) > 1:
        items = [operation(items[i], items[i + 1]) if i + 1 < len(items) else items[i] for i in range(0, len(items), 2)]
    return items[0]


def region(rings: Sequence[Sequence[Point2]], rule: str = "nonzero") -> BaseGeometry:
    """The area a path fills: ``rings`` are its closed sub-paths (the closing segment is implied) and ``rule`` is "evenodd" or "nonzero".

    Even-odd is the exclusive-or of the rings. Non-zero is read from the rings' directions: those that run the way of the largest ring add
    to the area and the others take away what they enclose of it (and add what they enclose of the empty plane), which is what the winding
    number gives for the drawings that exist (outlines with holes, shapes overlapping one another)."""
    polygons = [(ring, _ring_polygon(ring)) for ring in rings]
    polygons = [(ring, poly) for ring, poly in polygons if not poly.is_empty]
    if not polygons:
        return Polygon()
    if rule == "evenodd":
        return polygonal(_balanced([poly for _, poly in polygons], lambda a, b: a.symmetric_difference(b)))
    largest = max(polygons, key=lambda item: abs(signed_area(item[0])))
    lead = signed_area(largest[0]) >= 0
    same = [poly for ring, poly in polygons if (signed_area(ring) >= 0) == lead]
    other = [poly for ring, poly in polygons if (signed_area(ring) >= 0) != lead]
    added = shapely.union_all(same) if same else Polygon()
    if not other:
        return polygonal(added)
    return polygonal(added.symmetric_difference(shapely.union_all(other)))


# -- strokes ----------------------------------------------------------------------------------------------------------------------------
CAPS = {"butt": "flat", "round": "round", "square": "square", "flat": "flat"}
JOINS = {"miter": "mitre", "mitre": "mitre", "round": "round", "bevel": "bevel"}


def stroke(points: Sequence[Point2], width: float, *, closed: bool = False, cap: str = "butt", join: str = "miter", miter_limit: float = 4.0) -> BaseGeometry:
    """The area covered by a pen of ``width`` drawn along a polyline (a closed one when ``closed``)."""
    if width <= 0 or len(points) < 2:
        return Polygon()
    cap_style, join_style = CAPS.get(cap, "flat"), JOINS.get(join, "mitre")
    try:
        if closed and len(points) >= 3:
            line = LineString(list(points) + [points[0]])
        elif len(points) == 2 and points[0] == points[1]:
            return polygonal(Point(points[0]).buffer(width / 2.0)) if cap == "round" else Polygon()
        else:
            line = LineString(points)
        return polygonal(line.buffer(width / 2.0, cap_style=cap_style, join_style=join_style, mitre_limit=max(1.0, miter_limit), quad_segs=8))
    except (ValueError, shapely.errors.ShapelyError):
        return Polygon()


# -- colours ----------------------------------------------------------------------------------------------------------------------------
def _byte(value: float) -> int:
    return max(0, min(255, int(round(value))))


def hex_colour(r: float, g: float, b: float, scale: float = 255.0) -> str:
    """``#rrggbb`` from three channels on a scale of 0..``scale`` (255 by default, 1.0 for the channels of a PDF)."""
    k = 255.0 / scale
    return "#%02x%02x%02x" % (_byte(r * k), _byte(g * k), _byte(b * k))


def rgb_of(colour: str) -> tuple[int, int, int]:
    """The channels (0..255) of a ``#rrggbb`` string."""
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def on_white(colour: str, alpha: float) -> str:
    """A colour drawn with opacity ``alpha`` (0..1) on white paper, as the opaque colour that looks like it."""
    alpha = max(0.0, min(1.0, alpha))
    if alpha >= 1.0:
        return colour
    return hex_colour(*(c * alpha + 255.0 * (1.0 - alpha) for c in rgb_of(colour)))


def cmyk(c: float, m: float, y: float, k: float) -> str:
    """sRGB of a CMYK colour (each 0..1) by the plain device formula: the same result in every program, no profile involved."""
    c, m, y, k = (max(0.0, min(1.0, v)) for v in (c, m, y, k))
    return hex_colour(255.0 * (1 - c) * (1 - k), 255.0 * (1 - m) * (1 - k), 255.0 * (1 - y) * (1 - k))


def grey(value: float) -> str:
    """``#rrggbb`` of a grey level 0..1."""
    return hex_colour(value, value, value, scale=1.0)


def is_hex(value) -> bool:
    return isinstance(value, str) and len(value) == 7 and value[0] == "#" and all(ch in "0123456789abcdef" for ch in value[1:])
