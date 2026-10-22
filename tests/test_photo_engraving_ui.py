"""The picture on the photo engraving screen (REQ-059): it stays when another scale is chosen and its prediction follows every change by
itself. Run in node over the small DOM of the other screen tests, with a fake server that answers as the grey-scale API does."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
SCRIPTS = ["app.js", "photo-modes.js", "dialogs.js", "hardware.js", "filepick.js"]
GLUE = ("const __screens = {}; App.register = (d) => { __screens[d.id] = d; }; App.render = () => {}; globalThis.__screens = __screens;"
        "globalThis.FormData = class { constructor() { this.fields = []; } append(k, v) { this.fields.push([k, v]); } };")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context({});
load(ctx, %(ui)s, [...%(tables)s, ...%(scripts)s, {code: %(glue)s}, 'screens/photo-engraving.js']);
const requests = [], hold = {};
const info = (id, lo, hi, width) => ({cache_id: id, preview: `/api/grey-scales/picture/${id}.png?min_power=${lo}&max_power=${hi}`, by_colour: false, colour_match: null,
  outside_share: 0, time: {seconds: 600}, size_mm: {width: +width, height: 40}, file: `/api/grey-scales/picture/${id}.lbrn2`, power_range: [+lo, +hi], dpi: 1000, notes: []});
const answer = (json) => ({ok: true, status: 200, headers: {get: (k) => (k.toLowerCase() === 'content-type' ? 'application/json' : null)}, json: async () => json});
ctx.fetch = async (url, opts = {}) => {
  const path = String(url).split('?')[0], method = opts.method || 'GET';
  const fields = opts.body && opts.body.fields ? Object.fromEntries(opts.body.fields.map(([k, v]) => [k, v && typeof v === 'object' ? v.name : String(v)])) : null;
  requests.push({path, url: String(url), method, fields});
  if (path === '/api/grey-scales') return answer({scales: data.scales});
  if (path === '/api/devices') return answer([{id: 1, lens: {id: 2}}]);
  if (path === '/api/materials') return answer([]);
  if (path === '/api/grey-scales/scale') return answer(data.scale);
  if (path === '/api/grey-scales/picture' && method === 'POST') {
    if (hold[fields.speed]) await hold[fields.speed];
    return answer(info(`pic-${fields.speed}-${fields.picture}`, fields.min_power, fields.max_power, fields.width_mm));
  }
  if (path.startsWith('/api/grey-scales/picture/')) {
    const q = new URLSearchParams(String(url).split('?')[1]);
    return answer(info(path.split('/').pop(), q.get('min_power'), q.get('max_power'), q.get('width_mm')));
  }
  return {ok: false, status: 404, headers: {get: () => 'application/json'}, json: async () => ({error: path + ' not found'})};
};
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const settle = async () => { for (let i = 0; i < 10; i++) await wait(0); };
const input = (tree, test) => tree.querySelectorAll('input').find(test);
const fileOf = (tree) => input(tree, (i) => i.getAttribute('type') === 'file');
const shown = (tree) => { const img = tree.querySelectorAll('img').find((i) => (i.className || '').includes('pp-image')); return img ? img.getAttribute('src') : null; };
const uploads = () => requests.filter((r) => r.method === 'POST').map((r) => r.fields);
const choosePicture = async (tree, name) => { const f = fileOf(tree); f.files = [{name, size: 2048}]; f.dispatch('change'); await settle(); };
(async () => {
  const out = {};
  const tree = await ctx.__screens['photo-engraving'].render({query: {}});
  await settle();
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, body):
    (tmp_path / "data.json").write_text(json.dumps({"scales": [scale(150, [1, 30]), scale(100, [2, 25])], "scale": scale_answer()}), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "scripts": json.dumps(SCRIPTS), "glue": json.dumps(GLUE),
                                 "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout)


# -- answers shaped as the server sends them ------------------------------------------------------------------------------------------
def scale(speed, span):
    return {"mode": {"device_id": 1, "lens_id": 2, "material_id": 3, "speed": speed, "frequency": 60, "pulse_width": 250, "line_interval": 0.0254,
                     "passes": 1, "global_passes": 1},
            "dpi": 1000, "span": span, "material": {"name": "Big Plate 150"}, "bar": [{"hex": "#aa8844"}, {"hex": "#3355aa"}],
            "by_kind": {"grey ramp": 1}, "time_s_per_cm2": 70, "confirmation": {"engravings": 1, "median_de": None}, "reference": "chart"}


def scale_answer():
    levels = [{"level": g, "power": 30 - g * 29 / 255, "lab": [50, 0, 0], "hex": "#777777", "spread_de": None} for g in range(256)]
    return {"greys": {"levels": levels, "measured_levels": 256}, "confirmation": {"rows": [], "tolerance_de": 5, "engravings": 1, "median_de": None},
            "fill_points": [], "curve": {"points": []}, "notes": []}


# -- the picture -----------------------------------------------------------------------------------------------------------------------
@node
def test_the_picture_stays_when_another_scale_is_chosen_and_is_predicted_on_it_by_itself(tmp_path):
    out = run(tmp_path, """
  const file = fileOf(tree);
  await choosePicture(tree, 'girl.png');
  out.chosen = {uploads: uploads(), shown: shown(tree)};
  const max = input(tree, (i) => i.getAttribute('type') === 'number' && i.getAttribute('aria-label') === 'Max мощность, % (чёрный)');
  max.value = '20'; await max.dispatch('change'); await wait(300); await settle();
  out.max = {uploads: uploads().length, shown: shown(tree)};
  await tree.querySelectorAll('button.ge-scale')[1].dispatch('click'); await settle();
  out.other = {sameFile: fileOf(tree) === file, file: fileOf(tree).files[0].name, uploads: uploads(), shown: shown(tree),
               text: tree.textContent.includes('Прогноз на титане')};
""")
    first = out["chosen"]["uploads"]
    assert [(u["speed"], u["picture"], u["min_power"], u["max_power"]) for u in first] == [("150", "girl.png", "1", "30")]   # chosen -> predicted, no button
    assert out["chosen"]["shown"].startswith("/api/grey-scales/picture/pic-150-girl.png.png?min_power=1&max_power=30")
    assert out["max"]["uploads"] == 1 and "max_power=20" in out["max"]["shown"]                                             # Max re-renders the kept upload
    other = out["other"]
    assert other["sameFile"] and other["file"] == "girl.png"                                                                  # the picture stays
    assert [(u["speed"], u["picture"], u["min_power"], u["max_power"]) for u in other["uploads"]][1:] == [("100", "girl.png", "2", "25")]
    assert other["shown"].startswith("/api/grey-scales/picture/pic-100-girl.png.png?min_power=2&max_power=25") and other["text"]


@node
def test_a_late_answer_for_the_previous_scale_does_not_replace_the_picture_on_the_chosen_one(tmp_path):
    out = run(tmp_path, """
  let release; hold['150'] = new Promise((r) => { release = r; });
  await choosePicture(tree, 'girl.png');
  await tree.querySelectorAll('button.ge-scale')[1].dispatch('click'); await settle();
  out.before = shown(tree);
  release(); await settle();
  out.after = shown(tree);
  out.speeds = uploads().map((u) => u.speed);
""")
    assert out["speeds"] == ["150", "100"]
    assert out["before"].startswith("/api/grey-scales/picture/pic-100-") and out["after"] == out["before"]


@node
def test_the_width_and_the_colour_choice_re_predict_without_the_button_and_the_button_sends_the_file_again(tmp_path):
    out = run(tmp_path, """
  await choosePicture(tree, 'girl.png');
  const width = input(tree, (i) => i.getAttribute('aria-label') === 'Ширина на титане, мм');
  width.value = '100'; await width.dispatch('change'); await settle();
  out.width = {uploads: uploads().length, size: tree.textContent.includes('для 100 × 40 мм')};
  const colour = input(tree, (i) => i.getAttribute('type') === 'checkbox');
  colour.checked = true; await colour.dispatch('change'); await settle();
  out.colour = uploads().map((u) => [u.by_colour, u.width_mm]);
  await tree.querySelectorAll('button').find((b) => b.textContent === 'Показать на титане').dispatch('click'); await settle();
  out.again = uploads().length;
""")
    assert out["width"] == {"uploads": 1, "size": True}                     # the width re-renders the kept upload
    assert out["colour"] == [["false", "50"], ["true", "100"]]              # the colour choice is a new upload: its greys are chosen on the server
    assert out["again"] == 3
