import json
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import synth
from titanium_platform import devices, lenses
from titanium_platform import ingest as ig
from titanium_platform import plans as pl
from titanium_platform import setup as su
from titanium_platform import registration
from titanium_platform import lightburn as lb

CELLS = {"r1c1": (200, 60, 60), "r1c2": (60, 200, 60), "r2c1": (60, 60, 200), "r2c2": (200, 200, 60)}
JOB = {"pulse_width": 200, "line_interval": 0.025, "passes": 1}


@pytest.fixture
def world(store):
    store.set_setting("allow_non_raw_photos", True)  # tests use PNG renders; real use requires RAW
    device = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    lens = lenses.create_lens(store, "F-Theta 174", 174, 170)
    lenses.install(store, device["id"], lens["id"])
    stand = su.save_capture_setup(store, "Rig", "cam", "LED", "90", "ColorChecker Classic")
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    pl.save_marker_layer_settings(store, 20, 60, 300)
    out = pl.create_plate_series(store, device["id"], "10 20", "40 80", "900", 5, 4, 1, **JOB)[0]
    plan = pl.get_plan(store, out["plan_id"])
    return {"store": store, "device": device, "lens": lens, "setup": (device["id"], lens["id"]), "stand": stand,
            "material": material, "plan": plan, "plate": out, "lbrn": pl.export_lbrn2(plan)}


def png(img) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def test_line_measurement_outside_a_manually_aligned_photo_is_missing_evidence():
    layer = SimpleNamespace(regions=[SimpleNamespace(kind="path", polygon=[(0, 0), (10, 0)])])
    image = np.full((100, 100, 3), .5, np.float32)
    image_to_mm = np.array([[1, 0, 1000], [0, 1, 1000], [0, 0, 1]], float)

    result = ig._line_metrics(image, image_to_mm, layer)

    assert result["line_count"] == 1
    assert result["visible_line_count"] == 0
    assert result["lines"][0]["continuity_percent"] == 0


def make_pair(w, lbrn=None, photo=None, **kw):
    context = {"material_id": w["material"]["id"], **kw.pop("context", {})}
    return ig.create_pair(w["store"], device_id=w["device"]["id"], lens_id=kw.pop("lens_id", w["lens"]["id"]),
                          stand_id=w["stand"]["id"], lightburn_name="plate.lbrn2",
                          lightburn_bytes=lbrn or w["lbrn"], photo_name="plate.png", context=context,
                          photo_bytes=photo or png(synth.plate_photo(w["plan"], CELLS, gains=(0.9, 0.97, 1.08))), **kw)


def test_a_good_plate_pair_passes_every_check_and_measures_each_cell(world):
    s = world["store"]
    pid = make_pair(world)
    report = ig.check_pair(s, pid)
    assert report["problems"] == [], report
    al = report["alignment"]
    assert report["chart"]["detected"] and (al["method"], al["valid"], al["error"]) == ("markers", True, None)
    assert len(al["image_to_mm"]) == 3 and all(len(r) == 3 for r in al["image_to_mm"])  # kept so the overlay matches the measurement
    assert report["discrepancies"] == [] and report["plate"]["experiment_id"] == world["plate"]["experiment_id"]
    measured = {l["name"]: l["measured_lab"] for l in report["layers"] if l["measured_lab"]}
    test_measured = {name: lab for name, lab in measured.items() if name in CELLS}
    assert set(test_measured) == set(CELLS)
    assert len({tuple(round(v) for v in lab) for lab in test_measured.values()}) == 4  # four distinguishable colours
    assert any(l.get("role") == "pre-test cleaning witness" and l["measured_lab"] for l in report["layers"])
    marker = next(l for l in report["layers"] if l.get("role") == "registration, QR and engraved labels")
    assert marker["measured_lab"] and {m["name"] for m in marker["submeasurements"]} == {
        "ArUco 0", "ArUco 1", "ArUco 2", "ArUco 3", "QR registration code"}
    assert ig.get_pair(s, pid)["status"] == ig.ST_READY


def test_plate_moved_in_lightburn_uses_saved_file_coordinates(world):
    root = ET.fromstring(world["lbrn"])
    for shape in root.findall(".//Shape"):
        xform = shape.find("XForm")
        if xform is None:
            continue
        values = [float(value) for value in xform.text.split()]
        values[4] += 50
        values[5] += 60
        xform.text = " ".join(str(value) for value in values)
    moved = ET.tostring(root)
    pid = make_pair(world, lbrn=moved)

    report = ig.check_pair(world["store"], pid)

    old_x, old_y = pl.export_offset(world["plan"])
    assert report["alignment"]["valid"] and report["alignment"]["method"] == "markers"
    assert report["alignment"]["file_offset_mm"] == [old_x + 50, old_y + 60]
    assert report["problems"] == []
    assert {layer["name"] for layer in report["layers"] if layer.get("measured_lab")} >= set(CELLS)


def test_lightburn_saved_vertical_mirror_is_reconciled_with_plan_and_photo(world):
    """LightBurn 2.1 can save a MirrorY=True export as MirrorY=False with flipped XForms."""
    store = world["store"]
    plan = world["plan"]
    plan["export_mirror_y"] = True
    row = store.one("SELECT data_json FROM plan WHERE id=?", (plan["id"],))
    data = json.loads(row["data_json"])
    data["export_mirror_y"] = True
    store.execute("UPDATE plan SET data_json=? WHERE id=?", (json.dumps(data), plan["id"]))
    root = ET.fromstring(pl.export_lbrn2(plan))
    assert root.get("MirrorY") == "True"
    work_height = plan["markers"]["extent"]["max_y"] - plan["markers"]["extent"]["min_y"]
    root.set("MirrorY", "False")
    for shape in root.findall(".//Shape"):
        xform = shape.find("XForm")
        if xform is None:
            continue
        a, b, c, d, e, f = (float(value) for value in xform.text.split())
        xform.text = " ".join(str(value) for value in (a, -b, c, -d, e + 30, work_height - f + 40))
    saved = ET.tostring(root)
    photo = png(synth.plate_photo(plan, CELLS, with_chart=False))
    pid = make_pair(world, lbrn=saved, photo=photo)

    report = ig.check_pair(store, pid)

    assert report["project"]["normalized_axes"] == ["Y"]
    assert report["alignment"]["valid"], report["problems"]
    old_x, old_y = pl.export_offset(plan)
    assert report["alignment"]["file_offset_mm"] == pytest.approx([old_x + 30, old_y + 40])
    assert report["problems"] == []
    parsed = lb.parse_bytes(saved)
    lb.normalize_saved_orientation(parsed, mirror_x=False, mirror_y=True)
    original = lb.parse_bytes(pl.export_lbrn2(plan))
    assert parsed.layer(1).regions[0].x == pytest.approx(original.layer(1).regions[0].x + 30)
    assert parsed.layer(1).regions[0].y == pytest.approx(original.layer(1).regions[0].y + 40)


def test_accepting_requires_the_mask_review_then_writes_immutable_observations(world):
    s = world["store"]
    pid = make_pair(world)
    ig.check_pair(s, pid)
    with pytest.raises(ig.IngestError, match="masks"):
        ig.accept_pair(s, pid)
    ig.review_masks(s, pid)
    calls = []
    ids = ig.accept_pair(s, pid, on_accepted=lambda st, device_id, lens_id: calls.append((device_id, lens_id)))
    assert len(ids) == 6 and calls == [world["setup"]]
    assert {(r["device_id"], r["lens_id"]) for r in s.query("SELECT device_id, lens_id FROM observation")} == {world["setup"]}
    obs = s.one("SELECT * FROM observation WHERE evidence_json LIKE '%r1c1%' LIMIT 1")
    params = json.loads(obs["parameters_json"])
    assert {k: params[k] for k in ("power", "frequency", "speed", "pulse_width", "line_interval", "passes")} == {
        "power": 10, "frequency": 40, "speed": 900, "pulse_width": 200, "line_interval": 0.025, "passes": 1}
    assert obs["alignment_method"] == "markers" and obs["model_eligible"] == 1 and obs["repeat_eligible"] == 1
    assert ig.get_pair(s, pid)["status"] == ig.ST_ACCEPTED
    with pytest.raises(ig.IngestError, match="immutable"):
        ig.check_pair(s, pid)
    paths = [s.one("SELECT lightburn_path,photo_path FROM pair WHERE id=?", (pid,))[k] for k in ("lightburn_path", "photo_path")]
    ig.delete_pair(s, pid)
    assert s.one("SELECT status FROM pair WHERE id=?", (pid,))["status"] == ig.ST_DELETED
    assert s.one("SELECT COUNT(*) AS n FROM observation WHERE pair_id=?", (pid,))["n"] == 6
    assert all(not __import__("pathlib").Path(path).exists() for path in paths)
    with pytest.raises(KeyError, match="not found"):
        ig.get_pair(s, pid)
    from titanium_platform import model
    assert all(o["pair_id"] != pid for o in model.eligible_observations(s, *world["setup"]))


def test_a_system_plate_without_a_separate_chart_is_measured_relative_to_the_raw_photo(world):
    s = world["store"]
    pid = make_pair(world, photo=png(synth.plate_photo(world["plan"], CELLS, with_chart=False)))
    report = ig.check_pair(s, pid)
    assert not report["chart"]["detected"] and report["color_measurement"]["mode"] == "raw_camera_relative"
    assert report["alignment"]["valid"] and report["problems"] == [] and report["warnings"]
    assert ig.get_pair(s, pid)["status"] == ig.ST_READY
    ig.review_masks(s, pid)
    ids = ig.accept_pair(s, pid)
    assert len(ids) == 6
    evidence = json.loads(s.one("SELECT evidence_json FROM observation ORDER BY id LIMIT 1")["evidence_json"])
    assert evidence["color_measurement"]["mode"] == "raw_camera_relative"
    assert s.one("SELECT model_eligible FROM observation ORDER BY id LIMIT 1")["model_eligible"] == 0
    from titanium_platform import model
    relative_sets = model.camera_relative_sets(s, *world["setup"])
    assert len(relative_sets) == 1 and len(relative_sets[0]["samples"]) == 6
    assert model.knowledge_summaries(s, *world["setup"]) == {}


def test_a_mirrored_plate_with_three_markers_aligns_only_after_its_qr_matches(world):
    plan = world["plan"]
    img = synth.plate_photo(plan, CELLS, with_chart=False)
    marker, ext = plan["markers"]["aruco"][0], plan["markers"]["extent"]
    scale, ox, oy = 20.0, 520, 80
    x0 = round((marker["x"] - ext["min_x"]) * scale + ox)
    y0 = round((marker["y"] - ext["min_y"]) * scale + oy)
    x1 = round((marker["x"] + marker["size"] - ext["min_x"]) * scale + ox)
    y1 = round((marker["y"] + marker["size"] - ext["min_y"]) * scale + oy)
    img[y0:y1, x0:x1] = 255  # simulate one unreadable engraved registration marker
    pid = make_pair(world, photo=png(cv2.flip(img, 1)))

    report = ig.check_pair(world["store"], pid)

    assert report["alignment"]["valid"] and report["alignment"]["marker_count"] == 3
    assert report["problems"] == [] and report["color_measurement"]["mode"] == "raw_camera_relative"


def test_manual_photo_corners_use_qr_to_preserve_vertical_mirror(world):
    plan = world["plan"]
    img = cv2.flip(synth.plate_photo(plan, CELLS, with_chart=False), 0)
    ext = plan["markers"]["extent"]
    ox, oy, scale = 520, 80, 20.0
    width = (ext["max_x"] - ext["min_x"]) * scale
    height = (ext["max_y"] - ext["min_y"]) * scale
    top = img.shape[0] - (oy + height)
    bottom = img.shape[0] - oy
    corners = [(ox, top), (ox + width, top), (ox + width, bottom), (ox, bottom)]
    pid = make_pair(world, photo=png(img))

    report = ig.check_pair(world["store"], pid, corners=corners)

    assert report["alignment"]["valid"] and report["alignment"]["method"] == "manual"
    assert report["alignment"]["identifier_verified"] and report["alignment"]["reflected"]
    assert report["problems"] == []


def test_plate_chart_candidate_with_rejected_correction_falls_back_to_raw_relative_measurement(world, monkeypatch):
    s = world["store"]
    pid = make_pair(world)
    chart = ig.ph.Chart(True, reason="chart correction residual 40.5 exceeds 12")
    correction = ig.ph.Correction(np.eye(3), 40.5)
    monkeypatch.setattr(ig.ph, "correct", lambda _img, **_kw: (None, chart, correction))

    report = ig.check_pair(s, pid)

    assert report["chart"]["detected"] and not report["chart"]["usable"]
    assert report["chart"]["residual"] == 40.5 and report["chart"]["max_residual"] == 12.0
    assert report["color_measurement"]["mode"] == "raw_camera_relative"
    assert report["alignment"]["valid"] and report["problems"] == [] and report["warnings"]
    assert s.one("SELECT COUNT(*) AS n FROM observation")["n"] == 0


def test_two_markers_without_qr_stop_the_plate_mapping_instead_of_guessing(world):
    s = world["store"]
    plan = dict(world["plan"])
    markers = plan["markers"]
    plan["markers"] = {**markers, "aruco": markers["aruco"][:2],
                       "qr": {**markers["qr"], "rects": []}}
    pid = make_pair(world, photo=png(synth.plate_photo({**world["plan"], "markers": plan["markers"]}, CELLS)))
    report = ig.check_pair(s, pid)
    assert not report["alignment"]["valid"] and "only 2 registration markers" in report["alignment"]["error"]
    assert s.one("SELECT COUNT(*) AS n FROM observation")["n"] == 0


def test_a_plate_with_unreadable_aruco_marks_can_use_manual_corners_and_verify_its_qr(world, monkeypatch):
    plan = world["plan"]
    extent = plan["markers"]["extent"]
    scale, ox, oy = 20.0, 520, 80
    px_w = (extent["max_x"] - extent["min_x"]) * scale
    px_h = (extent["max_y"] - extent["min_y"]) * scale
    corners = [(ox, oy), (ox + px_w, oy), (ox + px_w, oy + px_h), (ox, oy + px_h)]
    pid = make_pair(world)
    monkeypatch.setattr(ig.ph, "detect_marker_candidates", lambda _img: [])
    monkeypatch.setattr(registration, "register_markers", lambda *_args: None)

    report = ig.check_pair(world["store"], pid, corners=corners)

    assert report["alignment"]["valid"] and report["alignment"]["method"] == "manual"
    assert report["alignment"]["marker_count"] == 0 and report["alignment"]["identifier_verified"]
    assert report["problems"] == []
    assert all(layer["measured_lab"] for layer in report["layers"] if layer["role"] == "test feature")


def test_one_manually_placed_element_positions_the_whole_plate(world, monkeypatch):
    project = lb.parse_bytes(world["lbrn"])
    layer = next(item for item in project.layers if item.name == "r1c1")
    polygon = layer.regions[0].polygon
    photo = synth.plate_photo(world["plan"], CELLS, with_chart=False)
    height, width = photo.shape[:2]
    anchor = {"layer_index": layer.index, "region_index": 0,
              "corners_fraction": [[(x * 20 + 520) / width, (y * 20 + 80) / height] for x, y in polygon]}
    pid = make_pair(world, photo=png(photo))
    monkeypatch.setattr(ig.ph, "detect_marker_candidates", lambda _img: [])
    monkeypatch.setattr(registration, "register_markers", lambda *_args: None)

    report = ig.check_pair(world["store"], pid, anchor=anchor)

    assert report["alignment"]["valid"] and report["alignment"]["method"] == "element anchor"
    assert report["alignment"]["anchor_element"] == "r1c1 #1"
    assert report["problems"] == []
    assert {item["name"] for item in report["layers"] if item.get("measured_lab")} >= set(CELLS)
    assert ig.get_pair(world["store"], pid)["anchor"] == anchor


def test_a_small_element_anchor_cannot_be_stretched_over_the_entire_plate(world, monkeypatch):
    project = lb.parse_bytes(world["lbrn"])
    layer = next(item for item in project.layers if item.name == "r1c1")
    photo = synth.plate_photo(world["plan"], CELLS, with_chart=False)
    anchor = {"layer_index": layer.index, "region_index": 0,
              "corners_fraction": [[.1, .1], [.9, .1], [.9, .9], [.1, .9]]}
    pid = make_pair(world, photo=png(photo))
    monkeypatch.setattr(ig.ph, "detect_marker_candidates", lambda _img: [])
    monkeypatch.setattr(registration, "register_markers", lambda *_args: None)

    report = ig.check_pair(world["store"], pid, anchor=anchor)

    assert not report["alignment"]["valid"]
    assert "selected detail is too small" in report["alignment"]["error"]
    assert ig.get_pair(world["store"], pid)["status"] == ig.ST_CORRECTION


def test_manual_plate_alignment_still_rejects_a_readable_wrong_qr(world, monkeypatch):
    s = world["store"]
    other = pl.create_plate_series(s, world["device"]["id"], "10 20", "40 80", "1200", 5, 4, 1, **JOB)[0]
    other_plan = pl.get_plan(s, other["plan_id"])
    extent = other_plan["markers"]["extent"]
    scale, ox, oy = 20.0, 520, 80
    px_w = (extent["max_x"] - extent["min_x"]) * scale
    px_h = (extent["max_y"] - extent["min_y"]) * scale
    corners = [(ox, oy), (ox + px_w, oy), (ox + px_w, oy + px_h), (ox, oy + px_h)]
    pid = make_pair(world, photo=png(synth.plate_photo(other_plan, CELLS)))
    monkeypatch.setattr(ig.ph, "detect_marker_candidates", lambda _img: [])
    monkeypatch.setattr(registration, "register_markers", lambda *_args: None)

    report = ig.check_pair(s, pid, corners=corners)

    assert not report["alignment"]["valid"] and "photographed plate is" in report["alignment"]["error"]
    assert s.one("SELECT COUNT(*) AS n FROM observation")["n"] == 0


def test_vector_line_readout_reports_visibility_continuity_and_apparent_trace_width():
    rgb = np.ones((120, 120, 3), np.float32)
    rgb[57:63, 10:110] = 0.03
    layer = SimpleNamespace(regions=[SimpleNamespace(kind="path", polygon=[(1.0, 6.0), (11.0, 6.0)])])
    px_to_mm = np.array([[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]], np.float32)

    metrics = ig._line_metrics(rgb, px_to_mm, layer)

    assert metrics["line_count"] == metrics["visible_line_count"] == 1
    assert metrics["median_continuity_percent"] == 100.0
    assert 0.4 <= metrics["median_apparent_trace_width_mm"] <= 0.7
    assert "not the optical spot diameter" in metrics["limitation"]


def test_single_vector_stroke_has_a_measurement_corridor_when_fill_mask_is_empty():
    layer = SimpleNamespace(regions=[SimpleNamespace(kind="path", polygon=[(1.0, 6.0), (11.0, 6.0)])])
    image_to_mm = np.array([[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]], np.float32)

    mask = ig._small_path_mask(layer, image_to_mm, (120, 120))

    assert mask.dtype == bool and mask.sum() >= 100
    assert mask[60, 60] and not mask[40, 60]


def test_tiny_rectangular_text_glyphs_are_sampled_without_eroding_them_away():
    layer = SimpleNamespace(regions=[SimpleNamespace(kind="rect", polygon=[
        (2.0 + i * .27, 2.0), (2.16 + i * .27, 2.0),
        (2.16 + i * .27, 2.16), (2.0 + i * .27, 2.16)]) for i in range(20)])
    image_to_mm = np.array([[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]], np.float32)

    mask = ig._small_path_mask(layer, image_to_mm, (80, 80))

    assert mask.sum() >= 25 and mask[20, 20]


def test_compact_multi_gap_layer_reports_each_spacing_group_separately():
    rgb = np.ones((120, 120, 3), np.float32)
    rgb[42:48, 10:110] = 0.03
    rgb[72:78, 10:110] = 0.03
    layer = SimpleNamespace(regions=[
        SimpleNamespace(kind="path", polygon=[(1.0, 4.5), (11.0, 4.5)]),
        SimpleNamespace(kind="path", polygon=[(1.0, 7.5), (11.0, 7.5)]),
    ])
    planned = {"measurement_groups": [
        {"name": "LINE-GAP-20UM", "region_start": 0, "region_count": 1, "spacing_um": 20},
        {"name": "LINE-GAP-300UM", "region_start": 1, "region_count": 1, "spacing_um": 300},
    ]}
    px_to_mm = np.array([[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]], np.float32)
    metrics = ig._line_metrics(rgb, px_to_mm, layer, planned)
    assert [(g["spacing_um"], g["line_count"], g["visible_line_count"]) for g in metrics["groups"]] == [(20, 1, 1), (300, 1, 1)]


def test_a_non_raw_photo_is_refused_when_not_allowed(world):
    world["store"].set_setting("allow_non_raw_photos", False)
    with pytest.raises(ig.IngestError, match="RAW"):
        make_pair(world)


def test_bad_inputs_are_rejected_before_anything_is_stored(world):
    s = world["store"]
    with pytest.raises(ig.IngestError, match="lbrn"):
        ig.create_pair(s, device_id=world["device"]["id"], lens_id=None, stand_id=world["stand"]["id"], lightburn_name="x.txt", lightburn_bytes=b"x", photo_name="p.png", photo_bytes=b"x")
    with pytest.raises(ig.IngestError, match="capture setup"):
        ig.create_pair(s, device_id=world["device"]["id"], lens_id=None, stand_id=999, lightburn_name="x.lbrn2", lightburn_bytes=b"x", photo_name="p.png", photo_bytes=b"x")
    assert s.one("SELECT COUNT(*) AS n FROM pair")["n"] == 0


def test_context_is_optional_and_defaults_to_unknown():
    assert ig.clean_context(None) == {"material_id": None, "titanium_name": None, "titanium_grade": None,
                                     "titanium_thickness_mm": None, "titanium_surface": None,
                                     "batch": None, "focus": None, "engraved_at": None, "note": None}
    c = ig.clean_context({"focus": "1.5", "engraved_at": "2026-10-14", "batch": " B1 "})
    assert (c["focus"], c["engraved_at"], c["batch"]) == (1.5, "2026-10-14", "B1")
    for bad in ({"focus": "abc"}, {"focus": "nan"}, {"engraved_at": "14.10.2026"}):
        with pytest.raises(su.ValidationError):
            ig.clean_context(bad)


def test_same_as_previous_uses_the_last_accepted_pair_of_the_laser_with_its_lens(world):
    s = world["store"]
    assert ig.previous_context(s, world["device"]["id"]) is None
    s.execute("UPDATE material_profile SET batch='B-7' WHERE id=?", (world["material"]["id"],))
    pid = make_pair(world, context={"batch": "B-7", "focus": 0.5})
    ig.check_pair(s, pid)
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    previous = ig.previous_context(s, world["device"]["id"])
    assert previous["batch"] == "B-7" and previous["lens_id"] == world["lens"]["id"]


def test_an_imported_work_is_not_given_the_installed_lens(world):
    """REQ-016: the lens installed now is never asserted for an imported work; unknown stays unknown."""
    s = world["store"]
    pid = make_pair(world, lens_id=None)
    pair = ig.get_pair(s, pid)
    assert pair["lens_id"] is None and pair["hardware"]["lens"] is None and pair["hardware"]["device"]["id"] == world["device"]["id"]


def test_a_photograph_of_a_plate_takes_the_plates_lens_and_says_so(world):
    """REQ-019: comparability follows the lens the plate was made with; the other choice stays visible as a warning."""
    s = world["store"]
    pid = make_pair(world, lens_id=None)
    report = ig.check_pair(s, pid)
    assert report["problems"] == [] and report["lens"]["lens_id"] == world["lens"]["id"]
    assert any(w.startswith("no lens was chosen for this photograph") for w in report["lens"]["warnings"])
    pair = ig.get_pair(s, pid)
    assert pair["lens_id"] == world["lens"]["id"] and pair["hardware"]["lens"]["id"] == world["lens"]["id"]
    again = ig.check_pair(s, pid)                    # the operator's choice and the warning stay on a re-check
    assert again["lens"]["chosen_lens_id"] is None and any(w.startswith("no lens was chosen") for w in again["lens"]["warnings"])
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    assert {r["lens_id"] for r in s.query("SELECT lens_id FROM observation WHERE pair_id=?", (pid,))} == {world["lens"]["id"]}


def test_a_plate_made_for_another_laser_blocks_the_pair(world):
    s = world["store"]
    other = devices.create_from_template(s, "jpt-ydflp-e-60-m7-m-r", "Second laser")
    pid = ig.create_pair(s, device_id=other["id"], lens_id=None, stand_id=world["stand"]["id"], lightburn_name="plate.lbrn2",
                         lightburn_bytes=world["lbrn"], photo_name="plate.png", context={"material_id": world["material"]["id"]},
                         photo_bytes=png(synth.plate_photo(world["plan"], CELLS, gains=(0.9, 0.97, 1.08))))
    report = ig.check_pair(s, pid)
    assert "this plate was made for a different laser than the one selected" in report["problems"]
    assert ig.get_pair(s, pid)["status"] == ig.ST_CORRECTION
    with pytest.raises(ig.IngestError, match="not ready to accept"):
        ig.accept_pair(s, pid)


def edited_lbrn(world, power_for_r1c2=None, pulse_width=None):
    """The plate file as exported, then edited the way an operator might in LightBurn."""
    text = world["lbrn"].decode()
    if power_for_r1c2 is not None:
        # r1c2 is the second cell: power 20, frequency 40
        text = text.replace('<name Value="r1c2"/>\n        <maxPower Value="20"/>\n        <maxPower2 Value="20"/>',
                            f'<name Value="r1c2"/>\n        <maxPower Value="{power_for_r1c2}"/>\n        <maxPower2 Value="{power_for_r1c2}"/>')
    if pulse_width is not None:
        # C00 is the pre-test cleaning layer; mutate only the first experimental cell.
        layer_start = text.index('<name Value="r1c1"/>')
        pulse_at = text.index('<QPulseWidth Value="200"/>', layer_start)
        text = text[:pulse_at] + text[pulse_at:].replace('<QPulseWidth Value="200"/>', f'<QPulseWidth Value="{pulse_width}"/>', 1)
    return text.encode()


def test_a_file_that_differs_from_the_plate_blocks_acceptance_until_confirmed(world):
    s = world["store"]
    pid = make_pair(world, lbrn=edited_lbrn(world, power_for_r1c2=33))
    report = ig.check_pair(s, pid)
    assert report["discrepancies"] == [{"cell_id": "r1c2", "field": "power", "defined": 20, "from_file": 33}]
    assert any("differs from the plate definition" in p for p in report["problems"])
    ig.review_masks(s, pid)
    with pytest.raises(ig.IngestError):
        ig.accept_pair(s, pid)
    with pytest.raises(ig.IngestError, match="own words"):
        ig.confirm_file(s, pid, "  ")
    conf = ig.confirm_file(s, pid, "I engraved with this exact file")
    assert conf["discrepancies"] == report["discrepancies"] and conf["file_name"] == "plate.lbrn2"
    assert ig.get_pair(s, pid)["status"] == ig.ST_READY
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    power = {r["layer_index"]: json.loads(r["parameters_json"])["power"] for r in s.query("SELECT layer_index, parameters_json FROM observation")}
    # layers follow the cell order r1c1, r1c2, r2c1, r2c2 -> indices 1..4; r1c2 was edited from 20 to 33 in the file
    assert power == {-1: 20, 0: 20, 1: 10, 2: 33, 3: 10, 4: 20}  # system layers and test layers have distinct indices
    evidence = json.loads(s.one("SELECT evidence_json FROM observation WHERE layer_index=2")["evidence_json"])
    assert evidence["discrepancies"][0]["from_file"] == 33 and evidence["file_confirmation"]["text"].startswith("I engraved")
    assert s.one("SELECT COUNT(*) AS n FROM audit WHERE action='file_confirmed'")["n"] == 1


def test_correcting_the_pair_with_a_matching_file_clears_the_mismatch(world):
    s = world["store"]
    pid = make_pair(world, lbrn=edited_lbrn(world, power_for_r1c2=33))
    ig.check_pair(s, pid)
    ig.confirm_file(s, pid, "used")
    ig.replace_lightburn_file(s, pid, "fixed.lbrn2", world["lbrn"])
    pair = ig.get_pair(s, pid)
    assert pair["status"] == ig.ST_PENDING and pair["file_confirmation"] is None and not pair["masks_reviewed"] and pair["check"] is None
    assert ig.check_pair(s, pid)["discrepancies"] == []
    with pytest.raises(ig.IngestError, match="no discrepancy"):
        ig.confirm_file(s, pid, "used")


def test_a_layer_with_a_different_pulse_width_is_retained_as_a_job_setting(world):
    s = world["store"]
    pid = make_pair(world, lbrn=edited_lbrn(world, pulse_width=500))
    report = ig.check_pair(s, pid)
    layer = next(l for l in report["layers"] if l["name"] == "r1c1")
    assert layer["compatible"] and layer["pulse_width"] == 500 and layer["measured_lab"] is not None
    assert any(d["field"] == "pulse_width" for d in report["discrepancies"])
    ig.confirm_file(s, pid, "This edited LightBurn file was used for the engraving")
    ig.review_masks(s, pid)
    ids = ig.accept_pair(s, pid)
    assert len(ids) == 6
    params = json.loads(s.one("SELECT parameters_json FROM observation WHERE layer_index=1")["parameters_json"])
    assert params["pulse_width"] == 500


def test_omitted_q_pulse_and_cut_interval_are_unknown_not_plate_differences(world):
    project = lb.parse_bytes(world["lbrn"])
    cells = json.loads(world["store"].one("SELECT cells_json FROM plate WHERE id=?", (world["plate"]["plate_id"],))["cells_json"])
    target = next(layer for layer in project.layers if layer.name == cells[0]["id"])
    target.pulse_width = None
    target.line_interval = None
    target.layer_type = "Cut"
    differences, mapping, missing = ig.compare_plate(cells, project.layers, 0, 0)
    assert differences == []
    assert missing == [] and mapping[cells[0]["id"]] is target
    assert not any("line interval is missing" in note for note in ig.layer_report(target, world["device"]["passport"])["notes"])


def test_export_rounding_is_not_a_false_plate_discrepancy():
    cell = {"name": "MATRIX-V2333.33-F262.5", "parameters": {"power": 60.0,
            "frequency": 262.5004, "speed": 2333.3333, "pulse_width": 200.0,
            "line_interval": 0.025, "passes": 1}}
    layer = SimpleNamespace(name=cell["name"], power=60.0, frequency_khz=262.5,
                            speed=2333.33, pulse_width=200.0, line_interval=0.025,
                            passes=1, regions=[])
    differences, _, missing = ig.compare_plate([cell], [layer], 0, 0)
    assert differences == [] and missing == []
    layer.speed = 2340.0
    differences, _, _ = ig.compare_plate([cell], [layer], 0, 0)
    assert [(item["field"], item["from_file"]) for item in differences] == [("speed", 2340.0)]


def test_the_marker_layer_is_measured_even_when_legacy_settings_are_incomplete(world):
    s = world["store"]
    pid = make_pair(world)
    report = ig.check_pair(s, pid)
    marker = next(l for l in report["layers"] if l["name"] == "Markers")
    assert marker["measured_lab"] is not None
    assert marker["submeasurements"]
    assert not marker["compatible"] and any("pulse width is missing" in note for note in marker["notes"])


def test_a_rephotograph_shares_the_engraving_and_is_never_an_independent_repetition(world):
    s = world["store"]
    first = make_pair(world)
    ig.check_pair(s, first)
    ig.review_masks(s, first)
    ig.accept_pair(s, first)
    again = make_pair(world, rephoto_of=first)
    ig.check_pair(s, again)
    ig.review_masks(s, again)
    ig.accept_pair(s, again)
    rows = s.query("SELECT pair_id, engraving_id, repeat_eligible, model_eligible FROM observation")
    assert len({r["engraving_id"] for r in rows}) == 1
    assert {r["repeat_eligible"] for r in rows if r["pair_id"] == first} == {1}
    assert {r["repeat_eligible"] for r in rows if r["pair_id"] == again} == {0}
    check_rows = s.query("SELECT model_eligible,evidence_json FROM observation")
    assert {r["model_eligible"] for r in check_rows} == {0, 1}
    marker_rows = [r for r in check_rows if json.loads(r["evidence_json"]).get("role") == "registration, QR and engraved labels"]
    assert marker_rows and all(r["model_eligible"] == 0 for r in marker_rows)  # legacy marker settings lack the full vector
    with pytest.raises(ig.IngestError, match="accepted pair"):
        make_pair(world, rephoto_of=make_pair(world))


def test_a_marked_work_without_a_known_plate_needs_corners_and_aligns_manually(world):
    """A finished work from LightBurn: no markers, so the operator places the four corners."""
    s = world["store"]
    lbrn = (b'<LightBurnProject AppVersion="2.0.04"><CutSetting type="Scan"><index Value="5"/><name Value="C05"/>'
            b'<maxPower Value="24"/><speed Value="900"/><frequency Value="40000"/><QPulseWidth Value="200"/><interval Value="0.025"/></CutSetting>'
            b'<Shape Type="Rect" CutIndex="5" W="40" H="20" Cr="0"><XForm>1 0 0 1 30 20</XForm></Shape></LightBurnProject>')
    import numpy as np
    img = synth.scene(work_rgb=(200, 120, 40), work_box=(560, 200, 960, 400))
    pid = make_pair(world, lbrn=lbrn, photo=png(img))
    first = ig.check_pair(s, pid)
    assert not first["alignment"]["valid"] and any("four image corners" in p for p in first["problems"])
    corners = [(560, 200), (960, 200), (960, 400), (560, 400)]
    report = ig.check_pair(s, pid, corners=corners)
    assert report["problems"] == [] and report["alignment"]["method"] == "manual"
    lab = report["layers"][0]["measured_lab"]
    from titanium_platform import color
    assert color.delta_e(lab, color.srgb8_to_lab(np.array([200, 120, 40]))) < 6
    assert ig.get_pair(s, pid)["corners"] == [list(c) for c in corners]  # stored as JSON lists
    bad = ig.check_pair(s, pid, corners=[(0, 0), (10, 0), (0, 10), (10, 10)])
    assert not bad["alignment"]["valid"] and "convex" in bad["alignment"]["error"]


def test_a_photo_of_another_plate_is_refused(world):
    s = world["store"]
    other = pl.create_plate_series(s, world["device"]["id"], "10 20", "40 80", "1200", 5, 4, 1, **JOB)[0]
    other_plan = pl.get_plan(s, other["plan_id"])
    pid = make_pair(world, photo=png(synth.plate_photo(other_plan, CELLS)))
    report = ig.check_pair(s, pid)
    assert not report["alignment"]["valid"] and "photographed plate is" in report["alignment"]["error"]


def test_corners_can_be_given_as_fractions_of_the_photo_and_must_lie_inside_it(world):
    s = world["store"]
    lbrn = (b'<LightBurnProject AppVersion="2.0.04"><CutSetting type="Scan"><index Value="5"/><name Value="C05"/>'
            b'<maxPower Value="24"/><speed Value="900"/><frequency Value="40000"/><QPulseWidth Value="200"/><interval Value="0.025"/></CutSetting>'
            b'<Shape Type="Rect" CutIndex="5" W="40" H="20" Cr="0"><XForm>1 0 0 1 30 20</XForm></Shape></LightBurnProject>')
    img = synth.scene(work_rgb=(200, 120, 40), work_box=(560, 200, 960, 400))   # 1500 x 1000 px
    pid = make_pair(world, lbrn=lbrn, photo=png(img))
    report = ig.check_pair(s, pid, corners_fraction=[(560 / 1500, 0.2), (960 / 1500, 0.2), (960 / 1500, 0.4), (560 / 1500, 0.4)])
    assert report["problems"] == [] and report["alignment"]["method"] == "manual" and report["image_size"] == [1500, 1000]
    assert len(report["alignment"]["image_to_mm"]) == 3
    stored = ig.get_pair(s, pid)["corners"]
    assert stored[0] == pytest.approx([560, 200]) and stored[2] == pytest.approx([960, 400])
    bad = ig.check_pair(s, pid, corners_fraction=[(0, 0), (1.2, 0), (1, 1), (0, 1)])
    assert any("inside the photograph" in p for p in bad["problems"])


def test_the_overlay_outlines_the_measured_layers_on_the_photograph(world):
    import numpy as np
    s = world["store"]
    pid = make_pair(world)
    with pytest.raises(ig.IngestError, match="not aligned"):
        ig.overlay_png(s, pid)
    ig.check_pair(s, pid)
    raw_bytes = ig.overlay_png(s, pid, corrected=False)
    raw = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
    plain = cv2.imdecode(np.frombuffer(open(ig.get_pair(s, pid)["photo_path"], "rb").read(), np.uint8), cv2.IMREAD_COLOR)
    scale = raw.shape[1] / plain.shape[1]
    assert scale <= 1.0 and raw.shape[2] == 3
    resized = cv2.resize(plain, (raw.shape[1], raw.shape[0]), interpolation=cv2.INTER_AREA)
    changed = (np.abs(raw.astype(int) - resized.astype(int)).sum(axis=2) > 30)
    assert 0 < changed.mean() < 0.05  # thin outlines were drawn, the picture is otherwise untouched
    report = ig.get_pair(s, pid)["check"]
    chosen = next(layer for layer in report["layers"] if layer["measured_lab"] is not None)
    isolated = cv2.imdecode(np.frombuffer(ig.overlay_png(s, pid, corrected=False, layer_index=chosen["index"]), np.uint8), cv2.IMREAD_COLOR)
    lifted = cv2.imdecode(np.frombuffer(ig.overlay_png(s, pid, corrected=False, visibility="lifted"), np.uint8), cv2.IMREAD_COLOR)
    assert not np.array_equal(raw, isolated)  # one layer can be inspected without the other outlines
    assert lifted.mean() > raw.mean()  # viewing brightness changes only the PNG, never the measured values
    with pytest.raises(ig.IngestError, match="not part of this pair"):
        ig.overlay_png(s, pid, layer_index=999)
    assert len(ig.overlay_png(s, pid, corrected=True)) > 1000


def test_moving_one_outline_shifts_the_entire_lightburn_geometry_and_persists(world):
    s = world["store"]
    pid = make_pair(world)
    original = ig.check_pair(s, pid)
    width, height = original["image_size"]
    before = np.asarray(original["alignment"]["image_to_mm"])
    with pytest.raises(ig.IngestError, match="displacement"):
        ig.check_pair(s, pid, translation_fraction=[1.1, 0])

    moved = ig.check_pair(s, pid, translation_fraction=[.002, -.002])
    assert moved["alignment"]["valid"] and moved["alignment"]["method"] == "manual shift"
    after = np.asarray(moved["alignment"]["image_to_mm"])
    points = np.float32([[[100., 100.], [120., 150.]]])
    file_points = cv2.perspectiveTransform(points, before)
    image_points = cv2.perspectiveTransform(file_points, np.linalg.inv(after))
    assert np.allclose(image_points[0] - points[0], [width * .002, -height * .002], atol=.1)
    assert np.allclose(np.linalg.norm(file_points[0, 0] - file_points[0, 1]),
                       np.linalg.norm(cv2.perspectiveTransform(image_points, after)[0, 0] -
                                      cv2.perspectiveTransform(image_points, after)[0, 1]), atol=.01)
    assert np.allclose(ig.check_pair(s, pid)["alignment"]["image_to_mm"], after)
    assert ig.get_pair(s, pid)["masks_reviewed"] is False
    alpha = cv2.imdecode(np.frombuffer(ig.overlay_png(s, pid, transparent=True), np.uint8), cv2.IMREAD_UNCHANGED)
    assert alpha.shape[2] == 4 and alpha[..., 3].max() == 255 and alpha[..., 3].min() == 0


def test_rotating_overlay_keeps_every_lightburn_vector_rigid_and_can_rotate_back(world):
    s = world["store"]
    pid = make_pair(world)
    original = ig.check_pair(s, pid)
    width, height = original["image_size"]
    before = np.asarray(original["alignment"]["image_to_mm"])
    with pytest.raises(ig.IngestError, match="rotation"):
        ig.check_pair(s, pid, rotation_degrees=361)
    with pytest.raises(ig.IngestError, match="rotation"):
        ig.check_pair(s, pid, rotation_degrees=float("nan"))

    rotated = ig.check_pair(s, pid, rotation_degrees=90)
    assert rotated["alignment"]["method"] == "manual rotation"
    after = np.asarray(rotated["alignment"]["image_to_mm"])
    image_points = np.float32([[[width * .4, height * .4], [width * .6, height * .4]]])
    file_points = cv2.perspectiveTransform(image_points, before)
    projected = cv2.perspectiveTransform(file_points, np.linalg.inv(after))[0]
    center = np.array([width / 2, height / 2])
    relative = image_points[0] - center
    expected = center + np.column_stack((-relative[:, 1], relative[:, 0]))
    assert np.allclose(projected, expected, atol=.1)
    assert np.allclose(ig.check_pair(s, pid)["alignment"]["image_to_mm"], after)

    restored = ig.check_pair(s, pid, rotation_degrees=270)
    assert restored["alignment"]["valid"]
    assert np.allclose(restored["alignment"]["image_to_mm"], before, atol=1e-8)

    combined = ig.check_pair(s, pid, rotation_degrees=17, translation_fraction=[.004, -.006])
    after_both = np.asarray(combined["alignment"]["image_to_mm"])
    projected = cv2.perspectiveTransform(file_points, np.linalg.inv(after_both))[0]
    radians = np.deg2rad(17)
    rotated = np.column_stack((relative[:, 0] * np.cos(radians) - relative[:, 1] * np.sin(radians),
                               relative[:, 0] * np.sin(radians) + relative[:, 1] * np.cos(radians)))
    assert np.allclose(projected, center + rotated + [width * .004, -height * .006], atol=.1)


@pytest.mark.parametrize("mirror_horizontal,mirror_vertical", [(True, False), (False, True), (True, True)])
def test_scaling_and_mirroring_overlay_change_photo_projection_not_lightburn_mm(world, mirror_horizontal, mirror_vertical):
    s = world["store"]
    pid = make_pair(world)
    original = ig.check_pair(s, pid)
    width, height = original["image_size"]
    before = np.asarray(original["alignment"]["image_to_mm"])
    for invalid in (0, .09, 8.01, float("nan")):
        with pytest.raises(ig.IngestError, match="scale"):
            ig.check_pair(s, pid, scale_factor=invalid)

    changed = ig.check_pair(s, pid, scale_factor=1.5, mirror_horizontal=mirror_horizontal,
                            mirror_vertical=mirror_vertical, rotation_degrees=90,
                            translation_fraction=[.01, -.02])
    assert changed["alignment"]["method"] == "manual transform"
    assert changed["alignment"]["reflected"] == (mirror_horizontal ^ mirror_vertical)
    after = np.asarray(changed["alignment"]["image_to_mm"])
    image_points = np.float32([[[width * .4, height * .4], [width * .6, height * .4]]])
    file_points = cv2.perspectiveTransform(image_points, before)
    projected = cv2.perspectiveTransform(file_points, np.linalg.inv(after))[0]
    center = np.array([width / 2, height / 2])
    relative = image_points[0] - center
    reflected = relative * [(-1 if mirror_horizontal else 1) * 1.5,
                            (-1 if mirror_vertical else 1) * 1.5]
    expected = center + np.column_stack((-reflected[:, 1], reflected[:, 0])) + [width * .01, -height * .02]
    assert np.allclose(projected, expected, atol=.1)
    assert np.allclose(cv2.perspectiveTransform(projected[None].astype(np.float32), after), file_points, atol=.01)
    assert np.allclose(ig.check_pair(s, pid)["alignment"]["image_to_mm"], after)


def test_shape_snap_preview_uses_current_transform_without_saving_it(world, monkeypatch):
    s = world["store"]
    pid = make_pair(world)
    ig.check_pair(s, pid)
    original = ig.get_pair(s, pid)
    captured = {}

    def fake_snap(image, layers, image_to_mm, excluded):
        captured.update(image_shape=image.shape, image_to_mm=image_to_mm, excluded=excluded)
        return [{"element": "test detail", "shift_px": [14, -7], "support_count": 2, "shape_score": .03}]

    monkeypatch.setattr(registration, "snap_translations", fake_snap)
    candidates = ig.snap_pair_overlay(s, pid, scale_factor=1.5, mirror_horizontal=True,
                                      translation_fraction=[.01, -.02])
    height, width = captured["image_shape"][:2]
    assert candidates == [{"element": "test detail", "support_count": 2, "shape_score": .03,
                           "shift_fraction": [14 / width, -7 / height]}]
    assert 0 < width <= 1400 and 0 < height <= 1400
    assert not np.allclose(captured["image_to_mm"], original["check"]["alignment"]["image_to_mm"])
    assert ig.get_pair(s, pid)["check"] == original["check"]


def test_bad_overlay_shift_is_blocked_but_can_be_moved_back(world):
    s = world["store"]
    pid = make_pair(world)
    assert ig.check_pair(s, pid)["alignment"]["vector_found"] >= 4

    bad = ig.check_pair(s, pid, translation_fraction=[.06, .03])

    assert not bad["alignment"]["valid"] and ig.get_pair(s, pid)["status"] == ig.ST_CORRECTION
    assert "lost too many" in bad["problems"][0]
    assert len(ig.overlay_png(s, pid, transparent=True)) > 1000  # still editable on the photo
    recovered = ig.check_pair(s, pid, translation_fraction=[-.06, -.03])
    assert recovered["alignment"]["valid"] and recovered["alignment"]["vector_found"] >= 4


def test_correcting_work_corners_overrides_automatic_marker_alignment(world):
    s = world["store"]
    pid = make_pair(world)
    first = ig.check_pair(s, pid)
    assert first["alignment"]["method"] == "markers"
    initial = first["alignment"]["work_corners_fraction"]
    shifted = [[x + .002, y] for x, y in initial]

    corrected = ig.check_pair(s, pid, corners_fraction=shifted)

    assert corrected["alignment"]["valid"] and corrected["alignment"]["method"] == "manual"
    assert np.allclose(corrected["alignment"]["work_corners_fraction"], shifted, atol=.002)
    assert corrected["alignment"]["image_to_mm"] != first["alignment"]["image_to_mm"]
    repeated = ig.check_pair(s, pid)
    assert repeated["alignment"]["method"] == "manual"
    assert np.allclose(repeated["alignment"]["image_to_mm"], corrected["alignment"]["image_to_mm"])


def test_cleaning_overlay_reaches_the_full_lightburn_rectangle(world):
    s = world["store"]
    pid = make_pair(world)
    report = ig.check_pair(s, pid)
    clean = next(layer for layer in lb.parse_bytes(world["lbrn"]).layers
                 if layer.name.startswith("CLEAN-CROSSHATCH-"))
    full = np.asarray(clean.regions[0].polygon, np.float32)
    projected = cv2.perspectiveTransform(full[None],
                                         np.linalg.inv(np.asarray(report["alignment"]["image_to_mm"])))[0]
    overlay = cv2.imdecode(np.frombuffer(ig.overlay_png(s, pid, corrected=False, layer_index=clean.index), np.uint8),
                           cv2.IMREAD_COLOR)
    scale = overlay.shape[1] / report["image_size"][0]
    red = (overlay[:, :, 2] > 180) & (overlay[:, :, 1] < 150) & (overlay[:, :, 0] < 150)
    for a, b in zip(projected, np.roll(projected, -1, axis=0)):
        x, y = np.rint((a + b) * .5 * scale).astype(int)
        assert red[max(0, y-4):y+5, max(0, x-4):x+5].any()


def test_partial_marker_masks_keep_boolean_indexing_and_photo_visibility():
    polygon = [(10, 10), (20, 10), (20, 20), (10, 20)]
    alignment = {"marker_feature_adjustments": {"aruco:1": {
        "bounds_mm": [10, 10, 20, 20],
        "pixel_transform": [[1, 0, 30], [0, 1, -3], [0, 0, 1]],
    }}, "visible_right_surface_edge": [[0, 55], [69, 55]]}
    mask = ig._marker_polygons_mask([polygon], np.eye(3), (70, 70), alignment,
                                    edge_fraction=0.0)

    assert mask.dtype == np.bool_
    assert mask[12, 45]
    assert not mask[12, 15]
    visible = ig._visible_surface_mask((70, 70), alignment)
    assert visible[12, 54] and not visible[12, 55]


def test_farthest_pair_agrees_with_the_plain_double_loop_also_on_ties():
    def brute(pts):
        return max(((np.linalg.norm(pts[j] - pts[i]), i, j) for i in range(len(pts)) for j in range(i + 1, len(pts))), default=None)

    rng = np.random.default_rng(7)
    for pts in (rng.normal(size=(60, 2)).astype(np.float32) * 10, rng.integers(0, 6, (40, 2)).astype(np.float32),
                np.float32([[0, 0], [10, 0], [10, 10], [0, 10]]), np.float32([[0, 0], [3, 4]]),
                np.float32([[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [5, 0], [6, 0], [7, 0], [8, 0], [9, 0]])):
        got, want = ig._farthest_pair(pts), brute(pts)
        assert got[0] == pytest.approx(want[0], rel=1e-6)
        assert np.linalg.norm(pts[got[2]] - pts[got[1]]) == pytest.approx(want[0], rel=1e-6)
    assert ig._farthest_pair(np.float32([[1, 1]])) is None


def test_a_path_of_many_flattened_points_is_measured_quickly():
    import time
    theta = np.linspace(0, 2 * np.pi, 4000, endpoint=False)
    layer = SimpleNamespace(regions=[SimpleNamespace(kind="path", polygon=list(zip(20 + 15 * np.cos(theta), 20 + 15 * np.sin(theta))))])
    started = time.time()
    ig._line_metrics(np.full((200, 200, 3), .5, np.float32), np.diag([0.25, 0.25, 1.0]), layer)
    assert time.time() - started < 2
