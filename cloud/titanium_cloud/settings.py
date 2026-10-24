"""What the service is configured with, from the environment (Vercel's project settings in production; a test passes a Settings of its
own). Nothing here is a secret of the repository: DATABASE_URL and the Neon Auth addresses are set where the service runs."""
from __future__ import annotations

import os
from dataclasses import dataclass

CHUNK_BYTES = 1024 * 1024                      # one chunk of a release (DEC-028, DEC-058): under the Functions request limits
UPLOAD_LIFETIME_S = 24 * 3600                  # a publication that is not finalized expires after this
INVITATION_LIFETIME_S = 14 * 24 * 3600
OAUTH_PROVIDERS = ("google",)                  # the social providers switched on in Neon Auth, offered on the sign-in page


@dataclass(frozen=True)
class Settings:
    repository: str = "memory"                 # "memory" (tests, local smoke) or "postgres"
    database_url: str | None = None            # the connection of the non-privileged role app_api
    jwks_url: str | None = None                # Neon Auth's JWKS address
    jwks_json: str | None = None               # an inline JWKS instead of the address (tests, local smoke)
    issuer: tuple[str, ...] | str | None = None     # the issuers tokens may carry (Neon Auth's host for its JWT plugin, its base URL for OAuth); unset = not checked
    audience: tuple[str, ...] | str | None = None   # the audiences tokens may carry (the same host; this service's address for OAuth); unset = not checked
    public_base_url: str | None = None         # the address invitation links point at (the service itself when unset)
    auth_base_url: str | None = None           # Neon Auth's base URL (…/<database>/auth): the sign-in page calls it from the browser
    oauth_providers: tuple[str, ...] = OAUTH_PROVIDERS
    oauth_client_id: str | None = None         # the desktop's public OAuth client at Neon Auth (signin.py); unset = no sign-in pages (503)
    resource: str | None = None                # the protected resource the desktop asks tokens for (this service's address when unset)
    chunk_bytes: int = CHUNK_BYTES
    upload_lifetime_s: int = UPLOAD_LIFETIME_S
    invitation_lifetime_s: int = INVITATION_LIFETIME_S

    @classmethod
    def from_environment(cls, env: dict | None = None) -> "Settings":
        env = os.environ if env is None else env
        url = env.get("DATABASE_URL") or None
        kind = env.get("CLOUD_REPOSITORY") or ("postgres" if url else "memory")
        if kind not in ("memory", "postgres"):
            raise ValueError(f"CLOUD_REPOSITORY must be memory or postgres, not {kind!r}")
        if kind == "postgres" and not url:
            raise ValueError("DATABASE_URL is required for the postgres repository")
        return cls(repository=kind, database_url=url, jwks_url=env.get("NEON_AUTH_JWKS_URL") or None,
                   jwks_json=env.get("NEON_AUTH_JWKS_JSON") or None, issuer=_names(env.get("NEON_AUTH_ISSUER")),
                   audience=_names(env.get("NEON_AUTH_AUDIENCE")), public_base_url=(env.get("PUBLIC_BASE_URL") or "").rstrip("/") or None,
                   auth_base_url=(env.get("NEON_AUTH_BASE_URL") or "").rstrip("/") or None,
                   oauth_providers=tuple(p.strip().lower() for p in (env.get("CLOUD_OAUTH_PROVIDERS") or ",".join(OAUTH_PROVIDERS)).split(",")
                                         if p.strip()),
                   oauth_client_id=(env.get("CLOUD_OAUTH_CLIENT_ID") or "").strip() or None,
                   resource=(env.get("CLOUD_RESOURCE") or "").rstrip("/") or None,
                   chunk_bytes=int(env.get("CLOUD_CHUNK_BYTES") or CHUNK_BYTES),
                   upload_lifetime_s=int(env.get("CLOUD_UPLOAD_LIFETIME_S") or UPLOAD_LIFETIME_S),
                   invitation_lifetime_s=int(env.get("CLOUD_INVITATION_LIFETIME_S") or INVITATION_LIFETIME_S))


def _names(value: str | None) -> tuple[str, ...] | None:
    """A comma-separated environment value as a tuple of names, None when empty."""
    names = tuple(v.strip() for v in (value or "").split(",") if v.strip())
    return names or None
