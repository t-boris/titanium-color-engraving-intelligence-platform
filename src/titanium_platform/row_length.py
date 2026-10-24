"""How long the scan rows of an engraving are (DEC-107): the size a colour was measured at and a prediction is made for.

On titanium the colour depends on the size of what is engraved, not only on its settings: the operator's «Inna Portrait» engraved
150 mm wide came out straw and gold where the 38.4 mm grey ramps of the same settings had given violet and blue (median 14 dE apart),
while the same file's greys drawn with the colours measured at 150 mm matched its engraving (median 4.9 dE). The working hypothesis:
the laser comes back over a point after one row, so a short row returns while the titanium is still hot and drives the oxide further.
A measurement therefore keeps the row length it was made at, and a prediction uses the measurements at the size it predicts
(``prediction.curve_at``).

The row length of a layer is the length the laser marks along one scan row through a point of it, averaged over its marked points:
``sum(m_r ** 2) / sum(m_r)`` over its rows ``r``, where ``m_r`` is the marked length of row ``r``. A rectangle ``W`` wide gives ``W``;
a picture gives its width along the scan (in grayscale mode every pixel fires, the white at Min). The rows run along the layer's
scan angle (0 = along x). A fill of several shapes is scanned as one (LightBurn's "Fill all shapes at once", its default and what the
app writes): a row's marked length sums every shape it crosses, the jumps between them being fast on a galvo; a layer filled shape by
shape (``scanOpt`` "individual", or flood fill) scans each shape on its own. Fill "by group" is taken as all at once: the groups of a
file are not read. A Line-mode layer has no rows, nor has an Offset fill (it follows the outlines).

The rows are sampled across the shapes (``ROWS`` of them, not one per line interval): the length is a mean, and the sample keeps its
error well under the 10 % that tells two sizes apart (``prediction.SIZE_TOLERANCE``).
"""
from __future__ import annotations

import json
import math
import threading
from collections import OrderedDict
from typing import Iterable

import numpy as np

from . import lightburn as lb, render_cache as rc

ROWS = 512                       # scan rows sampled across a layer's shapes
FILLS = ("Scan", "Scan+Cut")     # layer types that fill their shapes row by row (an Offset fill follows the outlines instead)
ALGORITHM = "1"                  # how a row length is measured; a release names it (electron REQ-083)
KEEP_FILES = 256                 # row lengths of the stored files read last, kept in memory

_files: OrderedDict[str, dict[int, float | None]] = OrderedDict()
_lock = threading.Lock()


def _loops(region) -> list[np.ndarray]:
    """The closed loops a region fills: its outline and its holes (even-odd), as (n, 2) arrays; none for an open path."""
    if not (region.kind in ("rect", "bitmap") or region.closed) or len(region.polygon) < 3:
        return []
    return [np.asarray(loop, np.float64) for loop in [region.polygon, *region.holes] if len(loop) >= 3]


def _marked(loops: list[np.ndarray], along: np.ndarray, across: np.ndarray) -> np.ndarray:
    """The marked length of each sampled row over ``loops`` filled together (even-odd), the rows running along ``along``."""
    edges = np.concatenate([np.stack([loop, np.roll(loop, -1, axis=0)], axis=1) for loop in loops])      # (e, 2 ends, 2)
    u, v = edges @ along, edges @ across                                                                # (e, 2) each
    low, high = v.min(), v.max()
    if not high > low:
        return np.zeros(0)
    step = (high - low) / ROWS
    rows = low + (np.arange(ROWS) + 0.5) * step
    v1, v2, u1, u2 = v[:, 0], v[:, 1], u[:, 0], u[:, 1]
    first = np.ceil((np.minimum(v1, v2) - low) / step - 0.5).astype(int)          # an edge crosses the rows with min <= v < max
    last = np.ceil((np.maximum(v1, v2) - low) / step - 0.5).astype(int)
    count = np.clip(last, 0, ROWS) - np.clip(first, 0, ROWS)
    keep = (count > 0) & (v1 != v2)
    if not keep.any():
        return np.zeros(ROWS)
    counts = count[keep]
    edge = np.repeat(np.flatnonzero(keep), counts)
    row = np.repeat(np.clip(first[keep], 0, ROWS) - (np.cumsum(counts) - counts), counts) + np.arange(int(counts.sum()))
    x = u1[edge] + (rows[row] - v1[edge]) * (u2[edge] - u1[edge]) / (v2[edge] - v1[edge])
    order = np.lexsort((x, row))
    row, x = row[order], x[order]
    marked = np.zeros(ROWS)
    np.add.at(marked, row[0::2], x[1::2] - x[0::2])                 # each row crosses closed loops an even number of times
    return marked


def of_regions(regions: Iterable, angle_deg: float = 0.0, together: bool = True) -> float | None:
    """The row length (mm) of shapes scanned at ``angle_deg``: filled together (one fill over them all) or each on its own. None when
    nothing of them is filled."""
    return _of_groups([loops for loops in (_loops(r) for r in regions) if loops], angle_deg, together)


def of_shapes(shapes: Iterable[Iterable], angle_deg: float = 0.0, together: bool = True) -> float | None:
    """The row length (mm) of shapes given as their closed loops in mm (each shape: its outline, then its holes), as ``of_regions``: the
    regions of a vector work that one layer fills."""
    groups = [[np.asarray(loop, np.float64) for loop in loops if len(loop) >= 3] for loops in shapes]
    return _of_groups([loops for loops in groups if loops], angle_deg, together)


def _of_groups(groups: list[list[np.ndarray]], angle_deg: float, together: bool) -> float | None:
    a = math.radians(angle_deg or 0.0)
    along, across = np.array([math.cos(a), math.sin(a)]), np.array([-math.sin(a), math.cos(a)])
    if together:
        groups = [[loop for loops in groups for loop in loops]] if groups else []
    marked = np.concatenate([_marked(loops, along, across) for loops in groups]) if groups else np.zeros(0)
    total = float(marked.sum())
    return round(float((marked ** 2).sum()) / total, 2) if total > 1e-9 else None


def _setting(layer: lb.Layer, key: str) -> str:
    raw = (layer.source_settings or {}).get(key)
    raw = raw.get("Value") if isinstance(raw, dict) else raw
    return "" if raw is None else str(raw).strip().lower()


def _together(layer: lb.Layer) -> bool:
    """Does LightBurn fill the layer's shapes as one (not shape by shape)?"""
    return _setting(layer, "scanOpt") != "individual" and _setting(layer, "floodFill") not in ("1", "true")


def of_layer(layer: lb.Layer) -> float | None:
    """The row length of one layer of a file: an Image layer's largest picture (the one a photograph of it measures), a fill's shapes
    as LightBurn scans them; None for a Line-mode layer or one with nothing filled."""
    if layer.layer_type == "Image":
        pictures = [r for r in layer.regions if r.bitmap]
        picture = max(pictures, key=lambda r: r.width * r.height, default=None)
        return None if picture is None else of_regions([picture], layer.scan_angle or 0.0)
    if layer.layer_type not in FILLS:
        return None
    return of_regions(layer.regions, layer.scan_angle or 0.0, _together(layer))


def of_project(project: lb.Project) -> dict[int, float | None]:
    """The row length of every layer of a parsed file, by layer index."""
    return {layer.index: of_layer(layer) for layer in project.layers}


def recorded(store) -> dict[int, dict[int, float | None]]:
    """The row lengths stored with pairs whose LightBurn file is not kept, by pair id and layer index: the snapshot of a connected
    laboratory release, which publishes every row length with its layer (electron REQ-083). Empty in a workshop of its own."""
    out: dict[int, dict[int, float | None]] = {}
    for row in store.query("SELECT pair_id, layer_index, row_mm FROM pair_row_length"):
        out.setdefault(row["pair_id"], {})[row["layer_index"]] = row["row_mm"]
    return out


def of_pair(known: dict[int, dict[int, float | None]], pair_id: int, path: str | None) -> dict[int, float | None]:
    """The row lengths of a pair's layers: those stored with it (``recorded``), else read from its LightBurn file (``of_file``)."""
    return known[pair_id] if pair_id in known else of_file(path)


def of_file(path: str | None) -> dict[int, float | None]:
    """The row lengths of a stored LightBurn file's layers (``of_project``), read once per version of the file; empty when the file
    is missing or cannot be read (its measurements then have no known size)."""
    stamp = rc.file_stamp(path)
    if stamp.get("missing"):
        return {}
    key = json.dumps(stamp, sort_keys=True)
    with _lock:
        if key in _files:
            _files.move_to_end(key)
            return _files[key]
    try:
        found = of_project(lb.parse_file(str(path)))
    except (lb.LightBurnError, OSError):
        found = {}
    with _lock:
        _files[key] = found
        while len(_files) > KEEP_FILES:
            _files.popitem(last=False)
    return found
