/* Open laser specification questions are computed by the server and change as values are entered or confirmed (DEC-039). */
'use strict';
const DeviceQuestions = (() => {
  const {h, link} = App;
  const SECTION = GlossaryController.TAB;

  /** Question text and route to resolve it. */
  function describe(q, id) {
    const to = (tab, section) => `/devices/${id}?tab=${tab}` + (section ? `&section=${section}` : '');
    if (q.kind === 'unread') return {text: `Not read from the photo: ${q.key} (section “${SECTION[q.tab] || q.tab}”). Enter the value.`, route: to('controller', q.tab)};
    if (q.kind === 'unconfirmed') return {text: `Hand-entered values awaiting confirmation: ${q.count}. Check the original and select ✓.`, route: to('controller', q.items[0].tab)};
    if (q.kind === 'lens') return {text: 'No lens is specified. Spot diameter and work field cannot be calculated without it. Set a lens on the Lens tab.', route: to('lens')};
    if (q.kind === 'focal_length') return {text: 'The lens focal length is missing. Spot diameter, energy density and pulse overlap cannot be calculated without it. Enter it on the Lens tab.', route: to('lens')};
    if (q.kind === 'm2') return {text: 'M² (beam quality) is missing. Only a spot-size range is known and it is excluded from calculations. Enter M² from the manual or measure the spot.', route: to('lens')};

    if (q.kind === 'serial') return {text: 'The laser serial number is missing.', route: to('overview')};
    return {text: q.text, route: null};
  }

  function list(d) {
    const items = d.open_questions.map((q) => describe(q, d.id));
    return h('ul', {}, items.map((x) => h('li', {}, x.text, x.route ? [' ', link(x.route, 'Open')] : '')));
  }

  /** An expandable section; the caller chooses whether it starts open. */
  function card(d, open = false) {
    if (!d.open_questions.length) return h('div', {class: 'alert ok'}, 'No open specification questions.');
    return h('details', {class: 'alert warn', open}, h('summary', {}, h('strong', {}, 'Open specification questions: ' + d.open_questions.length)), list(d));
  }
  return {card, list};
})();
