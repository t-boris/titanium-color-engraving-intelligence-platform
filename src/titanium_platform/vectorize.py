"""Image -> editable vector document -> LightBurn Path shapes (REQ-021, DEC-065).

The source raster is reduced per strategy and traced with OpenCV (no other library):

* ``color``: every pixel takes the nearest palette colour in Lab, or one of ``n_colors`` found by a deterministic
  k-means (a median cut gives the starting labels, ``cv2.kmeans`` refines them); each colour's areas become closed
  outlines with their holes.
* ``fill`` / ``text``: a one-colour silhouette, pixels at or below a grey threshold (Otsu when none is given), traced as
  closed outlines; text counters are holes.
* ``line``: the same silhouette thinned to centre-lines (``cv2.ximgproc.thinning``) and walked into open polylines.

Areas under ``min_area_mm2`` first merge into the neighbour that shares the longest border with them (for fill, text and
line art that is usually the background, so specks are dropped and pinholes filled). Outlines follow the pixel edges,
not the pixel centres, so neighbouring colours share their border and a traced area equals its pixel count. Each region
keeps its unsimplified outline (``raw``, source pixels) so the tolerance can change without the image. Coordinates are
millimetres from the image's top-left corner with y down, as in :func:`plans.export_lbrn2`.

The document is a JSON-serialisable dict::

    {"version": 1, "strategy", "size_mm": {"width", "height"}, "px_mm", "image_px": {"width", "height"},
     "tolerance_mm", "min_area_mm2", "threshold",          # grey threshold used (None for "color")
     "regions": [{"id", "task", "srgb": [r, g, b], "lab": [L, a, b], "pixels", "layer_key",
                  "loops": [[[x, y], ...], ...],            # closed outlines in mm: an outer boundary, then its holes
                  "strokes": [[[x, y], ...], ...],          # open centre-lines in mm (line art); a cycle repeats its start
                  "raw": [[[x, y], ...], ...]}]}            # the same, unsimplified, in source pixels
"""
from __future__ import annotations

import copy
import math
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from xml.sax.saxutils import quoteattr

import cv2
import numpy as np

from . import color

VERSION = 1
STRATEGIES = ("color", "fill", "text", "line")
TASKS = ("fill", "color", "text", "line", "tonal")
OUTPUT_LAYERS = range(30)          # LightBurn output colours 00..29; T1/T2 never carry geometry (DEC-044)
MAX_COLORS = len(OUTPUT_LAYERS)
WEAK = "#d32f2f"
_STEPS = ((0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1))   # (dy, dx), 4-neighbours first


class VectorizeError(ValueError):
    """The vectorisation or edit cannot proceed; the message is meant for the operator."""


@dataclass
class Region:
    """A connected area of one source colour (closed ``loops``) or the centre-lines of one stroke (open ``strokes``)."""
    id: str
    task: str
    srgb: list[int]
    lab: list[float]
    pixels: int
    layer_key: str
    loops: list = field(default_factory=list)
    strokes: list = field(default_factory=list)
    raw: list = field(default_factory=list)


def _number(value, name: str, *, positive: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise VectorizeError(f"{name} must be a number") from None
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise VectorizeError(f"{name} must be a {'positive' if positive else 'non-negative'} number")
    return number


# -- reduction ------------------------------------------------------------------------------------------------
def _unique_colors(rgb: np.ndarray):
    codes = (rgb[..., 0].astype(np.int32) << 16) | (rgb[..., 1].astype(np.int32) << 8) | rgb[..., 2]
    uniq, inverse, counts = np.unique(codes.ravel(), return_inverse=True, return_counts=True)
    return np.stack([uniq >> 16, (uniq >> 8) & 255, uniq & 255], axis=1), inverse.ravel(), counts


def _palette_classes(rgb: np.ndarray, colors) -> tuple[np.ndarray, list]:
    """Nearest palette colour (CIE76 in Lab) per pixel; a tie goes to the earlier palette entry."""
    pal = np.asarray(colors, dtype=float)
    if pal.ndim != 2 or pal.shape[1] != 3 or not 1 <= len(pal) <= MAX_COLORS or ((pal < 0) | (pal > 255) | (pal != np.round(pal))).any():
        raise VectorizeError(f"the palette must list 1 to {MAX_COLORS} sRGB colours with whole channels 0..255")
    uniq, inverse, _ = _unique_colors(rgb)
    ulab, plab = color.srgb8_to_lab(uniq), color.srgb8_to_lab(pal)
    best, labels = np.full(len(uniq), np.inf), np.zeros(len(uniq), np.int32)
    for i, p in enumerate(plab):
        d = ((ulab - p) ** 2).sum(axis=1)
        closer = d < best
        labels[closer], best[closer] = i, d[closer]
    return labels[inverse].reshape(rgb.shape[:2]), [(pal[i].astype(int).tolist(), plab[i]) for i in range(len(pal))]


def _kmeans_classes(rgb: np.ndarray, n_colors) -> tuple[np.ndarray, list]:
    """Deterministic k-means in Lab: a pixel-weighted median cut gives the starting labels, cv2.kmeans refines them."""
    if isinstance(n_colors, bool) or not isinstance(n_colors, (int, np.integer)) or not 1 <= n_colors <= MAX_COLORS:
        raise VectorizeError(f"the number of colours must be a whole number from 1 to {MAX_COLORS}")
    uniq, inverse, counts = _unique_colors(rgb)
    ulab = color.srgb8_to_lab(uniq)
    k = min(int(n_colors), len(uniq))
    boxes = [np.arange(len(uniq))]
    while len(boxes) < k:
        widest = int(np.argmax([np.ptp(ulab[b], axis=0).max() for b in boxes]))
        box = boxes.pop(widest)
        axis = int(np.argmax(np.ptp(ulab[box], axis=0)))
        box = box[np.argsort(ulab[box, axis], kind="stable")]
        cum = np.cumsum(counts[box])
        cut = min(max(int(np.searchsorted(cum, cum[-1] / 2)) + 1, 1), len(box) - 1)
        boxes += [box[:cut], box[cut:]]
    start = np.empty(len(uniq), np.int32)
    for i, box in enumerate(boxes):
        start[box] = i
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.01)
    _, labels, centers = cv2.kmeans(ulab[inverse].astype(np.float32), k, start[inverse].reshape(-1, 1), criteria, 1,
                                    cv2.KMEANS_USE_INITIAL_LABELS)
    order = np.lexsort((centers[:, 2], centers[:, 1], -centers[:, 0]))      # lightest first, as conversion._cluster
    rank = np.empty(k, np.int32)
    rank[order] = np.arange(k)
    lab = centers[order].astype(float)
    return rank[labels.ravel()].reshape(rgb.shape[:2]), [(color.lab_to_srgb8(c).tolist(), c) for c in lab]


def _binarise(rgb: np.ndarray, threshold) -> tuple[float, np.ndarray]:
    grey = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if threshold is None:
        t = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0]
    else:
        t = _number(threshold, "the threshold")
        if t > 255:
            raise VectorizeError("the threshold must be a grey level from 0 to 255")
    return float(t), grey <= t


def _merge_small(classes: np.ndarray, min_px: float) -> np.ndarray:
    """Give every 8-connected area under ``min_px`` pixels the class of the neighbour sharing its longest border.

    Smallest first (ties: component number), a still-small merged group merges on; ties between neighbours go to the
    longer border, then the larger area, then the lower number. Deterministic.
    """
    if min_px <= 1:
        return classes
    comp, cls, area = np.zeros(classes.shape, np.int64), [], []
    for c in np.unique(classes):
        n, lab, stats, _ = cv2.connectedComponentsWithStats((classes == c).astype(np.uint8), connectivity=8)
        comp[lab > 0] = lab[lab > 0] - 1 + len(cls)
        cls += [int(c)] * (n - 1)
        area += stats[1:, cv2.CC_STAT_AREA].tolist()
    if min(area) >= min_px:
        return classes
    a = np.concatenate([comp[:, :-1].ravel(), comp[:-1, :].ravel()])
    b = np.concatenate([comp[:, 1:].ravel(), comp[1:, :].ravel()])
    keep = a != b
    codes, lengths = np.unique(np.minimum(a, b)[keep] * len(area) + np.maximum(a, b)[keep], return_counts=True)
    border: list[dict] = [{} for _ in area]
    for code, n in zip(codes.tolist(), lengths.tolist()):
        i, j = divmod(code, len(area))
        border[i][j], border[j][i] = n, n
    parent = list(range(len(area)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in sorted(range(len(area)), key=lambda i: (area[i], i)):
        r = find(i)
        if area[r] >= min_px:
            continue
        shared: dict[int, int] = {}
        for j, n in border[r].items():
            if (root := find(j)) != r:
                shared[root] = shared.get(root, 0) + n
        if not shared:
            continue
        target = max(shared, key=lambda j: (shared[j], area[j], -j))
        parent[r] = target
        area[target] += area[r]
        for j, n in border[r].items():
            border[target][j] = border[target].get(j, 0) + n
    return np.array([cls[find(i)] for i in range(len(area))])[comp]


# -- tracing --------------------------------------------------------------------------------------------------
def _pixel_edges(contour: np.ndarray) -> list[list[int]]:
    """A contour on the half-pixel lattice as its exact pixel-edge polygon, in pixel-corner units.

    findContours steps diagonally past a concave corner; the corner it skips is the neighbour whose coordinates are
    both even (a pixel corner). It is put back and only the points where the direction turns are kept.
    """
    p = contour.reshape(-1, 2)
    q = np.roll(p, -1, axis=0)
    corner = np.where(p % 2 == 0, p, q)
    points = np.stack([p, corner], axis=1).reshape(-1, 2)[np.stack([np.ones(len(p), bool), (p != q).all(axis=1)], axis=1).ravel()]
    d = np.sign(np.roll(points, -1, axis=0) - points)
    return (points[(d != np.roll(d, 1, axis=0)).any(axis=1)] // 2).tolist()


def _trace_mask(mask: np.ndarray) -> list[list[list[list[int]]]]:
    """Pixel-edge outlines of a mask: one [outer, hole, ...] loop set per 8-connected area.

    Every pixel is drawn as its closed square on a doubled lattice (corners at even coordinates), so the contours run
    along pixel edges and two areas touching at a corner stay one area, as with 8-connectivity.
    """
    h, w = mask.shape
    grid = np.zeros((2 * h + 3, 2 * w + 3), np.uint8)      # one lattice point of padding on every side
    grid[2:-1:2, 2:-1:2] = mask
    grid = cv2.dilate(grid, np.ones((3, 3), np.uint8))
    contours, hierarchy = cv2.findContours(grid, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE, offset=(-1, -1))
    if hierarchy is None:
        return []
    following, child, parent = hierarchy[0][:, 0], hierarchy[0][:, 2], hierarchy[0][:, 3]
    sets = []
    for i in range(len(contours)):
        if parent[i] == -1:
            loops, c = [_pixel_edges(contours[i])], child[i]
            while c != -1:
                loops.append(_pixel_edges(contours[c]))
                c = following[c]
            sets.append(loops)
    return sets


def _loops_mask(loops: list, width: int, height: int) -> np.ndarray:
    """Pixels whose centre lies inside the loops (even-odd), the inverse of :func:`_trace_mask`."""
    grid = np.zeros((2 * height + 1, 2 * width + 1), np.uint8)
    cv2.fillPoly(grid, [np.asarray(loop, np.int32) * 2 for loop in loops], 1)
    return grid[1::2, 1::2].astype(bool)


def _centre_lines(skeleton: np.ndarray) -> list[list[tuple[int, int]]]:
    """Polylines of (x, y) pixels through a one-pixel skeleton: from every end or junction, then the closed cycles.

    A diagonal step is no edge when both pixels touch a common 4-neighbour, so a staircase is a chain, not junctions.
    """
    on = set(zip(*map(np.ndarray.tolist, np.nonzero(skeleton))))
    graph = {}
    for y, x in sorted(on):
        graph[(y, x)] = [(y + dy, x + dx) for dy, dx in _STEPS if (y + dy, x + dx) in on and
                         (dy == 0 or dx == 0 or ((y, x + dx) not in on and (y + dy, x) not in on))]
    walked, paths = set(), []

    def walk(p, q):
        path = [p, q]
        walked.add(frozenset((p, q)))
        while len(graph[q]) == 2:
            nxt = next((r for r in graph[q] if frozenset((q, r)) not in walked), None)
            if nxt is None:
                break
            walked.add(frozenset((q, nxt)))
            path.append(nxt)
            q = nxt
        return path

    for ends_only in (True, False):
        for p, neighbours in graph.items():
            if ends_only and len(neighbours) == 2:
                continue
            paths += [walk(p, q) for q in neighbours if frozenset((p, q)) not in walked]
    return [[(x, y) for y, x in path] for path in paths]


def _signed_area(points) -> float:
    pts = np.asarray(points, dtype=float)
    return 0.5 * float(np.dot(pts[:, 0], np.roll(pts[:, 1], -1)) - np.dot(np.roll(pts[:, 0], -1), pts[:, 1]))


def _simplified(raw: list, closed: bool, tolerance_mm: float, px_mm: float) -> list:
    """Douglas-Peucker (cv2.approxPolyDP) at the tolerance, in mm; a loop that would collapse keeps its raw outline.

    approxPolyDP drops the repeated end of an open curve, so a centre-line cycle is simplified as a closed curve and
    gets its start point back at the end.
    """
    out = []
    for line in raw:
        points = np.asarray(line, np.float32)
        cycle = not closed and len(points) > 3 and (points[0] == points[-1]).all()
        body = points[:-1] if cycle else points
        kept = cv2.approxPolyDP(body.reshape(-1, 1, 2), tolerance_mm / px_mm, closed or cycle).reshape(-1, 2)
        if (closed or cycle) and len(kept) < 3:
            kept = body
        if cycle:
            kept = np.vstack([kept, kept[:1]])
        out.append([[round(float(x) * px_mm, 5), round(float(y) * px_mm, 5)] for x, y in kept])
    return out


def _region(regions: list, task: str, layer_key: str, srgb: list, lab, pixels: int, raw: list, closed: bool,
            tolerance_mm: float, px_mm: float) -> None:
    paths = _simplified(raw, closed, tolerance_mm, px_mm)
    regions.append(Region(f"r{len(regions) + 1}", task, [int(v) for v in srgb], [round(float(v), 3) for v in lab], int(pixels),
                          layer_key, loops=paths if closed else [], strokes=[] if closed else paths, raw=raw))


def trace(image_rgb: np.ndarray, width_mm: float, strategy: str, *, colors=None, n_colors=None, threshold=None,
          tolerance_mm: float = 0.05, min_area_mm2: float = 0.2) -> dict:
    """Vector document of an RGB uint8 image ``width_mm`` wide, traced with ``strategy`` (see the module docstring)."""
    img = np.asarray(image_rgb)
    if img.ndim != 3 or img.shape[2] != 3 or img.dtype != np.uint8 or not img.size:
        raise VectorizeError("the image must be an RGB array of 8-bit channels")
    if strategy not in STRATEGIES:
        raise VectorizeError(f"strategy must be one of {', '.join(STRATEGIES)} (tonal is a task given to a traced region)")
    px_mm = _number(width_mm, "the work width", positive=True) / img.shape[1]
    tolerance, min_area = _number(tolerance_mm, "the tolerance"), _number(min_area_mm2, "the minimum area")
    t = None
    if strategy == "color":
        if (colors is None) == (n_colors is None):
            raise VectorizeError("give either a palette or a number of colours")
        classes, palette = _palette_classes(img, colors) if colors is not None else _kmeans_classes(img, n_colors)
        kept = range(len(palette))
    else:
        t, foreground = _binarise(img, threshold)
        classes, kept = foreground.astype(np.int32), [1]
    classes = _merge_small(classes, min_area / px_mm ** 2)
    if strategy != "color":
        mean = color.srgb8_to_lab(img[classes == 1]).mean(axis=0) if (classes == 1).any() else np.zeros(3)
        palette = {1: (color.lab_to_srgb8(mean).tolist(), mean)}
    regions: list[Region] = []
    if strategy == "line":
        foreground = (classes == 1).astype(np.uint8)
        n, comp = cv2.connectedComponents(foreground, connectivity=8)
        pixels, strokes = np.bincount(comp.ravel(), minlength=n), {}
        for path in _centre_lines(cv2.ximgproc.thinning(foreground * 255) > 0):
            strokes.setdefault(int(comp[path[0][1], path[0][0]]), []).append([[x + 0.5, y + 0.5] for x, y in path])
        for label in sorted(strokes):
            _region(regions, "line", "line", *palette[1], pixels[label], strokes[label], False, tolerance, px_mm)
    else:
        for c in kept:
            for loops in _trace_mask(classes == c):
                pixels = round(abs(sum(_signed_area(loop) for loop in loops)))
                _region(regions, strategy, f"c{c}" if strategy == "color" else strategy, *palette[c], pixels, loops, True,
                        tolerance, px_mm)
    return {"version": VERSION, "strategy": strategy, "size_mm": {"width": float(width_mm), "height": img.shape[0] * px_mm},
            "px_mm": px_mm, "image_px": {"width": img.shape[1], "height": img.shape[0]}, "tolerance_mm": tolerance,
            "min_area_mm2": min_area, "threshold": t, "regions": [asdict(r) for r in regions]}


def region_area_mm2(region: dict) -> float:
    """Area of a region's simplified outline with its holes subtracted (outer loops and holes turn opposite ways)."""
    return abs(sum(_signed_area(loop) for loop in region["loops"]))


# -- review -----------------------------------------------------------------------------------------------------
def _find(document: dict, region_id) -> dict:
    found = next((r for r in document["regions"] if r["id"] == region_id), None)
    if found is None:
        raise VectorizeError(f"there is no region {region_id!r}")
    return found


def edit(document: dict, op: dict) -> dict:
    """A new document with one operation applied; the input is not changed.

    ``{"op": "set_task", "region", "task"}``, ``{"op": "set_layer", "region", "layer_key"}``, ``{"op": "delete", "region"}``,
    ``{"op": "merge", "regions": [first, second]}`` (the union takes the first region's id, colour, task and settings
    group) and ``{"op": "set_tolerance", "tolerance_mm"}`` (every region re-simplified from its raw outline).
    """
    doc, kind = copy.deepcopy(document), op.get("op")
    if kind == "set_tolerance":
        doc["tolerance_mm"] = _number(op.get("tolerance_mm"), "the tolerance")
        for r in doc["regions"]:
            closed = bool(r["loops"])
            r["loops" if closed else "strokes"] = _simplified(r["raw"], closed, doc["tolerance_mm"], doc["px_mm"])
        return doc
    if kind == "merge":
        ids = list(op.get("regions") or [])
        if len(ids) != 2 or ids[0] == ids[1]:
            raise VectorizeError("merge needs two different regions")
        first, second = _find(doc, ids[0]), _find(doc, ids[1])
        closed = bool(first["loops"])
        if closed != bool(second["loops"]):
            raise VectorizeError("an outlined region and a centre-line region cannot be merged")
        if closed:
            w, h = doc["image_px"]["width"], doc["image_px"]["height"]
            union = _loops_mask(first["raw"], w, h) | _loops_mask(second["raw"], w, h)
            first["raw"], first["pixels"] = [loop for s in _trace_mask(union) for loop in s], int(union.sum())
        else:
            first["raw"], first["pixels"] = first["raw"] + second["raw"], first["pixels"] + second["pixels"]
        first["loops" if closed else "strokes"] = _simplified(first["raw"], closed, doc["tolerance_mm"], doc["px_mm"])
        doc["regions"].remove(second)
        return doc
    region = _find(doc, op.get("region"))
    if kind == "delete":
        doc["regions"].remove(region)
    elif kind == "set_task":
        if op.get("task") not in TASKS:
            raise VectorizeError(f"task must be one of {', '.join(TASKS)}")
        if region["strokes"] and op["task"] != "line":
            raise VectorizeError("a centre-line region has no outline to fill; it can only be engraved as a line")
        region["task"] = op["task"]
    elif kind == "set_layer":
        key = op.get("layer_key")
        if not isinstance(key, str) or not key.strip():
            raise VectorizeError("the settings group must be a non-empty name")
        region["layer_key"] = key.strip()
    else:
        raise VectorizeError(f"unknown edit operation {kind!r}")
    return doc


def _num(v: float) -> str:
    text = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def to_svg(document: dict, *, weak=frozenset()) -> str:
    """Preview in mm: one <path> per region in its source colour (even-odd fill, so holes stay open; lines as strokes).

    Regions listed in ``weak`` (inadequate evidence) are hatched and outlined with a dashed red line.
    """
    w, h = document["size_mm"]["width"], document["size_mm"]["height"]
    line_width, hatch = _num(max(document["px_mm"], 0.05)), max(w, h) / 80
    dash = f' stroke="{WEAK}" stroke-width="{line_width}" stroke-dasharray="{_num(4 * hatch)} {_num(2 * hatch)}"'
    defs, body = [], []
    for r in document["regions"]:
        rgb = "#{:02x}{:02x}{:02x}".format(*r["srgb"])
        closed = bool(r["loops"])
        d = " ".join("M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in path) + (" Z" if closed else "")
                     for path in (r["loops"] if closed else r["strokes"]))
        data = f'data-region={quoteattr(r["id"])} data-task={quoteattr(r["task"])} data-layer={quoteattr(r["layer_key"])}'
        is_weak = r["id"] in weak
        if closed:
            fill = rgb
            if is_weak:
                fill = f"url(#weak{len(defs)})"
                defs.append(f'<pattern id="weak{len(defs)}" patternUnits="userSpaceOnUse" width="{_num(hatch)}" height="{_num(hatch)}" '
                            f'patternTransform="rotate(45)"><rect width="{_num(hatch)}" height="{_num(hatch)}" fill="{rgb}"/>'
                            f'<line x1="0" y1="0" x2="0" y2="{_num(hatch)}" stroke="{WEAK}" stroke-width="{_num(hatch / 3)}"/></pattern>')
            body.append(f'<path d="{d}" fill="{fill}" fill-rule="evenodd"{dash if is_weak else ""} {data}/>')
        else:
            stroke = dash if is_weak else f' stroke="{rgb}" stroke-width="{line_width}"'
            body.append(f'<path d="{d}" fill="none"{stroke} stroke-linecap="round" stroke-linejoin="round" {data}/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_num(w)} {_num(h)}" width="{_num(w)}mm" height="{_num(h)}mm">'
            f'<defs>{"".join(defs)}</defs>{"".join(body)}</svg>')


def _has_handle(handle, node) -> bool:
    return abs(handle[0] - node[0]) > 1e-6 or abs(handle[1] - node[1]) > 1e-6


def _vertex(node) -> str:
    """LightBurn's vertex: the point, then the out-handle ``c0`` and the in-handle ``c1`` as absolute points; ``c0x1`` / ``c1x1`` is no handle."""
    out = f"c0x{node[2]:.5f}c0y{node[3]:.5f}" if _has_handle(node[2:4], node) else "c0x1"
    into = f"c1x{node[4]:.5f}c1y{node[5]:.5f}" if _has_handle(node[4:6], node) else "c1x1"
    return f"V{node[0]:.5f} {node[1]:.5f}{out}{into}"


def to_lbrn2_shapes(document: dict, layer_index_of: Mapping[str, int] | Callable[[str], int], *,
                    offset: tuple[float, float] = (0.0, 0.0)) -> list[str]:
    """LightBurn ``<Shape Type="Path">`` XML, one per region, in the format :mod:`lightburn` reads.

    Every polyline of a region is a sub-path of its shape: an outline's loops close (holes nest inside their outer
    boundary), centre-lines stay open. Straight edges (``L a b``; ``c0x1c1x1`` marks a vertex without handles), or, for a
    region that carries ``nodes`` (smooth borders, :func:`segment.smoothed`), cubic Béziers (``B a b``) through the nodes.
    ``layer_index_of`` maps a settings group (``layer_key``) to a LightBurn output colour 0..29; ``offset`` (mm) is
    written as the shape's XForm translation.
    """
    shapes = []
    for r in document["regions"]:
        try:
            index = layer_index_of[r["layer_key"]] if isinstance(layer_index_of, Mapping) else layer_index_of(r["layer_key"])
        except KeyError:
            raise VectorizeError(f"no LightBurn layer is assigned to the settings group {r['layer_key']!r}") from None
        if isinstance(index, bool) or not isinstance(index, (int, np.integer)) or index not in OUTPUT_LAYERS:
            raise VectorizeError(f"LightBurn layer {index!r} is not an output colour 00-29 (T1/T2 never carry geometry)")
        closed = bool(r["loops"])
        vertices, edges = [], []
        curves = r.get("nodes")                       # a region with smooth borders: its loops as nodes with Bézier handles
        for path in curves if curves and closed else r["loops"] if closed else r["strokes"]:
            start = len(vertices)
            vertices += path
            edges += [(start + i, start + i + 1) for i in range(len(path) - 1)]
            if closed:
                edges.append((start + len(path) - 1, start))
        if not edges:
            continue
        if curves and closed:
            verts = "".join(_vertex(v) for v in vertices)
            prims = "".join(f"{'B' if _has_handle(vertices[a][2:4], vertices[a]) or _has_handle(vertices[b][4:6], vertices[b]) else 'L'}{a} {b}"
                            for a, b in edges)
        else:
            verts = "".join(f"V{x:.5f} {y:.5f}c0x1c1x1" for x, y in vertices)
            prims = "".join(f"L{a} {b}" for a, b in edges)
        shapes.append(f'    <Shape Type="Path" CutIndex="{int(index)}">\n'
                      f'        <XForm>1 0 0 1 {offset[0]:.5f} {offset[1]:.5f}</XForm>\n'
                      f'        <VertList>{verts}</VertList>\n        <PrimList>{prims}</PrimList>\n    </Shape>\n')
    return shapes
