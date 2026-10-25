"""Analysis runs and their findings (REQ-022): run now, the periodic schedule, filtered, sorted and paged findings with their history
and the operator's marks (feature findings-you-can-manage-short-lists-re-check), and a proposal of the Experiment Designer for a gap."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import designer, exclusions, findings
from .common import store_of

router = APIRouter(prefix="/api/analysis")
exclusions_router = APIRouter(prefix="/api/exclusions")


class ScheduleIn(BaseModel):
    interval_hours: float


class MarkIn(BaseModel):
    action: str
    note: str | None = None


class RemedyIn(BaseModel):
    action: str
    note: str | None = None
    confirm: bool = False


class FindingProposalIn(BaseModel):
    seed: int = 1729
    size: int = designer.DEFAULT_SIZE


@router.get("/runs")
def runs(request: Request, limit: int = 50):
    return findings.list_runs(store_of(request), limit)


@router.post("/runs", status_code=201)
def run_now(request: Request):
    """Analyse everything accepted so far now ("Пересчитать выводы"); waits for a run already in progress."""
    return findings.run_analysis(store_of(request), "manual")


@router.get("/runs/{run_id}")
def run_findings(run_id: str, request: Request, kind: str | None = None, task: str | None = None, setup: str | None = None,
                 material: str | None = None, state: str | None = None, sort: str | None = None, offset: int = 0, limit: int | None = None):
    """The findings of one run (``latest`` for the newest), filtered by the operator's state, kind, task, laser + lens and titanium
    stock, sorted, and one page of them when ``limit`` is given; with the counts each filter would show."""
    s = store_of(request)
    run = findings.get_run(s, None if run_id == "latest" else _run_id(run_id))
    if run is None:
        return {"run": None, "findings": [], "matched": 0, "total": 0, "counts": {"state": {}, "kind": {}},
                "options": {"kinds": [], "tasks": [], "setups": [], "stocks": []}}
    return findings.findings_of(s, run["id"], kind=kind or None, task=task or None, setup=setup or None, material=material or None,
                                state=state or None, sort=sort or None, offset=offset, limit=limit)


def _run_id(text: str) -> int:
    if not text.isdigit():
        raise KeyError(f"analysis run {text} not found")
    return int(text)


@router.get("/findings/{finding_id}")
def get_finding(finding_id: int, request: Request):
    return findings.get_finding(store_of(request), finding_id)


@router.post("/findings/{finding_id}/mark")
def mark_finding(finding_id: int, body: MarkIn, request: Request):
    """«Учтено», «Скрыть», «Вернуть», «Закрепить», «Открепить» or a note; kept by the finding's key across runs (DEC-001)."""
    return findings.mark(store_of(request), finding_id, body.action, body.note)


@router.post("/findings/{finding_id}/remedy")
def remedy(finding_id: int, body: RemedyIn, request: Request):
    """«Убрать измерение» or «Считать с последней гравировки» (feature act-on-findings): without ``confirm`` what it would change, with
    it the decision, after which the knowledge, the findings and the works are recalculated once; refused while every work is being
    re-checked."""
    return findings.remedy(store_of(request), finding_id, body.action, body.note, body.confirm)


@router.get("/findings/{finding_id}/history")
def finding_history(finding_id: int, request: Request):
    return findings.history(store_of(request), finding_id)


@router.post("/findings/{finding_id}/proposal", status_code=201)
def propose_for_finding(finding_id: int, body: FindingProposalIn, request: Request):
    return findings.propose_for(store_of(request), finding_id, seed=body.seed, size=body.size)


@router.get("/schedule")
def get_schedule(request: Request):
    return _schedule(request)


@router.put("/schedule")
def put_schedule(body: ScheduleIn, request: Request):
    findings.set_interval(store_of(request), body.interval_hours)
    scheduler = getattr(request.app.state, "analysis_scheduler", None)
    if scheduler is not None:
        scheduler.start_if_enabled()          # the thread starts the moment an interval is set; with 0 it stays idle
    return _schedule(request)


def _schedule(request: Request) -> dict:
    scheduler = getattr(request.app.state, "analysis_scheduler", None)
    return findings.schedule(store_of(request)) | {"running": bool(scheduler and scheduler.running)}


@exclusions_router.get("")
def list_exclusions(request: Request, include_revoked: bool = False):
    """The operator's exclusions, newest first, with the number in force (act-on-findings REQ-005)."""
    return exclusions.listing(store_of(request), include_revoked)


@exclusions_router.post("/{exclusion_id}/revoke")
def revoke_exclusion(exclusion_id: int, request: Request):
    """«Вернуть»: the measurements of the decision count again, recalculated once."""
    return exclusions.revoke(store_of(request), exclusion_id)
