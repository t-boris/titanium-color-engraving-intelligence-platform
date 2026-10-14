/* Диалог «Создать плату»: серия плат по мощности × частоте, по плате на каждую скорость (REQ-003).
   «Создать планы» доступно только после актуального предпросмотра; любое изменение значений его сбрасывает. */
'use strict';
const PlateDialog = (() => {
  const {h, btn, field, post, toast, modal, table} = App;

  /** Мощность и энергия импульса ячейки, если профиль привязан к лазеру; расчёт, не измерение. */
  function passport(o) {
    if (!o) return '—';
    const energy = o.pulse_energy_mj == null ? '' : ` · ${+o.pulse_energy_mj.toPrecision(3)} мДж`;
    return h('span', {}, `≈ ${+o.output_power_w.toPrecision(3)} Вт${energy}`, o.below_cutoff ? [' ', App.pill('ниже среза', 'warn')] : '');
  }

  function open(profiles, reload) {
    const prof = h('select', {'aria-label': 'Версия профиля'}, profiles.map((p) => h('option', {value: p.id}, `${p.name} · версия ${p.version}`)));
    const f = {powers: h('input', {value: '10 20 30'}), frequencies: h('input', {value: '40 80'}), speeds: h('input', {value: '900'}),
      cw: h('input', {type: 'number', step: 'any', value: 6}), ch: h('input', {type: 'number', step: 'any', value: 5}), gap: h('input', {type: 'number', step: 'any', value: 1})};
    const out = h('div', {}, h('p', {class: 'muted small'}, 'Нажмите «Предпросмотр»: создать планы можно только по актуальному предпросмотру.'));
    let fresh = false;
    const body = () => ({profile_id: +prof.value, powers: f.powers.value, frequencies: f.frequencies.value, speeds: f.speeds.value,
      cell_width: +f.cw.value, cell_height: +f.ch.value, gap: +f.gap.value});
    const stale = () => { fresh = false; out.replaceChildren(h('p', {class: 'muted small'}, 'Значения изменены: сделайте предпросмотр заново.')); };
    Object.values(f).concat([prof]).forEach((el) => el.addEventListener('input', stale));
    const form = h('div', {class: 'stack'}, field('Версия профиля', prof),
      h('div', {class: 'grid g3'}, field('Мощность, %', f.powers, 'числа через пробел или «;»'), field('Частота, кГц', f.frequencies), field('Скорости, мм/с — по плате на каждую', f.speeds)),
      h('div', {class: 'grid g3'}, field('Ширина ячейки, мм', f.cw), field('Высота ячейки, мм', f.ch), field('Зазор, мм', f.gap)),
      h('div', {class: 'alert'}, 'Маркеры и машинный идентификатор обязательны, отключить их нельзя. Создание плат не создаёт измерений.'), out);
    return modal('Создать плату', form, [
      {label: 'Отмена', run: (x) => x.close()},
      {label: 'Предпросмотр', run: async () => {
        const grids = await post('/plates/preview', body());
        fresh = true;
        out.replaceChildren(...grids.map((g) => h('div', {class: 'card'}, h('strong', {}, `Скорость ${g.speed} мм/с`),
          h('p', {class: 'muted small'}, `${g.geometry.columns} × ${g.geometry.rows} ячеек, ${g.geometry.width.toFixed(1)} × ${g.geometry.height.toFixed(1)} мм`),
          table(['Ячейка', 'Мощность', 'Частота', 'По паспорту лазера'], g.cells.map((c) => [c.id, c.parameters.power, c.parameters.frequency, passport(c.operating_point)])))));
      }},
      {label: 'Создать планы', cls: 'primary', run: async (x) => {
        if (!fresh) throw new Error('Сначала сделайте актуальный предпросмотр');
        const made = await post('/plates', body());
        x.close(); toast(`Создано плат: ${made.length}`, 'ok'); reload();
      }}]);
  }
  return {open};
})();
