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
  'screens/experiment-cards.js', 'screens/device-view.js', 'screens/material-picker.js', 'screens/source-refs.js', 'screens/plate-dialog.js', 'screens/experiments.js',
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
    "/api/materials/1": {"status": 200, "json": {"id": 1, "name": "Titan", "grade": "2", "batch": "A"}},       # the stock selector reads the one record it shows
    "/api/application-goals": {"status": 200, "json": [{"id": "text", "name": "Надписи", "objective": "Разборчивые буквы выбранного размера"},
                                                       {"id": "line", "name": "Линии", "objective": "Тонкие линии"}]},
    "/api/devices/1/findings": {"status": 200, "json": [FINDING, {**FINDING, "purpose": "text", "status": "needs_test", "pair_id": 8}]},
    "/api/application-guide": {"status": 200, "json": {"status": "ok", "message": "Сравнить надписи при трёх мощностях.", "next_step": "Создать плату надписей и сфотографировать её.",
                                                       "plate": {"test_type": "text_readability", "source_pair_id": 7, "settings": {"pulse_width": 200}}, "finding": FINDING,
                                                       "task": {"kind": "text"}, "pending_plan_id": None,
                                                       "support": {"pair_id": 7, "observation_ids": [11, 12], "engravings": 2, "photographs": 3, "missing_context": []}}},
    "/api/application-guide/next-plate": {"status": 201, "json": {"plan_id": 9, "name": "Plate 9"}},
    "/api/application-guide/preview": {"status": 200, "json": {"revision": "preview-1", "summary": {"size_mm": {"width": 44, "height": 35},
        "test_features": 9, "work_field": {"checked": True}}, "time": {"seconds": 120, "complete": True}}},
    "/api/tasks": {"status": 200, "json": [{"key": "line", "goals": [], "metrics": []}, {"key": "text", "goals": [], "metrics": []}]},
}


def run(tmp_path, body, routes=None, query=None, store=None, setup="") -> dict:
    (tmp_path / "data.json").write_text(json.dumps({"routes": routes or ROUTES, "query": query or {}, "store": store or {}}), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS.replace("  const tree = await ctx.__screens.experiments.render", setup + "\n  const tree = await ctx.__screens.experiments.render") % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


# -- the frame -------------------------------------------------------------------------------------------------------------------------
@node
def test_experiment_catalog_remains_usable_while_lasers_load_without_resetting_list_state(tmp_path):
    setup = """
  const original = ctx.fetch;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  ctx.fetch = async (url, opts) => { if (String(url).split('?')[0] === '/api/devices') await gate; return original(url, opts); };
"""
    out = run(tmp_path, """
  const list = tree.querySelector('.ex-list');
  const row = list.querySelector('.lst-main');
  await row.dispatch('click'); await tick();
  const detail = list.querySelector('.lst-det');
  out.before = [titles(P(tree, '.ex-list', '.os-scroll')).length, !detail.hidden,
    byText(tree, 'button', 'Advanced plate options').disabled];
  release(); await tick(); await tick(); await tick();
  out.after = [tree.querySelector('.ex-list') === list, list.querySelector('.lst-det') === detail, !detail.hidden,
    byText(tree, 'button', 'Advanced plate options').disabled];
""", setup=setup)
    assert out["before"] == [3, True, True] and out["after"] == [True, True, True, False]


@node
def test_failed_laser_request_offers_retry_without_hiding_experiments(tmp_path):
    routes = {**ROUTES, "/api/devices": {"status": 503, "json": {"error": "lasers unavailable"}}}
    out = run(tmp_path, """
  const task = tree.querySelector('.ex-task');
  out.before = [titles(P(tree, '.ex-list', '.os-scroll')).length, task.textContent.includes('lasers unavailable'),
    byText(tree, 'button', 'Advanced plate options').disabled];
  data.routes['/api/devices'] = %(devices)s;
  await byText(task, 'button', 'Retry').dispatch('click'); await tick(); await tick();
  out.after = [titles(P(tree, '.ex-list', '.os-scroll')).length, byText(tree, 'button', 'Advanced plate options').disabled];
""" % {"devices": json.dumps(ROUTES["/api/devices"])}, routes=routes)
    assert out["before"] == [3, True, True] and out["after"] == [3, False]


@node
def test_existing_experiments_remain_visible_when_no_lasers_are_available(tmp_path):
    out = run(tmp_path, """
  out.rows = titles(P(tree, '.ex-list', '.os-scroll')).length;
  out.disabled = byText(tree, 'button', 'Advanced plate options').disabled;
  out.lasers = byText(tree, 'a', 'Lasers').getAttribute('href');
""", routes={**ROUTES, "/api/devices": {"status": 200, "json": []}})
    assert out == {"rows": 3, "disabled": True, "lasers": "#/devices"}


@node
def test_unknown_laser_filter_falls_back_to_the_full_experiment_catalog(tmp_path):
    out = run(tmp_path, """
  const list = tree.querySelector('.ex-list');
  out.rows = titles(P(tree, '.ex-list', '.os-scroll')).length;
  out.scopeHidden = list.querySelector('.ex-filters').hidden;
  out.total = P(list, '.os-col-head').querySelectorAll('.pill')[0].textContent;
""", query={"device": "999"})
    assert out == {"rows": 3, "scopeHidden": True, "total": "3"}


@node
def test_catalogue_remains_usable_while_each_secondary_panel_loads_and_retries(tmp_path):
    setup = """
  const original = ctx.fetch, waiting = {};
  ctx.fetch = (url, opts) => {
    const path = String(url).split('?')[0];
    if (['/api/devices/1/findings', '/api/application-guide', '/api/photo-knowledge'].includes(path))
      return new Promise((resolve) => { waiting[path] = {resolve, url, opts}; });
    return original(url, opts);
  };
  const complete = async (path) => { const call = waiting[path]; call.resolve(await original(call.url, call.opts)); };
  const failRequest = (path) => waiting[path].resolve({ok: false, status: 503, headers: {get: () => 'application/json'}, json: async () => ({error: 'offline'})});
"""
    routes = {**ROUTES, "/api/photo-knowledge": {"status": 200, "json": {"kinds": []}}}
    out = run(tmp_path, """
  out.rowsWhileWaiting = titles(P(tree, '.ex-list', '.os-scroll'));
  out.requests = Object.keys(waiting).sort();
  await complete('/api/application-guide'); await tick(); await tick();
  out.taskReady = !!byText(tree, 'button', 'Create next test');
  out.findingsStillLoading = tree.querySelectorAll('.ex-find')[0].textContent.includes('Loading');
  failRequest('/api/devices/1/findings'); await tick(); await tick();
  out.failure = tree.querySelectorAll('.ex-find')[0].textContent;
  const retry = byText(tree.querySelectorAll('.ex-find')[0], 'button', 'Retry').dispatch('click');
  await complete('/api/devices/1/findings'); await retry; await tick(); await tick();
  out.findings = tree.querySelectorAll('.ex-find')[0].textContent;
  const details = tree.querySelectorAll('.ex-find')[0].querySelector('details'); details.open = true;
  await complete('/api/photo-knowledge'); await tick(); await tick();
  out.photo = tree.querySelectorAll('.ex-find')[1].textContent;
  out.detailsKept = tree.querySelectorAll('.ex-find')[0].querySelector('details') === details && details.open;
""", routes=routes, setup=setup)
    assert len(out["rowsWhileWaiting"]) == 3
    assert out["requests"] == ["/api/application-guide", "/api/devices/1/findings", "/api/photo-knowledge"]
    assert out["taskReady"] and out["findingsStillLoading"]
    assert "Retry" in out["failure"] and "Тонкие линии" in out["findings"]
    assert "No photo engraving types" in out["photo"] and out["detailsKept"]


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
  out.toolbar = [q(scroll, '.lst-search') != null, chips(scroll), labelled(scroll, 'Experiment status') != null,
    selectOf(scroll, 'Task').options.map((o) => o.textContent), selectOf(scroll, 'Sort order').options.map((o) => [o.value, o.textContent]), q(scroll, '.lst-count').textContent];
  out.rowsInScroll = scroll.querySelectorAll('.lst-row').length; out.rowsInList = list.querySelectorAll('.lst-row').length; out.cards = list.querySelectorAll('article').length;
  out.cardTitles = titles(scroll);
  out.open = scroll.querySelectorAll('.lst-act').map((a) => [a.textContent, a.querySelector('a').getAttribute('href')]);
  const task = q(tree, '.ex-task');
  out.task = {head: P(task, '.os-col-head', 'h3').textContent, labels: task.querySelectorAll('label').map((l) => l.querySelector('span').textContent),
    next: byText(task, 'button', 'Create next test') != null, details: task.querySelectorAll('details').map((d) => d.textContent),
    inScroll: q(task, '.os-scroll').querySelectorAll('select, .matpick').length, result: q(task, '.dashboard-task-result').textContent, foot: q(task, '.dashboard-task-foot').textContent};
  const find = q(tree, '.ex-find');
  out.find = {head: q(find, '.os-col-head').textContent, cards: q(find, '.os-scroll').querySelectorAll('article').map((a) => a.textContent),
    link: P(find, '.os-col-head', 'a').getAttribute('href')};
  out.footerInside = tree.querySelectorAll('p').some((p) => has(p, 'demo'));
""")
    classes = out["root"].split()
    assert "os" in classes and "ex" in classes and "workspace" not in classes                 # the side menu stays
    assert out["top"] == ["os-head ex-head", "os-body ex-body"] and out["title"] == "Experiments"
    assert out["actions"] == [["AI researcher", "#/research", False], ["Color map", "#/colors", False], ["Advanced plate options", None, False], ["Add work and photo", "#/ingest", False]]
    assert out["columns"] == ["os-col ex-list", "ex-right"] and out["right"] == ["os-col ex-task", "os-col ex-find", "os-col ex-find"]
    assert out["listParts"] == ["os-col-head", "os-scroll"] and out["listHead"].startswith("Experiments") and out["pills"] == ["3", "1 to review"]
    search, states, state_group, tasks, orders, count = out["toolbar"]                                  # the shared list's search, filters and order, in the list column
    assert search and state_group and states == ["All · 3", "Needs review · 1", "Awaiting photo · 1", "Accepted · 1"]
    assert tasks == ["All tasks · 3", "Lettering · 3"] and count == "showing 3 of 3"
    assert orders == [["recent", "Most recent"], ["review", "Needs review first"], ["title", "Title"]]
    assert out["rowsInScroll"] == out["rowsInList"] == 3 and out["cards"] == 0                           # one line each; the cards open under a line
    assert out["cardTitles"] == ["Плата текста", "Тест Q-Pulse", "Шаг строк"]                             # the most recently active first, as the server sends
    assert out["open"] == [["Open", "#/experiment/plan-3"], ["Open", "#/experiment/eng-a"], ["Open", "#/experiment/eng-b"]]
    assert out["task"]["head"] == "Work goal" and out["task"]["labels"][:2] == ["Goal", "Material"] and out["task"]["inScroll"] >= 2
    assert out["task"]["next"] is True and "Laser A" not in out["task"]["result"] and "Разборчивые буквы выбранного размера" in out["task"]["result"]
    assert out["task"]["details"] == [out["task"]["details"][0]] and out["task"]["details"][0].startswith("Finding evidence and settings")
    assert "evidence: review #7, observations #11, #12" in out["task"]["details"][0] and "30%" in out["task"]["details"][0].replace(" ", "")   # the long lines are folded
    assert "основание" not in out["task"]["result"].split("Основание вывода")[0] and "text readability" not in out["task"]["foot"]
    assert out["task"]["foot"].startswith("Plate: lettering 3 × 3, three sizes")
    assert out["find"]["head"].startswith("Material findings") and len(out["find"]["cards"]) == 2 and out["find"]["link"] == "#/devices/1"
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
  await chip(scroll, 'Needs review').dispatch('click'); await tick();
  out.state = titles(scroll);
  await chip(scroll, 'All').dispatch('click'); await tick();
  out.tasks = selectOf(scroll, 'Task').options.map((o) => [o.value, o.textContent]);
  const task = selectOf(scroll, 'Task'); task.value = 'text'; await task.dispatch('change'); await tick();
  out.task = titles(scroll);
  const order = selectOf(scroll, 'Sort order'); order.value = 'title'; await order.dispatch('change'); await tick();
  out.ordered = titles(scroll);
  out.kept = JSON.parse(ctx.__store['list:experiments']); out.renders = ctx.__renders.length;
""", routes=routes)
    assert out["searched"] == ["Тест Q-Pulse"] and out["chipsSearched"] == ["All · 1", "Accepted · 1"]      # the search reads the title; the counts follow it
    assert out["state"] == ["Шаг строк"]
    assert out["tasks"] == [["", "All tasks · 3"], ["text", "Lettering · 2"], ["line", "Lines · 1"], ["fill", "Fill · 1"]]    # only the tasks the experiments have
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
    assert nothing["rows"] == 0 and nothing["text"] == "No results: change the search, status or laser." and nothing["pills"] == ["3", "1 to review"]
    assert nothing["page"] == ["os-head ex-head", "os-body ex-body"]                                       # the frame stays whole
    none = run(tmp_path, "out.text = P(tree, '.ex-list', '.os-scroll').querySelector('.lst-empty').textContent;",
               routes={**ROUTES, "/api/experiments": {"status": 200, "json": []}})
    assert none["text"] == "No experiments yet. Create a plate or add a work and photo."


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
    assert len(out["first"]) == 20 and out["first"][:2] == ["Плата 25", "Плата 24"] and out["count"] == "showing 20 of 25"
    assert out["more"] == "Show 5 more" and out["all"] == 25 and out["after"] is None
    assert out["card"] == [1, "Плата 25", "/api/pairs/7/photo.png?visibility=lifted&size=480"]           # the card opens under its line, built then


@node
def test_the_experiments_of_one_laser_show_its_pill_and_the_way_back_in_the_filters(tmp_path):
    out = run(tmp_path, """
  const filters = tree.querySelector('.ex-filters');
  out.first = filters.children[0].textContent; out.link = filters.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
  out.pills = P(tree, '.ex-list', '.os-col-head').querySelectorAll('.pill').map((p) => p.textContent);
""", query={"device": "1"})
    assert out["first"] == "Laser: Laser AAll lasers" and out["link"] == [["All lasers", "#/experiments"]] and out["pills"] == ["3 of 3", "1 to review"]


# -- behaviour that must not change -----------------------------------------------------------------------------------------------------
@node
def test_next_test_preview_does_not_block_the_catalog_and_must_finish_before_creation(tmp_path):
    setup = """
  const original = ctx.fetch;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  ctx.fetch = async (url, opts) => { if (String(url).split('?')[0] === '/api/application-guide/preview') await gate; return original(url, opts); };
"""
    out = run(tmp_path, """
  const task = tree.querySelector('.ex-task');
  const create = byText(task, 'button', 'Create next test');
  out.before = [create.disabled, task.textContent.includes('Calculating plate size and time'), titles(P(tree, '.ex-list', '.os-scroll')).length];
  await create.dispatch('click'); await tick();
  out.beforePosts = ctx.requests.filter((r) => r.path === '/api/application-guide/next-plate').length;
  release(); await tick(); await tick();
  out.after = [create.disabled, task.textContent.includes('44 × 35 mm'), task.textContent.includes('Estimated engraving time: 2 min 00 s')];
""", setup=setup)
    assert out["before"] == [True, True, 3] and out["beforePosts"] == 0
    assert out["after"] == [False, True, True]


@node
def test_next_test_preview_reports_an_unchecked_work_field_and_incomplete_time(tmp_path):
    preview = {"revision": "partial", "summary": {"size_mm": {"width": 44, "height": 35}, "test_features": 9,
        "work_field": {"checked": False, "note": "The lens work field is unknown; placement was not checked."}},
        "time": {"seconds": 30, "complete": False}}
    out = run(tmp_path, """
  const task = tree.querySelector('.ex-task');
  out.text = task.textContent;
  out.enabled = !byText(task, 'button', 'Create next test').disabled;
""", routes={**ROUTES, "/api/application-guide/preview": {"status": 200, "json": preview}})
    assert out["enabled"] and "placement was not checked" in out["text"] and "known layers only" in out["text"]


@node
def test_pulse_preview_ignores_an_older_response_after_a_new_selection(tmp_path):
    routes = {**ROUTES, "/api/devices": {"status": 200, "json": [{**ROUTES["/api/devices"]["json"][0],
        "passport": {"pulse_steps": [{"pulse_width_ns": 100}, {"pulse_width_ns": 250}]}}]},
        "/api/application-guide": {**ROUTES["/api/application-guide"], "json": {**ROUTES["/api/application-guide"]["json"],
            "plate": {**ROUTES["/api/application-guide"]["json"]["plate"], "settings": {"pulse_width": None}}}}}
    setup = """
  const original = ctx.fetch, pending = {};
  ctx.fetch = (url, opts) => String(url).split('?')[0] === '/api/application-guide/preview'
    ? new Promise((resolve) => { pending[new URLSearchParams(String(url).split('?')[1]).get('pulse_width')] = resolve; }) : original(url, opts);
  const answer = (width, revision) => ({ok: true, status: 200, headers: {get: () => 'application/json'},
    json: async () => ({revision, summary: {size_mm: {width, height: 35}, test_features: 9, work_field: {checked: true}}, time: {seconds: 120, complete: true}})});
"""
    out = run(tmp_path, """
  const task = tree.querySelector('.ex-task');
  const pulse = task.querySelectorAll('select').find((s) => s.options.some((o) => o.textContent === '250 ns'));
  out.initial = [byText(task, 'button', 'Create next test').disabled, task.textContent.includes('Select a pulse width')];
  pulse.value = '100'; pulse.dispatch('change'); await tick();
  pulse.value = '250'; pulse.dispatch('change'); await tick();
  pending['250'](answer(50, 'newest')); await tick(); await tick();
  pending['100'](answer(20, 'old')); await tick(); await tick();
  out.display = [task.textContent.includes('50 × 35 mm'), task.textContent.includes('20 × 35 mm')];
  await byText(task, 'button', 'Create next test').dispatch('click'); await tick();
  out.body = JSON.parse(ctx.requests.find((r) => r.path === '/api/application-guide/next-plate').body);
""", routes=routes, setup=setup)
    assert out["initial"] == [True, True] and out["display"] == [True, False]
    assert out["body"]["pulse_width"] == 250 and out["body"]["preview_revision"] == "newest"


@node
def test_failed_plate_preview_offers_retry_without_hiding_the_experiment_list(tmp_path):
    routes = {**ROUTES, "/api/application-guide/preview": {"status": 503, "json": {"error": "preview service unavailable"}}}
    out = run(tmp_path, """
  const task = tree.querySelector('.ex-task');
  out.failed = [byText(task, 'button', 'Create next test').disabled, task.textContent.includes('preview service unavailable'),
    titles(P(tree, '.ex-list', '.os-scroll')).length];
  data.routes['/api/application-guide/preview'] = {status: 200, json: {revision: 'fresh', summary: {size_mm: {width: 44, height: 35},
    test_features: 9, work_field: {checked: true}}, time: {seconds: 120, complete: true}}};
  await byText(task, 'button', 'Retry plate preview').dispatch('click'); await tick();
  out.retry = [byText(task, 'button', 'Create next test').disabled, task.textContent.includes('44 × 35 mm')];
""", routes=routes)
    assert out["failed"] == [True, True, 3] and out["retry"] == [False, True]


@node
def test_the_next_test_button_still_creates_the_plate_for_the_goal_material_and_laser_and_opens_it(tmp_path):
    out = run(tmp_path, """
  const button = byText(tree.querySelector('.ex-task'), 'button', 'Create next test');
  await button.dispatch('click'); await tick();
  const post = ctx.requests.find((r) => r.method === 'POST');
  out.path = post.path; out.body = JSON.parse(post.body); out.hash = ctx.location.hash;
""")
    assert out["path"] == "/api/application-guide/next-plate" and out["hash"] == "#/experiment/plan-9"
    assert out["body"] == {"device_id": 1, "material_id": 1, "goal": "text", "pulse_width": None, "preview_revision": "preview-1"}


@node
def test_the_task_pickers_remember_their_choice_and_reload(tmp_path):
    out = run(tmp_path, """
  const selects = tree.querySelector('.ex-task').querySelectorAll('select, .matpick');        // the material is the stock selector, no longer a drop-down
  out.labels = selects.map((s) => s.getAttribute('aria-label'));
  selects[0].value = 'line'; await selects[0].dispatch('change');
  out.goal = ctx.__store['experiment-dashboard-goal']; out.renders = ctx.__renders.length;
  out.guideUrls = ctx.requests.filter((r) => r.path === '/api/application-guide').map((r) => r.url);
""")
    assert out["labels"] == ["Research goal", "Material and stock"] and out["goal"] == "line" and out["renders"] == 1
    assert out["guideUrls"] == ["/api/application-guide?device_id=1&material_id=1&goal=text"]


@node
def test_without_a_laser_the_screen_offers_to_add_one_and_does_not_offer_a_plate(tmp_path):
    routes = {**ROUTES, "/api/devices": {"status": 200, "json": []}}
    out = run(tmp_path, """
  out.root = tree.className; out.text = tree.textContent;
  out.plate = byText(tree, 'button', 'Advanced plate options').disabled; out.link = byText(tree, 'a', 'Lasers').getAttribute('href');
""", routes=routes)
    assert "os" in out["root"].split() and "First add a laser and install a lens" in out["text"] and out["plate"] is True and out["link"] == "#/devices"


@node
def test_the_laser_page_shows_the_same_short_list_with_the_same_filters_and_keeps_its_own_choice(tmp_path):
    out = run(tmp_path, """
  const all = data.routes['/api/experiments'].json;
  const card = ctx.DeviceView.experimentsCard(all, {id: 1, name: 'Laser A', lens: {id: 5, name: 'F-Theta', focal_length_mm: 174}}, [{id: 5, name: 'F-Theta', focal_length_mm: 174}]);
  const panel = card.querySelectorAll('section').find((s) => s.textContent.startsWith('Эксперименты этого лазера'));
  out.head = panel.querySelector('.dashboard-panel-head').textContent;
  out.toolbar = [panel.querySelector('.lst-search') != null, chips(panel), selectOf(panel, 'Task').options.map((o) => o.textContent),
    selectOf(panel, 'Sort order').options.map((o) => o.textContent)];
  await chip(panel, 'Accepted').dispatch('click'); await tick();
  out.accepted = titles(panel);
  out.kept = [JSON.parse(ctx.__store['list:laser-experiments']).filters, ctx.__store['list:experiments'] || null];
  out.api = Object.keys(ctx.ExperimentCards);
  out.empty = ctx.ExperimentCards.list([], {empty: 'Пусто'}).querySelector('.lst-empty').textContent;
""")
    assert out["head"] == "Эксперименты этого лазера3Открыть в общем списке"
    search, states, tasks, orders = out["toolbar"]
    assert search and states == ["All · 3", "Needs review · 1", "Awaiting photo · 1", "Accepted · 1"] and tasks == ["All tasks · 3", "Lettering · 3"]
    assert orders == ["Most recent", "Needs review first", "Title"]
    assert out["accepted"] == ["Тест Q-Pulse"] and out["kept"][0] == {"status": "accepted", "task": ""} and out["kept"][1] is None   # its own choice, not the screen's
    assert out["api"] == ["card", "list", "layers"] and out["empty"] == "Пусто"


# -- «Create plate»: the plate dialog ---------------------------------------------------------------------------------------------
DIALOG = """
const fs = require('fs');
const {context, load, El} = require(%(dom)s);
// the small DOM keeps no inline style; the dialog shows and hides the card of the chosen plate type through element.style
Object.defineProperty(El.prototype, 'style', {get() { return this._style || (this._style = {}); }});
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'forms.js', 'dialogs.js', 'list.js', 'hardware.js', 'tasks.js', 'screens/material-picker.js', 'screens/plate-dialog.js', {code: 'globalThis.PlateDialog = PlateDialog;'}]);
const tick = () => new Promise((r) => setTimeout(r, 0));
/** A control by its name: its aria-label, or the text of the label it points to (aria-labelledby). */
const labelled = (root, label) => root.querySelectorAll('input, select, textarea, [aria-label]').find((el) => el.getAttribute('aria-label') === label
  || (el.getAttribute('aria-labelledby') && root.querySelectorAll('[id]').some((n) => n.getAttribute('id') === el.getAttribute('aria-labelledby') && n.textContent === label)));
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
    out.photoCard = card(labelled(box, 'Картинка копий (PNG или JPEG)')); out.greyCard = card(labelled(box, 'Строки шкал серого'));
    labelled(box, 'Картинка копий (PNG или JPEG)').files = [{name: 'yana.png', arrayBuffer: async () => new Uint8Array([137, 80, 78, 71]).buffer}];
    labelled(box, 'Вид копий').value = 'grayscale';
    labelled(box, 'Размер копии (длинная сторона)').value = '24';
    labelled(box, 'Min мощность копий (градации серого)').value = '2';
  });
""")
    assert out["none"] is None                                                       # nothing is sent without a picture
    assert out["photoCard"] == "" and out["greyCard"] == "none"
    assert out["photo"]["test_type"] == "photo_variations"
    assert out["photo"]["variations"] == {"picture_name": "yana.png", "dither": "grayscale", "copy_mm": 24, "min_power": 2, "picture_png": "iVBORw=="}


@node
def test_the_plate_dialog_says_the_unit_and_the_permitted_values_of_every_number_and_keeps_a_wrong_one_beside_its_box(tmp_path):
    out = run_dialog(tmp_path, """
  const words = (el) => (el.getAttribute('aria-describedby') || '').split(' ').map((id) => (ctx.document.getElementById(id) || {textContent: ''}).textContent).join(' ');
  const dialog = await ctx.PlateDialog.open(data.devices, data.materials, null, {type: 'fill_sizes'});
  await tick();
  const box = dialog.el;
  labelled(box, 'Заготовка').value = '1';
  out.words = {width: words(labelled(box, 'Ширины полосок заливки')), power: words(labelled(box, 'Базовая мощность')), speed: words(labelled(box, 'Базовая скорость')),
    frequency: words(labelled(box, 'Базовая частота')), size: words(labelled(box, 'Максимальная ширина платы')), passes: words(labelled(box, 'Глобальные проходы'))};
  // a width below the least the server takes: nothing is sent, the reason stands beside the box and the typed text stays
  labelled(box, 'Ширины полосок заливки').value = '5, 2, 40';
  const before = ctx.requests.length;
  await box.querySelectorAll('button').find((b) => b.textContent === 'Создать плату').dispatch('click');
  for (let i = 0; i < 5; i += 1) await tick();
  out.wrong = {posted: ctx.requests.slice(before).filter((r) => r.method === 'POST').length, kept: labelled(box, 'Ширины полосок заливки').value,
    invalid: labelled(box, 'Ширины полосок заливки').getAttribute('aria-invalid'), beside: box.querySelectorAll('.f-error').map((n) => n.textContent),
    summary: box.querySelectorAll('.f-form-error').map((n) => n.textContent), toasts: ctx.document.body.querySelectorAll('.toast').length};
  // the laser's own range: 5000 kHz is above what this laser takes
  labelled(box, 'Ширины полосок заливки').value = '5, 20';
  labelled(box, 'Базовая частота').value = '5000';
  await box.querySelectorAll('button').find((b) => b.textContent === 'Создать плату').dispatch('click');
  for (let i = 0; i < 5; i += 1) await tick();
  out.laser = box.querySelectorAll('.f-error').map((n) => n.textContent);
""")
    assert "from 3 to 300" in out["words"]["width"] and "unit: mm" in out["words"]["width"] and "не больше 5" in out["words"]["width"]
    assert "greater than 0 and at most 100" in out["words"]["power"] and "unit: %" in out["words"]["power"]
    assert "greater than 0 and at most 10000" in out["words"]["speed"] and "unit: mm/s" in out["words"]["speed"]
    assert "from 1 to 4000" in out["words"]["frequency"] and "unit: kHz" in out["words"]["frequency"]       # the laser's own range
    assert "from 1 to 300" in out["words"]["size"] and "from 1 to 20" in out["words"]["passes"] and "whole number" in out["words"]["passes"]
    wrong = out["wrong"]
    assert wrong["posted"] == 0 and wrong["kept"] == "5, 2, 40" and wrong["invalid"] == "true" and wrong["toasts"] == 0
    assert any("Значение 2: Allowed: from 3 to 300 mm. Entered: 2" in text for text in wrong["beside"])
    assert any("Ширины полосок заливки" in text and "remain in the form" in text for text in wrong["summary"])
    assert any("Allowed: from 1 to 4000 kHz. Entered: 5000" in text for text in out["laser"])


@node
def test_a_refusal_of_the_server_stays_in_the_plate_dialog_with_everything_typed(tmp_path):
    out = run_dialog(tmp_path, """
  data.routes['/api/capability-plates'] = {status: 400, json: {error: 'скорость теста не должна превышать 10000 мм/с', kind: 'invalid'}};
  const dialog = await ctx.PlateDialog.open(data.devices, data.materials, null, {type: 'fill_sizes'});
  await tick();
  const box = dialog.el;
  labelled(box, 'Заготовка').value = '1';
  labelled(box, 'Базовая скорость').value = '900';
  await box.querySelectorAll('button').find((b) => b.textContent === 'Создать плату').dispatch('click');
  for (let i = 0; i < 6; i += 1) await tick();
  out.kept = labelled(box, 'Базовая скорость').value;
  out.open = !!box.parentNode;
  out.said = box.querySelectorAll('.f-form-error').map((n) => n.textContent).filter(Boolean);
  out.toasts = ctx.document.body.querySelectorAll('.toast').length;
  // the form of a new stock record inside the dialog: its refusal stands beside it too
  data.routes['/api/materials'] = {status: 400, json: {error: 'material name is required', kind: 'invalid'}};
  await box.querySelectorAll('button').find((b) => b.textContent === 'Сохранить заготовку').dispatch('click');
  for (let i = 0; i < 6; i += 1) await tick();
  out.stock = box.querySelectorAll('.f-form-error').map((n) => n.textContent).filter((t) => t.startsWith('Запись'));
  out.toastsAfter = ctx.document.body.querySelectorAll('.toast').length;
""")
    assert out["open"] and out["kept"] == "900" and out["toasts"] == 0
    assert len(out["stock"]) == 1 and "Запись заготовки failed" in out["stock"][0] and out["toastsAfter"] == 0
    assert len(out["said"]) == 1 and "скорость теста не должна превышать 10000 мм/с" in out["said"][0] and "remain in the form" in out["said"][0]


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
    for part in ("h('div', {class: 'os ex'}, hero,", "h('div', {class: 'os-body ex-body'},", "h('section', {class: 'os-col ex-list'},", "h('div', {class: 'ex-right'}, taskSlot,",
                 "h('section', {class: 'os-col ex-task'},", "{class: 'os-col ex-find'}", "ExperimentCards.list(items, {id: 'experiments',",
                 "panel('Material findings', latest.size, insightCards,", "App.post('/application-guide/next-plate'", "PlateDialog.open(devices, null, reload)"):
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
  const panel = tree.querySelectorAll('section').find((s) => has(s, 'ex-find') && s.textContent.includes('Photo engraving: laboratory recommendations'));
  out.head = panel.querySelector('.os-col-head').textContent;
  out.cards = panel.querySelectorAll('article').map((a) => a.textContent);
  out.image = tree.querySelectorAll('article').find((a) => a.textContent.startsWith('Image')).textContent;
  out.asked = ctx.requests.filter((r) => r.path === '/api/photo-knowledge').map((r) => r.url);
  out.buttons = panel.querySelectorAll('article').map((a) => a.querySelectorAll('button').map((b) => b.textContent));
  await byText(panel.querySelectorAll('article')[1], 'button', 'Сделать плату: 3 копии').dispatch('click'); await tick(); await tick();
  out.made = ctx.requests.filter((r) => r.path === '/api/photo-knowledge/plate').map((r) => JSON.parse(r.body));
  out.went = ctx.location.hash;
""", routes=routes)
    assert out["head"].startswith("Photo engraving: laboratory recommendations3")                    # three kinds have an experiment proposed
    assert out["asked"] == ["/api/photo-knowledge?device_id=1&lens_id=5&material_id=1"]
    jarvis, atkinson, stucki, grey = out["cards"]
    assert "мощность вдвое больше: темнее на 6 L*, оценка +0,1 (по фото №7)" in jarvis                 # what the power does here
    assert "Плата 42 × 25 мм: 2 копии по 18 × 12 мм" in jarvis and "мощность 20 % → 18 %" in jarvis
    assert "Картинки для платы ещё нет: сделайте первую плату из фотоработы или фотозоны" in stucki   # nothing to engrave it from yet
    assert out["buttons"] == [["Сделать следующую плату"], ["Сделать плату: 3 копии"], [], []]
    # the image purpose of the capability plate no longer says only «needs a test»: what the photographs measured is said there
    assert out["image"].startswith("ImagePhoto measured") and "the best result was “Jarvis” (score 0.81 from photo #7)" in out["image"]
    assert jarvis.startswith("Jarvisпоиск идёт") and "Лучшее: 20 %, 125 мм/с, 60 кГц, 200 нс, шаг 0,01 мм — автоматическая оценка 0,81 по фото №7" in jarvis
    assert "Следующая плата вокруг копии 2 J P20, изменения вдвое меньше." in jarvis and jarvis.endswith("Сделать следующую плату")
    assert "Ещё не фотографировался на этом лазере и титане." in atkinson and "на лучших настройках другого вида точками" in atkinson
    assert "Начните со шкал серого (Фотогравировка → Шкалы серого)." in grey
    assert out["made"] == [{"device_id": 1, "lens_id": 5, "material_id": 1, "kind": "atkinson"}] and out["went"] == "#/experiment/plan-12"


@node
def test_a_long_list_of_supporting_observations_is_a_count_and_a_list_not_a_sentence(tmp_path):
    many = list(range(40, 52))
    routes = {**ROUTES, "/api/application-guide": {**ROUTES["/api/application-guide"], "json": {**ROUTES["/api/application-guide"]["json"],
              "support": {"pair_id": 7, "observation_ids": many, "engravings": 2, "photographs": 3, "missing_context": []}}}}
    short = run(tmp_path, "out.text = tree.querySelector('.ex-task').textContent; out.refs = tree.querySelectorAll('.srefs').length;")
    long_ = run(tmp_path, "out.text = tree.querySelector('.ex-task').textContent; out.refs = tree.querySelectorAll('.srefs').length;"
                "out.count = tree.querySelector('.srefs-count').textContent;", routes=routes)
    assert "observations #11, #12" in short["text"] and short["refs"] == 0                       # a few stay in the sentence, as before
    assert "наблюдения №40" not in long_["text"] and long_["refs"] == 1 and long_["count"] == "12"
    assert "Evidence observations" in long_["text"] and "evidence: review #7" in long_["text"]
