"""The portable laboratory release ``.tcelab`` v1 (electron REQ-083, DEC-024, Q-008): one UTF-8 JSON document of numbers, written and read
one record at a time, whose content hash any implementation can reproduce.

The document is a JSON object whose members come in a fixed order: ``manifest``, ``lab``, then the record sections ``SECTIONS``, each an
array. Every line of the file is one piece of it, ending in a line feed (no BOM, no carriage return):

    {"manifest":<manifest>
    ,"lab":<lab>
    ,"equipment":[
    <record>
    ,<record>
    ]
    ,"materials":[
    ]
    ...
    }

Each manifest, lab and record is written in the canonical JSON of RFC 8785 (JCS): members sorted by key, no white space, numbers as
ECMAScript prints them, strings with only the required escapes. A record carries ``seq``, strictly ascending within its section, so a
release is written and read in one order. ``manifest.content_sha256`` is the SHA-256 of the whole file with that one member left out of
the manifest line; it detects a change of content, not who made it (DEC-024).

What a record may hold is the schema ``schemas/tcelab-1.schema.json`` (JSON Schema 2020-12, its subset that :func:`validate`
interprets): the allowlist of DEC-024. A file of a newer minor version of the same major is read when every capability it requires is
known here; members this version does not know are then kept with the record but never used. A newer major version is refused before
anything is stored. Numbers must be finite, keys plain ASCII names, text free of control and direction characters, of script and file
protocols and of absolute paths; nothing a release names is ever fetched. Limits (``ResourcePolicy``) refuse a release, never shorten it.

Standard library only: the cloud service validates releases with this same module."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping
from urllib.parse import urlsplit

FORMAT = "tcelab"
SCHEMA_MAJOR, SCHEMA_MINOR = 1, 0
SCHEMA_VERSION = f"{SCHEMA_MAJOR}.{SCHEMA_MINOR}"
SECTIONS = ("equipment", "materials", "captures", "measurements", "tone_profiles", "provenance")
RECORD_OF = {"equipment": "equipment", "materials": "material", "captures": "capture", "measurements": "measurement",
             "tone_profiles": "tone_profile", "provenance": "provenance"}
CAPABILITIES: frozenset[str] = frozenset({"measurements", "tone_profiles", "dot_profiles", "grey_ramps", "withdrawals"})
SCHEMA_FILE = Path(__file__).with_name("schemas") / "tcelab-1.schema.json"
EXTENSION = ".tcelab"
MEDIA_TYPE = "application/vnd.titanium.tcelab+json"

# The approved usage terms (DEC-042): id -> version, permissions and the names the screens show.
USAGE_TERMS = {
    "CC-BY-4.0": {"version": "4.0", "commercial": True, "modify": True, "redistribute": True,
                  "name": {"ru": "CC BY 4.0 — с указанием автора", "en": "CC BY 4.0 — with attribution"},
                  "summary": {"ru": "Можно использовать, изменять и передавать дальше, в том числе коммерчески, указывая автора.",
                              "en": "Use, adapt and share, commercially too, with attribution."},
                  "url": "https://creativecommons.org/licenses/by/4.0/"},
    "CC-BY-NC-4.0": {"version": "4.0", "commercial": False, "modify": True, "redistribute": True,
                     "name": {"ru": "CC BY-NC 4.0 — некоммерчески", "en": "CC BY-NC 4.0 — non-commercial"},
                     "summary": {"ru": "Можно использовать, изменять и передавать дальше с указанием автора, но не коммерчески.",
                                 "en": "Use, adapt and share with attribution, not commercially."},
                     "url": "https://creativecommons.org/licenses/by-nc/4.0/"},
    "tce-own-engravings-1": {"version": "1", "commercial": True, "modify": False, "redistribute": False,
                             "name": {"ru": "Только для своих гравировок", "en": "For own engravings only"},
                             "summary": {"ru": "Можно гравировать по этим данным и продавать изделия; передавать файл или данные дальше нельзя.",
                                         "en": "Engrave with these data and sell the products; do not pass the file or its data on."},
                             "url": None},
}

KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
SAFE_INT = 2 ** 53
UNSAFE_TEXT = re.compile(r"(?i)\b(?:javascript|vbscript|file|blob)\s*:|\bdata:\S|<\s*/?\s*script|(?:^|[\s\"'(=])(?:/(?:Users|home|private|var|tmp|Volumes)/|[A-Za-z]:\\|\\\\[^\\\s]+\\)")
DIRECTION = set("‎‏‪‫‬‭‮⁦⁧⁨⁩؜")


class FormatError(ValueError):
    """A release is not acceptable; ``code`` names why (the screens translate it), the message says where."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResourcePolicy:
    """The resources one release may use (REQ-083): bytes of the file and of one line, records per section, bins per profile, nesting and
    lengths of text. The defaults are DEC-024's starting limits; ``docs/features/electron/benchmarks`` records what was measured."""
    max_bytes: int = 16 * 1024 * 1024
    max_line_bytes: int = 256 * 1024
    max_records: Mapping[str, int] = field(default_factory=lambda: {"equipment": 1000, "materials": 1000, "captures": 50_000,
                                                                     "measurements": 50_000, "tone_profiles": 5_000, "provenance": 10_000})
    max_bins: int = 256
    max_depth: int = 8
    max_string: int = 2048
    max_number: float = 1e15

    def limit(self, section: str) -> int:
        return int(self.max_records.get(section, 0))


DEFAULT_POLICY = ResourcePolicy()


# -- canonical JSON (RFC 8785) ---------------------------------------------------------------------------------------------------
def _es_number(value: float) -> str:
    """A finite number as ECMAScript's Number::toString prints it (RFC 8785, 3.2.2.3), from Python's shortest round-trip digits."""
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    text = repr(abs(float(value)))
    mantissa, _, exponent = text.partition("e")
    whole, _, fraction = mantissa.partition(".")
    digits, point = (whole + fraction), len(whole) + int(exponent or 0)
    stripped = digits.lstrip("0")
    point -= len(digits) - len(stripped)
    digits = stripped.rstrip("0") or "0"
    k, n = len(digits), point
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    e = n - 1
    exp = f"e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + (digits if k == 1 else digits[0] + "." + digits[1:]) + exp


def _string(text: str) -> str:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise FormatError("text", "a string holds a lone surrogate") from None
    return json.dumps(text, ensure_ascii=False)


def canonical(value: Any, policy: ResourcePolicy = DEFAULT_POLICY, _depth: int = 0) -> str:
    """``value`` in RFC 8785 canonical JSON; refuses what a release may not hold (non-finite or huge numbers, non-name keys, depth)."""
    if _depth > policy.max_depth:
        raise FormatError("depth", f"nested deeper than {policy.max_depth}")
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > SAFE_INT:
            raise FormatError("number", f"integer {value} is outside the exactly representable range")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value) or abs(value) > policy.max_number:
            raise FormatError("number", f"number {value!r} is not finite or too large")
        return _es_number(value)
    if isinstance(value, str):
        if len(value) > policy.max_string:
            raise FormatError("limit", f"a string is longer than {policy.max_string} characters")
        return _string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical(v, policy, _depth + 1) for v in value) + "]"
    if isinstance(value, Mapping):
        for key in value:
            if not isinstance(key, str) or not KEY.fullmatch(key):
                raise FormatError("key", f"key {key!r} is not a plain name")
        return "{" + ",".join(f"{_string(k)}:{canonical(value[k], policy, _depth + 1)}" for k in sorted(value)) + "}"
    raise FormatError("type", f"a value of type {type(value).__name__} cannot be in a release")


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise FormatError("duplicate_key", f"key {key!r} appears twice in one object")
        out[key] = value
    return out


def _no_constant(name):
    raise FormatError("number", f"{name} is not a number a release may hold")


def decode(text: str) -> Any:
    """One JSON value read strictly: duplicate keys, NaN and Infinity are refused."""
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except RecursionError:
        raise FormatError("depth", "nested too deeply") from None
    except json.JSONDecodeError as exc:
        raise FormatError("json", f"not valid JSON: {exc.msg} at column {exc.colno}") from None


# -- text and identities ---------------------------------------------------------------------------------------------------------
def check_text(value: str, where: str, multiline: bool = False) -> None:
    """Text a release may carry: no control or direction characters (line breaks only where ``multiline``), no script or file protocols,
    no absolute paths. Text from a release is rendered as data and never followed; this refuses what has no business in it."""
    for ch in value:
        if ch in DIRECTION or (unicodedata.category(ch) in ("Cc", "Cf") and not (multiline and ch == "\n")):
            raise FormatError("text", f"{where}: control or direction character U+{ord(ch):04X}")
    if UNSAFE_TEXT.search(value):
        raise FormatError("text", f"{where}: a script or file protocol or an absolute path")


def check_url(value: str, where: str) -> None:
    """A link a release may show (never fetched): https, a host name with a domain, no credentials, at most 512 characters."""
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        parts, port = None, None
    if (len(value) > 512 or parts is None or parts.scheme != "https" or not re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", parts.hostname or "")
            or re.search(r"[\s<>\"'`\\]", value) or (port is not None and not 0 < port < 65536)):
        raise FormatError("url", f"{where}: only an https link to a named host is allowed")
    if parts.username is not None or parts.password is not None:
        raise FormatError("url", f"{where}: a link with credentials is not allowed")
    check_text(value, where)


def _walk_text(value, where: str) -> None:
    if isinstance(value, str):
        check_text(value, where)
    elif isinstance(value, Mapping):
        for k, v in value.items():
            _walk_text(v, f"{where}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _walk_text(v, f"{where}[{i}]")


def utc_now() -> str:
    """Now in UTC with microseconds, so that two releases made in one second still follow each other in their text order."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# -- schema -------------------------------------------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


_TYPES = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list), "string": lambda v: isinstance(v, str),
          "boolean": lambda v: isinstance(v, bool), "null": lambda v: v is None,
          "integer": lambda v: isinstance(v, int) and not isinstance(v, bool) or (isinstance(v, float) and v.is_integer()),
          "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)}


def validate(value: Any, rule: Mapping, where: str = "$", strict: bool = True, root: Mapping | None = None) -> None:
    """``value`` against a JSON Schema ``rule``, in the subset the release schema uses: ``$ref`` to ``$defs``, ``type`` (one or a list),
    ``anyOf``, ``enum``, ``const``, ``properties``, ``required``, ``additionalProperties`` (``false`` or a schema), ``items``, ``minItems``,
    ``maxItems``, ``minimum``, ``maximum``, ``exclusiveMinimum``, ``minLength``, ``maxLength``, ``pattern``, ``format`` (``uuid``,
    ``date-time``, ``uri``). With ``strict`` false, members the schema does not name are allowed (a newer minor version)."""
    root = schema() if root is None else root
    if "$ref" in rule:
        name = rule["$ref"].rsplit("/", 1)[-1]
        return validate(value, root["$defs"][name], where, strict, root)
    if "anyOf" in rule:
        for option in rule["anyOf"]:
            try:
                validate(value, option, where, strict, root)
                break
            except FormatError:
                continue
        else:
            raise FormatError("schema", f"{where}: matches none of the allowed forms")
    kinds = rule.get("type")
    if kinds is not None:
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if not any(_TYPES[k](value) for k in kinds):
            raise FormatError("schema", f"{where}: expected {' or '.join(kinds)}")
    if "const" in rule and value != rule["const"]:
        raise FormatError("schema", f"{where}: must be {rule['const']!r}")
    if "enum" in rule and value not in rule["enum"]:
        raise FormatError("schema", f"{where}: {value!r} is not one of {rule['enum']}")
    if isinstance(value, str):
        if len(value) < rule.get("minLength", 0) or len(value) > rule.get("maxLength", 10 ** 9):
            raise FormatError("schema", f"{where}: length out of range")
        if "pattern" in rule and not re.fullmatch(rule["pattern"], value):
            raise FormatError("schema", f"{where}: does not match {rule['pattern']}")
        fmt = rule.get("format")
        if fmt == "uuid" and not UUID.fullmatch(value):
            raise FormatError("schema", f"{where}: not a lowercase UUID")
        if fmt == "date-time" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
            raise FormatError("schema", f"{where}: not a UTC time like 2026-10-24T12:00:00Z")
        if fmt == "uri":
            check_url(value, where)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in rule and value < rule["minimum"] or "maximum" in rule and value > rule["maximum"]:
            raise FormatError("schema", f"{where}: {value} is out of range")
        if "exclusiveMinimum" in rule and value <= rule["exclusiveMinimum"]:
            raise FormatError("schema", f"{where}: {value} must be above {rule['exclusiveMinimum']}")
    if isinstance(value, list):
        if len(value) < rule.get("minItems", 0) or len(value) > rule.get("maxItems", 10 ** 9):
            raise FormatError("schema", f"{where}: {len(value)} items out of range")
        if "items" in rule:
            for i, item in enumerate(value):
                validate(item, rule["items"], f"{where}[{i}]", strict, root)
    if isinstance(value, dict):
        props = rule.get("properties", {})
        for name in rule.get("required", ()):
            if name not in value:
                raise FormatError("schema", f"{where}: {name} is missing")
        extra = rule.get("additionalProperties", True)
        for name, item in value.items():
            if name in props:
                validate(item, props[name], f"{where}.{name}", strict, root)
            elif extra is False:
                if strict:
                    raise FormatError("schema", f"{where}: {name} is not allowed")
            elif isinstance(extra, Mapping):
                validate(item, extra, f"{where}.{name}", strict, root)


# -- manifest and compatibility --------------------------------------------------------------------------------------------------
def version_of(manifest: Mapping) -> tuple[int, int]:
    found = re.fullmatch(r"(\d{1,4})\.(\d{1,4})", str(manifest.get("schema_version", "")))
    if manifest.get("format") != FORMAT or not found:
        raise FormatError("not_a_release", "this is not a laboratory release (.tcelab)")
    return int(found.group(1)), int(found.group(2))


def compatibility(manifest: Mapping) -> dict:
    """Whether this version reads a release with this manifest (REQ-083): a newer major version never; a newer minor one when every
    capability it requires is known here (then ``strict`` is false: members this version does not know are kept and not used)."""
    major, minor = version_of(manifest)
    if major != SCHEMA_MAJOR:
        raise FormatError("version_major", f"schema version {major}.{minor} is not supported: this version reads {SCHEMA_MAJOR}.x")
    required = set((manifest.get("capabilities") or {}).get("required") or ())
    unknown = sorted(required - CAPABILITIES)
    if unknown:
        raise FormatError("capability", f"the release requires capabilities this version does not have: {', '.join(unknown)}")
    optional = set((manifest.get("capabilities") or {}).get("optional") or ())
    return {"schema_version": f"{major}.{minor}", "strict": minor <= SCHEMA_MINOR, "newer_minor": minor > SCHEMA_MINOR,
            "unknown_optional": sorted(optional - CAPABILITIES)}


def check_manifest(manifest: Mapping, strict: bool = True, policy: ResourcePolicy = DEFAULT_POLICY) -> None:
    validate(manifest, {"$ref": "#/$defs/manifest"}, "manifest", strict)
    _walk_text({k: v for k, v in manifest.items() if k != "attribution"}, "manifest")
    attribution = manifest["attribution"]
    for key in ("name", "organization"):
        if attribution.get(key):
            check_text(attribution[key], f"manifest.attribution.{key}")
    terms = manifest["usage_terms"]
    if terms["id"] not in USAGE_TERMS:
        raise FormatError("terms", f"usage terms {terms['id']!r} are not on the approved list")
    for section in SECTIONS:
        count = manifest["counts"].get(section, 0)
        if count > policy.limit(section):
            raise FormatError("limit", f"{count} {section} exceed the limit of {policy.limit(section)}")


def check_record(section: str, record: Mapping, strict: bool = True, policy: ResourcePolicy = DEFAULT_POLICY) -> None:
    validate(record, {"$ref": f"#/$defs/{RECORD_OF[section]}"}, f"{section}[{record.get('seq', '?')}]", strict)
    if section == "tone_profiles" and len(record["bins"]) > policy.max_bins:
        raise FormatError("limit", f"a tone profile has {len(record['bins'])} bins, more than {policy.max_bins}")
    _walk_text(record, f"{section}[{record.get('seq')}]")


def check_lab(lab: Mapping, manifest: Mapping, strict: bool = True) -> None:
    validate(lab, {"$ref": "#/$defs/lab"}, "lab", strict)
    if lab["id"] != manifest["origin_lab_id"]:
        raise FormatError("reference", "the laboratory record is not the laboratory of the manifest")
    check_text(lab["name"], "lab.name")
    if lab.get("description"):
        check_text(lab["description"], "lab.description", multiline=True)


# -- writing ----------------------------------------------------------------------------------------------------------------------
class Cancelled(Exception):
    """The user cancelled a long export or import; nothing was kept."""


def _encode_line(text: str, policy: ResourcePolicy) -> bytes:
    data = (text + "\n").encode("utf-8")
    if len(data) > policy.max_line_bytes:
        raise FormatError("limit", f"a record is longer than {policy.max_line_bytes} bytes")
    return data


def write(path: str | Path, manifest: Mapping, lab: Mapping, sections: Mapping[str, Iterable[Mapping]], *,
          policy: ResourcePolicy = DEFAULT_POLICY, progress: Callable[[str, int], None] | None = None,
          cancelled: Callable[[], bool] | None = None) -> dict:
    """Write a release to ``path`` and return its manifest with ``counts`` and ``content_sha256``. ``manifest`` holds every other member;
    ``sections`` give each section's records lazily, in ``seq`` order, so memory does not grow with the release. Each record is checked
    against the schema as it is written. The body is written to a temporary file first and the release appears under ``path`` only
    complete (an atomic rename), so a failure or ``cancelled`` leaves nothing behind."""
    path = Path(path)
    unknown = set(sections) - set(SECTIONS)
    if unknown:
        raise FormatError("schema", f"unknown sections {sorted(unknown)}")
    base = {k: v for k, v in manifest.items() if k not in ("counts", "content_sha256")}
    counts = {}
    hasher_body = hashlib.sha256()
    size = 0
    tmp_dir = path.parent
    tmp_dir.mkdir(parents=True, exist_ok=True)
    body = tempfile.NamedTemporaryFile("wb", dir=tmp_dir, prefix=".tcelab-body-", delete=False)
    final = None
    try:
        def emit(text: str) -> None:
            nonlocal size
            data = _encode_line(text, policy)
            size += len(data)
            if size > policy.max_bytes:
                raise FormatError("limit", f"the release is larger than {policy.max_bytes} bytes")
            hasher_body.update(data)
            body.write(data)

        check_lab(lab, {**base, "origin_lab_id": base.get("origin_lab_id")})
        emit("," + _string("lab") + ":" + canonical(dict(lab), policy))
        for section in SECTIONS:
            emit("," + _string(section) + ":[")
            last, n = -1, 0
            for record in sections.get(section, ()):
                if cancelled is not None and n % 256 == 0 and cancelled():
                    raise Cancelled()
                check_record(section, record, True, policy)
                if record["seq"] <= last:
                    raise FormatError("order", f"{section}: seq {record['seq']} after {last}")
                last = record["seq"]
                n += 1
                if n > policy.limit(section):
                    raise FormatError("limit", f"more than {policy.limit(section)} {section}")
                emit(("" if n == 1 else ",") + canonical(dict(record), policy))
                if progress is not None and n % 1000 == 0:
                    progress(section, n)
            counts[section] = n
            emit("]")
        emit("}")
        body.close()
        full = {**base, "counts": counts}
        check_manifest({**full, "content_sha256": "0" * 64}, True, policy)
        head = "{" + _string("manifest") + ":" + canonical(full, policy)
        digest = hashlib.sha256(_encode_line(head, policy))
        with open(body.name, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        full["content_sha256"] = digest.hexdigest()
        final = tempfile.NamedTemporaryFile("wb", dir=tmp_dir, prefix=".tcelab-", delete=False)
        final.write(_encode_line("{" + _string("manifest") + ":" + canonical(full, policy), policy))
        with open(body.name, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                final.write(chunk)
        final.flush()
        os.fsync(final.fileno())
        final.close()
        os.replace(final.name, path)
        final = None
        return full
    finally:
        body.close()
        Path(body.name).unlink(missing_ok=True)
        if final is not None:
            final.close()
            Path(final.name).unlink(missing_ok=True)


# -- reading ----------------------------------------------------------------------------------------------------------------------
def _lines(stream, policy: ResourcePolicy) -> Iterator[bytes]:
    while True:
        line = stream.readline(policy.max_line_bytes + 1)
        if not line:
            return
        if len(line) > policy.max_line_bytes:
            raise FormatError("limit", f"a line is longer than {policy.max_line_bytes} bytes")
        if not line.endswith(b"\n"):
            raise FormatError("truncated", "the file ends in the middle of a line")
        yield line


def _text(line: bytes) -> str:
    if b"\r" in line:
        raise FormatError("framing", "carriage returns are not allowed")
    try:
        return line[:-1].decode("utf-8")
    except UnicodeDecodeError:
        raise FormatError("encoding", "the file is not UTF-8") from None


def read(stream, *, policy: ResourcePolicy = DEFAULT_POLICY, progress: Callable[[int], None] | None = None,
         cancelled: Callable[[], bool] | None = None) -> Iterator[tuple[str, Any]]:
    """The pieces of a release from a binary ``stream``, checked as they come: ``("manifest", m)``, ``("compatibility", c)``,
    ``("lab", lab)``, then ``(section, record)`` for every record, and last ``("end", manifest)`` once the counts and the content hash are
    confirmed. Any problem raises :class:`FormatError` at the line it is found on; the caller keeps nothing unless ``end`` arrives.
    Memory does not grow with the release; uniqueness and references are the caller's to check (on disk)."""
    lines = _lines(stream, policy)
    total = 0

    def nxt() -> tuple[bytes, str]:
        nonlocal total
        try:
            line = next(lines)
        except StopIteration:
            raise FormatError("truncated", "the file ends before the release is complete") from None
        total += len(line)
        if total > policy.max_bytes:
            raise FormatError("limit", f"the release is larger than {policy.max_bytes} bytes")
        return line, _text(line)

    def piece(text: str, prefix: str) -> Any:
        if not text.startswith(prefix):
            raise FormatError("framing", f"expected {prefix!r}")
        value = decode(text[len(prefix):])
        try:
            again = canonical(value, policy)
        except FormatError:
            raise
        if again != text[len(prefix):]:
            raise FormatError("canonical", f"not in canonical form after {prefix!r}")
        return value

    first, text = nxt()
    if first.startswith(b"\xef\xbb\xbf"):
        raise FormatError("framing", "a byte order mark is not allowed")
    head = '{"manifest":'
    if not text.startswith(head):
        raise FormatError("not_a_release", "this is not a laboratory release (.tcelab)")
    manifest = decode(text[len(head):])
    if not isinstance(manifest, dict):
        raise FormatError("not_a_release", "this is not a laboratory release (.tcelab)")
    compat = compatibility(manifest)
    strict = compat["strict"]
    if canonical(manifest, policy) != text[len(head):]:
        raise FormatError("canonical", "the manifest is not in canonical form")
    check_manifest(manifest, strict, policy)
    yield "manifest", manifest
    yield "compatibility", compat
    digest = hashlib.sha256(_encode_line(head + canonical({k: v for k, v in manifest.items() if k != "content_sha256"}, policy), policy))

    line, text = nxt()
    digest.update(line)
    lab = piece(text, ',"lab":')
    check_lab(lab, manifest, strict)
    yield "lab", lab
    counts = {}
    for section in SECTIONS:
        if cancelled is not None and cancelled():          # at every section too, so that a small release can be cancelled
            raise Cancelled()
        if progress is not None:
            progress(total)
        line, text = nxt()
        digest.update(line)
        if text != f',"{section}":[':
            raise FormatError("framing", f"expected the section {section}")
        n, last = 0, -1
        while True:
            line, text = nxt()
            digest.update(line)
            if text == "]":
                break
            record = piece(text, "" if n == 0 else ",")
            if not isinstance(record, dict):
                raise FormatError("schema", f"{section}: a record must be an object")
            check_record(section, record, strict, policy)
            if record["seq"] <= last:
                raise FormatError("order", f"{section}: seq {record['seq']} after {last}")
            last = record["seq"]
            n += 1
            if n > policy.limit(section):
                raise FormatError("limit", f"more than {policy.limit(section)} {section}")
            if cancelled is not None and n % 256 == 0 and cancelled():
                raise Cancelled()
            if progress is not None and n % 512 == 0:
                progress(total)
            yield section, record
        counts[section] = n
    line, text = nxt()
    digest.update(line)
    if text != "}":
        raise FormatError("framing", "expected the end of the release")
    if stream.read(1):
        raise FormatError("framing", "something follows the end of the release")
    if counts != {s: manifest["counts"].get(s, 0) for s in SECTIONS}:
        raise FormatError("counts", "the number of records is not the one the manifest declares")
    if digest.hexdigest() != manifest["content_sha256"]:
        raise FormatError("hash", "the content does not match its hash: the file was changed or damaged")
    if progress is not None:
        progress(total)
    yield "end", manifest


def peek_manifest(path: str | Path, policy: ResourcePolicy = DEFAULT_POLICY) -> dict:
    """The manifest of a release file, checked (version, schema, limits) without reading the rest."""
    with open(path, "rb") as fh:
        line = fh.readline(policy.max_line_bytes + 1)
    if not line.endswith(b"\n"):
        raise FormatError("not_a_release", "this is not a laboratory release (.tcelab)")
    text = _text(line)
    head = '{"manifest":'
    if not text.startswith(head):
        raise FormatError("not_a_release", "this is not a laboratory release (.tcelab)")
    manifest = decode(text[len(head):])
    if not isinstance(manifest, dict):
        raise FormatError("not_a_release", "this is not a laboratory release (.tcelab)")
    compat = compatibility(manifest)
    check_manifest(manifest, compat["strict"], policy)
    return manifest
