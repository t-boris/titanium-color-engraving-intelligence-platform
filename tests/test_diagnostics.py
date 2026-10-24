"""The diagnostics export (electron REQ-080): the zip holds exactly the summary, the tails of the logs and the audit tail, every text redacted
(home folder, user names in paths, e-mail addresses, keys and tokens), never a photograph, the database or a laboratory release; it is
written outside the workshop and fetched back by its name only."""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import labworld  # noqa: E402
from titanium_platform import diagnostics, lab_export, lab_import, migrations  # noqa: E402
from titanium_platform import setup as su  # noqa: E402
from titanium_platform.api.app import create_app  # noqa: E402

HOME = str(Path.home())


def test_redaction_hides_the_home_folder_other_users_emails_keys_and_tokens():
    text = (f"opened {HOME}/.titanium-platform/files/a.jpg and /Users/someone/x.lbrn2 and C:\\Users\\Boris\\data; "
            "mail boris.t@example.com; OPENAI_API_KEY=sk-abcdefghijklmnop1234 token: ghp_" + "A" * 40 + " hash 0123456789abcdef0123456789abcdef "
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature; release 4f2a1c6e-1b2d-4e5f-8a9b-0c1d2e3f4a5b stays")
    out = diagnostics.redact(text)
    assert HOME not in out and "~/.titanium-platform/files/a.jpg" in out
    assert "/Users/someone" not in out and "/Users/<user>/x.lbrn2" in out and "C:\\Users\\<user>\\data" in out
    assert "boris.t@example.com" not in out and "<email>" in out
    assert "sk-abcdefghijklmnop1234" not in out and "OPENAI_API_KEY=<redacted>" in out
    assert "ghp_" + "A" * 40 not in out and "token: <redacted>" in out
    assert "0123456789abcdef0123456789abcdef" not in out and "<hex>" in out
    assert "eyJhbGciOiJIUzI1NiJ9" not in out
    assert "4f2a1c6e-1b2d-4e5f-8a9b-0c1d2e3f4a5b" in out                     # a UUID is an identifier, kept
    assert diagnostics.redact("") == "" and diagnostics.redact("plain text 12 mm") == "plain text 12 mm"


@pytest.fixture()
def workshop(tmp_path):
    with TestClient(create_app(tmp_path / "live")) as client:
        store = client.app.state.store
        labworld.build(store, tmp_path / "live" / "files")
        other = create_app(tmp_path / "other")
        with TestClient(other) as other_client:
            labworld.build(other_client.app.state.store, tmp_path / "other" / "files")
            lab_export.set_public_info(other_client.app.state.store, {"name": "Other lab", "author": "O."})
            lab_export.export(other_client.app.state.store, tmp_path / "other.tcelab", None, "CC-BY-4.0")
        lab_import.start(store, lab_import.stage(store, [(tmp_path / "other.tcelab").read_bytes()]), wait=True)
        store.set_setting("openai_api_key_hint", "sk-secretsecretsecret")
        store.set_setting("backup_dir", str(tmp_path / "kept"))
        (tmp_path / "live" / "app.log").write_text("\n".join([f"line {i} at {HOME}/.titanium-platform for boris@example.com" for i in range(600)]) + "\n")
        (tmp_path / "live" / "server.log").write_text("titanium-platform 0.29.0: http://127.0.0.1:8765\nkey=sk-abcdefghijklmnopqrstu\n")
        yield client, store, tmp_path


def test_the_zip_holds_exactly_the_summary_the_log_tails_and_the_audit_tail_all_redacted(workshop):
    client, store, tmp = workshop
    made = client.post("/api/workshop/diagnostics", json={})
    assert made.status_code == 201
    body = made.json()
    assert Path(body["path"]).parent == tmp / "kept" and body["download"] == f"/api/workshop/diagnostics/{body['name']}"
    with zipfile.ZipFile(body["path"]) as zf:
        assert sorted(zf.namelist()) == ["audit.jsonl", "logs/app.log", "logs/server.log", "summary.json"] == sorted(body["members"])
        summary = json.loads(zf.read("summary.json"))
        app_log = zf.read("logs/app.log").decode()
        server_log = zf.read("logs/server.log").decode()
        audit = zf.read("audit.jsonl").decode()
    assert summary["app"] and summary["schema"] == migrations.CURRENT and summary["integrity_check"] == "ok"
    assert summary["counts"]["observation"] > 0 and summary["counts"]["lab_release"] == 1 and "photograph" not in json.dumps(summary)
    assert [r["name"] for r in summary["lab_releases"]] == ["Other lab"] and summary["lab_releases"][0]["release_id"]
    assert summary["settings"]["openai_api_key_hint"] == "<redacted>" and HOME not in summary["settings"]["backup_dir"]
    assert HOME not in json.dumps(summary)
    assert app_log.count("\n") == diagnostics.LOG_LINES and "line 599" in app_log and "line 99 " not in app_log
    assert HOME not in app_log and "boris@example.com" not in app_log and "<email>" in app_log
    assert "sk-abcdefghijklmnopqrstu" not in server_log and "0.29.0" in server_log
    assert HOME not in audit and '"action": "diagnostics_exported"' not in audit          # the export itself is audited after the tail is taken
    assert store.one("SELECT action FROM audit ORDER BY id DESC LIMIT 1")["action"] == "diagnostics_exported"
    fetched = client.get(body["download"])
    assert fetched.status_code == 200 and fetched.headers["content-type"] == "application/zip"
    assert zipfile.ZipFile(io.BytesIO(fetched.content)).namelist() == zipfile.ZipFile(body["path"]).namelist()
    assert client.get("/api/workshop/diagnostics/..%2Fsummary.json").status_code in (404, 422)
    assert client.get("/api/workshop/diagnostics/titanium-diagnostics-20000101T000000Z.zip").status_code == 404


def test_the_export_is_refused_inside_the_workshop_and_goes_where_it_is_asked(workshop):
    client, store, tmp = workshop
    refused = client.post("/api/workshop/diagnostics", json={"target_dir": str(tmp / "live" / "inside")})
    assert refused.status_code == 422 and "inside the workshop" in refused.json()["error"]
    assert not (tmp / "live" / "inside").exists()
    with pytest.raises(su.ValidationError, match="choose the folder"):
        diagnostics.export(store, "  ")
    made = client.post("/api/workshop/diagnostics", json={"target_dir": str(tmp / "elsewhere")}).json()
    assert Path(made["path"]).parent == tmp / "elsewhere" and made["download"] is None
    assert diagnostics.NAME.match(made["name"])
    again = client.post("/api/workshop/diagnostics", json={"target_dir": str(tmp / "elsewhere")}).json()
    assert again["path"] != made["path"]                                                   # the same second gets another name


def test_recovery_copies_are_listed_with_their_kind_newest_first(workshop):
    client, store, tmp = workshop
    folder = tmp / "live" / migrations.BACKUPS
    folder.mkdir(exist_ok=True)
    (folder / "schema-before-2-20261024T100000Z.sqlite").write_bytes(b"x" * 10)
    (folder / "titanium-before-0.4.0-20261001T100000Z.sqlite").write_bytes(b"y" * 20)
    (folder / "notes.txt").write_text("not a copy")
    listed = client.get("/api/workshop/recovery-copies").json()
    assert [(c["name"], c["kind"], c["bytes"]) for c in listed] in ([("schema-before-2-20261024T100000Z.sqlite", "schema", 10), ("titanium-before-0.4.0-20261001T100000Z.sqlite", "release", 20)],
                                                                    [("titanium-before-0.4.0-20261001T100000Z.sqlite", "release", 20), ("schema-before-2-20261024T100000Z.sqlite", "schema", 10)])
    assert all(c["modified_at"].endswith("+00:00") for c in listed)
