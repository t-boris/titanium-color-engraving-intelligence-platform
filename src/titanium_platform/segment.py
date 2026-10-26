"""A photograph split into gapless colour regions, eyes and lips first (REQ-033, DEC-076).

Method (every step deterministic, so the same picture and settings give a byte-identical document):

1. The picture in Lab (:func:`color.srgb8_to_lab`) is smoothed edge-preservingly (bilateral filter).
2. Superpixels (``cv2.ximgproc``) follow its edges: coarse over the picture, finer in faces and finest in eyes, lips
   and areas the operator marks (:mod:`faces`); faces are a run of the algorithm of its own inside their area, and every eye, the lips
   and every marked area a run inside its own box at its own ``detail`` (``faces.DETAILS``), the finer one where two overlap. Four
   algorithms differ in the kind of picture they give (``ALGORITHMS``): SLIC patches of an even size (the default), a fine
   grid of tiny cells so that the colour classes alone decide the shapes ("tonal"), graph segmentation into flat planes
   ("planes") and SEEDS.
3. The mean Lab of every superpixel is clustered into at most ``n_colors`` colours by a seeded k-means weighted by pixels;
   superpixels of faces and of the finest areas weigh more, so that their distinct colours keep clusters of their own. Every
   superpixel then takes the colour of the nearest centre. A split given the ``centres`` of an earlier one (the same picture,
   algorithm, density and number of colours) takes them as they are instead of clustering anew, so that a change of one area
   (vector-detail-and-colour-control I-3) leaves every superpixel outside it, and so its colour, as it was.
4. A region is a 4-connected area of one colour, so two neighbours never share a colour in a fresh split. Regions under
   the minimum area merge into the neighbour of the nearest colour (smallest first); inside important areas (eyes,
   lips, marked areas) only specks smaller than a finest superpixel do.
5. The region map becomes a planar map: the pixel edges between two regions (or a region and the picture's edge) form
   arcs between junctions, the points where three or more regions meet, the picture's edge counting as one, and the
   picture's corners. Every arc is smoothed and simplified once with its ends fixed (a Gaussian along its length takes
   out the pixel steps, Douglas-Peucker at the tolerance simplifies, Chaikin rounds the corners left) and used by both
   regions it separates, so the regions cover the picture without gaps or overlaps. A closed border without junctions
   is one closed arc.
6. Every region's boundary is its loops of arcs: the outer boundary first, then its holes.

The colour editor changes a split only by merging, each time into a new document (DEC-076 of the vector work colour
editor): :func:`merge_colours` makes palette colours one, :func:`merge_regions` makes a connected set of regions one region
by dropping the arcs between them and chaining their loops anew, so the picture stays covered without gaps. After a merge
two neighbours may share a colour, a junction may be left with two arcs, and the palette's indexes and the region ids
may have gaps: they never shift, so the operator's choices keep naming the same colours and regions.

The document is a JSON-serialisable dict; coordinates are millimetres from the picture's top-left corner, y down::

    {"version": 1, "kind": "segments", "size_mm": {"width", "height"}, "px_mm", "image_px": {"width", "height"},
     "n_colors",                                          # colours asked for; the palette never has more
     "min_area_mm2", "tolerance_mm", "seed", "superpixels",  # coarse superpixels along the longer side
     "superpixel_px": {"coarse", "face", "fine"},       # "fine": at the default detail of an area
     "centres": [[L, a, b], ...],                         # the colour centres every superpixel took the nearest of
     "faces": {"searched", "found", "error"},             # found == 0: no face in the picture (or not searched)
     "important": [area, ...],                            # detected and manual areas used, in pixels (see faces)
     "palette": [{"index", "lab": [L, a, b], "srgb": [r, g, b], "pixels"}],   # lightest first; indexes may have gaps
     "regions": [{"id": "r1", "color", "lab", "srgb", "pixels", "important",
                  "loops": [[arc reference, ...], ...]}], # outer boundary first, then the holes
     "arcs": [{"id", "left", "right",                     # region ids on either side; None outside the picture
               "closed",                                  # a whole border without junctions (first point == last)
               "points": [[x, y], ...]}]}

An arc reference ``i`` walks arc ``i`` from its first point to its last with the region on its left (screen left, y
down); ``~i`` (``-i - 1``, as in TopoJSON) walks it backwards; an arc's ``id`` is its place in ``arcs``. Regions are
numbered in raster order of their first pixel; a region's ``lab`` and ``srgb`` are its colour's. :func:`neighbours` gives
the regions bordering each region. :func:`regions_as_loops` turns the arcs back into closed outlines per region for :mod:`vectorize`'s LightBurn and
SVG writers; :func:`coverage` measures gaps and overlaps of such outlines by rasterising them.

The stored arcs are the borders as traced. :func:`smoothed` gives the same document with every border in use replaced by smooth
cubic Béziers of the operator's strength in mm (:mod:`contour`, DEC-083): an arc then also has ``"nodes"``, ``[x, y, c0x, c0y, c1x,
c1y]`` as LightBurn's ``Path`` shape has them, and its ``points`` are the curve flattened. The regions, their colours and the
topology are untouched, so a colouring made on the traced split stays valid at every strength; :func:`regions_as_loops` and
:func:`to_svg` follow the curves, which is how the preview and the LightBurn file get the same geometry.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Iterable, Mapping
from xml.sax.saxutils import quoteattr

import cv2
import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon

from . import color, contour, faces
from .vectorize import _num

VERSION = 1
MIN_COLORS, MAX_COLORS = 2, 29          # LightBurn's 30 output colours less the cleaning (DEC-073); markers: the caller
MIN_AREA_MM2 = 0.5
TOLERANCE_MM = 0.08
SMOOTH_COLOR, SMOOTH_SPACE = 6.0, 2.0   # bilateral filter: Lab difference and pixel distance
SUPERPIXELS_ACROSS = 150                # coarse superpixels along the longer side of the picture, unless asked otherwise
MIN_SUPERPIXELS_ACROSS = 10
LEVEL_SCALE = (1.0, faces.DETAILS["face"], faces.DETAILS[faces.DEFAULT_DETAIL])   # superpixel size of the picture, of faces, of fine areas
MIN_SUPERPIXEL_PX = 3
SLIC_ITERATIONS = 10
ALGORITHMS = ("slic", "tonal", "planes", "seeds")   # the algorithms a split can use (feature vector-detail-and-colour-control, DEC-082)
DEFAULT_ALGORITHM = "slic"
LEVEL_SHARE = (0.0, 0.15, 0.25)         # least share of the k-means weight of faces and of the finest areas
KMEANS_RUNS, KMEANS_ITERATIONS = 4, 60
KMEANS_POINTS = 20000                   # superpixel colours are merged on a grid of this many points at most: a fine grid has 100 000
PLANES_SCALE = 150.0                    # graph segmentation: above ~500 a face collapses into one region (measured on a portrait)
PLANES_SIGMA = 0.6
ARC_SIGMA_PX = 1.2                      # an arc is low-passed along its length first: pixel steps are no detail
CHAIKIN_ROUNDS = 2
FINE_KINDS = faces.FINE_KINDS
SEAM_PX = 0.6                           # width of the preview's hairline in source pixels (see to_svg)
STEP = ((1, 0), (0, 1), (-1, 0), (0, -1))     # directions right, down, left, up; (d + 3) % 4 turns left on screen
_ONE_BIT = {1: 0, 2: 1, 4: 2, 8: 3}


class SegmentError(ValueError):
    """The picture cannot be split with these settings; the message is meant for the operator."""


class SplitError(SegmentError):
    """A region cannot be split again (:func:`split_region`); the message is meant for the operator."""


def _number(value, name: str, *, positive: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise SegmentError(f"{name} must be a number") from None
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise SegmentError(f"{name} must be a {'positive' if positive else 'non-negative'} number")
    return number


def _whole(value, name: str, low: int, high: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < low or (high is not None and value > high):
        raise SegmentError(f"{name} must be a whole number " + (f"from {low} to {high}" if high is not None else f"of at least {low}"))
    return int(value)


# -- superpixels and colours ----------------------------------------------------------------------------------------
def _levels(areas: list[dict], shape: tuple[int, int]) -> np.ndarray:
    """0 for the picture, 1 inside faces, 2 inside eyes, lips and marked areas."""
    levels = np.zeros(shape, np.uint8)
    for level, kinds in ((1, ("face",)), (2, FINE_KINDS)):
        for area in areas:
            if area["kind"] in kinds:
                levels[faces.area_mask(area, shape)] = level
    return levels


def _slic(lab: np.ndarray, size: int) -> np.ndarray:
    slic = cv2.ximgproc.createSuperpixelSLIC(lab, cv2.ximgproc.SLIC, size, 10.0)
    slic.iterate(SLIC_ITERATIONS)
    slic.enforceLabelConnectivity(25)
    return slic.getLabels()


def _bgr8(lab: np.ndarray) -> np.ndarray:
    """A Lab picture as the 8-bit BGR picture OpenCV's segmentation reads."""
    rgb = np.clip(color.lab_to_srgb8(lab.astype(np.float64)), 0, 255).astype(np.uint8)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _seeds(lab: np.ndarray, size: int) -> np.ndarray:
    """SEEDS superpixels: they follow thin dark lines and text more closely than SLIC and take less time, at the cost of
    rougher borders on soft gradients. OpenCV's SEEDS reads an 8-bit picture, so the Lab picture goes in as sRGB; a crop
    smaller than two superpixels is one."""
    h, w = lab.shape[:2]
    count = (h * w) // (size * size)
    if count < 2:
        return np.zeros((h, w), np.int32)
    seeds = cv2.ximgproc.createSuperpixelSEEDS(w, h, 3, count, 4, 2, 5, False)
    seeds.iterate(_bgr8(lab), SLIC_ITERATIONS)
    return seeds.getLabels()


def _tonal(lab: np.ndarray, size: int) -> np.ndarray:
    """A grid of cells of ``MIN_SUPERPIXEL_PX``: too small to carry a shape of their own (``size`` is not used), so the colour
    classes alone decide the shapes, which follow the shading: brows, lips, the highlight on a nose. About a hundred thousand
    cells to a 1200 px picture, which :func:`_classes` merges before it clusters."""
    slic = cv2.ximgproc.createSuperpixelSLIC(lab, cv2.ximgproc.SLIC, MIN_SUPERPIXEL_PX, 10.0)
    slic.iterate(5)
    slic.enforceLabelConnectivity(4)
    return slic.getLabels()


def _planes(lab: np.ndarray, size: int) -> np.ndarray:
    """Graph segmentation (Felzenszwalb): flat planes of one tone and ribbons along features, with no patches of an even size.
    The scale is bounded (``PLANES_SCALE``) so that a face never collapses into one region; ``size`` only sets how small a
    piece may be, so faces and eyes still get finer pieces than the rest."""
    h, w = lab.shape[:2]
    if min(h, w) < 2:
        return np.zeros((h, w), np.int32)
    graph = cv2.ximgproc.segmentation.createGraphSegmentation(PLANES_SIGMA, PLANES_SCALE, max(10, size * size // 6))
    return graph.processImage(_bgr8(lab)).astype(np.int32)


_ALGORITHM = {"slic": _slic, "tonal": _tonal, "planes": _planes, "seeds": _seeds}


def _listed(names) -> str:
    return ", ".join(names[:-1]) + " or " + names[-1]


def _superpixels(lab: np.ndarray, levels: np.ndarray, sizes: list[int], fine: list[tuple[np.ndarray, int]],
                 algorithm: str = DEFAULT_ALGORITHM) -> np.ndarray:
    """Superpixel numbers 0..n-1: superpixels of the whole picture, then of the faces inside their area, then of every fine area
    (``fine``: its pixels and its superpixel size, coarser first, so that the finer one wins where two overlap) inside its own box, by
    the chosen algorithm (``ALGORITHMS``). An area's superpixels depend only on the picture inside its box, so a change of one area
    leaves those of the others as they were."""
    make = _ALGORITHM[algorithm]
    labels = make(lab, sizes[0]).astype(np.int64)
    h, w = levels.shape
    for mask, size in [(levels == 1, sizes[1])] + fine:
        if not mask.any():
            continue
        ys, xs = np.nonzero(mask)
        pad = 2 * size
        y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + 1 + pad)
        x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + 1 + pad)
        inside = mask[y0:y1, x0:x1]
        sub = make(np.ascontiguousarray(lab[y0:y1, x0:x1]), size).astype(np.int64) + labels.max() + 1
        labels[y0:y1, x0:x1][inside] = sub[inside]
    _, numbers = np.unique(labels, return_inverse=True)
    return numbers.reshape(levels.shape)


def _kmeans(points: np.ndarray, weights: np.ndarray, k: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Weighted k-means (k-means++ starts from a seeded generator, the run of least weighted error kept): centres and
    the cluster of every point. Fewer centres when the points have fewer distinct values."""
    rng = np.random.default_rng(seed)
    k = min(k, len(np.unique(points, axis=0)))
    best = None
    for _ in range(KMEANS_RUNS):
        centres = [points[rng.choice(len(points), p=weights / weights.sum())]]
        nearest = ((points - centres[0]) ** 2).sum(axis=1)
        while len(centres) < k:
            p = weights * nearest
            if p.sum() <= 0:
                break
            centres.append(points[rng.choice(len(points), p=p / p.sum())])
            nearest = np.minimum(nearest, ((points - centres[-1]) ** 2).sum(axis=1))
        centres = np.array(centres)
        assign = None
        for _ in range(KMEANS_ITERATIONS):
            new = _nearest(points, centres)
            if assign is not None and (new == assign).all():
                break
            assign = new
            mass = np.bincount(assign, weights=weights, minlength=len(centres))
            total = np.stack([np.bincount(assign, weights=weights * points[:, d], minlength=len(centres)) for d in range(3)], axis=1)
            centres[mass > 0] = total[mass > 0] / mass[mass > 0, None]       # an emptied cluster keeps its centre
        error = float((weights * ((points - centres[assign]) ** 2).sum(axis=1)).sum())
        if best is None or error < best[0]:
            best = (error, centres, assign)
    return best[1], best[2]


def _nearest(points: np.ndarray, centres: np.ndarray) -> np.ndarray:
    """The nearest centre of every point (the lower number on a tie)."""
    return np.stack([((points - c) ** 2).sum(axis=1) for c in centres], axis=1).argmin(axis=1)


def _classes(smooth: np.ndarray, levels: np.ndarray, sizes: list[int], fine: list, n_colors: int, seed: int,
             algorithm: str = DEFAULT_ALGORITHM, centres: np.ndarray | None = None):
    """Colour class of every pixel and the Lab of every class: every superpixel takes the nearest of the centres, clustered from the
    superpixels or given (``centres`` of an earlier split)."""
    sp = _superpixels(smooth, levels, sizes, fine, algorithm)
    n = int(sp.max()) + 1
    flat = sp.ravel()
    pixels = np.bincount(flat, minlength=n).astype(float)
    mean = np.stack([np.bincount(flat, weights=smooth[..., c].ravel(), minlength=n) for c in range(3)], axis=1) / pixels[:, None]
    if centres is not None:
        return _nearest(mean, centres)[sp].astype(np.int32), centres
    level = np.zeros(n, np.uint8)
    level[flat] = levels.ravel()
    weights = pixels.copy()
    for lv in (1, 2):                   # each finer level weighs at least its share of all the weight so far
        own, rest = weights[level == lv].sum(), weights[level < lv].sum()
        if own > 0 and LEVEL_SHARE[lv] > 0:
            weights[level == lv] *= max(1.0, LEVEL_SHARE[lv] * rest / ((1 - LEVEL_SHARE[lv]) * own))
    # superpixels of the same colour to half a Lab unit (no visible difference) are clustered as one weighted point; a fine grid
    # has too many of them, and a coarser step (at most 2 units) keeps the clustering to a couple of seconds
    step = 0.5
    while True:
        points, same = np.unique(np.round(mean / step) * step, axis=0, return_inverse=True)
        if len(points) <= KMEANS_POINTS or step >= 2.0:
            break
        step += 0.5
    same = same.ravel()
    centres, _ = _kmeans(points, np.bincount(same, weights=weights, minlength=len(points)), n_colors, seed)
    return _nearest(mean, centres)[sp].astype(np.int32), centres


def _components(classes: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Region of every pixel (4-connected areas of one class, numbered in raster order of their first pixel) and the
    class of every region."""
    region = np.zeros(classes.shape, np.int64)
    count, of_class = 0, []
    for c in range(k):
        n, labels = cv2.connectedComponents((classes == c).astype(np.uint8), connectivity=4)
        inside = labels > 0
        region[inside] = labels[inside] - 1 + count
        count += n - 1
        of_class += [c] * (n - 1)
    _, first = np.unique(region.ravel(), return_index=True)
    rank = np.empty(count, np.int64)
    rank[np.argsort(first, kind="stable")] = np.arange(count)
    renumbered = np.empty(count, np.int32)
    renumbered[rank] = of_class
    return rank[region], renumbered


def _merge_small(region: np.ndarray, of_class: np.ndarray, class_lab: np.ndarray, min_px: float, keep: np.ndarray) -> np.ndarray:
    """New class of every region: each region under ``min_px`` pixels (not kept) takes the class of the neighbour of the
    nearest colour, smallest first (ties: the longer shared border, the larger area, the lower number); a merged group
    still too small merges on."""
    n = len(of_class)
    area = np.bincount(region.ravel(), minlength=n).astype(np.int64)
    small = np.flatnonzero((area < min_px) & ~keep)
    if not len(small):
        return of_class
    a = np.concatenate([region[:, :-1].ravel(), region[:-1, :].ravel()])
    b = np.concatenate([region[:, 1:].ravel(), region[1:, :].ravel()])
    differ = a != b
    codes, lengths = np.unique(np.minimum(a, b)[differ] * n + np.maximum(a, b)[differ], return_counts=True)
    border: list[dict] = [{} for _ in range(n)]
    for code, length in zip(codes.tolist(), lengths.tolist()):
        i, j = divmod(code, n)
        border[i][j] = border[j][i] = length
    distance = np.sqrt(((class_lab[:, None, :] - class_lab[None, :, :]) ** 2).sum(axis=2))
    cls, area, keep = of_class.tolist(), area.tolist(), keep.tolist()
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in sorted(small.tolist(), key=lambda i: (area[i], i)):
        r = find(i)
        if area[r] >= min_px or keep[r]:
            continue
        shared: dict[int, int] = {}
        for j, length in border[r].items():
            if (root := find(j)) != r:
                shared[root] = shared.get(root, 0) + length
        if not shared:
            continue
        target = min(shared, key=lambda j: (distance[cls[r], cls[j]], -shared[j], -area[j], j))
        parent[r] = target
        area[target] += area[r]
        keep[target] = keep[target] or keep[r]
        for j, length in border[r].items():
            border[target][j] = border[target].get(j, 0) + length
    return np.array([cls[find(i)] for i in range(n)], np.int32)


# -- planar map ---------------------------------------------------------------------------------------------------------
def _planar_map(region: np.ndarray):
    """Arcs of the pixel-edge boundaries between regions and the loops of every region.

    Returns (arcs, loops): an arc is (pixel corners walked, numbered ``y * (width + 1) + x``; the region left and right
    of it, -1 outside the picture; its first and last direction; closed); ``loops[r]`` lists region r's loops as signed
    arc references, outer boundary first.
    At a vertex where a region touches itself diagonally its boundary turns left, as 4-connected regions require.
    """
    h, w = region.shape
    cols = w + 1
    p = np.full((h + 2, w + 2), -1, np.int64)
    p[1:-1, 1:-1] = region
    across = p[:-1, 1:-1] != p[1:, 1:-1]        # (h+1, w): edge from vertex (x, y) to (x+1, y)
    down = p[1:-1, :-1] != p[1:-1, 1:]          # (h, w+1): edge from vertex (x, y) to (x, y+1)
    bits = np.zeros((h + 1, w + 1), np.uint8)
    bits[:, :w] |= across.astype(np.uint8)
    bits[:h, :] |= down.astype(np.uint8) << 1
    bits[:, 1:] |= across.astype(np.uint8) << 2
    bits[1:, :] |= down.astype(np.uint8) << 3
    degree = np.zeros(bits.shape, np.uint8)
    for d in range(4):
        degree += (bits >> d) & 1
    junction = degree >= 3
    junction[0, 0] = junction[0, w] = junction[h, 0] = junction[h, w] = True
    flat_bits, is_junction = bits.ravel().tolist(), junction.ravel().tolist()
    step = (1, cols, -1, -cols)
    seen = bytearray(2 * (h + 1) * cols)        # 2 * vertex + 0: edge to the right of it, + 1: edge below it

    def edge(v: int, d: int) -> int:
        return 2 * v if d == 0 else 2 * v + 1 if d == 1 else 2 * (v - 1) if d == 2 else 2 * (v - cols) + 1

    pad = p.ravel().tolist()

    def sides(v: int, d: int) -> tuple[int, int]:
        """Regions left and right of the edge leaving vertex v in direction d."""
        y, x = divmod(v, cols)
        dx, dy = STEP[d]
        mx, my = 2 * x + dx, 2 * y + dy                  # doubled midpoint of the edge; left normal is (dy, -dx)
        lx, ly, rx, ry = mx + dy, my - dx, mx - dy, my + dx
        return pad[((ly + 1) // 2) * (w + 2) + (lx + 1) // 2], pad[((ry + 1) // 2) * (w + 2) + (rx + 1) // 2]

    arcs = []

    def walk(v0: int, d0: int) -> None:
        vertices, v, d = [v0], v0, d0
        while True:
            seen[edge(v, d)] = 1
            v += step[d]
            vertices.append(v)
            if is_junction[v] or v == v0:
                break
            d = _ONE_BIT[flat_bits[v] & ~(1 << ((d + 2) % 4))]
        left, right = sides(v0, d0)
        arcs.append((vertices, left, right, d0, d, not is_junction[v0]))

    for v0 in np.flatnonzero(junction & (degree > 0)).tolist():
        for d0 in range(4):
            if flat_bits[v0] >> d0 & 1 and not seen[edge(v0, d0)]:
                walk(v0, d0)
    boundary = np.zeros((h + 1, cols, 2), bool)
    boundary[:, :w, 0], boundary[:h, :, 1] = across, down
    left_over = np.flatnonzero(boundary.ravel() & (np.frombuffer(bytes(seen), np.uint8) == 0))
    for v0 in np.unique(left_over // 2).tolist():       # borders without junctions: closed cycles, from their first vertex
        for d0 in range(4):
            if flat_bits[v0] >> d0 & 1 and not seen[edge(v0, d0)]:
                walk(v0, d0)

    n_regions = int(region.max()) + 1
    directed: list[list[int]] = [[] for _ in range(n_regions)]
    for i, (_, left, right, _, _, _) in enumerate(arcs):
        if left >= 0:
            directed[left].append(i)
        if right >= 0:
            directed[right].append(~i)

    def ends(ref: int) -> tuple[int, int, int, int]:
        """Start vertex, end vertex, first and last direction of a signed arc reference."""
        vertices, _, _, first, last, _ = arcs[ref if ref >= 0 else ~ref]
        if ref >= 0:
            return vertices[0], vertices[-1], first, last
        return vertices[-1], vertices[0], (last + 2) % 4, (first + 2) % 4

    doubled = []                                # twice the signed area each arc adds to a loop walked forward
    for vertices, *_ in arcs:
        y, x = np.divmod(np.asarray(vertices, np.int64), cols)
        doubled.append(int((x[:-1] * y[1:] - x[1:] * y[:-1]).sum()))
    loops = []
    for refs in directed:
        starts: dict[int, list[int]] = {}
        for ref in refs:
            starts.setdefault(ends(ref)[0], []).append(ref)
        used, found = set(), []
        for first in sorted(refs, key=lambda r: r if r >= 0 else ~r):
            if first in used:
                continue
            loop, ref = [first], first
            used.add(first)
            while True:
                _, end, _, last = ends(ref)
                options = [c for c in starts[end] if c not in used or c == first]
                ref = min(options, key=lambda c: ((ends(c)[2] - last + 1) % 4, c))   # left turn, straight, right turn
                if ref == first:
                    break
                loop.append(ref)
                used.add(ref)
            area = sum(doubled[r] if r >= 0 else -doubled[~r] for r in loop)
            found.append((area >= 0, loop))     # walked with the region on the left, the outer boundary has area < 0
        loops.append([loop for _, loop in sorted(found, key=lambda f: f[0])])
    return arcs, loops


def _chaikin(points: np.ndarray, closed: bool) -> np.ndarray:
    """Chaikin's corner cutting; an open polyline keeps its ends and the direction in which it leaves them."""
    for _ in range(CHAIKIN_ROUNDS):
        if closed:
            nxt = np.roll(points, -1, axis=0)
            points = np.stack([0.75 * points + 0.25 * nxt, 0.25 * points + 0.75 * nxt], axis=1).reshape(-1, 2)
        elif len(points) > 2:
            a, b = points[:-1], points[1:]
            cut = np.stack([0.75 * a + 0.25 * b, 0.25 * a + 0.75 * b], axis=1).reshape(-1, 2)
            points = np.vstack([points[:1], cut[1:-1], points[-1:]])
    return points


_KERNEL = np.exp(-0.5 * (np.arange(-math.ceil(3 * ARC_SIGMA_PX), math.ceil(3 * ARC_SIGMA_PX) + 1) / ARC_SIGMA_PX) ** 2)
_KERNEL /= _KERNEL.sum()


def _low_pass(points: np.ndarray, closed: bool) -> np.ndarray:
    """The path (one point per pixel edge) Gaussian-filtered along its length; an open path keeps its ends."""
    r, n = len(_KERNEL) // 2, len(points)
    if closed:
        padded = points[np.arange(-r, n + r) % n]
    else:                                       # reflected through the ends, so that the filter keeps them in place
        k = np.minimum(np.arange(r, 0, -1), n - 1)
        padded = np.vstack([2 * points[0] - points[k], points, 2 * points[-1] - points[n - 1 - k[::-1]]])
    out = np.stack([np.convolve(padded[:, c], _KERNEL, mode="valid") for c in range(2)], axis=1)
    if not closed:
        out[0], out[-1] = points[0], points[-1]
    return out


def _arc_points(vertices: list[int], cols: int, closed: bool, tolerance_px: float, px_mm: float) -> list[list[float]]:
    """An arc's pixel-corner path smoothed and simplified once, in mm; the ends of an open arc stay where they are."""
    y, x = np.divmod(np.asarray(vertices, np.int64), cols)
    path = np.stack([x, y], axis=1).astype(np.float64)
    line = _low_pass(path[:-1] if closed else path, closed)
    if closed:
        kept = _douglas_peucker(line, tolerance_px, True)
        smooth = _chaikin(kept if len(kept) >= 3 else line, True)
        smooth = np.vstack([smooth, smooth[:1]])
    else:
        if (path[0] == path[-1]).all():         # leaves a junction and comes back to it: simplified in thirds
            cuts = [0, len(line) // 3, 2 * len(line) // 3, len(line) - 1]
            kept = np.vstack([_douglas_peucker(line[a:b + 1], tolerance_px, False)[:-1] for a, b in zip(cuts, cuts[1:])] + [line[-1:]])
        else:
            kept = _douglas_peucker(line, tolerance_px, False)
            if len(kept) == 2 and len(line) > 2:    # keep a curved arc curved: a thin region between two arcs never vanishes
                chord = line[-1] - line[0]
                off = np.abs(chord[0] * (line[:, 1] - line[0, 1]) - chord[1] * (line[:, 0] - line[0, 0]))
                if off.max() > 1e-9:
                    kept = line[[0, int(off.argmax()), -1]]
        kept[0], kept[-1] = path[0], path[-1]
        smooth = _chaikin(kept, False)
    return [[round(float(px) * px_mm, 5), round(float(py) * px_mm, 5)] for px, py in smooth]


def _douglas_peucker(points: np.ndarray, tolerance_px: float, closed: bool) -> np.ndarray:
    return cv2.approxPolyDP(points.astype(np.float32).reshape(-1, 1, 2), tolerance_px, closed).reshape(-1, 2).astype(np.float64)


def _palette(classes: np.ndarray, lab: np.ndarray, k: int) -> tuple[np.ndarray, list[dict]]:
    """The colours still used, each the mean source Lab of its pixels, lightest first, and the new index of every class."""
    used = np.unique(classes)
    flat = classes.ravel()
    count = np.bincount(flat, minlength=k)[used]
    mean = np.stack([np.bincount(flat, weights=lab[..., c].ravel().astype(np.float64), minlength=k)[used] for c in range(3)],
                    axis=1) / count[:, None]
    order = np.lexsort((mean[:, 2], mean[:, 1], -mean[:, 0]))
    index = np.zeros(k, np.int32)
    index[used[order]] = np.arange(len(used))
    return index, [{"index": i, "lab": [round(float(v), 3) for v in mean[j]], "srgb": color.lab_to_srgb8(mean[j]).tolist(),
                    "pixels": int(count[j])} for i, j in enumerate(order)]


def segment(image_rgb, width_mm: float, n_colors: int, *, important: Iterable = (), use_faces: bool = True,
            min_area_mm2: float = MIN_AREA_MM2, tolerance_mm: float = TOLERANCE_MM, seed: int = 0,
            superpixels: int = SUPERPIXELS_ACROSS, algorithm: str = DEFAULT_ALGORITHM, centres: Iterable | None = None) -> dict:
    """Split an RGB uint8 picture ``width_mm`` wide into at most ``n_colors`` gapless colour regions (module docstring).

    ``important`` lists areas the operator marked (or detected areas handed back to keep them, see
    :func:`faces.check_area`), in pixels of this picture; ``use_faces`` adds the faces, eyes and lips found in it.
    ``superpixels`` is the number of coarse superpixels along the longer side: fewer follow only the larger edges.
    ``algorithm`` makes them: ``slic`` (the default), ``tonal``, ``planes`` or ``seeds`` (``ALGORITHMS``). ``centres`` are the colour
    centres of an earlier split of the same picture with the same algorithm, superpixels and number of colours, taken instead of
    clustering anew (step 3).
    """
    img = np.asarray(image_rgb)
    if img.ndim != 3 or img.shape[2] != 3 or img.dtype != np.uint8 or not img.size:
        raise SegmentError("the picture must be an RGB array of 8-bit channels")
    n_colors = _whole(n_colors, "the number of colours", MIN_COLORS, MAX_COLORS)
    seed = _whole(seed, "the seed", 0)
    superpixels = _whole(superpixels, "the number of superpixels across the picture", MIN_SUPERPIXELS_ACROSS)
    if algorithm not in ALGORITHMS:
        raise SegmentError("the algorithm must be " + _listed(ALGORITHMS))
    if centres is not None:
        centres = np.asarray(centres, np.float64)
        if centres.ndim != 2 or centres.shape[1] != 3 or not 1 <= len(centres) <= n_colors or not np.isfinite(centres).all():
            raise SegmentError("the colour centres must be at most n_colors finite Lab triples")
    h, w = img.shape[:2]
    px_mm = _number(width_mm, "the work width", positive=True) / w
    min_area, tolerance = _number(min_area_mm2, "the minimum area"), _number(tolerance_mm, "the tolerance")
    try:
        manual = [faces.check_area(a) for a in important or ()]
    except (TypeError, ValueError) as exc:
        raise SegmentError(str(exc)) from None
    search = faces.important_areas(img) if use_faces else faces.FaceSearch([], 0)
    areas = search.areas + manual
    levels = _levels(areas, (h, w))
    coarse = max(MIN_SUPERPIXEL_PX, round(max(h, w) / superpixels))
    sizes = [max(MIN_SUPERPIXEL_PX, round(coarse * scale)) for scale in LEVEL_SCALE]
    runs = sorted(((faces.area_mask(a, (h, w)), max(MIN_SUPERPIXEL_PX, round(coarse * faces.DETAILS[a.get("detail") or faces.DEFAULT_DETAIL])))
                   for a in areas if a["kind"] in FINE_KINDS), key=lambda run: -run[1])        # coarser first: the finer wins an overlap
    speck = np.zeros((h, w))                       # a finest superpixel's area at every pixel of a fine area: smaller specks merge
    for mask, size in runs:
        speck[mask] = size ** 2

    lab = color.srgb8_to_lab(img).astype(np.float32)
    smooth = cv2.bilateralFilter(lab, 0, SMOOTH_COLOR, SMOOTH_SPACE)
    classes, class_lab = _classes(smooth, levels, sizes, runs, n_colors, seed, algorithm, centres)
    region, of_class = _components(classes, len(class_lab))
    fine = (levels == 2).ravel()
    area = np.bincount(region.ravel(), minlength=len(of_class))
    inside = np.bincount(region.ravel(), weights=fine, minlength=len(of_class))
    least = np.bincount(region.ravel(), weights=speck.ravel(), minlength=len(of_class)) / np.maximum(inside, 1)
    keep = (2 * inside >= area) & (area >= np.minimum(min_area / px_mm ** 2, least))
    classes = _merge_small(region, of_class, class_lab, min_area / px_mm ** 2, keep)[region]
    index, palette = _palette(classes, lab, len(class_lab))
    region, of_class = _components(index[classes], len(palette))
    area = np.bincount(region.ravel(), minlength=len(of_class))
    inside = np.bincount(region.ravel(), weights=fine, minlength=len(of_class))

    arcs, loops = _planar_map(region)
    name = [f"r{i + 1}" for i in range(len(of_class))]
    regions = [{"id": name[i], "color": int(of_class[i]), "lab": palette[of_class[i]]["lab"], "srgb": palette[of_class[i]]["srgb"],
                "pixels": int(area[i]), "important": bool(2 * inside[i] >= area[i]), "loops": loops[i]} for i in range(len(of_class))]
    arc_list = [{"id": i, "left": name[left] if left >= 0 else None, "right": name[right] if right >= 0 else None, "closed": closed,
                 "points": _arc_points(vertices, w + 1, closed, tolerance / px_mm, px_mm)}
                for i, (vertices, left, right, _, _, closed) in enumerate(arcs)]
    return {"version": VERSION, "kind": "segments", "size_mm": {"width": float(width_mm), "height": h * px_mm}, "px_mm": px_mm,
            "image_px": {"width": w, "height": h}, "n_colors": n_colors, "min_area_mm2": min_area, "tolerance_mm": tolerance,
            "seed": seed, "superpixels": superpixels, "algorithm": algorithm, "superpixel_px": dict(zip(("coarse", "face", "fine"), sizes)),
            "centres": [[float(v) for v in c] for c in class_lab],
            "faces": {"searched": bool(use_faces), "found": search.faces, "error": search.error},
            "important": areas, "palette": palette, "regions": regions, "arcs": arc_list}


# -- for the rest of the application --------------------------------------------------------------------------------
def _loop_points(document: dict, loop: list[int]) -> list[list[float]]:
    """A loop's closed outline (the start not repeated). It starts inside an arc, never at a junction, so that a hole
    touching its outer boundary at a junction is still found inside it by a point test (LightBurn's reader does one);
    a loop of straight arcs only gets the midpoint of its first arc as its start."""
    arcs = document["arcs"]
    ring, spans = [], []
    for ref in loop:
        points = arcs[ref if ref >= 0 else ~ref]["points"]
        spans.append((len(ring), len(points)))
        ring += (points if ref >= 0 else points[::-1])[:-1]
    offset, size = next(((offset, size) for offset, size in spans if size >= 3), (None, 2))
    if offset is None:
        (x0, y0), (x1, y1) = ring[0], ring[1 % len(ring)]
        ring.insert(1, [round((x0 + x1) / 2, 5), round((y0 + y1) / 2, 5)])
        start = 1
    else:
        start = offset + (size - 1) // 2
    return ring[start:] + ring[:start]


def smoothed(document: dict, sigma_mm: float) -> dict:
    """The document with every border a region uses replaced by its smooth Bézier form (``nodes``) and the points along it; a strength of
    0 is the document as traced. The ends of an arc do not move, so both regions of a border and all arcs of a junction still agree."""
    sigma = _number(sigma_mm, "the smoothing")
    if sigma == 0:
        return document
    used = {ref if ref >= 0 else ~ref for r in document["regions"] for loop in r["loops"] for ref in loop}
    arcs = []
    for arc in document["arcs"]:
        if arc["id"] not in used:
            arcs.append(arc)
            continue
        nodes = [[round(v, 5) for v in node] for node in contour.smooth_arc(arc["points"], arc["closed"], sigma)]
        arcs.append({**arc, "nodes": nodes, "points": contour.flatten(nodes)})
    return {**document, "arcs": arcs, "smoothing_mm": sigma}


def scaled(document: dict, factor: float) -> dict:
    """The split engraved ``factor`` times as large (feature work-size-and-splitting-a-region-again, DEC-001): a copy in which every arc point,
    the size, the millimetres per pixel, the minimum area and the tolerance are scaled; the regions, their ids, the palette, the picture's
    pixels and the important areas (in pixels) are as they were. A split of the same picture at the new width with the same settings would
    give the same raster (its minimum area is a share of the picture, the superpixels work in pixels), so the scale is exact. The document
    is the one as traced, without smoothing (:func:`smoothed` is applied on reading)."""
    factor = _number(factor, "the scale factor", positive=True)
    doc = copy.deepcopy(document)
    for arc in doc["arcs"]:
        arc["points"] = [[round(x * factor, 5), round(y * factor, 5)] for x, y in arc["points"]]
        arc.pop("nodes", None)
    doc.pop("smoothing_mm", None)
    doc["size_mm"] = {"width": document["size_mm"]["width"] * factor, "height": document["size_mm"]["height"] * factor}
    doc["px_mm"] = document["px_mm"] * factor
    doc["min_area_mm2"] = document["min_area_mm2"] * factor ** 2
    doc["tolerance_mm"] = document["tolerance_mm"] * factor
    return doc


def _oriented(nodes: list[list[float]], backwards: bool) -> list[list[float]]:
    """The nodes of an arc walked backwards: the order reverses and every node's in- and out-handle swap."""
    return [[n[0], n[1], n[4], n[5], n[2], n[3]] for n in reversed(nodes)] if backwards else nodes


def _split_node(a: list[float], b: list[float]) -> list[list[float]]:
    """The nodes a and b with one more node in the middle of the curve between them (de Casteljau at 0.5); a and b keep their points."""
    p0, c0, c1, p1 = np.array(a[0:2]), np.array(a[2:4]), np.array(b[4:6]), np.array(b[0:2])
    q0, q1, q2 = (p0 + c0) / 2, (c0 + c1) / 2, (c1 + p1) / 2
    r0, r1 = (q0 + q1) / 2, (q1 + q2) / 2
    m = (r0 + r1) / 2
    r = lambda v: [round(float(x), 5) for x in v]
    return [[a[0], a[1], *r(q0), a[4], a[5]], [*r(m), *r(r1), *r(r0)], [b[0], b[1], b[2], b[3], *r(q2)]]


def _loop_nodes(document: dict, loop: list[int]) -> list[list[float]]:
    """A loop's closed outline as nodes (the last node joins the first by a curve of its own), starting inside an arc like
    :func:`_loop_points`. A node at a junction has the in-handle of the arc before it and the out-handle of the arc after it."""
    runs = [_oriented(document["arcs"][ref if ref >= 0 else ~ref]["nodes"], ref < 0) for ref in loop]
    ring, spans = [], []
    for k, run in enumerate(runs):
        body = [list(n) for n in run[:-1]]
        body[0][4:6] = runs[k - 1][-1][4:6]
        spans.append((len(ring), len(body)))
        ring += body
    offset, size = next(((offset, size) for offset, size in spans if size >= 2), (None, 1))
    if offset is None:                                 # every arc is a single curve: split the first one in two
        a, b, rest = ring[0], ring[1 % len(ring)], ring[2:]
        first, mid, last = _split_node(a, b)
        return [mid, last, *rest, first] if len(ring) > 1 else [first, mid]
    start = offset + size // 2
    return ring[start:] + ring[:start]


def regions_as_loops(document: dict) -> list[dict]:
    """Every region as :mod:`vectorize` keeps a traced colour region: closed ``loops`` in mm (outer boundary, then holes)
    built from the shared arcs, so two neighbours are identical along their border. The settings group (``layer_key``)
    is the colour, ``c<index>``. ``{"regions": regions_as_loops(doc)}`` goes to :func:`vectorize.to_lbrn2_shapes`."""
    curved = any("nodes" in arc for arc in document["arcs"])
    return [{"id": r["id"], "task": "color", "color": r["color"], "srgb": r["srgb"], "lab": r["lab"], "pixels": r["pixels"],
             "important": r["important"], "layer_key": f"c{r['color']}", "loops": [_loop_points(document, loop) for loop in r["loops"]],
             "strokes": [], **({"nodes": [_loop_nodes(document, loop) for loop in r["loops"]]} if curved else {})}
            for r in document["regions"]]


def _rgb(value) -> str:
    try:
        r, g, b = value
    except (TypeError, ValueError):
        r = g = b = None
    if not all(isinstance(v, (int, np.integer)) and not isinstance(v, bool) and 0 <= v <= 255 for v in (r, g, b)):
        raise SegmentError("a preview colour must be three whole sRGB channels 0..255")
    return "#{:02x}{:02x}{:02x}".format(int(r), int(g), int(b))


def _curve_path(ring: list[list[float]]) -> str:
    """An SVG sub-path through a closed ring of nodes: one cubic curve from every node to the next, the last back to the first."""
    parts = [f"M{_num(ring[0][0])} {_num(ring[0][1])}"]
    for a, b in zip(ring, ring[1:] + ring[:1]):
        parts.append(f"C{_num(a[2])} {_num(a[3])} {_num(b[4])} {_num(b[5])} {_num(b[0])} {_num(b[1])}")
    return " ".join(parts) + " Z"


def _arc_path(arc: dict) -> str:
    """An SVG sub-path along one arc, the same curves (or points) the loops of its regions take there."""
    if "nodes" in arc:
        n = arc["nodes"]
        return " ".join([f"M{_num(n[0][0])} {_num(n[0][1])}"] + [f"C{_num(a[2])} {_num(a[3])} {_num(b[4])} {_num(b[5])} {_num(b[0])} {_num(b[1])}"
                                                               for a, b in zip(n, n[1:])])
    return "M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in arc["points"])


def _borders(document: dict) -> str:
    """Every border the regions use, once: a hidden group of paths, each with ``data-sides`` - the regions whose loops take it (one at the
    edge of the picture). The outline of any set of regions is then the borders with a region of the set on one side only."""
    sides: dict[int, dict[str, None]] = {}
    for r in document["regions"]:
        for loop in r["loops"]:
            for ref in loop:
                sides.setdefault(ref if ref >= 0 else ~ref, {})[r["id"]] = None
    arcs = document["arcs"]
    return ('<g class="vw-borders" display="none">'
            + "".join(f'<path d="{_arc_path(arcs[i])}" data-sides={quoteattr(" ".join(sides[i]))}/>' for i in sorted(sides)) + "</g>")


def to_svg(document: dict, colours: Mapping[int, list] | None = None, *, borders: bool = False) -> str:
    """Preview in mm: one even-odd ``<path>`` per region (holes stay open) filled with its source colour, or with
    ``colours[color index]`` (sRGB) where given, e.g. the titanium colour assigned to that colour; with ``borders``, also every border
    once (:func:`_borders`), for the editor to outline a selection as one shape.

    Each path has a hairline of its own colour: a browser anti-aliases two touching paths separately and lets the
    background show along their common border, a seam the geometry does not have.
    """
    w, h = document["size_mm"]["width"], document["size_mm"]["height"]
    fills = {int(k): _rgb(v) for k, v in (colours or {}).items()}
    hairline = _num(SEAM_PX * document["px_mm"])
    body = []
    for r in regions_as_loops(document):
        if "nodes" in r:
            d = " ".join(_curve_path(ring) for ring in r["nodes"])
        else:
            d = " ".join("M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in loop) + " Z" for loop in r["loops"])
        fill = fills.get(r["color"]) or _rgb(r["srgb"])
        body.append(f'<path d="{d}" fill="{fill}" fill-rule="evenodd" stroke="{fill}" stroke-width="{hairline}" stroke-linejoin="round" '
                    f'data-region={quoteattr(r["id"])} data-color="{r["color"]}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_num(w)} {_num(h)}" width="{_num(w)}mm" height="{_num(h)}mm">'
            f'{"".join(body)}{_borders(document) if borders else ""}</svg>')


def coverage(regions: Iterable[list], width_mm: float, height_mm: float, samples_per_mm: float) -> dict:
    """Shares of the picture that no region covers and that two or more regions cover.

    Each region is a list of closed loops in mm (as :func:`regions_as_loops` gives them, or a LightBurn outline with its
    holes); it covers the sample points (centres of a ``samples_per_mm`` grid) inside it by the even-odd rule.
    """
    cols, rows = max(1, round(width_mm * samples_per_mm)), max(1, round(height_mm * samples_per_mm))
    scale = (cols / width_mm, rows / height_mm)
    count = np.zeros((rows, cols), np.int32)
    for loops in regions:
        rings = [np.asarray(loop, np.float64) * scale for loop in loops if len(loop) >= 3]
        if not rings:
            continue
        a = np.vstack(rings)
        b = np.vstack([np.roll(ring, -1, axis=0) for ring in rings])
        first = np.clip(np.ceil(np.minimum(a[:, 1], b[:, 1]) - 0.5), 0, rows).astype(np.int64)   # rows j: lo <= j + 0.5 < hi
        stop = np.clip(np.ceil(np.maximum(a[:, 1], b[:, 1]) - 0.5), 0, rows).astype(np.int64)
        n = stop - first
        if not n.sum():
            continue
        edge = np.repeat(np.arange(len(a)), n)
        row = first[edge] + np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
        x = a[edge, 0] + (row + 0.5 - a[edge, 1]) * (b[edge, 0] - a[edge, 0]) / (b[edge, 1] - a[edge, 1])
        col = np.clip(np.floor(x - 0.5) + 1, 0, cols).astype(np.int64)        # the first sample centre right of the crossing
        r0, r1 = int(row.min()), int(row.max()) + 1
        toggles = np.bincount((row - r0) * (cols + 1) + col, minlength=(r1 - r0) * (cols + 1)).reshape(r1 - r0, cols + 1)
        count[r0:r1] += (np.cumsum(toggles, axis=1)[:, :cols] % 2).astype(np.int32)
    return {"uncovered": float((count == 0).mean()), "overlap": float((count >= 2).mean())}


# -- merging (the colour editor, DEC-076) ----------------------------------------------------------------------------------
def neighbours(document: dict) -> dict[str, set[str]]:
    """The regions each region borders along an arc; a touch at a corner only is no border, the picture's edge no region."""
    out: dict[str, set[str]] = {r["id"]: set() for r in document["regions"]}
    for arc in document["arcs"]:
        left, right = arc["left"], arc["right"]
        if left is not None and right is not None and left != right:
            out[left].add(right)
            out[right].add(left)
    return out


def merge_colours(document: dict, indexes: Iterable[int]) -> tuple[dict, int]:
    """A new document in which two or more palette colours are one, and its index; the input is not changed.

    The colour keeps the index of its member with most pixels (the lower index on a tie), so the other indexes stay as
    they were and the palette has a gap; its Lab is the pixel-weighted mean of the members', its pixels their sum. The
    palette stays lightest first; every region of a member takes the colour. Region ids and geometry are unchanged.
    """
    chosen = set(indexes)
    members = [p for p in document["palette"] if p["index"] in chosen]
    if len(chosen) < 2 or len(members) != len(chosen):
        raise RuntimeError("a merge of colours needs two or more colours of the palette")
    keeper = max(members, key=lambda p: (p["pixels"], -p["index"]))["index"]
    mean = np.average([p["lab"] for p in members], axis=0, weights=[max(p["pixels"], 1) for p in members])
    lab = [round(float(v), 3) for v in mean]
    srgb = color.lab_to_srgb8(np.asarray(lab)).tolist()
    doc = copy.deepcopy(document)
    doc["palette"] = [p for p in doc["palette"] if p["index"] not in chosen or p["index"] == keeper]
    for p in doc["palette"]:
        if p["index"] == keeper:
            p.update(lab=lab, srgb=srgb, pixels=sum(m["pixels"] for m in members))
    doc["palette"].sort(key=lambda p: (-p["lab"][0], p["lab"][1], p["lab"][2]))      # lightest first, as :func:`_palette`
    for r in doc["regions"]:
        if r["color"] in chosen:
            r.update(color=keeper, lab=lab, srgb=srgb)
    return doc, keeper


def merge_regions(document: dict, ids: Iterable[str]) -> tuple[dict, str]:
    """A new document in which a connected set of regions is one region, and its id; the input is not changed.

    The arcs between two members are dropped. The boundary is chained again from the members' own loops: after an arc
    comes the next arc of its loop, and while that one lies between two members the walk crosses it into the other
    member's loop at the same point, so pinch points and holes come out exactly as the members had them. The loops are
    ordered outer boundary first by their signed area (outer < 0, y down; exactly one), the arcs left keep their order
    and are numbered again (an arc's id is its place), every region's references follow, and a side that named a member
    names the region. A junction left with two arcs stays. The region keeps the id, place, colour, Lab and sRGB of its
    member with most pixels (the first in the document on a tie); its pixels are the members' sum, it is important when
    the important members hold half of them or more, and its palette colour takes over the other members' pixels; a
    colour left without a region leaves the palette.
    """
    chosen = set(ids)
    if len(chosen) < 2 or sum(r["id"] in chosen for r in document["regions"]) != len(chosen):
        raise RuntimeError("a merge of regions needs two or more regions of the document")
    doc, keepers = merge_groups(document, [chosen])
    return doc, keepers[0]


def merge_groups(document: dict, groups: Iterable[Iterable[str]], *, strict: bool = True) -> tuple[dict, list[str | None]]:
    """A new document in which each of several disjoint connected sets of regions is one region, as :func:`merge_regions` makes one,
    in a single pass (one copy of the document however many sets there are), and the id each set kept (in the order of ``groups``).
    With ``strict`` off, a set whose loops do not chain into one region (a set that is not connected) stays as it was and its id is
    None; with it on, that raises like :func:`merge_regions`."""
    by_id = {r["id"]: r for r in document["regions"]}
    sets = [set(g) for g in groups]
    owner: dict[str, int] = {}
    for n, members in enumerate(sets):
        if len(members) < 2 or any(i not in by_id for i in members):
            raise RuntimeError("a merge of regions needs two or more regions of the document")
        for i in members:
            if i in owner:
                raise RuntimeError("a region can be merged into one region only")
            owner[i] = n
    arcs = document["arcs"]
    interior = {i for i, arc in enumerate(arcs) if arc["left"] in owner and arc["right"] in owner and owner[arc["left"]] == owner[arc["right"]]}
    keepers: list[str | None] = [None] * len(sets)
    loops: dict[int, list[list[int]]] = {}
    for n, members in enumerate(sets):
        rows = [r for r in document["regions"] if r["id"] in members]
        try:
            loops[n] = _merged_loops(document, rows, interior)
        except RuntimeError:
            if strict:
                raise
            interior -= {i for i in interior if owner[arcs[i]["left"]] == n}
            for i in members:
                del owner[i]
            continue
        keepers[n] = max(rows, key=lambda r: r["pixels"])["id"]          # max keeps the first of the largest
    keeper_of = {i: keepers[n] for i, n in owner.items()}
    doc = copy.deepcopy(document)
    renumber, kept_arcs = {}, []
    for i, arc in enumerate(doc["arcs"]):
        if i in interior:
            continue
        renumber[i] = len(kept_arcs)
        arc["id"] = len(kept_arcs)
        arc["left"], arc["right"] = (keeper_of.get(side, side) for side in (arc["left"], arc["right"]))
        kept_arcs.append(arc)
    doc["arcs"] = kept_arcs
    palette = {p["index"]: p for p in doc["palette"]}
    totals: dict[int, list[int]] = {}
    for r in document["regions"]:
        if r["id"] in owner:
            total = totals.setdefault(owner[r["id"]], [0, 0])
            total[0] += r["pixels"]
            total[1] += r["pixels"] if r["important"] else 0
    kept = []
    for r in doc["regions"]:
        n = owner.get(r["id"])
        if n is not None and r["id"] != keepers[n]:
            palette[r["color"]]["pixels"] -= r["pixels"]
            palette[by_id[keepers[n]]["color"]]["pixels"] += r["pixels"]
            continue
        if n is not None:
            r.update(pixels=totals[n][0], important=2 * totals[n][1] >= totals[n][0], loops=loops[n])
        r["loops"] = [[renumber[ref] if ref >= 0 else ~renumber[~ref] for ref in loop] for loop in r["loops"]]
        kept.append(r)
    doc["regions"] = kept
    used = {r["color"] for r in kept}
    doc["palette"] = [p for p in doc["palette"] if p["index"] in used]
    return doc, keepers


def _arc_of(ref: int) -> int:
    return ref if ref >= 0 else ~ref


def _merged_loops(document: dict, members: list[dict], interior: set[int]) -> list[list[int]]:
    """The loops of a merged region in the document's arc references, outer boundary first (see :func:`merge_regions`)."""
    succ = {}
    for r in members:
        for loop in r["loops"]:
            succ.update({ref: loop[(k + 1) % len(loop)] for k, ref in enumerate(loop)})

    def after(ref: int) -> int:
        n = succ[ref]
        for _ in range(len(succ) + 1):
            if _arc_of(n) not in interior:
                return n
            if ~n not in succ:
                break
            n = succ[~n]                    # across the dropped arc: on in the other member's loop, at the same point
        raise RuntimeError("the loops of the regions to merge do not chain")

    used, found = set(), []
    for first in sorted((ref for ref in succ if _arc_of(ref) not in interior), key=_arc_of):
        if first in used:
            continue
        loop, ref = [first], first
        used.add(first)
        while (ref := after(ref)) != first:
            if ref in used:
                raise RuntimeError("the loops of the regions to merge do not chain")
            loop.append(ref)
            used.add(ref)
        found.append(loop)
    arcs = document["arcs"]
    doubled = [sum(_doubled_area(arcs[_arc_of(ref)]["points"]) * (1 if ref >= 0 else -1) for ref in loop) for loop in found]
    if sum(area < 0 for area in doubled) != 1:
        raise RuntimeError("the merged region does not have exactly one outer boundary")
    return [loop for area, loop in sorted(zip(doubled, found), key=lambda f: f[0] >= 0)]     # stable: the outer boundary first


def _doubled_area(points: list) -> float:
    """Twice the signed area an arc adds to a loop walked forward: the shoelace over its points (y down)."""
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:]))



# ======================================================================================================================
# A region split again (feature work-size-and-splitting-a-region-again, REQ-002, DEC-084)
# ======================================================================================================================
# One region's pixels are clustered into a few colours at the finest superpixel size and the connected parts become regions of their
# own. The region's outer border is kept point for point: its arcs are only cut where a new inner border meets them, so every neighbour
# keeps its geometry and the picture stays watertight. The new borders inside are traced from the pixels as the split's arcs are.
SPLIT_AGAIN_MAX = 8                     # colours a region can be split into
SPLIT_MIN_DE = 2.0                      # colours of a region closer than this (Lab distance, about the least visible) are one: noise is no colour
SPLIT_MIN_SPECKS = 4                    # a part is at least this many finest superpixels
ROUND_MM = 2e-5                         # points are kept to 5 decimals of a mm: a point this near the outline is on it
SPLIT_INSET_PX = 0.05                   # the new borders inside keep this far (in pixels) inside the region's outline
SPLIT_STRAY_SHARE = 0.02                # pixels of a region's outline apart from its main piece: more than this share means a wrong outline
SNAP_PX = 3.0                           # a mask corner farther than this from the region's outline means the outline does not match
CUT_EPS_MM = 1e-4                       # cuts closer than this along the outline are one cut


def split_region(document: dict, raster: np.ndarray, image_rgb, rid: str, n_colors: int, *, seed: int = 0) -> tuple[dict, list[str]]:
    """A new document in which region ``rid`` is split into finer regions by colour and the ids of its parts, the largest first.

    ``raster`` is the split on the picture's pixels (:func:`photo_zones.labels`: the index of the region at each pixel, in the document's
    order), ``image_rgb`` the working picture (``image_px``). The region's pixels are clustered into ``n_colors`` colours (2 to
    ``SPLIT_AGAIN_MAX``) at the finest superpixel size; parts under half an even share of the region (at most the split's minimum area,
    at least a few finest superpixels) merge into the neighbouring part of the nearest colour. The largest part keeps the region's id and place; the parts of its colour keep the region's palette colour, each other
    colour becomes one new palette colour (the mean Lab of its pixels) with a new index, so the palette grows by ``n_colors - 1`` at most;
    the other parts get new ids. Every other region is as it was: the arcs of the region's border are cut where the new
    borders inside meet them and otherwise untouched, so a neighbour's border is the same curve. The input is not changed. A region that is
    one colour at that detail, or whose outline does not match its pixels, is refused with :class:`SplitError`; a wrong picture, raster or
    number of colours with :class:`SegmentError`.
    """
    img = np.asarray(image_rgb)
    rows, cols = document["image_px"]["height"], document["image_px"]["width"]
    if img.ndim != 3 or img.shape[:2] != (rows, cols) or img.dtype != np.uint8 or raster.shape != (rows, cols):
        raise SegmentError("the picture and the raster must be those of the split")
    n_colors = _whole(n_colors, "the number of colours", 2, SPLIT_AGAIN_MAX)
    regions = document["regions"]
    index = next((i for i, r in enumerate(regions) if r["id"] == rid), None)
    if index is None:
        raise SplitError(f"there is no region {rid!r}")
    mask = raster == index
    if not mask.any():
        raise SplitError("the region covers no pixel of the picture")
    px_mm = float(document["px_mm"])
    region = regions[index]
    rings = [_Ring(document, loop) for loop in region["loops"]]
    outline = Polygon(rings[0].points, [ring.points for ring in rings[1:]])
    outline = outline if outline.is_valid else outline.buffer(0)
    mask = _whole_mask(mask, [Polygon(ring.points) for ring in rings[1:]], px_mm)
    parts, part_class, class_lab = _parts(document, img, mask, n_colors, seed)
    m = len(part_class)
    sub_arcs, sub_loops = _planar_map(parts)
    junction_mm = _junctions([arc for arc in sub_arcs if arc[1] < 0 or arc[2] < 0], cols + 1, px_mm)

    # where each mask corner on the region's border lies along its rings
    placed: dict[int, tuple[int, float, list[float]]] = {}            # corner vertex -> (ring, param, point)
    for v, (x, y) in junction_mm.items():
        best = min(((r, *ring.project(x, y)) for r, ring in enumerate(rings)), key=lambda found: found[2])
        if best[2] > SNAP_PX * px_mm:
            raise SplitError("the region cannot be split again: its outline does not match its pixels")
        placed[v] = (best[0], best[1], best[3])

    # boundary arcs of the parts, oriented with the part on the left: the chain of corners along each ring, or a whole ring
    chain: dict[int, dict[int, tuple[int, int]]] = {r: {} for r in range(len(rings))}     # ring -> start corner -> (end corner, sub arc)
    whole: dict[int, int] = {}                                                         # sub arc of a whole ring -> ring
    boundary_of: dict[int, tuple[int, int, int]] = {}                                  # sub arc -> (part, start corner, end corner)
    for i, (vertices, left, right, _, _, closed) in enumerate(sub_arcs):
        if left >= 0 and right >= 0:
            continue
        part = left if left >= 0 else right
        if closed:
            x, y = divmod(vertices[0], cols + 1)[::-1]
            r = min(range(len(rings)), key=lambda r: rings[r].project(x * px_mm, y * px_mm)[1])
            if rings[r].project(x * px_mm, y * px_mm)[1] > SNAP_PX * px_mm:
                raise SplitError("the region cannot be split again: its outline does not match its pixels")
            whole[i] = r
            boundary_of[i] = (part, -1, -1)
            continue
        start, end = (vertices[0], vertices[-1]) if left == part else (vertices[-1], vertices[0])
        if placed[start][0] != placed[end][0]:
            raise SplitError("the region cannot be split again: its outline does not match its pixels")
        chain[placed[start][0]][start] = (end, i)
        boundary_of[i] = (part, start, end)
    if set(whole.values()) & {r for r, links in chain.items() if links} or len(set(whole.values())) + sum(1 for links in chain.values() if links) != len(rings):
        raise SplitError("the region cannot be split again: its outline does not match its pixels")

    # cut every ring at its corners in their order along it, pieces between consecutive cuts; new arcs for the cut pieces
    doc = copy.deepcopy(document)
    old_arcs = doc["arcs"]
    new_arcs: list[dict] = []
    renumber: dict[int, list] = {}             # old arc index -> forward refs of the pieces that replace it, in its own direction
    part_ids = [rid] + [f"r{1 + max(int(r['id'][1:]) for r in regions) + k}" for k in range(m - 1)]
    piece_refs: dict[tuple[int, int], list[tuple]] = {}               # (start corner, end corner) -> ("old", ref) | ("new", arc) in ring order
    side_of: dict[int, str] = {}                                      # old arc of the region left whole -> the part's id on its side
    for r, ring in enumerate(rings):
        links = chain[r]
        if not links:
            continue
        first = min(links, key=lambda v: placed[v][1])
        order, v = [], first
        while True:
            order.append(v)
            v = links[v][0]
            if v == first:
                break
        if len(order) != len(links):
            raise SplitError("the region cannot be split again: its outline does not match its pixels")
        params = []
        for v in order:
            s = placed[v][1]
            params.append(s if not params else max(s, params[-1] + CUT_EPS_MM))
        cuts = ring.cuts(params)
        for k, v in enumerate(order):
            end, sub = links[v]
            part = boundary_of[sub][0]
            piece_refs[(v, end)] = ring.piece(cuts[k], cuts[(k + 1) % len(order)], k == len(order) - 1, old_arcs, new_arcs, renumber,
                                              part_ids[part], side_of)
    for sub, r in whole.items():
        for ref in rings[r].loop:
            side_of[_arc_of(ref)] = part_ids[boundary_of[sub][0]]
    for a, pieces in renumber.items():          # forward refs in the old arc's own direction
        pieces.sort(key=lambda piece: piece[0], reverse=not pieces[0][2])
        renumber[a] = [ref for _, ref, _ in pieces]

    # arcs of the other regions and the region's arcs left whole, renumbered; then the new borders inside the region
    kept: dict[int, int] = {}
    for i, arc in enumerate(old_arcs):
        if i in renumber:
            continue
        copy_arc = dict(arc)
        if i in side_of:
            copy_arc["left"], copy_arc["right"] = (side_of[i] if side == rid else side for side in (arc["left"], arc["right"]))
        kept[i] = len(new_arcs)
        new_arcs.append(copy_arc)
    inner: dict[int, int] = {}
    tolerance_px = float(document["tolerance_mm"]) / px_mm
    within, inside = outline.buffer(ROUND_MM), outline.buffer(-SPLIT_INSET_PX * px_mm)
    shapely.prepare(within)
    for i, (vertices, left, right, _, _, closed) in enumerate(sub_arcs):
        if i in boundary_of:
            continue
        ends = [] if closed else [list(placed[v][2]) if v in placed else None for v in (vertices[0], vertices[-1])]
        for tolerance in (tolerance_px, 0.0):          # simplified as every border; where that cuts across the outline, dense
            points = _arc_points(vertices, cols + 1, closed, tolerance, px_mm)
            for at, end in zip((0, -1), ends):
                if end is not None:
                    points[at] = end
            points = _kept_inside(points, closed, within, inside, SPLIT_INSET_PX * px_mm)
            if within.contains(LineString(points)):
                break
        inner[i] = len(new_arcs)
        new_arcs.append({"id": None, "left": part_ids[left], "right": part_ids[right], "closed": closed, "points": points})
    for i, arc in enumerate(new_arcs):
        arc["id"] = i
    doc["arcs"] = new_arcs

    def rewrite(ref: int) -> list[int]:
        a = _arc_of(ref)
        if a in kept:
            return [kept[a] if ref >= 0 else ~kept[a]]
        forward = renumber[a]
        return forward if ref >= 0 else [~x for x in reversed(forward)]

    for other in doc["regions"]:
        if other["id"] != rid:
            other["loops"] = [[x for ref in loop for x in rewrite(ref)] for loop in other["loops"]]
    part_loops = []
    for part in range(m):
        loops = []
        for loop in sub_loops[part]:
            refs: list[int] = []
            for ref in loop:
                i = _arc_of(ref)
                if i in inner:
                    refs.append(inner[i] if ref >= 0 else ~inner[i])
                elif i in whole:
                    refs += [x for old in rings[whole[i]].loop for x in rewrite(old)]
                else:
                    _, start, end = boundary_of[i]
                    for kind, x in piece_refs[(start, end)]:
                        refs += [x] if kind == "new" else rewrite(x)
            loops.append(refs)
        part_loops.append(loops)

    # the regions: the largest part in the region's place; the colour of its parts is the region's, each other colour a new one
    sizes = _shares(np.bincount(parts[parts >= 0], minlength=m), region["pixels"])
    next_index = 1 + max(p["index"] for p in doc["palette"])
    colour_of = {part_class[0]: (region["color"], region["lab"], region["srgb"])}
    for c in part_class:
        if c not in colour_of:
            lab = [round(float(v), 3) for v in class_lab[c]]
            colour_of[c] = (next_index, lab, color.lab_to_srgb8(np.asarray(class_lab[c])).tolist())
            doc["palette"].append({"index": next_index, "lab": lab, "srgb": colour_of[c][2], "pixels": 0})
            next_index += 1
    palette = {p["index"]: p for p in doc["palette"]}
    palette[region["color"]]["pixels"] -= region["pixels"]
    made = []
    for part in range(m):
        colour, lab, srgb = colour_of[part_class[part]]
        palette[colour]["pixels"] += int(sizes[part])
        made.append({"id": part_ids[part], "color": colour, "lab": lab, "srgb": srgb, "pixels": int(sizes[part]), "important": region["important"],
                     "loops": part_loops[part]})
    doc["regions"] = [made[0] if r["id"] == rid else r for r in doc["regions"]] + made[1:]
    for part in made:                      # never a part whose outline crosses itself: refused rather than saved (a loop that
        loops = [_loop_points(doc, loop) for loop in part["loops"]]      # touches itself at a corner, as the split's own do, is fine)
        reason = "" if all(len(loop) >= 4 for loop in loops) else "Too few points"
        reason = reason or shapely.is_valid_reason(Polygon(loops[0], loops[1:]))
        if reason != "Valid Geometry" and not reason.startswith("Ring Self-intersection"):
            raise SplitError("the region cannot be split cleanly into so many colours: try fewer")
    return doc, part_ids


def _whole_mask(mask: np.ndarray, holes: list, px_mm: float) -> np.ndarray:
    """The region's pixels as one piece with the holes of its outline only (``holes``: the polygons of its inner rings). The pixels drawn
    from the outline of a region (and of its neighbours) can leave a pixel out inside it, pinch off a pixel of the outside where the
    outline passes between two pixel centres, or touch only at a corner. A hole of the pixels whose middle is in none of ``holes`` is
    filled; pieces that touch at a corner are joined by a pixel next to both; pieces still apart are left to the outline when they are a
    few pixels (SPLIT_STRAY_SHARE), and refused when more."""
    mask = mask.copy()
    count, background = cv2.connectedComponents((~mask).astype(np.uint8), connectivity=4)
    if count > 2:
        edge = set(np.unique(np.concatenate([background[0], background[-1], background[:, 0], background[:, -1]])).tolist())
        depth = cv2.distanceTransform((~mask).astype(np.uint8), cv2.DIST_L2, 3)
        for k in set(range(1, count)) - edge:
            hole = background == k
            y, x = np.unravel_index(int(np.argmax(np.where(hole, depth, -1))), hole.shape)
            middle = Point((x + 0.5) * px_mm, (y + 0.5) * px_mm)
            if not any(polygon.contains(middle) for polygon in holes):
                mask |= hole
    for _ in range(3):
        count, pieces = cv2.connectedComponents(mask.astype(np.uint8), connectivity=4)
        if count <= 2:
            return mask
        padded = np.pad(pieces, 1)
        around = np.stack([padded[:-2, 1:-1], padded[2:, 1:-1], padded[1:-1, :-2], padded[1:-1, 2:]])
        biggest = np.where(around > 0, around, np.iinfo(np.int32).min).max(axis=0)
        smallest = np.where(around > 0, around, np.iinfo(np.int32).max).min(axis=0)
        bridge = ~mask & (biggest > 0) & (smallest < np.iinfo(np.int32).max) & (biggest != smallest)
        if not bridge.any():
            break
        mask |= bridge
    count, pieces = cv2.connectedComponents(mask.astype(np.uint8), connectivity=4)
    if count > 2:
        sizes = np.bincount(pieces.ravel(), minlength=count)[1:]
        if sizes.sum() - sizes.max() > SPLIT_STRAY_SHARE * sizes.sum():
            raise SplitError("the region cannot be split again: its outline does not match its pixels")
        mask = pieces == 1 + int(sizes.argmax())
    return mask


def _parts(document: dict, img: np.ndarray, mask: np.ndarray, n_colors: int, seed: int) -> tuple[np.ndarray, list[int], dict[int, list[float]]]:
    """The region's pixels split into parts: a raster of the picture with the part (0..m-1, the largest first) of every pixel of the
    region and -1 elsewhere, the colour of each part, and the mean Lab of each colour's pixels. Superpixels at the finest size inside the region's box, clustered into
    ``n_colors`` colours; the connected parts under the split's minimum area merge into the neighbouring part of the nearest colour,
    an island of the region (no neighbouring part) stays whatever its size."""
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    size = max(MIN_SUPERPIXEL_PX, round(document["superpixel_px"]["coarse"] * faces.DETAILS["finest"]))
    pad = 2 * size
    y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + 1 + pad)
    x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + 1 + pad)
    inside = mask[y0:y1, x0:x1]
    lab = color.srgb8_to_lab(np.ascontiguousarray(img[y0:y1, x0:x1])).astype(np.float32)
    smooth = cv2.bilateralFilter(lab, 0, SMOOTH_COLOR, SMOOTH_SPACE)
    make = _ALGORITHM[document.get("algorithm", DEFAULT_ALGORITHM)]
    _, sp = np.unique(make(np.ascontiguousarray(smooth), size).astype(np.int64)[inside], return_inverse=True)
    sp = sp.ravel()
    n = int(sp.max()) + 1
    pixels = np.bincount(sp, minlength=n).astype(float)
    mean = np.stack([np.bincount(sp, weights=smooth[inside][:, c].astype(np.float64), minlength=n) for c in range(3)], axis=1) / pixels[:, None]
    # the colours come from the region's inside, a pixel in from its border: the border pixels of the raster drawn from the smoothed
    # outline can be the neighbours' and must make no colour of their own, nor a strip of another colour along the outline. A border
    # pixel takes the colour of the nearest pixel inside (each pixel by itself when the region is too thin to have an inside).
    core_box = cv2.erode(inside.astype(np.uint8), np.ones((3, 3), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0).astype(bool)
    core = core_box[inside]
    sample = np.bincount(sp[core], minlength=n).astype(float) if core.any() else pixels
    chosen = sample > 0
    centres, assign = _kmeans(mean[chosen], sample[chosen], n_colors, seed)
    centres = _distinct(centres, np.bincount(assign, weights=sample[chosen], minlength=len(centres)))
    k = len(centres)
    full = np.full(inside.shape, k, np.int32)
    full[inside] = _nearest(mean, centres)[sp]
    if core.any():
        _, nearest = cv2.distanceTransformWithLabels((~core_box).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
        class_of = np.zeros(int(nearest.max()) + 1, np.int32)
        class_of[nearest[core_box]] = full[core_box]
        rim = inside & ~core_box
        full[rim] = class_of[nearest[rim]]
    if k < 2 or len(np.unique(full[inside])) < 2:
        raise SplitError("the region is one colour at this detail: there is nothing to split")
    region, of_class = _components(full, k + 1)
    outside = of_class == k
    a = np.concatenate([region[:, :-1].ravel(), region[:-1, :].ravel()])
    b = np.concatenate([region[:, 1:].ravel(), region[1:, :].ravel()])
    touching = (a != b) & ~outside[a] & ~outside[b]
    has_neighbour = np.zeros(len(of_class), bool)
    has_neighbour[a[touching]] = has_neighbour[b[touching]] = True
    keep = outside | ~has_neighbour
    class_lab = np.vstack([centres, [[1e6, 0.0, 0.0]]])            # the outside is never the nearest colour
    # a part is at least half an even share of the region (at most the split's minimum area) and a few finest superpixels
    least = max(SPLIT_MIN_SPECKS * size ** 2, min(document["min_area_mm2"] / document["px_mm"] ** 2, int(mask.sum()) / (2 * n_colors)))
    merged = _merge_small(region, of_class, class_lab, least, keep)[region]
    merged[~inside] = k
    region, of_class = _components(merged, k + 1)
    numbers = [i for i in range(len(of_class)) if of_class[i] != k]
    if len(numbers) < 2:
        raise SplitError("the region's colours lie in specks smaller than the smallest region: there is nothing to split")
    area = np.bincount(region.ravel(), minlength=len(of_class))
    numbers.sort(key=lambda i: (-area[i], i))
    renumber = np.full(len(of_class), -1, np.int32)
    renumber[numbers] = np.arange(len(numbers))
    crop = renumber[region]
    parts = np.full((h, w), -1, np.int32)
    parts[y0:y1, x0:x1] = crop
    part_class = [int(of_class[i]) for i in numbers]
    flat, labs = merged.ravel(), lab.reshape(-1, 3).astype(np.float64)
    means = {c: [float(v) for v in labs[flat == c].mean(axis=0)] for c in set(part_class)}
    return parts, part_class, means


def _shares(counts: np.ndarray, total: int) -> np.ndarray:
    """``counts`` scaled to add up to ``total`` (the region's own pixels: the raster drawn from its outline has a few more or fewer), each
    part at least one pixel, the rounding left on the largest."""
    scaled = np.maximum(1, np.round(counts * total / max(int(counts.sum()), 1))).astype(np.int64)
    scaled[int(np.argmax(counts))] += total - int(scaled.sum())
    return scaled


def _distinct(centres: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """The colour centres with those closer than SPLIT_MIN_DE joined, the heaviest pair first (the joined one is their weighted mean)."""
    centres, weights = [np.asarray(c, np.float64) for c in centres], [float(w) for w in weights]
    while len(centres) > 1:
        pairs = [(float(np.sqrt(((centres[a] - centres[b]) ** 2).sum())), a, b) for a in range(len(centres)) for b in range(a + 1, len(centres))]
        distance, a, b = min(pairs)
        if distance >= SPLIT_MIN_DE:
            break
        total = weights[a] + weights[b] or 1.0
        centres[a] = (centres[a] * weights[a] + centres[b] * weights[b]) / total
        weights[a] = total
        del centres[b], weights[b]
    return np.array(centres)


def _kept_inside(points: list, closed: bool, within, inside, inset_mm: float) -> list:
    """A new border inside a region kept inside it. ``within`` is the region's outline (a hair larger, so a border on it is within):
    a border that stays within it is as traced. Where the border traced from the pixels strays beyond it (a pixel corner lies up to
    half a pixel past the smoothed outline), each point outside ``inside``, the outline shrunk a hair, moves to the nearest point of its
    edge, and a step that still leaves the outline follows that edge, when that is a short way (never round the region). The ends of an
    open border stay where they are, on the outline."""
    if len(points) < 2 or inside.is_empty or within.contains(LineString(points)):
        return points
    edges = [ring for polygon in getattr(inside, "geoms", [inside]) for ring in [polygon.exterior, *polygon.interiors]]
    last = len(points) - 1
    moved = [list(q) if (not closed and k in (0, last)) or inside.contains(Point(q)) else _on_edge(edges, q) for k, q in enumerate(points)]
    if closed:
        moved[-1] = moved[0]
    out = [moved[0]]
    for k in range(1, len(moved)):
        a, b = out[-1], moved[k]
        if not within.contains(LineString([a, b])):
            start = _on_edge(edges, a) if not closed and k == 1 else a          # from the junction on the outline: onto the edge first
            target = _on_edge(edges, b) if not closed and k == last else b
            path = _along(edges, start, target)
            if path and LineString([start, *path]).length <= 2 * math.dist(a, b) + 4 * inset_mm:
                out += ([start] if start is not a else []) + path
                if out[-1] != b:
                    out.append(b)
                continue
        out.append(b)
    kept = [[round(float(x), 5), round(float(y), 5)] for x, y in out]
    return [q for k, q in enumerate(kept) if k == 0 or q != kept[k - 1]]


def _on_edge(edges: list, point) -> list[float]:
    """The point of the nearest of ``edges`` (rings) nearest to ``point``."""
    p = Point(point)
    ring = min(edges, key=lambda r: r.distance(p))
    q = ring.interpolate(ring.project(p))
    return [q.x, q.y]


def _along(edges: list, a, b) -> list[list[float]]:
    """The path from ``a`` to ``b`` along the nearest ring of ``edges``, the shorter way round: its corners between them and ``b``'s
    place on it (nothing when ``a`` and ``b`` are one point or on different rings)."""
    pa, pb = Point(a), Point(b)
    ring = min(edges, key=lambda r: r.distance(pa) + r.distance(pb))
    if ring.distance(pa) > 1e-6 or ring.distance(pb) > 1e-6 or pa.distance(pb) < 1e-9:
        return []
    coords = np.asarray(ring.coords)[:-1]
    s = np.array([ring.project(Point(c)) for c in coords])
    length = ring.length
    sa, sb = ring.project(pa), ring.project(pb)
    forward = (sb - sa) % length
    if forward <= length - forward:
        ahead = (s - sa) % length
        chosen = [k for k in np.argsort(ahead) if 0 < ahead[k] < forward]
    else:
        behind = (sa - s) % length
        chosen = [k for k in np.argsort(behind) if 0 < behind[k] < length - forward]
    end = ring.interpolate(sb)
    return [[float(x), float(y)] for x, y in coords[chosen]] + [[end.x, end.y]]


def _junctions(arcs: list, cols: int, px_mm: float) -> dict[int, tuple[float, float]]:
    """The corners where the open arcs of a planar map end, in mm."""
    out = {}
    for vertices, _, _, _, _, closed in arcs:
        if not closed:
            for v in (vertices[0], vertices[-1]):
                y, x = divmod(v, cols)
                out[v] = (x * px_mm, y * px_mm)
    return out


class _Ring:
    """One loop of a region as a closed polyline in mm with the region on the left: where each of its arcs lies along it (``spans``), the
    nearest point of it to a given point (``project``), and the pieces of it between cuts (``piece``), made of its arcs cut at them."""

    def __init__(self, document: dict, loop: list[int]):
        self.loop = loop
        arcs = document["arcs"]
        points: list[list[float]] = []
        self.spans = []                          # (ref, first index, last index) of each arc's points in the ring
        for ref in loop:
            p = arcs[_arc_of(ref)]["points"]
            p = p if ref >= 0 else p[::-1]
            if points:
                points.extend(p[1:])
                self.spans.append((ref, len(points) - len(p), len(points) - 1))
            else:
                points.extend(p)
                self.spans.append((ref, 0, len(points) - 1))
        self.points = np.asarray(points, np.float64)
        steps = np.sqrt(((self.points[1:] - self.points[:-1]) ** 2).sum(axis=1))
        self.s = np.concatenate([[0.0], np.cumsum(steps)])
        self.length = float(self.s[-1])

    def project(self, x: float, y: float) -> tuple[float, float, list[float]]:
        """The param along the ring, the distance and the point of the ring nearest to (x, y)."""
        a, b = self.points[:-1], self.points[1:]
        d = b - a
        q = np.array([x, y]) - a
        t = np.clip((q * d).sum(axis=1) / np.maximum((d * d).sum(axis=1), 1e-18), 0.0, 1.0)
        near = a + t[:, None] * d
        dist = np.sqrt(((near - [x, y]) ** 2).sum(axis=1))
        i = int(dist.argmin())
        s = float(self.s[i] + t[i] * (self.s[i + 1] - self.s[i]))
        return s, float(dist[i]), [round(float(v), 5) for v in near[i]]

    def cuts(self, params: list[float]) -> list[tuple[int, float, list[float]]]:
        """Each cut as (span, param, point): a cut within CUT_EPS_MM of an arc's end is at that end (the start of the next span)."""
        out = []
        for s in params:
            s = min(max(s, 0.0), self.length)
            j = max(0, min(len(self.spans) - 1, int(np.searchsorted(self.s, s, side="right") - 1)))
            while j < len(self.spans) - 1 and s > self.s[self.spans[j][2]]:
                j += 1
            while j > 0 and s < self.s[self.spans[j][1]]:
                j -= 1
            ref, first, last = self.spans[j]
            if s >= self.s[last] - CUT_EPS_MM:               # at the arc's end: the start of the next arc
                j = (j + 1) % len(self.spans)
                out.append((j, float(self.s[self.spans[j][1]]) if j else 0.0, [float(v) for v in self.points[self.spans[j][1]]]))
            elif s <= self.s[first] + CUT_EPS_MM:
                out.append((j, float(self.s[first]), [float(v) for v in self.points[first]]))
            else:
                i = int(np.searchsorted(self.s, s, side="right") - 1)
                t = (s - self.s[i]) / max(self.s[i + 1] - self.s[i], 1e-18)
                point = self.points[i] + t * (self.points[i + 1] - self.points[i])
                out.append((j, s, [round(float(v), 5) for v in point]))
        return out

    def piece(self, start: tuple, end: tuple, wrap: bool, old_arcs: list, new_arcs: list, renumber: dict, part_id: str, side_of: dict) -> list[tuple]:
        """What the ring is from cut ``start`` forward to cut ``end``, with the part on the left: ``("old", ref)`` for an arc left whole
        (``side_of`` notes the part on its side) and ``("new", index)`` for a new arc appended to ``new_arcs`` (noted in ``renumber`` as
        forward refs in the old arc's own direction). Nothing between two cuts at one point; the last piece (``wrap``) goes round."""
        (ja, sa, pa), (jb, sb, pb) = start, end
        n = len(self.spans)
        if not wrap and (ja, sa) == (jb, sb):
            return []
        if ja == jb and sa < sb and not wrap:
            return [x for x in [self._portion(ja, sa, sb, pa, pb, old_arcs, new_arcs, renumber, part_id, side_of)] if x]
        refs = [self._portion(ja, sa, None, pa, None, old_arcs, new_arcs, renumber, part_id, side_of)]
        j = (ja + 1) % n
        while j != jb:
            ref = self.spans[j][0]
            side_of[_arc_of(ref)] = part_id
            refs.append(("old", ref))
            j = (j + 1) % n
        refs.append(self._portion(jb, None, sb, None, pb, old_arcs, new_arcs, renumber, part_id, side_of))
        return [x for x in refs if x]

    def _portion(self, j: int, sa, sb, pa, pb, old_arcs: list, new_arcs: list, renumber: dict, part_id: str, side_of: dict):
        """Span ``j`` from ``sa`` (its start when None) to ``sb`` (its end when None) in ring direction: ``("old", ref)`` when that is the
        whole arc, ``("new", index)`` for a new arc, None when it is nothing (a cut at the span's start, or at its end)."""
        ref, first, last = self.spans[j]
        a = _arc_of(ref)
        s_first, s_last = float(self.s[first]), float(self.s[last])
        at_start = sa is None or sa <= s_first + CUT_EPS_MM
        at_end = sb is None or sb >= s_last - CUT_EPS_MM
        if at_start and at_end:
            side_of[a] = part_id
            return ("old", ref)
        if (sb is not None and sb <= s_first + CUT_EPS_MM) or (sa is not None and sa >= s_last - CUT_EPS_MM):
            return None
        lo = first if at_start else int(np.searchsorted(self.s, sa, side="right"))
        hi = last if at_end else int(np.searchsorted(self.s, sb, side="left") - 1)
        points = ([] if at_start else [pa]) + [[float(v) for v in q] for q in self.points[lo:hi + 1]] + ([] if at_end else [pb])
        if len(points) < 2:
            points = [pa if pa is not None else points[0], pb if pb is not None else points[-1]]
        old = old_arcs[a]
        other = old["right"] if ref >= 0 else old["left"]
        new_arcs.append({"id": None, "left": part_id, "right": other, "closed": False, "points": points})
        index = len(new_arcs) - 1
        # where the piece starts along the ring: the pieces of one arc are put in the arc's order once all are made (the last piece
        # of a ring wraps round to the start of the arc the first cut lies on, so they are not made in that order)
        renumber.setdefault(a, []).append((s_first if at_start else sa, index if ref >= 0 else ~index, ref >= 0))
        return ("new", index)
