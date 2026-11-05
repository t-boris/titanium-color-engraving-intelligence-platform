/* The review of a pair as four stages: Файлы → Совмещение → Проверка → Принятие (ux-photo-review-p0: REQ-001, REQ-002, DEC-001).

   What the screen shows is what the server derived (``pair.review``, src/titanium_platform/pair_review.py): the stage to work on, the
   blocking conditions (exactly those ``accept_pair`` refuses on) with the tools that resolve them, and the advisory notes. This file
   draws it: a stage bar, a header per stage (completeness, blockers, notes, exactly one primary action), and the row of manual tools
   that is on the screen at every stage whether or not automation warned (DEC-001).

   The panels of the stages and the regions of the tools are built once by the caller and only shown or hidden here, so what an operator
   typed into one survives a visit to another stage. Nothing here decides whether a pair may be accepted: the accept button is enabled
   only while the server says ``acceptable``, and is disabled while a re-check is running. */
'use strict';
const IngestStages = (() => {
  const {h, fill, btn, pill} = App;

  const STAGES = [['files', 'Файлы'], ['alignment', 'Совмещение'], ['review', 'Проверка'], ['accept', 'Принятие']];
  const KEYS = STAGES.map(([key]) => key);
  const NAME = Object.fromEntries(STAGES);
  const HINT = {
    files: 'Файл LightBurn и фотография читаются, файл совпадает с определением платы, настройки слоёв известны.',
    alignment: 'Контуры из файла лежат на тех же местах фотографии. Если автоматика не справилась или сомневается, поправьте совмещение вручную.',
    review: 'Фотография с контурами и короткий итог. Проверьте, что контуры лежат на нужных деталях; метрики и слои свёрнуты.',
    accept: 'Принятые наблюдения неизменяемы и входят в знания лазера. Здесь видно, что именно будет записано и откуда это взято.',
  };
  const MANUAL = ['corners', 'anchor', 'shift', 'matrix', 'layers', 'tasks'];
  const TOOLS = {corners: 'Углы работы', anchor: 'Привязка по детали', shift: 'Сдвиг и поворот схемы', matrix: 'Матрица параметров',
    layers: 'Слои файла', tasks: 'Задачи гравировки'};
  const CONTEXT = {check: 'Проверить пару', restart: 'Найти заново по RAW и LightBurn', file: 'Исправить пару',
    file_confirm: 'Подтвердить использованный файл', supplied: 'Ввести недостающие настройки', masks: 'Проверить маски слоёв'};

  // What stands in the way of acceptance, said for the operator; the codes are those of pair_review.py. The server's own sentence (if it
  // has one) is printed under it, translated, so nothing the check said is lost.
  const BLOCKER = {
    not_checked: 'Пара ещё не проверена: фотография не совмещена с файлом, слои не измерены.',
    file_unreadable: 'Файл LightBurn не читается.',
    photo_unreadable: 'Фотографию не удалось прочитать.',
    identifier_unknown: 'Идентификатор эксперимента на плате неизвестен этой системе.',
    identifier_deleted: 'Идентификатор на плате принадлежит удалённому эксперименту.',
    other_laser: 'Плата сделана для другого лазера, чем выбран для пары.',
    matrix_incomplete: 'Настройки матрицы прочитаны не полностью.',
    matrix_pulse_width: 'Длительность импульса матрицы вне диапазона этого лазера.',
    matrix_unconfirmed: 'Параметры матрицы ещё не подтверждены.',
    no_chart: 'Калибровочная карта на фотографии не подтверждена.',
    no_colour_basis: 'У фотографии нет основы для измерения цвета.',
    plate_cells_missing: 'В файле LightBurn не найдены ячейки платы.',
    file_unconfirmed: 'Файл отличается от определения платы: исправьте пару или подтвердите, что гравировали именно этим файлом.',
    alignment_lost: 'Поправка совмещения потеряла слишком много распознанных деталей.',
    alignment_failed: 'Фотография не совмещена с файлом.',
    masks_unreviewed: 'Маски слоёв ещё не проверены на этой фотографии.',
    no_measured_layer: 'Не измерен ни один читаемый сопоставимый слой.',
    not_ready: 'Пара не готова к принятию.',
  };
  const advisoryText = (a) => {
    const names = (a.names || []).map((n) => I18N.name(n)).join(', ');
    const more = a.count > (a.names || []).length ? ' и др.' : '';
    switch (a.code) {
      case 'layers_skipped': return `Не измерены слои: ${a.count} (${names}${more}).`;
      case 'layers_incomparable': return `Слои без сопоставимых настроек, в модель не попадут: ${a.count} (${names}${more}).`;
      case 'settings_missing': return `В файле нет настроек у слоёв: ${a.count} (${names}${more}). Их можно ввести вручную.`;
      case 'qr_offset': return 'QR-код на фотографии сдвинут относительно основной матрицы; его контур и измерение поправлены отдельно.';
      default: return a.detail ? I18N.tr(a.detail) : 'Проверка оставила замечание.';
    }
  };

  const toolName = (key) => TOOLS[key] || CONTEXT[key] || key;
  const stateText = (state, count) => (state === 'done' ? 'выполнено' : state === 'current'
    ? (count ? `нужно решить: ${count}` : 'сейчас') : count ? `впереди, проблем: ${count}` : 'впереди');

  /** The stage bar. ``onSelect`` null draws it for reading only (the upload pages, an accepted pair). */
  function bar(stages, {shown = null, onSelect = null} = {}) {
    const items = stages.map(({key, state, blockers}, i) => {
      const body = [h('span', {class: 'rv-num', 'aria-hidden': 'true'}, String(i + 1)), h('span', {class: 'rv-name'}, NAME[key]),
        h('span', {class: 'rv-state'}, stateText(state, (blockers || []).length))];
      const attrs = {class: `rv-step ${state}${key === shown ? ' shown' : ''}`, 'aria-current': key === shown ? 'step' : null};
      return h('li', {}, onSelect
        ? h('button', {type: 'button', ...attrs, 'aria-controls': `rv-panel-${key}`, onClick: () => onSelect(key)}, body)
        : h('span', {...attrs, tabindex: null}, body));
    });
    return h('nav', {'aria-label': 'Этапы проверки'}, h('ol', {class: 'rv-steps'}, items));
  }

  /** The stage bar of the pages that come before a review (a new pair, a re-photograph): the files stage is the one in progress. */
  const upload = () => bar(KEYS.map((key) => ({key, state: key === 'files' ? 'current' : 'todo', blockers: []})), {shown: 'files'});

  /** What invalidates a review, said to the operator (the same list as ``INVALIDATED_BY`` in pair_review.py). */
  const invalidation = () => h('details', {class: 'rv-note'}, h('summary', {}, 'Что сбрасывает проверку масок'),
    h('p', {class: 'muted small'}, 'Проверка масок относится к конкретному результату измерения. Она сбрасывается, если после неё заменить файл LightBurn, '
      + 'пересчитать совмещение (углы, привязка по детали, сдвиг схемы, «Найти заново», повторная проверка), ввести или убрать настройку слоя, '
      + 'исправить матрицу параметров. Если после повторной проверки расхождения с платой другие, подтверждение файла тоже снимается. '
      + 'Выбор задачи гравировки и подтверждение файла проверку масок не сбрасывают. Принятая пара неизменяема; поправка совмещения — новая пара.'));

  /** The review screen. ``panels`` {stage: [nodes]}, ``regions`` {tool: {el} | {build}}, ``actions`` the things the stages do
      (check, restart, file, file_confirm, supplied, masks, reviewMasks, accept), ``state`` {checked, ready, masksReviewed}, ``status`` a
      line the caller keeps under the header (the progress of a re-check), ``open`` the tools to show from the start. */
  function shell({review, panels, regions, actions, state, status = null, open = []}) {
    let shown = KEYS.includes(review.stage) ? review.stage : 'accept', busy = false;
    const barHost = h('div'), headHost = h('div'), announce = h('p', {class: 'rv-sr', role: 'status', 'aria-live': 'polite'});
    const wrappers = {}, filled = {}, buttons = {};

    const panelEls = Object.fromEntries(KEYS.map((key) => [key, h('section', {class: 'stack rv-panel', id: `rv-panel-${key}`,
      'aria-label': NAME[key], hidden: key !== shown}, ...(panels[key] || []))]));

    const fillRegion = (key) => {
      if (filled[key]) return;
      filled[key] = true;
      wrappers[key].append(regions[key].el || regions[key].build());
    };
    const setOpen = (key, on) => {
      if (on) fillRegion(key);
      wrappers[key].hidden = !on;
      buttons[key].setAttribute('aria-expanded', String(on));
      buttons[key].classList.toggle('on', on);
    };
    const openTool = (key) => {
      setOpen(key, true);
      wrappers[key].focus();
      if (wrappers[key].scrollIntoView) wrappers[key].scrollIntoView({block: 'nearest'});
    };
    const toggleTool = (key) => { if (wrappers[key].hidden) openTool(key); else setOpen(key, false); };

    const toolsBar = h('nav', {class: 'rv-tools', 'aria-label': 'Ручные инструменты'},
      h('span', {class: 'muted small'}, 'Ручные инструменты:'),
      ...MANUAL.map((key) => (buttons[key] = h('button', {type: 'button', class: 'btn rv-tool', 'aria-expanded': 'false',
        'aria-controls': `rv-region-${key}`, onClick: () => toggleTool(key)}, TOOLS[key]))));
    const regionsHost = h('div', {class: 'stack rv-regions'}, ...MANUAL.map((key) => (wrappers[key] = h('div', {class: 'rv-region',
      id: `rv-region-${key}`, tabindex: '-1', role: 'region', 'aria-label': TOOLS[key], hidden: true}))));
    for (const key of MANUAL) if (regions[key] && regions[key].el) fillRegion(key);          // inputs exist from the start, hidden
    for (const key of open) if (regions[key]) setOpen(key, true);

    const has = (stage) => review.blockers.some((b) => b.stage === stage);
    const use = (key) => (MANUAL.includes(key) ? openTool(key) : actions[key] && actions[key]());
    const toolButton = (key) => h('button', {type: 'button', class: 'btn btn-small', onClick: () => use(key)}, toolName(key));

    const primary = () => {
      if (shown === 'files' && !state.checked) return {label: 'Проверить пару', run: actions.check};
      if (shown === 'files') return {label: 'Далее: совмещение', run: () => show('alignment'), disabled: has('files')};
      if (shown === 'alignment') return {label: 'Далее: проверка', run: () => show('review'), disabled: has('files') || has('alignment')};
      if (shown === 'review' && state.masksReviewed) return {label: 'Далее: принятие', run: () => show('accept'), disabled: KEYS.slice(0, 3).some(has)};
      if (shown === 'review') return {label: 'Маски проверены: контуры лежат на нужных деталях', run: actions.reviewMasks, disabled: !state.ready};
      return {label: 'Принять наблюдения', run: actions.accept, disabled: !review.acceptable};
    };

    const blockerRow = (b) => {
      const known = BLOCKER[b.code];
      return h('li', {class: 'rv-blocker'},
        h('div', {class: 'rv-what'}, h('strong', {}, known || (b.detail ? I18N.tr(b.detail) : 'Проверка нашла проблему.')),
          known && b.detail ? h('span', {class: 'muted small'}, I18N.tr(b.detail)) : null,
          shown === 'accept' ? h('span', {class: 'muted small'}, `Этап: ${NAME[b.stage]}`) : null),
        h('div', {class: 'rv-fix'}, ...b.tools.map((key) => h('button', {type: 'button', class: 'btn btn-small',
          onClick: () => { if (b.stage !== shown && !MANUAL.includes(key)) show(b.stage); use(key); }}, toolName(key)))));
    };
    const advisoryRow = (a) => h('li', {class: 'rv-advisory'}, h('div', {class: 'rv-what'}, advisoryText(a)),
      h('div', {class: 'rv-fix'}, ...a.tools.map((key) => toolButton(key))));

    function drawHead() {
      const at = KEYS.indexOf(shown), here = review.blockers.filter((b) => shown === 'accept' || b.stage === shown);
      const earlier = shown === 'accept' ? [] : [...new Set(review.blockers.filter((b) => KEYS.indexOf(b.stage) < at).map((b) => b.stage))];
      const done = review.stages.filter((s) => s.state === 'done').length;
      const act = primary(), off = act.disabled || busy;
      const reason = busy ? 'Идёт пересчёт: дождитесь его конца.' : act.disabled && here.length ? 'Станет доступно, когда будет решено то, что указано выше.'
        : act.disabled ? 'Сначала решите то, что мешает на более раннем этапе.' : null;
      const notes = review.advisories || [];
      fill(headHost, h('section', {class: 'card stack rv-head', 'aria-labelledby': 'rv-head-title'},
        h('div', {class: 'row'}, h('h3', {id: 'rv-head-title'}, `Этап ${at + 1} из ${KEYS.length}: ${NAME[shown]}`), h('span', {class: 'spacer'}),
          pill(`выполнено этапов: ${done} из ${KEYS.length}`, done === KEYS.length ? 'ok' : '')),
        h('p', {class: 'muted small'}, HINT[shown]),
        here.length ? h('div', {class: 'stack'}, h('strong', {}, 'Что мешает принять результат'), h('ul', {class: 'rv-list'}, here.map(blockerRow)))
          : h('div', {class: 'alert ok', role: 'status'}, shown === 'accept' ? 'Всё проверено: наблюдения можно принять.' : 'На этом этапе ничего не мешает принять результат.'),
        earlier.length ? h('div', {class: 'alert warn', role: 'status'}, 'На более раннем этапе есть нерешённое: ',
          earlier.map((key, i) => [i ? ', ' : '', h('button', {type: 'button', class: 'btn btn-small', onClick: () => show(key)}, NAME[key])])) : null,
        notes.length ? h('div', {class: 'stack'}, h('strong', {}, 'На что обратить внимание'),
          h('ul', {class: 'rv-list'}, notes.slice(0, 4).map(advisoryRow)),
          notes.length > 4 ? h('details', {}, h('summary', {}, `Ещё ${notes.length - 4}`), h('ul', {class: 'rv-list'}, notes.slice(4).map(advisoryRow))) : null) : null,
        h('div', {class: 'row'}, btn(act.label, (ev) => { const self = ev.currentTarget; act.run(self); }, 'primary', off), reason ? h('span', {class: 'muted small'}, reason) : null)));
    }

    function show(stage) {
      shown = stage;
      for (const key of KEYS) panelEls[key].hidden = key !== stage;
      fill(barHost, bar(review.stages, {shown, onSelect: show}));
      drawHead();
      const count = review.blockers.filter((b) => stage === 'accept' || b.stage === stage).length;
      announce.textContent = `Этап ${KEYS.indexOf(stage) + 1} из ${KEYS.length}: ${NAME[stage]}. ${count
        ? `Нерешённых проблем: ${count}.` : 'Проблем на этом этапе нет.'}`;
    }
    show(shown);

    const el = h('div', {class: 'stack rv'}, barHost, announce, headHost, status, toolsBar, regionsHost, ...KEYS.map((key) => panelEls[key]));
    return {el, show, open: openTool, stage: () => shown, setBusy(on) { busy = on; drawHead(); },
      focusPrimary() { const first = headHost.querySelector('button.primary'); if (first) first.focus(); }};
  }

  return {shell, bar, upload, invalidation, KEYS, MANUAL, CONTEXT, TOOLS, BLOCKER};
})();
