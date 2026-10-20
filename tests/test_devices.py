import io
import json
import os

import pytest
from fastapi.testclient import TestClient

from titanium_platform import devices as dv
from titanium_platform import setup as su
from titanium_platform.api.app import create_app

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
TEMPLATE = "jpt-ydflp-e-60-m7-m-r"


def jpt(store, **kw):
    return dv.create_from_template(store, TEMPLATE, **kw)


JOB = {"pulse_width": 200, "line_interval": 0.025, "passes": 1}


# -- passport and template -------------------------------------------------------------------------------
def test_the_jpt_template_holds_the_manufacturers_table(store):
    d = jpt(store, serial="MC2BDJD71684")
    steps = {s["pulse_width_ns"]: s["cutoff_khz"] for s in d["passport"]["pulse_steps"]}
    assert len(steps) == 17 and steps[1] is None and steps[2] == 1950 and steps[200] == 48 and steps[250] == 46 and steps[500] == 40
    assert d["passport"]["rated_power_w"] == 60 and d["serial"] == "MC2BDJD71684" and d["model"] == "YDFLP-E-60-M7-M-R"


def test_the_cutoff_frequency_falls_as_the_pulse_gets_longer(store):
    pulsed = [s for s in jpt(store)["passport"]["pulse_steps"] if s["cutoff_khz"] is not None]
    cutoffs = [s["cutoff_khz"] for s in pulsed]
    assert cutoffs == sorted(cutoffs, reverse=True)


@pytest.mark.parametrize("change", [
    {"rated_power_w": 0}, {"rated_power_w": "x"}, {"repetition_rate_khz": {"min": 10, "max": 10}}, {"repetition_rate_khz": 5},
    {"pulse_steps": []}, {"pulse_steps": [{"pulse_width_ns": 5, "cutoff_khz": 1}, {"pulse_width_ns": 5, "cutoff_khz": 2}]},
    {"pulse_steps": [{"pulse_width_ns": -1, "cutoff_khz": 1}]}, {"pulse_steps": [{"pulse_width_ns": 5, "cutoff_khz": 0}]},
    {"open_items": "text"}, {"controller": [1]}])
def test_the_passport_is_validated(store, change):
    passport = json.loads(json.dumps(dv.TEMPLATES[TEMPLATE]["passport"])) | change
    with pytest.raises(su.ValidationError):
        dv.create_device(store, "X", passport)


def test_a_device_needs_a_name_and_an_unknown_template_is_refused(store):
    with pytest.raises(su.ValidationError, match="name"):
        dv.create_device(store, "  ", dv.TEMPLATES[TEMPLATE]["passport"])
    with pytest.raises(su.ValidationError, match="template"):
        dv.create_from_template(store, "nope")


def test_editing_a_device_in_place_keeps_unchanged_fields(store):
    d = jpt(store)
    e = dv.update_device(store, d["id"], serial="S1", description=None)
    assert e["serial"] == "S1" and e["description"] is None and e["name"] == d["name"] and e["passport"] == d["passport"]
    with pytest.raises(su.ValidationError, match="name"):
        dv.update_device(store, d["id"], name="")


# -- operating point -------------------------------------------------------------------------------------
def test_above_the_cutoff_the_pulse_energy_is_constant_and_the_power_is_the_set_fraction(store):
    p = jpt(store)["passport"]
    a = dv.operating_point(p, 50, 80, 900, 200, 0.025)
    b = dv.operating_point(p, 50, 160, 900, 200, 0.025)
    assert a["output_power_w"] == 30 and b["output_power_w"] == 30 and a["power_factor"] == b["power_factor"] == 1
    assert a["pulse_energy_mj"] == pytest.approx(0.375) and b["pulse_energy_mj"] == pytest.approx(0.1875)
    assert a["below_cutoff"] is False and a["basis"] == "passport model"


def test_below_the_cutoff_the_power_falls_in_proportion_and_the_energy_stays_that_of_the_cutoff(store):
    p = jpt(store)["passport"]
    at_cutoff = dv.operating_point(p, 100, 48, 900, 200, 0.025)
    below = dv.operating_point(p, 100, 24, 900, 200, 0.025)
    assert at_cutoff["output_power_w"] == pytest.approx(60) and at_cutoff["pulse_energy_mj"] == pytest.approx(1.25)
    assert below["output_power_w"] == pytest.approx(30) and below["pulse_energy_mj"] == pytest.approx(1.25)
    assert below["below_cutoff"] is True and below["power_factor"] == pytest.approx(0.5) and any("below the cut-off" in n for n in below["notes"])


def test_the_test_report_point_is_reproduced(store):
    """The unit's test report measured 62.6 W at 200 ns and 48 kHz: the model gives the rated 60 W there."""
    op = dv.operating_point(jpt(store)["passport"], 100, 48, 900, 200, 0.025)
    assert op["output_power_w"] == pytest.approx(60)


def test_pulse_pitch_density_and_dose(store):
    op = dv.operating_point(jpt(store)["passport"], 50, 80, 900, 200, 0.025, passes=2)
    assert op["pulse_pitch_um"] == pytest.approx(11.25)                       # 900 mm/s / 80 kHz
    assert op["pulses_per_mm2"] == pytest.approx(2 / (0.01125 * 0.025))
    assert op["areal_energy_j_cm2"] == pytest.approx(2 * 30 / (900 * 0.025) * 100)
    assert op["coverage_rate_mm2_s"] == pytest.approx(900 * 0.025 / 2)


def test_fluence_and_overlap_need_the_spot_diameter(store):
    d = jpt(store)
    assert dv.operating_point(d["passport"], 50, 80, 900, 200, 0.025)["fluence_j_cm2"] is None
    lens = {"name": "F-Theta", "focal_length_mm": None, "field_mm": None, "expansion": 1.0, "spot_diameter_um": 50}   # measured with this lens
    op = dv.operating_point(d["passport"], 50, 80, 900, 200, 0.025, lens=lens)
    assert op["spot_basis"] == "measured" and op["fluence_j_cm2"] == pytest.approx(0.375e-3 / (3.141592653589793 * (25e-4) ** 2), rel=1e-6)
    assert op["pulse_overlap"] == pytest.approx(1 - 11.25 / 50)


def test_cw_has_no_cutoff_pulse_energy_or_pitch(store):
    op = dv.operating_point(jpt(store)["passport"], 50, 80, 900, 1, 0.025)
    assert op["cw"] is True and op["cutoff_khz"] is None and op["power_factor"] == 1
    assert op["pulse_energy_mj"] is None and op["pulse_pitch_um"] is None and op["output_power_w"] == 30


def test_a_pulse_width_outside_the_range_is_refused_with_the_range(store):
    with pytest.raises(su.ValidationError, match=r"600 ns is outside the range of this laser \(1-500 ns\)"):
        dv.operating_point(jpt(store)["passport"], 50, 80, 900, 600, 0.025)


def test_frequency_outside_the_laser_range_is_reported(store):
    op = dv.operating_point(jpt(store)["passport"], 50, 5000, 900, 200, 0.025)
    assert op["problems"] and "outside the repetition rate range" in op["problems"][0]


@pytest.mark.parametrize("args", [(0, 80, 900), (101, 80, 900), (50, 0, 900), (50, 80, -1), (50, "x", 900)])
def test_operating_point_validates_input(store, args):
    with pytest.raises(su.ValidationError):
        dv.operating_point(jpt(store)["passport"], *args, 200, 0.025)


def test_charts_come_from_the_passport_and_agree_with_the_model(store):
    p = jpt(store)["passport"]
    c = dv.charts(p)
    assert c["cw_steps"] == [1] and len(c["cutoff"]) == 16 and len(c["curves"]) == 16
    by_width = {x["pulse_width_ns"]: x for x in c["cutoff"]}
    assert by_width[200]["cutoff_khz"] == 48 and by_width[200]["max_pulse_energy_mj"] == pytest.approx(1.25)
    assert max(x["max_pulse_energy_mj"] for x in c["cutoff"]) <= 1.5 + 1e-9        # the stated maximum pulse energy
    curve = next(x for x in c["curves"] if x["pulse_width_ns"] == 200)
    assert any(pt["frequency_khz"] == 48 for pt in curve["points"])                # the knee is a point of the curve
    for pt in curve["points"]:
        model = dv.operating_point(p, 100, pt["frequency_khz"], 900, 200, 0.025)
        assert pt["power_w"] == pytest.approx(model["output_power_w"], rel=1e-5)
    freqs = [pt["frequency_khz"] for pt in curve["points"]]
    assert freqs == sorted(freqs) and freqs[0] == 1 and freqs[-1] == 4000


# -- job settings and stored work ----------------------------------------------------------------------------
def test_job_settings_are_validated_against_the_selected_laser(store):
    d = jpt(store)
    assert su.parameter_vector(d["passport"], 20, 48, 900, **JOB)["pulse_width"] == 200
    with pytest.raises(su.ValidationError, match="outside the range"):
        su.parameter_vector(d["passport"], 20, 48, 900, 600, 0.025, 1)


def test_a_passport_edit_does_not_depend_on_stored_job_settings(store):
    d = jpt(store)
    _plates(store, d["id"])                                               # stored work used the 200 ns step
    trimmed = dict(d["passport"], pulse_steps=[s for s in d["passport"]["pulse_steps"] if s["pulse_width_ns"] != 200])
    assert len(dv.update_device(store, d["id"], passport=trimmed)["passport"]["pulse_steps"]) == 16


def test_a_device_named_by_stored_work_cannot_be_deleted_and_the_refusal_leaves_its_lens_installed(store):
    from titanium_platform import lenses
    d = jpt(store)
    lens = lenses.create_lens(store, "F174", 174)
    lenses.install(store, d["id"], lens["id"])
    _plates(store, d["id"])
    with pytest.raises(su.ProtectedError, match="stored records of work"):
        dv.delete_device(store, d["id"])
    assert dv.get_device(store, d["id"])["lens"]["id"] == lens["id"]
    free = jpt(store, name="Unused")
    lenses.install(store, d["id"], None)
    lenses.install(store, free["id"], lens["id"])
    dv.delete_device(store, free["id"])
    assert [x["id"] for x in dv.list_devices(store)] == [d["id"]] and lenses.get_lens(store, lens["id"])["installed_on"] is None


# -- documents ---------------------------------------------------------------------------------------------
def test_a_document_is_stored_byte_for_byte_and_removed_with_its_file(store):
    d = jpt(store)
    doc = dv.add_document(store, d["id"], "test_report", "Протокол испытаний", "IMG 3262.JPG", JPEG)
    stored = dv.get_document(store, d["id"], doc["id"])
    assert open(stored["path"], "rb").read() == JPEG and doc["media_type"] == "image/jpeg" and doc["size"] == len(JPEG) and doc["title"] == "Протокол испытаний"
    assert " " not in stored["path"].rsplit("/files/", 1)[1]
    assert [x["id"] for x in dv.get_device(store, d["id"])["documents"]] == [doc["id"]]
    dv.delete_document(store, d["id"], doc["id"])
    assert not os.path.exists(stored["path"]) and dv.get_device(store, d["id"])["documents"] == []


@pytest.mark.parametrize("kind,name,data,message", [
    ("nope", "a.jpg", JPEG, "kind"), ("other", "a.exe", JPEG, "JPG, PNG, PDF or TXT"), ("other", "a.jpg", b"", "empty"),
    ("other", "a.jpg", PNG, "does not match"), ("other", "a.png", JPEG, "does not match"), ("other", "a.pdf", JPEG, "does not match"),
    ("other", "a.txt", b"\xff\xfe\x00bad", "does not match")])
def test_documents_are_checked(store, kind, name, data, message):
    d = jpt(store)
    with pytest.raises(su.ValidationError, match=message):
        dv.add_document(store, d["id"], kind, "t", name, data)
    assert dv.get_device(store, d["id"])["documents"] == []


def test_a_document_title_defaults_to_the_file_name_and_other_devices_documents_are_not_reachable(store):
    a, b = jpt(store), jpt(store, name="Second")
    doc = dv.add_document(store, a["id"], "other", "", "cutoff.png", PNG)
    assert doc["title"] == "cutoff"
    with pytest.raises(KeyError):
        dv.get_document(store, b["id"], doc["id"])
    with pytest.raises(KeyError):
        dv.delete_document(store, b["id"], doc["id"])


def test_deleting_a_device_removes_its_document_files(store):
    d = jpt(store)
    doc = dv.add_document(store, d["id"], "other", "t", "a.png", PNG)
    path = dv.get_document(store, d["id"], doc["id"])["path"]
    dv.delete_device(store, d["id"])
    assert not os.path.exists(path)




# -- plates carry the operating point -----------------------------------------------------------------------
def _plates(store, device_id):
    from titanium_platform import plans as pl
    pl.save_marker_layer_settings(store, 20, 60, 300)
    return pl.create_plate_series(store, device_id, "10 50", "24 80", "900", 6, 5, 1, **JOB)


def test_plate_cells_carry_the_operating_point_outside_the_parameter_vector(store):
    from titanium_platform import plans as pl
    made = _plates(store, jpt(store)["id"])
    plate = json.loads(store.one("SELECT cells_json FROM plate WHERE id=?", (made[0]["plate_id"],))["cells_json"])
    low = next(c for c in plate if c["parameters"]["power"] == 50 and c["parameters"]["frequency"] == 24)
    assert low["operating_point"]["below_cutoff"] is True and low["operating_point"]["basis"] == "passport model"
    assert low["operating_point"]["output_power_w"] == pytest.approx(60 * 0.5 * 24 / 48)
    assert "operating_point" not in low["parameters"] and set(low["parameters"]) == {"power", "frequency", "speed", "pulse_width", "line_interval", "passes"}
    layer = pl.get_plan(store, made[0]["plan_id"])["layers"][0]
    assert layer["operating_point"] is not None and layer["parameters"] == plate[0]["parameters"]




def test_a_layer_whose_job_settings_are_unknown_gets_no_operating_point_and_no_default(client):
    """REQ-016: an unknown pulse width stays unknown; no 200 ns is put in its place to compute figures."""
    d = client.post("/api/devices/from-template", json={"template": TEMPLATE}).json()
    layer = {"index": 1, "name": "C01", "parameters": {"power": 50, "frequency": 24, "speed": 900, "pulse_width": None,
                                                       "line_interval": 0.025, "passes": 1}, "regions": []}
    store = client.app.state.store
    plan_id = store.execute("INSERT INTO plan(name,mode,status,device_id,lens_id,markers,data_json,created_at) VALUES ('Old work',?,'Ready to export',?,NULL,0,?,'t')",
                            ("Restored from file", d["id"], json.dumps({"layers": [layer]}))).lastrowid
    got = client.get(f"/api/plans/{plan_id}").json()["layers"][0]
    assert got.get("operating_point") is None and got["parameters"]["pulse_width"] is None


# -- API -------------------------------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as c:
        yield c
    app.state.store.close()


def test_api_device_flow(client):
    assert client.get("/api/device-templates").json()[0]["key"] == TEMPLATE
    d = client.post("/api/devices/from-template", json={"template": TEMPLATE, "serial": "S"}).json()
    assert d["serial"] == "S" and client.get("/api/devices").json()[0]["id"] == d["id"]
    assert len(client.get(f"/api/devices/{d['id']}/charts").json()["curves"]) == 16
    assert "profiles" not in d
    op = client.post("/api/operating-point", json={"device_id": d["id"], "lens_id": None, "power": 30, "frequency": 40, "speed": 900, **JOB}).json()
    assert op["below_cutoff"] is True and op["output_power_w"] == pytest.approx(60 * 0.3 * 40 / 48)


def test_api_job_settings_are_checked_and_a_device_with_stored_work_is_kept(client):
    d = client.post("/api/devices/from-template", json={"template": TEMPLATE}).json()
    invalid_point = client.post("/api/operating-point", json={"device_id": d["id"], "lens_id": None, "power": 20, "frequency": 48,
                                                              "speed": 900, "pulse_width": 600, "line_interval": 0.025, "passes": 1})
    assert invalid_point.status_code == 422 and "outside the range" in invalid_point.json()["error"]
    client.put("/api/marker-layer", json={"power": 20, "frequency": 60, "speed": 300})
    plates = {"device_id": d["id"], "powers": "50", "frequencies": "24", "speeds": "900", "cell_width": 6, "cell_height": 5, "gap": 1}
    assert client.post("/api/plates", json=plates).status_code == 422          # the job settings are never filled in
    assert client.post("/api/plates", json=plates | JOB).status_code == 201
    r = client.delete(f"/api/devices/{d['id']}")
    assert r.status_code == 409 and "stored records of work" in r.json()["error"]


def test_api_documents_round_trip_and_errors(client):
    d = client.post("/api/devices/from-template", json={"template": TEMPLATE}).json()
    url = f"/api/devices/{d['id']}/documents"
    r = client.post(url, data={"kind": "waveform", "title": "Форма импульса"}, files={"file": ("IMG_3263.jpg", io.BytesIO(JPEG), "image/jpeg")})
    assert r.status_code == 201
    doc = r.json()
    got = client.get(f"{url}/{doc['id']}")
    assert got.status_code == 200 and got.content == JPEG and got.headers["content-type"] == "image/jpeg"
    assert got.headers["content-disposition"].startswith("inline;") and got.headers["x-content-type-options"] == "nosniff"
    assert client.post(url, data={"kind": "other"}).status_code == 422
    r = client.post(url, data={"kind": "other"}, files={"file": ("a.exe", io.BytesIO(b"MZ"), "application/octet-stream")})
    assert r.status_code == 422 and "JPG, PNG, PDF or TXT" in r.json()["error"]
    assert client.get(f"{url}/999").status_code == 404 and client.get("/api/devices/999").status_code == 404
    assert client.delete(f"{url}/{doc['id']}").status_code == 204 and client.get(f"{url}/{doc['id']}").status_code == 404


def test_api_patch_a_device_and_validation_errors(client):
    d = client.post("/api/devices/from-template", json={"template": TEMPLATE}).json()
    r = client.patch(f"/api/devices/{d['id']}", json={"serial": "S2", "passport": dict(d["passport"], open_items=["scale factors"])})
    assert r.json()["serial"] == "S2" and "spot_diameter_um" not in r.json()["passport"] and r.json()["passport"]["open_items"] == ["scale factors"]
    spot = client.patch(f"/api/devices/{d['id']}", json={"passport": dict(d["passport"], spot_diameter_um=40)})   # a spot is the lens's (REQ-019)
    assert spot.status_code == 422 and "belongs to the lens" in spot.json()["error"]
    assert client.patch(f"/api/devices/{d['id']}", json={"passport": {"rated_power_w": 60}}).status_code == 422
    assert client.post("/api/devices", json={"name": "X", "passport": {}}).status_code == 422
    assert client.post("/api/devices/from-template", json={"template": "nope"}).status_code == 422

