"""A layer's Show and Output switches are the job's, not the recipe's (DEC-119, BUG-004): the same settings measured on a hidden layer
are the recipe measured on a shown one, a job writes its layers shown and engraved, and ``tools/forget_layer_switches.py`` moves the
colours the works chose to the names their recipes have now."""
import importlib.util
import json
from pathlib import Path

import pytest

import obs
import recipes
from titanium_platform import lightburn as lb, model, palette, plans as pl, setup as su
from titanium_platform.db import now

ROOT = Path(__file__).resolve().parents[1]
SWITCHES = {"hide": {"Value": "1"}, "doOutput": {"Value": "0"}}


def load_tool():
    spec = importlib.util.spec_from_file_location("forget_layer_switches", ROOT / "tools" / "forget_layer_switches.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def w(store):
    w = obs.setup(store)
    w["ti"] = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")["id"]
    w["shown"] = recipes.recipes(w["device"]["passport"])["Gold fill"]
    w["hidden"] = dict(w["shown"], source_settings={**w["shown"]["source_settings"], "hide": {"Value": "1"}})   # stored by 0.25.1
    return w


def ids(store, w) -> list[str]:
    return [e["id"] for e in palette.vector_palette(store, *w["setup"], w["ti"])["entries"]]


def test_the_show_and_output_switches_are_not_part_of_a_recipe_or_its_key(w):
    with_switches = dict(w["shown"], source_settings={**w["shown"]["source_settings"], **SWITCHES})
    assert model.parameters_key(with_switches) == model.parameters_key(w["hidden"]) == model.parameters_key(w["shown"])
    assert model._parameters_key(w["hidden"], ()) != model.parameters_key(w["shown"])                # as 0.25.1 keyed it
    settings = {**SWITCHES, "priority": {"Value": "2"}, "floodFill": {"Value": "1"}}
    assert lb.recipe_settings(settings) == {"floodFill": {"Value": "1"}}                             # what a new observation stores


def test_a_recipe_measured_on_a_hidden_layer_is_exported_shown_and_engraved_with_its_key(w):
    measured = dict(w["shown"], source_settings={**w["shown"]["source_settings"], **SWITCHES})
    plan = {"markers": None, "layers": [{"index": 1, "name": "K1", "parameters": measured, "regions": [{"x": 0, "y": 0, "width": 5, "height": 5}]}]}
    layer = lb.parse_bytes(pl.export_lbrn2(plan)).layers[0]
    assert not layer.hidden and not layer.output_off and not set(SWITCHES) & set(layer.source_settings)
    assert layer.source_settings["floodFill"] == {"Value": "1"}                                       # the rest of the recipe is kept
    assert model.parameters_key(recipes.parameters(layer, w["device"]["passport"])) == model.parameters_key(measured)


def test_the_same_settings_measured_on_a_hidden_and_a_shown_layer_are_one_colour_of_the_palette(store, w):
    recipes.add(store, w, w["shown"], (60.0, 5.0, 20.0), material_id=w["ti"])
    recipes.add(store, w, w["hidden"], (61.0, 5.0, 20.0), material_id=w["ti"])
    entries = palette.vector_palette(store, *w["setup"], w["ti"])["entries"]
    assert len(entries) == 1 and entries[0]["engravings"] == 4 and entries[0]["lab"] == pytest.approx([60.5, 5.0, 20.0])


# -- the works' colours move to the recipes' new names ----------------------------------------------------------------------------
@pytest.fixture
def moved(store, w):
    """A shown and a hidden recipe of 0.25.1 with their two palette ids then, and a work that chose both."""
    recipes.add(store, w, w["shown"], (60.0, 5.0, 20.0), material_id=w["ti"])
    recipes.add(store, w, w["hidden"], (61.0, 5.0, 20.0), material_id=w["ti"])
    tool = load_tool()
    with tool.keys_of_0_25_1():
        before = ids(store, w)
    assert len(before) == 2 and len(ids(store, w)) == 1
    shown, hidden = sorted(before, key=lambda i: i != ids(store, w)[0])                                 # the shown one keeps its id
    data = {"material_id": w["ti"], "colouring": {"assignment": {"r1": hidden, "r2": shown}, "regions": {"r3": hidden}},
            "undo": [{"colouring": {"assignment": {"r1": shown}}}], "layers": [{"entry_id": hidden, "layer_keys": ["e" + hidden]}]}
    work = store.execute("INSERT INTO plan(name,mode,status,device_id,lens_id,markers,data_json,created_at) VALUES ('Portrait','Vector job','Draft',?,?,0,?,?)",
                         (*w["setup"], json.dumps(data), now())).lastrowid
    return {"tool": tool, "shown": shown, "hidden": hidden, "work": work, "data": data}


def stored(store, work: int) -> dict:
    return json.loads(store.one("SELECT data_json FROM plan WHERE id=?", (work,))["data_json"])


def test_the_tool_moves_a_colour_measured_on_a_hidden_layer_to_its_recipe_after_a_dry_run_that_changes_nothing(store, moved, capsys):
    tool, shown, hidden = moved["tool"], moved["shown"], moved["hidden"]
    assert tool.main(["--data-dir", str(store.data_dir)]) == 0
    assert f"{hidden} -> {shown} (4x)" in capsys.readouterr().out and stored(store, moved["work"]) == moved["data"]   # a dry run
    assert tool.main(["--data-dir", str(store.data_dir), "--apply"]) == 0
    assert stored(store, moved["work"]) == {"material_id": moved["data"]["material_id"],
                                            "colouring": {"assignment": {"r1": shown, "r2": shown}, "regions": {"r3": shown}},
                                            "undo": [{"colouring": {"assignment": {"r1": shown}}}], "layers": [{"entry_id": shown, "layer_keys": ["e" + shown]}]}
    assert len(list((store.data_dir / "backups").glob("titanium-before-forget-layer-switches-*.sqlite"))) == 1
    audit = store.one("SELECT detail_json FROM audit WHERE action='layer_switches_forgotten'")
    assert json.loads(audit["detail_json"]) == {"works": {str(moved["work"]): {hidden: shown}}}
    capsys.readouterr()
    assert tool.main(["--data-dir", str(store.data_dir)]) == 0 and "no work keeps a colour whose id changed" in capsys.readouterr().out


def test_the_tool_refuses_and_changes_nothing_when_a_work_keeps_an_old_id_in_a_form_it_does_not_rename(store, moved, capsys):
    data = {**moved["data"], "note": f"chosen {moved['hidden']} by hand"}
    store.execute("UPDATE plan SET data_json=? WHERE id=?", (json.dumps(data), moved["work"]))
    assert moved["tool"].main(["--data-dir", str(store.data_dir), "--apply"]) == 2
    assert "would still keep" in capsys.readouterr().err and stored(store, moved["work"]) == data
    assert not (store.data_dir / "backups").exists()
