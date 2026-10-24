"""Where a work's measured colours and tonal curves come from (electron REQ-085): the workshop's own measurements, or one connected
laboratory release chosen explicitly with the laser, lens and titanium it measured. Sources are never substituted or combined.

A work keeps its source in ``data_json.evidence_source`` (its *pin*); a work without one uses the own measurements. A pin names the
laboratory and the release by identity and content hash, the laser, lens and titanium by their release UUIDs (and the ids they have in
the release's snapshot, the same in every release of that laboratory), the records withdrawn when it was made (they stay out for this
work), the algorithm versions it was calculated with, and the palette it was confirmed with (``palette_path``: the measured colours and
complete recipes, so that the confirmed result can be shown and exported when the release is gone or the algorithms changed).

The colours and curves of a pinned work are read from the release's snapshot (``lab_import.open_release``) by the same code as the own
ones; everything the work itself is (its picture, its document, its files) stays in the workshop. A pinned work whose release is no
longer on this computer, or whose algorithms changed since, is *frozen*: its confirmed result is kept and not calculated again, and the
reason is shown; updating its source (:func:`preview_update`, then the work's own update) calculates it again.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from . import color, devices, lab_export, lab_import, palette, prediction_store as ps
from . import setup as su
from .db import Store, now

KIND = "release"


@dataclass(frozen=True)
class Evidence:
    """What a work's colours and curves are read from: ``store`` (the workshop, or a release's snapshot) and the laser, lens and titanium
    there. ``frozen`` says why a pinned work keeps its confirmed result instead (``store`` is then None)."""
    store: Store | None
    device_id: int
    lens_id: int | None
    material_id: int | None
    pin: dict | None = None
    frozen: str | None = None

    @property
    def external(self) -> bool:
        return self.pin is not None


def pin_of(plan: Mapping) -> dict | None:
    found = plan.get("evidence_source")
    return found if isinstance(found, Mapping) and found.get("kind") == KIND else None


def setup_of(plan: Mapping) -> tuple[int, int | None]:
    """The laser and lens a work's colours and curves were measured with: its own, or those of its pinned release."""
    pin = pin_of(plan)
    if pin is None:
        return plan["device_id"], plan["lens_id"]
    return pin["laser"]["id"], None if pin["lens"] is None else pin["lens"]["id"]


def material_of(plan: Mapping) -> int | None:
    """The titanium a work's colours were measured on: its pinned release's, or the work's own."""
    pin = pin_of(plan)
    if pin is not None and pin.get("material"):
        return pin["material"]["id"]
    return plan.get("material_id")


def frozen_reason(store: Store, pin: Mapping) -> str | None:
    """Why a pinned work cannot be calculated again now, or None."""
    row = store.one("SELECT status FROM lab_release WHERE release_id=?", (pin["release_id"],))
    if row is None or row["status"] == "removed" or not (lab_import.release_dir(store, pin["release_id"]) / lab_import.FILE).is_file():
        return "the laboratory release of this work is no longer on this computer: its confirmed result is kept; connect the release again or choose another source to calculate it again"
    changed = sorted(k for k, v in lab_export.algorithm_versions().items() if pin["algorithm_versions"].get(k) != v)
    if changed:
        return (f"this work was calculated with other versions of the algorithms ({', '.join(changed)}): its confirmed result is kept and not "
                "calculated again; update its source to calculate it with this version")
    return None


def of(store: Store, plan: Mapping, material_id: int | None = None) -> Evidence:
    """The source of a work: the workshop's own measurements with its laser and lens (and ``material_id``, by default the work's), or
    its pinned release's snapshot with the pinned laser, lens and titanium."""
    pin = pin_of(plan)
    if pin is None:
        return Evidence(store, plan["device_id"], plan["lens_id"], material_id if material_id is not None else plan.get("material_id"))
    device_id, lens_id = setup_of(plan)
    material = pin["material"]["id"] if pin.get("material") else material_id
    reason = frozen_reason(store, pin)
    if reason is not None:
        return Evidence(None, device_id, lens_id, material, pin, reason)
    return Evidence(lab_import.reader(store, pin["release_id"], list(pin["hidden"])), device_id, lens_id, material, pin)


def require(evidence: Evidence) -> Store:
    """The store to calculate from; a frozen work is refused with its reason."""
    if evidence.frozen is not None:
        raise su.ValidationError(evidence.frozen)
    return evidence.store


# -- choosing a source -----------------------------------------------------------------------------------------------------------
def _uuid_of(snapshot: Store, kind: str, local: int | None) -> str | None:
    if local is None:
        return None
    row = snapshot.one("SELECT uuid FROM release_record WHERE kind=? AND local_id=?", (kind, local))
    return row["uuid"] if row else None


def choices(store: Store) -> list[dict]:
    """The connected laboratories a new work can take its colours and curves from (not disconnected, their current release not
    withdrawn): each with its current release and every laser, lens and titanium it measured, with how many photographs."""
    out = []
    for source in lab_import.sources(store):
        current = source["current"]
        if source["status"] != "connected" or current is None or current["status"] == "removed" or source["release_withdrawn"]:
            continue
        snapshot = lab_import.reader(store, current["release_id"], lab_import.hidden(store, source["id"]))
        setups = []
        for row in snapshot.query("SELECT p.device_id, p.lens_id, p.material_id, d.name AS laser, d.manufacturer, d.model, l.focal_length_mm, "
                                  "m.family, m.grade, m.thickness_mm, COUNT(*) AS photographs FROM pair p JOIN laser_device d ON d.id=p.device_id "
                                  "LEFT JOIN lens l ON l.id=p.lens_id LEFT JOIN material_profile m ON m.id=p.material_id WHERE p.status='Accepted' "
                                  "GROUP BY p.device_id, p.lens_id, p.material_id ORDER BY d.name, l.focal_length_mm, m.family, m.grade"):
            setups.append({"laser": {"uuid": _uuid_of(snapshot, "laser", row["device_id"]), "public_name": row["laser"],
                                     "manufacturer": row["manufacturer"], "model": row["model"]},
                           "lens": None if row["lens_id"] is None else {"uuid": _uuid_of(snapshot, "lens", row["lens_id"]),
                                                                        "focal_length_mm": row["focal_length_mm"]},
                           "material": None if row["material_id"] is None else {"uuid": _uuid_of(snapshot, "material", row["material_id"]),
                                                                                "family": row["family"], "grade": row["grade"],
                                                                                "thickness_mm": row["thickness_mm"]},
                           "photographs": row["photographs"]})
        out.append({"source_id": source["id"], "name": source["name"], "release": {k: current[k] for k in (
            "release_id", "release_number", "created_at", "content_sha256", "verified", "terms", "attribution")}, "setups": setups})
    return out


def pin(store: Store, request: Mapping, *, with_material: bool = True) -> dict:
    """A work's pin to a connected release from the user's choice (``release_id``, ``laser``, ``lens`` and, for a vector work,
    ``material``: release UUIDs), checked before anything is calculated: the release is here and its laboratory connected, it is not
    withdrawn, and it measured that laser, lens and titanium."""
    if not isinstance(request, Mapping):
        raise su.ValidationError("choose a laboratory release, its laser, lens and titanium")
    release_id = str(request.get("release_id") or "")
    row = store.one("SELECT r.release_id, r.source_id, r.origin_lab_id, r.content_sha256, r.manifest_json, r.status, s.status AS source_status, "
                    "s.name FROM lab_release r JOIN lab_source s ON s.id=r.source_id WHERE r.release_id=?", (release_id,))
    if row is None or row["status"] == "removed":
        raise su.ValidationError("this laboratory release is not connected: choose a connected laboratory")
    if row["source_status"] != "connected":
        raise su.ValidationError("this laboratory is disconnected: connect it again to use it for new work")
    if store.one("SELECT 1 FROM lab_withdrawal WHERE source_id=? AND target_kind='release' AND target_id=?", (row["source_id"], release_id)):
        raise su.ValidationError("its owner withdrew this release: choose another")
    hidden = lab_import.hidden(store, row["source_id"])
    snapshot = lab_import.reader(store, release_id, hidden)
    laser = _record(snapshot, "laser", request.get("laser"))
    if laser is None:
        raise su.ValidationError("choose a laser this release measured")
    lens = _record(snapshot, "lens", request.get("lens")) if request.get("lens") else None
    if request.get("lens") and lens is None:
        raise su.ValidationError("choose a lens this release measured")
    material = _record(snapshot, "material", request.get("material")) if with_material else None
    if with_material and material is None:
        raise su.ValidationError("choose a titanium this release measured")
    measured = snapshot.one("SELECT COUNT(*) AS n FROM pair WHERE status='Accepted' AND device_id=? AND lens_id IS ? "
                            + ("AND material_id=?" if material else ""),
                            (laser["id"], None if lens is None else lens["id"], *((material["id"],) if material else ())))["n"]
    if not measured:
        raise su.ValidationError("this release measured nothing with this laser, lens and titanium")
    manifest = json.loads(row["manifest_json"])
    device = snapshot.one("SELECT name, manufacturer, model FROM laser_device WHERE id=?", (laser["id"],))
    focal = None if lens is None else snapshot.one("SELECT focal_length_mm FROM lens WHERE id=?", (lens["id"],))["focal_length_mm"]
    stock = None if material is None else snapshot.one("SELECT family, grade, thickness_mm FROM material_profile WHERE id=?", (material["id"],))
    return {"kind": KIND, "release_id": release_id, "source_id": row["source_id"], "origin_lab_id": row["origin_lab_id"], "lab_name": row["name"],
            "content_sha256": row["content_sha256"], "release_created_at": manifest["created_at"],
            "release_algorithm_versions": manifest["algorithm_versions"], "algorithm_versions": lab_export.algorithm_versions(),
            "laser": {**laser, "public_name": device["name"], "manufacturer": device["manufacturer"], "model": device["model"]},
            "lens": None if lens is None else {**lens, "focal_length_mm": focal},
            "material": None if material is None else {**material, **dict(stock)},
            "hidden": hidden, "pinned_at": now()}


def release_palette(store: Store, request: Mapping) -> dict:
    """The colours a vector work would take from a connected release (``request`` as :func:`pin`), before one is made: the release, and
    every colour of its laser, lens and titanium that fills an area as the work's palette has it (measured Lab and sRGB, the basis of
    the measurement, independent engravings, spread and concerns) with its complete recipe; what was left out and why."""
    chosen = pin(store, request)
    snapshot = lab_import.reader(store, chosen["release_id"], chosen["hidden"])
    lens = None if chosen["lens"] is None else chosen["lens"]["id"]
    found = palette.vector_palette(snapshot, chosen["laser"]["id"], lens, chosen["material"]["id"])
    entries = []
    for entry in found["entries"]:
        row = snapshot.one("SELECT parameters_json FROM observation WHERE id=?", (entry["observation_ids"][0],)) if entry["observation_ids"] else None
        entries.append({**entry, "recipe": json.loads(row["parameters_json"]) if row else entry["parameters"]})
    return {"source": summary(store, chosen), "conditions": conditions(store, {"evidence_source": chosen}), **found, "entries": entries}


def release_scales(store: Store, request: Mapping) -> dict:
    """The grey scales a photo work would take from a connected release (``request`` as :func:`pin`, without titanium): every scale its
    laser and lens measured, the best first, as the list of scales gives them."""
    chosen = pin(store, request, with_material=False)
    snapshot = lab_import.reader(store, chosen["release_id"], chosen["hidden"])
    lens = None if chosen["lens"] is None else chosen["lens"]["id"]
    return {"source": summary(store, chosen), "conditions": conditions(store, {"evidence_source": chosen}),
            "scales": ps.scales(snapshot, chosen["laser"]["id"], lens)}


def _record(snapshot: Store, kind: str, record_id) -> dict | None:
    row = snapshot.one("SELECT uuid, local_id FROM release_record WHERE kind=? AND uuid=?", (kind, str(record_id or "")))
    return None if row is None else {"uuid": row["uuid"], "id": row["local_id"]}


def conditions(store: Store, plan: Mapping) -> list[str]:
    """What the user must know about a work's source before its colours are used, in the order shown: none for the own measurements."""
    pin = pin_of(plan)
    if pin is None:
        return []
    out = ["the colours and curves are another laboratory's measurements on its laser: the same colour on this laser is not promised"]
    learned = {w["target_id"] for w in store.query("SELECT target_id FROM lab_withdrawal WHERE source_id=? AND target_kind IN "
                                                    "('measurement', 'tone_profile')", (pin["source_id"],))}
    if learned - set(pin["hidden"]):
        out.append(f"the laboratory withdrew {len(learned - set(pin['hidden']))} of the measurements this work may use: update its source to leave them out")
    if store.one("SELECT 1 FROM lab_withdrawal WHERE source_id=? AND target_kind='release' AND target_id=?", (pin["source_id"], pin["release_id"])):
        out.append("its owner withdrew this release")
    newer = store.one("SELECT current_release_id FROM lab_source WHERE id=?", (pin["source_id"],))
    if newer is not None and newer["current_release_id"] not in (None, pin["release_id"]):
        out.append("a newer release of this laboratory is connected: the work keeps its own until its source is updated")
    reason = frozen_reason(store, pin)
    if reason is not None:
        out.append(reason)
    return out


def shown(store: Store, plan: Mapping) -> dict:
    """The active source of a work as its screen shows it."""
    pin = pin_of(plan)
    if pin is None:
        return {"kind": "own"}
    return {**{k: pin[k] for k in ("kind", "release_id", "source_id", "lab_name", "content_sha256", "release_created_at", "laser", "lens",
                                   "material", "pinned_at", "algorithm_versions")}, "withdrawn_hidden": len(pin["hidden"]),
            "conditions": conditions(store, plan), "frozen": frozen_reason(store, pin), "versions": len(plan.get("source_versions") or [])}


def own_limits(store: Store, device_id: int, layers: list[tuple[str, Mapping]]) -> None:
    """The settings of each named layer, measured on another laboratory's laser, checked against the own laser that engraves them before
    its file is written (REQ-085): power within 0-100 %, the frequency within its repetition rates and the pulse width within its range.
    Settings it cannot take are refused with what is wrong; they are never changed to fit."""
    passport = devices.brief(store, device_id)["passport"]
    low, high = devices.pulse_range(passport)
    for name, settings in layers:
        found = su.check_in_range(passport, settings.get("power"), settings.get("frequency"))
        width = settings.get("pulse_width")
        if width is not None and not low <= width <= high:
            found.append(f"pulse width {width:g} ns is outside the range of this laser ({low:g}-{high:g} ns)")
        if found:
            raise su.ValidationError(f"the layer {name} has settings this laser cannot take: " + "; ".join(found))


# -- updating a work's source ----------------------------------------------------------------------------------------------------
def next_pin(store: Store, plan: Mapping, request: Mapping | None, *, with_material: bool = True) -> dict:
    """The pin a pinned work's source is updated to (an explicit step, never automatic): the release ``request`` names with its laser,
    lens and titanium, by default the current release of the work's laboratory with the laser, lens and titanium the work has now."""
    old = pin_of(plan)
    if old is None:
        raise su.ValidationError("this work uses the workshop's own measurements: a laboratory release is chosen when a work is made")
    wanted = dict(request or {})
    if not wanted.get("release_id"):
        row = store.one("SELECT current_release_id FROM lab_source WHERE id=?", (old["source_id"],))
        wanted["release_id"] = row["current_release_id"] if row else None
    for key in ("laser", "lens", "material"):
        if key not in wanted and old.get(key):
            wanted[key] = old[key]["uuid"]
    new = pin(store, wanted, with_material=with_material)
    same = ("release_id", "hidden", "algorithm_versions")
    if all(new[k] == old[k] for k in same) and all((new[k] or {}).get("uuid") == (old[k] or {}).get("uuid") for k in ("laser", "lens", "material")):
        raise su.ValidationError("the work already uses this release with these measurements: there is nothing to update")
    return new


def previous_pin(plan: Mapping) -> dict:
    """The source a work had before its last update: going back restores it with the result confirmed with it."""
    versions = plan.get("source_versions") or []
    if not versions:
        raise su.ValidationError("this work has no earlier source to go back to")
    return versions[-1]["pin"]


def moved(plan: Mapping, new: dict, back: bool) -> list[dict]:
    """The source history of a work after it moves to ``new``: going back takes the last earlier source off it."""
    versions = list(plan.get("source_versions") or [])
    return versions[:-1] if back else versions + [{"pin": pin_of(plan), "until": now()}]


def summary(store: Store, new: Mapping) -> dict:
    """A pin as a preview of an update shows where the work would go."""
    return {**{k: new[k] for k in ("release_id", "lab_name", "content_sha256", "release_created_at", "laser", "lens", "material")},
            "withdrawn_hidden": len(new["hidden"]), "frozen": frozen_reason(store, new)}


def compared(before: list[dict], after: list[dict], used: set[str]) -> dict:
    """The colours a work uses before and after an update of its source: each one's colour in both, its ΔE, or that the new source has
    not measured it (it cannot be used any more and the work shows it as missing)."""
    old, new = {e["id"]: e for e in before}, {e["id"]: e for e in after}
    rows = []
    for entry_id in sorted(used):
        a, b = old.get(entry_id), new.get(entry_id)
        rows.append({"entry_id": entry_id, "before": None if a is None else {"lab": a["lab"], "srgb": a["srgb"]},
                     "after": None if b is None else {"lab": b["lab"], "srgb": b["srgb"]},
                     "delta_e": None if a is None or b is None else round(color.delta_e(a["lab"], b["lab"]), 3), "missing": b is None})
    changes = [r["delta_e"] for r in rows if r["delta_e"] is not None]
    return {"entries": rows, "missing": sum(r["missing"] for r in rows), "changed": sum(d > 0 for d in changes),
            "max_delta_e": max(changes, default=None)}


# -- the confirmed palette of a pinned work ----------------------------------------------------------------------------------------
def keep_palette(store: Store, entries: list[dict], recipes: Mapping[str, dict]) -> dict:
    """Keep the palette a pinned work was confirmed with, with each entry's complete recipe, in the workshop's files; where it is."""
    data = json.dumps({"entries": [{**e, "recipe": recipes.get(e["id"])} for e in entries]}, sort_keys=True, default=str).encode()
    digest = hashlib.sha256(data).hexdigest()
    path = store.data_dir / "files" / f"source-palette-{digest[:16]}.json"
    if not path.is_file():
        path.write_bytes(data)
    return {"palette_path": str(path), "palette_sha256": digest}


def kept_palette(pin: Mapping) -> list[dict]:
    """The palette a pinned work was confirmed with (:func:`keep_palette`)."""
    path = pin.get("palette_path")
    if not path or not Path(path).is_file():
        raise su.ValidationError("the confirmed colours of this work are missing: choose its source again")
    return json.loads(Path(path).read_text(encoding="utf-8"))["entries"]
