"""The selector of a stock record in every place that used to build a drop-down of all records (feature ux-growing-collections-p0, REQ-001,
criterion 3: «the choice of a stock record offers search and the records used last, keeping the difference between a grade and one concrete
batch/sheet»). Seven places: the form of a new vector work, the «Проверить у себя» dialog of a laboratory, the plate dialog (with its «new
material» form), the photo-engraving preview, the dialog that changes the workshop's shared choice, the filter of the experiments overview
and the upload form of a work with its photograph. For each, with two hundred stock records in the real application (the screens run in node
over the small DOM and reach the real API of a server on a free port): (1) no option or row per record is drawn, the control is one line;
(2) the chosen record's number reaches the request the screen sends, as it did from the drop-down; (3) a remembered or preset number is
selected; (4) with no stock record at all the screen still says so, and no request reads the whole catalogue. What a real browser adds (the
focus on its way back from the dialog, the keyboard, the look of the line) is not covered here."""
import re

import pytest

from growing_ui import fill_materials, node, run_node, serving
from test_ui_labs import CHOICES, SOURCE
from titanium_platform import creation_context, devices, lenses, setup as su

pytestmark = node
PICKER = "screens/material-picker.js"
EXPORTS = ("MaterialPicker",)
FORM_DATA = "ctx.FormData = class { constructor() { this.items = []; } append(k, v) { this.items.push([k, typeof v === 'object' && v ? v.name : String(v)]); } };"
HELPERS = r"""
const stockUrls = () => requests('/api/materials').map((x) => x.url);                      // every read of the catalogue, pages and single records
const records = (root) => qa(root, 'option').filter((o) => /^Лист \d+/.test(o.textContent)).length;     // an option per record: what the drop-down was
const picker = (root, name) => qa(root, '.matpick').find((p) => p.getAttribute('aria-label') === name);
const labelOf = (p) => q(p, '.matpick-label').textContent;
const sent = (url, method = 'POST') => log.filter((x) => x.url === url && x.method === method);
const opened = async (p) => { const b = button(p, 'Choose…'); b.focus(); await b.dispatch('click'); return qa(doc.body, '.modal').pop(); };
"""
VECTOR = ["hardware.js", "photo-modes.js", "photo-quality.js", "tasks.js", PICKER, "context.js", "screens/vector-split.js", "screens/vector-photo.js",
          "screens/lettering.js", "screens/vector-editor.js", "screens/vector-colours.js", "screens/lifecycle.js", "screens/vector-review.js",
          "screens/vector-workspace.js", "screens/lab-source.js", "screens/evidence-summary.js", "screens/vector.js"]


def bounded(urls) -> None:
    """No request read the whole catalogue: each is a page (``limit=``) or one record by its number."""
    assert urls
    for url in urls:
        assert re.fullmatch(r"/api/materials(/\d+|\?.*\blimit=\d+.*)", url), url


@pytest.fixture
def workshop(tmp_path):
    """The real application with a laser (a lens on it), a camera rig and two hundred stock records; the workshop's last choice is the 88th."""
    with serving(tmp_path / "data") as (app, port):
        store = app.state.store
        laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
        lenses.install(store, laser["id"], lenses.create_lens(store, "F-Theta 174", 174, 110)["id"])
        su.save_capture_setup(store, "Стенд 1", "Canon R5", "LED 5600K", "90", "ColorChecker")
        fill_materials(store, 200)
        creation_context.save(store, {"material_id": 88})
        yield store, port


@pytest.fixture
def bare(tmp_path):
    """The same workshop with no stock record at all."""
    with serving(tmp_path / "data") as (app, port):
        store = app.state.store
        laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
        lenses.install(store, laser["id"], lenses.create_lens(store, "F-Theta 174", 174, 110)["id"])
        su.save_capture_setup(store, "Стенд 1", "Canon R5", "LED 5600K", "90", "ColorChecker")
        yield store, port


# -- 1. the form of a new vector work ----------------------------------------------------------------------------------------------
def test_the_vector_form_starts_with_the_workshops_record_and_sends_the_record_chosen_in_the_selector(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, VECTOR, FORM_DATA + HELPERS + r"""
      stub('/vector', {status: 201, json: {id: 99}}, 'POST');
      const box = mount(await ctx.__screens.vector.render({query: {new: '1', classic: '1'}}));
      const stock = picker(box, 'Титан');
      await stock.ready;
      await until(() => stock.record !== null);
      out.start = {pickers: qa(box, '.matpick').length, records: records(box), rows: lines(box).length, label: labelOf(stock), value: stock.value, urls: stockUrls()};
      stock.value = '41';                                                                        // the person chooses another record
      await until(() => stock.record !== null && stock.record.id === 41);
      qa(box, 'input').find((i) => i.getAttribute('placeholder') === 'Название работы').value = 'Портрет';
      qa(box, 'input').find((i) => i.getAttribute('type') === 'file').files = [{name: 'Inna.jpg'}];
      const tolerance = qa(box, 'label').find((l) => (q(l, 'span') || {}).textContent === 'Допуск ΔE');
      q(tolerance, 'input').value = '5';
      await button(box, 'Создать работу').dispatch('click');
      await until(() => sent('/api/vector').length === 1 && sent('/api/creation/context', 'PUT').length === 1);
      out.sent = {material: sent('/api/vector')[0].body.items.filter(([k]) => k === 'material_id'), remembered: JSON.parse(sent('/api/creation/context', 'PUT')[0].body).material_id,
        urls: stockUrls()};
    """, EXPORTS)
    assert out["start"]["value"] == "88" and out["start"]["label"].startswith("Лист 88 · ")            # the remembered number is selected
    assert (out["start"]["pickers"], out["start"]["records"], out["start"]["rows"]) == (1, 0, 0)       # one line, not an option per record
    bounded(out["start"]["urls"] + out["sent"]["urls"])
    assert out["sent"]["material"] == [["material_id", "41"]] and out["sent"]["remembered"] == 41   # the number the work is made with, and the next start


def test_the_vector_form_without_any_stock_record_says_so_and_reads_no_catalogue(bare, tmp_path):
    store, port = bare
    out = run_node(tmp_path, port, VECTOR, HELPERS + r"""
      const box = mount(await ctx.__screens.vector.render({query: {new: '1', classic: '1'}}));
      out.empty = {title: q(box, 'h3').textContent, pickers: qa(box, '.matpick').length, urls: stockUrls()};
    """, EXPORTS)
    assert out["empty"]["title"] == "Сначала добавьте заготовку титана" and out["empty"]["pickers"] == 0
    assert out["empty"]["urls"] == ["/api/materials?limit=1"]                                          # whether any exists, not all of them


# -- 2. the dialog «Проверить у себя» of a connected laboratory ---------------------------------------------------------------------
CARD = {"id": 4, "name": "Лаборатория Север", "status": "connected", "connected_at": "2026-10-20T10:00:00", "kept": 1, "withdrawals": 0, "release_withdrawn": False,
        "lab": {"name": "Лаборатория Север"}, "withdrawal_list": [],
        "current": {"release_id": "r-1", "release_number": 3, "created_at": "2026-10-20T09:00:00Z", "content_sha256": "abcdef0123456789ffff", "verified": False, "status": "kept",
                    "terms": {"id": "CC-BY-4.0"}, "attribution": {"name": "Автор"}, "counts": {"measurements": 40}},
        "releases": [{"release_id": "r-1", "release_number": 3, "created_at": "2026-10-20T09:00:00Z", "content_sha256": "abcdef0123456789ffff", "verified": False,
                      "status": "kept", "withdrawn": False, "works": []}]}
PALETTE = {"source": SOURCE, "conditions": [], "entries": [
    {"id": "e1", "lab": [50, 10, 10], "srgb": [140, 110, 100], "basis": "chart", "engravings": 2, "agreement": {"engravings": 2, "agreeing": 2, "differing": 0}, "caution": None,
     "recipe": {"power": 40, "frequency": 30, "speed": 500, "pulse_width": 200, "line_interval": 0.02, "passes": 1}, "observation_ids": [1]}]}


LABS = ["hardware.js", "photo-modes.js", "photo-quality.js", "tasks.js", PICKER, "screens/lab-source.js", "screens/vector-split.js", "screens/vector-photo.js",
        "screens/lettering.js", "screens/vector-editor.js", "screens/vector-colours.js", "screens/lifecycle.js", "screens/vector-review.js",
        "screens/vector-workspace.js", "screens/evidence-summary.js", "screens/vector.js", "screens/photo-panels.js", "screens/labs-cloud.js", "screens/labs.js"]
LABS_OPEN = r"""
      stub('/labs/sources/4', {status: 200, json: %(card)s});
      stub('/labs/choices', {status: 200, json: %(choices)s});
      stub('/labs/palette', {status: 200, json: %(palette)s}, 'POST');
      stub('/labs/transfers', {status: 200, json: []}, 'GET');
      stub('/labs/transfers', {status: 201, json: {plan_id: 77, name: 'Перенос'}}, 'POST');
      const tree = mount(await ctx.__screens.labs.render({query: {source: '4'}}));
      await until(() => button(tree, 'Палитра'));
      await button(tree, 'Палитра').dispatch('click');
      await until(() => button(tree, 'Проверить у себя'));
      await button(tree, 'Проверить у себя').dispatch('click');
"""


def labs_open() -> str:
    import json
    return LABS_OPEN % {"card": json.dumps(CARD), "choices": json.dumps(CHOICES), "palette": json.dumps(PALETTE)}


def test_the_transfer_dialog_of_a_laboratory_picks_the_own_titanium_in_the_selector_inside_the_dialog(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, LABS, HELPERS + labs_open() + r"""
      await until(() => q(doc.body, '.modal'));
      const dialog = q(doc.body, '.modal');
      const stock = picker(dialog, 'Свой титан');
      await stock.ready;
      out.start = {pickers: qa(dialog, '.matpick').length, records: records(dialog), selects: qa(dialog, 'select').map((s) => s.getAttribute('aria-label')), label: labelOf(stock), value: stock.value};
      // the selector's own dialog opens above this one; a choice there leaves this one open and gives the focus back to the button that opened it
      const opener = button(stock, 'Choose…');
      const inner = await opened(stock);
      await until(() => rows(inner).length === 20);
      out.nested = {dialogs: qa(doc.body, '.modal').length, inertBelow: dialog.parentNode.hasAttribute('inert')};
      const search = q(inner, '.lst-search');
      search.value = 'b-0137';
      await search.dispatch('input');
      await until(() => count(inner) === 'showing 1 of 1');
      await button(rows(inner)[0], 'Choose').dispatch('click');
      out.after = {dialogs: qa(doc.body, '.modal').length, inertBelow: dialog.parentNode.hasAttribute('inert'), value: stock.value, focus: doc.activeElement === opener};
      await button(dialog, 'Создать пластину').dispatch('click');
      await until(() => sent('/api/labs/transfers').length === 1);
      out.posted = JSON.parse(sent('/api/labs/transfers')[0].body);
      out.urls = stockUrls();
    """, EXPORTS)
    assert out["start"]["pickers"] == 1 and out["start"]["records"] == 0 and out["start"]["selects"] == ["Свой лазер"]       # the laser stays a drop-down, the titanium is one line
    assert out["start"]["value"] == "200" and out["start"]["label"].startswith("Лист 200 · ")           # nothing used yet: the newest record
    assert out["nested"] == {"dialogs": 2, "inertBelow": True}
    assert out["after"] == {"dialogs": 1, "inertBelow": False, "value": "137", "focus": True}
    assert out["posted"]["material_id"] == 137 and out["posted"]["entry_id"] == "e1" and out["posted"]["release_id"] == "r-1"
    bounded(out["urls"])


def test_the_transfer_dialog_without_any_stock_record_says_so_and_reads_no_catalogue(bare, tmp_path):
    store, port = bare
    out = run_node(tmp_path, port, LABS, HELPERS + labs_open() + r"""
      await until(() => qa(doc.body, '.toast.bad').length > 0);
      out.refused = {toast: qa(doc.body, '.toast.bad').map((t) => t.textContent), dialogs: qa(doc.body, '.modal').length, urls: stockUrls()};
    """, EXPORTS)
    assert any("Сначала добавьте лазер и заготовку титана" in t for t in out["refused"]["toast"]) and out["refused"]["dialogs"] == 0
    assert out["refused"]["urls"] == ["/api/materials?limit=1"]                                         # whether any exists, not all of them


# -- 3. the plate dialog and its «new material» form -----------------------------------------------------------------------------
PLATE = ["hardware.js", "tasks.js", PICKER, "screens/plate-dialog.js"]


def test_the_plate_dialog_selects_the_preset_record_adds_a_new_one_and_sends_the_chosen_record(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, PLATE, HELPERS + r"""
      stub('/capability-plates', {status: 201, json: {plan_id: 9, name: 'Плата · TCE-1', summary: {layers: 4, work_field: {checked: true}}}}, 'POST');
      const list = await App.get('/devices');
      const dialog = await ctx.PlateDialog.open(list, null, null, {type: 'fill_sizes', material: 137});
      const stock = picker(dialog.el, 'Заготовка');
      await until(() => stock.record !== null);
      out.preset = {pickers: qa(dialog.el, '.matpick').length, records: records(dialog.el), value: stock.value, label: labelOf(stock), urls: stockUrls()};
      // a record added in the dialog's own form is the one chosen
      qa(dialog.el, 'input').find((i) => i.getAttribute('placeholder') === 'Например: лист Grade 2').value = 'Новый лист';
      await button(dialog.el, 'Сохранить заготовку').dispatch('click');
      await until(() => stock.record !== null && stock.record.name === 'Новый лист');
      out.added = {value: stock.value, label: labelOf(stock), created: sent('/api/materials').length, records: records(dialog.el)};
      await button(dialog.el, 'Создать плату').dispatch('click');
      await until(() => sent('/api/capability-plates').length === 1);
      out.plate = JSON.parse(sent('/api/capability-plates')[0].body).material_id;
      out.urls = stockUrls().filter((u) => u !== '/api/materials');
    """, ("PlateDialog", "MaterialPicker"))
    assert out["preset"]["value"] == "137" and out["preset"]["label"].startswith("Лист 137 · ")             # the preset number is selected
    assert (out["preset"]["pickers"], out["preset"]["records"]) == (1, 0)
    assert out["added"]["value"] == "201" and out["added"]["label"].startswith("Новый лист") and out["added"]["created"] == 1 and out["added"]["records"] == 0
    assert out["plate"] == 201                                                                                # the number of the record the plate is made on
    bounded(out["preset"]["urls"] + out["urls"])


def test_the_plate_dialog_starts_with_the_workshops_record_and_refuses_a_plate_with_nothing_chosen(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, PLATE, HELPERS + r"""
      const list = await App.get('/devices');
      const dialog = await ctx.PlateDialog.open(list, [], null, {type: 'fill_sizes'});        // an array from an old caller is not read
      const stock = picker(dialog.el, 'Заготовка');
      await until(() => stock.record !== null);
      out.start = {value: stock.value, label: labelOf(stock), records: records(dialog.el)};
      await button(stock, 'Снять выбор').dispatch('click');
      out.cleared = {value: stock.value, label: labelOf(stock)};
      await button(dialog.el, 'Создать плату').dispatch('click');
      out.refused = {posted: sent('/api/capability-plates').length, toast: qa(dialog.el, '.f-error, .f-form-error').map((t) => t.textContent)};      // said in the dialog, beside the field
      out.urls = stockUrls();
    """, ("PlateDialog", "MaterialPicker"))
    assert out["start"]["value"] == "88" and out["start"]["label"].startswith("Лист 88 · ") and out["start"]["records"] == 0
    assert out["cleared"] == {"value": "", "label": "выберите конкретную заготовку"}
    assert out["refused"]["posted"] == 0 and any("конкретную заготовку" in t for t in out["refused"]["toast"])
    bounded(out["urls"])


def test_the_plate_dialog_with_no_stock_record_asks_for_one_and_chooses_the_record_that_is_added(bare, tmp_path):
    store, port = bare
    out = run_node(tmp_path, port, PLATE, HELPERS + r"""
      stub('/capability-plates', {status: 201, json: {plan_id: 9, name: 'Плата · TCE-1', summary: {layers: 4, work_field: {checked: true}}}}, 'POST');
      const dialog = await ctx.PlateDialog.open(await App.get('/devices'), null, null, {type: 'fill_sizes'});
      const stock = picker(dialog.el, 'Заготовка');
      await stock.ready;
      out.none = {value: stock.value, label: labelOf(stock), cleared: q(stock, '.matpick-clear').hidden};
      await button(dialog.el, 'Создать плату').dispatch('click');
      out.refused = {posted: sent('/api/capability-plates').length, toast: qa(dialog.el, '.f-error, .f-form-error').map((t) => t.textContent)};
      qa(dialog.el, 'input').find((i) => i.getAttribute('placeholder') === 'Например: лист Grade 2').value = 'Первый лист';
      await button(dialog.el, 'Сохранить заготовку').dispatch('click');
      await until(() => stock.record !== null && stock.record.name === 'Первый лист');
      await button(dialog.el, 'Создать плату').dispatch('click');
      await until(() => sent('/api/capability-plates').length === 1);
      out.plate = JSON.parse(sent('/api/capability-plates')[0].body).material_id;
      out.urls = stockUrls().filter((u) => u !== '/api/materials');
    """, ("PlateDialog", "MaterialPicker"))
    assert out["none"] == {"value": "", "label": "выберите конкретную заготовку", "cleared": True}
    assert out["refused"]["posted"] == 0 and any("конкретную заготовку" in t for t in out["refused"]["toast"])
    assert out["plate"] == 1                                                                              # the record added in the form is the one the plate is made on
    bounded(out["urls"])


# -- 4. the preview of a photo engraving --------------------------------------------------------------------------------------------
PREVIEW = ["hardware.js", "photo-modes.js", "photo-quality.js", "filepick.js", PICKER, "screens/photo-preview.js"]


def test_the_photo_preview_selects_the_record_of_the_address_names_the_records_it_offers_and_sends_the_chosen_one(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, PREVIEW, FORM_DATA + HELPERS + r"""
      ctx.File = class { constructor(parts, name) { this.name = name; } };
      const laser = (await App.get('/devices'))[0];
      const refused = {cache_id: null, file: 'a.lbrn2', device_id: laser.id, lens_id: laser.lens.id, material_id: 137,
        layers: [{index: 1, name: 'C01', dither: 'grayscale', settings: {overridden: []}, refused: 'no colour has been measured at this mode: there is nothing to predict from',
                  measured_on: [{device_id: laser.id, lens_id: laser.lens.id, material_id: 88}, {device_id: laser.id, lens_id: laser.lens.id, material_id: 90}]}]};
      stub('/predictions/photo', {status: 200, json: refused}, 'POST');
      const box = mount(await ctx.__screens['photo-preview'].render({query: {material: '137'}}));
      const stock = picker(box, 'Stock');
      await until(() => stock.record !== null);
      out.start = {pickers: qa(box, '.matpick').length, records: records(box), value: stock.value, label: labelOf(stock), urls: stockUrls()};
      qa(box, 'input').find((i) => i.getAttribute('type') === 'file').files = [{name: 'a.lbrn2'}];
      await button(box, 'Show prediction').dispatch('click');
      await until(() => sent('/api/predictions/photo').length === 1 && button(box, 'Show using this setup'));
      out.first = {material: sent('/api/predictions/photo')[0].body.items.filter(([k]) => k === 'material_id'), says: box.textContent.includes('This mode was measured here:'),
        lines: qa(box, '.row').filter((r) => r.textContent.includes('Show using this setup')).map((r) => qa(r, '.small')[0].textContent.split(' · ').slice(0, 2).join(' · '))};
      await qa(box, 'button').filter((b) => b.textContent === 'Show using this setup')[1].dispatch('click');          // «Show using this setup»: the second record it offers
      await until(() => sent('/api/predictions/photo').length === 2);
      out.second = {value: stock.value, material: sent('/api/predictions/photo')[1].body.items.filter(([k]) => k === 'material_id')};
      out.urls = stockUrls();
    """, EXPORTS)
    assert out["start"]["value"] == "137" and out["start"]["label"].startswith("Лист 137 · ") and (out["start"]["pickers"], out["start"]["records"]) == (1, 0)
    assert out["first"]["material"] == [["material_id", "137"]] and out["first"]["says"]
    assert [line.split(" · ")[0] for line in out["first"]["lines"]] == ["Лист 88", "Лист 90"]              # the records it names are read one by one
    assert out["second"] == {"value": "90", "material": [["material_id", "90"]]}
    bounded(out["start"]["urls"] + out["urls"])
    assert sorted(set(out["urls"])) == sorted({"/api/materials/137", "/api/materials/88", "/api/materials/90"})   # nothing else was read


def test_the_photo_preview_without_any_stock_record_offers_an_empty_catalogue_and_reads_no_list(bare, tmp_path):
    store, port = bare
    out = run_node(tmp_path, port, PREVIEW, HELPERS + r"""
      const box = mount(await ctx.__screens['photo-preview'].render({query: {}}));
      const stock = picker(box, 'Stock');
      await stock.ready;
      const dialog = await opened(stock);
      await until(() => dialog.textContent.includes('No stock records yet.'));
      out.empty = {label: labelOf(stock), value: stock.value, text: dialog.textContent.includes('No stock records yet.'), urls: stockUrls()};
    """, EXPORTS)
    assert out["empty"]["label"] == "choose titanium" and out["empty"]["value"] == "" and out["empty"]["text"]
    bounded(out["empty"]["urls"])


# -- 5. the dialog that changes the workshop's shared choice -------------------------------------------------------------------------
def test_the_dialog_of_the_shared_choice_selects_the_workshops_record_and_saves_the_chosen_one(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, ["hardware.js", "photo-modes.js", "photo-quality.js", "tasks.js", PICKER, "screens/lab-source.js", "context.js"], HELPERS + r"""
      const context = await App.get('/creation/context');
      let saved = null;
      const dialog = (await ctx.WorkContext.change(context, (c) => { saved = c; }, {source: false})).el;
      const stock = picker(dialog, 'Stock');
      await until(() => stock.record !== null && sent('/api/creation/context/impact').length >= 1);
      out.start = {pickers: qa(dialog, '.matpick').length, records: records(dialog), value: stock.value, label: labelOf(stock), selects: qa(dialog, 'select').map((s) => s.getAttribute('aria-label') || '')};
      const before = sent('/api/creation/context/impact').length;
      stock.value = '41';                                                                       // this setter is a programmatic one and asks nothing
      await until(() => stock.record !== null && stock.record.id === 41);
      const inner = await opened(stock);                                                      // a choice made by the person asks what it makes unavailable
      await until(() => rows(inner).length === 20);
      const search = q(inner, '.lst-search');
      search.value = 'b-0150';
      await search.dispatch('input');
      await until(() => count(inner) === 'showing 1 of 1');
      await button(rows(inner)[0], 'Choose').dispatch('click');
      await until(() => sent('/api/creation/context/impact').length === before + 1);
      out.impact = JSON.parse(sent('/api/creation/context/impact').pop().body).material_id;
      await button(dialog, 'Apply').dispatch('click');
      await until(() => saved !== null);
      out.saved = {put: JSON.parse(sent('/api/creation/context', 'PUT')[0].body).material_id, material: saved.material_id};
      out.urls = stockUrls();
    """, ("WorkContext", "MaterialPicker"))
    assert out["start"]["value"] == "88" and out["start"]["label"].startswith("Лист 88 · ") and (out["start"]["pickers"], out["start"]["records"]) == (1, 0)
    assert "Stock" not in out["start"]["selects"]                                              # the laser and the lens are drop-downs, the titanium is not
    assert out["impact"] == 150 and out["saved"] == {"put": 150, "material": 150}
    bounded(out["urls"])


# -- 6. the filter of the experiments overview -----------------------------------------------------------------------------------------
EXPERIMENTS = ["hardware.js", "photo-modes.js", "photo-quality.js", "tasks.js", PICKER, "screens/plate-dialog.js", "screens/experiment-cards.js", "screens/device-view.js",
               "screens/experiments.js"]
STORAGE = ("const __store = {}; ctx.sessionStorage = {getItem: (k) => (k in __store ? __store[k] : null), setItem: (k, v) => { __store[k] = String(v); },"
           "removeItem: (k) => { delete __store[k]; }}; ctx.__store = __store;")


def test_the_experiments_overview_is_about_the_remembered_record_and_a_choice_in_the_selector_is_remembered(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, EXPERIMENTS, STORAGE + HELPERS + r"""
      ctx.sessionStorage.setItem('experiment-dashboard-material', '120');
      const box = mount(await ctx.__screens.experiments.render({query: {}}));
      await until(() => picker(box, 'Material and stock') != null);
      const stock = picker(box, 'Material and stock');
      await until(() => stock.record !== null);
      out.start = {pickers: qa(box, '.matpick').length, records: records(box), value: stock.value, label: labelOf(stock),
        guide: log.filter((x) => x.url.startsWith('/api/application-guide?')).map((x) => x.url.match(/material_id=(\d+)/)[1])};
      const inner = await opened(stock);
      await until(() => rows(inner).length === 20);
      const search = q(inner, '.lst-search');
      search.value = 'b-0033';
      await search.dispatch('input');
      await until(() => count(inner) === 'showing 1 of 1');
      await button(rows(inner)[0], 'Choose').dispatch('click');
      out.chosen = {remembered: ctx.__store['experiment-dashboard-material'], renders: ctx.__renders.length};
      out.urls = stockUrls();
    """, EXPORTS)
    assert out["start"]["value"] == "120" and out["start"]["label"].startswith("Лист 120 · ") and (out["start"]["pickers"], out["start"]["records"]) == (1, 0)
    assert out["start"]["guide"] == ["120"] or out["start"]["guide"] == []                           # the guide, when asked, is about that record
    assert out["chosen"] == {"remembered": "33", "renders": 1}                                        # remembered for the window, and the overview is drawn again
    bounded(out["urls"])


def test_the_experiments_overview_starts_with_the_record_used_last_and_is_quiet_when_there_is_none(bare, tmp_path):
    store, port = bare
    out = run_node(tmp_path, port, EXPERIMENTS, STORAGE + HELPERS + r"""
      const box = mount(await ctx.__screens.experiments.render({query: {}}));
      await until(() => picker(box, 'Material and stock') != null);
      const stock = picker(box, 'Material and stock');
      await stock.ready;
      out.none = {label: labelOf(stock), value: stock.value, guide: log.filter((x) => x.url.startsWith('/api/application-guide?')).length, urls: stockUrls()};
    """, EXPORTS)
    assert out["none"]["value"] == "" and out["none"]["label"] == "No stock selected" and out["none"]["guide"] == 0
    bounded(out["none"]["urls"])


# -- 7. the upload form of a work with its photograph --------------------------------------------------------------------------------
INGEST = ["hardware.js", "photo-modes.js", "photo-quality.js", "filepick.js", "tasks.js", PICKER, "screens/composition.js", "screens/ingest-upload.js", "screens/ingest-dialogs.js",
          "screens/ingest-tasks.js", "screens/ingest-stages.js", "screens/lifecycle.js", "screens/ingest-review.js", "screens/ingest.js"]


def test_the_upload_form_selects_the_record_of_the_address_and_sends_the_chosen_record_with_the_pair(workshop, tmp_path):
    store, port = workshop
    out = run_node(tmp_path, port, INGEST, FORM_DATA + HELPERS + r"""
      class Xhr { constructor() { this.upload = {}; } open(method, url) { this.url = url; } send(fd) { this.fd = fd; Xhr.sent.push(this); this.status = 201; this.response = {id: 5}; setTimeout(() => this.onload(), 0); } }
      Xhr.sent = [];
      ctx.XMLHttpRequest = Xhr;
      const box = mount(await ctx.__screens.ingest.render({query: {material: '137'}}));
      const stock = picker(box, 'Использованный титан / лист / партия');
      await until(() => stock.record !== null);
      out.start = {pickers: qa(box, '.matpick').length, records: records(box), value: stock.value, label: labelOf(stock), urls: stockUrls()};
      stock.value = '64';
      await until(() => stock.record !== null && stock.record.id === 64);
      const files = qa(box, 'input').filter((i) => i.getAttribute('type') === 'file');
      files[0].files = [{name: 'work.lbrn2'}];
      files[1].files = [{name: 'IMG_1.CR3'}];
      await button(box, 'Загрузить пару').dispatch('click');
      await until(() => Xhr.sent.length === 1);
      const material = Xhr.sent[0].fd.items.find(([k]) => k === 'context');
      out.sent = {url: Xhr.sent[0].url, context: JSON.parse(material[1]).material_id};
      out.urls = stockUrls();
    """, EXPORTS)
    assert out["start"]["value"] == "137" and out["start"]["label"].startswith("Лист 137 · ") and (out["start"]["pickers"], out["start"]["records"]) == (1, 0)
    assert out["sent"] == {"url": "/api/pairs", "context": 64}                                          # the number reaches the upload as it did from the drop-down
    bounded(out["start"]["urls"] + out["urls"])


def test_the_upload_page_names_the_missing_stock_record_without_reading_the_catalogue(bare, tmp_path):
    store, port = bare
    out = run_node(tmp_path, port, INGEST, HELPERS + r"""
      const box = mount(await ctx.__screens.ingest.render({query: {}}));
      out.empty = {title: qa(box, 'h3').map((n) => n.textContent), links: qa(box, 'a').map((a) => a.getAttribute('href')), pickers: qa(box, '.matpick').length, urls: stockUrls()};
    """, EXPORTS)
    assert "Add the titanium stock used" in out["empty"]["title"] and "#/setup?tab=material" in out["empty"]["links"] and out["empty"]["pickers"] == 0
    assert out["empty"]["urls"] == ["/api/materials?limit=1"]
