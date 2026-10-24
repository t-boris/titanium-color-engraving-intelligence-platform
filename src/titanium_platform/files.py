"""Where a workshop's records keep the paths of its files, and how they are moved with the workshop (feature electron, REQ-081).

Records store absolute paths, written when the file is kept under the workshop's ``files/`` folder:

* ``pair.lightburn_path`` and ``pair.photo_path`` (``ingest``: the LightBurn file and the photograph of a measurement);
* ``device_document.path`` (``devices``: a laser's documents);
* inside ``plan.data_json``: ``image_path`` and ``labels_path`` (``conversion``, the uploaded picture and its labels), ``document_path``
  and ``history[].path`` (``vector_job``, the split documents), ``exports[].path`` (the LightBurn files written), ``evidence_source.palette_path``
  and ``evidence_source.confirmed.path`` with the same under ``source_versions[].pin`` (``evidence_source``, ``photo_work``: the confirmed
  result of a work pinned to a laboratory release).

Everything else under the workshop (``labs/``, ``lab_exports/``, ``fonts/``, ``cache/``) is found by its place relative to the folder.
When a backup is restored into another folder, :func:`rebase_all` rewrites every such path once, in the restored database, from the
folder the backup recorded to the new one, so that reading code keeps reading absolute paths; nothing is rewritten at read time.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path, PurePosixPath, PureWindowsPath

PATH_KEYS = ("image_path", "labels_path", "document_path", "palette_path", "path")        # keys of data_json whose strings are paths
COLUMNS = (("pair", "lightburn_path"), ("pair", "photo_path"), ("device_document", "path"))
RESTORED_FROM = "restored_from"                                                            # setting: the folders this workshop was under


def _parts(path: str) -> tuple:
    pure = PureWindowsPath(path) if "\\" in path or (len(path) > 1 and path[1] == ":") else PurePosixPath(path)
    return tuple(p.lower() if isinstance(pure, PureWindowsPath) else p for p in pure.parts)


def rebase(path, old_root: str, new_root: str) -> str:
    """``path`` moved from under ``old_root`` to under ``new_root``; a path elsewhere is given back as it is."""
    if not isinstance(path, str) or not path:
        return path
    base, here = _parts(old_root), _parts(path)
    if len(here) <= len(base) or here[:len(base)] != base:
        return path
    pure = PureWindowsPath(path) if "\\" in path else PurePosixPath(path)
    return str(Path(new_root).joinpath(*pure.parts[len(base):]))


def resolve(store, path: str) -> str:
    """A recorded path as it is on this computer: as recorded when the file is there, else moved from any folder the workshop was restored
    from (:data:`RESTORED_FROM`) to the current one when that file exists. For records restored before this version rewrote paths."""
    if not isinstance(path, str) or not path or Path(path).exists():
        return path
    for root in store.get_setting(RESTORED_FROM, []) or []:
        moved = rebase(path, root, str(store.data_dir))
        if moved != path and Path(moved).exists():
            return moved
    return path


def _rebased_json(value, old_root: str, new_root: str, key: str | None = None):
    if isinstance(value, dict):
        return {k: _rebased_json(v, old_root, new_root, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_rebased_json(v, old_root, new_root, key) for v in value]
    if isinstance(value, str) and key in PATH_KEYS:
        return rebase(value, old_root, new_root)
    return value


def rebase_all(conn: sqlite3.Connection, old_root: str, new_root: str) -> int:
    """Rewrite every stored path from under ``old_root`` to under ``new_root`` in the database ``conn`` (one transaction); how many rows
    changed. Observations hold no paths, so their immutability is not touched."""
    changed = 0
    conn.execute("BEGIN")
    try:
        for table, column in COLUMNS:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is None:
                continue
            for row in conn.execute(f"SELECT rowid, {column} AS value FROM {table}").fetchall():
                moved = rebase(row[1], old_root, new_root)
                if moved != row[1]:
                    conn.execute(f"UPDATE {table} SET {column}=? WHERE rowid=?", (moved, row[0]))
                    changed += 1
        for row in conn.execute("SELECT id, data_json FROM plan").fetchall():
            try:
                data = json.loads(row[1] or "{}")
            except ValueError:
                continue
            moved = _rebased_json(data, old_root, new_root)
            if moved != data:
                conn.execute("UPDATE plan SET data_json=? WHERE id=?", (json.dumps(moved), row[0]))
                changed += 1
        roots = conn.execute("SELECT value_json FROM setting WHERE key=?", (RESTORED_FROM,)).fetchone()
        known = json.loads(roots[0]) if roots else []
        if old_root not in known:
            conn.execute("INSERT INTO setting(key, value_json) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                         (RESTORED_FROM, json.dumps(known + [old_root])))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return changed
