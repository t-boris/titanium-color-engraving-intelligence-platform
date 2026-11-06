/* The selector of a titanium stock record: a search and the records used last instead of a list of all (ux-growing-collections-p0, REQ-001).
   A control that shows the chosen record and opens a dialog to change it: a search, the records used last, and the whole catalogue a page of
   twenty at a time (GET /materials?limit=20) with the grade as a filter. What is chosen is always one concrete batch or sheet (a record),
   never a grade. The control holds ``value`` (the id as text, or an empty string when nothing is chosen) and reports ``onChange``. */
'use strict';
const MaterialPicker = (() => {
  const {h, fill, btn, link, get, modal} = App;
  const RECENT = 5;
  const SORTS = [['name', 'Name'], ['grade', 'Grade'], ['thickness', 'Thickness'], ['newest', 'Recently added']];

  /** Show the record name, grade, batch and thickness together. */
  const label = (m) => [m.name, m.grade, m.batch && `batch ${m.batch}`, m.thickness_mm != null && `${+m.thickness_mm} mm`].filter(Boolean).join(' · ');
  /** A page of the catalogue; an older server that answers with the plain list is read as one page. */
  async function page(params) {
    const answer = await get('/materials?' + new URLSearchParams(params));
    return Array.isArray(answer) ? {items: answer, total: answer.length, all: answer.length, counts: {}, options: {}} : answer;
  }

  /** The control. ``opts``: ``value`` (a record id to start with), ``initial: 'recent'`` (start with the record used last when no ``value`` is
      given), ``onChange(record | null)``, ``empty`` (the line while nothing is chosen), ``allowEmpty`` (a way to choose nothing, named by ``clearLabel``), ``title`` (of
      the dialog), ``name`` (the control's accessible name). Returns the element: ``value`` (get and set), ``record`` (the chosen one),
      ``ready`` (a promise that resolves once the start value is read). */
  function create(opts = {}) {
    let chosen = null, sequence = 0;
    let value = opts.value == null ? '' : String(opts.value);
    const shown = h('span', {class: 'matpick-label', role: 'status'});
    const change = btn('Choose…', () => open(), 'btn-small matpick-button');
    change.setAttribute('aria-haspopup', 'dialog');
    if (opts.name) change.setAttribute('aria-label', `${opts.name}: choose`);
    const clear = opts.allowEmpty ? btn(opts.clearLabel || 'Clear selection', () => set(null), 'btn-small matpick-clear') : null;
    const el = h('div', {class: 'matpick', role: 'group', 'aria-label': opts.name || 'Stock'}, shown, ' ', change, ' ', clear);
    Object.defineProperty(el, 'value', {get: () => value, set: (v) => { select(v == null ? '' : String(v)); }, configurable: true});
    Object.defineProperty(el, 'record', {get: () => chosen, configurable: true});
    const draw = () => {
      shown.textContent = chosen ? label(chosen) : (value ? `Stock #${value}` : (opts.empty || 'No stock selected'));
      if (clear) clear.hidden = !value;
    };
    function set(record) {
      ++sequence;
      chosen = record;
      value = record ? String(record.id) : '';
      draw();
      if (opts.onChange) opts.onChange(record);
      if (el.dispatchEvent && typeof Event !== 'undefined') el.dispatchEvent(new Event('change', {bubbles: true}));
    }
    /** Set the value to a record id and read the record for the line; a record that is gone is said, not skipped. */
    async function select(id) {
      const mine = ++sequence;
      value = id;
      chosen = null;
      draw();
      if (!id) return;
      try {
        const record = await get('/materials/' + id);
        if (mine === sequence && value === id) { chosen = record; draw(); }
      } catch (e) { if (mine === sequence && value === id) shown.textContent = `Stock #${id} is unavailable: ${e.message || e}`; }
    }

    function open() {
      const recent = h('div', {class: 'matpick-recent'});
      const grid = App.list({
        id: 'matpick', search: true, key: (m) => m.id, className: 'matpick-list',
        load: async ({sort, filters, search, offset, limit}) => {
          const q = {offset, limit, sort};
          if (search) q.search = search;
          for (const [k, v] of Object.entries(filters)) if (v) q[k] = v;
          const got = await page(q);
          return {items: got.items, total: got.total, counts: got.counts, options: got.options};
        },
        row: (m) => [h('strong', {class: 'lst-text', title: label(m)}, m.name), m.grade ? h('span', {class: 'pill', title: 'Grade or alloy'}, m.grade) : null,
          m.batch ? h('span', {class: 'small'}, `batch ${m.batch}`) : h('span', {class: 'muted small'}, 'batch not specified'),
          m.thickness_mm != null ? h('span', {class: 'small'}, `${+m.thickness_mm} mm`) : null],
        actions: (m) => [btn(String(m.id) === value ? 'Selected' : 'Choose', () => { set(m); dialog.close(); }, 'btn-small' + (String(m.id) === value ? ' primary' : ''))],
        filters: [{key: 'grade', label: 'Grade', select: true, options: (a) => (a.options || {}).grades || []}],
        sorts: SORTS, selected: () => value || null, selectedItem: (key) => get('/materials/' + key),
        empty: 'No stock records yet.', noResults: 'No stock records match this search.'});
      const settings = link('/setup?tab=material', 'Add or edit stock records');
      settings.addEventListener('click', () => dialog.close());      // the dialog is not part of the screen: it must not stay over the next one
      const dialog = modal(opts.title || 'Choose stock', h('div', {class: 'stack matpick-body'},
        h('p', {class: 'muted small'}, 'Choose a specific batch or sheet. A grade is a general designation; a work is linked to one stock record.'),
        recent, grid.el, h('p', {class: 'small'}, settings)),
      [{label: 'Close', run: (m) => m.close()}]);
      // the records used last: a short row of buttons above the catalogue
      page({limit: RECENT, sort: 'recent'}).then((got) => {
        const used = got.items.filter((m) => m.last_used_at);
        fill(recent, used.length ? [h('span', {class: 'small muted'}, 'Recently used: '),
          ...used.map((m) => btn(label(m), () => { set(m); dialog.close(); }, 'btn-small matpick-recent-item'))] : null);
      }).catch(() => { /* the catalogue below still works */ });
    }

    draw();
    el.ready = (async () => {
      if (value) { await select(value); return; }
      if (opts.initial === 'recent') {
        const mine = ++sequence;
        try {
          const first = (await page({limit: 1, sort: 'recent'})).items[0];
          if (mine === sequence && first && !value) { chosen = first; value = String(first.id); draw(); if (opts.onChange) opts.onChange(first); }
        } catch (_) { /* nothing is chosen until the person chooses */ }
      }
    })();
    return el;
  }

  /** How many stock records there are, asked without loading them (GET /materials?limit=1): a screen that only needs to know whether any record
      exists, or a record by its id (``one``), never reads the whole catalogue. */
  const total = async () => (await page({limit: 1})).total;
  const one = (id) => get('/materials/' + id);
  /** The record used last (or, when none was used yet, the newest), or null when there is none: the start of a screen that needs one record. */
  const lastUsed = async () => (await page({limit: 1, sort: 'recent'})).items[0] || null;

  return {create, label, total, one, lastUsed};
})();
