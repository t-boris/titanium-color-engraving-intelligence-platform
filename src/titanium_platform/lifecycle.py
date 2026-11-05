"""The life of the file of one work: prepared, file received, result added, checked (feature ux-engraving-lifecycle-p0, REQ-001..003).

The operator makes a LightBurn file, engraves it somewhere else, photographs the result and tells the platform. This module reads what
is already kept and says where one work stands, so that every screen of the work shows the same chain and the same readiness:

* ``readiness``: whether the file can be made now and, if not, why (structured blockers, no prose), with the size, the estimated time
  and the layer count a file would have. The file is only handed to the browser; nothing is ever sent to the laser (``local_only``);
* ``files``: every file the work handed out, from the records its exports keep (``plan["exports"]``, append-only), each with the stage
  of its own life and the results linked to it. A repeat export is a new file and starts again at "file received": a stage is never
  inherited from another file, and the work edited since its last file is "prepared" again;
* ``chain``: the stage of the work now (that of its newest file while the work is as that file left it) and the next action.

Nothing is stored here except the records of a plain plan's exports (:func:`record_plain_export`, additive keys of the plan, nothing is
migrated: a plan without them reads as before) and the small summary of a result's effect on the prediction that :mod:`work_errors`
keeps in a review. A promise (the colours a file showed in the preview) is kept by vector photograph works only; for every other
file :func:`basis_of` says that no promise was kept, and a reconstruction is never presented as the original promise.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import conversion as cv, engraving_time, plans as pl
from .db import Store, now

STAGES = ("prepared", "file", "result", "verified")
LEGACY = 0                                              # the number of the one file of a plan exported before exports were recorded
PENDING = ("Awaiting check", "Needs correction", "Ready to accept")
ACCEPTED = "Accepted"
CLOSED = ("Superseded", "Cancelled")


# -- the basis of a comparison ------------------------------------------------------------------------------------------------------------
def basis(kind: str, export: dict | None = None, ambiguous=()) -> dict:
    """What an engraving is compared with. ``saved``: the colours the exported file showed, kept with it. ``reconstructed``: the colours
    worked out from the work's layers as they are kept now, because no promise was kept (a file made before promises were kept, or a work
    never exported); ``lost``: nothing can be claimed (the work was recoloured or split again since a file that kept no promise).
    ``ambiguous`` lists the files whose layers fit the engraving equally well, the newest made before the photograph is the one chosen."""
    return {"kind": kind, "export_number": export["number"] if export else None, "exported_at": export["at"] if export else None,
            "document_version": export.get("document_version") if export else None, "ambiguous": sorted(ambiguous)}


def basis_of(plan: dict, review: dict) -> dict:
    """The basis of a review: as it was named when the review was made, or worked out from the fields every review carries (reviews made
    before the basis was named; their stored form is not changed)."""
    if review.get("basis"):
        return review["basis"]
    number = review.get("export_number")
    export = next((e for e in plan.get("exports") or [] if e["number"] == number), None)
    kind = "lost" if review.get("promise_lost") else "reconstructed" if review.get("approximate") else "saved"
    return basis(kind, export)


# -- pairs and files ----------------------------------------------------------------------------------------------------------------------
def pairs_of(store: Store, plan: dict) -> list[dict]:
    """The photographs of the work's engravings that are still in use (not deleted), oldest first."""
    rows = store.query("SELECT id, status, engraving_id, photo_name, created_at, accepted_at FROM pair "
                       "WHERE (plan_id=? OR (plate_id IS NOT NULL AND plate_id IS ?)) AND status!='Deleted' ORDER BY id", (plan["id"], plan.get("plate_id")))
    return [dict(r) for r in rows]


def _file_of(pair: dict, review: dict | None, exports: list[dict], legacy: bool) -> tuple[int | None, str]:
    """The file a photograph belongs to and how that is known: a review names the file it was compared with (``review``); else the newest
    file made at or before the photograph was added (``time``). None when no file existed then."""
    if review is not None and review.get("export_number") is not None and any(e["number"] == review["export_number"] for e in exports):
        return review["export_number"], "review"
    earlier = [e["number"] for e in exports if (e.get("at") or "") <= pair["created_at"]]
    if earlier:
        return max(earlier), "time"
    return (LEGACY, "time") if legacy else (None, "time")


def _unchanged(plan: dict, export: dict, latest: bool) -> bool:
    """The work is as this file left it: it is the newest file, the work was not edited since (an edit makes a work ready or draft again;
    only an export makes it "Exported") and its markers are as the file had them (known for files made since they were recorded)."""
    if not latest or plan.get("status") != "Exported":
        return False
    return export.get("markers") is None or export["markers"] == bool(plan.get("markers_enabled"))


def files_of(plan: dict, pairs: list[dict], download_url=None) -> tuple[list[dict], list[dict]]:
    """Every file the work handed out, oldest first, with the stage of its own life, and the photographs linked to no file.

    A plan exported before the exports were recorded (status "Exported", no record) has one unnumbered file (``recorded`` false) whose
    date is unknown; a file whose bytes are gone (``downloadable`` false) is still listed. ``download_url(number)`` gives the address of a
    stored file, or None when the plan keeps none."""
    exports = plan.get("exports") or []
    legacy = not exports and plan.get("status") == "Exported"
    reviews = {r["engraving_id"]: r for r in plan.get("reviews") or []}
    records = [dict(e) for e in exports] or ([{"number": LEGACY, "name": None, "at": None}] if legacy else [])
    files = []
    for position, e in enumerate(records):
        path = e.get("path")
        files.append({"number": e["number"], "name": e.get("name"), "at": e.get("at"), "document_version": e.get("document_version"),
                      "layers": e.get("layers"), "regions": e.get("regions"), "seconds": e.get("seconds"), "variant": e.get("variant"),
                      "recorded": e["number"] != LEGACY, "downloadable": bool(path) and Path(path).is_file(),
                      "download_url": download_url(e["number"]) if download_url and path else None, "promise": "saved" if e.get("promised") else "none",
                      "current": _unchanged(plan, e, position == len(records) - 1), "results": [], "stage": "file"})
    by_number = {f["number"]: f for f in files}
    unlinked = []
    for pair in pairs:
        number, how = _file_of(pair, reviews.get(pair["engraving_id"]), exports, legacy)
        item = {"pair_id": pair["id"], "status": pair["status"], "photo_name": pair["photo_name"], "created_at": pair["created_at"],
                "accepted_at": pair["accepted_at"], "engraving_id": pair["engraving_id"], "linked_by": how}
        if number in by_number:
            by_number[number]["results"].append(item)
        else:
            unlinked.append(item)
    for f in files:
        f["stage"] = "verified" if any(r["status"] == ACCEPTED for r in f["results"]) else "result" if f["results"] else "file"
    return files, unlinked


def chain_of(plan: dict, files: list[dict], readiness: dict, unlinked: list[dict]) -> dict:
    """Where the work stands now and what comes next. The stage is that of the newest file while the work is as that file left it; a work
    edited since, or never exported, is "prepared" and nothing of an older file's life carries over to it."""
    latest = files[-1] if files else None
    stage = latest["stage"] if latest is not None and latest["current"] else "prepared"
    here = STAGES.index(stage)
    steps = [{"id": s, "state": "done" if i < here else "current" if i == here else "todo"} for i, s in enumerate(STAGES)]
    pending = next((r for r in (latest["results"] if latest else []) if r["status"] in PENDING), None)
    accepted = next((r for r in reversed(latest["results"] if latest else []) if r["status"] == ACCEPTED), None)
    if stage == "prepared":
        action = {"code": "download" if readiness["ready"] else "fix"}
    elif stage == "file":
        action = {"code": "add_result"}
    elif stage == "result":
        action = {"code": "check_result", "pair_id": pending["pair_id"]}
    else:
        action = {"code": "compare", "pair_id": accepted["pair_id"], "engraving_id": accepted["engraving_id"]}
    return {"stage": stage, "steps": steps, "next": action, "file": latest["number"] if latest else None,
            "edited_after": latest["number"] if latest is not None and stage == "prepared" else None, "unlinked": len(unlinked)}


# -- readiness ----------------------------------------------------------------------------------------------------------------------------
def _traced_time(plan: dict, view: dict) -> dict:
    """The time of a traced work's file: the cleaning (when it has one) over the work, then each layer over the area of its regions. A layer
    of lines has no length here and an area without a value is unknown, so the total then says it is incomplete."""
    size, areas = view["document"]["size_mm"], {r["id"]: r.get("area_mm2") for r in view["regions"]}
    markers, rows = plan.get("markers"), []
    clean = plan.get("clean_layer")
    if clean:
        extent = markers["extent"] if markers and plan.get("markers_enabled") else None
        area = ((extent["max_x"] - extent["min_x"]) * (extent["max_y"] - extent["min_y"])) if extent else size["width"] * size["height"]
        rows.append({"index": 0, "name": clean["name"], "parameters": clean, "area_mm2": area})
    for layer in view["layers"]:
        found = [areas.get(i) for i in layer.get("region_ids") or []]
        rows.append({"index": layer["index"], "name": layer["name"], "parameters": layer["parameters"],
                     "area_mm2": None if not found or any(a is None for a in found) else sum(found)})
    return engraving_time.estimate(rows)


def readiness_of_vector(plan: dict, view: dict) -> dict:
    """Whether a vector work's file can be made, from the answer :func:`vector_job.view` gave (so nothing is assessed twice)."""
    photo = view.get("strategy") == "photo"
    time = view["time"] if photo else _traced_time(plan, view)
    blockers = list(view.get("blockers") or [])
    cap = view["layer_cap"]
    used = len(view["layers"]) + len(view.get("zones") or [])
    return {"kind": "photo" if photo else "traced", "ready": not blockers and view.get("export_blocked") is None,
            "size_mm": view["document"]["size_mm"], "seconds": time["seconds"], "time_complete": bool(time["complete"]),
            "layers": used, "layer_cap": cap, "blockers": blockers, "reason": view.get("export_blocked"), "local_only": True,
            "checks": {"colours": not any(b["code"] in ("weak_regions", "missing_colours", "no_palette") for b in blockers),
                       "layers": {"used": used, "cap": cap, "ok": used <= cap}, "cleanup": bool(plan.get("clean_layer")) or photo,
                       "markers": bool(plan.get("markers_enabled"))}}


def readiness_of_plain(plan: dict, time: dict | None) -> dict:
    """Whether a plate or another plain plan can be exported, from its status and layers (the colour reachability of a discrete plan is
    settled before it leaves "draft": :func:`conversion.finalize_discrete`)."""
    blockers = []
    if plan["mode"] == pl.MODE_RESTORED:
        blockers.append({"code": "restored"})
    elif plan["status"] == cv.ST_DRAFT:
        blockers.append({"code": "draft"})
    elif plan["status"] in CLOSED:
        blockers.append({"code": "closed"})
    elif not plan.get("layers"):
        blockers.append({"code": "no_layers"})
    layers = len(plan.get("layers") or [])
    unreachable = sum(1 for m in plan.get("matches") or [] if m.get("status") == "unreachable")
    return {"kind": "plain", "ready": not blockers, "size_mm": plan.get("size_mm"), "seconds": time["seconds"] if time else None,
            "time_complete": bool(time and time.get("complete")), "layers": layers or None, "layer_cap": pl.MAX_LAYERS, "blockers": blockers,
            "reason": None, "local_only": True,
            "checks": {"colours": unreachable == 0, "layers": {"used": layers, "cap": pl.MAX_LAYERS, "ok": layers <= pl.MAX_LAYERS},
                       "cleanup": bool(plan.get("clean_layer")), "markers": bool(plan.get("markers_enabled"))}}


# -- the whole -----------------------------------------------------------------------------------------------------------------------------
def build(store: Store, plan: dict, readiness: dict, download_url=None) -> dict:
    """The lifecycle of one work from its stored plan and the readiness a caller worked out."""
    files, unlinked = files_of(plan, pairs_of(store, plan), download_url)
    return {"plan_id": plan["id"], "status": plan["status"], "readiness": readiness, "files": files, "unlinked": unlinked,
            "chain": chain_of(plan, files, readiness, unlinked)}


def of_vector(store: Store, plan_id: int, view: dict) -> dict:
    """The lifecycle of a vector work whose :func:`vector_job.view` the caller already has."""
    plan = pl.get_plan(store, plan_id)
    return build(store, plan, readiness_of_vector(plan, view), lambda n: f"/api/vector/{plan_id}/exports/{n}")


def of_plain(store: Store, plan_id: int, time: dict | None) -> dict:
    """The lifecycle of any other plan (a plate, a discrete or photograph plan); its exports keep no file, only the record."""
    plan = pl.get_plan(store, plan_id)
    url = (lambda n: f"/api/vector/{plan_id}/exports/{n}") if plan["mode"] == pl.MODE_VECTOR else None
    return build(store, plan, readiness_of_plain(plan, time), url)


def record_plain_export(store: Store, plan_id: int) -> dict:
    """Keep a record of a file handed out for a plain plan (additive: the plan gains an ``exports`` list, nothing else changes) and set it
    "Exported" when it was ready. The file itself is not kept: it is written again from the plan. A plan edited since is draft again."""
    with store.transaction():
        row = store.one("SELECT name, status, markers, data_json FROM plan WHERE id=?", (plan_id,))
        data = json.loads(row["data_json"])
        exports = data.setdefault("exports", [])
        record = {"number": len(exports) + 1, "name": row["name"] + ".lbrn2", "at": now(), "layers": len(data.get("layers") or []) or None,
                  "markers": bool(row["markers"])}
        exports.append(record)
        status = "Exported" if row["status"] == cv.ST_READY else row["status"]
        store.execute("UPDATE plan SET status=?, data_json=? WHERE id=?", (status, json.dumps(data), plan_id))
    return record


# -- what an accepted result did to the prediction -----------------------------------------------------------------------------------------
def slim_attention(attention: dict | None) -> dict | None:
    """The counts of a work's drift that the summary keeps (``None`` when the work has no baseline to drift from)."""
    if attention is None:
        return None
    return {k: attention.get(k) for k in ("layers", "area_share", "proposals")}


def acceptance_summary(plan: dict, review: dict, pair_id: int) -> dict:
    """What the operator needs on returning to the work after a result was accepted: which file the result belongs to and on what basis it
    was compared, how it came out, what changed in the work's current prediction (the counts of layers whose titanium colour moved since the
    file, before this acceptance and after it), and what to do next. The numbers are the stored review's and the work's own."""
    found = review.get("summary") or {}
    change = review.get("prediction_change") or {}
    before, after = change.get("before"), change.get("after")
    proposals = (after or {}).get("proposals") or 0
    return {"plan_id": plan["id"], "work": plan["name"], "pair_id": pair_id, "engraving_id": review["engraving_id"],
            "export_number": review.get("export_number"), "basis": basis_of(plan, review),
            "result": {"promised": found.get("promised"), "engraved": found.get("engraved"), "matched": found.get("matched"),
                       "beyond_layers": found.get("beyond_layers"), "mean_delta_e": found.get("mean_delta_e")},
            "prediction": {"before": before, "after": after, "known": "after" in change,
                           "layers_more": ((after or {}).get("layers") or 0) - ((before or {}).get("layers") or 0) if after is not None else None},
            "next": "replace" if proposals else "compare", "route": f"/vector?plan={plan['id']}&accepted={pair_id}"}
