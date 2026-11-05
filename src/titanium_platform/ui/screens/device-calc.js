/* Расчёт рабочей точки по паспорту лазера и установленной на нём линзе для заданных настроек работы (REQ-017, REQ-018, DEC-036).
   Результат — паспортная модель, не измерение; точка отмечается и на графике (onResult). Значения по умолчанию не подставляются
   сервером: 200 нс предлагается здесь, только если лазер даёт такую ступень (DEC-043). */
'use strict';
const DeviceCalc = (() => {
  const {h, btn, pill, post, facts, num} = App;
  const g = (v, d = 3) => (v == null ? '—' : String(+(+v).toPrecision(d)));

  function result(o) {
    const tile = ([k, v]) => h('div', {class: 'card'}, h('strong', {}, v), h('p', {class: 'muted small'}, k));
    const notes = [...o.problems.map((t) => h('div', {class: 'alert bad'}, I18N.tr(t))), ...o.notes.map((t) => h('div', {class: 'alert warn'}, I18N.tr(t)))];
    return [h('div', {class: 'grid g3'}, [['Выходная мощность', g(o.output_power_w) + ' Вт'], ['Энергия импульса', o.pulse_energy_mj == null ? '—' : g(o.pulse_energy_mj) + ' мДж'],
      ['Шаг между импульсами', o.pulse_pitch_um == null ? '—' : g(o.pulse_pitch_um) + ' мкм']].map(tile)),
    facts([['Доза за все проходы', g(o.areal_energy_j_cm2) + ' Дж/см²'], ['Импульсов на мм²', o.pulses_per_mm2 == null ? null : num(o.pulses_per_mm2, 0)],
      ['Скорость покрытия', g(o.coverage_rate_mm2_s) + ' мм²/с'], ['Плотность энергии', o.fluence_j_cm2 == null ? null : g(o.fluence_j_cm2) + ' Дж/см²'],
      ['Перекрытие импульсов', o.pulse_overlap == null ? null : Math.round(o.pulse_overlap * 100) + ' %'], ['Основание', pill('паспортная модель, не измерение')]]), ...notes];
  }

  function calculator(d, onResult) {
    const steps = d.passport.pulse_steps.map((s) => +s.pulse_width_ns);
    const f = Forms.create();
    const Q = Forms.QUANTITIES;
    const number = (q, value) => Forms.numberInput(q, {value});
    const pulse = h('select', {}, h('option', {value: '', selected: !steps.includes(200)}, 'выберите'),
      steps.map((w) => h('option', {value: w, selected: w === 200}, w + ' нс')));
    // the pulse is one of the laser's own steps (devices.require_selectable): a list, so no typed value can miss it
    const boxes = [f.add('power', 'Мощность', number(Q.power, 30), {quantity: 'power', required: true}),
      f.add('frequency', 'Частота', number(Q.frequency, 80), {quantity: 'frequency', required: true, help: 'вне диапазона этого лазера расчёт скажет об этом сам'}),
      f.add('speed', 'Скорость', number(Q.speed, 900), {quantity: 'speed', required: true}),
      f.add('pulse', 'Импульс, нс', pulse, {required: true, read: () => (pulse.value === '' ? {ok: false, message: 'Выберите длительность импульса: у лазера есть только свои ступени'} : {ok: true, value: +pulse.value})}),
      f.add('interval', 'Интервал линий', number(Q.lineInterval, 0.025), {quantity: 'lineInterval', required: true}),
      f.add('passes', 'Проходы слоя', number(Q.passes, 1), {quantity: 'passes', required: true})];
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
    return h('div', {class: 'card stack'}, h('h3', {}, 'Рабочая точка'),
      h('p', {class: 'muted small'}, 'Расчёт по паспортной модели: мощность растёт с частотой до частоты среза и дальше не растёт.'),
      h('p', {class: 'muted small'}, d.lens ? `Линза: ${App.lensLabel(d.lens)} (установлена на этом лазере).`
        : 'Линза не установлена: диаметр пятна, плотность энергии и перекрытие импульсов не рассчитываются.'),
      h('div', {class: 'grid g3'}, ...boxes), f.error,
      h('div', {class: 'row'}, btn('Рассчитать', run, 'primary')), out);
  }
  return {calculator};
})();
