"""Screens of the I-15 gaps: what they show is rendered from the fields the API returns (static checks of the scripts, as in
test_ui_files and test_conversion_ui), and the names the server keeps in English are shown in Russian (run with node)."""
import json
import re
import shutil
import subprocess

import pytest

from test_vector_work import TABLES
from titanium_platform.api.app import UI_DIR


def source(name: str) -> str:
    return (UI_DIR / name).read_text(encoding="utf-8")


def test_the_gap_translations_are_loaded_with_the_other_tables_and_before_the_screens():
    scripts = re.findall(r'<script src="(/[^"]+)"', source("index.html"))
    tables = [i for i, script in enumerate(scripts) if script.startswith("/i18n")]
    assert scripts.index("/i18n-gaps.js") == max(tables) and max(tables) < scripts.index("/app.js")   # after every other table


# -- REQ-002, REQ-004 AC3/AC5: the discrete conversion and the plan show the three estimates of every match and layer --------
def test_the_discrete_screen_renders_each_matchs_titanium_colour_errors_confidence_stability_and_the_threshold():
    screen = source("screens/artwork.js")
    for field in ("m.titanium", "swatch(t.lab)", "num(m.distance)", "num(t.expected_delta_e)", "num(m.match_error)", "num(t.confidence)",
                  "t.stability.assessed", "num(t.stability.variance)", "plan.threshold"):
        assert field in screen, field
    for header in ("'Цвет титана'", "'ΔE до цели'", "'Ожидаемая ошибка записи'", "'Ожидаемая ошибка совпадения'", "'Уверенность'", "'Стабильность'"):
        assert header in screen, header
    assert "Текущий порог ΔE: ${plan.threshold}" in screen and "field('Порог ΔE', thr)" in screen


def test_the_plan_screen_renders_the_three_estimates_of_each_layer_from_its_prediction():
    screen = source("screens/plan.js")
    for field in ("num(pr.confidence)", "num(pr.expected_delta_e)", "pr.stability.assessed", "num(pr.stability.variance)"):
        assert field in screen, field
    # a layer is a line of a short list (DEC-090): its three estimates are the facts under the line, in this order
    at = [screen.index(f"['{label}', pr ? ") for label in ("Уверенность", "Ожидаемая ошибка ΔE", "Стабильность")]
    assert at == sorted(at)


def test_a_setting_computed_from_a_law_is_shown_with_its_three_estimates_or_the_reason_it_is_not():
    screen = source("screens/color-map.js")
    for field in ("e.confidence", "e.expected_delta_e", "e.stability.variance", "I18N.tr(r.note"):
        assert field in screen, field
    assert "within_measured" not in screen                        # nothing beyond the measured doses is offered


# -- REQ-015, REQ-016: settings missing from the file ----------------------------------------------------------------------------
def test_the_pair_review_offers_an_input_for_exactly_the_missing_settings_and_shows_who_supplied_them():
    screen = source("screens/ingest-review.js")
    assert "l.missing_settings" in screen and "layer.missing_settings.map((s) => entry(layer, s))" in screen
    assert "post(`/pairs/${pair.id}/supplied-settings`, {layer_index: layer.index, setting, value})" in screen
    assert "введено оператором" in screen and "given.at" in screen and "send(self, layer, setting, null)" in screen
    assert "await suppliedSettingsCard(pair, reload)" in screen


# -- REQ-019, REQ-018, REQ-017 -------------------------------------------------------------------------------------------------------
def test_the_lens_tab_saves_the_measured_spot_on_the_lens_and_m2_on_the_laser():
    tab = source("screens/device-lens.js")
    assert "patch('/lenses/' + lens.id, {spot_diameter_um: num(f.spot)})" in tab and "lens.spot_diameter_um" in tab
    assert "spot_diameter_um" not in source("screens/device-forms.js")             # the passport form no longer takes a spot
    assert "p.spot_diameter_um" not in source("screens/device-view.js")


def test_a_plate_against_an_unknown_work_field_is_labelled_not_checked_in_the_dialog_and_on_the_plan():
    label = "поле линзы неизвестно — размещение не проверено"
    assert label in source("screens/plate-dialog.js") and "summary.work_field" in source("screens/plate-dialog.js")
    assert label in source("screens/plan.js") and "p.work_field" in source("screens/plan.js")


def test_the_laser_card_shows_unresolved_controller_values_together():
    card = source("screens/device-character-card.js")
    assert "d.characterization.unresolved" in card and "c.values[0]" in card and "c.values[1]" in card


# -- REQ-024 AC7, REQ-027 AC4: margins per side on the review and experiment screens -------------------------------------------------
def test_the_hidden_margins_are_shown_per_side_on_the_review_and_the_experiment_screens():
    review, experiment = source("screens/ingest-review.js"), source("screens/experiment.js")
    assert "function hiddenMargins(alignment)" in review and "alignment.hidden_mm" in review and "alignment.frame_sides" in review
    assert "return {render, matrixGrid, hiddenMargins};" in review and "IngestReview.hiddenMargins(check.alignment)" in experiment


# -- REQ-031: the names of a matrix and its cells in Russian ---------------------------------------------------------------------
def test_the_matrix_title_and_cell_names_are_shown_through_the_name_rules():
    review, experiment, dialogs = source("screens/ingest-review.js"), source("screens/experiment.js"), source("screens/ingest-dialogs.js")
    assert "I18N.name(pair.engraving_title)" in review and "I18N.name(layer.name)" in review and "I18N.name(l.name)" in review
    assert "h('h2', {}, I18N.name(exp.title))" in experiment and "I18N.name(l.name)" in experiment
    assert "I18N.name(l.name)" in dialogs


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_server_names_of_a_matrix_read_in_russian_and_an_operators_title_is_left_alone(tmp_path):
    names = ["Material test: Power x Speed · 330 kHz 4 ns · IMG_3290", "Material test: Interval · 1950 kHz 2 ns · IMG_3291",
             "Material test: matrix · IMG_3292", "Power 20.0 x Speed 900", "Q-Pulse 4", "Interval 0.0030 x Power 35", "Cell 2,3",
             "Inna portrait", "C01", "Speed 900 x Colour 3"]
    script = tmp_path / "names.js"
    tables = ["i18n.js", "i18n-more.js", "i18n-device.js", "i18n-rest.js", "i18n-photo.js", "i18n-data.js", "i18n-gaps.js"]
    script.write_text(
        "const fs=require('fs'),vm=require('vm');\n"
        f"const ui={json.dumps(str(UI_DIR) + '/')};\n"
        f"const code={json.dumps(tables)}.map(f=>fs.readFileSync(ui+f,'utf8')).join('\\n')+';globalThis.__I=I18N;';\n"
        "const ctx={};vm.createContext(ctx);vm.runInContext(code,ctx);\n"
        f"console.log(JSON.stringify({json.dumps(names)}.map((n)=>ctx.__I.name(n))));\n", encoding="utf-8")
    out = json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60, check=True).stdout)
    assert out == ["Тест материала: Мощность × Скорость · 330 кГц 4 нс · IMG_3290", "Тест материала: Шаг строк · 1950 кГц 2 нс · IMG_3291",
                   "Тест материала: матрица · IMG_3292", "Мощность 20.0 × Скорость 900", "Q-Pulse 4", "Шаг строк 0.0030 × Мощность 35",
                   "Ячейка 2,3", "Inna portrait", "C01", "Speed 900 x Colour 3"]


def run_translations(tmp_path, messages: list[str]) -> list[str]:
    """The messages through I18N.tr with every translation table, as the screens show them."""
    script = tmp_path / "tr.js"
    tables = ["i18n.js", "i18n-more.js", "i18n-device.js", "i18n-rest.js", "i18n-photo.js", "i18n-tasks.js", "i18n-data.js",
              "i18n-findings.js", "i18n-palette.js", "i18n-gaps.js"]
    script.write_text(
        "const fs=require('fs'),vm=require('vm');\n"
        f"const ui={json.dumps(str(UI_DIR) + '/')};\n"
        f"const code={json.dumps(tables)}.map(f=>fs.readFileSync(ui+f,'utf8')).join('\\n')+';globalThis.__I=I18N;';\n"
        "const ctx={};vm.createContext(ctx);vm.runInContext(code,ctx);\n"
        f"console.log(JSON.stringify({json.dumps(messages)}.map((n)=>ctx.__I.tr(n))));\n", encoding="utf-8")
    return json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60, check=True).stdout)


# -- REQ-036 AC3: shapes and settings the importer does not read are shown on their layer -----------------------------------------
def test_the_review_screen_prints_every_note_of_a_layer_whether_it_was_measured_or_skipped():
    dialogs, review = source("screens/ingest-dialogs.js"), source("screens/ingest-review.js")
    # skipped layer: its notes beside the status; measured layer: its notes under the colour
    assert "pill(l.readable ? 'пропущен' : 'нечитаем', 'warn'), ' ', l.notes.map((n) => I18N.tr(n)).join('; ')" in dialogs
    assert "if (l.notes?.length) details.push(h('div', {class: 'muted small'}, l.notes.map((n) => I18N.tr(n)).join('; ')));" in dialogs
    assert "IngestDialogs.layersTable(check.layers)" in review and "h('h3', {}, 'Слои файла')" in review


def test_the_matrix_review_shows_the_recognised_labels_the_uncertain_values_and_whose_reconstruction_the_settings_are():
    """REQ-036 AC8: what was read from the photograph, what is missing, unusual or disagrees, and that the settings are the
    operator's confirmed reconstruction (with when), not an original LightBurn file."""
    review = source("screens/ingest-review.js")
    card = review[review.index("function matrixCard(pair, reload)"):review.index("async function render(pair, reload)")]
    for label in ("labels.header", "labels.x_title", "labels.y_title", "readings(labels.rows)", "readings(labels.cols)"):
        assert label in card, label                                     # every label recognised on the photograph
    for uncertain in ("fit.y.read", "fit.y.agreeing", "fit.x.read", "fit.x.agreeing", "s.missing.map((x) => I18N.tr(x))",
                      "s.unusual.map(paramName)"):
        assert uncertain in card, uncertain                             # read against agreeing labels, missing and unusual values
    assert "`параметры подтверждены ${stamp(m.confirmed_at)}`" in card and "pill('параметры ждут подтверждения', 'warn')" in card
    assert "восстановлены по фотографии матрицы и подтверждаются оператором" in card and "не является исходным файлом" in card


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_notes_of_unread_shapes_and_unknown_settings_read_in_russian(tmp_path):
    out = run_translations(tmp_path, ["2 Ellipse objects on this layer are not read: no outline geometry",
                                      "settings unknown to this version are kept with the recipe but not interpreted: perfMode, rampLength"])
    assert out == ["Объектов «Ellipse» на этом слое: 2. Они не читаются: у них нет контура в файле.",
                   "Настройки, неизвестные этой версии, сохранены в рецепте, но не учитываются: perfMode, rampLength"]


# -- findings-you-can-manage-short-lists-re-check REQ-005: the review's layer lists are short lists (run in node) ------------------
REVIEW = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'photo-modes.js', 'dialogs.js', 'list.js', 'tasks.js', 'screens/composition.js', 'screens/ingest-dialogs.js',
  'screens/ingest-tasks.js', 'screens/ingest-review.js', {code: %(glue)s}]);
const tick = () => new Promise((r) => setTimeout(r, 0));
const reloads = [];
const draw = async () => { const t = await ctx.__review.render(data.pair, () => { reloads.push(1); }); for (let i = 0; i < 4; i++) await tick(); return t; };
const listOf = (t, title) => t.querySelectorAll('div').find((d) => (d.className || '').split(' ').includes('card') && d.querySelector('h3')
  && d.querySelector('h3').textContent === title).querySelector('.lst');
const keys = (l) => l.querySelectorAll('.lst-row').map((r) => r.getAttribute('data-key'));
const lines = (l) => l.querySelectorAll('.lst-main');
const opened = (l) => l.querySelectorAll('.lst-det').filter((d) => !d.hidden).map((d) => d.textContent);
(async () => {
  const out = {};
  const tree = await draw();
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""
REVIEW_GLUE = ("const __session = {}; globalThis.__review = IngestReview;"
               "globalThis.sessionStorage = {getItem: (k) => (k in __session ? __session[k] : null), setItem: (k, v) => { __session[k] = String(v); }};")


def review_layer(index, **over):
    return {"index": index, "name": f"C{index:02d}", "type": "Scan", "power": 40.0, "frequency_khz": 1950.0, "speed": 1800.0, "pulse_width": 200.0,
            "line_interval": 0.003, "passes": 1, "regions": 2, "readable": True, "compatible": True, "notes": [], "missing_settings": [],
            "supplied_settings": {}, "defaulted_settings": {}, "measured_lab": [50.0 - index, 10.0, -10.0], "pixels": 1200, "role": "test feature",
            "task": {"kind": "fill", "basis": "derived", "source": "layer"}, "metrics": [], **over}


def review_pair():
    """A photograph of a file with 30 layers: 22 lack the pass count (one is given by the operator), one has no fill and was skipped, one
    could not be read."""
    layers = [review_layer(i, missing_settings=["passes"], passes=None) if i < 22 else review_layer(i) for i in range(28)]
    layers[2]["supplied_settings"] = {"passes": {"value": 2, "by": "operator", "at": "2026-10-25T10:00:00+00:00"}}
    layers += [review_layer(28, regions=0, measured_lab=None, pixels=None, notes=["the layer has no fill geometry"]),
               review_layer(29, readable=False, compatible=False, measured_lab=None, pixels=None, notes=["pulse width is missing from this LightBurn layer"])]
    check = {"layers": layers, "problems": [], "warnings": [], "discrepancies": [], "color_measurement": {"mode": "reference_chart_corrected"},
             "chart": {"detected": True, "usable": True, "residual": 1.2}, "alignment": {"valid": True, "method": "markers", "marker_count": 4}}
    return {"id": 77, "status": "Needs correction", "lightburn_name": "work.lbrn2", "photo_name": "IMG_77.DNG", "engraving_title": "Работа",
            "device_id": 1, "matrix": None, "layer_tasks": {}, "work_task": None, "plan_task": None, "file_confirmation": None, "check": check}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_review_shows_the_layers_of_a_long_file_as_short_lists_with_their_fields_and_choices_under_a_line(tmp_path):
    """A file of 30 layers: «Слои файла», «Настройки, которых нет в файле LightBurn» and «Задачи гравировки» each show a page of 20 lines;
    the layers not measured come first in «Слои файла»; the result, the fields of the missing settings and the task choice open under a
    line; a task chosen for a layer is sent and the layer stays open when the page is drawn again."""
    routes = {"/api/pairs/77/tasks": {"status": 200, "json": {}}}
    (tmp_path / "data.json").write_text(json.dumps({"pair": review_pair(), "routes": routes}), encoding="utf-8")
    script = tmp_path / "review.js"
    script.write_text(REVIEW % {"dom": json.dumps(str(UI_DIR.parents[2] / "tests" / "ui_dom.js")), "data": json.dumps(str(tmp_path / "data.json")),
                                "ui": json.dumps(str(UI_DIR) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(REVIEW_GLUE), "body": """
  const files = listOf(tree, 'Слои файла');
  out.files = {keys: keys(files), count: files.querySelector('.lst-count').textContent, lines: lines(files).slice(0, 3).map((m) => m.textContent),
    chips: files.querySelectorAll('.lst-chip').map((c) => c.textContent)};
  await lines(files)[0].dispatch('click'); await tick();
  out.files.open = opened(files);
  const supplied = listOf(tree, 'Настройки, которых нет в файле LightBurn');
  out.supplied = {keys: keys(supplied), count: supplied.querySelector('.lst-count').textContent, lines: lines(supplied).slice(0, 3).map((m) => m.textContent),
    fieldsBefore: supplied.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'number').length};
  await lines(supplied)[0].dispatch('click'); await tick();
  out.supplied.fields = supplied.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'number').map((i) => i.getAttribute('aria-label'));
  await lines(supplied)[2].dispatch('click'); await tick();
  out.supplied.given = opened(supplied);
  const tasks = listOf(tree, 'Задачи гравировки');
  out.tasks = {keys: keys(tasks), count: tasks.querySelector('.lst-count').textContent, choicesBefore: tasks.querySelectorAll('select').length};
  await lines(tasks)[1].dispatch('click'); await tick();
  const choice = tasks.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === 'Задача слоя C01');
  choice.value = 'text'; await choice.dispatch('change'); for (let i = 0; i < 4; i++) await tick();
  out.tasks.sent = ctx.requests.filter((r) => r.method === 'PUT').map((r) => [r.path, JSON.parse(r.body)]);
  out.tasks.reloads = reloads.length;
  const again = listOf(await draw(), 'Задачи гравировки');
  out.tasks.reopened = again.querySelectorAll('.lst-row').filter((r) => (r.className || '').split(' ').includes('open')).map((r) => r.getAttribute('data-key'));
"""}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2500:]
    out = json.loads(done.stdout)
    files, supplied, tasks = out["files"], out["supplied"], out["tasks"]
    assert len(files["keys"]) == 20 and files["count"] == "показано 20 из 30" and files["keys"][:3] == ["29", "28", "0"]   # not measured first
    assert "нечитаем" in files["lines"][0] and "пропущен" in files["lines"][1] and "измерен" in files["lines"][2]
    assert "40.0 % · 1950 кГц · 1800 мм/с" in files["lines"][2] and "областей 2" in files["lines"][2]
    assert files["chips"] == ["Все · 30", "Нечитаемые · 1", "Пропущенные · 1", "Измеренные · 28"]
    assert files["open"] == ["нечитаем В этом слое LightBurn не задан Q-Pulse"]                    # the result and its notes under the line
    assert len(supplied["keys"]) == 20 and supplied["count"] == "показано 20 из 22" and supplied["fieldsBefore"] == 0
    assert supplied["lines"][0] == "C00нет в файле: проходы" and "введено оператором: 1" in supplied["lines"][2]
    assert supplied["fields"] == ["Проходы, слой C00"]
    assert len(supplied["given"]) == 1 and "Проходы: 2" in supplied["given"][0] and "Убрать" in supplied["given"][0]
    assert len(tasks["keys"]) == 20 and tasks["count"] == "показано 20 из 29" and tasks["choicesBefore"] == 0   # a layer without fill has no task
    assert tasks["sent"] == [["/api/pairs/77/tasks", {"layer_index": 1, "task": "text"}]] and tasks["reloads"] == 1
    assert tasks["reopened"] == ["1"]
