"""The endpoints of DEC-058. Reading a public laboratory needs no account; a private one is read by its owner and its members, and does
not exist for anyone else (404, never a hint). Every change is made by the laboratory's owner, checked here and again by the database's
policies. Status codes: 401 no or invalid token, 403 not the owner, 404 unknown or invisible, 409 the expected previous release is not
the latest, 410 an expired publication or a spent invitation, 413 a chunk above its size, 422 a release that is not acceptable."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any, Iterator, Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field

from . import __version__, _lab_format as lf, finalize as fz
from .auth import bearer
from .chunks import chunk_count as count_of, expected_size
from .errors import Conflict, Forbidden, Gone, Invalid, NotFound, TooLarge, Unauthorized
from .repository import InMemoryRepository, PostgresRepository, Repository, moment, now, stamp

router = APIRouter()
WITHDRAWN_KINDS = ("release", "measurement", "tone_profile")      # as lab_export.WITHDRAWN_KINDS


# -- who asks, and where the catalogue is -------------------------------------------------------------------------------------------
def viewer(request: Request, authorization: str | None = Header(default=None)) -> str | None:
    token = bearer(authorization)
    if token is None:
        return None
    if request.app.state.verifier is None:
        raise Unauthorized("sign-in is not configured on this service", "no_auth")
    return request.app.state.verifier.account_id(token)


def repo(request: Request, account: str | None = Depends(viewer)) -> Iterator[Repository]:
    memory: InMemoryRepository | None = request.app.state.memory
    if memory is not None:
        yield memory
        return
    store = PostgresRepository(request.app.state.settings.database_url, account)
    try:
        yield store
    finally:
        store.close()


def signed_in(account: str | None = Depends(viewer)) -> str:
    if account is None:
        raise Unauthorized()
    return account


# -- shapes ------------------------------------------------------------------------------------------------------------------------
def lab_view(lab: dict, role: str | None) -> dict:
    return {"id": lab["id"], "name": lab["name"], "author": lab["author"], "description": lab.get("description"), "url": lab.get("url"),
            "visibility": lab["visibility"], "origin_lab_id": lab["origin_lab_id"], "created_at": lab["created_at"], "role": role}


def release_view(release: dict) -> dict:
    manifest = release["manifest"]
    return {"id": release["id"], "lab_id": release["lab_id"], "number": release["number"], "content_sha256": release["content_sha256"],
            "file_sha256": release["file_sha256"], "byte_size": release["byte_size"], "chunk_count": release["chunk_count"],
            "chunk_bytes": release["chunk_bytes"], "counts": release["counts"], "terms": release["terms"], "usage_terms": manifest["usage_terms"],
            "attribution": manifest["attribution"], "schema_version": manifest["schema_version"], "created_at": manifest["created_at"],
            "algorithm_versions": manifest["algorithm_versions"], "previous_release_id": release.get("previous_release_id"),
            "published_at": release["published_at"]}


def publication_view(pub: dict) -> dict:
    return {k: pub[k] for k in ("id", "lab_id", "release_id", "release_number", "expected_previous_release_id", "file_sha256", "byte_size",
                                "chunk_count", "chunk_bytes", "state", "failure", "created_at", "expires_at")}


def visible_lab(store: Repository, lab_id: str, account: str | None) -> tuple[dict, str]:
    lab = store.lab(lab_id, account)
    role = store.role(lab, account) if lab else None
    if lab is None or role is None:
        raise NotFound()
    return lab, role


def owned_lab(store: Repository, lab_id: str, account: str) -> dict:
    lab, role = visible_lab(store, lab_id, account)
    if role != "owner":
        raise Forbidden()
    return lab


def visible_release(store: Repository, release_id: str, account: str | None) -> tuple[dict, dict, str]:
    release = store.release(release_id)
    if release is None:
        raise NotFound()
    lab, role = visible_lab(store, release["lab_id"], account)
    return release, lab, role


def live_publication(store: Repository, publication_id: str, account: str) -> dict:
    pub = store.publication(publication_id)
    if pub is None or pub["owner_id"] != account:
        raise NotFound("there is no such publication")
    if pub["state"] == "expired" or (pub["state"] == "uploading" and moment(pub["expires_at"]) < now()):
        store.fail(pub["id"], "expired", "the upload was not finalized in time")
        raise Gone("the upload expired: reserve a new publication", "expired")
    return pub


def _text(value: str | None, where: str, limit: int, multiline: bool = False) -> str | None:
    value = (value or "").strip() if multiline else " ".join((value or "").split())
    if len(value) > limit:
        raise Invalid(f"{where} is longer than {limit} characters", "text")
    if value:
        try:
            lf.check_text(value, where, multiline)
        except lf.FormatError as exc:
            raise Invalid(f"{where} may hold only plain text: {exc}", "text") from None
    return value or None


def _link(value: str | None, where: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        lf.check_url(value, where)
    except lf.FormatError as exc:
        raise Invalid(f"{where} is not an acceptable link: {exc}", "url") from None
    return value


# -- bodies ------------------------------------------------------------------------------------------------------------------------
class NewLab(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    author: str = Field(min_length=1, max_length=200)
    origin_lab_id: str = Field(pattern=lf.UUID.pattern)
    visibility: Literal["public", "private"] = "public"
    description: str | None = Field(default=None, max_length=2000)
    url: str | None = Field(default=None, max_length=500)


class Reserve(BaseModel):
    """A publication is reserved before the file exists: the author writes the release with the reserved identity, then uploads it."""
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_previous_release_id: str | None = Field(default=None, pattern=lf.UUID.pattern)


class Declared(BaseModel):
    """What the author says of the file at finalize; the server checks every part of it against the uploaded chunks."""
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=1)
    chunk_count: int = Field(ge=1)


class Target(BaseModel):
    kind: Literal["release", "measurement", "tone_profile"]
    id: str = Field(pattern=lf.UUID.pattern)


class Withdraw(BaseModel):
    targets: list[Target] = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=500)
    replacement_release_id: str | None = Field(default=None, pattern=lf.UUID.pattern)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class NewInvitation(BaseModel):
    expires_in_s: int | None = Field(default=None, ge=60, le=365 * 24 * 3600)


# -- reading ----------------------------------------------------------------------------------------------------------------------
@router.get("/health")
def health(request: Request) -> dict:
    return {"ok": True, "version": __version__, "repository": request.app.state.settings.repository, "chunk_bytes": request.app.state.settings.chunk_bytes}


@router.get("/labs")
def labs(store: Repository = Depends(repo), account: str | None = Depends(viewer)) -> dict:
    out = []
    for lab in store.labs(account):
        role = store.role(lab, account)
        if role is None:
            continue
        latest = store.latest(lab["id"])
        out.append({**lab_view(lab, role), "latest_release": release_view(latest) if latest else None})
    return {"labs": out}


@router.get("/labs/{lab_id}")
def lab(lab_id: str, store: Repository = Depends(repo), account: str | None = Depends(viewer)) -> dict:
    found, role = visible_lab(store, lab_id, account)
    releases = store.releases(found["id"])
    return {**lab_view(found, role), "release_count": len(releases), "latest_release": release_view(releases[0]) if releases else None}


@router.get("/labs/{lab_id}/releases")
def releases(lab_id: str, store: Repository = Depends(repo), account: str | None = Depends(viewer)) -> dict:
    found, _ = visible_lab(store, lab_id, account)
    return {"releases": [release_view(r) for r in store.releases(found["id"])]}


@router.get("/releases/{release_id}/manifest")
def manifest(release_id: str, store: Repository = Depends(repo), account: str | None = Depends(viewer)) -> dict:
    release, lab, role = visible_release(store, release_id, account)
    return {"release": release_view(release), "manifest": release["manifest"], "lab": release["lab"], "laboratory": lab_view(lab, role)}


@router.get("/releases/{release_id}/chunks/{n}")
def chunk(release_id: str, n: int, store: Repository = Depends(repo), account: str | None = Depends(viewer)) -> Response:
    release, lab, _ = visible_release(store, release_id, account)
    if not 0 <= n < release["chunk_count"]:
        raise NotFound(f"the release has chunks 0 to {release['chunk_count'] - 1}")
    data = store.chunk(release_id, n)
    if data is None:
        raise NotFound("the chunk is missing")
    cache = "public, max-age=31536000, immutable" if lab["visibility"] == "public" else "private, no-store"
    return Response(content=data, media_type="application/octet-stream",
                    headers={"X-Chunk-Index": str(n), "X-Chunk-Count": str(release["chunk_count"]), "Cache-Control": cache})


@router.get("/releases/{release_id}/withdrawals")
def withdrawals(release_id: str, store: Repository = Depends(repo), account: str | None = Depends(viewer)) -> dict:
    visible_release(store, release_id, account)
    return {"withdrawals": store.withdrawals(release_id)}


# -- the owner's laboratories and publications --------------------------------------------------------------------------------------
@router.post("/labs", status_code=201)
def create_lab(body: NewLab, store: Repository = Depends(repo), account: str = Depends(signed_in)) -> dict:
    fields = {"owner_id": account, "origin_lab_id": body.origin_lab_id, "visibility": body.visibility,
              "name": _text(body.name, "name", 200), "author": _text(body.author, "author", 200),
              "description": _text(body.description, "description", 2000, multiline=True), "url": _link(body.url, "url")}
    if not fields["name"] or not fields["author"]:
        raise Invalid("a laboratory needs a name and an author", "text")
    return lab_view(store.create_lab(fields), "owner")


@router.post("/labs/{lab_id}/publications", status_code=201)
def reserve(lab_id: str, body: Reserve, request: Request, store: Repository = Depends(repo), account: str = Depends(signed_in)) -> dict:
    lab = owned_lab(store, lab_id, account)
    settings = request.app.state.settings
    pub = store.reserve({"lab_id": lab["id"], "owner_id": account, "idempotency_key": body.idempotency_key,
                         "expected_previous_release_id": body.expected_previous_release_id, "chunk_bytes": settings.chunk_bytes,
                         "expires_at": stamp(now() + timedelta(seconds=settings.upload_lifetime_s))})
    if pub["lab_id"] != lab["id"]:
        raise Conflict("this idempotency key was used for another laboratory", "idempotency_key")
    return publication_view(pub)


@router.put("/publications/{publication_id}/chunks/{n}")
async def put_chunk(publication_id: str, n: int, request: Request, store: Repository = Depends(repo), account: str = Depends(signed_in)) -> dict:
    pub = live_publication(store, publication_id, account)
    if pub["state"] == "finalized":
        raise Conflict("the publication is finalized: a release never changes", "finalized")
    most = count_of(lf.DEFAULT_POLICY.max_bytes, pub["chunk_bytes"])
    if not 0 <= n < most:
        raise NotFound(f"a release has at most {most} chunks of {pub['chunk_bytes']} bytes")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > pub["chunk_bytes"]:
        raise TooLarge(f"a chunk has at most {pub['chunk_bytes']} bytes", "chunk_bytes")
    data = await request.body()
    if len(data) > pub["chunk_bytes"]:
        raise TooLarge(f"a chunk has at most {pub['chunk_bytes']} bytes", "chunk_bytes")
    if not data:
        raise Invalid("a chunk cannot be empty", "chunk_size")
    store.put_chunk(pub["id"], n, data)
    return {"publication_id": pub["id"], "n": n, "bytes": len(data)}


@router.post("/publications/{publication_id}/finalize")
def finalize(publication_id: str, body: Declared, store: Repository = Depends(repo), account: str = Depends(signed_in)) -> dict:
    pub = live_publication(store, publication_id, account)
    if pub["state"] == "finalized":
        if (body.file_sha256, body.byte_size, body.chunk_count) != (pub["file_sha256"], pub["byte_size"], pub["chunk_count"]):
            raise Conflict("the publication is finalized with other content: a release never changes", "finalized")
        return {"release": release_view(store.release(pub["release_id"])), "repeated": True}
    if pub["state"] == "failed":
        raise Conflict(pub["failure"] or "the publication failed", "expected_previous")
    if body.byte_size > lf.DEFAULT_POLICY.max_bytes:
        raise TooLarge(f"a release may have at most {lf.DEFAULT_POLICY.max_bytes} bytes", "limit")
    if body.chunk_count != count_of(body.byte_size, pub["chunk_bytes"]):
        raise Invalid(f"{body.byte_size} bytes make {count_of(body.byte_size, pub['chunk_bytes'])} chunks of {pub['chunk_bytes']}", "chunk_count")
    sizes = store.chunk_sizes(pub["id"])
    missing = [n for n in range(body.chunk_count) if n not in sizes]
    if missing:
        raise Invalid(f"chunks not uploaded yet: {missing[:20]}", "chunks_missing")
    for n in range(body.chunk_count):
        wanted = expected_size(n, body.byte_size, body.chunk_count, pub["chunk_bytes"])
        if sizes[n] != wanted:
            raise Invalid(f"chunk {n} has {sizes[n]} bytes, {wanted} were expected", "chunk_size")
    lab = store.lab(pub["lab_id"], account)
    declared = {"file_sha256": body.file_sha256, "byte_size": body.byte_size, "chunk_count": body.chunk_count}
    try:
        validated = fz.validate(store.publication_chunks(pub["id"], body.chunk_count), pub, lab, declared)
    except Invalid as exc:
        store.fail(pub["id"], "uploading", str(exc))
        raise
    try:
        release = store.finalize(pub["id"], validated)
    except Conflict as exc:
        store.fail(pub["id"], "failed", str(exc))
        raise
    return {"release": release_view(release), "repeated": False}


@router.get("/publications/{publication_id}")
def publication(publication_id: str, store: Repository = Depends(repo), account: str = Depends(signed_in)) -> dict:
    pub = live_publication(store, publication_id, account)
    return {**publication_view(pub), "chunks_received": sorted(store.chunk_sizes(pub["id"]))}


@router.post("/releases/{release_id}/withdraw", status_code=201)
def withdraw(release_id: str, body: Withdraw, store: Repository = Depends(repo), account: str = Depends(signed_in)) -> Any:
    release, lab, role = visible_release(store, release_id, account)
    if role != "owner":
        raise Forbidden()
    if body.idempotency_key:
        stored = store.idempotent(account, body.idempotency_key, "withdraw")
        if stored is not None:
            return stored[1]
    reason = _text(body.reason, "reason", 500, multiline=True)
    rows = [{"target_kind": t.kind, "target_id": t.id, "reason": reason, "replacement_release_id": body.replacement_release_id} for t in body.targets]
    made = {"withdrawals": store.add_withdrawals(release["id"], rows)}
    if body.idempotency_key:
        store.remember(account, body.idempotency_key, "withdraw", 201, made)
    return made


# -- invitations and members -------------------------------------------------------------------------------------------------------
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


@router.post("/labs/{lab_id}/invitations", status_code=201)
def create_invitation(lab_id: str, body: NewInvitation, request: Request, store: Repository = Depends(repo), account: str = Depends(signed_in)) -> dict:
    lab = owned_lab(store, lab_id, account)
    settings = request.app.state.settings
    token = secrets.token_urlsafe(32)
    lifetime = body.expires_in_s or settings.invitation_lifetime_s
    made = store.create_invitation({"lab_id": lab["id"], "token_hash": _hash(token), "created_by": account,
                                    "expires_at": stamp(now() + timedelta(seconds=lifetime))})
    base = settings.public_base_url or str(request.base_url).rstrip("/")
    return {"id": made["id"], "lab_id": lab["id"], "token": token, "link": f"{base}/invitations/{token}", "expires_at": made["expires_at"],
            "created_at": made["created_at"]}


@router.get("/labs/{lab_id}/invitations")
def invitations(lab_id: str, store: Repository = Depends(repo), account: str = Depends(signed_in)) -> dict:
    lab = owned_lab(store, lab_id, account)
    return {"invitations": [{k: i[k] for k in ("id", "lab_id", "created_at", "expires_at", "accepted_by", "accepted_at", "revoked_at")}
                            for i in store.invitations(lab["id"])]}


@router.delete("/labs/{lab_id}/invitations/{invitation_id}", status_code=204)
def revoke_invitation(lab_id: str, invitation_id: str, store: Repository = Depends(repo), account: str = Depends(signed_in)) -> Response:
    lab = owned_lab(store, lab_id, account)
    if not store.revoke_invitation(lab["id"], invitation_id):
        raise NotFound("there is no such invitation")
    return Response(status_code=204)


@router.post("/invitations/{token}/accept")
def accept_invitation(token: str, store: Repository = Depends(repo), account: str = Depends(signed_in)) -> dict:
    member = store.accept_invitation(_hash(token), account)
    lab, role = visible_lab(store, member["lab_id"], account)
    return {"lab": lab_view(lab, role), "member_since": member["created_at"]}


@router.get("/labs/{lab_id}/members")
def members(lab_id: str, store: Repository = Depends(repo), account: str = Depends(signed_in)) -> dict:
    lab = owned_lab(store, lab_id, account)
    return {"members": store.members(lab["id"])}


@router.delete("/labs/{lab_id}/members/{account_id}", status_code=204)
def remove_member(lab_id: str, account_id: str, store: Repository = Depends(repo), account: str = Depends(signed_in)) -> Response:
    lab = owned_lab(store, lab_id, account)
    if not store.remove_member(lab["id"], account_id):
        raise NotFound("there is no such member")
    return Response(status_code=204)
