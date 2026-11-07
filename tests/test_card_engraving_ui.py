"""The engraving of what is selected, chosen where it is selected (card-engraving-where-the-element-is): the inspector of an element or of several shows what they
engrave with (swatch, name, figures, state) and opens one wide dialog (types and groups on the left, settings with figures on the right) whose Use gives the choice
to the selection at once (op ``assign_choice``). These tests run the screen in node over the harness and the fake card server of test_card_work_ui.py."""
from test_card_settings_ui import PRELUDE
from test_card_work_ui import node, run as run_screen

EXTRA = r"""
const block = () => root.querySelector('.cw-engraving-block');
const blockState = () => ({name: text(block().querySelector('.cw-eng-name')), chip: text(block().querySelector('.cw-chip')), figures: text(block().querySelector('.cw-eng-figures')),
  swatch: block().querySelector('.cw-eng-swatch').hidden ? null : block().querySelector('.cw-eng-swatch').getAttribute('style'),
  choose: text(block().querySelector('.cw-eng-choose')), shared: text(block().querySelector('.cw-eng-shared')), confirm: !!block().querySelector('.cw-eng-confirm-btn')});
const picker = () => dialog() && dialog().querySelector('.cw-picker') ? dialog() : null;
const pickTypes = () => picker().querySelectorAll('.cw-pick-type');
const dlgType = async (type) => { await pickTypes().find((b) => b.getAttribute('data-type') === type).dispatch('click'); await sleep(0); };
const pickGroups = () => picker().querySelectorAll('.cw-pick-group');
const pickRows = () => picker().querySelectorAll('.lst-row');
const labelsIn = () => pickRows().map((r) => text(r.querySelector('.cw-item-label')));
const useRow = (i) => pickRows()[i].querySelectorAll('button').find((b) => /^(Use|In use)$/.test(b.textContent));
const openPicker = async () => { await block().querySelector('.cw-eng-choose').dispatch('click'); await until(() => picker(), 'the picker'); await until(() => pickRows().length > 0 || /unknown|Could not/.test(text(picker())), 'its rows'); };
"""


def run(tmp_path, body: str) -> dict:
    return run_screen(tmp_path, PRELUDE + EXTRA + body)


@node
def test_a_selected_element_shows_its_engraving_first_and_offers_one_button_to_choose_it(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  await open();
  const before = asked('/api/card-works/7/settings-choices');
  await press('Text'); await saved();
  const inspector = root.querySelector('.cw-inspector');
  out.order = inspector.children.map((c) => c.classList.contains('cw-engraving-block') ? 'engraving' : c.localName);
  out.state = blockState();
  out.noBlankForm = numberBoxes(block()).length;
  out.asked = asked('/api/card-works/7/settings-choices') - before;
""")
    assert out["order"][:3] == ["h4", "div", "section"] or "engraving" in out["order"][:3]
    assert out["state"] == {"name": "No engraving chosen yet", "chip": "Unknown", "figures": "No settings are chosen yet.", "swatch": None, "choose": "Choose colour / engraving…",
                            "shared": "These are the card’s default settings: every element without its own choice engraves with them.", "confirm": False}
    assert out["noBlankForm"] == 0 and out["asked"] == 0                       # nothing is fetched until the operator opens the choice


@node
def test_using_a_colour_in_the_wide_dialog_gives_it_to_the_selected_element_and_closes_the_dialog(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  await open();
  await press('Text'); await saved();
  await openPicker();
  out.types = pickTypes().map((b) => text(b));
  out.groups = pickGroups().map((b) => text(b));
  out.first = labelsIn().slice(0, 3);
  out.title = text(dialog().querySelector('h3'));
  await pickGroups()[2].dispatch('click'); await sleep(0);                      // the group "Measured colours"
  out.narrow = labelsIn();
  await useRow(1).dispatch('click'); await saved();
  out.post = lastPost();
  out.closed = !dialog();
  out.block = blockState();
  out.sets = srv.w.settings.map((s) => [s.id, s.name]);
  out.layer = root.querySelectorAll('.cw-layer-swatch').map((s) => s.getAttribute('style'));
""")
    assert out["types"] == ["Colour 23", "Photo 2", "Lines and text 1", "Deep engraving unknown"]
    assert out["groups"] == ["All 23", "Colour plates 20", "Measured colours 3"]
    assert out["title"] == "Choose the engraving for Text 1"
    assert out["narrow"] == ["Colour matrix 1", "Colour matrix 2", "Colour matrix 3"]
    assert out["post"] == {"side": "front", "op": "assign_choice", "ids": ["e1"], "choice_id": "color:matrix:2"}
    assert out["closed"] is True
    assert out["block"]["name"] == "Colour matrix 2" and out["block"]["chip"] == "Chosen" and out["block"]["swatch"] == "background:#3a6ea5"
    assert out["block"]["figures"].startswith("32 % · 500 mm/s · 40 kHz")
    assert out["sets"] == [[1, "Engraving 1"], [2, "Colour matrix 2"]]               # the default stays, the colour is a set of its own that the operator never had to make
    assert out["layer"] == ["background:#3a6ea5"]


@node
def test_several_selected_elements_get_the_same_choice_and_a_mixed_selection_says_so(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  await open();
  await press('Text'); await saved();
  await press('QR code'); await saved();
  canvas().handlers.onSelect(['e1', 'e2']);
  await sleep(2);
  out.before = {title: text(root.querySelector('.cw-inspector').querySelector('h4')), block: blockState()};
  await openPicker();
  out.dialogTitle = text(dialog().querySelector('h3'));
  await useRow(0).dispatch('click'); await saved();
  out.post = lastPost();
  canvas().handlers.onSelect(['e1']);
  await sleep(2);
  out.one = blockState();
  canvas().handlers.onSelect(['e2']);                                           // the second element takes another colour
  await sleep(2);
  await openPicker();
  await useRow(1).dispatch('click'); await saved();
  canvas().handlers.onSelect(['e1', 'e2']);
  await sleep(2);
  out.mixed = blockState();
""")
    assert out["before"]["title"] == "2 elements selected" and out["before"]["block"]["name"] == "No engraving chosen yet"
    assert out["dialogTitle"] == "Choose the engraving for 2 elements"
    assert out["post"] == {"side": "front", "op": "assign_choice", "ids": ["e1", "e2"], "choice_id": "color:plate:1"}
    assert out["one"]["name"] == "Colour plate 1" and out["one"]["shared"] == "Also used by QR code 1."
    assert out["mixed"]["name"] == "Mixed engravings" and out["mixed"]["figures"].startswith("2 elements engrave with different settings") and out["mixed"]["swatch"] is None


@node
def test_types_without_data_say_unknown_with_the_reason_and_closing_the_dialog_changes_nothing(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  await open();
  await press('Text'); await saved();
  await openPicker();
  await dlgType('deep');
  out.deep = {title: text(picker().querySelector('.cw-unknown-title')), reason: text(picker().querySelector('.cw-reason')), groups: pickGroups().length, rows: pickRows().length};
  await dialog().querySelectorAll('button').find((b) => b.textContent === 'Close').dispatch('click');
  out.closed = !dialog();
  out.posts = posts('/edit').length;
""")
    assert out["deep"]["title"] == "Deep engraving: unknown" and "not been measured" in out["deep"]["reason"] and out["deep"]["groups"] == 0 and out["deep"]["rows"] == 0
    assert out["closed"] is True and out["posts"] == 1                                # only the added text: closing the dialog changes nothing


@node
def test_a_picture_engraved_as_a_photo_opens_the_dialog_on_the_photo_settings(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  const logo = (engrave) => build('front', {type: 'image', name: 'Logo', width: 30, height: 15, image: {name: 'Logo', size: [200, 100], auto_threshold: true, threshold: 128, invert: false,
    treatment: 'none', detail: 50, strength: 60, min_feature_mm: 0.15, origin: 'import', prompt: null, engrave}});
  srv.w.sides.front.elements.push(logo('raster'));
  await open();
  canvas().handlers.onSelect(['e1']);
  await sleep(2);
  await openPicker();
  out.raster = {selected: pickTypes().filter((b) => b.getAttribute('aria-selected') === 'true').map((b) => b.getAttribute('data-type')), rows: labelsIn()};
  await dialog().querySelectorAll('button').find((b) => b.textContent === 'Close').dispatch('click');
""")
    assert out["raster"] == {"selected": ["photo"], "rows": ["Photo engraving 1", "Photo engraving 2"]}


@node
def test_a_refused_choice_stays_in_the_dialog_with_its_words_and_the_one_in_use_is_marked(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  await open();
  await press('Text'); await saved();
  await openPicker();
  await useRow(0).dispatch('click'); await saved();                              // chosen: Colour plate 1
  await openPicker();
  out.inUse = pickRows().map((r) => useRow2(r)).slice(0, 2);
  srv.refuse.push({when: (m, p, b) => b && b.op === 'assign_choice', error: 'these settings are not measured for this laser, lens and material.'});
  await useRow(1).dispatch('click'); await sleep(20);
  out.refused = {open: !!dialog(), error: text(dialog().querySelector('.alert'))};
  await useRow(0).dispatch('click'); await sleep(10);
  out.sameClosed = !dialog();
  out.assigns = posts('/edit').filter((p) => p.op === 'assign_choice').length;
""".replace("useRow2(r)", "(r.querySelectorAll('button').find((b) => /^(Use|In use)$/.test(b.textContent)).textContent)"))
    assert out["inUse"] == ["In use", "Use"]
    assert out["refused"] == {"open": True, "error": "these settings are not measured for this laser, lens and material."}
    assert out["sameClosed"] is True and out["assigns"] == 2                                # pressing the one in use only closes the dialog
    

@node
def test_a_proposed_engraving_is_confirmed_from_the_block_and_the_details_hold_the_figures(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  srv.w.settings[0] = chosenFrom('color:plate:2');                                // proposed: not confirmed yet
  await open();
  await press('Text'); await saved();
  out.proposed = blockState();
  out.detailsClosed = !root.querySelector('.cw-eng-details').open;
  out.details = text(root.querySelector('.cw-eng-details').querySelector('summary'));
  out.figures = root.querySelector('.cw-eng-details').querySelectorAll('dt').map((d) => text(d));
  await block().querySelector('.cw-eng-confirm-btn').dispatch('click'); await saved();
  out.post = lastPost();
  out.chosen = blockState();
""")
    assert out["proposed"]["chip"] == "Proposed: confirm" and out["proposed"]["confirm"] is True and out["proposed"]["name"] == "Colour plate 2"
    assert out["proposed"]["choose"] == "Change colour / engraving…"
    assert out["detailsClosed"] is True and out["details"] == "Settings details" and out["figures"][:3] == ["Mode", "Power", "Speed"]
    assert out["post"] == {"op": "settings_confirm", "settings_id": 1}
    assert out["chosen"]["chip"] == "Chosen" and out["chosen"]["confirm"] is False


@node
def test_groups_that_share_one_source_are_told_apart_by_place_and_only_the_chosen_one_is_active(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  for (const type of srv.choices) for (const g of type.groups) g.source = 'Colour map';           // the live workshop: every hue group has the same source, only the label differs
  await open();
  await press('Text'); await saved();
  await openPicker();
  const state = () => pickGroups().map((b) => [text(b.querySelector('.cw-group-name')), b.getAttribute('aria-pressed'), b.classList.contains('active')]);
  out.start = state();
  await pickGroups()[2].dispatch('click'); await sleep(0);
  out.second = {groups: state(), rows: labelsIn(), heading: text(picker().querySelector('.cw-pick-main').querySelector('.cw-pick-heading'))};
  await pickGroups()[0].dispatch('click'); await sleep(0);
  out.all = {groups: state().map((g) => g[1]), rows: pickRows().length};
""")
    assert [g[1:] for g in out["start"]] == [["true", True], ["false", False], ["false", False]]
    assert [g[1:] for g in out["second"]["groups"]] == [["false", False], ["false", False], ["true", True]]
    assert out["second"]["rows"] == ["Colour matrix 1", "Colour matrix 2", "Colour matrix 3"] and out["second"]["heading"].endswith("Measured colours")
    assert out["all"]["groups"] == ["true", "false", "false"] and out["all"]["rows"] > 3


@node
def test_the_set_of_the_card_opens_the_same_wide_choice_from_the_panel_where_nothing_is_selected(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  await open();
  await loaded();
  const wide = button('Choose colour / engraving…');
  out.has = !!wide;
  await wide.dispatch('click');
  await until(() => picker(), 'the wide choice');
  out.title = text(dialog().querySelector('h3'));
  await until(() => pickRows().length > 0, 'its rows');
  await useRow(1).dispatch('click'); await saved();
  out.post = lastPost();
  out.closed = !dialog();
  out.set = {origin: srv.w.settings[0].origin.choice_id, state: setEl().getAttribute('data-state'), sets: srv.w.settings.length};
""")
    assert out["has"] is True and out["title"] == "Choose the engraving for “Engraving 1”"
    assert out["post"] == {"op": "settings_apply", "settings_id": 1, "choice_id": "color:plate:2"} and out["closed"] is True
    assert out["set"] == {"origin": "color:plate:2", "state": "chosen", "sets": 1}               # the default set itself changed: no second set was made
