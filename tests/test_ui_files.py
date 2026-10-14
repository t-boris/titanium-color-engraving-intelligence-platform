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
                      ("/screens/photo-form.js", "/screens/photo.js")]:
        assert order[dep] < order[user], (dep, user)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_every_ui_script_parses():
    for src in SCRIPTS:
        r = subprocess.run(["node", "--check", str(UI_DIR / src.lstrip("/"))], capture_output=True, text=True)
        assert r.returncode == 0, f"{src}: {r.stderr[:300]}"


def test_the_app_serves_the_ui_and_unknown_pages_fall_back_to_it(tmp_path):
    with TestClient(create_app(tmp_path / "d")) as c:
        home = c.get("/")
        assert home.status_code == 200 and "Цвет титана" in home.text and 'lang="ru"' in home.text
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

