"""Where a number on a screen comes from: the observations behind a knowledge entry, a finding or a colour, resolved to their photographs
(feature ux-growing-collections-p0, REQ-002).

A screen that shows “observations #4, #5, #9, …” as a count and an expandable list asks here, a page of numbers at a time, for the photograph
and layer each number belongs to, so that every number is a link to the analysis of its photograph and none is lost when the list is long.
"""
from __future__ import annotations

from .db import Store

REFS_MAX = 200                     # numbers resolved by one request


def observation_refs(store: Store, ids: list[int]) -> list[dict]:
    """For each observation number, in the order given and without repeats: ``pair_id`` (the photograph the analysis is under), the layer, the
    photograph's file name and its state. A number that is no observation comes back with ``pair_id`` None, never dropped."""
    wanted = list(dict.fromkeys(int(i) for i in ids))[:REFS_MAX]
    if not wanted:
        return []
    marks = ",".join("?" * len(wanted))
    rows = {r["id"]: r for r in store.query(
        "SELECT o.id, o.pair_id, o.layer_index, json_extract(o.evidence_json, '$.layer_name') AS layer_name, p.photo_name, p.status "
        f"FROM observation o JOIN pair p ON p.id=o.pair_id WHERE o.id IN ({marks})", wanted)}
    return [{"id": i, "pair_id": rows[i]["pair_id"], "layer_index": rows[i]["layer_index"], "layer_name": rows[i]["layer_name"],
             "photo_name": rows[i]["photo_name"], "status": rows[i]["status"]} if i in rows
            else {"id": i, "pair_id": None, "layer_index": None, "layer_name": None, "photo_name": None, "status": None} for i in wanted]
