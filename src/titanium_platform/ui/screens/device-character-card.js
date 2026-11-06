/* Laser characterization shows the source of each value and whether it is used in calculations (REQ-018, DEC-040). */
'use strict';
const DeviceCharacterCard = (() => {
  const {h, pill, link, facts} = App;
  const g = (v, d = 4) => (v == null ? '—' : String(+(+v).toPrecision(d)));
  const STATE = {used: ['used in calculations', 'ok'], waiting: ['awaiting confirmation', 'warn'], reference: ['reference only', ''], unknown: ['not specified', 'bad']};
  const BASIS = {installed: 'installed by you', bound: 'bounds only (M² required)', lens: 'lens field', 'lens and laser settings': 'smaller of lens field and settings',
    measured: 'measured by you / on this laser', rated: 'rated specification', controller: 'limited by controller settings', laser: 'laser specification',
    passport: 'specification', calculated: 'calculated', nominal: 'rated'};
  const WAIT = {'Min PWM': 'Min PWM', 'Max PWM': 'Max PWM', 'Field Size': 'Field Size', 'Size Width': 'Size Width', 'Size Height': 'Size Height',
    lens: 'lens', focal_length: 'lens focal length', beam_diameter: 'beam diameter', wavelength: 'wavelength', m2: 'M²'};

  function label(i) {
    const v = i.value;
    switch (i.key) {
      case 'power': return ['Laser power', `${g(v, 4)} W`, 'Used to calculate output power and pulse energy.'];
      case 'frequency_range': {
        const c = i.controller || {};
        return ['Operating frequencies', `${g(v.min)}–${g(v.max)} kHz`, `Lower limit ${c.min != null ? 'from Min PWM' : 'from the laser specification'}; upper limit ${c.max != null ? 'from Max PWM' : 'from the laser specification'}`
          + `${c.contradictory ? ' (Min PWM and Max PWM conflict and are not used)' : ''}. Exceeding controller limits produces a warning; exceeding laser limits produces an error.`];
      }
      case 'work_field': return ['Work field', v ? `${g(v.width)} × ${g(v.height)} mm` : '—', 'A plate with markers cannot exceed the field.'];
      case 'pulse_widths': return ['Pulse durations', `${v.length} steps`, 'Plates and plans accept durations between the minimum and maximum; cutoff frequency is estimated between steps.'];
      case 'max_pulse_energy': return ['Maximum pulse energy', v == null ? '—' : `${g(v)} mJ`, 'Calculated energy does not exceed this value.'];
      case 'spot_diameter': return ['Spot diameter', v != null ? `${g(v, 3)} µm` : (i.low ? `${g(i.low, 3)}${i.high ? '–' + g(i.high, 3) : '+'} µm` : '—'), 'Used for fluence and pulse overlap; calculated from the lens.'];
      case 'lens': return ['Lens', v ? App.lensLabel(v) : 'not installed', 'Determines spot and field; new plates record the replacement lens.'];

      case 'wavelength': return ['Wavelength', v == null ? '—' : `${g(v)} nm`, 'Reference only; not used in calculations.'];
      default: return ['Peak pulse power', v == null ? '—' : `${g(v)} kW`, 'Reference from the report waveform.'];
    }
  }

  function card(d) {
    const rows = d.characterization.items.map((i) => {
      const [name, value, why] = label(i), [state, kind] = STATE[i.state];
      return [h('div', {}, h('strong', {}, name), h('div', {class: 'small muted'}, why)), h('strong', {}, value), BASIS[i.basis] || i.basis || '—',
        h('span', {}, pill(state, kind), i.waiting_for.length ? h('div', {class: 'small muted'}, 'waiting for: ' + i.waiting_for.map((k) => WAIT[k] || k).join(', ')) : null)];
    });
    const waiting = d.characterization.items.filter((i) => i.state === 'waiting' || i.waiting_for.length);
    // Show both printed and handwritten conflicting values; neither is used (REQ-017).
    const shown = (c, v) => `${v.value}${typeof v.value === 'number' && c.unit ? ' ' + c.unit : ''}`;
    const conflicts = (d.characterization.unresolved || []).map((c) => h('li', {},
      h('strong', {}, c.key), `: ${c.values[0].status === 'printed' ? 'printed' : 'written'} ${shown(c, c.values[0])}, handwritten beside it — ${shown(c, c.values[1])}`));
    return h('div', {class: 'card stack'}, h('h3', {}, 'Laser characterization'),
      h('p', {class: 'muted small'}, 'Derived from the entered specifications, report, waveforms and settings. Recalculated whenever opened, including after a value is confirmed or corrected. '
        + 'Unconfirmed handwritten values are not used in calculations.'),
      App.table(['Item', 'Value', 'Source', 'Calculations'], rows, undefined, true),
      conflicts.length ? h('div', {class: 'alert warn'}, h('p', {}, 'Unresolved: printed and handwritten values conflict, so neither is used in calculations.'),
        h('ul', {}, ...conflicts), h('p', {class: 'small'}, 'Check the document photograph and confirm the correct value ✓ on the ',
          link(`/devices/${d.id}?tab=controller`, 'Laser settings'), '.')) : null,
      waiting.length ? h('div', {class: 'alert warn'}, 'To use these values, confirm them ✓ on the ', link(`/devices/${d.id}?tab=controller`, 'Laser settings'), '.') : null);
  }
  return {card};
})();
