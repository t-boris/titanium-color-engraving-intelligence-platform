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

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

GLUE = ("const __screens = {}; App.register = (d) => { __screens[d.id] = d; }; App.render = () => {};"
        "globalThis.__screens = __screens; App.go = (route) => { location.hash = '#' + route; };")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'photo-modes.js', 'photo-quality.js', 'dialogs.js', 'list.js', 'hardware.js', 'tasks.js', {code: %(glue)s},
  'screens/findings.js']);
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
ROUTES = {
    "/api/analysis/runs": {"status": 200, "json": []},
    "/api/analysis/schedule": {"status": 200, "json": {"interval_hours": 0, "next_due_at": None, "running": False}},
    "/api/application-goals": {"status": 200, "json": []},
    "/api/analysis/runs/latest": {"status": 200, "json": {"run": None, "findings": [], "total": 0,
                                                          "options": {"kinds": [], "tasks": [], "setups": [], "stocks": []}}},
    "/api/photo-knowledge/everywhere": {"status": 200, "json": EVERYWHERE},
    "/api/recheck/latest": {"status": 200, "json": None},
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
    assert out["rows"] == ["JPT M7 · F-Theta · Grade 5 sheet · Grade 5измерено видов: 1 из 1есть предложение"]      # one place: open at once
    jarvis, = out["cards"]
    assert jarvis.startswith("Джарвисизмерено, но не подобрано")
    assert "Лучшее: 30 %, 125 мм/с, 60 кГц, 200 нс, шаг 0,01 мм — оценка 0,62 по фото №41" in jarvis
    assert "мощность вдвое больше: темнее на 6 L*, оценка −0,1 (по фото №41, №42)" in jarvis
    assert "мощность 30 % → 24 %" in jarvis and "Картинки для платы ещё нет" in jarvis
    assert out["buttons"] == []                                   # no picture to engrave the plate from yet: nothing to press


@node
def test_without_a_photographed_photo_engraving_the_findings_have_no_photo_tab(tmp_path):
    out = run(tmp_path, """
  out.tabs = tree.querySelectorAll('button').filter((b) => b.getAttribute('role') === 'tab').map((b) => b.textContent);
""", routes={**ROUTES, "/api/photo-knowledge/everywhere": {"status": 200, "json": []}})
    assert out["tabs"] == []


# -- the findings as a short list the operator manages ------------------------------------------------------------------------
RUN = {"id": 63, "at": "2026-10-25T08:52:00+00:00", "trigger": "acceptance", "previous_run_id": 62,
       "inputs": {"accepted_pairs": 31, "eligible_observations": 794, "knowledge_entries": 669, "targets": 2, "insights": 3, "unset_rules": []},
       "counts": {"anomaly": 45, "unstable": 32, "gap": 10, "improvement": 5, "hypothesis": 3}}
CONTEXT = {"device_id": 1, "device": "JPT M7", "lens": {"id": 2, "name": "F-Theta 174", "focal_length_mm": 174, "field_mm": 170},
           "stock": {"name": "Grade 2 sheet", "grade": "Grade 2"}}


def finding(fid, kind, subkind, statement, state="attention", pinned=False, note=None, changed=False, new=False, deviation=None):
    return {"id": fid, "run_id": 63, "key": f"k{fid}", "kind": kind, "subkind": subkind, "basis": "measured" if kind != "anomaly" else "exploratory",
            "statement": statement, "device_id": 1, "lens_id": 2, "material_id": 3, "task": "fill", "context": CONTEXT, "new": new,
            "samples": {"independent_engravings": 3, "photographs": 3}, "uncertainty": {}, "evidence": {"pair_ids": [41]},
            "compares": {"observation_lab": [70, 0, 0], "reference_lab": [51, 0, 0], "rule": "tolerance", "delta_e": deviation, "tolerance": 10}
            if subkind == "observation" else {"stage": "production", "doubt_observation_ids": [3]},
            "limitations": [], "setup": "laser:1/lens:2", "stock_key": "3", "deviation": deviation, "state": state,
            "mark": {"status": None if state == "attention" and not changed else (state if state != "attention" else "hidden"), "pinned": pinned,
                     "note": note, "status_at": "2026-10-24T10:00:00+00:00" if state != "attention" or changed else None, "changed": changed}}


PAGE = {"run": RUN, "matched": 85, "total": 95,
        "findings": [finding(7, "anomaly", "observation", "Аномалия слоя C1", pinned=True, note="проверить", deviation=19.04),
                     finding(8, "unstable", "questioned", "Сомнение в знании № 12", changed=True, deviation=2.5),
                     finding(9, "gap", "coverage", "Нет линий на этом титане", new=True)],
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
    assert out["chips"] == ["Все · 85", "Требуют внимания · 85", "Учтённые · 0", "Скрытые · 0"]


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
  out.count = list.querySelector('.lst-count').textContent;
  out.more = list.querySelector('.lst-foot').textContent;
  out.cards = list.querySelectorAll('article').length;
""", routes=LIST_ROUTES)
    assert out["asked"] == ["/api/analysis/runs/latest?state=attention&sort=important&offset=0&limit=20"]
    assert out["run"].startswith("Расчёт № 63") and out["run"].endswith("после принятия фотографииПересчитать сейчасПерепроверить все работы")
    assert out["chips"] == ["Все · 95", "Требуют внимания · 85", "Учтённые · 6", "Скрытые · 4",
                            "Все · 85", "Улучшения · 5", "Нестабильность · 30", "Аномалии · 40", "Пробелы · 10"]   # no AI hypothesis to show
    assert out["pressed"] == ["Требуют внимания · 85", "Все · 85"]
    assert out["rows"] == ["📌АномалияАномалия слоя C1JPT M7 · Grade 2 sheet · Grade 2ΔE 19.0✎ проверить",       # the note on its row
                           "НестабильноСомнение в знании № 12JPT M7 · Grade 2 sheet · Grade 2ΔE 2.5изменился",
                           "ПробелНет линий на этом титанеJPT M7 · Grade 2 sheet · Grade 2новое"]
    assert out["actions"] == [["Учтено", "Скрыть", "Заметка", "Открепить"], ["Учтено", "Скрыть", "Заметка", "Закрепить"],
                              ["Учтено", "Скрыть", "Заметка", "Закрепить"]]
    assert out["count"] == "показано 3 из 85" and out["more"] == "Показать ещё 20" and out["cards"] == 0   # details only when a row opens


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
    assert out["buttons"] == ["Учтено", "Скрыть", "Заметка", "Открепить", "Закрыть", "Сохранить заметку"] and out["card"]


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
    assert out["reason"] == "Новое измерение читает меньше слоёв, чем принятоеОткрыть фото"
    assert out["hash"] == "#/findings?state=attention&sort=newest"
