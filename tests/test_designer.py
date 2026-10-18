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


# -- REQ-022: what a proposal says, its status and what became of it ------------------------------------------------------
# The sets the designer chose before REQ-022 for the data of seed_unstable_and_target (seed 11, size 8): power, frequency,
# speed, reason and target. The new fields of a proposal must not change them, nor its signature.
CHOSEN_BEFORE_REQ_022 = [(63.0, 2053.0, 2782.0, "target", 1), (60.0, 600.0, 2500.0, "instability", None),
                         (13.7, 1998.0, 6015.0, "gap", None), (3.8, 593.0, 9282.0, "uncertainty", None),
                         (62.6, 1477.0, 5114.0, "gap", None), (79.0, 2682.0, 5124.0, "gap", None),
                         (81.9, 2197.0, 9809.0, "uncertainty", None), (21.2, 2215.0, 4837.0, "gap", None)]


def seed_unstable_and_target(store, w):
    seed_measurements(store, w)
    for lab in ((50, 0, 0), (80, 0, 0)):
        obs.add(store, w, lab, power=60, frequency=600, speed=2500)
    store.execute("INSERT INTO target_color(device_id,lens_id,lab_json,source_plan_id,source_color_key,created_at) VALUES (?,?,?,1,'c0',?)",
                  (*w["setup"], json.dumps([70.0, -5.0, 20.0]), now()))
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=4, variance_threshold=2.0)


def test_the_new_fields_of_a_proposal_leave_its_chosen_sets_and_signature_as_they_were(store, w):
    seed_unstable_and_target(store, w)
    p = propose(store, w, seed=11, size=8)
    assert [(x["power"], x["frequency"], x["speed"], x["reason"], x["target_id"]) for x in p["parameters"]] == CHOSEN_BEFORE_REQ_022
    samples = list(model.knowledge_summaries(store, *w["setup"]).values())
    assert p["base_signature"] == ds.signature(su.setup_key(*w["setup"]), samples, ds.open_targets(store, *w["setup"]), 8, 2.0, p["domains"])
    assert "material_id" not in p["domains"]                                    # a proposal of every stock keeps the old state


def test_line_text_and_tonal_recipes_of_the_same_job_settings_never_count_for_a_fill_proposal(store, w):
    """A designer plate is fill cells (REQ-020): only fill recipes are its measured sets. Recipes of other tasks with the same
    pulse width, line interval and passes (a Cut line, an Image layer, a Scan recipe accepted as text), even unstable ones, leave
    the proposal of an all-fill database exactly as it was: the same stored proposal, sets and signature."""
    seed_unstable_and_target(store, w)
    before = propose(store, w, seed=11, size=8)
    for lab in ((20, 0, 0), (90, 0, 0)):
        obs.add(store, w, lab, power=45, frequency=700, speed=3500, layer_type="Cut")
        obs.add(store, w, lab, power=55, frequency=900, speed=1200, layer_type="Image")
        obs.add(store, w, lab, power=25, frequency=300, speed=6000, layer_type="Scan", task_kind="text")
    assert len(model.knowledge_summaries(store, *w["setup"])) == 8

    after = propose(store, w, seed=11, size=8)

    assert after["id"] == before["id"] and after["base_signature"] == before["base_signature"]
    assert [(x["power"], x["frequency"], x["speed"], x["reason"], x["target_id"]) for x in after["parameters"]] == CHOSEN_BEFORE_REQ_022
    assert after["model"]["measured_sets"] == 5 and after["stock"]["measured"][0]["sets"] == 5
    with pytest.raises(ds.DesignerError, match="filled region"):
        ds.propose_repeats(store, *w["setup"], [k for k, s in model.knowledge_summaries(store, *w["setup"]).items()
                                                 if s["task"]["kind"] != "fill"])


def test_a_proposal_states_its_question_its_value_and_a_reason_for_every_set(store, w):
    seed_unstable_and_target(store, w)
    p = propose(store, w, seed=11, size=8)
    assert p["questions"] == ["Which settings reproduce target colour 1 (L 70.0, a -5.0, b 20.0)?",
                              "Do repeat engravings of the unstable sets (1) agree within the variance threshold 2?",
                              "What colours do the settings give where the model is least certain (2 sets)?",
                              "What colours do settings far from every measured set give (4 sets)?"]
    assert len(p["worth"]) == 4 and p["worth"][0].startswith("a measured cell next to a target colour")
    why = {x["reason"]: x["rationale"] for x in p["parameters"]}
    assert why["target"] == "aimed at target colour 1: the model predicts 1.9 ΔE from it at these settings"
    assert why["instability"] == "re-measures settings whose repeat engravings vary by 450.00 ΔE², above the saved variance threshold 2"
    assert why["uncertainty"].startswith("the model is least certain here") and why["gap"].startswith("far from what is measured: ")
    assert p["task"] == "fill" and all(x["task"] == "fill" for x in p["parameters"])
    assert p["setup"] == {"device_id": w["device"]["id"], "device": w["device"]["title"], "lens_id": w["lens"]["id"],
                          "lens": {"id": w["lens"]["id"], "name": "F-Theta 174", "focal_length_mm": 174.0}}
    assert p["stock"]["material_id"] is None and p["stock"]["measured"][0]["sets"] == 5      # every stock measured with these settings


def test_a_proposal_of_one_stock_models_only_its_measurements(store, w):
    seed_measurements(store, w)
    titanium = su.save_material(store, "Grade 5 sheet", grade="Grade 5")
    obs.add(store, w, (40, 0, 0), power=30, frequency=200, speed=1000, material_id=titanium["id"])
    every = propose(store, w, seed=5)
    one_stock = propose(store, w, seed=5, material_id=titanium["id"])
    assert every["model"]["measured_sets"] == 5 and one_stock["model"]["measured_sets"] == 1 and one_stock["id"] != every["id"]
    assert one_stock["stock"]["material"]["name"] == "Grade 5 sheet" and one_stock["domains"]["material_id"] == titanium["id"]
    assert propose(store, w, seed=5, material_id=titanium["id"])["id"] == one_stock["id"]
    with pytest.raises(KeyError):
        propose(store, w, material_id=999)


def test_cleaning_is_the_first_lightburn_operation_of_a_plate_made_from_a_proposal(store, w):
    """REQ-022 AC5: the configured cleaning pass comes before the measurement geometry."""
    import xml.etree.ElementTree as ET
    seed_measurements(store, w)
    p = propose(store, w, size=4)
    for made in ds.create_plates(store, p["id"], 5, 4, 1):
        root = ET.fromstring(pl.export_lbrn2(pl.get_plan(store, made["plan_id"])))
        settings = root.findall("CutSetting")
        first = settings[0]
        assert first.find("index").get("Value") == "0" and first.find("name").get("Value").startswith("CLEAN-CROSSHATCH")
        assert min(int(s.find("priority").get("Value")) for s in settings) == int(first.find("priority").get("Value")) == 0
        assert root.findall("Shape")[0].get("CutIndex") == "0"                # the first shape engraved is the cleaning area
        assert all(s.find("index").get("Value") != "0" for s in settings[1:])


def test_a_proposal_is_accepted_with_its_plates_or_rejected_and_every_change_is_kept(store, w):
    seed_measurements(store, w)
    a = propose(store, w, seed=1)
    assert a["status"] == "proposed" and a["status_history"] == [] and a["origins"] == []
    rejected = ds.reject(store, a["id"], "  already tried on another sheet ")
    assert rejected["status"] == "rejected"
    assert [(e["from_status"], e["to_status"], e["reason"], e["note"]) for e in rejected["status_history"]] == \
        [("proposed", "rejected", "rejected by the operator", "already tried on another sheet")]
    with pytest.raises(ds.DesignerError, match="rejected"):
        ds.create_plates(store, a["id"], 5, 4, 1)
    with pytest.raises(ds.DesignerError, match="only a proposed experiment"):
        ds.reject(store, a["id"])
    b = propose(store, w, seed=2)
    ds.create_plates(store, b["id"], 5, 4, 1)
    accepted = ds.get_proposal(store, b["id"])
    assert accepted["status"] == "accepted" and [(e["from_status"], e["to_status"]) for e in accepted["status_history"]] == [("proposed", "accepted")]
    assert ds.reconcile_status(store, b["id"])["status"] == "accepted"          # no photograph yet
    with pytest.raises(ds.DesignerError, match="only a proposed experiment"):
        ds.reject(store, b["id"])


def test_a_proposal_whose_plates_were_made_before_statuses_existed_is_accepted(store, w):
    seed_measurements(store, w)
    p = propose(store, w, size=3)
    ds.create_plates(store, p["id"], 5, 4, 1)
    store.execute("DELETE FROM proposal_event")                                # as an older version left it
    assert ds.get_proposal(store, p["id"])["status"] == "accepted"


class FakeResponses:
    def __init__(self, text):
        self.text, self.calls = text, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.text, Exception):
            raise self.text
        return type("Response", (), {"output_text": self.text})()


class FakeClient:
    """Stands in for the OpenAI client: the real API is never called by the tests."""
    def __init__(self, text="Плата проверяет пробелы. Гипотеза: при росте мощности плёнка толще."):
        self.responses = FakeResponses(text)


def test_the_language_model_explains_a_proposal_without_changing_its_settings_or_data(store, w):
    from titanium_platform import research
    seed_unstable_and_target(store, w)
    p = propose(store, w, seed=11, size=8)
    stored = store.one("SELECT data_json FROM proposal WHERE id=?", (p["id"],))["data_json"]
    observations = [tuple(r) for r in store.query("SELECT * FROM observation ORDER BY id")]
    client = FakeClient()

    explained = ds.explain(store, p["id"], research.proposal_explainer(client))

    assert explained["explanation"] == "Плата проверяет пробелы. Гипотеза: при росте мощности плёнка толще."
    assert store.one("SELECT data_json FROM proposal WHERE id=?", (p["id"],))["data_json"] == stored          # byte-identical
    assert explained["parameters"] == p["parameters"] and observations == [tuple(r) for r in store.query("SELECT * FROM observation ORDER BY id")]
    call = client.responses.calls[0]
    brief = json.loads(call["input"][0]["content"])
    assert call["model"] == research.DEFAULT_MODEL and brief["questions"] == p["questions"]
    assert [x["rationale"] for x in brief["parameters"]] == [x["rationale"] for x in p["parameters"]]
    with pytest.raises(ds.DesignerError, match="did not answer"):
        ds.explain(store, p["id"], research.proposal_explainer(FakeClient(RuntimeError("down"))))
    assert ds.get_proposal(store, p["id"])["explanation"] == explained["explanation"]


def test_without_an_ai_key_the_explanation_is_refused_and_the_proposal_is_fully_usable(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from titanium_platform import research
    from titanium_platform.api.app import create_app
    monkeypatch.setattr(research, "_api_key", lambda: None)
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        store = app.state.store
        w = obs.setup(store)
        pl.save_marker_layer_settings(store, 20, 60, 300)
        seed_measurements(store, w)
        p = client.post("/api/designer/propose", json={"device_id": w["device"]["id"], "lens_id": w["lens"]["id"], **GROUP}).json()
        assert research.proposal_explainer() is None
        refused = client.post(f"/api/designer/proposals/{p['id']}/explanation")
        assert refused.status_code == 422 and refused.json()["error"].startswith("no AI key is configured")
        detail = client.get(f"/api/designer/proposals/{p['id']}").json()
        assert detail["explanation_available"] is False and detail["explanation"] is None
        accepted = client.post(f"/api/designer/proposals/{p['id']}/accept", json={"cell_width": 5, "cell_height": 4, "gap": 1})
        assert accepted.status_code == 201 and accepted.json()["proposal"]["status"] == "accepted"


def test_with_a_key_the_explanation_uses_the_researchers_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from titanium_platform import research
    from titanium_platform.api.app import create_app
    fake = FakeClient("Пояснение")
    monkeypatch.setattr(research, "_api_key", lambda: "test-key")
    monkeypatch.setattr(research, "openai_client", lambda: fake)
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        store = app.state.store
        w = obs.setup(store)
        seed_measurements(store, w)
        p = client.post("/api/designer/propose", json={"device_id": w["device"]["id"], "lens_id": w["lens"]["id"], **GROUP}).json()
        assert client.get(f"/api/designer/proposals/{p['id']}").json()["explanation_available"] is True
        explained = client.post(f"/api/designer/proposals/{p['id']}/explanation").json()
    assert explained["explanation"] == "Пояснение" and explained["parameters"] == p["parameters"] and len(fake.responses.calls) == 1


def test_an_accepted_proposal_links_to_its_plate_the_photograph_of_it_and_the_measured_result(tmp_path):
    """REQ-022 AC5: accept -> plate -> photographed pair -> result, with the target check, and the proposal becomes done."""
    import cv2
    import synth
    from fastapi.testclient import TestClient
    from titanium_platform import ingest as ig
    from titanium_platform.api.app import create_app
    app = create_app(tmp_path / "data")
    store = app.state.store
    store.set_setting("allow_non_raw_photos", True)                    # tests use PNG renders; real use requires RAW
    with TestClient(app) as client:
        w = obs.setup(store)
        pl.save_marker_layer_settings(store, 20, 60, 300)
        su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=6.0, variance_threshold=5.0)
        seed_measurements(store, w)
        store.execute("INSERT INTO target_color(device_id,lens_id,lab_json,source_plan_id,source_color_key,created_at) VALUES (?,?,?,1,'c0',?)",
                      (*w["setup"], json.dumps([80.0, -10.0, 30.0]), now()))
        p = propose(store, w, size=1)                                       # one set, for the target: one plate
        made = client.post(f"/api/designer/proposals/{p['id']}/accept", json={"cell_width": 5, "cell_height": 4, "gap": 1}).json()
        assert made["proposal"]["status"] == "accepted" and len(made["plates"]) == 1
        plan = pl.get_plan(store, made["plates"][0]["plan_id"])
        cells = json.loads(store.one("SELECT cells_json FROM plate WHERE id=?", (plan["plate_id"],))["cells_json"])
        colours = {c["id"]: tuple(int(v) for v in color.lab_to_srgb8((80.0, -10.0, 33.0))) for c in cells}
        titanium = su.save_material(store, "Grade 2 sheet", grade="Grade 2")
        pid = ig.create_pair(store, device_id=w["setup"][0], lens_id=w["setup"][1], stand_id=w["stand"]["id"], lightburn_name="proposal.lbrn2",
                             lightburn_bytes=pl.export_lbrn2(plan), photo_name="proposal.png", plan_id=plan["id"], context={"material_id": titanium["id"]},
                             photo_bytes=cv2.imencode(".png", synth.plate_photo(plan, colours))[1].tobytes())
        assert ig.check_pair(store, pid)["problems"] == []
        ig.review_masks(store, pid)
        before = client.get(f"/api/designer/proposals/{p['id']}").json()
        assert before["plates"][0]["pairs"][0]["id"] == pid and before["results"][0]["measured"] == []      # photographed, not accepted

        assert client.post(f"/api/pairs/{pid}/accept").status_code == 200

        after = client.get(f"/api/designer/proposals/{p['id']}").json()
        report = client.get(f"/api/pairs/{pid}/report").json()                # the photograph links back to the proposal
        experiment = client.get(f"/api/experiments/plan-{plan['id']}").json()
        assert client.delete(f"/api/pairs/{pid}").status_code == 204          # its only photograph leaves active use ...
        reopened = client.get(f"/api/designer/proposals/{p['id']}").json()
    assert reopened["status"] == "accepted" and reopened["status_history"][-1]["reason"] == "an accepted photograph of its plates left active use"
    assert reopened["results"][0]["measured"] == []                            # ... and its result with it
    assert report["proposal"] == {"id": p["id"], "device_id": w["device"]["id"], "lens_id": w["lens"]["id"], "status": "done"}
    assert experiment["plate"]["proposal"]["id"] == p["id"]
    assert after["status"] == "done" and [e["to_status"] for e in after["status_history"]] == ["accepted", "done"]
    assert after["plates"][0]["pairs"] == [after["plates"][0]["pairs"][0]] and after["plates"][0]["pairs"][0]["status"] == "Accepted"
    result = after["results"][0]
    assert result["reason"] == "target" and result["plate_id"] == plan["plate_id"] and len(result["measured"]) == 1
    measured = result["measured"][0]
    assert measured["pair_id"] == pid and measured["comparable"] and color.delta_e(measured["lab"], (80.0, -10.0, 33.0)) < 2.5
    assert measured["target_check"]["target_id"] == 1 and measured["target_check"]["within_tolerance"] is True
