"""The documents of a laser as a compact list (feature ux-growing-collections-p0, REQ-002, REQ-003): a line each, a search, the kind as a
filter, pages of twenty, the details and the original file on request, the document opened last kept in view, and a deletion that asks
first. Run in node over a small DOM against the real server, which keeps the files and says what each is."""
import pytest

from growing_ui import node, run_node, serving
from titanium_platform import devices

pytestmark = node
FILES = ["screens/device-forms.js", "screens/device-view.js"]
EXPORTS = ("DeviceView",)
KINDS = ("test_report", "manual", "other", "waveform")


@pytest.fixture
def laser(tmp_path):
    """A laser with 45 documents: 44 text files of four kinds and, the newest, a scan (a PNG)."""
    with serving(tmp_path / "data") as (app, port):
        store = app.state.store
        device = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
        for i in range(44):
            devices.add_document(store, device["id"], KINDS[i % 4], f"Документ {i + 1}", f"doc{i + 1}.txt", f"содержимое {i + 1}".encode())
        devices.add_document(store, device["id"], "test_report", "Скан паспорта", "scan.png", b"\x89PNG\r\n\x1a\n" + b"0" * 2048)
        yield store, device["id"], port


def card(device_id: int) -> str:
    return f"""
      let reloaded = [];
      const d = await App.get('/devices/{device_id}');
      const box = mount(ctx.DeviceView.documentsCard(d, (id) => reloaded.push(id)));
      await until(() => lines(box).length > 0);
    """


def test_the_documents_are_a_page_of_twenty_not_a_dump_and_every_one_is_reached(laser, tmp_path):
    store, device_id, port = laser
    out = run_node(tmp_path, port, FILES, card(device_id) + """
      out.first = {rows: lines(box).length, count: count(box), newest: qa(lines(box)[0], '.lst-text')[0].textContent, more: button(box, 'Show 20 more') !== null};
      await button(box, 'Show 20 more').dispatch('click');
      await button(box, 'Show 5 more').dispatch('click');
      const keys = lines(box).map((l) => l.getAttribute('data-key'));
      out.all = {rows: keys.length, distinct: new Set(keys).size, count: count(box)};
    """, EXPORTS)
    assert out["first"] == {"rows": 20, "count": "showing 20 of 45", "newest": "Скан паспорта", "more": True}
    assert out["all"] == {"rows": 45, "distinct": 45, "count": "showing 45 of 45"}


def test_a_search_and_the_kind_filter_narrow_the_documents_with_counts(laser, tmp_path):
    store, device_id, port = laser
    out = run_node(tmp_path, port, FILES, card(device_id) + """
      const search = q(box, '.lst-search');
      search.value = 'документ 17';
      await search.dispatch('input');
      await until(() => count(box) === 'showing 1 of 1');
      out.one = {title: qa(lines(box)[0], '.lst-text')[0].textContent, file: lines(box)[0].textContent.includes('doc17.txt')};
      search.value = 'SCAN.PNG';                                                                 // the file name is searched too, whatever the case
      await search.dispatch('input');
      await until(() => count(box) === 'showing 1 of 1' && qa(lines(box)[0], '.lst-text')[0].textContent === 'Скан паспорта');
      search.value = '';
      await search.dispatch('input');
      await until(() => lines(box).length === 20);
      const kind = qa(box, 'label').find((l) => l.textContent.startsWith('Type')).querySelector('select');
      out.options = kind.options.map((o) => o.textContent).slice(0, 3);
      kind.value = 'manual';
      await kind.dispatch('change');
      await until(() => count(box) === 'showing 11 of 11');
      out.manual = {rows: lines(box).length, pills: [...new Set(lines(box).map((l) => qa(l, '.pill')[0].textContent))]};
      search.value = 'нет такого';
      await search.dispatch('input');
      await until(() => q(box, '.lst-none') !== null);
      out.none = q(box, '.lst-empty').textContent;
    """, EXPORTS)
    assert out["one"] == {"title": "Документ 17", "file": True}
    assert out["options"][0] == "all · 45" and out["options"][1] == "Test report · 12"
    assert out["manual"] == {"rows": 11, "pills": ["Manual"]}
    assert out["none"] == "No documents match this name or type."


def test_the_original_stays_one_click_away_with_its_facts_and_the_last_opened_stays_in_view(laser, tmp_path):
    store, device_id, port = laser
    out = run_node(tmp_path, port, FILES, card(device_id) + f"""
      const scan = lines(box)[0];
      const open = qa(scan, 'a')[0];
      out.link = {{href: open.getAttribute('href'), target: open.getAttribute('target'), rel: open.getAttribute('rel'), text: open.textContent}};
      await scan.querySelector('.lst-main').dispatch('click');
      await until(() => qa(box, 'img').length === 1);
      const det = q(box, '.lst-det');
      out.details = {{text: det.textContent, alt: q(det, 'img').getAttribute('alt'), src: q(det, 'img').getAttribute('src')}};
      const search = q(box, '.lst-search');
      search.value = 'документ 3';
      await search.dispatch('input');
      await until(() => q(box, '.lst-pin-note') !== null);
      out.pinned = {{note: q(box, '.lst-pin-note').textContent.trim(), title: qa(q(box, '.lst-pin'), '.lst-text')[0].textContent, reset: button(q(box, '.lst-pin'), 'Clear search and filters') !== null}};
    """, EXPORTS)
    assert out["link"] == {"href": f"/api/devices/{device_id}/documents/45", "target": "_blank", "rel": "noopener", "text": "Open"}
    assert all(word in out["details"]["text"] for word in ("Test report", "scan.png", "Size", "Added"))
    assert out["details"]["alt"] == "Скан паспорта" and out["details"]["src"] == f"/api/devices/{device_id}/documents/45"
    assert out["pinned"]["title"] == "Скан паспорта" and out["pinned"]["note"].startswith("The selected row is hidden") and out["pinned"]["reset"]


def test_a_deletion_asks_first_and_removes_the_document_and_its_line(laser, tmp_path):
    store, device_id, port = laser
    out = run_node(tmp_path, port, FILES, card(device_id) + """
      const scan = lines(box)[0];
      await button(scan, 'Delete').dispatch('click');
      out.dialog = {title: q(doc.body, '.modal').getAttribute('aria-label'), text: q(doc.body, '.modal').textContent.includes('Скан паспорта'), focus: doc.activeElement.textContent,
        sentBefore: requests('/documents/').filter((x) => x.method === 'DELETE').length};
      await button(q(doc.body, '.modal'), 'Cancel').dispatch('click');
      out.cancelled = requests('/documents/').filter((x) => x.method === 'DELETE').length;
      await button(scan, 'Delete').dispatch('click');
      await button(q(doc.body, '.modal'), 'Delete').dispatch('click');
      out.deleted = {requests: requests('/documents/').filter((x) => x.method === 'DELETE').map((x) => x.url), reloaded};
    """, EXPORTS)
    assert out["dialog"] == {"title": "Delete document", "text": True, "focus": "Cancel", "sentBefore": 0} and out["cancelled"] == 0
    assert out["deleted"]["requests"] == [f"/api/devices/{device_id}/documents/45"] and out["deleted"]["reloaded"] == [device_id]
    assert store.one("SELECT COUNT(*) AS n FROM device_document WHERE device_id=?", (device_id,))["n"] == 44


def test_a_laser_without_documents_says_so(tmp_path):
    with serving(tmp_path / "data") as (app, port):
        device = devices.create_from_template(app.state.store, "jpt-ydflp-e-60-m7-m-r")
        out = run_node(tmp_path, port, FILES, f"""
          const d = await App.get('/devices/{device['id']}');
          const box = mount(ctx.DeviceView.documentsCard(d, () => {{}}));
          out.text = box.textContent.includes('No documents yet');
          out.list = q(box, '.lst') !== null;
        """, EXPORTS)
    assert out == {"text": True, "list": False}
