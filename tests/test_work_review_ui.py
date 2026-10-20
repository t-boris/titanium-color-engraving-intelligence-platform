"""The "Result" tab of a work, its marks in the list of works and its block in the report of a photograph (DEC-090, proposed): what the
file promised against what the engraving measured, the layers whose colour moved with a replacement offered, run in node over the small DOM
of the other screen tests with the server's real answers."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import GLUE, PAPER, TABLES, UI, by_rgb, colouring, job, lab, palette_ids, work    # noqa: F401  (fixtures)
from test_work_review import engrave, exported, moved
from titanium_platform import work_errors

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context({});
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'hardware.js', {code: %(glue)s}, 'screens/vector-review.js', {code: 'globalThis.VR = VectorReview;'}]);
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const VR = ctx.VR, ran = [];
const run = async (op) => { ran.push(op); return true; };
(async () => {
  const out = {};
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, payload, body):
    (tmp_path / "data.json").write_text(json.dumps(payload), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


def reviewed(c, j):
    """The work after a file and an engraving of it whose first layer came out 9 L* darker; the pair."""
    plan = exported(c, j)
    first = plan["layers"][0]["lab"]
    pair = engrave(c, j, labs={0: [first[0] - 9, *first[1:]]})
    work_errors.after_acceptance(c["store"], pair)
    return pair


@node
def test_the_tab_shows_what_came_out_against_what_was_promised_with_both_pictures_and_the_causes_on_demand(work, job, tmp_path):
    c, j = work, job
    pair = reviewed(c, j)
    payload = c["client"].get(f"/api/vector/{j['id']}").json()
    out = run(tmp_path, {"job": payload}, """
  const view = VR.view(data.job, run);
  out.text = view.textContent;
  out.rows = view.querySelectorAll('button').filter((b) => (b.className || '').includes('vw-review-row')).map((b) => b.textContent);
  out.pictures = view.querySelectorAll('img').map((i) => i.getAttribute('src'));
  out.label = VR.tabLabel(data.job);
  await view.querySelectorAll('button').find((b) => (b.className || '').includes('vw-review-row')).dispatch('click');
  out.dialog = ctx.document.body.querySelector('.modal').textContent;
""")
    review = payload["reviews"][0]
    assert "Результат гравировки" in out["text"] and f"Совпало слоёв {review['summary']['matched']} из {review['summary']['promised']} обещанных" in out["text"]
    assert len(out["rows"]) == review["summary"]["matched"] and out["rows"][0].find("ΔE") > 0                      # the worst layer first
    assert any("promised=true" in s for s in out["pictures"]) and any("promised=false" in s for s in out["pictures"])
    assert all(f"engraving={review['engraving_id']}" in s for s in out["pictures"]) and out["label"] == "Результат"
    assert "Обещано" in out["dialog"] and "Получилось" in out["dialog"] and "ΔE" in out["dialog"]
    assert pair


@node
def test_a_work_with_nothing_to_compare_says_what_to_do_and_a_file_never_made_promises_nothing(work, job, tmp_path):
    payload = work["client"].get(f"/api/vector/{job['id']}").json()
    out = run(tmp_path, {"job": payload}, """
  const view = VR.view(data.job, run);
  out.text = view.textContent;
""")
    assert "Фото результата по этой работе ещё не принято" in out["text"] and "Файл из этой работы ещё не создавали" in out["text"]


@node
def test_a_moved_layer_is_listed_with_the_replacement_and_the_button_sends_an_ordinary_edit(work, job, tmp_path):
    c, j = work, job
    ids = palette_ids(c)
    fast, exact = ids[(round(lab(PAPER)[0] - 2), 3000)], ids[(round(lab(PAPER)[0]), 500)]
    j = colouring(c, j, op="set_colour", colour=by_rgb(j, PAPER)["index"], entry_id=fast)
    exported(c, j)
    moved(c, j, fast)
    payload = c["client"].get(f"/api/vector/{j['id']}").json()
    proposal = next(p for p in payload["attention"]["layers"][0]["proposals"] if p["entry_id"])
    payload["attention"]["layers"][0]["proposals"].append({**proposal, "colour": 99})                       # a second replacement: "apply all" is offered
    out = run(tmp_path, {"job": payload}, """
  const view = VR.view(data.job, run);
  out.text = view.textContent;
  out.label = VR.tabLabel(data.job);
  await byText(view, 'button', 'Заменить').dispatch('click'); await tick();
  out.one = ran.splice(0);
  await view.querySelectorAll('button').find((b) => b.textContent.startsWith('Применить все замены')).dispatch('click'); await tick(); await tick();
  out.all = ran.splice(0);
""")
    assert "ушёл от обещанного" in out["text"] and out["label"] == "Результат · ⚠ 1"
    assert out["one"] == [{"op": "set_colour", "colour": proposal["colour"], "entry_id": exact}]
    assert [op["colour"] for op in out["all"]] == [proposal["colour"], 99] and all(op["entry_id"] == exact for op in out["all"])
    assert "Выгравированный файл не меняется" in out["text"]


@node
def test_the_list_and_the_report_carry_the_conclusion(work, job, tmp_path):
    c, j = work, job
    pair = reviewed(c, j)
    listed = next(w for w in c["client"].get("/api/vector").json() if w["id"] == j["id"])
    report = c["client"].get(f"/api/pairs/{pair}/report").json()
    out = run(tmp_path, {"listed": listed, "report": report}, """
  out.lines = VR.cardLines(data.listed).map((p) => p.textContent);
  const card = VR.reportCard(data.report.work_review);
  out.card = card.textContent;
  out.link = card.querySelectorAll('a').map((a) => a.getAttribute('href'));
  out.none = VR.reportCard(null);
""")
    assert any("Результат гравировки (IMG_1.DNG)" in line for line in out["lines"])
    assert f"Вывод по работе «{job['name']}»" in out["card"] and out["link"] == [f"#/vector?plan={j['id']}"] and out["none"] is None
