/* Calculate an operating point from laser specifications and its installed lens (REQ-017, REQ-018, DEC-036).
   Results are modeled, not measured; 200 ns is suggested only when the laser supports it (DEC-043). */
'use strict';
const DeviceCalc = (() => {
  const {h, btn, pill, post, facts, num} = App;
  const g = (v, d = 3) => (v == null ? '—' : String(+(+v).toPrecision(d)));

  function result(o) {
    const tile = ([k, v]) => h('div', {class: 'card'}, h('strong', {}, v), h('p', {class: 'muted small'}, k));
    const notes = [...o.problems.map((t) => h('div', {class: 'alert bad'}, I18N.tr(t))), ...o.notes.map((t) => h('div', {class: 'alert warn'}, I18N.tr(t)))];
    return [h('div', {class: 'grid g3'}, [['Output power', g(o.output_power_w) + ' W'], ['Pulse energy', o.pulse_energy_mj == null ? '—' : g(o.pulse_energy_mj) + ' mJ'],
      ['Pulse pitch', o.pulse_pitch_um == null ? '—' : g(o.pulse_pitch_um) + ' µm']].map(tile)),
    facts([['Dose across all passes', g(o.areal_energy_j_cm2) + ' J/cm²'], ['Pulses per mm²', o.pulses_per_mm2 == null ? null : num(o.pulses_per_mm2, 0)],
      ['Coverage rate', g(o.coverage_rate_mm2_s) + ' mm²/s'], ['Fluence', o.fluence_j_cm2 == null ? null : g(o.fluence_j_cm2) + ' J/cm²'],
      ['Pulse overlap', o.pulse_overlap == null ? null : Math.round(o.pulse_overlap * 100) + ' %'], ['Basis', pill('specification model, not a measurement')]]), ...notes];
  }

  function calculator(d, onResult) {
    const steps = d.passport.pulse_steps.map((s) => +s.pulse_width_ns);
    const f = Forms.create();
    const Q = Forms.QUANTITIES;
    const number = (q, value) => Forms.numberInput(q, {value});
    const pulse = h('select', {}, h('option', {value: '', selected: !steps.includes(200)}, 'Choose'),
      steps.map((w) => h('option', {value: w, selected: w === 200}, w + ' ns')));
    // the pulse is one of the laser's own steps (devices.require_selectable): a list, so no typed value can miss it
    const boxes = [f.add('power', 'Power', number(Q.power, 30), {quantity: 'power', required: true}),
      f.add('frequency', 'Frequency', number(Q.frequency, 80), {quantity: 'frequency', required: true, help: 'the calculation reports values outside this laser’s range'}),
      f.add('speed', 'Speed', number(Q.speed, 900), {quantity: 'speed', required: true}),
      f.add('pulse', 'Pulse, ns', pulse, {required: true, read: () => (pulse.value === '' ? {ok: false, message: 'Choose a pulse duration supported by the laser'} : {ok: true, value: +pulse.value})}),
      f.add('interval', 'Line spacing', number(Q.lineInterval, 0.025), {quantity: 'lineInterval', required: true}),
      f.add('passes', 'Layer passes', number(Q.passes, 1), {quantity: 'passes', required: true})];
    const out = h('div', {class: 'stack'});
    const run = async () => {
      const v = f.collect();
      if (!v) return;
      try {
        const o = await post('/operating-point', {device_id: d.id, lens_id: d.lens ? d.lens.id : null, power: v.power, frequency: v.frequency, speed: v.speed,
          pulse_width: v.pulse, line_interval: v.interval, passes: v.passes});
        out.replaceChildren(...result(o));
        onResult(o);
      } catch (e) { f.fail(e); }
    };
    return h('div', {class: 'card stack'}, h('h3', {}, 'Operating point'),
      h('p', {class: 'muted small'}, 'Specification model: power rises with frequency up to the cutoff and remains level above it.'),
      h('p', {class: 'muted small'}, d.lens ? `Lens: ${App.lensLabel(d.lens)} (installed on this laser).`
        : 'No lens is installed: spot diameter, fluence and pulse overlap cannot be calculated.'),
      h('div', {class: 'grid g3'}, ...boxes), f.error,
      h('div', {class: 'row'}, btn('Calculate', run, 'primary')), out);
  }
  return {calculator};
})();
