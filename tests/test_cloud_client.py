"""The desktop's side of the cloud (electron REQ-086, REQ-087, DEC-058) against the real cloud application in process: the catalogue,
a release connected from the cloud chunk by chunk with the same palette the author has, a publication reserved with a key kept before
anything is sent and continued with the same key after an interruption, withdrawals that reach the cloud at once, invitations and
members of a private laboratory, the check for updates (by hand and automatic only when allowed), and nothing called without a sign-in
or with the cloud switched off."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import labworld  # noqa: E402
from cloud_fakes import CLOUD_BASE, World  # noqa: E402
from test_cloud_api import keys, mint, verifier  # noqa: E402,F401  (fixtures)
from titanium_platform import cloud_client, cloud_http, cloud_session, evidence_source, lab_export, lab_import, outbound, palette  # noqa: E402
from titanium_platform.cloud_http import CloudError  # noqa: E402
from titanium_platform.db import Store  # noqa: E402

TERMS = "CC-BY-4.0"


@pytest.fixture(scope="module")
def author(tmp_path_factory):
    folder = tmp_path_factory.mktemp("author")
    store = Store(folder / "lab")
    ids = labworld.build(store, folder / "lab" / "files")
    lab_export.set_public_info(store, {"name": "Open titanium lab", "author": "A. Author", "url": "https://example.org/lab", "description": "Fibre on Grade 5"})
    yield {"store": store, "ids": ids, "origin": lab_export.identity(store)["origin_lab_id"]}
    store.close()


@pytest.fixture()
def world(verifier, mint, monkeypatch) -> World:
    return World(verifier, mint).install(monkeypatch)


@pytest.fixture()
def reader(tmp_path) -> Store:
    store = Store(tmp_path / "reader")
    store.set_setting(cloud_session.API_URL_SETTING, CLOUD_BASE)
    yield store
    store.close()


def done(job: dict) -> dict:
    assert job["done"] and not job["error"], job
    return job


def palettes_agree(author: dict, reader: Store, release_id: str) -> int:
    ids = author["ids"]
    mine = palette.vector_palette(author["store"], ids["laser"], ids["lens"], ids["m1"])["entries"]
    records = {kind: lab_export.portable_ids(author["store"], kind, [key])[str(key)] for kind, key in (("laser", ids["laser"]), ("lens", ids["lens"]), ("material", ids["m1"]))}
    theirs = evidence_source.release_palette(reader, {"release_id": release_id, "laser": records["laser"], "lens": records["lens"], "material": records["material"]})["entries"]
    a = sorted(tuple(round(v, 3) for v in e["lab"]) for e in mine)
    b = sorted(tuple(round(v, 3) for v in e["lab"]) for e in theirs)
    assert a and a == b
    return len(a)


def test_the_author_publishes_and_a_reader_connects_the_release_from_the_cloud_with_the_same_palette(author, reader, world):
    world.sign_in(author["store"], "acc-author", "A. Author")
    job = done(cloud_client.publish(author["store"], terms=TERMS, visibility="public", wait=True))
    release = job["result"]["release"]
    assert job["phase"] == "done" and release["number"] == 1 and release["counts"]["measurements"] > 0 and job["read"] == job["total"] > 0
    rows = cloud_client.publications(author["store"])
    assert rows[0]["state"] == "finalized" and rows[0]["release_id"] == release["id"] and rows[0]["published_at"] == release["published_at"]
    exported = lab_export.exports(author["store"])
    assert exported[0]["release_id"] == release["id"] and exported[0]["published"]["release_number"] == 1 and exported[0]["published"]["api_url"] == CLOUD_BASE
    assert (author["store"].data_dir / "lab_exports" / f"{release['id']}.tcelab").stat().st_size == release["byte_size"]
    mine = cloud_client.own(author["store"])
    assert mine["lab"]["origin_lab_id"] == author["origin"] and mine["lab"]["role"] == "owner" and [r["id"] for r in mine["releases"]] == [release["id"]]
    assert mine["lab"]["description"] == "Fibre on Grade 5" and mine["pending"] is None

    # the reader, without an account: the catalogue, then the release chunk by chunk
    listed = cloud_client.catalogue(reader)
    assert listed["signed_in"] is False and [lab["origin_lab_id"] for lab in listed["labs"]] == [author["origin"]]
    shown = listed["labs"][0]
    assert shown["own"] is False and shown["connected"] is None and shown["latest_release"]["id"] == release["id"]
    detail = cloud_client.lab(reader, shown["id"])
    assert [r["id"] for r in detail["releases"]] == [release["id"]] and detail["latest_release"]["number"] == 1
    connected = done(cloud_client.connect(reader, release["id"], wait=True))
    assert connected["kind"] == "connect" and connected["phase"] == "done" and connected["cloud"]["lab_name"] == "Open titanium lab"
    assert connected["result"]["release_id"] == release["id"] and connected["read"] == connected["total"]
    downloads = [c for c in world.transport.calls if "/chunks/" in c[1] and c[0] == "GET"]
    assert len(downloads) == release["chunk_count"] > 1
    [source] = lab_import.sources(reader)
    assert source["origin"] == "cloud" and source["url"] == f"{CLOUD_BASE}/labs/{shown['id']}" and source["current"]["verified"] is True
    assert source["current"]["release_number"] == 1
    assert palettes_agree(author, reader, release["id"]) > 0
    again = cloud_client.catalogue(reader)["labs"][0]["connected"]
    assert again == {"source_id": source["id"], "status": "connected", "origin": "cloud", "current_release_id": release["id"], "current_release_number": 1, "newer": False}
    assert done(cloud_client.connect(reader, release["id"], wait=True))["phase"] == "unchanged"
    # the author's own laboratory is marked as such and cannot be connected into the author's workshop
    assert cloud_client.catalogue(author["store"])["labs"][0]["own"] is True
    refused = cloud_client.connect(author["store"], release["id"], wait=True)
    assert refused["error"]["code"] == "own_lab"


def test_a_publication_interrupted_in_the_upload_is_continued_with_the_same_key_and_makes_one_release(author, reader, world):
    world.sign_in(author["store"], "acc-author", "A. Author")
    before = len(cloud_client.publications(author["store"]))
    world.transport.refuse = lambda method, path: method == "PUT" and "/chunks/" in path          # the network drops at the first chunk
    cloud_client.RETRIES, kept = 1, cloud_client.RETRIES
    try:
        failed = cloud_client.publish(author["store"], terms=TERMS, wait=True)
    finally:
        cloud_client.RETRIES = kept
    assert failed["phase"] == "failed" and failed["error"]["code"] == "unreachable"
    pending = cloud_client.pending(author["store"])
    assert pending is not None and pending["state"] == "uploading" and pending["publication_id"] and pending["release_number"] == 1
    assert (author["store"].data_dir / "lab_exports" / f"{pending['release_id']}.tcelab").is_file()
    with pytest.raises(CloudError) as busy:
        cloud_client.publish(author["store"], terms=TERMS, wait=True)
    assert busy.value.code == "pending"
    world.transport.refuse = None
    continued = done(cloud_client.retry(author["store"], wait=True))
    release = continued["result"]["release"]
    assert release["id"] == pending["release_id"] and release["number"] == 1 and continued["result"]["publication"]["publication_id"] == pending["publication_id"]
    rows = cloud_client.publications(author["store"])
    assert len(rows) == before + 1 and rows[0]["state"] == "finalized" and rows[0]["idempotency_key"] == pending["idempotency_key"]
    reservations = [c for c in world.transport.calls if c[0] == "POST" and c[1].endswith("/publications")]
    assert len(reservations) == 2                                                                    # reserved twice, the same reservation
    assert len(world.cloud.get(f"/labs/{pending['lab_id']}/releases").json()["releases"]) == 1
    assert cloud_client.pending(author["store"]) is None
    with pytest.raises(CloudError) as nothing:
        cloud_client.retry(author["store"], wait=True)
    assert nothing.value.code == "no_pending"
    # giving up a pending publication marks it failed and lets a new one start
    world.transport.refuse = lambda method, path: method == "PUT" and "/chunks/" in path
    cloud_client.RETRIES = 1
    try:
        cloud_client.publish(author["store"], terms=TERMS, wait=True)
    finally:
        cloud_client.RETRIES = kept
    world.transport.refuse = None
    assert cloud_client.abandon(author["store"])["state"] == "failed" and cloud_client.pending(author["store"]) is None
    assert cloud_client.abandon(author["store"]) is None
    second = done(cloud_client.publish(author["store"], terms=TERMS, wait=True))["result"]["release"]
    assert second["number"] == 2 and second["previous_release_id"] == release["id"]
    # the reader connects both and sees the second as current
    done(cloud_client.connect(reader, release["id"], wait=True))
    done(cloud_client.connect(reader, second["id"], wait=True))
    [source] = lab_import.sources(reader)
    assert source["current"]["release_id"] == second["id"] and source["kept"] == 2


def test_a_withdrawal_is_declared_here_and_announced_on_the_latest_cloud_release(author, reader, world):
    world.sign_in(author["store"], "acc-author", "A. Author")
    release = done(cloud_client.publish(author["store"], terms=TERMS, wait=True))["result"]["release"]
    done(cloud_client.connect(reader, release["id"], wait=True))
    measurement = author["store"].one("SELECT uuid FROM portable_id WHERE kind='observation' ORDER BY uuid LIMIT 1")["uuid"]
    made = cloud_client.withdraw(author["store"], "measurement", measurement, "measured with a dirty lens")
    assert made["local"]["target_id"] == measurement and made["cloud"]["withdrawals"][0]["target_id"] == measurement
    listed = world.cloud.get(f"/releases/{release['id']}/withdrawals").json()["withdrawals"]
    assert [w["target_id"] for w in listed] == [measurement] and listed[0]["reason"] == "measured with a dirty lens"
    assert lab_export.withdrawals(author["store"])[-1]["target_id"] == measurement
    with pytest.raises(Exception):
        cloud_client.withdraw(author["store"], "measurement", measurement, "again")                  # declared already: refused here first
    assert len(world.cloud.get(f"/releases/{release['id']}/withdrawals").json()["withdrawals"]) == 1


def test_a_private_laboratory_is_reached_by_invitation_and_members_are_listed_and_removed(author, reader, world):
    world.sign_in(author["store"], "acc-author", "A. Author")
    release = done(cloud_client.publish(author["store"], terms=TERMS, visibility="private", wait=True))["result"]["release"]
    assert cloud_client.catalogue(reader)["labs"] == []                                             # no account: not even listed
    world.sign_in(reader, "acc-reader", "Читатель")
    assert cloud_client.catalogue(reader)["labs"] == []
    with pytest.raises(CloudError) as none:
        cloud_client.invite(reader)
    assert none.value.code == "no_lab"
    invitation = cloud_client.invite(author["store"], 3600)
    assert invitation["link"].endswith(f"/invitations/{invitation['token']}")
    with pytest.raises(CloudError):
        cloud_client.accept(reader, "https://cloud.test/invitations/not a token")
    accepted = cloud_client.accept(reader, invitation["link"])
    assert accepted["lab"]["role"] == "member" and accepted["lab"]["connected"] is None and accepted["lab"]["own"] is False
    [visible] = cloud_client.catalogue(reader)["labs"]
    assert visible["visibility"] == "private" and visible["role"] == "member"
    done(cloud_client.connect(reader, release["id"], wait=True))
    assert lab_import.sources(reader)[0]["current"]["release_id"] == release["id"]
    mine = cloud_client.own(author["store"])
    assert [m["account_id"] for m in mine["members"]] == ["acc-reader"] and mine["invitations"][0]["accepted_by"] == "acc-reader"
    assert "token" not in mine["invitations"][0]
    cloud_client.remove_member(author["store"], "acc-reader")
    assert cloud_client.catalogue(reader)["labs"] == [] and cloud_client.own(author["store"])["members"] == []
    second = cloud_client.invite(author["store"])
    cloud_client.revoke(author["store"], second["id"])
    with pytest.raises(CloudError) as revoked:
        cloud_client.accept(reader, second["token"])
    assert revoked.value.status == 410
    # the connected release stays usable here: the cloud's membership is about new downloads, not local work
    assert lab_import.sources(reader)[0]["status"] == "connected"


def test_updates_are_checked_by_the_button_and_automatically_only_when_both_settings_allow(author, reader, world, monkeypatch):
    world.sign_in(author["store"], "acc-author", "A. Author")
    first = done(cloud_client.publish(author["store"], terms=TERMS, wait=True))["result"]["release"]
    done(cloud_client.connect(reader, first["id"], wait=True))
    [source] = lab_import.sources(reader)
    [checked] = cloud_client.check_updates(reader)
    assert checked["newer"] is False and checked["found"] and checked["latest"]["id"] == first["id"] and checked["current_release_number"] == 1
    second = done(cloud_client.publish(author["store"], terms=TERMS, wait=True))["result"]["release"]
    [checked] = cloud_client.check_updates(reader, source["id"])
    assert checked["newer"] is True and checked["latest"]["number"] == 2 and checked["lab_id"] == first["lab_id"]
    kept = lab_import.sources(reader)[0]
    assert kept["last_checked_at"] == checked["checked_at"] and json.loads(reader.one("SELECT last_check_json FROM lab_source")["last_check_json"])["newer"] is True
    assert cloud_client.catalogue(reader)["labs"][0]["connected"]["newer"] is True
    with pytest.raises(KeyError):
        cloud_client.check_updates(reader, 999)
    # automatic checks: the laboratory must be set to auto, and the network setting must allow automatic checks
    calls = len(world.transport.calls)
    assert cloud_client.automatic_checks(reader) == [] and len(world.transport.calls) == calls
    assert cloud_client.set_update_checks(reader, source["id"], "auto")["update_checks"] == "auto"
    assert cloud_client.automatic_checks(reader) == [] and len(world.transport.calls) == calls      # network.update_checks is off
    outbound.save(reader, {"update_checks": True})
    assert cloud_client.automatic_checks(reader) == [] and len(world.transport.calls) == calls      # checked within the day already
    reader.execute("UPDATE lab_source SET last_checked_at=NULL")
    [auto] = cloud_client.automatic_checks(reader)
    assert auto["newer"] is True and len(world.transport.calls) > calls
    world.transport.down = True
    reader.execute("UPDATE lab_source SET last_checked_at=NULL")
    [failed] = cloud_client.automatic_checks(reader)
    assert failed["newer"] is False and "could not be reached" in failed["error"]
    world.transport.down = False
    with pytest.raises(Exception):
        cloud_client.set_update_checks(reader, source["id"], "hourly")
    done(cloud_client.connect(reader, second["id"], wait=True))
    assert cloud_client.check_updates(reader)[0]["newer"] is False


def test_without_a_sign_in_or_with_the_cloud_switched_off_nothing_is_sent(author, reader, world, monkeypatch):
    cloud_session.sign_out(author["store"])
    world.transport.calls.clear()
    with pytest.raises(CloudError) as unsigned:
        cloud_client.publish(author["store"], terms=TERMS, wait=True)
    assert unsigned.value.code == "not_signed_in" and world.transport.calls == [] and cloud_client.pending(author["store"]) is None
    with pytest.raises(Exception):
        cloud_client.publish(author["store"], terms="all rights", wait=True)
    assert cloud_client.own(author["store"])["signed_in"] is False
    monkeypatch.setattr(cloud_http, "switched_on", False)
    with pytest.raises(CloudError) as off:
        cloud_client.catalogue(reader)
    assert off.value.code == "switched_off" and world.transport.calls == []
    assert cloud_client.own(author["store"])["switched_on"] is False
    monkeypatch.setattr(cloud_http, "switched_on", True)
    with pytest.raises(KeyError):
        cloud_client.lab(reader, "not-a-uuid")
    with pytest.raises(KeyError):
        cloud_client.status("nope")
