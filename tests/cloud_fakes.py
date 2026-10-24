"""An in-process cloud and sign-in service for the desktop's cloud tests (electron REQ-086, DEC-058): the real cloud application
(``cloud/``, in-memory repository) and a small Neon Auth look-alike, both behind a fake ``cloud_http.transport`` that answers the
desktop's ``urllib`` calls from TestClients. The look-alike does what the desktop relies on: a session cookie, ``GET /get-session``,
``GET /token`` (a JWT of the session's user, signed with the keys of ``tests/test_cloud_api.py`` so the cloud verifies it), and
``POST /sign-out`` that wants an ``Origin`` header as the real one does."""
from __future__ import annotations

import secrets
import sys
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, Request, Response
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
COOKIE = cloud_session.SESSION_COOKIE
CHUNK = 16 * 1024


class FakeAuth:
    """Neon Auth as the desktop sees it; ``sessions`` maps a session token to its user."""

    def __init__(self, mint):
        self.mint = mint
        self.sessions: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.token_lifetime_s = 900
        self.app = FastAPI()
        app = self.app

        @app.get("/get-session")
        def get_session(request: Request):
            self.calls.append(("GET", "/get-session"))
            user = self._user(request)
            if user is None:
                return Response("null", media_type="application/json")
            return {"session": {"token": request.cookies.get(COOKIE), "userId": user["id"]}, "user": user}

        @app.get("/token")
        def token(request: Request):
            self.calls.append(("GET", "/token"))
            user = self._user(request)
            if user is None:
                return JSONResponse({"message": "Unauthorized", "code": "UNAUTHORIZED"}, status_code=401)
            return {"token": self.mint(user["id"], key="ed", expires_in=self.token_lifetime_s)}

        @app.post("/sign-out")
        def sign_out(request: Request):
            self.calls.append(("POST", "/sign-out"))
            if not request.headers.get("origin"):
                return JSONResponse({"message": "Missing or null Origin", "code": "MISSING_OR_NULL_ORIGIN"}, status_code=403)
            self.sessions.pop(request.cookies.get(COOKIE) or "", None)
            return {"success": True}

        self.client = TestClient(app)

    def _user(self, request: Request) -> dict | None:
        return self.sessions.get(request.cookies.get(COOKIE) or "")

    def session_for(self, account: str, name: str = "", email: str = "") -> str:
        token = secrets.token_urlsafe(24)
        self.sessions[token] = {"id": account, "name": name or account, "email": email or f"{account}@example.org"}
        return token


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
        self.settings = Settings(repository="memory", chunk_bytes=chunk, auth_base_url=AUTH_BASE, oauth_providers=tuple(providers))
        self.app = create_cloud(self.settings, verifier=verifier)
        self.cloud = TestClient(self.app)
        self.auth = FakeAuth(mint)
        self.transport = Transport({CLOUD_BASE: self.cloud, AUTH_BASE: self.auth.client})
        self.base = CLOUD_BASE

    def install(self, monkeypatch) -> "World":
        monkeypatch.setattr(cloud_http, "transport", self.transport)
        monkeypatch.setattr(cloud_http, "switched_on", True)
        return self

    def handoff(self, url: str, account: str, name: str = "") -> tuple[str, str]:
        """What the sign-in page does after the operator signed in: the session token left under a code for ``state``."""
        query = parse_qs(urlsplit(url).query)
        token = self.auth.session_for(account, name=name)
        made = self.cloud.post("/auth/handoff", json={"state": query["state"][0], "challenge": query["challenge"][0], "session_token": token})
        assert made.status_code == 201, made.text
        return query["state"][0], made.json()["code"]

    def sign_in(self, store, account: str = "acc-author", name: str = "Автор", port: int = 8765) -> dict:
        """The whole sign-in of ``store`` through the real core: start, the page's handoff, the callback's exchange."""
        store.set_setting(cloud_session.API_URL_SETTING, self.base)
        started = cloud_session.start(store, port)
        state, code = self.handoff(started["url"], account, name)
        return cloud_session.complete(store, state, code)
