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
"""
from __future__ import annotations

import hashlib
import json
import math

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


def propose(store: Store, device_id: int, lens_id: int | None, pulse_width: float, line_interval: float, passes: int,
            seed: int = 1729, size: int = DEFAULT_SIZE) -> dict:
    """Return the stored proposal for this database state and job-settings group, creating it if it is new."""
    if int(size) != size or not 1 <= size <= MAX_SIZE:
        raise DesignerError(f"the proposal size must be a whole number between 1 and {MAX_SIZE}")
    if int(seed) != seed:
        raise DesignerError("the seed must be a whole number")
    setup = su.resolve(store, device_id, lens_id)
    group = su.job_settings(setup["device"]["passport"], pulse_width, line_interval, passes)
    axes = _axes(setup)
    domains = {"group": group, "power_frequency_speed_bounds": [{k: a[k] for k in ("key", "min", "max")} for a in axes]}
    samples = [s for s in model.knowledge_summaries(store, device_id, lens_id).values() if in_group(s["parameters"], group)]
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
    instab = {}
    for u in unstable:
        vec = [u["parameters"][k] for k in MODELLED_KEYS]
        cand.append(vec)
        instab[tuple(vec)] = min(1.0, u["variance"] / (2 * rules["variance_threshold"]))
    cand = np.array(cand, float)
    X = np.array([_norm(c, axes) for c in cand])
    measured = np.array([_norm([s["parameters"][k] for k in MODELLED_KEYS], axes) for s in samples]) if samples else np.zeros((0, 3))
    notes = []
    gap = np.ones(len(X)) if len(measured) == 0 else np.minimum(1.0, np.linalg.norm(X[:, None, :] - measured[None, :, :], axis=2).min(axis=1) / GAP_SCALE)
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
    params = []
    for pk in picks:
        i = pk["i"]
        params.append({**{k: float(cand[i][j]) for j, k in enumerate(MODELLED_KEYS)}, **group, "reason": pk["reason"],
                       "utility": pk["utility"], "scores": {k: float(scores[i, j]) for j, k in enumerate(ORDER)},
                       "target_id": pk["target_id"], "estimated_distance_to_target": pk["est"]})
    data = {"parameters": params, "target_ids": sorted({p["target_id"] for p in params if p["target_id"] is not None}), "size": size,
            "group": group, "notes": notes, "domains": domains,
            "model": {"measured_sets": len(samples), "gaussian_process": len(samples) >= MIN_SETS_FOR_MODEL, "dimensions": len(MODELLED_KEYS)},
            "unaddressed_targets": sorted({t["id"] for t in targets} - {p["target_id"] for p in params if p["target_id"] is not None})}
    with store.transaction():
        pid = store.execute("INSERT INTO proposal(device_id,lens_id,base_signature,seed,data_json,created_at) VALUES (?,?,?,?,?,?)",
                            (device_id, lens_id, sig, int(seed), json.dumps(data), now())).lastrowid
        for tid in data["target_ids"]:
            store.execute("UPDATE target_color SET proposal_id=? WHERE id=? AND proposal_id IS NULL", (pid, tid))
    return get_proposal(store, pid)


def get_proposal(store: Store, proposal_id: int) -> dict:
    row = store.one("SELECT * FROM proposal WHERE id=?", (proposal_id,))
    if row is None:
        raise KeyError(f"proposal {proposal_id} not found")
    d = dict(row)
    d.update(json.loads(d.pop("data_json")))
    d["boards"] = [r["id"] for r in store.query("SELECT id FROM plate WHERE proposal_id=? AND status IS NOT 'Deleted' ORDER BY id",
                                                (proposal_id,))]
    return d


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
    return pl.create_plates(store, prop["device_id"], series, cell_w, cell_h, gap, proposal_id=proposal_id)


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
