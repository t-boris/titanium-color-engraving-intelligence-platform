"""A photo zone of a vector work on its own screen (0.23.0, DEC-116): the panels of a photo work (photo-panels.js) over the zone's API — the
scales of the work's laser, lens and titanium on the left, the zone's picture beside its predicted look in the middle, the tabs on the
right; each change is a step of the vector work, undone and redone from the head or with Ctrl+Z, and a step that takes the zone away
returns to the work. Run in node over the small DOM of the other screen tests, with a fake server that answers as the zone's API does."""
import json
import subprocess
from pathlib import Path

from test_photo_engraving_ui import GLUE, KIND_KEYS, SCRIPTS, mode, node, scale, scale_answer
from test_vector_work import TABLES, UI

HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context({});
const docKeys = [];
ctx.document.addEventListener = (type, fn) => { if (type === 'keydown') docKeys.push(fn); };
const press = (extra) => Promise.all(docKeys.map((fn) => fn({type: 'keydown', target: ctx.document.body, preventDefault() {}, ...extra})));
load(ctx, %(ui)s, [...%(tables)s, ...%(scripts)s, {code: %(glue)s}, 'screens/dot-pick.js', 'screens/lettering.js', 'screens/photo-panels.js', 'screens/vector-zone.js']);
const requests = [], past = [], future = [];
let zone = data.zone, version = 0, refuse = null;
const base = '/api/vector/9/photo/1';
const view = () => ({...zone, work: {...data.work, undo: past.length, redo: future.length},
  picture: {preview: `${base}/preview.png?v=${version}`, by_colour: zone.by_colour, colour_choice: zone.colour_choice, contours: zone.contours,
    colour_match: zone.by_colour ? {choice: zone.colour_choice, median_de: 16.2, p90_de: 30.4, greys_used: 200, greys_available: 240,
      reach: zone.colour_choice === 'nearest' ? null : [42, 87.2], path: zone.colour_choice === 'nearest' ? null : 180, order: zone.colour_choice === 'nearest' ? null : 0.98, objects: null} : null,
    contours_report: zone.contours && zone.by_colour ? {share: 0.0123} : null, outside_share: 0, time: {seconds: 95, layers: [{index: 3, name: zone.name, seconds: 95}]},
    size_mm: {width: zone.width_mm, height: 18.2}, power_range: [zone.min_power, zone.max_power], dpi: 1000, notes: [],
    scale_size: {row_mm: zone.width_mm, how: 'between', measured_mm: [38.4, 150], from_mm: [38.4, 150], unknown_points: 0},
    ...(zone.kind !== 'grayscale' ? {kind: zone.kind, estimate: true, dots: {power: zone.dot_power, hex: '#3355aa', clean_hex: '#bbbbbb', struck_share: 0.42, measured: null},
      closeup: `${base}/closeup.png?v=${version}`, closeup_mm: 4, closeup_px: 3} : {})}});
const answer = (json, status = 200) => ({ok: status < 300, status, headers: {get: (k) => (k.toLowerCase() === 'content-type' ? 'application/json' : null)}, json: async () => json});
const restore = (from, to, error) => {
  if (!from.length) return answer({error}, 422);
  to.push({...zone}); zone = from.pop(); version++;
  return answer(zone === null ? {gone: true, work: {id: 9}} : view());
};
ctx.fetch = async (url, opts = {}) => {
  const path = String(url).split('?')[0], method = opts.method || 'GET';
  const body = opts.body ? JSON.parse(opts.body) : null;
  requests.push({path, url: String(url), method, body});
  if (path === '/api/grey-scales') return answer({scales: data.scales});
  if (path === '/api/grey-scales/scale') return answer(data.scale);
  if (path === base && method === 'GET') return answer(view());
  if (path === `${base}/settings`) {
    if (refuse) return answer({error: refuse}, 422);
    past.push({...zone}); future.length = 0;
    const next = {...zone, ...body};
    if (body.kind && body.kind !== 'grayscale' && next.dot_power == null) next.dot_power = 12.5;
    if (body.scale) {
      const sc = data.scales.find((s) => s.mode.speed === body.scale.speed);
      Object.assign(next, {scale: sc.mode, min_power: sc.span[0], max_power: sc.span[1]});
    }
    zone = next; version++;
    return answer(view());
  }
  if (path === `${base}/undo`) return restore(past, future, 'there is no earlier change of the work to undo');
  if (path === `${base}/redo`) return restore(future, past, 'there is no undone change to redo');
  if (path === `${base}/kinds`) return answer(data.kinds);
  return answer({error: path + ' not found'}, 404);
};
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const settle = async () => { for (let i = 0; i < 10; i++) await wait(0); };
const input = (tree, test) => tree.querySelectorAll('input').find(test);
const labelled = (tree, label) => input(tree, (i) => i.getAttribute('aria-label') === label && i.getAttribute('type') !== 'range');
const button = (tree, text) => tree.querySelectorAll('button').find((b) => b.textContent === text);
const shown = (tree) => { const img = tree.querySelectorAll('img').find((i) => (i.className || '').includes('pp-image')); return img ? img.getAttribute('src') : null; };
const saves = () => requests.filter((r) => r.path.endsWith('/settings')).map((r) => r.body);
const chosen = (tree) => tree.querySelectorAll('button.ge-scale').map((b) => b.getAttribute('aria-pressed') === 'true');
const powers = (tree) => [labelled(tree, 'Min мощность, %% (белый)').value, labelled(tree, 'Max мощность, %% (чёрный)').value];
const dialog = () => ctx.document.body.querySelector('.modal');
(async () => {
  const out = {};
  const tree = await ctx.__screens['vector-zone'].render({query: %(query)s});
  ctx.document.body.append(tree);
  await settle();
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""

ZONE = {"number": 1, "regions": ["p12", "p13"], "kind": "grayscale", "scale": mode(100), "min_power": 12, "max_power": 28, "dot_power": None,
        "by_colour": False, "colour_choice": "drawing", "contours": False, "rules": [], "colouring": {}, "ai": None, "ai_theme": None,
        "index": 3, "width_mm": 24.5, "area_mm2": 310.2, "box": {"x": 10, "y": 12, "width": 24.5, "height": 18.2}, "span": [1, 30],
        "referenced": True, "dots": None, "estimate": False, "problem": None, "name": "C03", "dpi": 1000, "time": {"seconds": 95},
        "ai_missing": None, "ai_photo": False}
WORK = {"id": 9, "name": "Портрет", "device_id": 1, "lens_id": 2, "material_id": 3}
KINDS = {"zone": 1, "kind": "grayscale", "kinds": [
    {"key": k, "family": "power" if k == "grayscale" else "edges" if k == "sketch" else "dots", "basis": "documented", "estimate": k != "grayscale",
     "picture": f"/api/vector/9/photo/1/kinds/{k}.png?v=1", **({"min_power": 12, "max_power": 28} if k == "grayscale" else {"power": 12.5, "hex": "#3355aa",
                                                                                                                            "clean_hex": "#bbbbbb"})}
    for k in KIND_KEYS]}


def run(tmp_path, body, query=None, **zone):
    (tmp_path / "data.json").write_text(json.dumps({"zone": {**ZONE, **zone}, "work": WORK, "scales": [scale(150, [1, 30]), scale(100, [2, 25])],
                                                    "scale": scale_answer(), "kinds": KINDS}), encoding="utf-8")
    script = tmp_path / "zone.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "scripts": json.dumps(SCRIPTS), "glue": json.dumps(GLUE),
                                 "query": json.dumps(query or {"work": "9", "zone": "1"}), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout)


@node
def test_a_zone_opens_on_the_scales_of_its_works_laser_lens_and_titanium_with_its_picture_beside_its_look(tmp_path):
    out = run(tmp_path, """
  out.head = [tree.querySelector('h2').textContent, tree.querySelectorAll('p').find((x) => x.className === 'sub').textContent, tree.querySelector('a.btn').getAttribute('href')];
  out.scales = requests.filter((r) => r.path === '/api/grey-scales').map((r) => Object.fromEntries(new URLSearchParams(r.url.split('?')[1])));
  out.opened = {chosen: chosen(tree), powers: powers(tree), shown: shown(tree)};
  const width = labelled(tree, 'Ширина на титане, мм');
  out.width = [width.value, !!width.disabled];
  out.widths = requests.filter((r) => r.path === '/api/grey-scales/scale').map((r) => new URLSearchParams(r.url.split('?')[1]).get('row_mm'));
  out.layer = tree.textContent.includes('Файл LightBurn работы: слой C03 — изображение в режиме градаций серого после слоёв цвета: Min 12 %, Max 28 %');
  out.missing = [!!button(tree, 'Проба на ширине работы'), tree.textContent.includes('Исходная цветная картинка'), tree.textContent.includes('чистка')];
  out.choices = tree.querySelectorAll('select').find((x) => x.getAttribute('aria-label') === 'Как подбирать серые').querySelectorAll('option').map((o) => o.textContent);
  out.tabs = tree.querySelectorAll('button').filter((t) => t.getAttribute('role') === 'tab').map((t) => t.textContent);
  out.steps = [button(tree, 'Отменить').disabled, button(tree, 'Повторить').disabled];
""")
    assert out["head"] == ["Фотозона 1", "работа «Портрет» · C03 · областей 2 · 24,5 × 18,2 мм", "#/vector?plan=9"]
    assert out["scales"] == [{"device_id": "1", "material_id": "3", "lens_id": "2"}]           # only the scales the work can be engraved on
    assert out["opened"] == {"chosen": [False, True], "powers": ["12", "28"], "shown": "/api/vector/9/photo/1/preview.png?v=0"}
    assert out["width"] == ["24.5", True] and out["widths"][0] == "24.5"                       # the zone's width is its regions', its scale read at it
    assert out["layer"] and out["missing"] == [False, False, False]                   # no ramp, no original picture, no cleaning of its own
    assert out["choices"] == ["Сохранить рисунок", "Ближайший цвет"]                            # «Раскраска по объектам» comes with its tab
    assert out["tabs"] == ["Картинка", "Шкала", "Подтверждение", "Точки"] and out["steps"] == [True, True]


@node
def test_a_zone_chooses_its_greys_contours_powers_and_scale_and_each_change_is_saved_and_shown(tmp_path):
    out = run(tmp_path, """
  const max = labelled(tree, 'Max мощность, % (чёрный)');
  max.value = '20'; await max.dispatch('change'); await wait(300); await settle();
  const colour = input(tree, (i) => i.getAttribute('type') === 'checkbox' && !i.getAttribute('aria-label'));
  colour.checked = true; await colour.dispatch('change'); await settle();
  const choice = tree.querySelectorAll('select').find((x) => x.getAttribute('aria-label') === 'Как подбирать серые');
  out.kept = tree.textContent.includes('Рисунок сохранён: тона картинки разложены по плавной полосе шкалы из 180 серых');
  choice.value = 'nearest'; await choice.dispatch('change'); await settle();
  const contours = labelled(tree, 'Контуры');
  contours.checked = true; await contours.dispatch('change'); await settle();
  out.said = [tree.textContent.includes('Подбор по цвету: ближайшие цвета шкалы отличаются от цветов картинки в среднем на 16,2 ΔE'),
              tree.textContent.includes('обведены линией 0,3 мм — 1,2 % картинки')];
  out.shown = shown(tree);
  await tree.querySelectorAll('button.ge-scale')[0].dispatch('click'); await settle(); await wait(300); await settle();
  out.scale = {chosen: chosen(tree), powers: powers(tree)};
  out.saves = saves();
  refuse = 'the contours must be on or off';
  contours.checked = false; await contours.dispatch('change'); await settle();
  out.refused = [contours.checked, tree.querySelectorAll('p.alert').filter((p) => !p.hidden).map((p) => p.textContent)];
""")
    assert out["saves"] == [{"min_power": 12, "max_power": 20}, {"by_colour": True}, {"colour_choice": "nearest"}, {"contours": True},
                            {"scale": mode(150)}]
    assert out["kept"] and out["said"] == [True, True] and out["shown"] == "/api/vector/9/photo/1/preview.png?v=4"
    assert out["scale"] == {"chosen": [True, False], "powers": ["1", "30"]}                  # another scale brings its measured span
    assert out["refused"] == [True, ["Контуры — либо включены, либо выключены"]]                       # refused: the zone stays as it was


@node
def test_undo_and_redo_are_the_works_from_the_head_and_ctrl_z_and_a_step_that_takes_the_zone_away_returns_to_the_work(tmp_path):
    out = run(tmp_path, """
  const max = labelled(tree, 'Max мощность, % (чёрный)');
  max.value = '25'; await max.dispatch('change'); await wait(300); await settle();
  out.changed = [powers(tree), button(tree, 'Отменить').disabled];
  await button(tree, 'Отменить').dispatch('click'); await settle();
  out.undone = [powers(tree), button(tree, 'Отменить').disabled, button(tree, 'Повторить').disabled];
  await press({key: 'z', ctrlKey: true, shiftKey: true}); await settle();
  out.redone = powers(tree);
  await press({key: 'z', metaKey: true, target: tree.querySelectorAll('input')[0]}); await settle();
  out.typing = powers(tree);
  await press({key: 'z', ctrlKey: true}); await settle();
  out.keyed = powers(tree);
  await press({key: 'z', ctrlKey: true, shiftKey: true}); await settle();
  past.unshift(null);                                                        // the step before the zone's changes made it: undoing it takes it away
  await press({key: 'z', ctrlKey: true}); await settle();
  out.before = ctx.__went.slice();
  await press({key: 'z', ctrlKey: true}); await settle();
  out.went = ctx.__went;
  out.steps = requests.filter((r) => /[/](undo|redo)$/.test(r.path)).map((r) => r.path.split('/').pop());
""")
    assert out["changed"] == [["12", "25"], False]
    assert out["undone"] == [["12", "28"], True, False]
    assert out["redone"] == ["12", "25"] and out["typing"] == ["12", "25"] and out["keyed"] == ["12", "28"]
    assert out["steps"] == ["undo", "redo", "undo", "redo", "undo", "undo"] and out["before"] == [] and out["went"] == ["/vector?plan=9"]


@node
def test_the_kind_of_a_zone_is_chosen_from_its_picture_in_each_kind_and_a_dot_kind_shows_its_dots(tmp_path):
    out = run(tmp_path, """
  await tree.querySelectorAll('button').find((b) => b.textContent.startsWith('Вид:')).dispatch('click'); await settle();
  const box = dialog();
  out.pictures = box.querySelectorAll('button.ge-kind').map((b) => b.querySelector('img').getAttribute('src'));
  await box.querySelectorAll('button.ge-kind').find((b) => b.querySelector('strong').textContent === 'Джарвис').dispatch('click'); await settle();
  out.kind = tree.querySelectorAll('button').find((b) => b.textContent.startsWith('Вид:')).textContent;
  out.dot = labelled(tree, 'Мощность точек, %').value;
  out.layer = tree.textContent.includes('Файл LightBurn работы: слой C03 — изображение в режиме «Джарвис»: мощность 12,5 %');
  out.closeup = tree.querySelectorAll('img').some((i) => (i.getAttribute('src') || '').startsWith('/api/vector/9/photo/1/closeup.png'));
  out.saves = saves();
""")
    assert out["pictures"][6] == "/api/vector/9/photo/1/kinds/jarvis.png?v=1"
    assert out["kind"] == "Вид: Джарвис" and out["dot"] == "12.5" and out["layer"] and out["closeup"]
    assert out["saves"] == [{"kind": "jarvis"}]


RECIPE = {"entry": "e-violet", "settings": {"power": 20, "speed": 500, "frequency": 60, "pulse_width": 300, "line_interval": 0.02, "passes": 1,
                                            "global_passes": 1}, "lab": [45, 15, -30], "size": {"row_mm": 24.5, "how": "unknown", "measured_mm": [], "from_mm": []},
          "missing": False}


@node
def test_a_dot_zone_opens_the_colour_map_for_its_dots_and_a_colour_from_the_map_goes_back_on_the_scale(tmp_path):
    out = run(tmp_path, """
  out.offered = !!button(tree, 'Цвет с карты') && !button(tree, 'На шкалу');
  await button(tree, 'Цвет с карты').dispatch('click'); await settle();
  out.went = [...ctx.__went];
  zone = {...zone, dot_recipe: RECIPE_JSON}; version++;
  const max = labelled(tree, 'Мощность точек, %');
  max.value = '13'; await max.dispatch('change'); await wait(300); await settle();
  out.mapped = [!!button(tree, 'Другой цвет'), !!button(tree, 'На шкалу'), !labelled(tree, 'Мощность точек, %'),
                tree.textContent.includes('с карты цветов: 20 % · 500 мм/с · 60 кГц · 300 нс · шаг 0,02 мм (1000 dpi)'),
                tree.textContent.includes('Файл LightBurn работы: слой C03 — изображение в режиме «Джарвис»: мощность 13 % (Min = Max — каждая точка бьёт на ней), 500 мм/с')];
  await button(tree, 'На шкалу').dispatch('click'); await wait(300); await settle();
  out.saves = saves();
""".replace("RECIPE_JSON", json.dumps(RECIPE)), kind="jarvis", dot_power=12.5)
    assert out["offered"] and out["went"] == ["/colors?dots=9&zone=1&setup=laser%3A1%2Flens%3A2"]
    assert out["mapped"] == [True, True, True, True, True]
    assert out["saves"] == [{"dot_power": 13}, {"dot_power": 13}]                              # «На шкалу»: back on the scale at its power


@node
def test_the_brightness_contrast_and_gamma_of_a_zone_are_saved_from_three_sliders_and_wait_while_its_greys_are_chosen_for_colours(tmp_path):
    out = run(tmp_path, """
  const slider = (name) => labelled(tree, name);
  const B = 'Яркость картинки, %: меньше нуля — темнее, больше — светлее', C = 'Контраст картинки, %: больше нуля — светлое светлее и тёмное темнее',
        G = 'Гамма картинки: меньше 1 — средние тона светлее, больше 1 — темнее';
  out.start = [slider(B).value, slider(C).value, slider(G).value, button(tree, 'Как есть').disabled, !!slider(B).disabled];
  slider(B).value = '20'; await slider(B).dispatch('change');
  slider(G).value = '1.5'; await slider(G).dispatch('change'); await wait(350); await settle();
  out.after = [slider(B).value, slider(G).value, button(tree, 'Как есть').disabled];
  await button(tree, 'Как есть').dispatch('click'); await settle();
  out.reset = [slider(B).value, slider(G).value];
  const colour = input(tree, (i) => i.getAttribute('type') === 'checkbox' && !i.getAttribute('aria-label'));
  colour.checked = true; await colour.dispatch('change'); await settle();
  const note = tree.querySelectorAll('p').find((p) => (p.className || '').includes('ge-tone-note'));
  out.off = [!!slider(B).disabled, !!slider(G).disabled, button(tree, 'Как есть').disabled, note.hidden];
  out.saves = saves();
""")
    assert out["start"] == ["0", "0", "1", True, False]
    assert out["after"] == ["20", "1.5", False]                                               # one save after a pause, the sliders as saved
    assert out["reset"] == ["0", "1"]
    assert out["off"] == [True, True, True, False]
    assert out["saves"] == [{"tone": {"brightness": 20, "contrast": 0, "gamma": 1.5}}, {"tone": {"brightness": 0, "contrast": 0, "gamma": 1}},
                            {"by_colour": True}]
