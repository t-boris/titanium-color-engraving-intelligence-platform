"""Greys of a picture chosen so that its drawing survives on titanium (REQ-067, REQ-068, DEC-108, DEC-109).

On a grayscale scale the colours do not darken step by step: power drives the oxide through straw, gold, violet, blue and back, so the grey
whose colour is nearest a pixel's colour (``grayscale.grey_for_colours``) may lie anywhere in power. Neighbouring skin tones then land on
distant powers (grey-blue next to tan, a black forehead), and the plain picture puts a whole face on the flat light end of a scale and its
shadows on the drop to dark. Two steps keep the drawing. Both measure on the titanium (millimetres, or a share of the picture's width for its
edges), never in pixels, so the preview (at preview size) and the LightBurn file (at the layer's DPI) are the same picture:

* :func:`choose` ("Сохранить рисунок"): the picture's tones laid along one path of the scale (:func:`path`): from its lightest grey to its
  darkest in power order, lightness never rising, the colour moving as little as it can at each step. Neighbouring tones get neighbouring
  powers, so a gradient of the skin stays a gradient and a hue swing of the scale at one lightness (a blue bump) is skipped. The picture's
  lightness is smoothed over ``SMOOTH_MM`` keeping its edges (JPEG blocks and skin grain would become spots), its contrast over ``DETAIL_MM``
  raised by ``DETAIL_GAIN`` (lips, eyes, the nose's shading), stretched over the path (``STRETCH``) with mid-tones lifted (``MIDTONES``);
  each pixel takes the grey of the path at its lightness. The picture's own hues are not matched: that is "Ближайший цвет".
* :func:`contours`: where the picture has an edge (``EDGE_DE`` across ``EDGE_SHARE`` of its width, not less than ``LINE_MM``: a lip's
  border is a feature of the picture and as soft at any size) that the predicted engraving does not keep (less than ``KEPT_DE`` across it)
  along at least ``MIN_LINE_MM``, the edge is drawn ``LINE_MM`` wide in the darkest grey of the scale, or in the lightest where the
  picture is a light ridge there (``RIDGE_L`` lighter than around it: a reflection); the other one when the engraving around would not let
  the first show (less than ``LINE_CONTRAST`` from it) and the other stands out more. Edges are found at ``WORK_PX_PER_MM`` whatever the
  size of the picture given. Only on request, and only for greys picked by colour (DEC-109).

Pure functions on numpy arrays; nothing here reads the store.
"""
from __future__ import annotations

import cv2
import numpy as np
from scipy import stats

from . import grayscale, prediction

# "Сохранить рисунок" (this module), "Ближайший цвет" (``grayscale.grey_for_colours``) and "Раскраска по объектам" (``colouring``: the drawing
# kept, each object with a main colour of its own along a path through it)
CHOICES = ("drawing", "nearest", "objects")
PATH_RISE_L = 0.5                   # L*: how much the lightness may rise along the path (the measurement's noise)
SMOOTH_MM = 0.25                    # the picture's lightness is smoothed over this, keeping edges
SMOOTH_L = 6.0                      # L*: differences larger than this are edges the smoothing keeps
DETAIL_MM = 1.5                     # the size of the detail whose contrast is raised
DETAIL_GAIN = 0.5                   # how much of the local contrast is added
STRETCH = (1.0, 99.0)               # percentiles of the picture's lightness laid over the path, lightest to darkest
MIDTONES = 0.8                      # the stretched tone t (0 dark .. 1 light) is laid as t ** MIDTONES: mid-tones lighter
MIN_SPAN_L = 1.0                    # L*: a picture whose lightness spans less is not stretched
LINE_MM = 0.3                       # the width of a contour line
EDGE_SHARE = 0.005                  # an edge is measured across this share of the picture's width (not less than LINE_MM)
EDGE_DE = 8.0                       # a difference across it at or above which the picture has an edge (a lip's border: 9-10)
KEPT_DE = 6.0                       # the predicted engraving keeps an edge when it differs at least this much across it
LINE_CONTRAST = 15.0                # L*: a line shows when the engraving around it differs at least this much
RIDGE_L = 5.0                       # L*: the picture this much lighter at an edge than around it is a light line (a reflection)
MIN_LINE_MM = 1.0                   # a lost edge reaching less far is texture (skin, reflections), not a line of the drawing
WORK_PX_PER_MM = 10.0               # the resolution edges are found at
CANNY = (20, 40)                    # thresholds that only thin the edges; their strength is EDGE_DE


def path(greys: np.ndarray, labs: np.ndarray) -> np.ndarray:
    """The indices (into ``greys`` / ``labs``, as ``grayscale.usable_greys`` gives them) of the path tones are laid along, lightest first:
    from the lightest grey to the darkest, in the order of power between them, lightness never rising by more than ``PATH_RISE_L``, and of
    such paths the one whose squared colour steps add up least (dynamic programming), so it takes small steps and skips a swing of hue."""
    light, dark = int(np.argmax(labs[:, 0])), int(np.argmin(labs[:, 0]))
    power = -greys.astype(np.int64)                                             # a lower grey is a higher power
    way = np.argsort(power if power[light] <= power[dark] else -power, kind="stable")
    way = way[np.flatnonzero(way == light)[0]:np.flatnonzero(way == dark)[0] + 1]
    lab = labs[way].astype(np.float64)
    cost, before = np.full(len(way), np.inf), np.full(len(way), -1)
    cost[0] = 0.0
    for j in range(1, len(way)):
        step = cost[:j] + np.sum((lab[j] - lab[:j]) ** 2, axis=1)
        step[lab[j, 0] > lab[:j, 0] + PATH_RISE_L] = np.inf
        k = int(np.argmin(step))
        cost[j], before[j] = step[k], k
    kept, j = [], len(way) - 1
    while j >= 0:
        kept.append(way[j])
        j = before[j]
    return np.array(kept[::-1], np.int64)


def choose(lab: np.ndarray, opaque: np.ndarray, curve: prediction.Curve, min_power: float, max_power: float, px_per_mm: float) -> dict:
    """The 8-bit grey of every pixel (``lab``: the picture's colours, shape (rows, cols, 3)) that keeps the picture's light and dark on the
    scale at Min..Max, laid along :func:`path`: as ``grayscale.grey_for_colours`` answers (``grey8``, ``lab`` reached, ``delta_e`` to the
    picture's own colour, ``choices``), with the lightness the path spans (``reach``, darkest and lightest), the number of greys on it
    (``path``) and how well the order of light and dark is kept (``order``: the rank correlation of the picture's lightness and the
    predicted one over the opaque pixels)."""
    greys, labs = grayscale.usable_greys(curve, min_power, max_power)
    on = path(greys, labs)
    way = labs[on]
    pic = np.asarray(lab, np.float64)
    light = pic[..., 0].astype(np.float32)
    shown = light[opaque] if opaque.any() else light.ravel()
    lo, hi = np.percentile(shown, STRETCH)
    if hi - lo >= MIN_SPAN_L:
        tone = np.clip((detailed(light, px_per_mm) - lo) / (hi - lo), 0, 1) ** MIDTONES
        target = way[-1, 0] + tone * (way[0, 0] - way[-1, 0])
    else:                                                                       # one lightness: nothing to stretch, it stays as it is
        target = light
    drop = way[0, 0] - np.minimum.accumulate(way[:, 0])                         # how far each grey of the path is below its start
    pick = on[np.clip(np.searchsorted(drop, way[0, 0] - target), 0, len(on) - 1)]
    reached = labs[pick]
    return {"grey8": greys[pick], "lab": reached, "delta_e": np.linalg.norm(reached - pic, axis=-1), "choices": len(greys),
            "reach": [round(float(way[:, 0].min()), 1), round(float(way[0, 0]), 1)], "path": len(on),
            "order": _order(pic[..., 0], reached[..., 0], opaque)}


def detailed(light: np.ndarray, px_per_mm: float) -> np.ndarray:
    """The picture's lightness (float32 L*) as :func:`choose` lays it: smoothed over ``SMOOTH_MM`` keeping edges, the contrast of detail of
    ``DETAIL_MM`` raised by ``DETAIL_GAIN``."""
    light = np.asarray(light, np.float32)
    reach = max(1, int(round(SMOOTH_MM * px_per_mm)))
    smooth = cv2.bilateralFilter(light, 2 * reach + 1, SMOOTH_L, SMOOTH_MM * px_per_mm)
    around = cv2.GaussianBlur(smooth, (0, 0), DETAIL_MM * px_per_mm)
    return smooth + DETAIL_GAIN * (smooth - around)


def _order(wanted: np.ndarray, got: np.ndarray, opaque: np.ndarray, sample: int = 20000) -> float | None:
    """Spearman's rank correlation of two lightness pictures over the opaque pixels (a fixed sample of them; tied values share their rank)."""
    a, b = wanted[opaque], got[opaque]
    if a.size < 3:
        return None
    if a.size > sample:
        keep = np.random.default_rng(0).choice(a.size, sample, replace=False)
        a, b = a[keep], b[keep]
    if np.ptp(a) == 0 or np.ptp(b) == 0:
        return None
    return round(float(stats.spearmanr(a, b)[0]), 2)


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
