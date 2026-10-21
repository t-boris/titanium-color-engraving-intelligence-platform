"""Where the predicted look of a photo engraving gets its curve (REQ-030, DEC-057, DEC-062): every colour measured at one mode,
with where it was measured. ``prediction.py`` stays pure; this module reads the store and the uploaded LightBurn file.

A mode is the laser and lens records (DEC-063 partition), the titanium stock record and the settings that do not vary with the
grey level: speed, frequency, pulse width, line interval, passes and LightBurn's global passes. Two sources measure colour
against power at a mode:

* the tonal profile of an accepted grayscale photo engraving whose image layer has that mode: each grey bin is the colour
  photographed where the picture had that grey, at the power that grey was engraved with (DEC-057, after the file's picture
  adjustments, applied as the prediction applies them, so that a picture rendered at its own mode meets its own bins);
* the flat fills (``Scan`` layers) of accepted checks with exactly those settings: one colour at the layer's power.

Only accepted checks count: provisional checks (DEC-045) and deleted pairs never take part, nor do service layers (labels, the
cleaning witness) or tonal profiles whose relation to the grey is weak.

A dot mode (REQ-054) has no power to vary: every dot is fired at the layer's power, so that power and the dot width belong to the
mode, and the one source is the tonal profile of an accepted check in that mode, whose bins give the colour at a grey level; the curve
runs over the darkness of the grey. A profile of a picture lying over vector fills is not used: its colour is the fill mixed with the
dots (DEC-095).

A chart-corrected colour is referenced. A camera-relative colour is expressed against the clean titanium of its own photograph
where that exists (DEC-056) and is used as photographed otherwise. One curve is built from one kind only: referenced points are
preferred (``prediction.curve``); among camera-relative ones, those expressed against clean titanium are preferred to colours as
photographed, which are counted and left out, since colours of different photographs are comparable only through that reference.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Mapping

import cv2
import numpy as np

from . import colormap, experiments, ingest, lightburn as lb, photo_modes, prediction, tasks
from .db import Store
from .prediction import PredictionError

SETTINGS = ("speed", "frequency", "pulse_width", "line_interval", "passes")
OVERRIDES = ("min_power", "max_power") + SETTINGS
PREVIEW_SIDE = 800           # px: the long side of the picture as it is rendered and shown
CHART, CLEAN, AS_SHOT = "chart", "clean titanium", "as photographed"


@dataclass(frozen=True)
class Mode:
    """The settings a curve belongs to; the power is what varies along it."""
    device_id: int
    lens_id: int | None
    material_id: int | None
    speed: float | None
    frequency: float | None          # kHz
    pulse_width: float | None        # ns
    line_interval: float | None      # mm
    passes: int | None
    global_passes: int | None = 1
    dither: str = prediction.PREDICTED_MODE      # the image mode: a curve belongs to one
    power: float | None = None                   # a dot mode fires every dot at the layer's power, so it is part of the mode (grayscale: None)
    dot_width: float | None = None               # mm, when the layer corrects the dot width (dot modes only)

    def matches(self, settings: Mapping) -> bool:
        """Do these settings (``speed``, ``frequency`` in kHz, ...) engrave at this mode? A missing value equals only a missing one."""
        same = all(_same(getattr(self, k), settings.get(k)) for k in SETTINGS) and _same(self.global_passes or 1, settings.get("global_passes") or 1)
        if self.dither == prediction.PREDICTED_MODE:
            return same
        return same and _same(self.power, settings.get("power")) and _same(self.dot_width, settings.get("dot_width"))

    def as_dict(self) -> dict:
        return asdict(self)


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-9)
    except (TypeError, ValueError):
        return False


def _number(value) -> float | None:
    try:
        number = float(value.get("Value") if isinstance(value, dict) else value)
    except (TypeError, ValueError, AttributeError):
        return None
    return number if math.isfinite(number) else None


def layer_settings(layer: lb.Layer, overrides: Mapping | None = None) -> dict:
    """Min and Max power and the mode settings of an image layer as the file states them, with the operator's overrides."""
    summary = layer.image_summary() or {}
    settings = {"min_power": _number(layer.source_settings.get("minPower")), "max_power": _number(layer.source_settings.get("maxPower")),
                "speed": layer.speed, "frequency": layer.frequency_khz, "pulse_width": layer.pulse_width,
                "line_interval": layer.line_interval, "passes": layer.passes, "global_passes": layer.global_passes,
                "dot_width": summary.get("dot_width_mm") if summary.get("dot_correction") else None}
    given = {k: v for k, v in (overrides or {}).items() if k in OVERRIDES and v is not None}
    if "passes" in given:
        given["passes"] = int(given["passes"])
    return {**settings, **given, "overridden": sorted(given)}


def mode_of(settings: Mapping, device_id: int, lens_id: int | None, material_id: int | None, dither: str = prediction.PREDICTED_MODE) -> Mode:
    dots = dither != prediction.PREDICTED_MODE
    return Mode(device_id, lens_id, material_id, *(settings.get(k) for k in SETTINGS), settings.get("global_passes") or 1, dither,
                settings.get("max_power") if dots else None, settings.get("dot_width") if dots else None)


# -- the measured points of a mode ------------------------------------------------------------------------------------------------
def _expressed(lab, kind: str, clean, nominal) -> tuple[list[float], str]:
    if kind == "calibrated":
        return [float(v) for v in lab], CHART
    if clean is not None:
        return colormap.expressed(lab, kind, clean, nominal)[0], CLEAN
    return [float(v) for v in lab], AS_SHOT


def _where(pair: Mapping, kept: set[int]) -> dict:
    """Where a point was measured: the plate of a kept experiment, else the pair (a finished work)."""
    plan_id = pair["plan_id"] if pair["plan_id"] in kept else None
    return {"kind": "plate" if plan_id else "pair", "id": plan_id or pair["id"], "pair_id": pair["id"],
            "experiment": experiments.plan_key(plan_id) if plan_id else experiments.engraving_key(pair["engraving_id"]),
            "engraving_id": pair["engraving_id"], "title": pair["engraving_title"] or pair["lightburn_name"].rsplit(".", 1)[0],
            "photo": pair["photo_name"], "date": pair["accepted_at"]}


def collect(store: Store, mode: Mode) -> dict:
    """Every colour measured at ``mode`` as curve points, and what was left aside: tonal profiles too weak to use."""
    refs = colormap.references(store)
    witness, derived, nominal = refs["witness"], refs["derived"], refs["nominal"]
    kept = experiments.kept_plan_ids(store)
    pairs = {r["id"]: r for r in store.query(
        "SELECT id, plan_id, engraving_id, engraving_title, lightburn_name, photo_name, accepted_at, data_json FROM pair "
        "WHERE status='Accepted' AND device_id=? AND lens_id IS ? AND material_id IS ? ORDER BY id",
        (mode.device_id, mode.lens_id, mode.material_id))}
    points, weak, over_fills = [], 0, 0
    for row in refs["rows"]:                                 # flat fills: one colour at a power, the points of a power curve only
        if row["pair_id"] not in pairs or mode.dither != prediction.PREDICTED_MODE:
            continue
        evidence = json.loads(row["evidence_json"] or "{}")
        params = json.loads(row["parameters_json"] or "{}")
        if colormap.is_service(evidence.get("role"), row["layer_index"], derived.get(row["pair_id"])) or params.get("layer_type") != "Scan":
            continue
        if tasks.of_observation(row)["kind"] not in tasks.AREA_TASKS:     # a filled text is not a flat fill (REQ-020)
            continue
        if params.get("power") is None or not mode.matches(params):
            continue
        kind = colormap._kind(evidence, row["model_eligible"])
        clean = witness.get(row["pair_id"])
        lab, reference = _expressed(json.loads(row["lab_json"]), kind, clean["lab"] if clean else None, nominal)
        source = {**_where(pairs[row["pair_id"]], kept), "layer": row["layer_index"], "layer_name": evidence.get("layer_name"),
                  "how": "flat fill", "reference": reference, "observation_id": row["id"]}
        points.append(prediction.Point(params["power"], lab, source, kind == "calibrated"))
    for pair_id, pair in pairs.items():                      # tonal profiles of photo engravings
        check = json.loads(pair["data_json"] or "{}").get("check") or {}
        kind = "calibrated" if (check.get("color_measurement") or {}).get("mode") == "reference_chart_corrected" else "relative"
        clean = witness.get(pair_id)
        for rep in check.get("layers", []):
            tonal, image = rep.get("tonal"), rep.get("image") or {}
            seen = photo_modes.mode(image.get("dither"))
            if not tonal or seen is None or seen.key != mode.dither:
                continue
            if mode.dither == prediction.PREDICTED_MODE and not tonal.get("power_range"):
                continue
            if not mode.matches({"speed": rep.get("speed"), "frequency": rep.get("frequency_khz"), "pulse_width": rep.get("pulse_width"),
                                 "line_interval": rep.get("line_interval"), "passes": rep.get("passes"), "global_passes": rep.get("global_passes"),
                                 "power": rep.get("power"), "dot_width": image.get("dot_width_mm") if image.get("dot_correction") else None}):
                continue
            if tonal.get("evidence") != "clear":
                weak += 1
                continue
            if mode.dither != prediction.PREDICTED_MODE and (check.get("composition") or {}).get("picture_over_fills"):
                over_fills += 1                              # the colour there is the fill mixed with the dots (DEC-095)
                continue
            values = prediction.adjustments_of(tonal.get("adjustments"))["values"]
            for step in tonal["bins"]:
                grey = prediction.adjust_grey(step["gray"], values["Gamma"], values["Contrast"], values["Brightness"])
                power = float(prediction.grey_to_power(grey, *tonal["power_range"])) if mode.dither == prediction.PREDICTED_MODE else float(100.0 * (1.0 - grey))
                lab, reference = _expressed([step["L"], step["a"], step["b"]], kind, clean["lab"] if clean else None, nominal)
                source = {**_where(pair, kept), "layer": rep["index"], "layer_name": rep.get("name"), "how": "tonal profile",
                          "gray": step["gray"], "pixels": step.get("n"), "reference": reference}
                points.append(prediction.Point(power, lab, source, kind == "calibrated"))
    return {"points": points, "weak_profiles": weak, "over_fills": over_fills}


def curve_for(store: Store, mode: Mode) -> tuple[prediction.Curve, dict]:
    """The curve of ``mode`` and what it rests on: the kind of reference of its colours and notes on what was left out."""
    found = collect(store, mode)
    points = found["points"]
    as_shot_left_out = 0
    if points and not any(p.referenced for p in points):
        anchored = [p for p in points if p.source["reference"] == CLEAN]
        if anchored:
            as_shot_left_out, points = len(points) - len(anchored), anchored
    curve = prediction.curve(points, axis=prediction.POWER_AXIS if mode.dither == prediction.PREDICTED_MODE else prediction.TONE_AXIS)
    # (raises PredictionError when nothing was measured at the mode)
    references = {source["reference"] for row in curve.points for source in row["sources"]}
    reference = CHART if curve.referenced else CLEAN if references == {CLEAN} else AS_SHOT
    notes = []
    if reference == CLEAN:
        notes.append("Camera-relative colours are expressed against the clean titanium of their own photograph: comparable between "
                     "photographs, but their shade is approximate.")
    elif reference == AS_SHOT:
        notes.append("No photograph of this mode shows clean titanium: the colours are as photographed, at that photograph's exposure.")
    if as_shot_left_out:
        notes.append(f"{as_shot_left_out} camera-relative points without clean titanium in their photograph are left out: they are not "
                     "mixed with colours expressed against clean titanium.")
    if found["weak_profiles"]:
        notes.append(f"{found['weak_profiles']} tonal profiles of this mode relate their colour to the grey only weakly and are not used.")
    if found["over_fills"]:
        notes.append(f"{found['over_fills']} tonal profiles of this mode were photographed over vector fills and are not used: their colour is "
                     "the fill mixed with the dots.")
    return curve, {"reference": reference, "notes": notes}


# -- an uploaded LightBurn file ---------------------------------------------------------------------------------------------------
def image_layers(data: bytes) -> list[lb.Layer]:
    """The image layers of an uploaded LightBurn file; a file that is not one or has none is refused with the reason."""
    try:
        project = lb.parse_bytes(data)
    except lb.LightBurnError as exc:
        raise PredictionError(f"LightBurn file: {exc}") from None
    layers = [layer for layer in project.layers if layer.layer_type == "Image"]
    if not layers:
        raise PredictionError("the file has no image layer: there is no picture to predict")
    return layers


def _upright(grey: np.ndarray, matrix) -> tuple[np.ndarray, bool]:
    """The picture the way LightBurn shows it, and whether that could be done. LightBurn's y axis points up and row 0 of the
    stored picture lies at the bottom of its object (the reading the tonal profile and the registration take, DEC-052); the
    object's transform may also mirror it or turn it by quarter turns. Any other turn is not undone (False)."""
    a, b, c, d = (float(v) for v in matrix[:4])
    to_screen = np.array([[a, c], [-b, -d]])                    # picture columns and rows -> screen right and down
    q = np.round(to_screen / max(np.abs(to_screen).max(), 1e-12))
    if q[0, 1] == q[1, 0] == 0 and abs(q[0, 0]) == abs(q[1, 1]) == 1:
        return grey[::int(q[1, 1]), ::int(q[0, 0])], True
    if q[0, 0] == q[1, 1] == 0 and abs(q[0, 1]) == abs(q[1, 0]) == 1:
        return grey.T[::int(q[1, 0]), ::int(q[0, 1])], True
    return grey[::-1], False


def _picture(layer: lb.Layer) -> dict:
    """The layer's largest picture as grey 0..1 and opacity 0..1, upright, at most PREVIEW_SIDE px on its long side for rendering; the
    grey levels of the whole picture's opaque pixels with their counts (the share outside the span is the whole picture's); how many
    pictures the layer has and whether the picture is turned by an angle the preview does not undo."""
    regions = [r for r in layer.regions if r.bitmap and r.bitmap.get("png")]
    region = max(regions, key=lambda r: r.width * r.height, default=None)
    found = photo_modes.decode_picture(region.bitmap["png"]) if region else None
    if found is None:
        raise PredictionError("the layer has no picture: there is nothing to predict")
    grey, upright = _upright(np.clip(found[0].astype(np.float32), 0.0, 1.0), region.bitmap["matrix"])
    alpha, _ = _upright(found[1], region.bitmap["matrix"])
    opaque = alpha >= photo_modes.ALPHA_MIN
    if not opaque.any():
        raise PredictionError("the picture is fully transparent: the layer engraves nothing, so there is nothing to predict")
    levels, counts = np.unique(grey[opaque], return_counts=True)
    rows, cols = grey.shape
    scale = PREVIEW_SIDE / max(rows, cols)
    size = (max(1, round(cols * scale)), max(1, round(rows * scale)))
    shown, shown_alpha = (grey, alpha) if scale >= 1 else (cv2.resize(grey, size, interpolation=cv2.INTER_AREA), cv2.resize(alpha, size, interpolation=cv2.INTER_AREA))
    return {"picture": np.ascontiguousarray(np.clip(shown, 0.0, 1.0)), "alpha": np.ascontiguousarray(np.clip(shown_alpha, 0.0, 1.0)),
            "levels": levels, "counts": counts, "size": [cols, rows], "pictures": len({r.bitmap["png"] for r in regions}), "turned": not upright}


def check_power_range(min_power, max_power) -> tuple[float, float]:
    low, high = _number(min_power), _number(max_power)
    if low is None or high is None:
        raise PredictionError(f"Min and Max power must be numbers, got {min_power!r} and {max_power!r}")
    if not 0 <= low <= high <= 100:
        raise PredictionError(f"Min power {low:g} % and Max power {high:g} % must lie within 0..100 % with Min not above Max")
    return low, high


def prepare(store: Store, data: bytes, device_id: int, lens_id: int | None, material_id: int | None,
            overrides: Mapping | None = None) -> list[dict]:
    """Per image layer of the file: what rendering it needs (the picture at preview resolution, the curve of its mode, its
    adjustments and Min and Max power) or why it is refused. The same ``overrides`` apply to every image layer."""
    out = []
    for layer in image_layers(data):
        summary = layer.image_summary() or {}
        settings = layer_settings(layer, overrides)
        item = {"index": layer.index, "name": layer.name, "dither": summary.get("dither"), "settings": settings, "refused": None}
        try:
            prediction.refuse_mode(summary.get("dither"))
            dither = photo_modes.mode(summary.get("dither")).key
            picture = _picture(layer)
            if dither == prediction.PREDICTED_MODE:
                settings["min_power"], settings["max_power"] = check_power_range(settings["min_power"], settings["max_power"])
            elif settings["max_power"] is None:
                raise PredictionError("a dot mode fires every dot at the layer's power and the layer states none: there is nothing to predict from")
            mode = mode_of(settings, device_id, lens_id, material_id, dither)
            curve, basis = curve_for(store, mode)
        except PredictionError as exc:
            item["refused"] = str(exc)
            out.append(item)
            continue
        notes = list(basis["notes"])
        if picture["pictures"] > 1:
            notes.append(f"The layer holds {picture['pictures']} pictures; the largest one is shown.")
        if picture["turned"]:
            notes.append("The picture is turned by an angle in the file; the preview shows it without that turn.")
        item.update(picture, mode=mode, curve=curve, reference=basis["reference"], adjustments=summary.get("adjusted") or {}, basis_notes=notes)
        out.append(item)
    return out


def _grey_for(x: float, curve: prediction.Curve, low, high, values: Mapping) -> float | None:
    """The grey level of the stored picture that lands at ``x`` on the curve (a power at Min..Max, or a darkness for a curve over tones,
    after the assumed adjustments); None when ``x`` lies outside what the picture can reach."""
    grey = np.linspace(0.0, 1.0, 1001)
    xs = prediction.x_of(grey, curve, values, low, high)
    if not xs.min() - prediction.SPAN_TOLERANCE <= x <= xs.max() + prediction.SPAN_TOLERANCE:
        return None
    order = np.argsort(xs, kind="stable")
    return round(float(np.interp(x, xs[order], grey[order])), 3)


def describe(item: dict, min_power=None, max_power=None) -> tuple[dict, np.ndarray]:
    """The prediction of one prepared layer at Min..Max power (the layer's own when not given): the description shown beside the
    preview, and the side-by-side image (picture | prediction, hatched where no power was measured)."""
    if item["curve"].axis == prediction.TONE_AXIS:           # a dot mode: the layer's power is part of its mode, there is no Min..Max to move
        low = high = None
    else:
        low, high = check_power_range(item["settings"]["min_power"] if min_power is None else min_power,
                                      item["settings"]["max_power"] if max_power is None else max_power)
    outside = prediction.share_outside(item["levels"], item["counts"], low, high, item["curve"], item["adjustments"])
    spread = prediction.share_by_spread(item["levels"], item["counts"], low, high, item["curve"], item["adjustments"])
    rendered = prediction.render(item["picture"], low, high, item["curve"], item["adjustments"], outside_share=outside, spread_shares=spread,
                                 alpha=item["alpha"])
    values = rendered["adjustments"]["values"]
    curve = item["curve"].as_dict()
    curve["points"] = [{**row, "grey": _grey_for(row["power"], item["curve"], low, high, values)} for row in curve["points"]]
    rows, cols = item["picture"].shape
    info = {"index": item["index"], "name": item["name"], "dither": item["dither"], "settings": item["settings"], "refused": None,
            "mode": item["mode"].as_dict(), "curve": curve, "referenced": rendered["referenced"], "reference": item["reference"],
            "span": rendered["span"], "axis": rendered["axis"], "power_range": rendered["power_range"], "outside_share": rendered["outside_share"], "spread": rendered["spread"],
            "transparent_share": rendered["transparent_share"],
            "adjustments": rendered["adjustments"], "notes": rendered["notes"] + item["basis_notes"],
            "picture": {"width": item["size"][0], "height": item["size"][1], "shown_width": cols, "shown_height": rows}}
    return info, prediction.side_by_side(item["picture"], rendered["rgb8"])
