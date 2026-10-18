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
