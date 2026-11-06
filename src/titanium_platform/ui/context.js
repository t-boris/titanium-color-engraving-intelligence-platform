/* Shared starting context for new work and tests (ux-work-creation-p0, REQ-001). Existing work keeps its own recorded setup. */
'use strict';
const WorkContext = (() => {
  const {h, fill, btn, get, put, post, modal} = App;

  // Counts provided by the server for each result (creation_context.RESULTS).
  const COUNTED = {photo: 'Measured grey scales (photo engraving)', colour: 'Measured fill colors (color regions)',
    silhouette: 'Verified fill recipes (silhouette)', lines: 'Verified line recipes (lines)'};
  const WARNING = {
    none_left: (w) => `${COUNTED[w.result]}: ${w.now} available before; none for the selected setup.`,
    fewer: (w) => `${COUNTED[w.result]}: ${w.now} available before; ${w.after} for the selected setup.`,
    lens_unknown: () => 'The lens is unknown. Knowledge from different lenses is kept separate, so measurements from other lenses will not be included.',
    lens_not_installed: () => 'This lens is not currently installed on the selected laser.',
    titanium_differs: () => 'The titanium grade is different. Recipes and colors measured on the previous grade do not apply to this one.',
    source_unavailable: (w) => `The selected source is currently unavailable: ${I18N.tr(w.detail)}`,
    source_dropped: () => 'Colors and scales will use this workshop’s measurements instead of the laboratory release.',
  };
  const warningText = (w) => (WARNING[w.code] ? WARNING[w.code](w) : w.code);

  const stockName = (m) => (m ? [m.name, m.grade, m.batch && `batch ${m.batch}`].filter(Boolean).join(' · ') : 'Not selected');
  const laserName = (d) => (d ? d.title || d.name : 'Not selected');
  const lensName = (lens, basis) => (lens ? App.lensLabel(lens) + (basis === 'installed' ? ' (installed on laser)' : '') : 'Unknown');
  const sourceName = (s) => (s ? s.label || 'Connected laboratory release' : 'This workshop’s measurements');

  /** A definition-list entry keeps its label and value together for screen readers. */
  const row = (name, value) => [h('dt', {}, name), h('dd', {}, value)];

  /** Summarize the selected laser, lens, stock and measurements. */
  function summary(context) {
    return h('dl', {class: 'work-context-list'}, row('Laser', laserName(context.device)), row('Lens', lensName(context.lens, context.lens_basis)),
      row('Stock', stockName(context.material)), row('Measurements', sourceName(context.source)));
  }

  /** Explain which selected records were removed and replaced. */
  function staleNote(context) {
    const names = {device: 'laser', lens: 'lens', material: 'stock', capture_setup: 'capture setup'};
    const lost = (context.stale || []).map((k) => names[k]).filter(Boolean);
    return lost.length ? h('p', {class: 'alert warn small', role: 'status'}, `The previous selection is no longer available (${lost.join(', ')}); the current selection is shown.`) : null;
  }

  /** Show the impact of a change before saving it. When source is false, preserve the existing source. */
  async function change(context, done, {source: withSource = true} = {}) {
    const [devices, lenses] = await Promise.all([get('/devices'), get('/lenses')]);
    const pick = App.laserLensPicker({devices, lenses}, {device: context.device_id, lens: context.lens_id == null ? 'unknown' : context.lens_id,
      defaultLens: 'installed', onChange: () => ask()});
    // one concrete record, chosen by a search among the records used last and not from a list of all (ux-growing-collections-p0, REQ-001); with no
    // shared choice yet it starts with the record used last
    const stock = MaterialPicker.create({value: context.material_id, initial: 'recent', name: 'Stock', onChange: () => ask()});
    const source = withSource ? LabSource.picker('vector', {onChange: () => ask()}) : null;
    const impact = h('div', {class: 'stack', role: 'status', 'aria-live': 'polite'});
    let asked = 0;
    const wanted = () => ({device_id: pick.deviceId(), lens_id: pick.lensId(), material_id: stock.value === '' ? null : +stock.value, source: sourceValue()});
    const sourceValue = () => {
      if (!withSource) return context.source || null;
      const value = source.value();
      if (!value) return null;
      const option = [...source.select.options].find((o) => o.value === source.select.value);
      return {...value, label: option ? option.textContent : null};
    };
    async function ask() {
      const mine = ++asked;
      const body = wanted();
      let report;
      try { report = await post('/creation/context/impact', body); }
      catch (e) { if (mine === asked) fill(impact, h('p', {class: 'alert bad', role: 'alert'}, e.message)); return; }
      if (mine !== asked) return;                                         // another choice was made meanwhile: that answer is for the choice before it
      fill(impact, !report.changed ? h('p', {class: 'muted small'}, 'The selection matches the current setup.')
        : report.warnings.length ? [h('p', {class: 'small'}, h('strong', {}, 'Changes for new work and tests')),
          h('ul', {class: 'small'}, report.warnings.map((w) => h('li', {class: 'alert warn'}, warningText(w)))),
          h('p', {class: 'muted small'}, 'These warnings do not prevent the change. Existing work keeps its recorded settings.')]
          : h('p', {class: 'small'}, 'Everything available for the previous setup is available for this selection. Existing work is unchanged.'));
    }
    const dialog = modal('New work context', h('div', {class: 'stack'},
      h('p', {class: 'small muted'}, 'New work and tests start with this selection. Existing work keeps its recorded setup.'),
      h('div', {class: 'grid g2'}, App.field('Laser', pick.laser), App.field('Lens', pick.lens, 'knowledge from different lasers and lenses is kept separate'),
        App.field('Stock', stock), withSource ? source.el : null), impact), [
      {label: 'Cancel', run: (m) => m.close()},
      {label: 'Apply', cls: 'primary', run: async (m) => {
        const saved = await put('/creation/context', wanted());
        m.close();
        if (done) done(saved);
      }}]);
    if (withSource) source.loaded.then(() => { selectSource(source, context.source); return ask(); }); else ask();
    return dialog;
  }

  /** Select the matching release after the source options load. */
  function selectSource(picker, wanted) {
    if (!wanted) return;
    const key = (v) => (v ? JSON.stringify([v.release_id, v.laser, v.lens ?? null, v.material ?? null]) : null);
    for (let i = 1; i < picker.select.options.length; i++) {
      picker.select.value = String(i);
      if (key(picker.value()) === key(wanted)) return;
    }
    picker.select.value = '';
  }

  /** Show the shared starting context and allow a confirmed change. */
  function strip(initial, {onChange = null, heading = 'Starts with', source = true} = {}) {
    let current = initial, changeButton = null, opening = false;
    const body = h('div', {class: 'stack'});
    const el = h('section', {class: 'card work-context', 'aria-label': 'New work context'}, body);
    const focus = () => { if (changeButton && changeButton.focus) changeButton.focus(); };
    const open = () => {
      if (opening) return;                                 // the button stays enabled and focused (the dialog gives the focus back to it): a second click is ignored
      opening = true;
      change(current, (saved) => { current = saved; draw(); if (onChange) onChange(saved); focus(); }, {source}).catch(App.fail).finally(() => { opening = false; });
    };
    const draw = () => {
      changeButton = btn('Change…', open, 'btn-small');
      fill(body, h('div', {class: 'row'}, h('strong', {}, heading), h('span', {class: 'spacer'}), changeButton), summary(current), staleNote(current),
        h('p', {class: 'small muted'}, 'Shared selection: new work and tests start here. Existing work keeps its recorded setup.'));
    };
    draw();
    return {el, focus, context: () => current, update: (context) => { current = context; draw(); }};
  }

  /** Show the settings recorded with an existing work; the shared context cannot change them. */
  function own({device, lens, material, source, heading = 'This work’s settings'}) {
    return h('section', {class: 'work-context work-context-own', 'aria-label': heading},
      h('div', {class: 'row'}, h('strong', {}, heading)),
      summary({device, lens, lens_basis: null, material, source: source && source.kind === 'release' ? {label: `${source.lab_name}, ${LabSource.releaseName(source)}`} : null}),
      h('p', {class: 'small muted'}, 'Recorded with this work. The shared selection for new work does not change it.'));
  }

  return {summary, strip, change, own, warningText, selectSource, COUNTED, stockName, laserName, lensName, sourceName};
})();
