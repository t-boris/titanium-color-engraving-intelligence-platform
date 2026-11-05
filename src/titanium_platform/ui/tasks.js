/* Задача гравировки на экранах (REQ-020): выбор задачи плана, платы или загружаемой работы, подпись задачи слоя,
   метрики качества с основанием и способом измерения, недоступные метрики с причиной и недостающий контекст.
   Список задач приходит с сервера (/api/tasks); подписи — TaskText (i18n-tasks.js). */
'use strict';
const Tasks = (() => {
  const {h, fill, field, pill, get, num, labText} = App;
  let vocabulary = null;

  /** Словарь задач с сервера: ключ, цели, которые задача записывает, метрики. Загружается один раз. */
  const load = () => (vocabulary ||= get('/tasks'));
  const name = (kind) => TaskText.KIND[kind] || kind;

  /** «Надписи · выбрана для слоя», «Заливка · по слою LightBurn». */
  function label(task) {
    if (!task) return '—';
    const source = TaskText.SOURCE[task.source] || (task.basis === 'explicit' ? 'задана оператором' : TaskText.SOURCE.layer);
    return `${name(task.kind)} · ${source}`;
  }
  const badge = (task) => (task ? pill(label(task), task.basis === 'explicit' ? 'ok' : '') : null);

  /** Список задач. empty — подпись пустого значения (задача не выбрана), extra — особые значения [значение, подпись]. */
  function select(current, {empty = null, extra = [], aria = 'Задача гравировки', onChange = null} = {}) {
    const el = h('select', {'aria-label': aria});
    const options = (keys) => fill(el, empty == null ? null : h('option', {value: ''}, empty), ...extra.map(([v, l]) => h('option', {value: v}, l)),
      ...keys.map((k) => h('option', {value: k}, name(k))));
    options(Object.keys(TaskText.KIND));
    el.value = current ?? '';
    load().then((list) => { const value = el.value; options(list.map((t) => t.key)); el.value = value; }).catch(() => {});
    if (onChange) el.addEventListener('change', () => onChange(el.value));
    return el;
  }

  /** Поля целей выбранной задачи (только те, что она записывает, и примечание); value() — объект для сервера.
      Числа читаются строго (ux-save-feedback-p0, REQ-003): правила — те, что проверяет сервер (tasks.clean_goals), ошибка стоит рядом с полем,
      набранное остаётся. check() — все ли поля верны (и отметить неверные); value() и при ошибке не правит набранное: сервер откажет сам. */
  const GOAL_QUANTITY = {line_width_mm: 'lineWidth', text_height_mm: 'textHeight'};
  const NOTE_LIMIT = 500;                                                  // tasks.clean_goals: «a task note must not exceed 500 characters»
  function goalFields(kind, list) {
    const spec = ((list || []).find((t) => t.key === kind) || {goals: []}).goals.concat(['note']);
    const reads = {};                                                      // goal -> () => {ok, value} | {ok: false, message}; value null: nothing typed
    const marks = {};
    const fields = spec.map((g) => {
      let el;
      if (g === 'target_lab') {
        const parts = ['L', 'a', 'b'].map((c) => h('input', {type: 'number', step: 'any', placeholder: c, 'aria-label': `${TaskText.GOAL[g]}: ${c}`, style: 'width:5em'}));
        el = field(TaskText.GOAL[g], h('span', {class: 'row'}, ...parts), 'три числа: L от 0 до 100, a и b — любые', {constraint: 'допустимо: L от 0 до 100'});
        reads[g] = () => {
          const typed = parts.map((i) => i.value.trim());
          if (typed.every((t) => t === '')) return {ok: true, value: null};
          if (typed.some((t) => t === '')) return {ok: false, message: 'Нужны все три числа: L, a и b. Заполнены не все'};
          const got = typed.map((t, i) => Forms.parse(t, Forms.QUANTITIES[i === 0 ? 'labL' : 'labAB'], {required: true}));
          const bad = got.findIndex((r) => !r.ok);
          return bad < 0 ? {ok: true, value: got.map((r) => r.value)} : {ok: false, message: `${'Lab'[bad]}: ${got[bad].message}`};
        };
        for (const i of parts) i.addEventListener('input', () => el.clearError());
      } else if (GOAL_QUANTITY[g]) {
        const input = h('input', {type: 'number', step: 'any', min: '0'});
        const q = GOAL_QUANTITY[g];
        el = field(TaskText.GOAL[g] || g, input, null, {unit: 'мм', constraint: 'допустимо: больше 0'});
        reads[g] = () => (input.value.trim() === '' ? {ok: true, value: null} : Forms.parse(input.value, Forms.QUANTITIES[q], {}));
        input.addEventListener('input', () => el.clearError());
      } else {
        const input = h('input', {placeholder: 'необязательно'});
        el = field(TaskText.GOAL[g] || g, input, null, {constraint: `не больше ${NOTE_LIMIT} символов`});
        reads[g] = () => {
          const text = input.value.trim();
          return text.length > NOTE_LIMIT ? {ok: false, message: `Не больше ${NOTE_LIMIT} символов. Введено: ${text.length}`} : {ok: true, value: text === '' ? null : input.value};
        };
        input.addEventListener('input', () => el.clearError());
      }
      marks[g] = el;
      return el;
    });
    function check() {
      let all = true;
      for (const [g, read] of Object.entries(reads)) {
        const r = read();
        if (r.ok) marks[g].clearError(); else { marks[g].setError(r.message); all = false; }
      }
      return all;
    }
    const value = () => {
      const out = {};
      for (const [g, read] of Object.entries(reads)) {
        const r = read();
        if (r.ok) { if (r.value !== null) out[g] = r.value; continue; }
        marks[g].setError(r.message);                                      // beside the box; the typed text is sent as it is and the server refuses it in its words
        const typed = [...marks[g].querySelectorAll('input')].map((i) => i.value).filter((t) => t !== '');
        out[g] = g === 'target_lab' ? typed : typed[0];
      }
      return out;
    };
    return {el: h('div', {class: 'grid g3'}, ...fields), value, check};
  }

  /** Выбор задачи плана или платы с её целями (REQ-020 AC1). empty — подпись значения «задача по умолчанию» (её определит
      сервер). append(fd) кладёт task и goals в форму, body() — в JSON. */
  function chooser(initial, {hint = null, empty = null} = {}) {
    const goalsBox = h('div', {});
    let goals = goalFields(initial, null);
    const redraw = async (kind) => { goals = goalFields(kind, await load().catch(() => [])); fill(goalsBox, kind ? goals.el : null); };
    const sel = select(initial, {empty, onChange: redraw});
    redraw(initial);
    const chosen = () => {
      const g = sel.value ? goals.value() : {};
      return {task: sel.value || null, goals: Object.keys(g).length ? g : null};
    };
    return {
      el: h('div', {class: 'stack'}, field('Задача гравировки', sel, hint || 'что должна дать эта работа; результаты разных задач не смешиваются'),
        h('details', {}, h('summary', {}, 'Цели задачи (необязательно)'), goalsBox)),
      kind: () => sel.value,
      check: () => (sel.value ? goals.check() : true),                      // false (and the bad boxes marked) when a goal cannot be read
      set: (kind) => { sel.value = kind; redraw(kind); },
      append(fd) { const c = chosen(); if (c.task) fd.append('task', c.task); if (c.goals) fd.append('goals', JSON.stringify(c.goals)); },
      body() { const c = chosen(); return c.task ? {task: c.task, task_goals: c.goals} : {}; },
    };
  }

  /** Цели задачи плана одной строкой. */
  function goalsText(goals) {
    return Object.entries(goals || {}).map(([g, v]) => `${TaskText.GOAL[g] || g}: ${Array.isArray(v) ? labText(v) : v}`).join(' · ');
  }

  function value(m) {
    if (m.metric === 'lab') return labText(m.value);
    if (m.metric === 'line_visibility') return `${m.value[0]} из ${m.value[1]}`;
    if (m.metric === 'tonal_profile') return `связь с серым ${num(m.value.rho, 2)} · размах L* ${num(m.value.range_L, 0)}`;
    if (m.metric === 'apparent_trace_width') return `${num(m.value, 3)} мм ± ${num(m.scale.uncertainty_mm, 3)}`;
    if (m.metric === 'line_continuity') return `${num(m.value, 0)} %`;
    if (m.metric === 'contrast') return `ΔL* ${num(m.value, 1)}`;
    return num(m.value, 1);
  }
  function basis(m) {
    const text = TaskText.BASIS[m.basis] || m.basis;
    return m.basis === 'registration_scale' && m.scale ? `${text}: ${num(m.scale.px_per_mm, 1)} пикс./мм` : text;
  }

  /** Метрики качества слоя: значение, основание (подпись) и способ (подсказка); недоступные — с причиной (REQ-020 AC6). */
  function metrics(list, {skip = []} = {}) {
    const items = (list || []).filter((m) => !skip.includes(m.metric));
    if (!items.length) return null;
    return h('div', {class: 'stack small task-metrics'},
      ...items.map((m) => (m.available
        ? h('div', {title: `Способ: ${TaskText.METHOD[m.method] || m.method}`}, `${TaskText.METRIC[m.metric] || m.metric}: ${value(m)} `,
          h('span', {class: 'muted'}, `· ${basis(m)}`))
        : h('div', {class: 'muted'}, `${TaskText.METRIC[m.metric] || m.metric}: недоступно — ${I18N.tr(m.note)}`))));
  }
  /** Основание цвета слоя одной подписью: «по эталонной карте», «относительно чистого титана этого снимка»… */
  const colourBasis = (list) => { const m = (list || []).find((x) => x.metric === 'lab'); return m ? basis(m) : null; };

  /** Чего не хватает в контексте свидетельств (REQ-020 AC4). */
  const missing = (codes) => (codes || []).map((c) => pill(TaskText.MISSING[c] || c, 'warn'));

  return {load, name, label, badge, select, chooser, goalsText, metrics, colourBasis, missing};
})();
