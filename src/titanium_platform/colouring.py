"""Colouring a picture by its objects, like a colouring book (0.21.0): the lips, the glasses, the hair, a piece of the background ... each
takes a main colour of the scale of its own, and its light and dark tones are laid around that colour.

The objects are those of :mod:`objects`. An object with a main colour (``choices``: its key, :func:`key_of`, to ``{"power", "shift"}``)
keeps its own drawing in the colours of one stretch of the scale:

* :func:`path_through` the main colour: from it towards light and towards dark, steps of at most ``MAX_STEP`` dE between neighbouring
  colours (so the stretch stays in the main colour's family: no jump from gold to blue), lightness moving only one way on each side, and
  of such stretches the smoothest (dynamic programming over the greys of the scale; the power order is not kept, the colour is);
* the object's tones (its lightness smoothed and its detail raised as ``drawing.choose`` does, ``drawing.detailed``) stretched over the
  path, the object's middle tone on the main colour (a power curve of the tone); ``shift`` (-1 darker .. 1 lighter) moves the middle
  tone up or down the path by ``SHIFT_SPAN`` of it. Each pixel takes the grey of the path at its lightness.

An object without a main colour keeps the greys it has (the whole picture laid along one path, ``drawing.choose``: «Авто»). Ready
themes (:func:`theme`) give every object a main colour from the scale's own colours (``candidates``): warm, cool, contrasting or
random. Pure functions on numpy arrays; nothing here reads the store.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np

from . import color, drawing, grayscale, prediction

MAX_STEP = 5.0                  # dE: the most a path through a main colour moves between neighbouring colours
SHIFT_SPAN = 0.25               # «светлее/темнее» at its end (1 or -1) moves the middle tone this share of the path's lightness
STRETCH = (2.0, 98.0)           # percentiles of an object's tones laid over its path, darkest to lightest
GAMMA = (0.15, 6.0)             # the power curve that puts the middle tone on the main colour stays within these
CANDIDATE_DE = 8.0              # dE: the scale's colours offered for a theme are at least this far apart
WARM_HUE, COOL_HUE = (15.0, 110.0), (160.0, 330.0)   # degrees of hue (a*, b*): red to yellow, and green-blue to violet
COLOURED = 8.0                  # chroma from which a colour counts as warm or cool rather than grey
THEMES = ("warm", "cool", "contrast", "random")
SKIN = ("face_skin", "body_skin")


def key_of(obj: Mapping) -> str:
    """The key an object's main colour is kept under: its kind, and for a background piece other than the main one its number."""
    return obj["kind"] if not obj.get("piece") else f"{obj['kind']}-{obj['piece']}"


def _walk(labs: np.ndarray, start: int, sign: int, max_step: float) -> list[int]:
    """From grey ``start`` towards light (``sign`` 1) or dark (-1): the smoothest way, by steps of at most ``max_step`` dE with the
    lightness moving only that way (by more than ``drawing.PATH_RISE_L`` never back), to the farthest grey it reaches; ``start`` first."""
    side = [i for i in range(len(labs)) if sign * (labs[i, 0] - labs[start, 0]) >= 0 and i != start]
    order = [start] + sorted(side, key=lambda i: sign * labs[i, 0])
    lab = labs[order].astype(np.float64)
    cost, before = np.full(len(order), np.inf), np.full(len(order), -1)
    cost[0] = 0.0
    for j in range(1, len(order)):
        steps = np.linalg.norm(lab[j] - lab[:j], axis=1)
        step = cost[:j] + steps ** 2
        step[(steps > max_step) | (sign * (lab[:j, 0] - lab[j, 0]) > drawing.PATH_RISE_L)] = np.inf
        if np.isfinite(step).any():
            k = int(np.argmin(step))
            cost[j], before[j] = step[k], k
    reached = np.flatnonzero(np.isfinite(cost))
    j = int(reached[np.argmax(sign * lab[reached, 0])])
    kept = []
    while j != -1:
        kept.append(order[j])
        j = int(before[j])
    return kept[::-1]


def path_through(labs: np.ndarray, main: int, max_step: float = MAX_STEP) -> np.ndarray:
    """The indices (into ``labs``, the colours of the usable greys) of the stretch of the scale through grey ``main``, lightest first."""
    up, down = _walk(labs, main, 1, max_step), _walk(labs, main, -1, max_step)
    return np.array(up[::-1] + down[1:], np.int64)


def _main_grey(greys: np.ndarray, power: float, min_power: float, max_power: float) -> int:
    return int(np.argmin(np.abs(grayscale.grey_power(greys / (grayscale.LEVELS - 1), min_power, max_power) - float(power))))


def colour(lab: np.ndarray, opaque: np.ndarray, labels: np.ndarray, objects: list[dict], choices: Mapping, curve: prediction.Curve,
           min_power: float, max_power: float, px_per_mm: float, base: Mapping) -> dict:
    """The greys of the picture (``lab``, its colours) with every object that has a main colour in ``choices`` coloured along its path,
    the others as ``base`` has them (``drawing.choose``'s answer at the same size). ``labels``: the object of every pixel (``objects.find``,
    resized to the picture), -1 where transparent. Answers as ``drawing.choose`` does, with ``objects``: per object coloured its key, the
    main colour (power, Lab, hex), the greys on its path and the lightness the path spans."""
    greys, labs = grayscale.usable_greys(curve, min_power, max_power)
    grey8, reached = np.array(base["grey8"], copy=True), np.array(base["lab"], copy=True)
    light = drawing.detailed(np.asarray(lab, np.float64)[..., 0], px_per_mm)
    report = []
    for obj in objects:
        chosen = choices.get(key_of(obj))
        mask = (labels == obj["id"]) & opaque
        if chosen is None or not mask.any():
            continue
        main = _main_grey(greys, chosen["power"], min_power, max_power)
        on = path_through(labs, main)
        way = labs[on]
        top, bottom = float(way[0, 0]), float(way[:, 0].min())
        tones = light[mask]
        lo, hi = np.percentile(tones, STRETCH)
        t = np.clip((tones - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
        middle = float(np.clip(np.median(t), 0.05, 0.95))
        q = float(np.clip((labs[main, 0] - bottom) / max(top - bottom, 1e-6) + SHIFT_SPAN * float(chosen.get("shift", 0.0)), 0.03, 0.97))
        gamma = float(np.clip(math.log(q) / math.log(middle), *GAMMA))
        target = bottom + t ** gamma * (top - bottom)
        drop = way[0, 0] - np.minimum.accumulate(way[:, 0])                    # how far each grey of the path is below its start
        pick = on[np.clip(np.searchsorted(drop, way[0, 0] - target), 0, len(on) - 1)]
        grey8[mask], reached[mask] = greys[pick], labs[pick]
        report.append({"key": key_of(obj), "power": round(float(grayscale.grey_power(greys[main] / (grayscale.LEVELS - 1), min_power, max_power)), 2),
                       "lab": [round(float(v), 1) for v in labs[main]], "hex": _hex(labs[main]), "shift": float(chosen.get("shift", 0.0)),
                       "path": len(on), "reach": [round(bottom, 1), round(top, 1)]})
    pic = np.asarray(lab, np.float64)
    return {**base, "grey8": grey8, "lab": reached, "delta_e": np.linalg.norm(reached - pic, axis=-1),
            "order": drawing._order(pic[..., 0], reached[..., 0], opaque), "objects": report}


# -- themes ----------------------------------------------------------------------------------------------------------------------------
def candidates(curve: prediction.Curve, min_power: float, max_power: float) -> list[dict]:
    """The scale's colours a theme chooses from: the usable greys at Min..Max (lightest first), each at least ``CANDIDATE_DE`` from those
    kept before it, with its power, Lab, hex, hue (degrees) and chroma."""
    greys, labs = grayscale.usable_greys(curve, min_power, max_power)
    kept: list[int] = []
    for i in np.argsort(-labs[:, 0], kind="stable"):
        if all(np.linalg.norm(labs[i] - labs[k]) >= CANDIDATE_DE for k in kept):
            kept.append(int(i))
    out = []
    for i in kept:
        L, a, b = (float(v) for v in labs[i])
        out.append({"power": round(float(grayscale.grey_power(greys[i] / (grayscale.LEVELS - 1), min_power, max_power)), 2),
                    "lab": [round(L, 1), round(a, 1), round(b, 1)], "hex": _hex(labs[i]), "hue": round(math.degrees(math.atan2(b, a)) % 360, 1),
                    "chroma": round(math.hypot(a, b), 1)})
    return out


def theme(name: str, objects: list[dict], options: list[dict], seed: int = 0) -> dict:
    """Main colours for every object from ``options`` (:func:`candidates`): ``warm`` - the skin in the lightest warm colour, the lips in the
    reddest, the rest in warm colours darker the less light the object is; ``cool`` - the skin as warm, everything else in cool colours;
    ``contrast`` - the largest objects first, each the colour farthest from those already given; ``random`` - any colour, by ``seed``.
    Objects are given in the order of ``objects``; an object is answered under :func:`key_of` with ``{"power", "shift": 0}``."""
    if name not in THEMES:
        raise ValueError(f"no theme {name!r}")
    if not options:
        return {}
    warm = [c for c in options if c["chroma"] >= COLOURED and WARM_HUE[0] <= c["hue"] <= WARM_HUE[1]] or options
    cool = [c for c in options if c["chroma"] >= COLOURED and COOL_HUE[0] <= c["hue"] <= COOL_HUE[1]] or options
    out = {}
    if name == "random":
        rng = np.random.default_rng(seed)
        for obj in objects:
            out[key_of(obj)] = options[int(rng.integers(len(options)))]
    elif name == "contrast":
        given: list[dict] = []
        for obj in sorted(objects, key=lambda o: -o["share"]):
            pick = max(options, key=lambda c: min((_de(c, g) for g in given), default=c["lab"][0]))
            given.append(pick)
            out[key_of(obj)] = pick
    else:
        pool = warm if name == "warm" else cool
        for obj in objects:
            if obj["kind"] in SKIN:
                out[key_of(obj)] = max(warm, key=lambda c: c["lab"][0])
            elif obj["kind"] == "lips":
                out[key_of(obj)] = max(warm if name == "warm" else options, key=lambda c: c["lab"][1])     # the reddest
            else:
                out[key_of(obj)] = _by_light(pool, obj)
    return {key: {"power": c["power"], "shift": 0.0} for key, c in out.items()}


def _by_light(pool: list[dict], obj: Mapping) -> dict:
    """The colour of ``pool`` whose lightness is nearest the object's own (its mean L*), so light things stay light and dark ones dark."""
    return min(pool, key=lambda c: abs(c["lab"][0] - obj["lab"][0]))


def _de(a: Mapping, b: Mapping) -> float:
    return float(np.linalg.norm(np.subtract(a["lab"], b["lab"])))


def _hex(lab) -> str:
    r, g, b = (int(v) for v in np.clip(color.lab_to_srgb8(np.asarray([lab], np.float64))[0], 0, 255))
    return f"#{r:02x}{g:02x}{b:02x}"
