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
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'photo-modes.js', 'photo-quality.js', 'dialogs.js', 'list.js', 'hardware.js', 'tasks.js', {code: %(glue)s},
  'screens/experiment-cards.js', 'screens/device-view.js', 'screens/plate-dialog.js', 'screens/experiments.js',
  {code: 'globalThis.ExperimentCards = ExperimentCards; globalThis.DeviceView = DeviceView;'}]);
for (const [k, v] of Object.entries(data.store || {})) ctx.sessionStorage.setItem(k, v);
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const has = (el, cls) => (el.className || '').split(' ').includes(cls);
const kids = (el) => el.children.map((c) => c.className);
const P = (root, ...sels) => sels.reduce((el, s) => el && el.querySelector(s), root);        // the stub has no descendant selectors
const topLink = (a) => P(a, '.dashboard-item-top', 'a').textContent;
const titles = (root) => root.querySelectorAll('.lst-text').map((t) => t.textContent);               // the lines of the shared list
const chips = (root) => root.querySelectorAll('.lst-chip').map((c) => c.textContent);
const chip = (root, text) => root.querySelectorAll('.lst-chip').find((c) => c.textContent.startsWith(text));
const labelled = (root, label) => root.querySelectorAll('[aria-label]').find((el) => el.getAttribute('aria-label') === label);
const selectOf = (root, label) => root.querySelectorAll('.lst-select').find((l) => l.querySelector('span').textContent === label).querySelector('select');
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
  const scroll = q(list, '.os-scroll');
  out.toolbar = [q(scroll, '.lst-search') != null, chips(scroll), labelled(scroll, 'Состояние эксперимента') != null,
    selectOf(scroll, 'Задача').options.map((o) => o.textContent), selectOf(scroll, 'Порядок').options.map((o) => [o.value, o.textContent]), q(scroll, '.lst-count').textContent];
  out.rowsInScroll = scroll.querySelectorAll('.lst-row').length; out.rowsInList = list.querySelectorAll('.lst-row').length; out.cards = list.querySelectorAll('article').length;
  out.cardTitles = titles(scroll);
  out.open = scroll.querySelectorAll('.lst-act').map((a) => [a.textContent, a.querySelector('a').getAttribute('href')]);
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
    assert out["listParts"] == ["os-col-head", "os-scroll"] and out["listHead"].startswith("Эксперименты") and out["pills"] == ["3", "1 к проверке"]
    search, states, state_group, tasks, orders, count = out["toolbar"]                                  # the shared list's search, filters and order, in the list column
    assert search and state_group and states == ["Все · 3", "Нужна проверка · 1", "Ждут фото · 1", "Приняты · 1"]
    assert tasks == ["все задачи · 3", "Надписи · 3"] and count == "показано 3 из 3"
    assert orders == [["recent", "Сначала недавние"], ["review", "Сначала к проверке"], ["title", "По названию"]]
    assert out["rowsInScroll"] == out["rowsInList"] == 3 and out["cards"] == 0                           # one line each; the cards open under a line
    assert out["cardTitles"] == ["Плата текста", "Тест Q-Pulse", "Шаг строк"]                             # the most recently active first, as the server sends
    assert out["open"] == [["Открыть", "#/experiment/plan-3"], ["Открыть", "#/experiment/eng-a"], ["Открыть", "#/experiment/eng-b"]]
    assert out["task"]["head"] == "Рабочая задача" and out["task"]["labels"][:2] == ["Что хотим сделать", "На каком материале"] and out["task"]["inScroll"] >= 2
    assert out["task"]["next"] is True and "Laser A" not in out["task"]["result"] and "Разборчивые буквы выбранного размера" in out["task"]["result"]
    assert out["task"]["details"] == [out["task"]["details"][0]] and out["task"]["details"][0].startswith("Основание вывода и параметры")
    assert "основание — проверка №7, наблюдения №11, №12" in out["task"]["details"][0] and "30%" in out["task"]["details"][0].replace(" ", "")   # the long lines are folded
    assert "основание" not in out["task"]["result"].split("Основание вывода")[0] and "text readability" not in out["task"]["foot"]
    assert out["task"]["foot"].startswith("Плата: надписи 3 × 3, три размера")
    assert out["find"]["head"].startswith("Выводы для материала") and len(out["find"]["cards"]) == 2 and out["find"]["link"] == "#/devices/1"
    assert out["footerInside"] is False


@node
def test_the_filters_sit_in_the_list_column_narrow_it_in_place_and_remember_their_choice_for_the_session(tmp_path):
    routes = {**ROUTES, "/api/experiments": {"status": 200, "json": [*ROUTES["/api/experiments"]["json"][:2],
                                                                      experiment("eng-b", "Шаг строк", "needs_review", tasks=["line", "fill"])]}}
    out = run(tmp_path, """
  const scroll = P(tree, '.ex-list', '.os-scroll');
  const search = scroll.querySelector('.lst-search');
  search.value = 'q-pulse'; await search.dispatch('input'); await tick();
  out.searched = titles(scroll); out.chipsSearched = chips(scroll);
  search.value = ''; await search.dispatch('input'); await tick();
  await chip(scroll, 'Нужна проверка').dispatch('click'); await tick();
  out.state = titles(scroll);
  await chip(scroll, 'Все').dispatch('click'); await tick();
  out.tasks = selectOf(scroll, 'Задача').options.map((o) => [o.value, o.textContent]);
  const task = selectOf(scroll, 'Задача'); task.value = 'text'; await task.dispatch('change'); await tick();
  out.task = titles(scroll);
  const order = selectOf(scroll, 'Порядок'); order.value = 'title'; await order.dispatch('change'); await tick();
  out.ordered = titles(scroll);
  out.kept = JSON.parse(ctx.__store['list:experiments']); out.renders = ctx.__renders.length;
""", routes=routes)
    assert out["searched"] == ["Тест Q-Pulse"] and out["chipsSearched"] == ["Все · 1", "Приняты · 1"]      # the search reads the title; the counts follow it
    assert out["state"] == ["Шаг строк"]
    assert out["tasks"] == [["", "все задачи · 3"], ["text", "Надписи · 2"], ["line", "Линии · 1"], ["fill", "Заливка · 1"]]    # only the tasks the experiments have
    assert out["task"] == ["Плата текста", "Тест Q-Pulse"] and out["ordered"] == ["Плата текста", "Тест Q-Pulse"]
    assert out["kept"] == {"sort": "title", "filters": {"status": "", "task": "text"}, "search": "", "shown": 20}
    assert out["renders"] == 0                                                                                 # a choice narrows the list, the screen stays


@node
def test_a_remembered_filter_narrows_the_list_and_an_empty_result_says_so_inside_the_list(tmp_path):
    accepted = run(tmp_path, "out.titles = titles(P(tree, '.ex-list', '.os-scroll'));",
                   store={"list:experiments": json.dumps({"filters": {"status": "accepted"}})})
    assert accepted["titles"] == ["Тест Q-Pulse"]
    nothing = run(tmp_path, "const s = P(tree, '.ex-list', '.os-scroll'); out.rows = s.querySelectorAll('.lst-row').length; out.text = s.querySelector('.lst-empty').textContent;"
                            "out.pills = P(tree, '.ex-list', '.os-col-head').querySelectorAll('.pill').map((p) => p.textContent);"
                            "out.page = kids(tree);", store={"list:experiments": json.dumps({"search": "нет такого"})})
    assert nothing["rows"] == 0 and nothing["text"] == "Ничего не найдено: измените поиск, состояние или лазер." and nothing["pills"] == ["3", "1 к проверке"]
    assert nothing["page"] == ["os-head ex-head", "os-body ex-body"]                                       # the frame stays whole
    none = run(tmp_path, "out.text = P(tree, '.ex-list', '.os-scroll').querySelector('.lst-empty').textContent;",
               routes={**ROUTES, "/api/experiments": {"status": 200, "json": []}})
    assert none["text"] == "Экспериментов пока нет. Создайте плату или добавьте работу и фото."


@node
def test_a_long_list_shows_one_page_of_twenty_lines_and_the_rest_on_request(tmp_path):
    many = [experiment(f"eng-{i}", f"Плата {i:02d}", "accepted", last_activity=f"2026-10-{i:02d}T10:00:00") for i in range(1, 26)]
    out = run(tmp_path, """
  const scroll = P(tree, '.ex-list', '.os-scroll');
  out.first = titles(scroll); out.count = scroll.querySelector('.lst-count').textContent;
  const more = scroll.querySelector('.lst-foot').querySelector('button');
  out.more = more.textContent;
  await more.dispatch('click'); await tick();
  out.all = titles(scroll).length; out.after = scroll.querySelector('.lst-foot').querySelector('button');
  await scroll.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  out.card = [scroll.querySelectorAll('article').length, topLink(scroll.querySelector('article')), scroll.querySelector('article').querySelector('img').getAttribute('src')];
""", routes={**ROUTES, "/api/experiments": {"status": 200, "json": many[::-1]}})
    assert len(out["first"]) == 20 and out["first"][:2] == ["Плата 25", "Плата 24"] and out["count"] == "показано 20 из 25"
    assert out["more"] == "Показать ещё 5" and out["all"] == 25 and out["after"] is None
    assert out["card"] == [1, "Плата 25", "/api/pairs/7/photo.png?visibility=lifted&size=480"]           # the card opens under its line, built then


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
def test_the_laser_page_shows_the_same_short_list_with_the_same_filters_and_keeps_its_own_choice(tmp_path):
    out = run(tmp_path, """
  const all = data.routes['/api/experiments'].json;
  const card = ctx.DeviceView.experimentsCard(all, {id: 1, name: 'Laser A', lens: {id: 5, name: 'F-Theta', focal_length_mm: 174}}, [{id: 5, name: 'F-Theta', focal_length_mm: 174}]);
  const panel = card.querySelectorAll('section').find((s) => s.textContent.startsWith('Эксперименты этого лазера'));
  out.head = panel.querySelector('.dashboard-panel-head').textContent;
  out.toolbar = [panel.querySelector('.lst-search') != null, chips(panel), selectOf(panel, 'Задача').options.map((o) => o.textContent),
    selectOf(panel, 'Порядок').options.map((o) => o.textContent)];
  await chip(panel, 'Приняты').dispatch('click'); await tick();
  out.accepted = titles(panel);
  out.kept = [JSON.parse(ctx.__store['list:laser-experiments']).filters, ctx.__store['list:experiments'] || null];
  out.api = Object.keys(ctx.ExperimentCards);
  out.empty = ctx.ExperimentCards.list([], {empty: 'Пусто'}).querySelector('.lst-empty').textContent;
""")
    assert out["head"] == "Эксперименты этого лазера3Открыть в общем списке"
    search, states, tasks, orders = out["toolbar"]
    assert search and states == ["Все · 3", "Нужна проверка · 1", "Ждут фото · 1", "Приняты · 1"] and tasks == ["все задачи · 3", "Надписи · 3"]
    assert orders == ["Сначала недавние", "Сначала к проверке", "По названию"]
    assert out["accepted"] == ["Тест Q-Pulse"] and out["kept"][0] == {"status": "accepted", "task": ""} and out["kept"][1] is None   # its own choice, not the screen's
    assert out["api"] == ["card", "list", "layers"] and out["empty"] == "Пусто"


# -- «Создать плату»: the plate dialog ---------------------------------------------------------------------------------------------
DIALOG = """
const fs = require('fs');
const {context, load, El} = require(%(dom)s);
// the small DOM keeps no inline style; the dialog shows and hides the card of the chosen plate type through element.style
Object.defineProperty(El.prototype, 'style', {get() { return this._style || (this._style = {}); }});
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'list.js', 'hardware.js', 'tasks.js', 'screens/plate-dialog.js', {code: 'globalThis.PlateDialog = PlateDialog;'}]);
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


@node
def test_the_plate_dialog_sends_the_picture_of_a_photo_variations_plate_its_kind_and_size(tmp_path):
    out = run_dialog(tmp_path, """
  ctx.btoa = (text) => Buffer.from(text, 'binary').toString('base64');
  out.none = await made({type: 'photo_variations'}, () => {});
  out.photo = await made({type: 'photo_variations'}, (box) => {
    out.photoCard = card(labelled(box, 'Картинка копий')); out.greyCard = card(labelled(box, 'Строки шкал серого'));
    labelled(box, 'Картинка копий').files = [{name: 'yana.png', arrayBuffer: async () => new Uint8Array([137, 80, 78, 71]).buffer}];
    labelled(box, 'Вид копий').value = 'grayscale';
    labelled(box, 'Размер копии, мм').value = '24';
    labelled(box, 'Min мощность копий, %').value = '2';
  });
""")
    assert out["none"] is None                                                       # nothing is sent without a picture
    assert out["photoCard"] == "" and out["greyCard"] == "none"
    assert out["photo"]["test_type"] == "photo_variations"
    assert out["photo"]["variations"] == {"picture_name": "yana.png", "dither": "grayscale", "copy_mm": 24, "min_power": 2, "picture_png": "iVBORw=="}


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
                 "h('section', {class: 'os-col ex-task'},", "{class: 'os-col ex-find'}", "ExperimentCards.list(shown, {id: 'experiments',",
                 "panel('Выводы для материала', latest.size, insightCards,", "App.post('/application-guide/next-plate'", "PlateDialog.open(devices, materials, reload)"):
        assert part in SCREEN, part
    assert "{class: 'dashboard-hero'" not in SCREEN and "{class: 'experiment-dashboard'" not in SCREEN and "exp-columns" not in SCREEN     # the old page frame is gone
    assert "return {card, list, layers};" in CARDS and "App.list({id, items: experiments" in CARDS                  # the laser page keeps using the same list
    for gone in ("'experiment-search'", "'experiment-status'", "'experiment-task'"):                                      # the filters are the shared list's
        assert gone not in SCREEN, gone


# -- what the laboratory proposes for each kind of photo engraving (photo-engraving-quality REQ-005) ---------------------------------------
JARVIS = {"dither": "jarvis", "power": 20.0, "min_power": 20.0, "speed": 125.0, "frequency": 60.0, "pulse_width": 200.0, "line_interval": 0.01,
          "passes": 1, "global_passes": 1, "dot_width": None}
KNOWN = {"device_id": 1, "lens_id": 5, "material_id": 1, "picture_from": {"pair_id": 7, "plan_id": 3}, "kinds": [
    {"kind": "jarvis", "status": "searching", "engravings": 9,
     "effects": {"power": {"per": "doubling", "photographs": [7], "mean_L": {"median": -6.0, "n": 2}, "score": {"median": 0.1, "n": 2}}}, "best": {"settings": JARVIS, "score": 0.81, "source": {"pair_id": 7, "layer": "PV2-RAMP"}},
     "proposal": {"kind": "next", "pair_id": 7, "centre": JARVIS, "step": 0.5, "best_label": "2 J P20",
                  "copies": [[], [{"setting": "power", "from": 20.0, "to": 18.0}]], "plate": {"copy_mm": [18.0, 12.0], "size_mm": [42.0, 24.6], "picture": "p.png"}}},
    {"kind": "atkinson", "status": "unmeasured", "engravings": 0, "effects": {}, "best": None,
     "proposal": {"kind": "around", "centre": {**JARVIS, "dither": "atkinson"}, "step": 1.0, "source": {"pair_id": 7, "layer": "PV2-RAMP"},
                  "copies": [[], [{"setting": "power", "from": 20.0, "to": 16.0}], [{"setting": "power", "from": 20.0, "to": 24.0}]],
                  "plate": {"copy_mm": [18.0, 12.0], "size_mm": [65.0, 24.6], "picture": "p.png"}}},
    {"kind": "stucki", "status": "unmeasured", "engravings": 0, "effects": {}, "best": None,
     "proposal": {"kind": "around", "centre": {**JARVIS, "dither": "stucki"}, "step": 1.0, "source": {"pair_id": 7, "layer": "PV2-RAMP"},
                  "copies": [[], [{"setting": "power", "from": 20.0, "to": 16.0}]], "plate": None}},
    {"kind": "grayscale", "status": "unmeasured", "engravings": 0, "effects": {}, "best": None, "proposal": None}]}


@node
def test_the_laboratory_proposes_the_next_plate_of_each_kind_of_photo_engraving_for_the_laser_and_titanium(tmp_path):
    image = {**FINDING, "purpose": "image", "status": "needs_image_test", "summary": "Режим для изображения пока не подтверждён", "pair_id": 9}
    routes = {**ROUTES, "/api/photo-knowledge": {"status": 200, "json": KNOWN}, "/api/devices/1/findings": {"status": 200, "json": [FINDING, image]},
              "/api/photo-knowledge/plate": {"status": 201, "json": {"plan_id": 12, "name": "Фотогравировка · TCE-12"}}}
    out = run(tmp_path, """
  const panel = tree.querySelectorAll('section').find((s) => has(s, 'ex-find') && s.textContent.includes('Фотогравировка: что предлагает лаборатория'));
  out.head = panel.querySelector('.os-col-head').textContent;
  out.cards = panel.querySelectorAll('article').map((a) => a.textContent);
  out.image = tree.querySelectorAll('article').find((a) => a.textContent.startsWith('Изображение')).textContent;
  out.asked = ctx.requests.filter((r) => r.path === '/api/photo-knowledge').map((r) => r.url);
  out.buttons = panel.querySelectorAll('article').map((a) => a.querySelectorAll('button').map((b) => b.textContent));
  await byText(panel.querySelectorAll('article')[1], 'button', 'Сделать плату: 3 копии').dispatch('click'); await tick(); await tick();
  out.made = ctx.requests.filter((r) => r.path === '/api/photo-knowledge/plate').map((r) => JSON.parse(r.body));
  out.went = ctx.location.hash;
""", routes=routes)
    assert out["head"].startswith("Фотогравировка: что предлагает лаборатория3")                    # three kinds have an experiment proposed
    assert out["asked"] == ["/api/photo-knowledge?device_id=1&lens_id=5&material_id=1"]
    jarvis, atkinson, stucki, grey = out["cards"]
    assert "мощность вдвое больше: темнее на 6 L*, оценка +0,1 (по фото №7)" in jarvis                 # what the power does here
    assert "Плата 42 × 25 мм: 2 копии по 18 × 12 мм" in jarvis and "мощность 20 % → 18 %" in jarvis
    assert "Картинки для платы ещё нет: сделайте первую плату из фотоработы или фотозоны" in stucki   # nothing to engrave it from yet
    assert out["buttons"] == [["Сделать следующую плату"], ["Сделать плату: 3 копии"], [], []]
    # the image purpose of the capability plate no longer says only «needs a test»: what the photographs measured is said there
    assert out["image"].startswith("ИзображениеФото измерено") and "лучше всего вышел вид «Джарвис» (оценка 0,81 по фото №7)" in out["image"]
    assert jarvis.startswith("Джарвиспоиск идёт") and "Лучшее: 20 %, 125 мм/с, 60 кГц, 200 нс, шаг 0,01 мм — оценка 0,81 по фото №7" in jarvis
    assert "Следующая плата вокруг копии 2 J P20, изменения вдвое меньше." in jarvis and jarvis.endswith("Сделать следующую плату")
    assert "Ещё не фотографировался на этом лазере и титане." in atkinson and "на лучших настройках другого вида точками" in atkinson
    assert "Начните со шкал серого (Фотогравировка → Шкалы серого)." in grey
    assert out["made"] == [{"device_id": 1, "lens_id": 5, "material_id": 1, "kind": "atkinson"}] and out["went"] == "#/experiment/plan-12"
