"""A hand-built ``lifecycle`` answer for the UI tests that build a work's or a plan's JSON by hand (the real server always sends one, so the
screens do not guard against its absence). The values are those of a work that is ready and was never exported, unless a test changes them."""
from __future__ import annotations

STAGES = ("prepared", "file", "result", "verified")


def readiness(**over) -> dict:
    base = {"kind": "photo", "ready": True, "size_mm": {"width": 150.0, "height": 143.0}, "seconds": 400.0, "time_complete": True, "layers": 3,
            "layer_cap": 29, "blockers": [], "reason": None, "local_only": True,
            "checks": {"colours": True, "layers": {"used": 3, "cap": 29, "ok": True}, "cleanup": True, "markers": False}}
    return {**base, **over}


def file_record(number: int = 1, *, results=(), stage: str = "file", current: bool = True, **over) -> dict:
    base = {"number": number, "name": f"work-{number}.lbrn2", "at": "2026-10-20T10:00:00", "document_version": 3, "layers": 3, "regions": 5, "seconds": 400.0,
            "variant": 1, "recorded": number != 0, "downloadable": True, "download_url": f"/api/vector/7/exports/{number}", "promise": "saved",
            "current": current, "results": list(results), "stage": stage}
    return {**base, **over}


def lifecycle(stage: str = "prepared", *, files=(), unlinked=(), edited_after=None, next_action=None, plan_id: int = 7, **ready) -> dict:
    """The answer for a work at ``stage`` (the steps before it are done, the later ones not yet)."""
    here = STAGES.index(stage)
    steps = [{"id": s, "state": "done" if i < here else "current" if i == here else "todo"} for i, s in enumerate(STAGES)]
    rd = readiness(**ready)
    action = next_action or {"prepared": {"code": "download" if rd["ready"] else "fix"}, "file": {"code": "add_result"}, "result": {"code": "check_result", "pair_id": 4},
                             "verified": {"code": "compare", "pair_id": 3, "engraving_id": "abc"}}[stage]
    return {"plan_id": plan_id, "status": "Ready to export", "readiness": rd, "files": list(files), "unlinked": list(unlinked),
            "chain": {"stage": stage, "steps": steps, "next": action, "file": files[-1]["number"] if files else None, "edited_after": edited_after,
                      "unlinked": len(unlinked)}}
