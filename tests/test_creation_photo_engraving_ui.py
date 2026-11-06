"""«Новая работа» of photo engraving and the work screen, with the shared context (feature ux-work-creation-p0, REQ-001, REQ-002). The two-step
dialog of BUG-003 (the picture, then «Какая гравировка?») is the base and is tested in test_photo_engraving_ui.py; here only what the shared context
adds to it: the hand-over to the creation screen when nothing is measured, the context shown and its scale used, and the work's own context line.
The harness of that file is reused with a small server for the creation routes added in front of its own."""
import json
import subprocess
from pathlib import Path

import test_photo_engraving_ui as base
from test_photo_engraving_ui import KINDS, UI, WORK, TABLES, node, scale

ANCHOR = "  if (path === '/api/grey-scales') return answer({scales: data.scales});\n"
CREATION = """
  if (path === '/api/creation/context') return method === 'PUT' ? answer(data.after) : answer(data.context);
  if (path === '/api/creation/context/impact') return answer(data.impact);
  if (path === '/api/materials') return answer([{id: 3, name: 'Big Plate 150', grade: 'Grade 5'}, {id: 4, name: 'Sheet', grade: 'Grade 2'}]);
  if (path === '/api/materials/3') return answer({id: 3, name: 'Big Plate 150', grade: 'Grade 5'});      // the stock selector reads the one record it shows
  if (path === '/api/materials/4') return answer({id: 4, name: 'Sheet', grade: 'Grade 2'});
  if (path === '/api/creation/readiness') return data.readiness_error ? answer({error: 'workshop is busy'}, 500) : answer(data.readiness);
  if (path === '/api/devices') return answer([{id: 1, name: 'JPT', title: 'JPT 60', lens: {id: 2}}]);
  if (path === '/api/lenses') return answer([{id: 2, kind: 'F-Theta', name: 'F-Theta', focal_length_mm: 174}]);
"""
assert ANCHOR in base.HARNESS, "the photo engraving harness changed: update the anchor"
HARNESS = base.HARNESS.replace(ANCHOR, CREATION + ANCHOR)
SCRIPTS = [*base.SCRIPTS, "screens/material-picker.js", "context.js"]
CONTEXT = {"device_id": 1, "lens_id": 2, "lens_basis": "chosen", "material_id": 3, "capture_setup_id": None, "source": None, "stale": [],
           "device": {"id": 1, "name": "JPT", "title": "JPT 60"}, "lens": {"id": 2, "name": "F-Theta", "focal_length_mm": 174},
           "material": {"id": 3, "name": "Big Plate 150", "grade": "Grade 5"}}
READY = {"result": "photo", "ready": True, "missing": [], "measured": 2, "starter_test": None}
NOT_READY = {"result": "photo", "ready": False, "missing": ["measurements"], "measured": 0,
             "starter_test": {"result": "photo", "needs_rig": False, "becomes": "measured_scale", "test_type": "grey_scales"}}


AFTER = {**CONTEXT, "material_id": 4, "material": {"id": 4, "name": "Sheet", "grade": "Grade 2"}}
IMPACT = {"changed": True, "warnings": [{"code": "titanium_differs"}], "now": {}, "after": {}}


def run(tmp_path, query, body, work=None, context=CONTEXT, readiness=READY, readiness_error=False, scales=None):
    work = {**WORK, **(work or {})}
    scales = [scale(150, [1, 30]), scale(100, [2, 25])] if scales is None else scales
    (tmp_path / "data.json").write_text(json.dumps({"scales": scales, "scale": base.scale_answer(), "work": work, "kinds": KINDS, "works": [base.listed(work)],
                                                    "parts": base.PARTS, "ai_rules": base.AI_RULES, "engravings": [], "objects": base.OBJECTS,
                                                    "themes": base.THEMES, "advice": base.ADVICE, "context": context, "readiness": readiness,
                                                    "readiness_error": readiness_error, "after": AFTER, "impact": IMPACT}), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "scripts": json.dumps(SCRIPTS), "glue": json.dumps(base.GLUE),
                                 "query": json.dumps(query), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout)


OPEN_DIALOG = """
  await button(tree, 'Новая работа').dispatch('click'); await settle();
  let box = dialog();
"""


@node
def test_with_nothing_measured_new_work_goes_to_the_creation_screen_with_the_photo_result_instead_of_a_dialog_that_would_fail(tmp_path):
    out = run(tmp_path, {}, OPEN_DIALOG + """
  out.dialog = box !== null;
  out.went = [...ctx.__went];
  out.created = requests.filter((r) => r.path === '/api/photo-works' && r.method === 'POST').length;
""", readiness=NOT_READY)
    assert out["dialog"] is False and out["went"] == ["/new?result=photo"] and out["created"] == 0


@node
def test_an_answer_the_form_cannot_read_never_blocks_the_dialog(tmp_path):
    out = run(tmp_path, {}, OPEN_DIALOG + """
  out.dialog = box !== null && box.querySelector('h3').textContent;
  out.went = [...ctx.__went];
""", readiness_error=True)
    assert out["dialog"] == "Новая работа · шаг 1 из 2: картинка" and out["went"] == []


@node
def test_new_work_shows_the_shared_laser_lens_and_titanium_and_is_made_on_the_scale_of_exactly_that_setup(tmp_path):
    scales = [scale(150, [1, 30]), scale(100, [2, 25])]
    scales[0]["mode"] = {**scales[0]["mode"], "device_id": 5}                       # the best scale of the workshop belongs to another laser
    out = run(tmp_path, {}, OPEN_DIALOG + """
  out.shown = box.textContent;
  const file = input(box, (i) => i.getAttribute('type') === 'file');
  file.files = [{name: 'moto.jpg', size: 4096}]; await file.dispatch('change');
  await button(box, 'Дальше →').dispatch('click'); await settle();
  out.sent = requests.filter((r) => r.path === '/api/photo-works' && r.method === 'POST').map((r) => r.body);
  out.asked = requests.filter((r) => r.path === '/api/grey-scales').map((r) => r.url);
  out.second = dialog().querySelector('h3').textContent;
  out.remembered = requests.filter((r) => r.path === '/api/creation/context' && r.method === 'PUT').length;
""", scales=scales)
    for word in ("Работа делается на", "JPT 60", "F-Theta", "Big Plate 150", "Grade 5", "This workshop’s measurements"):
        assert word in out["shown"]
    [sent] = out["sent"]
    assert json.loads(sent["scale"])["speed"] == 100 and json.loads(sent["scale"])["device_id"] == 1      # not the first scale listed: that is another laser's
    assert "row_mm=" in out["asked"][-1] and "device_id=1&lens_id=2&material_id=3" in out["asked"][-1]
    assert out["second"] == "New work · step 2 of 2: which engraving?"                                   # BUG-003: the kind step is still the second
    assert out["remembered"] == 0                                                                           # the own measurements: the context is the same as before


@node
def test_without_a_shared_choice_the_dialog_is_as_it_was_and_the_best_scale_decides(tmp_path):
    out = run(tmp_path, {}, OPEN_DIALOG + """
  out.shown = box.textContent.includes('Работа делается на');
  const file = input(box, (i) => i.getAttribute('type') === 'file');
  file.files = [{name: 'moto.jpg', size: 4096}]; await file.dispatch('change');
  await button(box, 'Дальше →').dispatch('click'); await settle();
  out.sent = requests.filter((r) => r.path === '/api/photo-works' && r.method === 'POST').map((r) => Object.keys(r.body));
""", context={**CONTEXT, "device_id": None, "material_id": None})
    assert out["shown"] is False and out["sent"] == [["picture", "name", "width_mm"]]               # no shared choice yet: as before, the best scale decides


@node
def test_an_opened_photo_work_writes_its_own_laser_lens_titanium_and_source_under_its_title_whatever_the_shared_choice_is(tmp_path):
    other = {**CONTEXT, "device_id": 2, "material_id": 4, "device": {"id": 2, "name": "Mopa", "title": "Mopa 30"}}
    out = run(tmp_path, {"work": "7"}, """
  const line = tree.querySelectorAll('p').find((p) => p.getAttribute('aria-label') === 'Лазер, линза и титан этой работы');
  out.line = line.textContent;
""", context=other)
    assert out["line"] == "Laser: JPT 60 · lens: F-Theta · 174 mm · stock: Big Plate 150 · measurements: this workshop"


CHANGE = """
  await button(tree, 'Новая работа').dispatch('click'); await settle();
  const box = dialog();
  const open = box.querySelectorAll('button').find((b) => b.textContent === 'Change…');
  out.heading = box.querySelector('.work-context').textContent.slice(0, 40);
  await open.dispatch('click'); await settle();
  const nested = ctx.document.body.querySelectorAll('.modal')[1];
  out.nested = [nested.querySelector('h3').textContent, nested.textContent.includes('Measurement source')];
  const stock = nested.querySelectorAll('.matpick').find((x) => x.getAttribute('aria-label') === 'Stock');            // the titanium is the stock selector, no longer a drop-down
  await button(stock, 'Choose…').dispatch('click'); await settle();                                              // its own dialog opens above this one
  const chooser = ctx.document.body.querySelectorAll('.modal')[2];
  await button(chooser.querySelectorAll('.lst-row').find((r) => r.textContent.includes('Sheet')), 'Choose').dispatch('click'); await settle();
  out.warned = [nested.textContent.includes('The titanium grade is different'), requests.filter((r) => r.path === '/api/creation/context' && r.method === 'PUT').length];
  await nested.querySelectorAll('button').find((b) => b.textContent === 'Apply').dispatch('click'); await settle();
  out.put = requests.filter((r) => r.path === '/api/creation/context' && r.method === 'PUT').map((r) => r.body);
  out.shown = box.querySelector('.work-context').textContent;
  out.stillOpen = ctx.document.body.querySelectorAll('.modal').length;
  const file = input(box, (i) => i.getAttribute('type') === 'file');
  file.files = [{name: 'moto.jpg', size: 4096}]; await file.dispatch('change');
  await button(box, 'Дальше →').dispatch('click'); await settle();
  out.posts = requests.filter((r) => r.path === '/api/photo-works' && r.method === 'POST').map((r) => r.body);
  out.second = dialog().querySelector('h3').textContent;
  out.toast = ctx.document.body.querySelector('.toasts') ? ctx.document.body.querySelector('.toasts').textContent : '';
  out.formError = dialog().querySelectorAll('.f-form-error').map((n) => n.textContent).join(' ');          // a refusal stands in the dialog, beside the form
"""


@node
def test_the_dialog_of_new_work_changes_the_shared_choice_by_the_creation_dialog_and_makes_the_work_on_a_scale_of_the_new_choice(tmp_path):
    scales = [scale(100, [2, 25])]
    scales[0]["mode"] = {**scales[0]["mode"], "material_id": 4}
    out = run(tmp_path, {}, CHANGE, scales=scales)
    assert out["heading"].startswith("Работа делается на") and out["nested"] == ["New work context", False]       # the source is chosen below in this dialog
    assert out["warned"] == [True, 0]                                                                          # read before «Apply»: nothing is saved yet
    assert out["put"] == [{"device_id": 1, "lens_id": 2, "material_id": 4, "source": None}] and "Sheet" in out["shown"] and out["stillOpen"] == 1
    [sent] = out["posts"]
    assert json.loads(sent["scale"])["material_id"] == 4                                                       # the work is made on the new choice's own scale
    assert out["second"] == "New work · step 2 of 2: which engraving?"                                      # BUG-003: the kind step is still the second


@node
def test_a_choice_changed_to_a_setup_without_a_measured_scale_is_told_and_no_work_is_made_on_another_laser_scale(tmp_path):
    out = run(tmp_path, {}, CHANGE)                                                # the scales of the workshop are measured on titanium 3 only
    assert out["posts"] == [] and out["second"] == "Новая работа · шаг 1 из 2: картинка"
    assert "нет измеренной шкалы серого" in out["formError"] and "нет измеренной шкалы серого" not in out["toast"]


def test_the_dialog_of_photo_engraving_and_the_creation_screen_ask_which_kind_of_engraving_through_one_function():
    shared = (UI / "screens" / "photo-kind-step.js").read_text(encoding="utf-8")
    engraving = (UI / "screens" / "photo-engraving.js").read_text(encoding="utf-8")
    creation = (UI / "screens" / "creation.js").read_text(encoding="utf-8")
    assert "PhotoKindStep.open(" in engraving and "PhotoKindStep.open(" in creation                          # BUG-003: the same question in both places
    assert "kindTiles(" in shared and "kindTiles(" not in engraving and "kindTiles(" not in creation          # the tiles are drawn in one place only
    assert "which engraving" in shared
