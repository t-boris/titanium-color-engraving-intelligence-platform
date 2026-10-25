"""A full backup of a workshop and its restoration (feature electron, REQ-081, DEC-031).

A backup is a folder ``titanium-backup-<UTC>/`` holding a consistent snapshot of the database (SQLite's backup API, so every committed
change in the WAL is in it, as one file), copies of the folders of user files (``files/``: photographs, LightBurn files, pictures and
documents of works; ``labs/``: connected laboratory releases; ``lab_exports/``: own releases; ``fonts/``: own and downloaded fonts) and a
``manifest.json`` with the application and schema versions, the folder the workshop was in, and the size and SHA-256 of every file. The
manifest is written last, after every copied file was read back and its hash confirmed, and the folder gets its final name only then:
an interrupted or failed backup is a ``.partial`` folder that is never taken for a backup and never replaces an earlier one.

A backup is the whole workshop; a laboratory release (``.tcelab``) is a selection of numbers for others and restores nothing.

Restoring puts a backup into another folder (an existing non-empty folder is refused unless overwriting is asked for explicitly, and then
the folder is set aside under ``<folder>.replaced-<UTC>``, never deleted), after every file was checked against the manifest, and
rewrites the paths the records hold from the recorded folder to the new one (``files.rebase_all``).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from . import __version__, files as fs, migrations
from . import setup as su
from .db import Store

KIND = "titanium-workshop-backup"
VERSION = 1
MANIFEST = "manifest.json"
DATABASE = "titanium.sqlite"
FOLDERS = ("files", "labs", "lab_exports", "fonts")
PARTIAL = ".partial"
SKIPPED = {Path("labs") / ".staging"}                 # a release still being connected is not part of the workshop
SETTING = "backup_dir"                                # the folder the operator keeps backups in


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _user_files(data_dir: Path):
    """Every file of the user folders, as (relative path, absolute path)."""
    for folder in FOLDERS:
        root = data_dir / folder
        if not root.is_dir():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = path.relative_to(data_dir)
            if any(rel.parts[:len(s.parts)] == s.parts for s in SKIPPED):
                continue
            yield rel, path


def default_target(store: Store) -> str:
    """Where a backup goes when no folder is named: the folder the operator keeps backups in, else ``~/titanium-backups``."""
    return store.get_setting(SETTING) or str(Path.home() / "titanium-backups")


def needed_bytes(store: Store) -> int:
    """The space a backup of ``store``'s workshop takes, with a margin."""
    return sum(path.stat().st_size for _, path in _user_files(store.data_dir)) + _database_bytes(store.path) + migrations.SPARE_BYTES


def make(store: Store, target_dir: str | Path) -> dict:
    """Write a backup of ``store``'s workshop under ``target_dir``; the manifest with ``path``. Space is checked first; any failure
    removes the partial folder and raises."""
    target_dir = Path(target_dir).expanduser()
    if not str(target_dir).strip():
        raise su.ValidationError("choose the folder the backup is written to")
    if target_dir.resolve() == store.data_dir.resolve() or store.data_dir.resolve() in target_dir.resolve().parents:
        raise su.ValidationError("a backup cannot be written inside the workshop it copies: choose another folder")
    target_dir.mkdir(parents=True, exist_ok=True)
    wanted = needed_bytes(store)
    free = shutil.disk_usage(target_dir).free
    if free < wanted:
        raise su.ValidationError(f"not enough free space for the backup: {wanted // 2**20} MB are needed and {free // 2**20} MB are free")
    name = f"titanium-backup-{_utc()}"
    final, partial = target_dir / name, target_dir / (name + PARTIAL)
    n = 1
    while final.exists() or partial.exists():
        n += 1
        final, partial = target_dir / f"{name}-{n}", target_dir / f"{name}-{n}{PARTIAL}"
    partial.mkdir()
    try:
        entries = {}
        with store._lock:                                    # one consistent picture of the database and the files it names
            copy = sqlite3.connect(partial / DATABASE)
            try:
                store.conn.backup(copy)
                copy.execute("PRAGMA journal_mode=DELETE")
                verdict = copy.execute("PRAGMA integrity_check").fetchone()[0]
                schema = migrations.version(copy)
            finally:
                copy.close()
            if verdict != "ok":
                raise su.ValidationError(f"the copy of the database did not pass the integrity check ({verdict}): the backup was not made")
            for rel, path in _user_files(store.data_dir):
                dest = partial / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
                entries[rel.as_posix()] = _sha256(path)
        for rel, (digest, size) in list(entries.items()):
            again, again_size = _sha256(partial / rel)
            if (again, again_size) != (digest, size):
                raise su.ValidationError(f"the copy of {rel} does not match the original: the backup was not made")
        entries[DATABASE] = _sha256(partial / DATABASE)
        manifest = {"kind": KIND, "version": VERSION, "app": __version__, "schema": schema, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "data_dir": str(store.data_dir.resolve()), "files": {rel: {"sha256": d, "size": s} for rel, (d, s) in sorted(entries.items())},
                    "bytes": sum(s for _, s in entries.values())}
        text = json.dumps(manifest, indent=1, sort_keys=True)
        with open(partial / MANIFEST, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(partial, final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    store.audit("workshop_backup", path=str(final), files=len(entries), bytes=manifest["bytes"])
    return {**manifest, "path": str(final)}


def _database_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in (path, path.with_name(path.name + "-wal")) if p.exists())


def inspect(backup_dir: str | Path, verify: bool = False) -> dict:
    """What a backup folder holds: its manifest, whether it is complete (every listed file present with its size; with ``verify``, its
    hash too) and what is wrong with it. A ``.tcelab`` file or a folder without a manifest is not a backup."""
    folder = Path(backup_dir).expanduser()
    out = {"path": str(folder), "manifest": None, "complete": False, "problems": []}
    if folder.is_file() and folder.suffix == ".tcelab":
        out["problems"].append("this is a laboratory release, not a backup of a workshop: a release is connected on the laboratories screen")
        return out
    if folder.name.endswith(PARTIAL):
        out["problems"].append("this backup was not finished")
        return out
    manifest_path = folder / MANIFEST
    if not folder.is_dir() or not manifest_path.is_file():
        out["problems"].append("this folder holds no backup of a workshop (no manifest)")
        return out
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        out["problems"].append("the manifest of this backup cannot be read")
        return out
    if not isinstance(manifest, Mapping) or manifest.get("kind") != KIND:
        out["problems"].append("this folder holds no backup of a workshop (no manifest)")
        return out
    out["manifest"] = {k: manifest[k] for k in ("kind", "version", "app", "schema", "created_at", "data_dir", "bytes") if k in manifest}
    out["manifest"]["files"] = len(manifest.get("files") or {})
    for rel, entry in (manifest.get("files") or {}).items():
        path = folder / rel
        if not path.is_file():
            out["problems"].append(f"the file {rel} is missing from the backup")
        elif path.stat().st_size != entry.get("size"):
            out["problems"].append(f"the file {rel} has another size than the backup recorded")
        elif verify and _sha256(path)[0] != entry.get("sha256"):
            out["problems"].append(f"the file {rel} does not match the hash the backup recorded")
    out["complete"] = not out["problems"]
    return out


def restore(backup_dir: str | Path, target_dir: str | Path, overwrite: bool = False) -> dict:
    """Restore a backup into ``target_dir``: refused when the backup is incomplete or any file fails its hash, and when the folder is not
    empty unless ``overwrite`` (the folder is then set aside, never deleted). The restored database gets its paths rewritten to the new
    folder; the schema of the backup is kept and migrated by the application that opens it."""
    seen = inspect(backup_dir, verify=True)
    if not seen["complete"]:
        raise su.ValidationError(seen["problems"][0])          # the first reason; ``inspect`` lists them all
    source, target = Path(backup_dir).expanduser(), Path(target_dir).expanduser()
    if not str(target_dir).strip():
        raise su.ValidationError("choose the folder the workshop is restored into")
    if target.resolve() == source.resolve() or source.resolve() in target.resolve().parents:
        raise su.ValidationError("a workshop cannot be restored into its own backup: choose another folder")
    if migrations.held_here(target) and not overwrite:
        raise su.ValidationError("this folder is the open workshop: restoring into it replaces it, which must be chosen explicitly")
    aside = None
    if target.exists() and any(target.iterdir()):
        if not overwrite:
            raise su.ValidationError("the folder is not empty: choose an empty folder, or ask explicitly to replace what is there")
        aside = target.with_name(f"{target.name}.replaced-{_utc()}")
        os.replace(target, aside)
    partial = target.with_name(target.name + PARTIAL)
    shutil.rmtree(partial, ignore_errors=True)
    try:
        partial.mkdir(parents=True)
        manifest = json.loads((source / MANIFEST).read_text(encoding="utf-8"))
        for rel in manifest["files"]:
            dest = partial / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / rel, dest)
        conn = sqlite3.connect(partial / DATABASE)
        try:
            rebased = fs.rebase_all(conn, manifest["data_dir"], str(target.resolve()))
        finally:
            conn.close()
        if target.exists():
            target.rmdir()
        os.replace(partial, target)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return {"path": str(target), "from": manifest["data_dir"], "rebased": rebased, "set_aside": None if aside is None else str(aside),
            "app": manifest.get("app"), "schema": manifest.get("schema"), "created_at": manifest.get("created_at")}


def listing(folders) -> list[dict]:
    """Every backup under the given folders, the newest first, as :func:`inspect` sees it (sizes checked, hashes not)."""
    out = []
    for folder in folders:
        folder = Path(folder).expanduser()
        if not folder.is_dir():
            continue
        for child in folder.iterdir():
            if child.is_dir() and child.name.startswith("titanium-backup-") and not child.name.endswith(PARTIAL):
                out.append(inspect(child))
    return sorted(out, key=lambda b: (b["manifest"] or {}).get("created_at") or "", reverse=True)
