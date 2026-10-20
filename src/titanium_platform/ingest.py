"""Universal observation ingestion: a LightBurn file paired with a rig photograph (REQ-001, REQ-015).

A *pair* goes through ``create_pair`` -> ``check_pair`` -> (``confirm_file``) -> ``review_masks`` ->
``accept_pair``. Only ``accept_pair`` writes observations, and observations are immutable afterwards.

Rules implemented here:

* Power, frequency, speed, pulse width, line interval and pass count come from each paired LightBurn layer: they are
  job settings (DEC-042). The operator chooses the laser and the lens of the work; the lens may be unknown, and the
  lens installed now is never assumed for an imported work (REQ-016). A pair linked to a plate takes the plate's lens.
  A required setting that a layer does not hold stays unknown unless the operator supplies it for that layer
  (``supply_setting``); the observation then records which settings came from the file and which from the operator.
* System calibration plates can be measured without a separate ColorChecker: their RAW-rendered colors are
  stored as camera-relative observations. General photographs still require a usable reference chart.
* A calibration plate is identified by the ``TCE1:<id>`` note in its LightBurn file; its cells are matched to
  file layers by geometry, never guessed. Marker or identifier failures stop the mapping (REQ-003). An engraving plan
  exported by this system (discrete, tonal, colour-path) is identified the same way by its plan identifier and aligned by
  its markers when it has them (REQ-013, DEC-010). Four markers whose identifier cannot be read are accepted only for a
  photograph the operator linked to that plate or plan.
* A difference between file parameters and the plate definition blocks acceptance until the operator
  corrects the pair (a new file) or explicitly confirms the attached file was used (DEC-017).
* Every readable physical layer is measured, including the clean witness and registration/label marks. A clean
  witness excludes geometry engraved later; registration and labels include separately sampled QR, ArUco and
  text readouts. Incomplete/out-of-range settings remain attached to the measured result but do not feed process
  recommendations. Vector lines also receive continuity and apparent-width analysis.
* A re-photograph of an engraving shares its ``engraving_id`` and never counts as an independent
  repetition (DEC-021).
* Every layer has an engraving task (REQ-020, ``tasks``): the operator's choice for the layer on the review, else the task
  given to the whole work on the upload, else that of the plan or plate layer it was made from, else the one its LightBurn
  mode implies. Acceptance stores it with each observation; until then it is derived on every read.

LightBurn coordinates remain in millimetres; the photo may be rotated or reflected.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import cv2

from . import color
from . import lightburn as lb
from . import photo as ph
from . import plans as pl
from . import render_cache as rc
from . import setup as su
from . import tasks
from .db import Store, now

ST_PENDING, ST_CORRECTION, ST_READY, ST_ACCEPTED, ST_DELETED = "Awaiting check", "Needs correction", "Ready to accept", "Accepted", "Deleted"
PARAM_TOLERANCE = 1e-6
CONTEXT_KEYS = ("material_id", "titanium_name", "titanium_grade", "titanium_thickness_mm", "titanium_surface",
                "batch", "focus", "engraved_at", "note")
DATA_KEYS = ("rephoto_of", "correction_of", "masks_reviewed", "file_confirmation", "corners", "prefer_corners", "anchor", "alignment_override", "check",
             "matrix", "lens_choice", "linked_plan_id", "work_task", "layer_tasks", "supplied_settings")
# The six settings a comparable layer needs (REQ-015): the LightBurn tag each is read from and the field of a layer report
# that holds the value read from the file.
REQUIRED_SETTINGS = {"power": ("maxPower", "power"), "frequency": ("frequency", "frequency_khz"), "speed": ("speed", "speed"),
                     "pulse_width": ("QPulseWidth", "pulse_width"), "line_interval": ("interval", "line_interval"),
                     "passes": ("numPasses", "passes")}
SUPPLIED_BY = "operator"
DEFAULTED = "laser default"          # a setting the file leaves out and the laser's passport gives a default for (DEC-086)
# The settings of a cell of a photographed parameter matrix: read from the photograph and confirmed by the operator; the
# LightBurn file of such a pair is generated from them, so it is never evidence of its own (REQ-036, DEC-061, DEC-072).
RECONSTRUCTED = "reconstruction"
RECONSTRUCTED_FROM = "photographed parameter matrix"


class IngestError(ValueError):
    """The pair cannot be processed or accepted; the message is meant for the operator."""


def _pair_row(store: Store, pair_id: int):
    row = store.one("SELECT * FROM pair WHERE id=?", (pair_id,))
    if row is None or row["status"] == ST_DELETED:
        raise KeyError(f"pair {pair_id} not found")
    return row


def get_pair(store: Store, pair_id: int) -> dict:
    d = dict(_pair_row(store, pair_id))
    plan = store.one("SELECT mode, data_json FROM plan WHERE id=?", (d["plan_id"],)) if d["plan_id"] else None
    d["plan_mode"] = plan["mode"] if plan else None        # a plan restored from the imported file is not a plate (REQ-005)
    d["context"] = json.loads(d.pop("context_json"))
    d["hardware"] = json.loads(d.pop("hardware_json") or "{}")
    d.update(json.loads(d.pop("data_json")))
    plan_data = {**json.loads(plan["data_json"] or "{}"), "mode": plan["mode"]} if plan else None
    d["plan_task"] = (plan_data or {}).get("engraving_task")
    if d.get("check"):
        express_against_clean(store, d["check"])
        _layer_tasks(store, d, plan_data)
    return d


def layer_task(pair: dict, plan: dict | None, rep: dict) -> dict:
    """The engraving task of one layer of a check (REQ-020); the order of precedence is in the module notes."""
    return tasks.effective(rep.get("type"), rep.get("source_settings"), rep.get("role"),
                           operator=(pair.get("layer_tasks") or {}).get(str(rep.get("index"))), work=pair.get("work_task"),
                           plan=tasks.plan_layer_task(plan, rep.get("name"), rep.get("index")))


def _layer_tasks(store: Store, pair: dict, plan: dict | None) -> None:
    """The task of every layer of the check and the quality metrics of every measured one with their method and basis
    (REQ-020); an accepted pair shows the task its observations were accepted with. Derived on every read, never stored."""
    check = pair["check"]
    layers = check.get("layers") or []
    accepted: dict[str, dict] = {}
    if pair["status"] == ST_ACCEPTED:
        for row in store.query("SELECT task_kind, parameters_json, evidence_json FROM observation WHERE pair_id=?", (pair["id"],)):
            accepted.setdefault(json.loads(row["evidence_json"] or "{}").get("layer_name"), tasks.of_observation(row))
    witness = next((rep.get("measured_lab") for rep in layers if rep.get("role") == tasks.WITNESS), None)
    scale, mode = tasks.photo_scale(check.get("alignment")), (check.get("color_measurement") or {}).get("mode")
    for rep in layers:
        rep["task"] = accepted.get(rep.get("name")) or layer_task(pair, plan, rep)
        if rep.get("measured_lab"):
            rep["metrics"] = tasks.quality_metrics(
                rep["task"]["kind"], lab=rep["measured_lab"], against_clean=rep.get("measured_lab_against_clean"), mode=mode,
                line_metrics=rep.get("line_metrics"), tonal=rep.get("tonal"), scale=scale,
                clean_lab=witness if rep.get("role") != tasks.WITNESS else None)


def express_against_clean(store: Store, check: dict) -> None:
    """A photograph without a chart is measured as the camera exposed it: an underexposed shot makes every colour dark and
    "light colours are not found". Where the work's cleaning layer shows clean titanium in the same photograph, every
    measured colour is also given as it would look next to nominal clean titanium (ratio in linear light, DEC-056); the
    camera-relative value stays as the evidence. Derived on every read, never stored, so a later calibrated witness
    improves old checks too."""
    if (check.get("color_measurement") or {}).get("mode") != "raw_camera_relative":
        return
    witness = next((rep for rep in check.get("layers", []) if rep.get("role") == "pre-test cleaning witness" and rep.get("measured_lab")), None)
    if witness is None:
        return
    from . import colormap
    nominal, source = colormap.nominal_clean(store)
    clean = witness["measured_lab"]
    y_clean = max(float(color.lab_to_linear_rgb(np.asarray(clean, float)) @ (0.2126, 0.7152, 0.0722)), 1e-6)
    y_nominal = float(color.lab_to_linear_rgb(np.asarray(nominal, float)) @ (0.2126, 0.7152, 0.0722))
    check["clean_reference"] = {"layer_index": witness["index"], "lab": clean, "nominal": nominal, "nominal_source": source,
                               "exposure_stops": round(float(np.log2(y_nominal / y_clean)), 2)}
    for rep in check["layers"]:
        if rep.get("measured_lab") and rep is not witness:
            rep["measured_lab_against_clean"] = color.against_clean(rep["measured_lab"], clean, nominal)
            for sub in rep.get("submeasurements") or []:
                if sub.get("measured_lab"):
                    sub["measured_lab_against_clean"] = color.against_clean(sub["measured_lab"], clean, nominal)


def _normalize_project_to_plan(project: lb.Project, plan: dict | None) -> list[str]:
    if plan is None:
        return []
    return lb.normalize_saved_orientation(
        project, mirror_x=bool(plan.get("export_mirror_x", False)),
        mirror_y=bool(plan.get("export_mirror_y", False)))


DERIVED_CHECK_KEYS = ("clean_reference",)              # added by express_against_clean on every read, never stored
DERIVED_LAYER_KEYS = ("measured_lab_against_clean", "task", "metrics")     # added by get_pair on every read


def _without_derived(check):
    if not isinstance(check, dict):
        return check
    out = {k: v for k, v in check.items() if k not in DERIVED_CHECK_KEYS}
    if isinstance(out.get("layers"), list):
        layers = []
        for rep in out["layers"]:
            rep = {k: v for k, v in rep.items() if k not in DERIVED_LAYER_KEYS}
            if isinstance(rep.get("submeasurements"), list):
                rep["submeasurements"] = [{k: v for k, v in s.items() if k not in DERIVED_LAYER_KEYS} for s in rep["submeasurements"]]
            layers.append(rep)
        out["layers"] = layers
    return out


def _save(store: Store, pair_id: int, data: dict, status: str | None = None, plate_id=None, plan_id=None) -> None:
    stored = {k: data.get(k) for k in DATA_KEYS}
    stored["check"] = _without_derived(stored.get("check"))
    sets, params = ["data_json=?"], [json.dumps(stored)]
    for col, val in (("status", status), ("plate_id", plate_id), ("plan_id", plan_id)):
        if val is not None:
            sets.append(f"{col}=?")
            params.append(val)
    store.execute(f"UPDATE pair SET {', '.join(sets)} WHERE id=?", (*params, pair_id))


def _guard_mutable(row) -> None:
    if row["status"] == ST_ACCEPTED:
        raise IngestError("an accepted pair and its observations are immutable")


def clean_context(ctx: dict | None) -> dict:
    """Run context. The chosen titanium stock is mandatory; focus, date and note are optional."""
    ctx = dict(ctx or {})
    out = {k: ctx.get(k) for k in CONTEXT_KEYS}
    if out["material_id"] in ("", None):
        out["material_id"] = None
    else:
        try:
            out["material_id"] = int(out["material_id"])
        except (TypeError, ValueError):
            raise su.ValidationError("select a titanium stock from the list") from None
        if out["material_id"] < 1:
            raise su.ValidationError("select a titanium stock from the list")
    if out["focus"] in ("", None):
        out["focus"] = None
    else:
        try:
            out["focus"] = float(out["focus"])
        except (TypeError, ValueError):
            raise su.ValidationError("focus must be a number") from None
        if not np.isfinite(out["focus"]):
            raise su.ValidationError("focus must be a finite number")
    if out["engraved_at"] in ("", None):
        out["engraved_at"] = None
    else:
        try:
            datetime.strptime(str(out["engraved_at"]), "%Y-%m-%d")
        except ValueError:
            raise su.ValidationError("date must be YYYY-MM-DD") from None
    for k in ("titanium_name", "titanium_grade", "titanium_surface", "batch", "note"):
        out[k] = (str(out[k]).strip() or None) if out[k] is not None else None
    if out["titanium_thickness_mm"] not in (None, ""):
        out["titanium_thickness_mm"] = float(out["titanium_thickness_mm"])
    else:
        out["titanium_thickness_mm"] = None
    return out


def previous_context(store: Store, device_id: int) -> dict | None:
    """'Same as previous': the context and the lens of the last accepted pair of this laser (``lens_id`` None = unknown)."""
    row = store.one("SELECT context_json, lens_id FROM pair WHERE device_id=? AND status=? ORDER BY accepted_at DESC, id DESC LIMIT 1",
                    (device_id, ST_ACCEPTED))
    return None if row is None else {**json.loads(row["context_json"]), "lens_id": row["lens_id"]}


# -- creation ------------------------------------------------------------------------------------------
def relative_finished_allowed(store: Store) -> bool:
    """A finished work photographed without a reference chart may be measured relative to the camera (DEC-053).

    Its observations are flagged camera-relative and excluded from the colour model, as for plates. The operator
    allowed this on 2026-10-16; set the setting ``allow_relative_finished_works`` to false for the strict rule of REQ-009.
    """
    return bool(store.get_setting("allow_relative_finished_works", True))


def non_raw_allowed(store: Store) -> bool:
    """Test/demo switch. Measurement requires RAW (DEC-003); this is off unless explicitly set and is not exposed by the API."""
    return bool(store.get_setting("allow_non_raw_photos", False))


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name) or "file"


def create_pair(store: Store, *, device_id: int, lens_id: int | None, stand_id: int | None = None, lightburn_name: str,
                lightburn_bytes: bytes, photo_name: str, photo_bytes: bytes, plan_id: int | None = None, rephoto_of: int | None = None,
                context: dict | None = None, task: str | None = None) -> int:
    """A new pair of the laser and lens the operator chose (``lens_id`` None: the lens is unknown), photographed on the
    capture setup ``stand_id`` (None: the one used last, REQ-009). ``task`` is the engraving task the operator gives the
    whole work; None leaves every layer the task of its plan or of its LightBurn mode (REQ-020)."""
    if rephoto_of is not None:
        # Legacy callers may still supply these fields. A second view must inherit the real job.
        return create_rephoto(store, rephoto_of, photo_name=photo_name, photo_bytes=photo_bytes, stand_id=stand_id)
    setup = su.resolve(store, device_id, lens_id)
    if stand_id is not None and store.one("SELECT id FROM capture_setup WHERE id=?", (stand_id,)) is None:
        raise IngestError("the selected capture setup was not found")
    stand_id = su.capture_setup_for_photo(store, stand_id)
    if not re.search(r"\.(lbrn2?)$", lightburn_name, re.I):
        raise IngestError("Select a .lbrn or .lbrn2 file")
    if Path(photo_name).suffix.lower() not in ph.RAW_EXTENSIONS and not non_raw_allowed(store):
        raise IngestError("A RAW photograph is required for measurement")
    if not lightburn_bytes or not photo_bytes:
        raise IngestError("both files must be non-empty")
    ctx = clean_context(context)
    work_task = tasks.optional(task)
    if ctx["material_id"] is None:
        raise IngestError("select the titanium stock used for this engraving")
    material = store.one("SELECT * FROM material_profile WHERE id=?", (ctx["material_id"],))
    if material is None:
        raise IngestError("the selected titanium stock was not found; choose it again")
    if plan_id is not None:
        linked = store.one("SELECT status FROM plan WHERE id=?", (plan_id,))
        if linked is None or linked["status"] == "Deleted":
            raise IngestError("the plan or plate chosen for this photograph was not found")
    # Store a snapshot on the run so later edits to the stock card do not rewrite this experiment's context.
    ctx.update(titanium_name=material["name"], titanium_grade=material["grade"],
               titanium_thickness_mm=material["thickness_mm"], titanium_surface=material["surface"], batch=material["batch"])
    hardware = {"device": {key: setup["device"].get(key) for key in ("id", "name", "manufacturer", "model", "serial")},
                "lens": su.lens_snapshot(setup)}
    engraving_id = uuid.uuid4().hex
    tag = uuid.uuid4().hex[:12]
    folder = store.data_dir / "files"
    lb_path, photo_path = folder / f"{tag}-{_safe_name(lightburn_name)}", folder / f"{tag}-{_safe_name(photo_name)}"
    lb_path.write_bytes(lightburn_bytes)
    photo_path.write_bytes(photo_bytes)
    # The plan or plate the operator uploaded this photograph for: the identity of the work is then the operator's
    data = {"rephoto_of": None, "masks_reviewed": False, "file_confirmation": None, "corners": None, "check": None,
            "linked_plan_id": plan_id, "work_task": work_task, "layer_tasks": {}}
    pair_id = store.execute(
        "INSERT INTO pair(status,device_id,lens_id,stand_id,material_id,plan_id,engraving_id,engraving_title,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,hardware_json,created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ST_PENDING, device_id, lens_id, stand_id, ctx["material_id"], plan_id, engraving_id, Path(lightburn_name).stem, lightburn_name, str(lb_path), photo_name, str(photo_path),
         json.dumps(ctx), json.dumps(data), json.dumps(hardware), now())).lastrowid
    if plan_id is None:
        restore_plan(store, pair_id)
    return pair_id


RESTORED_OUTLINE_MM = 0.01      # outlines of a restored plan keep their shape within 10 µm with far fewer flattened points


def _restored_region(region: lb.Region) -> dict:
    out = region.as_dict()
    for key, loops in (("polygon", [region.polygon]), ("holes", region.holes)):
        simplified = []
        for loop in loops:
            points = np.asarray(loop, np.float32).reshape(-1, 1, 2)
            if len(points) > 8:
                points = cv2.approxPolyDP(points, RESTORED_OUTLINE_MM, region.closed)
            simplified.append(points.reshape(-1, 2).round(4).tolist())
        if key == "polygon":
            out["polygon"] = simplified[0]
        elif simplified:
            out["holes"] = simplified
    return out


def restore_plan(store: Store, pair_id: int) -> int | None:
    """The EngravingPlan of an imported work, reconstructed from its LightBurn file (REQ-005, REQ-006): every layer with its
    power, frequency, speed, job settings and fill geometry, and the colour that was planned for it: the prediction of
    the knowledge entry of those settings at this moment, when one exists with all three estimates (REQ-002), else none.
    The pair is linked to it (mode 'Restored from file', status 'Restored'). It records the job that was engraved and is
    never exported as a new job. A file that names a plate or plan of this system restores nothing; a pair already linked
    to its own restored plan has it rebuilt from the current file. Returns the plan id, or None."""
    from . import model
    row = _pair_row(store, pair_id)
    own = pl.get_plan(store, row["plan_id"]) if row["plan_id"] else None
    if own is not None and not (own["mode"] == pl.MODE_RESTORED and own["restored"]["pair_id"] == pair_id):
        return None                                  # linked to a plan of this system, or to the plan of its source photograph
    try:
        project = lb.parse_file(row["lightburn_path"])
    except lb.LightBurnError:
        project = None                               # the check says why the file cannot be read
    if project is None or project.identifier:
        if own is not None:
            with store.transaction():
                store.execute("UPDATE pair SET plan_id=NULL WHERE id=?", (pair_id,))
                store.execute("DELETE FROM plan WHERE id=?", (own["id"],))
        return None
    setup = su.resolve(store, row["device_id"], row["lens_id"])
    context = json.loads(row["context_json"])
    summaries = model.knowledge_summaries(store, row["device_id"], row["lens_id"])
    entries = {r["parameters_key"]: r for r in store.query("SELECT id, parameters_key, stage, questioned FROM knowledge WHERE device_id=? AND lens_id IS ?",
                                                          (row["device_id"], row["lens_id"]))}
    supplied = json.loads(row["data_json"] or "{}").get("supplied_settings") or {}
    layers = []
    for layer in project.layers:
        if not layer.regions:
            continue
        params, _ = observation_parameters(setup["device"]["passport"],
                                           layer_report(layer, setup["device"]["passport"], supplied.get(str(layer.index))))
        task = tasks.effective(layer.layer_type, layer.source_settings, None, work=json.loads(row["data_json"] or "{}").get("work_task"))
        key = model.observation_key(params, context, task)
        entry, summary = entries.get(key), summaries.get(key)
        predicted = entry is not None and summary is not None and summary["available"]
        layers.append({"index": layer.index, "name": layer.name, "parameters": params, "cut_type": layer.layer_type,
                       "regions": [_restored_region(region) for region in layer.regions],
                       "prediction": {k: summary[k] for k in ("lab", "confidence", "expected_delta_e", "stability")} if predicted else None,
                       "knowledge_id": entry["id"] if predicted else None, "stage": entry["stage"] if predicted else None,
                       "questioned": bool(entry["questioned"]) if predicted else False})
    data = {"layers": layers, "markers": None, "lens": su.lens_snapshot(setup),
            "restored": {"pair_id": pair_id, "lightburn_name": row["lightburn_name"], "at": now()}}
    name = row["engraving_title"] or Path(row["lightburn_name"]).stem
    with store.transaction():
        if own is not None:
            store.execute("UPDATE plan SET name=?, lens_id=?, data_json=? WHERE id=?", (name, row["lens_id"], json.dumps(data), own["id"]))
            plan_id = own["id"]
        else:
            plan_id = store.execute(
                "INSERT INTO plan(name,mode,status,device_id,lens_id,markers,plan_identifier,band_count,data_json,created_at) VALUES (?,?,?,?,?,0,NULL,NULL,?,?)",
                (name, pl.MODE_RESTORED, pl.ST_RESTORED, row["device_id"], row["lens_id"], json.dumps(data), now())).lastrowid
            store.execute("UPDATE pair SET plan_id=? WHERE id=?", (plan_id, pair_id))
        store.audit("plan_restored", pair_id=pair_id, plan_id=plan_id, layers=len(layers),
                    predicted=sum(layer["prediction"] is not None for layer in layers))
    return plan_id


def create_rephoto(store: Store, source_pair_id: int, *, photo_name: str, photo_bytes: bytes, stand_id: int | None = None,
                   same_photograph: bool = False) -> int:
    """Attach a RAW view to the same engraving with the exact accepted job and context snapshot. The new photograph is taken
    on ``stand_id``, by default the rig of its source (the rig used last when the source has only the placeholder of old
    pairs); ``same_photograph`` keeps the source's record for the very same photograph aligned again."""
    source = _pair_row(store, source_pair_id)
    if source["status"] != ST_ACCEPTED:
        raise IngestError("only an accepted pair can be re-photographed")
    if stand_id is not None and store.one("SELECT id FROM capture_setup WHERE id=?", (stand_id,)) is None:
        raise IngestError("the selected capture setup was not found")
    if stand_id is None and (same_photograph or not su.get_capture_setup(store, source["stand_id"])["legacy"]):
        stand_id = source["stand_id"]
    stand_id = su.capture_setup_for_photo(store, stand_id, keep=source["stand_id"] if same_photograph else None)
    if Path(photo_name).suffix.lower() not in ph.RAW_EXTENSIONS and not non_raw_allowed(store):
        raise IngestError("A RAW photograph is required for measurement")
    if not photo_bytes:
        raise IngestError("Файл фотографии пуст")
    original_file = Path(source["lightburn_path"])
    if not original_file.is_file():
        raise IngestError("Файл LightBurn исходной пары не найден")
    source_data = json.loads(source["data_json"] or "{}")
    prior_root = source_data.get("rephoto_of")
    root = store.one("SELECT status FROM pair WHERE id=?", (prior_root,)) if prior_root else None
    root_pair_id = prior_root if root and root["status"] == ST_ACCEPTED else source_pair_id
    tag = uuid.uuid4().hex[:12]
    folder = store.data_dir / "files"
    lb_path = folder / f"{tag}-{_safe_name(source['lightburn_name'])}"
    photo_path = folder / f"{tag}-{_safe_name(photo_name)}"
    lb_path.write_bytes(original_file.read_bytes())
    photo_path.write_bytes(photo_bytes)
    # a new view of an accepted engraving keeps the identity that engraving was accepted with
    data = {"rephoto_of": root_pair_id, "masks_reviewed": False, "file_confirmation": source_data.get("file_confirmation"),
            "corners": None, "anchor": None, "check": None, "linked_plan_id": source["plan_id"],
            "work_task": source_data.get("work_task"), "layer_tasks": source_data.get("layer_tasks") or {},
            "supplied_settings": source_data.get("supplied_settings")}
    if source_data.get("matrix"):
        data["matrix"] = _matrix_for_rephoto(store, source_data, photo_name, photo_bytes)
    pair_id = store.execute(
        "INSERT INTO pair(status,device_id,lens_id,stand_id,material_id,plate_id,plan_id,engraving_id,engraving_title,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,hardware_json,created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ST_PENDING, source["device_id"], source["lens_id"], stand_id, source["material_id"], source["plate_id"], source["plan_id"],
         source["engraving_id"], source["engraving_title"] or Path(source["lightburn_name"]).stem, source["lightburn_name"], str(lb_path), photo_name, str(photo_path), source["context_json"],
         json.dumps(data), source["hardware_json"], now())).lastrowid
    store.audit("rephoto_created", source_pair_id=source_pair_id, pair_id=pair_id, engraving_id=source["engraving_id"])
    return pair_id


# -- a parameter matrix (LightBurn Material Test) recognised from its photograph (REQ-031, DEC-061) ------------------------
def _detect_matrices(store: Store, photo_name: str, photo_bytes: bytes) -> dict:
    """Every complete matrix in a photograph (the photograph is decoded from a temporary copy)."""
    from . import matrix
    folder = store.data_dir / "tmp"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex[:12]}-{_safe_name(photo_name)}"
    path.write_bytes(photo_bytes)
    try:
        linear = ph.decode_linear(path, allow_non_raw=non_raw_allowed(store))
        exposed = ph.exposed_bgr(linear)
        chart = ph.detect_chart(exposed)
        if not chart.detected:
            chart = ph.detect_chart(ph.decode_image(path, allow_non_raw=non_raw_allowed(store)))
        return matrix.detect(exposed, chart.box if chart.detected else None)
    except ph.PhotoError as exc:
        raise IngestError(f"the photograph cannot be read: {exc}") from exc
    finally:
        path.unlink(missing_ok=True)


def _matrix_record(grid: dict, detection: dict, index: int) -> dict:
    others = [g for k, g in enumerate(detection["grids"]) if k != index]
    return {**grid, "confirmed": False, "confirmed_at": None, "grid_index": index, "grids_in_photo": len(detection["grids"]),
            "ocr": detection["ocr"], "squares": detection["squares"], "others": [{**g, "created_pair_id": None} for g in others]}


def _stored(store: Store, pair_id: int) -> dict:
    """The pair's data as stored (``get_pair`` adds derived values that are never written back)."""
    return json.loads(_pair_row(store, pair_id)["data_json"] or "{}")


def create_matrix_pair(store: Store, *, device_id: int, lens_id: int | None, photo_name: str, photo_bytes: bytes,
                       context: dict | None = None, stand_id: int | None = None, grid: dict | None = None,
                       detection: dict | None = None) -> int:
    """A pair from a photograph of a parameter matrix: the matrix is found, its labels are read and a LightBurn file
    with one layer per cell is generated from what was read. The settings stay a proposal until the operator confirms
    them (``confirm_matrix``); nothing is accepted before (REQ-003)."""
    from . import matrix
    if Path(photo_name).suffix.lower() not in ph.RAW_EXTENSIONS and not non_raw_allowed(store):
        raise IngestError("A RAW photograph is required for measurement")
    if not photo_bytes:
        raise IngestError("Файл фотографии пуст")
    index = 0
    if grid is None:
        detection = _detect_matrices(store, photo_name, photo_bytes)
        if not detection["grids"]:
            raise IngestError("no parameter matrix was found in the photograph: photograph the whole test with its labels, "
                              "square to the camera")
        grid = detection["grids"][0]
    record = _matrix_record(grid, detection or {"grids": [grid], "ocr": matrix.ocr_available(), "squares": None}, index)
    spec = record["spec"]
    title = matrix.title(spec, photo_name)
    pair_id = create_pair(store, device_id=device_id, lens_id=lens_id, stand_id=stand_id, lightburn_name=f"{_safe_name(title)}.lbrn2",
                          lightburn_bytes=matrix.lightburn_bytes(spec, record["cols"], record["rows"]),
                          photo_name=photo_name, photo_bytes=photo_bytes, context=context)
    data = _stored(store, pair_id)
    data["matrix"] = record
    _save(store, pair_id, data)
    store.execute("UPDATE pair SET engraving_title=? WHERE id=?", (title, pair_id))
    store.audit("matrix_pair_created", pair_id=pair_id, cols=record["cols"], rows=record["rows"],
                missing=len(spec["missing"]), grids_in_photo=record["grids_in_photo"])
    return pair_id


def create_matrix_sibling(store: Store, pair_id: int, index: int) -> int:
    """Another matrix of the same photograph as its own experiment, from the detection already made."""
    row = _pair_row(store, pair_id)
    pair = _stored(store, pair_id)
    record = pair.get("matrix")
    if not record or not 0 <= index < len(record.get("others") or []):
        raise IngestError("this photograph holds no such other matrix")
    other = record["others"][index]
    if other.get("created_pair_id"):
        raise IngestError(f"that matrix is already experiment №{other['created_pair_id']}")
    photo = Path(row["photo_path"])
    if not photo.is_file():
        raise IngestError("the photograph of this pair is no longer available")
    grid = {k: v for k, v in other.items() if k != "created_pair_id"}
    context = json.loads(row["context_json"])
    new_id = create_matrix_pair(store, device_id=row["device_id"], lens_id=row["lens_id"], stand_id=row["stand_id"], photo_name=row["photo_name"],
                                photo_bytes=photo.read_bytes(), context={k: context.get(k) for k in ("material_id", "focus", "engraved_at", "note")},
                                grid=grid)
    record["others"][index]["created_pair_id"] = new_id
    if row["status"] != ST_ACCEPTED:
        pair["matrix"] = record
        _save(store, pair_id, pair)
    return new_id


def update_matrix(store: Store, pair_id: int, edit: dict, confirm: bool = False) -> dict:
    """The operator's corrections of what was read (axis settings, first and last values, fixed settings, extent):
    the LightBurn file is generated again and the photograph checked again. ``confirm`` also confirms the result."""
    from . import matrix
    row = _pair_row(store, pair_id)
    _guard_mutable(row)
    pair = _stored(store, pair_id)
    if not pair.get("matrix"):
        raise IngestError("this pair is not a parameter matrix")
    try:
        record = matrix.apply_edit(pair["matrix"], edit or {})
    except ValueError as exc:
        raise IngestError(str(exc)) from exc
    spec = record["spec"]
    if confirm:
        if spec["missing"]:
            raise IngestError("the matrix settings are incomplete: " + "; ".join(spec["missing"]))
        require_matrix_steps(su.resolve(store, row["device_id"], row["lens_id"])["device"]["passport"], record)
        record.update(confirmed=True, confirmed_at=now())
    title = matrix.title(spec, row["photo_name"])
    Path(row["lightburn_path"]).write_bytes(matrix.lightburn_bytes(spec, record["cols"], record["rows"]))
    pair["matrix"] = record
    _save(store, pair_id, pair)
    store.execute("UPDATE pair SET engraving_title=?, lightburn_name=? WHERE id=?", (title, f"{_safe_name(title)}.lbrn2", pair_id))
    store.audit("matrix_settings_edited", pair_id=pair_id, confirmed=record["confirmed"], cols=record["cols"], rows=record["rows"])
    restore_plan(store, pair_id)
    return check_pair(store, pair_id)


def require_matrix_steps(passport: dict, record: dict) -> None:
    """Every pulse width of a matrix's cells must be a step of the laser: the laser ignores any other, so a cell with one
    would not record the job that was engraved. Refused with the steps listed (REQ-017)."""
    from . import devices, matrix
    widths = {matrix.cell_settings(record["spec"], col, row)["pulse_width"] for row in range(record["rows"]) for col in range(record["cols"])}
    for width in sorted(w for w in widths if w is not None):
        devices.require_selectable(passport, width)


def confirm_matrix(store: Store, pair_id: int) -> None:
    """The operator states that the settings read from the matrix are the ones engraved."""
    row = _pair_row(store, pair_id)
    _guard_mutable(row)
    pair = _stored(store, pair_id)
    record = pair.get("matrix")
    if not record:
        raise IngestError("this pair is not a parameter matrix")
    if record["spec"]["missing"]:
        raise IngestError("the matrix settings are incomplete: " + "; ".join(record["spec"]["missing"]))
    require_matrix_steps(su.resolve(store, row["device_id"], row["lens_id"])["device"]["passport"], record)
    record.update(confirmed=True, confirmed_at=now())
    pair["matrix"] = record
    _save(store, pair_id, pair)
    store.audit("matrix_settings_confirmed", pair_id=pair_id)


def _matrix_for_rephoto(store: Store, source: dict, photo_name: str, photo_bytes: bytes) -> dict:
    """A new photograph of an accepted matrix: the matrix is found again in it; the confirmed settings carry over when
    a matrix of the same size is there."""
    detection = _detect_matrices(store, photo_name, photo_bytes)
    old = source["matrix"]
    same = [g for g in detection["grids"] if g["cols"] == old["cols"] and g["rows"] == old["rows"]]
    if not same:
        raise IngestError(f"no {old['cols']} x {old['rows']} matrix was found in the new photograph")
    grid = {**same[0], "spec": {**old["spec"], "cell_fraction": same[0]["spec"].get("cell_fraction", old["spec"].get("cell_fraction"))}}
    return {**_matrix_record(grid, detection, detection["grids"].index(same[0])), "confirmed": old.get("confirmed", False),
            "confirmed_at": old.get("confirmed_at")}


def create_alignment_revision(store: Store, source_pair_id: int) -> int:
    """Draft a corrected measurement of the very same RAW without mutating accepted observations."""
    source = get_pair(store, source_pair_id)
    if source["status"] != ST_ACCEPTED or not (source.get("check") or {}).get("alignment", {}).get("valid"):
        raise IngestError("only an accepted, aligned photograph can be revised")
    source_photo = Path(source["photo_path"])
    if not source_photo.is_file():
        raise IngestError("the source photograph is no longer available")
    alignment = source["check"]["alignment"]
    if (not alignment.get("work_corners_fraction") and source["check"].get("image_size")) or not alignment.get("snap_candidates"):
        project = lb.parse_file(source["lightburn_path"])
        _normalize_project_to_plan(project, pl.get_plan(store, source["plan_id"]) if source.get("plan_id") else None)
        regions = [region for layer in project.layers for region in layer.regions]
        if regions and not alignment.get("work_corners_fraction") and source["check"].get("image_size"):
            alignment["work_corners_fraction"] = _work_corners_fraction(
                regions, alignment["image_to_mm"], *source["check"]["image_size"])
        if not alignment.get("snap_candidates"):
            from . import registration
            system = {item["index"] for item in source["check"].get("layers", [])
                      if item.get("role") in ("pre-test cleaning witness", "registration, QR and engraved labels")}
            image = ph.decode_image(source_photo, allow_non_raw=non_raw_allowed(store))
            alignment["snap_candidates"] = registration.snap_translations(
                image, [layer for layer in project.layers if layer.regions], alignment["image_to_mm"], system)
    new_id = create_rephoto(store, source_pair_id, photo_name=source["photo_name"], photo_bytes=source_photo.read_bytes(),
                            same_photograph=True)
    revision = get_pair(store, new_id)
    # The same photograph aligned again, not a new view: it is a re-photograph only when its source is one, so the engraving
    # keeps exactly one independent repetition whichever revision is accepted (DEC-021).
    revision.update(correction_of=source_pair_id, rephoto_of=source.get("rephoto_of"), check=source["check"], corners=source.get("corners"),
                    prefer_corners=source.get("prefer_corners"), anchor=source.get("anchor"),
                    alignment_override=source.get("alignment_override"),
                    masks_reviewed=False)
    _save(store, new_id, revision, ST_READY)
    store.audit("alignment_revision_created", source_pair_id=source_pair_id, pair_id=new_id)
    return new_id


def _observation_summary(store: Store, pair_id: int) -> dict[int, dict]:
    """What a pair measured, by layer: the colour, the pulse width it was taken with and whether the model may learn from it."""
    out = {}
    for row in store.query("SELECT layer_index, lab_json, parameters_json, model_eligible, evidence_json FROM observation WHERE pair_id=? ORDER BY layer_index", (pair_id,)):
        out[row["layer_index"]] = {"lab": json.loads(row["lab_json"]), "pulse_width": (json.loads(row["parameters_json"]) or {}).get("pulse_width"),
                                   "model_eligible": bool(row["model_eligible"]), "name": (json.loads(row["evidence_json"]) or {}).get("layer_name")}
    return out


def remeasure_pair(store: Store, pair_id: int, on_accepted: Callable[[Store, int, int | None], None] | None = None) -> dict:
    """Measure an accepted photograph again with the measurement as it is now (the colour correction, the laser's defaults, the
    settings the operator supplied) and let the new measurement replace the old one. The alignment is the one the pair was accepted
    with. The old measurement stays untouched, and the draft is dropped, unless the new one is whole: the same colour basis, nothing
    the check objects to, no layer less than before. Returns what happened and, layer by layer, the colour before and after."""
    result = {"pair_id": pair_id, "status": "kept", "replaced_by": None, "reason": None, "layers": []}
    before = _observation_summary(store, pair_id)
    basis = ((get_pair(store, pair_id).get("check") or {}).get("color_measurement") or {}).get("mode")
    try:
        draft = create_alignment_revision(store, pair_id)
    except IngestError as exc:
        return {**result, "reason": str(exc)}
    try:
        report = check_pair(store, draft)
        if report["problems"]:
            raise IngestError("resolve the problems found by the check: " + "; ".join(report["problems"]))
        now_basis = (report.get("color_measurement") or {}).get("mode")
        if now_basis != basis:
            raise IngestError(f"the colour basis of the photograph would change from {basis} to {now_basis}")
        if sum(1 for layer in report["layers"] if layer["measured_lab"] is not None) < len(before):
            raise IngestError("the new measurement reads fewer layers than the accepted one")
        review_masks(store, draft)
        accept_pair(store, draft, on_accepted)
    except Exception as exc:
        state = store.one("SELECT status FROM pair WHERE id=?", (draft,))
        if state is not None and state["status"] == ST_ACCEPTED:
            raise                                   # the new measurement is in; only what followed it failed
        if state is not None and state["status"] != ST_DELETED:
            delete_pair(store, draft)
        return {**result, "reason": str(exc)}
    after = _observation_summary(store, draft)
    layers = [{"layer_index": index, "name": (after.get(index) or before.get(index))["name"], "before": (before.get(index) or {}).get("lab"),
               "after": (after.get(index) or {}).get("lab"),
               "delta_e": None if index not in before or index not in after else round(float(np.linalg.norm(np.array(before[index]["lab"]) - np.array(after[index]["lab"]))), 2),
               "pulse_width_before": (before.get(index) or {}).get("pulse_width"), "pulse_width_after": (after.get(index) or {}).get("pulse_width"),
               "model_eligible_before": (before.get(index) or {}).get("model_eligible"), "model_eligible_after": (after.get(index) or {}).get("model_eligible")}
              for index in sorted(set(before) | set(after))]
    store.audit("pair_remeasured", pair_id=pair_id, replaced_by=draft, layers=len(layers))
    return {**result, "status": "replaced", "replaced_by": draft, "layers": layers}


def replace_lightburn_file(store: Store, pair_id: int, name: str, data: bytes) -> None:
    """'Correct the pair': attach a different LightBurn file. Clears the check, confirmation and mask review."""
    row = _pair_row(store, pair_id)
    _guard_mutable(row)
    if not re.search(r"\.(lbrn2?)$", name, re.I):
        raise IngestError("Select a .lbrn or .lbrn2 file")
    path = Path(row["lightburn_path"]).with_name(f"{uuid.uuid4().hex[:12]}-{_safe_name(name)}")
    path.write_bytes(data)
    store.execute("UPDATE pair SET lightburn_name=?, lightburn_path=? WHERE id=?", (name, str(path), pair_id))
    pair = get_pair(store, pair_id)
    # settings supplied for the layers of the previous file do not describe this one
    pair.update(masks_reviewed=False, file_confirmation=None, alignment_override=None, prefer_corners=False, check=None,
                supplied_settings=None)
    _save(store, pair_id, pair, ST_PENDING)
    restore_plan(store, pair_id)                     # a plan restored from the previous file follows the new one


def rename_engraving(store: Store, engraving_id: str, title: str) -> None:
    """Rename one physical engraving across all of its photographs."""
    clean = title.strip()
    if not clean or len(clean) > 120:
        raise IngestError("Название гравировки должно содержать от 1 до 120 символов")
    rows = store.query("SELECT id FROM pair WHERE engraving_id=? AND status!='Deleted'", (engraving_id,))
    if not rows:
        raise KeyError("гравировка не найдена")
    store.execute("UPDATE pair SET engraving_title=? WHERE engraving_id=?", (clean, engraving_id))
    store.audit("engraving_renamed", engraving_id=engraving_id, title=clean)


# -- plate comparison ----------------------------------------------------------------------------------
def _bbox(regions) -> tuple[float, float, float, float]:
    x0, y0 = min(r.x for r in regions), min(r.y for r in regions)
    return x0, y0, max(r.x + r.width for r in regions) - x0, max(r.y + r.height for r in regions) - y0


def _work_corners_fraction(regions, image_to_mm, width: int, height: int) -> list[list[float]]:
    x, y, w, h = _bbox(regions)
    vertices = np.float32([[(x, y), (x + w, y), (x + w, y + h), (x, y + h)]])
    on_photo = cv2.perspectiveTransform(vertices, np.linalg.inv(np.asarray(image_to_mm, float)))[0]
    return (on_photo / np.array([width, height])).round(6).tolist()


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _same_exported_setting(field: str, defined: float, got: float) -> bool:
    """Accept a plan value or the exact value written by older LightBurn exports.

    The writer used six significant digits for most settings and integer Hz for frequency.
    That can turn 2333.3333 mm/s into 2333.33 mm/s without a changed laser setting.
    A larger real edit must still be reported as a discrepancy.
    """
    if abs(defined - got) <= PARAM_TOLERANCE:
        return True
    serialized = round(defined * 1000) / 1000 if field == "frequency" else float(f"{defined:g}")
    return abs(serialized - got) <= PARAM_TOLERANCE


def compare_plate(plate_cells: list[dict], layers: list[lb.Layer], dx: float, dy: float):
    """Match plate cells to file layers by geometry and list parameter discrepancies (DEC-017).

    Returns (discrepancies, cell_id -> layer, cell ids that no layer covers). A cell with no matching
    geometry is reported, never guessed.
    """
    discrepancies, mapping, missing = [], {}, []
    for cell in plate_cells:
        # Older saved plates put geometry and parameters directly on each cell; current plates nest both.
        g = cell.get("geometry", cell)
        cell_id = cell.get("id", cell.get("cell_id", cell.get("name", "unknown")))
        # Mixed capability coupons include zero-area vector lines and wobble parameters; their stable
        # per-feature name is an exact identity and must be checked before attempting area overlap.
        best = next((layer for layer in layers if layer.name == cell_id), None)
        best_iou = 1.0 if best else 0.0
        want = None
        if best is None and all(k in g for k in ("x", "y", "width", "height")):
            want = (g["x"] + dx, g["y"] + dy, g["width"], g["height"])
        for layer in layers:
            if want is None:
                break
            for r in layer.regions:
                score = _iou(want, (r.x, r.y, r.width, r.height))
                if score > best_iou:
                    best, best_iou = layer, score
        if best is None or best_iou < 0.5:
            missing.append(cell_id)
            continue
        mapping[cell_id] = best
        p = cell.get("parameters", cell)
        for field, defined, got in (("power", p["power"], best.power), ("frequency", p["frequency"], best.frequency_khz),
                                    ("speed", p["speed"], best.speed), ("pulse_width", p.get("pulse_width"), best.pulse_width),
                                    ("line_interval", p.get("line_interval"), best.line_interval),
                                    ("passes", p.get("passes", 1), best.passes)):
            # An omitted setting is unknown, not evidence that the physical job differed from the
            # plate definition. In particular, Cut has no fill interval and many LightBurn files
            # omit Q-Pulse. Keep those values null in observations instead of inventing them.
            if defined is not None and got is not None and not _same_exported_setting(field, defined, got):
                discrepancies.append({"cell_id": cell_id, "field": field, "defined": defined, "from_file": got})
    return discrepancies, mapping, missing


def _file_value(layer: lb.Layer, setting: str):
    return layer.frequency_khz if setting == "frequency" else getattr(layer, REQUIRED_SETTINGS[setting][1])


def missing_settings(layer: lb.Layer) -> list[str]:
    """The required settings that the LightBurn layer does not hold at all: these, and only these, the operator may
    supply (REQ-015). A value that is present but unreadable is not missing (the file has to be corrected), and a Cut
    layer has no fill, so it needs no line interval."""
    out = []
    for setting, (tag, _) in REQUIRED_SETTINGS.items():
        if setting == "line_interval" and layer.layer_type == "Cut":
            continue
        unreadable = any(p.startswith(f"{tag}:") and p != f"{tag}: missing" for p in layer.unreadable)
        if _file_value(layer, setting) is None and not unreadable:
            out.append(setting)
    return out


def laser_defaults(passport: dict, settings: list[str]) -> dict:
    """The settings of ``settings`` that the laser gives a default for: LightBurn leaves a setting out of a layer when it is at
    the default, so a layer without the tag has that value (DEC-086). Only the pulse width has a default in the passport."""
    width = passport.get("default_pulse_width_ns")
    if "pulse_width" in settings and width is not None:
        return {"pulse_width": {"value": width, "source": DEFAULTED}}
    return {}


def effective_setting(rep: dict, setting: str):
    """The value of a required setting of a layer report: the file's, else the operator's, else the laser's default."""
    field = REQUIRED_SETTINGS[setting][1]
    if rep.get(field) is not None:
        return rep[field]
    for source in ("supplied_settings", "defaulted_settings"):
        entry = (rep.get(source) or {}).get(setting)
        if entry:
            return entry["value"]
    return None


def supplied_value(passport: dict, setting: str, value) -> float | int:
    """A setting the operator supplies for a layer, checked as a plate's setting is: a pulse width must be a step of the
    laser (refused with the steps listed), a frequency within the laser's repetition-rate range, a power above 0 and up
    to 100 %, a speed and a line interval above 0, the passes a whole number from 1."""
    from . import devices
    if setting == "passes":
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = float("nan")
        if not np.isfinite(number) or number < 1 or int(number) != number:
            raise su.ValidationError("passes must be a positive integer")
        return int(number)
    number = su._finite(value, setting.replace("_", " "), True)
    if setting == "power" and number > 100:
        raise su.ValidationError("power must not exceed 100 %")
    if setting == "frequency":
        rate = passport["repetition_rate_khz"]
        if not rate["min"] <= number <= rate["max"]:
            raise su.ValidationError(f"frequency {number:g} kHz is outside the repetition rate range {rate['min']:g}-{rate['max']:g} kHz of this laser")
    if setting == "pulse_width":
        devices.require_selectable(passport, number)
    return number


def layer_report(layer: lb.Layer, passport: dict, supplied: dict | None = None) -> dict:
    """Per-layer readability and comparability to the limits of the selected laser.

    ``supplied`` are the settings the operator gave for this layer ({setting: {"value", "by", "at"}}, REQ-015, REQ-016).
    They count only for settings the file does not hold; the values read from the file stay in the report unchanged, and
    the report lists the settings missing from the file and the supplied ones apart."""
    missing = missing_settings(layer)
    given = {k: v for k, v in (supplied or {}).items() if k in missing}
    defaulted = laser_defaults(passport, [k for k in missing if k not in given])
    value = {k: given[k]["value"] if k in given else defaulted[k]["value"] if k in defaulted else _file_value(layer, k) for k in REQUIRED_SETTINGS}
    resolved = {f"{REQUIRED_SETTINGS[k][0]}: missing" for k in (*given, *defaulted)}
    unreadable = [n for n in layer.unreadable if n not in resolved]
    notes, compatible = [], True
    if unreadable:
        compatible = False
        notes += unreadable
    else:
        problems = su.check_in_range(passport, value["power"], value["frequency"])
        if value["pulse_width"] is None:
            problems.append("pulse width is missing from this LightBurn layer")
        if layer.layer_type != "Cut" and value["line_interval"] is None:
            problems.append("line interval is missing from this LightBurn layer")
        if value["passes"] is None:
            problems.append("pass count is missing from this LightBurn layer")
        if problems:
            compatible = False
            notes += [f"not comparable within this laser and lens: {m}" for m in problems]
    for kind, count in sorted(layer.unsupported.items()):
        notes.append(f"{count} {kind} objects on this layer are not read: no outline geometry")
    if layer.unknown_settings:      # kept with the recipe, so they still separate recipes, but nothing here interprets them
        notes.append(f"settings unknown to this version are kept with the recipe but not interpreted: {', '.join(layer.unknown_settings)}")
    if not layer.regions:
        compatible = False
        notes.append("the layer has no fill geometry")
    image = layer.image_summary()
    return {"index": layer.index, "name": layer.name, "type": layer.layer_type, "power": layer.power,
            "frequency_khz": layer.frequency_khz, "speed": layer.speed, "pulse_width": layer.pulse_width,
            "line_interval": layer.line_interval, "passes": layer.passes, "global_passes": layer.global_passes,
            "bidirectional": layer.bidirectional, "cross_hatch": layer.cross_hatch, "scan_angle": layer.scan_angle,
            "angle_increment": layer.angle_increment, "source_settings": layer.source_settings,
            "regions": len(layer.regions), "readable": not unreadable, "missing_settings": missing, "supplied_settings": given,
            "defaulted_settings": defaulted, "compatible": compatible, "notes": notes, "measured_lab": None, "pixels": None,
            **({"image": image} if image else {})}



# -- checking ------------------------------------------------------------------------------------------
def lens_check(store: Store, plate: dict, chosen_lens_id: int | None, kind: Literal["plate", "plan"] = "plate") -> dict:
    """Compare the lens a plate (or an engraving plan, ``kind="plan"``) was made for with the lens installed now and with the
    lens the operator chose for the photograph (DEC-041, REQ-019). A difference is a warning, never a block; the plate's or
    plan's lens, when it is recorded, is the lens of the measurements (``lens_id``), so comparability follows the historical
    configuration."""
    from . import lenses
    made = json.loads(plate["lens_json"]) if plate.get("lens_json") else None
    now_lens = lenses.installed(store, plate["device_id"])
    warnings = []
    if made and now_lens and (made["id"] != now_lens["id"] or made["focal_length_mm"] != now_lens["focal_length_mm"] or made["expansion"] != now_lens["expansion"]):
        warnings.append(f"the lens installed now ({lenses.label(now_lens)}) differs from the lens of this {kind} ({lenses.label(made)})")
    elif made and not now_lens:
        warnings.append(f"no lens is installed on the laser now; the {kind} was made with {lenses.label(made)}")
    elif now_lens and not made:
        warnings.append(f"this {kind} has no record of its lens")
    lens_id = chosen_lens_id
    if plate["lens_id"] is not None and plate["lens_id"] != chosen_lens_id:
        made_label = lenses.label(made) if made else lenses.label(lenses.get_lens(store, plate["lens_id"]))
        if chosen_lens_id is None:
            warnings.append(f"no lens was chosen for this photograph; the {kind} was made with {made_label}: the measurements are kept with the {kind}'s lens")
        else:
            warnings.append(f"the lens chosen for this photograph ({lenses.label(lenses.get_lens(store, chosen_lens_id))}) differs from the lens of "
                            f"this {kind} ({made_label}): the measurements are kept with the {kind}'s lens")
        lens_id = plate["lens_id"]
    return {"plate": made, "installed": None if not now_lens else {"id": now_lens["id"], "name": now_lens["name"], "focal_length_mm": now_lens["focal_length_mm"]},
            "chosen_lens_id": chosen_lens_id, "lens_id": lens_id, "warnings": warnings}


def _set_lens(store: Store, row, lens_id: int | None, snapshot: dict | None) -> None:
    """The lens of the pair's measurements, with its snapshot: the plate's when given, else one taken of the lens now."""
    if snapshot is None and lens_id is not None:
        snapshot = su.lens_snapshot(su.resolve(store, row["device_id"], lens_id))
    hardware = json.loads(row["hardware_json"] or "{}") | {"lens": snapshot}
    store.execute("UPDATE pair SET lens_id=?, hardware_json=? WHERE id=?", (lens_id, json.dumps(hardware), row["id"]))


def _plate_row(store: Store, plate_id: int) -> dict:
    plate = dict(store.one("SELECT * FROM plate WHERE id=?", (plate_id,)))
    plate["cells"] = json.loads(plate["cells_json"])
    return plate


def _load_identified(store: Store, identifier: str | None):
    """(plate, plan) named by the TCE1 identifier found in the LightBurn file, or (None, None): a calibration or capability
    plate by its experiment identifier, or an engraving plan exported by this system (discrete, tonal, colour-path) by its
    plan identifier, with the plate it was made from when it has one (REQ-013)."""
    if not identifier:
        return None, None
    prow = store.one("SELECT id FROM plate WHERE experiment_id=?", (identifier,))
    if prow is not None:
        plan_row = store.one("SELECT id FROM plan WHERE plate_id=?", (prow["id"],))
        return _plate_row(store, prow["id"]), (pl.get_plan(store, plan_row["id"]) if plan_row else None)
    plan_row = store.one("SELECT id, plate_id FROM plan WHERE plan_identifier=? ORDER BY id DESC LIMIT 1", (identifier,))
    if plan_row is None:
        return None, None
    return (_plate_row(store, plan_row["plate_id"]) if plan_row["plate_id"] else None), pl.get_plan(store, plan_row["id"])


def _made_for(plan: dict) -> dict:
    """What a plan remembers of its laser and lens, in the form ``lens_check`` reads a plate."""
    return {"device_id": plan["device_id"], "lens_id": plan["lens_id"],
            "lens_json": json.dumps(plan["lens"]) if plan.get("lens") else None}


def _rect_polygons(rects: list[dict], dx: float = 0.0, dy: float = 0.0) -> list[list[tuple[float, float]]]:
    """Convert planned filled rectangles to file-coordinate polygons."""
    return [[(r["x"] + dx, r["y"] + dy), (r["x"] + r["width"] + dx, r["y"] + dy),
             (r["x"] + r["width"] + dx, r["y"] + r["height"] + dy),
             (r["x"] + dx, r["y"] + r["height"] + dy)] for r in rects]


def _qr_local_geometry(plan: dict | None, alignment: dict) -> tuple[tuple[float, float, float, float], np.ndarray] | None:
    """Keep a QR-specific photographic offset separate from file millimetres."""
    if not plan or alignment.get("qr_used_as_anchor") is not False:
        return None
    offset = alignment.get("qr_offset_px")
    qr = (plan.get("markers") or {}).get("qr") or {}
    if not offset or not qr:
        return None
    dx, dy = alignment.get("file_offset_mm", [0, 0])
    bounds = (qr["x"] + dx, qr["y"] + dy,
              qr["x"] + qr["size"] + dx, qr["y"] + qr["size"] + dy)
    shift_back = np.array([[1., 0., -offset[0]], [0., 1., -offset[1]], [0., 0., 1.]])
    return bounds, shift_back


def _layer_image_to_mm(h: np.ndarray, alignment: dict, layer_index: int) -> np.ndarray:
    offset = (alignment.get("layer_offsets_px") or {}).get(str(layer_index))
    if offset is None:
        offset = (alignment.get("layer_offsets_px") or {}).get(layer_index)
    if not offset:
        return h
    shift = offset["offset_px"] if isinstance(offset, dict) else offset
    return h @ np.array([[1., 0., -shift[0]], [0., 1., -shift[1]], [0., 0., 1.]])


def _within_qr(polygon, bounds: tuple[float, float, float, float]) -> bool:
    if len(polygon) == 0:
        return False
    points = np.asarray(polygon, float)
    return (points[:, 0].min() >= bounds[0] - .01 and
            points[:, 1].min() >= bounds[1] - .01 and
            points[:, 0].max() <= bounds[2] + .01 and
            points[:, 1].max() <= bounds[3] + .01)


def _marker_region_image_to_mm(h: np.ndarray, alignment: dict, polygon,
                               qr_local=None) -> np.ndarray:
    """Use the photographed position of one marker/label; retain file millimetres."""
    if qr_local and _within_qr(polygon, qr_local[0]):
        return h @ qr_local[1]
    for feature in (alignment.get("marker_feature_adjustments") or {}).values():
        if _within_qr(polygon, feature["bounds_mm"]):
            return h @ np.linalg.inv(np.asarray(feature["pixel_transform"], float))
    return h


def _marker_polygons_mask(polygons: list, h: np.ndarray, shape: tuple[int, int],
                          alignment: dict, qr_local=None,
                          edge_fraction: float | None = None) -> np.ndarray:
    """Measure an engraved marker layer with each identifiable fragment aligned."""
    grouped: dict[tuple[float, ...], tuple[np.ndarray, list]] = {}
    for polygon in polygons:
        local_h = _marker_region_image_to_mm(h, alignment, polygon, qr_local)
        key = tuple(np.round(local_h.ravel(), 9))
        grouped.setdefault(key, (local_h, []))[1].append(polygon)
    mask = np.zeros(shape, bool)
    for local_h, shapes in grouped.values():
        kwargs = {} if edge_fraction is None else {"edge_fraction": edge_fraction}
        mask |= ph.layer_mask(shapes, local_h, shape, **kwargs)
    return mask


FRAME_MARGIN_MM = 0.4   # pixels this close to the frame's inner edge are shadow and bevel, not engraving (DEC-049)


def _visible_surface_mask(shape: tuple[int, int], alignment: dict, include_window: bool = True) -> np.ndarray | None:
    """Pixels that show the plate: not beyond the right edge of a plate, not under the frame of a framed work."""
    result = None
    edge = alignment.get("visible_right_surface_edge") or []
    if len(edge) >= 2:
        height, width = shape
        result = np.ones(shape, bool)
        y0, y1 = max(0, edge[0][0]-100), min(height, edge[-1][0]+101)
        boundary = np.interp(np.arange(y0, y1), [p[0] for p in edge], [p[1] for p in edge])
        for y, x in zip(range(y0, y1), boundary):
            result[y, max(0, min(width, round(x))):] = False
    window = alignment.get("window_px")
    if include_window and window:
        import cv2
        inside = np.zeros(shape, np.uint8)
        cv2.fillConvexPoly(inside, np.round(np.asarray(window, float)).astype(np.int32), 1)
        px_per_mm = (alignment.get("px_per_mm") or ((alignment.get("anchoring") or {}).get("details") or {}).get("px_per_mm") or 20.0)
        k = int(max(3, round(FRAME_MARGIN_MM * px_per_mm))) | 1
        inside = cv2.erode(inside, np.ones((k, k), np.uint8)).astype(bool)
        result = inside if result is None else result & inside
    return result


def _sample_marker_subfeature(rgb: np.ndarray, h: np.ndarray, regions: list[dict], name: str,
                              dx: float, dy: float, alignment: dict, qr_local=None,
                              visible_surface=None) -> dict | None:
    polygons = _rect_polygons(regions, dx, dy)
    if not polygons:
        return None
    mask = _marker_polygons_mask(polygons, h, rgb.shape[:2], alignment, qr_local, edge_fraction=0.0)
    if visible_surface is not None:
        mask &= visible_surface
    try:
        lab, pixels = ph.sample_lab(rgb, mask)
    except ph.PhotoError as exc:
        return {"name": name, "measured_lab": None, "pixels": int(mask.sum()), "error": str(exc)}
    return {"name": name, "measured_lab": lab, "pixels": pixels,
            "interpretation": "RAW camera-relative appearance of the engraved mark"}


def _sample_subfeature(rgb: np.ndarray, h: np.ndarray, regions: list[dict], name: str,
                       dx: float = 0.0, dy: float = 0.0) -> dict | None:
    """Measure one named area without eroding tiny text/module rectangles."""
    polygons = _rect_polygons(regions, dx, dy)
    if not polygons:
        return None
    mask = ph.layer_mask(polygons, h, rgb.shape[:2], edge_fraction=0.0)
    try:
        lab, pixels = ph.sample_lab(rgb, mask)
    except ph.PhotoError as exc:
        return {"name": name, "measured_lab": None, "pixels": int(mask.sum()), "error": str(exc)}
    return {"name": name, "measured_lab": lab, "pixels": pixels,
            "interpretation": "RAW camera-relative appearance of the engraved mark"}


def _clean_witness_mask(clean_layer: lb.Layer, other_layers: list[lb.Layer], h: np.ndarray,
                        shape: tuple[int, int], qr_local=None, alignment=None) -> np.ndarray:
    """Keep cleaned titanium that later engraving did not overwrite, for an isolated cleaning readout. The cleaned
    plate shows only where no later layer engraved (often a ring at the edge and the gaps between elements), so the
    plate rectangle is not shrunk by the usual share of its side; a guard of one millimetre around every later
    outline and along the plate edge keeps engraved edges out of the sample."""
    import cv2

    px_per_mm = float(np.sqrt(abs(np.linalg.det(np.linalg.inv(np.asarray(h, float))[:2, :2]))))
    guard = int(max(3, round(CLEAN_GUARD_MM * px_per_mm))) | 1
    clean = cv2.erode(ph.layer_mask([r.polygon for r in clean_layer.regions], h, shape, edge_fraction=0.0).astype(np.uint8),
                      np.ones((guard, guard), np.uint8)).astype(bool)
    covered = np.zeros(shape, np.uint8)
    mm_to_image = np.linalg.inv(h).astype(np.float32)
    alignment = alignment or {}
    for layer in other_layers:
        layer_h = _layer_image_to_mm(h, alignment, layer.index)
        layer_to_image = np.linalg.inv(layer_h).astype(np.float32) if layer_h is not h else mm_to_image
        for region in layer.regions:
            if not region.polygon:
                continue
            matrix = (np.linalg.inv(_marker_region_image_to_mm(h, alignment, region.polygon, qr_local))
                      if layer.name == "Markers and labels" else layer_to_image)
            pts = cv2.perspectiveTransform(np.array([region.polygon], np.float32), matrix)[0]
            cv2.fillPoly(covered, [np.round(pts).astype(np.int32)], 1)
    covered = cv2.dilate(covered, np.ones((guard, guard), np.uint8))
    return clean & (covered == 0)


def _small_path_mask(layer: lb.Layer, image_to_mm: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Sample tiny vector strokes/glyphs when 20% interior erosion removes every pixel."""
    mm_to_image = np.linalg.inv(image_to_mm)
    mask = np.zeros(shape, np.uint8)
    for region in layer.regions:
        if region.kind not in ("path", "rect") or len(region.polygon) < 2:
            continue
        polygon = np.asarray(region.polygon, np.float32)
        points = cv2.perspectiveTransform(polygon[None], mm_to_image)[0]
        if not np.isfinite(points).all():
            continue
        pixels = np.round(points).astype(np.int32)
        if len(points) >= 3 and cv2.contourArea(polygon) > .001:
            cv2.fillPoly(mask, [pixels], 1)
        else:
            # Nominal 0.08 mm sampling corridor, not an optical spot diameter.
            a = cv2.perspectiveTransform(np.float32([[[polygon[0, 0], polygon[0, 1]],
                                                       [polygon[0, 0] + .08, polygon[0, 1]]]]), mm_to_image)[0]
            thickness = max(2, min(12, int(round(np.linalg.norm(a[1] - a[0])))))
            cv2.polylines(mask, [pixels], False, 1, thickness)
    return mask.astype(bool)


def _farthest_pair(pts: np.ndarray) -> tuple[float, int, int] | None:
    """(distance, i, j) of the two farthest points, i < j; ties go to the larger (i, j) as in a plain double loop.

    Only vertices of the convex hull can be that far apart, so a path of thousands of flattened curve points
    costs a few hundred distances instead of millions (REQ-023 made outlines much denser).
    """
    if len(pts) < 2:
        return None
    index = (cv2.convexHull(np.ascontiguousarray(pts, np.float32).reshape(-1, 1, 2), returnPoints=False).ravel()
             if len(pts) > 8 else np.arange(len(pts)))
    hull = np.asarray(pts, np.float32)[index]
    dist = np.linalg.norm(hull[:, None, :] - hull[None, :, :], axis=2)
    best = float(dist.max())
    a, b = np.nonzero(dist >= best * (1 - 1e-6))
    pairs = [(min(index[x], index[y]), max(index[x], index[y])) for x, y in zip(a, b) if x != y]
    if not pairs:
        return None
    i, j = max(pairs)
    return float(np.linalg.norm(np.asarray(pts, np.float32)[j] - np.asarray(pts, np.float32)[i])), int(i), int(j)


def _line_metrics(rgb: np.ndarray, h: np.ndarray, layer: lb.Layer, planned_layer: dict | None = None) -> dict | None:
    """Estimate photographed vector-line visibility, continuity and apparent trace width.

    The measured width is the visible material mark in the photograph, not an optical beam/spot diameter.
    """
    import cv2

    paths = [region.polygon for region in layer.regions if region.kind == "path" and len(region.polygon) >= 2]
    if not paths:
        return None
    lab = cv2.cvtColor(np.asarray(np.clip(rgb, 0, 1), np.float32), cv2.COLOR_RGB2LAB)[:, :, 0]
    mm_to_image = np.linalg.inv(h).astype(np.float32)
    offsets = np.arange(-0.5, 0.5001, 0.025, dtype=np.float32)
    outer = np.abs(offsets) >= 0.3
    result = []
    for region_index, path in ((i, r.polygon) for i, r in enumerate(layer.regions)
                               if r.kind == "path" and len(r.polygon) >= 2):
        pts = np.asarray(path, np.float32)
        pair = _farthest_pair(pts)
        if pair is None or pair[0] <= 0.1:
            continue
        length, i, j = pair
        start, end = pts[i], pts[j]
        direction = (end - start) / length
        normal = np.array([-direction[1], direction[0]], np.float32)
        stations = max(32, min(600, int(round(length * 10))))
        t = np.linspace(0.05, 0.95, stations, dtype=np.float32)
        centers = start[None, :] + (end - start)[None, :] * t[:, None]
        samples_mm = centers[:, None, :] + offsets[None, :, None] * normal[None, None, :]
        px = cv2.perspectiveTransform(samples_mm.reshape(1, -1, 2), mm_to_image)[0].reshape(stations, len(offsets), 2)
        values = cv2.remap(lab, px[:, :, 0].astype(np.float32), px[:, :, 1].astype(np.float32),
                           cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan)
        # A manually aligned photograph can put some lines outside the image.
        # Those stations have no samples; they are missing evidence, not a reason
        # to abort the entire check with ``All-NaN slice encountered``.
        baseline = np.full(stations, np.nan, dtype=np.float32)
        has_background = np.isfinite(values[:, outer]).any(axis=1)
        baseline[has_background] = np.nanmedian(values[has_background][:, outer], axis=1)
        delta = values - baseline[:, None]
        has_signal = np.isfinite(delta).any(axis=1)
        peak = np.full(stations, -1, dtype=np.int32)
        peak[has_signal] = np.nanargmax(np.abs(delta[has_signal]), axis=1)
        peak_contrast = np.full(stations, np.nan, dtype=np.float32)
        rows = np.flatnonzero(has_signal)
        peak_contrast[rows] = np.abs(delta[rows, peak[rows]])
        contrast = float(np.nanmedian(peak_contrast)) if np.isfinite(peak_contrast).any() else 0.0
        threshold = max(3.0, contrast * 0.25)
        visible = np.isfinite(peak_contrast) & (peak_contrast >= threshold)
        widths = []
        if contrast >= 3.0:
            for row, center_i in enumerate(peak):
                signal = np.abs(delta[row])
                if not np.isfinite(signal[center_i]) or signal[center_i] < threshold:
                    continue
                left = right = int(center_i)
                while left > 0 and np.isfinite(signal[left - 1]) and signal[left - 1] >= threshold:
                    left -= 1
                while right + 1 < len(offsets) and np.isfinite(signal[right + 1]) and signal[right + 1] >= threshold:
                    right += 1
                widths.append(float(offsets[right] - offsets[left] + 0.025))
        result.append({"region_index": region_index, "length_mm": float(length), "visible": contrast >= 3.0,
                       "median_contrast_Lstar": round(contrast, 2),
                       "continuity_percent": round(float(visible.mean() * 100), 1),
                       "apparent_trace_width_mm": None if not widths else round(float(np.median(widths)), 4)})
    if not result:
        return None
    widths = [x["apparent_trace_width_mm"] for x in result if x["apparent_trace_width_mm"] is not None]
    summary = {"line_count": len(result), "visible_line_count": sum(x["visible"] for x in result),
            "median_continuity_percent": round(float(np.median([x["continuity_percent"] for x in result])), 1),
            "median_contrast_Lstar": round(float(np.median([x["median_contrast_Lstar"] for x in result])), 2),
            "median_apparent_trace_width_mm": None if not widths else round(float(np.median(widths)), 4),
            "lines": result,
            "limitation": "Width is the visible engraved trace at this photo resolution; it is not the optical spot diameter."}
    groups = []
    for group in (planned_layer or {}).get("measurement_groups", []):
        indices = set(range(group["region_start"], group["region_start"] + group["region_count"]))
        items = [line for line in result if line["region_index"] in indices]
        if not items:
            continue
        group_widths = [line["apparent_trace_width_mm"] for line in items if line["apparent_trace_width_mm"] is not None]
        groups.append({"name": group["name"], "spacing_um": group.get("spacing_um"), "line_count": len(items),
                       "visible_line_count": sum(line["visible"] for line in items),
                       "median_continuity_percent": round(float(np.median([line["continuity_percent"] for line in items])), 1),
                       "median_contrast_Lstar": round(float(np.median([line["median_contrast_Lstar"] for line in items])), 2),
                       "median_apparent_trace_width_mm": None if not group_widths else round(float(np.median(group_widths)), 4)})
    if groups:
        summary["groups"] = groups
    return summary


def _element_anchor(anchor, work_layers, report) -> np.ndarray:
    layer = next((item for item in work_layers if item.index == anchor["layer_index"]), None)
    if layer is None or not 0 <= anchor["region_index"] < len(layer.regions):
        raise ph.PhotoError("the selected LightBurn detail no longer exists")
    polygon = np.asarray(layer.regions[anchor["region_index"]].polygon, np.float32)
    if len(polygon) != 4 or cv2.contourArea(polygon) < .1:
        raise ph.PhotoError("the selected LightBurn detail needs four distinct corners")
    photo_corners = anchor["corners_px"]
    ph.validate_corners(photo_corners)
    report["alignment"].update(method="element anchor", anchor_element=f"{layer.name} #{anchor['region_index'] + 1}",
                               anchor_layer_index=layer.index)
    return cv2.getPerspectiveTransform(np.asarray(photo_corners, np.float32), polygon)


def _identifier_at_plan_qr(img_bgr, image_to_mm, qr, dx, dy) -> str | None:
    """Read only the QR's LightBurn location, including a quiet margin."""
    module = float(qr.get("module", .25))
    # The engraved QR on dark titanium often needs more unmarked metal around
    # it than the nominal four-module quiet zone. Try a second, wider crop if
    # the tight high-resolution patch is unreadable.
    for pad, px_per_mm in ((max(.8, 4 * module), 32.), (max(2., 8 * module), 20.)):
        x, y = float(qr["x"]) + dx - pad, float(qr["y"]) + dy - pad
        side = float(qr["size"]) + 2 * pad
        to_patch = np.array([[px_per_mm, 0, -x * px_per_mm],
                             [0, px_per_mm, -y * px_per_mm], [0, 0, 1.]])
        pixels = max(20, int(round(side * px_per_mm)))
        patch = cv2.warpPerspective(img_bgr, to_patch @ image_to_mm, (pixels, pixels),
                                    borderValue=(255, 255, 255))
        seen = ph.read_identifier(patch)
        if seen:
            return seen
    return None


def _read_aligned_identifier(img_bgr, image_to_mm, markers, area, dx, dy) -> str | None:
    return (_identifier_at_plan_qr(img_bgr, image_to_mm, markers["qr"], dx, dy)
            or ph.read_identifier_rectified(img_bgr, image_to_mm, area))


def _plate_corners_with_orientation(img_bgr, corners, area, expected, markers, dx, dy) -> tuple[np.ndarray, str | None]:
    """Use the QR at its known file position to orient physical photo corners."""
    physical = [tuple(point) for point in corners]
    ph.validate_corners(physical)
    direct = ph.homography_from_corners(physical, area)
    mismatch = None
    verified = []
    for step in (1, -1):
        for start in range(4):
            ordered = [physical[(start + step * i) % 4] for i in range(4)]
            h = ph.homography_from_corners(ordered, area)
            seen = _identifier_at_plan_qr(img_bgr, h, markers["qr"], dx, dy)
            if seen == expected:
                verified.append(h)
            if seen:
                mismatch = seen
    if verified:
        if len(verified) == 1:
            return verified[0], expected
        # Some older plate layouts placed the QR on a symmetry axis. Its
        # location then verifies the job but not its handedness; marker IDs
        # break the tie when they remain readable.
        detected = ph.detect_marker_candidates(img_bgr)
        scored = []
        for h in verified:
            for found in detected:
                errors = []
                for marker in markers["aruco"]:
                    if marker["id"] not in found:
                        continue
                    image_center = np.asarray(found[marker["id"]], np.float32).mean(axis=0)
                    file_center = cv2.perspectiveTransform(image_center[None, None], h)[0, 0]
                    wanted = np.array([marker["x"] + dx + marker["size"] / 2,
                                       marker["y"] + dy + marker["size"] / 2])
                    errors.append(float(np.linalg.norm(file_center - wanted)))
                if len(errors) >= 2:
                    scored.append((float(np.median(errors)), h))
        if scored:
            return min(scored, key=lambda item: item[0])[1], expected
        if any(np.allclose(h, direct) for h in verified):
            return direct, expected
        return verified[0], expected
    if mismatch:
        raise ph.PhotoError(f"the photographed plate is {mismatch} but the LightBurn file is {expected}")
    seen = _read_aligned_identifier(img_bgr, direct, markers, area, dx, dy)
    if seen and seen != expected:
        raise ph.PhotoError(f"the photographed plate is {seen} but the LightBurn file is {expected}")
    return direct, seen


def _element_status(details: dict) -> dict:
    """{layer index: {region index: status}} of the elements the anchoring classified (JSON keys are strings)."""
    out: dict = {}
    for (layer_index, region_index), status in zip(details["element_refs"], details["statuses"]):
        out.setdefault(str(layer_index), {})[str(region_index)] = status
    return out


TONAL_BINS = 16
TONAL_BLUR_MM = 0.25    # dithered dots are far finer than the photograph resolves: compare local averages, not pixels


def _picture_gray(png: bytes) -> np.ndarray | None:
    """The embedded picture as grey levels 0..1 (black engraves); a transparent area counts as white."""
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.dtype != np.uint8:
        img = (img.astype(np.float32) / (65535.0 if img.dtype == np.uint16 else 1.0) * 255).clip(0, 255).astype(np.uint8)
    if img.ndim == 2:
        return img.astype(np.float32) / 255.0
    gray = cv2.cvtColor(img[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    if img.shape[2] == 4:
        alpha = img[..., 3].astype(np.float32) / 255.0
        gray = gray * alpha + (1 - alpha)
    return gray


def _prefer_reading(rho: float, other: float | None) -> bool:
    """Is a reading with this rank correlation better than the other? A clear positive agreement wins; with none, the stronger."""
    if other is None:
        return True
    return rho > other if max(rho, other) >= 0.3 else abs(rho) > abs(other)


def _tonal_profile(corrected_rgb: np.ndarray, layer_h: np.ndarray, layer, shape: tuple[int, int],
                   allowed: np.ndarray | None) -> dict | None:
    """How the grey levels of an image object came out on the metal: L* of the photograph against the grey level of the
    embedded picture at the same place (REQ-004, tonal evaluation).

    The picture is laid over the photograph through the alignment of the work. Which edge of the picture is up is not
    stated by the file, so both are tried and the one that agrees better is kept and reported. The grey levels are
    those of the picture as stored, before LightBurn's brightness, contrast and gamma, and dithering is not modelled:
    this is a measurement of what was photographed, not a prediction.
    """
    mm_to_image = np.linalg.inv(np.asarray(layer_h, float))
    lab = cv2.cvtColor(np.asarray(np.clip(corrected_rgb, 0, 1), np.float32), cv2.COLOR_RGB2LAB)
    best = None
    for region in layer.regions:
        bm = region.bitmap
        gray = _picture_gray(bm["png"]) if bm and bm.get("png") else None
        if gray is None:
            continue
        rows, cols = gray.shape
        a, b, c, d, e, f = bm["matrix"]
        local_to_mm = np.array([[a, c, e], [b, d, f], [0, 0, 1.0]])
        px_per_mm = float(np.sqrt(abs(np.linalg.det(mm_to_image[:2, :2]))))
        sigma = max(1.0, TONAL_BLUR_MM * px_per_mm)
        shrink = cv2.erode(cv2.fillConvexPoly(np.zeros(shape, np.uint8), np.round(cv2.perspectiveTransform(
            np.asarray(region.polygon, np.float32)[None], mm_to_image.astype(np.float32))[0]).astype(np.int32), 1),
            np.ones((int(max(3, 2 * sigma)) | 1,) * 2, np.uint8)).astype(bool)
        if allowed is not None:
            shrink &= allowed
        lit = [cv2.GaussianBlur(lab[:, :, c], (0, 0), sigma) for c in range(3)]
        for flip in (False, True):
            to_local = np.array([[bm["w"] / cols, 0, -bm["w"] / 2],
                                 [0, (-1 if flip else 1) * bm["h"] / rows, (bm["h"] / 2 if flip else -bm["h"] / 2)],
                                 [0, 0, 1.0]])
            warp = mm_to_image @ local_to_mm @ to_local
            laid = cv2.GaussianBlur(cv2.warpPerspective(gray, warp, (shape[1], shape[0]), flags=cv2.INTER_AREA), (0, 0), sigma)
            inside = shrink & (cv2.warpPerspective(np.ones_like(gray), warp, (shape[1], shape[0])) > 0.999)
            if int(inside.sum()) < 400:
                continue
            ys, xs = np.nonzero(inside)
            pick = np.random.default_rng(3).choice(len(xs), min(len(xs), 60000), replace=False)
            g = laid[ys[pick], xs[pick]]
            lightness, ca, cb = (lit[c][ys[pick], xs[pick]] for c in range(3))
            rank = lambda v: np.argsort(np.argsort(v)).astype(np.float64)
            rho_of = lambda v: float(np.corrcoef(rank(g), rank(v))[0, 1]) if np.ptp(g) > 1e-6 and np.ptp(v) > 1e-6 else 0.0
            rho = rho_of(lightness)
            # Engraved (black) parts are expected to come out darker, so a positive relation is preferred; a picture
            # turned over with an inverted tone cannot be told from the plain one, and this is the reading that is kept.
            if _prefer_reading(rho - (0.02 if flip else 0.0), None if best is None else best["rho"]):     # a tie keeps the plain reading
                edges = np.linspace(0, 1, TONAL_BINS + 1)
                which = np.clip(np.digitize(g, edges) - 1, 0, TONAL_BINS - 1)
                bins = []
                for i in range(TONAL_BINS):
                    sel = which == i
                    if sel.sum() < 50:
                        continue
                    l_, a_, b_ = (float(np.median(v[sel])) for v in (lightness, ca, cb))
                    bins.append({"gray": round(float((edges[i] + edges[i + 1]) / 2), 3), "L": round(l_, 2), "a": round(a_, 2),
                                 "b": round(b_, 2), "C": round(float(np.hypot(a_, b_)), 2), "n": int(sel.sum())})
                best = {"samples": int(len(g)), "rho": round(rho, 3), "rho_a": round(rho_of(ca), 3), "rho_b": round(rho_of(cb), 3),
                        "rho_chroma": round(rho_of(np.hypot(ca, cb)), 3), "vertical_flip": flip, "bins": bins}
    if best is None or len(best["bins"]) < 3:
        return None
    levels = [x["L"] for x in best["bins"]]
    adjusted = (layer.image_summary() or {}).get("adjusted") or {}
    summary = layer.image_summary() or {}
    best["power_range"] = None
    if summary.get("dither") == "grayscale":
        # LightBurn's documentation: grayscale varies the power between Min (lightest) and Max (darkest)
        try:
            low, high = float(layer.source_settings["minPower"]["Value"]), float(layer.source_settings["maxPower"]["Value"])
            best["power_range"] = [low, high]
            for item in best["bins"]:
                item["power_pct"] = round(low + (high - low) * (1 - item["gray"]), 2)
        except (KeyError, TypeError, ValueError):
            pass
    best["adjustments"] = adjusted                       # applied by LightBurn before engraving; the grey axis is before them
    best["adjustments_keep_order"] = not any(tag not in lb.MONOTONE_ADJUSTMENTS for tag in adjusted)
    best.update(range_L=round(max(levels) - min(levels), 2), dark_L=levels[0], light_L=levels[-1],
                evidence="clear" if abs(best["rho"]) >= 0.5 else "weak",
                limitation="Grey levels are those of the stored picture, before LightBurn's brightness, contrast and gamma; dithering is not "
                           "modelled. Which edge of the picture is up is taken from the better positive agreement: a turned picture with an inverted tone looks the same. "
                           "The power of a bin follows the settings of the layer: the lightest grey gets Min power, the darkest Max power, linearly between "
                           "(rule confirmed by the operator, Q-024).")
    return best


def _picture_silhouettes(project, image_to_mm: np.ndarray, shape: tuple[int, int]) -> np.ndarray | None:
    """Mask, in photograph pixels, of the strongest edges (silhouettes) of the picture stored in the file."""
    regions = [r for layer in project.layers for r in layer.regions if r.bitmap and r.bitmap.get("png")]
    if not regions:
        return None
    region = max(regions, key=lambda r: r.width * r.height)
    gray = _picture_gray(region.bitmap["png"])
    if gray is None:
        return None
    n = 512
    small = cv2.GaussianBlur(cv2.resize(gray, (n, n), interpolation=cv2.INTER_AREA), (0, 0), 1.0)
    magnitude = cv2.magnitude(cv2.Sobel(small, cv2.CV_32F, 1, 0), cv2.Sobel(small, cv2.CV_32F, 0, 1))
    edges = (magnitude > np.percentile(magnitude, 94)).astype(np.uint8) * 255
    a, b, c, d, e, f = region.bitmap["matrix"]
    to_mm = np.array([[a, c, e], [b, d, f], [0, 0, 1.0]]) @ np.array(
        [[region.bitmap["w"] / n, 0, -region.bitmap["w"] / 2], [0, region.bitmap["h"] / n, -region.bitmap["h"] / 2], [0, 0, 1.0]])
    laid = cv2.warpPerspective(edges, np.linalg.inv(image_to_mm) @ to_mm, (shape[1], shape[0]), flags=cv2.INTER_NEAREST)
    return laid > 100


CLEAN_GUARD_MM = 1.0             # clean titanium is sampled this far from every later outline and from the plate edge
CLEAN_TITANIUM_MIN_L = 50.0      # cleaned titanium is light ...
CLEAN_TITANIUM_MAX_CHROMA = 15.0  # ... and nearly neutral; a first layer darker or more coloured is a background fill


def _looks_like_clean_titanium(lab) -> bool:
    return lab is not None and lab[0] >= CLEAN_TITANIUM_MIN_L and float(np.hypot(lab[1], lab[2])) <= CLEAN_TITANIUM_MAX_CHROMA


def _finished_work_cleaning_layer(project) -> int | None:
    """The layer of a finished work that cleans its plate before the engraving: run first, one filled rectangle that
    encloses everything else. Where later layers did not overwrite it, it shows the cleaned titanium of this very
    photograph, the reference that makes colours of different photographs comparable (DEC-056)."""
    layers = [layer for layer in project.layers if layer.regions]
    if len(layers) < 3:
        return None
    first = min(layers, key=_burn_order)
    if first.layer_type != "Scan" or len(first.regions) != 1:
        return None
    frame = first.regions[0]
    others = [region for layer in layers if layer is not first for region in layer.regions]
    if frame.kind != "rect" or not frame.closed or len(others) < 3:
        return None
    x0, y0 = min(r.x for r in others), min(r.y for r in others)
    x1, y1 = max(r.x + r.width for r in others), max(r.y + r.height for r in others)
    inside = (frame.x <= x0 + 0.05 and frame.y <= y0 + 0.05 and frame.x + frame.width >= x1 - 0.05 and frame.y + frame.height >= y1 - 0.05)
    return first.index if inside else None


def _burn_order(layer) -> tuple[float, int]:
    """LightBurn runs layers by priority, then by index; what is run later is on top where outlines overlap."""
    value = layer.source_settings.get("priority")
    try:
        priority = float(value.get("Value") if isinstance(value, dict) else value)
    except (TypeError, ValueError, AttributeError):
        priority = 0.0
    return priority, layer.index


def _covered_by_later_layers(layer, layers, h, alignment, shape, system_indices) -> np.ndarray | None:
    """Pixels of this layer's area that a layer run after it engraves again (DEC-050).

    The colour seen there belongs to the later layer, so it must not enter this layer's sample. Only filled areas of
    ``Scan``/``Image`` layers count; lines and the plate's service layers do not cover anything. A two-pixel
    guard avoids mixing the edge of the later engraving into the sample, as for the cleaning witness.
    """
    later = [other for other in layers if other.index != layer.index and other.index not in system_indices and
             other.regions and other.layer_type in ("Scan", "Image") and _burn_order(other) > _burn_order(layer)]
    if not later:
        return None
    covered = np.zeros(shape, bool)
    for other in later:
        regions = [r for r in other.regions if len(r.polygon) >= 3 and (r.closed or r.kind in ("rect", "bitmap"))]
        if regions:
            covered |= ph.layer_mask([r.polygon for r in regions], _layer_image_to_mm(h, alignment, other.index), shape,
                                     edge_fraction=0, holes_mm=[r.holes for r in regions])
    if not covered.any():
        return None
    return cv2.dilate(covered.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)


def _note_frame(rep: dict, alignment: dict) -> None:
    """Tell the operator which elements of a layer the frame hides: they are measured on the visible part only."""
    status = (alignment.get("element_status") or {}).get(str(rep["index"]))
    if not status:
        return
    partly = sum(v == "partly hidden" for v in status.values())
    hidden = sum(v == "hidden" for v in status.values())
    if partly or hidden:
        rep["frame"] = {"partly_hidden": partly, "hidden": hidden}
        rep["notes"].append(f"under the frame: {partly} elements are measured on their visible part, "
                            f"{hidden} are entirely hidden and not measured")


def _by_markers(img_bgr, markers: dict, expected: str | None, area, dx: float, dy: float, work_layers, report,
                plate_named: bool, linked: bool) -> np.ndarray | None:
    """Image -> file mm from the engraved markers once the identifier confirms them; None when no consistent set is found.

    A readable identifier of another plate or work stops the check. Four markers whose identifier cannot be read fit
    every plate or work of the same layout: they are accepted, with a warning, only for a photograph the operator linked
    to this plate or plan, whose identity is then the operator's and not a guess (REQ-003); otherwise the alignment is
    left to four placed corners (``identifier_unreadable``)."""
    candidates = ph.detect_marker_candidates(img_bgr)
    mismatch = None
    for found in candidates:
        try:
            h = ph.homography_from_markers(found, markers, dx, dy)
        except ph.PhotoError:
            continue
        seen = _read_aligned_identifier(img_bgr, h, markers, area, dx, dy)
        if seen == expected:
            report["alignment"].update(method="markers", marker_count=len(found), orientation_candidates=len(candidates),
                                       identifier_verified=True, identifier_read=seen)
            return h
        if seen:
            mismatch = seen
    if mismatch:
        raise ph.PhotoError(f"the photographed {'plate' if plate_named else 'work'} is {mismatch} but the LightBurn file is {expected}")
    report["alignment"]["marker_count"] = max(map(len, candidates), default=0)
    # Darkened titanium and a vertical mirror can defeat ArUco's square
    # detector. Find each engraved marker independently, then require one
    # consistent four-marker layout in the exact LightBurn millimetres.
    from . import registration
    matched = registration.register_markers(img_bgr, markers, dx, dy, expected, work_layers)
    if matched is None or not (len(matched.matches) == 4 or matched.method == "two marker + QR"):
        return None
    seen = _read_aligned_identifier(img_bgr, matched.image_to_mm, markers, area, dx, dy)
    if seen is None and matched.method == "two marker + QR":
        # The identifier was decoded directly from the located QR
        # before fitting; a full-frame rectification can make it
        # unreadable when the QR lies close to the work-area edge.
        seen = expected
    if seen and seen != expected:
        raise ph.PhotoError(f"the photographed {'plate' if plate_named else 'work'} is {seen} but the LightBurn file is {expected}")
    report["alignment"]["marker_count"] = len(matched.matches)
    if seen is None and not linked:
        report["alignment"]["identifier_unreadable"] = True
        return None
    report["alignment"].update(method=matched.method, marker_matches=matched.matches, residual_px=matched.residual_px,
                               reflected=matched.reflected, identifier_verified=(seen == expected), identifier_read=seen)
    if matched.qr_offset_px is not None:
        report["alignment"].update(qr_offset_px=list(matched.qr_offset_px),
                                   qr_used_as_anchor=matched.qr_used_as_anchor)
    if seen is None:
        report["warnings"].append(
            "Four engraved markers match the LightBurn geometry, but the QR identifier is unreadable; review the full layer overlay before accepting."
        )
    return matched.image_to_mm


def _align(store: Store, row, img_bgr, plate, plan, corners, anchor, work_layers, report,
           prefer_corners: bool = False, linked: bool = False) -> tuple:
    """Returns (image->mm homography, dx, dy). Raises PhotoError instead of guessing (REQ-003).

    ``plan`` is the plan of the plate, or the engraving plan the file names or the operator linked; ``linked`` says the
    operator uploaded the photograph for it. A plate or plan with markers is aligned by its markers and identifier, one
    path for both (DEC-010); an unmarked one, like a small-patch plate without registration (DEC-066 item 2), never looks
    for markers and is aligned like any work: by its elements or by four placed corners.
    """
    matrix_record = json.loads(row["data_json"] or "{}").get("matrix")
    if matrix_record and not (prefer_corners and corners):
        from . import matrix
        report["alignment"].update(method="material test grid", residual_px=matrix_record.get("residual_px"), reflected=False,
                                   matrix={"cols": matrix_record["cols"], "rows": matrix_record["rows"],
                                           "outlined_cells": matrix_record.get("outlined_cells")})
        return matrix.image_to_mm(matrix_record), 0.0, 0.0
    if plate is not None and plan is None:
        raise ph.PhotoError("the plate has no marker definition")
    dx, dy = pl.export_offset(plan) if plan is not None else (0.0, 0.0)
    marked = plan if plan is not None and plan.get("markers") and plan.get("markers_enabled", True) else None
    if marked is not None:
        ext = marked["markers"]["extent"]
        if plate is not None:
            clean = next((layer for layer in work_layers if layer.name.startswith("CLEAN-CROSSHATCH-") and
                          len(layer.regions) == 1), None)
            if clean is not None:
                # LightBurn lets the operator move the complete job on its bed.
                # Its cleaning rectangle has the same physical size as the plate
                # extent, so it locates the plan's markers in the *saved file*.
                cx, cy, cw, ch = _bbox(clean.regions)
                ew, eh = ext["max_x"] - ext["min_x"], ext["max_y"] - ext["min_y"]
                if abs(cw - ew) > .05 or abs(ch - eh) > .05:
                    raise ph.PhotoError("the cleaning rectangle size differs from the plate definition")
                dx, dy = cx - ext["min_x"], cy - ext["min_y"]
        report["alignment"]["file_offset_mm"] = [round(dx, 4), round(dy, 4)]
        area =(ext["min_x"] + dx, ext["min_y"] + dy, ext["max_x"] - ext["min_x"], ext["max_y"] - ext["min_y"])
        expected = plate["experiment_id"] if plate is not None else (marked["markers"].get("identifier") or marked.get("plan_identifier"))
        if prefer_corners and corners:
            h, seen = _plate_corners_with_orientation(img_bgr, corners, area, expected, marked["markers"], dx, dy)
            report["alignment"].update(method="manual", marker_count=0,
                                       identifier_verified=(seen == expected), identifier_read=seen,
                                       reflected=bool(np.linalg.det(h[:2, :2]) < 0))
            report["warnings"].append("The work corners were corrected manually; review every layer outline before accepting measurements.")
            return h, dx, dy
        h = _by_markers(img_bgr, marked["markers"], expected, area, dx, dy, work_layers, report, plate is not None, linked)
        if h is not None:
            return h, dx, dy
        count = report["alignment"].get("marker_count", 0)
        if anchor:
            return _element_anchor(anchor, work_layers, report), dx, dy
        if corners:
            # A known plate can still be aligned when its engraved ArUco marks are unreadable.
            # The operator supplies the four outer work corners; keep the plan's export offset so
            # its layer masks and marker submeasurements remain in the same LightBurn coordinates.
            h, seen = _plate_corners_with_orientation(img_bgr, corners, area, expected, marked["markers"], dx, dy)
            report["alignment"].update(method="manual", marker_count=count,
                                       identifier_verified=(seen == expected), identifier_read=seen,
                                       reflected=bool(np.linalg.det(h[:2, :2]) < 0))
            if seen != expected:
                report["warnings"].append(
                    "Manual alignment was used for this plate; its QR identifier could not be verified. Check the layer overlay before accepting measurements."
                )
            return h, dx, dy
        if report["alignment"].get("identifier_unreadable"):
            raise ph.PhotoError("four registration markers match the LightBurn geometry, but the identifier QR code cannot be read, so the "
                                "photograph is not confirmed to show this plate or work: place the four corners of the work, or upload the "
                                "photograph from its plate or plan")
        if plate is not None:
            if count < 3:
                raise ph.PhotoError(f"only {count} registration markers detected; at least three are needed")
            raise ph.PhotoError("the experiment identifier QR code could not be read in the aligned photograph")
        # The markers of a finished work may be illegible: its own drawing can still be found below (DEC-010).
    if prefer_corners and corners:
        if not work_layers:
            raise ph.PhotoError("the LightBurn file has no geometry to align to")
        report["alignment"]["method"] = "manual"
        return ph.homography_from_corners([tuple(c) for c in corners], _bbox([r for layer in work_layers for r in layer.regions])), dx, dy
    from . import anchoring, registration
    diagnostics: dict = {}
    matched = anchoring.register(img_bgr, work_layers, diagnostics)
    report["alignment"]["anchoring"] = diagnostics
    if matched is not None:
        return _anchored(report, matched), dx, dy
    if any(r.bitmap and r.bitmap.get("png") for layer in work_layers for r in layer.regions):
        from . import picturing
        picture_diagnostics: dict = {}
        matched = picturing.register(img_bgr, work_layers, picture_diagnostics)
        report["alignment"]["picture"] = picture_diagnostics
        if matched is not None:
            d = matched.details
            hidden = d["hidden_mm"]
            report["alignment"].update(method=matched.method, element_matches=[], residual_px=matched.residual_px,
                                       reflected=matched.reflected, window_px=d["window_px"], px_per_mm=d["px_per_mm"],
                                       hidden_mm=hidden, frame_sides=d["frame_sides"], window_found=d["window_found"])
            report["warnings"].append(
                f"The picture of the file was matched to the photograph (correlation {d['zncc']:.2f}). The frame hides about "
                f"{hidden['left']:g} mm on the left, {hidden['right']:g} on the right, {hidden['top']:g} at the top and "
                f"{hidden['bottom']:g} at the bottom; that part is not measured.")
            for side in ("left", "right", "top", "bottom"):            # REQ-027: an assumed margin is said, side by side
                if not d["frame_sides"][side]:
                    report["warnings"].append(f"The edge of the frame was not found on the {side} side: a margin of "
                                              f"{picturing.FALLBACK_INSET * 100:g}% ({hidden[side]:g} mm) is assumed there.")
            return matched.image_to_mm, dx, dy
    matched = registration.register_geometry(img_bgr, work_layers)
    if matched is not None:
        # Three whole shapes can agree by chance in a dense drawing (a mirrored fit of a lion of parallel strokes
        # was accepted once). The fit is only a start: the elements of the file must confirm it independently.
        confirmation: dict = {}
        confirmed = anchoring.confirm(img_bgr, work_layers, matched.image_to_mm, confirmation)
        report["alignment"]["geometry_confirmation"] = confirmation
        if confirmed is not None:
            return _anchored(report, confirmed), dx, dy
        outlines = sum(1 for e in anchoring.elements_from_layers(work_layers) if not e.boundary and len(e.points) >= 25)
        if outlines < WHOLE_SHAPE_GUARD_MIN_OUTLINES:
            # A simple work: its few whole shapes are distinct, so a fit of three of them is real evidence, and
            # there are too few outlines to confirm it by anchors. The operator is told it is unconfirmed.
            report["alignment"].update(method=matched.method, element_matches=matched.matches,
                                       residual_px=matched.residual_px, reflected=matched.reflected)
            if matched.method == "single distinctive detail":
                report["warnings"].append(
                    "Only one distinctive detail was matched; distant outlines are extrapolated from it and require careful review."
                )
            if confirmation.get("refused"):
                report["warnings"].append(
                    "The fit of whole shapes was not confirmed by element anchors; review the layer overlay before accepting."
                )
            return matched.image_to_mm, dx, dy
    if anchor:
        return _element_anchor(anchor, work_layers, report), dx, dy
    if corners:
        if not work_layers:
            raise ph.PhotoError("the LightBurn file has no geometry to align to")
        area = _bbox([r for layer in work_layers for r in layer.regions])
        report["alignment"]["method"] = "manual"
        return ph.homography_from_corners([tuple(c) for c in corners], area), dx, dy
    raise ph.PhotoError("no reliable combination of LightBurn details was found: place the four image corners of the work")


WHOLE_SHAPE_GUARD_MIN_OUTLINES = 30   # from this many outlines on, a fit of three whole shapes must be confirmed by anchors


def _anchored(report: dict, matched) -> np.ndarray:
    """Report an element-anchored registration: anchors, the visible window, what the frame hides."""
    details = matched.details
    report["alignment"].update(method=matched.method, element_matches=matched.matches,
                               residual_px=matched.residual_px, reflected=matched.reflected,
                               window_px=details["window_px"], window_found=details["window_found"],
                               # what the frame hides, per side of the plate in mm, and on which sides its edge was found (REQ-024)
                               hidden_mm=details["hidden_side_mm"], frame_sides=details["frame_sides"],
                               element_status=_element_status(details))
    counts = details["counts"]
    if counts["partly hidden"] or counts["hidden"]:
        report["warnings"].append(
            f"The frame hides part of the work: {counts['partly hidden']} elements are measured on their visible part only, "
            f"{counts['hidden']} are entirely under it and are not measured; their positions are inferred from the matched elements.")
    return matched.image_to_mm


def _overlay_override(pair: dict, *, translation_fraction=None, rotation_degrees=None, scale_factor=None,
                      mirror_horizontal=None, mirror_vertical=None) -> dict:
    """Convert the editor's whole-drawing CSS transform into an image→mm map."""
    rotation_degrees = 0. if rotation_degrees is None else rotation_degrees
    if (not isinstance(rotation_degrees, (int, float)) or not np.isfinite(rotation_degrees)
            or rotation_degrees < 0 or rotation_degrees > 360):
        raise IngestError("the overlay rotation must be between 0 and 360 degrees")
    scale_factor = 1. if scale_factor is None else scale_factor
    if (isinstance(scale_factor, bool) or not isinstance(scale_factor, (int, float))
            or not np.isfinite(scale_factor) or scale_factor < .1 or scale_factor > 8):
        raise IngestError("the overlay scale must be between 10 and 800 percent")
    mirror_horizontal = False if mirror_horizontal is None else mirror_horizontal
    mirror_vertical = False if mirror_vertical is None else mirror_vertical
    if not isinstance(mirror_horizontal, bool) or not isinstance(mirror_vertical, bool):
        raise IngestError("the overlay mirror settings must be boolean")
    translation_fraction = [0., 0.] if translation_fraction is None else translation_fraction
    if (not isinstance(translation_fraction, list) or len(translation_fraction) != 2 or
            any(not isinstance(v, (int, float)) or not np.isfinite(v) or abs(v) > 1 for v in translation_fraction)):
        raise IngestError("the overlay displacement must stay inside the photograph")
    previous = (pair.get("check") or {}).get("alignment") or {}
    previous_h = previous.get("image_to_mm")
    size = (pair.get("check") or {}).get("image_size")
    if not previous_h or not size:
        raise IngestError("check and align the photograph before adjusting its contours")
    dx, dy = translation_fraction[0] * size[0], translation_fraction[1] * size[1]
    theta = np.deg2rad(rotation_degrees % 360)
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    cx, cy = size[0] / 2, size[1] / 2
    translate = lambda x, y: np.array([[1., 0., x], [0., 1., y], [0., 0., 1.]])
    inverse_rotation = np.array([[cos_t, sin_t, 0.], [-sin_t, cos_t, 0.], [0., 0., 1.]])
    sx = scale_factor * (-1 if mirror_horizontal else 1)
    sy = scale_factor * (-1 if mirror_vertical else 1)
    inverse_scale = np.diag([1 / sx, 1 / sy, 1.])
    # CSS previews T(shift) · T(center) · R(angle) · S(scale, mirror) · T(-center).
    # Compose its inverse with the current image→mm map; LightBurn mm are untouched.
    adjusted = (np.asarray(previous_h, dtype=float) @ translate(cx, cy) @ inverse_scale @ inverse_rotation @
                translate(-cx, -cy) @ translate(-dx, -dy))
    return {"image_to_mm": adjusted.tolist(), "rotation_degrees": float(rotation_degrees),
            "scale_factor": float(scale_factor), "mirror_horizontal": mirror_horizontal,
            "mirror_vertical": mirror_vertical,
            "reflected": bool(previous.get("reflected", False)) ^ (mirror_horizontal ^ mirror_vertical),
            "file_offset_mm": previous.get("file_offset_mm", [0., 0.])}


def snap_pair_overlay(store: Store, pair_id: int, *, translation_fraction=None, rotation_degrees=None,
                      scale_factor=None, mirror_horizontal=None, mirror_vertical=None) -> list[dict]:
    """Find photo contours matching the previewed whole-drawing transform, without saving it."""
    row = _pair_row(store, pair_id)
    _guard_mutable(row)
    pair = get_pair(store, pair_id)
    override = _overlay_override(pair, translation_fraction=translation_fraction,
                                 rotation_degrees=rotation_degrees, scale_factor=scale_factor,
                                 mirror_horizontal=mirror_horizontal, mirror_vertical=mirror_vertical)
    try:
        project = lb.parse_file(row["lightburn_path"])
        _normalize_project_to_plan(project, pl.get_plan(store, row["plan_id"]) if row["plan_id"] else None)
        img_bgr = ph.decode_image(row["photo_path"], allow_non_raw=non_raw_allowed(store))
    except (lb.LightBurnError, ph.PhotoError) as exc:
        raise IngestError(str(exc)) from exc
    height, width = img_bgr.shape[:2]
    scale = min(1., MAX_OVERLAY_PX / max(height, width))
    if scale < 1:
        img_bgr = cv2.resize(img_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    image_to_mm = np.asarray(override["image_to_mm"], float) @ np.diag([1 / scale, 1 / scale, 1.])
    excluded = {layer["index"] for layer in (pair.get("check") or {}).get("layers", [])
                if layer.get("role") in ("pre-test cleaning witness", "registration, QR and engraved labels")}
    from . import registration
    proposals = registration.snap_translations(img_bgr, [layer for layer in project.layers if layer.regions],
                                               image_to_mm, excluded)
    preview_width, preview_height = img_bgr.shape[1], img_bgr.shape[0]
    return [{"element": item["element"], "support_count": item["support_count"],
             "shape_score": item["shape_score"],
             "shift_fraction": [item["shift_px"][0] / preview_width,
                                item["shift_px"][1] / preview_height]} for item in proposals]


def check_pair(store: Store, pair_id: int, corners=None, allow_non_raw: bool = False, corners_fraction=None,
               anchor=None, translation_fraction=None, rotation_degrees=None, scale_factor=None,
               mirror_horizontal=None, mirror_vertical=None, reset_alignment: bool = False) -> dict:
    """Run every check and measure the layers. Never writes observations. Returns the check report."""
    row = _pair_row(store, pair_id)
    _guard_mutable(row)
    pair = get_pair(store, pair_id)
    if reset_alignment:
        if any(value is not None for value in (corners, corners_fraction, anchor, translation_fraction,
                                               rotation_degrees, scale_factor, mirror_horizontal, mirror_vertical)):
            raise IngestError("automatic reset cannot be combined with manual alignment changes")
        pair.update(alignment_override=None, corners=None, anchor=None, prefer_corners=False)
    if any(value is not None for value in (translation_fraction, rotation_degrees, scale_factor,
                                           mirror_horizontal, mirror_vertical)):
        if corners is not None or corners_fraction is not None or anchor is not None:
            raise IngestError("adjust the entire overlay or set alignment corners, not both")
        pair["alignment_override"] = _overlay_override(
            pair, translation_fraction=translation_fraction, rotation_degrees=rotation_degrees,
            scale_factor=scale_factor, mirror_horizontal=mirror_horizontal, mirror_vertical=mirror_vertical)
    elif corners_fraction is not None or anchor is not None or corners is not None:
        pair["alignment_override"] = None
    setup = su.resolve(store, row["device_id"], row["lens_id"])
    problems: list[str] = []
    report: dict = {"chart": {"detected": False, "reason": "", "residual": None},
                    "alignment": {"method": None, "valid": False, "error": None},
                    "layers": [], "discrepancies": [], "project": {}, "problems": problems,
                    "warnings": [], "plate": None, "color_measurement": None}
    explicit_corners = corners is not None or corners_fraction is not None
    corners = corners if corners is not None else pair.get("corners")
    if anchor is not None:
        pair["anchor"] = anchor
        pair["prefer_corners"] = False
        corners = None
    elif explicit_corners:
        pair["anchor"] = None
        pair["prefer_corners"] = True
    pair.update(corners=corners, masks_reviewed=False)  # a new check always needs the masks reviewed again
    ids = {"plate_id": None, "plan_id": None}

    def finish(ok: bool) -> dict:
        pair["check"] = report
        _save(store, pair_id, pair, ST_READY if ok else ST_CORRECTION, **ids)
        express_against_clean(store, report)       # derived, after the save: the stored check stays the evidence
        return report

    try:
        project = lb.parse_file(row["lightburn_path"])
    except lb.LightBurnError as exc:
        problems.append(f"LightBurn file: {exc}")
        return finish(False)
    report["project"] = {"app_version": project.app_version, "device": project.device_name,
                         "identifier": project.identifier, "mirror_x": project.mirror_x,
                         "mirror_y": project.mirror_y}
    supplied = pair.get("supplied_settings") or {}
    report["layers"] = [layer_report(layer, setup["device"]["passport"], supplied.get(str(layer.index))) for layer in project.layers]
    matrix_record = pair.get("matrix")
    overflow_indices = [layer.index for layer in project.layers if layer.index >= pl.MAX_LAYERS] if not matrix_record else []
    if matrix_record:
        from . import matrix
        spec = matrix_record["spec"]
        if spec.get("missing"):
            problems.append("the matrix settings are incomplete: " + "; ".join(spec["missing"]))
        try:
            require_matrix_steps(setup["device"]["passport"], matrix_record)
        except su.ValidationError as exc:
            problems.append(str(exc))                  # a pulse width the laser does not offer, with its steps (REQ-017)
        for item in report["layers"]:
            col, row_ = item["index"] % matrix_record["cols"], item["index"] // matrix_record["cols"]
            item["matrix_cell"] = {"col": col, "row": row_, **{k: v for k, v in matrix.cell_settings(spec, col, row_).items()}}
            item["notes"] = [n for n in item["notes"] if "outside LightBurn's 30 standard output colors" not in n]
    if overflow_indices:
        low, high = min(overflow_indices), max(overflow_indices)
        report["warnings"].append(
            f"LightBurn layer indexes {low}–{high} are outside the standard output color range 00–29. "
            "Their photo regions are still measured; the file alone cannot confirm whether those operations were emitted."
        )
        for item in report["layers"]:
            if item["index"] in overflow_indices:
                item["notes"].append("This layer index is outside LightBurn's 30 standard output colors; its photo measurement is retained.")
    plate, plan = _load_identified(store, project.identifier)
    if project.identifier and plate is None and plan is None:
        problems.append(f"experiment identifier {project.identifier} is not known to this system")
    elif "Deleted" in ((plan or {}).get("status"), (plate or {}).get("status")):
        problems.append(f"experiment identifier {project.identifier} belongs to a deleted experiment")
    if plate is None and plan is None and row["plan_id"]:
        # a file without an identifier: the plan (and its plate) the photograph is linked to
        plan = pl.get_plan(store, row["plan_id"])
        plate = _plate_row(store, plan["plate_id"]) if plan.get("plate_id") else None
    if plan is not None and plan["mode"] == pl.MODE_RESTORED:
        plan = None          # a plan restored from this very file describes it; it is not a system plan to align with
    linked = plan is not None and pair.get("linked_plan_id") == plan["id"]
    # The operator's lens choice is kept apart from the lens of the measurements, so every re-check shows it again.
    pair["lens_choice"] = pair.get("lens_choice") or {"lens_id": row["lens_id"]}
    lens_id = pair["lens_choice"]["lens_id"]
    made_for = None
    if plate is not None:
        ids["plate_id"], ids["plan_id"] = plate["id"], (plan or {}).get("id")
        report["plate"] = {"experiment_id": plate["experiment_id"], "device_id": plate["device_id"], "lens_id": plate["lens_id"]}
        if plate["device_id"] != row["device_id"]:
            problems.append("this plate was made for a different laser than the one selected")
        made_for, kind = plate, "plate"
    elif plan is not None:
        # an engraving plan exported by this system: its laser and lens are compared like a plate's (REQ-013)
        ids["plan_id"] = plan["id"]
        report["plan"] = {"identifier": plan["plan_identifier"], "mode": plan["mode"], "device_id": plan["device_id"],
                          "lens_id": plan["lens_id"]}
        if plan["device_id"] != row["device_id"]:
            problems.append("this plan was made for a different laser than the one selected")
        made_for, kind = _made_for(plan), "plan"
    if made_for is not None:
        report["lens"] = lens_check(store, made_for, lens_id, kind)
        lens_id = report["lens"]["lens_id"]
    if lens_id != row["lens_id"]:
        _set_lens(store, row, lens_id, json.loads(made_for["lens_json"]) if made_for is not None and made_for["lens_json"]
                  and lens_id == made_for["lens_id"] else None)
    # System plate exports put cleanup first and registration/labels next. They are real engraved operations,
    # so retain them as measured layers. Only the test-cell comparison excludes these two system layers.
    system_plan = plan
    if system_plan is not None:
        normalized_axes = _normalize_project_to_plan(project, system_plan)
        if normalized_axes:
            report["project"]["normalized_axes"] = normalized_axes
    marker = next((layer for layer in project.layers if layer.name in ("Markers", "Markers and labels")), None) if system_plan is not None and system_plan.get("markers") else None
    marker_idx = marker.index if marker else None
    clean_layer = next((layer for layer in project.layers if layer.name.startswith("CLEAN-CROSSHATCH-")), None) if system_plan else None
    clean_idx = clean_layer.index if clean_layer else None
    if system_plan is None and clean_idx is None:
        clean_idx = _finished_work_cleaning_layer(project)         # a finished work cleans its plate first (DEC-056)
    for rep in report["layers"]:
        if rep["index"] == marker_idx:
            rep["role"] = "registration, QR and engraved labels"
        elif rep["index"] == clean_idx:
            rep["role"] = "pre-test cleaning witness"
        else:
            rep["role"] = "test feature"
    work_layers = [layer for layer in project.layers if layer.regions]
    return _measure(store, row, pair, project, plate, plan, corners, work_layers, report, problems, finish, allow_non_raw,
                    corners_fraction, linked)


def _chart_reference(store: Store, row) -> dict:
    """The chart values the photograph is corrected toward: those of the rig it was taken on (DEC-025)."""
    return su.get_capture_setup(store, row["stand_id"])["chart_reference"] if row["stand_id"] is not None else ph.published_reference()


def _measure(store, row, pair, project, plate, plan, corners, work_layers, report, problems, finish, allow_non_raw,
             corners_fraction=None, linked=False):
    """Decode, choose chart-corrected or plate-relative color, align, compare, and sample the regions."""
    try:
        img_bgr = ph.decode_image(row["photo_path"], allow_non_raw=allow_non_raw or non_raw_allowed(store))
        linear = ph.decode_linear(row["photo_path"], allow_non_raw=allow_non_raw or non_raw_allowed(store))
    except ph.PhotoError as exc:
        problems.append(f"Photograph: {exc}")
        return finish(False)
    height, width = img_bgr.shape[:2]
    report["image_size"] = [width, height]
    anchor = None
    if pair.get("anchor"):
        request = pair["anchor"]
        fractions = request.get("corners_fraction") if isinstance(request, dict) else None
        if (not isinstance(fractions, list) or len(fractions) != 4 or
                any(not isinstance(p, (list, tuple)) or len(p) != 2 or
                    not all(isinstance(v, (int, float)) and np.isfinite(v) and 0 <= v <= 1 for v in p)
                    for p in fractions)):
            problems.append("Alignment: the selected element needs four corners inside the photograph")
            return finish(False)
        try:
            anchor = {"layer_index": int(request["layer_index"]), "region_index": int(request["region_index"]),
                      "corners_px": [(x * width, y * height) for x, y in fractions]}
        except (KeyError, TypeError, ValueError):
            problems.append("Alignment: the selected LightBurn element is invalid")
            return finish(False)
    if corners_fraction:
        if len(corners_fraction) != 4 or any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in corners_fraction):
            problems.append("Alignment: the four corners must lie inside the photograph")
            return finish(False)
        corners = [(x * width, y * height) for x, y in corners_fraction]
        pair["corners"] = corners
    reference = _chart_reference(store, row)
    corrected, chart, corr = ph.correct(img_bgr, linear=linear, reference=reference)
    report["chart"] = {"detected": chart.detected, "usable": corrected is not None, "reason": chart.reason,
                       "residual": None if corr is None else round(corr.residual, 3),
                       "max_residual": ph.MAX_CORRECTION_RESIDUAL,
                       "grey_ramp": None if corr is None else corr.grey_ramp,
                       "reference": {"capture_setup_id": row["stand_id"], **{k: reference[k] for k in ("source", "white_point", "observer", "published")}}}
    plate_relative = plate is not None and plan is not None and plan.get("mode") in (pl.MODE_PLATE, pl.MODE_CAPABILITY)
    finished_relative = plate is None and relative_finished_allowed(store)
    if corrected is None and (plate_relative or finished_relative):
        # The calibration plate is itself the experiment target; no separate ColorChecker is required.
        # A finished work without a chart is measured the same way when the operator allows it (DEC-053).
        # Keep these measurements useful for same-camera comparisons while making their limitations explicit.
        corrected = ph.decoded_srgb(img_bgr, linear)
        report["color_measurement"] = {"mode": "raw_camera_relative", "reference_chart_used": False,
                                       "relative": True}
        report["warnings"].append(
            ("Calibration plate" if plate_relative else "Finished work") +
            " measured from decoded RAW without reference-chart correction; Lab values are camera-relative, not standard-calibrated. These values are stored for experiment analysis but excluded from standard-color predictions."
        )
    elif corrected is not None:
        report["color_measurement"] = {"mode": "reference_chart_corrected", "reference_chart_used": True,
                                       "relative": False}
    if corrected is None:
        if chart.detected:
            problems.append("A reference-chart candidate was detected, but color correction failed: no observations will be created. " + chart.reason)
        else:
            problems.append("Reference chart not detected: no observations will be created. " + chart.reason)
        return finish(False)
    try:
        override = pair.get("alignment_override")
        if override:
            h = np.asarray(override["image_to_mm"], dtype=float)
            if h.shape != (3, 3) or not np.isfinite(h).all() or abs(np.linalg.det(h)) < 1e-12:
                raise ph.PhotoError("the saved overlay adjustment is invalid")
            dx, dy = override.get("file_offset_mm", [0., 0.])
            transformed = (override.get("scale_factor", 1.) != 1. or override.get("mirror_horizontal")
                           or override.get("mirror_vertical"))
            method = ("manual transform" if transformed else
                      "manual rotation" if override.get("rotation_degrees", 0.) % 360 else "manual shift")
            report["alignment"].update(method=method, file_offset_mm=[dx, dy],
                                       reflected=override.get("reflected", False))
            report["warnings"].append("The whole LightBurn drawing was adjusted by hand; inspect every contour before accepting measurements.")
        else:
            h, dx, dy = _align(store, row, img_bgr, plate, plan, corners, anchor, work_layers, report,
                               prefer_corners=bool(pair.get("prefer_corners")), linked=linked)
        if anchor:
            # A quadrilateral on the entire plate must never be accepted as a
            # 3 mm LightBurn detail. One anchor defines the transform, but the
            # resulting *whole work* still has to fit in this photograph.
            area = _bbox([region for layer in work_layers for region in layer.regions])
            x, y, w, hh = area
            work_corners = np.float32([[(x, y), (x + w, y), (x + w, y + hh), (x, y + hh)]])
            projected = cv2.perspectiveTransform(work_corners, np.linalg.inv(np.asarray(h, float)))[0]
            span = np.ptp(projected, axis=0) if np.isfinite(projected).all() else (np.inf, np.inf)
            if (not np.isfinite(projected).all() or span[0] > width * 1.5 or span[1] > height * 1.5 or
                    np.max(np.abs(projected[:, 0])) > width * 2 or np.max(np.abs(projected[:, 1])) > height * 2):
                raise ph.PhotoError("the selected detail is too small for the four placed corners; mark the four corners of the whole work instead")
            report["warnings"].append("Alignment starts from one manually placed detail; review the other layer outlines before accepting measurements.")
    except ph.PhotoError as exc:
        report["alignment"].update(valid=False, error=str(exc))
        problems.append(f"Alignment: {exc}")
        from . import registration
        report["alignment"]["suggestions"] = registration.suggest_element_anchors(img_bgr, work_layers)
        return finish(False)
    report["alignment"]["valid"] = True
    report["alignment"]["image_to_mm"] = np.asarray(h, float).tolist()
    report["alignment"]["work_corners_fraction"] = _work_corners_fraction(
        [r for layer in work_layers for r in layer.regions], h, width, height)
    # Registration is global, but evidence is gathered for each closed vector.
    # A layer may contain many independent artwork elements with different
    # visibility; its cut settings are metadata, not the matching unit.
    from . import registration
    system_indices = {rep["index"] for rep in report["layers"]
                      if rep.get("role") in ("pre-test cleaning witness", "registration, QR and engraved labels")}
    if not pair.get("alignment_override") and not pair.get("prefer_corners"):
        report["alignment"]["layer_offsets_px"] = registration.snap_layer_translations(
            img_bgr, work_layers, h, system_indices)
        if plan and plan.get("markers"):
            report["alignment"]["marker_feature_adjustments"] = registration.snap_marker_features(
                img_bgr, plan["markers"], plan.get("marker_labels", []), h, dx, dy)
            report["alignment"]["visible_right_surface_edge"] = registration.visible_right_surface_edge(
                img_bgr, plan["markers"], h, dx, dy)
    layer_offsets = report["alignment"].get("layer_offsets_px") or {}
    vectors = registration.match_closed_vectors(img_bgr, work_layers, h, system_indices,
                                                layer_offsets)
    report["alignment"]["vector_matches"] = vectors
    report["alignment"]["vector_found"] = sum(v["status"] == "found" for v in vectors)
    report["alignment"]["vector_total"] = len(vectors)
    report["alignment"]["snap_candidates"] = registration.snap_translations(img_bgr, work_layers, h, system_indices)
    previous_found = ((pair.get("check") or {}).get("alignment") or {}).get("vector_found", 0)
    if (pair.get("alignment_override") or pair.get("prefer_corners")) and previous_found >= 2 and (
            report["alignment"]["vector_found"] == 0 or
            previous_found >= 4 and report["alignment"]["vector_found"] < previous_found / 2):
        report["alignment"]["valid"] = False
        problems.append("Alignment: the adjustment lost too many previously recognized vectors; move the overlay back or correct the four work corners")
        return finish(False)
    if plate is not None:
        test_layers = [layer for layer in work_layers if layer.index not in system_indices]
        discrepancies, _, missing = compare_plate(plate["cells"], test_layers, dx, dy)
        report["discrepancies"] = discrepancies
        if missing:
            problems.append(f"plate cells not found in the LightBurn file: {', '.join(missing)}")
            return finish(False)
        if discrepancies and not pair.get("file_confirmation"):
            problems.append("The LightBurn file differs from the plate definition: correct the pair or confirm that this file was used")
    shape = corrected.shape[:2]
    visible_surface = _visible_surface_mask(shape, report["alignment"])
    by_index = {layer.index: layer for layer in project.layers}
    qr_local = _qr_local_geometry(plan, report["alignment"])
    for rep in report["layers"]:
        layer = by_index[rep["index"]]
        if not rep["readable"] or not layer.regions:
            continue
        planned_layer = next((item for item in (plan or {}).get("layers", []) if item.get("name") == rep["name"]), None)
        layer_h = _layer_image_to_mm(h, report["alignment"], layer.index)
        if rep.get("role") == "pre-test cleaning witness":
            later = [item for item in project.layers if item.index != layer.index and item.regions]
            mask = _clean_witness_mask(layer, later, h, shape, qr_local, report["alignment"])
            rep["measurement"] = "cleaned area after removing pixels covered by later engraved geometry"
        elif rep.get("role") == "registration, QR and engraved labels":
            mask = _marker_polygons_mask([region.polygon for region in layer.regions],
                                         h, shape, report["alignment"], qr_local)
        else:
            mask = ph.layer_mask([region.polygon for region in layer.regions], layer_h, shape,
                                 holes_mm=[region.holes for region in layer.regions])
        if visible_surface is not None:
            mask &= visible_surface
        covered = None
        if rep.get("role") == "test feature":
            covered = _covered_by_later_layers(layer, project.layers, np.asarray(h, float), report["alignment"], shape,
                                               system_indices)
            if covered is not None:
                before = int(mask.sum())
                mask &= ~covered
                if before:
                    rep["covered_by_later_layers_percent"] = round(100.0 * (before - int(mask.sum())) / before, 1)
                    if rep["covered_by_later_layers_percent"] >= 1:
                        rep["notes"].append(f"{rep['covered_by_later_layers_percent']:g}% of the sampled area is engraved again by a "
                                            "later layer and is not sampled")
        _note_frame(rep, report["alignment"])
        if rep.get("role") == "pre-test cleaning witness" and int(mask.sum()) < ph.MIN_MASK_PIXELS:
            # the first layer is engraved over entirely: nothing of it shows, and there is no clean reference here
            rep["measured_lab"], rep["pixels"] = None, int(mask.sum())
            rep["notes"].append("the cleaning layer is engraved over entirely: no clean titanium is visible in this photograph")
            continue
        try:
            rep["measured_lab"], rep["pixels"] = ph.sample_lab(corrected, mask)
        except ph.PhotoError as exc:
            fallback = _small_path_mask(layer, layer_h, shape)
            if visible_surface is not None:
                fallback &= visible_surface
            if covered is not None:
                fallback &= ~covered
            try:
                rep["measured_lab"], rep["pixels"] = ph.sample_lab(corrected, fallback)
                rep["measurement"] = "narrow vector stroke or glyph; no edge exclusion possible"
            except ph.PhotoError:
                rep["compatible"] = False
                rep["notes"].append(str(exc))
                line_metrics = _line_metrics(corrected, layer_h, layer, planned_layer)
                if line_metrics:
                    rep["line_metrics"] = line_metrics
                continue
        if rep.get("role") == "pre-test cleaning witness" and not _looks_like_clean_titanium(rep["measured_lab"]):
            # a first-run enclosing rectangle burned dark is a background fill, not a cleaning pass: a colour, no reference
            lab_ = rep["measured_lab"]
            rep["notes"].append(f"the first layer is not clean titanium (L* {lab_[0]:.0f}, chroma {float(np.hypot(lab_[1], lab_[2])):.0f}): "
                                "a background fill, measured as a colour; this photograph has no clean reference")
            rep["role"] = "test feature"
        if layer.layer_type == "Image" and rep.get("role") == "test feature":
            allowed = visible_surface
            if covered is not None:
                allowed = ~covered if allowed is None else allowed & ~covered
            tonal = _tonal_profile(corrected, layer_h, layer, shape, allowed)
            if tonal is not None:
                rep["tonal"] = tonal
        if rep.get("role") == "registration, QR and engraved labels" and plan and plan.get("markers"):
            aruco = [{"name": f"ArUco {marker['id']}", "rects": marker["rects"]} for marker in plan["markers"].get("aruco", [])]
            subfeatures = [_sample_marker_subfeature(corrected, h, item["rects"], item["name"],
                                                     dx, dy, report["alignment"], qr_local,
                                                     visible_surface) for item in aruco]
            qr = plan["markers"].get("qr", {}).get("rects", [])
            if qr:
                subfeatures.append(_sample_marker_subfeature(corrected, h, qr, "QR registration code",
                                                               dx, dy, report["alignment"], qr_local,
                                                               visible_surface))
            labels = plan.get("marker_labels", [])
            if labels:
                subfeatures.append(_sample_marker_subfeature(corrected, h, labels, "engraved labels and values",
                                                               dx, dy, report["alignment"], qr_local,
                                                               visible_surface))
            rep["submeasurements"] = [item for item in subfeatures if item is not None]
        elif planned_layer and planned_layer.get("measurement_groups"):
            subfeatures = []
            for group in planned_layer["measurement_groups"]:
                start = group["region_start"]
                regions = planned_layer["regions"][start:start + group["region_count"]]
                if regions and all(region.get("kind") == "rect" for region in regions):
                    subfeatures.append(_sample_subfeature(corrected, layer_h, regions, group["name"], dx, dy))
            rep["submeasurements"] = [item for item in subfeatures if item is not None]
        line_metrics = _line_metrics(corrected, layer_h, layer, planned_layer)
        if line_metrics:
            rep["line_metrics"] = line_metrics
    if not any(rep["measured_lab"] for rep in report["layers"]):
        problems.append("No readable, comparable layer could be measured")
    return finish(not problems)


# -- operator decisions --------------------------------------------------------------------------------
def confirm_file(store: Store, pair_id: int, text: str) -> dict:
    """Operator confirms the attached LightBurn file was used for the physical engraving (DEC-017)."""
    row = _pair_row(store, pair_id)
    _guard_mutable(row)
    pair = get_pair(store, pair_id)
    discrepancies = (pair.get("check") or {}).get("discrepancies")
    if not discrepancies:
        raise IngestError("there is no discrepancy to confirm")
    if not (text or "").strip():
        raise IngestError("state in your own words that this file was used for the engraving")
    pair["file_confirmation"] = {"at": now(), "file_name": row["lightburn_name"], "text": text.strip(), "discrepancies": discrepancies}
    check = pair["check"]
    check["problems"] = [p for p in check["problems"] if not p.startswith("The LightBurn file differs")]
    ok = not check["problems"] and any(rep["measured_lab"] for rep in check["layers"])
    _save(store, pair_id, pair, ST_READY if ok else ST_CORRECTION)
    store.audit("file_confirmed", pair_id=pair_id, file=row["lightburn_name"], discrepancies=len(discrepancies))
    return pair["file_confirmation"]


def supply_setting(store: Store, pair_id: int, layer_index: int, setting: str, value) -> dict:
    """The operator gives a required setting that a LightBurn layer does not hold (REQ-015, REQ-016): it is checked
    against the laser, kept with the pair as supplied by the operator with the time, and the pair is checked again.
    ``value`` None takes a supplied value back before acceptance. Nothing is filled in automatically, and a value the
    file holds is never replaced. Returns the new check report."""
    row = _pair_row(store, pair_id)
    _guard_mutable(row)
    pair = _stored(store, pair_id)
    if pair.get("matrix"):
        raise IngestError("the settings of a parameter matrix are corrected in the matrix itself")
    if setting not in REQUIRED_SETTINGS:
        raise IngestError("only power, frequency, speed, pulse width, line interval and passes can be supplied")
    try:
        project = lb.parse_file(row["lightburn_path"])
    except lb.LightBurnError as exc:
        raise IngestError(f"LightBurn file: {exc}") from exc
    layer = next((item for item in project.layers if item.index == layer_index), None)
    if layer is None:
        raise IngestError(f"the LightBurn file has no layer {layer_index}")
    if setting not in missing_settings(layer):
        raise IngestError("the LightBurn layer holds this setting: a value read from the file is never replaced")
    supplied = dict(pair.get("supplied_settings") or {})
    given = dict(supplied.get(str(layer_index)) or {})
    if value is None:
        given.pop(setting, None)
    else:
        passport = su.resolve(store, row["device_id"], row["lens_id"])["device"]["passport"]
        given[setting] = {"value": supplied_value(passport, setting, value), "by": SUPPLIED_BY, "at": now()}
    if given:
        supplied[str(layer_index)] = given
    else:
        supplied.pop(str(layer_index), None)
    pair["supplied_settings"] = supplied or None
    _save(store, pair_id, pair)
    store.audit("setting_supplied", pair_id=pair_id, layer_index=layer_index, setting=setting,
                value=(given.get(setting) or {}).get("value"))
    restore_plan(store, pair_id)                     # a plan restored from the file records the job with these settings
    return check_pair(store, pair_id)


def review_masks(store: Store, pair_id: int) -> None:
    row = _pair_row(store, pair_id)
    _guard_mutable(row)
    pair = get_pair(store, pair_id)
    if not ((pair.get("check") or {}).get("alignment") or {}).get("valid"):
        raise IngestError("align the photograph before reviewing the masks")
    pair["masks_reviewed"] = True
    _save(store, pair_id, pair)


def set_task(store: Store, pair_id: int, layer_index: int | None, kind: str | None) -> None:
    """The operator's engraving task (REQ-020): of the whole work when ``layer_index`` is None, else of one layer of the file.
    None clears the choice; for a layer, ``"layer"`` asks for the task its LightBurn mode implies whatever the work's task.
    It changes no measurement, so the check stays as it is."""
    row = _pair_row(store, pair_id)
    _guard_mutable(row)
    pair = _stored(store, pair_id)
    if layer_index is None:
        pair["work_task"] = tasks.optional(kind)
    else:
        if kind not in (None, "", tasks.LAYER_DEFAULT):
            tasks.require(kind)
        known = [rep.get("index") for rep in (pair.get("check") or {}).get("layers") or []]
        if known and layer_index not in known:
            raise IngestError("this layer is not in the LightBurn file of the pair")
        chosen = dict(pair.get("layer_tasks") or {})
        if kind in (None, ""):
            chosen.pop(str(layer_index), None)
        else:
            chosen[str(layer_index)] = kind
        pair["layer_tasks"] = chosen
    _save(store, pair_id, pair)
    store.audit("pair_task_set", pair_id=pair_id, layer_index=layer_index, task=kind)



# -- acceptance ----------------------------------------------------------------------------------------
def settings_provenance(rep: dict) -> dict:
    """Where each required setting of a layer report comes from: "file", "operator" (supplied explicitly, REQ-016),
    "reconstruction" (a cell of a photographed parameter matrix: its generated file holds what the operator confirmed) or
    None (unknown)."""
    if rep.get("matrix_cell") is not None:
        return {k: RECONSTRUCTED if rep.get(field) is not None else None for k, (_, field) in REQUIRED_SETTINGS.items()}
    supplied, defaulted = rep.get("supplied_settings") or {}, rep.get("defaulted_settings") or {}
    return {k: "file" if rep.get(field) is not None else SUPPLIED_BY if k in supplied else DEFAULTED if k in defaulted else None
            for k, (_, field) in REQUIRED_SETTINGS.items()}


def observation_parameters(passport: dict, rep: dict) -> tuple[dict, str | None]:
    """The settings an observation of a layer report stores, and why they are not a parameter vector of this laser (None
    when they are): the six settings and the LightBurn execution controls of the layer. A setting the file lacks takes
    the value the operator supplied for it, if any (REQ-015)."""
    v = {k: effective_setting(rep, k) for k in REQUIRED_SETTINGS}
    param_error = None
    try:
        if None in (v["power"], v["frequency"], v["speed"]):         # an unreadable layer of a restored file
            raise su.ValidationError("power, frequency or speed is missing from this LightBurn layer")
        params = su.parameter_vector(passport, v["power"], v["frequency"], v["speed"], v["pulse_width"], v["line_interval"], v["passes"])
    except su.ValidationError as exc:
        # Keep the real measured output and the exact values found in the LightBurn file. Missing
        # settings stay null; no preset or default is substituted for what the file omitted.
        param_error = str(exc)
        params = dict(v)
    params.update({"layer_type": rep.get("type"), "global_passes": rep.get("global_passes"),
                   "bidirectional": rep.get("bidirectional"), "cross_hatch": rep.get("cross_hatch"),
                   "scan_angle": rep.get("scan_angle"), "angle_increment": rep.get("angle_increment"),
                   "source_settings": lb.recipe_settings(rep.get("source_settings"))})
    return params, param_error


def accept_pair(store: Store, pair_id: int, on_accepted: Callable[[Store, int, int | None], None] | None = None) -> list[int]:
    """Write one immutable observation per measured layer with the pair's laser and lens, atomically. Returns the
    observation ids; ``on_accepted(store, device_id, lens_id)`` runs after the commit."""
    row = _pair_row(store, pair_id)
    _guard_mutable(row)
    pair = get_pair(store, pair_id)
    check = pair.get("check")
    passport = su.resolve(store, row["device_id"], row["lens_id"])["device"]["passport"]
    plan = pl.get_plan(store, row["plan_id"]) if row["plan_id"] else None
    if not check or row["status"] != ST_READY:
        raise IngestError("run the check first; the pair is not ready to accept")
    if not check.get("color_measurement"):
        raise IngestError("the photograph has no usable color measurement basis")
    if check["problems"]:
        raise IngestError("resolve the problems found by the check: " + "; ".join(check["problems"]))
    if check["discrepancies"] and not pair["file_confirmation"]:
        raise IngestError("the LightBurn file differs from the plate definition: correct the pair or confirm the file")
    if not pair["masks_reviewed"]:
        raise IngestError("review the layer masks overlaid on the photograph before accepting")
    if pair.get("matrix") and not pair["matrix"].get("confirmed"):
        raise IngestError("confirm the settings read from the matrix before accepting")
    layers = [rep for rep in check["layers"] if rep["measured_lab"] is not None]
    if not layers:
        raise IngestError("no readable, comparable layer to accept")
    rephoto = pair["rephoto_of"] is not None
    color_mode = check["color_measurement"]["mode"]
    reason = ("reference-chart corrected, aligned, layer readable and comparable" if color_mode == "reference_chart_corrected"
              else "RAW camera-relative measurement, aligned, layer readable and comparable; retained as experiment evidence but excluded from standard-color predictions")
    if rephoto:
        reason += "; re-photograph of an already counted engraving, never an independent repetition (DEC-021)"
    ids: list[int] = []
    with store.transaction():
        for rep in layers:
            params, param_error = observation_parameters(passport, rep)
            # Reserve distinct non-test indices for the clean witness (-1) and registration/label output (0).
            # Test-feature indices remain canonical to the saved plan even though LightBurn shifts them.
            if rep.get("role") == "pre-test cleaning witness":
                observation_index = -1
            elif rep.get("role") == "registration, QR and engraved labels":
                observation_index = 0
            elif plan is not None and plan.get("mode") in (pl.MODE_PLATE, pl.MODE_CAPABILITY):
                planned_layer = next((layer for layer in plan["layers"] if layer["name"] == rep["name"]), None)
                observation_index = planned_layer["index"] if planned_layer else rep["index"]
            else:
                observation_index = rep["index"]
            evidence = {"discrepancies": check["discrepancies"], "file_confirmation": pair["file_confirmation"],
                        "pixels": rep["pixels"], "chart_residual": check["chart"]["residual"],
                        "chart_reference": check["chart"].get("reference"), "layer_name": rep["name"],
                        "lightburn_file": row["lightburn_name"], "color_measurement": check["color_measurement"],
                        "role": rep.get("role"), "submeasurements": rep.get("submeasurements", []),
                        "line_metrics": rep.get("line_metrics"), "parameter_error": param_error,
                        "matrix_cell": rep.get("matrix_cell"), "task": rep.get("task") or layer_task(pair, plan, rep),
                        # which settings the file holds and which the operator supplied, with who and when (REQ-016)
                        "settings_provenance": settings_provenance(rep), "supplied_settings": rep.get("supplied_settings") or None,
                        "defaulted_settings": rep.get("defaulted_settings") or None,
                        # a matrix cell: who confirmed the reconstructed settings and when (REQ-036, DEC-061)
                        "reconstruction": {"from": RECONSTRUCTED_FROM, "confirmed_by": SUPPLIED_BY,
                                           "confirmed_at": pair["matrix"].get("confirmed_at")} if rep.get("matrix_cell") else None}
            # Cleaning, registration markers and engraved labels are kept as evidence and shown, but they are operations of
            # the plate, not test settings: they never feed the model or knowledge (DEC-027, DEC-028, DEC-045).
            test_feature = rep.get("role", "test feature") == "test feature"
            model_eligible = color_mode == "reference_chart_corrected" and rep["compatible"] and param_error is None and test_feature
            observation_reason = reason
            if not test_feature:
                observation_reason += f"; {rep['role']} layer: kept as evidence, never used for parameter recommendations"
            if not rep["compatible"] or param_error:
                observation_reason += "; retained as physical measurement, excluded from parameter recommendations: " + "; ".join(rep["notes"] + ([param_error] if param_error else []))
            ids.append(store.execute(
                "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,"
                "context_json,model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at,task_kind)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pair_id, observation_index, row["device_id"], row["lens_id"], row["engraving_id"], json.dumps(rep["measured_lab"]), json.dumps(params),
                 check["alignment"]["method"], row["context_json"], int(model_eligible), 0 if rephoto else 1, observation_reason, json.dumps(evidence), now(),
                 evidence["task"]["kind"])).lastrowid)
        store.execute("UPDATE pair SET status=?, accepted_at=? WHERE id=?", (ST_ACCEPTED, now(), pair_id))
        store.audit("pair_accepted", pair_id=pair_id, observations=len(ids))
    superseded = pair.get("correction_of")
    if superseded is not None:
        older = store.one("SELECT status FROM pair WHERE id=?", (superseded,))
        if older is not None and older["status"] == ST_ACCEPTED:
            delete_pair(store, superseded)
    if on_accepted is not None:
        on_accepted(store, row["device_id"], row["lens_id"])
    from . import capability_results, designer
    capability_results.save_findings(store, pair_id)
    designer.record_target_checks(store, pair_id)          # a cell made for a target colour is checked against it (REQ-006)
    return ids


def delete_pair(store: Store, pair_id: int) -> None:
    """Remove a pair from active use (DEC-047) and rebuild the knowledge its observations fed."""
    from . import knowledge, model
    row = store.one("SELECT * FROM pair WHERE id=?", (pair_id,))
    if row is None or row["status"] == ST_DELETED:
        raise KeyError(f"pair {pair_id} not found")
    observations = store.query("SELECT * FROM observation WHERE pair_id=?", (pair_id,))
    # Pair and measurement rows remain in the immutable audit history. Marking the pair Deleted
    # removes it from active lists, color learning, and reports; uploaded file copies are purged.
    with store.transaction():
        store.execute("UPDATE pair SET status=? WHERE id=?", (ST_DELETED, pair_id))
        store.audit("pair_deleted", pair_id=pair_id, previous_status=row["status"], observations=len(observations))
        # a plan restored from the file of this work is its record: archived with the last of its photographs
        store.execute("UPDATE plan SET status='Deleted' WHERE id=? AND mode=? AND NOT EXISTS "
                      "(SELECT 1 FROM pair WHERE plan_id=plan.id AND status!=?)", (row["plan_id"], pl.MODE_RESTORED, ST_DELETED))
    for col in ("lightburn_path", "photo_path"):
        Path(row[col]).unlink(missing_ok=True)
    rc.remove_pair(store, pair_id)                  # the pictures drawn from the purged photograph go with it
    removed: dict[tuple, dict[str, list[int]]] = {}
    for o in observations:
        key = model.knowledge_key_of(o)
        if key is not None:
            removed.setdefault((o["device_id"], o["lens_id"]), {}).setdefault(key, []).append(o["id"])
    for (device_id, lens_id), keys in removed.items():
        knowledge.after_removal(store, device_id, lens_id, keys)


# -- overlay for the mask review -----------------------------------------------------------------------
MAX_OVERLAY_PX = 1400
FULL_PREVIEW_PX = 5000      # the longest side of a full-detail picture (zooming), and the largest size a picture can be asked for
MIN_PREVIEW_PX = 64


def _view_limit(visibility: str, full: bool, size: int | None) -> int:
    """The longest side of a picture in pixels (never enlarged beyond the photograph): ``size`` when asked for, else the
    full-detail or the preview size. Refuses a view the pictures do not have."""
    if visibility not in ("normal", "lifted"):
        raise IngestError("unknown photo preview visibility mode")
    if size is None:
        return FULL_PREVIEW_PX if full else MAX_OVERLAY_PX
    if not MIN_PREVIEW_PX <= size <= FULL_PREVIEW_PX:
        raise IngestError(f"the picture size must be from {MIN_PREVIEW_PX} to {FULL_PREVIEW_PX} pixels")
    return size


def overlay_picture(store: Store, pair_id: int, corrected: bool = True, layer_index: int | None = None,
                    visibility: str = "normal", transparent: bool = False, full: bool = False,
                    size: int | None = None) -> rc.Picture:
    """The overlay of ``overlay_png`` known by its cache key before it is drawn (BUG-001).

    The key covers every input of the drawing: the photograph and LightBurn files (path, size, modification time), the stored
    check (alignment, layer reports, frame window), the plan the file is normalised to, the chart reference a corrected
    picture is corrected toward, the RAW-only switch and every view parameter. Refusals come before any drawing."""
    limit = _view_limit(visibility, full, size)
    row = _pair_row(store, pair_id)
    check = json.loads(row["data_json"] or "{}").get("check") or {}
    if not (check.get("alignment") or {}).get("image_to_mm"):
        raise IngestError("the photograph is not aligned yet: run the check first")
    if layer_index is not None and layer_index not in {rep["index"] for rep in check.get("layers", [])}:
        raise IngestError("the requested LightBurn layer is not part of this pair")
    plan_row = store.one("SELECT data_json FROM plan WHERE id=?", (row["plan_id"],)) if row["plan_id"] else None
    allow_non_raw = non_raw_allowed(store)
    reference = _chart_reference(store, row) if corrected and not transparent else None
    key = rc.key_of({"picture": "overlay", "pair_id": pair_id, "photo": rc.file_stamp(row["photo_path"]),
                     "lightburn": rc.file_stamp(row["lightburn_path"]), "check": check, "plan_id": row["plan_id"],
                     "plan": rc.text_digest(plan_row["data_json"]) if plan_row else None, "allow_non_raw": allow_non_raw,
                     "chart_reference": reference, "corrected": corrected, "layer_index": layer_index, "visibility": visibility,
                     "transparent": transparent, "full": full, "size": size})

    def draw() -> bytes:
        plan = pl.get_plan(store, row["plan_id"]) if row["plan_id"] else None
        return _draw_overlay(row["photo_path"], row["lightburn_path"], check, plan, allow_non_raw, corrected, reference,
                             layer_index, visibility, transparent, limit)
    return rc.Picture(store, pair_id, key, draw)


def overlay_png(store: Store, pair_id: int, corrected: bool = True, layer_index: int | None = None,
                visibility: str = "normal", transparent: bool = False, full: bool = False, size: int | None = None) -> bytes:
    """Photo preview with the measured layer masks outlined for operator review (REQ-015).

    The overlay is recomputed from the stored alignment, so it shows exactly what ``check_pair`` measured.
    ``layer_index`` isolates one LightBurn layer; None shows all measured layers. ``visibility='lifted'``
    brightens only the returned preview for viewing a dark RAW exposure; it never changes measured Lab values.
    ``size`` asks for that longest side in pixels instead of the preview or full-detail size. A drawn overlay is kept in
    the render cache until one of its inputs changes.
    """
    return overlay_picture(store, pair_id, corrected, layer_index, visibility, transparent, full, size).png()


def _draw_overlay(photo_path: str, lightburn_path: str, check: dict, plan: dict | None, allow_non_raw: bool, corrected: bool,
                  reference: dict | None, layer_index: int | None, visibility: str, transparent: bool, limit: int) -> bytes:
    """Draw the overlay of ``overlay_png`` from exactly the inputs its cache key names."""
    import cv2

    h = check["alignment"]["image_to_mm"]
    img_bgr = ph.decode_image(photo_path, allow_non_raw=allow_non_raw)
    if corrected and not transparent:
        rgb, _, _ = ph.correct(img_bgr, linear=ph.decode_linear(photo_path, allow_non_raw=allow_non_raw), reference=reference)
        if rgb is not None:
            img_bgr = cv2.cvtColor((np.clip(rgb, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    if visibility == "lifted" and not transparent:
        # A display-only gamma lift makes underexposed RAW captures inspectable.
        # It is applied solely in this PNG endpoint after all measurement data was saved.
        gamma = 0.58
        lut = np.round(np.power(np.arange(256, dtype=np.float32) / 255.0, gamma) * 255).astype(np.uint8)
        img_bgr = cv2.LUT(img_bgr, lut)
    if transparent:
        img_bgr = np.zeros((*img_bgr.shape[:2], 4), dtype=np.uint8)
    background = img_bgr.copy()
    project = lb.parse_file(lightburn_path)
    by_index = {layer.index: layer for layer in project.layers}
    reports = check.get("layers", [])
    _normalize_project_to_plan(project, plan)
    qr_local = _qr_local_geometry(plan, check.get("alignment") or {})
    palette = [(60, 60, 255), (60, 200, 60), (255, 120, 40), (30, 220, 220), (220, 60, 200), (200, 200, 60)]
    thickness = max(3, img_bgr.shape[1] // 650)
    window = None
    window_px = (check.get("alignment") or {}).get("window_px")
    if window_px:
        window = np.zeros(img_bgr.shape[:2], bool)
        window[cv2.fillConvexPoly(np.zeros(img_bgr.shape[:2], np.uint8),
                                  np.round(np.asarray(window_px, float)).astype(np.int32), 1) > 0] = True
    hidden_color = (255, 60, 255, 255) if transparent else (255, 60, 255)
    for n, rep in enumerate(reports):
        if layer_index is not None and rep["index"] != layer_index:
            continue
        layer = by_index.get(rep["index"])
        if layer is None or not layer.regions:
            continue
        layer_h = _layer_image_to_mm(np.asarray(h, float), check.get("alignment") or {}, layer.index)
        layer_to_image = np.linalg.inv(layer_h)
        color = palette[n % len(palette)] if rep.get("measured_lab") is not None else (160, 160, 160)
        if transparent:
            color = (*color, 255)
        # Display the exact LightBurn vectors. Measurement masks deliberately
        # erode filled areas and subtract later cuts; outlining those masks
        # made the cleaning rectangle and every closed shape look too small.
        for region in layer.regions:
            if len(region.polygon) < 2:
                continue
            matrix = (np.linalg.inv(_marker_region_image_to_mm(np.asarray(h, float),
                      check.get("alignment") or {}, region.polygon, qr_local))
                      if rep.get("role") == "registration, QR and engraved labels" else layer_to_image)
            points = cv2.perspectiveTransform(np.asarray(region.polygon, np.float32)[None], matrix)[0]
            if not np.isfinite(points).all():
                continue
            pixels = np.rint(points).astype(np.int32)
            closed = region.closed or region.kind in ("rect", "bitmap")
            width = thickness + (1 if rep.get("role") == "pre-test cleaning witness" else 0)
            if window is None:
                cv2.polylines(img_bgr, [pixels], closed, color, width, cv2.LINE_AA)
                continue
            # the part of an outline under the frame is inferred, not seen: draw it in its own colour
            loop = np.vstack([pixels, pixels[:1]]) if closed else pixels
            ix = np.clip(loop, [0, 0], [window.shape[1] - 1, window.shape[0] - 1])
            seen = window[ix[:, 1], ix[:, 0]]
            start = 0
            for i in range(1, len(loop) + 1):
                if i == len(loop) or seen[i] != seen[start]:
                    run = loop[max(start - 1, 0):i]
                    if len(run) > 1:
                        cv2.polylines(img_bgr, [run], False, color if seen[start] else hidden_color,
                                      width if seen[start] else width + 1, cv2.LINE_AA)
                    start = i
    if (check.get("alignment") or {}).get("method") == "picture":
        silhouettes = _picture_silhouettes(project, np.asarray(h, float), img_bgr.shape[:2])
        if silhouettes is not None:        # where the silhouettes of the stored picture were found on the photograph
            img_bgr[silhouettes] = (0, 255, 0, 255) if transparent else (0, 255, 0)
    if window_px:       # the visible window of a frame: what is measured; the rest of the outlines is inferred
        cv2.polylines(img_bgr, [np.round(np.asarray(window_px, float)).astype(np.int32)], True,
                      (255, 255, 0, 255) if transparent else (255, 255, 0), max(2, thickness // 2), cv2.LINE_AA)
    visible_surface = _visible_surface_mask(img_bgr.shape[:2], check.get("alignment") or {}, include_window=False)
    if visible_surface is not None:
        img_bgr[~visible_surface] = background[~visible_surface]
    scale = min(1.0, limit / max(img_bgr.shape[:2]))
    if scale < 1.0:
        img_bgr = cv2.resize(img_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img_bgr)
    if not ok:
        raise IngestError("could not render the overlay")
    return buf.tobytes()


def photo_preview_picture(store: Store, pair_id: int, corrected: bool = False, visibility: str = "normal",
                          full: bool = False, size: int | None = None) -> rc.Picture:
    """The photograph of ``photo_preview_png`` known by its cache key before it is drawn (BUG-001): the key covers the
    photograph file (path, size, modification time), the chart reference a corrected picture is corrected toward, the
    RAW-only switch and every view parameter."""
    limit = _view_limit(visibility, full, size)
    row = _pair_row(store, pair_id)
    allow_non_raw = non_raw_allowed(store)
    reference = _chart_reference(store, row) if corrected else None
    key = rc.key_of({"picture": "photo", "pair_id": pair_id, "photo": rc.file_stamp(row["photo_path"]), "allow_non_raw": allow_non_raw,
                     "chart_reference": reference, "corrected": corrected, "visibility": visibility, "full": full, "size": size})
    return rc.Picture(store, pair_id, key,
                      lambda: _draw_photo_preview(row["photo_path"], allow_non_raw, corrected, reference, visibility, limit))


def photo_preview_png(store: Store, pair_id: int, corrected: bool = False, visibility: str = "normal",
                      full: bool = False, size: int | None = None) -> bytes:
    """Display-only decoded photograph; full detail is available when zooming, a small one (``size``, the longest side in
    pixels) for a list. A drawn photograph is kept in the render cache until one of its inputs changes."""
    return photo_preview_picture(store, pair_id, corrected, visibility, full, size).png()


def _draw_photo_preview(photo_path: str, allow_non_raw: bool, corrected: bool, reference: dict | None, visibility: str,
                        limit: int) -> bytes:
    """Draw the photograph of ``photo_preview_png`` from exactly the inputs its cache key names."""
    import cv2

    img = ph.decode_image(photo_path, allow_non_raw=allow_non_raw)
    if corrected:
        rgb, _, _ = ph.correct(img, linear=ph.decode_linear(photo_path, allow_non_raw=allow_non_raw), reference=reference)
        if rgb is not None:
            img = cv2.cvtColor((np.clip(rgb, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    if visibility == "lifted":
        lut = np.round(np.power(np.arange(256, dtype=np.float32) / 255.0, .58) * 255).astype(np.uint8)
        img = cv2.LUT(img, lut)
    scale = min(1.0, limit / max(img.shape[:2]))
    if scale < 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise IngestError("could not render the photograph")
    return buf.tobytes()

