/* Вкладки «Правила оценки» и «Слой маркеров» (REQ-005, DEC-021, DEC-027). */
'use strict';
const SetupRules = (() => {
  const {h, btn, field, link, get, put, toast, fail} = App;
  const nul = (el) => (el.value === '' ? null : +el.value);

  async function rulesTab(p, reload) {
    if (!p) return h('div', {class: 'card'}, 'Сначала настройте профиль лазера');
    const r = await get(`/profiles/${p.id}/rules`);
    const rep = h('input', {type: 'number', step: '1', min: '1', value: r.repeat_threshold ?? ''});
    const tol = h('input', {type: 'number', step: 'any', min: '0', value: r.delta_tolerance ?? ''});
    const varr = h('input', {type: 'number', step: 'any', min: '0', value: r.variance_threshold ?? ''});
    const agreed = h('input', {type: 'checkbox', checked: r.criteria_agreed});
    return h('div', {class: 'card stack'}, h('h3', {}, 'Как система оценивает повторяемость'),
      r.criteria_agreed
        ? h('div', {class: 'alert ok'}, 'Автоматическое повышение до «Валидировано» включено по указанным ниже критериям.')
        : h('div', {class: 'alert warn'}, 'Пока критерии не согласованы, записи остаются измеренными/повторёнными и не повышаются автоматически.'),
      h('p', {class: 'muted'}, 'Эти правила нужны только для автоматической отметки надёжности результата. Они не меняют параметры лазера, файл LightBurn или сам цвет.'),
      h('ul', {class: 'muted small'},
        h('li', {}, 'Независимые повторы — отдельные физические гравировки одного набора параметров; пересъёмка той же гравировки не считается.'),
        h('li', {}, 'Допуск ΔE — максимальное цветовое отклонение между повторами, которое вы считаете приемлемым.'),
        h('li', {}, 'Порог дисперсии — дополнительная граница разброса цвета между повторами; меньше означает стабильнее.')),
      h('div', {class: 'grid g3'}, field('Сколько гравировок повторить', rep), field('Допуск цветового отклонения, ΔE', tol), field('Допустимая дисперсия цвета', varr)),
      h('p', {class: 'muted small'}, 'При заполнении всех трёх значений система сможет отметить результат «Валидировано», когда наберётся нужное число независимых гравировок и оба показателя разброса окажутся в пределах порогов. Значения выбираете вы; заранее заданных нет.'),
      h('label', {class: 'row'}, agreed, h('span', {}, 'Включить автоматическую оценку по этим критериям')),
      h('div', {class: 'row'}, btn('Сохранить пороги', async () => {
        try {
          await put(`/profiles/${p.id}/rules`, {repeat_threshold: nul(rep), delta_tolerance: nul(tol), variance_threshold: nul(varr), criteria_agreed: agreed.checked});
          toast('Пороги сохранены', 'ok'); reload(p.id, 'rules');
        } catch (e) { fail(e); }
      }, 'primary'), link('/colors?profile=' + p.id, 'Карта цветов')));
  }

  async function markersTab(reload) {
    const cur = await get('/marker-layer');
    const f = {power: h('input', {type: 'number', step: 'any', value: cur ? cur.power : ''}), frequency: h('input', {type: 'number', step: 'any', value: cur ? cur.frequency : ''}),
      speed: h('input', {type: 'number', step: 'any', value: cur ? cur.speed : ''})};
    return h('div', {class: 'card stack'}, h('h3', {}, 'Кодовые метки на тестовой плате'),
      h('p', {class: 'muted'}, 'Это не тестовый рисунок и не слой чистки. Вокруг матрицы идут четыре угловые метки и QR с номером эксперимента. Они помогают программе выровнять фотографию и понять, какая пластина снята. В измерения цвета они не входят.'),
      h('p', {class: 'muted small'}, 'В LightBurn эти фигуры находятся на отдельном слое «Markers», поэтому при желании его можно выключить. Мощность, частота и скорость ниже задают читаемость кода на титане; этот слой идёт после обязательной чистки и до тестовых ячеек.'),
      cur ? null : h('div', {class: 'alert warn'}, 'Параметры кодовых меток пока не заданы. Их нужно задать один раз и проверить на титане перед автоматическим поиском меток по фотографии.'),
      h('div', {class: 'grid g3'}, field('Мощность, %', f.power), field('Частота, кГц', f.frequency), field('Скорость, мм/с', f.speed)),
      btn('Сохранить параметры кодовых меток', async () => {
        try { await put('/marker-layer', {power: +f.power.value, frequency: +f.frequency.value, speed: +f.speed.value}); toast('Слой маркеров сохранён', 'ok'); reload(); } catch (e) { fail(e); }
      }, 'primary'));
  }

  return {rulesTab, markersTab};
})();
