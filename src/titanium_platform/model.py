"""Color-space model: knowledge from eligible observations, estimates and predictions.

Measured values are never changed (REQ-001): everything here is derived on read from the immutable
observation rows and carries the ids of the observations it was derived from. The formulas for confidence,
expected color error and stability are an explicit assumption (proposed DEC-029); the requirements define
only that all three must accompany every prediction (REQ-002).
"""
from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from . import color
from .db import Store

CONFIDENCE_K = 2.0


def parameters_key(p: dict) -> str:
    return f"{p['power']:g}|{p['frequency']:g}|{p['speed']:g}"


def eligible_observations(store: Store, profile_id: int) -> list[dict]:
    """Observations that may inform the model (chart-gated, comparable layers only), oldest first."""
    out = []
    for r in store.query("SELECT * FROM observation WHERE profile_id=? AND model_eligible=1 ORDER BY id", (profile_id,)):
        out.append({"id": r["id"], "pair_id": r["pair_id"], "engraving_id": r["engraving_id"], "lab": json.loads(r["lab_json"]),
                    "parameters": json.loads(r["parameters_json"]), "repeat_eligible": bool(r["repeat_eligible"]),
                    "context": json.loads(r["context_json"]), "alignment": r["alignment_method"]})
    return out


def _by_engraving(obs: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for o in obs:
        groups.setdefault(o["engraving_id"], []).append(o)
    return groups


def summarize(obs: list[dict]) -> dict:
    """Derived values for the observations that share one parameter vector."""
    groups = _by_engraving(obs)
    per_engraving = np.array([np.mean([o["lab"] for o in g], axis=0) for g in groups.values()])
    independent = len({o["engraving_id"] for o in obs if o["repeat_eligible"]})
    n = len(per_engraving)
    lab = per_engraving.mean(axis=0)
    if n >= 2:
        variance = float(np.var(per_engraving, axis=0, ddof=1).sum())
        deviations = [color.delta_e(x, lab) for x in per_engraving]
        stability = {"assessed": True, "variance": variance, "max_deviation": max(deviations), "engravings": n}
    else:
        variance, deviations = None, [0.0]
        stability = {"assessed": False, "variance": None, "max_deviation": None, "engravings": n}
    repeat_devs = [color.delta_e(o["lab"], np.mean([x["lab"] for x in g], axis=0)) for g in groups.values() if len(g) > 1 for o in g]
    rig = {"assessed": bool(repeat_devs), "photos": max(len(g) for g in groups.values()),
           "mean_delta_e": float(np.mean(repeat_devs)) if repeat_devs else None}
    expected = None if variance is None else math.sqrt(variance) + (rig["mean_delta_e"] or 0.0)
    confidence = n / (n + CONFIDENCE_K) if variance is not None else None
    return {"lab": [float(v) for v in lab], "observation_ids": [o["id"] for o in obs], "observations": len(obs),
            "independent_engravings": independent, "engravings": n, "stability": stability, "rig_repeatability": rig,
            "expected_delta_e": expected, "confidence": confidence, "available": variance is not None,
            "context_groups": context_groups(obs)}


def context_groups(obs: list[dict]) -> list[dict]:
    """Group repeats by material batch and focus; unknown context is labelled, never merged into a known group."""
    groups: dict[tuple, list[dict]] = {}
    for o in obs:
        c = o["context"]
        groups.setdefault((c.get("batch"), c.get("focus")), []).append(o)
    out = []
    for (batch, focus), g in groups.items():
        labs = np.array([o["lab"] for o in g])
        out.append({"batch": batch, "focus": focus, "batch_known": batch is not None, "focus_known": focus is not None,
                    "observations": len(g), "mean_lab": [float(v) for v in labs.mean(axis=0)]})
    return out


def attribution_note(groups: list[dict]) -> str | None:
    """REQ-010/016: say plainly when unknown context prevents attributing a deviation."""
    if len(groups) < 2 and not any(not g["batch_known"] or not g["focus_known"] for g in groups):
        return None
    unknown = [g for g in groups if not g["batch_known"] or not g["focus_known"]]
    if unknown:
        return "Context is unknown for some repeats: a deviation cannot be attributed to material batch or focus for those."
    return None


def knowledge_summaries(store: Store, profile_id: int) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for o in eligible_observations(store, profile_id):
        groups.setdefault(parameters_key(o["parameters"]), []).append(o)
    out = {}
    for key, obs in groups.items():
        s = summarize(obs)
        s["parameters"] = obs[0]["parameters"]
        s["key"] = key
        s["attribution_note"] = attribution_note(s["context_groups"])
        out[key] = s
    return out


def coverage_box(samples: list[dict]) -> tuple[np.ndarray, np.ndarray] | None:
    labs = np.array([s["lab"] for s in samples if s["available"]])
    return None if labs.size == 0 else (labs.min(axis=0), labs.max(axis=0))


def predict_for_lab(samples: list[dict], target_lab) -> dict:
    """Nearest available measured sample for a requested color. Never returns a partial prediction (REQ-002)."""
    if not color.valid_lab(target_lab):
        raise ValueError("target color is not a valid Lab value")
    avail = [s for s in samples if s["available"]]
    if not avail:
        return {"available": False, "reason": "not enough data for a prediction", "outside_coverage": True}
    best = min(avail, key=lambda s: (color.delta_e(s["lab"], target_lab), s["key"]))
    lo, hi = coverage_box(avail)
    t = np.asarray(target_lab, float)
    outside = bool((t < lo).any() or (t > hi).any())
    return {"available": True, "outside_coverage": outside, "key": best["key"], "parameters": best["parameters"], "lab": best["lab"],
            "confidence": best["confidence"], "expected_delta_e": best["expected_delta_e"], "stability": best["stability"],
            "distance_to_target": color.delta_e(best["lab"], target_lab), "observation_ids": best["observation_ids"]}


def unstable_regions(samples: list[dict], variance_threshold: float | None) -> list[dict]:
    """Parameter sets whose repeats vary more than the configured threshold (REQ-001). Needs a saved threshold."""
    if variance_threshold is None:
        return []
    return [{"key": s["key"], "variance": s["stability"]["variance"], "parameters": s["parameters"]}
            for s in samples if s["stability"]["assessed"] and s["stability"]["variance"] > variance_threshold]
