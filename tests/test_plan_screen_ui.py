"""The engraving plan of a vector work lists its photo zones (REQ-073, 0.22.2): each zone's Image layer after the colour layers, with its
kind, powers, settings, picture and regions, or why it cannot be engraved. Run in node over the small DOM of the other screen tests, with
answers shaped like the server's."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
CSS = (UI / "styles.css").read_text(encoding="utf-8")

GLUE = ("const __screens = {}, __renders = []; App.register = (d) => { __screens[d.id] = d; }; App.render = () => { __renders.push(1); };"
        "globalThis.__screens = __screens; globalThis.__renders = __renders;")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'photo-modes.js', 'photo-quality.js', {code: %(glue)s}, 'screens/photo-form.js', 'screens/vector-photo.js',
  'screens/plan.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
(async () => {
  const out = {};
  const tree = await ctx.__screens.plan.render({arg: '22', query: {}});
  await tick(); await tick();
  const card = tree.querySelectorAll('div').find((d) => (d.querySelector('h3') || {}).textContent === 'Слои и параметры');
  out.rows = card.querySelectorAll('tr').slice(1).map((tr) => tr.querySelectorAll('td').map((td) => td.textContent));
  out.pictures = card.querySelectorAll('img').map((im) => [im.getAttribute('src'), im.getAttribute('alt'), im.className]);
  out.export = tree.querySelectorAll('button').find((b) => b.textContent === 'Экспортировать в LightBurn').disabled;
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""

SETTINGS = {"speed": 150.0, "frequency": 60.0, "pulse_width": 350.0, "line_interval": 0.0212, "passes": 1, "global_passes": 1,
            "layer_type": "Image"}


def zone(number, index, kind, parameters, problem=None, regions=("r1", "r2"), **greys):
    name = None if parameters is None else f"C{index:02d} Photo {number} {kind} P{parameters['power']:g}"
    greys = {"by_colour": False, "colour_choice": "drawing", "contours": False, "rules": [], **greys}
    return {"number": number, "index": index, "kind": kind, "regions": list(regions), "name": name, "problem": problem, "parameters": parameters, **greys,
            "picture": None if problem else f"/api/vector/22/photo/{number}.png?v=k{number}", "width_mm": 50.0, "area_mm2": 2109.0}


def plan(zones, layers=True):
    layer = {"index": 2, "name": "C02 P50-F1950-V1800-I0.01", "cut_type": "Scan", "region_ids": ["r9"], "prediction": None, "stage": None,
             "parameters": {"power": 50.0, "frequency": 1950.0, "speed": 1800.0, "pulse_width": 2.0, "line_interval": 0.01, "passes": 1}}
    return {"id": 22, "name": "Inna + Boris", "mode": "Vector job", "status": "Ready to export", "strategy": "photo", "markers_enabled": True,
            "layers": [layer] if layers else [], "photo_zones": zones, "active_pairs": 0, "device_id": 1, "lens_id": 2, "plan_identifier": "TCE-A-22",
            "size_mm": {"width": 150.0, "height": 143.0}, "warnings": [], "exports": [], "experiment": None}


def run(tmp_path, body) -> dict:
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"routes": {"/api/plans/22": {"status": 200, "json": body}}}), encoding="utf-8")
    script = tmp_path / "run.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(data)), "ui": json.dumps(str(UI) + "/"),
                                 "tables": json.dumps(TABLES), "glue": json.dumps(GLUE)}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@node
def test_the_plan_of_a_vector_work_lists_each_photo_zone_as_its_image_layer_after_the_colours(tmp_path):
    out = run(tmp_path, plan([zone(1, 3, "grayscale", {**SETTINGS, "min_power": 2.0, "power": 29.0}, by_colour=True, colour_choice="nearest", contours=True),
                              zone(2, 4, "jarvis", {**SETTINGS, "min_power": 20.0, "power": 20.0}, regions=("r4",), by_colour=True),
                              zone(3, 5, "grayscale", None, problem="the width of the picture must be 1..1000 mm")]))
    assert [r[0] for r in out["rows"]] == ["C02 P50-F1950-V1800-I0.01", "C03 Photo 1 grayscale P29Фотозона 1 · Градации серого",
                                           "C04 Photo 2 jarvis P20Фотозона 2 · Джарвис", "Фотозона 3Фотозона 3 · Градации серого"]
    gray, dots, bad = out["rows"][1:]
    assert gray[1].startswith("Min 2.0 % – Max 29.0 % · 60.0 кГц · 150 мм/с · Q-Pulse 350 нс · шаг строк 0.0212 мм · 1 проход(а)")
    assert gray[1].endswith("Изображение (Image), режим «Градации серого»: картинка работы в областях зоны, вне зоны прозрачна; "
                            "серые подобраны под цвета: ближайший цвет · контуры")                      # how its greys are chosen (0.23.0)
    assert dots[1].startswith("точки 20.0 % · 60.0 кГц") and dots[1].endswith("режим «Джарвис»: картинка работы в областях зоны, вне зоны прозрачна")
    assert bad[1] == "Ширина картинки должна быть от 1 до 1000 мм" and bad[2] == "—"            # the server's reason, translated
    assert [gray[-1], dots[-1], bad[-1]] == ["2", "1", "2"] and gray[3:7] == ["—"] * 4
    assert out["pictures"] == [["/api/vector/22/photo/1.png?v=k1", "Фотозона 1", "plan-zone-pic"], ["/api/vector/22/photo/2.png?v=k2", "Фотозона 2", "plan-zone-pic"]]
    assert out["export"] is False
    assert ".plan-zone-pic {" in CSS


@node
def test_a_work_engraved_only_as_photo_zones_still_has_its_layers_and_its_export(tmp_path):
    out = run(tmp_path, plan([zone(1, 2, "grayscale", {**SETTINGS, "min_power": 2.0, "power": 29.0})], layers=False))
    assert [r[0] for r in out["rows"]] == ["C02 Photo 1 grayscale P29Фотозона 1 · Градации серого"] and out["export"] is False
