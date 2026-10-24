"""The guard of the local API (feature electron, DEC-046, REQ-080): the application serves one workshop on this computer, in a browser
or under the desktop shell, and an unrelated web page must not be able to read or change it.

In both run modes every request's ``Host`` must name this computer (a loopback name, an IP address, or a host the operator allowed
with ``TCE_ALLOWED_HOSTS``), so that a page that rebinds its own name to this address is refused; a request that changes something and
comes from another site (``Origin`` not this host, or ``Sec-Fetch-Site: cross-site``) is refused; a body larger than any upload the
application takes is refused before it is read.

Under the desktop shell (``TCE_SESSION_SECRET`` set, ``titanium-platform --desktop``) the shell opens its window once at
``/session/<secret>``: that address sets the session cookie (HttpOnly, SameSite=Strict) and is spent; every other request without the
cookie is refused with 403, so that a browser on this computer, or a page a browser opens, cannot use the workshop the shell runs.
The secret is per launch and never written anywhere by the core.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import os
import secrets
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from fastapi import FastAPI

LOOPBACK = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
MAX_BODY_BYTES = 601 * 1024 * 1024            # above the largest upload the application reads (api.common.MAX_PHOTO_BYTES)
COOKIE = "tce_session"
SESSION_PATH = "/session/"
SECRET_ENV, HOSTS_ENV = "TCE_SESSION_SECRET", "TCE_ALLOWED_HOSTS"


@dataclass
class Guard:
    """What the guard checks against: the hosts allowed besides loopback and IP addresses, and the desktop session when there is one."""
    allowed_hosts: frozenset[str] = frozenset()
    secret: str | None = None                          # the shell's bootstrap secret; None in browser mode
    cookie: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    spent: bool = False                                # the bootstrap address was used once

    @classmethod
    def from_environment(cls) -> "Guard":
        hosts = frozenset(h.strip().lower() for h in os.environ.get(HOSTS_ENV, "").split(",") if h.strip())
        secret = os.environ.get(SECRET_ENV) or None
        return cls(allowed_hosts=hosts, secret=secret)

    @property
    def desktop(self) -> bool:
        return self.secret is not None

    def host_allowed(self, host: str | None) -> bool:
        """A loopback name, an IP address (a rebinding page cannot send one) or an allowed host, with or without a port."""
        name = _hostname(host)
        if not name:
            return False
        if name in LOOPBACK or name in self.allowed_hosts:
            return True
        try:
            ipaddress.ip_address(name.strip("[]"))
            return True
        except ValueError:
            return False

    def origin_allowed(self, origin: str | None, host: str | None, fetch_site: str | None) -> bool:
        """A request that changes something must come from this host: no ``Origin`` (not a browser, or same-origin without one), or the
        origin's host is the request's host; a browser that says the request is cross-site is refused."""
        if fetch_site and fetch_site.lower() == "cross-site":
            return False
        if not origin or origin == "null":
            return not origin
        return _hostname(urlsplit(origin).netloc) == _hostname(host) and self.host_allowed(urlsplit(origin).netloc)

    def session_ok(self, cookie_header: str | None) -> bool:
        if not self.desktop:
            return True
        for part in (cookie_header or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and hmac.compare_digest(value, self.cookie):
                return True
        return False

    def bootstrap(self, path: str) -> bool:
        """Whether ``path`` is the shell's one-time session address with the right secret; it is spent by this call."""
        if not self.desktop or self.spent or not path.startswith(SESSION_PATH):
            return False
        if not hmac.compare_digest(path[len(SESSION_PATH):], self.secret):
            return False
        self.spent = True
        return True


def _hostname(host: str | None) -> str:
    """The name of ``host`` without its port, lower-case; an IPv6 literal keeps its brackets."""
    if not host:
        return ""
    host = host.strip().lower()
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class LocalGuard:
    """ASGI middleware that applies :class:`Guard` before any route runs."""

    def __init__(self, app, guard: Guard):
        self.app, self.guard = app, guard

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host = headers.get("host")
        if not self.guard.host_allowed(host):
            return await _refuse(send, 421, "this address does not name this computer", "misdirected")
        if scope["method"].upper() in UNSAFE and not self.guard.origin_allowed(headers.get("origin"), host, headers.get("sec-fetch-site")):
            return await _refuse(send, 403, "a request from another site cannot change this workshop", "forbidden")
        length = headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return await _refuse(send, 413, f"the request is larger than {MAX_BODY_BYTES // (1024 * 1024)} MB", "too_large")
        path = scope.get("path", "")
        if self.guard.desktop and path.startswith(SESSION_PATH):
            if self.guard.bootstrap(path):
                cookie = f"{COOKIE}={self.guard.cookie}; Path=/; HttpOnly; SameSite=Strict"
                return await _respond(send, 303, [(b"location", b"/"), (b"set-cookie", cookie.encode("latin-1"))], b"")
            return await _refuse(send, 403, "this session address is not valid", "forbidden")
        if not self.guard.session_ok(headers.get("cookie")):
            return await _refuse(send, 403, "open the workshop from the application", "forbidden")
        return await self.app(scope, receive, send)


async def _refuse(send, status: int, message: str, kind: str):
    body = json.dumps({"error": message, "kind": kind}).encode("utf-8")
    await _respond(send, status, [(b"content-type", b"application/json")], body)


async def _respond(send, status: int, headers: list[tuple[bytes, bytes]], body: bytes):
    await send({"type": "http.response.start", "status": status,
                "headers": headers + [(b"content-length", str(len(body)).encode()), (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": body})


def install(app: FastAPI, guard: Guard | None = None) -> Guard:
    """Put the guard in front of ``app`` (from the environment unless given) and keep it as ``app.state.guard``."""
    guard = guard or Guard.from_environment()
    app.state.guard = guard
    app.add_middleware(LocalGuard, guard=guard)
    return guard
