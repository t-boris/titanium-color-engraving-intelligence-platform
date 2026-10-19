/* Расчёт рабочей точки по паспорту лазера и установленной на нём линзе для заданных настроек работы (REQ-017, REQ-018, DEC-036).
   Результат — паспортная модель, не измерение; точка отмечается и на графике (onResult). Значения по умолчанию не подставляются
   сервером: 200 нс предлагается здесь, только если лазер даёт такую ступень (DEC-043). */
'use strict';
const DeviceCalc = (() => {
  const {h, btn, field, pill, post, fail, facts, num} = App;
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
    const pulse = h('select', {'aria-label': 'Длительность импульса'}, h('option', {value: '', selected: !steps.includes(200)}, 'выберите'),
      steps.map((w) => h('option', {value: w, selected: w === 200}, w + ' нс')));
    const f = {power: h('input', {type: 'number', step: 'any', value: 30}), frequency: h('input', {type: 'number', step: 'any', value: 80}), speed: h('input', {type: 'number', step: 'any', value: 900}),
      pulse, interval: h('input', {type: 'number', step: 'any', value: 0.025}), passes: h('input', {type: 'number', min: '1', step: '1', value: 1})};
    const out = h('div', {class: 'stack'});
    const run = async () => {
      if (f.pulse.value === '') return fail(new Error('Выберите длительность импульса'));
      try {
        const o = await post('/operating-point', {device_id: d.id, lens_id: d.lens ? d.lens.id : null, power: +f.power.value, frequency: +f.frequency.value, speed: +f.speed.value,
          pulse_width: +f.pulse.value, line_interval: +f.interval.value, passes: +f.passes.value});
        out.replaceChildren(...result(o));
        onResult(o);
      } catch (e) { fail(e); }
    };
    return h('div', {class: 'card stack'}, h('h3', {}, 'Рабочая точка'),
      h('p', {class: 'muted small'}, 'Расчёт по паспортной модели: мощность растёт с частотой до частоты среза и дальше не растёт.'),
      h('p', {class: 'muted small'}, d.lens ? `Линза: ${App.lensLabel(d.lens)} (установлена на этом лазере).`
        : 'Линза не установлена: диаметр пятна, плотность энергии и перекрытие импульсов не рассчитываются.'),
      h('div', {class: 'grid g3'}, field('Мощность, %', f.power), field('Частота, кГц', f.frequency), field('Скорость, мм/с', f.speed),
        field('Импульс, нс', f.pulse), field('Интервал линий, мм', f.interval), field('Проходы слоя', f.passes)),
      h('div', {class: 'row'}, btn('Рассчитать', run, 'primary')), out);
  }
  return {calculator};
})();
