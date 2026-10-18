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
                      ("/screens/corners.js", "/screens/ingest-review.js"), ("/screens/ingest-dialogs.js", "/screens/ingest-review.js"), ("/screens/ingest-upload.js", "/screens/ingest.js"),
                      ("/screens/ingest-review.js", "/screens/ingest.js"), ("/screens/knowledge.js", "/screens/colors.js"), ("/screens/artwork-start.js", "/screens/artwork.js"),
                      ("/screens/photo-form.js", "/screens/photo.js"), ("/screens/device-charts.js", "/screens/device-plots.js"), ("/screens/device-plots.js", "/screens/device.js"),
                      ("/screens/device-forms.js", "/screens/device-view.js"), ("/screens/device-view.js", "/screens/device.js"), ("/screens/device-calc.js", "/screens/device.js"),
                      ("/app.js", "/hardware.js"), ("/hardware.js", "/screens/setup-rules.js"), ("/hardware.js", "/screens/ingest-upload.js"), ("/hardware.js", "/screens/device-view.js"),
                      ("/screens/glossary-report.js", "/screens/device-report.js"), ("/screens/device-report.js", "/screens/device.js"), ("/screens/device-controller.js", "/screens/device.js"),
                      ("/screens/glossary-controller.js", "/screens/controller-rows.js"), ("/screens/controller-rows.js", "/screens/device-controller.js"),
                      ("/screens/glossary-controller.js", "/screens/device-questions.js"), ("/screens/device-questions.js", "/screens/device-view.js"),
                      ("/screens/device-character-card.js", "/screens/device.js"), ("/screens/device-lens.js", "/screens/device.js"),
                      ("/markdown.js", "/screens/research.js"), ("/screens/color-map.js", "/screens/colors.js")]:
        assert order[dep] < order[user], (dep, user)


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

