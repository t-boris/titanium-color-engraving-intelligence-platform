"""A file the operator scaled or moved in LightBurn to the plate at hand, markers and cleaning rectangle included, is measured where it was
engraved (BUG-006): the photograph is aligned to the file's own markers, the file's shapes are measured as they are, and the operator is
told the file's size against the export. A plate of another size is still refused."""
import copy
import json
import re

import cv2
import numpy as np
import pytest

import obs
import synth
from titanium_platform import color, ingest as ig, plans as pl, setup as su
from titanium_platform.db import now

RED, BLUE, GREEN = (200, 40, 40), (30, 40, 200), (40, 150, 70)
COLOURS = {"C02 red": RED, "C03 blue": BLUE, "C04 green": GREEN}
SCALE, MOVE = (0.89, 0.85), (7.0, 12.0)


def png(img) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def lab(rgb):
    return [float(v) for v in color.srgb8_to_lab(np.array(rgb, float))]


def scaled(plan: dict, sx: float, sy: float) -> dict:
    """The plan with every shape, marker and its extent scaled about the origin, as LightBurn scales a whole file."""
    out = copy.deepcopy(plan)
    rect = lambda r: r.update(x=sx * r["x"], y=sy * r["y"], width=sx * r["width"], height=sy * r["height"])
    for layer in out["layers"]:
        for r in layer["regions"]:
            rect(r)
    m = out["markers"]
    for a in m["aruco"]:
        a.update(x=sx * a["x"], y=sy * a["y"], size=sx * a["size"])
        for r in a["rects"]:
            rect(r)
    m["qr"].update(x=sx * m["qr"]["x"], y=sy * m["qr"]["y"], size=sx * m["qr"]["size"])
    for r in m["qr"]["rects"]:
        rect(r)
    e = m["extent"]
    m["extent"] = {"min_x": sx * e["min_x"], "min_y": sy * e["min_y"], "max_x": sx * e["max_x"], "max_y": sy * e["max_y"]}
    return out


def moved(lightburn: bytes, mx: float, my: float) -> bytes:
    """The file with every shape moved by (mx, my) mm, as LightBurn moves a whole job on its bed."""
    def shift(match):
        a, b, c, d, e, f = match.groups()
        return f"<XForm>{a} {b} {c} {d} {float(e) + mx:.5f} {float(f) + my:.5f}</XForm>"
    return re.sub(r"<XForm>(\S+) (\S+) (\S+) (\S+) (\S+) (\S+)</XForm>", shift, lightburn.decode()).encode()


@pytest.fixture
def work(store, tmp_path):
    """A vector work of three rectangles on a 120 x 100 mm plan with markers, its export recorded."""
    w = obs.setup(store)
    store.set_setting("allow_non_raw_photos", True)
    pl.save_marker_layer_settings(store, 20, 60, 300)
    w["ti"] = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")["id"]
    boxes = {"C02 red": [(10, 10, 30, 20), (70, 60, 25, 25)], "C03 blue": [(50, 15, 40, 30), (15, 55, 20, 35)], "C04 green": [(80, 5, 35, 45)]}
    layers = [{"index": i + 2, "name": name, "parameters": su.parameter_vector(w["device"]["passport"], 20 + 10 * i, 60, 500, 200, 0.025, 1),
               "regions": [{"x": x, "y": y, "width": bw, "height": bh} for x, y, bw, bh in boxes[name]]} for i, name in enumerate(COLOURS)]
    plan = {"mode": pl.MODE_VECTOR, "plan_identifier": "TCE-A-5CA1ED01", "size_mm": {"width": 120, "height": 100},
            "markers": pl.marker_geometry("TCE-A-5CA1ED01", 120, 100), "marker_layer": pl.marker_layer_settings(store),
            "clean_layer": pl.clean_layer(w["device"]["passport"]), "layers": layers}
    export = tmp_path / "export.lbrn2"
    export.write_bytes(pl.export_lbrn2({**plan, "markers_enabled": True}))
    plan["exports"] = [{"number": 1, "name": "Work.lbrn2", "path": str(export), "at": now()}]
    w["plan"] = plan
    w["plan_id"] = store.execute("INSERT INTO plan(name,mode,status,device_id,lens_id,markers,plan_identifier,data_json,created_at) "
                                 "VALUES ('Work','Vector job','Exported',?,?,1,?,?,?)", (*w["setup"], plan["plan_identifier"], json.dumps(plan), now())).lastrowid
    return w


def checked(store, w, engraved: bytes, photographed: dict) -> dict:
    pid = ig.create_pair(store, device_id=w["setup"][0], lens_id=w["setup"][1], stand_id=w["stand"]["id"], lightburn_name="engraved.lbrn2",
                         lightburn_bytes=engraved, photo_name="plate.png", plan_id=w["plan_id"], context={"material_id": w["ti"]},
                         photo_bytes=png(synth.plate_photo({**photographed, "markers_enabled": True}, COLOURS, scale=12.0, size=(1900, 2400))))
    return ig.check_pair(store, pid)


def measured(check: dict) -> dict:
    return {rep["name"]: rep["measured_lab"] for rep in check["layers"] if rep["name"] in COLOURS}


def test_a_file_scaled_and_moved_to_the_plate_is_aligned_to_its_own_markers_and_measured_on_its_shapes(store, work):
    plan = {**work["plan"], "markers_enabled": True}
    small = scaled(plan, *SCALE)
    check = checked(store, work, moved(pl.export_lbrn2(small), *MOVE), small)        # engraved and photographed at 89% x 85%
    assert check["problems"] == [] and check["alignment"]["valid"]
    ext = plan["markers"]["extent"]
    assert check["alignment"]["file_placement"] == {"scale": [pytest.approx(SCALE[0], abs=.002), pytest.approx(SCALE[1], abs=.002)],
                                                    "offset_mm": [pytest.approx(MOVE[0] - ext["min_x"], abs=.01), pytest.approx(MOVE[1] - ext["min_y"], abs=.01)]}
    assert check["alignment"]["file_offset_mm"] == check["alignment"]["file_placement"]["offset_mm"]
    assert ("the file is 89% by 85% of the export: the photograph is aligned to the file's own markers and the engraving is measured at that size"
            in check["warnings"])
    assert check["alignment"]["vector_found"] == check["alignment"]["vector_total"] == 5
    for name, rgb in COLOURS.items():
        assert measured(check)[name] == pytest.approx(lab(rgb), abs=4), name          # sampled on the shapes, not beside them


def test_a_file_at_the_exports_size_only_moved_on_the_bed_is_measured_without_a_word_about_its_size(store, work):
    plan = {**work["plan"], "markers_enabled": True}
    check = checked(store, work, moved(pl.export_lbrn2(plan), *MOVE), plan)
    assert check["problems"] == [] and check["alignment"]["valid"]
    ext = plan["markers"]["extent"]
    assert check["alignment"]["file_placement"] == {"scale": [1, 1], "offset_mm": [pytest.approx(MOVE[0] - ext["min_x"], abs=.01), pytest.approx(MOVE[1] - ext["min_y"], abs=.01)]}
    assert not any("of the export" in warning for warning in check["warnings"])
    assert check["alignment"]["vector_found"] == check["alignment"]["vector_total"] == 5
    for name, rgb in COLOURS.items():
        assert measured(check)[name] == pytest.approx(lab(rgb), abs=4), name


def test_the_scaled_markers_keep_the_plans_export_offset_and_get_a_height_of_their_own(work):
    plan = {**work["plan"], "markers_enabled": True}
    small = scaled(plan, *SCALE)
    project = __import__("titanium_platform.lightburn", fromlist=["x"]).parse_bytes(pl.export_lbrn2(small))
    as_engraved, placement = ig._plan_as_engraved(plan, None, [layer for layer in project.layers if layer.regions])
    assert placement["scale"] == [pytest.approx(SCALE[0], abs=.002), pytest.approx(SCALE[1], abs=.002)]
    assert pl.export_offset(as_engraved) == pl.export_offset(plan)
    a, b = plan["markers"]["aruco"][1], as_engraved["markers"]["aruco"][1]
    ext = plan["markers"]["extent"]
    assert (b["size"], b["height"]) == (pytest.approx(SCALE[0] * a["size"], abs=.01), pytest.approx(SCALE[1] * a["size"], abs=.01))
    assert b["x"] == pytest.approx(ext["min_x"] + SCALE[0] * (a["x"] - ext["min_x"]), abs=.01) and len(b["rects"]) == len(a["rects"])
    same, none = ig._plan_as_engraved(plan, None, [layer for layer in project.layers if not layer.name.startswith("CLEAN")])
    assert same is plan and none is None                                                  # nothing says the size: the plan as it is


def test_a_plate_of_another_size_is_still_refused(store, tmp_path):
    w = obs.setup(store)
    store.set_setting("allow_non_raw_photos", True)
    pl.save_marker_layer_settings(store, 20, 60, 300)
    ti = su.save_material(store, "Grade 2 sheet", grade="Grade 2")["id"]
    made = pl.create_plate_series(store, w["device"]["id"], "20,40", "100", "800", 5, 4, 1, pulse_width=200, line_interval=0.025, passes=1)
    plan = pl.get_plan(store, made[0]["plan_id"])
    cells = json.loads(store.one("SELECT cells_json FROM plate WHERE id=?", (plan["plate_id"],))["cells_json"])
    small = scaled(plan, *SCALE)
    pid = ig.create_pair(store, device_id=w["setup"][0], lens_id=w["setup"][1], stand_id=w["stand"]["id"], lightburn_name="plate.lbrn2",
                         lightburn_bytes=pl.export_lbrn2(small), photo_name="plate.png", plan_id=plan["id"], context={"material_id": ti},
                         photo_bytes=png(synth.plate_photo(small, {c["id"]: RED for c in cells})))
    check = ig.check_pair(store, pid)
    assert any("cleaning rectangle size differs from the plate definition" in p for p in check["problems"])
