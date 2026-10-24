"""Where the predicted look of a photo engraving gets its curve (REQ-030, DEC-057, DEC-062): every colour measured at one mode,
with where it was measured. ``prediction.py`` stays pure; this module reads the store and the uploaded LightBurn file.

A mode is the laser and lens records (DEC-063 partition), the titanium stock record and the settings that do not vary with the
grey level: speed, frequency, pulse width, line interval, passes and LightBurn's global passes. Two sources measure colour
against power at a mode:

* the tonal profile of an accepted grayscale photo engraving whose image layer has that mode: each grey bin is the colour
  photographed where the picture had that grey, at the power that grey was engraved with (DEC-057, after the file's picture
  adjustments, applied as the prediction applies them, so that a picture rendered at its own mode meets its own bins);
* the grey ramps of a "grey scales" plate (REQ-059): each step measured where the plate put it, at the power of its grey.

The flat fills (``Scan`` layers) of accepted checks with exactly those settings are collected too, but only as a reference beside
the curve (``fills``), never in it (DEC-100): on the operator's plate a fill and a grayscale picture engraved with the same settings
and power differ by up to 36 dE in the light and middle tones (the Power x Speed row at 150 mm/s against Motorcycle and Girl on a
bike), so a fill does not say what a grey level of a picture comes out as.

Only accepted checks count: provisional checks (DEC-045) and deleted pairs never take part, nor do service layers (labels, the
cleaning witness) or tonal profiles whose relation to the grey is weak.

A dot mode (REQ-054) has no power to vary: every dot is fired at the layer's power, so that power and the dot width belong to the
mode, and the one source is the tonal profile of an accepted check in that mode, whose bins give the colour at a grey level; the curve
runs over the darkness of the grey. A profile of a picture lying over vector fills is not used: its colour is the fill mixed with the
dots (DEC-095).

Every point and fill keeps the row length it was measured at (``source["row_mm"]``, DEC-107): the length the laser marks along a scan
row through it, derived from the pair's stored LightBurn file (``row_length``; nothing is written to the database), so that a curve is
made for the size of what it predicts (``curve_for(..., row_mm)``, ``prediction.curve_at``).

A chart-corrected colour is referenced. A camera-relative colour is expressed against the clean titanium of its own photograph
where that exists (DEC-056) and is used as photographed otherwise. One curve is built from one kind only: referenced points are
preferred (``prediction.curve``); among camera-relative ones, those expressed against clean titanium are preferred to colours as
photographed, which are counted and left out, since colours of different photographs are comparable only through that reference.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from typing import Mapping

import cv2
import numpy as np

from . import (color, colormap, colouring, devices, dots, drawing, engraving_time, experiments, grayscale, ingest, lightburn as lb, people, photo_modes, picture_rules,
               plans as pl, prediction, row_length, setup as su, tasks)
from .db import Store
from .prediction import PredictionError

SETTINGS = ("speed", "frequency", "pulse_width", "line_interval", "passes")
OVERRIDES = ("min_power", "max_power") + SETTINGS
PREVIEW_SIDE = 800           # px: the long side of the picture as it is rendered and shown
COLLECTED = 64               # modes whose measurements are kept in memory while the data is unchanged (``collect``)
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
    """Where a point was measured: the plate of a kept experiment, else the pair (a finished work), and the titanium stock record."""
    plan_id = pair["plan_id"] if pair["plan_id"] in kept else None
    return {"kind": "plate" if plan_id else "pair", "id": plan_id or pair["id"], "pair_id": pair["id"], "material_id": pair["material_id"],
            "experiment": experiments.plan_key(plan_id) if plan_id else experiments.engraving_key(pair["engraving_id"]),
            "engraving_id": pair["engraving_id"], "title": pair["engraving_title"] or pair["lightburn_name"].rsplit(".", 1)[0],
            "photo": pair["photo_name"], "date": pair["accepted_at"]}


def _on_titanium(store: Store, material_id: int | None) -> tuple[str, tuple]:
    """The SQL condition and its arguments that pick the pairs engraved on the titanium of ``material_id``: every plate of it
    (``setup.same_titanium``, DEC-110); no titanium only none."""
    if material_id is None:
        return "material_id IS NULL", ()
    plates = su.same_titanium(store, material_id)
    return f"material_id IN ({','.join('?' * len(plates))})", tuple(plates)


def collect(store: Store, mode: Mode) -> dict:
    """Every colour measured at ``mode`` in its image mode, on any plate of its titanium (DEC-110), as curve points; the flat fills with
    the same settings beside them (``fills``, a power curve only, DEC-100); and what was left aside: tonal profiles too weak to use.
    Read once per state of the data (``Store.stamp``): a photo zone, its tiles of every kind and the list of scales ask for the same
    modes many times (REQ-073). Each caller gets lists of its own; the points themselves are frozen."""
    found = _collected(store, mode, store.stamp())
    return {**found, "points": list(found["points"]), "fills": list(found["fills"])}


@lru_cache(maxsize=COLLECTED)
def _collected(store: Store, mode: Mode, stamp: tuple[int, int]) -> dict:
    refs = colormap.references(store)
    witness, derived, nominal = refs["witness"], refs["derived"], refs["nominal"]
    kept = experiments.kept_plan_ids(store)
    titanium, plates = _on_titanium(store, mode.material_id)
    pairs = {r["id"]: r for r in store.query(
        "SELECT id, plan_id, engraving_id, engraving_title, lightburn_name, lightburn_path, photo_name, accepted_at, material_id, data_json FROM pair "
        f"WHERE status='Accepted' AND device_id=? AND lens_id IS ? AND {titanium} ORDER BY id", (mode.device_id, mode.lens_id, *plates))}
    points, fills, weak, over_fills = [], [], 0, 0
    for row in refs["rows"]:                                 # flat fills: one colour at a power, a reference for a power curve only
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
                  "how": "flat fill", "reference": reference, "observation_id": row["id"],
                  "row_mm": row_length.of_file(pairs[row["pair_id"]]["lightburn_path"]).get(row["layer_index"])}
        fills.append(prediction.Point(params["power"], lab, source, kind == "calibrated"))
    for pair_id, pair in pairs.items():                      # tonal profiles of photo engravings and grey ramps
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
            row_mm = row_length.of_file(pair["lightburn_path"]).get(rep["index"])
            for step in tonal["bins"]:
                grey = prediction.adjust_grey(step["gray"], values["Gamma"], values["Contrast"], values["Brightness"])
                power = float(prediction.grey_to_power(grey, *tonal["power_range"])) if mode.dither == prediction.PREDICTED_MODE else float(100.0 * (1.0 - grey))
                lab, reference = _expressed([step["L"], step["a"], step["b"]], kind, clean["lab"] if clean else None, nominal)
                how = "grey ramp" if tonal.get("measured_by") == "grey ramp" else "tonal profile"
                source = {**_where(pair, kept), "layer": rep["index"], "layer_name": rep.get("name"), "how": how,
                          "gray": step["gray"], "pixels": step.get("n"), "reference": reference, "row_mm": row_mm}
                points.append(prediction.Point(power, lab, source, kind == "calibrated"))
    return {"points": tuple(points), "fills": tuple(fills), "weak_profiles": weak, "over_fills": over_fills}


def photographed_kinds(store: Store) -> frozenset[str]:
    """The kinds of photo engraving an accepted check measured a tonal profile of, on any laser and titanium: a kind outside it has no
    measured tones anywhere, so :func:`collect` need not look for them (REQ-073). Read once per state of the data."""
    return _photographed_kinds(store, store.stamp())


@lru_cache(maxsize=8)
def _photographed_kinds(store: Store, stamp: tuple[int, int]) -> frozenset[str]:
    kinds = set()
    for pair in store.query("SELECT data_json FROM pair WHERE status='Accepted'"):
        for rep in (json.loads(pair["data_json"] or "{}").get("check") or {}).get("layers", []):
            seen = photo_modes.mode((rep.get("image") or {}).get("dither"))
            if rep.get("tonal") and seen is not None:
                kinds.add(seen.key)
    return frozenset(kinds)


def curve_for(store: Store, mode: Mode, row_mm: float | None = None) -> tuple[prediction.Curve, dict]:
    """The curve of ``mode`` for an engraving whose rows are ``row_mm`` long (``prediction.curve_at``; without it, at the size most
    engravings measured) and what it rests on: the kind of reference of its colours, the sizes measured (``sizes``: each one's row
    length, engravings and points) and notes on what was left out and on the size."""
    found = collect(store, mode)
    points = found["points"]
    as_shot_left_out = 0
    if points and not any(p.referenced for p in points):
        anchored = [p for p in points if p.source["reference"] == CLEAN]
        if anchored:
            as_shot_left_out, points = len(points) - len(anchored), anchored
    curve = prediction.curve_at(points, row_mm, axis=prediction.POWER_AXIS if mode.dither == prediction.PREDICTED_MODE else prediction.TONE_AXIS)
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
    if found["fills"]:
        notes.append(f"{len(found['fills'])} flat fills with these settings are shown beside the curve and not used in it: a fill and a grey "
                     "level of a picture engraved at the same power need not come out the same colour.")
    notes += size_notes(curve.size)
    groups = prediction.sizes([p for p in points if p.referenced == curve.referenced])
    sizes = [{"row_mm": g["row_mm"], "engravings": g["engravings"], "points": len(g["points"])} for g in groups]
    return curve, {"reference": reference, "notes": notes, "fills": found["fills"], "sizes": sizes}


def _mm(values) -> str:
    return ", ".join(f"{v:g}" for v in values)


def size_notes(size) -> list[str]:
    """What a curve's size (``prediction.curve_at``) says beside a prediction: nothing when that size was measured."""
    if not size:
        return []
    how, row, measured, used = size["how"], size["row_mm"], size["measured_mm"], size["from_mm"]
    notes = []
    if how == prediction.BETWEEN:
        notes.append(f"Rows {row:g} mm long were not measured at this mode: the colours are interpolated between the measurements with "
                     f"rows of {used[0]:g} and {used[1]:g} mm.")
    elif how == prediction.OUTSIDE:
        notes.append(f"Rows {row:g} mm long were not measured at this mode (measured: {_mm(measured)} mm): the colours are those of {used[0]:g} mm "
                     "rows and may come out different at this size; engrave a grey ramp of this width to measure it.")
    elif how == prediction.UNKNOWN and row is not None:
        notes.append(f"The row length of these measurements is not known (their LightBurn files cannot be read): the colours may come out "
                     f"different with rows {row:g} mm long.")
    if size.get("unknown_points") and measured:
        notes.append(f"{size['unknown_points']} points whose row length is not known (their LightBurn file cannot be read) are left out.")
    return notes


# -- grayscale scales (REQ-059) ---------------------------------------------------------------------------------------------------
BAR_SAMPLES = 48


def _materials(store: Store) -> dict[int, dict]:
    return {r["id"]: dict(r) for r in store.query("SELECT id, name, family, grade, batch, thickness_mm FROM material_profile")}


def scale_modes(store: Store, device_id: int | None = None, lens_id=None, material_id=None) -> list[Mode]:
    """Every grayscale mode with a clear grey -> colour measurement in an accepted check (a photo engraving or a grey ramp), optionally
    of one laser, lens and titanium; each once per titanium (DEC-110), in the order first measured. A mode names the titanium asked for,
    else the plate it was first measured on."""
    sql = "SELECT id, device_id, lens_id, material_id, data_json FROM pair WHERE status='Accepted'"
    args: list = []
    if device_id is not None:
        sql += " AND device_id=?"
        args.append(device_id)
    if lens_id is not None:
        sql += " AND lens_id IS ?"
        args.append(lens_id)
    if material_id is not None:
        titanium, plates = _on_titanium(store, material_id)
        sql += " AND " + titanium
        args += plates
    materials = _materials(store)
    modes: list[Mode] = []
    listed: set = set()
    for pair in store.query(sql + " ORDER BY id", tuple(args)):
        check = json.loads(pair["data_json"] or "{}").get("check") or {}
        for rep in check.get("layers", []):
            tonal, image = rep.get("tonal") or {}, rep.get("image") or {}
            seen = photo_modes.mode(image.get("dither"))
            if seen is None or seen.key != prediction.PREDICTED_MODE or tonal.get("evidence") != "clear" or not tonal.get("power_range"):
                continue
            mode = mode_of({"speed": rep.get("speed"), "frequency": rep.get("frequency_khz"), "pulse_width": rep.get("pulse_width"),
                            "line_interval": rep.get("line_interval"), "passes": rep.get("passes"), "global_passes": rep.get("global_passes")},
                           pair["device_id"], pair["lens_id"], pair["material_id"] if material_id is None else material_id)
            key = (replace(mode, material_id=None), su.titanium_key(materials.get(mode.material_id)))
            if key not in listed:
                listed.add(key)
                modes.append(mode)
    return modes


def _hex(lab) -> str:
    r, g, b = (int(v) for v in np.clip(color.lab_to_srgb8(np.asarray([lab], np.float64)), 0, 255)[0])
    return f"#{r:02x}{g:02x}{b:02x}"


def _scale_summary(store: Store, mode: Mode, materials: Mapping, row_mm: float | None = None) -> dict | None:
    try:
        curve, basis = curve_for(store, mode, row_mm)
    except PredictionError:
        return None
    lo, hi = curve.span
    powers = np.linspace(lo, hi, BAR_SAMPLES) if hi > lo else np.array([lo])
    labs = curve.lab_at(powers)
    sources = [src for row in curve.points for src in row["sources"]]
    engravings = {prediction._engraving_of(src) for src in sources}
    hows = {}
    for key in engravings:
        how = next(src["how"] for src in sources if prediction._engraving_of(src) == key)
        hows[how] = hows.get(how, 0) + 1
    settings = {k: getattr(mode, k) for k in SETTINGS} | {"global_passes": mode.global_passes}
    time = engraving_time.per_area(settings)
    return {"mode": mode.as_dict(), "material": materials.get(mode.material_id), "titanium": _titanium(mode, materials, sources),
            "span": [lo, hi], "points": len(curve.points),
            "engravings": len(engravings), "by_kind": hows, "reference": basis["reference"], "referenced": curve.referenced,
            "dpi": grayscale.image_dpi(mode.line_interval) if mode.line_interval else None,
            "bar": [{"power": round(float(p), 2), "hex": _hex(lab)} for p, lab in zip(powers, labs) if np.isfinite(lab[0])],
            "confirmation": {k: v for k, v in grayscale.confirmation(_per_engraving(store, mode, curve.referenced)).items() if k != "rows"},
            "fills": len(basis["fills"]), "time_s_per_cm2": time["s_per_cm2"], "notes": basis["notes"], "size": dict(curve.size),
            "sizes": basis["sizes"]}


def _titanium(mode: Mode, materials: Mapping, sources: list[dict]) -> dict:
    """The titanium of a scale (DEC-110): its family and grade, the stock records that are it (``records``) and those its points were
    measured on (``measured_on``, by name)."""
    own = materials.get(mode.material_id)
    key = su.titanium_key(own)
    records = [i for i, m in materials.items() if su.titanium_key(m) == key] if own else []
    measured = sorted({src.get("material_id") for src in sources if src.get("material_id") is not None})
    return {"family": own["family"] if own else None, "grade": own["grade"] if own else None, "records": sorted(records),
            "measured_on": [{"id": i, "name": materials[i]["name"]} for i in measured if i in materials]}


def _per_engraving(store: Store, mode: Mode, referenced: bool) -> list[prediction.Point]:
    """The points of a mode as each engraving measured them (not averaged over engravings), of the kind its curve uses."""
    found = collect(store, mode)["points"]
    kind = [p for p in found if p.referenced == referenced]
    if not referenced and kind and any(p.source["reference"] == CLEAN for p in kind):
        kind = [p for p in kind if p.source["reference"] == CLEAN]
    return kind


def engraving_check(store: Store, mode: Mode, pair_id: int, tolerance: float = 5.0) -> dict:
    """The engraving of a photographed pair at ``mode`` against the curve of every other engraving there at its own size, as the scale's
    confirmation compares them (``grayscale.compare``): each grey it was measured at, the colour predicted there and the colour engraved.
    Its re-photographs are the same engraving: they are compared with it, never with each other (electron DEC-045).
    ``reason`` says why nothing is compared: the engraving gave no clear colours at this mode (``no_points``), its photograph has no
    colour chart while the scale's colours are chart-corrected or the other way round (``kind``), no other engraving measured this mode
    yet (``alone``), the others measured no size near or around its own (``other_size``: ``size`` names theirs), or its powers lie
    outside theirs (``outside``)."""
    found = [p for p in collect(store, mode)["points"] if p.source["pair_id"] == pair_id]
    if not found:
        return {"reason": "no_points", "compared": 0, "bands": []}
    curve, _ = curve_for(store, mode)
    points = _per_engraving(store, mode, curve.referenced)
    engraving = prediction._engraving_of(found[0].source)
    own = [p for p in points if prediction._engraving_of(p.source) == engraving]
    if not own:
        return {"reason": "kind", "compared": 0, "bands": []}
    others = [p for p in points if prediction._engraving_of(p.source) != engraving]
    out = {**grayscale.compare(own, others, tolerance), "referenced": curve.referenced, "tolerance_de": tolerance,
           "row_mm": own[0].source.get("row_mm")}
    out["others"] = (out["size"] or {}).get("engravings", 0)        # the other engravings the prediction was made from, at its size
    out["confirmed"] = out["median_de"] is not None and out["median_de"] <= tolerance
    other_size = (out["size"] or {}).get("how") == prediction.OUTSIDE
    out["reason"] = None if out["compared"] else ("alone" if not others else "other_size" if other_size else "outside")
    return out


def scales(store: Store, device_id: int | None = None, lens_id=None, material_id=None) -> list[dict]:
    """Every grayscale scale (one per mode) with its colour bar over the measured powers, how many engravings measured it and of which
    kind, whether they confirm each other, the fills of the same settings and the time per square centimetre. The best measured first:
    chart-referenced colours, then more engravings, then more points."""
    materials = _materials(store)
    out = [_scale_summary(store, mode, materials) for mode in scale_modes(store, device_id, lens_id, material_id)]
    return sorted((item for item in out if item is not None), key=lambda item: (not item["referenced"], -item["engravings"], -item["points"]))


def measured_mode(store: Store, wanted) -> Mode:
    """The measured scale named by ``wanted``: the laser, lens, titanium and fixed settings, as the list of scales gives them; on any
    plate of its titanium (DEC-110), the caller keeping the plate named."""
    if isinstance(wanted, Mapping):
        for mode in scale_modes(store, material_id=wanted.get("material_id")):
            if (mode.device_id == wanted.get("device_id") and mode.lens_id == wanted.get("lens_id")
                    and mode.material_id == wanted.get("material_id") and mode.matches(wanted)):
                return mode
    raise su.ValidationError("this scale is not measured: choose one of the measured scales")


def measured_span(store: Store, mode: Mode, width_mm: float) -> tuple[float, float]:
    """The scale's measured powers at ``width_mm`` rounded inwards to 0.1 %, so that the white and the black of a picture both stay
    inside them."""
    lo, hi = curve_for(store, mode, width_mm)[0].span
    low, high = math.ceil(lo * 10 - 1e-9) / 10, math.floor(hi * 10 + 1e-9) / 10
    return (low, high) if low <= high else (float(lo), float(hi))


def scale(store: Store, mode: Mode, min_power=None, max_power=None, row_mm=None) -> dict:
    """One scale in full at a size (rows ``row_mm`` long; by default the size most engravings measured): its curve with every source,
    "which grey makes which colour" at Min..Max (by default the measured span), each engraving against the curve of the others at its own
    size, and each fill of the same settings against the curve at its power."""
    curve, basis = curve_for(store, mode, None if row_mm is None else check_width(row_mm))
    lo, hi = curve.span
    low, high = check_power_range(lo if min_power is None else min_power, hi if max_power is None else max_power)
    summary = _scale_summary(store, mode, _materials(store), curve.size["row_mm"])
    fills = []
    for p in basis["fills"]:
        at = curve.lab_at(p.power)
        fills.append({"power": p.power, "lab": list(p.lab), "hex": _hex(p.lab), "source": p.source, "referenced": p.referenced,
                      "curve_lab": None if not np.isfinite(at[0]) else [round(float(v), 2) for v in at],
                      "de": None if not np.isfinite(at[0]) or p.referenced != curve.referenced else round(float(np.linalg.norm(np.asarray(p.lab) - at)), 1)})
    points = [{**row, "hex": _hex(row["lab"])} for row in curve.as_dict()["points"]]
    return {**summary, "curve": {**curve.as_dict(), "points": points}, "greys": grayscale.scale_of_greys(curve, low, high),
            "confirmation": grayscale.confirmation(_per_engraving(store, mode, curve.referenced)), "fill_points": fills}


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


def check_width(width_mm) -> float:
    """The width of a picture on the titanium: 1..1000 mm."""
    width = None if isinstance(width_mm, bool) else _number(width_mm)
    if width is None or not 1 <= width <= 1000:
        raise PredictionError("the width of the picture must be 1..1000 mm")
    return width


def file_parameters(mode: Mode, min_power: float, max_power: float) -> dict:
    """The settings of the grayscale Image layer that engraves a picture at ``mode`` with Min and Max power (``plans.export_picture``)."""
    return {"power": max_power, "min_power": min_power, "speed": mode.speed, "frequency": mode.frequency, "pulse_width": mode.pulse_width,
            "line_interval": mode.line_interval, "passes": mode.passes or 1, "global_passes": mode.global_passes or 1}


def prepare(store: Store, data: bytes, device_id: int, lens_id: int | None, material_id: int | None,
            overrides: Mapping | None = None) -> list[dict]:
    """Per image layer of the file: what rendering it needs (the picture at preview resolution, the curve of its mode, its
    adjustments and Min and Max power) or why it is refused. The same ``overrides`` apply to every image layer."""
    out = []
    for layer in image_layers(data):
        summary = layer.image_summary() or {}
        settings = layer_settings(layer, overrides)
        item = {"index": layer.index, "name": layer.name, "dither": summary.get("dither"), "settings": settings, "refused": None}
        mode = None
        try:
            prediction.refuse_mode(summary.get("dither"))
            dither = photo_modes.mode(summary.get("dither")).key
            picture = _picture(layer)
            if dither == prediction.PREDICTED_MODE:
                settings["min_power"], settings["max_power"] = check_power_range(settings["min_power"], settings["max_power"])
            elif settings["max_power"] is None:
                raise PredictionError("a dot mode fires every dot at the layer's power and the layer states none: there is nothing to predict from")
            mode = mode_of(settings, device_id, lens_id, material_id, dither)
            curve, basis = curve_for(store, mode, row_length.of_layer(layer))
        except PredictionError as exc:
            item["refused"] = str(exc)
            item["measured_on"] = measured_on(store, mode) if mode is not None else None
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


def measured_on(store: Store, mode: Mode) -> list[dict] | None:
    """The lasers, lenses and titanium on which the settings of ``mode`` are measured as a grayscale scale (``scale_modes``, one plate
    per titanium): where a file refused for another laser, lens or titanium can be predicted. None for a dot mode: those are not searched."""
    if mode.dither != prediction.PREDICTED_MODE:
        return None
    settings = {**{k: getattr(mode, k) for k in SETTINGS}, "global_passes": mode.global_passes}
    return [{"device_id": m.device_id, "lens_id": m.lens_id, "material_id": m.material_id} for m in scale_modes(store) if m.matches(settings)]


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
    info, rgb8 = predicted(item, min_power, max_power)
    return info, prediction.side_by_side(item["picture"], rgb8)


def predicted(item: dict, min_power=None, max_power=None) -> tuple[dict, np.ndarray]:
    """What :func:`describe` says, with the predicted look alone (RGB uint8, at preview size), as the list of photo works shows it."""
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
    return info, rendered["rgb8"]


# -- a picture engraved on a scale (REQ-059) --------------------------------------------------------------------------------------
MAX_PICTURE_PIXELS = 60_000_000      # a larger upload is refused: it would not fit in memory with its Lab copy


def decode_upload(data: bytes) -> dict:
    """An uploaded picture (PNG, JPEG, TIFF ...) as LightBurn takes it: grey 0..1 by luminance (as a colour picture is converted for
    an Image layer, and as the reader converts the pictures of the operator's files), its opacity, and its colour (Lab) for choosing
    greys by colour; everything at full size and at preview size."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise PredictionError("the file is not a picture that can be read (PNG, JPEG, TIFF, BMP or WebP)")
    if img.shape[0] * img.shape[1] > MAX_PICTURE_PIXELS:
        raise PredictionError(f"the picture has {img.shape[1]} x {img.shape[0]} pixels: at most {MAX_PICTURE_PIXELS // 1_000_000} million are taken")
    if img.dtype != np.uint8:
        img = (img.astype(np.float32) / (65535.0 if img.dtype == np.uint16 else 1.0) * 255).clip(0, 255).astype(np.uint8)
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img[..., :3]
    grey, alpha = photo_modes.decode_picture(cv2.imencode(".png", img)[1].tobytes())
    rows, cols = grey.shape
    scale = min(1.0, PREVIEW_SIDE / max(rows, cols))
    size = (max(1, round(cols * scale)), max(1, round(rows * scale)))
    small = (lambda a: a) if scale >= 1 else (lambda a: cv2.resize(a, size, interpolation=cv2.INTER_AREA))
    return {"grey_full": grey, "alpha_full": alpha, "bgr_full": np.ascontiguousarray(bgr), "picture": np.ascontiguousarray(small(grey)),
            "alpha": np.ascontiguousarray(np.clip(small(alpha), 0.0, 1.0)), "lab": _lab_of(small(bgr)), "size": [cols, rows]}


def _lab_of(bgr: np.ndarray) -> np.ndarray:
    rgb = bgr[..., ::-1].reshape(-1, 3).astype(np.float64)
    return color.srgb8_to_lab(rgb).reshape(bgr.shape[:2] + (3,))


def picture_item(store: Store, mode: Mode, upload: Mapping, name: str, by_colour: bool = False, width_mm: float | None = None,
                 colour_choice: str = drawing.CHOICES[0], contours: bool = False, colouring: Mapping | None = None) -> dict:
    """A picture prepared for ``describe`` at ``mode``, engraved ``width_mm`` wide (its rows that long, DEC-107): its curve at that size,
    the levels and counts of its greys and the measured span. With ``by_colour`` the picture's colours are what is wanted: its greys are
    chosen at each Min and Max (``with_colours``) the way ``colour_choice`` says (DEC-108, DEC-109); with ``contours`` and ``by_colour`` the
    edges its engraving would lose are drawn in (``engraved``): never on a picture engraved as it was uploaded. With ``colour_choice``
    "objects" the objects of the picture (``objects`` of the item, :mod:`objects`, set by the caller) with a main colour in ``colouring``
    are coloured each along its own stretch of the scale (:mod:`colouring`)."""
    if mode.dither != prediction.PREDICTED_MODE:
        raise PredictionError("only the grayscale image mode is predicted from a scale")
    curve, basis = curve_for(store, mode, width_mm)
    lo, hi = curve.span
    settings = {**{k: getattr(mode, k) for k in SETTINGS}, "global_passes": mode.global_passes, "min_power": lo, "max_power": hi,
                "overridden": []}
    item = {"index": 0, "name": name, "dither": prediction.PREDICTED_MODE, "settings": settings, "refused": None, "mode": mode,
            "curve": curve, "reference": basis["reference"], "adjustments": {}, "basis_notes": list(basis["notes"]), "by_colour": by_colour,
            "colour_choice": colour_choice, "contours": bool(contours and by_colour), "colouring": dict(colouring or {}), "sizes": basis["sizes"],
            "pictures": 1, "turned": False, "width_mm": width_mm,
            **{k: upload[k] for k in ("picture", "alpha", "size", "lab", "grey_full", "alpha_full", "bgr_full")}}
    return _with_levels(item)


# -- a picture in a dot kind seen from the scale, before that kind was photographed (0.21.0) ---------------------------------------
DOT_PX_MAX = 4          # at most this many dots a side are drawn per preview pixel to see a dot kind from a distance (16 a pixel)
CLOSEUP_MM = 4.0        # the side of the close-up of the dots, in mm of the titanium, drawn dot for dot at the layer's DPI
CLOSEUP_PX = 3          # screen pixels per dot in the close-up


def clean_titanium(store: Store) -> list[float]:
    """The colour of cleaned titanium, between the dots of a dot kind: the nominal clean colour the measurements are expressed against."""
    return list(colormap.references(store)["nominal"])


def dot_power(curve: prediction.Curve, clean_lab) -> float:
    """The power of a dot kind's dots by default: the one at which the scale's colour stands out most from the cleaned titanium between
    the dots (the largest dE), to 0.1 %."""
    lo, hi = curve.span
    powers = np.unique(np.round(np.linspace(lo, hi, 200), 1))
    de = np.linalg.norm(curve.lab_at(powers) - np.asarray(clean_lab, np.float64), axis=1)
    return float(powers[int(np.nanargmax(np.where(np.isfinite(de), de, -1.0)))])


def dot_power_at(store: Store, mode: Mode, width_mm: float, wanted=None) -> float:
    """The power of a dot kind's dots on ``mode`` at ``width_mm``: ``wanted`` while the scale is measured there at that width, otherwise
    the power whose colour stands out most from the cleaned titanium (:func:`dot_power`)."""
    curve = curve_for(store, mode, width_mm)[0]
    lo, hi = curve.span
    if wanted is not None and lo <= wanted <= hi:
        return float(wanted)
    return dot_power(curve, clean_titanium(store))


def _rounded_hex(lab) -> str:
    rgb = np.clip(color.lab_to_srgb8(np.asarray([lab], float)), 0, 255).round().astype(int)[0]
    return "#%02x%02x%02x" % tuple(rgb)


def dots_at(store: Store, power: float, curve: prediction.Curve) -> dict:
    """The colour of the dots at ``power`` (the scale's colour there, at the curve's width) and of the cleaned titanium between them."""
    lab = curve.lab_at(float(power))
    if not np.all(np.isfinite(lab)):
        lo, hi = curve.span
        raise PredictionError(f"the dots' power {float(power):g} % lies outside the measured powers {lo:g}..{hi:g} % of the scale at this width: choose it inside them")
    clean = clean_titanium(store)
    return {"power": float(power), "lab": [round(float(v), 2) for v in lab], "hex": _rounded_hex(lab),
            "clean_lab": [round(float(v), 2) for v in clean], "clean_hex": _rounded_hex(clean)}


def _mixed(share: np.ndarray, dot_lab, clean_lab) -> np.ndarray:
    """RGB uint8 of dots of ``dot_lab`` striking ``share`` of the area on titanium of ``clean_lab``, as the eye mixes them (in linear light)."""
    dot, clean = (color.lab_to_linear_rgb(np.asarray(lab, np.float64)) for lab in (dot_lab, clean_lab))
    linear = share[..., None] * dot + (1.0 - share[..., None]) * clean
    return (color.linear_to_srgb(linear) * 255).round().astype(np.uint8)


def dot_look(picture, alpha, kind: str, dot_lab, clean_lab, width_mm: float, layer_dpi: float) -> tuple[np.ndarray, np.ndarray]:
    """A picture (grey 0..1 at preview size, ``width_mm`` wide on the titanium) engraved in the dot kind ``kind`` at ``layer_dpi`` with
    dots of colour ``dot_lab`` on cleaned titanium of ``clean_lab``, seen from a distance: the share of each pixel its dots strike
    (:func:`dots.coverage`, as many dots a pixel as the layer fires there, at most DOT_PX_MAX a side) and the colour mixed from dots and
    titanium in that share. RGB uint8 and the share; a transparent pixel is blank. An estimate: a dot is the shortest row there is, and
    its colour is taken from the scale's rows (DEC-107: the colour moves with the length of the rows)."""
    grey = np.asarray(picture, np.float64)
    rows, cols = grey.shape
    per_px = int(min(DOT_PX_MAX, max(1, round(float(width_mm) / grayscale.MM_PER_INCH * float(layer_dpi) / cols))))
    share = dots.coverage(grey, kind, dots_per_px=per_px, dpi=per_px * cols * grayscale.MM_PER_INCH / float(width_mm), alpha=alpha)
    rgb8 = _mixed(np.asarray(share, np.float64), dot_lab, clean_lab)
    if alpha is not None:
        rgb8[np.asarray(alpha) < photo_modes.ALPHA_MIN] = prediction.BLANK
    return rgb8, share


def dot_closeup(item: Mapping, kind: str, dot_lab, clean_lab, width_mm: float, fired: Mode | None = None) -> np.ndarray:
    """The dots of a dot kind dot for dot: a square of ``CLOSEUP_MM`` mm from the middle of the picture at the layer's DPI (the grid the laser
    fires on: of ``fired``, the settings the dots fire at when they are not the item's scale), each fired dot in ``dot_lab`` and the
    titanium between in ``clean_lab``, CLOSEUP_PX screen pixels a dot. RGB uint8."""
    rows, cols = item["grey_full"].shape
    dpi = grayscale.image_dpi((fired or item["mode"]).line_interval)
    target = (max(1, round(width_mm / grayscale.MM_PER_INCH * dpi)), max(1, round(width_mm * rows / cols / grayscale.MM_PER_INCH * dpi)))
    grey = cv2.resize(item["grey_full"], target, interpolation=cv2.INTER_AREA if target[0] < cols else cv2.INTER_LINEAR)
    alpha = cv2.resize(item["alpha_full"], target, interpolation=cv2.INTER_AREA if target[0] < cols else cv2.INTER_LINEAR)
    side = max(1, min(round(CLOSEUP_MM / grayscale.MM_PER_INCH * dpi), *grey.shape))
    y0, x0 = (grey.shape[0] - side) // 2, (grey.shape[1] - side) // 2
    window = (slice(y0, y0 + side), slice(x0, x0 + side))
    fired = dots.struck(grey[window], kind, dpi=dpi, alpha=alpha[window])
    rgb8 = _mixed(fired.astype(np.float64), dot_lab, clean_lab)
    return np.repeat(np.repeat(rgb8, CLOSEUP_PX, axis=0), CLOSEUP_PX, axis=1)


def at_width(store: Store, item: dict, width_mm: float) -> dict:
    """A prepared picture (``picture_item``) engraved at another width: its curve made again for that size; the same item when its width
    is that already."""
    width = check_width(width_mm)
    if item.get("width_mm") == width:
        return item
    curve, basis = curve_for(store, item["mode"], width)
    return {**item, "curve": curve, "reference": basis["reference"], "basis_notes": list(basis["notes"]), "sizes": basis["sizes"], "width_mm": width}


def _with_levels(item: dict) -> dict:
    opaque = item["alpha"] >= photo_modes.ALPHA_MIN
    if not opaque.any():
        raise PredictionError("the picture is fully transparent: it engraves nothing, so there is nothing to predict")
    item["levels"], item["counts"] = np.unique(item["picture"][opaque], return_counts=True)
    return item


def _px_per_mm(width_mm: float | None, cols: int) -> float:
    """Pixels per millimetre of a picture ``cols`` wide engraved ``width_mm`` wide: the drawing is kept in millimetres (DEC-108)."""
    if not width_mm:
        raise PredictionError("the width of the picture on the titanium is needed to keep its drawing")
    return cols / width_mm


def _choose(item: dict, lab: np.ndarray, opaque: np.ndarray, low: float, high: float, width_mm: float | None) -> dict:
    """The greys for the colours ``lab`` the way the item's ``colour_choice`` says: keeping the drawing (``drawing.choose``), the nearest
    colour (``grayscale.grey_for_colours``), or keeping the drawing with every object that has a main colour coloured along its own stretch
    of the scale (``colouring.colour``; the objects found at preview size, their map resized to ``lab``)."""
    choice = item.get("colour_choice", drawing.CHOICES[0])
    if choice == "nearest":
        return grayscale.grey_for_colours(lab, item["curve"], low, high)
    px_per_mm = _px_per_mm(width_mm, lab.shape[1])
    found = drawing.choose(lab, opaque, item["curve"], low, high, px_per_mm)
    if choice != "objects" or not item.get("colouring") or not item.get("objects"):
        return found
    labels = item["objects"]["labels"]
    if labels.shape != lab.shape[:2]:
        labels = cv2.resize(labels, (lab.shape[1], lab.shape[0]), interpolation=cv2.INTER_NEAREST)
    return colouring.colour(lab, opaque, labels, item["objects"]["objects"], item["colouring"], item["curve"], low, high, px_per_mm, found)


def with_colours(item: dict, min_power: float, max_power: float) -> dict:
    """The item whose picture is the grey chosen for each pixel's colour on the scale at Min..Max (``_choose``), and how near the colours
    come (median and 90th percentile dE of the opaque pixels), with, when the drawing is kept, the lightness its path of the scale spans, the
    greys on that path and how well the order of light and dark is kept."""
    low, high = check_power_range(min_power, max_power)
    opaque = item["alpha"] >= photo_modes.ALPHA_MIN
    found = _choose(item, item["lab"], opaque, low, high, item.get("width_mm"))
    de = found["delta_e"][opaque]
    out = _with_levels({**item, "picture": np.ascontiguousarray(found["grey8"].astype(np.float32) / (grayscale.LEVELS - 1))})
    out["colour_match"] = {"choice": item.get("colour_choice", drawing.CHOICES[0]), "median_de": round(float(np.median(de)), 1),
                           "p90_de": round(float(np.percentile(de, 90)), 1), "greys_used": int(len(np.unique(found["grey8"][opaque]))),
                           "greys_available": found["choices"], "reach": found.get("reach"), "path": found.get("path"), "order": found.get("order"),
                           "objects": found.get("objects")}
    return out


# the colours shown for the parts of a picture on its overlay, in the order of ``people.PARTS``
PART_COLOURS = ((90, 90, 90), (160, 90, 40), (255, 190, 140), (255, 140, 100), (70, 120, 255), (60, 200, 90))


def part_scores(item: dict) -> np.ndarray:
    """The people model's scores of the item's picture (``people.scores``), computed once and kept with the upload."""
    if "part_scores" not in item:
        item["part_scores"] = people.scores(item["bgr_full"])
    return item["part_scores"]


def parts_of(item: dict) -> list[dict]:
    """The parts the picture has, at preview size: each one's share of the opaque picture and its mean colour in the photograph."""
    rows, cols = item["picture"].shape
    parts = people.parts_at(part_scores(item), (cols, rows))
    opaque = item["alpha"] >= photo_modes.ALPHA_MIN
    total = int(opaque.sum()) or 1
    out = []
    for index, name in enumerate(people.PARTS):
        mask = (parts == index) & opaque
        if not mask.any():
            continue
        lab = item["lab"][mask].mean(axis=0)
        rgb = np.clip(color.lab_to_srgb8(lab[None]), 0, 255).astype(int)[0]
        out.append({"part": name, "share": round(float(mask.sum()) / total, 4), "lab": [round(float(v), 1) for v in lab],
                    "hex": "#%02x%02x%02x" % tuple(rgb)})
    return out


def parts_overlay(item: dict) -> np.ndarray:
    """The preview of the picture with every part tinted in its colour (``PART_COLOURS``), RGB uint8, to check what the model found."""
    rows, cols = item["picture"].shape
    parts = people.parts_at(part_scores(item), (cols, rows))
    grey = np.repeat((np.clip(item["picture"], 0, 1) * 255)[..., None], 3, axis=-1)
    tint = np.asarray(PART_COLOURS, np.float32)[parts]
    return (grey * 0.45 + tint * 0.55).round().astype(np.uint8)


def _spared(rules, parts: np.ndarray) -> np.ndarray | None:
    """The pixels of the parts engraved in one tone on purpose (rule ``even``): contours are not drawn there."""
    even = [people.PARTS.index(r["part"]) for r in rules or () if r["kind"] == "even"]
    return np.isin(parts, even) if even else None


def engraved(item: dict, min_power: float, max_power: float, rules: list[dict] | None = None) -> dict:
    """The item as it is engraved at Min..Max: its own greys or the greys chosen for its colours (``by_colour``), each part with a rule
    by that rule (``with_rules``) and, with ``contours`` (only for greys chosen for its colours, ``picture_item``), the edges this engraving
    would lose drawn in (``drawing.contours``; not inside a part engraved in one tone), with the share of the picture the lines take
    (``contours_report``)."""
    low, high = check_power_range(min_power, max_power)
    if rules:
        shown = with_rules(item, low, high, rules)
    else:
        shown = with_colours(item, low, high) if item["by_colour"] else item
    if not item.get("contours"):
        return shown
    rows, cols = item["picture"].shape
    spare = _spared(rules, people.parts_at(part_scores(item), (cols, rows))) if any(r["kind"] == "even" for r in rules or ()) else None
    base = (np.clip(shown["picture"], 0, 1) * 255).round().astype(np.uint8)
    lined = drawing.contours(base, item["lab"], item["alpha"] >= photo_modes.ALPHA_MIN, item["curve"], low, high,
                             _px_per_mm(item.get("width_mm"), cols), spare)
    out = _with_levels({**shown, "picture": np.ascontiguousarray(lined["grey8"].astype(np.float32) / (grayscale.LEVELS - 1))})
    out["contours_report"] = {"share": lined["share"]}
    return out


def with_rules(item: dict, min_power: float, max_power: float, rules: list[dict]) -> dict:
    """The item as it is engraved at Min..Max: its own greys (or the greys chosen for its colours with ``by_colour``) and, inside each
    part that has a rule, the greys of that rule (``picture_rules.greys``), with what each rule covers and reaches."""
    low, high = check_power_range(min_power, max_power)
    shown = with_colours(item, low, high) if item["by_colour"] else item
    if not rules:
        return shown
    rows, cols = item["picture"].shape
    base = (np.clip(shown["picture"], 0, 1) * 255).round().astype(np.uint8)
    done = picture_rules.greys(item["lab"], base, people.parts_at(part_scores(item), (cols, rows)), rules, item["curve"], low, high)
    out = _with_levels({**shown, "picture": np.ascontiguousarray(done["grey8"].astype(np.float32) / (grayscale.LEVELS - 1))})
    out["rules_report"] = done["rules"]
    return out


def cleaning(store: Store, mode: Mode) -> dict:
    """The cleaning a picture's file runs first on the laser of ``mode`` (``plans.clean_layer``): the scales were measured on cleaned
    plates, so the picture is engraved on cleaned titanium too."""
    return pl.clean_layer(devices.brief(store, mode.device_id)["passport"])


def picture_time(mode: Mode, width_mm: float, height_mm: float, clean: dict | None) -> dict:
    """How long the picture's file engraves at ``mode``: the cleaning ``clean`` over the picture's rectangle first, when it has one, then
    the whole rectangle scanned row by row (in grayscale mode every grey fires, the white at Min), at the mode's settings, one piece of
    scan line per row (``engraving_time.estimate``, DEC-101)."""
    settings = {**{k: getattr(mode, k) for k in SETTINGS}, "global_passes": mode.global_passes, "layer_type": "Image"}
    rows = (height_mm + (width_mm if settings.get("cross_hatch") else 0.0)) / mode.line_interval if mode.line_interval else None
    first = [] if clean is None else [{"index": pl.CLEAN_LAYER_INDEX, "name": clean["name"], "parameters": clean, "area_mm2": width_mm * height_mm,
                                       "scan_pieces": (height_mm + (width_mm if clean.get("cross_hatch") else 0.0)) / clean["line_interval"]}]
    index = 0 if clean is None else pl.CLEAN_LAYER_INDEX + 1
    return engraving_time.estimate(first + [{"index": index, "name": f"C{index:02d}", "parameters": settings, "area_mm2": width_mm * height_mm,
                                             "scan_pieces": rows}])


def picture_for_file(item: dict, min_power: float, max_power: float, width_mm: float, rules: list[dict] | None = None, *,
                     transparent: bool = False, fired: Mode | None = None) -> np.ndarray:
    """The 8-bit upright picture written to the LightBurn file, as ``engraved`` makes the preview: the uploaded grey, or with ``by_colour``
    the greys chosen for its colours, inside each part with a rule that rule's greys, and with ``contours`` the lost edges drawn in, at the
    layer's DPI (no finer: the laser does not engrave finer; ``fired`` is the layer's settings when they are not the item's scale, the
    dots of a recipe of the colour map). Transparent pixels are white, so they get Min power; with ``transparent`` the picture is BGRA
    instead and they stay transparent, so the layer leaves them alone (a photo zone of a vector work, DEC-114)."""
    rows, cols = item["grey_full"].shape
    dpi = grayscale.image_dpi((fired or item["mode"]).line_interval)
    target = (max(1, round(width_mm / grayscale.MM_PER_INCH * dpi)), max(1, round(width_mm * rows / cols / grayscale.MM_PER_INCH * dpi)))
    fit = (lambda a: a) if target[0] >= cols else (lambda a: cv2.resize(a, target, interpolation=cv2.INTER_AREA))
    alpha = fit(item["alpha_full"])
    low, high = check_power_range(min_power, max_power)
    contours = item.get("contours", False)
    lab = _lab_of(fit(item["bgr_full"])) if item.get("by_colour") or rules or contours else None
    opaque = alpha >= photo_modes.ALPHA_MIN
    if item.get("by_colour"):
        grey = _choose(item, lab, opaque, low, high, width_mm)["grey8"].astype(np.float32) / 255
    else:
        grey = fit(item["grey_full"])
    parts = people.parts_at(part_scores(item), (grey.shape[1], grey.shape[0])) if rules else None
    if rules:
        base = (np.clip(grey, 0, 1) * 255).round().astype(np.uint8)
        grey = picture_rules.greys(lab, base, parts, rules, item["curve"], low, high)["grey8"].astype(np.float32) / 255
    if contours:
        base = (np.clip(grey, 0, 1) * 255).round().astype(np.uint8)
        grey = drawing.contours(base, lab, opaque, item["curve"], low, high, _px_per_mm(width_mm, grey.shape[1]),
                                _spared(rules, parts) if rules else None)["grey8"].astype(np.float32) / 255
    grey = np.where(opaque, grey, 1.0)
    grey8 = (np.clip(grey, 0, 1) * 255).round().astype(np.uint8)
    if not transparent:
        return grey8
    return np.dstack([grey8, grey8, grey8, np.where(opaque, 255, 0).astype(np.uint8)])
