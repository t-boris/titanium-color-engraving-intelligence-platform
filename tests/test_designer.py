import json

import numpy as np
import pytest

import obs
from titanium_platform import color, designer as ds, knowledge as kn, model, plans as pl, setup as su
from titanium_platform.db import now

KEYS = ("power", "frequency", "speed")
GROUP = {"pulse_width": 200, "line_interval": 0.025, "passes": 1}      # the job settings obs.add uses by default


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


def propose(store, w, **kw):
    return ds.propose(store, *w["setup"], **{**GROUP, **kw})


def axes(store, w):
    return ds._axes(su.resolve(store, *w["setup"]))


def test_without_enough_data_it_falls_back_to_gap_sampling_and_says_so(store, w):
    measure(store, w, 20, 100, 800, (30, 5, 5))
    p = propose(store, w)
    assert not p["model"]["gaussian_process"] and any("not fitted" in n for n in p["notes"])
    assert {x["reason"] for x in p["parameters"]} == {"gap"} and len(p["parameters"]) == ds.DEFAULT_SIZE


def test_proposals_are_reproducible_for_a_fixed_database_state_and_seed(store, w):
    seed_measurements(store, w)
    a = propose(store, w, seed=7)
    b = propose(store, w, seed=7)
    assert a["id"] == b["id"] and [vec(x) for x in a["parameters"]] == [vec(x) for x in b["parameters"]]
    assert store.one("SELECT COUNT(*) AS n FROM proposal")["n"] == 1
    c = propose(store, w, seed=8)
    assert c["id"] != a["id"] and [vec(x) for x in c["parameters"]] != [vec(x) for x in a["parameters"]]


def test_the_result_is_a_pure_function_of_data_and_seed_across_stores(tmp_path):
    from titanium_platform.db import Store
    out = []
    for name in ("a", "b"):
        s = Store(tmp_path / name)
        wd = obs.setup(s)
        seed_measurements(s, wd)
        out.append([vec(x) for x in propose(s, wd, seed=3)["parameters"]])
        s.close()
    assert out[0] == out[1]


def test_a_new_observation_changes_the_state_and_so_the_proposal(store, w):
    seed_measurements(store, w)
    a = propose(store, w, seed=1)
    measure(store, w, 65, 700, 2500, (70, 0, 0))
    b = propose(store, w, seed=1)
    assert a["id"] != b["id"] and a["parameters"] != b["parameters"]


def test_every_proposed_set_has_a_named_reason_utility_and_stays_in_range(store, w):
    seed_measurements(store, w)
    p = propose(store, w, size=10)
    ranges = {a["key"]: a for a in axes(store, w)}
    assert len(p["parameters"]) == 10 and len({vec(x) for x in p["parameters"]}) == 10
    for x in p["parameters"]:
        assert x["reason"] in ds.ORDER and 0 < x["utility"] <= 1
        assert x["scores"][x["reason"]] == pytest.approx(x["utility"])  # the stated reason is the score that won
        for k in KEYS:
            assert ranges[k]["min"] <= x[k] <= ranges[k]["max"]
        assert {k: x[k] for k in GROUP} == GROUP           # the job settings are the proposal's group


def test_proposals_are_not_just_a_clump(store, w):
    seed_measurements(store, w)
    pts = [ds._norm(vec(x), axes(store, w)) for x in propose(store, w, size=8)["parameters"]]
    dmin = min(np.linalg.norm(a - b) for i, a in enumerate(pts) for b in pts[i + 1:])
    assert dmin >= 0.05


def test_a_set_far_from_everything_measured_is_proposed_for_a_gap(store, w):
    measure(store, w, 20, 100, 800, (30, 5, 5))
    measure(store, w, 22, 110, 850, (31, 5, 5))
    measure(store, w, 24, 120, 900, (32, 5, 5))
    p = propose(store, w, size=3)
    far = [x for x in p["parameters"] if x["power"] > 50 or x["speed"] > 3000]
    assert far, "the proposals should leave the small measured corner"


def test_an_unreachable_target_steers_a_proposal_to_where_the_model_predicts_it(store, w):
    seed_measurements(store, w)
    target = (80.0, -10.0, 30.0)  # exactly the lab measured at (80, 1000, 3000)
    store.execute("INSERT INTO target_color(device_id,lens_id,lab_json,source_plan_id,source_color_key,created_at) VALUES (?,?,?,1,'c0',?)", (*w["setup"], json.dumps(target), now()))
    p = propose(store, w, size=6)
    tgt = [x for x in p["parameters"] if x["reason"] == "target"]
    assert tgt and tgt[0]["target_id"] == 1 and tgt[0]["estimated_distance_to_target"] < 6
    assert p["target_ids"] == [1] and p["unaddressed_targets"] == []
    assert store.one("SELECT proposal_id FROM target_color WHERE id=1")["proposal_id"] == p["id"]  # the target is linked to the proposal


def test_a_plate_made_for_a_target_colour_is_checked_against_it_after_measurement(store, w):
    """REQ-006 AC3: the cell that addressed a target is measured, compared with it within the saved tolerance, and the
    target records the result."""
    import cv2
    import synth
    from titanium_platform import analysis, ingest as ig
    store.set_setting("allow_non_raw_photos", True)                    # tests use PNG renders; real use requires RAW
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=6.0, variance_threshold=5.0)
    seed_measurements(store, w)
    target = (80.0, -10.0, 30.0)
    store.execute("INSERT INTO target_color(device_id,lens_id,lab_json,source_plan_id,source_color_key,created_at) VALUES (?,?,?,1,'c0',?)",
                  (*w["setup"], json.dumps(target), now()))
    proposal = propose(store, w, size=4)
    chosen = next(x for x in proposal["parameters"] if x["reason"] == "target")
    made = next(o for o in ds.create_plates(store, proposal["id"], 5, 4, 1) if o["speed"] == chosen["speed"])
    plan = pl.get_plan(store, made["plan_id"])
    cells = json.loads(store.one("SELECT cells_json FROM plate WHERE id=?", (made["plate_id"],))["cells_json"])
    cell = next(c for c in cells if c["target_id"] == 1)
    colours = {c["id"]: (110, 90, 70) for c in cells} | {cell["id"]: tuple(int(v) for v in color.lab_to_srgb8((80.0, -10.0, 33.0)))}
    titanium = su.save_material(store, "Grade 2 sheet", grade="Grade 2")
    pid = ig.create_pair(store, device_id=w["setup"][0], lens_id=w["setup"][1], stand_id=w["stand"]["id"], lightburn_name="target.lbrn2",
                         lightburn_bytes=pl.export_lbrn2(plan), photo_name="target.png", plan_id=plan["id"], context={"material_id": titanium["id"]},
                         photo_bytes=cv2.imencode(".png", synth.plate_photo(plan, colours))[1].tobytes())
    assert ig.check_pair(store, pid)["problems"] == []
    ig.review_masks(store, pid)
    ig.accept_pair(store, pid)

    checks = analysis.report_for_pair(store, pid)["target_checks"]

    assert [(c["target_id"], c["cell_id"], c["comparable"], c["tolerance"]) for c in checks] == [(1, cell["id"], True, 6.0)]
    assert checks[0]["target_lab"] == list(target) and 1.5 < checks[0]["delta_e"] < 4.5 and checks[0]["within_tolerance"] is True
    assert color.delta_e(checks[0]["measured_lab"], (80.0, -10.0, 33.0)) < 2.5
    recorded = ds.open_targets(store, *w["setup"])[0]["checks"]
    assert len(recorded) == 1 and recorded[0]["pair_id"] == pid and recorded[0]["within_tolerance"] is True
    assert recorded[0]["delta_e"] == pytest.approx(checks[0]["delta_e"])
    su.save_rules(store, *w["setup"], delta_tolerance=1.0)              # the report judges by the tolerance saved now ...
    assert analysis.report_for_pair(store, pid)["target_checks"][0]["within_tolerance"] is False
    assert ds.open_targets(store, *w["setup"])[0]["checks"][0]["tolerance"] == 6.0   # ... the record keeps the one it was judged by


def test_targets_cannot_be_addressed_without_a_fitted_model_and_are_reported_unaddressed(store, w):
    measure(store, w, 20, 100, 800, (30, 5, 5))
    store.execute("INSERT INTO target_color(device_id,lens_id,lab_json,source_plan_id,source_color_key,created_at) VALUES (?,?,?,1,'c0',?)", (*w["setup"], json.dumps([80, -10, 30]), now()))
    p = propose(store, w)
    assert p["unaddressed_targets"] == [1] and p["target_ids"] == []


def test_unstable_sets_need_a_saved_threshold_and_are_then_proposed_for_instability(store, w):
    measure(store, w, 20, 100, 800, (30, 5, 5), repeats=2)
    for lab in ((50, 0, 0), (80, 0, 0)):  # a very noisy set
        obs.add(store, w, lab, power=50, frequency=400, speed=1500)
    measure(store, w, 80, 1000, 3000, (80, -10, 30))
    before = propose(store, w, size=8)
    assert all(x["reason"] != "instability" for x in before["parameters"])
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=4, variance_threshold=2.0)
    after = propose(store, w, size=8)
    noisy = [x for x in after["parameters"] if x["reason"] == "instability"]
    assert after["id"] != before["id"] and len(noisy) == 1 and vec(noisy[0]) == (50, 400, 1500)


def test_the_proposal_uses_observations_from_every_artefact_source(store, w):
    """Plate cells and finished works are one evidence pool; the designer cannot tell them apart."""
    seed_measurements(store, w)
    a = propose(store, w, seed=2)
    store.execute("UPDATE pair SET plan_id=NULL")  # a finished work has no plate; same observation rows
    assert propose(store, w, seed=2)["id"] == a["id"]


def test_a_proposal_models_one_job_settings_group_and_never_mixes_another(store, w):
    """DEC-042: power, frequency and speed are modelled within one group of equal pulse width, line interval and passes."""
    seed_measurements(store, w)
    for pulse, (lab, power) in ((100, ((20, 40, -30), 25)), (100, ((25, 35, -25), 60)), (100, ((90, 0, 0), 45)), (100, ((10, 0, 0), 70))):
        obs.add(store, w, lab, power=power, frequency=300, speed=1200, pulse_width=pulse)
    for passes in (2, 3):                              # same pulse width, another pass count: another group
        obs.add(store, w, (5, 0, 0), power=40, frequency=300, speed=1200, passes=passes)
    a = propose(store, w, seed=4)
    assert a["group"] == GROUP and a["model"]["measured_sets"] == 4 and a["model"]["dimensions"] == 3
    assert all({k: x[k] for k in GROUP} == GROUP for x in a["parameters"])
    other = propose(store, w, seed=4, pulse_width=100)
    assert other["group"]["pulse_width"] == 100 and other["model"]["measured_sets"] == 4 and other["id"] != a["id"]
    obs.add(store, w, (60, 60, 60), power=90, frequency=900, speed=500, pulse_width=100)
    assert propose(store, w, seed=4)["id"] == a["id"]    # a measurement of another group does not change this proposal


def test_the_job_settings_of_a_proposal_are_required_and_must_be_offered_by_the_laser(store, w):
    with pytest.raises(TypeError):
        ds.propose(store, *w["setup"])                   # no pulse width, line interval or passes is filled in (DEC-043)
    with pytest.raises(su.ValidationError, match="not a selectable step"):
        propose(store, w, pulse_width=210)
    with pytest.raises(su.ValidationError, match="passes"):
        propose(store, w, passes=0)


def test_plates_need_the_lens_the_proposal_was_made_for(store, w):
    from titanium_platform import lenses
    seed_measurements(store, w)
    p = propose(store, w, size=3)
    lenses.install(store, w["device"]["id"], lenses.create_lens(store, "F-Theta 254", 254)["id"])
    with pytest.raises(ds.DesignerError, match="another lens"):
        ds.create_plates(store, p["id"], 5, 4, 1)
    assert store.one("SELECT COUNT(*) AS n FROM plate")["n"] == 0


@pytest.mark.parametrize("kw", [dict(size=0), dict(size=ds.MAX_SIZE + 1), dict(size=2.5), dict(seed=1.5)])
def test_bad_arguments_are_rejected(store, w, kw):
    with pytest.raises(ds.DesignerError):
        propose(store, w, **kw)


def test_plates_from_a_proposal_carry_the_reasons_and_mark_intersections(store, w):
    seed_measurements(store, w)
    p = propose(store, w, size=5)
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
    assert {(r["device_id"], r["lens_id"]) for r in store.query("SELECT device_id, lens_id FROM plate")} == {w["setup"]}
    with pytest.raises(ds.DesignerError, match="already created"):
        ds.create_plates(store, p["id"], 5, 4, 1)


def test_plates_from_a_proposal_need_the_marker_layer_settings(store):
    w = obs.setup(store)
    seed_measurements(store, w)
    p = propose(store, w, size=3)
    with pytest.raises(su.ValidationError, match="marker layer"):
        ds.create_plates(store, p["id"], 5, 4, 1)
    assert store.one("SELECT COUNT(*) AS n FROM plate")["n"] == 0


def test_no_explainer_means_no_explanation_and_an_identical_proposal(store, w):
    seed_measurements(store, w)
    p = propose(store, w)
    assert ds.attach_explanation(store, p["id"], None) is None
    assert ds.get_proposal(store, p["id"]) == p and p["explanation"] is None


def test_an_explainer_can_only_attach_text_and_cannot_change_parameters_or_data(store, w):
    seed_measurements(store, w)
    p = propose(store, w)
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
