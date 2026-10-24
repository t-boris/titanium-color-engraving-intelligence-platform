# The cloud of laboratories

The service behind «Лаборатории» in the desktop (electron REQ-086, REQ-087; DEC-058): a catalogue of laboratories, their releases
(`.tcelab` files, published in chunks and validated with the very reader the desktop uses), withdrawals, and invitation-only private
laboratories. FastAPI on Vercel, Postgres on Neon with row-level security, sign-in by Neon Auth (its OAuth provider for the desktop;
JWTs verified against its JWKS).

## Layout

| Path | What |
|---|---|
| `index.py` | Vercel's entrypoint: the `app` instance (`uvicorn cloud.index:app` locally, from the repository root) |
| `titanium_cloud/app.py` | `create_app(settings, repository=…, verifier=…)`: routes, error shape `{"error", "code"}` |
| `titanium_cloud/routes.py` | the endpoints and their status codes |
| `titanium_cloud/auth.py` | bearer tokens against a JWKS: RS256, ES256, EdDSA (Neon Auth signs with Ed25519); key by `kid`, refresh on an unknown one |
| `titanium_cloud/repository.py` | the storage contract, `InMemoryRepository` (tests, local runs) and `PostgresRepository` (psycopg 3, one connection per request as `app_api`) |
| `titanium_cloud/finalize.py` | what makes an upload a release: streamed through `_lab_format.read`, hashes, schema, the reserved identity |
| `titanium_cloud/_lab_format.py`, `titanium_cloud/schemas/` | byte-equal copies of `src/titanium_platform/lab_format.py` and the schema (`tools/sync_shared.py` refreshes them; `tests/test_cloud_shared.py` fails on drift) |
| `migrations/0001_schema.sql` | tables, the role `app_api`, policies |
| `tools/migrate.py` | applies `migrations/*.sql` in order as the owner, records them in `schema_migration` |
| `tools/app_api_password.py` | gives `app_api` a random password and writes `APP_API_DATABASE_URL` to `~/.titanium-cloud.env` |
| `tests_live/` | the main suite's contract tests against the real database, plus the RLS checks (not collected by the main suite) |
| `requirements.txt`, `.python-version` | what Vercel installs (Python 3.12) |

The main suite (`tests/test_cloud_api.py`) runs the whole contract against the in-memory repository; `tools/cloud_smoke.py` at the
repository root publishes and reads a release end to end against a running service.

## Endpoints

Public, no token: `GET /health`, `GET /labs`, `GET /labs/{id}`, `GET /labs/{id}/releases`, `GET /releases/{id}/manifest`,
`GET /releases/{id}/chunks/{n}`, `GET /releases/{id}/withdrawals`. With a token the same calls also show the caller's private
laboratories and the ones they are a member of.

Owner only (token of the laboratory's owner): `POST /labs`, `POST /labs/{id}/publications` (reserve: release id and number),
`PUT /publications/{id}/chunks/{n}`, `POST /publications/{id}/finalize` (body: `file_sha256`, `byte_size`, `chunk_count`),
`GET /publications/{id}`, `POST /releases/{id}/withdraw`, `POST /labs/{id}/invitations`, `GET /labs/{id}/invitations`,
`DELETE /labs/{id}/invitations/{iid}`, `GET /labs/{id}/members`, `DELETE /labs/{id}/members/{account}`.

Any signed-in account: `POST /invitations/{token}/accept`.

Sign-in (`titanium_cloud/signin.py`; the desktop's side is `titanium_platform/cloud_session.py`, DEC-060): Neon Auth is an OAuth 2.1
authorization server for this service (its OAuth provider plugin, enabled on the Neon branch with `https://titanium-labs-api.vercel.app/signin`
as the login page, `/consent` as the consent page and `https://titanium-labs-api.vercel.app` as the protected resource; the desktop is the
managed public client «Titanium Workshop» with PKCE and the one redirect URI `/auth/return`). `GET /auth/config` tells the desktop Neon
Auth's address, the client id, the resource, the redirect address and the social providers; the desktop opens Neon Auth's authorization
endpoint in the browser with `state=<random>.<its loopback port>`; Neon Auth sends the browser to `GET /signin` (the self-contained
Russian login page, which signs the operator in from the browser and passes the signed request back as `oauth_query`), then to
`GET /consent` (approved once per account), then to `GET /auth/return?state&code`, which answers 302 to
`http://127.0.0.1:<port>/api/cloud/callback?state&code` and nothing else (400 for a malformed state). The desktop exchanges the code and
its verifier at Neon Auth's token endpoint for an access token (an EdDSA JWT with `iss` the Neon Auth base URL and `aud` containing this
service's address, an hour) and a refresh token (thirty days, rotated on every use); this service keeps nothing of a sign-in.

Status codes: 401 no or invalid token; 403 signed in but not the owner; 404 unknown, or a private laboratory the caller may not see
(never a hint that it exists); 409 the expected previous release is not the latest, the origin is taken, a key is reused, a finalized
publication is changed; 410 an expired publication, a spent or revoked invitation; 413 a chunk above `CLOUD_CHUNK_BYTES` or a release
above the reader's policy; 422 a release that is not acceptable (the `code` names the first problem: `lab_mismatch`, `release_id`,
`release_number`, `author`, `lab_name`, `file_hash`, `size`, `chunk_size`, `chunks_missing`, or the reader's own codes).

Publishing: reserve first (`idempotency_key`, `expected_previous_release_id`), export the release with the reserved `release_id` and
`release_number`, upload the chunks of `chunk_bytes` each, finalize with the file's hash, size and chunk count. The same key returns the
same reservation; finalize repeated with the same declaration returns the release again (`repeated: true`). Two publishers who reserve
against the same latest release both get the next number; the second to finalize gets 409 and must reserve again. Nothing of a
publication is visible before finalize succeeds; a failed validation keeps the uploaded chunks so the author can replace the wrong one.

## Environment

The Vercel project (`titanium-labs-api`, root directory `cloud`) needs:

| Variable | Value |
|---|---|
| `DATABASE_URL` | the `app_api` connection string (the pooled host is fine: the account is set per transaction) |
| `NEON_AUTH_JWKS_URL` | Neon Auth's JWKS |
| `NEON_AUTH_ISSUER` | the issuers tokens may carry, comma-separated: Neon Auth's host (its JWT plugin's tokens, used by the live tests) and its base URL (the desktop's OAuth access tokens); unset = not checked |
| `NEON_AUTH_AUDIENCE` | the audiences tokens may carry, comma-separated: Neon Auth's host and this service's address (`CLOUD_RESOURCE`); unset = not checked |
| `PUBLIC_BASE_URL` | optional, for invitation links (`{base}/invitations/{token}`) |
| `NEON_AUTH_BASE_URL` | Neon Auth's base URL (`…/<database>/auth`), called by the sign-in page from the browser; unset = no sign-in page (503) |
| `CLOUD_OAUTH_PROVIDERS` | optional; the social providers switched on in Neon Auth, offered on the sign-in page (default `google`) |
| `CLOUD_OAUTH_CLIENT_ID` | the desktop's public OAuth client at Neon Auth (created on the branch's OAuth provider); unset = no sign-in pages (503) |
| `CLOUD_RESOURCE` | optional; the protected resource the desktop asks tokens for (`PUBLIC_BASE_URL` when unset) |
| `CLOUD_REPOSITORY` | `postgres` (the default when `DATABASE_URL` is set); `memory` for a local run without a database |
| `CLOUD_CHUNK_BYTES`, `CLOUD_UPLOAD_LIFETIME_S`, `CLOUD_INVITATION_LIFETIME_S` | optional; 1 MiB, one day, fourteen days |
| `NEON_AUTH_JWKS_JSON` | a JWKS inline instead of a URL (tests and the local smoke) |

No secret is in the repository: the owner connection and the ids live in `~/.titanium-cloud.env` (mode 0600), which the tools read.

## Database

```
.venv/bin/python cloud/tools/migrate.py --status        # what is pending
.venv/bin/python cloud/tools/migrate.py                 # apply, as the owner (DATABASE_URL of ~/.titanium-cloud.env)
.venv/bin/python cloud/tools/app_api_password.py        # once: the API role's password → APP_API_DATABASE_URL in ~/.titanium-cloud.env
```

Row-level security is enabled on every table (not forced: the owner role runs migrations and the live tests' cleanup). The API
connects as `app_api`, which can only read and write through the policies, keyed on `current_setting('app.account_id')`, set by the
repository inside every transaction. Cross-table checks (`cloud_owns_lab`, `cloud_is_member`, `cloud_can_read_lab`, …) are
`SECURITY DEFINER` functions, so a policy never recurses into another policy. Chunks of public releases are readable by everyone;
the chunks of an unfinished publication only by its owner. `cloud_accept_invitation` is the one write a non-owner makes, inside a
definer function that checks the token's hash, expiry and that it is unused. The handoff table of migration 0002 was dropped by migration 0003 (DEC-060: the service keeps nothing of a sign-in).
The service's origin (`https://titanium-labs-api.vercel.app`) must be a trusted
domain of Neon Auth, or the browser page's calls to it are refused with `INVALID_ORIGIN`.

## Tests

```
.venv/bin/python -m pytest -q tests/test_cloud_api.py tests/test_cloud_shared.py    # in the main suite, in memory
.venv/bin/python -m pytest -q cloud/tests_live                                        # against Neon; skipped without the env file
.venv/bin/python tools/cloud_smoke.py                                                 # local uvicorn, in-memory catalogue
CLOUD_BASE_URL=https://… CLOUD_TOKEN=… .venv/bin/python tools/cloud_smoke.py          # a deployment; writes docs/features/electron/cloud-smoke-<date>.md
```

The live tests create laboratories under accounts named `test-…-<random>` and delete, as the owner, only those rows afterwards.
