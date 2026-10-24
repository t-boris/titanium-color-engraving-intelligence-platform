"""The cloud API of laboratories (electron REQ-086, REQ-087, DEC-058) against the in-memory repository: anonymous reading of public
laboratories, owner-only changes, invitation-only private ones, chunked publication validated on finalize, idempotent retries, the
expected-previous-release check, withdrawals, and tokens verified against a JWKS. ``cloud/tests_live`` runs these very tests against
the Neon database through another ``app`` fixture."""
from __future__ import annotations

import hashlib
import io
import sys
import time
import uuid
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from fastapi.testclient import TestClient

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "cloud"))

import labworld  # noqa: E402
from titanium_cloud import _lab_format as clf  # noqa: E402
from titanium_cloud.app import create_app  # noqa: E402
from titanium_cloud.auth import Verifier  # noqa: E402
from titanium_cloud.chunks import split  # noqa: E402
from titanium_cloud.settings import Settings  # noqa: E402
from titanium_platform import lab_export, lab_format as lf, lab_import  # noqa: E402
from titanium_platform.db import Store  # noqa: E402

CHUNK = 16 * 1024                       # small chunks, so that a test release takes several
ISSUER = "https://auth.test"


# -- keys and tokens ---------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def keys() -> dict:
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ed = ed25519.Ed25519PrivateKey.generate()
    jwks = {"keys": [{**jwt.algorithms.RSAAlgorithm.to_jwk(rsa_key.public_key(), as_dict=True), "kid": "rsa-1", "use": "sig", "alg": "RS256"},
                     {**jwt.algorithms.OKPAlgorithm.to_jwk(ed.public_key(), as_dict=True), "kid": "ed-1", "use": "sig", "alg": "EdDSA"}]}
    return {"rsa": rsa_key, "other": other, "ed": ed, "jwks": jwks}


@pytest.fixture(scope="session")
def verifier(keys) -> Verifier:
    return Verifier(jwks=keys["jwks"], issuer=ISSUER)


@pytest.fixture(scope="session")
def mint(keys):
    def token(account: str, *, key: str = "rsa", kid: str | None = None, expires_in: int = 3600, issuer: str = ISSUER) -> str:
        claims = {"sub": account, "iss": issuer, "iat": int(time.time()), "exp": int(time.time()) + expires_in}
        if key == "ed":
            return jwt.encode(claims, keys["ed"], algorithm="EdDSA", headers={"kid": kid or "ed-1"})
        return jwt.encode(claims, keys[key], algorithm="RS256", headers={"kid": kid or "rsa-1"})
    return token


@pytest.fixture()
def who() -> dict:
    tag = uuid.uuid4().hex[:8]
    return {"owner": f"test-owner-{tag}", "reader": f"test-reader-{tag}", "other": f"test-other-{tag}"}


# -- the application -----------------------------------------------------------------------------------------------------------------
@pytest.fixture()
def settings() -> Settings:
    return Settings(repository="memory", chunk_bytes=CHUNK)


@pytest.fixture()
def app(settings, verifier):
    return create_app(settings, verifier=verifier)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# -- an author with a workshop to publish -------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def author(tmp_path_factory):
    folder = tmp_path_factory.mktemp("author")
    store = Store(folder / "lab")
    labworld.build(store, folder / "lab" / "files")
    lab_export.set_public_info(store, {"name": "Open titanium lab", "author": "A. Author", "url": "https://example.org/lab"})
    yield {"store": store, "folder": folder, "origin": lab_export.identity(store)["origin_lab_id"]}
    store.close()


@pytest.fixture()
def origin(author) -> str:
    """The laboratory of each test: the author's origin id (a fresh in-memory catalogue per test; the live tests clean up after each)."""
    return author["origin"]


def exported(author, release_id: str, number: int, terms: str = "CC-BY-4.0") -> bytes:
    path = author["folder"] / f"{release_id}.tcelab"
    lab_export.export(author["store"], path, None, terms, release_id=release_id, release_number=number)
    return path.read_bytes()


def new_lab(client, token, origin: str, visibility="public", **more) -> dict:
    response = client.post("/labs", json={"name": "Open titanium lab", "author": "A. Author", "origin_lab_id": origin, "visibility": visibility, **more},
                           headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


def reserve(client, token, lab_id: str, key: str, previous: str | None = None) -> dict:
    response = client.post(f"/labs/{lab_id}/publications", json={"idempotency_key": key, "expected_previous_release_id": previous}, headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


def declared(data: bytes) -> dict:
    return {"file_sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data), "chunk_count": max(1, -(-len(data) // CHUNK))}


def upload(client, token, pub: dict, data: bytes, tamper: bool = False, declare: dict | None = None) -> dict:
    """Upload the chunks of ``data`` and finalize: the status and body of finalize."""
    pieces = list(split(data, CHUNK))
    for n, piece in enumerate(pieces):
        if tamper and n == min(1, len(pieces) - 1):
            piece = bytes([piece[0] ^ 0x01]) + piece[1:]
        put = client.put(f"/publications/{pub['id']}/chunks/{n}", content=piece, headers={**auth(token), "Content-Type": "application/octet-stream"})
        assert put.status_code == 200, put.text
    response = client.post(f"/publications/{pub['id']}/finalize", json=declare or declared(data), headers=auth(token))
    return {"status": response.status_code, "body": response.json(), "publication": pub, "data": data}


def published(client, token, lab, author, key, previous=None) -> dict:
    """Reserve, export with the reserved identity, upload, finalize: the release and the bytes of its file."""
    pub = reserve(client, token, lab["id"], key, previous)
    data = exported(author, pub["release_id"], pub["release_number"])
    out = upload(client, token, pub, data)
    assert out["status"] == 200, out["body"]
    return {"release": out["body"]["release"], "data": data, "publication": pub}


# -- reading and ownership ---------------------------------------------------------------------------------------------------------
def test_public_catalogue_needs_no_account_and_private_labs_stay_out_of_it(client, mint, who, origin):
    public = new_lab(client, mint(who["owner"]), origin)
    assert public["role"] == "owner" and public["visibility"] == "public"
    listed = [lab for lab in client.get("/labs").json()["labs"] if lab["id"] == public["id"]]
    assert listed and listed[0]["role"] == "public" and listed[0]["latest_release"] is None
    assert client.get(f"/labs/{public['id']}").json()["release_count"] == 0
    # a second laboratory of the same origin is refused; another origin may be private
    again = client.post("/labs", json={"name": "Copy", "author": "A. Author", "origin_lab_id": origin}, headers=auth(mint(who["other"])))
    assert again.status_code == 409 and again.json()["code"] == "origin_taken"
    private = client.post("/labs", json={"name": "Closed lab", "author": "B.", "origin_lab_id": str(uuid.uuid4()), "visibility": "private"},
                          headers=auth(mint(who["owner"]))).json()
    assert private["id"] not in {lab["id"] for lab in client.get("/labs").json()["labs"]}
    assert client.get(f"/labs/{private['id']}").status_code == 404
    assert client.get(f"/labs/{private['id']}", headers=auth(mint(who["reader"]))).status_code == 404
    assert client.get(f"/labs/{private['id']}", headers=auth(mint(who["owner"]))).json()["role"] == "owner"
    assert {public["id"], private["id"]} <= {lab["id"] for lab in client.get("/labs", headers=auth(mint(who["owner"]))).json()["labs"]}


def test_creating_a_lab_needs_a_valid_token_and_plain_text(client, mint, who, origin):
    body = {"name": "Lab", "author": "A.", "origin_lab_id": origin}
    assert client.post("/labs", json=body).status_code == 401
    assert client.post("/labs", json=body, headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.post("/labs", json=body, headers=auth("not.a.jwt")).status_code == 401
    assert client.post("/labs", json=body, headers=auth(mint(who["owner"], expires_in=-120))).json()["code"] == "expired"
    assert client.post("/labs", json=body, headers=auth(mint(who["owner"], key="other"))).status_code == 401       # wrong signature, known kid
    assert client.post("/labs", json=body, headers=auth(mint(who["owner"], kid="nobody"))).json()["code"] == "unknown_key"
    assert client.post("/labs", json=body, headers=auth(mint(who["owner"], issuer="https://elsewhere.test"))).status_code == 401
    unsafe = client.post("/labs", json={**body, "name": "see /Users/me/secret"}, headers=auth(mint(who["owner"])))
    assert unsafe.status_code == 422 and unsafe.json()["code"] == "text"
    assert client.post("/labs", json={**body, "url": "javascript:alert(1)"}, headers=auth(mint(who["owner"]))).status_code == 422
    assert client.post("/labs", json={**body, "origin_lab_id": "not-a-uuid"}, headers=auth(mint(who["owner"]))).status_code == 422
    assert client.post("/labs", json=body, headers=auth(mint(who["owner"], key="ed"))).status_code == 201            # EdDSA, as Neon Auth signs


# -- publication -------------------------------------------------------------------------------------------------------------------
def test_a_release_is_published_in_chunks_and_read_back_whole_without_an_account(client, mint, who, author, origin, tmp_path):
    token = mint(who["owner"])
    lab = new_lab(client, token, origin)
    made = published(client, token, lab, author, "k1")
    release, data = made["release"], made["data"]
    assert release["number"] == 1 and release["lab_id"] == lab["id"] and release["previous_release_id"] is None
    assert release["byte_size"] == len(data) and release["file_sha256"] == hashlib.sha256(data).hexdigest()
    assert release["chunk_count"] == declared(data)["chunk_count"] > 1
    assert release["counts"]["measurements"] > 0 and release["terms"] == "CC-BY-4.0" and release["attribution"]["name"] == "A. Author"
    shown = client.get(f"/releases/{release['id']}/manifest").json()
    assert shown["manifest"]["content_sha256"] == release["content_sha256"] and shown["lab"]["name"] == "Open titanium lab"
    assert shown["laboratory"]["role"] == "public" and shown["release"]["usage_terms"] == shown["manifest"]["usage_terms"]
    assert client.get(f"/labs/{lab['id']}").json()["latest_release"]["id"] == release["id"]
    assert [r["id"] for r in client.get(f"/labs/{lab['id']}/releases").json()["releases"]] == [release["id"]]
    chunks = []
    for n in range(release["chunk_count"]):
        got = client.get(f"/releases/{release['id']}/chunks/{n}")
        assert got.status_code == 200 and got.headers["X-Chunk-Count"] == str(release["chunk_count"])
        assert "immutable" in got.headers["Cache-Control"]
        chunks.append(got.content)
    assert b"".join(chunks) == data
    assert client.get(f"/releases/{release['id']}/chunks/{release['chunk_count']}").status_code == 404
    # another workshop connects what it downloaded, as the desktop importer does
    reader = Store(tmp_path / "reader")
    try:
        job = lab_import.start(reader, lab_import.stage(reader, chunks), origin="cloud", url=f"/releases/{release['id']}", verified=True, wait=True)
        assert job["done"] and job["error"] is None, job
        snapshot = lab_import.reader(reader, release["id"], [])
        assert snapshot.one("SELECT count(*) AS n FROM observation")["n"] == release["counts"]["measurements"]
        assert lab_import.sources(reader)[0]["name"] == "Open titanium lab"
    finally:
        reader.close()


def test_an_incomplete_or_tampered_publication_is_never_visible(client, mint, who, author, origin):
    token = mint(who["owner"])
    lab = new_lab(client, token, origin)
    pub = reserve(client, token, lab["id"], "k")
    data = exported(author, pub["release_id"], pub["release_number"])
    pieces = list(split(data, CHUNK))
    assert len(pieces) > 2
    assert client.put(f"/publications/{pub['id']}/chunks/0", content=pieces[0], headers=auth(token)).status_code == 200
    assert client.get(f"/labs/{lab['id']}/releases").json()["releases"] == []
    assert client.get(f"/releases/{pub['release_id']}/manifest").status_code == 404
    early = client.post(f"/publications/{pub['id']}/finalize", json=declared(data), headers=auth(token))
    assert early.status_code == 422 and early.json()["code"] == "chunks_missing"
    assert client.get(f"/publications/{pub['id']}", headers=auth(token)).json()["chunks_received"] == [0]
    assert client.get(f"/publications/{pub['id']}", headers=auth(mint(who["other"]))).status_code == 404
    # a chunk above the limit, an empty one, one far outside the range, one by someone else
    big = client.put(f"/publications/{pub['id']}/chunks/1", content=b"x" * (CHUNK + 1), headers=auth(token))
    assert big.status_code == 413 and big.json()["code"] == "chunk_bytes"
    assert client.put(f"/publications/{pub['id']}/chunks/1", content=b"", headers=auth(token)).status_code == 422
    assert client.put(f"/publications/{pub['id']}/chunks/99999999", content=b"x", headers=auth(token)).status_code == 404
    assert client.put(f"/publications/{pub['id']}/chunks/1", content=pieces[1], headers=auth(mint(who["other"]))).status_code == 404
    # a chunk of the wrong size is found at finalize
    short = client.put(f"/publications/{pub['id']}/chunks/1", content=pieces[1][:-1], headers=auth(token))
    assert short.status_code == 200
    for n, piece in enumerate(pieces[2:], start=2):
        client.put(f"/publications/{pub['id']}/chunks/{n}", content=piece, headers=auth(token))
    wrong = client.post(f"/publications/{pub['id']}/finalize", json=declared(data), headers=auth(token))
    assert wrong.status_code == 422 and wrong.json()["code"] == "chunk_size"
    # tampered content fails on finalize and leaves nothing behind
    out = upload(client, token, pub, data, tamper=True)
    assert out["status"] == 422 and out["body"]["code"] in ("hash", "file_hash", "canonical", "schema", "framing", "encoding", "json"), out["body"]
    assert client.get(f"/labs/{lab['id']}/releases").json()["releases"] == []
    assert client.get(f"/releases/{pub['release_id']}/manifest").status_code == 404
    # a wrong declaration too
    lie = upload(client, token, pub, data, declare={**declared(data), "file_sha256": "f" * 64})
    assert lie["status"] == 422 and lie["body"]["code"] == "file_hash"
    # the right chunks mend it: the same publication finalizes, and nothing changes it afterwards
    out = upload(client, token, pub, data)
    assert out["status"] == 200 and out["body"]["release"]["id"] == pub["release_id"]
    assert client.put(f"/publications/{pub['id']}/chunks/0", content=pieces[0], headers=auth(token)).status_code == 409
    other = client.post(f"/publications/{pub['id']}/finalize", json={**declared(data), "byte_size": len(data) + 1, "chunk_count": declared(data)["chunk_count"]},
                        headers=auth(token))
    assert other.status_code == 409 and other.json()["code"] == "finalized"


def test_a_release_of_another_laboratory_or_identity_is_refused(client, mint, who, author, origin):
    token = mint(who["owner"])
    lab = new_lab(client, token, origin)
    pub = reserve(client, token, lab["id"], "k-id")
    out = upload(client, token, pub, exported(author, str(uuid.uuid4()), pub["release_number"]))        # not the reserved release id
    assert out["status"] == 422 and out["body"]["code"] == "release_id"
    pub = reserve(client, token, lab["id"], "k-number")
    out = upload(client, token, pub, exported(author, pub["release_id"], 7))                             # not the reserved number
    assert out["status"] == 422 and out["body"]["code"] == "release_number"
    other = client.post("/labs", json={"name": "Open titanium lab", "author": "A. Author", "origin_lab_id": str(uuid.uuid4())}, headers=auth(token)).json()
    pub = reserve(client, token, other["id"], "k-origin")
    out = upload(client, token, pub, exported(author, pub["release_id"], pub["release_number"]))         # another laboratory's file
    assert out["status"] == 422 and out["body"]["code"] == "lab_mismatch"
    assert client.get(f"/labs/{other['id']}/releases").json()["releases"] == []
    renamed = client.post("/labs", json={"name": "Other name", "author": "A. Author", "origin_lab_id": str(uuid.uuid4())}, headers=auth(token)).json()
    assert client.get(f"/labs/{renamed['id']}").json()["release_count"] == 0


def test_the_same_idempotency_key_returns_the_same_publication_and_finalize_repeats_harmlessly(client, mint, who, author, origin):
    token = mint(who["owner"])
    lab = new_lab(client, token, origin)
    first = reserve(client, token, lab["id"], "same")
    again = reserve(client, token, lab["id"], "same")
    assert again["id"] == first["id"] and again["release_id"] == first["release_id"]
    made = published(client, token, lab, author, "k")
    repeat = client.post(f"/publications/{made['publication']['id']}/finalize", json=declared(made["data"]), headers=auth(token)).json()
    assert repeat["repeated"] is True and repeat["release"]["id"] == made["release"]["id"]
    assert len(client.get(f"/labs/{lab['id']}/releases").json()["releases"]) == 1
    # the key is the owner's: another account's key of the same text is another publication
    elsewhere = client.post("/labs", json={"name": "Lab 2", "author": "O.", "origin_lab_id": str(uuid.uuid4())}, headers=auth(mint(who["other"]))).json()
    theirs = reserve(client, mint(who["other"]), elsewhere["id"], "same")
    assert theirs["id"] != first["id"]
    # and a key reused for another laboratory of the same owner is refused
    second = client.post("/labs", json={"name": "Lab 3", "author": "A. Author", "origin_lab_id": str(uuid.uuid4())}, headers=auth(token)).json()
    reused = client.post(f"/labs/{second['id']}/publications", json={"idempotency_key": "same"}, headers=auth(token))
    assert reused.status_code == 409 and reused.json()["code"] == "idempotency_key"


def test_the_expected_previous_release_is_checked_and_numbers_stay_sequential(client, mint, who, author, origin):
    token = mint(who["owner"])
    lab = new_lab(client, token, origin)
    r1 = published(client, token, lab, author, "one")["release"]
    stale = client.post(f"/labs/{lab['id']}/publications", json={"idempotency_key": "stale", "expected_previous_release_id": None}, headers=auth(token))
    assert stale.status_code == 409 and stale.json()["code"] == "expected_previous"
    # two publishers reserve against the same latest: both get number 2; the second to finalize is refused
    a = reserve(client, token, lab["id"], "a", r1["id"])
    b = reserve(client, token, lab["id"], "b", r1["id"])
    assert a["release_number"] == b["release_number"] == 2 and a["release_id"] != b["release_id"]
    data_a = exported(author, a["release_id"], 2)
    data_b = exported(author, b["release_id"], 2)
    done_a = upload(client, token, a, data_a)
    assert done_a["status"] == 200 and done_a["body"]["release"]["number"] == 2 and done_a["body"]["release"]["previous_release_id"] == r1["id"]
    done_b = upload(client, token, b, data_b)
    assert done_b["status"] == 409 and done_b["body"]["code"] == "expected_previous"
    assert client.post(f"/publications/{b['id']}/finalize", json=declared(data_b), headers=auth(token)).status_code == 409
    assert [r["number"] for r in client.get(f"/labs/{lab['id']}/releases").json()["releases"]] == [2, 1]
    r3 = published(client, token, lab, author, "three", done_a["body"]["release"]["id"])["release"]
    assert r3["number"] == 3 and client.get(f"/labs/{lab['id']}").json()["latest_release"]["id"] == r3["id"]


def test_an_expired_upload_is_gone(mint, who, origin, verifier, settings):
    app = create_app(Settings(repository=settings.repository, database_url=settings.database_url, chunk_bytes=CHUNK, upload_lifetime_s=-5),
                     verifier=verifier)
    with TestClient(app) as client:
        token = mint(who["owner"])
        lab = new_lab(client, token, origin)
        pub = reserve(client, token, lab["id"], "k")
        gone = client.put(f"/publications/{pub['id']}/chunks/0", content=b"x", headers=auth(token))
        assert gone.status_code == 410 and gone.json()["code"] == "expired"
        assert client.post(f"/publications/{pub['id']}/finalize", json={"file_sha256": "0" * 64, "byte_size": 1, "chunk_count": 1},
                           headers=auth(token)).status_code == 410


def test_a_release_above_the_policy_or_with_the_wrong_chunk_count_is_refused(client, mint, who, origin):
    token = mint(who["owner"])
    lab = new_lab(client, token, origin)
    pub = reserve(client, token, lab["id"], "big")
    client.put(f"/publications/{pub['id']}/chunks/0", content=b"x", headers=auth(token))
    too_big = client.post(f"/publications/{pub['id']}/finalize", json={"file_sha256": "0" * 64, "byte_size": lf.DEFAULT_POLICY.max_bytes + 1, "chunk_count": 1},
                          headers=auth(token))
    assert too_big.status_code == 413
    wrong = client.post(f"/publications/{pub['id']}/finalize", json={"file_sha256": "0" * 64, "byte_size": CHUNK * 3, "chunk_count": 2}, headers=auth(token))
    assert wrong.status_code == 422 and wrong.json()["code"] == "chunk_count"
    assert client.post(f"/labs/{lab['id']}/publications", json={"idempotency_key": "x"}, headers=auth(mint(who["other"]))).status_code == 403
    assert client.post(f"/labs/{lab['id']}/publications", json={"idempotency_key": "x"}).status_code == 401


# -- withdrawals -------------------------------------------------------------------------------------------------------------------
def test_the_owner_withdraws_a_measurement_and_everyone_who_reads_the_release_sees_it(client, mint, who, author, origin):
    token = mint(who["owner"])
    lab = new_lab(client, token, origin)
    made = published(client, token, lab, author, "w")
    measurement = next(record["id"] for kind, record in clf.read(io.BytesIO(made["data"])) if kind == "measurements")
    body = {"targets": [{"kind": "measurement", "id": measurement}], "reason": "the plate was measured under the wrong light", "idempotency_key": "wd-1"}
    assert client.post(f"/releases/{made['release']['id']}/withdraw", json=body, headers=auth(mint(who["other"]))).status_code == 403
    assert client.post(f"/releases/{made['release']['id']}/withdraw", json=body).status_code == 401
    first = client.post(f"/releases/{made['release']['id']}/withdraw", json=body, headers=auth(token))
    assert first.status_code == 201 and first.json()["withdrawals"][0]["target_id"] == measurement
    again = client.post(f"/releases/{made['release']['id']}/withdraw", json=body, headers=auth(token))
    assert again.json() == first.json()
    seen = client.get(f"/releases/{made['release']['id']}/withdrawals").json()["withdrawals"]
    assert len(seen) == 1 and seen[0]["reason"] == body["reason"] and seen[0]["target_kind"] == "measurement"
    assert client.get(f"/releases/{uuid.uuid4()}/withdrawals").status_code == 404


# -- private laboratories ----------------------------------------------------------------------------------------------------------
def test_a_private_release_is_read_by_invitation_only_and_revocation_ends_it(client, mint, who, author, origin):
    owner, reader, other = mint(who["owner"]), mint(who["reader"]), mint(who["other"])
    lab = new_lab(client, owner, origin, visibility="private")
    made = published(client, owner, lab, author, "p")
    release = made["release"]
    for headers in ({}, auth(reader)):
        assert client.get(f"/labs/{lab['id']}", headers=headers).status_code == 404
        assert client.get(f"/labs/{lab['id']}/releases", headers=headers).status_code == 404
        assert client.get(f"/releases/{release['id']}/manifest", headers=headers).status_code == 404
        assert client.get(f"/releases/{release['id']}/chunks/0", headers=headers).status_code == 404
        assert client.get(f"/releases/{release['id']}/withdrawals", headers=headers).status_code == 404
    assert client.post(f"/labs/{lab['id']}/invitations", json={}, headers=auth(reader)).status_code == 404     # not even the owner's screens
    invited = client.post(f"/labs/{lab['id']}/invitations", json={"expires_in_s": 3600}, headers=auth(owner))
    assert invited.status_code == 201 and invited.json()["token"] in invited.json()["link"]
    token = invited.json()["token"]
    assert client.post(f"/invitations/{token}/accept").status_code == 401
    assert client.post("/invitations/not-a-token/accept", headers=auth(reader)).status_code == 404
    accepted = client.post(f"/invitations/{token}/accept", headers=auth(reader))
    assert accepted.status_code == 200 and accepted.json()["lab"]["role"] == "member"
    assert client.get(f"/labs/{lab['id']}", headers=auth(reader)).json()["role"] == "member"
    assert client.get(f"/releases/{release['id']}/manifest", headers=auth(reader)).status_code == 200
    got = client.get(f"/releases/{release['id']}/chunks/0", headers=auth(reader))
    assert got.status_code == 200 and "no-store" in got.headers["Cache-Control"]
    assert lab["id"] in {lab_["id"] for lab_ in client.get("/labs", headers=auth(reader)).json()["labs"]}
    assert client.post(f"/invitations/{token}/accept", headers=auth(reader)).status_code == 200              # the same person, again: fine
    used = client.post(f"/invitations/{token}/accept", headers=auth(other))
    assert used.status_code == 410 and used.json()["code"] == "used"
    # a member reads, never changes
    assert client.post(f"/labs/{lab['id']}/publications", json={"idempotency_key": "m"}, headers=auth(reader)).status_code == 403
    assert client.post(f"/releases/{release['id']}/withdraw", json={"targets": [{"kind": "release", "id": release["id"]}], "reason": "x"},
                       headers=auth(reader)).status_code == 403
    members = client.get(f"/labs/{lab['id']}/members", headers=auth(owner)).json()["members"]
    assert [m["account_id"] for m in members] == [who["reader"]]
    assert client.get(f"/labs/{lab['id']}/members", headers=auth(reader)).status_code == 403
    listed = client.get(f"/labs/{lab['id']}/invitations", headers=auth(owner)).json()["invitations"]
    assert listed[0]["accepted_by"] == who["reader"] and "token" not in listed[0] and "token_hash" not in listed[0]
    # removal ends access on the next request
    assert client.delete(f"/labs/{lab['id']}/members/{who['reader']}", headers=auth(owner)).status_code == 204
    assert client.get(f"/releases/{release['id']}/manifest", headers=auth(reader)).status_code == 404
    assert client.get(f"/labs/{lab['id']}", headers=auth(reader)).status_code == 404
    assert client.delete(f"/labs/{lab['id']}/members/{who['reader']}", headers=auth(owner)).status_code == 404
    # a revoked invitation cannot be accepted; an expired one neither
    second = client.post(f"/labs/{lab['id']}/invitations", json={}, headers=auth(owner)).json()
    assert client.delete(f"/labs/{lab['id']}/invitations/{second['id']}", headers=auth(owner)).status_code == 204
    revoked = client.post(f"/invitations/{second['token']}/accept", headers=auth(other))
    assert revoked.status_code == 410 and revoked.json()["code"] == "revoked"
    assert client.delete(f"/labs/{lab['id']}/invitations/{second['id']}", headers=auth(reader)).status_code == 404


def test_the_catalogue_shows_what_the_release_file_declares(client, mint, who, author, origin):
    token = mint(who["owner"])
    lab = new_lab(client, token, origin)
    made = published(client, token, lab, author, "d")
    path = author["folder"] / "check.tcelab"
    path.write_bytes(made["data"])
    manifest = lf.peek_manifest(path)
    assert made["release"]["content_sha256"] == manifest["content_sha256"] and made["release"]["counts"] == manifest["counts"]
    assert made["release"]["usage_terms"] == manifest["usage_terms"] and made["release"]["schema_version"] == manifest["schema_version"]
    assert made["release"]["id"] == manifest["release_id"] and made["release"]["number"] == manifest["release_number"]
