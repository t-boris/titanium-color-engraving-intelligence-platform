/* Три графика лазера из ответа /api/devices/:id/charts (REQ-017): срез мощности, наибольшая энергия импульса,
   мощность и энергия импульса по частоте. Рисует DeviceCharts.plot; здесь только выбор данных. */
'use strict';
const DevicePlots = (() => {
  const {plot, COLORS} = DeviceCharts;

  /** Частота среза по длительности импульса. Ниже линии лазер сам занижает мощность. */
  function cutoff(charts) {
    return plot({title: 'Частота среза мощности по длительности импульса', xLabel: 'Длительность импульса, нс', yLabel: 'Частота среза, кГц',
      series: [{name: 'Частота среза', points: charts.cutoff.map((c) => [c.pulse_width_ns, c.cutoff_khz]), markers: true}], xLog: true, yLog: true});
  }

  /** Наибольшая энергия импульса: номинальная мощность, делённая на частоту среза; пунктир — паспортный максимум. */
  function energy(charts) {
    const pts = charts.cutoff.map((c) => [c.pulse_width_ns, c.max_pulse_energy_mj]), stated = charts.stated_max_pulse_energy_mj;
    const lo = Math.min(...pts.map((p) => p[0])), hi = Math.max(...pts.map((p) => p[0]));
    const series = [{name: 'Номинальная мощность ÷ частота среза', points: pts, markers: true}];
    if (stated) series.push({name: 'Паспортный максимум', points: [[lo, stated], [hi, stated]], color: '#f2ce8b', dash: '5 4', width: 1.5});
    return plot({title: 'Наибольшая энергия импульса по длительности импульса', xLabel: 'Длительность импульса, нс', yLabel: 'Энергия импульса, мДж', series, xLog: true, yLog: true});
  }

  /** Мощность или энергия импульса по частоте для выбранной длительности; остальные длительности — бледно. mark — рассчитанная рабочая точка. */
  function byFrequency(charts, width, quantity, mark) {
    const key = quantity === 'power' ? 'power_w' : 'pulse_energy_mj';
    const series = charts.curves.map((c, i) => ({name: c.pulse_width_ns + ' нс', points: c.points.map((p) => [p.frequency_khz, p[key]]), faint: c.pulse_width_ns !== width,
      color: c.pulse_width_ns === width ? COLORS[0] : COLORS[(i % 5) + 1], width: c.pulse_width_ns === width ? 3 : 1}));
    const cur = charts.curves.find((c) => c.pulse_width_ns === width), marks = [];
    if (cur) {
      const knee = cur.points.find((p) => p.frequency_khz === cur.cutoff_khz);
      if (knee) marks.push({x: cur.cutoff_khz, y: knee[key], label: `срез ${cur.cutoff_khz} кГц`, color: '#f2ce8b'});
    }
    if (mark) marks.push(mark);
    return plot({title: quantity === 'power' ? 'Выходная мощность по частоте' : 'Энергия импульса по частоте', xLabel: 'Частота повторения, кГц',
      yLabel: quantity === 'power' ? 'Мощность при 100 %, Вт' : 'Энергия импульса при 100 %, мДж', series, marks, xLog: true, yLog: quantity !== 'power'});
  }
  /** Форма одного импульса в тех же осях, что и на оригинале из протокола: P, кВт от t, нс (DEC-038). */
  function waveform(w) {
    const points = w.t_ns.map((t, i) => [t, w.p_kw[i]]), s = w.stats;
    const marks = [{x: s.peak_t_ns, y: s.peak_kw, label: `пик ${+s.peak_kw.toPrecision(3)} кВт`, color: '#f2ce8b'}];
    return plot({title: 'Форма импульса: ' + I18N.name(w.title), xLabel: 't, нс', yLabel: 'P, кВт', series: [{name: I18N.name(w.title), points, width: 2}], marks});
  }

  return {cutoff, energy, byFrequency, waveform};
})();
