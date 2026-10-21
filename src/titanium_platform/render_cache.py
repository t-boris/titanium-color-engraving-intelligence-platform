"""On-disk cache of the pictures drawn from a photograph (BUG-001).

Decoding a RAW, and for a corrected picture its linear decode and the chart correction, takes seconds; the picture depends
only on inputs that are known before it is drawn. A picture is therefore known by a key, the SHA-256 of a canonical JSON
of every one of those inputs and of ``RENDER_VERSION``, and is stored once drawn at
``<data dir>/cache/renders/<pair id>/<key>.png``. The cache is derived data: a missing or damaged file is drawn again,
deleting a pair removes its pictures, and the cache is kept under ``LIMIT_BYTES`` by removing the pictures used longest
ago. The same key is the picture's HTTP ETag.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .db import Store

RENDER_VERSION = 3                      # bump whenever the drawing of a cached picture changes: every stored picture is redrawn
#                                         2: the overlay outlines the layers that are off when the work was found by pictures (REQ-056)
#                                         3: paths that share their vertex or primitive list with an earlier path are outlined whole
LIMIT_BYTES = 500 * 1024 * 1024
PNG_START = b"\x89PNG\r\n\x1a\n"
PNG_END = b"IEND\xaeB`\x82"             # the last chunk of every complete PNG


def root(store: Store) -> Path:
    return Path(store.data_dir) / "cache" / "renders"


def pair_dir(store: Store, pair_id: int | str) -> Path:
    """The folder of a pair's pictures; a vector work's thumbnails use a folder of their own, ``vector-<plan id>``, the same way."""
    return root(store) / (pair_id if isinstance(pair_id, str) else str(int(pair_id)))


def file_stamp(path: str | Path | None) -> dict:
    """What identifies a stored file without reading it: its path, size and modification time (``missing`` when absent)."""
    if not path:
        return {"path": None, "missing": True}
    try:
        st = os.stat(path)
    except OSError:
        return {"path": str(path), "missing": True}
    return {"path": str(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns}


def text_digest(text: str | None) -> str | None:
    """A short stand-in for a large stored text (a plan's JSON) in a key."""
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def key_of(inputs: dict[str, Any]) -> str:
    """The key of a picture: SHA-256 of the canonical JSON of its inputs and of the drawing code's version."""
    text = json.dumps({"render_version": RENDER_VERSION, **inputs}, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read(store: Store, pair_id: int, key: str) -> bytes | None:
    """The stored picture, or None when it is missing or damaged (a damaged file is removed to be drawn again)."""
    path = pair_dir(store, pair_id) / f"{key}.png"
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not (data.startswith(PNG_START) and data.endswith(PNG_END)):
        path.unlink(missing_ok=True)
        return None
    try:
        os.utime(path)                  # used now: the size limit removes the pictures used longest ago first
    except OSError:
        pass
    return data


def write(store: Store, pair_id: int, key: str, data: bytes, limit: int = LIMIT_BYTES) -> None:
    """Store a picture atomically (a reader never sees half a file), then keep the cache within ``limit``."""
    folder = pair_dir(store, pair_id)
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(tmp, folder / f"{key}.png")
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    trim(store, limit)


def trim(store: Store, limit: int = LIMIT_BYTES) -> int:
    """Remove the pictures used longest ago until the cache holds at most ``limit`` bytes; the number of bytes removed."""
    pictures = []
    for folder, _, names in os.walk(root(store)):
        for name in names:
            if name.endswith(".png"):
                path = os.path.join(folder, name)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                pictures.append((st.st_mtime_ns, st.st_size, path))
    total, removed = sum(size for _, size, _ in pictures), 0
    for _, size, path in sorted(pictures):
        if total <= limit:
            break
        try:
            os.unlink(path)
        except OSError:
            continue
        total -= size
        removed += size
    return removed


def remove_pair(store: Store, pair_id: int) -> None:
    """Forget every picture of a pair (it was deleted)."""
    shutil.rmtree(pair_dir(store, pair_id), ignore_errors=True)


@dataclass(frozen=True)
class Picture:
    """A picture of one pair, known by its key before it is drawn: ``draw`` is called only when the cache lacks it."""
    store: Store
    pair_id: int
    key: str
    draw: Callable[[], bytes]

    def cached(self) -> bool:
        """Whether the picture is in the cache, intact."""
        return read(self.store, self.pair_id, self.key) is not None

    def png(self) -> bytes:
        data = read(self.store, self.pair_id, self.key)
        if data is None:
            data = self.draw()
            try:
                write(self.store, self.pair_id, self.key, data)
            except OSError:
                pass                    # a cache that cannot be written (disk full, read-only) only costs time
        return data
