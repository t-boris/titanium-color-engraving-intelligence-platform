"""The general colour map on one screen (REQ-029, REQ-044, DEC-080): filters on the left, the map in the middle with the picked colour under it,
the colour search on the right with its results as the only list that scrolls. Run in node over the small DOM of the other screen tests,
with answers shaped like the server's."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[1] / "src" / "titanium_platform" / "ui"
CSS = (UI / "styles.css").read_text(encoding="utf-8")
SCREEN = (UI / "screens" / "color-map.js").read_text(encoding="utf-8")
TABLES = ["i18n.js", "i18n-more.js", "i18n-device.js", "i18n-rest.js", "i18n-photo.js", "i18n-tasks.js", "i18n-data.js", "i18n-findings.js",
          "i18n-palette.js", "i18n-gaps.js"]
node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# the router and the browser's storage, as the screen meets them
GLUE = ("App.render = () => {}; App.toast = (text) => { (globalThis.__toasts = globalThis.__toasts || []).push(text); }; const __store = {};"
        "globalThis.__went = []; App.go = (route) => { __went.push(route); };"
        "globalThis.sessionStorage = {getItem: (k) => (k in __store ? __store[k] : null), setItem: (k, v) => { __store[k] = String(v); }, removeItem: (k) => { delete __store[k]; }};"
        "globalThis.__store = __store; const __svg = document.createElementNS, __html = document.createElement; document.createElementNS = (ns, t) => { const e = __svg(ns, t); e.style = {}; return e; };"
        "document.createElement = (t) => { const e = __html(t); e.style = {}; return e; };")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'photo-modes.js', 'dialogs.js', 'hardware.js', 'tasks.js', {code: %(glue)s}, 'screens/dot-pick.js', 'screens/color-map.js',
                    {code: 'globalThis.ColorMap = ColorMap;'}]);
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const labelled = (root, text) => root.querySelectorAll('label').find((l) => l.querySelector('span') && l.querySelector('span').textContent === text);
const has = (el, cls) => (el.className || '').split(' ').includes(cls);
(async () => {
  const out = {};
  const screen = async () => { const t = await ctx.ColorMap.render({query: {}}); await tick(); await tick(); return t; };
  let tree = await screen();
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def point(i, lab, **extra):
    return {"id": f"p{i}", "display_lab": lab, "title": f"Test {i}", "layer_name": f"C0{i}", "layer_index": i, "referenced": True, "provisional": False,
            "measurement": "calibrated", "approximate": False, "pair_id": 10 + i, "experiment": f"eng-{i}", "origin": "test", "work_id": None, "source": "color", "task": None, "review": None,
            "setup_label": "Laser · lens", "material": "Grade 2", "photo": f"IMG_{i}.DNG", "date": "2026-10-19T10:00:00", "parameters": {"power": 25, "frequency": 330,
            "speed": 800, "pulse_width": 4, "line_interval": 0.005, "passes": 1}, "time": {}, "time_s_per_cm2": 41.0, **extra}


def colours(points=None):
    points = [point(1, [80.0, 4.0, 30.0]), point(2, [55.0, 12.0, 20.0]), point(3, [30.0, -2.0, -6.0], measurement="relative")] if points is None else points
    return {"points": points, "counts": {"calibrated": sum(p["measurement"] == "calibrated" for p in points), "relative": sum(p["measurement"] == "relative" for p in points),
                                         "unreferenced": 0, "provisional": 0, "slower": 0},
            "options": {"setups": [{"key": "d1:l1", "label": "Laser · lens", "device_id": 1, "lens_id": 1}], "materials": ["Grade 2", "Grade 5"], "tasks": ["color", "text"]}}


SEARCH = {"matches": [{"id": "p1", "display_lab": [80.0, 4.0, 30.0], "distance": 0.4, "measurement": "calibrated", "within_tolerance": True, "approximate": False, "referenced": True,
                       "provisional": False, "repeats": 2, "photographs": 1, "experiments": ["eng-1"], "repeatability": {"assessed": False}, "observation_ids": [3],
                       "provisional_checks": [], "missing_context": [], **point(1, [80.0, 4.0, 30.0])}],
          "order": {"by": "distance"}, "counts": {"unreferenced": 0, "provisional": 0, "slower": 0}}


def run(tmp_path, routes, body):
    (tmp_path / "data.json").write_text(json.dumps({"routes": routes}), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")), "ui": json.dumps(str(UI) + "/"),
                                 "tables": json.dumps(TABLES), "glue": json.dumps(GLUE), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


def routes_of(world=None):
    return {"/api/colors": {"status": 200, "json": world or colours()}, "/api/colors/search": {"status": 200, "json": SEARCH}}


# -- the three columns ---------------------------------------------------------------------------------------------------------------------
@node
def test_the_map_is_one_workspace_of_three_columns_filters_map_and_colour_search(tmp_path):
    out = run(tmp_path, routes_of(), """
  const cols = tree.children.find((c) => has(c, 'os-body')).children;
  out.root = tree.className; out.cols = cols.map((c) => c.className);
  out.head = tree.querySelector('.os-head').textContent; out.h2 = tree.querySelector('h2').textContent;
  const [filters, middle, right] = cols;
  out.filterTitle = filters.querySelector('h3').textContent;
  out.labels = filters.querySelectorAll('label').map((l) => (l.querySelector('span') || l).textContent);
  out.selects = filters.querySelectorAll('select').length;
  out.checkbox = filters.querySelectorAll('input').some((i) => i.getAttribute('type') === 'checkbox');
  out.details = filters.querySelectorAll('details').map((d) => [d.querySelector('summary').textContent, d.textContent]);
  out.filtersScroll = has(filters.children[1], 'os-scroll');
  out.middleTitle = middle.querySelector('h3').textContent;
  out.planes = middle.querySelectorAll('button').map((b) => b.textContent);
  out.plot = middle.querySelectorAll('div').filter((d) => has(d, 'cm-plot')).map((d) => d.children.map((c) => c.localName));
  out.circles = middle.querySelectorAll('circle').length;
  out.detailInMiddle = middle.querySelectorAll('div').some((d) => has(d, 'cm-detail') && d.hidden === true);
  out.rightTitle = right.querySelector('h3').textContent;
  out.target = right.querySelector('.cm-target').querySelectorAll('input').length;
  out.findButton = !!byText(right, 'button', 'Найти');
  out.rightScroll = right.children.filter((c) => has(c, 'os-scroll')).length;
""")
    assert out["root"] == "os cm" and out["cols"] == ["os-col", "os-col", "os-col"] and out["h2"] == "Карта цветов"
    assert "Показано цветов: 3 · по эталонной карте 2 · относительно камеры 1" in out["head"] and "Выберите лазер и линзу" in out["head"]
    assert out["filterTitle"] == "Фильтры" and out["selects"] == 4 and out["checkbox"] is True and out["filtersScroll"] is True
    assert out["labels"][:5] == ["Лазер и линза", "Материал", "Как измерен", "Задача", "Не дольше, мин/см²"]
    assert [s for s, _ in out["details"]] == ["Как это считается"] and "Время гравировки — оценка по настройкам рецепта" in out["details"][0][1]
    assert out["middleTitle"] == "Карта цветов" and out["planes"] == ["a* × b*", "a* × L*", "b* × L*", "+", "−", "Весь вид"]
    assert out["plot"] == [["div"]] and out["circles"] == 3 and out["detailInMiddle"] is True              # the picked colour is described under the map
    assert out["rightTitle"] == "Какой цвет нужен" and out["target"] == 5 and out["findButton"] is True and out["rightScroll"] == 1      # the picker, L, a, b and the tolerance


@node
def test_the_long_explanation_is_folded_and_the_counts_are_one_line_in_the_head(tmp_path):
    world = colours()
    world["counts"].update(unreferenced=4, provisional=2, slower=5)
    out = run(tmp_path, routes_of(world), """
  out.sub = tree.querySelector('.sub').textContent;
  out.outside = tree.querySelectorAll('p').filter((p) => p.textContent.includes('Время гравировки — оценка')).map((p) => p.parentNode.localName);
  out.provisionalNote = tree.querySelector('details').textContent.includes('Предварительные цвета обведены');
""")
    assert "из них без привязки к чистому титану 4" in out["sub"] and "предварительных (проверка ещё не принята) 2" in out["sub"] and "скрыто как более долгие" in out["sub"]
    assert out["outside"] == ["details"] and out["provisionalNote"] is True


@node
def test_with_a_laser_and_lens_chosen_the_head_links_to_their_model_and_without_colours_the_map_says_so(tmp_path):
    out = run(tmp_path, routes_of(colours([])), """
  out.plot = tree.querySelectorAll('div').filter((d) => has(d, 'cm-plot')).map((d) => d.textContent);
  out.cols = tree.querySelector('.os-body').children.length;
  ctx.sessionStorage.setItem('color-map', JSON.stringify({setup: 'd1:l1'}));
  tree = await screen();
  out.link = tree.querySelector('.os-head').querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
""")
    assert out["plot"] == ["Нет цветов под такие условия."] and out["cols"] == 3
    assert out["link"] == [["Модель и прогноз параметров для этого лазера с линзой", "#/colors?device=1&lens=1"]]


# -- the filters still ask the server again ------------------------------------------------------------------------------------------------
@node
def test_a_filter_is_remembered_and_the_next_query_carries_it(tmp_path):
    out = run(tmp_path, routes_of(), """
  const left = () => tree.querySelector('.os-body').children[0];
  const again = async () => { tree = await screen(); };                          // the router draws the screen again after each change
  const pick = async (label, value) => { const s = labelled(left(), label).querySelector('select'); s.value = value; await s.dispatch('change'); await again(); };
  await pick('Как измерен', 'relative'); await pick('Материал', 'Grade 5');
  out.stored = JSON.parse(ctx.__store['color-map']);
  const limit = labelled(left(), 'Не дольше, мин/см²').querySelector('input'); limit.value = '0:30'; await limit.dispatch('change'); await again();
  const box = left().querySelectorAll('input').find((i) => i.getAttribute('type') === 'checkbox'); box.checked = true; await box.dispatch('change'); await again();
  out.after = JSON.parse(ctx.__store['color-map']);
  const before = ctx.requests.length; await again();
  out.query = ctx.requests.slice(before).filter((r) => r.path === '/api/colors').map((r) => r.url);
  out.selected = labelled(left(), 'Как измерен').querySelector('select').value;
  const bad = labelled(left(), 'Не дольше, мин/см²').querySelector('input'); bad.value = 'abc'; await bad.dispatch('change');
  out.toasts = ctx.__toasts;
""")
    assert out["stored"]["measurement"] == "relative" and out["stored"]["material"] == "Grade 5"
    assert out["after"]["maxTime"] == 30 and out["after"]["hide"] is True and out["after"]["measurement"] == "relative"
    assert len(out["query"]) == 1 and all(part in out["query"][0] for part in ("measurement=relative", "material=Grade+5", "max_time_s_per_cm2=30", "include_unreferenced=false"))
    assert out["selected"] == "relative" and out["toasts"] == ["Введите время как минуты:секунды (например 0:30) или минуты числом"]


@node
def test_the_planes_and_the_lightness_range_are_remembered_for_the_next_drawing(tmp_path):
    out = run(tmp_path, routes_of(), """
  const middle = tree.querySelector('.os-body').children[1];
  await byText(middle, 'button', 'a* × L*').dispatch('click');
  out.plane = JSON.parse(ctx.__store['color-map']).plane;
  tree = await screen();
  const [from] = tree.querySelector('.os-body').children[1].querySelectorAll('input'); from.value = '50'; await from.dispatch('change');
  out.band = JSON.parse(ctx.__store['color-map']).band;
  tree = await screen();
  out.primary = tree.querySelectorAll('button').filter((b) => has(b, 'primary') && has(b, 'btn-small')).map((b) => b.textContent);
  out.shown = tree.querySelector('.cm-bar').textContent;
  out.circles = tree.querySelectorAll('circle').length;
""")
    assert out["plane"] == "La" and out["band"] == [50, 100]
    assert out["primary"] == ["a* × L*"] and "показано 2 из 3" in out["shown"] and out["circles"] == 2


# -- picking a colour and searching --------------------------------------------------------------------------------------------------------
@node
def test_a_picked_colour_is_described_under_the_map_and_the_search_fills_the_list_on_the_right(tmp_path):
    out = run(tmp_path, routes_of(), """
  const [, middle, right] = tree.querySelector('.os-body').children;
  const detail = middle.querySelectorAll('div').find((d) => has(d, 'cm-detail'));
  out.hiddenAtFirst = detail.hidden;
  await middle.querySelectorAll('circle')[0].dispatch('click');
  out.detailShown = !detail.hidden; out.detail = detail.textContent; out.detailTitle = detail.querySelector('h3').textContent;
  out.pickedCircle = middle.querySelectorAll('circle').filter((c) => c.getAttribute('stroke') === '#ffffff').length;
  const before = ctx.requests.length;
  await byText(detail, 'button', 'Найти такой же среди всех').dispatch('click'); await tick(); await tick();
  const list = right.children.find((c) => has(c, 'os-scroll'));
  out.requests = ctx.requests.slice(before).map((r) => r.url);
  out.list = list.textContent; out.hits = list.querySelectorAll('article').length;
  out.fields = right.querySelector('.cm-target').querySelectorAll('input').map((i) => i.value);
  out.target = JSON.parse(ctx.__store['color-map']).target;
  out.targetMark = middle.querySelectorAll('circle').some((c) => c.getAttribute('stroke') === '#ffd166');
""")
    assert out["hiddenAtFirst"] is True and out["detailShown"] is True and out["detailTitle"] == "Выбранный цвет"
    assert "L 80.0 · a 4.0 · b 30.0" in out["detail"] and "по эталонной карте" in out["detail"] and "время ≈ 41.0 с на см² (оценка)" in out["detail"]
    assert out["pickedCircle"] == 1
    assert out["requests"][0].startswith("/api/colors/search?L=80&a=4&b=30&limit=12") and any(u.startswith("/api/colors/settings?L=80&a=4&b=30") for u in out["requests"])
    assert "Где встречался такой цвет" in out["list"] and out["hits"] == 1 and "ΔE 0.4" in out["list"] and "в допуске" in out["list"]
    assert out["fields"][1:4] == ["80", "4", "30"] and out["target"] == [80, 4, 30] and out["targetMark"] is True


@node
def test_the_find_button_searches_the_typed_colour_with_the_tolerance_and_the_filters(tmp_path):
    out = run(tmp_path, routes_of(), """
  ctx.sessionStorage.setItem('color-map', JSON.stringify({setup: 'd1:l1', task: 'color', maxTime: 45, tolerance: ''}));
  tree = await screen();
  const right = tree.querySelector('.os-body').children[2];
  const [, L, A, B, tol] = right.querySelector('.cm-target').querySelectorAll('input');
  L.value = '62'; A.value = '-3.5'; B.value = '11'; tol.value = '2.5';
  await tol.dispatch('change');                                                  // a tolerance alone does not search before a colour is chosen
  out.searchedByTolerance = ctx.requests.filter((r) => r.path === '/api/colors/search').length;
  const before = ctx.requests.length;
  await byText(right, 'button', 'Найти').dispatch('click'); await tick(); await tick();
  out.search = ctx.requests.slice(before).filter((r) => r.path === '/api/colors/search').map((r) => r.url);
""")
    assert out["searchedByTolerance"] == 0 and len(out["search"]) == 1
    for part in ("L=62", "a=-3.5", "b=11", "limit=12", "setup=d1%3Al1", "task=color", "max_time_s_per_cm2=45", "tolerance_de=2.5"):
        assert part in out["search"][0], (part, out["search"][0])


# -- how far a colour is trusted and where it comes from (REQ-049) ----------------------------------------------------------------------------
def agree(n, k):
    return {"engravings": n, "agreeing": k, "differing": n - k, "limit": 5.0, "contradicted": 2 * k <= n}


def source(i, title, lab, agrees=True, delta=0.5, **extra):
    return {"engraving_id": f"e{i}", "experiment": f"eng-{i}", "title": title, "date": f"2026-10-1{i}T10:00:00", "pair_ids": [20 + i], "photos": [f"IMG_{i}.DNG"],
            "origin": "test" if i % 2 else "work", "work_id": None, "layers": ["C01"], "observation_ids": [i], "lab": lab, "delta_e": delta, "agrees": agrees,
            "measurement": "calibrated", "provisional": False, **extra}


TRUSTED = point(1, [80.0, 4.0, 30.0], group="g-three", trust=0.5, confidence=0.5, agreement=agree(3, 2), caution=None, doubtful=False)
ONCE = point(2, [55.0, 12.0, 20.0], group="g-once", trust=1 / 3, confidence=None, agreement=agree(1, 1), caution=None, doubtful=False)
DOUBT = point(3, [30.0, -2.0, -6.0], group="g-two", trust=1 / 6, confidence=1 / 6, agreement=agree(2, 1), caution="contradicted", doubtful=True)
RECIPES = {"g-three": {"lab": [80.5, 4.0, 30.0], "sources": [source(3, "Third try", [80.2, 4.0, 30.0]), source(2, "Second try", [80.8, 4.0, 30.0]),
                                                                 source(1, "First try", [60.0, 4.0, 30.0], agrees=False, delta=20.5)]},
           "g-two": {"lab": [30.0, -2.0, -6.0], "sources": [source(5, "Newer", [30.0, -2.0, -6.0]), source(4, "Older", [50.0, 9.0, 9.0], agrees=False, delta=27.0)]}}


@node
def test_the_filter_hides_the_doubtful_colours_and_the_next_questions_carry_it(tmp_path):
    world = colours([TRUSTED, ONCE, DOUBT])
    world["counts"]["doubtful"] = 1
    out = run(tmp_path, routes_of(world), """
  const left = () => tree.querySelector('.os-body').children[0];
  const box = () => left().querySelectorAll('label').find((l) => l.textContent.startsWith('Скрыть цвета, в которых не уверены')).querySelector('input');
  out.title = box().parentNode.getAttribute('title'); out.sub0 = tree.querySelector('.sub').textContent;
  box().checked = true; await box().dispatch('change'); tree = await screen();
  out.stored = JSON.parse(ctx.__store['color-map']).doubtful;
  out.checked = box().checked; out.sub1 = tree.querySelector('.sub').textContent;
  const before = ctx.requests.length;
  tree = await screen();
  out.map = ctx.requests.slice(before).filter((r) => r.path === '/api/colors').map((r) => r.url);
  const middle = tree.querySelector('.os-body').children[1];
  await middle.querySelectorAll('circle')[0].dispatch('click');
  await byText(middle.querySelectorAll('div').find((d) => has(d, 'cm-detail')), 'button', 'Найти такой же среди всех').dispatch('click'); await tick(); await tick();
  out.search = ctx.requests.filter((r) => r.path === '/api/colors/search').map((r) => r.url).pop();
  out.explained = tree.querySelector('details').textContent.includes('такие цвета помечены «сомнительный» и их можно скрыть');
""")
    assert "Кружок меньше, чем у гравировки, которую не повторяли" in out["title"]
    assert "сомнительных (кружок меньше, чем у одной гравировки) 1" in out["sub0"] and "скрыто" not in out["sub0"]
    assert out["stored"] is True and out["checked"] is True and "скрыто сомнительных (кружок меньше, чем у одной гравировки) 1" in out["sub1"]
    assert len(out["map"]) == 1 and "hide_doubtful=true" in out["map"][0] and "hide_doubtful=true" in out["search"] and out["explained"] is True


@node
def test_a_picked_colour_shows_its_confidence_and_every_engraving_it_is_known_from(tmp_path):
    world = colours([TRUSTED, ONCE, DOUBT])
    world["recipes"] = RECIPES
    out = run(tmp_path, routes_of(world), """
  const middle = tree.querySelector('.os-body').children[1];
  const detail = middle.querySelectorAll('div').find((d) => has(d, 'cm-detail'));
  const circles = middle.querySelectorAll('circle').filter((c) => c.getAttribute('stroke') !== '#ffd166');
  const pickByTitle = async (title) => { await circles.find((c) => c.querySelector('title').textContent.startsWith(title)).dispatch('click'); await tick(); };
  const read = () => ({text: detail.textContent, summary: detail.querySelector('summary').textContent, rows: detail.querySelectorAll('li').map((li) => li.textContent),
    links: detail.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]), pills: detail.querySelectorAll('.pill').map((p) => p.textContent),
    dot: detail.querySelectorAll('svg').map((v) => +v.querySelector('circle').getAttribute('r'))});
  await pickByTitle('Test 1'); out.three = read();
  await pickByTitle('Test 2'); out.once = read();
  await pickByTitle('Test 3'); out.doubt = read();
""")
    three = out["three"]
    assert "Уверенность: 0.50 (2 из 3 совпали)" in three["text"] and three["dot"] == [4.0]                    # the circle is the one the map draws
    assert three["summary"] == "Откуда мы знаем этот цвет: 3 независимые гравировки (2 теста, 1 работа)" and "Цвет настроек: " in three["text"] and "L 80.5 · a 4.0 · b 30.0" in three["text"]
    assert len(three["rows"]) == 3 and "Third try" in three["rows"][0] and "First try" in three["rows"][2] and "ΔE 20.5 от цвета настроек" in three["rows"][2]
    assert three["pills"].count("совпадает") == 2 and three["pills"].count("расходится") == 1 and "сомнительный" not in three["pills"]
    assert three["pills"].count("тест") == 2 and three["pills"].count("работа") == 1                      # every engraving says what it was (REQ-051)
    assert ["разбор №23", "#/analysis/23"] in three["links"] and ["эксперимент", "#/experiment/eng-1"] in three["links"] and "фото IMG_3.DNG" in three["rows"][0]
    assert "в пределах ΔE 5" in three["text"] and "повторное фото той же гравировки повтором не считается" in three["text"]
    once = out["once"]
    assert "Уверенность: не оценена, гравировка не повторялась" in once["text"] and once["summary"] == "Откуда мы знаем этот цвет: одна гравировка (тест)"
    assert len(once["rows"]) == 1 and "Test 2" in once["rows"][0] and "совпадает" not in once["pills"] and "Цвет настроек:" not in once["text"]
    doubt = out["doubt"]
    assert "Уверенность: 0.17 (1 из 2 совпали)" in doubt["text"] and "сомнительный" in doubt["pills"] and "цвет менялся при тех же настройках" in doubt["text"]
    assert doubt["dot"][0] == pytest.approx(4 / 1.5) and "Older" in doubt["rows"][1] and "ΔE 27.0 от цвета настроек" in doubt["rows"][1]


@node
def test_a_found_recipe_shows_the_same_confidence_and_sources_and_says_what_the_filter_left_out(tmp_path):
    match = {**SEARCH["matches"][0], **TRUSTED, "id": "p1", "distance": 0.4, "within_tolerance": True, "repeats": 3, "sources": RECIPES["g-three"]["sources"]}
    found = {**SEARCH, "matches": [match], "counts": {"unreferenced": 0, "provisional": 0, "slower": 0, "doubtful": 2}}
    routes = {"/api/colors": {"status": 200, "json": colours([TRUSTED])}, "/api/colors/search": {"status": 200, "json": found}}
    out = run(tmp_path, routes, """
  const [, middle, right] = tree.querySelector('.os-body').children;
  await middle.querySelectorAll('circle')[0].dispatch('click');
  await byText(middle.querySelectorAll('div').find((d) => has(d, 'cm-detail')), 'button', 'Найти такой же среди всех').dispatch('click'); await tick(); await tick();
  const list = right.children.find((c) => has(c, 'os-scroll'));
  const card = list.querySelectorAll('article')[0];
  out.card = card.textContent; out.summary = card.querySelector('summary').textContent; out.rows = card.querySelectorAll('li').length;
  out.once = list.querySelectorAll('.alert').map((a) => a.textContent);
  ctx.sessionStorage.setItem('color-map', JSON.stringify({doubtful: true, target: [80, 4, 30]}));
  tree = await screen();
  const list2 = tree.querySelector('.os-body').children[2].children.find((c) => has(c, 'os-scroll'));
  out.hidden = list2.querySelectorAll('.alert').map((a) => a.textContent);
  const show = byText(list2, 'button', 'Показать и их'); await show.dispatch('click');
  out.shown = JSON.parse(ctx.__store['color-map']).doubtful;
""")
    assert "Уверенность: 0.50 (2 из 3 совпали)" in out["card"] and "получался 3 раза" in out["card"] and out["card"].count("уверенность 0.50") == 0       # said once
    assert out["summary"] == "Откуда мы знаем этот цвет: 3 независимые гравировки (2 теста, 1 работа)" and out["rows"] == 3
    assert out["once"] == ["Среди найденных рецептов сомнительных (при повторах цвет менялся): 2; они помечены. "]
    assert out["hidden"] == ["2 рецептов с сомнительным цветом в поиске не участвуют: при повторах цвет менялся. Показать и их"] and out["shown"] is False


# -- the frame -----------------------------------------------------------------------------------------------------------------------------
def test_the_screen_is_one_screen_frame_and_only_the_found_recipes_scroll():
    assert ("h('div', {class: 'os cm' + (pick ? ' cm-picking' : '')}, head, pick ? DotPick.banner(pick) : null, "
            "h('div', {class: 'os-body cm-body'}, filters, mapCol, search))") in SCREEN               # picking a work's dots: a strip under the head
    assert "h('details', {class: 'cm-about'}, h('summary', {}, 'Как это считается')" in SCREEN and "h('div', {class: 'os-scroll'}, results)" in SCREEN
    assert "svg.style.cssText = 'width:100%;height:100%;cursor:grab;touch-action:none;outline:none';" in SCREEN and "max-width:820px" not in SCREEN       # the box around the map sets its size
    section = CSS[CSS.index("/* === cm:"):CSS.index("/* === end cm === */")]
    assert re.search(r"\.cm-body \{grid-template-columns:minmax\(250px,290px\) minmax\(0,1fr\) minmax\(280px,340px\)\}", section)       # three columns
    assert re.search(r"\.cm-plot \{flex:1;min-height:0;display:flex", section) and re.search(r"\.cm-detail \{flex:none;max-height:40%;overflow:auto", section)
    assert re.search(r"\.cm-target \{[^}]*flex:none", section) and re.search(r"\.cm-lab \{display:grid;grid-template-columns:repeat\(3,minmax\(0,1fr\)\)", section)
    narrow = re.search(r"@media \(max-width:1100px\) \{(.*?)\n\}", section, re.S)
    assert narrow and ".cm-plot {flex:none;height:62vh}" in narrow.group(1)                                # a phone: the map has its own height, the page scrolls


@node
def test_the_diameter_of_a_circle_grows_one_and_a_half_times_per_agreeing_repeat_and_shrinks_per_differing_one(tmp_path):
    """REQ-045, DEC-084: radius 4 for a setting engraved once, times 1.5 for every agreeing repeat, divided by 1.5 for every differing engraving,
    held between 2 and 14; the title of a circle says the confidence and how many engravings agree."""
    def agree(n, k):
        return {"engravings": n, "agreeing": k, "differing": n - k}
    pts = [point(1, [80.0, 4.0, 30.0], trust=1 / 6, confidence=1 / 6, agreement=agree(2, 1)),        # 1 of 2: 4 / 1.5
           point(2, [60.0, 6.0, 20.0], trust=1 / 3, confidence=None, agreement=agree(1, 1)),          # once: 4
           point(3, [50.0, 8.0, 10.0], trust=0.6, confidence=0.6, agreement=agree(3, 3)),             # 3 agree: 4 * 1.5 * 1.5
           point(4, [40.0, 2.0, 5.0], trust=0.83, confidence=0.83, agreement=agree(10, 10)),          # 10 agree: held at 14
           point(5, [30.0, 1.0, 3.0], trust=0.05, confidence=0.05, agreement=agree(4, 1)),            # 1 of 4: 4 / 1.5^3 held at 2
           point(6, [20.0, 3.0, 7.0], trust=0.5, confidence=0.5, agreement=agree(3, 2))]              # 2 of 3: 4 * 1.5 / 1.5
    out = run(tmp_path, routes_of(colours(pts)), """
  const circles = tree.querySelectorAll('circle').filter((c) => c.getAttribute('stroke') !== '#ffd166');
  out.radii = circles.map((c) => +c.getAttribute('r'));
  out.titles = circles.map((c) => c.querySelector('title').textContent);
""")
    assert out["radii"] == sorted(out["radii"], reverse=True)          # the larger circles are drawn first: none hides a smaller one
    by_title = {t.split(" · ")[0]: r for t, r in zip(out["titles"], out["radii"])}
    assert by_title["Test 2"] == 4
    assert by_title["Test 1"] == pytest.approx(4 / 1.5) and by_title["Test 3"] == pytest.approx(9)
    assert by_title["Test 4"] == 14 and by_title["Test 5"] == 2 and by_title["Test 6"] == pytest.approx(4)
    titles = " ".join(out["titles"])
    assert "уверенность не оценена (одна гравировка)" in titles and "уверенность 0.60 (все 3 совпали)" in titles and "уверенность 0.17 (1 из 2 совпали)" in titles
    assert "каждый повтор с тем же цветом увеличивает его в 1,5 раза" in SCREEN


# -- zoom and pan of the map -------------------------------------------------------------------------------------------------------------------
@node
def test_the_view_math_keeps_the_point_under_the_cursor_and_stays_inside_the_picture(tmp_path):
    out = run(tmp_path, routes_of(), """
  const {zoomView, panView, clampView} = ctx.ColorMap;
  const v0 = {s: 1, tx: 0, ty: 0};
  out.zoom = zoomView(v0, 2, 100, 50, 640, 460);
  out.fixedPoint = [out.zoom.s * 100 + out.zoom.tx, out.zoom.s * 50 + out.zoom.ty];        // the point under the cursor does not move
  out.most = zoomView(v0, 1e6, 10, 10, 640, 460).s;
  out.least = zoomView({s: 2, tx: -100, ty: -50}, 1e-6, 10, 10, 640, 460);
  out.panFull = panView(v0, 300, 300, 640, 460);                                           // the whole picture cannot be moved away
  out.panZoomed = panView({s: 2, tx: -100, ty: -50}, -1000, 1000, 640, 460);
  out.clamp = clampView({s: 3, tx: 50, ty: -9999}, 640, 460);
""")
    assert out["zoom"] == {"s": 2, "tx": -100, "ty": -50} and out["fixedPoint"] == [100, 50]
    assert out["most"] == 60 and out["least"] == {"s": 1, "tx": 0, "ty": 0} and out["panFull"] == {"s": 1, "tx": 0, "ty": 0}
    assert out["panZoomed"] == {"s": 2, "tx": -640, "ty": 0} and out["clamp"] == {"s": 3, "tx": 0, "ty": -920}


@node
def test_the_wheel_zooms_a_drag_moves_the_map_circles_keep_their_size_and_a_pick_keeps_the_view(tmp_path):
    pts = [point(1, [80.0, 4.0, 30.0]), point(2, [55.0, 12.0, 20.0], agreement={"engravings": 3, "agreeing": 3, "differing": 0}), point(3, [30.0, -2.0, -6.0])]
    out = run(tmp_path, routes_of(colours(pts)), """
  const svg = () => tree.querySelector('svg');
  const view = () => { const m = svg().querySelector('g').getAttribute('transform').match(/-?[0-9]+[.]?[0-9]*(?:e-?[0-9]+)?/g); return m ? m.map(Number) : null; };
  const radii = () => svg().querySelectorAll('circle').filter((c) => c.getAttribute('stroke') !== '#ffd166').map((c) => +c.getAttribute('r'));
  out.start = view(); out.r0 = radii();
  await svg().dispatch('wheel', {clientX: 50, clientY: 50, deltaX: 0, deltaY: -460});       // one notch of a mouse wheel is about 100; this is a few
  out.zoomed = view(); out.r1 = radii();
  await svg().dispatch('pointerdown', {clientX: 40, clientY: 40});
  await svg().dispatch('pointermove', {clientX: 41, clientY: 40});                           // inside the click tolerance: nothing moves
  out.small = view();
  await svg().dispatch('pointermove', {clientX: 60, clientY: 40});
  await svg().dispatch('pointerup', {clientX: 60, clientY: 40});
  out.dragged = view();
  await svg().dispatch('wheel', {clientX: 50, clientY: 50, deltaX: 80, deltaY: 0});          // sideways: the map moves, the scale stays
  out.sideways = view();
  const bar = tree.querySelector('.cm-zoombar');
  out.scaleText = bar.querySelector('.cm-scale').textContent;
  await byText(bar, 'button', '+').dispatch('click');
  out.plus = view();
  await byText(bar, 'button', '−').dispatch('click');
  out.minus = view();
  // a colour is picked: the map is drawn again, and the view is kept
  await svg().querySelectorAll('circle')[0].dispatch('click');
  await tick();
  out.afterPick = view();
  await byText(tree.querySelector('.cm-zoombar'), 'button', 'Весь вид').dispatch('click');
  out.reset = view(); out.r2 = radii();
  await svg().dispatch('keydown', {key: '+'});
  out.key = view();
  await svg().dispatch('keydown', {key: '0'});
  out.keyReset = view();
""")
    assert out["start"] == [0, 0, 1] and out["r0"] == sorted(out["r0"], reverse=True)
    s = out["zoomed"][2]
    assert out["zoomed"][2] > 1.5 and out["zoomed"][0] < 0 and out["zoomed"][1] < 0                       # zoomed about the middle of the box
    assert [round(r * s, 6) for r in out["r1"]] == [round(r, 6) for r in out["r0"]]                      # a circle keeps its size on the screen: its diameter tells the confidence
    assert out["small"] == out["zoomed"] and out["dragged"][0] > out["zoomed"][0] and out["dragged"][1] == out["zoomed"][1] and out["dragged"][2] == s
    assert out["sideways"][0] < out["dragged"][0] and out["sideways"][2] == s
    assert out["scaleText"].startswith("×")
    assert out["plus"][2] == pytest.approx(s * 1.5) and out["minus"][2] == pytest.approx(s)
    assert out["afterPick"][2] == pytest.approx(s)                                                       # picking a colour does not throw the view away
    assert out["reset"] == [0, 0, 1] and out["r2"][1:] == out["r0"][1:] and out["r2"][0] == out["r0"][0] + 3          # only the picked circle is larger
    assert out["key"][2] == 1.5 and out["keyReset"] == [0, 0, 1]
    assert "touch-action:none" in SCREEN and "{passive: false}" in SCREEN


# -- the colour of a photo work's dots picked on the map (0.25.0, DEC-118) ----------------------------------------------------------------
def picking():
    fill = {"power": 20, "frequency": 60, "speed": 500, "pulse_width": 300, "line_interval": 0.02, "passes": 1}
    world = colours([point(1, [50.0, 12.0, -25.0], group="g-fill", parameters=fill),
                     point(2, [60.0, 5.0, 25.0], group="g-step", parameters={**fill, "speed": 600, "line_interval": 0.005}),
                     point(3, [45.0, 10.0, 20.0], group="g-tone", source="tonal", parameters={**fill, "power": 12.5, "speed": 150, "line_interval": 0.0212})])
    world["options"]["setups"] = [{"key": "laser:1/lens:2", "label": "JPT M7 · F-Theta 174", "device_id": 1, "lens_id": 2}]
    world["dots"] = {"work": {"id": 37, "name": "Inna Portrait 2", "kind": "atkinson", "width_mm": 100, "device_id": 1, "lens_id": 2,
                              "material": {"grade": "Grade 5"}, "dot_recipe": None},
                     "step_min_mm": 0.0085, "setup": "laser:1/lens:2", "reasons": {"step": "its step is finer than 0.0085 mm: there the dots merge"},
                     "groups": {"g-fill": {"fill": True}, "g-step": {"reason": "step"}, "g-tone": {"scale": {"speed": 150}, "power": 12.5}}}
    return {**routes_of(world), "/api/photo-works/37/settings": {"status": 200, "json": {}}}


@node
def test_the_map_picks_the_colour_of_a_photo_works_dots_and_says_why_a_colour_cannot_be_them(tmp_path):
    out = run(tmp_path, picking(), """
  ctx.sessionStorage.setItem('color-map', JSON.stringify({setup: 'laser:9/lens:9'}));
  const before = ctx.requests.length;
  tree = await ctx.ColorMap.render({query: {dots: '37', setup: 'laser:1/lens:2'}}); await tick(); await tick();
  out.asked = ctx.requests.slice(before).filter((r) => r.path === '/api/colors').map((r) => r.url);
  out.root = tree.className;
  out.banner = tree.querySelector('.dp-banner').textContent;
  out.back = tree.querySelector('.dp-banner').querySelector('a').getAttribute('href');
  const filters = tree.querySelector('.os-body').children[0];
  out.setup = filters.querySelectorAll('div').filter((d) => has(d, 'f')).map((d) => d.textContent);
  out.selects = filters.querySelectorAll('select').length;
  const circle = (name) => tree.querySelectorAll('circle').find((c) => c.querySelector('title') && c.querySelector('title').textContent.startsWith(name + ' ·'));
  out.pale = ['Test 1', 'Test 2', 'Test 3'].map((n) => circle(n).getAttribute('fill-opacity'));
  const detail = () => tree.querySelectorAll('div').find((d) => has(d, 'cm-detail'));
  const action = () => detail().querySelector('.dp-action');
  await circle('Test 2').dispatch('click'); await tick();
  out.step = action().textContent;
  await circle('Test 3').dispatch('click'); await tick();
  out.tone = action().textContent;
  await circle('Test 1').dispatch('click'); await tick();
  out.fill = action().textContent;
  out.under = detail().children.findIndex((c) => has(c, 'dp-action'));
  await byText(action(), 'button', 'Точки этим цветом').dispatch('click'); await tick(); await tick();
  out.saved = ctx.requests.filter((r) => r.path === '/api/photo-works/37/settings').map((r) => [r.method, JSON.parse(r.body)]);
  out.went = [...ctx.__went]; out.toasts = ctx.__toasts;
""")
    assert out["asked"] == ["/api/colors?dots=37&setup=laser%3A1%2Flens%3A2"] and out["root"] == "os cm cm-picking"
    assert out["banner"].startswith("Цвет точек для работы «Inna Portrait 2» · Аткинсон · 100 мм") and "на титане Grade 5" in out["banner"]
    assert "с шагом строк от 0,0085 мм" in out["banner"] and out["back"] == "#/photo-engraving?work=37"
    assert out["setup"] == ["Лазер и линзаJPT M7 · F-Theta 174"] and out["selects"] == 3            # the work's laser and lens, not a choice
    assert out["pale"] == ["1", "0.18", "1"]                                                          # what cannot be the dots is pale
    assert out["step"] == "Для точек этот цвет не подходит: шаг строк мельче 0,0085 мм: при таком шаге точки слипаются."            # the server's reason
    assert out["tone"] == "Точки этим цветомТочки встанут на эту шкалу серого при 12,5 %: 150 мм/с · 60 кГц · 300 нс · шаг 0,0212 мм."
    assert out["fill"] == "Точки этим цветомТочки будут бить на настройках этой заливки: 20 % · 500 мм/с · 60 кГц · 300 нс · шаг 0,02 мм; шаг строк станет шагом точек."
    assert out["under"] == 2                                                                          # right under the picked colour
    assert out["saved"] == [["POST", {"dot_colour": "g-fill"}]] and out["went"] == ["/photo-engraving?work=37"]
    assert out["toasts"] == ["Цвет точек выбран: работа покажет точки этим цветом"]


@node
@pytest.mark.parametrize("opened", [None, "editor"])
def test_the_map_picks_the_colour_of_a_photo_zones_dots_and_goes_back_where_it_was_opened(tmp_path, opened):
    routes = picking()
    world = routes["/api/colors"]["json"]
    world["dots"]["work"] = {**world["dots"]["work"], "id": 41, "name": "Яня портрет - 1", "zone": 2, "kind": "jarvis", "width_mm": 150}
    routes["/api/vector/41/photo/2/settings"] = {"status": 200, "json": {}}
    query = {"dots": "41", "zone": "2", "setup": "laser:1/lens:2", **({"from": opened} if opened else {})}
    out = run(tmp_path, routes, f"""
  const before = ctx.requests.length;
  tree = await ctx.ColorMap.render({{query: {json.dumps(query)}}}); await tick(); await tick();
  out.asked = ctx.requests.slice(before).filter((r) => r.path === '/api/colors').map((r) => r.url);
  const banner = tree.querySelector('.dp-banner');
  out.banner = banner.querySelector('strong').textContent;
  out.back = [banner.querySelector('a').getAttribute('href'), banner.querySelector('a').textContent];
  const circle = tree.querySelectorAll('circle').find((c) => c.querySelector('title') && c.querySelector('title').textContent.startsWith('Test 1 ·'));
  await circle.dispatch('click'); await tick();
  const action = tree.querySelectorAll('div').find((d) => has(d, 'cm-detail')).querySelector('.dp-action');
  await byText(action, 'button', 'Точки этим цветом').dispatch('click'); await tick(); await tick();
  out.saved = ctx.requests.filter((r) => r.method === 'POST').map((r) => [r.path, JSON.parse(r.body)]);
  out.went = [...ctx.__went]; out.toasts = ctx.__toasts;
""")
    back = "/vector?plan=41" if opened else "/vector-zone?work=41&zone=2"
    assert out["asked"] == ["/api/colors?dots=41&zone=2&setup=laser%3A1%2Flens%3A2"]
    assert out["banner"] == "Цвет точек для фотозоны 2 работы «Яня портрет - 1» · Джарвис · 150 мм"
    assert out["back"] == [f"#{back}", "← К работе без изменений" if opened else "← К зоне без изменений"]
    assert out["saved"] == [["/api/vector/41/photo/2/settings", {"dot_colour": "g-fill"}]] and out["went"] == [back]
    assert out["toasts"] == ["Цвет точек выбран: зона покажет точки этим цветом"]
