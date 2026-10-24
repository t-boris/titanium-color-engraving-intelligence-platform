"""A connected laboratory release as the source of a work (electron REQ-085): it is chosen explicitly with the laser, lens and titanium it
measured and stays visible; the work is pinned to it and keeps its confirmed palette or file; when it cannot be calculated again its
confirmed result is kept and the reason shown; a source is updated only by an explicit step that is previewed first and can be gone back
on; nothing of the recipient's picture or work leaves the computer."""
import json
import socket

import pytest
from fastapi.testclient import TestClient

from test_grey_scales import app_world, picture_png  # noqa: F401
from test_vector_photo_zones import of_colour, world  # noqa: F401  (grey scales and flat colours on one laser, lens and titanium)
from test_vector_work import RED, picture
from titanium_platform import devices, evidence_source as es, lab_export, lab_import, plans as pl
from titanium_platform import setup as su
from titanium_platform.api.app import create_app


def _uuid(store, kind: str, local: int) -> str:
    return store.one("SELECT uuid FROM portable_id WHERE kind=? AND local_key=?", (kind, str(local)))["uuid"]


@pytest.fixture(scope="module")
def lab(world, tmp_path_factory):  # noqa: F811
    """The grey-scale workshop published twice and connected by another workshop with a laser and titanium of its own."""
    author = world["store"]
    lab_export.set_public_info(author, {"name": "Grey lab", "author": "A. Author"})
    folder = tmp_path_factory.mktemp("lab")
    first = lab_export.export(author, folder / "1.tcelab", None, "CC-BY-4.0")
    second = lab_export.export(author, folder / "2.tcelab", None, "CC-BY-4.0")
    with TestClient(create_app(folder / "reader")) as client:
        store = client.app.state.store
        laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="Own laser", serial="OWN-1")
        titanium = su.save_material(store, "Own sheet", grade="Grade 5", thickness_mm=1.0)
        lab_import.start(store, lab_import.stage(store, [(folder / "1.tcelab").read_bytes()]), wait=True)
        source = {"release_id": first["release_id"], "laser": _uuid(author, "laser", world["laser"]["id"]),
                  "lens": _uuid(author, "lens", world["lens"]["id"]), "material": _uuid(author, "material", world["titanium"]["id"])}
        yield {"client": client, "store": store, "laser": laser, "titanium": titanium, "source": source, "first": first, "second": second,
               "folder": folder}


def connect_second(lab):
    lab_import.start(lab["store"], lab_import.stage(lab["store"], [(lab["folder"] / "2.tcelab").read_bytes()]), wait=True)


def vector_work(lab, source=None, strategy="photo"):
    data = {"device_id": lab["laser"]["id"], "lens_id": "unknown", "material_id": lab["titanium"]["id"], "name": "Portrait", "width_mm": 60,
            "strategy": strategy, "n_colors": 5, "threshold": 6, "detail": "medium", "faces": "false",
            "source": json.dumps(lab["source"] if source is None else source)}
    return lab["client"].post("/api/vector", data=data, files={"image": ("photo.png", picture(), "image/png")})


def photo_work(lab):
    source = {k: lab["source"][k] for k in ("release_id", "laser", "lens")} | {"device_id": lab["laser"]["id"], "lens_id": None}
    answer = lab["client"].post("/api/photo-works", data={"width_mm": "40", "name": "Gradient", "source": json.dumps(source)},
                                files={"picture": ("g.png", picture_png(), "image/png")})
    assert answer.status_code == 201, answer.text
    return answer.json()


@pytest.fixture()
def offline(monkeypatch):
    """No connection may be opened while a work uses its source (REQ-085: the picture and the work stay on this computer)."""
    def refuse(*args, **kwargs):
        raise AssertionError("a connection was opened")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_the_choice_names_the_release_with_what_it_measured_and_its_palette_shows_everything_a_colour_is_used_by(lab):
    client = lab["client"]
    [choice] = client.get("/api/labs/choices").json()
    assert choice["name"] == "Grey lab" and choice["release"]["release_id"] == lab["first"]["release_id"]
    assert {(s["laser"]["uuid"], s["lens"]["uuid"], s["material"]["uuid"]) for s in choice["setups"]} >= {
        (lab["source"]["laser"], lab["source"]["lens"], lab["source"]["material"])}
    shown = client.post("/api/labs/palette", json=lab["source"]).json()
    assert shown["source"]["release_id"] == lab["first"]["release_id"] and shown["entries"]
    assert any("not promised" in c for c in shown["conditions"])
    for entry in shown["entries"]:
        assert {"lab", "srgb", "basis", "engravings", "agreement", "caution", "recipe"} <= set(entry)
        assert entry["recipe"]["power"] == entry["parameters"]["power"]
    scales = client.post("/api/labs/scales", json={k: lab["source"][k] for k in ("release_id", "laser", "lens")}).json()["scales"]
    assert scales and all(s["mode"]["material_id"] is not None for s in scales)
    wrong = client.post("/api/labs/palette", json={**lab["source"], "material": "00000000-0000-4000-8000-000000000000"})
    assert wrong.status_code == 422 and wrong.json()["error"] == "choose a titanium this release measured"


def test_a_photograph_work_takes_its_colours_from_the_release_and_keeps_the_palette_it_was_made_with(lab, offline):
    answer = vector_work(lab)
    assert answer.status_code == 201, answer.text
    job = answer.json()
    assert job["source"]["kind"] == "release" and job["source"]["release_id"] == lab["first"]["release_id"]
    assert job["source"]["laser"]["uuid"] == lab["source"]["laser"] and job["source"]["frozen"] is None
    assert job["source"]["conditions"][0].startswith("the colours and curves are another laboratory's measurements")
    offered = {e["id"] for e in lab["client"].post("/api/labs/palette", json=lab["source"]).json()["entries"]}
    assert job["entries"] and set(job["entries"]) <= offered
    plan = pl.get_plan(lab["store"], job["id"])
    kept = es.kept_palette(plan["evidence_source"])
    assert {e["id"] for e in kept} == offered and all(e["recipe"] for e in kept)
    assert plan["device_id"] == lab["laser"]["id"] and plan["material_id"] == lab["titanium"]["id"]   # engraved on the own laser
    assert "palette_path" not in json.dumps(job)
    exported = lab["client"].get(f"/api/vector/{job['id']}/export.lbrn2")
    assert exported.status_code == 200 and b"CutSetting" in exported.content


def test_a_traced_work_takes_the_own_measurements_and_a_choice_the_release_did_not_measure_is_refused(lab):
    traced = vector_work(lab, strategy="color")
    assert traced.status_code == 422 and "own measurements" in traced.json()["error"]
    other = vector_work(lab, source={**lab["source"], "laser": lab["source"]["material"]})
    assert other.status_code == 422 and other.json()["error"] == "choose a laser this release measured"


def test_a_photo_zone_of_a_pinned_work_is_engraved_on_the_release_scales(lab):
    job = vector_work(lab).json()
    red = of_colour({"store": lab["store"]}, job, RED)
    answer = lab["client"].post(f"/api/vector/{job['id']}/colouring", json={"op": "photo_add", "regions": red})
    assert answer.status_code == 200, answer.text
    [zone] = answer.json()["zones"]
    assert zone["problem"] is None, zone
    view = lab["client"].get(f"/api/vector/{job['id']}/photo/{zone['number']}").json()
    pin = pl.get_plan(lab["store"], job["id"])["evidence_source"]
    assert view["scale"]["device_id"] == pin["laser"]["id"] and view["picture"] is not None


def test_a_photo_work_on_a_release_keeps_its_file_and_when_the_algorithms_change_keeps_that_file(lab, monkeypatch):
    work = photo_work(lab)
    assert work["source"]["release_id"] == lab["first"]["release_id"] and work["picture"] is not None
    assert work["scale"]["device_id"] == pl.get_plan(lab["store"], work["id"])["evidence_source"]["laser"]["id"]
    ramp = lab["client"].post(f"/api/photo-works/{work['id']}/width-ramp")
    assert ramp.status_code == 422 and "transfer experiment" in ramp.json()["error"]
    confirmed = lab["client"].get(f"/api/photo-works/{work['id']}/export.lbrn2")
    assert confirmed.status_code == 200
    original = lab_export.algorithm_versions
    monkeypatch.setattr(lab_export, "algorithm_versions", lambda: {**original(), "prediction": "999"})
    frozen = lab["client"].get(f"/api/photo-works/{work['id']}").json()
    assert frozen["picture"] is None and "other versions of the algorithms (prediction)" in frozen["problem"]
    assert frozen["confirmed"]["file"].endswith("/export.lbrn2") and frozen["source"]["frozen"] == frozen["problem"]
    again = lab["client"].get(f"/api/photo-works/{work['id']}/export.lbrn2")
    assert again.status_code == 200 and again.content == confirmed.content
    changed = lab["client"].post(f"/api/photo-works/{work['id']}/settings", json={"min_power": 10})
    assert changed.status_code == 422 and "other versions of the algorithms" in changed.json()["error"]
    moved = lab["client"].post(f"/api/photo-works/{work['id']}/source", json={"confirm": True}).json()
    assert moved["to"]["release_id"] == lab["first"]["release_id"] and moved["work"]["picture"] is not None
    assert moved["work"]["source"]["versions"] == 1


def test_a_frozen_photograph_work_shows_its_confirmed_colours_and_is_calculated_again_only_when_its_source_is_updated(lab, monkeypatch):
    job = vector_work(lab).json()
    red = of_colour({"store": lab["store"]}, job, RED)
    lab["client"].post(f"/api/vector/{job['id']}/colouring", json={"op": "photo_add", "regions": red})
    original = lab_export.algorithm_versions
    monkeypatch.setattr(lab_export, "algorithm_versions", lambda: {**original(), "prediction": "999"})
    frozen = lab["client"].get(f"/api/vector/{job['id']}").json()
    assert "other versions of the algorithms (prediction)" in frozen["source"]["frozen"]
    assert frozen["entries"] == job["entries"] or set(frozen["entries"]) <= set(job["entries"])      # the confirmed colours
    assert [z["problem"] for z in frozen["zones"]] == [frozen["source"]["frozen"]]
    refused = lab["client"].get(f"/api/vector/{job['id']}/photo/1/preview.png")
    assert refused.status_code == 422
    updated = lab["client"].post(f"/api/vector/{job['id']}/source", json={"confirm": True}).json()
    assert updated["to"]["release_id"] == lab["first"]["release_id"] and updated["work"]["source"]["frozen"] is None
    assert updated["work"]["zones"][0]["problem"] is None


def test_updating_the_source_is_previewed_moves_the_work_and_can_be_gone_back_on(lab):
    job = vector_work(lab).json()
    connect_second(lab)
    shown = lab["client"].get(f"/api/vector/{job['id']}").json()
    assert shown["source"]["release_id"] == lab["first"]["release_id"]                 # a newer release does not move a work
    assert any("a newer release of this laboratory is connected" in c for c in shown["source"]["conditions"])
    preview = lab["client"].post(f"/api/vector/{job['id']}/source", json={}).json()
    assert preview["to"]["release_id"] == lab["second"]["release_id"] and preview["missing"] == 0 and preview["max_delta_e"] == 0.0
    assert preview["work"]["source"]["release_id"] == lab["first"]["release_id"]        # a preview changes nothing
    moved = lab["client"].post(f"/api/vector/{job['id']}/source", json={"confirm": True}).json()
    assert moved["work"]["source"]["release_id"] == lab["second"]["release_id"] and moved["work"]["source"]["versions"] == 1
    plan = pl.get_plan(lab["store"], job["id"])
    assert plan["history"][-1]["op"] == {"op": "source", "release_id": lab["second"]["release_id"], "back": False}
    with pytest.raises(su.ValidationError, match="saved works use this release"):
        lab_import.remove_release(lab["store"], lab["first"]["release_id"])            # kept to go back to
    nothing = lab["client"].post(f"/api/vector/{job['id']}/source", json={"confirm": True})
    assert nothing.status_code == 422 and "nothing to update" in nothing.json()["error"]
    back = lab["client"].post(f"/api/vector/{job['id']}/source", json={"back": True, "confirm": True}).json()
    assert back["work"]["source"]["release_id"] == lab["first"]["release_id"] and back["work"]["source"]["versions"] == 0
    copy = lab["client"].post(f"/api/vector/{job['id']}/copy", json={}).json()
    assert pl.get_plan(lab["store"], copy["id"])["evidence_source"]["release_id"] == lab["first"]["release_id"]
    gone = lab["client"].post(f"/api/vector/{job['id']}/source", json={"back": True})
    assert gone.status_code == 422 and gone.json()["error"] == "this work has no earlier source to go back to"


def test_settings_the_own_laser_cannot_take_are_refused_before_the_file_is_written(lab):
    store = lab["store"]
    narrow = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="Short pulses", serial="OWN-2")
    passport = devices.brief(store, narrow["id"])["passport"]
    passport["pulse_steps"] = [s for s in passport["pulse_steps"] if s["pulse_width_ns"] <= 200]
    store.execute("UPDATE laser_device SET data_json=? WHERE id=?", (json.dumps(passport), narrow["id"]))
    source = {k: lab["source"][k] for k in ("release_id", "laser", "lens")} | {"device_id": narrow["id"], "lens_id": None}
    work = lab["client"].post("/api/photo-works", data={"width_mm": "40", "name": "Gradient", "source": json.dumps(source)},
                              files={"picture": ("g.png", picture_png(), "image/png")}).json()
    pulse = work["scale"]["pulse_width"]
    refused = lab["client"].get(f"/api/photo-works/{work['id']}/export.lbrn2")
    assert refused.status_code == 422
    assert refused.json()["error"] == (f"the layer Gradient has settings this laser cannot take: pulse width {pulse:g} ns is outside the range "
                                       "of this laser (1-200 ns)")
    assert pl.get_plan(store, work["id"])["evidence_source"].get("confirmed") is None
