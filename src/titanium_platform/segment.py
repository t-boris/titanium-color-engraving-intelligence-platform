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

