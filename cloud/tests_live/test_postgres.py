"""The contract of the cloud API against the Neon database (every test of ``tests/test_cloud_api.py`` through the Postgres repository,
connecting as ``app_api``), and the row-level security itself: as ``app_api`` without an account, private laboratories and the chunks
of unfinished publications are not there, and an update of another owner's laboratory touches no row. Each test cleans up the rows of
the accounts it made (as the owner role), and only those."""
from __future__ import annotations

import psycopg
import pytest

from conftest import APP_URL, OWNER_URL
from test_cloud_api import *  # noqa: F401,F403  (the fixtures and the tests of the contract)
from test_cloud_api import AUTH_BASE, CHUNK, auth, new_lab, published, reserve
from titanium_cloud.settings import Settings


@pytest.fixture()
def settings() -> Settings:
    return Settings(repository="postgres", database_url=APP_URL, chunk_bytes=CHUNK, auth_base_url=AUTH_BASE)


@pytest.fixture(autouse=True)
def cleanup(who):
    """Delete, as the owner role, everything the test's accounts made; nothing else is touched."""
    yield
    accounts = list(who.values())
    with psycopg.connect(OWNER_URL) as conn:
        labs = "SELECT id FROM lab WHERE owner_id = ANY(%s)"
        releases = f"SELECT id FROM release WHERE lab_id IN ({labs})"
        conn.execute("DELETE FROM idempotency WHERE account_id = ANY(%s)", (accounts,))
        conn.execute(f"DELETE FROM membership WHERE account_id = ANY(%s) OR lab_id IN ({labs})", (accounts, accounts))
        conn.execute(f"DELETE FROM invitation WHERE lab_id IN ({labs})", (accounts,))
        conn.execute(f"DELETE FROM release_withdrawal WHERE release_id IN ({releases})", (accounts,))
        conn.execute(f"DELETE FROM chunk WHERE release_id IN ({releases})", (accounts,))
        conn.execute(f"DELETE FROM publication WHERE lab_id IN ({labs}) OR owner_id = ANY(%s)", (accounts, accounts))
        conn.execute(f"UPDATE release SET previous_release_id = NULL WHERE lab_id IN ({labs})", (accounts,))
        conn.execute(f"DELETE FROM release WHERE lab_id IN ({labs})", (accounts,))
        conn.execute("DELETE FROM lab WHERE owner_id = ANY(%s)", (accounts,))
        conn.execute("DELETE FROM auth_handoff WHERE expires_at < now()")        # the handoff tests spend their codes; this sweeps expired ones
        conn.commit()


def as_app_api(account: str | None):
    return psycopg.connect(APP_URL), account


def query(api, sql: str, *params, rollback: bool = False):
    """One statement as ``app_api`` with the account set inside the transaction (the pooler keeps no session state): the cursor."""
    conn, account = api
    with conn.transaction(force_rollback=rollback):
        conn.execute("SELECT set_config('app.account_id', %s, true)", (account or "",))
        cur = conn.execute(sql, params)
        rows = cur.fetchall() if cur.description else None
    return cur.rowcount, rows


def count(api, sql: str, *params) -> int:
    return query(api, sql, *params)[1][0][0]


def changed(api, sql: str, *params) -> int:
    return query(api, sql, *params, rollback=True)[0]


def test_rls_hides_private_laboratories_from_the_api_role_without_an_account(client, mint, who, author, origin):
    owner = mint(who["owner"])
    private = new_lab(client, owner, origin, visibility="private")
    public = client.post("/labs", json={"name": "Open", "author": "A. Author", "origin_lab_id": str(uuid.uuid4())}, headers=auth(owner)).json()
    release = published(client, owner, private, author, "p")["release"]
    anon, other, me = as_app_api(None), as_app_api(who["other"]), as_app_api(who["owner"])
    try:
        assert count(anon, "SELECT count(*) FROM lab WHERE id=%s", private["id"]) == 0
        assert count(other, "SELECT count(*) FROM lab WHERE id=%s", private["id"]) == 0
        assert count(me, "SELECT count(*) FROM lab WHERE id=%s", private["id"]) == 1
        assert count(anon, "SELECT count(*) FROM lab WHERE id=%s", public["id"]) == 1
        assert count(anon, "SELECT count(*) FROM release WHERE id=%s", release["id"]) == 0
        assert count(anon, "SELECT count(*) FROM chunk WHERE release_id=%s", release["id"]) == 0
        assert count(me, "SELECT count(*) FROM chunk WHERE release_id=%s", release["id"]) == release["chunk_count"]
        assert count(anon, "SELECT count(*) FROM membership WHERE lab_id=%s", private["id"]) == 0
        assert count(anon, "SELECT count(*) FROM invitation WHERE lab_id=%s", private["id"]) == 0
    finally:
        for api in (anon, other, me):
            api[0].close()


def test_rls_keeps_another_owners_laboratory_and_uploads_out_of_reach(client, mint, who, author, origin):
    owner = mint(who["owner"])
    lab = new_lab(client, owner, origin)
    made = published(client, owner, lab, author, "p")
    pub = reserve(client, owner, lab["id"], "open", made["release"]["id"])
    client.put(f"/publications/{pub['id']}/chunks/0", content=b"x" * 10, headers=auth(owner))
    anon, other, me = as_app_api(None), as_app_api(who["other"]), as_app_api(who["owner"])
    try:
        assert changed(other, "UPDATE lab SET name='Taken over' WHERE id=%s", lab["id"]) == 0
        assert changed(anon, "UPDATE lab SET visibility='private' WHERE id=%s", lab["id"]) == 0
        assert changed(me, "UPDATE lab SET name='Mine to change' WHERE id=%s", lab["id"]) == 1
        assert count(other, "SELECT count(*) FROM publication WHERE id=%s", pub["id"]) == 0
        assert count(other, "SELECT count(*) FROM publication_chunk WHERE publication_id=%s", pub["id"]) == 0
        assert count(me, "SELECT count(*) FROM publication_chunk WHERE publication_id=%s", pub["id"]) == 1
        # the chunks of a public release are read by everyone, as the API serves them without a token
        assert count(anon, "SELECT count(*) FROM chunk WHERE release_id=%s", made["release"]["id"]) == made["release"]["chunk_count"]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            changed(me, "DELETE FROM lab WHERE id=%s", lab["id"])
    finally:
        for api in (anon, other, me):
            api[0].close()
    assert client.get(f"/labs/{lab['id']}").json()["name"] == lab["name"]


def test_the_api_role_inserts_reads_and_deletes_handoffs_but_never_changes_one(client):
    """The handoff tests of the contract ran above through the Postgres repository; here the role's grants: no UPDATE on auth_handoff."""
    anon = as_app_api(None)
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            changed(anon, "UPDATE auth_handoff SET state='taken over' WHERE false")
        assert count(anon, "SELECT count(*) FROM auth_handoff WHERE expires_at < now() - interval '1 day'") == 0     # expired rows are swept
    finally:
        anon[0].close()
