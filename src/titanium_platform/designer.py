"""Offline Experiment Designer (REQ-006, DEC-013).

Proposals are computed by an acquisition function over candidate parameter sets; no network and no LLM is
involved. With the same database state, seed and size the same proposal is returned (stored once per
``(laser, lens, base_signature, seed)``).

A proposal belongs to one laser and lens record and to one group of equal job settings (pulse width, line interval,
passes), which is its input (DEC-042): power, frequency and speed are modelled within that group and measurements of
another group take no part. Model: a Gaussian process (fixed RBF kernel, no hyper-parameter fitting) over those three
normalised axes, fitted on the mean Lab of every measured parameter set of the group. It needs at least
``MIN_SETS_FOR_MODEL`` sets; with fewer the designer falls back to gap sampling and says so. Everything numeric below
is an explicit, unvalidated engineering default (proposed DEC-033), not a requirement.

Utility of a candidate is the largest of four scores in 0..1; its reason is the score that won:
  target       closeness of the model's predicted Lab to a registered target color
  instability  an existing parameter set whose repeats exceed the saved variance threshold
  uncertainty  posterior standard deviation of the model
  gap          distance to the nearest measured set
Sets are picked greedily and each pick discounts its neighbours so a proposal spreads out.

A plate made from a proposal keeps, per cell, the target colour it addressed; once a photograph of the plate is accepted,
each such cell is checked against its target and the target records the result (REQ-006).

Power is searched over 1-100 %, frequency over the laser's usable range (narrowed by confirmed controller limits,
REQ-018) and speed over ``SPEED_RANGE_MM_S``: no scanner limit is stored, so it is the same ceiling as the capability
plates. The pulse width must be a selectable step of the laser.

A proposal also states, in words built only from its reasons and numbers (REQ-022): the question it asks, why the answer is
valuable, why each set was chosen, the task (its plates are LightBurn fill cells), the laser and lens, and the titanium stock
it models (one stock when the operator chose it, else every stock measured with these job settings). None of this takes part
in the selection, so the chosen sets are what they were before these fields existed. Its status moves proposed -> accepted
(its plates are made) -> done (every plate photographed and accepted), or proposed -> rejected, and every change is kept.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

from . import color, model, plans as pl, setup as su
from .db import Store, now

MIN_SETS_FOR_MODEL = 3
N_CANDIDATES = 1500
GAP_SCALE = 0.25
TARGET_SCALE = 10.0
DIVERSITY_RADIUS = 0.15
LENGTH_SCALE = 0.3
NOISE = 1e-2
DEFAULT_SIZE = 6
MAX_SIZE = 40
MAX_EXPLANATION_CHARS = 4000
ORDER = ("target", "instability", "uncertainty", "gap")  # tie-break order for the winning score
ROUND = {"power": 1, "frequency": 0, "speed": 0}
MODELLED_KEYS = ("power", "frequency", "speed")
GROUP_KEYS = ("pulse_width", "line_interval", "passes")
POWER_RANGE_PCT = (1.0, 100.0)
SPEED_RANGE_MM_S = (1.0, 10000.0)
PLATE_LAYER_TYPE = "Scan"           # every cell of a designer plate is a LightBurn fill (plans.export_lbrn2)


class DesignerError(ValueError):
    """A proposal cannot be made or used; the message is meant for the operator."""


def _axes(setup: dict) -> list[dict]:
    """The search ranges of the modelled settings on this laser and lens."""
    from .characterization import characterize
    frequency = characterize(setup["device"]["passport"], setup["lens"])["frequency_range_khz"]
    return [{"key": "power", "name": "Power", "unit": "%", "min": POWER_RANGE_PCT[0], "max": POWER_RANGE_PCT[1]},
            {"key": "frequency", "name": "Frequency", "unit": "kHz", "min": float(frequency["min"]), "max": float(frequency["max"])},
            {"key": "speed", "name": "Speed", "unit": "mm/s", "min": SPEED_RANGE_MM_S[0], "max": SPEED_RANGE_MM_S[1]}]


def in_group(parameters: dict, group: dict) -> bool:
    return all(parameters.get(k) is not None and math.isclose(float(parameters[k]), float(group[k]), rel_tol=1e-9, abs_tol=1e-12)
               for k in GROUP_KEYS)


def _norm(vec, axes) -> np.ndarray:
    return np.array([(v - a["min"]) / (a["max"] - a["min"]) for v, a in zip(vec, axes)], float)


def _denorm(x, axes) -> list[float]:
    return [round(a["min"] + float(v) * (a["max"] - a["min"]), ROUND[a["key"]]) for v, a in zip(x, axes)]


def signature(setup_key: str, samples: list[dict], targets: list[dict], size: int, variance_threshold,
              domains: dict) -> str:
    state = {"setup": setup_key, "obs": sorted(i for s in samples for i in s["observation_ids"]),
             "targets": sorted((t["id"], tuple(round(v, 6) for v in t["lab"])) for t in targets), "size": size,
             "var": variance_threshold, "domains": domains}
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()[:20]


def open_targets(store: Store, device_id: int, lens_id: int | None) -> list[dict]:
    """The target colours of one laser and lens, each with the measurements of plate cells that addressed it, newest first."""
    return [{"id": r["id"], "lab": json.loads(r["lab_json"]), "source_plan_id": r["source_plan_id"], "proposal_id": r["proposal_id"],
             "checks": recorded_checks(store, r["id"])}
            for r in store.query("SELECT * FROM target_color WHERE device_id=? AND lens_id IS ? ORDER BY id", (device_id, lens_id))]


def target_checks(store: Store, pair_id: int) -> list[dict]:
    """Each cell of the pair's plate that a proposal made for a registered target colour, checked against it (REQ-006): the
    measured Lab, delta E to the target and whether it is within the delta E tolerance of the laser and lens (None while no
    tolerance is saved). A camera-relative measurement is not comparable with a target and gets no delta E."""
    pair = store.one("SELECT * FROM pair WHERE id=?", (pair_id,))
    plate = store.one("SELECT cells_json FROM plate WHERE id=?", (pair["plate_id"],)) if pair and pair["plate_id"] else None
    cells = {c.get("id"): c for c in json.loads(plate["cells_json"])} if plate else {}
    if not any(c.get("target_id") is not None for c in cells.values()):
        return []
    plan = store.one("SELECT data_json FROM plan WHERE plate_id=?", (pair["plate_id"],))
    cell_of = {layer["index"]: layer.get("cell_id") for layer in json.loads(plan["data_json"])["layers"]} if plan else {}
    tolerance = su.get_rules(store, pair["device_id"], pair["lens_id"])["delta_tolerance"]
    out = []
    for o in store.query("SELECT * FROM observation WHERE pair_id=? ORDER BY layer_index", (pair_id,)):
        evidence = json.loads(o["evidence_json"] or "{}")
        cell = cells.get(cell_of.get(o["layer_index"])) if evidence.get("role", "test feature") == "test feature" else None
        target = store.one("SELECT * FROM target_color WHERE id=?", (cell["target_id"],)) if cell and cell.get("target_id") is not None else None
        if target is None:
            continue
        measured, wanted = json.loads(o["lab_json"]), json.loads(target["lab_json"])
        comparable = (evidence.get("color_measurement") or {}).get("mode") == "reference_chart_corrected"
        delta = color.delta_e(measured, wanted) if comparable else None
        check = {"target_id": target["id"], "target_lab": wanted, "pair_id": pair_id, "observation_id": o["id"], "layer_index": o["layer_index"],
                 "cell_id": cell["id"], "measured_lab": measured, "delta_e": delta, "tolerance": tolerance, "comparable": comparable,
                 "within_tolerance": None if delta is None or tolerance is None else delta <= tolerance}
        if not comparable:
            check["note"] = "camera-relative measurement: it cannot be compared with a target colour"
        out.append(check)
    return out


def record_target_checks(store: Store, pair_id: int) -> list[dict]:
    """The targets keep the result of an accepted plate: one record per target and observation, never rewritten."""
    checks = target_checks(store, pair_id)
    with store.transaction():
        for c in checks:
            store.execute("INSERT OR IGNORE INTO target_check(target_id,pair_id,observation_id,cell_id,measured_lab_json,delta_e,tolerance,"
                          "within_tolerance,comparable,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (c["target_id"], pair_id, c["observation_id"], c["cell_id"], json.dumps(c["measured_lab"]), c["delta_e"], c["tolerance"],
                           None if c["within_tolerance"] is None else int(c["within_tolerance"]), int(c["comparable"]), now()))
    return checks


def recorded_checks(store: Store, target_id: int) -> list[dict]:
    return [{"pair_id": r["pair_id"], "observation_id": r["observation_id"], "cell_id": r["cell_id"], "measured_lab": json.loads(r["measured_lab_json"]),
             "delta_e": r["delta_e"], "tolerance": r["tolerance"], "comparable": bool(r["comparable"]),
             "within_tolerance": None if r["within_tolerance"] is None else bool(r["within_tolerance"]), "at": r["created_at"]}
            for r in store.query("SELECT c.* FROM target_check c JOIN pair p ON p.id=c.pair_id WHERE c.target_id=? AND p.status!='Deleted' "
                                 "ORDER BY c.id DESC", (target_id,))]


def _fit(samples: list[dict], axes):
    X = np.array([_norm([s["parameters"][k] for k in MODELLED_KEYS], axes) for s in samples])
    Y = np.array([s["lab"] for s in samples])
    mu, sd = Y.mean(axis=0), Y.std(axis=0)
    sd[sd < 1e-9] = 1.0
    kernel = ConstantKernel(1.0, "fixed") * RBF(LENGTH_SCALE, "fixed") + WhiteKernel(NOISE, "fixed")
    gp = GaussianProcessRegressor(kernel=kernel, optimizer=None, normalize_y=False).fit(X, (Y - mu) / sd)
    return gp, mu, sd, X


def stock_of(summary: dict) -> int | None:
    """The titanium stock record of a knowledge summary (its key keeps one stock), None when the stock is not a record."""
    groups = summary.get("context_groups") or [{}]
    return groups[0].get("material_id")


def _stock(store: Store, material_id: int | None, samples: list[dict]) -> dict:
    """The titanium a proposal covers: the stock chosen for it, else every stock measured with its job settings."""
    if material_id is not None:
        row = store.one("SELECT id,name,grade,batch FROM material_profile WHERE id=?", (material_id,))
        return {"material_id": material_id, "material": dict(row), "measured": []}
    fields = ("material_id", "titanium_name", "titanium_grade", "batch")
    measured = Counter(tuple((s.get("context_groups") or [{}])[0].get(k) for k in fields) for s in samples)
    return {"material_id": None, "material": None,
            "measured": [{"material_id": m, "name": n, "grade": g, "batch": b, "sets": count}
                         for (m, n, g, b), count in sorted(measured.items(), key=lambda kv: (kv[0][0] is None, kv[0][0] or 0, str(kv[0][1])))]}


def _plate_task() -> str | None:
    """The task of a designer plate: its cells are LightBurn fills (read by the one task helper of the analysis)."""
    from .findings import task_of
    return task_of({"layer_type": PLATE_LAYER_TYPE})


def _setup_label(setup: dict) -> dict:
    lens = setup["lens"]
    return {"device_id": setup["device_id"], "device": setup["device"]["title"], "lens_id": setup["lens_id"],
            "lens": None if lens is None else {k: lens[k] for k in ("id", "name", "focal_length_mm")}}


def _words(picks: list[dict], targets: list[dict], variance_threshold) -> tuple[list[str], list[str]]:
    """The question a proposal asks and why its answer is worth an engraving, one sentence per reason it serves (REQ-022);
    built from its reasons and numbers only, so the same proposal always reads the same."""
    questions: list[str] = []
    worth: list[str] = []
    by_reason = {r: [p for p in picks if p["reason"] == r] for r in (*ORDER, "repeat")}
    labs = {t["id"]: t["lab"] for t in targets}
    for p in by_reason["target"]:
        L, a, b = labs[p["target_id"]]
        questions.append(f"Which settings reproduce target colour {p['target_id']} (L {L:.1f}, a {a:.1f}, b {b:.1f})?")
    if by_reason["target"]:
        worth.append("a measured cell next to a target colour shows whether it can be engraved within the tolerance, and an unreachable "
                     "artwork colour becomes usable")
    if by_reason["instability"]:
        questions.append(f"Do repeat engravings of the unstable sets ({len(by_reason['instability'])}) agree within the variance threshold "
                         f"{variance_threshold:g}?")
        worth.append("repeats show whether these settings are reproducible or must be avoided in a work")
    if by_reason["uncertainty"]:
        questions.append(f"What colours do the settings give where the model is least certain ({len(by_reason['uncertainty'])} sets)?")
        worth.append("a measurement where the model is least certain reduces the error of every prediction near it")
    if by_reason["gap"]:
        questions.append(f"What colours do settings far from every measured set give ({len(by_reason['gap'])} sets)?")
        worth.append("a measurement far from the others extends the measured colour space")
    if by_reason["repeat"]:
        questions.append(f"Do recipes measured on a single engraving give the same colour when engraved again ({len(by_reason['repeat'])} sets)?")
        worth.append("a second independent engraving lets the stability of a recipe be assessed and, under agreed criteria, validated")
    return questions, worth


def _rationale(pick: dict, variance_threshold) -> str:
    """Why one set was chosen, in words (REQ-022 AC4)."""
    if pick["reason"] == "target":
        rationale = (f"aimed at target colour {pick['target_id']}: the model predicts {pick['est']:.1f} ΔE from it at these settings")
    elif pick["reason"] == "instability":
        rationale = (f"re-measures settings whose repeat engravings vary by {pick['variance']:.2f} ΔE², above the saved variance "
                     f"threshold {variance_threshold:g}")
    elif pick["reason"] == "uncertainty":
        rationale = f"the model is least certain here: posterior standard deviation {pick['utility']:.2f} of the standardised colour"
    elif pick["reason"] == "repeat":
        rationale = (f"repeats a recipe measured on a single engraving ({pick['lab'][0]:.1f}, {pick['lab'][1]:.1f}, {pick['lab'][2]:.1f} "
                     "L, a, b) so that its stability can be assessed")
    elif pick["nearest"] is None:
        rationale = "nothing is measured with these job settings yet: the set spreads the first plate over the laser's range"
    else:
        rationale = (f"far from what is measured: {pick['nearest']:.2f} on the normalised power, frequency and speed axes to the "
                     "nearest measured set")
    return rationale


def propose(store: Store, device_id: int, lens_id: int | None, pulse_width: float, line_interval: float, passes: int,
            seed: int = 1729, size: int = DEFAULT_SIZE, material_id: int | None = None) -> dict:
    """Return the stored proposal for this database state and job-settings group, creating it if it is new.

    With ``material_id`` only the measured sets of that titanium stock are modelled; without it every stock measured with
    these job settings is, as before (its signature and its sets are unchanged)."""
    if int(size) != size or not 1 <= size <= MAX_SIZE:
        raise DesignerError(f"the proposal size must be a whole number between 1 and {MAX_SIZE}")
    if int(seed) != seed:
        raise DesignerError("the seed must be a whole number")
    setup = su.resolve(store, device_id, lens_id)
    group = su.job_settings(setup["device"]["passport"], pulse_width, line_interval, passes)
    axes = _axes(setup)
    domains = {"group": group, "power_frequency_speed_bounds": [{k: a[k] for k in ("key", "min", "max")} for a in axes]}
    samples = [s for s in model.knowledge_summaries(store, device_id, lens_id).values() if in_group(s["parameters"], group)]
    if material_id is not None:
        if store.one("SELECT id FROM material_profile WHERE id=?", (material_id,)) is None:
            raise KeyError(f"titanium stock {material_id} not found")
        domains["material_id"] = material_id                 # a proposal of one stock is another state than one of all stocks
        samples = [s for s in samples if stock_of(s) == material_id]
    targets = open_targets(store, device_id, lens_id)
    rules = su.get_rules(store, device_id, lens_id)
    sig = signature(setup["key"], samples, targets, int(size), rules["variance_threshold"], domains)
    row = store.one("SELECT id FROM proposal WHERE device_id=? AND lens_id IS ? AND base_signature=? AND seed=?",
                    (device_id, lens_id, sig, int(seed)))
    if row is not None:
        return get_proposal(store, row["id"])

    rng = np.random.default_rng(int(seed))
    cand = [_denorm(rng.random(3), axes) for _ in range(N_CANDIDATES)]
    unstable = model.unstable_regions(samples, rules["variance_threshold"])
    instab, variance_of = {}, {}
    for u in unstable:
        vec = [u["parameters"][k] for k in MODELLED_KEYS]
        cand.append(vec)
        instab[tuple(vec)] = min(1.0, u["variance"] / (2 * rules["variance_threshold"]))
        variance_of[tuple(vec)] = u["variance"]
    cand = np.array(cand, float)
    X = np.array([_norm(c, axes) for c in cand])
    measured = np.array([_norm([s["parameters"][k] for k in MODELLED_KEYS], axes) for s in samples]) if samples else np.zeros((0, 3))
    notes = []
    nearest = None if len(measured) == 0 else np.linalg.norm(X[:, None, :] - measured[None, :, :], axis=2).min(axis=1)
    gap = np.ones(len(X)) if nearest is None else np.minimum(1.0, nearest / GAP_SCALE)
    unc = np.zeros(len(X))
    tgt = np.zeros(len(X))
    per_target: dict[int, tuple[np.ndarray, np.ndarray]] = {}   # target id -> (closeness, predicted delta E)
    if len(samples) >= MIN_SETS_FOR_MODEL:
        gp, mu, sd, _ = _fit(samples, axes)
        mean, std = gp.predict(X, return_std=True)
        # Lab has three outputs. They share one fixed kernel, so their posterior standard deviations are
        # identical (the targets were standardised outside the model); reduce to one value per candidate.
        std = np.asarray(std)
        if std.ndim == 2:
            std = std.mean(axis=1)
        unc = np.clip(std, 0.0, 1.0)
        pred_lab = mean * sd + mu
        for t in targets:
            d = np.linalg.norm(pred_lab - np.asarray(t["lab"]), axis=1)
            per_target[t["id"]] = (np.exp(-d / TARGET_SCALE), d)
            tgt = np.maximum(tgt, per_target[t["id"]][0])
    else:
        notes.append(f"fewer than {MIN_SETS_FOR_MODEL} measured parameter sets with these job settings: the model is not fitted, so candidates are chosen by gap only and target colors cannot be addressed yet")
    inst = np.array([instab.get(tuple(c), 0.0) for c in cand])
    scores = np.stack([tgt, inst, unc, gap], axis=1)  # columns follow ORDER
    size = int(size)
    discount = np.ones(len(X))
    picks: list[dict] = []

    def take(i: int, reason: str, utility: float, target_id=None, est=None) -> None:
        picks.append({"i": i, "reason": reason, "utility": float(utility), "target_id": target_id, "est": est})
        discount[:] = discount * np.minimum(1.0, np.linalg.norm(X - X[i], axis=1) / DIVERSITY_RADIUS)
        discount[i] = 0.0

    # Phase 1: registered target colors come first (DEC-009: the strongest signal for the next experiment), at most
    # half of the proposal. Taking the max of all four scores would let the many far-away gap candidates, whose gap
    # score saturates at 1, outrank every target candidate and make a target impossible to address.
    for tid in sorted(per_target)[:-(-size // 2)]:
        close, dist = per_target[tid]
        i = int(np.argmax(close * discount))
        if close[i] * discount[i] > 0:
            take(i, "target", close[i], tid, float(dist[i]))
    # Phase 2: existing parameter sets whose repeats exceed the saved variance threshold, at most half of what is left.
    n_base = len(cand) - len(unstable)
    for i in sorted(range(n_base, len(cand)), key=lambda k: (-inst[k], k))[:-(-(size - len(picks)) // 2)]:
        if discount[i] > 0:
            take(i, "instability", inst[i])
    # Phase 3: the rest by the larger of posterior uncertainty and distance to the nearest measured set.
    while len(picks) < size:
        util = np.maximum(unc, gap) * discount
        i = int(np.argmax(util))
        if util[i] <= 0:
            break
        take(i, "uncertainty" if unc[i] >= gap[i] else "gap", max(unc[i], gap[i]))
    if not picks:
        raise DesignerError("no candidate parameter sets are available in the laser's ranges")
    task = _plate_task()
    params = []
    for pk in picks:
        i = pk["i"]
        pk.update(variance=variance_of.get(tuple(cand[i])), nearest=None if nearest is None else float(nearest[i]))
        params.append({**{k: float(cand[i][j]) for j, k in enumerate(MODELLED_KEYS)}, **group, "reason": pk["reason"],
                       "utility": pk["utility"], "scores": {k: float(scores[i, j]) for j, k in enumerate(ORDER)},
                       "target_id": pk["target_id"], "estimated_distance_to_target": pk["est"],
                       "rationale": _rationale(pk, rules["variance_threshold"]), "task": task})
    questions, worth = _words(picks, targets, rules["variance_threshold"])
    data = {"parameters": params, "target_ids": sorted({p["target_id"] for p in params if p["target_id"] is not None}), "size": size,
            "group": group, "notes": notes, "domains": domains,
            "model": {"measured_sets": len(samples), "gaussian_process": len(samples) >= MIN_SETS_FOR_MODEL, "dimensions": len(MODELLED_KEYS)},
            "unaddressed_targets": sorted({t["id"] for t in targets} - {p["target_id"] for p in params if p["target_id"] is not None}),
            "questions": questions, "worth": worth, "task": task, "setup": _setup_label(setup), "stock": _stock(store, material_id, samples)}
    return _insert(store, device_id, lens_id, sig, int(seed), data)


def _insert(store: Store, device_id: int, lens_id: int | None, sig: str, seed: int, data: dict) -> dict:
    with store.transaction():
        pid = store.execute("INSERT INTO proposal(device_id,lens_id,base_signature,seed,data_json,created_at) VALUES (?,?,?,?,?,?)",
                            (device_id, lens_id, sig, seed, json.dumps(data), now())).lastrowid
        for tid in data["target_ids"]:
            store.execute("UPDATE target_color SET proposal_id=? WHERE id=? AND proposal_id IS NULL", (pid, tid))
    return get_proposal(store, pid)


def propose_repeats(store: Store, device_id: int, lens_id: int | None, keys: list[str], size: int = DEFAULT_SIZE,
                    material_id: int | None = None) -> dict:
    """A proposal that engraves again recipes of this laser and lens measured on a single independent engraving (REQ-022, a
    gap of the analysis): the first ``size`` of ``keys`` in key order whose six settings are all recorded, each with its
    measured colour, so the repeat can be compared with it. Stored once per laser, lens and chosen recipes.

    Its plates are designer plates: LightBurn fill cells with these six settings. A recipe whose file had other LightBurn
    settings is repeated in those six only, and the proposal says so."""
    if int(size) != size or not 1 <= size <= MAX_SIZE:
        raise DesignerError(f"the proposal size must be a whole number between 1 and {MAX_SIZE}")
    setup = su.resolve(store, device_id, lens_id)
    summaries = model.knowledge_summaries(store, device_id, lens_id)
    chosen = [summaries[k] for k in sorted(set(keys)) if k in summaries
              and all(summaries[k]["parameters"].get(p) is not None for p in (*MODELLED_KEYS, *GROUP_KEYS))][:int(size)]
    if not chosen:
        raise DesignerError("none of these recipes has all six settings recorded: they cannot be repeated on a plate")
    sig = "repeat:" + hashlib.sha256(json.dumps({"setup": setup["key"], "keys": [s["key"] for s in chosen],
                                                  "obs": sorted(i for s in chosen for i in s["observation_ids"])}, sort_keys=True).encode()).hexdigest()[:20]
    row = store.one("SELECT id FROM proposal WHERE device_id=? AND lens_id IS ? AND base_signature=? AND seed=0", (device_id, lens_id, sig))
    if row is not None:
        return get_proposal(store, row["id"])
    task = _plate_task()
    notes, params, picks = [], [], []
    for s in chosen:
        p = s["parameters"]
        pick = {"reason": "repeat", "lab": s["lab"], "target_id": None}
        picks.append(pick)
        params.append({**{k: float(p[k]) for k in MODELLED_KEYS}, **{k: p[k] for k in GROUP_KEYS}, "reason": "repeat", "utility": None,
                       "scores": {}, "target_id": None, "estimated_distance_to_target": None, "rationale": _rationale(pick, None),
                       "task": task, "repeats": {"key": s["key"], "lab": s["lab"], "observation_ids": s["observation_ids"]}})
        if p.get("source_settings") or p.get("layer_type") not in (None, PLATE_LAYER_TYPE):
            notes.append("some of these recipes were engraved with other LightBurn settings than a plate cell has: the repeat "
                         "keeps their power, frequency, speed, pulse width, line interval and passes only")
    questions, worth = _words(picks, [], None)
    data = {"parameters": params, "target_ids": [], "size": len(params), "group": None, "notes": sorted(set(notes)),
            "domains": {"repeats": [s["key"] for s in chosen]}, "model": {"measured_sets": len(chosen), "gaussian_process": False,
                                                                         "dimensions": len(MODELLED_KEYS)},
            "unaddressed_targets": [], "questions": questions, "worth": worth, "task": task, "setup": _setup_label(setup),
            "stock": _stock(store, material_id, chosen)}
    return _insert(store, device_id, lens_id, sig, 0, data)


def get_proposal(store: Store, proposal_id: int) -> dict:
    row = store.one("SELECT * FROM proposal WHERE id=?", (proposal_id,))
    if row is None:
        raise KeyError(f"proposal {proposal_id} not found")
    d = dict(row)
    d.update(json.loads(d.pop("data_json")))
    d["boards"] = [r["id"] for r in store.query("SELECT id FROM plate WHERE proposal_id=? AND status IS NOT 'Deleted' ORDER BY id",
                                                (proposal_id,))]
    d["status_history"] = status_history(store, proposal_id)
    d["status"] = _current_status(d["status_history"], d["boards"])
    d["origins"] = [{"finding_id": e["finding_id"], "at": e["at"]} for e in d["status_history"] if e["finding_id"] is not None]
    return d


# -- status: proposed -> accepted -> done, or proposed -> rejected; every change is kept (REQ-022) -------------------------
def status_history(store: Store, proposal_id: int) -> list[dict]:
    return [dict(r) for r in store.query("SELECT id,at,from_status,to_status,reason,note,finding_id FROM proposal_event "
                                         "WHERE proposal_id=? ORDER BY id", (proposal_id,))]


def _current_status(history: list[dict], boards: list[int]) -> str:
    """The last recorded status; a proposal whose plates were made before statuses were recorded is accepted."""
    changes = [e for e in history if e["to_status"] != e["from_status"]]
    return changes[-1]["to_status"] if changes else ("accepted" if boards else "proposed")


def _record(store: Store, proposal_id: int, to_status: str, reason: str, note: str | None = None, finding_id: int | None = None,
            from_status: str | None = None) -> None:
    from_status = from_status or get_proposal(store, proposal_id)["status"]
    store.execute("INSERT INTO proposal_event(proposal_id,at,from_status,to_status,reason,note,finding_id) VALUES (?,?,?,?,?,?,?)",
                  (proposal_id, now(), from_status, to_status, reason, note, finding_id))


def link_finding(store: Store, proposal_id: int, finding_id: int) -> dict:
    """Record that a finding of the analysis asked for this proposal (once per finding); its status does not change."""
    prop = get_proposal(store, proposal_id)
    if finding_id not in {o["finding_id"] for o in prop["origins"]}:
        _record(store, proposal_id, prop["status"], "proposed for a finding of the analysis", finding_id=finding_id)
    return get_proposal(store, proposal_id)


def reject(store: Store, proposal_id: int, note: str = "") -> dict:
    """The operator declines a proposal before its plates are made; the reason he gives is kept as he wrote it."""
    prop = get_proposal(store, proposal_id)
    if prop["status"] != "proposed":
        raise DesignerError(f"only a proposed experiment can be rejected (this one is {prop['status']})")
    _record(store, proposal_id, "rejected", "rejected by the operator", (note or "").strip() or None)
    return get_proposal(store, proposal_id)


def _plate_pairs(store: Store, plate_id: int) -> list[dict]:
    """The photographs of one plate in active use: uploaded for its plate or its plan."""
    return [dict(r) for r in store.query(
        "SELECT id,status,photo_name,created_at,accepted_at,engraving_id FROM pair WHERE status!='Deleted' "
        "AND (plate_id=? OR plan_id IN (SELECT id FROM plan WHERE plate_id=?)) ORDER BY id", (plate_id, plate_id))]


def reconcile_status(store: Store, proposal_id: int) -> dict:
    """An accepted proposal whose every plate has an accepted photograph is done; a done one whose photograph left active use
    is accepted again. Both changes are recorded."""
    prop = get_proposal(store, proposal_id)
    if prop["status"] not in ("accepted", "done"):
        return prop
    complete = bool(prop["boards"]) and all(any(p["status"] == "Accepted" for p in _plate_pairs(store, b)) for b in prop["boards"])
    if prop["status"] == "accepted" and complete:
        _record(store, proposal_id, "done", "every plate of it was photographed and accepted")
    elif prop["status"] == "done" and not complete:
        _record(store, proposal_id, "accepted", "an accepted photograph of its plates left active use")
    return get_proposal(store, proposal_id)


def reconcile_statuses(store: Store) -> None:
    for r in store.query("SELECT id FROM proposal ORDER BY id"):
        reconcile_status(store, r["id"])


def results(store: Store, proposal_id: int) -> dict:
    """What became of a proposal (REQ-022 AC5): its plates, the photographs of each with their acceptance, and per proposed set
    the measured outcome of its cell on every accepted photograph, with the target check recorded for it."""
    prop = get_proposal(store, proposal_id)
    plates, cells = [], []                   # cells: (plate id, cell, its measurements on every accepted photograph)
    for r in store.query("SELECT id,experiment_id,speed,cells_json,status FROM plate WHERE proposal_id=? ORDER BY id", (proposal_id,)):
        plan = store.one("SELECT id,status,data_json FROM plan WHERE plate_id=?", (r["id"],))
        pairs = _plate_pairs(store, r["id"])
        plates.append({"plate_id": r["id"], "experiment_id": r["experiment_id"], "speed": r["speed"], "deleted": r["status"] == "Deleted",
                       "plan_id": plan["id"] if plan else None, "plan_status": plan["status"] if plan else None, "pairs": pairs})
        index_of = {layer.get("cell_id"): layer["index"] for layer in json.loads(plan["data_json"])["layers"]} if plan else {}
        accepted = [p["id"] for p in pairs if p["status"] == "Accepted"]
        for cell in json.loads(r["cells_json"]):
            if cell.get("proposed") and cell["id"] in index_of:
                cells.append((r["id"], cell, [_measured(store, o, cell["id"]) for o in store.query(
                    f"SELECT id,pair_id,lab_json,evidence_json FROM observation WHERE layer_index=? AND pair_id IN ({','.join('?' * len(accepted))}) "
                    "ORDER BY id", (index_of[cell["id"]], *accepted))] if accepted else []))
    out = []
    for i, p in enumerate(prop["parameters"]):
        plate_id, cell, found = next(((plate_id, cell, found) for plate_id, cell, found in cells
                                      if all(math.isclose(float(cell["parameters"][k]), float(p[k]), rel_tol=1e-9, abs_tol=1e-9)
                                             for k in (*MODELLED_KEYS, *GROUP_KEYS))), (None, None, []))
        repeated = (p.get("repeats") or {}).get("lab")
        out.append({"index": i, "reason": p["reason"], "target_id": p["target_id"], "plate_id": plate_id,
                    "cell_id": cell["id"] if cell else None,
                    "measured": [m | {"delta_e_to_repeated_recipe": color.delta_e(m["lab"], repeated) if repeated and m["comparable"] else None}
                                 for m in found]})
    return {"plates": plates, "results": out}


def proposal_of_plate(store: Store, plate_id: int | None) -> dict | None:
    """The proposal a plate was made for, as a photograph of the plate links back to it (REQ-022 AC5); None for other plates."""
    row = store.one("SELECT proposal_id, device_id, lens_id FROM plate WHERE id=?", (plate_id,)) if plate_id else None
    if row is None or row["proposal_id"] is None:
        return None
    return {"id": row["proposal_id"], "device_id": row["device_id"], "lens_id": row["lens_id"],
            "status": get_proposal(store, row["proposal_id"])["status"]}


def _measured(store: Store, o, cell_id: str) -> dict:
    """One measurement of a proposed cell, with the target check recorded for it when the cell was made for a target."""
    check = store.one("SELECT * FROM target_check WHERE observation_id=? AND cell_id=?", (o["id"], cell_id))
    return {"pair_id": o["pair_id"], "observation_id": o["id"], "lab": json.loads(o["lab_json"]),
            "comparable": (json.loads(o["evidence_json"]).get("color_measurement") or {}).get("mode") == "reference_chart_corrected",
            "target_check": None if check is None else {
                "target_id": check["target_id"], "delta_e": check["delta_e"], "tolerance": check["tolerance"],
                "comparable": bool(check["comparable"]),
                "within_tolerance": None if check["within_tolerance"] is None else bool(check["within_tolerance"])}}


def list_proposals(store: Store, device_id: int, lens_id: int | None) -> list[dict]:
    return [get_proposal(store, r["id"]) for r in store.query("SELECT id FROM proposal WHERE device_id=? AND lens_id IS ? ORDER BY id DESC",
                                                              (device_id, lens_id))]


def create_plates(store: Store, proposal_id: int, cell_w: float, cell_h: float, gap: float) -> list[dict]:
    """Create one P×F grid per proposed speed/pulse/interval/pass combination.

    Cells the designer did not choose are intersections of that grid and are marked so; the proposal keeps its
    per-set reasons and target references and the plates carry them. The plates are engraved with the lens installed
    now, so it must be the lens the proposal was made for: otherwise the new measurements would not answer it.
    """
    prop = get_proposal(store, proposal_id)
    if prop["boards"]:
        raise DesignerError("plates were already created for this proposal")
    if prop["status"] == "rejected":
        raise DesignerError("this proposal was rejected: make a new proposal to engrave it")
    if su.installed(store, prop["device_id"])["lens_id"] != prop["lens_id"]:
        raise DesignerError("the proposal was made for another lens than the one installed on the laser now: install that lens or make a proposal for the installed one")
    by_conditions: dict[tuple[float, float, float, int], dict] = {}
    for p in prop["parameters"]:
        key = (p["speed"], p["pulse_width"], p["line_interval"], p["passes"])
        g = by_conditions.setdefault(key, {"speed": p["speed"], "pulse_width": p["pulse_width"],
                                           "line_interval": p["line_interval"], "passes": p["passes"],
                                           "powers": [], "frequencies": [], "proposed": {}})
        if p["power"] not in g["powers"]:
            g["powers"].append(p["power"])
        if p["frequency"] not in g["frequencies"]:
            g["frequencies"].append(p["frequency"])
        g["proposed"][(p["power"], p["frequency"])] = {"reason": p["reason"], "target_id": p["target_id"]}
    series = [g for _, g in sorted(by_conditions.items())]
    made = pl.create_plates(store, prop["device_id"], series, cell_w, cell_h, gap, proposal_id=proposal_id)
    _record(store, proposal_id, "accepted", "accepted by the operator: its plates were made", from_status=prop["status"])
    return made


def attach_explanation(store: Store, proposal_id: int, explainer) -> str | None:
    """Store explanatory text produced by ``explainer(proposal_copy) -> str``. Never touches parameters or data.

    ``explainer`` is optional: with None this is a no-op and the proposal is exactly as before, which is how
    the module behaves with no LLM configured. The function receives a deep copy, so it cannot alter the
    proposal, and only its returned text (a string, bounded in length) is stored.
    """
    if explainer is None:
        return None
    import copy
    before = get_proposal(store, proposal_id)
    text = explainer(copy.deepcopy(before))
    if not isinstance(text, str) or not text.strip():
        raise DesignerError("the explanation must be non-empty text")
    text = text.strip()[:MAX_EXPLANATION_CHARS]
    store.execute("UPDATE proposal SET explanation=? WHERE id=?", (text, proposal_id))
    return text


def explain(store: Store, proposal_id: int, explainer) -> dict:
    """The explanation the operator asks for (REQ-006): refused with the reason when no language model is configured, and when
    the model fails the proposal is left exactly as it was."""
    get_proposal(store, proposal_id)
    if explainer is None:
        raise DesignerError("no AI key is configured: set OPENAI_API_KEY in the environment or in .env.local to get an explanation; "
                            "the proposal works without it")
    try:
        attach_explanation(store, proposal_id, explainer)
    except DesignerError:
        raise
    except Exception as exc:          # provider details stay out of the screen, as in the research chat
        raise DesignerError(f"the AI service did not answer ({type(exc).__name__}): the proposal is unchanged") from None
    return get_proposal(store, proposal_id)
