"""Tones of a picture engraved on a grayscale scale, part by part (REQ-062).

A picture of people is split into parts (:mod:`people`) and each part may get its own rule; the rules come from the operator by hand or
from the AI (:mod:`ai_picture`), and the greys are always chosen here, on the scale at the chosen Min and Max, never by the model:

* ``as_is``: the grey as LightBurn sees the picture (by luminance), or the greys chosen for its colours when the whole picture is
  coloured that way;
* ``photo``: for each pixel the grey whose colour on the scale is nearest the pixel's own colour;
* ``neutral``: black and white - only the greys whose colour on the scale is nearly grey (``NEUTRAL_CHROMA``), the light and dark of the
  part kept, its lightness stretched over the lightness those greys reach or over the rule's ``range`` (L* from .. to);
* ``colour``: one target colour (``lab``), the light and dark of the part kept around it at ``CONTRAST``, each pixel the nearest grey;
* ``even``: one grey for the whole part, the one whose colour is nearest the target.

A part without a rule keeps the picture's own greys. Pure functions on numpy arrays.
"""
from __future__ import annotations

from typing import Iterable, Mapping

import numpy as np

from . import grayscale, prediction
from .people import PARTS

KINDS = ("as_is", "photo", "neutral", "colour", "even")
NEUTRAL_CHROMA = 8.0                # C* at or below which a colour of the scale counts as grey for "black and white"
NEUTRAL_LEAST = 4                   # with fewer such greys, the least coloured quarter of the scale is used
CONTRAST = 0.5                      # how much of a part's own light and dark a target colour keeps
STRETCH = (2.0, 98.0)               # percentiles of a part's lightness stretched over the range of its greys


class RuleError(ValueError):
    """A rule that cannot be applied; the message is for the operator."""


def check(rules) -> list[dict]:
    """The rules as plain dicts with checked values: one per part at most, a known part and kind, a target colour for ``colour`` and
    ``even``, an optional lightness range for ``neutral``."""
    if rules is None:
        return []
    if not isinstance(rules, list) or len(rules) > len(PARTS):
        raise RuleError(f"the rules of the parts must be a list of at most {len(PARTS)}")
    out, seen = [], set()
    for rule in rules:
        if not isinstance(rule, Mapping):
            raise RuleError("each rule must name a part and what to do with it")
        part, kind = rule.get("part"), rule.get("kind")
        if part not in PARTS or part in seen:
            raise RuleError(f"a rule must name one of the parts {', '.join(PARTS)}, each once")
        if kind not in KINDS:
            raise RuleError(f"a rule must be one of {', '.join(KINDS)}")
        seen.add(part)
        clean = {"part": part, "kind": kind}
        if kind in ("colour", "even"):
            lab = rule.get("lab")
            if (not isinstance(lab, (list, tuple)) or len(lab) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in lab)
                    or not 0 <= lab[0] <= 100 or not all(-128 <= v <= 128 for v in lab[1:])):
                raise RuleError("a target colour must be L*a*b*: L 0..100, a and b -128..128")
            clean["lab"] = [float(v) for v in lab]
        if kind == "neutral" and rule.get("range") is not None:
            rng = rule["range"]
            if (not isinstance(rng, (list, tuple)) or len(rng) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in rng)
                    or not 0 <= rng[0] < rng[1] <= 100):
                raise RuleError("the lightness range of black and white must be two L* values, 0 <= from < to <= 100")
            clean["range"] = [float(rng[0]), float(rng[1])]
        out.append(clean)
    return out


def neutral_levels(table: dict) -> list[int]:
    """The grey levels whose colour on the scale is nearly grey: C* <= ``NEUTRAL_CHROMA``, or the least coloured quarter of the measured
    levels when fewer than ``NEUTRAL_LEAST`` are that grey."""
    known = [r for r in table["levels"] if r["lab"] is not None]
    chroma = {r["level"]: float(np.hypot(r["lab"][1], r["lab"][2])) for r in known}
    grey = [lv for lv, c in chroma.items() if c <= NEUTRAL_CHROMA]
    if len(grey) >= NEUTRAL_LEAST:
        return sorted(grey)
    least = sorted(chroma, key=lambda lv: (chroma[lv], lv))[:max(NEUTRAL_LEAST, len(chroma) // 4)]
    return sorted(least)


def _stretch(lightness: np.ndarray, low: float, high: float) -> np.ndarray:
    a, b = np.percentile(lightness, STRETCH)
    t = np.clip((lightness - a) / (b - a), 0.0, 1.0) if b > a else np.full_like(lightness, 0.5)
    return low + t * (high - low)


def greys(lab: np.ndarray, base_grey8: np.ndarray, parts: np.ndarray, rules: Iterable[Mapping], curve: prediction.Curve,
          min_power: float, max_power: float) -> dict:
    """The 8-bit grey of every pixel (255 white) of a picture whose colours are ``lab`` and whose parts are ``parts`` (same shape):
    ``base_grey8`` where a part has no rule, each rule's greys inside its part. Also, per rule, the share of the picture it covers and
    how near its greys come to what was wanted (median dE), so the operator sees what the scale could do."""
    out = np.array(base_grey8, np.uint8, copy=True)
    table = grayscale.scale_of_greys(curve, min_power, max_power)
    report = []
    for rule in rules:
        mask = parts == PARTS.index(rule["part"])
        share = float(mask.mean()) if mask.size else 0.0
        kind = rule["kind"]
        if not mask.any() or kind == "as_is":
            report.append({"part": rule["part"], "kind": kind, "share": round(share, 4), "median_de": None})
            continue
        pixels = lab[mask]
        levels = None
        if kind == "photo":
            wanted = pixels
        elif kind == "neutral":
            levels = neutral_levels(table)
            reach = [table["levels"][lv]["lab"][0] for lv in levels]
            low, high = rule.get("range") or (min(reach), max(reach))
            wanted = np.stack([_stretch(pixels[:, 0], low, high), np.zeros(len(pixels)), np.zeros(len(pixels))], axis=-1)
        elif kind == "colour":
            target = np.asarray(rule["lab"], float)
            light = np.clip(target[0] + (pixels[:, 0] - np.median(pixels[:, 0])) * CONTRAST, 0.0, 100.0)
            wanted = np.stack([light, np.full(len(pixels), target[1]), np.full(len(pixels), target[2])], axis=-1)
        else:                                                    # even: one grey, the nearest to the target
            wanted = np.asarray(rule["lab"], float)[None]
        found = grayscale.grey_for_colours(wanted, curve, min_power, max_power, levels=levels)
        out[mask] = found["grey8"] if kind != "even" else found["grey8"][0]
        report.append({"part": rule["part"], "kind": kind, "share": round(share, 4), "median_de": round(float(np.median(found["delta_e"])), 1)})
    return {"grey8": out, "rules": report}
