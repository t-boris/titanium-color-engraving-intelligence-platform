"""feature-3 (REQ-001..REQ-005), the screen: importing an SVG or Illustrator file into the card editor, choosing one part out of the artwork, changing its design
colour apart from the engraving colour, and the engraving colours suggested for it. These tests run the screen in node over the harness and the fake card server of
test_card_work_ui.py (which stands in for card_work.import_vector, the ops ``recolour`` and ``scale`` and ``GET colour-matches``; the real server is
tests/test_card_vector.py)."""
from test_card_settings_ui import PRELUDE
from test_card_work_ui import node, run as run_screen

EXTRA = r"""
const artworkBox = () => root.querySelector('.cw-art');
const artRows = () => (artworkBox() ? artworkBox().querySelectorAll('.cw-art-row') : []);
const artState = (row) => ({colour: row.getAttribute('data-colour'), count: text(row.querySelectorAll('span').find((s) => /parts?$/.test(s.textContent || ''))),
  suggest: text(row.querySelector('.cw-art-suggest')), far: text(row.querySelector('.cw-art-far')), none: text(row.querySelector('.cw-art-none')), engraves: text(row.querySelector('.cw-art-engraves')),
  use: (row.querySelector('.cw-art-use') || {}).textContent || null, back: !!row.querySelectorAll('button').find((b) => b.textContent === 'Back to the colour of the file')});
const importFile = async (name = 'cat.svg') => {
  await press('Vector');
  const input = root.querySelectorAll('input').find((i) => i.getAttribute('type') === 'file');
  input.files = [new File(['<svg/>'], name, {type: 'image/svg+xml'})];
  await input.dispatch('change');
  await saved();
  await sleep(2);
  return input;
};
const inspectorTitle = () => text(root.querySelector('.cw-inspector').querySelector('h4'));
const colourInput = (row) => row.querySelector('.cw-colour-input');
const layerRow = (name) => root.querySelectorAll('.lst-row').find((r) => (r.textContent || '').includes(name));
"""


def run(tmp_path, body: str) -> dict:
    return run_screen(tmp_path, PRELUDE + EXTRA + body)


@node
def test_a_vector_file_is_posted_with_its_side_becomes_a_group_of_parts_and_the_report_says_what_was_not_carried_over(tmp_path):
    out = run(tmp_path, """
  srv.vectorFile = {notes: ['Text was not converted to outlines, so it was left out: convert it in Illustrator or Inkscape.', 'A gradient was replaced by its first colour.']};
  await open();
  await press('Vector');
  const input = root.querySelectorAll('input').find((i) => i.getAttribute('type') === 'file');
  out.accept = input.getAttribute('accept');
  out.hint = text(root.querySelectorAll('p').find((p) => (p.textContent || '').startsWith('SVG, or an Illustrator file')));
  input.files = [new File(['<svg/>'], 'cat.svg', {type: 'image/svg+xml'})];
  await input.dispatch('change');
  await saved();
  await sleep(2);
  out.post = lastPost('/vector');
  out.layers = layerNames();
  out.groups = root.querySelectorAll('.pill').filter((p) => /^Group of/.test(p.textContent)).map((p) => p.textContent);
  out.selected = lastShow().selection;
  out.title = inspectorTitle();
  out.report = text(root.querySelector('.cw-import-report'));
  out.notes = root.querySelector('.cw-import-notes').querySelectorAll('li').map((li) => li.textContent);
  out.cleared = input.value;
""")
    assert out["post"] == {"side": "front", "picture": None, "artwork": "cat.svg"}
    assert ".svg" in out["accept"] and ".ai" in out["accept"]
    assert out["layers"] == ["eye", "ear", "body"] and out["groups"] == ["Group of 3"] * 3
    assert out["selected"] == ["e1", "e2", "e3"] and out["title"] == "3 elements selected"
    assert "Imported “cat.svg” (SVG): 3 parts in 2 colours, 30 × 20 mm" in out["report"] and "double-click one to select it alone" in out["report"]
    assert "Not carried over or changed:" in out["report"]
    assert out["notes"] == ["Text was not converted to outlines, so it was left out: convert it in Illustrator or Inkscape.", "A gradient was replaced by its first colour."]
    assert out["cleared"] == "", "the same file can be chosen again"
    assert "convert text to outlines" in out["hint"].lower() or "Text must be converted to outlines first" in out["hint"]


@node
def test_a_refused_file_is_told_beside_the_form_and_changes_nothing(tmp_path):
    out = run(tmp_path, """
  srv.vectorFile = {fail: 'this Illustrator file has no PDF-compatible content: save it again with “Create PDF Compatible File” or export an SVG.'};
  await open();
  await importFile('old.ai');
  const alert_ = root.querySelectorAll('.alert').find((a) => a.getAttribute('role') === 'alert' && !a.hidden && /PDF-compatible/.test(a.textContent));
  out.alert = text(alert_);
  out.layers = layerNames();
  out.state = line();
  out.report = text(root.querySelector('.cw-import-report'));
""")
    assert "has no PDF-compatible content" in out["alert"]
    assert out["layers"] == [] and out["report"] == ""
    assert out["state"].startswith("Card: Saved"), "a refused file does not make the card unsaved"


@node
def test_the_colours_of_the_artwork_are_listed_once_for_each_design_colour_and_a_part_can_be_recoloured_and_set_back(tmp_path):
    out = run(tmp_path, """
  await open();
  await importFile();
  const rows = artRows();
  out.rows = rows.map(artState);
  out.title = text(artworkBox().querySelector('h4'));
  out.note = text(artworkBox().querySelectorAll('p').find((p) => /design colour is what the file draws/i.test(p.textContent)));
  // one design colour, two parts: recolour both at once
  const brown = rows.find((r) => r.getAttribute('data-colour') === '#a05a2c');
  colourInput(brown).value = '#336699';
  await colourInput(brown).dispatch('change');
  await saved();
  out.recolour = lastPost();
  out.afterRecolour = artRows().map(artState);
  out.dots = root.querySelectorAll('.cw-layer-design').map((d) => d.getAttribute('style'));
  out.canvasColours = lastShow().elements.map((e) => [e.name, e.color]);
  const changed = artRows().find((r) => r.getAttribute('data-colour') === '#336699');
  await changed.querySelectorAll('button').find((b) => b.textContent === 'Back to the colour of the file').dispatch('click');
  await sleep(0); await saved();
  out.reset = lastPost();
  out.afterReset = artRows().map(artState);
  out.sourceKept = srv.w.sides.front.elements.map((e) => [e.name, e.vector.fill, e.vector.source]);
""")
    assert [r["colour"] for r in out["rows"]] == ["#a05a2c", "#101010"] and [r["count"] for r in out["rows"]] == ["2 parts", "1 part"]
    assert out["title"] == "Colours of the artwork" and "engraving colour is what the laser makes" in out["note"]
    assert not any(r["back"] for r in out["rows"]), "nothing is recoloured yet"
    assert out["recolour"] == {"side": "front", "op": "recolour", "ids": ["e1", "e2"], "fill": "#336699"}
    assert [r["colour"] for r in out["afterRecolour"]] == ["#336699", "#101010"] and out["afterRecolour"][0]["back"] is True
    assert "background:#336699" in out["dots"][1] and out["canvasColours"][0] == ["body", "#336699"]
    assert out["reset"] == {"side": "front", "op": "recolour", "ids": ["e1", "e2"], "reset": True}
    assert [r["colour"] for r in out["afterReset"]] == ["#a05a2c", "#101010"]
    assert out["sourceKept"] == [["body", "#a05a2c", "#a05a2c"], ["ear", "#a05a2c", "#a05a2c"], ["eye", "#101010", "#101010"]]


@node
def test_a_click_on_a_layer_of_a_whole_group_picks_that_part_and_its_form_says_the_shape_cannot_be_edited(tmp_path):
    out = run(tmp_path, """
  await open();
  await importFile();
  await layerRow('ear').querySelector('.cw-layer').dispatch('click'); await sleep(0);
  out.one = {canvas: canvas().selection, title: rightTitle()};
  out.info = text(root.querySelector('.cw-form').querySelector('p'));
  out.rows = artRows().map(artState);
  out.note = text(root.querySelector('.cw-nodes-note'));
  out.sizes = [control('Width').getAttribute('min'), control('Height').getAttribute('min')];
  await layerRow('body').querySelector('.cw-layer').dispatch('click'); await sleep(0);
  out.other = {canvas: canvas().selection, title: inspectorTitle()};
""")
    assert out["one"]["canvas"] == ["e2"]
    assert out["info"] == "Part 2 of “cat.svg” (SVG)"
    assert [r["colour"] for r in out["rows"]] == ["#a05a2c"] and out["rows"][0]["count"] == "1 part"
    assert "cannot be edited (no path nodes)" in out["note"] and "Double-click a part of a group" in out["note"]
    assert out["sizes"] == ["0.02", "0.02"], "a part may be a hairline"
    assert out["other"]["canvas"] == ["e1", "e2", "e3"] and out["other"]["title"] == "3 elements selected", "choosing another member of the group chooses the group again"


@node
def test_the_closest_measured_engraving_colour_is_suggested_with_its_distance_and_use_gives_it_to_the_parts_of_that_colour_only(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  srv.deltaE = {'#a05a2c': {'color:matrix:1': 8.4, 'color:matrix:2': 30, 'color:matrix:3': 41}, '#101010': {'color:matrix:1': 38.2, 'color:matrix:2': 52, 'color:matrix:3': 61}};
  await open();
  await importFile();
  const brown = artRows().find((r) => r.getAttribute('data-colour') === '#a05a2c');
  await until(() => artRows().every((r) => !!r.querySelector('.cw-art-suggest')), 'the suggestions');
  out.asked = log.filter((x) => x.path === '/api/card-works/7/colour-matches').map((x) => decodeURIComponent(x.url.split('colours=')[1]));
  out.brown = artState(artRows().find((r) => r.getAttribute('data-colour') === '#a05a2c'));
  out.black = artState(artRows().find((r) => r.getAttribute('data-colour') === '#101010'));
  const use = artRows().find((r) => r.getAttribute('data-colour') === '#a05a2c').querySelector('.cw-art-use');
  out.useLabel = use.getAttribute('aria-label');
  await use.dispatch('click'); await sleep(0); await saved();
  out.post = lastPost();
  out.assigned = srv.w.sides.front.elements.map((e) => [e.name, e.settings_id]);
  out.after = artState(artRows().find((r) => r.getAttribute('data-colour') === '#a05a2c'));
  out.design = srv.w.sides.front.elements.map((e) => [e.name, e.vector.fill]);
""")
    assert out["asked"][0].split(",") == ["#101010", "#a05a2c"] or sorted(out["asked"][0].split(",")) == ["#101010", "#a05a2c"]
    assert out["brown"]["suggest"].startswith("Closest engraving colour") and "Colour matrix 1" in out["brown"]["suggest"] and "ΔE 8.4" in out["brown"]["suggest"]
    assert out["brown"]["use"] == "Use" and out["brown"]["far"] is None
    assert out["black"]["suggest"].startswith("Nearest, but not close") and out["black"]["use"] == "Use nearest"
    assert "No measured engraving colour is close to #101010" in out["black"]["far"] and "38.2 ΔE away" in out["black"]["far"]
    assert out["useLabel"] == "Use Colour matrix 1 for 2 parts of #a05a2c"
    assert out["post"] == {"side": "front", "op": "assign_choice", "ids": ["e1", "e2"], "only": True, "choice_id": "color:matrix:1"}
    assert out["assigned"][0][1] == out["assigned"][1][1] and out["assigned"][0][1] is not None and out["assigned"][2][1] is None, "the other colour keeps its own settings"
    assert out["after"]["use"] == "In use" and "Colour matrix 1" in out["after"]["engraves"]
    assert out["design"] == [["body", "#a05a2c"], ["ear", "#a05a2c"], ["eye", "#101010"]], "choosing an engraving never recolours the design"


@node
def test_with_nothing_measured_the_panel_says_so_and_never_invents_an_engraving_colour(tmp_path):
    out = run(tmp_path, """
  srv.choices = null;
  await open();
  await importFile();
  await until(() => artRows().every((r) => !!r.querySelector('.cw-art-none')), 'the reason');
  out.rows = artRows().map(artState);
  out.report = text(root.querySelector('.cw-import-report'));
  out.suggestButtons = root.querySelectorAll('.cw-art-use').length;
  out.another = artRows()[0].querySelectorAll('button').map((b) => b.textContent);
""")
    assert all(r["none"] == "No colour is measured for this laser, lens and material yet." for r in out["rows"])
    assert out["suggestButtons"] == 0 and "Choose another…" in out["another"]
    assert "No engraving colour is measured for this card yet." in out["report"]


@node
def test_the_import_report_tells_how_many_colours_were_matched_at_import(tmp_path):
    out = run(tmp_path, """
  srv.vectorFile = {engraving: {available: true, reason: null, assigned: 1, colours: 2}};
  await open();
  await importFile();
  out.report = text(root.querySelector('.cw-import-report'));
  srv.vectorFile = {engraving: {available: true, reason: null, assigned: 0, colours: 2}};
  const input = root.querySelectorAll('input').find((i) => i.getAttribute('type') === 'file');
  input.files = [new File(['x'], 'b.svg', {type: 'image/svg+xml'})];
  await input.dispatch('change'); await saved(); await sleep(2);
  out.second = text(root.querySelector('.cw-import-report'));
""")
    assert "Engraving colours: 1 of 2 colours were matched to colours measured for this card" in out["report"]
    assert "No colour is close to a colour measured for this card" in out["second"]


@node
def test_a_part_of_a_group_gets_its_own_engraving_through_the_dialog_and_the_whole_group_can_be_scaled(tmp_path):
    out = run(tmp_path, """
  srv.choices = TYPES();
  await open();
  await importFile();
  const before = srv.w.sides.front.elements.map((e) => [e.width, e.height]);
  await fill_('Scale the selection', 150); await saved();
  out.scale = lastPost();
  out.scaled = srv.w.sides.front.elements.map((e, i) => [e.width / before[i][0], e.height / before[i][1]]);
  out.box = control('Scale the selection').value;
  await layerRow('eye').querySelector('.cw-layer').dispatch('click'); await sleep(0);
  const block = root.querySelector('.cw-engraving-block');
  await block.querySelector('.cw-eng-choose').dispatch('click');
  await until(() => dialog() && dialog().querySelectorAll('.lst-row').length > 0, 'the rows');
  const use = dialog().querySelectorAll('.lst-row')[0].querySelectorAll('button').find((b) => /^(Use|In use)$/.test(b.textContent));
  await use.dispatch('click'); await sleep(0); await saved();
  out.post = lastPost();
  out.assigned = srv.w.sides.front.elements.map((e) => [e.name, e.settings_id != null]);
""")
    assert out["scale"] == {"side": "front", "op": "scale", "ids": ["e1", "e2", "e3"], "factor": 1.5}
    assert all(abs(w - 1.5) < 1e-9 and abs(h - 1.5) < 1e-9 for w, h in out["scaled"]) and out["box"] == "100"
    assert out["post"]["op"] == "assign_choice" and out["post"]["ids"] == ["e3"] and out["post"]["only"] is True, "a part picked out of its group is given the engraving alone"
    assert out["assigned"] == [["body", False], ["ear", False], ["eye", True]]
