"""The page of one experiment on one screen without a scrolling page (REQ-044, DEC-080): the photograph with its overlay on the left, the
tabs of the result, matrix, checks, plate, work and conclusions on the right. Run in node over the small DOM of the other screen tests, with
the answers of the experiment API shaped as the server sends them."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
CSS = (UI / "styles.css").read_text(encoding="utf-8")
SCRIPTS = ["app.js", "dialogs.js", "hardware.js", "tasks.js", "screens/ingest-upload.js", "screens/ingest-dialogs.js", "screens/ingest-tasks.js", "screens/ingest-review.js"]
GLUE = ("const __screens = {}; App.register = (d) => { __screens[d.id] = d; }; App.render = () => { globalThis.__renders = (globalThis.__renders || 0) + 1; };"
        "App.go = (route) => { location.hash = '#' + route; };"
        "const __local = {}, __session = {};"
        "globalThis.localStorage = {getItem: (k) => (k in __local ? __local[k] : null), setItem: (k, v) => { __local[k] = String(v); }};"
        "globalThis.sessionStorage = {getItem: (k) => (k in __session ? __session[k] : null), setItem: (k, v) => { __session[k] = String(v); }};"
        "globalThis.__screens = __screens; globalThis.__local = __local; globalThis.__session = __session;")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, ...%(scripts)s, {code: %(glue)s}, 'screens/experiment.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const has = (el, cls) => (el.className || '').split(' ').includes(cls);
const tabButtons = (tree) => tree.querySelectorAll('button').filter((b) => b.getAttribute('role') === 'tab' && b.getAttribute('id').startsWith('ep-tab-'));
const shownPanels = (tree) => tree.querySelectorAll('div').filter((d) => d.getAttribute('role') === 'tabpanel' && d.getAttribute('id').startsWith('ep-tab-panel-') && !d.hidden).map((d) => d.getAttribute('id'));
(async () => {
  const out = {};
  const screen = async (key) => { const t = await ctx.__screens.experiment.render({arg: key, query: {}}); for (let i = 0; i < 6; i++) await tick(); return t; };
  const tree = await screen(data.key);
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, routes, key, body):
    (tmp_path / "data.json").write_text(json.dumps({"key": key, "routes": routes}), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "scripts": json.dumps(SCRIPTS), "glue": json.dumps(GLUE), "body": body},
                      encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout)


# -- answers shaped as the server sends them ------------------------------------------------------------------------------------------
def pair_summary(pid, status="Accepted", alignment="material test grid", name="IMG_1.DNG", **more):
    return {"id": pid, "status": status, "photo_name": name, "lightburn_name": f"work-{pid}.lbrn2", "created_at": "2026-10-18T17:56:06+00:00",
            "accepted_at": "2026-10-18T17:58:39+00:00" if status == "Accepted" else None, "alignment": alignment, "problems": [], "measured_layers": 2,
            "observations": 2, "measurement": "reference_chart_corrected", "lightburn_url": f"/api/pairs/{pid}/lightburn", "grayscale_image": False, **more}


def layer(index, lab, name):
    return {"index": index, "name": name, "power": 40.0, "frequency_khz": 1950.0, "speed": 1800.0, "pulse_width": 10.0, "line_interval": 0.003, "passes": 1,
            "measured_lab": lab, "notes": [], "task": {"kind": "fill", "basis": "derived", "source": "layer", "mode": "Scan"},
            "metrics": [{"metric": "lab", "value": lab, "unit": "Lab", "method": "layer_mask_median", "basis": "chart", "available": True}]}


def pair_detail(pid, matrix=False, layers=2):
    labs = [[47.5 - i, 14.0 + i, -14.0 - i] for i in range(layers)]
    out = {"id": pid, "status": "Accepted", "check": {"layers": [layer(i, labs[i], f"Power 40 x Q-Pulse {10 - i}.00") for i in range(layers)], "problems": [],
                                                     "warnings": ["The overlay is approximate"]}}
    out["matrix"] = ({"cols": 1, "rows": layers, "confirmed": True, "spec": {"x": {"param": "power", "values": [40], "decimals": 0},
                                                                              "y": {"param": "pulse_width", "values": list(range(layers, 0, -1)), "decimals": 2}}}
                     if matrix else None)
    return out


def experiment(key, **over):
    base = {"key": key, "title": "Тест материала", "status": "accepted", "status_text": "Принят", "kind": "Матрица параметров", "plan_id": None,
            "engraving_id": "abc", "device_id": 1, "lens_id": 2, "main_pair_id": None, "created_at": "2026-10-18T17:56:06+00:00", "tasks": ["fill"],
            "laser": "JPT YDFLP", "lens": "F-Theta", "material": "Big Plate 150 · Grade 5", "plate": None, "pairs": [], "findings": []}
    return {**base, **over}


def api(**routes) -> dict:
    return {path: {"status": 200, "json": data} for path, data in routes.items()}


MATRIX = experiment("eng-abc", main_pair_id=59, pairs=[pair_summary(59, name="IMG_3305.DNG")])
WORK = experiment("eng-work", kind="Готовая работа", main_pair_id=51, pairs=[pair_summary(51, alignment="picture", name="IMG_3296.DNG", grayscale_image=True)])
PLATE = experiment("plan-22", status="plate_ready", status_text="Плата готова: ждёт фото", kind="Векторная работа", plan_id=22, engraving_id=None,
                   plate={"plan_id": 22, "name": "Imma + Boris", "mode": "Vector job", "status": "Ready to export", "test_name": "Векторная работа", "description": "Описание платы",
                          "layers": 16, "band_count": None, "identifier": "TCE-A-22", "proposal": {"id": 3, "device_id": 1, "lens_id": 2},
                          "engraving_task": {"kind": "color_image", "goals": {}, "basis": "explicit"}})
BOTH = experiment("plan-5", status="needs_review", status_text="Нужна проверка", kind="Тест возможностей лазера", plan_id=5, engraving_id=None, main_pair_id=70,
                  plate={"plan_id": 5, "name": "Плата 5", "mode": "Laser capability test", "test_name": "Тест", "layers": 9, "identifier": "TCE-A-5", "proposal": None},
                  pairs=[pair_summary(70, status="Needs correction", name="IMG_70.DNG"), pair_summary(71, name="IMG_71.DNG")],
                  findings=[{"purpose": "color", "status": "candidate", "summary": "Цвет найден", "next_test": "Повторить", "history": [
                      {"valid_from": "2026-10-18T10:00:00+00:00", "replaced_at": "2026-10-19T10:00:00+00:00", "summary": "Прежний вывод"}]}])


def routes_for(*experiments) -> dict:
    routes = {f"/api/experiments/{e['key']}": {"status": 200, "json": e} for e in experiments}
    routes.update(api(**{"/api/pairs/59": pair_detail(59, matrix=True, layers=10), "/api/pairs/51": pair_detail(51), "/api/pairs/70": pair_detail(70),
                         "/api/pairs/71": pair_detail(71, matrix=True)}))
    routes.update({f"/api/pairs/{n}": {"status": 200, "json": {}} for n in ()})
    return routes


# -- the page --------------------------------------------------------------------------------------------------------------------------
@node
def test_an_experiment_with_a_matrix_is_one_screen_with_the_photo_on_the_left_and_tabs_of_result_matrix_checks_and_work_on_the_right(tmp_path):
    out = run(tmp_path, routes_for(MATRIX), "eng-abc", """
  out.root = tree.className;
  out.head = tree.querySelectorAll('header')[0].textContent;
  out.back = tree.querySelectorAll('a').find((a) => a.textContent === '← Эксперименты').getAttribute('href');
  out.addPhoto = tree.querySelectorAll('a').find((a) => a.textContent === 'Добавить фото').getAttribute('href');
  out.tabs = tabButtons(tree).map((b) => [b.textContent, b.hidden]);
  out.shown = shownPanels(tree);
  const photo = tree.querySelectorAll('section').find((s) => has(s, 'ep-photo-col'));
  out.photoTools = photo.querySelectorAll('button').map((b) => b.textContent);
  out.legend = photo.querySelectorAll('summary').map((s) => s.textContent);
  out.img = photo.querySelector('img').getAttribute('src');
  out.full = photo.querySelector('a').getAttribute('href');
  out.caption = photo.querySelectorAll('p').map((p) => p.textContent).find((t) => t.startsWith('IMG_3305.DNG'));
  const side = tree.querySelectorAll('aside').find((s) => has(s, 'ep-side'));
  out.layers = side.querySelectorAll('div').filter((d) => has(d, 'ep-layer')).length;
  out.layersHeading = side.querySelectorAll('h3').map((h) => h.textContent);
  out.alerts = side.querySelectorAll('div').filter((d) => has(d, 'alert')).map((d) => d.textContent);
""")
    assert out["root"] == "os experiment" and "Тест материала" in out["head"] and "Принят" in out["head"] and "Заливка" in out["head"]   # task pill beside the title
    assert out["back"] == "#/experiments" and out["addPhoto"] == "#/ingest?rephoto=59"
    assert out["tabs"] == [["Результат", False], ["Матрица", False], ["Проверки (1)", False], ["Работа", False]] and out["shown"] == ["ep-tab-panel-result"]
    assert out["photoTools"] == ["Скрыть контуры", "Поднять яркость"] and out["legend"] == ["Что означают линии"]
    assert out["img"].startswith("/api/pairs/59/overlay.png?corrected=true&visibility=normal&full=false") and "full=true" in out["full"]     # overlay first, the corrected photograph as it is
    assert "проверка №59" in out["caption"] and "цвет по эталонной карте" in out["caption"]
    assert out["layers"] == 10 and out["layersHeading"][0] == "Измеренные слои · 10" and "Матрица параметров 1 × 10" in out["layersHeading"]
    assert len(out["alerts"]) == 1


@node
def test_the_tabs_switch_panels_remember_the_open_one_and_the_matrix_tab_is_hidden_when_the_check_has_none(tmp_path):
    out = run(tmp_path, routes_for(MATRIX, WORK), "eng-abc", """
  out.first = shownPanels(tree);
  await byText(tree, 'button', 'Матрица').dispatch('click');
  out.afterClick = shownPanels(tree); out.saved = ctx.__local['ep.tab'];
  const again = await screen('eng-abc');
  out.restored = shownPanels(again);
  const work = await screen('eng-work');
  out.workTabs = tabButtons(work).map((b) => [b.textContent, b.hidden]);
  out.workShown = shownPanels(work);                     // the remembered matrix tab is gone with the matrix: the result is shown
  const list = work.querySelectorAll('div').find((d) => d.getAttribute('role') === 'tablist');
  await list.dispatch('keydown', {key: 'ArrowRight'});
  out.workArrow = shownPanels(work);                     // the arrow skips the hidden matrix tab
""")
    assert out["first"] == ["ep-tab-panel-result"] and out["afterClick"] == ["ep-tab-panel-matrix"] and out["saved"] == "matrix" and out["restored"] == ["ep-tab-panel-matrix"]
    assert out["workTabs"] == [["Результат", False], ["Матрица", True], ["Проверки (1)", False], ["Работа", False]] and out["workShown"] == ["ep-tab-panel-result"]
    assert out["workArrow"] == ["ep-tab-panel-checks"]


@node
def test_the_overlay_and_brightness_buttons_redraw_the_photo_and_are_remembered_for_the_session(tmp_path):
    out = run(tmp_path, routes_for(MATRIX), "eng-abc", """
  const photo = tree.querySelectorAll('section').find((s) => has(s, 'ep-photo-col'));
  await byText(photo, 'button', 'Скрыть контуры').dispatch('click'); await tick();
  out.noContours = photo.querySelector('img').getAttribute('src'); out.stored = ctx.__session['experiment-contours'];
  await byText(photo, 'button', 'Поднять яркость').dispatch('click'); await tick();
  out.normal = photo.querySelector('img').getAttribute('src'); out.light = ctx.__session['experiment-lifted'];
  out.buttons = photo.querySelectorAll('button').map((b) => b.textContent);
""")
    assert out["noContours"].startswith("/api/pairs/59/photo.png?corrected=true&visibility=normal") and out["stored"] == "0"
    assert "visibility=lifted" in out["normal"] and out["light"] == "1" and out["buttons"] == ["Показать контуры", "Обычная яркость"]


@node
def test_a_plate_without_photos_shows_its_picture_slot_the_plate_and_its_actions_and_nothing_else(tmp_path):
    out = run(tmp_path, routes_for(PLATE), "plan-22", """
  out.tabs = tabButtons(tree).map((b) => b.textContent); out.shown = shownPanels(tree);
  const photo = tree.querySelectorAll('section').find((s) => has(s, 'ep-photo-col'));
  out.nophoto = photo.textContent; out.nophotoLink = photo.querySelectorAll('a').map((a) => a.getAttribute('href'));
  const side = tree.querySelectorAll('aside').find((s) => has(s, 'ep-side'));
  out.plate = side.textContent;
  out.links = side.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
  out.head = tree.querySelectorAll('a').filter((a) => a.textContent === 'Добавить фото').map((a) => a.getAttribute('href'));
""")
    assert out["tabs"] == ["Плата"] and out["shown"] == ["ep-tab-panel-plate"]
    assert "Фото ещё нет" in out["nophoto"] and out["nophotoLink"] == ["#/ingest?plan=22"]
    assert out["head"] == ["#/ingest?plan=22", "#/ingest?plan=22"]                                  # the title row and the empty picture slot both offer it
    assert "Imma + Boris" in out["plate"] and "Описание платы" in out["plate"] and "16 слоёв" in out["plate"] and "Задача:" in out["plate"]
    links = dict((text, href) for text, href in out["links"])
    assert links["Открыть и изменить плату"] == "#/plans/22" and links["Скачать .lbrn2"] == "/api/plans/22/export.lbrn2"
    assert links["Попросить AI-исследователя изменить плату"] == "#/research" and links["предложению планировщика № 3"].startswith("#/designer?device=1&lens=")


@node
def test_checks_conclusions_and_the_two_deletions_keep_their_actions(tmp_path):
    routes = routes_for(BOTH)
    routes.update(api(**{"/api/pairs/70": pair_detail(70), "/api/pairs/71": pair_detail(71, matrix=True)}))
    for path in ("/api/pairs/70", "/api/pairs/71", "/api/plans/5"):
        routes[path + "#delete"] = routes.get(path, {"status": 200, "json": {}})
    out = run(tmp_path, routes, "plan-5", """
  out.tabs = tabButtons(tree).map((b) => b.textContent); out.shown = shownPanels(tree);
  const side = tree.querySelectorAll('aside').find((s) => has(s, 'ep-side'));
  await byText(side, 'button', 'Проверки (2)').dispatch('click');
  const rows = side.querySelectorAll('div').filter((d) => has(d, 'ep-check'));
  out.checks = rows.map((r) => [r.textContent, has(r, 'is-current')]);
  out.links = side.querySelectorAll('a').filter((a) => ['Разбор', 'Проверить и принять'].includes(a.textContent)).map((a) => [a.textContent, a.getAttribute('href')]);
  const photo = tree.querySelectorAll('section').find((s) => has(s, 'ep-photo-col'));
  out.before = photo.querySelector('img').getAttribute('src').split('?')[0];
  await byText(side, 'button', 'Проверка №71').dispatch('click'); await tick();
  out.after = photo.querySelector('img').getAttribute('src').split('?')[0];
  out.current = side.querySelectorAll('div').filter((d) => has(d, 'is-current')).map((d) => d.textContent.slice(0, 12));
  await byText(side, 'button', 'Выводы (1)').dispatch('click');
  out.findings = side.querySelectorAll('div').filter((d) => d.getAttribute('role') === 'tabpanel' && !d.hidden).map((d) => d.textContent)[0];
  await byText(tree, 'button', 'Удалить эксперимент').dispatch('click');
  const dialog = ctx.document.body.querySelector('.modal');
  out.question = dialog.textContent;
  out.deletedBefore = ctx.requests.filter((r) => r.method === 'DELETE').length;
  await byText(dialog, 'button', 'Удалить').dispatch('click'); await tick(); await tick();
  out.deleted = ctx.requests.filter((r) => r.method === 'DELETE').map((r) => r.path);
  out.route = ctx.location ? null : null;
""")
    assert out["tabs"] == ["Результат", "Матрица", "Проверки (2)", "Плата", "Выводы (1)"] and out["shown"] == ["ep-tab-panel-result"]
    assert [row[0].split("IMG")[0] for row in out["checks"]] == ["Проверка №71", "Проверка №70"] and out["checks"][0][1] is False and out["checks"][1][1] is True   # newest first, the main one is shown
    assert out["links"] == [["Разбор", "#/analysis/71"], ["Проверить и принять", "#/ingest?pair=70"]]
    assert out["before"] == "/api/pairs/70/overlay.png" and out["after"] == "/api/pairs/71/overlay.png" and out["current"] == ["Проверка №71"]
    assert "Цвет найден" in out["findings"] and "Прежние версии вывода: 1" in out["findings"] and "Кандидат" in out["findings"]
    assert "все проверки (2)" in out["question"] and out["deletedBefore"] == 0                      # asked first
    assert out["deleted"] == ["/api/pairs/70", "/api/pairs/71", "/api/plans/5"]                    # each check on its own, then the plate


# -- the frame -------------------------------------------------------------------------------------------------------------------------
def test_the_experiment_page_takes_the_screen_with_the_photo_filling_its_column_and_only_a_long_panel_scrolling():
    assert re.search(r"\.ep-body \{grid-template-columns:minmax\(340px,42%\) minmax\(0,1fr\)\}", CSS)
    assert re.search(r"\.ep-stage \{position:relative;flex:1;min-height:0;overflow:auto", CSS) and re.search(r"\.ep-stage>a \{position:absolute;inset:8px", CSS)
    assert re.search(r"\.ep-photo \{[^}]*width:100%;height:100%;object-fit:contain", CSS)
    assert re.search(r"@media \(max-width:1100px\) \{\s*\.ep-stage \{flex:none;height:60vh\}", CSS)                   # a phone: the photo gets a height, the page scrolls
    for gone in (".exp-head", ".exp-photo-card", ".exp-stage", ".exp-photo ", ".exp-tools", ".exp-checks", ".exp-check "):
        assert gone not in CSS, gone                                                                      # the rules of the old long page are gone
    script = (UI / "screens" / "experiment.js").read_text(encoding="utf-8")
    assert "App.tabs(items, {initial: items[0][0], remember: 'ep.tab'" in script and "class: 'os experiment'" in script
