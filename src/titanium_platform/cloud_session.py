"""Sign-in to the cloud of laboratories, owned by the core in both run modes (feature electron, REQ-086, DEC-058, DEC-060).

The core never shows a password form and never sees a password or a session cookie. Neon Auth acts as an OAuth 2.1 authorization
server for the cloud's own API (its OAuth provider plugin): :func:`start` makes a ``state`` and a PKCE verifier and gives the screen
the address of the authorization endpoint for the operator's browser. Neon Auth sends the browser to the cloud's login page (the cloud
hosts the login and the consent page, ``cloud/titanium_cloud/signin.py``); the operator signs in there and approves the application
once; Neon Auth returns the browser to the cloud's ``/auth/return`` with a one-time code, which forwards it to this core's loopback
callback ``GET /api/cloud/callback?state&code`` (the port is the tail of the state; the guard lets the callback through without the
desktop session cookie only while that state is pending). :func:`complete` exchanges the code and the verifier at the token endpoint
for an access token (a JWT for the cloud's API, an hour) and a refresh token (thirty days, rotated on every use), asks the userinfo
endpoint who it is, and keeps the refresh token in ``<data>/cloud/session.json`` (mode 0600).

Calls to the cloud carry the access token (:func:`jwt`), renewed with the refresh token a minute before it expires; a refresh the
service refuses ends the sign-in here. Refreshes are serialised, because a refresh token presented twice revokes the whole sign-in.
:func:`sign_out` revokes the refresh token (best effort) and deletes the file. A sign-in the operator does not finish is forgotten
after ten minutes; nothing of the workshop changes whatever happens here.

The address of the cloud is the setting ``cloud.api_url`` (editable on the network screen); what else the core needs (Neon Auth's
address, the client id, the resource, the redirect address, the social providers) the cloud tells it at ``GET /auth/config``, and the
endpoints come from Neon Auth's own discovery document, whose issuer must be the address the cloud named."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from . import cloud_http
from .cloud_http import CloudError, Response, expect, request
from .db import Store, now

API_URL_SETTING = "cloud.api_url"
DEFAULT_API_URL = "https://titanium-labs-api.vercel.app"      # the production service (cloud/README.md); a setting overrides it
FOLDER, FILE = "cloud", "session.json"
PENDING_S = 600                                               # a sign-in the operator did not finish is forgotten after this
REFRESH_MARGIN_S = 60                                         # an access token is renewed this long before it expires
AUTH = "the sign-in service"
CALLBACK_PATH = "/api/cloud/callback"                         # api.security lets it through without the desktop cookie while a state is pending
STATE = re.compile(r"^[A-Za-z0-9_-]{16,128}\.(\d{1,5})$")       # a state: the random part, one dot, this core's loopback port (signin.py agrees)
DISCOVERY = "/.well-known/oauth-authorization-server"         # RFC 8414, served by Neon Auth under its base URL
SCOPES = "openid profile email offline_access"                # who signed in (name, e-mail) and a refresh token
FILE_KEYS = ("api_url", "auth_base_url", "client_id", "resource", "token_endpoint", "userinfo_endpoint", "revocation_endpoint",
             "refresh_token", "account", "signed_in_at")

_pending: dict[str, dict] = {}                                # state -> the sign-in waiting for its callback
_tokens: dict[str, tuple[str, float]] = {}                    # data folder -> (access token, its expiry)
_lock = threading.Lock()
_refresh_lock = threading.Lock()                              # one refresh at a time: a refresh token used twice revokes the sign-in


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
    if not isinstance(data, dict) or not all(data.get(key) for key in ("refresh_token", "token_endpoint", "client_id", "account")):
        return None
    return data


def _write(store: Store, data: dict) -> None:
    path = session_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({key: data.get(key) for key in FILE_KEYS}, fh)
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


def state_port(state: str) -> int | None:
    """The loopback port a state carries after its one dot (the cloud's ``/auth/return`` forwards the browser there), or None."""
    found = STATE.match(state or "")
    port = int(found.group(1)) if found else 0
    return port if 0 < port < 65536 else None


def start(store: Store, port: int) -> dict:
    """A new sign-in: the address of Neon Auth's authorization endpoint for the operator's browser, with this core's port in the state."""
    url = api_url(store)
    config = expect(request("GET", f"{url}/auth/config"), 200)
    if not isinstance(config, dict) or not all(isinstance(config.get(k), str) and config[k] for k in ("auth_base_url", "client_id", "redirect_uri")):
        raise CloudError("the cloud does not offer sign-in: it is not configured for it", code="no_auth")
    auth_base = config["auth_base_url"].rstrip("/")
    found = expect(request("GET", auth_base + DISCOVERY, where=AUTH), 200, where=AUTH)
    if not isinstance(found, dict) or found.get("issuer") != auth_base:
        raise CloudError("the sign-in service names another issuer than the cloud does", code="issuer")
    for key in ("authorization_endpoint", "token_endpoint", "userinfo_endpoint"):
        if not isinstance(found.get(key), str) or not found[key].startswith(auth_base + "/"):
            raise CloudError("the discovery document of the sign-in service is not as expected", code="discovery")
    revocation = found.get("revocation_endpoint")
    state, verifier = f"{secrets.token_urlsafe(24)}.{int(port)}", secrets.token_urlsafe(48)
    entry = {"verifier": verifier, "api_url": url, "auth_base_url": auth_base, "client_id": config["client_id"],
             "resource": str(config.get("resource") or url), "redirect_uri": config["redirect_uri"], "token_endpoint": found["token_endpoint"],
             "userinfo_endpoint": found["userinfo_endpoint"], "created": time.time(),
             "revocation_endpoint": revocation if isinstance(revocation, str) and revocation.startswith(auth_base + "/") else None}
    with _lock:
        _purge()
        _pending[state] = entry
    query = urlencode({"response_type": "code", "client_id": entry["client_id"], "redirect_uri": entry["redirect_uri"],
                       "scope": str(config.get("scopes") or SCOPES), "state": state, "code_challenge": s256(verifier),
                       "code_challenge_method": "S256", "resource": entry["resource"]})
    return {"url": f"{found['authorization_endpoint']}?{query}", "state": state, "providers": list(config.get("providers") or []),
            "expires_in_s": PENDING_S}


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


def complete(store: Store, state: str, code: str, error: str | None = None, error_description: str | None = None) -> dict:
    """The callback: the code and the verifier for the tokens, then who signed in; the state is spent by this call."""
    with _lock:
        _purge()
        entry = _pending.pop(state or "", None)
    if entry is None:
        raise CloudError("this sign-in is not expected: start it again from the application", code="unknown_state")
    if error:
        if error == "access_denied":
            raise CloudError("the sign-in was cancelled at the sign-in service", code="denied")
        raise CloudError(f"the sign-in service answered with an error: {(error_description or error)[:200]}", code="provider_error")
    if not code or len(code) > 512:
        raise CloudError("the sign-in code is missing", code="bad_code")
    answer = request("POST", entry["token_endpoint"], where=AUTH,
                     form={"grant_type": "authorization_code", "code": code, "code_verifier": entry["verifier"], "redirect_uri": entry["redirect_uri"],
                           "client_id": entry["client_id"], "resource": entry["resource"]})
    if answer.status != 200:
        raise CloudError(f"the sign-in service refused the code: {_oauth_error(answer)}", code="bad_code")
    tokens = answer.json()
    access = tokens.get("access_token") if isinstance(tokens, dict) else None
    refresh = tokens.get("refresh_token") if isinstance(tokens, dict) else None
    if not isinstance(access, str) or not access:
        raise CloudError("the sign-in service gave no token: sign in again", code="no_token")
    if not isinstance(refresh, str) or not refresh:
        raise CloudError("the sign-in service gave no refresh token: sign in again", code="no_refresh")
    who = whoami(entry["userinfo_endpoint"], access)
    _write(store, {**entry, "refresh_token": refresh, "account": who, "signed_in_at": now()})
    with _lock:
        _tokens[str(store.data_dir)] = (access, _expiry(tokens, access))
    store.audit("cloud_signed_in", account=who["id"], api_url=entry["api_url"])
    return account(store)


def whoami(userinfo_endpoint: str, access_token: str) -> dict:
    """The account of an access token, from the userinfo endpoint: id, name and e-mail (nothing else is kept)."""
    data = expect(request("GET", userinfo_endpoint, headers={"Authorization": f"Bearer {access_token}"}, where=AUTH), 200, where=AUTH)
    subject = data.get("sub") if isinstance(data, dict) else None
    if not isinstance(subject, str) or not subject.strip():
        raise CloudError("the sign-in service named no account for this sign-in: sign in again", code="no_session")
    return {"id": subject, "name": str(data.get("name") or ""), "email": str(data.get("email") or "")}


def _oauth_error(answer: Response) -> str:
    data = answer.json()
    if isinstance(data, dict):
        return str(data.get("error_description") or data.get("error") or answer.status)
    return str(answer.status)


def _oauth_code(answer: Response) -> str:
    data = answer.json()
    return str(data.get("error") or "") if isinstance(data, dict) else ""


def _expiry(tokens: dict, access: str) -> float:
    exp = _claims(access).get("exp")
    if isinstance(exp, (int, float)):
        return float(exp)
    lifetime = tokens.get("expires_in")
    return time.time() + (float(lifetime) if isinstance(lifetime, (int, float)) else 10 * 60)


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


def _cached(key: str) -> str | None:
    with _lock:
        cached = _tokens.get(key)
    if cached and cached[1] - time.time() > REFRESH_MARGIN_S:
        return cached[0]
    return None


def jwt(store: Store) -> str:
    """The access token for the cloud's API, renewed with the refresh token a minute before it expires; a refresh the sign-in service
    refuses ends the sign-in here."""
    if _read(store) is None:
        raise CloudError("sign in to the cloud first", 401, "not_signed_in")
    key = str(store.data_dir)
    cached = _cached(key)
    if cached:
        return cached
    with _refresh_lock:
        cached = _cached(key)                              # another thread renewed it while this one waited
        if cached:
            return cached
        data = _read(store)
        if data is None:
            raise CloudError("sign in to the cloud first", 401, "not_signed_in")
        answer = request("POST", data["token_endpoint"], where=AUTH,
                         form={"grant_type": "refresh_token", "refresh_token": data["refresh_token"], "client_id": data["client_id"]})
        if answer.status == 401 or (answer.status == 400 and _oauth_code(answer) in ("invalid_grant", "invalid_token")):
            _forget(store)
            store.audit("cloud_session_expired", account=data["account"]["id"])
            raise CloudError("the cloud sign-in expired: sign in again", 401, "expired")
        if answer.status != 200:
            raise CloudError(f"the sign-in service did not renew the sign-in: {_oauth_error(answer)}", code="refresh")
        tokens = answer.json()
        access = tokens.get("access_token") if isinstance(tokens, dict) else None
        if not isinstance(access, str) or not access:
            raise CloudError("the sign-in service gave no token: sign in again", code="no_token")
        rotated = tokens.get("refresh_token")
        if isinstance(rotated, str) and rotated:
            _write(store, {**data, "refresh_token": rotated})      # kept before the token is used: the old one is dead now
        with _lock:
            _tokens[key] = (access, _expiry(tokens, access))
        return access


def sign_out(store: Store) -> dict:
    """Delete the session file; the refresh token is revoked at the sign-in service when it can be reached (best effort)."""
    data = _read(store)
    if data is not None:
        if data.get("revocation_endpoint"):
            try:
                request("POST", data["revocation_endpoint"], where=AUTH, headers={"Origin": data["api_url"]},
                        form={"token": data["refresh_token"], "token_type_hint": "refresh_token", "client_id": data["client_id"]})
            except CloudError:
                pass                                           # the file goes either way; the refresh token dies within its month
        store.audit("cloud_signed_out", account=data["account"]["id"])
    _forget(store)
    return account(store)


def switched_on() -> bool:
    return cloud_http.switched_on
