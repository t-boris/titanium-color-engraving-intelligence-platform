"""The prediction against the result (DEC-117): an accepted photo engraving beside what its grey scale predicted for it before it, from
the engravings known earlier at its own row length, and the facts the prediction rested on. The three photographs of the operator's
mode 150 mm/s · 60 kHz · 350 ns stand behind the numbers: grey ramps 38.4 mm long on the 3 mm plate after cleaning, a 100 mm portrait on
the 2 mm plate without cleaning, a 150 mm portrait on the 3 mm plate after cleaning, its clean titanium 12 L* lighter on its photograph."""
import json

import pytest
from fastapi.testclient import TestClient

from test_prediction_store import observe, pair, tonal_check
from titanium_platform import colormap, devices, lenses, prediction_review as pr, row_length, setup as su
from titanium_platform.api.app import create_app

RAMPS = [(1.0, [80.0, 0.0, 6.0]), (0.5, [50.0, 10.0, 20.0]), (0.0, [40.0, 0.0, -20.0])]          # 38.4 mm, cleaned, 3 mm plate
PORTRAIT_100 = [(1.0, [76.0, 0.0, 8.0]), (0.5, [45.0, 12.0, 22.0]), (0.0, [35.0, 0.0, -15.0])]   # 100 mm, not cleaned, 2 mm plate
PORTRAIT_150 = [(1.0, [91.0, 0.0, 6.0]), (0.5, [80.0, 2.0, 40.0]), (0.0, [56.0, -5.0, -30.0])]  # 150 mm, cleaned, 3 mm plate


def world(store):
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    lens = lenses.create_lens(store, "F-Theta 174", 174, 170)
    big = su.save_material(store, "Big Plate 150", grade="Grade 5", thickness_mm=3.0)
    small = su.save_material(store, "Small Plate", grade="Grade 5", thickness_mm=2.0)
    return {"store": store, "laser": laser, "lens": lens, "titanium": big, "big": big, "small": small, "n": 0}


@pytest.fixture
def w(store, monkeypatch):
    rows: dict[str, float] = {}
    monkeypatch.setattr(row_length, "of_file", lambda path: {0: rows[path]} if path in rows else {})
    return {**world(store), "rows": rows}


def engraved(w, bins, *, row_mm, plate, cleans, accepted_at, chart=True, engraving=None, status="Accepted", witness=None) -> int:
    """An accepted photograph of one grayscale layer at MODE (Min 1 %, Max 30 %), its row length, plate, cleaning and acceptance time."""
    check = tonal_check(bins, chart=chart, power_range=(1.0, 30.0))
    check["composition"] = {"cleaning_layer": 1 if cleans else None}
    pid = pair(w, check=check, material=w[plate]["id"], engraving=engraving, status=status)
    path = f"/x/work-{pid}.lbrn2"
    w["rows"][path] = row_mm
    w["store"].execute("UPDATE pair SET lightburn_path=?, accepted_at=? WHERE id=?", (path, accepted_at, pid))
    if witness is not None:
        observe(w, pid, witness, 20.0, index=-1, chart=chart, role=colormap.WITNESS)
    return pid


def the_three(w):
    ramps = engraved(w, RAMPS, row_mm=38.4, plate="big", cleans=True, accepted_at="2026-10-22T01:12:00+00:00", witness=[79.0, 0.7, 5.4])
    p100 = engraved(w, PORTRAIT_100, row_mm=100.0, plate="small", cleans=False, accepted_at="2026-10-22T05:14:00+00:00")
    p150 = engraved(w, PORTRAIT_150, row_mm=150.0, plate="big", cleans=True, accepted_at="2026-10-22T11:10:00+00:00")
    return ramps, p100, p150


def cause(layer, code):
    return next(c for c in layer["causes"] if c["code"] == code)


def test_a_photograph_is_set_beside_what_the_engravings_before_it_predicted_at_its_own_size(w):
    _, p100, p150 = the_three(w)
    (layer,) = pr.review(w["store"], p150)["layers"]
    assert layer["reason"] is None and layer["row_mm"] == 150.0 and layer["engravings"] == 1      # the nearest size, 100 mm: one engraving
    assert [b["power"] for b in layer["bands"]] == [1.0, 15.5, 30.0]
    assert [b["predicted"] for b in layer["bands"]] == [lab for _, lab in PORTRAIT_100]            # the 100 mm portrait, not recomputed
    assert [b["lab"] for b in layer["bands"]] == [lab for _, lab in PORTRAIT_150]
    assert [b["de"] for b in layer["bands"]] == [15.1, 40.6, 26.3]
    assert (layer["compared"], layer["median_de"], layer["max_de"], layer["within"]) == (3, 26.3, 40.6, 0.0)
    assert (layer["median_dL"], layer["median_db"]) == (21.0, -2.0)                                 # lighter than predicted
    size = cause(layer, "size")
    assert (size["how"], size["measured_mm"], size["from_mm"], size["differs"]) == ("outside", [38.4, 100.0], [100.0], True)


def test_the_plate_its_thickness_and_the_cleaning_the_prediction_rested_on_are_named(w):
    _, p100, p150 = the_three(w)
    (layer,) = pr.review(w["store"], p150)["layers"]
    plate = cause(layer, "plate")
    assert plate["own"] == {"id": w["big"]["id"], "name": "Big Plate 150", "thickness_mm": 3.0}
    assert plate["used"] == [{"id": w["small"]["id"], "name": "Small Plate", "thickness_mm": 2.0}] and plate["differs"]
    cleaning = cause(layer, "cleaning")
    assert cleaning["own"] is True and [(c["pair_id"], c["cleans"]) for c in cleaning["used"]] == [(p100, False)] and cleaning["differs"]


def test_clean_titanium_on_the_same_plate_and_cleaning_tells_the_photographs_light_from_the_metal(w):
    ramps, p100, p150 = the_three(w)
    (layer,) = pr.review(w["store"], p150)["layers"]
    photo = cause(layer, "photo")
    assert (photo["own"]["L"], photo["own"]["how"]) == (91.0, "lightest")                          # the white of the picture, at Min
    assert [(r["pair_id"], r["L"], r["how"], r["same_surface"]) for r in photo["used"]] == [(p100, 76.0, "lightest", False)] and photo["dL_used"] == 15.0
    assert [(r["pair_id"], r["L"], r["how"]) for r in photo["same_surface"]] == [(ramps, 79.0, "witness")] and photo["dL_same"] == 12.0
    assert photo["differs"]


def test_the_first_engraving_of_a_mode_had_no_prediction_and_a_later_one_is_never_used_for_an_earlier(w):
    ramps, p100, _ = the_three(w)
    (first,) = pr.review(w["store"], ramps)["layers"]
    assert first["reason"] == "first" and first["compared"] == 0 and first["bands"] == []
    (second,) = pr.review(w["store"], p100)["layers"]                                              # from the ramps alone, not the 150 mm portrait
    assert second["engravings"] == 1 and cause(second, "size")["from_mm"] == [38.4] and cause(second, "size")["measured_mm"] == [38.4]
    assert cause(second, "photo")["same_surface"] == [] and cause(second, "photo")["dL_used"] == -3.0


def test_a_photograph_measured_again_keeps_the_place_of_its_engraving_among_the_others(w):
    engraved(w, RAMPS, row_mm=100.0, plate="big", cleans=True, accepted_at="2026-10-22T01:00:00+00:00", engraving="e-ramps", status="Deleted")
    portrait = engraved(w, PORTRAIT_100, row_mm=100.0, plate="big", cleans=True, accepted_at="2026-10-22T02:00:00+00:00")
    again = engraved(w, RAMPS, row_mm=100.0, plate="big", cleans=True, accepted_at="2026-10-22T03:00:00+00:00", engraving="e-ramps")
    (layer,) = pr.review(w["store"], portrait)["layers"]
    assert layer["engravings"] == 1 and cause(layer, "size")["how"] == "measured" and layer["bands"][0]["predicted"] == RAMPS[0][1]
    assert pr.review(w["store"], again)["layers"][0]["reason"] == "first"


def test_colours_measured_against_a_chart_are_not_compared_with_camera_relative_ones(w):
    engraved(w, RAMPS, row_mm=100.0, plate="big", cleans=True, accepted_at="2026-10-22T01:00:00+00:00")
    relative = engraved(w, PORTRAIT_100, row_mm=100.0, plate="big", cleans=True, accepted_at="2026-10-22T02:00:00+00:00", chart=False)
    (layer,) = pr.review(w["store"], relative)["layers"]
    assert layer["reason"] == "kind" and layer["compared"] == 0


def test_a_photograph_awaiting_acceptance_has_no_review(w):
    pid = engraved(w, RAMPS, row_mm=100.0, plate="big", cleans=True, accepted_at=None, status="Ready to accept")
    assert pr.review(w["store"], pid) == {"pair_id": pid, "photo": f"IMG_{w['n']}.DNG", "accepted": False, "tolerance_de": 5.0, "layers": []}


def test_every_review_together_is_the_measure_and_the_sizes_measured_beforehand_are_counted_apart(w):
    ramps, p100, p150 = the_three(w)
    again = engraved(w, PORTRAIT_150, row_mm=150.0, plate="big", cleans=True, accepted_at="2026-10-22T20:00:00+00:00")
    found = pr.summary(w["store"])
    assert [(r["pair_id"], r["compared"]) for r in found["layers"]] == [(p100, 3), (p150, 3), (again, 3)]
    assert found["all"]["engravings"] == 3 and found["all"]["tones"] == 9
    assert found["size_measured"] == {"layers": 1, "engravings": 1, "tones": 3, "median_de": 0.0, "within": 1.0}      # 150 mm measured by p150


def test_the_api_gives_the_review_of_a_photograph_and_of_every_photograph(tmp_path, monkeypatch):
    app = create_app(tmp_path / "data")
    rows: dict[str, float] = {}
    monkeypatch.setattr(row_length, "of_file", lambda path: {0: rows[path]} if path in rows else {})
    w = {**world(app.state.store), "rows": rows}
    _, _, p150 = the_three(w)
    with TestClient(app) as client:
        got = client.get(f"/api/pairs/{p150}/prediction-review")
        assert got.status_code == 200 and got.json()["layers"][0]["median_de"] == 26.3
        assert client.get("/api/prediction-reviews").json()["all"]["engravings"] == 2
        missing = client.get("/api/pairs/9999/prediction-review")
        assert missing.status_code == 404 and json.loads(missing.text)["error"]
    app.state.store.close()



def test_a_prediction_from_the_same_plate_and_cleaning_says_so_and_the_other_photographs_of_it_are_named_apart(w):
    ramps, _, p150 = the_three(w)
    again = engraved(w, PORTRAIT_150, row_mm=150.0, plate="big", cleans=True, accepted_at="2026-10-22T20:00:00+00:00")
    photo = cause(pr.review(w["store"], again)["layers"][0], "photo")
    assert [(r["pair_id"], r["same_surface"]) for r in photo["used"]] == [(p150, True)] and photo["dL_used"] == 0.0
    assert [r["pair_id"] for r in photo["same_surface"]] == [ramps] and photo["dL_same"] == 12.0      # p150 is not named twice
