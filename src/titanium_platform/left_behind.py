"""Layers a LightBurn file left behind (REQ-050).

The operator opens the file of a work in LightBurn and moves or resizes the picture. LightBurn's tools skip the shapes of a layer whose
"Show" switch is off, so such a layer stays where the file of the work had it while every other layer moved with the picture. The photograph
then shows the visible layers where they were engraved, and the outlines of the hidden one where nothing is: the colour measured there is the
colour of another place. This module finds those layers by comparing the engraved file with the file the work exported.

Nothing here reads or writes the database or the photograph. It compares the shapes of the layers the two files share:

* the move the rest of the file made is the median of what each layer's bounding box shows (a scale, an offset and whether the axis was mirrored, on each axis);
* a layer is LEFT BEHIND when its shapes sit where the exported file had them (a move of nothing) and do not sit where that move would put them.
  A layer that was merely edited matches neither, and is not named: the comparison says nothing about it.
"""
from __future__ import annotations

import numpy as np

from . import lightburn as lb

MIN_SPAN_MM = 3.0        # a layer narrower than this on an axis does not tell the scale of that axis
SAME_MM = 0.25           # two boxes are the same shape when each of their four numbers is within this
OFFSET_MM = 1.0          # layers agree on an offset of the move when they differ by no more than this (a deleted shape moves a layer's edge)
MATCH_SHARE = 0.5        # a layer sits at a place when at least this share of its shapes has a counterpart there
NEEDED_LAYERS = 3        # layers that must follow the move before it is believed
SAME_COUNT = 0.15        # the layers share shapes when their counts differ by no more than this share (a shape or two deleted is allowed)


def _boxes(layer: lb.Layer) -> np.ndarray:
    """The bounding boxes of a layer's shapes as rows ``x0, y0, x1, y1``."""
    return np.array([(r.x, r.y, r.x + r.width, r.y + r.height) for r in layer.regions], float).reshape(-1, 4)


def _share(file_boxes: np.ndarray, expected: np.ndarray) -> float:
    """The share of the file's shapes that have a counterpart among the expected ones, within :data:`SAME_MM` on all four numbers."""
    if not len(file_boxes) or not len(expected):
        return 0.0
    near = (np.abs(file_boxes[:, None, :] - expected[None, :, :]) <= SAME_MM).all(axis=2)
    return float(near.any(axis=1).mean())


def _span(boxes: np.ndarray) -> np.ndarray:
    return np.array([boxes[:, 0].min(), boxes[:, 1].min(), boxes[:, 2].max(), boxes[:, 3].max()])


def _fit_axis(now: np.ndarray, was: np.ndarray) -> dict | None:
    """The move one axis made, from the spans of the shared layers on it (rows ``min, max``): ``scale``, ``flip`` (the axis was mirrored) and
    ``offset``, so that a coordinate ``v`` of the exported file is ``offset + scale * v`` (``offset - scale * v`` flipped) in the engraved one.
    None when no move is shared by enough layers."""
    size_now, size_was = now[:, 1] - now[:, 0], was[:, 1] - was[:, 0]
    keep = (size_now >= MIN_SPAN_MM) & (size_was >= MIN_SPAN_MM)
    if keep.sum() < NEEDED_LAYERS:
        return None
    now, was = now[keep], was[keep]
    ratio = (now[:, 1] - now[:, 0]) / (was[:, 1] - was[:, 0])
    scale = float(np.median(ratio))
    best = None
    for flip in (False, True):
        offset = now[:, 0] + scale * was[:, 1] if flip else now[:, 0] - scale * was[:, 0]
        centre = float(np.median(offset))
        agree = int((np.abs(offset - centre) <= OFFSET_MM).sum())
        if best is None or agree > best["agree"]:
            best = {"scale": scale, "flip": flip, "offset": centre, "agree": agree}
    return best if best["agree"] >= NEEDED_LAYERS else None


def _there(boxes: np.ndarray, axis: int, fit: dict) -> np.ndarray:
    """The boxes as the move ``fit`` of one axis puts them (axis 0: columns 0 and 2, axis 1: columns 1 and 3)."""
    low, high = boxes[:, axis], boxes[:, axis + 2]
    out = boxes.copy()
    if fit["flip"]:
        out[:, axis], out[:, axis + 2] = fit["offset"] - fit["scale"] * high, fit["offset"] - fit["scale"] * low
    else:
        out[:, axis], out[:, axis + 2] = fit["offset"] + fit["scale"] * low, fit["offset"] + fit["scale"] * high
    return out


def compare(engraved: lb.Project, exported: lb.Project) -> dict:
    """What the engraved file did to the layers of the exported one: ``verdict`` is ``unknown`` (too little to compare), ``unmoved`` (nothing
    moved) or ``moved``; ``moved`` carries the ``scale`` and ``offset_mm`` of the rest of the file, ``left`` the indexes of the layers left
    behind, ``followed`` those that moved with it."""
    theirs = {layer.index: layer for layer in exported.layers if layer.regions}
    common = []
    for layer in engraved.layers:
        other = theirs.get(layer.index)
        if layer.regions and other is not None and abs(len(layer.regions) - len(other.regions)) <= max(1, SAME_COUNT * len(other.regions)):
            common.append((layer, other))
    if len(common) < NEEDED_LAYERS:
        return {"verdict": "unknown", "left": [], "followed": []}
    now = np.array([_span(_boxes(layer)) for layer, _ in common])
    was = np.array([_span(_boxes(other)) for _, other in common])
    fits = [_fit_axis(now[:, [axis, axis + 2]], was[:, [axis, axis + 2]]) for axis in (0, 1)]
    if None in fits:
        return {"verdict": "unknown", "left": [], "followed": []}
    if all(not f["flip"] and abs(f["scale"] - 1) < 0.001 and abs(f["offset"]) <= SAME_MM for f in fits):
        return {"verdict": "unmoved", "left": [], "followed": []}
    moved, stayed = [], []
    for layer, other in common:
        mine, before = _boxes(layer), _boxes(other)
        there = _there(_there(before, 0, fits[0]), 1, fits[1])
        if _share(mine, there) >= MATCH_SHARE:
            moved.append(layer.index)
        elif _share(mine, before) >= MATCH_SHARE:
            stayed.append(layer.index)
    if len(moved) < NEEDED_LAYERS or len(moved) < len(common) / 2:        # no move the rest of the file agrees on: say nothing
        return {"verdict": "unknown", "left": [], "followed": moved}
    return {"verdict": "moved", "left": stayed, "followed": moved, "scale": [f["scale"] for f in fits], "offset_mm": [f["offset"] for f in fits],
            "flipped": [f["flip"] for f in fits]}
