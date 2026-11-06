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
SCRIPTS = ["app.js", "photo-modes.js", "photo-quality.js", "dialogs.js", "list.js", "hardware.js", "filepick.js", "screens/material-picker.js"]
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
const named = (tree, label) => tree.querySelectorAll('label').find((l) => l.firstChild && l.firstChild.textContent === label);
const select = (tree, label) => tree.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === label) || (named(tree, label) ? named(tree, label).firstControl() : undefined);
const stock = (tree) => tree.querySelectorAll('.matpick').find((p) => p.getAttribute('aria-label') === 'Stock');       // the titanium is the stock selector, no longer a drop-down
const posted = () => ctx.requests.filter((r) => r.path === '/api/predictions/photo')
  .map((r) => Object.fromEntries(r.body.fields.map(([k, v]) => [k, v && typeof v === 'object' ? v.name : String(v)])));
(async () => {
  const out = {};
  const tree = await ctx.__screens['photo-preview'].render({query: %(query)s});
  await settle();
  out.opened = {titanium: stock(tree).value, laser: select(tree, 'Laser').value, lens: select(tree, 'Lens').value,
                note: tree.textContent.includes('Work file “Inna Portrait-P1-17.lbrn2” is already selected'),
                says: tree.textContent.includes('This mode was measured here:Big Plate 150 · Grade 5 · 3 mm · JPT M7 · F-Theta · 174 mm')};
  stock(tree).value = '3';
  tree.querySelectorAll('button').find((b) => b.textContent === 'Show prediction').dispatch('click'); await settle();
  tree.querySelectorAll('button').find((b) => b.textContent === 'Show using this setup').dispatch('click'); await settle();
  out.posted = posted().map((p) => [p.material_id, p.device_id, p.lens_id, p.lightburn]);
  out.titanium = stock(tree).value;
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""
REFUSED = {"cache_id": None, "file": "Inna Portrait-P1-17.lbrn2", "device_id": 1, "lens_id": 2, "material_id": 2,
           "layers": [{"index": 1, "name": "C01", "dither": "grayscale", "settings": {"overridden": []},
                       "refused": "no colour has been measured at this mode: there is nothing to predict from",
                       "measured_on": [{"device_id": 1, "lens_id": 2, "material_id": 2}]}]}
WORK = {"id": 7, "name": "Inna Portrait", "min_power": 1, "max_power": 17,
        "scale": {"device_id": 1, "lens_id": 2, "material_id": 2, "speed": 150, "frequency": 60, "pulse_width": 350, "line_interval": 0.0254}}


def run(tmp_path, query, body=None):
    routes = {"/api/devices": {"status": 200, "json": [{"id": 1, "title": "JPT M7", "lens": {"id": 2}}]},
              "/api/lenses": {"status": 200, "json": [{"id": 2, "name": "F-Theta", "focal_length_mm": 174}]},
              "/api/materials": {"status": 200, "json": [{"id": 2, "name": "Big Plate 150", "grade": "Grade 5", "thickness_mm": 3},
                                                         {"id": 3, "name": "Small Plate", "grade": "Grade 5", "thickness_mm": 2}]},
              "/api/materials/2": {"status": 200, "json": {"id": 2, "name": "Big Plate 150", "grade": "Grade 5", "thickness_mm": 3}},
              "/api/materials/3": {"status": 200, "json": {"id": 3, "name": "Small Plate", "grade": "Grade 5", "thickness_mm": 2}},
              "/api/photo-works": {"status": 200, "json": [WORK]},
              "/api/photo-works/7/export.lbrn2": {"status": 200, "text": "<LightBurnProject/>", "type": "application/octet-stream"},
              "/api/predictions/photo": {"status": 200, "json": REFUSED}}
    script = tmp_path / "screen.js"
    harness = HARNESS if body is None else HARNESS[:HARNESS.index("(async () => {")] + body
    script.write_text(harness % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "routes": json.dumps(routes),
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


@node
def test_previous_result_survives_failures_and_late_responses(tmp_path):
    body = r"""
const original = ctx.fetch;
const pending = [];
let delayed = false;
ctx.fetch = (url, opts) => {
  if (String(url) === '/api/predictions/photo' && delayed) return new Promise((resolve) => pending.push(resolve));
  return original(url, opts);
};
const response = (data, status = 200) => ({ok: status < 300, status, headers: {get: () => 'application/json'}, json: async () => data});
(async () => {
  const tree = await ctx.__screens['photo-preview'].render({query: %(query)s});
  ctx.document.body.append(tree);
  await settle();
  const button = tree.querySelectorAll('button').find((b) => b.textContent === 'Show prediction');
  const status = tree.querySelectorAll('[role]').find((e) => e.getAttribute('role') === 'status' && e.getAttribute('aria-live') === 'polite');
  const old = tree.textContent.includes('File “Inna Portrait-P1-17.lbrn2”');
  delayed = true;
  const first = button.dispatch('click'); await settle();
  const waiting = [status.textContent, tree.textContent.includes('File “Inna Portrait-P1-17.lbrn2”')];
  const second = button.dispatch('click'); await settle();
  pending[1](response({...%(refused)s, file: 'new.lbrn2'})); await second; await settle();
  pending[0](response({error: 'late failure'}, 500)); await first; await settle();
  const latest = [tree.textContent.includes('File “new.lbrn2”'), status.textContent, tree.textContent.includes('late failure')];
  const third = button.dispatch('click'); await settle();
  pending[2](response({error: 'offline'}, 500)); await third; await settle();
  console.log(JSON.stringify({old, waiting, latest, failure: [status.textContent, tree.textContent.includes('File “new.lbrn2”')]}));
})().catch((e) => { console.error(e.stack); process.exit(1); });
""".replace("%(refused)s", json.dumps(REFUSED))
    out = run(tmp_path, {"work": "7"}, body)
    assert out["old"] and out["waiting"][1] and "previous prediction" in out["waiting"][0]
    assert out["latest"] == [True, "", False]
    assert out["failure"][1] and "failed" in out["failure"][0]


@node
def test_slider_keeps_image_until_new_render_loads_and_ignores_stale_failures(tmp_path):
    layer = {"index": 1, "name": "C01", "dither": "grayscale", "settings": {"overridden": [], "min_power": 10, "max_power": 80},
             "axis": "power", "preview": "/old.png", "referenced": True, "reference": "chart", "mode": {}, "span": [0, 100],
             "curve": {"points": []}, "outside_share": 0, "notes": []}
    body = r"""
const original = ctx.fetch, pending = [], images = [];
ctx.Image = class { constructor() { images.push(this); } };
ctx.fetch = (url, opts) => {
  if (String(url) === '/api/predictions/photo') return Promise.resolve(response({cache_id: 'cache', file: 'test', layers: [%(layer)s]}));
  if (String(url).startsWith('/api/predictions/photo/cache/')) return new Promise((resolve) => pending.push(resolve));
  return original(url, opts);
};
const response = (data, code = 200) => ({ok: code < 300, status: code, headers: {get: () => 'application/json'}, json: async () => data});
(async () => {
  const tree = await ctx.__screens['photo-preview'].render({query: %(query)s}); await settle();
  const img = tree.querySelector('.pp-image');
  const range = tree.querySelectorAll('input').find((e) => e.getAttribute('type') === 'range');
  const status = () => tree.querySelectorAll('[role]').filter((e) => e.getAttribute('role') === 'status' && e.getAttribute('aria-live') === 'polite').pop().textContent;
  const initial = img.src;
  range.value = '20'; await range.dispatch('input'); await wait(300);
  range.value = '30'; await range.dispatch('input'); await wait(300);
  pending[1](response({...%(layer)s, preview: '/new.png'})); await settle();
  const beforeLoad = [img.src, status()];
  pending[0](response({error: 'late failure'}, 500)); await settle();
  const afterLate = [img.src, status()];
  images[0].onerror();
  const afterError = [img.src, status()];
  const retry = tree.querySelectorAll('button').find((b) => b.textContent === 'Retry calculation');
  await retry.dispatch('click'); await wait(300);
  pending[2](response({...%(layer)s, preview: '/new.png'})); await settle();
  images[1].onload();
  console.log(JSON.stringify({initial, beforeLoad, afterLate, afterError, final: [img.src, status()]}));
})().catch((e) => { console.error(e.stack); process.exit(1); });
""".replace("%(layer)s", json.dumps(layer))
    out = run(tmp_path, {"work": "7"}, body)
    assert out["initial"].startswith("/old.png?")
    assert out["beforeLoad"][0] == out["initial"] and "previous prediction" in out["beforeLoad"][1]
    assert out["afterLate"] == out["beforeLoad"]
    assert out["afterError"][0] == out["initial"] and "failed" in out["afterError"][1]
    assert out["final"][0].startswith("/new.png?min_power=30") and out["final"][1] == ""
