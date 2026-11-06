/* Capture setup forms. Titanium stock is managed in material-catalog.js. */
'use strict';
const SetupForms = (() => {
  const {h, btn, post, put, del, toast, fail, confirmBox} = App;

  /** Reference chart values default to published values; custom Lab values can be saved or reset (DEC-025). */
  function chartReference(r, reload) {
    const ref = r.chart_reference;
    const white = h('select', {'aria-label': 'White point'}, ['D65', 'D50'].map((w) => h('option', {value: w}, w)));
    white.value = ref.white_point;
    const source = h('input', {value: ref.source || '', placeholder: 'e.g. X-Rite ColorChecker Classic after 2014, D50'});
    const form = Forms.create();
    const cells = Array.from({length: 24}, (_, i) => ['L', 'a', 'b'].map((component, j) => {
      const input = h('input', {type: 'text', inputmode: 'decimal', value: String((ref.patches_lab[i] || [])[j] ?? '')});
      const rule = component === 'L' ? {min: 0, max: 100} : {min: -128, max: 127};
      const field = form.add(`patch_${i}_${j}`, `Patch ${i + 1} ${component}`, input, {required: true, quantity: rule});
      return {input, field};
    }));
    const grid = h('div', {class: 'reference-grid', 'aria-label': 'Reference patches'}, cells.map((row, i) =>
      h('div', {class: 'reference-patch'}, h('strong', {}, `Patch ${i + 1} · row ${Math.floor(i / 6) + 1}, column ${i % 6 + 1}`), row.map((cell) => cell.field))));
    const raw = h('textarea', {rows: '5', 'aria-label': 'Raw reference numbers'});
    const exchangeError = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const exchange = h('details', {}, h('summary', {}, 'Import or export raw numbers (JSON)'),
      h('p', {class: 'small'}, '24 triples in patch order, each [L, a, b]. Import replaces the grid only; save to apply.'), raw, exchangeError,
      h('div', {class: 'row'}, btn('Load numbers into grid', () => {
        let list;
        try { list = JSON.parse(raw.value); } catch (_) { list = null; }
        if (!Array.isArray(list) || list.length !== 24 || list.some((t) => !Array.isArray(t) || t.length !== 3 || t.some((n) => typeof n !== 'number' || !Number.isFinite(n)))) {
          exchangeError.textContent = 'Enter exactly 24 [L, a, b] numeric triples. The grid is unchanged.'; exchangeError.hidden = false; return;
        }
        cells.forEach((row, i) => row.forEach((cell, j) => { cell.input.value = String(list[i][j]); cell.field.clearError(); }));
        exchangeError.hidden = true; exchangeError.textContent = '';
      }), btn('Copy grid to raw numbers', () => {
        const list = cells.map((row) => row.map(({input}) => Forms.parse(input.value, {}, {required: true})));
        if (list.some((row) => row.some((v) => !v.ok))) { exchangeError.textContent = 'Complete every grid field with a number before exporting.'; exchangeError.hidden = false; return; }
        raw.value = JSON.stringify(list.map((row) => row.map((v) => v.value)), null, 2); exchangeError.hidden = true; exchangeError.textContent = '';
      })));
    const whiteField = form.add('white_point', 'Reference white point', white, {required: true, read: () => ({ok: true, value: white.value})});
    const sourceField = form.add('source', 'Source of values', source, {required: true});
    const save = btn('Save reference values', async () => {
      const v = form.collect();
      if (!v) return;
      try {
        await put(`/setups/${r.id}/chart-reference`, {patches_lab: cells.map((row, i) => row.map((_, j) => v[`patch_${i}_${j}`])), white_point: v.white_point, observer: '2°', source: v.source});
        toast('Reference values saved', 'ok'); reload('rigs');
      } catch (e) { form.fail(e); }
    });
    const reset = ref.published ? null : btn('Restore published values', async () => {
      try { await del(`/setups/${r.id}/chart-reference`); toast('Published values restored', 'ok'); reload('rigs'); } catch (e) { fail(e); }
    });
    return h('details', {}, h('summary', {}, `Chart reference values: ${ref.published ? 'published' : 'custom'} · ${ref.white_point} / ${ref.observer}`),
      h('p', {class: 'muted small'}, 'Source: ' + (ref.published ? 'published ColorChecker Classic values (sRGB, D65), converted to CIELAB D65 / 2°' : ref.source)
        + '. Photos from this setup are corrected using these values; accepted measurements do not change.'),
      h('p', {class: 'small'}, 'Patch order is left to right, top to bottom (four rows of six); edit L, a, b in each patch.'),
      grid, exchange,
      h('div', {class: 'grid g2'}, whiteField, sourceField),
      form.error,
      h('div', {class: 'row'}, save, reset));
  }

  /** Capture setups record camera, lighting, angle and reference chart with each photo (DEC-066). */
  function rigsTab(items, reload) {
    const editor = (r = {}) => {
      const f = {name: h('input', {value: r.name || '', placeholder: 'For example, window table · tripod'}),
        camera: h('input', {value: r.camera || '', placeholder: 'camera and lens'}),
        lighting: h('input', {value: r.lighting || '', placeholder: 'e.g. LED 5600 K, two lights'}),
        angle: h('input', {value: r.angle || '', placeholder: 'e.g. 90°'}),
        chart: h('input', {value: r.reference_chart || 'ColorChecker Classic', placeholder: 'reference chart'})};
      // setup.save_capture_setup: every one of the five is required; a refusal is said beside the box it names or above the buttons
      const form = Forms.create();
      const fields = [['name', 'Name', f.name], ['camera', 'Camera', f.camera], ['lighting', 'Lighting', f.lighting], ['angle', 'Capture angle', f.angle],
        ['reference_chart', 'Reference chart', f.chart]].map(([name, label, input]) => form.add(name, label, input, {required: true}));
      const save = btn(r.id ? 'Save setup' : 'Add setup', async () => {
        const body = form.collect();
        if (!body) return;
        try { if (r.id) await put('/setups/' + r.id, body); else await post('/setups', body); toast('Capture setup saved', 'ok'); reload('rigs'); }
        catch (e) { form.fail(e); }
      }, 'primary');
      const remove = r.id ? btn('Delete', () => confirmBox('Delete setup', `“${I18N.name(r.name)}”. A setup used by saved photographs cannot be deleted.`, 'Delete',
        async () => { await del('/setups/' + r.id); toast('Setup deleted', 'ok'); reload('rigs'); }), 'danger') : null;
      return h('div', {class: 'card stack'}, h('strong', {}, r.id ? `Setup #${r.id}${r.last_used ? ' · used last time' : ''}` : 'Add setup'),
        r.legacy ? h('div', {class: 'alert warn'}, 'Placeholder for pairs uploaded before each photograph had a capture setup. New photographs cannot use it.') : null,
        h('div', {class: 'grid g2'}, ...fields),
        r.id ? chartReference(r, reload) : null,
        form.error,
        h('div', {class: 'row'}, save, remove));
    };
    return h('div', {class: 'stack'}, h('div', {class: 'alert'}, 'A capture setup describes the camera, lighting, angle and reference chart used for each experiment photograph; '
      + 'the previous photograph’s setup is selected by default when uploading.'),
      ...items.map((r) => editor(r)), editor());
  }

  return {rigsTab};
})();
