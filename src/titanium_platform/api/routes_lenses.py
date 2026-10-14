"""Lenses and the lens installed on a laser (REQ-019, DEC-041)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import lenses
from .common import store_of

router = APIRouter(prefix="/api")


class LensIn(BaseModel):
    name: str
    focal_length_mm: float
    field_mm: float | None = None
    expansion: float = 1.0
    note: str | None = None


class LensPatch(BaseModel):
    name: str | None = None
    focal_length_mm: float | None = None
    field_mm: float | None = None
    expansion: float | None = None
    note: str | None = None


class InstallIn(BaseModel):
    lens_id: int | None = None


@router.get("/lenses")
def list_lenses(request: Request):
    return lenses.list_lenses(store_of(request))


@router.post("/lenses", status_code=201)
def create_lens(body: LensIn, request: Request):
    return lenses.create_lens(store_of(request), body.name, body.focal_length_mm, body.field_mm, body.expansion, body.note)


@router.get("/lenses/{lens_id}")
def get_lens(lens_id: int, request: Request):
    return lenses.get_lens(store_of(request), lens_id)


@router.patch("/lenses/{lens_id}")
def update_lens(lens_id: int, body: LensPatch, request: Request):
    return lenses.update_lens(store_of(request), lens_id, **body.model_dump(exclude_unset=True))


@router.delete("/lenses/{lens_id}", status_code=204)
def delete_lens(lens_id: int, request: Request):
    lenses.delete_lens(store_of(request), lens_id)


@router.put("/devices/{device_id}/lens")
def install_lens(device_id: int, body: InstallIn, request: Request):
    """Install a lens on the laser, or take it off with ``{"lens_id": null}``."""
    from .. import devices
    s = store_of(request)
    lenses.install(s, device_id, body.lens_id)
    return devices.get_device(s, device_id)
