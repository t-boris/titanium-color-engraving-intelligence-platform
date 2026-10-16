"""Knowledge maturation (REQ-005, DEC-006, DEC-011, DEC-021, proposed DEC-029).

Stages: measured < candidate < repeated < validated < production. Automatic promotion stops at validated
and only runs once the operator has saved the thresholds and agreed the criteria; production needs an
explicit action and is never lowered automatically (not even by rollback). A production entry whose later
observations break the saved thresholds is flagged questioned and keeps its stage.
"""
from __future__ import annotations

import json

from . import model, profiles as pf
from .db import Store, now

STAGES = ["measured", "candidate", "repeated", "validated", "production"]


class KnowledgeError(ValueError):
    """A maturity action is not allowed; the message is meant for the operator."""


def _rank(stage: str) -> int:
    return STAGES.index(stage)


def _event(store: Store, kid: int, type_: str, frm: str | None, to: str | None, reason: str, obs_ids: list[int]) -> None:
    store.execute("INSERT INTO knowledge_event(knowledge_id,at,type,from_stage,to_stage,reason,observation_ids_json) VALUES (?,?,?,?,?,?,?)",
                  (kid, now(), type_, frm, to, reason, json.dumps(obs_ids)))


def automatic_stage(summary: dict, rules: dict) -> tuple[str, str]:
    """The stage the evidence supports and why. Without agreed criteria nothing passes 'measured' (DEC-029)."""
    if not rules["criteria_agreed"]:
        return "measured", "criteria not agreed: automatic promotion is disabled"
    n_ind, obs = summary["independent_engravings"], summary["observations"]
    if n_ind >= 2:
        t = max(2, rules["repeat_threshold"])
        st = summary["stability"]
        if n_ind >= t and st["assessed"] and st["variance"] <= rules["variance_threshold"] and st["max_deviation"] <= rules["delta_tolerance"]:
            return "validated", f"{n_ind} independent engravings within variance and tolerance"
        return "repeated", f"{n_ind} independent engravings"
    if obs > 1:
        return "candidate", "more than one observation"
    return "measured", "single observation"


def _breaks_thresholds(summary: dict, rules: dict) -> list[str]:
    why = []
    st = summary["stability"]
    if rules["variance_threshold"] is not None and st["assessed"] and st["variance"] > rules["variance_threshold"]:
        why.append(f"variance {st['variance']:.2f} exceeds {rules['variance_threshold']:g}")
    if rules["delta_tolerance"] is not None and st["assessed"] and st["max_deviation"] > rules["delta_tolerance"]:
        why.append(f"deviation {st['max_deviation']:.2f} exceeds {rules['delta_tolerance']:g}")
    return why


def refresh(store: Store, profile_id: int) -> list[dict]:
    """Refresh one laser/lens knowledge base, combining legacy IDs for that same hardware pair."""
    profile_id = model.canonical_profile_id(store, profile_id)
    rules = pf.get_rules(store, profile_id)
    changes = []
    with store.transaction():
        for key, s in model.knowledge_summaries(store, profile_id).items():
            row = store.one("SELECT * FROM knowledge WHERE profile_id=? AND parameters_key=?", (profile_id, key))
            target, why = automatic_stage(s, rules)
            if row is None:
                kid = store.execute("INSERT INTO knowledge(profile_id,parameters_key,parameters_json,stage,questioned,updated_at) VALUES (?,?,?,?,0,?)",
                                    (profile_id, key, json.dumps(s["parameters"]), "measured", now())).lastrowid
                _event(store, kid, "created", None, "measured", "first eligible observation", s["observation_ids"])
                row = store.one("SELECT * FROM knowledge WHERE id=?", (kid,))
            cur = row["stage"]
            # automatic promotion only moves up and never reaches or leaves production
            if cur != "production" and _rank(target) > _rank(cur):
                store.execute("UPDATE knowledge SET stage=?, updated_at=? WHERE id=?", (target, now(), row["id"]))
                _event(store, row["id"], "promoted", cur, target, why, s["observation_ids"])
                changes.append({"id": row["id"], "key": key, "from": cur, "to": target})
                cur = target
            if cur == "production":
                broken = _breaks_thresholds(s, rules)
                if broken and not row["questioned"]:
                    doubt = {"reason": "; ".join(broken), "observation_ids": s["observation_ids"]}
                    store.execute("UPDATE knowledge SET questioned=1, doubt_json=?, updated_at=? WHERE id=?", (json.dumps(doubt), now(), row["id"]))
                    _event(store, row["id"], "questioned", cur, cur, doubt["reason"], s["observation_ids"])
                    changes.append({"id": row["id"], "key": key, "questioned": True})
    return changes


def get(store: Store, kid: int) -> dict:
    row = store.one("SELECT * FROM knowledge WHERE id=?", (kid,))
    if row is None:
        raise KeyError(f"knowledge {kid} not found")
    d = dict(row)
    d["parameters"] = json.loads(d.pop("parameters_json"))
    d["doubt"] = json.loads(d.pop("doubt_json")) if d.get("doubt_json") else None
    d.pop("doubt_json", None)
    d["questioned"] = bool(d["questioned"])
    d["history"] = [dict(e, observation_ids=json.loads(e.pop("observation_ids_json"))) for e in
                    (dict(r) for r in store.query("SELECT * FROM knowledge_event WHERE knowledge_id=? ORDER BY id", (kid,)))]
    s = model.knowledge_summaries(store, d["profile_id"]).get(d["parameters_key"])
    d["summary"] = s
    return d


def list_for_profile(store: Store, profile_id: int) -> list[dict]:
    canonical = model.canonical_profile_id(store, profile_id)
    return [get(store, r["id"]) for r in store.query("SELECT id FROM knowledge WHERE profile_id=? ORDER BY id", (canonical,))]


# -- operator decisions ---------------------------------------------------------------------------------
def approve_for_production(store: Store, kid: int, confirm: bool) -> dict:
    k = get(store, kid)
    if not confirm:
        raise KnowledgeError("approving for production needs your explicit confirmation")
    if k["stage"] != "validated":
        raise KnowledgeError(f"only a validated entry can be approved for production (this one is {k['stage']})")
    store.execute("UPDATE knowledge SET stage='production', updated_at=? WHERE id=?", (now(), kid))
    _event(store, kid, "approved", "validated", "production", "approved by the operator", (k["summary"] or {}).get("observation_ids", []))
    return get(store, kid)


def demote(store: Store, kid: int, to_stage: str, reason: str, confirm: bool) -> dict:
    k = get(store, kid)
    if k["stage"] != "production":
        raise KnowledgeError("only a production entry can be demoted manually")
    if to_stage not in STAGES[:-1]:
        raise KnowledgeError("choose a lower stage")
    if not confirm:
        raise KnowledgeError("demotion needs your explicit confirmation")
    obs = (k["doubt"] or {}).get("observation_ids") or (k["summary"] or {}).get("observation_ids", [])
    store.execute("UPDATE knowledge SET stage=?, questioned=0, doubt_json=NULL, updated_at=? WHERE id=?", (to_stage, now(), kid))
    _event(store, kid, "demoted", "production", to_stage, (reason or "").strip() or "manual demotion", obs)
    return get(store, kid)


def confirm_questioned(store: Store, kid: int) -> dict:
    k = get(store, kid)
    if not k["questioned"]:
        raise KnowledgeError("this entry is not questioned")
    store.execute("UPDATE knowledge SET questioned=0, doubt_json=NULL, updated_at=? WHERE id=?", (now(), kid))
    _event(store, kid, "confirmed", k["stage"], k["stage"], "flag cleared by the operator: " + (k["doubt"] or {}).get("reason", ""),
           (k["doubt"] or {}).get("observation_ids", []))
    return get(store, kid)


def rollback(store: Store, kid: int, event_id: int, confirm_production: bool = False) -> dict:
    """Return to the stage before the chosen event by adding a new event. Never raises the stage."""
    k = get(store, kid)
    ev = next((e for e in k["history"] if e["id"] == event_id), None)
    if ev is None or ev["from_stage"] is None:
        raise KnowledgeError("choose a transition that has a previous stage")
    if _rank(ev["from_stage"]) >= _rank(k["stage"]):
        raise KnowledgeError("rollback would not lower the current stage")
    if k["stage"] == "production" and not confirm_production:
        raise KnowledgeError("rolling back a production entry needs your explicit confirmation")
    store.execute("UPDATE knowledge SET stage=?, updated_at=? WHERE id=?", (ev["from_stage"], now(), kid))
    _event(store, kid, "rollback", k["stage"], ev["from_stage"], f"rolled back event {event_id}", ev["observation_ids"])
    return get(store, kid)
