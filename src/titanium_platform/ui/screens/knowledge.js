/* Знание о цвете: стадия, доказательства, история и решения оператора (REQ-005, DEC-006, DEC-011).
   В производство — только явное действие; автоматически стадия не понижается; «под вопросом» можно подтвердить или понизить вручную.
   Страница на один экран (REQ-044, DEC-080): слева сведения и решения, справа история и наблюдения-основания; длинное прокручивается в своей панели. */
'use strict';
const KnowledgeView = (() => {
  const {h, btn, field, link, pill, get, post, modal, num, labText, swatch, facts} = App;
  const STAGE = {measured: 'Измерено', candidate: 'Кандидат', repeated: 'Повторено', validated: 'Валидировано', production: 'Производственное'};
  const EVENT = {created: 'создано', promoted: 'повышено автоматически', questioned: 'помечено «под вопросом»', approved: 'утверждено в производство',
    demoted: 'понижено вручную', confirmed: 'флаг снят', rollback: 'откат'};
  const stab = (s) => (s.assessed ? `дисперсия ${num(s.variance)}` : 'не оценена');
  /** Повторяемость стенда (REQ-009): расхождение снимков одной гравировки; есть только у пересъёмок, скорректированных по карте. */
  const rig = (r) => (r && r.assessed
    ? `ΔE ${num(r.mean_delta_e)} в среднем, до ${num(r.max_delta_e)} · снимков одной гравировки: ${r.photos}`
    : 'не оценена: её дают только пересъёмки одной гравировки, скорректированные по эталонной карте');
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 0)} кГц · ${num(p.speed, 0)} мм/с`;

  /** Кнопка, открывающая окно решения; после успеха экран перерисовывается. ``form`` (Forms.create()) — поля решения: окно остаётся открытым, пока
      они не верны, а отказ сервера показан под ними, с набранным (ux-save-feedback-p0, REQ-003); ``run(values)`` получает прочитанные значения. */
  function decision(label, body, run, cls, form = null) {
    return btn(label, () => modal(label, h('div', {class: 'stack'}, ...body, form ? form.error : null), [
      {label: 'Отмена', run: (m) => m.close()},
      {label, cls: cls || 'primary', run: async (m) => {
        const values = form ? form.collect() : {};
        if (!values) return;
        try { await run(values); } catch (e) { if (!form) throw e; form.fail(e); return; }
        m.close(); App.render();
      }}]));
  }

  function actions(k, kid) {
    const acts = [];
    if (k.stage === 'validated') {
      acts.push(decision('Утвердить для производства', [h('p', {}, 'Производственным цвет становится только по вашему явному действию.')],
        () => post(`/knowledge/${kid}/approve`, {confirm: true})));
    }
    if (k.stage === 'production') {
      const form = Forms.create();
      const to = h('select', {}, ['validated', 'repeated', 'candidate', 'measured'].map((x) => h('option', {value: x}, STAGE[x])));
      acts.push(decision('Понизить вручную', [form.add('to', 'Новая стадия', to, {required: true}),
        form.add('why', 'Причина', h('input', {placeholder: 'причина'}), {raw: true, help: 'необязательно; без причины в истории будет «manual demotion»'})],
      (v) => post(`/knowledge/${kid}/demote`, {confirm: true, to_stage: v.to, reason: v.why}), 'danger', form));
    }
    if (k.counted_from) {
      acts.push(decision('Отменить «с последней гравировки»', [h('p', {}, 'Старые гравировки этого рецепта снова будут считаться; знание, выводы и работы '
        + 'пересчитаются.')], () => post(`/exclusions/${k.counted_from.id}/revoke`, {})));
    }
    if (k.questioned) {
      acts.push(decision('Подтвердить запись', [h('div', {class: 'alert warn'}, I18N.tr(k.doubt.reason)),
        SourceRefs.observations(k.doubt.observation_ids)], () => post(`/knowledge/${kid}/confirm-questioned`)));
    }
    return acts;
  }

  /** The operator's «Считать с последней гравировки» on this recipe (act-on-findings REQ-002): which engraving it counts from, how many older
      ones do not count. */
  function countedFrom(x) {
    const kept = x.kept || {};
    const at = (iso) => (iso ? new Date(iso).toLocaleDateString('ru-RU') : '—');
    const photos = kept.pair_ids || [];
    const long = photos.length > SourceRefs.SHORT;                 // a few photographs are named in the sentence; many are a count with a list (ux-growing-collections-p0 REQ-002)
    return h('div', {class: 'alert warn small'}, `Считается с гравировки${kept.title ? ` «${kept.title}»` : ''} от ${at(kept.when)}`
      + (photos.length && !long ? ` (фото № ${photos.join(', ')})` : '') + `; старых не считается: ${(x.engraving_ids || []).length}. `
      + `Решение оператора от ${at(x.created_at)}` + (x.note ? `: «${x.note}»` : '') + '.',
    long ? SourceRefs.photos(photos, {label: 'Фото этой гравировки'}) : null);
  }

  async function render(kid) {
    const k = await get('/knowledge/' + kid + '?history_limit=0');          // the events come a page at a time from the list below, not all with the entry
    const s = k.summary;
    const history = KnowledgeHistory.list(kid, {labels: {STAGE, EVENT}, stage: k.stage});
    await history.ready;
    const back = `/colors?device=${k.device_id}&lens=${App.lensParam(k.lens_id)}`;
    const ids = s ? s.observation_ids : [];
    return h('div', {class: 'os kn'},
      h('div', {class: 'os-head'}, h('a', {class: 'btn btn-small', href: '#' + back}, '← К модели цвета'), h('h2', {}, 'Знание о цвете'), pill(STAGE[k.stage], k.stage === 'production' ? 'ok' : ''),
        h('span', {class: 'spacer'}), h('a', {class: 'btn btn-small', href: `#/setup?tab=rules&device=${k.device_id}&lens=${App.lensParam(k.lens_id)}`}, 'Правила оценки')),
      k.questioned ? h('div', {class: 'alert bad kn-alert'}, [h('strong', {}, 'Под вопросом. '), I18N.tr(k.doubt.reason)]) : null,
      h('div', {class: 'os-body kn-body'},
        h('section', {class: 'os-col'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Сведения')),
          h('div', {class: 'os-scroll stack'}, facts([
            ['Стадия', pill(STAGE[k.stage], k.stage === 'production' ? 'ok' : '')],
            ['Параметры', params(k.parameters) + ` · импульс ${k.parameters.pulse_width} · интервал ${k.parameters.line_interval} · проходов ${k.parameters.passes}`]]),
          // REQ-001 of ux-evidence-summaries-p0: the colour and how far it is trusted on the first level (every observation of an entry is
          // chart-corrected); Lab and the figures of the calculation are one fold away
          s ? EvidenceSummary.summary({...s, measurement: 'calibrated', engravings: s.independent_engravings}, {lead: swatch(s.lab)}) : null,
          EvidenceSummary.disclosure('Цифры расчёта: цвет Lab, уверенность, ожидаемая ошибка', facts([
            ['Цвет', s ? h('span', {}, swatch(s.lab), labText(s.lab)) : '—'],
            ['Независимых гравировок', s ? s.independent_engravings : '—'], ['Уверенность', s ? num(s.confidence) : '—'],
            ['Совпали по цвету', s ? App.agreed(s.agreement) + (s.caution ? ` · ${App.CAUTION[s.caution]}` : '') : '—'],
            ['Ожидаемая ошибка ΔE', s ? num(s.expected_delta_e) : '—'], ['Стабильность', s ? stab(s.stability) : '—'],
            ['Повторяемость стенда', s ? rig(s.rig_repeatability) : '—']])),
          s && s.attribution_note ? h('div', {class: 'alert warn'}, I18N.tr(s.attribution_note)) : null,
          k.counted_from ? countedFrom(k.counted_from) : null, h('div', {class: 'row'}, actions(k, kid)),
          // «знание», «стадия», «основание» through what they are for; the technical number is in the fold (ux-save-feedback-p0, REQ-003)
          h('div', {class: 'stack kn-terms'}, Terms.note('knowledge', kid), Terms.note('stage'), Terms.note('basis')))),
        h('div', {class: 'kn-right'},
          h('section', {class: 'os-col kn-history'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'История'), pill(k.history_total ?? k.history.length)), h('div', {class: 'os-scroll'}, history.el)),
          s ? h('section', {class: 'os-col kn-evidence'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Наблюдения-основания'), pill(ids.length)),
            h('div', {class: 'os-scroll'}, SourceRefs.observations(ids, {label: 'Номера наблюдений'}))) : null)));
  }
  return {render, STAGE, stab, rig, params};
})();
