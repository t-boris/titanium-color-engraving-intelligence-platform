# Cloud sign-in against the deployed service, 2026-10-24 (feature electron, REQ-086, DEC-058, DEC-060)

## Why the design changed

The sign-in of DEC-058 had the browser page hand Neon Auth's session token to the cloud and the desktop turn it into JWTs at
`GET <auth>/token`. Probed against the real Neon Auth on 2026-10-24 (project `titanium-labs`, branch main):

| call | with the bare session token (the `token` of the sign-in JSON) | with the signed cookie the browser holds |
|---|---|---|
| `GET /get-session`, cookie | 200 `null` | 200, the session and user, `set-auth-jwt` header |
| `GET /get-session`, `Authorization: Bearer` | 200 `null` | 200 `null` |
| `GET /token`, cookie | 401 | 200, a JWT |
| `GET /token`, `Authorization: Bearer` | 401 | 401 |

Only the signed cookie value (`<token>.<HMAC>`, signed with Neon's secret) authenticates, and it is `HttpOnly`, so no page can read it
for the desktop. Neon Auth exposes no bearer, device-code, API-key or one-time-token plugin (its OpenAPI document lists 79 routes; the
supported plugins are Admin, Email OTP, JWT, Magic Link, OAuth Provider, Organization, Open API, Phone Number). Its OAuth provider is
the documented way for "a desktop app or CLI" to sign users in: the authorization code flow with PKCE, access tokens as EdDSA JWTs
for a named resource, refresh tokens of thirty days rotated on every use. DEC-060 adopts it.

## What was set up on Neon (Console API, 2026-10-24 18:30 UTC)

- OAuth provider enabled on branch `br-curly-dust-b754kh21`: login page `https://titanium-labs-api.vercel.app/signin`, consent page
  `https://titanium-labs-api.vercel.app/consent`, protected resource `https://titanium-labs-api.vercel.app`.
- Managed public client «Titanium Workshop», `client_id uuftXbnCKvixZxlXIknNvggUDzZtlmHT`, redirect URI
  `https://titanium-labs-api.vercel.app/auth/return`, resource as above, consent not skipped (the id of a public client is not a secret;
  it is served by `GET /auth/config`).
- Discovery at `<auth>/.well-known/oauth-authorization-server`: issuer = the Neon Auth base URL, endpoints `/oauth2/authorize`,
  `/oauth2/token`, `/oauth2/userinfo`, `/oauth2/revoke`, scopes `openid profile email offline_access`, `S256` only.
- Vercel production environment: `NEON_AUTH_ISSUER` = the host and the base URL, `NEON_AUTH_AUDIENCE` = the host and
  `https://titanium-labs-api.vercel.app`, `CLOUD_OAUTH_CLIENT_ID`, `CLOUD_RESOURCE`, `PUBLIC_BASE_URL`; migration 0003 dropped the
  handoff table.

## The flow, scripted end to end against production

Observed with the smoke account through Neon Auth and the deployed service (the browser's part emulated with its session cookie):

1. authorize without a session → 302 to `/signin` with the signed request (`ba_param`, `sig`, `exp`, the client's parameters);
   `POST /sign-in/email {…, oauth_query}` → `{redirect: true, url: /consent?…}`; `POST /oauth2/continue` for a signed-in browser → the same.
2. `POST /oauth2/consent {accept: true, oauth_query}` → `{redirect: true, url: https://titanium-labs-api.vercel.app/auth/return?code&state&iss}`;
   the consent is remembered: the next authorize of a signed-in browser goes straight to `/auth/return`.
3. `POST /oauth2/token` (form, `client_id` in the body, `code_verifier`, `redirect_uri`, `resource`) → access token (EdDSA JWT, 3600 s,
   `aud` = [the resource, the userinfo endpoint], `iss` = the base URL, `sub` = the account id, `client_id`, `scope`), refresh token,
   id token; `GET /oauth2/userinfo` → `sub`, `name`, `email`.
4. refresh → a new pair; the old refresh token presented again → `invalid_grant`, and the whole sign-in is revoked ("session not found"
   for the new one too): the core keeps the rotated token on disk before using it and serialises refreshes.

Then through the real core (`cloud_session`, `cloud_client`) in a temporary workshop against production:

| step | result |
|---|---|
| `start` | authorization address of Neon Auth, state `<random>.8765`, providers `['google']` |
| browser (signed in, consent remembered) | 302 `/auth/return` → 302 `http://127.0.0.1:8765/api/cloud/callback?state&code` |
| `complete` | signed in as «TCE smoke», `tce-smoke@example.com` |
| `jwt` | `aud` contains the service's address, `iss` the base URL, lifetime 3600 s |
| `catalogue` with the token | `signed_in: true`, labs `['Smoke laboratory']` (the service verified the OAuth token) |
| forced refresh | a new access token, the refresh token in `cloud/session.json` rotated; `own` answers with it |
| `sign_out` | the refresh token revoked, the file gone |

Tests: `tests/test_cloud_session.py` (8), `tests/test_cloud_routes.py` (2), `tests/test_cloud_api.py` (the pages, the return, the
verifier with several issuers and audiences), `tests/cloud_fakes.py` (an OAuth look-alike with rotation and family revocation);
the full suite 2190 passed, none skipped.

Open: a sign-in with a real browser and Google (shared provider) from the application window is an operator check, as the first
consent screen; the smoke account's consent is remembered on Neon.
