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
