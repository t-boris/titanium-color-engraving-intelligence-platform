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

from . import capability_results, ingest, plans as pl
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
    return groups


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


def _summary(key: str, group: dict, observations: dict[int, int]) -> dict:
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
            "last_activity": max(stamps) if stamps else None, **_names(group)}


def _observation_counts(store: Store) -> dict[int, int]:
    return {r["pair_id"]: r["n"] for r in store.query("SELECT pair_id, COUNT(*) AS n FROM observation GROUP BY pair_id")}


def list_experiments(store: Store, device_id: int | None = None) -> list[dict]:
    """Every experiment, the most recently active first; of one laser when ``device_id`` is given."""
    counts = _observation_counts(store)
    out = [_summary(key, group, counts) for key, group in _groups(store).items()]
    if device_id is not None:
        out = [e for e in out if e["device_id"] == device_id]
    return sorted(out, key=lambda e: (e["last_activity"] or "", e["main_pair_id"] or 0, e["key"]), reverse=True)


def get_experiment(store: Store, key: str) -> dict:
    groups = _groups(store)
    if key not in groups:
        raise KeyError(f"experiment {key} not found")
    group = groups[key]
    summary = _summary(key, group, _observation_counts(store))
    plan = group["plan"]
    plate = None
    if plan:
        meta = plan.get("experiment") or {}
        plate = {"plan_id": plan["id"], "name": plan["name"], "mode": plan["mode"], "status": plan["status"],
                 "test_type": plan.get("test_type") or meta.get("test_type"), "test_name": meta.get("test_name"),
                 "description": meta.get("test_description"), "layers": len(plan.get("layers", [])),
                 "band_count": plan.get("band_count"), "identifier": plan.get("plan_identifier"), "created_at": plan["created_at"]}
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
                      "grayscale_image": any((l.get("image") or {}).get("dither") == "grayscale" for l in check.get("layers", []))})
    ids = [p["id"] for p in group["pairs"]]
    findings = []
    if ids:
        marks = ",".join("?" * len(ids))
        for r in store.query(f"SELECT * FROM capability_finding WHERE pair_id IN ({marks}) ORDER BY id DESC", ids):
            findings.append({"id": r["id"], "pair_id": r["pair_id"], "purpose": r["purpose"], "status": r["status"], "summary": r["summary"],
                             "next_test": r["next_test"], "parameters": json.loads(r["parameters_json"]) if r["parameters_json"] else None,
                             "updated_at": r["updated_at"], "history": capability_results.finding_history(store, r["id"])})
    return {**summary, "plate": plate, "pairs": pairs, "findings": findings}
