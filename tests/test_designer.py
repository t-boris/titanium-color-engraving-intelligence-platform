import json

import numpy as np
import pytest

import obs
from titanium_platform import color, designer as ds, knowledge as kn, model, plans as pl, profiles as pf
from titanium_platform.db import now

KEYS = ("power", "frequency", "speed")


@pytest.fixture
def w(store):
    w = obs.setup(store)
    pl.save_marker_layer_settings(store, 20, 60, 300)
    return w


def measure(store, w, power, frequency, speed, lab, repeats=2):
    for k in range(repeats):
        obs.add(store, w, (lab[0] + (-1) ** k, lab[1], lab[2]), power=power, frequency=frequency, speed=speed)


def seed_measurements(store, w):
    measure(store, w, 20, 100, 800, (30, 5, 5))
    measure(store, w, 50, 400, 1500, (60, 20, -10))
    measure(store, w, 80, 1000, 3000, (80, -10, 30))
    measure(store, w, 35, 250, 2000, (45, 0, 15))


def vec(p):
    return tuple(p[k] for k in KEYS)


def test_without_enough_data_it_falls_back_to_gap_sampling_and_says_so(store, w):
    measure(store, w, 20, 100, 800, (30, 5, 5))
    p = ds.propose(store, w["profile"]["id"])
    assert not p["model"]["gaussian_process"] and any("not fitted" in n for n in p["notes"])
    assert {x["reason"] for x in p["parameters"]} == {"gap"} and len(p["parameters"]) == ds.DEFAULT_SIZE


def test_proposals_are_reproducible_for_a_fixed_database_state_and_seed(store, w):
    seed_measurements(store, w)
    a = ds.propose(store, w["profile"]["id"], seed=7)
    b = ds.propose(store, w["profile"]["id"], seed=7)
    assert a["id"] == b["id"] and [vec(x) for x in a["parameters"]] == [vec(x) for x in b["parameters"]]
    assert store.one("SELECT COUNT(*) AS n FROM proposal")["n"] == 1
    c = ds.propose(store, w["profile"]["id"], seed=8)
    assert c["id"] != a["id"] and [vec(x) for x in c["parameters"]] != [vec(x) for x in a["parameters"]]


def test_the_result_is_a_pure_function_of_data_and_seed_across_stores(tmp_path):
    from titanium_platform.db import Store
    out = []
    for name in ("a", "b"):
        s = Store(tmp_path / name)
        wd = obs.setup(s)
        seed_measurements(s, wd)
        out.append([vec(x) for x in ds.propose(s, wd["profile"]["id"], seed=3)["parameters"]])
        s.close()
    assert out[0] == out[1]


def test_a_new_observation_changes_the_state_and_so_the_proposal(store, w):
    seed_measurements(store, w)
    a = ds.propose(store, w["profile"]["id"], seed=1)
    measure(store, w, 65, 700, 2500, (70, 0, 0))
    b = ds.propose(store, w["profile"]["id"], seed=1)
    assert a["id"] != b["id"] and a["parameters"] != b["parameters"]


def test_every_proposed_set_has_a_named_reason_utility_and_stays_in_range(store, w):
    seed_measurements(store, w)
    p = ds.propose(store, w["profile"]["id"], size=10)
    axes = {a["key"]: a for a in w["profile"]["axes"]}
    assert len(p["parameters"]) == 10 and len({vec(x) for x in p["parameters"]}) == 10
    for x in p["parameters"]:
        assert x["reason"] in ds.ORDER and 0 < x["utility"] <= 1
        assert x["scores"][x["reason"]] == pytest.approx(x["utility"])  # the stated reason is the score that won
        for k in KEYS:
            assert axes[k]["min"] <= x[k] <= axes[k]["max"]


def test_proposals_are_not_just_a_clump(store, w):
    seed_measurements(store, w)
    axes = [a for a in w["profile"]["axes"] if a["key"] in KEYS]
    pts = [ds._norm(vec(x), axes) for x in ds.propose(store, w["profile"]["id"], size=8)["parameters"]]
    dmin = min(np.linalg.norm(a - b) for i, a in enumerate(pts) for b in pts[i + 1:])
    assert dmin >= 0.05


def test_a_set_far_from_everything_measured_is_proposed_for_a_gap(store, w):
    measure(store, w, 20, 100, 800, (30, 5, 5))
    measure(store, w, 22, 110, 850, (31, 5, 5))
    measure(store, w, 24, 120, 900, (32, 5, 5))
    p = ds.propose(store, w["profile"]["id"], size=3)
    far = [x for x in p["parameters"] if x["power"] > 50 or x["speed"] > 3000]
    assert far, "the proposals should leave the small measured corner"


def test_an_unreachable_target_steers_a_proposal_to_where_the_model_predicts_it(store, w):
    seed_measurements(store, w)
    target = (80.0, -10.0, 30.0)  # exactly the lab measured at (80, 1000, 3000)
    store.execute("INSERT INTO target_color(profile_id,lab_json,source_plan_id,source_color_key,created_at) VALUES (?,?,1,'c0',?)", (w["profile"]["id"], json.dumps(target), now()))
    p = ds.propose(store, w["profile"]["id"], size=6)
    tgt = [x for x in p["parameters"] if x["reason"] == "target"]
    assert tgt and tgt[0]["target_id"] == 1 and tgt[0]["estimated_distance_to_target"] < 6
    assert p["target_ids"] == [1] and p["unaddressed_targets"] == []
    assert store.one("SELECT proposal_id FROM target_color WHERE id=1")["proposal_id"] == p["id"]  # the target is linked to the proposal


def test_targets_cannot_be_addressed_without_a_fitted_model_and_are_reported_unaddressed(store, w):
    measure(store, w, 20, 100, 800, (30, 5, 5))
    store.execute("INSERT INTO target_color(profile_id,lab_json,source_plan_id,source_color_key,created_at) VALUES (?,?,1,'c0',?)", (w["profile"]["id"], json.dumps([80, -10, 30]), now()))
    p = ds.propose(store, w["profile"]["id"])
    assert p["unaddressed_targets"] == [1] and p["target_ids"] == []


def test_unstable_sets_need_a_saved_threshold_and_are_then_proposed_for_instability(store, w):
    measure(store, w, 20, 100, 800, (30, 5, 5), repeats=2)
    for lab in ((50, 0, 0), (80, 0, 0)):  # a very noisy set
        obs.add(store, w, lab, power=50, frequency=400, speed=1500)
    measure(store, w, 80, 1000, 3000, (80, -10, 30))
    before = ds.propose(store, w["profile"]["id"], size=8)
    assert all(x["reason"] != "instability" for x in before["parameters"])
    pf.save_rules(store, w["profile"]["id"], repeat_threshold=2, delta_tolerance=4, variance_threshold=2.0)
    after = ds.propose(store, w["profile"]["id"], size=8)
    noisy = [x for x in after["parameters"] if x["reason"] == "instability"]
    assert after["id"] != before["id"] and len(noisy) == 1 and vec(noisy[0]) == (50, 400, 1500)


def test_the_proposal_uses_observations_from_every_artefact_source(store, w):
    """Plate cells and finished works are one evidence pool; the designer cannot tell them apart."""
    seed_measurements(store, w)
    a = ds.propose(store, w["profile"]["id"], seed=2)
    store.execute("UPDATE pair SET plan_id=NULL")  # a finished work has no plate; same observation rows
    assert ds.propose(store, w["profile"]["id"], seed=2)["id"] == a["id"]


@pytest.mark.parametrize("kw", [dict(size=0), dict(size=ds.MAX_SIZE + 1), dict(size=2.5), dict(seed=1.5)])
def test_bad_arguments_are_rejected(store, w, kw):
    with pytest.raises(ds.DesignerError):
        ds.propose(store, w["profile"]["id"], **kw)


def test_plates_from_a_proposal_carry_the_reasons_and_mark_intersections(store, w):
    seed_measurements(store, w)
    p = ds.propose(store, w["profile"]["id"], size=5)
    out = ds.create_plates(store, p["id"], 5, 4, 1)
    assert {o["speed"] for o in out} == {x["speed"] for x in p["parameters"]}
    chosen = {vec(x): x for x in p["parameters"]}
    seen = 0
    for o in out:
        for cell in json.loads(store.one("SELECT cells_json FROM plate WHERE id=?", (o["plate_id"],))["cells_json"]):
            pr = cell["parameters"]
            key = (pr["power"], pr["frequency"], pr["speed"])
            if cell["proposed"]:
                seen += 1
                assert key in chosen and cell["reason"] == chosen[key]["reason"] and cell["target_id"] == chosen[key]["target_id"]
            else:
                assert key not in chosen and cell["reason"] is None  # an intersection, not a recommendation
    assert seen == 5
    assert sum(o["intersections"] for o in out) == sum(o["cells"] for o in out) - 5
    assert all(r["proposal_id"] == p["id"] for r in store.query("SELECT proposal_id FROM plate"))
    with pytest.raises(ds.DesignerError, match="already created"):
        ds.create_plates(store, p["id"], 5, 4, 1)


def test_plates_from_a_proposal_need_the_marker_layer_settings(store):
    w = obs.setup(store)
    seed_measurements(store, w)
    p = ds.propose(store, w["profile"]["id"], size=3)
    with pytest.raises(pf.ValidationError, match="marker layer"):
        ds.create_plates(store, p["id"], 5, 4, 1)
    assert store.one("SELECT COUNT(*) AS n FROM plate")["n"] == 0


def test_no_explainer_means_no_explanation_and_an_identical_proposal(store, w):
    seed_measurements(store, w)
    p = ds.propose(store, w["profile"]["id"])
    assert ds.attach_explanation(store, p["id"], None) is None
    assert ds.get_proposal(store, p["id"]) == p and p["explanation"] is None


def test_an_explainer_can_only_attach_text_and_cannot_change_parameters_or_data(store, w):
    seed_measurements(store, w)
    p = ds.propose(store, w["profile"]["id"])
    obs_before = [tuple(r) for r in store.query("SELECT * FROM observation ORDER BY id")]

    def hostile(copy_of_proposal):
        copy_of_proposal["parameters"][0]["power"] = 1.0   # tries to rewrite the proposal it was handed
        return "  Higher power may widen the gamut.  "

    text = ds.attach_explanation(store, p["id"], hostile)
    after = ds.get_proposal(store, p["id"])
    assert text == "Higher power may widen the gamut." and after["explanation"] == text
    assert after["parameters"] == p["parameters"]
    assert obs_before == [tuple(r) for r in store.query("SELECT * FROM observation ORDER BY id")]
    with pytest.raises(ds.DesignerError):
        ds.attach_explanation(store, p["id"], lambda c: "   ")
    assert len(ds.attach_explanation(store, p["id"], lambda c: "x" * 99999)) == ds.MAX_EXPLANATION_CHARS
