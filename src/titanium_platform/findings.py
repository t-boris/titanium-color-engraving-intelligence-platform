"""Analysis of the accumulated work (REQ-022): what improved, what is unstable, what looks anomalous, where evidence is
missing, and what the AI researcher only supposes.

A run reads the accepted, immutable observations and what is derived from them (knowledge, target checks, research
insights) and writes only its own records: ``analysis_run`` (when, why, its inputs and the recipe figures it will be compared
with next time) and ``finding`` (one row per conclusion). Earlier runs are never changed. A finding has a stable key, so the
same conclusion can be followed across runs: its history is the findings of that key in every run. Each finding says what
supports it (observation, photograph, knowledge, target, plan or research ids), what it compares, how many independent
engravings and photographs it rests on, how uncertain it is, and its basis: measured, an exploratory anomaly, or a hypothesis
of the AI researcher, which is never shown as a measured conclusion.

Kinds (each finding names one laser + lens partition, DEC-063, and, where known, its titanium stock and task; the task of a
recipe is the task of its observations as ``tasks.of_observation`` reads it: the one stated when it was accepted, else the one
its layer implies):
  improvement  the expected colour error of a recipe fell since the previous run; a recipe is validated or approved for
               production; a registered target colour is reached within the saved delta E tolerance
  unstable     the repeats of a recipe vary more than the saved variance threshold; a knowledge entry is questioned
  anomaly      an observation far from its recipe's mean: beyond the saved delta E tolerance when one is saved, else more
               than three standard deviations of the recipe's other engravings (when two or more give one)
  gap          a task on a titanium stock with a laser and lens that has no accepted evidence; a registered target colour
               not reached; recipes that rest on a single independent engraving
  hypothesis   an insight saved by the AI researcher (DEC-064)

Runs are made after every acceptance, on demand and, when the operator sets an interval, by a scheduler thread of the app.
Two runs of one database never overlap.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
from datetime import datetime, timedelta, timezone

import numpy as np

from . import color, designer, devices, exclusions, ingest, model, setup as su, tasks
from .db import Store, now

KINDS = ("improvement", "unstable", "anomaly", "gap", "hypothesis")
TRIGGERS = ("acceptance", "manual", "schedule", "recheck", "operator")
STATES = ("attention", "acknowledged", "hidden")
SORTS = ("important", "newest", "delta", "setup")
MARK_ACTIONS = ("acknowledge", "hide", "reopen", "pin", "unpin", "note")
CHANGE_DELTA_E = 1.0          # a hidden or acknowledged finding returns when its ΔE moves by this much (about the smallest visible difference)
# the tasks a coverage gap is looked for: those a LightBurn mode implies, so a photographed layer can show each of them
TASKS = tuple(key for key, task in tasks.TASKS.items() if task.get("lightburn_modes"))
INTERVAL_SETTING = "analysis_interval_hours"
MAX_INTERVAL_HOURS = 24 * 365
POLL_SECONDS = 60.0
ANOMALY_SD = 3.0
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(store: Store) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(store.path.resolve()), threading.Lock())


def _entry_id(device_id: int, lens_id: int | None, key: str) -> str:
    return f"{device_id}:{'unknown' if lens_id is None else lens_id}:{hashlib.sha256(key.encode()).hexdigest()[:16]}"


def _stock_key(key: str) -> str:
    """The titanium stock part of a recipe key (model.observation_key): a stock record, a described stock, or none."""
    return key.split("|ti:", 1)[1] if "|ti:" in key else "none"


# -- names as they are when the run is made (a finding keeps them, like the plates keep their lens) ------------------------
class _Names:
    def __init__(self, store: Store):
        self.devices = {r["id"]: devices.display_title(r["name"], r["serial"]) for r in store.query("SELECT id,name,serial FROM laser_device")}
        self.lenses = {r["id"]: dict(r) for r in store.query("SELECT id,name,focal_length_mm FROM lens")}
        self.materials = {r["id"]: dict(r) for r in store.query("SELECT id,name,grade,batch FROM material_profile")}

    def context(self, device_id, lens_id, material_id, task, stock: dict | None = None) -> dict:
        return {"device_id": device_id, "device": self.devices.get(device_id), "lens_id": lens_id,
                "lens": self.lenses.get(lens_id) if lens_id is not None else None, "material_id": material_id,
                "stock": self.materials.get(material_id) if material_id is not None else stock, "task": task}


def _stock_of_summary(s: dict) -> tuple[int | None, dict | None]:
    g = (s.get("context_groups") or [{}])[0]
    described = {k: g.get(k) for k in ("titanium_name", "titanium_grade", "batch") if g.get(k) is not None}
    return g.get("material_id"), ({"name": described.get("titanium_name"), "grade": described.get("titanium_grade"),
                                   "batch": described.get("batch")} if described else None)


def _samples(s: dict, pair_of: dict[int, int]) -> dict:
    return {"independent_engravings": s["independent_engravings"], "engravings": s["engravings"],
            "photographs": len({pair_of[i] for i in s["observation_ids"] if i in pair_of}), "observations": s["observations"]}


def _uncertainty(s: dict) -> dict:
    return {"assessed": s["stability"]["assessed"], "variance": s["stability"]["variance"], "max_deviation": s["stability"]["max_deviation"],
            "expected_delta_e": s["expected_delta_e"], "confidence": s["confidence"],
            "rig_mean_delta_e": s["rig_repeatability"]["mean_delta_e"]}


def _evidence(s: dict, pair_of: dict[int, int], knowledge_id: int | None) -> dict:
    return {"observation_ids": s["observation_ids"], "pair_ids": sorted({pair_of[i] for i in s["observation_ids"] if i in pair_of}),
            "knowledge_id": knowledge_id}


def _recipe(s: dict) -> dict:
    """What a finding shows of a recipe: its settings and measured mean colour."""
    keep = ("power", "frequency", "speed", "pulse_width", "line_interval", "passes", "layer_type")
    return {"key": s["key"], "parameters": {k: s["parameters"].get(k) for k in keep}, "lab": s["lab"]}


# -- one run --------------------------------------------------------------------------------------------------------------
def run_analysis(store: Store, trigger: str, *, blocking: bool = True) -> dict | None:
    """Analyse everything accepted so far and keep the result as a new run; earlier runs stay as they are. Returns the run,
    or None when ``blocking`` is false and another run of this database is in progress."""
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown analysis trigger {trigger}")
    lock = _lock(store)
    if not lock.acquire(blocking=blocking):
        return None
    try:
        previous = store.one("SELECT * FROM analysis_run ORDER BY id DESC LIMIT 1")
        found, summary = _analyse(store, previous)
        with store.transaction():
            run_id = store.execute("INSERT INTO analysis_run(at,trigger,summary_json) VALUES (?,?,?)",
                                   (now(), trigger, json.dumps(summary))).lastrowid
            for f in found:
                store.execute("INSERT INTO finding(run_id,key,kind,device_id,lens_id,material_id,task,data_json) VALUES (?,?,?,?,?,?,?,?)",
                              (run_id, f["key"], f["kind"], f["device_id"], f["lens_id"], f["material_id"], f["task"], json.dumps(f["data"])))
        return get_run(store, run_id)
    finally:
        lock.release()


def after_acceptance(store: Store) -> dict | None:
    """What follows an accepted photograph (REQ-022 AC1): the proposals whose plates it completes are done, then a run.
    The acceptance is committed already, so a failing analysis is recorded in the audit instead of undoing it."""
    try:
        designer.reconcile_statuses(store)
        return run_analysis(store, "acceptance")
    except Exception as exc:          # the next run recalculates everything; the operator's acceptance stands
        store.audit("analysis_failed", trigger="acceptance", error=f"{type(exc).__name__}: {exc}")
        return None


def _partitions(store: Store) -> list[tuple[int, int | None]]:
    rows = store.query("SELECT DISTINCT o.device_id, o.lens_id FROM observation o JOIN pair p ON p.id=o.pair_id WHERE p.status='Accepted' "
                       "UNION SELECT device_id, lens_id FROM target_color UNION SELECT device_id, lens_id FROM knowledge")
    return sorted({(r["device_id"], r["lens_id"]) for r in rows}, key=lambda dl: (dl[0], -1 if dl[1] is None else dl[1]))


def _analyse(store: Store, previous) -> tuple[list[dict], dict]:
    names = _Names(store)
    originals = ingest.original_pairs(store)
    before = json.loads(previous["summary_json"]) if previous else {}
    previous_entries = before.get("entries", {})
    previous_keys = {r["key"] for r in store.query("SELECT key FROM finding WHERE run_id=?", (previous["id"],))} if previous else set()
    out: list[dict] = []
    entries: dict[str, dict] = {}
    rules_used: dict[str, dict] = {}
    unset_rules: list[dict] = []          # partitions where a saved threshold is missing, so a kind of finding cannot be judged
    eligible = 0
    for device_id, lens_id in _partitions(store):
        rules = su.get_rules(store, device_id, lens_id)
        rules_used[su.setup_key(device_id, lens_id)] = rules
        missing = [k for k in ("variance_threshold", "delta_tolerance") if rules[k] is None]
        if missing:
            unset_rules.append({**names.context(device_id, lens_id, None, None), "missing": missing})
        obs = model.eligible_observations(store, device_id, lens_id)
        eligible += len(obs)
        summaries = model.knowledge_summaries(store, device_id, lens_id)
        rows = {r["parameters_key"]: r for r in store.query("SELECT * FROM knowledge WHERE device_id=? AND lens_id IS ?", (device_id, lens_id))}
        partition = {"device_id": device_id, "lens_id": lens_id, "rules": rules, "names": names, "rows": rows,
                     "pair_of": {o["id"]: o["pair_id"] for o in obs}, "previous": previous, "previous_entries": previous_entries,
                     "original_of": originals}
        for key, s in sorted(summaries.items()):
            eid = _entry_id(device_id, lens_id, key)
            if s["available"]:
                entries[eid] = {"expected_delta_e": s["expected_delta_e"], "variance": s["stability"]["variance"],
                                "independent_engravings": s["independent_engravings"]}
            out += _recipe_findings(store, partition, key, s, eid)
        for key, row in sorted(rows.items()):
            if row["questioned"]:
                out.append(_questioned(partition, key, row, summaries.get(key)))
        out += _anomalies(partition, obs, summaries)
        out += _single_engravings(partition, summaries)
        out += _targets(store, partition)
    out += _coverage(store, names)
    out += _hypotheses(store, names)
    for f in out:
        f["data"]["new"] = f["key"] not in previous_keys
    counts = {k: sum(1 for f in out if f["kind"] == k) for k in KINDS}
    inputs = {"accepted_pairs": store.one("SELECT COUNT(*) AS n FROM pair WHERE status='Accepted'")["n"], "eligible_observations": eligible,
              "last_observation_id": store.one("SELECT MAX(id) AS n FROM observation")["n"],
              "knowledge_entries": store.one("SELECT COUNT(*) AS n FROM knowledge")["n"],
              "targets": store.one("SELECT COUNT(*) AS n FROM target_color")["n"],
              "insights": store.one("SELECT COUNT(*) AS n FROM research_insight")["n"], "rules": rules_used, "unset_rules": unset_rules}
    return out, {"inputs": inputs, "counts": counts, "entries": entries, "previous_run_id": previous["id"] if previous else None}


def _finding(kind: str, key: str, partition: dict, material_id, task, data: dict, stock: dict | None = None) -> dict:
    data["context"] = partition["names"].context(partition["device_id"], partition["lens_id"], material_id, task, stock)
    data.setdefault("limitations", [])
    return {"kind": kind, "key": key, "device_id": partition["device_id"], "lens_id": partition["lens_id"], "material_id": material_id,
            "task": task, "data": data}


def _recipe_findings(store: Store, partition: dict, key: str, s: dict, eid: str) -> list[dict]:
    """Improvements and instability of one recipe."""
    out = []
    rules, row = partition["rules"], partition["rows"].get(key)
    material_id, stock = _stock_of_summary(s)
    task = s["task"]["kind"]

    def common() -> dict:
        return {"samples": _samples(s, partition["pair_of"]), "uncertainty": _uncertainty(s), "recipe": _recipe(s),
                "evidence": _evidence(s, partition["pair_of"], row["id"] if row else None)}

    old = partition["previous_entries"].get(eid)
    if s["available"] and old and old.get("expected_delta_e") is not None and round(s["expected_delta_e"], 2) < round(old["expected_delta_e"], 2):
        data = {"subkind": "error_reduced", "basis": "measured", **common(),
                "statement": (f"the expected colour error of this recipe fell from {old['expected_delta_e']:.2f} to {s['expected_delta_e']:.2f} ΔE "
                              f"since the previous analysis ({s['independent_engravings']} independent engravings)"),
                "compares": {"previous_run_id": partition["previous"]["id"], "before": old,
                             "after": {"expected_delta_e": s["expected_delta_e"], "variance": s["stability"]["variance"],
                                       "independent_engravings": s["independent_engravings"]}}}
        out.append(_finding("improvement", f"recipe:{eid}:error", partition, material_id, task, data, stock))
    if row is not None and row["stage"] in ("validated", "production") and not row["questioned"] and s["available"]:
        event = store.one("SELECT at,type FROM knowledge_event WHERE knowledge_id=? AND to_stage=? AND type IN ('promoted','approved') "
                          "ORDER BY id DESC LIMIT 1", (row["id"], row["stage"]))
        production = row["stage"] == "production"
        data = {"subkind": "validated", "basis": "measured", **common(),
                "statement": (f"recipe {'approved for production' if production else 'validated'}: {s['independent_engravings']} independent "
                              f"engravings, variance {s['stability']['variance']:.2f} ΔE², expected error {s['expected_delta_e']:.2f} ΔE"),
                "compares": {"stage": row["stage"], "since": event["at"] if event else None,
                             "repeat_threshold": rules["repeat_threshold"], "variance_threshold": rules["variance_threshold"],
                             "delta_tolerance": rules["delta_tolerance"]}}
        out.append(_finding("improvement", f"recipe:{eid}:validated", partition, material_id, task, data, stock))
    threshold = rules["variance_threshold"]
    if threshold is not None and s["stability"]["assessed"] and s["stability"]["variance"] > threshold:
        data = {"subkind": "variance", "basis": "measured", **common(),
                "statement": (f"repeat engravings of this recipe vary by {s['stability']['variance']:.2f} ΔE², above the saved variance "
                              f"threshold {threshold:g}"),
                "compares": {"variance": s["stability"]["variance"], "variance_threshold": threshold}}
        out.append(_finding("unstable", f"recipe:{eid}:variance", partition, material_id, task, data, stock))
    return out


def _questioned(partition: dict, key: str, row, s: dict | None) -> dict:
    """A questioned knowledge entry, also when a removed photograph took all its evidence away (DEC-066 item 3)."""
    doubt = json.loads(row["doubt_json"] or "{}")
    parameters = json.loads(row["parameters_json"])
    material_id, stock = _stock_of_summary(s) if s else (None, None)
    data = {"subkind": "questioned", "basis": "measured", "statement": f"this knowledge entry is questioned: {doubt.get('reason', '')}",
            "samples": _samples(s, partition["pair_of"]) if s else {"independent_engravings": 0, "engravings": 0, "photographs": 0, "observations": 0},
            "uncertainty": _uncertainty(s) if s else {"assessed": False},
            "recipe": _recipe(s) if s else {"key": key, "parameters": parameters, "lab": None},
            "evidence": _evidence(s, partition["pair_of"], row["id"]) if s else {"observation_ids": [], "pair_ids": [], "knowledge_id": row["id"]},
            "compares": {"stage": row["stage"], "doubt_observation_ids": doubt.get("observation_ids", [])}}
    return _finding("unstable", f"recipe:{_entry_id(partition['device_id'], partition['lens_id'], key)}:questioned", partition, material_id,
                    s["task"]["kind"] if s else tasks.of_key(key, parameters), data, stock)


def _anomalies(partition: dict, obs: list[dict], summaries: dict[str, dict]) -> list[dict]:
    """Observations far from the agreed colour of their recipe (exploratory: one observation against its recipe, DEC-083)."""
    out = []
    tolerance = partition["rules"]["delta_tolerance"]
    groups: dict[str, list[dict]] = {}
    for o in obs:
        groups.setdefault(model.observation_key(o["parameters"], o["context"], o["task"]), []).append(o)
    taken: dict[str, int] = {}
    for key, members in sorted(groups.items()):
        s = summaries[key]
        if len(members) < 2:
            continue
        per_engraving = {e: np.mean([o["lab"] for o in members if o["engraving_id"] == e], axis=0) for e in {o["engraving_id"] for o in members}}
        for o in members:
            limitations: list[str] = []
            if tolerance is not None:
                reference, sd = np.asarray(s["lab"]), None
                distance = color.delta_e(o["lab"], reference)
                if distance <= tolerance:
                    continue
                statement = f"observation {o['id']} lies {distance:.1f} ΔE from the agreed colour of its recipe, beyond the saved tolerance {tolerance:g}"
            else:
                others = [lab for e, lab in per_engraving.items() if e != o["engraving_id"]]
                if len(others) < 2:
                    continue
                reference = np.mean(others, axis=0)
                sd = math.sqrt(float(np.var(others, axis=0, ddof=1).sum()))
                distance = color.delta_e(o["lab"], reference)
                if sd <= 0 or distance <= ANOMALY_SD * sd:
                    continue
                statement = (f"observation {o['id']} lies {distance:.1f} ΔE from the mean of the other engravings of its recipe, more than "
                             f"three standard deviations ({sd:.2f} ΔE)")
                limitations.append("the standard deviation comes from few engravings: it is a rough scale, not a measured spread")
            limitations.append("an anomaly is one observation against its recipe: check its photograph and alignment before drawing a conclusion")
            material_id, stock = _stock_of_summary(s)
            data = {"subkind": "observation", "basis": "exploratory", "statement": statement, "limitations": limitations,
                    "samples": _samples(s, partition["pair_of"]), "uncertainty": _uncertainty(s), "recipe": _recipe(s),
                    "evidence": {"observation_ids": [o["id"]], "pair_ids": [o["pair_id"]],
                                 "recipe_observation_ids": s["observation_ids"],
                                 "knowledge_id": partition["rows"][key]["id"] if key in partition["rows"] else None},
                    "compares": {"observation_lab": o["lab"], "reference_lab": [float(v) for v in reference], "delta_e": distance,
                                 "rule": "tolerance" if tolerance is not None else "three_sd", "tolerance": tolerance, "sd": sd}}
            # the photograph (its first measurement) and the layer, so a re-measure keeps the operator's mark (DEC-002); a photograph
            # accepted twice by an old version has two observations of a layer, numbered in the order they were made
            base = f"anomaly:photo:{partition['original_of'].get(o['pair_id'], o['pair_id'])}:{o['layer_index']}"
            taken[base] = taken.get(base, 0) + 1
            fkey = base if taken[base] == 1 else f"{base}:{taken[base]}"
            out.append(_finding("anomaly", fkey, partition, material_id, s["task"]["kind"], data, stock))
    return out


def _single_engravings(partition: dict, summaries: dict[str, dict]) -> list[dict]:
    """One gap per stock and task: the recipes that rest on a single independent engraving."""
    rules = partition["rules"]
    groups: dict[tuple[str, str], list[dict]] = {}
    for key, s in sorted(summaries.items()):
        if s["independent_engravings"] <= 1:
            groups.setdefault((_stock_key(key), s["task"]["kind"]), []).append(s)
    validates = rules["criteria_agreed"] and rules["repeat_threshold"] is not None and max(2, rules["repeat_threshold"]) == 2
    out = []
    for (stock_key, task), members in sorted(groups.items()):
        material_id, stock = _stock_of_summary(members[0])
        # a repeat is a designer plate, so only recipes of its task with all six settings recorded can be repeated
        repeatable = [s for s in members if task == designer.PLATE_TASK and all(s["parameters"].get(k) is not None for k in
                                                ("power", "frequency", "speed", "pulse_width", "line_interval", "passes"))]
        needed = None if not rules["criteria_agreed"] or rules["repeat_threshold"] is None else max(2, rules["repeat_threshold"]) - 1
        limitations: list[str] = []
        if not rules["criteria_agreed"]:
            limitations.append("the evaluation criteria are not agreed for this laser and lens: no recipe is validated automatically")
        data = {"subkind": "single_engraving", "basis": "measured",
                "statement": (f"{len(members)} recipes rest on a single independent engraving: a repeat would let their stability be assessed"
                              f"{' and validate them under the saved criteria' if validates else ''}"),
                "limitations": limitations,
                "samples": {"recipes": len(members), "independent_engravings": sum(s["independent_engravings"] for s in members),
                            "photographs": len({partition["pair_of"][i] for s in members for i in s["observation_ids"] if i in partition["pair_of"]}),
                            "observations": sum(s["observations"] for s in members)},
                "uncertainty": {"assessed": False},
                "evidence": {"observation_ids": sorted(i for s in members for i in s["observation_ids"]),
                             "pair_ids": sorted({partition["pair_of"][i] for s in members for i in s["observation_ids"] if i in partition["pair_of"]}),
                             "knowledge_ids": sorted(partition["rows"][s["key"]]["id"] for s in members if s["key"] in partition["rows"])},
                "compares": {"engravings_needed_for_validation": needed, "recipes": [_recipe(s) for s in members],
                             "repeatable_keys": [s["key"] for s in repeatable]},
                "proposable": bool(repeatable)}
        key = f"gap:single:{partition['device_id']}:{partition['lens_id'] or 'unknown'}:{stock_key}:{task}"
        out.append(_finding("gap", key, partition, material_id, task, data, stock))
    return out


def _targets(store: Store, partition: dict) -> list[dict]:
    """A registered target colour reached within the saved tolerance (improvement) or not reached (gap); one key for both, so
    its history shows when it was reached."""
    out = []
    tolerance = partition["rules"]["delta_tolerance"]
    for t in designer.open_targets(store, partition["device_id"], partition["lens_id"]):
        checks = t["checks"]
        comparable = [c for c in checks if c["comparable"] and c["delta_e"] is not None]
        best = min(comparable, key=lambda c: (c["delta_e"], c["observation_id"])) if comparable else None
        reached = best is not None and tolerance is not None and best["delta_e"] <= tolerance
        tid = t["id"]
        if reached:
            statement = f"target colour {tid} is reached: a plate cell measured {best['delta_e']:.1f} ΔE from it, within the tolerance {tolerance:g}"
        elif not checks:
            statement = f"target colour {tid} is not reached yet: no plate cell made for it has been measured"
        elif best is None:
            statement = (f"target colour {tid} is not reached yet: its cells were measured without a reference chart and cannot be "
                         "compared with it")
        elif tolerance is None:
            statement = (f"target colour {tid} cannot be judged: no ΔE tolerance is saved; the closest measurement is "
                         f"{best['delta_e']:.1f} ΔE away")
        else:
            statement = (f"target colour {tid} is not reached: the closest measurement is {best['delta_e']:.1f} ΔE away, beyond the "
                         f"tolerance {tolerance:g}")
        data = {"subkind": "target_reached" if reached else "target_missing", "basis": "measured", "statement": statement,
                "samples": {"independent_engravings": len({c["pair_id"] for c in comparable}), "photographs": len({c["pair_id"] for c in checks}),
                            "observations": len(checks)},
                "uncertainty": {"assessed": best is not None, "delta_e": best["delta_e"] if best else None, "tolerance": tolerance},
                "evidence": {"target_id": tid, "plan_id": t["source_plan_id"], "proposal_id": t["proposal_id"],
                             "observation_ids": [c["observation_id"] for c in checks], "pair_ids": sorted({c["pair_id"] for c in checks})},
                "compares": {"target_lab": t["lab"], "closest_lab": best["measured_lab"] if best else None,
                             "delta_e": best["delta_e"] if best else None, "tolerance": tolerance},
                "proposable": not reached}
        out.append(_finding("improvement" if reached else "gap", f"target:{tid}", partition, None, designer.PLATE_TASK, data))
    return out


def _coverage(store: Store, names: _Names) -> list[dict]:
    """Tasks on a titanium stock with a laser and a lens record that no accepted test feature covers. The universe is what the
    operator works with: each laser with evidence, its installed lens and the lenses and stocks of its evidence."""
    covered: dict[tuple, dict] = {}
    for r in store.query(f"SELECT o.id,o.pair_id,o.device_id,o.lens_id,o.parameters_json,o.context_json,o.evidence_json,o.task_kind,"
                         f"p.material_id FROM observation o JOIN pair p ON p.id=o.pair_id WHERE p.status='Accepted' AND "
                         f"{model.TEST_FEATURE_SQL} ORDER BY o.id"):
        task = tasks.of_observation(r)["kind"]
        material_id = json.loads(r["context_json"] or "{}").get("material_id") or r["material_id"]
        entry = covered.setdefault((r["device_id"], r["lens_id"], material_id, task), {"observations": 0, "pairs": set()})
        entry["observations"] += 1
        entry["pairs"].add(r["pair_id"])
    out = []
    for device_id in sorted({d for d, _, _, _ in covered}):
        installed = store.one("SELECT lens_id FROM laser_device WHERE id=?", (device_id,))
        lenses = sorted({l for d, l, _, _ in covered if d == device_id and l is not None}
                        | ({installed["lens_id"]} if installed and installed["lens_id"] is not None else set()))
        stocks = sorted({m for d, _, m, _ in covered if d == device_id and m is not None})
        for lens_id in lenses:
            partition = {"device_id": device_id, "lens_id": lens_id, "names": names}
            for material_id in stocks:
                for task in TASKS:
                    if (device_id, lens_id, material_id, task) in covered:
                        continue
                    limitations: list[str] = []
                    limitations.append("coverage counts accepted test features of any measurement; the task of a layer is the one "
                                       "stated for it, else the one its LightBurn mode implies")
                    data = {"subkind": "coverage", "basis": "measured",
                            "statement": f"no accepted evidence for {task} on this titanium with this laser and lens",
                            "limitations": limitations,
                            "samples": {"independent_engravings": 0, "photographs": 0, "observations": 0},
                            "uncertainty": {"assessed": False}, "evidence": {"observation_ids": [], "pair_ids": []},
                            "compares": {"tasks_on_this_stock": sorted(t for d, l, m, t in covered if (d, l, m) == (device_id, lens_id, material_id) and t),
                                         "stocks_with_this_task": sorted(m for d, l, m, t in covered if (d, l, t) == (device_id, lens_id, task) and m is not None),
                                         "lenses_with_this_task": sorted(l for d, l, m, t in covered if (d, m, t) == (device_id, material_id, task) and l is not None),
                                         "names": {"stocks": {str(m): names.materials.get(m) for m in stocks},
                                                   "lenses": {str(l): names.lenses.get(l) for l in lenses}}},
                            "proposable": task == designer.PLATE_TASK}
                    key = f"gap:coverage:{device_id}:{lens_id}:{material_id}:{task}"
                    out.append(_finding("gap", key, partition, material_id, task, data))
    return out


def _hypotheses(store: Store, names: _Names) -> list[dict]:
    """The AI researcher's insights: always hypotheses, whatever confidence it gave them (REQ-022 AC3, DEC-064)."""
    out = []
    for r in store.query("SELECT i.*,s.device_id,s.lens_id,s.material_id FROM research_insight i JOIN research_session s ON s.id=i.session_id "
                         "WHERE s.status!='Deleted' ORDER BY i.id"):
        pair_ids = json.loads(r["evidence_pair_ids_json"])
        marks = ",".join("?" * len(pair_ids))
        pairs = store.query(f"SELECT id,engraving_id,status FROM pair WHERE id IN ({marks})", pair_ids) if pair_ids else []
        active = [p for p in pairs if p["status"] == "Accepted"]
        limitations: list[str] = []
        limitations.append("an insight of the AI researcher is a hypothesis: it is not a measured conclusion until a plate tests it")
        if len(active) < len(pair_ids):
            limitations.append("some photographs it cites are no longer in active use")
        partition = {"device_id": r["device_id"], "lens_id": r["lens_id"], "names": names}
        data = {"subkind": "insight", "basis": "hypothesis", "statement": r["claim"], "limitations": limitations,
                "samples": {"independent_engravings": len({p["engraving_id"] for p in active}), "photographs": len(active),
                            "observations": None},
                "uncertainty": {"assessed": False, "ai_confidence": r["confidence"]},
                "evidence": {"pair_ids": pair_ids, "session_id": r["session_id"], "insight_id": r["id"]},
                "compares": {"purpose": r["purpose"], "ai_confidence": r["confidence"], "saved_at": r["created_at"]}}
        out.append(_finding("hypothesis", f"hypothesis:insight:{r['id']}", partition, r["material_id"],
                            tasks.GOAL_TASK.get(r["purpose"]), data))
    return out


# -- reading runs and findings ----------------------------------------------------------------------------------------------
def _run(row) -> dict:
    summary = json.loads(row["summary_json"])
    return {"id": row["id"], "at": row["at"], "trigger": row["trigger"], "inputs": summary.get("inputs", {}), "counts": summary.get("counts", {}),
            "previous_run_id": summary.get("previous_run_id")}


def get_run(store: Store, run_id: int | None = None) -> dict | None:
    """One run (the latest when ``run_id`` is None), without its findings; None when nothing was analysed yet."""
    row = (store.one("SELECT * FROM analysis_run WHERE id=?", (run_id,)) if run_id is not None
           else store.one("SELECT * FROM analysis_run ORDER BY id DESC LIMIT 1"))
    if row is None and run_id is not None:
        raise KeyError(f"analysis run {run_id} not found")
    return None if row is None else _run(row)


def list_runs(store: Store, limit: int = 50) -> list[dict]:
    return [_run(r) for r in store.query("SELECT * FROM analysis_run ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 500)),))]


def _public(row) -> dict:
    return {"id": row["id"], "run_id": row["run_id"], "key": row["key"], "kind": row["kind"], "device_id": row["device_id"],
            "lens_id": row["lens_id"], "material_id": row["material_id"], "task": row["task"], **json.loads(row["data_json"])}


# -- the operator's marks (DEC-001 of findings-you-can-manage-short-lists-re-check) ----------------------------------------
def deviation(f: dict) -> float | None:
    """The ΔE a finding is about: an observation's or a target's distance, else its recipe's expected error."""
    c, u = f.get("compares") or {}, f.get("uncertainty") or {}
    value = c.get("delta_e") if f.get("subkind") in ("observation", "target_reached", "target_missing") else u.get("expected_delta_e")
    return None if value is None else float(value)


def substance(f: dict) -> dict:
    """What a mark is given for: the kind of conclusion, what it rests on and its ΔE."""
    s = f.get("samples") or {}
    return {"kind": f["kind"], "subkind": f.get("subkind"), "independent_engravings": s.get("independent_engravings"),
            "photographs": s.get("photographs"), "recipes": s.get("recipes"), "delta_e": deviation(f)}


def changed_since(snapshot: dict, now_: dict) -> bool:
    """New data for the finding: another kind, a new engraving or photograph, or a ΔE moved by CHANGE_DELTA_E or more."""
    if any(snapshot.get(k) != now_.get(k) for k in ("kind", "subkind", "independent_engravings", "photographs", "recipes")):
        return True
    before, after = snapshot.get("delta_e"), now_.get("delta_e")
    if (before is None) != (after is None):
        return True
    return before is not None and abs(after - before) >= CHANGE_DELTA_E


def _marks(store: Store) -> dict[str, dict]:
    return {r["key"]: dict(r) for r in store.query("SELECT * FROM finding_mark")}


def _with_mark(f: dict, row: dict | None) -> dict:
    """The finding with its mark, its state now («учтено» or «скрыто» only while it is the finding they were given for) and the ΔE it is
    about, as the list shows and sorts it."""
    mark = {"status": None, "pinned": False, "note": None, "status_at": None, "changed": False}
    state = "attention"
    if row is not None:
        mark.update(pinned=bool(row["pinned"]), note=row["note"], status=row["status"], status_at=row["status_at"])
        if row["status"]:
            if changed_since(json.loads(row["snapshot_json"] or "{}"), substance(f)):
                mark["changed"] = True
            else:
                state = row["status"]
    return f | {"mark": mark, "state": state, "deviation": deviation(f)}


def mark(store: Store, finding_id: int, action: str, note: str | None = None) -> dict:
    """The operator acknowledges, hides, reopens, pins, unpins or annotates a finding; kept by its key, written to the audit."""
    if action not in MARK_ACTIONS:
        raise su.ValidationError(f"unknown finding action {action}")
    row = store.one("SELECT * FROM finding WHERE id=?", (finding_id,))
    if row is None:
        raise KeyError(f"finding {finding_id} not found")
    f = _public(row)
    old = store.one("SELECT * FROM finding_mark WHERE key=?", (f["key"],))
    current = dict(old) if old else {"key": f["key"], "status": None, "pinned": 0, "note": None, "snapshot_json": None, "status_at": None}
    at = now()
    if action in ("acknowledge", "hide"):
        current.update(status="acknowledged" if action == "acknowledge" else "hidden", snapshot_json=json.dumps(substance(f)), status_at=at)
    elif action == "reopen":
        current.update(status=None, snapshot_json=None, status_at=at)
    elif action in ("pin", "unpin"):
        current["pinned"] = 1 if action == "pin" else 0
    else:
        current["note"] = (note or "").strip()[:2000] or None
    with store.transaction():
        store.execute("INSERT INTO finding_mark(key,status,pinned,note,snapshot_json,status_at,updated_at) VALUES (?,?,?,?,?,?,?) "
                      "ON CONFLICT(key) DO UPDATE SET status=excluded.status, pinned=excluded.pinned, note=excluded.note, "
                      "snapshot_json=excluded.snapshot_json, status_at=excluded.status_at, updated_at=excluded.updated_at",
                      (f["key"], current["status"], current["pinned"], current["note"], current["snapshot_json"], current["status_at"], at))
        store.audit("finding_marked", finding_id=finding_id, key=f["key"], mark=action, status=current["status"],
                    pinned=bool(current["pinned"]), note=current["note"])
    return _with_mark(f, store.one("SELECT * FROM finding_mark WHERE key=?", (f["key"],)))["mark"]


def get_finding(store: Store, finding_id: int) -> dict:
    """One finding with its mark and state (a link to it opens it, REQ-002) and what can be done about it."""
    row = store.one("SELECT * FROM finding WHERE id=?", (finding_id,))
    if row is None:
        raise KeyError(f"finding {finding_id} not found")
    f = _public(row)
    f["setup"] = su.setup_key(f["device_id"], f["lens_id"])
    f["stock_key"] = "unknown" if f["material_id"] is None else str(f["material_id"])
    latest = get_run(store)
    f["remedies"] = remedies(f) if latest is not None and latest["id"] == f["run_id"] else []
    return _with_mark(f, store.one("SELECT * FROM finding_mark WHERE key=?", (f["key"],)))


# -- what can be done about a finding (feature act-on-findings) -------------------------------------------------------------------
REMEDIES = ("exclude_measurement", "count_from_latest")       # decided here; «Перемерить фото» and «Подтвердить запись» have their own routes


def remedies(f: dict) -> list[dict]:
    """The actions a finding of the latest run offers on its substance, in the order «Что сделать» shows them: take the measurement
    out and re-measure its photograph (an anomaly), count the recipe from its newest engraving (an anomaly, an unstable or questioned
    recipe of two or more engravings), confirm a questioned knowledge entry. A gap keeps its «Предложить эксперимент»."""
    sub, evidence = f.get("subkind"), f.get("evidence") or {}
    out = []
    if f["kind"] == "anomaly" and sub == "observation" and evidence.get("observation_ids"):
        out.append({"action": "exclude_measurement", "observation_id": evidence["observation_ids"][0]})
        out.append({"action": "remeasure", "pair_id": evidence["pair_ids"][0]})
    if sub in ("observation", "variance", "questioned") and ((f.get("samples") or {}).get("engravings") or 0) >= 2 \
            and (f.get("recipe") or {}).get("key"):
        out.append({"action": "count_from_latest"})
    if sub == "questioned" and evidence.get("knowledge_id") is not None:
        out.append({"action": "confirm_questioned", "knowledge_id": evidence["knowledge_id"]})
    return out


def remedy(store: Store, finding_id: int, action: str, note: str | None = None, confirm: bool = False) -> dict:
    """A remedy of a finding: without ``confirm`` what it would change (REQ-004), with it the decision, made and recalculated once."""
    f = get_finding(store, finding_id)
    offered = {r["action"]: r for r in f["remedies"]}
    if action not in REMEDIES or action not in offered:
        raise su.ValidationError(f"this finding offers no action {action}")
    if action == "exclude_measurement":
        observation_id = offered[action]["observation_id"]
        if not confirm:
            return exclusions.preview_measurement(store, observation_id)
        return exclusions.exclude_measurement(store, observation_id, note, f["key"])
    key = f["recipe"]["key"]
    if not confirm:
        return exclusions.preview_latest(store, f["device_id"], f["lens_id"], key)
    return exclusions.count_from_latest(store, f["device_id"], f["lens_id"], key, note, f["key"])


_KIND_RANK = {"anomaly": 0, "unstable": 1, "gap": 2, "hypothesis": 3, "improvement": 4}


def _same_finding(store: Store):
    """A key as today's runs write it: a run before DEC-002 named an anomaly by its observation, today it is the photograph (its first
    measurement) and the layer."""
    originals = ingest.original_pairs(store)

    def key(k: str) -> str:
        if not k.startswith("anomaly:observation:"):
            return k
        o = store.one("SELECT pair_id, layer_index FROM observation WHERE id=?", (int(k.rsplit(":", 1)[1]),))
        return k if o is None else f"anomaly:photo:{originals.get(o['pair_id'], o['pair_id'])}:{o['layer_index']}"
    return key


def compare_runs(store: Store, before_id: int | None, after_id: int, listed: int = 60) -> dict:
    """What a run changed against an earlier one, by finding: appeared, gone, and changed (another kind, new evidence or ΔE moved by
    CHANGE_DELTA_E, as a mark would lapse); at most ``listed`` of each are named, the counts are whole."""
    same = _same_finding(store)
    load = lambda run_id: {same(r["key"]): _public(r) for r in store.query("SELECT * FROM finding WHERE run_id=?", (run_id,))}  # noqa: E731
    before, after = (load(before_id) if before_id is not None else {}), load(after_id)
    brief = lambda f: {"id": f["id"], "kind": f["kind"], "statement": f["statement"]}  # noqa: E731
    order = lambda f: (_KIND_RANK.get(f["kind"], 9), f["statement"])  # noqa: E731
    appeared = sorted((after[k] for k in after.keys() - before.keys()), key=order)
    gone = sorted((before[k] for k in before.keys() - after.keys()), key=order)
    changed = sorted((after[k] for k in after.keys() & before.keys() if changed_since(substance(before[k]), substance(after[k]))), key=order)
    return {"before_run_id": before_id, "after_run_id": after_id, "before": len(before), "after": len(after),
            "counts": {"appeared": len(appeared), "gone": len(gone), "changed": len(changed)},
            "appeared": [brief(f) for f in appeared[:listed]], "gone": [brief(f) for f in gone[:listed]],
            "changed": [brief(f) | {"was": brief(before[same(f["key"])])} for f in changed[:listed]]}


def _sort_key(sort: str, first_seen: dict[str, int]):
    if sort == "newest":
        return lambda f: (not f["mark"]["pinned"], -first_seen.get(f["key"], 0), f["id"])
    if sort == "delta":
        return lambda f: (not f["mark"]["pinned"], deviation(f) is None, -(deviation(f) or 0), f["id"])
    if sort == "setup":
        return lambda f: (not f["mark"]["pinned"], f["setup"], f["stock_key"], _KIND_RANK.get(f["kind"], 9), f["id"])
    return lambda f: (not f["mark"]["pinned"], not (f.get("new") or f["mark"]["changed"]), _KIND_RANK.get(f["kind"], 9),
                      -(deviation(f) or 0), f["id"])


def findings_of(store: Store, run_id: int, kind: str | None = None, task: str | None = None, setup: str | None = None,
                material: str | None = None, state: str | None = None, sort: str | None = None, offset: int = 0,
                limit: int | None = None) -> dict:
    """The findings of one run with the operator's marks, filtered by state (attention, acknowledged, hidden), kind, task, laser +
    lens (``laser:<id>/lens:<id|unknown>``) and titanium stock (its record id or ``unknown``), sorted (``important``: pinned, then new
    or changed, then by kind and deviation; ``newest``: the run a finding first appeared in; ``delta``: largest ΔE; ``setup``) and
    paged. Returns the page, ``matched`` (all that pass the filters), ``total`` (the run's findings), ``counts`` per state and per
    kind (each with the other filters applied, as a filter would show them) and the values each filter can take in this run."""
    if state is not None and state not in STATES:
        raise su.ValidationError(f"unknown finding state {state}")
    if sort is not None and sort not in SORTS:
        raise su.ValidationError(f"unknown finding order {sort}")
    run = get_run(store, run_id)
    latest = get_run(store)["id"] == run_id         # a remedy acts on the data as it is now: offered on the latest run only
    marks = _marks(store)
    rows = [_with_mark(_public(r), marks.get(r["key"])) for r in store.query("SELECT * FROM finding WHERE run_id=? ORDER BY id", (run_id,))]
    setups, stocks = {}, {}
    for f in rows:
        f["remedies"] = remedies(f) if latest else []
        f["setup"] = su.setup_key(f["device_id"], f["lens_id"])
        f["stock_key"] = "unknown" if f["material_id"] is None else str(f["material_id"])
        setups.setdefault(f["setup"], {"key": f["setup"], "device": f["context"]["device"], "lens": f["context"]["lens"]})
        stocks.setdefault(f["stock_key"], {"key": f["stock_key"], "stock": f["context"]["stock"]})
    options = {"kinds": [k for k in KINDS if any(f["kind"] == k for f in rows)], "tasks": sorted({f["task"] for f in rows if f["task"]}),
               "setups": [setups[k] for k in sorted(setups)], "stocks": [stocks[k] for k in sorted(stocks)]}
    test = {"state": lambda f: state is None or f["state"] == state, "kind": lambda f: kind is None or f["kind"] == kind,
            "task": lambda f: task is None or f["task"] == task, "setup": lambda f: setup is None or f["setup"] == setup,
            "material": lambda f: material is None or f["stock_key"] == material}
    passes = lambda f, but=None: all(fn(f) for name, fn in test.items() if name != but)  # noqa: E731
    shown = [f for f in rows if passes(f)]
    counts = {"state": {"": sum(1 for f in rows if passes(f, "state"))} | {s: sum(1 for f in rows if passes(f, "state") and f["state"] == s) for s in STATES},
              "kind": {"": sum(1 for f in rows if passes(f, "kind"))} | {k: sum(1 for f in rows if passes(f, "kind") and f["kind"] == k) for k in KINDS}}
    if sort is not None or limit is not None:
        keys = sorted({f["key"] for f in shown})
        first_seen = {}
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            first_seen |= {r["key"]: r["first"] for r in store.query(
                f"SELECT key, MIN(run_id) AS first FROM finding WHERE key IN ({','.join('?' * len(chunk))}) GROUP BY key", chunk)}
        for f in shown:
            f["first_run_id"] = first_seen.get(f["key"])
        shown.sort(key=_sort_key(sort or "important", first_seen))
    matched = len(shown)
    if limit is not None:
        shown = shown[max(0, int(offset)):max(0, int(offset)) + max(1, min(int(limit), 200))]
    return {"run": run, "findings": shown, "matched": matched, "total": len(rows), "counts": counts, "options": options}


def history(store: Store, finding_id: int) -> list[dict]:
    """The same finding in every run that had it, newest first, each with its run's date and trigger (REQ-022 AC6)."""
    row = store.one("SELECT key FROM finding WHERE id=?", (finding_id,))
    if row is None:
        raise KeyError(f"finding {finding_id} not found")
    return [_public(r) | {"run_at": r["at"], "run_trigger": r["trigger"]} for r in store.query(
        "SELECT f.*, r.at, r.trigger FROM finding f JOIN analysis_run r ON r.id=f.run_id WHERE f.key=? ORDER BY f.run_id DESC", (row["key"],))]


# -- a proposal for a gap ----------------------------------------------------------------------------------------------------
def _measured_group(store: Store, device_id: int, lens_id: int | None) -> dict:
    """The job settings (pulse width, line interval, passes) with the most eligible observations of the designer's task on this
    laser and lens: the settings a proposal for a gap keeps, taken from the measurements, never filled in (DEC-043)."""
    counts: dict[tuple, int] = {}
    for s in model.knowledge_summaries(store, device_id, lens_id).values():
        group = tuple(s["parameters"].get(k) for k in designer.GROUP_KEYS)
        if None not in group and s["task"]["kind"] == designer.PLATE_TASK:
            counts[group] = counts.get(group, 0) + s["observations"]
    if not counts:
        raise designer.DesignerError("no filled regions are measured on this laser and lens yet: choose the pulse width, line interval "
                                     "and passes in the experiment designer")
    best = min(counts, key=lambda g: (-counts[g], g))
    return dict(zip(designer.GROUP_KEYS, best))


def propose_for(store: Store, finding_id: int, seed: int = 1729, size: int = designer.DEFAULT_SIZE) -> dict:
    """A proposal of the Experiment Designer for a gap finding, linked to it: a target colour not reached is served by the
    designer's target phase, fill evidence missing on a stock by a proposal of that stock, recipes on a single engraving by a
    plate that repeats them. Other findings ask for an experiment the designer does not plan."""
    row = store.one("SELECT * FROM finding WHERE id=?", (finding_id,))
    if row is None:
        raise KeyError(f"finding {finding_id} not found")
    f = _public(row)
    if f["kind"] != "gap" or not f.get("proposable"):
        raise designer.DesignerError("the experiment designer plans fill plates for a target colour, missing fill evidence or a repeat; "
                                     "this finding asks for another kind of test")
    device_id, lens_id = f["device_id"], f["lens_id"]
    if f["subkind"] == "single_engraving":
        prop = designer.propose_repeats(store, device_id, lens_id, f["compares"]["repeatable_keys"], size=size, material_id=f["material_id"])
    else:
        group = None
        if f["subkind"] == "target_missing" and f["evidence"].get("proposal_id"):
            group = designer.get_proposal(store, f["evidence"]["proposal_id"]).get("group")
        group = group or _measured_group(store, device_id, lens_id)
        prop = designer.propose(store, device_id, lens_id, group["pulse_width"], group["line_interval"], group["passes"], seed=seed, size=size,
                                material_id=f["material_id"] if f["subkind"] == "coverage" else None)
    return designer.link_finding(store, prop["id"], finding_id)


# -- the schedule ------------------------------------------------------------------------------------------------------------
def interval_hours(store: Store) -> float:
    return float(store.get_setting(INTERVAL_SETTING, 0) or 0)


def schedule(store: Store) -> dict:
    """The periodic analysis: its interval (0 is off, the default), the last run and when the next one is due."""
    hours = interval_hours(store)
    last = get_run(store)
    due = None
    if hours > 0:
        due = now() if last is None else (datetime.fromisoformat(last["at"]) + timedelta(hours=hours)).isoformat(timespec="seconds")
    return {"interval_hours": hours, "last_run_at": last["at"] if last else None, "next_due_at": due}


def set_interval(store: Store, hours) -> dict:
    try:
        value = float(hours)
    except (TypeError, ValueError):
        raise su.ValidationError(f"the analysis interval must be a number of hours from 0 to {MAX_INTERVAL_HOURS}") from None
    if not math.isfinite(value) or not 0 <= value <= MAX_INTERVAL_HOURS:
        raise su.ValidationError(f"the analysis interval must be a number of hours from 0 to {MAX_INTERVAL_HOURS}")
    store.set_setting(INTERVAL_SETTING, value)
    return schedule(store)


def due(store: Store, at: datetime | None = None) -> bool:
    hours = interval_hours(store)
    if hours <= 0:
        return False
    last = get_run(store)
    if last is None:
        return True
    return (at or datetime.now(timezone.utc)) - datetime.fromisoformat(last["at"]) >= timedelta(hours=hours)


class Scheduler:
    """Runs the analysis when it is due, in one background thread of the app. The thread starts only once an interval is set
    (never with the default of 0), checks every ``poll_seconds``, skips a check while another run is in progress and stops
    when the app shuts down."""

    def __init__(self, store: Store, poll_seconds: float = POLL_SECONDS):
        self.store, self.poll_seconds = store, poll_seconds
        self._stop = threading.Event()
        self._guard = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start_if_enabled(self) -> bool:
        with self._guard:
            if self._thread is None and not self._stop.is_set() and interval_hours(self.store) > 0:
                self._thread = threading.Thread(target=self._loop, name="analysis-scheduler", daemon=True)
                self._thread.start()
            return self.running

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        with self._guard:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                if due(self.store):
                    run_analysis(self.store, "schedule", blocking=False)
            except Exception as exc:          # a failed run is recorded; the schedule goes on
                self.store.audit("analysis_failed", trigger="schedule", error=f"{type(exc).__name__}: {exc}")
