"""Vector LightBurn jobs from an image (REQ-021, DEC-065): create, review, edit, export. A photograph job (REQ-042) is split
again and coloured through its own routes (its colour editor: paint, merge, undo and redo, the preview of a fill and the
neighbours of every region); its geometry reaches the browser once per split version as an SVG."""
from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from .. import segment, setup as su, vector_job
from .common import MAX_IMAGE_BYTES, content_disposition, form_flag, lens_param, public_plan, read_upload, store_of, task_goals

router = APIRouter(prefix="/api")


def _view(request: Request, plan_id: int) -> dict:
    return public_plan(vector_job.view(store_of(request), plan_id))


@router.get("/vector/palette")
def vector_palette(request: Request, device_id: int, lens_id: str, material_id: int):
    """The recipes a vector job of this laser, lens and titanium stock can use, every LightBurn mode, with their sRGB."""
    s = store_of(request)
    lens = lens_param(lens_id)
    su.resolve(s, device_id, lens)
    return vector_job.eligible(s, device_id, lens, material_id)


@router.post("/vector", status_code=201)
async def create_vector_job(request: Request, device_id: int = Form(...), lens_id: str = Form(...), material_id: int = Form(...),
                            name: str = Form(...), width_mm: float = Form(...), strategy: str = Form(...),
                            threshold: float | None = Form(None), n_colors: int | None = Form(None), palette: str | None = Form(None),
                            grey_threshold: float | None = Form(None), tolerance_mm: float | None = Form(None), min_area_mm2: float = Form(0.2),
                            markers: bool = Form(False), clean: bool = Form(False), task: str | None = Form(None),
                            goals: str | None = Form(None), detail: str | None = Form(None), faces: str | None = Form(None),
                            algorithm: str | None = Form(None), max_time: float | None = Form(None), include_as_shot: bool = Form(False), image: UploadFile = File(None)):
    """Trace an uploaded image with a strategy (color, fill, text, line) at a width in mm for one laser, lens and titanium
    stock. ``palette`` is a JSON list of sRGB colours for the colour strategy (else ``n_colors`` are found in the image).
    ``task`` and ``goals`` (a JSON object) are the job's main engraving task (REQ-020); empty: the one its strategy serves.
    The ``photo`` strategy splits a photograph into ``n_colors`` regions by an ``algorithm`` (slic, the default, tonal, planes or seeds) at a
    level of ``detail`` with ``faces`` first, smoothed by ``tolerance_mm`` (``faces`` left out: searched); it always cleans first, and ``threshold``, ``max_time`` (s/cm²) and ``include_as_shot``
    rule its automatic colouring."""
    _, data = await read_upload(image, MAX_IMAGE_BYTES, "image")
    if strategy == vector_job.PHOTO:
        pid = vector_job.start_photo(store_of(request), device_id, lens_param(lens_id), material_id, data, width_mm, name, threshold=threshold,
                                     n_colors=n_colors, detail=detail or vector_job.DEFAULT_DETAIL,
                                     algorithm=algorithm or segment.DEFAULT_ALGORITHM,
                                     tolerance_mm=segment.TOLERANCE_MM if tolerance_mm is None else tolerance_mm,
                                     use_faces=form_flag(faces, True, "face search"),
                                     markers=markers, max_time=max_time, include_as_shot=include_as_shot, task=task or None,
                                     goals=task_goals(goals))
        return _view(request, pid)
    try:
        colours = None if palette in (None, "") else [[int(v) for v in rgb] for rgb in json.loads(palette)]
    except (ValueError, TypeError):
        raise su.ValidationError("the palette must be a JSON list of sRGB colours") from None
    pid = vector_job.start(store_of(request), device_id, lens_param(lens_id), material_id, data, width_mm, strategy, name,
                           threshold=threshold, n_colors=n_colors, palette=colours, grey_threshold=grey_threshold,
                           tolerance_mm=0.05 if tolerance_mm is None else tolerance_mm, min_area_mm2=min_area_mm2, markers=markers,
                           clean=clean, task=task or None, goals=task_goals(goals))
    return _view(request, pid)


@router.get("/vector/{plan_id}")
def get_vector_job(plan_id: int, request: Request):
    return _view(request, plan_id)


@router.post("/vector/{plan_id}/edit")
def edit_vector_job(plan_id: int, op: dict, request: Request):
    """One review operation (see vector_job.edit); the job is returned as it is afterwards."""
    vector_job.edit(store_of(request), plan_id, op)
    return _view(request, plan_id)


@router.post("/vector/{plan_id}/split")
def split_vector_job(plan_id: int, body: dict, request: Request):
    """Split a photograph job's picture again (see vector_job.resplit): ``n_colors``, ``detail``, ``tolerance_mm``,
    ``faces``, ``manual`` areas in picture pixels and ``removed`` detected areas."""
    vector_job.resplit(store_of(request), plan_id, body)
    return _view(request, plan_id)


@router.post("/vector/{plan_id}/smoothing")
def smooth_vector_job(plan_id: int, body: dict, request: Request):
    """Set how smooth a photograph job's borders are (see vector_job.smooth): ``mm`` from 0 (as traced) to the end of the slider.
    Only the drawing of the borders changes; the job is returned as it is afterwards."""
    vector_job.smooth(store_of(request), plan_id, body.get("mm"))
    return _view(request, plan_id)


@router.post("/vector/{plan_id}/ai-photo")
def allow_vector_photo(plan_id: int, body: dict, request: Request):
    """Allow (``allowed`` true) or forbid sending a reduced copy of a photograph job's picture to the language model with the numbers
    of an AI colouring (see vector_job.allow_photo). The job remembers the answer; it is off until the operator turns it on."""
    vector_job.allow_photo(store_of(request), plan_id, body.get("allowed"))
    return _view(request, plan_id)


@router.post("/vector/{plan_id}/colouring")
def colour_vector_job(plan_id: int, op: dict, request: Request):
    """One operation of a photograph job's colour editor (see vector_job.colour): an automatic mode, a variant, the
    settings, a click of the brush, a choice by hand, an exclusion, a merge of titanium colours, source colours or regions,
    undo and redo; the job is returned as it is afterwards."""
    vector_job.colour(store_of(request), plan_id, op)
    return _view(request, plan_id)


@router.get("/vector/{plan_id}/reach")
def vector_job_reach(plan_id: int, request: Request, region: str | None = None, similarity_de: str | None = None):
    """The regions a click of the brush with the fill scope on ``region`` would paint at ``similarity_de`` (see
    vector_job.reach), with their pixels and share; nothing is changed. Both are checked by the job, whose messages the
    screen translates."""
    return vector_job.reach(store_of(request), plan_id, region, similarity_de)


@router.get("/vector/{plan_id}/neighbours")
def vector_job_neighbours(plan_id: int, request: Request):
    """Which regions of the current split border which (see vector_job.neighbours), so that the screen offers the merge of
    regions only for a connected selection; nothing is changed. The server still checks every merge it is asked for."""
    return vector_job.neighbours(store_of(request), plan_id)


@router.get("/vector/{plan_id}/split.svg")
def vector_split_svg(plan_id: int, request: Request):
    """The current split of a photograph job in its source colours; each path names its region and colour index."""
    return Response(vector_job.split_svg(store_of(request), plan_id), media_type="image/svg+xml")


@router.get("/vector/{plan_id}/palette")
def vector_job_palette(plan_id: int, request: Request):
    """Every measured colour a photograph job may be coloured with by hand, with its evidence and time per cm²."""
    return vector_job.photo_palette(store_of(request), plan_id)


@router.get("/vector/{plan_id}/export.lbrn2")
def export_vector_job(plan_id: int, request: Request):
    name, data = vector_job.export(store_of(request), plan_id)
    return Response(data, media_type="application/xml", headers={"Content-Disposition": content_disposition(name, ".lbrn2")})


@router.get("/vector/{plan_id}/exports/{number}")
def stored_vector_export(plan_id: int, number: int, request: Request):
    """A file handed out earlier, exactly as it was written."""
    name, data = vector_job.stored_export(store_of(request), plan_id, number)
    return Response(data, media_type="application/xml",
                    headers={"Content-Disposition": content_disposition(name.removesuffix(".lbrn2"), ".lbrn2")})
