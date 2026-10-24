"""Access from a tablet on the local network (electron REQ-082, DEC-047): the workshop's CA and server certificate, the pairing code, the
devices and their tokens, the guard's treatment of requests from the network, the TLS server started and stopped at will, and the
switches of what the application may reach outside this computer (REQ-080)."""
from __future__ import annotations

import http.cookiejar
import ipaddress
import json
import os
import ssl
import stat
import sys
import urllib.error
import urllib.request
from datetime import timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from titanium_platform import fonts, lan, outbound, research
from titanium_platform import setup as su
from titanium_platform.api import security
from titanium_platform.api.app import create_app
from titanium_platform.db import Store

TABLET = "https://192.168.1.20:8766"


# -- certificates ----------------------------------------------------------------------------------------------------------------
def test_the_workshop_ca_is_made_once_and_the_server_certificate_follows_the_addresses(tmp_path):
    first = lan.certificates(tmp_path, ["192.168.1.20", "Studio.local"], "North")
    ca = x509.load_pem_x509_certificate(first.ca_pem())
    server = x509.load_pem_x509_certificate(first.cert_path.read_bytes())
    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is True
    assert "North" in ca.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
    assert first.fingerprint == ":".join(f"{b:02X}" for b in ca.fingerprint(hashes.SHA256())) and len(first.fingerprint) == 95
    names = server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert set(names.get_values_for_type(x509.DNSName)) == {"localhost", "studio.local"}
    assert set(names.get_values_for_type(x509.IPAddress)) == {ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("192.168.1.20")}
    assert x509.ExtendedKeyUsageOID.SERVER_AUTH in server.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert server.not_valid_after_utc - server.not_valid_before_utc <= timedelta(days=825)        # what tablets accept
    ca.public_key().verify(server.signature, server.tbs_certificate_bytes, ec.ECDSA(server.signature_hash_algorithm))
    if sys.platform != "win32":
        for key in (first.key_path, tmp_path / "lan" / "ca.key"):
            assert stat.S_IMODE(key.stat().st_mode) == 0o600
    again = lan.certificates(tmp_path, ["studio.local", "192.168.1.20"], "North")
    assert x509.load_pem_x509_certificate(again.cert_path.read_bytes()).serial_number == server.serial_number     # same hosts: kept
    moved = lan.certificates(tmp_path, ["10.0.0.7", "studio.local"], "North")
    renewed = x509.load_pem_x509_certificate(moved.cert_path.read_bytes())
    assert renewed.serial_number != server.serial_number and moved.fingerprint == first.fingerprint                # new address: new server cert, same CA
    assert ipaddress.ip_address("10.0.0.7") in renewed.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)


# -- pairing codes and devices ---------------------------------------------------------------------------------------------------
def test_a_pairing_code_has_six_digits_a_short_life_one_use_and_a_few_attempts():
    clock = [1000.0]
    codes = lan.PairingCodes(ttl_s=300, attempts=3, clock=lambda: clock[0])
    assert codes.current() is None
    with pytest.raises(su.ValidationError, match="there is no pairing code now"):
        codes.redeem("123456")
    made = codes.new()
    assert len(made["code"]) == 6 and made["code"].isdigit() and made["expires_in_s"] == 300
    clock[0] += 100
    assert codes.current()["expires_in_s"] == 200
    with pytest.raises(su.ValidationError, match="the pairing code is wrong"):
        codes.redeem("000000" if made["code"] != "000000" else "111111")
    codes.redeem(made["code"])                                   # spent
    with pytest.raises(su.ValidationError, match="there is no pairing code now"):
        codes.redeem(made["code"])
    made = codes.new()
    clock[0] += 301
    with pytest.raises(su.ValidationError, match="there is no pairing code now"):   # expired
        codes.redeem(made["code"])
    made = codes.new()
    wrong = "999999" if made["code"] != "999999" else "888888"
    for _ in range(2):
        with pytest.raises(su.ValidationError, match="is wrong"):
            codes.redeem(wrong)
    with pytest.raises(su.ValidationError, match="too many times"):
        codes.redeem(wrong)
    assert codes.current() is None                                # cancelled: the right code no longer works either
    with pytest.raises(su.ValidationError, match="there is no pairing code now"):
        codes.redeem(made["code"])


def test_a_device_is_known_by_the_hash_of_its_token_and_loses_access_when_revoked(store):
    device, token = lan.pair(store, "  iPad of the bench ")
    assert device["name"] == "iPad of the bench" and device["revoked_at"] is None
    assert token not in json.dumps([dict(r) for r in store.query("SELECT * FROM device")])      # only the hash is kept
    assert lan.authenticate(store, token)["id"] == device["id"]
    assert lan.authenticate(store, token[:-1] + ("a" if token[-1] != "a" else "b")) is None
    assert lan.authenticate(store, None) is None
    assert lan.device(store, device["id"])["last_seen_at"] is not None
    renamed = lan.rename(store, device["id"], "Tablet 2")
    assert renamed["name"] == "Tablet 2"
    with pytest.raises(su.ValidationError, match="one to 64 characters"):
        lan.rename(store, device["id"], " ")
    with pytest.raises(KeyError, match="there is no device 99"):
        lan.revoke(store, 99)
    revoked = lan.revoke(store, device["id"])
    assert revoked["revoked_at"] is not None and lan.authenticate(store, token) is None
    assert lan.revoke(store, device["id"])["revoked_at"] == revoked["revoked_at"]            # revoking again changes nothing
    other, _ = lan.pair(store, "New")
    assert [d["id"] for d in lan.devices(store)] == [other["id"], device["id"]]               # active first


def test_the_lan_settings_are_validated_and_default_to_port_8766(store):
    assert lan.settings(store)["port"] == 8766 and lan.settings(store)["enabled"] is False and lan.settings(store)["name"]
    with pytest.raises(su.ValidationError, match="between 1024 and 65535"):
        lan.save_settings(store, {"port": 80})
    with pytest.raises(su.ValidationError, match="between 1024 and 65535"):
        lan.save_settings(store, {"port": True})
    with pytest.raises(su.ValidationError, match="one to 64 characters"):
        lan.save_settings(store, {"name": "x" * 65})
    assert lan.save_settings(store, {"port": 9443, "name": " Bench "}) == {"enabled": False, "port": 9443, "name": "Bench"}
    assert lan.settings(store)["port"] == 9443


# -- the guard and the API, seen from the owner's computer and from a tablet ----------------------------------------------------------
@pytest.fixture()
def owner(tmp_path):
    with TestClient(create_app(tmp_path / "data"), base_url="http://127.0.0.1") as client:
        yield client


@pytest.fixture()
def tablet(owner):
    """A client whose requests arrive through the LAN server (lan.Entry marks them), over https from a LAN address."""
    return TestClient(lan.Entry(owner.app), base_url=TABLET)


def test_an_unpaired_tablet_reaches_only_the_pairing_page_the_pairing_call_and_the_ca(owner, tablet):
    sent = tablet.get("/", follow_redirects=False)
    assert sent.status_code == 303 and sent.headers["location"] == "/pair"
    assert tablet.get("/index.html", follow_redirects=False).status_code == 303
    refused = tablet.get("/api/health")
    assert refused.status_code == 403 and "pair this tablet" in refused.json()["error"]
    assert tablet.post("/api/materials", json={"name": "x"}).status_code == 403
    page = tablet.get("/pair")
    assert page.status_code == 200 and "Подключение планшета" in page.text and owner.get("/api/lan").json()["fingerprint"] in page.text
    assert page.headers["cache-control"] == "no-store"
    ca = tablet.get("/api/lan/ca")
    assert ca.status_code == 200 and ca.content.startswith(b"-----BEGIN CERTIFICATE-----") and "titanium-workshop-ca.crt" in ca.headers["content-disposition"]
    assert tablet.post("/api/lan/pair", json={"code": "123456", "name": "iPad"}).status_code == 422          # no code yet: refused, not 403


def test_a_tablet_pairs_with_the_code_keeps_a_secure_cookie_and_works_until_revoked(owner, tablet):
    status = owner.get("/api/lan").json()
    assert status["code"] is None and status["enabled"] is False and status["devices"] == []
    code = owner.post("/api/lan/code").json()["code"]
    assert owner.get("/api/lan").json()["code"]["code"] == code
    wrong = tablet.post("/api/lan/pair", json={"code": "000000" if code != "000000" else "111111", "name": "iPad"})
    assert wrong.status_code == 422 and "is wrong" in wrong.json()["error"]
    assert tablet.post("/api/lan/pair", json={"code": code, "name": ""}).status_code == 422                # a bad name does not spend the code
    paired = tablet.post("/api/lan/pair", json={"code": code, "name": "iPad <b>bench</b>"})
    assert paired.status_code == 200 and paired.json()["device"]["name"] == "iPad <b>bench</b>"
    cookie = paired.headers["set-cookie"]
    assert cookie.startswith(lan.COOKIE + "=") and "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert code not in cookie
    assert tablet.post("/api/lan/pair", json={"code": code, "name": "again"}).status_code == 422          # spent
    assert tablet.get("/api/health").status_code == 200
    assert tablet.get("/", follow_redirects=False).status_code == 200                                       # the application itself
    assert tablet.post("/api/materials", json={"name": "x"}).status_code != 403                           # changes are the device's to make
    assert tablet.post("/api/pairs", files={"lightburn": ("a.lbrn2", b"<x/>", "text/xml")}, data={}).status_code != 403   # the upload flow is reached
    for owner_only in ("/api/lan", "/api/lan/devices", "/api/network", "/api/workshop"):
        refused = tablet.get(owner_only)
        assert refused.status_code == 403 and "workshop's own computer" in refused.json()["error"], owner_only
    assert tablet.post("/api/lan/code").status_code == 403
    devices = owner.get("/api/lan/devices").json()
    assert [d["name"] for d in devices] == ["iPad <b>bench</b>"] and devices[0]["last_seen_at"] is not None
    assert owner.put(f"/api/lan/devices/{devices[0]['id']}", json={"name": "Bench"}).json()["name"] == "Bench"
    revoked = owner.post(f"/api/lan/devices/{devices[0]['id']}/revoke").json()
    assert revoked["revoked_at"] is not None
    assert tablet.get("/api/health").status_code == 403                                                    # the next request is refused
    assert owner.post("/api/lan/devices/999/revoke").status_code == 404
    bare = TestClient(lan.Entry(owner.app), base_url=TABLET)                                              # no cookie at all
    assert bare.get("/api/health").status_code == 403


def test_the_desktop_session_is_never_opened_from_the_network_and_a_paired_tablet_needs_none(tmp_path, monkeypatch):
    monkeypatch.setenv(security.SECRET_ENV, "launch-secret")
    with TestClient(create_app(tmp_path / "data"), base_url="http://127.0.0.1") as shell:
        tablet = TestClient(lan.Entry(shell.app), base_url=TABLET)
        refused = tablet.get("/session/launch-secret", follow_redirects=False)
        assert refused.status_code == 403 and "not opened from the network" in refused.json()["error"]
        assert "set-cookie" not in refused.headers
        assert shell.get("/session/launch-secret", follow_redirects=False).status_code == 303           # not spent by the tablet's try
        code = shell.post("/api/lan/code").json()["code"]
        assert tablet.post("/api/lan/pair", json={"code": code, "name": "iPad"}).status_code == 200
        assert tablet.get("/api/health").status_code == 200                                               # the device cookie, no session
        assert tablet.get("/session/launch-secret", follow_redirects=False).status_code == 403
        assert tablet.get("/api/lan").status_code == 403


def test_the_host_of_a_request_may_be_a_name_of_this_computer_on_the_network(owner):
    host = next(iter(owner.app.state.guard.lan_hosts))
    assert owner.get("/api/health", headers={"Host": f"{host}:8766"}).status_code == 200
    assert owner.get("/api/health", headers={"Host": "evil.example"}).status_code == 421


# -- the TLS server --------------------------------------------------------------------------------------------------------------
def _opener(ca_pem: bytes):
    context = ssl.create_default_context(cadata=ca_pem.decode("ascii"))
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def test_the_lan_server_starts_with_the_workshop_certificate_when_enabled_and_stops_when_switched_off(tmp_path):
    store = Store(tmp_path / "data")
    store.set_setting(lan.SETTING, {"enabled": True, "port": 0, "name": "Bench"})          # port 0: a free one (the tests only)
    store.close()
    assert os.environ[lan.BIND_ENV] == "127.0.0.1"
    with TestClient(create_app(tmp_path / "data"), base_url="http://127.0.0.1") as owner:
        running = owner.app.state.lan
        assert running.running and running.port > 0, running.error
        status = owner.get("/api/lan").json()
        assert status["running"] is True and status["bound_port"] == running.port
        base = f"https://127.0.0.1:{running.port}"
        opener = _opener(running.certs.ca_pem())
        with pytest.raises(urllib.error.URLError):                                             # without the workshop's CA the certificate is unknown
            urllib.request.urlopen(base + "/api/lan/ca", timeout=10)
        with opener.open(base + "/api/lan/ca", timeout=10) as answer:                           # with it, TLS verifies the server
            assert answer.status == 200 and b"BEGIN CERTIFICATE" in answer.read()
        with pytest.raises(urllib.error.HTTPError) as refused:
            opener.open(base + "/api/health", timeout=10)
        assert refused.value.code == 403
        code = owner.post("/api/lan/code").json()["code"]
        request = urllib.request.Request(base + "/api/lan/pair", data=json.dumps({"code": code, "name": "iPad"}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        with opener.open(request, timeout=10) as answer:
            assert answer.status == 200
        with opener.open(base + "/api/health", timeout=10) as answer:
            assert json.loads(answer.read())["status"] == "ok"
        with opener.open(base + "/", timeout=10) as answer:
            assert answer.status == 200 and b"<html" in answer.read(4096).lower()
        assert owner.get("/api/health").status_code == 200                                     # the loopback server, as before
        assert owner.put("/api/lan", json={"enabled": False}).json()["running"] is False
        assert not running.running
        with pytest.raises(urllib.error.URLError):
            opener.open(base + "/api/health", timeout=5)
        assert owner.get("/api/health").status_code == 200                                     # the loopback server is untouched
        assert owner.put("/api/lan", json={"enabled": True}).json()["running"] is True        # on again at runtime
        port2 = owner.app.state.lan.port
        with _opener(running.certs.ca_pem()).open(f"https://127.0.0.1:{port2}/pair", timeout=10) as answer:
            assert answer.status == 200
    assert not running.running                                                                 # stopped with the application


def test_a_port_that_cannot_be_opened_leaves_the_network_off_with_the_reason(tmp_path):
    import socket
    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen(1)
    port = taken.getsockname()[1]
    try:
        with TestClient(create_app(tmp_path / "data"), base_url="http://127.0.0.1") as owner:
            answer = owner.put("/api/lan", json={"enabled": True, "port": port}).json()
            assert answer["enabled"] is True and answer["running"] is False and str(port) in answer["error"]
            assert owner.put("/api/lan", json={"port": 80}).status_code == 422
    finally:
        taken.close()


# -- the switches of what may be reached outside this computer ---------------------------------------------------------------------
def test_the_network_switches_are_kept_and_applied_to_the_ai_and_google_fonts(owner, monkeypatch):
    assert owner.get("/api/network").json() == {"ai": True, "google_fonts": True, "update_checks": False}
    assert owner.put("/api/network", json={"ai": "yes"}).status_code == 422
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert research.ai_available() is True
    assert owner.put("/api/network", json={"ai": False, "update_checks": True}).json() == {"ai": False, "google_fonts": True, "update_checks": True}
    assert research.ai_available() is False and research.openai_client() is None
    assert owner.put("/api/network", json={"ai": True}).json()["ai"] is True and research.ai_available() is True
    data_dir = owner.app.state.store.data_dir
    monkeypatch.setattr(fonts, "_get", lambda url: (_ for _ in ()).throw(AssertionError("a network request was made")), raising=True)
    owner.put("/api/network", json={"google_fonts": False})
    assert fonts.network_allowed is False
    monkeypatch.undo()
    monkeypatch.setattr(fonts, "network_allowed", False)
    with pytest.raises(su.ValidationError, match="switched off in the network settings"):
        fonts.google_index(data_dir, refresh=True)
    assert outbound.get(owner.app.state.store)["google_fonts"] is False
    outbound.save(owner.app.state.store, {"google_fonts": True})
    assert fonts.network_allowed is True
