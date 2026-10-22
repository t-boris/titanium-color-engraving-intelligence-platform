"""The experiments screen on one screen (REQ-044, DEC-080): the list with its filters on the left, the working task over the findings for
the material on the right, only the list scrolling inside its panel. Run in node over the small DOM of the other screen tests, with
answers shaped like the server's."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
CSS = (UI / "styles.css").read_text(encoding="utf-8")
SCREEN = (UI / "screens" / "experiments.js").read_text(encoding="utf-8")
CARDS = (UI / "screens" / "experiment-cards.js").read_text(encoding="utf-8")

GLUE = ("const __screens = {}, __renders = []; App.register = (d) => { __screens[d.id] = d; }; App.render = () => { __renders.push(1); };"
        "globalThis.__screens = __screens; globalThis.__renders = __renders;"
        "const __store = {}; globalThis.sessionStorage = {getItem: (k) => (k in __store ? __store[k] : null), setItem: (k, v) => { __store[k] = String(v); },"
        "removeItem: (k) => { delete __store[k]; }}; globalThis.__store = __store; App.go = (route) => { location.hash = '#' + route; };")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'tasks.js', {code: %(glue)s}, 'screens/experiment-cards.js', 'screens/plate-dialog.js',
  'screens/experiments.js', {code: 'globalThis.ExperimentCards = ExperimentCards;'}]);
for (const [k, v] of Object.entries(data.store || {})) ctx.sessionStorage.setItem(k, v);
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const has = (el, cls) => (el.className || '').split(' ').includes(cls);
const kids = (el) => el.children.map((c) => c.className);
const P = (root, ...sels) => sels.reduce((el, s) => el && el.querySelector(s), root);        // the stub has no descendant selectors
const topLink = (a) => P(a, '.dashboard-item-top', 'a').textContent;
(async () => {
  const out = {};
  const tree = await ctx.__screens.experiments.render({query: data.query || {}});
  await tick(); await tick();
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def experiment(key, title, status, **more) -> dict:
    return {"key": key, "title": title, "status": status, "status_text": {"accepted": "Принят", "plate_ready": "Плата готова: ждёт фото", "needs_review": "Нужна проверка"}[status],
            "kind": "Матрица параметров", "laser": "Laser A", "lens": "F-Theta", "material": "Titan 2", "tasks": ["text"], "checks": 1, "photos": 1, "layers_measured": 5,
            "needs_review": 1 if status == "needs_review" else 0, "last_activity": "2026-10-18T10:00:00", "main_pair_id": 7, "device_id": 1, **more}


FINDING = {"material_id": 1, "lens_id": 5, "purpose": "line", "status": "candidate", "summary": "Тонкие линии держатся при 30 % мощности", "next_test": "Повторить на другой заготовке",
           "pair_id": 7, "parameters": {"power": 30, "frequency": 1950, "speed": 900}}
ROUTES = {
    "/api/experiments": {"status": 200, "json": [experiment("plan-3", "Плата текста", "plate_ready", main_pair_id=None, checks=0, photos=0),
                                                 experiment("eng-a", "Тест Q-Pulse", "accepted"), experiment("eng-b", "Шаг строк", "needs_review")]},
    "/api/devices": {"status": 200, "json": [{"id": 1, "name": "Laser A", "title": "Laser A", "lens": {"id": 5, "name": "F-Theta"}, "passport": {"pulse_steps": []}}]},
    "/api/materials": {"status": 200, "json": [{"id": 1, "name": "Titan", "grade": "2", "batch": "A"}]},
    "/api/application-goals": {"status": 200, "json": [{"id": "text", "name": "Надписи", "objective": "Разборчивые буквы выбранного размера"},
                                                       {"id": "line", "name": "Линии", "objective": "Тонкие линии"}]},
    "/api/devices/1/findings": {"status": 200, "json": [FINDING, {**FINDING, "purpose": "text", "status": "needs_test", "pair_id": 8}]},
    "/api/application-guide": {"status": 200, "json": {"status": "ok", "message": "Сравнить надписи при трёх мощностях.", "next_step": "Создать плату надписей и сфотографировать её.",
                                                       "plate": {"test_type": "text_readability", "source_pair_id": 7, "settings": {"pulse_width": 200}}, "finding": FINDING,
                                                       "task": {"kind": "text"}, "pending_plan_id": None,
                                                       "support": {"pair_id": 7, "observation_ids": [11, 12], "engravings": 2, "photographs": 3, "missing_context": []}}},
    "/api/application-guide/next-plate": {"status": 201, "json": {"plan_id": 9, "name": "Plate 9"}},
    "/api/tasks": {"status": 200, "json": [{"key": "line", "goals": [], "metrics": []}, {"key": "text", "goals": [], "metrics": []}]},
}


def run(tmp_path, body, routes=None, query=None, store=None) -> dict:
    (tmp_path / "data.json").write_text(json.dumps({"routes": routes or ROUTES, "query": query or {}, "store": store or {}}), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


# -- the frame -------------------------------------------------------------------------------------------------------------------------
@node
def test_the_screen_is_one_frame_with_the_list_on_the_left_and_the_task_over_the_findings_on_the_right(tmp_path):
    out = run(tmp_path, """
  const q = (root, sel) => root.querySelector(sel);
  out.root = tree.className; out.top = kids(tree);
  const head = q(tree, '.os-head');
  out.title = head.querySelector('h2').textContent;
  out.actions = head.querySelectorAll('a,button').map((el) => [el.textContent, el.getAttribute('href'), has(el, 'primary')]);
  const body = q(tree, '.os-body');
  out.columns = kids(body); out.right = kids(q(tree, '.ex-right'));
  const list = q(tree, '.ex-list');
  out.listParts = kids(list); out.listHead = list.querySelector('.os-col-head').textContent; out.pills = P(list, '.os-col-head').querySelectorAll('.pill').map((p) => p.textContent);
  const filters = q(list, '.ex-filters');
  out.filters = filters.children.map((el) => [el.localName, el.getAttribute('aria-label')]);
  const scroll = q(list, '.os-scroll');
  out.cardsInScroll = scroll.querySelectorAll('article').length; out.cardsInList = list.querySelectorAll('article').length;
  out.cardTitles = scroll.querySelectorAll('article').map(topLink);
  const task = q(tree, '.ex-task');
  out.task = {head: P(task, '.os-col-head', 'h3').textContent, labels: task.querySelectorAll('label').map((l) => l.querySelector('span').textContent),
    next: byText(task, 'button', 'Создать следующий тест') != null, details: task.querySelectorAll('details').map((d) => d.textContent),
    inScroll: q(task, '.os-scroll').querySelectorAll('select').length, result: q(task, '.dashboard-task-result').textContent, foot: q(task, '.dashboard-task-foot').textContent};
  const find = q(tree, '.ex-find');
  out.find = {head: q(find, '.os-col-head').textContent, cards: q(find, '.os-scroll').querySelectorAll('article').map((a) => a.textContent),
    link: P(find, '.os-col-head', 'a').getAttribute('href')};
  out.footerInside = tree.querySelectorAll('p').some((p) => has(p, 'demo'));
""")
    classes = out["root"].split()
    assert "os" in classes and "ex" in classes and "workspace" not in classes                 # the side menu stays
    assert out["top"] == ["os-head ex-head", "os-body ex-body"] and out["title"] == "Эксперименты"
    assert out["actions"] == [["AI-исследователь", "#/research", False], ["Карта цветов", "#/colors", False], ["Создать плату", None, True], ["Добавить работу и фото", "#/ingest", False]]
    assert out["columns"] == ["os-col ex-list", "ex-right"] and out["right"] == ["os-col ex-task", "os-col ex-find"]
    assert out["listParts"] == ["os-col-head", "ex-filters", "os-scroll"] and out["listHead"].startswith("Эксперименты") and out["pills"] == ["3", "1 к проверке"]
    assert out["filters"] == [["input", "Поиск эксперимента"], ["select", "Состояние эксперимента"], ["select", "Задача гравировки"]]    # in the list column, not above it
    assert out["cardsInScroll"] == out["cardsInList"] == 3 and out["cardTitles"] == ["Плата текста", "Тест Q-Pulse", "Шаг строк"]       # only the list scrolls
    assert out["task"]["head"] == "Рабочая задача" and out["task"]["labels"][:2] == ["Что хотим сделать", "На каком материале"] and out["task"]["inScroll"] >= 2
    assert out["task"]["next"] is True and "Laser A" not in out["task"]["result"] and "Разборчивые буквы выбранного размера" in out["task"]["result"]
    assert out["task"]["details"] == [out["task"]["details"][0]] and out["task"]["details"][0].startswith("Основание вывода и параметры")
    assert "основание — проверка №7, наблюдения №11, №12" in out["task"]["details"][0] and "30%" in out["task"]["details"][0].replace(" ", "")   # the long lines are folded
    assert "основание" not in out["task"]["result"].split("Основание вывода")[0] and "text readability" not in out["task"]["foot"]
    assert out["task"]["foot"].startswith("Плата: надписи 3 × 3, три размера")
    assert out["find"]["head"].startswith("Выводы для материала") and len(out["find"]["cards"]) == 2 and out["find"]["link"] == "#/devices/1"
    assert out["footerInside"] is False


@node
def test_the_filters_sit_in_the_list_column_remember_their_choice_and_reload_the_screen(tmp_path):
    out = run(tmp_path, """
  const filters = tree.querySelector('.ex-filters');
  const search = filters.querySelector('input'); const state = filters.querySelectorAll('select')[0]; const taskSelect = filters.querySelectorAll('select')[1];
  search.value = 'Q-Pulse'; await search.dispatch('change');
  out.search = ctx.__store['experiment-search']; out.afterSearch = ctx.__renders.length;
  state.value = 'accepted'; await state.dispatch('change');
  out.status = ctx.__store['experiment-status']; out.afterStatus = ctx.__renders.length;
  taskSelect.value = 'text'; await taskSelect.dispatch('change');
  out.task = ctx.__store['experiment-task']; out.afterTask = ctx.__renders.length;
  out.states = state.querySelectorAll('option').map((o) => [o.value, o.textContent]);
""")
    assert out["search"] == "Q-Pulse" and out["status"] == "accepted" and out["task"] == "text"
    assert (out["afterSearch"], out["afterStatus"], out["afterTask"]) == (1, 2, 3)                      # each choice rebuilds the screen
    assert out["states"] == [["all", "Все"], ["needs_review", "Нужна проверка"], ["plate_ready", "Ждут фото"], ["accepted", "Приняты"]]


@node
def test_a_remembered_filter_narrows_the_list_and_an_empty_result_says_so_inside_the_list(tmp_path):
    accepted = run(tmp_path, "out.titles = P(tree, '.ex-list', '.os-scroll').querySelectorAll('article').map(topLink);",
                   store={"experiment-status": "accepted"})
    assert accepted["titles"] == ["Тест Q-Pulse"]
    nothing = run(tmp_path, "const s = P(tree, '.ex-list', '.os-scroll'); out.cards = s.querySelectorAll('article').length; out.text = s.textContent;"
                            "out.pills = P(tree, '.ex-list').querySelectorAll('.pill').map((p) => p.textContent); out.page = kids(tree);", store={"experiment-search": "нет такого"})
    assert nothing["cards"] == 0 and nothing["text"] == "Ничего не найдено: измените поиск, состояние или лазер." and nothing["pills"] == ["3", "1 к проверке"]
    assert nothing["page"] == ["os-head ex-head", "os-body ex-body"]                                       # the frame stays whole


@node
def test_the_experiments_of_one_laser_show_its_pill_and_the_way_back_in_the_filters(tmp_path):
    out = run(tmp_path, """
  const filters = tree.querySelector('.ex-filters');
  out.first = filters.children[0].textContent; out.link = filters.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
  out.pills = P(tree, '.ex-list', '.os-col-head').querySelectorAll('.pill').map((p) => p.textContent);
""", query={"device": "1"})
    assert out["first"] == "Лазер: Laser AВсе лазеры" and out["link"] == [["Все лазеры", "#/experiments"]] and out["pills"] == ["3 из 3", "1 к проверке"]


# -- behaviour that must not change -----------------------------------------------------------------------------------------------------
@node
def test_the_next_test_button_still_creates_the_plate_for_the_goal_material_and_laser_and_opens_it(tmp_path):
    out = run(tmp_path, """
  const button = byText(tree.querySelector('.ex-task'), 'button', 'Создать следующий тест');
  await button.dispatch('click'); await tick();
  const post = ctx.requests.find((r) => r.method === 'POST');
  out.path = post.path; out.body = JSON.parse(post.body); out.hash = ctx.location.hash;
""")
    assert out["path"] == "/api/application-guide/next-plate" and out["hash"] == "#/experiment/plan-9"
    assert out["body"] == {"device_id": 1, "material_id": 1, "goal": "text", "pulse_width": None}


@node
def test_the_task_pickers_remember_their_choice_and_reload(tmp_path):
    out = run(tmp_path, """
  const selects = tree.querySelector('.ex-task').querySelectorAll('select');
  out.labels = selects.map((s) => s.getAttribute('aria-label'));
  selects[0].value = 'line'; await selects[0].dispatch('change');
  out.goal = ctx.__store['experiment-dashboard-goal']; out.renders = ctx.__renders.length;
  out.guideUrls = ctx.requests.filter((r) => r.path === '/api/application-guide').map((r) => r.url);
""")
    assert out["labels"] == ["Цель исследования", "Материал и заготовка"] and out["goal"] == "line" and out["renders"] == 1
    assert out["guideUrls"] == ["/api/application-guide?device_id=1&material_id=1&goal=text"]


@node
def test_without_a_laser_the_screen_offers_to_add_one_and_does_not_offer_a_plate(tmp_path):
    routes = {**ROUTES, "/api/devices": {"status": 200, "json": []}}
    out = run(tmp_path, """
  out.root = tree.className; out.text = tree.textContent;
  out.plate = byText(tree, 'button', 'Создать плату').disabled; out.link = byText(tree, 'a', 'Лазеры').getAttribute('href');
""", routes=routes)
    assert "os" in out["root"].split() and "Сначала добавьте лазер и установите линзу" in out["text"] and out["plate"] is True and out["link"] == "#/devices"


@node
def test_the_experiment_cards_keep_the_list_api_the_laser_page_uses(tmp_path):
    out = run(tmp_path, """
  const list = ctx.ExperimentCards.list(data.routes['/api/experiments'].json, '');
  out.list = list.className; out.cards = list.children.map((c) => c.className);
  out.empty = ctx.ExperimentCards.list([], 'Пусто').textContent; out.api = Object.keys(ctx.ExperimentCards);
""")
    assert out["list"] == "dashboard-list" and out["cards"] == ["dashboard-item exp-card"] * 3 and out["empty"] == "Пусто" and out["api"] == ["card", "list", "layers"]


# -- «Создать плату»: the plate dialog ---------------------------------------------------------------------------------------------
DIALOG = """
const fs = require('fs');
const {context, load, El} = require(%(dom)s);
// the small DOM keeps no inline style; the dialog shows and hides the card of the chosen plate type through element.style
Object.defineProperty(El.prototype, 'style', {get() { return this._style || (this._style = {}); }});
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'hardware.js', 'tasks.js', 'screens/plate-dialog.js', {code: 'globalThis.PlateDialog = PlateDialog;'}]);
const tick = () => new Promise((r) => setTimeout(r, 0));
const labelled = (root, label) => root.querySelectorAll('[aria-label]').find((el) => el.getAttribute('aria-label') === label);
const card = (input) => {                                                   // whether the card around an input is shown
  let el = input;
  while (!(el.className || '').split(' ').includes('card')) el = el.parentNode;
  return el.style.display;
};
/** Open the dialog for a plate type, choose the stock, let ``fill`` set the card, press «Создать плату»: the body it sends. */
async function made(preset, fill) {
  const dialog = await ctx.PlateDialog.open(data.devices, data.materials, null, preset);
  await tick();
  labelled(dialog.el, 'Заготовка').value = '1';
  fill(dialog.el);
  const before = ctx.requests.length;
  await dialog.el.querySelectorAll('button').find((b) => b.textContent === 'Создать плату').dispatch('click');
  for (let i = 0; i < 5; i += 1) await tick();
  const sent = ctx.requests.slice(before).find((r) => r.path === '/api/capability-plates' && r.method === 'POST');
  return sent ? JSON.parse(sent.body) : null;
}
(async () => {
  const out = {};
%(body)s
  console.log(JSON.stringify(out));
  process.exit(0);                                                          // the toasts' timers need not run out
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run_dialog(tmp_path, body) -> dict:
    from titanium_platform import capability_plates
    data = {"routes": {"/api/plate-types": {"status": 200, "json": capability_plates.PLATE_TYPES},
                       "/api/tasks": ROUTES["/api/tasks"],
                       "/api/capability-plates": {"status": 201, "json": {"plan_id": 9, "name": "Плата · TCE-1",
                                                                          "summary": {"layers": 4, "work_field": {"checked": True}}}}},
            "devices": [{"id": 1, "name": "Laser A", "lens": {"id": 5, "name": "F-Theta", "focal_length_mm": 174, "field_mm": 170},
                         "passport": {"pulse_steps": [{"pulse_width_ns": 200, "cutoff_khz": 100}], "repetition_rate_khz": {"min": 1, "max": 4000}}}],
            "materials": [{"id": 1, "family": "Titanium", "name": "Titan", "grade": "2"}]}
    (tmp_path / "data.json").write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / "dialog.js"
    script.write_text(DIALOG % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


@node
def test_the_plate_dialog_sends_the_recipes_and_widths_of_a_fill_size_plate_and_a_grey_ramp_width_axis(tmp_path):
    out = run_dialog(tmp_path, """
  out.fill = await made({type: 'fill_sizes'}, (box) => {
    out.fillCard = card(labelled(box, 'Ширины полосок заливки')); out.greyCard = card(labelled(box, 'Строки шкал серого'));
    labelled(box, 'Ширины полосок заливки').value = '5, 40, 120';
    labelled(box, 'Параметр рецептов заливки').value = 'speed';
    labelled(box, 'Значения рецептов заливки').value = '150, 300';
  });
  out.oneRecipe = await made({type: 'fill_sizes'}, () => {});
  out.grey = await made({type: 'grey_scales'}, (box) => {
    const rows = labelled(box, 'Строки шкал серого');
    out.greyAxes = rows.options.map((o) => [o.value, o.textContent]);
    rows.value = 'width';
    box.querySelectorAll('input').find((i) => i.value === '0.0127, 0.0169, 0.0212, 0.0254').value = '20, 40, 70';
  });
""")
    assert out["fillCard"] == "" and out["greyCard"] == "none"                     # the fill card is the one shown
    fill = out["fill"]
    assert fill["test_type"] == "fill_sizes" and fill["widths_mm"] == [5, 40, 120] and fill["recipes"] == [{"speed": 150}, {"speed": 300}]
    assert (fill["max_width_mm"], fill["max_height_mm"], fill["pulse_width"]) == (150, 150, 200)     # strips up to 100 mm do not fit 100 mm
    assert out["oneRecipe"]["recipes"] == [{}] and out["oneRecipe"]["widths_mm"] == [5, 20, 50, 100]   # the plate's own settings, the default widths
    assert ["width", "Ширина полоски, мм"] in out["greyAxes"]
    assert out["grey"]["scales"]["rows"] == {"axis": "width", "values": [20, 40, 70]} and out["grey"]["max_width_mm"] == 100


# -- the CSS ---------------------------------------------------------------------------------------------------------------------------
def test_the_list_and_the_right_column_share_the_height_and_only_the_list_and_long_panels_scroll():
    assert re.search(r"\.ex-body \{grid-template-columns:minmax\(340px,40%\) minmax\(0,1fr\)\}", CSS)
    assert re.search(r"\.ex-right \{display:flex;flex-direction:column;[^}]*min-height:0\}", CSS)
    assert re.search(r"\.ex-task \{flex:0 1 auto\}", CSS) and re.search(r"\.ex-find \{flex:1 1 150px;min-height:150px\}", CSS)    # findings keep room, the task panel gives way
    assert re.search(r"\.ex-filters \{display:grid;grid-template-columns:repeat\(2,minmax\(0,1fr\)\)", CSS) and re.search(r"\.ex-filters>input,\.ex-filters>\.row \{grid-column:1 / -1\}", CSS)
    assert re.search(r"\.ex-list \.exp-card \{grid-template-columns:64px minmax\(0,1fr\)", CSS) and re.search(r"\.ex-list \.exp-thumb \{width:64px;height:64px\}", CSS)
    assert re.search(r"\.ex-insights \{display:grid;grid-template-columns:repeat\(2,minmax\(0,1fr\)\)", CSS)
    narrow = re.search(r"@media \(max-width:1100px\) \{\s*\.ex-body \{(.*?)\n\}", CSS[CSS.index("ex-: «Эксперименты»"):], re.S)
    assert narrow and "grid-template-columns:minmax(0,1fr)" in narrow.group(1) and ".ex-find {flex:none;min-height:0}" in CSS     # a phone scrolls the page as before


def test_the_source_builds_the_frame_from_the_shared_classes_and_keeps_what_other_tests_and_screens_rely_on():
    for part in ("h('div', {class: 'os ex'}, hero,", "h('div', {class: 'os-body ex-body'},", "h('section', {class: 'os-col ex-list'},", "h('div', {class: 'ex-right'}, taskPanel,",
                 "h('section', {class: 'os-col ex-task'},", "{class: 'os-col ex-find'}", "ExperimentCards.list(shown", "panel('Выводы для материала', latest.size, insightCards,",
                 "sessionStorage.getItem('experiment-search')", "App.post('/application-guide/next-plate'", "PlateDialog.open(devices, materials, reload)"):
        assert part in SCREEN, part
    assert "{class: 'dashboard-hero'" not in SCREEN and "{class: 'experiment-dashboard'" not in SCREEN and "exp-columns" not in SCREEN     # the old page frame is gone
    assert "return {card, list, layers};" in CARDS                                                                    # the laser page keeps using the same list
