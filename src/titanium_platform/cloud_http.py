"""HTTP to the cloud of laboratories and to its sign-in service (feature electron, REQ-086, REQ-087, DEC-058): one function over
``urllib`` with certifi's certificate store and timeouts, behind the switch ``cloud`` of the network settings (:mod:`outbound`), so that
nothing leaves this computer when the operator switched the cloud off; and a transport a test replaces with an in-process fake.

Nothing here is called during ordinary local work: the catalogue, a connection from the cloud, a publication, an invitation and a
check for updates are each the operator's own action on the laboratories screen (or an automatic check the operator allowed)."""
from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Literal

from . import setup as su

switched_on = True                       # outbound.apply sets it from the network setting "cloud"
TIMEOUT_S = 60.0                         # a call of the API
CHUNK_TIMEOUT_S = 300.0                  # one chunk of a release, up or down
USER_AGENT = "titanium-platform"
_ssl_context: ssl.SSLContext | None = None


class CloudError(su.ValidationError):
    """A refusal the operator can act on (answered 422 by the API of this process, translated on the screen). ``status`` is the
    status the cloud or the sign-in service answered with, 0 when it could not be reached; ``code`` its own code when it gave one."""

    def __init__(self, message: str, status: int = 0, code: str = "cloud"):
        super().__init__(message)
        self.status, self.code = status, code


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes

    def json(self):
        if not self.body:
            return None
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


Transport = Callable[[str, str, bytes | None, dict, float], Response]


def _context() -> ssl.SSLContext:
    global _ssl_context
    if _ssl_context is None:
        try:
            import certifi
            _ssl_context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:                                      # the platform's own store then
            _ssl_context = ssl.create_default_context()
    return _ssl_context


def _urllib_transport(method: str, url: str, data: bytes | None, headers: dict, timeout: float) -> Response:
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_context()) as answer:   # noqa: S310 (https from the settings)
            return Response(answer.status, {k.lower(): v for k, v in answer.headers.items()}, answer.read())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read())


transport: Transport = _urllib_transport     # a test puts an in-process fake here


def request(method: str, url: str, *, body=None, raw: bytes | None = None, headers: dict | None = None, timeout: float = TIMEOUT_S,
            where: Literal["the cloud", "the sign-in service"] = "the cloud") -> Response:
    """One call. ``body`` is sent as JSON, ``raw`` as octets. A network failure is a :class:`CloudError` naming ``where``; an answer,
    whatever its status, is returned for the caller to judge (:func:`expect`)."""
    if not switched_on:
        raise CloudError("the cloud of laboratories is switched off in the network settings of this workshop", 0, "switched_off")
    sent = {"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})}
    data = raw
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        sent["Content-Type"] = "application/json"
    elif raw is not None:
        sent["Content-Type"] = "application/octet-stream"
    try:
        return transport(method, url, data, sent, timeout)
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise CloudError(f"{where} could not be reached: {reason}", 0, "unreachable") from None


def expect(answer: Response, *statuses: int, where: Literal["the cloud", "the sign-in service"] = "the cloud") -> object:
    """The JSON of ``answer`` when its status is one of ``statuses``; otherwise a :class:`CloudError` with the service's own message."""
    if answer.status in statuses:
        return answer.json()
    data = answer.json()
    message = None
    if isinstance(data, dict):
        message = data.get("error") or data.get("message")
        if isinstance(message, dict):
            message = message.get("message")
    code = data.get("code") if isinstance(data, dict) and isinstance(data.get("code"), str) else "cloud"
    if answer.status == 401 and where == "the cloud":
        raise CloudError("the cloud does not accept this sign-in any more: sign in again", 401, code)
    raise CloudError(f"{where} refused the request: {message or f'HTTP {answer.status}'}", answer.status, code)
