"""Where the catalogue lives (DEC-058): the same operations over an in-memory store (tests, the local smoke) and over Postgres on Neon
(the service). Rows are plain dicts; identities are UUID strings; times are UTC ISO-8601 strings ending in ``Z``.

The Postgres repository connects as the non-privileged role ``app_api`` and sets ``app.account_id`` for the connection, so that the
row-level security policies of ``cloud/migrations`` see the same account the API checked; the owner role is used by migrations only.
"""
from __future__ import annotations

import contextlib
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping, Protocol

from .errors import Conflict, Gone, Invalid, NotFound

STATES = ("uploading", "finalized", "failed", "expired")


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(moment: datetime | None = None) -> str:
    moment = moment or now()
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def moment(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def new_id() -> str:
    return str(uuid.uuid4())


class Repository(Protocol):
    """Every operation the routes need; ``viewer`` is the account id of the caller or None."""

    def labs(self, viewer: str | None) -> list[dict]: ...
    def lab(self, lab_id: str, viewer: str | None) -> dict | None: ...
    def role(self, lab: Mapping, viewer: str | None) -> str | None: ...
    def create_lab(self, fields: Mapping) -> dict: ...
    def releases(self, lab_id: str) -> list[dict]: ...
    def release(self, release_id: str) -> dict | None: ...
    def latest(self, lab_id: str) -> dict | None: ...
    def chunk(self, release_id: str, n: int) -> bytes | None: ...
    def withdrawals(self, release_id: str) -> list[dict]: ...
    def add_withdrawals(self, release_id: str, rows: list[dict]) -> list[dict]: ...
    def idempotent(self, account: str, key: str, operation: str) -> tuple[int, Any] | None: ...
    def remember(self, account: str, key: str, operation: str, status: int, body: Any) -> None: ...
    def reserve(self, fields: Mapping) -> dict: ...
    def publication(self, publication_id: str) -> dict | None: ...
    def put_chunk(self, publication_id: str, n: int, data: bytes) -> None: ...
    def chunk_sizes(self, publication_id: str) -> dict[int, int]: ...
    def publication_chunks(self, publication_id: str, count: int) -> Iterator[bytes]: ...
    def finalize(self, publication_id: str, validated: Mapping) -> dict: ...
    def fail(self, publication_id: str, state: str, reason: str) -> None: ...
    def create_invitation(self, fields: Mapping) -> dict: ...
    def invitations(self, lab_id: str) -> list[dict]: ...
    def revoke_invitation(self, lab_id: str, invitation_id: str) -> bool: ...
    def accept_invitation(self, token_hash: str, account: str) -> dict: ...
    def members(self, lab_id: str) -> list[dict]: ...
    def remove_member(self, lab_id: str, account: str) -> bool: ...
    def close(self) -> None: ...


# -- in memory --------------------------------------------------------------------------------------------------------------------
class InMemoryRepository:
    """The catalogue in dictionaries, shared by every request of one application; one lock keeps reserve and finalize serial."""

    def __init__(self):
        self.lock = threading.RLock()
        self._labs: dict[str, dict] = {}
        self._releases: dict[str, dict] = {}
        self._chunks: dict[tuple[str, int], bytes] = {}
        self._publications: dict[str, dict] = {}
        self._pub_chunks: dict[tuple[str, int], bytes] = {}
        self._withdrawals: list[dict] = []
        self._invitations: dict[str, dict] = {}
        self._members: dict[tuple[str, str], dict] = {}
        self._idempotency: dict[tuple[str, str, str], tuple[int, Any]] = {}

    def close(self) -> None:
        pass

    def role(self, lab: Mapping, viewer: str | None) -> str | None:
        if viewer is not None and lab["owner_id"] == viewer:
            return "owner"
        if viewer is not None and (lab["id"], viewer) in self._members:
            return "member"
        return "public" if lab["visibility"] == "public" else None

    def labs(self, viewer):
        with self.lock:
            return [dict(lab) for lab in self._labs.values() if self.role(lab, viewer)]

    def lab(self, lab_id, viewer):
        with self.lock:
            lab = self._labs.get(lab_id)
            return dict(lab) if lab is not None and self.role(lab, viewer) else None

    def create_lab(self, fields):
        with self.lock:
            if any(lab["origin_lab_id"] == fields["origin_lab_id"] for lab in self._labs.values()):
                raise Conflict("a laboratory with this origin id is in the catalogue already", "origin_taken")
            lab = {"id": new_id(), "created_at": stamp(), **fields}
            self._labs[lab["id"]] = lab
            return dict(lab)

    def releases(self, lab_id):
        with self.lock:
            return sorted((dict(r) for r in self._releases.values() if r["lab_id"] == lab_id), key=lambda r: -r["number"])

    def release(self, release_id):
        with self.lock:
            found = self._releases.get(release_id)
            return dict(found) if found else None

    def latest(self, lab_id):
        found = self.releases(lab_id)
        return found[0] if found else None

    def chunk(self, release_id, n):
        return self._chunks.get((release_id, n))

    def withdrawals(self, release_id):
        with self.lock:
            return [dict(w) for w in self._withdrawals if w["release_id"] == release_id]

    def add_withdrawals(self, release_id, rows):
        with self.lock:
            made = []
            for row in rows:
                made.append({"id": len(self._withdrawals) + 1, "release_id": release_id, "created_at": stamp(), **row})
                self._withdrawals.append(made[-1])
            return [dict(w) for w in made]

    def idempotent(self, account, key, operation):
        return self._idempotency.get((account, key, operation))

    def remember(self, account, key, operation, status, body):
        self._idempotency.setdefault((account, key, operation), (status, body))

    def reserve(self, fields):
        with self.lock:
            for pub in self._publications.values():
                if pub["owner_id"] == fields["owner_id"] and pub["idempotency_key"] == fields["idempotency_key"]:
                    return dict(pub)
            latest = self.latest(fields["lab_id"])
            latest_id = latest["id"] if latest else None
            if fields["expected_previous_release_id"] != latest_id:
                raise Conflict("the laboratory's latest release is not the one expected: another release was published", "expected_previous")
            pub = {"id": new_id(), "release_id": new_id(), "release_number": (latest["number"] + 1) if latest else 1, "state": "uploading",
                   "failure": None, "file_sha256": None, "byte_size": None, "chunk_count": None, "created_at": stamp(), **fields}
            self._publications[pub["id"]] = pub
            return dict(pub)

    def publication(self, publication_id):
        with self.lock:
            found = self._publications.get(publication_id)
            return dict(found) if found else None

    def put_chunk(self, publication_id, n, data):
        with self.lock:
            self._pub_chunks[(publication_id, n)] = bytes(data)

    def chunk_sizes(self, publication_id):
        with self.lock:
            return {n: len(b) for (p, n), b in self._pub_chunks.items() if p == publication_id}

    def publication_chunks(self, publication_id, count):
        for n in range(count):
            piece = self._pub_chunks.get((publication_id, n))
            if piece is None:
                raise Invalid(f"chunk {n} was not uploaded", "chunks_missing")
            yield piece

    def finalize(self, publication_id, validated):
        with self.lock:
            pub = self._publications[publication_id]
            if pub["state"] == "finalized":
                return dict(self._releases[pub["release_id"]])
            latest = self.latest(pub["lab_id"])
            if (latest["id"] if latest else None) != pub["expected_previous_release_id"]:
                raise Conflict("another release was published since this publication was reserved", "expected_previous")
            release = {"id": pub["release_id"], "lab_id": pub["lab_id"], "number": pub["release_number"], "chunk_bytes": pub["chunk_bytes"],
                       "previous_release_id": pub["expected_previous_release_id"], "published_at": stamp(),
                       **{k: validated[k] for k in ("manifest", "lab", "counts", "content_sha256", "terms", "byte_size", "file_sha256", "chunk_count")}}
            for n in range(validated["chunk_count"]):
                self._chunks[(release["id"], n)] = self._pub_chunks.pop((publication_id, n))
            self._releases[release["id"]] = release
            pub.update(state="finalized", file_sha256=validated["file_sha256"], byte_size=validated["byte_size"], chunk_count=validated["chunk_count"])
            return dict(release)

    def fail(self, publication_id, state, reason):
        with self.lock:
            pub = self._publications[publication_id]
            if pub["state"] == "uploading":
                pub["state"], pub["failure"] = state, reason

    def create_invitation(self, fields):
        with self.lock:
            invitation = {"id": new_id(), "created_at": stamp(), "accepted_by": None, "accepted_at": None, "revoked_at": None, **fields}
            self._invitations[invitation["id"]] = invitation
            return dict(invitation)

    def invitations(self, lab_id):
        with self.lock:
            return [dict(i) for i in self._invitations.values() if i["lab_id"] == lab_id]

    def revoke_invitation(self, lab_id, invitation_id):
        with self.lock:
            found = self._invitations.get(invitation_id)
            if found is None or found["lab_id"] != lab_id:
                return False
            found["revoked_at"] = found["revoked_at"] or stamp()
            return True

    def accept_invitation(self, token_hash, account):
        with self.lock:
            found = next((i for i in self._invitations.values() if i["token_hash"] == token_hash), None)
            return _accept(found, account, self._members)

    def members(self, lab_id):
        with self.lock:
            return [dict(m) for (lab, _), m in self._members.items() if lab == lab_id]

    def remove_member(self, lab_id, account):
        with self.lock:
            return self._members.pop((lab_id, account), None) is not None


def _accept(invitation: dict | None, account: str, members: dict) -> dict:
    """The one-time semantics of an invitation, shared by the in-memory store and the SQL function."""
    if invitation is None:
        raise NotFound("there is no such invitation", "not_found")
    if invitation["revoked_at"]:
        raise Gone("the invitation was revoked", "revoked")
    if moment(invitation["expires_at"]) < now():
        raise Gone("the invitation expired", "expired")
    if invitation["accepted_by"] and invitation["accepted_by"] != account:
        raise Gone("the invitation was used by someone else", "used")
    invitation["accepted_by"], invitation["accepted_at"] = account, invitation["accepted_at"] or stamp()
    member = members.setdefault((invitation["lab_id"], account),
                                {"lab_id": invitation["lab_id"], "account_id": account, "via_invitation": invitation["id"], "created_at": stamp()})
    return dict(member)


# -- Postgres ---------------------------------------------------------------------------------------------------------------------
LAB_COLUMNS = "id, owner_id, origin_lab_id, name, author, description, url, visibility, created_at"
RELEASE_COLUMNS = ("id, lab_id, number, content_sha256, file_sha256, manifest, lab_record AS lab, byte_size, chunk_count, chunk_bytes, counts, terms, "
                   "previous_release_id, published_at")
PUBLICATION_COLUMNS = ("id, lab_id, owner_id, idempotency_key, release_id, release_number, expected_previous_release_id, file_sha256, byte_size, "
                       "chunk_count, chunk_bytes, state, failure, created_at, expires_at")
INVITATION_COLUMNS = "id, lab_id, token_hash, created_by, created_at, expires_at, accepted_by, accepted_at, revoked_at"


def _plain(row: Mapping | None) -> dict | None:
    """A row as the API gives it: UUIDs and times as strings, memoryviews as bytes."""
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif isinstance(value, datetime):
            value = stamp(value)
        elif isinstance(value, memoryview):
            value = value.tobytes()
        out[key] = value
    return out


class PostgresRepository:
    """One connection per request as ``app_api`` with the caller's account set for the policies."""

    def __init__(self, url: str, account: str | None):
        import psycopg
        from psycopg.rows import dict_row
        self._psycopg = psycopg
        self.conn = psycopg.connect(url, row_factory=dict_row, autocommit=False)
        self.account = account

    @contextlib.contextmanager
    def _tx(self):
        """One transaction with the caller's account set for the policies. The account is set locally in every transaction, not once per
        session, because Neon's pooler hands the connection on between transactions and a session setting would not survive."""
        with self.conn.transaction():
            self.conn.execute("SELECT set_config('app.account_id', %s, true)", (self.account or "",))
            yield

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def _one(self, sql: str, params=()) -> dict | None:
        with self._tx():
            return _plain(self.conn.execute(sql, params).fetchone())

    def _all(self, sql: str, params=()) -> list[dict]:
        with self._tx():
            return [_plain(r) for r in self.conn.execute(sql, params).fetchall()]

    def _json(self, value):
        from psycopg.types.json import Jsonb
        return Jsonb(value)

    def role(self, lab, viewer):
        if viewer is not None and lab["owner_id"] == viewer:
            return "owner"
        if viewer is not None and self._one("SELECT 1 AS m FROM membership WHERE lab_id=%s AND account_id=%s", (lab["id"], viewer)):
            return "member"
        return "public" if lab["visibility"] == "public" else None

    def labs(self, viewer):
        return self._all(f"SELECT {LAB_COLUMNS} FROM lab ORDER BY created_at, id")          # the policy shows what the viewer may see

    def lab(self, lab_id, viewer):
        return self._one(f"SELECT {LAB_COLUMNS} FROM lab WHERE id=%s", (lab_id,))

    def create_lab(self, fields):
        try:
            return self._one(f"INSERT INTO lab(id, owner_id, origin_lab_id, name, author, description, url, visibility) "
                             f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING {LAB_COLUMNS}",
                             (new_id(), fields["owner_id"], fields["origin_lab_id"], fields["name"], fields["author"], fields.get("description"),
                              fields.get("url"), fields["visibility"]))
        except self._psycopg.errors.UniqueViolation:
            raise Conflict("a laboratory with this origin id is in the catalogue already", "origin_taken") from None

    def releases(self, lab_id):
        return self._all(f"SELECT {RELEASE_COLUMNS} FROM release WHERE lab_id=%s ORDER BY number DESC", (lab_id,))

    def release(self, release_id):
        return self._one(f"SELECT {RELEASE_COLUMNS} FROM release WHERE id=%s", (release_id,))

    def latest(self, lab_id):
        return self._one(f"SELECT {RELEASE_COLUMNS} FROM release WHERE lab_id=%s ORDER BY number DESC LIMIT 1", (lab_id,))

    def chunk(self, release_id, n):
        row = self._one("SELECT bytes FROM chunk WHERE release_id=%s AND n=%s", (release_id, n))
        return None if row is None else row["bytes"]

    def withdrawals(self, release_id):
        return self._all("SELECT id, release_id, target_kind, target_id, reason, replacement_release_id, created_at FROM release_withdrawal "
                         "WHERE release_id=%s ORDER BY id", (release_id,))

    def add_withdrawals(self, release_id, rows):
        made = []
        with self._tx():
            for row in rows:
                made.append(_plain(self.conn.execute(
                    "INSERT INTO release_withdrawal(release_id, target_kind, target_id, reason, replacement_release_id) VALUES (%s,%s,%s,%s,%s) "
                    "RETURNING id, release_id, target_kind, target_id, reason, replacement_release_id, created_at",
                    (release_id, row["target_kind"], row["target_id"], row["reason"], row.get("replacement_release_id"))).fetchone()))
        return made

    def idempotent(self, account, key, operation):
        row = self._one("SELECT status, response FROM idempotency WHERE account_id=%s AND key=%s AND operation=%s", (account, key, operation))
        return None if row is None else (row["status"], row["response"])

    def remember(self, account, key, operation, status, body):
        with self._tx():
            self.conn.execute("INSERT INTO idempotency(account_id, key, operation, status, response) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                              (account, key, operation, status, self._json(body)))

    def reserve(self, fields):
        with self._tx():
            found = self.conn.execute(f"SELECT {PUBLICATION_COLUMNS} FROM publication WHERE owner_id=%s AND idempotency_key=%s",
                                      (fields["owner_id"], fields["idempotency_key"])).fetchone()
            if found:
                return _plain(found)
            self.conn.execute("SELECT id FROM lab WHERE id=%s FOR UPDATE", (fields["lab_id"],))
            latest = self.conn.execute("SELECT id, number FROM release WHERE lab_id=%s ORDER BY number DESC LIMIT 1", (fields["lab_id"],)).fetchone()
            latest_id = str(latest["id"]) if latest else None
            if fields["expected_previous_release_id"] != latest_id:
                raise Conflict("the laboratory's latest release is not the one expected: another release was published", "expected_previous")
            return _plain(self.conn.execute(
                "INSERT INTO publication(id, lab_id, owner_id, idempotency_key, release_id, release_number, expected_previous_release_id, "
                "chunk_bytes, state, expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'uploading',%s) "
                f"RETURNING {PUBLICATION_COLUMNS}",
                (new_id(), fields["lab_id"], fields["owner_id"], fields["idempotency_key"], new_id(), (latest["number"] + 1) if latest else 1,
                 fields["expected_previous_release_id"], fields["chunk_bytes"], moment(fields["expires_at"]))).fetchone())

    def publication(self, publication_id):
        return self._one(f"SELECT {PUBLICATION_COLUMNS} FROM publication WHERE id=%s", (publication_id,))

    def put_chunk(self, publication_id, n, data):
        with self._tx():
            self.conn.execute("INSERT INTO publication_chunk(publication_id, n, bytes) VALUES (%s,%s,%s) "
                              "ON CONFLICT (publication_id, n) DO UPDATE SET bytes=excluded.bytes", (publication_id, n, bytes(data)))

    def chunk_sizes(self, publication_id):
        return {r["n"]: r["size"] for r in self._all("SELECT n, octet_length(bytes) AS size FROM publication_chunk WHERE publication_id=%s",
                                                     (publication_id,))}

    def publication_chunks(self, publication_id, count):
        for n in range(count):
            row = self._one("SELECT bytes FROM publication_chunk WHERE publication_id=%s AND n=%s", (publication_id, n))
            if row is None:
                raise Invalid(f"chunk {n} was not uploaded", "chunks_missing")
            yield row["bytes"]

    def finalize(self, publication_id, validated):
        with self._tx():
            pub = _plain(self.conn.execute(f"SELECT {PUBLICATION_COLUMNS} FROM publication WHERE id=%s FOR UPDATE", (publication_id,)).fetchone())
            if pub["state"] == "finalized":
                return _plain(self.conn.execute(f"SELECT {RELEASE_COLUMNS} FROM release WHERE id=%s", (pub["release_id"],)).fetchone())
            self.conn.execute("SELECT id FROM lab WHERE id=%s FOR UPDATE", (pub["lab_id"],))
            latest = self.conn.execute("SELECT id FROM release WHERE lab_id=%s ORDER BY number DESC LIMIT 1", (pub["lab_id"],)).fetchone()
            if (str(latest["id"]) if latest else None) != pub["expected_previous_release_id"]:
                raise Conflict("another release was published since this publication was reserved", "expected_previous")
            release = _plain(self.conn.execute(
                "INSERT INTO release(id, lab_id, number, content_sha256, file_sha256, manifest, lab_record, byte_size, chunk_count, chunk_bytes, "
                "counts, terms, previous_release_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                f"RETURNING {RELEASE_COLUMNS}",
                (pub["release_id"], pub["lab_id"], pub["release_number"], validated["content_sha256"], validated["file_sha256"],
                 self._json(validated["manifest"]), self._json(validated["lab"]), validated["byte_size"], validated["chunk_count"], pub["chunk_bytes"],
                 self._json(validated["counts"]), validated["terms"], pub["expected_previous_release_id"])).fetchone())
            self.conn.execute("INSERT INTO chunk(release_id, n, bytes) SELECT %s, n, bytes FROM publication_chunk WHERE publication_id=%s AND n < %s",
                              (pub["release_id"], publication_id, validated["chunk_count"]))
            self.conn.execute("DELETE FROM publication_chunk WHERE publication_id=%s", (publication_id,))
            self.conn.execute("UPDATE publication SET state='finalized', file_sha256=%s, byte_size=%s, chunk_count=%s WHERE id=%s",
                              (validated["file_sha256"], validated["byte_size"], validated["chunk_count"], publication_id))
            return release

    def fail(self, publication_id, state, reason):
        with self._tx():
            self.conn.execute("UPDATE publication SET state=%s, failure=%s WHERE id=%s AND state='uploading'", (state, reason, publication_id))

    def create_invitation(self, fields):
        return self._one("INSERT INTO invitation(id, lab_id, token_hash, created_by, expires_at) VALUES (%s,%s,%s,%s,%s) "
                         f"RETURNING {INVITATION_COLUMNS}",
                         (new_id(), fields["lab_id"], fields["token_hash"], fields["created_by"], moment(fields["expires_at"])))

    def invitations(self, lab_id):
        return self._all(f"SELECT {INVITATION_COLUMNS} FROM invitation WHERE lab_id=%s ORDER BY created_at, id", (lab_id,))

    def revoke_invitation(self, lab_id, invitation_id):
        with self._tx():
            cur = self.conn.execute("UPDATE invitation SET revoked_at=COALESCE(revoked_at, now()) WHERE id=%s AND lab_id=%s", (invitation_id, lab_id))
            return cur.rowcount > 0

    def accept_invitation(self, token_hash, account):
        try:
            with self._tx():
                row = self.conn.execute("SELECT * FROM cloud_accept_invitation(%s, %s)", (token_hash, account)).fetchone()
        except self._psycopg.errors.RaiseException as exc:
            code, _, message = (exc.diag.message_primary or "").partition(":")
            if code == "not_found":
                raise NotFound("there is no such invitation", "not_found") from None
            raise Gone(message.strip() or "the invitation cannot be used", code or "gone") from None
        return _plain(row)

    def members(self, lab_id):
        return self._all("SELECT lab_id, account_id, via_invitation, created_at FROM membership WHERE lab_id=%s ORDER BY created_at", (lab_id,))

    def remove_member(self, lab_id, account):
        with self._tx():
            return self.conn.execute("DELETE FROM membership WHERE lab_id=%s AND account_id=%s", (lab_id, account)).rowcount > 0
