"""Reader of Adobe Illustrator files (``.ai``) for the card editor (feature-3): the artwork of the file as :class:`Shape` objects.

An Illustrator file saved with "Create PDF Compatible File" is a PDF whose page is the artboard. There is no PDF library in the project, so
this module holds a small one that reads what the artwork needs and nothing else:

* the PDF syntax: objects, the cross-reference (classic tables, streams, hybrid files, incremental updates; rebuilt by scanning when it is
  missing or wrong), object streams, stream filters (Flate with predictors, LZW, ASCII85, ASCIIHex) -- everything lazily, so that the private
  data of Illustrator and the pictures, which make a file 44 MB, are never inflated;
* the content interpreter: the graphics state, paths, fills, strokes, clips, colours (device, ICC, Lab, indexed, separation and DeviceN
  with their tint functions, shading patterns as their average colour), form XObjects, optional content (layers) and opacity;
* the output of :func:`parse`: shapes in millimetres, y pointing down, origin at the top-left of the page, in painting order.

What the artwork holds that cannot be carried over (pictures, live text, tiling patterns, soft masks, dashes) is counted and said in the
notes. A file that cannot be read raises :class:`ValidationError` with a message for the operator; nothing else leaves :func:`parse`.
"""
from __future__ import annotations

import base64
import binascii
import itertools
import math
import re
import time
import zlib
from typing import Any, Callable, NamedTuple, Optional, Sequence

import numpy as np
import shapely
from shapely.geometry import Polygon, box

from . import card_vector_geometry as geo
from .card_vector_geometry import Parsed, Shape
from .color import lab_under_to_linear_rgb, linear_to_srgb
from .setup import ValidationError

__all__ = ["parse"]

# -- limits -----------------------------------------------------------------------------------------------------------------------------
MAX_STREAM_BYTES = 256 * 1024 * 1024        # one stream after decoding
MAX_TOTAL_BYTES = 600 * 1024 * 1024         # all streams of the file after decoding
MAX_VERTICES = 1_500_000                    # flattened vertices of all painted paths
MAX_SHAPES = 100_000
MAX_FORM_DEPTH = 12                         # form XObjects inside one another
FORM_CACHE_ITEM_BYTES = 4 * 1024 * 1024      # a form that is kept decoded, and all of them
FORM_CACHE_BYTES = 64 * 1024 * 1024
MAX_NESTING = 64                            # arrays and dictionaries inside one another
MAX_PAGE_NODES = 20_000
MAX_SECONDS = 90.0                          # of interpreting one file; beyond it the drawing is "too detailed"
MIN_STROKE_MM = 0.05                        # a line of width 0 is the thinnest line the device can draw
MM_PER_PT = 25.4 / 72.0
MAX_COORDINATE_MM = 1e7

PS_ONLY = ("This Illustrator file has no PDF-compatible content, so it cannot be imported. Open it in Illustrator and save it again with "
           "“Create PDF Compatible File” ticked, or export it as SVG.")
NOT_ILLUSTRATOR = ("This file is not an Illustrator file with PDF-compatible content, so it cannot be imported. Save the artwork in "
                   "Illustrator with “Create PDF Compatible File” ticked, or export it as SVG.")
ENCRYPTED = ("This Illustrator file is protected with a password or encryption, so it cannot be imported. Save an unprotected copy in "
             "Illustrator, or export it as SVG.")
DAMAGED = "This Illustrator file is damaged and cannot be read. Open it in Illustrator and save it again, or export it as SVG."
NO_PAGE = "This Illustrator file has no artboard to import."
TOO_DETAILED = ("This drawing is too detailed to import. Simplify it in Illustrator (fewer shapes and anchor points) or export a smaller "
                "part of it as SVG.")


class _PdfError(Exception):
    """The structure of the file is damaged at this place."""


class _NoPage(_PdfError):
    """The document has no page."""


class _BadOffset(_PdfError):
    """The cross-reference points to something that is not the object asked for."""


class _Abort(Exception):
    """The file is too large or too detailed to read within the limits."""


# =======================================================================================================================================
# PDF objects and syntax
# =======================================================================================================================================
class Name(str):
    """A PDF name (``/Type``); a plain ``str`` holds nothing else in the objects, so a name never equals a string of the file."""
    __slots__ = ()


class Ref(NamedTuple):
    num: int
    gen: int


class Stream:
    """A stream object: its dictionary and where its raw bytes lie in the file (never read until asked for)."""
    __slots__ = ("head", "start", "end")

    def __init__(self, head: dict, start: int, end: int):
        self.head, self.start, self.end = head, start, end


class _Op(str):
    """A keyword met where an object was expected (``endobj``, ``stream``, ``>>``...)."""
    __slots__ = ()


_REGULAR = rb"[^\x00\t\n\x0c\r ()<>\[\]{}/%]"
_SKIP = re.compile(rb"(?:[\x00\t\n\x0c\r ]+|%[^\r\n]*)*")
_TOKEN = re.compile(
    rb"(<<|>>|\[|\]|\{|\}|\(|<[^>]*>|/" + _REGULAR + rb"*"
    rb"|[+-]?(?:\d+\.?\d*|\.\d+)(?!" + _REGULAR + rb")"
    rb"|" + _REGULAR + rb"+|>|<|\))")
_REF_TAIL = re.compile(rb"[\x00\t\n\x0c\r ]+(\d+)[\x00\t\n\x0c\r ]+R(?!" + _REGULAR + rb")")
_STRING_SPECIAL = re.compile(rb"[()\\]")
_NAME_ESCAPE = re.compile(rb"#([0-9A-Fa-f]{2})")
_STRING_ESCAPE = re.compile(rb"\\(?:([nrtbf()\\])|([0-7]{1,3})|(\r\n|\n|\r)|([\s\S]))")
_STRING_SIMPLE = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}
_OBJ_HEAD = re.compile(rb"[\x00\t\n\x0c\r ]*(\d+)[\x00\t\n\x0c\r ]+(\d+)[\x00\t\n\x0c\r ]+obj(?![A-Za-z])")
_STREAM_WORD = re.compile(rb"[\x00\t\n\x0c\r ]*stream(?:\r\n|\n|\r)?")
_END_STREAM = re.compile(rb"[\x00\t\n\x0c\r ]*endstream")
_OBJ_SCAN = re.compile(rb"(?<![\w.])(\d{1,10})[\x00\t\n\x0c\r ]+(\d{1,5})[\x00\t\n\x0c\r ]+obj(?![A-Za-z])")
_XREF_SUBSECTION = re.compile(rb"[\x00\t\n\x0c\r ]*(\d+)[\x00\t\n\x0c\r ]+(\d+)")
_XREF_ENTRY = re.compile(rb"[\x00\t\n\x0c\r ]*(\d+)[\x00\t\n\x0c\r ]+(\d+)[\x00\t\n\x0c\r ]+([nf])")
_TRAILER_WORD = re.compile(rb"[\x00\t\n\x0c\r ]*trailer")
_START_XREF = re.compile(rb"startxref[\x00\t\n\x0c\r ]+(\d+)")


def _name(token: bytes) -> str:
    raw = token[1:]
    if b"#" in raw:
        raw = _NAME_ESCAPE.sub(lambda m: bytes([int(m.group(1), 16)]), raw)
    return raw.decode("latin-1")


def _unescape(raw: bytes) -> bytes:
    if b"\\" not in raw:
        return raw

    def one(m):
        if m.group(1):
            return _STRING_SIMPLE[m.group(1)]
        if m.group(2):
            return bytes([int(m.group(2), 8) & 255])
        if m.group(3):
            return b""
        return m.group(4)
    return _STRING_ESCAPE.sub(one, raw)


def _parse(data: bytes, pos: int, depth: int = 0) -> tuple[Any, int]:
    """The object that starts at ``pos`` and the position after it. Keywords that are not objects come back as :class:`_Op`."""
    if depth > MAX_NESTING:
        raise _PdfError("nesting")
    pos = _SKIP.match(data, pos).end()
    m = _TOKEN.match(data, pos)
    if m is None:
        raise _PdfError("syntax")
    token = m.group(1)
    end = m.end()
    first = token[0]
    if first == 0x2F:                                                   # /
        return Name(_name(token)), end
    if token == b"<<":
        out: dict = {}
        while True:
            pos = _SKIP.match(data, end).end()
            key_match = _TOKEN.match(data, pos)
            if key_match is None:
                raise _PdfError("dictionary")
            key = key_match.group(1)
            if key == b">>":
                return out, key_match.end()
            if key[0] != 0x2F:
                if key in (b"endobj", b"stream", b"endstream"):         # the closing >> is missing
                    return out, pos
                end = key_match.end()
                continue
            value, end = _parse(data, key_match.end(), depth + 1)
            if isinstance(value, _Op):
                if value == ">>":
                    out[_name(key)] = None
                    return out, end
                if value in ("endobj", "stream", "endstream"):
                    return out, pos
                value = None
            out[_name(key)] = value
    if first == 0x5B:                                                   # [
        items: list = []
        while True:
            value, end = _parse(data, end, depth + 1)
            if isinstance(value, _Op):
                if value == "]":
                    return items, end
                if value in ("endobj", "stream", "endstream", ">>"):          # the closing ] is missing
                    return items, end - len(value)
                continue
            items.append(value)
    if first == 0x28:                                                   # (
        level, i = 1, end
        while level:
            special = _STRING_SPECIAL.search(data, i)
            if special is None:
                raise _PdfError("string")
            ch = data[special.start()]
            if ch == 0x5C:
                i = special.start() + 2
                continue
            level += 1 if ch == 0x28 else -1
            i = special.start() + 1
        return _unescape(data[end:i - 1]), i
    if first == 0x3C and len(token) >= 2:                               # <hex>
        digits = re.sub(rb"[^0-9A-Fa-f]", b"", token)
        if len(digits) % 2:
            digits += b"0"
        return binascii.unhexlify(digits), end
    if token.isdigit():
        number = int(token)
        tail = _REF_TAIL.match(data, end)
        if tail is not None:
            return Ref(number, int(tail.group(1))), tail.end()
        return number, end
    if first in b"+-.0123456789":
        try:
            return (float(token) if b"." in token else int(token)), end
        except ValueError:
            return _Op(token.decode("latin-1")), end
    if token == b"true":
        return True, end
    if token == b"false":
        return False, end
    if token == b"null":
        return None, end
    return _Op(token.decode("latin-1")), end


# =======================================================================================================================================
# Stream filters
# =======================================================================================================================================
def _inflate(raw: bytes) -> bytes:
    """Flate data, as far as it goes: a truncated or damaged stream gives what could be read before the damage."""
    chunk_size = 1 << 16
    for wbits, skip in ((zlib.MAX_WBITS, 0), (-zlib.MAX_WBITS, 2)):
        decoder = zlib.decompressobj(wbits)
        out: list[bytes] = []
        total = 0
        try:
            for i in range(skip, len(raw), chunk_size):
                chunk = raw[i:i + chunk_size]
                while chunk:
                    piece = decoder.decompress(chunk, MAX_STREAM_BYTES - total + 1)
                    total += len(piece)
                    if total > MAX_STREAM_BYTES:
                        raise _Abort("stream too large")
                    out.append(piece)
                    chunk = decoder.unconsumed_tail
                if decoder.eof:
                    break
        except zlib.error:
            pass
        if out:
            return b"".join(out)
    return b""


def _lzw(data: bytes, early: int = 1) -> bytes:
    out = bytearray()
    table: list[bytes] = [bytes([i]) for i in range(256)] + [b"", b""]
    bits, acc, held = 9, 0, 0
    previous: Optional[bytes] = None
    for byte in data:
        acc = (acc << 8) | byte
        held += 8
        while held >= bits:
            code = (acc >> (held - bits)) & ((1 << bits) - 1)
            held -= bits
            acc &= (1 << held) - 1
            if code == 256:
                del table[258:]
                bits, previous = 9, None
                continue
            if code == 257:
                return bytes(out)
            if previous is None:
                if code >= len(table):
                    return bytes(out)
                entry = table[code]
            else:
                if code < len(table):
                    entry = table[code]
                elif code == len(table):
                    entry = previous + previous[:1]
                else:
                    return bytes(out)
                if len(table) < 4096:
                    table.append(previous + entry[:1])
            out += entry
            if len(out) > MAX_STREAM_BYTES:
                raise _Abort("stream too large")
            previous = entry
            size = len(table) + early
            bits = 9 if size < 512 else 10 if size < 1024 else 11 if size < 2048 else 12
    return bytes(out)


def _ascii85(data: bytes) -> bytes:
    text = re.sub(rb"\s+", b"", data)
    if text.startswith(b"<~"):
        text = text[2:]
    end = text.find(b"~>")
    if end >= 0:
        text = text[:end]
    try:
        return base64.a85decode(text)
    except ValueError:
        return base64.a85decode(text[:len(text) - len(text) % 5]) if len(text) >= 5 else b""


def _ascii_hex(data: bytes) -> bytes:
    end = data.find(b">")
    digits = re.sub(rb"[^0-9A-Fa-f]", b"", data if end < 0 else data[:end])
    return binascii.unhexlify(digits + (b"0" if len(digits) % 2 else b""))


def _predict(data: bytes, parms: dict) -> bytes:
    """Undo the predictor of a Flate or LZW stream: TIFF (2) and PNG (10..15) as the cross-reference and object streams use them."""
    predictor = int(parms.get("Predictor") or 1)
    if predictor < 2:
        return data
    colours = max(1, int(parms.get("Colors") or 1))
    bits = int(parms.get("BitsPerComponent") or 8)
    columns = max(1, int(parms.get("Columns") or 1))
    row_len = (colours * bits * columns + 7) // 8
    if predictor == 2:
        if bits != 8:
            return data
        rows = len(data) // row_len
        arr = np.frombuffer(data, np.uint8, count=rows * row_len).reshape(rows, columns, colours).astype(np.uint16)
        return (np.cumsum(arr, axis=1) & 255).astype(np.uint8).tobytes()
    bpp = max(1, colours * bits // 8)
    stride = row_len + 1
    rows = (len(data) + stride - 1) // stride
    if rows == 0:
        return b""
    padded = data + bytes(rows * stride - len(data))
    arr = np.frombuffer(padded, np.uint8).reshape(rows, stride)
    out = np.zeros((rows, row_len), np.uint8)
    previous = np.zeros(row_len, np.uint8)
    for i in range(rows):
        kind = int(arr[i, 0])
        row = arr[i, 1:]
        if kind == 0:
            current = row.copy()
        elif kind == 2:
            current = row + previous
        elif kind == 1 and row_len % bpp == 0:
            current = (np.cumsum(row.reshape(-1, bpp).astype(np.uint32), axis=0) & 255).astype(np.uint8).reshape(-1)
        else:                                                           # sub (odd widths), average, Paeth: byte by byte
            raw, prev = row.tolist(), previous.tolist()
            cur = [0] * row_len
            for j in range(row_len):
                left = cur[j - bpp] if j >= bpp else 0
                up = prev[j]
                if kind == 1:
                    value = raw[j] + left
                elif kind == 3:
                    value = raw[j] + (left + up) // 2
                elif kind == 4:
                    corner = prev[j - bpp] if j >= bpp else 0
                    p = left + up - corner
                    pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                    value = raw[j] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)
                else:
                    value = raw[j]
                cur[j] = value & 255
            current = np.array(cur, np.uint8)
        out[i] = current
        previous = out[i]
    return out.tobytes()


# =======================================================================================================================================
# The document: cross-reference, objects, streams, page tree
# =======================================================================================================================================
class _Doc:
    def __init__(self, data: bytes):
        self.data = data
        self.xref: dict[int, tuple] = {}
        self.trailer: dict = {}
        self.rebuilt = False
        self.inflated = 0
        self._cache: dict[int, Any] = {}
        self._loading: set[int] = set()
        self._object_streams: dict[int, tuple[bytes, int, dict[int, int]]] = {}
        ready = False
        try:
            self._read_cross_reference()
        except (_PdfError, ValueError, IndexError, KeyError, TypeError, RecursionError):
            pass
        else:
            if "Encrypt" in self.trailer:
                raise ValidationError(ENCRYPTED)
            try:
                ready = self._has_root()
            except (_PdfError, ValueError, IndexError, KeyError, TypeError, RecursionError):
                ready = False
        if not ready and not self.rebuilt:
            self._rebuild()
        if "Encrypt" in self.trailer:
            raise ValidationError(ENCRYPTED)

    # -- values ------------------------------------------------------------------------------------------------------------------------
    def resolve(self, obj: Any) -> Any:
        for _ in range(16):
            if not isinstance(obj, Ref):
                return obj
            obj = self.get(obj.num)
        return None

    def get(self, num: int) -> Any:
        try:
            return self._cache[num]
        except KeyError:
            pass
        entry = self.xref.get(num)
        if entry is None or num in self._loading:
            return None
        self._loading.add(num)
        try:
            try:
                obj = self._load(entry, num)
            except _BadOffset:
                obj = None
                if not self.rebuilt:
                    self._rebuild()
                    entry = self.xref.get(num)
                    if entry is not None:
                        try:
                            obj = self._load(entry, num)
                        except _PdfError:
                            obj = None
            except (_PdfError, ValueError, IndexError, KeyError, TypeError, RecursionError):
                obj = None
        finally:
            self._loading.discard(num)
        self._cache[num] = obj
        return obj

    def dict_of(self, obj: Any) -> dict:
        """The dictionary of a dictionary or of a stream (an empty one for anything else)."""
        obj = self.resolve(obj)
        if isinstance(obj, Stream):
            return obj.head
        return obj if isinstance(obj, dict) else {}

    def numbers(self, obj: Any, count: Optional[int] = None) -> Optional[list[float]]:
        obj = self.resolve(obj)
        if not isinstance(obj, list):
            return None
        out: list[float] = []
        for item in obj:
            item = self.resolve(item)
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                return None
            out.append(float(item))
        if count is not None:
            if len(out) < count:
                return None
            out = out[:count]
        return out

    def number(self, obj: Any, default: float) -> float:
        obj = self.resolve(obj)
        return float(obj) if isinstance(obj, (int, float)) and not isinstance(obj, bool) else default

    # -- loading objects -----------------------------------------------------------------------------------------------------------------
    def _load(self, entry: tuple, num: int) -> Any:
        if entry[0] == "off":
            return self._read_at(entry[1], num)
        return self._read_compressed(entry[1], num)

    def _read_at(self, offset: int, num: int) -> Any:
        head = _OBJ_HEAD.match(self.data, offset)
        if head is None or int(head.group(1)) != num:
            raise _BadOffset(num)
        obj, pos = _parse(self.data, head.end())
        if isinstance(obj, _Op):
            return None
        if isinstance(obj, dict):
            word = _STREAM_WORD.match(self.data, pos)
            if word is not None:
                return self._stream(obj, word.end())
        return obj

    def _stream(self, head: dict, start: int) -> Stream:
        data = self.data
        end = -1
        length = self.resolve(head.get("Length"))
        if isinstance(length, int) and not isinstance(length, bool) and 0 <= length and start + length <= len(data):
            if _END_STREAM.match(data, start + length) is not None:
                end = start + length
        if end < 0:
            end = data.find(b"endstream", start)
            if end < 0:
                end = data.find(b"endobj", start)
            if end < 0:
                end = len(data)
            if data[end - 2:end] == b"\r\n":
                end -= 2
            elif data[end - 1:end] in (b"\n", b"\r"):
                end -= 1
        return Stream(head, start, max(start, end))

    def _read_compressed(self, stream_num: int, num: int) -> Any:
        stored = self._object_streams.get(stream_num)
        if stored is None:
            stream = self.get(stream_num)
            if not isinstance(stream, Stream):
                raise _PdfError("object stream")
            body = self.stream_data(stream)
            if body is None:
                raise _PdfError("object stream")
            count = int(self.number(stream.head.get("N"), 0))
            first = int(self.number(stream.head.get("First"), 0))
            numbers = re.findall(rb"\d+", body[:first])[:2 * count]
            where = {int(numbers[i]): int(numbers[i + 1]) for i in range(0, len(numbers) - 1, 2)}
            stored = (body, first, where)
            if len(self._object_streams) >= 4:
                self._object_streams.pop(next(iter(self._object_streams)))
            self._object_streams[stream_num] = stored
        body, first, where = stored
        if num not in where:
            raise _PdfError("object not in its stream")
        obj, _ = _parse(body, first + where[num])
        return None if isinstance(obj, _Op) else obj

    # -- streams -------------------------------------------------------------------------------------------------------------------------
    def stream_data(self, stream: Stream) -> Optional[bytes]:
        """The decoded bytes of a stream, or None when a filter is not one the artwork uses (pictures: DCT, JPX, CCITT...)."""
        head = stream.head
        filters = self.resolve(head.get("Filter"))
        filters = [] if filters is None else filters if isinstance(filters, list) else [filters]
        parms = self.resolve(head.get("DecodeParms"))
        parms = [] if parms is None else parms if isinstance(parms, list) else [parms]
        data = self.data[stream.start:stream.end]
        for i, name in enumerate(filters):
            name = self.resolve(name)
            options = self.resolve(parms[i]) if i < len(parms) else None
            options = options if isinstance(options, dict) else {}
            options = {k: self.resolve(v) for k, v in options.items()}
            if name in ("FlateDecode", "Fl"):
                data = _predict(_inflate(data), options)
            elif name in ("LZWDecode", "LZW"):
                early = options.get("EarlyChange")
                data = _predict(_lzw(data, 1 if early is None else int(early)), options)
            elif name in ("ASCII85Decode", "A85"):
                data = _ascii85(data)
            elif name in ("ASCIIHexDecode", "AHx"):
                data = _ascii_hex(data)
            elif name == "Crypt":
                continue
            else:
                return None
            if len(data) > MAX_STREAM_BYTES:
                raise _Abort("stream too large")
        self.inflated += len(data)
        if self.inflated > MAX_TOTAL_BYTES:
            raise _Abort("file too large")
        return data

    # -- cross-reference -------------------------------------------------------------------------------------------------------------
    def _has_root(self) -> bool:
        root = self.resolve(self.trailer.get("Root"))
        return isinstance(root, dict) and self.resolve(root.get("Pages")) is not None

    def _read_cross_reference(self) -> None:
        data = self.data
        found = data.rfind(b"startxref")
        if found < 0:
            raise _PdfError("no startxref")
        match = _START_XREF.match(data, found)
        if match is None:
            raise _PdfError("startxref")
        entries: dict[int, tuple] = {}
        trailer: dict = {}
        position: Any = int(match.group(1))
        seen: set[int] = set()
        while isinstance(position, (int, float)) and not isinstance(position, bool) and int(position) not in seen:
            position = int(position)
            seen.add(position)
            table, section = self._read_section(position)
            for num, entry in table.items():
                entries.setdefault(num, entry)
            for key, value in section.items():
                trailer.setdefault(key, value)
            hybrid = section.get("XRefStm")
            if isinstance(hybrid, int) and int(hybrid) not in seen:
                seen.add(int(hybrid))
                more, _ = self._read_section(int(hybrid))
                for num, entry in more.items():
                    entries.setdefault(num, entry)
            position = section.get("Prev")
        if not entries:
            raise _PdfError("empty cross-reference")
        self.xref, self.trailer = entries, trailer

    def _read_section(self, position: int) -> tuple[dict[int, tuple], dict]:
        data = self.data
        start = _SKIP.match(data, position).end()
        if data.startswith(b"xref", start):
            return self._read_table(start + 4)
        head = _OBJ_HEAD.match(data, start)
        if head is None:
            raise _PdfError("cross-reference")
        obj, pos = _parse(data, head.end())
        word = _STREAM_WORD.match(data, pos)
        if not isinstance(obj, dict) or word is None:
            raise _PdfError("cross-reference stream")
        return self._stream_entries(self._stream(obj, word.end())), obj

    def _read_table(self, pos: int) -> tuple[dict[int, tuple], dict]:
        data = self.data
        entries: dict[int, tuple] = {}
        while True:
            sub = _XREF_SUBSECTION.match(data, pos)
            if sub is None:
                break
            first, count = int(sub.group(1)), int(sub.group(2))
            pos = sub.end()
            if count > (len(data) - pos) // 15 + 1:
                raise _PdfError("cross-reference count")
            for i in range(count):
                entry = _XREF_ENTRY.match(data, pos)
                if entry is None:
                    raise _PdfError("cross-reference entry")
                pos = entry.end()
                if i == 0 and first == 1 and entry.group(3) == b"f" and int(entry.group(2)) == 65535:
                    first = 0                                           # a table that numbers its first object 1 though it lists 0 first
                if entry.group(3) == b"n" and int(entry.group(1)) > 0:
                    entries.setdefault(first + i, ("off", int(entry.group(1))))
        word = _TRAILER_WORD.match(data, pos)
        if word is None:
            raise _PdfError("trailer")
        trailer, _ = _parse(data, word.end())
        if not isinstance(trailer, dict):
            raise _PdfError("trailer")
        return entries, trailer

    def _stream_entries(self, stream: Stream) -> dict[int, tuple]:
        head = stream.head
        widths = self.numbers(head.get("W"), 3)
        if widths is None or not all(0 <= w <= 8 for w in widths):
            raise _PdfError("W")
        w = [int(v) for v in widths]
        row = sum(w)
        body = self.stream_data(stream)
        if row <= 0 or body is None:
            raise _PdfError("cross-reference stream")
        rows = len(body) // row
        table = np.frombuffer(body, np.uint8, count=rows * row).reshape(rows, row)

        def field(index: int, default: int) -> list[int]:
            if w[index] == 0:
                return [default] * rows
            at = sum(w[:index])
            column = np.zeros(rows, np.uint64)
            for j in range(w[index]):
                column = (column << np.uint64(8)) | table[:, at + j].astype(np.uint64)
            return column.astype(np.int64).tolist()
        kinds, second, third = field(0, 1), field(1, 0), field(2, 0)
        size = int(self.number(head.get("Size"), rows))
        index = self.numbers(head.get("Index")) or [0.0, float(size)]
        entries: dict[int, tuple] = {}
        r = 0
        for first, count in zip(index[0::2], index[1::2]):
            for i in range(int(count)):
                if r >= rows:
                    break
                if kinds[r] == 1:
                    entries.setdefault(int(first) + i, ("off", second[r]))
                elif kinds[r] == 2:
                    entries.setdefault(int(first) + i, ("stm", second[r]))
                r += 1
        return entries

    def _rebuild(self) -> None:
        """Rebuild the cross-reference by looking for the objects themselves (a file that was damaged or edited by hand)."""
        self.rebuilt = True
        data = self.data
        self._cache.clear()
        self._object_streams.clear()
        entries: dict[int, tuple] = {}
        where: dict[int, int] = {}
        containers: list[int] = []
        catalogues: list[int] = []
        trailer: dict = {}
        for m in _OBJ_SCAN.finditer(data):
            num = int(m.group(1))
            entries[num] = ("off", m.start(1))
            where[num] = m.start(1)
            peek = data[m.end():m.end() + 400]
            if b"/ObjStm" in peek:
                containers.append(num)
            elif b"/XRef" in peek:
                try:
                    obj, _ = _parse(data, m.end())
                except _PdfError:
                    obj = None
                if isinstance(obj, dict) and obj.get("Type") == "XRef":
                    for key in ("Root", "Encrypt", "Info"):
                        if key in obj:
                            trailer[key] = obj[key]
            elif b"/Catalog" in peek:
                catalogues.append(num)
        for m in re.finditer(rb"trailer", data):
            try:
                obj, _ = _parse(data, m.end())
            except _PdfError:
                continue
            if isinstance(obj, dict):
                for key in ("Root", "Encrypt", "Info"):
                    if key in obj:
                        trailer[key] = obj[key]
        self.xref = entries
        for stream_num in containers:                                  # objects inside object streams
            try:
                stream = self.get(stream_num)
                if "Encrypt" in trailer or not isinstance(stream, Stream):
                    continue
                body = self.stream_data(stream)
                first = int(self.number(stream.head.get("First"), 0))
                count = int(self.number(stream.head.get("N"), 0))
                numbers = re.findall(rb"\d+", body[:first])[:2 * count] if body else []
            except (_PdfError, ValueError):
                continue
            for i in range(0, len(numbers) - 1, 2):
                num = int(numbers[i])
                if where.get(num, -1) < where[stream_num]:
                    entries[num] = ("stm", stream_num)
                    where[num] = where[stream_num]
            if "Root" not in trailer and body and b"/Catalog" in body:
                for i in range(0, len(numbers) - 1, 2):
                    try:
                        obj, _ = _parse(body, first + int(numbers[i + 1]))
                    except _PdfError:
                        continue
                    if isinstance(obj, dict) and obj.get("Type") == "Catalog":
                        trailer["Root"] = Ref(int(numbers[i]), 0)
        if "Root" not in trailer and catalogues:
            trailer["Root"] = Ref(catalogues[-1], 0)
        self._cache.clear()
        self.trailer = trailer

    # -- the page ------------------------------------------------------------------------------------------------------------------------
    def first_page(self) -> tuple[dict, int]:
        """The first page with the attributes it inherits, and the number of pages."""
        root = self.resolve(self.trailer.get("Root"))
        if not isinstance(root, dict):
            raise _PdfError("catalogue")
        stack: list[tuple[Any, dict]] = [(root.get("Pages"), {})]
        seen: set[int] = set()
        page: Optional[dict] = None
        total: Optional[int] = None
        top = True
        while stack and page is None:
            ref, inherited = stack.pop()
            if isinstance(ref, Ref):
                if ref.num in seen:
                    continue
                seen.add(ref.num)
                if len(seen) > MAX_PAGE_NODES:
                    raise _PdfError("page tree")
            node = self.resolve(ref)
            if not isinstance(node, dict):
                continue
            merged = dict(inherited)
            for key in ("MediaBox", "CropBox", "Resources", "Rotate"):
                if key in node:
                    merged[key] = node[key]
            kids = self.resolve(node.get("Kids"))
            if isinstance(kids, list) and node.get("Type") != "Page":
                if top:
                    count = self.resolve(node.get("Count"))
                    total = int(count) if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else None
                top = False
                for kid in reversed(kids):
                    stack.append((kid, merged))
                continue
            top = False
            page = dict(node)
            for key, value in merged.items():
                page.setdefault(key, value)
        if page is None:
            raise _NoPage("no page")
        if total is None:
            total = self._count_pages(root.get("Pages"))
        return page, total

    def _count_pages(self, ref: Any) -> int:
        stack, seen, leaves = [ref], set(), 0
        while stack and leaves < 1000:
            item = stack.pop()
            if isinstance(item, Ref):
                if item.num in seen or len(seen) > MAX_PAGE_NODES:
                    continue
                seen.add(item.num)
            node = self.resolve(item)
            if not isinstance(node, dict):
                continue
            kids = self.resolve(node.get("Kids"))
            if isinstance(kids, list) and node.get("Type") != "Page":
                stack.extend(kids)
            else:
                leaves += 1
        return leaves


# =======================================================================================================================================
# Optional content (layers)
# =======================================================================================================================================
def _text_of(raw: Any) -> Optional[str]:
    if not isinstance(raw, bytes):
        return str(raw) if isinstance(raw, Name) else None
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", "replace")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", "replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


class _Layers:
    """Which optional content groups are shown in the default configuration of the document."""

    def __init__(self, doc: _Doc):
        self.doc = doc
        root = doc.resolve(doc.trailer.get("Root"))
        props = doc.dict_of(root.get("OCProperties")) if isinstance(root, dict) else {}
        config = doc.dict_of(props.get("D"))
        self.base_on = str(doc.resolve(config.get("BaseState")) or "ON") != "OFF"
        self.on = self._numbers(config.get("ON"))
        self.off = self._numbers(config.get("OFF"))

    def _numbers(self, raw: Any) -> set[int]:
        items = self.doc.resolve(raw)
        return {item.num for item in items if isinstance(item, Ref)} if isinstance(items, list) else set()

    def _group_on(self, raw: Any) -> bool:
        if isinstance(raw, Ref):
            if raw.num in self.off:
                return False
            if raw.num in self.on:
                return True
        return self.base_on

    def status(self, raw: Any, depth: int = 0) -> tuple[bool, Optional[str]]:
        """Whether what is marked with this group or membership dictionary is shown, and the name of the layer when it is a group."""
        obj = self.doc.resolve(raw)
        if not isinstance(obj, dict) or depth > 8:
            return True, None
        if obj.get("Type") == "OCMD":
            expression = self.doc.resolve(obj.get("VE"))
            if isinstance(expression, list):
                return self._expression(expression, depth + 1), None
            groups = obj.get("OCGs")
            resolved = self.doc.resolve(groups)
            items = resolved if isinstance(resolved, list) else [groups] if resolved is not None else []
            states = [self._group_on(item) for item in items]
            policy = str(self.doc.resolve(obj.get("P")) or "AnyOn")
            if not states:
                return True, None
            if policy == "AllOn":
                return all(states), None
            if policy == "AnyOff":
                return any(not s for s in states), None
            if policy == "AllOff":
                return not any(states), None
            return any(states), None
        return self._group_on(raw), _text_of(self.doc.resolve(obj.get("Name")))

    def _expression(self, expression: list, depth: int) -> bool:
        if not expression or depth > 8:
            return True
        operator = str(self.doc.resolve(expression[0]))
        operands = expression[1:]

        def value(item: Any) -> bool:
            resolved = self.doc.resolve(item)
            if isinstance(resolved, list):
                return self._expression(resolved, depth + 1)
            return self._group_on(item)
        if operator == "Not":
            return not value(operands[0]) if operands else True
        values = [value(item) for item in operands]
        if operator == "And":
            return all(values)
        if operator == "Or":
            return any(values)
        return True


# =======================================================================================================================================
# Functions (tint transforms and shadings)
# =======================================================================================================================================
class _FunctionError(Exception):
    pass


def _bin(fn: Callable[[Any, Any], Any]) -> Callable[[list], None]:
    def op(stack: list) -> None:
        b = stack.pop()
        a = stack.pop()
        stack.append(fn(a, b))
    return op


def _un(fn: Callable[[Any], Any]) -> Callable[[list], None]:
    def op(stack: list) -> None:
        stack.append(fn(stack.pop()))
    return op


def _idiv(a, b):
    a, b = int(a), int(b)
    quotient = abs(a) // abs(b)
    return quotient if (a >= 0) == (b >= 0) else -quotient


def _bitwise(logical, bitwise):
    return _bin(lambda a, b: logical(a, b) if isinstance(a, bool) and isinstance(b, bool) else bitwise(int(a), int(b)))


def _copy(stack: list) -> None:
    n = int(stack.pop())
    if n < 0 or n > len(stack) or n > 100:
        raise _FunctionError("copy")
    if n:
        stack.extend(stack[-n:])


def _index(stack: list) -> None:
    n = int(stack.pop())
    if n < 0 or n >= len(stack):
        raise _FunctionError("index")
    stack.append(stack[-1 - n])


def _roll(stack: list) -> None:
    j = int(stack.pop())
    n = int(stack.pop())
    if n < 0 or n > len(stack):
        raise _FunctionError("roll")
    if n:
        j %= n
        if j:
            part = stack[-n:]
            stack[-n:] = part[-j:] + part[:-j]


_PS_OPS: dict[str, Callable[[list], None]] = {
    "abs": _un(abs), "neg": _un(lambda a: -a), "ceiling": _un(lambda a: float(math.ceil(a))), "floor": _un(lambda a: float(math.floor(a))),
    "round": _un(lambda a: float(math.floor(a + 0.5))), "truncate": _un(lambda a: float(math.trunc(a))), "sqrt": _un(math.sqrt),
    "sin": _un(lambda a: math.sin(math.radians(a))), "cos": _un(lambda a: math.cos(math.radians(a))), "ln": _un(math.log),
    "log": _un(math.log10), "cvi": _un(lambda a: int(math.trunc(a))), "cvr": _un(float),
    "add": _bin(lambda a, b: a + b), "sub": _bin(lambda a, b: a - b), "mul": _bin(lambda a, b: a * b), "div": _bin(lambda a, b: a / b),
    "idiv": _bin(_idiv), "mod": _bin(lambda a, b: int(math.fmod(int(a), int(b)))), "exp": _bin(lambda a, b: float(a) ** b),
    "atan": _bin(lambda a, b: math.degrees(math.atan2(a, b)) % 360.0),
    "eq": _bin(lambda a, b: a == b), "ne": _bin(lambda a, b: a != b), "gt": _bin(lambda a, b: a > b), "ge": _bin(lambda a, b: a >= b),
    "lt": _bin(lambda a, b: a < b), "le": _bin(lambda a, b: a <= b),
    "and": _bitwise(lambda a, b: a and b, lambda a, b: a & b), "or": _bitwise(lambda a, b: a or b, lambda a, b: a | b),
    "xor": _bitwise(lambda a, b: a != b, lambda a, b: a ^ b),
    "not": _un(lambda a: (not a) if isinstance(a, bool) else ~int(a)),
    "bitshift": _bin(lambda a, b: int(a) << int(b) if b >= 0 else int(a) >> int(-b)),
    "pop": lambda s: s.pop(), "exch": lambda s: s.extend((s.pop(), s.pop())), "dup": lambda s: s.append(s[-1]),
    "copy": _copy, "index": _index, "roll": _roll,
}


def _ps_program(body: bytes) -> list:
    """The nested procedures of a PostScript calculator function: numbers, operator names and lists."""
    text = re.sub(rb"%[^\r\n]*", b"", body)
    stack: list[list] = []
    for token in re.findall(rb"[{}]|[^\s{}]+", text):
        if token == b"{":
            stack.append([])
        elif token == b"}":
            if not stack:
                raise _FunctionError("braces")
            done = stack.pop()
            if not stack:
                return done
            stack[-1].append(done)
        else:
            if not stack:
                continue
            word = token.decode("latin-1")
            try:
                stack[-1].append(float(word) if re.search(r"[.eE]", word) else int(word))
            except ValueError:
                stack[-1].append(word)
    raise _FunctionError("braces")


def _ps_run(program: list, stack: list, budget: list) -> None:
    for item in program:
        budget[0] -= 1
        if budget[0] < 0 or len(stack) > 200:
            raise _FunctionError("too long")
        if isinstance(item, (int, float, list)):
            stack.append(item)
        elif item == "true":
            stack.append(True)
        elif item == "false":
            stack.append(False)
        elif item == "if":
            procedure, condition = stack.pop(), stack.pop()
            if condition:
                _ps_run(procedure, stack, budget)
        elif item == "ifelse":
            otherwise, procedure, condition = stack.pop(), stack.pop(), stack.pop()
            _ps_run(procedure if condition else otherwise, stack, budget)
        else:
            op = _PS_OPS.get(item)
            if op is None:
                raise _FunctionError(item)
            op(stack)


def _clip_values(values: Sequence[float], bounds: Optional[Sequence[float]]) -> list[float]:
    if not bounds:
        return list(values)
    return [min(max(v, bounds[2 * i]), bounds[2 * i + 1]) if 2 * i + 1 < len(bounds) else v for i, v in enumerate(values)]


def _make_function(doc: _Doc, raw: Any, depth: int = 0) -> Optional[Callable[[Sequence[float]], list[float]]]:
    """A callable for a PDF function (types 0, 2, 3, 4) or for an array of functions with one output each; None when it cannot be built."""
    if depth > 8:
        return None
    obj = doc.resolve(raw)
    if isinstance(obj, list):
        parts = [_make_function(doc, item, depth + 1) for item in obj]
        if not parts or any(part is None for part in parts):
            return None
        return lambda xs: [part(xs)[0] for part in parts]                              # type: ignore[misc]
    head = doc.dict_of(obj)
    kind = doc.resolve(head.get("FunctionType"))
    domain = doc.numbers(head.get("Domain")) or [0.0, 1.0]
    out_range = doc.numbers(head.get("Range"))
    try:
        if kind == 2:
            c0 = doc.numbers(head.get("C0")) or [0.0]
            c1 = doc.numbers(head.get("C1")) or [1.0]
            exponent = doc.number(head.get("N"), 1.0)
            count = min(len(c0), len(c1))

            def exponential(xs: Sequence[float]) -> list[float]:
                x = _clip_values(xs[:1], domain)[0]
                try:
                    power = x ** exponent
                    if isinstance(power, complex):
                        power = 0.0
                except (ZeroDivisionError, OverflowError, ValueError):
                    power = 0.0
                return _clip_values([c0[i] + power * (c1[i] - c0[i]) for i in range(count)], out_range)
            return exponential
        if kind == 3:
            functions = doc.resolve(head.get("Functions"))
            parts = [_make_function(doc, item, depth + 1) for item in functions] if isinstance(functions, list) else []
            bounds = doc.numbers(head.get("Bounds")) or []
            encode = doc.numbers(head.get("Encode")) or []
            if not parts or any(part is None for part in parts) or len(encode) < 2 * len(parts):
                return None

            def stitching(xs: Sequence[float]) -> list[float]:
                x = _clip_values(xs[:1], domain)[0]
                i = 0
                while i < len(bounds) and i < len(parts) - 1 and x >= bounds[i]:
                    i += 1
                low = domain[0] if i == 0 else bounds[i - 1]
                high = domain[1] if i >= len(bounds) else bounds[i]
                e0, e1 = encode[2 * i], encode[2 * i + 1]
                t = e0 if high == low else e0 + (x - low) * (e1 - e0) / (high - low)
                return _clip_values(parts[i]([t]), out_range)                           # type: ignore[misc]
            return stitching
        if kind == 4 and isinstance(obj, Stream):
            body = doc.stream_data(obj)
            if body is None or out_range is None:
                return None
            program = _ps_program(body)
            outputs = len(out_range) // 2

            def calculator(xs: Sequence[float]) -> list[float]:
                stack: list = list(_clip_values(xs, domain))
                _ps_run(program, stack, [100_000])
                if len(stack) < outputs:
                    raise _FunctionError("outputs")
                return _clip_values([float(v) for v in stack[-outputs:]], out_range)
            return calculator
        if kind == 0 and isinstance(obj, Stream):
            return _sampled_function(doc, obj, domain, out_range)
    except (_FunctionError, ArithmeticError, ValueError, TypeError, IndexError):
        return None
    return None


def _sampled_function(doc: _Doc, stream: Stream, domain: list[float], out_range: Optional[list[float]]):
    head = stream.head
    sizes = doc.numbers(head.get("Size"))
    bits = int(doc.number(head.get("BitsPerSample"), 8))
    if sizes is None or out_range is None or bits not in (1, 2, 4, 8, 12, 16, 24, 32) or len(sizes) > 8:
        return None
    size = [max(1, int(v)) for v in sizes]
    inputs, outputs = len(size), len(out_range) // 2
    total = int(np.prod(size, dtype=np.int64)) * outputs
    if total <= 0 or total > 2_000_000 or len(domain) < 2 * inputs:
        return None
    encode = doc.numbers(head.get("Encode")) or [v for s in size for v in (0.0, float(s - 1))]
    decode = doc.numbers(head.get("Decode")) or out_range
    body = doc.stream_data(stream)
    if body is None:
        return None
    if bits == 8:
        samples = np.frombuffer(body, np.uint8)
    elif bits == 16:
        samples = np.frombuffer(body[:len(body) // 2 * 2], ">u2")
    elif bits == 32:
        samples = np.frombuffer(body[:len(body) // 4 * 4], ">u4")
    else:
        unpacked = np.unpackbits(np.frombuffer(body, np.uint8))
        usable = len(unpacked) // bits * bits
        samples = unpacked[:usable].reshape(-1, bits).astype(np.int64) @ (1 << np.arange(bits - 1, -1, -1, dtype=np.int64))
    values = samples[:total].astype(np.float64).tolist()
    values += [0.0] * (total - len(values))
    top = float((1 << bits) - 1)

    def sampled(xs: Sequence[float]) -> list[float]:
        position: list[float] = []
        for k in range(inputs):
            low, high = domain[2 * k], domain[2 * k + 1]
            x = min(max(xs[k] if k < len(xs) else 0.0, low), high)
            e = encode[2 * k] if high == low else encode[2 * k] + (x - low) * (encode[2 * k + 1] - encode[2 * k]) / (high - low)
            position.append(min(max(e, 0.0), float(size[k] - 1)))
        base = [int(math.floor(v)) for v in position]
        fraction = [v - b for v, b in zip(position, base)]
        mixed = [0.0] * outputs
        for corner in itertools.product((0, 1), repeat=inputs):
            weight, offset, stride = 1.0, 0, 1
            for k in range(inputs):
                weight *= fraction[k] if corner[k] else 1.0 - fraction[k]
                offset += min(base[k] + corner[k], size[k] - 1) * stride
                stride *= size[k]
            if weight:
                for j in range(outputs):
                    mixed[j] += weight * values[offset * outputs + j]
        return _clip_values([decode[2 * j] + mixed[j] * (decode[2 * j + 1] - decode[2 * j]) / top for j in range(outputs)], out_range)
    return sampled


# =======================================================================================================================================
# Colour spaces
# =======================================================================================================================================
class _Space:
    """A colour space: how many components a colour has, the initial colour and the design colour (``#rrggbb``) of a colour."""
    n = 1
    initial: tuple[float, ...] = (0.0,)

    def hex(self, comps: Sequence[float]) -> Optional[str]:
        raise NotImplementedError

    def unit(self, values: Sequence[float]) -> list[float]:
        """Components given as fractions 0..1 (the palette of an indexed space) in the natural range of this space."""
        return list(values)


class _Gray(_Space):
    n, initial = 1, (0.0,)

    def hex(self, comps):
        return geo.grey(comps[0] if comps else 0.0)


class _Rgb(_Space):
    n, initial = 3, (0.0, 0.0, 0.0)

    def hex(self, comps):
        c = list(comps) + [0.0] * (3 - len(comps))
        return geo.hex_colour(c[0], c[1], c[2], scale=1.0)


class _Cmyk(_Space):
    n, initial = 4, (0.0, 0.0, 0.0, 1.0)

    def hex(self, comps):
        c = list(comps) + [0.0] * (4 - len(comps))
        return geo.cmyk(c[0], c[1], c[2], c[3])


class _Lab(_Space):
    n, initial = 3, (0.0, 0.0, 0.0)

    def __init__(self, white: Sequence[float], ranges: Sequence[float]):
        self.white = "D50" if abs(white[0] - 0.9642) < abs(white[0] - 0.9505) else "D65"
        self.ranges = list(ranges)

    def hex(self, comps):
        c = list(comps) + [0.0] * (3 - len(comps))
        rgb = linear_to_srgb(lab_under_to_linear_rgb(np.array(c[:3], dtype=np.float64), self.white))
        return geo.hex_colour(float(rgb[0]), float(rgb[1]), float(rgb[2]), scale=1.0)

    def unit(self, values):
        r = self.ranges
        v = list(values) + [0.0] * (3 - len(values))
        return [v[0] * 100.0, r[0] + v[1] * (r[1] - r[0]), r[2] + v[2] * (r[3] - r[2])]


class _Indexed(_Space):
    n, initial = 1, (0.0,)

    def __init__(self, base: _Space, hival: int, table: bytes):
        self.base, self.hival, self.table = base, max(0, hival), table
        self._colours: dict[int, Optional[str]] = {}

    def hex(self, comps):
        index = max(0, min(self.hival, int(round(comps[0] if comps else 0.0))))
        if index not in self._colours:
            k = self.base.n
            chunk = self.table[index * k:(index + 1) * k]
            if len(chunk) < k:
                chunk = chunk + bytes(k - len(chunk))
            self._colours[index] = self.base.hex(self.base.unit([b / 255.0 for b in chunk]))
        return self._colours[index]


class _Tint(_Space):
    """Separation and DeviceN: the tint transform maps the tints to the alternate space. When the function cannot be evaluated the colour is
    a grey that gets darker with the tint, and the colour is counted (the sink) so that the operator hears of it."""

    def __init__(self, n: int, alternate: _Space, function: Optional[Callable], paints: bool, key: Any, sink: Callable[[Any], None]):
        self.n, self.alternate, self.function, self.paints, self.key, self.sink = n, alternate, function, paints, key, sink
        self.initial = (1.0,) * n
        self._colours: dict[tuple, str] = {}
        self._fell_back: set[tuple] = set()

    def hex(self, comps):
        if not self.paints:
            return None
        tints = tuple(round(v, 4) for v in list(comps) + [0.0] * (self.n - len(comps)))
        if tints not in self._colours:
            colour = None
            if self.function is not None:
                try:
                    colour = self.alternate.hex(self.function(list(tints)))
                except (_FunctionError, ArithmeticError, ValueError, TypeError, IndexError):
                    colour = None
            if colour is None:
                self._fell_back.add(tints)
                colour = geo.grey(1.0 - max(tints or (0.0,)))
            self._colours[tints] = colour
        if tints in self._fell_back:
            self.sink((self.key, tints))
        return self._colours[tints]


class _Pattern(_Space):
    n, initial = 0, ()

    def hex(self, comps):
        return None


GRAY, RGB, CMYK, PATTERN = _Gray(), _Rgb(), _Cmyk(), _Pattern()
_DEVICE_SPACES = {"DeviceGray": GRAY, "G": GRAY, "CalGray": GRAY, "DeviceRGB": RGB, "RGB": RGB, "CalRGB": RGB, "DeviceCMYK": CMYK,
                  "CMYK": CMYK, "Pattern": PATTERN}
_BY_COMPONENTS = {1: GRAY, 3: RGB, 4: CMYK}


class _Gradient(str):
    """The colour of a shading pattern (its average): painted like a colour, counted as a gradient."""
    __slots__ = ()


class _TilingPattern:
    """Marks a tiling pattern: whatever is painted with it is left out."""


TILING = _TilingPattern()


# =======================================================================================================================================
# Graphics state and clipping
# =======================================================================================================================================
Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mul(a: Sequence[float], b: Sequence[float]) -> Matrix:
    """The matrix that applies ``a`` and then ``b`` (row-vector convention of PDF)."""
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3], a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5])


def _page_matrix(media: Sequence[float], rotate: int, unit: float) -> Matrix:
    """User space of the page to millimetres with y down and the origin at the top-left of the page as it is shown."""
    left, bottom, right, top = media
    s = MM_PER_PT * unit
    parts = {0: (1, 0, 0, -1, -left, top), 90: (0, 1, 1, 0, -bottom, -left), 180: (-1, 0, 0, 1, right, -bottom),
             270: (0, -1, -1, 0, top, right)}[rotate]
    return (parts[0] * s, parts[1] * s, parts[2] * s, parts[3] * s, parts[4] * s, parts[5] * s)


def _rect_bounds(geometry) -> Optional[tuple[float, float, float, float]]:
    """The bounds of a geometry that is an upright rectangle, else None."""
    if not isinstance(geometry, Polygon) or geometry.interiors:
        return None
    coords = list(geometry.exterior.coords)
    if len(coords) != 5:
        return None
    for (ax, ay), (bx, by) in zip(coords, coords[1:]):
        if abs(ax - bx) > 1e-7 and abs(ay - by) > 1e-7:
            return None
    return geometry.bounds


class _Clip:
    """The clipping path: a rectangle (the usual artboard clip, cheap to apply) or any area; ``empty`` hides everything."""
    __slots__ = ("geom", "bounds", "rect", "empty")

    def __init__(self, geom, bounds, rect: bool, empty: bool = False):
        self.geom, self.bounds, self.rect, self.empty = geom, bounds, rect, empty

    @staticmethod
    def of(geom) -> "_Clip":
        if geom is None or geom.is_empty:
            return _Clip(Polygon(), (0.0, 0.0, 0.0, 0.0), True, True)
        rect = _rect_bounds(geom)
        if rect is not None:
            return _Clip(geom, rect, True)
        if len(shapely.get_coordinates(geom)) > 12:
            shapely.prepare(geom)
        return _Clip(geom, geom.bounds, False)

    def intersect(self, other: "_Clip") -> "_Clip":
        if self.empty or other.empty:
            return _Clip.of(None)
        if self.rect and other.rect:
            x0, y0 = max(self.bounds[0], other.bounds[0]), max(self.bounds[1], other.bounds[1])
            x1, y1 = min(self.bounds[2], other.bounds[2]), min(self.bounds[3], other.bounds[3])
            return _Clip.of(None) if x0 >= x1 or y0 >= y1 else _Clip.of(box(x0, y0, x1, y1))
        try:
            return _Clip.of(geo.polygonal(self.geom.intersection(other.geom)))
        except shapely.errors.ShapelyError:
            return _Clip.of(geo.polygonal(shapely.make_valid(self.geom).intersection(shapely.make_valid(other.geom))))

    def apply(self, geom):
        """The part of ``geom`` inside the clip (``geom`` itself when all of it is inside)."""
        if self.empty:
            return Polygon()
        gx0, gy0, gx1, gy1 = geom.bounds
        cx0, cy0, cx1, cy1 = self.bounds
        if gx0 >= cx1 or gx1 <= cx0 or gy0 >= cy1 or gy1 <= cy0:
            return Polygon()
        inside = gx0 >= cx0 - 1e-9 and gy0 >= cy0 - 1e-9 and gx1 <= cx1 + 1e-9 and gy1 <= cy1 + 1e-9
        if self.rect:
            return geom if inside else shapely.clip_by_rect(geom, cx0, cy0, cx1, cy1)
        try:
            if inside and self.geom.contains(geom):
                return geom
            if not self.geom.intersects(geom):
                return Polygon()
            return geom.intersection(self.geom)
        except shapely.errors.ShapelyError:
            try:
                return shapely.make_valid(geom).intersection(shapely.make_valid(self.geom))
            except shapely.errors.ShapelyError:
                return geom


class _GState:
    __slots__ = ("ctm", "fill", "stroke", "fill_space", "stroke_space", "fill_alpha", "stroke_alpha", "group_alpha", "width", "cap", "join",
                 "miter", "dashed", "clip")

    def __init__(self, ctm: Matrix):
        self.ctm = ctm
        self.fill: Any = "#000000"
        self.stroke: Any = "#000000"
        self.fill_space: _Space = GRAY
        self.stroke_space: _Space = GRAY
        self.fill_alpha = self.stroke_alpha = self.group_alpha = 1.0
        self.width = 1.0
        self.cap, self.join, self.miter = "butt", "miter", 10.0
        self.dashed = False
        self.clip: Optional[_Clip] = None

    def copy(self) -> "_GState":
        other = _GState.__new__(_GState)
        other.ctm, other.fill, other.stroke = self.ctm, self.fill, self.stroke
        other.fill_space, other.stroke_space = self.fill_space, self.stroke_space
        other.fill_alpha, other.stroke_alpha, other.group_alpha = self.fill_alpha, self.stroke_alpha, self.group_alpha
        other.width, other.cap, other.join, other.miter = self.width, self.cap, self.join, self.miter
        other.dashed, other.clip = self.dashed, self.clip
        return other


# =======================================================================================================================================
# The content interpreter
# =======================================================================================================================================
_NUMBER = rb"[+-]?(?:\d+\.?\d*|\.\d+)"
# A run of numbers and the operator after it are matched as one token (most operators are numbers and a word); the run is bounded so that a
# long array of numbers is not scanned again from every number in it. A longer run comes as single numbers and the last ones with the word.
_CONTENT = re.compile(
    rb"((?:" + _NUMBER + rb"[\x00\t\n\x0c\r ]+){0,8}+)([A-Za-z'\"][A-Za-z0-9*'\"]*)"                      # 1 numbers, 2 operator
    rb"|(" + _NUMBER + rb")"                                                                                # 3 a number
    rb"|(/" + _REGULAR + rb"*)"                                                                             # 4 a name
    rb"|(\((?:[^()\\]++|\\[\s\S]|\((?:[^()\\]++|\\[\s\S]|\([^()\\]*+\))*+\))*+\))"                        # 5 a string
    rb"|(<<)|(>>)"                                                                                          # 6, 7
    rb"|(<[0-9A-Fa-f\x00\t\n\x0c\r ]*>)"                                                                    # 8 a hexadecimal string
    rb"|([\[\]])"                                                                                           # 9
    rb"|%[^\r\n]*")
_INLINE_DATA = re.compile(rb"[\x00\t\n\x0c\r ]ID[\x00\t\n\x0c\r ]")
_INLINE_END = re.compile(rb"[\x00\t\n\x0c\r ]EI(?!" + _REGULAR + rb")")
_CAPS = {0: "butt", 1: "round", 2: "square"}
_JOINS = {0: "miter", 1: "round", 2: "bevel"}


def _sane(rings: list) -> bool:
    for points, _ in rings:
        for x, y in points:
            if not (-MAX_COORDINATE_MM < x < MAX_COORDINATE_MM and -MAX_COORDINATE_MM < y < MAX_COORDINATE_MM):
                return False
    return True


class _Interpreter:
    def __init__(self, doc: _Doc, layers: _Layers, base: Matrix):
        self.doc, self.layers = doc, layers
        self.shapes: list[Shape] = []
        self.pictures = self.texts = self.dashes = self.gradients = self.tilings = 0
        self.masks: set = set()
        self.fallbacks: set = set()
        self.vertices = 0
        self.deadline = time.monotonic() + MAX_SECONDS
        self.gs = _GState(base)
        self.stack: list[_GState] = []
        self.stack_base = 0
        self.res: dict = {}
        self.rings: list[tuple[list, bool]] = []
        self.current: Optional[list] = None
        self.pending_clip: Optional[str] = None
        self.hidden = 0
        self.layer_name: Optional[str] = None
        self.marked: list[tuple[bool, Optional[str]]] = []
        self.marked_base = 0
        self.active_forms: list[int] = []
        self._forms: dict[int, tuple[Stream, bytes]] = {}
        self._forms_bytes = 0
        self._spaces: dict[Any, tuple[Any, _Space]] = {}
        self._averages: dict[int, str] = {}
        self._ops: dict[bytes, Callable[[list], None]] = {
            b"q": self._q, b"Q": self._Q, b"cm": self._cm, b"w": self._w, b"J": self._J, b"j": self._j, b"M": self._M, b"d": self._d,
            b"gs": self._gs, b"m": self._m, b"l": self._l, b"c": self._c, b"v": self._v, b"y": self._y, b"h": self._h, b"re": self._re,
            b"S": lambda a: self._paint(False, True, "nonzero", False), b"s": lambda a: self._paint(False, True, "nonzero", True),
            b"f": lambda a: self._paint(True, False, "nonzero", False), b"F": lambda a: self._paint(True, False, "nonzero", False),
            b"f*": lambda a: self._paint(True, False, "evenodd", False), b"B": lambda a: self._paint(True, True, "nonzero", False),
            b"B*": lambda a: self._paint(True, True, "evenodd", False), b"b": lambda a: self._paint(True, True, "nonzero", True),
            b"b*": lambda a: self._paint(True, True, "evenodd", True), b"n": lambda a: self._paint(False, False, "nonzero", False),
            b"W": lambda a: setattr(self, "pending_clip", "nonzero"), b"W*": lambda a: setattr(self, "pending_clip", "evenodd"),
            b"g": lambda a: self._device(a, GRAY, False), b"G": lambda a: self._device(a, GRAY, True),
            b"rg": lambda a: self._device(a, RGB, False), b"RG": lambda a: self._device(a, RGB, True),
            b"k": lambda a: self._device(a, CMYK, False), b"K": lambda a: self._device(a, CMYK, True),
            b"cs": lambda a: self._cs(a, False), b"CS": lambda a: self._cs(a, True),
            b"sc": lambda a: self._sc(a, False), b"scn": lambda a: self._sc(a, False),
            b"SC": lambda a: self._sc(a, True), b"SCN": lambda a: self._sc(a, True),
            b"Do": self._do, b"sh": self._sh, b"BT": self._bt, b"BDC": self._bdc, b"BMC": self._bmc, b"EMC": self._emc,
        }
        # inside a hidden layer nothing is drawn or counted, but the graphics state and the marked-content nesting are kept: what a layer
        # sets without q/Q is still in force after it
        state = (b"q", b"Q", b"cm", b"w", b"J", b"j", b"M", b"d", b"gs", b"g", b"G", b"rg", b"RG", b"k", b"K", b"cs", b"CS", b"sc", b"scn",
                 b"SC", b"SCN", b"BDC", b"BMC", b"EMC")
        self._hidden_ops: dict[bytes, Callable[[list], None]] = {name: self._ops[name] for name in state}

    # -- driving -------------------------------------------------------------------------------------------------------------------------
    def run(self, content: bytes, resources: dict) -> None:
        outer = (self.res, self.stack_base, self.marked_base)
        self.res, self.stack_base, self.marked_base = resources, len(self.stack), len(self.marked)
        try:
            self._loop(content)
        finally:
            while len(self.marked) > self.marked_base:
                self._emc([])
            del self.stack[self.stack_base:]
            self.res, self.stack_base, self.marked_base = outer

    def _loop(self, content: bytes) -> None:
        operands: list = []
        containers: list[tuple[str, list]] = []
        pos, ticks = 0, 0
        while True:
            jump = -1
            for m in _CONTENT.finditer(content, pos):
                kind = m.lastindex
                if kind == 2:
                    ticks += 1
                    if not ticks & 0x3FFF and time.monotonic() > self.deadline:
                        raise _Abort("time")
                    numbers = m.group(1)
                    if numbers:
                        try:
                            values = [float(v) for v in numbers.split()]
                        except ValueError:
                            operands = []
                            continue
                        if operands:
                            operands.extend(values)
                        else:
                            operands = values
                    op = m.group(2)
                    if containers:
                        containers, operands = [], []
                        continue
                    handler = (self._hidden_ops if self.hidden else self._ops).get(op)
                    if handler is not None:
                        try:
                            handler(operands)
                        except (_Abort, ValidationError):
                            raise
                        except Exception:                               # a malformed operand: the operator is skipped
                            self.rings, self.current, self.pending_clip = [], None, None
                    elif op == b"BI":
                        jump = self._inline_image_end(content, m.end())
                        break
                    elif op == b"true" or op == b"false":
                        operands.append(op == b"true")
                        continue
                    elif op == b"null":
                        operands.append(None)
                        continue
                    operands = []
                elif kind == 3:
                    (containers[-1][1] if containers else operands).append(float(m.group(3)))
                elif kind == 4:
                    (containers[-1][1] if containers else operands).append(Name(_name(m.group(4))))
                elif kind == 9:
                    if m.group(9) == b"[":
                        containers.append(("a", []))
                    elif containers and containers[-1][0] == "a":
                        done = containers.pop()[1]
                        (containers[-1][1] if containers else operands).append(done)
                elif kind == 6:
                    containers.append(("d", []))
                elif kind == 7:
                    if containers and containers[-1][0] == "d":
                        items = containers.pop()[1]
                        entries = {items[i]: items[i + 1] for i in range(0, len(items) - 1, 2) if isinstance(items[i], Name)}
                        (containers[-1][1] if containers else operands).append(entries)
                elif kind == 5 or kind == 8:
                    (containers[-1][1] if containers else operands).append(m.group(kind))
            if jump < 0:
                return
            pos = jump
            operands, containers = [], []

    def _inline_image_end(self, content: bytes, pos: int) -> int:
        """The position after an inline image that starts at ``pos`` (after ``BI``), or the end of the content when it is cut short."""
        if not self.hidden:
            self.pictures += 1
        data = _INLINE_DATA.search(content, pos)
        if data is None:
            return len(content)
        for end in _INLINE_END.finditer(content, data.end()):
            if content[end.end():end.end() + 12].isascii():
                return end.end()
        return len(content)

    # -- graphics state ----------------------------------------------------------------------------------------------------------------
    def _q(self, a: list) -> None:
        self.stack.append(self.gs)
        self.gs = self.gs.copy()

    def _Q(self, a: list) -> None:
        if len(self.stack) > self.stack_base:
            self.gs = self.stack.pop()

    def _cm(self, a: list) -> None:
        if len(a) >= 6:
            self.gs.ctm = _mul(a[-6:], self.gs.ctm)

    def _w(self, a: list) -> None:
        if a:
            self.gs.width = abs(a[-1])

    def _J(self, a: list) -> None:
        if a:
            self.gs.cap = _CAPS.get(int(a[-1]), "butt")

    def _j(self, a: list) -> None:
        if a:
            self.gs.join = _JOINS.get(int(a[-1]), "miter")

    def _M(self, a: list) -> None:
        if a:
            self.gs.miter = max(1.0, a[-1])

    def _d(self, a: list) -> None:
        if len(a) >= 2 and isinstance(a[-2], list):
            self.gs.dashed = any(isinstance(v, float) and v > 0 for v in a[-2])

    def _lookup(self, category: str, name: Any, raw: bool = False) -> Any:
        table = self.doc.dict_of(self.res.get(category))
        found = table.get(name)
        return found if raw else self.doc.resolve(found)

    def _gs(self, a: list) -> None:
        if not a or not isinstance(a[-1], Name):
            return
        state = self.doc.dict_of(self._lookup("ExtGState", a[-1]))
        gs, doc = self.gs, self.doc
        for key, value in state.items():
            value = doc.resolve(value)
            if key == "LW" and isinstance(value, (int, float)):
                gs.width = abs(float(value))
            elif key == "LC" and isinstance(value, int):
                gs.cap = _CAPS.get(value, "butt")
            elif key == "LJ" and isinstance(value, int):
                gs.join = _JOINS.get(value, "miter")
            elif key == "ML" and isinstance(value, (int, float)):
                gs.miter = max(1.0, float(value))
            elif key == "D" and isinstance(value, list) and value:
                dashes = doc.resolve(value[0])
                gs.dashed = isinstance(dashes, list) and any(isinstance(doc.resolve(v), (int, float)) and doc.resolve(v) > 0 for v in dashes)
            elif key == "CA" and isinstance(value, (int, float)):
                gs.stroke_alpha = max(0.0, min(1.0, float(value)))
            elif key == "ca" and isinstance(value, (int, float)):
                gs.fill_alpha = max(0.0, min(1.0, float(value)))
            elif key == "SMask" and value is not None and str(value) != "None" and not self.hidden:
                raw = state.get("SMask")
                self.masks.add(raw.num if isinstance(raw, Ref) else id(value))

    # -- colour --------------------------------------------------------------------------------------------------------------------------
    def _device(self, a: list, space: _Space, stroking: bool) -> None:
        if len(a) < space.n:
            return
        colour = space.hex(a[-space.n:])
        if stroking:
            self.gs.stroke_space, self.gs.stroke = space, colour
        else:
            self.gs.fill_space, self.gs.fill = space, colour

    def _fallback(self, item: Any) -> None:
        if not self.hidden:
            self.fallbacks.add(item)

    def _space(self, raw: Any, depth: int = 0) -> _Space:
        doc = self.doc
        if depth > 8:
            return GRAY
        if isinstance(raw, Name):
            device = _DEVICE_SPACES.get(str(raw))
            if device is not None:
                return device
            found = doc.dict_of(self.res.get("ColorSpace")).get(raw)
            return self._space(found, depth + 1) if found is not None else GRAY
        key = raw.num if isinstance(raw, Ref) else None
        obj = doc.resolve(raw)
        if isinstance(obj, Name):
            return self._space(obj, depth + 1)
        if not isinstance(obj, list) or not obj:
            return GRAY
        if key is None:
            key = id(obj)
        cached = self._spaces.get(key)
        if cached is not None and cached[0] is obj:
            return cached[1]
        space = self._array_space(obj, key, depth)
        self._spaces[key] = (obj, space)
        return space

    def _array_space(self, arr: list, key: Any, depth: int) -> _Space:
        doc = self.doc
        family = str(doc.resolve(arr[0]))
        if family in _DEVICE_SPACES and family != "Pattern":
            return _DEVICE_SPACES[family]
        if family == "Pattern":
            return PATTERN
        if family == "ICCBased" and len(arr) > 1:
            n = doc.resolve(doc.dict_of(arr[1]).get("N"))
            return _BY_COMPONENTS.get(n if isinstance(n, int) else 3, RGB)
        if family == "Lab" and len(arr) > 1:
            head = doc.dict_of(arr[1])
            return _Lab(doc.numbers(head.get("WhitePoint"), 3) or [0.9505, 1.0, 1.089], doc.numbers(head.get("Range"), 4) or [-100, 100, -100, 100])
        if family in ("Indexed", "I") and len(arr) >= 4:
            lookup = doc.resolve(arr[3])
            table = doc.stream_data(lookup) if isinstance(lookup, Stream) else lookup if isinstance(lookup, bytes) else b""
            return _Indexed(self._space(arr[1], depth + 1), int(doc.number(arr[2], 255)), table or b"")
        if family in ("Separation", "DeviceN") and len(arr) >= 4:
            names = doc.resolve(arr[1])
            n = len(names) if family == "DeviceN" and isinstance(names, list) else 1
            if family == "DeviceN":
                paints = not (isinstance(names, list) and names and all(str(doc.resolve(v)) == "None" for v in names))
            else:
                paints = str(names) != "None"
            return _Tint(n, self._space(arr[2], depth + 1), _make_function(doc, arr[3]), paints, key, self._fallback)
        return GRAY

    def _cs(self, a: list, stroking: bool) -> None:
        if not a:
            return
        space = self._space(a[-1])
        colour = space.hex(space.initial) if space.n else None
        if space is PATTERN:
            colour = None
        if stroking:
            self.gs.stroke_space, self.gs.stroke = space, colour
        else:
            self.gs.fill_space, self.gs.fill = space, colour

    def _sc(self, a: list, stroking: bool) -> None:
        gs = self.gs
        space = gs.stroke_space if stroking else gs.fill_space
        if space is PATTERN:
            colour: Any = None
            if a and isinstance(a[-1], Name):
                colour = self._pattern(a[-1])
        else:
            comps = [v for v in a if isinstance(v, float)]
            colour = space.hex(comps[-space.n:] if space.n and len(comps) >= space.n else comps)
        if stroking:
            gs.stroke = colour
        else:
            gs.fill = colour

    def _pattern(self, name: Name) -> Any:
        doc = self.doc
        raw = doc.dict_of(self.res.get("Pattern")).get(name)
        pattern = doc.resolve(raw)
        head = doc.dict_of(pattern)
        if doc.resolve(head.get("PatternType")) == 2:
            return _Gradient(self._shading_colour(head.get("Shading")))
        return TILING

    def _shading_colour(self, raw: Any) -> str:
        """The average colour of a shading (axial, radial or function based; the meshes give a middle grey)."""
        doc = self.doc
        key = raw.num if isinstance(raw, Ref) else id(doc.resolve(raw))
        if key in self._averages:
            return self._averages[key]
        head = doc.dict_of(raw)
        colour = "#808080"
        kind = doc.resolve(head.get("ShadingType"))
        function = _make_function(doc, head.get("Function")) if head.get("Function") is not None else None
        if function is not None and kind in (1, 2, 3):
            space = self._space(head.get("ColorSpace"))
            if kind == 1:
                domain = doc.numbers(head.get("Domain")) or [0.0, 1.0, 0.0, 1.0]
                points = [[domain[0] + (domain[1] - domain[0]) * i / 2.0, domain[2] + (domain[3] - domain[2]) * j / 2.0]
                          for i in range(3) for j in range(3)]
            else:
                domain = doc.numbers(head.get("Domain")) or [0.0, 1.0]
                points = [[domain[0] + (domain[1] - domain[0]) * i / 8.0] for i in range(9)]
            channels = []
            for point in points:
                try:
                    hexed = space.hex(function(point))
                except (_FunctionError, ArithmeticError, ValueError, TypeError, IndexError):
                    hexed = None
                if hexed:
                    channels.append(geo.rgb_of(hexed))
            if channels:
                mean = np.mean(np.array(channels, dtype=np.float64), axis=0)
                colour = geo.hex_colour(float(mean[0]), float(mean[1]), float(mean[2]))
        self._averages[key] = colour
        return colour

    # -- paths ---------------------------------------------------------------------------------------------------------------------------
    def _point(self, x: float, y: float) -> tuple[float, float]:
        a, b, c, d, e, f = self.gs.ctm
        return (a * x + c * y + e, b * x + d * y + f)

    def _end_subpath(self, closed: bool) -> None:
        if self.current is not None and len(self.current) >= 2:
            self.rings.append((self.current, closed))
        self.current = None

    def _m(self, a: list) -> None:
        if len(a) >= 2 and not self.hidden:
            self._end_subpath(False)
            self.current = [self._point(a[-2], a[-1])]

    def _l(self, a: list) -> None:
        if len(a) >= 2 and not self.hidden:
            point = self._point(a[-2], a[-1])
            if self.current is None:
                self.current = [point]
            else:
                self.current.append(point)

    def _curve(self, control1: Optional[tuple], control2: Optional[tuple], end: tuple) -> None:
        if self.current is None:
            self.current = [end]
            return
        start = self.current[-1]
        self.current.extend(geo.cubic(start, start if control1 is None else control1, end if control2 is None else control2, end))

    def _c(self, a: list) -> None:
        if len(a) >= 6 and not self.hidden:
            self._curve(self._point(a[-6], a[-5]), self._point(a[-4], a[-3]), self._point(a[-2], a[-1]))

    def _v(self, a: list) -> None:
        if len(a) >= 4 and not self.hidden:
            self._curve(None, self._point(a[-4], a[-3]), self._point(a[-2], a[-1]))

    def _y(self, a: list) -> None:
        if len(a) >= 4 and not self.hidden:
            self._curve(self._point(a[-4], a[-3]), None, self._point(a[-2], a[-1]))

    def _h(self, a: list) -> None:
        if self.current is not None and not self.hidden:
            start = self.current[0]
            self._end_subpath(True)
            self.current = [start]

    def _re(self, a: list) -> None:
        if len(a) >= 4 and not self.hidden:
            x, y, w, h = a[-4:]
            self._end_subpath(False)
            self.rings.append(([self._point(x, y), self._point(x + w, y), self._point(x + w, y + h), self._point(x, y + h)], True))
            self.current = [self._point(x, y)]

    # -- painting ------------------------------------------------------------------------------------------------------------------------
    def _paint(self, fill: bool, stroke: bool, rule: str, close: bool) -> None:
        if self.hidden:
            return
        self._end_subpath(close)
        rings, self.rings = self.rings, []
        clip_rule, self.pending_clip = self.pending_clip, None
        if not rings or not _sane(rings):
            return
        self.vertices += sum(len(points) for points, _ in rings)
        if self.vertices > MAX_VERTICES:
            raise _Abort("vertices")
        if fill:
            self._fill(rings, rule)
        if stroke:
            self._stroke(rings)
        if clip_rule:
            area = geo.region([points for points, _ in rings], clip_rule)
            clip = _Clip.of(area)
            self.gs.clip = clip if self.gs.clip is None else self.gs.clip.intersect(clip)

    def _colour(self, value: Any, alpha: float) -> Optional[str]:
        """The design colour to paint with, or None when nothing is painted (a spot colour "None", a pattern that cannot be imported)."""
        if value is None:
            return None
        if value is TILING:
            self.tilings += 1
            return None
        if alpha <= 0.0:
            return None
        if type(value) is _Gradient:
            self.gradients += 1
        return geo.on_white(str(value), alpha) if alpha < 1.0 else str(value)

    def _fill(self, rings: list, rule: str) -> None:
        gs = self.gs
        colour = self._colour(gs.fill, gs.fill_alpha * gs.group_alpha)
        if colour is not None:
            self._emit(geo.region([points for points, _ in rings], rule), colour)

    def _stroke(self, rings: list) -> None:
        gs = self.gs
        colour = self._colour(gs.stroke, gs.stroke_alpha * gs.group_alpha)
        if colour is None:
            return
        if gs.dashed:
            self.dashes += 1
        a, b, c, d = gs.ctm[:4]
        width = gs.width * math.sqrt(abs(a * d - b * c))
        width = width if gs.width > 0 else MIN_STROKE_MM
        parts = [geo.stroke(points, width, closed=closed, cap=gs.cap, join=gs.join, miter_limit=gs.miter) for points, closed in rings
                 if len(points) >= 2]
        parts = [p for p in parts if not p.is_empty]
        if parts:
            self._emit(parts[0] if len(parts) == 1 else geo.polygonal(shapely.union_all(parts)), colour)

    def _emit(self, geom, colour: str, clipped: bool = False) -> None:
        if geom is None or geom.is_empty:
            return
        clip = self.gs.clip
        if clip is not None and not clipped:
            result = clip.apply(geom)
            geom = result if result is geom else geo.polygonal(result)
            if geom.is_empty:
                return
        if not all(math.isfinite(v) for v in geom.bounds):
            return
        self.shapes.append(Shape(geom, colour, self.layer_name))
        if len(self.shapes) > MAX_SHAPES:
            raise _Abort("shapes")

    def _sh(self, a: list) -> None:
        if self.hidden or not a or not isinstance(a[-1], Name):
            return
        shading = self._lookup("Shading", a[-1], raw=True)
        if shading is None:
            return
        colour = _Gradient(self._shading_colour(shading))
        self.gradients += 1
        clip = self.gs.clip
        alpha = self.gs.fill_alpha * self.gs.group_alpha
        if clip is not None and not clip.empty and alpha > 0.0:
            self._emit(clip.geom, geo.on_white(str(colour), alpha) if alpha < 1.0 else str(colour), clipped=True)

    # -- text, marked content, XObjects ----------------------------------------------------------------------------------------------------
    def _bt(self, a: list) -> None:
        self.texts += 1

    def _bmc(self, a: list) -> None:
        self.marked.append((False, self.layer_name))

    def _bdc(self, a: list) -> None:
        entry = (False, self.layer_name)
        if len(a) >= 2 and a[-2] == "OC" and not self.hidden:
            properties = a[-1]
            if isinstance(properties, Name):
                properties = self.doc.dict_of(self.res.get("Properties")).get(properties)
            shown, name = self.layers.status(properties)
            if not shown:
                self.hidden += 1
                entry = (True, self.layer_name)
            elif name:
                self.layer_name = name
        self.marked.append(entry)

    def _emc(self, a: list) -> None:
        if len(self.marked) > self.marked_base:
            hid, name = self.marked.pop()
            if hid:
                self.hidden -= 1
            self.layer_name = name

    def _do(self, a: list) -> None:
        if not a or not isinstance(a[-1], Name):
            return
        xobject = self._lookup("XObject", a[-1])
        if not isinstance(xobject, Stream):
            return
        head = xobject.head
        if "OC" in head and not self.layers.status(head["OC"])[0]:
            return
        subtype = self.doc.resolve(head.get("Subtype"))
        if subtype == "Image":
            self.pictures += 1
        elif subtype == "Form":
            self._form(xobject)

    def _form_content(self, form: Stream) -> Optional[bytes]:
        """The decoded content of a form; a small one is kept, since the same symbol is often drawn many times."""
        kept = self._forms.get(id(form))
        if kept is not None:
            return kept[1]
        content = self.doc.stream_data(form)
        if content is not None and len(content) <= FORM_CACHE_ITEM_BYTES and self._forms_bytes + len(content) <= FORM_CACHE_BYTES:
            self._forms[id(form)] = (form, content)
            self._forms_bytes += len(content)
        return content

    def _form(self, form: Stream) -> None:
        doc = self.doc
        if len(self.active_forms) >= MAX_FORM_DEPTH or id(form) in self.active_forms:
            return
        head = form.head
        content = self._form_content(form)
        if not content:
            return
        resources = doc.resolve(head.get("Resources"))
        resources = resources if isinstance(resources, dict) else self.res
        matrix = doc.numbers(head.get("Matrix"), 6)
        box_ = doc.numbers(head.get("BBox"), 4)
        saved_gs, saved_path = self.gs, (self.rings, self.current, self.pending_clip)
        gs = saved_gs.copy()
        if matrix is not None:
            gs.ctm = _mul(matrix, gs.ctm)
        if "Group" in head:                                             # a transparency group: its opacity is the one it is painted with
            gs.group_alpha *= gs.fill_alpha
            gs.fill_alpha = gs.stroke_alpha = 1.0
        if box_ is not None:
            x0, y0, x1, y1 = box_
            self.gs = gs
            corners = [self._point(x0, y0), self._point(x1, y0), self._point(x1, y1), self._point(x0, y1)]
            clip = _Clip.of(geo.polygonal(Polygon(corners)))
            gs.clip = clip if gs.clip is None else gs.clip.intersect(clip)
        self.gs = gs
        self.rings, self.current, self.pending_clip = [], None, None
        self.active_forms.append(id(form))
        try:
            self.run(content, resources)
        finally:
            self.active_forms.pop()
            self.gs = saved_gs
            self.rings, self.current, self.pending_clip = saved_path


# =======================================================================================================================================
# The entry point
# =======================================================================================================================================
def _count_note(count: int, singular: str, plural: str) -> list[str]:
    return [(singular if count == 1 else plural).format(n=count)] if count else []


def _media_box(doc: _Doc, page: dict) -> tuple[float, float, float, float]:
    numbers = doc.numbers(page.get("MediaBox"), 4)
    if numbers is None or not all(math.isfinite(v) for v in numbers):
        numbers = [0.0, 0.0, 612.0, 792.0]
    left, right = sorted((numbers[0], numbers[2]))
    bottom, top = sorted((numbers[1], numbers[3]))
    if right - left <= 0 or top - bottom <= 0:
        raise _PdfError("empty page")
    return left, bottom, right, top


def _read(data: bytes) -> Parsed:
    start = data.find(b"%PDF-", 0, 1024)
    if start < 0:
        if data[:1024].lstrip().startswith(b"%!PS-Adobe"):
            raise ValidationError(PS_ONLY)
        raise ValidationError(NOT_ILLUSTRATOR)
    doc = _Doc(data[start:] if start else data)
    try:
        page, total = doc.first_page()
    except _NoPage:
        raise ValidationError(NO_PAGE) from None
    media = _media_box(doc, page)
    rotate = int(doc.number(page.get("Rotate"), 0.0)) % 360
    rotate = rotate if rotate in (0, 90, 180, 270) else 0
    unit = doc.number(page.get("UserUnit"), 1.0)
    unit = unit if 0 < unit < 1e4 else 1.0
    interpreter = _Interpreter(doc, _Layers(doc), _page_matrix(media, rotate, unit))
    contents = doc.resolve(page.get("Contents"))
    parts = contents if isinstance(contents, list) else [contents]
    chunks = []
    for part in parts:
        part = doc.resolve(part)
        decoded = doc.stream_data(part) if isinstance(part, Stream) else None
        if decoded:
            chunks.append(decoded)
    resources = doc.resolve(page.get("Resources"))
    if chunks:
        interpreter.run(b"\n".join(chunks), resources if isinstance(resources, dict) else {})
    notes: list[str] = []
    if total > 1:
        notes.append("Only the first artboard was imported.")
    notes += _count_note(interpreter.pictures, "{n} picture inside the file was not imported.",
                         "{n} pictures inside the file were not imported.")
    notes += _count_note(interpreter.texts, "{n} text object was not imported: create outlines of the text in Illustrator and save again.",
                         "{n} text objects were not imported: create outlines of the text in Illustrator and save again.")
    notes += _count_note(interpreter.tilings, "{n} pattern fill was not imported.", "{n} pattern fills were not imported.")
    notes += _count_note(interpreter.gradients, "{n} gradient fill was replaced by its average colour.",
                         "{n} gradient fills were replaced by their average colour.")
    notes += _count_note(len(interpreter.masks), "{n} soft mask (transparency gradient) was ignored.",
                         "{n} soft masks (transparency gradients) were ignored.")
    notes += _count_note(interpreter.dashes, "{n} dashed line was drawn solid.", "{n} dashed lines were drawn solid.")
    notes += _count_note(len(interpreter.fallbacks), "{n} colour could not be converted exactly and was replaced by a grey.",
                         "{n} colours could not be converted exactly and were replaced by greys.")
    return Parsed(interpreter.shapes, notes, "ai")


def parse(data: bytes) -> Parsed:
    """The artwork of an Illustrator file (saved PDF-compatible) as shapes in millimetres, y down, origin at the top-left of the page, in
    painting order (the first shape is the bottom one), with notes for the operator about what could not be carried over. Raises
    :class:`ValidationError` for a file that cannot be read; no other exception leaves."""
    try:
        if not isinstance(data, (bytes, bytearray, memoryview)) or len(data) == 0:
            raise ValidationError(NOT_ILLUSTRATOR)
        return _read(bytes(data))
    except ValidationError:
        raise
    except _Abort:
        raise ValidationError(TOO_DETAILED) from None
    except MemoryError:
        raise ValidationError(TOO_DETAILED) from None
    except Exception:                                                   # damaged beyond what the readers tolerate
        raise ValidationError(DAMAGED) from None
