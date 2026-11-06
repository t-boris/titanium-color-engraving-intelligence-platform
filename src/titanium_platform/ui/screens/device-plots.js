/* Laser plots use data from /api/devices/:id/charts (REQ-017); DeviceCharts.plot draws the selected series. */
'use strict';
const DevicePlots = (() => {
  const {plot, COLORS} = DeviceCharts;

  /** Cutoff frequency by pulse duration; the laser reduces power below the curve. */
  function cutoff(charts) {
    return plot({title: 'Power cutoff frequency by pulse duration', xLabel: 'Pulse duration, ns', yLabel: 'Cutoff frequency, kHz',
      series: [{name: 'Cutoff frequency', points: charts.cutoff.map((c) => [c.pulse_width_ns, c.cutoff_khz]), markers: true}], xLog: true, yLog: true});
  }

  /** Maximum pulse energy is rated power divided by cutoff frequency; the dashed line is the specified maximum. */
  function energy(charts) {
    const pts = charts.cutoff.map((c) => [c.pulse_width_ns, c.max_pulse_energy_mj]), stated = charts.stated_max_pulse_energy_mj;
    const lo = Math.min(...pts.map((p) => p[0])), hi = Math.max(...pts.map((p) => p[0]));
    const series = [{name: 'Rated power ÷ cutoff frequency', points: pts, markers: true}];
    if (stated) series.push({name: 'Specified maximum', points: [[lo, stated], [hi, stated]], color: '#f2ce8b', dash: '5 4', width: 1.5});
    return plot({title: 'Maximum pulse energy by pulse duration', xLabel: 'Pulse duration, ns', yLabel: 'Pulse energy, mJ', series, xLog: true, yLog: true});
  }

  /** Power or pulse energy by frequency for the selected duration; other durations are faded. mark is the calculated operating point. */
  function byFrequency(charts, width, quantity, mark) {
    const key = quantity === 'power' ? 'power_w' : 'pulse_energy_mj';
    const series = charts.curves.map((c, i) => ({name: c.pulse_width_ns + ' ns', points: c.points.map((p) => [p.frequency_khz, p[key]]), faint: c.pulse_width_ns !== width,
      color: c.pulse_width_ns === width ? COLORS[0] : COLORS[(i % 5) + 1], width: c.pulse_width_ns === width ? 3 : 1}));
    const cur = charts.curves.find((c) => c.pulse_width_ns === width), marks = [];
    if (cur) {
      const knee = cur.points.find((p) => p.frequency_khz === cur.cutoff_khz);
      if (knee) marks.push({x: cur.cutoff_khz, y: knee[key], label: `cutoff ${cur.cutoff_khz} kHz`, color: '#f2ce8b'});
    }
    if (mark) marks.push(mark);
    return plot({title: quantity === 'power' ? 'Output power by frequency' : 'Pulse energy by frequency', xLabel: 'Repetition frequency, kHz',
      yLabel: quantity === 'power' ? 'Power at 100%, W' : 'Pulse energy at 100%, mJ', series, marks, xLog: true, yLog: quantity !== 'power'});
  }
  /** One pulse waveform on the original report axes: power in kW over time in ns (DEC-038). */
  function waveform(w) {
    const points = w.t_ns.map((t, i) => [t, w.p_kw[i]]), s = w.stats;
    const marks = [{x: s.peak_t_ns, y: s.peak_kw, label: `peak ${+s.peak_kw.toPrecision(3)} kW`, color: '#f2ce8b'}];
    return plot({title: 'Pulse waveform: ' + I18N.name(w.title), xLabel: 't, ns', yLabel: 'P, kW', series: [{name: I18N.name(w.title), points, width: 2}], marks});
  }

  return {cutoff, energy, byFrequency, waveform};
})();
