"""Plates, pairs (observations), knowledge, analysis and the color map."""
from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from pydantic import BaseModel

from .. import analysis, designer, ingest, knowledge, model, plans, profiles as pf
from .common import (MAX_LIGHTBURN_BYTES, MAX_PHOTO_BYTES, public_pair, public_plan, read_upload, refresh_after_change, store_of)

router = APIRouter(prefix="/api")


class PlatesIn(BaseModel):
    profile_id: int
    powers: str
    frequencies: str
    speeds: str
    cell_width: float
    cell_height: float
    gap: float


class CornersIn(BaseModel):
    corners: list[list[float]] | None = None
    corners_fraction: list[list[float]] | None = None


class ConfirmIn(BaseModel):
    text: str


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
    return plans.preview_series(pf.get_profile(s, body.profile_id), body.powers, body.frequencies, body.speeds, body.cell_width, body.cell_height, body.gap)


@router.post("/plates", status_code=201)
def create_plates(body: PlatesIn, request: Request):
    return plans.create_plate_series(store_of(request), body.profile_id, body.powers, body.frequencies, body.speeds, body.cell_width, body.cell_height, body.gap)


@router.get("/pairs")
def list_pairs(request: Request):
    s = store_of(request)
    rows = s.query("SELECT id FROM pair ORDER BY id DESC")
    out = []
    for r in rows:
        p = public_pair(ingest.get_pair(s, r["id"]))
        p.pop("check", None)
        out.append(p)
    return out


@router.post("/pairs", status_code=201)
async def create_pair(request: Request, profile_id: int = Form(...), stand_id: int = Form(...), plan_id: int | None = Form(None),
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


@router.get("/profiles/{profile_id}/previous-context")
def previous_context(profile_id: int, request: Request):
    return ingest.previous_context(store_of(request), profile_id) or {}


@router.post("/pairs/{pair_id}/check")
def check_pair(pair_id: int, body: CornersIn, request: Request):
    corners = [tuple(c) for c in body.corners] if body.corners else None
    ingest.check_pair(store_of(request), pair_id, corners=corners, corners_fraction=body.corners_fraction)
    return public_pair(ingest.get_pair(store_of(request), pair_id))


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
    ingest.delete_pair(store_of(request), pair_id)


@router.get("/pairs/{pair_id}/overlay.png")
def overlay(pair_id: int, request: Request, corrected: bool = True):
    return Response(ingest.overlay_png(store_of(request), pair_id, corrected=corrected), media_type="image/png")


@router.get("/pairs/{pair_id}/photo.png")
def photo_preview(pair_id: int, request: Request, corrected: bool = False):
    return Response(ingest.photo_preview_png(store_of(request), pair_id, corrected=corrected), media_type="image/png")


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
    return {"samples": samples, "unstable": model.unstable_regions(samples, rules["variance_threshold"]), "targets": designer.open_targets(s, profile_id),
            "rules": rules}


class LabIn(BaseModel):
    lab: list[float]


@router.post("/profiles/{profile_id}/predict")
def predict(profile_id: int, body: LabIn, request: Request):
    s = store_of(request)
    pf.get_profile(s, profile_id)
    return model.predict_for_lab(list(model.knowledge_summaries(s, profile_id).values()), body.lab)
