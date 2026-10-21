"""The browser UI is plain files served by the same process: check that what index.html loads really exists."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from titanium_platform.api.app import UI_DIR, create_app

SCRIPTS = re.findall(r'<script src="(/[^"]+)"', (UI_DIR / "index.html").read_text(encoding="utf-8"))


def test_every_script_and_the_stylesheet_that_index_html_loads_exists():
    assert len(SCRIPTS) >= 20
    for src in SCRIPTS + ["/styles.css"]:
        assert (UI_DIR / src.lstrip("/")).is_file(), src


def test_no_ui_script_is_orphaned_or_loaded_twice():
    on_disk = {"/" + str(p.relative_to(UI_DIR)) for p in UI_DIR.rglob("*.js")}
    assert set(SCRIPTS) == on_disk, (set(SCRIPTS) ^ on_disk)
    assert len(SCRIPTS) == len(set(SCRIPTS))


def test_screens_are_loaded_after_the_helpers_they_use():
    order = {s: i for i, s in enumerate(SCRIPTS)}
    for dep, user in [("/i18n.js", "/app.js"), ("/app.js", "/dialogs.js"), ("/dialogs.js", "/router.js"), ("/router.js", "/screens/setup.js"),
                      ("/screens/setup-forms.js", "/screens/setup.js"), ("/screens/setup-rules.js", "/screens/setup.js"), ("/screens/plate-dialog.js", "/screens/experiments.js"),
                      ("/photo-modes.js", "/screens/composition.js"), ("/photo-modes.js", "/screens/ingest-review.js"), ("/photo-modes.js", "/screens/photo-preview.js"),
                      ("/screens/composition.js", "/screens/ingest-review.js"), ("/screens/composition.js", "/screens/experiment.js"),
                      ("/screens/corners.js", "/screens/ingest-review.js"), ("/screens/ingest-dialogs.js", "/screens/ingest-review.js"), ("/screens/ingest-upload.js", "/screens/ingest.js"),
                      ("/screens/ingest-review.js", "/screens/ingest.js"), ("/screens/knowledge.js", "/screens/colors.js"), ("/screens/artwork-start.js", "/screens/artwork.js"),
                      ("/screens/photo-form.js", "/screens/photo.js"), ("/screens/device-charts.js", "/screens/device-plots.js"), ("/screens/device-plots.js", "/screens/device.js"),
                      ("/screens/device-forms.js", "/screens/device-view.js"), ("/screens/device-view.js", "/screens/device.js"), ("/screens/device-calc.js", "/screens/device.js"),
                      ("/app.js", "/hardware.js"), ("/hardware.js", "/screens/setup-rules.js"), ("/hardware.js", "/screens/ingest-upload.js"), ("/hardware.js", "/screens/device-view.js"),
                      ("/screens/glossary-report.js", "/screens/device-report.js"), ("/screens/device-report.js", "/screens/device.js"), ("/screens/device-controller.js", "/screens/device.js"),
                      ("/screens/glossary-controller.js", "/screens/controller-rows.js"), ("/screens/controller-rows.js", "/screens/device-controller.js"),
                      ("/screens/glossary-controller.js", "/screens/device-questions.js"), ("/screens/device-questions.js", "/screens/device-view.js"),
                      ("/screens/device-character-card.js", "/screens/device.js"), ("/screens/device-lens.js", "/screens/device.js"),
                      ("/markdown.js", "/screens/research.js"), ("/screens/color-map.js", "/screens/colors.js"),
                      ("/screens/experiment-cards.js", "/screens/device-view.js"), ("/screens/experiment-cards.js", "/screens/experiments.js"),
                      ("/hardware.js", "/screens/photo-preview.js"), ("/filepick.js", "/screens/photo-preview.js")]:
        assert order[dep] < order[user], (dep, user)


def _screen(name: str) -> str:
    return (UI_DIR / "screens" / name).read_text(encoding="utf-8")


def test_the_laser_page_shows_the_one_experiment_list_filtered_by_it_and_no_list_of_its_own():
    """REQ-028: no separate list of plates, engravings or photographs anywhere; the laser's tab is the experiment list."""
    device, view = _screen("device.js"), _screen("device-view.js")
    assert "/experiments?device_id=${id}" in device and "/devices/${id}/experiments" not in device
    assert "ExperimentCards.list(experiments" in view and "/experiments?device=" in view
    assert "source_photo_url" not in view and "item.observations" not in view
    assert "ExperimentCards.list(shown" in _screen("experiments.js") and "ctx.query.device" in _screen("experiments.js")


def test_photo_engraving_is_the_fourth_section_and_the_other_photo_screens_open_from_it():
    """REQ-059: the menu's fourth item is photo engraving; colour engraving (it is vector work) left the menu; the banded form and the
    preview by LightBurn file left it too and open from the section; every address still opens its screen."""
    router = (UI_DIR / "router.js").read_text(encoding="utf-8")
    nav = re.findall(r"\['(/[\w-]+)', '", router[router.index("const NAV"):router.index("const ROUTE_ID")])
    icons = re.findall(r"^\s+'<", router[router.index("const ICONS"):router.index("function icon")], re.M)
    assert nav[3] == "/photo-engraving" and "['/photo-engraving', 'Фотогравировка']" in router and len(icons) == len(nav)
    assert not {"/artwork", "/photo", "/photo-preview"} & set(nav)
    for route, screen, file in (("artwork", "artwork", "artwork.js"), ("photo", "photo", "photo.js"), ("'photo-preview'", "photo-preview", "photo-preview.js"),
                                ("'photo-engraving'", "photo-engraving", "photo-engraving.js")):
        assert f"{route}: '{screen}'" in router and f"App.register({{id: '{screen}'" in _screen(file)
    engraving = _screen("photo-engraving.js")
    assert "link('/photo-preview'" in engraving and "link('/photo'," in engraving and "type: 'grey_scales'" in engraving
    assert "photo: '/photo-engraving', 'photo-preview': '/photo-engraving'" in router


def test_the_menu_starts_with_experiments_the_colour_map_and_vector_work_and_every_route_still_opens():
    """vector-detail-and-colour-control, criterion 1: Vector Work is third; its addresses (#/vector, #/vector?plan=N) are unchanged."""
    router = (UI_DIR / "router.js").read_text(encoding="utf-8")
    nav = re.findall(r"\['(/[\w-]+)', '", router[router.index("const NAV"):router.index("const ROUTE_ID")])
    icons = re.findall(r"^\s+'<", router[router.index("const ICONS"):router.index("function icon")], re.M)
    assert nav[:3] == ["/experiments", "/colors", "/vector"] and len(icons) == len(nav) == len(set(nav))
    assert nav[3:] == ["/photo-engraving", "/designer", "/findings", "/devices", "/setup", "/research"]      # REQ-059: photo engraving fourth
    assert "vector: 'vector'" in router and "App.register({id: 'vector'" in _screen("vector.js")
    vector_icon = '<circle cx="5" cy="19" r="2"/><circle cx="19" cy="5" r="2"/>'
    assert vector_icon in icons_block(router, 2)                                                           # the vector icon moved with its entry


def icons_block(router: str, index: int) -> str:
    """The ``index``-th icon of the ICONS list in router.js."""
    block = router[router.index("const ICONS"):router.index("function icon")]
    return re.findall(r"^\s+('<.*>')[,\]]?\s*$", block, re.M)[index]


def test_the_findings_screen_is_in_the_menu_right_after_the_designer_with_an_icon_of_its_own():
    router = (UI_DIR / "router.js").read_text(encoding="utf-8")
    nav = re.findall(r"\['(/[\w-]+)', '", router[router.index("const NAV"):router.index("const ROUTE_ID")])
    icons = re.findall(r"^\s+'<", router[router.index("const ICONS"):router.index("function icon")], re.M)
    assert nav[nav.index("/designer") + 1] == "/findings" and len(icons) == len(nav)
    assert "['/findings', 'Выводы']" in router and "findings: 'findings'" in router
    assert "App.register({id: 'findings'" in _screen("findings.js")
    order = {s: i for i, s in enumerate(SCRIPTS)}
    assert order["/i18n-data.js"] < order["/i18n-findings.js"] < order["/app.js"]
    assert order["/screens/findings.js"] < order["/screens/designer.js"]


def test_the_findings_screen_separates_measured_conclusions_from_hypotheses_and_offers_history_schedule_and_proposals():
    """REQ-022: each finding is labelled measured, exploratory anomaly or AI hypothesis; its history, evidence and the
    schedule are on the screen; a gap can be turned into a proposal."""
    findings = _screen("findings.js")
    for text in ("'Измерено'", "'Исследовательская аномалия, не вывод'", "'Гипотеза AI, не измерение'", "'Пересчитать сейчас'",
                 "'Предложить эксперимент'", "'История вывода по расчётам'", "'Сохранить расписание'", "'Неопределённость'", "'Образцы'"):
        assert text in findings, text
    for route in ("/analysis/findings/${f.id}/history", "/analysis/findings/${f.id}/proposal", "put('/analysis/schedule'", "post('/analysis/runs')",
                  "'/analysis/' + id", "'/knowledge/' + e.knowledge_id", "'/research/' + e.session_id"):
        assert route in findings, route
    assert "f.kind !== 'gap' || !f.proposable" in findings              # only gaps the designer can plan offer a proposal
    for kind in ("improvement", "unstable", "anomaly", "gap", "hypothesis"):
        assert f"{kind}: '" in findings, kind


def test_the_designer_shows_the_question_reasons_status_and_result_of_a_proposal_and_the_ai_explanation_only_with_a_key():
    designer = _screen("designer.js")
    for text in ("prop.questions", "prop.worth", "x.rationale", "'Почему выбран'", "'Результат'", "prop.status_history", "'Отклонить'",
                 "'Принять и создать платы'", "/designer/proposals/${prop.id}/accept", "/designer/proposals/${prop.id}/reject",
                 "/designer/proposals/${prop.id}/explanation", "'Пояснение AI — гипотезы, не измерения. '", "material_id: stock.value"):
        assert text in designer, text
    assert "if (!prop.explanation_available)" in designer and "get('/designer/proposals/' + chosen.id)" in designer
    assert "/designer/proposals/${prop.id}/plates" not in designer       # plates are made by accepting the proposal
    # a photograph of a plate made for a proposal links back to it (REQ-022 AC5)
    assert "r.proposal ? link(`/designer?device=${r.proposal.device_id}" in _screen("analysis.js")
    assert "exp.plate.proposal ? h('p'" in _screen("experiment.js")


def test_an_accepted_photo_engraving_links_to_its_preview_and_a_finished_work_offers_its_file():
    experiment = _screen("experiment.js")
    assert "p.status === 'Accepted' && (p.grayscale_image || p.tonal_image)" in experiment and "/photo-preview?pair=${photoEngraving.id}" in experiment
    assert "work.lightburn_url" in experiment
    preview = _screen("photo-preview.js")
    assert "ctx.query.pair" in preview and "/lightburn`" in preview      # the work's own file, fetched, not asked for again


def test_the_photo_preview_states_camera_relative_colours_on_the_picture_itself():
    """DEC-062: the statement is drawn over the preview, not in a note below it."""
    preview = _screen("photo-preview.js")
    assert "h('div', {class: 'pp-stage'}, img, banner)" in preview and "banner.hidden = info.referenced" in preview
    css = (UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert re.search(r"\.pp-stage \{[^}]*position:relative", css) and re.search(r"\.pp-banner \{[^}]*position:absolute", css)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_every_ui_script_parses():
    for src in SCRIPTS:
        r = subprocess.run(["node", "--check", str(UI_DIR / src.lstrip("/"))], capture_output=True, text=True)
        assert r.returncode == 0, f"{src}: {r.stderr[:300]}"


def test_the_app_serves_the_ui_and_unknown_pages_fall_back_to_it(tmp_path):
    with TestClient(create_app(tmp_path / "d")) as c:
        home = c.get("/")
        assert home.status_code == 200 and "Лазерная мастерская" in home.text and 'lang="ru"' in home.text
        for src in SCRIPTS + ["/styles.css"]:
            r = c.get(src)
            assert r.status_code == 200 and len(r.content) > 50, src
        assert c.get("/some/page").text == home.text   # client-side routes fall back to index.html
        assert c.get("/api/missing").status_code == 404 and c.get("/api/missing").json()["kind"] == "not_found"


CAPTURE = re.compile(r"const \w+ = ev\.currentTarget;")


def offending_lines(source: str) -> list[str]:
    """Lines that read ``currentTarget`` other than by capturing it into a variable."""
    return [line.strip() for line in source.splitlines() if "currentTarget" in line and not CAPTURE.search(line)]


def test_event_currentTarget_is_only_read_before_the_first_await():
    """Regression: ``ev.currentTarget`` is null once a handler has awaited, so six buttons threw on their finish path.

    The only allowed use is capturing it into a variable at the top of the handler (``const self = ev.currentTarget;``).
    """
    offenders = []
    for src in SCRIPTS:
        found = offending_lines((UI_DIR / src.lstrip("/")).read_text(encoding="utf-8"))
        offenders += [f"{src}: {line[:90]}" for line in found]
    assert offenders == [], "use `const self = ev.currentTarget;` first:\n" + "\n".join(offenders)


def test_the_currentTarget_guard_flags_the_original_bug_and_accepts_the_fix():
    buggy = "try { await post('/x'); } catch (e) { fail(e); ev.currentTarget.disabled = false; }"
    fixed = "const self = ev.currentTarget;\nself.disabled = true;"
    assert offending_lines(buggy) == [buggy]
    assert offending_lines(fixed) == []
    assert offending_lines("ev.currentTarget.disabled = true;") != []   # reading it directly is flagged even before an await



NULLABLE = re.compile(r":\s*(null|undefined|false)\s*$")


def nullable_children(source: str) -> list[str]:
    """Top-level arguments of ``.replaceChildren(...)`` that can be null: the DOM inserts them as the text "null"."""
    out = []
    for m in re.finditer(r"\.replaceChildren\(", source):
        i, depth, args, cur = m.end(), 1, [], ""
        while depth and i < len(source):
            ch = source[i]
            i += 1
            if ch in "'\"`":                                  # a string: its brackets and commas are text
                end = i
                while end < len(source) and source[end] != ch:
                    end += 2 if source[end] == "\\" else 1
                cur += source[i - 1:end + 1]
                i = end + 1
                continue
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            if depth == 1 and ch == ",":
                args.append(cur)
                cur = ""
            elif depth:
                cur += ch
        args.append(cur)
        out += [a.strip() for a in args if not a.strip().startswith("...")
                and (NULLABLE.search(a.strip()) or (re.match(r"^[\w.!()]+\s*&&", a.strip()) and "?" not in a))]
    return out


def test_no_screen_passes_a_possibly_null_child_to_replaceChildren():
    """Regression: the colour search printed "null" above the film card. ``h()`` skips null children, the DOM's
    ``replaceChildren`` does not; ``App.fill(el, ...)`` replaces children the way ``h()`` appends them."""
    offenders = []
    for src in SCRIPTS:
        offenders += [f"{src}: {arg[:90]}" for arg in nullable_children((UI_DIR / src.lstrip("/")).read_text(encoding="utf-8"))]
    assert offenders == [], "use App.fill(el, ...) for children that can be null:\n" + "\n".join(offenders)


def test_the_null_child_guard_flags_the_original_bug_and_accepts_the_fix():
    buggy = "results.replaceChildren(h('h3', {}, 'a, (b'), r.n && !f.within ? h('div') : null, film ? card(film) : null);"
    assert nullable_children(buggy) == ["r.n && !f.within ? h('div') : null", "film ? card(film) : null"]
    assert nullable_children("fill(results, h('h3'), film ? card(film) : null);") == []
    assert nullable_children("el.replaceChildren(...items.map((x) => (x ? h('p') : null)), h('p', {}, ok ? 'a' : 'b'));") == []
    assert nullable_children("el.replaceChildren(h('p'), shown && h('div'));") == ["shown && h('div')"]


def test_ui_files_are_revalidated_so_an_upgrade_takes_effect_on_reload(tmp_path):
    """Regression: without Cache-Control a reloaded tab kept the old screen scripts after they changed."""
    with TestClient(create_app(tmp_path / "d")) as c:
        for path in ("/", "/index.html", "/styles.css", "/app.js", "/screens/designer.js", "/some/client/route"):
            r = c.get(path)
            assert r.status_code == 200 and r.headers.get("cache-control") == "no-cache", path
        etag = c.get("/styles.css").headers["etag"]
        assert c.get("/styles.css", headers={"If-None-Match": etag}).status_code == 304   # still cheap when unchanged


def test_fields_and_buttons_in_one_line_use_the_bottom_aligned_toolbar():
    """Regression: in a centred flex row the button sat 14 px above the inputs (the label pushes the input down)."""
    css = (UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert re.search(r"\.toolbar \{[^}]*align-items:flex-end", css)
    offenders = []
    for src in SCRIPTS:
        for n, line in enumerate((UI_DIR / src.lstrip("/")).read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"class: '(card )?row'\}, (field\(|h\('div', \{(style: 'min-width|class: 'f-wrap))", line):
                offenders.append(f"{src}:{n}")
    assert offenders == [], "a row starts with a labelled field; use class 'toolbar':\n" + "\n".join(offenders)


def test_the_split_settings_share_one_top_line_and_the_card_has_no_empty_bands():
    """Regression (0.7.0 screenshot): the bottom-aligned toolbar put four labels at four heights because only some fields have a hint, and the
    empty warning block and the paragraph margins added bands of 30-60 px between the blocks of the colours card."""
    css = (UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert re.search(r"\.vw-split-fields \{[^}]*align-items:start", css)
    assert re.search(r"\.vw-split-actions \{[^}]*align-items:center", css)
    assert re.search(r"\.vw-colours>div:empty \{display:none\}", css)
    assert re.search(r"\.vw-colours>p,[^{]*\.vw-split>h4[^{]*\{margin:0\}", css)
    source = (UI_DIR / "screens" / "vector-split.js").read_text(encoding="utf-8")
    assert "vw-split-fields" in source and "vw-split-actions" in source and "class: 'toolbar'" not in source


def test_rig_repeatability_is_shown_with_the_stability_data():
    """REQ-009: computed for every recipe and every re-photographed engraving, it must reach the screens that show stability."""
    for screen in ("screens/knowledge.js", "screens/analysis.js"):
        text = (UI_DIR / screen).read_text(encoding="utf-8")
        assert "rig_repeatability" in text and "Повторяемость стенда" in text, screen
        assert "по эталонной карте" in text, screen         # says it exists only for chart-corrected re-photographs


def test_every_file_input_is_shown_through_the_russian_file_picker():
    """Regression: the native file input showed 'Choose File / no file selected' in English, off-centre in its box."""
    pattern = re.compile(r"field\('[^']*', (\w+)\)")
    offenders = []
    for src in SCRIPTS:
        text = (UI_DIR / src.lstrip("/")).read_text(encoding="utf-8")
        file_vars = set(re.findall(r"const (\w+) = h\('input', \{type: 'file'", text))
        for var in file_vars:
            if f"App.filePick({var}" not in text:
                offenders.append(f"{src}: {var}")
        offenders += [f"{src}: {m} passed raw to field()" for m in pattern.findall(text) if m in file_vars]
    assert offenders == [], "wrap file inputs with App.filePick(input, label):\n" + "\n".join(offenders)
    css = (UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".file-field>input.file-native" in css and "opacity:0" in css   # the real input stays clickable on top

