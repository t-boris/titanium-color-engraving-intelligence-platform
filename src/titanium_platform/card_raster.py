"""A card picture engraved as a raster photo instead of a traced vector form (REQ-026).

A raster picture fills its rectangle on the card (``width`` x ``height`` mm, turned by ``rotation`` degrees clockwise on the screen, y
down). :func:`prepare` makes the pixels LightBurn's Image layer engraves (``plans.export_lbrn2``, a layer's ``picture["pixels"]``),
:func:`preview_png` draws the look of those pixels in the layer's image mode for the screen, :func:`bounds` is the axis-aligned box the
rotated picture occupies and :func:`cache_key` names a result for callers that cache it.

Pixel format. ``prepare`` returns a uint8 array (rows, columns, 4) in BGRA order, row 0 at the top (y down), whose pixel is one dot of the
engraving grid: ``dpi`` pixels to the inch over the bounding box of the rotated picture, so ``plans.export_lbrn2`` stores it with that
DPI and LightBurn neither resamples nor resizes it. The picture is grey (B = G = R, the grey the preview and the dot kinds use) so that
what the screen shows is what the layer engraves; the corners the rotated picture does not cover have alpha 0 (white colour), the edge of
the picture is one pixel of partial alpha, and an unrotated picture is opaque everywhere. LightBurn leaves transparent pixels alone.

What the settings do. ``invert`` swaps light and dark. ``treatment`` "pencil" redraws the tones as the pencil drawing of
``card_image.pencil_sketch`` (on a raster whose pixel is a third of ``min_feature_mm``, as the traced form draws it, then brought to the
layer's grid), with ``detail`` and ``strength``. ``threshold`` and ``auto_threshold`` are ignored: a raster has no black and white cut
(the image mode decides how grey becomes dots). Transparency in the imported file is composited on white by ``card_image.load``, which
also caps the long side of the source at ``card_image.WORK_PX`` pixels. The picture is stretched to fill the rectangle, as the rectangle
is what the operator sized.

Pure functions on bytes and arrays: the same input always gives the same bytes. The sizes are bounded (:data:`MAX_SIDE_PX`,
:data:`MAX_PIXELS`, :data:`MIN_DPI` .. :data:`MAX_DPI`) and checked before the file is decoded.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Mapping

import cv2
import numpy as np

from . import card_image, dots, grayscale, photo_modes
from . import setup as su

MIN_DPI, MAX_DPI = 10.0, 5080.0          # the resolutions a raster picture may be made at (pixels per inch; 5080 dpi is a 0.005 mm line interval)
MAX_SIDE_PX = 6000                       # the most pixels on a side of the result ...
MAX_PIXELS = 20_000_000                  # ... and in all
PLAIN = "grayscale"                      # the image mode whose look is the plain grey levels (and what any unknown mode looks like)
INK, PAPER = 0, 255                      # a fired dot is drawn black on white in the dithered look
ALGORITHM = 1                            # raise it when the pixels or the look of a picture change, so that cached results are not reused
QUARTER_EPS = 1e-9                       # a turn this close to a multiple of 90 degrees is made exactly
PNG_COMPRESSION = 3


# -- checking -------------------------------------------------------------------------------------------------------------------------
def _box(width_mm, height_mm) -> tuple[float, float]:
    try:
        width, height = float(width_mm), float(height_mm)
    except (TypeError, ValueError):
        width = height = 0.0
    if not (math.isfinite(width) and math.isfinite(height) and width > 0 and height > 0):
        raise su.ValidationError("The width and the height of the picture must be positive numbers of millimetres.")
    return width, height


def _angle(rotation_deg) -> float:
    try:
        angle = float(rotation_deg)
    except (TypeError, ValueError):
        angle = math.nan
    if not math.isfinite(angle):
        raise su.ValidationError("The rotation of the picture must be a number of degrees.")
    return angle


def _dpi(value) -> float:
    try:
        dpi = float(value)
    except (TypeError, ValueError):
        dpi = math.nan
    if isinstance(value, bool) or not MIN_DPI <= dpi <= MAX_DPI:                       # NaN fails the comparison too
        raise su.ValidationError(f"The resolution of the picture must be a number from {MIN_DPI:g} to {MAX_DPI:g} dpi.")
    return dpi


def _settings(params) -> dict:
    if params is not None and not isinstance(params, Mapping):
        raise su.ValidationError("The picture settings must be an object.")
    return card_image.checked(None if params is None else dict(params))


# -- sizes ----------------------------------------------------------------------------------------------------------------------------
def bounds(width_mm: float, height_mm: float, rotation_deg: float) -> tuple[float, float]:
    """The (width, height) in mm of the axis-aligned box that holds a width_mm x height_mm rectangle turned by ``rotation_deg`` about its
    centre (rounded to a millionth of a millimetre, so that a quarter turn gives exact numbers)."""
    width, height = _box(width_mm, height_mm)
    turn = math.radians(_angle(rotation_deg) % 360.0)
    c, s = abs(math.cos(turn)), abs(math.sin(turn))
    return round(width * c + height * s, 6), round(width * s + height * c, 6)


def _quarter_turns(angle: float) -> int | None:
    """The clockwise quarter turns (0..3) of an angle that is a multiple of 90 degrees, else None."""
    turns = (angle % 360.0) / 90.0
    whole = round(turns)
    return whole % 4 if abs(turns - whole) < QUARTER_EPS else None


def _sizes(width: float, height: float, angle: float, dpi: float) -> tuple[tuple[int, int], tuple[int, int]]:
    """The pixel size (columns, rows) of the unturned picture and of the result (the bounding box of the turned one), both on the grid of ``dpi``."""
    scale = dpi / grayscale.MM_PER_INCH
    box_w, box_h = bounds(width, height, angle)
    out = (max(1, round(box_w * scale)), max(1, round(box_h * scale)))
    quarter = _quarter_turns(angle)
    if quarter is None:
        return (max(1, round(width * scale)), max(1, round(height * scale))), out
    return (out[1], out[0]) if quarter % 2 else out, out                 # a quarter turn swaps the sides exactly


def check(width_mm: float, height_mm: float, rotation_deg: float, dpi: float) -> tuple[int, int]:
    """The pixel size (columns, rows) the picture would have at ``dpi``, or ValidationError with the sentence that says why it cannot be made
    (a bad size, rotation or resolution, or too many pixels). Nothing is decoded or drawn, so the editor can say it before the file is asked for."""
    width, height = _box(width_mm, height_mm)
    angle = _angle(rotation_deg)
    dpi = _dpi(dpi)
    columns, rows = _sizes(width, height, angle, dpi)[1]
    _refuse_size(columns, rows, dpi)
    return columns, rows


def _refuse_size(columns: int, rows: int, dpi: float) -> None:
    if max(columns, rows) > MAX_SIDE_PX or columns * rows > MAX_PIXELS:
        raise su.ValidationError(f"A raster picture may have at most {MAX_SIDE_PX} pixels on a side and {MAX_PIXELS // 1_000_000} million "
                                 f"pixels in all, and this one would be {columns} x {rows} pixels at {dpi:g} dpi.")


# -- the pixels -----------------------------------------------------------------------------------------------------------------------
def _resized(plane: np.ndarray, columns: int, rows: int) -> np.ndarray:
    have_rows, have_columns = plane.shape
    if (have_columns, have_rows) == (columns, rows):
        return plane
    shrinks = columns <= have_columns and rows <= have_rows
    return cv2.resize(plane, (columns, rows), interpolation=cv2.INTER_AREA if shrinks else cv2.INTER_CUBIC)


def _pencil(grey: np.ndarray, width_mm: float, height_mm: float, p: Mapping) -> np.ndarray:
    """The pencil drawing of a grey picture that fills width_mm x height_mm, on the raster the traced form draws it on (a pixel a third of
    the smallest feature, between the limits of ``card_image``); ``invert`` applies before the drawing, as there."""
    long_mm = max(width_mm, height_mm)
    pixel = min(max(p["min_feature_mm"] / card_image.PENCIL_MIN_STROKE_PX, long_mm / card_image.PENCIL_MAX_PX),
                long_mm / card_image.PENCIL_MIN_RASTER_PX)
    columns, rows = max(1, round(width_mm / pixel)), max(1, round(height_mm / pixel))
    raster = cv2.resize(grey, (columns, rows), interpolation=cv2.INTER_AREA if columns < grey.shape[1] else cv2.INTER_CUBIC)
    return card_image.pencil_sketch(255 - raster if p["invert"] else raster, p["detail"], p["strength"])


def _turned(plane: np.ndarray, angle: float, columns: int, rows: int) -> tuple[np.ndarray, np.ndarray]:
    """``plane`` turned ``angle`` degrees clockwise on the screen (y down) about its centre into a columns x rows canvas, and the alpha plane
    of that canvas: 255 where the picture covers it, 0 where it does not (one pixel of partial alpha at the edge). The colour continues the
    picture's edge beyond it so that the edge pixels are not darkened by the empty corners."""
    quarter = _quarter_turns(angle)
    if quarter is not None:                                              # exact, nothing is resampled
        turned = np.ascontiguousarray(np.rot90(plane, -quarter))         # rot90 turns counter-clockwise for a positive count
        return turned, np.full(turned.shape, 255, np.uint8)
    have_rows, have_columns = plane.shape
    turn = math.radians(angle)
    c, s = math.cos(turn), math.sin(turn)
    cx, cy, ox, oy = (have_columns - 1) / 2.0, (have_rows - 1) / 2.0, (columns - 1) / 2.0, (rows - 1) / 2.0
    # (x, y) -> (x c - y s, x s + y c) about the centres: with y down this is a clockwise turn on the screen
    matrix = np.array([[c, -s, ox - (c * cx - s * cy)], [s, c, oy - (s * cx + c * cy)]], np.float64)
    grey = cv2.warpAffine(plane, matrix, (columns, rows), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    alpha = cv2.warpAffine(np.full(plane.shape, 255, np.uint8), matrix, (columns, rows), flags=cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    grey[alpha == 0] = 255                                               # what is hidden under full transparency is white, whatever the edge was
    return grey, alpha


def prepare(image_bytes: bytes, width_mm: float, height_mm: float, rotation_deg: float, dpi: float, params: Mapping) -> np.ndarray:
    """The pixels LightBurn's Image layer engraves for a picture file: uint8 BGRA (rows, columns, 4), see the module's notes.

    The picture is resampled to ``width_mm`` x ``height_mm`` at ``dpi``, turned ``rotation_deg`` degrees clockwise on the screen and placed
    in the bounding box of the turned picture (:func:`bounds`); the corners it does not cover are transparent. ``params`` are the picture
    settings of ``card_image.IMAGE_PARAMS``: ``invert`` and the pencil ``treatment`` (with ``detail``, ``strength``, ``min_feature_mm``)
    apply, ``threshold`` and ``auto_threshold`` do not. A ValidationError (a plain sentence) names what is wrong: a size or a resolution
    out of bounds (6000 pixels on a side, 20 million in all, 10 to 5080 dpi, checked before the file is read), an unreadable file, a
    setting out of range.
    """
    width, height = _box(width_mm, height_mm)
    angle = _angle(rotation_deg)
    dpi = _dpi(dpi)
    p = _settings(params)
    (columns, rows), (out_columns, out_rows) = _sizes(width, height, angle, dpi)
    _refuse_size(out_columns, out_rows, dpi)
    grey = cv2.cvtColor(card_image.load(image_bytes), cv2.COLOR_BGR2GRAY)
    if p["treatment"] == "pencil":
        grey = _pencil(grey, width, height, p)
    elif p["invert"]:
        grey = 255 - grey
    grey, alpha = _turned(_resized(np.ascontiguousarray(grey), columns, rows), angle, out_columns, out_rows)
    return cv2.merge([grey, grey, grey, alpha])


# -- the look -------------------------------------------------------------------------------------------------------------------------
def _kind(dither) -> str | None:
    """The dot kind of an image mode (``dots.KINDS``), or None for grayscale and for every mode that is not a dot kind or not known."""
    found = photo_modes.mode(dither)
    return found.key if found is not None and found.key in dots.KINDS else None


def _planes(pixels) -> tuple[np.ndarray, np.ndarray]:
    """The grey (rows, columns) and alpha planes of 8-bit grey, BGR or BGRA pixels."""
    a = np.asarray(pixels)
    if a.dtype != np.uint8 or a.ndim not in (2, 3) or (a.ndim == 3 and a.shape[2] not in (3, 4)) or min(a.shape[:2]) < 1:
        raise su.ValidationError("The picture must be an 8-bit grey, colour or colour-with-transparency image.")
    if a.ndim == 2:
        return a, np.full(a.shape, 255, np.uint8)
    grey = cv2.cvtColor(np.ascontiguousarray(a[..., :3]), cv2.COLOR_BGR2GRAY)
    return grey, np.ascontiguousarray(a[..., 3]) if a.shape[2] == 4 else np.full(a.shape[:2], 255, np.uint8)


def preview_png(pixels: np.ndarray, dither: str, dot_width: float | None, dpi: float) -> bytes:
    """The look of ``pixels`` (as :func:`prepare` returns them, on the grid of ``dpi``) engraved in the image mode ``dither``, as a PNG with
    the picture's alpha, the same size as the pixels.

    ``dither`` is the ``ditherMode`` of the layer: a dot kind of ``dots.KINDS`` (threshold, ordered, atkinson, dither = Floyd-Steinberg,
    stucki, jarvis, newsprint, halftone, sketch, and the aliases ``photo_modes.mode`` reads) draws the dots the kind fires (``dots.struck``,
    one pixel a dot) black on white, so the screen shows the pattern the laser makes; grayscale, an unknown name or None draws the plain grey
    levels and never raises. ``dot_width`` (LightBurn's dot width correction, mm) is not drawn: the project's other previews of dot kinds
    do not draw it either, so it changes nothing here.
    """
    dpi = _dpi(dpi)
    grey, alpha = _planes(pixels)
    kind = _kind(dither)
    if kind is None:
        shade = grey
    else:
        fired = dots.struck(grey / 255.0, kind, dpi=dpi, alpha=alpha / 255.0)
        shade = np.where(fired, INK, PAPER).astype(np.uint8)
    ok, buffer = cv2.imencode(".png", cv2.merge([shade, shade, shade, alpha]), [cv2.IMWRITE_PNG_COMPRESSION, PNG_COMPRESSION])
    if not ok:
        raise su.ValidationError("The picture could not be encoded as a PNG.")
    return buffer.tobytes()


# -- caching --------------------------------------------------------------------------------------------------------------------------
def cache_key(image_bytes_stamp, width_mm: float, height_mm: float, rotation_deg: float, dpi: float, params: Mapping,
              dither: str, dot_width: float | None) -> str:
    """A stable 16-character name for the pixels and the look of one raster picture: the stamp of its file (a hash, a version, or
    ``render_cache.file_stamp``'s dict), the box, the turn and the resolution, the settings that change the pixels (not ``threshold``,
    which is ignored), the dot kind (every mode that is not one gives the plain grey look the same name) and the dot width."""
    width, height = _box(width_mm, height_mm)
    p = _settings(params)
    settings = {"invert": p["invert"], "treatment": p["treatment"]}
    if p["treatment"] == "pencil":
        settings.update({k: p[k] for k in ("detail", "strength", "min_feature_mm")})
    try:
        dot = None if dot_width is None else round(float(dot_width), 4)
    except (TypeError, ValueError):
        raise su.ValidationError("The dot width must be a number of millimetres.") from None
    parts = [ALGORITHM, image_bytes_stamp, round(width, 3), round(height, 3), round(_angle(rotation_deg), 2), round(_dpi(dpi), 3), settings,
             _kind(dither) or PLAIN, dot]
    return hashlib.sha1(json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()[:16]
