"""The path of a work's file on the work screens (feature ux-engraving-lifecycle-p0): the screen of a work made from a photograph and the
screen of a traced work draw the chain from the server's lifecycle answer, make the file through one action whose readiness comes from the
same answer, keep an edited work from claiming the verification of an older file, and take the operator back to the work after an
accepted result with a short summary. Run in node over the small DOM of ui_dom.js with the server's real answers."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_job import GREEN, WHITE, BLACK, by_colour, edit, job as traced      # noqa: F401  (fixture ``job`` as ``traced``)
from test_vector_work import GLUE, TABLES, UI, by_rgb, colouring, job, routes_of, work, PAPER    # noqa: F401  (fixtures)
from test_lifecycle import EARLY, LATE, MID, at, stamp
from test_work_review import engrave, exported
from test_work_review_ui import reviewed
from titanium_platform import work_errors

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'list.js', 'hardware.js', 'tasks.js', 'photo-modes.js', 'photo-quality.js', {code: %(glue)s}, 'screens/vector-split.js',
  'screens/vector-photo.js', 'screens/lettering.js', 'screens/vector-editor.js', 'screens/vector-colours.js', 'screens/lifecycle.js', 'screens/vector-review.js',
  'screens/vector-workspace.js', 'screens/lab-source.js', 'screens/evidence-summary.js', 'screens/vector.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
const saved = [];
ctx.document.createElement('a').constructor.prototype.click = function () { saved.push([this.getAttribute('href'), this.getAttribute('download')]); };
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const stepsOf = (root) => root.querySelectorAll('li').filter((li) => li.querySelector('.lc-name')).map((li) => li.querySelector('.lc-name').textContent + li.querySelector('.lc-word').textContent.trim());
const tabSelected = (root, name) => root.querySelectorAll('button').find((b) => b.getAttribute('id') === 'vw-tab-' + name).getAttribute('aria-selected');
(async () => {
  const out = {};
  const tree = await ctx.__screens.vector.render({query: data.query});
  await tick(); await tick();
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, plan_id, routes, body, **query):
    (tmp_path / "data.json").write_text(json.dumps({"routes": routes, "query": {"plan": str(plan_id), **query}}), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout)


def steps(*current):
    """The chain as the screen words it: the first ``current`` steps done, the next one current, the rest ahead."""
    names = ["Подготовлено", "Файл получен", "Результат добавлен", "Проверено"]
    here = names.index(current[0])
    return [n + ("(выполнено)" if i < here else "(сейчас)" if i == here else "(впереди)") for i, n in enumerate(names)]


# -- a work made from a photograph ------------------------------------------------------------------------------------------------------
@node
def test_a_photograph_work_walks_the_chain_from_prepared_to_checked_and_an_edit_after_the_file_starts_again(work, job, tmp_path):
    c, j = work, job
    stages = []

    def seen(*extra):
        routes = routes_of(c, j)
        out = run(tmp_path, j["id"], routes, """
  out.steps = stepsOf(tree);
  out.next = tree.querySelectorAll('.lc-next').map((p) => p.textContent);
  out.files = tree.querySelectorAll('summary').map((s) => s.textContent).filter((t) => t.startsWith('Прежние файлы'));
""")
        stages.append(out)
        return out

    first = seen()
    assert first["steps"] == steps("Подготовлено") and first["files"] == ["Прежние файлы"]               # nothing made yet: no count
    exported(c, j)
    second = seen()
    assert second["steps"] == steps("Файл получен") and second["files"] == ["Прежние файлы (1)"]
    pair = engrave(c, j)
    third = seen()
    assert third["steps"] == steps("Проверено") and third["files"] == ["Прежние файлы (1)"]               # accepted result of the file that was made
    colouring(c, j, op="assign", mode="random")                                                          # an edit after the verified file
    fourth = seen()
    assert fourth["steps"] == steps("Подготовлено")                                                       # nothing is inherited by the new version
    assert fourth["next"] and fourth["next"][0].startswith("Работа изменена после файла № 1: прежний файл остаётся в истории")
    exported(c, j)
    stamp(c, j, [EARLY, LATE])                                                                            # the order within one second is nobody's to read
    at(c, pair, MID)
    fifth = seen()
    assert fifth["steps"] == steps("Файл получен") and fifth["files"] == ["Прежние файлы (2)"]            # a repeat export is a new file: file 1 stays verified, file 2 is not


@node
def test_the_file_is_made_by_one_action_that_saves_it_asks_the_server_once_and_redraws_the_work(work, job, tmp_path):
    c, j = work, job
    routes = routes_of(c, j)
    routes[f"/api/vector/{j['id']}/export.lbrn2"] = {"status": 200, "text": "<xml/>", "type": "application/xml",
                                                      "headers": {"content-disposition": "attachment; filename*=UTF-8''Badge.lbrn2"}}
    out = run(tmp_path, j["id"], routes, """
  const button = byText(tree, 'button', 'Скачать LightBurn');
  out.before = [button.disabled, tree.querySelectorAll('button').filter((b) => b.textContent === 'Скачать LightBurn').length];
  out.text = tree.textContent.includes('В лазер он не отправляется');
  const a = button.dispatch('click'), b = button.dispatch('click');
  await Promise.all([a, b]); await tick(); await tick();
  out.requests = ctx.requests.filter((r) => r.path.includes('export')).map((r) => r.path);
  out.saved = saved.slice(); out.reads = ctx.requests.filter((r) => r.path === '/api/vector/__ID__').length;
  out.toast = ctx.document.body.querySelectorAll('div').filter((d) => (d.className || '').split(' ')[0] === 'toast').map((d) => d.textContent.replace(/\\s*×$/, ''));
""".replace("__ID__", str(j["id"])))
    assert out["before"] == [False, 1] and out["text"]
    assert out["requests"] == [f"/api/vector/{j['id']}/export.lbrn2"] and out["saved"] == [["blob:x", "Badge.lbrn2"]]
    assert out["reads"] == 2                                                                              # the work is read again to show the file as made
    assert out["toast"] == ["Файл создан, сохранён в работе и скачан на этот компьютер. Откройте его в LightBurn и проверьте слои"]


@node
def test_a_blocker_with_a_target_takes_the_operator_to_the_colours_where_it_is_fixed(work, job, tmp_path):
    c, j = work, job
    routes = routes_of(c, j)
    view = routes[f"/api/vector/{j['id']}"]["json"]
    view["lifecycle"]["readiness"]["ready"] = False
    view["lifecycle"]["readiness"]["blockers"] = [{"code": "weak_regions", "count": 1, "ids": ["r1"], "target": {"kind": "region", "id": "r1"}}]
    view["lifecycle"]["chain"]["next"] = {"code": "fix"}
    out = run(tmp_path, j["id"], routes, """
  await byText(tree, 'button', 'Файл LightBurn').dispatch('click').catch(() => {});
  out.disabled = byText(tree, 'button', 'Скачать LightBurn').disabled;
  out.row = tree.querySelectorAll('li').filter((li) => li.textContent.startsWith('Областей без достаточных данных')).map((li) => li.textContent);
  out.fileTab = tabSelected(tree, 'file');
  await byText(tree, 'button', 'Показать область').dispatch('click'); await tick();
  out.after = [tabSelected(tree, 'colours'), tabSelected(tree, 'file')];
""")
    assert out["disabled"] is True and len(out["row"]) == 1 and "Показать область" in out["row"][0]
    assert out["after"] == ["true", "false"]                                                             # the colours tab opens, the file tab lets go


@node
def test_back_from_an_accepted_result_the_work_tells_what_the_result_did_and_the_button_opens_the_comparison(work, job, tmp_path):
    c, j = work, job
    pair = reviewed(c, j)
    routes = routes_of(c, j)
    routes[f"/api/pairs/{pair}/work-summary"] = {"status": 200, "json": c["client"].get(f"/api/pairs/{pair}/work-summary").json()}
    out = run(tmp_path, j["id"], routes, """
  const card = tree.querySelectorAll('section').find((s) => s.getAttribute('aria-label') === 'Итог принятого результата');
  out.card = card.textContent;
  out.buttons = card.querySelectorAll('button').map((b) => b.textContent);
  out.steps = stepsOf(tree);
  await byText(card, 'button', 'Сравнить с ожиданием').dispatch('click'); await tick();
  out.tab = tabSelected(tree, 'review');
  await byText(card, 'button', 'Закрыть итог').dispatch('click'); await tick();
  out.closed = tree.querySelectorAll('section').filter((s) => s.getAttribute('aria-label') === 'Итог принятого результата').length;
""", accepted=str(pair))
    assert out["card"].startswith(f"Результат принят: «{j['name']}»") and "Основание: прогноз, сохранённый вместе с файлом № 1" in out["card"]
    assert "Сопоставлено слоёв:" in out["card"] and "Файл № 1 от этого не меняется." in out["card"]
    assert out["buttons"] == ["Сравнить с ожиданием", "Закрыть итог"] and out["steps"] == steps("Проверено")
    assert out["tab"] == "true" and out["closed"] == 0


@node
def test_a_summary_that_cannot_be_found_is_said_instead_of_an_empty_space_and_the_work_still_opens(work, job, tmp_path):
    c, j = work, job
    routes = routes_of(c, j)
    out = run(tmp_path, j["id"], routes, """
  out.text = tree.textContent.includes('Итог принятого результата не найден');
  out.cards = tree.querySelectorAll('section').filter((s) => s.getAttribute('aria-label') === 'Итог принятого результата').length;
  out.steps = stepsOf(tree);
""", accepted="999")
    assert out["text"] is True and out["cards"] == 0 and out["steps"] == steps("Подготовлено")


@node
def test_the_action_of_the_current_stage_opens_the_tab_where_it_is_done(work, job, tmp_path):
    c, j = work, job
    prepared = run(tmp_path, j["id"], routes_of(c, j), """
  const chain = tree.querySelectorAll('div').find((d) => d.className === 'vw-chain');
  out.buttons = chain.querySelectorAll('button').map((b) => b.textContent);
  await byText(chain, 'button', 'К файлу').dispatch('click'); await tick();
  out.tab = tabSelected(tree, 'file');
""")
    assert prepared["buttons"] == ["К файлу"] and prepared["tab"] == "true"
    exported(c, j)
    waiting = run(tmp_path, j["id"], routes_of(c, j), """
  const chain = tree.querySelectorAll('div').find((d) => d.className === 'vw-chain');
  out.links = chain.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
""")
    assert waiting["links"] == [["Добавить результат", f"#/ingest?plan={j['id']}"]]               # the file is made: the next thing is the result
    reviewed(c, j)
    verified = run(tmp_path, j["id"], routes_of(c, j), """
  const chain = tree.querySelectorAll('div').find((d) => d.className === 'vw-chain');
  await byText(chain, 'button', 'Сравнить с ожиданием').dispatch('click'); await tick();
  out.tab = tabSelected(tree, 'review');
""")
    assert verified["tab"] == "true"


# -- a traced work ----------------------------------------------------------------------------------------------------------------------
@node
def test_a_traced_work_with_weak_regions_cannot_make_its_file_says_which_and_opens_the_region_that_needs_a_decision(traced, tmp_path):
    c, j = traced, traced["job"]
    view = c["client"].get(f"/api/vector/{j['id']}").json()
    first = view["weak"][0]
    out = run(tmp_path, j["id"], {f"/api/vector/{j['id']}": {"status": 200, "json": view}}, """
  out.steps = stepsOf(tree);
  const button = byText(tree, 'button', 'Скачать LightBurn');
  out.disabled = button.disabled;
  const rows = tree.querySelectorAll('li').filter((li) => li.textContent.startsWith('Областей без достаточных данных')).map((li) => li.textContent);
  out.rows = rows;
  out.open = tree.querySelectorAll('.lst-det').filter((d) => !d.hidden).length;
  await byText(tree, 'button', 'Показать область').dispatch('click'); await tick(); await tick();
  out.opened = tree.querySelectorAll('.lst-det').filter((d) => !d.hidden).map((d) => d.textContent.slice(0, 40));
  out.exact = tree.textContent.includes('region(s) have no adequate evidence') || tree.textContent.includes('Точная формулировка проверки');
""")
    assert out["steps"] == steps("Подготовлено") and out["disabled"] is True and out["open"] == 0
    assert len(out["rows"]) == 1 and out["rows"][0].startswith(f"Областей без достаточных данных: {len(view['weak'])}.")
    assert len(out["opened"]) == 1 and first                                                              # the region the blocker names is open in the list
    assert out["exact"]


@node
def test_a_traced_work_made_ready_by_its_edits_makes_its_file_and_keeps_it_as_the_first_of_its_files(traced, tmp_path):
    c, j = traced, traced["job"]
    j = edit(c, j, op="delete", region=by_colour(j, WHITE)[0]["id"])
    for letter in by_colour(j, BLACK):
        j = edit(c, j, op="set_task", region=letter["id"], task="line")
    j = edit(c, j, op="exclude", region=by_colour(j, GREEN)[0]["id"])
    view = c["client"].get(f"/api/vector/{j['id']}").json()
    assert view["lifecycle"]["readiness"]["ready"] is True and view["lifecycle"]["readiness"]["kind"] == "traced"
    made = c["client"].get(f"/api/vector/{j['id']}/export.lbrn2")
    assert made.status_code == 200
    after = c["client"].get(f"/api/vector/{j['id']}").json()
    routes = {f"/api/vector/{j['id']}": {"status": 200, "json": view},
              f"/api/vector/{j['id']}/export.lbrn2": {"status": 200, "text": made.text, "type": "application/xml"}}
    out = run(tmp_path, j["id"], routes, """
  out.disabled = byText(tree, 'button', 'Скачать LightBurn').disabled;
  out.facts = tree.querySelectorAll('.lc-ready').map((r) => r.textContent)[0];
  await byText(tree, 'button', 'Скачать LightBurn').dispatch('click'); await tick(); await tick();
  out.requests = ctx.requests.filter((r) => r.path.includes('export')).map((r) => r.path); out.saved = saved.length; out.renders = ctx.__renders.length;
""")
    assert out["disabled"] is False and "Файл LightBurn: готов к выгрузке" in out["facts"] and "мм" in out["facts"] and "слоёв" in out["facts"]
    assert out["requests"] == [f"/api/vector/{j['id']}/export.lbrn2"] and out["saved"] == 1 and out["renders"] == 1
    assert after["lifecycle"]["files"][0]["number"] == 1 and after["lifecycle"]["chain"]["stage"] == "file"
    assert after["lifecycle"]["files"][0]["download_url"] == f"/api/vector/{j['id']}/exports/1"
