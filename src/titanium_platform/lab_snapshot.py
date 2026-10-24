"""The snapshot of a connected laboratory release (electron REQ-084): a store with the main schema in which the release's records are
accepted photographs with their observations and tonal profiles, so that the colour map, the palettes and the tonal curves are made from
it by the same code as at the author's workshop and give the same numbers (REQ-083: within 1e-6 for the same data and algorithm versions).

A release names no files, so each pair of the snapshot has none: the row length of every measured layer is stored with it
(``pair_row_length``) and its cleaning witness is an observation in that role. Every record keeps its release UUID in
``release_record``; the snapshot's own ids are:

* a laser, lens and titanium stock record: the first 52 bits of its UUID, the same in every release of a laboratory, so the recipe of a
  palette entry (which names them) stays the same when a saved work moves to a newer release (REQ-085);
* a pair (a capture) and an observation (a measurement): its place in the release (``seq`` + 1), so that their order is the author's,
  which breaks ties as it did there;
* an experiment: in the order first named.

Names are labels: a laser is named as its owner published it, an engraving ``E0001``..., a photograph ``P00001``..., a layer as the
release labels it. The snapshot is written once, by :class:`Builder`, and read only from then on (:func:`open_snapshot`)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Iterable, Mapping

from . import colormap, lab_format as lf, plans as pl
from .db import Store

RECORDS = """
CREATE TABLE IF NOT EXISTS release_record (uuid TEXT PRIMARY KEY, kind TEXT NOT NULL, local_id INTEGER, seq INTEGER, layer INTEGER,
    digest TEXT);
CREATE TABLE IF NOT EXISTS release_withdrawal (id TEXT PRIMARY KEY, target_kind TEXT NOT NULL, target_id TEXT NOT NULL,
    reason TEXT NOT NULL, replacement_release_id TEXT, declared_at TEXT NOT NULL);
"""
RELEASE = "lab.release"             # setting of a snapshot: the manifest and the laboratory record it was built from
VERSION = "1"                       # how a release is laid out in a snapshot; a snapshot of another version is built again from its file
PUBLISHED_WORK = "Published work"   # an experiment of a release that was neither a test nor a vector work
MODE_OF = {"test": pl.MODE_PLATE, "vector_work": pl.MODE_VECTOR, "other": PUBLISHED_WORK}
ROLE_OF = {"test_feature": "test feature", "cleaning_witness": colormap.WITNESS, "service": colormap.SERVICE[0]}
MODE_OF_KIND = {"calibrated": "reference_chart_corrected", "relative": "raw_camera_relative"}
FLOATS = ("power", "frequency", "speed", "pulse_width", "line_interval", "scan_angle", "angle_increment")
INTEGERS = ("passes", "global_passes")


def local_id(text: str) -> int:
    """The snapshot id of a laser, lens or titanium stock record: the first 52 bits of its UUID (stable across releases)."""
    return int(uuid.UUID(text).hex[:13], 16)


def _float(value):
    return None if value is None else float(value)


def _parameters(parameters: Mapping) -> dict:
    """The settings of a measurement with the number types they are stored with at the author's (JSON writes 1.0 as 1)."""
    out = dict(parameters)
    for key in FLOATS:
        if out.get(key) is not None and not isinstance(out[key], bool):
            out[key] = float(out[key])
    for key in INTEGERS:
        if out.get(key) is not None and not isinstance(out[key], bool):
            out[key] = int(out[key])
    return out


class Builder:
    """Writes the snapshot of one release in ``folder`` record by record, in the order the release holds them, checking that every id is
    new and every reference names a record already written. Nothing is visible to the workshop until the importer moves the folder in."""

    def __init__(self, folder: str | Path):
        self.store = Store(folder)
        self.conn = self.store.conn
        self.conn.executescript(RECORDS)
        self.conn.execute("BEGIN")
        self.setups: dict[str, tuple[int, int | None]] = {}
        self.engravings: dict[str, int] = {}
        self.when = "1970-01-01T00:00:00.000000Z"

    # -- references --------------------------------------------------------------------------------------------------------------
    def _register(self, record_id: str, kind: str, local: int | None, seq: int | None, layer: int | None = None) -> None:
        try:
            self.conn.execute("INSERT INTO release_record(uuid, kind, local_id, seq, layer) VALUES (?,?,?,?,?)", (record_id, kind, local, seq, layer))
        except sqlite3.IntegrityError:
            raise lf.FormatError("duplicate_id", f"the id {record_id} is used twice") from None

    def _local(self, record_id: str | None, kind: str) -> int | None:
        if record_id is None:
            return None
        row = self.conn.execute("SELECT kind, local_id FROM release_record WHERE uuid=?", (record_id,)).fetchone()
        if row is None or row["kind"] != kind:
            raise lf.FormatError("reference", f"{kind} {record_id} is named before it is given, or is not a {kind}")
        return row["local_id"]

    # -- records -------------------------------------------------------------------------------------------------------------------
    def add(self, section: str, record: Mapping) -> None:
        """Write one record; its digest (of its canonical form) tells a later release whether it changed."""
        getattr(self, "_" + section)(record)
        digest = hashlib.sha256(lf.canonical(record).encode()).hexdigest()
        self.conn.execute("UPDATE release_record SET digest=? WHERE uuid=?", (digest, record["id"]))

    def _equipment(self, r: Mapping) -> None:
        laser, lens = r["laser"], r["lens"]
        laser_id = local_id(laser["id"])
        passport = {k: laser.get(k) for k in ("rated_power_w", "wavelength_nm") if laser.get(k) is not None}
        self.conn.execute("INSERT OR IGNORE INTO laser_device(id, name, manufacturer, model, serial, description, data_json, created_at, updated_at) "
                          "VALUES (?,?,?,?,NULL,NULL,?,?,?)", (laser_id, laser["public_name"], laser.get("manufacturer"), laser.get("model"),
                                                               json.dumps(passport), self.when, self.when))
        lens_id = None
        if lens is not None:
            lens_id = local_id(lens["id"])
            focal = lens.get("focal_length_mm")
            self.conn.execute("INSERT OR IGNORE INTO lens(id, name, focal_length_mm, field_mm, expansion, note, created_at, spot_diameter_um) "
                              "VALUES (?,?,?,?,?,NULL,?,?)", (lens_id, f"F {focal:g} mm" if focal else "Lens", focal, lens.get("field_mm"),
                                                             lens.get("expansion") if lens.get("expansion") is not None else 1.0, self.when,
                                                             lens.get("spot_diameter_um")))
        self._register(r["id"], "setup", None, r["seq"])
        for record_id, kind, local in ((laser["id"], "laser", laser_id), (None if lens is None else lens["id"], "lens", lens_id)):
            if record_id is not None:            # a laser or lens of several setups is one record; its UUID names it for a work's source
                self.conn.execute("INSERT OR IGNORE INTO release_record(uuid, kind, local_id) VALUES (?,?,?)", (record_id, kind, local))
        self.setups[r["id"]] = (laser_id, lens_id)

    def _materials(self, r: Mapping) -> None:
        material_id = local_id(r["id"])
        name = " ".join(x for x in (r["family"], r.get("grade")) if x) or "Titanium"
        self.conn.execute("INSERT INTO material_profile(id, name, family, batch, grade, thickness_mm, surface, created_at) "
                          "VALUES (?,?,?,NULL,?,?,NULL,?)", (material_id, f"{name} ({r['seq'] + 1})", r["family"], r.get("grade"),
                                                            _float(r.get("thickness_mm")), self.when))
        self._register(r["id"], "material", material_id, r["seq"])

    def _captures(self, r: Mapping) -> None:
        if r["equipment_id"] not in self.setups:
            raise lf.FormatError("reference", f"capture {r['id']} names equipment the release does not give")
        laser_id, lens_id = self.setups[r["equipment_id"]]
        material_id = self._local(r["material_id"], "material")
        plan_id = None
        if r["experiment"] is not None:
            found = self.conn.execute("SELECT kind, local_id FROM release_record WHERE uuid=?", (r["experiment"]["id"],)).fetchone()
            if found is None:
                cur = self.conn.execute("INSERT INTO plan(name, mode, status, device_id, lens_id, data_json, created_at) VALUES (?,?,?,?,?,?,?)",
                                        ("", MODE_OF[r["experiment"]["kind"]], "Exported" if r["experiment"]["kept"] else "Superseded",
                                         laser_id, lens_id, "{}", r["measured_at"]))
                plan_id = cur.lastrowid
                self.conn.execute("UPDATE plan SET name=? WHERE id=?", (f"X{plan_id:04d}", plan_id))
                self._register(r["experiment"]["id"], "plan", plan_id, None)
            elif found["kind"] != "plan":
                raise lf.FormatError("reference", f"experiment {r['experiment']['id']} is not an experiment")
            else:
                plan_id = found["local_id"]
        engraving = self.engravings.setdefault(r["engraving_id"], len(self.engravings) + 1)
        pair_id = r["seq"] + 1
        check = {"color_measurement": {"mode": "reference_chart_corrected" if r["basis"] == "chart" else "raw_camera_relative"},
                 "composition": {"picture_over_fills": bool(r["over_fills"])}, "layers": []}
        self.conn.execute("INSERT INTO pair(id, status, device_id, lens_id, material_id, plan_id, engraving_id, engraving_title, lightburn_name, "
                          "lightburn_path, photo_name, photo_path, context_json, data_json, hardware_json, created_at, accepted_at) "
                          "VALUES (?,'Accepted',?,?,?,?,?,?,?,'',?,'',?,?,'{}',?,?)",
                          (pair_id, laser_id, lens_id, material_id, plan_id, r["engraving_id"], f"E{engraving:04d}", f"E{engraving:04d}",
                           f"P{pair_id:05d}", json.dumps({"batch": "known"} if r["batch_known"] else {}), json.dumps({"check": check}),
                           r["measured_at"], r["measured_at"]))
        self._register(r["id"], "capture", pair_id, r["seq"])

    def _measurements(self, r: Mapping) -> None:
        pair_id = self._local(r["capture_id"], "capture")
        pair = self.conn.execute("SELECT device_id, lens_id, engraving_id, created_at FROM pair WHERE id=?", (pair_id,)).fetchone()
        observation_id = r["seq"] + 1
        evidence = {"role": ROLE_OF[r["layer"]["role"]], "layer_name": r["layer"]["label"],
                    "color_measurement": {"mode": MODE_OF_KIND[r["kind"]]}, "task": dict(r["task"])}
        if r["matrix"]:
            evidence["matrix_cell"] = True
        if r.get("transfer_of"):
            evidence["transfer_of"] = dict(r["transfer_of"])
        self.conn.execute("INSERT INTO observation(id, pair_id, layer_index, device_id, lens_id, engraving_id, lab_json, parameters_json, "
                          "alignment_method, context_json, model_eligible, repeat_eligible, eligibility_reason, evidence_json, created_at, task_kind) "
                          "VALUES (?,?,?,?,?,?,?,?,'published','{}',?,?,'',?,?,?)",
                          (observation_id, pair_id, r["layer"]["index"], pair["device_id"], pair["lens_id"], pair["engraving_id"],
                           json.dumps([float(v) for v in r["lab"]]), json.dumps(_parameters(r["parameters"])), int(r["model_eligible"]),
                           int(r["repeat_eligible"]), json.dumps(evidence), pair["created_at"], r["task"]["kind"]))
        self.conn.execute("INSERT OR IGNORE INTO pair_row_length(pair_id, layer_index, row_mm) VALUES (?,?,?)",
                          (pair_id, r["layer"]["index"], _float(r["row_mm"])))
        self._register(r["id"], "measurement", observation_id, r["seq"])

    def _tone_profiles(self, r: Mapping) -> None:
        pair_id = self._local(r["capture_id"], "capture")
        if r["measurement_id"] is not None:
            self._local(r["measurement_id"], "measurement")
        s = r["settings"]
        rep = {"index": r["layer"]["index"], "name": r["layer"]["label"], "type": s.get("type"), "power": _float(s.get("power")),
               "frequency_khz": _float(s.get("frequency_khz")), "speed": _float(s.get("speed")), "pulse_width": _float(s.get("pulse_width")),
               "line_interval": _float(s.get("line_interval")), "passes": s.get("passes"), "global_passes": s.get("global_passes"),
               "image": {k: v for k, v in r["image"].items() if v is not None},
               "tonal": {"evidence": r["evidence"], "power_range": None if r["power_range"] is None else [float(v) for v in r["power_range"]],
                         "adjustments": dict(r["adjustments"]), "measured_by": r["measured_by"],
                         "bins": [{**{k: (int(v) if k == "n" else float(v)) for k, v in step.items() if v is not None},
                                   **({"power_pct": None} if "power_pct" in step and step["power_pct"] is None else {})}
                                  for step in r["bins"]]}}
        if s.get("pulse_width") is None and s.get("pulse_width_effective") is not None:
            rep["supplied_settings"] = {"pulse_width": {"value": float(s["pulse_width_effective"])}}
        if r.get("task") is not None:
            rep["task"] = dict(r["task"])
        self.conn.execute("UPDATE pair SET data_json=json_insert(data_json, '$.check.layers[#]', json(?)) WHERE id=?", (json.dumps(rep), pair_id))
        self.conn.execute("INSERT OR IGNORE INTO pair_row_length(pair_id, layer_index, row_mm) VALUES (?,?,?)",
                          (pair_id, r["layer"]["index"], _float(r["row_mm"])))
        self._register(r["id"], "tone_profile", pair_id, r["seq"], r["layer"]["index"])

    def _provenance(self, r: Mapping) -> None:
        self._register(r["id"], "provenance", None, r["seq"])
        self.conn.execute("INSERT INTO release_withdrawal(id, target_kind, target_id, reason, replacement_release_id, declared_at) "
                          "VALUES (?,?,?,?,?,?)", (r["id"], r["target_kind"], r["target_id"], r["reason"], r.get("replacement_release_id"),
                                                   r["declared_at"]))

    # -- the end -------------------------------------------------------------------------------------------------------------------
    def start(self, manifest: Mapping, lab: Mapping) -> None:
        self.when = manifest["created_at"]
        self.store.conn.execute("INSERT INTO setting(key, value_json) VALUES (?,?)",
                                (RELEASE, json.dumps({"manifest": dict(manifest), "lab": dict(lab), "version": VERSION})))

    def finish(self) -> None:
        self.conn.execute("COMMIT")
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.store.close()

    def abandon(self) -> None:
        if self.conn.in_transaction:
            self.conn.execute("ROLLBACK")
        self.store.close()


def build(folder: str | Path, stream, **read_options) -> dict:
    """The snapshot of the release read from the binary ``stream`` (``lab_format.read``) written in ``folder``; returns the manifest.
    Any problem raises and leaves ``folder`` for the caller to remove."""
    builder = Builder(folder)
    try:
        for kind, value in lf.read(stream, **read_options):
            if kind == "manifest":
                manifest = value
            elif kind == "lab":
                builder.start(manifest, value)
            elif kind in lf.SECTIONS:
                builder.add(kind, value)
        builder.finish()
    except BaseException:
        builder.abandon()
        raise
    return manifest


def open_snapshot(folder: str | Path, hidden: Iterable[str] = ()) -> Store:
    """The snapshot in ``folder`` for reading: nothing written through it reaches the file. The measurements and tonal profiles whose
    UUIDs are ``hidden`` (withdrawn by their owner) are left out of what this connection sees, the file keeping them as published: a
    temporary view named ``observation`` stands before the table for every query of this connection only."""
    store = Store(folder)
    hidden = list(hidden)
    if hidden:
        conn = store.conn
        conn.execute("CREATE TEMP TABLE hidden_record (uuid TEXT PRIMARY KEY)")
        conn.executemany("INSERT OR IGNORE INTO temp.hidden_record(uuid) VALUES (?)", [(u,) for u in hidden])
        conn.execute("CREATE TEMP VIEW observation AS SELECT o.* FROM main.observation o WHERE NOT EXISTS ("
                     "SELECT 1 FROM main.release_record r JOIN temp.hidden_record h ON h.uuid=r.uuid WHERE "
                     "(r.kind='measurement' AND r.local_id=o.id) OR (r.kind='tone_profile' AND r.local_id=o.pair_id AND r.layer=o.layer_index))")
    store.conn.execute("PRAGMA query_only = ON")
    return store


def differences(old: Store, new: Store) -> dict:
    """What a newer release of a laboratory adds, changes and removes against an older one, by record UUID and digest; counts by kind and
    the first few UUIDs of each. Both are read in UUID order, so memory does not grow with the releases."""
    out = {"added": {}, "changed": {}, "removed": {}, "examples": {"added": [], "changed": [], "removed": []}}

    def note(what, kind, record_id):
        out[what][kind] = out[what].get(kind, 0) + 1
        if len(out["examples"][what]) < 20:
            out["examples"][what].append(record_id)

    sql = "SELECT uuid, kind, digest FROM release_record ORDER BY uuid"
    a, b = old.conn.execute(sql), new.conn.execute(sql)
    x, y = a.fetchone(), b.fetchone()
    while x is not None or y is not None:
        if y is None or (x is not None and x["uuid"] < y["uuid"]):
            note("removed", x["kind"], x["uuid"])
            x = a.fetchone()
        elif x is None or y["uuid"] < x["uuid"]:
            note("added", y["kind"], y["uuid"])
            y = b.fetchone()
        else:
            if x["digest"] != y["digest"]:
                note("changed", y["kind"], y["uuid"])
            x, y = a.fetchone(), b.fetchone()
    return out


def release_of(store: Store) -> dict:
    """The manifest and laboratory record a snapshot was built from."""
    return store.get_setting(RELEASE) or {}
