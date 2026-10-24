"""Who is asking (DEC-040, DEC-058): a Bearer JWT issued by Neon Auth, verified against its JWKS; the token's subject is the account id.
Neon Auth signs with EdDSA (Ed25519) today and may rotate to other keys, so the key is chosen by ``kid``, RS256, ES256 and EdDSA are
accepted, and an unknown ``kid`` refreshes the cached key set once. Public routes need no token; a token that is present must be valid."""
from __future__ import annotations

import json
import ssl
import threading
import time
import urllib.request
from typing import Callable

import jwt

from .errors import Unauthorized

ALGORITHMS = ("RS256", "ES256", "EdDSA")
TTL_S = 600
LEEWAY_S = 60


def _fetch(url: str) -> dict:
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:                                           # the platform's own store then
        context = ssl.create_default_context()
    with urllib.request.urlopen(url, timeout=10, context=context) as response:   # noqa: S310 (an https address from the settings)
        return json.loads(response.read().decode("utf-8"))


class Verifier:
    """Verifies tokens against a JWKS: an address fetched and cached for ``TTL_S``, or a key set given once."""

    def __init__(self, *, jwks_url: str | None = None, jwks: dict | None = None, issuer: str | None = None, audience: str | None = None,
                 fetch: Callable[[str], dict] = _fetch, ttl_s: int = TTL_S):
        if not jwks_url and jwks is None:
            raise ValueError("a JWKS address or key set is required")
        self.url, self.issuer, self.audience, self.fetch, self.ttl_s = jwks_url, issuer, audience, fetch, ttl_s
        self._keys: dict[str, jwt.PyJWK] = {}
        self._loaded_at = 0.0
        self._lock = threading.Lock()
        if jwks is not None:
            self._set(jwks)
            self._loaded_at = float("inf")

    def _set(self, jwks: dict) -> None:
        keys = {}
        for entry in jwks.get("keys") or []:
            try:
                key = jwt.PyJWK(entry)
            except jwt.PyJWKError:
                continue                                           # a key type this service does not use
            if key.key_id:
                keys[key.key_id] = key
        self._keys = keys

    def _refresh(self, force: bool = False) -> None:
        with self._lock:
            if self.url and (force or time.monotonic() - self._loaded_at > self.ttl_s):
                self._set(self.fetch(self.url))
                self._loaded_at = time.monotonic()

    def key(self, kid: str | None) -> jwt.PyJWK:
        self._refresh()
        found = self._keys.get(kid or "")
        if found is None and self.url:
            self._refresh(force=True)
            found = self._keys.get(kid or "")
        if found is None:
            raise Unauthorized("the token was not signed by a known key", "unknown_key")
        return found

    def account_id(self, token: str) -> str:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise Unauthorized("the token is not a JWT", "bad_token") from None
        if header.get("alg") not in ALGORITHMS:
            raise Unauthorized(f"the token's algorithm {header.get('alg')!r} is not accepted", "bad_token")
        key = self.key(header.get("kid"))
        options = {"require": ["sub", "exp"], "verify_aud": self.audience is not None, "verify_iss": self.issuer is not None}
        try:
            claims = jwt.decode(token, key.key, algorithms=[header["alg"]], audience=self.audience, issuer=self.issuer, options=options,
                                leeway=LEEWAY_S)
        except jwt.ExpiredSignatureError:
            raise Unauthorized("the session expired: sign in again", "expired") from None
        except jwt.PyJWTError as exc:
            raise Unauthorized(f"the token is not valid: {exc}", "bad_token") from None
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise Unauthorized("the token names no account", "bad_token")
        return subject


def bearer(authorization: str | None) -> str | None:
    """The token of an ``Authorization: Bearer …`` header, None without one."""
    if not authorization:
        return None
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthorized("use a Bearer token", "bad_token")
    return token.strip()
