/* The catalogue of titanium stock records: compact rows instead of a stack of forms (ux-growing-collections-p0, REQ-001, REQ-003, REQ-004).
   A line of the list is one concrete batch or sheet: name, grade (alloy), batch, thickness. The grade is what records of one titanium have
   in common and is a filter; the batch or sheet is the record. Adding and editing are separate forms: the editor opens only for the record
   chosen with “Edit” (or for the one the address names), above the list, so a search or a new page never takes the typed text away.
   The records are read from the server a page of twenty at a time (GET /materials?limit=20 with a search, a filter and an order), so a
   workshop with thousands of sheets draws twenty lines. The record being edited or just saved stays in view as the list's pinned line. */
'use strict';
const MaterialCatalog = (() => {
  const {h, fill, btn, get, post, put, toast} = App;
  const SORTS = [['recent', 'Recently used'], ['name', 'Name'], ['grade', 'Grade'], ['thickness', 'Thickness'], ['newest', 'Recently added']];
  const mm = (v) => `${+v} mm`;

  /** The words of a line: each part says what it is, so the grade and the batch are never taken for one another. */
  const parts = (m) => ({grade: m.grade || null, batch: m.batch || null, thickness: m.thickness_mm == null ? null : mm(m.thickness_mm)});
  const row = (m) => {
    const p = parts(m);
    const text = [m.name, p.grade, p.batch && `batch ${p.batch}`, p.thickness].filter(Boolean).join(' · ');
    return [h('strong', {class: 'lst-text', title: text}, m.name),
      p.grade ? h('span', {class: 'pill mat-grade', title: 'Grade or alloy'}, p.grade) : h('span', {class: 'muted small'}, 'grade not specified'),
      p.batch ? h('span', {class: 'small mat-batch', title: 'Specific batch or sheet'}, `batch ${p.batch}`) : h('span', {class: 'muted small'}, 'batch not specified'),
      p.thickness ? h('span', {class: 'small mat-thickness'}, p.thickness) : h('span', {class: 'muted small'}, 'thickness not specified'),
      m.family && m.family.toLowerCase() !== 'titanium' ? h('span', {class: 'pill'}, m.family) : null];
  };

  /** The six fields of a record; ``m`` is the record being edited or nothing (a new one). ``collect()`` reads them strictly (null, with every bad
      box marked, when one is wrong); ``form.fail`` puts a refusal of the server beside them (ux-save-feedback-p0, REQ-003). */
  function fields(m = {}) {
    const form = Forms.create();
    const grid = h('div', {class: 'grid g2'},
      form.add('name', 'Name', h('input', {value: m.name || '', placeholder: 'For example, Grade 2 · sheet A'}), {required: true}),
      form.add('family', 'Material', h('input', {value: m.family || 'Titanium', placeholder: 'Titanium, Steel, Brass…'}), {required: true}),
      form.add('grade', 'Grade / alloy', h('input', {value: m.grade || '', placeholder: 'Grade 2, Ti-6Al-4V…'})),
      form.add('batch', 'Batch or sheet', h('input', {value: m.batch || '', placeholder: 'batch or sheet number'})),
      form.add('thickness_mm', 'Thickness', Forms.numberInput(Forms.QUANTITIES.thickness, {value: m.thickness_mm ?? '', placeholder: 'mm'}), {quantity: 'thickness'}),
      form.add('surface', 'Surface / preparation', h('input', {value: m.surface || '', placeholder: 'sanding, polishing…'})));
    return {first: form.entries[0].input, grid, form, collect: form.collect};
  }

  /** A button that saves once: a second click while the request is on its way does nothing; a refusal stays under the boxes. */
  function saveButton(label, run, form) {
    let saving = false;
    const b = btn(label, async () => {
      if (saving) return;
      saving = true; b.disabled = true;
      try { await run(); } catch (e) { form.fail(e); } finally { saving = false; b.disabled = false; }
    }, 'primary');
    return b;
  }

  /** The form that adds a record. */
  function addForm({saved, cancel}) {
    const f = fields();
    return {first: f.first, el: h('div', {class: 'card stack mat-editor', role: 'group', 'aria-label': 'Add material'}, h('strong', {}, 'Add material'), f.grid, f.form.error,
      h('div', {class: 'row'}, saveButton('Add material', async () => {
        const body = f.collect();
        if (!body) return;
        const made = await post('/materials', body); toast('Material saved', 'ok'); saved(made);
      }, f.form), btn('Cancel', cancel)))};
  }

  /** The form that changes the record ``m``. */
  function editForm(m, {saved, cancel}) {
    const f = fields(m);
    return {first: f.first, el: h('div', {class: 'card stack mat-editor', role: 'group', 'aria-label': `Material #${m.id}`}, h('strong', {}, `Material #${m.id}`), f.grid, f.form.error,
      h('div', {class: 'row'}, saveButton('Save material', async () => {
        const body = f.collect();
        if (!body) return;
        const made = await put('/materials/' + m.id, body); toast('Material saved', 'ok'); saved(made);
      }, f.form), btn('Close', cancel)))};
  }

  /** The catalogue as a tab body. ``query``: the address (``material`` — the record open for editing, kept in the address). */
  function catalog(query = {}) {
    const cur = {material: query.material || '', search: query.search || '', grade: query.grade || '', family: query.family || '', sort: query.sort || ''};
    const keep = (change) => {
      Object.assign(cur, change);
      const q = new URLSearchParams([['tab', 'material'], ...Object.entries(cur).filter(([, v]) => v)]);
      if (typeof history !== 'undefined' && history.replaceState) history.replaceState(null, '', '#/setup?' + q);
    };
    const editor = h('div', {class: 'mat-editor-box'});
    let lst = null;
    let opened = null;                                         // 'add', 'edit' or null: which form is open
    const addButton = btn('Add material', () => showAdd(), 'primary');

    const rowButton = (id) => {
      const line = [...lst.el.querySelectorAll('.lst-row')].find((r) => r.getAttribute('data-key') === String(id));
      const actions = line && line.querySelector('.lst-act');
      return (actions && actions.querySelector('button')) || addButton;
    };
    /** Close the open form, forget the selection and give the focus back to the button that opened it. */
    const close = (backTo) => {
      const id = cur.material;
      opened = null;
      keep({material: ''});
      fill(editor, null);
      lst.refresh().then(() => { const target = backTo === 'row' ? rowButton(id) : addButton; if (target && target.focus) target.focus(); });
    };
    function showAdd() {
      keep({material: ''});
      opened = 'add';
      const form = addForm({saved: (made) => showEdit(made.id), cancel: () => close('add')});
      fill(editor, form.el);
      lst.refresh();
      form.first.focus();
    }
    /** Open the editor for the record ``id``. ``redraw`` false: the list is drawing itself anyway (the first draw names the record as the selected one). */
    async function showEdit(id, redraw = true) {
      keep({material: String(id)});
      opened = 'edit';
      let record;
      try { record = await get('/materials/' + id); }
      catch (e) {                                              // a record the address names that is not there: said, not silently skipped
        fill(editor, h('div', {class: 'alert bad', role: 'alert'}, `Material #${id} is unavailable: ${e.message || e}. `, btn('Close', () => close('add'), 'btn-small')));
        if (redraw) lst.refresh();
        return;
      }
      if (opened !== 'edit' || cur.material !== String(id)) return;      // another record was chosen while this one was read
      const form = editForm(record, {saved: () => lst.refresh(), cancel: () => close('row')});
      fill(editor, form.el);
      if (redraw) lst.refresh();
      if (redraw) form.first.focus();
    }

    lst = App.list({
      id: 'setup.materials', search: true, key: (m) => m.id, className: 'mat-list',
      load: async ({sort, filters, search, offset, limit}) => {
        const q = new URLSearchParams({offset, limit, sort});
        if (search) q.set('search', search);
        for (const [k, v] of Object.entries(filters)) if (v) q.set(k, v);
        const page = await get('/materials?' + q);
        return {items: page.items, total: page.total, counts: page.counts, options: page.options};
      },
      row, actions: (m) => [btn('Edit', () => showEdit(m.id), 'btn-small')],
      filters: [{key: 'family', label: 'Material', select: true, options: (a) => (a.options || {}).families || []},
        {key: 'grade', label: 'Grade', select: true, options: (a) => (a.options || {}).grades || []}],
      sorts: SORTS, initial: {sort: cur.sort || undefined, search: cur.search, filters: {family: cur.family, grade: cur.grade}},
      selected: () => cur.material || null, selectedItem: (key) => get('/materials/' + key),
      clearSelection: () => close('add'),
      empty: 'No materials yet. Add the first stock record.', noResults: 'No stock records match the search and filters.',
      onChange: (s) => keep({search: s.search, sort: s.sort === SORTS[0][0] ? '' : s.sort, grade: s.filters.grade, family: s.filters.family})});

    const opening = cur.material ? showEdit(cur.material, false) : Promise.resolve();
    const root = h('div', {class: 'stack mat'}, h('div', {class: 'alert'},
      'Add a separate record for each batch or sheet. When uploading a result, select the stock that was engraved. '
      + 'Other materials need their own cleaning recipe; titanium cleaning does not apply to them.'),
    h('div', {class: 'row'}, h('p', {class: 'muted small'}, 'A grade (alloy) can cover multiple batches; each batch or sheet has its own record.'), h('span', {class: 'spacer'}), addButton),
    editor, lst.el);
    return {el: root, list: lst, ready: Promise.all([lst.ready, opening])};
  }

  /** The “Stock” tab of the settings screen. */
  async function tab(ctx) {
    const made = catalog(ctx.query);
    await made.ready;
    return made.el;
  }

  return {tab, catalog, row, SORTS};
})();
