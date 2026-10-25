/* Выводы (REQ-022): что показала накопленная работа и что проверить дальше. Вопрос оператора к экрану — «что изменилось
   и где не хватает данных?». Каждый вывод показывает основания со ссылками, лазер с линзой, титан и задачу, число
   независимых гравировок и фотографий, неопределённость и ясную пометку: измерено, исследовательская аномалия или гипотеза AI.
   История вывода — тот же вывод в прежних расчётах; прежние расчёты не меняются.
   The findings are a short list (findings-you-can-manage-short-lists-re-check, REQ-002, REQ-003): one line per finding, opened on
   «Требуют внимания»; a finding can be acknowledged, hidden, pinned to the top and given a note. «Учтено» and «скрыто» hold while the
   finding has no new data (DEC-001). Photo engraving is a tab of its own.
   «Перепроверить все работы» (REQ-004, DEC-089): a full backup, every accepted photograph measured again, the findings drawn once; the
   progress on the screen, a stop between photographs, the report of the last re-check (after a restart too).
   Acting on a finding (act-on-findings): an opened finding of the latest run starts with «Что сделать» — take the measurement out,
   measure its photograph again, count the recipe from its newest engraving, confirm a questioned entry; each decision shows what it
   changes first, and «Убрано оператором N» lists the decisions with «Вернуть».
   Адрес: #/findings?run=&state=&kind=&task=&setup=&material=&sort=&tab=&finding= */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, post, put, toast, fail, num, labText, swatch, facts} = App;
  const KINDS = ['improvement', 'unstable', 'anomaly', 'gap', 'hypothesis'];
  const KIND = {improvement: 'Улучшения', unstable: 'Нестабильность', anomaly: 'Аномалии', gap: 'Пробелы', hypothesis: 'Гипотезы AI'};
  const KIND_ONE = {improvement: 'Улучшение', unstable: 'Нестабильно', anomaly: 'Аномалия', gap: 'Пробел', hypothesis: 'Гипотеза AI'};
  const BASIS = {measured: ['Измерено', 'ok'], exploratory: ['Исследовательская аномалия, не вывод', 'warn'],
    hypothesis: ['Гипотеза AI, не измерение', 'bad']};
  const TRIGGER = {acceptance: 'после принятия фотографии', manual: 'по кнопке', schedule: 'по расписанию', recheck: 'после перепроверки всех работ',
    operator: 'после решения оператора'};
  const STATES = [['attention', 'Требуют внимания'], ['acknowledged', 'Учтённые'], ['hidden', 'Скрытые']];
  const SORTS = [['important', 'Сначала важные'], ['newest', 'Сначала новые'], ['delta', 'Больший ΔE'], ['setup', 'По лазеру и титану']];
  const STAGE = {measured: 'измерено', candidate: 'кандидат', repeated: 'повторено', validated: 'валидировано', production: 'производственное'};
  const when = (iso) => (iso ? new Date(iso).toLocaleString('ru-RU', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—');
  const taskName = (t) => (t ? Tasks.name(t) : 'задача не определена');     // задачи — общий словарь (REQ-020, tasks.js)
  let goalNames = {};                     // цели руководства (/application-goals): задача исследования AI по-русски
  const stockName = (s) => (s ? [s.name, s.grade, s.batch].filter(Boolean).join(' · ') || 'титан без названия' : 'титан не указан');
  const setupName = (c) => `${c.device || 'лазер № ' + c.device_id} · ${App.lensLabel(c.lens)}`;
  const settings = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 0)} кГц · ${num(p.speed, 0)} мм/с · ${num(p.pulse_width, 0)} нс · шаг ${num(p.line_interval, 4)} мм · ${p.passes ?? '—'} пр.`;
  const designerRoute = (deviceId, lensId, proposalId) => `/designer?device=${deviceId}&lens=${App.lensParam(lensId)}${proposalId ? '&proposal=' + proposalId : ''}`;

  function samples(s) {
    if (!s) return '—';
    const parts = [];
    if (s.recipes != null) parts.push(`рецептов: ${s.recipes}`);
    if (s.independent_engravings != null) parts.push(`независимых гравировок: ${s.independent_engravings}`);
    if (s.photographs != null) parts.push(`фотографий: ${s.photographs}`);
    if (s.observations != null) parts.push(`наблюдений: ${s.observations}`);
    return parts.join(' · ') || '—';
  }

  function uncertainty(f) {
    const u = f.uncertainty || {};
    if (f.basis === 'hypothesis') return `не измерена; уверенность, которую дал AI: ${u.ai_confidence === 'candidate' ? 'кандидат' : 'гипотеза'}`;
    if (f.subkind === 'coverage') return 'данных нет';
    if (u.expected_delta_e != null) {
      return `ожидаемая ошибка ΔE ${num(u.expected_delta_e)} · дисперсия ${num(u.variance)} ΔE² · доверие ${num(u.confidence)}`
        + (u.rig_mean_delta_e != null ? ` · повторяемость стенда ΔE ${num(u.rig_mean_delta_e)}` : '');
    }
    if (u.delta_e != null) return `ближайшее измерение ΔE ${num(u.delta_e, 1)} · ` + (u.tolerance != null ? `допуск ${u.tolerance}` : 'допуск не сохранён');
    if (f.subkind === 'target_missing') return 'не оценена: сравнимых измерений цели ещё нет';
    return 'не оценена: меньше двух независимых гравировок';
  }

  /** Что сравнивает вывод — по его виду. */
  function compares(f) {
    const c = f.compares || {};
    switch (f.subkind) {
      case 'error_reduced': return `С расчётом № ${c.previous_run_id}: ожидаемая ошибка ΔE ${num(c.before.expected_delta_e)} → ${num(c.after.expected_delta_e)}, `
        + `независимых гравировок ${c.before.independent_engravings} → ${c.after.independent_engravings}`;
      case 'validated': return `Стадия «${STAGE[c.stage] || c.stage}»${c.since ? ' с ' + when(c.since) : ''}; критерии: повторов ${c.repeat_threshold ?? '—'}, `
        + `допуск ΔE ${c.delta_tolerance ?? '—'}, порог дисперсии ${c.variance_threshold ?? '—'}`;
      case 'variance': return `Дисперсия повторов ${num(c.variance)} ΔE² против сохранённого порога ${c.variance_threshold}`;
      case 'questioned': return `Стадия «${STAGE[c.stage] || c.stage}»; наблюдения, вызвавшие сомнение: ${(c.doubt_observation_ids || []).join(', ') || '—'}`;
      case 'observation': return [h('span', {}, swatch(c.observation_lab), ' наблюдение ', labText(c.observation_lab)), ' против ',
        h('span', {}, swatch(c.reference_lab), c.rule === 'tolerance' ? ' среднее рецепта ' : ' среднее других гравировок ', labText(c.reference_lab)),
        ` · ΔE ${num(c.delta_e, 1)} · ` + (c.rule === 'tolerance' ? `допуск ${c.tolerance}` : `3σ = ${num(3 * c.sd)} ΔE`)];
      case 'target_reached':
      case 'target_missing': return [h('span', {}, swatch(c.target_lab), ' цель ', labText(c.target_lab)),
        c.closest_lab ? h('span', {}, ' · ближайшее измерение ', swatch(c.closest_lab), labText(c.closest_lab), ` · ΔE ${num(c.delta_e, 1)}`) : ' · сравнимых измерений нет',
        c.tolerance != null ? ` · допуск ${c.tolerance}` : ' · допуск не сохранён'];
      case 'coverage': {
        const names = c.names || {stocks: {}, lenses: {}};
        const stocks = c.stocks_with_this_task.map((id) => stockName(names.stocks[id]));
        const lenses = c.lenses_with_this_task.map((id) => App.lensLabel(names.lenses[id]));
        return `На этом титане с этим лазером и линзой есть: ${c.tasks_on_this_stock.map(taskName).join(', ') || 'ничего'}; эта задача есть `
          + (stocks.length ? `на заготовках: ${stocks.join(', ')}` : 'ни на одной другой заготовке') + (lenses.length ? ` и с линзами: ${lenses.join(', ')}` : '');
      }
      case 'single_engraving': return (c.engravings_needed_for_validation == null ? 'Сколько гравировок нужно для валидации, не задано: критерии не согласованы'
        : `Для валидации нужно ещё независимых гравировок: ${c.engravings_needed_for_validation}`) + ` · можно повторить на плате: ${c.repeatable_keys.length} из ${c.recipes.length}`;
      case 'insight': return `Сохранено AI-исследователем ${when(c.saved_at)} · задача исследования: ${goalNames[c.purpose] || c.purpose}`;
      default: return null;
    }
  }

  function evidence(f) {
    const e = f.evidence || {};
    const links = [];
    const pairs = e.pair_ids || [];
    pairs.slice(0, 12).forEach((id) => links.push(link('/analysis/' + id, 'фото № ' + id)));
    if (pairs.length > 12) links.push(h('span', {class: 'muted'}, `и ещё ${pairs.length - 12}`));
    if (e.knowledge_id) links.push(link('/knowledge/' + e.knowledge_id, 'знание № ' + e.knowledge_id));
    (e.knowledge_ids || []).slice(0, 8).forEach((id) => links.push(link('/knowledge/' + id, 'знание № ' + id)));
    if (e.target_id != null) links.push(link(designerRoute(f.device_id, f.lens_id), 'цель № ' + e.target_id));
    if (e.plan_id) links.push(link('/plans/' + e.plan_id, 'исходная работа цели'));
    if (e.proposal_id) links.push(link(designerRoute(f.device_id, f.lens_id, e.proposal_id), 'предложение № ' + e.proposal_id));
    if (e.session_id) links.push(link('/research/' + e.session_id, 'исследование № ' + e.session_id));
    const obs = e.observation_ids || [];
    return h('div', {class: 'row small'}, h('span', {class: 'muted'}, 'Основания:'),
      links.length ? links : h('span', {class: 'muted'}, 'принятых записей нет'),
      obs.length ? h('span', {class: 'muted'}, `наблюдения № ${obs.slice(0, 8).join(', ')}${obs.length > 8 ? ` … (всего ${obs.length})` : ''}`) : null);
  }

  /** Тот же вывод во всех расчётах, где он был; подряд идущие одинаковые объединены. */
  function historyBlock(f) {
    const body = h('div', {class: 'small'}, h('p', {class: 'muted'}, 'Загружаем…'));
    const details = h('details', {}, h('summary', {}, 'История вывода по расчётам'), body);
    details.addEventListener('toggle', async () => {
      if (!details.open || details.dataset.loaded) return;
      details.dataset.loaded = '1';
      try {
        const rows = [];
        for (const x of await get(`/analysis/findings/${f.id}/history`)) {
          const last = rows[rows.length - 1];
          if (last && last.kind === x.kind && last.statement === x.statement) last.runs.push(x);
          else rows.push({kind: x.kind, statement: x.statement, runs: [x]});
        }
        App.fill(body, App.table(['Расчёты', 'Вид', 'Вывод'], rows.map((r) => {
          const first = r.runs[r.runs.length - 1], last = r.runs[0];
          return [r.runs.length === 1 ? `№ ${last.run_id} · ${when(last.run_at)}` : `№ ${first.run_id}–${last.run_id} · ${when(first.run_at)} — ${when(last.run_at)} (${r.runs.length})`,
            KIND_ONE[r.kind] || r.kind, I18N.tr(r.statement)];
        }), 'Истории нет', true));
      } catch (e) { App.fill(body, h('div', {class: 'alert bad'}, e.message)); }
    });
    return details;
  }

  function proposeButton(f) {
    if (f.kind !== 'gap' || !f.proposable) return null;
    return btn('Предложить эксперимент', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const p = await post(`/analysis/findings/${f.id}/proposal`, {});
        toast(`Предложение № ${p.id} готово`, 'ok');
        App.go(designerRoute(p.device_id, p.lens_id, p.id));
      } catch (e) { fail(e); self.disabled = false; }
    }, 'primary btn-small');
  }

  function findingCard(f) {
    const [basis, basisKind] = BASIS[f.basis] || [f.basis, ''];
    const c = f.context || {};
    const recipe = f.recipe && f.recipe.lab ? h('p', {class: 'small'}, swatch(f.recipe.lab), ' ', labText(f.recipe.lab), ' · ', settings(f.recipe.parameters)) : null;
    return h('article', {class: 'stack finding'},
      h('div', {class: 'row'}, pill(KIND_ONE[f.kind] || f.kind), pill(basis, basisKind), f.new ? pill('новое в этом расчёте', 'ok') : null,
        h('span', {class: 'spacer'}), proposeButton(f)),
      h('p', {}, h('strong', {}, I18N.tr(f.statement))),
      recipe,
      facts([['Лазер и линза', setupName(c)], ['Титан', stockName(c.stock)], ['Задача', taskName(f.task)], ['Образцы', samples(f.samples)],
        ['Неопределённость', uncertainty(f)], ['Сравнивает', compares(f)]]),
      (f.limitations || []).length ? h('ul', {class: 'small muted'}, f.limitations.map((l) => h('li', {}, I18N.tr(l)))) : null,
      evidence(f), historyBlock(f));
  }

  // -- the operator's marks (REQ-003): «Учтено», «Скрыть» / «Вернуть», «Закрепить», a note; ``done`` reads the findings again
  const mark = (f, action, note) => post(`/analysis/findings/${f.id}/mark`, note === undefined ? {action} : {action, note});
  const DONE = {acknowledge: 'Отмечено «учтено»: вывод вернётся в «Требуют внимания», когда у него появятся новые данные.',
    hide: 'Скрыто до новых данных: вывод можно найти в «Скрытых».', reopen: 'Вывод снова требует внимания.'};
  function markButtons(f, done, openNote) {
    const act = (action, text) => btn(text, async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { await mark(f, action); if (DONE[action]) toast(DONE[action], 'ok'); await done(); }
      catch (e) { fail(e); self.disabled = false; }
    }, 'btn-small');
    return [f.state === 'attention' ? act('acknowledge', 'Учтено') : act('reopen', 'Вернуть'),
      f.state !== 'hidden' ? act('hide', 'Скрыть') : null,
      btn('Заметка', () => openNote(), 'btn-small'),
      act(f.mark.pinned ? 'unpin' : 'pin', f.mark.pinned ? 'Открепить' : 'Закрепить')];
  }

  function markBlock(f, done) {
    const m = f.mark;
    const was = m.status === 'hidden' ? 'скрыт' : 'отмечен «учтено»';
    const status = m.changed ? `Был ${was} ${when(m.status_at)}; с тех пор появились новые данные, вывод снова требует внимания.`
      : m.status ? `${m.status === 'hidden' ? 'Скрыт' : 'Отмечен «учтено»'} ${when(m.status_at)}: вернётся, когда появятся новые данные.` : null;
    const note = h('textarea', {rows: '2', maxlength: '2000', placeholder: 'Что сделано, что проверить…'});
    note.value = m.note || '';
    const save = btn('Сохранить заметку', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { await mark(f, 'note', note.value); toast('Заметка сохранена', 'ok'); await done(); }
      catch (e) { fail(e); self.disabled = false; }
    }, 'btn-small');
    return h('div', {class: 'stack fd-mark'}, status ? h('p', {class: 'small muted'}, status) : null,
      h('div', {class: 'toolbar'}, field('Заметка оператора', note), save));
  }

  // -- what can be done about a finding (act-on-findings REQ-001..REQ-004) ---------------------------------------------------
  const REMEDY = {
    exclude_measurement: ['Убрать измерение', 'Этот слой этой фотографии перестанет считаться в рецепте, на карте цветов, в палитре и в работах. '
      + 'Фотография и её другие слои остаются; «Вернуть» отменит.'],
    remeasure: ['Перемерить фото', 'Измерить фотографию заново так, как приложение измеряет сейчас (около полуминуты). Если новое измерение '
      + 'не получится целиком, останется старое.'],
    count_from_latest: ['Считать с последней гравировки', 'Цвет рецепта — по самой новой гравировке. Старые остаются в истории, но не считаются; '
      + 'гравировки, сделанные позже, считаются как обычно.'],
    confirm_questioned: ['Подтвердить запись', 'Снять с записи знания пометку «под вопросом»: стадия не меняется.'],
  };
  const DECIDED = {exclude_measurement: 'измерение убрано из расчёта', count_from_latest: 'рецепт считается с последней гравировки'};
  const layerName = (name, index) => (name ? `«${I18N.name(name)}»` : `№ ${index}`);
  const engravingText = (e) => `${e.title || 'гравировка'} · ${when(e.when)} · фото № ${e.pair_ids.join(', ')}`;

  /** The recipe's colour before and after a decision, as the knowledge will derive it. */
  function colourChange(p) {
    const side = (c) => (c ? h('span', {}, swatch(c.lab), labText(c.lab), ` · гравировок: ${c.engravings}`)
      : h('span', {class: 'muted'}, 'измерений в рецепте не останется'));
    return h('div', {class: 'stack small fd-change'}, h('strong', {}, 'Цвет рецепта'), h('div', {}, 'сейчас: ', side(p.before)),
      h('div', {}, 'станет: ', side(p.after)), p.delta_e != null ? h('div', {class: 'muted'}, `сдвиг ΔE ${num(p.delta_e, 1)}`) : null);
  }

  /** What leaves the calculation: one layer of one photograph, or the older engravings of a recipe. */
  function leaving(p) {
    if (p.action === 'exclude_measurement') {
      const o = p.observation;
      return h('p', {}, 'Перестанет считаться: ', link('/analysis/' + o.pair_id, `фото № ${o.pair_id}`), `, слой ${layerName(o.layer_name, o.layer_index)} `,
        h('span', {}, swatch(o.lab), labText(o.lab)));
    }
    return h('div', {class: 'stack small'}, h('div', {}, 'Останется: ', swatch(p.kept.lab), ' ', engravingText(p.kept)),
      h('div', {}, `Перестанут считаться (${p.older.length}):`),
      h('ul', {}, p.older.slice(0, 6).map((e) => h('li', {}, swatch(e.lab), ' ', engravingText(e)))),
      p.older.length > 6 ? h('div', {class: 'muted'}, `и ещё ${p.older.length - 6}`) : null);
  }

  /** «Вернуть»: the measurements of a decision count again; the screen is drawn again with the new run. */
  async function revoke(id) {
    try {
      const r = await post(`/exclusions/${id}/revoke`, {});
      toast('Снова считается' + (r.run_id ? ` · расчёт № ${r.run_id}` : ''), 'ok');
      App.render({preserveScroll: true});
    } catch (e) { fail(e); }
  }

  /** A decision: what it changes first (REQ-004), a note, then the decision and the screen with the new run and «Вернуть». */
  async function decide(f, action) {
    const preview = await post(`/analysis/findings/${f.id}/remedy`, {action});
    const note = h('textarea', {rows: '2', maxlength: '2000', placeholder: 'Почему (необязательно)'});
    App.modal(REMEDY[action][0] + '?', h('div', {class: 'stack fd-remedy-preview'}, leaving(preview), colourChange(preview),
      h('p', {class: 'muted small'}, 'Сами измерения не меняются: решение хранится отдельно, «Вернуть» его отменит. После решения пересчитаются '
        + 'знание, выводы и работы.'), field('Заметка', note)),
    [{label: 'Отмена', run: (m) => m.close()},
      {label: REMEDY[action][0], cls: 'primary', run: async (m) => {
        const r = await post(`/analysis/findings/${f.id}/remedy`, {action, note: note.value, confirm: true});
        m.close();
        toast([`Готово · ${DECIDED[action]}${r.run_id ? ` · расчёт № ${r.run_id}` : ''} `, btn('Вернуть', () => revoke(r.exclusion.id), 'btn-small')], 'ok');
        App.render({preserveScroll: true});
      }}]);
  }

  /** «Перемерить фото» from the finding (REQ-003): busy while it measures, then every layer's colour before and after (the finding's layer
      first), or why the old measurement was kept; the screen is drawn again when the result is closed. */
  async function remeasure(f, pairId, control) {
    control.disabled = true;
    control.textContent = 'Перемеряю… (около полуминуты)';
    let out;
    try { out = await post(`/pairs/${pairId}/remeasure`); }
    catch (e) { fail(e); control.disabled = false; control.textContent = REMEDY.remeasure[0]; return; }
    const own = f.kind === 'anomaly' ? Number(String(f.key).split(':')[3]) : null;
    const body = out.status !== 'replaced' ? h('p', {}, 'Прежнее измерение оставлено: ' + I18N.tr(out.reason || ''))
      : h('div', {class: 'stack'}, h('p', {}, `Фото № ${pairId} перемерено; новое измерение — `, link('/analysis/' + out.replaced_by, `фото № ${out.replaced_by}`), '.'),
        App.list({items: out.layers, key: (l) => String(l.layer_index), className: 'fd-remeasured',
          row: (l) => [l.layer_index === own ? pill('этот вывод', 'warn') : null, h('span', {class: 'lst-text'}, `Слой ${layerName(l.name, l.layer_index)}`),
            l.before ? swatch(l.before) : null, '→', l.after ? swatch(l.after) : null,
            h('span', {class: 'small'}, l.delta_e != null ? `ΔE ${num(l.delta_e, 1)}` : 'нет пары')],
          details: (l) => facts([['Было', l.before ? labText(l.before) : '—'], ['Стало', l.after ? labText(l.after) : '—']]),
          sorts: [['delta', 'Больший сдвиг', (a, b) => (b.layer_index === own) - (a.layer_index === own) || (b.delta_e ?? -1) - (a.delta_e ?? -1)],
            ['order', 'По порядку слоёв', (a, b) => a.layer_index - b.layer_index]]}).el);
    App.modal(out.status === 'replaced' ? 'Фото перемерено' : 'Фото не перемерено', body, [{label: 'Закрыть', run: (m) => m.close()}],
      () => App.render({preserveScroll: true}));
  }

  /** «Подтвердить запись» of a questioned knowledge entry, then a new run so the finding goes. */
  function confirmEntry(kid) {
    App.modal('Подтвердить запись?', h('p', {}, `Запись знания № ${kid} перестанет быть «под вопросом»; стадия не меняется. `, link('/knowledge/' + kid, 'Открыть запись')),
      [{label: 'Отмена', run: (m) => m.close()},
        {label: 'Подтвердить', cls: 'primary', run: async (m) => {
          await post(`/knowledge/${kid}/confirm-questioned`, {});
          const r = await post('/analysis/runs');
          m.close();
          toast(`Запись подтверждена · расчёт № ${r.id}`, 'ok');
          App.render({preserveScroll: true});
        }}]);
  }

  /** «Что сделать»: one button per remedy the finding offers, each with a line on what it does; nothing for a finding with none. */
  function remedyBlock(f) {
    const offered = (f.remedies || []).filter((r) => REMEDY[r.action]);
    if (!offered.length) return null;
    const button = (r) => btn(REMEDY[r.action][0], async (ev) => {
      const self = ev.currentTarget;
      if (r.action === 'remeasure') { await remeasure(f, r.pair_id, self); return; }
      self.disabled = true;
      try { if (r.action === 'confirm_questioned') confirmEntry(r.knowledge_id); else await decide(f, r.action); }
      catch (e) { fail(e); } finally { self.disabled = false; }
    }, 'btn-small');
    return h('div', {class: 'stack fd-remedies'}, h('h4', {}, 'Что сделать'),
      offered.map((r) => h('div', {class: 'fd-remedy'}, button(r), h('span', {class: 'muted small'}, REMEDY[r.action][1]))));
  }

  /** «Убрано оператором N» (REQ-005): the decisions in force as a short list, each with «Вернуть»; nothing when there is none. */
  function exclusionsBlock(x) {
    if (!x || !x.active) return null;
    const what = (e) => (e.kind === 'measurement'
      ? `Измерение: фото № ${e.pair_id ?? e.original_pair_id}, слой ${layerName((e.observation || {}).layer_name, e.layer_index)}`
      : `Рецепт ${settings(e.settings || {})} — с последней гравировки${e.kept && e.kept.title ? ` «${e.kept.title}»` : ''}`);
    const shown = (e) => (e.kind === 'measurement' ? (e.observation || {}).lab : (e.after || {}).lab);
    const list = App.list({items: x.exclusions, key: (e) => String(e.id), search: (e) => `${what(e)} ${e.note || ''}`,
      row: (e) => [shown(e) ? swatch(shown(e)) : null, h('span', {class: 'lst-text', title: what(e)}, what(e)), h('span', {class: 'muted small'}, when(e.created_at)),
        e.note ? h('span', {class: 'muted small fd-note', title: e.note}, '✎ ' + e.note) : null],
      details: (e) => h('div', {class: 'stack small'}, facts([['Что не считается', what(e)],
        ['Наблюдений вне расчёта', String(e.observations_out ?? '—')],
        ['Цвет рецепта при решении', [e.before ? h('span', {}, swatch(e.before.lab), ' ', labText(e.before.lab)) : '—', ' → ',
          e.after ? h('span', {}, swatch(e.after.lab), ' ', labText(e.after.lab)) : 'измерений не осталось']],
        ['Решение', when(e.created_at)], ['Заметка', e.note || '—']]),
        e.kind === 'measurement' && e.pair_id ? h('p', {}, link('/analysis/' + e.pair_id, 'Открыть фото')) : null),
      actions: (e) => [btn('Вернуть', () => revoke(e.id), 'btn-small')],
      filters: [{key: 'kind', label: 'Что', options: [['measurement', 'Измерения'], ['older_engravings', 'Рецепты']], test: (e, v) => e.kind === v}],
      sorts: [['newest', 'Сначала новые', (a, b) => b.id - a.id]], className: 'fd-excluded-list'});
    return h('details', {class: 'card fd-fold fd-excluded'}, h('summary', {}, `Убрано оператором: ${x.active}`), list.el);
  }

  /** One line of the list: pinned, kind, the statement, laser and titanium, ΔE, new or changed, its mark, a note. */
  function row(f) {
    const c = f.context || {};
    return [f.mark.pinned ? h('span', {title: 'Закреплён наверху', 'aria-label': 'Закреплён наверху'}, '📌') : null,
      h('span', {class: 'fd-kind fd-' + f.kind}, KIND_ONE[f.kind] || f.kind),
      h('span', {class: 'lst-text', title: I18N.tr(f.statement)}, I18N.tr(f.statement)),
      h('span', {class: 'muted small fd-where'}, `${c.device || 'лазер № ' + f.device_id} · ${stockName(c.stock)}`),
      f.deviation != null ? h('span', {class: 'small'}, `ΔE ${num(f.deviation, 1)}`) : null,
      f.mark.changed ? pill('изменился', 'warn') : f.new ? pill('новое', 'ok') : null,
      f.state === 'hidden' ? pill('скрыт') : f.state === 'acknowledged' ? pill('учтён') : null,
      f.mark.note ? h('span', {class: 'muted small fd-note', title: f.mark.note}, '✎ ' + f.mark.note) : null];
  }

  function rulesAlerts(run) {
    const MISSING = {variance_threshold: 'порог дисперсии — нестабильность не оценивается', delta_tolerance: 'допуск ΔE — аномалии судятся по трём стандартным отклонениям, достижение целевых цветов не оценивается'};
    return (run.inputs.unset_rules || []).map((u) => h('div', {class: 'alert warn small'}, `${setupName(u)}: не сохранены ${u.missing.map((m) => MISSING[m]).join('; ')}. `,
      link('/setup', 'Правила оценки')));
  }

  function scheduleBlock(schedule) {
    const hours = h('input', {type: 'number', min: '0', step: 'any', value: schedule.interval_hours, 'aria-label': 'Интервал пересчёта, ч'});
    const state = schedule.interval_hours > 0
      ? `Включено: каждые ${schedule.interval_hours} ч. Следующий расчёт — ${when(schedule.next_due_at)}${schedule.running ? '' : ' (начнётся после перезапуска приложения)'}.`
      : 'Выключено: выводы пересчитываются после каждого принятия фотографии и по кнопке.';
    return h('div', {class: 'stack'}, h('h4', {}, 'Пересчёт по расписанию'), h('p', {class: 'muted small'}, state),
      h('div', {class: 'toolbar'}, field('Пересчитывать каждые, ч (0 — выключено)', hours),
        btn('Сохранить расписание', async (ev) => {
          const self = ev.currentTarget;
          self.disabled = true;
          try { await put('/analysis/schedule', {interval_hours: hours.value === '' ? 0 : +hours.value}); toast('Расписание сохранено', 'ok'); App.render({preserveScroll: true}); }
          catch (e) { fail(e); self.disabled = false; }
        })));
  }

  // -- «Перепроверить все работы» (REQ-004, DEC-089) ----------------------------------------------------------------------
  const RECHECK_POLL_MS = 1000;
  const RECHECK_PHASE = {backup: 'Делаю резервную копию мастерской…', analysis: 'Пересчитываю выводы…'};
  const RECHECK_END = {done: 'Перепроверка закончена', cancelled: 'Перепроверка остановлена', failed: 'Перепроверка не удалась',
    interrupted: 'Перепроверка прервана: приложение было закрыто'};
  const PHOTO = {replaced: ['заменено', 'ok'], kept: ['оставлено старое', 'warn'], failed: ['ошибка', 'bad']};
  const CHANGE = {appeared: ['появился', 'ok'], gone: ['ушёл', ''], changed: ['изменился', 'warn']};
  const mb = (bytes) => (bytes == null ? '—' : bytes >= 1024 * 1024 * 1024 ? `${(bytes / 1024 / 1024 / 1024).toFixed(1).replace('.', ',')} ГБ`
    : `${(bytes / 1024 / 1024).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0).replace('.', ',')} МБ`);
  const duration = (s) => (s < 90 ? `${Math.max(1, Math.round(s))} с` : `${Math.round(s / 60)} мин`);

  /** Ask first: how many photographs, about how long, where the backup goes and whether it fits; then start and follow. */
  function recheckButton(box) {
    return btn('Перепроверить все работы', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const p = await get('/recheck/preview');
        if (p.running) { followRecheck(box, await get('/recheck/latest')); return; }
        const short = p.free_bytes != null && p.free_bytes < p.backup_bytes;
        const body = !p.photos ? h('p', {}, 'Принятых фотографий нет: перепроверять нечего.') : h('div', {class: 'stack'},
          h('p', {}, `Все принятые фотографии (${p.photos}) будут заново измерены так, как приложение измеряет сейчас, и выводы пересчитаны один раз в конце. `
            + `Займёт примерно ${duration(p.estimate_s)}.`),
          h('p', {}, `Сначала — полная резервная копия мастерской в папку ${p.backup_dir} (${mb(p.backup_bytes)}, свободно ${mb(p.free_bytes)}): `
            + 'новое измерение заменяет старое вместе с его файлами, вернуть прежнее можно только из этой копии.'),
          h('p', {class: 'muted small'}, 'Если новое измерение фотографии не получится целиком, останется старое. Пока идёт перепроверка, фотографии нельзя '
            + 'принимать, перемерять и удалять; её можно остановить между фотографиями.'),
          short ? h('div', {class: 'alert bad'}, 'Места для резервной копии не хватает: освободите место или выберите другую папку резервных копий в разделе «Мастерская».') : null);
        App.modal('Перепроверить все работы?', body, !p.photos || short ? [{label: 'Закрыть', run: (m) => m.close()}]
          : [{label: 'Отмена', run: (m) => m.close()},
            {label: 'Перепроверить', cls: 'primary', run: async (m) => { const started = await post('/recheck', {}); m.close(); followRecheck(box, started); }}]);
      } catch (e) { fail(e); } finally { self.disabled = false; }
    }, 'btn-small');
  }

  /** A re-check running: its phase, «k из N» with the photograph being measured and the time left, a bar and «Остановить»; polled every
      second while the screen shows it (the re-check goes on when the screen is left); at the end the screen is drawn again with the report. */
  function followRecheck(box, r) {
    const fillBar = h('div', {class: 'lab-bar-fill'});
    const meter = h('div', {role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(r.total), 'aria-label': 'Перепроверка всех работ'},
      h('div', {class: 'lab-bar'}, fillBar));
    const text = h('span', {class: 'small'});
    const stopButton = btn('Остановить', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { await post(`/recheck/${r.id}/stop`, {}); toast('Перепроверка остановится после фотографии, которая сейчас измеряется', 'ok'); }
      catch (e) { fail(e); self.disabled = false; }
    }, 'btn-small');
    App.fill(box, h('div', {class: 'row'}, h('strong', {class: 'small'}, 'Перепроверка всех работ'), text, h('span', {class: 'spacer'}), stopButton), meter);
    const show = () => {
      const c = r.current;
      const left = r.done && r.total > r.done ? ` · осталось ≈ ${duration(r.elapsed_s / r.done * (r.total - r.done))}` : '';
      text.textContent = r.phase === 'remeasure'
        ? `Перемеряю фото ${Math.min(r.done + 1, r.total)} из ${r.total}` + (c ? ` · ${c.title || c.photo_name} (фото № ${c.pair_id})` : '') + left
        : RECHECK_PHASE[r.phase] || r.phase;
      const percent = r.total ? Math.round(r.done / r.total * 100) : 0;
      fillBar.setAttribute('style', `width:${percent}%`);
      meter.setAttribute('aria-valuenow', String(r.done));
    };
    const poll = async () => {
      if (!box.isConnected) return;
      try { r = await get(`/recheck/${r.id}`); } catch (e) { App.fill(box, h('div', {class: 'alert bad'}, e.message)); return; }
      if (r.status === 'running') { show(); setTimeout(poll, RECHECK_POLL_MS); return; }
      toast(RECHECK_END[r.status] || r.status, r.status === 'done' ? 'ok' : 'bad');
      App.render({preserveScroll: true});                         // the new run of conclusions and the report
    };
    show();
    setTimeout(poll, RECHECK_POLL_MS);
  }

  /** The report of the last re-check in a fold: the backup, the photographs (replaced, kept with the reason, failed; the largest colour
      change) and what changed in the findings, each as a short list. */
  function recheckReport(r, route) {
    const count = (s) => r.photos.filter((p) => p.status === s).length;
    const f = r.findings;
    const photos = App.list({items: r.photos, key: (p) => p.pair_id, search: (p) => `${p.title || ''} ${p.photo_name || ''} ${p.pair_id}`,
      row: (p) => [pill(...(PHOTO[p.status] || [p.status])), h('span', {class: 'lst-text'}, p.title || p.photo_name || `фото № ${p.pair_id}`),
        h('span', {class: 'muted small'}, `фото № ${p.pair_id}`), p.max_delta_e != null ? h('span', {class: 'small'}, `ΔE до ${num(p.max_delta_e, 1)}`) : null,
        p.changed_layers ? h('span', {class: 'muted small'}, `слоёв изменилось: ${p.changed_layers}`) : null],
      details: (p) => h('div', {class: 'stack small'}, p.reason ? h('p', {}, I18N.tr(p.reason)) : null,
        h('p', {}, link('/analysis/' + (p.replaced_by || p.pair_id), p.replaced_by ? `Новое измерение — фото № ${p.replaced_by}` : 'Открыть фото'))),
      filters: [{key: 'status', label: 'Итог', options: Object.entries(PHOTO).map(([k, [text]]) => [k, text]), test: (p, v) => p.status === v}],
      sorts: [['delta', 'Больший сдвиг цвета', (a, b) => (b.max_delta_e ?? -1) - (a.max_delta_e ?? -1)], ['order', 'По порядку', (a, b) => a.pair_id - b.pair_id]],
      empty: 'Фотографии не перемерялись.'});
    const changes = f ? [...f.appeared.map((x) => ({...x, change: 'appeared'})), ...f.gone.map((x) => ({...x, change: 'gone'})),
      ...f.changed.map((x) => ({...x, change: 'changed'}))] : [];
    const changeList = changes.length ? App.list({items: changes, key: (x) => `${x.change}:${x.id}`,
      row: (x) => [pill(...CHANGE[x.change]), h('span', {class: 'fd-kind fd-' + x.kind}, KIND_ONE[x.kind] || x.kind), h('span', {class: 'lst-text'}, I18N.tr(x.statement))],
      details: (x) => h('div', {class: 'stack small'}, x.was ? h('p', {}, `Было: ${KIND_ONE[x.was.kind] || x.was.kind} — ${I18N.tr(x.was.statement)}`) : null,
        h('p', {}, btn('Открыть вывод', () => route({finding: x.id}), 'btn-small'))),
      filters: [{key: 'change', label: 'Изменение', options: Object.entries(CHANGE).map(([k, [text]]) => [k, text]), test: (x, v) => x.change === v}]}) : null;
    const listed = f ? ['appeared', 'gone', 'changed'].filter((k) => f.counts[k] > f[k].length) : [];
    const summary = `${when(r.finished_at || r.started_at)} · ${RECHECK_END[r.status] || r.status}`
      + (r.photos.length ? ` · заменено ${count('replaced')}, оставлено старое ${count('kept')}, ошибок ${count('failed')}` : '');
    return h('details', {class: 'fd-fold'}, h('summary', {}, 'Последняя перепроверка: ' + summary),
      h('div', {class: 'stack'},
        r.error ? h('div', {class: 'alert bad'}, I18N.tr(r.error)) : null,
        facts([['Резервная копия', r.backup ? `${r.backup.path} (${mb(r.backup.bytes)})` : 'не сделана'],
          ['Фотографии', `перемерено ${r.done} из ${r.total}` + (r.elapsed_s ? ` за ${duration(r.elapsed_s)}` : '')],
          ['Выводы', f ? `расчёт № ${f.before_run_id ?? '—'} → № ${f.after_run_id}: появилось ${f.counts.appeared}, ушло ${f.counts.gone}, изменилось ${f.counts.changed}`
            : 'не пересчитаны']]),
        f ? h('div', {class: 'toolbar'}, btn('Показать выводы, требующие внимания, — сначала новые', () => route({run: '', finding: '', tab: '', state: 'attention',
          sort: 'newest', kind: '', task: '', setup: '', material: ''}), 'btn-small')) : null,
        h('h4', {}, 'Фотографии'), photos.el,
        changeList ? [h('h4', {}, 'Что изменилось в выводах'), changeList.el] : null,
        listed.length ? h('p', {class: 'muted small'}, 'Названы не все изменения: ' + listed.map((k) => `${CHANGE[k][0]} — ${f[k].length} из ${f.counts[k]}`).join(', ')) : null));
  }

  /** The run on one line, «Пересчитать сейчас»; what it read, the rules not saved, earlier runs and the schedule in a fold. */
  function runLine(run, runs, schedule, cur, route, recheckBox) {
    const recalc = btn('Пересчитать сейчас', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const r = await post('/analysis/runs');
        toast(`Расчёт № ${r.id} готов`, 'ok');
        route({run: '', finding: ''});                           // the new run is the latest
      }
      catch (e) { fail(e); self.disabled = false; }
    }, 'primary btn-small');
    const runSelect = h('select', {'aria-label': 'Расчёт', onChange: (e) => route({run: e.target.value, finding: ''})},
      h('option', {value: ''}, 'последний'), runs.map((r) => h('option', {value: r.id, selected: String(r.id) === cur.run}, `№ ${r.id} · ${when(r.at)} · ${TRIGGER[r.trigger] || r.trigger}`)));
    const alerts = run ? rulesAlerts(run) : [];
    const older = run && runs.length && runs[0].id !== run.id;
    return h('div', {class: 'card stack fd-run'},
      h('div', {class: 'row'}, run ? h('strong', {}, `Расчёт № ${run.id}`) : h('strong', {}, 'Расчётов ещё не было'),
        run ? h('span', {class: 'muted small'}, `${when(run.at)} · ${TRIGGER[run.trigger] || run.trigger}`) : null,
        older ? h('span', {class: 'small'}, pill('прежний расчёт', 'warn'), ' ', h('a', {href: '#', onClick: (e) => { e.preventDefault(); route({run: '', finding: ''}); }}, 'к последнему')) : null,
        h('span', {class: 'spacer'}), recalc, recheckButton(recheckBox)),
      run ? null : h('p', {class: 'muted small'}, 'Выводы считаются после каждого принятия фотографии; можно пересчитать и сейчас.'),
      recheckBox,
      h('details', {class: 'fd-fold'}, h('summary', {}, 'О расчёте и расписании' + (alerts.length ? ` · правила оценки не сохранены: ${alerts.length}` : '')),
        h('div', {class: 'stack'},
          run ? facts([['Входные данные', `принятых фотографий ${run.inputs.accepted_pairs} · наблюдений для модели ${run.inputs.eligible_observations} · записей знания ${run.inputs.knowledge_entries}`
            + ` · целевых цветов ${run.inputs.targets} · выводов AI ${run.inputs.insights}`],
            ['Найдено', KINDS.map((k) => `${KIND[k]}: ${run.counts[k] || 0}`).join(' · ')]]) : null,
          alerts,
          h('div', {class: 'toolbar'}, field('Показать расчёт', runSelect), h('p', {class: 'toolbar-hint'}, 'Прежние расчёты сохраняются: их выводы можно открыть и сравнить.')),
          scheduleBlock(schedule))));
  }

  /** The findings of the run as a short list read from the server page by page (REQ-002). */
  function findingsList(cur, keep) {
    const asked = {state: cur.state === 'all' ? '' : (cur.state || 'attention'), kind: cur.kind || '', task: cur.task || '', setup: cur.setup || '', material: cur.material || ''};
    return App.list({
      load: async (s) => {
        const params = Object.entries({...s.filters, sort: s.sort, offset: s.offset, limit: s.limit}).filter(([, v]) => v !== '' && v != null);
        const r = await get(`/analysis/runs/${cur.run || 'latest'}?` + new URLSearchParams(params).toString());
        return {items: r.findings, total: r.matched, counts: r.counts, options: r.options};
      },
      key: (f) => f.key, row, details: (f, list) => [remedyBlock(f), markBlock(f, list.refresh), findingCard(f)], actions: (f, list) => markButtons(f, list.refresh,
        () => list.open(f.key).then((det) => { const note = det && det.querySelector('textarea'); if (note) note.focus(); })),
      filters: [{key: 'state', label: 'Состояние', options: STATES, keepEmpty: true},
        {key: 'kind', label: 'Вид', options: KINDS.map((k) => [k, KIND[k]])},
        {key: 'task', label: 'Задача', select: true, options: (a) => ((a.options || {}).tasks || []).map((t) => [t, taskName(t)])},
        {key: 'setup', label: 'Лазер и линза', select: true, options: (a) => ((a.options || {}).setups || []).map((s) => [s.key, setupName(s)])},
        {key: 'material', label: 'Титан', select: true, options: (a) => ((a.options || {}).stocks || []).map((s) => [s.key, stockName(s.stock)])}],
      sorts: SORTS, initial: {sort: cur.sort || 'important', filters: asked},
      empty: 'Под выбранные фильтры выводов нет.', className: 'fd-list',
      onChange: (s) => keep({...s.filters, state: s.filters.state || 'all', sort: s.sort === 'important' ? '' : s.sort}),
    });
  }

  /** A finding a link opened (``?finding=<id>``, from the designer): above the list, open, whatever the filters. */
  async function linkedFinding(id, close) {
    const box = h('div', {class: 'card stack fd-linked'});
    const show = async () => {
      const f = await get(`/analysis/findings/${id}`);
      App.fill(box, [h('div', {class: 'row'}, h('h3', {}, `Вывод № ${f.id}`), h('span', {class: 'muted small'}, `из расчёта № ${f.run_id}`),
        h('span', {class: 'spacer'}), markButtons(f, show, () => box.querySelector('textarea').focus()), btn('Закрыть', () => { box.remove(); close(); }, 'btn-small')),
        remedyBlock(f), markBlock(f, show), findingCard(f)]);
    };
    try { await show(); } catch (e) { App.fill(box, h('div', {class: 'alert bad'}, e.message || String(e))); }
    return box;
  }

  /** Photo engraving on every laser and titanium where one was photographed (photo-engraving-quality): one row each, the kinds under it. */
  function photoList(photo) {
    const keyOf = (k) => `${k.device_id}/${k.lens_id}/${k.material_id}`;
    return h('div', {class: 'stack'},
      h('p', {class: 'muted small'}, 'Лучшие измеренные настройки каждого вида, что делает каждая настройка и какую плату предлагает лаборатория — по всем принятым фотографиям.'),
      App.list({items: photo, key: keyOf, open: photo.length === 1 ? keyOf(photo[0]) : null,
        row: (k) => [h('span', {class: 'lst-text'}, `${k.setup} · ${k.titanium}`),
          h('span', {class: 'muted small'}, `измерено видов: ${k.kinds.filter((x) => x.best).length} из ${k.kinds.length}`),
          k.kinds.some((x) => x.proposal) ? pill('есть предложение', 'ok') : null],
        details: (k) => h('div', {class: 'ex-insights'}, PhotoQuality.kindCards(k, {device_id: k.device_id, lens_id: k.lens_id, material_id: k.material_id})),
        sorts: [['setup', 'По лазеру и титану', (p, q) => `${p.setup} · ${p.titanium}`.localeCompare(`${q.setup} · ${q.titanium}`)]]}).el);
  }

  App.register({id: 'findings', async render(ctx) {
    const cur = {...ctx.query};
    const [runs, schedule, goals, lastRecheck, excluded] = await Promise.all([get('/analysis/runs?limit=60'), get('/analysis/schedule'), get('/application-goals'),
      get('/recheck/latest'), get('/exclusions')]);
    goalNames = Object.fromEntries(goals.map((g) => [g.id, g.name]));
    const run = cur.run ? (runs.find((r) => String(r.id) === cur.run) || await get(`/analysis/runs/${cur.run}?limit=1`).then((r) => r.run)) : runs[0] || null;
    // the list keeps its choices in the address without drawing the screen again; another run draws it again
    const address = () => '/findings?' + new URLSearchParams(Object.entries(cur).filter(([, v]) => v)).toString();
    const keep = (change) => { Object.assign(cur, change); history.replaceState(null, '', '#' + address()); };
    const route = (change) => { Object.assign(cur, change); App.go(address()); };
    let photo = [];
    try { photo = await get('/photo-knowledge/everywhere'); } catch (_) { /* the rest of the screen stands */ }
    const linked = cur.finding ? await linkedFinding(cur.finding, () => keep({finding: ''})) : null;
    const total = run ? KINDS.reduce((n, k) => n + (run.counts[k] || 0), 0) : 0;
    const recheckBox = h('div', {class: 'stack fd-recheck'});
    if (lastRecheck && lastRecheck.status === 'running') followRecheck(recheckBox, lastRecheck);
    else if (lastRecheck) App.fill(recheckBox, recheckReport(lastRecheck, route));
    const findings = h('div', {class: 'stack'}, linked,
      !run ? null : total ? findingsList(cur, keep).el : h('div', {class: 'card empty'}, 'В этом расчёте выводов нет.'));
    const tabs = photo.length ? App.tabs([['findings', 'Выводы', findings], ['photo', 'Фотогравировка', photoList(photo)]],
      {initial: cur.tab === 'photo' ? 'photo' : 'findings', label: 'Выводы', prefix: 'fd', onSelect: (id) => keep({tab: id === 'photo' ? 'photo' : ''})}) : null;
    return h('div', {class: 'stack fd-page'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Выводы'),
        h('p', {class: 'sub'}, 'Что показала накопленная работа: улучшения, нестабильность, аномалии, пробелы и гипотезы AI. Измеренное отделено от гипотез.')),
        h('span', {class: 'spacer'}), link('/designer', 'Планировщик экспериментов')),
      runLine(run, runs, schedule, cur, route, recheckBox),
      exclusionsBlock(excluded),
      tabs ? [tabs.list, ...tabs.panels] : findings);
  }});
})();
