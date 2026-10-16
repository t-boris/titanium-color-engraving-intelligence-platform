"""Register an unmarked finished work to its photograph from element anchors (REQ-024, DEC-048, DEC-049).

The old route for work without markers (``registration.register_geometry``) needs three whole shapes that match by
Hu moments. It fails when a frame clips the large shapes, when most paths are not recognised, or when the drawing is
a mirror image of the photograph. This module works the other way round:

1. the visible window of a frame is found from its inner edges (``find_window``);
2. the 8 orientations (four rotations, with and without mirror) are scored by the distance of all file outlines to the
   photograph's edges around the window, and the result is refused when the best does not clearly beat the second;
3. every file element is searched on its own in a small window around where the current transform predicts it; only an
   element with a close, distinctive match becomes an *anchor*;
4. a homography is fitted to the anchors only (RANSAC) and every element, also one hidden under the frame, is
   predicted from it; steps 3-4 repeat with a shrinking window.

Nothing is guessed: a registration that is not supported by enough spread-out anchors is refused (``None``) with the
reason in ``diagnostics``, and the operator places four corners (REQ-013). A hidden element is *inferred*, never
measured. All thresholds are in millimetres and scale with the photograph.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .registration import Registration

TARGET_PX_PER_MM = 10.0          # working resolution of the edge map
CAP_MM = 0.8                     # an outline farther than this from any photo edge counts as "no edge here"
SAMPLE_STEP_MM = 0.6             # spacing of outline sample points
ORIENTATION_MARGIN = 0.9         # early gate: best coarse cost at most this fraction of the second best
SECOND_ORIENTATION_SHARE = 0.5   # decisive gate: the second orientation may keep at most this share of the anchors
MAX_RESIDUAL_MM = (0.2, 0.6)     # median and 90th percentile of the anchor outline residual
MIN_SPREAD = 0.2                 # anchors' convex hull must cover this fraction of the work's area
MIN_INLIER_FRACTION = 0.5
# (search radius mm, best cost mm, distinctiveness mm) of each pass; the radius shrinks as the transform improves
SCHEDULE = ((1.4, 0.14, 0.02), (1.0, 0.11, 0.02), (0.7, 0.10, 0.02), (0.5, 0.09, 0.02), (0.4, 0.09, 0.02))
CONTRAST_MIN = 0.6               # best cost vs the median cost of the search window

STATUSES = ("anchor", "confirmed", "computed", "partly hidden", "hidden", "boundary")


@dataclass
class Element:
    layer_index: int
    region_index: int
    name: str
    points: np.ndarray       # outline samples in file mm (outer loop, holes and open polylines)
    centroid: np.ndarray
    area: float
    boundary: bool = False


# -- file side -------------------------------------------------------------------------------------------------
def _loop_samples(loop: np.ndarray, closed: bool, step: float) -> np.ndarray:
    pts = np.vstack([loop, loop[:1]]) if closed else loop
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    total = float(seg.sum())
    if total < 1e-6:
        return np.zeros((0, 2))
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0, total, max(4, int(total / step)), endpoint=False)
    return np.column_stack([np.interp(t, s, pts[:, 0]), np.interp(t, s, pts[:, 1])])


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
    geometry is flagged as the plate boundary: it lies at the frame's inner edge, not on the engraving."""
    pairs = []
    for layer in layers:
        for region_index, region in enumerate(layer.regions):
            poly = np.asarray(region.polygon, float)
            if len(poly) < 2:
                continue
            closed = bool(region.closed or region.kind in ("rect", "bitmap"))
            loops = [(poly, closed)] + [(np.asarray(h, float), True) for h in getattr(region, "holes", [])]
            samples = [_loop_samples(l, c, SAMPLE_STEP_MM) for l, c in loops]
            points = np.vstack([x for x in samples if len(x)]) if any(len(x) for x in samples) else np.zeros((0, 2))
            area, centroid = _polygon_area_centroid(poly) if closed and len(poly) >= 3 else (0.0, poly.mean(axis=0))
            pairs.append((Element(layer.index, region_index, f"{layer.name} #{region_index + 1}", points, centroid, area),
                          region))
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
    lightness = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(12, 12)).apply(to8(L, 1, 99.5))
    edges = cv2.Canny(lightness, 25, 70) | cv2.Canny(to8(A), 30, 80) | cv2.Canny(to8(B), 30, 80)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(edges, connectivity=8)
    keep = np.zeros(count, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= 25          # scan-line texture is short; real boundaries are long chains
    return Prepared(s, lab, (keep[labels] * 255).astype(np.uint8))


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


def find_window(prep: Prepared) -> np.ndarray | None:
    """Corners (TL, TR, BR, BL; working pixels) of the bright window inside a dark frame; None when there is no frame.

    The frame is the darkest large area. Scanning from every side, the window starts after a long dark run; a
    line is fitted per side with RANSAC so that a dark part of the work touching the frame (a black silhouette)
    does not move the side.
    """
    L = prep.lab[:, :, 0]
    h, w = L.shape
    Lb = cv2.GaussianBlur(L, (0, 0), 3)
    thr = _frame_threshold(Lb)
    if thr is None:
        return None

    def first_content(profile: np.ndarray) -> int | None:
        run = max(8, int(0.015 * len(profile)))
        is_dark = profile < thr
        for k in range(len(profile) - run):
            if is_dark[k:k + run].all():
                for j in range(k + run, len(profile)):
                    if not is_dark[j]:
                        return j
                return None
        return None

    sides: dict[str, list[tuple[float, float]]] = {"top": [], "bottom": [], "left": [], "right": []}
    for x in np.linspace(0.12 * w, 0.88 * w, 60).astype(int):
        col = Lb[:, x]
        t, b = first_content(col[: h // 2]), first_content(col[h // 2:][::-1])
        if t is not None: sides["top"].append((x, t))
        if b is not None: sides["bottom"].append((x, h - 1 - b))
    for y in np.linspace(0.12 * h, 0.82 * h, 60).astype(int):
        row = Lb[y]
        l, r = first_content(row[: w // 2]), first_content(row[w // 2:][::-1])
        if l is not None: sides["left"].append((l, y))
        if r is not None: sides["right"].append((w - 1 - r, y))
    rng = np.random.default_rng(0)
    lines = {}
    for name, found in sides.items():
        if len(found) < 12:
            return None
        pts = np.asarray(found, np.float32)
        best, best_n = None, 0
        for _ in range(300):
            i, j = rng.choice(len(pts), 2, replace=False)
            d = pts[j] - pts[i]
            if np.linalg.norm(d) < 5:
                continue
            n = np.array([-d[1], d[0]]) / np.linalg.norm(d)
            inliers = np.abs((pts - pts[i]) @ n) < 3
            if inliers.sum() > best_n:
                best, best_n = inliers, int(inliers.sum())
        if best is None or best_n < 0.5 * len(pts):
            return None
        lines[name] = cv2.fitLine(pts[best], cv2.DIST_L2, 0, 0.01, 0.01).ravel()

    def meet(a, b):
        (vx1, vy1, x1, y1), (vx2, vy2, x2, y2) = a, b
        t = np.linalg.solve(np.array([[vx1, -vx2], [vy1, -vy2]]), np.array([x2 - x1, y2 - y1]))
        return np.array([x1 + vx1 * t[0], y1 + vy1 * t[0]])

    try:
        quad = np.array([meet(lines["top"], lines["left"]), meet(lines["top"], lines["right"]),
                         meet(lines["bottom"], lines["right"]), meet(lines["bottom"], lines["left"])], np.float32)
    except np.linalg.LinAlgError:
        return None
    area = abs(cv2.contourArea(quad))
    if (not np.isfinite(quad).all() or not cv2.isContourConvex(quad) or area < 0.2 * h * w or
            quad.min() < -0.02 * max(h, w) or quad[:, 0].max() > 1.02 * w or quad[:, 1].max() > 1.02 * h):
        return None
    return quad


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


def _trimmed(costs: np.ndarray, share: float = 0.5) -> np.ndarray:
    """Mean of the smallest ``share`` of every row: outlines that are not visible (hidden, overpainted) must not
    decide which orientation is right."""
    k = max(1, int(costs.shape[1] * share))
    return np.partition(costs, k - 1, axis=1)[:, :k].mean(axis=1)


def _similarity_about(c, f, th, t) -> np.ndarray:
    ct, st = math.cos(th) * f, math.sin(th) * f
    a = np.array([[ct, -st, 0], [st, ct, 0], [0, 0, 1]])
    return (np.array([[1, 0, t[0]], [0, 1, t[1]], [0, 0, 1]]) @ np.array([[1, 0, c[0]], [0, 1, c[1]], [0, 0, 1]]) @ a @
            np.array([[1, 0, -c[0]], [0, 1, -c[1]], [0, 0, 1]]))


def _orientations(window: np.ndarray, plate: np.ndarray):
    for mirror in (False, True):
        q = window[::-1] if mirror else window
        for k in range(4):
            qq = np.roll(q, -k, axis=0).astype(np.float32)
            yield mirror, k, cv2.getPerspectiveTransform(plate.astype(np.float32), qq)


def _coarse(points: np.ndarray, dist_blur: np.ndarray, window: np.ndarray, plate: np.ndarray, cap: float,
            has_boundary: bool) -> list[dict]:
    """Best cost of every orientation (stage 1, cheap), then a finer pose search for the best two (stage 2)."""
    centre = window.mean(axis=0)
    rng = np.random.default_rng(0)

    def sample(n):
        return points[rng.choice(len(points), min(len(points), n), replace=False)]

    extent = float(np.ptp(window, axis=0).max())
    reach = (0.06 if has_boundary else 0.2) * extent
    f_values = (np.arange(0.97, 1.115, 0.02) if has_boundary else np.arange(0.6, 1.13, 0.04))
    step = max(4, int(round(reach / 11)))
    shifts = np.arange(-int(reach), int(reach) + 1, step)
    sx, sy = np.meshgrid(shifts, shifts)
    shift_grid = np.stack([sx.ravel(), sy.ravel()], 1)

    def search(pts, H0, f_list, th_list):
        best = (1e9, None)
        for f in f_list:
            for th in th_list:
                s = _similarity_about(centre, f, th, (0, 0))
                base = to_px(s @ H0, pts)
                cost = _trimmed(_lookup(dist_blur, base[None] + shift_grid[:, None, :], cap))
                i = int(cost.argmin())
                if cost[i] < best[0]:
                    move = np.array([[1, 0, shift_grid[i][0]], [0, 1, shift_grid[i][1]], [0, 0, 1.0]])
                    best = (float(cost[i]), move @ s @ H0)
        return best

    stage1 = []
    quick = sample(600)
    for mirror, k, H0 in _orientations(window, plate):
        cost, pose = search(quick, H0, f_values[::2], np.deg2rad([-1.2, 0, 1.2]))
        stage1.append({"mirror": mirror, "k": k, "H0": H0, "coarse_cost": cost, "pose": pose})
    stage1.sort(key=lambda r: r["coarse_cost"])
    fine = sample(2500)
    for cand in stage1[:2]:
        cost, pose = search(fine, cand["H0"], f_values, np.deg2rad([-2.4, -1.2, 0, 1.2, 2.4]))
        cand["fine_cost"], cand["pose"] = cost, pose
    return stage1


def _polish(h: np.ndarray, points: np.ndarray, dist: np.ndarray, cap: float, centre: np.ndarray) -> np.ndarray:
    """Coordinate descent on shift, rotation and scale of the whole drawing, from the coarse pose to well under a
    millimetre, so that the first element search window (which is small) contains the true positions."""
    rng = np.random.default_rng(2)
    sub = points if len(points) <= 3000 else points[rng.choice(len(points), 3000, replace=False)]
    best = float(_trimmed(_lookup(dist, to_px(h, sub)[None], cap))[0])
    for step_px, step_deg, step_scale in ((8, 1.2, .02), (4, .6, .01), (2, .3, .005), (1, .15, .0025), (.5, .08, .001)):
        for _ in range(12):
            improved = False
            for dx, dy, deg, f in ((step_px, 0, 0, 1), (-step_px, 0, 0, 1), (0, step_px, 0, 1), (0, -step_px, 0, 1),
                                   (0, 0, step_deg, 1), (0, 0, -step_deg, 1), (0, 0, 0, 1 + step_scale), (0, 0, 0, 1 - step_scale)):
                candidate = _similarity_about(centre, f, math.radians(deg), (dx, dy)) @ h
                cost = float(_trimmed(_lookup(dist, to_px(candidate, sub)[None], cap))[0])
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
    has_boundary = any(e.boundary for e in elements)
    plate_w = float(np.ptp(plate[:, 0])); plate_h = float(np.ptp(plate[:, 1]))

    # find the window on a small copy, derive the working scale from it, then do everything at TARGET_PX_PER_MM
    first = prepare(img_bgr, 1100)
    window1 = find_window(first)
    if window1 is None:
        return refuse("no frame window was found in the photograph")
    est = float(np.ptp(window1, axis=0).max()) / max(plate_w, plate_h, 1e-6)
    prep = prepare(img_bgr, int(np.clip(1100 * TARGET_PX_PER_MM / max(est, 1e-6), 1200, 3200)))
    window = find_window(prep)
    if window is None:
        return refuse("no frame window was found in the photograph")
    s = prep.scale
    scale0 = float(np.ptp(window, axis=0).max()) / max(plate_w, plate_h, 1e-6)     # px per mm, rough
    cap = CAP_MM * scale0
    inside = cv2.fillConvexPoly(np.zeros(prep.edges.shape, np.uint8), window.astype(np.int32), 255)
    k = int(max(3, round(0.9 * scale0))) | 1
    inside = cv2.erode(inside, np.ones((k, k), np.uint8))
    edges = prep.edges & inside
    dist = np.minimum(cv2.distanceTransform(255 - edges, cv2.DIST_L2, 3), cap).astype(np.float32)
    dist_blur = cv2.GaussianBlur(dist, (0, 0), max(1.0, 0.3 * scale0))

    all_points = np.vstack([e.points for e in movable])
    candidates = _coarse(all_points, dist_blur, window, plate, cap, has_boundary)
    best, second = candidates[0]["coarse_cost"], candidates[1]["coarse_cost"]
    diag["orientation"] = {"best_cost_mm": round(best / scale0, 3), "second_cost_mm": round(second / scale0, 3)}
    if best > ORIENTATION_MARGIN * second:
        return refuse("the orientation of the work is ambiguous: the best and the second best differ too little")

    refined = []
    fine = cv2.GaussianBlur(dist, (0, 0), 1.0)
    for cand in candidates[:2]:
        start = _polish(cand["pose"], all_points, fine, cap, window.mean(axis=0))
        h, anchors = _refine(start, elements, dist, cap)
        refined.append((len(anchors), h, anchors, cand))
    refined.sort(key=lambda item: -item[0])
    n_anchors, h, anchors, cand = refined[0]
    second_anchors = refined[1][0]
    diag["orientation"]["anchors_second"] = second_anchors
    if second_anchors >= max(3, SECOND_ORIENTATION_SHARE * n_anchors):
        return refuse("the orientation of the work is ambiguous: the best and the second best differ too little")
    diag["anchors"] = n_anchors
    scale = _px_per_mm(h, plate.mean(axis=0))
    if n_anchors < max(5, min(12, math.ceil(0.1 * len(movable)))):
        return refuse(f"only {n_anchors} elements matched the photograph")
    hn, good, src, dst, owner = _fit(h, elements, anchors, scale, 0.2)
    if hn is None or good is None or good.mean() < MIN_INLIER_FRACTION:
        return refuse("the matched elements disagree about the position of the work")
    h = hn

    # residual of the anchor outlines under the final transform, in mm
    resid = np.linalg.norm(to_px(h, src[good]) - dst[good], axis=1) / scale
    med, p90 = float(np.median(resid)), float(np.percentile(resid, 90))
    centres = np.array([elements[a["index"]].centroid for a in anchors])
    work_area = float(np.prod(np.ptp(np.vstack([e.points for e in movable]), axis=0)))
    hull = float(cv2.contourArea(cv2.convexHull(centres.astype(np.float32)))) if len(centres) >= 3 else 0.0
    diag.update(residual_median_mm=round(med, 3), residual_p90_mm=round(p90, 3),
                inlier_fraction=round(float(good.mean()), 3), spread=round(hull / max(work_area, 1e-9), 3))
    if med > MAX_RESIDUAL_MM[0] or p90 > MAX_RESIDUAL_MM[1]:
        return refuse(f"the outlines do not fit closely enough ({med:.2f} mm median)")
    if hull < MIN_SPREAD * work_area:
        return refuse("the matched elements are concentrated in one part of the work")

    details = _classify(h, elements, anchors, dist, window, scale, cap, plate, src, dst, owner, good)
    details.update(orientation={"mirror": bool(cand["mirror"]), "rotation_degrees": 90 * int(cand["k"]),
                                "best_cost_mm": round(best / scale0, 3), "second_cost_mm": round(second / scale0, 3),
                                "margin": round(best / second, 3), "anchors_second": second_anchors},
                   residual_median_mm=round(med, 3), residual_p90_mm=round(p90, 3), px_per_mm=round(scale / s, 3))
    to_full = np.diag([1 / s, 1 / s, 1.0])
    mm_to_image = to_full @ h
    details["window_px"] = (window / s).round(1).tolist()
    diag.update(details={k: v for k, v in details.items() if k != "statuses"})
    reflected = bool(np.linalg.det(mm_to_image[:2, :2]) < 0)
    matches = [{"element": elements[a["index"]].name, "center_mm": elements[a["index"]].centroid.round(3).tolist(),
                "center_px": (to_px(mm_to_image, elements[a["index"]].centroid[None])[0]).round(1).tolist()}
               for a in anchors]
    elements_ref = [(e.layer_index, e.region_index) for e in elements]
    details["element_refs"] = elements_ref
    return Registration(np.linalg.inv(mm_to_image), "element anchors", matches, round(med * scale / s, 2), reflected,
                        details=details)


def _refine(h, elements, dist, cap):
    anchors: list[dict] = []
    for radius_mm, cost_mm, distinct_mm in SCHEDULE:
        scale = _px_per_mm(h, np.mean([e.centroid for e in elements if len(e.points)], axis=0))
        found = _match_elements(h, elements, dist, scale, radius_mm, cap)
        chosen = [m for m in found if _is_anchor(m, cost_mm, distinct_mm)]
        if len(chosen) < 6:
            continue
        hn, good, *_ = _fit(h, elements, chosen, scale, 0.2)
        if hn is None:
            continue
        h, anchors = hn, chosen
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
        support = float((_lookup(dist, px, cap) <= 0.15 * scale).mean())
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
