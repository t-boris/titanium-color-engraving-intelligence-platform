"""Grayscale scales (photo engraving in LightBurn's grayscale mode): what grey level of a picture comes out as what colour.

In grayscale mode every setting of the layer is fixed except the power, which LightBurn sets per pixel from the grey level:
the lightest grey gets Min, the darkest Max, linearly between (DEC-057). On titanium the power drives the oxide through its colours,
so when the fixed settings are chosen away from black the grey levels of one picture engrave in several colours. A *scale* is one
such set of fixed settings with its measured "power -> colour" curve; this module turns a curve into "grey -> colour" for a chosen
Min and Max, finds the grey for a wanted colour, and draws the grey ramp that measures a scale on a test plate.

* A grey ramp is a row of ``RAMP_STEPS`` flat steps from white (left) to black (right), each a known grey, so each step is one
  power: Min + (Max - Min) x (1 - grey). Steps are measured by their place on the plate, not by binning the picture's grey: the
  colours of a scale need not darken step by step (gold, violet, blue ...), so a rank correlation says nothing about them.
* The picture is written at the layer's DPI (25.4 / line interval, as LightBurn links them) with that DPI in its PNG header, so LightBurn
  neither resamples nor resizes it (the operator's own Image layers carry the same header: W = columns / dpi x 25.4 mm).
* Grey levels are written as 8-bit values 0..255 (0 black). A grey read back is level / 255.

Pure functions on plain data and numpy arrays; nothing here reads the store.
"""
from __future__ import annotations

import struct
import zlib
from typing import Iterable, Mapping

import cv2
import numpy as np
from scipy.spatial import cKDTree

from . import color, prediction

RAMP_STEPS = 16
LEVELS = 256                     # grey levels of an 8-bit picture
MM_PER_INCH = 25.4


def ramp_greys(steps: int = RAMP_STEPS) -> list[float]:
    """The greys of a ramp, white first: 1, ..., 0 in equal steps (8-bit exact: k x 17 / 255 for 16 steps)."""
    if steps < 2:
        raise ValueError("a grey ramp needs at least two steps")
    return [round(1.0 - k / (steps - 1), 6) for k in range(steps)]


def ramp_steps(ramp: Mapping) -> list[dict]:
    """The step rectangles of a ramp ``{"x", "y", "width", "height", "greys"}`` in plan millimetres, left to right."""
    greys = list(ramp["greys"])
    x, y, width, height = (float(ramp[k]) for k in ("x", "y", "width", "height"))
    step = width / len(greys)
    return [{"grey": float(g), "x": x + i * step, "y": y, "width": step, "height": height} for i, g in enumerate(greys)]


def image_dpi(line_interval_mm: float) -> int:
    """The DPI LightBurn links to an image layer's line interval: 25.4 / interval, rounded (0.0169 mm -> 1503, as in the
    operator's own file)."""
    interval = float(line_interval_mm)
    if not np.isfinite(interval) or interval <= 0:
        raise ValueError(f"an image layer needs a positive line interval, got {line_interval_mm!r}")
    return max(1, round(MM_PER_INCH / interval))


def ramp_picture(ramp: Mapping, dpi: float) -> np.ndarray:
    """The 8-bit grey picture of a ramp at ``dpi``: one column band per step, the steps as equal as whole pixels allow."""
    greys = list(ramp["greys"])
    cols = max(len(greys), round(float(ramp["width"]) / MM_PER_INCH * dpi))
    rows = max(1, round(float(ramp["height"]) / MM_PER_INCH * dpi))
    edges = np.round(np.linspace(0, cols, len(greys) + 1)).astype(int)
    line = np.empty(cols, np.uint8)
    for i, g in enumerate(greys):
        line[edges[i]:edges[i + 1]] = round(255 * float(g))
    return np.repeat(line[None, :], rows, axis=0)


def png_with_dpi(picture: np.ndarray, dpi: float) -> bytes:
    """PNG bytes of an 8-bit grey (or BGR / BGRA) picture with a pHYs chunk stating ``dpi``: LightBurn sizes a picture by it."""
    ok, buf = cv2.imencode(".png", np.ascontiguousarray(picture))
    if not ok:
        raise ValueError("the picture could not be encoded as PNG")
    data = buf.tobytes()
    per_metre = round(float(dpi) / 0.0254)
    body = b"pHYs" + struct.pack(">IIB", per_metre, per_metre, 1)
    chunk = struct.pack(">I", 9) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    at = 8 + 25                                                  # signature, then the IHDR chunk (13 bytes of data)
    return data[:at] + chunk + data[at:]


def grey_power(grey, min_power: float, max_power: float) -> np.ndarray:
    """DEC-057 for grey 0..1: the power each grey is engraved with."""
    return prediction.grey_to_power(grey, min_power, max_power)


def scale_of_greys(curve: prediction.Curve, min_power: float, max_power: float, levels: int = LEVELS) -> dict:
    """"Which grey makes which colour" on a curve at Min..Max: for each 8-bit level (0 black .. 255 white) its power, the colour
    the curve gives there (None outside the measured span, never extrapolated) and how far independent engravings disagree there."""
    level = np.arange(levels)
    power = grey_power(level / (levels - 1), min_power, max_power)
    lab = curve.lab_at(power)
    spread = curve.spread_at(power)
    rgb = np.clip(color.lab_to_srgb8(np.nan_to_num(lab)), 0, 255).astype(int)
    rows = []
    for i in range(levels):
        known = bool(np.isfinite(lab[i, 0]))
        rows.append({"level": int(level[i]), "power": round(float(power[i]), 3),
                     "lab": [round(float(v), 2) for v in lab[i]] if known else None,
                     "hex": "#%02x%02x%02x" % tuple(rgb[i]) if known else None,
                     "spread_de": None if not np.isfinite(spread[i]) else round(float(spread[i]), 1)})
    inside = [r for r in rows if r["lab"] is not None]
    return {"min_power": float(min_power), "max_power": float(max_power), "levels": rows, "measured_levels": len(inside),
            "span": list(curve.span)}


def usable_greys(curve: prediction.Curve, min_power: float, max_power: float, levels: Iterable[int] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """The 8-bit greys that can be chosen at Min..Max (every level inside the measured span, or only ``levels``), ascending, and the colour
    (Lab) the curve gives each. Refused when no level of Min..Max lies inside the span."""
    level = np.arange(LEVELS)
    lab = curve.lab_at(grey_power(level / (LEVELS - 1), min_power, max_power))
    keep = np.isfinite(lab[:, 0])
    if levels is not None:
        keep &= np.isin(level, list(levels))
    if not keep.any():
        raise prediction.PredictionError(f"no grey level of Min {min_power:g} % .. Max {max_power:g} % falls inside the measured powers "
                                         f"{curve.span[0]:g}..{curve.span[1]:g} %: there is no colour to choose from")
    return level[keep].astype(np.uint8), np.round(lab[keep], 2)


def grey_for_colours(lab_pixels: np.ndarray, curve: prediction.Curve, min_power: float, max_power: float,
                     levels: Iterable[int] | None = None) -> dict:
    """For each wanted colour (Lab, shape (..., 3)) the 8-bit grey whose power at Min..Max the curve turns into the nearest colour
    (CIE76), with that colour and its distance. ``levels`` limits the greys allowed (a palette chosen on the scale); by default every
    level inside the measured span. Refused when no level of Min..Max lies inside the span."""
    greys, labs = usable_greys(curve, min_power, max_power, levels)
    tree = cKDTree(labs)
    wanted = np.asarray(lab_pixels, np.float64)
    distance, index = tree.query(wanted.reshape(-1, 3))
    grey8 = greys[index].reshape(wanted.shape[:-1])
    reached = labs[index].reshape(wanted.shape)
    return {"grey8": grey8, "lab": reached, "delta_e": distance.reshape(wanted.shape[:-1]), "choices": len(greys)}


def compare(own: list[prediction.Point], others: list[prediction.Point], tolerance: float = 5.0) -> dict:
    """The points of one engraving (``own``) against the curve of ``others`` at the engraving's own size (``prediction.curve_at``, DEC-107):
    at each of its powers inside that curve's span, the grey of the picture it was measured at, the colour it measured, the colour the
    others predict there and the distance (CIE76) between them; their median and largest, and the share within ``tolerance``. Nothing is
    compared without others, nor when the others measured no size near it or around it (``size`` says which sizes they measured): a
    colour at another size is not a prediction of this one. The photographs of one engraving are one colour at each power (DEC-045)."""
    out = {"compared": 0, "median_de": None, "max_de": None, "within": None, "bands": [], "size": None}
    if not own or not others:
        return out
    own = prediction.per_engraving(own)
    curve = prediction.curve_at(others, own[0].source.get("row_mm"))
    out["size"] = dict(curve.size)
    if curve.size["how"] == prediction.OUTSIDE:
        return out
    powers = np.array([p.power for p in own])
    predicted = curve.lab_at(powers)
    inside = np.isfinite(predicted[:, 0])
    if not inside.any():
        return out
    measured = np.array([p.lab for p in own])
    de = np.linalg.norm(measured[inside] - predicted[inside], axis=1)
    kept = [p for p, keep in zip(own, inside) if keep]
    out.update(compared=int(inside.sum()), median_de=round(float(np.median(de)), 1), max_de=round(float(de.max()), 1),
               within=round(float(np.mean(de <= tolerance)), 3),
               bands=[{"power": round(float(p.power), 2), "gray": p.source.get("gray"), "lab": [round(float(v), 2) for v in p.lab],
                       "predicted": [round(float(v), 2) for v in lab], "de": round(float(d), 1)}
                      for p, lab, d in zip(kept, predicted[inside], de)])
    return out


def confirmation(points: Iterable[prediction.Point], tolerance: float = 5.0) -> dict:
    """Do the engravings of a scale confirm each other? Each engraving (its photographs together, DEC-045) is compared with the curve built from
    every OTHER engraving of the same kind at its own size (``compare``): at each of its powers inside that curve's span, the distance
    (CIE76) between what it measured and what the others predict. With one engraving, or none other near its size, nothing is
    confirmed yet, and that is said."""
    points = list(points)
    by: dict[tuple, list[prediction.Point]] = {}
    for p in points:
        by.setdefault(prediction._engraving_of(p.source), []).append(p)
    rows = []
    for key, own in by.items():
        others = [p for k, ps in by.items() if k != key for p in ps if p.referenced == own[0].referenced]
        first = own[0].source
        compared = compare(own, others, tolerance)
        rows.append({"engraving": {"kind": first.get("kind"), "pair_id": first.get("pair_id"), "title": first.get("title"),
                                   "how": first.get("how"), "experiment": first.get("experiment"), "photo": first.get("photo")},
                     "row_mm": first.get("row_mm"), "points": len(own), **compared,
                     "bands": [{"power": b["power"], "de": b["de"]} for b in compared["bands"]]})
    compared = [r for r in rows if r["compared"]]
    every = [b["de"] for r in compared for b in r["bands"]]
    return {"engravings": len(rows), "tolerance_de": tolerance, "rows": rows,
            "median_de": round(float(np.median(every)), 1) if every else None,
            "within": round(float(np.mean(np.array(every) <= tolerance)), 3) if every else None,
            "confirmed": bool(every) and float(np.median(every)) <= tolerance}
