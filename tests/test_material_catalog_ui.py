"""The catalogue of titanium stock records (feature ux-growing-collections-p0, REQ-001, REQ-003, REQ-004): compact rows a page of twenty at a
time with 20, 200 and 2000 records, separate forms for adding and for editing, the editor only for the record chosen (and for the one the
address names), a search that never takes the typed text away, a record outside the page kept in view, a failed read with a retry and a save
that cannot be sent twice. Run in node over a small DOM against the real server; a real browser and a screen reader add layout, the
cursor and speech, which are not covered here."""
import pytest

from growing_ui import fill_materials, node, run_node, serving

pytestmark = node
FILES = ["screens/material-catalog.js"]
EXPORTS = ("MaterialCatalog",)
OPEN = """
  const el = await ctx.MaterialCatalog.tab({query: %s});
  const box = mount(el);
"""


def catalogue(tmp_path, count):
    cm = serving(tmp_path / "data")
    app, port = cm.__enter__()
    fill_materials(app.state.store, count)
    return cm, app.state.store, port


@pytest.fixture
def small(tmp_path):
    cm, store, port = catalogue(tmp_path, 200)
    yield store, port
    cm.__exit__(None, None, None)


@pytest.mark.parametrize("count", [20, 200, 2000])
def test_the_catalogue_draws_twenty_compact_rows_whatever_its_size(tmp_path, count):
    cm, store, port = catalogue(tmp_path, count)
    try:
        out = run_node(tmp_path, port, FILES, OPEN % "{}" + """
          out.asked = requests('/api/materials').map((x) => x.url);
          out.first = {rows: rows(box).length, count: count(box), editor: q(box, '.mat-editor') !== null};
          out.parts = rows(box).slice(0, 4).map((r) => ({name: qa(r, 'strong')[0].textContent, grade: qa(r, '.mat-grade').map((n) => n.textContent),
            batch: qa(r, '.mat-batch').map((n) => n.textContent), thickness: qa(r, '.mat-thickness').map((n) => n.textContent), text: q(r, '.lst-main').textContent}));
          out.more = button(box, 'Show 20 more') !== null;
          if (out.more) {
            await button(box, 'Show 20 more').dispatch('click');
            await until(() => rows(box).length === 40);
            out.second = {count: count(box), asked: requests('/api/materials').slice(1).map((x) => x.url)};
          }
        """, EXPORTS)
    finally:
        cm.__exit__(None, None, None)
    assert out["asked"] == ["/api/materials?offset=0&limit=20&sort=recent"]                       # one page of twenty, never the whole catalogue
    shown = min(20, count)
    assert out["first"] == {"rows": shown, "count": f"showing {shown} of {count}", "editor": False}   # no form is drawn until a record is chosen
    first = out["parts"][0]
    assert first["name"] == f"Лист {count}" and first["batch"] == [f"партия B-{count:04d}"]       # the newest first while nothing has been used
    grades = ("Grade 2", "Grade 5", "Ti-6Al-4V", None)
    for row, number in zip(out["parts"], range(count, count - 4, -1)):
        grade = grades[(number - 1) % 4]
        assert row["grade"] == ([grade] if grade else []) and (grade or "марка не указана" in row["text"])    # the grade and the batch are told apart; a missing grade is said
        assert row["thickness"] == [f"{+(0.5 + ((number - 1) % 5) * 0.5):g} мм"]
    assert out["more"] is (count > 20)
    if count > 20:
        assert out["second"] == {"count": f"showing 40 of {count}", "asked": ["/api/materials?offset=20&limit=20&sort=recent"]}


def test_a_search_a_grade_and_an_order_are_asked_of_the_server_and_kept_in_the_address(small, tmp_path):
    store, port = small
    out = run_node(tmp_path, port, FILES, OPEN % "{}" + """
      const search = q(box, '.lst-search');
      search.focus();
      search.value = 'b-0137';
      await search.dispatch('input');
      await until(() => count(box) === 'showing 1 of 1');
      out.found = {names: rows(box).map((r) => qa(r, 'strong')[0].textContent), asked: requests('/api/materials?').pop().url, focus: doc.activeElement === search};
      await button(box, 'Clear search and filters').dispatch('click');
      await until(() => count(box) === 'showing 20 of 200');
      const grade = qa(box, 'label').find((l) => l.textContent.startsWith('Марка')).querySelector('select');
      out.options = grade.options.map((o) => o.textContent);
      grade.value = 'grade 5';
      await grade.dispatch('change');
      await until(() => count(box) === 'showing 20 of 50');
      const order = qa(box, 'select').find((s) => s.getAttribute('aria-label') === 'Sort order');
      out.orders = order.options.map((o) => o.textContent);
      order.value = 'thickness';
      await order.dispatch('change');
      await until(() => requests('/api/materials?').pop().url.includes('sort=thickness'));
      await sleep(30);
      out.grade = {asked: requests('/api/materials?').pop().url, hash: ctx.location.hash, thicknesses: rows(box).slice(0, 3).map((r) => qa(r, '.mat-thickness')[0].textContent)};
      search.value = 'нет такого';
      await search.dispatch('input');
      await until(() => q(box, '.lst-none') !== null);
      out.none = q(box, '.lst-empty').textContent;
    """, EXPORTS)
    assert out["found"] == {"names": ["Лист 137"], "asked": "/api/materials?offset=0&limit=20&sort=recent&search=b-0137", "focus": True}   # the cursor stays in the field
    assert out["options"][:3] == ["all · 200", "Grade 2 · 50", "Grade 5 · 50"] and "без марки · 50" in out["options"]
    assert out["orders"] == ["Недавно использованные", "По названию", "По марке", "По толщине", "Недавно добавленные"]
    assert "grade=grade+5" in out["grade"]["asked"] and "sort=thickness" in out["grade"]["asked"]
    assert out["grade"]["hash"].startswith("#/setup?tab=material") and "grade=grade+5" in out["grade"]["hash"] and "sort=thickness" in out["grade"]["hash"]
    assert out["grade"]["thicknesses"] == ["0.5 мм"] * 3
    assert out["none"] == "Ни одна заготовка не подходит под поиск и фильтры."


def test_adding_and_editing_are_separate_forms_and_the_editor_is_for_the_chosen_record_only(small, tmp_path):
    store, port = small
    out = run_node(tmp_path, port, FILES, OPEN % "{}" + """
      const editors = () => qa(box, '.mat-editor').map((e) => e.getAttribute('aria-label'));
      out.start = editors();
      await button(box, 'Добавить материал').dispatch('click');
      out.add = {editors: editors(), focus: doc.activeElement === qa(q(box, '.mat-editor'), 'input')[0], save: button(q(box, '.mat-editor'), 'Сохранить материал') !== null,
        create: button(q(box, '.mat-editor'), 'Добавить материал') !== null};
      const target = rows(box)[2];
      await button(target, 'Изменить').dispatch('click');
      await until(() => editors()[0] === 'Материал № ' + target.getAttribute('data-key'));
      const form = q(box, '.mat-editor');
      out.edit = {editors: editors(), id: target.getAttribute('data-key'), name: qa(form, 'input')[0].value, batch: qa(form, 'input')[3].value,
        save: button(form, 'Сохранить материал') !== null, create: button(form, 'Добавить материал') !== null, focus: doc.activeElement === qa(form, 'input')[0],
        hash: ctx.location.hash};
      await button(rows(box)[5], 'Изменить').dispatch('click');                                  // another record: the editor is replaced, never doubled
      await until(() => editors()[0] === 'Материал № ' + rows(box)[5].getAttribute('data-key'));
      out.another = editors();
      await button(box, 'Добавить материал').dispatch('click');                                  // adding while editing: the add form replaces the editor
      out.back = {editors: editors(), hash: ctx.location.hash};
    """, EXPORTS)
    assert out["start"] == []
    assert out["add"] == {"editors": ["Добавить материал"], "focus": True, "save": False, "create": True}
    assert out["edit"]["editors"] == [f"Материал № {out['edit']['id']}"] and out["edit"]["name"] == "Лист 198" and out["edit"]["batch"] == "B-0198"
    assert out["edit"]["save"] and not out["edit"]["create"] and out["edit"]["focus"] and f"material={out['edit']['id']}" in out["edit"]["hash"]
    assert len(out["another"]) == 1
    assert out["back"]["editors"] == ["Добавить материал"] and "material=" not in out["back"]["hash"]


def test_a_new_record_is_saved_once_and_appears_in_the_list(small, tmp_path):
    store, port = small
    out = run_node(tmp_path, port, FILES, OPEN % "{}" + """
      await button(box, 'Добавить материал').dispatch('click');
      const form = q(box, '.mat-editor');
      const [name, family, grade, batch, thickness, surface] = qa(form, 'input');
      name.value = 'Новый лист'; grade.value = 'Grade 7'; batch.value = 'N-77'; thickness.value = '1.5';
      const gate = hold('/api/materials', 'POST');
      const save = button(form, 'Добавить материал');
      const first = save.dispatch('click');
      await until(() => gate.seen);
      out.during = {disabled: save.disabled};
      save.dispatch('click'); save.dispatch('click');                                             // a second click while the request is on its way
      await sleep(30);
      out.posts = requests('/api/materials').filter((x) => x.method === 'POST').length;
      gate.release();
      await first;
      await until(() => q(box, '.mat-editor') && q(box, '.mat-editor').getAttribute('aria-label').startsWith('Материал №'));
      await until(() => rows(box)[0] && qa(rows(box)[0], 'strong')[0].textContent === 'Новый лист');
      out.saved = {body: JSON.parse(requests('/api/materials').filter((x) => x.method === 'POST')[0].body), editor: q(box, '.mat-editor').getAttribute('aria-label'),
        toast: qa(doc.body, '.toast').map((t) => t.textContent), first: q(rows(box)[0], '.lst-main').textContent, count: count(box), hash: ctx.location.hash};
    """, EXPORTS)
    assert out["during"] == {"disabled": True} and out["posts"] == 1
    assert out["saved"]["body"] == {"name": "Новый лист", "family": "Titanium", "grade": "Grade 7", "batch": "N-77", "thickness_mm": 1.5, "surface": None}
    assert out["saved"]["editor"] == "Материал № 201" and "Материал сохранён" in out["saved"]["toast"][0]
    assert "Grade 7" in out["saved"]["first"] and "партия N-77" in out["saved"]["first"] and "1.5 мм" in out["saved"]["first"]
    assert out["saved"]["count"] == "showing 20 of 201" and "material=201" in out["saved"]["hash"]
    assert store.one("SELECT name, batch FROM material_profile WHERE id=201")["batch"] == "N-77"


def test_a_refused_save_keeps_the_form_and_what_was_typed(small, tmp_path):
    """A missing name is refused beside its box before anything is sent (ux-save-feedback-p0, REQ-003); what was typed stays, the form is the same one."""
    store, port = small
    out = run_node(tmp_path, port, FILES, OPEN % "{}" + """
      await button(box, 'Добавить материал').dispatch('click');
      const form = q(box, '.mat-editor');
      const inputs = qa(form, 'input');
      inputs[2].value = 'Grade 9';                                                                  // a name is missing
      inputs[4].value = '-1';                                                                       // and a thickness below zero
      const save = button(form, 'Добавить материал');
      await save.dispatch('click');
      const field = (text) => qa(form, 'label').find((l) => l.firstChild.textContent === text);
      out.refused = {name: field('Название').errorText(), thickness: field('Толщина').errorText(), enabled: !save.disabled, same: q(box, '.mat-editor') === form, grade: inputs[2].value,
        thicknessKept: inputs[4].value, summary: q(form, '.f-form-error').textContent, toasts: qa(doc.body, '.toast.bad').length,
        posts: requests('/api/materials').filter((x) => x.method === 'POST').length, count: count(box), invalid: inputs[0].getAttribute('aria-invalid')};
    """, EXPORTS)
    assert out["refused"]["same"] and out["refused"]["enabled"] and out["refused"]["grade"] == "Grade 9" and out["refused"]["posts"] == 0 and out["refused"]["toasts"] == 0
    assert out["refused"]["name"] == "Complete this field" and out["refused"]["thickness"] == "Allowed: greater than 0 mm. Entered: -1" and out["refused"]["thicknessKept"] == "-1"
    assert out["refused"]["summary"] == "Not submitted: correct fields “Название”, “Толщина”. Your entries remain in the form." and out["refused"]["invalid"] == "true"
    assert out["refused"]["count"] == "showing 20 of 200"


def test_a_change_is_saved_once_and_the_typed_text_survives_a_search(small, tmp_path):
    store, port = small
    out = run_node(tmp_path, port, FILES, OPEN % "{}" + """
      const row = rows(box)[0];
      const id = row.getAttribute('data-key');
      await button(row, 'Изменить').dispatch('click');
      await until(() => q(box, '.mat-editor') !== null);
      const form = q(box, '.mat-editor');
      const inputs = qa(form, 'input');
      inputs[0].value = 'Переименованный лист';
      const search = q(box, '.lst-search');
      search.value = 'b-0010';
      await search.dispatch('input');
      await until(() => count(box) === 'showing 1 of 1');
      out.typed = {same: q(box, '.mat-editor') === form, name: inputs[0].value, pinned: q(box, '.lst-pin-note') !== null,
        note: q(box, '.lst-pin-note') ? q(box, '.lst-pin-note').textContent.trim() : null, pinnedName: q(box, '.lst-pin') ? qa(q(box, '.lst-pin'), 'strong')[0].textContent : null};
      const gate = hold('/api/materials/' + id, 'PUT');
      const save = button(form, 'Сохранить материал');
      const first = save.dispatch('click');
      await until(() => gate.seen);
      save.dispatch('click');
      await sleep(30);
      out.puts = requests('/api/materials/' + id).filter((x) => x.method === 'PUT').length;
      gate.release();
      await first;
      await until(() => !save.disabled);
      await sleep(30);
      out.saved = {id, body: JSON.parse(requests('/api/materials/' + id).filter((x) => x.method === 'PUT')[0].body).name, editor: q(box, '.mat-editor').getAttribute('aria-label')};
    """, EXPORTS)
    assert out["typed"]["same"] and out["typed"]["name"] == "Переименованный лист"                # the search did not take the typed text away
    assert out["typed"]["pinned"] and out["typed"]["pinnedName"] == "Лист 200"                       # the record being edited is kept in view though the search hides it
    assert out["typed"]["note"].startswith("The selected row")
    assert out["puts"] == 1 and out["saved"]["body"] == "Переименованный лист" and out["saved"]["editor"] == f"Материал № {out['saved']['id']}"
    assert store.one("SELECT name FROM material_profile WHERE id=?", (out["saved"]["id"],))["name"] == "Переименованный лист"


def test_the_record_named_in_the_address_opens_and_is_kept_in_view_beyond_the_first_page(small, tmp_path):
    store, port = small
    out = run_node(tmp_path, port, FILES, OPEN % "{material: '37'}" + """
      const pin = q(box, '.lst-pin');
      out.open = {editor: q(box, '.mat-editor').getAttribute('aria-label'), name: qa(q(box, '.mat-editor'), 'input')[0].value, rows: rows(box).length,
        note: q(pin, '.lst-pin-note').textContent.trim(), pinned: qa(pin, 'strong')[0].textContent, asked: requests('/api/materials/37').length};
      await button(pin, 'Clear selection').dispatch('click');
      await until(() => q(box, '.lst-pin') === null);
      out.cleared = {editors: qa(box, '.mat-editor').length, hash: ctx.location.hash, focus: doc.activeElement && doc.activeElement.textContent};
    """, EXPORTS)
    assert out["open"]["editor"] == "Материал № 37" and out["open"]["name"] == "Лист 37" and out["open"]["rows"] == 20
    assert out["open"]["note"].startswith("The selected row is beyond the displayed portion of the list.") and out["open"]["pinned"] == "Лист 37"
    assert out["cleared"]["editors"] == 0 and "material=" not in out["cleared"]["hash"]


def test_a_record_that_is_not_there_is_said_not_skipped(small, tmp_path):
    store, port = small
    out = run_node(tmp_path, port, FILES, OPEN % "{material: '99999'}" + """
      out.alert = {role: q(box, '.alert.bad').getAttribute('role'), text: q(box, '.alert.bad').textContent, pin: q(box, '.lst-pin-note').textContent.trim(), rows: rows(box).length};
      await button(q(box, '.alert.bad'), 'Закрыть').dispatch('click');
      await until(() => q(box, '.alert.bad') === null);
      out.closed = {hash: ctx.location.hash, editors: qa(box, '.mat-editor').length};
    """, EXPORTS)
    assert out["alert"]["role"] == "alert" and "Материал № 99999 недоступен" in out["alert"]["text"] and out["alert"]["rows"] == 20
    assert out["alert"]["pin"].startswith("The selected item is unavailable")
    assert "material=" not in out["closed"]["hash"] and out["closed"]["editors"] == 0


def test_a_failed_read_keeps_the_screen_and_offers_a_retry(small, tmp_path):
    store, port = small
    out = run_node(tmp_path, port, FILES, """
      breakNext('/api/materials?');
      const el = await ctx.MaterialCatalog.tab({query: {}});
      const box = mount(el);
      out.failed = {alert: q(box, '.lst-fail').getAttribute('role'), text: q(box, '.lst-fail').textContent, rows: rows(box).length, add: button(box, 'Добавить материал') !== null};
      await q(box, '.lst-retry').dispatch('click');
      await until(() => rows(box).length === 20);
      out.retried = {fail: q(box, '.lst-fail') !== null, count: count(box)};
    """, EXPORTS)
    assert out["failed"]["alert"] == "alert" and "Cannot reach the local service" in out["failed"]["text"] and out["failed"]["rows"] == 0 and out["failed"]["add"]
    assert out["retried"] == {"fail": False, "count": "showing 20 of 200"}


def test_an_empty_catalogue_invites_the_first_record(tmp_path):
    with serving(tmp_path / "data") as (app, port):
        out = run_node(tmp_path, port, FILES, OPEN % "{}" + """
          out.empty = q(box, '.lst-empty').textContent;
          out.rows = rows(box).length;
        """, EXPORTS)
    assert out == {"empty": "Материалов пока нет. Добавьте первую заготовку.", "rows": 0}
