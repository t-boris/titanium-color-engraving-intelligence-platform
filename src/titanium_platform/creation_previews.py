"""Pictures that let a person compare the results a picture can become before choosing one (feature ux-work-creation-p0, REQ-003).

Every tile is the person's own picture made by the same code the work will use, on a reduced copy of the picture and at the width asked
for: colour areas by :func:`segment.segment` (the split of a photograph work), a silhouette and lines by :func:`vectorize.trace` (the
strategies ``fill`` and ``line``), photo engraving as the grey picture a photo work takes (:func:`prediction_store.decode_upload`). They
show the *structure* each result gives (how many areas, which shapes, which strokes); the colours of titanium come later, from the
measurements of the chosen setup, and no tile claims them. Nothing is stored: a tile is drawn when it is asked for, and the pictures
that were drawn last are remembered by the key of what they were drawn from.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache

import cv2
import numpy as np

from . import conversion as cv, prediction_store as ps, segment as seg, setup as su, vectorize
from .creation_context import RESULTS

SIDE_PX = 360                              # the longer side of a tile; the same as a saved work's thumbnail (vector_job.THUMB_PX)
SUPERSAMPLE = 2                            # drawn twice as large and reduced: smooth edges and no seam between two neighbours
BACKGROUND = (58, 60, 66)                  # the same ground as a saved work's thumbnail (vector_job.THUMB_BACKGROUND)
SHAPE = (232, 234, 238)                    # a silhouette and lines are shown in one neutral colour: their colour is not chosen yet
COLOURS = 12                               # the number of colour areas the vector form starts from
CACHED = 24                                # tiles remembered


def _reduced(data: bytes) -> np.ndarray:
    """The picture as an RGB array whose longer side is at most ``SIDE_PX``."""
    bgr = cv.decode_image_bytes(data)
    scale = min(1.0, SIDE_PX / max(bgr.shape[:2]))
    small = cv2.resize(bgr, (max(1, round(bgr.shape[1] * scale)), max(1, round(bgr.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2RGB)


def _png(rgb: np.ndarray) -> bytes:
    return cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))[1].tobytes()


def _canvas(document: dict) -> tuple[np.ndarray, float, int, int]:
    size = document["size_mm"]
    scale = SIDE_PX / max(size["width"], size["height"])
    cols, rows = max(1, round(size["width"] * scale)), max(1, round(size["height"] * scale))
    canvas = np.empty((rows * SUPERSAMPLE, cols * SUPERSAMPLE, 3), np.uint8)
    canvas[:] = BACKGROUND
    return canvas, scale * SUPERSAMPLE, cols, rows


def _fill(canvas: np.ndarray, region: dict, rgb, big: float) -> None:
    loops = [np.round(np.asarray(loop) * big).astype(np.int32) for loop in region["loops"] if len(loop) >= 3]
    if loops:
        cv2.fillPoly(canvas, loops, tuple(int(v) for v in rgb))          # the outer boundary and the holes in one call: the holes stay open


def _done(canvas: np.ndarray, cols: int, rows: int) -> bytes:
    return _png(cv2.resize(canvas, (cols, rows), interpolation=cv2.INTER_AREA))


def _colour(rgb: np.ndarray, width_mm: float) -> tuple[bytes, dict]:
    document = seg.segment(rgb, width_mm, COLOURS, use_faces=False)       # the faces are searched when the work is made, not for a tile
    canvas, big, cols, rows = _canvas(document)
    for region in seg.regions_as_loops(document):
        _fill(canvas, region, region["srgb"], big)
    return _done(canvas, cols, rows), {"areas": len(document["regions"]), "colours": len(document["palette"])}


def _silhouette(rgb: np.ndarray, width_mm: float) -> tuple[bytes, dict]:
    document = vectorize.trace(rgb, width_mm, "fill")
    canvas, big, cols, rows = _canvas(document)
    for region in document["regions"]:
        _fill(canvas, region, SHAPE, big)
    return _done(canvas, cols, rows), {"areas": len(document["regions"])}


def _lines(rgb: np.ndarray, width_mm: float) -> tuple[bytes, dict]:
    document = vectorize.trace(rgb, width_mm, "line")
    canvas, big, cols, rows = _canvas(document)
    stroke = max(1, round(max(document["px_mm"], 0.05) * big))
    for region in document["regions"]:
        for line in region["strokes"]:
            cv2.polylines(canvas, [np.round(np.asarray(line) * big).astype(np.int32)], False, SHAPE, stroke)
    return _done(canvas, cols, rows), {"strokes": sum(len(r["strokes"]) for r in document["regions"])}


def _photo(rgb: np.ndarray, width_mm: float) -> tuple[bytes, dict]:
    """The grey picture a photo work takes (a luminance, as LightBurn converts a colour picture for an Image layer)."""
    grey = ps.decode_upload(_png(rgb))["picture"]
    shown = np.clip(np.asarray(grey) * 255.0, 0, 255).round().astype(np.uint8)
    scale = SIDE_PX / max(shown.shape[:2])              # the size of the other tiles: all of them show the same picture at the same size
    shown = cv2.resize(shown, (max(1, round(shown.shape[1] * scale)), max(1, round(shown.shape[0] * scale))), interpolation=cv2.INTER_LINEAR)
    return _png(cv2.cvtColor(shown, cv2.COLOR_GRAY2RGB)), {"levels": int(len(np.unique(shown)))}


DRAW = {"colour": _colour, "silhouette": _silhouette, "lines": _lines, "photo": _photo}


def key(data: bytes, width_mm: float, result: str) -> str:
    """What a tile is drawn from: the picture, the width and the result. The same key is the same tile."""
    return hashlib.sha256(data + f"|{width_mm:.4f}|{result}".encode()).hexdigest()[:32]


@lru_cache(maxsize=CACHED)
def _tile(tile_key: str, data: bytes, width_mm: float, result: str) -> tuple[bytes, tuple]:
    png, facts = DRAW[result](_reduced(data), width_mm)
    return png, tuple(sorted(facts.items()))


def tile(data: bytes, width_mm, result: str) -> tuple[str, bytes, dict]:
    """The tile of ``result`` for a picture at ``width_mm``: its key, its PNG and the counts that describe it (areas, strokes ...)."""
    if result not in RESULTS:
        raise su.ValidationError("choose what the work will be: colour areas, photo engraving, a silhouette or lines")
    try:
        width = float(width_mm)
    except (TypeError, ValueError):
        raise su.ValidationError("the work width must be a positive number of millimetres") from None
    if not np.isfinite(width) or width <= 0:
        raise su.ValidationError("the work width must be a positive number of millimetres")
    tile_key = key(data, width, result)
    png, facts = _tile(tile_key, data, width, result)
    return tile_key, png, dict(facts)
