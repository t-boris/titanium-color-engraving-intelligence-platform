"""The curve of a photo-engraving mode is collected from what was measured at that mode (REQ-030, DEC-057, DEC-062, DEC-063)."""
import json

import numpy as np
import pytest

from titanium_platform import color, colormap, devices, lenses, prediction as pr, prediction_store as ps, setup as su
from titanium_platform.db import now

MODE = {"speed": 128.0, "frequency": 60.0, "pulse_width": 300.0, "line_interval": 0.0169, "passes": 1, "global_passes": 1}
BINS = [(0.25, [10.0, 1.0, 1.0]), (0.5, [18.0, 0.5, 3.0]), (0.75, [26.0, 0.0, 5.0])]


@pytest.fixture
def w(store):
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    lens = lenses.create_lens(store, "F-Theta 174", 174, 170)
    titanium = su.save_material(store, "Grade 2 sheet", grade="Grade 2", batch="A")
    return {"store": store, "laser": laser, "lens": lens, "titanium": titanium, "n": 0}


def mode(w, **changes) -> ps.Mode:
    return ps.mode_of({**MODE, **changes}, w["laser"]["id"], w["lens"]["id"], w["titanium"]["id"])


def pair(w, *, check=None, status="Accepted", device=None, lens="same", material="same", engraving=None, plan_id=None) -> int:
    w["n"] += 1
    return w["store"].execute(
        "INSERT INTO pair(status,device_id,lens_id,material_id,plan_id,engraving_id,engraving_title,lightburn_name,lightburn_path,photo_name,"
        "photo_path,context_json,data_json,created_at,accepted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (status, device or w["laser"]["id"], w["lens"]["id"] if lens == "same" else lens, w["titanium"]["id"] if material == "same" else material,
         plan_id, engraving or f"e{w['n']}", f"work {w['n']}", "work.lbrn2", "/x/work.lbrn2", f"IMG_{w['n']}.DNG", "/y", "{}",
         json.dumps({"check": check} if check else {}), now(), now() if status == "Accepted" else None)).lastrowid


def observe(w, pair_id, lab, power, *, index=1, chart=False, role="test feature", layer_type="Scan", **settings) -> int:
    params = {"power": power, **MODE, **settings, "layer_type": layer_type}
    evidence = {"role": role, "layer_name": f"C{index:02d}", "color_measurement": {"mode": "reference_chart_corrected" if chart else "raw_camera_relative"}}
    row = w["store"].one("SELECT * FROM pair WHERE id=?", (pair_id,))
    return w["store"].execute(
        "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,"
        "model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pair_id, index, row["device_id"], row["lens_id"], row["engraving_id"], json.dumps(lab), json.dumps(params), "element anchors", "{}",
         int(chart), 1, "test", json.dumps(evidence), now())).lastrowid


def tonal_check(bins=BINS, *, chart=False, evidence="clear", power_range=(5.0, 16.0), adjustments=None, dither="grayscale", **settings):
    s = {**MODE, **settings}
    return {"color_measurement": {"mode": "reference_chart_corrected" if chart else "raw_camera_relative"},
            "alignment": {"valid": True, "method": "picture"},
            "layers": [{"index": 0, "name": "C00", "type": "Image", "measured_lab": [18.0, 0.5, 3.0], "power": power_range[1],
                        "frequency_khz": s["frequency"], "speed": s["speed"], "pulse_width": s["pulse_width"], "line_interval": s["line_interval"],
                        "passes": s["passes"], "global_passes": s["global_passes"], "image": {"dither": dither},
                        "tonal": {"evidence": evidence, "power_range": list(power_range), "adjustments": adjustments or {},
                                  "bins": [{"gray": g, "L": lab[0], "a": lab[1], "b": lab[2], "n": 500,
                                            "power_pct": power_range[0] + (power_range[1] - power_range[0]) * (1 - g)} for g, lab in bins]}}]}


def test_a_tonal_profile_gives_one_point_per_bin_at_the_power_its_grey_was_engraved_with(w):
    pid = pair(w, check=tonal_check())
    points = ps.collect(w["store"], mode(w))["points"]
    assert sorted(p.power for p in points) == pytest.approx([7.75, 10.5, 13.25])          # Min + (Max - Min)(1 - grey), DEC-057
    lightest = max(points, key=lambda p: p.source["gray"])
    assert lightest.lab == (26.0, 0.0, 5.0) and not lightest.referenced
    assert lightest.source["kind"] == "pair" and lightest.source["id"] == pid and lightest.source["how"] == "tonal profile"
    assert lightest.source["reference"] == ps.AS_SHOT and lightest.source["experiment"].startswith("eng-")


def test_the_grey_of_a_bin_goes_through_the_files_picture_adjustments_as_the_prediction_applies_them(w):
    pair(w, check=tonal_check(adjustments={"Gamma": 0.8}))
    powers = sorted(p.power for p in ps.collect(w["store"], mode(w))["points"])
    assert powers == pytest.approx(sorted(5.0 + 11.0 * (1 - g ** 0.8) for g, _ in BINS))


def test_flat_fills_at_exactly_the_mode_are_kept_beside_the_curve_and_every_other_layer_is_not(w):
    """DEC-100: a fill with the settings of a grayscale mode is a reference beside its curve, never a point of it."""
    pid = pair(w)
    observe(w, pid, [30.0, 2.0, 8.0], 6.0)
    observe(w, pid, [31.0, 2.0, 8.0], 6.0, speed=129.0)               # another speed: another mode
    observe(w, pid, [32.0, 2.0, 8.0], 6.0, global_passes=2)           # repeated globally: another mode
    observe(w, pid, [33.0, 2.0, 8.0], 6.0, layer_type="Image")        # the median of an image layer is not a colour at one power
    observe(w, pid, [70.0, 0.0, 2.0], 3.0, index=-1, role=colormap.WITNESS)
    observe(w, pid, [50.0, 0.0, 0.0], 20.0, index=0, role=colormap.SERVICE[0])
    found = ps.collect(w["store"], mode(w))
    (point,) = found["fills"]
    assert found["points"] == []
    assert point.power == 6.0 and point.source["how"] == "flat fill" and point.source["layer_name"] == "C01"
    with pytest.raises(pr.PredictionError, match="no colour has been measured at this mode"):
        ps.curve_for(w["store"], mode(w))                             # fills alone make no curve


def test_a_curve_with_fills_of_its_settings_names_them_and_leaves_them_out(w):
    pair(w, check=tonal_check(chart=True))
    fill = pair(w)
    observe(w, fill, [90.0, -8.0, 36.0], 10.5, chart=True)          # a fill far from the picture's colour at the same power
    curve, basis = ps.curve_for(w["store"], mode(w))
    assert len(curve.points) == 3 and all(src["how"] == "tonal profile" for row in curve.points for src in row["sources"])
    assert [p.power for p in basis["fills"]] == [10.5]
    assert any("1 flat fills with these settings are shown beside the curve and not used" in n for n in basis["notes"])


def test_another_laser_lens_or_titanium_is_another_partition(w):
    twin = devices.create_from_template(w["store"], "jpt-ydflp-e-60-m7-m-r")
    other_lens = lenses.create_lens(w["store"], "F-Theta 254", 254, 220)
    grade5 = su.save_material(w["store"], "Grade 5 sheet", grade="Grade 5", batch="A")      # another grade, the same name and batch
    unnamed = su.save_material(w["store"], "Offcut")                                         # no grade: only itself
    pair(w, check=tonal_check(), device=twin["id"])
    pair(w, check=tonal_check(), lens=other_lens["id"])
    pair(w, check=tonal_check(), lens=None)                            # an unknown lens is its own partition
    pair(w, check=tonal_check(), material=grade5["id"])
    pair(w, check=tonal_check(), material=unnamed["id"])
    assert ps.collect(w["store"], mode(w))["points"] == []
    with pytest.raises(pr.PredictionError, match="no colour has been measured at this mode"):
        ps.curve_for(w["store"], mode(w))


def test_every_plate_of_one_grade_is_one_titanium_whatever_its_name_size_thickness_or_batch(w):
    """DEC-110: the operator engraves the grey-scale plate on one plate and the work on another of the same grade."""
    small = su.save_material(w["store"], "Small Plate", grade=" grade  2 ", batch="B", thickness_mm=2.0)
    pair(w, check=tonal_check(), material=small["id"])
    on_small = ps.mode_of(MODE, w["laser"]["id"], w["lens"]["id"], small["id"])
    assert len(ps.collect(w["store"], mode(w))["points"]) == 3 == len(ps.collect(w["store"], on_small)["points"])
    assert {src["material_id"] for p in ps.collect(w["store"], mode(w))["points"] for src in [p.source]} == {small["id"]}
    (listed,) = ps.scale_modes(w["store"])                                           # one scale, named by the plate it was measured on
    assert listed.material_id == small["id"]
    (asked,) = ps.scale_modes(w["store"], material_id=w["titanium"]["id"])           # or by the titanium asked for
    assert asked.material_id == w["titanium"]["id"]
    pair(w, check=tonal_check(), material=w["titanium"]["id"])
    assert len(ps.scale_modes(w["store"])) == 1                                      # measured on both plates: still one scale
    (summary,) = ps.scales(w["store"])
    assert summary["titanium"]["records"] == sorted([w["titanium"]["id"], small["id"]])
    assert [m["name"] for m in summary["titanium"]["measured_on"]] == ["Grade 2 sheet", "Small Plate"] and summary["engravings"] == 2


def test_checks_awaiting_acceptance_and_deleted_pairs_never_feed_a_curve(w):
    pair(w, check=tonal_check(), status="Ready to accept")
    pair(w, check=tonal_check(), status="Deleted")
    assert ps.collect(w["store"], mode(w))["points"] == []


def test_a_weak_tonal_profile_and_another_dither_mode_are_not_used(w):
    pair(w, check=tonal_check(evidence="weak"))
    pair(w, check=tonal_check(dither="stucki"))
    found = ps.collect(w["store"], mode(w))
    assert found["points"] == [] and found["weak_profiles"] == 1


def test_referenced_points_are_preferred_and_the_camera_relative_ones_are_counted_left_out(w):
    pair(w, check=tonal_check())
    pair(w, check=tonal_check(bins=[(0.0, [40.0, 5.0, 20.0]), (1.0, [30.0, 6.0, 25.0])], power_range=(6.0, 12.0), chart=True))
    curve, basis = ps.curve_for(w["store"], mode(w))
    assert curve.referenced and curve.span == (6.0, 12.0) and curve.left_out == 3 and basis["reference"] == ps.CHART
    assert [s["reference"] for row in curve.points for s in row["sources"]] == [ps.CHART, ps.CHART]


def test_camera_relative_colours_are_put_against_the_clean_titanium_of_their_own_photograph(w):
    clean = [30.0, 0.0, 6.0]
    anchored = pair(w, check=tonal_check())
    observe(w, anchored, clean, 3.0, index=-1, role=colormap.WITNESS)
    pair(w, check=tonal_check(bins=[(0.5, [5.0, 0.0, 1.0])]))          # no clean titanium in this photograph
    curve, basis = ps.curve_for(w["store"], mode(w))
    assert basis["reference"] == ps.CLEAN and not curve.referenced and len(curve.points) == 3
    nominal = colormap.references(w["store"])["nominal"]
    middle = next(row for row in curve.points if row["power"] == pytest.approx(10.5))
    assert middle["lab"] == pytest.approx(color.against_clean([18.0, 0.5, 3.0], clean, nominal), abs=1e-6)
    assert any("1 camera-relative points without clean titanium" in n for n in basis["notes"])
    assert any("expressed against the clean titanium" in n for n in basis["notes"])


def test_colours_without_any_reference_are_used_as_photographed_and_say_so(w):
    pair(w, check=tonal_check())
    curve, basis = ps.curve_for(w["store"], mode(w))
    assert basis["reference"] == ps.AS_SHOT and not curve.referenced and curve.left_out == 0
    assert basis["notes"] == ["No photograph of this mode shows clean titanium: the colours are as photographed, at that photograph's exposure."]


@pytest.mark.parametrize("matrix, corner", [
    ((0.4, 0, 0, 0.4), (-1, 0)),          # LightBurn's y points up: row 0 of the stored picture is the bottom of the work
    ((0.4, 0, 0, -0.4), (0, 0)),          # mirrored vertically in the file: row 0 is on top
    ((-0.4, 0, 0, 0.4), (-1, -1)),        # mirrored horizontally as well as standing on its row 0
    ((0, 0.4, -0.4, 0), (-1, -1)),        # a quarter turn: the first column becomes the bottom row
])
def test_the_preview_shows_the_picture_the_way_lightburn_shows_it(matrix, corner):
    grey = np.zeros((4, 6), np.float32)
    grey[0, 0] = 1.0                                                       # the first pixel of the stored picture
    shown, upright = ps._upright(grey, matrix)
    assert upright and shown[corner] == 1.0 and shown.sum() == 1.0
    assert shown.shape == ((6, 4) if matrix[0] == 0 else (4, 6))


def test_a_picture_turned_by_another_angle_is_shown_without_the_turn_and_says_so():
    shown, upright = ps._upright(np.eye(3, dtype=np.float32), (0.35, 0.2, -0.2, 0.35))
    assert not upright and shown.shape == (3, 3)


def test_a_point_of_a_kept_plate_names_the_plate_and_its_experiment(w):
    plan = w["store"].execute("INSERT INTO plan(name,mode,status,device_id,lens_id,data_json,created_at) VALUES ('P','Calibration plate','Exported',?,?,'{}',?)",
                              (w["laser"]["id"], w["lens"]["id"], now())).lastrowid
    pid = pair(w, plan_id=plan)
    observe(w, pid, [30.0, 2.0, 8.0], 6.0)
    (point,) = ps.collect(w["store"], mode(w))["fills"]
    assert point.source["kind"] == "plate" and point.source["id"] == plan and point.source["pair_id"] == pid
    assert point.source["experiment"] == f"plan-{plan}"


def test_measurements_are_read_once_per_state_of_the_data(w, tmp_path):
    store, before = w["store"], ps._collected.cache_info()
    pair(w, check=tonal_check())
    first = ps.collect(store, mode(w))
    first["points"].clear()                                                      # a caller's list is its own
    again = ps.collect(store, mode(w))
    assert len(again["points"]) == 3 and ps._collected.cache_info().hits == before.hits + 1
    pair(w, check=tonal_check(power_range=(6.0, 17.0)))                              # a write through the store: read again
    assert len(ps.collect(store, mode(w))["points"]) == 6
    other = __import__("sqlite3").connect(store.path)                                # a commit by another connection: read again
    other.execute("UPDATE pair SET status='Deleted' WHERE id=(SELECT max(id) FROM pair)")
    other.commit()
    other.close()
    assert len(ps.collect(store, mode(w))["points"]) == 3


def test_the_stamp_changes_with_every_write_and_never_with_a_read(store):
    first = store.stamp()
    store.query("SELECT count(*) FROM pair")
    assert store.stamp() == first
    su.save_material(store, "Grade 5 sheet", grade="Grade 5")
    assert store.stamp() != first


def test_the_kinds_photographed_are_those_of_accepted_tonal_profiles(w):
    assert ps.photographed_kinds(w["store"]) == frozenset()
    pair(w, check=tonal_check())
    pair(w, check=tonal_check(dither="jarvis"), status="Pending")                    # awaiting acceptance: not yet
    pair(w, check={"layers": [{"index": 1, "image": {"dither": "stucki"}}]})         # no tonal profile: nothing measured
    assert ps.photographed_kinds(w["store"]) == {"grayscale"}
    pair(w, check=tonal_check(dither="jarvis"))
    assert ps.photographed_kinds(w["store"]) == {"grayscale", "jarvis"}
