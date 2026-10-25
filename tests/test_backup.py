"""Full backup and restoration of a workshop (electron REQ-081): the backup holds a consistent database with its committed WAL data and
every user file, its manifest is written last and only after every hash was confirmed, an interrupted backup is never taken for one and
never replaces an earlier one; restoring into another folder keeps every work and its files reachable (paths rebased), a tampered
backup is refused, a non-empty folder is refused unless replacing is asked for, and a laboratory release is not a backup."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import labworld  # noqa: E402
from titanium_platform import backup, files as fs, lab_export, lab_import, migrations  # noqa: E402
from titanium_platform import setup as su  # noqa: E402
from titanium_platform.api.app import create_app  # noqa: E402
from titanium_platform.db import Store  # noqa: E402


@pytest.fixture()
def workshop(tmp_path):
    """A workshop with measurements and their files, a vector work, a connected laboratory release and an own release."""
    author = Store(tmp_path / "author")
    labworld.build(author, tmp_path / "author" / "files")
    lab_export.set_public_info(author, {"name": "Other lab", "author": "O."})
    lab_export.export(author, tmp_path / "other.tcelab", None, "CC-BY-4.0")
    author.close()
    store = Store(tmp_path / "work")
    ids = labworld.build(store, tmp_path / "work" / "files")
    lab_export.set_public_info(store, {"name": "My lab", "author": "M."})
    lab_export.export(store, tmp_path / "work" / "lab_exports" / "mine.tcelab", None, "CC-BY-4.0")
    lab_import.start(store, lab_import.stage(store, [(tmp_path / "other.tcelab").read_bytes()]), wait=True)
    store.execute("UPDATE plan SET data_json=? WHERE id=?", (json.dumps({"image_path": str(tmp_path / "work" / "files" / "MARKER-PATH-narrow.lbrn2"),
                                                                        "history": [{"path": str(tmp_path / "work" / "files" / "x.json")}]}), ids["work"]))
    (tmp_path / "work" / "cache").mkdir()
    (tmp_path / "work" / "cache" / "render.png").write_bytes(b"not backed up")
    yield store, ids, tmp_path
    store.close()


def test_a_backup_holds_the_database_with_its_wal_and_every_user_file_and_its_manifest_last(workshop):
    store, ids, tmp = workshop
    store.execute("INSERT INTO setting(key, value_json) VALUES ('just-written', '1')")        # committed, still in the WAL
    made = backup.make(store, tmp / "copies")
    folder = Path(made["path"])
    assert folder.name.startswith("titanium-backup-") and (folder / "manifest.json").is_file()
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["kind"] == backup.KIND and manifest["schema"] == migrations.CURRENT and manifest["data_dir"] == str((tmp / "work").resolve())
    names = set(manifest["files"])
    assert "titanium.sqlite" in names and any(n.startswith("files/") for n in names)
    assert any(n.startswith("labs/") and n.endswith("release.tcelab") for n in names) and "lab_exports/mine.tcelab" in names
    assert not any(n.startswith("cache/") for n in names) and not any(".staging" in n for n in names)
    assert not (folder / "titanium.sqlite-wal").exists()
    import sqlite3
    conn = sqlite3.connect(folder / "titanium.sqlite")
    assert conn.execute("SELECT value_json FROM setting WHERE key='just-written'").fetchone()[0] == "1"
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()
    for rel, entry in manifest["files"].items():
        assert (folder / rel).stat().st_size == entry["size"]
    seen = backup.inspect(folder, verify=True)
    assert seen["complete"] and seen["manifest"]["files"] == len(manifest["files"])
    assert [b["path"] for b in backup.listing([tmp / "copies"])] == [str(folder)]
    assert store.one("SELECT action FROM audit ORDER BY id DESC LIMIT 1")["action"] == "workshop_backup"


def test_an_interrupted_backup_is_a_partial_folder_that_is_neither_listed_nor_a_backup(workshop, monkeypatch):
    store, ids, tmp = workshop
    first = backup.make(store, tmp / "copies")
    calls = []

    def failing(src, dst, *a, **k):
        calls.append(dst)
        if len(calls) == 3:
            raise OSError(28, "No space left on device")
        return original(src, dst, *a, **k)
    original = backup.shutil.copyfile
    monkeypatch.setattr(backup.shutil, "copyfile", failing)
    with pytest.raises(OSError):
        backup.make(store, tmp / "copies")
    assert [p.name for p in (tmp / "copies").iterdir()] == [Path(first["path"]).name]       # the partial folder is gone, the first stays
    assert backup.inspect(first["path"])["complete"]
    partial = tmp / "copies" / "titanium-backup-20000101T000000Z.partial"
    partial.mkdir()
    assert backup.listing([tmp / "copies"]) and all(not b["path"].endswith(".partial") for b in backup.listing([tmp / "copies"]))
    assert backup.inspect(partial)["problems"] == ["this backup was not finished"]


def test_without_space_or_inside_the_workshop_no_backup_is_made(workshop, monkeypatch):
    store, ids, tmp = workshop
    with pytest.raises(su.ValidationError, match="inside the workshop"):
        backup.make(store, tmp / "work" / "copies")
    usage = type("Usage", (), {"free": 10, "total": 1 << 40, "used": 0})
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda path: usage)
    with pytest.raises(su.ValidationError, match="not enough free space"):
        backup.make(store, tmp / "copies")
    assert not any((tmp / "copies").iterdir())


def test_a_restored_workshop_in_another_folder_opens_with_its_work_files_and_release(workshop):
    store, ids, tmp = workshop
    made = backup.make(store, tmp / "copies")
    plans_before = [dict(r) for r in store.query("SELECT id, name, mode FROM plan ORDER BY id")]
    pairs_before = store.one("SELECT COUNT(*) AS n FROM pair")["n"]
    done = backup.restore(made["path"], tmp / "restored")
    assert done["path"] == str(tmp / "restored") and done["rebased"] > 0 and done["set_aside"] is None
    restored = Store(tmp / "restored")
    assert [dict(r) for r in restored.query("SELECT id, name, mode FROM plan ORDER BY id")] == plans_before
    assert restored.one("SELECT COUNT(*) AS n FROM pair")["n"] == pairs_before
    for row in restored.query("SELECT lightburn_path FROM pair"):
        assert row["lightburn_path"].startswith(str((tmp / "restored").resolve())) and Path(row["lightburn_path"]).is_file()
    data = json.loads(restored.one("SELECT data_json FROM plan WHERE id=?", (ids["work"],))["data_json"])
    assert data["image_path"] == str((tmp / "restored").resolve() / "files" / "MARKER-PATH-narrow.lbrn2") and Path(data["image_path"]).is_file()
    assert data["history"][0]["path"].startswith(str((tmp / "restored").resolve()))
    assert restored.get_setting(fs.RESTORED_FROM) == [str((tmp / "work").resolve())]
    [source] = lab_import.sources(restored)
    assert source["name"] == "Other lab" and (lab_import.release_dir(restored, source["current"]["release_id"]) / lab_import.FILE).is_file()
    assert (tmp / "restored" / "lab_exports" / "mine.tcelab").is_file()
    (tmp / "restored" / "files" / "only-here.txt").write_text("x")           # a path recorded under the old folder, not rewritten
    assert fs.resolve(restored, str((tmp / "work").resolve() / "files" / "only-here.txt")) == str((tmp / "restored").resolve() / "files" / "only-here.txt")
    assert fs.resolve(restored, str(tmp / "work" / "files" / "MARKER-PATH-wide.lbrn2")) == str(tmp / "work" / "files" / "MARKER-PATH-wide.lbrn2")
    restored.close()
    assert store.one("SELECT COUNT(*) AS n FROM pair")["n"] == pairs_before                  # the source workshop is as it was


def test_a_tampered_backup_and_a_non_empty_folder_are_refused_and_replacing_sets_the_folder_aside(workshop):
    store, ids, tmp = workshop
    made = backup.make(store, tmp / "copies")
    target = tmp / "target"
    target.mkdir()
    (target / "something.txt").write_text("mine")
    with pytest.raises(su.ValidationError, match="not empty"):
        backup.restore(made["path"], target)
    assert (target / "something.txt").read_text() == "mine"
    done = backup.restore(made["path"], target, overwrite=True)
    assert Path(done["set_aside"]).name.startswith("target.replaced-") and (Path(done["set_aside"]) / "something.txt").read_text() == "mine"
    assert (target / "titanium.sqlite").is_file()
    victim = next(p for p in Path(made["path"]).rglob("*.lbrn2"))
    data = victim.read_bytes()
    victim.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))                    # the same size, one bit changed
    with pytest.raises(su.ValidationError, match="does not match the hash"):
        backup.restore(made["path"], tmp / "again")
    assert not (tmp / "again").exists()
    assert not backup.inspect(made["path"], verify=True)["complete"]
    assert backup.inspect(made["path"])["complete"]                                   # same size: only the hash tells
    assert backup.inspect(tmp / "other.tcelab")["problems"][0].startswith("this is a laboratory release")
    with pytest.raises(su.ValidationError, match="laboratory release"):
        backup.restore(tmp / "other.tcelab", tmp / "nowhere")


def test_the_workshop_api_makes_lists_inspects_and_restores_backups(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))      # the listing also reads ~/titanium-backups: the operator's own backups stay out
    with TestClient(create_app(tmp_path / "live")) as client:
        store = client.app.state.store
        labworld.build(store, tmp_path / "live" / "files")
        shown = client.get("/api/workshop").json()
        assert shown["schema"] == shown["schema_known"] == migrations.CURRENT and shown["lock"]["pid"] and shown["disk"]["free_bytes"] > 0
        assert client.put("/api/workshop/backup-dir", json={"path": str(tmp_path / "kept")}).json()["backup_dir"] == str(tmp_path / "kept")
        made = client.post("/api/workshop/backups", json={})
        assert made.status_code == 201 and made.json()["path"].startswith(str(tmp_path / "kept"))
        assert [b["path"] for b in client.get("/api/workshop/backups").json()] == [made.json()["path"]]
        assert client.post("/api/workshop/backups/inspect", json={"path": made.json()["path"]}).json()["complete"]
        refused = client.post("/api/workshop/restore", json={"path": made.json()["path"], "target_dir": str(tmp_path / "live"), "overwrite": True})
        assert refused.status_code == 422 and "chosen explicitly" in refused.json()["error"]
        done = client.post("/api/workshop/restore", json={"path": made.json()["path"], "target_dir": str(tmp_path / "elsewhere")}).json()
        assert done["restart_needed"] is False and (tmp_path / "elsewhere" / "titanium.sqlite").is_file()
        assert client.post("/api/workshop/restore", json={"path": str(tmp_path / "nothing"), "target_dir": str(tmp_path / "x")}).status_code == 422
    again = Store(tmp_path / "elsewhere")
    assert again.one("SELECT COUNT(*) AS n FROM pair")["n"] > 0
    again.close()
