"""Predicted look of a photo engraving (REQ-030): the picture of a grayscale-mode image layer, its grey turned into power by the
layer's Min and Max (DEC-057), the power into the colour measured at that power in the same mode.

* The curve is linear in Lab between neighbouring measured powers. A power outside the measured span is not predicted (REQ-003):
  those pixels are hatched over the picture's grey and their share is reported.
* Every point keeps where it was measured (pair or plate, layer). Chart-corrected (referenced) points are preferred; without any,
  the curve is built from camera-relative ones and the preview says so (DEC-062). The two kinds are never mixed in one curve.
* LightBurn's picture adjustments are applied before the grey becomes power, with standard formulas marked assumed: LightBurn does
  not publish its own. Its documentation gives the directions only (gamma: lower values lighten the mid-tones; contrast: higher
  values make light tones lighter and dark ones darker; brightness: lightens or darkens every tone). Enhance amount, radius and
  denoise are local filters; they are not modelled and are named when set.
* Two kinds of mode are predicted (REQ-054): grayscale, where the grey sets the power, from the colour measured at each power; and the
  dot modes whose grey sets the density of full-power dots (ordered, atkinson, dither, stucki, jarvis, newsprint, halftone), from the
  colour measured at each tone in the same mode and settings, the curve running over the darkness of the grey instead of a power
  (``Curve.axis``). Dithering itself is not modelled. Threshold, sketch and 3D slice have no tones to measure and are refused (DEC-052).

Pure functions on plain data: nothing is read from or written to the store, so a new Min or Max re-renders from the same curve.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import cv2
import numpy as np

from . import agreement, color, lightburn as lb, photo_modes

PREDICTED_MODE = "grayscale"
POWER_AXIS, TONE_AXIS = "power", "darkness"      # what a curve runs over: the power engraved with, or the darkness (%) of the grey
NOT_PREDICTED = {"3dslice": "3D slicing engraves depth in repeated passes, not a tone",
                 "threshold": "it is a cut at mid grey: every pixel is fired at full power or not at all, so there are no tones in between",
                 "sketch": "it engraves the edges of the picture, not its tones"}
ASSUMED = lb.MONOTONE_ADJUSTMENTS                                              # Gamma, Contrast, Brightness: applied, marked assumed
NOT_MODELLED = tuple(tag for tag in lb.BITMAP_DEFAULTS if tag not in ASSUMED)  # EnhanceAmount, EnhanceRadius, EnhanceDenoise
SPAN_TOLERANCE = 1e-6      # % power: this close to an end of the measured span counts as inside (rounding of grey -> power)
HATCH_PERIOD = 8           # px between diagonal hatch lines at least; more on a large picture, so the hatch survives scaling down
HATCH_PER_SIDE = 64        # hatch lines across the long side of a large picture
GAP = 8                    # px of white between the picture and its prediction
BLANK = 235                # grey of a pixel the layer does not engrave (transparent in the picture)


class PredictionError(ValueError):
    """The layer cannot be predicted; the message says why."""


@dataclass(frozen=True)
class Point:
    """One measured colour at one power of a mode, with where it was measured."""
    power: float                         # %
    lab: tuple[float, float, float]
    source: dict                         # kind 'pair' | 'plate', id, layer, label
    referenced: bool                     # chart-corrected; False: camera-relative (DEC-062)

    def __post_init__(self):
        try:
            power, lab = float(self.power), tuple(float(v) for v in self.lab)
        except (TypeError, ValueError):
            power, lab = float("nan"), ()
        if len(lab) != 3 or not np.isfinite([power, *lab]).all():
            raise ValueError(f"a curve point needs a finite power and Lab, got {self.power!r} and {self.lab!r}")
        if not isinstance(self.source, Mapping) or self.source.get("kind") not in ("pair", "plate"):
            raise ValueError(f"a curve point must say where it was measured (kind 'pair' or 'plate'), got {self.source!r}")
        object.__setattr__(self, "power", power)
        object.__setattr__(self, "lab", lab)


@dataclass(frozen=True, eq=False)
class Curve:
    """Colour against power at one mode, from points of one kind only."""
    powers: np.ndarray                   # measured powers, ascending, each once
    labs: np.ndarray                     # (n, 3): mean Lab at each power
    points: tuple[dict, ...]             # per power: power, lab, referenced, sources (every point measured there)
    referenced: bool
    left_out: int                        # points of the other kind at this mode, not used
    axis: str = POWER_AXIS               # what ``powers`` are: powers (%), or for a dot mode the darkness (%) of the grey

    @property
    def span(self) -> tuple[float, float]:
        return float(self.powers[0]), float(self.powers[-1])

    def lab_at(self, power) -> np.ndarray:
        """Lab at each power, shape (..., 3): linear between the neighbouring measured powers, NaN outside the span (never extrapolated)."""
        p = np.asarray(power, np.float64)
        lab = np.stack([np.interp(p, self.powers, self.labs[:, c]) for c in range(3)], axis=-1)
        lo, hi = self.span
        inside = np.isfinite(p) & (p >= lo - SPAN_TOLERANCE) & (p <= hi + SPAN_TOLERANCE)
        return np.where(inside[..., None], lab, np.nan)

    def spread_at(self, power) -> np.ndarray:
        """How far independent engravings disagree (ΔE) at each power, shape of ``power``: linear between the powers where at least two
        engravings measured, NaN where fewer did (the repeatability there is not known) and outside the span."""
        known = [(row["power"], row["spread_de"]) for row in self.points if row.get("spread_de") is not None]
        p = np.asarray(power, np.float64)
        if not known:
            return np.full(p.shape, np.nan)
        xs, ys = (np.array(v, np.float64) for v in zip(*known))
        inside = np.isfinite(p) & (p >= xs[0] - SPAN_TOLERANCE) & (p <= xs[-1] + SPAN_TOLERANCE)
        return np.where(inside, np.interp(p, xs, ys), np.nan)

    def as_dict(self) -> dict:
        return {"span": list(self.span), "referenced": self.referenced, "left_out": self.left_out, "axis": self.axis, "points": list(self.points)}


def _engraving_of(source: Mapping) -> tuple:
    """One engraving is one photographed pair: its layers are not independent of each other, two pairs are."""
    return ("pair", source["pair_id"]) if source.get("pair_id") is not None else (source.get("kind"), source.get("id"))


def disagreement(points: Iterable[Point], powers: Iterable[float]) -> list[dict]:
    """At each power, how many independent engravings measured the colour there and how far apart their colours are (largest ΔE between
    any two, CIE76). Each engraving gives its colour at a power as its own curve says it (linear between its measured powers, none
    outside them). Fewer than two engravings: no spread, the repeatability is unknown (REQ-054)."""
    by_engraving: dict[tuple, dict[float, list]] = {}
    for p in points:
        by_engraving.setdefault(_engraving_of(p.source), {}).setdefault(round(p.power, 6), []).append(p.lab)
    curves = []
    for at in by_engraving.values():
        xs = sorted(at)
        curves.append((np.array(xs), np.array([np.mean(at[x], axis=0) for x in xs])))
    rows = []
    for power in powers:
        labs = [[float(np.interp(power, xs, labs[:, c])) for c in range(3)] for xs, labs in curves
                if xs[0] - SPAN_TOLERANCE <= power <= xs[-1] + SPAN_TOLERANCE]
        if len(labs) < 2:
            rows.append({"engravings": len(labs), "spread_de": None})
            continue
        labs = np.array(labs)
        rows.append({"engravings": len(labs), "spread_de": round(float(np.linalg.norm(labs[:, None] - labs[None], axis=2).max()), 1)})
    return rows


def curve(points: Iterable[Point], prefer_referenced: bool = True, axis: str = POWER_AXIS) -> Curve:
    """The curve of one mode. When both kinds exist only the preferred one is used (referenced by default, DEC-062) and the others are
    counted in ``left_out``. Points at the same power are averaged in Lab and keep all their sources."""
    points = list(points)
    if not points:
        raise PredictionError("no colour has been measured at this mode: there is nothing to predict from")
    kinds = {p.referenced for p in points}
    use = prefer_referenced if len(kinds) == 2 else kinds.pop()
    at: dict[float, list[Point]] = {}
    for p in points:
        if p.referenced == use:
            at.setdefault(round(p.power, 6), []).append(p)
    powers = sorted(at)
    labs = np.array([np.mean([p.lab for p in at[k]], axis=0) for k in powers])
    spread = disagreement([p for k in powers for p in at[k]], powers)
    rows = tuple({"power": k, "lab": [float(v) for v in lab], "referenced": use, "sources": [dict(p.source) for p in at[k]], **extent}
                 for k, lab, extent in zip(powers, labs, spread))
    return Curve(np.array(powers), labs, rows, use, sum(p.referenced != use for p in points), axis)


def adjust_grey(grey, gamma: float = 1.0, contrast: float = 0.0, brightness: float = 0.0) -> np.ndarray:
    """LightBurn's picture adjustments on grey 0..1 (0 = black), with standard formulas ASSUMED (LightBurn does not publish its own),
    in this order, also assumed:

    * brightness b %:  g + b / 100                       an offset of b % of the full scale; positive lightens
    * contrast c %:    0.5 + (g - 0.5) * (1 + c / 100)   a scale around mid-grey; positive spreads the tones, -100 flattens them
    * clipped to 0..1, then gamma:  g ** gamma           lower than 1 lightens the mid-tones, higher darkens them (as LightBurn says)

    The defaults (gamma 1, contrast 0, brightness 0) leave the grey exactly as it is; no setting reorders the grey levels.
    """
    if not (np.isfinite(gamma) and gamma > 0 and np.isfinite(contrast) and contrast >= -100 and np.isfinite(brightness)):
        raise PredictionError(f"picture adjustments out of range: gamma {gamma:g} (must be above 0), contrast {contrast:g} "
                              f"(must be -100 or more), brightness {brightness:g}")
    g = np.asarray(grey, np.float64)
    if brightness:
        g = g + brightness / 100
    if contrast:
        g = 0.5 + (g - 0.5) * (1 + contrast / 100)
    g = np.clip(g, 0.0, 1.0)
    return g ** gamma if gamma != 1 else g


def adjustments_of(settings: Mapping | None) -> dict:
    """The adjustments of one image object as the parser names them (an item of ``source_settings["bitmaps"]``, or
    ``image_summary()["adjusted"]``): LightBurn's default where unset; the set ones split into ``assumed`` (applied by
    ``adjust_grey``) and ``not_modelled`` (named, not applied). "Set" means what ``lightburn.changed_processing`` means."""
    changed = lb.changed_processing([dict(settings or {})])
    return {"values": {**lb.BITMAP_DEFAULTS, **changed}, "assumed": [t for t in ASSUMED if t in changed],
            "not_modelled": [t for t in NOT_MODELLED if t in changed]}


def grey_to_power(grey, min_power: float, max_power: float) -> np.ndarray:
    """DEC-057: power = Min + (Max - Min) x (1 - grey); the lightest grey gets Min, the darkest Max, linearly between."""
    try:
        low, high = float(min_power), float(max_power)
    except (TypeError, ValueError):
        low = high = float("nan")
    if not (np.isfinite(low) and np.isfinite(high)):
        raise PredictionError(f"Min and Max power must be numbers, got {min_power!r} and {max_power!r}")
    return low + (high - low) * (1.0 - np.asarray(grey, np.float64))


def refuse_mode(mode: str | None) -> None:
    """Raise PredictionError with the reason unless the layer engraves in a mode that is predicted: grayscale, or a dot mode whose grey
    sets the density of dots (``photo_modes``, REQ-054)."""
    name = str(mode or "").strip().lower()
    known = photo_modes.mode(name)
    if known is not None and known.predicted_from in (photo_modes.CURVE, photo_modes.PROFILE):
        return
    if not name:
        raise PredictionError("the layer states no image mode: only grayscale mode, where the grey level sets the power, and the dot modes "
                              "whose grey level sets the density of dots are predicted")
    why = NOT_PREDICTED.get(known.key if known else name, "the grey level does not set the power or the density of dots in this mode")
    raise PredictionError(f"{mode} mode is not predicted: {why}; only grayscale mode, where the grey level sets the power, and the dot modes "
                          "whose grey level sets the density of dots are predicted")


def x_of(grey, curve: Curve, values: Mapping, min_power=None, max_power=None) -> np.ndarray:
    """Where on the curve each grey level lies, after the picture adjustments: its power at Min..Max for a power curve, its darkness
    (%) for a curve over tones."""
    adjusted = adjust_grey(grey, values["Gamma"], values["Contrast"], values["Brightness"])
    return 100.0 * (1.0 - adjusted) if curve.axis == TONE_AXIS else grey_to_power(adjusted, min_power, max_power)


def share_outside(levels, counts, min_power: float, max_power: float, curve: Curve, adjustments: Mapping | None = None) -> float:
    """The share of a picture, given as its grey levels and the number of pixels at each, that needs a power outside the measured
    span at Min..Max: computed on the whole picture, where a preview scaled down averages the extreme greys away."""
    values = adjustments_of(adjustments)["values"]
    power = x_of(levels, curve, values, min_power, max_power)
    weights = np.asarray(counts, np.float64)
    total = float(weights.sum())
    return float(weights[~np.isfinite(curve.lab_at(power)[..., 0])].sum() / total) if total else 0.0


def share_by_spread(levels, counts, min_power: float, max_power: float, curve: Curve, adjustments: Mapping | None = None) -> dict:
    """Of the pixels of the whole picture that the curve predicts, the share at powers where independent engravings disagree by more
    than ``agreement.AGREEMENT_DE`` (``uncertain``), the share at powers where fewer than two engravings measured (``single``) and the
    largest disagreement met (``max_de``, None when no power of the picture has one)."""
    values = adjustments_of(adjustments)["values"]
    power = x_of(levels, curve, values, min_power, max_power)
    weights = np.asarray(counts, np.float64)
    predicted = np.isfinite(curve.lab_at(power)[..., 0])
    spread = curve.spread_at(power)
    total = float(weights[predicted].sum())
    if not total:
        return {"uncertain": 0.0, "single": 0.0, "max_de": None}
    known = predicted & np.isfinite(spread)
    return {"uncertain": float(weights[known & (spread > agreement.AGREEMENT_DE)].sum() / total),
            "single": float(weights[predicted & ~np.isfinite(spread)].sum() / total),
            "max_de": float(spread[known].max()) if known.any() else None}


def render(picture_grey, min_power: float, max_power: float, curve: Curve, adjustments: Mapping | None = None,
           outside_share: float | None = None, spread_shares: Mapping | None = None, alpha=None) -> dict:
    """The predicted look of the picture engraved at Min..Max power: Lab and sRGB per pixel, where it is predicted, and notes that say
    what the prediction rests on and what it leaves out. Pass the picture at the resolution it is to be shown; the share outside the
    measured span is that of the picture passed unless ``outside_share`` gives the one of the whole picture (``share_outside``).
    ``alpha`` (opacity 0..1 of the same shape) says where the picture is transparent: the layer engraves nothing there, so nothing is
    predicted and the pixel is shown blank (DEC-095)."""
    grey = _picture(picture_grey)
    opaque = np.ones(grey.shape, bool) if alpha is None else np.asarray(alpha, np.float64) >= photo_modes.ALPHA_MIN
    applied = adjustments_of(adjustments)
    values = applied["values"]
    power = x_of(grey, curve, values, min_power, max_power)
    lab = curve.lab_at(power)
    in_span = np.isfinite(lab[..., 0])
    covered = in_span & opaque
    rgb8 = np.repeat(_grey8(grey)[..., None], 3, axis=2)
    rgb8[covered] = np.clip(color.lab_to_srgb8(lab[covered]), 0, 255).astype(np.uint8)
    hatch = _hatch(grey.shape) & ~in_span & opaque
    rgb8[hatch] = np.where(grey[hatch] > 0.5, 0, 255).astype(np.uint8)[:, None]       # dark lines on light grey, light on dark
    rgb8[~opaque] = BLANK
    transparent = float(np.mean(~opaque))
    outside = (float(np.mean(~in_span[opaque])) if opaque.any() else 0.0) if outside_share is None else float(outside_share)
    lo, hi = curve.span
    notes = []
    if curve.axis == TONE_AXIS:
        notes.append(f"The prediction rests on {len(curve.points)} measured tones of this mode, darkness {lo:g}..{hi:g} %, "
                     + ("chart-corrected (referenced)." if curve.referenced else "camera-relative."))
        notes.append("Dithering is not modelled: the colour of a tone is what was photographed at that tone in this mode and these settings.")
    else:
        notes.append(f"The prediction rests on {len(curve.points)} measured powers of this mode, {lo:g}..{hi:g} %, "
                     + ("chart-corrected (referenced)." if curve.referenced else "camera-relative."))
    if not curve.referenced:
        notes.append("Camera-relative colours: they are as that camera saw them under that light, not corrected by a reference chart.")
    if curve.left_out:
        notes.append(f"{curve.left_out} " + ("camera-relative" if curve.referenced else "referenced")
                     + " points of this mode are left out: the two kinds are never mixed in one curve.")
    if outside > 0:
        notes.append(f"{100 * outside:.3g} % of the picture needs " + ("a tone outside the measured darkness" if curve.axis == TONE_AXIS else "a power outside the measured")
                     + f" span {lo:g}..{hi:g} %: not predicted, hatched.")
    if transparent > 0:
        notes.append(f"{100 * transparent:.3g} % of the picture is transparent: this layer engraves nothing there, so nothing is predicted "
                     "for it and what lies under it shows.")
    shares = dict(spread_shares) if spread_shares is not None else _shares_of_shown(curve.spread_at(power), covered)
    unit = "tones" if curve.axis == TONE_AXIS else "powers"
    if shares["single"] > 0:
        notes.append(f"{100 * shares['single']:.3g} % of the predicted picture lies at {unit} that only one engraving measured: "
                     "how much the colour repeats there is not known.")
    if shares["uncertain"] > 0:
        notes.append(f"{100 * shares['uncertain']:.3g} % of the predicted picture lies at {unit} where independent engravings of this mode "
                     f"differ by more than {agreement.AGREEMENT_DE:g} ΔE (up to {shares['max_de']:.3g}): read the colour there as a range, not a value.")
    if applied["assumed"]:
        notes.append("Picture adjustments applied with standard formulas, assumed (LightBurn does not publish its own): "
                     + ", ".join(f"{t} {values[t]:g}" for t in applied["assumed"]) + ".")
    if applied["not_modelled"]:
        notes.append("Picture adjustments not modelled and left out of the prediction: "
                     + ", ".join(f"{t} {values[t]:g}" for t in applied["not_modelled"]) + ".")
    return {"lab": lab, "rgb8": rgb8, "covered": covered, "outside_share": outside, "referenced": curve.referenced, "spread": shares,
            "transparent_share": transparent, "span": [lo, hi], "power_range": None if curve.axis == TONE_AXIS else [float(min_power), float(max_power)], "axis": curve.axis,
            "adjustments": applied, "notes": notes}


def _shares_of_shown(spread: np.ndarray, covered: np.ndarray) -> dict:
    """``share_by_spread`` for the picture as it is shown, when the caller gives no shares of the whole picture."""
    total = int(covered.sum())
    known = covered & np.isfinite(spread)
    if not total:
        return {"uncertain": 0.0, "single": 0.0, "max_de": None}
    return {"uncertain": float((known & (spread > agreement.AGREEMENT_DE)).sum() / total), "single": float((covered & ~np.isfinite(spread)).sum() / total),
            "max_de": float(spread[known].max()) if known.any() else None}


def side_by_side(picture_grey, rgb8: np.ndarray) -> np.ndarray:
    """The picture (left) and its predicted look (right) as one RGB uint8 image; the prediction is scaled to the picture if needed."""
    grey = _picture(picture_grey)
    h, w = grey.shape
    right = np.asarray(rgb8, np.uint8)
    if right.shape[:2] != (h, w):
        right = cv2.resize(right, (w, h), interpolation=cv2.INTER_NEAREST)
    return np.hstack([np.repeat(_grey8(grey)[..., None], 3, axis=2), np.full((h, GAP, 3), 255, np.uint8), right])


def to_png(rgb: np.ndarray) -> bytes:
    """PNG bytes of an RGB uint8 image (OpenCV writes BGR)."""
    ok, buf = cv2.imencode(".png", cv2.cvtColor(np.ascontiguousarray(rgb, np.uint8), cv2.COLOR_RGB2BGR))
    if not ok:
        raise ValueError("the image could not be encoded as PNG")
    return buf.tobytes()


def _picture(picture_grey) -> np.ndarray:
    if picture_grey is None:
        raise PredictionError("the layer has no picture: there is nothing to predict")
    grey = np.asarray(picture_grey, np.float64)
    if grey.ndim != 2 or grey.size == 0:
        raise PredictionError("the picture is empty or not a single grey channel: there is nothing to predict")
    if not np.isfinite(grey).all() or grey.min() < 0 or grey.max() > 1:
        raise PredictionError("the grey levels of the picture must lie within 0..1")
    return grey


def _grey8(grey: np.ndarray) -> np.ndarray:
    return np.round(grey * 255).astype(np.uint8)


def _hatch(shape: tuple[int, int]) -> np.ndarray:
    """Diagonal lines over the whole picture; a pixel not predicted is drawn as a line where this is true."""
    period = max(HATCH_PERIOD, max(shape) // HATCH_PER_SIDE)
    y, x = np.ogrid[:shape[0], :shape[1]]
    return (x + y) % period < max(2, period // 4)
