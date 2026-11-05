"""Unfinished creation tasks (feature ux-work-creation-p0, DEC-001, REQ-002).

A new work starts with a picture, a name, a physical size, a chosen result and the settings of its method. When something is missing
(a laser, a lens, a titanium stock, a photography setup, or measurements that only a starter test can give) the person leaves to complete
it, and the engraving and the photograph of a starter test happen outside the application, perhaps after it was closed. So what was
entered is kept as a *draft*: a row of ``creation_draft`` with the picture beside it, and the application offers it again at the next start.

* ``status`` is ``open`` while the task is unfinished. Closing the application never changes it: an open draft is only ever closed by an
  explicit step, :func:`complete` (the work was made) or :func:`discard` (the person gave the task up). A completed or discarded draft is
  never listed as unfinished; it keeps its row (what was asked, and when it ended) and loses its picture.
* The picture is kept under ``files/drafts/`` of the workshop and the row names it relative to that folder, so a backup (which copies
  ``files/``) takes it along and a restore into another folder needs no rewriting of paths (``files.rebase_all`` has nothing to do here).
* ``state`` is the form as the person left it: a JSON object the screen defines (the step, the result, the name, the size, the settings
  of the method, the context at that moment and what interrupted the task). The server keeps it as it is and does not interpret it; it
  only bounds its size and requires an object.
* Making the work and closing its draft are two steps (the work comes first): if the application dies between them the task is offered
  once more, with its picture, and the person closes it; the other order could lose a task, so it is not used.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import conversion as cv, setup as su
from .db import Store, now

OPEN, COMPLETED, DISCARDED = "open", "completed", "discarded"
FLOWS = ("new", "vector", "photo-engraving", "discrete", "continuous")      # the creation entry a draft was started from
FOLDER = "drafts"                                                           # under the workshop's files/
MAX_STATE_BYTES = 64 * 1024
MAX_PICTURE_BYTES = 60 * 1024 * 1024
MEDIA_TYPES = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"BM", "image/bmp"), (b"II*\x00", "image/tiff"),
               (b"MM\x00*", "image/tiff"))


def _media_type(data: bytes) -> str:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return next((kind for magic, kind in MEDIA_TYPES if data.startswith(magic)), "application/octet-stream")


def _folder(store: Store) -> Path:
    folder = store.data_dir / "files" / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _state(state) -> str:
    """The form as JSON text: an object of bounded size."""
    if not isinstance(state, dict):
        raise su.ValidationError("the unfinished task must be an object")
    text = json.dumps(state, ensure_ascii=False, sort_keys=True)
    if len(text.encode("utf-8")) > MAX_STATE_BYTES:
        raise su.ValidationError("the unfinished task holds too much text")
    return text


def _row(store: Store, draft_id: int):
    row = store.one("SELECT * FROM creation_draft WHERE id=?", (draft_id,))
    if row is None:
        raise KeyError(f"unfinished task {draft_id} not found")
    return row


def _view(store: Store, row) -> dict:
    path = _folder(store) / row["image_file"] if row["image_file"] else None
    has_image = bool(path and path.is_file())
    return {"id": row["id"], "status": row["status"], "flow": row["flow"], "name": row["name"], "state": json.loads(row["state_json"]),
            "image": {"name": row["image_name"], "type": row["image_type"], "size": path.stat().st_size} if has_image else None,
            "created_at": row["created_at"], "updated_at": row["updated_at"], "finished_at": row["finished_at"],
            "work_kind": row["work_kind"], "work_id": row["work_id"]}


def _keep_picture(store: Store, data: bytes) -> tuple[str, str]:
    """Write a picture under files/drafts/ and give its name relative to that folder and its media type. A file that is no picture is
    refused before anything is written."""
    if not data:
        raise su.ValidationError("the picture is empty")
    if len(data) > MAX_PICTURE_BYTES:
        raise su.ValidationError(f"the picture is larger than {MAX_PICTURE_BYTES // (1024 * 1024)} MB")
    cv.decode_image_bytes(data)                         # ConversionError: "the image could not be read"
    name = f"draft-{uuid.uuid4().hex[:12]}.bin"
    (_folder(store) / name).write_bytes(data)
    return name, _media_type(data)


def _drop_picture(store: Store, name: str | None) -> None:
    if name:
        (_folder(store) / name).unlink(missing_ok=True)


def create(store: Store, flow: str, state: dict, picture: tuple[str, bytes] | None = None, name: str | None = None) -> dict:
    """A new unfinished task of the creation entry ``flow``, with its form ``state`` and its picture ``(file name, bytes)`` when there is one."""
    if flow not in FLOWS:
        raise su.ValidationError("the unfinished task belongs to an unknown creation screen")
    text = _state(state)
    kept = media = file_name = None
    if picture is not None:
        file_name, data = picture
        kept, media = _keep_picture(store, data)
    stamp = now()
    try:
        draft_id = store.execute("INSERT INTO creation_draft(status,flow,name,image_file,image_name,image_type,state_json,created_at,updated_at) "
                                 "VALUES (?,?,?,?,?,?,?,?,?)", (OPEN, flow, _title(name), kept, file_name, media, text, stamp, stamp)).lastrowid
    except BaseException:
        _drop_picture(store, kept)
        raise
    return _view(store, _row(store, draft_id))


def _title(name) -> str | None:
    return name.strip()[:200] or None if isinstance(name, str) else None


def update(store: Store, draft_id: int, state: dict | None = None, picture: tuple[str, bytes] | None = None, name: str | None = None) -> dict:
    """Save the form of an open task again: its ``state`` and/or its title, and a new picture when one is given (the old one is removed
    after the row names the new one). A task that is no longer open is not changed."""
    row = _row(store, draft_id)
    if row["status"] != OPEN:
        raise su.ValidationError("this task is finished: it cannot be changed")
    text = row["state_json"] if state is None else _state(state)
    kept, media, file_name = row["image_file"], row["image_type"], row["image_name"]
    replaced = None
    if picture is not None:
        file_name, data = picture
        replaced = row["image_file"]
        kept, media = _keep_picture(store, data)
    title = row["name"] if name is None else _title(name)
    try:
        store.execute("UPDATE creation_draft SET name=?, image_file=?, image_name=?, image_type=?, state_json=?, updated_at=? WHERE id=? AND status=?",
                      (title, kept, file_name, media, text, now(), draft_id, OPEN))
    except BaseException:
        if replaced is not None:
            _drop_picture(store, kept)
        raise
    _drop_picture(store, replaced)
    return _view(store, _row(store, draft_id))


def get(store: Store, draft_id: int) -> dict:
    return _view(store, _row(store, draft_id))


def listing(store: Store) -> list[dict]:
    """The tasks the person has not finished, the newest first. Only open ones: a completed or discarded task is never offered."""
    return [_view(store, r) for r in store.query("SELECT * FROM creation_draft WHERE status=? ORDER BY updated_at DESC, id DESC", (OPEN,))]


def picture(store: Store, draft_id: int) -> tuple[bytes, str, str | None]:
    """The picture of an open task: its bytes, its media type and the name of the file it came from."""
    row = _row(store, draft_id)
    path = _folder(store) / row["image_file"] if row["image_file"] else None
    if row["status"] != OPEN or path is None or not path.is_file():
        raise KeyError("the picture of this unfinished task is not kept")
    return path.read_bytes(), row["image_type"] or "application/octet-stream", row["image_name"]


def _finish(store: Store, draft_id: int, status: str, work_kind: str | None = None, work_id: int | None = None) -> dict:
    row = _row(store, draft_id)
    if row["status"] != OPEN:
        return _view(store, row)                          # finishing twice is not an error: the task is finished either way
    with store.transaction():
        store.execute("UPDATE creation_draft SET status=?, finished_at=?, updated_at=?, work_kind=?, work_id=?, image_file=NULL WHERE id=?",
                      (status, now(), now(), work_kind, work_id, draft_id))
        store.audit("creation_draft_" + status, draft_id=draft_id, flow=row["flow"], work_kind=work_kind, work_id=work_id)
    _drop_picture(store, row["image_file"])
    return _view(store, _row(store, draft_id))


def complete(store: Store, draft_id: int, work_kind: str, work_id: int) -> dict:
    """The work this task was for has been made: the task is over and is no longer offered."""
    if not isinstance(work_kind, str) or not work_kind.strip():
        raise su.ValidationError("name the kind of the work that was made")
    return _finish(store, draft_id, COMPLETED, work_kind.strip(), int(work_id))


def discard(store: Store, draft_id: int) -> dict:
    """The person gave the task up, explicitly: it is no longer offered and its picture is removed."""
    return _finish(store, draft_id, DISCARDED)
