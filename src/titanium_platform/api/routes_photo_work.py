"""Photo engraving works (REQ-061, DEC-104): list, create, open, change, copy, rename, their pictures and their LightBurn file; the parts
of a work's picture and the AI that proposes their rules (REQ-062, DEC-105). A work is deleted as every plan is (``DELETE /api/plans/{id}``)."""
from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from .. import photo_work, setup as su
from .common import MAX_IMAGE_BYTES, content_disposition, picture_response, read_upload, store_of

router = APIRouter(prefix="/api")


@router.get("/photo-works")
def list_photo_works(request: Request):
    """Every photo work, the newest first (see photo_work.listing)."""
    return photo_work.listing(store_of(request))


@router.post("/photo-works", status_code=201)
async def create_photo_work(request: Request, width_mm: float = Form(...), name: str | None = Form(None), scale: str | None = Form(None),
                            picture: UploadFile = File(None)):
    """A new work of an uploaded picture (PNG, JPEG ...) ``width_mm`` wide; ``scale`` (JSON, as the list of scales gives a scale's mode)
    is optional: without it the best measured scale is taken. The work is returned as it opens."""
    file_name, data = await read_upload(picture, MAX_IMAGE_BYTES, "picture")
    try:
        wanted = None if scale in (None, "") else json.loads(scale)
    except ValueError:
        raise su.ValidationError("this scale is not measured: choose one of the measured scales") from None
    s = store_of(request)
    return photo_work.view(s, photo_work.create(s, data, file_name, name, width_mm, wanted))


@router.get("/photo-works/{plan_id}")
def get_photo_work(plan_id: int, request: Request):
    return photo_work.view(store_of(request), plan_id)


@router.post("/photo-works/{plan_id}/settings")
def change_photo_work(plan_id: int, body: dict, request: Request):
    """Change the scale, Min and Max power, the width, the colour choice, the rules of the parts or the permission to send the picture to
    the AI (see photo_work.update); the work is returned as it is now."""
    s = store_of(request)
    photo_work.update(s, plan_id, body)
    return photo_work.view(s, plan_id)


@router.post("/photo-works/{plan_id}/copy", status_code=201)
def copy_photo_work(plan_id: int, request: Request, body: dict | None = None):
    return {"id": photo_work.copy_work(store_of(request), plan_id, (body or {}).get("name"))}


@router.post("/photo-works/{plan_id}/rename")
def rename_photo_work(plan_id: int, request: Request, body: dict | None = None):
    return {"id": plan_id, "name": photo_work.rename_work(store_of(request), plan_id, (body or {}).get("name"))}


@router.get("/photo-works/{plan_id}/preview.png")
def photo_work_preview(plan_id: int, request: Request):
    """The picture beside its predicted look on the titanium."""
    return picture_response(request, photo_work.preview(store_of(request), plan_id))


@router.get("/photo-works/{plan_id}/thumb.png")
def photo_work_thumbnail(plan_id: int, request: Request):
    """The work in the list: its predicted look on the titanium."""
    return picture_response(request, photo_work.thumbnail(store_of(request), plan_id))


@router.get("/photo-works/{plan_id}/picture")
def photo_work_picture(plan_id: int, request: Request):
    """The picture as it was uploaded."""
    data, media_type = photo_work.original(store_of(request), plan_id)
    return Response(data, media_type=media_type, headers={"Cache-Control": "private, max-age=0, must-revalidate"})


@router.get("/photo-works/{plan_id}/export.lbrn2")
def photo_work_file(plan_id: int, request: Request):
    """The LightBurn file of the work: one grayscale Image layer at its scale's settings, Min and Max, the picture at its width."""
    data, name = photo_work.export(store_of(request), plan_id)
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": content_disposition(name, ".lbrn2"), "Cache-Control": "no-store"})


@router.get("/photo-works/{plan_id}/parts")
def photo_work_parts(plan_id: int, request: Request):
    """The parts the people model finds in the picture: share and mean colour of each, and the address of the picture tinted by part."""
    return photo_work.parts(store_of(request), plan_id)


@router.get("/photo-works/{plan_id}/parts.png")
def photo_work_parts_picture(plan_id: int, request: Request):
    """The picture with every part tinted in its colour."""
    return picture_response(request, photo_work.parts_picture(store_of(request), plan_id))


@router.post("/photo-works/{plan_id}/ai")
def ask_photo_work_ai(plan_id: int, request: Request, body: dict | None = None):
    """Ask the AI for the rules of the parts after the operator's ``wish``; the work is returned with them (see photo_work.ask_ai)."""
    s = store_of(request)
    photo_work.ask_ai(s, plan_id, (body or {}).get("wish"))
    return photo_work.view(s, plan_id)
