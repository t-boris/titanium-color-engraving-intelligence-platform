"""Schema safety of a workshop (feature electron, REQ-081, DEC-031): the schema stamp, the registry of numbered migrations, the
recovery backup made before any of them runs, and the lock that keeps two programs from migrating or writing one workshop at once.

The stamp is SQLite's ``PRAGMA user_version``. ``CURRENT`` is the schema this version of the application knows:

* a workshop stamped newer than ``CURRENT`` was made by a newer application and is refused unchanged (:class:`SchemaTooNewError`),
  so that older code never runs against a schema it does not know;
* a workshop stamped older (or not stamped: made before 0.30.0) is migrated when it is opened: first the free disk space is checked
  (twice the database plus a margin), then a consistent copy of the database is made with SQLite's backup API (the WAL included)
  into ``backups/schema-before-<CURRENT>-<UTC>.sqlite`` and verified with ``integrity_check``, and only then the migrations run and the
  stamp is set. The additive, idempotent layer the application has always applied at start (``db.SCHEMA`` and ``Store._migrate``:
  tables and columns created when missing) is migration 1; every later change of stored data is a numbered function in
  :data:`MIGRATIONS` and all the pending ones run in one transaction with the new stamp, so a failure leaves the stamp and the data
  as they were and the copy beside them.

A snapshot of a connected laboratory release (``lab_snapshot``) is a store too: it is never backed up before a migration, because it is
rebuilt from its ``.tcelab`` file whenever its layout changes.

The lock is the file ``workshop.lock`` in the workshop folder, held with an exclusive advisory lock while any store of this process has
the folder open (several stores of one process share it, as the application and its tests do); another process finds it locked and is
refused with the holder's pid (:class:`WorkshopLockedError`). The operating system drops the lock when the holder dies, so a lock
left by a crashed program is taken over without any cleaning.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

CURRENT = 1                                   # the schema this application knows
MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {}      # number > 1 -> what it changes, run inside one transaction
SPARE_BYTES = 64 * 1024 * 1024                # free space wanted beyond twice the database before a migration
LOCK_FILE = "workshop.lock"
BACKUPS = "backups"


class MigrationError(RuntimeError):
    """An older database cannot be migrated as it is; it was left unchanged and the message says why."""


class SchemaTooNewError(MigrationError):
    """The workshop was made by a newer application."""


class WorkshopLockedError(MigrationError):
    """Another program has the workshop open."""


# -- the stamp -----------------------------------------------------------------------------------------------------------------
def version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def prepare(conn: sqlite3.Connection, data_dir: Path, copy: Path | None = None) -> dict:
    """Before the additive layer is applied to an open database: refuse a newer schema; for a workshop that is behind, check the space and
    make the recovery copy (unless ``copy`` was made in this start already, by the rebuild of a pre-0.4.0 database). Returns what
    :func:`finish` needs (``from``: the stamp found, ``backup``: the copy, or None)."""
    found = version(conn)
    if found > CURRENT:
        raise SchemaTooNewError(f"this workshop was made by a newer version of the application (schema {found}, this version knows "
                                f"{CURRENT}): update the application to open it; nothing was changed")
    if found == CURRENT:
        return {"from": found, "backup": None}
    tables = _tables(conn)
    fresh = not (tables - {"sqlite_sequence"})
    snapshot = "release_record" in tables
    if fresh or snapshot:
        return {"from": found, "backup": None}
    if copy is not None:
        return {"from": found, "backup": copy}
    path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    size = sum(p.stat().st_size for p in (path, path.with_name(path.name + "-wal")) if p.exists())
    needed = 2 * size + SPARE_BYTES
    free = shutil.disk_usage(data_dir).free
    if free < needed:
        raise MigrationError(f"the workshop needs a schema update (to {CURRENT}) and a recovery copy first, but only {free // 2**20} MB are "
                             f"free where {needed // 2**20} MB are needed: free some space and start again; nothing was changed")
    return {"from": found, "backup": recovery_copy(conn, data_dir, f"schema-before-{CURRENT}")}


def recovery_copy(conn: sqlite3.Connection, data_dir: Path, stem: str) -> Path:
    """A consistent copy of the database ``conn`` reads (the backup API: committed WAL data included) under ``backups/``, verified with
    ``integrity_check``; a copy that fails the check is removed and the migration refused."""
    folder = data_dir / BACKUPS
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target, n = folder / f"{stem}-{stamp}.sqlite", 1
    while target.exists():
        n += 1
        target = folder / f"{stem}-{stamp}-{n}.sqlite"
    copy = sqlite3.connect(target)
    try:
        conn.backup(copy)
        copy.execute("PRAGMA journal_mode=DELETE")          # one file, as a copy to keep
        verdict = copy.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        copy.close()
    if verdict != "ok":
        target.unlink(missing_ok=True)
        raise MigrationError(f"the recovery copy of the database did not pass the integrity check ({verdict}): the schema update was not "
                             "started; check the disk and start again")
    return target


def finish(conn: sqlite3.Connection, plan: dict) -> None:
    """After the additive layer: run every migration newer than the stamp in one transaction and set the stamp to ``CURRENT``. A failure
    rolls everything back and the stamp stays where it was."""
    found = plan["from"]
    if found >= CURRENT:
        return
    pending = [n for n in sorted(MIGRATIONS) if found < n <= CURRENT]
    conn.execute("BEGIN IMMEDIATE")
    try:
        for n in pending:
            MIGRATIONS[n](conn)
        conn.execute(f"PRAGMA user_version = {int(CURRENT)}")
        conn.execute("COMMIT")
    except BaseException as exc:
        conn.execute("ROLLBACK")
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError(f"the schema update to {CURRENT} failed and was rolled back ({exc}); the workshop is as it was and the recovery "
                             f"copy is {plan['backup']}") from exc


# -- the workshop lock ---------------------------------------------------------------------------------------------------------
_held: dict[Path, list] = {}                  # folder -> [file object, count]
_guard = threading.Lock()


def _try_lock(fh) -> bool:
    if sys.platform == "win32":
        import msvcrt
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fh) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def holder(data_dir: Path) -> dict | None:
    """Who holds the workshop's lock as the lock file records it (pid, program, since), or None without a lock file."""
    try:
        text = (Path(data_dir) / LOCK_FILE).read_text(encoding="utf-8")
        return json.loads(text) if text.strip() else None
    except (OSError, ValueError):
        return None


def acquire(data_dir: Path, program: str = "titanium-platform") -> None:
    """Hold the workshop for this process (shared by its stores); refused when another process holds it."""
    folder = Path(data_dir).resolve()
    with _guard:
        if folder in _held:
            _held[folder][1] += 1
            return
        folder.mkdir(parents=True, exist_ok=True)
        fh = open(folder / LOCK_FILE, "a+", encoding="utf-8")
        if not _try_lock(fh):
            other = holder(folder) or {}
            fh.close()
            who = f"pid {other['pid']}" if other.get("pid") else "another program"
            raise WorkshopLockedError(f"the workshop {folder} is open in another program ({who}{', ' + other['program'] if other.get('program') else ''}): "
                                      "close it first, or open another workshop")
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps({"pid": os.getpid(), "program": program, "since": datetime.now(timezone.utc).isoformat(timespec="seconds")}))
        fh.flush()
        _held[folder] = [fh, 1]


def release(data_dir: Path) -> None:
    folder = Path(data_dir).resolve()
    with _guard:
        entry = _held.get(folder)
        if entry is None:
            return
        entry[1] -= 1
        if entry[1] > 0:
            return
        fh = entry.pop(0)
        del _held[folder]
        _unlock(fh)
        fh.close()
        try:
            (folder / LOCK_FILE).unlink()
        except OSError:
            pass


def held_here(data_dir: Path) -> bool:
    return Path(data_dir).resolve() in _held
