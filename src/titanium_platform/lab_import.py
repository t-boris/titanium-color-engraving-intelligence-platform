"""Connected laboratory releases (electron REQ-084): a ``.tcelab`` file is checked as it is read, its snapshot is built beside the
workshop, and the release becomes available all at once or not at all; connected laboratories are listed, updated, disconnected and
removed without touching the workshop's own observations.

* A chosen file is first kept in ``labs/.staging/<token>/`` and what it declares (laboratory, author, release, lasers, lenses, titanium,
  contents, usage terms, compatibility) is shown by :func:`inspect` before anything is connected; the authorship of a file is not
  confirmed by any server, and is said to be so.
* Connecting reads it once (``lab_format.read``: compatibility, limits, finite numbers, canonical form, references, unique ids, the
  content hash) while building its snapshot (``lab_snapshot``) in staging, with progress and cancellation (:class:`Job`).
* Only a complete, valid release is activated: its folder is renamed to ``labs/<release_id>/``, then one transaction records it. A
  malformed or truncated file, a broken hash, a limit, a cancellation, a full disk or a crash leave the connected sources and the own
  observations as they were; what an interruption leaves (staging, a folder no transaction recorded) is removed at the next start by
  :func:`reconcile`.
* The same release again (same id and hash) adds nothing; the same id with other content is refused; a release of this workshop's own
  laboratory is refused (its results are here already). A newer release of a connected laboratory becomes its current one; earlier
  ones stay, each in its own folder, for the works that use them (REQ-085).
* A withdrawal (a measurement, a tonal profile or a whole release) is recorded as it was learned and never changed; a snapshot opened
  for new work leaves withdrawn records out (:func:`hidden`), its file keeping them as published.
* Disconnecting stops update checks and takes the laboratory out of the choice for new work; a release is removed from disk only when
  no saved work uses it (:func:`remove_release`).
"""
from __future__ import annotations

import errno
import hashlib
import json
import shutil
import sqlite3
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Iterable

from . import lab_export, lab_format as lf, lab_snapshot
from . import setup as su
from .db import Store, now

LABS, STAGING, FILE, SNAPSHOT = "labs", ".staging", "release.tcelab", "snapshot"
CHUNK = 1024 * 1024
SNAPSHOT_FACTOR = 12               # disk a release may take while it is built, per byte of its file (snapshot and journal)
SPARE_BYTES = 64 * 1024 * 1024     # left free on the disk beyond that
KEEP_OPEN = 8                      # snapshots kept open for works (:func:`reader`): the releases used last
_jobs: dict[str, "Job"] = {}
_running = threading.Lock()
_open: "OrderedDict[tuple, Store]" = OrderedDict()
_open_lock = threading.Lock()


class LabImportError(su.ValidationError):
    """A release that cannot be connected; ``code`` names why, for the screen."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def labs_dir(store: Store) -> Path:
    return store.data_dir / LABS


def staging_dir(store: Store) -> Path:
    return labs_dir(store) / STAGING


def release_dir(store: Store, release_id: str) -> Path:
    if not lf.UUID.fullmatch(str(release_id)):
        raise KeyError("no such laboratory release")
    return labs_dir(store) / release_id


def _own_lab(store: Store) -> str | None:
    return (store.get_setting(lab_export.IDENTITY) or {}).get("origin_lab_id")


# -- receiving and inspecting a file -------------------------------------------------------------------------------------------
def stage(store: Store, chunks: Iterable[bytes], policy: lf.ResourcePolicy = lf.DEFAULT_POLICY) -> str:
    """Keep a received file in staging and return its token; a file larger than a release may be is refused as it arrives."""
    token = uuid.uuid4().hex
    folder = staging_dir(store) / token
    folder.mkdir(parents=True)
    size = 0
    try:
        with open(folder / FILE, "wb") as fh:
            for chunk in chunks:
                size += len(chunk)
                if size > policy.max_bytes:
                    raise LabImportError(f"the file is larger than a laboratory release may be ({policy.max_bytes // CHUNK} MB)", "limit")
                fh.write(chunk)
        if size == 0:
            raise LabImportError("the file is empty", "empty")
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return token


def _staged(store: Store, token: str) -> Path:
    folder = staging_dir(store) / str(token)
    if not (isinstance(token, str) and len(token) == 32 and token.isalnum() and (folder / FILE).is_file()):
        raise KeyError("this file is no longer waiting to be connected: choose it again")
    return folder


def discard(store: Store, token: str) -> None:
    """Forget a staged file the user decided not to connect."""
    shutil.rmtree(_staged(store, token), ignore_errors=True)


def _invalid(exc: lf.FormatError) -> LabImportError:
    return LabImportError(f"the file is not a valid laboratory release: {exc}", exc.code)


def inspect(store: Store, token: str) -> dict:
    """What a staged release declares, read without connecting it: the laboratory, its author (not confirmed by a server for a file),
    the release, its lasers, lenses and titanium, how much it holds, its usage terms, whether this version can use it, and whether it is
    already connected or is this workshop's own. The whole file is checked when it is connected."""
    path = _staged(store, token) / FILE
    equipment, materials = [], []
    manifest = compat = lab = None
    with open(path, "rb") as fh:
        reader = lf.read(fh)
        try:
            for kind, value in reader:
                if kind == "manifest":
                    manifest = value
                elif kind == "compatibility":
                    compat = value
                elif kind == "lab":
                    lab = value
                elif kind == "equipment":
                    laser, lens = value["laser"], value["lens"] or {}
                    equipment.append({"laser": laser["public_name"], "manufacturer": laser.get("manufacturer"), "model": laser.get("model"),
                                      "rated_power_w": laser.get("rated_power_w"), "wavelength_nm": laser.get("wavelength_nm"),
                                      "source_type": laser.get("source_type"), "focal_length_mm": lens.get("focal_length_mm")})
                elif kind == "materials":
                    materials.append({"family": value["family"], "grade": value.get("grade"), "thickness_mm": value.get("thickness_mm")})
                else:
                    break
        except lf.FormatError as exc:
            raise _invalid(exc) from None
        finally:
            reader.close()
    known = store.one("SELECT content_sha256, source_id, status FROM lab_release WHERE release_id=?", (manifest["release_id"],))
    terms = lf.USAGE_TERMS[manifest["usage_terms"]["id"]]
    return {"token": token, "bytes": path.stat().st_size, "lab": lab, "attribution": manifest["attribution"], "verified": False,
            "release": {k: manifest[k] for k in ("release_id", "release_number", "created_at", "schema_version", "content_sha256", "counts",
                                                 "algorithm_versions", "producer", "capabilities")},
            "terms": {"id": manifest["usage_terms"]["id"], "version": manifest["usage_terms"]["version"], **terms},
            "compatibility": compat, "equipment": equipment, "materials": materials, "own": manifest["origin_lab_id"] == _own_lab(store),
            "connected": None if known is None or known["status"] == "removed" else
            {"source_id": known["source_id"], "same": known["content_sha256"] == manifest["content_sha256"]}}


# -- connecting ---------------------------------------------------------------------------------------------------------------------
class Job:
    """One connection running in the background: what it is doing, how far it got and how it ended."""

    def __init__(self, total: int):
        self.id, self.total = uuid.uuid4().hex, total
        self.phase, self.read, self.started, self.finished = "waiting", 0, time.time(), None
        self.error: dict | None = None
        self.result: dict | None = None
        self.cancel = threading.Event()

    def status(self) -> dict:
        elapsed = (self.finished or time.time()) - self.started
        return {"id": self.id, "phase": self.phase, "read": self.read, "total": self.total, "elapsed_s": round(elapsed, 2),
                "share": round(self.read / self.total, 4) if self.total else 0.0, "error": self.error, "result": self.result,
                "done": self.finished is not None}


def start(store: Store, token: str, *, origin: str = "file", url: str | None = None, verified: bool = False, wait: bool = False,
          policy: lf.ResourcePolicy = lf.DEFAULT_POLICY) -> dict:
    """Connect the staged release ``token`` in the background (with ``wait``, before returning); the job's status. One at a time.
    ``policy`` is the release's resource limits (``tools/bench_tcelab.py`` measures beyond the default ones)."""
    folder = _staged(store, token)
    if not _running.acquire(blocking=False):
        raise su.ValidationError("another laboratory release is being connected: wait until it ends")
    job = Job((folder / FILE).stat().st_size)
    _jobs[job.id] = job

    def work():
        try:
            job.result = run(store, folder, job, origin=origin, url=url, verified=verified, policy=policy)
            job.phase = "unchanged" if job.result["unchanged"] else "done"
        except lf.Cancelled:
            job.phase, job.error = "cancelled", {"code": "cancelled", "message": "the connection was cancelled: nothing was connected"}
        except LabImportError as exc:
            job.phase, job.error = "failed", {"code": exc.code, "message": str(exc)}
        except Exception as exc:                  # reported, never a half-connected release: activation is one rename and one transaction
            job.phase, job.error = "failed", {"code": "internal", "message": f"the release could not be connected: {exc}"}
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            job.finished = time.time()
            _running.release()

    if wait:
        work()
    else:
        threading.Thread(target=work, name=f"lab-connect-{job.id[:8]}", daemon=True).start()
    return job.status()


def status(job_id: str) -> dict:
    if job_id not in _jobs:
        raise KeyError("no such connection of a laboratory release")
    return _jobs[job_id].status()


def cancel(job_id: str) -> dict:
    if job_id not in _jobs:
        raise KeyError("no such connection of a laboratory release")
    _jobs[job_id].cancel.set()
    return _jobs[job_id].status()


def _disk_full(exc: BaseException) -> bool:
    return (isinstance(exc, OSError) and exc.errno == errno.ENOSPC) or (isinstance(exc, sqlite3.OperationalError) and "full" in str(exc))


def run(store: Store, folder: Path, job: Job | None = None, *, origin: str = "file", url: str | None = None, verified: bool = False,
        policy: lf.ResourcePolicy = lf.DEFAULT_POLICY) -> dict:
    """Check, build and activate the release staged in ``folder``: the connected release, or ``unchanged`` when it is here already."""
    path = folder / FILE
    job = job or Job(path.stat().st_size)
    job.phase = "checking"
    try:
        manifest = lf.peek_manifest(path, policy)
    except lf.FormatError as exc:
        raise _invalid(exc) from None
    if manifest["origin_lab_id"] == _own_lab(store):
        raise LabImportError("this is a release of this workshop's own laboratory: its results are here already", "own_lab")
    known = store.one("SELECT release_id, content_sha256, source_id, status FROM lab_release WHERE release_id=?", (manifest["release_id"],))
    if known is not None and known["content_sha256"] != manifest["content_sha256"]:
        raise LabImportError("a release with this identity but other content is already connected: the file was changed, or it is not "
                             "the release it claims to be", "conflict")
    if known is not None and known["status"] != "removed" and (release_dir(store, known["release_id"]) / FILE).is_file():
        return {"unchanged": True, "release_id": known["release_id"], "source_id": known["source_id"], "current": None}
    needed = job.total * SNAPSHOT_FACTOR + SPARE_BYTES
    if shutil.disk_usage(folder).free < needed:
        raise LabImportError(f"not enough free disk space to connect this release: {needed // CHUNK} MB are needed", "disk_full")
    job.phase = "building"
    built = folder / SNAPSHOT
    try:
        with open(path, "rb") as fh:
            lab_snapshot.build(built, fh, policy=policy, cancelled=job.cancel.is_set, progress=lambda read: setattr(job, "read", read))
        shutil.copyfile(path, built / FILE)
    except lf.FormatError as exc:
        raise _invalid(exc) from None
    except (OSError, sqlite3.OperationalError) as exc:
        if not _disk_full(exc):
            raise
        raise LabImportError("the disk filled up while the release was being connected: nothing was connected", "disk_full") from None
    job.read, job.phase = job.total, "activating"
    return activate(store, built, origin=origin, url=url, verified=verified)


def activate(store: Store, built: Path, *, origin: str, url: str | None, verified: bool) -> dict:
    """Move a built snapshot (with its file) into place and record it in one transaction; the move is undone if the record fails."""
    snapshot = lab_snapshot.open_snapshot(built)
    try:
        release = lab_snapshot.release_of(snapshot)
        withdrawals = [dict(r) for r in snapshot.query("SELECT * FROM release_withdrawal ORDER BY declared_at, id")]
    finally:
        snapshot.close()
    manifest, lab = release["manifest"], release["lab"]
    target = release_dir(store, manifest["release_id"])
    if target.exists():
        shutil.rmtree(target)                      # what a removal left, or a folder no transaction recorded
    target.parent.mkdir(parents=True, exist_ok=True)
    built.rename(target)
    stamp = now()
    try:
        with store.transaction():
            source = store.one("SELECT id, current_release_id FROM lab_source WHERE origin_lab_id=?", (manifest["origin_lab_id"],))
            if source is None:
                source_id = store.conn.execute(
                    "INSERT INTO lab_source(origin_lab_id, name, origin, url, status, current_release_id, connected_at) VALUES (?,?,?,?,?,?,?)",
                    (manifest["origin_lab_id"], lab["name"], origin, url, "connected", manifest["release_id"], stamp)).lastrowid
                current = True
            else:
                source_id = source["id"]
                current = _newer(store, source["current_release_id"], manifest)
                store.conn.execute("UPDATE lab_source SET name=CASE WHEN ? THEN ? ELSE name END, status='connected', disconnected_at=NULL, "
                                   "url=COALESCE(?, url), current_release_id=CASE WHEN ? THEN ? ELSE current_release_id END WHERE id=?",
                                   (current, lab["name"], url, current, manifest["release_id"], source_id))
            store.conn.execute(
                "INSERT INTO lab_release(release_id, source_id, origin_lab_id, release_number, content_sha256, schema_version, manifest_json, "
                "lab_json, compatibility_json, verified, retrieved_at, bytes, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'kept') "
                "ON CONFLICT(release_id) DO UPDATE SET verified=excluded.verified, retrieved_at=excluded.retrieved_at, bytes=excluded.bytes, "
                "status='kept'",
                (manifest["release_id"], source_id, manifest["origin_lab_id"], manifest.get("release_number"), manifest["content_sha256"],
                 manifest["schema_version"], json.dumps(manifest), json.dumps(lab), json.dumps(lf.compatibility(manifest)), int(verified),
                 stamp, (target / FILE).stat().st_size))
            for w in withdrawals:
                store.conn.execute("INSERT OR IGNORE INTO lab_withdrawal(source_id, target_kind, target_id, reason, replacement_release_id, "
                                   "declared_at, learned_at, learned_from) VALUES (?,?,?,?,?,?,?,?)",
                                   (source_id, w["target_kind"], w["target_id"], w["reason"], w["replacement_release_id"], w["declared_at"],
                                    stamp, f"release:{manifest['release_id']}"))
            store.conn.execute("INSERT INTO audit(at, action, detail_json) VALUES (?,?,?)",
                               (stamp, "lab_connected", json.dumps({"source_id": source_id, "release_id": manifest["release_id"],
                                                                    "content_sha256": manifest["content_sha256"], "origin": origin})))
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return {"unchanged": False, "release_id": manifest["release_id"], "source_id": source_id, "current": current}


def _newer(store: Store, current: str | None, manifest: dict) -> bool:
    """Whether a release replaces its laboratory's current one: a higher number given by the server, else a later creation time."""
    row = store.one("SELECT manifest_json FROM lab_release WHERE release_id=? AND status!='removed'", (current,)) if current else None
    if row is None:
        return True
    old = json.loads(row["manifest_json"])
    if old.get("release_number") is not None and manifest.get("release_number") is not None:
        return manifest["release_number"] > old["release_number"]
    return manifest["created_at"] > old["created_at"]


# -- reading a connected release ----------------------------------------------------------------------------------------------------
def hidden(store: Store, source_id: int) -> list[str]:
    """The UUIDs of the measurements and tonal profiles of a laboratory its owner withdrew, as this workshop learned them."""
    return [r["target_id"] for r in store.query("SELECT target_id FROM lab_withdrawal WHERE source_id=? AND target_kind IN "
                                                "('measurement', 'tone_profile') ORDER BY id", (source_id,))]


def open_release(store: Store, release_id: str, hidden_records: Iterable[str] = ()) -> Store:
    """A connected release for reading, without ``hidden_records``. A snapshot laid out by another version is built again from the
    release's own file first (the file is the release; the snapshot only serves it)."""
    row = store.one("SELECT status FROM lab_release WHERE release_id=?", (release_id,))
    folder = release_dir(store, release_id)
    if row is None or row["status"] == "removed" or not (folder / FILE).is_file():
        raise KeyError("this laboratory release is not on this computer: connect its file again")
    snapshot = lab_snapshot.open_snapshot(folder)
    try:
        stale = lab_snapshot.release_of(snapshot).get("version") != lab_snapshot.VERSION
    finally:
        snapshot.close()
    if stale:
        _forget(store, release_id)
        _rebuild(folder)
    return lab_snapshot.open_snapshot(folder, hidden_records)


def reader(store: Store, release_id: str, hidden_records: list[str]) -> Store:
    """:func:`open_release`, kept open for the works that read it (the last :data:`KEEP_OPEN` releases and hidden sets)."""
    key = (str(store.data_dir), release_id, hashlib.sha256("\n".join(hidden_records).encode()).hexdigest())
    with _open_lock:
        if key in _open:
            _open.move_to_end(key)
            return _open[key]
    opened = open_release(store, release_id, hidden_records)
    with _open_lock:
        if key in _open:                         # opened meanwhile by another request
            opened.close()
            return _open[key]
        _open[key] = opened
        while len(_open) > KEEP_OPEN:
            _open.popitem(last=False)[1].close()
    return opened


def _forget(store: Store, release_id: str) -> None:
    """Close what :func:`reader` keeps open of a release, before its files are removed or built again."""
    with _open_lock:
        for key in [k for k in _open if k[0] == str(store.data_dir) and k[1] == release_id]:
            _open.pop(key).close()


def _rebuild(folder: Path) -> None:
    """Build a release's snapshot again from its file, beside it, and put it in place of the old one."""
    fresh = folder.parent / STAGING / f"rebuild-{folder.name}-{uuid.uuid4().hex[:8]}"
    try:
        with open(folder / FILE, "rb") as fh:
            lab_snapshot.build(fresh, fh)
        for suffix in ("-wal", "-shm"):
            (folder / f"titanium.sqlite{suffix}").unlink(missing_ok=True)
        (fresh / "titanium.sqlite").replace(folder / "titanium.sqlite")
    finally:
        shutil.rmtree(fresh, ignore_errors=True)


# -- the connected laboratories ------------------------------------------------------------------------------------------------------
def _release_row(row) -> dict:
    manifest, compat = json.loads(row["manifest_json"]), json.loads(row["compatibility_json"])
    return {"release_id": row["release_id"], "release_number": row["release_number"], "created_at": manifest["created_at"],
            "retrieved_at": row["retrieved_at"], "content_sha256": row["content_sha256"], "schema_version": row["schema_version"],
            "verified": bool(row["verified"]), "compatibility": compat, "bytes": row["bytes"], "status": row["status"],
            "counts": manifest["counts"], "terms": manifest["usage_terms"], "attribution": manifest["attribution"],
            "algorithm_versions": manifest["algorithm_versions"]}


def _release_withdrawn(store: Store, source_id: int, release_id: str) -> bool:
    return store.one("SELECT 1 FROM lab_withdrawal WHERE source_id=? AND target_kind='release' AND target_id=?", (source_id, release_id)) is not None


def sources(store: Store) -> list[dict]:
    """Every connected laboratory with its current release, how many releases are kept, and how many withdrawals were learned."""
    out = []
    for s in store.query("SELECT * FROM lab_source ORDER BY name COLLATE NOCASE, id"):
        current = store.one("SELECT * FROM lab_release WHERE release_id=?", (s["current_release_id"],)) if s["current_release_id"] else None
        kept = store.one("SELECT COUNT(*) AS n FROM lab_release WHERE source_id=? AND status!='removed'", (s["id"],))["n"]
        withdrawn = store.one("SELECT COUNT(*) AS n FROM lab_withdrawal WHERE source_id=?", (s["id"],))["n"]
        out.append({"id": s["id"], "origin_lab_id": s["origin_lab_id"], "name": s["name"], "origin": s["origin"], "url": s["url"],
                    "status": s["status"], "connected_at": s["connected_at"], "disconnected_at": s["disconnected_at"],
                    "update_checks": s["update_checks"], "last_checked_at": s["last_checked_at"],
                    "current": None if current is None else _release_row(current), "kept": kept, "withdrawals": withdrawn,
                    "release_withdrawn": bool(current is not None and _release_withdrawn(store, s["id"], current["release_id"]))})
    return out


def source(store: Store, source_id: int) -> dict:
    """One connected laboratory: its card, every release kept, the withdrawals learned, and the saved works that use each release."""
    card = next((x for x in sources(store) if x["id"] == source_id), None)
    if card is None:
        raise KeyError("no such connected laboratory")
    current = card["current"]
    row = store.one("SELECT lab_json FROM lab_release WHERE release_id=?", (current["release_id"],)) if current else None
    card["lab"] = json.loads(row["lab_json"]) if row else None
    card["releases"] = [{**_release_row(r), "withdrawn": _release_withdrawn(store, source_id, r["release_id"]),
                         "works": references(store, r["release_id"])}
                        for r in store.query("SELECT * FROM lab_release WHERE source_id=? ORDER BY retrieved_at DESC, release_id", (source_id,))]
    card["withdrawal_list"] = [dict(r) for r in store.query("SELECT target_kind, target_id, reason, replacement_release_id, declared_at, "
                                                            "learned_at, learned_from FROM lab_withdrawal WHERE source_id=? ORDER BY id",
                                                            (source_id,))]
    return card


def references(store: Store, release_id: str) -> list[dict]:
    """The saved works whose results come from ``release_id``: their pinned source, or an earlier source they can go back to (REQ-085)."""
    return [{"plan_id": r["id"], "name": r["name"], "mode": r["mode"]}
            for r in store.query("SELECT id, name, mode FROM plan WHERE COALESCE(status, '')!='Deleted' AND "
                                 "(json_extract(data_json, '$.evidence_source.release_id')=? OR EXISTS (SELECT 1 FROM "
                                 "json_each(data_json, '$.source_versions') v WHERE json_extract(v.value, '$.pin.release_id')=?)) ORDER BY id",
                                 (release_id, release_id))]


def disconnect(store: Store, source_id: int) -> dict:
    """Stop update checks for a laboratory and take it out of the choice for new work; its releases stay for the works that use them."""
    if store.one("SELECT 1 FROM lab_source WHERE id=?", (source_id,)) is None:
        raise KeyError("no such connected laboratory")
    store.execute("UPDATE lab_source SET status='disconnected', update_checks='off', disconnected_at=? WHERE id=?", (now(), source_id))
    store.audit("lab_disconnected", source_id=source_id)
    return source(store, source_id)


def reconnect(store: Store, source_id: int) -> dict:
    """Bring a disconnected laboratory back into the choice for new work; update checks are manual again."""
    if store.one("SELECT 1 FROM lab_source WHERE id=?", (source_id,)) is None:
        raise KeyError("no such connected laboratory")
    store.execute("UPDATE lab_source SET status='connected', update_checks='manual', disconnected_at=NULL WHERE id=?", (source_id,))
    store.audit("lab_reconnected", source_id=source_id)
    return source(store, source_id)


def remove_release(store: Store, release_id: str) -> dict:
    """Remove a release's files from this computer when no saved work uses it; its record stays (what was connected, and when)."""
    row = store.one("SELECT source_id FROM lab_release WHERE release_id=?", (release_id,))
    if row is None:
        raise KeyError("no such laboratory release")
    works = references(store, release_id)
    if works:
        raise su.ValidationError(f"{len(works)} saved works use this release: move them to another source first")
    with store.transaction():
        store.conn.execute("UPDATE lab_release SET status='removed' WHERE release_id=?", (release_id,))
        store.conn.execute("UPDATE lab_source SET current_release_id=(SELECT release_id FROM lab_release WHERE source_id=? AND status!='removed' "
                           "ORDER BY COALESCE(release_number, -1) DESC, json_extract(manifest_json, '$.created_at') DESC LIMIT 1) "
                           "WHERE id=? AND current_release_id=?", (row["source_id"], row["source_id"], release_id))
        store.conn.execute("INSERT INTO audit(at, action, detail_json) VALUES (?,?,?)",
                           (now(), "lab_release_removed", json.dumps({"release_id": release_id})))
    _forget(store, release_id)
    shutil.rmtree(release_dir(store, release_id), ignore_errors=True)
    return source(store, row["source_id"])


def differences(store: Store, release_id: str, against: str | None = None) -> dict:
    """What ``release_id`` adds, changes and removes against ``against`` (by default the kept release of the same laboratory made just
    before it), and how many withdrawals it brings."""
    row = store.one("SELECT source_id FROM lab_release WHERE release_id=?", (release_id,))
    if row is None:
        raise KeyError("no such laboratory release")
    if against is None:
        before = store.one("SELECT release_id FROM lab_release WHERE source_id=? AND release_id!=? AND status!='removed' AND "
                           "json_extract(manifest_json, '$.created_at') < (SELECT json_extract(manifest_json, '$.created_at') FROM lab_release "
                           "WHERE release_id=?) ORDER BY json_extract(manifest_json, '$.created_at') DESC LIMIT 1",
                           (row["source_id"], release_id, release_id))
        against = before["release_id"] if before else None
    new = open_release(store, release_id)
    try:
        withdrawn = new.one("SELECT COUNT(*) AS n FROM release_withdrawal")["n"]
        if against is None:
            counts = {r["kind"]: r["n"] for r in new.query("SELECT kind, COUNT(*) AS n FROM release_record GROUP BY kind")}
            return {"against": None, "added": counts, "changed": {}, "removed": {}, "withdrawn": withdrawn}
        old = open_release(store, against)
        try:
            return {"against": against, **lab_snapshot.differences(old, new), "withdrawn": withdrawn}
        finally:
            old.close()
    finally:
        new.close()


# -- after an interruption ----------------------------------------------------------------------------------------------------------
def reconcile(store: Store) -> dict:
    """What an interrupted connection left, cleaned at start: staging, and folders no transaction recorded. A recorded release whose
    files are gone is marked removed. Own observations are never touched."""
    labs = labs_dir(store)
    removed, missing = [], []
    if not labs.exists():
        return {"removed": removed, "missing": missing}
    shutil.rmtree(labs / STAGING, ignore_errors=True)
    recorded = {r["release_id"]: r["status"] for r in store.query("SELECT release_id, status FROM lab_release")}
    for folder in labs.iterdir():
        if folder.is_dir() and recorded.get(folder.name, "removed") == "removed":
            shutil.rmtree(folder, ignore_errors=True)
            removed.append(folder.name)
    for release_id, state in recorded.items():
        if state != "removed" and not (labs / release_id / FILE).is_file():
            store.execute("UPDATE lab_release SET status='removed' WHERE release_id=?", (release_id,))
            missing.append(release_id)
    if removed or missing:
        store.audit("labs_reconciled", removed=removed, missing=missing)
    return {"removed": removed, "missing": missing}
