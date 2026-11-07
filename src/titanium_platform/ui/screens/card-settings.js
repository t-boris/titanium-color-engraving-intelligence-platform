/* The engraving settings of a business card as a CHOICE (ready-engraving-settings-for-business-cards, REQ-001..005, 022..024). A set of settings is
   never a blank form to type numbers into: the editor offers the settings the workshop measured for the card's own laser, lens and material,
   by type of engraving (colour, photo, lines and text, deep engraving), and says "unknown" plainly, with the reason, when nothing is known.
   Typing numbers ("Custom values") is the last resort and comes last. Settings of another laser, lens or material are never offered: the
   server lists only what was measured for the card's setup, and this file never lists anything else.

   It draws what the screen hands it (card-panels.js builds the engraving panel and passes its number and text controls) and reports every
   edit through ``env``; it never talks to the server itself:
     env.local(), env.setSettings(id, changes, label), env.settingsDelete(id)             the figures of a set (as card-panels.js)
     env.choices() -> {data, loading, error}, env.reloadChoices()                          the ready settings of the card's setup (lazy, cached)
     env.applyChoice(id, choiceId), env.confirmSettings(id), env.customSettings(id)        choose, confirm, keep the numbers as typed by hand
     env.setSetup({device_id, lens_id, material_id})                                       resolves to the error text or null
   Every edit resolves to its error (an Error) or to null.

   What the operator does is choose the engraving of what they selected: ``engravingBlock`` sits at the top of the inspector of an element or
   of several, shows what the element engraves with (colour swatch, name, figures, state) and opens ``pickerDialog``, a wide dialog with the
   types and groups on the left and the settings with their figures on the right; choosing there gives the settings to the selected
   elements at once (env.assignChoice(ids, choiceId)). Sets of settings stay behind "Settings details" and in the panel shown with nothing
   selected. */
'use strict';
const CardSettings = (() => {
  const {h, fill, btn, pill, field} = App;
  const PAGE = 8;                                            // rows of a group shown at once; a group of more rows also gets a filter box
  const TYPES = [['color', 'Colour'], ['photo', 'Photo'], ['line_text', 'Lines and text'], ['deep', 'Deep engraving']];
  const KIND = {unknown: 'warn', proposed: 'warn', chosen: 'ok', custom: 'ok', other_setup: 'bad'};   // the chip's colour; its words say the same
  const NUMBERS = ['power', 'speed', 'frequency', 'pulse_width', 'line_interval'];
  const EXTRAS = ['min_power', 'scan_angle', 'dot_width'];
  const yesNo = (v) => (v ? 'Yes' : 'No');
  // [key, label, unit | formatter]: the figures a set can carry, in the order they are told
  const VALUES = [['mode', 'Mode', (v) => (v === 'line' ? 'Line' : 'Fill')], ['power', 'Power', '%'], ['speed', 'Speed', 'mm/s'], ['frequency', 'Frequency', 'kHz'],
    ['pulse_width', 'Pulse width', 'ns'], ['line_interval', 'Line interval', 'mm'], ['passes', 'Passes', ''], ['global_passes', 'Whole-work passes', ''],
    ['bidirectional', 'Bidirectional', yesNo], ['cross_hatch', 'Cross-hatch', yesNo], ['scan_angle', 'Scan angle', '°'], ['min_power', 'Minimum power', '%'],
    ['dither', 'Image mode', ''], ['dot_width', 'Dot width', 'mm']];
  const LABEL = Object.fromEntries(VALUES.map(([key, label]) => [key, label]));

  const message = (error) => (error ? error.message || String(error) : '');
  const fixed = (v) => String(+(+v).toFixed(3));
  const cap = (text) => String(text).charAt(0).toUpperCase() + String(text).slice(1).replace(/_/g, ' ');
  const show = (v, unit) => {
    if (typeof unit === 'function') return unit(v);
    const text = typeof v === 'number' ? fixed(v) : String(v);
    return !unit ? text : unit === '°' ? text + unit : `${text} ${unit}`;
  };
  const typeName = (type) => (TYPES.find(([key]) => key === type) || [type, cap(type)])[1];
  const infoOf = (data, type) => ((data && data.types) || []).find((t) => t.type === type) || null;
  const total = (info) => (info.groups || []).reduce((sum, g) => sum + (g.count ?? (g.items || []).length), 0);
  const sameSetup = (a, b) => !!a && !!b && ['device_id', 'lens_id', 'material_id'].every((k) => (a[k] ?? null) === (b[k] ?? null));

  /** Where a set stands. The server always sends ``status``; an older answer is read as the plain facts it has. */
  function statusOf(set) {
    if (set.status) return {needs: [], summary: '', ...set.status};
    return {state: set.origin ? 'custom' : 'unknown', ready: false, needs: [], summary: ''};
  }
  /** The figures of a source as one short line: ``30 % · 500 mm/s · 40 kHz`` (only what the source gives). */
  function figureLine(s) {
    s = s || {};
    const parts = [];
    if (s.power != null) parts.push(`${fixed(s.power)} %`);
    if (s.speed != null) parts.push(`${fixed(s.speed)} mm/s`);
    if (s.frequency != null) parts.push(`${fixed(s.frequency)} kHz`);
    if (s.pulse_width != null) parts.push(`${fixed(s.pulse_width)} ns`);
    if (s.line_interval != null) parts.push(`${fixed(s.line_interval)} mm interval`);
    if (s.passes != null && s.passes > 1) parts.push(`${s.passes} passes`);
    if (s.dither) parts.push(String(s.dither));
    return parts.join(' · ');
  }
  /** The figures a set has, as a read-only list (only the keys that are not null). */
  function valuesList(set) {
    const rows = VALUES.filter(([key]) => set[key] != null).map(([key, label, unit]) => [h('dt', {}, label), h('dd', {}, show(set[key], unit))]);
    return h('dl', {class: 'facts cw-facts cw-values'}, rows);
  }
  /** The names of the figures a set does not have (a line interval means nothing to a line). */
  const notGiven = (set) => VALUES.filter(([key]) => key !== 'mode' && set[key] == null && !(key === 'line_interval' && set.mode === 'line')).map(([, label]) => label.toLowerCase());
  /** The line under the name of a set: where its figures come from. */
  function originLine(set, st) {
    const o = set.origin;
    if (!o) return `Unknown: ${st.summary}`;
    if (o.kind === 'custom') return o.note ? `Typed by hand. ${o.note}` : 'Typed by hand';
    return `From: ${o.label}${o.source ? ` · ${o.source}` : ''}`;
  }
  const evidenceText = (value) => (Array.isArray(value) ? value.join(', ') : value && typeof value === 'object' ? JSON.stringify(value) : String(value));
  /** What the workshop knows about a source, for the person who wants to check it: shown on demand. */
  function sourceDetails(item) {
    const evidence = Object.entries(item.evidence || {}).filter(([key, value]) => key !== 'status' && value != null);
    return h('div', {class: 'stack cw-item-details'},
      item.detail ? h('p', {class: 'small'}, item.detail) : null,
      Object.keys(item.settings || {}).length ? h('dl', {class: 'facts cw-facts'}, VALUES.filter(([key]) => (item.settings || {})[key] != null)
        .map(([key, label, unit]) => [h('dt', {}, label), h('dd', {}, show(item.settings[key], unit))])) : null,
      evidence.length ? h('dl', {class: 'facts cw-facts'}, evidence.map(([key, value]) => [h('dt', {}, cap(key)), h('dd', {}, evidenceText(value))])) : null,
      (item.unused || []).length ? h('p', {class: 'small muted'}, `Not used for shapes and text: ${item.unused.map((k) => (LABEL[k] || cap(k)).toLowerCase()).join(', ')}.`) : null);
  }
  const evidenceBadge = (item) => {
    const status = item.evidence && item.evidence.status;
    return status ? pill(cap(status), /valid|verif|confirm|accept/i.test(status) ? 'ok' : '') : null;
  };

  // ---- the choice of ready settings: type, groups, rows ---------------------------------------------------------------------------------

  /** The chooser of one set: four types (a tab list), the groups of the chosen type as sections with counts, rows with a Use button. The
      ready settings are asked for only when the chooser is first shown (``activate``) and are the ones of the card's own setup. */
  function chooser({setId, env}) {
    let set = null, selected = 'color', picked = false, active = false, inUse = null, seen = null, version = 0, drawn = '', waiting = null;
    const groupOpen = new Map(), lists = new Map();         // the sections the person opened or closed; the lists live as long as the chooser (their filter and page stay)
    const panelId = `cw-types-panel-${setId}`;
    const buttons = TYPES.map(([type, label]) => h('button', {type: 'button', role: 'tab', class: 'vw-tab cw-type', id: `cw-type-${setId}-${type}`, 'data-type': type,
      'aria-controls': panelId, onClick: () => pick(type)}, h('span', {class: 'cw-type-name'}, label), ' ', h('span', {class: 'cw-type-count muted'})));
    const tabList = h('div', {role: 'tablist', class: 'vw-tabs cw-types', 'aria-label': 'Type of engraving'}, buttons);
    const panel = h('div', {role: 'tabpanel', class: 'cw-type-panel stack', id: panelId});
    const failure = h('p', {class: 'alert bad small', role: 'alert', hidden: true});
    const said = h('p', {class: 'sr-only', role: 'status', 'aria-live': 'polite'});
    const el = h('div', {class: 'stack cw-choose', id: `cw-choose-${setId}`, role: 'group', 'aria-label': 'Ready engraving settings'},
      h('p', {class: 'small muted cw-choose-note'}, 'Settings the workshop measured for the laser, lens and material of this card. Choose the type of engraving first.'),
      tabList, failure, said, panel);
    tabList.addEventListener('keydown', (ev) => {
      const at = TYPES.findIndex(([type]) => type === selected);
      const to = ev.key === 'ArrowRight' ? (at + 1) % TYPES.length : ev.key === 'ArrowLeft' ? (at + TYPES.length - 1) % TYPES.length : ev.key === 'Home' ? 0 : ev.key === 'End' ? TYPES.length - 1 : -1;
      if (to < 0) return;
      ev.preventDefault();
      pick(TYPES[to][0]);
      buttons[to].focus();
    });

    function pick(type) { selected = type; picked = true; draw(); }
    /** The type shown before the person chooses one: the one the set came from, else the first that has settings. */
    function firstType(data) {
      const known = (type) => { const info = infoOf(data, type); return !!info && info.known; };
      const o = set && set.origin;
      if (o && o.kind === 'choice' && known(o.type)) return o.type;
      const withRows = TYPES.map(([type]) => type).find((type) => known(type) && total(infoOf(data, type)) > 0);
      return withRows || 'color';
    }
    function paintTabs(data) {
      for (const b of buttons) {
        const type = b.getAttribute('data-type'), info = infoOf(data, type), on = type === selected;
        b.setAttribute('aria-selected', String(on));
        b.setAttribute('tabindex', on ? '0' : '-1');
        b.classList.toggle('active', on);
        fill(b.querySelector('.cw-type-count'), !data ? '' : info && info.known ? `(${total(info)})` : 'unknown');
      }
    }

    // a use button never goes dead: the one in use is pressed, not disabled, so that the keyboard stays where it is
    function useButton(item) {
      const on = item.id === inUse;
      const b = btn(on ? 'In use' : 'Use', () => use(item), 'btn-small cw-use' + (on ? '' : ' primary'));
      b.setAttribute('aria-pressed', String(on));
      b.setAttribute('aria-label', on ? `${item.label}: in use` : `Use ${item.label}`);
      b.setAttribute('data-choice', item.id);
      return b;
    }
    async function use(item) {
      if (item.id === inUse) return;
      const error = message(await env.applyChoice(setId, item.id));
      failure.textContent = error; failure.hidden = !error;
      if (error) { env.reloadChoices(); refresh(); return; }
      fill(said, `Using “${item.label}” for ${set ? set.name : 'these settings'}.`);
    }
    function itemRow(item) {
      const swatch = item.swatch && /^#[0-9a-f]{6}$/i.test(item.swatch.srgb || '')
        ? h('span', {class: 'sw cw-swatch', style: `background:${item.swatch.srgb}`, role: 'img', 'aria-label': `Colour ${item.swatch.srgb}`}) : null;
      // the sentence about the source is in the details (opened on demand); the row keeps the name, the evidence and the figures
      return [swatch, h('strong', {class: 'lst-text cw-item-label'}, item.label), evidenceBadge(item),
        h('span', {class: 'small cw-figures'}, figureLine(item.settings) || 'no figures given')];
    }
    function fillGroup(key, group, body) {
      const many = (group.items || []).length > PAGE;
      let entry = lists.get(key);
      if (entry && entry.many !== many) { lists.delete(key); entry = null; }
      if (!entry) {
        const list = App.list({items: group.items || [], key: (i) => i.id, page: PAGE, className: 'cw-list' + (many ? '' : ' cw-list-small'),
          search: many ? (i) => `${i.label} ${i.detail || ''} ${figureLine(i.settings)}` : null, rowClass: (i) => (i.id === inUse ? 'cw-in-use' : ''),
          row: itemRow, details: (i) => sourceDetails(i), actions: (i) => [useButton(i)],
          empty: 'No settings in this group.', noResults: 'No setting of this group matches this filter.'});
        const box = many ? list.el.querySelector('.lst-search') : null;
        if (box) { box.setAttribute('aria-label', `Filter ${group.label}`); box.setAttribute('placeholder', 'Filter…'); }
        entry = {list, many};
        lists.set(key, entry);
      } else { entry.list.items = group.items || []; entry.list.refresh(); }
      fill(body, entry.list.el);
    }
    function groupBox(type, group, index) {
      const key = `${type}/${index}`, wanted = groupOpen.has(key) ? groupOpen.get(key) : index === 0;       // by place: the groups of one type share a source, only their labels differ
      const body = h('div', {class: 'cw-group-body'});
      const count = group.count ?? (group.items || []).length;
      const box = h('details', {class: 'cw-group', 'data-source': group.source},
        h('summary', {}, h('span', {class: 'cw-group-name'}, group.label), ' ', pill(String(count)), h('span', {class: 'sr-only'}, count === 1 ? ' setting' : ' settings')), body);
      box.open = wanted;
      if (wanted) fillGroup(key, group, body);
      box.addEventListener('toggle', () => { groupOpen.set(key, box.open); if (box.open) fillGroup(key, group, body); });
      return box;
    }
    function paintPanel(data, c) {
      panel.setAttribute('aria-labelledby', `cw-type-${setId}-${selected}`);
      if (!data) {
        fill(panel, c.error ? h('div', {class: 'alert bad small', role: 'alert'}, `Could not load the ready settings: ${c.error} `,
          btn('Retry', () => { env.reloadChoices(); refresh(); }, 'btn-small'))
          : h('p', {class: 'small muted', role: 'status'}, 'Loading the ready settings…'));
        return;
      }
      const info = infoOf(data, selected) || {known: false, reason: 'The workshop has no information about this type of engraving for this laser, lens and material.'};
      if (!info.known) {
        fill(panel, h('p', {class: 'cw-unknown-title'}, h('strong', {}, `${typeName(selected)}: unknown`)),
          h('p', {class: 'alert warn small cw-reason', role: 'status'}, info.reason || 'Nothing of this type has been measured for this laser, lens and material.'));
        return;
      }
      const groups = info.groups || [];
      fill(panel, groups.length ? groups.map((g, i) => groupBox(selected, g, i))
        : h('p', {class: 'small muted'}, 'No ready settings of this type are measured for this laser, lens and material.'));
    }
    function draw() {
      if (!active) return;
      const c = env.choices(), data = c.data;                // the env gives only what was measured for the card's setup as it is now
      if (data !== seen) { seen = data; version += 1; }
      if (!picked) selected = firstType(data);
      paintTabs(data);
      const sig = [selected, version, c.error || '', c.loading ? 1 : 0, data ? 1 : 0].join('|');
      if (sig !== drawn) { drawn = sig; paintPanel(data, c); }
    }
    function refresh() {
      if (!active) return;
      const c = env.choices();
      if (c.promise && waiting !== c.promise) { waiting = c.promise; c.promise.then(draw, draw); }
      draw();
    }
    return {el, activate() { active = true; refresh(); },
      update(next) {
        set = next;
        const st = statusOf(next).state, o = next.origin;
        const now = o && o.kind === 'choice' && (st === 'chosen' || st === 'proposed') ? o.choice_id : null;
        if (now !== inUse) { inUse = now; for (const entry of lists.values()) entry.list.refresh(); }
        refresh();
      },
      focus() { const b = buttons.find((x) => x.getAttribute('data-type') === selected); if (b) b.focus(); }};
  }

  // ---- one set of settings --------------------------------------------------------------------------------------------------------------

  /** One set: a line (name, state, where its figures come from) that opens to its figures, the choice of ready settings and, last and quiet,
      the custom values. ``controls`` are card-panels.js's {numberControl, textControl, Q}. */
  function setRow(first, env, controls, options = {}) {
    const compact = !!options.compact;                       // inside the inspector of an element: its figures and custom values only, the choice is the dialog's
    const {numberControl, textControl, Q} = controls;
    const id = first.id, K = (p) => `s${id}:${p}`, local = env.local;
    const commit = (changes, label) => env.setSettings(id, changes, label);
    let last = first, status = statusOf(first), chooseOpen = false, custom = null, drawn = '';

    const name = textControl({label: 'Name', key: K('name'), local, nonEmpty: true, commit: (v) => commit({name: v}, 'Name')});
    const mark = h('strong', {class: 'cw-set-name'}), flags = h('span', {class: 'cw-set-flags'});
    const chip = h('span', {class: 'pill cw-chip'}), origin = h('span', {class: 'small muted cw-origin'}), needs = h('span', {class: 'small cw-set-needs'});
    const failure = h('p', {class: 'alert bad small', role: 'alert', hidden: true});
    const say = (text) => { failure.textContent = text; failure.hidden = !text; };

    // what the set has now: its figures (read only), and what to do with a proposal or a set chosen for another setup
    const note = h('p', {class: 'alert warn small cw-other', hidden: true});
    const values = h('div', {class: 'stack cw-values-box'});
    const confirmSlot = h('span', {class: 'row cw-confirm'});
    const chooser_ = chooser({setId: id, env});
    const choose = btn('Choose others', () => { chooseOpen = !chooseOpen; paintChoose(); if (chooseOpen) chooser_.focus(); }, 'btn-small cw-choose-btn');
    choose.setAttribute('aria-controls', `cw-choose-${id}`);
    const decide = h('div', {class: 'row cw-decide'}, confirmSlot, choose);
    // the same wide choice as in the inspector of an element, here for this whole set (the card's default one is what an element without its own choice engraves with)
    const wide = btn('Choose colour / engraving…', () => {
      const o = last.origin;
      pickerDialog(env, {subject: `“${last.name}”`, inUse: o && o.kind === 'choice' && status.state === 'chosen' ? {id: o.choice_id, type: o.type} : null, onPick: (item) => env.applyChoice(id, item.id)});
    }, 'btn-small cw-wide-btn');

    const customBody = h('div', {class: 'stack cw-custom-body'});
    const customBox = h('details', {class: 'cw-custom', onToggle: () => { if (customBox.open) buildCustom(); }},
      h('summary', {}, 'Custom values'), customBody);
    /** The number boxes: built when the person opens "Custom values", so that a set with nothing chosen offers choices and no blank form. */
    function buildCustom() {
      if (custom) return;
      const mode = h('div', {class: 'row cw-mode', role: 'radiogroup', 'aria-label': 'Mode'}, [['fill', 'Fill'], ['line', 'Line']].map(([value, text]) => h('label', {class: 'row small'},
        h('input', {type: 'radio', name: `cw-mode-${id}`, value, 'aria-label': text, onChange: async () => { say(message(await commit({mode: value}, 'Mode'))); }}), h('span', {}, text))));
      const number = (p, extra = {}) => [p, numberControl({label: Q[p].label, key: K(p), local, quantity: Q[p], clearable: true, commit: (v) => commit({[p]: v}, Q[p].label), ...extra})];
      const fields = NUMBERS.map((p) => number(p));
      const passes = numberControl({label: 'Passes', key: K('passes'), local, quantity: Q.passes, commit: (v) => commit({passes: v}, 'Passes')});
      const extras = EXTRAS.map((p) => number(p));
      const dither = textControl({label: 'Image mode', key: K('dither'), local, commit: (v) => commit({dither: v.trim() || null}, 'Image mode')});
      const keep = btn('Keep these numbers as custom values', async () => { say(message(await env.customSettings(id))); }, 'btn-small cw-keep');
      fill(customBody, h('p', {class: 'small muted cw-custom-note'}, 'Typing numbers is the last resort: it is not a measured setting.'), mode,
        fields.map(([, c]) => c.el), passes.el, extras.map(([, c]) => c.el), dither.el, keep);
      custom = {mode, fields, passes, extras, dither, keep,
        sync(set) {
          const now = local()[K('mode')] ?? set.mode;
          for (const radio of mode.querySelectorAll('input')) radio.checked = radio.value === now;
          for (const [p, c] of fields) { c.sync(set[p]); if (p === 'line_interval') c.el.hidden = now === 'line'; }
          passes.sync(set.passes);
          for (const [p, c] of extras) c.sync(set[p]);
          dither.sync(set.dither);
          keep.hidden = !(set.origin && set.origin.kind === 'choice');
        }};
      custom.sync(last);
    }

    const remove = btn('Delete settings', () => env.settingsDelete(id), 'btn-small danger');
    const usage = h('p', {class: 'small muted'});
    const head = h('summary', {}, ...(compact ? ['Figures and custom values of these settings'] : [mark, ' ', flags, chip, origin, needs]));
    const el = h('details', {class: 'cw-set' + (compact ? ' cw-set-compact' : ''), 'data-set': String(id), onToggle: () => { if (el.open) paintChoose(); }},
      head, h('div', {class: 'stack cw-set-body'}, ...(compact ? [values, failure, customBox, usage]
        : [h('div', {class: 'row cw-wide'}, wide), name.el, note, values, decide, chooser_.el, failure, customBox, usage, remove])));

    async function confirm() {
      say(message(await env.confirmSettings(id)));
      if (!el.contains(document.activeElement) && head.focus) head.focus();      // the button that was pressed is gone with the proposal
    }
    function paintValues() {
      const st = status.state, set = last, custom_ = set.origin && set.origin.kind === 'custom';
      values.hidden = st === 'unknown';
      if (st === 'unknown') { fill(values, null); return; }
      const missing = notGiven(set), o = set.origin;
      const evidence = o ? Object.entries(o.evidence || {}).filter(([key, value]) => key !== 'status' && value != null) : [];
      fill(values, h('p', {class: 'cw-values-title'}, h('strong', {}, st === 'proposed' ? 'Proposed settings' : 'Settings in use')), valuesList(set),
        missing.length ? h('details', {class: 'small cw-notgiven'}, h('summary', {}, `${custom_ ? 'Not set' : 'Not given by the source'} (${missing.length})`), h('p', {}, `${missing.join(', ')}.`)) : null,
        o && (o.detail || evidence.length) ? h('details', {class: 'small cw-source'}, h('summary', {}, 'About these settings'), o.detail ? h('p', {}, o.detail) : null,
          evidence.length ? h('dl', {class: 'facts cw-facts'}, evidence.map(([key, value]) => [h('dt', {}, cap(key)), h('dd', {}, evidenceText(value))])) : null) : null);
    }
    function paintDecision() {
      const st = status.state, o = last.origin;
      const label = st === 'other_setup' && o && o.kind === 'custom' ? 'Confirm for this setup' : (st === 'proposed' || (st === 'custom' && !last.confirmed)) ? 'Confirm these settings' : null;
      fill(confirmSlot, label ? btn(label, confirm, 'primary cw-confirm-btn') : null);
      note.hidden = st !== 'other_setup';
      fill(note, st !== 'other_setup' ? null : o && o.kind === 'custom'
        ? 'These numbers were typed for another laser, lens or material. Confirm them for this setup, or choose settings measured for it.'
        : 'These figures were measured for another laser, lens or material and are not used here. Choose settings measured for this setup.');
    }
    /** The choice is always open for a set with nothing chosen or chosen for another setup; otherwise it is one press away. */
    function paintChoose() {
      const st = status.state, auto = st === 'unknown' || st === 'other_setup', shown = auto || chooseOpen;
      choose.hidden = auto;
      fill(choose, st === 'custom' ? 'Choose ready settings' : 'Choose others');
      choose.setAttribute('aria-expanded', String(shown));
      chooser_.el.hidden = !shown;
      decide.hidden = auto && !confirmSlot.firstChild;
      if (shown && el.open && !compact) chooser_.activate();
    }

    return {el, id, isOpen: () => el.open, open: () => { el.open = true; paintChoose(); },
      sync(set, used, count) {
        last = set; status = statusOf(set);
        fill(mark, set.name);
        name.sync(set.name);
        fill(flags, set.id === used.defaultId ? pill('default') : null);
        chip.className = `pill ${KIND[status.state] || ''} cw-chip cw-chip-${status.state}`;
        chip.setAttribute('data-state', status.state);
        fill(chip, status.summary || cap(status.state));
        fill(origin, originLine(set, status));
        fill(needs, status.needs.length ? `Needs: ${status.needs.join('; ')}` : null);
        needs.hidden = !status.needs.length;
        el.setAttribute('data-state', status.state);
        const sig = JSON.stringify(set);
        if (sig !== drawn) { drawn = sig; paintValues(); paintDecision(); }
        paintChoose();
        chooser_.update(set);
        if (custom) custom.sync(set);
        fill(usage, used.names.length ? `Used by: ${used.names.slice(0, 6).join(', ')}${used.names.length > 6 ? ` and ${used.names.length - 6} more` : ''}.`
          : 'No element uses these settings (elements without their own settings use the default ones).');
        remove.disabled = count < 2;
        remove.setAttribute('title', count < 2 ? 'A card keeps at least one set of engraving settings' : 'Delete these engraving settings');
      }};
  }

  // ---- the wide choice, for what is selected ----------------------------------------------------------------------------------------------

  const PICK_PAGE = 12;                                       // rows shown at once in the wide list (it has room); a filter box is always there
  /** The dialog that chooses ready settings FOR what is selected: the types of engraving and their groups on the left, the settings of the chosen
      group (or of the whole type) on the right, each with its figures, its evidence and a Use button. ``onPick(item)`` resolves to an error or
      null; the dialog closes by itself when the choice was taken. ``inUse`` ({id, type}) marks the setting the selection engraves with now and
      ``prefer`` names the type to show first (pictures engraved as photos want ``photo``). */
  function pickerDialog(env, {subject, prefer = null, inUse = null, onPick}) {
    let selected = null, group = '', seen = null, waiting = null, picked = false, dlg = null, version = 0;
    const lists = new Map();
    const setup = env.setup() || {};
    const where = [setup.device ? setup.device.name : 'no laser', setup.lens ? setup.lens.name : 'unknown lens', setup.material ? setup.material.name : 'no material'].join(' · ');
    const types = h('div', {role: 'tablist', 'aria-orientation': 'vertical', class: 'cw-pick-types', 'aria-label': 'Type of engraving'});
    const groupsBox = h('div', {class: 'cw-pick-groups', role: 'group', 'aria-label': 'Groups of this type'});
    const main = h('div', {class: 'stack cw-pick-main'});
    const failure = h('p', {class: 'alert bad small', role: 'alert', hidden: true});
    const said = h('p', {class: 'sr-only', role: 'status', 'aria-live': 'polite'});
    const body = h('div', {class: 'stack cw-picker'},
      h('p', {class: 'small muted cw-pick-note'}, `Settings the workshop measured for ${where}. Nothing from another laser, lens or material is offered.`), failure, said,
      h('div', {class: 'cw-pick-cols'}, h('div', {class: 'stack cw-pick-side'}, types, groupsBox), main));

    const known = (data, type) => { const info = infoOf(data, type); return !!info && info.known; };
    function firstType(data) {
      for (const wanted of [prefer, inUse && inUse.type]) if (wanted && known(data, wanted) && total(infoOf(data, wanted)) > 0) return wanted;
      return TYPES.map(([type]) => type).find((type) => known(data, type) && total(infoOf(data, type)) > 0) || 'color';
    }
    function pick(type) { selected = type; group = ''; picked = true; draw(); }
    function pickGroup(place) { group = place; draw(); }
    types.addEventListener('keydown', (ev) => {
      const at = TYPES.findIndex(([type]) => type === selected);
      const to = ev.key === 'ArrowDown' ? (at + 1) % TYPES.length : ev.key === 'ArrowUp' ? (at + TYPES.length - 1) % TYPES.length : ev.key === 'Home' ? 0 : ev.key === 'End' ? TYPES.length - 1 : -1;
      if (to < 0) return;
      ev.preventDefault();
      pick(TYPES[to][0]);
      const next = [...types.querySelectorAll('button')].find((b) => b.getAttribute('data-type') === TYPES[to][0]);
      if (next) next.focus();
    });

    async function use(item) {
      if (inUse && item.id === inUse.id) { dlg.close(); return; }
      const error = message(await onPick(item));
      failure.textContent = error; failure.hidden = !error;
      if (error) { env.reloadChoices(); refresh(); return; }
      fill(said, `Using “${item.label}” for ${subject}.`);
      dlg.close();
    }
    function useButton(item) {
      const on = !!inUse && item.id === inUse.id;
      const b = btn(on ? 'In use' : 'Use', () => use(item), 'btn-small cw-use' + (on ? '' : ' primary'));
      b.setAttribute('aria-pressed', String(on));
      b.setAttribute('aria-label', on ? `${item.label}: in use` : `Use ${item.label} for ${subject}`);
      b.setAttribute('data-choice', item.id);
      return b;
    }
    function rowOf(item) {
      const swatch = item.swatch && /^#[0-9a-f]{6}$/i.test(item.swatch.srgb || '')
        ? h('span', {class: 'sw cw-swatch', style: `background:${item.swatch.srgb}`, role: 'img', 'aria-label': `Colour ${item.swatch.srgb}`}) : null;
      return [swatch, h('strong', {class: 'lst-text cw-item-label'}, item.label), evidenceBadge(item), h('span', {class: 'small cw-figures'}, figureLine(item.settings) || 'no figures given')];
    }
    function listOf(info) {
      const key = `${selected}/${group}/${version}`;
      let entry = lists.get(key);
      if (!entry) {
        const groups = info.groups || [];
        const items = group === '' ? groups.flatMap((g) => g.items || []) : ((groups[Number(group)] || {}).items || []);
        const list = App.list({items, key: (i) => i.id, page: PICK_PAGE, className: 'cw-list cw-list-wide', search: (i) => `${i.label} ${i.detail || ''} ${figureLine(i.settings)}`,
          rowClass: (i) => (inUse && i.id === inUse.id ? 'cw-in-use' : ''), row: rowOf, details: (i) => sourceDetails(i), actions: (i) => [useButton(i)],
          empty: 'No settings in this group.', noResults: 'No setting matches this filter.'});
        const box = list.el.querySelector('.lst-search');
        if (box) { box.setAttribute('aria-label', 'Filter the settings'); box.setAttribute('placeholder', 'Filter…'); }
        entry = {list};
        lists.set(key, entry);
      }
      return entry.list.el;
    }
    function paintTypes(data) {
      fill(types, TYPES.map(([type, label]) => {
        const info = infoOf(data, type), on = type === selected;
        const b = h('button', {type: 'button', role: 'tab', class: 'cw-pick-type' + (on ? ' active' : ''), 'data-type': type, 'aria-selected': String(on), tabindex: on ? '0' : '-1', onClick: () => pick(type)},
          h('span', {class: 'cw-type-name'}, label), ' ', h('span', {class: 'cw-type-count muted'}, !data ? '' : info && info.known ? String(total(info)) : 'unknown'));
        return b;
      }));
    }
    function paintGroups(info) {
      const groups = info && info.known ? info.groups || [] : [];
      if (groups.length < 2) { fill(groupsBox, null); groupsBox.hidden = true; return; }
      groupsBox.hidden = false;
      const one = (place, label, count) => h('button', {type: 'button', class: 'cw-pick-group' + (group === place ? ' active' : ''), 'data-group': place, 'aria-pressed': String(group === place),
        onClick: () => pickGroup(place)}, h('span', {class: 'cw-group-name'}, label), ' ', h('span', {class: 'cw-type-count muted'}, String(count)));
      fill(groupsBox, h('p', {class: 'small muted cw-pick-heading'}, `${typeName(selected)}: groups`), one('', 'All', total(info)), groups.map((g, i) => one(String(i), g.label, g.count ?? (g.items || []).length)));
    }
    function paintMain(data, c) {
      if (!data) {
        fill(main, c.error ? h('div', {class: 'alert bad small', role: 'alert'}, `Could not load the ready settings: ${c.error} `, btn('Retry', () => { env.reloadChoices(); refresh(); }, 'btn-small'))
          : h('p', {class: 'small muted', role: 'status'}, 'Loading the ready settings…'));
        return;
      }
      const info = infoOf(data, selected) || {known: false, reason: 'The workshop has no information about this type of engraving for this laser, lens and material.'};
      if (!info.known) {
        fill(main, h('p', {class: 'cw-unknown-title'}, h('strong', {}, `${typeName(selected)}: unknown`)),
          h('p', {class: 'alert warn small cw-reason', role: 'status'}, info.reason || 'Nothing of this type has been measured for this laser, lens and material.'));
        return;
      }
      fill(main, h('p', {class: 'cw-pick-heading'}, h('strong', {}, typeName(selected)), group ? ` · ${((info.groups || [])[Number(group)] || {}).label || ''}` : ''), listOf(info));
    }
    function draw() {
      const c = env.choices(), data = c.data;
      if (data !== seen) { seen = data; version += 1; }
      if (!picked && data) selected = firstType(data);
      if (!selected) selected = prefer || (inUse && inUse.type) || 'color';
      paintTypes(data);
      paintGroups(data ? infoOf(data, selected) : null);
      paintMain(data, c);
    }
    function refresh() {
      const c = env.choices();
      if (c.promise && waiting !== c.promise) { waiting = c.promise; c.promise.then(draw, draw); }
      draw();
    }
    dlg = App.modal(`Choose the engraving for ${subject}`, body, [{label: 'Close', run: (m) => m.close(), initial: true}]);
    refresh();
    return dlg;
  }

  // ---- the engraving of what is selected, at the top of its inspector -------------------------------------------------------------------

  /** Which elements (of both sides) engrave with a set, from the review the server made. */
  function usageOf(view, id) {
    const names = [];
    for (const side of Object.keys(view.review || {})) names.push(...view.review[side].elements.filter((x) => x.effective_settings_id === id).map((x) => x.name));
    return {names, defaultId: view.default_settings_id};
  }
  const swatchOf = (set) => (set && set.origin && /^#[0-9a-f]{6}$/i.test(set.origin.swatch || '') ? set.origin.swatch : null);
  const nameOf = (elements) => (elements.length === 1 ? elements[0].name : `${elements.length} elements`);

  /** The block of the inspector that says what the selected elements engrave with and lets the operator change it in one step: a swatch, the name
      of the settings, their figures and state, and "Choose colour / engraving…" (the wide dialog). ``extra`` is a node (the old choice among the
      card's sets) shown under "Settings details" with the figures and the custom values of the settings. */
  function engravingBlock(env, controls, extra = null) {
    const swatch = h('span', {class: 'sw cw-swatch cw-eng-swatch', 'aria-hidden': 'true', hidden: true});
    const name = h('strong', {class: 'cw-eng-name'}), chip = h('span', {class: 'pill cw-chip'}), figures = h('p', {class: 'small cw-eng-figures'});
    const shared = h('p', {class: 'small muted cw-eng-shared'}), failure = h('p', {class: 'alert bad small', role: 'alert', hidden: true});
    const confirmSlot = h('span', {class: 'cw-eng-confirm'});
    let current = [], row = null, rowId = null, shown = null;
    const choose = btn('Choose colour / engraving…', () => {
      if (!current.length) return;
      const set = effective(current);
      const o = set && set.origin, st = set ? statusOf(set) : null;
      pickerDialog(env, {subject: nameOf(current), inUse: o && o.kind === 'choice' && st.state === 'chosen' ? {id: o.choice_id, type: o.type} : null,
        prefer: current.some((e) => e.type === 'image' && e.image && e.image.engrave === 'raster') ? 'photo' : null,
        onPick: (item) => env.assignChoice(current.map((e) => e.id), item.id)});
    }, 'primary cw-eng-choose');
    const detailsBody = h('div', {class: 'stack cw-eng-details-body'});
    const details = h('details', {class: 'cw-eng-details'}, h('summary', {}, 'Settings details'), detailsBody);
    const el = h('section', {class: 'stack cw-engraving-block', 'aria-label': 'Engraving of the selection'},
      h('div', {class: 'row cw-eng-head'}, swatch, name, h('span', {class: 'spacer'}), chip), figures, shared, failure, h('div', {class: 'row cw-eng-actions'}, choose, confirmSlot), details);
    /** The id of the set all of ``elements`` engrave with, or null when they differ. */
    const idOf = (elements) => {
      const view = env.view(), ids = new Set(elements.map((e) => (e.settings_id == null ? view.default_settings_id : e.settings_id)));
      return ids.size === 1 ? [...ids][0] : null;
    };
    function effective(elements) { const id = idOf(elements); return id == null ? null : env.view().settings.find((s) => s.id === id) || null; }
    async function confirm(set) {
      const error = message(await env.confirmSettings(set.id));
      failure.textContent = error; failure.hidden = !error;
    }
    return {el, choose, sync(elements) {
      current = elements;
      const view = env.view(), set = effective(elements);
      if (!set) {                                             // the selection engraves with more than one set
        swatch.hidden = true;
        fill(name, 'Mixed engravings'); fill(chip, null); chip.hidden = true;
        fill(figures, `${elements.length} elements engrave with different settings. Choose one to give all of them the same.`);
        fill(shared, null); fill(confirmSlot, null);
        row = null; rowId = null;
        if (shown !== 'mixed') { shown = 'mixed'; fill(detailsBody, extra); }
        return;
      }
      const st = statusOf(set), o = set.origin, colour = swatchOf(set);
      swatch.hidden = !colour;
      if (colour) swatch.setAttribute('style', `background:${colour}`);
      fill(name, st.state === 'unknown' ? 'No engraving chosen yet' : o && o.kind === 'choice' ? o.label : `${set.name} (typed by hand)`);
      chip.hidden = false;
      chip.className = `pill ${KIND[st.state] || ''} cw-chip cw-chip-${st.state}`;
      chip.setAttribute('data-state', st.state);
      fill(chip, st.state === 'unknown' ? 'Unknown' : st.state === 'proposed' ? 'Proposed: confirm' : st.state === 'chosen' ? 'Chosen' : st.state === 'custom' ? 'Typed by hand' : 'Another setup');
      fill(figures, st.state === 'unknown' ? st.summary : figureLine(set) || 'no figures given');
      const used = usageOf(view, set.id), others = used.names.filter((n) => !elements.some((e) => e.name === n));
      const isDefault = set.id === view.default_settings_id;
      fill(shared, isDefault ? 'These are the card’s default settings: every element without its own choice engraves with them.'
        : others.length ? `Also used by ${others.slice(0, 4).join(', ')}${others.length > 4 ? ` and ${others.length - 4} more` : ''}.` : null);
      const needsConfirm = st.state === 'proposed' || (st.state === 'custom' && !set.confirmed) || (st.state === 'other_setup' && o && o.kind === 'custom');
      fill(confirmSlot, needsConfirm ? btn(st.state === 'other_setup' ? 'Confirm for this setup' : 'Confirm these settings', () => confirm(set), 'cw-eng-confirm-btn') : null);
      fill(choose, st.state === 'unknown' ? 'Choose colour / engraving…' : 'Change colour / engraving…');
      if (rowId !== set.id) { row = setRow(set, env, controls, {compact: true}); rowId = set.id; shown = null; }
      row.sync(set, used, view.settings.length);
      if (shown !== rowId) { shown = rowId; fill(detailsBody, row.el, extra); }           // the nodes are moved only when the set changes: a field being typed in keeps its focus
    }};
  }

  // ---- the laser, lens and material of the card -------------------------------------------------------------------------------------

  const MISSING = {device: 'the laser', laser: 'the laser', lens: 'the lens', material: 'the material', material_id: 'the material', device_id: 'the laser'};
  /** What is still to choose, in words. */
  function missingText(setup) {
    const named = (setup.missing || []).map((m) => MISSING[m] || String(m));
    const parts = [];
    if (!setup.material) parts.push('The material of this card is not chosen, so no ready engraving settings can be offered or confirmed.');
    if (!setup.device) parts.push('The laser of this card is not chosen.');
    if (named.length && !parts.length) parts.push(`Still to choose: ${named.join(', ')}.`);
    return parts.join(' ');
  }

  /** The dialog that changes the laser, lens or material of the card (the lens may be unknown). It says what happens to the sets already chosen. */
  async function setupDialog(env, setup) {
    const lists = await App.hardwareLists();
    const pick = App.laserLensPicker(lists, {device: setup.device_id, lens: setup.lens_id == null ? 'unknown' : setup.lens_id, defaultLens: 'installed'});
    const unknownLens = () => { for (const o of [...pick.lens.options]) if (String(o.value) === 'unknown') o.textContent = 'Unknown lens'; };
    unknownLens();
    pick.laser.addEventListener('change', unknownLens);
    const stock = MaterialPicker.create({value: setup.material_id, name: 'Material', title: 'Choose the material of this card'});
    const failure = h('p', {class: 'alert bad small', role: 'alert', hidden: true});
    return App.modal('Laser, lens and material of the card', h('div', {class: 'stack'},
      h('p', {class: 'small'}, 'Engraving settings are offered only for the laser, lens and material of this card. If you change them, settings chosen for the old setup are replaced '
        + 'by choices for the new one or become unknown. Settings typed by hand keep their numbers and must be confirmed again.'),
      h('div', {class: 'grid g2'}, field('Laser', pick.laser), field('Lens', pick.lens), field('Material', stock)), failure),
    [{label: 'Cancel', run: (m) => m.close()}, {label: 'Change setup', cls: 'primary', run: async (m) => {
      if (stock.value === '') { failure.textContent = 'Choose the material of this card.'; failure.hidden = false; return; }
      const error = message(await env.setSetup({device_id: pick.deviceId(), lens_id: pick.lensId(), material_id: +stock.value}));
      failure.textContent = error; failure.hidden = !error;
      if (!error) m.close();
    }}]);
  }

  /** The setup bar at the top of the panel: laser, lens and material of the card, and a way to change them. */
  function setupBar(env) {
    const line = h('p', {class: 'cw-setup-line'}), missing = h('p', {class: 'alert warn small cw-setup-missing', role: 'status', hidden: true});
    const change = btn('Change', async () => {
      change.disabled = true;
      try { await setupDialog(env, env.setup()); } catch (e) { App.fail(e); } finally { change.disabled = false; }
    }, 'btn-small cw-setup-change');
    change.setAttribute('aria-label', 'Change the laser, lens or material of this card');
    const el = h('section', {class: 'stack cw-setup', 'aria-label': 'Laser, lens and material of this card'}, h('div', {class: 'row'}, line, h('span', {class: 'spacer'}), change), missing);
    return {el, change,
      sync(setup) {
        const parts = [setup.device ? `Laser ${setup.device.name}` : 'No laser', setup.lens ? `Lens ${setup.lens.name}` : 'Unknown lens', setup.material ? `Material ${setup.material.name}` : 'No material'];
        fill(line, parts.map((p, i) => h('span', {class: 'cw-setup-part'}, p, i < parts.length - 1 ? h('span', {class: 'muted', 'aria-hidden': 'true'}, ' · ') : null)));
        const words = setup.material && setup.complete ? '' : missingText(setup);
        missing.hidden = !words;
        fill(missing, words);
      }};
  }

  return {PAGE, PICK_PAGE, TYPES, VALUES, figureLine, valuesList, notGiven, originLine, statusOf, chooser, setRow, setupBar, setupDialog, missingText, sameSetup, typeName,
    pickerDialog, engravingBlock, swatchOf, usageOf};
})();
