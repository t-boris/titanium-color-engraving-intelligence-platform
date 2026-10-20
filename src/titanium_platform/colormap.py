"""One general colour map (REQ-029, DEC-056): every colour measured in every kept experiment, with the settings that gave it
and where it came from, so that a wanted colour can be looked up without going through the experiments.

Colours measured against a reference chart are absolute (CIE Lab). Colours measured without one are relative to their camera and
cannot be compared between photographs, so each is expressed against the cleaned titanium of the *same* photograph (the cleaning
witness): the ratio of the two in linear light does not depend on the exposure, and multiplied with the nominal clean titanium it
gives the colour shown. They are marked approximate. A colour with no witness has no
reference: it is still on the map, as it was photographed and flagged ``referenced: false``, but it takes no part in the search
unless asked, because its distance to the other colours would mean nothing (operator, 2026-10-16).

A checked pair that is not accepted yet shows its measured layers too, marked provisional and linked to its review (DEC-045,
REQ-020): only when its alignment is valid and layers were measured. Provisional colours take part in no search unless the
search asks for them, and in no prediction; deleted pairs never show.

The search returns one entry per recipe: the settings, the laser and lens records, the titanium stock record, how the colour was
measured (chart, against clean titanium, as photographed), whether it is provisional and its engraving task (REQ-020: a
filled text and a filled area of the same settings are two entries); colours of different kinds are never pooled into one
entry. An entry is observed evidence, never a prediction: it links its observations, counts independent engravings
(re-photographs of one engraving count once, DEC-021) and photographs separately, says how far its engravings agree when
there are several, and names the context it lacks (an unknown lens or batch, camera-relative or unreferenced colours,
provisional checks, settings missing from the file).

Every colour and every entry carries the estimated engraving time of its recipe (REQ-035, DEC-075): seconds per square
centimetre, or per centimetre of path for a Line-mode recipe, labelled an estimate. The map can be narrowed to recipes no
slower than a time per square centimetre, and within the delta E tolerance the search puts the fastest recipe first.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import agreement, color, engraving_time, experiments, ingest, lightburn as lb, model, tasks
from . import setup as su
from .db import Store

DEFAULT_CLEAN = [68.0, 0.0, 2.0]          # cleaned titanium when no photograph with a chart has measured it yet
SERVICE = ("registration, QR and engraved labels",)
WITNESS = "pre-test cleaning witness"
PENDING = ("Accepted", "Deleted")         # statuses that are not a check awaiting acceptance


def _rows(store: Store):
    return store.query(
        "SELECT o.id, o.pair_id, o.layer_index, o.lab_json, o.parameters_json, o.model_eligible, o.alignment_method, o.evidence_json, "
        "o.task_kind, p.plan_id, p.engraving_id, p.engraving_title, p.photo_name, p.lightburn_name, p.accepted_at, p.created_at AS pair_created, "
        "p.device_id, p.lens_id, p.material_id, "
        "p.hardware_json, p.context_json AS pair_context, p.lightburn_path, pl.status AS plan_status "
        "FROM observation o JOIN pair p ON p.id=o.pair_id LEFT JOIN plan pl ON pl.id=p.plan_id "
        "WHERE p.status!='Deleted' ORDER BY o.pair_id, o.layer_index")


@lru_cache(maxsize=64)
def _cleaning_layer(path: str, stamp: int) -> int | None:
    """The cleaning layer of a finished work, found again from its stored LightBurn file (DEC-056); None if there is none."""
    from .ingest import _finished_work_cleaning_layer     # noqa: F811 (same module, imported at call time to keep the cache simple)
    try:
        return _finished_work_cleaning_layer(lb.parse_file(path))
    except (OSError, lb.LightBurnError):
        return None


def _names(store: Store) -> tuple[dict[int, str], dict[int, str]]:
    """The titles of the lasers and the names of the lenses, by record id."""
    from .devices import display_title
    lasers = {r["id"]: display_title(r["name"], r["serial"]) for r in store.query("SELECT id, name, serial FROM laser_device")}
    return lasers, {r["id"]: r["name"] for r in store.query("SELECT id, name FROM lens")}


def _source_of_row(row) -> dict:
    return {"plan_id": row["plan_id"], "engraving_id": row["engraving_id"], "engraving_title": row["engraving_title"],
            "lightburn_name": row["lightburn_name"], "photo_name": row["photo_name"], "date": row["accepted_at"] or row["pair_created"],
            "context": json.loads(row["pair_context"] or "{}"), "device_id": row["device_id"], "lens_id": row["lens_id"],
            "material_id": row["material_id"]}


def _source_of_pair(pair: dict) -> dict:
    return {"plan_id": pair.get("plan_id"), "engraving_id": pair["engraving_id"], "engraving_title": pair.get("engraving_title"),
            "lightburn_name": pair["lightburn_name"], "photo_name": pair["photo_name"], "date": pair.get("accepted_at") or pair["created_at"],
            "context": pair.get("context") or {}, "device_id": pair["device_id"], "lens_id": pair["lens_id"], "material_id": pair.get("material_id")}


def _pair_info(source: dict, names: tuple[dict[int, str], dict[int, str]], kept: set[int]) -> dict:
    """Where a colour came from. The laser and lens are its records (DEC-063): ``setup`` is their key, so two units with
    the same name stay apart, and the names are only the label. The titanium is its stock record (``material_id``)."""
    context = source["context"]
    laser, lens = names[0].get(source["device_id"]), names[1].get(source["lens_id"])
    material = " · ".join(x for x in (context.get("titanium_name"), context.get("titanium_grade")) if x) or None
    key = experiments.plan_key(source["plan_id"]) if source["plan_id"] in kept else experiments.engraving_key(source["engraving_id"])
    return {"experiment": key, "title": source["engraving_title"] or source["lightburn_name"].rsplit(".", 1)[0], "photo": source["photo_name"],
            "date": source["date"], "laser": laser, "lens": lens, "engraving_id": source["engraving_id"],
            "device_id": source["device_id"], "lens_id": source["lens_id"], "setup": su.setup_key(source["device_id"], source["lens_id"]),
            "setup_label": f"{laser} · {lens or 'линза неизвестна'}", "material": material, "material_id": source["material_id"],
            "batch": context.get("batch")}


_against_clean = color.against_clean


def nominal_clean(store: Store) -> tuple[list[float], str]:
    """Clean titanium as a photograph with a chart measured it (median over such witnesses), else the default; and its source."""
    calibrated = []
    for row in _rows(store):
        evidence = json.loads(row["evidence_json"] or "{}")
        if (evidence.get("role") == WITNESS or row["layer_index"] == -1) and _kind(evidence, row["model_eligible"]) == "calibrated":
            calibrated.append(json.loads(row["lab_json"]))
    if calibrated:
        return [float(v) for v in np.median(np.array(calibrated), axis=0)], "chart"
    return list(DEFAULT_CLEAN), "default"


def _kind(evidence: dict, eligible: int) -> str:
    mode = (evidence.get("color_measurement") or {}).get("mode")
    return "calibrated" if mode == "reference_chart_corrected" or (mode is None and eligible) else "relative"


def references(store: Store) -> dict:
    """The accepted observations with the clean titanium of each photograph (DEC-056): ``witness`` by pair id (lab, kind),
    ``derived`` the cleaning layer found again from the stored file of works accepted before it was recognised, and the
    ``nominal`` clean titanium every camera-relative colour is expressed against."""
    rows = list(_rows(store))
    witness: dict[int, dict] = {}
    for row in rows:
        evidence = json.loads(row["evidence_json"] or "{}")
        if evidence.get("role") == WITNESS or row["layer_index"] == -1:
            witness[row["pair_id"]] = {"lab": json.loads(row["lab_json"]), "kind": _kind(evidence, row["model_eligible"])}
    # Works accepted before the cleaning layer was recognised have no witness observation: find the layer again in the stored file.
    derived: dict[int, int] = {}
    for row in rows:
        if row["pair_id"] in witness or (row["plan_id"] and row["plan_status"] != "Restored") or row["pair_id"] in derived:
            continue
        try:
            stamp = Path(row["lightburn_path"]).stat().st_mtime_ns
        except OSError:
            continue
        layer = _cleaning_layer(row["lightburn_path"], stamp)
        if layer is not None:
            derived[row["pair_id"]] = layer
    for row in rows:
        if derived.get(row["pair_id"]) == row["layer_index"] and row["pair_id"] not in witness:
            evidence = json.loads(row["evidence_json"] or "{}")
            witness[row["pair_id"]] = {"lab": json.loads(row["lab_json"]), "kind": _kind(evidence, row["model_eligible"]), "layer": row["layer_index"]}
    calibrated_clean = [w["lab"] for w in witness.values() if w["kind"] == "calibrated"]
    nominal = [float(v) for v in np.median(np.array(calibrated_clean), axis=0)] if calibrated_clean else list(DEFAULT_CLEAN)
    return {"rows": rows, "witness": witness, "derived": derived, "nominal": nominal, "nominal_source": "chart" if calibrated_clean else "default"}


def is_service(role: str | None, layer_index: int, cleaning_layer: int | None = None) -> bool:
    """Registration and labels, the cleaning witness (or the cleaning layer found from the file): not colours of a recipe."""
    return role in SERVICE or role == WITNESS or layer_index == -1 or (cleaning_layer is not None and layer_index == cleaning_layer)


def expressed(lab: list[float], kind: str, clean: list[float] | None, nominal: list[float]) -> tuple[list[float], bool, bool]:
    """The colour as it is shown and compared, whether it is approximate and whether it has a reference: absolute when
    measured against a chart, against the clean titanium of its own photograph when that exists, else as photographed."""
    if kind == "calibrated":
        return lab, False, True
    if clean is not None:
        return _against_clean(lab, clean, nominal), True, True
    return lab, True, False


def layer_parameters(rep: dict) -> dict:
    """The settings of a measured layer of a check, as acceptance stores them with its observation."""
    return {"power": rep.get("power"), "frequency": rep.get("frequency_khz"), "speed": rep.get("speed"), "pulse_width": ingest.effective_setting(rep, "pulse_width"),
            "line_interval": rep.get("line_interval"), "passes": rep.get("passes"), "layer_type": rep.get("type"),
            "global_passes": rep.get("global_passes"), "bidirectional": rep.get("bidirectional"), "cross_hatch": rep.get("cross_hatch"),
            "scan_angle": rep.get("scan_angle"), "angle_increment": rep.get("angle_increment"),
            "source_settings": lb.recipe_settings(rep.get("source_settings"))}


SHOWN_PARAMETERS = ("power", "frequency", "speed", "pulse_width", "line_interval", "passes", "layer_type", "global_passes", "bidirectional",
                    "cross_hatch", "scan_angle")


def _group(params: dict, info: dict, kind: str, referenced: bool, provisional: bool, task: dict, tonal: bool = False) -> str:
    """One recipe of the search: the settings, the laser and lens records, the titanium stock record, how the colour was measured,
    whether it is provisional and its engraving task; colours that differ in any of these are never one entry (REQ-020, REQ-029)."""
    basis = "chart" if kind == "calibrated" else "clean" if referenced else "as-shot"
    return "|".join((model.parameters_key(params), "tonal" if tonal else "layer", info["setup"], f"ti:{info['material_id'] or 'unknown'}",
                     basis, "provisional" if provisional else "accepted", f"task:{task['kind']}"))


def _time(params: dict) -> dict:
    """The estimated engraving time of a point's recipe from its full settings (DEC-075)."""
    time = engraving_time.of_recipe(params)
    return {"time": time, "time_s_per_cm2": time["s_per_cm2"], "time_s_per_cm": time["s_per_cm"]}


def time_limit(value) -> float | None:
    """The longest time per square centimetre a filter allows, in seconds; None: no limit."""
    if value is None:
        return None
    try:
        limit = float(value)
    except (TypeError, ValueError):
        limit = math.nan
    if not math.isfinite(limit) or limit <= 0:
        raise su.ValidationError("the longest engraving time per square centimetre must be a positive number of seconds")
    return limit


def _task(task: dict) -> dict:
    """The task of a point: its kind and whether it was stated or derived from the layer."""
    return {"kind": task["kind"], "basis": task.get("basis", tasks.DERIVED)}


def _tonal_points(pair_id: int, check: dict, info: dict, kind: str, clean, nominal, provisional: bool,
                  observations: dict | None = None) -> list[dict]:
    """A grayscale-mode image is a continuum of recipes: the grey level sets the power and the power sets the colour. Each step of
    its tonal profile is a colour with the settings of that power (DEC-056); its evidence is the observation of its image layer
    (``observations`` by layer name), none while the check is provisional."""
    out = []
    for rep in check.get("layers", []):
        tonal = rep.get("tonal")
        if not tonal or tonal.get("evidence") != "clear" or not tonal.get("power_range"):
            continue
        for step in tonal["bins"]:
            if "power_pct" not in step:
                continue
            lab = [step["L"], step["a"], step["b"]]
            display, approximate, referenced = expressed(lab, kind, clean, nominal)
            params = {"power": step["power_pct"], "frequency": rep.get("frequency_khz"), "speed": rep.get("speed"),
                      "pulse_width": ingest.effective_setting(rep, "pulse_width"), "line_interval": rep.get("line_interval"), "passes": rep.get("passes"),
                      "layer_type": "Image", "grayscale": True}
            task = _task(rep.get("task") or tasks.derive_from_parameters(params))
            out.append({"id": f"tonal-{pair_id}-{rep['index']}-{step['gray']}", "pair_id": pair_id, "layer_index": rep["index"],
                        "layer_name": f"{rep.get('name')} · серый {step['gray']:.2f}", "measurement": kind, "approximate": approximate,
                        "referenced": referenced, "provisional": provisional, "lab": lab, "delta": None, "display_lab": display,
                        "parameters": params, "source": "tonal", "task": task, **_time(params),
                        "observation_ids": [observations[rep.get("name")]] if rep.get("name") in (observations or {}) else [],
                        "group": _group(params, info, kind, referenced, provisional, task, tonal=True), **info})
    return out


def collect(store: Store, include_unreferenced: bool = True, setup: str | None = None, material: str | None = None,
            measurement: str | None = None, include_provisional: bool = True, task: str | None = None,
            max_time_s_per_cm2: float | None = None) -> dict:
    """Every colour of the map. Filters narrow the points (``setup`` is the key of a laser and lens, ``laser:1/lens:2``;
    ``task`` an engraving task, REQ-020; ``max_time_s_per_cm2`` the longest estimated time per square centimetre, which
    leaves out slower recipes and those with no time per area, counted as ``slower``, REQ-035); the options describe
    everything that exists."""
    if task is not None:
        tasks.require(task)
    limit = time_limit(max_time_s_per_cm2)
    refs = references(store)
    rows, witness, derived, nominal = refs["rows"], refs["witness"], refs["derived"], refs["nominal"]
    kept, names = experiments.kept_plan_ids(store), _names(store)

    points = []
    observations: dict[int, dict[str, int]] = {}
    for row in rows:
        evidence = json.loads(row["evidence_json"] or "{}")
        observations.setdefault(row["pair_id"], {}).setdefault(evidence.get("layer_name"), row["id"])
        if is_service(evidence.get("role"), row["layer_index"], derived.get(row["pair_id"])):
            continue
        info = _pair_info(_source_of_row(row), names, kept)
        lab = json.loads(row["lab_json"])
        kind = _kind(evidence, row["model_eligible"])
        ref = witness.get(row["pair_id"])
        delta = [lab[i] - ref["lab"][i] for i in range(3)] if ref else None
        display, approximate, referenced = expressed(lab, kind, ref["lab"] if ref else None, nominal)
        params = json.loads(row["parameters_json"] or "{}")
        point_task = _task(tasks.of_observation(row))
        points.append({"id": row["id"], "pair_id": row["pair_id"], "layer_index": row["layer_index"], "layer_name": evidence.get("layer_name"),
                       "measurement": kind, "approximate": approximate, "referenced": referenced, "provisional": False, "lab": lab, "delta": delta,
                       "display_lab": display, "parameters": {k: params.get(k) for k in SHOWN_PARAMETERS}, "task": point_task,
                       "observation_ids": [row["id"]], "group": _group(params, info, kind, referenced, False, point_task), **_time(params),
                       **info})
    first_row = {}
    for row in rows:
        first_row.setdefault(row["pair_id"], row)
    for pair_id, row in first_row.items():
        check = ingest.get_pair(store, pair_id).get("check") or {}
        kind = "calibrated" if (check.get("color_measurement") or {}).get("mode") == "reference_chart_corrected" else "relative"
        ref = witness.get(pair_id)
        points += _tonal_points(pair_id, check, _pair_info(_source_of_row(row), names, kept), kind, ref["lab"] if ref else None, nominal, False,
                                observations.get(pair_id))
    points += _provisional_points(store, names, kept, nominal)

    setups, materials, kinds = {}, set(), set()
    for p in points:
        setups[p["setup"]] = p
        kinds.add(p["task"]["kind"])
        if p["material"]:
            materials.add(p["material"])
    shown = [p for p in points if (setup is None or p["setup"] == setup) and (material is None or p["material"] == material)
             and (measurement is None or p["measurement"] == measurement) and (task is None or p["task"]["kind"] == task)]
    slower = 0
    if limit is not None:
        fast = [p for p in shown if p["time_s_per_cm2"] is not None and p["time_s_per_cm2"] <= limit]
        slower, shown = len(shown) - len(fast), fast
    provisional = sum(p["provisional"] for p in shown)
    if not include_provisional:
        shown = [p for p in shown if not p["provisional"]]
    unreferenced = sum(not p["referenced"] for p in shown)
    if not include_unreferenced:
        shown = [p for p in shown if p["referenced"]]
    return {"points": shown, "nominal_clean": {"lab": nominal, "source": refs["nominal_source"]},
            "options": {"setups": sorted(({"key": key, "label": info["setup_label"], "device_id": info["device_id"], "lens_id": info["lens_id"]}
                                          for key, info in setups.items()), key=lambda o: (o["label"], o["key"])),
                        "materials": sorted(materials), "tasks": [k for k in tasks.TASKS if k in kinds]},
            "counts": {"calibrated": sum(p["measurement"] == "calibrated" for p in shown),
                       "relative": sum(p["measurement"] == "relative" for p in shown), "unreferenced": unreferenced,
                       "provisional": provisional, "slower": slower}}


def _provisional_points(store: Store, names, kept: set[int], nominal: list[float]) -> list[dict]:
    """The measured layers of checked pairs awaiting acceptance (DEC-045): only a valid alignment with measured layers counts."""
    out = []
    marks = ",".join("?" * len(PENDING))
    for row in store.query(f"SELECT id FROM pair WHERE status NOT IN ({marks}) ORDER BY id", PENDING):
        pair = ingest.get_pair(store, row["id"])
        check = pair.get("check") or {}
        measured = [rep for rep in check.get("layers", []) if rep.get("measured_lab")]
        if not (check.get("alignment") or {}).get("valid") or not measured:
            continue
        kind = "calibrated" if (check.get("color_measurement") or {}).get("mode") == "reference_chart_corrected" else "relative"
        clean = next((rep["measured_lab"] for rep in measured if rep.get("role") == WITNESS), None)
        info = {**_pair_info(_source_of_pair(pair), names, kept), "review": f"/ingest?pair={pair['id']}"}
        for rep in measured:
            if is_service(rep.get("role"), rep["index"]):
                continue
            lab = [float(v) for v in rep["measured_lab"]]
            display, approximate, referenced = expressed(lab, kind, clean, nominal)
            params = layer_parameters(rep)
            point_task = _task(rep.get("task") or tasks.derive_from_parameters(params, rep.get("role")))
            out.append({"id": f"provisional-{pair['id']}-{rep['index']}", "pair_id": pair["id"], "layer_index": rep["index"],
                        "layer_name": rep.get("name"), "measurement": kind, "approximate": approximate, "referenced": referenced,
                        "provisional": True, "lab": lab, "delta": [lab[i] - clean[i] for i in range(3)] if clean else None,
                        "display_lab": display, "parameters": {k: params.get(k) for k in SHOWN_PARAMETERS}, "task": point_task,
                        "observation_ids": [], "group": _group(params, info, kind, referenced, True, point_task), **_time(params),
                        **info})
        out += _tonal_points(pair["id"], check, info, kind, clean, nominal, True)
    return out


def by_recipe(points: list[dict]) -> dict[str, dict]:
    """The points of each recipe (one entry of the search) with its evidence: the colours of each independent engraving (a
    re-photograph counts once, DEC-021), when each was made (its latest photograph; the observation id breaks a tie), its
    photographs, experiments and observations."""
    out: dict[str, dict] = {}
    for point in points:
        entry = out.setdefault(point["group"], {"points": [], "engravings": {}, "when": {}, "photographs": set(), "experiments": [],
                                                "observation_ids": []})
        entry["points"].append(point)
        entry["engravings"].setdefault(point["engraving_id"], []).append(point["display_lab"])
        entry["when"][point["engraving_id"]] = max(entry["when"].get(point["engraving_id"], ("", 0)),
                                                   (point.get("date") or "", max(point["observation_ids"], default=0)))
        entry["photographs"].add(point["pair_id"])
        entry["observation_ids"] += [i for i in point["observation_ids"] if i not in entry["observation_ids"]]
        if point["experiment"] not in entry["experiments"]:
            entry["experiments"].append(point["experiment"])
    return out


def agreed(recipe: dict) -> dict:
    """The agreed colour of a recipe of :func:`by_recipe` and the confidence in it (REQ-045, DEC-083): :func:`agreement.consensus`
    over the mean colour of each independent engraving, which are also returned as ``means`` in the order of ``engravings``."""
    means = [np.mean(np.asarray(labs, float), axis=0) for labs in recipe["engravings"].values()]
    found = agreement.consensus([{"lab": mean, "when": recipe["when"].get(engraving)} for mean, engraving in zip(means, recipe["engravings"])])
    return {**found, "means": means}


def sources_of(recipe: dict, found: dict) -> list[dict]:
    """Where the colour of a recipe is known from (REQ-049): one entry per independent engraving, the newest first, with the experiment
    and photographs it was measured in, its own colour, how far that is from the agreed colour and whether it is one of the engravings
    the agreed colour is made of. ``found`` is :func:`agreed` of the same recipe."""
    out = []
    for i, (engraving, mean) in enumerate(zip(recipe["engravings"], found["means"])):
        points = [p for p in recipe["points"] if p["engraving_id"] == engraving]
        out.append({"engraving_id": engraving, "experiment": points[0]["experiment"], "title": points[0]["title"],
                    "date": recipe["when"][engraving][0] or None, "pair_ids": sorted({p["pair_id"] for p in points}),
                    "photos": sorted({p["photo"] for p in points if p.get("photo")}),
                    "layers": [name for name in dict.fromkeys(p.get("layer_name") for p in points) if name],
                    "observation_ids": sorted({i for p in points for i in p["observation_ids"]}),
                    "lab": [round(float(v), 1) for v in mean], "delta_e": round(float(color.delta_e(found["lab"], mean)), 2),
                    "agrees": i in found["members"], "measurement": points[0]["measurement"],
                    "provisional": any(p["provisional"] for p in points)})
    return sorted(out, key=lambda e: (e["date"] or "", e["engraving_id"]), reverse=True)


def annotate(points: list[dict], recipes: dict | None = None) -> list[dict]:
    """Give every point the confidence of its recipe, in place (REQ-045): ``trust`` (0..1, always a number: what the map draws the
    circle's diameter by), ``confidence`` (None while the recipe was engraved once), ``agreement``, ``caution`` and ``doubtful`` (the
    circle is smaller than that of one engraving, REQ-049). When ``recipes`` is a dict it receives, by group, the agreed colour and the
    sources of each recipe engraved more than once; a recipe engraved once is its own source and is told by its point."""
    for group, recipe in by_recipe(points).items():
        found = agreed(recipe)
        shown = {"trust": found["trust"], "confidence": found["confidence"], "agreement": agreement.shown(found),
                 "caution": "contradicted" if found["contradicted"] else None, "doubtful": agreement.doubtful(found)}
        for point in recipe["points"]:
            point.update(shown)
        if recipes is not None and found["engravings"] > 1:
            recipes[group] = {"lab": [round(v, 1) for v in found["lab"]], "sources": sources_of(recipe, found)}
    return points


def hide_doubtful(data: dict) -> dict:
    """The colour map without the colours of doubtful recipes (REQ-049): the points left out are counted in ``counts.doubtful``, and the
    counts of calibrated and camera-relative colours follow what is shown. ``data`` is :func:`collect` after :func:`annotate`."""
    kept = [p for p in data["points"] if not p["doubtful"]]
    counts = {**data["counts"], "calibrated": sum(p["measurement"] == "calibrated" for p in kept),
              "relative": sum(p["measurement"] == "relative" for p in kept), "doubtful": len(data["points"]) - len(kept)}
    return {**data, "points": kept, "counts": counts}


def delta_tolerance(value) -> float:
    """A delta E tolerance given by the operator: a non-negative number."""
    try:
        tolerance = float(value)
    except (TypeError, ValueError):
        tolerance = math.nan
    if not math.isfinite(tolerance) or tolerance < 0:
        raise su.ValidationError("the delta E tolerance must be a non-negative number")
    return tolerance


def _search_tolerance(store: Store, data: dict, tolerance_de, setup: str | None) -> tuple[float | None, str | None]:
    """The delta E tolerance of a search and where it comes from: the request's, else the saved rule of the one laser and
    lens the search is narrowed to; none otherwise (a tolerance is never invented)."""
    if tolerance_de is not None:
        return delta_tolerance(tolerance_de), "request"
    option = next((o for o in data["options"]["setups"] if setup is not None and o["key"] == setup), None)
    saved = su.get_rules(store, option["device_id"], option["lens_id"])["delta_tolerance"] if option else None
    return (float(saved), "rules") if saved is not None else (None, None)


def fastest_first(entries: list[dict], tolerance: float | None) -> list[dict]:
    """Entries (each with its ``distance``, the ``time_s_per_cm2`` of its recipe and, when it has one, its ``confidence``) in the
    order of DEC-083 and DEC-075: within the tolerance the most confident recipe first, among equally confident ones the fastest
    (those with no time per area after the timed ones, the nearer first among equals), then every other entry by distance.
    Without a tolerance: by distance."""
    if tolerance is None:
        return sorted(entries, key=lambda e: e["distance"])
    within = [e for e in entries if e["distance"] <= tolerance]
    rest = [e for e in entries if e["distance"] > tolerance]
    return (sorted(within, key=lambda e: (-agreement.trust(e), math.inf if e["time_s_per_cm2"] is None else e["time_s_per_cm2"], e["distance"]))
            + sorted(rest, key=lambda e: e["distance"]))


def search(store: Store, lab: list[float], limit: int = 12, include_unreferenced: bool = False, include_provisional: bool = False,
           tolerance_de: float | None = None, hide_doubtful: bool = False, **filters) -> dict:
    """The recipes whose colour is nearest to ``lab``: one entry per recipe, with how many independent engravings gave it, in how
    many photographs, and from which experiments. Colours without a clean reference and provisional colours are left out unless
    asked for; their numbers are returned. Every entry is observed evidence (REQ-020): it links its observations and the checks
    it came from, says how far its independent engravings agree when there are several, and names the context it lacks.

    The colour of an entry, and its distance to the wanted colour, is the colour its independent engravings agree on, not the nearest
    single measurement (DEC-083); ``confidence``, ``agreement`` (how many engravings agree) and ``caution`` (``contradicted``) say how
    far to trust it. Within the delta E tolerance (``tolerance_de``, else the saved rule of the laser and lens the search is narrowed
    to) the most confident recipe comes first, then the fastest (DEC-083, DEC-075); ``order`` says how the entries were ordered and
    with which tolerance. Each entry names its ``sources``, the engravings its colour is known from, and says whether it is ``doubtful``;
    with ``hide_doubtful`` the doubtful ones are left out and counted in ``counts.doubtful`` (REQ-049)."""
    data = collect(store, include_unreferenced=include_unreferenced, include_provisional=include_provisional, **filters)
    entries, doubtful = [], 0
    for entry in by_recipe(data["points"]).values():
        found = agreed(entry)
        if agreement.doubtful(found):
            doubtful += 1
            if hide_doubtful:
                continue
        agreeing = {engraving for engraving, i in zip(entry["engravings"], range(len(found["means"]))) if i in found["members"]}
        # the point that stands for the recipe: of an engraving that agrees, the nearest to the agreed colour, the newer one first
        stand = min((p for p in entry["points"] if p["engraving_id"] in agreeing),
                    key=lambda p: (color.delta_e(found["lab"], p["display_lab"]), -max(p["observation_ids"], default=0)))
        entries.append({**entry, "best": {**stand, "display_lab": found["lab"]}, "distance": color.delta_e(lab, found["lab"]),
                        "time_s_per_cm2": stand["time_s_per_cm2"], "confidence": found["confidence"], "found": found})
    tolerance, source = _search_tolerance(store, data, tolerance_de, filters.get("setup"))
    ranked = fastest_first(entries, tolerance)[:limit]
    return {"target": lab, "evidence": "observed",
            "order": {"by": "distance" if tolerance is None else "time_within_tolerance", "tolerance_de": tolerance,
                      "tolerance_source": source,
                      "within_tolerance": None if tolerance is None else sum(e["distance"] <= tolerance for e in entries)},
            "matches": [{**e["best"], "distance": round(float(e["distance"]), 2), "repeats": len(e["engravings"]),
                         "photographs": len(e["photographs"]), "experiments": e["experiments"], "evidence": "observed",
                         "observation_ids": sorted(e["observation_ids"]),
                         "provisional_checks": sorted({p["pair_id"] for p in e["points"] if p["provisional"]}),
                         "within_tolerance": None if tolerance is None else bool(e["distance"] <= tolerance),
                         "confidence": e["confidence"], "agreement": agreement.shown(e["found"]),
                         "caution": "contradicted" if e["found"]["contradicted"] else None, "doubtful": agreement.doubtful(e["found"]),
                         "sources": sources_of(e, e["found"]),
                         "repeatability": _repeatability(e["engravings"]), "missing_context": missing_context(e["points"])} for e in ranked],
            "nominal_clean": data["nominal_clean"], "counts": {**data["counts"], "doubtful": doubtful}}


def _repeatability(engravings: dict[str, list]) -> dict:
    """How far the independent engravings of one entry agree: the largest delta E of an engraving's colour from their mean.
    One engraving cannot show it (DEC-021: its re-photographs are views, not repeats)."""
    means = [np.mean(np.asarray(labs, float), axis=0) for labs in engravings.values()]
    if len(means) < 2:
        return {"assessed": False, "engravings": len(means)}
    centre = np.mean(means, axis=0)
    return {"assessed": True, "engravings": len(means), "max_delta_e": round(max(color.delta_e(m, centre) for m in means), 2)}


def missing_context(points: list[dict]) -> list[str]:
    """What an entry's evidence lacks, as codes the screen names: an unknown lens or titanium batch, colours relative to the
    camera or without any reference, checks not accepted yet, settings the LightBurn file did not record."""
    out = []
    checks = (("lens_unknown", lambda p: p["lens_id"] is None), ("batch_unknown", lambda p: not p.get("batch")),
              ("camera_relative", lambda p: p["measurement"] == "relative"), ("unreferenced", lambda p: not p["referenced"]),
              ("provisional", lambda p: p["provisional"]),
              ("settings_incomplete", lambda p: any(p["parameters"].get(k) is None for k in
                                                    ("power", "frequency", "speed", "pulse_width", "passes"))))
    for code, lacks in checks:
        if any(lacks(p) for p in points):
            out.append(code)
    return out
