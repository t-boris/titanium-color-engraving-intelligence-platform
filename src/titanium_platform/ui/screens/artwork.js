/* Цветная гравировка: сопоставление цветов рисунка с валидированными и производственными цветами титана (REQ-004, DEC-009).
   Недостижимый цвет нужно заменить или исключить: пока он есть, план создать нельзя. Недостижимые цвета сами
   становятся целями планировщика. Форма и окна — artwork-start.js. */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, post, patch, put, fail, go, table, num, labText, swatch} = App;
  const {startForm, replaceDialog, questionedDialog} = ArtworkParts;
  const STATUS = {matched: ['Сопоставлен', 'ok'], unreachable: ['Недостижим', 'bad'], replaced: ['Заменён вручную', 'ok'], excluded: ['Исключён', '']};

  App.register({id: 'artwork', async render(ctx) {
    const id = ctx.query.plan || ctx.query.id;
    if (!id) {
      const lists = await App.hardwareLists();
      if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте лазер'), link('/devices', 'Лазеры'));
      return h('div', {class: 'stack'}, h('h2', {}, 'Цветная гравировка'), startForm(lists, ctx));
    }
    const reload = () => App.render();
    const plan = await get('/plans/' + id), palette = await get(`/discrete/${id}/palette`);
    const unresolved = plan.matches.filter((m) => m.status === 'unreachable').length;
    const active = plan.matches.filter((m) => m.status === 'matched' || m.status === 'replaced').length;
    const thr = h('input', {type: 'number', step: 'any', min: '0', value: plan.threshold, 'aria-label': 'Порог ΔE'});
    const rows = plan.matches.map((m) => {
      const [label, kind] = STATUS[m.status];
      // the titanium colour the match was tested against, with its three estimates (REQ-002, REQ-004): carried by the match;
      // a plan matched before the match carried them takes them from the palette entry
      const entry = palette.find((x) => x.id === (m.knowledge_id ?? m.candidate_id));
      const t = m.titanium || (entry ? {lab: entry.lab, confidence: entry.confidence, expected_delta_e: entry.expected_delta_e, stability: entry.stability} : null);
      const back = btn('Вернуть в сопоставление', async () => {
        const rep = Object.fromEntries(Object.entries(plan.replacements).filter(([k]) => k !== m.source_key));
        await patch('/discrete/' + id, {exclusions: plan.exclusions.filter((k) => k !== m.source_key), replacements: rep}); reload();
      });
      const act = m.status === 'excluded' ? back : h('span', {class: 'row'}, btn('Заменить', () => replaceDialog(plan, m, palette, reload)),
        btn('Исключить', async () => { await patch('/discrete/' + id, {exclusions: [...plan.exclusions, m.source_key]}); reload(); }));
      const shown = t && m.status !== 'excluded';
      return [h('span', {}, swatch(m.source_lab), labText(m.source_lab)), pill(label, kind),
        shown ? h('span', {}, m.status === 'unreachable' ? 'ближайший: ' : '', swatch(t.lab), labText(t.lab)) : '—',
        m.distance == null ? '—' : num(m.distance), shown ? num(t.expected_delta_e) : '—',
        m.match_error == null ? '—' : h('span', {}, num(m.match_error), m.match_error > plan.threshold ? ` > ${plan.threshold}` : ` ≤ ${plan.threshold}`),
        shown ? num(t.confidence) : '—', shown ? (t.stability.assessed ? 'дисперсия ' + num(t.stability.variance) : 'не оценена') : '—', act];
    });
    const markerBtn = btn(plan.markers_enabled ? 'Выключить регистрационные маркеры' : 'Включить регистрационные маркеры',
      async () => { try { await put(`/plans/${id}/markers`, {enabled: !plan.markers_enabled}); reload(); } catch (e) { fail(e); } });
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Цветная гравировка · ' + plan.name),
        h('p', {class: 'sub'}, `Текущий порог ΔE: ${plan.threshold}. Он сравнивается с суммой расстояния до цели и ожидаемой ошибки записи (DEC-030).`)),
      h('span', {class: 'spacer'}), link(`/designer?device=${plan.device_id}&lens=${App.lensParam(plan.lens_id)}`, 'Цели экспериментов')),
      palette.length ? null : h('div', {class: 'alert warn'}, 'Нет валидированных или производственных цветов для этого лазера с этой линзой: все цвета недостижимы.'),
      h('div', {class: 'card toolbar'}, field('Порог ΔE', thr),
        btn('Сопоставить цвета', async () => { try { await patch('/discrete/' + id, {threshold: +thr.value}); reload(); } catch (e) { fail(e); } }),
        btn('Включить параметры под вопросом в этот план', () => questionedDialog(plan, reload)), markerBtn),
      h('div', {class: 'card'}, h('h3', {}, 'Цвета рисунка'),
        h('p', {class: 'muted small'}, `Ожидаемая ошибка совпадения = ΔE до цели + ожидаемая ошибка записи титана; цвет сопоставлен, если она не больше порога ${plan.threshold}.`),
        table(['Исходный цвет', 'Статус', 'Цвет титана', 'ΔE до цели', 'Ожидаемая ошибка записи', 'Ожидаемая ошибка совпадения', 'Уверенность', 'Стабильность', ''], rows)),
      // картина плана перерисовывается после каждого сопоставления: адрес меняется вместе с решениями по цветам
      h('div', {class: 'card stack'}, h('h3', {}, 'Рисунок в цветах титана'), h('div', {class: 'grid g2'},
        h('figure', {}, h('img', {src: `/api/plans/${id}/source-image`, style: 'width:100%', alt: 'Исходное изображение'}), h('figcaption', {class: 'muted small'}, 'Исходное изображение')),
        h('figure', {}, h('img', {src: `/api/plans/${id}/banding.png?v=${encodeURIComponent(plan.matches.map((m) => `${m.status}${m.knowledge_id}`).join('.'))}`,
          style: 'width:100%;image-rendering:pixelated', alt: 'Рисунок в сопоставленных цветах титана'}),
          h('figcaption', {class: 'muted small'}, 'Сопоставленные цвета титана; недостижимые заштрихованы красным, исключённые — белые')))),
      unresolved ? h('div', {class: 'alert bad'}, `Нерешённые цвета: ${unresolved}. Замените или исключите каждый: создание плана отключено. Они уже переданы планировщику как цели.`) : null,
      active === 0 && !unresolved ? h('div', {class: 'alert warn'}, 'Все области исключены: создание отключено.') : null,
      h('div', {class: 'row'}, btn('Создать план', async (ev) => {
        const self = ev.currentTarget;
        self.disabled = true;
        try { await post(`/discrete/${id}/finalize`); go('/plans/' + id); } catch (e) { fail(e); self.disabled = false; }
      }, 'primary', unresolved > 0 || active === 0)));
  }});
})();
