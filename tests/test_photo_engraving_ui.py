"""The photo engraving screens (REQ-059, REQ-061): the list of works, a new work, a work on one screen and the grey-scales page. Run in
node over the small DOM of the other screen tests, with a fake server that answers as the photo-work and grey-scale API do."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
SCRIPTS = ["app.js", "photo-modes.js", "dialogs.js", "hardware.js", "filepick.js"]
GLUE = ("const __screens = {}; App.register = (d) => { __screens[d.id] = d; }; App.render = () => {}; globalThis.__screens = __screens;"
        "globalThis.__went = []; App.go = (route) => { __went.push(route); };"
        "globalThis.FormData = class { constructor() { this.fields = []; } append(k, v) { this.fields.push([k, v]); } };")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context({});
load(ctx, %(ui)s, [...%(tables)s, ...%(scripts)s, {code: %(glue)s}, 'screens/vector-workspace.js', 'screens/photo-engraving.js']);
const requests = [], hold = [];
let work = data.work, version = 0;
const same = (a, b) => ['speed', 'line_interval', 'material_id'].every((k) => a[k] === b[k]);
const view = () => ({...work, picture: work.problem ? null : {preview: `/api/photo-works/${work.id}/preview.png?v=${version}`, by_colour: work.by_colour, colour_match: null,
  outside_share: 0, time: {seconds: 600}, size_mm: {width: work.width_mm, height: work.width_mm / 2}, power_range: [work.min_power, work.max_power], dpi: 1000, notes: []}});
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
    const next = {...work, ...body};
    if (body.scale) {
      const sc = data.scales.find((s) => same(s.mode, body.scale));
      Object.assign(next, {scale: sc.mode, min_power: sc.span[0], max_power: sc.span[1], problem: null});
    }
    work = next; version++;
    return answer(view());
  }
  if (path === `/api/photo-works/${work.id}/copy`) return answer({id: 8}, 201);
  if (path === `/api/photo-works/${work.id}/parts`) return answer(data.parts);
  if (path === `/api/photo-works/${work.id}/ai`) {
    if (hold.length) await hold.shift();
    work = {...work, rules: data.ai_rules, ai: {wish: body.wish.trim(), note: 'платье фиолетовым, остальное как есть', photo: work.ai_photo, before: work.rules}};
    version++;
    return answer(view());
  }
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


def run(tmp_path, query, body, work=None):
    work = {**WORK, **(work or {})}
    (tmp_path / "data.json").write_text(json.dumps({"scales": [scale(150, [1, 30]), scale(100, [2, 25])], "scale": scale_answer(), "work": work,
                                                    "works": [listed(work)], "parts": PARTS, "ai_rules": AI_RULES}), encoding="utf-8")
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
            "by_kind": {"grey ramp": 1}, "time_s_per_cm2": 70, "confirmation": {"engravings": 1, "median_de": None}, "reference": "chart"}


def scale_answer():
    levels = [{"level": g, "power": 30 - g * 29 / 255, "lab": [50, 0, 0], "hex": "#777777", "spread_de": None} for g in range(256)]
    return {"greys": {"levels": levels, "measured_levels": 256}, "confirmation": {"rows": [], "tolerance_de": 5, "engravings": 1, "median_de": None},
            "fill_points": [], "curve": {"points": []}, "notes": []}


WORK = {"id": 7, "name": "Портрет", "identifier": "TCE-P-1", "created_at": "2026-10-21T10:00:00", "updated_at": "2026-10-21T10:05:00",
        "image_name": "girl.png", "image_size": [240, 120], "scale": mode(100), "material": {"name": "Big Plate 150"}, "dpi": 1000,
        "min_power": 12, "max_power": 28, "width_mm": 60, "height_mm": 30, "by_colour": False, "time": {"seconds": 600}, "problem": None,
        "rules": [], "ai": None, "ai_photo": False, "ai_missing": None}
PARTS = {"parts": [{"part": "face_skin", "share": 0.5, "lab": [70, 10, 15], "hex": "#c8a08c", "tint": "#ff8c64"},
                   {"part": "clothes", "share": 0.5, "lab": [40, 0, -30], "hex": "#3355aa", "tint": "#4678ff"}], "picture": "/api/photo-works/7/parts.png?v=1"}
AI_RULES = [{"part": "clothes", "kind": "colour", "lab": [40, 40, -40], "hex": "#7a3fa0"}]


def listed(work):
    return {k: v for k, v in work.items() if k not in ("problem", "ai_missing")}


# -- the list and a new work -----------------------------------------------------------------------------------------------------------
@node
def test_the_list_shows_each_work_and_a_new_work_is_made_from_a_picture_a_name_and_a_width_and_opened(tmp_path):
    out = run(tmp_path, {}, """
  out.cards = tree.querySelectorAll('article.vw-work-card').map((c) => c.textContent);
  out.thumb = tree.querySelector('a.vw-thumb').children[0].getAttribute('src');
  await button(tree, 'Новая работа').dispatch('click'); await settle();
  const box = dialog();
  const file = input(box, (i) => i.getAttribute('type') === 'file');
  file.files = [{name: 'moto.jpg', size: 4096}]; await file.dispatch('change');
  out.name = labelled(box, 'Название работы').value;
  labelled(box, 'Ширина на титане, мм').value = '80';
  await button(box, 'Создать').dispatch('click'); await settle();
  out.sent = requests.filter((r) => r.path === '/api/photo-works' && r.method === 'POST').map((r) => r.body);
  out.went = ctx.__went; out.open = !!dialog();
""")
    card = out["cards"][0]
    assert "Портрет" in card and "60 × 30 мм" in card and "Min 12 % · Max 28 %" in card and "100 мм/с" in card
    assert out["thumb"] == "/api/photo-works/7/thumb.png?v=2026-10-21T10%3A05%3A00"
    assert out["name"] == "moto"                                              # the name follows the picture until the operator types one
    assert out["sent"] == [{"picture": "moto.jpg", "name": "moto", "width_mm": "80"}]   # no scale: the best measured one is taken
    assert out["went"] == ["/photo-engraving?work=9"] and not out["open"]


# -- a work -----------------------------------------------------------------------------------------------------------------------------
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
  width.value = '0'; await width.dispatch('change'); await settle();
  out.refused = {width: width.value, error: tree.querySelectorAll('p.alert').filter((p) => !p.hidden).map((p) => p.textContent)};
""")
    opened = out["opened"]
    assert opened["chosen"] == [False, True] and opened["powers"] == ["12", "28"] and opened["width"] == "60" and opened["title"] == "Портрет"
    assert opened["shown"] == "/api/photo-works/7/preview.png?v=0"
    assert out["saves"] == [{"min_power": 12, "max_power": 20}, {"width_mm": 100}, {"by_colour": True}]
    assert out["shown"] == "/api/photo-works/7/preview.png?v=3" and out["size"]
    assert out["refused"] == {"width": "100", "error": ["Ширина картинки должна быть от 1 до 1000 мм"]}   # refused: the work stays as it was


@node
def test_another_scale_is_saved_in_the_work_the_picture_stays_and_min_and_max_become_the_new_scales_span(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  await tree.querySelectorAll('button.ge-scale')[0].dispatch('click'); await settle(); await wait(300); await settle();
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
  out.opened = {chosen: chosen(tree), text: tree.textContent, sliders: tree.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'range').length};
  await tree.querySelectorAll('button.ge-scale')[1].dispatch('click'); await settle(); await wait(300); await settle();
  out.saves = saves(); out.chosen = chosen(tree); out.powers = powers(tree); out.shown = shown(tree);
""", work={"scale": {**mode(999)}, "problem": "no colour has been measured at this mode: there is nothing to predict from"})
    opened = out["opened"]
    assert opened["chosen"] == [False, False] and opened["sliders"] == 0
    assert "В этом режиме цвет ещё не измерялся" in opened["text"] and "Шкала этой работы не измерена: выберите шкалу слева." in opened["text"]
    assert out["saves"] == [{"scale": mode(100)}] and out["chosen"] == [False, True] and out["powers"] == ["2", "25"]
    assert out["shown"] == "/api/photo-works/7/preview.png?v=1"


# -- the grey-scales page ---------------------------------------------------------------------------------------------------------------
@node
def test_the_grey_scales_page_shows_each_scale_and_makes_a_new_work_on_the_chosen_one(tmp_path):
    out = run(tmp_path, {"scales": "1"}, """
  out.first = {chosen: chosen(tree), powers: powers(tree), table: tree.textContent.includes('Серый картинки (0–255)'), works: requests.some((r) => r.path.startsWith('/api/photo-works'))};
  await tree.querySelectorAll('button.ge-scale')[1].dispatch('click'); await settle();
  out.second = {chosen: chosen(tree), powers: powers(tree)};
  await button(tree, 'Новая работа на этой шкале').dispatch('click'); await settle();
  const box = dialog();
  const file = input(box, (i) => i.getAttribute('type') === 'file');
  file.files = [{name: 'girl.png', size: 2048}]; await file.dispatch('change');
  await button(box, 'Создать').dispatch('click'); await settle();
  out.sent = requests.filter((r) => r.path === '/api/photo-works' && r.method === 'POST').map((r) => r.body);
  out.went = ctx.__went;
""")
    assert out["first"] == {"chosen": [True, False], "powers": ["1", "30"], "table": True, "works": False}
    assert out["second"] == {"chosen": [False, True], "powers": ["2", "25"]}
    sent = out["sent"][0]
    assert json.loads(sent.pop("scale")) == mode(100) and sent == {"picture": "girl.png", "name": "girl", "width_mm": "50"}
    assert out["went"] == ["/photo-engraving?work=9"]


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
def test_asking_the_ai_sends_the_wish_shows_its_note_and_the_rules_before_can_be_put_back(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  await button(tree, 'Попросить AI').dispatch('click'); await settle();
  out.empty = {asks: asks().length, text: tree.textContent.includes('Напишите, что AI должен изменить в картинке.')};
  const permission = input(tree, (i) => i.getAttribute('type') === 'checkbox' && i.parentNode.textContent.includes('уменьшенную картинку'));
  permission.checked = true; await permission.dispatch('change'); await settle();
  const wish = tree.querySelectorAll('textarea')[0];
  wish.value = ' платье сделать фиолетовым '; await button(tree, 'Попросить AI').dispatch('click'); await settle();
  out.asked = {asks: asks(), note: tree.textContent.includes('AI: платье фиолетовым, остальное как есть'), photo: tree.textContent.includes(', с картинкой'),
               rule: select(tree, 'Правило: Одежда').value, shown: shown(tree)};
  await button(tree, 'Вернуть как было').dispatch('click'); await settle();
  out.back = {saves: saves(), again: !!button(tree, 'Вернуть как было'), rule: select(tree, 'Правило: Одежда').value};
""")
    assert out["empty"] == {"asks": 0, "text": True}
    assert out["asked"] == {"asks": [{"wish": " платье сделать фиолетовым "}], "note": True, "photo": True, "rule": "colour",
                            "shown": "/api/photo-works/7/preview.png?v=2"}
    assert out["back"] == {"saves": [{"ai_photo": True}, {"rules": []}], "again": False, "rule": "as_is"}


@node
def test_without_a_key_the_ai_button_is_off_and_says_why_while_rules_can_still_be_set(tmp_path):
    out = run(tmp_path, {"work": "7"}, """
  out.disabled = button(tree, 'Попросить AI').disabled;
  out.text = tree.textContent.includes('AI выключен: не задан ключ языковой модели (OPENAI_API_KEY)');
  const clothes = select(tree, 'Правило: Одежда');
  clothes.value = 'photo'; await clothes.dispatch('change'); await settle();
  out.saves = saves();
""", work={"ai_missing": "key"})
    assert out == {"disabled": True, "text": True, "saves": [{"rules": [{"part": "clothes", "kind": "photo"}]}]}
