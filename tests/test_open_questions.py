"""Open questions about a laser are derived from its data, so they disappear when the operator answers them (DEC-039)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from titanium_platform import devices as dv
from titanium_platform.api.app import create_app

UNIT = Path(__file__).resolve().parents[1] / "tools" / "units" / "jpt-ydflp-e-60-m7-m-r-mc2bdjd71684.json"


def unit_passport():
    u = json.loads(UNIT.read_text(encoding="utf-8"))
    return u, dict(dv.TEMPLATES[u["template"]]["passport"]) | u["passport"]


def kinds(qs):
    return [q["kind"] for q in qs]


def field(passport, key):
    return next(f for t in passport["controller"]["tabs"] for f in t["fields"] if f["key"] == key)


def test_the_unit_has_derived_questions_and_no_stale_stored_ones():
    u, p = unit_passport()
    assert u["passport"]["open_items"] == []                                  # nothing stored that could go out of date
    qs = dv.open_questions(dv.validate_passport(p), u["serial"])
    assert kinds(qs).count("unread") == 7 and "unconfirmed" in kinds(qs) and "lens" in kinds(qs) and "serial" not in kinds(qs)


def test_filling_in_a_value_removes_its_question():
    u, p = unit_passport()
    p = dv.validate_passport(p)
    before = [q["key"] for q in dv.open_questions(p, u["serial"]) if q["kind"] == "unread"]
    assert "Galvo 1 Scale" in before
    f = field(p, "Galvo 1 Scale")
    f["value"], f["status"] = 78.585, "confirmed"
    after = [q["key"] for q in dv.open_questions(p, u["serial"]) if q["kind"] == "unread"]
    assert "Galvo 1 Scale" not in after and len(after) == len(before) - 1


def test_confirming_every_handwritten_value_removes_the_unconfirmed_question():
    u, p = unit_passport()
    p = dv.validate_passport(p)
    for t in p["controller"]["tabs"]:
        for f in t["fields"]:
            if f["status"] == "handwritten" and f["value"] != dv.UNREAD:
                f["status"] = "confirmed"
    assert "unconfirmed" not in kinds(dv.open_questions(p, u["serial"]))


def test_a_lens_then_m2_or_a_measured_spot_remove_the_spot_questions():
    u, p = unit_passport()
    p = dv.validate_passport(p)
    lens = {"focal_length_mm": 254, "expansion": 1}
    assert "lens" in kinds(dv.open_questions(p, u["serial"]))
    assert "lens" not in kinds(dv.open_questions(p, u["serial"], lens)) and "m2" in kinds(dv.open_questions(p, u["serial"], lens))
    assert "m2" not in kinds(dv.open_questions(dv.validate_passport(p | {"m2": 1.3}), u["serial"], lens))
    measured = lens | {"spot_diameter_um": 65}                     # a spot measured with the installed lens (REQ-019)
    assert not {"lens", "m2", "focal_length"} & set(kinds(dv.open_questions(p, u["serial"], measured)))
    no_focal = {"focal_length_mm": None, "expansion": 1}
    assert "focal_length" in kinds(dv.open_questions(p, u["serial"], no_focal))
    assert "focal_length" not in kinds(dv.open_questions(p, u["serial"], no_focal | {"spot_diameter_um": 65}))
    assert "serial" in kinds(dv.open_questions(p, None)) and "serial" not in kinds(dv.open_questions(p, "S1"))


def test_the_operators_own_notes_are_kept_as_questions():
    u, p = unit_passport()
    p = dv.validate_passport(p | {"open_items": ["check the lens"]})
    assert {"kind": "note", "text": "check the lens"} in dv.open_questions(p, u["serial"])


def test_a_device_without_a_controller_section_does_not_fail(store):
    d = dv.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    assert kinds(d["open_questions"]) == ["lens", "serial"]


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as c:
        yield c
    app.state.store.close()


def test_what_the_operator_saves_in_the_controller_table_is_what_comes_back_and_answers_the_questions(client):
    u, p = unit_passport()
    d = client.post("/api/devices", json={"name": "JPT", "serial": u["serial"], "passport": p}).json()
    n0 = len(d["open_questions"])
    controller = d["passport"]["controller"]
    for t in controller["tabs"]:
        for f in t["fields"]:
            if f["key"] in ("Size Width", "Size Height"):
                f["value"], f["status"] = 175, "confirmed"
            if f["key"] == "Machine number (S/N)":
                f["value"], f["status"] = "HEZ74042P12X", "confirmed"
    saved = client.patch(f"/api/devices/{d['id']}", json={"passport": {**d["passport"], "controller": controller}}).json()
    again = client.get(f"/api/devices/{d['id']}").json()
    keys = {(t["key"], f["key"]): f for t in again["passport"]["controller"]["tabs"] for f in t["fields"]}
    assert keys[("workspace", "Size Width")]["value"] == 175 and keys[("workspace", "Size Width")]["status"] == "confirmed"
    assert keys[("workspace", "Machine number (S/N)")]["value"] == "HEZ74042P12X"
    assert len(again["open_questions"]) == n0 - 1 and saved["open_questions"] == again["open_questions"]
    assert "Machine number (S/N)" not in [q.get("key") for q in again["open_questions"]]
