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
measured (chart, against clean titanium, as photographed) and whether it is provisional; colours of different kinds are never
pooled into one entry. An entry counts independent engravings (re-photographs of one engraving count once, DEC-021) and
photographs separately.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import color, experiments, ingest, lightburn as lb, model
from . import setup as su
from .db import Store

DEFAULT_CLEAN = [68.0, 0.0, 2.0]          # cleaned titanium when no photograph with a chart has measured it yet
SERVICE = ("registration, QR and engraved labels",)
WITNESS = "pre-test cleaning witness"
PENDING = ("Accepted", "Deleted")         # statuses that are not a check awaiting acceptance


def _rows(store: Store):
    return store.query(
        "SELECT o.id, o.pair_id, o.layer_index, o.lab_json, o.parameters_json, o.model_eligible, o.alignment_method, o.evidence_json, "
        "p.plan_id, p.engraving_id, p.engraving_title, p.photo_name, p.lightburn_name, p.accepted_at, p.created_at AS pair_created, "
        "p.device_id, p.lens_id, p.material_id, "
        "p.hardware_json, p.context_json AS pair_context, p.lightburn_path "
        "FROM observation o JOIN pair p ON p.id=o.pair_id "
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
            "setup_label": f"{laser} · {lens or 'линза неизвестна'}", "material": material, "material_id": source["material_id"]}


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
    return {"power": rep.get("power"), "frequency": rep.get("frequency_khz"), "speed": rep.get("speed"), "pulse_width": rep.get("pulse_width"),
            "line_interval": rep.get("line_interval"), "passes": rep.get("passes"), "layer_type": rep.get("type"),
            "global_passes": rep.get("global_passes"), "bidirectional": rep.get("bidirectional"), "cross_hatch": rep.get("cross_hatch"),
            "scan_angle": rep.get("scan_angle"), "angle_increment": rep.get("angle_increment"),
            "source_settings": lb.recipe_settings(rep.get("source_settings"))}


SHOWN_PARAMETERS = ("power", "frequency", "speed", "pulse_width", "line_interval", "passes", "layer_type", "global_passes", "bidirectional",
                    "cross_hatch", "scan_angle")


def _group(params: dict, info: dict, kind: str, referenced: bool, provisional: bool, tonal: bool = False) -> str:
    """One recipe of the search: the settings, the laser and lens records, the titanium stock record, how the colour was measured
    and whether it is provisional; colours that differ in any of these are never one entry (REQ-020, REQ-029)."""
    basis = "chart" if kind == "calibrated" else "clean" if referenced else "as-shot"
    return "|".join((model.parameters_key(params), "tonal" if tonal else "layer", info["setup"], f"ti:{info['material_id'] or 'unknown'}",
                     basis, "provisional" if provisional else "accepted"))


def _tonal_points(pair_id: int, check: dict, info: dict, kind: str, clean, nominal, provisional: bool) -> list[dict]:
    """A grayscale-mode image is a continuum of recipes: the grey level sets the power and the power sets the colour. Each step of
    its tonal profile is a colour with the settings of that power (DEC-056)."""
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
                      "pulse_width": rep.get("pulse_width"), "line_interval": rep.get("line_interval"), "passes": rep.get("passes"),
                      "layer_type": "Image", "grayscale": True}
            out.append({"id": f"tonal-{pair_id}-{rep['index']}-{step['gray']}", "pair_id": pair_id, "layer_index": rep["index"],
                        "layer_name": f"{rep.get('name')} · серый {step['gray']:.2f}", "measurement": kind, "approximate": approximate,
                        "referenced": referenced, "provisional": provisional, "lab": lab, "delta": None, "display_lab": display,
                        "parameters": params, "source": "tonal", "group": _group(params, info, kind, referenced, provisional, tonal=True), **info})
    return out


def collect(store: Store, include_unreferenced: bool = True, setup: str | None = None, material: str | None = None,
            measurement: str | None = None, include_provisional: bool = True) -> dict:
    """Every colour of the map. Filters narrow the points (``setup`` is the key of a laser and lens, ``laser:1/lens:2``);
    the options and counts describe everything that exists."""
    refs = references(store)
    rows, witness, derived, nominal = refs["rows"], refs["witness"], refs["derived"], refs["nominal"]
    kept, names = experiments.kept_plan_ids(store), _names(store)

    points = []
    for row in rows:
        evidence = json.loads(row["evidence_json"] or "{}")
        if is_service(evidence.get("role"), row["layer_index"], derived.get(row["pair_id"])):
            continue
        info = _pair_info(_source_of_row(row), names, kept)
        lab = json.loads(row["lab_json"])
        kind = _kind(evidence, row["model_eligible"])
        ref = witness.get(row["pair_id"])
        delta = [lab[i] - ref["lab"][i] for i in range(3)] if ref else None
        display, approximate, referenced = expressed(lab, kind, ref["lab"] if ref else None, nominal)
        params = json.loads(row["parameters_json"] or "{}")
        points.append({"id": row["id"], "pair_id": row["pair_id"], "layer_index": row["layer_index"], "layer_name": evidence.get("layer_name"),
                       "measurement": kind, "approximate": approximate, "referenced": referenced, "provisional": False, "lab": lab, "delta": delta,
                       "display_lab": display, "parameters": {k: params.get(k) for k in SHOWN_PARAMETERS},
                       "group": _group(params, info, kind, referenced, False), **info})
    first_row = {}
    for row in rows:
        first_row.setdefault(row["pair_id"], row)
    for pair_id, row in first_row.items():
        check = ingest.get_pair(store, pair_id).get("check") or {}
        kind = "calibrated" if (check.get("color_measurement") or {}).get("mode") == "reference_chart_corrected" else "relative"
        ref = witness.get(pair_id)
        points += _tonal_points(pair_id, check, _pair_info(_source_of_row(row), names, kept), kind, ref["lab"] if ref else None, nominal, False)
    points += _provisional_points(store, names, kept, nominal)

    setups, materials = {}, set()
    for p in points:
        setups[p["setup"]] = p
        if p["material"]:
            materials.add(p["material"])
    shown = [p for p in points if (setup is None or p["setup"] == setup) and (material is None or p["material"] == material)
             and (measurement is None or p["measurement"] == measurement)]
    provisional = sum(p["provisional"] for p in shown)
    if not include_provisional:
        shown = [p for p in shown if not p["provisional"]]
    unreferenced = sum(not p["referenced"] for p in shown)
    if not include_unreferenced:
        shown = [p for p in shown if p["referenced"]]
    return {"points": shown, "nominal_clean": {"lab": nominal, "source": refs["nominal_source"]},
            "options": {"setups": sorted(({"key": key, "label": info["setup_label"], "device_id": info["device_id"], "lens_id": info["lens_id"]}
                                          for key, info in setups.items()), key=lambda o: (o["label"], o["key"])),
                        "materials": sorted(materials)},
            "counts": {"calibrated": sum(p["measurement"] == "calibrated" for p in shown),
                       "relative": sum(p["measurement"] == "relative" for p in shown), "unreferenced": unreferenced,
                       "provisional": provisional}}


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
            out.append({"id": f"provisional-{pair['id']}-{rep['index']}", "pair_id": pair["id"], "layer_index": rep["index"],
                        "layer_name": rep.get("name"), "measurement": kind, "approximate": approximate, "referenced": referenced,
                        "provisional": True, "lab": lab, "delta": [lab[i] - clean[i] for i in range(3)] if clean else None,
                        "display_lab": display, "parameters": {k: params.get(k) for k in SHOWN_PARAMETERS},
                        "group": _group(params, info, kind, referenced, True), **info})
        out += _tonal_points(pair["id"], check, info, kind, clean, nominal, True)
    return out


def search(store: Store, lab: list[float], limit: int = 12, include_unreferenced: bool = False, include_provisional: bool = False,
           **filters) -> dict:
    """The recipes whose colour is nearest to ``lab``: one entry per recipe, with how many independent engravings gave it, in how
    many photographs, and from which experiments. Colours without a clean reference and provisional colours are left out unless
    asked for; their numbers are returned."""
    data = collect(store, include_unreferenced=include_unreferenced, include_provisional=include_provisional, **filters)
    best: dict[str, dict] = {}
    for point in data["points"]:
        distance = color.delta_e(lab, point["display_lab"])
        entry = best.setdefault(point["group"], {"best": point, "distance": distance, "engravings": set(), "photographs": set(), "experiments": []})
        entry["engravings"].add(point["engraving_id"])
        entry["photographs"].add(point["pair_id"])
        if point["experiment"] not in entry["experiments"]:
            entry["experiments"].append(point["experiment"])
        if distance < entry["distance"]:
            entry["best"], entry["distance"] = point, distance
    ranked = sorted(best.values(), key=lambda e: e["distance"])[:limit]
    return {"target": lab, "matches": [{**e["best"], "distance": round(float(e["distance"]), 2), "repeats": len(e["engravings"]),
                                         "photographs": len(e["photographs"]), "experiments": e["experiments"]} for e in ranked],
            "nominal_clean": data["nominal_clean"], "counts": data["counts"]}
