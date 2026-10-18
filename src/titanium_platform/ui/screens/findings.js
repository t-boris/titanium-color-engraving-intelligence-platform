/* Выводы (REQ-022): что показала накопленная работа и что проверить дальше. Вопрос оператора к экрану — «что изменилось
   и где не хватает данных?». Каждый вывод показывает основания со ссылками, лазер с линзой, титан и задачу, число
   независимых гравировок и фотографий, неопределённость и ясную пометку: измерено, исследовательская аномалия или гипотеза AI.
   История вывода — тот же вывод в прежних расчётах; прежние расчёты не меняются. Адрес: #/findings?run=&kind=&task=&setup=&material= */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, post, put, toast, fail, num, labText, swatch, facts} = App;
  const KINDS = ['improvement', 'unstable', 'anomaly', 'gap', 'hypothesis'];
  const KIND = {improvement: 'Улучшения', unstable: 'Нестабильность', anomaly: 'Аномалии', gap: 'Пробелы', hypothesis: 'Гипотезы AI'};
  const KIND_ONE = {improvement: 'Улучшение', unstable: 'Нестабильно', anomaly: 'Аномалия', gap: 'Пробел', hypothesis: 'Гипотеза AI'};
  const BASIS = {measured: ['Измерено', 'ok'], exploratory: ['Исследовательская аномалия, не вывод', 'warn'],
    hypothesis: ['Гипотеза AI, не измерение', 'bad']};
  const TRIGGER = {acceptance: 'после принятия фотографии', manual: 'по кнопке', schedule: 'по расписанию'};
  const STAGE = {measured: 'измерено', candidate: 'кандидат', repeated: 'повторено', validated: 'валидировано', production: 'производственное'};
  const when = (iso) => (iso ? new Date(iso).toLocaleString('ru-RU', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—');
  const taskName = (t) => (t ? Tasks.name(t) : 'задача не определена');     // задачи — общий словарь (REQ-020, tasks.js)
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
      case 'insight': return `Сохранено AI-исследователем ${when(c.saved_at)} · задача исследования: ${c.purpose}`;
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
    return h('article', {class: 'card stack finding'},
      h('div', {class: 'row'}, pill(KIND_ONE[f.kind] || f.kind), pill(basis, basisKind), f.new ? pill('новое в этом расчёте', 'ok') : null,
        h('span', {class: 'spacer'}), proposeButton(f)),
      h('p', {}, h('strong', {}, I18N.tr(f.statement))),
      recipe,
      facts([['Лазер и линза', setupName(c)], ['Титан', stockName(c.stock)], ['Задача', taskName(f.task)], ['Образцы', samples(f.samples)],
        ['Неопределённость', uncertainty(f)], ['Сравнивает', compares(f)]]),
      (f.limitations || []).length ? h('ul', {class: 'small muted'}, f.limitations.map((l) => h('li', {}, I18N.tr(l)))) : null,
      evidence(f), historyBlock(f));
  }

  function rulesAlerts(run) {
    const MISSING = {variance_threshold: 'порог дисперсии — нестабильность не оценивается', delta_tolerance: 'допуск ΔE — аномалии судятся по трём стандартным отклонениям, достижение целевых цветов не оценивается'};
    return (run.inputs.unset_rules || []).map((u) => h('div', {class: 'alert warn small'}, `${setupName(u)}: не сохранены ${u.missing.map((m) => MISSING[m]).join('; ')}. `,
      link('/setup', 'Правила оценки')));
  }

  function scheduleCard(schedule) {
    const hours = h('input', {type: 'number', min: '0', step: 'any', value: schedule.interval_hours, 'aria-label': 'Интервал пересчёта, ч'});
    const state = schedule.interval_hours > 0
      ? `Включено: каждые ${schedule.interval_hours} ч. Следующий расчёт — ${when(schedule.next_due_at)}${schedule.running ? '' : ' (начнётся после перезапуска приложения)'}.`
      : 'Выключено: выводы пересчитываются после каждого принятия фотографии и по кнопке.';
    return h('div', {class: 'card stack'}, h('h3', {}, 'Пересчёт по расписанию'), h('p', {class: 'muted small'}, state),
      h('div', {class: 'toolbar'}, field('Пересчитывать каждые, ч (0 — выключено)', hours),
        btn('Сохранить расписание', async (ev) => {
          const self = ev.currentTarget;
          self.disabled = true;
          try { await put('/analysis/schedule', {interval_hours: hours.value === '' ? 0 : +hours.value}); toast('Расписание сохранено', 'ok'); App.render({preserveScroll: true}); }
          catch (e) { fail(e); self.disabled = false; }
        })));
  }

  App.register({id: 'findings', async render(ctx) {
    const q = ctx.query;
    const [runs, schedule, result] = await Promise.all([get('/analysis/runs?limit=60'), get('/analysis/schedule'),
      get(`/analysis/runs/${q.run || 'latest'}?` + new URLSearchParams(Object.entries({kind: q.kind, task: q.task, setup: q.setup, material: q.material})
        .filter(([, v]) => v)).toString())]);
    const run = result.run;
    const route = (change) => {
      const next = Object.fromEntries(Object.entries({...q, ...change}).filter(([, v]) => v));
      App.go('/findings?' + new URLSearchParams(next).toString());
    };
    const recalc = btn('Пересчитать сейчас', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const r = await post('/analysis/runs');
        toast(`Расчёт № ${r.id} готов`, 'ok');
        if (q.run) route({run: ''}); else App.render();          // the new run is the latest
      }
      catch (e) { fail(e); self.disabled = false; }
    }, 'primary');
    const runSelect = h('select', {'aria-label': 'Расчёт', onChange: (e) => route({run: e.target.value})},
      h('option', {value: ''}, 'последний'), runs.map((r) => h('option', {value: r.id, selected: String(r.id) === q.run}, `№ ${r.id} · ${when(r.at)} · ${TRIGGER[r.trigger] || r.trigger}`)));
    const o = result.options;
    const select = (label, key, items) => field(label, h('select', {onChange: (e) => route({[key]: e.target.value})},
      h('option', {value: ''}, 'все'), items.map(([v, text]) => h('option', {value: v, selected: v === q[key]}, text))));
    const filters = h('div', {class: 'toolbar'},
      select('Вид', 'kind', o.kinds.map((k) => [k, KIND[k]])), select('Задача', 'task', o.tasks.map((t) => [t, taskName(t)])),
      select('Лазер и линза', 'setup', o.setups.map((s) => [s.key, setupName(s)])), select('Титан', 'material', o.stocks.map((s) => [s.key, stockName(s.stock)])));
    const runCard = h('div', {class: 'card stack'}, h('h3', {}, 'Расчёт выводов'),
      run ? facts([['Расчёт', `№ ${run.id} · ${when(run.at)} · ${TRIGGER[run.trigger] || run.trigger}`],
        ['Входные данные', `принятых фотографий ${run.inputs.accepted_pairs} · наблюдений для модели ${run.inputs.eligible_observations} · записей знания ${run.inputs.knowledge_entries}`
          + ` · целевых цветов ${run.inputs.targets} · выводов AI ${run.inputs.insights}`],
        ['Найдено', KINDS.map((k) => `${KIND[k]}: ${run.counts[k] || 0}`).join(' · ')]])
        : h('p', {class: 'muted'}, 'Расчётов ещё не было. Выводы считаются после каждого принятия фотографии; можно пересчитать и сейчас.'),
      ...(run ? rulesAlerts(run) : []),
      h('div', {class: 'toolbar'}, recalc, field('Показать расчёт', runSelect),
        h('p', {class: 'toolbar-hint'}, 'Прежние расчёты сохраняются: их выводы можно открыть и сравнить.')));
    const sections = KINDS.map((k) => {
      const items = result.findings.filter((f) => f.kind === k);
      return items.length ? h('section', {class: 'stack'}, h('h3', {}, `${KIND[k]} · ${items.length}`), items.map(findingCard)) : null;
    });
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Выводы'),
        h('p', {class: 'sub'}, 'Что показала накопленная работа: улучшения, нестабильность, аномалии, пробелы и гипотезы AI. Измеренное отделено от гипотез.')),
        h('span', {class: 'spacer'}), link('/designer', 'Планировщик экспериментов')),
      runCard, scheduleCard(schedule), run ? filters : null,
      run && !result.findings.length ? h('div', {class: 'card empty'}, result.total ? 'Под выбранные фильтры выводов нет.' : 'В этом расчёте выводов нет.') : null,
      sections);
  }});
})();
