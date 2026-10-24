"""The laboratories over HTTP (electron REQ-083, REQ-084): the owner enters the public names, sees what a release holds, writes it and
downloads its file; another workshop sends the file, sees what it declares, connects it in the background and finds it among its
sources; a broken file is answered with a reason and connects nothing."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import labworld  # noqa: E402
from titanium_platform.api.app import create_app  # noqa: E402
from titanium_platform.db import Store  # noqa: E402


def finished(client: TestClient, job: dict) -> dict:
    deadline = time.time() + 30
    while not job["done"] and time.time() < deadline:
        time.sleep(0.05)
        job = client.get(f"/api/labs/jobs/{job['id']}").json()
    return job


def test_a_release_written_by_one_workshop_is_connected_by_another(tmp_path):
    seeded = Store(tmp_path / "author")
    ids = labworld.build(seeded, tmp_path / "author" / "files")
    seeded.close()
    with TestClient(create_app(tmp_path / "author")) as author:
        refused = author.put("/api/labs/own", json={"name": "<script>alert(1)</script>", "author": "Me"})
        assert refused.status_code == 422 and "plain text" in refused.json()["error"]
        own = author.put("/api/labs/own", json={"name": "Open titanium lab", "author": "A. Author", "url": "https://example.org",
                                                "lasers": {str(ids["laser"]): {"public_name": "Fiber 60 W"}}}).json()
        assert own["name"] == "Open titanium lab" and own["lasers"][str(ids["laser"])]["public_name"] == "Fiber 60 W"
        page = author.get("/api/labs/own").json()
        assert page["choices"]["setups"] and [t["id"] for t in page["terms"]] == ["CC-BY-4.0", "CC-BY-NC-4.0", "tce-own-engravings-1"]
        seen = author.post("/api/labs/own/preview", json={"selection": None}).json()
        assert seen["ready"] and seen["public"]["lasers"][str(ids["laser"])]["public_name"] == "Fiber 60 W"
        assert author.post("/api/labs/own/releases", json={"selection": None, "terms": "all rights"}).status_code == 422
        written = author.post("/api/labs/own/releases", json={"selection": None, "terms": "CC-BY-4.0"})
        assert written.status_code == 201
        release = written.json()
        download = author.get(release["download"])
        assert download.status_code == 200 and download.headers["content-type"] == "application/vnd.titanium.tcelab+json"
        assert ".tcelab" in download.headers["content-disposition"]
        assert author.get("/api/labs/own").json()["exports"][0]["release_id"] == release["manifest"]["release_id"]
        data = download.content
        own_file = author.post("/api/labs/files", files={"release": ("lab.tcelab", data)}).json()
        assert own_file["own"] is True
        assert finished(author, author.post(f"/api/labs/files/{own_file['token']}/connect").json())["error"]["code"] == "own_lab"

    with TestClient(create_app(tmp_path / "reader")) as reader:
        assert reader.post("/api/labs/files", files={"release": ("x.tcelab", b"not a release\n")}).status_code == 422
        shown = reader.post("/api/labs/files", files={"release": ("lab.tcelab", data)})
        assert shown.status_code == 201
        card = shown.json()
        assert card["lab"]["name"] == "Open titanium lab" and card["verified"] is False and card["equipment"][0]["laser"] == "Fiber 60 W"
        assert reader.get("/api/labs/sources").json() == []
        job = reader.post(f"/api/labs/files/{card['token']}/connect")
        assert job.status_code == 202
        job = finished(reader, job.json())
        assert job["phase"] == "done", job
        [lab] = reader.get("/api/labs/sources").json()
        assert lab["name"] == "Open titanium lab" and lab["current"]["release_id"] == release["manifest"]["release_id"]
        detail = reader.get(f"/api/labs/sources/{lab['id']}").json()
        assert detail["lab"]["url"] == "https://example.org" and detail["releases"][0]["works"] == []
        assert reader.get(f"/api/labs/releases/{lab['current']['release_id']}/differences").json()["against"] is None
        assert reader.post(f"/api/labs/sources/{lab['id']}/disconnect").json()["status"] == "disconnected"
        assert reader.get(f"/api/labs/jobs/{'0' * 32}").status_code == 404
        gone = reader.delete(f"/api/labs/releases/{lab['current']['release_id']}").json()
        assert gone["current"] is None and gone["releases"][0]["status"] == "removed"
