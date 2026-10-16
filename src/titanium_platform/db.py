"""Local SQLite store (DEC-020). One file, no network.

Measured observations are immutable (REQ-001): SQL triggers reject UPDATE and DELETE as a backstop and
``Store.update_observation`` rejects and logs the attempt in the audit table.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS laser_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family TEXT NOT NULL,
    version INTEGER NOT NULL,
    name TEXT NOT NULL,
    axes_json TEXT NOT NULL,
    pulse_width REAL NOT NULL,
    line_interval REAL NOT NULL,
    passes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (family, version)
);
CREATE TABLE IF NOT EXISTS lens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    focal_length_mm REAL NOT NULL,
    field_mm REAL,
    expansion REAL NOT NULL DEFAULT 1,
    note TEXT,
    created_at TEXT NOT NULL
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
    profile_id INTEGER NOT NULL REFERENCES laser_profile(id),
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
    profile_id INTEGER NOT NULL REFERENCES laser_profile(id),
    plate_id INTEGER REFERENCES plate(id),
    markers INTEGER NOT NULL DEFAULT 0,
    plan_identifier TEXT,
    band_count INTEGER,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pair (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    profile_id INTEGER NOT NULL REFERENCES laser_profile(id),
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
    profile_id INTEGER NOT NULL REFERENCES laser_profile(id),
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
    profile_id INTEGER NOT NULL REFERENCES laser_profile(id),
    parameters_key TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    stage TEXT NOT NULL,
    questioned INTEGER NOT NULL DEFAULT 0,
    doubt_json TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (profile_id, parameters_key)
);
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
    profile_id INTEGER NOT NULL REFERENCES laser_profile(id),
    lab_json TEXT NOT NULL,
    source_plan_id INTEGER NOT NULL,
    source_color_key TEXT NOT NULL,
    proposal_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE (source_plan_id, source_color_key)
);
CREATE TABLE IF NOT EXISTS proposal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES laser_profile(id),
    base_signature TEXT NOT NULL,
    seed INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    explanation TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (profile_id, base_signature, seed)
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    action TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ImmutableError(RuntimeError):
    """An attempt to change a stored measurement was rejected (REQ-001)."""


class Store:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        (self.data_dir / "files").mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "titanium.sqlite"
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Additive, idempotent changes to tables that an older version already created (DEC-035).

        A data directory written by this version stays readable by the previous one: the new column is nullable
        and the previous version ignores columns it does not know.
        """
        for table, column, definition in (
                ("laser_profile", "device_id", "INTEGER REFERENCES laser_device(id)"),
                ("laser_profile", "lens_id", "INTEGER REFERENCES lens(id)"),
                ("laser_device", "lens_id", "INTEGER REFERENCES lens(id)"),   # DEC-041
                ("plate", "lens_json", "TEXT"),
                ("plate", "material_id", "INTEGER REFERENCES material_profile(id)"),
                ("plate", "test_type", "TEXT"),
                ("material_profile", "grade", "TEXT"),
                ("material_profile", "thickness_mm", "REAL"),
                ("material_profile", "surface", "TEXT"),
                ("pair", "material_id", "INTEGER REFERENCES material_profile(id)"),
                ("pair", "engraving_title", "TEXT"),
                ("pair", "hardware_json", "TEXT")):
            columns = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        plan_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(plan)")}
        if "research_session_id" not in plan_columns:
            self.conn.execute("ALTER TABLE plan ADD COLUMN research_session_id INTEGER REFERENCES research_session(id)")
        # Existing profiles followed the currently installed lens. Freeze that pairing during migration.
        self.conn.execute("UPDATE laser_profile SET lens_id=(SELECT lens_id FROM laser_device WHERE laser_device.id=laser_profile.device_id) WHERE lens_id IS NULL AND device_id IS NOT NULL")
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
        # stored snapshot takes precedence over the linked identity's lens record.
        for row in self.conn.execute(
                "SELECT pa.id,pr.device_id,pr.lens_id,d.name,d.manufacturer,d.model,d.serial,d.data_json,"
                "l.name AS lens_name,l.focal_length_mm,l.field_mm,l.expansion,t.lens_json "
                "FROM pair pa JOIN laser_profile pr ON pr.id=pa.profile_id "
                "LEFT JOIN laser_device d ON d.id=pr.device_id LEFT JOIN lens l ON l.id=pr.lens_id "
                "LEFT JOIN plate t ON t.id=pa.plate_id WHERE pa.hardware_json='{}' AND d.id IS NOT NULL"):
            if row["lens_json"]:
                lens = json.loads(row["lens_json"])
            elif row["lens_id"] is not None:
                lens = {"id": row["lens_id"], "name": row["lens_name"], "focal_length_mm": row["focal_length_mm"],
                        "field_mm": row["field_mm"], "expansion": row["expansion"],
                        "spot_diameter_um": json.loads(row["data_json"]).get("spot_diameter_um")}
            else:
                lens = None
            hardware = {"device": {k: row[k] for k in ("device_id", "name", "manufacturer", "model", "serial")}, "lens": lens}
            self.conn.execute("UPDATE pair SET hardware_json=? WHERE id=?", (json.dumps(hardware), row["id"]))

    def close(self) -> None:
        self.conn.close()

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
