"""Publishing own results (electron REQ-083, DEC-024, DEC-042): only allowlisted numbers leave the workshop, nothing private does in any
encoding, the owner chooses what is published and under which terms, and identities stay the same from one release to the next."""
from __future__ import annotations

import base64
import binascii
import json
import sys
import urllib.parse
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import labworld  # noqa: E402
from titanium_platform import experiments, lab_export, lab_format as lf, setup as su  # noqa: E402
from titanium_platform.db import Store  # noqa: E402

PHOTO_BYTES = b"\x89PNG\r\n\x1a\nMARKER-IMAGE-BYTES-0123456789abcdef"


@pytest.fixture()
def workshop(tmp_path):
    store = Store(tmp_path / "data")
    ids = labworld.build(store, tmp_path / "data" / "files")
    for row in store.query("SELECT photo_path FROM pair"):
        Path(row["photo_path"]).write_bytes(PHOTO_BYTES)          # the photographs exist, with bytes no release may carry
    lab_export.set_public_info(store, {"name": "Open titanium lab", "author": "A. Author", "url": "https://example.org/lab"})
    yield store, ids, tmp_path
    store.close()


def encodings(text: bytes) -> list[bytes]:
    return [text, base64.b64encode(text), base64.urlsafe_b64encode(text), binascii.hexlify(text), binascii.hexlify(text).upper(),
            urllib.parse.quote(text).encode(), urllib.parse.quote_plus(text).encode(), json.dumps(text.decode("latin-1"))[1:-1].encode()]


def test_nothing_private_leaves_the_workshop_in_any_encoding(workshop):
    store, ids, tmp = workshop
    path = tmp / "lab.tcelab"
    lab_export.export(store, path, None, "CC-BY-4.0")
    data = path.read_bytes()
    for marker in labworld.MARKERS:
        for form in encodings(marker.encode()):
            assert form not in data, f"{marker} is in the release as {form[:40]!r}"
    for form in encodings(PHOTO_BYTES[8:]) + encodings(PHOTO_BYTES):
        assert form not in data
    for row in store.query("SELECT lightburn_path FROM pair WHERE lightburn_path!=''"):   # the LightBurn files' pictures and geometry
        source = Path(row["lightburn_path"]).read_bytes()
        assert source[200:264] not in data and Path(row["lightburn_path"]).name.encode() not in data
    assert b"MARKER" not in data and b"/Users/" not in data and str(tmp).encode() not in data
    assert b'"subname":{"Value":"tok:' in data                     # the sub-layer's name is a token, the setting is kept


def test_equal_texts_are_equal_tokens_and_unreadable():
    secret = "00" * 32
    a = lab_export.public_setting({"subname": {"Value": "Clean"}, "scanOpt": {"Value": "individual"}, "frequency": {"Value": "1.95e+06"},
                                   "QPulseWidth": {"Value": " 200"}, "SubLayer": [{"type": "Cut", "subname": {"Value": "Clean"}}]}, secret)
    assert a["subname"]["Value"].startswith("tok:") and a["subname"]["Value"] == a["SubLayer"][0]["subname"]["Value"]
    assert a["scanOpt"]["Value"] == "individual" and a["frequency"]["Value"] == "1.95e+06" and a["SubLayer"][0]["type"] == "Cut"
    assert a["QPulseWidth"]["Value"] == "200.0"
    assert lab_export.token(secret, "Clean") != lab_export.token("11" * 32, "Clean")
    assert lab_export.public_setting({"subname": {"Value": "javascript:alert(1)"}}, secret)["subname"]["Value"].startswith("tok:")


def test_the_owner_sees_what_is_published_and_what_never_is(workshop):
    store, ids, _ = workshop
    seen = lab_export.preview(store, None)
    accepted = store.one("SELECT COUNT(*) AS n FROM pair WHERE status='Accepted'")["n"]
    assert seen["photographs"] == accepted and seen["ready"]
    assert seen["tokenised"]["subname"] == ["MARKER-SUBNAME"]
    assert {"photographs", "paths", "serial", "batch", "surface", "notes", "ai", "layer_names"} <= set(seen["never"])
    assert [t["id"] for t in seen["terms"]] == list(lf.USAGE_TERMS)
    assert seen["public"]["name"] == "Open titanium lab"


def test_a_release_holds_only_what_was_chosen_and_counts_only_that(workshop):
    store, ids, tmp = workshop
    plate = experiments.plan_key(ids["plate"])
    chosen = {"setups": [f"laser:{ids['laser']}/lens:{ids['lens']}"], "materials": [ids["m1"]], "exclude": [plate]}
    manifest = lab_export.export(store, tmp / "part.tcelab", chosen, "CC-BY-NC-4.0")
    pairs = store.query("SELECT id, plan_id FROM pair WHERE status='Accepted' AND device_id=? AND lens_id=? AND material_id=?",
                        (ids["laser"], ids["lens"], ids["m1"]))
    kept = [p for p in pairs if p["plan_id"] != ids["plate"]]
    assert manifest["counts"]["captures"] == len(kept) < len(pairs)
    measured = store.one(f"SELECT COUNT(*) AS n FROM observation WHERE pair_id IN ({','.join(str(p['id']) for p in kept)})")["n"]
    assert manifest["counts"]["measurements"] == measured
    assert manifest["counts"]["equipment"] == 1 and manifest["counts"]["materials"] == 1
    assert manifest["usage_terms"] == {"id": "CC-BY-NC-4.0", "version": "4.0"}


def test_identities_stay_from_one_release_to_the_next(workshop):
    store, _, tmp = workshop
    first = lab_export.export(store, tmp / "1.tcelab", None, "CC-BY-4.0")
    second = lab_export.export(store, tmp / "2.tcelab", None, "tce-own-engravings-1")
    assert first["origin_lab_id"] == second["origin_lab_id"] and first["release_id"] != second["release_id"]

    def ids(path):
        return {rec["id"] for kind, rec in lf.read(open(path, "rb")) if kind in lf.SECTIONS}
    assert ids(tmp / "1.tcelab") == ids(tmp / "2.tcelab")
    assert store.one("SELECT COUNT(*) AS n FROM lab_export")["n"] == 2


def test_a_release_needs_a_public_name_an_author_and_approved_terms(tmp_path):
    store = Store(tmp_path / "data")
    labworld.build(store, tmp_path / "data" / "files")
    with pytest.raises(su.ValidationError, match="public name"):
        lab_export.export(store, tmp_path / "x.tcelab", None, "CC-BY-4.0")
    lab_export.set_public_info(store, {"name": "Lab", "author": "Me"})
    with pytest.raises(su.ValidationError, match="approved list"):
        lab_export.export(store, tmp_path / "x.tcelab", None, "public-domain")
    with pytest.raises(su.ValidationError, match="nothing is chosen"):
        lab_export.export(store, tmp_path / "x.tcelab", {"materials": [999]}, "CC-BY-4.0")
    with pytest.raises(su.ValidationError, match="plain text"):
        lab_export.set_public_info(store, {"name": "javascript:alert(1)", "author": "Me"})
    assert not (tmp_path / "x.tcelab").exists()
