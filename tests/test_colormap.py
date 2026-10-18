"""One general colour map: every measured colour with its settings and where it came from (REQ-029, DEC-057)."""
import json

import cv2
import numpy as np
import pytest

import synth
from titanium_platform import colormap, devices, ingest as ig, setup as su


@pytest.fixture
def world(store):
    store.set_setting("allow_non_raw_photos", True)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")   # every photograph names its rig (REQ-009)
    return {"store": store, "laser": laser, "material": material}


def pair_with(w, observations, *, mode="raw_camera_relative", seed=3, status="Accepted"):
    """A pair row with observation rows written directly: (layer_index, lab, power, role)."""
    data = synth.framed_work(seed=seed, blobs=6)
    pid = ig.create_pair(w["store"], device_id=w["laser"]["id"], lens_id=None, lightburn_name=f"work{seed}.lbrn2", lightburn_bytes=data["lightburn"],
                         photo_name=f"photo{seed}.png", photo_bytes=cv2.imencode(".png", data["photo"])[1].tobytes(),
                         context={"material_id": w["material"]["id"]})
    w["store"].execute("UPDATE pair SET status=?, accepted_at='2026-10-16T12:00:00+00:00', hardware_json=? WHERE id=?",
                       (status, json.dumps({"device": {"name": "JPT"}, "lens": {"name": "F-Theta"}}), pid))
    engraving = w["store"].one("SELECT engraving_id FROM pair WHERE id=?", (pid,))["engraving_id"]
    for index, lab, power, role in observations:
        evidence = {"role": role, "layer_name": f"C{index:02d}", "color_measurement": {"mode": mode}}
        w["store"].execute(
            "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,model_eligible,"
            "repeat_eligible,eligibility_reason,evidence_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, index, w["laser"]["id"], None, engraving, json.dumps(lab),
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


def test_a_colour_without_a_clean_reference_is_on_the_map_flagged_and_can_be_left_out(world):
    pair_with(world, [(1, [20.0, 8.0, 21.0], 50.0, "test feature")])
    data = colormap.collect(world["store"])
    (point,) = data["points"]
    assert point["referenced"] is False and point["approximate"] and point["display_lab"] == [20.0, 8.0, 21.0] and data["counts"]["unreferenced"] == 1
    left_out = colormap.collect(world["store"], include_unreferenced=False)
    assert left_out["points"] == [] and left_out["counts"]["unreferenced"] == 1


def test_service_layers_and_deleted_experiments_are_not_colours(world):
    pair_with(world, [WITNESS, (0, [50.0, 0.0, 0.0], 20.0, "registration, QR and engraved labels"), (1, [20.0, 8.0, 21.0], 50.0, "test feature")], seed=3)
    gone = pair_with(world, [WITNESS, (1, [22.0, 9.0, 22.0], 55.0, "test feature")], seed=4, status="Deleted")
    points = colormap.collect(world["store"])["points"]
    assert [p["layer_index"] for p in points] == [1] and all(p["pair_id"] != gone for p in points)


def test_each_colour_says_where_it_came_from_and_with_which_settings(world):
    pid = pair_with(world, [WITNESS, (5, [20.0, 8.0, 21.0], 50.0, "test feature")])
    (p,) = colormap.collect(world["store"])["points"]
    assert p["pair_id"] == pid and p["layer_name"] == "C05" and p["photo"] == "photo3.png" and p["experiment"].startswith("eng-")
    assert p["setup"] == f"laser:{world['laser']['id']}/lens:unknown" and p["setup_label"] == "JPT YDFLP-E-60-M7-M-R · линза неизвестна"
    assert p["material"] == "Grade 2 sheet · Grade 2" and p["parameters"]["power"] == 50.0


def test_filters_narrow_the_points_but_the_options_describe_everything(world):
    pair_with(world, [WITNESS, (1, [20.0, 8.0, 21.0], 50.0, "test feature")], seed=3)
    data = colormap.collect(world["store"], setup="laser:99/lens:unknown")
    assert data["points"] == [] and data["options"]["setups"] == [
        {"key": f"laser:{world['laser']['id']}/lens:unknown", "label": "JPT YDFLP-E-60-M7-M-R · линза неизвестна",
         "device_id": world["laser"]["id"], "lens_id": None}]
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


TONAL = {"color_measurement": {"mode": "raw_camera_relative"}, "layers": [{
    "index": 7, "name": "C07", "frequency_khz": 60.0, "speed": 128.0, "pulse_width": 300.0, "line_interval": 0.0169, "passes": 1,
    "tonal": {"evidence": "clear", "power_range": [5.0, 16.1], "bins": [
        {"gray": 0.3, "power_pct": 12.9, "L": 2.0, "a": 0.1, "b": -0.4}, {"gray": 0.6, "power_pct": 9.5, "L": 2.0, "a": 0.5, "b": 1.2},
        {"gray": 0.9, "power_pct": 6.0, "L": 7.2, "a": -0.4, "b": 1.9}]}}]}


def test_a_grayscale_work_gives_one_colour_per_step_of_its_grey_to_power_profile(world):
    pid = pair_with(world, [(7, [3.4, 0.2, 1.4], 16.1, "test feature")])          # layer 7 is not the cleaning layer: no reference
    world["store"].execute("UPDATE pair SET data_json=? WHERE id=?", (json.dumps({"check": TONAL}), pid))
    steps = [p for p in colormap.collect(world["store"])["points"] if p.get("source") == "tonal"]
    assert [p["parameters"]["power"] for p in steps] == [12.9, 9.5, 6.0] and not any(p["referenced"] for p in steps)
    assert all(p["parameters"]["frequency"] == 60.0 and p["parameters"]["speed"] == 128.0 and p["parameters"]["pulse_width"] == 300.0 for p in steps)
    assert steps[0]["layer_name"] == "C07 · серый 0.30" and steps[0]["lab"] == [2.0, 0.1, -0.4]
    assert colormap.search(world["store"], [7.2, -0.4, 1.9], limit=3)["matches"] == []             # no reference: not part of the search
    found = colormap.search(world["store"], [7.2, -0.4, 1.9], limit=3, include_unreferenced=True)["matches"][0]
    assert found["parameters"]["power"] == 6.0 and found["source"] == "tonal"


def test_two_lasers_with_the_same_name_stay_apart_on_the_map(world):
    """The map's laser and lens filter is keyed by the records; names are only labels (DEC-063)."""
    pair_with(world, [WITNESS, (1, [20.0, 8.0, 21.0], 50.0, "test feature")], seed=3)
    twin = devices.create_from_template(world["store"], "jpt-ydflp-e-60-m7-m-r")
    other = pair_with(world, [WITNESS, (1, [20.0, 8.0, 21.0], 50.0, "test feature")], seed=4)
    world["store"].execute("UPDATE pair SET device_id=? WHERE id=?", (twin["id"], other))
    data = colormap.collect(world["store"])
    assert len(data["options"]["setups"]) == 2 and len({p["group"] for p in data["points"]}) == 2
    only = colormap.collect(world["store"], setup=f"laser:{twin['id']}/lens:unknown")["points"]
    assert [p["pair_id"] for p in only] == [other]


# -- checks awaiting acceptance: provisional (DEC-045, REQ-020 AC7) ------------------------------------------------------------
def pending_check(w, layers, *, valid=True, status="Ready to accept", seed=5):
    """A pair whose check is stored but not accepted: (index, lab, power, role) per measured layer, no observation rows."""
    data = synth.framed_work(seed=seed, blobs=6)
    pid = ig.create_pair(w["store"], device_id=w["laser"]["id"], lens_id=None, lightburn_name=f"work{seed}.lbrn2", lightburn_bytes=data["lightburn"],
                         photo_name=f"photo{seed}.png", photo_bytes=cv2.imencode(".png", data["photo"])[1].tobytes(),
                         context={"material_id": w["material"]["id"]})
    reports = [{"index": index, "name": f"C{index:02d}", "type": "Scan", "role": role, "measured_lab": lab, "power": power, "frequency_khz": 300.0,
                "speed": 1000.0, "pulse_width": 10.0, "line_interval": 0.005, "passes": 1} for index, lab, power, role in layers]
    check = {"alignment": {"valid": valid, "method": "element anchors"}, "color_measurement": {"mode": "raw_camera_relative"}, "layers": reports}
    w["store"].execute("UPDATE pair SET status=?, data_json=? WHERE id=?", (status, json.dumps({"check": check}), pid))
    return pid


def test_a_checked_pair_awaiting_acceptance_is_on_the_map_as_provisional_with_a_link_to_its_review(world):
    pid = pending_check(world, [WITNESS, (1, [20.0, 8.0, 21.0], 50.0, "test feature")])
    data = colormap.collect(world["store"])
    (point,) = data["points"]
    assert point["provisional"] and point["review"] == f"/ingest?pair={pid}" and point["pair_id"] == pid
    assert point["referenced"] and point["display_lab"] == pytest.approx(colormap._against_clean([20.0, 8.0, 21.0], WITNESS[1], colormap.DEFAULT_CLEAN))
    assert data["counts"]["provisional"] == 1 and colormap.collect(world["store"], include_provisional=False)["points"] == []


def test_without_a_valid_alignment_or_measured_layers_a_pending_check_stays_off_the_map_and_a_deleted_one_always(world):
    pending_check(world, [(1, [20.0, 8.0, 21.0], 50.0, "test feature")], valid=False, seed=5)
    pending_check(world, [], seed=6)
    pending_check(world, [WITNESS, (1, [20.0, 8.0, 21.0], 50.0, "test feature")], status="Deleted", seed=7)
    assert colormap.collect(world["store"])["points"] == []


def test_provisional_colours_join_the_search_only_when_asked_and_then_say_so(world):
    pending_check(world, [WITNESS, (1, [20.0, 8.0, 21.0], 50.0, "test feature")])
    wanted = colormap.collect(world["store"])["points"][0]["display_lab"]
    plain = colormap.search(world["store"], wanted)
    assert plain["matches"] == [] and plain["counts"]["provisional"] == 1
    (found,) = colormap.search(world["store"], wanted, include_provisional=True)["matches"]
    assert found["provisional"] and found["distance"] == 0.0 and found["review"].startswith("/ingest?pair=")


def test_the_grey_steps_of_a_photo_engraving_awaiting_acceptance_are_provisional_too(world):
    pid = pending_check(world, [(7, [3.4, 0.2, 1.4], 16.1, "test feature")])
    check = {**TONAL, "alignment": {"valid": True, "method": "picture"}}
    check["layers"] = [{**TONAL["layers"][0], "measured_lab": [3.4, 0.2, 1.4], "type": "Image"}]
    world["store"].execute("UPDATE pair SET data_json=? WHERE id=?", (json.dumps({"check": check}), pid))
    steps = [p for p in colormap.collect(world["store"])["points"] if p.get("source") == "tonal"]
    assert [p["parameters"]["power"] for p in steps] == [12.9, 9.5, 6.0]
    assert all(p["provisional"] and p["review"] == f"/ingest?pair={pid}" for p in steps)


def test_a_recipe_counts_independent_engravings_and_its_photographs_apart(world):
    """DEC-021: a re-photograph of one engraving is not a repetition; it is one more photograph."""
    first = pair_with(world, [WITNESS, (1, [20.0, 8.0, 21.0], 50.0, "test feature")], seed=3)
    again = pair_with(world, [WITNESS, (1, [20.2, 8.1, 21.1], 50.0, "test feature")], seed=4)
    pair_with(world, [WITNESS, (1, [20.4, 8.2, 21.2], 50.0, "test feature")], seed=5)
    engraving = world["store"].one("SELECT engraving_id FROM pair WHERE id=?", (first,))["engraving_id"]
    world["store"].execute("UPDATE pair SET engraving_id=? WHERE id=?", (engraving, again))
    (entry,) = colormap.search(world["store"], [40.0, 10.0, 30.0])["matches"]
    assert entry["repeats"] == 2 and entry["photographs"] == 3 and len(entry["experiments"]) == 2


def test_chart_corrected_and_camera_relative_colours_of_one_recipe_are_separate_entries(world):
    pair_with(world, [WITNESS, (1, [20.0, 8.0, 21.0], 50.0, "test feature")], seed=3)
    pair_with(world, [(-1, [72.0, 0.5, 3.0], 20.0, "pre-test cleaning witness"), (1, [40.0, 10.0, 30.0], 50.0, "test feature")],
              mode="reference_chart_corrected", seed=4)
    matches = colormap.search(world["store"], [40.0, 10.0, 30.0])["matches"]
    assert sorted(m["measurement"] for m in matches) == ["calibrated", "relative"] and all(m["repeats"] == 1 for m in matches)


def test_two_titanium_stocks_of_one_name_and_grade_are_separate_entries(world):
    """The titanium is its stock record: two batches of the same grade never pool into one recipe."""
    pair_with(world, [WITNESS, (1, [20.0, 8.0, 21.0], 50.0, "test feature")], seed=3)
    other = pair_with(world, [WITNESS, (1, [20.0, 8.0, 21.0], 50.0, "test feature")], seed=4)
    batch = su.save_material(world["store"], "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed", batch="B-2")
    world["store"].execute("UPDATE pair SET material_id=? WHERE id=?", (batch["id"], other))
    matches = colormap.search(world["store"], [40.0, 10.0, 30.0])["matches"]
    assert len(matches) == 2 and {m["material_id"] for m in matches} == {world["material"]["id"], batch["id"]}
    assert len({m["material"] for m in matches}) == 1                     # the same label: only the record tells them apart
