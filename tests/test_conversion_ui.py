"""Conversion and vector-job screens (REQ-004, REQ-012, REQ-021): static checks of what the screens load and ask the server for."""
import re

from fastapi.testclient import TestClient

from titanium_platform import conversion
from titanium_platform.api.app import UI_DIR, create_app

SCRIPTS = re.findall(r'<script src="(/[^"]+)"', (UI_DIR / "index.html").read_text(encoding="utf-8"))


def source(name: str) -> str:
    return (UI_DIR / name).read_text(encoding="utf-8")


def test_the_vector_screen_is_loaded_after_the_helpers_it_uses_and_has_a_menu_entry():
    order = {s: i for i, s in enumerate(SCRIPTS)}
    for dep in ("/app.js", "/dialogs.js", "/filepick.js", "/hardware.js", "/router.js"):
        assert order[dep] < order["/screens/vector.js"], dep
    assert order["/screens/photo-form.js"] < order["/screens/plan.js"]      # the plan screen lists questioned entries with PhotoForm
    router = source("router.js")
    assert "['/vector', 'Векторная работа']" in router and "vector: 'vector'" in router
    nav = re.search(r"const NAV = \[(.*?)\];", router, re.S).group(1)
    icons = re.search(r"const ICONS = \[(.*?)\];", router, re.S).group(1)
    assert nav.count("['/") == icons.count("'<")                          # one icon per menu entry, in menu order
    assert "App.register({id: 'vector'" in source("screens/vector.js")


def test_the_photo_form_takes_its_band_limit_from_the_server_and_never_offers_more(tmp_path):
    form = source("screens/photo-form.js")
    assert "255" not in form and "value: 32" not in form
    assert "get('/continuous/limits')" in form and "max: String(maxBands)" in form and "value: revising ? Math.min(revising.band_count, maxBands) : maxBands" in form
    with TestClient(create_app(tmp_path / "d")) as c:
        assert c.get("/api/continuous/limits").json()["max_bands"] == conversion.MAX_BANDS == 29


def test_the_banding_picture_is_shown_on_the_photo_artwork_and_plan_screens():
    assert "p.banding_png" in source("screens/photo-form.js")
    assert "/banding.png?v=" in source("screens/artwork.js")              # a new address after every re-match
    assert "/banding.png`" in source("screens/plan.js")


def test_colour_path_offers_the_per_plan_inclusion_of_questioned_entries_and_every_warning_entry_is_listed():
    form = source("screens/photo-form.js")
    assert "Включить параметры под вопросом в этот план" in form and "state.allowed = [...picked]" in form
    assert "include_questioned=true" in form and "!e.questioned || state.allowed.includes(e.id)" in form
    assert "entries.map((e)" in form and "w.knowledge_ids[0]" not in form and "w.knowledge_ids[0]" not in source("screens/plan.js")


def test_a_photo_plan_is_revised_from_its_own_values_and_image_into_a_new_plan():
    form, plan = source("screens/photo-form.js"), source("screens/plan.js")
    assert "ctx.query.plan" in form and "/source-image`" in form and "fd.append('revision_of', revising.id)" in form
    assert "'/photo?plan=' + p.id" in plan and "'/vector?plan=' + p.id" in plan


def test_the_vector_screen_disables_export_while_regions_lack_evidence_and_offers_every_resolution():
    screen = source("screens/vector.js")
    assert "'primary', !!j.export_blocked)" in screen and "I18N.tr(j.export_blocked)" in screen
    for op in ("set_task", "set_layer", "delete", "merge", "set_tolerance", "exclude", "include", "set_settings", "to_designer", "revert", "set_threshold"):
        assert f"op: '{op}'" in screen, op
    assert "App.laserLensPicker(" in screen and "/vector/palette?" in screen and "/exports/${e.number}" in screen


VECTOR_SCREENS = ("screens/vector.js", "screens/vector-split.js", "screens/vector-editor.js", "screens/vector-colours.js")


def test_the_vector_work_steps_are_loaded_before_the_screen_that_assembles_them():
    order = {s: i for i, s in enumerate(SCRIPTS)}
    for part in ("/screens/vector-split.js", "/screens/vector-editor.js", "/screens/vector-colours.js"):
        assert order["/app.js"] < order["/dialogs.js"] < order[part] < order["/screens/vector.js"], part
    assert order["/screens/vector-editor.js"] < order["/screens/vector-colours.js"]      # the colour step embeds the editor
    screen = source("screens/vector.js")
    assert "VectorSplit.card(next, reload, smooth)" in screen and "VectorColours.card(j, run, split, permit)" in screen and "j.strategy === 'photo' ? photoView(j) : jobView(j)" in screen


def test_no_vector_screen_links_to_an_api_address_and_files_are_fetched_with_their_errors_translated():
    for name in VECTOR_SCREENS:
        text = source(name)
        assert not re.search(r"href:\s*[`'\"]/api", text), name                  # the raw API (and its English JSON) is never opened
        assert "window.open(" not in text and "location.href" not in text, name
    screen = source("screens/vector.js")
    assert "await fetch('/api' + path)" in screen and "I18N.tr(raw)" in screen and "URL.createObjectURL(await res.blob())" in screen
    assert "saveButton(`/vector/${id}/exports/${e.number}`" in screen and "saveButton(`/vector/${j.id}/exports/${e.number}`" in screen


def test_the_colouring_step_offers_every_operation_the_server_knows():
    from titanium_platform import vector_job
    colours = source("screens/vector-colours.js") + source("screens/vector-editor.js")
    for op in vector_job.COLOURING_OPS:
        assert f"'{op}'" in colours, op
    for label in ("Ближе к оригиналу", "Сохранить тональность", "Случайно", "Меньше слоёв", "Включить цвета без привязки"):
        assert label in colours, label
    assert "Принять" not in colours                                                    # DEC-001: nothing waits for acceptance
    split = source("screens/vector-split.js")
    assert "post(`/vector/${j.id}/split`" in split and "'Разбить заново'" in split and "лицо не найдено" in split


def test_the_discrete_screens_offer_a_time_limit_and_say_that_the_fastest_colour_within_the_threshold_is_chosen():
    start, plan = source("screens/artwork-start.js"), source("screens/artwork.js")
    assert "fd.append('max_time', maxTime.value)" in start and "Наибольшее время гравировки, с/см²" in start
    assert "выбирается самый быстрый" in start and "выбирается самый быстрый" in plan and "'Время на см²'" in plan
    assert "max_time: maxTime.value === '' ? null : +maxTime.value" in plan and "seconds(e.time_s_per_cm2)" in start


def test_regions_without_evidence_are_counted_in_one_short_message_and_their_ids_shown_only_on_request():
    screen = source("screens/vector.js")
    assert "(${j.weak.join(', ')})" not in screen and "weakSummary(j.weak)" in screen
    assert "h('p', {class: 'small', hidden: true}, weak.join(', '))" in screen and "btn('показать'" in screen
