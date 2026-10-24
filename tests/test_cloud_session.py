"""The sign-in to the cloud owned by the core (electron REQ-086, DEC-058, DEC-060): a state carrying this core's port and a PKCE
verifier per sign-in, the authorization address of the sign-in service built from the cloud's configuration and the service's own
discovery document, a callback for a state that is not pending refused, the refresh token kept in a file of mode 0600, access tokens
renewed with the refresh token before they expire (the rotated refresh token kept at once), a refresh the service refuses ending
the sign-in here, sign-out revoking the refresh token and deleting the file, and nothing called when the cloud is switched off."""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import jwt as pyjwt
import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from cloud_fakes import AUTH_BASE, CLIENT_ID, CLOUD_BASE, RETURN_URI, World  # noqa: E402
from test_cloud_api import ISSUER, keys, mint, verifier  # noqa: E402,F401  (fixtures)
from titanium_platform import cloud_http, cloud_session  # noqa: E402
from titanium_platform.cloud_http import CloudError  # noqa: E402


@pytest.fixture()
def world(verifier, mint, monkeypatch) -> World:
    return World(verifier, mint).install(monkeypatch)


def test_a_sign_in_starts_with_a_state_carrying_this_cores_port_and_a_pkce_challenge(store, world):
    store.set_setting(cloud_session.API_URL_SETTING, CLOUD_BASE)
    started = cloud_session.start(store, 8765)
    parts = urlsplit(started["url"])
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{AUTH_BASE}/oauth2/authorize" and started["providers"] == ["google"]
    state = started["state"]
    assert query == {"response_type": "code", "client_id": CLIENT_ID, "redirect_uri": RETURN_URI, "scope": "openid profile email offline_access",
                     "state": state, "code_challenge": cloud_session.s256(cloud_session._pending[state]["verifier"]), "code_challenge_method": "S256",
                     "resource": CLOUD_BASE}
    assert state.endswith(".8765") and cloud_session.state_port(state) == 8765 and len(state.split(".")[0]) >= 24
    assert all(cloud_session.state_port(bad) is None for bad in ("no-port", "x" * 24 + ".0", "x" * 24 + ".70000", "x.1", state + ".1", ""))
    assert cloud_session.pending(state) and not cloud_session.pending(state + "x") and not cloud_session.pending("")
    assert len(cloud_session._pending[state]["verifier"]) >= 43
    assert ("GET", "/.well-known/oauth-authorization-server") in world.auth.calls                   # the endpoints come from discovery
    # the pages the cloud serves to the browser on the way: the login page and the consent page, with no external script
    for path in ("/signin", "/consent"):
        page = world.cloud.get(path, params={"client_id": CLIENT_ID, "state": state, "redirect_uri": RETURN_URI, "sig": "x"})
        assert page.status_code == 200 and "<script src=" not in page.text and AUTH_BASE in page.text, path
    assert cloud_session.cancel(store, state)["signed_in"] is False and not cloud_session.pending(state)
    assert cloud_session.account(store) == {"signed_in": False, "account": None, "signed_in_at": None, "api_url": CLOUD_BASE}


def test_the_callback_is_refused_for_a_state_that_is_not_pending_and_a_wrong_code_or_a_denial_spends_the_state(store, world):
    store.set_setting(cloud_session.API_URL_SETTING, CLOUD_BASE)
    with pytest.raises(CloudError) as refused:
        cloud_session.complete(store, "never-started-state.1", "code")
    assert refused.value.code == "unknown_state" and not cloud_session.session_path(store).exists()
    started = cloud_session.start(store, 8765)
    with pytest.raises(CloudError) as wrong:
        cloud_session.complete(store, started["state"], "not-the-code")
    assert wrong.value.code == "bad_code" and "refused the code" in str(wrong.value) and "invalid code" in str(wrong.value)
    assert not cloud_session.pending(started["state"]) and cloud_session.account(store)["signed_in"] is False
    with pytest.raises(CloudError) as again:
        cloud_session.complete(store, started["state"], "not-the-code")
    assert again.value.code == "unknown_state"
    # the operator declined on the consent page: nothing is called at the service, the state is spent
    started = cloud_session.start(store, 8765)
    before = len(world.auth.calls)
    with pytest.raises(CloudError) as denied:
        cloud_session.complete(store, started["state"], "", error="access_denied", error_description="The user denied")
    assert denied.value.code == "denied" and len(world.auth.calls) == before and not cloud_session.pending(started["state"])
    started = cloud_session.start(store, 8765)
    with pytest.raises(CloudError) as broken:
        cloud_session.complete(store, started["state"], "", error="server_error", error_description="try later")
    assert broken.value.code == "provider_error" and "try later" in str(broken.value)
    # the right code with the wrong verifier (another launch's) is refused by the service
    started = cloud_session.start(store, 8765)
    state, code = world.auth.authorize(started["url"], "acc-x")
    cloud_session._pending[state]["verifier"] = "another-launch-verifier-of-the-right-length-xxxxxxxxxxxxxx"
    with pytest.raises(CloudError) as mismatch:
        cloud_session.complete(store, state, code)
    assert mismatch.value.code == "bad_code" and "verifier" in str(mismatch.value)


def test_the_refresh_token_is_kept_in_a_private_file_and_access_tokens_are_renewed_with_it(store, world, verifier):
    account = world.sign_in(store, "acc-1", "Мастерская Север")
    assert account["signed_in"] and account["account"] == {"id": "acc-1", "name": "Мастерская Север", "email": "acc-1@example.org"}
    path = cloud_session.session_path(store)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600 and stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    kept = json.loads(path.read_text(encoding="utf-8"))
    assert set(kept) == set(cloud_session.FILE_KEYS) and kept["client_id"] == CLIENT_ID and kept["resource"] == CLOUD_BASE
    assert kept["token_endpoint"] == f"{AUTH_BASE}/oauth2/token" and kept["refresh_token"] in world.auth.refresh
    assert "access_token" not in path.read_text(encoding="utf-8") and ("GET", "/oauth2/userinfo") in world.auth.calls
    token = cloud_session.jwt(store)
    assert verifier.account_id(token) == "acc-1" and pyjwt.get_unverified_header(token)["alg"] == "EdDSA"
    assert cloud_session.jwt(store) == token and world.auth.calls.count(("POST", "/oauth2/token")) == 1    # the exchange; cached since
    world.auth.token_lifetime_s = 30                                                                       # tokens that expire within the margin
    cloud_session._tokens.clear()
    first = cloud_session.jwt(store)
    second = cloud_session.jwt(store)
    assert world.auth.calls.count(("POST", "/oauth2/token")) == 3 and first != token                        # renewed each time (the same
    assert second != token                                                                                # second may mint equal tokens)
    rotated = json.loads(path.read_text(encoding="utf-8"))["refresh_token"]
    assert rotated != kept["refresh_token"] and rotated in world.auth.refresh and kept["refresh_token"] not in world.auth.refresh
    assert pyjwt.decode(second, options={"verify_signature": False})["iss"] == ISSUER


def test_a_refresh_the_service_no_longer_accepts_ends_the_sign_in_here(store, world):
    world.sign_in(store, "acc-2")
    world.auth.refresh.clear()                                         # revoked at the provider (signed out elsewhere, or a month passed)
    cloud_session._tokens.clear()
    with pytest.raises(CloudError) as ended:
        cloud_session.jwt(store)
    assert ended.value.code == "expired" and ended.value.status == 401
    assert cloud_session.account(store)["signed_in"] is False and not cloud_session.session_path(store).exists()
    with pytest.raises(CloudError) as none:
        cloud_session.jwt(store)
    assert none.value.code == "not_signed_in"
    assert [a for a in store.query("SELECT action FROM audit ORDER BY id")][-1]["action"] == "cloud_session_expired"


def test_sign_out_revokes_the_refresh_token_and_deletes_the_file_whatever_the_service_says(store, world):
    world.sign_in(store, "acc-3")
    kept = json.loads(cloud_session.session_path(store).read_text(encoding="utf-8"))["refresh_token"]
    assert cloud_session.sign_out(store)["signed_in"] is False
    assert not cloud_session.session_path(store).exists() and ("POST", "/oauth2/revoke") in world.auth.calls and kept not in world.auth.refresh
    revocations = [c for c in world.transport.calls if c[0] == "POST" and c[1].endswith("/oauth2/revoke")]
    assert revocations == [("POST", f"{AUTH_BASE}/oauth2/revoke")]
    # the service unreachable: the file goes all the same; a second sign-out is harmless
    world.sign_in(store, "acc-3")
    world.transport.down = True
    assert cloud_session.sign_out(store)["signed_in"] is False and not cloud_session.session_path(store).exists()
    assert cloud_session.sign_out(store)["signed_in"] is False
    actions = [r["action"] for r in store.query("SELECT action FROM audit ORDER BY id")]
    assert actions.count("cloud_signed_in") == 2 and actions.count("cloud_signed_out") == 2


def test_a_cloud_without_sign_in_or_a_service_naming_another_issuer_is_refused_before_the_browser_opens(store, world, verifier, mint, monkeypatch):
    store.set_setting(cloud_session.API_URL_SETTING, CLOUD_BASE)
    from titanium_cloud.app import create_app as create_cloud
    from titanium_cloud.settings import Settings
    from fastapi.testclient import TestClient
    bare = TestClient(create_cloud(Settings(repository="memory", auth_base_url=AUTH_BASE), verifier=verifier))     # no client id
    world.transport.targets[CLOUD_BASE] = bare
    with pytest.raises(CloudError) as unconfigured:
        cloud_session.start(store, 8765)
    assert unconfigured.value.code == "no_auth"
    world.transport.targets[CLOUD_BASE] = world.cloud
    from fastapi import FastAPI
    other = FastAPI()

    @other.get("/.well-known/oauth-authorization-server")
    def discovery():
        return {"issuer": "https://someone-else.test/auth", "authorization_endpoint": f"{AUTH_BASE}/oauth2/authorize", "token_endpoint": f"{AUTH_BASE}/oauth2/token"}

    world.transport.targets[AUTH_BASE] = TestClient(other)
    with pytest.raises(CloudError) as issuer:
        cloud_session.start(store, 8765)
    assert issuer.value.code == "issuer" and cloud_session._pending == {} or all(not s.endswith(".8765") for s in cloud_session._pending)


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
