"""«Перепроверить все работы» (feature findings-you-can-manage-short-lists-re-check, REQ-004, DEC-089).

After the measurement changed, every accepted photograph of the workshop is measured again with the code as it is now, in the background,
one photograph at a time, after a full backup of the workshop: accepting a new measurement deletes the old photograph's files, so only the
backup undoes it. A photograph whose new measurement does not come out whole keeps its old one with the reason (DEC-088). The conclusions
are drawn once at the end (an analysis run with the trigger ``recheck``); the report says, photograph by photograph, what was replaced, kept
or failed and the largest colour change, and which findings appeared, went or changed.

One re-check at a time per workshop; while it runs no photograph can be accepted, measured again or deleted (``ensure_idle``). A stop takes
effect between photographs and the conclusions are still drawn from what was measured. Each re-check and its report are kept
(``recheck_run``), so the last report is there after a restart; one the application did not finish (closed while it ran) reads as
interrupted.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from . import backup, designer, findings, ingest, work_errors
from .db import Store, now

SECONDS_PER_PHOTO = 32          # a copy of the workshop (2026-10-25): 31 photographs re-checked in 16 min, backup and conclusions included
CHANGED_DELTA_E = 1.0           # a layer whose colour moved by this much is counted as changed (about the smallest visible difference)
RUNNING, DONE, CANCELLED, FAILED, INTERRUPTED = "running", "done", "cancelled", "failed", "interrupted"

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_STOPS: dict[tuple[str, int], threading.Event] = {}


class Busy(Exception):
    """Every work is being re-checked: the photographs cannot change until it ends."""


def _key(store: Store) -> str:
    return str(store.path.resolve())


def _lock(store: Store) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(_key(store), threading.Lock())


def running(store: Store) -> bool:
    return _lock(store).locked()


def ensure_idle(store: Store) -> None:
    """Refuse to change a photograph while every work is being re-checked."""
    if running(store):
        raise Busy("every work is being re-checked: wait until it ends or stop it")


def _photos(store: Store) -> list[dict]:
    return [dict(r) for r in store.query("SELECT id, photo_name, engraving_title, device_id, lens_id FROM pair WHERE status='Accepted' ORDER BY id")]


def _free_bytes(folder: Path) -> int | None:
    """Free space where ``folder`` is or will be made (its nearest existing parent)."""
    for at in (folder, *folder.parents):
        if at.exists():
            return shutil.disk_usage(at).free
    return None


def preview(store: Store, target_dir: str | Path) -> dict:
    """What a re-check would do: how many photographs, about how long, where the backup goes, its size and the space there."""
    count = len(_photos(store))
    folder = Path(target_dir).expanduser()
    return {"photos": count, "estimate_s": count * SECONDS_PER_PHOTO, "backup_dir": str(folder), "backup_bytes": backup.needed_bytes(store),
            "free_bytes": _free_bytes(folder), "running": running(store)}


def _public(store: Store, row) -> dict:
    status = row["status"]
    if status == RUNNING and (_key(store), row["id"]) not in _STOPS:
        status = INTERRUPTED                    # the application was closed while it ran
    return {"id": row["id"], "started_at": row["started_at"], "finished_at": row["finished_at"], "status": status,
            "backup_path": row["backup_path"], **json.loads(row["report_json"])}


def get(store: Store, recheck_id: int) -> dict:
    row = store.one("SELECT * FROM recheck_run WHERE id=?", (recheck_id,))
    if row is None:
        raise KeyError(f"re-check {recheck_id} not found")
    return _public(store, row)


def latest(store: Store) -> dict | None:
    row = store.one("SELECT * FROM recheck_run ORDER BY id DESC LIMIT 1")
    return None if row is None else _public(store, row)


def stop(store: Store, recheck_id: int) -> dict:
    """Stop after the photograph being measured; the conclusions are still drawn from what was measured."""
    event = _STOPS.get((_key(store), recheck_id))
    if event is None:
        get(store, recheck_id)                  # a missing one is «not found»; a finished one is returned as it is
    else:
        event.set()
        store.audit("recheck_stop_asked", recheck_id=recheck_id)
    return get(store, recheck_id)


def start(store: Store, target_dir: str | Path, on_accepted: Callable[[Store, int, int | None], None] | None = None, wait: bool = False) -> dict:
    """Begin a re-check of every accepted photograph, the backup into ``target_dir`` first; with ``wait`` it ends before returning.
    ``on_accepted`` is what follows each new measurement, as for one photograph measured again."""
    lock = _lock(store)
    if not lock.acquire(blocking=False):
        raise Busy("every work is being re-checked already: wait until it ends")
    try:
        store.execute("UPDATE recheck_run SET status=?, finished_at=? WHERE status=?", (INTERRUPTED, now(), RUNNING))
        photos = _photos(store)
        before = findings.get_run(store)
        report = {"phase": "backup", "total": len(photos), "done": 0, "current": None, "elapsed_s": 0.0, "photos": [], "backup": None,
                  "findings": None, "before_run_id": before["id"] if before else None, "error": None}
        recheck_id = store.execute("INSERT INTO recheck_run(started_at,status,report_json) VALUES (?,?,?)",
                                   (now(), RUNNING, json.dumps(report))).lastrowid
        store.audit("recheck_started", recheck_id=recheck_id, photos=len(photos), backup_dir=str(target_dir))
        stopped = _STOPS[(_key(store), recheck_id)] = threading.Event()
    except BaseException:
        lock.release()
        raise

    def work():
        try:
            _run(store, recheck_id, report, photos, Path(target_dir).expanduser(), on_accepted, stopped)
        except Exception as exc:                # reported, never silent
            _finish(store, recheck_id, report, FAILED, f"the re-check stopped: {type(exc).__name__}: {exc}")
        finally:
            _STOPS.pop((_key(store), recheck_id), None)
            lock.release()

    if wait:
        work()
    else:
        threading.Thread(target=work, name=f"recheck-{recheck_id}", daemon=True).start()
    return get(store, recheck_id)


def _save(store: Store, recheck_id: int, report: dict) -> None:
    store.execute("UPDATE recheck_run SET report_json=? WHERE id=?", (json.dumps(report), recheck_id))


def _finish(store: Store, recheck_id: int, report: dict, status: str, error: str | None = None) -> None:
    report.update(phase=status, current=None, error=error)
    store.execute("UPDATE recheck_run SET status=?, finished_at=?, report_json=? WHERE id=?", (status, now(), json.dumps(report), recheck_id))
    kinds = [p["status"] for p in report["photos"]]
    store.audit("recheck_finished", recheck_id=recheck_id, status=status, replaced=kinds.count("replaced"), kept=kinds.count("kept"),
                failed=kinds.count("failed"), error=error)


def _run(store: Store, recheck_id: int, report: dict, photos: list[dict], target: Path, on_accepted, stopped: threading.Event) -> None:
    started = time.monotonic()
    try:
        made = backup.make(store, target)
    except Exception as exc:
        return _finish(store, recheck_id, report, FAILED, f"the backup could not be made, so nothing was measured again: {exc}")
    report.update(phase="remeasure", backup={"path": made["path"], "bytes": made["bytes"]})
    store.execute("UPDATE recheck_run SET backup_path=? WHERE id=?", (made["path"], recheck_id))
    _save(store, recheck_id, report)
    touched = set()
    for photo in photos:
        if stopped.is_set():
            break
        report["current"] = {"pair_id": photo["id"], "photo_name": photo["photo_name"], "title": photo["engraving_title"]}
        _save(store, recheck_id, report)
        item = {"pair_id": photo["id"], "photo_name": photo["photo_name"], "title": photo["engraving_title"], "replaced_by": None, "reason": None,
                "max_delta_e": None, "changed_layers": 0, "layers": 0}
        try:
            result = ingest.remeasure_pair(store, photo["id"], on_accepted=on_accepted)
            moved = [layer["delta_e"] for layer in result["layers"] if layer["delta_e"] is not None]
            item.update(status=result["status"], replaced_by=result["replaced_by"], reason=result["reason"], layers=len(result["layers"]),
                        max_delta_e=max(moved, default=None), changed_layers=sum(1 for d in moved if d >= CHANGED_DELTA_E))
            if result["replaced_by"] is not None:
                touched.add((photo["device_id"], photo["lens_id"]))
                try:
                    work_errors.record(store, result["replaced_by"])          # the review of the work it belongs to (DEC-090)
                except work_errors.SKIPPED:
                    pass
        except Exception as exc:                # one photograph must not stop the others; its new measurement may already be in
            touched.add((photo["device_id"], photo["lens_id"]))
            item.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
        report["photos"].append(item)
        report["done"] += 1
        report["elapsed_s"] = round(time.monotonic() - started, 1)
        _save(store, recheck_id, report)
    report.update(phase="analysis", current=None)
    _save(store, recheck_id, report)
    try:
        designer.reconcile_statuses(store)
        after = findings.run_analysis(store, "recheck")
        for device_id, lens_id in sorted(touched, key=lambda dl: (dl[0], -1 if dl[1] is None else dl[1])):
            work_errors.after_change(store, device_id, lens_id)
        report["findings"] = findings.compare_runs(store, report["before_run_id"], after["id"])
    except Exception as exc:
        return _finish(store, recheck_id, report, FAILED,
                       f"the photographs were measured again, but the conclusions could not be drawn: {type(exc).__name__}: {exc}")
    report["elapsed_s"] = round(time.monotonic() - started, 1)
    _finish(store, recheck_id, report, CANCELLED if stopped.is_set() else DONE)
