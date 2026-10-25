"""«Перепроверить все работы» (feature findings-you-can-manage-short-lists-re-check, REQ-004, DEC-089): what a re-check would do, starting
it, following it, stopping it, and its report (the last one too, after a restart)."""
from __future__ import annotations

from fastapi import APIRouter, Request

from .. import backup, recheck
from .common import refresh_after_change, store_of

router = APIRouter(prefix="/api/recheck")


@router.get("/preview")
def preview(request: Request):
    """How many photographs, about how long, where the backup goes, its size and the free space there."""
    store = store_of(request)
    return recheck.preview(store, backup.default_target(store))


@router.post("", status_code=202)
def start(request: Request):
    """Back the workshop up, then measure every accepted photograph again in the background; the re-check to follow."""
    store = store_of(request)
    return recheck.start(store, backup.default_target(store), on_accepted=refresh_after_change)


@router.get("/latest")
def latest(request: Request):
    return recheck.latest(store_of(request))


@router.get("/{recheck_id}")
def get(recheck_id: int, request: Request):
    return recheck.get(store_of(request), recheck_id)


@router.post("/{recheck_id}/stop")
def stop(recheck_id: int, request: Request):
    """Stop after the photograph being measured; the conclusions are drawn from what was measured."""
    return recheck.stop(store_of(request), recheck_id)
