"""The workshop itself (feature electron, REQ-080, REQ-081): where it is, its schema, who holds it; full backups and their restoration."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from .. import __version__, backup, diagnostics, migrations
from .. import setup as su
from .common import store_of

router = APIRouter(prefix="/api/workshop")
BACKUP_DIR = "backup_dir"                       # setting: the folder the operator keeps backups in


@router.get("")
def workshop(request: Request):
    """The open workshop: its folder, the schema it has and this application knows, the lock holder, the free space and the backup folder."""
    store = store_of(request)
    usage = shutil.disk_usage(store.data_dir)
    return {"data_dir": str(store.data_dir), "app": __version__, "schema": migrations.version(store.conn), "schema_known": migrations.CURRENT,
            "lock": migrations.holder(store.data_dir), "disk": {"free_bytes": usage.free, "total_bytes": usage.total},
            "backup_dir": store.get_setting(BACKUP_DIR), "default_backup_dir": str(store.data_dir / migrations.BACKUPS)}


def _backup_folders(store) -> list[str]:
    """The kept backup folder and the default one, in that order, without repeats."""
    return list(dict.fromkeys(f for f in (store.get_setting(BACKUP_DIR), str(Path.home() / "titanium-backups")) if f))


@router.get("/recovery-copies")
def recovery_copies(request: Request):
    """The copies of the database the application made by itself before changing its schema (``backups/`` beside the data), the newest first."""
    store = store_of(request)
    folder = store.data_dir / migrations.BACKUPS
    out = []
    if folder.is_dir():
        for path in folder.glob("*.sqlite"):
            if path.is_file():
                stat = path.stat()
                out.append({"name": path.name, "path": str(path), "bytes": stat.st_size,
                            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
                            "kind": "schema" if path.name.startswith("schema-before-") else "release" if path.name.startswith("titanium-before-") else "other"})
    return sorted(out, key=lambda c: c["modified_at"], reverse=True)


@router.post("/diagnostics", status_code=201)
def export_diagnostics(request: Request, body: dict | None = None):
    """The diagnostics zip (``diagnostics``) into ``target_dir``, by default the backup folder, with the address it is fetched from when it
    lies in one of the backup folders."""
    store = store_of(request)
    target = (body or {}).get("target_dir") or _backup_folders(store)[0]
    made = diagnostics.export(store, target)
    kept = Path(made["path"]).parent in [Path(f).expanduser() for f in _backup_folders(store)]
    return {**made, "download": f"/api/workshop/diagnostics/{made['name']}" if kept else None}


@router.get("/diagnostics/{name}")
def diagnostics_file(request: Request, name: str):
    """One diagnostics file written into a backup folder, by its name."""
    path = diagnostics.find(_backup_folders(store_of(request)), name)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.put("/backup-dir")
def set_backup_dir(request: Request, body: dict):
    """Keep the folder backups are written to by default."""
    folder = (body or {}).get("path")
    if not isinstance(folder, str) or not folder.strip():
        raise su.ValidationError("choose the folder the backup is written to")
    store_of(request).set_setting(BACKUP_DIR, folder.strip())
    return {"backup_dir": folder.strip()}


@router.post("/backups", status_code=201)
def make_backup(request: Request, body: dict | None = None):
    """A full backup into ``target_dir`` (by default the kept backup folder, else ``backups/`` beside the data)."""
    store = store_of(request)
    target = (body or {}).get("target_dir") or store.get_setting(BACKUP_DIR) or str(Path.home() / "titanium-backups")
    return backup.make(store, target)


@router.get("/backups")
def backups(request: Request):
    """Every backup under the kept backup folder and the default one, the newest first."""
    store = store_of(request)
    return backup.listing(_backup_folders(store))


@router.post("/backups/inspect")
def inspect_backup(body: dict):
    """What a backup folder holds and whether it is complete (every file checked against its hash)."""
    path = (body or {}).get("path")
    if not isinstance(path, str) or not path.strip():
        raise su.ValidationError("choose the backup folder")
    return backup.inspect(path.strip(), verify=bool((body or {}).get("verify", True)))


@router.post("/restore")
def restore(request: Request, body: dict):
    """Restore a backup (``path``) into ``target_dir``. Into another folder the restored workshop is opened by choosing that folder; into the
    open workshop's own folder only with ``overwrite`` true and ``confirm`` "overwrite": the folder is set aside and the application must be
    restarted to open what was restored."""
    store = store_of(request)
    path, target = (body or {}).get("path"), (body or {}).get("target_dir")
    if not isinstance(path, str) or not path.strip():
        raise su.ValidationError("choose the backup folder")
    if not isinstance(target, str) or not target.strip():
        raise su.ValidationError("choose the folder the workshop is restored into")
    overwrite = bool((body or {}).get("overwrite"))
    own = Path(target).expanduser().resolve() == store.data_dir.resolve()
    if own and not (overwrite and (body or {}).get("confirm") == "overwrite"):
        raise su.ValidationError("this folder is the open workshop: restoring into it replaces it, which must be chosen explicitly")
    done = backup.restore(path.strip(), target.strip(), overwrite=overwrite)
    store.audit("workshop_restored", path=path.strip(), target=target.strip(), set_aside=done["set_aside"], own=own)
    return {**done, "restart_needed": own}
