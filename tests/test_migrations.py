"""Schema safety of a workshop (electron REQ-081, DEC-031): an older workshop gets a verified recovery copy before its schema is updated
and the stamp afterwards; a failed update rolls back and leaves the stamp; a workshop of a newer schema is refused unchanged; no copy is
made without the space for it; one program at a time holds a workshop, and a second one is refused with the holder's pid."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from titanium_platform import migrations
from titanium_platform.db import MigrationError, Store, now

SRC = str(Path(__file__).resolve().parents[1] / "src")


def unstamped(folder: Path) -> Path:
    """A workshop made by a version before the stamp: the current layout with one laser, ``user_version`` 0."""
    store = Store(folder)
    store.execute("INSERT INTO laser_device(name,data_json,created_at,updated_at) VALUES ('JPT','{}',?,?)", (now(), now()))
    store.close()
    conn = sqlite3.connect(folder / "titanium.sqlite")
    conn.execute("PRAGMA user_version = 0")
    conn.close()
    return folder


def stamp_of(folder: Path) -> int:
    conn = sqlite3.connect(folder / "titanium.sqlite")
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def test_a_new_workshop_is_stamped_without_a_copy(tmp_path):
    store = Store(tmp_path / "w")
    assert migrations.version(store.conn) == migrations.CURRENT
    assert not (tmp_path / "w" / "backups").exists()
    store.close()


def test_an_older_workshop_gets_a_verified_recovery_copy_and_the_stamp(tmp_path):
    folder = unstamped(tmp_path / "w")
    assert stamp_of(folder) == 0
    store = Store(folder)
    assert migrations.version(store.conn) == migrations.CURRENT
    assert store.one("SELECT name FROM laser_device")["name"] == "JPT"
    [copy] = list((folder / "backups").iterdir())
    assert copy.name.startswith(f"schema-before-{migrations.CURRENT}-") and copy.suffix == ".sqlite"
    kept = sqlite3.connect(copy)
    assert kept.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert kept.execute("SELECT name FROM laser_device").fetchone()[0] == "JPT"
    assert kept.execute("PRAGMA user_version").fetchone()[0] == 0           # the copy is what the previous version can open
    kept.close()
    store.close()
    again = Store(folder)                                                    # nothing to do the second time: no second copy
    assert len(list((folder / "backups").iterdir())) == 1
    again.close()


def test_a_failed_migration_rolls_back_and_keeps_the_stamp(tmp_path, monkeypatch):
    folder = unstamped(tmp_path / "w")
    Store(folder).close()                                                    # stamped 1 now
    assert stamp_of(folder) == migrations.CURRENT

    def breaks(conn):
        conn.execute("UPDATE laser_device SET name='changed'")
        raise sqlite3.OperationalError("no such column: nothing")
    monkeypatch.setattr(migrations, "CURRENT", migrations.CURRENT + 1)
    monkeypatch.setitem(migrations.MIGRATIONS, migrations.CURRENT, breaks)
    with pytest.raises(MigrationError, match="rolled back"):
        Store(folder)
    assert stamp_of(folder) == migrations.CURRENT - 1
    conn = sqlite3.connect(folder / "titanium.sqlite")
    assert conn.execute("SELECT name FROM laser_device").fetchone()[0] == "JPT"
    conn.close()
    copies = sorted(p.name for p in (folder / "backups").iterdir())         # the copy made before the attempt stays, beside the first
    assert len(copies) == 2 and copies[1].startswith(f"schema-before-{migrations.CURRENT}-")
    assert not migrations.held_here(folder)                                  # the lock was given back


def test_a_pending_migration_runs_once_in_one_transaction(tmp_path, monkeypatch):
    folder = unstamped(tmp_path / "w")
    Store(folder).close()
    calls = []
    monkeypatch.setattr(migrations, "CURRENT", migrations.CURRENT + 1)
    monkeypatch.setitem(migrations.MIGRATIONS, migrations.CURRENT, lambda conn: calls.append(conn.in_transaction))
    store = Store(folder)
    assert calls == [True] and migrations.version(store.conn) == migrations.CURRENT
    store.close()
    Store(folder).close()
    assert calls == [True]


def test_a_newer_schema_is_refused_unchanged(tmp_path):
    folder = unstamped(tmp_path / "w")
    conn = sqlite3.connect(folder / "titanium.sqlite")
    conn.execute(f"PRAGMA user_version = {migrations.CURRENT + 5}")
    conn.close()
    with pytest.raises(MigrationError, match=f"newer version of the application \\(schema {migrations.CURRENT + 5}"):
        Store(folder)
    assert stamp_of(folder) == migrations.CURRENT + 5 and not (folder / "backups").exists()
    assert not migrations.held_here(folder)


def test_without_space_for_the_copy_nothing_is_changed(tmp_path, monkeypatch):
    folder = unstamped(tmp_path / "w")
    usage = type("Usage", (), {"free": 1024, "total": 1 << 40, "used": 0})
    monkeypatch.setattr(migrations.shutil, "disk_usage", lambda path: usage)
    with pytest.raises(MigrationError, match="free some space"):
        Store(folder)
    assert stamp_of(folder) == 0 and not (folder / "backups").exists()


def test_a_second_program_is_refused_with_the_holders_pid_and_a_closed_workshop_opens(tmp_path):
    folder = tmp_path / "w"
    store = Store(folder)
    assert json.loads((folder / "workshop.lock").read_text())["pid"] == os.getpid()
    second = Store(folder)                                                   # the same program shares the lock
    second.close()
    assert migrations.held_here(folder)
    code = "from titanium_platform.db import open_store; open_store(%r, 'second program')" % str(folder)
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": SRC}, timeout=60)
    assert run.returncode == 2 and f"open in another program (pid {os.getpid()}" in run.stderr and "Traceback" not in run.stderr
    store.close()
    assert not migrations.held_here(folder) and not (folder / "workshop.lock").exists()
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": SRC}, timeout=60)
    assert run.returncode == 0, run.stderr


def test_a_lock_left_by_a_dead_program_is_taken_over(tmp_path):
    folder = tmp_path / "w"
    folder.mkdir()
    (folder / "workshop.lock").write_text(json.dumps({"pid": 999999, "program": "gone"}))
    store = Store(folder)
    assert json.loads((folder / "workshop.lock").read_text())["pid"] == os.getpid()
    store.close()
