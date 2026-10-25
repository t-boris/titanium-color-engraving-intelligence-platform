"""How well a photo engraving came out (feature photo-engraving-quality, DEC-001): what a photograph shows of an image layer, judged as a
picture rather than as colours.

* **Tone**, from the layer's tonal profile (``ingest._tonal_profile`` of the picture, or ``_ramp_profile`` of a grey ramp at the same
  settings): the colour at each grey level, black (0) to white (1). From it:
  ``levels``      how many different tones a viewer tells apart: walking from black to white, a grey is a new tone when its colour is at
                  least ``JND`` (ΔE76) from the last new tone, so noise smaller than that never counts; ``levels_share`` is the new tones
                  over the steps measured;
  ``range_L``     how much lighter the white end is than the black end (L*);
  ``shadows_to``  the grey up to which everything looks like the black end (within ``FLAT_DE``): blocked shadows;
  ``highlights_from`` the grey from which everything looks like the white end: lost highlights;
  ``reversals``   greys where the lightness turns back by more than ``JND`` (a darker grey engraved lighter): a tone that is out of order;
                  ``reversal_share`` is their share of the steps;
  ``mid_darkness`` how dark the middle grey came out between the two ends (0 = like the white end, 1 = like the black end): 0.5 is
                  the picture's own tone; above it the mid-tones are darker (in a dot kind: dot gain), below lighter; not given when the
                  ends are less than ``MIN_RANGE`` apart (nothing to place the middle between);
  ``mean_L``      the mean lightness of the picture as it came out (its greys weighted by their area), for a picture profile only.
* **Detail** (:func:`detail`), from the photograph laid over the picture: at each scale (0.2, 0.4, 0.8 mm) the share of the picture's
  own contrast that the engraving keeps (a regression slope of the photograph's band of that scale on the picture's band, after the
  tone curve, so an engraving that only lightens keeps 1), how much of it is not the picture (grain, ΔL*), and the same along the scan
  lines and across them (blur along one direction only points at the scan, not the picture).

Pure functions on plain data and arrays; the store is never read here.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

ALGORITHM = 1
JND = 2.0                       # ΔE76: two neighbouring greys this far apart are told apart at a glance
FLAT_DE = 3.0                   # ΔE76 from an end within which a grey looks like that end
MIN_RANGE = 6.0                 # L*: ends closer than this leave no middle to judge
DETAIL_SCALES_MM = (0.2, 0.4, 0.8)
DETAIL_MIN_PX = 1.5             # a scale finer than this many photograph pixels is not measured
DETAIL_MIN_SAMPLES = 2000


def _bins(tonal: dict) -> list[dict]:
    return sorted((b for b in (tonal or {}).get("bins") or [] if b.get("L") is not None), key=lambda b: b["gray"])


def _lab(b: dict) -> np.ndarray:
    return np.array([b["L"], b.get("a", 0.0), b.get("b", 0.0)], float)


def _interp(greys: np.ndarray, values: np.ndarray, at: float) -> float:
    return float(np.interp(at, greys, values))


def tone(tonal: dict | None) -> dict | None:
    """The tone of a tonal profile (see the module); None when it has fewer than three measured greys."""
    bins = _bins(tonal or {})
    if len(bins) < 3:
        return None
    greys = np.array([b["gray"] for b in bins])
    labs = np.array([_lab(b) for b in bins])
    lightness = labs[:, 0]
    levels, anchor = 1, labs[0]
    for lab in labs[1:]:
        if float(np.linalg.norm(lab - anchor)) >= JND:
            levels, anchor = levels + 1, lab
    black, white = labs[0], labs[-1]
    from_black = np.linalg.norm(labs - black, axis=1)
    from_white = np.linalg.norm(labs - white, axis=1)
    flat_black = np.nonzero(from_black > FLAT_DE)[0]
    flat_white = np.nonzero(from_white > FLAT_DE)[0]
    shadows_to = float(greys[flat_black[0] - 1]) if len(flat_black) and flat_black[0] > 0 else float(greys[0]) if len(flat_black) else float(greys[-1])
    highlights_from = float(greys[flat_white[-1] + 1]) if len(flat_white) and flat_white[-1] < len(greys) - 1 else float(greys[-1]) if len(flat_white) else float(greys[0])
    # a reversal: walking from black to white, the lightness falls by more than JND below the lightest seen so far
    reversals, top = [], -math.inf
    for g, value in zip(greys, lightness):
        if value < top - JND:
            reversals.append(round(float(g), 3))
        top = max(top, value)
    span = float(lightness[-1] - lightness[0])
    mid = None
    if span >= MIN_RANGE:
        mid = round(float((lightness[-1] - _interp(greys, lightness, 0.5)) / span), 3)
    counts = np.array([b.get("n", 0) for b in bins], float)
    measured_by = (tonal or {}).get("measured_by") or "picture"
    return {"algorithm": ALGORITHM, "measured_by": measured_by, "steps": len(bins), "levels": levels,
            "levels_share": round((levels - 1) / max(1, len(bins) - 1), 3), "range_L": round(span, 1),
            "black_L": round(float(lightness[0]), 1), "white_L": round(float(lightness[-1]), 1),
            "shadows_to": round(shadows_to, 3), "highlights_from": round(highlights_from, 3),
            "shadows_blocked": round(max(0.0, shadows_to - float(greys[0])), 3),
            "highlights_lost": round(max(0.0, float(greys[-1]) - highlights_from), 3),
            "reversals": reversals, "reversal_share": round(len(reversals) / max(1, len(bins) - 1), 3), "mid_darkness": mid,
            "mean_L": round(float(np.average(lightness, weights=counts)), 1) if measured_by == "picture" and counts.sum() > 0 else None,
            "evidence": (tonal or {}).get("evidence"), "rho": (tonal or {}).get("rho")}


def detail(lightness: np.ndarray, expected: np.ndarray, inside: np.ndarray, px_per_mm: float, scan_axis: int = 1) -> dict | None:
    """How much of the picture's detail the engraving keeps (see the module). ``lightness`` is the photograph's L*, ``expected`` the L* the
    tone curve gives the picture's grey at each photograph pixel (the picture laid over the photograph without blur), ``inside`` the
    pixels that show the layer and nothing else, ``px_per_mm`` the photograph's scale there and ``scan_axis`` the photograph axis the scan
    lines run along (1: x). None when too few pixels are inside."""
    if px_per_mm <= 0 or int(inside.sum()) < DETAIL_MIN_SAMPLES:
        return None
    photo = lightness.astype(np.float32)
    model = expected.astype(np.float32)
    out = {"algorithm": ALGORITHM, "px_per_mm": round(float(px_per_mm), 1), "scales": []}
    for scale_mm in DETAIL_SCALES_MM:
        sigma = scale_mm * px_per_mm / 2.0                    # a band centred on features about scale_mm across
        if sigma < DETAIL_MIN_PX / 2.0:
            out["scales"].append({"mm": scale_mm, "kept": None, "match": None, "grain_L": None, "reason": "finer than the photograph"})
            continue
        size = int(max(3, 6 * sigma)) | 1
        core = cv2.erode(inside.astype(np.uint8), np.ones((size, size), np.uint8)).astype(bool)
        if int(core.sum()) < DETAIL_MIN_SAMPLES:
            out["scales"].append({"mm": scale_mm, "kept": None, "match": None, "grain_L": None, "reason": "too small"})
            continue
        band = lambda im: cv2.GaussianBlur(im, (0, 0), sigma) - cv2.GaussianBlur(im, (0, 0), 2 * sigma)     # noqa: E731
        bp, bq = band(photo)[core], band(model)[core]
        var = float(np.var(bq))
        if var < 1e-6:
            out["scales"].append({"mm": scale_mm, "kept": None, "match": None, "grain_L": round(float(np.std(bp)), 2), "reason": "flat picture"})
            continue
        slope = float(np.cov(bp, bq)[0, 1] / var)
        match = float(np.corrcoef(bp, bq)[0, 1])
        grain = float(np.std(bp - slope * bq))
        out["scales"].append({"mm": scale_mm, "kept": round(slope, 2), "match": round(match, 2), "grain_L": round(grain, 2),
                              "picture_L": round(float(np.sqrt(var)), 2)})
    # along and across the scan lines at the middle scale: the gradient of the photograph against the picture's, each direction alone
    sigma = DETAIL_SCALES_MM[1] * px_per_mm / 2.0
    size = int(max(3, 6 * sigma)) | 1
    core = cv2.erode(inside.astype(np.uint8), np.ones((size, size), np.uint8)).astype(bool)
    if int(core.sum()) >= DETAIL_MIN_SAMPLES and sigma >= DETAIL_MIN_PX / 2.0:
        smooth = lambda im: cv2.GaussianBlur(im, (0, 0), sigma)     # noqa: E731
        sp, sq = smooth(photo), smooth(model)
        kept = {}
        for name, (dx, dy) in (("x", (1, 0)), ("y", (0, 1))):
            gp = cv2.Sobel(sp, cv2.CV_32F, dx, dy, ksize=3)[core]
            gq = cv2.Sobel(sq, cv2.CV_32F, dx, dy, ksize=3)[core]
            energy = float(np.dot(gq, gq))
            kept[name] = round(float(np.dot(gp, gq) / energy), 2) if energy > 1e-6 else None
        along, across = (kept["x"], kept["y"]) if scan_axis == 1 else (kept["y"], kept["x"])
        out["along_scan"], out["across_scan"] = along, across
    middle = next((s for s in out["scales"] if s["mm"] == DETAIL_SCALES_MM[1]), None)
    out["kept"] = middle["kept"] if middle else None
    out["grain_L"] = middle["grain_L"] if middle else None
    return out


def score(tone_: dict | None, detail_: dict | None = None) -> float | None:
    """One number to rank engravings of one picture (DEC-001): the share of the tone steps told apart, times the share of steps whose tone
    keeps its order, times the detail kept at 0.4 mm when it was measured (capped at 1: an engraving cannot keep more than the picture has)."""
    if not tone_:
        return None
    value = tone_["levels_share"] * (1.0 - tone_["reversal_share"])
    kept = (detail_ or {}).get("kept")
    if kept is not None:
        value *= max(0.0, min(1.0, kept))
    return round(value, 3)


# -- the next plate (DEC-001) -------------------------------------------------------------------------------------------------------
NEXT_KINDS = {"jarvis": ("atkinson", "stucki"), "atkinson": ("jarvis", "stucki"), "stucki": ("jarvis", "atkinson")}


def _round(key: str, value: float) -> float:
    return round(value * 2) / 2 if key in ("power", "min_power") else round(value) if key == "speed" else round(value, 4)


def variants_around(centre: dict, step: float = 1.0) -> list[dict]:
    """The copies of a photo-variations plate around ``centre`` (the settings of a photo engraving: ``dither``, ``power``, ``min_power`` in
    grayscale, ``speed``, ``line_interval``, ``dot_width`` …): the centre itself (``{}``), then one setting changed at a time, each by
    ``step`` times its first change, so the next plate, closer to the best, changes less. A dot kind: power down and up 20 %, speed up 40 %
    (lighter), the line interval 1.69 times (0.01 → 0.0169 mm), the dot width corrected or not, and two other kinds of dots. Grayscale: Max
    down and up 20 %, Min 3 points (the highlights), the line interval 1.5 and 0.75 times, speed 0.7 and 1.4 times."""
    out: list[dict] = [{}]

    def add(change: dict) -> None:
        if change and change not in out:
            out.append(change)

    power = float(centre["power"])
    if centre.get("dither", "grayscale") == "grayscale":
        low = float(centre.get("min_power") or 0.0)
        for factor in (1 - 0.2 * step, 1 + 0.2 * step):
            high = min(100.0, _round("power", power * factor))
            if high > low and high != power:
                add({"power": high})
        lifted = _round("min_power", low + 3 * step if low + 3 * step < power else max(0.0, low - 3 * step))
        if lifted != low:
            add({"min_power": lifted})
        for factor in (1 + 0.5 * step, 1 - 0.25 * step):
            add({"line_interval": _round("line_interval", float(centre["line_interval"]) * factor)})
        for factor in (1 - 0.3 * step, 1 + 0.4 * step):
            add({"speed": _round("speed", float(centre["speed"]) * factor)})
        return out
    for factor in (1 - 0.2 * step, 1 + 0.2 * step):
        value = min(100.0, _round("power", power * factor))
        if value != power:
            add({"power": value})
    add({"speed": _round("speed", float(centre["speed"]) * (1 + 0.4 * step))})
    add({"line_interval": _round("line_interval", float(centre["line_interval"]) * (1 + 0.69 * step))})
    add({"dot_width": None} if centre.get("dot_width") is not None else {"dot_width": 0.01})
    for kind in NEXT_KINDS.get(centre["dither"], ("jarvis", "atkinson")):
        if kind != centre["dither"]:
            add({"dither": kind})
    return out
