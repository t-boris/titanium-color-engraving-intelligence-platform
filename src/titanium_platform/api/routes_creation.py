"""Starting new work (feature ux-work-creation-p0): the context a new task starts from (``/api/creation/context``), what a result needs
(``readiness``, the starter test), the unfinished tasks that setup or a starter test interrupted (``drafts``, kept on disk so they outlive
the application) and the pictures that compare the results of one picture (``drafts/{id}/preview/{result}.png``). Nothing here makes a
work: the works are made by their own routes (``/api/vector``, ``/api/photo-works`` ...), and a draft is closed once the work exists."""
from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from pydantic import BaseModel

from .. import creation_context as cc, creation_drafts as cd, creation_previews as cp, setup as su
from .common import MAX_IMAGE_BYTES, lens_param, read_upload, store_of

router = APIRouter(prefix="/api/creation")


class ContextIn(BaseModel):
    """The explicit changes of the shared context; a field that is not sent stays as it is. ``lens_id`` is a record id, ``unknown`` (or null) for
    the unknown lens, and absent for "the lens standing on the laser"."""
    device_id: int | None = None
    lens_id: int | str | None = None
    material_id: int | None = None
    capture_setup_id: int | None = None
    source: dict | None = None


class StarterIn(BaseModel):
    result: str


class CompleteIn(BaseModel):
    work_kind: str
    work_id: int


def _changes(body: ContextIn) -> dict:
    sent = body.model_fields_set
    changes = {k: getattr(body, k) for k in ("device_id", "material_id", "capture_setup_id", "source") if k in sent}
    if "lens_id" in sent:
        changes["lens_id"] = None if body.lens_id is None else lens_param(str(body.lens_id))
    return changes


@router.get("/context")
def get_context(request: Request):
    """The context new work starts from, with the records it names (see creation_context.get)."""
    return cc.get(store_of(request))


@router.put("/context")
def put_context(body: ContextIn, request: Request):
    """Keep an explicit change of the context. It changes no work that was already made."""
    return cc.save(store_of(request), _changes(body))


@router.post("/context/impact")
def context_impact(body: ContextIn, request: Request):
    """What starting from another setup does to what can be started, before the person confirms it. Nothing is changed."""
    return cc.impact(store_of(request), _changes(body))


@router.get("/readiness")
def readiness(request: Request, result: str):
    """Whether a result (photo, colour, silhouette, lines) can be started with the context, what is missing and the starter test."""
    return cc.readiness(store_of(request), result)


@router.post("/starter-plate", status_code=201)
def starter_plate(body: StarterIn, request: Request):
    """The starter test of a vector result, made as the experiment guide proposes it for the context's laser and titanium."""
    s = store_of(request)
    return cc.make_starter_plate(s, cc.get(s), body.result)


# -- the unfinished tasks --------------------------------------------------------------------------------------------------------
def _state(text: str | None) -> dict | None:
    if text in (None, ""):
        return None
    try:
        state = json.loads(text)
    except ValueError:
        raise su.ValidationError("the unfinished task must be an object") from None
    return state


async def _picture(upload: UploadFile | None) -> tuple[str, bytes] | None:
    if upload is None or not upload.filename:
        return None
    return await read_upload(upload, MAX_IMAGE_BYTES, "picture")


@router.get("/drafts")
def list_drafts(request: Request):
    """The tasks that were left unfinished, the newest first. A finished or discarded task is not listed."""
    return cd.listing(store_of(request))


@router.post("/drafts", status_code=201)
async def create_draft(request: Request, flow: str = Form(...), state: str = Form("{}"), name: str | None = Form(None),
                       picture: UploadFile = File(None)):
    """Keep a new task: where it started (``flow``), the form as it is (``state``, a JSON object) and its picture."""
    return cd.create(store_of(request), flow, _state(state) or {}, await _picture(picture), name)


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: int, request: Request):
    return cd.get(store_of(request), draft_id)


@router.put("/drafts/{draft_id}")
async def update_draft(draft_id: int, request: Request, state: str | None = Form(None), name: str | None = Form(None),
                       picture: UploadFile = File(None)):
    """Save the form of an unfinished task again: its state, its title, a new picture. What is not sent stays as it is."""
    return cd.update(store_of(request), draft_id, _state(state), await _picture(picture), name)


@router.get("/drafts/{draft_id}/picture")
def draft_picture(draft_id: int, request: Request):
    """The picture the task was started with, as it was added."""
    data, media_type, _ = cd.picture(store_of(request), draft_id)
    return Response(data, media_type=media_type, headers={"Cache-Control": "private, max-age=0, must-revalidate"})


@router.get("/drafts/{draft_id}/preview/{result}.png")
def draft_preview(draft_id: int, result: str, request: Request, width_mm: float):
    """The picture of the task as one result would make it, at the width asked for (see creation_previews). Known by a key of what it is
    drawn from, so the browser asks again and gets 304 while nothing changed."""
    data, _, _ = cd.picture(store_of(request), draft_id)
    tile_key, png, facts = cp.tile(data, width_mm, result)
    etag = f'"{tile_key}"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=0, must-revalidate", "X-Preview-Facts": json.dumps(facts)}
    if any(tag.strip().removeprefix("W/") in (etag, "*") for tag in request.headers.get("if-none-match", "").split(",")):
        return Response(status_code=304, headers=headers)
    return Response(png, media_type="image/png", headers=headers)


@router.post("/drafts/{draft_id}/complete")
def complete_draft(draft_id: int, body: CompleteIn, request: Request):
    """The work of the task has been made: the task is closed and never offered again."""
    return cd.complete(store_of(request), draft_id, body.work_kind, body.work_id)


@router.post("/drafts/{draft_id}/discard")
def discard_draft(draft_id: int, request: Request):
    """The person gave the task up: it is closed, its picture removed, and it is never offered again."""
    return cd.discard(store_of(request), draft_id)
