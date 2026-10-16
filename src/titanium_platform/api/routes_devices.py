"""Laser devices: passport, source documents, generated charts and operating-point figures (REQ-017)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from pydantic import BaseModel

from .. import capability_results, devices, experiment_library, lenses, profiles as pf
from .common import content_disposition, read_upload, store_of

router = APIRouter(prefix="/api")
MAX_DOCUMENT_UPLOAD = devices.MAX_DOCUMENT_BYTES


class DeviceIn(BaseModel):
    name: str
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    description: str | None = None
    passport: dict[str, Any]


class DevicePatch(BaseModel):
    name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    description: str | None = None
    passport: dict[str, Any] | None = None


class FromTemplateIn(BaseModel):
    template: str
    name: str | None = None
    serial: str | None = None


class OperatingPointIn(BaseModel):
    profile_id: int
    power: float
    frequency: float
    speed: float
    pulse_width: float = 200.0
    line_interval: float = 0.025
    passes: int = 1


class ResultLookupIn(BaseModel):
    lens_id: int | None = None
    power: float
    frequency: float
    speed: float
    pulse_width: float
    line_interval: float
    passes: int


@router.get("/device-templates")
def list_templates():
    return devices.list_templates()


@router.get("/devices")
def list_devices(request: Request):
    return devices.list_devices(store_of(request))


@router.post("/devices", status_code=201)
def create_device(body: DeviceIn, request: Request):
    return devices.create_device(store_of(request), body.name, body.passport, body.manufacturer, body.model, body.serial, body.description)


@router.post("/devices/from-template", status_code=201)
def create_from_template(body: FromTemplateIn, request: Request):
    return devices.create_from_template(store_of(request), body.template, body.name, body.serial)


@router.get("/devices/{device_id}")
def get_device(device_id: int, request: Request):
    return devices.get_device(store_of(request), device_id)


@router.patch("/devices/{device_id}")
def update_device(device_id: int, body: DevicePatch, request: Request):
    given = body.model_dump(exclude_unset=True)
    return devices.update_device(store_of(request), device_id, **given)


@router.delete("/devices/{device_id}", status_code=204)
def delete_device(device_id: int, request: Request):
    devices.delete_device(store_of(request), device_id)


@router.get("/devices/{device_id}/charts")
def device_charts(device_id: int, request: Request):
    s = store_of(request)
    return devices.charts(devices.get_passport(s, device_id), lenses.installed(s, device_id))


@router.get("/devices/{device_id}/capability-results")
def device_capability_results(device_id: int, request: Request):
    s = store_of(request)
    devices.get_device(s, device_id)  # validate the selected physical laser
    return capability_results.for_device(s, device_id)


@router.get("/devices/{device_id}/findings")
def device_findings(device_id: int, request: Request, purpose: str | None = None):
    s = store_of(request)
    devices.get_device(s, device_id)
    return capability_results.findings_for_device(s, device_id, purpose)


@router.get("/devices/{device_id}/experiments")
def device_experiments(device_id: int, request: Request):
    return experiment_library.for_device(store_of(request), device_id)


@router.post("/devices/{device_id}/result-lookup")
def lookup_result(device_id: int, body: ResultLookupIn, request: Request):
    values = body.model_dump()
    lens_id = values.pop("lens_id")
    return experiment_library.lookup_result(store_of(request), device_id, lens_id, values)


@router.post("/devices/{device_id}/documents", status_code=201)
async def add_document(device_id: int, request: Request, kind: str = Form(...), title: str = Form(""), file: UploadFile = File(None)):
    name, data = await read_upload(file, MAX_DOCUMENT_UPLOAD, "document")
    return devices.add_document(store_of(request), device_id, kind, title, name, data)


@router.get("/devices/{device_id}/documents/{document_id}")
def get_document(device_id: int, document_id: int, request: Request):
    from pathlib import Path
    doc = devices.get_document(store_of(request), device_id, document_id)
    path = Path(doc["path"])
    if not path.is_file():
        raise KeyError("the stored document file is missing")
    extension = path.suffix
    disposition = content_disposition(Path(doc["filename"]).stem, extension).replace("attachment;", "inline;", 1)
    return Response(path.read_bytes(), media_type=doc["media_type"], headers={"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff"})


@router.delete("/devices/{device_id}/documents/{document_id}", status_code=204)
def delete_document(device_id: int, document_id: int, request: Request):
    devices.delete_document(store_of(request), device_id, document_id)


@router.post("/operating-point")
def operating_point(body: OperatingPointIn, request: Request):
    """Passport-model figures for a parameter set of a profile that is linked to a laser device."""
    s = store_of(request)
    profile = pf.get_profile(s, body.profile_id)
    if profile["device"] is None:
        raise pf.ValidationError("link a laser device to this profile to calculate pulse energy")
    return devices.operating_point(profile["device"]["passport"], body.power, body.frequency, body.speed,
                                   body.pulse_width, body.line_interval, body.passes, profile["device"].get("lens"))
