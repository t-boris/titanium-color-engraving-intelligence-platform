"""«Новая векторная работа» and the delta E tolerance (0.22.4): the tolerance is never invented, so the form shows at once whether the
rules of the chosen laser and lens hold one; with none it asks for it before anything is sent and saves the typed value to the rules
(«Запомнить», on by default); with one it names it and a typed value is for the work only. Run in node over the small DOM of the
other screen tests."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import GLUE, TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

FORM_DATA = "globalThis.FormData = class { constructor() { this.items = []; } append(k, v) { this.items.push([k, String(v)]); } };"
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'list.js', 'hardware.js', 'filepick.js', 'tasks.js', 'photo-modes.js', 'photo-quality.js', {code: %(glue)s}, 'screens/vector-split.js', 'screens/vector-photo.js', 'screens/lettering.js',
  'screens/vector-editor.js', 'screens/vector-colours.js', 'screens/vector-review.js', 'screens/vector-workspace.js', 'screens/lab-source.js', 'screens/vector.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
(async () => {
  const out = {};
  const tree = await ctx.__screens.vector.render({query: {new: '1'}});
  await tick(); await tick();
  const field = tree.querySelectorAll('div').find((d) => d.classList.contains('f') && (d.querySelector('span') || {}).textContent === 'Допуск ΔE');
  const thr = field.querySelector('input');
  const remember = field.querySelectorAll('label').find((l) => l.classList.contains('row'));
  const sent = () => ctx.requests.filter((r) => r.method !== 'GET').map((r) => [r.method, r.path, typeof r.body === 'string' ? JSON.parse(r.body) : r.body.items]);
  out.shown = [thr.getAttribute('placeholder'), thr.getAttribute('aria-invalid'), field.textContent, remember.hidden];
  const stockOf = () => tree.querySelectorAll('label').find((l) => (l.querySelector('span') || {}).textContent === 'Титан').textContent;
  const strategy = tree.querySelectorAll('select').find((sel) => sel.getAttribute('aria-label') === 'Стратегия');
  out.stock = [stockOf()];
  strategy.value = 'fill'; await strategy.dispatch('change'); out.stock.push(stockOf());
  strategy.value = 'photo'; await strategy.dispatch('change'); await tick();
  tree.querySelectorAll('input').find((i) => i.getAttribute('type') === 'file').files = [{name: 'Inna Portrait.jpg'}];
  await byText(tree, 'button', 'Создать работу').dispatch('click'); await tick();
  out.empty = [tree.querySelectorAll('p').find((p) => p.getAttribute('role') === 'alert').textContent, sent()];
  thr.value = '5'; await thr.dispatch('input');
  out.typed = thr.getAttribute('aria-invalid');
  await byText(tree, 'button', 'Создать работу').dispatch('click'); await tick(); await tick();
  out.created = sent();
  out.after = [thr.getAttribute('placeholder'), remember.hidden];
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def routes(tolerance) -> dict:
    ok = lambda body, status=200: {"status": status, "json": body}  # noqa: E731
    return {"/api/devices": ok([{"id": 1, "name": "JPT", "title": "JPT YDFLP-E-60", "lens": {"id": 2}}]),
            "/api/lenses": ok([{"id": 2, "kind": "F-Theta", "focal_length_mm": 174}]),
            "/api/materials": ok([{"id": 3, "name": "Small Plate", "grade": "Grade 5", "batch": "Chineese order"}]),
            "/api/vector-palette": ok({"entries": []}),
            "/api/rules": ok({"repeat_threshold": None, "delta_tolerance": tolerance, "variance_threshold": None, "criteria_agreed": False}),
            "/api/vector": ok({"id": 99}, 201)}


def run(tmp_path, tolerance) -> dict:
    (tmp_path / "data.json").write_text(json.dumps({"routes": routes(tolerance)}), encoding="utf-8")
    script = tmp_path / "form.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE + FORM_DATA)}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


@node
def test_with_no_tolerance_saved_the_form_asks_for_it_first_and_saves_the_typed_one_to_the_rules(tmp_path):
    out = run(tmp_path, None)
    placeholder, invalid, text, hidden = out["shown"]
    assert placeholder == "задайте" and invalid == "true" and hidden is False
    assert "Для этого лазера с линзой допуск не сохранён — задайте его" in text and "5 — две гравировки одного рецепта ещё совпадают" in text
    assert "Запомнить для этого лазера с линзой" in text
    assert out["empty"] == ["Задайте допуск ΔE: для этого лазера с линзой он не сохранён", []]          # nothing is sent
    assert out["typed"] == "false"
    (put, rules, body), (post, path, items) = out["created"]
    assert (put, rules, body) == ("PUT", "/api/rules", {"device_id": 1, "lens_id": 2, "delta_tolerance": 5})
    assert (post, path) == ("POST", "/api/vector") and ["threshold", "5"] in items
    assert out["after"] == ["из правил: 5", True]
    assert out["stock"][0].endswith("цвета — измерения титана этой марки с любой его пластины")             # «Фото»: every plate of the grade
    assert out["stock"][1].endswith("рецепты — только измеренные на этой заготовке")                         # a silhouette: this plate


@node
def test_with_a_tolerance_saved_the_form_names_it_and_sends_nothing_to_the_rules(tmp_path):
    out = run(tmp_path, 5.0)
    placeholder, invalid, text, hidden = out["shown"]
    assert placeholder == "из правил: 5" and invalid == "false" and hidden is True
    assert "пусто — ΔE 5 из правил этого лазера с линзой; число здесь — только для этой работы" in text
    assert out["empty"][1][0][:2] == ["POST", "/api/vector"] and ["threshold", "5"] not in out["empty"][1][0][2]   # empty: the rules decide
    assert [r[:2] for r in out["created"]] == [["POST", "/api/vector"], ["POST", "/api/vector"]]                 # never the rules
