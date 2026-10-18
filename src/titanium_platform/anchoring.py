"""Register an unmarked finished work to its photograph from element anchors (REQ-024, DEC-048, DEC-049).

The old route for work without markers (``registration.register_geometry``) needs three whole shapes that match by
Hu moments. It fails when a frame clips the large shapes, when most paths are not recognised, or when the drawing is
a mirror image of the photograph. This module works the other way round, and it needs no frame:

1. the whole drawing is searched in a small copy of the photograph over every pose (mirror, four right angles with
   small offsets, the plate's scale from 0.3 to 1.1 of the photograph, every shift): the file outlines, each sample
   with its tangent direction, are correlated with a direction-aware proximity map of the photograph's edges
   (``global_search``). A drawing of parallel strokes cannot match itself turned by a right angle;
2. the best pose of every orientation is polished at a middle resolution; the orientation is refused when the best
   does not clearly beat the second;
3. every file element is searched on its own in a small window around where the current transform predicts it; only an
   element with a close, distinctive match becomes an *anchor*;
4. a homography is fitted to the anchors only (RANSAC) and every element is predicted from it; steps 3-4 repeat with
   a shrinking window;
5. only now is the frame looked for: along every side of the plate rectangle (its size is known from the file) the
   inner edge of a dark frame is found as the dominant line where the dark run ends (``window_from_frame``). A side
   without such an edge is the plate edge itself; a photograph without a frame hides nothing.

Nothing is guessed: a registration that is not supported by enough spread-out anchors is refused (``None``) with the
reason in ``diagnostics``, and the operator places four corners (REQ-013). A hidden element is *inferred*, never
measured. All thresholds are in millimetres and scale with the photograph.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import cv2
import numpy as np

from .registration import Registration

TARGET_PX_PER_MM = 10.0          # working resolution of the edge map
CAP_MM = 0.8                     # an outline farther than this from any photo edge counts as "no edge here"
SAMPLE_STEP_MM = 0.6             # spacing of outline sample points
COARSE_LONG_SIDE = 240           # resolution of the global search of the whole drawing
COARSE_CAP_SHARE = 0.0125        # proximity reach of the global search, share of the long side (3 px at 240)
COARSE_POINTS = 1500             # outline samples used by the global search
SCALE_RANGE = (0.3, 1.5)         # the plate's long side as a share of the photograph's long side (a close-up overflows)
SCALE_RATIO = 1.03               # geometric step of the scale search
ROTATION_OFFSETS_DEG = (-6.0, -3.0, 0.0, 3.0, 6.0)   # around each right angle: the camera is held roughly square
MIN_SEARCH_SCORE = 0.2           # mean proximity below which the drawing is not in the photograph at all
POLISH_LONG_SIDE = 1100          # resolution at which every orientation's best pose is polished and compared
POLISH_CAPS_MM = ((3.0, 2.0), (1.5, 1.5), (CAP_MM, 1.0))   # (cap, blur) of the polishing pyramid: wide basin first
ORIENTATION_MARGIN = 0.9         # orientations whose polished cost comes within this of the best are all tried
SECOND_ORIENTATION_SHARE = 0.5   # decisive gate: the second orientation may keep at most this share of the anchors ...
ORIENTATION_SUPPORT_MARGIN = 0.05  # ... unless the photograph confirms this much more of the drawing's outline in the best
MAX_RESIDUAL_MM = (0.2, 0.6)     # median and 90th percentile of the anchor outline residual
MIN_SPREAD = 0.2                 # anchors' convex hull must cover this fraction of the work's area
MIN_INLIER_FRACTION = 0.5
# (search radius mm, best cost mm, distinctiveness mm) of each pass; the radius shrinks as the transform improves
SCHEDULE = ((1.4, 0.14, 0.02), (1.0, 0.11, 0.02), (0.7, 0.10, 0.02), (0.5, 0.09, 0.02), (0.4, 0.09, 0.02))
CONTRAST_MIN = 0.6               # best cost vs the median cost of the search window
CONFIRM_RADIUS_MM = 0.5          # after the passes, every element matching this close to its prediction is an anchor
FRAME_SEARCH = (0.03, 0.12)      # the frame's inner edge is looked for from this far outside to this far inside the plate
FRAME_LINE_MM = 0.3              # tolerance of the frame edge line
SUPPORT_MM = 0.15                # an outline point this close to a photo edge is supported by the photograph
DIRECTION_BINS = 8               # edge directions are compared in bins of 22.5 degrees, each accepting +-33.75 degrees

STATUSES = ("anchor", "confirmed", "computed", "partly hidden", "hidden", "boundary")


@dataclass
class Element:
    layer_index: int
    region_index: int
    name: str
    points: np.ndarray       # outline samples in file mm (outer loop, holes and open polylines)
    tangents: np.ndarray     # unit direction of the outline at every sample
    centroid: np.ndarray
    area: float
    boundary: bool = False


# -- file side -------------------------------------------------------------------------------------------------
def _loop_samples(loop: np.ndarray, closed: bool, step: float) -> tuple[np.ndarray, np.ndarray]:
    pts = np.vstack([loop, loop[:1]]) if closed else loop
    seg = np.diff(pts, axis=0)
    length = np.linalg.norm(seg, axis=1)
    total = float(length.sum())
    if total < 1e-6:
        return np.zeros((0, 2)), np.zeros((0, 2))
    s = np.concatenate([[0.0], np.cumsum(length)])
    t = np.linspace(0, total, max(4, int(total / step)), endpoint=False)
    samples = np.column_stack([np.interp(t, s, pts[:, 0]), np.interp(t, s, pts[:, 1])])
    index = np.clip(np.searchsorted(s, t, side="right") - 1, 0, len(seg) - 1)
    tangents = seg[index] / np.maximum(length[index], 1e-9)[:, None]
    return samples, tangents


def _polygon_area_centroid(poly: np.ndarray) -> tuple[float, np.ndarray]:
    x, y = poly[:, 0], poly[:, 1]
    cross = x * np.roll(y, -1) - np.roll(x, -1) * y
    area = cross.sum() / 2
    if abs(area) < 1e-9:
        return 0.0, poly.mean(axis=0)
    c = np.array([((x + np.roll(x, -1)) * cross).sum(), ((y + np.roll(y, -1)) * cross).sum()]) / (6 * area)
    return abs(float(area)), c


def elements_from_layers(layers: list) -> list[Element]:
    """One element per region (of a layer with geometry), in layer / region order. A rectangle that encloses all other
    geometry is flagged as the plate boundary: it lies at the plate's edge, not on the engraving."""
    pairs = []
    for layer in layers:
        for region_index, region in enumerate(layer.regions):
            poly = np.asarray(region.polygon, float)
            if len(poly) < 2:
                continue
            closed = bool(region.closed or region.kind in ("rect", "bitmap"))
            loops = [(poly, closed)] + [(np.asarray(h, float), True) for h in getattr(region, "holes", [])]
            samples = [_loop_samples(l, c, SAMPLE_STEP_MM) for l, c in loops]
            kept = [x for x in samples if len(x[0])]
            points = np.vstack([x[0] for x in kept]) if kept else np.zeros((0, 2))
            tangents = np.vstack([x[1] for x in kept]) if kept else np.zeros((0, 2))
            area, centroid = _polygon_area_centroid(poly) if closed and len(poly) >= 3 else (0.0, poly.mean(axis=0))
            pairs.append((Element(layer.index, region_index, f"{layer.name} #{region_index + 1}", points, tangents,
                                  centroid, area), region))
    for element, region in pairs:
        if region.kind != "rect" or not region.closed or len(pairs) <= 3:
            continue
        others = [o.points for o, _ in pairs if o is not element and len(o.points)]
        if not others:
            continue
        lo, hi = np.min([o.min(axis=0) for o in others], axis=0), np.max([o.max(axis=0) for o in others], axis=0)
        if (region.x <= lo[0] + 0.05 and region.y <= lo[1] + 0.05 and
                region.x + region.width >= hi[0] - 0.05 and region.y + region.height >= hi[1] - 0.05):
            element.boundary = True
    return [e for e, _ in pairs]


def plate_rectangle(elements: list[Element]) -> np.ndarray:
    """Corners (file mm) of the plate: the enclosing rectangle if the file has one, else the work's bounding box."""
    chosen = [e for e in elements if e.boundary] or elements
    pts = np.vstack([e.points for e in chosen if len(e.points)])
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    return np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]], float)


# -- photo side ------------------------------------------------------------------------------------------------
@dataclass
class Prepared:
    scale: float             # working pixels per original pixel
    lab: np.ndarray
    edges: np.ndarray
    angle: np.ndarray        # direction of the edge at every pixel, radians in [0, pi)


def prepare(img_bgr: np.ndarray, long_side: int) -> Prepared:
    h, w = img_bgr.shape[:2]
    s = long_side / max(h, w)
    small = cv2.resize(img_bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(small.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)
    L, A, B = (cv2.GaussianBlur(c, (0, 0), 1.0) for c in cv2.split(lab))

    def to8(c, lo_p=1, hi_p=99):
        lo, hi = np.percentile(c, lo_p), np.percentile(c, hi_p)
        return np.clip((c - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)

    # a dark exposure still has region boundaries: stretch by local contrast, and use the colour channels as well
    channels = [cv2.createCLAHE(clipLimit=3.0, tileGridSize=(12, 12)).apply(to8(L, 1, 99.5)), to8(A), to8(B)]
    edges = cv2.Canny(channels[0], 25, 70) | cv2.Canny(channels[1], 30, 80) | cv2.Canny(channels[2], 30, 80)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(edges, connectivity=8)
    keep = np.zeros(count, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= 25          # scan-line texture is short; real boundaries are long chains
    # the direction of an edge: that of the strongest gradient among the three channels
    gx = np.stack([cv2.Sobel(c, cv2.CV_32F, 1, 0, ksize=3) for c in channels])
    gy = np.stack([cv2.Sobel(c, cv2.CV_32F, 0, 1, ksize=3) for c in channels])
    strongest = np.argmax(gx * gx + gy * gy, axis=0)
    rows, cols = np.indices(strongest.shape)
    angle = np.mod(np.arctan2(gy[strongest, rows, cols], gx[strongest, rows, cols]) + np.pi / 2, np.pi)
    return Prepared(s, lab, (keep[labels] * 255).astype(np.uint8), angle.astype(np.float32))


def _frame_threshold(lightness: np.ndarray) -> float | None:
    """Lightness that separates the frame from the work: the valley right after the frame's peak in the histogram.

    The frame is a large, uniform, very dark area, so it makes the first (lowest) peak; the valley behind it is
    where a dark part of the work (a black silhouette) starts. No clear valley means no usable frame.
    """
    counts, edges = np.histogram(np.clip(lightness, 0, 60), bins=np.arange(0, 60.5, 0.5))
    smooth = np.convolve(counts.astype(float), [1, 2, 3, 2, 1], mode="same") / 9
    low = int(np.searchsorted(edges, np.percentile(lightness, 5)))
    peak = int(np.argmax(smooth[: low + 13]))
    limit = min(len(smooth) - 2, peak + 24)               # the valley lies within 12 lightness units of the peak
    i = peak
    while i < limit and smooth[i + 1] <= smooth[i] and smooth[i] > 0.05 * smooth[peak]:
        i += 1
    if i >= limit or smooth[i] > 0.5 * smooth[peak]:
        return None
    return float(edges[i] + 0.25)


# -- geometry helpers ------------------------------------------------------------------------------------------
def to_px(h: np.ndarray, pts: np.ndarray) -> np.ndarray:
    p = np.c_[pts, np.ones(len(pts))] @ h.T
    return p[:, :2] / p[:, 2:3]


def _lookup(dist: np.ndarray, xy: np.ndarray, cap: float) -> np.ndarray:
    height, width = dist.shape
    x = np.rint(xy[..., 0]).astype(int)
    y = np.rint(xy[..., 1]).astype(int)
    ok = (x >= 0) & (x < width) & (y >= 0) & (y < height)
    out = np.full(x.shape, cap, np.float32)
    out[ok] = dist[y[ok], x[ok]]
    return out


def _cost(dist: np.ndarray, h: np.ndarray, points: np.ndarray, cap: float) -> float:
    """Mean capped distance of the outline samples to the nearest photo edge. The cap bounds what a hidden or
    painted-over outline can contribute, so every orientation pays the same for what is not visible."""
    return float(_lookup(dist, to_px(h, points), cap).mean())


def _similarity_about(c, f, th, t) -> np.ndarray:
    ct, st = math.cos(th) * f, math.sin(th) * f
    a = np.array([[ct, -st, 0], [st, ct, 0], [0, 0, 1]])
    return (np.array([[1, 0, t[0]], [0, 1, t[1]], [0, 0, 1]]) @ np.array([[1, 0, c[0]], [0, 1, c[1]], [0, 0, 1]]) @ a @
            np.array([[1, 0, -c[0]], [0, 1, -c[1]], [0, 0, 1]]))


def _capped_distance(edges: np.ndarray, cap: float) -> np.ndarray:
    return np.minimum(cv2.distanceTransform(255 - edges, cv2.DIST_L2, 3), cap).astype(np.float32)


# -- the global search of the whole drawing --------------------------------------------------------------------
def _proximity_by_direction(prep: Prepared, cap: float) -> np.ndarray:
    """(H, W, bins) proximity of every pixel to an edge of each direction: 1 on such an edge, 0 at ``cap`` pixels or
    farther."""
    return np.stack([1.0 - d / cap for d in _distances_by_direction(prep, cap)], axis=2)


def _direction_bins(tangents: np.ndarray, lin: np.ndarray) -> np.ndarray:
    """Direction bin of every outline sample after the linear map ``lin``."""
    direction = tangents @ lin.T
    width = np.pi / DIRECTION_BINS
    return np.rint(np.mod(np.arctan2(direction[:, 1], direction[:, 0]), np.pi) / width).astype(int) % DIRECTION_BINS


def _search_pose(prox: np.ndarray, pad: int, pts: np.ndarray, tan: np.ndarray, centre: np.ndarray,
                 lin: np.ndarray) -> tuple[float, np.ndarray] | None:
    """Best shift of the drawing under the linear map ``lin`` (file mm about the plate centre -> pixels): the
    outline samples, each in the channel of its direction, are correlated with the proximity map (FFT inside
    OpenCV). Returns (mean proximity, mm -> px homography) or None when the drawing does not fit the search area."""
    p = pts @ lin.T
    lo = np.floor(p.min(axis=0))
    ij = np.rint(p - lo).astype(int)
    template = np.zeros((int(ij[:, 1].max()) + 1, int(ij[:, 0].max()) + 1, DIRECTION_BINS), np.float32)
    template[ij[:, 1], ij[:, 0], _direction_bins(tan, lin)] = 1.0
    if template.shape[0] > prox.shape[0] or template.shape[1] > prox.shape[1]:
        return None
    result = cv2.matchTemplate(prox, template, cv2.TM_CCORR)
    at = np.unravel_index(int(result.argmax()), result.shape)
    h = np.eye(3)
    h[:2, :2] = lin
    h[:2, 2] = np.array([at[1], at[0]], float) - pad - lo - lin @ centre      # the plate centre lands at at - pad - lo
    return float(result[at]) / len(pts), h


def global_search(prep: Prepared, points: np.ndarray, tangents: np.ndarray, plate: np.ndarray) -> list[dict]:
    """The best pose of every orientation (mirror x right angle), by correlation of the drawing's outline samples with
    the direction-aware proximity map over every scale, small rotation and shift: a first pass on a coarse grid of
    scale and rotation, then the neighbourhood of every orientation's best. ``h`` maps file mm to pixels of
    ``prep``; ``score`` is the mean proximity of the outline samples (1 = every sample on an edge of its direction)."""
    height, width = prep.edges.shape
    long_px = max(height, width)
    cap = max(3.0, COARSE_CAP_SHARE * long_px)
    pad = int(0.2 * long_px)
    prox = np.pad(_proximity_by_direction(prep, cap), ((pad, pad), (pad, pad), (0, 0)))
    rng = np.random.default_rng(0)
    pick = rng.choice(len(points), min(len(points), COARSE_POINTS), replace=False)
    centre = plate.mean(axis=0)
    pts, tan = points[pick] - centre, tangents[pick]
    px_per_mm_of = long_px / float(np.ptp(plate, axis=0).max())

    def linear(mirror: bool, degrees: float, share: float) -> np.ndarray:
        th = math.radians(degrees)
        rot = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
        return (share * px_per_mm_of) * rot @ np.diag([1.0, -1.0 if mirror else 1.0])

    best: dict[tuple[bool, int], dict] = {}

    def consider(mirror: bool, k: int, degrees: float, share: float) -> None:
        found = _search_pose(prox, pad, pts, tan, centre, linear(mirror, degrees, share))
        if found is not None and found[0] > best.get((mirror, k), {"score": -1.0})["score"]:
            best[(mirror, k)] = {"mirror": mirror, "k": k, "degrees": degrees, "share": share,
                                 "score": found[0], "h": found[1]}

    coarse_ratio = SCALE_RATIO ** 2
    n_scales = int(math.log(SCALE_RANGE[1] / SCALE_RANGE[0]) / math.log(coarse_ratio)) + 1
    for mirror in (False, True):
        for k in range(4):
            for offset in ROTATION_OFFSETS_DEG[::2]:
                for share in SCALE_RANGE[0] * coarse_ratio ** np.arange(n_scales):
                    consider(mirror, k, 90 * k + offset, float(share))
    for (mirror, k), pose in list(best.items()):
        step = ROTATION_OFFSETS_DEG[1] - ROTATION_OFFSETS_DEG[0]
        for degrees in (pose["degrees"] - step, pose["degrees"], pose["degrees"] + step):
            for share in (pose["share"] / SCALE_RATIO, pose["share"], pose["share"] * SCALE_RATIO):
                if degrees != pose["degrees"] or share != pose["share"]:
                    consider(mirror, k, degrees, share)
    return sorted(best.values(), key=lambda c: -c["score"])


def _directional_cost(dists: list[np.ndarray], h: np.ndarray, points: np.ndarray, tangents: np.ndarray,
                      cap: float) -> float:
    """Mean capped distance of every outline sample to the nearest photo edge *of its own direction*. A dense
    drawing of parallel strokes lies close to some edge in every orientation, but close to an edge of the right
    direction in one only."""
    bins = _direction_bins(tangents, h[:2, :2])
    px = to_px(h, points)
    cost = np.empty(len(points), np.float32)
    for b in range(DIRECTION_BINS):
        members = bins == b
        if members.any():
            cost[members] = _lookup(dists[b], px[members], cap)
    return float(cost.mean())


def _distances_by_direction(prep: Prepared, cap: float) -> list[np.ndarray]:
    """Capped distance to the nearest edge of each direction bin; a bin accepts the edges within one and a half
    bin widths of its centre, so that a sample at the border of its bin still meets its own edge."""
    out = []
    width = np.pi / DIRECTION_BINS
    for b in range(DIRECTION_BINS):
        diff = np.abs(np.mod(prep.angle - b * width + np.pi / 2, np.pi) - np.pi / 2)
        members = prep.edges.copy()
        members[diff > 1.5 * width] = 0
        out.append(_capped_distance(members, cap))
    return out


def _polish(h: np.ndarray, points: np.ndarray, dist: np.ndarray, cap: float, centre: np.ndarray,
            steps=((8, 1.2, .02), (4, .6, .01), (2, .3, .005), (1, .15, .0025), (.5, .08, .001)),
            max_points: int = 3000) -> np.ndarray:
    """Coordinate descent on shift, rotation and scale of the whole drawing, from the coarse pose to well under a
    millimetre, so that the first element search window (which is small) contains the true positions."""
    rng = np.random.default_rng(2)
    sub = points if len(points) <= max_points else points[rng.choice(len(points), max_points, replace=False)]
    best = _cost(dist, h, sub, cap)
    for step_px, step_deg, step_scale in steps:
        for _ in range(12):
            improved = False
            for dx, dy, deg, f in ((step_px, 0, 0, 1), (-step_px, 0, 0, 1), (0, step_px, 0, 1), (0, -step_px, 0, 1),
                                   (0, 0, step_deg, 1), (0, 0, -step_deg, 1), (0, 0, 0, 1 + step_scale), (0, 0, 0, 1 - step_scale)):
                candidate = _similarity_about(centre, f, math.radians(deg), (dx, dy)) @ h
                cost = _cost(dist, candidate, sub, cap)
                if cost < best - 1e-4:
                    best, h, improved = cost, candidate, True
            if not improved:
                break
    return h


# -- element matching ------------------------------------------------------------------------------------------
def _search_element(dist, pts_px, radius, cap):
    s = np.arange(-radius, radius + 1)
    sx, sy = np.meshgrid(s, s)
    shifts = np.stack([sx.ravel(), sy.ravel()], 1)
    costs = _lookup(dist, pts_px[None] + shifts[:, None, :], cap).mean(axis=1).reshape(sx.shape)
    return s, costs


def _match_elements(h, elements, dist, scale, radius_mm, cap, only=None):
    out = []
    radius = max(2, int(round(radius_mm * scale)))
    sep = min(0.5 * scale, 0.75 * radius)
    for idx, e in enumerate(elements):
        if e.boundary or len(e.points) < 25 or (only is not None and idx not in only):
            continue
        pts = e.points if len(e.points) <= 400 else e.points[:: math.ceil(len(e.points) / 400)]
        s, costs = _search_element(dist, to_px(h, pts), radius, cap)
        i = np.unravel_index(int(costs.argmin()), costs.shape)
        best = float(costs[i])
        shift = np.array([s[i[1]], s[i[0]]], float)
        gx, gy = np.meshgrid(s, s)
        far = np.hypot(gx - shift[0], gy - shift[1]) >= sep
        median = float(np.median(costs))
        out.append({"index": idx, "shift": shift, "cost": best / scale, "median": median / scale,
                    "distinct": (float(costs[far].min()) - best) / scale if far.any() else 0.0})
    return out


def _is_anchor(m, cost_max, distinct_min) -> bool:
    return (m["cost"] <= cost_max and m["distinct"] >= distinct_min and
            (m["median"] - m["cost"]) / max(m["median"], 1e-9) >= CONTRAST_MIN)


def _fit(h, elements, anchors, scale, thresh_mm, max_pts=40):
    rng = np.random.default_rng(1)
    src, dst, owner = [], [], []
    for a in anchors:
        p = elements[a["index"]].points
        pick = rng.choice(len(p), min(len(p), max_pts), replace=False)
        src.append(p[pick])
        dst.append(to_px(h, p[pick]) + a["shift"])
        owner += [a["index"]] * len(pick)
    src, dst = np.vstack(src).astype(np.float32), np.vstack(dst).astype(np.float32)
    hn, inl = cv2.findHomography(src, dst, cv2.RANSAC, thresh_mm * scale, maxIters=3000, confidence=0.999)
    return hn, (None if inl is None else inl.ravel() > 0), src, dst, np.array(owner)


def _px_per_mm(h: np.ndarray, at: np.ndarray) -> float:
    p = to_px(h, np.array([at, at + [1.0, 0.0], at + [0.0, 1.0]]))
    return float((np.linalg.norm(p[1] - p[0]) + np.linalg.norm(p[2] - p[0])) / 2)


def _plate_mask(shape: tuple[int, int], h: np.ndarray, plate: np.ndarray, inset_px: float) -> np.ndarray:
    """Pixels inside the plate rectangle under ``h``, shrunk by ``inset_px`` so that the plate's or frame's own edge
    does not attract the outlines."""
    mask = cv2.fillConvexPoly(np.zeros(shape, np.uint8), np.rint(to_px(h, plate)).astype(np.int32), 255)
    k = int(max(3, round(inset_px))) | 1
    return cv2.erode(mask, np.ones((k, k), np.uint8))


# -- the frame, found after the work ---------------------------------------------------------------------------
def _dominant_line(pts: np.ndarray, outward: np.ndarray, tol: float, rng) -> np.ndarray | None:
    """The line through most of ``pts``; of lines with nearly as many points the outermost one (a dark run ends on
    the frame's inner edge or deeper inside the work, never outside it). None when no line holds enough points."""
    if len(pts) < 12:
        return None
    candidates = []
    for _ in range(300):
        i, j = rng.choice(len(pts), 2, replace=False)
        d = pts[j] - pts[i]
        if np.linalg.norm(d) < 5:
            continue
        n = np.array([-d[1], d[0]]) / np.linalg.norm(d)
        if n @ outward < 0:
            n = -n
        signed = (pts - pts[i]) @ n
        inliers = np.abs(signed) < tol
        candidates.append((int(inliers.sum()), float(pts[i] @ n), inliers))
    if not candidates:
        return None
    most = max(c[0] for c in candidates)
    if most < max(12, 0.25 * len(pts)):
        return None
    _, _, inliers = max((c for c in candidates if c[0] >= 0.8 * most), key=lambda c: c[1])
    return cv2.fitLine(pts[inliers].astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).ravel()


def window_from_frame(prep: Prepared, h: np.ndarray, plate: np.ndarray, scale: float) -> tuple[np.ndarray, dict]:
    """Corners (TL, TR, BR, BL in the file's order; pixels of ``prep``) of the visible window and which sides of the
    plate a dark frame covers. Along every side of the plate rectangle under ``h`` the lightness is read from a little
    outside to some way inside; where it starts dark (the frame) and turns bright is the frame's inner edge, and the
    dominant line of those points is the side of the window. A side without a frame edge is the plate edge itself."""
    corners = to_px(h, plate)
    centre = corners.mean(axis=0)
    L = cv2.GaussianBlur(prep.lab[:, :, 0], (0, 0), 3)
    height, width = L.shape
    thr = _frame_threshold(L)
    rng = np.random.default_rng(0)
    size = float(np.linalg.norm(corners[1] - corners[0]) + np.linalg.norm(corners[2] - corners[1])) / 2
    found: dict[str, bool] = {}
    lines = []
    for side, (a, b) in enumerate(((corners[0], corners[1]), (corners[1], corners[2]),
                                   (corners[2], corners[3]), (corners[3], corners[0]))):
        along = (b - a) / np.linalg.norm(b - a)
        outward = np.array([along[1], -along[0]])
        if outward @ ((a + b) / 2 - centre) < 0:
            outward = -outward
        line = None
        if thr is not None:
            outside, inside = FRAME_SEARCH[0] * size, FRAME_SEARCH[1] * size
            depth = np.arange(-outside, inside)
            bases = a[None] + np.linspace(0.12, 0.88, 60)[:, None] * (b - a)[None]
            coords = bases[:, None, :] - depth[None, :, None] * outward[None, None, :]      # (60, n, 2)
            profile = cv2.remap(L, coords[..., 0].astype(np.float32), coords[..., 1].astype(np.float32),
                                cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=100.0)
            run = max(8, int(0.015 * len(depth)))
            pts = []
            for row, values in enumerate(profile):
                dark = values < thr
                if not dark[:run].all():
                    continue                      # no frame outside this point of the plate edge
                end = np.argmin(dark) if not dark.all() else None
                if end is not None:
                    pts.append(coords[row, end])
            tol = max(3.0, FRAME_LINE_MM * scale)
            line = _dominant_line(np.asarray(pts, np.float32), outward, tol, rng) if pts else None
        found[("top", "right", "bottom", "left")[side]] = line is not None
        if line is None:
            line = np.array([along[0], along[1], a[0], a[1]], np.float32)
        lines.append(line)

    def meet(p, q):
        (vx1, vy1, x1, y1), (vx2, vy2, x2, y2) = p, q
        t = np.linalg.solve(np.array([[vx1, -vx2], [vy1, -vy2]]), np.array([x2 - x1, y2 - y1]))
        return np.array([x1 + vx1 * t[0], y1 + vy1 * t[0]])

    try:
        quad = np.array([meet(lines[3], lines[0]), meet(lines[0], lines[1]), meet(lines[1], lines[2]),
                         meet(lines[2], lines[3])], np.float32)
    except np.linalg.LinAlgError:
        quad = None
    if (quad is None or not np.isfinite(quad).all() or not cv2.isContourConvex(quad) or
            abs(cv2.contourArea(quad)) < 0.5 * abs(cv2.contourArea(corners.astype(np.float32)))):
        return corners.astype(np.float32), {k: False for k in found}
    return quad, found


# -- the registration ----------------------------------------------------------------------------------------------
def register(img_bgr: np.ndarray, layers: list, diagnostics: dict | None = None) -> Registration | None:
    """Align ``img_bgr`` (original resolution) to the file geometry of ``layers``; None when it is not supported."""
    diag = diagnostics if diagnostics is not None else {}

    def refuse(reason: str):
        diag["refused"] = reason
        return None

    elements = elements_from_layers([l for l in layers if l.regions])
    movable = [e for e in elements if not e.boundary and len(e.points) >= 25]
    if len(movable) < 6:
        return refuse("the file has too few closed outlines to match")
    plate = plate_rectangle(elements)
    all_points = np.vstack([e.points for e in movable])
    all_tangents = np.vstack([e.tangents for e in movable])
    centre = plate.mean(axis=0)

    # 1. the whole drawing over every pose, no frame needed
    started = time.perf_counter()
    coarse = prepare(img_bgr, COARSE_LONG_SIDE)
    poses = global_search(coarse, all_points, all_tangents, plate)
    diag["search"] = {"scores": [{"mirror": p["mirror"], "rotation_degrees": 90 * p["k"], "score": round(p["score"], 3)}
                                 for p in poses], "seconds": round(time.perf_counter() - started, 1)}
    if not poses or poses[0]["score"] < MIN_SEARCH_SCORE:
        return refuse("the drawing of the file was not found in the photograph")

    # 2. every orientation's best pose polished at a middle resolution; the orientation must win clearly
    mid = prepare(img_bgr, POLISH_LONG_SIDE)
    to_mid = np.diag([mid.scale / coarse.scale, mid.scale / coarse.scale, 1.0])
    mid_scale0 = _px_per_mm(to_mid @ poses[0]["h"], centre)
    pyramid = [(cap_mm * mid_scale0, cv2.GaussianBlur(_capped_distance(mid.edges, cap_mm * mid_scale0), (0, 0), blur))
               for cap_mm, blur in POLISH_CAPS_MM]
    by_direction = _distances_by_direction(mid, CAP_MM * mid_scale0)
    for pose in poses:
        h_mid = to_mid @ pose["h"]
        for cap_px, dist_mid in pyramid:
            h_mid = _polish(h_mid, all_points, dist_mid, cap_px, to_px(h_mid, centre[None])[0], max_points=1500)
        pose["h_mid"] = h_mid
        pose["cost"] = _directional_cost(by_direction, h_mid, all_points, all_tangents, CAP_MM * mid_scale0) / mid_scale0
    poses.sort(key=lambda p: p["cost"])
    best, second = poses[0]["cost"], poses[1]["cost"] if len(poses) > 1 else float("inf")
    diag["orientation"] = {"best_cost_mm": round(best, 3), "second_cost_mm": round(second, 3),
                           "costs_mm": [round(p["cost"], 3) for p in poses]}

    # 3-5. elements as anchors at the working resolution. Every orientation whose polished cost comes within the
    # margin of the best goes on (a drawing of symmetric parts has a close mirror twin), at least the best two, at
    # most three; the anchors and the confirmed share of the outline decide, and refuse when they cannot.
    close = [pose for pose in poses if pose["cost"] <= best / ORIENTATION_MARGIN]
    chosen = poses[:max(2, min(3, len(close)))]
    px_per_mm_full = _px_per_mm(poses[0]["h_mid"], centre) / mid.scale
    starts = [(np.diag([1 / mid.scale, 1 / mid.scale, 1.0]) @ pose["h_mid"], pose) for pose in chosen]
    orientation = {"best_cost_mm": round(best, 3), "second_cost_mm": round(second, 3),
                   "margin": round(best / second, 3) if np.isfinite(second) else 0.0}
    return _finish(img_bgr, elements, movable, plate, px_per_mm_full, starts, orientation, diag)


def confirm(img_bgr: np.ndarray, layers: list, image_to_mm: np.ndarray, diagnostics: dict | None = None) -> Registration | None:
    """A registration found by another route (whole shapes, markers) taken as the start of the element anchoring:
    the result holds only if enough spread-out elements confirm it independently. None, with the reason in
    ``diagnostics``, when the photograph does not support it."""
    diag = diagnostics if diagnostics is not None else {}
    elements = elements_from_layers([l for l in layers if l.regions])
    movable = [e for e in elements if not e.boundary and len(e.points) >= 25]
    if len(movable) < 6:
        diag["refused"] = "the file has too few closed outlines to match"
        return None
    plate = plate_rectangle(elements)
    mm_to_image = np.linalg.inv(image_to_mm)
    lin = mm_to_image[:2, :2]
    angle = math.degrees(math.atan2(lin[1, 0], lin[0, 0]))
    orientation = {"best_cost_mm": None, "second_cost_mm": None, "margin": None, "started_from": "another route"}
    pose = {"mirror": bool(np.linalg.det(lin) < 0), "k": int(round(angle / 90)) % 4, "score": None}
    return _finish(img_bgr, elements, movable, plate, _px_per_mm(mm_to_image, plate.mean(axis=0)),
                   [(mm_to_image, pose)], orientation, diag)


def _finish(img_bgr, elements, movable, plate, px_per_mm_full, starts, orientation, diag) -> Registration | None:
    """Steps 3-5 from one or two starting transforms (file mm -> pixels of the full photograph): element anchors,
    the gates, the frame window and the classification of every element."""

    def refuse(reason: str):
        diag["refused"] = reason
        return None

    centre = plate.mean(axis=0)
    all_points = np.vstack([e.points for e in movable])
    all_tangents = np.vstack([e.tangents for e in movable])
    prep = prepare(img_bgr, int(np.clip(max(img_bgr.shape[:2]) * TARGET_PX_PER_MM / max(px_per_mm_full, 1e-6), 1200, 3200)))
    s = prep.scale
    to_work = np.diag([s, s, 1.0])
    scale0 = _px_per_mm(to_work @ starts[0][0], centre)
    cap = CAP_MM * scale0
    refined = []
    for h_full, pose in starts:
        start = to_work @ h_full
        edges = prep.edges & _plate_mask(prep.edges.shape, start, plate, 0.9 * scale0)
        dist = _capped_distance(edges, cap)
        start = _polish(start, all_points, cv2.GaussianBlur(dist, (0, 0), 1.0), cap, to_px(start, centre[None])[0],
                        steps=((2, .3, .005), (1, .15, .0025), (.5, .08, .001)))
        h, anchors = _refine(start, elements, dist, cap)
        near = _outline_support(prep, h, all_points, all_tangents, cap) if anchors else np.zeros(len(all_points), bool)
        refined.append((float(near.mean()), len(anchors), h, anchors, pose, dist, near))
    # A drawing of symmetric parts (four identical shirts) gives the mirrored orientation anchors too; what tells the
    # orientations apart is how much of the whole outline the photograph confirms under each, and failing a clear
    # lead there, the elements that only one of the two explains (the asymmetric details).
    refined.sort(key=lambda item: (-item[0], -item[1]))
    support, n_anchors, h, anchors, pose, dist, near = refined[0]
    second_support, second_anchors = (refined[1][0], refined[1][1]) if len(refined) > 1 else (0.0, 0)
    owner = np.repeat(np.arange(len(movable)), [len(e.points) for e in movable])
    only_best, only_second = _explained_by_one_only(near, refined[1][6], owner) if len(refined) > 1 else (0, 0)
    diag["orientation"] = dict(orientation, anchors_second=second_anchors, support=round(support, 3),
                               support_second=round(second_support, 3), elements_only_best=only_best,
                               elements_only_second=only_second)
    if (len(refined) > 1 and second_anchors >= max(3, SECOND_ORIENTATION_SHARE * n_anchors) and
            support - second_support < ORIENTATION_SUPPORT_MARGIN and only_best < max(3, 3 * only_second)):
        return refuse("the orientation of the work is ambiguous: the best and the second best differ too little")
    diag["anchors"] = n_anchors
    scale = _px_per_mm(h, centre)
    if n_anchors < max(5, min(12, math.ceil(0.1 * len(movable)))):
        margin = orientation.get("margin")
        if len(starts) > 1 and margin is not None and margin >= ORIENTATION_MARGIN:
            # every orientation looked alike and none could be anchored: the drawing itself does not tell
            return refuse("the orientation of the work is ambiguous: the best and the second best differ too little")
        return refuse(f"only {n_anchors} elements matched the photograph")
    hn, good, src, dst, owner = _fit(h, elements, anchors, scale, 0.2)
    if hn is None or good is None or good.mean() < MIN_INLIER_FRACTION:
        return refuse("the matched elements disagree about the position of the work")
    h = hn

    # residual of the anchor outlines under the final transform, in mm
    resid = np.linalg.norm(to_px(h, src[good]) - dst[good], axis=1) / scale
    med, p90 = float(np.median(resid)), float(np.percentile(resid, 90))
    centres = np.array([elements[a["index"]].centroid for a in anchors])
    work_area = float(np.prod(np.ptp(all_points, axis=0)))
    hull = float(cv2.contourArea(cv2.convexHull(centres.astype(np.float32)))) if len(centres) >= 3 else 0.0
    diag.update(residual_median_mm=round(med, 3), residual_p90_mm=round(p90, 3),
                inlier_fraction=round(float(good.mean()), 3), spread=round(hull / max(work_area, 1e-9), 3))
    if med > MAX_RESIDUAL_MM[0] or p90 > MAX_RESIDUAL_MM[1]:
        return refuse(f"the outlines do not fit closely enough ({med:.2f} mm median)")
    if hull < MIN_SPREAD * work_area:
        return refuse("the matched elements are concentrated in one part of the work")

    # 5. the frame, from the plate's known size
    window, frame_sides = window_from_frame(prep, h, plate, scale)
    details = _classify(h, elements, anchors, dist, window, scale, cap, plate, src, dst, owner, good)
    details.update(orientation=dict(orientation, mirror=bool(pose["mirror"]), rotation_degrees=90 * int(pose["k"]),
                                    anchors_second=second_anchors, search_score=pose.get("score"),
                                    support=round(support, 3), support_second=round(second_support, 3),
                                    elements_only_best=only_best, elements_only_second=only_second),
                   residual_median_mm=round(med, 3), residual_p90_mm=round(p90, 3), px_per_mm=round(scale / s, 3),
                   frame_sides=frame_sides, window_found=any(frame_sides.values()))
    to_full = np.diag([1 / s, 1 / s, 1.0])
    mm_to_image = to_full @ h
    details["window_px"] = (window / s).round(1).tolist()
    diag.update(details={k: v for k, v in details.items() if k != "statuses"})
    reflected = bool(np.linalg.det(mm_to_image[:2, :2]) < 0)
    matches = [{"element": elements[a["index"]].name, "center_mm": elements[a["index"]].centroid.round(3).tolist(),
                "center_px": (to_px(mm_to_image, elements[a["index"]].centroid[None])[0]).round(1).tolist()}
               for a in anchors]
    details["element_refs"] = [(e.layer_index, e.region_index) for e in elements]
    return Registration(np.linalg.inv(mm_to_image), "element anchors", matches, round(med * scale / s, 2), reflected,
                        details=details)


def _outline_support(prep: Prepared, h: np.ndarray, points: np.ndarray, tangents: np.ndarray, cap: float) -> np.ndarray:
    """Which outline samples of the drawing lie within ``SUPPORT_MM`` of a photograph edge of their own direction under
    ``h``: how much of the whole drawing, not only of the anchors, the photograph confirms."""
    scale = _px_per_mm(h, points.mean(axis=0))
    bins = _direction_bins(tangents, h[:2, :2])
    px = to_px(h, points)
    near = np.zeros(len(points), bool)
    for b, dist in enumerate(_distances_by_direction(prep, cap)):
        members = bins == b
        if members.any():
            near[members] = _lookup(dist, px[members], cap) <= SUPPORT_MM * scale
    return near


def _explained_by_one_only(near_a: np.ndarray, near_b: np.ndarray, owner: np.ndarray) -> tuple[int, int]:
    """Elements the photograph confirms under one transform (>= 70 % of their outline) and not under the other (< 50 %):
    a drawing of symmetric parts has a mirror twin that explains nearly as much outline on average, while only the
    asymmetric details separate the two, and they count one by one."""
    counts = np.bincount(owner).astype(float)
    share_a = np.bincount(owner, weights=near_a) / np.maximum(counts, 1)
    share_b = np.bincount(owner, weights=near_b) / np.maximum(counts, 1)
    return int(((share_a >= 0.7) & (share_b < 0.5)).sum()), int(((share_b >= 0.7) & (share_a < 0.5)).sum())


def _refine(h, elements, dist, cap):
    """The transform is refined pass by pass on ever closer, ever stricter anchors; the anchors reported are then
    every element that, around the final transform, has a close and distinctive match within half a millimetre
    (the first pass's cost bound): the strictest pass alone would discard elements whose photographed edge is
    doubled by a dark rim, although the transform they confirm is the same."""
    anchors: list[dict] = []
    for radius_mm, cost_mm, distinct_mm in SCHEDULE:
        scale = _px_per_mm(h, np.mean([e.centroid for e in elements if len(e.points)], axis=0))
        found = _match_elements(h, elements, dist, scale, radius_mm, cap)
        chosen = [m for m in found if _is_anchor(m, cost_mm, distinct_mm)]
        if len(chosen) < 4:          # four anchors of 40 outline points each constrain a homography; the gates after
            continue                 # the last pass decide whether that many, that spread out, are enough
        hn, good, *_ = _fit(h, elements, chosen, scale, 0.2)
        if hn is None:
            continue
        h, anchors = hn, chosen
    if anchors:
        scale = _px_per_mm(h, np.mean([e.centroid for e in elements if len(e.points)], axis=0))
        confirmed = [m for m in _match_elements(h, elements, dist, scale, CONFIRM_RADIUS_MM, cap)
                     if _is_anchor(m, SCHEDULE[0][1], SCHEDULE[0][2])]
        if len(confirmed) >= len(anchors):
            anchors = confirmed
    return h, anchors


def _classify(h, elements, anchors, dist, window, scale, cap, plate, src, dst, owner, good) -> dict:
    anchor_ids = {a["index"] for a in anchors}
    shrunk = cv2.erode(cv2.fillConvexPoly(np.zeros(dist.shape, np.uint8), window.astype(np.int32), 255),
                       np.ones((int(max(3, 0.4 * scale)) | 1,) * 2, np.uint8))
    statuses = []
    for idx, e in enumerate(elements):
        if e.boundary:
            statuses.append("boundary")
            continue
        if len(e.points) == 0:
            statuses.append("computed")
            continue
        px = to_px(h, e.points)
        ip = np.clip(np.rint(px).astype(int), [0, 0], [dist.shape[1] - 1, dist.shape[0] - 1])
        visible = float((shrunk[ip[:, 1], ip[:, 0]] > 0).mean())
        support = float((_lookup(dist, px, cap) <= SUPPORT_MM * scale).mean())
        if visible < 0.5:
            statuses.append("hidden")
        elif visible < 0.97:
            statuses.append("partly hidden")
        elif idx in anchor_ids:
            statuses.append("anchor")
        elif support >= 0.6:
            statuses.append("confirmed")
        else:
            statuses.append("computed")
    counts = {name: statuses.count(name) for name in STATUSES}

    corners_px = to_px(h, plate)
    hidden_mm = [round(float(-cv2.pointPolygonTest(window.astype(np.float32), tuple(map(float, p)), True) / scale), 2)
                 for p in corners_px]

    # bootstrap over anchors: how far the prediction of the plate corners and of hidden elements may move
    rng = np.random.default_rng(5)
    ids = np.array(sorted(anchor_ids))
    targets = [plate[i] for i in range(4)]
    hid = [i for i, st in enumerate(statuses) if st in ("hidden", "partly hidden")]
    targets += [elements[i].centroid for i in hid[:50]]
    runs = []
    for _ in range(150):
        pick = rng.choice(ids, len(ids), replace=True)
        rows = np.concatenate([np.where((owner == p) & good)[0] for p in pick])
        hb, _ = cv2.findHomography(src[rows], dst[rows], 0)
        if hb is not None:
            runs.append(to_px(hb, np.array(targets)))
    unc = [0.0] * len(targets)
    if len(runs) >= 20:
        runs = np.array(runs)
        unc = [float(np.percentile(np.linalg.norm(runs[:, i] - np.median(runs[:, i], axis=0), axis=1), 95) / scale)
               for i in range(len(targets))]
    extrapolation = _ring_holdout(window, anchors, elements, src, dst, owner, good, h, dist, scale, cap)
    return {"statuses": statuses, "counts": counts, "elements": len(elements), "extrapolation_mm": extrapolation,
            "plate_hidden_mm": hidden_mm,                        # TL, TR, BR, BL: > 0 means under the frame
            "plate_uncertainty_mm": [round(u, 3) for u in unc[:4]],
            "hidden_uncertainty_mm": round(max(unc[4:], default=0.0), 3),
            "anchors": len(anchors)}


def _ring_holdout(window, anchors, elements, src, dst, owner, good, h, dist, scale, cap, ring: float = 0.12):
    """How well is the outer ring predicted from the rest? The anchors in the outer ``ring`` of the window are left out,
    the transform is fitted to the others, and each left-out element is searched again in a wide window around where
    that transform puts it; the displacement it needs is the error of the prediction.

    A frame hides a far narrower strip than this ring, so the number is a pessimistic bound on the error of the
    inferred positions under the frame; the bootstrap alone would be too optimistic because it cannot see an
    error of the model itself (lens, a bent plate).
    """
    to_unit = cv2.getPerspectiveTransform(window.astype(np.float32), np.float32([[0, 0], [1, 0], [1, 1], [0, 1]]))
    held = []
    for a in anchors:
        u, v = to_px(to_unit, to_px(h, elements[a["index"]].centroid[None]))[0]
        if min(u, 1 - u, v, 1 - v) < ring:
            held.append(a["index"])
    keep = np.array([o not in held for o in owner]) & good
    if len(held) < 3 or keep.sum() < 40:
        return None
    hh, _ = cv2.findHomography(src[keep], dst[keep], 0)
    if hh is None:
        return None
    found = [m for m in _match_elements(hh, elements, dist, scale, 1.5, cap, only=set(held)) if _is_anchor(m, 0.14, 0.02)]
    if len(found) < 3:
        return {"ring": ring, "elements": len(held), "found": len(found), "median": None, "p90": None}
    err = np.array([np.linalg.norm(m["shift"]) for m in found]) / scale
    return {"ring": ring, "elements": len(held), "found": len(found), "median": round(float(np.median(err)), 3),
            "p90": round(float(np.percentile(err, 90)), 3)}
