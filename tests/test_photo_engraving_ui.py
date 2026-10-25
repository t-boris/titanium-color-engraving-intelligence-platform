"""The photo engraving screens (REQ-059, REQ-061): the list of works, a new work, a work on one screen and the grey-scales page. Run in
node over the small DOM of the other screen tests, with a fake server that answers as the photo-work and grey-scale API do."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
SCRIPTS = ["app.js", "photo-modes.js", "photo-quality.js", "dialogs.js", "list.js", "hardware.js", "filepick.js"]
GLUE = ("const __screens = {}; App.register = (d) => { __screens[d.id] = d; }; App.render = () => {}; globalThis.__screens = __screens;"
        "globalThis.__went = []; App.go = (route) => { __went.push(route); };"
        "globalThis.FormData = class { constructor() { this.fields = []; } append(k, v) { this.fields.push([k, v]); } };")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context({});
const docKeys = [];
ctx.document.addEventListener = (type, fn) => { if (type === 'keydown') docKeys.push(fn); };
const press = (extra) => Promise.all(docKeys.map((fn) => fn({type: 'keydown', target: ctx.document.body, preventDefault() {}, ...extra})));
load(ctx, %(ui)s, [...%(tables)s, ...%(scripts)s, {code: %(glue)s}, 'screens/vector-workspace.js', 'screens/lettering.js', 'screens/vector-editor.js', 'screens/vector-colours.js', 'screens/photo-panels.js', 'screens/dot-pick.js', 'screens/lab-source.js', 'screens/photo-engraving.js']);
const requests = [], hold = [], past = [], future = [];
let work = data.work, version = 0;
const remember = () => { past.push({...work}); future.length = 0; };
const restore = (from, to, error) => {
  if (!from.length) return answer({error}, 422);
  to.push({...work}); work = {...from.pop(), ai_photo: work.ai_photo}; version++;
  return answer(view());
};
const same = (a, b) => ['speed', 'line_interval', 'material_id'].every((k) => a[k] === b[k]);
const match = () => (work.by_colour ? {choice: work.colour_choice, median_de: 16.2, p90_de: 30.4, greys_used: 200, greys_available: 240,
  reach: work.colour_choice === 'nearest' ? null : [42, 87.2], path: work.colour_choice === 'nearest' ? null : 180,
  order: work.colour_choice === 'nearest' ? null : 0.98,
  objects: work.colour_choice === 'objects' ? Object.entries(work.colouring || {}).map(([key, c]) => ({key, power: c.power, hex: '#7d5256', shift: c.shift})) : null} : null);
const view = () => ({...work, undo: past.length, redo: future.length, picture: work.problem ? null : {preview: `/api/photo-works/${work.id}/preview.png?v=${version}`, by_colour: work.by_colour,
  colour_match: match(), contours_report: work.contours && work.by_colour ? {share: 0.0123} : null,
  outside_share: 0, time: {seconds: 600, layers: [{index: 0, name: 'CLEAN-CROSSHATCH-P20-F48-V2000-PW200-I0.05', seconds: 42}, {index: 1, name: 'C01', seconds: 558}]}, size_mm: {width: work.width_mm, height: work.width_mm / 2}, power_range: [work.min_power, work.max_power], dpi: 1000, notes: [],
  scale_size: {row_mm: work.width_mm, how: 'between', measured_mm: [38.4, 150], from_mm: [38.4, 150], unknown_points: 0},
  ...(work.kind && work.kind !== 'grayscale' ? {kind: work.kind, estimate: true, dots: {power: work.dot_recipe ? work.dot_recipe.settings.power : work.dot_power,
    source: work.dot_recipe ? work.dot_recipe.source || 'map' : 'scale', recipe: work.dot_recipe || null, hex: '#3355aa', clean_hex: '#bbbbbb', struck_share: 0.42},
    closeup: `/api/photo-works/${work.id}/closeup.png?v=${version}`, closeup_mm: 4, closeup_px: 3} : {})}});
const answer = (json, status = 200) => ({ok: status < 300, status, headers: {get: (k) => (k.toLowerCase() === 'content-type' ? 'application/json' : null)}, json: async () => json});
ctx.fetch = async (url, opts = {}) => {
  const path = String(url).split('?')[0], method = opts.method || 'GET';
  const body = opts.body && opts.body.fields ? Object.fromEntries(opts.body.fields.map(([k, v]) => [k, v && typeof v === 'object' ? v.name : String(v)]))
    : opts.body ? JSON.parse(opts.body) : null;
  requests.push({path, url: String(url), method, body});
  if (path === '/api/grey-scales') return answer({scales: data.scales});
  if (path === '/api/devices') return answer([{id: 1, lens: {id: 2}}]);
  if (path === '/api/materials') return answer([]);
  if (path === '/api/grey-scales/scale') return answer(data.scale);
  if (path === '/api/photo-works' && method === 'GET') return answer(data.works);
  if (path === '/api/photo-works' && method === 'POST') return answer({id: 9}, 201);
  if (path === `/api/photo-works/${work.id}`) return answer(view());
  if (path === `/api/photo-works/${work.id}/settings`) {
    if (hold.length) await hold.shift();
    if (body.width_mm === 0) return answer({error: 'the width of the picture must be 1..1000 mm'}, 422);
    if (Object.keys(body).some((k) => k !== 'ai_photo')) remember();
    const next = {...work, ...body};
    if (body.kind && body.kind !== 'grayscale' && next.dot_power == null) next.dot_power = 12.5;     // where the scale's colour stands out most
    if ('dot_power' in body) next.dot_recipe = null;                                                // a power on the scale puts the dots back on it
    if (body.scale) {
      const sc = data.scales.find((s) => same(s.mode, body.scale));
      Object.assign(next, {scale: sc.mode, min_power: sc.span[0], max_power: sc.span[1], problem: null});
    }
    work = next; version++;
    return answer(view());
  }
  if (path === `/api/photo-works/${work.id}/kinds`) return answer(data.kinds);
  if (path === `/api/plans/${work.id}` && method === 'DELETE') return answer(null, 204);
  if (path === `/api/photo-works/${work.id}/copy`) return answer({id: 8}, 201);
  if (path === `/api/photo-works/${work.id}/width-ramp`) return answer({plan_id: 31, name: 'Шкалы серого · TCE-31'}, 201);
  if (path === `/api/photo-works/${work.id}/variations`) return answer({plan_id: 32, name: 'Фотогравировка: одна картинка × несколько настроек · TCE-32'}, 201);
  if (path === `/api/photo-works/${work.id}/parts`) return answer(data.parts);
  if (path === `/api/photo-works/${work.id}/objects`) return answer({...data.objects, active: work.by_colour && work.colour_choice === 'objects'});
  if (path === `/api/photo-works/${work.id}/theme`) {
    remember();
    work = {...work, by_colour: true, colour_choice: 'objects', colouring: data.themes[body.name]}; version++;
    return answer(view());
  }
  if (path === `/api/photo-works/${work.id}/ai-theme`) {
    remember();
    work = {...work, by_colour: true, colour_choice: 'objects', colouring: data.themes.warm,
      ai_theme: {wish: body.wish.trim(), note: 'очки золотом, губы красные', photo: work.ai_photo}}; version++;
    return answer(view());
  }
  if (path === `/api/photo-works/${work.id}/engravings`) return answer(data.engravings);
  if (path === `/api/photo-works/${work.id}/advice`) return answer(data.advice);
  if (path === '/api/photo-knowledge/plate') return answer({plan_id: 33, name: 'Фотогравировка: одна картинка × несколько настроек · TCE-33'}, 201);
  if (path === `/api/photo-works/${work.id}/ai`) {
    if (hold.length) await hold.shift();
    remember();
    work = {...work, rules: data.ai_rules, ai: {wish: body.wish.trim(), note: 'платье фиолетовым, остальное как есть', photo: work.ai_photo, fresh: body.fresh,
      before: work.rules}};
    version++;
    return answer(view());
  }
  if (path === `/api/photo-works/${work.id}/undo`) return restore(past, future, 'there is no earlier change of the work to undo');
  if (path === `/api/photo-works/${work.id}/redo`) return restore(future, past, 'there is no undone change to redo');
  return answer({error: path + ' not found'}, 404);
};
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const settle = async () => { for (let i = 0; i < 10; i++) await wait(0); };
const input = (tree, test) => tree.querySelectorAll('input').find(test);
const labelled = (tree, label) => input(tree, (i) => i.getAttribute('aria-label') === label && i.getAttribute('type') !== 'range');
const button = (tree, text) => tree.querySelectorAll('button').find((b) => b.textContent === text);
const shown = (tree) => { const img = tree.querySelectorAll('img').find((i) => (i.className || '').includes('pp-image')); return img ? img.getAttribute('src') : null; };
const saves = () => requests.filter((r) => r.path.endsWith('/settings')).map((r) => r.body);
const lines = (tree) => tree.querySelector('.ge-scale-list').querySelectorAll('.lst-main');      // a line a scale (DEC-090)
const chosen = (tree) => lines(tree).map((m) => m.textContent.includes('выбрана'));
/** The scale on line ``i`` chosen: its line opens its card, the card is pressed. */
const pickScale = async (tree, i) => { await lines(tree)[i].dispatch('click'); await settle(); await tree.querySelector('button.ge-scale').dispatch('click'); };
const powers = (tree) => [labelled(tree, 'Min мощность, %% (белый)').value, labelled(tree, 'Max мощность, %% (чёрный)').value];
const dialog = () => ctx.document.body.querySelector('.modal');
const asks = () => requests.filter((r) => r.path.endsWith('/ai')).map((r) => r.body);
const select = (tree, label) => tree.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === label);
(async () => {
  const out = {};
  const tree = await ctx.__screens['photo-engraving'].render({query: %(query)s});
  await settle();
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


JARVIS = {"power": 22.0, "speed": 180.0, "frequency": 60.0, "pulse_width": 250.0, "line_interval": 0.012, "passes": 1, "global_passes": 1}
# what the laboratory knows of the work's kind (photo_knowledge.advice): an engraving of it photographed, the power's effect measured
ADVICE = {"kind": "grayscale", "current": {}, "best": None, "at_best": False, "effects": {}, "status": "unmeasured", "proposal": None,
          "steps": {d: {"refused": "the settings are already at their limits: nothing known moves the engraving further that way"}
                    for d in ("darker", "lighter", "sharper", "softer")}}
JARVIS_ADVICE = {
    "kind": "jarvis", "current": {}, "at_best": False, "status": "measured",
    "best": {"settings": {"dither": "jarvis", "min_power": 22.0, "dot_width": 0.02, **JARVIS}, "score": 0.9, "source": {"pair_id": 118, "layer": "C20"},
             "other_titanium": False, "span_of": None},
    "effects": {"power": {"per": "doubling", "photographs": [120], "mean_L": {"median": -6.0, "n": 2}, "score": {"median": 0.1, "n": 2}}},
    "steps": {"darker": {"changed": [{"setting": "power", "from": 12.5, "to": 17.5}], "basis": "measured", "evidence": {"photographs": [120]},
                         "apply": {"dot_settings": {**JARVIS, "power": 17.5}}},
              "lighter": {"changed": [{"setting": "power", "from": 12.5, "to": 9.0}], "basis": "measured", "evidence": {"photographs": [120]},
                          "apply": {"dot_settings": {**JARVIS, "power": 9.0}}},
              "sharper": {"changed": [{"setting": "dot_width", "from": None, "to": 0.01}], "basis": "prior", "evidence": None, "apply": {"dot_width": 0.01}},
              "softer": {"changed": [{"setting": "power", "from": 12.5, "to": 14.0}], "basis": "prior", "evidence": None,
                         "apply": {"dot_settings": {**JARVIS, "power": 14.0}}}},
    "proposal": {"kind": "around", "centre": {"dither": "jarvis", **JARVIS}, "step": 1.0, "source": {"pair_id": 118, "layer": "C20"},
                 "copies": [[], [{"setting": "power", "from": 22.0, "to": 17.6}], [{"setting": "speed", "from": 180.0, "to": 252.0}],
                            [{"setting": "dither", "from": "jarvis", "to": "atkinson"}]],
                 "plate": {"copy_mm": [18.0, 12.0], "size_mm": [65.0, 44.6], "picture": "portrait.png"}},
    "take": {"dot_settings": JARVIS, "dot_width": 0.02}, "turn": None}


def run(tmp_path, query, body, work=None, engravings=(), scales=None, advice=None):
    work = {**WORK, **(work or {})}
    scales = [scale(150, [1, 30]), scale(100, [2, 25])] if scales is None else scales
    (tmp_path / "data.json").write_text(json.dumps({"scales": scales, "scale": scale_answer(), "work": work, "kinds": KINDS,
                                                    "works": [listed(work)], "parts": PARTS, "ai_rules": AI_RULES, "engravings": list(engravings),
                                                    "objects": OBJECTS, "themes": THEMES, "advice": advice or ADVICE}),
                                        encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "scripts": json.dumps(SCRIPTS), "glue": json.dumps(GLUE),
                                 "query": json.dumps(query), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout)


# -- answers shaped as the server sends them ------------------------------------------------------------------------------------------
def mode(speed):
    return {"device_id": 1, "lens_id": 2, "material_id": 3, "speed": speed, "frequency": 60, "pulse_width": 250, "line_interval": 0.0254, "passes": 1,
            "global_passes": 1}


def scale(speed, span):
    return {"mode": mode(speed), "dpi": 1000, "span": span, "material": {"name": "Big Plate 150"}, "bar": [{"hex": "#aa8844"}, {"hex": "#3355aa"}],
            "by_kind": {"grey ramp": 1}, "time_s_per_cm2": 70, "confirmation": {"engravings": 1, "median_de": None}, "reference": "chart",
            "sizes": [{"row_mm": 38.4, "engravings": 1, "points": 16}, {"row_mm": 150, "engravings": 1, "points": 16}],
            "size": {"row_mm": 150, "how": "measured", "measured_mm": [38.4, 150], "from_mm": [150], "unknown_points": 0, "engravings": 2}}


def scale_answer():
    levels = [{"level": g, "power": 30 - g * 29 / 255, "lab": [50, 0, 0], "hex": "#777777", "spread_de": None} for g in range(256)]
    return {"greys": {"levels": levels, "measured_levels": 256}, "confirmation": {"rows": [], "tolerance_de": 5, "engravings": 1, "median_de": None},
            "fill_points": [], "curve": {"points": []}, "notes": [], "span": [1, 30],
            "size": {"row_mm": 150, "how": "measured", "measured_mm": [38.4, 150], "from_mm": [150], "unknown_points": 0, "engravings": 2}}


WORK = {"id": 7, "name": "Портрет", "identifier": "TCE-P-1", "created_at": "2026-10-21T10:00:00", "updated_at": "2026-10-21T10:05:00",
        "image_name": "girl.png", "image_size": [240, 120], "scale": mode(100), "material": {"name": "Big Plate 150"}, "dpi": 1000,
        "min_power": 12, "max_power": 28, "width_mm": 60, "height_mm": 30, "by_colour": False, "colour_choice": "drawing", "contours": False,
        "time": {"seconds": 600}, "problem": None,
        "rules": [], "ai": None, "ai_photo": False, "ai_missing": None, "colouring": {}, "ai_theme": None}
PARTS = {"parts": [{"part": "face_skin", "share": 0.5, "lab": [70, 10, 15], "hex": "#c8a08c", "tint": "#ff8c64"},
                   {"part": "clothes", "share": 0.5, "lab": [40, 0, -30], "hex": "#3355aa", "tint": "#4678ff"}], "picture": "/api/photo-works/7/parts.png?v=1"}
AI_RULES = [{"part": "clothes", "kind": "colour", "lab": [40, 40, -40], "hex": "#7a3fa0"}]
KIND_KEYS = ["grayscale", "threshold", "ordered", "atkinson", "dither", "stucki", "jarvis", "newsprint", "halftone", "sketch"]
FAMILY = {"grayscale": "power", "sketch": "edges"}
KINDS = {"kind": "grayscale", "problem": None, "kinds": [
    {"key": k, "family": FAMILY.get(k, "dots"), "basis": "inferred" if k in ("ordered", "newsprint", "sketch") else "documented", "estimate": k != "grayscale",
     "picture": f"/api/photo-works/7/kinds/{k}.png?v=1", **({"min_power": 12, "max_power": 28} if k == "grayscale" else {"power": 12.5, "hex": "#3355aa",
                                                                                                                           "clean_hex": "#bbbbbb"})}
    for k in KIND_KEYS]}


def thing(i, kind, piece, share, tint):
    return {"id": i, "kind": kind, "piece": piece, "share": share, "lab": [60, 10, 10], "hex": "#9a8070", "box": [0, 0, 10, 10],
            "key": kind if not piece else f"{kind}-{piece}", "tint": tint, "colour": None}


OBJECTS = {"objects": [thing(0, "background", 0, 0.3, "#5a5a5a"), thing(1, "background", 1, 0.15, "#963cc8"), thing(2, "face_skin", 0, 0.3, "#ff8c64"),
                       thing(3, "other", 0, 0.1, "#e6c828"), thing(4, "lips", 0, 0.02, "#dc283c")],
           "faces": 1, "notes": ["1 eye is behind glasses or something else worn: they stay in the part 'other'."],
           "options": [{"power": 1.0, "lab": [80, 1, 5], "hex": "#cdc6bc", "hue": 84, "chroma": 6}, {"power": 6.46, "lab": [56, 8, 28], "hex": "#a38157", "hue": 75, "chroma": 28},
                       {"power": 12.15, "lab": [40, 16, 4], "hex": "#7d5256", "hue": 16, "chroma": 19}, {"power": 17.6, "lab": [58, -6, -17], "hex": "#7093ab", "hue": 250, "chroma": 18}],
           "themes": ["warm", "cool", "contrast", "random"], "active": False, "picture": "/api/photo-works/7/objects.png?v=1"}
THEMES = {"warm": {"face_skin": {"power": 1.0, "shift": 0}, "lips": {"power": 12.15, "shift": 0}}, "cool": {"background": {"power": 17.6, "shift": 0}},
          "contrast": {"background": {"power": 12.15, "shift": 0}}, "random": {"other": {"power": 6.46, "shift": 0}}}


def listed(work):
    return {k: v for k, v in work.items() if k not in ("problem", "ai_missing")}


# -- the list and a new work -----------------------------------------------------------------------------------------------------------
@node
def test_the_list_shows_each_work_and_a_new_work_is_made_in_two_steps_the_picture_then_which_kind_with_the_picture_in_each(tmp_path):
    out = run(tmp_path, {}, """
  out.cards = tree.querySelectorAll('article.vw-work-card').map((c) => c.textContent);
  out.thumb = tree.querySelector('a.vw-thumb').children[0].getAttribute('src');
  await button(tree, 'Новая работа').dispatch('click'); await settle();
  let box = dialog();
  out.first = {title: box.querySelector('h3').textContent, buttons: box.querySelectorAll('button').map((b) => b.textContent)};
  const file = input(box, (i) => i.getAttribute('type') === 'file');
  file.files = [{name: 'moto.jpg', size: 4096}]; await file.dispatch('change');
  out.name = labelled(box, 'Название работы').value;
  labelled(box, 'Ширина на титане, мм').value = '80';
  await button(box, 'Дальше →').dispatch('click'); await settle();
  out.sent = requests.filter((r) => r.path === '/api/photo-works' && r.method === 'POST').map((r) => r.body);
  box = dialog();
  const tiles = () => box.querySelectorAll('button.ge-kind');
  const marked = () => tiles().filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.querySelector('strong').textContent + ' ' + b.querySelector('.pill').textContent);
  out.second = {title: box.querySelector('h3').textContent, tiles: tiles().length, pictures: tiles().map((b) => b.querySelector('img').getAttribute('src')),
                marked: marked(), create: !!button(box, 'Создать в «Градации серого»'), back: !!button(box, '← Назад'), went: [...ctx.__went]};
  await tiles().find((b) => b.querySelector('strong').textContent === 'Джарвис').dispatch('click'); await settle();
  out.picked = {marked: marked(), open: !!dialog(), saved: saves()};
  await button(box, 'Создать в «Джарвис»').dispatch('click'); await settle();
  out.saved = saves(); out.went = ctx.__went; out.open = !!dialog();
  out.deleted = requests.filter((r) => r.method === 'DELETE').map((r) => r.path);
""", work={"id": 9})
    card = out["cards"][0]
    assert "Портрет" in card and "60 × 30 мм" in card and "Min 12 % · Max 28 %" in card and "100 мм/с" in card
    assert out["thumb"] == "/api/photo-works/9/thumb.png?v=2026-10-21T10%3A05%3A00"
    assert out["first"] == {"title": "Новая работа · шаг 1 из 2: картинка", "buttons": ["×", "Отмена", "Дальше →"]}
    assert out["name"] == "moto"                                              # the name follows the picture until the operator types one
    assert out["sent"] == [{"picture": "moto.jpg", "name": "moto", "width_mm": "80"}]   # no scale: the best measured one is taken
    second = out["second"]
    assert second["title"] == "Новая работа · шаг 2 из 2: какая гравировка?" and second["tiles"] == 10 and second["went"] == []
    assert second["pictures"][6] == "/api/photo-works/7/kinds/jarvis.png?v=1"            # the work's own picture in each kind
    assert second["marked"] == ["Градации серого выбрано"] and second["create"] and second["back"]
    assert out["picked"] == {"marked": ["Джарвис выбрано"], "open": True, "saved": []}      # a click chooses; nothing is saved yet
    assert out["saved"] == [{"kind": "jarvis"}] and out["went"] == ["/photo-engraving?work=9"] and not out["open"]
    assert out["deleted"] == []


@node
def test_back_from_which_kind_returns_to_the_picture_as_it_was_and_leaving_the_second_step_deletes_the_work_it_made(tmp_path):
    out = run(tmp_path, {}, """
  const posts = () => requests.filter((r) => r.path === '/api/photo-works' && r.method === 'POST').length;
  const deleted = () => requests.filter((r) => r.method === 'DELETE').map((r) => r.path);
  await button(tree, 'Новая работа').dispatch('click'); await settle();
  let box = dialog();
  const file = input(box, (i) => i.getAttribute('type') === 'file');
  file.files = [{name: 'moto.jpg', size: 4096}]; await file.dispatch('change');
  labelled(box, 'Название работы').value = 'Мото';
  labelled(box, 'Ширина на титане, мм').value = '80';
  await button(box, 'Дальше →').dispatch('click'); await settle();
  await button(dialog(), '← Назад').dispatch('click'); await settle();
  box = dialog();
  out.back = {title: box.querySelector('h3').textContent, name: labelled(box, 'Название работы').value, width: labelled(box, 'Ширина на титане, мм').value,
              file: box.querySelector('.file-name').textContent, deleted: deleted(), went: [...ctx.__went]};
  await button(box, 'Дальше →').dispatch('click'); await settle();
  out.again = {title: dialog().querySelector('h3').textContent, posts: posts()};
  await press({key: 'Escape'}); await settle();
  out.escaped = {open: !!dialog(), deleted: deleted(), went: ctx.__went, saved: saves()};
""", work={"id": 9})
    assert out["back"] == {"title": "Новая работа · шаг 1 из 2: картинка", "name": "Мото", "width": "80", "file": "moto.jpg · 4 КБ",
                           "deleted": ["/api/plans/9"], "went": []}
    assert out["again"] == {"title": "Новая работа · шаг 2 из 2: какая гравировка?", "posts": 2}
    assert out["escaped"] == {"open": False, "deleted": ["/api/plans/9", "/api/plans/9"], "went": [], "saved": []}


# -- a work -----------------------------------------------------------------------------------------------------------------------------
@node
def test_a_work_on_another_plate_of_its_scales_titanium_opens_on_that_scale_which_names_the_titanium_and_its_plates(tmp_path):
    """DEC-110: the scale was measured on Big Plate 150 (record 3), the work is on Small Plate (record 4) of the same grade."""
    grade5 = {"name": "Big Plate 150", "family": "Titanium", "grade": "Grade 5", "thickness_mm": 3}
    titanium = {"family": "Titanium", "grade": "Grade 5", "records": [3, 4], "measured_on": [{"id": 3, "name": "Big Plate 150"}]}
    scales = [{**scale(speed, span), "material": grade5, "titanium": titanium} for speed, span in ((150, [1, 30]), (100, [2, 25]))]
    out = run(tmp_path, {"work": "7"}, """
  out.chosen = chosen(tree);
  out.named = lines(tree).map((m) => m.querySelector('.lst-text').getAttribute('title').includes('Титан Grade 5 · измерена на Big Plate 150'));
  out.card = tree.querySelectorAll('button.ge-scale').map((b) => [b.getAttribute('aria-pressed'), b.textContent.includes('Титан Grade 5 · измерена на Big Plate 150')]);
""", work={"scale": {**mode(100), "material_id": 4}, "material": {"name": "Small Plate", "grade": "Grade 5"}}, scales=scales)
    assert out["chosen"] == [False, True] and out["named"] == [True, True] and out["card"] == [["true", True]]   # the chosen scale's card open


@node
def test_a_work_opens_on_its_scale_with_its_min_and_max_and_each_change_is_saved_and_its_prediction_shown(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  out.opened = {chosen: chosen(tree), powers: powers(tree), shown: shown(tree), width: labelled(tree, 'Ширина на титане, мм').value,
                title: tree.querySelector('h2').textContent};
  const max = labelled(tree, 'Max мощность, % (чёрный)');
  max.value = '20'; await max.dispatch('change'); await wait(300); await settle();
  const width = labelled(tree, 'Ширина на титане, мм');
  width.value = '100'; await width.dispatch('change'); await settle();
  const colour = input(tree, (i) => i.getAttribute('type') === 'checkbox');
  colour.checked = true; await colour.dispatch('change'); await settle();
  out.saves = saves(); out.shown = shown(tree); out.size = tree.textContent.includes('для 100 × 50 мм');
  out.cleaning = [tree.textContent.includes('из них чистка ≈ 42 с'),
                  tree.textContent.includes('Файл LightBurn: C00 — чистка CLEAN-CROSSHATCH-P20-F48-V2000-PW200-I0.05 по прямоугольнику картинки, первой')];
  out.widths = requests.filter((r) => r.path === '/api/grey-scales/scale').map((r) => new URLSearchParams(r.url.split('?')[1]).get('row_mm'));
  out.between = tree.textContent.includes('100 мм: между измерениями 38,4 и 150 мм');
  const ramp = tree.querySelectorAll('button').find((b) => b.textContent === 'Проба на ширине работы');
  out.ramp = {main: ramp.className.includes('primary'), says: ramp.parentNode.textContent.includes('полоской серого 100 мм в ширину')};
  await ramp.dispatch('click'); await settle();
  out.ramp.posted = requests.filter((r) => r.path.endsWith('/width-ramp')).map((r) => r.method); out.ramp.went = ctx.__went.slice(-1);
  const tries = tree.querySelectorAll('button').find((b) => b.textContent === 'Подобрать настройки: 8 копий');
  out.tries = {says: tries.parentNode.textContent.includes('Max −20 % и +20 %, Min ±3')};
  await tries.dispatch('click'); await settle();
  out.tries.posted = requests.filter((r) => r.path.endsWith('/variations')).map((r) => r.method); out.tries.went = ctx.__went.slice(-1);
  width.value = '0'; await width.dispatch('change'); await settle();
  out.refused = {width: width.value, error: tree.querySelectorAll('p.alert').filter((p) => !p.hidden).map((p) => p.textContent)};
""")
    opened = out["opened"]
    assert opened["chosen"] == [False, True] and opened["powers"] == ["12", "28"] and opened["width"] == "60" and opened["title"] == "Портрет"
    assert opened["shown"] == "/api/photo-works/7/preview.png?v=0"
    assert out["saves"] == [{"min_power": 12, "max_power": 20}, {"width_mm": 100}, {"by_colour": True}]
    assert out["shown"] == "/api/photo-works/7/preview.png?v=3" and out["size"]
    assert out["cleaning"] == [True, True]                                                    # the file cleans first, and its time says so
    assert out["widths"][0] == "60" and out["widths"][-1] == "100" and out["between"]          # the scale and its colours at the work's width
    assert out["ramp"] == {"main": True, "says": True, "posted": ["POST"], "went": ["/experiment/plan-31"]}   # a ramp of the width not measured yet
    assert out["tries"] == {"says": True, "posted": ["POST"], "went": ["/experiment/plan-32"]}     # eight copies, one change each
    assert out["refused"] == {"width": "100", "error": ["Ширина картинки должна быть от 1 до 1000 мм"]}   # refused: the work stays as it was


@node
def test_how_the_greys_are_chosen_and_the_contours_are_saved_in_the_work_and_said(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  const choice = tree.querySelectorAll('select').find((x) => x.getAttribute('aria-label') === 'Как подбирать серые'), contours = labelled(tree, 'Контуры');
  const said = () => tree.textContent;
  out.before = {choice: !!choice.disabled, value: choice.value, contours: !!contours.disabled, on: contours.checked, said: said().includes('Контуры выключены'),
                options: choice.querySelectorAll('option').map((o) => o.textContent)};
  const colour = input(tree, (i) => i.getAttribute('type') === 'checkbox');
  colour.checked = true; await colour.dispatch('change'); await settle();
  out.drawing = {choice: !!choice.disabled, contours: !!contours.disabled, off: said().includes('Контуры выключены'),
                 kept: said().includes('Рисунок сохранён: тона картинки разложены по плавной полосе шкалы из 180 серых (L* от 87 до 42), порядок светлого и тёмного совпадает с картинкой на 98 %')};
  contours.checked = true; await contours.dispatch('change'); await settle();
  out.lined = said().includes('обведены линией 0,3 мм — 1,2 % картинки') && said().includes('Подобранные серые и контуры');
  choice.value = 'nearest'; await choice.dispatch('change'); await settle();
  out.nearest = said().includes('Подбор по цвету: ближайшие цвета шкалы отличаются от цветов картинки в среднем на 16,2 ΔE');
  out.saves = saves();
""")
    assert out["before"] == {"choice": True, "value": "drawing", "contours": True, "on": False, "said": False,
                             "options": ["Сохранить рисунок", "Ближайший цвет", "Раскраска по объектам"]}
    assert out["drawing"] == {"choice": False, "contours": False, "off": True, "kept": True}
    assert out["lined"] and out["nearest"]
    assert out["saves"] == [{"by_colour": True}, {"contours": True}, {"colour_choice": "nearest"}]


@node
def test_another_scale_is_saved_in_the_work_the_picture_stays_and_min_and_max_become_the_new_scales_span(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  await pickScale(tree, 0); await settle(); await wait(300); await settle();
  out.saves = saves(); out.chosen = chosen(tree); out.powers = powers(tree); out.shown = shown(tree);
""")
    assert out["saves"] == [{"scale": {"device_id": 1, "lens_id": 2, "material_id": 3, "speed": 150, "frequency": 60, "pulse_width": 250,
                                       "line_interval": 0.0254, "passes": 1, "global_passes": 1}}]   # nothing more: the new sliders save nothing by themselves
    assert out["chosen"] == [True, False] and out["powers"] == ["1", "30"] and out["shown"] == "/api/photo-works/7/preview.png?v=1"


@node
def test_changes_are_sent_one_after_another_in_their_order_and_the_last_one_is_shown(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  let release; hold.push(new Promise((r) => { release = r; }));
  const width = labelled(tree, 'Ширина на титане, мм');
  width.value = '80'; width.dispatch('change'); await settle();             // not awaited: the first answer is held
  width.value = '90'; width.dispatch('change'); await settle();
  out.before = {sent: saves().length, waiting: tree.textContent.includes('Считаем прогноз')};
  release(); await settle();
  out.after = {sent: saves(), shown: shown(tree), width: width.value};
""")
    assert out["before"] == {"sent": 1, "waiting": True}                       # the second waits for the first
    assert out["after"] == {"sent": [{"width_mm": 80}, {"width_mm": 90}], "shown": "/api/photo-works/7/preview.png?v=2", "width": "90"}


@node
def test_a_work_whose_scale_is_not_measured_says_why_and_a_measured_scale_can_be_chosen(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  out.opened = {chosen: chosen(tree), text: tree.textContent, sliders: tree.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'range' && !i.closest('li.ge-object')
    && !i.closest('.ge-tone')).length, tone: tree.querySelector('.ge-tone').hidden};
  await pickScale(tree, 1); await settle(); await wait(300); await settle();
  out.saves = saves(); out.chosen = chosen(tree); out.powers = powers(tree); out.shown = shown(tree);
""", work={"scale": {**mode(999)}, "problem": "no colour has been measured at this mode: there is nothing to predict from"})
    opened = out["opened"]
    assert opened["chosen"] == [False, False] and opened["sliders"] == 0 and opened["tone"]               # nothing to predict: no powers, no tone
    assert "В этом режиме цвет ещё не измерялся" in opened["text"] and "Шкала этой работы не измерена: выберите шкалу слева." in opened["text"]
    assert out["saves"] == [{"scale": mode(100)}] and out["chosen"] == [False, True] and out["powers"] == ["2", "25"]
    assert out["shown"] == "/api/photo-works/7/preview.png?v=1"


# -- the grey-scales page ---------------------------------------------------------------------------------------------------------------
@node
def test_the_grey_scales_page_shows_each_scale_and_makes_a_new_work_on_the_chosen_one(tmp_path):
    out = run(tmp_path, {"scales": "1"}, """
  out.first = {chosen: chosen(tree), powers: powers(tree), table: tree.textContent.includes('Серый картинки (0–255)'), works: requests.some((r) => r.path.startsWith('/api/photo-works'))};
  const sizeButtons = (t) => t.querySelectorAll('button').filter((b) => (b.getAttribute('title') || '').startsWith('измерено гравировок'));
  out.widths = sizeButtons(tree).map((b) => [b.textContent, b.getAttribute('aria-pressed')]);
  await button(tree, '38,4 мм').dispatch('click'); await settle();
  out.asked = requests.filter((r) => r.path === '/api/grey-scales/scale').map((r) => new URLSearchParams(r.url.split('?')[1]).get('row_mm'));
  out.pressed = sizeButtons(tree).map((b) => b.getAttribute('aria-pressed'));
  await pickScale(tree, 1); await settle();
  out.second = {chosen: chosen(tree), powers: powers(tree)};
  await button(tree, 'Новая работа на этой шкале').dispatch('click'); await settle();
  const box = dialog();
  const file = input(box, (i) => i.getAttribute('type') === 'file');
  file.files = [{name: 'girl.png', size: 2048}]; await file.dispatch('change');
  await button(box, 'Дальше →').dispatch('click'); await settle();
  out.sent = requests.filter((r) => r.path === '/api/photo-works' && r.method === 'POST').map((r) => r.body);
  out.tiles = dialog().querySelectorAll('button.ge-kind').length;
  await button(dialog(), 'Создать в «Градации серого»').dispatch('click'); await settle();
  out.went = ctx.__went; out.saved = saves();
""", work={"id": 9})
    assert out["first"] == {"chosen": [True, False], "powers": ["1", "30"], "table": True, "works": False}
    assert out["widths"] == [["38,4 мм", "false"], ["150 мм", "true"]]                    # shown at the size most measured, the others a click away
    assert out["asked"] == ["150", "38.4"] and out["pressed"] == ["true", "false"]
    assert out["second"] == {"chosen": [False, True], "powers": ["2", "25"]}
    sent = out["sent"][0]
    assert json.loads(sent.pop("scale")) == mode(100) and sent == {"picture": "girl.png", "name": "girl", "width_mm": "50"}
    assert out["tiles"] == 10 and out["went"] == ["/photo-engraving?work=9"] and out["saved"] == []    # grayscale: nothing to change


# -- the AI tab: the parts and their rules (REQ-062) -------------------------------------------------------------------------------------
@node
def test_the_ai_tab_shows_the_parts_and_a_rule_set_by_hand_is_saved_with_its_target_colour(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  out.table = tree.textContent.includes('Кожа лица') && tree.textContent.includes('Одежда') && tree.textContent.includes('50 %');
  out.overlay = tree.querySelectorAll('img').some((i) => i.getAttribute('src') === '/api/photo-works/7/parts.png?v=1');
  const clothes = select(tree, 'Правило: Одежда');
  out.before = clothes.value;
  clothes.value = 'even'; await clothes.dispatch('change'); await settle();
  const colour = input(tree, (i) => i.getAttribute('aria-label') === 'Цвет-цель: Одежда');
  out.colour = colour.value;
  colour.value = '#ff0000'; await colour.dispatch('change'); await settle();
  const face = select(tree, 'Правило: Кожа лица');
  face.value = 'neutral'; await face.dispatch('change'); await settle();
  select(tree, 'Правило: Одежда').value = 'as_is'; await select(tree, 'Правило: Одежда').dispatch('change'); await settle();
  out.saves = saves();
""")
    assert out["table"] and out["overlay"] and out["before"] == "as_is" and out["colour"] == "#3355aa"      # the part's own colour to start from
    assert out["saves"] == [{"rules": [{"part": "clothes", "kind": "even", "hex": "#3355aa"}]},
                            {"rules": [{"part": "clothes", "kind": "even", "hex": "#ff0000"}]},
                            {"rules": [{"part": "clothes", "kind": "even", "hex": "#ff0000"}, {"part": "face_skin", "kind": "neutral"}]},
                            {"rules": [{"part": "face_skin", "kind": "neutral"}]}]                       # "as it is" is no rule


@node
def test_asking_the_ai_sends_the_wish_shows_its_note_and_the_answer_is_undone_from_the_head(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  await button(tree, 'Попросить AI').dispatch('click'); await settle();
  out.empty = {asks: asks().length, text: tree.textContent.includes('Напишите, что AI должен изменить в картинке.')};
  const permission = input(tree, (i) => i.getAttribute('type') === 'checkbox' && i.parentNode.textContent.includes('уменьшенную картинку'));
  permission.checked = true; await permission.dispatch('change'); await settle();
  const wish = tree.querySelectorAll('textarea')[0];
  wish.value = ' платье сделать фиолетовым '; await button(tree, 'Попросить AI').dispatch('click'); await settle();
  out.asked = {asks: asks(), note: tree.textContent.includes('AI: платье фиолетовым, остальное как есть'), photo: tree.textContent.includes(', с картинкой'),
               rule: select(tree, 'Правило: Одежда').value, shown: shown(tree)};
  await button(tree, 'Отменить').dispatch('click'); await settle();
  out.back = {saves: saves(), undo: requests.filter((r) => r.path.endsWith('/undo')).length, rule: select(tree, 'Правило: Одежда').value,
              note: tree.textContent.includes('AI: '), redo: !button(tree, 'Повторить').disabled};
""")
    assert out["empty"] == {"asks": 0, "text": True}
    assert out["asked"] == {"asks": [{"wish": " платье сделать фиолетовым ", "fresh": False}], "note": True, "photo": True, "rule": "colour",
                            "shown": "/api/photo-works/7/preview.png?v=2"}
    assert out["back"] == {"saves": [{"ai_photo": True}], "undo": 1, "rule": "as_is", "note": False, "redo": True}


@node
def test_without_a_key_the_ai_button_is_off_and_says_why_while_rules_can_still_be_set(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  out.disabled = button(tree, 'Попросить AI').disabled;
  out.text = tree.textContent.includes('AI выключен: не задан ключ OpenAI (его вводят на экране «Сеть»)');
  const clothes = select(tree, 'Правило: Одежда');
  clothes.value = 'photo'; await clothes.dispatch('change'); await settle();
  out.saves = saves();
""", work={"ai_missing": "key"})
    assert out == {"disabled": True, "text": True, "saves": [{"rules": [{"part": "clothes", "kind": "photo"}]}]}


# -- undo and redo, the AI from the plain picture (0.19.2) --------------------------------------------------------------------------------
@node
def test_undo_and_redo_in_the_head_bring_the_work_back_with_its_min_and_max_and_follow_ctrl_z(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  ctx.document.body.append(tree);
  out.start = {undo: button(tree, 'Отменить').disabled, redo: button(tree, 'Повторить').disabled, powers: powers(tree)};
  const max = labelled(tree, 'Max мощность, % (чёрный)');
  max.value = '25'; await max.dispatch('change'); await wait(300); await settle();
  out.changed = {saves: saves(), powers: powers(tree), undo: button(tree, 'Отменить').disabled};
  await button(tree, 'Отменить').dispatch('click'); await settle();
  out.undone = {powers: powers(tree), undo: button(tree, 'Отменить').disabled, redo: button(tree, 'Повторить').disabled};
  await press({key: 'z', ctrlKey: true, shiftKey: true}); await settle();
  out.redone = powers(tree);
  await press({key: 'z', metaKey: true, target: tree.querySelectorAll('textarea')[0]}); await settle();
  out.typing = powers(tree);
  await press({key: 'z', ctrlKey: true}); await settle();
  out.keyed = powers(tree);
  out.steps = requests.filter((r) => /[/](undo|redo)$/.test(r.path)).map((r) => r.path.split('/').pop());
""")
    assert out["start"] == {"undo": True, "redo": True, "powers": ["12", "28"]}
    assert out["changed"] == {"saves": [{"min_power": 12, "max_power": 25}], "powers": ["12", "25"], "undo": False}
    assert out["undone"] == {"powers": ["12", "28"], "undo": True, "redo": False}                    # the sliders follow the work
    assert out["redone"] == ["12", "25"] and out["typing"] == ["12", "25"] and out["keyed"] == ["12", "28"]
    assert out["steps"] == ["undo", "redo", "undo"]                                                   # Ctrl+Z in a text field is the field's


@node
def test_the_ai_can_start_again_from_the_picture_and_every_part_can_be_put_back_as_it_is(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  out.plainOff = button(tree, 'Все части как есть').disabled;
  tree.querySelectorAll('textarea')[0].value = 'платье фиолетовым';
  await button(tree, 'Заново с картинки').dispatch('click'); await settle();
  out.asked = {asks: asks(), again: tree.textContent.includes(', заново с картинки'), plainOff: button(tree, 'Все части как есть').disabled};
  await button(tree, 'Все части как есть').dispatch('click'); await settle();
  out.plain = {saves: saves(), rule: select(tree, 'Правило: Одежда').value, plainOff: button(tree, 'Все части как есть').disabled};
""")
    assert out["plainOff"] is True
    assert out["asked"] == {"asks": [{"wish": "платье фиолетовым", "fresh": True}], "again": True, "plainOff": False}
    assert out["plain"] == {"saves": [{"rules": []}], "rule": "as_is", "plainOff": True}


# -- the engravings of the work (0.19.3) ------------------------------------------------------------------------------------------------
def band(gray, power, de, hex_, predicted_hex):
    return {"gray": gray, "power": power, "de": de, "lab": [50, 0, 0], "predicted": [50, 0, 0], "hex": hex_, "predicted_hex": predicted_hex}


ENGRAVINGS = [
    {"pair_id": 41, "status": "Awaiting check", "photo_name": "IMG_2.dng", "lightburn_name": "Портрет.lbrn2", "created_at": "2026-10-22T09:00:00",
     "accepted_at": None, "settings": None, "same_scale": None, "mode": None, "check": None},
    {"pair_id": 40, "status": "Accepted", "photo_name": "IMG_1.dng", "lightburn_name": "Портрет.lbrn2", "created_at": "2026-10-22T08:00:00",
     "accepted_at": "2026-10-22T08:10:00", "settings": {"power_range": [12, 28]}, "same_scale": True, "mode": None,
     "check": {"reason": None, "compared": 3, "median_de": 2.4, "max_de": 7.5, "within": 0.667, "confirmed": True, "others": 1, "tolerance_de": 5.0,
               "bands": [band(0.0, 28, 2.4, "#223344", "#203040"), band(1.0, 12, 1.1, "#ddccbb", "#ddcabb"), band(0.5, 20, 7.5, "#886644", "#776655")]}},
    {"pair_id": 39, "status": "Accepted", "photo_name": "IMG_0.dng", "lightburn_name": "Портрет.lbrn2", "created_at": "2026-10-21T08:00:00",
     "accepted_at": "2026-10-21T08:10:00", "settings": {"power_range": [12, 28]}, "same_scale": False,
     "mode": {"speed": 250, "frequency": 60, "pulse_width": 300, "line_interval": 0.0169, "passes": 1},
     "check": {"reason": "alone", "compared": 0, "bands": []}},
]


@node
def test_the_confirmation_tab_shows_the_works_engravings_predicted_beside_engraved_and_the_upload_for_it(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  const links = tree.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
  out.upload = links.find(([t]) => t === 'Загрузить фото гравировки');
  out.pairs = links.filter(([t]) => t.startsWith('№')).map(([t, href]) => [t, href]);
  const text = tree.textContent;
  out.text = ['ждёт проверки', 'подтверждает прогноз: медиана 2,4 ΔE', 'сравнено серых 3', 'по 1 другой гравировке',
    'Выгравирована с другими настройками, чем шкала работы: 250 мм/с', 'Других гравировок с этими настройками нет'].map((t) => text.includes(t));
  const strips = tree.querySelectorAll('div').filter((d) => (d.className || '') === 'ge-strip ge-compare');
  out.strips = strips.map((st) => st.children.map((c) => c.getAttribute('style')));
""", engravings=ENGRAVINGS)
    assert out["upload"] == ["Загрузить фото гравировки", "#/ingest?plan=7&material=3"]
    assert out["pairs"] == [["№41 · IMG_2.dng", "#/ingest?pair=41"], ["№40 · IMG_1.dng", "#/analysis/40"], ["№39 · IMG_0.dng", "#/analysis/39"]]
    assert out["text"] == [True] * 6
    assert out["strips"] == [["background:#ddcabb", "background:#776655", "background:#203040"],          # white (Min) first
                             ["background:#ddccbb", "background:#886644", "background:#223344"]]


# -- the kind of engraving (0.21.0) ----------------------------------------------------------------------------------------------------
@node
def test_the_kind_button_of_a_work_shows_its_picture_in_each_kind_and_a_dot_kind_has_one_power_picked_on_the_scale_strip(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  out.before = !!dialog();
  await tree.querySelectorAll('button').find((b) => b.textContent.startsWith('Вид:')).dispatch('click'); await settle();
  const box = dialog();
  const tiles = () => box.querySelectorAll('button.ge-kind');
  out.title = box.querySelector('h3').textContent;
  out.tiles = tiles().map((b) => b.querySelector('strong').textContent);
  out.pictures = tiles().map((b) => b.querySelector('img').getAttribute('src'));
  out.current = tiles().filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.querySelector('strong').textContent + ' ' + b.querySelector('.pill').textContent);
  out.estimates = tiles().map((b) => b.textContent.includes('оценка'));
  out.keep = !!button(box, 'Закрыть');
  await tiles().find((b) => b.querySelector('strong').textContent === 'Джарвис').dispatch('click'); await settle();
  out.closed = !dialog();
  out.kind = tree.querySelectorAll('button').find((b) => b.textContent.startsWith('Вид:')).textContent;
  out.minMax = !!labelled(tree, 'Min мощность, % (белый)');
  out.dot = labelled(tree, 'Мощность точек, %').value;
  out.byColour = input(tree, (i) => i.getAttribute('type') === 'checkbox' && !i.getAttribute('aria-label')).disabled;
  out.closeup = tree.querySelectorAll('img').some((i) => (i.getAttribute('src') || '').includes('/closeup.png'));
  out.says = ['Каждая точка бьёт на 12,5 %', 'Это оценка', 'в режиме «Джарвис»: мощность 12,5 % (Min = Max'].map((t) => tree.textContent.includes(t));
  out.ramp = !!button(tree, 'Проба этого вида') && tree.textContent.includes('в виде «Джарвис» на мощности точек 12,5 %');
  await tree.querySelector('.ge-strip.ge-pickable').dispatch('click', {clientX: 75}); await wait(300); await settle();
  out.mark = tree.querySelector('.ge-dotmark').getAttribute('style');
  await button(tree, 'Отменить').dispatch('click'); await settle();
  out.undone = tree.querySelectorAll('button').find((b) => b.textContent.startsWith('Вид:')).textContent;
  out.saved = saves();
""")
    assert not out["before"] and out["title"] == "Какая гравировка?"                     # an existing work asks only when the button is clicked
    assert out["tiles"] == ["Градации серого", "Порог", "Упорядоченный (Байер)", "Аткинсон", "Растр (Флойд-Стейнберг)", "Стаки", "Джарвис",
                            "Газетный растр", "Полутона", "Эскиз"]
    assert out["pictures"][6] == "/api/photo-works/7/kinds/jarvis.png?v=1" and out["current"] == ["Градации серого сейчас"] and out["keep"]
    assert out["estimates"] == [False] + [True] * 9                                       # grayscale is measured, the dot kinds estimated
    assert out["closed"] and out["kind"] == "Вид: Джарвис" and not out["minMax"] and out["dot"] == "12.5"
    assert out["byColour"] and out["closeup"] and out["says"] == [True, True, True] and out["ramp"]
    # the strip runs over the scale's measured powers 1..30 %: a click at three quarters of it is 22.75 %, rounded to 0.1 %
    assert out["saved"] == [{"kind": "jarvis"}, {"dot_power": 22.8}] and out["mark"].startswith("left:75.172")
    assert out["undone"] == "Вид: Джарвис"                                                # undo takes back the power first


@node
def test_the_colouring_tab_colours_an_object_with_a_click_on_the_scales_colours_and_themes_and_the_ai_colour_all_of_them(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  const objects = () => tree.querySelectorAll('li.ge-object');
  const row = (name) => objects().find((li) => li.childNodes[0].textContent.trim() === name);
  const swatch = (label) => tree.querySelectorAll('button.ge-swatch').find((b) => b.getAttribute('aria-label') === label);
  const posts = (end) => requests.filter((r) => r.path.endsWith(end)).map((r) => r.body);
  out.listed = objects().map((li) => li.childNodes[0].textContent.trim());
  out.first = {current: row('Фон').getAttribute('aria-current'), auto: row('Губы').textContent.includes('авто'), swatches: tree.querySelectorAll('button.ge-swatch').length,
               note: tree.textContent.includes('Глаз за очками или чем-то надетым: 1'), overlay: tree.querySelectorAll('img').some((i) => i.getAttribute('src') === '/api/photo-works/7/objects.png?v=1')};
  await row('Губы').dispatch('click'); await settle();
  out.selected = row('Губы').getAttribute('aria-current');
  await swatch('Цвет шкалы 12,15 %').dispatch('click'); await settle();
  out.coloured = {chosen: swatch('Цвет шкалы 12,15 %').className.includes('is-chosen'), text: row('Губы').textContent.includes('12,15 %'),
                  choice: select(tree, 'Как подбирать серые').value, said: tree.textContent.includes('Раскраска по объектам: в своих цветах 1 объект')};
  const shift = input(tree, (i) => i.getAttribute('aria-label') === 'Светлее или темнее: Губы');
  shift.value = '-0.5'; await shift.dispatch('change'); await settle();
  await button(tree, 'Тёплая').dispatch('click'); await settle();
  await button(tree, 'Случайно').dispatch('click'); await settle();
  await button(row('Другое (очки…)'), 'Авто').dispatch('click'); await settle();
  tree.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'Как раскрасить — своими словами').value = ' очки золотом ';
  await button(tree, 'Раскрасить по просьбе').dispatch('click'); await settle();
  out.saves = saves();
  out.themes = posts('/theme').map((b) => [b.name, typeof b.seed]);
  out.ai = {asks: posts('/ai-theme'), note: tree.textContent.includes('AI: очки золотом, губы красные')};
  await button(tree, 'Всё — авто').dispatch('click'); await settle();
  out.cleared = saves().slice(-1)[0];
""")
    assert out["listed"] == ["Фон", "Фон 2", "Кожа лица", "Другое (очки…)", "Губы"]
    assert out["first"] == {"current": "true", "auto": True, "swatches": 4, "note": True, "overlay": True}
    assert out["selected"] == "true" and out["coloured"] == {"chosen": True, "text": True, "choice": "objects", "said": True}
    objects_on = {"by_colour": True, "colour_choice": "objects"}
    assert out["saves"] == [{**objects_on, "colouring": {"lips": {"power": 12.15, "shift": 0}}},
                            {**objects_on, "colouring": {"lips": {"power": 12.15, "shift": -0.5}}},
                            {**objects_on, "colouring": {}}]                                          # «Авто» on the random theme's only object
    assert out["themes"] == [["warm", "undefined"], ["random", "number"]]                             # «Случайно»: new colours each time
    assert out["ai"] == {"asks": [{"wish": " очки золотом "}], "note": True}
    assert out["cleared"] == {**objects_on, "colouring": {}}


VIOLET = {"entry": "a1b2c3d4e5f6", "settings": {"power": 20, "speed": 500, "frequency": 60, "pulse_width": 300, "line_interval": 0.02, "passes": 1,
                                                "global_passes": 1},
          "lab": [50.0, 12.0, -25.0], "size": {"row_mm": 60, "how": "between", "measured_mm": [40, 80], "from_mm": [40, 80]}, "engravings": 2,
          "photographs": 2, "basis": "chart", "picked_at": "2026-10-23T12:00:00", "missing": False}


@node
def test_a_dot_kind_takes_its_dots_colour_from_the_colour_map_and_goes_back_to_the_scale(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  out.onScale = {map: !!button(tree, 'Цвет с карты'), slider: !!labelled(tree, 'Мощность точек, %'), mark: !!tree.querySelector('.ge-dotmark'),
                 says: tree.textContent.includes('Любой другой измеренный цвет — «Цвет с карты»')};
  await button(tree, 'Цвет с карты').dispatch('click'); await settle();
  out.went = [...ctx.__went];
""", work={"kind": "jarvis", "dot_power": 12.5})
    assert out["onScale"] == {"map": True, "slider": True, "mark": True, "says": True}
    assert out["went"] == ["/colors?dots=7&setup=laser%3A1%2Flens%3A2"]                    # the map of the work's laser and lens


@node
def test_dots_with_a_colour_from_the_map_show_its_settings_and_go_back_to_the_scale_at_the_power_they_had(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  const text = () => tree.textContent;
  out.mapped = {source: tree.querySelector('.ge-dotsource').textContent, slider: !!labelled(tree, 'Мощность точек, %'), mark: !!tree.querySelector('.ge-dotmark'),
                ends: tree.querySelectorAll('.ge-ends').slice(-1)[0].textContent, title: tree.querySelector('.ge-settings').textContent,
                says: ['оценка по карте цветов', 'на настройках цвета, выбранного на карте цветов', 'Цвет точки взят с карты цветов',
                       'мощность 20 % (Min = Max — каждая точка бьёт на ней), 500 мм/с · 60 кГц · 300 нс · шаг 0,02 мм (1000 dpi) · проходов 1 — настройки цвета с карты цветов',
                       '60 мм: между измерениями 40 и 80 мм', 'на настройках цвета с карты (500 мм/с'].map((t) => text().includes(t))};
  await button(tree, 'Другой цвет').dispatch('click'); await settle();
  out.went = [...ctx.__went];
  await button(tree, 'На шкалу').dispatch('click'); await settle();
  out.back = {saved: saves(), source: tree.querySelector('.ge-dotsource').textContent, slider: labelled(tree, 'Мощность точек, %').value,
              mark: !!tree.querySelector('.ge-dotmark'), title: tree.querySelector('.ge-settings').textContent};
""", work={"kind": "jarvis", "dot_power": 12.5, "dot_recipe": VIOLET})
    m = out["mapped"]
    assert m["source"] == "Точкис карты цветов: 20 % · 500 мм/с · 60 кГц · 300 нс · шаг 0,02 мм (1000 dpi) · проходов 1Другой цветНа шкалу"
    assert not m["slider"] and not m["mark"] and m["ends"] == "1 %точки — с карты цветов30 %" and m["says"] == [True] * 6
    assert m["title"].startswith("шкала: 100 мм/с") and m["title"].endswith("точки — на настройках цвета с карты цветов")
    assert out["went"] == ["/colors?dots=7&setup=laser%3A1%2Flens%3A2"]
    assert out["back"] == {"saved": [{"dot_power": 12.5}], "source": "Цвет с карты", "slider": "12.5", "mark": True,
                           "title": "100 мм/с · 60 кГц · 250 нс · шаг 0,0254 мм (1000 dpi) · проходов 1"}


@node
def test_the_brightness_contrast_and_gamma_of_a_photo_work_are_saved_and_said_in_its_details(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  const B = 'Яркость картинки, %: меньше нуля — темнее, больше — светлее';
  const brightness = labelled(tree, B);
  const work = tree.querySelector('.ge-tone').parentNode; out.under = [work.className, work.children.indexOf(tree.querySelector('.ge-tone')) - work.children.indexOf(tree.querySelector('.ge-inputs'))];
  brightness.value = '-15'; await brightness.dispatch('change'); await wait(350); await settle();
  out.saves = saves();
  out.said = tree.textContent.includes('Картинка изменена: яркость -15 %, контраст 0 %, гамма 1.');
""", work={"kind": "jarvis", "dot_power": 12.5, "tone": {"brightness": -15, "contrast": 0, "gamma": 1}, "tone_used": True})
    assert out["under"] == ["ge-work", 1] and out["saves"] == [{"tone": {"brightness": -15, "contrast": 0, "gamma": 1}}] and out["said"]


@node
def test_a_tone_slider_dragged_saves_once_when_it_pauses_as_it_is_puts_the_picture_back_and_the_forecast_follows(tmp_path):
    """photo-zone-dots REQ-002 crit. 1: the sliders' own movement (their 'input' events) and «Как есть» on the photo work screen."""
    out = run(tmp_path, {"work": "7"}, """
  const B = 'Яркость картинки, %: меньше нуля — темнее, больше — светлее', C = 'Контраст картинки, %: больше нуля — светлое светлее и тёмное темнее',
        G = 'Гамма картинки: меньше 1 — средние тона светлее, больше 1 — темнее';
  const range = (label) => input(tree, (i) => i.getAttribute('aria-label') === label && i.getAttribute('type') === 'range');
  const both = () => [B, C, G].map((label) => [range(label).value, labelled(tree, label).value]);
  out.start = {sliders: [B, C, G].map((label) => [range(label).getAttribute('min'), range(label).getAttribute('max')]), values: both(),
               reset: button(tree, 'Как есть').disabled, shown: shown(tree)};
  for (const step of ['5', '10', '15', '20']) { range(B).value = step; await range(B).dispatch('input'); await wait(60); }
  out.dragging = {values: both(), saves: saves().length};
  await wait(350); await settle();
  out.paused = {values: both(), saves: saves().length, reset: button(tree, 'Как есть').disabled, shown: shown(tree)};
  range(G).value = '1.5'; await range(G).dispatch('input'); await wait(350); await settle();
  out.gamma = {values: both(), shown: shown(tree)};
  await button(tree, 'Как есть').dispatch('click'); await settle();
  out.reset = {values: both(), reset: button(tree, 'Как есть').disabled, shown: shown(tree)};
  out.saves = saves();
""")
    assert out["start"] == {"sliders": [["-100", "100"], ["-100", "100"], ["0.2", "5"]], "values": [["0", "0"], ["0", "0"], ["1", "1"]],
                            "reset": True, "shown": "/api/photo-works/7/preview.png?v=0"}
    assert out["dragging"] == {"values": [["20", "20"], ["0", "0"], ["1", "1"]], "saves": 0}                # the number follows, nothing sent yet
    assert out["paused"] == {"values": [["20", "20"], ["0", "0"], ["1", "1"]], "saves": 1, "reset": False,
                             "shown": "/api/photo-works/7/preview.png?v=1"}                              # one change, the forecast follows
    assert out["gamma"] == {"values": [["20", "20"], ["0", "0"], ["1.5", "1.5"]], "shown": "/api/photo-works/7/preview.png?v=2"}
    assert out["reset"] == {"values": [["0", "0"], ["0", "0"], ["1", "1"]], "reset": True, "shown": "/api/photo-works/7/preview.png?v=3"}
    assert out["saves"] == [{"tone": {"brightness": 20, "contrast": 0, "gamma": 1}}, {"tone": {"brightness": 20, "contrast": 0, "gamma": 1.5}},
                            {"tone": {"brightness": 0, "contrast": 0, "gamma": 1}}]


@node
def test_a_dot_kind_corrects_the_dot_width_with_a_tick_and_a_width_in_mm_and_grayscale_hides_it(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  const box = () => tree.querySelector('.ge-dotwidth');
  const tick = () => input(box(), (i) => i.getAttribute('type') === 'checkbox');
  const width = () => labelled(tree, 'Ширина точки лазера, мм');
  out.first = [box().hidden, tick().checked, width().value];
  tick().checked = true; await tick().dispatch('change'); await settle();
  out.empty = saves().length;
  width().value = '0.02'; await width().dispatch('change'); await settle();
  out.on = [tick().checked, width().value];
  out.ramp = tree.textContent.includes('на мощности точек 12,5 %, с поправкой ширины точки 0,02 мм и настройках шкалы');
  tick().checked = false; await tick().dispatch('change'); await settle();
  out.off = [tick().checked, width().value];
  tick().checked = true; await tick().dispatch('change'); await settle();
  out.waits = saves().length;
  width().value = '0.025'; await width().dispatch('change'); await settle();
  width().value = ''; await width().dispatch('change'); await settle();
  out.saves = saves();
  await button(tree, 'Отменить').dispatch('click'); await settle();
  out.undone = [tick().checked, width().value];
  await tree.querySelectorAll('button').find((b) => b.textContent.startsWith('Вид:')).dispatch('click'); await settle();
  await dialog().querySelectorAll('button.ge-kind').find((b) => b.querySelector('strong').textContent === 'Градации серого').dispatch('click'); await settle();
  out.grey = box().hidden;
""", work={"kind": "jarvis", "dot_power": 12.5, "dot_width": None})
    assert out["first"] == [False, False, ""] and out["empty"] == 0                       # off; a tick on an empty field waits for the width
    assert out["on"] == [True, "0.02"] and out["ramp"]                                    # a width switches it on; the ramp is engraved with it
    assert out["off"] == [False, "0.02"]                                                  # untick: off, the width stays in the field
    assert out["waits"] == 3                                                              # a tick with the width in the field sends it
    assert out["saves"] == [{"dot_width": 0.02}, {"dot_width": None}, {"dot_width": 0.02}, {"dot_width": 0.025}, {"dot_width": None}]
    assert out["undone"] == [True, "0.025"] and out["grey"]


def test_the_laboratory_says_what_it_knows_of_the_kind_and_a_step_darker_and_the_plate_it_proposes_are_made_from_the_work(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  const box = () => tree.querySelector('.pq-advisor');
  out.says = box().textContent;
  out.titles = Object.fromEntries(box().querySelectorAll('button').map((b) => [b.textContent, b.getAttribute('title')]));
  await box().querySelectorAll('button').find((b) => b.textContent === 'Темнее').dispatch('click'); await settle();
  await box().querySelectorAll('button').find((b) => b.textContent === 'Чётче').dispatch('click'); await settle();
  await box().querySelectorAll('button').find((b) => b.textContent === 'Взять лучшие настройки').dispatch('click'); await settle();
  out.saves = saves();
  await box().querySelectorAll('button').find((b) => b.textContent === 'Сделать плату: 4 копии').dispatch('click'); await settle();
  out.plate = requests.filter((r) => r.path === '/api/photo-knowledge/plate').map((r) => r.body); out.went = ctx.__went.slice(-1);
""", work={"kind": "jarvis", "dot_power": 12.5, "dot_width": None}, advice=JARVIS_ADVICE)
    says = out["says"]
    assert "Что известно о виде «Джарвис» на этом лазере и титане" in says and "измерено, но не подобрано" in says
    assert "Лучшее измеренное: 22 %, 180 мм/с, 60 кГц, 250 нс, шаг 0,012 мм, поправка точки 0,02 мм — оценка 0,9 по фото №118." in says
    assert "мощность вдвое больше: темнее на 6 L*, оценка +0,1 (по фото №120)" in says
    assert out["titles"]["Темнее"] == "мощность 12,5 % → 17,5 % — измерено по фото №120"
    assert out["titles"]["Чётче"] == "поправка ширины точки выкл. → 0,01 мм — по опыту процесса: ещё не измерено"
    assert "Точки: 22 %, 180 мм/с, шаг 0,012 мм, поправка точки 0,02 мм." in says
    # what the proposed plate finds out and how big it is
    assert ("Копия 1 — центр, остальные меняют по одной настройке: мощность 22 % → 17,6 %; скорость 180 мм/с → 252 мм/с; вид Джарвис → Аткинсон; "
            "по фото станет видно, какая лучше. Плата 65 × 45 мм: 4 копии по 18 × 12 мм, под каждой полоска серого.") in says
    assert out["saves"] == [{"dot_settings": {**JARVIS, "power": 17.5}}, {"dot_width": 0.01}, {"dot_settings": JARVIS, "dot_width": 0.02}]
    assert out["plate"] == [{"device_id": 1, "lens_id": 2, "material_id": 3, "kind": "jarvis"}] and out["went"] == ["/experiment/plan-33"]


# the dots of a photographed Jarvis engraving standing in for Atkinson (photo_knowledge.recipe, DEC-006)
JARVIS_DOTS = {"entry": "photo:149:C20", "source": "photo", "settings": {**JARVIS, "power": 25.0, "speed": 125.0, "line_interval": 0.01},
               "lab": [36.3, -1.6, 5.0], "size": None, "engravings": 1, "photographs": 1, "basis": "picture", "missing": False,
               "picked_at": "2026-10-25T18:00:00", "photo": {"pair_id": 149, "layer": "C20", "kind": "jarvis", "score": 0.26, "findings": []}}


@node
def test_dots_taken_from_a_photographed_engraving_name_its_photograph_not_the_colour_map(tmp_path):
    """BUG-008: a work whose dots come from photo 149 (Jarvis) says so on the dots line, the scale's title, the bar, the foot and the file."""
    out = run(tmp_path, {"work": "7"}, """
  out.source = tree.querySelector('.ge-dotsource').textContent;
  out.ends = tree.querySelectorAll('.ge-ends').slice(-1)[0].textContent;
  out.title = tree.querySelector('.ge-settings').textContent;
  out.text = tree.textContent;
""", work={"kind": "atkinson", "dot_power": 12.5, "dot_recipe": JARVIS_DOTS})
    assert out["source"].startswith("Точкипо фото № 149 (Джарвис): 25 % · 125 мм/с")
    assert out["ends"] == "1 %точки — по фото № 149 (Джарвис)30 %"
    assert out["title"].endswith("точки — на настройках точек по фото № 149 (Джарвис)")
    text = out["text"]
    assert "с карты цветов" not in text.replace("Цвет с карты", "") and "оценка по шкале" not in text
    assert "оценка по фото № 149 (Джарвис): этот вид на этих настройках ещё не гравировался" in text
    assert "Это оценка: этот вид на этих настройках ещё не гравировался. Цвет точки — как на фото № 149 (Джарвис), где сфотографированы точки этих настроек." in text
    assert "— настройки точек по фото № 149 (Джарвис)." in text


# a kind whose every engraving on the titanium came out a negative (DEC-006): the dots of another kind stand in for its best
FLOP = {"settings": {"dither": "atkinson", "power": 10.2, "min_power": 10.2, "speed": 128.0}, "score": 0.0, "black_lab": [91.8, 1.2, 12.7],
        "tone": {"range_L": -0.1}, "source": {"pair_id": 147, "layer": "C26"}, "findings": [{"code": "flat", "value": -0.1}]}
FAILED_ADVICE = {**JARVIS_ADVICE, "kind": "atkinson", "status": "failed", "best": None, "failed": [FLOP], "dot_width": True,
                 "stand_in": {**JARVIS_ADVICE["best"], "source": {"pair_id": 149, "layer": "C20"}},
                 "take": {"dot_settings": JARVIS, "dot_width": 0.02}, "effects": {}}


def test_a_kind_that_came_out_a_negative_says_so_and_takes_the_dark_dots_of_another_kind(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  const box = () => tree.querySelector('.pq-advisor');
  out.says = box().textContent;
  await box().querySelectorAll('button').find((b) => b.textContent === 'Взять тёмные точки «Джарвис»').dispatch('click'); await settle();
  out.saves = saves();
  await box().querySelectorAll('button').find((b) => b.textContent === 'Сделать плату: 4 копии').dispatch('click'); await settle();
  out.plate = requests.filter((r) => r.path === '/api/photo-knowledge/plate').map((r) => r.body);
""", work={"kind": "atkinson", "dot_power": 10.2, "dot_width": None}, advice=FAILED_ADVICE)
    says = out["says"]
    assert "не получился" in says and "Лучшее измеренное" not in says and "ещё не фотографировался" not in says
    assert ("«Аткинсон» на этом титане не получился: фото № 147, 10,2 % — точки не темнее титана (L* 92): картинки не видно или она вышла "
            "негативом. Вместо них — лучшие тёмные точки вида «Джарвис» на этом титане: 22 %, 180 мм/с, 60 кГц, 250 нс, шаг 0,012 мм, "
            "поправка точки 0,02 мм — оценка 0,9 по фото №149; для «Аткинсон» это предположение, пока его не сфотографируют на этих точках.") in says
    assert "Лаборатория предлагает: та же картинка вокруг лучших точек другого вида." in says
    assert out["saves"] == [{"dot_settings": JARVIS, "dot_width": 0.02}]
    assert out["plate"] == [{"device_id": 1, "lens_id": 2, "material_id": 3, "kind": "atkinson", "dot_width": True}]


def test_a_grayscale_work_past_its_scales_turn_is_told_so_offered_no_step_and_takes_the_span_in_order(tmp_path):
    refused = {"refused": "Max lies past the power where this scale's tones turn back lighter: take the span in order first"}
    past = {**ADVICE, "current": {"dither": "grayscale", "power": 28.0, "min_power": 12.0}, "steps": {d: refused for d in ("darker", "lighter", "sharper", "softer")},
            "turn": {"min_power": 1.0, "max_power": 14.5, "past": True}, "take": {"min_power": 12.0, "max_power": 14.5}}
    out = run(tmp_path, {"work": "7"}, """
  const box = () => tree.querySelector('.pq-advisor');
  out.says = box().textContent;
  out.disabled = box().querySelectorAll('button').filter((b) => b.disabled).map((b) => b.textContent);
  await box().querySelectorAll('button').find((b) => b.textContent === 'Взять диапазон до разворота').dispatch('click'); await settle();
  out.saves = saves();
""", advice=past)
    assert "Max 28 % — дальше 14,5 %, где тона этой шкалы разворачиваются: там больше мощности — светлее, а не темнее" in out["says"]
    assert "Min 12 %, Max 14,5 %." in out["says"]
    assert out["disabled"] == ["Темнее", "Светлее", "Чётче", "Мягче"]
    assert out["saves"] == [{"min_power": 12.0, "max_power": 14.5}]


@node
def test_many_grey_scales_are_one_line_each_best_first_by_pages_and_a_scale_opens_its_card_only_on_a_click(tmp_path):
    """DEC-090: 22 measured scales show 20 lines in the server's order (the best first) and «Показать ещё 2»; only the chosen scale's card is
    open; another line opens its card, the card chooses the scale; «Быстрее» puts the fastest scale first."""
    scales = [{**scale(100 + i, [1, 30 - i]), "time_s_per_cm2": 90 - i} for i in range(22)]
    out = run(tmp_path, {"scales": "1"}, """
  const list = tree.querySelector('.ge-scale-list');
  out.lines = lines(tree).length; out.count = list.querySelector('.lst-count').textContent;
  out.more = list.querySelector('.lst-foot').querySelector('button').textContent;
  out.first = lines(tree).slice(0, 2).map((m) => m.textContent);
  out.cards = tree.querySelectorAll('button.ge-scale').length; out.chosen = chosen(tree).indexOf(true);
  await pickScale(tree, 3); await settle();
  out.after = {chosen: chosen(tree).indexOf(true), cards: tree.querySelectorAll('button.ge-scale').map((b) => b.getAttribute('aria-pressed')), powers: powers(tree)};
  const sort = list.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === 'Порядок');
  out.sorts = sort.querySelectorAll('option').map((o) => o.textContent);
  sort.value = 'fast'; await sort.dispatch('change'); await settle();
  out.fastest = lines(tree)[0].textContent;
""", work={"id": 9}, scales=scales)
    assert out["lines"] == 20 and out["count"] == "показано 20 из 22" and out["more"] == "Показать ещё 2"
    assert "100 мм/с" in out["first"][0] and "выбрана" in out["first"][0] and "101 мм/с" in out["first"][1]
    assert out["cards"] == 1 and out["chosen"] == 0                                                 # the chosen scale's card, nothing else
    assert out["after"]["chosen"] == 3 and out["after"]["cards"] == ["true"]
    assert out["sorts"] == ["Лучшие первыми", "Быстрее", "Шире диапазон мощности"]
    assert "121 мм/с" in out["fastest"]
