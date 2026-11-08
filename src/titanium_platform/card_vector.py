"""Vector artwork on a business card (feature-3, REQ-003..005; Q-001 A, Q-002 C; DEC-001..003): an SVG or Adobe Illustrator file becomes a group of
independently editable PARTS.

A reader (:mod:`card_vector_svg` for SVG, :mod:`card_vector_ai` for the PDF-compatible content of an Illustrator file) turns the file into
shapes in millimetres, each with its design colour. This module

* picks the reader (:func:`read`) and refuses what no reader can take, saying why;
* prepares the shapes for the card (:func:`prepare`): a white page background is left out, specks too small to engrave are dropped and, when a
  side could not hold so many elements, neighbouring parts of one colour are merged (and the operator is told). Nothing else is merged: a part
  is a path of the file, so that one leg of the dog can be moved, coloured or deleted on its own;
* keeps the parts in a file of the workshop (:func:`store`, :func:`load`): ``vector-<id>.json`` in ``files/``, immutable, named by its NAME so that a
  moved or restored workshop still finds it. The undo history of a card holds only the small payload of an element, never the rings;
* builds the geometry of one part (:func:`part_geometry`) in the part's own frame, and suggests, for a design colour, the measured engraving colours
  of the card's own laser, lens and material (:func:`matches`). A design colour is what the file draws; an engraving colour is what the laser
  can make. The first never changes the second: the editor only suggests (:data:`CLOSE_DELTA_E`) and the operator chooses.

The editor shows and exports exactly this geometry. Path nodes are not editable (DEC-001): a part can be selected, coloured, copied, moved,
resized, rotated, ordered, grouped and deleted like any other element.
"""
from __future__ import annotations

import gzip
import io
import json
import math
import re
import threading
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from . import card_vector_geometry as vg, color, setup as su
from .card_vector_geometry import Parsed, Shape

VERSION = 1
FILE_PATTERN = re.compile(r"^vector-[0-9a-f]{12}\.json$")
MAX_FILE_BYTES = 60 * 1024 * 1024
MAX_UNZIPPED_BYTES = 120 * 1024 * 1024
MIN_PART_MM = 0.02                  # a part whose longer side is shorter than this (at the size it is placed) cannot be engraved: left out
MARGIN_MM = 2.0                     # the artwork keeps this far from the card's edge when it is fitted
SMALL_MM, LARGE_MM, TARGET_MM = 15.0, 40.0, 30.0       # a drawing of a size between these keeps its size; any other is fitted to TARGET_MM first
BACKGROUND_SHARE = 0.85             # a white shape covering this much of the drawing's box is the page, not a part
MAX_RING_POINTS = 600_000           # of one artwork; beyond it the outlines are simplified
DECIMALS = 4
CLOSE_DELTA_E = 25.0                # an engraving colour within this ΔE*ab of a design colour is a close match
SUGGESTIONS = 3
KEEP_ARTWORKS = 4
GENERATED_NAME = re.compile(r"^(path|rect|circle|ellipse|polygon|polyline|line|g|use|shape|layer|xmlid|svg|compound|group)[-_ ]?\d*$", re.I)

_lock = threading.Lock()
_artworks: OrderedDict[str, dict] = OrderedDict()


# -- reading ----------------------------------------------------------------------------------------------------------------------------
def _is_svg(head: bytes) -> bool:
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    return text.startswith((b"<?xml", b"<svg", b"<!DOCTYPE svg", b"<!--", b"<!doctype svg")) and b"<svg" in head


def read(data: bytes, file_name: str = "") -> Parsed:
    """The shapes of an SVG, an SVGZ or an Illustrator (PDF-compatible) file. A file nobody can read raises a ValidationError that says what to do."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise su.ValidationError("the artwork file is empty")
    data = bytes(data)
    if data[:2] == b"\x1f\x8b":                                           # SVGZ
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as handle:
                data = handle.read(MAX_UNZIPPED_BYTES + 1)
        except (OSError, EOFError, ValueError):
            raise su.ValidationError("this compressed file could not be read; export the artwork again as SVG")
        if len(data) > MAX_UNZIPPED_BYTES:
            raise su.ValidationError("this compressed file is too large to import")
    head = data[:4096]
    if b"%PDF-" in data[:1024]:
        from . import card_vector_ai
        return card_vector_ai.parse(data)
    if _is_svg(head) or (b"<svg" in head and file_name.lower().endswith((".svg", ".svgz"))):
        from . import card_vector_svg
        return card_vector_svg.parse(data)
    if data.startswith(b"%!PS-Adobe") or head.lstrip().startswith(b"%!PS"):
        raise su.ValidationError("This Illustrator file has no PDF-compatible content, so it cannot be imported. Open it in Illustrator and save it again "
                                 "with “Create PDF Compatible File” ticked, or export it as SVG.")
    raise su.ValidationError("this is not an SVG or Adobe Illustrator file: choose a file ending in .svg or .ai")


# -- preparing --------------------------------------------------------------------------------------------------------------------------
def _bounds(shapes: Sequence[Shape]) -> tuple[float, float, float, float]:
    boxes = [s.geometry.bounds for s in shapes if not s.geometry.is_empty]
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def _white(colour: str) -> bool:
    return all(channel >= 250 for channel in vg.rgb_of(colour))


def fit_factor(width: float, height: float, card: Mapping) -> float:
    """How much a drawing of ``width`` × ``height`` mm is scaled to be placed on a card: its own size when it is a plausible one for a card, else
    fitted to :data:`TARGET_MM`, and always inside the card with a margin."""
    width, height = max(width, 1e-6), max(height, 1e-6)
    longest = max(width, height)
    factor = 1.0 if SMALL_MM <= longest <= LARGE_MM else TARGET_MM / longest
    room_w, room_h = max(card["width"] - 2 * MARGIN_MM, 1.0), max(card["height"] - 2 * MARGIN_MM, 1.0)
    return min(factor, room_w / width, room_h / height)


def _union(geometries: list[BaseGeometry]) -> BaseGeometry:
    """The polygons covered by any of ``geometries``; a geometry the union refuses (self-crossing outlines of a hand-made file) is repaired first."""
    try:
        return vg.polygonal(shapely.union_all(geometries))
    except shapely.errors.GEOSException:
        return vg.polygonal(shapely.union_all([shapely.make_valid(g) for g in geometries]))


def _merged_runs(shapes: list[Shape]) -> list[Shape]:
    """Neighbouring shapes of one colour as one: painting them one after the other or as one gives the same picture. A run is united once, not shape by
    shape (a file of eight hundred pieces of one colour would take minutes)."""
    runs: list[list[Shape]] = []
    for shape in shapes:
        if runs and runs[-1][0].fill == shape.fill:
            runs[-1].append(shape)
        else:
            runs.append([shape])
    return [run[0] if len(run) == 1 else Shape(_union([s.geometry for s in run]), run[0].fill, run[0].name) for run in runs]


def _merged_colours(shapes: list[Shape]) -> list[Shape]:
    """All shapes of one colour as one, at the place of the first (the painting order of different colours is only kept approximately)."""
    order: dict[str, list[Shape]] = {}
    for shape in shapes:
        order.setdefault(shape.fill, []).append(shape)
    return [Shape(_union([s.geometry for s in group]), fill, group[0].name) for fill, group in order.items()]


def _polys(geometry: BaseGeometry) -> list[list[list[float]]]:
    """The polygons of a geometry as flat coordinate lists: the outline first, then its holes, each ring open and rounded."""
    out = []
    for polygon in vg._polygons(geometry):
        rings = []
        for ring in (polygon.exterior, *polygon.interiors):
            points = list(ring.coords)[:-1]
            if len(points) >= 3:
                rings.append([round(v, DECIMALS) for xy in points for v in xy])
        if rings:
            out.append(rings)
    return out


def prepare(parsed: Parsed, stem: str, card: Mapping, room: int) -> dict:
    """The artwork for a card of ``card`` mm (``{width, height}``) that has ``room`` free places on the side: parts in painting order with
    their boxes and rings in the drawing's own frame (millimetres, origin at the top-left of the drawing, y down), the factor that fits the
    drawing on the card, and what was left out or merged. Raises a ValidationError when nothing is left or the parts cannot be made to fit."""
    shapes = [s for s in parsed.shapes if s.geometry is not None and not s.geometry.is_empty]
    notes = list(parsed.notes)
    if not shapes:
        raise su.ValidationError("nothing to engrave was found in this file" + (": " + notes[0] if notes else ""))
    background = False
    x0, y0, x1, y1 = _bounds(shapes)
    box_area = max((x1 - x0) * (y1 - y0), 1e-9)
    for index, shape in enumerate(shapes):
        if _white(shape.fill) and shape.geometry.area >= BACKGROUND_SHARE * box_area and len(shapes) > 1:
            del shapes[index]
            background = True
            break
    if background:
        notes.append("A white background in the file was left out.")
        x0, y0, x1, y1 = _bounds(shapes)
    width, height = x1 - x0, y1 - y0
    factor = fit_factor(width, height, card)
    kept = [s for s in shapes if max(s.geometry.bounds[2] - s.geometry.bounds[0], s.geometry.bounds[3] - s.geometry.bounds[1]) * factor >= MIN_PART_MM]
    dropped = len(shapes) - len(kept)
    if dropped:
        notes.append(f"{dropped} detail{'s' if dropped != 1 else ''} smaller than {MIN_PART_MM:g} mm at this size could not be engraved and {'were' if dropped != 1 else 'was'} left out.")
    if not kept:
        raise su.ValidationError("every part of this file is too small to engrave at the size it would have on the card")
    merged = 0
    if len(kept) > room:
        before = len(kept)
        kept = _merged_runs(kept)
        if len(kept) > room:
            kept = _merged_colours(kept)
        merged = before - len(kept)
        if len(kept) > room:
            raise su.ValidationError(f"this drawing has {len(kept)} different colours and the side has room for {room} more elements: use fewer colours in the program that "
                                     "made the file, or make room by deleting elements of this side")
        notes.append(f"The drawing has {before} parts but the side has room for {room}: parts of the same colour were merged, {len(kept)} remain.")
    overlaps = _overlapping(kept)
    if overlaps:
        notes.append(f"{overlaps} part{'s' if overlaps != 1 else ''} of one colour lie{'' if overlaps != 1 else 's'} over a part of another colour: where parts overlap the laser engraves both.")
    points = sum(sum(len(r) // 2 for poly in _polys(s.geometry) for r in poly) for s in kept)
    tolerance = 0.0
    while points > MAX_RING_POINTS and tolerance < 0.5:
        tolerance = max(0.002, tolerance * 2)
        kept = [Shape(vg.polygonal(s.geometry.simplify(tolerance, preserve_topology=True)), s.fill, s.name) for s in kept]
        points = sum(sum(len(r) // 2 for poly in _polys(s.geometry) for r in poly) for s in kept)
    parts = []
    number = 0
    for shape in kept:
        geometry = vg.polygonal(affinity.translate(shape.geometry, -x0, -y0))
        if geometry.is_empty:
            continue
        number += 1
        gx0, gy0, gx1, gy1 = geometry.bounds
        name = shape.name if shape.name and not GENERATED_NAME.match(shape.name.strip()) else None
        parts.append({"fill": shape.fill, "name": (name or f"{stem} {number}")[:80], "box": [round(v, DECIMALS) for v in (gx0, gy0, gx1, gy1)], "polys": _polys(geometry)})
    if not parts:
        raise su.ValidationError("nothing to engrave was found in this file")
    colours = len({p["fill"] for p in parts})
    return {"version": VERSION, "name": stem[:80], "kind": parsed.kind, "width": round(width, DECIMALS), "height": round(height, DECIMALS), "parts": parts,
            "factor": factor, "notes": notes, "report": {"kind": parsed.kind, "parts": len(parts), "colours": colours, "merged": merged, "dropped": dropped,
                                                           "background": background, "notes": notes}}


def _overlapping(shapes: list[Shape]) -> int:
    """How many parts lie noticeably over a part of another colour (the laser would engrave both there)."""
    if len(shapes) < 2 or len(shapes) > 800:
        return 0
    tree = shapely.STRtree([s.geometry for s in shapes])
    found = 0
    for i, shape in enumerate(shapes):
        for j in tree.query(shape.geometry):
            if j > i and shapes[j].fill != shape.fill:
                small = min(shape.geometry.area, shapes[j].geometry.area)
                if small > 0 and shape.geometry.intersection(shapes[j].geometry).area > 0.05 * small:
                    found += 1
                    break
    return found


# -- the file of the parts --------------------------------------------------------------------------------------------------------------
def store(data_dir: Path, artwork: Mapping) -> str:
    """Write the parts of an artwork to ``files/`` and return the file's NAME (the payload of an element holds the name, not the path)."""
    name = f"vector-{uuid.uuid4().hex[:12]}.json"
    folder = Path(data_dir) / "files"
    folder.mkdir(parents=True, exist_ok=True)
    body = {k: artwork[k] for k in ("version", "name", "kind", "width", "height", "parts")}
    (folder / name).write_text(json.dumps(body, separators=(",", ":")), encoding="utf-8")
    return name


def path_of(data_dir: Path, name: str) -> Path:
    if not isinstance(name, str) or not FILE_PATTERN.match(name):
        raise su.ValidationError("a vector part needs the stored file of its artwork")
    return Path(data_dir) / "files" / name


def exists(data_dir: Path, name: str) -> bool:
    return path_of(data_dir, name).is_file()


def load(data_dir: Path, name: str) -> dict:
    """The stored artwork (cached while in use). Raises a ValidationError when its file is missing or damaged."""
    path = path_of(data_dir, name)
    key = str(path)
    with _lock:
        if key in _artworks:
            _artworks.move_to_end(key)
            return _artworks[key]
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(body, dict) or not isinstance(body.get("parts"), list):
            raise ValueError("not an artwork")
    except (OSError, ValueError) as error:
        raise su.ValidationError("The artwork file of this part is missing or damaged") from error
    with _lock:
        _artworks[key] = body
        _artworks.move_to_end(key)
        while len(_artworks) > KEEP_ARTWORKS:
            _artworks.popitem(last=False)
    return body


def part(artwork: Mapping, index) -> dict:
    parts = artwork["parts"]
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(parts):
        raise su.ValidationError("this part is not in its artwork file")
    return parts[index]


def part_geometry(item: Mapping, width_mm: float, height_mm: float) -> BaseGeometry:
    """One part of an artwork as a geometry centred on (0, 0), unrotated and stretched to ``width_mm`` × ``height_mm``."""
    x0, y0, x1, y1 = item["box"]
    polygons = []
    for rings in item["polys"]:
        shells = [[(r[i], r[i + 1]) for i in range(0, len(r), 2)] for r in rings]
        polygon = Polygon(shells[0], shells[1:])
        polygons.append(polygon if polygon.is_valid else shapely.make_valid(polygon))      # rounding the outlines to a tenth of a micron can make them touch themselves
    geometry = _union(polygons) if polygons else Polygon()
    if geometry.is_empty:
        return geometry
    sx, sy = width_mm / max(x1 - x0, 1e-9), height_mm / max(y1 - y0, 1e-9)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    return affinity.affine_transform(geometry, [sx, 0.0, 0.0, sy, -cx * sx, -cy * sy])


def fill_of(colour) -> str:
    """A design colour as ``#rrggbb`` (lowercase) from ``#rgb`` or ``#rrggbb`` in either case; anything else is refused."""
    if isinstance(colour, str):
        text = colour.strip().lower()
        if re.fullmatch(r"#[0-9a-f]{3}", text):
            text = "#" + "".join(ch * 2 for ch in text[1:])
        if vg.is_hex(text):
            return text
    raise su.ValidationError("a design colour is written like #c08040")


# -- engraving colours that go with a design colour ---------------------------------------------------------------------------------------
def _lab(colour: str) -> np.ndarray:
    return color.srgb8_to_lab(np.array(vg.rgb_of(colour), dtype=float))


def matches(colours: Sequence[str], items: Sequence[Mapping]) -> dict[str, dict]:
    """For each design colour the measured engraving colours (``items``: the colour items of :mod:`card_settings`) nearest to it by ΔE*ab, best
    first, and whether the best is close. ``items`` empty gives ``best`` None: nothing is measured to suggest."""
    measured = []
    for item in items:
        lab = (item.get("evidence") or {}).get("lab")
        swatch = (item.get("swatch") or {}).get("srgb")
        if lab is not None and swatch:
            measured.append((np.array(lab, dtype=float), item, swatch))
    out = {}
    for colour in colours:
        if not measured:
            out[colour] = {"best": None, "close": False, "alternatives": []}
            continue
        target = _lab(colour)
        ranked = sorted(((color.delta_e(target, lab), index) for index, (lab, _, _) in enumerate(measured)))
        rows = [{"choice_id": measured[i][1]["id"], "label": measured[i][1]["label"], "swatch": measured[i][2], "delta_e": round(d, 1)} for d, i in ranked[:SUGGESTIONS]]
        out[colour] = {"best": rows[0], "close": rows[0]["delta_e"] <= CLOSE_DELTA_E, "alternatives": rows[1:]}
    return out
