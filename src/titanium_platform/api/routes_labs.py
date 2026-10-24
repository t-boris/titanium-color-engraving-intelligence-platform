"""Portable laboratories (feature electron, REQ-083..085): the workshop's own laboratory published as a ``.tcelab`` release, and the
laboratories of others connected from their files. The screens are «Моя лаборатория» and «Подключённые лаборатории» (``#/labs``)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse

from .. import evidence_source as es, lab_export, lab_format as lf, lab_import, lab_transfer
from .. import setup as su
from .common import content_disposition, store_of

router = APIRouter(prefix="/api/labs")
EXPORTS = "lab_exports"                # the workshop's own releases, kept to be downloaded again (and later published)


def _exports_dir(request: Request):
    folder = store_of(request).data_dir / EXPORTS
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# -- the own laboratory ----------------------------------------------------------------------------------------------------------
@router.get("/own")
def own(request: Request):
    """What the owner enters for publication, what can be chosen, the releases written so far and the withdrawals declared."""
    store = store_of(request)
    exports = [{"release_id": r["release_id"], "created_at": r["created_at"], "bytes": r["bytes"], "content_sha256": r["content_sha256"],
                "counts": r["manifest"]["counts"], "terms": r["manifest"]["usage_terms"], "file": (_exports_dir(request) / f"{r['release_id']}.tcelab").is_file(),
                "published": r["published"]}
               for r in lab_export.exports(store)]
    return {"public": lab_export.public_info(store), "choices": lab_export.choices(store), "exports": exports,
            "withdrawals": lab_export.withdrawals(store), "terms": [{"id": k, **v} for k, v in lf.USAGE_TERMS.items()]}


@router.put("/own")
def set_own(request: Request, body: dict):
    """Keep the laboratory's public name, description, link, author and the public names of its lasers."""
    return lab_export.set_public_info(store_of(request), body)


@router.post("/own/preview")
def preview(request: Request, body: dict):
    """What a release of ``selection`` would hold, what is turned into tokens and what is never published."""
    return lab_export.preview(store_of(request), body.get("selection"))


@router.post("/own/releases", status_code=201)
def write_release(request: Request, body: dict):
    """Write a release of ``selection`` under ``terms``; its manifest and the address to download it from."""
    release_id = str(uuid.uuid4())
    path = _exports_dir(request) / f"{release_id}.tcelab"
    manifest = lab_export.export(store_of(request), path, body.get("selection"), body.get("terms"), release_id=release_id)
    return {"manifest": manifest, "download": f"/api/labs/own/releases/{release_id}/file"}


@router.get("/own/releases/{release_id}/file")
def release_file(request: Request, release_id: str):
    """A release this workshop wrote, as the ``.tcelab`` file to give to others."""
    path = _exports_dir(request) / f"{release_id}.tcelab"
    if not lf.UUID.fullmatch(release_id) or not path.is_file():
        raise KeyError("this release file is not kept on this computer")
    name = lab_export.public_info(store_of(request))["name"] or "laboratory"
    return FileResponse(path, media_type=lf.MEDIA_TYPE, headers={"Content-Disposition": content_disposition(f"{name} {release_id[:8]}", lf.EXTENSION)})


@router.post("/own/withdrawals", status_code=201)
def withdraw(request: Request, body: dict):
    """Withdraw a published release, measurement or tonal profile; the statement goes out with every later release."""
    return lab_export.withdraw(store_of(request), body.get("target_kind"), body.get("target_id"), body.get("reason"),
                               body.get("replacement_release_id"))


# -- connecting the laboratories of others ----------------------------------------------------------------------------------------
@router.post("/files", status_code=201)
def receive(request: Request, release: UploadFile = File(None)):
    """Keep a chosen ``.tcelab`` file aside and show what it declares; nothing is connected yet."""
    if release is None or not release.filename:
        raise su.ValidationError("choose the laboratory release file")
    store = store_of(request)
    token = lab_import.stage(store, iter(lambda: release.file.read(lab_import.CHUNK), b""))
    try:
        return lab_import.inspect(store, token)
    except BaseException:
        lab_import.discard(store, token)
        raise


@router.delete("/files/{token}")
def forget(request: Request, token: str):
    lab_import.discard(store_of(request), token)
    return {"discarded": token}


@router.post("/files/{token}/connect", status_code=202)
def connect(request: Request, token: str):
    """Check and connect the kept file in the background; the job to follow."""
    return lab_import.start(store_of(request), token)


@router.get("/jobs/{job_id}")
def job(job_id: str):
    return lab_import.status(job_id)


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str):
    return lab_import.cancel(job_id)


@router.get("/sources")
def sources(request: Request):
    return lab_import.sources(store_of(request))


@router.get("/sources/{source_id}")
def source(request: Request, source_id: int):
    return lab_import.source(store_of(request), source_id)


@router.post("/sources/{source_id}/disconnect")
def disconnect(request: Request, source_id: int):
    return lab_import.disconnect(store_of(request), source_id)


@router.post("/sources/{source_id}/reconnect")
def reconnect(request: Request, source_id: int):
    return lab_import.reconnect(store_of(request), source_id)


# -- a connected release as the source of a work -----------------------------------------------------------------------------------
@router.get("/choices")
def choices(request: Request):
    """The connected laboratories a new work can take its colours and curves from, with the laser, lens and titanium each measured."""
    return es.choices(store_of(request))


@router.post("/palette")
def release_palette(request: Request, body: dict):
    """The colours a vector work would take from ``release_id`` with its ``laser``, ``lens`` and ``material`` (release identities)."""
    return es.release_palette(store_of(request), body)


@router.post("/scales")
def release_scales(request: Request, body: dict):
    """The grey scales a photo work would take from ``release_id`` with its ``laser`` and ``lens`` (release identities)."""
    return es.release_scales(store_of(request), body)


@router.post("/transfers", status_code=201)
def transfer(request: Request, body: dict):
    """«Проверить у себя»: a test plate of one colour of a connected release on the own laser (see lab_transfer.create)."""
    return lab_transfer.create(store_of(request), body)


@router.get("/transfers")
def transfers(request: Request, release_id: str | None = None):
    """Every transfer experiment with what it measured against the release's colour; of one release when given."""
    return lab_transfer.listing(store_of(request), release_id)


@router.get("/transfers/{plan_id}")
def transfer_of(request: Request, plan_id: int):
    return lab_transfer.compare(store_of(request), plan_id)


@router.delete("/releases/{release_id}")
def remove(request: Request, release_id: str):
    return lab_import.remove_release(store_of(request), release_id)


@router.get("/releases/{release_id}/differences")
def differences(request: Request, release_id: str, against: str | None = None):
    return lab_import.differences(store_of(request), release_id, against)
