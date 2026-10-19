"""REQ-012: an exported layer carries its knowledge recipe in full, so LightBurn engraves what was measured."""
import pytest

import obs
import recipes
from test_continuous import gradient_png
from titanium_platform import conversion as cv, knowledge as kn, lightburn as lb, model, plans as pl, setup as su

LABS = {"Gold fill": (70.0, 5.0, 40.0), "Outline": (30.0, 0.0, 0.0), "Offset": (45.0, 10.0, -35.0)}


@pytest.fixture
def w(store):
    w = obs.setup(store)
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=6.0, variance_threshold=5.0)
    su.save_rules(store, *w["setup"], criteria_agreed=True)
    w["recipes"] = recipes.recipes(w["device"]["passport"])
    for name, params in w["recipes"].items():
        recipes.add(store, w, params, LABS[name])
    kn.refresh(store, *w["setup"])
    w["entries"] = {e["mode"]: e for e in cv.eligible_palette(store, *w["setup"], modes=None)}     # Scan, Cut, OffsetFill
    return w


def read_back(data: bytes, passport: dict) -> dict[int, lb.Layer]:
    return {layer.index: layer for layer in lb.parse_bytes(data).layers}


def key_of(layer: lb.Layer, passport: dict) -> str:
    return model.parameters_key(recipes.parameters(layer, passport))


def test_the_recipes_become_validated_entries_with_their_lightburn_modes(store, w):
    assert {e["mode"] for e in w["entries"].values()} == {"Scan", "Cut", "OffsetFill"}
    assert all(e["stage"] == "validated" and "|lb:" in e["key"] for e in w["entries"].values())   # every key holds the preserved settings


def test_every_exported_layer_reads_back_with_the_recipe_key_of_its_knowledge_entry(store, w):
    entries = list(w["entries"].values())
    plan = {"mode": pl.MODE_DISCRETE, "markers": None,
            "layers": [cv.layer_from_entry(i, f"K{e['id']}", e, [{"x": 6 * i, "y": 0, "width": 5, "height": 5}]) for i, e in enumerate(entries, start=1)]}
    layers = read_back(pl.export_lbrn2(plan), w["device"]["passport"])
    for i, e in enumerate(entries, start=1):
        layer = layers[i]
        assert key_of(layer, w["device"]["passport"]) == model.parameters_key(e["parameters"]) == e["key"]
        assert layer.layer_type == e["mode"] and layer.source_settings["priority"] == {"Value": str(i)}   # the run order is the job's (DEC-051)
    scan = layers[entries.index(next(e for e in entries if e["mode"] == "Scan")) + 1]
    assert (scan.cross_hatch, scan.scan_angle, scan.angle_increment, scan.passes) == (True, 45.0, 10.0, 2)
    assert scan.source_settings["SubLayer"]["speed"] == {"Value": "2000"} and scan.source_settings["floodFill"] == {"Value": "1"}
    offset = layers[entries.index(next(e for e in entries if e["mode"] == "OffsetFill")) + 1]
    assert offset.bidirectional is False and "maxPower2" not in offset.source_settings      # nothing the recipe lacked is added
    line = layers[entries.index(next(e for e in entries if e["mode"] == "Cut")) + 1]
    assert line.source_settings["wobbleEnable"] == {"Value": "1"} and line.line_interval == 0.05


def test_a_photo_plan_made_from_the_recipes_exports_them_unchanged(store, w):
    path = [w["entries"]["Scan"]["id"], w["entries"]["OffsetFill"]["id"]]
    pid = cv.create_continuous(store, *w["setup"], "color_path", gradient_png(), 40, 4, "Path", path_ids=path)
    plan = pl.get_plan(store, pid)
    layers = read_back(pl.export_lbrn2(plan), w["device"]["passport"])
    by_id = {e["id"]: e for e in w["entries"].values()}
    assert len(layers) == 4
    for planned in plan["layers"]:
        assert key_of(layers[planned["index"]], w["device"]["passport"]) == by_id[planned["knowledge_id"]]["key"]


def test_a_line_recipe_never_fills_the_area_of_a_conversion(store, w):
    modes = {e["mode"] for e in cv.eligible_palette(store, *w["setup"])}
    assert modes == {"Scan", "OffsetFill"}
    with pytest.raises(cv.ConversionError, match="not eligible"):
        cv.preview_continuous(store, *w["setup"], "color_path", gradient_png(), 40, 4, path_ids=[w["entries"]["Cut"]["id"], w["entries"]["Scan"]["id"]])


def test_a_recipe_measured_on_an_image_layer_is_refused_for_vector_shapes(store, w):
    params = dict(w["entries"]["Scan"]["parameters"], layer_type="Image")
    plan = {"markers": None, "layers": [{"index": 1, "name": "K9", "parameters": params, "regions": [{"x": 0, "y": 0, "width": 5, "height": 5}]}]}
    with pytest.raises(su.ValidationError, match="image layer"):
        pl.export_lbrn2(plan)


def test_a_plan_without_recorded_lightburn_settings_is_exported_as_before(store):
    plan = {"markers": None, "layers": [{"index": 1, "name": "B01", "regions": [{"x": 0, "y": 0, "width": 5, "height": 5}],
                                         "parameters": {"power": 20, "frequency": 40, "speed": 900, "pulse_width": 200, "line_interval": 0.025, "passes": 1}}]}
    layer = lb.parse_bytes(pl.export_lbrn2(plan)).layers[0]
    assert (layer.layer_type, layer.cross_hatch, layer.bidirectional, layer.power, layer.line_interval) == ("Scan", False, True, 20, 0.025)


def test_a_plan_that_cleans_first_puts_the_cleaning_on_c00_and_the_markers_on_c01(store, w):
    pl.save_marker_layer_settings(store, 20, 60, 300)
    e = w["entries"]["Scan"]
    plan = {"mode": pl.MODE_VECTOR, "plan_identifier": "TCE-A-12345678", "size_mm": {"width": 10, "height": 8},
            "markers": pl.marker_geometry("TCE-A-12345678", 10, 8), "markers_enabled": True, "marker_layer": pl.marker_layer_settings(store),
            "clean_layer": pl.clean_layer(w["device"]["passport"]),
            "layers": [cv.layer_from_entry(2, "K1", e, [{"x": 0, "y": 0, "width": 5, "height": 5}])]}
    project = lb.parse_bytes(pl.export_lbrn2(plan))
    layers = {layer.index: layer for layer in project.layers}
    assert sorted(layers) == [0, 1, 2] and layers[0].name.startswith("CLEAN-CROSSHATCH-") and layers[1].name == "Markers"
    assert layers[0].cross_hatch and layers[0].source_settings["priority"] == {"Value": "0"}            # the cleaning runs first
    clean = layers[0].regions[0]
    ext = plan["markers"]["extent"]
    assert (clean.width, clean.height) == (pytest.approx(ext["max_x"] - ext["min_x"]), pytest.approx(ext["max_y"] - ext["min_y"]))
    assert project.identifier == "TCE-A-12345678"
    plan["layers"][0]["index"] = 1                       # a plan's own layer may not take the colour of its markers
    with pytest.raises(su.ValidationError, match="overlap"):
        pl.export_lbrn2(plan)
