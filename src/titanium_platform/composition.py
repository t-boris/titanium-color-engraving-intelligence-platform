"""What a LightBurn file is made of: fills, photo engraving, or both (REQ-053, DEC-095).

A work may be a mix: a cleaning rectangle, colour fills (``Scan`` layers) and one image layer burned last whose picture has holes
where the fills are. This module rasterises the file on a grid of millimetres, in burn order, and says per layer how much of it shows in
the end, and over the marked area how much is fill only, photo only, or both. It needs no photograph: it is the design, and the
check lays the photograph over it. Pure functions of the parsed file.
"""
from __future__ import annotations

import math

import numpy as np

from . import photo as ph
from . import photo_modes

PX_PER_MM = 2.0          # grid resolution; shrunk for a very large file so that the grid keeps under MAX_SIDE pixels
MAX_SIDE = 3000
BOTH_MIN = 5.0           # percent of the marked area lying under both fill and picture from which the picture is "over the fills"
FILLING = ("Scan", "Image")


def _percent(part: float, whole: float) -> float | None:
    return None if whole <= 0 else float(round(100.0 * float(part) / whole, 1))


def _bounds(layers) -> tuple[float, float, float, float] | None:
    boxes = [(r.x, r.y, r.x + r.width, r.y + r.height) for layer in layers for r in layer.regions if len(r.polygon) >= 3]
    if not boxes:
        return None
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def cleaning_layer(layers) -> int | None:
    """The layer that cleans the plate before the engraving: run first, one filled rectangle that encloses everything else. It is not a
    colour of the work (DEC-056); its colour is the cleaned titanium."""
    layers = [layer for layer in layers if layer.regions]
    if len(layers) < 2:
        return None
    first = min(layers, key=lambda layer: layer.burn_order)
    if first.layer_type != "Scan" or len(first.regions) != 1 or first.regions[0].kind != "rect" or not first.regions[0].closed:
        return None
    frame = first.regions[0]
    others = [r for layer in layers if layer is not first for r in layer.regions]
    x0, y0 = min(r.x for r in others), min(r.y for r in others)
    x1, y1 = max(r.x + r.width for r in others), max(r.y + r.height for r in others)
    inside = frame.x <= x0 + 0.05 and frame.y <= y0 + 0.05 and frame.x + frame.width >= x1 - 0.05 and frame.y + frame.height >= y1 - 0.05
    return first.index if inside else None


def _fill_mask(layer, image_to_mm: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    regions = [r for r in layer.regions if len(r.polygon) >= 3 and r.closed]
    if not regions:
        return np.zeros(shape, bool)
    return ph.layer_mask([r.polygon for r in regions], image_to_mm, shape, edge_fraction=0, holes_mm=[r.holes for r in regions])


def compose(layers, flips: dict | None = None) -> dict | None:
    """The composition of a file: its layers in burn order with what each marks and how much of it shows, and the shares of the marked
    area that are fill only, photo only or both. ``flips`` gives, per image layer index, the edge of its picture that is up as the
    photograph said (default: as the file stores it). None when the file marks nothing."""
    layers = [layer for layer in layers if layer.regions]
    marking = [layer for layer in layers if layer.layer_type in FILLING]
    bounds = _bounds(marking)
    if bounds is None:
        return None
    x0, y0, x1, y1 = bounds[0] - 1.0, bounds[1] - 1.0, bounds[2] + 1.0, bounds[3] + 1.0
    px = min(PX_PER_MM, MAX_SIDE / max(x1 - x0, y1 - y0, 1e-6))
    shape = (max(1, math.ceil((y1 - y0) * px)), max(1, math.ceil((x1 - x0) * px)))
    image_to_mm = np.array([[1 / px, 0, x0], [0, 1 / px, y0], [0, 0, 1.0]])
    pixel_mm2 = 1.0 / (px * px)

    ordered = sorted(marking, key=lambda layer: layer.burn_order)
    cleaning = cleaning_layer(layers)
    own: dict[int, np.ndarray] = {}
    detail: dict[int, dict] = {}
    for layer in ordered:
        if layer.layer_type == "Image":
            mask, cover = photo_modes.struck_mask(layer, image_to_mm, shape, bool((flips or {}).get(layer.index)), with_coverage=True)
            frame = sum(abs(_polygon_area(r.polygon)) for r in layer.regions if r.bitmap and r.bitmap.get("png"))
            opaque = [float(np.mean(found[1] >= photo_modes.ALPHA_MIN)) for r in layer.regions
                      if r.bitmap and r.bitmap.get("png") and (found := photo_modes.decode_picture(r.bitmap["png"])) is not None]
            summary = layer.image_summary() or {}
            known = photo_modes.mode(summary.get("dither"))
            detail[layer.index] = {
                "mode": summary.get("dither"), "family": None if known is None else known.family,
                "picture_mm2": round(frame, 1), "opaque_percent": None if not opaque else round(100.0 * float(np.mean(opaque)), 1),
                "struck_percent": _percent(float(mask.sum()) * pixel_mm2, frame),
                "dot_density_percent": round(100.0 * float(cover[mask].mean()), 1) if mask.any() and known is not None and known.binary else None,
                "ignored_shapes": sum(1 for r in layer.regions if not (r.bitmap and r.bitmap.get("png")))}
            own[layer.index] = mask
        else:
            own[layer.index] = _fill_mask(layer, image_to_mm, shape)
            detail[layer.index] = {}

    entries = []
    for k, layer in enumerate(ordered):
        mask = own[layer.index]
        above = np.zeros(shape, bool)
        for later in ordered[k + 1:]:
            if not later.output_off:
                above |= own[later.index]
        area = float(mask.sum() * pixel_mm2)
        shown = float((mask & ~above).sum() * pixel_mm2) if not layer.output_off else 0.0
        depth = layer.layer_type == "Image" and detail[layer.index].get("family") == photo_modes.DEPTH
        entries.append({"index": layer.index, "name": layer.name, "type": layer.layer_type,
                        "kind": "cleaning" if layer.index == cleaning else "photo" if layer.layer_type == "Image" and not depth
                        else "depth" if depth else "fill",
                        "engraves": not layer.output_off, "hidden": layer.hidden, "area_mm2": round(area, 1),
                        "visible_percent": _percent(shown, area) if not layer.output_off else 0.0, **detail[layer.index]})

    fills = np.zeros(shape, bool)
    photos = np.zeros(shape, bool)
    for layer in ordered:
        if layer.output_off or layer.index == cleaning:
            continue
        if layer.layer_type == "Image":
            photos |= own[layer.index]
        else:
            fills |= own[layer.index]
    marked = float((fills | photos).sum() * pixel_mm2)           # the cleaned rectangle is not a colour: it does not count as marked
    both = float((fills & photos).sum() * pixel_mm2)
    share = {"fill_only": _percent(float((fills & ~photos).sum() * pixel_mm2), marked),
             "photo_only": _percent(float((photos & ~fills).sum() * pixel_mm2), marked), "both": _percent(both, marked)}
    mixed = bool(fills.any() and photos.any())
    lines = [{"index": layer.index, "name": layer.name, "type": layer.layer_type, "kind": "line", "engraves": not layer.output_off,
              "hidden": layer.hidden, "shapes": len(layer.regions)} for layer in layers if layer.layer_type not in FILLING]
    return {"px_per_mm": round(px, 3), "marked_mm2": round(marked, 1), "cleaning_layer": cleaning, "layers": entries, "lines": lines,
            "share": share, "mixed": mixed,
            "picture_over_fills": bool(mixed and (share["both"] or 0.0) >= BOTH_MIN),
            "assumptions": ["only the pictures of an image layer are engraved: a plain shape on it strikes nothing (DEC-095)"]}


def _polygon_area(points) -> float:
    xs, ys = np.asarray([p[0] for p in points], float), np.asarray([p[1] for p in points], float)
    return 0.5 * float(np.dot(xs, np.roll(ys, -1)) - np.dot(ys, np.roll(xs, -1)))
