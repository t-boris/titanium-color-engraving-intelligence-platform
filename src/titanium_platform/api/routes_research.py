"""Local research sessions and the AI assistant."""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from .. import research
from .common import store_of

router = APIRouter(prefix="/api/research")


class SessionIn(BaseModel):
    device_id: int
    material_id: int
    goal: str
    target: str


class MessageIn(BaseModel):
    message: str


class TestIn(BaseModel):
    test_type: str
    settings: dict = {}


class ReplaceTestIn(TestIn):
    plan_id: int


class CancelTestIn(BaseModel):
    plan_id: int
    reason: str


class InsightIn(BaseModel):
    purpose: str
    claim: str
    confidence: str
    evidence_pair_ids: list[int]


@router.get("/sessions")
def sessions(request: Request):
    return research.list_sessions(store_of(request))


@router.post("/sessions", status_code=201)
def create_session(body: SessionIn, request: Request):
    return research.create_session(store_of(request), body.device_id, body.material_id, body.goal, body.target)


@router.get("/sessions/{session_id}")
def get_session(session_id: int, request: Request):
    return research.get_session(store_of(request), session_id)


@router.get("/sessions/{session_id}/messages")
def list_messages(session_id: int, request: Request, before: int | None = None, limit: int = 40):
    return research.list_messages(store_of(request), session_id, before=before, limit=limit)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: int, request: Request):
    research.delete_session(store_of(request), session_id)
    return Response(status_code=204)


@router.get("/sessions/{session_id}/context")
def context(session_id: int, request: Request):
    return research.context(store_of(request), session_id)


@router.get("/sessions/{session_id}/next-test")
def next_test(session_id: int, request: Request):
    return research.next_test(store_of(request), session_id)


@router.post("/sessions/{session_id}/preview-test")
def preview_test(session_id: int, body: TestIn, request: Request):
    return research.preview_plate(store_of(request), session_id, body.test_type, body.settings)


@router.post("/sessions/{session_id}/tests", status_code=201)
def create_test(session_id: int, body: TestIn, request: Request):
    return research.create_plate(store_of(request), session_id, body.test_type, body.settings)


@router.post("/sessions/{session_id}/replace-test", status_code=201)
def replace_test(session_id: int, body: ReplaceTestIn, request: Request):
    return research.create_plate(store_of(request), session_id, body.test_type, body.settings,
                                 replace_plan_id=body.plan_id)


@router.post("/sessions/{session_id}/cancel-test")
def cancel_test(session_id: int, body: CancelTestIn, request: Request):
    return research.cancel_pending_plate(store_of(request), session_id, body.plan_id, body.reason)


@router.get("/sessions/{session_id}/pairs/{pair_id}")
def inspect_pair(session_id: int, pair_id: int, request: Request):
    return research.inspect_pair(store_of(request), session_id, pair_id)


@router.post("/sessions/{session_id}/pairs/{pair_id}/map")
def map_pair(session_id: int, pair_id: int, request: Request):
    return research.run_photo_mapping(store_of(request), session_id, pair_id)


@router.post("/sessions/{session_id}/insights", status_code=201)
def save_insight(session_id: int, body: InsightIn, request: Request):
    return research.save_insight(store_of(request), session_id, body.purpose, body.claim,
                                 body.confidence, body.evidence_pair_ids)


@router.post("/sessions/{session_id}/messages")
def chat(session_id: int, body: MessageIn, request: Request):
    return research.answer(store_of(request), session_id, body.message)
