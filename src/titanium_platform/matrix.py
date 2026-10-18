"""A parameter matrix (LightBurn Material Test) recognised from its photograph (REQ-031, DEC-061).

The operator engraves LightBurn's Material Test: a grid of filled squares, one setting pair per square, two settings
varying along the two axes (often power across and speed, line interval, Q-pulse or passes down), the axis values
engraved beside the rows and under the columns, and the settings that stay fixed engraved above the grid. A
one-parameter test is a single column. There is no LightBurn file to read: the photograph itself carries the job.

1. the cells are found as near-square closed outlines on an exposure-normalised rendering of the RAW;
2. a lattice (integer cell coordinates -> photo pixels) is fitted to the cells of the dominant size; cells that are too
   faint to give an outline are still part of the lattice;
3. the extent of the grid is the connected block of lattice nodes whose interior differs from the gap around it and is
   uniform (a printed digit is not), containing the outlined cells;
4. the grid is rectified and its labels are read with tesseract when the program is installed (an optional system
   tool, not a Python dependency): the row values left of the grid, the column values below it (rotated text), the
   fixed settings above it and the two axis titles;
5. the axis values of a Material Test are evenly spaced, so a straight line is fitted robustly to the labels that were
   read (at least three must agree): a misread digit is repaired, and the rows and columns are trimmed to, or
   extended by, the labels that agree with the line;
6. the varying settings are named by the axis titles or by what the header does not list; every cell's full setting is
   the header's values plus its row's and column's.

Nothing read is trusted silently (REQ-003): the result is a proposal the operator confirms or corrects before any
observation is accepted. The confirmed specification becomes a generated LightBurn file with one filled square per
cell, so the photograph is checked and measured exactly as any other pair.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile

import cv2
import numpy as np

from . import photo as ph

PARAMS = ("power", "speed", "frequency", "pulse_width", "line_interval", "passes")
UNITS = {"power": "%", "speed": "mm/s", "frequency": "kHz", "pulse_width": "ns", "line_interval": "mm", "passes": ""}
LABELS = {"power": "Power", "speed": "Speed", "frequency": "Frequency", "pulse_width": "Q-Pulse", "line_interval": "Interval",
          "passes": "Passes"}
RANGES = {"power": (0.01, 100.0), "speed": (0.01, 50000.0), "frequency": (0.5, 5000.0), "pulse_width": (0.5, 2000.0),
          "line_interval": (0.0001, 5.0), "passes": (1.0, 500.0)}
# the usual range of each setting on a fibre / MOPA marking laser, used only to tell two candidate settings apart
TYPICAL = {"power": (1.0, 100.0), "speed": (10.0, 20000.0), "frequency": (10.0, 4000.0), "pulse_width": (1.0, 500.0),
           "line_interval": (0.0005, 0.2), "passes": (1.0, 20.0)}
TITLE_WORDS = (("pulse_width", r"pul|q[\W_]*p"), ("line_interval", r"interv|nterva"), ("frequency", r"freq|requen"),
               ("passes", r"pass"), ("speed", r"spe+d|peed"), ("power", r"pow|ower"))

WORK_LONG_SIDE = 1600            # resolution of the cell search
RECT_PX = 80                     # pixels per lattice pitch in the rectified grid used for reading labels
SQUARE_ASPECT = 0.8              # a cell outline is at least this square ...
SQUARE_FILL = 0.85               # ... and fills this share of its bounding rectangle
LATTICE_TOLERANCE = 0.15         # a cell belongs to the lattice when it lies this close (in pitches) to a node
CELL_CONTRAST_DE = 3.0           # interior against the gap around it
CELL_UNIFORM_L = 4.0             # standard deviation of L* inside a cell (a printed digit is far less uniform)
TEXT_DARKER = 25                 # a label stroke is darker (8-bit) than its local background by at most this threshold ...
TEXT_DARKER_MIN = 6              # ... and at least this one; between them it follows the contrast of the labels themselves
TEXT_SPECK = 0.003               # a dark mark smaller than this share of a cell's area is texture, not a stroke
MIN_CONSISTENT_LABELS = 3        # labels that must agree with one evenly spaced sequence
MAX_RELATIVE_TOLERANCE = 0.35    # a reading's printed precision must be finer than this share of the value it confirms
DEFAULT_PITCH_MM = 5.0           # LightBurn's Material Test default cell; only the shape of the generated file depends on it
OCR_TIMEOUT_S = 15


# -- the cells and the lattice ------------------------------------------------------------------------------------------
def find_squares(img_bgr: np.ndarray, exclude: list | None = None) -> list[tuple[float, float, float]]:
    """(x, y, side) in photo pixels of every near-square closed outline; ``exclude`` are polygons (photo px) to ignore."""
    height, width = img_bgr.shape[:2]
    s = WORK_LONG_SIDE / max(height, width)
    small = cv2.resize(img_bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
    area_max = 0.02 * small.shape[0] * small.shape[1]
    found = []
    for channel in range(3):
        c = cv2.GaussianBlur(lab[:, :, channel], (0, 0), 1.2)
        for lo, hi in ((20, 60), (10, 30)):
            edges = cv2.dilate(cv2.Canny(c, lo, hi), np.ones((2, 2), np.uint8))
            contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < 150 or area > area_max:
                    continue
                poly = cv2.approxPolyDP(contour, 0.06 * cv2.arcLength(contour, True), True)
                if len(poly) != 4 or not cv2.isContourConvex(poly):
                    continue
                (cx, cy), (rw, rh), _ = cv2.minAreaRect(poly)
                if min(rw, rh) / max(rw, rh) < SQUARE_ASPECT or area / (rw * rh) < SQUARE_FILL:
                    continue
                found.append((cx / s, cy / s, (rw + rh) / 2 / s))
    out: list[tuple[float, float, float]] = []
    for f in sorted(found, key=lambda f: -f[2]):
        if all(math.hypot(f[0] - g[0], f[1] - g[1]) > 0.4 * g[2] for g in out):
            out.append(f)
    for poly in exclude or []:
        contour = np.asarray(poly, np.float32).reshape(-1, 1, 2)
        out = [f for f in out if cv2.pointPolygonTest(contour, (float(f[0]), float(f[1])), False) < 0]
    return out


def _size_classes(squares: list) -> list[tuple[list, float]]:
    """The squares grouped by size (within 20 %), the most numerous group first, the larger size on a tie."""
    sizes = np.array([f[2] for f in squares])
    groups, taken = [], np.zeros(len(squares), bool)
    while not taken.all():
        best = None
        for s0 in sizes[~taken]:
            keep = (np.abs(np.log(sizes / s0)) < math.log(1.2)) & ~taken
            if best is None or (keep.sum(), s0) > (best[0], best[1]):
                best = (int(keep.sum()), float(s0), keep)
        groups.append(([f for f, k in zip(squares, best[2]) if k], float(np.median(sizes[best[2]]))))
        taken |= best[2]
    return groups


def fit_lattice(squares: list) -> dict | None:
    """The lattice of the largest set of equal squares that forms one: ``H`` maps integer cell coordinates (i, j) to
    photo pixels. Groups of other sizes (chart patches, the holes of a ruler's digits) are tried after it."""
    for cells, size in _size_classes(squares):
        if len(cells) < 2:
            break
        lattice = _fit_cells(cells, size)
        if lattice is not None:
            return lattice
    return None


def _fit_cells(cells: list, size: float) -> dict | None:
    c = np.array([[f[0], f[1]] for f in cells])
    d = c[None] - c[:, None]
    dist = np.linalg.norm(d, axis=2)
    disp = d[(dist > 0.9 * size) & (dist < 1.7 * size)]
    hor = disp[np.abs(disp[:, 0]) > np.abs(disp[:, 1])]
    ver = disp[np.abs(disp[:, 1]) >= np.abs(disp[:, 0])]
    hor = np.where(hor[:, :1] < 0, -hor, hor)
    ver = np.where(ver[:, 1:] < 0, -ver, ver)
    u = np.median(hor, axis=0) if len(hor) else None
    v = np.median(ver, axis=0) if len(ver) else None
    if u is None and v is None:
        return None
    if u is None:
        u = np.array([v[1], -v[0]])          # a single column: the cells are square, the pitch is the same across
    if v is None:
        v = np.array([-u[1], u[0]])
    basis = np.column_stack([u, v])
    best = None
    for k in range(len(c)):
        ij = np.linalg.solve(basis, (c - c[k]).T).T
        ok = np.linalg.norm(ij - np.round(ij), axis=1) < LATTICE_TOLERANCE
        if best is None or ok.sum() > best[0]:
            best = (int(ok.sum()), np.round(ij).astype(int), ok)
    _, ij, ok = best
    if ok.sum() < 2:
        return None
    ij, pts = ij[ok], c[ok]
    two_d = len(np.unique(ij[:, 0])) > 1 and len(np.unique(ij[:, 1])) > 1
    if two_d and len(pts) >= 6:
        H, _ = cv2.findHomography(ij.astype(np.float32), pts.astype(np.float32), 0)
    else:
        origin = pts.mean(axis=0) - ij.mean(axis=0) @ np.vstack([u, v])
        H = np.array([[u[0], v[0], origin[0]], [u[1], v[1], origin[1]], [0, 0, 1.0]])
    residual = float(np.median(np.linalg.norm(to_px(H, ij) - pts, axis=1)))
    pitch = float((np.linalg.norm(to_px(H, [[1, 0]]) - to_px(H, [[0, 0]])) + np.linalg.norm(to_px(H, [[0, 1]]) - to_px(H, [[0, 0]]))) / 2)
    return {"H": H, "cells": [tuple(map(int, x)) for x in ij], "size_px": size, "pitch_px": pitch, "residual_px": residual,
            "squares_used": [tuple(map(float, f)) for f, k in zip(cells, ok) if k]}


def to_px(H: np.ndarray, pts) -> np.ndarray:
    p = np.c_[np.asarray(pts, float), np.ones(len(pts))] @ np.asarray(H, float).T
    return p[:, :2] / p[:, 2:3]


def _lab_image(img_bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(cv2.GaussianBlur(img_bgr, (0, 0), 2), cv2.COLOR_BGR2LAB).astype(np.float32)
    lab[:, :, 0] *= 100 / 255
    lab[:, :, 1:] -= 128
    return lab


def _node_stats(lab: np.ndarray, H: np.ndarray, i: int, j: int) -> tuple[float, float] | None:
    """Contrast of a lattice node's interior against the gap around it, and how uniform the interior is."""
    height, width = lab.shape[:2]

    def take(offsets):
        px = to_px(H, [(i + a, j + b) for a, b in offsets])
        x, y = np.rint(px[:, 0]).astype(int), np.rint(px[:, 1]).astype(int)
        ok = (x >= 0) & (x < width) & (y >= 0) & (y < height)
        return lab[y[ok], x[ok]] if ok.mean() > 0.8 else None

    grid = np.linspace(-0.3, 0.3, 7)
    inner = take([(a, b) for a in grid for b in grid])
    side = np.linspace(-0.35, 0.35, 7)
    gap = take([(a, b) for a in side for b in (-0.5, 0.5)] + [(b, a) for a in side for b in (-0.5, 0.5)])
    if inner is None or gap is None:
        return None
    return float(np.linalg.norm(np.median(inner, 0) - np.median(gap, 0))), float(np.std(inner[:, 0]))


def grid_extent(lab: np.ndarray, lattice: dict) -> tuple[int, int, int, int]:
    """(i0, i1, j0, j1): the connected block of cell-like nodes that holds the most outlined cells."""
    cells = np.array(lattice["cells"])
    i_lo, j_lo = cells.min(axis=0) - 4
    i_hi, j_hi = cells.max(axis=0) + 4
    accepted = set(map(tuple, cells))
    for i in range(i_lo, i_hi + 1):
        for j in range(j_lo, j_hi + 1):
            s = _node_stats(lab, lattice["H"], i, j)
            if s is not None and s[0] >= CELL_CONTRAST_DE and s[1] < CELL_UNIFORM_L:
                accepted.add((i, j))
    outlined = set(map(tuple, cells))
    seen: set = set()
    best: set = set()
    for start in accepted:
        if start in seen:
            continue
        stack, comp = [start], set()
        while stack:
            q = stack.pop()
            if q in seen or q not in accepted:
                continue
            seen.add(q)
            comp.add(q)
            stack += [(q[0] + 1, q[1]), (q[0] - 1, q[1]), (q[0], q[1] + 1), (q[0], q[1] - 1)]
        if (len(comp & outlined), len(comp)) > (len(best & outlined), len(best)):
            best = comp
    xs, ys = [q[0] for q in best], [q[1] for q in best]
    return min(xs), max(xs), min(ys), max(ys)


# -- reading the labels -------------------------------------------------------------------------------------------------
def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def _tesseract(img: np.ndarray, psm: int, whitelist: str | None = None) -> str:
    if not ocr_available():
        return ""
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "label.png")
        cv2.imwrite(path, img)
        cmd = ["tesseract", path, "-", "--psm", str(psm)] + (["-c", f"tessedit_char_whitelist={whitelist}"] if whitelist else [])
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=OCR_TIMEOUT_S).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""


OCR_SCALE = 2.5
LABEL_WINDOWS = (1.6, 2.2)      # lengths (in pitches) of the windows a label is read from, measured from the grid
CLOSINGS = (0, 5, 7)            # hollow (outlined) engraved glyphs are filled by closing with these kernels


def _ink(gray: np.ndarray, closing: int, keep_border: bool = False) -> np.ndarray:
    """Dark-on-white rendering of a text crop for tesseract: Otsu threshold of the enlarged crop, hollow strokes closed,
    specks and pieces of neighbouring text cut by the crop's left or right edge removed; decimal points (small marks
    in the lower half of the text line, between its glyphs) are kept."""
    if gray.size == 0 or min(gray.shape) < 4:
        return np.full((40, 40), 255, np.uint8)
    up = cv2.resize(gray, None, fx=OCR_SCALE, fy=OCR_SCALE, interpolation=cv2.INTER_CUBIC).astype(np.float32)
    # the plate's shade changes across a crop (a neighbouring test, a shadow): divide by the local background first
    k = max(15, int(min(up.shape) * 0.6)) | 1
    background = cv2.morphologyEx(up, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    flat = np.clip(up / np.maximum(background, 1.0) * 200, 0, 255).astype(np.uint8)
    _, bw = cv2.threshold(cv2.GaussianBlur(flat, (0, 0), 1.2), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = (bw == 0).astype(np.uint8)
    if closing:
        ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (closing, closing)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    height, width = ink.shape
    keep = np.zeros(n, bool)
    if keep_border:             # several lines of text: drop only specks
        keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= 20
    else:
        glyphs = [c for c in range(1, n) if stats[c, 3] >= 0.3 * height and stats[c, 4] >= 40
                  and stats[c, 0] > 0 and stats[c, 0] + stats[c, 2] < width]
        for c in glyphs:
            keep[c] = True
        if glyphs:
            top = min(stats[c, 1] for c in glyphs)
            bottom = max(stats[c, 1] + stats[c, 3] for c in glyphs)
            left = min(stats[c, 0] for c in glyphs)
            right = max(stats[c, 0] + stats[c, 2] for c in glyphs)
            line = bottom - top
            for c in range(1, n):
                x, y, w, h, area = stats[c]
                if (not keep[c] and h < 0.3 * line and w < 0.3 * line and area >= 0.004 * line * line and
                        y >= top + 0.55 * line and y + h <= bottom + 0.1 * line and x > left and x + w < right):
                    keep[c] = True
    ink = keep[labels].astype(np.uint8)
    return cv2.copyMakeBorder(255 - ink * 255, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)


def _read(gray: np.ndarray, psm: int, whitelist: str | None = None) -> list[str]:
    """Every distinct reading of a crop over the binarisation variants."""
    out = []
    for k in CLOSINGS:
        text = _tesseract(_ink(gray, k), psm, whitelist)
        if text and text not in out:
            out.append(text)
    return out


def _run(profile: np.ndarray, start: int, step: int, max_gap: int, reach: int) -> tuple[int, int] | None:
    """The run of text positions in ``profile`` met first when walking from ``start`` by ``step`` (within ``reach``),
    with gaps no longer than ``max_gap``."""
    first = last = None
    gap = 0
    k = start
    while 0 <= k < len(profile):
        if profile[k]:
            if first is None:
                first = k
            last, gap = k, 0
        elif first is not None:
            gap += 1
            if gap > max_gap:
                break
        elif abs(k - start) > reach:
            break
        k += step
    return None if first is None else (min(first, last), max(first, last))


class _Rectified:
    """The grid region warped upright: lattice point (i, j) sits at ((i - L) * P, (j - T) * P)."""

    def __init__(self, img_bgr: np.ndarray, H: np.ndarray, i0: int, i1: int, j0: int, j1: int):
        self.P = RECT_PX
        self.L, self.T = i0 - 5.0, j0 - 3.4
        R, B = i1 + 5.0, j1 + 4.0
        size = (int((R - self.L) * self.P), int((B - self.T) * self.P))
        rect_to_lattice = np.array([[1 / self.P, 0, self.L], [0, 1 / self.P, self.T], [0, 0, 1.0]])
        self.bgr = cv2.warpPerspective(img_bgr, np.asarray(H, float) @ rect_to_lattice, size,
                                       flags=cv2.INTER_AREA | cv2.WARP_INVERSE_MAP, borderValue=(255, 255, 255))
        self.gray = cv2.cvtColor(self.bgr, cv2.COLOR_BGR2GRAY)
        darker = cv2.medianBlur(self.gray, 31).astype(int) - self.gray.astype(int)
        self.darker = np.clip(darker, 0, 255).astype(np.float32)
        # how much darker a label stroke is depends on the lighting and the engraving: measured where the row labels are
        P = self.P
        zone = darker[max(0, self.y(j0) - P):self.y(j1) + P, max(0, self.x(i0) - 3 * P):max(1, self.x(i0) - P // 2)]
        if zone.size:
            mad = float(np.median(np.abs(zone - np.median(zone))))
            self.threshold = float(np.clip(max(0.35 * np.percentile(zone, 99.5), 4.5 * mad), TEXT_DARKER_MIN, TEXT_DARKER))
        else:
            self.threshold = float(TEXT_DARKER)
        text = (darker > self.threshold).astype(np.uint8)
        # specks of the metal's texture are not strokes: a stroke of a digit is far larger
        n, labels, stats, _ = cv2.connectedComponentsWithStats(text, 8)
        keep = stats[:, cv2.CC_STAT_AREA] >= TEXT_SPECK * P * P
        keep[0] = False
        self.text = keep[labels]

    def x(self, i: float) -> int:
        return int(round((i - self.L) * self.P))

    def y(self, j: float) -> int:
        return int(round((j - self.T) * self.P))

    def crop(self, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        h, w = self.gray.shape
        return self.gray[max(0, y0):min(h, y1), max(0, x0):min(w, x1)]

    def band(self, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        h, w = self.text.shape
        return self.text[max(0, y0):min(h, y1), max(0, x0):min(w, x1)]


def _tesseract_words(img: np.ndarray, psm: int, whitelist: str | None = None) -> list[tuple[str, float, float]]:
    """(text, centre x, centre y) of every word tesseract finds, in the pixels of ``img``."""
    if not ocr_available():
        return []
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "strip.png")
        cv2.imwrite(path, img)
        cmd = ["tesseract", path, "-", "--psm", str(psm)] + (["-c", f"tessedit_char_whitelist={whitelist}"] if whitelist else []) + ["tsv"]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=OCR_TIMEOUT_S).stdout
        except (OSError, subprocess.SubprocessError):
            return []
    words = []
    for line in out.splitlines()[1:]:
        f = line.split("\t")
        if len(f) >= 12 and f[0] == "5" and f[11].strip():
            left, top, w, h = (float(v) for v in f[6:10])
            words.append((f[11].strip(), left + w / 2, top + h / 2))
    return words


def _sane(fit: dict, lo: int, hi: int) -> tuple[dict, int, int]:
    """A LightBurn sequence is positive on every row. When a well supported sequence reaches zero at an end of the
    block, that end is not a row of cells (it is the band of column labels, say) and the block stops before it; a
    sequence that is not positive inside its own labels is no sequence at all."""
    if fit["a"] is None:
        return fit, lo, hi
    if not fit.get("single") and fit["b"] == 0:
        return {**fit, "a": None, "b": None, "inliers": []}, lo, hi
    positive = [k for k in range(lo, hi + 1) if fit["a"] + fit["b"] * k > 0]
    supported = len(fit["inliers"]) >= 5 and positive and min(fit["inliers"]) >= positive[0] and max(fit["inliers"]) <= positive[-1]
    if len(positive) == hi - lo + 1:
        return fit, lo, hi
    if supported and positive == list(range(positive[0], positive[-1] + 1)):
        return fit, positive[0], positive[-1]
    return {**fit, "a": None, "b": None, "inliers": []}, lo, hi


def _merge(a: dict, b: dict) -> dict:
    out = {k: list(v) for k, v in a.items()}
    for k, texts in b.items():
        out.setdefault(k, [])
        out[k] += [x for x in texts if x not in out[k]]
    return out


def _strip_readings(r: _Rectified, axis: str, i0: int, i1: int, j0: int, j1: int, found: dict) -> dict[int, list[str]]:
    """The labels of one axis read as one strip (faint, outlined digits are read better in context than alone): every
    number found is given to the row (or column) whose centre it sits on. The strip is bounded by the labels found one
    by one, so that the axis title and the ruler stay out of it."""
    P = r.P
    out: dict[int, list[str]] = {}
    if axis == "y":
        lefts = [v["left"] for v in found.values() if v.get("like")]
        x0 = (min(lefts) - int(0.1 * P)) if lefts else r.x(i0) - int(2.2 * P)
        x1 = r.x(i0) - int(0.5 * P)
        y0, y1 = r.y(j0 - 2) - int(0.5 * P), r.y(j1 + 2) + int(0.5 * P)
        crop = r.crop(y0, y1, x0, x1)
    else:
        bottoms = [v["bottom"] for v in found.values() if v.get("like")]
        x0, x1 = r.x(i0 - 2) - int(0.5 * P), r.x(i1 + 2) + int(0.5 * P)
        y0 = r.y(j1) + int(0.5 * P)
        y1 = (max(bottoms) + int(0.1 * P)) if bottoms else r.y(j1) + int(2.2 * P)
        crop = cv2.rotate(r.crop(y0, y1, x0, x1), cv2.ROTATE_90_CLOCKWISE)
    x0, y0 = max(0, x0), max(0, y0)
    for k in (0, 5):
        for text, cx, cy in _tesseract_words(_ink(crop, k, keep_border=True), 6, "0123456789."):
            # back to rectified pixels: undo the border and the enlargement (and the rotation for the columns)
            u, v = (cx - 20) / OCR_SCALE, (cy - 20) / OCR_SCALE
            if axis == "y":
                index = int(round((y0 + v) / P + r.T))
            else:
                index = int(round((x0 + v) / P + r.L))
            out.setdefault(index, [])
            if text not in out[index]:
                out[index].append(text)
    return out


def _span(darker: np.ndarray, start: int, step: int, P: int) -> tuple[int, int, float] | None:
    """The run of a label along a band of the darkness map (axis 1 runs along the label), walking from ``start`` by
    ``step``: each label gets its own threshold, 0.4 of the darkest strokes near the grid, so that a faint outlined
    label is found whole and a strong one does not merge with its neighbours."""
    if darker.size == 0:
        return None
    middle = darker[int(darker.shape[0] * 0.2):int(darker.shape[0] * 0.8)]
    profile = np.percentile(middle, 95, axis=0)
    lo, hi = (max(0, start - int(2.6 * P)), start + 1) if step < 0 else (start, min(len(profile), start + int(2.6 * P)))
    zone = profile[lo:hi]
    if not zone.size:
        return None
    level = max(float(TEXT_DARKER_MIN), 0.4 * float(np.percentile(zone, 98)))
    run = _run(profile > level, start, step, int(0.22 * P), int(1.0 * P))
    return None if run is None else (run[0], run[1], level)


def _dense_block(profile: np.ndarray, P: int) -> tuple[int, int] | None:
    """Across a label (its height): the contiguous block of text around the densest line near the middle of the band;
    the edge of a neighbouring label or a gap line at the band's edge is not part of it."""
    if not len(profile) or profile.max() <= 1:
        return None
    middle = len(profile) // 2
    reach = int(0.35 * P)
    lo_, hi_ = max(0, middle - reach), min(len(profile), middle + reach + 1)
    peak = lo_ + int(np.argmax(profile[lo_:hi_]))
    on = profile > max(1, 0.12 * profile[peak])
    a = b = peak
    gap = int(0.06 * P) + 1
    while a > 0 and on[max(0, a - gap):a].any():
        a -= 1
    while b < len(profile) - 1 and on[b + 1:b + 1 + gap].any():
        b += 1
    while a < peak and not on[a]:
        a += 1
    while b > peak and not on[b]:
        b -= 1
    return a, b


def _row_label(r: _Rectified, j: int, i0: int, i1: int) -> dict | None:
    """The label left of row ``j``: its readings, where it starts, whether it looks like a row label (it ends at the
    grid, it is centred on the row) and whether it stands alone (no text runs on over the row's cells, as a header line
    would)."""
    P = r.P
    yc = r.y(j)
    y0, y1 = yc - int(0.5 * P), yc + int(0.5 * P)
    right = r.x(i0) - int(0.55 * P)
    if y0 < 0 or y1 > r.gray.shape[0] or right <= 0:
        return None
    band = r.darker[y0:y1, :right]
    # the rotated axis title runs along the labels and often touches them; it crosses the whole height of the band,
    # a digit never does, so those columns end the label
    strong = band > max(float(TEXT_DARKER_MIN), 0.4 * float(np.percentile(band[:, -int(2.6 * P):], 99.5)))
    crossing = strong[:3].any(axis=0) & strong[-3:].any(axis=0) & (strong.sum(axis=0) > 0.8 * strong.shape[0])
    band = band.copy()
    band[:, crossing] = 0
    span = _span(band, band.shape[1] - 1, -1, P)
    if span is None:
        return None
    a, b, level = span
    block = _dense_block((band[:, a:b + 1] > level).sum(axis=1), P)
    if block is None:
        return None
    top, bottom = y0 + block[0], y0 + block[1]
    over_cells = r.band(top, bottom + 1, r.x(i0) - int(0.4 * P), r.x(i1) + int(0.4 * P))
    like = (b >= band.shape[1] - 1 - int(0.35 * P) and abs((top + bottom) / 2 - yc) < 0.25 * P
            and 0.2 * P < bottom - top < 1.0 * P)
    alone = not ((over_cells.sum(axis=0) > 1).mean() > 0.15 if over_cells.size else False)
    texts = _read(r.crop(top - 8, bottom + 9, a - 8, b + 9), 7, "0123456789.")
    return {"texts": texts, "left": a, "like": bool(like), "alone": bool(alone)}


def _column_label(r: _Rectified, i: int, j0: int, j1: int) -> dict | None:
    """The rotated label under column ``i``: its readings, where it ends, whether it looks like a column label (it
    starts right under the grid, centred on the column) and whether it stands alone (no text runs through the cells)."""
    P = r.P
    xc = r.x(i)
    x0, x1 = xc - int(0.5 * P), xc + int(0.5 * P)
    top = r.y(j1) + int(0.55 * P)
    if x0 < 0 or x1 > r.gray.shape[1] or top >= r.gray.shape[0]:
        return None
    band = r.darker[top:top + int(2.6 * P), x0:x1].T          # rows: across the column, columns: downwards
    span = _span(band, 0, 1, P)
    if span is None:
        return None
    a, b, level = span
    block = _dense_block((band[:, a:b + 1] > level).sum(axis=1), P)
    if block is None:
        return None
    left, right = x0 + block[0], x0 + block[1]
    over_cells = r.band(r.y(j0) - int(0.4 * P), r.y(j1) + int(0.4 * P), left, right + 1)
    like = a <= int(0.35 * P) and abs((left + right) / 2 - xc) < 0.25 * P and 0.2 * P < right - left < 1.0 * P
    alone = not ((over_cells.sum(axis=1) > 1).mean() > 0.15 if over_cells.size else False)
    crop = r.crop(top + a - 8, top + b + 9, left - 8, right + 9)
    texts = _read(cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE), 7, "0123456789.")
    return {"texts": texts, "bottom": top + b, "like": bool(like), "alone": bool(alone)}


def _header(r: _Rectified, i0: int, i1: int, j0: int) -> list[str]:
    """The fixed settings above the grid: the block of text lines nearest above it, around its centre."""
    P = r.P
    centre = (r.x(i0) + r.x(i1)) // 2
    half = max((r.x(i1) - r.x(i0)) // 2 + int(0.5 * P), int(3.0 * P))
    y_bottom = r.y(j0) - int(0.55 * P)
    region = r.band(y_bottom - int(2.6 * P), y_bottom, centre - half, centre + half)
    if region.size == 0:
        return []
    # a line of text fills a good share of the row; scattered marks of the metal do not
    dense = region.sum(axis=1) > max(3, 0.06 * region.shape[1])
    lines = _run(dense, region.shape[0] - 1, -1, int(0.25 * P), int(1.2 * P))
    if lines is None:
        return []
    top, bottom = y_bottom - int(2.6 * P) + lines[0], y_bottom - int(2.6 * P) + lines[1]
    top = max(top, bottom - int(1.8 * P))           # LightBurn prints at most three short lines
    row_band = r.band(top, bottom + 1, 0, r.text.shape[1])
    cols = row_band.sum(axis=0) > max(1, 0.05 * row_band.shape[0])
    left = _run(cols, centre, -1, int(0.35 * P), int(3.0 * P))
    right_ = _run(cols, centre, 1, int(0.35 * P), int(3.0 * P))
    spans = [s for s in (left, right_) if s]
    if not spans:
        return []
    a, b = min(s[0] for s in spans), max(s[1] for s in spans)
    crop = r.crop(top - 8, bottom + 9, a - 10, b + 11)
    out = []
    for k in (0, 5):
        text = _tesseract(_ink(crop, k, keep_border=True), 6)
        if text and text not in out:
            out.append(text)
    return out


def _titles(r: _Rectified, i0: int, i1: int, j0: int, j1: int, label_left: int | None, label_bottom: int | None) -> tuple[list[str], list[str]]:
    """(x title readings, y title readings): the axis titles below the column labels and left of the row labels."""
    P = r.P
    x_title: list[str] = []
    y_title: list[str] = []
    if label_bottom is not None:
        x0, x1 = r.x(i0) - int(1.5 * P), r.x(i1) + int(1.5 * P)
        region = r.band(label_bottom + 4, label_bottom + int(1.4 * P), x0, x1)
        lines = _run(region.sum(axis=1) > 1, 0, 1, int(0.15 * P), int(0.8 * P)) if region.size else None
        if lines:
            top, bottom = label_bottom + 4 + lines[0], label_bottom + 4 + lines[1]
            for k in (0, 5):
                text = _tesseract(_ink(r.crop(top - 6, bottom + 7, x0, x1), k, keep_border=True), 7)
                if text:
                    x_title.append(text)
    if label_left is not None:
        y0, y1 = r.y(j0) - int(0.5 * P), r.y(j1) + int(0.5 * P)
        band = r.band(y0, y1, 0, max(1, label_left - 3))
        run = _run(band.sum(axis=0) > 2, band.shape[1] - 1, -1, int(0.15 * P), int(0.8 * P)) if band.size else None
        if run:
            a, b = run
            crop = cv2.rotate(r.crop(y0, y1, a - 6, b + 7), cv2.ROTATE_90_CLOCKWISE)
            for k in (0, 5):
                text = _tesseract(_ink(crop, k, keep_border=True), 7)
                if text:
                    y_title.append(text)
    return x_title, y_title


# -- interpretation -----------------------------------------------------------------------------------------------------
def parse_header(text: str) -> dict:
    """The fixed settings LightBurn prints above a Material Test, tolerant of the usual misreads."""
    t = text.replace(",", ".")
    found: dict = {}
    # the setting's name decides; the unit after the number is often misread ("ns" as "rs"), so it is not required
    patterns = (("line_interval", r"[il1|][nmt]{0,2}er\w*\W{0,3}([0-9]*\.[0-9]+|[0-9]+)"),
                ("passes", r"pa[s5]+\w*\W{0,3}([0-9]+)"),
                ("frequency", r"fr\w*n\w*y\W{0,3}([0-9]+(?:\.[0-9]+)?)"),
                ("pulse_width", r"[qo0][\W_]{0,2}pu\w*\W{0,3}([0-9]+(?:\.[0-9]+)?)"),
                ("speed", r"[s5]pe+d\W{0,3}([0-9]+(?:\.[0-9]+)?)"),
                ("power", r"pow\w*\W{0,3}([0-9]+(?:\.[0-9]+)?)"))
    for param, pattern in patterns:
        m = re.search(pattern, t, re.I)
        if m:
            try:
                value = float(m.group(1))
            except ValueError:
                continue
            lo, hi = RANGES[param]
            if lo <= value <= hi:
                found[param] = value
    return found


def param_of_title(text: str) -> str | None:
    for param, pattern in TITLE_WORDS:
        if re.search(pattern, text or "", re.I):
            return param
    return None


def _candidates(texts) -> list[tuple[float, float, int]]:
    """(value, tolerance, decimal shift) readings of a label over all its readings: as printed, and with a lost decimal
    point put back (a shift; the fit prefers readings without one)."""
    out: list[tuple[float, float, int]] = []
    for text in ([texts] if isinstance(texts, str) else (texts or [])):
        digits = re.sub(r"[^0-9.]", "", text or "").strip(".")
        # LightBurn prints at least two digits ("1.0", "40.0", "1500") and never a zero value
        if not digits or digits.count(".") > 1 or len(digits.replace(".", "")) < 2:
            continue
        try:
            value = float(digits)
        except ValueError:
            continue
        if value == 0:
            continue
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        options = [(value, 0.6 * 10 ** -decimals, 0)]
        if "." not in digits:
            options += [(value / 10 ** s, 0.6 * 10 ** -s, s) for s in (1, 2, 3, 4)]
        for o in options:
            if all(abs(o[0] - q[0]) > 1e-12 or o[2] != q[2] for q in out):
                out.append(o)
    return out


def fit_axis(labels: dict, need: int | None = None) -> dict:
    """An evenly spaced sequence through the labels (index -> readings): value(k) = a + b * k. At least three labels must
    agree within their printed precision (or all of them when fewer than three were read); readings without a shifted
    decimal point are preferred; the line is refined by least squares on the agreeing labels."""
    parsed = {k: _candidates(v) for k, v in labels.items()}
    parsed = {k: c for k, c in parsed.items() if c}
    out = {"a": None, "b": None, "inliers": [], "read": len(parsed), "decimals": 0, "single": False}
    if not parsed:
        return out
    keys = sorted(parsed)
    if len(keys) == 1:
        texts = labels[keys[0]] if not isinstance(labels[keys[0]], str) else [labels[keys[0]]]
        unshifted = [c for c in parsed[keys[0]] if c[2] == 0]
        dotted = [c for c, txt in zip(unshifted, [x for x in texts if _candidates(x)]) if "." in txt]
        pool = dotted or unshifted or parsed[keys[0]]
        values = [c[0] for c in pool]
        value = max(set(values), key=values.count)
        alternatives = [float(value)] + sorted({float(c[0]) for c in parsed[keys[0]]} - {float(value)}, key=lambda v: abs(v - value))
        return {**out, "a": float(value), "b": 0.0, "inliers": keys, "single": True, "alternatives": alternatives,
                "decimals": _decimals_of(labels[keys[0]])}
    need = min(MIN_CONSISTENT_LABELS, len(keys)) if need is None else max(need, 2)
    best = None
    for x, k in enumerate(keys):
        for k2 in keys[x + 1:]:
            for va, _, sa in parsed[k]:
                for vb, _, sb in parsed[k2]:
                    b = (vb - va) / (k2 - k)
                    if b == 0:
                        continue
                    a = va - b * k
                    chosen, weight, err = {}, 0.0, 0.0
                    for q in keys:
                        pred = a + b * q
                        fits = [(c[2], abs(c[0] - pred) / max(c[1], 0.002 * abs(pred)), c[0]) for c in parsed[q]
                                if abs(c[0] - pred) <= max(c[1], 0.002 * abs(pred)) and c[1] <= MAX_RELATIVE_TOLERANCE * abs(pred)]
                        if fits:
                            s, e, v = min(fits)
                            chosen[q], weight, err = v, weight + (1.0 if s == 0 else 0.5), err + e
                    # a label that agrees only with its decimal point moved is a repair: it counts half
                    score = (weight, len(chosen), -err)
                    if best is None or score > best[0]:
                        best = (score, chosen)
    if best is None or len(best[1]) < need or best[0][0] < min(2.0, need):
        return out          # at least two labels read as printed must carry the sequence
    chosen = best[1]
    ks = np.array(sorted(chosen), float)
    vs = np.array([chosen[k] for k in sorted(chosen)])
    b, a = np.polyfit(ks, vs, 1) if len(ks) >= 2 else (0.0, float(vs[0]))
    return {**out, "a": float(a), "b": float(b), "inliers": [int(k) for k in ks],
            "decimals": max(_decimals_of(labels[int(k)]) for k in ks)}


def _decimals_of(texts) -> int:
    best = 0
    for text in ([texts] if isinstance(texts, str) else (texts or [])):
        digits = re.sub(r"[^0-9.]", "", text or "").strip(".")
        if "." in digits:
            best = max(best, len(digits.split(".")[1]))
    return best


def _axis_values(fit: dict, start: int, count: int) -> list[float] | None:
    """The value of every row (or column): LightBurn spaces them evenly between a first and a last value the operator
    typed, printed with a fixed number of decimals; the ends are therefore rounded to that precision and the values
    between them interpolated, which removes the rounding of the printed labels from the fit."""
    if fit["a"] is None:
        return None
    decimals = int(fit.get("decimals") or 0)
    first = round(float(fit["a"] + fit["b"] * start), decimals)
    if count == 1:
        return [first]
    last = round(float(fit["a"] + fit["b"] * (start + count - 1)), decimals)
    return [round(first + (last - first) * k / (count - 1), 6) for k in range(count)]


def parse_headers(texts: list[str]) -> dict:
    """The fixed settings from every reading of the header: a setting read the same way more often wins."""
    votes: dict = {}
    for text in texts:
        for p, v in parse_header(text).items():
            votes.setdefault(p, {}).setdefault(v, 0)
            votes[p][v] += 1
    return {p: max(vs.items(), key=lambda kv: kv[1])[0] for p, vs in votes.items()}


def interpret(header_texts: list[str], x_titles: list[str], y_titles: list[str], cols: int, rows: int, x_fit: dict,
              y_fit: dict, i0: int, j0: int) -> dict:
    """The proposed specification of a matrix: the setting along each axis, its values per column / row, the fixed
    settings, and what is still missing."""
    fixed = parse_headers(header_texts)
    x_param = next((p for p in map(param_of_title, x_titles) if p), None)
    y_param = next((p for p in map(param_of_title, y_titles) if p), None)
    if x_param is not None and x_param == y_param:
        x_param = y_param = None
    absent = [p for p in PARAMS if p not in fixed]
    if cols > 1 and rows > 1:
        if x_param is None and "power" in absent and y_param != "power":
            x_param = "power"
        rest = [p for p in absent if p not in (x_param, y_param)]
        if y_param is None and x_param is not None and len(rest) == 1:
            y_param = rest[0]
        if x_param is None and y_param is not None and len(rest) == 1:
            x_param = rest[0]
    elif rows > 1:              # one column: the rows vary, the value under the column is one more setting
        x_param = x_param or ("power" if "power" in absent else None)
        rest = [p for p in absent if p != x_param]
        if y_param is None and len(rest) == 1:
            y_param = rest[0]
    else:                       # one row: the columns vary, the value beside the row is one more setting
        y_param = y_param or ("power" if "power" in absent and x_param != "power" else None)
        rest = [p for p in absent if p != y_param]
        if x_param is None and len(rest) == 1:
            x_param = rest[0]
    x_values, y_values = _axis_values(x_fit, i0, cols), _axis_values(y_fit, j0, rows)
    # still two candidates for an axis: the one whose usual range holds the values read
    for axis in ("x", "y"):
        values = x_values if axis == "x" else y_values
        if (x_param if axis == "x" else y_param) is not None or not values:
            continue
        taken = y_param if axis == "x" else x_param
        options = [p for p in absent if p != taken and TYPICAL[p][0] <= min(values) and max(values) <= TYPICAL[p][1]]
        if len(options) == 1:
            if axis == "x":
                x_param = options[0]
            else:
                y_param = options[0]
    # a single label (one column or one row) read with a lost decimal point: the reading in the setting's range
    for param, fit_, axis in ((x_param, x_fit, "x"), (y_param, y_fit, "y")):
        values = x_values if axis == "x" else y_values
        if param and fit_.get("single") and values and len(values) == 1 and not RANGES[param][0] <= values[0] <= RANGES[param][1]:
            good = [v for v in fit_.get("alternatives", []) if TYPICAL[param][0] <= v <= TYPICAL[param][1]]
            if good:
                if axis == "x":
                    x_values = [good[0]]
                else:
                    y_values = [good[0]]
    for p in (x_param, y_param):
        fixed.pop(p, None)
    spec = {"x": {"param": x_param, "values": x_values, "decimals": x_fit.get("decimals", 0)},
            "y": {"param": y_param, "values": y_values, "decimals": y_fit.get("decimals", 0)},
            "fixed": {p: fixed.get(p) for p in PARAMS if p not in (x_param, y_param)},
            "pitch_mm": DEFAULT_PITCH_MM}
    spec["missing"] = missing(spec, cols, rows)
    spec["unusual"] = unusual(spec)
    return spec


def missing(spec: dict, cols: int, rows: int) -> list[str]:
    """What the specification still lacks for every cell to have a full setting, or what contradicts the grid."""
    out = []
    for axis, count in (("x", cols), ("y", rows)):
        a = spec[axis]
        if a.get("param") is None:
            out.append(f"the setting along {'the columns' if axis == 'x' else 'the rows'} is not known")
        elif not a.get("values") or len(a["values"]) != count:
            out.append(f"the values of {LABELS[a['param']]} are not known for every {'column' if axis == 'x' else 'row'}")
        else:
            lo, hi = RANGES[a["param"]]
            if any(not lo <= v <= hi for v in a["values"]):
                out.append(f"a value of {LABELS[a['param']]} lies outside {lo:g}..{hi:g} {UNITS[a['param']]}")
    covered = {spec["x"].get("param"), spec["y"].get("param")}
    for p in PARAMS:
        if p in covered:
            continue
        value = (spec.get("fixed") or {}).get(p)
        if value is None:
            out.append(f"{LABELS[p]} is not known")
        else:
            lo, hi = RANGES[p]
            if not lo <= value <= hi:
                out.append(f"{LABELS[p]} {value:g} lies outside {lo:g}..{hi:g} {UNITS[p]}")
    return out


def unusual(spec: dict) -> list[str]:
    """Settings that are valid but outside the usual range of a marking laser: probably misread, worth a look."""
    out = []
    for axis in ("x", "y"):
        a = spec[axis]
        if a.get("param") and a.get("values"):
            lo, hi = TYPICAL[a["param"]]
            if any(not lo <= v <= hi for v in a["values"]):
                out.append(a["param"])
    for p, v in (spec.get("fixed") or {}).items():
        if v is not None and not TYPICAL[p][0] <= v <= TYPICAL[p][1]:
            out.append(p)
    return out


def cell_settings(spec: dict, col: int, row: int) -> dict:
    out = {p: (spec.get("fixed") or {}).get(p) for p in PARAMS}
    if spec["x"].get("param") and spec["x"].get("values"):
        out[spec["x"]["param"]] = spec["x"]["values"][col]
    if spec["y"].get("param") and spec["y"].get("values"):
        out[spec["y"]["param"]] = spec["y"]["values"][row]
    return out


# -- detection of every matrix in a photograph ----------------------------------------------------------------------------
def _labels(r: "_Rectified", i0: int, i1: int, j0: int, j1: int) -> tuple[dict, dict]:
    rows = {j: info for j in range(j0 - 2, j1 + 3) if (info := _row_label(r, j, i0, i1)) is not None}
    cols = {i: info for i in range(i0 - 2, i1 + 3) if (info := _column_label(r, i, j0, j1)) is not None}
    return rows, cols


def _one_grid(img: np.ndarray, lab: np.ndarray, lattice: dict, read_labels: bool) -> dict | None:
    i0, i1, j0, j1 = grid_extent(lab, lattice)
    height, width = img.shape[:2]

    def inside(a0, a1, b0, b1) -> bool:
        corners = to_px(lattice["H"], [(a0 - 0.5, b0 - 0.5), (a1 + 0.5, b0 - 0.5), (a1 + 0.5, b1 + 0.5), (a0 - 0.5, b1 + 0.5)])
        return bool((corners >= 0).all() and (corners[:, 0] < width).all() and (corners[:, 1] < height).all())

    if not inside(i0, i1, j0, j1):
        return None                 # a matrix cut by the edge of the photograph is not measured
    empty = {"a": None, "b": None, "inliers": [], "read": 0, "decimals": 0, "single": False}
    x_fit = y_fit = empty
    rows_info: dict = {}
    cols_info: dict = {}
    row_texts: dict = {}
    col_texts: dict = {}
    header: list[str] = []
    x_titles: list[str] = []
    y_titles: list[str] = []
    if read_labels:
        r = _Rectified(img, lattice["H"], i0, i1, j0, j1)
        for _ in range(2):          # the labels decide the extent; a changed extent moves the labels that are read
            rows_info, cols_info = _labels(r, i0, i1, j0, j1)
            # inside the visible block every label counts; outside it only one that looks like a label and stands alone
            row_present = {j for j, v in rows_info.items() if j0 <= j <= j1 or (v["like"] and v["alone"])}
            col_present = {i for i, v in cols_info.items() if i0 <= i <= i1 or (v["like"] and v["alone"])}
            row_texts = {j: list(rows_info[j]["texts"]) for j in row_present}
            col_texts = {i: list(cols_info[i]["texts"]) for i in col_present}
            need_y, need_x = min(MIN_CONSISTENT_LABELS, j1 - j0 + 1), min(MIN_CONSISTENT_LABELS, i1 - i0 + 1)
            y_fit, sj0, sj1 = _sane(fit_axis(row_texts, need_y), j0, j1)
            x_fit, si0, si1 = _sane(fit_axis(col_texts, need_x), i0, i1)
            # labels too faint to be read one by one are read as a strip, only when the single labels gave no sequence
            if y_fit["a"] is None or (y_fit["single"] and j1 > j0):
                row_texts = _merge(row_texts, _strip_readings(r, "y", i0, i1, j0, j1, rows_info))
                y_fit, sj0, sj1 = _sane(fit_axis(row_texts, need_y), j0, j1)
            if x_fit["a"] is None or (x_fit["single"] and i1 > i0):
                col_texts = _merge(col_texts, _strip_readings(r, "x", i0, i1, j0, j1, cols_info))
                x_fit, si0, si1 = _sane(fit_axis(col_texts, need_x), i0, i1)
            nj0, nj1 = _settle(sj0, sj1, y_fit, row_present, trim=True)
            ni0, ni1 = _settle(si0, si1, x_fit, col_present, trim=False)
            if (ni0, ni1, nj0, nj1) == (i0, i1, j0, j1) or not inside(ni0, ni1, nj0, nj1):
                break
            i0, i1, j0, j1 = ni0, ni1, nj0, nj1
        header = _header(r, i0, i1, j0)
        lefts = [v["left"] for j, v in rows_info.items() if v["like"] and j0 <= j <= j1]
        bottoms = [v["bottom"] for i, v in cols_info.items() if v["like"] and i0 <= i <= i1]
        x_titles, y_titles = _titles(r, i0, i1, j0, j1, min(lefts) if lefts else None, max(bottoms) if bottoms else None)
    cols, rows = i1 - i0 + 1, j1 - j0 + 1
    spec = interpret(header, x_titles, y_titles, cols, rows, x_fit, y_fit, i0, j0)
    shift = np.array([[1, 0, i0], [0, 1, j0], [0, 0, 1.0]])
    H = np.asarray(lattice["H"], float) @ shift          # (col, row) of the grid -> photo px
    spec["cell_fraction"] = round(float(np.clip(lattice["size_px"] / lattice["pitch_px"], 0.5, 0.98)), 3)
    corners = to_px(H, [(-0.5, -0.5), (cols - 0.5, -0.5), (cols - 0.5, rows - 0.5), (-0.5, rows - 0.5)])
    return {"cols": cols, "rows": rows, "H": H.round(6).tolist(), "pitch_px": round(lattice["pitch_px"], 2),
            "residual_px": round(lattice["residual_px"], 2), "outlined_cells": len(lattice["cells"]),
            "labels": {"rows": {str(k - j0): v for k, v in sorted(row_texts.items())},
                       "cols": {str(k - i0): v for k, v in sorted(col_texts.items())},
                       "header": header, "x_title": x_titles, "y_title": y_titles},
            "axis_fit": {"x": {"agreeing": len(x_fit["inliers"]), "read": x_fit["read"]},
                         "y": {"agreeing": len(y_fit["inliers"]), "read": y_fit["read"]}},
            "corners_px": corners.round(1).tolist(), "spec": spec}


def _settle(lo: int, hi: int, fit: dict, present: set, trim: bool) -> tuple[int, int]:
    """The rows (or columns) once the labels are known. The visible block of cells stands, except that a row at its
    ends with no label text at all is dropped when labels were found for most of the block (the band of column labels
    can pass for a row of faint cells); columns are never dropped this way, because the rotated labels of faint columns
    are often not found. Both grow over every index next to them whose label agrees with the evenly spaced sequence (a
    cell too faint to show is still a cell)."""
    if trim and present and len({k for k in present if lo <= k <= hi}) >= 0.6 * (hi - lo + 1):
        while lo < hi and lo not in present:
            lo += 1
        while hi > lo and hi not in present:
            hi -= 1
    agreeing = set(fit["inliers"]) & present if fit["a"] is not None and not fit.get("single") else set()
    while lo - 1 in agreeing:
        lo -= 1
    while hi + 1 in agreeing:
        hi += 1
    return lo, hi


def _plain(obj):
    """Numbers and containers as plain Python, for JSON."""
    if isinstance(obj, dict):
        return {str(k) if isinstance(k, (np.integer,)) else k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return _plain(obj.tolist())
    return obj


def detect(img_bgr_exposed: np.ndarray, chart_box: list | None = None, read_labels: bool = True, max_grids: int = 6) -> dict:
    """Every complete matrix in the photograph, the largest first. ``img_bgr_exposed`` is the exposure-normalised
    rendering (``photo.exposed_bgr``)."""
    squares = find_squares(img_bgr_exposed, [chart_box] if chart_box else None)
    lab = _lab_image(img_bgr_exposed)
    grids: list[dict] = []
    remaining = list(squares)
    for _ in range(max_grids * 2):
        lattice = fit_lattice(remaining)
        if lattice is None:
            break
        grid = _one_grid(img_bgr_exposed, lab, lattice, read_labels)
        used = {(round(f[0]), round(f[1])) for f in lattice["squares_used"]}
        if grid is not None:
            poly = np.float32(grid["corners_px"]).reshape(-1, 1, 2)
            remaining = [f for f in remaining if (round(f[0]), round(f[1])) not in used and
                         cv2.pointPolygonTest(poly, (float(f[0]), float(f[1])), False) < 0]
            grids.append(grid)
        else:
            remaining = [f for f in remaining if (round(f[0]), round(f[1])) not in used]
        if len(grids) >= max_grids or len(remaining) < 2:
            break
    grids.sort(key=lambda g: -(g["cols"] * g["rows"]))
    return _plain({"grids": grids, "squares": len(squares), "ocr": ocr_available()})


# -- the generated LightBurn file and the alignment -------------------------------------------------------------------------
ORIGIN_MM = 10.0


def cell_centre_mm(spec: dict, rows: int, col: int, row: int) -> tuple[float, float]:
    """File millimetres of a cell's centre; the top row of the photograph is the top of the LightBurn workspace (y up)."""
    pitch = float(spec.get("pitch_mm") or DEFAULT_PITCH_MM)
    return ORIGIN_MM + (col + 0.5) * pitch, ORIGIN_MM + (rows - 1 - row + 0.5) * pitch


def layer_name(spec: dict, col: int, row: int) -> str:
    parts = []
    for axis, k in (("x", col), ("y", row)):
        a = spec[axis]
        if a.get("param") and a.get("values"):
            parts.append(f"{LABELS[a['param']]} {a['values'][k]:.{max(0, int(a.get('decimals') or 0))}f}")
    return " x ".join(parts) or f"Cell {col + 1},{row + 1}"


def lightburn_bytes(spec: dict, cols: int, rows: int) -> bytes:
    """A LightBurn project that describes the engraved matrix: one Scan layer per cell (index = row * cols + col) with
    the cell's full setting, and one filled square per layer. It is a record of the job, generated from what the
    photograph says, never sent to a laser."""
    pitch = float(spec.get("pitch_mm") or DEFAULT_PITCH_MM)
    side = pitch * float(spec.get("cell_fraction") or 0.86)
    cuts, shapes = [], []
    for row in range(rows):
        for col in range(cols):
            index = row * cols + col
            s = cell_settings(spec, col, row)
            tags = [f'<index Value="{index}"/>', f'<name Value="{layer_name(spec, col, row)}"/>']
            if s["power"] is not None:
                tags += [f'<maxPower Value="{s["power"]:.6g}"/>', f'<maxPower2 Value="{s["power"]:.6g}"/>']
            if s["speed"] is not None:
                tags.append(f'<speed Value="{s["speed"]:.6g}"/>')
            if s["frequency"] is not None:
                tags.append(f'<frequency Value="{s["frequency"] * 1000:.6g}"/>')
            if s["pulse_width"] is not None:
                tags.append(f'<QPulseWidth Value="{s["pulse_width"]:.6g}"/>')
            if s["line_interval"] is not None:
                tags.append(f'<interval Value="{s["line_interval"]:.6g}"/>')
            if s["passes"] is not None:
                tags.append(f'<numPasses Value="{int(round(s["passes"]))}"/>')
            tags.append(f'<priority Value="{index}"/>')
            cuts.append(f'<CutSetting type="Scan">{"".join(tags)}</CutSetting>')
            cx, cy = cell_centre_mm(spec, rows, col, row)
            shapes.append(f'<Shape Type="Rect" CutIndex="{index}" W="{side:.4f}" H="{side:.4f}" Cr="0"><XForm>1 0 0 1 {cx:.4f} {cy:.4f}</XForm></Shape>')
    return ('<?xml version="1.0" encoding="UTF-8"?><LightBurnProject AppVersion="2.1.04" DeviceName="Material Test (generated)" '
            'FormatVersion="1" MaterialHeight="0" MirrorX="False" MirrorY="False">' + "".join(cuts) + "".join(shapes) +
            '<Notes ShowOnLoad="0" Notes="Generated from a photographed LightBurn Material Test; one layer per cell."/></LightBurnProject>').encode()


def image_to_mm(matrix: dict) -> np.ndarray:
    """Photo pixels -> file millimetres of the generated LightBurn file: the lattice inverted, then the cell pitch."""
    spec, rows = matrix["spec"], int(matrix["rows"])
    pitch = float(spec.get("pitch_mm") or DEFAULT_PITCH_MM)
    # (col, row) -> mm: x = O + (col + 0.5) p, y = O + (rows - 1 - row + 0.5) p
    lattice_to_mm = np.array([[pitch, 0, ORIGIN_MM + 0.5 * pitch], [0, -pitch, ORIGIN_MM + (rows - 0.5) * pitch], [0, 0, 1.0]])
    return lattice_to_mm @ np.linalg.inv(np.asarray(matrix["H"], float))


def title(spec: dict, photo_name: str) -> str:
    parts = [LABELS[a["param"]] for a in (spec["x"], spec["y"]) if a.get("param") and a.get("values") and len(set(a["values"])) > 1]
    fixed = spec.get("fixed") or {}
    tail = " ".join(f"{fixed[p]:g} {UNITS[p]}" for p in ("frequency", "pulse_width") if fixed.get(p) is not None)
    return f"Material test: {' x '.join(parts) or 'matrix'}{' · ' + tail if tail else ''} · {os.path.splitext(photo_name)[0]}"


def apply_edit(matrix: dict, edit: dict) -> dict:
    """A new matrix record from the operator's corrections: the axis settings and their first / last values (evenly
    spaced), the fixed settings, and the grid's extent (cells added or removed at either end of the lattice)."""
    out = {k: v for k, v in matrix.items()}
    spec = {k: (dict(v) if isinstance(v, dict) else v) for k, v in matrix["spec"].items()}
    cols, rows = int(matrix["cols"]), int(matrix["rows"])
    H = np.asarray(matrix["H"], float)
    ext = edit.get("extent") or {}
    dc, dr = int(ext.get("col_shift", 0)), int(ext.get("row_shift", 0))
    cols = int(ext.get("cols", cols))
    rows = int(ext.get("rows", rows))
    if cols < 1 or rows < 1 or cols * rows > 900:
        raise ValueError("a matrix has between 1 and 900 cells")
    if dc or dr:
        H = H @ np.array([[1, 0, dc], [0, 1, dr], [0, 0, 1.0]])
    for axis, count in (("x", cols), ("y", rows)):
        e = (edit.get(axis) or {})
        a = dict(spec[axis])
        if "param" in e:
            if e["param"] is not None and e["param"] not in PARAMS:
                raise ValueError(f"unknown setting {e['param']}")
            a["param"] = e["param"]
        if e.get("first") is not None and e.get("last") is not None:
            first, last = float(e["first"]), float(e["last"])
            a["values"] = [round(first + (last - first) * k / max(1, count - 1), 6) for k in range(count)]
            if "decimals" in e:
                a["decimals"] = int(e["decimals"])
        elif a.get("values") and len(a["values"]) != count:
            a["values"] = None
        spec[axis] = a
    fixed = dict(spec.get("fixed") or {})
    for p, v in (edit.get("fixed") or {}).items():
        if p not in PARAMS:
            raise ValueError(f"unknown setting {p}")
        fixed[p] = None if v in (None, "") else float(v)
    axes = {spec["x"].get("param"), spec["y"].get("param")}
    spec["fixed"] = {p: fixed.get(p) for p in PARAMS if p not in axes}
    if edit.get("pitch_mm") is not None:
        spec["pitch_mm"] = float(edit["pitch_mm"])
    spec["missing"] = missing(spec, cols, rows)
    spec["unusual"] = unusual(spec)
    out.update(spec=spec, cols=cols, rows=rows, H=H.round(6).tolist(), confirmed=False)
    return _plain(out)
