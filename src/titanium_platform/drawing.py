"""Greys of a picture chosen so that its drawing survives on titanium (REQ-067, DEC-108).

On a grayscale scale the colours do not darken step by step: power drives the oxide through straw, gold, violet, blue and back, so the grey
whose colour is nearest a pixel's colour (``grayscale.grey_for_colours``) may lie anywhere in power. A skin tone may come nearest at a high
power that engraves dark (the black on a forehead), and lips of nearly the skin's colour get the same grey as the skin and vanish. Two steps
keep the drawing. Both measure on the titanium (millimetres, or a share of the picture's width for its edges), never in pixels, so the
preview (at preview size) and the LightBurn file (at the layer's DPI) are the same picture:

* :func:`choose` ("Сохранить рисунок"): lightness first. The picture's lightness is stretched in order over the lightness the scale reaches
  (``STRETCH`` of the picture over ``REACH`` of the scale), its local contrast over ``DETAIL_MM`` raised by ``DETAIL_GAIN``, and each pixel
  gets the grey whose colour is nearest that target with a difference of lightness counted ``LIGHTNESS_WEIGHT`` times. In a flat area
  (lightness varying less than ``FLAT_L`` around it) a grey where the colour changes fast with power is avoided when one no more than
  ``STEEP_SLACK`` farther changes slower: a fast-changing colour is the one that shifts most when the titanium runs hotter or colder, and
  a large area shows that shift as blotches.
* :func:`contours`: where the picture has an edge (``EDGE_DE`` across ``EDGE_SHARE`` of its width, not less than ``LINE_MM``: a lip's
  border is a feature of the picture and as soft at any size) that the predicted engraving does not keep (less than ``KEPT_DE`` across it)
  along at least ``MIN_LINE_MM``, the edge is drawn ``LINE_MM`` wide in the darkest grey of the scale, or in the lightest where the
  picture is a light ridge there (``RIDGE_L`` lighter than around it: a reflection); the other one when the engraving around would not let
  the first show (less than ``LINE_CONTRAST`` from it) and the other stands out more. Edges are found at ``WORK_PX_PER_MM`` whatever the
  size of the picture given.

Pure functions on numpy arrays; nothing here reads the store.
"""
from __future__ import annotations

import cv2
import numpy as np
from scipy.spatial import cKDTree

from . import grayscale, prediction

CHOICES = ("drawing", "nearest")    # "Сохранить рисунок" (this module) and "Ближайший цвет" (``grayscale.grey_for_colours``)
STRETCH = (2.0, 98.0)               # percentiles of the picture's lightness laid over the scale's reach
REACH = (3.0, 97.0)                 # percentiles of the lightness of the scale's greys taken as what it reaches
MIN_SPAN_L = 1.0                    # L*: a picture whose lightness spans less is not stretched
DETAIL_MM = 1.5                     # the size of the detail whose contrast is raised
DETAIL_GAIN = 0.8                   # how much of the local contrast is added on top of the stretch
LIGHTNESS_WEIGHT = 4.0              # a difference of lightness counts this many times a difference of colour
FLAT_L = 2.0                        # L*: a pixel whose surroundings (DETAIL_MM) vary less is in a flat area
STEEP_SLACK = 3.0                   # dE (weighted): how much farther a slower-changing grey may be in a flat area
CANDIDATES = 8                      # nearest greys looked at for a flat area
CHUNK = 500_000                     # pixels whose candidates are looked up at once
LINE_MM = 0.3                       # the width of a contour line
EDGE_SHARE = 0.005                  # an edge is measured across this share of the picture's width (not less than LINE_MM)
EDGE_DE = 8.0                       # a difference across it at or above which the picture has an edge (a lip's border: 9-10)
KEPT_DE = 6.0                       # the predicted engraving keeps an edge when it differs at least this much across it
LINE_CONTRAST = 15.0                # L*: a line shows when the engraving around it differs at least this much
RIDGE_L = 5.0                       # L*: the picture this much lighter at an edge than around it is a light line (a reflection)
MIN_LINE_MM = 1.0                   # a lost edge reaching less far is texture (skin, reflections), not a line of the drawing
WORK_PX_PER_MM = 10.0               # the resolution edges are found at
CANNY = (20, 40)                    # thresholds that only thin the edges; their strength is EDGE_DE


def choose(lab: np.ndarray, opaque: np.ndarray, curve: prediction.Curve, min_power: float, max_power: float, px_per_mm: float) -> dict:
    """The 8-bit grey of every pixel (``lab``: the picture's colours, shape (rows, cols, 3)) that keeps the picture's light and dark on the
    scale at Min..Max: as ``grayscale.grey_for_colours`` answers (``grey8``, ``lab`` reached, ``delta_e`` to the picture's own colour,
    ``choices``), with the lightness the scale reaches (``reach``) and how well the order of light and dark is kept (``order``: the rank
    correlation of the picture's lightness and the predicted one over the opaque pixels)."""
    greys, labs = grayscale.usable_greys(curve, min_power, max_power)
    pic = np.asarray(lab, np.float64)
    light = pic[..., 0]
    shown = light[opaque] if opaque.any() else light.ravel()
    lo, hi = np.percentile(shown, STRETCH)
    reach_lo, reach_hi = np.percentile(labs[:, 0], REACH)
    sigma = DETAIL_MM * px_per_mm
    around = cv2.GaussianBlur(light.astype(np.float32), (0, 0), sigma).astype(np.float64)
    target = pic.copy()
    if hi - lo >= MIN_SPAN_L:
        gain = (reach_hi - reach_lo) / (hi - lo)
        target[..., 0] = np.clip(reach_lo + gain * (light - lo + DETAIL_GAIN * (light - around)), reach_lo, reach_hi)
    else:                                                                       # one lightness: nothing to stretch, it stays as it is
        target[..., 0] = np.clip(light, reach_lo, reach_hi)
    weight = np.array([np.sqrt(LIGHTNESS_WEIGHT), 1.0, 1.0])
    tree = cKDTree(labs * weight)
    wanted = (target * weight).reshape(-1, 3)
    k = min(CANDIDATES, len(greys))
    step = np.linalg.norm(np.diff(labs, axis=0), axis=1)
    steep = np.maximum(np.r_[step, 0.0], np.r_[0.0, step])                      # dE to the next grey either way: how fast the colour moves
    spread = np.sqrt(np.maximum(cv2.GaussianBlur((light * light).astype(np.float32), (0, 0), sigma) - around.astype(np.float32) ** 2, 0))
    flat = (spread < FLAT_L).ravel()
    pick = np.empty(len(wanted), np.int64)
    for start in range(0, len(wanted), CHUNK):                                  # k candidates of every pixel at once would not fit in memory
        part = slice(start, start + CHUNK)
        distance, index = tree.query(wanted[part], k=k)
        if k == 1:
            pick[part] = index
            continue
        allowed = distance <= distance[:, :1] + STEEP_SLACK
        calm = np.argmin(np.where(allowed, steep[index], np.inf), axis=1)
        pick[part] = index[np.arange(len(index)), np.where(flat[part], calm, 0)]
    pick = pick.reshape(light.shape)
    reached = labs[pick]
    return {"grey8": greys[pick], "lab": reached, "delta_e": np.linalg.norm(reached - pic, axis=-1), "choices": len(greys),
            "reach": [round(float(reach_lo), 1), round(float(reach_hi), 1)], "order": _order(light, reached[..., 0], opaque)}


def _order(wanted: np.ndarray, got: np.ndarray, opaque: np.ndarray, sample: int = 20000) -> float | None:
    """Spearman's rank correlation of two lightness pictures over the opaque pixels (a fixed sample of them)."""
    a, b = wanted[opaque], got[opaque]
    if a.size < 3:
        return None
    if a.size > sample:
        keep = np.random.default_rng(0).choice(a.size, sample, replace=False)
        a, b = a[keep], b[keep]
    ra, rb = np.argsort(np.argsort(a)).astype(np.float64), np.argsort(np.argsort(b)).astype(np.float64)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return round(float(np.corrcoef(ra, rb)[0, 1]), 2)


def contours(grey8: np.ndarray, lab: np.ndarray, opaque: np.ndarray, curve: prediction.Curve, min_power: float, max_power: float,
             px_per_mm: float, spare: np.ndarray | None = None) -> dict:
    """``grey8`` (the greys as they would be engraved, 255 white) with the edges of the picture (``lab``) that its predicted engraving loses
    drawn in: ``grey8`` and the share of the opaque picture the lines cover (``share``). ``spare`` marks pixels left as they are (a part
    engraved in one tone on purpose); transparent pixels are never drawn on. With no grey of Min..Max inside the measured span nothing is
    predicted, so nothing is lost and nothing is drawn."""
    try:
        greys, labs = grayscale.usable_greys(curve, min_power, max_power)
    except prediction.PredictionError:
        return {"grey8": np.array(grey8, np.uint8, copy=True), "share": 0.0}
    rows, cols = grey8.shape
    table = np.full((grayscale.LEVELS, 3), np.nan)
    table[greys] = labs
    pic = np.asarray(lab, np.float32)
    predicted = table[grey8]
    predicted = np.where(np.isfinite(predicted), predicted, pic).astype(np.float32)   # outside the scale nothing is predicted, nothing lost
    scale = WORK_PX_PER_MM / px_per_mm
    size = (max(1, round(cols * scale)), max(1, round(rows * scale)))
    shrink = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    d = max(1, round(LINE_MM * WORK_PX_PER_MM))
    e = max(d, round(EDGE_SHARE * cols / px_per_mm * WORK_PX_PER_MM))
    pic_w = cv2.GaussianBlur(cv2.resize(pic, size, interpolation=shrink), (0, 0), e / 2)
    pred_w = cv2.GaussianBlur(cv2.resize(predicted, size, interpolation=shrink), (0, 0), e / 2)
    keep = opaque if spare is None else opaque & ~spare
    inside = cv2.erode(cv2.resize(keep.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST), np.ones((2 * e + 1, 2 * e + 1), np.uint8)) > 0
    coded = np.dstack([pic_w[..., 0] * 2.55, pic_w[..., 1] * 2.55 + 128, pic_w[..., 2] * 2.55 + 128]).clip(0, 255).astype(np.uint8)
    edges = cv2.Canny(coded, *CANNY) > 0
    lost = edges & inside & (_across(pic_w, e) >= EDGE_DE) & (_across(pred_w, e) < KEPT_DE)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(lost.astype(np.uint8), connectivity=8)
    extent = np.maximum(stats[1:, cv2.CC_STAT_WIDTH], stats[1:, cv2.CC_STAT_HEIGHT])            # a speck's outline is a loop, not long
    long_enough = np.r_[False, extent >= MIN_LINE_MM * WORK_PX_PER_MM]
    lost = long_enough[labels]
    line = cv2.dilate(lost.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))) > 0
    dark, bright = greys[np.argmin(labs[:, 0])], greys[np.argmax(labs[:, 0])]
    surround = cv2.blur(pred_w[..., 0], (5 * d, 5 * d))
    against_dark, against_bright = surround - table[dark, 0], table[bright, 0] - surround
    ridge = pic_w[..., 0] - cv2.blur(pic_w[..., 0], (5 * d, 5 * d)) >= RIDGE_L
    light = np.where(ridge, ~((against_bright < LINE_CONTRAST) & (against_dark > against_bright)),
                     (against_dark < LINE_CONTRAST) & (against_bright > against_dark))
    drawn = np.where(light, bright, dark).astype(np.uint8)
    mask = cv2.resize(line.astype(np.uint8), (cols, rows), interpolation=cv2.INTER_NEAREST) > 0
    mask &= keep
    colour = cv2.resize(drawn, (cols, rows), interpolation=cv2.INTER_NEAREST)
    out = np.array(grey8, np.uint8, copy=True)
    out[mask] = colour[mask]
    share = float(mask[opaque].mean()) if opaque.any() else 0.0
    return {"grey8": out, "share": round(share, 4)}


def _across(img: np.ndarray, d: int) -> np.ndarray:
    """The largest colour difference (CIE76) across ``d`` pixels through each pixel, over the four directions."""
    h = max(1, (d + 1) // 2)
    padded = cv2.copyMakeBorder(img, h, h, h, h, cv2.BORDER_REPLICATE)
    rows, cols = img.shape[:2]

    def at(dy: int, dx: int) -> np.ndarray:
        return padded[h + dy:h + dy + rows, h + dx:h + dx + cols]
    out = np.zeros((rows, cols), np.float32)
    for dy, dx in ((0, h), (h, 0), (h, h), (h, -h)):
        out = np.maximum(out, np.linalg.norm(at(dy, dx) - at(-dy, -dx), axis=-1))
    return out
