"""The findings screen («Выводы», REQ-022) and its photo engraving section (feature photo-engraving-quality REQ-003, REQ-005): on every laser
and titanium where a photo engraving was photographed, the best measured settings of each kind, what each setting does there and the plate
the laboratory proposes. Run in node over the small DOM of the other screen tests, with answers shaped like the server's."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

GLUE = ("const __screens = {}; App.register = (d) => { __screens[d.id] = d; }; App.render = () => {};"
        "globalThis.__screens = __screens; App.go = (route) => { location.hash = '#' + route; };")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'photo-modes.js', 'photo-quality.js', 'dialogs.js', {code: %(glue)s}, 'screens/findings.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
(async () => {
  const out = {};
  const tree = await ctx.__screens.findings.render({query: {}});
  await tick();
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""

JARVIS = {"dither": "jarvis", "power": 30.0, "min_power": 30.0, "speed": 125.0, "frequency": 60.0, "pulse_width": 200.0, "line_interval": 0.01,
          "passes": 1, "global_passes": 1, "dot_width": None}
EVERYWHERE = [{"device_id": 1, "lens_id": 2, "material_id": 3, "setup": "JPT M7 · F-Theta", "titanium": "Grade 5 sheet · Grade 5", "picture_from": None, "kinds": [
    {"kind": "jarvis", "status": "measured", "engravings": 2,
     "best": {"settings": JARVIS, "score": 0.62, "source": {"pair_id": 41, "layer": "C1"}},
     "effects": {"power": {"per": "doubling", "photographs": [41, 42], "mean_L": {"median": -6.0, "n": 2}, "score": {"median": -0.1, "n": 2}}},
     "proposal": {"kind": "around", "centre": JARVIS, "step": 1.0, "source": {"pair_id": 41, "layer": "C1"},
                  "copies": [[], [{"setting": "power", "from": 30.0, "to": 24.0}]], "plate": None}}]}]
ROUTES = {
    "/api/analysis/runs": {"status": 200, "json": []},
    "/api/analysis/schedule": {"status": 200, "json": {"interval_hours": 0, "next_due_at": None, "running": False}},
    "/api/application-goals": {"status": 200, "json": []},
    "/api/analysis/runs/latest": {"status": 200, "json": {"run": None, "findings": [], "total": 0,
                                                          "options": {"kinds": [], "tasks": [], "setups": [], "stocks": []}}},
    "/api/photo-knowledge/everywhere": {"status": 200, "json": EVERYWHERE},
}


def run(tmp_path, body, routes=None) -> dict:
    (tmp_path / "data.json").write_text(json.dumps({"routes": routes or ROUTES}), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


@node
def test_the_findings_say_what_each_setting_does_to_a_photo_engraving_on_every_laser_and_titanium_photographed(tmp_path):
    out = run(tmp_path, """
  const section = tree.querySelectorAll('section').find((s) => s.querySelector('h3') && s.querySelector('h3').textContent === 'Фотогравировка');
  out.heads = section.querySelectorAll('h4').map((x) => x.textContent);
  out.cards = section.querySelectorAll('article').map((a) => a.textContent);
  out.buttons = section.querySelectorAll('button').map((b) => b.textContent);
""")
    assert out["heads"] == ["JPT M7 · F-Theta · Grade 5 sheet · Grade 5"]
    jarvis, = out["cards"]
    assert jarvis.startswith("Джарвисизмерено, но не подобрано")
    assert "Лучшее: 30 %, 125 мм/с, 60 кГц, 200 нс, шаг 0,01 мм — оценка 0,62 по фото №41" in jarvis
    assert "мощность вдвое больше: темнее на 6 L*, оценка −0,1 (по фото №41, №42)" in jarvis
    assert "мощность 30 % → 24 %" in jarvis and "Картинки для платы ещё нет" in jarvis
    assert out["buttons"] == []                                   # no picture to engrave the plate from yet: nothing to press


@node
def test_without_a_photographed_photo_engraving_the_findings_have_no_photo_section(tmp_path):
    out = run(tmp_path, """
  out.photo = tree.querySelectorAll('h3').some((x) => x.textContent === 'Фотогравировка');
""", routes={**ROUTES, "/api/photo-knowledge/everywhere": {"status": 200, "json": []}})
    assert out["photo"] is False
