"""The findings screen («Выводы», REQ-022) as a short list the operator manages (feature findings-you-can-manage-short-lists-re-check
REQ-002, REQ-003): one line per finding, opened on «Требуют внимания», chips with counts, a page of 20 from the server, «Учтено», «Скрыть»,
«Закрепить» and a note, the details under the row, a link to one finding. Its photo engraving tab (feature photo-engraving-quality REQ-003,
REQ-005): on every laser and titanium where a photo engraving was photographed, the best measured settings of each kind, what each setting
does there and the plate the laboratory proposes. Run in node over the small DOM of the other screen tests, with answers shaped like the
server's."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI
from titanium_platform import findings as fd

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

GLUE = ("const __screens = {}; App.register = (d) => { __screens[d.id] = d; }; App.render = () => {};"
        "globalThis.__screens = __screens; App.go = (route) => { location.hash = '#' + route; };")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'photo-modes.js', 'photo-quality.js', 'dialogs.js', 'list.js', 'hardware.js', 'tasks.js', {code: %(glue)s},
  'screens/source-refs.js', 'screens/findings.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
(async () => {
  const out = {};
  const tree = await ctx.__screens.findings.render({query: data.query || {}});
  await tick(); await tick();
  const tab = (name) => tree.querySelectorAll('button').find((b) => b.getAttribute('role') === 'tab' && b.textContent === name);
  const panel = (name) => tree.querySelectorAll('div').find((d) => d.getAttribute('role') === 'tabpanel' && d.getAttribute('aria-labelledby') === tab(name).getAttribute('id'));
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""

JARVIS = {"dither": "jarvis", "power": 30.0, "min_power": 30.0, "speed": 125.0, "frequency": 60.0, "pulse_width": 200.0, "line_interval": 0.01,
          "passes": 1, "global_passes": 1, "dot_width": None}
EVERYWHERE = [{"device_id": 1, "lens_id": 2, "material_id": 3, "setup": "JPT M7 · F-Theta", "titanium": "Grade 5 sheet · Grade 5", "picture_from": None, "kinds": [
    {"kind": "jarvis", "status": "measured", "engravings": 2,
     "best": {"settings": JARVIS, "score": 0.62, "source": {"pair_id": 41, "layer": "C1"}},
     "effects": {"power": {"per": "doubling", "photographs": [41, 42], "mean_L": {"median": -6.0, "n": 2}, "score": {"median": -0.1, "n": 2}}},
     "proposal": {"kind": "around", "centre": JARVIS, "step": 1.0, "source": {"pair_id": 41, "layer": "C1"},
                  "copies": [[], [{"setting": "power", "from": 30.0, "to": 24.0}]], "plate": None}}]}]


def queued(places):
    """The photo queue as the server gives it: each kind with the one next step the server's rules recommend for it."""
    return [{**place, "kinds": [{**k, "recommendation": fd.photo_recommend(k)} for k in place["kinds"]]} for place in places]


ROUTES = {
    "/api/analysis/runs": {"status": 200, "json": []},
    "/api/analysis/schedule": {"status": 200, "json": {"interval_hours": 0, "next_due_at": None, "running": False}},
    "/api/application-goals": {"status": 200, "json": []},
    "/api/analysis/runs/latest": {"status": 200, "json": {"run": None, "findings": [], "total": 0,
                                                          "options": {"kinds": [], "tasks": [], "setups": [], "stocks": []}}},
    "/api/analysis/photo-queue": {"status": 200, "json": queued(EVERYWHERE)},
    "/api/recheck/latest": {"status": 200, "json": None},
    "/api/exclusions": {"status": 200, "json": {"exclusions": [], "active": 0}},
}


def run(tmp_path, body, routes=None, query=None) -> dict:
    (tmp_path / "data.json").write_text(json.dumps({"routes": routes or ROUTES, "query": query or {}}), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


@node
def test_the_findings_say_what_each_setting_does_to_a_photo_engraving_on_every_laser_and_titanium_photographed(tmp_path):
    out = run(tmp_path, """
  await tab('Фотогравировка').dispatch('click'); await tick();
  const section = panel('Фотогравировка');
  out.hidden = section.hidden; out.hash = ctx.location.hash;
  out.rows = section.querySelectorAll('.lst-main').map((x) => x.textContent);
  out.cards = section.querySelectorAll('article').map((a) => a.textContent);
  out.buttons = section.querySelectorAll('button').filter((b) => !b.closest('.lst-bar')).map((b) => b.textContent);
""")
    assert out["hidden"] is False and out["hash"] == "#/findings?tab=photo"
    assert out["rows"] == ["JPT M7 · F-Theta · Grade 5 sheet · Grade 5измерено видов: 1 из 1есть предложениеДальше: Jarvis — измерено, но не подобрано"]   # one place: open at once
    jarvis, = out["cards"]
    assert jarvis.startswith("Jarvisизмерено, но не подобрано")
    assert "Лучшее: 30 %, 125 мм/с, 60 кГц, 200 нс, шаг 0,01 мм — автоматическая оценка 0,62 по фото №41" in jarvis
    assert "мощность вдвое больше: темнее на 6 L*, оценка −0,1 (по фото №41, №42)" in jarvis
    assert "мощность 30 % → 24 %" in jarvis and "Картинки для платы ещё нет" in jarvis
    assert out["buttons"] == ["Открыть фото № 41"]               # the row's one step; no picture to engrave the plate from yet: no plate to press


@node
def test_a_kind_that_came_out_a_negative_on_a_titanium_is_counted_and_its_card_says_why(tmp_path):
    flop = {"settings": {"dither": "atkinson", "power": 15.0}, "black_lab": [74.1, 5.6, 36.7], "tone": {"range_L": -7.1},
            "source": {"pair_id": 143, "layer": "C22"}}
    faint = {"settings": {"dither": "atkinson", "power": 8.0}, "black_lab": [70.0, 0.0, 0.0], "tone": {"range_L": 4.2},
             "source": {"pair_id": 120, "layer": "C3"}}
    failed = {"kind": "atkinson", "status": "failed", "engravings": 2, "best": None, "failed": [flop, faint], "effects": {}, "proposal": None}
    place = {**EVERYWHERE[0], "kinds": [*EVERYWHERE[0]["kinds"], failed]}
    out = run(tmp_path, """
  await tab('Фотогравировка').dispatch('click'); await tick();
  const section = panel('Фотогравировка');
  out.rows = section.querySelectorAll('.lst-main').map((x) => x.textContent);
  out.cards = section.querySelectorAll('article').map((a) => a.textContent);
""", routes={**ROUTES, "/api/analysis/photo-queue": {"status": 200, "json": queued([place])}})
    assert out["rows"] == ["JPT M7 · F-Theta · Grade 5 sheet · Grade 5измерено видов: 1 из 2не получилось видов: 1есть предложениеДальше: Atkinson — не получился"]
    card = out["cards"][1]
    assert card.startswith("Atkinsonне получился")
    assert ("«Atkinson» на этом титане не получился: фото № 143, 15 % — точки не темнее титана (L* 74): картинки не видно или она вышла "
            "негативом; фото № 120, 8 % — картинка едва видна: тёмное темнее светлого всего на 4 L*.") in card
    assert "Нужны точки темнее титана: по опыту процесса — больше мощность, меньше скорость или шаг строк." in card


@node
def test_without_a_photographed_photo_engraving_the_findings_have_no_photo_tab(tmp_path):
    out = run(tmp_path, """
  out.tabs = tree.querySelectorAll('button').filter((b) => b.getAttribute('role') === 'tab').map((b) => b.textContent);
""", routes={**ROUTES, "/api/analysis/photo-queue": {"status": 200, "json": []}})
    assert out["tabs"] == []


# -- the findings as a short list the operator manages ------------------------------------------------------------------------
RUN = {"id": 63, "at": "2026-10-25T08:52:00+00:00", "trigger": "acceptance", "previous_run_id": 62,
       "inputs": {"accepted_pairs": 31, "eligible_observations": 794, "knowledge_entries": 669, "targets": 2, "insights": 3, "unset_rules": []},
       "counts": {"anomaly": 45, "unstable": 32, "gap": 10, "improvement": 5, "hypothesis": 3}}
CONTEXT = {"device_id": 1, "device": "JPT M7", "lens": {"id": 2, "name": "F-Theta 174", "focal_length_mm": 174, "field_mm": 170},
           "stock": {"name": "Grade 2 sheet", "grade": "Grade 2"}}


def finding(fid, kind, subkind, statement, state="attention", pinned=False, note=None, changed=False, new=False, deviation=None,
            remedies=(), proposable=False):
    f = {"id": fid, "run_id": 63, "key": f"k{fid}", "kind": kind, "subkind": subkind, "basis": "measured" if kind != "anomaly" else "exploratory",
            "statement": statement, "device_id": 1, "lens_id": 2, "material_id": 3, "task": "fill", "context": CONTEXT, "new": new,
            "samples": {"independent_engravings": 3, "photographs": 3}, "uncertainty": {}, "evidence": {"pair_ids": [41]},
            "compares": {"observation_lab": [70, 0, 0], "reference_lab": [51, 0, 0], "rule": "tolerance", "delta_e": deviation, "tolerance": 10}
            if subkind == "observation" else {"tasks_on_this_stock": ["fill"], "stocks_with_this_task": [], "lenses_with_this_task": [], "names": {"stocks": {}, "lenses": {}}}
            if subkind == "coverage" else {"stage": "production", "doubt_observation_ids": [3]},
            "limitations": [], "setup": "laser:1/lens:2", "stock_key": "3", "deviation": deviation, "state": state,
            "mark": {"status": None if state == "attention" and not changed else (state if state != "attention" else "hidden"), "pinned": pinned,
                     "note": note, "status_at": "2026-10-24T10:00:00+00:00" if state != "attention" or changed else None, "changed": changed},
         "remedies": list(remedies), "proposable": proposable}
    return {**f, "recommendation": fd.recommend(f)}                       # what the server would say, from its own rules


PAGE = {"run": RUN, "matched": 85, "total": 95,
        "findings": [finding(7, "anomaly", "observation", "Аномалия слоя C1", pinned=True, note="проверить", deviation=19.04,
                             remedies=[{"action": "exclude_measurement", "observation_id": 3063}, {"action": "remeasure", "pair_id": 41}, {"action": "count_from_latest"}]),
                     finding(8, "unstable", "questioned", "Сомнение в знании № 12", changed=True, deviation=2.5,
                             remedies=[{"action": "count_from_latest"}, {"action": "confirm_questioned", "knowledge_id": 12}]),
                     finding(9, "gap", "coverage", "Нет линий на этом титане", new=True, proposable=True)],
        "counts": {"state": {"": 95, "attention": 85, "acknowledged": 6, "hidden": 4, }, "kind": {"": 85, "anomaly": 40, "unstable": 30, "gap": 10,
                                                                                               "improvement": 5, "hypothesis": 0}},
        "options": {"kinds": ["anomaly", "unstable", "gap", "improvement", "hypothesis"], "tasks": ["fill", "line"],
                    "setups": [{"key": "laser:1/lens:2", "device": "JPT M7", "lens": CONTEXT["lens"]}],
                    "stocks": [{"key": "3", "stock": CONTEXT["stock"]}]}}
LIST_ROUTES = {**ROUTES, "/api/analysis/runs": {"status": 200, "json": [RUN]}, "/api/analysis/runs/latest": {"status": 200, "json": PAGE},
               "/api/analysis/findings/8/mark": {"status": 200, "json": {"status": "hidden"}},
               "/api/analysis/findings/7": {"status": 200, "json": finding(7, "anomaly", "observation", "Аномалия слоя C1", pinned=True)}}


@node
def test_the_acknowledged_and_hidden_chips_are_offered_even_before_anything_is_marked(tmp_path):
    """REQ-002: the state chips «Требуют внимания · Учтённые · Скрытые · Все» are always there, so the operator sees where a hidden
    finding goes before hiding one."""
    page = {**PAGE, "counts": {**PAGE["counts"], "state": {"": 85, "attention": 85, "acknowledged": 0, "hidden": 0}}}
    out = run(tmp_path, """
  out.chips = panel('Выводы').querySelectorAll('.lst-chip').map((c) => c.textContent).slice(0, 4);
""", routes={**LIST_ROUTES, "/api/analysis/runs/latest": {"status": 200, "json": page}})
    assert out["chips"] == ["All · 85", "Требуют внимания · 85", "Учтённые · 0", "Скрытые · 0"]


@node
def test_the_findings_open_on_those_needing_attention_one_line_each_with_chips_counted_by_the_server(tmp_path):
    out = run(tmp_path, """
  const list = panel('Выводы');
  out.asked = ctx.requests.filter((r) => r.path === '/api/analysis/runs/latest').map((r) => r.url);
  out.run = tree.querySelector('.fd-run').querySelector('.row').textContent;
  out.chips = list.querySelectorAll('.lst-chip').map((c) => c.textContent);
  out.pressed = list.querySelectorAll('.lst-chip').filter((c) => c.getAttribute('aria-pressed') === 'true').map((c) => c.textContent);
  out.rows = list.querySelectorAll('.lst-main').map((r) => r.textContent);
  out.actions = list.querySelectorAll('.lst-act').map((a) => a.querySelectorAll('button').map((b) => b.textContent));
  out.recommended = list.querySelectorAll('.lst-act').map((a) => a.querySelectorAll('button').filter((b) => (b.className || '').split(' ').includes('fd-recommended')).length);
  out.count = list.querySelector('.lst-count').textContent;
  out.more = list.querySelector('.lst-foot').textContent;
  out.cards = list.querySelectorAll('article').length;
""", routes=LIST_ROUTES)
    assert out["asked"] == ["/api/analysis/runs/latest?state=attention&sort=important&offset=0&limit=20"]
    assert out["run"].startswith("Расчёт № 63") and out["run"].endswith("после принятия фотографииПересчитать сейчасПерепроверить все работы")
    assert out["chips"] == ["All · 95", "Требуют внимания · 85", "Учтённые · 6", "Скрытые · 4",
                            "All · 85", "Улучшения · 5", "Нестабильность · 30", "Аномалии · 40", "Пробелы · 10"]   # no AI hypothesis to show
    assert out["pressed"] == ["Требуют внимания · 85", "All · 85"]
    assert out["rows"] == ["📌АномалияАномалия слоя C1JPT M7 · Grade 2 sheet · Grade 2 · FillΔE 19.0✎ проверить",       # the problem, what it concerns, the note
                           "НестабильноСомнение в знании № 12JPT M7 · Grade 2 sheet · Grade 2 · FillΔE 2.5изменился",
                           "ПробелНет линий на этом титанеJPT M7 · Grade 2 sheet · Grade 2 · Fillновое"]
    assert out["actions"] == [["Перемерить фото", "Учтено", "Скрыть", "Заметка", "Открепить"],                    # ONE recommended step first, the queue's controls after it
                              ["Открыть основания", "Учтено", "Скрыть", "Заметка", "Закрепить"],
                              ["Предложить эксперимент", "Учтено", "Скрыть", "Заметка", "Закрепить"]]
    assert out["recommended"] == [1, 1, 1]                                                                   # exactly one button is the recommended one
    assert out["count"] == "showing 3 of 85" and out["more"] == "Show 20 more" and out["cards"] == 0   # details only when a row opens


@node
def test_hiding_a_finding_marks_it_by_the_server_and_reads_the_page_again(tmp_path):
    out = run(tmp_path, """
  const list = panel('Выводы');
  const before = ctx.requests.length;
  await list.querySelectorAll('.lst-act')[1].querySelectorAll('button').find((b) => b.textContent === 'Скрыть').dispatch('click'); await tick(); await tick();
  out.sent = ctx.requests.slice(before).map((r) => [r.method, r.url, r.body || null]);
  out.toast = ctx.document.body.querySelectorAll('.toast').map((t) => t.textContent);
""", routes=LIST_ROUTES)
    assert out["sent"] == [["POST", "/api/analysis/findings/8/mark", '{"action":"hide"}'],
                           ["GET", "/api/analysis/runs/latest?state=attention&sort=important&offset=0&limit=20", None]]
    assert out["toast"] == ["Скрыто до новых данных: вывод можно найти в «Скрытых». ×"]


@node
def test_the_note_action_opens_the_row_with_the_cursor_in_the_note(tmp_path):
    """REQ-003: «Заметка» on a row opens the finding under it and puts the cursor in the operator's note."""
    out = run(tmp_path, """
  const list = panel('Выводы');
  await list.querySelectorAll('.lst-act')[1].querySelectorAll('button').find((b) => b.textContent === 'Заметка').dispatch('click'); await tick(); await tick();
  const open = list.querySelectorAll('.lst-det').filter((d) => !d.hidden);
  out.open = open.length; out.focused = open.length ? !!open[0].querySelector('textarea').focused : null;
  out.expanded = list.querySelectorAll('.lst-main').map((m) => m.getAttribute('aria-expanded'));
""", routes=LIST_ROUTES)
    assert out["open"] == 1 and out["focused"] is True and out["expanded"] == ["false", "true", "false"]


@node
def test_a_row_opens_its_mark_its_note_and_the_full_finding_and_the_choices_go_to_the_address(tmp_path):
    out = run(tmp_path, """
  const list = panel('Выводы');
  await list.querySelectorAll('.lst-main')[1].dispatch('click'); await tick();
  const open = list.querySelectorAll('.lst-det').find((d) => !d.hidden);
  out.status = open.querySelector('.fd-mark').querySelector('p').textContent;
  out.card = open.querySelector('article').textContent;
  await list.querySelectorAll('.lst-chip').find((c) => c.textContent.startsWith('Скрытые')).dispatch('click'); await tick();
  out.hash = ctx.location.hash;
  out.last = ctx.requests.filter((r) => r.path === '/api/analysis/runs/latest').map((r) => r.url).pop();
""", routes=LIST_ROUTES)
    assert out["status"].startswith("Был скрыт 24.10.2026, ")                    # the hour as this computer's clock shows it
    assert out["status"].endswith("; с тех пор появились новые данные, вывод снова требует внимания.")
    assert "Измерено" in out["card"] and "Сомнение в знании № 12" in out["card"] and "Образцы" in out["card"]
    assert out["hash"] == "#/findings?state=hidden"
    assert out["last"] == "/api/analysis/runs/latest?state=hidden&sort=important&offset=0&limit=20"


@node
def test_a_link_to_one_finding_opens_it_above_the_list(tmp_path):
    out = run(tmp_path, """
  const linked = tree.querySelector('.fd-linked');
  out.head = linked.querySelector('h3').textContent;
  out.buttons = linked.querySelectorAll('button').filter((b) => !b.closest('.finding')).map((b) => b.textContent);
  out.card = linked.querySelector('article').textContent.includes('Аномалия слоя C1');
""", routes=LIST_ROUTES, query={"finding": "7"})
    assert out["head"] == "Вывод № 7"
    assert out["buttons"] == ["Учтено", "Скрыть", "Заметка", "Открепить", "Закрыть", "Открыть основания", "Сохранить заметку"] and out["card"]


# -- «Перепроверить все работы» (REQ-004, DEC-089) ----------------------------------------------------------------------------
PREVIEW = {"photos": 31, "estimate_s": 775, "backup_dir": "/Users/op/titanium-backups", "backup_bytes": 1181116006, "free_bytes": 50 * 2**30, "running": False}
STARTED = {"id": 4, "status": "running", "phase": "backup", "total": 31, "done": 0, "current": None, "elapsed_s": 0, "photos": [], "backup": None,
           "findings": None, "error": None, "started_at": "2026-10-25T12:00:00+00:00", "finished_at": None, "backup_path": None}
RUNNING = {**STARTED, "phase": "remeasure", "done": 12, "elapsed_s": 300.0, "current": {"pair_id": 77, "photo_name": "IMG_77.CR3", "title": "Пейзаж"}}
REPORT = {**STARTED, "status": "done", "phase": "done", "done": 3, "total": 3, "elapsed_s": 75.0, "finished_at": "2026-10-25T12:20:00+00:00",
          "backup": {"path": "/Users/op/titanium-backups/titanium-backup-20261025T120000Z", "bytes": 1181116006},
          "photos": [{"pair_id": 41, "photo_name": "a.CR3", "title": "Тестовая плата", "status": "replaced", "replaced_by": 120, "reason": None,
                      "max_delta_e": 0.4, "changed_layers": 0, "layers": 24},
                     {"pair_id": 52, "photo_name": "b.CR3", "title": "Пейзаж", "status": "replaced", "replaced_by": 121, "reason": None,
                      "max_delta_e": 6.2, "changed_layers": 3, "layers": 10},
                     {"pair_id": 60, "photo_name": "c.CR3", "title": None, "status": "kept", "replaced_by": None,
                      "reason": "the new measurement reads fewer layers than the accepted one", "max_delta_e": None, "changed_layers": 0, "layers": 0}],
          "findings": {"before_run_id": 63, "after_run_id": 64, "before": 95, "after": 96, "counts": {"appeared": 2, "gone": 1, "changed": 1},
                       "appeared": [{"id": 900, "kind": "anomaly", "statement": "Новая аномалия"}, {"id": 901, "kind": "gap", "statement": "Новый пробел"}],
                       "gone": [{"id": 700, "kind": "anomaly", "statement": "Старая аномалия"}],
                       "changed": [{"id": 902, "kind": "unstable", "statement": "Стало нестабильно", "was": {"id": 702, "kind": "improvement", "statement": "Было валидировано"}}]}}


@node
def test_recheck_asks_first_with_the_photographs_the_time_and_the_backup_then_starts_and_shows_its_progress(tmp_path):
    out = run(tmp_path, """
  ctx.document.body.append(tree);
  await tree.querySelectorAll('button').find((b) => b.textContent === 'Перепроверить все работы').dispatch('click'); await tick(); await tick();
  const modal = ctx.document.body.querySelector('.modal');
  out.title = modal.querySelector('h3').textContent;
  out.text = modal.querySelectorAll('p').map((p) => p.textContent);
  out.buttons = modal.querySelectorAll('button').map((b) => b.textContent);
  await modal.querySelectorAll('button').find((b) => b.textContent === 'Перепроверить').dispatch('click'); await tick(); await tick();
  out.started = ctx.requests.filter((r) => r.path === '/api/recheck').map((r) => r.method);
  const box = tree.querySelector('.fd-recheck');
  out.progress = box.querySelector('.row').textContent;
  await box.querySelectorAll('button').find((b) => b.textContent === 'Остановить').dispatch('click'); await tick();
  out.stopped = ctx.requests.filter((r) => r.path === '/api/recheck/4/stop').map((r) => r.method);
  tree.remove();
""", routes={**LIST_ROUTES, "/api/recheck/preview": {"status": 200, "json": PREVIEW}, "/api/recheck": {"status": 202, "json": STARTED},
             "/api/recheck/4/stop": {"status": 200, "json": STARTED}})
    assert out["title"] == "Перепроверить все работы?"
    assert out["text"][0] == ("Все принятые фотографии (31) будут заново измерены так, как приложение измеряет сейчас, и выводы пересчитаны один раз в конце. "
                              "Займёт примерно 13 мин.")
    assert out["text"][1].startswith("Сначала — полная резервная копия мастерской в папку /Users/op/titanium-backups (1,1 ГБ, свободно 50,0 ГБ)")
    assert out["buttons"] == ["×", "Отмена", "Перепроверить"]
    assert out["started"] == ["POST"] and out["stopped"] == ["POST"]
    assert out["progress"] == "Перепроверка всех работДелаю резервную копию мастерской…Остановить"


@node
def test_without_room_for_the_backup_the_recheck_is_not_offered(tmp_path):
    out = run(tmp_path, """
  await tree.querySelectorAll('button').find((b) => b.textContent === 'Перепроверить все работы').dispatch('click'); await tick(); await tick();
  const modal = ctx.document.body.querySelector('.modal');
  out.alert = modal.querySelector('.alert').textContent;
  out.buttons = modal.querySelectorAll('button').map((b) => b.textContent);
""", routes={**LIST_ROUTES, "/api/recheck/preview": {"status": 200, "json": {**PREVIEW, "free_bytes": 2**20}}})
    assert out["alert"].startswith("Места для резервной копии не хватает") and out["buttons"] == ["×", "Закрыть"]


@node
def test_a_recheck_running_when_the_screen_opens_shows_which_photograph_of_how_many_and_the_time_left(tmp_path):
    out = run(tmp_path, """
  out.progress = tree.querySelector('.fd-recheck').querySelector('.row').textContent;
  out.now = tree.querySelector('.fd-recheck').querySelector('div').getAttribute('aria-valuenow');
""", routes={**LIST_ROUTES, "/api/recheck/latest": {"status": 200, "json": RUNNING}})
    assert out["progress"] == "Перепроверка всех работПеремеряю фото 13 из 31 · Пейзаж (фото № 77) · осталось ≈ 8 минОстановить"


@node
def test_the_last_recheck_report_lists_the_photographs_and_the_changed_findings_briefly(tmp_path):
    out = run(tmp_path, """
  const box = tree.querySelector('.fd-recheck');
  out.summary = box.querySelector('summary').textContent;
  out.facts = box.querySelector('dl').textContent;
  const [photos, changes] = box.querySelectorAll('.lst');
  out.photos = photos.querySelectorAll('.lst-main').map((r) => r.textContent);
  out.changes = changes.querySelectorAll('.lst-main').map((r) => r.textContent);
  await photos.querySelectorAll('.lst-main')[2].dispatch('click'); await tick();
  out.reason = photos.querySelectorAll('.lst-det').find((d) => !d.hidden).textContent;
  await box.querySelectorAll('button').find((b) => b.textContent.startsWith('Показать выводы')).dispatch('click');
  out.hash = ctx.location.hash;
""", routes={**LIST_ROUTES, "/api/recheck/latest": {"status": 200, "json": REPORT}})
    assert out["summary"].startswith("Последняя перепроверка: 25.10.2026, ")
    assert out["summary"].endswith(" · Перепроверка закончена · заменено 2, оставлено старое 1, ошибок 0")
    assert "Резервная копия/Users/op/titanium-backups/titanium-backup-20261025T120000Z (1,1 ГБ)" in out["facts"]
    assert "расчёт № 63 → № 64: появилось 2, ушло 1, изменилось 1" in out["facts"]
    assert out["photos"] == ["замененоПейзажфото № 52ΔE до 6.2слоёв изменилось: 3",
                             "замененоТестовая платафото № 41ΔE до 0.4", "оставлено староеc.CR3фото № 60"]       # the largest colour change first
    assert out["changes"] == ["появилсяАномалияНовая аномалия", "появилсяПробелНовый пробел", "ушёлАномалияСтарая аномалия",
                              "изменилсяНестабильноСтало нестабильно"]
    assert out["reason"] == "the new measurement reads fewer layers than the accepted oneОткрыть фото"
    assert out["hash"] == "#/findings?state=attention&sort=newest"


# -- acting on a finding (feature act-on-findings) ------------------------------------------------------------------------------
ANOMALY = {**finding(7, "anomaly", "observation", "Наблюдение № 3063 отстоит на 84.1 ΔE", deviation=84.1,
                     remedies=[{"action": "exclude_measurement", "observation_id": 3063}, {"action": "remeasure", "pair_id": 136},
                               {"action": "count_from_latest"}]),
           "key": "anomaly:photo:41:3", "evidence": {"pair_ids": [136], "observation_ids": [3063], "knowledge_id": 496}}
REMEDY_PREVIEW = {"action": "exclude_measurement", "kind": "measurement", "device_id": 1, "lens_id": 2, "recipe_key": "k",
                  "observation": {"id": 3063, "pair_id": 136, "layer_index": 3, "layer_name": "C03", "photo_name": "a.CR3", "lab": [40.0, 9.2, -21.4]},
                  "leaving": {"observation_ids": [3063], "pair_ids": [136], "engraving_ids": ["e1"]},
                  "before": {"lab": [75.4, 10.2, 54.9], "engravings": 3, "observations": 3, "confidence": 0.11, "contradicted": True},
                  "after": {"lab": [76.0, 10.0, 55.0], "engravings": 2, "observations": 2, "confidence": 0.33, "contradicted": False}, "delta_e": 0.7}
DECIDED = {"exclusion": {"id": 5, "kind": "measurement", "active": True}, "preview": REMEDY_PREVIEW, "run_id": 64}
REMEDY_ROUTES = {**LIST_ROUTES, "/api/analysis/runs/latest": {"status": 200, "json": {**PAGE, "findings": [ANOMALY]}},
                 "/api/analysis/findings/7/remedy": {"status": 200, "json": REMEDY_PREVIEW}}


@node
def test_an_opened_anomaly_leads_with_the_recommended_step_then_the_evidence_and_keeps_the_other_actions_in_a_fold(tmp_path):
    """REQ-002, DEC-001: an anomaly of a measurement recommends measuring its photograph again; the evidence follows it; taking the
    measurement out and counting from the newest engraving wait under «Другие действия», each with its line on what it does."""
    out = run(tmp_path, """
  const list = panel('Выводы');
  await list.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  const open = list.querySelectorAll('.lst-det').find((d) => !d.hidden);
  const next = open.querySelector('.fd-next');
  out.order = open.children.map((c) => (c.className || '').split(' ')[0] || c.localName);
  out.head = next.querySelector('h4').textContent; out.action = next.getAttribute('data-action');
  out.step = next.querySelectorAll('button').map((b) => b.textContent); out.why = next.querySelector('.fd-next-why').textContent;
  const more = open.querySelector('.fd-more-actions');
  out.fold = [more.hasAttribute('open'), more.querySelector('summary').textContent];
  out.lines = more.querySelectorAll('.fd-remedy').map((r) => [r.querySelector('button').textContent, r.querySelector('span').textContent]);
  out.evidence = open.querySelector('.fd-evidence').textContent;
  out.terms = open.querySelectorAll('.terms-note').map((n) => [n.querySelector('summary').textContent, n.textContent.includes('Technical identifier')]);
  out.history = open.querySelectorAll('details').filter((d) => d.querySelector('summary').textContent === 'История вывода по расчётам').length;
""", routes=REMEDY_ROUTES)
    assert out["head"] == "Что дальше" and out["action"] == "remeasure" and out["step"] == ["Перемерить фото"]
    assert out["order"][:5] == ["fd-remedies", "row", "stack", "fd-more-actions", "stack"]               # the step, the evidence, the words explained, the other actions, the mark
    assert out["why"].startswith("Сначала перемерьте фотографию") and "после проверки причины" in out["why"]
    assert ["What is evidence?", False] in out["terms"]
    assert out["fold"] == [False, "Другие действия (2)"]                                              # the measuring again is the step, not repeated below
    assert [button for button, _ in out["lines"]] == ["Убрать измерение", "Считать с последней гравировки"]
    assert out["lines"][0][1].startswith("Этот слой этой фотографии перестанет считаться в рецепте, на карте цветов, в палитре и в работах.")
    assert out["lines"][1][1].startswith("Цвет рецепта — по самой новой гравировке. Старые остаются в истории, но не считаются")
    assert "фото № 136" in out["evidence"] and out["history"] == 1


@node
def test_when_the_corrective_choice_is_unclear_the_evidence_is_the_step_and_every_remedy_is_one_fold_away(tmp_path):
    ambiguous = {**ANOMALY, "remedies": [r for r in ANOMALY["remedies"] if r["action"] != "remeasure"]}
    ambiguous["recommendation"] = fd.recommend(ambiguous)
    out = run(tmp_path, """
  const list = panel('Выводы');
  const row = list.querySelectorAll('.lst-act')[0];
  out.row = row.querySelectorAll('button').map((b) => b.textContent);
  await row.querySelectorAll('button').find((b) => b.textContent === 'Открыть основания').dispatch('click'); await tick(); await tick();
  const open = list.querySelectorAll('.lst-det').find((d) => !d.hidden);
  const first = open && open.querySelector('.fd-evidence').querySelector('a');
  out.opened = !!open; out.focused = first ? !!first.focused : null;
  out.action = open.querySelector('.fd-next').getAttribute('data-action');
  out.more = open.querySelector('.fd-more-actions').querySelectorAll('button').map((b) => b.textContent);
""", routes={**REMEDY_ROUTES, "/api/analysis/runs/latest": {"status": 200, "json": {**PAGE, "findings": [ambiguous]}}})
    assert out["row"][0] == "Открыть основания" and out["opened"] and out["action"] == "open_evidence"
    assert out["focused"] is True                                                                       # the cursor goes to the first thing the finding rests on
    assert out["more"] == ["Убрать измерение", "Считать с последней гравировки"]


@node
def test_a_finding_of_an_earlier_run_or_one_already_marked_offers_no_corrective_step(tmp_path):
    earlier = {**ANOMALY, "remedies": []}
    earlier["recommendation"] = fd.recommend(earlier)
    handled = finding(8, "anomaly", "observation", "Отмеченная аномалия", state="acknowledged", remedies=ANOMALY["remedies"])
    out = run(tmp_path, """
  const list = panel('Выводы');
  out.rows = list.querySelectorAll('.lst-act').map((a) => a.querySelectorAll('button').map((b) => b.textContent));
  await list.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  const open = list.querySelectorAll('.lst-det').find((d) => !d.hidden);
  out.folds = open.querySelectorAll('.fd-more-actions').length; out.step = open.querySelector('.fd-next').getAttribute('data-action');
  out.why = open.querySelector('.fd-next-why').textContent;
""", routes={**REMEDY_ROUTES, "/api/analysis/runs/latest": {"status": 200, "json": {**PAGE, "findings": [earlier, handled]}}})
    assert out["rows"][0][0] == "Открыть основания" and "Перемерить фото" not in out["rows"][0]            # nothing to measure again in an earlier calculation
    assert out["rows"][1] == ["Вернуть", "Скрыть", "Заметка", "Закрепить"]                                  # a marked finding is returned, not advised again
    assert out["folds"] == 0 and out["step"] == "open_evidence"                                         # an earlier run offers no remedy at all
    assert out["why"].startswith("Исправлений этот вывод не предлагает")


@node
def test_a_gap_proposes_an_experiment_and_a_finding_with_nothing_to_fix_is_acknowledged(tmp_path):
    good = finding(11, "improvement", "validated", "Рецепт валидирован")
    good["evidence"] = {}
    good["recommendation"] = fd.recommend(good)
    out = run(tmp_path, """
  const list = panel('Выводы');
  out.rows = list.querySelectorAll('.lst-act').map((a) => a.querySelectorAll('button').map((b) => [b.textContent, (b.className || '').includes('primary')]));
  out.actions = list.querySelectorAll('.lst-act').map((a) => a.querySelectorAll('button').filter((b) => b.className.includes('fd-recommended')).map((b) => b.textContent));
  await list.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  out.proposals = list.querySelectorAll('.lst-det').find((d) => !d.hidden).querySelectorAll('button').filter((b) => b.textContent === 'Предложить эксперимент').length;
""", routes={**REMEDY_ROUTES, "/api/analysis/runs/latest": {"status": 200, "json": {**PAGE, "findings": [PAGE["findings"][2], good]}}})
    assert out["actions"] == [["Предложить эксперимент"], ["Учтено"]]                                  # «Учтено» is itself the recommended step
    assert out["proposals"] == 1                                                                         # the opened gap does not offer the same button twice
    assert out["rows"][1][0] == ["Учтено", True]


@node
def test_taking_a_measurement_out_shows_what_leaves_and_the_colour_before_and_after_then_decides_with_the_note(tmp_path):
    out = run(tmp_path, """
  ctx.document.body.append(tree);
  const list = panel('Выводы');
  await list.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  await list.querySelector('.fd-more-actions').querySelectorAll('button').find((b) => b.textContent === 'Убрать измерение').dispatch('click'); await tick(); await tick();
  const modal = ctx.document.body.querySelector('.modal');
  out.title = modal.querySelector('h3').textContent;
  out.leaving = modal.querySelector('p').textContent;
  out.change = modal.querySelector('.fd-change').textContent;
  out.buttons = modal.querySelectorAll('button').map((b) => b.textContent);
  out.asked = ctx.requests.filter((r) => r.path === '/api/analysis/findings/7/remedy').map((r) => r.body);
  modal.querySelector('textarea').value = 'блик на фото';
  data.routes['/api/analysis/findings/7/remedy'] = {status: 200, json: %(decided)s};
  await modal.querySelectorAll('button').find((b) => b.textContent === 'Убрать измерение').dispatch('click'); await tick(); await tick();
  out.sent = ctx.requests.filter((r) => r.path === '/api/analysis/findings/7/remedy').map((r) => r.body);
  out.toast = ctx.document.body.querySelectorAll('.toast').map((t) => t.textContent);
  out.closed = !ctx.document.body.querySelector('.modal');
  tree.remove();
""" % {"decided": json.dumps(DECIDED)}, routes=REMEDY_ROUTES)
    assert out["title"] == "Убрать измерение?"
    assert out["leaving"] == "Перестанет считаться: фото № 136, слой «C03» L 40.0 · a 9.2 · b -21.4"
    assert out["change"] == ("Цвет рецептасейчас: L 75.4 · a 10.2 · b 54.9 · гравировок: 3станет: L 76.0 · a 10.0 · b 55.0 · гравировок: 2"
                             "сдвиг ΔE 0.7")
    assert out["buttons"] == ["×", "Отмена", "Убрать измерение"]
    assert out["asked"] == ['{"action":"exclude_measurement"}']
    assert out["sent"][-1] == '{"action":"exclude_measurement","note":"блик на фото","confirm":true}'
    assert out["toast"] == ["Готово · измерение убрано из расчёта · расчёт № 64 Вернуть ×"] and out["closed"]


@node
def test_measuring_the_photograph_again_from_the_finding_shows_each_layer_before_and_after_its_own_first(tmp_path):
    remeasured = {"pair_id": 136, "status": "replaced", "replaced_by": 151, "reason": None,
                  "layers": [{"layer_index": 1, "name": "C01", "before": [50, 0, 0], "after": [50, 0, 5], "delta_e": 5.0},
                             {"layer_index": 3, "name": "C03", "before": [40, 9, -21], "after": [74, 10, 54], "delta_e": 82.0},
                             {"layer_index": 2, "name": "C02", "before": [60, 0, 0], "after": [60, 0, 0], "delta_e": 0.0}]}
    out = run(tmp_path, """
  ctx.document.body.append(tree);
  const list = panel('Выводы');
  await list.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  await list.querySelector('.fd-next').querySelectorAll('button').find((b) => b.textContent === 'Перемерить фото').dispatch('click'); await tick(); await tick();
  out.sent = ctx.requests.filter((r) => r.path === '/api/pairs/136/remeasure').map((r) => r.method);
  const modal = ctx.document.body.querySelector('.modal');
  out.title = modal.querySelector('h3').textContent;
  out.text = modal.querySelector('p').textContent;
  out.rows = modal.querySelectorAll('.lst-main').map((r) => r.textContent);
  tree.remove();
""", routes={**REMEDY_ROUTES, "/api/pairs/136/remeasure": {"status": 200, "json": remeasured}})
    assert out["sent"] == ["POST"] and out["title"] == "Фото перемерено"
    assert out["text"] == "Фото № 136 перемерено; новое измерение — фото № 151."
    assert out["rows"] == ["этот выводСлой «C03»→ΔE 82.0", "Слой «C01»→ΔE 5.0", "Слой «C02»→ΔE 0.0"]


@node
def test_a_failed_remeasure_from_the_row_leaves_the_finding_as_it_was_and_the_button_ready_again(tmp_path):
    out = run(tmp_path, """
  ctx.document.body.append(tree);
  const list = panel('Выводы');
  const step = () => list.querySelectorAll('.lst-act')[0].querySelectorAll('button')[0];
  await step().dispatch('click'); await tick(); await tick();
  out.sent = ctx.requests.filter((r) => r.path === '/api/pairs/136/remeasure').map((r) => r.method);
  out.label = step().textContent; out.disabled = !!step().disabled;
  out.modal = !!ctx.document.body.querySelector('.modal');
  out.toast = ctx.document.body.querySelectorAll('.toast').map((x) => x.textContent);
  out.rows = list.querySelectorAll('.lst-main').length;
  tree.remove();
""", routes={**REMEDY_ROUTES, "/api/pairs/136/remeasure": {"status": 409, "json": {"error": "every work is being re-checked: wait until it ends or stop it", "kind": "busy"}}})
    assert out["sent"] == ["POST"] and out["label"] == "Перемерить фото" and out["disabled"] is False       # ready again, not left on «Перемеряю…»
    assert out["modal"] is False and out["rows"] == 1                                                   # no result is shown for a measurement that did not happen
    assert len(out["toast"]) == 1 and out["toast"][0].startswith("every work is being re-checked")                                   # the server's refusal is told, once


@node
def test_pressing_the_recommended_step_twice_measures_the_photograph_once(tmp_path):
    remeasured = {"pair_id": 136, "status": "kept", "replaced_by": None, "reason": "the new measurement reads fewer layers than the accepted one", "layers": []}
    out = run(tmp_path, """
  ctx.document.body.append(tree);
  const list = panel('Выводы');
  await list.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  const row = list.querySelectorAll('.lst-act')[0].querySelectorAll('button')[0];
  const inside = list.querySelector('.fd-next').querySelectorAll('button')[0];
  const first = row.dispatch('click');
  const again = row.dispatch('click');                       // the same button again
  const other = inside.dispatch('click');                    // the same photograph from the other button
  await Promise.all([first, again, other]); await tick(); await tick();
  out.sent = ctx.requests.filter((r) => r.path === '/api/pairs/136/remeasure').length;
  out.title = ctx.document.body.querySelector('.modal').querySelector('h3').textContent;
  tree.remove();
""", routes={**REMEDY_ROUTES, "/api/pairs/136/remeasure": {"status": 200, "json": remeasured}})
    assert out["sent"] == 1 and out["title"] == "Фото не перемерено"


@node
def test_the_marks_still_work_beside_the_recommendation_and_a_hidden_finding_loses_its_step(tmp_path):
    hidden = finding(12, "anomaly", "observation", "Скрытая аномалия", state="hidden", remedies=ANOMALY["remedies"])
    out = run(tmp_path, """
  const list = panel('Выводы');
  const acts = list.querySelectorAll('.lst-act');
  out.hidden = acts[1].querySelectorAll('button').map((b) => b.textContent);
  const before = ctx.requests.length;
  await acts[0].querySelectorAll('button').find((b) => b.textContent === 'Закрепить').dispatch('click'); await tick(); await tick();
  out.sent = ctx.requests.slice(before).filter((r) => r.method === 'POST').map((r) => [r.url, r.body]);
""", routes={**REMEDY_ROUTES, "/api/analysis/findings/7/mark": {"status": 200, "json": {"pinned": True}},
             "/api/analysis/runs/latest": {"status": 200, "json": {**PAGE, "findings": [ANOMALY, hidden]}}})
    assert out["hidden"] == ["Вернуть", "Заметка", "Закрепить"]                                         # no step on a finding the operator hid: «Вернуть» first
    assert out["sent"] == [["/api/analysis/findings/7/mark", '{"action":"pin"}']]


@node
def test_the_photo_queue_puts_what_came_out_a_negative_first_and_asks_nothing_of_a_settled_place(tmp_path):
    flop = {"settings": {"dither": "atkinson", "power": 15.0}, "black_lab": [74.1, 5.6, 36.7], "tone": {"range_L": -7.1}, "source": {"pair_id": 143, "layer": "C22"}}
    broken = {**EVERYWHERE[0], "device_id": 2, "setup": "Laser B · lens", "titanium": "Grade 2", "kinds": [
        {"kind": "atkinson", "status": "failed", "engravings": 1, "best": None, "failed": [flop], "effects": {}, "proposal": None}]}
    fine = {**EVERYWHERE[0], "device_id": 3, "setup": "Laser A · lens", "titanium": "Grade 5", "kinds": [
        {"kind": "grayscale", "status": "settled", "engravings": 3, "best": {"settings": JARVIS, "score": 0.9, "source": {"pair_id": 7, "layer": "C1"}},
         "failed": [], "effects": {}, "proposal": None}]}
    out = run(tmp_path, """
  await tab('Фотогравировка').dispatch('click'); await tick();
  const section = panel('Фотогравировка');
  out.rows = section.querySelectorAll('.lst-main').map((x) => x.textContent);
  out.steps = section.querySelectorAll('.lst-act').map((a) => a.querySelectorAll('button').map((b) => [b.textContent, b.className.includes('fd-recommended')]));
  await section.querySelectorAll('.lst-act')[0].querySelectorAll('button')[0].dispatch('click');
  out.went = ctx.location.hash;
""", routes={**ROUTES, "/api/analysis/photo-queue": {"status": 200, "json": queued([fine, broken])}})
    assert out["rows"][0].startswith("Laser B · lens · Grade 2") and out["rows"][0].endswith("Дальше: Atkinson — не получился")             # most urgent first
    assert out["rows"][1].startswith("Laser A · lens · Grade 5") and out["rows"][1].endswith("решений не требуется")
    assert out["steps"] == [[["Открыть фото № 143", True]], []]                                                                        # a settled place has no step
    assert out["went"] == "#/analysis/143"


@node
def test_a_plate_the_laboratory_proposes_is_looked_at_before_it_is_made(tmp_path):
    around = {"kind": "around", "centre": JARVIS, "step": 1.0, "source": {"pair_id": 41, "layer": "C1"}, "copies": [[], [{"setting": "power", "from": 30.0, "to": 24.0}]],
              "plate": {"copy_mm": [10, 10], "size_mm": [40, 40], "picture": "Face"}}
    place = {**EVERYWHERE[0], "kinds": [{**EVERYWHERE[0]["kinds"][0], "proposal": around}]}
    out = run(tmp_path, """
  await tab('Фотогравировка').dispatch('click'); await tick();
  const section = panel('Фотогравировка');
  const step = section.querySelectorAll('.lst-act')[0].querySelectorAll('button')[0];
  out.label = step.textContent; out.posts = ctx.requests.filter((r) => r.method === 'POST').length;
  await step.dispatch('click'); await tick(); await tick();
  out.opened = section.querySelectorAll('.lst-det').filter((d) => !d.hidden).length;
  out.postsAfter = ctx.requests.filter((r) => r.method === 'POST').length;
""", routes={**ROUTES, "/api/analysis/photo-queue": {"status": 200, "json": queued([{**place, "device_id": 9}, {**place, "device_id": 8, "setup": "Another"}])}})
    assert out["label"] == "Посмотреть предложение" and out["posts"] == 0
    assert out["opened"] == 1 and out["postsAfter"] == 0                          # the step opens the proposal; nothing is made until its own button is pressed


@node
def test_when_the_photo_queue_cannot_be_read_the_findings_still_stand(tmp_path):
    out = run(tmp_path, """
  out.tabs = tree.querySelectorAll('button').filter((b) => b.getAttribute('role') === 'tab').map((b) => b.textContent);
  out.title = tree.querySelector('h2').textContent;
""", routes={**LIST_ROUTES, "/api/analysis/photo-queue": {"status": 500, "json": {"error": "boom", "kind": "internal"}}})
    assert out["tabs"] == [] and out["title"] == "Выводы"


EXCLUSIONS = {"active": 2, "exclusions": [
    {"id": 6, "kind": "older_engravings", "active": True, "created_at": "2026-10-25T13:00:00+00:00", "note": None, "observations_out": 2,
     "settings": {"power": 13.3, "frequency": 60, "speed": 117, "pulse_width": 300, "line_interval": 0.0169, "passes": 1},
     "kept": {"title": "Big Plate", "lab": [60, 20, 0]}, "before": {"lab": [55, 5, 0], "engravings": 3}, "after": {"lab": [60, 20, 0], "engravings": 1}},
    {"id": 5, "kind": "measurement", "active": True, "created_at": "2026-10-25T12:00:00+00:00", "note": "блик", "observations_out": 1, "pair_id": 151,
     "original_pair_id": 136, "layer_index": 3, "observation": {"layer_name": "C03", "lab": [40, 9, -21]},
     "before": {"lab": [75.4, 10.2, 54.9], "engravings": 3}, "after": {"lab": [76, 10, 55], "engravings": 2}}]}


@node
def test_what_the_operator_took_out_is_one_short_list_with_vernut_on_each_line(tmp_path):
    out = run(tmp_path, """
  const block = tree.querySelector('.fd-excluded');
  out.summary = block.querySelector('summary').textContent;
  out.rows = block.querySelectorAll('.lst-main').map((r) => r.textContent);
  await block.querySelectorAll('.lst-act')[1].querySelector('button').dispatch('click'); await tick(); await tick();
  out.sent = ctx.requests.filter((r) => r.path === '/api/exclusions/5/revoke').map((r) => r.method);
  out.toast = ctx.document.body.querySelectorAll('.toast').map((t) => t.textContent);
""", routes={**LIST_ROUTES, "/api/exclusions": {"status": 200, "json": EXCLUSIONS},
             "/api/exclusions/5/revoke": {"status": 200, "json": {"exclusion": {"id": 5, "active": False}, "run_id": 65}}})
    assert out["summary"] == "Убрано оператором: 2"
    assert out["rows"][0].startswith("Рецепт 13.3 % · 60 кГц · 117 мм/с · 300 нс · шаг 0.0169 мм · 1 пр. — с последней гравировки «Big Plate»25.10.2026")
    assert out["rows"][1].startswith("Измерение: фото № 151, слой «C03»25.10.2026") and out["rows"][1].endswith("✎ блик")
    assert out["sent"] == ["POST"] and out["toast"] == ["Снова считается · расчёт № 65 ×"]


@node
def test_without_exclusions_the_findings_show_no_such_block(tmp_path):
    out = run(tmp_path, "  out.block = !!tree.querySelector('.fd-excluded');\n", routes=LIST_ROUTES)
    assert out["block"] is False


# -- long lists of source numbers (feature ux-growing-collections-p0, REQ-002) ------------------------------------------------------
def page_of(*findings) -> dict:
    return {**REMEDY_ROUTES, "/api/analysis/runs/latest": {"status": 200, "json": {**PAGE, "findings": list(findings)}}}


@node
def test_long_evidence_is_a_count_with_a_list_of_every_number_and_a_short_one_stays_in_the_row(tmp_path):
    many = {**ANOMALY, "evidence": {"pair_ids": list(range(200, 230)), "observation_ids": list(range(1, 41)), "knowledge_ids": list(range(300, 312)), "knowledge_id": 496}}
    out = run(tmp_path, """
  const list = panel('Выводы');
  await list.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  const evidence = list.querySelectorAll('.lst-det').find((d) => !d.hidden).querySelector('.fd-evidence');
  out.blocks = evidence.querySelectorAll('.srefs').map((b) => [b.querySelector('.srefs-label').textContent, b.querySelector('.srefs-count').textContent]);
  out.before = {text: evidence.textContent, links: evidence.querySelectorAll('a').map((a) => a.textContent)};
  await evidence.querySelectorAll('.srefs-toggle')[0].dispatch('click'); await tick();
  out.photos = evidence.querySelectorAll('.srefs-list')[0].querySelectorAll('a').map((a) => a.getAttribute('href'));
""", routes=page_of(many))
    assert out["blocks"] == [["Фото: ", "30"], ["Знание: ", "12"], ["Наблюдения: ", "40"]]
    assert "и ещё" not in out["before"]["text"] and "…" not in out["before"]["text"] and out["before"]["links"] == ["знание № 496"]    # no number is cut off, none is printed
    assert out["photos"] == [f"#/analysis/{i}" for i in range(200, 230)]
    few = run(tmp_path, """
  const list = panel('Выводы');
  await list.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  const evidence = list.querySelectorAll('.lst-det').find((d) => !d.hidden).querySelector('.fd-evidence');
  out.text = evidence.textContent; out.blocks = evidence.querySelectorAll('.srefs').length;
""", routes=page_of({**ANOMALY, "evidence": {"pair_ids": [136, 137], "observation_ids": [3063, 3064]}}))
    assert few["blocks"] == 0 and "фото № 136" in few["text"] and "наблюдения № 3063, 3064" in few["text"]


@node
def test_the_observations_that_raised_a_doubt_are_a_count_when_many_and_named_when_few(tmp_path):
    def doubtful(ids):
        return {**finding(8, "unstable", "questioned", "Сомнение в знании № 12", deviation=2.5), "compares": {"stage": "production", "doubt_observation_ids": ids}}
    body = """
  const list = panel('Выводы');
  await list.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  const open = list.querySelectorAll('.lst-det').find((d) => !d.hidden);
  out.text = open.textContent; out.blocks = open.querySelectorAll('.srefs').map((b) => [b.querySelector('.srefs-label').textContent, b.querySelector('.srefs-count').textContent]);
"""
    many = run(tmp_path, body, routes=page_of(doubtful(list(range(10, 19)))))
    assert many["blocks"] == [["Наблюдения, вызвавшие сомнение: ", "9"]] and "Стадия «производственное»" in many["text"]
    few = run(tmp_path, body, routes=page_of(doubtful([10, 11, 12])))
    assert few["blocks"] == [] and "наблюдения, вызвавшие сомнение: 10, 11, 12" in few["text"]


@node
def test_the_preview_of_counting_from_the_newest_engraving_counts_many_photographs_and_names_few(tmp_path):
    preview = {**REMEDY_PREVIEW, "action": "count_from_latest", "kind": "older_engravings", "observation": None,
               "kept": {"title": "Big Plate", "when": "2026-10-24T10:00:00", "lab": [75.0, 10.0, 55.0], "pair_ids": list(range(1, 11))},
               "older": [{"title": "Old plate", "when": "2026-10-20T10:00:00", "lab": [70.0, 9.0, 50.0], "pair_ids": [5, 6]}]}
    routes = {**page_of(ANOMALY), "/api/analysis/findings/7/remedy": {"status": 200, "json": preview}}
    out = run(tmp_path, """
  ctx.document.body.append(tree);
  const list = panel('Выводы');
  await list.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  await list.querySelector('.fd-more-actions').querySelectorAll('button').find((b) => b.textContent === 'Считать с последней гравировки').dispatch('click'); await tick(); await tick();
  const modal = ctx.document.body.querySelector('.modal');
  out.text = modal.querySelector('.stack').textContent;
  out.counts = modal.querySelectorAll('.srefs').map((b) => [b.querySelector('.srefs-label').textContent, b.querySelector('.srefs-count').textContent]);
  tree.remove();
""", routes=routes)
    assert out["counts"] == [["Фото: ", "10"]]                                                       # the kept engraving has ten photographs; the older one two
    assert "Big Plate" in out["text"] and "фото: 10" in out["text"] and "Old plate" in out["text"] and "фото № 5, 6" in out["text"]


@node
def test_the_interval_of_the_schedule_is_read_as_the_server_states_it_and_a_wrong_one_is_said_beside_its_box_with_nothing_saved(tmp_path):
    """ux-save-feedback-p0, REQ-003: 0 to 8760 hours (findings.set_interval); the number stays in the box and nothing is sent."""
    out = run(tmp_path, """
  const labelled = tree.querySelectorAll('label').find((l) => (l.querySelector('span') || {}).textContent === 'Пересчитывать каждые (0 — выключено)');
  const box = labelled.firstControl();
  const puts = () => ctx.requests.filter((r) => r.method === 'PUT').length;
  out.rule = [labelled.textContent.includes('required'), labelled.textContent.includes('allowed: from 0 to 8760'), labelled.textContent.includes('unit: h')];
  for (const typed of ['9000', '-1', '2.5h', '']) {
    box.value = typed; await box.dispatch('input');
    await byText(tree, 'button', 'Сохранить расписание').dispatch('click'); await tick();
    out[typed || 'empty'] = [puts(), labelled.errorText(), box.value, box.getAttribute('aria-invalid')];
  }
  box.value = '24'; await box.dispatch('input');
  await byText(tree, 'button', 'Сохранить расписание').dispatch('click'); await tick(); await tick();
  out.saved = [puts(), JSON.parse(ctx.requests.filter((r) => r.method === 'PUT')[0].body), labelled.errorText()];
""", routes={**ROUTES, "/api/analysis/schedule": {"status": 200, "json": {"interval_hours": 0, "next_due_at": None, "running": False}}})
    assert out["rule"] == [True, True, True]
    for typed in ("9000", "-1", "2.5h"):
        count, said, kept, invalid = out[typed]
        assert count == 0 and said and kept == typed and invalid == "true"
    assert "Entered: 9000" in out["9000"][1] and out["empty"][1] == "Complete this field" and out["empty"][0] == 0
    assert out["saved"] == [1, {"interval_hours": 24}, ""]
