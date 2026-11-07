"""A graphic -> engravable vector geometry for a card (feature-2, REQ-002 imported / generated graphics, REQ-004 pencil treatment).

An imported or generated picture becomes shapely geometry in millimetres (:func:`geometry`): closed polygons with holes, centred on
(0, 0), y down, fitted inside the width x height box with the picture's aspect kept. The card editor draws and exports exactly this
geometry, so it is made clean:

* the dark areas of the graphic are the engraved areas (``invert`` swaps that); the grey level that separates them is Otsu's, or the
  operator's ``threshold``;
* the outline is not the staircase of the pixel mask: the tone field is enlarged with cubic interpolation, the mask's contour is moved
  onto the true threshold level of that field (one Newton step along the gradient: sub-pixel exact) and lightly smoothed along the
  outline before Douglas-Peucker (:data:`TOLERANCE_MM`);
* specks and pinholes smaller than ``min_feature_mm`` squared are dropped; the vertex count is capped at :data:`MAX_VERTICES` by
  coarsening the tolerance (and the smallest details with it) until it fits.

The pencil treatment (:func:`pencil_sketch`) redraws the tones as a pencil drawing before that same tracing: outlines on both sides of
every edge plus single-direction hatching whose strokes widen with darkness; paper stays white. It is made on a raster whose pixel is a
third of ``min_feature_mm`` so that every stroke is at least that wide at the box size. ``detail`` (how much fine texture is kept, how
fine the hatching is) and ``strength`` (how dark and dense the strokes are) change the picture visibly.

:func:`load` reads the bytes of an imported file (transparency is composited on white, the long side capped at :data:`WORK_PX`);
:func:`checked` validates the settings; :func:`cache_key` names a result for callers that cache it.
"""
from __future__ import annotations

import json
import math
import struct

import cv2
import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient

from . import setup as su

MAX_SIDE_PX = 8000             # a file larger than this on a side is refused ...
MAX_MEGAPIXELS = 40            # ... or in all
WORK_PX = 1600                 # the long side of a loaded picture
MAX_VERTICES = 6000            # of the geometry of one picture
TOLERANCE_MM = 0.02            # Douglas-Peucker tolerance
SMOOTH_PX = 1.5                # the outline is smoothed along its length by about one pixel of the picture ...
SMOOTH_MM = (0.03, 0.4)        # ... but by between these many mm (a staircase of hard pixel edges is gone, a corner is not blunted much)
UPSCALE_PX = 2000              # the tone field is enlarged to about this many pixels on its long side ...
MAX_UPSCALE = 8                # ... by at most this factor
BLUR_DIVISOR = 4               # detail finer than min_feature_mm / BLUR_DIVISOR is not a feature: the picture is blurred by that much
MAX_BLUR_PX = 6.0
PENCIL_MIN_STROKE_PX = 2.5     # a pencil raster pixel is min_feature_mm / this, so that the thinnest stroke is a feature wide
PENCIL_MAX_PX = 1800           # the pencil raster's long side stays between these
PENCIL_MIN_RASTER_PX = 128
PENCIL_LEVEL = 128             # the grey level of the pencil sketch below which it is engraved when the threshold is automatic
PENCIL_BLUR_MAX_PX = 3.5      # detail 0 smooths fine texture away with a Gaussian of this sigma (detail 100: none)
PENCIL_LINE_SCALE_PX = 2.0     # an edge is drawn where the tone changes by about 1/gain of its range within this many pixels
PENCIL_PERIOD_PX = (14.0, 7.0)  # hatching period at detail 0 / 100
PENCIL_HATCH_MIN_PX = 3.0      # the thinnest hatching stroke
PENCIL_HATCH_MAX_DUTY = (0.45, 0.85)   # the widest hatching stroke, as a share of the period, at strength 0 / 100

LABELS = {"threshold": "Threshold", "auto_threshold": "Automatic threshold", "invert": "Invert", "treatment": "Treatment",
          "detail": "Detail", "strength": "Strength", "min_feature_mm": "Smallest feature"}
IMAGE_PARAMS = [
    {"name": "auto_threshold", "label": LABELS["auto_threshold"], "type": "bool", "min": None, "max": None, "default": True, "unit": ""},
    {"name": "threshold", "label": LABELS["threshold"], "type": "int", "min": 0, "max": 255, "default": 128, "unit": "grey level"},
    {"name": "invert", "label": LABELS["invert"], "type": "bool", "min": None, "max": None, "default": False, "unit": ""},
    {"name": "treatment", "label": LABELS["treatment"], "type": "choice", "min": None, "max": None, "default": "none", "unit": "",
     "options": ["none", "pencil"], "option_labels": {"none": "As drawn", "pencil": "Pencil drawing"}},
    {"name": "detail", "label": LABELS["detail"], "type": "int", "min": 0, "max": 100, "default": 50, "unit": "%"},
    {"name": "strength", "label": LABELS["strength"], "type": "int", "min": 0, "max": 100, "default": 60, "unit": "%"},
    {"name": "min_feature_mm", "label": LABELS["min_feature_mm"], "type": "number", "min": 0.05, "max": 1.0, "default": 0.15, "unit": "mm"},
]
DEFAULTS = {spec["name"]: spec["default"] for spec in IMAGE_PARAMS}


# -- settings -------------------------------------------------------------------------------------------------------------------------
def _whole(value, spec: dict) -> int:
    ok = (not isinstance(value, bool) and isinstance(value, (int, float, np.integer, np.floating)) and math.isfinite(value)
          and value == int(value) and spec["min"] <= value <= spec["max"])
    if not ok:
        raise su.ValidationError(f"{spec['label']} must be a whole number from {spec['min']} to {spec['max']}.")
    return int(value)


def _number(value, spec: dict) -> float:
    ok = (not isinstance(value, bool) and isinstance(value, (int, float, np.integer, np.floating)) and math.isfinite(value)
          and spec["min"] <= value <= spec["max"])
    if not ok:
        raise su.ValidationError(f"{spec['label']} must be a number from {spec['min']} to {spec['max']} {spec['unit']}.")
    return round(float(value), 4)


def checked(params=None) -> dict:
    """The picture settings with every field present and in range (missing fields take :data:`DEFAULTS`).

    ``threshold`` of None means an automatic threshold. A ValidationError names the first field that is not valid.
    """
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise su.ValidationError("The picture settings must be an object.")
    specs = {spec["name"]: spec for spec in IMAGE_PARAMS}
    unknown = sorted(str(name) for name in set(params) - set(specs))
    if unknown:
        raise su.ValidationError(f"The picture has no setting {unknown[0]!r}.")
    given = dict(params)
    if "threshold" in given and given["threshold"] is None:
        del given["threshold"]
        given["auto_threshold"] = True
    out = {**DEFAULTS, **given}
    for name, spec in specs.items():
        value = out[name]
        if spec["type"] == "bool":
            if not isinstance(value, bool):
                raise su.ValidationError(f"{spec['label']} must be true or false.")
        elif spec["type"] == "int":
            out[name] = _whole(value, spec)
        elif spec["type"] == "number":
            out[name] = _number(value, spec)
        elif value not in spec["options"]:
            raise su.ValidationError(f"{spec['label']} must be one of {', '.join(spec['options'])}.")
    return out


def cache_key(data_stamp: str, params, width_mm: float, height_mm: float) -> str:
    """A stable name for the geometry of one picture: its stamp (hash, id or version), the validated settings and the box (0.1 mm)."""
    return json.dumps([str(data_stamp), checked(params), round(float(width_mm), 1), round(float(height_mm), 1)],
                      sort_keys=True, separators=(",", ":"))


# -- reading a file -------------------------------------------------------------------------------------------------------------------
def _bytes(data) -> bytes:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise su.ValidationError("The picture file could not be read.")
    data = bytes(data)
    if not data:
        raise su.ValidationError("The picture file is empty.")
    return data


def _unreadable() -> su.ValidationError:
    return su.ValidationError("The file is not a picture that can be read. Use a PNG, JPEG, GIF, BMP, TIFF or WebP file.")


def _jpeg_size(data: bytes):
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
        elif marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            i += 2
        elif 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return width, height
        else:
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None


def _webp_size(data: bytes):
    kind = data[12:16]
    if kind == b"VP8 ":
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if kind == b"VP8L":
        bits = struct.unpack("<I", data[21:25])[0]
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if kind == b"VP8X":
        return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
    return None


def _tiff_size(data: bytes):
    e = "<" if data[:2] == b"II" else ">"
    offset = struct.unpack(e + "I", data[4:8])[0]
    found = {}
    for i in range(struct.unpack(e + "H", data[offset:offset + 2])[0]):
        base = offset + 2 + 12 * i
        tag, kind = struct.unpack(e + "HH", data[base:base + 4])
        if tag in (256, 257) and kind in (3, 4):
            found[tag] = struct.unpack(e + ("H" if kind == 3 else "I"), data[base + 8:base + (10 if kind == 3 else 12)])[0]
    return (found[256], found[257]) if 256 in found and 257 in found else None


def _header_size(data: bytes):
    """(width, height) read from the file's header without decoding it; None when the format is not recognised."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:2] == b"BM":
            if struct.unpack("<I", data[14:18])[0] == 12:
                return struct.unpack("<HH", data[18:22])
            width, height = struct.unpack("<ii", data[18:26])
            return abs(width), abs(height)
        if data[:3] == b"\xff\xd8\xff":
            return _jpeg_size(data)
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return _webp_size(data)
        if data[:4] in (b"II*\x00", b"MM\x00*"):
            return _tiff_size(data)
    except (struct.error, IndexError):
        pass
    return None


def _decode(data: bytes) -> np.ndarray:
    # IMREAD_UNCHANGED keeps the alpha channel (conversion.decode_image_bytes drops it and leaves the hidden colour of transparent
    # pixels, usually black) but also ignores the EXIF turn of a photograph; a JPEG has no alpha, so it is read as colour.
    flag = cv2.IMREAD_COLOR if data[:3] == b"\xff\xd8\xff" else cv2.IMREAD_UNCHANGED
    try:
        img = cv2.imdecode(np.frombuffer(data, np.uint8), flag)
    except cv2.error:
        img = None
    if img is None or img.size == 0:
        raise _unreadable()
    return img


def image_size(data) -> tuple[int, int]:
    """The picture's (width, height) in pixels as stored in the file (a photograph's EXIF turn is not applied)."""
    data = _bytes(data)
    size = _header_size(data)
    if size is None:
        img = _decode(data)
        size = (img.shape[1], img.shape[0])
    return int(size[0]), int(size[1])


def _check_size(width: int, height: int) -> None:
    if width < 1 or height < 1:
        raise _unreadable()
    if max(width, height) > MAX_SIDE_PX or width * height > MAX_MEGAPIXELS * 1_000_000:
        raise su.ValidationError(f"The picture is too large ({width} x {height} pixels). Use one with at most {MAX_SIDE_PX} pixels "
                                 f"on a side and {MAX_MEGAPIXELS} megapixels in all.")


def _on_white(colour: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """``colour`` (h, w, 3 uint8) over white by ``alpha`` (h, w uint8), in strips so that a large picture needs no large float copy."""
    out = np.empty(colour.shape, np.uint8)
    for y in range(0, colour.shape[0], 512):
        a = alpha[y:y + 512, :, None].astype(np.float32) / 255.0
        out[y:y + 512] = np.rint(colour[y:y + 512].astype(np.float32) * a + 255.0 * (1.0 - a)).astype(np.uint8)
    return out


def _to_bgr(img: np.ndarray) -> np.ndarray:
    if img.dtype != np.uint8:
        img = cv2.convertScaleAbs(img, alpha=1.0 / 257.0 if img.dtype == np.uint16 else 255.0 if img.dtype.kind == "f" else 1.0)
    if img.ndim == 2 or img.shape[2] == 1:
        return cv2.cvtColor(img.reshape(img.shape[:2]), cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 2:                                   # grey with alpha
        return _on_white(cv2.cvtColor(np.ascontiguousarray(img[..., 0]), cv2.COLOR_GRAY2BGR), img[..., 1])
    if img.shape[2] == 4:
        return _on_white(np.ascontiguousarray(img[..., :3]), img[..., 3])
    return img


def load(data) -> np.ndarray:
    """The bytes of a picture file as a BGR uint8 image, transparency composited on white, the long side capped at :data:`WORK_PX`.

    Empty or unreadable data and pictures larger than :data:`MAX_SIDE_PX` pixels on a side or :data:`MAX_MEGAPIXELS` megapixels are
    refused with a ValidationError (the size is read from the header, so a huge picture is refused before it is decoded).
    """
    data = _bytes(data)
    size = _header_size(data)
    if size is not None:
        _check_size(*size)
    img = _to_bgr(_decode(data))
    _check_size(img.shape[1], img.shape[0])
    height, width = img.shape[:2]
    if max(height, width) > WORK_PX:
        scale = WORK_PX / max(height, width)
        img = cv2.resize(img, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(img)


# -- the pencil treatment -------------------------------------------------------------------------------------------------------------
def _grey(image) -> np.ndarray:
    """A grey 2-D uint8 view of an 8-bit grey or BGR image."""
    img = np.asarray(image)
    if img.dtype != np.uint8 or img.ndim not in (2, 3) or (img.ndim == 3 and img.shape[2] != 3) or min(img.shape[:2]) < 1:
        raise su.ValidationError("The picture must be an 8-bit colour or grey image.")
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _percent(value, name: str) -> float:
    spec = next(s for s in IMAGE_PARAMS if s["name"] == name)
    return _whole(value, spec) / 100.0


def pencil_sketch(gray, detail: int = 50, strength: int = 60) -> np.ndarray:
    """A grey picture redrawn as a pencil drawing: uint8, white paper (255) and dark strokes.

    The strokes are the outline of every edge (the steepness of the tone, which is large on both sides of an edge, so a solid
    shape is drawn as an outline) and, in the shapes darker than a limit, parallel hatching at 45 degrees
    whose strokes widen with the darkness. ``detail`` 0..100: 0 blurs fine texture away and hatches coarsely, 100 keeps all texture and
    hatches finely. ``strength`` 0..100: how dark and dense the strokes are (higher: weaker edges are drawn, lighter tones are hatched,
    the strokes are wider). The thinnest stroke is about three pixels wide, so draw it on a raster whose pixel is a third of the
    thinnest line wanted. Flat white stays white.
    """
    g = _grey(gray).astype(np.float32)
    d, s = _percent(detail, "detail"), _percent(strength, "strength")
    height, width = g.shape
    sigma = PENCIL_BLUR_MAX_PX * (1.0 - d)
    base = cv2.GaussianBlur(g, (0, 0), sigma, borderType=cv2.BORDER_REFLECT) if sigma >= 0.3 else g
    # outlines: the steepness of the tone, drawn on both sides of the edge; the stroke is as wide as the edge is soft (detail)
    gx, gy = (cv2.Sobel(base, cv2.CV_32F, dx, dy, ksize=3, scale=0.125, borderType=cv2.BORDER_REFLECT) for dx, dy in ((1, 0), (0, 1)))
    edge = cv2.magnitude(gx, gy) * (PENCIL_LINE_SCALE_PX * (2.0 + 5.0 * s) / 255.0)
    dark = cv2.dilate(np.clip(edge, 0.0, 1.0), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    # hatching: stripes along 45 degrees, the stroke width growing from the thinnest to the widest with the tone
    period = PENCIL_PERIOD_PX[0] + (PENCIL_PERIOD_PX[1] - PENCIL_PERIOD_PX[0]) * d
    tone = 1.0 - cv2.GaussianBlur(base, (0, 0), max(3.0, period / 2.0), borderType=cv2.BORDER_REFLECT) / 255.0
    start = 0.65 - 0.53 * s                                      # lighter tones than this stay unhatched
    widest = (PENCIL_HATCH_MAX_DUTY[0] + (PENCIL_HATCH_MAX_DUTY[1] - PENCIL_HATCH_MAX_DUTY[0]) * s) * period
    stroke = np.where(tone > start, PENCIL_HATCH_MIN_PX + (widest - PENCIL_HATCH_MIN_PX)
                      * np.clip((tone - start) / (1.0 - start), 0.0, 1.0), 0.0).astype(np.float32)
    u = (np.arange(width, dtype=np.float32)[None, :] + np.arange(height, dtype=np.float32)[:, None]) * np.float32(0.70710678)
    across = np.abs(np.mod(u, np.float32(period)) - np.float32(period / 2.0))
    np.maximum(dark, np.where(stroke > 0, np.clip(stroke * 0.5 - across + 0.5, 0.0, 1.0), 0.0), out=dark)
    return np.rint(255.0 * (1.0 - dark)).astype(np.uint8)


# -- tracing --------------------------------------------------------------------------------------------------------------------------
def _refine(field: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Contour pixels (x, y) moved onto the zero level of ``field``: one Newton step ``p - f * grad / |grad|^2`` where the level
    lies within a pixel (an inside pixel has f > 0, so the step goes towards the outside, which is right for holes too)."""
    height, width = field.shape
    x, y = points[:, 0].astype(np.intp), points[:, 1].astype(np.intp)
    f = field[y, x]
    gx = (field[y, np.minimum(x + 1, width - 1)] - field[y, np.maximum(x - 1, 0)]) * 0.5
    gy = (field[np.minimum(y + 1, height - 1), x] - field[np.maximum(y - 1, 0), x]) * 0.5
    g2 = gx * gx + gy * gy
    step = np.where((g2 > 1e-9) & (f * f <= g2), f / np.where(g2 > 1e-9, g2, 1.0), 0.0)
    return np.stack([x - step * gx, y - step * gy], axis=1)


def _smooth(ring: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """A closed outline low-passed along its length (the kernel is odd and normalised; the outline wraps round)."""
    n, r = len(ring), len(kernel) // 2
    if n < 8:
        return ring
    padded = ring[np.arange(-r, n + r) % n]
    return np.stack([np.convolve(padded[:, c], kernel, mode="valid") for c in (0, 1)], axis=1)


def _ring_area(ring: np.ndarray) -> float:
    x, y = ring[:, 0].astype(np.float64), ring[:, 1].astype(np.float64)
    x, y = x - x[0], y - y[0]
    return 0.5 * abs(float(np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1])))


def _simplified(ring: np.ndarray, tolerance: float, floor: float):
    kept = cv2.approxPolyDP(ring.astype(np.float32).reshape(-1, 1, 2), tolerance, True).reshape(-1, 2)
    return kept if len(kept) >= 3 and _ring_area(kept) >= floor else None


def _polygons(geometry) -> list:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [p for part in geometry.geoms for p in _polygons(part)]
    return []


def _simplified_shapes(shapes: list, tolerance: float, floor: float) -> tuple[list, int]:
    """The outlines (shell, [holes]) simplified at ``tolerance``, rings under ``floor`` mm2 dropped, and their vertex count."""
    out, count = [], 0
    for shell, holes in shapes:
        outer = _simplified(shell, tolerance, floor)
        if outer is not None:
            kept = [h for h in (_simplified(hole, tolerance, floor) for hole in holes) if h is not None]
            out.append((outer, kept))
            count += len(outer) + sum(len(h) for h in kept)
    return out, count


def _assemble(shapes: list, rect: tuple, floor: float):
    """One valid Polygon or MultiPolygon (largest part first, shells counter-clockwise) from simplified outlines, cut to ``rect``;
    a part the cut leaves smaller than ``floor`` mm2 is dropped."""
    polygons = [Polygon(shell, holes) for shell, holes in shapes]
    if not polygons:
        return Polygon()
    array = np.array(polygons, dtype=object)
    bad = ~shapely.is_valid(array)
    if bad.any():
        array[bad] = shapely.make_valid(array[bad])
    parts = [orient(p) for p in _polygons(shapely.clip_by_rect(shapely.union_all(array), *rect)) if p.area >= floor]
    if not parts:
        return Polygon()
    parts.sort(key=lambda p: -p.area)
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def _vectorise(field: np.ndarray, width_mm: float, height_mm: float, min_area: float):
    """Geometry of the area where ``field`` is positive; the field covers a width_mm x height_mm picture centred on (0, 0).

    The enlarged field is padded with its own edge values, so an area that reaches the edge of the picture is traced beyond it and
    then cut exactly at the edge (a solid picture is a clean rectangle, not one with blunted corners).
    """
    height, width = field.shape
    k = int(np.clip(math.ceil(UPSCALE_PX / max(height, width)), 1, MAX_UPSCALE))
    up = cv2.resize(field, (width * k, height * k), interpolation=cv2.INTER_CUBIC) if k > 1 else field
    uh, uw = up.shape
    to_mm = np.array([width_mm / uw, height_mm / uh])
    sigma = float(np.clip(SMOOTH_PX * width_mm / width, *SMOOTH_MM) / to_mm[0])          # in samples: one sample is about one enlarged pixel
    kernel = np.exp(-0.5 * (np.arange(-math.ceil(3 * sigma), math.ceil(3 * sigma) + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    pad = math.ceil(3 * sigma) + 2                                              # the smoothing rounds corners only beyond the edge
    up = cv2.copyMakeBorder(up, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    mask = np.zeros((up.shape[0] + 2, up.shape[1] + 2), np.uint8)
    mask[1:-1, 1:-1] = up > 0
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE, offset=(-1, -1))
    if hierarchy is None:
        return Polygon()
    parent = hierarchy[0][:, 3].tolist()
    min_px = min_area / (to_mm[0] * to_mm[1])
    # a cheap pixel-count estimate throws away the specks before any per-point work
    alive = {i for i, c in enumerate(contours) if len(c) >= 3 and cv2.contourArea(c) + len(c) / 2.0 + 1.0 >= 0.5 * min_px}
    order = [i for i in sorted(alive) if parent[i] == -1 or parent[i] in alive]
    if not order:
        return Polygon()
    points = _refine(up, np.concatenate([contours[i][:, 0, :] for i in order])) - pad     # back to the enlarged field's pixels
    shells, holes = {}, {}
    for i, ring in zip(order, np.split(points, np.cumsum([len(contours[i]) for i in order])[:-1])):
        ring = (_smooth(ring, kernel) + 0.5) * to_mm - np.array([width_mm, height_mm]) / 2.0
        if parent[i] == -1:
            shells[i] = ring
        else:
            holes.setdefault(parent[i], []).append(ring)
    shapes = [(shell, holes.get(i, [])) for i, shell in shells.items()]
    rect = (-width_mm / 2.0, -height_mm / 2.0, width_mm / 2.0, height_mm / 2.0)
    tolerance = TOLERANCE_MM
    for _ in range(16):                       # the vertex cap: coarser tolerance, and the details it can no longer carry, until it fits
        floor = max(min_area, (3.0 * tolerance) ** 2)
        shapes, count = _simplified_shapes(shapes, tolerance, floor)                  # each round on the last one's rings
        if count <= MAX_VERTICES:
            result = _assemble(shapes, rect, floor)
            if shapely.get_num_coordinates(result) <= MAX_VERTICES:
                return result
        tolerance *= min(2.5, max(1.5, 1.2 * math.sqrt(count / MAX_VERTICES)))
    return Polygon()


def _field(gray: np.ndarray, scale: float, p: dict) -> tuple[np.ndarray, float, float]:
    """The tone field (positive where engraved) of a grey picture of ``scale`` mm per pixel, and its size in mm."""
    height, width = gray.shape
    size = (width * scale, height * scale)
    if p["treatment"] == "pencil":
        long_mm = max(size)
        pixel = min(max(p["min_feature_mm"] / PENCIL_MIN_STROKE_PX, long_mm / PENCIL_MAX_PX), long_mm / PENCIL_MIN_RASTER_PX)
        shape = (max(1, round(size[0] / pixel)), max(1, round(size[1] / pixel)))
        raster = cv2.resize(gray, shape, interpolation=cv2.INTER_AREA if shape[0] < width else cv2.INTER_CUBIC)
        sketch = pencil_sketch(255 - raster if p["invert"] else raster, p["detail"], p["strength"])
        level = PENCIL_LEVEL if p["auto_threshold"] else p["threshold"]
        return (level + 0.5) - sketch.astype(np.float32), *size
    sigma = min(p["min_feature_mm"] / BLUR_DIVISOR / scale, MAX_BLUR_PX)      # what is smaller than a feature is not drawn
    if sigma >= 0.3:
        gray = cv2.GaussianBlur(gray, (0, 0), sigma)
    level = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0] if p["auto_threshold"] else p["threshold"]
    field = (level + 0.5) - gray.astype(np.float32)
    return (-field if p["invert"] else field), *size


def geometry(image_bgr, width_mm: float, height_mm: float, params=None):
    """Engravable geometry of a picture: a shapely Polygon or MultiPolygon in mm, centred on (0, 0), y down, fitted inside the
    width_mm x height_mm box with the picture's aspect kept, closed rings with holes, valid. An empty Polygon when nothing is engraved.

    ``params`` are the settings of :data:`IMAGE_PARAMS` (see :func:`checked`). Dark areas of the graphic are the engraved areas;
    ``invert`` swaps that. The picture is read at most :data:`WORK_PX` pixels on its long side.
    """
    p = checked(params)
    try:
        box = float(width_mm), float(height_mm)
    except (TypeError, ValueError):
        box = (0.0, 0.0)
    if not all(math.isfinite(v) and v > 0 for v in box):
        raise su.ValidationError("The width and the height of the picture must be positive numbers of millimetres.")
    gray = _grey(image_bgr)
    if max(gray.shape) > WORK_PX:
        scale = WORK_PX / max(gray.shape)
        gray = cv2.resize(gray, (max(1, round(gray.shape[1] * scale)), max(1, round(gray.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    scale = min(box[0] / gray.shape[1], box[1] / gray.shape[0])               # mm per pixel: the picture is contained in the box
    field, width, height = _field(np.ascontiguousarray(gray), scale, p)
    return _vectorise(field, width, height, p["min_feature_mm"] ** 2)
