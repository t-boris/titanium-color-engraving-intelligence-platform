"""Smooth contours for the shared borders of a split (feature vector-detail-and-colour-control, DEC-083, REQ-052).

A split stores every border once, as an *arc*: a polyline in mm from one junction to the next (or a closed loop). The
operator's slider is a strength in mm; ``smooth_arc`` turns one arc into cubic Béziers:

1. the arc is resampled at an even step along its length and low-passed with a Gaussian of that sigma; the ends stay where
   they are (the sequence is reflected through them, which also keeps the direction in which the arc leaves a junction), so
   the two regions next to a border and every arc meeting at a junction still share the same points;
2. a cubic Hermite spline is laid through knots of that smooth path, the tangent at a knot being the path's own tangent, so
   the curve is tangent-continuous inside the arc; the whole run starts as one interval and an interval that strays more than
   ``FIT_MM`` from the path is halved until none does. Junctions and the corners found before the smoothing (:func:`_corners`) keep their own tangent on each side.

A node is ``[x, y, c0x, c0y, c1x, c1y]`` in the format LightBurn's ``Path`` shape uses: the point, its out-handle control
point ``c0`` (towards the next node) and its in-handle control point ``c1`` (from the previous one); the first node of an open
arc has no in-handle and the last no out-handle (both equal the point).
"""
from __future__ import annotations

import math

import numpy as np

FIT_MM = 0.02                  # a segment strays at most this far from the smoothed path
FLAT_MM = 0.2                  # step along a curve when it is flattened to points (the deviation stays well below 0.01 mm)
MIN_STEP_MM = 0.04             # the smoothed path is sampled at sigma / STEP_DIVISOR, but not finer than this nor coarser than MAX_STEP_MM
MAX_STEP_MM = 0.25
STEP_DIVISOR = 4
CORNER_DEGREES = 70.0          # a turn of this size over that distance is an intended corner; tracing noise and tips narrower than it are not
CORNER_SIGMA_MM = 0.2          # corners are looked for in the path smoothed this much, so that tracing noise is no corner
CORNER_MM = 0.6                # the turn is measured between the points this far on either side, or one sigma if that is more
MAX_ROUNDS = 14


def _gauss_kernel(sigma_samples: float) -> np.ndarray:
    radius = max(1, math.ceil(3 * sigma_samples))
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma_samples) ** 2)
    return kernel / kernel.sum()


def _low_pass(points: np.ndarray, closed: bool, sigma_samples: float) -> np.ndarray:
    """Gaussian along the path; an open path keeps its ends (reflected through them, so the filter keeps them in place)."""
    kernel = _gauss_kernel(sigma_samples)
    r, n = len(kernel) // 2, len(points)
    if closed:
        padded = points[np.arange(-r, n + r) % n]
    else:
        k = np.minimum(np.arange(r, 0, -1), n - 1)
        padded = np.vstack([2 * points[0] - points[k], points, 2 * points[-1] - points[n - 1 - k[::-1]]])
    out = np.stack([np.convolve(padded[:, c], kernel, mode="valid") for c in range(2)], axis=1)
    if not closed:
        out[0], out[-1] = points[0], points[-1]
    return out


def _resample(points: np.ndarray, step: float) -> tuple[np.ndarray, float]:
    """The polyline at an even step along its length (the last point kept), and its length."""
    seg = np.hypot(*np.diff(points, axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    length = float(s[-1])
    count = max(int(round(length / step)) + 1, 3)
    t = np.linspace(0.0, length, count)
    return np.stack([np.interp(t, s, points[:, 0]), np.interp(t, s, points[:, 1])], axis=1), length


def _unit(v: np.ndarray) -> np.ndarray:
    norm = np.hypot(v[..., 0], v[..., 1])
    return v / np.where(norm > 1e-12, norm, 1.0)[..., None]


def _corners(points: np.ndarray, closed: bool, window_mm: float) -> list[int]:
    """Indexes of an open or closed path's samples where it turns by CORNER_DEGREES or more over ``window_mm`` (before smoothing)."""
    if closed:
        return _corners_of(points[:-1], True, window_mm)
    return _corners_of(points, False, window_mm)


def _corners_of(points: np.ndarray, closed: bool, window_mm: float) -> list[int]:
    n = len(points)
    if n < 5:
        return []
    seg = np.hypot(*np.diff(points, axis=0).T)
    step = float(seg.mean()) if seg.size else 0.0
    if step <= 0:
        return []
    w = max(1, int(round(window_mm / step)))
    idx = np.arange(n)
    points = _low_pass(points, closed, max(CORNER_SIGMA_MM / step, 0.5))
    if closed:
        before, after = points[(idx - w) % n], points[(idx + w) % n]
    else:
        before, after = points[np.clip(idx - w, 0, n - 1)], points[np.clip(idx + w, 0, n - 1)]
    a, b = _unit(points - before), _unit(after - points)
    turn = np.degrees(np.arccos(np.clip((a * b).sum(axis=1), -1.0, 1.0)))
    if not closed:
        turn[:w] = 0.0
        turn[-w:] = 0.0
    hot = np.flatnonzero(turn >= CORNER_DEGREES)
    picked: list[int] = []
    for i in hot:                                # one corner per run of samples: the sharpest
        if picked and i - picked[-1] <= w:
            if turn[i] > turn[picked[-1]]:
                picked[-1] = int(i)
        else:
            picked.append(int(i))
    return picked


def _bezier(p0, c0, c1, p1, u):
    """Points of cubic Béziers (arrays of shape (m, 2)) at the parameters ``u`` (shape (m,))."""
    u = u[:, None]
    v = 1.0 - u
    return v ** 3 * p0 + 3 * v ** 2 * u * c0 + 3 * v * u ** 2 * c1 + u ** 3 * p1


def _fit(path: np.ndarray, closed: bool, tolerance: float):
    """Knots of a tangent-continuous cubic Hermite spline through the samples ``path`` (an open run: for a closed one the last
    sample repeats the first). Returns the knot indexes, the unit tangents into and out of each knot and the arc length at every sample."""
    n = len(path)
    last = n - 1
    s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(path, axis=0).T))])
    knots = np.array([0, last], np.int64)          # the whole run as one curve; an interval that strays is halved

    def tangents(ks: np.ndarray):
        central = _unit(path[np.minimum(ks + 1, last)] - path[np.maximum(ks - 1, 0)])
        if closed:
            central[0] = central[-1] = _unit(path[1] - path[last - 1])
        else:
            central[0] = _unit(path[min(2, last)] - path[0])
            central[-1] = _unit(path[last] - path[max(last - 2, 0)])
        return central

    index = np.arange(n)
    for _ in range(MAX_ROUNDS):
        tangent = tangents(knots)
        a, b = knots[:-1], knots[1:]
        length = s[b] - s[a]
        c0 = path[a] + tangent[:-1] * (length / 3.0)[:, None]
        c1 = path[b] - tangent[1:] * (length / 3.0)[:, None]
        owner = np.clip(np.searchsorted(knots, index, side="right") - 1, 0, len(a) - 1)
        span = length[owner]
        u = np.clip(np.divide(s - s[a][owner], span, out=np.zeros(n), where=span > 0), 0.0, 1.0)
        error = np.hypot(*(_bezier(path[a][owner], c0[owner], c1[owner], path[b][owner], u) - path).T)
        worst = np.maximum.reduceat(error, knots[:-1])
        bad = np.flatnonzero((worst > tolerance) & (b - a >= 2))
        if not len(bad):
            break
        knots = np.sort(np.concatenate([knots, (a[bad] + b[bad]) // 2]))
    return knots, tangents(knots), s


def _nodes(path: np.ndarray, knots: np.ndarray, tangent: np.ndarray, s: np.ndarray) -> list[list[float]]:
    """The nodes of the spline: each knot with its out-handle control point (towards the next) and in-handle (from the previous)."""
    point = path[knots]
    third = np.diff(s[knots]) / 3.0
    c0, c1 = point.copy(), point.copy()
    c0[:-1] = point[:-1] + tangent[:-1] * third[:, None]
    c1[1:] = point[1:] - tangent[1:] * third[:, None]
    return np.hstack([point, c0, c1]).tolist()


def _smooth_run(samples: np.ndarray, closed: bool, sigma_samples: float, tolerance: float) -> list[list[float]]:
    """One run of evenly spaced samples (open, or closed with its last sample repeating the first) smoothed and fitted."""
    if closed:
        path = _low_pass(samples[:-1], True, sigma_samples)
        path = np.vstack([path, path[:1]])
    else:
        path = _low_pass(samples, False, sigma_samples)
    knots, tangent, s = _fit(path, closed, tolerance)
    nodes = _nodes(path, knots, tangent, s)
    nodes[0][0:2], nodes[-1][0:2] = samples[0].tolist(), samples[-1].tolist()
    return nodes


def _straight(points: np.ndarray) -> list[list[float]]:
    return [[float(x), float(y), float(x), float(y), float(x), float(y)] for x, y in points]


def smooth_arc(points, closed: bool, sigma_mm: float, tolerance_mm: float = FIT_MM) -> list[list[float]]:
    """Nodes (see the module) of the smooth cubic Bézier path that replaces an arc given as points in mm.

    The ends of an open arc stay where they are exactly; a closed arc's last node repeats its first. A corner of the arc (a turn the
    smoothing must not round off) splits it into runs that are smoothed alone, so the corner is a node with a tangent of its own on
    each side. ``sigma_mm`` of 0, or an arc too short to smooth, gives the arc as straight nodes without handles.
    """
    pts = np.asarray(points, np.float64)
    if sigma_mm <= 0 or len(pts) < 3:
        return _straight(pts)
    step = min(MAX_STEP_MM, max(MIN_STEP_MM, sigma_mm / STEP_DIVISOR))
    base, length = _resample(pts, step)
    if length < 4 * step:
        return _straight(pts)
    base[0], base[-1] = pts[0], pts[-1]
    sigma = sigma_mm / (length / (len(base) - 1))
    corners = _corners(base, closed, max(CORNER_MM, sigma_mm))
    if not corners:
        return _smooth_run(base, closed, sigma, tolerance_mm)
    if closed:                                   # start at a corner: the loop becomes an open run between corners
        first = corners[0]
        ring = np.roll(base[:-1], -first, axis=0)
        base = np.vstack([ring, ring[:1]])
        corners = [c - first for c in corners if c > first] + [c + len(ring) - first for c in corners if c < first]
        corners = sorted(set(corners) - {0})
    cut = [0] + [c for c in corners if 0 < c < len(base) - 1] + [len(base) - 1]
    nodes: list[list[float]] = []
    for a, b in zip(cut, cut[1:]):
        run = base[a:b + 1]
        piece = _smooth_run(run, False, sigma, tolerance_mm) if b - a >= 4 else _straight(run[[0, -1]])
        if nodes:                                # the corner: its in-handle from the run before, its out-handle from this one
            piece[0][4:6] = nodes[-1][4:6]
            nodes.pop()
        nodes.extend(piece)
    return nodes


def flatten(nodes: list[list[float]], step_mm: float = FLAT_MM) -> list[list[float]]:
    """Points along the curve through the nodes, about ``step_mm`` apart, ending at the last node (the first node included)."""
    if len(nodes) < 2:
        return [[n[0], n[1]] for n in nodes]
    arr = np.asarray(nodes, np.float64)
    p0, c0, c1, p1 = arr[:-1, 0:2], arr[:-1, 2:4], arr[1:, 4:6], arr[1:, 0:2]
    chord = np.hypot(*(p1 - p0).T) + np.hypot(*(c0 - p0).T) + np.hypot(*(c1 - c0).T) + np.hypot(*(p1 - c1).T)
    counts = np.maximum(2, np.ceil(chord / (2 * step_mm)).astype(int))
    out = [arr[0, 0:2]]
    for i, c in enumerate(counts):
        out.extend(_bezier(p0[i], c0[i], c1[i], p1[i], np.arange(1, c + 1) / c))
    return [[round(float(x), 5), round(float(y), 5)] for x, y in out]
