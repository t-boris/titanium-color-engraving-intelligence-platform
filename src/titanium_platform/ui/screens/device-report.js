/* Laser test report and pulse waveforms with explanations (REQ-017, DEC-037, DEC-038). */
'use strict';
const DeviceReport = (() => {
  const {h, pill, table} = App;
  const cell = (v) => (v == null || v === '' ? '—' : typeof v === 'number' ? String(+v.toPrecision(5)) : String(v));


  function reportCard(d) {
    const r = d.passport.test_report;
    if (!r) return null;
    const rows = r.rows.map((x) => [h('div', {}, h('strong', {}, x.key), h('div', {class: 'small muted'}, GlossaryReport.ROWS[x.key] || x.key)),
      x.condition || '—', x.unit || '—', cell(x.min), cell(x.typ), cell(x.max), x.result == null ? pill('no number', 'warn') : h('strong', {}, cell(x.result))]);
    return h('div', {class: 'card stack'}, h('h3', {}, 'Test report for this laser'),
      h('p', {class: 'muted small'}, `Serial number ${r.serial || '—'} · model ${r.part_number || '—'} · tested ${r.tested_on || '—'}. ${GlossaryReport.COLUMNS}`),
      table(['Specification and meaning', 'Conditions', 'Unit', 'Min', 'Typical', 'Max', 'Result'], rows, undefined, true));
  }

  /** Pulse waveforms use the original axes, with the source photo and comparison to the specification. */
  function waveformsCard(d, charts) {
    if (!charts.waveforms.length) return null;
    const photo = d.documents.find((x) => x.kind === 'waveform');
    const blocks = charts.waveforms.map((w) => {
      const s = w.stats, ok = s.ratio != null && s.ratio > 0.7 && s.ratio < 1.3;
      return h('div', {class: 'stack'}, h('h3', {}, I18N.name(w.title)), DevicePlots.waveform(w),
        h('p', {class: 'muted small'}, `Peak ${+s.peak_kw.toPrecision(3)} kW at ${+s.peak_t_ns.toPrecision(3)} ns. Energy from curve ≈ ${+s.energy_mj.toPrecision(3)} mJ`
          + (s.passport_energy_mj ? `, per specification (60 W ÷ ${w.frequency_khz} kHz) ${+s.passport_energy_mj.toPrecision(3)} mJ.` : '.')),
        s.ratio != null ? pill(ok ? 'digitized curve agrees with specification' : 'difference from specification: ×' + s.ratio, ok ? 'ok' : 'warn') : null,
        w.note ? h('p', {class: 'muted small'}, w.note) : null);
    });
    return h('div', {class: 'card stack'}, h('h3', {}, 'Pulse waveforms from the report'),
      h('p', {class: 'muted small'}, 'Pulse power is in kilowatts and time is in nanoseconds. Average power is tens of watts because the pulse is short and the gap between pulses is long, '
        + 'so peak power is thousands of times higher than average. Curves are digitized approximately from a photograph; open the original under Documents.'),
      h('div', {class: 'grid g2'}, blocks), photo ? h('a', {href: `/api/devices/${d.id}/documents/${photo.id}`, target: '_blank', rel: 'noopener'}, 'Open original photograph') : null);
  }
  return {reportCard, waveformsCard};
})();
