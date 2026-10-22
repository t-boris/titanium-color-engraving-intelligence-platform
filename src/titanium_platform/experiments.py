"""An experiment is one object (REQ-028, DEC-055): the plate it was made from, the engraving file, every photograph of it
with its checks, the measured result and its conclusions.

Nothing is stored for it. It is derived from what exists: a plate (``plan``) with all the checks (``pair``) made on it, or,
for a finished work without a plate, the checks of one engraving (re-photographs share an ``engraving_id``). The key is
``plan-<id>`` or ``eng-<engraving id>``. Deleted plates and checks are not part of any experiment, and neither are research
plates that were cancelled or replaced before anything was engraved: they are history, not experiments waiting for a photo.
The checks of a plate that is not kept stay as a finished work.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import capability_results, designer, engraving_time, ingest, lightburn as lb, photo_modes, plans as pl, setup as su, tasks
from .db import Store

NEEDS_REVIEW = ("Awaiting check", "Needs correction", "Ready to accept")
STATUS = {"plate_ready": "Плата готова: ждёт фото", "needs_review": "Нужна проверка", "accepted": "Принят"}
HIDDEN_PLANS = ("Deleted", "Cancelled", "Superseded", "Restored")   # a restored plan records a finished work, not a plate


def plan_key(plan_id: int) -> str:
    return f"plan-{plan_id}"


def engraving_key(engraving_id: str) -> str:
    return f"eng-{engraving_id}"


def kept_plan_ids(store: Store) -> set[int]:
    """The plates that are experiments: not deleted, cancelled or superseded, and not on a plate record marked deleted.
    A database without ``plate.status`` (or a NULL there) has no such mark."""
    marks = ",".join("?" * len(HIDDEN_PLANS))
    plate_status = any(c["name"] == "status" for c in store.query("PRAGMA table_info(plate)"))
    sql = (f"SELECT pl.id FROM plan pl LEFT JOIN plate t ON t.id=pl.plate_id WHERE pl.status NOT IN ({marks}) "
           "AND (t.status IS NULL OR t.status!='Deleted')") if plate_status else f"SELECT pl.id FROM plan pl WHERE pl.status NOT IN ({marks})"
    return {r["id"] for r in store.query(sql, HIDDEN_PLANS)}


def _groups(store: Store) -> dict[str, dict]:
    # a plan restored from an imported file is the record of a finished work, not a plate: its pairs stay a finished work
    plans = {pid: pl.get_plan(store, pid) for pid in sorted(kept_plan_ids(store))}
    groups: dict[str, dict] = {plan_key(pid): {"plan": plan, "pairs": []} for pid, plan in plans.items()}
    for row in store.query("SELECT id FROM pair WHERE status!='Deleted' ORDER BY id"):
        pair = ingest.get_pair(store, row["id"])
        key = plan_key(pair["plan_id"]) if pair.get("plan_id") in plans else engraving_key(pair["engraving_id"])
        groups.setdefault(key, {"plan": None, "pairs": []})["pairs"].append(pair)
    # a vector or photo work nobody has photographed is the operator's work, not an experiment: deleting an "experiment" deletes its
    # plan, and for such a work the plan is the work itself (REQ-044, DEC-082, DEC-104)
    works = (pl.MODE_VECTOR, pl.MODE_PHOTO_WORK)
    return {key: g for key, g in groups.items() if g["pairs"] or not g["plan"] or g["plan"]["mode"] not in works}


def _status(group: dict) -> str:
    pairs = group["pairs"]
    if not pairs:
        return "plate_ready"
    return "needs_review" if any(p["status"] in NEEDS_REVIEW for p in pairs) else "accepted"


def _names(group: dict) -> dict:
    plan, pairs = group["plan"], group["pairs"]
    meta = (plan or {}).get("experiment") or {}
    hardware = (pairs[-1].get("hardware") or {}) if pairs else {}
    context = pairs[-1].get("context", {}) if pairs else {}
    material = meta.get("material") or {}
    return {"laser": (meta.get("device") or {}).get("name") or (hardware.get("device") or {}).get("name"),
            "lens": (meta.get("lens") or {}).get("name") or (hardware.get("lens") or {}).get("name"),
            "material": " · ".join(x for x in (material.get("name") or context.get("titanium_name"),
                                              material.get("grade") or context.get("titanium_grade")) if x) or None}


def _observed_tasks(store: Store) -> dict[int, set[str]]:
    """The tasks the observations of every accepted pair were accepted with (derived for those accepted before tasks)."""
    out: dict[int, set[str]] = {}
    for row in store.query("SELECT pair_id, task_kind, parameters_json, evidence_json FROM observation"):
        if json.loads(row["evidence_json"] or "{}").get("role", "test feature") == "test feature":
            out.setdefault(row["pair_id"], set()).add(tasks.of_observation(row)["kind"])
    return out


def _tasks(group: dict, observed: dict[int, set[str]]) -> list[str]:
    """The engraving tasks of an experiment (REQ-020): the one its plan or plate was made for and those of its measured layers
    (the cleaning, markers and labels are the plate's operations, not its tasks), in the order of the task table. An accepted
    check has the tasks of its observations, a check awaiting acceptance those of its layers as they stand."""
    kinds = set()
    plan_task = ((group["plan"] or {}).get("engraving_task") or {}).get("kind")
    if plan_task:
        kinds.add(plan_task)
    for pair in group["pairs"]:
        if pair["status"] == "Accepted":
            kinds |= observed.get(pair["id"], set())
            continue
        for rep in (pair.get("check") or {}).get("layers") or []:
            if rep.get("measured_lab") and rep.get("task") and rep.get("role") in (None, "test feature"):
                kinds.add(rep["task"]["kind"])
    return [k for k in tasks.TASKS if k in kinds]


def _summary(key: str, group: dict, observations: dict[int, int], observed: dict[int, set[str]]) -> dict:
    plan, pairs = group["plan"], group["pairs"]
    main = pairs[-1] if pairs else None            # the latest check is shown first; the others stay one click away
    title = plan["name"] if plan else (pairs[0].get("engraving_title") or pairs[0]["lightburn_name"].rsplit(".", 1)[0])
    stamps = [plan["created_at"]] if plan else []
    stamps += [p["created_at"] for p in pairs] + [p["accepted_at"] for p in pairs if p.get("accepted_at")]
    meta = (plan or {}).get("experiment") or {}
    owner = plan or main                           # the laser and lens records of the experiment (DEC-063)
    return {"key": key, "title": title, "status": _status(group), "status_text": STATUS[_status(group)],
            "kind": (meta.get("test_name") or plan["mode"]) if plan else ("Матрица параметров" if pairs and pairs[0].get("matrix") else "Готовая работа"),
            "plan_id": plan["id"] if plan else None, "engraving_id": pairs[0]["engraving_id"] if pairs and not plan else None,
            "device_id": owner["device_id"], "lens_id": owner["lens_id"],
            "checks": len(pairs), "photos": len({p["photo_name"] for p in pairs}),
            "needs_review": sum(p["status"] in NEEDS_REVIEW for p in pairs),
            "layers_measured": sum(observations.get(p["id"], 0) for p in pairs),
            "main_pair_id": main["id"] if main else None, "created_at": min(stamps) if stamps else None,
            "last_activity": max(stamps) if stamps else None, "tasks": _tasks(group, observed),
            "engraving_task": (plan or {}).get("engraving_task"), **_names(group)}


def _observation_counts(store: Store) -> dict[int, int]:
    return {r["pair_id"]: r["n"] for r in store.query("SELECT pair_id, COUNT(*) AS n FROM observation GROUP BY pair_id")}


def list_experiments(store: Store, device_id: int | None = None, task: str | None = None) -> list[dict]:
    """Every experiment, the most recently active first; of one laser when ``device_id`` is given, of one engraving task when
    ``task`` is (REQ-020)."""
    if task is not None:
        tasks.require(task)
    counts, observed = _observation_counts(store), _observed_tasks(store)
    out = [_summary(key, group, counts, observed) for key, group in _groups(store).items()]
    if device_id is not None:
        out = [e for e in out if e["device_id"] == device_id]
    if task is not None:
        out = [e for e in out if task in e["tasks"]]
    return sorted(out, key=lambda e: (e["last_activity"] or "", e["main_pair_id"] or 0, e["key"]), reverse=True)


def plan_time(plan: dict) -> dict | None:
    """The estimated engraving time of a plan (REQ-060): of the LightBurn file it exports, cleaning and markers included. None when the
    plan cannot be exported yet (the reason is shown where the file is made) and for a vector job, whose colour layers its own export
    writes (the vector screen shows their time)."""
    if plan["mode"] == pl.MODE_VECTOR:
        return None
    try:
        return engraving_time.of_project(lb.parse_bytes(pl.export_lbrn2(plan)))
    except (su.ValidationError, lb.LightBurnError, KeyError, ValueError):
        return None


@lru_cache(maxsize=64)
def _file_time(path: str, stamp: int) -> dict | None:
    try:
        return engraving_time.of_project(lb.parse_file(path))
    except (OSError, lb.LightBurnError):
        return None


def work_time(lightburn_path: str | None) -> dict | None:
    """The estimated engraving time of a finished work from its stored LightBurn file; None when the file cannot be read."""
    if not lightburn_path or not Path(lightburn_path).is_file():
        return None
    return _file_time(lightburn_path, Path(lightburn_path).stat().st_mtime_ns)


def get_experiment(store: Store, key: str) -> dict:
    groups = _groups(store)
    if key not in groups:
        raise KeyError(f"experiment {key} not found")
    group = groups[key]
    summary = _summary(key, group, _observation_counts(store), _observed_tasks(store))
    plan = group["plan"]
    plate = None
    if plan:
        meta = plan.get("experiment") or {}
        plate = {"plan_id": plan["id"], "name": plan["name"], "mode": plan["mode"], "status": plan["status"],
                 "test_type": plan.get("test_type") or meta.get("test_type"), "test_name": meta.get("test_name"),
                 "description": meta.get("test_description"), "layers": len(plan.get("layers", [])),
                 "band_count": plan.get("band_count"), "identifier": plan.get("plan_identifier"), "created_at": plan["created_at"],
                 "proposal": designer.proposal_of_plate(store, plan.get("plate_id")), "engraving_task": plan.get("engraving_task")}
    counts = _observation_counts(store)
    pairs = []
    for p in group["pairs"]:
        check = p.get("check") or {}
        pairs.append({"id": p["id"], "status": p["status"], "photo_name": p["photo_name"], "lightburn_name": p["lightburn_name"],
                      "created_at": p["created_at"], "accepted_at": p.get("accepted_at"),
                      "alignment": (check.get("alignment") or {}).get("method"), "problems": check.get("problems") or [],
                      "measured_layers": sum(1 for l in check.get("layers", []) if l.get("measured_lab")), "observations": counts.get(p["id"], 0),
                      "measurement": (check.get("color_measurement") or {}).get("mode"),
                      "lightburn_url": f"/api/pairs/{p['id']}/lightburn",
                      # a photo engraving whose grey sets the power: its look at other Min and Max can be predicted (REQ-030)
                      "grayscale_image": any((l.get("image") or {}).get("dither") == "grayscale" for l in check.get("layers", [])),
                      # a dot mode whose tones are predicted from what was photographed in it (REQ-054)
                      "tonal_image": any(getattr(photo_modes.mode((l.get("image") or {}).get("dither")), "predicted_from", None) == photo_modes.PROFILE
                                         for l in check.get("layers", []))})
    ids = [p["id"] for p in group["pairs"]]
    findings = []
    if ids:
        marks = ",".join("?" * len(ids))
        for r in store.query(f"SELECT * FROM capability_finding WHERE pair_id IN ({marks}) ORDER BY id DESC", ids):
            findings.append({"id": r["id"], "pair_id": r["pair_id"], "purpose": r["purpose"], "status": r["status"], "summary": r["summary"],
                             "next_test": r["next_test"], "parameters": json.loads(r["parameters_json"]) if r["parameters_json"] else None,
                             "updated_at": r["updated_at"], "history": capability_results.finding_history(store, r["id"])})
    # a plate: the file it exports; a finished work (a vector job's too): the file that was engraved
    last = group["pairs"][-1] if group["pairs"] else None
    time = plan_time(plan) if plan and plan["mode"] != pl.MODE_VECTOR else work_time(last.get("lightburn_path")) if last else None
    return {**summary, "plate": plate, "pairs": pairs, "findings": findings, "time": time}


# -- the pictures the experiment screens show by default ------------------------------------------------------------------
LIST_THUMBNAIL_PX = 480     # experiment-cards.js: photo.png?visibility=lifted&size=480


def screen_pictures(store: Store, pair_id: int) -> list:
    """The pictures the experiment screens ask for one check when they open (BUG-001), so that ``titanium-platform
    warm-cache`` can draw them ahead of time: the thumbnail of the list (experiment-cards.js) and the photograph of the
    experiment page (experiment.js: chart-corrected and as it is when the colours were measured by the chart, the dark uncorrected
    RAW lifted otherwise, with the LightBurn outlines once the photograph is aligned, else the plain photograph the page falls
    back to)."""
    check = ingest.get_pair(store, pair_id).get("check") or {}
    corrected = (check.get("color_measurement") or {}).get("mode") == "reference_chart_corrected"
    visibility = "normal" if corrected else "lifted"
    page = None
    if (check.get("alignment") or {}).get("method"):
        try:
            page = ingest.overlay_picture(store, pair_id, corrected=corrected, visibility=visibility)
        except ingest.IngestError:
            page = None             # an alignment without a transform: the page shows the plain photograph instead
    return [ingest.photo_preview_picture(store, pair_id, visibility="lifted", size=LIST_THUMBNAIL_PX),
            page or ingest.photo_preview_picture(store, pair_id, corrected=corrected, visibility=visibility)]
