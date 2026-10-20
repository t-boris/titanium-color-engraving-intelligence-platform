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
        "globalThis.sessionStorage = {getItem: (k) => (k in __store ? __store[k] : null), setItem: (k, v) => { __store[k] = String(v); }, removeItem: (k) => { delete __store[k]; }};"
        "globalThis.__store = __store; const __svg = document.createElementNS, __html = document.createElement; document.createElementNS = (ns, t) => { const e = __svg(ns, t); e.style = {}; return e; };"
        "document.createElement = (t) => { const e = __html(t); e.style = {}; return e; };")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'hardware.js', 'tasks.js', {code: %(glue)s}, 'screens/color-map.js', {code: 'globalThis.ColorMap = ColorMap;'}]);
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
            "measurement": "calibrated", "approximate": False, "pair_id": 10 + i, "experiment": f"eng-{i}", "source": "color", "task": None, "review": None,
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
    assert out["middleTitle"] == "Карта цветов" and out["planes"] == ["a* × b*", "a* × L*", "b* × L*"]
    assert out["plot"] == [["svg"]] and out["circles"] == 3 and out["detailInMiddle"] is True              # the picked colour is described under the map
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


# -- the frame -----------------------------------------------------------------------------------------------------------------------------
def test_the_screen_is_one_screen_frame_and_only_the_found_recipes_scroll():
    assert "h('div', {class: 'os cm'}, head, h('div', {class: 'os-body cm-body'}, filters, mapCol, search))" in SCREEN
    assert "h('details', {class: 'cm-about'}, h('summary', {}, 'Как это считается')" in SCREEN and "h('div', {class: 'os-scroll'}, results)" in SCREEN
    assert "svg.style.cssText = 'width:100%;height:100%';" in SCREEN and "max-width:820px" not in SCREEN       # the box around the map sets its size
    section = CSS[CSS.index("/* === cm:"):CSS.index("/* === end cm === */")]
    assert re.search(r"\.cm-body \{grid-template-columns:minmax\(250px,290px\) minmax\(0,1fr\) minmax\(280px,340px\)\}", section)       # three columns
    assert re.search(r"\.cm-plot \{flex:1;min-height:0;display:flex", section) and re.search(r"\.cm-detail \{flex:none;max-height:40%;overflow:auto", section)
    assert re.search(r"\.cm-target \{[^}]*flex:none", section) and re.search(r"\.cm-lab \{display:grid;grid-template-columns:repeat\(3,minmax\(0,1fr\)\)", section)
    narrow = re.search(r"@media \(max-width:1100px\) \{(.*?)\n\}", section, re.S)
    assert narrow and ".cm-plot {flex:none;height:62vh}" in narrow.group(1)                                # a phone: the map has its own height, the page scrolls


@node
def test_the_diameter_of_a_circle_follows_the_confidence_in_the_colour_of_its_settings(tmp_path):
    """REQ-045: a recipe engraved once is small, one whose repeats agree is larger the more they are, one whose colour changed is the smallest;
    the title of a circle says the confidence and how many engravings agree."""
    pts = [point(1, [80.0, 4.0, 30.0], trust=1 / 6, confidence=1 / 6, agreement={"engravings": 2, "agreeing": 1, "differing": 1}),
           point(2, [60.0, 6.0, 20.0], trust=1 / 3, confidence=None, agreement={"engravings": 1, "agreeing": 1, "differing": 0}),
           point(3, [50.0, 8.0, 10.0], trust=0.6, confidence=0.6, agreement={"engravings": 3, "agreeing": 3, "differing": 0}),
           point(4, [40.0, 2.0, 5.0], trust=0.83, confidence=0.83, agreement={"engravings": 10, "agreeing": 10, "differing": 0})]
    out = run(tmp_path, routes_of(colours(pts)), """
  const circles = tree.querySelectorAll('circle').filter((c) => c.getAttribute('stroke') !== '#ffd166');
  out.radii = circles.map((c) => +c.getAttribute('r'));
  out.titles = circles.map((c) => c.querySelector('title').textContent);
""")
    assert out["radii"] == sorted(out["radii"], reverse=True) or out["radii"] == sorted(out["radii"])
    assert len(set(out["radii"])) == 4 and max(out["radii"]) - min(out["radii"]) > 5
    by_title = {t.split(" · ")[0]: r for t, r in zip(out["titles"], out["radii"])}
    assert by_title["Test 1"] < by_title["Test 2"] < by_title["Test 3"] < by_title["Test 4"]
    titles = " ".join(out["titles"])
    assert "уверенность не оценена (одна гравировка)" in titles and "уверенность 0.60 (все 3 совпали)" in titles and "уверенность 0.17 (1 из 2 совпали)" in titles
    assert "Диаметр кружка" in SCREEN
