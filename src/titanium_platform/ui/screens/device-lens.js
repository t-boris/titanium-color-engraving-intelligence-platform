/* Lens selection and measured spot data. Spot measurements belong to the lens; M² belongs to the laser (REQ-019). */
'use strict';
const DeviceLens = (() => {
  const {h, btn, pill, get, post, put, patch, del, toast, fail, confirmBox, modal, table, facts} = App;
  const g = (v, d = 4) => (v == null ? '—' : String(+(+v).toPrecision(d)));
  const SOURCE = {lens: 'from lens', 'lens and laser settings': 'smaller of lens field and laser settings', 'Field Size': 'from settings: Field Size', 'Size Width / Size Height': 'from settings: work area size'};

  /** M² belongs to the laser; measured spot size belongs to its lens. */
  function spotForm(d, refresh) {
    const p = d.passport, lens = d.lens;
    const f = Forms.create();
    const Q = Forms.QUANTITIES;
    const m2 = f.add('m2', 'Your laser’s M²', Forms.numberInput(Q.m2, {value: p.m2 ?? '', placeholder: 'e.g. 1.3'}),
      {quantity: 'm2', help: 'beam quality from the test report or manufacturer; without it only spot-size bounds are known'});
    const spot = f.add('spot', `Or spot diameter measured with lens “${lens.name}”`, Forms.numberInput(Q.spot, {value: lens.spot_diameter_um ?? '', placeholder: 'µm'}),
      {quantity: 'spot', help: 'if measured, takes precedence over the calculation and stays with this lens'});
    return h('div', {class: 'stack'}, h('div', {class: 'grid g2'}, m2, spot), f.error,
    btn('Save', async () => {
      const v = f.collect();
      if (!v) return;
      try {
        if (v.m2 !== (p.m2 ?? null)) await patch('/devices/' + d.id, {passport: {...p, m2: v.m2}});
        if (v.spot !== (lens.spot_diameter_um ?? null)) await patch('/lenses/' + lens.id, {spot_diameter_um: v.spot});
        toast('Saved', 'ok'); refresh(d.id);
      } catch (e) { f.fail(e); }
    }, 'primary'));
  }

  function summary(d, refresh) {
    const c = d.characterization, spot = c.items.find((i) => i.key === 'spot_diameter'), lens = d.lens;
    if (!lens) {
      return h('div', {class: 'alert warn'}, 'No lens is installed, so its spot and work field cannot be calculated. Select or create a lens below.');
    }
    const range = spot.low ? `${g(spot.low, 3)}${spot.high ? '–' + g(spot.high, 3) : '+'} µm (bounds, not used in calculations)` : null;
    const wf = c.work_field_mm;
    return h('div', {class: 'stack'}, facts([['Installed', App.lensLabel(lens) + (lens.expansion !== 1 ? ` · expander ×${lens.expansion}` : '')],
      ['Spot diameter', spot.value != null ? `${g(spot.value, 3)} µm (${spot.basis === 'measured' ? 'measured by you' : 'calculated'})` : (range || 'unknown')],
      ['Work field', wf ? `${g(wf.width)} × ${g(wf.height)} mm (${SOURCE[wf.source] || wf.source})` : 'unknown']]),
    spot.waiting_for.includes('m2') ? h('div', {class: 'alert warn'}, `Lens included: focal length ${g(lens.focal_length_mm)} mm, beam diameter at lens ${g(d.passport.beam_diameter_mm)} mm. Only M² (beam quality) is missing for spot diameter.`
      + (d.passport.m2_max ? ` The manual’s maximum ${g(d.passport.m2_max)} is a limit, not this laser’s measured value, so it is not used.` : '') + ' Enter M² or a measured spot below.') : null,
    spot.waiting_for.includes('focal_length') ? h('div', {class: 'alert warn'}, 'This lens has no focal length: spot diameter, fluence and pulse overlap cannot be calculated. '
      + 'Other operating-point calculations remain available. Enter focal length below or enter a measured spot.') : null,
    spotForm(d, refresh),                                    // Keep the measurement editable here.
    wf && wf.settings_exceeds_lens ? h('div', {class: 'alert warn'}, 'The field in laser settings exceeds the lens field; the plate is limited to the lens field.') : null);
  }

  /** Lens row: install, edit or delete. */
  function lensRow(d, l, refresh) {
    const here = d.lens && d.lens.id === l.id, elsewhere = l.installed_on && !here;
    const set = btn(here ? 'Remove' : 'Install', async () => {
      try { await put(`/devices/${d.id}/lens`, {lens_id: here ? null : l.id}); toast(here ? 'Lens removed' : 'Lens installed', 'ok'); refresh(d.id); } catch (e) { fail(e); }
    }, here ? '' : 'primary', !!elsewhere);
    const remove = btn('Delete', () => confirmBox('Delete lens', `“${l.name}”. An installed lens or one with plates or measurements cannot be deleted.`, 'Delete',
      async () => { await del('/lenses/' + l.id); toast('Lens deleted', 'ok'); refresh(d.id); }), 'danger', here);
    const focal = l.focal_length_mm == null ? btn('Enter focal length', () => focalDialog(d, l, refresh), 'btn-small') : `${g(l.focal_length_mm)} mm`;
    return [h('div', {}, h('strong', {}, l.name), l.note ? h('div', {class: 'small muted'}, l.note) : null), focal, l.field_mm ? `${g(l.field_mm)} mm` : '—',
      l.expansion === 1 ? '—' : '×' + l.expansion, l.spot_diameter_um != null ? `${g(l.spot_diameter_um, 3)} µm` : 'not measured',
      here ? pill('installed', 'ok') : elsewhere ? pill('on “' + l.installed_on.name + '”', 'warn') : '', h('span', {class: 'row'}, set, remove)];
  }

  /** Add a missing focal length without changing lens identity. */
  function focalDialog(d, l, refresh) {
    const f = Forms.create();
    const focal = f.add('focal', 'Focal length', Forms.numberInput(Forms.QUANTITIES.focal), {quantity: 'focal', required: true});
    modal('Lens focal length', h('div', {class: 'stack'}, h('p', {}, `“${l.name}”: enter the value from the lens mount or documentation.`), focal, f.error), [
      {label: 'Cancel', run: (m) => m.close()},
      {label: 'Save', cls: 'primary', run: async (m) => {
        const v = f.collect();
        if (!v) return;                                  // the dialog stays open with the reason beside the box
        try { await patch('/lenses/' + l.id, {focal_length_mm: v.focal}); } catch (e) { f.fail(e); return; }
        m.close(); toast('Focal length saved', 'ok'); refresh(d.id);
      }}]);
  }

  function form(d, refresh) {
    const f = Forms.create();
    const Q = Forms.QUANTITIES;
    const number = (q, attrs) => Forms.numberInput(q, attrs);
    return h('div', {class: 'stack'}, h('div', {class: 'grid g3'},
      f.add('name', 'Name', h('input', {placeholder: 'e.g. F-theta 254'}), {required: true}),
      f.add('focal', 'Focal length', number(Q.focal, {placeholder: 'mm'}), {quantity: 'focal', help: 'engraved on the mount as F=…; leave blank if unknown'}),
      f.add('fieldMm', 'Lens field', number(Q.lensField, {placeholder: 'mm, e.g. 175'}), {quantity: 'lensField', help: 'square side length, e.g. 110, 150, 175'}),
      f.add('exp', 'Beam expander', number(Q.expansion, {value: 1}), {quantity: 'expansion', help: '1 without an expander; ×2 halves the spot'}),
      f.add('note', 'Note', h('input', {placeholder: 'optional'}), {})), f.error,
    btn('Add and install', async () => {
      const v = f.collect();
      if (!v) return;
      try {
        const lens = await post('/lenses', {name: v.name, focal_length_mm: v.focal, field_mm: v.fieldMm, expansion: v.exp ?? 1, note: v.note});
        await put(`/devices/${d.id}/lens`, {lens_id: lens.id}); toast('Lens added and installed', 'ok'); refresh(d.id);
      } catch (e) { f.fail(e); }
    }, 'primary'));
  }

  async function card(d, refresh) {
    const all = await get('/lenses');
    return h('div', {class: 'stack'}, h('div', {class: 'card stack'}, h('h3', {}, 'Lens on this laser'),
      h('p', {class: 'muted small'}, 'The lens determines spot size and work field. Install a replacement here; new plates record it and old plates retain their original lens.'), summary(d, refresh)),
    h('div', {class: 'card stack'}, h('h3', {}, 'My lenses'),
      table(['Lens', 'Focal length', 'Field', 'Expander', 'Measured spot', 'Status', ''], all.map((l) => lensRow(d, l, refresh)), 'No lenses yet; add one below', true)),
    h('div', {class: 'card stack'}, h('h3', {}, 'New lens'), form(d, refresh)));
  }
  return {card};
})();
