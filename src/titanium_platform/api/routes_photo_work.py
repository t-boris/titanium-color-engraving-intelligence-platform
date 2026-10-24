"""Photo engraving works (REQ-061, DEC-104): list, create, open, change, copy, rename, their pictures and their LightBurn file, a ramp
plate at a work's width (DEC-107); the parts of a work's picture and the AI that proposes their rules (REQ-062, DEC-105); the kinds of
engraving a work can take, each with the work's picture as it would come out, and the dots of a dot kind close up; the objects of a
work's picture and their colours, by hand or from a theme (0.21.0). The colour of a dot kind's dots is picked on the colour map
(``GET /api/colors?dots={id}``, 0.25.0). The inscriptions of a work and the titanium colours they are engraved in (feature
inscriptions-in-works). A work is deleted as every plan is (``DELETE /api/plans/{id}``)."""
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
                            source: str | None = Form(None), picture: UploadFile = File(None)):
    """A new work of an uploaded picture (PNG, JPEG ...) ``width_mm`` wide; ``scale`` (JSON, as the list of scales gives a scale's mode)
    is optional: without it the best measured scale is taken. ``source`` (JSON: a connected laboratory release, its laser and lens, and
    the own laser and lens the work is engraved with, feature electron) takes the scales from that release. The work is returned as it
    opens."""
    file_name, data = await read_upload(picture, MAX_IMAGE_BYTES, "picture")
    try:
        wanted = None if scale in (None, "") else json.loads(scale)
    except ValueError:
        raise su.ValidationError("this scale is not measured: choose one of the measured scales") from None
    try:
        chosen = None if source in (None, "") else json.loads(source)
    except ValueError:
        raise su.ValidationError("choose a laboratory release, its laser, lens and titanium") from None
    s = store_of(request)
    return photo_work.view(s, photo_work.create(s, data, file_name, name, width_mm, wanted, chosen))


@router.get("/photo-works/{plan_id}")
def get_photo_work(plan_id: int, request: Request):
    return photo_work.view(store_of(request), plan_id)


@router.post("/photo-works/{plan_id}/settings")
def change_photo_work(plan_id: int, body: dict, request: Request):
    """Change the scale, Min and Max power, the width, the colour choice, the rules of the parts, the kind of engraving, its dots' power or
    their colour picked on the colour map (``dot_colour``), or the permission to send the picture to the AI (see photo_work.update); the
    work is returned as it is now."""
    s = store_of(request)
    photo_work.update(s, plan_id, body)
    return photo_work.view(s, plan_id)


@router.post("/photo-works/{plan_id}/texts")
def change_photo_work_texts(plan_id: int, body: dict, request: Request):
    """Add, change, copy or take away an inscription (``op``: text_add, text_set, text_copy, text_delete, see photo_work.text); the work is
    returned as it is now."""
    s = store_of(request)
    photo_work.text(s, plan_id, body)
    return photo_work.view(s, plan_id)


@router.get("/photo-works/{plan_id}/palette")
def photo_work_palette(plan_id: int, request: Request):
    """The titanium colours an inscription of the work is engraved in: every measured colour of its laser, lens and titanium."""
    return photo_work.palette_of(store_of(request), plan_id)


@router.post("/photo-works/{plan_id}/copy", status_code=201)
def copy_photo_work(plan_id: int, request: Request, body: dict | None = None):
    return {"id": photo_work.copy_work(store_of(request), plan_id, (body or {}).get("name"))}


@router.post("/photo-works/{plan_id}/source")
def photo_work_source(plan_id: int, request: Request, body: dict | None = None):
    """Preview, or with ``confirm`` make, an update of the laboratory release a work is pinned to (``release_id``, ``laser``, ``lens``;
    by default its laboratory's current release), or go back to its earlier source (``back``): see photo_work.source_change."""
    body = dict(body or {})
    s = store_of(request)
    preview = photo_work.source_change(s, plan_id, body, confirm=bool(body.pop("confirm", False)))
    return {**preview, "work": photo_work.view(s, plan_id)}


@router.post("/photo-works/{plan_id}/rename")
def rename_photo_work(plan_id: int, request: Request, body: dict | None = None):
    return {"id": plan_id, "name": photo_work.rename_work(store_of(request), plan_id, (body or {}).get("name"))}


@router.post("/photo-works/{plan_id}/width-ramp", status_code=201)
def photo_work_width_ramp(plan_id: int, request: Request):
    """A grey-ramp plate of one ramp as wide as the work at its scale's settings, to measure the scale at the work's size (DEC-107); the
    plate is returned as the plate dialog creates one (``plan_id``, ``name``, ``summary`` ...)."""
    return photo_work.width_ramp(store_of(request), plan_id)


@router.get("/photo-works/{plan_id}/preview.png")
def photo_work_preview(plan_id: int, request: Request):
    """The picture beside its predicted look on the titanium."""
    return picture_response(request, photo_work.preview(store_of(request), plan_id))


@router.get("/photo-works/{plan_id}/thumb.png")
def photo_work_thumbnail(plan_id: int, request: Request):
    """The work in the list: its predicted look on the titanium."""
    return picture_response(request, photo_work.thumbnail(store_of(request), plan_id))


@router.get("/photo-works/{plan_id}/closeup.png")
def photo_work_closeup(plan_id: int, request: Request):
    """The dots of a work in a dot kind dot for dot, from the middle of the picture."""
    return picture_response(request, photo_work.closeup(store_of(request), plan_id))


@router.get("/photo-works/{plan_id}/kinds")
def photo_work_kinds(plan_id: int, request: Request):
    """Every kind of engraving that colours titanium, each with the address of the work's picture as it would come out in it."""
    return photo_work.kinds(store_of(request), plan_id)


@router.get("/photo-works/{plan_id}/kinds/{kind}.png")
def photo_work_kind_picture(plan_id: int, kind: str, request: Request):
    """The work's picture as it would come out in ``kind``."""
    return picture_response(request, photo_work.kind_picture(store_of(request), plan_id, kind))


@router.get("/photo-works/{plan_id}/picture")
def photo_work_picture(plan_id: int, request: Request):
    """The picture as it was uploaded."""
    data, media_type = photo_work.original(store_of(request), plan_id)
    return Response(data, media_type=media_type, headers={"Cache-Control": "private, max-age=0, must-revalidate"})


@router.get("/photo-works/{plan_id}/export.lbrn2")
def photo_work_file(plan_id: int, request: Request):
    """The LightBurn file of the work: the cleaning, then one Image layer in its kind at its scale's settings (Min and Max, or the dots' power), the
    picture at its width, then the letters of its inscriptions on a layer of each titanium colour."""
    data, name = photo_work.export(store_of(request), plan_id)
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": content_disposition(name, ".lbrn2"), "Cache-Control": "no-store"})


@router.get("/photo-works/{plan_id}/engravings")
def photo_work_engravings(plan_id: int, request: Request):
    """Every photograph of the work's engravings, with each grey engraved against the colour predicted for it once accepted."""
    return photo_work.engravings(store_of(request), plan_id)


@router.get("/photo-works/{plan_id}/parts")
def photo_work_parts(plan_id: int, request: Request):
    """The parts the people model finds in the picture: share and mean colour of each, and the address of the picture tinted by part."""
    return photo_work.parts(store_of(request), plan_id)


@router.get("/photo-works/{plan_id}/parts.png")
def photo_work_parts_picture(plan_id: int, request: Request):
    """The picture with every part tinted in its colour."""
    return picture_response(request, photo_work.parts_picture(store_of(request), plan_id))


@router.get("/photo-works/{plan_id}/objects")
def photo_work_objects(plan_id: int, request: Request):
    """The objects of the picture to colour, the scale's colours to colour them with and the themes (see photo_work.objects_of)."""
    return photo_work.objects_of(store_of(request), plan_id)


@router.get("/photo-works/{plan_id}/objects.png")
def photo_work_objects_picture(plan_id: int, request: Request):
    """The picture with every object tinted in its colour."""
    return picture_response(request, photo_work.objects_picture(store_of(request), plan_id))


@router.post("/photo-works/{plan_id}/theme")
def colour_photo_work_by_theme(plan_id: int, request: Request, body: dict | None = None):
    """Colour every object by a theme (``name``: warm, cool, contrast or random with ``seed``); the work is returned as it is then."""
    s = store_of(request)
    photo_work.colour_theme(s, plan_id, (body or {}).get("name"), (body or {}).get("seed", 0))
    return photo_work.view(s, plan_id)


@router.post("/photo-works/{plan_id}/ai-theme")
def colour_photo_work_by_ai(plan_id: int, request: Request, body: dict | None = None):
    """Colour every object as the AI chooses after the operator's ``wish``; the work is returned as it is then."""
    s = store_of(request)
    photo_work.ai_theme(s, plan_id, (body or {}).get("wish"))
    return photo_work.view(s, plan_id)


@router.post("/photo-works/{plan_id}/ai")
def ask_photo_work_ai(plan_id: int, request: Request, body: dict | None = None):
    """Ask the AI for the rules of the parts after the operator's ``wish``; the work is returned with them (see photo_work.ask_ai)."""
    s = store_of(request)
    photo_work.ask_ai(s, plan_id, (body or {}).get("wish"), (body or {}).get("fresh", False))
    return photo_work.view(s, plan_id)


@router.post("/photo-works/{plan_id}/undo")
def undo_photo_work(plan_id: int, request: Request):
    """Undo the last change of what the work engraves; the work is returned as it is then."""
    s = store_of(request)
    photo_work.step(s, plan_id, "undo")
    return photo_work.view(s, plan_id)


@router.post("/photo-works/{plan_id}/redo")
def redo_photo_work(plan_id: int, request: Request):
    """Redo the last undone change of the work; the work is returned as it is then."""
    s = store_of(request)
    photo_work.step(s, plan_id, "redo")
    return photo_work.view(s, plan_id)
