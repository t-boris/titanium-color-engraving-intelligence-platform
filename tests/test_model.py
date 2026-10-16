import math

import pytest

import obs
from titanium_platform import model

BASE = "10|40|900|200|0.025|1"


@pytest.fixture
def w(store):
    return obs.setup(store)


def test_a_single_observation_gives_no_prediction_because_stability_is_not_assessed(store, w):
    obs.add(store, w, (50, 10, 20))
    s = model.knowledge_summaries(store, w["profile"]["id"])[BASE]
    assert s["lab"] == [50, 10, 20] and not s["available"] and s["confidence"] is None and s["expected_delta_e"] is None
    assert s["stability"] == {"assessed": False, "variance": None, "max_deviation": None, "engravings": 1}
    assert model.predict_for_lab(list(model.knowledge_summaries(store, w["profile"]["id"]).values()), (50, 10, 20))["available"] is False


def test_two_engravings_give_hand_computed_estimates(store, w):
    obs.add(store, w, (50, 10, 20))
    obs.add(store, w, (52, 10, 24))
    s = model.knowledge_summaries(store, w["profile"]["id"])[BASE]
    # sample variances (ddof=1): L: 2, a: 0, b: 8 -> total 10
    assert s["lab"] == [51, 10, 22]
    assert s["stability"]["variance"] == pytest.approx(10.0)
    assert s["stability"]["max_deviation"] == pytest.approx(math.sqrt(1 + 4))
    assert s["expected_delta_e"] == pytest.approx(math.sqrt(10.0))
    assert s["confidence"] == pytest.approx(2 / 4)
    assert s["available"] and s["independent_engravings"] == 2


def test_rephotographs_average_into_one_engraving_and_feed_rig_repeatability(store, w):
    obs.add(store, w, (50, 0, 0), engraving="A")
    obs.add(store, w, (52, 0, 0), engraving="A", rephoto=True)
    obs.add(store, w, (60, 0, 0), engraving="B")
    s = model.knowledge_summaries(store, w["profile"]["id"])[BASE]
    assert s["engravings"] == 2 and s["independent_engravings"] == 2 and s["observations"] == 3
    assert s["lab"][0] == pytest.approx((51 + 60) / 2)
    assert s["rig_repeatability"] == {"assessed": True, "photos": 2, "mean_delta_e": pytest.approx(1.0)}
    assert s["stability"]["variance"] == pytest.approx((60 - 51) ** 2 / 2)


def test_a_rephotograph_does_not_count_as_an_independent_engraving(store, w):
    obs.add(store, w, (50, 0, 0), engraving="A")
    obs.add(store, w, (51, 0, 0), engraving="A", rephoto=True)
    s = model.knowledge_summaries(store, w["profile"]["id"])[BASE]
    assert s["independent_engravings"] == 1 and s["engravings"] == 1 and not s["available"]


def test_parameter_sets_use_all_six_process_values_and_unlinked_lasers_stay_isolated(store, w):
    from titanium_platform import profiles as pf
    obs.add(store, w, (50, 0, 0), power=10)
    obs.add(store, w, (60, 0, 0), power=20)
    assert set(model.knowledge_summaries(store, w["profile"]["id"])) == {
        "10|40|900|200|0.025|1", "20|40|900|200|0.025|1"}
    separate = pf.create_profile(store, "unlinked laser identity")
    assert model.knowledge_summaries(store, separate["id"]) == {}


def test_ineligible_observations_are_ignored_by_the_model(store, w):
    obs.add(store, w, (50, 0, 0), model_eligible=0)
    assert model.knowledge_summaries(store, w["profile"]["id"]) == {}


def test_raw_camera_relative_observations_appear_as_per_photo_color_map_sets_but_never_predictions(store, w):
    import json
    from titanium_platform.db import now

    profile_id, stand_id = w["profile"]["id"], w["stand"]["id"]
    context = {"material_id": None, "titanium_name": "Grade 2", "titanium_grade": "Grade 2", "batch": "B1"}
    check = {"warnings": ["LightBurn layer indexes 30–43 are outside the standard output color range 00–29. "
                          "Their photo regions are still measured; the file alone cannot confirm whether those operations were emitted."],
             "layers": [{"index": 1, "name": "P100-F48", "notes": [
                 "This layer index is outside LightBurn's 30 standard output colors; its photo measurement is retained."]}]}
    pair_id = store.execute(
        "INSERT INTO pair(status,profile_id,stand_id,material_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at,accepted_at) "
        "VALUES ('Accepted',?,?,NULL,'raw-A','test.lbrn2','/x','test.DNG','/y',?,?,?,?)",
        (profile_id, stand_id, json.dumps(context), json.dumps({"check": check}), now(), now())).lastrowid
    settings = {"power": 100, "frequency": 48, "speed": 900, "pulse_width": 200,
                "line_interval": 0.025, "passes": 1}
    for layer_index, role, name, lab in ((-1, "pre-test cleaning witness", "CLEAN", [60, 0, 2]),
                                         (1, "test feature", "P100-F48", [18, 0, 1])):
        evidence = {"layer_name": name, "role": role, "pixels": 100,
                    "color_measurement": {"mode": "raw_camera_relative", "reference_chart_used": False}}
        store.execute(
            "INSERT INTO observation(pair_id,layer_index,profile_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at) "
            "VALUES (?,?,?,?,?,?, 'markers',?,0,1,'camera-relative',?,?)",
            (pair_id, layer_index, profile_id, "raw-A", json.dumps(lab), json.dumps(settings),
             json.dumps(context), json.dumps(evidence), now()))

    relative = model.camera_relative_sets(store, profile_id)
    assert len(relative) == 1 and relative[0]["pair_id"] == pair_id
    assert len(relative[0]["samples"]) == 2
    assert relative[0]["findings"][0]["name"] == "P100-F48"
    assert relative[0]["samples"][1]["delta_e_from_clean_witness"] == pytest.approx(model.color.delta_e([18, 0, 1], [60, 0, 2]))
    assert relative[0]["warnings"] == check["warnings"]
    assert relative[0]["samples"][1]["notes"] == check["layers"][0]["notes"]
    assert model.knowledge_summaries(store, profile_id) == {}


def test_relative_color_variants_keep_each_fill_patch_and_its_settings_without_promoting_it():
    entry = {"pair_id": 9, "samples": [
        {"name": "CLEAN", "role": "pre-test cleaning witness", "lab": [60, 0, 0],
         "parameters": {"layer_type": "Scan"}, "submeasurements": [], "observation_id": 1, "layer_index": -1},
        {"name": "MATRIX-A", "role": "test feature", "lab": [35, 0, 0],
         "parameters": {"layer_type": "Scan", "power": 20, "frequency": 48, "speed": 900,
                        "pulse_width": None, "line_interval": 0.025, "passes": 1},
         "submeasurements": [{"name": "blue", "measured_lab": [35, 2, -15], "pixels": 120},
                             {"name": "yellow", "measured_lab": [45, 1, 18], "pixels": 115}],
         "observation_id": 2, "layer_index": 1},
        {"name": "TEXT-A", "role": "test feature", "lab": [15, 0, 0],
         "parameters": {"layer_type": "Scan"}, "submeasurements": [],
         "observation_id": 3, "layer_index": 2},
    ]}
    result = model._finish_camera_relative_set(entry)
    variants = result["color_variants"]
    assert [v["name"] for v in variants] == ["MATRIX-A / blue", "MATRIX-A / yellow"]
    assert [v["lab"] for v in variants] == [[35, 2, -15], [45, 1, 18]]
    assert all(v["pair_id"] == 9 and v["observation_id"] == 2 for v in variants)
    assert all(v["status"] == "measured_relative" and not v["settings_complete"] for v in variants)
    assert variants[0]["delta_e_from_clean_witness"] == pytest.approx(model.color.delta_e([35, 2, -15], [60, 0, 0]))


def test_a_checked_raw_pair_is_visible_as_provisional_evidence_before_acceptance(store, w):
    import json
    from titanium_platform.db import now

    profile_id = w["profile"]["id"]
    context = {"titanium_name": "Grade 2", "titanium_grade": "Grade 2", "material_id": None}
    layers = [
        {"index": 0, "name": "CLEAN", "role": "pre-test cleaning witness", "measured_lab": [61.9, -1.3, 4.9],
         "power": 20, "frequency_khz": 48, "speed": 2000, "pulse_width": 200, "line_interval": 0.05, "passes": 1, "pixels": 100},
        {"index": 2, "name": "P100-F48", "role": "test feature", "measured_lab": [17.5, -0.5, 1.3],
         "power": 100, "frequency_khz": 48, "speed": 900, "pulse_width": 200, "line_interval": 0.025, "passes": 1, "pixels": 100},
        {"index": 3, "name": "P30-F60", "role": "test feature", "measured_lab": [49.2, -1.7, 11.7],
         "power": 30, "frequency_khz": 60, "speed": 900, "pulse_width": 200, "line_interval": 0.025, "passes": 1, "pixels": 100},
    ]
    check = {"color_measurement": {"mode": "raw_camera_relative"}, "alignment": {"valid": True}, "layers": layers, "problems": []}
    pair_id = store.execute(
        "INSERT INTO pair(status,profile_id,stand_id,material_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at) "
        "VALUES ('Ready to accept',?,NULL,NULL,'pending-A','test.lbrn2','/x','test.DNG','/y',?,?,?)",
        (profile_id, json.dumps(context), json.dumps({"masks_reviewed": False, "check": check}), now())).lastrowid

    relative = model.camera_relative_sets(store, profile_id)
    assert len(relative) == 1 and relative[0]["pair_id"] == pair_id
    assert relative[0]["provisional"] and not relative[0]["masks_reviewed"]
    assert relative[0]["findings"][0]["name"] == "P100-F48"
    assert relative[0]["findings"][2]["name"] == "P30-F60"
    assert relative[0]["samples"][1]["parameters"]["profile_id"] == profile_id
    assert model.knowledge_summaries(store, profile_id) == {}


def _two_samples(store, w):
    for lab in ((50, 10, 20), (52, 10, 24)):
        obs.add(store, w, lab, power=10)
    for lab in ((70, -20, 30), (72, -20, 34)):
        obs.add(store, w, lab, power=30)
    return list(model.knowledge_summaries(store, w["profile"]["id"]).values())


def test_prediction_returns_the_nearest_sample_with_all_three_estimates(store, w):
    samples = _two_samples(store, w)
    p = model.predict_for_lab(samples, (69, -19, 31))
    assert p["available"] and p["key"] == "30|40|900|200|0.025|1" and not p["outside_coverage"]
    assert p["confidence"] is not None and p["expected_delta_e"] is not None and p["stability"]["assessed"]
    assert p["distance_to_target"] == pytest.approx(model.color.delta_e(p["lab"], (69, -19, 31)))


def test_a_color_outside_the_measured_space_is_flagged_not_silently_matched(store, w):
    samples = _two_samples(store, w)
    assert model.predict_for_lab(samples, (90, 0, 0))["outside_coverage"] is True
    assert model.predict_for_lab(samples, (60, 0, 25))["outside_coverage"] is False
    with pytest.raises(ValueError):
        model.predict_for_lab(samples, (150, 0, 0))


def test_unstable_regions_need_a_saved_threshold(store, w):
    samples = _two_samples(store, w)
    assert model.unstable_regions(samples, None) == []
    assert {r["key"] for r in model.unstable_regions(samples, 5.0)} == {"10|40|900|200|0.025|1", "30|40|900|200|0.025|1"}
    assert model.unstable_regions(samples, 50.0) == []


def test_context_groups_label_unknown_and_state_the_attribution_limit(store, w):
    obs.add(store, w, (50, 0, 0), batch="B1", focus=0.0)
    obs.add(store, w, (55, 0, 0), batch=None, focus=None)
    samples = list(model.knowledge_summaries(store, w["profile"]["id"]).values())
    assert len(samples) == 2  # known context is not averaged with an unknown one
    known = next(s for s in samples if s["context_groups"][0]["batch"] == "B1")
    unknown = next(s for s in samples if s["context_groups"][0]["batch"] is None)
    assert known["context_groups"][0]["focus"] == 0.0 and known["context_groups"][0]["batch_known"]
    assert not unknown["context_groups"][0]["batch_known"]
    assert "cannot be attributed" in unknown["attribution_note"]


def test_no_attribution_note_when_all_context_is_known(store, w):
    obs.add(store, w, (50, 0, 0), batch="B1", focus=0.0)
    obs.add(store, w, (55, 0, 0), batch="B1", focus=0.0)
    p = model.parameters_key({"power": 10, "frequency": 40, "speed": 900, "pulse_width": 200, "line_interval": 0.025, "passes": 1})
    key = model.observation_key({"power": 10, "frequency": 40, "speed": 900, "pulse_width": 200, "line_interval": 0.025, "passes": 1},
                                {"batch": "B1", "focus": 0.0})
    assert key != p and model.knowledge_summaries(store, w["profile"]["id"])[key]["attribution_note"] is None


# -- recipe keys stay stable for existing data and see sub-layers (REQ-025) --------------------------------------------
def _legacy_key(p: dict) -> str:
    """parameters_key as it was before sub-layers were captured: numbers normalised one level deep."""
    import hashlib, json, math
    base = "|".join("?" if p.get(k) is None else f"{float(p[k]):g}" for k in
                    ("power", "frequency", "speed", "pulse_width", "line_interval", "passes"))
    controls = {k: p[k] for k in ("layer_type", "global_passes", "bidirectional", "cross_hatch", "scan_angle", "angle_increment") if k in p}
    known = {"maxPower", "frequency", "speed", "QPulseWidth", "interval", "numPasses", "passes",
             "globalRepeat", "bidir", "crossHatch", "angle", "anglePerPass"}
    extra = {}
    for tag, value in (p.get("source_settings") or {}).items():
        if tag in known:
            continue
        if isinstance(value, dict):
            normalized = {}
            for attr, raw in value.items():
                try:
                    number = float(raw)
                    normalized[attr] = f"{number:g}" if math.isfinite(number) else raw
                except (TypeError, ValueError):
                    normalized[attr] = raw
            extra[tag] = normalized
        else:
            extra[tag] = value
    if extra:
        controls["source_settings"] = extra
    encoded = json.dumps(controls, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"{base}|lb:{hashlib.sha256(encoded).hexdigest()}"


def test_keys_of_existing_flat_settings_do_not_change():
    from titanium_platform import model
    p = {"power": 75, "frequency": 330, "speed": 1300, "pulse_width": 4, "line_interval": 0.005, "passes": 1,
         "layer_type": "Scan", "global_passes": 1, "bidirectional": False, "cross_hatch": False, "scan_angle": 0.0, "angle_increment": 0.0,
         "source_settings": {"maxPower2": {"Value": "20.0"}, "scanOpt": {"Value": "individual"}, "tabCount": {"Value": "1"},
                             "wobbleStep": {"Value": "0.0500"}, "priority": {"Value": "15"}}}
    assert model.parameters_key(p) == _legacy_key(p)


def test_numbers_written_differently_inside_a_sub_layer_are_the_same_setting():
    from titanium_platform import model
    base = {"power": 60, "frequency": 48, "speed": 900, "pulse_width": 4, "line_interval": 0.02, "passes": 1}
    a = {**base, "source_settings": {"SubLayer": {"type": "Scan", "index": "1", "maxPower": {"Value": "20"}, "speed": {"Value": "2000.0"}}}}
    b = {**base, "source_settings": {"SubLayer": {"type": "Scan", "index": "1", "maxPower": {"Value": "20.0"}, "speed": {"Value": "2000"}}}}
    c = {**base, "source_settings": {"SubLayer": {"type": "Scan", "index": "1", "maxPower": {"Value": "25"}, "speed": {"Value": "2000"}}}}
    assert model.parameters_key(a) == model.parameters_key(b) != model.parameters_key(c)
