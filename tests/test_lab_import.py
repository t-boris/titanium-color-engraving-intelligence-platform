"""Connecting laboratory releases (electron REQ-084): what a file declares is shown first; a complete, valid release becomes available
whole and a broken, cancelled, oversized or interrupted one leaves the workshop as it was; the same release adds nothing and a changed
one is refused; newer releases, withdrawals, disconnecting and removing keep every saved work's source."""
from __future__ import annotations

import errno
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import evidence_summary as summary  # noqa: E402
import labworld  # noqa: E402
from titanium_platform import lab_export, lab_format as lf, lab_import, lab_snapshot  # noqa: E402
from titanium_platform import setup as su  # noqa: E402
from titanium_platform.db import Store  # noqa: E402

TABLES = ("pair", "observation", "plan", "material_profile", "laser_device", "lens", "lab_source", "lab_release", "lab_withdrawal")


@pytest.fixture()
def author(tmp_path):
    store = Store(tmp_path / "author")
    ids = labworld.build(store, tmp_path / "author" / "files")
    lab_export.set_public_info(store, {"name": "Open titanium lab", "author": "A. Author", "url": "https://example.org/lab"})
    yield store, ids
    store.close()


@pytest.fixture()
def reader(tmp_path):
    """Another workshop with its own observations."""
    store = Store(tmp_path / "reader")
    labworld.build(store, tmp_path / "reader" / "files")
    yield store
    store.close()


def publish(store: Store, path: Path, terms: str = "CC-BY-4.0", **kw) -> dict:
    return lab_export.export(store, path, None, terms, **kw)


def connect(store: Store, path: Path) -> dict:
    token = lab_import.stage(store, [path.read_bytes()])
    return lab_import.start(store, token, wait=True)


def state(store: Store) -> tuple:
    """The workshop as a connection may not change it: its records, the connected sources, and the release folders."""
    digest = hashlib.sha256()
    for table in TABLES:
        for row in store.query(f"SELECT * FROM {table} ORDER BY rowid"):
            digest.update(repr(tuple(row)).encode())
    labs = lab_import.labs_dir(store)
    folders = sorted(p.name for p in labs.iterdir() if p.name != lab_import.STAGING) if labs.exists() else []
    return digest.hexdigest(), folders


def rewritten(source: Path, target: Path, change) -> Path:
    """The release ``source`` read, changed by ``change(manifest, lab, sections)`` and written again with a correct hash and counts."""
    manifest, lab, sections = None, None, {s: [] for s in lf.SECTIONS}
    with open(source, "rb") as fh:
        for kind, value in lf.read(fh):
            if kind == "manifest":
                manifest = value
            elif kind == "lab":
                lab = value
            elif kind in lf.SECTIONS:
                sections[kind].append(value)
    change(manifest, lab, sections)
    lf.write(target, manifest, lab, sections)
    return target


def test_a_release_is_shown_before_it_is_connected_then_connected_whole_and_kept_after_a_restart(author, reader, tmp_path):
    store, _ = author
    path = tmp_path / "lab.tcelab"
    manifest = publish(store, path)
    own = state(reader)
    token = lab_import.stage(reader, [path.read_bytes()[:1000], path.read_bytes()[1000:]])
    seen = lab_import.inspect(reader, token)
    assert seen["lab"]["name"] == "Open titanium lab" and seen["attribution"]["name"] == "A. Author"
    assert seen["verified"] is False and seen["own"] is False and seen["connected"] is None
    assert seen["release"]["release_id"] == manifest["release_id"] and seen["release"]["counts"] == manifest["counts"]
    assert seen["terms"]["id"] == "CC-BY-4.0" and seen["compatibility"]["strict"] and not seen["compatibility"]["newer_minor"]
    assert {e["laser"] for e in seen["equipment"]} and seen["materials"]
    assert state(reader) == own                                             # nothing is connected by looking
    job = lab_import.start(reader, token, wait=True)
    assert job["phase"] == "done" and job["share"] == 1.0 and job["result"]["current"]
    assert not any(lab_import.staging_dir(reader).iterdir())
    assert state(reader)[0] != own[0] and state(reader)[1] == [manifest["release_id"]]
    for table in ("pair", "observation"):                                   # the own observations are as they were
        assert reader.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"]
    [lab] = lab_import.sources(reader)
    assert lab["name"] == "Open titanium lab" and lab["status"] == "connected" and lab["current"]["release_id"] == manifest["release_id"]
    assert lab["current"]["verified"] is False and lab["current"]["retrieved_at"]
    shutil.rmtree(tmp_path / "author" / "files")                            # nor does it need the author's files after a restart
    again = Store(tmp_path / "reader")
    snapshot = lab_import.open_release(again, manifest["release_id"])
    points = [p for p in summary.colour_map(snapshot)["points"] if not p["provisional"]]
    assert len(points) > 40
    with pytest.raises(Exception, match="readonly|read-only"):
        snapshot.execute("DELETE FROM observation")
    snapshot.close()
    again.close()


def test_the_same_release_adds_nothing_a_changed_one_is_refused_and_an_own_one_too(author, reader, tmp_path):
    store, _ = author
    first = publish(store, tmp_path / "1.tcelab")
    assert connect(reader, tmp_path / "1.tcelab")["phase"] == "done"
    before = state(reader)
    again = connect(reader, tmp_path / "1.tcelab")
    assert again["phase"] == "unchanged" and state(reader) == before
    with pytest.raises(su.ValidationError, match="published already"):
        publish(store, tmp_path / "forged.tcelab", "CC-BY-NC-4.0", release_id=first["release_id"])
    rewritten(tmp_path / "1.tcelab", tmp_path / "forged.tcelab", lambda m, lab, s: m.update(usage_terms={"id": "CC-BY-NC-4.0", "version": "4.0"}))
    refused = connect(reader, tmp_path / "forged.tcelab")
    assert refused["phase"] == "failed" and refused["error"]["code"] == "conflict" and state(reader) == before
    token = lab_import.stage(store, [(tmp_path / "1.tcelab").read_bytes()])
    assert lab_import.inspect(store, token)["own"] is True
    own = lab_import.start(store, token, wait=True)
    assert own["error"]["code"] == "own_lab" and not lab_import.sources(store)


def _truncated(src, dst):
    dst.write_bytes(src.read_bytes()[: len(src.read_bytes()) // 2])


def _flipped(src, dst):
    data = bytearray(src.read_bytes())
    at = data.index(b'"lab":[', len(data) // 2) + 8
    data[at] = ord("1") if data[at] != ord("1") else ord("2")
    dst.write_bytes(bytes(data))


def _garbage_line(src, dst):
    lines = src.read_bytes().split(b"\n")
    lines[3] = b"{not json"
    dst.write_bytes(b"\n".join(lines))


def _duplicate_measurement(src, dst):
    def change(m, lab, s):
        s["measurements"].append({**s["measurements"][0], "seq": s["measurements"][-1]["seq"] + 1})
    rewritten(src, dst, change)


def _unknown_capture(src, dst):
    def change(m, lab, s):
        s["measurements"][-1] = {**s["measurements"][-1], "capture_id": "00000000-0000-4000-8000-000000000000"}
    rewritten(src, dst, change)


def _newer_major(src, dst):
    rewritten(src, dst, lambda m, lab, s: m.update(schema_version="2.0"))


def _not_a_release(src, dst):
    dst.write_bytes(b"PK\x03\x04 a zip file\n")


@pytest.mark.parametrize("damage, code", [(_truncated, "truncated"), (_flipped, "hash"), (_garbage_line, "json"),
                                          (_duplicate_measurement, "duplicate_id"), (_unknown_capture, "reference"),
                                          (_newer_major, "version_major"), (_not_a_release, "not_a_release")])
def test_a_broken_release_leaves_the_workshop_and_its_sources_as_they_were(author, reader, tmp_path, damage, code):
    store, _ = author
    publish(store, tmp_path / "good.tcelab")
    assert connect(reader, tmp_path / "good.tcelab")["phase"] == "done"   # a source connected before must stay as it is
    publish(store, tmp_path / "next.tcelab")
    damage(tmp_path / "next.tcelab", tmp_path / "bad.tcelab")
    before = state(reader)
    job = connect(reader, tmp_path / "bad.tcelab")
    assert job["phase"] == "failed" and job["error"]["code"] == code, job["error"]
    assert state(reader) == before and not any(lab_import.staging_dir(reader).iterdir())


def test_a_release_over_the_limits_is_refused_before_it_is_kept(author, reader, tmp_path):
    store, _ = author
    publish(store, tmp_path / "lab.tcelab")
    small = lf.ResourcePolicy(max_bytes=4096)
    before = state(reader)
    with pytest.raises(lab_import.LabImportError, match="larger than"):
        lab_import.stage(reader, [(tmp_path / "lab.tcelab").read_bytes()], small)
    token = lab_import.stage(reader, [(tmp_path / "lab.tcelab").read_bytes()])
    few = lf.ResourcePolicy(max_records={"measurements": 3})
    with pytest.raises(lab_import.LabImportError) as refused:
        lab_import.run(reader, lab_import.staging_dir(reader) / token, policy=few)
    assert refused.value.code == "limit" and state(reader) == before


def test_cancelling_a_full_disk_or_a_failed_record_leave_nothing(author, reader, tmp_path, monkeypatch):
    store, _ = author
    publish(store, tmp_path / "lab.tcelab")
    before = state(reader)

    def staged():
        token = lab_import.stage(reader, [(tmp_path / "lab.tcelab").read_bytes()])
        return lab_import.staging_dir(reader) / token

    job = lab_import.Job(1)
    job.cancel.set()
    with pytest.raises(lf.Cancelled):
        lab_import.run(reader, staged(), job)
    assert state(reader) == before
    with monkeypatch.context() as m:
        m.setattr(lab_import.shutil, "disk_usage", lambda _: shutil._ntuple_diskusage(10, 10, 0))
        with pytest.raises(lab_import.LabImportError, match="disk space"):
            lab_import.run(reader, staged())
    assert state(reader) == before

    def full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")
    with monkeypatch.context() as m:
        m.setattr(lab_import.lab_snapshot, "build", full)
        with pytest.raises(lab_import.LabImportError) as refused:
            lab_import.run(reader, staged())
        assert refused.value.code == "disk_full"
    assert state(reader) == before

    def broken(manifest):
        raise RuntimeError("power cut")
    with monkeypatch.context() as m:                 # the record fails after the folder was moved into place: the move is undone
        m.setattr(lab_import.lf, "compatibility", broken)
        with pytest.raises(RuntimeError):
            lab_import.run(reader, staged())
    assert state(reader) == before


def test_what_an_interruption_leaves_is_cleaned_at_the_next_start(author, reader, tmp_path):
    store, _ = author
    kept = publish(store, tmp_path / "kept.tcelab")
    connect(reader, tmp_path / "kept.tcelab")
    lost = publish(store, tmp_path / "lost.tcelab")
    token = lab_import.stage(reader, [(tmp_path / "lost.tcelab").read_bytes()])
    with open(tmp_path / "lost.tcelab", "rb") as fh:                        # a crash after the folder was moved, before its record
        lab_snapshot.build(lab_import.release_dir(reader, lost["release_id"]), fh)
    before = state(reader)
    found = lab_import.reconcile(reader)
    assert found == {"removed": [lost["release_id"]], "missing": []}
    assert not lab_import.staging_dir(reader).exists() and token
    assert state(reader)[1] == [kept["release_id"]] and state(reader)[0] == before[0]
    shutil.rmtree(lab_import.release_dir(reader, kept["release_id"]))      # files taken away by hand: the record says so
    assert lab_import.reconcile(reader)["missing"] == [kept["release_id"]]
    assert lab_import.sources(reader)[0]["current"]["status"] == "removed"


def test_a_newer_release_becomes_current_shows_what_changed_and_brings_withdrawals(author, reader, tmp_path):
    store, ids = author
    first = publish(store, tmp_path / "1.tcelab")
    measurement = store.one("SELECT uuid FROM portable_id WHERE kind='observation' ORDER BY CAST(local_key AS INTEGER) LIMIT 1")["uuid"]
    with pytest.raises(su.ValidationError, match="never published"):
        lab_export.withdraw(store, "measurement", "00000000-0000-4000-8000-000000000000", "wrong")
    lab_export.withdraw(store, "measurement", measurement, "the chart was the wrong one")
    second = publish(store, tmp_path / "2.tcelab")
    connect(reader, tmp_path / "2.tcelab")
    connect(reader, tmp_path / "1.tcelab")                                  # an older one connected later does not take its place
    [lab] = lab_import.sources(reader)
    assert lab["current"]["release_id"] == second["release_id"] and lab["kept"] == 2 and lab["withdrawals"] == 1
    changes = lab_import.differences(reader, second["release_id"])
    assert changes["against"] == first["release_id"] and changes["added"] == {"provenance": 1} and changes["changed"] == {}
    assert changes["removed"] == {} and changes["withdrawn"] == 1
    whole = lab_import.open_release(reader, second["release_id"])
    without = lab_import.open_release(reader, second["release_id"], lab_import.hidden(reader, lab["id"]))
    n = whole.one("SELECT COUNT(*) AS n FROM observation")["n"]
    assert without.one("SELECT COUNT(*) AS n FROM observation")["n"] == n - 1
    assert whole.one("SELECT COUNT(*) AS n FROM main.observation")["n"] == without.one("SELECT COUNT(*) AS n FROM main.observation")["n"] == n
    whole.close()
    without.close()
    with pytest.raises(Exception, match="kept as it was learned"):
        reader.execute("DELETE FROM lab_withdrawal")


def test_disconnecting_keeps_releases_a_used_release_is_not_removed_and_an_unused_one_is(author, reader, tmp_path):
    store, _ = author
    first = publish(store, tmp_path / "1.tcelab")
    second = publish(store, tmp_path / "2.tcelab")
    connect(reader, tmp_path / "1.tcelab")
    connect(reader, tmp_path / "2.tcelab")
    source_id = lab_import.sources(reader)[0]["id"]
    card = lab_import.disconnect(reader, source_id)
    assert card["status"] == "disconnected" and card["update_checks"] == "off" and len(card["releases"]) == 2
    laser = reader.one("SELECT id FROM laser_device ORDER BY id LIMIT 1")["id"]
    plan = reader.execute("INSERT INTO plan(name, mode, status, device_id, data_json, created_at) VALUES ('Work', 'Vector job', 'Draft', ?, ?, '2026')",
                          (laser, json.dumps({"evidence_source": {"kind": "release", "release_id": first["release_id"]}}))).lastrowid
    assert lab_import.references(reader, first["release_id"]) == [{"plan_id": plan, "name": "Work", "mode": "Vector job"}]
    with pytest.raises(su.ValidationError, match="1 saved works use this release"):
        lab_import.remove_release(reader, first["release_id"])
    card = lab_import.remove_release(reader, second["release_id"])
    assert card["current"]["release_id"] == first["release_id"]
    assert not lab_import.release_dir(reader, second["release_id"]).exists()
    assert [r["status"] for r in card["releases"] if r["release_id"] == second["release_id"]] == ["removed"]
    assert lab_import.reconnect(reader, source_id)["status"] == "connected"
    assert connect(reader, tmp_path / "2.tcelab")["phase"] == "done"        # a removed release can be connected again


def test_a_snapshot_of_another_layout_is_built_again_from_its_file(author, reader, tmp_path, monkeypatch):
    store, _ = author
    manifest = publish(store, tmp_path / "lab.tcelab")
    connect(reader, tmp_path / "lab.tcelab")
    snapshot = lab_import.open_release(reader, manifest["release_id"])
    expected = summary.colour_map(snapshot)
    snapshot.close()
    monkeypatch.setattr(lab_snapshot, "VERSION", "next")
    snapshot = lab_import.open_release(reader, manifest["release_id"])
    assert lab_snapshot.release_of(snapshot)["version"] == "next" and summary.colour_map(snapshot) == expected
    snapshot.close()
