/* Знание о цвете: стадия, доказательства, история и решения оператора (REQ-005, DEC-006, DEC-011).
   В производство — только явное действие; автоматически стадия не понижается; «под вопросом» можно подтвердить или понизить вручную.
   Страница на один экран (REQ-044, DEC-080): слева сведения и решения, справа история и наблюдения-основания; длинное прокручивается в своей панели. */
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
    if (k.counted_from) {
      acts.push(decision('Отменить «с последней гравировки»', [h('p', {}, 'Старые гравировки этого рецепта снова будут считаться; знание, выводы и работы '
        + 'пересчитаются.')], () => post(`/exclusions/${k.counted_from.id}/revoke`, {})));
    }
    if (k.questioned) {
      acts.push(decision('Подтвердить запись', [h('div', {class: 'alert warn'}, I18N.tr(k.doubt.reason)),
        h('p', {class: 'small'}, 'Наблюдения-основания: ' + k.doubt.observation_ids.join(', '))], () => post(`/knowledge/${kid}/confirm-questioned`)));
    }
    return acts;
  }

  /** The operator's «Считать с последней гравировки» on this recipe (act-on-findings REQ-002): which engraving it counts from, how many older
      ones do not count. */
  function countedFrom(x) {
    const kept = x.kept || {};
    const at = (iso) => (iso ? new Date(iso).toLocaleDateString('ru-RU') : '—');
    return h('div', {class: 'alert warn small'}, `Считается с гравировки${kept.title ? ` «${kept.title}»` : ''} от ${at(kept.when)}`
      + (kept.pair_ids ? ` (фото № ${kept.pair_ids.join(', ')})` : '') + `; старых не считается: ${(x.engraving_ids || []).length}. `
      + `Решение оператора от ${at(x.created_at)}` + (x.note ? `: «${x.note}»` : '') + '.');
  }

  async function render(kid) {
    const k = await get('/knowledge/' + kid);
    const s = k.summary;
    const history = table(['Когда', 'Событие', 'Было', 'Стало', 'Основание', ''], k.history.map((e) => [
      e.at.slice(0, 16).replace('T', ' '), EVENT[e.type] || e.type, e.from_stage ? STAGE[e.from_stage] : '—', e.to_stage ? STAGE[e.to_stage] : '—', e.type === 'demoted' ? I18N.known(e.reason) ?? e.reason : I18N.tr(e.reason),     // своё основание оператора — как написано
      e.from_stage && e.type !== 'rollback'
        ? btn('Откатить переход', () => confirmBox('Откатить переход', 'Будет добавлено новое событие; стадия не повышается.', 'Откатить',
          async () => { await post(`/knowledge/${kid}/rollback`, {event_id: e.id, confirm_production: k.stage === 'production'}); App.render(); })) : '']), 'Истории нет');
    const back = `/colors?device=${k.device_id}&lens=${App.lensParam(k.lens_id)}`;
    const ids = s ? s.observation_ids : [];
    return h('div', {class: 'os kn'},
      h('div', {class: 'os-head'}, h('a', {class: 'btn btn-small', href: '#' + back}, '← К модели цвета'), h('h2', {}, 'Знание о цвете'), pill(STAGE[k.stage], k.stage === 'production' ? 'ok' : ''),
        h('span', {class: 'spacer'}), h('a', {class: 'btn btn-small', href: `#/setup?tab=rules&device=${k.device_id}&lens=${App.lensParam(k.lens_id)}`}, 'Правила оценки')),
      k.questioned ? h('div', {class: 'alert bad kn-alert'}, [h('strong', {}, 'Под вопросом. '), I18N.tr(k.doubt.reason)]) : null,
      h('div', {class: 'os-body kn-body'},
        h('section', {class: 'os-col'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Сведения')),
          h('div', {class: 'os-scroll stack'}, facts([
            ['Стадия', pill(STAGE[k.stage], k.stage === 'production' ? 'ok' : '')], ['Цвет', s ? h('span', {}, swatch(s.lab), labText(s.lab)) : '—'],
            ['Параметры', params(k.parameters) + ` · импульс ${k.parameters.pulse_width} · интервал ${k.parameters.line_interval} · проходов ${k.parameters.passes}`],
            ['Независимых гравировок', s ? s.independent_engravings : '—'], ['Уверенность', s ? num(s.confidence) : '—'],
            ['Совпали по цвету', s ? App.agreed(s.agreement) + (s.caution ? ` · ${App.CAUTION[s.caution]}` : '') : '—'],
            ['Ожидаемая ошибка ΔE', s ? num(s.expected_delta_e) : '—'], ['Стабильность', s ? stab(s.stability) : '—'],
            ['Повторяемость стенда', s ? rig(s.rig_repeatability) : '—']]),
          s && s.attribution_note ? h('div', {class: 'alert warn'}, I18N.tr(s.attribution_note)) : null,
          k.counted_from ? countedFrom(k.counted_from) : null, h('div', {class: 'row'}, actions(k, kid)))),
        h('div', {class: 'kn-right'},
          h('section', {class: 'os-col kn-history'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'История'), pill(k.history.length)), h('div', {class: 'os-scroll'}, history)),
          s ? h('section', {class: 'os-col kn-evidence'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Наблюдения-основания'), pill(ids.length)),
            h('div', {class: 'os-scroll'}, h('p', {}, ids.join(', ')))) : null)));
  }
  return {render, STAGE, stab, rig, params};
})();
