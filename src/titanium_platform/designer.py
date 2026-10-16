"""Offline Experiment Designer (REQ-006, DEC-013).

Proposals are computed by an acquisition function over candidate parameter sets; no network and no LLM is
involved. With the same database state, seed and size the same proposal is returned (stored once per
``(profile, base_signature, seed)``).

Model: a Gaussian process (fixed RBF kernel, no hyper-parameter fitting) over six normalised process axes,
fitted on the mean Lab of every measured parameter set. It needs at least ``MIN_SETS_FOR_MODEL`` sets; with
fewer the designer falls back to gap sampling and says so. Everything numeric below is an explicit,
unvalidated engineering default (proposed DEC-033), not a requirement.

Utility of a candidate is the largest of four scores in 0..1; its reason is the score that won:
  target       closeness of the model's predicted Lab to a registered target color
  instability  an existing parameter set whose repeats exceed the saved variance threshold
  uncertainty  posterior standard deviation of the model
  gap          distance to the nearest measured set
Sets are picked greedily and each pick discounts its neighbours so a proposal spreads out.

Power/frequency/speed bounds come from the selected laser/lens profile. Pulse-width choices come from that
laser's selectable steps by default. Line intervals and passes are entered for each proposal, since they are
changing process settings and never belong to the hardware profile.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

from . import color, model, plans as pl, profiles as pf
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
ROUND = {"power": 1, "frequency": 0, "speed": 0, "pulse_width": 2, "line_interval": 4, "passes": 0}
PROCESS_KEYS = ("power", "frequency", "speed", "pulse_width", "line_interval", "passes")


class DesignerError(ValueError):
    """A proposal cannot be made or used; the message is meant for the operator."""


def _axes(profile: dict) -> list[dict]:
    by = {a["key"]: a for a in profile["axes"]}
    return [by[k] for k in ("power", "frequency", "speed")]


def _all_axes(profile: dict, pulse_widths: list[float], line_intervals: list[float], pass_counts: list[int]) -> list[dict]:
    axes = _axes(profile)
    for key, values, name, unit in (("pulse_width", pulse_widths, "Pulse width", "ns"),
                                    ("line_interval", line_intervals, "Line interval", "mm"),
                                    ("passes", pass_counts, "Passes", "count")):
        lo, hi = min(values), max(values)
        axes.append({"key": key, "name": name, "unit": unit, "min": lo, "max": hi if hi > lo else lo + 1.0})
    return axes


def _norm(vec, axes) -> np.ndarray:
    return np.array([(v - a["min"]) / (a["max"] - a["min"]) for v, a in zip(vec, axes)], float)


def _denorm(x, axes) -> list[float]:
    return [round(a["min"] + float(v) * (a["max"] - a["min"]), ROUND[a["key"]]) for v, a in zip(x, axes)]


def signature(profile_id: int, samples: list[dict], targets: list[dict], size: int, variance_threshold,
              domains: dict) -> str:
    state = {"profile": profile_id, "obs": sorted(i for s in samples for i in s["observation_ids"]),
             "targets": sorted((t["id"], tuple(round(v, 6) for v in t["lab"])) for t in targets), "size": size,
             "var": variance_threshold, "domains": domains}
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()[:20]


def open_targets(store: Store, profile_id: int) -> list[dict]:
    return [{"id": r["id"], "lab": json.loads(r["lab_json"]), "source_plan_id": r["source_plan_id"], "proposal_id": r["proposal_id"]}
            for r in store.query("SELECT * FROM target_color WHERE profile_id=? ORDER BY id", (profile_id,))]


def _fit(samples: list[dict], axes):
    X = np.array([_norm([s["parameters"][k] for k in PROCESS_KEYS], axes) for s in samples])
    Y = np.array([s["lab"] for s in samples])
    mu, sd = Y.mean(axis=0), Y.std(axis=0)
    sd[sd < 1e-9] = 1.0
    kernel = ConstantKernel(1.0, "fixed") * RBF(LENGTH_SCALE, "fixed") + WhiteKernel(NOISE, "fixed")
    gp = GaussianProcessRegressor(kernel=kernel, optimizer=None, normalize_y=False).fit(X, (Y - mu) / sd)
    return gp, mu, sd, X


def propose(store: Store, profile_id: int, seed: int = 1729, size: int = DEFAULT_SIZE,
            pulse_widths: list[float] | None = None, line_intervals: list[float] | None = None,
            pass_counts: list[float] | None = None) -> dict:
    """Return the stored proposal for this database state, creating it if it is new."""
    if int(size) != size or not 1 <= size <= MAX_SIZE:
        raise DesignerError(f"the proposal size must be a whole number between 1 and {MAX_SIZE}")
    if int(seed) != seed:
        raise DesignerError("the seed must be a whole number")
    profile = pf.get_profile(store, profile_id)
    if pulse_widths is None:
        pulse_widths = ([float(s["pulse_width_ns"]) for s in profile["device"]["passport"]["pulse_steps"]]
                        if profile.get("device") else [200.0])
    pulse_widths = sorted(set(pf._finite(v, "pulse width", True) for v in pulse_widths))
    line_intervals = sorted(set(pf._finite(v, "line interval", True) for v in (line_intervals or [0.025, 0.05, 0.1])))
    pass_counts = sorted(set(pass_counts or [1, 2, 3]))
    if not pulse_widths or not line_intervals or not pass_counts:
        raise DesignerError("each of the six process settings needs at least one candidate value")
    if any(int(v) != v or v < 1 for v in pass_counts):
        raise DesignerError("pass counts must be positive whole numbers")
    pass_counts = [int(v) for v in pass_counts]
    if profile.get("device"):
        from . import devices
        for width in pulse_widths:
            devices.require_selectable(profile["device"]["passport"], width)
    axes = _all_axes(profile, pulse_widths, line_intervals, pass_counts)
    domains = {"pulse_widths": pulse_widths, "line_intervals": line_intervals, "passes": pass_counts,
               "power_frequency_speed_bounds": [{k: a[k] for k in ("key", "min", "max")} for a in axes[:3]]}
    samples = list(model.knowledge_summaries(store, profile_id).values())
    targets = open_targets(store, profile_id)
    rules = pf.get_rules(store, profile_id)
    sig = signature(profile_id, samples, targets, int(size), rules["variance_threshold"], domains)
    row = store.one("SELECT id FROM proposal WHERE profile_id=? AND base_signature=? AND seed=?", (profile_id, sig, int(seed)))
    if row is not None:
        return get_proposal(store, row["id"])

    rng = np.random.default_rng(int(seed))
    cand = []
    for _ in range(N_CANDIDATES):
        continuous = _denorm(rng.random(3), axes[:3])
        cand.append(continuous + [float(rng.choice(pulse_widths)), float(rng.choice(line_intervals)), float(rng.choice(pass_counts))])
    unstable = model.unstable_regions(samples, rules["variance_threshold"])
    instab = {}
    for u in unstable:
        vec = [u["parameters"][k] for k in PROCESS_KEYS]
        cand.append(vec)
        instab[tuple(vec)] = min(1.0, u["variance"] / (2 * rules["variance_threshold"]))
    cand = np.array(cand, float)
    X = np.array([_norm(c, axes) for c in cand])
    measured = np.array([_norm([s["parameters"][k] for k in PROCESS_KEYS], axes) for s in samples]) if samples else np.zeros((0, 6))
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
        notes.append(f"fewer than {MIN_SETS_FOR_MODEL} measured parameter sets: the model is not fitted, so candidates are chosen by gap only and target colors cannot be addressed yet")
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
        raise DesignerError("no candidate parameter sets are available in the profile's axis ranges")
    params = []
    for pk in picks:
        i = pk["i"]
        params.append({**{k: (int(cand[i][j]) if k == "passes" else float(cand[i][j])) for j, k in enumerate(PROCESS_KEYS)}, "reason": pk["reason"],
                       "utility": pk["utility"], "scores": {k: float(scores[i, j]) for j, k in enumerate(ORDER)},
                       "target_id": pk["target_id"], "estimated_distance_to_target": pk["est"]})
    data = {"parameters": params, "target_ids": sorted({p["target_id"] for p in params if p["target_id"] is not None}), "size": size,
            "notes": notes, "domains": domains, "model": {"measured_sets": len(samples), "gaussian_process": len(samples) >= MIN_SETS_FOR_MODEL,
                                                               "dimensions": len(PROCESS_KEYS)},
            "unaddressed_targets": sorted({t["id"] for t in targets} - {p["target_id"] for p in params if p["target_id"] is not None})}
    with store.transaction():
        pid = store.execute("INSERT INTO proposal(profile_id,base_signature,seed,data_json,created_at) VALUES (?,?,?,?,?)",
                            (profile_id, sig, int(seed), json.dumps(data), now())).lastrowid
        for tid in data["target_ids"]:
            store.execute("UPDATE target_color SET proposal_id=? WHERE id=? AND proposal_id IS NULL", (pid, tid))
    return get_proposal(store, pid)


def get_proposal(store: Store, proposal_id: int) -> dict:
    row = store.one("SELECT * FROM proposal WHERE id=?", (proposal_id,))
    if row is None:
        raise KeyError(f"proposal {proposal_id} not found")
    d = dict(row)
    d.update(json.loads(d.pop("data_json")))
    d["boards"] = [r["id"] for r in store.query("SELECT id FROM plate WHERE proposal_id=? ORDER BY id", (proposal_id,))]
    return d


def list_proposals(store: Store, profile_id: int) -> list[dict]:
    return [get_proposal(store, r["id"]) for r in store.query("SELECT id FROM proposal WHERE profile_id=? ORDER BY id DESC", (profile_id,))]


def create_plates(store: Store, proposal_id: int, cell_w: float, cell_h: float, gap: float) -> list[dict]:
    """Create one P×F grid per proposed speed/pulse/interval/pass combination.

    Cells the designer did not choose are intersections of that grid and are marked so; the proposal keeps its
    per-set reasons and target references and the plates carry them.
    """
    prop = get_proposal(store, proposal_id)
    if prop["boards"]:
        raise DesignerError("plates were already created for this proposal")
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
    return pl.create_plates(store, prop["profile_id"], series, cell_w, cell_h, gap, proposal_id=proposal_id)


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
