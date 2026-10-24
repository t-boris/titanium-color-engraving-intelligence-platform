"""The desktop's side of the cloud of laboratories (feature electron, REQ-086, REQ-087, DEC-058; the service is ``cloud/``).

* the catalogue: the public laboratories, and with a sign-in the private ones the account owns or was invited to, each marked when it
  is connected here already or is this workshop's own;
* connecting from the cloud: the chunks of a release are downloaded one by one into the importer's staging with progress and a
  cancel, checked against the hash the cloud declares, then connected by :mod:`lab_import` exactly as a file is, as a job the screen
  polls like a file connection;
* publishing: the own laboratory is created in the cloud once (``POST /labs`` with the workshop's public information and its origin
  id); a publication is reserved with an idempotency key kept in ``lab_publication`` of the workshop's database before anything is
  sent, so that a retry after a crash resumes the very same publication; the release is exported with the reserved identity into
  ``lab_exports/``, uploaded in the cloud's chunks with retries, and finalized; the row then says which release of the cloud the
  export became (``lab_export.exports`` shows it);
* withdrawals, invitations and members of the own cloud laboratory; and the check for updates of the laboratories connected from
  the cloud: by the operator's button, or automatically when both the laboratory and the network setting allow it.

Nothing here runs unless the operator acts (or allowed the automatic check); every call goes through :mod:`cloud_http` and its switch."""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from . import cloud_session, lab_export, lab_format as lf, lab_import, outbound
from . import setup as su
from .cloud_http import CHUNK_TIMEOUT_S, CloudError, expect, request
from .db import Store, now

EXPORTS = "lab_exports"                      # as api.routes_labs.EXPORTS: the workshop's own releases
ORIGIN = "cloud"                             # lab_source.origin of a laboratory connected from the cloud
RETRIES = 3                                  # attempts per chunk, up or down
BACKOFF_S = (1.0, 3.0)                       # between attempts
PENDING_STATES = ("reserved", "exported", "uploading")
AUTO_CHECK_EVERY_S = 24 * 3600               # an automatic check for updates at most once a day per laboratory
UPDATE_CHECK_MODES = ("manual", "auto")

_jobs: dict[str, "Job"] = {}
_lock = threading.Lock()
_publishing = threading.Lock()               # one publication at a time


class Cancelled(Exception):
    pass


# -- helpers ------------------------------------------------------------------------------------------------------------------------
def _api(store: Store) -> str:
    return cloud_session.api_url(store)


def _bearer(store: Store, required: bool) -> dict:
    """The Authorization header: always when ``required``, else only when signed in (a public read works without an account)."""
    if not required and not cloud_session.signed_in(store):
        return {}
    return {"Authorization": f"Bearer {cloud_session.jwt(store)}"}


def _call(store: Store, method: str, path: str, *, body=None, raw: bytes | None = None, signed: bool = True, ok=(200,), timeout=None):
    headers = _bearer(store, signed)
    answer = request(method, f"{_api(store)}{path}", body=body, raw=raw, headers=headers, **({"timeout": timeout} if timeout else {}))
    return expect(answer, *ok)


def _retrying(fn, *, cancelled=None):
    """``fn()`` up to RETRIES times when the cloud could not be reached or answered 5xx; any other refusal is final."""
    for attempt in range(RETRIES):
        try:
            return fn()
        except CloudError as exc:
            final = attempt == RETRIES - 1 or (exc.status and exc.status < 500)
            if final or (cancelled and cancelled()):
                raise
            time.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
    raise AssertionError("unreachable")


def _own_origin(store: Store) -> str:
    return lab_export.identity(store)["origin_lab_id"]


def _lab_id_of(source: dict) -> str | None:
    """The cloud laboratory a connected source came from, kept in its url as ``{api}/labs/{id}``."""
    url = source.get("url") or ""
    tail = url.rsplit("/labs/", 1)
    return tail[1] if len(tail) == 2 and lf.UUID.fullmatch(tail[1]) else None


# -- jobs the screen polls ------------------------------------------------------------------------------------------------------------
class Job:
    """A connection from the cloud or a publication running in the background, with the status shape of ``lab_import.Job`` (phase,
    read, total, share, error, result, done) plus ``kind`` and ``cloud`` (what it is about). A connection hands over to the importer's
    own job once the file is downloaded and reports that job's phases from then on."""

    def __init__(self, kind: str, total: int, cloud: dict):
        self.id, self.kind, self.total, self.cloud = uuid.uuid4().hex, kind, total, cloud
        self.phase, self.read, self.started, self.finished = "waiting", 0, time.time(), None
        self.error: dict | None = None
        self.result: dict | None = None
        self.cancel = threading.Event()
        self.inner: str | None = None

    def status(self) -> dict:
        if self.inner is not None:
            inner = lab_import.status(self.inner)
            return {**inner, "id": self.id, "kind": self.kind, "cloud": self.cloud, "stage": "connecting"}
        elapsed = (self.finished or time.time()) - self.started
        return {"id": self.id, "kind": self.kind, "cloud": self.cloud, "stage": self.phase, "phase": self.phase, "read": self.read, "total": self.total,
                "elapsed_s": round(elapsed, 2), "share": round(self.read / self.total, 4) if self.total else 0.0, "error": self.error,
                "result": self.result, "done": self.finished is not None}

    def run(self, work, wait: bool) -> dict:
        def guarded():
            try:
                work()
            except Cancelled:
                self.phase, self.error = "cancelled", {"code": "cancelled", "message": "the operation was cancelled: nothing changed"}
            except (CloudError, lab_import.LabImportError, su.ValidationError) as exc:
                self.phase, self.error = "failed", {"code": getattr(exc, "code", "invalid"), "message": str(exc)}
            except lf.Cancelled:
                self.phase, self.error = "cancelled", {"code": "cancelled", "message": "the operation was cancelled: nothing changed"}
            except Exception as exc:                  # reported to the screen, never a half-done state: each step is one transaction
                self.phase, self.error = "failed", {"code": "internal", "message": f"the operation failed: {exc}"}
            finally:
                if self.inner is None:
                    self.finished = time.time()
        with _lock:
            _jobs[self.id] = self
        if wait:
            guarded()
        else:
            threading.Thread(target=guarded, name=f"cloud-{self.kind}-{self.id[:8]}", daemon=True).start()
        return self.status()


def status(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise KeyError("no such cloud operation")
    return job.status()


def cancel(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise KeyError("no such cloud operation")
    job.cancel.set()
    if job.inner is not None:
        lab_import.cancel(job.inner)
    return job.status()


# -- the catalogue -----------------------------------------------------------------------------------------------------------------
def _marked(store: Store, labs: list[dict]) -> list[dict]:
    """Each cloud laboratory with what this workshop knows of it: connected here (and whether the cloud has a newer release), or own."""
    own = _own_origin(store)
    local = {s["origin_lab_id"]: s for s in lab_import.sources(store)}
    out = []
    for lab in labs:
        source = local.get(lab["origin_lab_id"])
        latest = lab.get("latest_release")
        connected = None
        if source is not None:
            current = source.get("current") or {}
            number = current.get("release_number")
            newer = bool(latest) and (number is None or latest["number"] > number) and latest["id"] != current.get("release_id")
            connected = {"source_id": source["id"], "status": source["status"], "origin": source["origin"], "current_release_id": current.get("release_id"),
                         "current_release_number": number, "newer": newer}
        out.append({**lab, "own": lab["origin_lab_id"] == own, "connected": connected})
    return out


def catalogue(store: Store) -> dict:
    """The laboratories the cloud shows this workshop: public ones without an account; with a sign-in also the own and the invited."""
    listed = _call(store, "GET", "/labs", signed=False)
    return {"api_url": _api(store), "signed_in": cloud_session.signed_in(store), "labs": _marked(store, listed["labs"])}


def lab(store: Store, lab_id: str) -> dict:
    """One cloud laboratory with its releases, newest first."""
    if not lf.UUID.fullmatch(str(lab_id)):
        raise KeyError("no such laboratory in the cloud")
    found = _call(store, "GET", f"/labs/{lab_id}", signed=False)
    releases = _call(store, "GET", f"/labs/{lab_id}/releases", signed=False)["releases"]
    return {**_marked(store, [found])[0], "releases": releases}


# -- connecting a release from the cloud ------------------------------------------------------------------------------------------
def connect(store: Store, release_id: str, *, wait: bool = False) -> dict:
    """Download the chunks of ``release_id`` into the importer's staging and connect them as a file is connected; the job to poll."""
    if not lf.UUID.fullmatch(str(release_id)):
        raise KeyError("no such release in the cloud")
    shown = _call(store, "GET", f"/releases/{release_id}/manifest", signed=False)
    release, laboratory = shown["release"], shown["laboratory"]
    api = _api(store)
    job = Job("connect", release["byte_size"], {"release_id": release_id, "lab_id": release["lab_id"], "lab_name": laboratory["name"],
                                                "release_number": release["number"]})
    digest = hashlib.sha256()

    def chunks() -> Iterator[bytes]:
        headers = _bearer(store, required=False)
        for n in range(release["chunk_count"]):
            if job.cancel.is_set():
                raise Cancelled()
            piece = _retrying(lambda: _download(api, release_id, n, headers), cancelled=job.cancel.is_set)
            if len(piece) > release["chunk_bytes"]:
                raise CloudError("the cloud sent a chunk larger than it declared", code="chunk_size")
            digest.update(piece)
            job.read += len(piece)
            yield piece

    def work():
        job.phase = "downloading"
        token = lab_import.stage(store, chunks())
        if digest.hexdigest() != release["file_sha256"] or job.read != release["byte_size"]:
            lab_import.discard(store, token)
            raise CloudError("the downloaded release does not match the hash the cloud declares: nothing was connected", code="file_hash")
        if job.cancel.is_set():
            lab_import.discard(store, token)
            raise Cancelled()
        started = lab_import.start(store, token, origin=ORIGIN, url=f"{api}/labs/{release['lab_id']}", verified=True, wait=wait)
        job.inner = started["id"]

    return job.run(work, wait)


def _download(api: str, release_id: str, n: int, headers: dict) -> bytes:
    answer = request("GET", f"{api}/releases/{release_id}/chunks/{n}", headers=headers, timeout=CHUNK_TIMEOUT_S)
    if answer.status != 200:
        expect(answer, 200)
    return answer.body


# -- the own laboratory in the cloud ------------------------------------------------------------------------------------------------
def own_lab(store: Store, *, create: bool = False, visibility: str = "public", description: str | None = None) -> dict | None:
    """This workshop's laboratory in the cloud (the one with its origin id, owned by the signed-in account), made when ``create``."""
    origin = _own_origin(store)
    for found in _call(store, "GET", "/labs")["labs"]:
        if found["origin_lab_id"] == origin:
            if found["role"] != "owner":
                raise CloudError("a laboratory with this workshop's identity exists in the cloud under another account", 409, "origin_taken")
            return found
    if not create:
        return None
    public = lab_export.public_info(store)
    if not public["name"] or not public["author"]:
        raise su.ValidationError("enter the laboratory's public name and the author before publishing")
    if visibility not in ("public", "private"):
        raise CloudError("the visibility of the laboratory is public or private", code="visibility")
    body = {"name": public["name"], "author": public["author"], "origin_lab_id": origin, "visibility": visibility,
            "description": (description if description is not None else public["description"]) or None, "url": public["url"] or None}
    made = _call(store, "POST", "/labs", body=body, ok=(201,))
    store.audit("cloud_lab_created", lab_id=made["id"], visibility=visibility)
    return {**made, "latest_release": None}


def _row(store: Store, publication_id: int) -> dict:
    row = store.one("SELECT * FROM lab_publication WHERE id=?", (publication_id,))
    if row is None:
        raise KeyError("no such publication")
    return dict(row)


def pending(store: Store) -> dict | None:
    row = store.one(f"SELECT * FROM lab_publication WHERE state IN ({','.join('?' * len(PENDING_STATES))}) ORDER BY id DESC LIMIT 1", PENDING_STATES)
    return dict(row) if row else None


def publications(store: Store) -> list[dict]:
    return [dict(r) for r in store.query("SELECT * FROM lab_publication ORDER BY id DESC")]


def _update(store: Store, row_id: int, **fields) -> None:
    fields["updated_at"] = now()
    store.execute(f"UPDATE lab_publication SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), row_id))


def publish(store: Store, *, terms: str, visibility: str = "public", description: str | None = None, selection: dict | None = None,
            wait: bool = False) -> dict:
    """Publish a new release of the own laboratory in the cloud: the job to poll. A publication left pending by a crash is not
    repeated: continue it with :func:`retry` or give it up with :func:`abandon`."""
    if terms not in lf.USAGE_TERMS:
        raise su.ValidationError("choose usage terms from the approved list")
    cloud_session.jwt(store)                                          # signed in, or nothing is started
    if pending(store) is not None:
        raise CloudError("a publication is still pending: continue it or give it up first", 409, "pending")
    laboratory = own_lab(store, create=True, visibility=visibility, description=description)
    stamp = now()
    row_id = store.conn.execute(
        "INSERT INTO lab_publication(idempotency_key, api_url, lab_id, visibility, terms, selection_json, state, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), _api(store), laboratory["id"], laboratory["visibility"], terms,
                                       json.dumps(dict(selection or {})), "reserved", stamp, stamp)).lastrowid
    store.audit("cloud_publication_started", publication=row_id, lab_id=laboratory["id"])
    return _run_publication(store, row_id, wait)


def retry(store: Store, *, wait: bool = False) -> dict:
    """Continue the pending publication with the same idempotency key: the cloud gives the same reservation back."""
    row = pending(store)
    if row is None:
        raise CloudError("there is no pending publication to continue", 404, "no_pending")
    cloud_session.jwt(store)
    return _run_publication(store, row["id"], wait)


def abandon(store: Store) -> dict | None:
    """Give up the pending publication: the row is marked failed; the cloud's reservation expires by itself, unseen by anyone."""
    row = pending(store)
    if row is None:
        return None
    _update(store, row["id"], state="failed", error="given up by the operator")
    store.audit("cloud_publication_abandoned", publication=row["id"])
    return _row(store, row["id"])


def _run_publication(store: Store, row_id: int, wait: bool) -> dict:
    row = _row(store, row_id)
    job = Job("publish", 0, {"publication": row_id, "lab_id": row["lab_id"], "terms": row["terms"]})

    def fail(message: str, code: str):
        _update(store, row_id, state="failed", error=message)
        raise CloudError(message, code=code)

    def work():
        if not _publishing.acquire(blocking=False):
            raise CloudError("another publication is running: wait until it ends", 409, "busy")
        try:
            current = _row(store, row_id)
            job.phase = "reserving"
            latest = _call(store, "GET", f"/labs/{current['lab_id']}")["latest_release"]
            reservation = _call(store, "POST", f"/labs/{current['lab_id']}/publications",
                                body={"idempotency_key": current["idempotency_key"], "expected_previous_release_id": latest["id"] if latest else None},
                                ok=(201,))
            if reservation["state"] != "uploading":
                fail("the cloud no longer takes this publication: it expired or failed there; publish again", "expired")
            _update(store, row_id, publication_id=reservation["id"], release_id=reservation["release_id"], release_number=reservation["release_number"],
                    expected_previous_release_id=reservation["expected_previous_release_id"], chunk_bytes=reservation["chunk_bytes"])
            current = _row(store, row_id)
            path = store.data_dir / EXPORTS / f"{current['release_id']}.tcelab"
            if current["state"] == "reserved" or not path.is_file():
                job.phase = "exporting"
                path.parent.mkdir(parents=True, exist_ok=True)
                if store.one("SELECT 1 FROM lab_export WHERE release_id=?", (current["release_id"],)) is None:
                    lab_export.export(store, path, json.loads(current["selection_json"]) or None, current["terms"], release_id=current["release_id"],
                                      release_number=current["release_number"], cancelled=job.cancel.is_set)
                elif not path.is_file():
                    fail("the exported file of this publication is gone from lab_exports: publish again", "file_missing")
                _update(store, row_id, state="exported")
            data = path.read_bytes()
            size = current["chunk_bytes"]
            pieces = [data[i:i + size] for i in range(0, len(data), size)] or [b""]
            job.total, job.read, job.phase = len(data), 0, "uploading"
            _update(store, row_id, state="uploading")
            for n, piece in enumerate(pieces):
                if job.cancel.is_set():
                    raise Cancelled()
                _retrying(lambda: _call(store, "PUT", f"/publications/{current['publication_id']}/chunks/{n}", raw=piece, timeout=CHUNK_TIMEOUT_S),
                          cancelled=job.cancel.is_set)
                job.read += len(piece)
            job.phase = "finalizing"
            declared = {"file_sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data), "chunk_count": len(pieces)}
            try:
                done = _retrying(lambda: _call(store, "POST", f"/publications/{current['publication_id']}/finalize", body=declared))
            except CloudError as exc:
                if exc.status in (409, 410):
                    fail(str(exc), exc.code)
                raise
            release = done["release"]
            _update(store, row_id, state="finalized", published_at=release["published_at"], release_number=release["number"], error=None)
            store.audit("cloud_published", publication=row_id, release_id=release["id"], number=release["number"], counts=release["counts"])
            job.result = {"release": release, "publication": _row(store, row_id)}
            job.phase = "done"
        finally:
            _publishing.release()

    return job.run(work, wait)


# -- withdrawals, invitations, members -----------------------------------------------------------------------------------------------
def withdraw(store: Store, target_kind: str, target_id: str, reason: str, replacement_release_id: str | None = None) -> dict:
    """Declare a withdrawal here (it goes out with every later release) and, when the own laboratory has releases in the cloud, on
    its latest cloud release at once, so that connected workshops learn it without waiting for the next release."""
    declared = lab_export.withdraw(store, target_kind, target_id, reason, replacement_release_id)
    laboratory = own_lab(store)
    latest = laboratory and laboratory.get("latest_release")
    if not latest:
        return {"local": declared, "cloud": None}
    body = {"targets": [{"kind": target_kind, "id": target_id}], "reason": declared["reason"], "replacement_release_id": replacement_release_id,
            "idempotency_key": declared["id"]}
    announced = _call(store, "POST", f"/releases/{latest['id']}/withdraw", body=body, ok=(201,))
    store.audit("cloud_withdrawn", release_id=latest["id"], target_kind=target_kind, target_id=target_id)
    return {"local": declared, "cloud": announced}


def _owned(store: Store) -> dict:
    laboratory = own_lab(store)
    if laboratory is None:
        raise CloudError("this workshop has no laboratory in the cloud yet: publish a release first", 404, "no_lab")
    return laboratory


def own(store: Store) -> dict:
    """The «Облако» block of «Моя лаборатория»: the account, the own cloud laboratory with its releases, the publications made from
    here (pending first), the invitations and the members."""
    state = cloud_session.account(store)
    out = {**state, "lab": None, "releases": [], "invitations": [], "members": [], "publications": publications(store), "pending": pending(store),
           "switched_on": cloud_session.switched_on()}
    if not state["signed_in"]:
        return out
    laboratory = own_lab(store)
    if laboratory is None:
        return out
    out["lab"] = laboratory
    out["releases"] = _call(store, "GET", f"/labs/{laboratory['id']}/releases", signed=False)["releases"]
    out["invitations"] = _call(store, "GET", f"/labs/{laboratory['id']}/invitations")["invitations"]
    out["members"] = _call(store, "GET", f"/labs/{laboratory['id']}/members")["members"]
    return out


def invite(store: Store, expires_in_s: int | None = None) -> dict:
    laboratory = _owned(store)
    body = {} if expires_in_s is None else {"expires_in_s": int(expires_in_s)}
    made = _call(store, "POST", f"/labs/{laboratory['id']}/invitations", body=body, ok=(201,))
    store.audit("cloud_invitation_created", lab_id=laboratory["id"], invitation=made["id"])
    return made


def revoke(store: Store, invitation_id: str) -> None:
    laboratory = _owned(store)
    _call(store, "DELETE", f"/labs/{laboratory['id']}/invitations/{invitation_id}", ok=(204,))
    store.audit("cloud_invitation_revoked", lab_id=laboratory["id"], invitation=invitation_id)


def remove_member(store: Store, account_id: str) -> None:
    laboratory = _owned(store)
    _call(store, "DELETE", f"/labs/{laboratory['id']}/members/{account_id}", ok=(204,))
    store.audit("cloud_member_removed", lab_id=laboratory["id"], account=account_id)


def accept(store: Store, link: str) -> dict:
    """Accept an invitation by its link (``{base}/invitations/{token}``) or bare token; the laboratory then appears in the catalogue."""
    text = (link or "").strip()
    token = text.rsplit("/invitations/", 1)[-1].strip("/").split("?")[0] if "/invitations/" in text else text
    if not token or len(token) > 256 or not all(c.isalnum() or c in "-_" for c in token):
        raise CloudError("paste the invitation link as it was given", code="invitation")
    accepted = _call(store, "POST", f"/invitations/{token}/accept", body={})
    store.audit("cloud_invitation_accepted", lab_id=accepted["lab"]["id"])
    return {**accepted, "lab": _marked(store, [{**accepted["lab"], "latest_release": None}])[0]}


# -- updates of the laboratories connected from the cloud ------------------------------------------------------------------------------
def check_updates(store: Store, source_id: int | None = None) -> list[dict]:
    """Whether the cloud has a newer release of each laboratory connected from it (or of ``source_id``); the result is kept on the
    source for the screen. A laboratory connected from a file is not asked about: a newer file is connected the same way."""
    sources = [s for s in lab_import.sources(store) if source_id is None or s["id"] == source_id]
    if source_id is not None and not sources:
        raise KeyError("no such connected laboratory")
    sources = [s for s in sources if s["origin"] == ORIGIN]
    if source_id is not None and not sources:
        raise CloudError("this laboratory was connected from a file: a newer release is connected from a file too", code="not_cloud")
    if not sources:
        return []
    by_origin = {found["origin_lab_id"]: found for found in _call(store, "GET", "/labs", signed=False)["labs"]}
    stamp = now()
    out = []
    for source in sources:
        found = by_origin.get(source["origin_lab_id"])
        latest = found.get("latest_release") if found else None
        current = source.get("current") or {}
        number = current.get("release_number")
        newer = bool(latest) and latest["id"] != current.get("release_id") and (number is None or latest["number"] > number)
        result = {"source_id": source["id"], "name": source["name"], "checked_at": stamp, "found": found is not None,
                  "lab_id": found["id"] if found else _lab_id_of(source), "current_release_id": current.get("release_id") or None,
                  "current_release_number": number, "latest": None if not latest else {k: latest[k] for k in ("id", "number", "created_at", "counts", "byte_size")},
                  "newer": newer, "withdrawn_here": source.get("release_withdrawn", False)}
        store.execute("UPDATE lab_source SET last_checked_at=?, last_check_json=? WHERE id=?", (stamp, json.dumps(result), source["id"]))
        out.append(result)
    store.audit("cloud_updates_checked", sources=[s["id"] for s in sources], newer=[r["source_id"] for r in out if r["newer"]])
    return out


def set_update_checks(store: Store, source_id: int, mode: str) -> dict:
    """How a laboratory connected from the cloud is checked for updates: by the button only, or also automatically (when the network
    setting ``update_checks`` allows any automatic check at all)."""
    if mode not in UPDATE_CHECK_MODES:
        raise su.ValidationError("the check for updates of a laboratory is manual or auto")
    source = next((s for s in lab_import.sources(store) if s["id"] == source_id), None)
    if source is None:
        raise KeyError("no such connected laboratory")
    if source["origin"] != ORIGIN:
        raise CloudError("this laboratory was connected from a file: a newer release is connected from a file too", code="not_cloud")
    if source["status"] != "connected":
        raise su.ValidationError("reconnect the laboratory first: a disconnected one is not checked")
    store.execute("UPDATE lab_source SET update_checks=? WHERE id=?", (mode, source_id))
    return next(s for s in lab_import.sources(store) if s["id"] == source_id)


def automatic_checks(store: Store) -> list[dict]:
    """The checks due now: laboratories set to ``auto`` not checked within a day, only when the network setting allows automatic
    checks; the screen calls it when it opens. A failure is reported, never raised: the screen still shows what it has."""
    if not outbound.get(store)["update_checks"]:
        return []
    due = []
    for source in lab_import.sources(store):
        if source["origin"] != ORIGIN or source["status"] != "connected" or source["update_checks"] != "auto":
            continue
        checked = source.get("last_checked_at")
        if checked:
            try:
                when = datetime.fromisoformat(checked.replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - when < timedelta(seconds=AUTO_CHECK_EVERY_S):
                    continue
            except ValueError:
                pass
        due.append(source["id"])
    out = []
    for source_id in due:
        try:
            out += check_updates(store, source_id)
        except (CloudError, su.ValidationError, KeyError) as exc:
            out.append({"source_id": source_id, "error": str(exc), "newer": False})
    return out


def exports_dir(store: Store) -> Path:
    return store.data_dir / EXPORTS
