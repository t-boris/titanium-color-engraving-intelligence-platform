"""Business card works (feature-2): list, create, open, edit, undo and redo, copy, rename, import a graphic, generate a picture from a
description, and the preview and LightBurn file of each side. A work is deleted as every plan is (``DELETE /api/plans/{id}``)."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from .. import card_work, setup as su
from .common import MAX_IMAGE_BYTES, content_disposition, read_upload, store_of

router = APIRouter(prefix="/api")


@router.get("/card-library")
def card_library():
    """What the editor offers: shapes, frames and icons with their parameters, the QR kinds and fields, picture treatment, card sizes."""
    return card_work.library()


@router.get("/card-works")
def list_card_works(request: Request):
    """Every card work, the newest first."""
    return card_work.listing(store_of(request))


@router.post("/card-works", status_code=201)
def create_card_work(body: dict, request: Request):
    """A new, empty card: ``name``, ``preset`` ("85x53", "85x54" or "custom") and, for a custom card, ``width_mm`` and ``height_mm``."""
    s = store_of(request)
    return card_work.view(s, card_work.create(s, body.get("name"), body.get("preset", "85x53"), body.get("width_mm"), body.get("height_mm")))


@router.get("/card-works/{plan_id}")
def get_card_work(plan_id: int, request: Request):
    return card_work.view(store_of(request), plan_id)


@router.post("/card-works/{plan_id}/edit")
def edit_card_work(plan_id: int, body: dict, request: Request):
    """One edit of the card (``op``: add, set, move, resize, rotate, reorder, duplicate, delete, group, ungroup, assign_settings,
    settings_add, settings_set, settings_delete, set_size); the work is returned as it is now, with ``added``."""
    return card_work.edit(store_of(request), plan_id, body)


@router.post("/card-works/{plan_id}/undo")
def undo_card_work(plan_id: int, request: Request):
    return card_work.step(store_of(request), plan_id, "undo")


@router.post("/card-works/{plan_id}/redo")
def redo_card_work(plan_id: int, request: Request):
    return card_work.step(store_of(request), plan_id, "redo")


@router.post("/card-works/{plan_id}/rename")
def rename_card_work(plan_id: int, body: dict, request: Request):
    return {"name": card_work.rename_work(store_of(request), plan_id, body.get("name"))}


@router.post("/card-works/{plan_id}/copy", status_code=201)
def copy_card_work(plan_id: int, body: dict, request: Request):
    s = store_of(request)
    return card_work.view(s, card_work.copy_work(s, plan_id, body.get("name")))


@router.post("/card-works/{plan_id}/images")
async def import_card_image(plan_id: int, request: Request, side: str = Form(...), picture: UploadFile = File(None)):
    """Add a graphic (PNG, JPEG, GIF, BMP, TIFF, WebP) to a side; it is traced into shapes that can be engraved."""
    file_name, data = await read_upload(picture, MAX_IMAGE_BYTES, "picture")
    return card_work.add_image(store_of(request), plan_id, side, file_name, data)


@router.post("/card-works/{plan_id}/generate")
def generate_card_picture(plan_id: int, body: dict, request: Request):
    """Generate an icon or a drawing (``kind``) from a ``description`` with the OpenAI image service and add it to ``side``."""
    return card_work.generate(store_of(request), plan_id, body.get("side"), body.get("description"), body.get("kind"))


@router.get("/card-works/{plan_id}/sides/{side}/preview.svg")
def card_side_preview(plan_id: int, side: str, request: Request):
    return Response(card_work.preview_svg(store_of(request), plan_id, side), media_type="image/svg+xml",
                    headers={"Cache-Control": "private, max-age=0, must-revalidate"})


@router.get("/card-works/{plan_id}/thumb.svg")
def card_thumb(plan_id: int, request: Request):
    return Response(card_work.preview_svg(store_of(request), plan_id, "front"), media_type="image/svg+xml",
                    headers={"Cache-Control": "private, max-age=0, must-revalidate"})


@router.get("/card-works/{plan_id}/sides/{side}/export.lbrn2")
def card_side_file(plan_id: int, side: str, request: Request):
    """The LightBurn project of one side of the card: its shapes at their physical size, on a layer for each set of engraving settings."""
    data, name = card_work.export(store_of(request), plan_id, side)
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": content_disposition(name, ".lbrn2"), "Cache-Control": "no-store"})
