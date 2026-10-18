"""Lenses: records, installing and replacing, the spot and the field they give, and the snapshot a plate keeps (REQ-019, DEC-041)."""
import json
import math

import pytest
from fastapi.testclient import TestClient

from titanium_platform import characterization as ch
from titanium_platform import devices as dv
from titanium_platform import ingest, lenses as ln
from titanium_platform import plans as pl
from titanium_platform import setup as su
from titanium_platform.api.app import create_app

TEMPLATE = "jpt-ydflp-e-60-m7-m-r"
BEAM = {"beam_diameter_mm": 7.0}
JOB = {"pulse_width": 200, "line_interval": 0.025, "passes": 1}


def laser(store, **passport):
    d = dv.create_from_template(store, TEMPLATE)
    return dv.update_device(store, d["id"], passport=d["passport"] | passport) if passport else d


def ready(store, **passport):
    """A device with an installed 254 mm lens and the marker layer set."""
    d = laser(store, **passport)
    lens = ln.create_lens(store, "F254", 254, 175)
    ln.install(store, d["id"], lens["id"])
    pl.save_marker_layer_settings(store, 20, 60, 300)
    return dv.get_device(store, d["id"]), lens


# -- the lens record ---------------------------------------------------------------------------------------
def test_a_lens_is_stored_with_defaults(store):
    lens = ln.create_lens(store, " F160 ", 160)
    assert lens["name"] == "F160" and lens["focal_length_mm"] == 160 and lens["field_mm"] is None and lens["expansion"] == 1 and lens["installed_on"] is None


def test_a_lens_may_stay_without_a_focal_length_and_the_figures_that_need_it_are_unavailable(store):
    """REQ-019: an incomplete lens is kept as it is; the spot, fluence and overlap wait for the focal length."""
    d = laser(store, m2=1.3)
    lens = ln.create_lens(store, "Unmarked F-theta")
    assert lens["focal_length_mm"] is None
    ln.install(store, d["id"], lens["id"])
    d = dv.get_device(store, d["id"])
    spot = next(i for i in d["characterization"]["items"] if i["key"] == "spot_diameter")
    assert spot["value"] is None and spot["state"] == "unknown" and spot["waiting_for"] == ["focal_length"]
    assert "focal_length" in [q["kind"] for q in d["open_questions"]]
    op = dv.operating_point(d["passport"], 50, 80, 900, 200, 0.025, 1, d["lens"])
    assert op["fluence_j_cm2"] is None and op["pulse_overlap"] is None
    assert op["areal_energy_j_cm2"] > 0 and op["pulse_energy_mj"] > 0                # the independent figures stay
    assert ln.update_lens(store, lens["id"], focal_length_mm=254)["focal_length_mm"] == 254
    assert ln.update_lens(store, lens["id"], focal_length_mm=None)["focal_length_mm"] is None


def test_a_lens_named_by_stored_work_cannot_be_deleted(store):
    d, lens = ready(store)
    pl.create_plate_series(store, d["id"], "10", "40", "900", 6, 5, 1, **JOB)
    ln.install(store, d["id"], None)
    with pytest.raises(su.ProtectedError, match="stored records of work"):
        ln.delete_lens(store, lens["id"])


@pytest.mark.parametrize("kw", [dict(name=" "), dict(focal_length_mm=0), dict(focal_length_mm="x"), dict(focal_length_mm=5), dict(focal_length_mm=5000),
                                dict(field_mm=0), dict(field_mm=9999), dict(expansion=0), dict(expansion=100)])
def test_a_lens_is_validated(store, kw):
    args = dict(name="L", focal_length_mm=160) | kw
    with pytest.raises(su.ValidationError):
        ln.create_lens(store, **args)


def test_editing_a_lens_keeps_what_is_not_given(store):
    lens = ln.create_lens(store, "F254", 254, 175)
    e = ln.update_lens(store, lens["id"], note="from the box")
    assert e["note"] == "from the box" and e["focal_length_mm"] == 254 and e["field_mm"] == 175
    assert ln.update_lens(store, lens["id"], field_mm=None)["field_mm"] is None
    with pytest.raises(su.ValidationError):
        ln.update_lens(store, lens["id"], focal_length_mm=0)


def test_a_lens_is_on_one_laser_and_an_installed_lens_cannot_be_deleted(store):
    a, b = laser(store), dv.create_from_template(store, TEMPLATE, "Second")
    lens = ln.create_lens(store, "F254", 254)
    ln.install(store, a["id"], lens["id"])
    assert ln.get_lens(store, lens["id"])["installed_on"]["id"] == a["id"] and dv.get_device(store, a["id"])["lens"]["name"] == "F254"
    with pytest.raises(su.ValidationError, match="already installed"):
        ln.install(store, b["id"], lens["id"])
    with pytest.raises(su.ProtectedError):
        ln.delete_lens(store, lens["id"])
    ln.install(store, a["id"], None)
    assert dv.get_device(store, a["id"])["lens"] is None
    ln.delete_lens(store, lens["id"])
    assert ln.list_lenses(store) == []


def test_replacing_a_lens_takes_the_old_one_off(store):
    d = laser(store)
    old, new = ln.create_lens(store, "F160", 160), ln.create_lens(store, "F254", 254)
    ln.install(store, d["id"], old["id"])
    ln.install(store, d["id"], new["id"])
    assert dv.get_device(store, d["id"])["lens"]["id"] == new["id"] and ln.get_lens(store, old["id"])["installed_on"] is None


def test_unknown_lens_and_device_are_not_found(store):
    d = laser(store)
    with pytest.raises(KeyError):
        ln.install(store, d["id"], 999)
    with pytest.raises(KeyError):
        ln.install(store, 999, None)
    with pytest.raises(KeyError):
        ln.get_lens(store, 999)


# -- the spot ----------------------------------------------------------------------------------------------
def test_the_spot_follows_the_focused_gaussian_beam_formula():
    lens = {"focal_length_mm": 254, "expansion": 1, "field_mm": 175}
    p = dv.validate_passport(dv.TEMPLATES[TEMPLATE]["passport"] | BEAM | {"m2": 1.3})
    spot = ch.spot_estimate(p, lens, {})
    assert spot["value"] == pytest.approx(4 * 1.3 * 1.064 * 254 / (math.pi * 7.0), rel=1e-9) and spot["basis"] == "calculated" and spot["state"] == "used"


def test_a_shorter_lens_gives_a_smaller_spot_and_an_expander_shrinks_it():
    p = dv.TEMPLATES[TEMPLATE]["passport"] | BEAM | {"m2": 1.3}
    spot = lambda lens: ch.spot_estimate(p, lens, {})["value"]
    assert spot({"focal_length_mm": 160, "expansion": 1}) < spot({"focal_length_mm": 254, "expansion": 1})
    assert spot({"focal_length_mm": 254, "expansion": 2}) == pytest.approx(spot({"focal_length_mm": 254, "expansion": 1}) / 2)


def test_without_m2_only_a_bound_is_shown_and_it_is_not_used():
    p = dv.TEMPLATES[TEMPLATE]["passport"] | BEAM | {"m2_max": 1.5}
    spot = ch.spot_estimate(p, {"focal_length_mm": 254, "expansion": 1}, {})
    assert spot["value"] is None and spot["state"] == "reference" and spot["basis"] == "bound"
    assert spot["low"] == pytest.approx(4 * 1.064 * 254 / (math.pi * 7.0)) and spot["high"] == pytest.approx(spot["low"] * 1.5)


def test_the_operators_measured_spot_wins_over_the_calculation():
    p = dv.TEMPLATES[TEMPLATE]["passport"] | BEAM | {"m2": 1.3, "spot_diameter_um": 55}
    spot = ch.spot_estimate(p, {"focal_length_mm": 254, "expansion": 1}, {})
    assert spot["value"] == 55 and spot["basis"] == "measured"


def test_what_is_missing_is_named():
    bare = {k: v for k, v in dv.TEMPLATES[TEMPLATE]["passport"].items() if k != "beam_diameter_mm"}
    assert ch.spot_estimate(bare, None, {})["missing"] == ["lens", "beam_diameter"]
    assert ch.spot_estimate(bare | BEAM, {"focal_length_mm": 254, "expansion": 1}, {})["missing"] == ["m2"]
    assert ch.spot_estimate(dv.TEMPLATES[TEMPLATE]["passport"], None, {})["missing"] == ["lens"]      # the template carries the beam diameter


def test_the_beam_diameter_of_the_test_report_is_used():
    rows = {"Output beam diameter": {"result": 7.0}}
    p = dv.TEMPLATES[TEMPLATE]["passport"] | {"m2": 1.3}
    assert ch.spot_estimate(p, {"focal_length_mm": 254, "expansion": 1}, rows)["value"] == pytest.approx(4 * 1.3 * 1.064 * 254 / (math.pi * 7.0))


# -- the field ---------------------------------------------------------------------------------------------
def settings_passport(width, status="confirmed"):
    return {"controller": {"software": "EZCAD", "source": None, "tabs": [{"key": "field", "fields": [{"key": "Field Size", "value": width, "unit": "мм", "status": status}]}]}}


def test_the_lens_field_alone_is_a_work_field():
    p = dv.validate_passport(dv.TEMPLATES[TEMPLATE]["passport"])
    field, waiting = ch.work_field(p, {"field_mm": 175})
    assert field["width"] == 175 and field["source"] == "lens" and waiting == []


def test_the_smaller_of_the_lens_and_the_settings_field_rules_and_a_larger_setting_is_flagged():
    big = dv.validate_passport(dv.TEMPLATES[TEMPLATE]["passport"] | settings_passport(200))
    field, _ = ch.work_field(big, {"field_mm": 175})
    assert field["width"] == 175 and field["settings_exceeds_lens"] is True
    small = dv.validate_passport(dv.TEMPLATES[TEMPLATE]["passport"] | settings_passport(150))
    field, _ = ch.work_field(small, {"field_mm": 175})
    assert field["width"] == 150 and field["settings_exceeds_lens"] is False



def test_an_unconfirmed_handwritten_settings_field_does_not_narrow_the_lens_field():
    p = dv.validate_passport(dv.TEMPLATES[TEMPLATE]["passport"] | settings_passport(100, "handwritten"))
    field, waiting = ch.work_field(p, {"field_mm": 175})
    assert field["width"] == 175 and waiting == ["Field Size"]


# -- operating points and plates ---------------------------------------------------------------------------
def test_fluence_and_overlap_use_the_spot_of_the_installed_lens(store):
    d, lens = ready(store, m2=1.3)
    op = dv.operating_point(d["passport"], 50, 80, 900, 200, 0.025, 1, d["lens"])
    spot = 4 * 1.3 * 1.064 * 254 / (math.pi * 7.0)
    assert op["spot_basis"] == "calculated" and op["spot_diameter_um"] == pytest.approx(spot, rel=1e-4)
    assert op["pulse_overlap"] == pytest.approx(1 - 11.25 / spot, rel=1e-4) and op["fluence_j_cm2"] > 0
    shorter = dv.operating_point(d["passport"], 50, 80, 900, 200, 0.025, 1, {"focal_length_mm": 160, "expansion": 1})
    assert shorter["fluence_j_cm2"] > op["fluence_j_cm2"]                         # a smaller spot concentrates the same pulse


def test_without_m2_the_operating_point_has_no_fluence_and_says_so(store):
    d, _ = ready(store)
    op = dv.operating_point(d["passport"], 50, 80, 900, 200, 0.025, 1, d["lens"])
    assert op["fluence_j_cm2"] is None and op["pulse_overlap"] is None and any("spot diameter is not known" in n for n in op["notes"])


def test_a_plate_keeps_a_snapshot_of_its_lens_and_later_edits_do_not_change_it(store):
    d, lens = ready(store, m2=1.3)
    made = pl.create_plate_series(store, d["id"], "10 20", "40 80", "900", 6, 5, 1, **JOB)[0]
    snap = json.loads(store.one("SELECT lens_json FROM plate WHERE id=?", (made["plate_id"],))["lens_json"])
    assert snap["name"] == "F254" and snap["focal_length_mm"] == 254 and snap["spot_diameter_um"] == pytest.approx(63.9, abs=0.1)
    assert snap["spot_basis"] == "calculated"                                       # REQ-019: the spot value with its basis
    assert store.one("SELECT lens_id FROM plate WHERE id=?", (made["plate_id"],))["lens_id"] == lens["id"]
    ln.update_lens(store, lens["id"], name="F160", focal_length_mm=160)
    assert json.loads(store.one("SELECT lens_json FROM plate WHERE id=?", (made["plate_id"],))["lens_json"])["focal_length_mm"] == 254
    assert pl.get_plan(store, made["plan_id"])["lens"]["focal_length_mm"] == 254


def test_a_plate_made_without_a_lens_has_none(store):
    d = laser(store)
    pl.save_marker_layer_settings(store, 20, 60, 300)
    made = pl.create_plate_series(store, d["id"], "10", "40", "900", 6, 5, 1, **JOB)[0]
    row = store.one("SELECT lens_id, lens_json FROM plate WHERE id=?", (made["plate_id"],))
    assert row["lens_json"] is None and row["lens_id"] is None
    assert pl.get_plan(store, made["plan_id"])["lens_id"] is None


def test_a_plate_larger_than_the_lens_field_is_refused_with_the_sizes(store):
    d, lens = ready(store)
    ln.update_lens(store, lens["id"], field_mm=40)
    with pytest.raises(su.ValidationError, match=r"larger than the work field 40 x 40 mm"):
        pl.create_plate_series(store, d["id"], "10 20 30 40 50 60", "40 80", "900", 6, 5, 1, **JOB)
    ln.update_lens(store, lens["id"], field_mm=175)
    assert pl.create_plate_series(store, d["id"], "10 20 30 40 50 60", "40 80", "900", 6, 5, 1, **JOB)


# -- the check of a photographed pair warns about a replaced lens ------------------------------------------
def test_a_replaced_lens_is_a_warning_not_a_block(store):
    d, lens = ready(store)
    made = pl.create_plate_series(store, d["id"], "10", "40", "900", 6, 5, 1, **JOB)[0]
    plate = dict(store.one("SELECT * FROM plate WHERE id=?", (made["plate_id"],)))
    chosen = plate["lens_id"]
    assert ingest.lens_check(store, plate, chosen)["warnings"] == []
    new = ln.create_lens(store, "F160", 160, 110)
    ln.install(store, d["id"], new["id"])
    warnings = ingest.lens_check(store, plate, chosen)["warnings"]
    assert warnings == ["the lens installed now (F160, 160 mm) differs from the lens of this plate (F254, 254 mm)"]
    ln.install(store, d["id"], None)
    assert "no lens is installed" in ingest.lens_check(store, plate, chosen)["warnings"][0]


def test_a_photograph_of_a_plate_keeps_the_plates_lens_whatever_lens_was_chosen(store):
    """REQ-016, REQ-019: comparability follows the lens the plate was made with; a different choice is a warning."""
    d, lens = ready(store)
    made = pl.create_plate_series(store, d["id"], "10", "40", "900", 6, 5, 1, **JOB)[0]
    plate = dict(store.one("SELECT * FROM plate WHERE id=?", (made["plate_id"],)))
    check = ingest.lens_check(store, plate, None)
    assert check["lens_id"] == lens["id"] and check["warnings"] == [
        "no lens was chosen for this photograph; the plate was made with F254, 254 mm: the measurements are kept with the plate's lens"]
    check = ingest.lens_check(store, plate, ln.create_lens(store, "Spare", None)["id"])
    assert check["lens_id"] == lens["id"] and check["warnings"] == [
        "the lens chosen for this photograph (Spare, focal length unknown) differs from the lens of this plate (F254, 254 mm): "
        "the measurements are kept with the plate's lens"]


def test_a_plate_from_before_lenses_is_reported_as_having_no_lens_record(store):
    d, _ = ready(store)
    made = pl.create_plate_series(store, d["id"], "10", "40", "900", 6, 5, 1, **JOB)[0]
    store.execute("UPDATE plate SET lens_json=NULL WHERE id=?", (made["plate_id"],))
    plate = dict(store.one("SELECT * FROM plate WHERE id=?", (made["plate_id"],)))
    assert ingest.lens_check(store, plate, plate["lens_id"])["warnings"] == ["this plate has no record of its lens"]



# -- API ---------------------------------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as c:
        yield c
    app.state.store.close()


def test_api_lens_flow(client):
    d = client.post("/api/devices/from-template", json={"template": TEMPLATE}).json()
    lens = client.post("/api/lenses", json={"name": "F254", "focal_length_mm": 254, "field_mm": 175}).json()
    assert client.get("/api/lenses").json()[0]["id"] == lens["id"]
    done = client.put(f"/api/devices/{d['id']}/lens", json={"lens_id": lens["id"]}).json()
    assert done["lens"]["name"] == "F254" and done["characterization"]["work_field_mm"]["width"] == 175
    assert any(i["key"] == "lens" and i["state"] == "used" for i in done["characterization"]["items"])
    assert client.delete(f"/api/lenses/{lens['id']}").status_code == 409
    assert client.patch(f"/api/lenses/{lens['id']}", json={"expansion": 2}).json()["expansion"] == 2
    assert client.put(f"/api/devices/{d['id']}/lens", json={"lens_id": None}).json()["lens"] is None
    assert client.delete(f"/api/lenses/{lens['id']}").status_code == 204 and client.get(f"/api/lenses/{lens['id']}").status_code == 404
    assert client.post("/api/lenses", json={"name": "x", "focal_length_mm": 1}).status_code == 422


def test_m2_entered_next_to_the_lens_turns_the_bound_into_a_spot_and_keeps_the_rest_of_the_passport(client):
    """The Lens tab saves M2 with the same PATCH as the passport form: the spot becomes calculated, the question goes, nothing else changes."""
    d = client.post("/api/devices/from-template", json={"template": TEMPLATE}).json()
    lens = client.post("/api/lenses", json={"name": "F174", "focal_length_mm": 174, "field_mm": 170}).json()
    before = client.put(f"/api/devices/{d['id']}/lens", json={"lens_id": lens["id"]}).json()
    spot = lambda dev: next(i for i in dev["characterization"]["items"] if i["key"] == "spot_diameter")
    assert spot(before)["state"] == "reference" and spot(before)["waiting_for"] == ["m2"] and [q["kind"] for q in before["open_questions"]] == ["m2", "serial"]
    after = client.patch(f"/api/devices/{d['id']}", json={"passport": before["passport"] | {"m2": 1.3, "spot_diameter_um": None}}).json()
    assert spot(after)["basis"] == "calculated" and spot(after)["state"] == "used" and spot(after)["waiting_for"] == []
    assert spot(after)["value"] == pytest.approx(4 * 1.3 * 1.064 * 174 / (math.pi * 7.0), rel=1e-9)
    assert [q["kind"] for q in after["open_questions"]] == ["serial"]
    assert after["lens"]["id"] == lens["id"] and after["passport"]["pulse_steps"] == before["passport"]["pulse_steps"]
    cleared = client.patch(f"/api/devices/{d['id']}", json={"passport": after["passport"] | {"m2": None}}).json()
    assert spot(cleared)["state"] == "reference" and "m2" in [q["kind"] for q in cleared["open_questions"]]


def test_api_charts_and_the_operating_point_use_the_installed_lens(client):
    d = client.post("/api/devices/from-template", json={"template": TEMPLATE}).json()
    client.patch(f"/api/devices/{d['id']}", json={"passport": d["passport"] | {"m2": 1.3}})
    lens = client.post("/api/lenses", json={"name": "F254", "focal_length_mm": 254}).json()
    client.put(f"/api/devices/{d['id']}/lens", json={"lens_id": lens["id"]})
    point = {"device_id": d["id"], "lens_id": lens["id"], "power": 30, "frequency": 80, "speed": 900, **JOB}
    op = client.post("/api/operating-point", json=point).json()
    assert op["spot_basis"] == "calculated" and op["fluence_j_cm2"] > 0
    unknown = client.post("/api/operating-point", json=point | {"lens_id": None}).json()
    assert unknown["fluence_j_cm2"] is None and unknown["areal_energy_j_cm2"] == op["areal_energy_j_cm2"]
    for missing in ("pulse_width", "line_interval", "passes", "lens_id"):   # nothing is filled in (DEC-043)
        assert client.post("/api/operating-point", json={k: v for k, v in point.items() if k != missing}).status_code == 422
    assert client.get(f"/api/devices/{d['id']}/charts").status_code == 200
