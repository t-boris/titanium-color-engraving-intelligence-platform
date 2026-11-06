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
      const picker = ctx.MaterialPicker.create({initial: 'recent', name: 'Material and stock', onChange: (m) => changes.push(m && m.id)});
      mount(picker);
      await picker.ready;
      out.chosen = {value: picker.value, label: q(picker, '.matpick-label').textContent, changes, record: picker.record.name,
        asked: requests('/api/materials').map((x) => x.url), role: picker.getAttribute('role'), name: picker.getAttribute('aria-label')};
    """, EXPORTS)
    assert out["chosen"]["value"] == "7" and out["chosen"]["changes"] == [7]
    assert out["chosen"]["label"] == "Sheet 7 · Ti-6Al-4V · batch B-0007 · 1 mm"                      # the grade and the batch are told apart
    assert out["chosen"]["asked"] == ["/api/materials?limit=1&sort=recent"]                           # one record asked of the server, not the catalogue
    assert (out["chosen"]["role"], out["chosen"]["name"]) == ("group", "Material and stock")


def test_the_dialog_offers_recent_records_a_search_and_pages_and_gives_the_focus_back(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, FILES, """
      const changes = [];
      const picker = ctx.MaterialPicker.create({initial: 'recent', onChange: (m) => changes.push(m.id)});
      mount(picker);
      await picker.ready;
      const opener = button(picker, 'Choose…');
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
      await until(() => count(dialog) === 'showing 1 of 1');
      out.row = q(rows(dialog)[0], '.lst-main').textContent;
      await button(rows(dialog)[0], 'Choose').dispatch('click');
      out.after = {open: q(doc.body, '.modal') !== null, value: picker.value, label: q(picker, '.matpick-label').textContent, changes, focus: doc.activeElement === opener,
        inert: doc.body.children.map((c) => c.hasAttribute('inert'))};
    """, EXPORTS)
    assert out["dialog"]["title"] == "Choose stock" and out["dialog"]["modal"] == "true" and out["dialog"]["count"] == "showing 20 of 200"
    assert out["dialog"]["recent"] == ["Sheet 7 · Ti-6Al-4V · batch B-0007 · 1 mm", "Sheet 42 · Grade 5 · batch B-0042 · 1 mm"]     # the latest use first
    assert out["dialog"]["firstRow"] == "Sheet 1" and out["dialog"]["pinned"] == ["Selected"]       # the record chosen now stays in view though the page does not hold it
    assert all("limit=" in url for url in out["dialog"]["asked"])
    assert "Sheet 137" in out["row"] and "batch B-0137" in out["row"]
    assert {k: v for k, v in out["after"].items() if k != "label"} == {"open": False, "value": "137", "changes": [7, 137], "focus": True, "inert": [False]}
    assert out["after"]["label"].startswith("Sheet 137 · ") and "batch B-0137" in out["after"]["label"]


def test_the_grade_narrows_the_dialog_and_escape_closes_it_without_a_choice(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, FILES, """
      const picker = ctx.MaterialPicker.create({value: 5});
      mount(picker);
      await picker.ready;
      const opener = button(picker, 'Choose…');
      opener.focus();
      await opener.dispatch('click');
      const dialog = q(doc.body, '.modal');
      await until(() => rows(dialog).length === 20);
      const grade = qa(dialog, 'label').find((l) => l.textContent.startsWith('Grade')).querySelector('select');
      grade.value = 'grade 2';
      await grade.dispatch('change');
      await until(() => count(dialog) === 'showing 20 of 50');
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
      const picker = ctx.MaterialPicker.create({allowEmpty: true, empty: 'not selected', onChange: (m) => changes.push(m && m.id)});
      mount(picker);
      await picker.ready;
      out.empty = {value: picker.value, label: q(picker, '.matpick-label').textContent, clear: q(picker, '.matpick-clear').hidden};
      picker.value = '12';
      await until(() => picker.record !== null);
      out.set = {value: picker.value, label: q(picker, '.matpick-label').textContent, clear: q(picker, '.matpick-clear').hidden};
      picker.value = '99999';
      await until(() => q(picker, '.matpick-label').textContent.includes('is unavailable'));
      out.missing = {value: picker.value, label: q(picker, '.matpick-label').textContent, record: picker.record};
      picker.value = '12';
      await until(() => picker.record !== null);
      await q(picker, '.matpick-clear').dispatch('click');
      out.cleared = {value: picker.value, label: q(picker, '.matpick-label').textContent, changes, clear: q(picker, '.matpick-clear').hidden};
    """, EXPORTS)
    assert out["empty"] == {"value": "", "label": "not selected", "clear": True}
    assert out["set"]["value"] == "12" and out["set"]["label"].startswith("Sheet 12 · ") and out["set"]["clear"] is False
    assert out["missing"]["value"] == "99999" and out["missing"]["record"] is None and out["missing"]["label"].startswith("Stock #99999 is unavailable")
    assert out["cleared"] == {"value": "", "label": "not selected", "changes": [None], "clear": True}


def test_late_stock_responses_cannot_replace_a_newer_choice_or_clear(workshop, tmp_path):
    _, port = workshop
    out = run_node(tmp_path, port, FILES, """
      const delayed = hold('/api/materials/12');
      const picker = ctx.MaterialPicker.create();
      mount(picker);
      picker.value = '12';
      await until(() => delayed.seen);
      picker.value = '13';
      await until(() => picker.record && picker.record.id === 13);
      delayed.release();
      await sleep(100);
      out.selected = {value: picker.value, record: picker.record.id, label: q(picker, '.matpick-label').textContent};

      const recent = hold('/api/materials?limit=1&sort=recent');
      const changes = [];
      const other = ctx.MaterialPicker.create({initial: 'recent', onChange: (m) => changes.push(m)});
      await until(() => recent.seen);
      other.value = '';
      recent.release();
      await other.ready;
      out.cleared = {value: other.value, record: other.record, changes};
    """, EXPORTS)
    assert out["selected"]["value"] == "13" and out["selected"]["record"] == 13
    assert out["selected"]["label"].startswith("Sheet 13 · ")
    assert out["cleared"] == {"value": "", "record": None, "changes": []}


def test_a_failed_read_in_the_dialog_is_said_and_can_be_retried(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, FILES, """
      const picker = ctx.MaterialPicker.create({value: 3});
      mount(picker);
      await picker.ready;
      breakNext('/api/materials?');
      await button(picker, 'Choose…').dispatch('click');
      const dialog = q(doc.body, '.modal');
      await until(() => q(dialog, '.lst-fail') !== null);
      out.failed = {text: q(dialog, '.lst-fail').textContent, rows: rows(dialog).length};
      await q(dialog, '.lst-retry').dispatch('click');
      await until(() => rows(dialog).length === 20);
      out.retried = {fail: q(dialog, '.lst-fail') !== null, count: count(dialog)};
    """, EXPORTS)
    assert "Cannot reach the local service" in out["failed"]["text"] and out["failed"]["rows"] == 0
    assert out["retried"] == {"fail": False, "count": "showing 20 of 200"}


def test_the_link_to_the_catalogue_closes_the_dialog_so_it_does_not_stay_over_the_next_screen(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, FILES, """
      const picker = ctx.MaterialPicker.create({value: 3});
      mount(picker);
      await picker.ready;
      await button(picker, 'Choose…').dispatch('click');
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
          await button(picker, 'Choose…').dispatch('click');
          const dialog = q(doc.body, '.modal');
          await until(() => rows(dialog).length === 20);
          out.rows = rows(dialog).length;
          out.count = count(dialog);
          out.unbounded = requests('/api/materials').filter((x) => (x.url === '/api/materials' || x.url.startsWith('/api/materials?')) && !x.url.includes('limit=')).length;   // list reads only; one record by its number is another route
          out.label = q(picker, '.matpick-label').textContent;
        """, EXPORTS)
    assert out["rows"] == 20 and out["count"] == "showing 20 of 2000" and out["unbounded"] == 0
    assert out["label"].startswith("Sheet 2000 · ")                                                  # nothing used yet: the newest record
