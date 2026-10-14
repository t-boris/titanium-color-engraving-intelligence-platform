/* Расчёт рабочей точки по паспорту лазера для профиля, привязанного к нему (REQ-017, DEC-036).
   Результат — паспортная модель, не измерение; точка отмечается и на графике (onResult). */
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
    if (!d.profiles.length) {
      return h('div', {class: 'card'}, h('h3', {}, 'Рабочая точка'), h('p', {class: 'muted'}, 'Привяжите профиль к лазеру, чтобы рассчитать мощность и энергию импульса.'));
    }
    const prof = h('select', {'aria-label': 'Профиль'}, d.profiles.map((p) => h('option', {value: p.id}, `${p.name} · версия ${p.version} · ${p.pulse_width} нс`)));
    const f = {power: h('input', {type: 'number', step: 'any', value: 30}), frequency: h('input', {type: 'number', step: 'any', value: 80}), speed: h('input', {type: 'number', step: 'any', value: 900})};
    const out = h('div', {class: 'stack'});
    const run = async () => {
      try {
        const o = await post('/operating-point', {profile_id: +prof.value, power: +f.power.value, frequency: +f.frequency.value, speed: +f.speed.value});
        out.replaceChildren(...result(o));
        onResult(o);
      } catch (e) { fail(e); }
    };
    return h('div', {class: 'card stack'}, h('h3', {}, 'Рабочая точка'),
      h('p', {class: 'muted small'}, 'Расчёт по паспортной модели: мощность растёт с частотой до частоты среза и дальше не растёт.'),
      h('div', {class: 'grid g3'}, field('Профиль', prof), field('Мощность, %', f.power), field('Частота, кГц', f.frequency), field('Скорость, мм/с', f.speed)),
      h('div', {class: 'row'}, btn('Рассчитать', run, 'primary')), out);
  }
  return {calculator};
})();
