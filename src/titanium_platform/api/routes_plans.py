"""Plans, conversions (discrete and continuous), export, and the Experiment Designer."""
from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from pydantic import BaseModel

from .. import conversion, designer, plans, profiles as pf
from .common import MAX_IMAGE_BYTES, content_disposition, public_plan, read_upload, store_of

router = APIRouter(prefix="/api")


class DiscreteUpdate(BaseModel):
    threshold: float | None = None
    replacements: dict[str, int] | None = None
    exclusions: list[str] | None = None
    allowed_questioned: list[int] | None = None


class MarkersIn(BaseModel):
    enabled: bool


class ProposeIn(BaseModel):
    profile_id: int
    seed: int = 1729
    size: int = designer.DEFAULT_SIZE


class DesignerPlatesIn(BaseModel):
    cell_width: float
    cell_height: float
    gap: float


def _plan(request: Request, plan_id: int, regions: bool = False) -> dict:
    return public_plan(plans.get_plan(store_of(request), plan_id), with_regions=regions)


@router.get("/plans")
def list_plans(request: Request):
    s = store_of(request)
    out = []
    for r in s.query("SELECT id FROM plan ORDER BY id DESC"):
        p = public_plan(plans.get_plan(s, r["id"]))
        out.append({k: p.get(k) for k in ("id", "name", "mode", "status", "profile_id", "band_count", "plan_identifier", "created_at")} | {"layers": len(p.get("layers", []))})
    return out


@router.get("/plans/{plan_id}")
def get_plan(plan_id: int, request: Request):
    return _plan(request, plan_id)


@router.get("/plans/{plan_id}/export.lbrn2")
def export_plan(plan_id: int, request: Request):
    s = store_of(request)
    plan = plans.get_plan(s, plan_id)
    if plan["status"] == conversion.ST_DRAFT:
        raise conversion.ConversionError("the plan is a draft: finish the conversion before exporting")
    data = plans.export_lbrn2(plan)
    s.execute("UPDATE plan SET status=? WHERE id=? AND status=?", ("Exported", plan_id, conversion.ST_READY))
    return Response(data, media_type="application/xml", headers={"Content-Disposition": content_disposition(plan["name"], ".lbrn2")})


@router.put("/plans/{plan_id}/markers")
def set_markers(plan_id: int, body: MarkersIn, request: Request):
    conversion.set_markers(store_of(request), plan_id, body.enabled)
    return _plan(request, plan_id)


@router.delete("/plans/{plan_id}", status_code=204)
def delete_plan(plan_id: int, request: Request):
    s = store_of(request)
    plan = plans.get_plan(s, plan_id)
    if s.one("SELECT COUNT(*) AS n FROM pair WHERE plan_id=?", (plan_id,))["n"]:
        raise pf.ProtectedError("this plan is linked to stored pairs and keeps their measurement history")
    with s.transaction():
        s.execute("DELETE FROM target_color WHERE source_plan_id=? AND proposal_id IS NULL", (plan_id,))
        if s.one("SELECT COUNT(*) AS n FROM target_color WHERE source_plan_id=?", (plan_id,))["n"]:
            raise pf.ProtectedError("targets of this plan are already used by an experiment proposal")
        s.execute("DELETE FROM plan WHERE id=?", (plan_id,))
        if plan["plate_id"]:
            s.execute("DELETE FROM plate WHERE id=?", (plan["plate_id"],))
    s.audit("plan_deleted", plan_id=plan_id)


@router.post("/discrete", status_code=201)
async def start_discrete(request: Request, profile_id: int = Form(...), name: str = Form(...), width_mm: float = Form(...), threshold: float | None = Form(None),
                         markers: bool = Form(False), max_colors: int = Form(conversion.MAX_COLORS), image: UploadFile = File(None)):
    _, data = await read_upload(image, MAX_IMAGE_BYTES, "image")
    pid = conversion.start_discrete(store_of(request), profile_id, data, width_mm, name, threshold=threshold, markers=markers, max_colors=max_colors)
    return _plan(request, pid)


@router.patch("/discrete/{plan_id}")
def update_discrete(plan_id: int, body: DiscreteUpdate, request: Request):
    conversion.update_discrete(store_of(request), plan_id, **body.model_dump())
    return _plan(request, plan_id)


@router.get("/discrete/{plan_id}/palette")
def discrete_palette(plan_id: int, request: Request):
    s = store_of(request)
    plan = plans.get_plan(s, plan_id)
    return conversion.eligible_palette(s, plan["profile_id"], allowed_questioned=plan.get("allowed_questioned", []))


@router.post("/discrete/{plan_id}/finalize")
def finalize_discrete(plan_id: int, request: Request):
    conversion.finalize_discrete(store_of(request), plan_id)
    return _plan(request, plan_id)


def _continuous_args(path_ids: str, allowed: str) -> tuple[list[int], list[int]]:
    try:
        return [int(x) for x in json.loads(path_ids or "[]")], [int(x) for x in json.loads(allowed or "[]")]
    except (ValueError, TypeError):
        raise pf.ValidationError("the trajectory and the allowed entries must be JSON lists of whole numbers") from None


@router.post("/continuous/preview")
async def preview_continuous(request: Request, profile_id: int = Form(...), mode: str = Form(...), width_mm: float = Form(...), bands: int = Form(...),
                             path_ids: str = Form("[]"), allowed_questioned: str = Form("[]"), image: UploadFile = File(None)):
    _, data = await read_upload(image, MAX_IMAGE_BYTES, "image")
    path, allowed = _continuous_args(path_ids, allowed_questioned)
    p = conversion.preview_continuous(store_of(request), profile_id, mode, data, width_mm, bands, path, allowed)
    p["layers"] = [{k: v for k, v in l.items() if k != "regions"} for l in p["layers"]]
    return p


@router.post("/continuous", status_code=201)
async def create_continuous(request: Request, profile_id: int = Form(...), mode: str = Form(...), name: str = Form(...), width_mm: float = Form(...), bands: int = Form(...),
                            path_ids: str = Form("[]"), allowed_questioned: str = Form("[]"), markers: bool = Form(False), image: UploadFile = File(None)):
    _, data = await read_upload(image, MAX_IMAGE_BYTES, "image")
    path, allowed = _continuous_args(path_ids, allowed_questioned)
    pid = conversion.create_continuous(store_of(request), profile_id, mode, data, width_mm, bands, name, path, allowed, markers)
    return _plan(request, pid)


@router.get("/profiles/{profile_id}/palette")
def palette(profile_id: int, request: Request, include_questioned: bool = False):
    s = store_of(request)
    pf.get_profile(s, profile_id)
    return conversion.eligible_palette(s, profile_id, include_questioned_warning=include_questioned)


@router.post("/designer/propose")
def propose(body: ProposeIn, request: Request):
    return designer.propose(store_of(request), body.profile_id, body.seed, body.size)


@router.get("/profiles/{profile_id}/proposals")
def proposals(profile_id: int, request: Request):
    s = store_of(request)
    pf.get_profile(s, profile_id)
    return designer.list_proposals(s, profile_id)


@router.get("/designer/proposals/{proposal_id}")
def get_proposal(proposal_id: int, request: Request):
    return designer.get_proposal(store_of(request), proposal_id)


@router.post("/designer/proposals/{proposal_id}/plates", status_code=201)
def proposal_plates(proposal_id: int, body: DesignerPlatesIn, request: Request):
    return designer.create_plates(store_of(request), proposal_id, body.cell_width, body.cell_height, body.gap)
