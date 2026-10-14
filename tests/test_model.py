import math

import pytest

import obs
from titanium_platform import model


@pytest.fixture
def w(store):
    return obs.setup(store)


def test_a_single_observation_gives_no_prediction_because_stability_is_not_assessed(store, w):
    obs.add(store, w, (50, 10, 20))
    s = model.knowledge_summaries(store, w["profile"]["id"])["10|40|900"]
    assert s["lab"] == [50, 10, 20] and not s["available"] and s["confidence"] is None and s["expected_delta_e"] is None
    assert s["stability"] == {"assessed": False, "variance": None, "max_deviation": None, "engravings": 1}
    assert model.predict_for_lab(list(model.knowledge_summaries(store, w["profile"]["id"]).values()), (50, 10, 20))["available"] is False


def test_two_engravings_give_hand_computed_estimates(store, w):
    obs.add(store, w, (50, 10, 20))
    obs.add(store, w, (52, 10, 24))
    s = model.knowledge_summaries(store, w["profile"]["id"])["10|40|900"]
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
    s = model.knowledge_summaries(store, w["profile"]["id"])["10|40|900"]
    assert s["engravings"] == 2 and s["independent_engravings"] == 2 and s["observations"] == 3
    assert s["lab"][0] == pytest.approx((51 + 60) / 2)
    assert s["rig_repeatability"] == {"assessed": True, "photos": 2, "mean_delta_e": pytest.approx(1.0)}
    assert s["stability"]["variance"] == pytest.approx((60 - 51) ** 2 / 2)


def test_a_rephotograph_does_not_count_as_an_independent_engraving(store, w):
    obs.add(store, w, (50, 0, 0), engraving="A")
    obs.add(store, w, (51, 0, 0), engraving="A", rephoto=True)
    s = model.knowledge_summaries(store, w["profile"]["id"])["10|40|900"]
    assert s["independent_engravings"] == 1 and s["engravings"] == 1 and not s["available"]


def test_parameter_sets_and_profile_versions_are_never_merged(store, w):
    from titanium_platform import profiles as pf
    obs.add(store, w, (50, 0, 0), power=10)
    obs.add(store, w, (60, 0, 0), power=20)
    assert set(model.knowledge_summaries(store, w["profile"]["id"])) == {"10|40|900", "20|40|900"}
    v2 = pf.update_profile(store, w["profile"]["id"], pulse_width=250, confirm_new_version=True)
    assert model.knowledge_summaries(store, v2["id"]) == {}


def test_ineligible_observations_are_ignored_by_the_model(store, w):
    obs.add(store, w, (50, 0, 0), model_eligible=0)
    assert model.knowledge_summaries(store, w["profile"]["id"]) == {}


def _two_samples(store, w):
    for lab in ((50, 10, 20), (52, 10, 24)):
        obs.add(store, w, lab, power=10)
    for lab in ((70, -20, 30), (72, -20, 34)):
        obs.add(store, w, lab, power=30)
    return list(model.knowledge_summaries(store, w["profile"]["id"]).values())


def test_prediction_returns_the_nearest_sample_with_all_three_estimates(store, w):
    samples = _two_samples(store, w)
    p = model.predict_for_lab(samples, (69, -19, 31))
    assert p["available"] and p["key"] == "30|40|900" and not p["outside_coverage"]
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
    assert {r["key"] for r in model.unstable_regions(samples, 5.0)} == {"10|40|900", "30|40|900"}
    assert model.unstable_regions(samples, 50.0) == []


def test_context_groups_label_unknown_and_state_the_attribution_limit(store, w):
    obs.add(store, w, (50, 0, 0), batch="B1", focus=0.0)
    obs.add(store, w, (55, 0, 0), batch=None, focus=None)
    s = model.knowledge_summaries(store, w["profile"]["id"])["10|40|900"]
    keys = {(g["batch"], g["focus"]): g for g in s["context_groups"]}
    assert keys[("B1", 0.0)]["batch_known"] and not keys[(None, None)]["batch_known"]
    assert "cannot be attributed" in s["attribution_note"]


def test_no_attribution_note_when_all_context_is_known(store, w):
    obs.add(store, w, (50, 0, 0), batch="B1", focus=0.0)
    obs.add(store, w, (55, 0, 0), batch="B1", focus=0.0)
    assert model.knowledge_summaries(store, w["profile"]["id"])["10|40|900"]["attribution_note"] is None
