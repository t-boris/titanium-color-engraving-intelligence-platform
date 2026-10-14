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
    stand_id INTEGER NOT NULL REFERENCES capture_setup(id),
    plate_id INTEGER REFERENCES plate(id),
    plan_id INTEGER REFERENCES plan(id),
    engraving_id TEXT NOT NULL,
    lightburn_name TEXT NOT NULL,
    lightburn_path TEXT NOT NULL,
    photo_name TEXT NOT NULL,
    photo_path TEXT NOT NULL,
    context_json TEXT NOT NULL,
    data_json TEXT NOT NULL,
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
                ("laser_device", "lens_id", "INTEGER REFERENCES lens(id)"),   # DEC-041
                ("plate", "lens_json", "TEXT")):
            columns = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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
