/* Laser forms for creation, specification editing and document upload (REQ-017). */
'use strict';
const DeviceForms = (() => {
  const {h, btn, get, post, patch, form, toast} = App;
  const KINDS = [['test_report', 'Test report'], ['cutoff_table', 'Cutoff frequency table'], ['waveform', 'Pulse waveforms'],
    ['controller_config', 'Controller settings'], ['packing_list', 'Packing list'], ['manual', 'Manual'], ['other', 'Other']];
  const KIND = Object.fromEntries(KINDS);

  /** One “20 252” step per line; CW or blank means no cutoff. Invalid lines are reported with their number (ux-save-feedback-p0, REQ-003). */
  function readSteps(area) {
    return () => {
      const steps = [];
      const lines = area.value.split('\n');
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        const [w, c] = line.split(/[\s;:,]+/);
        const width = Forms.parse(w, Forms.QUANTITIES.pulseWidth, {required: true});
        if (!width.ok) return {ok: false, message: `Line ${i + 1}: pulse duration. ${width.message}`};
        let cutoff = null;
        // Accept the legacy spelling as well as English when reading existing step lists.
        if (c != null && !/^(cw|none|\u043d\u0435\u0442|—|-)$/i.test(c)) {
          const parsed = Forms.parse(c, Forms.QUANTITIES.cutoff, {required: true});
          if (!parsed.ok) return {ok: false, message: `Line ${i + 1}: cutoff frequency. ${parsed.message}`};
          cutoff = parsed.value;
        }
        steps.push({pulse_width_ns: width.value, cutoff_khz: cutoff});
      }
      return steps.length ? {ok: true, value: steps} : {ok: false, message: 'Enter at least one step: pulse duration in ns and cutoff frequency in kHz (or CW)'};
    };
  }
  const stepsText = (steps) => steps.map((s) => `${s.pulse_width_ns} ${s.cutoff_khz == null ? 'CW' : s.cutoff_khz}`).join('\n');
  const area = (value, rows) => h('textarea', {rows, style: 'height:auto;min-height:44px', value});

  async function templateForm(done) {
    const templates = await get('/device-templates');
    const f = Forms.create();
    const pick = h('select', {}, templates.map((t) => h('option', {value: t.key}, t.name)));
    return h('div', {class: 'stack'}, h('div', {class: 'grid g2'}, f.add('template', 'Template', pick, {required: true}),
      f.add('serial', 'Serial number', h('input', {placeholder: 'e.g. MC2BDJD71684'}), {help: 'it appears in the name automatically and can be changed later'})),
      h('p', {class: 'muted small'}, 'The template includes the manufacturer’s pulse duration steps and cutoff frequencies.'), f.error,
      btn('Add laser from template', async () => {
        const v = f.collect();
        if (!v) return;
        try { const d = await post('/devices/from-template', {template: v.template, serial: v.serial}); toast('Laser added', 'ok'); done(d.id); } catch (e) { f.fail(e); }
      }, 'primary'));
  }

  function createForm(done) {
    const f = Forms.create();
    const Q = Forms.QUANTITIES;
    const number = (q, attrs) => Forms.numberInput(q, attrs);
    const steps = area('1 CW\n2 1950', 6);
    return h('div', {class: 'stack'}, h('div', {class: 'grid g3'}, f.add('name', 'Name', h('input'), {required: true}),
      f.add('manufacturer', 'Manufacturer', h('input'), {empty: ''}), f.add('model', 'Model', h('input'), {empty: ''}),
      f.add('serial', 'Serial number', h('input'), {help: 'optional', empty: ''}),
      f.add('power', 'Rated power', number(Q.ratedPower), {quantity: 'ratedPower', required: true}),
      f.add('wavelength', 'Wavelength', number(Q.wavelength), {quantity: 'wavelength', help: 'optional'}),
      f.add('lo', 'Repetition frequency from', number(Q.repetitionRate, {value: 1}), {quantity: 'repetitionRate', required: true}),
      f.add('hi', 'Repetition frequency to', number(Q.repetitionRate), {quantity: 'repetitionRate', required: true, help: 'greater than the lower limit'})),
    f.add('steps', 'Pulse duration steps', steps, {required: true, read: readSteps(steps), help: 'one step per line: duration in ns and cutoff frequency in kHz; CW has no cutoff'}),
    f.error,
    btn('Create laser', async () => {
      const v = f.collect();
      if (!v) return;
      const passport = {rated_power_w: v.power, wavelength_nm: v.wavelength, repetition_rate_khz: {min: v.lo, max: v.hi}, pulse_steps: v.steps};
      try { const d = await post('/devices', {name: v.name, manufacturer: v.manufacturer, model: v.model, serial: v.serial, passport}); toast('Laser created', 'ok'); done(d.id); } catch (e) { f.fail(e); }
    }, 'primary'));
  }

  /** Edit serial number, description, M², steps and open questions without changing measurements. Measured spot diameter belongs to the lens (REQ-019). */
  function editForm(d, done) {
    const p = d.passport;
    const f = Forms.create();
    const Q = Forms.QUANTITIES;
    const number = (q, attrs) => Forms.numberInput(q, attrs);
    const steps = area(stepsText(p.pulse_steps), 8);
    const open = area((p.open_items || []).join('\n'), 3);
    return h('div', {class: 'stack'}, h('div', {class: 'grid g2'}, f.add('serial', 'Serial number', h('input', {value: d.serial || ''})),
      h('p', {class: 'muted small'}, 'Enter measured spot diameter on the Lens tab: it belongs to the measured lens and does not transfer to its replacement.')),
    h('div', {class: 'grid g3'}, f.add('m2', 'Your laser’s M²', number(Q.m2, {value: p.m2 ?? '', placeholder: 'e.g. 1.3'}), {quantity: 'm2', help: 'beam quality; without it only spot-size bounds are known'}),
      f.add('m2max', 'Maximum M² (from manual)', number(Q.m2, {value: p.m2_max ?? '', placeholder: '1.5'}), {quantity: 'm2', help: 'for this model: 1.5'}),
      f.add('beam', 'Beam diameter at lens', number(Q.beamDiameter, {value: p.beam_diameter_mm ?? ''}), {quantity: 'beamDiameter', help: '7 mm at the laser output; multiply by the beam expander if present'})),
      f.add('defw', 'Default Q-Pulse', number(Forms.QUANTITIES.pulseWidth, {value: p.default_pulse_width_ns ?? '', placeholder: 'e.g. 200'}),
        {quantity: 'pulseWidth', help: 'LightBurn omits Q-Pulse when it equals this value; such layers inherit it. It must be between the shortest and longest steps.'}),
      f.add('desc', 'Description', area(d.description || '', 4)),
      f.add('open', 'Your specification notes', open, {read: () => ({ok: true, value: open.value.split('\n').map((x) => x.trim()).filter(Boolean)}),
        help: 'one per line; the app identifies unread or unconfirmed values, spot diameter and serial number questions'}),
      f.add('steps', 'Pulse duration steps', steps, {required: true, read: readSteps(steps)}),
      f.error,
      btn('Save specifications', async () => {
        const v = f.collect();
        if (!v) return;
        const passport = {...p, m2: v.m2, m2_max: v.m2max, beam_diameter_mm: v.beam, default_pulse_width_ns: v.defw, open_items: v.open, pulse_steps: v.steps};
        try { await patch('/devices/' + d.id, {serial: v.serial, description: v.desc, passport}); toast('Specifications saved', 'ok'); done(d.id); } catch (e) { f.fail(e); }
      }, 'primary'));
  }

  function uploadForm(d, done) {
    const f = Forms.create();
    const kind = h('select', {}, KINDS.map(([k, l]) => h('option', {value: k}, l)));
    const file = h('input', {type: 'file', accept: 'image/jpeg,image/png,application/pdf,text/plain'});
    return h('div', {class: 'stack'}, h('div', {class: 'grid g3'}, f.add('kind', 'Document type', kind, {required: true}),
      f.add('title', 'Name', h('input', {placeholder: 'defaults to file name'}), {empty: ''}),
      f.add('file', 'File', App.filePick(file, 'Choose document'), {required: true,
        read: () => (file.files[0] ? {ok: true, value: file.files[0]} : {ok: false, message: 'Choose a document file: image, PDF or text'})})), f.error,
      btn('Add document', async () => {
        const v = f.collect();
        if (!v) return;
        const fd = new FormData();
        fd.append('kind', v.kind); fd.append('title', v.title);
        fd.append('file', v.file);
        try { await form(`/devices/${d.id}/documents`, fd); toast('Document added', 'ok'); done(d.id); } catch (e) { f.fail(e); }
      }, 'primary'));
  }
  return {templateForm, createForm, editForm, uploadForm, KIND, KINDS};
})();
