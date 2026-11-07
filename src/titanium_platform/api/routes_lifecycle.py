"""The life of a work's file, read model (feature ux-engraving-lifecycle-p0): where the work stands (prepared, file received, result added,
checked), whether its file can be made now, the files it handed out, and what an accepted result did to its prediction. Nothing is
changed here; the file itself is made by the existing export routes."""
from __future__ import annotations

from fastapi import APIRouter, Request

from .. import experiments, lifecycle, plans, vector_job, work_errors
from .common import store_of

router = APIRouter(prefix="/api")


def of_plan(store, plan_id: int) -> dict:
    """The lifecycle of any plan: a vector work from its assessment (one :func:`vector_job.view`), another plan from its stored layers."""
    plan = plans.get_plan(store, plan_id)
    if plan["status"] == "Deleted" or plan["mode"] in (plans.MODE_PHOTO_WORK, plans.MODE_CARD_WORK):      # these works export through their own routes
        raise KeyError(f"plan {plan_id} not found")
    if plan["mode"] == plans.MODE_VECTOR:
        return lifecycle.of_vector(store, plan_id, vector_job.view(store, plan_id))
    return lifecycle.of_plain(store, plan_id, experiments.plan_time(plan))


@router.get("/plans/{plan_id}/lifecycle")
def plan_lifecycle(plan_id: int, request: Request):
    """The chain, the readiness and the files of one plan (a vector work, a plate or another plan)."""
    return of_plan(store_of(request), plan_id)


@router.get("/pairs/{pair_id}/work-summary")
def pair_work_summary(pair_id: int, request: Request):
    """What accepting this photograph of an engraving did to the work it belongs to: the file it was compared with and on what basis, how it
    came out, how the work's current prediction moved. 404 when the photograph is not an accepted one of a vector work made from a photograph."""
    found = work_errors.summary_of_pair(store_of(request), pair_id)
    if found is None:
        raise KeyError(f"pair {pair_id} not found")
    return found
