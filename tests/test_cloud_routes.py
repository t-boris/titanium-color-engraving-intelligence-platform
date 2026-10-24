"""The cloud over the local API (electron REQ-086, REQ-087, DEC-058): under the desktop shell the sign-in's callback is the one address
the browser reaches without the session cookie, and only while its state is pending; the whole flow from «Войти» to a publication,
the catalogue, a connection from the cloud as a job, invitations, the check for updates and the settings; the cloud routes are the
workshop's own computer's and obey the network switch."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import labworld  # noqa: E402
from cloud_fakes import CLOUD_BASE, World  # noqa: E402
from test_cloud_api import keys, mint, verifier  # noqa: E402,F401  (fixtures)
from titanium_platform import cloud_session, lab_export  # noqa: E402
from titanium_platform.api import security  # noqa: E402
from titanium_platform.api.app import create_app  # noqa: E402
from titanium_platform.db import Store  # noqa: E402


@pytest.fixture()
def world(verifier, mint, monkeypatch) -> World:
    return World(verifier, mint).install(monkeypatch)


def workshop(folder: Path, build: bool = False) -> TestClient:
    store = Store(folder)
    if build:
        labworld.build(store, folder / "files")
        lab_export.set_public_info(store, {"name": "Open titanium lab", "author": "A. Author"})
    store.set_setting(cloud_session.API_URL_SETTING, CLOUD_BASE)
    store.close()
    return TestClient(create_app(folder), base_url="http://127.0.0.1")


def signed_in(client: TestClient, world: World, account: str, name: str = "") -> dict:
    started = client.post("/api/cloud/signin")
    assert started.status_code == 201, started.text
    state, code = world.handoff(started.json()["url"], account, name)
    page = TestClient(client.app, base_url="http://127.0.0.1").get("/api/cloud/callback", params={"state": state, "code": code})
    assert page.status_code == 200 and "Вход выполнен, вернитесь в приложение" in page.text and "<script" not in page.text
    return client.get("/api/cloud/account").json()


def finished(client: TestClient, job: dict) -> dict:
    deadline = time.time() + 60
    while not job["done"] and time.time() < deadline:
        time.sleep(0.05)
        job = client.get(f"/api/cloud/jobs/{job['id']}").json()
    assert job["done"] and not job["error"], job
    return job


def test_under_the_desktop_shell_the_callback_passes_without_the_cookie_only_while_its_state_is_pending(tmp_path, world, monkeypatch):
    monkeypatch.setenv(security.SECRET_ENV, "s3cret-of-this-launch")
    with workshop(tmp_path / "data") as desktop:
        assert desktop.get("/session/s3cret-of-this-launch", follow_redirects=False).status_code == 303
        bare = TestClient(desktop.app, base_url="http://127.0.0.1")
        assert bare.get("/api/cloud/account").status_code == 403
        refused = bare.get("/api/cloud/callback", params={"state": "not-pending-state-xx", "code": "c"})
        assert refused.status_code == 403 and refused.json()["error"] == "open the workshop from the application"
        started = desktop.post("/api/cloud/signin").json()
        assert started["url"].startswith(f"{CLOUD_BASE}/signin?") and "callback=http%3A%2F%2F127.0.0.1%3A80%2Fapi%2Fcloud%2Fcallback" in started["url"]
        state = started["state"]
        assert bare.post("/api/cloud/callback", params={"state": state, "code": "c"}).status_code == 403          # GET only
        assert bare.get("/api/cloud/callback", params={"state": state, "code": "c", "extra": "1"}).status_code != 403
        # a wrong code: the page says so in Russian, and the state is spent: the address no longer passes the guard
        again = desktop.post("/api/cloud/signin").json()
        wrong = bare.get("/api/cloud/callback", params={"state": again["state"], "code": "not-a-code"})
        assert wrong.status_code == 422 and "Вход не выполнен" in wrong.text and "Код входа уже использован или неизвестен" in wrong.text
        assert bare.get("/api/cloud/callback", params={"state": again["state"], "code": "not-a-code"}).status_code == 403
        assert desktop.get("/api/cloud/account").json()["signed_in"] is False
        # the real thing
        account = signed_in(desktop, world, "acc-desktop", "Настольная")
        assert account["signed_in"] and account["account"]["name"] == "Настольная" and account["switched_on"] is True
        assert bare.get("/api/cloud/account").status_code == 403                                                  # still guarded
        assert desktop.post("/api/cloud/signout").json()["signed_in"] is False
        assert desktop.post("/api/cloud/signin/cancel", json={}).json()["signed_in"] is False
    assert "/api/cloud" in security.LAN_OWNER_ONLY                                                                # never from a tablet


def test_the_whole_flow_over_the_api_publish_connect_invite_check_and_settings(tmp_path, world):
    with workshop(tmp_path / "author", build=True) as author, workshop(tmp_path / "reader") as reader:
        assert author.get("/api/cloud/own").json()["signed_in"] is False
        signed_in(author, world, "acc-author", "A. Author")
        assert author.post("/api/cloud/publish", json={"terms": "all rights"}).status_code == 422
        job = author.post("/api/cloud/publish", json={"terms": "CC-BY-4.0", "visibility": "public", "description": "Fibre, Grade 5"})
        assert job.status_code == 202 and job.json()["kind"] == "publish"
        job = finished(author, job.json())
        release = job["result"]["release"]
        assert release["number"] == 1 and job["phase"] == "done"
        own = author.get("/api/cloud/own").json()
        assert own["lab"]["description"] == "Fibre, Grade 5" and own["publications"][0]["state"] == "finalized" and own["pending"] is None
        assert author.get("/api/labs/own").json()["exports"][0]["published"]["release_number"] == 1
        assert author.post("/api/cloud/publish/retry").status_code == 422
        assert author.post("/api/cloud/publish/abandon").status_code == 422

        listed = reader.get("/api/cloud/catalogue").json()
        assert listed["signed_in"] is False and listed["labs"][0]["latest_release"]["id"] == release["id"]
        assert reader.get(f"/api/cloud/labs/{own['lab']['id']}").json()["releases"][0]["id"] == release["id"]
        assert reader.get("/api/cloud/labs/not-a-uuid").status_code == 404
        started = reader.post(f"/api/cloud/releases/{release['id']}/connect")
        assert started.status_code == 202 and started.json()["kind"] == "connect"
        connected = finished(reader, started.json())
        assert connected["result"]["release_id"] == release["id"] and connected["cloud"]["lab_name"] == "Open titanium lab"
        [source] = reader.get("/api/labs/sources").json()
        assert source["origin"] == "cloud" and source["current"]["release_number"] == 1
        assert reader.get("/api/cloud/jobs/nope").status_code == 404
        assert reader.post(f"/api/cloud/jobs/{connected['id']}/cancel").json()["done"] is True
        [checked] = reader.post("/api/cloud/updates/check", json={"source_id": source["id"]}).json()
        assert checked["newer"] is False
        assert reader.post("/api/cloud/updates/check", json={"source_id": "x"}).status_code == 422
        assert reader.put(f"/api/cloud/sources/{source['id']}", json={"update_checks": "auto"}).json()["update_checks"] == "auto"
        assert reader.post("/api/cloud/updates/automatic").json() == []                                            # the network setting says no
        second = finished(author, author.post("/api/cloud/publish", json={"terms": "CC-BY-4.0"}).json())["result"]["release"]
        assert reader.post("/api/cloud/updates/check", json={}).json()[0]["latest"]["number"] == 2 == second["number"]
        assert reader.get("/api/cloud/catalogue").json()["labs"][0]["connected"]["newer"] is True

        # a withdrawal through the cloud routes is declared here and announced there
        withdrawn = author.post("/api/cloud/withdrawals", json={"target_kind": "release", "target_id": release["id"], "reason": "superseded",
                                                                "replacement_release_id": second["id"]})
        assert withdrawn.status_code == 201 and withdrawn.json()["cloud"]["withdrawals"][0]["target_kind"] == "release"
        assert author.get("/api/labs/own").json()["withdrawals"][0]["target_id"] == release["id"]

        # invitations and members
        invitation = author.post("/api/cloud/invitations", json={"expires_in_s": 3600})
        assert invitation.status_code == 201 and "/invitations/" in invitation.json()["link"]
        assert author.post("/api/cloud/invitations", json={"expires_in_s": 5}).status_code == 422
        assert reader.post("/api/cloud/invitations/accept", json={"link": invitation.json()["link"]}).status_code == 422   # not signed in
        signed_in(reader, world, "acc-reader")
        assert reader.post("/api/cloud/invitations/accept", json={"link": invitation.json()["link"]}).json()["lab"]["role"] == "member"
        assert [m["account_id"] for m in author.get("/api/cloud/own").json()["members"]] == ["acc-reader"]
        assert author.delete("/api/cloud/members/acc-reader").status_code == 204
        assert author.delete(f"/api/cloud/invitations/{invitation.json()['id']}").status_code == 204
        assert author.get("/api/cloud/own").json()["members"] == []

        # the settings and the switch
        assert reader.get("/api/cloud/settings").json() == {"api_url": CLOUD_BASE, "default": cloud_session.DEFAULT_API_URL, "custom": True}
        assert reader.put("/api/cloud/settings", json={"api_url": "ftp://x"}).status_code == 422
        assert reader.put("/api/cloud/settings", json={"api_url": ""}).json()["api_url"] == cloud_session.DEFAULT_API_URL
        assert reader.put("/api/network", json={"cloud": False}).json()["cloud"] is False
        off = reader.get("/api/cloud/catalogue")
        assert off.status_code == 422 and "switched off" in off.json()["error"]
        assert reader.get("/api/cloud/account").json()["switched_on"] is False
        assert reader.put("/api/network", json={"cloud": True}).json()["cloud"] is True
        assert reader.get("/api/cloud/account").json()["switched_on"] is True
