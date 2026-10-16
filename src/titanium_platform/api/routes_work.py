"""Plates, pairs (observations), knowledge, analysis and the color map."""
from __future__ import annotations

import json
import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from pydantic import BaseModel

from .. import analysis, application_guide, capability_plates, colormap, designer, experiments, ingest, knowledge, model, plans, profiles as pf
from .common import (MAX_LIGHTBURN_BYTES, MAX_PHOTO_BYTES, public_pair, public_plan, read_upload, refresh_after_change, store_of)
from .common import content_disposition

router = APIRouter(prefix="/api")


@lru_cache(maxsize=4096)
def _photo_digest(path: str, size: int, modified_ns: int) -> str:
    """Identify identical RAW bytes even when copies have different paths or names."""
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PlatesIn(BaseModel):
    profile_id: int
    powers: str
    frequencies: str
    speeds: str
    cell_width: float
    cell_height: float
    gap: float
    pulse_width: float = 200.0
    line_interval: float = 0.025
    passes: int = 1
    global_passes: int = 1
    bidirectional: bool = True
    cross_hatch: bool = False
    scan_angle: float = 0.0
    angle_increment: float = 0.0


class CapabilityPlateIn(BaseModel):
    device_id: int
    material_id: int
    test_type: str
    power: float = 20.0
    frequency: float = 48.0
    speed: float = 900.0
    pulse_width: float = 200.0
    line_interval: float = 0.025
    passes: int = 1
    global_passes: int = 1
    matrix: dict | None = None
    patch_size_mm: float = 3.0
    patches: list[dict] | None = None
    registration: str = "full"
    max_width_mm: float = 100.0
    max_height_mm: float = 100.0
    split_if_needed: bool = True


class ApplicationGoalIn(BaseModel):
    device_id: int
    material_id: int
    goal: str


class CornersIn(BaseModel):
    corners: list[list[float]] | None = None
    corners_fraction: list[list[float]] | None = None
    anchor: dict | None = None
    translation_fraction: list[float] | None = None
    rotation_degrees: float | None = None
    scale_factor: float | None = None
    mirror_horizontal: bool | None = None
    mirror_vertical: bool | None = None
    reset_alignment: bool = False


class ConfirmIn(BaseModel):
    text: str


class EngravingTitleIn(BaseModel):
    title: str


class ConfirmFlag(BaseModel):
    confirm: bool = False
    to_stage: str | None = None
    reason: str = ""


class RollbackIn(BaseModel):
    event_id: int
    confirm_production: bool = False


@router.post("/plates/preview")
def preview_plates(body: PlatesIn, request: Request):
    s = store_of(request)
    return plans.preview_series(pf.get_profile(s, body.profile_id), body.powers, body.frequencies, body.speeds,
                                body.cell_width, body.cell_height, body.gap, body.pulse_width, body.line_interval, body.passes,
                                {k: getattr(body, k) for k in ("global_passes", "bidirectional", "cross_hatch", "scan_angle", "angle_increment")})


@router.get("/plate-types")
def plate_types():
    return capability_plates.PLATE_TYPES


@router.get("/application-goals")
def application_goals():
    return application_guide.list_goals()


@router.get("/application-guide")
def application_guide_for_stock(request: Request, device_id: int, material_id: int, goal: str):
    return application_guide.suggest(store_of(request), device_id, material_id, goal)


@router.post("/application-guide/next-plate", status_code=201)
def create_next_application_plate(body: ApplicationGoalIn, request: Request):
    s = store_of(request)
    suggestion = application_guide.suggest(s, body.device_id, body.material_id, body.goal)
    plate = suggestion["plate"]
    if plate is None:
        raise pf.ValidationError(suggestion["message"])
    settings = {**plate["settings"], "research_goal": body.goal, "source_pair_id": plate["source_pair_id"]}
    return capability_plates.create(s, body.device_id, body.material_id, plate["test_type"], settings)


def _capability_settings(body: CapabilityPlateIn) -> dict:
    settings = {k: getattr(body, k) for k in ("power", "frequency", "speed", "pulse_width", "line_interval", "passes",
                                              "global_passes", "patch_size_mm", "registration", "max_width_mm", "max_height_mm")}
    settings["matrix"] = body.matrix or {}
    if body.patches is not None:
        settings["patches"] = body.patches
    return settings


@router.post("/capability-plates/preview")
def preview_capability_plate(body: CapabilityPlateIn, request: Request):
    if body.test_type == "small_patches" and body.split_if_needed:
        parts = capability_plates.preview_small_patch_parts(store_of(request), body.device_id, body.material_id,
                                                            _capability_settings(body))
        summaries = [{"sample_indexes": p["sample_indexes"], "summary": p["prepared"]["experiment"]["summary"],
                      "output_layers": len(p["prepared"]["layers"]) + 1 + int(bool(p["prepared"]["markers"]))} for p in parts]
        return {"test_type": body.test_type, "name": capability_plates.TYPE_BY_ID[body.test_type]["name"],
                "summary": summaries[0]["summary"] if len(summaries) == 1 else None,
                "output_layers": summaries[0]["output_layers"] if len(summaries) == 1 else None,
                "parts": summaries}
    prepared = capability_plates.preview(store_of(request), body.device_id, body.material_id, body.test_type,
                                         _capability_settings(body))
    return {"test_type": body.test_type, "name": prepared["experiment"]["test_name"],
            "summary": prepared["experiment"]["summary"],
            "output_layers": len(prepared["layers"]) + 1 + int(bool(prepared["markers"]))}


@router.post("/capability-plates", status_code=201)
def create_capability_plate(body: CapabilityPlateIn, request: Request):
    settings = _capability_settings(body)
    if body.test_type == "small_patches" and body.split_if_needed:
        series = capability_plates.create_small_patch_parts(store_of(request), body.device_id, body.material_id, settings)
        if len(series["parts"]) == 1:
            return {**series["parts"][0], **series}
        return series
    return capability_plates.create(store_of(request), body.device_id, body.material_id, body.test_type, settings)


@router.post("/plates", status_code=201)
def create_plates(body: PlatesIn, request: Request):
    return plans.create_plate_series(store_of(request), body.profile_id, body.powers, body.frequencies, body.speeds,
                                     body.cell_width, body.cell_height, body.gap, pulse_width=body.pulse_width,
                                     line_interval=body.line_interval, passes=body.passes,
                                     lightburn_settings={k: getattr(body, k) for k in ("global_passes", "bidirectional", "cross_hatch", "scan_angle", "angle_increment")})


@router.get("/colors")
def all_colors(request: Request, setup: str | None = None, material: str | None = None, measurement: str | None = None,
               include_unreferenced: bool = False):
    """The general colour map: every measured colour of every kept experiment (REQ-029)."""
    return colormap.collect(store_of(request), include_unreferenced=include_unreferenced, setup=setup, material=material,
                            measurement=measurement)


@router.get("/colors/search")
def search_colors(request: Request, L: float, a: float, b: float, limit: int = 12, setup: str | None = None,
                  material: str | None = None, measurement: str | None = None, include_unreferenced: bool = False):
    """Where did a wanted colour occur: the nearest recipes, with their settings and the experiments they came from."""
    return colormap.search(store_of(request), [L, a, b], limit=max(1, min(limit, 60)), setup=setup, material=material,
                           measurement=measurement, include_unreferenced=include_unreferenced)


@router.get("/experiments")
def list_experiments(request: Request):
    """One entry per experiment: a plate with all its checks, or a finished work with its photographs (REQ-028)."""
    return experiments.list_experiments(store_of(request))


@router.get("/experiments/{key}")
def get_experiment(key: str, request: Request):
    return experiments.get_experiment(store_of(request), key)


@router.get("/pairs")
def list_pairs(request: Request):
    s = store_of(request)
    rows = s.query("SELECT id FROM pair WHERE status!='Deleted' ORDER BY id DESC")
    out = []
    for r in rows:
        source = ingest.get_pair(s, r["id"])
        path = Path(source["photo_path"])
        p = public_pair(source)
        p.pop("check", None)
        try:
            stat = path.stat()
            p["photo_sha256"] = _photo_digest(str(path), stat.st_size, stat.st_mtime_ns)
        except OSError:
            p["photo_sha256"] = None
        out.append(p)
    return out


@router.patch("/engravings/{engraving_id}")
def rename_engraving(engraving_id: str, body: EngravingTitleIn, request: Request):
    ingest.rename_engraving(store_of(request), engraving_id, body.title)
    return {"engraving_id": engraving_id, "title": body.title.strip()}


@router.post("/pairs", status_code=201)
async def create_pair(request: Request, profile_id: int = Form(...), stand_id: int | None = Form(None), plan_id: int | None = Form(None),
                      rephoto_of: int | None = Form(None), context: str = Form("{}"), lightburn: UploadFile = File(None), photo: UploadFile = File(None)):
    lb_name, lb_bytes = await read_upload(lightburn, MAX_LIGHTBURN_BYTES, "LightBurn")
    ph_name, ph_bytes = await read_upload(photo, MAX_PHOTO_BYTES, "photograph")
    try:
        ctx = json.loads(context or "{}")
    except json.JSONDecodeError:
        raise pf.ValidationError("the context is not valid JSON") from None
    pid = ingest.create_pair(store_of(request), profile_id=profile_id, stand_id=stand_id, lightburn_name=lb_name, lightburn_bytes=lb_bytes,
                             photo_name=ph_name, photo_bytes=ph_bytes, plan_id=plan_id, rephoto_of=rephoto_of, context=ctx)
    return public_pair(ingest.get_pair(store_of(request), pid))


@router.get("/pairs/{pair_id}")
def get_pair(pair_id: int, request: Request):
    return public_pair(ingest.get_pair(store_of(request), pair_id))


@router.post("/pairs/{pair_id}/rephotos", status_code=201)
async def create_rephoto(pair_id: int, request: Request, photo: UploadFile = File(None)):
    name, data = await read_upload(photo, MAX_PHOTO_BYTES, "photograph")
    new_id = ingest.create_rephoto(store_of(request), pair_id, photo_name=name, photo_bytes=data)
    return public_pair(ingest.get_pair(store_of(request), new_id))


@router.post("/pairs/{pair_id}/alignment-revisions", status_code=201)
def create_alignment_revision(pair_id: int, request: Request):
    s = store_of(request)
    new_id = ingest.create_alignment_revision(s, pair_id)
    return public_pair(ingest.get_pair(s, new_id))


@router.get("/profiles/{profile_id}/previous-context")
def previous_context(profile_id: int, request: Request):
    return ingest.previous_context(store_of(request), profile_id) or {}


@router.post("/pairs/{pair_id}/check")
def check_pair(pair_id: int, body: CornersIn, request: Request):
    corners = [tuple(c) for c in body.corners] if body.corners else None
    ingest.check_pair(store_of(request), pair_id, corners=corners, corners_fraction=body.corners_fraction,
                      anchor=body.anchor, translation_fraction=body.translation_fraction,
                      rotation_degrees=body.rotation_degrees, scale_factor=body.scale_factor,
                      mirror_horizontal=body.mirror_horizontal, mirror_vertical=body.mirror_vertical,
                      reset_alignment=body.reset_alignment)
    return public_pair(ingest.get_pair(store_of(request), pair_id))


@router.post("/pairs/{pair_id}/snap")
def snap_pair(pair_id: int, body: CornersIn, request: Request):
    return {"candidates": ingest.snap_pair_overlay(
        store_of(request), pair_id, translation_fraction=body.translation_fraction,
        rotation_degrees=body.rotation_degrees, scale_factor=body.scale_factor,
        mirror_horizontal=body.mirror_horizontal, mirror_vertical=body.mirror_vertical)}


@router.post("/pairs/{pair_id}/lightburn")
async def replace_lightburn(pair_id: int, request: Request, lightburn: UploadFile = File(None)):
    name, data = await read_upload(lightburn, MAX_LIGHTBURN_BYTES, "LightBurn")
    ingest.replace_lightburn_file(store_of(request), pair_id, name, data)
    return public_pair(ingest.get_pair(store_of(request), pair_id))


@router.post("/pairs/{pair_id}/confirm-file")
def confirm_file(pair_id: int, body: ConfirmIn, request: Request):
    ingest.confirm_file(store_of(request), pair_id, body.text)
    return public_pair(ingest.get_pair(store_of(request), pair_id))


@router.post("/pairs/{pair_id}/review-masks")
def review_masks(pair_id: int, request: Request):
    ingest.review_masks(store_of(request), pair_id)
    return public_pair(ingest.get_pair(store_of(request), pair_id))


@router.post("/pairs/{pair_id}/accept")
def accept_pair(pair_id: int, request: Request):
    ids = ingest.accept_pair(store_of(request), pair_id, on_accepted=refresh_after_change)
    return {"pair": public_pair(ingest.get_pair(store_of(request), pair_id)), "observation_ids": ids}


@router.delete("/pairs/{pair_id}", status_code=204)
def delete_pair(pair_id: int, request: Request):
    s = store_of(request)
    pair = ingest.get_pair(s, pair_id)
    ingest.delete_pair(s, pair_id)
    refresh_after_change(s, pair["profile_id"])


@router.get("/pairs/{pair_id}/overlay.png")
def overlay(pair_id: int, request: Request, corrected: bool = True, layer_index: int | None = None,
            visibility: str = "normal", full: bool = False):
    return Response(ingest.overlay_png(store_of(request), pair_id, corrected=corrected, layer_index=layer_index,
                                       visibility=visibility, full=full), media_type="image/png")


@router.get("/pairs/{pair_id}/vector-overlay.png")
def vector_overlay(pair_id: int, request: Request, layer_index: int | None = None, full: bool = False):
    return Response(ingest.overlay_png(store_of(request), pair_id, corrected=False, layer_index=layer_index,
                                       transparent=True, full=full), media_type="image/png")


@router.get("/pairs/{pair_id}/photo.png")
def photo_preview(pair_id: int, request: Request, corrected: bool = False, visibility: str = "normal", full: bool = False):
    return Response(ingest.photo_preview_png(store_of(request), pair_id, corrected=corrected, visibility=visibility,
                                             full=full), media_type="image/png")


@router.get("/pairs/{pair_id}/source-photo")
def source_photo(pair_id: int, request: Request):
    from pathlib import Path
    pair = ingest.get_pair(store_of(request), pair_id)
    path = Path(pair["photo_path"])
    if not path.is_file():
        raise KeyError("the stored source photograph is missing")
    disposition = content_disposition(Path(pair["photo_name"]).stem, Path(pair["photo_name"]).suffix)
    return Response(path.read_bytes(), media_type="application/octet-stream", headers={"Content-Disposition": disposition,
                    "X-Content-Type-Options": "nosniff"})


@router.get("/pairs/{pair_id}/lightburn")
def source_lightburn(pair_id: int, request: Request):
    from pathlib import Path
    pair = ingest.get_pair(store_of(request), pair_id)
    path = Path(pair["lightburn_path"])
    if not path.is_file():
        raise KeyError("the stored LightBurn file is missing")
    disposition = content_disposition(Path(pair["lightburn_name"]).stem, Path(pair["lightburn_name"]).suffix)
    return Response(path.read_bytes(), media_type="application/octet-stream", headers={"Content-Disposition": disposition,
                    "X-Content-Type-Options": "nosniff"})


@router.get("/pairs/{pair_id}/report")
def report(pair_id: int, request: Request):
    return analysis.report_for_pair(store_of(request), pair_id)


@router.get("/profiles/{profile_id}/knowledge")
def list_knowledge(profile_id: int, request: Request):
    s = store_of(request)
    pf.get_profile(s, profile_id)
    return knowledge.list_for_profile(s, profile_id)


@router.get("/knowledge/{kid}")
def get_knowledge(kid: int, request: Request):
    return knowledge.get(store_of(request), kid)


@router.post("/knowledge/{kid}/approve")
def approve(kid: int, body: ConfirmFlag, request: Request):
    return knowledge.approve_for_production(store_of(request), kid, body.confirm)


@router.post("/knowledge/{kid}/demote")
def demote(kid: int, body: ConfirmFlag, request: Request):
    return knowledge.demote(store_of(request), kid, body.to_stage or "", body.reason, body.confirm)


@router.post("/knowledge/{kid}/confirm-questioned")
def confirm_questioned(kid: int, request: Request):
    return knowledge.confirm_questioned(store_of(request), kid)


@router.post("/knowledge/{kid}/rollback")
def rollback(kid: int, body: RollbackIn, request: Request):
    return knowledge.rollback(store_of(request), kid, body.event_id, body.confirm_production)


@router.get("/profiles/{profile_id}/map")
def color_map(profile_id: int, request: Request):
    """Measured coverage, unstable regions and open targets of one laser profile version."""
    s = store_of(request)
    pf.get_profile(s, profile_id)
    samples = list(model.knowledge_summaries(s, profile_id).values())
    rules = pf.get_rules(s, profile_id)
    return {"samples": samples, "camera_relative_sets": model.camera_relative_sets(s, profile_id),
            "unstable": model.unstable_regions(samples, rules["variance_threshold"]), "targets": designer.open_targets(s, profile_id),
            "rules": rules}


class LabIn(BaseModel):
    lab: list[float]


@router.post("/profiles/{profile_id}/predict")
def predict(profile_id: int, body: LabIn, request: Request):
    s = store_of(request)
    pf.get_profile(s, profile_id)
    return model.predict_for_lab(list(model.knowledge_summaries(s, profile_id).values()), body.lab)
