"""Universal observation ingestion: a LightBurn file paired with a rig photograph (REQ-001, REQ-015).

A *pair* goes through ``create_pair`` -> ``check_pair`` -> (``confirm_file``) -> ``review_masks`` ->
``accept_pair``. Only ``accept_pair`` writes observations, and observations are immutable afterwards.

Rules implemented here:

* Power, frequency and speed always come from the paired LightBurn file; profile constants come from the
  linked laser profile version (REQ-010, DEC-017, DEC-022).
* A photograph in which no reference chart is detected produces no observations (REQ-009).
* A calibration plate is identified by the ``TCE1:<id>`` note in its LightBurn file; its cells are matched to
  file layers by geometry, never guessed. Marker or identifier failures stop the mapping (REQ-003).
* A difference between file parameters and the plate definition blocks acceptance until the operator
  corrects the pair (a new file) or explicitly confirms the attached file was used (DEC-017).
* One observation is stored per layer, sampled from the union of that layer's shapes with their edges
  excluded (proposed DEC-028). Layers that are unreadable or not comparable to the laser profile are
  skipped and reported (REQ-015, DEC-022). The marker layer of a system-generated file is never measured.
* A re-photograph of an engraving shares its ``engraving_id`` and never counts as an independent
  repetition (DEC-021).

Assumption (not fixed by the requirements): LightBurn project y points down like image rows, and the
photograph shows the work from the side it is viewed; mirrored jobs are not handled.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from . import lightburn as lb
from . import photo as ph
from . import plans as pl
from . import profiles as pf
from .db import Store, now

ST_PENDING, ST_CORRECTION, ST_READY, ST_ACCEPTED = "Awaiting check", "Needs correction", "Ready to accept", "Accepted"
PARAM_TOLERANCE = 1e-6
CONTEXT_KEYS = ("material_id", "batch", "focus", "engraved_at", "note")
DATA_KEYS = ("rephoto_of", "masks_reviewed", "file_confirmation", "corners", "check")


class IngestError(ValueError):
    """The pair cannot be processed or accepted; the message is meant for the operator."""


def _pair_row(store: Store, pair_id: int):
    row = store.one("SELECT * FROM pair WHERE id=?", (pair_id,))
    if row is None:
        raise KeyError(f"pair {pair_id} not found")
    return row


def get_pair(store: Store, pair_id: int) -> dict:
    d = dict(_pair_row(store, pair_id))
    d["context"] = json.loads(d.pop("context_json"))
    d.update(json.loads(d.pop("data_json")))
    return d


def _save(store: Store, pair_id: int, data: dict, status: str | None = None, plate_id=None, plan_id=None) -> None:
    sets, params = ["data_json=?"], [json.dumps({k: data.get(k) for k in DATA_KEYS})]
    for col, val in (("status", status), ("plate_id", plate_id), ("plan_id", plan_id)):
        if val is not None:
            sets.append(f"{col}=?")
            params.append(val)
    store.execute(f"UPDATE pair SET {', '.join(sets)} WHERE id=?", (*params, pair_id))


def _guard_mutable(row) -> None:
    if row["status"] == ST_ACCEPTED:
        raise IngestError("an accepted pair and its observations are immutable")


def clean_context(ctx: dict | None) -> dict:
    """Optional context: everything defaults to None ('unknown'). Only the laser profile is mandatory."""
    ctx = dict(ctx or {})
    out = {k: ctx.get(k) for k in CONTEXT_KEYS}
    if out["focus"] in ("", None):
        out["focus"] = None
    else:
        try:
            out["focus"] = float(out["focus"])
        except (TypeError, ValueError):
            raise pf.ValidationError("focus must be a number") from None
        if not np.isfinite(out["focus"]):
            raise pf.ValidationError("focus must be a finite number")
    if out["engraved_at"] in ("", None):
        out["engraved_at"] = None
    else:
        try:
            datetime.strptime(str(out["engraved_at"]), "%Y-%m-%d")
        except ValueError:
            raise pf.ValidationError("date must be YYYY-MM-DD") from None
    for k in ("batch", "note"):
        out[k] = (str(out[k]).strip() or None) if out[k] is not None else None
    return out


def previous_context(store: Store, profile_id: int) -> dict | None:
    """'Same as previous': the context of the last accepted pair of this laser profile version."""
    row = store.one("SELECT context_json FROM pair WHERE profile_id=? AND status=? ORDER BY accepted_at DESC, id DESC LIMIT 1",
                    (profile_id, ST_ACCEPTED))
    return None if row is None else json.loads(row["context_json"])


# -- creation ------------------------------------------------------------------------------------------
def non_raw_allowed(store: Store) -> bool:
    """Test/demo switch. Measurement requires RAW (DEC-003); this is off unless explicitly set and is not exposed by the API."""
    return bool(store.get_setting("allow_non_raw_photos", False))


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name) or "file"


def create_pair(store: Store, *, profile_id: int, stand_id: int, lightburn_name: str, lightburn_bytes: bytes,
                photo_name: str, photo_bytes: bytes, plan_id: int | None = None, rephoto_of: int | None = None,
                context: dict | None = None) -> int:
    pf.get_profile(store, profile_id)
    if store.one("SELECT id FROM capture_setup WHERE id=?", (stand_id,)) is None:
        raise IngestError("select a capture setup (rig) for this photograph")
    if not re.search(r"\.(lbrn2?)$", lightburn_name, re.I):
        raise IngestError("Select a .lbrn or .lbrn2 file")
    if Path(photo_name).suffix.lower() not in ph.RAW_EXTENSIONS and not non_raw_allowed(store):
        raise IngestError("A RAW photograph is required for measurement")
    if not lightburn_bytes or not photo_bytes:
        raise IngestError("both files must be non-empty")
    ctx = clean_context(context)
    engraving_id = uuid.uuid4().hex
    if rephoto_of is not None:
        orig = _pair_row(store, rephoto_of)
        if orig["status"] != ST_ACCEPTED:
            raise IngestError("only an accepted pair can be re-photographed")
        engraving_id = orig["engraving_id"]
    tag = uuid.uuid4().hex[:12]
    folder = store.data_dir / "files"
    lb_path, photo_path = folder / f"{tag}-{_safe_name(lightburn_name)}", folder / f"{tag}-{_safe_name(photo_name)}"
    lb_path.write_bytes(lightburn_bytes)
    photo_path.write_bytes(photo_bytes)
    data = {"rephoto_of": rephoto_of, "masks_reviewed": False, "file_confirmation": None, "corners": None, "check": None}
    return store.execute(
        "INSERT INTO pair(status,profile_id,stand_id,plan_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (ST_PENDING, profile_id, stand_id, plan_id, engraving_id, lightburn_name, str(lb_path), photo_name, str(photo_path),
         json.dumps(ctx), json.dumps(data), now())).lastrowid


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
    pair.update(masks_reviewed=False, file_confirmation=None, check=None)
    _save(store, pair_id, pair, ST_PENDING)


# -- plate comparison ----------------------------------------------------------------------------------
def _bbox(regions) -> tuple[float, float, float, float]:
    x0, y0 = min(r.x for r in regions), min(r.y for r in regions)
    return x0, y0, max(r.x + r.width for r in regions) - x0, max(r.y + r.height for r in regions) - y0


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def compare_plate(plate_cells: list[dict], layers: list[lb.Layer], dx: float, dy: float):
    """Match plate cells to file layers by geometry and list parameter discrepancies (DEC-017).

    Returns (discrepancies, cell_id -> layer, cell ids that no layer covers). A cell with no matching
    geometry is reported, never guessed.
    """
    discrepancies, mapping, missing = [], {}, []
    for cell in plate_cells:
        g = cell["geometry"]
        want = (g["x"] + dx, g["y"] + dy, g["width"], g["height"])
        best, best_iou = None, 0.0
        for layer in layers:
            for r in layer.regions:
                score = _iou(want, (r.x, r.y, r.width, r.height))
                if score > best_iou:
                    best, best_iou = layer, score
        if best is None or best_iou < 0.5:
            missing.append(cell["id"])
            continue
        mapping[cell["id"]] = best
        p = cell["parameters"]
        for field, defined, got in (("power", p["power"], best.power), ("frequency", p["frequency"], best.frequency_khz),
                                    ("speed", p["speed"], best.speed)):
            if got is None or abs(defined - got) > PARAM_TOLERANCE:
                discrepancies.append({"cell_id": cell["id"], "field": field, "defined": defined, "from_file": got})
    return discrepancies, mapping, missing


def layer_report(layer: lb.Layer, profile: dict) -> dict:
    """Per-layer readability and comparability to the laser profile (REQ-015, DEC-022)."""
    notes, compatible = [], True
    if not layer.readable:
        compatible = False
        notes += layer.unreadable
    else:
        problems = pf.check_in_range(profile, layer.power, layer.frequency_khz, layer.speed)
        problems += lb.compare_with_profile(layer, profile["constants"]["pulse_width"], profile["constants"]["line_interval"])
        if problems:
            compatible = False
            notes += [f"not comparable to the laser profile: {m}" for m in problems]
    if not layer.regions:
        compatible = False
        notes.append("the layer has no fill geometry")
    return {"index": layer.index, "name": layer.name, "type": layer.layer_type, "power": layer.power,
            "frequency_khz": layer.frequency_khz, "speed": layer.speed, "pulse_width": layer.pulse_width,
            "line_interval": layer.line_interval, "regions": len(layer.regions), "readable": layer.readable,
            "compatible": compatible, "notes": notes, "measured_lab": None, "pixels": None}



# -- checking ------------------------------------------------------------------------------------------
def lens_check(store: Store, plate: dict) -> dict:
    """Compare the lens a plate was made for with the lens installed now (DEC-041). A difference is a warning, never a block."""
    made = json.loads(plate["lens_json"]) if plate.get("lens_json") else None
    profile = pf.get_profile(store, plate["profile_id"])
    now_lens = (profile.get("device") or {}).get("lens")
    warnings = []
    if made and now_lens and (made["id"] != now_lens["id"] or made["focal_length_mm"] != now_lens["focal_length_mm"] or made["expansion"] != now_lens["expansion"]):
        warnings.append(f"the lens installed now ({now_lens['name']}, {now_lens['focal_length_mm']:g} mm) differs from the lens of this plate ({made['name']}, {made['focal_length_mm']:g} mm)")
    elif made and not now_lens and profile.get("device"):
        warnings.append(f"no lens is installed on the laser now; the plate was made with {made['name']} ({made['focal_length_mm']:g} mm)")
    elif now_lens and not made:
        warnings.append("this plate has no record of its lens")
    return {"plate": made, "installed": None if not now_lens else {"id": now_lens["id"], "name": now_lens["name"], "focal_length_mm": now_lens["focal_length_mm"]}, "warnings": warnings}


def _load_plate(store: Store, identifier: str | None):
    """(plate, plan) for a TCE1 identifier found in the LightBurn file, or (None, None)."""
    if not identifier:
        return None, None
    prow = store.one("SELECT * FROM plate WHERE experiment_id=?", (identifier,))
    if prow is None:
        return None, None
    plate = dict(prow)
    plate["cells"] = json.loads(plate["cells_json"])
    plan_row = store.one("SELECT id FROM plan WHERE plate_id=?", (plate["id"],))
    return plate, (pl.get_plan(store, plan_row["id"]) if plan_row else None)


def _align(store: Store, row, img_bgr, plate, plan, corners, work_layers, report) -> tuple:
    """Returns (image->mm homography, dx, dy). Raises PhotoError instead of guessing (REQ-003)."""
    if plate is not None:
        if plan is None or not plan.get("markers"):
            raise ph.PhotoError("the plate has no marker definition")
        dx, dy = pl.export_offset(plan)
        h = ph.homography_from_markers(ph.detect_markers(img_bgr), plan["markers"], dx, dy)
        ext = plan["markers"]["extent"]
        area = (ext["min_x"] + dx, ext["min_y"] + dy, ext["max_x"] - ext["min_x"], ext["max_y"] - ext["min_y"])
        seen = ph.read_identifier_rectified(img_bgr, h, area) or ph.read_identifier(img_bgr)
        if seen is None:
            raise ph.PhotoError("the experiment identifier QR code could not be read from the photograph")
        if seen != plate["experiment_id"]:
            raise ph.PhotoError(f"the photographed plate is {seen} but the LightBurn file is {plate['experiment_id']}")
        report["alignment"]["method"] = "markers"
        return h, dx, dy
    marked = pl.get_plan(store, row["plan_id"]) if row["plan_id"] else None
    if marked is not None and marked.get("markers"):
        found = ph.detect_markers(img_bgr)
        if len(found) == 4:
            dx, dy = pl.export_offset(marked)
            report["alignment"]["method"] = "markers"
            return ph.homography_from_markers(found, marked["markers"], dx, dy), dx, dy
    if corners:
        if not work_layers:
            raise ph.PhotoError("the LightBurn file has no geometry to align to")
        area = _bbox([r for layer in work_layers for r in layer.regions])
        report["alignment"]["method"] = "manual"
        return ph.homography_from_corners([tuple(c) for c in corners], area), 0.0, 0.0
    raise ph.PhotoError("no registration markers were detected: place the four image corners of the work")


def check_pair(store: Store, pair_id: int, corners=None, allow_non_raw: bool = False, corners_fraction=None) -> dict:
    """Run every check and measure the layers. Never writes observations. Returns the check report."""
    row = _pair_row(store, pair_id)
    _guard_mutable(row)
    pair = get_pair(store, pair_id)
    profile = pf.get_profile(store, row["profile_id"])
    problems: list[str] = []
    report: dict = {"chart": {"detected": False, "reason": "", "residual": None},
                    "alignment": {"method": None, "valid": False, "error": None},
                    "layers": [], "discrepancies": [], "project": {}, "problems": problems, "plate": None}
    corners = corners if corners is not None else pair.get("corners")
    pair.update(corners=corners, masks_reviewed=False)  # a new check always needs the masks reviewed again
    ids = {"plate_id": None, "plan_id": None}

    def finish(ok: bool) -> dict:
        pair["check"] = report
        _save(store, pair_id, pair, ST_READY if ok else ST_CORRECTION, **ids)
        return report

    try:
        project = lb.parse_file(row["lightburn_path"])
    except lb.LightBurnError as exc:
        problems.append(f"LightBurn file: {exc}")
        return finish(False)
    report["project"] = {"app_version": project.app_version, "device": project.device_name, "identifier": project.identifier}
    report["layers"] = [layer_report(layer, profile) for layer in project.layers]
    plate, plan = _load_plate(store, project.identifier)
    if project.identifier and plate is None:
        problems.append(f"experiment identifier {project.identifier} is not known to this system")
    if plate is not None:
        ids["plate_id"], ids["plan_id"] = plate["id"], (plan or {}).get("id")
        report["plate"] = {"experiment_id": plate["experiment_id"], "profile_id": plate["profile_id"]}
        if plate["profile_id"] != row["profile_id"]:
            problems.append("this plate was generated for a different laser profile version than the one selected")
        report["lens"] = lens_check(store, plate)
    # The marker layer of a system-generated file is never measured. A user's own file may legitimately use
    # layer index 0 (the real file this was checked against does), so skip it only for files this system wrote.
    system_plan = plan if plate is not None else (pl.get_plan(store, row["plan_id"]) if row["plan_id"] else None)
    marker_idx = pl.MARKER_LAYER_INDEX if system_plan is not None and system_plan.get("markers") else None
    work_layers = [layer for layer in project.layers if layer.regions and layer.index != marker_idx]
    for rep in report["layers"]:
        if rep["index"] == marker_idx:
            rep["compatible"], rep["notes"] = False, ["registration marker layer: not measured"]
    return _measure(store, row, pair, profile, project, plate, plan, corners, work_layers, report, problems, finish, allow_non_raw,
                    corners_fraction)


def _measure(store, row, pair, profile, project, plate, plan, corners, work_layers, report, problems, finish, allow_non_raw,
             corners_fraction=None):
    """Photograph steps of the check: decode, chart gate, alignment, plate discrepancies, region sampling."""
    try:
        img_bgr = ph.decode_image(row["photo_path"], allow_non_raw=allow_non_raw or non_raw_allowed(store))
    except ph.PhotoError as exc:
        problems.append(f"Photograph: {exc}")
        return finish(False)
    height, width = img_bgr.shape[:2]
    report["image_size"] = [width, height]
    if corners_fraction:
        if len(corners_fraction) != 4 or any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in corners_fraction):
            problems.append("Alignment: the four corners must lie inside the photograph")
            return finish(False)
        corners = [(x * width, y * height) for x, y in corners_fraction]
        pair["corners"] = corners
    corrected, chart, corr = ph.correct(img_bgr)
    report["chart"] = {"detected": chart.detected, "reason": chart.reason,
                       "residual": None if corr is None else round(corr.residual, 3)}
    if corrected is None:  # REQ-009: no usable chart, no observations
        problems.append("Reference chart not detected or not usable: no observations will be created. " + chart.reason)
        return finish(False)
    try:
        h, dx, dy = _align(store, row, img_bgr, plate, plan, corners, work_layers, report)
    except ph.PhotoError as exc:
        report["alignment"].update(valid=False, error=str(exc))
        problems.append(f"Alignment: {exc}")
        return finish(False)
    report["alignment"]["valid"] = True
    report["alignment"]["image_to_mm"] = np.asarray(h, float).tolist()
    if plate is not None:
        discrepancies, _, missing = compare_plate(plate["cells"], work_layers, dx, dy)
        report["discrepancies"] = discrepancies
        if missing:
            problems.append(f"plate cells not found in the LightBurn file: {', '.join(missing)}")
            return finish(False)
        if discrepancies and not pair.get("file_confirmation"):
            problems.append("The LightBurn file differs from the plate definition: correct the pair or confirm that this file was used")
    shape = corrected.shape[:2]
    by_index = {layer.index: layer for layer in project.layers}
    for rep in report["layers"]:
        if not rep["compatible"]:
            continue
        mask = ph.layer_mask([region.polygon for region in by_index[rep["index"]].regions], h, shape)
        try:
            rep["measured_lab"], rep["pixels"] = ph.sample_lab(corrected, mask)
        except ph.PhotoError as exc:
            rep["compatible"] = False
            rep["notes"].append(str(exc))
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


def review_masks(store: Store, pair_id: int) -> None:
    row = _pair_row(store, pair_id)
    _guard_mutable(row)
    pair = get_pair(store, pair_id)
    if not ((pair.get("check") or {}).get("alignment") or {}).get("valid"):
        raise IngestError("align the photograph before reviewing the masks")
    pair["masks_reviewed"] = True
    _save(store, pair_id, pair)



# -- acceptance ----------------------------------------------------------------------------------------
def accept_pair(store: Store, pair_id: int, on_accepted: Callable[[Store, int], None] | None = None) -> list[int]:
    """Write one immutable observation per measured layer, atomically. Returns the observation ids."""
    row = _pair_row(store, pair_id)
    _guard_mutable(row)
    pair = get_pair(store, pair_id)
    check = pair.get("check")
    profile = pf.get_profile(store, row["profile_id"])
    if not check or row["status"] != ST_READY:
        raise IngestError("run the check first; the pair is not ready to accept")
    if not check["chart"]["detected"]:
        raise IngestError("no reference chart was detected: no observations can be created")
    if check["problems"]:
        raise IngestError("resolve the problems found by the check: " + "; ".join(check["problems"]))
    if check["discrepancies"] and not pair["file_confirmation"]:
        raise IngestError("the LightBurn file differs from the plate definition: correct the pair or confirm the file")
    if not pair["masks_reviewed"]:
        raise IngestError("review the layer masks overlaid on the photograph before accepting")
    layers = [rep for rep in check["layers"] if rep["measured_lab"] is not None]
    if not layers:
        raise IngestError("no readable, comparable layer to accept")
    rephoto = pair["rephoto_of"] is not None
    reason = "chart detected, aligned, layer readable and comparable"
    if rephoto:
        reason += "; re-photograph of an already counted engraving, never an independent repetition (DEC-021)"
    ids: list[int] = []
    with store.transaction():
        for rep in layers:
            params = pf.parameter_vector(profile, rep["power"], rep["frequency_khz"], rep["speed"])
            evidence = {"discrepancies": check["discrepancies"], "file_confirmation": pair["file_confirmation"],
                        "pixels": rep["pixels"], "chart_residual": check["chart"]["residual"], "layer_name": rep["name"],
                        "lightburn_file": row["lightburn_name"]}
            ids.append(store.execute(
                "INSERT INTO observation(pair_id,layer_index,profile_id,engraving_id,lab_json,parameters_json,alignment_method,"
                "context_json,model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pair_id, rep["index"], row["profile_id"], row["engraving_id"], json.dumps(rep["measured_lab"]), json.dumps(params),
                 check["alignment"]["method"], row["context_json"], 1, 0 if rephoto else 1, reason, json.dumps(evidence), now())).lastrowid)
        store.execute("UPDATE pair SET status=?, accepted_at=? WHERE id=?", (ST_ACCEPTED, now(), pair_id))
        store.audit("pair_accepted", pair_id=pair_id, observations=len(ids))
    if on_accepted is not None:
        on_accepted(store, row["profile_id"])
    return ids


def delete_pair(store: Store, pair_id: int) -> None:
    row = _pair_row(store, pair_id)
    if row["status"] == ST_ACCEPTED:
        raise IngestError("an accepted pair and its measurements are protected and cannot be deleted")
    store.execute("DELETE FROM pair WHERE id=?", (pair_id,))
    for col in ("lightburn_path", "photo_path"):
        Path(row[col]).unlink(missing_ok=True)
    store.audit("pair_deleted", pair_id=pair_id)


# -- overlay for the mask review -----------------------------------------------------------------------
MAX_OVERLAY_PX = 1400


def overlay_png(store: Store, pair_id: int, corrected: bool = True) -> bytes:
    """PNG of the photograph with every measured layer's mask outlined, for the operator's review (REQ-015).

    The overlay is recomputed from the stored alignment, so it shows exactly what ``check_pair`` measured.
    ``corrected=False`` shows the photograph as decoded, before chart correction.
    """
    import cv2

    row = _pair_row(store, pair_id)
    pair = get_pair(store, pair_id)
    check = pair.get("check") or {}
    h = (check.get("alignment") or {}).get("image_to_mm")
    if not h:
        raise IngestError("the photograph is not aligned yet: run the check first")
    img_bgr = ph.decode_image(row["photo_path"], allow_non_raw=non_raw_allowed(store))
    if corrected:
        rgb, _, _ = ph.correct(img_bgr)
        if rgb is not None:
            img_bgr = cv2.cvtColor((np.clip(rgb, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    project = lb.parse_file(row["lightburn_path"])
    by_index = {layer.index: layer for layer in project.layers}
    palette = [(60, 60, 255), (60, 200, 60), (255, 120, 40), (30, 220, 220), (220, 60, 200), (200, 200, 60)]
    for n, rep in enumerate(check.get("layers", [])):
        if rep.get("measured_lab") is None:
            continue
        mask = ph.layer_mask([r.polygon for r in by_index[rep["index"]].regions], np.asarray(h, float), img_bgr.shape[:2])
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img_bgr, contours, -1, palette[n % len(palette)], max(2, img_bgr.shape[1] // 400))
    scale = min(1.0, MAX_OVERLAY_PX / max(img_bgr.shape[:2]))
    if scale < 1.0:
        img_bgr = cv2.resize(img_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img_bgr)
    if not ok:
        raise IngestError("could not render the overlay")
    return buf.tobytes()


def photo_preview_png(store: Store, pair_id: int, corrected: bool = False) -> bytes:
    """The decoded photograph, downscaled, so the operator can place the four corners on it."""
    import cv2

    row = _pair_row(store, pair_id)
    img = ph.decode_image(row["photo_path"], allow_non_raw=non_raw_allowed(store))
    if corrected:
        rgb, _, _ = ph.correct(img)
        if rgb is not None:
            img = cv2.cvtColor((np.clip(rgb, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    scale = min(1.0, MAX_OVERLAY_PX / max(img.shape[:2]))
    if scale < 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise IngestError("could not render the photograph")
    return buf.tobytes()

