import json

import cv2
import numpy as np
import pytest

import obs
from titanium_platform import color, conversion as cv, engraving_time, knowledge as kn, lightburn as lb, plans as pl, setup as su

# Two measured colours, each from two engravings 2 apart in L: expected error = sqrt(variance) = sqrt(2) ~ 1.414
RED_LAB = (45.0, 60.0, 40.0)
BLUE_LAB = (35.0, 20.0, -50.0)


def png(rgb_blocks, size=(60, 120)):
    """An image of vertical colour stripes (RGB tuples)."""
    h, w = size
    img = np.zeros((h, w, 3), np.uint8)
    step = w // len(rgb_blocks)
    for i, rgb in enumerate(rgb_blocks):
        img[:, i * step:(i + 1) * step if i < len(rgb_blocks) - 1 else w] = rgb[::-1]
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture
def w(store):
    w = obs.setup(store)
    setup = w["setup"]
    su.save_rules(store, *setup, repeat_threshold=2, delta_tolerance=6.0, variance_threshold=5.0)
    su.save_rules(store, *setup, criteria_agreed=True)
    for power, base in ((10, RED_LAB), (30, BLUE_LAB)):
        for dl in (-1.0, 1.0):
            obs.add(store, w, (base[0] + dl, base[1], base[2]), power=power)
    kn.refresh(store, *setup)
    w["ids"] = {k["parameters"]["power"]: k["id"] for k in kn.list_for_setup(store, *setup)}
    return w


def rgb_of(lab):
    return tuple(int(v) for v in color.lab_to_srgb8(lab))


def test_both_colors_become_validated_with_all_three_estimates(store, w):
    assert {k["stage"] for k in kn.list_for_setup(store, *w["setup"])} == {"validated"}
    palette = cv.eligible_palette(store, *w["setup"])
    assert len(palette) == 2 and all(e["confidence"] and e["expected_delta_e"] > 0 and e["stability"]["assessed"] for e in palette)


def test_matching_within_the_threshold_shows_distance_and_error(store, w):
    pid = cv.start_discrete(store, *w["setup"], png([rgb_of(RED_LAB), rgb_of(BLUE_LAB)]), 40, "A", threshold=8.0)
    plan = pl.get_plan(store, pid)
    assert plan["status"] == cv.ST_DRAFT and plan["threshold"] == 8.0
    assert [m["status"] for m in plan["matches"]] == ["matched", "matched"]
    m = plan["matches"][0]
    assert m["knowledge_id"] == w["ids"][10] and m["distance"] < 3
    assert m["match_error"] == pytest.approx(m["distance"] + 2 ** 0.5, abs=1e-6)  # DEC-030: distance + entry's expected error


def test_each_match_carries_its_titanium_colour_with_confidence_expected_error_and_stability(store, w):
    """REQ-002, REQ-004 AC3: the screen shows these per match from the match itself, also for the nearest colour of an
    unreachable one; DEC-030: the match error is the distance plus that entry's own expected error."""
    far = (90.0, -60.0, 70.0)
    pid = cv.start_discrete(store, *w["setup"], png([rgb_of(RED_LAB), rgb_of(far)]), 40, "A", threshold=8.0)
    palette = {e["id"]: e for e in cv.eligible_palette(store, *w["setup"])}
    for m in pl.get_plan(store, pid)["matches"]:
        entry = palette[m["knowledge_id"] or m["candidate_id"]]
        assert m["titanium"] == {"lab": entry["lab"], "confidence": entry["confidence"], "expected_delta_e": entry["expected_delta_e"],
                                 "stability": entry["stability"]}
        assert m["match_error"] == pytest.approx(m["distance"] + m["titanium"]["expected_delta_e"])
    cv.update_discrete(store, pid, exclusions=[pl.get_plan(store, pid)["matches"][0]["source_key"]])
    excluded = pl.get_plan(store, pid)["matches"][0]
    assert excluded["status"] == "excluded" and excluded["titanium"] is None


def fast_red(store, w):
    """A third validated colour 2 L from the red, engraved four times faster (speed 3600 instead of 900)."""
    for dl in (-1.0, 1.0):
        obs.add(store, w, (RED_LAB[0] + 2 + dl, RED_LAB[1], RED_LAB[2]), power=12, speed=3600)
    kn.refresh(store, *w["setup"])
    return next(k["id"] for k in kn.list_for_setup(store, *w["setup"]) if k["parameters"]["power"] == 12)


def test_among_colours_within_the_threshold_the_fastest_recipe_is_chosen_and_said_so(store, w):
    fast = fast_red(store, w)
    palette = {e["id"]: e for e in cv.eligible_palette(store, *w["setup"])}
    assert palette[fast]["time_s_per_cm2"] < palette[w["ids"][10]]["time_s_per_cm2"]
    assert palette[fast]["time_s_per_cm2"] == pytest.approx(engraving_time.per_area(palette[fast]["parameters"])["s_per_cm2"])
    pid = cv.start_discrete(store, *w["setup"], png([rgb_of(RED_LAB)]), 40, "A", threshold=8.0)
    (m,) = pl.get_plan(store, pid)["matches"]
    assert (m["status"], m["knowledge_id"], m["how"]) == ("matched", fast, "fastest_within_threshold")        # DEC-075, not the nearest
    assert m["time_s_per_cm2"] == palette[fast]["time_s_per_cm2"] and m["distance"] > color.delta_e(palette[w["ids"][10]]["lab"], m["source_lab"])
    # with a threshold only the nearer, slower red meets, that one is taken (DEC-030 still decides what is within)
    tight = cv.start_discrete(store, *w["setup"], png([rgb_of(RED_LAB)]), 40, "B", threshold=m["distance"] + palette[fast]["expected_delta_e"] - 0.01)
    assert pl.get_plan(store, tight)["matches"][0]["knowledge_id"] == w["ids"][10]


def test_a_time_limit_per_square_centimetre_leaves_slower_recipes_out_of_the_automatic_matching(store, w):
    fast = fast_red(store, w)
    palette = {e["id"]: e for e in cv.eligible_palette(store, *w["setup"])}
    limit = (palette[fast]["time_s_per_cm2"] + palette[w["ids"][10]]["time_s_per_cm2"]) / 2
    pid = cv.start_discrete(store, *w["setup"], png([rgb_of(RED_LAB), rgb_of(BLUE_LAB)]), 40, "A", threshold=8.0, max_time=limit)
    plan = pl.get_plan(store, pid)
    assert plan["max_time"] == limit
    by_status = {m["status"]: m for m in plan["matches"]}
    assert by_status["matched"]["knowledge_id"] == fast and by_status["unreachable"]["candidate_id"] == fast   # the slow blue is left out
    cv.update_discrete(store, pid, threshold=8.0)                                 # left out: the plan keeps its limit
    assert pl.get_plan(store, pid)["max_time"] == limit
    cv.update_discrete(store, pid, max_time=None)                                 # None removes it
    assert {m["status"] for m in pl.get_plan(store, pid)["matches"]} == {"matched"}
    with pytest.raises(su.ValidationError, match="positive number of seconds"):
        cv.update_discrete(store, pid, max_time=0)


def test_the_api_takes_and_keeps_the_time_limit_of_a_discrete_plan(tmp_path):
    from fastapi.testclient import TestClient
    from titanium_platform.api.app import create_app
    app = create_app(tmp_path / "data")
    store = app.state.store
    w = obs.setup(store)
    for power, base in ((10, RED_LAB), (30, BLUE_LAB)):
        for dl in (-1.0, 1.0):
            obs.add(store, w, (base[0] + dl, base[1], base[2]), power=power)
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=6.0, variance_threshold=5.0)
    su.save_rules(store, *w["setup"], criteria_agreed=True)
    kn.refresh(store, *w["setup"])
    with TestClient(app) as c:
        r = c.post("/api/discrete", data={"device_id": w["setup"][0], "lens_id": w["setup"][1], "name": "A", "width_mm": 40, "threshold": 8,
                                          "max_time": 3}, files={"image": ("a.png", png([rgb_of(RED_LAB)]), "image/png")})
        plan = r.json()
        assert r.status_code == 201 and plan["max_time"] == 3 and plan["matches"][0]["status"] == "unreachable"   # 900 mm/s is slower
        assert c.get(f"/api/discrete/{plan['id']}/palette").json()[0]["time_s_per_cm2"] > 3
        kept = c.patch(f"/api/discrete/{plan['id']}", json={"threshold": 8}).json()
        assert kept["max_time"] == 3
        cleared = c.patch(f"/api/discrete/{plan['id']}", json={"max_time": None}).json()
        assert cleared["max_time"] is None and cleared["matches"][0]["status"] == "matched" and cleared["matches"][0]["time_s_per_cm2"] > 3
    store.close()


def test_a_color_beyond_the_threshold_is_unreachable_and_becomes_a_designer_target(store, w):
    far = (90.0, -60.0, 70.0)
    pid = cv.start_discrete(store, *w["setup"], png([rgb_of(RED_LAB), rgb_of(far)]), 40, "A", threshold=8.0)
    plan = pl.get_plan(store, pid)
    # source colors are ordered by lightness, so look the unreachable one up by status, not by stripe position
    assert sorted(m["status"] for m in plan["matches"]) == ["matched", "unreachable"]
    unreachable = next(m for m in plan["matches"] if m["status"] == "unreachable")
    assert color.delta_e(unreachable["source_lab"], far) < 3  # it really is the far color
    targets = store.query("SELECT * FROM target_color WHERE source_plan_id=?", (pid,))
    assert len(targets) == 1 and json.loads(targets[0]["lab_json"]) == pytest.approx(unreachable["source_lab"])
    cv.update_discrete(store, pid)  # re-matching must not duplicate the target
    assert store.one("SELECT COUNT(*) AS n FROM target_color")["n"] == 1
    with pytest.raises(cv.ConversionError, match="unreachable"):
        cv.finalize_discrete(store, pid)


def test_the_plan_can_be_finalised_after_replacing_or_excluding_each_unreachable_color(store, w):
    far = (90.0, -60.0, 70.0)
    pid = cv.start_discrete(store, *w["setup"], png([rgb_of(RED_LAB), rgb_of(far)]), 40, "A", threshold=8.0)
    unreachable = next(m["source_key"] for m in pl.get_plan(store, pid)["matches"] if m["status"] == "unreachable")
    cv.update_discrete(store, pid, replacements={unreachable: w["ids"][30]})
    assert {m["status"] for m in pl.get_plan(store, pid)["matches"]} == {"matched", "replaced"}
    plan = cv.finalize_discrete(store, pid)
    assert plan["status"] == cv.ST_READY and len(plan["layers"]) == 2
    cv.update_discrete(store, pid, replacements={}, exclusions=[unreachable])
    assert pl.get_plan(store, pid)["status"] == cv.ST_DRAFT  # any change requires finalising again
    assert len(cv.finalize_discrete(store, pid)["layers"]) == 1


def test_excluding_every_color_leaves_nothing_to_finalise(store, w):
    pid = cv.start_discrete(store, *w["setup"], png([rgb_of(RED_LAB)]), 40, "A", threshold=8.0)
    cv.update_discrete(store, pid, exclusions=["c0"])
    with pytest.raises(cv.ConversionError, match="nothing to engrave"):
        cv.finalize_discrete(store, pid)


def test_one_layer_per_distinct_titanium_color_with_parameters_and_estimates_exported(store, w):
    # two source shades that both match the red entry share ONE layer
    pid = cv.start_discrete(store, *w["setup"],
                            png([rgb_of((44, 58, 38)), rgb_of((47, 62, 42)), rgb_of(BLUE_LAB)], size=(60, 90)), 30, "A", threshold=12.0, max_colors=3)
    plan = cv.finalize_discrete(store, pid)
    assert len(plan["layers"]) == 2
    red = next(l for l in plan["layers"] if l["parameters"]["power"] == 10)
    assert len(red["source_color_keys"]) == 2
    assert set(red["prediction"]) == {"lab", "confidence", "expected_delta_e", "stability"} and red["stage"] == "validated"
    project = lb.parse_bytes(pl.export_lbrn2(plan))
    assert {(l.power, l.frequency_khz, l.speed) for l in project.layers} == {(10, 40, 900), (30, 40, 900)}
    area = sum(r.width * r.height for l in project.layers for r in l.regions)
    assert area == pytest.approx(plan["size_mm"]["width"] * plan["size_mm"]["height"], rel=1e-6)  # the layers tile the whole image


def test_plan_generation_leaves_stage_and_questioned_flag_unchanged(store, w):
    before = [(k["id"], k["stage"], k["questioned"], len(k["history"])) for k in kn.list_for_setup(store, *w["setup"])]
    pid = cv.start_discrete(store, *w["setup"], png([rgb_of(RED_LAB)]), 40, "A", threshold=8.0)
    cv.finalize_discrete(store, pid)
    assert before == [(k["id"], k["stage"], k["questioned"], len(k["history"])) for k in kn.list_for_setup(store, *w["setup"])]


def questioned_world(store, w):
    kid = w["ids"][10]
    kn.approve_for_production(store, kid, True)
    obs.add(store, w, (80, 60, 40), power=10)   # a far-off later engraving: the production entry is questioned
    kn.refresh(store, *w["setup"])
    assert kn.get(store, kid)["questioned"]
    return kid


def test_questioned_entries_are_excluded_by_default_and_allowed_per_plan(store, w):
    kid = questioned_world(store, w)
    pid = cv.start_discrete(store, *w["setup"], png([rgb_of(RED_LAB)]), 40, "A", threshold=60.0)
    assert all(e["id"] != kid for e in cv.eligible_palette(store, *w["setup"]))
    assert pl.get_plan(store, pid)["matches"][0]["knowledge_id"] != kid
    assert kid in pl.get_plan(store, pid)["questioned_available"]
    cv.update_discrete(store, pid, allowed_questioned=[kid])
    plan = pl.get_plan(store, pid)
    assert plan["matches"][0]["knowledge_id"] == kid and plan["allowed_questioned"] == [kid]
    other = cv.start_discrete(store, *w["setup"], png([rgb_of(RED_LAB)]), 40, "B", threshold=60.0)
    assert pl.get_plan(store, other)["allowed_questioned"] == []  # the allowance does not carry over
    assert kn.get(store, kid)["questioned"] and kn.get(store, kid)["stage"] == "production"


def test_threshold_must_be_explicit_and_valid(store, w):
    su.save_rules(store, *w["setup"])  # keep saved rules
    with pytest.raises(cv.ConversionError, match="non-negative"):
        cv.start_discrete(store, *w["setup"], png([rgb_of(RED_LAB)]), 40, "A", threshold=-1)
    pid = cv.start_discrete(store, *w["setup"], png([rgb_of(RED_LAB)]), 40, "A")  # falls back to the saved tolerance 6.0
    assert pl.get_plan(store, pid)["threshold"] == 6.0


def test_without_a_saved_tolerance_a_threshold_is_required(store):
    w = obs.setup(store)
    with pytest.raises(cv.ConversionError, match="set the delta E threshold"):
        cv.start_discrete(store, *w["setup"], png([(200, 20, 20)]), 40, "A")


def test_no_eligible_palette_makes_every_color_unreachable(store):
    w = obs.setup(store)
    pid = cv.start_discrete(store, *w["setup"], png([(200, 20, 20)]), 40, "A", threshold=10)
    assert [m["status"] for m in pl.get_plan(store, pid)["matches"]] == ["unreachable"]


@pytest.mark.parametrize("kw,msg", [(dict(width_mm=0), "positive"), (dict(name=" "), "name"), (dict(image_bytes=b"nope"), "could not be read")])
def test_bad_inputs(store, w, kw, msg):
    args = dict(device_id=w["setup"][0], lens_id=w["setup"][1], image_bytes=png([rgb_of(RED_LAB)]), width_mm=40, name="A", threshold=8.0)
    args.update(kw)
    with pytest.raises(cv.ConversionError, match=msg):
        cv.start_discrete(store, **args)


def test_mask_to_rects_covers_exactly_the_mask():
    m = np.zeros((6, 8), bool)
    m[1:4, 1:5] = True
    m[4:6, 2:3] = True
    m[0, 6:8] = True
    rects = cv.mask_to_rects(m, 2.0)
    rebuilt = np.zeros_like(m)
    for r in rects:
        x0, y0, x1, y1 = (int(round(v / 2)) for v in (r["x"], r["y"], r["x"] + r["width"], r["y"] + r["height"]))
        assert not rebuilt[y0:y1, x0:x1].any()  # no overlaps
        rebuilt[y0:y1, x0:x1] = True
    assert (rebuilt == m).all()
