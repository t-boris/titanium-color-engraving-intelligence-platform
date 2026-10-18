import pytest

import obs
from titanium_platform import knowledge as kn
from titanium_platform import setup as su


@pytest.fixture
def w(store):
    return obs.setup(store)


def agree(store, w, repeat=3, tol=4.0, var=2.0):
    setup = w["setup"]
    su.save_rules(store, *setup, repeat_threshold=repeat, delta_tolerance=tol, variance_threshold=var)
    su.save_rules(store, *setup, criteria_agreed=True)


def stage(store, w):
    return kn.list_for_setup(store, *w["setup"])[0]["stage"]


def test_nothing_passes_measured_until_the_criteria_are_agreed(store, w):
    setup = w["setup"]
    for lab in ((50, 0, 0), (50.2, 0, 0), (50.1, 0, 0)):
        obs.add(store, w, lab)
    kn.refresh(store, *setup)
    assert stage(store, w) == "measured"
    su.save_rules(store, *setup, repeat_threshold=2, delta_tolerance=4, variance_threshold=2)  # numbers alone do not agree
    kn.refresh(store, *setup)
    assert stage(store, w) == "measured"


def test_stages_follow_the_evidence_once_criteria_are_agreed(store, w):
    setup = w["setup"]
    agree(store, w, repeat=3)
    obs.add(store, w, (50, 0, 0))
    kn.refresh(store, *setup)
    assert stage(store, w) == "measured"
    obs.add(store, w, (50.5, 0, 0), engraving="e1", rephoto=True)  # same engraving again: candidate, not repeated
    kn.refresh(store, *setup)
    assert stage(store, w) == "candidate"
    obs.add(store, w, (50.2, 0, 0))
    kn.refresh(store, *setup)
    assert stage(store, w) == "repeated"  # 2 independent engravings < threshold 3
    obs.add(store, w, (50.1, 0, 0))
    kn.refresh(store, *setup)
    assert stage(store, w) == "validated"  # 3 independent engravings, variance and tolerance respected
    events = [e["to_stage"] for e in kn.list_for_setup(store, *setup)[0]["history"]]
    assert events == ["measured", "candidate", "repeated", "validated"]


def test_a_rephotograph_never_counts_toward_the_threshold(store, w):
    agree(store, w, repeat=2)
    obs.add(store, w, (50, 0, 0), engraving="A")
    obs.add(store, w, (50.1, 0, 0), engraving="A", rephoto=True)
    obs.add(store, w, (50.2, 0, 0), engraving="A", rephoto=True)
    kn.refresh(store, *w["setup"])
    assert stage(store, w) == "candidate"  # three photos of ONE engraving are one repetition, not three


def test_a_noisy_set_stops_at_repeated(store, w):
    agree(store, w, repeat=2, var=2.0)
    for lab in ((50, 0, 0), (60, 0, 0)):
        obs.add(store, w, lab)
    kn.refresh(store, *w["setup"])
    assert stage(store, w) == "repeated"


def test_the_threshold_below_two_is_treated_as_two(store, w):
    agree(store, w, repeat=1)
    obs.add(store, w, (50, 0, 0))
    kn.refresh(store, *w["setup"])
    assert stage(store, w) == "measured"  # one engraving can never validate


def validated(store, w):
    agree(store, w, repeat=2)
    obs.add(store, w, (50, 0, 0))
    obs.add(store, w, (50.2, 0, 0))
    kn.refresh(store, *w["setup"])
    return kn.list_for_setup(store, *w["setup"])[0]["id"]


def test_production_needs_explicit_confirmation_and_a_validated_entry(store, w):
    kid = validated(store, w)
    with pytest.raises(kn.KnowledgeError, match="explicit confirmation"):
        kn.approve_for_production(store, kid, confirm=False)
    assert kn.approve_for_production(store, kid, confirm=True)["stage"] == "production"
    with pytest.raises(kn.KnowledgeError, match="only a validated"):
        kn.approve_for_production(store, kid, confirm=True)


def test_automatic_refresh_never_lowers_or_changes_production(store, w):
    kid = validated(store, w)
    kn.approve_for_production(store, kid, True)
    su.save_rules(store, *w["setup"], criteria_agreed=False)
    kn.refresh(store, *w["setup"])
    assert kn.get(store, kid)["stage"] == "production"


def test_a_production_entry_that_degrades_is_questioned_keeps_its_stage_and_shows_evidence(store, w):
    kid = validated(store, w)
    kn.approve_for_production(store, kid, True)
    first = kn.get(store, kid)["summary"]["observation_ids"]
    new = obs.add(store, w, (58, 0, 0))  # a later engraving far from the earlier ones
    kn.refresh(store, *w["setup"])
    k = kn.get(store, kid)
    assert k["stage"] == "production" and k["questioned"]
    assert "variance" in k["doubt"]["reason"] and new in k["doubt"]["observation_ids"] and set(first) <= set(k["doubt"]["observation_ids"])
    before = len(k["history"])
    kn.refresh(store, *w["setup"])
    assert len(kn.get(store, kid)["history"]) == before  # idempotent: no duplicate flag events


def test_confirming_a_questioned_entry_clears_the_flag_and_records_it(store, w):
    kid = validated(store, w)
    kn.approve_for_production(store, kid, True)
    obs.add(store, w, (58, 0, 0))
    kn.refresh(store, *w["setup"])
    k = kn.confirm_questioned(store, kid)
    assert not k["questioned"] and k["stage"] == "production" and k["history"][-1]["type"] == "confirmed"
    assert k["history"][-1]["observation_ids"]
    with pytest.raises(kn.KnowledgeError, match="not questioned"):
        kn.confirm_questioned(store, kid)


def test_manual_demotion_is_explicit_recorded_and_only_from_production(store, w):
    kid = validated(store, w)
    with pytest.raises(kn.KnowledgeError, match="only a production"):
        kn.demote(store, kid, "repeated", "x", True)
    kn.approve_for_production(store, kid, True)
    with pytest.raises(kn.KnowledgeError, match="explicit confirmation"):
        kn.demote(store, kid, "repeated", "x", False)
    with pytest.raises(kn.KnowledgeError, match="lower stage"):
        kn.demote(store, kid, "production", "x", True)
    k = kn.demote(store, kid, "repeated", "new titanium batch", True)
    assert k["stage"] == "repeated" and k["history"][-1]["reason"] == "new titanium batch"


def test_rollback_adds_an_event_never_raises_and_guards_production(store, w):
    kid = validated(store, w)
    hist = kn.get(store, kid)["history"]
    promoted = next(e for e in hist if e["to_stage"] == "validated")
    k = kn.rollback(store, kid, promoted["id"])
    assert k["stage"] == promoted["from_stage"] and k["history"][-1]["type"] == "rollback" and len(k["history"]) == len(hist) + 1
    with pytest.raises(kn.KnowledgeError, match="would not lower"):
        kn.rollback(store, kid, promoted["id"])
    kid2_events = [e for e in kn.get(store, kid)["history"] if e["from_stage"] is None]
    with pytest.raises(kn.KnowledgeError, match="previous stage"):
        kn.rollback(store, kid, kid2_events[0]["id"])


def test_rolling_back_production_needs_confirmation(store, w):
    kid = validated(store, w)
    kn.approve_for_production(store, kid, True)
    approved = next(e for e in kn.get(store, kid)["history"] if e["type"] == "approved")
    with pytest.raises(kn.KnowledgeError, match="explicit confirmation"):
        kn.rollback(store, kid, approved["id"])
    assert kn.rollback(store, kid, approved["id"], confirm_production=True)["stage"] == "validated"


def test_an_unknown_lens_is_a_partition_of_its_own(store, w):
    """DEC-063: the same recipe on the same laser with the lens unknown never counts toward the known lens."""
    device_id, lens_id = w["setup"]
    for lens in (lens_id, None):
        su.save_rules(store, device_id, lens, repeat_threshold=2, delta_tolerance=4, variance_threshold=2)
        su.save_rules(store, device_id, lens, criteria_agreed=True)
    obs.add(store, w, (50, 0, 0))
    obs.add(store, w, (50.2, 0, 0), lens_id=None)     # together these two would be "repeated"
    kn.refresh(store, device_id, lens_id)
    kn.refresh(store, device_id, None)
    known, unknown = kn.list_for_setup(store, device_id, lens_id), kn.list_for_setup(store, device_id, None)
    assert [k["stage"] for k in known] == ["measured"] and [k["stage"] for k in unknown] == ["measured"]
    assert known[0]["parameters_key"] == unknown[0]["parameters_key"] and known[0]["id"] != unknown[0]["id"]
    assert known[0]["summary"]["observations"] == 1 and unknown[0]["summary"]["observations"] == 1
    assert (unknown[0]["device_id"], unknown[0]["lens_id"]) == (device_id, None)


def test_rules_belong_to_one_laser_and_lens(store, w):
    device_id, lens_id = w["setup"]
    su.save_rules(store, device_id, lens_id, delta_tolerance=4)
    assert su.get_rules(store, device_id, lens_id)["delta_tolerance"] == 4
    assert su.get_rules(store, device_id, None)["delta_tolerance"] is None
    assert store.get_setting(f"rules:laser:{device_id}/lens:{lens_id}")["delta_tolerance"] == 4
