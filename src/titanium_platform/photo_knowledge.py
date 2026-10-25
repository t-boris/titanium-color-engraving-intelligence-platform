"""What the workshop knows of photo engraving on one laser and lens (feature photo-engraving-quality, REQ-003..REQ-005): every photographed
photo layer judged as a picture (``photo_quality.judge``), the best measured settings of each kind of engraving, what each setting
measurably does, the change for a slightly darker, lighter, sharper or softer engraving, and the experiment that would close what is not
known yet (a photo-variations plate, DEC-002, DEC-003).

* An **engraving** is one set of settings a photo layer was engraved at (:data:`KEYS`: the kind, power, Min power in grayscale, speed,
  frequency, Q-pulse, line interval, passes and the dot width) on one titanium, from the accepted checks of the laser and lens. Its tone
  is a ramp's when one was engraved at those settings (every grey alike), else a picture's; its detail a picture's. The best judged
  photograph stands for it. A grayscale ramp whose colour turns back past some power also gives the span below the turn
  (``photo_quality.ordered_span``) as an engraving of its own. An engraving that shows no picture (:func:`failed`: too little contrast,
  or a negative, as dots lighter than the titanium make it) is never a kind's best; a dot kind with only those takes the dots of another
  kind there (:func:`stand_in`, DEC-006).
* **Effects** come from engravings that differ in one setting only, measured the same way: ramps against ramps (the copies of a plate, the
  rows of a grey-scale plate), and for the detail the pictures of one photo-variations plate. Each is the change per doubling of the
  setting; :func:`effects` gives their median per setting with the photographs they rest on.
* The change for **darker / lighter / sharper / softer** (:func:`adjust`) takes the setting whose measured effect rests on the most
  photographs and moves it by what that effect says for one visible step (``STEP_L`` L*, ``STEP_KEPT`` of the detail); without a
  measured effect it takes the prior of the process (``PRIORS``) and says so.

Read on demand from the checks; nothing is stored here.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Mapping

from . import capability_plates as cp, ingest, photo_modes, photo_quality as pq, plans, prediction_store as ps, setup as su
from .db import Store, now
from .prediction import PredictionError

KEYS = ("power", "min_power", "speed", "frequency", "pulse_width", "line_interval", "passes", "global_passes", "dot_width")
NUMERIC = ("power", "min_power", "speed", "frequency", "pulse_width", "line_interval", "dot_width")
# the settings a step of :func:`adjust` moves: continuous ones; the frequency and the Q-pulse take the laser's own values and move the oxide's
# colour as much as its lightness, so their measured effects are shown but not stepped through
ADJUSTABLE = ("power", "min_power", "speed", "line_interval", "dot_width")
DIGITS = {"power": 2, "min_power": 2, "speed": 1, "frequency": 1, "pulse_width": 0, "line_interval": 4, "dot_width": 4}
METRICS = ("mean_L", "range_L", "shadows_blocked", "highlights_lost", "levels_share", "score", "kept")
STEP_L = 3.0                    # L*: one visible step lighter or darker (1.5 JND)
STEP_KEPT = 0.1                 # one visible step of the detail kept at 0.4 mm
MIN_EFFECT = {"mean_L": 1.0, "kept": 0.03}       # per doubling: a smaller measured effect does not move the engraving a step
FACTOR = (0.67, 1.5)            # one step changes a setting by at most this factor
LIMITS = {"power": (0.5, 100.0), "min_power": (0.0, 100.0), "speed": (1.0, 10000.0), "line_interval": (0.005, 0.2),
          "frequency": (1.0, 4000.0), "pulse_width": (1.0, 2000.0), "dot_width": (0.0, 0.05)}
# without a measured effect: the priors of the process, the strongest first, per kind family and direction: a factor, or for the dot width
# a step in mm. More energy per area darkens and spreads the mark (dot gain, heat): less of it is sharper; the dot width correction shrinks
# each dot; in grayscale Max sets the darkest tone and Min the lightest.
PRIORS = {("dots", "darker"): (("power", 1.15),), ("dots", "lighter"): (("power", 1 / 1.15),),
          ("dots", "sharper"): (("dot_width", +0.005), ("power", 1 / 1.1)), ("dots", "softer"): (("dot_width", -0.005), ("power", 1.1)),
          ("grayscale", "darker"): (("power", 1.1), ("min_power", 1.2)), ("grayscale", "lighter"): (("power", 1 / 1.1), ("min_power", 1 / 1.2)),
          ("grayscale", "sharper"): (("power", 1 / 1.1),), ("grayscale", "softer"): (("power", 1.1),)}
DIRECTIONS = ("darker", "lighter", "sharper", "softer")
TARGETS = {"darker": ("mean_L", -STEP_L), "lighter": ("mean_L", STEP_L), "sharper": ("kept", STEP_KEPT), "softer": ("kept", -STEP_KEPT)}
WATCHED = ("jarvis", "atkinson", "stucki", "grayscale")      # the kinds the laboratory keeps proposing experiments for


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def settings_of(rep: Mapping) -> dict | None:
    """The settings a check's photo layer was engraved at (:data:`KEYS` and its ``dither``), as the file holds them; None for a layer that
    engraves no tone (a relief, an unknown mode)."""
    image = rep.get("image") or {}
    kind = photo_modes.mode(image.get("dither"))
    if kind is None or kind.family not in (photo_modes.POWER, photo_modes.DOTS):
        return None
    dots = kind.family == photo_modes.DOTS
    value = lambda setting: _number(ingest.effective_setting(rep, setting))     # noqa: E731  (the file's, else the operator's, else the laser's)
    power = value("power")
    out = {"dither": kind.key, "power": power, "min_power": power if dots else _number(image.get("min_power")),
           "speed": value("speed"), "frequency": value("frequency"), "pulse_width": value("pulse_width"),
           "line_interval": value("line_interval"), "passes": int(value("passes") or 1),
           "global_passes": int(rep.get("global_passes") or 1),
           "dot_width": _number(image.get("dot_width_mm")) if dots and image.get("dot_correction") else None}
    return _rounded(out)


def _rounded(settings: Mapping) -> dict:
    return {k: (round(v, DIGITS[k]) if isinstance(v, float) and k in DIGITS else v) for k, v in settings.items()}


def _step_value(key: str, value: float) -> float:
    """A value a step of :func:`adjust` gives, rounded as the operator types it: power to 0.5 %, speed to 1 mm/s, the rest to its digits."""
    return pq._round(key, value) if key in ("power", "min_power", "speed") else round(value, DIGITS.get(key, 4))


def _key(settings: Mapping) -> str:
    return json.dumps({k: settings.get(k) for k in ("dither", *KEYS)}, sort_keys=True)


def _family(kind: str) -> str:
    return "grayscale" if kind == "grayscale" else "dots"


def photographs(store: Store, device_id: int, lens_id: int | None) -> list[dict]:
    """Every photo layer of the accepted checks of a laser and lens, judged: its pair, layer, titanium, settings, how its tone was measured
    (``grey ramp`` or ``picture``), the plate type it was engraved on, the judgement (``photo_quality.judge``) and its black end's colour."""
    rows = store.query(
        "SELECT p.id, p.material_id, p.context_json, p.data_json, p.accepted_at, t.test_type, t.id AS plate_id FROM pair p "
        "LEFT JOIN plan l ON l.id=p.plan_id LEFT JOIN plate t ON t.id=COALESCE(p.plate_id, l.plate_id) "
        "WHERE p.status=? AND p.device_id=? AND p.lens_id IS ? ORDER BY p.id", (ingest.ST_ACCEPTED, device_id, lens_id))
    out = []
    for row in rows:
        check = json.loads(row["data_json"] or "{}").get("check") or {}
        material = row["material_id"] or json.loads(row["context_json"] or "{}").get("material_id")
        for rep in check.get("layers") or []:
            settings = settings_of(rep) if rep.get("tonal") else None
            if settings is None:
                continue
            judged = pq.judge(rep["tonal"], (rep.get("quality") or {}).get("detail"), settings["dither"])
            if judged is None:
                continue
            bins = sorted(rep["tonal"]["bins"], key=lambda b: b["gray"])
            item = {"pair_id": row["id"], "layer": rep.get("name"), "material_id": material, "settings": settings,
                    "measured_by": rep["tonal"].get("measured_by") or "picture", "plate_type": row["test_type"], "plate_id": row["plate_id"],
                    "accepted_at": row["accepted_at"], "black_lab": [bins[0]["L"], bins[0].get("a", 0.0), bins[0].get("b", 0.0)], **judged}
            out.append(item)
            span = pq.ordered_span(rep["tonal"]) if settings["dither"] == "grayscale" and item["measured_by"] == "grey ramp" else None
            if span is not None:                    # the part of the ramp below the oxide's turn: an engraving of its own
                out.append({**item, "settings": _rounded({**settings, "min_power": span["min_power"], "power": span["max_power"]}),
                            "span_of": rep.get("name"), "tone": span["tone"], "detail": None, "score": pq.score(span["tone"]),
                            "findings": pq.findings(span["tone"], None, "grayscale")})
    return out


def engravings(store: Store, device_id: int, lens_id: int | None, material_id: int | None = None, kind: str | None = None,
               items: list[dict] | None = None) -> list[dict]:
    """The engravings of a laser and lens (see the module), the best judged first; only one titanium's and one kind's when given.
    ``items``: the :func:`photographs` already read."""
    groups: dict[tuple, list[dict]] = {}
    for item in photographs(store, device_id, lens_id) if items is None else items:
        if (material_id is not None and item["material_id"] != material_id) or (kind is not None and item["settings"]["dither"] != kind):
            continue
        groups.setdefault((item["material_id"], _key(item["settings"])), []).append(item)
    out = []
    for (material, _), items in groups.items():
        ramps = [i for i in items if i["measured_by"] == "grey ramp"]
        pictures = [i for i in items if i["measured_by"] != "grey ramp"]
        rank = lambda i: (i["score"] or 0.0, i["pair_id"])          # noqa: E731
        toned = max(ramps or pictures, key=rank)
        detailed = max((i for i in pictures if i.get("detail")), key=rank, default=None)
        detail = (detailed or {}).get("detail")
        settings = items[0]["settings"]
        out.append({"settings": settings, "material_id": material, "tone": toned["tone"], "detail": detail,
                    "score": pq.score(toned["tone"], detail), "findings": pq.findings(toned["tone"], detail, settings["dither"]),
                    "measured_by": toned["measured_by"], "span_of": toned.get("span_of"), "black_lab": toned["black_lab"],
                    "source": {"pair_id": toned["pair_id"], "layer": toned["layer"]},
                    "photographs": sorted({i["pair_id"] for i in items}), "plate_types": sorted({i["plate_type"] or "work" for i in items}),
                    "variations": sorted({i["plate_id"] for i in items if i["plate_type"] == "photo_variations"})})
    return sorted(out, key=lambda e: (-(e["score"] or 0.0), -len(e["photographs"]), -max(e["photographs"])))


def failed(engraving: Mapping) -> bool:
    """Whether a judged engraving shows no picture (``photo_quality.findings`` «flat»: its dark end less than ``FLAT_RANGE_L`` darker than
    its light end, or lighter, as dots lighter than the titanium make it, a negative): never a kind's best (DEC-006)."""
    return any(f["code"] == "flat" for f in engraving["findings"])


def _usable(engraving: Mapping, dot_width: bool) -> bool:
    """Whether an engraving can be a kind's best for its owner: judged, a picture (:func:`failed`), and without the dot width correction
    when the owner cannot write it."""
    return engraving["score"] is not None and not failed(engraving) and (dot_width or engraving["settings"].get("dot_width") is None)


def best(store: Store, device_id: int, lens_id: int | None, material_id: int | None, kind: str, *, dot_width: bool = True) -> dict | None:
    """The best measured engraving of ``kind`` on the laser and lens: on the titanium when it has one there, else on any (``other_titanium``);
    never one that showed no picture (:func:`failed`, DEC-006); without the dot width correction when the owner cannot write it
    (``dot_width`` False: a photo zone). None when none usable was photographed."""
    for material in ([material_id, None] if material_id is not None else [None]):
        found = [e for e in engravings(store, device_id, lens_id, material, kind) if _usable(e, dot_width)]
        if found:
            return {**found[0], "other_titanium": material is None and material_id is not None, "tried": len(found)}
    return None


def failures(store: Store, device_id: int, lens_id: int | None, material_id: int | None, kind: str) -> list[dict]:
    """The engravings of ``kind`` on the laser, lens and titanium that showed no picture (:func:`failed`), the newest photograph first."""
    if material_id is None:
        return []
    return sorted((e for e in engravings(store, device_id, lens_id, material_id, kind) if failed(e)), key=lambda e: -max(e["photographs"]))


def stand_in(store: Store, device_id: int, lens_id: int | None, material_id: int | None, kind: str, *, dot_width: bool = True) -> dict | None:
    """The dots a dot kind takes on a titanium where every engraving of it showed no picture (DEC-006): the best usable engraving of
    another dot kind there (:func:`_usable`), an estimate until the kind itself is photographed. None for grayscale, for a kind never
    photographed there or with an engraving that is not a failure, and when no other dot kind was photographed usable there."""
    if kind == "grayscale" or material_id is None:
        return None
    here = engravings(store, device_id, lens_id, material_id)
    mine = [e for e in here if e["settings"]["dither"] == kind]
    if not mine or not all(failed(e) for e in mine):
        return None
    found = next((e for e in here if e["settings"]["dither"] not in ("grayscale", kind) and _usable(e, dot_width)), None)
    return None if found is None else {**found, "other_titanium": False, "tried": 1}


# -- the best settings filled in when a kind is chosen (REQ-004) ---------------------------------------------------------------------
DOT_SETTINGS = ("power", "speed", "frequency", "pulse_width", "line_interval", "passes", "global_passes")


def recipe(engraving: Mapping) -> dict:
    """The dots of a measured photo engraving of a dot kind as a work or photo zone keeps them (``dot_recipe``, as ``dot_colours.recipe``
    keeps a fill of the colour map, ``source`` "photo"): its settings, the colour where its dots cover the titanium (the black end of its
    tones, as photographed), the photographs it rests on and how it was judged. Its colour was measured on a picture, not on rows of
    one length: it does not change with the owner's width (``size`` None)."""
    settings = {k: engraving["settings"].get(k) for k in DOT_SETTINGS}
    settings["passes"], settings["global_passes"] = settings["passes"] or 1, settings["global_passes"] or 1
    source = engraving["source"]
    return {"entry": f"photo:{source['pair_id']}:{source['layer']}", "source": "photo", "settings": settings,
            "lab": [round(float(v), 2) for v in engraving["black_lab"]], "size": None, "engravings": len(engraving["photographs"]),
            "photographs": len(engraving["photographs"]), "basis": engraving["measured_by"], "missing": False, "picked_at": now(),
            "photo": {"pair_id": source["pair_id"], "layer": source["layer"], "kind": engraving["settings"]["dither"],
                      "score": engraving["score"], "findings": [f["code"] for f in engraving["findings"]]}}


def filled(store: Store, mode: ps.Mode, kind: str, *, dot_width: bool = True) -> dict | None:
    """The settings a work or photo zone on ``mode`` (its scale: laser, lens and titanium) takes when ``kind`` is chosen: the best measured
    engraving of that kind on its own titanium (:func:`best`); a dot kind whose every engraving there showed no picture takes the dots of
    the best engraving of another dot kind there (:func:`stand_in`, DEC-006). A dot kind: its dots (``dot_recipe``, :func:`recipe`) and dot
    width (when the owner writes one, ``dot_width``); grayscale: its measured scale and the span of its tones in order (``scale``,
    ``min_power``, ``max_power``) when that scale is measured. None when nothing usable of the kind was photographed there."""
    found = best(store, mode.device_id, mode.lens_id, mode.material_id, kind, dot_width=dot_width)
    if (found is None or found["other_titanium"]) and kind != "grayscale":
        found = stand_in(store, mode.device_id, mode.lens_id, mode.material_id, kind, dot_width=dot_width) or found
    if found is None or found["other_titanium"]:
        return None
    settings = found["settings"]
    if kind != "grayscale":
        out = {"dot_recipe": recipe(found)}
        if dot_width:
            out["dot_width"] = settings.get("dot_width")
        return out
    wanted = {"device_id": mode.device_id, "lens_id": mode.lens_id, "material_id": mode.material_id,
              **{k: settings.get(k) for k in ("speed", "frequency", "pulse_width", "line_interval", "passes", "global_passes")}}
    try:
        scale = ps.measured_mode(store, wanted)
    except su.ValidationError:
        return None
    return {"scale": scale, "min_power": settings["min_power"], "max_power": settings["power"], "best": found["source"]}


def ordered_span(store: Store, mode: ps.Mode) -> tuple[float, float] | None:
    """Min and Max of a grayscale scale whose tones stay in order (``photo_quality.ordered_span``): the best grayscale engraving measured
    at exactly the scale's settings on its titanium, when it is a span of a ramp that turns back; None when none was."""
    for engraving in engravings(store, mode.device_id, mode.lens_id, mode.material_id, "grayscale"):
        if mode.matches(engraving["settings"]):
            return (float(engraving["settings"]["min_power"]), float(engraving["settings"]["power"])) if engraving.get("span_of") else None
    return None


def default_span(store: Store, mode: ps.Mode, width_mm: float) -> tuple[float, float]:
    """Min and Max a grayscale picture takes on a scale: the scale's measured powers at ``width_mm`` (``prediction_store.measured_span``),
    narrowed to the span whose tones stay in order once a photograph showed where the scale's oxide turns back (:func:`ordered_span`)."""
    low, high = ps.measured_span(store, mode, width_mm)
    ordered = ordered_span(store, mode)
    if ordered is not None and max(low, ordered[0]) < min(high, ordered[1]):
        return max(low, ordered[0]), min(high, ordered[1])
    return low, high


def _distance(a: Mapping, b: Mapping) -> float:
    """How far apart two settings are: the sum of the doublings between their continuous settings (power, speed, frequency, Q-pulse, line
    interval)."""
    out = 0.0
    for key in ("power", "speed", "frequency", "pulse_width", "line_interval"):
        x, y = _number(a.get(key)), _number(b.get(key))
        out += abs(math.log2(y / x)) if x and y and x > 0 and y > 0 else (0.0 if x == y else 4.0)
    return out


def dots_at(store: Store, mode: ps.Mode, kind: str, settings: Mapping, width_mm: float, current: Mapping | None = None) -> dict:
    """How a work or photo zone on ``mode`` (its scale) engraves ``kind``'s dots at ``settings`` (:data:`DOT_SETTINGS`; a step of
    :func:`adjust`): on the scale at that power (``dot_power``) when those are the scale's settings and the power lies in its measured
    powers at ``width_mm``; else as a recipe (``dot_recipe``): the engraving measured at exactly those settings (:func:`recipe`), or the
    settings with the colour of the dots kept now (``current``) or of the nearest measured engraving of the kind, marked ``estimate``."""
    wanted = {k: _number(settings.get(k)) for k in DOT_SETTINGS}
    if wanted["power"] is None or not 0 < wanted["power"] <= 100:
        raise su.ValidationError("the dots' power must be a number above 0 and up to 100 %")
    for key in ("speed", "frequency", "pulse_width", "line_interval"):
        if wanted[key] is None or wanted[key] <= 0:
            raise su.ValidationError("give the dots' speed, frequency, Q-pulse and line interval")
    wanted["passes"], wanted["global_passes"] = int(wanted["passes"] or 1), int(wanted["global_passes"] or 1)
    if mode.matches(wanted):
        try:
            lo, hi = ps.curve_for(store, mode, width_mm)[0].span
        except PredictionError:
            lo, hi = math.inf, -math.inf
        if lo <= wanted["power"] <= hi:
            return {"dot_power": wanted["power"], "dot_recipe": None}
    measured = engravings(store, mode.device_id, mode.lens_id, mode.material_id, kind)
    exact = next((e for e in measured if all(_same(e["settings"].get(k), wanted[k]) for k in DOT_SETTINGS)), None)
    if exact is not None:
        return {"dot_recipe": recipe(exact)}
    nearest = min(measured, key=lambda e: _distance(e["settings"], wanted), default=None)
    if current is None and nearest is None:
        raise su.ValidationError("no engraving of this kind was photographed on this titanium: its dots' colour is not known at these settings")
    lab = current["lab"] if current is not None else nearest["black_lab"]
    entry = "settings:" + json.dumps({k: wanted[k] for k in DOT_SETTINGS}, sort_keys=True)
    return {"dot_recipe": {"entry": entry, "source": "photo", "settings": wanted, "lab": [round(float(v), 2) for v in lab], "size": None,
                           "engravings": 0, "photographs": 0, "basis": "estimate", "missing": False, "picked_at": now(),
                           "photo": None if nearest is None else {"pair_id": nearest["source"]["pair_id"], "layer": nearest["source"]["layer"],
                                                                  "kind": kind, "score": None, "findings": [], "near": True}}}


def _same(a, b) -> bool:
    x, y = _number(a), _number(b)
    return (x is None and y is None) or (x is not None and y is not None and abs(x - y) <= 1e-6 * max(1.0, abs(x), abs(y)))


def _differs(a: Mapping, b: Mapping) -> str | None:
    """The one setting two engravings differ in, or None when they differ in none or in more."""
    dots = a.get("dither") != "grayscale"                 # a dot kind's Min power is its power: it changes with it, not on its own
    keys = [k for k in ("dither", *KEYS) if a.get(k) != b.get(k) and not (dots and k == "min_power")]
    return keys[0] if len(keys) == 1 else None


def _doublings(key: str, a, b) -> float | None:
    if key == "dot_width":                      # the correction off counts as no width
        a, b = a or 0.0, b or 0.0
        return (b - a) / 0.01 if a != b else None                     # per 0.01 mm of correction
    if not a or not b or a <= 0 or b <= 0 or a == b:
        return None
    return math.log2(b / a)


def effects(store: Store, device_id: int, lens_id: int | None, material_id: int | None, kind: str,
            items: list[dict] | None = None) -> dict[str, dict]:
    """What each setting measurably does to engravings of ``kind`` (see the module): per setting, the median change of each of
    :data:`METRICS` per doubling (the dot width: per 0.01 mm), how many comparisons and which photographs they rest on. ``items``: the
    :func:`photographs` already read."""
    items = [i for i in (photographs(store, device_id, lens_id) if items is None else items) if i["settings"]["dither"] == kind
             and not i.get("span_of") and (material_id is None or i["material_id"] == material_id)]
    found: dict[str, dict[str, list[float]]] = {}
    sources: dict[str, set[int]] = {}
    for n, a in enumerate(items):
        for b in items[n + 1:]:
            key = _differs(a["settings"], b["settings"])
            if key is None or key not in NUMERIC or a["material_id"] != b["material_id"]:
                continue
            ramps = a["measured_by"] == b["measured_by"] == "grey ramp"
            pictures = (a["measured_by"] == b["measured_by"] == "picture" and a["pair_id"] == b["pair_id"]
                        and a["plate_type"] == "photo_variations")                 # copies of one picture in one photograph
            if not (ramps or pictures):
                continue
            steps = _doublings(key, a["settings"][key], b["settings"][key])
            if not steps:
                continue
            values = found.setdefault(key, {m: [] for m in METRICS})
            for metric in METRICS:
                if metric == "kept":
                    x, y = (a.get("detail") or {}).get("kept"), (b.get("detail") or {}).get("kept")
                elif metric == "score":
                    x, y = a["score"], b["score"]
                else:
                    x, y = a["tone"].get(metric), b["tone"].get(metric)
                if x is not None and y is not None and (ramps or metric == "kept"):
                    values[metric].append((y - x) / steps)
            sources.setdefault(key, set()).update((a["pair_id"], b["pair_id"]))
    out = {}
    for key, values in found.items():
        out[key] = {"per": "0.01 mm" if key == "dot_width" else "doubling", "photographs": sorted(sources[key]),
                    **{m: {"median": round(statistics.median(v), 3), "n": len(v)} for m, v in values.items() if v}}
    return out


def _limited(key: str, value: float, settings: Mapping, turn: float | None = None) -> float | None:
    lo, hi = LIMITS.get(key, (0.0, math.inf))
    if key == "min_power":
        hi = min(hi, float(settings.get("power") or 100.0) - 0.5)
    if key == "power" and settings.get("dither") == "grayscale":
        lo = max(lo, float(settings.get("min_power") or 0.0) + 0.5)
        hi = hi if turn is None else min(hi, turn)          # past the scale's turn its tones go back lighter
    if key == "dot_width" and value <= 0:
        return None
    return round(min(hi, max(lo, _step_value(key, value))), DIGITS.get(key, 4))    # rounded as typed, never past a limit


def adjust(store: Store, device_id: int, lens_id: int | None, material_id: int | None, settings: Mapping, direction: str,
           allowed: tuple[str, ...] | None = None, turn: float | None = None) -> dict:
    """The settings for one visible step ``direction`` (darker, lighter, sharper, softer) from ``settings`` (a photo engraving's: its
    ``dither`` and :data:`KEYS`): the setting with the largest measured effect that way (then the one resting on the most photographs) moved
    by what the effect says, at most ``FACTOR``; without one the prior (``PRIORS``). ``allowed``: the settings the owner can change (a grayscale work
    on a measured scale: its Min and Max); ``turn``: the power past which a grayscale scale's tones turn back lighter (Max stays below
    it, :func:`ordered_span`). Returns the new settings, what changed, the basis and the expected change."""
    if direction not in DIRECTIONS:
        raise su.ValidationError("choose darker, lighter, sharper or softer")
    kind = str(settings.get("dither") or "")
    if photo_modes.mode(kind) is None:
        raise su.ValidationError("choose the kind of photo engraving first")
    current = _rounded({k: _number(settings.get(k)) if k in NUMERIC else settings.get(k) for k in KEYS} | {"dither": kind})
    metric, target = TARGETS[direction]
    measured = effects(store, device_id, lens_id, material_id, kind)
    candidates = []
    for key, found in measured.items():
        slope = (found.get(metric) or {}).get("median")
        if slope is None or abs(slope) < MIN_EFFECT[metric] or key not in (ADJUSTABLE if allowed is None else allowed):
            continue
        if key != "dot_width" and not current.get(key):
            continue
        candidates.append((-abs(slope), -found[metric]["n"], key, slope, found))       # the strongest lever first (REQ-004)
    for _, _, key, slope, found in sorted(candidates):
        steps = target / slope
        if key == "dot_width":
            wanted = (current.get(key) or 0.0) + 0.01 * steps
        else:
            wanted = current[key] * min(FACTOR[1], max(FACTOR[0], 2 ** steps))
        value = _limited(key, wanted, current, turn)
        if _moves(current.get(key), wanted, value):
            return _adjusted(current, direction, key, value, "measured", {"metric": metric, "per": found["per"], "median": slope,
                                                                          "n": found[metric]["n"], "photographs": found["photographs"]})
    for key, change in PRIORS[(_family(kind), direction)]:
        if key not in (ADJUSTABLE if allowed is None else allowed):
            continue
        if key == "dot_width":
            wanted = (current.get(key) or (0.005 if change > 0 else 0.0)) + change
        elif current.get(key):
            wanted = float(current[key]) * change
        else:
            continue
        value = _limited(key, wanted, current, turn)
        if _moves(current.get(key), wanted, value):
            return _adjusted(current, direction, key, value, "prior", None)
    raise su.ValidationError("the settings are already at their limits: nothing known moves the engraving further that way")


def _moves(now_, wanted: float, value) -> bool:
    """Whether a limited ``value`` still moves a setting the way ``wanted`` does (a limit can leave it where it is, or even push it back)."""
    before = now_ or 0.0
    return (value or 0.0) != before and ((value or 0.0) - before) * (wanted - before) > 0


def _adjusted(current: dict, direction: str, key: str, value, basis: str, evidence: dict | None) -> dict:
    new = {**current, key: value}
    if key == "power" and current["dither"] != "grayscale":
        new["min_power"] = value                 # every dot fires at the layer's power
    return {"direction": direction, "settings": new, "changed": [{"setting": key, "from": current.get(key), "to": value}],
            "basis": basis, "evidence": evidence}


def _applied(found: Mapping) -> dict:
    """The change of a work or photo zone that makes the step ``found`` (:func:`adjust`): grayscale's Min and Max, a dot kind's dot width,
    or the settings its dots fire at (``dot_settings``)."""
    new = found["settings"]
    if new["dither"] == "grayscale":
        return {"min_power": new["min_power"], "max_power": new["power"]}
    if found["changed"][0]["setting"] == "dot_width":
        return {"dot_width": new["dot_width"]}
    return {"dot_settings": {k: new[k] for k in DOT_SETTINGS}}


def _taken(store: Store, mode: ps.Mode, engraving: Mapping, dot_width: bool) -> dict | None:
    """The change of a work or photo zone on ``mode`` that engraves it at the measured ``engraving`` of its kind: grayscale's measured scale
    with Min and Max, a dot kind's dots at its settings (and its dot width, when the owner writes one); None when its titanium is another
    or its grey scale is not measured there."""
    if engraving["other_titanium"]:
        return None
    settings = engraving["settings"]
    if settings["dither"] != "grayscale":
        out = {"dot_settings": {k: settings[k] for k in DOT_SETTINGS}}
        if dot_width:
            out["dot_width"] = settings.get("dot_width")
        return out
    keys = ("speed", "frequency", "pulse_width", "line_interval", "passes", "global_passes")
    try:
        scale = ps.measured_mode(store, {"device_id": mode.device_id, "lens_id": mode.lens_id, "material_id": mode.material_id,
                                         **{k: settings.get(k) for k in keys}})
    except su.ValidationError:
        return None
    return {"scale": {"device_id": scale.device_id, "lens_id": scale.lens_id, "material_id": scale.material_id, **{k: getattr(scale, k) for k in keys}},
            "min_power": settings["min_power"], "max_power": settings["power"]}


def advice(store: Store, mode: ps.Mode, centre: Mapping, *, dot_width: bool = True, own: bool = True) -> dict:
    """What the laboratory knows and proposes for a work or photo zone engraved at ``centre`` (the settings of its file's layer: ``dither``
    and :data:`KEYS`) on ``mode`` (its scale: laser, lens and titanium), read from ``store`` (its source of measurements): the best
    measured engraving of its kind there and whether it is engraved at it, what each setting measurably does, one step darker, lighter,
    sharper and softer from where it is (:func:`adjust`, each with the change that applies it, ``apply``, or why there is none), and, for
    the workshop's own measurements (``own``), where the search of its kind stands and the experiment proposed (:func:`knowledge`);
    ``take``: the change that engraves it at the best measured engraving (:func:`_taken`), and for grayscale the scale's ``turn`` (the span
    of its tones in order, :func:`ordered_span`): with Max past it no step is offered and ``take`` brings it back inside.
    ``dot_width``: whether the owner writes LightBurn's dot width correction (a photo zone does not; said back as ``dot_width``, so the plate
    proposed is made for the same owner). A kind with no usable engraving there: ``failed``, its engravings that showed no picture
    (:func:`failures`), and for a dot kind ``stand_in``, the dots of another kind it takes instead (:func:`stand_in`), which ``take``
    applies (DEC-006)."""
    kind = str(centre.get("dither") or "grayscale")
    current = _rounded({**{k: centre.get(k) for k in KEYS}, "dither": kind})
    if kind != "grayscale":
        current["min_power"] = current["power"]
    allowed = ("power", "min_power") if kind == "grayscale" else ("power", "speed", "line_interval") + (("dot_width",) if dot_width else ())
    span = ordered_span(store, mode) if kind == "grayscale" else None
    past_turn = span is not None and current["power"] > span[1] + 0.25
    steps = {}
    for direction in DIRECTIONS:
        if past_turn:                            # past the turn more power is lighter, not darker: no step means what it says there
            steps[direction] = {"refused": "Max lies past the power where this scale's tones turn back lighter: take the span in order first"}
            continue
        try:
            found = adjust(store, mode.device_id, mode.lens_id, mode.material_id, current, direction, allowed, None if span is None else span[1])
        except su.ValidationError as exc:
            steps[direction] = {"refused": str(exc)}
            continue
        steps[direction] = {**found, "apply": _applied(found)}
    top = best(store, mode.device_id, mode.lens_id, mode.material_id, kind, dot_width=dot_width)
    at = lambda e: all(_same(e["settings"].get(k), current.get(k)) for k in (*DOT_SETTINGS, "min_power", "dot_width"))    # noqa: E731
    at_best = top is not None and not top["other_titanium"] and at(top)
    take = None if top is None or at_best else _taken(store, mode, top, dot_width)
    flops = failures(store, mode.device_id, mode.lens_id, mode.material_id, kind) if top is None or top["other_titanium"] else []
    stand = stand_in(store, mode.device_id, mode.lens_id, mode.material_id, kind, dot_width=dot_width) if flops else None
    if stand is not None:
        take = None if at(stand) else _taken(store, mode, stand, dot_width)
    if past_turn and take is None:               # at least the span of this scale's tones in order
        take = {"min_power": max(current["min_power"] or 0.0, span[0]), "max_power": span[1]}
    entry = None
    if own:
        entry = next((k for k in knowledge(store, mode.device_id, mode.lens_id, mode.material_id, dot_width=dot_width)["kinds"]
                      if k["kind"] == kind), None)
    return {"kind": kind, "current": current, "best": top, "at_best": at_best, "take": take, "failed": flops, "stand_in": stand,
            "dot_width": dot_width,
            "turn": None if span is None else {"min_power": span[0], "max_power": span[1], "past": past_turn},
            "effects": effects(store, mode.device_id, mode.lens_id, mode.material_id, kind), "steps": steps,
            "status": None if entry is None else entry["status"], "proposal": None if entry is None else entry["proposal"]}


# -- the experiments that close what is not known (REQ-005) ----------------------------------------------------------------------
def _plate_searches(store: Store, device_id: int, lens_id: int | None) -> list[dict]:
    """The photographed photo-variations plates of a laser and lens, the newest first: each with its accepted pair and the comparison of its
    copies (``photo_quality.plate_report`` through ``ingest.get_pair``)."""
    rows = store.query(
        "SELECT p.id FROM pair p LEFT JOIN plan l ON l.id=p.plan_id JOIN plate t ON t.id=COALESCE(p.plate_id, l.plate_id) "
        "WHERE p.status=? AND p.device_id=? AND p.lens_id IS ? AND t.test_type='photo_variations' ORDER BY p.id DESC",
        (ingest.ST_ACCEPTED, device_id, lens_id))
    out = []
    for row in rows:
        pair = ingest.get_pair(store, row["id"])
        report = pair.get("variations")
        if report:
            centre = next((c for c in report["ranked"] if c["copy"] == 1), None)
            out.append({"pair_id": row["id"], "plan_id": pair["plan_id"], "report": report, "centre_kind": None if centre is None else
                        _centre_kind(store, pair["plan_id"])})
    return out


def _centre_kind(store: Store, plan_id: int) -> str | None:
    plan = store.one("SELECT plate_id FROM plan WHERE id=?", (plan_id,))
    plate = store.one("SELECT geometry_json FROM plate WHERE id=?", (plan["plate_id"],)) if plan else None
    copies = ((json.loads(plate["geometry_json"] or "{}") if plate else {}).get("variations") or {}).get("copies") or []
    return copies[0]["variant"]["dither"] if copies else None


def _variations_of(store: Store, plan_id: int) -> dict | None:
    """The variations of the plate of a photo-variations plate's plan, as its geometry keeps them (its copies, their size, its picture)."""
    row = store.one("SELECT t.geometry_json FROM plan l JOIN plate t ON t.id=l.plate_id WHERE l.id=?", (plan_id,))
    return None if row is None else json.loads(row["geometry_json"] or "{}").get("variations")


def _described(proposal: dict, variations: Mapping | None) -> dict:
    """``proposal`` with what its plate finds out and how big it is: the change each copy makes from the centre (``copies``, the centre's
    own empty, DEC-003) and the plate made on the picture of ``variations`` (a photographed plate's): its copies' and its own size;
    ``plate`` None when no plate was photographed yet to take the picture from."""
    centre = proposal["centre"]
    changes = pq.variants_around({k: centre.get(k) for k in ("dither", "power", "min_power", "speed", "line_interval", "dot_width")},
                                 proposal["step"])
    copies = [[{"setting": k, "from": centre.get(k), "to": v} for k, v in change.items()] for change in changes]
    if variations is None:
        return {**proposal, "copies": copies, "plate": None}
    grid = cp.variation_grid(variations["width_mm"], variations["height_mm"], len(changes))
    return {**proposal, "copies": copies, "plate": {"copy_mm": [variations["width_mm"], variations["height_mm"]],
                                                    "size_mm": [round(grid["width"], 1), round(grid["height"], 1)],
                                                    "picture": (variations.get("picture") or {}).get("name")}}


def knowledge(store: Store, device_id: int, lens_id: int | None, material_id: int | None, items: list[dict] | None = None, *,
              dot_width: bool = True) -> dict:
    """What is known of each watched kind (:data:`WATCHED`, and every other kind photographed) on a laser, lens and titanium: the best
    measured engraving, how many were judged, the measured effects of its settings, where the search stands and the experiment proposed
    (``proposal``): the next plate of a search that has not settled; a plate around the best of a kind measured only on works; a plate of
    an unmeasured dot kind around the best dot engraving. Each proposal says what its copies change and how big its plate is
    (:func:`_described`). ``items``: the :func:`photographs` of the laser and lens already read. ``dot_width`` False (a photo zone, which
    writes no dot width correction): only the engravings made without one count as the best and as a proposal's centre, as in :func:`best`.
    An engraving that showed no picture is never the best (:func:`failed`): a kind with only those is ``failed`` (its engravings listed
    there, the newest first), and a dot kind is proposed around the best dots of another kind, as one never photographed (DEC-006)."""
    searches = _plate_searches(store, device_id, lens_id)
    items = photographs(store, device_id, lens_id) if items is None else items
    every = [e for e in engravings(store, device_id, lens_id, material_id, items=items) if dot_width or e["settings"].get("dot_width") is None]
    kinds = list(WATCHED) + sorted({e["settings"]["dither"] for e in every} - set(WATCHED))
    best_dots = next((e for e in every if e["settings"]["dither"] != "grayscale" and _usable(e, dot_width)), None)
    out = []
    for kind in kinds:
        mine = [e for e in every if e["settings"]["dither"] == kind and _usable(e, dot_width)]
        flops = sorted((e for e in every if e["settings"]["dither"] == kind and failed(e)), key=lambda e: -max(e["photographs"]))
        top = mine[0] if mine else None
        search = next((s for s in searches if s["centre_kind"] == kind), None)
        if search is not None and search["report"]["settled"]:
            status, proposal = "settled", None
        elif search is not None:
            report = search["report"]
            status = "searching"
            proposal = {"kind": "next", "pair_id": search["pair_id"], "centre": report["next"]["centre"], "step": report["next"]["step"],
                        "best_label": report["best_label"]}
        elif top is not None:
            status = "measured"
            proposal = {"kind": "around", "centre": top["settings"], "step": 1.0, "source": top["source"]}
        elif kind != "grayscale" and best_dots is not None:
            status = "failed" if flops else "unmeasured"
            proposal = {"kind": "around", "centre": {**best_dots["settings"], "dither": kind}, "step": 1.0, "source": best_dots["source"]}
        else:
            status, proposal = "failed" if flops else "unmeasured", None
        picture = next((s for s in searches), None)
        if proposal is not None:
            proposal = _described(proposal, _variations_of(store, search["plan_id"] if proposal["kind"] == "next" else picture["plan_id"])
                                  if proposal["kind"] == "next" or picture is not None else None)
        out.append({"kind": kind, "status": status, "best": top, "engravings": len(mine) + len(flops), "failed": flops,
                    "effects": effects(store, device_id, lens_id, material_id, kind, items) if mine else {}, "proposal": proposal})
    picture = next((s for s in searches), None)
    return {"device_id": device_id, "lens_id": lens_id, "material_id": material_id, "kinds": out,
            "picture_from": None if picture is None else {"pair_id": picture["pair_id"], "plan_id": picture["plan_id"]}}


def everywhere(store: Store) -> list[dict]:
    """What is known of photo engraving on every laser, lens and titanium where one was photographed (the «Выводы» screen): the
    :func:`knowledge` of each, with the names of its laser and lens (``setup``) and its titanium."""
    out = []
    setups = store.query("SELECT DISTINCT p.device_id, p.lens_id, d.name AS laser, l.name AS lens FROM pair p JOIN laser_device d ON d.id=p.device_id "
                         "LEFT JOIN lens l ON l.id=p.lens_id WHERE p.status=? ORDER BY d.name, p.device_id, p.lens_id", (ingest.ST_ACCEPTED,))
    for row in setups:
        items = photographs(store, row["device_id"], row["lens_id"])
        for material_id in sorted({i["material_id"] for i in items if i["material_id"] is not None}):
            stock = store.one("SELECT name, grade, batch FROM material_profile WHERE id=?", (material_id,))
            out.append({**knowledge(store, row["device_id"], row["lens_id"], material_id, items),
                        "setup": f"{row['laser']} · {row['lens'] or 'линза неизвестна'}",
                        "titanium": " · ".join(x for x in (stock["name"], stock["grade"], stock["batch"]) if x) if stock else f"титан № {material_id}"})
    return out


def _plate_picture(store: Store, plan_id: int) -> tuple[bytes, dict, dict]:
    """The picture a photo-variations plate engraves (its file), its geometry's variations and its plate row."""
    plan = plans.get_plan(store, plan_id)
    plate = store.one("SELECT * FROM plate WHERE id=?", (plan["plate_id"],))
    variations = json.loads(plate["geometry_json"] or "{}").get("variations")
    path = (plan.get("pictures") or {}).get("variation")
    if not variations or not path or not Path(path).is_file():
        raise su.ValidationError("the picture of this plate is missing: make the plate from a photo work or zone")
    return Path(path).read_bytes(), variations, dict(plate)


def plate_around(store: Store, plan_id: int, centre: Mapping, step: float, follows: Mapping) -> dict:
    """A photo-variations plate of the picture of the plate of ``plan_id`` (where the picture came from kept), its copies one change each
    around ``centre`` (DEC-003); ``follows`` says why it was made."""
    png, variations, plate = _plate_picture(store, plan_id)
    settings = {k: centre[k] for k in ("dither", *KEYS) if centre.get(k) is not None}
    settings["variations"] = {"picture_png": png, "copy_mm": variations["copy_mm"], "picture_name": variations["picture"]["name"],
                              "step": step, "source": variations["picture"].get("source"), "follows": dict(follows)}
    return cp.create(store, plate["device_id"], plate["material_id"], "photo_variations", settings)


def next_plate(store: Store, pair_id: int) -> dict:
    """The next plate of a photographed photo-variations plate (DEC-003): the same picture, centred on its best copy, the changes halved."""
    pair = ingest.get_pair(store, pair_id)
    if pair["status"] != ingest.ST_ACCEPTED:
        raise su.ValidationError("accept the check of the plate first: the next plate is centred on its best copy")
    report = pair.get("variations")
    if not report:
        raise su.ValidationError("this check is not of a photo-variations plate, or none of its copies was measured")
    if report["next"] is None:
        raise su.ValidationError("the search has settled: the centre stayed the best at the smallest changes")
    made = plate_around(store, pair["plan_id"], report["next"]["centre"], report["next"]["step"],
                        {"kind": "next", "pair_id": pair_id, "best_copy": report["best"]})
    store.audit("photo_variations_next", pair_id=pair_id, plan_id=made["plan_id"], best_copy=report["best"], step=report["next"]["step"])
    return made


def proposed_plate(store: Store, device_id: int, lens_id: int | None, material_id: int | None, kind: str, *, dot_width: bool = True) -> dict:
    """The plate the laboratory proposes for ``kind`` (:func:`knowledge`), on the picture of the newest photographed variations plate;
    ``dot_width`` False: the plate proposed to a photo zone, around an engraving it can reproduce (DEC-005)."""
    known = knowledge(store, device_id, lens_id, material_id, dot_width=dot_width)
    entry = next((k for k in known["kinds"] if k["kind"] == kind), None)
    if entry is None or entry["proposal"] is None:
        raise su.ValidationError("no experiment is proposed for this kind")
    proposal = entry["proposal"]
    if proposal["kind"] == "next":
        return next_plate(store, proposal["pair_id"])
    if known["picture_from"] is None:
        raise su.ValidationError("no photo-variations plate was photographed yet: make the first from a photo work or zone "
                                 "(«Подобрать настройки: 8 копий»)")
    made = plate_around(store, known["picture_from"]["plan_id"], proposal["centre"], proposal["step"],
                        {"kind": "proposal", "for": kind, "from": proposal.get("source")})
    store.audit("photo_variations_proposed", kind=kind, plan_id=made["plan_id"])
    return made
