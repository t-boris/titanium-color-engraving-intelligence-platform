"""Sign-in to the cloud of laboratories, owned by the core in both run modes (feature electron, REQ-086, DEC-058).

The core never shows a password form and never sees a password. :func:`start` makes a ``state`` and a PKCE verifier and gives the
screen the address of the cloud's sign-in page with the state, the S256 challenge and this core's loopback callback; the screen opens
it in the operator's browser, where the page signs the operator in with Neon Auth and leaves the session token with the cloud under a
one-time code (``cloud/titanium_cloud/handoff.py``). The browser then comes back to ``GET /api/cloud/callback?state&code``, which the
guard lets through without the desktop session cookie only while that state is pending; :func:`complete` exchanges the code and the
verifier for the session token, asks Neon Auth who it is, and keeps the token in ``<data>/cloud/session.json`` (mode 0600).

Calls to the cloud carry a JWT, not the session token: :func:`jwt` asks Neon Auth's ``GET <auth>/token`` with the session cookie for one
(fifteen minutes, EdDSA, verified by the cloud against the JWKS) and refreshes it a minute before it expires. :func:`sign_out` tells
Neon Auth (best effort) and deletes the file. A sign-in the operator does not finish is forgotten after ten minutes; nothing of the
workshop changes whatever happens here.

The address of the cloud is the setting ``cloud.api_url`` (editable on the network screen); what else the core needs for a sign-in
(Neon Auth's address, the social providers) the cloud tells it at ``GET /auth/config``."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from . import cloud_http
from .cloud_http import CloudError, expect, request
from .db import Store, now

API_URL_SETTING = "cloud.api_url"
DEFAULT_API_URL = "https://titanium-labs-api.vercel.app"      # the production service (cloud/README.md); a setting overrides it
FOLDER, FILE = "cloud", "session.json"
PENDING_S = 600                                               # a sign-in the operator did not finish is forgotten after this
REFRESH_MARGIN_S = 60                                         # a JWT is renewed this long before it expires
SESSION_COOKIE = "__Secure-neon-auth.session_token"           # how Neon Auth (Better Auth) takes the session token on /token and /get-session
AUTH = "the sign-in service"
CALLBACK_PATH = "/api/cloud/callback"                         # api.security lets it through without the desktop cookie while a state is pending

_pending: dict[str, dict] = {}                                # state -> the sign-in waiting for its callback
_tokens: dict[str, tuple[str, float]] = {}                    # data folder -> (JWT, its expiry)
_lock = threading.Lock()


# -- where the cloud is -----------------------------------------------------------------------------------------------------------
def api_url(store: Store) -> str:
    return (store.get_setting(API_URL_SETTING) or DEFAULT_API_URL).rstrip("/")


def set_api_url(store: Store, url) -> dict:
    """Keep the address of the cloud: https, or http on this computer only (a local service under test); empty returns to the default."""
    url = (url or "").strip().rstrip("/") if isinstance(url, str) else None
    if url is None:
        raise CloudError("the address of the cloud is text", code="api_url")
    if url:
        parts = urlsplit(url)
        local = parts.hostname in ("127.0.0.1", "localhost", "::1")
        if parts.scheme not in ("https", "http") or not parts.hostname or parts.query or parts.fragment or (parts.scheme == "http" and not local):
            raise CloudError("the address of the cloud is an https address (http only on this computer)", code="api_url")
    store.set_setting(API_URL_SETTING, url or None)
    store.audit("cloud_api_url_changed", api_url=url or DEFAULT_API_URL)
    return settings(store)


def settings(store: Store) -> dict:
    return {"api_url": api_url(store), "default": DEFAULT_API_URL, "custom": bool(store.get_setting(API_URL_SETTING))}


# -- the file ---------------------------------------------------------------------------------------------------------------------
def session_path(store: Store) -> Path:
    return store.data_dir / FOLDER / FILE


def _read(store: Store) -> dict | None:
    try:
        data = json.loads(session_path(store).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("session_token") and data.get("auth_base_url") else None


def _write(store: Store, data: dict) -> None:
    path = session_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.chmod(path, 0o600)


def _forget(store: Store) -> None:
    try:
        session_path(store).unlink()
    except FileNotFoundError:
        pass
    with _lock:
        _tokens.pop(str(store.data_dir), None)


# -- the sign-in ------------------------------------------------------------------------------------------------------------------
def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def _purge() -> None:
    gone = [state for state, entry in _pending.items() if time.time() - entry["created"] > PENDING_S]
    for state in gone:
        del _pending[state]


def start(store: Store, port: int) -> dict:
    """A new sign-in: the address of the cloud's page for the operator's browser, with this core's callback on ``port``."""
    url = api_url(store)
    config = expect(request("GET", f"{url}/auth/config"), 200)
    if not isinstance(config, dict) or not config.get("auth_base_url"):
        raise CloudError("the cloud does not offer sign-in: it is not configured for it", code="no_auth")
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    with _lock:
        _purge()
        _pending[state] = {"verifier": verifier, "api_url": url, "auth_base_url": config["auth_base_url"].rstrip("/"), "created": time.time()}
    callback = urlunsplit(("http", f"127.0.0.1:{int(port)}", CALLBACK_PATH, "", ""))      # this core's loopback address, never fetched by it
    query = urlencode({"state": state, "challenge": s256(verifier), "callback": callback})
    return {"url": f"{url}/signin?{query}", "state": state, "providers": list(config.get("providers") or []), "expires_in_s": PENDING_S}


def pending(state: str) -> bool:
    """Whether a sign-in with this state waits for its callback (the guard asks before letting the callback through)."""
    with _lock:
        _purge()
        return bool(state) and state in _pending


def cancel(store: Store, state: str | None = None) -> dict:
    """Forget a pending sign-in (or all of them); nothing else changes."""
    with _lock:
        if state:
            _pending.pop(state, None)
        else:
            _pending.clear()
    return account(store)


def complete(store: Store, state: str, code: str) -> dict:
    """The callback: the code and the verifier for the session token, then who signed in; the state is spent by this call."""
    with _lock:
        _purge()
        entry = _pending.pop(state or "", None)
    if entry is None:
        raise CloudError("this sign-in is not expected: start it again from the application", code="unknown_state")
    if not code or len(code) > 256:
        raise CloudError("the sign-in code is missing", code="bad_code")
    exchanged = expect(request("POST", f"{entry['api_url']}/auth/handoff/exchange", body={"state": state, "code": code, "verifier": entry["verifier"]}), 200)
    token = exchanged.get("session_token") if isinstance(exchanged, dict) else None
    if not token:
        raise CloudError("the cloud gave no session for this sign-in: sign in again", code="no_session")
    who = whoami(entry["auth_base_url"], token)
    _write(store, {"api_url": entry["api_url"], "auth_base_url": entry["auth_base_url"], "session_token": token, "account": who, "signed_in_at": now()})
    with _lock:
        _tokens.pop(str(store.data_dir), None)
    store.audit("cloud_signed_in", account=who["id"], api_url=entry["api_url"])
    return account(store)


def whoami(auth_base_url: str, session_token: str) -> dict:
    """The account of a session token, from Neon Auth's ``get-session``: id, name and e-mail (nothing else is kept)."""
    answer = request("GET", f"{auth_base_url}/get-session", headers={"Cookie": f"{SESSION_COOKIE}={session_token}"}, where=AUTH)
    data = expect(answer, 200, where=AUTH)
    user = data.get("user") if isinstance(data, dict) else None
    if not isinstance(user, dict) or not user.get("id"):
        raise CloudError("the sign-in service knows no session for this sign-in: sign in again", code="no_session")
    return {"id": str(user["id"]), "name": str(user.get("name") or ""), "email": str(user.get("email") or "")}


# -- the signed-in state ----------------------------------------------------------------------------------------------------------
def account(store: Store) -> dict:
    data = _read(store)
    if data is None:
        return {"signed_in": False, "account": None, "signed_in_at": None, "api_url": api_url(store)}
    return {"signed_in": True, "account": dict(data["account"]), "signed_in_at": data.get("signed_in_at"), "api_url": data["api_url"]}


def signed_in(store: Store) -> bool:
    return _read(store) is not None


def _claims(token: str) -> dict:
    """The payload of a JWT without verification (the cloud verifies it; the core only reads its expiry)."""
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)).decode("utf-8"))
    except (IndexError, ValueError, UnicodeDecodeError):
        return {}


def jwt(store: Store) -> str:
    """A JWT for the cloud's API, renewed a minute before it expires; a session Neon Auth no longer accepts ends the sign-in here."""
    data = _read(store)
    if data is None:
        raise CloudError("sign in to the cloud first", 401, "not_signed_in")
    key = str(store.data_dir)
    with _lock:
        cached = _tokens.get(key)
    if cached and cached[1] - time.time() > REFRESH_MARGIN_S:
        return cached[0]
    answer = request("GET", f"{data['auth_base_url']}/token", headers={"Cookie": f"{SESSION_COOKIE}={data['session_token']}"}, where=AUTH)
    if answer.status == 401:
        _forget(store)
        store.audit("cloud_session_expired", account=data["account"]["id"])
        raise CloudError("the cloud sign-in expired: sign in again", 401, "expired")
    body = expect(answer, 200, where=AUTH)
    token = body.get("token") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token:
        raise CloudError("the sign-in service gave no token: sign in again", code="no_token")
    expiry = _claims(token).get("exp")
    with _lock:
        _tokens[key] = (token, float(expiry) if isinstance(expiry, (int, float)) else time.time() + 10 * 60)
    return token


def sign_out(store: Store) -> dict:
    """Delete the session file; Neon Auth is told when it can be reached (its sign-out wants an Origin: the cloud's own is sent)."""
    data = _read(store)
    if data is not None:
        try:
            request("POST", f"{data['auth_base_url']}/sign-out", body={}, where=AUTH,
                    headers={"Cookie": f"{SESSION_COOKIE}={data['session_token']}", "Origin": data["api_url"]})
        except CloudError:
            pass                                               # the file goes either way; the session ends at Neon Auth within its week
        store.audit("cloud_signed_out", account=data["account"]["id"])
    _forget(store)
    return account(store)


def switched_on() -> bool:
    return cloud_http.switched_on
