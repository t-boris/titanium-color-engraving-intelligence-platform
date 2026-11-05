"""The selector for a titanium stock record (feature ux-growing-collections-p0, REQ-001): the record used last chosen at once, a dialog with the
records used last, a search and the catalogue a page of twenty at a time, a record that is always one concrete batch or sheet (its grade told
apart from its batch), and the screen of the research that starts a session with it. Run in node over a small DOM against the real server."""
import pytest

import obs
from growing_ui import fill_materials, node, run_node, serving

pytestmark = node
FILES = ["screens/material-picker.js"]
EXPORTS = ("MaterialPicker",)


def use(store, material_id: int, when: str) -> None:
    """A photograph work on the record, at the given time: it is the record used last."""
    w = obs.setup(store)
    observation = obs.add(store, w, (50, 0, 0), material_id=material_id)
    store.execute("UPDATE pair SET created_at=? WHERE id=(SELECT pair_id FROM observation WHERE id=?)", (when, observation))


@pytest.fixture
def workshop(tmp_path):
    """Two hundred records; the 42nd used in January, the 7th in February."""
    with serving(tmp_path / "data") as (app, port):
        fill_materials(app.state.store, 200)
        use(app.state.store, 42, "2026-01-10T10:00:00")
        use(app.state.store, 7, "2026-02-10T10:00:00")
        yield app.state.store, port


def test_the_record_used_last_is_chosen_at_once_and_told_by_its_grade_batch_and_thickness(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, FILES, """
      const changes = [];
      const picker = ctx.MaterialPicker.create({initial: 'recent', name: 'Материал и заготовка', onChange: (m) => changes.push(m && m.id)});
      mount(picker);
      await picker.ready;
      out.chosen = {value: picker.value, label: q(picker, '.matpick-label').textContent, changes, record: picker.record.name,
        asked: requests('/api/materials').map((x) => x.url), role: picker.getAttribute('role'), name: picker.getAttribute('aria-label')};
    """, EXPORTS)
    assert out["chosen"]["value"] == "7" and out["chosen"]["changes"] == [7]
    assert out["chosen"]["label"] == "Лист 7 · Ti-6Al-4V · партия B-0007 · 1 мм"                      # the grade and the batch are told apart
    assert out["chosen"]["asked"] == ["/api/materials?limit=1&sort=recent"]                           # one record asked of the server, not the catalogue
    assert (out["chosen"]["role"], out["chosen"]["name"]) == ("group", "Материал и заготовка")


def test_the_dialog_offers_recent_records_a_search_and_pages_and_gives_the_focus_back(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, FILES, """
      const changes = [];
      const picker = ctx.MaterialPicker.create({initial: 'recent', onChange: (m) => changes.push(m.id)});
      mount(picker);
      await picker.ready;
      const opener = button(picker, 'Выбрать…');
      opener.focus();
      await opener.dispatch('click');
      const dialog = q(doc.body, '.modal');
      await until(() => rows(dialog).length === 20 && qa(dialog, '.matpick-recent-item').length === 2);
      out.dialog = {title: dialog.getAttribute('aria-label'), modal: dialog.getAttribute('aria-modal'), count: count(dialog), focus: doc.activeElement.getAttribute('aria-label'),
        recent: qa(dialog, '.matpick-recent-item').map((b) => b.textContent), firstRow: qa(rows(dialog)[0], 'strong')[0].textContent,
        pinned: q(dialog, '.lst-pin') ? qa(q(q(dialog, '.lst-pin'), '.lst-act'), 'button').map((b) => b.textContent) : null, asked: requests('/api/materials?').slice(1).map((x) => x.url)};
      const search = q(dialog, '.lst-search');
      search.value = 'b-0137';
      await search.dispatch('input');
      await until(() => count(dialog) === 'показано 1 из 1');
      out.row = q(rows(dialog)[0], '.lst-main').textContent;
      await button(rows(dialog)[0], 'Выбрать').dispatch('click');
      out.after = {open: q(doc.body, '.modal') !== null, value: picker.value, label: q(picker, '.matpick-label').textContent, changes, focus: doc.activeElement === opener,
        inert: doc.body.children.map((c) => c.hasAttribute('inert'))};
    """, EXPORTS)
    assert out["dialog"]["title"] == "Выбор заготовки" and out["dialog"]["modal"] == "true" and out["dialog"]["count"] == "показано 20 из 200"
    assert out["dialog"]["recent"] == ["Лист 7 · Ti-6Al-4V · партия B-0007 · 1 мм", "Лист 42 · Grade 5 · партия B-0042 · 1 мм"]     # the latest use first
    assert out["dialog"]["firstRow"] == "Лист 1" and out["dialog"]["pinned"] == ["Выбрана"]       # the record chosen now stays in view though the page does not hold it
    assert all("limit=" in url for url in out["dialog"]["asked"])
    assert "Лист 137" in out["row"] and "партия B-0137" in out["row"]
    assert {k: v for k, v in out["after"].items() if k != "label"} == {"open": False, "value": "137", "changes": [7, 137], "focus": True, "inert": [False]}
    assert out["after"]["label"].startswith("Лист 137 · ") and "партия B-0137" in out["after"]["label"]


def test_the_grade_narrows_the_dialog_and_escape_closes_it_without_a_choice(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, FILES, """
      const picker = ctx.MaterialPicker.create({value: 5});
      mount(picker);
      await picker.ready;
      const opener = button(picker, 'Выбрать…');
      opener.focus();
      await opener.dispatch('click');
      const dialog = q(doc.body, '.modal');
      await until(() => rows(dialog).length === 20);
      const grade = qa(dialog, 'label').find((l) => l.textContent.startsWith('Марка')).querySelector('select');
      grade.value = 'grade 2';
      await grade.dispatch('change');
      await until(() => count(dialog) === 'показано 20 из 50');
      out.grade = {asked: requests('/api/materials?').pop().url, grades: [...new Set(rows(dialog).map((r) => qa(r, '.pill')[0].textContent))]};
      await doc.dispatch('keydown', {key: 'Escape'});
      out.escaped = {open: q(doc.body, '.modal') !== null, value: picker.value, focus: doc.activeElement === opener};
    """, EXPORTS)
    assert "grade=grade+2" in out["grade"]["asked"] and out["grade"]["grades"] == ["Grade 2"]
    assert out["escaped"] == {"open": False, "value": "5", "focus": True}


def test_a_record_can_be_set_from_outside_cleared_and_a_missing_one_is_said(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, FILES, """
      const changes = [];
      const picker = ctx.MaterialPicker.create({allowEmpty: true, empty: 'не выбрана', onChange: (m) => changes.push(m && m.id)});
      mount(picker);
      await picker.ready;
      out.empty = {value: picker.value, label: q(picker, '.matpick-label').textContent, clear: q(picker, '.matpick-clear').hidden};
      picker.value = '12';
      await until(() => picker.record !== null);
      out.set = {value: picker.value, label: q(picker, '.matpick-label').textContent, clear: q(picker, '.matpick-clear').hidden};
      picker.value = '99999';
      await until(() => q(picker, '.matpick-label').textContent.includes('недоступна'));
      out.missing = {value: picker.value, label: q(picker, '.matpick-label').textContent, record: picker.record};
      picker.value = '12';
      await until(() => picker.record !== null);
      await q(picker, '.matpick-clear').dispatch('click');
      out.cleared = {value: picker.value, label: q(picker, '.matpick-label').textContent, changes, clear: q(picker, '.matpick-clear').hidden};
    """, EXPORTS)
    assert out["empty"] == {"value": "", "label": "не выбрана", "clear": True}
    assert out["set"]["value"] == "12" and out["set"]["label"].startswith("Лист 12 · ") and out["set"]["clear"] is False
    assert out["missing"]["value"] == "99999" and out["missing"]["record"] is None and out["missing"]["label"].startswith("заготовка № 99999 недоступна")
    assert out["cleared"] == {"value": "", "label": "не выбрана", "changes": [None], "clear": True}


def test_a_failed_read_in_the_dialog_is_said_and_can_be_retried(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, FILES, """
      const picker = ctx.MaterialPicker.create({value: 3});
      mount(picker);
      await picker.ready;
      breakNext('/api/materials?');
      await button(picker, 'Выбрать…').dispatch('click');
      const dialog = q(doc.body, '.modal');
      await until(() => q(dialog, '.lst-fail') !== null);
      out.failed = {text: q(dialog, '.lst-fail').textContent, rows: rows(dialog).length};
      await q(dialog, '.lst-retry').dispatch('click');
      await until(() => rows(dialog).length === 20);
      out.retried = {fail: q(dialog, '.lst-fail') !== null, count: count(dialog)};
    """, EXPORTS)
    assert "Нет связи" in out["failed"]["text"] and out["failed"]["rows"] == 0
    assert out["retried"] == {"fail": False, "count": "показано 20 из 200"}


def test_the_link_to_the_catalogue_closes_the_dialog_so_it_does_not_stay_over_the_next_screen(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, FILES, """
      const picker = ctx.MaterialPicker.create({value: 3});
      mount(picker);
      await picker.ready;
      await button(picker, 'Выбрать…').dispatch('click');
      const dialog = q(doc.body, '.modal');
      const link = qa(dialog, 'a').find((a) => a.getAttribute('href') === '#/setup?tab=material');
      out.href = link.getAttribute('href');
      await link.dispatch('click');
      out.open = q(doc.body, '.modal') !== null;
    """, EXPORTS)
    assert out == {"href": "#/setup?tab=material", "open": False}


def test_a_catalogue_of_two_thousand_is_never_read_whole(tmp_path):
    with serving(tmp_path / "data") as (app, port):
        fill_materials(app.state.store, 2000)
        out = run_node(tmp_path, port, FILES, """
          const picker = ctx.MaterialPicker.create({initial: 'recent'});
          mount(picker);
          await picker.ready;
          await button(picker, 'Выбрать…').dispatch('click');
          const dialog = q(doc.body, '.modal');
          await until(() => rows(dialog).length === 20);
          out.rows = rows(dialog).length;
          out.count = count(dialog);
          out.unbounded = requests('/api/materials').filter((x) => (x.url === '/api/materials' || x.url.startsWith('/api/materials?')) && !x.url.includes('limit=')).length;   // list reads only; one record by its number is another route
          out.label = q(picker, '.matpick-label').textContent;
        """, EXPORTS)
    assert out["rows"] == 20 and out["count"] == "показано 20 из 2000" and out["unbounded"] == 0
    assert out["label"].startswith("Лист 2000 · ")                                                  # nothing used yet: the newest record
