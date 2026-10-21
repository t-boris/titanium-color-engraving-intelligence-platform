"""The scale and the corner of a measuring angle (two rulers at a right angle) lying beside the plate (REQ-055, DEC-097).

A ruler is a strip whose brightness repeats every millimetre and, stronger still, every 5 or 10 mm. The millimetre period is the
scale of the photograph, exact for the plane the ruler lies on. Texture of the plate or of the table repeats at no such pair of
periods, so a spectral peak is believed only when its multiple (5 or 10 times the period) stands out as well.

Two rulers at a right angle give more than a scale: the two directions of the plate, the corner where they meet and the side on which
the plate lies, so the work is looked for in one quadrant of the photograph and nowhere else.

Pure functions of the photograph. A photograph without a ruler gives None; nothing is guessed.
"""
from __future__ import annotations

from typing import NamedTuple

import cv2
import numpy as np

LONG = 1024                 # window length along the ruler, px (several 10 mm periods at any usable scale)
SHORT = 128                 # window width across the ruler, px (the profile is the mean across it)
STRIDE = 256                # step along the ruler: neighbouring windows of one ruler are this far apart
STEP = 64                   # step across the ruler
MM_PX = (6.0, LONG / 30)    # usable scale: pixels per mm; the 10 mm ticks must repeat at least three times in a window
MIN_RATIO = 6.0             # the millimetre peak over the median of the spectrum
MIN_HARMONIC = 3.0          # the 5 mm peak, and the 10 mm peak, over the median of the spectrum
AGREE = 0.015               # windows of one ruler agree on the scale within this share
HARMONIC_TOLERANCE = 0.015  # the 5 mm and 10 mm ticks repeat at exactly 5 and 10 times the millimetre period, within this share
MIN_CHAIN = 3               # a ruler fills at least this many windows in a row along its length
EDGE_SHARE = 0.3            # a column belongs to the ruler where its tick energy is this share of the strongest column's
MAX_WIDTH_MM = 30.0         # a ruler is a narrow strip: its ticks are confined to this width
SURROUND_MM = 40.0          # looked at on each side of a strip, to see that the ticks stop there
MIN_CONTRAST = 8.0          # tick energy on the strip over the median tick energy around it: a texture has no such contrast


class Hit(NamedTuple):
    period: float           # pixels per mm
    score: float
    axis: str               # "vertical": the ticks repeat along y; "horizontal": along x
    along: int              # start of the window along the ruler
    across: int             # start of the window across it


DETREND = 150               # px: the slow brightness of the strip is removed, leaving the ticks (10 mm ticks are 340 px apart at the finest scale)
LEAK_BINS = 6              # peaks this close (in bins of the unpadded spectrum) to a stronger one are its leakage, not a ruler
RELATIVE_POWER = 0.3        # a peak is considered when it carries this share of the strongest candidate's power
PAD = 4096                  # the profile is zero-padded to this length: the spectrum is sampled finely enough to read a period to 0.5 %


def _spectrum(profile: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    profile = profile - cv2.GaussianBlur(profile.reshape(-1, 1), (0, 0), DETREND).ravel()
    return np.fft.rfftfreq(PAD), np.abs(np.fft.rfft(profile * np.hanning(len(profile)), n=PAD))


def _band(freq: np.ndarray, power: np.ndarray, centre: float, tolerance: float = 0.04) -> tuple[float, float]:
    """The strongest component within ``tolerance`` of ``centre`` (cycles per pixel): (frequency, magnitude)."""
    inside = (freq >= centre * (1 - tolerance)) & (freq <= centre * (1 + tolerance)) & (freq > 0)
    if not inside.any():
        return centre, 0.0
    i = int(np.argmax(np.where(inside, power, 0.0)))
    return float(freq[i]), float(power[i])


def _window_scale(profile: np.ndarray) -> tuple[float, float] | None:
    """(pixels per mm, score) of one profile, or None when it holds no ruler: a millimetre peak whose 5 mm and 10 mm multiples are
    both there, at exactly those periods. Texture has a peak by chance, rarely its multiples as well."""
    freq, power = _spectrum(profile)
    usable = (freq > 1 / 700) & (freq < 1 / 4)
    floor = float(np.median(power[usable])) + 1e-9
    found = []                                               # (power, period, score, frequency)
    for i in range(2, len(power) - 1):
        if not (power[i] >= power[i - 1] and power[i] > power[i + 1]) or not (1 / MM_PX[1] <= freq[i] <= 1 / MM_PX[0]):
            continue
        ratio = power[i] / floor
        if ratio < MIN_RATIO:
            continue
        f5, p5 = _band(freq, power, freq[i] / 5, HARMONIC_TOLERANCE)
        f10, p10 = _band(freq, power, freq[i] / 10, HARMONIC_TOLERANCE)
        if p5 / floor < MIN_HARMONIC or p10 / floor < MIN_HARMONIC:
            continue
        found.append((float(power[i]), float(1.0 / freq[i]), float(min(ratio, p5 / floor, p10 / floor)), float(freq[i])))
    if not found:
        return None
    # a weaker peak next to a stronger one is its leakage; a ruler also repeats every half millimetre, so of the strong peaks that
    # remain the millimetre is the longest period
    reach = LEAK_BINS / len(profile)
    top = max(item[0] for item in found)
    real = [item for item in found if item[0] >= RELATIVE_POWER * top and not any(o[0] > item[0] and abs(o[3] - item[3]) <= reach for o in found)]
    best = max(real, key=lambda item: item[1])
    return best[1], best[2]


def _band_across(gray: np.ndarray, axis: str, along: tuple[int, int], across: tuple[int, int], period: float) -> tuple[float, float] | None:
    """The strip (lo, hi) in pixels, across a ruler, where the brightness repeats at the millimetre period: each column (or row) is
    demodulated at that period and the strip is where its energy is at least ``EDGE_SHARE`` of the strongest. None when the energy is
    spread over more than ``MAX_WIDTH_MM`` (a texture)."""
    a0, a1 = along
    c0, c1 = max(0, across[0]), min(gray.shape[1 if axis == "vertical" else 0], across[1])
    if axis == "vertical":
        band = gray[a0:a1, c0:c1]
        t = np.arange(band.shape[0], dtype=np.float32)
        carrier = (np.exp(-2j * np.pi * t / period) * np.hanning(len(t))).astype(np.complex64)
        energy = np.abs(carrier @ (band - band.mean(axis=0)))
    else:
        band = gray[c0:c1, a0:a1]
        t = np.arange(band.shape[1], dtype=np.float32)
        carrier = (np.exp(-2j * np.pi * t / period) * np.hanning(len(t))).astype(np.complex64)
        energy = np.abs((band - band.mean(axis=1, keepdims=True)) @ carrier)
    smooth = cv2.GaussianBlur(energy.astype(np.float32).reshape(-1, 1), (0, 0), 6).ravel()
    inside = smooth >= EDGE_SHARE * smooth.max()
    index = np.nonzero(inside)[0]
    lo, hi = int(index.min()), int(index.max())
    if (hi - lo) > MAX_WIDTH_MM * period:       # a ruler has two scales, so the strip need not be one piece, but it is narrow
        return None
    if smooth.max() < MIN_CONTRAST * (float(np.median(smooth)) + 1e-6):
        return None                             # the ticks are everywhere around: a texture, not a strip
    return float(c0 + lo), float(c0 + hi)


def _strip(gray: np.ndarray, run: list[Hit], period: float) -> tuple[float, float, float, float] | None:
    """(across_lo, across_hi, along_lo, along_hi) of the ruler that a run of windows lies on, or None when it is no narrow strip."""
    axis = run[0].axis
    a0, a1 = min(h.along for h in run), max(h.along for h in run) + LONG
    c_lo, c_hi = min(h.across for h in run), max(h.across for h in run) + SHORT
    reach = int(SURROUND_MM * period)
    found = _band_across(gray, axis, (a0, a1), (c_lo - reach, c_hi + reach), period)
    return None if found is None else (found[0], found[1], float(a0), float(a1))


def _chains(found: list[Hit], axis: str) -> list[list[Hit]]:
    """Runs of windows side by side along one ruler (same position across it, consecutive along it) that agree on the scale."""
    runs: list[list[Hit]] = []
    for across in sorted({h.across for h in found if h.axis == axis}):
        column = sorted((h for h in found if h.axis == axis and h.across == across), key=lambda h: h.along)
        run: list[Hit] = []
        for h in column:
            if run and h.along - run[-1].along == STRIDE and abs(h.period - run[-1].period) / run[-1].period <= AGREE:
                run.append(h)
            else:
                if len(run) >= MIN_CHAIN:
                    runs.append(run)
                run = [h]
        if len(run) >= MIN_CHAIN:
            runs.append(run)
    return runs


def find_scale(img_bgr: np.ndarray, diagnostics: dict | None = None) -> dict | None:
    """The ruler of the photograph: {"px_per_mm", "windows", "axes", "score", "alternatives"} and, where two rulers meet at a right angle, "corner_px"
    (x, y of the inner corner) and "quadrant" ((sx, sy), the side the plate lies on: +1 right / down, -1 left / up). None without a ruler."""
    diag = diagnostics if diagnostics is not None else {}
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    height, width = gray.shape
    found: list[Hit] = []
    for axis, name in ((0, "vertical"), (1, "horizontal")):
        along, across = (height, width) if axis == 0 else (width, height)
        if along < LONG or across < SHORT:
            continue
        for a in range(0, along - LONG + 1, STRIDE):
            for c in range(0, across - SHORT + 1, STEP):
                profile = gray[a:a + LONG, c:c + SHORT].mean(axis=1) if axis == 0 else gray[c:c + SHORT, a:a + LONG].mean(axis=0)
                result = _window_scale(profile.astype(np.float32))
                if result is not None:
                    found.append(Hit(result[0], result[1], name, a, c))
    diag["windows_with_ticks"] = len(found)
    runs = [r for r in _chains(found, "vertical") + _chains(found, "horizontal")
            if _strip(gray, r, float(np.median([h.period for h in r]))) is not None]
    if not runs:
        diag["refused"] = "no ruler: no strip of windows in a row shows millimetre ticks with their 5 mm and 10 mm ticks"
        return None
    # the scale supported by the most windows (rulers of one angle lie in one plane, so they agree)
    best: list[list[Hit]] = []
    for run in runs:
        s0 = float(np.median([h.period for h in run]))
        same = [r for r in runs if abs(float(np.median([h.period for h in r])) - s0) / s0 <= AGREE]
        if sum(len(r) for r in same) > sum(len(r) for r in best):
            best = same
    chosen = [h for r in best for h in r]
    weights = np.array([h.score for h in chosen])
    scale = float(np.average([h.period for h in chosen], weights=weights))
    out = {"px_per_mm": scale, "windows": len(chosen), "score": round(float(weights.mean()), 1), "axes": sorted({h.axis for h in chosen}),
           "alternatives": [2 * scale, scale / 2]}       # a ruler with half-millimetre ticks reads as twice, one with only long ticks as half
    arms = {}
    for axis in ("vertical", "horizontal"):                              # the longest run of each direction is one arm of the angle
        runs_of_axis = [r for r in best if r[0].axis == axis]
        if runs_of_axis:
            run = max(runs_of_axis, key=len)
            arms[axis] = _strip(gray, run, float(np.median([h.period for h in run])))
    if arms.get("vertical") and arms.get("horizontal"):
        v_lo, v_hi, v_top, v_bottom = arms["vertical"]                   # x of the vertical ruler, its y span
        h_lo, h_hi, h_left, h_right = arms["horizontal"]                 # y of the horizontal ruler, its x span
        # the arms run away from the corner; the plate lies between them, on the side the arms point to
        sx = 1 if (h_left + h_right) / 2 > (v_lo + v_hi) / 2 else -1     # the horizontal arm lies right of the vertical one
        sy = 1 if (v_top + v_bottom) / 2 > (h_lo + h_hi) / 2 else -1     # the vertical arm lies below the horizontal one
        corner = (v_hi if sx == 1 else v_lo, h_lo if sy == -1 else h_hi)  # the inner corner: the edges facing the plate
        out.update(corner_px=[round(corner[0], 1), round(corner[1], 1)], quadrant=[sx, sy])
    diag.update(windows=len(chosen), px_per_mm=round(scale, 3), **{k: out[k] for k in ("corner_px", "quadrant") if k in out})
    return out
