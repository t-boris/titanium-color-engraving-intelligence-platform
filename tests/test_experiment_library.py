import json

from fastapi.testclient import TestClient

from titanium_platform import devices, experiment_library, knowledge, lenses, model, setup as su
from titanium_platform.api.app import create_app
from titanium_platform.db import now
import obs


TEMPLATE = "jpt-ydflp-e-60-m7-m-r"


def test_lookup_uses_all_six_settings_and_does_not_mix_lightburn_modes(store):
    base = {"power": 20, "frequency": 48, "speed": 900, "pulse_width": 200, "line_interval": 0.05, "passes": 1}
    assert model.parameters_key(base) != model.parameters_key(base | {"line_interval": 0.1})
    fill = base | {"layer_type": "Scan", "global_passes": 1, "cross_hatch": False}
    cut = base | {"layer_type": "Line" , "global_passes": 1, "cross_hatch": False}
    assert model.parameters_key(fill) != model.parameters_key(cut)
    assert model.base_parameters_key(fill) == model.base_parameters_key(cut)
    wobble_a = fill | {"source_settings": {"wobbleStep": {"Value": "0.0500"}, "maxPower": {"Value": "20.0"}}}
    wobble_b = fill | {"source_settings": {"wobbleStep": {"Value": "0.05"}, "maxPower": {"Value": "20"}}}
    wobble_c = fill | {"source_settings": {"wobbleStep": {"Value": "0.10"}, "maxPower": {"Value": "20"}}}
    assert model.parameters_key(wobble_a) == model.parameters_key(wobble_b)
    assert model.parameters_key(wobble_a) != model.parameters_key(wobble_c)


def test_learning_is_kept_apart_by_lens_and_by_titanium_stock(store):
    device = devices.create_from_template(store, TEMPLATE, serial="LASER-A")
    lens = lenses.create_lens(store, "F174", 174)
    other_lens = lenses.create_lens(store, "F254", 254)
    stand = su.save_capture_setup(store, "Photo", "cam", "LED", "90", "ColorChecker")
    world = {"device": device, "setup": (device["id"], lens["id"]), "stand": stand, "n": 0}
    world_other = {"device": device, "setup": (device["id"], other_lens["id"]), "stand": stand, "n": 0}
    titanium_a = su.save_material(store, "Grade 2 batch A", grade="Grade 2", thickness_mm=1.0, surface="brushed", batch="A")
    titanium_b = su.save_material(store, "Grade 5 batch B", grade="Grade 5", thickness_mm=1.0, surface="mill", batch="B")
    obs.add(store, world, (50, 0, 0), material_id=titanium_a["id"])
    obs.add(store, world, (52, 0, 0), material_id=titanium_a["id"])
    obs.add(store, world, (75, 0, 0), material_id=titanium_b["id"])
    obs.add(store, world_other, (80, 0, 0), material_id=titanium_b["id"])

    samples = model.knowledge_summaries(store, device["id"], lens["id"])
    key_a = model.observation_key(obs_parameters(device), {"material_id": titanium_a["id"]})
    key_b = model.observation_key(obs_parameters(device), {"material_id": titanium_b["id"]})
    assert samples[key_a]["independent_engravings"] == 2 and samples[key_a]["available"]
    assert samples[key_b]["independent_engravings"] == 1 and not samples[key_b]["available"]
    assert model.knowledge_summaries(store, device["id"], other_lens["id"])[key_b]["lab"] == [80, 0, 0]
    knowledge.refresh(store, device["id"], lens["id"])
    assert {item["parameters_key"] for item in knowledge.list_for_setup(store, device["id"], lens["id"])} == {key_a, key_b}
    assert knowledge.list_for_setup(store, device["id"], other_lens["id"]) == []
    lookup = experiment_library.lookup_result(store, device["id"], lens["id"], obs_parameters(device))
    assert len(lookup["matches"]) == 2
    by_grade = {match["material_contexts"][0]["titanium_grade"]: match for match in lookup["matches"]}
    assert by_grade["Grade 2"]["available_for_prediction"]
    assert len(by_grade["Grade 2"]["source_pair_ids"]) == 2
    assert not by_grade["Grade 5"]["available_for_prediction"]
    assert experiment_library.lookup_result(store, device["id"], None, obs_parameters(device))["matches"] == []


def obs_parameters(device):
    return su.parameter_vector(device["passport"], 10, 40, 900, 200, 0.025, 1)


def test_device_archive_keeps_pending_photo_lightburn_material_and_hardware_snapshot(tmp_path):
    app = create_app(tmp_path / "archive")
    store = app.state.store
    device = devices.create_from_template(store, TEMPLATE, serial="ARCHIVE-1")
    lens = lenses.create_lens(store, "F174", 174)
    lenses.install(store, device["id"], lens["id"])
    titanium = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed", batch="B-17")
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")   # every photograph names its rig (REQ-009)
    store.set_setting("allow_non_raw_photos", True)
    with TestClient(app) as client:
        unknown = client.post("/api/pairs", data={"device_id": device["id"], "lens_id": "unknown", "context": json.dumps({"material_id": titanium["id"]})},
                              files={"lightburn": ("old.lbrn2", b"<LightBurnProject/>", "application/xml"),
                                     "photo": ("old.png", b"old photo bytes", "image/png")}).json()
        assert unknown["lens_id"] is None and unknown["hardware"]["lens"] is None      # the installed lens is not assumed (REQ-016)
        missing = client.post("/api/pairs", data={"device_id": device["id"], "context": json.dumps({"material_id": titanium["id"]})},
                              files={"lightburn": ("old.lbrn2", b"<LightBurnProject/>", "application/xml"),
                                     "photo": ("old.png", b"old photo bytes", "image/png")})
        assert missing.status_code == 422                                              # the lens is an explicit choice
        client.delete(f"/api/pairs/{unknown['id']}")
        pair = client.post("/api/pairs", data={"device_id": device["id"], "lens_id": str(lens["id"]), "context": json.dumps({"material_id": titanium["id"]})},
                           files={"lightburn": ("source.lbrn2", b"<LightBurnProject/>", "application/xml"),
                                  "photo": ("result.png", b"original photo bytes", "image/png")}).json()
        archive = client.get(f"/api/devices/{device['id']}/experiments").json()
        assert len(archive) == 1
        run = archive[0]
        assert run["pair_id"] == pair["id"] and run["status"] == "Awaiting check"
        assert run["hardware"]["device"]["serial"] == "ARCHIVE-1"
        assert run["hardware"]["lens"]["id"] == lens["id"]
        assert run["material"]["grade"] == "Grade 2" and run["material"]["batch"] == "B-17"
        assert client.get(run["source_photo_url"]).content == b"original photo bytes"
        assert client.get(run["lightburn_url"]).content == b"<LightBurnProject/>"
        stand = su.save_capture_setup(store, "Photo", "cam", "LED", "90", "ColorChecker")
        obs.add(store, {"device": device, "setup": (device["id"], lens["id"]), "stand": stand, "n": 0}, (48, 1, 2), material_id=titanium["id"])
        result = client.post(f"/api/devices/{device['id']}/result-lookup", json={
            "lens_id": lens["id"], "power": 10, "frequency": 40, "speed": 900,
            "pulse_width": 200, "line_interval": 0.025, "passes": 1}).json()
        assert len(result["matches"]) == 1 and result["matches"][0]["lab"] == [48.0, 1.0, 2.0]
    store.close()


def test_the_archive_names_the_lens_of_the_work_record_not_an_older_snapshot(store):
    """DEC-063: one source of truth for the lens of a work; a disagreeing stored snapshot does not override it."""
    device = devices.create_from_template(store, TEMPLATE)
    used, other = lenses.create_lens(store, "F174", 174), lenses.create_lens(store, "F254", 254)
    stand = su.save_capture_setup(store, "Photo", "cam", "LED", "90", "ColorChecker")
    obs.add(store, {"device": device, "setup": (device["id"], used["id"]), "stand": stand, "n": 0}, (48, 1, 2))
    store.execute("UPDATE pair SET hardware_json=?", (json.dumps({"device": {"id": device["id"]}, "lens": {"id": other["id"], "name": "F254"}}),))
    (item,) = experiment_library.for_device(store, device["id"])
    assert item["lens_id"] == used["id"] and item["lens"]["name"] == "F174"
