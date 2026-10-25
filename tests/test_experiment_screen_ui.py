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
SCRIPTS = ["app.js", "photo-modes.js", "photo-quality.js", "dialogs.js", "hardware.js", "tasks.js", "screens/composition.js", "screens/ingest-upload.js", "screens/ingest-dialogs.js", "screens/ingest-tasks.js", "screens/ingest-review.js",
           "screens/vector-workspace.js", "screens/prediction-review.js"]
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
    assert out["photoTools"] == ["Скрыть контуры", "Поднять яркость", "Перемерить заново"] and out["legend"] == ["Что означают линии"]
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
    assert "visibility=lifted" in out["normal"] and out["light"] == "1" and out["buttons"] == ["Показать контуры", "Обычная яркость", "Перемерить заново"]


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


PHOTO_WORK = experiment("plan-28", kind="Photo engraving work", plan_id=28, engraving_id=None, main_pair_id=51,
                        plate={"plan_id": 28, "name": "Inna Portrait", "mode": "Photo engraving work", "status": "Draft", "test_name": None, "description": None,
                               "layers": 0, "band_count": None, "identifier": "TCE-P-41F96DBB", "proposal": None, "engraving_task": None},
                        pairs=[pair_summary(51, alignment="picture", name="simulated.png", grayscale_image=True)])


@node
def test_a_photo_work_is_shown_as_the_work_opened_and_exported_on_its_own_screen_not_as_a_plate(tmp_path):
    out = run(tmp_path, routes_for(PHOTO_WORK), "plan-28", """
  out.tabs = tabButtons(tree).map((b) => b.textContent);
  const side = tree.querySelectorAll('aside').find((s) => has(s, 'ep-side'));
  out.side = side.textContent;
  out.links = side.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
""")
    assert out["tabs"][-1] == "Работа фотогравировки" and "Плата" not in out["tabs"]
    assert "Inna Portrait" in out["side"] and "TCE-P-41F96DBB" in out["side"] and "слоёв" not in out["side"]
    links = dict(out["links"])
    assert links["Открыть работу"] == "#/photo-engraving?work=28" and links["Скачать .lbrn2"] == "/api/photo-works/28/export.lbrn2"
    assert "Открыть и изменить плату" not in links and "Попросить AI-исследователя изменить плату" not in links


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



# -- the prediction against the result (DEC-117) ----------------------------------------------------------------------------------------
def photo_detail(pid):
    """An accepted photograph of one grayscale picture layer with its tonal profile."""
    out = pair_detail(pid, layers=1)
    out["check"]["warnings"] = []
    out["check"]["layers"][0].update(name="C00", type="Image", image={"dither": "grayscale"}, tonal={"rho": -0.9, "range_L": 40})
    return out


def bands():
    return [{"power": 1.9, "gray": 1.0, "lab": [91.2, -0.2, 6.0], "predicted": [76.2, 0.1, 7.8], "de": 15.1},
            {"power": 9.2, "gray": 0.75, "lab": [79.0, 3.0, 38.0], "predicted": [40.0, 14.0, 4.0], "de": 52.8}]


REVIEW = {"pair_id": 111, "photo": "IMG_3378.DNG", "accepted": True, "tolerance_de": 5.0, "layers": [{
    "layer": 0, "name": "C00", "kind": "grayscale", "row_mm": 150.0, "reason": None, "engravings": 1, "compared": 16, "median_de": 18.7, "max_de": 59.5,
    "within": 0.125, "median_dL": 17.1, "median_db": 0.7, "tolerance_de": 5.0, "bands": bands(), "causes": [
        {"code": "size", "row_mm": 150.0, "measured_mm": [38.4, 100.0], "how": "outside", "from_mm": [100.0], "engravings": 1, "differs": True},
        {"code": "plate", "own": {"id": 2, "name": "Big Plate 150", "thickness_mm": 3.0}, "used": [{"id": 3, "name": "Small Plate", "thickness_mm": 2.0}], "differs": True},
        {"code": "cleaning", "own": True, "used": [{"pair_id": 109, "photo": "IMG_3377.DNG", "cleans": False}], "differs": True},
        {"code": "photo", "own": {"pair_id": 111, "photo": "IMG_3378.DNG", "L": 91.2, "how": "lightest"},
         "used": [{"pair_id": 109, "photo": "IMG_3377.DNG", "L": 76.2, "how": "lightest", "same_surface": False}],
         "same_surface": [{"pair_id": 108, "photo": "IMG_3376.DNG", "L": 79.4, "how": "witness"}], "dL_used": 15.0, "dL_same": 11.8, "differs": True}]}]}
OVERALL = {"tolerance_de": 5.0, "all": {"layers": 3, "engravings": 3, "tones": 47, "median_de": 13.8, "within": 0.213},
           "size_measured": {"layers": 1, "engravings": 1, "tones": 15, "median_de": 10.2, "within": 0.4}, "layers": []}
PORTRAIT = experiment("plan-32", kind="Работа фотогравировки", plan_id=32, engraving_id=None, main_pair_id=111,
                      pairs=[pair_summary(111, alignment="picture", name="IMG_3378.DNG", grayscale_image=True)])


@node
def test_an_accepted_photo_engraving_shows_what_was_predicted_before_it_beside_what_came_out_and_why(tmp_path):
    routes = routes_for(PORTRAIT)
    routes.update(api(**{"/api/pairs/111": photo_detail(111), "/api/pairs/111/prediction-review": REVIEW, "/api/prediction-reviews": OVERALL}))
    out = run(tmp_path, routes, "plan-32", """
  const side = tree.querySelectorAll('aside').find((s) => has(s, 'ep-side'));
  const card = side.querySelectorAll('div').find((d) => has(d, 'pr-card'));
  out.order = side.querySelectorAll('h3').map((x) => x.textContent);
  out.text = card.textContent;
  out.pills = card.querySelectorAll('span').filter((x) => has(x, 'pill')).map((x) => [x.textContent, x.className]);
  out.causes = card.querySelectorAll('li').filter((li) => !has(li, 'pr-tone')).map((li) => [li.textContent, li.className]);
  out.tones = card.querySelectorAll('li').filter((li) => has(li, 'pr-tone')).map((li) => li.textContent);
  out.summary = card.querySelectorAll('summary').map((x) => x.textContent);
  out.asked = ctx.requests.map((r) => r.path).filter((x) => x.includes('review'));
""")
    assert out["order"][:2] == ["Прогноз и результат", "Измеренные слои · 1"]                    # before the measured layers
    assert out["asked"] == ["/api/pairs/111/prediction-review", "/api/prediction-reviews"]
    assert "Прогноз по 1 гравировке, принятой раньше" in out["text"] and ["медиана 18,7 ΔE", "pill warn"] in out["pills"]
    assert "Тонов сравнено: 16 · максимум 59,5 ΔE · в пределах 5 ΔE: 13 %. Вышло светлее прогноза на 17,1 L* (медианы по тонам)." in out["text"]
    size, plate, cleaning, photo = out["causes"]
    assert size == ["Ширина строк 150 мм — вне измеренных до неё (38,4; 100 мм): прогноз взят с ближайшей, 100 мм, без пересчёта. "
                    "На другой ширине строки остывают иначе, и та же мощность даёт другие цвета.", "pr-warn"]
    assert plate == ["Прогноз — по гравировкам на Small Plate (2 мм); эта — на Big Plate 150 (3 мм).", "pr-warn"]
    assert cleaning == ["Эта гравировка — по чистке; прогноз — по гравировкам без чистки.", "pr-warn"]
    assert photo[0] == ("Чистый титан на этом фото — IMG_3378.DNG: L* 91,2 (самый светлый тон). На фото прогноза — IMG_3377.DNG: L* 76,2 "
                        "(самый светлый тон): это фото светлее на 15 L*. На той же пластине с той же чисткой — IMG_3376.DNG: L* 79,4 "
                        "(свидетель чистки): это фото светлее на 11,8 L* — это свет снимка, а не металл.")
    assert out["summary"] == ["Тона: прогноз и результат (2)"] and out["tones"][0].startswith("1,9 %") and "52,8 ΔE" in out["tones"][1]
    assert "прогноз до них ошибался на 13,8 ΔE (медиана 47 тонов, гравировок 3); где ширина была измерена заранее — 10,2 ΔE." in out["text"]


@node
def test_a_photograph_without_a_picture_layer_asks_for_no_review_and_a_first_one_says_there_was_no_prediction(tmp_path):
    routes = routes_for(MATRIX, PORTRAIT)
    first = {**REVIEW, "layers": [{**REVIEW["layers"][0], "name": name, "reason": "first", "compared": 0, "bands": [], "causes": []}
                                  for name in ("GREY-1", "GREY-2")]}
    routes.update(api(**{"/api/pairs/111": photo_detail(111), "/api/pairs/111/prediction-review": first, "/api/prediction-reviews": OVERALL}))
    out = run(tmp_path, routes, "eng-abc", """
  out.matrixAsked = ctx.requests.map((r) => r.path).filter((x) => x.includes('review'));
  const again = await screen('plan-32');
  const side = again.querySelectorAll('aside').find((s) => has(s, 'ep-side'));
  out.text = side.querySelectorAll('div').find((d) => has(d, 'pr-card')).textContent;
""")
    assert out["matrixAsked"] == []
    assert out["text"].count("до неё на этих настройках") == 1 and "GREY" not in out["text"]       # one line for every layer of one reason
    assert "Прогноз: до неё на этих настройках ничего не было измерено — прогноза не было; теперь шкала этих настроек строится по ней." in out["text"]


@node
def test_a_prediction_from_the_same_plate_and_cleaning_puts_the_difference_on_the_photographs_light(tmp_path):
    routes = routes_for(PORTRAIT)
    layer = REVIEW["layers"][0]
    photo = {**layer["causes"][3], "used": [{"pair_id": 93, "photo": "IMG_3296.DNG", "L": 65.5, "how": "lightest", "same_surface": True}],
             "same_surface": [], "dL_used": 9.2, "dL_same": None}
    review = {**REVIEW, "layers": [{**layer, "causes": [*layer["causes"][:3], photo]}]}
    routes.update(api(**{"/api/pairs/111": photo_detail(111), "/api/pairs/111/prediction-review": review, "/api/prediction-reviews": OVERALL}))
    out = run(tmp_path, routes, "plan-32", """
  const card = tree.querySelectorAll('div').find((d) => has(d, 'pr-card'));
  out.photo = card.querySelectorAll('li').filter((li) => !has(li, 'pr-tone'))[3].textContent;
""")
    assert out["photo"] == ("Чистый титан на этом фото — IMG_3378.DNG: L* 91,2 (самый светлый тон). На фото прогноза — IMG_3296.DNG: L* 65,5 "
                            "(самый светлый тон): это фото светлее на 9,2 L*. Пластина и чистка те же — это свет снимка, а не металл.")

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


@node
def test_the_pencil_beside_the_title_renames_the_experiment_with_one_request(tmp_path):
    routes = routes_for(WORK)
    routes["/api/experiments/eng-work/rename"] = {"status": 200, "json": {"id": "eng-work", "name": "Inna Portrait 150 мм"}}
    out = run(tmp_path, routes, "eng-work", """
  const head = tree.querySelectorAll('header').find((x) => has(x, 'ep-head'));
  const pencil = head.querySelectorAll('button').find((b) => has(b, 'vw-rename'));
  out.pencil = [pencil.textContent, pencil.getAttribute('aria-label')];
  await pencil.dispatch('click');
  const dialog = ctx.document.body.querySelector('.modal');
  out.dialog = [dialog.querySelector('h3').textContent, dialog.querySelector('input').value];
  dialog.querySelector('input').value = '  Inna Portrait 150 мм ';
  await byText(dialog, 'button', 'Сохранить').dispatch('click'); await tick(); await tick();
  out.posts = ctx.requests.filter((r) => r.method === 'POST').map((r) => [r.path, r.body]);
  out.title = head.querySelector('h2').textContent;
  out.label = pencil.getAttribute('aria-label');
  out.toasts = ctx.document.body.querySelectorAll('.toast').map((t) => t.textContent);
""")
    assert out["pencil"] == ["✎", "Переименовать эксперимент «Тест материала»"]
    assert out["dialog"] == ["Переименовать эксперимент", "Тест материала"]
    assert out["posts"] == [["/api/experiments/eng-work/rename", json.dumps({"name": "Inna Portrait 150 мм"}, separators=(",", ":"), ensure_ascii=False)]]
    assert out["title"] == "Inna Portrait 150 мм" and out["label"] == "Переименовать эксперимент «Inna Portrait 150 мм»"
    assert out["toasts"] == ["Эксперимент переименован ×"]


# -- a photographed photo engraving judged as a picture, and the copies of a «Подобрать настройки» plate (photo-engraving-quality) --------
def judged(score, findings, **tone):
    scales = [{"mm": 0.2, "kept": 0.3, "grain_L": 2.0}, {"mm": 0.4, "kept": 0.55, "grain_L": 2.4}, {"mm": 0.8, "kept": 0.8, "grain_L": 2.6},
              {"mm": 0.1, "kept": None, "reason": "finer than the photograph"}]
    return {"algorithm": 1, "score": score, "findings": findings, "detail": {"kept": 0.55, "grain_L": 2.4, "scales": scales},
            "tone": {"measured_by": "picture", "levels": 9, "steps": 16, "range_L": 25.0, "black_L": 31.0, "white_L": 56.0, "mean_L": 44.0, **tone}}


BLOCKED = {"code": "shadows_blocked", "value": 0.3, "basis": "prior",
           "moves": [{"setting": "power", "direction": "down"}, {"setting": "dot_width", "direction": "up"}, {"setting": "line_interval", "direction": "up"}]}
GOOD = {"code": "good", "value": 0.81, "moves": [], "basis": None}


def variations_detail(pid):
    out = photo_detail(pid)
    out["check"]["layers"][0].update(name="PV1-PICTURE", image={"dither": "jarvis"}, photo_quality=judged(0.42, [BLOCKED]))
    out["variations"] = {
        "ranked": [{"copy": 2, "score": 0.81, "findings": [GOOD], "label": "2 J P20"},
                   {"copy": 1, "score": 0.42, "findings": [BLOCKED], "label": "1 J P25 V125 F60 PW200 I.01"}],
        "best": 2, "best_label": "2 J P20", "settled": False, "step": 1.0,
        "effects": [{"copy": 2, "label": "2 J P20", "changed": [{"setting": "power", "from": 25.0, "to": 20.0}], "mean_L": 3.1, "range_L": 2.0,
                     "shadows_blocked": -0.2, "highlights_lost": 0.0, "levels": 2, "mid_darkness": -0.05, "kept": 0.1, "score": 0.39}],
        "next": {"centre": {"dither": "jarvis", "power": 20.0}, "step": 0.5}}
    return out


@node
def test_a_photographed_variations_plate_ranks_its_copies_says_what_each_change_did_and_makes_the_next_plate(tmp_path):
    routes = routes_for(PORTRAIT)
    routes.update(api(**{"/api/pairs/111": variations_detail(111), "/api/pairs/111/prediction-review": REVIEW, "/api/prediction-reviews": OVERALL}))
    routes["/api/pairs/111/next-variations"] = {"status": 201, "json": {"plan_id": 40, "name": "Фотогравировка · TCE-40"}}
    out = run(tmp_path, routes, "plan-32", """
  const side = tree.querySelectorAll('aside').find((s) => has(s, 'ep-side'));
  const box = side.querySelectorAll('div').find((d) => has(d, 'pq-variations'));
  out.text = box.textContent;
  out.layer = side.querySelectorAll('div').find((d) => has(d, 'pq-layer')).textContent;
  await byText(box, 'button', 'Сделать следующую плату').dispatch('click'); for (let i = 0; i < 4; i++) await tick();
  out.posted = ctx.requests.filter((r) => r.path.endsWith('/next-variations')).map((r) => r.method);
  out.went = ctx.location.hash;
""")
    text = out["text"]
    assert "Лучше всех — копия 2 J P20 (оценка 0,81)." in text
    assert "2 J P20 — 0,81" in text and "1 J P25 V125 F60 PW200 I.01 — 0,42 · Тени слились: всё темнее 30 % серого выходит одним тоном" in text
    assert "мощность 25 % → 20 %: светлее на 3,1 L*, контраст +2 L*, тени открылись на 20 %, тонов +2, чётче (+10 % деталей)" in text
    assert "Следующая плата: та же картинка вокруг копии 2, изменения вдвое меньше (шаг 0,5 от первых)." in text
    layer = out["layer"]
    assert "PV1-PICTURE" in layer and "оценка 0,42" in layer and "Различимых тонов 9 из 16, от чёрного до белого 25 L* (31 → 56), в среднем L* 44." in layer
    assert "Детали сохранились: 0,2 мм — 30 %, 0,4 мм — 55 %, 0,8 мм — 80 %; зерно ±2,4 L*." in layer
    assert "Что поменять: мощность меньше, поправка ширины точки больше, шаг строк больше (по опыту процесса)" in layer
    assert out["posted"] == ["POST"] and out["went"] == "#/experiment/plan-40"
