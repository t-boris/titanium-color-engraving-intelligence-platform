"""The operator's exclusions (feature act-on-findings): measurements taken out of every calculation by a decision, never by changing
them (observations are immutable, REQ-001).

Two decisions, each kept in ``operator_exclusion`` until «Вернуть» revokes it (the record and the audit stay):
  measurement       one measured layer of one photograph (REQ-001, DEC-001). It is kept by the photograph's first measurement and the
                    layer, as the stable anomaly key (DEC-002 of findings-you-can-manage-short-lists-re-check), so every re-measure of
                    the photograph stays out; a re-photo of the engraving is another photograph and counts.
  older_engravings  a recipe counted from its newest engraving (REQ-002, DEC-003): the ids of its older engravings, not a date, so a
                    re-measure (which renews ``accepted_at``) cannot bring them back and an engraving made later counts.

:func:`excluded_ids` is the one answer every reader of measurements asks (DEC-004): the knowledge and the findings
(``model.eligible_observations``), the colour map, palette, predictions and works (``colormap``), the oxide model and a new laboratory
release. A decision shows its effect first (:func:`preview`) and, once made or revoked, recalculates once (:func:`_recalculate`).
"""
from __future__ import annotations

import json

import numpy as np

from . import color, setup as su
from .db import Store, now

MEASUREMENT = "measurement"
OLDER = "older_engravings"
KINDS = (MEASUREMENT, OLDER)
ACTIONS = {"exclude_measurement": MEASUREMENT, "count_from_latest": OLDER}


# -- what is out now -------------------------------------------------------------------------------------------------------------
def _active(store: Store) -> list:
    return store.query("SELECT * FROM operator_exclusion WHERE revoked_at IS NULL ORDER BY id")


def _recipe_ids(store: Store, device_id: int, lens_id: int | None, recipe_key: str, engraving_ids: list[str]) -> set[int]:
    """The observations of the given engravings that count toward the recipe ``recipe_key`` on this laser and lens."""
    from . import model, tasks
    if not engraving_ids:
        return set()
    rows = store.query(f"SELECT * FROM observation WHERE device_id=? AND lens_id IS ? AND engraving_id IN ({','.join('?' * len(engraving_ids))})",
                       (device_id, lens_id, *engraving_ids))
    return {r["id"] for r in rows
            if model.observation_key(json.loads(r["parameters_json"]), json.loads(r["context_json"]), tasks.of_observation(r)) == recipe_key}


def excluded_ids(store: Store) -> set[int]:
    """The ids of the observations the operator's decisions keep out of every calculation now."""
    rows = _active(store)
    if not rows:
        return set()
    out: set[int] = set()
    taken = {(r["original_pair_id"], r["layer_index"]) for r in rows if r["kind"] == MEASUREMENT}
    if taken:
        from . import ingest
        originals = ingest.original_pairs(store)
        firsts = {first for first, _ in taken}
        pairs = [pair_id for pair_id, first in originals.items() if first in firsts]
        if pairs:
            for o in store.query(f"SELECT id, pair_id, layer_index FROM observation WHERE pair_id IN ({','.join('?' * len(pairs))})", pairs):
                if (originals[o["pair_id"]], o["layer_index"]) in taken:
                    out.add(o["id"])
    for r in rows:
        if r["kind"] == OLDER:
            out |= _recipe_ids(store, r["device_id"], r["lens_id"], r["recipe_key"], json.loads(r["engraving_ids_json"]))
    return out


# -- what a decision would change ------------------------------------------------------------------------------------------------
def _recipe(store: Store, device_id: int, lens_id: int | None, recipe_key: str) -> list[dict]:
    """The observations that count toward one recipe now (the operator's exclusions already left out)."""
    from . import model
    return [o for o in model.eligible_observations(store, device_id, lens_id)
            if model.observation_key(o["parameters"], o["context"], o["task"]) == recipe_key]


def _colour(obs: list[dict]) -> dict | None:
    """A recipe's agreed colour and how far its engravings agree, as the knowledge derives it (``model.summarize``)."""
    from . import model
    if not obs:
        return None
    s = model.summarize(obs)
    return {"lab": [round(v, 2) for v in s["lab"]], "engravings": s["engravings"], "observations": s["observations"],
            "confidence": s["confidence"], "contradicted": s["caution"] == "contradicted"}


def _change(before: list[dict], after: list[dict]) -> dict:
    was, becomes = _colour(before), _colour(after)
    moved = None if was is None or becomes is None else round(color.delta_e(np.asarray(was["lab"]), np.asarray(becomes["lab"])), 2)
    return {"before": was, "after": becomes, "delta_e": moved}


def _engravings(store: Store, obs: list[dict]) -> list[dict]:
    """The engravings of a recipe, newest first: when, which photographs, the work they belong to."""
    from . import model
    groups: dict[str, list[dict]] = {}
    for o in obs:
        groups.setdefault(o["engraving_id"], []).append(o)
    out = []
    for engraving_id, members in sorted(groups.items(), key=lambda kv: model._when(kv[1]), reverse=True):
        pairs = sorted({o["pair_id"] for o in members})
        title = store.one("SELECT engraving_title FROM pair WHERE id=?", (pairs[0],))
        out.append({"engraving_id": engraving_id, "title": title["engraving_title"] if title else None, "pair_ids": pairs,
                    "when": model._when(members)[0] or None, "observation_ids": [o["id"] for o in members],
                    "lab": [round(float(v), 2) for v in np.mean([o["lab"] for o in members], axis=0)]})
    return out


def _observation(store: Store, observation_id: int) -> dict:
    """An observation that counts now, with its photograph and layer name; refused when it counts toward nothing."""
    from . import model, tasks
    row = store.one("SELECT o.*, p.photo_name, p.engraving_title, p.status AS pair_status FROM observation o JOIN pair p ON p.id=o.pair_id "
                    "WHERE o.id=?", (observation_id,))
    if row is None:
        raise KeyError(f"observation {observation_id} not found")
    if observation_id in excluded_ids(store):
        raise su.ValidationError(f"observation {observation_id} is already taken out of the calculations")
    if row["pair_status"] != "Accepted" or model.knowledge_key_of(row) is None:
        raise su.ValidationError(f"observation {observation_id} counts toward no recipe: there is nothing to take out")
    parameters, context = json.loads(row["parameters_json"]), json.loads(row["context_json"])
    return {"id": row["id"], "pair_id": row["pair_id"], "layer_index": row["layer_index"], "engraving_id": row["engraving_id"],
            "device_id": row["device_id"], "lens_id": row["lens_id"], "lab": json.loads(row["lab_json"]),
            "layer_name": json.loads(row["evidence_json"] or "{}").get("layer_name"), "photo_name": row["photo_name"],
            "engraving_title": row["engraving_title"], "recipe_key": model.observation_key(parameters, context, tasks.of_observation(row)),
            "parameters": parameters}


def _settings(obs: list[dict]) -> dict:
    keep = ("power", "frequency", "speed", "pulse_width", "line_interval", "passes", "layer_type")
    return {k: obs[0]["parameters"].get(k) for k in keep} if obs else {}


def preview_measurement(store: Store, observation_id: int) -> dict:
    """What «Убрать измерение» would change: the layer that leaves and the recipe's colour before and after (REQ-004)."""
    o = _observation(store, observation_id)
    members = _recipe(store, o["device_id"], o["lens_id"], o["recipe_key"])
    remaining = [m for m in members if m["id"] != observation_id]
    gone_engravings = sorted({o["engraving_id"]} - {m["engraving_id"] for m in remaining})
    return {"action": "exclude_measurement", "kind": MEASUREMENT, "device_id": o["device_id"], "lens_id": o["lens_id"],
            "recipe_key": o["recipe_key"], "settings": _settings(members),
            "observation": {k: o[k] for k in ("id", "pair_id", "layer_index", "layer_name", "photo_name", "engraving_title", "lab")},
            "leaving": {"observation_ids": [observation_id], "pair_ids": [o["pair_id"]], "engraving_ids": gone_engravings},
            **_change(members, remaining)}


def preview_latest(store: Store, device_id: int, lens_id: int | None, recipe_key: str) -> dict:
    """What «Считать с последней гравировки» would change: the engraving kept, the older ones that leave, and the recipe's colour
    before and after (REQ-002, REQ-004). Refused when the recipe has one engraving."""
    members = _recipe(store, device_id, lens_id, recipe_key)
    if not members:
        raise su.ValidationError("no measurement counts toward this recipe now")
    engravings = _engravings(store, members)
    if len(engravings) < 2:
        raise su.ValidationError("this recipe rests on one engraving: there is no older one to leave out")
    kept, older = engravings[0], engravings[1:]
    remaining = [m for m in members if m["engraving_id"] == kept["engraving_id"]]
    return {"action": "count_from_latest", "kind": OLDER, "device_id": device_id, "lens_id": lens_id, "recipe_key": recipe_key,
            "settings": _settings(members), "kept": kept, "older": older,
            "leaving": {"observation_ids": [i for e in older for i in e["observation_ids"]],
                        "pair_ids": sorted({p for e in older for p in e["pair_ids"]}), "engraving_ids": [e["engraving_id"] for e in older]},
            **_change(members, remaining)}


# -- the decisions ---------------------------------------------------------------------------------------------------------------
def _recalculate(store: Store, device_id: int, lens_id: int | None, removed: dict[str, list[int]] | None) -> dict | None:
    """One recalculation after a decision (DEC-004): the knowledge (an entry whose evidence left is questioned, as after a removed
    photograph), the proposals, a findings run and the works of the laser and lens. The decision stands when the run fails: it is
    written to the audit and the next run recalculates everything."""
    from . import designer, findings, knowledge, work_errors
    if removed:
        knowledge.after_removal(store, device_id, lens_id, removed, taken_out=True)
    else:
        knowledge.refresh(store, device_id, lens_id)
    run = None
    try:
        designer.reconcile_statuses(store)
        run = findings.run_analysis(store, "operator")
    except Exception as exc:
        store.audit("analysis_failed", trigger="operator", error=f"{type(exc).__name__}: {exc}")
    work_errors.after_change(store, device_id, lens_id)
    return run


def _guard(store: Store) -> None:
    from . import recheck
    recheck.ensure_idle(store)                      # not while every work is being re-checked


def _insert(store: Store, kind: str, p: dict, note: str | None, finding_key: str | None, **fields) -> int:
    note = (note or "").strip()[:2000] or None
    detail = {k: p.get(k) for k in ("settings", "observation", "kept", "older", "before", "after", "delta_e")}
    xid = store.execute(
        "INSERT INTO operator_exclusion(kind,device_id,lens_id,original_pair_id,layer_index,recipe_key,engraving_ids_json,kept_engraving_id,"
        "finding_key,note,detail_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (kind, p["device_id"], p["lens_id"], fields.get("original_pair_id"), fields.get("layer_index"), p["recipe_key"],
         json.dumps(fields["engraving_ids"]) if "engraving_ids" in fields else None, fields.get("kept_engraving_id"), finding_key, note,
         json.dumps(detail), now())).lastrowid
    store.audit("exclusion_added", exclusion_id=xid, kind=kind, device_id=p["device_id"], lens_id=p["lens_id"], recipe_key=p["recipe_key"],
                observation_ids=p["leaving"]["observation_ids"], finding_key=finding_key, note=note)
    return xid


def exclude_measurement(store: Store, observation_id: int, note: str | None = None, finding_key: str | None = None) -> dict:
    """«Убрать измерение»: one measured layer of one photograph leaves every calculation (REQ-001)."""
    from . import ingest
    _guard(store)
    p = preview_measurement(store, observation_id)
    o = p["observation"]
    with store.transaction():
        xid = _insert(store, MEASUREMENT, p, note, finding_key, original_pair_id=ingest.original_pairs(store).get(o["pair_id"], o["pair_id"]),
                      layer_index=o["layer_index"])
    run = _recalculate(store, p["device_id"], p["lens_id"], {p["recipe_key"]: [observation_id]})
    return {"exclusion": get(store, xid), "preview": p, "run_id": run["id"] if run else None}


def count_from_latest(store: Store, device_id: int, lens_id: int | None, recipe_key: str, note: str | None = None,
                      finding_key: str | None = None) -> dict:
    """«Считать с последней гравировки»: the recipe counts from its newest engraving, its older ones leave (REQ-002). An earlier decision
    of the recipe is replaced, and the engravings it left out stay out."""
    _guard(store)
    p = preview_latest(store, device_id, lens_id, recipe_key)
    earlier = store.query("SELECT * FROM operator_exclusion WHERE kind=? AND device_id=? AND lens_id IS ? AND recipe_key=? AND revoked_at IS NULL",
                          (OLDER, device_id, lens_id, recipe_key))
    left = list(dict.fromkeys([e for r in earlier for e in json.loads(r["engraving_ids_json"])] + p["leaving"]["engraving_ids"]))
    with store.transaction():
        for r in earlier:
            store.execute("UPDATE operator_exclusion SET revoked_at=? WHERE id=?", (now(), r["id"]))
            store.audit("exclusion_revoked", exclusion_id=r["id"], kind=OLDER, reason="replaced by a newer decision of the recipe")
        xid = _insert(store, OLDER, p, note, finding_key, engraving_ids=left, kept_engraving_id=p["kept"]["engraving_id"])
    run = _recalculate(store, device_id, lens_id, {recipe_key: p["leaving"]["observation_ids"]})
    return {"exclusion": get(store, xid), "preview": p, "run_id": run["id"] if run else None}


def revoke(store: Store, exclusion_id: int) -> dict:
    """«Вернуть»: the measurements of a decision count again; the record and the audit stay."""
    _guard(store)
    row = store.one("SELECT * FROM operator_exclusion WHERE id=?", (exclusion_id,))
    if row is None:
        raise KeyError(f"exclusion {exclusion_id} not found")
    if row["revoked_at"] is not None:
        raise su.ValidationError(f"exclusion {exclusion_id} was already undone")
    with store.transaction():
        store.execute("UPDATE operator_exclusion SET revoked_at=? WHERE id=?", (now(), exclusion_id))
        store.audit("exclusion_revoked", exclusion_id=exclusion_id, kind=row["kind"], reason="returned by the operator")
    run = _recalculate(store, row["device_id"], row["lens_id"], None)
    return {"exclusion": get(store, exclusion_id), "run_id": run["id"] if run else None}


# -- reading them ----------------------------------------------------------------------------------------------------------------
def _public(row) -> dict:
    detail = json.loads(row["detail_json"] or "{}")
    return {"id": row["id"], "kind": row["kind"], "device_id": row["device_id"], "lens_id": row["lens_id"], "recipe_key": row["recipe_key"],
            "original_pair_id": row["original_pair_id"], "layer_index": row["layer_index"],
            "engraving_ids": json.loads(row["engraving_ids_json"]) if row["engraving_ids_json"] else None,
            "kept_engraving_id": row["kept_engraving_id"], "finding_key": row["finding_key"], "note": row["note"],
            "created_at": row["created_at"], "revoked_at": row["revoked_at"], "active": row["revoked_at"] is None, **detail}


def get(store: Store, exclusion_id: int) -> dict:
    row = store.one("SELECT * FROM operator_exclusion WHERE id=?", (exclusion_id,))
    if row is None:
        raise KeyError(f"exclusion {exclusion_id} not found")
    return _public(row)


def listing(store: Store, include_revoked: bool = False) -> dict:
    """The operator's exclusions, newest first, with what each keeps out now (REQ-005)."""
    rows = store.query("SELECT * FROM operator_exclusion" + ("" if include_revoked else " WHERE revoked_at IS NULL") + " ORDER BY id DESC")
    items = []
    for r in rows:
        item = _public(r)
        if item["active"]:
            if r["kind"] == OLDER:
                item["observations_out"] = len(_recipe_ids(store, r["device_id"], r["lens_id"], r["recipe_key"], item["engraving_ids"]))
            else:
                item["observations_out"] = 1
            pair = _current_pair(store, r["original_pair_id"]) if r["kind"] == MEASUREMENT else None
            item["pair_id"] = pair
        items.append(item)
    active = store.one("SELECT COUNT(*) AS n FROM operator_exclusion WHERE revoked_at IS NULL")["n"]
    return {"exclusions": items, "active": active}


def _current_pair(store: Store, original_pair_id: int) -> int | None:
    """The accepted measurement of a photograph now: its first one or the latest re-measure of it."""
    from . import ingest
    originals = ingest.original_pairs(store)
    ids = [p for p, first in originals.items() if first == original_pair_id]
    if not ids:
        return None
    row = store.one(f"SELECT id FROM pair WHERE status='Accepted' AND id IN ({','.join('?' * len(ids))}) ORDER BY id DESC LIMIT 1", ids)
    return row["id"] if row else None


def of_pair(store: Store, pair_id: int) -> dict[int, dict]:
    """The layers of a photograph the operator took out, by layer index (the photo page marks them)."""
    from . import ingest
    first = ingest.original_pairs(store).get(pair_id, pair_id)
    return {r["layer_index"]: _public(r) for r in store.query(
        "SELECT * FROM operator_exclusion WHERE kind=? AND original_pair_id=? AND revoked_at IS NULL ORDER BY id", (MEASUREMENT, first))}


def of_recipe(store: Store, device_id: int, lens_id: int | None, recipe_key: str) -> dict | None:
    """The decision that counts a recipe from its newest engraving, if there is one (the knowledge entry shows it)."""
    row = store.one("SELECT * FROM operator_exclusion WHERE kind=? AND device_id=? AND lens_id IS ? AND recipe_key=? AND revoked_at IS NULL "
                    "ORDER BY id DESC LIMIT 1", (OLDER, device_id, lens_id, recipe_key))
    return None if row is None else _public(row)
