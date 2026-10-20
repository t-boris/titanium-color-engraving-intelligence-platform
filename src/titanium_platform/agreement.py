"""The colour of a setting is the colour its independent engravings agree on (REQ-045, DEC-083).

A recipe (the same settings on the same laser, lens and titanium) is engraved more than once as the work goes on, and the
engravings do not always give one colour. This module turns the colours of its independent engravings (a re-photograph is
not one, DEC-021; the callers pass one mean colour per engraving) into the colour of the recipe and a confidence in it:

* two engravings AGREE when their colours differ by at most :data:`AGREEMENT_DE` (CIE76, DEC-026);
* the colour of the recipe is the mean of the largest group of engravings that agree with one another (each within the limit of
  a representative engraving); an engraving outside the group does not move it, so one stale or wrong measurement cannot invent
  a colour nobody measured. When two groups are equally large the one holding the newest engraving wins: a recipe first yellow
  and engraved again dark brown is dark brown;
* ``trust`` = k² / ((k + K) · n) with k the engravings in the group, n all of them and K = :data:`CONFIDENCE_K`. It grows with
  every further engraving that agrees and falls with every one that differs; when all agree it is n / (n + K) as the model always
  gave it (0.5, 0.6, 0.67 for two, three, four). One engraving has 1/3: less than a repeated colour, more than a contradicted one;
* ``confidence`` is ``trust`` once the colour was repeated (n ≥ 2) and None for a single engraving, which cannot be assessed
  (REQ-002: a metric that is not supported is unavailable, not invented); ``trust`` is what colours are ranked by;
* a recipe is CONTRADICTED when n ≥ 2 and the group is not a strict majority (2k ≤ n): its colour changes under the same
  settings, so it is not to be taken until further engravings settle it.

Nothing here reads or writes the database: measurements stay unchanged and everything is derived on every read (REQ-001).
"""
from __future__ import annotations

import numpy as np

AGREEMENT_DE = 5.0       # engravings of one recipe agree within this ΔE; an assumption (DEC-083), real repeats lie at 0.8-4.1, conflicts at 7-23
CONFIDENCE_K = 2.0       # the prior of the confidence formula (DEC-029)


def trust_of(agreeing: int, engravings: int) -> float:
    """k² / ((k + K) · n): the confidence in a colour that ``agreeing`` of ``engravings`` engravings give."""
    return agreeing * agreeing / ((agreeing + CONFIDENCE_K) * engravings)


SINGLE = trust_of(1, 1)  # the rank of a colour engraved once: below a repeated colour, above a contradicted one


def consensus(engravings: list[dict], limit: float = AGREEMENT_DE) -> dict:
    """The agreed colour of a recipe from its independent engravings, each ``{"lab": [L, a, b], "when": sortable}`` (``when``
    orders them in time; missing means the oldest). ``members`` are the indexes (into ``engravings``) of the agreeing group."""
    n = len(engravings)
    if n == 0:
        raise ValueError("a recipe needs at least one engraving")
    labs = np.asarray([e["lab"] for e in engravings], float)
    when = [e.get("when") or ("", 0) for e in engravings]
    distance = np.linalg.norm(labs[:, None, :] - labs[None, :, :], axis=2)
    groups = [[j for j in range(n) if distance[i, j] <= limit] for i in range(n)]

    def rank(i: int):
        group = groups[i]
        return len(group), max(when[j] for j in group), -float(distance[i, group].mean()), -i

    members = groups[max(range(n), key=rank)]
    k = len(members)
    trust = trust_of(k, n)
    return {"lab": [float(v) for v in labs[members].mean(axis=0)], "members": members, "engravings": n, "agreeing": k,
            "differing": n - k, "confidence": trust if n >= 2 else None, "trust": trust, "contradicted": n >= 2 and 2 * k <= n,
            "limit": limit}


def shown(found: dict) -> dict:
    """The part of :func:`consensus` a screen or an API shows: the counts and the verdict, not the indexes."""
    return {k: found[k] for k in ("engravings", "agreeing", "differing", "contradicted", "limit")}


def doubtful(found: dict) -> bool:
    """A colour whose circle on the colour map is smaller than that of one engraving never repeated (DEC-084, REQ-049): more of its
    engravings differ from the agreed colour than repeats agree with it, ``agreeing - 1 - differing < 0``. A colour engraved once is not
    doubtful, it is only not assessed. ``found`` is :func:`consensus` or :func:`shown`."""
    return found["agreeing"] - 1 - found["differing"] < 0


def trust(entry: dict) -> float:
    """The rank of an entry that carries ``confidence`` (a palette entry, a colour map result): its confidence, else that of a
    colour engraved once."""
    value = entry.get("confidence")
    return SINGLE if value is None else float(value)
