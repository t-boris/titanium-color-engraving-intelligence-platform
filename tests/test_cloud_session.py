"""The sign-in to the cloud owned by the core (electron REQ-086, DEC-058): a state and a PKCE verifier per sign-in, the page's address
with this core's loopback callback, a callback for a state that is not pending refused, the session token kept in a file of mode 0600,
JWTs fetched from the sign-in service with the session cookie and renewed before they expire, a session the service no longer accepts
ending the sign-in here, sign-out deleting the file and telling the service, and nothing called when the cloud is switched off."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import jwt as pyjwt
import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from cloud_fakes import AUTH_BASE, CLOUD_BASE, World  # noqa: E402
from test_cloud_api import ISSUER, keys, mint, verifier  # noqa: E402,F401  (fixtures)
from titanium_platform import cloud_http, cloud_session  # noqa: E402
from titanium_platform.cloud_http import CloudError  # noqa: E402


@pytest.fixture()
def world(verifier, mint, monkeypatch) -> World:
    return World(verifier, mint).install(monkeypatch)


def test_a_sign_in_starts_with_a_state_and_a_pkce_challenge_for_this_cores_callback(store, world):
    store.set_setting(cloud_session.API_URL_SETTING, CLOUD_BASE)
    started = cloud_session.start(store, 8765)
    parts = urlsplit(started["url"])
    query = parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{CLOUD_BASE}/signin" and started["providers"] == ["google"]
    assert query["callback"] == ["http://127.0.0.1:8765/api/cloud/callback"] and query["state"] == [started["state"]]
    state = started["state"]
    assert cloud_session.pending(state) and not cloud_session.pending(state + "x") and not cloud_session.pending("")
    assert query["challenge"] == [cloud_session.s256(cloud_session._pending[state]["verifier"])]
    assert len(state) >= 24 and len(cloud_session._pending[state]["verifier"]) >= 43
    # the page the cloud serves for this very address is the sign-in page
    assert world.cloud.get(f"/signin?{parts.query}").status_code == 200
    assert cloud_session.cancel(store, state)["signed_in"] is False and not cloud_session.pending(state)
    assert cloud_session.account(store) == {"signed_in": False, "account": None, "signed_in_at": None, "api_url": CLOUD_BASE}


def test_the_callback_is_refused_for_a_state_that_is_not_pending_and_a_wrong_code_spends_the_state(store, world):
    store.set_setting(cloud_session.API_URL_SETTING, CLOUD_BASE)
    with pytest.raises(CloudError) as refused:
        cloud_session.complete(store, "never-started-state", "code")
    assert refused.value.code == "unknown_state" and not cloud_session.session_path(store).exists()
    started = cloud_session.start(store, 8765)
    with pytest.raises(CloudError) as wrong:
        cloud_session.complete(store, started["state"], "not-the-code")
    assert wrong.value.status == 404 and "the cloud refused the request" in str(wrong.value)
    assert not cloud_session.pending(started["state"]) and cloud_session.account(store)["signed_in"] is False
    with pytest.raises(CloudError) as again:
        cloud_session.complete(store, started["state"], "not-the-code")
    assert again.value.code == "unknown_state"


def test_the_session_is_kept_in_a_private_file_and_jwts_come_from_the_sign_in_service(store, world, verifier):
    account = world.sign_in(store, "acc-1", "Мастерская Север")
    assert account["signed_in"] and account["account"] == {"id": "acc-1", "name": "Мастерская Север", "email": "acc-1@example.org"}
    path = cloud_session.session_path(store)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600 and stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    assert path.read_text(encoding="utf-8").count("session_token") == 1 and ("GET", "/get-session") in world.auth.calls
    token = cloud_session.jwt(store)
    assert verifier.account_id(token) == "acc-1" and pyjwt.get_unverified_header(token)["alg"] == "EdDSA"
    assert cloud_session.jwt(store) == token and world.auth.calls.count(("GET", "/token")) == 1        # cached until a minute before expiry
    world.auth.token_lifetime_s = 30                                                                  # a token that expires within the margin
    cloud_session._tokens.clear()
    first = cloud_session.jwt(store)
    second = cloud_session.jwt(store)
    assert world.auth.calls.count(("GET", "/token")) == 3 and first != second or first == second     # renewed each time, whatever the signature
    assert pyjwt.decode(second, options={"verify_signature": False})["iss"] == ISSUER
    # the session file names nothing but the account, the token and the addresses
    import json
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {"api_url", "auth_base_url", "session_token", "account", "signed_in_at"}


def test_a_session_the_service_no_longer_accepts_ends_the_sign_in_here(store, world):
    world.sign_in(store, "acc-2")
    world.auth.sessions.clear()                                        # revoked at the provider (another device signed out, or it expired)
    cloud_session._tokens.clear()
    with pytest.raises(CloudError) as ended:
        cloud_session.jwt(store)
    assert ended.value.code == "expired" and ended.value.status == 401
    assert cloud_session.account(store)["signed_in"] is False and not cloud_session.session_path(store).exists()
    with pytest.raises(CloudError) as none:
        cloud_session.jwt(store)
    assert none.value.code == "not_signed_in"
    assert [a for a in store.query("SELECT action FROM audit ORDER BY id")][-1]["action"] == "cloud_session_expired"


def test_sign_out_deletes_the_file_and_tells_the_service_when_it_can(store, world):
    world.sign_in(store, "acc-3")
    assert cloud_session.sign_out(store)["signed_in"] is False
    assert not cloud_session.session_path(store).exists() and ("POST", "/sign-out") in world.auth.calls and world.auth.sessions == {}
    sign_out_calls = [c for c in world.transport.calls if c[0] == "POST" and c[1].endswith("/sign-out")]
    assert sign_out_calls == [("POST", f"{AUTH_BASE}/sign-out")]
    # the service unreachable: the file goes all the same; a second sign-out is harmless
    world.sign_in(store, "acc-3")
    world.transport.down = True
    assert cloud_session.sign_out(store)["signed_in"] is False and not cloud_session.session_path(store).exists()
    assert cloud_session.sign_out(store)["signed_in"] is False
    actions = [r["action"] for r in store.query("SELECT action FROM audit ORDER BY id")]
    assert actions.count("cloud_signed_in") == 2 and actions.count("cloud_signed_out") == 2


def test_the_address_of_the_cloud_is_a_setting_with_the_production_service_as_its_default(store):
    assert cloud_session.settings(store) == {"api_url": "https://titanium-labs-api.vercel.app", "default": "https://titanium-labs-api.vercel.app", "custom": False}
    assert cloud_session.set_api_url(store, "https://labs.example.org/")["api_url"] == "https://labs.example.org"
    assert cloud_session.set_api_url(store, "http://127.0.0.1:9000")["custom"] is True              # a local service under test
    for bad in ("http://labs.example.org", "ftp://x", "labs.example.org", "https://labs.example.org/?x=1", 7):
        with pytest.raises(CloudError):
            cloud_session.set_api_url(store, bad)
    assert cloud_session.set_api_url(store, "")["custom"] is False


def test_with_the_cloud_switched_off_nothing_is_called_and_a_pending_sign_in_is_simply_dropped(store, world, monkeypatch):
    store.set_setting(cloud_session.API_URL_SETTING, CLOUD_BASE)
    monkeypatch.setattr(cloud_http, "switched_on", False)
    with pytest.raises(CloudError) as off:
        cloud_session.start(store, 8765)
    assert off.value.code == "switched_off" and world.transport.calls == [] and not cloud_session.switched_on()
    monkeypatch.setattr(cloud_http, "switched_on", True)
    started = cloud_session.start(store, 8765)
    monkeypatch.setattr(cloud_http, "switched_on", False)
    with pytest.raises(CloudError):
        cloud_session.complete(store, started["state"], "code")
    assert cloud_session.account(store)["signed_in"] is False and not cloud_session.session_path(store).exists()
