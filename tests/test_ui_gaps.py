"""Screens of the I-15 gaps: what they show is rendered from the fields the API returns (static checks of the scripts, as in
test_ui_files and test_conversion_ui), and the names the server keeps in English are shown in Russian (run with node)."""
import json
import re
import shutil
import subprocess

import pytest

from titanium_platform.api.app import UI_DIR


def source(name: str) -> str:
    return (UI_DIR / name).read_text(encoding="utf-8")


def test_the_gap_translations_are_loaded_with_the_other_tables_and_before_the_screens():
    scripts = re.findall(r'<script src="(/[^"]+)"', source("index.html"))
    assert scripts.index("/i18n-gaps.js") == scripts.index("/i18n-data.js") + 1 and scripts.index("/i18n-gaps.js") < scripts.index("/app.js")


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
    assert "'Уверенность', 'Ожидаемая ошибка ΔE', 'Стабильность'" in screen


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
