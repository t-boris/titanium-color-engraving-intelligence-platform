"""One general colour map: every measured colour with its settings and where it came from (REQ-029, DEC-057)."""
import json

import cv2
import numpy as np
import pytest

import synth
from titanium_platform import colormap, ingest as ig, profiles as pf


@pytest.fixture
def world(store):
    store.set_setting("allow_non_raw_photos", True)
    profile = pf.create_profile(store, "MOPA", 200, 0.025, 1)
    material = pf.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    return {"store": store, "profile": profile, "material": material}


def pair_with(w, observations, *, mode="raw_camera_relative", seed=3, status="Accepted"):
    """A pair row with observation rows written directly: (layer_index, lab, power, role)."""
    data = synth.framed_work(seed=seed, blobs=6)
    pid = ig.create_pair(w["store"], profile_id=w["profile"]["id"], lightburn_name=f"work{seed}.lbrn2", lightburn_bytes=data["lightburn"],
                         photo_name=f"photo{seed}.png", photo_bytes=cv2.imencode(".png", data["photo"])[1].tobytes(),
                         context={"material_id": w["material"]["id"]})
    w["store"].execute("UPDATE pair SET status=?, accepted_at='2026-10-16T12:00:00+00:00', hardware_json=? WHERE id=?",
                       (status, json.dumps({"device": {"name": "JPT"}, "lens": {"name": "F-Theta"}}), pid))
    engraving = w["store"].one("SELECT engraving_id FROM pair WHERE id=?", (pid,))["engraving_id"]
    for index, lab, power, role in observations:
        evidence = {"role": role, "layer_name": f"C{index:02d}", "color_measurement": {"mode": mode}}
        w["store"].execute(
            "INSERT INTO observation(pair_id,layer_index,profile_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,model_eligible,"
            "repeat_eligible,eligibility_reason,evidence_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, index, w["profile"]["id"], engraving, json.dumps(lab),
             json.dumps({"power": power, "frequency": 300.0, "speed": 1000.0, "pulse_width": 10.0, "line_interval": 0.005, "passes": 1, "layer_type": "Scan"}),
             "element anchors", "{}", int(mode == "reference_chart_corrected"), 1, "x", json.dumps(evidence), "2026-10-16T12:00:00+00:00"))
    return pid


WITNESS = (-1, [30.0, 0.0, 6.0], 20.0, "pre-test cleaning witness")


def test_a_camera_relative_colour_is_drawn_through_its_ratio_to_the_clean_surface_of_the_same_photograph(world):
    from titanium_platform import color
    pair_with(world, [WITNESS, (1, [20.0, 8.0, 21.0], 50.0, "test feature")])
    data = colormap.collect(world["store"])
    (point,) = data["points"]
    assert point["measurement"] == "relative" and point["approximate"] and point["referenced"]
    assert data["nominal_clean"]["lab"] == colormap.DEFAULT_CLEAN and data["nominal_clean"]["source"] == "default"
    assert point["delta"] == pytest.approx([-10.0, 8.0, 15.0])
    # the clean surface itself, put through the same rule, must come out as the nominal clean titanium
    assert colormap._against_clean(WITNESS[1], WITNESS[1], colormap.DEFAULT_CLEAN) == pytest.approx(colormap.DEFAULT_CLEAN, abs=0.05)
    assert point["display_lab"][0] < colormap.DEFAULT_CLEAN[0] and point["display_lab"][2] > colormap.DEFAULT_CLEAN[2]       # darker, yellower than clean


def test_the_same_appearance_photographed_with_another_exposure_lands_on_the_same_place(world):
    from titanium_platform import color
    clean, colour = color.srgb8_to_lab([150, 150, 150]), color.srgb8_to_lab([110, 80, 40])
    def under(exposure):      # exposure scales every channel in linear light
        return [[float(v) for v in color.linear_rgb_to_lab(np.clip(color.lab_to_linear_rgb(np.asarray(lab)) * exposure, 0, 1))] for lab in (clean, colour)]
    (c1, k1), (c2, k2) = under(1.0), under(0.35)
    assert k1 != pytest.approx(k2, abs=3)                         # as photographed they differ a lot
    pair_with(world, [(-1, c1, 20.0, "pre-test cleaning witness"), (1, k1, 50.0, "test feature")], seed=3)
    pair_with(world, [(-1, c2, 20.0, "pre-test cleaning witness"), (1, k2, 50.0, "test feature")], seed=4)
    a, b = colormap.collect(world["store"])["points"]
    assert color.delta_e(a["display_lab"], b["display_lab"]) < 1.0


def test_a_calibrated_colour_stays_absolute_and_defines_the_nominal_clean_titanium(world):
    pair_with(world, [(-1, [72.0, 0.5, 3.0], 20.0, "pre-test cleaning witness"), (1, [40.0, 10.0, 30.0], 50.0, "test feature")], mode="reference_chart_corrected")
    data = colormap.collect(world["store"])
    (point,) = data["points"]
    assert point["measurement"] == "calibrated" and not point["approximate"] and point["display_lab"] == [40.0, 10.0, 30.0]
    assert data["nominal_clean"] == {"lab": [72.0, 0.5, 3.0], "source": "chart"}


def test_a_colour_without_a_clean_reference_is_counted_and_kept_off_the_map_unless_asked(world):
    pair_with(world, [(1, [20.0, 8.0, 21.0], 50.0, "test feature")])
    assert colormap.collect(world["store"])["points"] == []
    assert colormap.collect(world["store"])["counts"]["unreferenced"] == 1
    (point,) = colormap.collect(world["store"], include_unreferenced=True)["points"]
    assert point["referenced"] is False and point["approximate"]


def test_service_layers_and_deleted_experiments_are_not_colours(world):
    pair_with(world, [WITNESS, (0, [50.0, 0.0, 0.0], 20.0, "registration, QR and engraved labels"), (1, [20.0, 8.0, 21.0], 50.0, "test feature")], seed=3)
    gone = pair_with(world, [WITNESS, (1, [22.0, 9.0, 22.0], 55.0, "test feature")], seed=4, status="Deleted")
    points = colormap.collect(world["store"])["points"]
    assert [p["layer_index"] for p in points] == [1] and all(p["pair_id"] != gone for p in points)


def test_each_colour_says_where_it_came_from_and_with_which_settings(world):
    pid = pair_with(world, [WITNESS, (5, [20.0, 8.0, 21.0], 50.0, "test feature")])
    (p,) = colormap.collect(world["store"])["points"]
    assert p["pair_id"] == pid and p["layer_name"] == "C05" and p["photo"] == "photo3.png" and p["experiment"].startswith("eng-")
    assert p["setup"] == "JPT · F-Theta" and p["material"] == "Grade 2 sheet · Grade 2" and p["parameters"]["power"] == 50.0


def test_filters_narrow_the_points_but_the_options_describe_everything(world):
    pair_with(world, [WITNESS, (1, [20.0, 8.0, 21.0], 50.0, "test feature")], seed=3)
    data = colormap.collect(world["store"], setup="another laser")
    assert data["points"] == [] and data["options"]["setups"] == ["JPT · F-Theta"]
    assert len(colormap.collect(world["store"], measurement="relative")["points"]) == 1
    assert colormap.collect(world["store"], measurement="calibrated")["points"] == []


def test_the_search_returns_one_entry_per_recipe_nearest_first_with_its_repeats(world):
    pair_with(world, [WITNESS, (1, [20.0, 8.0, 21.0], 50.0, "test feature"), (2, [24.0, 0.0, 6.0], 40.0, "test feature")], seed=3)
    pair_with(world, [WITNESS, (1, [20.4, 8.2, 21.2], 50.0, "test feature")], seed=4)            # the same recipe again
    shown = {p["parameters"]["power"]: p["display_lab"] for p in colormap.collect(world["store"])["points"]}
    wanted = [v + 0.3 for v in shown[50.0]]                       # a colour very near the recipe with 50 percent power
    result = colormap.search(world["store"], wanted, limit=5)
    first, second = result["matches"][0], result["matches"][1]
    assert first["parameters"]["power"] == 50.0 and first["repeats"] == 2 and len(first["experiments"]) == 2
    assert first["distance"] < second["distance"] and second["parameters"]["power"] == 40.0
    assert len(result["matches"]) == 2


def test_the_app_serves_the_colour_map_and_its_search(tmp_path):
    from fastapi.testclient import TestClient
    from titanium_platform.api.app import create_app
    client = TestClient(create_app(tmp_path / "data"))
    assert client.get("/api/colors").json()["points"] == []
    assert client.get("/api/colors/search", params={"L": 50, "a": 0, "b": 0}).json()["matches"] == []


def test_a_work_accepted_before_its_cleaning_layer_was_recognised_gets_its_witness_from_the_stored_file(world):
    # layer 0 of the synthetic work is the enclosing cleaning rectangle; its observation carries no witness role
    pid = pair_with(world, [(0, [30.0, 0.0, 6.0], 20.0, "test feature"), (1, [20.0, 8.0, 21.0], 50.0, "test feature")])
    points = colormap.collect(world["store"])["points"]
    assert [p["layer_index"] for p in points] == [1] and points[0]["referenced"] and points[0]["pair_id"] == pid
    assert points[0]["delta"] == pytest.approx([-10.0, 8.0, 15.0])
