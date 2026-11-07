"""ready-engraving-settings-for-business-cards: the engraving panel of the card editor as a CHOICE (``screens/card-settings.js``, ``card-panels.js``, ``card-work.js``).
The settings of a card are never a blank form to type numbers into: the panel offers the settings the workshop measured for the card's own laser, lens and
material, by type of engraving, says "unknown" plainly with the reason, and puts typing numbers ("Custom values") last. These tests run the screen in node over
the harness and the small fake of the card server of test_card_work_ui.py (here with the new parts: the setup, the origin and status of a set, GET
settings-choices, the ops settings_apply, settings_confirm, settings_custom and set_setup, and a picture that is engraved as a photo). What is checked is what the
screen asks the server for and what it draws from the answers; the look, the real server and the real browser are covered elsewhere."""
from test_card_work_ui import node, run as run_screen

PRELUDE = r"""
const SRC = {matrix: 'Colour matrix', plate: 'Colour plate', photo: 'Photo engraving', text: 'Text test'};
const mkItem = (type, source, n, extra = {}) => ({id: `${type}:${source}:${n}`, type, source: SRC[source], label: `${SRC[source]} ${n}`, detail: `measured on ${n} mm`,
  evidence: {status: 'validated', engravings: 3}, settings: {mode: 'fill', power: 30 + n, speed: 500, frequency: 40, line_interval: 0.02, passes: 1}, unused: [], swatch: null, ...extra});
const mkGroup = (type, source, label, count, extra = {}) => ({source, label, count, items: Array.from({length: count}, (_, i) => mkItem(type, source, i + 1, extra))});
const TYPES = () => [
  {type: 'color', label: 'Colour', known: true, reason: null, groups: [mkGroup('color', 'plate', 'Colour plates', 20), mkGroup('color', 'matrix', 'Measured colours', 3, {swatch: {srgb: '#3a6ea5'}})]},
  {type: 'photo', label: 'Photo', known: true, reason: null, groups: [mkGroup('photo', 'photo', 'Photo engravings', 2,
    {settings: {mode: 'fill', power: 20, speed: 900, frequency: 30, line_interval: 0.05, min_power: 8, dither: 'jarvis', dot_width: 0.04}})]},
  {type: 'line_text', label: 'Lines and text', known: true, reason: null, groups: [mkGroup('line_text', 'text', 'Text tests', 1,
    {settings: {mode: 'line', power: 40, speed: 300, frequency: 50, passes: 2}, unused: ['dither', 'dot_width']})]},
  {type: 'deep', label: 'Deep engraving', known: false, reason: 'Deep engraving has not been measured on this titanium: engrave a depth test to measure it.', groups: []}];
// the other routes the setup dialog reads (the lists of lasers, lenses and the titanium stock record)
const baseFetch = ctx.fetch;
srv.hold = null;                                             // a promise: the answer of GET settings-choices waits for it
const asked = (path) => log.filter((x) => x.method === 'GET' && x.path === path).length;
ctx.fetch = async (url, opts = {}) => {
  const path = String(url).split('?')[0];
  const json = {'/api/devices': [{id: 1, name: 'Laser A', title: 'Laser A', lens: null}, {id: 2, name: 'Laser B', title: 'Laser B', lens: null}],
    '/api/lenses': [{id: 1, name: 'Lens 100 mm', focal_length_mm: 100}],
    '/api/materials/3': {id: 3, name: 'Titanium grade 2', grade: '2', batch: null, thickness_mm: 1}}[path];
  if (json !== undefined && (opts.method || 'GET') === 'GET') { log.push({method: 'GET', path, url: String(url), body: null}); return reply(200, json); }
  if (path === '/api/card-works/7/settings-choices' && srv.hold) { const wait = srv.hold; await wait; }
  return baseFetch(url, opts);
};
const setEl = () => root.querySelector('.cw-set');
const tab = (type) => root.querySelectorAll('.cw-type').find((b) => b.getAttribute('data-type') === type);
const pickType = async (type) => { await tab(type).dispatch('click'); await sleep(0); };
const attention = () => { const box = root.querySelector('.cw-attention'); return box ? box.querySelectorAll('li').map((li) => text(li.querySelector('.lst-text'))) : []; };
const alertIn = (scope) => { const a = scope && scope.querySelector('.alert'); return a && !a.hidden ? text(a) : null; };
// the view the screen holds changes only with an answer of the server: a harmless edit (the name of the set) brings the stored setup and sets
const refetch = async () => { await fill_('Name', 'Engraving ' + Math.random().toString(36).slice(2, 5), setEl()); await saved(); };
const groupsOf = () => root.querySelectorAll('.cw-group');
const rowsIn = (scope) => scope.querySelectorAll('.lst-row');
const loaded = () => until(() => !/Loading/.test(text(root.querySelector('.cw-type-panel'))), 'the ready settings');
const numberBoxes = (scope = root) => scope.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'number');
const useIn = (row) => row.querySelectorAll('button').find((b) => /^(Use|In use)$/.test(b.textContent));
/** A set that came from the choice ``id`` of the workshop's measurements, for the setup of the card unless ``setup`` says another. */
const chosenFrom = (id, over = {}, setup = null) => {
  const found = TYPES().flatMap((t) => t.groups.flatMap((g) => g.items)).find((i) => i.id === id);
  return {...srv.w.settings[0], ...Object.fromEntries(Object.entries(found.settings).filter(([, v]) => v != null)),
    origin: {kind: 'choice', choice_id: id, type: found.type, source: found.source, label: found.label, detail: found.detail, evidence: found.evidence,
      setup: setup || {...srv.w.setup}, at: 'now', note: null, proposed: true}, confirmed: false, ...over};
};
"""


def run(tmp_path, body: str) -> dict:
    return run_screen(tmp_path, PRELUDE + body)


# -- a set with nothing chosen: the types and the reason, never a blank form --------------------------------------------------------------------------------
@node
def test_a_set_with_nothing_chosen_shows_the_types_and_the_reason_and_no_number_box_until_custom_values_is_opened(tmp_path):
    out = run(tmp_path, """
  await open();
  await loaded();
  const set = setEl();
  out.header = {name: text(set.querySelector('.cw-set-name')), chip: text(set.querySelector('.cw-chip')), origin: text(set.querySelector('.cw-origin')), state: set.getAttribute('data-state')};
  out.tabs = root.querySelectorAll('.cw-type').map((b) => [b.getAttribute('data-type'), text(b), b.getAttribute('aria-selected')]);
  out.tabRole = [root.querySelector('.cw-types').getAttribute('role'), root.querySelectorAll('.cw-type').map((b) => b.getAttribute('role'))];
  out.panel = {title: text(set.querySelector('.cw-unknown-title')), reason: text(set.querySelector('.cw-reason'))};
  out.valuesHidden = set.querySelector('.cw-values-box').hidden;
  out.confirm = !!button('Confirm these settings');
  out.chooseHidden = [button('Choose others').hidden, set.querySelector('.cw-choose').hidden];
  out.before = {numbers: numberBoxes(set).length, radios: set.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'radio').length, custom: !!set.querySelector('.cw-custom').open,
    customTitle: text(set.querySelector('.cw-custom').querySelector('summary'))};
  const body = set.querySelector('.cw-set-body').children;
  out.order = [body.findIndex((c) => c.classList.contains('cw-choose')), body.findIndex((c) => c.classList.contains('cw-custom')), body.findIndex((c) => c.classList.contains('cw-values-box'))];
  out.asked = asked('/api/card-works/7/settings-choices');
  await openCustom(set);
  out.after = {numbers: numberBoxes(set).map((i) => i.getAttribute('aria-label')), note: text(set.querySelector('.cw-custom-note')), mode: set.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'radio').length};
""")
    assert out["header"] == {"name": "Engraving 1", "chip": "No settings are chosen yet.", "origin": "Unknown: No settings are chosen yet.", "state": "unknown"}
    assert out["tabs"] == [["color", "Colour unknown", "true"], ["photo", "Photo unknown", "false"], ["line_text", "Lines and text unknown", "false"], ["deep", "Deep engraving unknown", "false"]]
    assert out["tabRole"] == ["tablist", ["tab", "tab", "tab", "tab"]]
    assert out["panel"]["title"] == "Colour: unknown" and "Nothing of type color has been measured for this laser, lens and material." in out["panel"]["reason"]
    assert out["valuesHidden"] is True and out["confirm"] is False
    assert out["chooseHidden"] == [True, False]                                    # with nothing chosen the choice is open and there is no "Choose others"
    assert out["before"] == {"numbers": 0, "radios": 0, "custom": False, "customTitle": "Custom values"}       # no blank form: not a number box, not a mode choice
    assert out["order"][0] < out["order"][1] and out["order"][2] >= 0                # the choice comes before the custom values, which are last of the figures
    assert out["asked"] == 1                                                      # the ready settings were asked for once, when the set opened
    assert out["after"]["numbers"] == ["Power", "Speed", "Frequency", "Pulse width (optional)", "Line interval", "Passes", "Minimum power", "Scan angle", "Dot width"]
    assert out["after"]["note"] == "Typing numbers is the last resort: it is not a measured setting." and out["after"]["mode"] == 2


@node
def test_deep_engraving_is_shown_as_unknown_with_its_reason_and_the_arrow_keys_move_between_the_types(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  await open();
  await loaded();
  out.tabs = root.querySelectorAll('.cw-type').map((b) => text(b));
  out.counts = root.querySelectorAll('.cw-type').map((b) => text(b.querySelector('.cw-type-count')));
  const list = root.querySelector('.cw-types');
  await list.dispatch('keydown', {key: 'End'});
  out.deep = {selected: tab('deep').getAttribute('aria-selected'), tabindex: tab('deep').getAttribute('tabindex'), others: tab('color').getAttribute('tabindex'),
    title: text(root.querySelector('.cw-unknown-title')), reason: text(root.querySelector('.cw-reason')), groups: groupsOf().length, panel: root.querySelector('.cw-type-panel').getAttribute('aria-labelledby'),
    focus: doc.activeElement === tab('deep')};
  await list.dispatch('keydown', {key: 'ArrowRight'});
  out.wrapped = {selected: tab('color').getAttribute('aria-selected'), groups: groupsOf().length};
  await list.dispatch('keydown', {key: 'ArrowLeft'});
  out.back = tab('deep').getAttribute('aria-selected');
  await pickType('photo');
  out.photo = {selected: tab('photo').getAttribute('aria-selected'), groups: groupsOf().map((g) => text(g.querySelector('.cw-group-name'))), rows: rowsIn(groupsOf()[0]).length};
""")
    assert out["tabs"] == ["Colour (23)", "Photo (2)", "Lines and text (1)", "Deep engraving unknown"]
    assert out["counts"] == ["(23)", "(2)", "(1)", "unknown"]
    assert out["deep"] == {"selected": "true", "tabindex": "0", "others": "-1", "title": "Deep engraving: unknown", "groups": 0, "panel": "cw-type-1-deep", "focus": True,
                           "reason": "Deep engraving has not been measured on this titanium: engrave a depth test to measure it."}
    assert out["wrapped"] == {"selected": "true", "groups": 2} and out["back"] == "true"
    assert out["photo"] == {"selected": "true", "groups": ["Photo engravings"], "rows": 2}


# -- choosing -----------------------------------------------------------------------------------------------------------------------------------------------
@node
def test_a_group_has_a_count_the_first_group_is_open_and_use_posts_the_choice_with_its_ids(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  await open();
  await loaded();
  const groups = groupsOf();
  out.groups = groups.map((g) => [text(g.querySelector('.cw-group-name')), text(g.querySelector('.pill')), g.open]);
  const first = groups[0];
  const row = rowsIn(first)[1];
  out.row = {label: text(row.querySelector('.cw-item-label')), plain: row.querySelector('.cw-item-detail') === null, figures: text(row.querySelector('.cw-figures')),
    badge: text(row.querySelector('.pill')), use: useIn(row).getAttribute('aria-label')};
  await groups[1].dispatch('toggle');                                          // the second group is closed: its rows are made when it opens
  out.closed = rowsIn(groups[1]).length;
  groups[1].open = true; await groups[1].dispatch('toggle');
  const swatch = rowsIn(groups[1])[0].querySelector('.cw-swatch');
  out.swatch = [swatch.getAttribute('style'), swatch.getAttribute('aria-label')];
  await useIn(row).dispatch('click');
  await saved();
  out.post = lastPost();
  const set = setEl();
  out.header = {chip: text(set.querySelector('.cw-chip')), origin: text(set.querySelector('.cw-origin')), state: set.getAttribute('data-state')};
  out.values = set.querySelector('.cw-values').querySelectorAll('dt').map((dt, i) => [dt.textContent, set.querySelector('.cw-values').querySelectorAll('dd')[i].textContent]);
  out.notGiven = {title: text(set.querySelector('.cw-notgiven').querySelector('summary')), list: text(set.querySelector('.cw-notgiven').querySelector('p'))};
  const again = rowsIn(groupsOf()[0])[1];
  out.inUse = [text(useIn(again)), useIn(again).getAttribute('aria-pressed'), useIn(again).getAttribute('aria-label'), again.classList.contains('cw-in-use'), text(useIn(rowsIn(groupsOf()[0])[0]))];
  out.rowsKept = rowsIn(groupsOf()[0]).length;
  out.confirm = !!button('Confirm these settings');
  out.chooseButton = [button('Choose others').hidden, set.querySelector('.cw-choose').hidden];
  out.stored = srv.w.settings[0].origin.choice_id;
""")
    assert out["groups"] == [["Colour plates", "20", True], ["Measured colours", "3", False]]
    assert out["row"] == {"label": "Colour plate 2", "plain": True, "figures": "32 % · 500 mm/s · 40 kHz · 0.02 mm interval", "badge": "Validated", "use": "Use Colour plate 2"}
    assert out["closed"] == 0
    assert out["swatch"] == ["background:#3a6ea5", "Colour #3a6ea5"]
    assert out["post"] == {"op": "settings_apply", "settings_id": 1, "choice_id": "color:plate:2"}
    assert out["header"] == {"chip": "Chosen from the workshop's measurements.", "origin": "From: Colour plate 2 · Colour plate", "state": "chosen"}
    assert out["values"] == [["Mode", "Fill"], ["Power", "32 %"], ["Speed", "500 mm/s"], ["Frequency", "40 kHz"], ["Line interval", "0.02 mm"], ["Passes", "1"]]
    assert out["notGiven"]["title"] == "Not given by the source (8)" and "pulse width" in out["notGiven"]["list"] and "minimum power" in out["notGiven"]["list"]
    assert out["inUse"] == ["In use", "true", "Colour plate 2: in use", True, "Use"]
    assert out["rowsKept"] == 8 and out["confirm"] is False
    assert out["chooseButton"] == [False, True]                                    # a chosen set offers "Choose others" and keeps the choice folded away
    assert out["stored"] == "color:plate:2"


@node
def test_a_group_of_twenty_shows_eight_with_show_more_and_a_filter_that_narrows_the_rows(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  await open();
  await loaded();
  const group = groupsOf()[0];
  const filter = () => group.querySelectorAll('input').find((i) => i.getAttribute('type') === 'search');
  const more = () => group.querySelectorAll('button').find((b) => /^Show \\d+ more$/.test(b.textContent));
  out.first = {rows: rowsIn(group).length, more: text(more()), filter: filter().getAttribute('aria-label'), count: text(group.querySelector('.lst-count'))};
  await more().dispatch('click');
  out.second = {rows: rowsIn(group).length, more: text(more())};
  await more().dispatch('click');
  out.third = {rows: rowsIn(group).length, more: more() ? text(more()) : null};
  filter().value = 'plate 12'; await filter().dispatch('input'); await sleep(20);
  out.narrow = {rows: rowsIn(group).map((r) => text(r.querySelector('.cw-item-label'))), count: text(group.querySelector('.lst-count')), more: more() ? text(more()) : null};
  filter().value = 'nothing like it'; await filter().dispatch('input'); await sleep(20);
  out.none = text(group.querySelector('.lst-none'));
  filter().value = ''; await filter().dispatch('input'); await sleep(20);
  out.cleared = rowsIn(group).length;
  const small = groupsOf()[1];
  small.open = true; await small.dispatch('toggle');
  out.small = {rows: rowsIn(small).length, search: small.querySelectorAll('input').length, more: small.querySelectorAll('button').filter((b) => /more/.test(b.textContent)).length};
""")
    assert out["first"] == {"rows": 8, "more": "Show 8 more", "filter": "Filter Colour plates", "count": "showing 8 of 20"}
    assert out["second"] == {"rows": 16, "more": "Show 4 more"} and out["third"] == {"rows": 20, "more": None}
    assert out["narrow"] == {"rows": ["Colour plate 12"], "count": "showing 1 of 1", "more": None}
    assert "No setting of this group matches this filter." in out["none"] and out["cleared"] == 8       # the filter cleared, the first page is shown again
    assert out["small"] == {"rows": 3, "search": 0, "more": 0}                      # a short group has neither a filter nor a "Show more"


@node
def test_details_of_a_row_open_on_demand_and_show_what_the_source_gives_and_does_not_use(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  await open();
  await loaded();
  await pickType('line_text');
  const group = groupsOf()[0];
  const row = rowsIn(group)[0];
  out.before = group.querySelectorAll('.cw-item-details').length;
  await row.querySelector('.lst-main').dispatch('click');
  await sleep(5);
  const det = group.querySelector('.cw-item-details');
  out.after = {detail: text(det.querySelector('p')), keys: det.querySelectorAll('dt').map((d) => d.textContent), unused: text(det.querySelectorAll('p').slice(-1)[0])};
  out.figures = text(row.querySelector('.cw-figures'));
""")
    assert out["before"] == 0
    assert out["after"]["detail"] == "measured on 1 mm"
    assert out["after"]["keys"] == ["Mode", "Power", "Speed", "Frequency", "Passes", "Engravings"]
    assert out["after"]["unused"] == "Not used for shapes and text: image mode, dot width."
    assert out["figures"] == "40 % · 300 mm/s · 50 kHz · 2 passes"                              # a figure the source does not give is not made up


@node
def test_a_refused_choice_is_told_beside_the_choice_and_the_ready_settings_are_read_again(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  await open();
  await loaded();
  const before = asked('/api/card-works/7/settings-choices');
  srv.refuse.push({when: (m, p, b) => b && b.op === 'settings_apply', error: 'these settings are not measured for this laser, lens and material.'});
  await useIn(rowsIn(groupsOf()[0])[0]).dispatch('click');
  await until(() => alertIn(root.querySelector('.cw-choose')), 'the refusal');
  out.alert = alertIn(root.querySelector('.cw-choose'));
  await sleep(10);
  out.state = setEl().getAttribute('data-state');
  out.reread = asked('/api/card-works/7/settings-choices') - before;
""")
    assert "are not measured for this laser, lens and material" in out["alert"] and out["state"] == "unknown" and out["reread"] >= 1


@node
def test_the_ready_settings_that_cannot_be_read_are_said_with_a_retry(tmp_path):
    out = run(tmp_path, """
  srv.refuse.push({when: (m, p) => m === 'GET' && p.endsWith('/settings-choices'), status: 500, error: 'The workshop database is busy'});
  await open();
  await until(() => alertIn(root.querySelector('.cw-type-panel')), 'the failure');
  out.alert = alertIn(root.querySelector('.cw-type-panel'));
  srv.choices = TYPES();
  await press('Retry');
  await until(() => groupsOf().length > 0, 'the groups');
  out.groups = groupsOf().length;
""")
    assert "Could not load the ready settings: The workshop database is busy" in out["alert"] and out["groups"] == 2


# -- a proposal, a set of another setup, the numbers -----------------------------------------------------------------------------------------------------
@node
def test_a_proposal_is_confirmed_by_one_button_next_to_choose_others_and_the_choice_is_asked_for_only_when_it_is_opened(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  srv.w.settings[0] = chosenFrom('line_text:text:1');
  await open();
  const set = setEl();
  out.header = {chip: text(set.querySelector('.cw-chip')), origin: text(set.querySelector('.cw-origin')), state: set.getAttribute('data-state'), title: text(set.querySelector('.cw-values-title'))};
  out.confirm = {text: text(button('Confirm these settings')), primary: button('Confirm these settings').classList.contains('primary'), choose: text(button('Choose others')),
    sameRow: button('Confirm these settings').closest('.cw-decide') === button('Choose others').closest('.cw-decide')};
  out.folded = {hidden: set.querySelector('.cw-choose').hidden, expanded: button('Choose others').getAttribute('aria-expanded'), asked: asked('/api/card-works/7/settings-choices')};
  out.values = set.querySelector('.cw-values').querySelectorAll('dd').map((dd) => dd.textContent);
  await press('Choose others');
  await loaded();
  out.opened = {hidden: set.querySelector('.cw-choose').hidden, expanded: button('Choose others').getAttribute('aria-expanded'), asked: asked('/api/card-works/7/settings-choices'),
    selected: tab('line_text').getAttribute('aria-selected'), inUse: text(useIn(rowsIn(groupsOf()[0])[0]))};
  await press('Confirm these settings');
  await saved();
  out.post = lastPost();
  out.after = {chip: text(set.querySelector('.cw-chip')), state: set.getAttribute('data-state'), confirm: !!button('Confirm these settings'), title: text(set.querySelector('.cw-values-title'))};
""")
    assert out["header"] == {"chip": "Proposed from the workshop's measurements. Confirm them or choose others.", "state": "proposed", "title": "Proposed settings",
                             "origin": "From: Text test 1 · Text test"}
    assert out["confirm"] == {"text": "Confirm these settings", "primary": True, "choose": "Choose others", "sameRow": True}
    assert out["folded"] == {"hidden": True, "expanded": "false", "asked": 0}
    assert out["values"] == ["Line", "40 %", "300 mm/s", "50 kHz", "2"]
    assert out["opened"] == {"hidden": False, "expanded": "true", "asked": 1, "selected": "true", "inUse": "In use"}   # the type it came from is the one shown first
    assert out["post"] == {"op": "settings_confirm", "settings_id": 1}
    assert out["after"] == {"chip": "Chosen from the workshop's measurements.", "state": "chosen", "confirm": False, "title": "Settings in use"}


@node
def test_a_set_chosen_for_another_setup_says_so_and_offers_a_confirmation_only_for_numbers_typed_by_hand(tmp_path):
    out = run(tmp_path, """
  const other = {device_id: 2, lens_id: null, material_id: 3};
  srv.choices = TYPES();
  srv.w.settings[0] = chosenFrom('color:plate:2', {confirmed: true}, other);
  await open();
  await loaded();
  const set = setEl();
  out.choice = {chip: text(set.querySelector('.cw-chip')), state: set.getAttribute('data-state'), note: text(set.querySelector('.cw-other')), noteHidden: set.querySelector('.cw-other').hidden,
    confirm: !!button('Confirm for this setup'), chooseHidden: button('Choose others').hidden, chooserShown: !set.querySelector('.cw-choose').hidden,
    inUse: rowsIn(groupsOf()[0]).map((r) => text(useIn(r))).filter((t) => t === 'In use').length, needs: text(set.querySelector('.cw-set-needs'))};
  srv.w.settings[0] = {...srv.w.settings[0], origin: {...srv.w.settings[0].origin, kind: 'custom', choice_id: null, type: null, source: 'Custom', label: 'Typed by the operator', note: null}};
  await refetch();
  out.custom = {chip: text(set.querySelector('.cw-chip')), note: text(set.querySelector('.cw-other')), confirm: text(button('Confirm for this setup'))};
  await press('Confirm for this setup');
  await saved();
  out.post = lastPost();
  out.after = {chip: text(set.querySelector('.cw-chip')), state: set.getAttribute('data-state'), confirm: !!button('Confirm for this setup'), origin: text(set.querySelector('.cw-origin'))};
""")
    assert out["choice"]["chip"] == "Chosen for another laser, lens or material." and out["choice"]["state"] == "other_setup"
    assert "measured for another laser, lens or material and are not used here" in out["choice"]["note"] and out["choice"]["noteHidden"] is False
    assert out["choice"]["confirm"] is False                                        # a measurement of another setup cannot be confirmed for this one
    assert out["choice"]["chooseHidden"] is True and out["choice"]["chooserShown"] is True
    assert out["choice"]["inUse"] == 0                                              # and the choice that set came from is not marked as in use
    assert out["choice"]["needs"] == "Needs: settings chosen again, or confirmed, for this laser, lens and material"
    assert out["custom"] == {"chip": "Chosen for another laser, lens or material.", "note": "These numbers were typed for another laser, lens or material. Confirm them for this setup, or choose settings measured for it.",
                             "confirm": "Confirm for this setup"}
    assert out["post"] == {"op": "settings_confirm", "settings_id": 1}
    assert out["after"] == {"chip": "Typed by hand, the last resort.", "state": "custom", "confirm": False, "origin": "Typed by hand"}


@node
def test_typing_a_number_posts_it_and_makes_the_set_the_operators_own_and_nothing_wrong_is_sent(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  srv.w.settings[0] = chosenFrom('color:plate:2', {confirmed: true});
  await open();
  const set = setEl();
  await openCustom(set);
  await fill_('Power', 35, set); await saved();
  out.power = lastPost();
  out.header = {chip: text(set.querySelector('.cw-chip')), origin: text(set.querySelector('.cw-origin')), state: set.getAttribute('data-state')};
  await fill_('Minimum power', 12, set); await saved();
  out.min = lastPost();
  await fill_('Scan angle', -45, set); await saved(); await fill_('Dot width', 0.05, set); await saved();
  out.extras = posts().slice(-2).map((b) => b.changes);
  await fill_('Image mode', 'jarvis', set); await saved();
  out.dither = lastPost();
  await fill_('Image mode', '', set); await saved();
  out.ditherCleared = lastPost();
  const before = posts().length;
  await fill_('Minimum power', 150, set); await sleep(10);
  out.bad = {posts: posts().length - before, note: errorOf('Minimum power', set)};
  out.units = ['Minimum power', 'Scan angle', 'Dot width'].map((l) => text(labelled(l, set).querySelectorAll('span').find((s) => s.classList.contains('f-unit'))));
  out.values = set.querySelector('.cw-values').querySelectorAll('dd').map((dd) => dd.textContent);
  out.keep = button('Keep these numbers as custom values').hidden;
""")
    assert out["power"] == {"op": "settings_set", "id": 1, "changes": {"power": 35}}
    assert out["header"] == {"chip": "Typed by hand, the last resort.", "origin": "Typed by hand. Started from Colour plate 2.", "state": "custom"}
    assert out["min"]["changes"] == {"min_power": 12} and out["extras"] == [{"scan_angle": -45}, {"dot_width": 0.05}]
    assert out["dither"]["changes"] == {"dither": "jarvis"} and out["ditherCleared"]["changes"] == {"dither": None}
    assert out["bad"]["posts"] == 0 and "Allowed: from 0 to 100 %" in out["bad"]["note"]
    assert out["units"] == ["%", "degrees", "mm"]
    assert out["values"][:3] == ["Fill", "35 %", "500 mm/s"] and "-45°" in out["values"] and "0.05 mm" in out["values"]
    assert out["keep"] is True                                                      # typed numbers are already custom: nothing to keep


@node
def test_numbers_of_a_chosen_set_can_be_kept_as_custom_without_changing_them(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  srv.w.settings[0] = chosenFrom('color:plate:2', {confirmed: true});
  await open();
  const set = setEl();
  await openCustom(set);
  out.shown = !button('Keep these numbers as custom values').hidden;
  await press('Keep these numbers as custom values');
  await saved();
  out.post = lastPost();
  out.after = {state: set.getAttribute('data-state'), power: srv.w.settings[0].power, note: srv.w.settings[0].origin.note, keep: button('Keep these numbers as custom values').hidden};
""")
    assert out["shown"] is True and out["post"] == {"op": "settings_custom", "settings_id": 1}
    assert out["after"] == {"state": "custom", "power": 32, "note": "Started from Colour plate 2.", "keep": True}


# -- the laser, lens and material of the card -----------------------------------------------------------------------------------------------------------
@node
def test_the_setup_bar_names_the_laser_lens_and_material_and_says_in_words_what_is_missing(tmp_path):
    out = run(tmp_path, """
  await open();
  const bar = () => root.querySelector('.cw-setup');
  out.complete = {line: text(bar().querySelector('.cw-setup-line')), missing: bar().querySelector('.cw-setup-missing').hidden, label: bar().getAttribute('aria-label'),
    change: [text(button('Change')), button('Change').getAttribute('aria-label')]};
  srv.w.setup = {device_id: 1, lens_id: 1, material_id: null};
  await refetch();
  out.noMaterial = {line: text(bar().querySelector('.cw-setup-line')), missing: bar().querySelector('.cw-setup-missing').hidden, words: text(bar().querySelector('.cw-setup-missing'))};
  out.setNeeds = text(setEl().querySelector('.cw-set-needs'));
  out.panel = text(root.querySelector('.cw-reason'));
  srv.w.setup = {device_id: 2, lens_id: null, material_id: 4};
  await refetch();
  out.again = {line: text(bar().querySelector('.cw-setup-line')), missing: bar().querySelector('.cw-setup-missing').hidden};
""")
    assert out["complete"] == {"line": "Laser Laser A · Unknown lens · Material Titanium grade 2", "missing": True, "label": "Laser, lens and material of this card",
                               "change": ["Change", "Change the laser, lens or material of this card"]}
    assert out["noMaterial"]["line"] == "Laser Laser A · Lens Lens 100 mm · No material" and out["noMaterial"]["missing"] is False
    assert out["noMaterial"]["words"] == "The material of this card is not chosen, so no ready engraving settings can be offered or confirmed."
    assert out["setNeeds"].startswith("Needs: the material of this card; ")
    assert out["again"] == {"line": "Laser Laser B · Unknown lens · Material Titanium grade 5", "missing": True}


@node
def test_changing_the_setup_posts_it_says_what_happens_to_the_chosen_sets_and_asks_for_the_choices_again(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  srv.w.settings[0] = chosenFrom('color:plate:2', {confirmed: true});
  await open();
  await loaded();
  const first = asked('/api/card-works/7/settings-choices');
  await press('Change');
  await until(() => dialog(), 'the dialog');
  const box = dialog();
  out.text = text(box.querySelector('p'));
  out.lens = control('Lens', box).options.map((o) => [o.value, o.textContent]);
  out.start = [control('Laser', box).value, control('Lens', box).value, box.querySelector('.matpick') !== null];
  await choose('Laser', '2', box);
  await choose('Lens', '1', box);
  srv.choices = [{type: 'color', label: 'Colour', known: false, reason: 'Nothing is measured for colour on Laser B.', groups: []}, ...TYPES().slice(1)];     // for the new setup colour is unknown
  await press('Change setup', box);
  await saved();
  out.post = lastPost();
  out.closed = !dialog();
  out.bar = text(root.querySelector('.cw-setup-line'));
  out.set = {state: setEl().getAttribute('data-state'), chip: text(setEl().querySelector('.cw-chip')), numbers: numberBoxes(setEl()).length};
  await until(() => asked('/api/card-works/7/settings-choices') > first, 'the choices of the new setup');
  await sleep(10);
  out.tabs = root.querySelectorAll('.cw-type').map((b) => text(b));
  out.stored = srv.w.setup;
""")
    assert "settings chosen for the old setup are replaced by choices for the new one or become unknown" in out["text"]
    assert out["lens"][0] == ["unknown", "Unknown lens"] and out["start"] == ["1", "unknown", True]
    assert out["post"] == {"op": "set_setup", "device_id": 2, "lens_id": 1, "material_id": 3} and out["closed"] is True
    assert out["bar"] == "Laser Laser B · Lens Lens 100 mm · Material Titanium grade 2"
    assert out["set"] == {"state": "unknown", "chip": "No settings are chosen yet.", "numbers": 0}
    assert out["tabs"] == ["Colour unknown", "Photo (2)", "Lines and text (1)", "Deep engraving unknown"]
    assert out["stored"] == {"device_id": 2, "lens_id": 1, "material_id": 3}


@node
def test_a_setup_without_a_material_is_not_sent_and_a_refusal_stays_in_the_dialog(tmp_path):
    out = run(tmp_path, """
  srv.w.setup = {device_id: 1, lens_id: null, material_id: null};
  await open();
  await press('Change');
  await until(() => dialog(), 'the dialog');
  const box = dialog();
  const before = posts().length;
  await press('Change setup', box);
  await sleep(5);
  out.noMaterial = {alert: text(box.querySelector('.alert')), posts: posts().length - before, open: !!dialog()};
  srv.w.setup = {device_id: 1, lens_id: null, material_id: 3};
  srv.refuse.push({when: (m, p, b) => b && b.op === 'set_setup', error: 'choose the material of this card.'});
  box.querySelector('.matpick').value = '3';
  await press('Change setup', box);
  await sleep(10);
  out.refused = {alert: text(box.querySelector('.alert')), open: !!dialog()};
""")
    assert out["noMaterial"] == {"alert": "Choose the material of this card.", "posts": 0, "open": True}
    assert out["refused"] == {"alert": "choose the material of this card.", "open": True}


@node
def test_the_ready_settings_of_the_old_setup_are_never_shown_while_those_of_the_new_one_are_on_their_way(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  await open();
  await loaded();
  out.before = rowsIn(groupsOf()[0]).length;
  await press('Change');
  await until(() => dialog(), 'the dialog');
  await choose('Laser', '2', dialog());
  let release = null;
  srv.hold = new Promise((resolve) => { release = resolve; });
  srv.choices = [{type: 'color', label: 'Colour', known: false, reason: 'Nothing is measured for colour on Laser B.', groups: []}, ...TYPES().slice(1, 2),
    {type: 'line_text', label: 'Lines and text', known: false, reason: 'Nothing is measured for lines on Laser B.', groups: []}, TYPES()[3]];
  await press('Change setup', dialog());
  await saved();
  await until(() => /Loading/.test(text(root.querySelector('.cw-type-panel'))), 'the loading line');
  out.waiting = {panel: text(root.querySelector('.cw-type-panel')), rows: root.querySelectorAll('.cw-item-label').length, counts: root.querySelectorAll('.cw-type-count').map((c) => text(c))};
  release();
  srv.hold = null;
  await until(() => !/Loading/.test(text(root.querySelector('.cw-type-panel'))), 'the new choices');
  out.arrived = {shown: groupsOf().map((g) => text(g.querySelector('.cw-group-name'))), selected: root.querySelectorAll('.cw-type').filter((b) => b.getAttribute('aria-selected') === 'true').map((b) => b.getAttribute('data-type')),
    counts: root.querySelectorAll('.cw-type-count').map((c) => text(c))};
  await pickType('color');
  out.colour = {title: text(root.querySelector('.cw-unknown-title')), reason: text(root.querySelector('.cw-reason')), rows: root.querySelectorAll('.cw-item-label').length};
""")
    assert out["before"] == 8
    assert out["waiting"] == {"panel": "Loading the ready settings…", "rows": 0, "counts": ["", "", "", ""]}
    # the first type with something to offer is shown (colour has nothing for Laser B); colour says plainly that it is unknown, with the reason
    assert out["arrived"] == {"shown": ["Photo engravings"], "selected": ["photo"], "counts": ["unknown", "(2)", "unknown", "unknown"]}
    assert out["colour"] == {"title": "Colour: unknown", "reason": "Nothing is measured for colour on Laser B.", "rows": 0}


# -- a picture engraved as a photo ----------------------------------------------------------------------------------------------------------------------
@node
def test_a_picture_is_engraved_as_traced_shapes_or_as_a_photo_and_a_photo_has_no_tracing_controls_but_invert(tmp_path):
    out = run(tmp_path, """
  srv.w.sides.front.elements.push(build('front', {type: 'image', name: 'Logo', width: 30, height: 15, image: {name: 'Logo', size: [200, 100], auto_threshold: true, threshold: 128, invert: false,
    treatment: 'none', detail: 50, strength: 60, min_feature_mm: 0.15, origin: 'import', prompt: null, engrave: 'vector'}}));
  await open();
  canvas().handlers.onSelect(['e1']);
  const radio = (label) => root.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === label);
  const checks = () => root.querySelectorAll('.cw-check').map((c) => [text(c).slice(0, 16), c.hidden]);
  const hidden = (label) => labelled(label).hidden;
  const state = () => ({group: root.querySelector('.cw-segmented').getAttribute('role'), name: root.querySelector('.cw-segmented').getAttribute('aria-label'),
    radios: [radio('Traced shapes').checked, radio('Photo (raster)').checked], on: root.querySelectorAll('.cw-seg').map((l) => l.classList.contains('on')),
    hint: root.querySelector('.cw-raster-hint').hidden, plain: root.querySelector('.cw-raster-plain').hidden,
    trace: ['Grey level', 'Treatment', 'Detail', 'Pencil strength', 'Smallest feature'].map((l) => hidden(l)), checks: checks()});
  out.vector = state();
  radio('Photo (raster)').checked = true; await radio('Photo (raster)').dispatch('change');
  await saved();
  out.post = lastPost();
  out.raster = state();
  out.hint = text(root.querySelector('.cw-raster-hint'));
  out.plain = text(root.querySelector('.cw-raster-plain'));
  out.shown = lastShow().elements[0].raster;
  canvas().handlers.onEscape();
  out.review = attention()[0];
  canvas().handlers.onSelect(['e1']);
  radio('Traced shapes').checked = true; await radio('Traced shapes').dispatch('change');
  await saved();
  out.back = {post: lastPost(), state: state(), raster: lastShow().elements[0].raster};
""")
    vector = out["vector"]
    assert vector["group"] == "radiogroup" and vector["name"] == "Engrave as" and vector["radios"] == [True, False] and vector["on"] == [True, False]
    assert vector["hint"] is True and vector["plain"] is True and vector["trace"] == [False, False, True, True, False]      # detail and strength belong to the pencil look only
    assert out["post"] == {"side": "front", "op": "set", "id": "e1", "changes": {"image": {"engrave": "raster"}}}
    raster = out["raster"]
    assert raster["radios"] == [False, True] and raster["on"] == [False, True] and raster["hint"] is False and raster["plain"] is False
    assert raster["trace"] == [True, True, True, True, True]                                          # nothing of the tracing is left ...
    assert [c for c in raster["checks"] if not c[1]] == [["Invert (engrave ", False]]                 # ... but "invert"
    assert out["hint"] == "Engraved as a photo with the photo settings of the chosen engraving settings (image mode, line interval, minimum power)."
    assert out["plain"].startswith("The engraving settings of this picture give no line interval or image mode yet")
    assert out["shown"]["url"].startswith("/api/card-works/7/elements/e1/raster.png") and out["shown"]["given"] is False
    assert "Logo (Image): its engraving settings still need settings chosen for this laser, lens and material" in out["review"]
    assert out["back"]["post"]["changes"] == {"image": {"engrave": "vector"}} and out["back"]["raster"] is None
    assert out["back"]["state"]["trace"] == vector["trace"] and out["back"]["state"]["hint"] is True


@node
def test_a_photo_that_lacks_photo_figures_is_named_in_the_review_and_a_complete_one_is_not_plain_grey(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  srv.w.sides.front.elements.push(build('front', {type: 'image', name: 'Logo', width: 30, height: 15, image: {name: 'Logo', size: [200, 100], auto_threshold: true, threshold: 128, invert: false,
    treatment: 'none', detail: 50, strength: 60, min_feature_mm: 0.15, origin: 'import', prompt: null, engrave: 'raster'}}));
  srv.w.settings[0] = chosenFrom('color:plate:2', {confirmed: true});
  await open();
  out.lacking = attention()[0];
  out.set = text(setEl().querySelector('.cw-set-needs'));
  srv.w.settings[0] = chosenFrom('photo:photo:1', {confirmed: true});
  await refetch();
  out.complete = {attention: attention().length, given: lastShow().elements[0].raster.given, needs: setEl().querySelector('.cw-set-needs').hidden};
""")
    assert out["lacking"] == "Logo (Image): its engraving settings still need min power, dither"
    assert out["set"] == "Needs: min power, dither"
    assert out["complete"] == {"attention": 0, "given": True, "needs": True}


# -- keyboard, names -------------------------------------------------------------------------------------------------------------------------------------
@node
def test_every_control_of_the_settings_panel_has_a_name_and_every_number_a_unit(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  await open();
  await loaded();
  await openCustom();
  groupsOf()[1].open = true; await groupsOf()[1].dispatch('toggle');
  const named = (el) => {
    if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return true;
    if (el.localName === 'button' || el.localName === 'summary') return (el.textContent || '').trim().length > 0;
    for (let n = el.parentNode; n; n = n.parentNode) if (n.localName === 'label' && (n.textContent || '').trim()) return true;
    return false;
  };
  const scope = root.querySelector('.cw-engraving');
  out.unnamed = scope.querySelectorAll('button, input, select, textarea, summary').filter((el) => !named(el)).map((el) => el.localName + ' ' + el.className);
  out.controls = scope.querySelectorAll('button, input, select, textarea, summary').length;
  const hasUnit = (i) => { for (let n = i.parentNode; n; n = n.parentNode) if (n.localName === 'label') return n.querySelectorAll('span').some((s) => s.classList.contains('f-unit') || s.classList.contains('sr-only')); return false; };
  out.numbers = {total: numberBoxes(scope).length, withoutUnit: numberBoxes(scope).filter((i) => !hasUnit(i)).length};
  out.names = scope.querySelectorAll('.cw-use').slice(0, 2).map((b) => b.getAttribute('aria-label'));
  out.groupSummaries = scope.querySelectorAll('.cw-group').map((g) => text(g.querySelector('summary')));
""")
    assert out["unnamed"] == [] and out["controls"] > 30
    assert out["numbers"]["total"] == 9 and out["numbers"]["withoutUnit"] == 0
    assert out["names"] == ["Use Colour plate 1", "Use Colour plate 2"]
    assert out["groupSummaries"] == ["Colour plates 20 settings", "Measured colours 3 settings"]
