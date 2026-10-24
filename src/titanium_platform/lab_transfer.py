"""Transfer experiments (feature electron REQ-085, «Проверить у себя»): a colour of a connected laboratory release engraved on the own
laser to see what it gives there. The release's complete recipe becomes a test plate of one cell on the own laser with the lens on it
now; the own laser's limits are checked first and settings it cannot take are refused, never changed to fit. The plate is an own
experiment like any other: photographed and accepted, it is measured with the own laser, lens, titanium and conditions, and its colour
is compared with the release's by ΔE. The release stays as it was: the author's observation is not changed and its independent
engravings are not counted up, because the own measurement is never one of the release's.

The plate's plan keeps where its recipe came from (``data_json.transfer``): the laboratory, the release and its content hash, the
palette colour and the release identities of its observations, and the colour the release measured, so that the comparison stays
readable after the release is disconnected or removed.
"""
from __future__ import annotations

import json
from typing import Mapping

import numpy as np

from . import color, evidence_source as es, ingest as ig, lab_import, plans as pl
from . import setup as su
from .db import Store, now

CELL_MM = 10.0                       # the side of the plate's one cell
SCAN = ("global_passes", "bidirectional", "cross_hatch", "scan_angle", "angle_increment")
NUMBERS = ("power", "frequency", "speed", "pulse_width", "line_interval")


def create(store: Store, request: Mapping) -> dict:
    """A transfer plate of one palette colour of a connected release (``release_id``, its ``laser``, ``lens`` and ``material`` as release
    identities, the colour's ``entry_id``) on the own laser ``device_id`` for the own titanium ``material_id``: the plate and its plan,
    as a plate series makes them, with the recipe's every setting on its cell."""
    if not isinstance(request, Mapping):
        raise su.ValidationError("choose a colour of a connected laboratory release to check on this laser")
    offered = es.release_palette(store, request)
    entry = next((e for e in offered["entries"] if e["id"] == request.get("entry_id")), None)
    if entry is None:
        raise su.ValidationError("choose a colour of this release's palette to check on this laser")
    device = store.one("SELECT id FROM laser_device WHERE id=?", (request.get("device_id"),)) if isinstance(request.get("device_id"), int) else None
    if device is None:
        raise su.ValidationError("choose the laser of this workshop the colour is checked on")
    material = store.one("SELECT id, name, grade, thickness_mm FROM material_profile WHERE id=?", (request.get("material_id"),)) \
        if isinstance(request.get("material_id"), int) else None
    if material is None:
        raise su.ValidationError("choose the titanium of this workshop the colour is checked on")
    recipe = dict(entry["recipe"])
    es.own_limits(store, device["id"], [(f"«{entry['id'][:8]}»", recipe)])
    chosen = es.pin(store, request)
    snapshot = lab_import.reader(store, chosen["release_id"], chosen["hidden"])
    observations = [r["uuid"] for r in snapshot.query(
        f"SELECT uuid FROM release_record WHERE kind='measurement' AND local_id IN ({','.join('?' * len(entry['observation_ids']))}) ORDER BY uuid",
        tuple(entry["observation_ids"]))] if entry["observation_ids"] else []
    transfer = {"release_id": chosen["release_id"], "source_id": chosen["source_id"], "origin_lab_id": chosen["origin_lab_id"],
                "lab_name": chosen["lab_name"], "content_sha256": chosen["content_sha256"], "entry_id": entry["id"],
                "observations": observations, "laser": chosen["laser"], "lens": chosen["lens"], "material": chosen["material"],
                "source": {"lab": entry["lab"], "srgb": entry["srgb"], "engravings": entry["engravings"], "basis": entry["basis"]},
                "recipe": recipe, "own_material": dict(material), "created_at": now()}
    made = pl.create_plates(store, device["id"], [{
        "speed": recipe["speed"], "powers": [recipe["power"]], "frequencies": [recipe["frequency"]], "pulse_width": recipe["pulse_width"],
        "line_interval": recipe["line_interval"], "passes": recipe.get("passes") or 1,
        "lightburn_settings": {k: recipe[k] for k in SCAN if recipe.get(k) is not None}, "recipe": recipe,
        "data": {"transfer": transfer}}], CELL_MM, CELL_MM, 0.0)[0]
    store.audit("lab_transfer_created", plan_id=made["plan_id"], release_id=chosen["release_id"], entry_id=entry["id"])
    return {**made, "transfer": _shown(transfer)}


def _shown(transfer: Mapping) -> dict:
    return {k: transfer[k] for k in ("release_id", "lab_name", "content_sha256", "entry_id", "observations", "laser", "lens", "material",
                                      "source", "recipe", "own_material", "created_at")}


def compare(store: Store, plan_id: int) -> dict:
    """A transfer plate and what its accepted photographs measured on the own laser: each measurement with the own laser, lens and
    titanium it was engraved with and its ΔE to the release's colour; their mean ΔE once there is one."""
    row = store.one("SELECT id, name, plan_identifier, device_id, lens_id, data_json FROM plan WHERE id=?", (plan_id,))
    transfer = json.loads(row["data_json"]).get("transfer") if row else None
    if transfer is None:
        raise KeyError(f"there is no transfer experiment {plan_id}")
    recipe = transfer["recipe"]
    own = []
    for o in store.query("SELECT o.id, o.lab_json, o.parameters_json, o.device_id, o.lens_id, o.created_at, p.id AS pair_id, p.material_id "
                         "FROM observation o JOIN pair p ON p.id=o.pair_id WHERE p.plan_id=? AND p.status=? ORDER BY o.id", (plan_id, ig.ST_ACCEPTED)):
        settings = json.loads(o["parameters_json"])
        if any(settings.get(k) is None or abs(float(settings[k]) - float(recipe[k])) > 1e-6 for k in NUMBERS):
            continue                       # the cleaning and the markers of the plate are not the colour checked
        lab = json.loads(o["lab_json"])
        own.append({"observation_id": o["id"], "pair_id": o["pair_id"], "device_id": o["device_id"], "lens_id": o["lens_id"],
                    "material_id": o["material_id"], "lab": lab, "srgb": [int(v) for v in np.clip(color.lab_to_srgb8(np.asarray([lab], np.float64))[0], 0, 255)],
                    "delta_e": round(color.delta_e(lab, transfer["source"]["lab"]), 3), "measured_at": o["created_at"]})
    return {"plan_id": row["id"], "name": row["name"], "identifier": row["plan_identifier"], "device_id": row["device_id"],
            "lens_id": row["lens_id"], **_shown(transfer), "measurements": own,
            "mean_delta_e": round(sum(m["delta_e"] for m in own) / len(own), 3) if own else None}


def listing(store: Store, release_id: str | None = None) -> list[dict]:
    """Every transfer experiment, the newest first; of one release when ``release_id`` is given."""
    rows = store.query("SELECT id FROM plan WHERE json_extract(data_json, '$.transfer.release_id') IS NOT NULL AND COALESCE(status, '')!='Deleted' "
                       + ("AND json_extract(data_json, '$.transfer.release_id')=? " if release_id else "") + "ORDER BY id DESC",
                       (release_id,) if release_id else ())
    return [compare(store, r["id"]) for r in rows]
