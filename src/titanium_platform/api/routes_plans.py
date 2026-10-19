"""Plans, conversions (discrete and continuous), export, and the Experiment Designer."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from pydantic import BaseModel

from .. import conversion, designer, plans, research, setup as su, vector_job
from .common import MAX_IMAGE_BYTES, content_disposition, image_media_type, lens_param, public_plan, read_upload, store_of, task_goals

router = APIRouter(prefix="/api")


class DiscreteUpdate(BaseModel):
    threshold: float | None = None
    replacements: dict[str, int] | None = None
    exclusions: list[str] | None = None
    allowed_questioned: list[int] | None = None


class MarkersIn(BaseModel):
    enabled: bool


class ProposeIn(BaseModel):
    device_id: int
    lens_id: int | None            # required: null is the unknown lens
    pulse_width: float             # the job-settings group of the proposal (DEC-042); nothing is filled in
    line_interval: float
    passes: int
    seed: int = 1729
    size: int = designer.DEFAULT_SIZE
    material_id: int | None = None  # one titanium stock; none models every stock measured with these job settings


class DesignerPlatesIn(BaseModel):
    cell_width: float
    cell_height: float
    gap: float


class RejectIn(BaseModel):
    note: str = ""


def _plan(request: Request, plan_id: int, regions: bool = False) -> dict:
    s = store_of(request)
    result = public_plan(plans.with_operating_points(s, _visible_plan(s, plan_id)), with_regions=regions)
    result["active_pairs"] = s.one("SELECT COUNT(*) AS n FROM pair WHERE plan_id=? AND status!='Deleted'", (plan_id,))["n"]
    return result


def _visible_plan(s, plan_id: int) -> dict:
    plan = plans.get_plan(s, plan_id)
    if plan["status"] == "Deleted":
        raise KeyError(f"plan {plan_id} not found")
    return plan


@router.get("/plans")
def list_plans(request: Request):
    s = store_of(request)
    out = []
    for r in s.query("SELECT id FROM plan WHERE status!='Deleted' ORDER BY id DESC"):
        p = public_plan(plans.get_plan(s, r["id"]))
        out.append({k: p.get(k) for k in ("id", "name", "mode", "status", "device_id", "lens_id", "band_count", "plan_identifier", "created_at",
                                           "test_type", "experiment")} | {"layers": len(p.get("layers", []))})
    return out


@router.get("/plans/{plan_id}")
def get_plan(plan_id: int, request: Request):
    return _plan(request, plan_id)


@router.get("/plans/{plan_id}/banding.png")
def plan_banding(plan_id: int, request: Request):
    """The banding of a discrete or photo engraving plan in its predicted colours (REQ-012)."""
    s = store_of(request)
    plan = _visible_plan(s, plan_id)
    return Response(conversion.picture_png(conversion.plan_banding(s, plan)), media_type="image/png")


@router.get("/plans/{plan_id}/source-image")
def plan_source_image(plan_id: int, request: Request):
    """The image a conversion or a vector job was made from, as it was uploaded."""
    plan = _visible_plan(store_of(request), plan_id)
    path = Path(plan.get("image_path") or "")
    if not plan.get("image_path") or not path.is_file():
        raise KeyError("the stored source image is missing")
    data = path.read_bytes()
    return Response(data, media_type=image_media_type(data), headers={"X-Content-Type-Options": "nosniff"})


@router.get("/plans/{plan_id}/export.lbrn2")
def export_plan(plan_id: int, request: Request):
    s = store_of(request)
    plan = _visible_plan(s, plan_id)
    if plan["mode"] == plans.MODE_RESTORED:
        raise su.ValidationError("a plan restored from an imported file records the job that was engraved; it is not exported as a new job")
    if plan["mode"] == plans.MODE_VECTOR:      # a vector job checks its evidence and records the file it hands out
        name, data = vector_job.export(s, plan_id)
        return Response(data, media_type="application/xml", headers={"Content-Disposition": content_disposition(name, ".lbrn2")})
    if plan["status"] == conversion.ST_DRAFT:
        raise conversion.ConversionError("the plan is a draft: finish the conversion before exporting")
    if plan["status"] in {"Superseded", "Cancelled"}:
        raise su.ProtectedError("эта плата заменена или отменена; откройте актуальную плату исследования")
    data = plans.export_lbrn2(plan)
    s.execute("UPDATE plan SET status=? WHERE id=? AND status=?", ("Exported", plan_id, conversion.ST_READY))
    return Response(data, media_type="application/xml", headers={"Content-Disposition": content_disposition(plan["name"], ".lbrn2")})


@router.put("/plans/{plan_id}/markers")
def set_markers(plan_id: int, body: MarkersIn, request: Request):
    s = store_of(request)
    if _visible_plan(s, plan_id)["mode"] == plans.MODE_RESTORED:
        raise su.ValidationError("a plan restored from an imported file records the job that was engraved; it is not exported as a new job")
    conversion.set_markers(s, plan_id, body.enabled)
    return _plan(request, plan_id)


@router.delete("/plans/{plan_id}", status_code=204)
def delete_plan(plan_id: int, request: Request):
    """Remove a plan from active experiments (DEC-047). Refused while a photograph of it is in active use: each pair is
    removed on its own first, so the knowledge it fed is rebuilt. A plan whose pairs are all deleted is archived with its
    plate as their history; a plan never photographed is deleted with its plate."""
    s = store_of(request)
    plan = _visible_plan(s, plan_id)
    linked = "(plan_id=? OR (plate_id IS NOT NULL AND plate_id IS ?))"
    if s.one(f"SELECT COUNT(*) AS n FROM pair WHERE {linked} AND status!='Deleted'", (plan_id, plan["plate_id"]))["n"]:
        raise su.ProtectedError("active input pairs are linked to this plan; delete those pairs first")
    archived_pairs = s.one(f"SELECT COUNT(*) AS n FROM pair WHERE {linked} AND status='Deleted'", (plan_id, plan["plate_id"]))["n"]
    if archived_pairs:
        # Keep the plan and plate rows as the immutable context for archived pair measurements.
        # The Deleted status removes the plan and its plate from active experiment lists and public routes.
        with s.transaction():
            s.execute("UPDATE plan SET status='Deleted' WHERE id=?", (plan_id,))
            if plan["plate_id"]:
                s.execute("UPDATE plate SET status='Deleted' WHERE id=?", (plan["plate_id"],))
            s.audit("plan_archived", plan_id=plan_id, plate_id=plan["plate_id"], archived_pairs=archived_pairs)
        return
    with s.transaction():
        s.execute("DELETE FROM target_color WHERE source_plan_id=? AND proposal_id IS NULL", (plan_id,))
        if s.one("SELECT COUNT(*) AS n FROM target_color WHERE source_plan_id=?", (plan_id,))["n"]:
            raise su.ProtectedError("targets of this plan are already used by an experiment proposal")
        s.execute("DELETE FROM plan WHERE id=?", (plan_id,))
        if plan["plate_id"]:
            s.execute("DELETE FROM plate WHERE id=?", (plan["plate_id"],))
    s.audit("plan_deleted", plan_id=plan_id)


@router.post("/discrete", status_code=201)
async def start_discrete(request: Request, device_id: int = Form(...), lens_id: str = Form(...), name: str = Form(...), width_mm: float = Form(...),
                         threshold: float | None = Form(None), markers: bool = Form(False), max_colors: int = Form(conversion.MAX_COLORS),
                         task: str | None = Form(None), goals: str | None = Form(None), image: UploadFile = File(None)):
    _, data = await read_upload(image, MAX_IMAGE_BYTES, "image")
    pid = conversion.start_discrete(store_of(request), device_id, lens_param(lens_id), data, width_mm, name, threshold=threshold,
                                    markers=markers, max_colors=max_colors, task=task or None, goals=task_goals(goals))
    return _plan(request, pid)


@router.patch("/discrete/{plan_id}")
def update_discrete(plan_id: int, body: DiscreteUpdate, request: Request):
    s = store_of(request)
    _visible_plan(s, plan_id)
    conversion.update_discrete(s, plan_id, **body.model_dump())
    return _plan(request, plan_id)


@router.get("/discrete/{plan_id}/palette")
def discrete_palette(plan_id: int, request: Request):
    s = store_of(request)
    plan = _visible_plan(s, plan_id)
    return conversion.eligible_palette(s, plan["device_id"], plan["lens_id"], allowed_questioned=plan.get("allowed_questioned", []))


@router.post("/discrete/{plan_id}/finalize")
def finalize_discrete(plan_id: int, request: Request):
    s = store_of(request)
    _visible_plan(s, plan_id)
    conversion.finalize_discrete(s, plan_id)
    return _plan(request, plan_id)


def _continuous_args(path_ids: str, allowed: str) -> tuple[list[int], list[int]]:
    try:
        return [int(x) for x in json.loads(path_ids or "[]")], [int(x) for x in json.loads(allowed or "[]")]
    except (ValueError, TypeError):
        raise su.ValidationError("the trajectory and the allowed entries must be JSON lists of whole numbers") from None


@router.get("/continuous/limits")
def continuous_limits():
    """How many bands a photo engraving can have: LightBurn's 30 output colours less the marker layer (DEC-044, DEC-066)."""
    return {"max_bands": conversion.MAX_BANDS}


@router.post("/continuous/preview")
async def preview_continuous(request: Request, device_id: int = Form(...), lens_id: str = Form(...), mode: str = Form(...),
                             width_mm: float = Form(...), bands: int = Form(...), path_ids: str = Form("[]"),
                             allowed_questioned: str = Form("[]"), image: UploadFile = File(None)):
    """The banding without saving anything: per band its share and measured set, and the picture of the bands in their
    predicted colours (``banding_png``, a data URL) so N can be judged before the plan exists."""
    _, data = await read_upload(image, MAX_IMAGE_BYTES, "image")
    path, allowed = _continuous_args(path_ids, allowed_questioned)
    p = conversion.preview_continuous(store_of(request), device_id, lens_param(lens_id), mode, data, width_mm, bands, path, allowed)
    picture = conversion.band_picture(p.pop("band_map"), [l["prediction"]["lab"] for l in p["layers"]])
    p["banding_png"] = "data:image/png;base64," + base64.b64encode(conversion.picture_png(picture)).decode("ascii")
    p["layers"] = [{k: v for k, v in l.items() if k != "regions"} for l in p["layers"]]
    return p


@router.post("/continuous", status_code=201)
async def create_continuous(request: Request, device_id: int = Form(...), lens_id: str = Form(...), mode: str = Form(...), name: str = Form(...),
                            width_mm: float = Form(...), bands: int = Form(...), path_ids: str = Form("[]"),
                            allowed_questioned: str = Form("[]"), markers: bool = Form(False), revision_of: int | None = Form(None),
                            task: str | None = Form(None), goals: str | None = Form(None), image: UploadFile = File(None)):
    _, data = await read_upload(image, MAX_IMAGE_BYTES, "image")
    path, allowed = _continuous_args(path_ids, allowed_questioned)
    s = store_of(request)
    if revision_of is not None:
        _visible_plan(s, revision_of)
    pid = conversion.create_continuous(s, device_id, lens_param(lens_id), mode, data, width_mm, bands, name, path, allowed, markers,
                                       revision_of=revision_of, task=task or None, goals=task_goals(goals))
    return _plan(request, pid)


@router.get("/palette")
def palette(request: Request, device_id: int, lens_id: str, include_questioned: bool = False):
    """Validated and production colours of one laser and lens (``lens_id=unknown`` included)."""
    s = store_of(request)
    lens = lens_param(lens_id)
    su.resolve(s, device_id, lens)
    return conversion.eligible_palette(s, device_id, lens, include_questioned_warning=include_questioned)


@router.post("/designer/propose")
def propose(body: ProposeIn, request: Request):
    return designer.propose(store_of(request), body.device_id, body.lens_id, body.pulse_width, body.line_interval, body.passes,
                            body.seed, body.size, material_id=body.material_id)


@router.get("/designer/proposals")
def proposals(request: Request, device_id: int, lens_id: str):
    s = store_of(request)
    lens = lens_param(lens_id)
    su.resolve(s, device_id, lens)
    return designer.list_proposals(s, device_id, lens)


@router.get("/designer/proposals/{proposal_id}")
def get_proposal(proposal_id: int, request: Request):
    """A proposal with what became of it (REQ-022 AC5): its plates, their photographs and acceptance, the measured outcome of
    every proposed set with its target check, and whether an AI explanation can be asked for."""
    s = store_of(request)
    return designer.get_proposal(s, proposal_id) | designer.results(s, proposal_id) | {"explanation_available": research.ai_available()}


@router.post("/designer/proposals/{proposal_id}/plates", status_code=201)
def proposal_plates(proposal_id: int, body: DesignerPlatesIn, request: Request):
    return designer.create_plates(store_of(request), proposal_id, body.cell_width, body.cell_height, body.gap)


@router.post("/designer/proposals/{proposal_id}/accept", status_code=201)
def accept_proposal(proposal_id: int, body: DesignerPlatesIn, request: Request):
    """Accept a proposal: its plates are made (the cleaning operation first in each file) and it waits for their photographs."""
    s = store_of(request)
    plates = designer.create_plates(s, proposal_id, body.cell_width, body.cell_height, body.gap)
    return {"plates": plates, "proposal": designer.get_proposal(s, proposal_id)}


@router.post("/designer/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: int, body: RejectIn, request: Request):
    return designer.reject(store_of(request), proposal_id, body.note)


@router.post("/designer/proposals/{proposal_id}/explanation")
def explain_proposal(proposal_id: int, request: Request):
    """An optional plain-text explanation and hypotheses of the proposal by the language model the AI researcher uses (REQ-006,
    DEC-013). It is stored as text only and can never change the proposal's settings or any data; without a key the proposal
    works as before and this answers that no key is configured."""
    s = store_of(request)
    designer.get_proposal(s, proposal_id)
    return designer.explain(s, proposal_id, research.proposal_explainer())
