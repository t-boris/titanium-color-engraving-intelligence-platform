"""Knowledge maturation (REQ-005, DEC-006, DEC-011, DEC-021, proposed DEC-029).

Stages: measured < candidate < repeated < validated < production. Automatic promotion stops at validated
and only runs once the operator has saved the thresholds and agreed the criteria; production needs an
explicit action and is never lowered automatically (not even by rollback). A production entry whose later
observations break the saved thresholds is flagged questioned and keeps its stage; so is an entry of any stage whose
evidence a deleted pair took away (DEC-066 item 3).

Knowledge belongs to one laser and one lens record (DEC-063) and, within them, to one recipe key: entries of
different lasers, lenses (an unknown lens included) or job settings never share counts, stages or approval.
"""
from __future__ import annotations

import json

from . import exclusions, model, setup as su
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


def supported_stage(summary: dict | None, rules: dict) -> tuple[str | None, str]:
    """The highest stage the evidence of an entry still supports and why; None when no eligible observation is left.

    With agreed criteria it is the stage automatic promotion would reach. Without them the thresholds of 'validated' cannot
    be judged, so only the counts are, and two independent engravings do not contradict it."""
    if summary is None:
        return None, "no eligible observation is left"
    if rules["criteria_agreed"]:
        return automatic_stage(summary, rules)
    n_ind, obs = summary["independent_engravings"], summary["observations"]
    if n_ind >= 2:
        return "validated", f"{n_ind} independent engravings"
    if obs > 1:
        return "candidate", "more than one observation"
    return "measured", "single observation"


def removal_doubt(supported: str | None, why: str, taken_out: bool = False) -> str:
    """Why an entry is questioned after observations left active use (DEC-066 item 3): with a removed photograph, or ``taken_out`` by
    the operator from every calculation (act-on-findings DEC-004)."""
    if taken_out:
        if supported is None:
            return "measurements the operator took out took away the evidence of this stage: no eligible observation is left"
        return f"measurements the operator took out took away the evidence of this stage: what remains supports only {supported}: {why}"
    if supported is None:
        return "a removed photograph took away the evidence of this stage: no eligible observation is left"
    return f"a removed photograph took away the evidence of this stage: what remains supports only {supported}: {why}"


def _breaks_thresholds(summary: dict, rules: dict) -> list[str]:
    why = []
    st = summary["stability"]
    if rules["variance_threshold"] is not None and st["assessed"] and st["variance"] > rules["variance_threshold"]:
        why.append(f"variance {st['variance']:.2f} exceeds {rules['variance_threshold']:g}")
    if rules["delta_tolerance"] is not None and st["assessed"] and st["max_deviation"] > rules["delta_tolerance"]:
        why.append(f"deviation {st['max_deviation']:.2f} exceeds {rules['delta_tolerance']:g}")
    return why


def refresh(store: Store, device_id: int, lens_id: int | None) -> list[dict]:
    """Refresh the knowledge of one laser and lens record from its eligible observations."""
    rules = su.get_rules(store, device_id, lens_id)
    changes = []
    with store.transaction():
        for key, s in model.knowledge_summaries(store, device_id, lens_id).items():
            row = store.one("SELECT * FROM knowledge WHERE device_id=? AND lens_id IS ? AND parameters_key=?", (device_id, lens_id, key))
            target, why = automatic_stage(s, rules)
            if row is None:
                kid = store.execute("INSERT INTO knowledge(device_id,lens_id,parameters_key,parameters_json,stage,questioned,updated_at) VALUES (?,?,?,?,?,0,?)",
                                    (device_id, lens_id, key, json.dumps(s["parameters"]), "measured", now())).lastrowid
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


def after_removal(store: Store, device_id: int, lens_id: int | None, removed: dict[str, list[int]], taken_out: bool = False) -> list[dict]:
    """Rebuild the knowledge of one laser and lens after observations left active use with their deleted pair (DEC-047), or because
    the operator took them out of every calculation (``taken_out``, act-on-findings DEC-004).

    ``removed`` maps the key of every affected entry to the ids of its observations that left. Counts and statistics are
    derived on every read, so they follow at once; the stages are refreshed as after any change, which never lowers one.
    An affected entry whose remaining evidence no longer supports its stage keeps the stage and is flagged questioned with
    that reason, whatever the stage (DEC-066 item 3); the flag names the removed observations that triggered it.
    """
    changes = refresh(store, device_id, lens_id)
    rules = su.get_rules(store, device_id, lens_id)
    summaries = model.knowledge_summaries(store, device_id, lens_id)
    with store.transaction():
        for key, gone in sorted(removed.items()):
            row = store.one("SELECT * FROM knowledge WHERE device_id=? AND lens_id IS ? AND parameters_key=?", (device_id, lens_id, key))
            if row is None:
                continue
            supported, why = supported_stage(summaries.get(key), rules)
            needed = "validated" if row["stage"] == "production" else row["stage"]
            if supported is not None and _rank(supported) >= _rank(needed):
                continue
            doubt = {"reason": removal_doubt(supported, why, taken_out), "observation_ids": sorted(gone)}
            store.execute("UPDATE knowledge SET questioned=1, doubt_json=?, updated_at=? WHERE id=?", (json.dumps(doubt), now(), row["id"]))
            _event(store, row["id"], "questioned", row["stage"], row["stage"], doubt["reason"], doubt["observation_ids"])
            changes.append({"id": row["id"], "key": key, "questioned": True})
    return changes


def get(store: Store, kid: int, summaries: dict[str, dict] | None = None, events: list | None = None) -> dict:
    """One knowledge entry with its history and the summary of its evidence.

    A caller that reads many entries of one laser and lens passes what they share, read once: ``summaries`` (the
    ``model.knowledge_summaries`` of that laser and lens) and ``events`` (the entry's ``knowledge_event`` rows in id order).
    Each is read here when not given; the result is the same either way."""
    row = store.one("SELECT * FROM knowledge WHERE id=?", (kid,))
    if row is None:
        raise KeyError(f"knowledge {kid} not found")
    d = dict(row)
    d["parameters"] = json.loads(d.pop("parameters_json"))
    d["doubt"] = json.loads(d.pop("doubt_json")) if d.get("doubt_json") else None
    d.pop("doubt_json", None)
    d["questioned"] = bool(d["questioned"])
    if events is None:
        events = store.query("SELECT * FROM knowledge_event WHERE knowledge_id=? ORDER BY id", (kid,))
    d["history"] = [dict(e, observation_ids=json.loads(e.pop("observation_ids_json"))) for e in (dict(r) for r in events)]
    if summaries is None:
        summaries = model.knowledge_summaries(store, d["device_id"], d["lens_id"])
    d["summary"] = summaries.get(d["parameters_key"])
    d["counted_from"] = exclusions.of_recipe(store, d["device_id"], d["lens_id"], d["parameters_key"])   # act-on-findings REQ-002
    return d


def list_for_setup(store: Store, device_id: int, lens_id: int | None) -> list[dict]:
    """Every entry of one laser and lens, as ``get`` gives each. The summaries of the setup and the events of its entries are
    read once for the whole list (BUG-001: reading them per entry made the list quadratic in its length)."""
    ids = [r["id"] for r in store.query("SELECT id FROM knowledge WHERE device_id=? AND lens_id IS ? ORDER BY id", (device_id, lens_id))]
    events: dict[int, list] = {}
    for e in store.query("SELECT e.* FROM knowledge_event e JOIN knowledge k ON k.id=e.knowledge_id "
                         "WHERE k.device_id=? AND k.lens_id IS ? ORDER BY e.id", (device_id, lens_id)):
        events.setdefault(e["knowledge_id"], []).append(e)
    summaries = model.knowledge_summaries(store, device_id, lens_id)
    return [get(store, kid, summaries, events.get(kid, [])) for kid in ids]


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
