/* Capture setup forms. Titanium stock is managed in material-catalog.js. */
'use strict';
const SetupForms = (() => {
  const {h, btn, post, put, del, toast, fail, confirmBox} = App;

  /** Reference chart values default to published values; custom Lab values can be saved or reset (DEC-025). */
  function chartReference(r, reload) {
    const ref = r.chart_reference;
    const values = h('textarea', {rows: '5', 'aria-label': 'Reference Lab values'}, JSON.stringify(ref.patches_lab));
    const white = h('select', {'aria-label': 'White point'}, ['D65', 'D50'].map((w) => h('option', {value: w}, w)));
    white.value = ref.white_point;
    const source = h('input', {value: ref.published ? '' : ref.source, placeholder: 'e.g. X-Rite ColorChecker Classic after 2014, D50'});
    // the rules of setup.save_chart_reference: 24 triples (L 0 to 100, a and b -128 to 127), a source; a wrong text stays as typed with the reason beside it
    const form = Forms.create();
    const triples = form.add('patches_lab', 'Reference Lab values', values, {required: true, help: '24 [L, a, b] triples: L from 0 to 100, a and b from -128 to 127',
      read: () => {
        let list;
        try { list = JSON.parse(values.value); } catch (_) { return {ok: false, message: 'Enter 24 [L, a, b] triples as in [[37.5, 12, 14], ...]'}; }
        if (!Array.isArray(list) || list.length !== 24 || list.some((t) => !Array.isArray(t) || t.length !== 3 || t.some((n) => typeof n !== 'number' || !Number.isFinite(n)))) {
          return {ok: false, message: `Exactly 24 [L, a, b] triples are required. Current: ${Array.isArray(list) ? list.length : 'not a list'}`};
        }
        const at = list.findIndex(([L, a, b]) => L < 0 || L > 100 || a < -128 || a > 127 || b < -128 || b > 127);
        return at >= 0 ? {ok: false, message: `Triple ${at + 1}: L must be 0–100 and a and b must be -128–127. Entered: [${list[at].join(', ')}]`} : {ok: true, value: list};
      }});
    const whiteField = form.add('white_point', 'Reference white point', white, {required: true, read: () => ({ok: true, value: white.value})});
    const sourceField = form.add('source', 'Source of values', source, {required: true});
    const save = btn('Save reference values', async () => {
      const v = form.collect();
      if (!v) return;
      try {
        await put(`/setups/${r.id}/chart-reference`, {patches_lab: v.patches_lab, white_point: v.white_point, observer: '2°', source: v.source});
        toast('Reference values saved', 'ok'); reload('rigs');
      } catch (e) { form.fail(e); }
    });
    const reset = ref.published ? null : btn('Restore published values', async () => {
      try { await del(`/setups/${r.id}/chart-reference`); toast('Published values restored', 'ok'); reload('rigs'); } catch (e) { fail(e); }
    });
    return h('details', {}, h('summary', {}, `Chart reference values: ${ref.published ? 'published' : 'custom'} · ${ref.white_point} / ${ref.observer}`),
      h('p', {class: 'muted small'}, 'Source: ' + (ref.published ? 'published ColorChecker Classic values (sRGB, D65), converted to CIELAB D65 / 2°' : ref.source)
        + '. Photos from this setup are corrected using these values; accepted measurements do not change.'),
      triples,
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
