"""A release as the server keeps it: chunks of a fixed size, read back as one stream for the format reader."""
from __future__ import annotations

import hashlib
import math
from typing import Iterable, Iterator


def chunk_count(byte_size: int, chunk_bytes: int) -> int:
    return max(1, math.ceil(byte_size / chunk_bytes))


def expected_size(n: int, byte_size: int, count: int, chunk_bytes: int) -> int:
    """The size chunk ``n`` of a file of ``byte_size`` bytes in ``count`` chunks must have: full chunks, then the rest."""
    return chunk_bytes if n < count - 1 else byte_size - (count - 1) * chunk_bytes


def split(data: bytes, chunk_bytes: int) -> Iterator[bytes]:
    for start in range(0, len(data), chunk_bytes):
        yield data[start:start + chunk_bytes]
    if not data:
        yield b""


class ChunkStream:
    """A binary stream over chunks in order, with ``readline(limit)`` and ``read(n)`` as the format reader uses them; it counts the bytes
    and hashes them, so the file's size and SHA-256 are known once it is read to the end."""

    def __init__(self, chunks: Iterable[bytes]):
        self._chunks = iter(chunks)
        self._buffer = b""
        self._done = False
        self.size = 0
        self.hasher = hashlib.sha256()

    def _more(self) -> bool:
        if self._done:
            return False
        try:
            piece = next(self._chunks)
        except StopIteration:
            self._done = True
            return False
        self._buffer += piece
        self.size += len(piece)
        self.hasher.update(piece)
        return True

    def readline(self, limit: int = -1) -> bytes:
        while True:
            at = self._buffer.find(b"\n")
            if at >= 0 and (limit < 0 or at < limit):
                line, self._buffer = self._buffer[:at + 1], self._buffer[at + 1:]
                return line
            if 0 <= limit <= len(self._buffer):
                line, self._buffer = self._buffer[:limit], self._buffer[limit:]
                return line
            if not self._more():
                line, self._buffer = self._buffer, b""
                return line

    def read(self, n: int = -1) -> bytes:
        while n < 0 or len(self._buffer) < n:
            if not self._more():
                break
        if n < 0:
            data, self._buffer = self._buffer, b""
        else:
            data, self._buffer = self._buffer[:n], self._buffer[n:]
        return data

    def drain(self) -> None:
        """Read whatever is left, so that ``size`` and the hash cover the whole file."""
        while self._more():
            pass
        self._buffer = b""

    @property
    def sha256(self) -> str:
        return self.hasher.hexdigest()
