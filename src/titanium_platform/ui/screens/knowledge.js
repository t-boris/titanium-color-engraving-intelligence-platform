/* Знание о цвете: стадия, доказательства, история и решения оператора (REQ-005, DEC-006, DEC-011).
   В производство — только явное действие; автоматически стадия не понижается; «под вопросом» можно подтвердить или понизить вручную. */
'use strict';
const KnowledgeView = (() => {
  const {h, btn, field, link, pill, get, post, confirmBox, modal, table, num, labText, swatch, facts} = App;
  const STAGE = {measured: 'Измерено', candidate: 'Кандидат', repeated: 'Повторено', validated: 'Валидировано', production: 'Производственное'};
  const EVENT = {created: 'создано', promoted: 'повышено автоматически', questioned: 'помечено «под вопросом»', approved: 'утверждено в производство',
    demoted: 'понижено вручную', confirmed: 'флаг снят', rollback: 'откат'};
  const stab = (s) => (s.assessed ? `дисперсия ${num(s.variance)}` : 'не оценена');
  /** Повторяемость стенда (REQ-009): расхождение снимков одной гравировки; есть только у пересъёмок, скорректированных по карте. */
  const rig = (r) => (r && r.assessed
    ? `ΔE ${num(r.mean_delta_e)} в среднем, до ${num(r.max_delta_e)} · снимков одной гравировки: ${r.photos}`
    : 'не оценена: её дают только пересъёмки одной гравировки, скорректированные по эталонной карте');
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 0)} кГц · ${num(p.speed, 0)} мм/с`;

  /** Кнопка, открывающая окно решения; после успеха экран перерисовывается. */
  function decision(label, body, run, cls) {
    return btn(label, () => modal(label, h('div', {class: 'stack'}, ...body), [
      {label: 'Отмена', run: (m) => m.close()},
      {label, cls: cls || 'primary', run: async (m) => { await run(); m.close(); App.render(); }}]));
  }

  function actions(k, kid) {
    const acts = [];
    if (k.stage === 'validated') {
      acts.push(decision('Утвердить для производства', [h('p', {}, 'Производственным цвет становится только по вашему явному действию.')],
        () => post(`/knowledge/${kid}/approve`, {confirm: true})));
    }
    if (k.stage === 'production') {
      const to = h('select', {}, ['validated', 'repeated', 'candidate', 'measured'].map((x) => h('option', {value: x}, STAGE[x])));
      const why = h('input', {placeholder: 'причина'});
      acts.push(decision('Понизить вручную', [field('Новая стадия', to), field('Причина', why)],
        () => post(`/knowledge/${kid}/demote`, {confirm: true, to_stage: to.value, reason: why.value}), 'danger'));
    }
    if (k.questioned) {
      acts.push(decision('Подтвердить запись', [h('div', {class: 'alert warn'}, I18N.tr(k.doubt.reason)),
        h('p', {class: 'small'}, 'Наблюдения-основания: ' + k.doubt.observation_ids.join(', '))], () => post(`/knowledge/${kid}/confirm-questioned`)));
    }
    return acts;
  }

  async function render(kid) {
    const k = await get('/knowledge/' + kid);
    const s = k.summary;
    const history = table(['Когда', 'Событие', 'Было', 'Стало', 'Основание', ''], k.history.map((e) => [
      e.at.slice(0, 16).replace('T', ' '), EVENT[e.type] || e.type, e.from_stage ? STAGE[e.from_stage] : '—', e.to_stage ? STAGE[e.to_stage] : '—', e.type === 'demoted' ? e.reason : I18N.tr(e.reason),
      e.from_stage && e.type !== 'rollback'
        ? btn('Откатить переход', () => confirmBox('Откатить переход', 'Будет добавлено новое событие; стадия не повышается.', 'Откатить',
          async () => { await post(`/knowledge/${kid}/rollback`, {event_id: e.id, confirm_production: k.stage === 'production'}); App.render(); })) : '']), 'Истории нет');
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('h2', {}, 'Знание о цвете'), h('span', {class: 'spacer'}), link(`/colors?device=${k.device_id}&lens=${App.lensParam(k.lens_id)}`, 'К модели цвета'), link(`/setup?tab=rules&device=${k.device_id}&lens=${App.lensParam(k.lens_id)}`, 'Правила оценки')),
      k.questioned ? h('div', {class: 'alert bad'}, [h('strong', {}, 'Под вопросом. '), I18N.tr(k.doubt.reason)]) : null,
      h('div', {class: 'card stack'}, facts([
        ['Стадия', pill(STAGE[k.stage], k.stage === 'production' ? 'ok' : '')], ['Цвет', s ? h('span', {}, swatch(s.lab), labText(s.lab)) : '—'],
        ['Параметры', params(k.parameters) + ` · импульс ${k.parameters.pulse_width} · интервал ${k.parameters.line_interval} · проходов ${k.parameters.passes}`],
        ['Независимых гравировок', s ? s.independent_engravings : '—'], ['Уверенность', s ? num(s.confidence) : '—'],
        ['Ожидаемая ошибка ΔE', s ? num(s.expected_delta_e) : '—'], ['Стабильность', s ? stab(s.stability) : '—'],
        ['Повторяемость стенда', s ? rig(s.rig_repeatability) : '—']]),
      s && s.attribution_note ? h('div', {class: 'alert warn'}, I18N.tr(s.attribution_note)) : null, h('div', {class: 'row'}, actions(k, kid))),
      h('div', {class: 'card'}, h('h3', {}, 'История'), history),
      s ? h('div', {class: 'card'}, h('h3', {}, 'Наблюдения-основания'), h('p', {}, s.observation_ids.join(', '))) : null);
  }
  return {render, STAGE, stab, rig, params};
})();
