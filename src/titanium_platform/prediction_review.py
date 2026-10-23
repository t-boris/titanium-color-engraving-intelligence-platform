"""The prediction against the result: what the grey scale predicted for an accepted photo engraving before it was engraved and what its
photograph measured (DEC-117).

Each tonal layer of an accepted photograph is set beside the curve of its settings made from the engravings known BEFORE it (each
engraving is known from the first acceptance of any photograph of it, so measuring a photograph again does not move it after the
others), at its own row length, as the photo work showed it: ``prediction.curve_at``, the nearest measured size included when its size
lies outside them, never extrapolated. At each power it measured inside that curve: the colour predicted, the colour measured, their
difference (CIE76) and how much lighter (L*) and yellower (b*) the result came out.

What the prediction rested on is said as facts with their numbers, nothing is weighed or guessed (``causes``):

* ``size``: the row length against the sizes measured before it (measured, between two, outside them, unknown);
* ``plate``: the titanium plates the prediction's engravings were engraved on against this one, with their thickness (DEC-110 pools
  every plate of a grade);
* ``cleaning``: whether this file cleans the plate before the picture against the prediction's files;
* ``photo``: the clean titanium of this photograph against that of the prediction's photographs (each says whether it shows the same
  plate and cleaning) and of the other photographs of the same plate and cleaning at these settings: the cleaning witness where it was
  measured, else the lightest tone of the layer when it looks like clean titanium (``ingest``'s rule). On the same plate and cleaning a
  difference is the photograph's light, not the metal.

``summary`` gathers every review: the measure that a change of the model has to lower.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import colormap, composition, ingest, lightburn as lb, photo_modes, prediction, prediction_store as ps, work_review as wr
from .db import Store

TOLERANCE = 5.0                # ΔE: as the scale's confirmation (grayscale.confirmation)
SAME_LIGHT = wr.SYSTEMATIC_DL  # L*: clean titanium readings closer than this are the same light


def _known_since(store: Store) -> dict[str, str]:
    """When each engraving became known: the first acceptance of any photograph of it, a deleted or remeasured one included."""
    return {r["engraving_id"]: r["first"] for r in store.query(
        "SELECT engraving_id, MIN(accepted_at) AS first FROM pair WHERE accepted_at IS NOT NULL GROUP BY engraving_id")}


@lru_cache(maxsize=256)
def _file_cleans(path: str, stamp: int) -> bool | None:
    """Does a stored LightBurn file clean the plate before the rest (``composition.cleaning_layer``)? None when it cannot be read."""
    try:
        return composition.cleaning_layer(lb.parse_file(path).layers) is not None
    except (OSError, lb.LightBurnError):
        return None


def _cleans(check: dict, path: str | None) -> bool | None:
    """Whether a pair's file cleans the plate: as its check found it, else read again from the file (checks before the composition)."""
    found = check.get("composition")
    if found and "cleaning_layer" in found:
        return found["cleaning_layer"] is not None
    try:
        return _file_cleans(str(path), Path(path).stat().st_mtime_ns) if path else None
    except OSError:
        return None


def _mode(pair, rep: dict) -> ps.Mode | None:
    """The mode of a tonal layer of a check, as ``prediction_store.collect`` matches it; None for a layer without a tonal profile."""
    image = rep.get("image") or {}
    seen = photo_modes.mode(image.get("dither"))
    if not rep.get("tonal") or seen is None:
        return None
    dots = seen.key != prediction.PREDICTED_MODE
    return ps.Mode(device_id=pair["device_id"], lens_id=pair["lens_id"], material_id=pair["material_id"], speed=rep.get("speed"),
                   frequency=rep.get("frequency_khz"), pulse_width=rep.get("pulse_width"), line_interval=rep.get("line_interval"),
                   passes=rep.get("passes"), global_passes=rep.get("global_passes") or 1, dither=seen.key,
                   power=rep.get("power") if dots else None,
                   dot_width=image.get("dot_width_mm") if dots and image.get("dot_correction") else None)


def _of_kind(points: list[prediction.Point]) -> tuple[list[prediction.Point], bool | None]:
    """The points a curve is made of, as ``prediction_store.curve_for`` chooses them: chart-corrected ones when there are any, else
    those expressed against clean titanium when there are any, else all; and whether they are chart-corrected."""
    if not points:
        return [], None
    if any(p.referenced for p in points):
        return [p for p in points if p.referenced], True
    anchored = [p for p in points if p.source["reference"] == ps.CLEAN]
    return anchored or points, False


class _Pairs:
    """What a review needs to know of the pairs it names, read once: the plate, whether the file cleans and the clean titanium."""

    def __init__(self, store: Store):
        self.store = store
        self.witness = colormap.references(store)["witness"]
        self.plates = {r["id"]: {"id": r["id"], "name": r["name"], "thickness_mm": r["thickness_mm"]}
                       for r in store.query("SELECT id, name, thickness_mm FROM material_profile")}
        self._rows: dict[int, dict] = {}

    def row(self, pair_id: int) -> dict:
        if pair_id not in self._rows:
            r = self.store.one("SELECT id, material_id, photo_name, lightburn_path, data_json FROM pair WHERE id=?", (pair_id,))
            check = json.loads(r["data_json"] or "{}").get("check") or {}
            self._rows[pair_id] = {"id": r["id"], "material_id": r["material_id"], "photo": r["photo_name"],
                                   "cleans": _cleans(check, r["lightburn_path"])}
        return self._rows[pair_id]

    def plate(self, material_id) -> dict:
        return self.plates.get(material_id) or {"id": material_id, "name": None, "thickness_mm": None}

    def clean_titanium(self, pair_id: int, points: list[prediction.Point]) -> dict | None:
        """The clean titanium of a photograph: its cleaning witness, else the lightest tone of its points when it looks like clean
        titanium; None when neither."""
        witness = self.witness.get(pair_id)
        if witness is not None:
            lab = [float(v) for v in witness["lab"]]
            how = "witness"
        else:
            own = [p for p in points if p.source["pair_id"] == pair_id]
            if not own:
                return None
            lab = [float(v) for v in min(own, key=lambda p: p.power).lab]
            if not ingest._looks_like_clean_titanium(lab):
                return None
            how = "lightest"
        row = self.row(pair_id)
        return {"pair_id": pair_id, "photo": row["photo"], "L": round(lab[0], 1), "lab": [round(v, 2) for v in lab], "how": how}


def _mean_l(readings: list[dict]) -> float | None:
    return round(float(np.mean([r["L"] for r in readings])), 1) if readings else None


def _causes(pairs: _Pairs, pair_id: int, curve: prediction.Curve, before: list[prediction.Point], others: list[prediction.Point],
            own: list[prediction.Point]) -> list[dict]:
    used = sorted({s["pair_id"] for row in curve.points for s in row["sources"]})
    me = pairs.row(pair_id)
    plates = sorted({pairs.row(u)["material_id"] for u in used}, key=lambda m: (m is None, m))
    cleaning = [{"pair_id": u, "photo": pairs.row(u)["photo"], "cleans": pairs.row(u)["cleans"]} for u in used]
    known = [c["cleans"] for c in cleaning if c["cleans"] is not None]
    mine = pairs.clean_titanium(pair_id, own)
    surface = lambda u: pairs.row(u)["material_id"] == me["material_id"] and pairs.row(u)["cleans"] == me["cleans"]   # noqa: E731
    used_light = [{**r, "same_surface": surface(u)} for u in used if (r := pairs.clean_titanium(u, before)) is not None]
    same = sorted({p.source["pair_id"] for p in others if p.source["pair_id"] not in used and surface(p.source["pair_id"])})
    same_light = [r for u in same if (r := pairs.clean_titanium(u, others)) is not None]
    photo = {"code": "photo", "own": mine, "used": used_light, "same_surface": same_light, "dL_used": None, "dL_same": None, "differs": False}
    if mine is not None:
        if used_light:
            photo["dL_used"] = round(mine["L"] - _mean_l(used_light), 1)
        if same_light:
            photo["dL_same"] = round(mine["L"] - _mean_l(same_light), 1)
        photo["differs"] = any(d is not None and abs(d) >= SAME_LIGHT for d in (photo["dL_used"], photo["dL_same"]))
    return [{"code": "size", **dict(curve.size), "differs": curve.size["how"] != prediction.MEASURED},
            {"code": "plate", "own": pairs.plate(me["material_id"]), "used": [pairs.plate(m) for m in plates],
             "differs": any(m != me["material_id"] for m in plates)},
            {"code": "cleaning", "own": me["cleans"], "used": cleaning,
             "differs": me["cleans"] is not None and any(k != me["cleans"] for k in known)},
            photo]


def _layer(store: Store, pairs: _Pairs, pair, rep: dict, known: dict[str, str], tolerance: float) -> dict | None:
    mode = _mode(pair, rep)
    if mode is None:
        return None
    out = {"layer": rep["index"], "name": rep.get("name"), "kind": mode.dither, "mode": mode.as_dict(), "row_mm": None, "reason": None,
           "engravings": 0, "compared": 0, "median_de": None, "max_de": None, "within": None, "median_dL": None, "median_db": None,
           "bands": [], "causes": [], "tolerance_de": tolerance}
    points = ps.collect(store, mode)["points"]
    own = [p for p in points if p.source["pair_id"] == pair["id"] and p.source["layer"] == rep["index"]]
    if not own:
        out["reason"] = "no_points"                           # a weak profile or one over fills: not measured as a scale
        return out
    since = known.get(pair["engraving_id"], pair["accepted_at"])
    others = [p for p in points if p.source.get("engraving_id") != pair["engraving_id"]]
    before, referenced = _of_kind([p for p in others if known.get(p.source.get("engraving_id"), "") < since])
    out["row_mm"] = own[0].source.get("row_mm")
    if not before:
        out["reason"] = "first"
        return out
    own = [p for p in own if p.referenced == referenced and (referenced or p.source["reference"] == before[0].source["reference"])]
    if not own:
        out["reason"] = "kind"
        return out
    axis = prediction.POWER_AXIS if mode.dither == prediction.PREDICTED_MODE else prediction.TONE_AXIS
    curve = prediction.curve_at(before, out["row_mm"], axis=axis)
    own.sort(key=lambda p: p.power)
    predicted = curve.lab_at(np.array([p.power for p in own]))
    inside = np.isfinite(predicted[:, 0])
    out["engravings"] = len({prediction._engraving_of(s) for row in curve.points for s in row["sources"]})
    out["causes"] = _causes(pairs, pair["id"], curve, before, others, own)
    if not inside.any():
        out["reason"] = "outside"                             # its powers lie outside the powers measured before it
        return out
    measured = np.array([p.lab for p in own])[inside]
    diff = measured - predicted[inside]
    de = np.linalg.norm(diff, axis=1)
    out.update(compared=int(inside.sum()), median_de=round(float(np.median(de)), 1), max_de=round(float(de.max()), 1),
               within=round(float(np.mean(de <= tolerance)), 3), median_dL=round(float(np.median(diff[:, 0])), 1),
               median_db=round(float(np.median(diff[:, 2])), 1),
               bands=[{"power": round(p.power, 2), "gray": p.source.get("gray"), "lab": [round(float(v), 2) for v in lab],
                       "predicted": [round(float(v), 2) for v in guess], "de": round(float(d), 1)}
                      for p, lab, guess, d in zip([p for p, keep in zip(own, inside) if keep], measured, predicted[inside], de)])
    return out


def review(store: Store, pair_id: int, tolerance: float = TOLERANCE) -> dict:
    """The review of one accepted photograph: each of its tonal layers against the prediction made before it (see the module)."""
    pair = ingest._pair_row(store, pair_id)
    out = {"pair_id": pair_id, "photo": pair["photo_name"], "accepted": pair["status"] == ingest.ST_ACCEPTED, "tolerance_de": tolerance, "layers": []}
    if not out["accepted"]:
        return out
    check = json.loads(pair["data_json"] or "{}").get("check") or {}
    pairs, known = _Pairs(store), _known_since(store)
    out["layers"] = [found for rep in check.get("layers", []) if (found := _layer(store, pairs, pair, rep, known, tolerance)) is not None]
    return out


def summary(store: Store, tolerance: float = TOLERANCE) -> dict:
    """Every accepted photograph's review together: how many layers were compared, the median and the share within ``tolerance`` of
    every tone compared, and the same for the layers whose size was measured before them. Made once per state of the data: every
    experiment page asks for it."""
    return _summary(store, store.stamp(), tolerance)


@lru_cache(maxsize=4)
def _summary(store: Store, stamp: tuple[int, int], tolerance: float) -> dict:
    rows = store.query("SELECT id, data_json FROM pair WHERE status='Accepted' ORDER BY id")
    reviewed = []
    for r in rows:
        layers = (json.loads(r["data_json"] or "{}").get("check") or {}).get("layers", [])
        if any(rep.get("tonal") for rep in layers):
            reviewed += [{"pair_id": r["id"], **layer} for layer in review(store, r["id"], tolerance)["layers"] if layer["compared"]]

    def of(layers: list[dict]) -> dict:
        every = [b["de"] for layer in layers for b in layer["bands"]]
        return {"layers": len(layers), "engravings": len({layer["pair_id"] for layer in layers}), "tones": len(every),
                "median_de": round(float(np.median(every)), 1) if every else None,
                "within": round(float(np.mean(np.array(every) <= tolerance)), 3) if every else None}

    measured = [layer for layer in reviewed if next(c for c in layer["causes"] if c["code"] == "size")["how"] == prediction.MEASURED]
    return {"tolerance_de": tolerance, "all": of(reviewed), "size_measured": of(measured),
            "layers": [{k: layer[k] for k in ("pair_id", "layer", "name", "row_mm", "compared", "median_de", "within")} for layer in reviewed]}
