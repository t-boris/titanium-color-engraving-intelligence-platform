"""An in-process cloud and sign-in service for the desktop's cloud tests (electron REQ-086, DEC-058, DEC-060): the real cloud
application (``cloud/``, in-memory repository) and a small Neon Auth look-alike acting as the OAuth 2.1 authorization server the
desktop talks to, both behind a fake ``cloud_http.transport`` that answers the desktop's ``urllib`` calls from TestClients. The
look-alike does what the desktop relies on: the discovery document, the token endpoint (authorization code with PKCE, refresh tokens
rotated on every use and the whole sign-in revoked when one is presented twice, as the real one does), the userinfo endpoint and
revocation. What the browser does (the login and consent pages, the return to the cloud's ``/auth/return``) is ``authorize``."""
from __future__ import annotations

import secrets
import sys
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "cloud"))

from titanium_cloud.app import create_app as create_cloud  # noqa: E402
from titanium_cloud.settings import Settings  # noqa: E402
from titanium_platform import cloud_http, cloud_session  # noqa: E402

CLOUD_BASE = "https://cloud.test"
AUTH_BASE = "https://auth.test/titanium_labs/auth"
CLIENT_ID = "desktop-client-test"
RETURN_URI = CLOUD_BASE + "/auth/return"
CHUNK = 16 * 1024


class FakeAuth:
    """Neon Auth's OAuth provider as the desktop sees it; ``users`` maps an account id to its userinfo."""

    def __init__(self, mint):
        self.mint = mint
        self.users: dict[str, dict] = {}
        self.codes: dict[str, dict] = {}                # code -> {account, challenge, redirect_uri, resource}
        self.refresh: dict[str, dict] = {}              # live refresh token -> {account, family}
        self.spent: dict[str, str] = {}                 # rotated refresh token -> its family (a second use revokes the family)
        self.access: dict[str, str] = {}                # access token -> account
        self.calls: list[tuple[str, str]] = []
        self.token_lifetime_s = 3600
        self.app = FastAPI()
        app = self.app

        @app.get("/.well-known/oauth-authorization-server")
        def discovery():
            self.calls.append(("GET", "/.well-known/oauth-authorization-server"))
            return {"issuer": AUTH_BASE, "authorization_endpoint": f"{AUTH_BASE}/oauth2/authorize", "token_endpoint": f"{AUTH_BASE}/oauth2/token",
                    "userinfo_endpoint": f"{AUTH_BASE}/oauth2/userinfo", "revocation_endpoint": f"{AUTH_BASE}/oauth2/revoke",
                    "scopes_supported": ["openid", "profile", "email", "offline_access"], "code_challenge_methods_supported": ["S256"],
                    "grant_types_supported": ["authorization_code", "refresh_token"]}

        @app.post("/oauth2/token")
        async def token(request: Request):
            self.calls.append(("POST", "/oauth2/token"))
            if not request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
                return JSONResponse({"error": "invalid_request", "error_description": "form body expected"}, status_code=400)
            form = {k: v[0] for k, v in parse_qs((await request.body()).decode("ascii")).items()}
            if form.get("client_id") != CLIENT_ID:
                return JSONResponse({"error": "invalid_client"}, status_code=401)
            if form.get("grant_type") == "authorization_code":
                found = self.codes.pop(form.get("code", ""), None)
                if found is None:
                    return JSONResponse({"error": "invalid_grant", "error_description": "invalid code"}, status_code=400)
                if cloud_session.s256(form.get("code_verifier", "")) != found["challenge"]:
                    return JSONResponse({"error": "invalid_grant", "error_description": "code verifier mismatch"}, status_code=400)
                if form.get("redirect_uri") != found["redirect_uri"] or form.get("resource") != found["resource"]:
                    return JSONResponse({"error": "invalid_grant", "error_description": "redirect_uri or resource mismatch"}, status_code=400)
                return self._issue(found["account"], secrets.token_urlsafe(8))
            if form.get("grant_type") == "refresh_token":
                presented = form.get("refresh_token", "")
                live = self.refresh.pop(presented, None)
                if live is None:
                    family = self.spent.get(presented)
                    if family:                                                   # a rotated token used again: the family is revoked
                        for key in [k for k, v in self.refresh.items() if v["family"] == family]:
                            del self.refresh[key]
                    return JSONResponse({"error": "invalid_grant", "error_description": "invalid refresh token"}, status_code=400)
                self.spent[presented] = live["family"]
                return self._issue(live["account"], live["family"])
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

        @app.get("/oauth2/userinfo")
        def userinfo(request: Request):
            self.calls.append(("GET", "/oauth2/userinfo"))
            scheme, _, bearer = request.headers.get("authorization", "").partition(" ")
            account = self.access.get(bearer) if scheme.lower() == "bearer" else None
            if account is None:
                return JSONResponse({"error": "invalid_token", "error_description": "Invalid access token"}, status_code=401)
            user = self.users[account]
            return {"sub": account, "name": user["name"], "email": user["email"], "email_verified": False}

        @app.post("/oauth2/revoke")
        async def revoke(request: Request):
            self.calls.append(("POST", "/oauth2/revoke"))
            form = {k: v[0] for k, v in parse_qs((await request.body()).decode("ascii")).items()}
            self.refresh.pop(form.get("token", ""), None)
            return {}

        self.client = TestClient(app)

    def _issue(self, account: str, family: str) -> dict:
        access = self.mint(account, key="ed", expires_in=self.token_lifetime_s)
        self.access[access] = account
        refresh = secrets.token_urlsafe(24)
        self.refresh[refresh] = {"account": account, "family": family}
        return {"access_token": access, "token_type": "Bearer", "expires_in": self.token_lifetime_s, "refresh_token": refresh,
                "scope": "openid profile email offline_access"}

    def authorize(self, url: str, account: str, name: str = "", email: str = "") -> tuple[str, str]:
        """What the browser brings back after the operator signed in on the login page and approved the application on the consent
        page: the state and a one-time code for the authorization request at ``url`` (checked as the real server checks it)."""
        parts = urlsplit(url)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{AUTH_BASE}/oauth2/authorize", url
        assert query["response_type"] == "code" and query["client_id"] == CLIENT_ID and query["code_challenge_method"] == "S256", query
        assert query["redirect_uri"] == RETURN_URI and "offline_access" in query["scope"].split(" ") and query.get("resource"), query
        self.users.setdefault(account, {"name": name or account, "email": email or f"{account}@example.org"})
        code = secrets.token_urlsafe(24)
        self.codes[code] = {"account": account, "challenge": query["code_challenge"], "redirect_uri": query["redirect_uri"], "resource": query["resource"]}
        return query["state"], code


class Transport:
    """``cloud_http.transport`` over TestClients; every call is recorded; ``down`` makes every host unreachable, ``refuse`` a predicate
    ``(method, path) -> bool`` that makes matching calls unreachable (a network that drops in the middle of an upload)."""

    def __init__(self, targets: dict[str, TestClient]):
        self.targets = targets
        self.calls: list[tuple[str, str]] = []
        self.down = False
        self.refuse = None

    def __call__(self, method: str, url: str, data: bytes | None, headers: dict, timeout: float) -> cloud_http.Response:
        self.calls.append((method, url))
        if self.down:
            raise urllib.error.URLError("the network is down")
        for base, client in self.targets.items():
            if url == base or url.startswith(base + "/"):
                path = url[len(base):] or "/"
                if self.refuse and self.refuse(method, path):
                    raise urllib.error.URLError("the connection dropped")
                answer = client.request(method, path, content=data, headers=headers)
                return cloud_http.Response(answer.status_code, dict(answer.headers), answer.content)
        raise urllib.error.URLError(f"no such host: {url}")


class World:
    """One cloud (fresh catalogue), one sign-in service and the transport that reaches them, installed in ``cloud_http`` by ``install``."""

    def __init__(self, verifier, mint, *, chunk: int = CHUNK, providers=("google",)):
        self.settings = Settings(repository="memory", chunk_bytes=chunk, auth_base_url=AUTH_BASE, oauth_providers=tuple(providers),
                                 oauth_client_id=CLIENT_ID, public_base_url=CLOUD_BASE)
        self.app = create_cloud(self.settings, verifier=verifier)
        self.cloud = TestClient(self.app)
        self.auth = FakeAuth(mint)
        self.transport = Transport({CLOUD_BASE: self.cloud, AUTH_BASE: self.auth.client})
        self.base = CLOUD_BASE

    def install(self, monkeypatch) -> "World":
        monkeypatch.setattr(cloud_http, "transport", self.transport)
        monkeypatch.setattr(cloud_http, "switched_on", True)
        return self

    def browser(self, url: str, account: str, name: str = "") -> str:
        """The browser's way from the authorization address to the desktop: sign-in and consent (``authorize``), then the cloud's
        ``/auth/return``, whose redirect to the loopback callback is returned (its query carries the state and the code)."""
        state, code = self.auth.authorize(url, account, name)
        returned = self.cloud.get("/auth/return", params={"state": state, "code": code}, follow_redirects=False)
        assert returned.status_code == 302, returned.text
        return returned.headers["location"]

    def sign_in(self, store, account: str = "acc-author", name: str = "Автор", port: int = 8765) -> dict:
        """The whole sign-in of ``store`` through the real core: start, the browser's part, the callback's exchange."""
        store.set_setting(cloud_session.API_URL_SETTING, self.base)
        started = cloud_session.start(store, port)
        state, code = self.auth.authorize(started["url"], account, name)
        return cloud_session.complete(store, state, code)
