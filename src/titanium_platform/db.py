"""Local SQLite store (DEC-020). One file, no network.

Measured observations are immutable (REQ-001): SQL triggers reject UPDATE and DELETE as a backstop and
``Store.update_observation`` rejects and logs the attempt in the audit table.

Every record of work names the physical laser (``device_id``) and the lens record used for it (``lens_id``, NULL when the
lens is unknown) (DEC-063). A database written before 0.4.0 named them through a laser profile: opening it migrates once,
after a backup, every table that still has ``profile_id``; the old id stays as ``legacy_profile_id`` for provenance and the
``laser_profile`` table stays as a read-only archive that nothing reads.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import migrations

SCHEMA_RELEASE = "0.4.0"
SCHEMA = """
CREATE TABLE IF NOT EXISTS lens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    focal_length_mm REAL,
    field_mm REAL,
    expansion REAL NOT NULL DEFAULT 1,
    note TEXT,
    created_at TEXT NOT NULL,
    spot_diameter_um REAL
);
CREATE TABLE IF NOT EXISTS laser_device (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    manufacturer TEXT,
    model TEXT,
    serial TEXT,
    description TEXT,
    data_json TEXT NOT NULL,
    lens_id INTEGER REFERENCES lens(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS device_document (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES laser_device(id),
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS material_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    family TEXT NOT NULL,
    batch TEXT,
    grade TEXT,
    thickness_mm REAL,
    surface TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capture_setup (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    camera TEXT NOT NULL,
    lighting TEXT NOT NULL,
    angle TEXT NOT NULL,
    reference_chart TEXT NOT NULL,
    raw_format INTEGER NOT NULL DEFAULT 1,
    chart_detection_verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS setting (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL UNIQUE,
    device_id INTEGER NOT NULL REFERENCES laser_device(id),
    lens_id INTEGER REFERENCES lens(id),
    legacy_profile_id INTEGER,
    speed REAL NOT NULL,
    geometry_json TEXT NOT NULL,
    cells_json TEXT NOT NULL,
    proposal_id INTEGER,
    lens_json TEXT,
    material_id INTEGER REFERENCES material_profile(id),
    test_type TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    device_id INTEGER NOT NULL REFERENCES laser_device(id),
    lens_id INTEGER REFERENCES lens(id),
    legacy_profile_id INTEGER,
    plate_id INTEGER REFERENCES plate(id),
    markers INTEGER NOT NULL DEFAULT 0,
    plan_identifier TEXT,
    band_count INTEGER,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    research_session_id INTEGER REFERENCES research_session(id)
);
CREATE TABLE IF NOT EXISTS pair (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    device_id INTEGER NOT NULL REFERENCES laser_device(id),
    lens_id INTEGER REFERENCES lens(id),
    legacy_profile_id INTEGER,
    stand_id INTEGER REFERENCES capture_setup(id),
    material_id INTEGER REFERENCES material_profile(id),
    plate_id INTEGER REFERENCES plate(id),
    plan_id INTEGER REFERENCES plan(id),
    engraving_id TEXT NOT NULL,
    engraving_title TEXT,
    lightburn_name TEXT NOT NULL,
    lightburn_path TEXT NOT NULL,
    photo_name TEXT NOT NULL,
    photo_path TEXT NOT NULL,
    context_json TEXT NOT NULL,
    data_json TEXT NOT NULL,
    hardware_json TEXT,
    created_at TEXT NOT NULL,
    accepted_at TEXT
);
CREATE TABLE IF NOT EXISTS observation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id INTEGER NOT NULL REFERENCES pair(id),
    layer_index INTEGER NOT NULL,
    device_id INTEGER NOT NULL REFERENCES laser_device(id),
    lens_id INTEGER REFERENCES lens(id),
    legacy_profile_id INTEGER,
    engraving_id TEXT NOT NULL,
    lab_json TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    alignment_method TEXT NOT NULL,
    context_json TEXT NOT NULL,
    model_eligible INTEGER NOT NULL,
    repeat_eligible INTEGER NOT NULL,
    eligibility_reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS observation_no_update BEFORE UPDATE ON observation
BEGIN SELECT RAISE(ABORT, 'observations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS observation_no_delete BEFORE DELETE ON observation
BEGIN SELECT RAISE(ABORT, 'observations are immutable'); END;
CREATE TABLE IF NOT EXISTS capability_finding (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id INTEGER NOT NULL REFERENCES pair(id),
    purpose TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    parameters_json TEXT,
    evidence_json TEXT NOT NULL,
    next_test TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(pair_id, purpose)
);
CREATE TABLE IF NOT EXISTS research_session (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES laser_device(id),
    lens_id INTEGER NOT NULL REFERENCES lens(id),
    material_id INTEGER NOT NULL REFERENCES material_profile(id),
    goal TEXT NOT NULL,
    target TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES research_session(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_trace_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_memory (
    session_id INTEGER PRIMARY KEY REFERENCES research_session(id),
    through_message_id INTEGER NOT NULL,
    summary TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_insight (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES research_session(id),
    purpose TEXT NOT NULL,
    claim TEXT NOT NULL,
    confidence TEXT NOT NULL,
    evidence_pair_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_message_session_idx ON research_message(session_id,id);
CREATE INDEX IF NOT EXISTS research_insight_session_idx ON research_insight(session_id,id);
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES laser_device(id),
    lens_id INTEGER REFERENCES lens(id),
    legacy_profile_id INTEGER,
    parameters_key TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    stage TEXT NOT NULL,
    questioned INTEGER NOT NULL DEFAULT 0,
    doubt_json TEXT,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS knowledge_setup_recipe ON knowledge(device_id, IFNULL(lens_id, 0), parameters_key);
CREATE TABLE IF NOT EXISTS knowledge_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_id INTEGER NOT NULL REFERENCES knowledge(id),
    at TEXT NOT NULL,
    type TEXT NOT NULL,
    from_stage TEXT,
    to_stage TEXT,
    reason TEXT NOT NULL,
    observation_ids_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS target_color (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES laser_device(id),
    lens_id INTEGER REFERENCES lens(id),
    legacy_profile_id INTEGER,
    lab_json TEXT NOT NULL,
    source_plan_id INTEGER NOT NULL,
    source_color_key TEXT NOT NULL,
    proposal_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE (source_plan_id, source_color_key)
);
CREATE TABLE IF NOT EXISTS proposal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES laser_device(id),
    lens_id INTEGER REFERENCES lens(id),
    legacy_profile_id INTEGER,
    base_signature TEXT NOT NULL,
    seed INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    explanation TEXT,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS proposal_setup_signature ON proposal(device_id, IFNULL(lens_id, 0), base_signature, seed);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    action TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
"""


# Portable laboratories (electron REQ-083..085), created by ``Store._migrate`` in a workshop of any age.
LAB_SCHEMA = """
-- A portable identity is a UUID given once to a local record and kept in every later release (DEC-024): ``kind`` names the record
-- (laser, lens, material, setup, plan, engraving, pair, observation, tonal), ``local_key`` its key here.
CREATE TABLE IF NOT EXISTS portable_id (kind TEXT NOT NULL, local_key TEXT NOT NULL, uuid TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
    PRIMARY KEY (kind, local_key));
-- The row length of a measured layer where its LightBurn file is not kept: the snapshot of a connected release (``row_length.recorded``).
CREATE TABLE IF NOT EXISTS pair_row_length (pair_id INTEGER NOT NULL REFERENCES pair(id), layer_index INTEGER NOT NULL, row_mm REAL,
    PRIMARY KEY (pair_id, layer_index));
-- Releases this workshop wrote: what was chosen and the manifest.
CREATE TABLE IF NOT EXISTS lab_export (release_id TEXT PRIMARY KEY, content_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
    manifest_json TEXT NOT NULL, selection_json TEXT NOT NULL, bytes INTEGER NOT NULL);
-- Connected laboratories and their releases (REQ-084). A release never changes: its identity and hash are fixed and a newer one is
-- another row; ``status`` says whether it is the one in use (active), kept for saved works (kept) or gone from disk (removed).
CREATE TABLE IF NOT EXISTS lab_source (id INTEGER PRIMARY KEY AUTOINCREMENT, origin_lab_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
    origin TEXT NOT NULL, url TEXT, status TEXT NOT NULL, current_release_id TEXT, update_checks TEXT NOT NULL DEFAULT 'manual',
    connected_at TEXT NOT NULL, disconnected_at TEXT, last_checked_at TEXT, last_check_json TEXT);
CREATE TABLE IF NOT EXISTS lab_release (release_id TEXT PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES lab_source(id),
    origin_lab_id TEXT NOT NULL, release_number INTEGER, content_sha256 TEXT NOT NULL, schema_version TEXT NOT NULL,
    manifest_json TEXT NOT NULL, lab_json TEXT NOT NULL, compatibility_json TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0,
    retrieved_at TEXT NOT NULL, bytes INTEGER NOT NULL, status TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS lab_release_identity BEFORE UPDATE OF release_id, source_id, origin_lab_id, release_number, content_sha256,
    schema_version, manifest_json, lab_json ON lab_release BEGIN SELECT RAISE(ABORT, 'a laboratory release never changes'); END;
-- What the owners of connected laboratories withdrew, as this workshop learned it; kept for ever.
CREATE TABLE IF NOT EXISTS lab_withdrawal (id INTEGER PRIMARY KEY AUTOINCREMENT, source_id INTEGER NOT NULL REFERENCES lab_source(id),
    target_kind TEXT NOT NULL, target_id TEXT NOT NULL, reason TEXT NOT NULL, replacement_release_id TEXT, declared_at TEXT NOT NULL,
    learned_at TEXT NOT NULL, learned_from TEXT NOT NULL, UNIQUE (source_id, target_kind, target_id));
CREATE TRIGGER IF NOT EXISTS lab_withdrawal_kept BEFORE UPDATE ON lab_withdrawal
    BEGIN SELECT RAISE(ABORT, 'a withdrawal is kept as it was learned'); END;
CREATE TRIGGER IF NOT EXISTS lab_withdrawal_not_deleted BEFORE DELETE ON lab_withdrawal
    BEGIN SELECT RAISE(ABORT, 'a withdrawal is kept as it was learned'); END;
"""

REBUILT = ("plate", "plan", "pair", "observation", "knowledge", "target_color", "proposal")   # had profile_id before 0.4.0
SNAPSHOT_LENS = {      # where a record of 0.3.1 remembered the lens it was made with: its column and the JSON paths of the lens id
    "plate": ("lens_json", ("$.id",)), "plan": ("data_json", ("$.lens.id", "$.experiment.lens.id")), "pair": ("hardware_json", ("$.lens.id",))}
ARCHIVE_TRIGGERS = [f"CREATE TRIGGER IF NOT EXISTS laser_profile_read_only_{event.lower()} BEFORE {event} ON laser_profile "
                    "BEGIN SELECT RAISE(ABORT, 'laser profiles are a read-only archive'); END" for event in ("INSERT", "UPDATE", "DELETE")]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def statements(script: str) -> list[str]:
    """The complete SQL statements of a script, trigger bodies included."""
    out, pending = [], ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            out.append(pending.strip())
            pending = ""
    return out


def _schema_for(table: str) -> tuple[str, list[str]]:
    """The CREATE TABLE statement of ``table`` in SCHEMA and the indexes and triggers SCHEMA defines on it."""
    found = statements(SCHEMA)
    create = next(sql for sql in found if sql.startswith(f"CREATE TABLE IF NOT EXISTS {table} ("))
    attached = [sql for sql in found if sql.startswith(("CREATE UNIQUE INDEX", "CREATE INDEX", "CREATE TRIGGER"))
                and re.search(rf"\bON {table}\b", sql)]
    return create, attached


class ImmutableError(RuntimeError):
    """An attempt to change a stored measurement was rejected (REQ-001)."""


MigrationError = migrations.MigrationError      # an older database cannot be migrated as it is; it was left unchanged


def open_store(data_dir: str | Path, program: str = "titanium-platform") -> "Store":
    """The store a program starts on. A database the migration refuses stops the program with the reason, one paragraph,
    and exit code 2, without a traceback (DEC-063)."""
    try:
        return Store(data_dir)
    except MigrationError as exc:
        print(f"{program}: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


class Store:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        (self.data_dir / "files").mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "titanium.sqlite"
        self._lock = threading.RLock()
        migrations.acquire(self.data_dir)                 # one program at a time on a workshop (electron REQ-080, REQ-081)
        self._held = True
        self.conn = self._copy = None
        try:
            self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")
            if self._needs_rebuild():
                self._migrate_from_profiles()
            plan = migrations.prepare(self.conn, self.data_dir, self._copy)   # a newer schema is refused; an older one gets its recovery copy first
            self.conn.executescript(SCHEMA)
            self._migrate()
            migrations.finish(self.conn, plan)
        except BaseException:
            if self.conn is not None:
                self.conn.close()
            self.close()
            raise

    def _columns(self, table: str) -> dict[str, sqlite3.Row]:
        return {row["name"]: row for row in self.conn.execute(f"PRAGMA table_info({table})")}

    def _needs_rebuild(self) -> bool:
        """An older version's tables: a record still names a laser profile, or a lens needs a focal length (REQ-019)."""
        focal = self._columns("lens").get("focal_length_mm")
        return any("profile_id" in self._columns(t) for t in REBUILT) or bool(focal is not None and focal["notnull"])

    def _migrate(self) -> None:
        """Additive, idempotent changes to tables that an older version already created (DEC-035).

        A new column is nullable and an older version ignores columns it does not know.
        """
        for table, column, definition in (
                ("laser_device", "lens_id", "INTEGER REFERENCES lens(id)"),   # DEC-041
                ("material_profile", "grade", "TEXT"),
                ("material_profile", "thickness_mm", "REAL"),
                ("material_profile", "surface", "TEXT"),
                ("plate", "status", "TEXT"),                        # NULL: in use; 'Deleted' with its archived plan (DEC-047)
                ("capture_setup", "chart_reference_json", "TEXT"),   # NULL: the published chart values (DEC-025)
                ("capability_finding", "updated_at", "TEXT"),       # NULL: never recalculated to another text (REQ-022)
                ("observation", "task_kind", "TEXT"),               # NULL: accepted before tasks, derived from its layer (REQ-020)
                ("lens", "spot_diameter_um", "REAL")):              # NULL: not measured with this lens (REQ-019)
            if column not in self._columns(table):
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        # A target colour records every measurement of a plate cell that addressed it (REQ-006): the measured Lab, delta E
        # to the target and the tolerance it was judged by.
        self.conn.execute("CREATE TABLE IF NOT EXISTS target_check (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                          "target_id INTEGER NOT NULL REFERENCES target_color(id), pair_id INTEGER NOT NULL REFERENCES pair(id), "
                          "observation_id INTEGER NOT NULL REFERENCES observation(id), cell_id TEXT NOT NULL, measured_lab_json TEXT NOT NULL, "
                          "delta_e REAL, tolerance REAL, within_tolerance INTEGER, comparable INTEGER NOT NULL, created_at TEXT NOT NULL, "
                          "UNIQUE(target_id, observation_id))")
        # Analysis of the accumulated work (REQ-022): every run is kept with its trigger and inputs, and its findings with it; a
        # finding's history is the findings of the same key across runs. A recalculated capability finding keeps the version
        # it replaced, and a proposal records every change of its status. A finding names its laser, lens and stock as they were
        # (no reference): a gap may name a lens no record of work uses, which must stay deletable.
        self.conn.execute("CREATE TABLE IF NOT EXISTS analysis_run (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, "
                          "trigger TEXT NOT NULL, summary_json TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS finding (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                          "run_id INTEGER NOT NULL REFERENCES analysis_run(id), key TEXT NOT NULL, kind TEXT NOT NULL, "
                          "device_id INTEGER, lens_id INTEGER, material_id INTEGER, task TEXT, data_json TEXT NOT NULL, UNIQUE(run_id, key))")
        self.conn.execute("CREATE INDEX IF NOT EXISTS finding_key_run ON finding(key, run_id)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS capability_finding_history (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                          "finding_id INTEGER NOT NULL REFERENCES capability_finding(id), status TEXT NOT NULL, summary TEXT NOT NULL, "
                          "parameters_json TEXT, evidence_json TEXT NOT NULL, next_test TEXT NOT NULL, valid_from TEXT NOT NULL, "
                          "replaced_at TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS proposal_event (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                          "proposal_id INTEGER NOT NULL REFERENCES proposal(id), at TEXT NOT NULL, from_status TEXT, "
                          "to_status TEXT NOT NULL, reason TEXT NOT NULL, note TEXT, finding_id INTEGER REFERENCES finding(id))")
        self.conn.executescript(LAB_SCHEMA)
        self.conn.execute("UPDATE pair SET hardware_json='{}' WHERE hardware_json IS NULL")
        for engraving in self.conn.execute("SELECT DISTINCT engraving_id FROM pair"):
            known = self.conn.execute("SELECT engraving_title FROM pair WHERE engraving_id=? AND engraving_title IS NOT NULL LIMIT 1",
                                      (engraving["engraving_id"],)).fetchone()
            first = self.conn.execute("SELECT lightburn_name FROM pair WHERE engraving_id=? ORDER BY id LIMIT 1",
                                      (engraving["engraving_id"],)).fetchone()
            title = known["engraving_title"] if known else Path(first["lightburn_name"]).stem
            self.conn.execute("UPDATE pair SET engraving_title=? WHERE engraving_id=? AND engraving_title IS NULL",
                              (title, engraving["engraving_id"]))
        # Freeze the equipment association on older imports before any future lens edits. A plate's
        # stored snapshot takes precedence over the lens record.
        for row in self.conn.execute(
                "SELECT pa.id,pa.device_id,pa.lens_id,d.name,d.manufacturer,d.model,d.serial,d.data_json,"
                "l.name AS lens_name,l.focal_length_mm,l.field_mm,l.expansion,l.spot_diameter_um AS lens_spot,t.lens_json "
                "FROM pair pa JOIN laser_device d ON d.id=pa.device_id LEFT JOIN lens l ON l.id=pa.lens_id "
                "LEFT JOIN plate t ON t.id=pa.plate_id WHERE pa.hardware_json='{}'"):
            if row["lens_json"]:
                lens = json.loads(row["lens_json"])
            elif row["lens_id"] is not None:
                lens = {"id": row["lens_id"], "name": row["lens_name"], "focal_length_mm": row["focal_length_mm"],
                        "field_mm": row["field_mm"], "expansion": row["expansion"],
                        "spot_diameter_um": row["lens_spot"] if row["lens_spot"] is not None
                        else json.loads(row["data_json"]).get("spot_diameter_um")}
            else:
                lens = None
            hardware = {"device": {k: row[k] for k in ("device_id", "name", "manufacturer", "model", "serial")}, "lens": lens}
            self.conn.execute("UPDATE pair SET hardware_json=? WHERE id=?", (json.dumps(hardware), row["id"]))
        self._move_spot_to_lens()

    def _move_spot_to_lens(self) -> None:
        """A measured spot belongs to the lens it was measured with, not to the laser (REQ-019): a lens swap must not carry it
        to another lens. A value an older version kept in the laser passport moves, once, to the lens installed on that
        laser (a value the lens already has is kept); the move is recorded in the audit with the value. A laser without
        an installed lens names no lens to give it to: the value then stays only in the audit. An empty passport field is
        dropped without a record."""
        self.conn.execute("UPDATE laser_device SET data_json=json_remove(data_json, '$.spot_diameter_um') "
                          "WHERE json_type(data_json, '$.spot_diameter_um') = 'null'")
        rows = self.conn.execute("SELECT id, lens_id, data_json FROM laser_device "
                                 "WHERE json_extract(data_json, '$.spot_diameter_um') IS NOT NULL").fetchall()
        for device in rows:
            passport = json.loads(device["data_json"])
            spot = passport.pop("spot_diameter_um")
            lens = (self.conn.execute("SELECT spot_diameter_um FROM lens WHERE id=?", (device["lens_id"],)).fetchone()
                    if device["lens_id"] is not None else None)
            with self.transaction():
                if lens is not None and lens["spot_diameter_um"] is None:
                    self.conn.execute("UPDATE lens SET spot_diameter_um=? WHERE id=?", (spot, device["lens_id"]))
                self.conn.execute("UPDATE laser_device SET data_json=? WHERE id=?", (json.dumps(passport), device["id"]))
                self.conn.execute("INSERT INTO audit(at, action, detail_json) VALUES (?,?,?)", (
                    now(), "spot_moved_to_lens" if lens is not None else "spot_measurement_without_lens",
                    json.dumps({"device_id": device["id"], "lens_id": device["lens_id"], "spot_diameter_um": spot,
                                "lens_kept_its_own": None if lens is None else lens["spot_diameter_um"]})))

    # -- migration of a database written before 0.4.0 (DEC-063) -------------------------------------------------
    def _migrate_from_profiles(self) -> None:
        """Rebuild every table that still names its laser and lens through a laser profile, the lens table, and the
        profiles themselves as an archive.

        Everything happens while this connection holds the write lock: a second process starting at the same moment
        waits and then finds nothing to do. The mapping is worked out and checked first, and a database it cannot map is
        refused unchanged. Then a copy of the database is saved and the tables are rebuilt in one transaction (SQLite's
        procedure for a changed table: create, copy, drop, rename). Every row keeps its id and every stored value and
        keeps its profile id as ``legacy_profile_id``. Its laser is the profile's; its lens is the lens its own snapshot
        names (a plate's or plan's lens, a photograph's hardware), else the profile's, and every row where the two differ
        is listed in the audit. Rules saved per profile move to that laser and lens.
        """
        self.conn.execute("PRAGMA foreign_keys = OFF")      # tables are dropped and renamed; checked before the commit
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                if self._needs_rebuild():
                    self._rebuild_all()
                self.conn.execute("COMMIT")
            except BaseException:
                if self.conn.in_transaction:
                    self.conn.execute("ROLLBACK")
                raise
        finally:
            self.conn.execute("PRAGMA foreign_keys = ON")

    def _rebuild_all(self) -> None:
        mapping = self._profile_setups()
        self._check_mappable(mapping)
        rules, discarded = self._rules_by_setup(mapping)
        backup = self._copy = self._backup()
        sequences = {r["name"]: r["seq"] for r in self.conn.execute("SELECT name, seq FROM sqlite_sequence")} \
            if self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone() else {}
        self.conn.execute("CREATE TEMP TABLE profile_setup (profile_id INTEGER PRIMARY KEY, device_id INTEGER, lens_id INTEGER)")
        self.conn.executemany("INSERT INTO temp.profile_setup VALUES (?,?,?)",
                              [(pid, m["device_id"], m["lens_id"]) for pid, m in mapping.items()])
        counts, own_lens = {}, {}
        for table in REBUILT:
            if "profile_id" in self._columns(table):
                counts[table] = self._rebuild(table, sequences)
                differing = [list(r) for r in self.conn.execute(
                    f"SELECT t.id, m.lens_id, t.lens_id FROM {table} t JOIN temp.profile_setup m ON m.profile_id=t.legacy_profile_id "
                    "WHERE t.lens_id IS NOT m.lens_id ORDER BY t.id")]
                if differing:
                    own_lens[table] = differing          # [row id, lens of its profile, lens of its own record]
        focal = self._columns("lens").get("focal_length_mm")
        if focal is not None and focal["notnull"]:
            counts["lens"] = self._rebuild("lens", sequences)
        if self._columns("laser_profile"):
            counts["laser_profile"] = self._archive_profiles(sequences)
        self.conn.execute("DROP TABLE temp.profile_setup")
        for old in [r["key"] for r in self.conn.execute("SELECT key FROM setting WHERE key LIKE 'rules:%'")]:
            if old.split(":", 1)[1].isdigit() and mapping.get(int(old.split(":", 1)[1]), {}).get("device_id") is not None:
                self.conn.execute("DELETE FROM setting WHERE key=?", (old,))
        for key, value in rules.items():
            self.conn.execute("INSERT OR REPLACE INTO setting(key, value_json) VALUES (?,?)", (key, json.dumps(value["rules"])))
        broken = [tuple(r) for r in self.conn.execute("PRAGMA foreign_key_check")
                  if r[0] in REBUILT + ("lens",) or r[2] in REBUILT + ("lens",)]
        if broken:
            raise MigrationError(f"cannot migrate the database to {SCHEMA_RELEASE}: references would break {broken[:5]}; "
                                 "the database was left unchanged")
        self.conn.execute("INSERT INTO audit(at, action, detail_json) VALUES (?,?,?)", (now(), "schema_migrated", json.dumps({
            "release": SCHEMA_RELEASE, "backup": str(backup), "rows": counts,
            "profiles": {str(pid): {k: m[k] for k in ("device_id", "lens_id")} for pid, m in mapping.items()},
            "lens_from_own_record": own_lens,
            "rules": {key: value["from"] for key, value in rules.items()}, "rules_discarded": discarded})))

    def _profile_setups(self) -> dict[int, dict]:
        """The laser and lens of every laser profile. A profile without its own lens takes the lens installed on its
        laser, which is what the previous version froze it to on every start."""
        columns = self._columns("laser_profile")
        if not columns:
            return {}
        device = "p.device_id" if "device_id" in columns else "NULL"
        own = "p.lens_id" if "lens_id" in columns else "NULL"
        installed = ("(SELECT d.lens_id FROM laser_device d WHERE d.id=p.device_id)"
                     if "device_id" in columns and "lens_id" in self._columns("laser_device") else "NULL")
        return {r["id"]: {"name": r["name"], "device_id": r["device_id"], "lens_id": r["lens_id"]} for r in self.conn.execute(
            f"SELECT p.id, p.name, {device} AS device_id, COALESCE({own}, {installed}) AS lens_id FROM laser_profile p")}

    def _check_mappable(self, mapping: dict[int, dict]) -> None:
        """Refuse a database whose records cannot be given a laser, or whose knowledge would collide; say what to do."""
        devices = {r["id"] for r in self.conn.execute("SELECT id FROM laser_device")} if self._columns("laser_device") else set()
        lenses = {r["id"] for r in self.conn.execute("SELECT id FROM lens")} if self._columns("lens") else set()
        refusals, without_laser = [], {}
        for table in REBUILT:
            if "profile_id" not in self._columns(table):
                continue
            for row in self.conn.execute(f"SELECT profile_id, COUNT(*) AS n FROM {table} GROUP BY profile_id"):
                m = mapping.get(row["profile_id"])
                if m is None:
                    refusals.append(f"{row['n']} {table} rows name laser profile {row['profile_id']}, which does not exist")
                elif m["device_id"] is None:
                    without_laser[row["profile_id"]] = m["name"]
                elif m["device_id"] not in devices or (m["lens_id"] is not None and m["lens_id"] not in lenses):
                    refusals.append(f"laser profile {row['profile_id']} ({m['name']}) names a laser or lens that does not exist")
        for table, columns in (("knowledge", "parameters_key"), ("proposal", "base_signature, seed")):
            if "profile_id" not in self._columns(table):
                continue
            seen: dict[tuple, int] = {}
            for row in self.conn.execute(f"SELECT id, profile_id, {columns} FROM {table}"):
                m = mapping.get(row["profile_id"]) or {}
                key = (m.get("device_id"), m.get("lens_id"), *tuple(row)[2:])
                if key in seen:
                    refusals.append(f"{table} rows {seen[key]} and {row['id']} would become one entry of the same laser and lens")
                seen.setdefault(key, row["id"])
        if without_laser:
            names = ", ".join(f"{pid} ({name})" for pid, name in sorted(without_laser.items()))
            if "device_id" not in self._columns("laser_profile"):
                first = ("start version 0.3.1 once on this data directory: it adds the laser link to the profiles and lets you "
                         "create the laser on its laser screen; stop it, then")
            else:
                first = "with the application stopped,"
            refusals.append(
                f"stored records use laser profiles that name no laser: {names}. Version 0.3.1 cannot link a laser to a profile "
                f"that already has records, so {first} set the laser of each of these profiles in the database file itself, "
                f'for example: sqlite3 "{self.path}" "UPDATE laser_profile SET device_id=<laser id> WHERE id=<profile id>" '
                "(the laser ids are in the table laser_device), and start this version again")
        if refusals:
            raise MigrationError(f"cannot migrate the database to {SCHEMA_RELEASE}: " + "; ".join(dict.fromkeys(refusals))
                                 + "; the database was left unchanged")

    def _rules_by_setup(self, mapping: dict[int, dict]) -> tuple[dict[str, dict], dict[str, Any]]:
        """Rules saved per profile, moved to the key of the profile's laser and lens: {new key: {"rules", "from"}}, and the
        rules left out. When profiles of one laser and lens differ, the lowest profile id wins, as 0.3.1 applied the rules
        of that profile to the shared knowledge; the others are returned for the audit. Rules of a profile that names no
        laser stay with the archive."""
        from .setup import setup_key
        rows = [(int(r["key"].split(":", 1)[1]), r) for r in self.conn.execute("SELECT key, value_json FROM setting WHERE key LIKE 'rules:%'")
                if r["key"].split(":", 1)[1].isdigit()]
        kept, discarded = {}, {}
        for pid, row in sorted(rows, key=lambda item: item[0]):
            m = mapping.get(pid)
            if m is None or m["device_id"] is None:
                continue
            target, value = f"rules:{setup_key(m['device_id'], m['lens_id'])}", json.loads(row["value_json"])
            if target not in kept:
                kept[target] = {"rules": value, "from": row["key"]}
            elif kept[target]["rules"] != value:
                discarded[row["key"]] = value
        return kept, discarded

    def _backup(self) -> Path:
        """A copy of the database as it is before the migration, read through a second connection while this one holds
        the write lock (the backup API, so the WAL is included)."""
        folder = self.data_dir / "backups"
        folder.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target, n = folder / f"titanium-before-{SCHEMA_RELEASE}-{stamp}.sqlite", 1
        while target.exists():
            n += 1
            target = folder / f"titanium-before-{SCHEMA_RELEASE}-{stamp}-{n}.sqlite"
        source, copy = sqlite3.connect(self.path), sqlite3.connect(target)
        try:
            source.backup(copy)
        finally:
            copy.close()
            source.close()
        return target

    def _lens_of(self, table: str, old: dict) -> str:
        """SQL for the lens of a migrated row: the lens its own snapshot names, when that lens record exists, else the
        lens of its profile. An observation has the lens of its photograph (``pair`` is rebuilt before it)."""
        if table == "observation":
            return "(SELECT p.lens_id FROM pair p WHERE p.id=t.pair_id)"
        column, paths = SNAPSHOT_LENS.get(table, (None, ()))
        if column not in old:
            return "m.lens_id"
        named = [f"json_extract(t.{column}, '{path}')" for path in paths]
        named = named[0] if len(named) == 1 else f"COALESCE({', '.join(named)})"
        return (f"COALESCE((SELECT l.id FROM lens l WHERE l.id = CASE WHEN json_valid(t.{column}) THEN {named} END), "
                "m.lens_id)")

    def _rebuild(self, table: str, sequences: dict[str, int]) -> int:
        """Recreate ``table`` with its definition in SCHEMA and copy every row unchanged; returns the number of rows."""
        create, attached = _schema_for(table)
        old = self._columns(table)
        self.conn.execute(create.replace(f"CREATE TABLE IF NOT EXISTS {table} (", f"CREATE TABLE {table}__new (", 1))
        new = self._columns(f"{table}__new")
        dropped = set(old) - set(new) - {"profile_id"}
        if dropped:
            raise MigrationError(f"cannot migrate the database to {SCHEMA_RELEASE}: the columns {sorted(dropped)} of {table} "
                                 "would be lost; the database was left unchanged")
        columns, values = [], []
        for column in new:
            if column == "device_id" and "profile_id" in old:
                columns.append(column)
                values.append("m.device_id")
            elif column == "lens_id" and "profile_id" in old:
                columns.append(column)
                values.append(self._lens_of(table, old))
            elif column == "legacy_profile_id" and "profile_id" in old:
                columns.append(column)
                values.append("t.profile_id")
            elif column in old:
                columns.append(column)
                values.append(f"t.{column}")
        join = " JOIN temp.profile_setup m ON m.profile_id=t.profile_id" if "profile_id" in old else ""
        self.conn.execute(f"INSERT INTO {table}__new ({','.join(columns)}) SELECT {','.join(values)} FROM {table} t{join}")
        copied = self._replace(table, sequences)
        for sql in attached:
            self.conn.execute(sql)
        return copied

    def _archive_profiles(self, sequences: dict[str, int]) -> int:
        """Keep the laser profiles as a plain archive: the same rows and values without any reference, so an archived
        profile never stands in the way of deleting a laser or a lens, and triggers that refuse every change."""
        columns = self.conn.execute("PRAGMA table_info(laser_profile)").fetchall()
        definitions = ", ".join("id INTEGER PRIMARY KEY AUTOINCREMENT" if c["pk"] else f"{c['name']} {c['type']}" for c in columns)
        names = ",".join(c["name"] for c in columns)
        self.conn.execute(f"CREATE TABLE laser_profile__new ({definitions})")
        self.conn.execute(f"INSERT INTO laser_profile__new ({names}) SELECT {names} FROM laser_profile")
        copied = self._replace("laser_profile", sequences)
        for trigger in ARCHIVE_TRIGGERS:
            self.conn.execute(trigger)
        return copied

    def _replace(self, table: str, sequences: dict[str, int]) -> int:
        """Put ``<table>__new`` in the place of ``table`` once it holds every row; returns the number of rows."""
        copied = self.conn.execute(f"SELECT COUNT(*) FROM {table}__new").fetchone()[0]
        if copied != self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]:
            raise MigrationError(f"cannot migrate the database to {SCHEMA_RELEASE}: not every row of {table} could be copied; "
                                 "the database was left unchanged")
        for trigger in self.conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchall():
            self.conn.execute(f"DROP TRIGGER {trigger['name']}")
        self.conn.execute(f"DROP TABLE {table}")
        self.conn.execute(f"ALTER TABLE {table}__new RENAME TO {table}")
        if table in sequences:          # ids of deleted rows are never given out again (AUTOINCREMENT)
            self.conn.execute("UPDATE sqlite_sequence SET seq=MAX(seq, ?) WHERE name=?", (sequences[table], table))
            if self.conn.execute("SELECT 1 FROM sqlite_sequence WHERE name=?", (table,)).fetchone() is None:
                self.conn.execute("INSERT INTO sqlite_sequence(name, seq) VALUES (?,?)", (table, sequences[table]))
        return copied

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
        if getattr(self, "_held", False):
            self._held = False
            migrations.release(self.data_dir)

    # -- low level -------------------------------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, tuple(params))

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def stamp(self) -> tuple[int, int]:
        """The state of the data as two counters: rows written through this store, and commits by any other connection to the file (another
        program, another store). An equal stamp means the same data, so a result derived from it can be reused."""
        with self._lock:
            return self.conn.total_changes, self.conn.execute("PRAGMA data_version").fetchone()[0]

    def transaction(self):
        return _Tx(self)

    def audit(self, action: str, **detail: Any) -> None:
        self.execute("INSERT INTO audit(at, action, detail_json) VALUES (?,?,?)", (now(), action, json.dumps(detail)))

    # -- settings --------------------------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value_json FROM setting WHERE key=?", (key,))
        return default if row is None else json.loads(row["value_json"])

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO setting(key, value_json) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (key, json.dumps(value)),
        )

    # -- observations are immutable ----------------------------------------------------------
    def update_observation(self, observation_id: int, **changes: Any) -> None:
        """Always rejected and logged: measured values never change (REQ-001)."""
        self.audit("observation_update_rejected", observation_id=observation_id, fields=sorted(changes))
        raise ImmutableError(f"observation {observation_id} is immutable; model-derived values are stored separately")


class _Tx:
    def __init__(self, store: Store):
        self.store = store

    def __enter__(self):
        self.store._lock.acquire()
        self.store.conn.execute("BEGIN")
        return self.store

    def __exit__(self, exc_type, exc, tb):
        try:
            self.store.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.store._lock.release()
        return False
