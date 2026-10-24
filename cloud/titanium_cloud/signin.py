"""The sign-in pages (feature electron, REQ-086, DEC-058, DEC-060): how the desktop application signs in without ever showing a
password form of its own, and without a session cookie it could not obtain.

Neon Auth is an OAuth 2.1 authorization server for this service (its OAuth provider plugin, configured on the Neon branch with this
service's origin as the login and the consent page and this service's address as the protected resource; the desktop is a public
client with PKCE whose one redirect URI is ``/auth/return`` here).

1. The desktop makes a ``state`` (``<random>.<port>``, the port being its own loopback port) and a PKCE verifier, reads
   ``GET /auth/config`` and opens Neon Auth's authorization endpoint in the operator's browser.
2. Neon Auth sends the browser to ``GET /signin`` here with the signed authorization request in the query (``oauth_query``); the page
   (``signin.html``, self-contained, no external script) signs the operator in with Neon Auth from the browser: e-mail and password,
   a new account, or a social provider; Neon Auth then sends the browser to ``GET /consent`` here, where the operator approves the
   application once (``consent.html``).
3. Neon Auth returns the browser to ``GET /auth/return?state&code`` here, which forwards it to the desktop's loopback callback
   ``http://127.0.0.1:<port>/api/cloud/callback?state&code`` (nothing but a loopback address is ever a target).
4. The desktop exchanges the code and the verifier at Neon Auth's token endpoint for an access token (a JWT this service verifies:
   issuer the Neon Auth base URL, audience this service's address) and a refresh token.

This service keeps nothing of a sign-in: the pages talk to Neon Auth from the browser, and the code is bound to the desktop's
verifier. ``GET /auth/config`` tells the desktop Neon Auth's address, the client id, the resource, the redirect address and the social
providers, so that the desktop needs no setting but the address of this service.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .errors import ApiError

router = APIRouter()
HERE = Path(__file__).parent
STATE = re.compile(r"^[A-Za-z0-9_-]{16,128}\.(\d{1,5})$")          # the desktop's state: a random part, a dot, its loopback port
CALLBACK_PATH = "/api/cloud/callback"
RETURN_PATH = "/auth/return"
SCOPES = "openid profile email offline_access"
MAX_PARAM = 512


class NotConfigured(ApiError):
    status = 503

    def __init__(self, message: str = "sign-in is not configured on this service", code: str = "no_auth"):
        super().__init__(message, code)


def public_base(request: Request) -> str:
    settings = request.app.state.settings
    return settings.public_base_url or str(request.base_url).rstrip("/")


def configured(request: Request) -> bool:
    settings = request.app.state.settings
    return bool(settings.auth_base_url and settings.oauth_client_id)


def config_of(request: Request) -> dict:
    settings = request.app.state.settings
    if not configured(request):
        return {"auth_base_url": None, "client_id": None, "resource": None, "redirect_uri": None, "scopes": SCOPES, "providers": []}
    return {"auth_base_url": settings.auth_base_url, "client_id": settings.oauth_client_id, "resource": settings.resource or public_base(request),
            "redirect_uri": public_base(request) + RETURN_PATH, "scopes": SCOPES, "providers": list(settings.oauth_providers)}


def _page(request: Request, name: str, page_config: dict) -> HTMLResponse:
    """A self-contained page with its configuration embedded as JSON data (never markup)."""
    settings = request.app.state.settings
    data = json.dumps(page_config, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")
    html = (HERE / name).read_text(encoding="utf-8").replace("__CONFIG__", data)
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                       "Content-Security-Policy": f"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                                                  f"connect-src 'self' {settings.auth_base_url}; form-action 'none'; "
                                                                  f"frame-ancestors 'none'; base-uri 'none'"})


@router.get("/auth/config")
def config(request: Request):
    """What the desktop needs to sign in (None when sign-in is not configured on this service)."""
    return config_of(request)


@router.get("/signin", response_class=HTMLResponse)
def signin(request: Request):
    """The login page Neon Auth sends the browser to, with the signed authorization request in the query (read by the page itself)."""
    if not configured(request):
        raise NotConfigured()
    settings = request.app.state.settings
    return _page(request, "signin.html", {"auth_base_url": settings.auth_base_url, "providers": list(settings.oauth_providers)})


@router.get("/consent", response_class=HTMLResponse)
def consent(request: Request):
    """The consent page Neon Auth sends the browser to after the sign-in: the operator approves the application once."""
    if not configured(request):
        raise NotConfigured()
    settings = request.app.state.settings
    return _page(request, "consent.html", {"auth_base_url": settings.auth_base_url, "client_id": settings.oauth_client_id,
                                           "resource": settings.resource or public_base(request)})


@router.get(RETURN_PATH)
def auth_return(request: Request, state: str = "", code: str = "", error: str = "", error_description: str = ""):
    """Where Neon Auth sends the browser with the code (or an error): forwarded to the desktop's loopback callback, whose port is the
    tail of the state. Nothing but ``http://127.0.0.1:<port>/api/cloud/callback`` is ever a target."""
    if not configured(request):
        raise NotConfigured()
    found = STATE.match(state)
    port = int(found.group(1)) if found else 0
    if not 0 < port < 65536 or not (code or error) or any(len(v) > MAX_PARAM for v in (state, code, error, error_description)):
        return HTMLResponse(FAILED, status_code=400, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                                               "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"})
    query = {"state": state}
    if code:
        query["code"] = code
    else:
        query["error"] = error
        if error_description:
            query["error_description"] = error_description
    return RedirectResponse(f"http://127.0.0.1:{port}{CALLBACK_PATH}?{urlencode(query)}", status_code=302,
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


FAILED = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Не удалось вернуться в приложение</title><style>body{margin:0;background:#f3f5f7;color:#1b1f23;font:16px/1.45 -apple-system,"Segoe UI",Roboto,Arial,sans-serif}
main{max-width:420px;margin:12vh auto;padding:24px;background:#fff;border:1px solid #d5dbe1;border-radius:12px}h1{font-size:1.3rem;margin:0 0 8px}
@media (prefers-color-scheme:dark){body{background:#0d1117;color:#e6edf3}main{background:#161b22;border-color:#3a434d}}</style></head>
<body><main><h1>Не удалось вернуться в приложение</h1><p>Ответ службы входа не содержит адреса приложения. Начните вход заново с экрана
«Лаборатории» в приложении «Титан».</p></main></body></html>"""
