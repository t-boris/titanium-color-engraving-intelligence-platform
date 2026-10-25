"""How well a photo engraving came out (feature photo-engraving-quality, DEC-001): what a photograph shows of an image layer, judged as a
picture rather than as colours.

* **Tone**, from the layer's tonal profile (``ingest._tonal_profile`` of the picture, or ``_ramp_profile`` of a grey ramp at the same
  settings): the colour at each grey level, black (0) to white (1). From it:
  ``levels``      how many different tones a viewer tells apart in the picture's order: walking from black to white, a grey is a new
                  tone when its colour is at least ``JND`` (ΔE76) from the last new tone and it is not darker than that tone by more than
                  half of ``JND``, so noise smaller than that and greys out of order never count; ``levels_share`` is the new tones over
                  the steps measured;
  ``range_L``     how much lighter the white end is than the black end (L*);
  ``shadows_to``  the grey up to which everything looks like the black end (within ``FLAT_DE``): blocked shadows;
  ``highlights_from`` the grey from which everything looks like the white end: lost highlights;
  ``reversals``   greys where the lightness turns back by more than ``JND`` (a darker grey engraved lighter): a tone that is out of order;
                  ``reversal_share`` is their share of the steps;
  ``mid_darkness`` how dark the middle grey came out between the two ends (0 = like the white end, 1 = like the black end): 0.5 is
                  the picture's own tone; above it the mid-tones are darker (in a dot kind: dot gain), below lighter; not given when the
                  ends are less than ``MIN_RANGE`` apart (nothing to place the middle between);
  ``mean_L``      how light it came out on average: a picture's greys weighted by their area, a grey ramp's steps alike (the copies of
                  one plate compare by it: lighter or darker).
* **Detail** (:func:`detail`), from the photograph laid over the picture: at each scale (0.2, 0.4, 0.8 mm) the share of the picture's
  own contrast that the engraving keeps (a regression slope of the photograph's band of that scale on the picture's band, after the
  tone curve, so an engraving that only lightens keeps 1), how much of it is not the picture (grain, ΔL*), and the same along the scan
  lines and across them (blur along one direction only points at the scan, not the picture).
* **Findings** (:func:`findings`, REQ-003): what a layer's tone and detail say, each with the settings that usually correct it
  (``PRIOR_MOVES``: the physics of the process, marked ``basis: "prior"`` until plates measure them).
* **Copies of one plate compared** (:func:`compare`): ranked by :func:`score`, what each changed setting did against the centre copy
  (lighter or darker, shadows, highlights, tones, detail), and the next plate: centred on the best copy, the step halved (DEC-003).

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
FULL_RANGE_L = 40.0             # L*: a lightness range from which a photo engraving has its full contrast (the workshop's best reach 40–50)
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
        if float(np.linalg.norm(lab - anchor)) >= JND and lab[0] >= anchor[0] - JND / 2:
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
            "mean_L": round(float(np.average(lightness, weights=counts) if measured_by == "picture" and counts.sum() > 0 else lightness.mean()), 1),
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
    keeps its order, times the contrast (the lightness range over ``FULL_RANGE_L``, at most 1: a scale whose every step is told apart over
    25 L* still looks pale beside one over 45 L*), times the detail kept at 0.4 mm when it was measured (capped at 1: an engraving cannot
    keep more than the picture has)."""
    if not tone_:
        return None
    value = tone_["levels_share"] * (1.0 - tone_["reversal_share"]) * max(0.0, min(1.0, tone_["range_L"] / FULL_RANGE_L))
    kept = (detail_ or {}).get("kept")
    if kept is not None:
        value *= max(0.0, min(1.0, kept))
    return round(value, 3)


def ordered_span(tonal: dict | None) -> dict | None:
    """The part of a grayscale ramp's power span that engraves the most tones in order: on titanium the oxide's colour turns back lighter
    past some power, and a picture across the turn has reversed tones. Of every run of three or more neighbouring steps with no reversal,
    the one with the most tones told apart over the whole ramp's steps, times its contrast (as :func:`score`), the longer of two alike; its
    steps (their greys stretched to 0..1), its tone and its Min and Max power (the lightest step's and the darkest's). None without the
    steps' powers, or when the whole ramp keeps its tones in order."""
    bins = _bins(tonal or {})
    if len(bins) < 3 or any(b.get("power_pct") is None for b in bins) or not (tone(tonal) or {}).get("reversals"):
        return None
    best = None
    for i in range(len(bins)):
        for j in range(i + 2, len(bins)):
            lo, hi = bins[i]["gray"], bins[j]["gray"]
            if hi <= lo:
                continue
            part = {**tonal, "bins": [{**b, "gray": round((b["gray"] - lo) / (hi - lo), 4)} for b in bins[i:j + 1]]}
            tone_ = tone(part)
            if tone_ is None or tone_["reversals"]:
                continue
            value = (tone_["levels"] - 1) / (len(bins) - 1) * max(0.0, min(1.0, tone_["range_L"] / FULL_RANGE_L))
            if best is None or value > best[0] + 1e-9 or (value > best[0] - 1e-9 and j - i > best[2] - best[1]):
                best = (value, i, j, tone_, part)
    if best is None or (best[1], best[2]) == (0, len(bins) - 1):
        return None
    value, i, j, tone_, part = best
    return {"tonal": part, "tone": tone_, "score": round(value, 3), "min_power": float(bins[j]["power_pct"]), "max_power": float(bins[i]["power_pct"])}


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


# -- findings (REQ-003) -------------------------------------------------------------------------------------------------------------
BLOCKED_SHARE = 0.15            # a share of the grey scale (2 of 16 steps) that looks like one end is worth a change
FLAT_RANGE_L = 15.0             # L*: a picture whose black end is less than this darker than its white end barely shows
REVERSED_SHARE = 0.1            # a share of the steps out of order
MID_DARK, MID_LIGHT = 0.65, 0.35  # mid_darkness beyond which the mid-tones came out darker (dot gain) or lighter than the picture's
DETAIL_KEPT = 0.7               # the share of the picture's contrast at 0.4 mm below which a viewer sees it soft
GRAIN_L = 2.0                   # L*: what the photograph adds at 0.4 mm and the picture has not, seen as grain


def _up(setting: str) -> dict:
    return {"setting": setting, "direction": "up"}


def _down(setting: str) -> dict:
    return {"setting": setting, "direction": "down"}


# the settings that usually correct a finding, the strongest first: (dot kinds, grayscale). Priors from how a fibre laser marks titanium:
# more energy per area (power up, speed down, lines closer) darkens and spreads; the dot width correction shrinks each dot (dot gain);
# in grayscale Max sets the black end and Min the white one, and past some Max the oxide's colour turns back lighter.
PRIOR_MOVES: dict[str, tuple[list[dict], list[dict]]] = {
    "flat": ([_up("power"), _down("speed"), _down("line_interval")], [_up("power"), _down("speed")]),
    "reversed": ([_up("power")], [_down("power")]),
    "shadows_blocked": ([_down("power"), _up("dot_width"), _up("line_interval")], [_down("power")]),
    "highlights_lost": ([_down("dot_width"), _up("power")], [_down("min_power")]),
    "midtones_dark": ([_up("dot_width"), _up("line_interval")], []),
    "midtones_light": ([_down("dot_width")], []),
    "detail_lost": ([_down("power"), _down("line_interval")], [_down("power"), _down("line_interval")]),
    "grainy": ([{"setting": "dither", "to": "stucki"}, _down("line_interval")], [_down("line_interval")]),
}


def findings(tone_: dict | None, detail_: dict | None, dither: str) -> list[dict]:
    """What a photo layer's tone and detail say (REQ-003): a list of ``{"code", "value", "moves", "basis"}``, the most important first;
    ``moves`` are the settings that usually correct it (``PRIOR_MOVES``, ``basis: "prior"``). ``good`` alone when nothing is wrong; empty
    when nothing was measured."""
    if not tone_:
        return []
    dots = str(dither or "grayscale").lower() != "grayscale"
    out: list[dict] = []

    def add(code: str, value) -> None:
        moves = PRIOR_MOVES[code][0 if dots else 1]
        out.append({"code": code, "value": value, "moves": [dict(m) for m in moves], "basis": "prior" if moves else None})

    flat = tone_["range_L"] < FLAT_RANGE_L
    if flat:
        add("flat", tone_["range_L"])
    if tone_["reversal_share"] >= REVERSED_SHARE:
        add("reversed", tone_["reversals"])
        if not flat and dots:                    # dots of one power cannot turn back by themselves: look at the photograph first
            out[-1].update(moves=[], basis=None)
    if not flat:
        if tone_["shadows_blocked"] >= BLOCKED_SHARE:
            add("shadows_blocked", tone_["shadows_to"])
        if tone_["highlights_lost"] >= BLOCKED_SHARE:
            add("highlights_lost", tone_["highlights_from"])
        mid = tone_.get("mid_darkness")
        if mid is not None and mid > MID_DARK:
            add("midtones_dark", mid)
        elif mid is not None and mid < MID_LIGHT:
            add("midtones_light", mid)
    kept, grain = (detail_ or {}).get("kept"), (detail_ or {}).get("grain_L")
    if kept is not None and kept < DETAIL_KEPT:
        add("detail_lost", kept)
    if grain is not None and grain >= GRAIN_L:
        add("grainy", grain)
    return out or [{"code": "good", "value": score(tone_, detail_), "moves": [], "basis": None}]


# -- the copies of one plate compared (REQ-003, DEC-003) ----------------------------------------------------------------------------
EFFECT_KEYS = ("mean_L", "range_L", "shadows_blocked", "highlights_lost", "levels", "mid_darkness")
SETTLED_STEP = 0.25             # the centre stayed the best at changes this small (power ±5 %): the search has settled
MIN_STEP = 0.125                # the smallest share of the first changes a next plate makes


def compare(copies: list[dict], step: float = 1.0) -> dict | None:
    """The copies of a photo-variations plate judged together. ``copies``: ``[{"copy", "variant", "ramp", "picture", "detail"}]`` in the
    plate's order, the first the centre; ``ramp`` and ``picture`` are tonal profiles (each copy is judged on its ramp, every grey alike and
    the same for every copy, else on its picture), ``detail`` the picture's :func:`detail`. Gives the copies ranked by :func:`score` (a tie
    goes to the copy that changes less), what each copy's change did against the centre (positive ``mean_L``: lighter), and the next plate:
    centred on the best copy with ``step`` halved (at least ``MIN_STEP``); none when the centre stayed the best at a step of
    ``SETTLED_STEP`` or less (``settled``). None when no copy was measured."""
    judged = []
    for item in copies:
        tone_ = tone(item.get("ramp")) or tone(item.get("picture"))
        judged.append({**item, "tone": tone_, "score": score(tone_, item.get("detail"))})
    measured = [j for j in judged if j["score"] is not None]
    if not measured:
        return None
    ranked = sorted(measured, key=lambda j: (-j["score"], j["copy"]))
    centre = judged[0]
    effects = []
    if centre["tone"] is not None:
        for j in judged[1:]:
            if j["tone"] is None:
                continue
            keys = sorted(set(centre["variant"]) | set(j["variant"]))
            changed = [{"setting": k, "from": centre["variant"].get(k), "to": j["variant"].get(k)} for k in keys
                       if centre["variant"].get(k) != j["variant"].get(k)]
            effect = {"copy": j["copy"], "changed": changed}
            for key in EFFECT_KEYS:
                a, b = centre["tone"].get(key), j["tone"].get(key)
                effect[key] = round(b - a, 3) if a is not None and b is not None else None
            a, b = (centre.get("detail") or {}).get("kept"), (j.get("detail") or {}).get("kept")
            effect["kept"] = round(b - a, 2) if a is not None and b is not None else None
            effect["score"] = round(j["score"] - centre["score"], 3)
            effects.append(effect)
    best = ranked[0]
    settled = best["copy"] == judged[0]["copy"] and step <= SETTLED_STEP
    return {"ranked": [{"copy": j["copy"], "score": j["score"], "findings": findings(j["tone"], j.get("detail"), j["variant"].get("dither"))}
                       for j in ranked],
            "best": best["copy"], "effects": effects, "settled": settled,
            "next": None if settled else {"centre": best["variant"], "step": max(MIN_STEP, round(step / 2, 4))}}


def judge(tonal: dict | None, detail_: dict | None, dither: str) -> dict | None:
    """Everything said of one photo layer of a check: its tone, its detail (when measured), the score and the findings; None when its
    tones could not be read."""
    tone_ = tone(tonal)
    if tone_ is None:
        return None
    return {"algorithm": ALGORITHM, "tone": tone_, "detail": detail_, "score": score(tone_, detail_), "findings": findings(tone_, detail_, dither)}


def plate_report(variations: dict, layers: list[dict]) -> dict | None:
    """The copies of a photo-variations plate (``variations``: its geometry's, with each copy's settings, label and layer names) compared
    on a check's ``layers`` (each with its ``tonal`` profile and, for a picture, its measured ``quality``); each copy keeps its label. None
    when no copy was measured."""
    by_name = {rep.get("name"): rep for rep in layers}
    copies = []
    for item in variations.get("copies") or []:
        picture, ramp = by_name.get(item["picture_layer"]) or {}, by_name.get(item["ramp_layer"]) or {}
        copies.append({"copy": item["copy"], "variant": item["variant"], "ramp": ramp.get("tonal"), "picture": picture.get("tonal"),
                       "detail": (picture.get("quality") or {}).get("detail")})
    found = compare(copies, float(variations.get("step") or 1.0))
    if found is None:
        return None
    labels = {item["copy"]: item["label"] for item in variations.get("copies") or []}
    for item in found["ranked"] + found["effects"]:
        item["label"] = labels.get(item["copy"])
    return {**found, "best_label": labels.get(found["best"]), "step": float(variations.get("step") or 1.0)}
