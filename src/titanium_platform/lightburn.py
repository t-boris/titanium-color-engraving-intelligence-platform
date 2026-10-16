"""Reader for LightBurn project files (.lbrn / .lbrn2).

Both are XML. The structure used here was observed in a real LightBurn 2.0 .lbrn2 file:

* ``<CutSetting type="Scan">`` / ``<CutSetting_Img type="Image">`` hold one layer each, with
  ``<index>``, ``<name>``, ``<maxPower>`` (percent), ``<speed>`` (mm/s), ``<frequency>`` (Hz),
  ``<QPulseWidth>``, ``<interval>`` (mm), ``<numPasses>``, ``<globalRepeat>``, ``<bidir>``,
  ``<crossHatch>``, ``<angle>`` and ``<anglePerPass>`` as ``Value`` attributes.
* ``<Shape Type=... CutIndex=...>`` elements reference a layer through ``CutIndex``.
* A ``Path`` shape lists vertices (``V<x> <y>`` with optional Bezier handles ``c0x/c0y`` and ``c1x/c1y``) and
  primitives (``L<a> <b>`` line, ``B<a> <b>`` cubic Bezier from the out-handle ``c0`` of ``a`` to the in-handle
  ``c1`` of ``b``). Consecutive primitives form a sub-path; one path may hold several loops, nested ones are holes.

* A ``SubLayer`` inside a layer is a further pass with its own settings; every nested setting is kept in
  ``source_settings``. A ``Group`` lists its shapes under ``Children``; a shape's own XForm is applied first, then that
  of every group above it. An ``Ellipse`` has ``Rx``/``Ry``; a ``Text`` with a ``BackupPath`` child is read as that path.
  Shape types that are not read (a ``Text`` without outline, ...) are counted per layer in ``unsupported`` and
  reported, never dropped silently (REQ-025). ``Ellipse`` follows the public description of the format
  (lbrn2-to-svg); the ``BackupPath`` layout was checked on LightBurn 1.7 files.

The file does not record focus or material batch. A missing pass-count tag means LightBurn's default of one pass.
Unreadable layer parameters are reported, never replaced by guesses (REQ-015).
"""
from __future__ import annotations

import base64
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

_HANDLE_TAG = re.compile(r"(c0x|c0y|c1x|c1y)")
_PRIMITIVE = re.compile(r"([LB])(\d+) (\d+)")
_BITMAP_NOT_A_SETTING = ("Type", "CutIndex", "CutOrder", "W", "H", "Data", "File", "SourceHash")
FLATNESS_MM = 0.01   # a flattened Bezier deviates from its curve by less than this (REQ-023)


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
    # Outline in project mm. Rect/bitmap: the four corners. Path: one loop (or open polyline) with its Bezier
    # edges flattened to within FLATNESS_MM; loops nested inside it are listed in ``holes``.
    polygon: list[tuple[float, float]] = field(default_factory=list)
    closed: bool = False
    holes: list[list[tuple[float, float]]] = field(default_factory=list)   # loops inside ``polygon`` that stay unfilled
    # Image objects only: the embedded picture (PNG bytes, not serialised), its nominal size, the transform of its
    # centre-origin frame to project mm and its processing settings.
    bitmap: dict | None = None

    def as_dict(self) -> dict:
        out = {"kind": self.kind, "x": self.x, "y": self.y, "width": self.width, "height": self.height,
               "polygon": [list(p) for p in self.polygon], "closed": self.closed}
        if self.holes:
            out["holes"] = [[list(p) for p in hole] for hole in self.holes]
        return out


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
    passes: int | None = 1
    global_passes: int | None = 1
    bidirectional: bool | None = True
    cross_hatch: bool | None = False
    scan_angle: float | None = 0.0
    angle_increment: float | None = 0.0
    source_settings: dict = field(default_factory=dict)
    regions: list[Region] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    unsupported: dict = field(default_factory=dict)      # shape type -> how many objects of it are not read

    @property
    def readable(self) -> bool:
        return not self.unreadable

    def image_summary(self) -> dict | None:
        """How an image layer engraves its picture; None for any other layer. Read from LightBurn 1.7 files."""
        if self.layer_type != "Image":
            return None
        settings = self.source_settings

        def raw(tag):
            value = settings.get(tag)
            return value.get("Value") if isinstance(value, dict) else value

        def number(tag):
            try:
                return float(raw(tag))
            except (TypeError, ValueError):
                return None

        def flag(tag):
            value = raw(tag)
            return None if value is None else str(value).strip().lower() in ("1", "true", "yes")

        sub = settings.get("SubLayer")
        mode = raw("ditherMode")
        return {"dither": mode, "kind": "depth" if mode == "3dslice" else "tonal", "dpi": number("dpi"),
                "dot_width_mm": number("dotWidth"), "dot_correction": flag("useDotCorrection"),
                "cleanup_pass": flag("cleanupPass"), "passes": number("numPasses"), "line_interval_mm": number("interval"),
                "sub_layers": 0 if sub is None else len(sub) if isinstance(sub, list) else 1,
                "processing": settings.get("bitmaps", [])}

    @property
    def frequency_khz(self) -> float | None:
        return None if self.frequency_hz is None else self.frequency_hz / 1000.0

    def as_dict(self) -> dict:
        return {
            "index": self.index, "name": self.name, "type": self.layer_type,
            "power": self.power, "frequency_khz": self.frequency_khz, "speed": self.speed,
            "pulse_width": self.pulse_width, "line_interval": self.line_interval, "passes": self.passes,
            "lightburn_settings": {"global_passes": self.global_passes, "bidirectional": self.bidirectional,
                                   "cross_hatch": self.cross_hatch, "scan_angle": self.scan_angle,
                                   "angle_increment": self.angle_increment},
            # Preserve every setting tag from the source file, including controls this version does not
            # yet interpret (for example wobble/perforation). The original .lbrn2 remains attached too.
            "source_settings": self.source_settings,
            "readable": self.readable, "unreadable": list(self.unreadable),
            "regions": [r.as_dict() for r in self.regions],
            **({"unsupported": dict(self.unsupported)} if self.unsupported else {}),
        }


@dataclass
class Project:
    app_version: str | None
    device_name: str | None
    layers: list[Layer]
    notes: str = ""
    mirror_x: bool | None = None
    mirror_y: bool | None = None

    @property
    def identifier(self) -> str | None:
        """Experiment/plan identifier written by this system as ``TCE1:<id>`` in the project notes."""
        m = re.search(r"TCE1:([A-Za-z0-9_-]+)", self.notes or "")
        return m.group(1) if m else None

    def layer(self, index: int) -> Layer | None:
        return next((l for l in self.layers if l.index == index), None)


def normalize_saved_orientation(project: Project, *, mirror_x: bool, mirror_y: bool) -> list[str]:
    """Map LightBurn's saved shape coordinates back to the generated plan's axes.

    LightBurn may rewrite MirrorY when it saves an opened project and reflect
    every XForm at the same time. Its canvas stays visually unchanged, but the
    file coordinates no longer match the marker positions stored in the plan.
    The cleaning rectangle is the invariant work-area boundary, including a
    translation the operator made in LightBurn.
    """
    flip_x = project.mirror_x is not None and project.mirror_x != mirror_x
    flip_y = project.mirror_y is not None and project.mirror_y != mirror_y
    if not (flip_x or flip_y):
        return []
    regions = [region for layer in project.layers for region in layer.regions]
    if not regions:
        return []
    clean = next((region for layer in project.layers
                  if layer.name.startswith("CLEAN-CROSSHATCH-") for region in layer.regions), None)
    boundary = [clean] if clean is not None else regions
    x0 = min(region.x for region in boundary)
    y0 = min(region.y for region in boundary)
    x1 = max(region.x + region.width for region in boundary)
    y1 = max(region.y + region.height for region in boundary)
    for region in regions:
        region.polygon = [((x0 + x1 - x) if flip_x else x,
                           (y0 + y1 - y) if flip_y else y)
                          for x, y in region.polygon]
        xs, ys = zip(*region.polygon)
        region.x, region.y = min(xs), min(ys)
        region.width, region.height = max(xs) - region.x, max(ys) - region.y
    return [axis for axis, flipped in (("X", flip_x), ("Y", flip_y)) if flipped]


EXECUTION_ORDER_TAGS = ("priority",)


def recipe_settings(settings: dict | None) -> dict:
    """The settings of a layer that belong to its engraving recipe.

    The order in which LightBurn runs the layers is a property of the job, not of one layer: the same recipe in
    another file with another priority is the same recipe (DEC-051). Everything else is kept.
    """
    return {tag: value for tag, value in (settings or {}).items() if tag not in EXECUTION_ORDER_TAGS}


def _node(el: ET.Element):
    """A setting element as data: ``Value`` attributes as before, nested elements (a ``SubLayer``) recursively."""
    if len(el):
        out = dict(el.attrib)
        out.update(_settings(el))
        return out
    return dict(el.attrib) if el.attrib else (el.text or "")


def _settings(el: ET.Element, skip: tuple[str, ...] = ()) -> dict:
    out: dict = {}
    for child in el:
        if child.tag in skip:
            continue
        value = _node(child)
        if child.tag in out:           # several sub-layers: keep all of them, in file order
            previous = out[child.tag]
            out[child.tag] = (previous if isinstance(previous, list) else [previous]) + [value]
        else:
            out[child.tag] = value
    return out


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


def _flag(el: ET.Element, tag: str, default: bool) -> bool:
    raw = _value(el, tag)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes")


def _xform(shape: ET.Element) -> tuple[float, float, float, float, float, float]:
    text = (shape.findtext("XForm") or "1 0 0 1 0 0").split()
    try:
        a, b, c, d, e, f = (float(t) for t in text[:6])
    except ValueError as exc:
        raise LightBurnError(f"invalid XForm {text!r}") from exc
    return a, b, c, d, e, f


_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _compose(parent, local):
    """The transform that applies ``local`` first and ``parent`` after it (both ``a b c d e f``)."""
    pa, pb, pc, pd, pe, pf = parent
    la, lb, lc, ld, le, lf = local
    return (pa * la + pc * lb, pb * la + pd * lb, pa * lc + pc * ld, pb * lc + pd * ld,
            pa * le + pc * lf + pe, pb * le + pd * lf + pf)


def _shapes(container: ET.Element, parent=_IDENTITY):
    """Every drawable shape with the transform of the groups above it; a group passes its own transform on to its children."""
    for shape in container.findall("Shape"):
        if shape.get("Type") == "Group":
            children = shape.find("Children")
            if children is not None:
                yield from _shapes(children, _compose(parent, _xform(shape)))
        else:
            yield shape, parent


def _apply(m, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def _box(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _vertices(text: str) -> list[dict]:
    """``V<x> <y>`` with optional ``c0x/c0y`` (out handle) and ``c1x/c1y`` (in handle); ``c0x1`` means no handle."""
    out = []
    for chunk in text.split("V")[1:]:
        parts = _HANDLE_TAG.split(chunk)
        xy = parts[0].split()
        vertex = {"p": (float(xy[0]), float(xy[1])), "c0": None, "c1": None}
        values = dict(zip(parts[1::2], parts[2::2]))
        for handle in ("c0", "c1"):
            if handle + "x" in values and handle + "y" in values:
                vertex[handle] = (float(values[handle + "x"]), float(values[handle + "y"]))
        out.append(vertex)
    return out


def _flatten_bezier(p0, p1, p2, p3) -> list[tuple[float, float]]:
    """Points after ``p0`` of the cubic Bezier, spaced so that the polyline stays within FLATNESS_MM of the curve.

    |B''| <= 6*max(|p0-2p1+p2|, |p1-2p2+p3|), and a uniform polyline of n pieces deviates by at most |B''|/(8 n^2).
    """
    a = math.hypot(p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1])
    b = math.hypot(p1[0] - 2 * p2[0] + p3[0], p1[1] - 2 * p2[1] + p3[1])
    n = max(1, min(64, math.ceil(math.sqrt(6 * max(a, b) / (8 * FLATNESS_MM)))))
    points = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        points.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                       u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return points


def _path_loops(shape: ET.Element, m) -> list[tuple[list[tuple[float, float]], bool]]:
    """Every sub-path of a Path shape as (points in project mm, closed). Edges chain into one sub-path."""
    try:
        verts = _vertices(shape.findtext("VertList") or "")
    except (ValueError, IndexError):
        return []
    if not verts:
        return []
    for v in verts:       # the XForm goes first so that flattening is measured in project millimetres
        v["p"] = _apply(m, *v["p"])
        for handle in ("c0", "c1"):
            if v[handle] is not None:
                v[handle] = _apply(m, *v[handle])
    edges = [(k, int(a), int(b)) for k, a, b in _PRIMITIVE.findall(shape.findtext("PrimList") or "")]
    edges = [e for e in edges if e[1] < len(verts) and e[2] < len(verts)]
    if not edges:   # vertices without topology: one polyline through them, closed only by a repeated endpoint
        points = [v["p"] for v in verts]
        closed = len(points) >= 3 and math.dist(points[0], points[-1]) < 1e-6
        return [(points[:-1] if closed else points, closed)] if len(points) >= 2 else []
    chains, current = [], []
    for edge in edges:
        if current and edge[1] != current[-1][2]:
            chains.append(current)
            current = []
        current.append(edge)
    chains.append(current)
    loops = []
    for chain in chains:
        points = [verts[chain[0][1]]["p"]]
        for kind, a, b in chain:
            va, vb = verts[a], verts[b]
            if kind == "B":
                points += _flatten_bezier(va["p"], va["c0"] or va["p"], vb["c1"] or vb["p"], vb["p"])
            else:
                points.append(vb["p"])
        closed = chain[-1][2] == chain[0][1] and len(points) >= 4
        if not closed and len(points) >= 4 and math.dist(points[0], points[-1]) < 1e-6:
            closed = True       # an explicit repeated endpoint closes the outline too
        if closed:
            points = points[:-1]
        loops.append((points, closed))
    return loops


def _signed_area(points) -> float:
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1])) / 2


def _inside(point, polygon, box) -> bool:
    x, y = point
    if not (box[0] <= x <= box[0] + box[2] and box[1] <= y <= box[1] + box[3]):
        return False
    hit = False
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def _path_regions(shape: ET.Element, m) -> list[Region]:
    """One Region per open polyline and per outer loop; loops nested in a loop are its holes (even-odd nesting)."""
    loops = _path_loops(shape, m)
    closed = [points for points, is_closed in loops if is_closed]
    boxes = [_box(points) for points in closed]
    areas = [abs(_signed_area(points)) for points in closed]
    parents = []     # indices of the loops that contain loop i, largest first
    for i, points in enumerate(closed):
        parents.append(sorted((j for j in range(len(closed)) if j != i and areas[j] > areas[i] and
                               _inside(points[0], closed[j], boxes[j])), key=lambda j: -areas[j]))
    regions, outer_region = [], {}
    for i, points in enumerate(closed):
        if len(parents[i]) % 2 == 0:
            x, y, w, h = boxes[i]
            outer_region[i] = Region("path", x, y, w, h, polygon=points, closed=True)
            regions.append(outer_region[i])
    for i, points in enumerate(closed):
        if len(parents[i]) % 2 == 1:
            owner = parents[i][-1]
            if owner in outer_region:
                outer_region[owner].holes.append(points)
    for points, is_closed in loops:
        if not is_closed:
            x, y, w, h = _box(points)
            regions.append(Region("path", x, y, w, h, polygon=points, closed=False))
    return regions


def _regions(shape: ET.Element, parent=_IDENTITY) -> list[Region]:
    kind = shape.get("Type", "")
    m = _compose(parent, _xform(shape))
    if kind in ("Rect", "Bitmap"):
        try:
            w, h = float(shape.get("W", "nan")), float(shape.get("H", "nan"))
        except ValueError:
            return []
        if w != w or h != h:
            return []
        corners = [_apply(m, sx * w / 2, sy * h / 2) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        x, y, bw, bh = _box(corners)
        region = Region(kind.lower(), x, y, bw, bh, polygon=corners, closed=True)
        if kind == "Bitmap":
            try:
                png = base64.b64decode(shape.get("Data") or "", validate=False) or None
            except ValueError:
                png = None
            region.bitmap = {"png": png, "file": shape.get("File") or "", "w": w, "h": h, "matrix": m}
        return [region]
    if kind == "Path":
        return _path_regions(shape, m)
    if kind == "Ellipse":
        try:
            rx, ry = float(shape.get("Rx", "nan")), float(shape.get("Ry", "nan"))
        except ValueError:
            return []
        if not (math.isfinite(rx) and math.isfinite(ry)) or rx <= 0 or ry <= 0:
            return []
        scale = max(math.hypot(m[0], m[1]), math.hypot(m[2], m[3]), 1e-9) * max(rx, ry)
        pieces = max(24, min(720, math.ceil(math.pi / math.acos(max(0.0, 1 - FLATNESS_MM / scale))))) if scale > FLATNESS_MM else 24
        outline = [_apply(m, rx * math.cos(2 * math.pi * i / pieces), ry * math.sin(2 * math.pi * i / pieces)) for i in range(pieces)]
        x, y, w, h = _box(outline)
        return [Region("path", x, y, w, h, polygon=outline, closed=True)]
    if kind == "Text":
        # LightBurn keeps the converted outline of a text object in a ``BackupPath`` child (``HasBackupPath="1"``);
        # without it the file holds only the font and the string, and the object has no outline to measure.
        # Its own XForm equals the text's (checked on files of LightBurn 1.7), so it is not applied on top of the text's.
        backup = shape.find("BackupPath")
        if backup is not None:
            return _path_regions(backup, _compose(parent, _xform(backup)))
    return []


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
        passes = _number(el, "numPasses", problems, False)
        if passes is None:
            passes = _number(el, "passes", problems, False)
        if passes is not None and (int(passes) != passes or passes < 1):
            problems.append(f"numPasses: expected a positive integer, got {passes:g}")
        global_passes = _number(el, "globalRepeat", problems, False)
        if global_passes is not None and (int(global_passes) != global_passes or global_passes < 1):
            problems.append(f"globalRepeat: expected a positive integer, got {global_passes:g}")
        layers[index] = Layer(
            index=index,
            name=_value(el, "name") or f"C{index:02d}",
            layer_type=el.get("type", "Unknown"),
            power=_number(el, "maxPower", problems, True),
            frequency_hz=_number(el, "frequency", problems, True),
            speed=_number(el, "speed", problems, True),
            pulse_width=_number(el, "QPulseWidth", problems, False),
            line_interval=_number(el, "interval", problems, False),
            passes=1 if passes is None else int(passes),
            global_passes=1 if global_passes is None else int(global_passes),
            bidirectional=_flag(el, "bidir", True), cross_hatch=_flag(el, "crossHatch", False),
            scan_angle=_number(el, "angle", problems, False) or 0.0,
            angle_increment=_number(el, "anglePerPass", problems, False) or 0.0,
            source_settings=_settings(el, skip=("index", "name")),
            unreadable=problems,
        )

    bitmaps: dict[int, list[dict]] = {}
    for shape, parent in _shapes(root):
        raw = shape.get("CutIndex")
        try:
            idx = int(raw) if raw is not None else None
        except ValueError:
            idx = None
        layer = layers.get(idx) if idx is not None else None
        if layer is None:
            continue
        found = _regions(shape, parent)
        layer.regions.extend(found)
        kind = shape.get("Type", "")
        if not found and kind not in ("Rect", "Bitmap", "Path"):
            layer.unsupported[kind] = layer.unsupported.get(kind, 0) + 1
        if kind == "Bitmap":     # image processing settings of an image object are part of its layer's recipe
            attrs = {k: v for k, v in shape.attrib.items() if k not in _BITMAP_NOT_A_SETTING}
            if attrs not in bitmaps.setdefault(layer.index, []):
                bitmaps[layer.index].append(attrs)
    for index, items in bitmaps.items():
        layers[index].source_settings["bitmaps"] = items
    pictures = {r.bitmap["file"]: r.bitmap["png"] for layer in layers.values() for r in layer.regions
                if r.bitmap and r.bitmap["png"] and r.bitmap["file"]}
    for layer in layers.values():           # an image used on several layers is stored once, with the first object
        for region in layer.regions:
            if region.bitmap and not region.bitmap["png"]:
                region.bitmap["png"] = pictures.get(region.bitmap["file"])

    notes_el = root.find("Notes")
    notes = (notes_el.get("Notes") or "") if notes_el is not None else ""
    def mirror_flag(name: str) -> bool | None:
        raw = root.get(name)
        return None if raw is None else raw.strip().lower() in ("1", "true", "yes")

    return Project(root.get("AppVersion"), root.get("DeviceName"), sorted(layers.values(), key=lambda l: l.index),
                   notes, mirror_flag("MirrorX"), mirror_flag("MirrorY"))


def parse_file(path: str) -> Project:
    with open(path, "rb") as fh:
        return parse_bytes(fh.read())


def compare_with_profile(layer: Layer, pulse_width: float, line_interval: float, tol: float = 1e-9) -> list[str]:
    """Deprecated compatibility helper; process settings belong to each layer now.

    Returns human-readable differences; an empty list means comparable. A value the file does not
    record is not a difference (the profile constant is then the only source).
    """
    diffs: list[str] = []
    if layer.pulse_width is not None and abs(layer.pulse_width - pulse_width) > tol:
        diffs.append(f"pulse width {layer.pulse_width:g} in file, {pulse_width:g} in profile")
    if layer.line_interval is not None and abs(layer.line_interval - line_interval) > tol:
        diffs.append(f"line interval {layer.line_interval:g} in file, {line_interval:g} in profile")
    return diffs
