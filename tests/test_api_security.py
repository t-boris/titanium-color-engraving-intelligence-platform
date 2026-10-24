"""The guard of the local API (electron DEC-046, REQ-080): in both run modes a request whose Host does not name this computer, a change
from another site or an oversized body is refused; under the desktop shell nothing but the shell's one-time session address works
without the session cookie, and that address is spent once used. The console command and the smoke check start the core as the shell
does."""
from __future__ import annotations

import http.cookiejar
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from titanium_platform import cli
from titanium_platform.api import security
from titanium_platform.api.app import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def browser(tmp_path):
    with TestClient(create_app(tmp_path / "data"), base_url="http://127.0.0.1") as client:
        yield client


@pytest.fixture()
def desktop(tmp_path, monkeypatch):
    monkeypatch.setenv(security.SECRET_ENV, "s3cret-of-this-launch")
    with TestClient(create_app(tmp_path / "data"), base_url="http://127.0.0.1") as client:
        yield client


def test_in_browser_mode_the_host_must_name_this_computer_and_changes_must_come_from_it(browser):
    assert browser.get("/api/health").status_code == 200
    assert browser.get("/api/health", headers={"Host": "localhost:8765"}).status_code == 200
    assert browser.get("/api/health", headers={"Host": "192.168.1.20:8765"}).status_code == 200      # a tablet on the LAN, by address
    assert browser.get("/api/health", headers={"Host": "testserver"}).status_code == 200              # TCE_ALLOWED_HOSTS of the tests
    rebound = browser.get("/api/health", headers={"Host": "evil.example"})
    assert rebound.status_code == 421 and rebound.json()["kind"] == "misdirected"
    assert browser.post("/api/materials", json={"name": "x"}, headers={"Origin": "http://127.0.0.1"}).status_code != 403
    assert browser.post("/api/materials", json={"name": "x"}, headers={"Sec-Fetch-Site": "same-origin"}).status_code != 403
    foreign = browser.post("/api/materials", json={"name": "x"}, headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403 and "another site" in foreign.json()["error"]
    assert browser.post("/api/materials", json={"name": "x"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert browser.get("/api/health", headers={"Origin": "https://evil.example"}).status_code == 200        # reading is the browser's to stop
    huge = browser.post("/api/materials", content=b"", headers={"Content-Length": str(security.MAX_BODY_BYTES + 1)})
    assert huge.status_code == 413


def test_under_the_desktop_shell_only_the_spent_once_session_address_opens_the_workshop(desktop):
    refused = desktop.get("/api/health")
    assert refused.status_code == 403 and refused.json()["error"] == "open the workshop from the application"
    assert desktop.get("/").status_code == 403
    assert desktop.get("/session/wrong").status_code == 403
    opened = desktop.get("/session/s3cret-of-this-launch", follow_redirects=False)
    assert opened.status_code == 303 and opened.headers["location"] == "/"
    cookie = opened.headers["set-cookie"]
    assert cookie.startswith(security.COOKIE + "=") and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert "s3cret-of-this-launch" not in cookie                                     # the cookie is not the bootstrap secret
    assert desktop.get("/api/health").status_code == 200                              # the client keeps the cookie
    assert desktop.get("/session/s3cret-of-this-launch").status_code == 403         # spent
    bare = TestClient(desktop.app, base_url="http://127.0.0.1")
    assert bare.get("/api/health").status_code == 403
    assert desktop.get("/api/health", headers={"Host": "evil.example"}).status_code == 421


def test_the_desktop_flag_needs_the_secret_and_the_smoke_check_starts_a_core_and_asks_its_health(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(security.SECRET_ENV, raising=False)
    assert cli.main(["--desktop", "--data-dir", str(tmp_path / "d")]) == 2
    assert "TCE_SESSION_SECRET" in capsys.readouterr().err
    monkeypatch.setenv(security.SECRET_ENV, "replaced by the smoke")            # what the smoke sets is undone with the test
    monkeypatch.setenv("TCE_DESKTOP", "")
    assert cli.main(["--smoke", "--data-dir", str(tmp_path / "smoke")]) == 0
    told = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert told["smoke"] == "ok" and told["data_dir"] == str(tmp_path / "smoke") and (tmp_path / "smoke" / "titanium.sqlite").is_file()


def test_the_core_started_as_the_shell_starts_it_tells_its_port_serves_the_session_and_stops_with_its_parent(tmp_path):
    env = {**os.environ, security.SECRET_ENV: "launch-secret", "PYTHONPATH": str(ROOT / "src"), "TCE_ALLOWED_HOSTS": ""}
    core = subprocess.Popen([sys.executable, "-m", "titanium_platform", "--desktop", "--port", "0", "--parent-pid", str(os.getpid()),
                             "--data-dir", str(tmp_path / "w")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        line = core.stdout.readline()
        ready = json.loads(line)
        assert ready["ready"] is True and ready["pid"] == core.pid and ready["port"] > 0
        base = f"http://127.0.0.1:{ready['port']}"
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(base + "/api/version", timeout=10)
        assert refused.value.code == 403
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        with opener.open(base + "/session/launch-secret", timeout=10) as page:
            assert page.status == 200 and page.url.rstrip("/") == base
        with opener.open(base + "/api/version", timeout=10) as answer:
            assert json.loads(answer.read())["data_dir"] == str(tmp_path / "w")
    finally:
        core.terminate()
        assert core.wait(30) is not None
        core.stdout.close()
        core.stderr.close()


def test_the_parent_watchdog_sees_a_living_and_a_dead_process():
    assert cli._parent_alive(os.getpid())
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    assert not cli._parent_alive(gone.pid) or sys.platform == "win32"
