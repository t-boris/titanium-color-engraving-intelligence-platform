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
    return h('div', {class: 'card stack'}, h('h3', {}, 'Правила оценки'),
      r.criteria_agreed
        ? h('div', {class: 'alert ok'}, 'Критерии согласованы: автоматическое продвижение знаний до «Валидировано» включено.')
        : h('div', {class: 'alert warn'}, 'Автоматическая валидация ожидает согласования критериев. Ввод порогов сам по себе критерии не согласует.'),
      h('p', {class: 'muted small'}, 'Независимый повтор — отдельная физическая гравировка; повторная фотография той же гравировки повтором не считается (DEC-021). Значений по умолчанию нет.'),
      h('div', {class: 'grid g3'}, field('Порог независимых повторов', rep), field('Допуск отклонения ΔE', tol), field('Порог дисперсии', varr)),
      h('label', {class: 'row'}, agreed, h('span', {}, 'Я согласовал эти критерии')),
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
    return h('div', {class: 'card stack'}, h('h3', {}, 'Слой регистрационных маркеров'),
      h('p', {class: 'muted small'}, 'Маркеры (четыре ArUco и QR с идентификатором) гравируются отдельным слоем. Их параметры зависят от того, как метка выгорает на титане, и по умолчанию не заданы: пока их нет, платы не создаются (DEC-027).'),
      cur ? null : h('div', {class: 'alert warn'}, 'Параметры слоя маркеров не заданы.'),
      h('div', {class: 'grid g3'}, field('Мощность, %', f.power), field('Частота, кГц', f.frequency), field('Скорость, мм/с', f.speed)),
      btn('Сохранить слой маркеров', async () => {
        try { await put('/marker-layer', {power: +f.power.value, frequency: +f.frequency.value, speed: +f.speed.value}); toast('Слой маркеров сохранён', 'ok'); reload(); } catch (e) { fail(e); }
      }, 'primary'));
  }

  return {rulesTab, markersTab};
})();
