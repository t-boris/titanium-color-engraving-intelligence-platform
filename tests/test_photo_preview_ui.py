"""The photo engraving preview screen (REQ-030): a photo work's file opened from the work with its laser, lens and titanium, and a file
refused where its mode is not measured says where it is, with a button that switches there. Run in node over the small DOM of the other
screen tests, with fetch answered as the API does."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
SCRIPTS = ["app.js", "photo-modes.js", "dialogs.js", "hardware.js", "filepick.js"]
GLUE = ("const __screens = {}; App.register = (d) => { __screens[d.id] = d; }; App.render = () => {}; globalThis.__screens = __screens;"
        "globalThis.FormData = class { constructor() { this.fields = []; } append(k, v) { this.fields.push([k, v]); } };"
        "globalThis.File = class { constructor(parts, name) { this.parts = parts; this.name = name; this.size = 1; } };")
HARNESS = """
const {context, load} = require(%(dom)s);
const ctx = context(%(routes)s);
const make = ctx.document.createElement;
ctx.document.createElement = (t) => { const el = make(t); if (t === 'input') el.files = []; return el; };     // no file chosen, as a browser has it
load(ctx, %(ui)s, [...%(tables)s, ...%(scripts)s, {code: %(glue)s}, 'screens/photo-preview.js']);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const settle = async () => { for (let i = 0; i < 10; i++) await wait(0); };
const select = (tree, label) => tree.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === label);
const posted = () => ctx.requests.filter((r) => r.path === '/api/predictions/photo')
  .map((r) => Object.fromEntries(r.body.fields.map(([k, v]) => [k, v && typeof v === 'object' ? v.name : String(v)])));
(async () => {
  const out = {};
  const tree = await ctx.__screens['photo-preview'].render({query: %(query)s});
  await settle();
  out.opened = {titanium: select(tree, 'Титан').value, laser: select(tree, 'Лазер').value, lens: select(tree, 'Линза').value,
                note: tree.textContent.includes('Файл работы «Inna Portrait-P1-17.lbrn2» уже выбран'),
                says: tree.textContent.includes('Этот режим измерен здесь:Big Plate 150 · Grade 5 · 3 мм · JPT M7 · F-Theta · 174 мм')};
  select(tree, 'Титан').value = '3';
  tree.querySelectorAll('button').find((b) => b.textContent === 'Показать прогноз').dispatch('click'); await settle();
  tree.querySelectorAll('button').find((b) => b.textContent === 'Показать на нём').dispatch('click'); await settle();
  out.posted = posted().map((p) => [p.material_id, p.device_id, p.lens_id, p.lightburn]);
  out.titanium = select(tree, 'Титан').value;
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""
REFUSED = {"cache_id": None, "file": "Inna Portrait-P1-17.lbrn2", "device_id": 1, "lens_id": 2, "material_id": 2,
           "layers": [{"index": 1, "name": "C01", "dither": "grayscale", "settings": {"overridden": []},
                       "refused": "no colour has been measured at this mode: there is nothing to predict from",
                       "measured_on": [{"device_id": 1, "lens_id": 2, "material_id": 2}]}]}
WORK = {"id": 7, "name": "Inna Portrait", "min_power": 1, "max_power": 17,
        "scale": {"device_id": 1, "lens_id": 2, "material_id": 2, "speed": 150, "frequency": 60, "pulse_width": 350, "line_interval": 0.0254}}


def run(tmp_path, query):
    routes = {"/api/devices": {"status": 200, "json": [{"id": 1, "title": "JPT M7", "lens": {"id": 2}}]},
              "/api/lenses": {"status": 200, "json": [{"id": 2, "name": "F-Theta", "focal_length_mm": 174}]},
              "/api/materials": {"status": 200, "json": [{"id": 2, "name": "Big Plate 150", "grade": "Grade 5", "thickness_mm": 3},
                                                         {"id": 3, "name": "Small Plate", "grade": "Grade 5", "thickness_mm": 2}]},
              "/api/photo-works": {"status": 200, "json": [WORK]},
              "/api/photo-works/7/export.lbrn2": {"status": 200, "text": "<LightBurnProject/>", "type": "application/octet-stream"},
              "/api/predictions/photo": {"status": 200, "json": REFUSED}}
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "routes": json.dumps(routes),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "scripts": json.dumps(SCRIPTS), "glue": json.dumps(GLUE),
                                 "query": json.dumps(query)}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout)


@node
def test_a_photo_works_file_opens_with_its_setup_and_a_refused_file_switches_to_where_its_mode_is_measured(tmp_path):
    out = run(tmp_path, {"work": "7"})
    assert out["opened"] == {"titanium": "2", "laser": "1", "lens": "2", "note": True, "says": True}
    name = "Inna Portrait-P1-17.lbrn2"
    assert out["posted"] == [["2", "1", "2", name], ["3", "1", "2", name], ["2", "1", "2", name]]   # opened, another titanium, switched back
    assert out["titanium"] == "2"
