"""Vector LightBurn jobs from an image (REQ-021, DEC-065): create, review, edit, export."""
from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from .. import setup as su, vector_job
from .common import MAX_IMAGE_BYTES, content_disposition, lens_param, public_plan, read_upload, store_of

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
                            grey_threshold: float | None = Form(None), tolerance_mm: float = Form(0.05), min_area_mm2: float = Form(0.2),
                            markers: bool = Form(False), clean: bool = Form(False), image: UploadFile = File(None)):
    """Trace an uploaded image with a strategy (color, fill, text, line) at a width in mm for one laser, lens and titanium
    stock. ``palette`` is a JSON list of sRGB colours for the colour strategy (else ``n_colors`` are found in the image)."""
    _, data = await read_upload(image, MAX_IMAGE_BYTES, "image")
    try:
        colours = None if palette in (None, "") else [[int(v) for v in rgb] for rgb in json.loads(palette)]
    except (ValueError, TypeError):
        raise su.ValidationError("the palette must be a JSON list of sRGB colours") from None
    pid = vector_job.start(store_of(request), device_id, lens_param(lens_id), material_id, data, width_mm, strategy, name,
                           threshold=threshold, n_colors=n_colors, palette=colours, grey_threshold=grey_threshold,
                           tolerance_mm=tolerance_mm, min_area_mm2=min_area_mm2, markers=markers, clean=clean)
    return _view(request, pid)


@router.get("/vector/{plan_id}")
def get_vector_job(plan_id: int, request: Request):
    return _view(request, plan_id)


@router.post("/vector/{plan_id}/edit")
def edit_vector_job(plan_id: int, op: dict, request: Request):
    """One review operation (see vector_job.edit); the job is returned as it is afterwards."""
    vector_job.edit(store_of(request), plan_id, op)
    return _view(request, plan_id)


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
