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
* Only grayscale mode is predicted: in a dithered mode the grey sets the pattern of full-power dots, not the power (DEC-052).

Pure functions on plain data: nothing is read from or written to the store, so a new Min or Max re-renders from the same curve.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import cv2
import numpy as np

from . import color, lightburn as lb

PREDICTED_MODE = "grayscale"
DITHERED = ("threshold", "ordered", "dither", "atkinson", "stucki", "jarvis", "newsprint", "halftone", "sketch")
ASSUMED = lb.MONOTONE_ADJUSTMENTS                                              # Gamma, Contrast, Brightness: applied, marked assumed
NOT_MODELLED = tuple(tag for tag in lb.BITMAP_DEFAULTS if tag not in ASSUMED)  # EnhanceAmount, EnhanceRadius, EnhanceDenoise
SPAN_TOLERANCE = 1e-6      # % power: this close to an end of the measured span counts as inside (rounding of grey -> power)
HATCH_PERIOD = 8           # px between diagonal hatch lines at least; more on a large picture, so the hatch survives scaling down
HATCH_PER_SIDE = 64        # hatch lines across the long side of a large picture
GAP = 8                    # px of white between the picture and its prediction


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

    def as_dict(self) -> dict:
        return {"span": list(self.span), "referenced": self.referenced, "left_out": self.left_out, "points": list(self.points)}


def curve(points: Iterable[Point], prefer_referenced: bool = True) -> Curve:
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
    rows = tuple({"power": k, "lab": [float(v) for v in lab], "referenced": use, "sources": [dict(p.source) for p in at[k]]}
                 for k, lab in zip(powers, labs))
    return Curve(np.array(powers), labs, rows, use, sum(p.referenced != use for p in points))


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
    """Raise PredictionError with the reason unless the layer engraves in grayscale mode, the only mode predicted (REQ-030)."""
    name = str(mode or "").strip().lower()
    if name == PREDICTED_MODE:
        return
    if not name:
        raise PredictionError("the layer states no image mode: only grayscale mode, where the grey level sets the power, is predicted")
    if name == "3dslice":
        why = "3D slicing engraves depth in repeated passes, not a tone"
    elif name in DITHERED:
        why = "it is a dithered mode: every dot is fired at full power or not at all, the grey sets the dot pattern and dithering is not modelled"
    else:
        why = "the grey level does not set the power in this mode"
    raise PredictionError(f"{mode} mode is not predicted: {why}; only grayscale mode, where the grey level sets the power, is predicted")


def render(picture_grey, min_power: float, max_power: float, curve: Curve, adjustments: Mapping | None = None) -> dict:
    """The predicted look of the picture engraved at Min..Max power: Lab and sRGB per pixel, where it is predicted, and notes that say
    what the prediction rests on and what it leaves out. Pass the picture at the resolution it is to be shown."""
    grey = _picture(picture_grey)
    applied = adjustments_of(adjustments)
    values = applied["values"]
    power = grey_to_power(adjust_grey(grey, values["Gamma"], values["Contrast"], values["Brightness"]), min_power, max_power)
    lab = curve.lab_at(power)
    covered = np.isfinite(lab[..., 0])
    rgb8 = np.repeat(_grey8(grey)[..., None], 3, axis=2)
    rgb8[covered] = np.clip(color.lab_to_srgb8(lab[covered]), 0, 255).astype(np.uint8)
    hatch = _hatch(grey.shape) & ~covered
    rgb8[hatch] = np.where(grey[hatch] > 0.5, 0, 255).astype(np.uint8)[:, None]       # dark lines on light grey, light on dark
    outside = float(np.mean(~covered))
    lo, hi = curve.span
    notes = []
    notes.append(f"The prediction rests on {len(curve.points)} measured powers of this mode, {lo:g}..{hi:g} %, "
                 + ("chart-corrected (referenced)." if curve.referenced else "camera-relative."))
    if not curve.referenced:
        notes.append("Camera-relative colours: they are as that camera saw them under that light, not corrected by a reference chart.")
    if curve.left_out:
        notes.append(f"{curve.left_out} " + ("camera-relative" if curve.referenced else "referenced")
                     + " points of this mode are left out: the two kinds are never mixed in one curve.")
    if outside > 0:
        notes.append(f"{100 * outside:.3g} % of the picture needs a power outside the measured span {lo:g}..{hi:g} %: not predicted, hatched.")
    if applied["assumed"]:
        notes.append("Picture adjustments applied with standard formulas, assumed (LightBurn does not publish its own): "
                     + ", ".join(f"{t} {values[t]:g}" for t in applied["assumed"]) + ".")
    if applied["not_modelled"]:
        notes.append("Picture adjustments not modelled and left out of the prediction: "
                     + ", ".join(f"{t} {values[t]:g}" for t in applied["not_modelled"]) + ".")
    return {"lab": lab, "rgb8": rgb8, "covered": covered, "outside_share": outside, "referenced": curve.referenced,
            "span": [lo, hi], "power_range": [float(min_power), float(max_power)], "adjustments": applied, "notes": notes}


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
