/* Start color engraving and choose replacement or questioned settings (REQ-004, REQ-042). The explicit ΔE threshold uses the selected laser and lens. */
'use strict';
const ArtworkParts = (() => {
  const {h, btn, link, get, patch, go, modal, num, labText, swatch} = App;
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 0)} kHz · ${num(p.speed, 0)} mm/s`;
  const seconds = (s) => (s == null ? 'time unavailable' : `${num(s, 1)} s/cm²`);
  // the reason of a doubt joins one message per broken threshold with '; ' (knowledge.refresh): each is translated
  const doubt = (reason) => reason.split('; ').map((part) => I18N.tr(part)).join('; ');

  function startForm(lists, ctx) {
    const begin = ctx.start || {device: ctx.query.device, lens: ctx.query.lens};         // the laser and lens the workshop chose last; the address wins (REQ-001)
    const pick = App.laserLensPicker(lists, {device: begin.device, lens: begin.lens});
    const img = h('input', {type: 'file', accept: 'image/*'});
    const name = h('input', {placeholder: 'Plan name'}), width = Forms.numberInput(Forms.QUANTITIES.workWidth, {value: 60});
    const thr = Forms.numberInput(Forms.QUANTITIES.deltaE, {placeholder: 'from rules'}), markers = h('input', {type: 'checkbox'});
    const maxTime = Forms.numberInput(Forms.QUANTITIES.maxTime, {placeholder: 'no limit'});
    // REQ-020: record the image or flat-color task in the plan and its photo measurements.
    const task = Tasks.chooser('color_image', {hint: 'color image is the default; choose Fill for flat color regions'});
    // every box says what it takes and, when it is wrong, why, beside itself with what was typed kept; a refusal of the server stands where the field it names is
    const f = Forms.create();
    const laserField = f.add('laser', 'Laser', pick.laser, {read: () => ({ok: true, value: pick.deviceId()})});
    const lensField = f.add('lens', 'Lens', pick.lens, {help: 'the palette uses measurements from this laser and lens', read: () => ({ok: true, value: pick.lensValue()})});
    const imageField = f.add('image', 'Image', App.filePick(img, 'Choose image'), {required: true,
      read: () => (img.files[0] ? {ok: true, value: img.files[0]} : {ok: false, message: 'Add an image for color engraving'})});
    const nameField = f.add('name', 'Plan name', name, {required: true});               // conversion.start_discrete: «give the plan a name»
    const widthField = f.add('width_mm', 'Work width', width, {quantity: 'workWidth', required: true});
    const thrField = f.add('threshold', 'ΔE threshold', thr, {quantity: 'deltaE', help: 'leave blank to use this laser and lens tolerance; set a threshold if no rule exists'});
    const timeField = f.add('max_time', 'Maximum engraving time', maxTime, {quantity: 'maxTime', help: 'leave blank for no limit; slower recipes are not selected automatically'});
    const submit = btn('Match colors', async (ev) => {
      const v = f.collect();
      if (!v) return;
      if (!task.check()) return f.fail(new Error('Task goals are invalid; correct the marked fields'));
      const fd = new FormData();
      fd.append('device_id', v.laser); fd.append('lens_id', v.lens); fd.append('name', v.name); fd.append('width_mm', v.width_mm);
      fd.append('markers', markers.checked); fd.append('image', v.image);
      if (v.threshold != null) fd.append('threshold', v.threshold);
      if (v.max_time != null) fd.append('max_time', v.max_time);
      task.append(fd);
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const p = await App.form('/discrete', fd);
        App.rememberContext({device: pick.deviceId(), lens: pick.lensId()});
        go('/artwork?plan=' + p.id);
      } catch (e) { f.fail(e); self.disabled = false; }
    }, 'primary');
    return h('div', {class: 'stack'}, h('div', {class: 'card empty'}, h('h3', {}, 'Add an image for color engraving')),
      h('div', {class: 'card stack'}, h('div', {class: 'grid g2'}, laserField, lensField, imageField, nameField, widthField, thrField, timeField), task.el,
        h('p', {class: 'muted small'}, 'The fastest estimated titanium color within the ΔE threshold is selected; a color is unreachable if none qualifies.'),
      h('label', {class: 'row'}, markers, h('span', {}, 'Registration markers and identifier outside the image')), f.error, submit));
  }

  function replaceDialog(plan, m, palette, reload) {
    let chosen = plan.replacements[m.source_key] || null;
    const rows = palette.map((e) => h('label', {class: 'row'}, h('input', {type: 'radio', name: 'rep', checked: e.id === chosen, onChange: () => { chosen = e.id; }}),
      swatch(e.lab), labText(e.lab), h('span', {class: 'muted small'}, `${params(e.parameters)} · ΔE ${num(e.expected_delta_e)} · confidence ${num(e.confidence)} · ${seconds(e.time_s_per_cm2)}`)));
    const none = [h('p', {class: 'alert warn'}, 'No validated or production colors for this laser and lens')];
    const place = Forms.notice({what: 'Color replacement', kept: 'The selection remains in the dialog; the color was not replaced.'});
    modal('Replace color', h('div', {class: 'stack'}, h('p', {}, 'Choose a color from the eligible palette (validated and production).'), ...(rows.length ? rows : none), place.error), [
      {label: 'Cancel', run: (x) => x.close()},
      {label: 'Apply replacement', cls: 'primary', run: async (x) => {
        place.clear();
        if (!chosen) return place.say('Choose a color from the list above to replace it.');
        try { await patch('/discrete/' + plan.id, {replacements: {...plan.replacements, [m.source_key]: chosen}}); } catch (e) { return place.fail(e); }
        x.close(); reload();
      }}]);
  }

  async function questionedDialog(plan, reload) {
    const all = (await get(`/palette?${App.hardwareQuery(plan.device_id, plan.lens_id)}&include_questioned=true`)).filter((e) => e.questioned);
    const picked = new Set(plan.allowed_questioned);
    const rows = all.map((e) => h('div', {class: 'alert warn'},
      h('label', {class: 'row'}, h('input', {type: 'checkbox', checked: picked.has(e.id), onChange: (ev) => { if (ev.target.checked) picked.add(e.id); else picked.delete(e.id); }}), swatch(e.lab), labText(e.lab)),
      h('p', {class: 'small'}, (e.doubt && doubt(e.doubt.reason)) || 'Questioned settings'), link('/knowledge/' + e.id, 'Observations')));
    const place = Forms.notice({what: 'Permission', kept: 'Selections remain in the dialog; the plan was not changed.'});
    modal('Include questioned settings in this plan', h('div', {class: 'stack'},
      h('p', {}, 'Permission applies only to this plan. The knowledge stage and flag do not change.'), ...(rows.length ? rows : [h('p', {}, 'No questioned production settings')]), place.error), [
      {label: 'Cancel', run: (x) => x.close()},
      {label: 'Apply to this plan', cls: 'primary', run: async (x) => {
        place.clear();
        try { await patch('/discrete/' + plan.id, {allowed_questioned: [...picked]}); } catch (e) { return place.fail(e); }
        x.close(); reload();
      }}]);
  }

  return {startForm, replaceDialog, questionedDialog, params, seconds};
})();
