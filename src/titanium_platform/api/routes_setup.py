"""Profiles, materials, capture setups, rules and the marker layer (REQ-010, REQ-009, REQ-005)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import plans, profiles as pf
from .common import store_of

router = APIRouter(prefix="/api")


class ProfileIn(BaseModel):
    name: str
    device_id: int | None = None
    lens_id: int | None = None


class ProfilePatch(BaseModel):
    name: str | None = None
    device_id: int | None = None
    lens_id: int | None = None


class MaterialIn(BaseModel):
    name: str
    family: str | None = None
    batch: str | None = None
    grade: str | None = None
    thickness_mm: float | None = None
    surface: str | None = None


class SetupIn(BaseModel):
    name: str
    camera: str
    lighting: str
    angle: str
    reference_chart: str


class RulesIn(BaseModel):
    repeat_threshold: int | None = None
    delta_tolerance: float | None = None
    variance_threshold: float | None = None
    criteria_agreed: bool | None = None


class MarkerLayerIn(BaseModel):
    power: float
    frequency: float
    speed: float


@router.get("/profiles")
def list_profiles(request: Request):
    return pf.list_profiles(store_of(request))


@router.post("/profiles", status_code=201)
def create_profile(body: ProfileIn, request: Request):
    return pf.create_profile(store_of(request), body.name, device_id=body.device_id, lens_id=body.lens_id)


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: int, request: Request):
    return pf.get_profile(store_of(request), profile_id)


@router.patch("/profiles/{profile_id}")
def update_profile(profile_id: int, body: ProfilePatch, request: Request):
    given = body.model_dump(exclude_unset=True)   # device_id: null removes the link, an absent field leaves it
    return pf.update_profile(store_of(request), profile_id, **given)


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: int, request: Request):
    pf.delete_profile(store_of(request), profile_id)


@router.get("/profiles/{profile_id}/rules")
def get_rules(profile_id: int, request: Request):
    pf.get_profile(store_of(request), profile_id)
    return pf.get_rules(store_of(request), profile_id)


@router.put("/profiles/{profile_id}/rules")
def save_rules(profile_id: int, body: RulesIn, request: Request):
    from .. import knowledge
    s = store_of(request)
    rules = pf.save_rules(s, profile_id, **body.model_dump())
    knowledge.refresh(s, profile_id)  # new thresholds can promote (or flag) existing knowledge
    return rules


@router.get("/materials")
def list_materials(request: Request):
    return pf.list_materials(store_of(request))


@router.post("/materials", status_code=201)
def create_material(body: MaterialIn, request: Request):
    return pf.save_material(store_of(request), **body.model_dump())


@router.put("/materials/{material_id}")
def update_material(material_id: int, body: MaterialIn, request: Request):
    return pf.save_material(store_of(request), **body.model_dump(), material_id=material_id)


@router.get("/setups")
def list_setups(request: Request):
    return pf.list_capture_setups(store_of(request))


@router.post("/setups", status_code=201)
def create_setup(body: SetupIn, request: Request):
    return pf.save_capture_setup(store_of(request), **body.model_dump())


@router.put("/setups/{setup_id}")
def update_setup(setup_id: int, body: SetupIn, request: Request):
    return pf.save_capture_setup(store_of(request), **body.model_dump(), setup_id=setup_id)


@router.delete("/setups/{setup_id}", status_code=204)
def delete_setup(setup_id: int, request: Request):
    pf.delete_capture_setup(store_of(request), setup_id)


@router.get("/marker-layer")
def get_marker_layer(request: Request):
    return plans.marker_layer_settings(store_of(request))


@router.put("/marker-layer")
def put_marker_layer(body: MarkerLayerIn, request: Request):
    return plans.save_marker_layer_settings(store_of(request), body.power, body.frequency, body.speed)
