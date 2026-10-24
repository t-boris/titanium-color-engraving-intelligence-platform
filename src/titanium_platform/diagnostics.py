"""The diagnostics export of a workshop (feature electron, REQ-080): one small zip the operator can send with a bug report, holding what
explains a failure and nothing of the work itself.

It holds ``summary.json`` (the application and schema versions, the platform, the counts of the main tables, the result of the database's
integrity check, the connected laboratory releases by id and name, the settings with any value that looks like a secret replaced),
``logs/<name>.log`` (the last lines of every ``*.log`` file in the workshop folder) and ``audit.jsonl`` (the last audit records). Every
text goes through :func:`redact` first: the home folder becomes ``~``, other user folders lose their user name, e-mail addresses and
anything that looks like a key or token (``sk-…``, long hexadecimal or base64 runs, ``…_KEY=value``) are replaced. Photographs, files
of works, the database itself and laboratory releases are never in it: the members of the zip are exactly the ones listed here.
"""
from __future__ import annotations

import json
import platform
import re
import shutil
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, migrations
from . import setup as su
from .db import Store

PREFIX = "titanium-diagnostics-"
NAME = re.compile(r"^titanium-diagnostics-\d{8}T\d{6}Z(-\d+)?\.zip$")
LOG_LINES = 500                                   # the tail of each log file that is kept
AUDIT_ROWS = 200
TABLES = ("laser_device", "lens", "material_profile", "plate", "plan", "pair", "observation", "capture_setup", "finding", "proposal",
          "lab_source", "lab_release", "lab_withdrawal", "portable_id", "audit")
SECRET_KEY = re.compile(r"(key|token|secret|password|passwd|credential)", re.I)

_HOME = re.compile(re.escape(str(Path.home())) + r"(?=[/\\\s\"'),;:]|$)")
_USER_DIR = re.compile(r"(?P<root>(?:/Users|/home|[A-Za-z]:\\Users)[/\\])[^/\\\s\"'),;:]+")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ASSIGNED = re.compile(r"\b(?P<name>[A-Za-z0-9_-]*(?:key|token|secret|password|passwd)[A-Za-z0-9_-]*)(?P<sep>\s*[=:]\s*)(?P<value>\S+)", re.I)
_SK = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")
_HEX = re.compile(r"\b[A-Fa-f0-9]{32,}\b")
_BASE64 = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9+/_-])")


def redact(text: str, home: str | Path | None = None) -> str:
    """``text`` with the home folder, other user names in paths, e-mail addresses and anything that looks like a key or token replaced."""
    if not text:
        return text
    pattern = _HOME if home is None else re.compile(re.escape(str(home)) + r"(?=[/\\\s\"'),;:]|$)")
    out = pattern.sub("~", text)
    out = _USER_DIR.sub(lambda m: m.group("root") + "<user>", out)
    out = _EMAIL.sub("<email>", out)
    out = _ASSIGNED.sub(lambda m: m.group("name") + m.group("sep") + "<redacted>", out)
    out = _SK.sub("<key>", out)
    out = _BEARER.sub(lambda m: m.group(1) + "<token>", out)
    out = _HEX.sub("<hex>", out)
    out = _BASE64.sub("<token>", out)
    return out


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _tail(path: Path, lines: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"(the log could not be read: {exc.__class__.__name__})\n"
    kept = text.splitlines()[-lines:]
    return "\n".join(kept) + ("\n" if kept else "")


def _settings(store: Store) -> dict:
    out = {}
    for row in store.query("SELECT key, value_json FROM setting ORDER BY key"):
        if SECRET_KEY.search(row["key"]):
            out[row["key"]] = "<redacted>"
            continue
        try:
            value = json.loads(row["value_json"])
        except ValueError:
            value = row["value_json"]
        out[row["key"]] = json.loads(redact(json.dumps(value, ensure_ascii=False)))
    return out


def _counts(store: Store) -> dict:
    present = {r["name"] for r in store.query("SELECT name FROM sqlite_master WHERE type='table'")}
    return {t: store.one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in TABLES if t in present}


def _releases(store: Store) -> list[dict]:
    rows = store.query("SELECT s.id AS source_id, s.name, s.status, r.release_id, r.release_number, r.status AS release_status, r.retrieved_at "
                       "FROM lab_source s LEFT JOIN lab_release r ON r.source_id=s.id ORDER BY s.id, r.retrieved_at")
    return [{k: (redact(v) if isinstance(v, str) else v) for k, v in dict(r).items()} for r in rows]


def summary(store: Store) -> dict:
    """What the export says about the workshop, before it is written: nothing of the work, only versions, counts and health."""
    usage = shutil.disk_usage(store.data_dir)
    try:
        integrity = store.conn.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        integrity = f"failed: {exc.__class__.__name__}"
    return {"kind": "titanium-workshop-diagnostics", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "app": __version__, "schema": migrations.version(store.conn), "schema_known": migrations.CURRENT,
            "platform": platform.platform(), "machine": platform.machine(), "python": sys.version.split()[0],
            "data_dir": redact(str(store.data_dir)), "disk": {"free_bytes": usage.free, "total_bytes": usage.total},
            "database_bytes": sum(p.stat().st_size for p in (store.path, store.path.with_name(store.path.name + "-wal")) if p.exists()),
            "integrity_check": integrity, "counts": _counts(store), "lab_releases": _releases(store), "settings": _settings(store),
            "lock": migrations.holder(store.data_dir)}


def export(store: Store, target_dir: str | Path, log_lines: int = LOG_LINES) -> dict:
    """Write ``titanium-diagnostics-<UTC>.zip`` under ``target_dir`` (never inside the workshop); the members and sizes it holds."""
    folder = Path(str(target_dir)).expanduser()
    if not str(target_dir).strip():
        raise su.ValidationError("choose the folder the diagnostics file is written to")
    if folder.resolve() == store.data_dir.resolve() or store.data_dir.resolve() in folder.resolve().parents:
        raise su.ValidationError("a diagnostics file cannot be written inside the workshop: choose another folder")
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{PREFIX}{_utc()}.zip"
    path, n = folder / name, 1
    while path.exists():
        n += 1
        path = folder / f"{PREFIX}{_utc()}-{n}.zip"
    members = []
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("summary.json", json.dumps(summary(store), indent=1, ensure_ascii=False, sort_keys=True))
        members.append("summary.json")
        for log in sorted(p for p in store.data_dir.glob("*.log") if p.is_file()):
            zf.writestr(f"logs/{log.name}", redact(_tail(log, log_lines)))
            members.append(f"logs/{log.name}")
        rows = store.query("SELECT at, action, detail_json FROM audit ORDER BY id DESC LIMIT ?", (AUDIT_ROWS,))
        lines = [json.dumps({"at": r["at"], "action": r["action"], "detail": json.loads(redact(r["detail_json"]))}, ensure_ascii=False) for r in reversed(rows)]
        zf.writestr("audit.jsonl", "\n".join(lines) + ("\n" if lines else ""))
        members.append("audit.jsonl")
    store.audit("diagnostics_exported", path=str(path), members=len(members))
    return {"path": str(path), "name": path.name, "members": members, "bytes": path.stat().st_size}


def find(folders, name: str) -> Path:
    """The diagnostics file ``name`` in one of ``folders``; only a name this module writes is looked for."""
    if NAME.match(name):
        for folder in folders:
            candidate = Path(folder).expanduser() / name
            if candidate.is_file():
                return candidate
    raise KeyError(f"there is no diagnostics file {name}")
