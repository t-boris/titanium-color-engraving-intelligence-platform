"""The sign-in handoff (feature electron, REQ-086, DEC-058): how the desktop application gets a Neon Auth session without ever showing a
password form of its own.

1. The desktop makes a ``state`` and a PKCE verifier, and opens ``GET /signin?state&challenge&callback`` in the operator's browser.
   ``callback`` is the desktop's own loopback address (``http://127.0.0.1:<port>/api/cloud/callback``) and nothing else is accepted.
2. The page (``signin.html``, self-contained, no external script) signs the operator in with Neon Auth from the browser: e-mail and
   password, a new account, or a social provider. Neon Auth answers with the session token (or keeps it in its cookie after a social
   round trip, read back with ``get-session``).
3. The page posts ``{state, challenge, session_token}`` to ``POST /auth/handoff`` and receives a one-time ``code`` that lives
   ``handoff_lifetime_s``; then it sends the browser to ``callback?state&code``.
4. The desktop posts ``{state, code, verifier}`` to ``POST /auth/handoff/exchange``; when ``S256(verifier)`` is the challenge and the state
   is the one of the handoff, it receives the session token once, and the handoff is gone. A wrong verifier spends the code too.

The service keeps only the hash of the code, and no handoff grants anything by itself: the desktop still has to turn the session token
into a JWT at Neon Auth, which refuses a token that is not live. ``GET /auth/config`` tells the desktop Neon Auth's address and the
social providers, so that the desktop needs no setting but the address of this service.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .errors import ApiError, Gone, Invalid, NotFound, Unauthorized
from .repository import Repository, moment, now, stamp
from .routes import repo

router = APIRouter()
PAGE = Path(__file__).with_name("signin.html")
STATE = r"^[A-Za-z0-9_-]{16,128}$"
CHALLENGE = r"^[A-Za-z0-9_-]{43,128}$"             # base64url of a SHA-256, no padding: 43 characters
CALLBACK_PATH = "/api/cloud/callback"
CALLBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
CODE_BYTES = 32


class NotConfigured(ApiError):
    status = 503

    def __init__(self, message: str = "sign-in is not configured on this service", code: str = "no_auth"):
        super().__init__(message, code)


class Handoff(BaseModel):
    state: str = Field(pattern=STATE)
    challenge: str = Field(pattern=CHALLENGE)
    session_token: str = Field(min_length=1, max_length=4096)


class Exchange(BaseModel):
    state: str = Field(pattern=STATE)
    code: str = Field(min_length=1, max_length=256)
    verifier: str = Field(pattern=CHALLENGE)


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def callback_allowed(callback: str) -> bool:
    """Only the desktop's own loopback address, at the one path the core answers, without a query of its own."""
    parts = urlsplit(callback)
    host = parts.hostname or ""
    if parts.scheme != "http" or parts.path != CALLBACK_PATH or parts.query or parts.fragment or parts.username or parts.password:
        return False
    if host == "::1":
        host = "[::1]"
    return host in CALLBACK_HOSTS and parts.port is not None


def config_of(request: Request) -> dict:
    settings = request.app.state.settings
    return {"auth_base_url": settings.auth_base_url, "providers": list(settings.oauth_providers) if settings.auth_base_url else [],
            "handoff_lifetime_s": settings.handoff_lifetime_s}


@router.get("/auth/config")
def config(request: Request):
    """What the desktop needs to sign in: Neon Auth's address (None when sign-in is not configured) and the social providers."""
    return config_of(request)


@router.get("/signin", response_class=HTMLResponse)
def signin(request: Request, state: str = Query(pattern=STATE), challenge: str = Query(pattern=CHALLENGE), callback: str = Query(max_length=200)):
    """The sign-in page for one desktop: its state, challenge and loopback callback are embedded as data (JSON, never markup)."""
    settings = request.app.state.settings
    if not settings.auth_base_url:
        raise NotConfigured("sign-in is not configured on this service")
    if not callback_allowed(callback):
        raise Invalid("the callback must be the application's own loopback address", "callback")
    page_config = {"auth_base_url": settings.auth_base_url, "providers": list(settings.oauth_providers), "state": state, "challenge": challenge,
                   "callback": callback, "returned": request.query_params.get("returned") == "1"}
    data = json.dumps(page_config, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")
    html = PAGE.read_text(encoding="utf-8").replace("__CONFIG__", data)
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                       "Content-Security-Policy": f"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                                                  f"connect-src 'self' {settings.auth_base_url}; form-action 'none'; "
                                                                  f"frame-ancestors 'none'; base-uri 'none'"})


@router.post("/auth/handoff", status_code=201)
def make_handoff(request: Request, body: Handoff, store: Repository = Depends(repo)):
    """The page leaves the session token under a one-time code for the desktop named by ``state``."""
    settings = request.app.state.settings
    if not settings.auth_base_url:
        raise NotConfigured("sign-in is not configured on this service")
    code = secrets.token_urlsafe(CODE_BYTES)
    expires = now() + timedelta(seconds=settings.handoff_lifetime_s)
    store.create_handoff({"code_hash": code_hash(code), "state": body.state, "challenge": body.challenge, "session_token": body.session_token,
                          "expires_at": stamp(expires)})
    return {"code": code, "expires_at": stamp(expires), "expires_in_s": settings.handoff_lifetime_s}


@router.post("/auth/handoff/exchange")
def exchange(body: Exchange, store: Repository = Depends(repo)):
    """The session token for the code, once: the code is spent by this call whatever the outcome."""
    found = store.take_handoff(code_hash(body.code))
    if found is None:
        raise NotFound("there is no such sign-in code: it was used, or it never existed", "unknown_code")
    if moment(found["expires_at"]) < now():
        raise Gone("the sign-in code expired: sign in again", "expired")
    if not secrets.compare_digest(found["state"], body.state) or not secrets.compare_digest(found["challenge"], s256(body.verifier)):
        raise Unauthorized("the sign-in code does not belong to this application", "bad_verifier")
    return {"session_token": found["session_token"]}
