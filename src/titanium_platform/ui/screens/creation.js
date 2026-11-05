/* Creating a work from its result (feature ux-work-creation-p0, REQ-001..003, DEC-001).

   IMPLEMENTATION PLAN (derived from the requirements and the code that exists)
   -----------------------------------------------------------------------------------------------------------------------------------------
   Server (new modules, no change to how a work is made):
     creation_context.py   the shared context (laser, lens, titanium, rig, source) in the workshop settings; impact of a change; what a
                           result needs (readiness) and the starter test; routes /api/creation/context, /context/impact, /readiness,
                           /starter-plate.
     creation_drafts.py    unfinished tasks on disk (table creation_draft, picture under files/drafts/ by a relative name): created when the
                           picture is chosen, saved at every step, closed ONLY by an explicit complete (the work exists) or discard;
                           closing the application never closes one. Routes /api/creation/drafts*.
     creation_previews.py  one tile per result for the person's own picture at the requested width, drawn by the code the work will use
                           (segment.segment, vectorize.trace, the grey picture of a photo work): /api/creation/drafts/{id}/preview/{result}.png.
   Interface:
     context.js (WorkContext)  the context strip with «Изменить…» (a dialog that shows the impact of the change BEFORE «Применить»), the read-only
                               strip of an opened work's OWN context; hardware.js: contextStart / rememberContext for the older forms.
     this file (Creation)      ONE entry, Creation.start(); the screen #/new (also /vector?new=1) in three steps that keep picture, name, size,
                               result and every setting when the person goes back: 1 picture, name, size and context; 2 the result, as four
                               comparable tiles with what each is good for; 3 the settings of the chosen result (algorithm, ΔE, smoothing,
                               time under «Дополнительно») and «Создать работу». A missing laser, lens, titanium or measurement is a gate in
                               step 3 (and a mark on the tile): the person finishes it elsewhere and comes back by the bar below; for missing
                               measurements the gate is the starter test and says which result it makes available. Nothing is created until
                               the last button, so cancelling leaves no half-made work. A photograph ends with the question «Какая гравировка?»
                               (BUG-003, REQ-071): its button makes the work on the scale of the context and PhotoKindStep, the very dialog of
                               photo engraving's «Новая работа», shows the person's picture in every kind; «Создать в «…»» keeps the work in the
                               chosen kind, while «← Назад», × and Escape delete it and leave the form, the marked kind and the task as they were.
                               While the question is open the task records the work (``hold``), so a window closed in the middle does not leave it
                               behind: opening the task deletes it, if it is still that very work. The bar «Не закончена работа» is mounted outside
                               #app on every screen while an open task exists, so setup screens need no return logic and a restart finds it again.
   Not changed: BUG-003 (the two-step «Новая работа» of photo engraving stays, now through the shared PhotoKindStep; it hands over to this screen
   only when it cannot go on), the editors, the lifecycle and review screens, list.js, dialogs.js and router.js behaviour.
   ----------------------------------------------------------------------------------------------------------------------------------------- */
'use strict';
const Creation = (() => {
  const {h, fill, btn, field, link, pill, get, post, put, del, form, toast, fail, go} = App;

  // -- the four results -----------------------------------------------------------------------------------------------------------------
  const RESULTS = [
    {id: 'colour', title: 'Цветные области', strategy: 'photo', work: 'vector',
      about: 'Картинка делится на гладкие цветные области; каждой достаётся измеренный цвет титана.',
      file: 'Файл LightBurn: слой на каждый использованный цвет заливки.', needs: 'Нужны измеренные цвета заливки этого лазера, линзы и титана.'},
    {id: 'photo', title: 'Фотогравировка', strategy: null, work: 'photo',
      about: 'Картинка остаётся полутоновой: яркость каждой точки задаёт мощность на измеренной шкале.',
      file: 'Файл LightBurn: слой-изображение со своей шкалой.', needs: 'Нужна измеренная шкала серого этого лазера, линзы и титана.'},
    {id: 'silhouette', title: 'Силуэт', strategy: 'fill', work: 'vector',
      about: 'Тёмная форма картинки заливается одним рецептом.',
      file: 'Файл LightBurn: слой заливки.', needs: 'Нужен проверенный рецепт заливки.'},
    {id: 'lines', title: 'Линии', strategy: 'line', work: 'vector',
      about: 'Тёмные штрихи картинки становятся линиями по центру штриха.',
      file: 'Файл LightBurn: слои линий (режим Line).', needs: 'Нужен проверенный рецепт линии.'}];
  const RESULT = Object.fromEntries(RESULTS.map((r) => [r.id, r]));
  const STEPS = [['picture', 'Картинка и размер'], ['result', 'Что получится'], ['method', 'Настройки и создание']];
  const FACTS = {colour: (f) => `областей: ${f.areas} · цветов: ${f.colours}`, photo: (f) => `градаций серого в картинке: ${f.levels}`,
    silhouette: (f) => `областей: ${f.areas}`, lines: (f) => `линий: ${f.strokes}`};
  const DEFAULT_WIDTH = '60';                                         // a starting value in the field, the same as the vector form's
  const FLOW = 'new';
  const AUTOSAVE_MS = 500;
  const MISSING = {
    laser: ['Не добавлен ни один лазер.', '/devices', 'Добавить лазер'],
    titanium: ['Не добавлена заготовка титана.', '/setup', 'Добавить заготовку'],
    lens: ['На выбранном лазере нет линзы: тест гравируется через неё.', '/devices', 'Установить линзу'],
  };
  const BECOMES = {measured_scale: 'Когда измерения теста будут приняты, появится измеренная шкала серого, и фотогравировка станет доступна.',
    validated_recipes: 'Когда измерения теста будут приняты, они попадут в измеренные цвета этого лазера, линзы и титана. Рецепт входит в работу, когда он '
      + 'проверен повторами по правилам лазера, поэтому может понадобиться повторить тест.'};

  const url = ({result = null, draft = null} = {}) => {
    const query = [draft ? `draft=${draft}` : null, result ? `result=${result}` : null].filter(Boolean);
    return '/new' + (query.length ? '?' + query.join('&') : '');
  };
  /** The one way to start a work from anywhere (the works list, a menu, an empty state): ``result`` preselects a result, ``draft`` resumes a task. */
  const start = (options = {}) => go(url(options));

  const baseName = (file) => String(file || '').replace(/\.[^.]+$/, '');
  const numberOf = (text) => (String(text).trim() === '' ? NaN : +text);
  const lensField = (context) => (context.lens_id == null ? 'unknown' : String(context.lens_id));

  // -- the bar of an unfinished task, on every screen --------------------------------------------------------------------------------------
  const bar = h('aside', {id: 'creation-bar', class: 'alert warn creation-bar', 'aria-label': 'Незавершённая работа', hidden: true});
  let barToken = 0;
  const onWizard = () => /^#\/(new|vector\?(.*&)?new=)/.test(String((typeof location === 'object' && location.hash) || '')) && !/[?&]classic=/.test(location.hash);
  // the bar is fixed over the lower edge of the window and its height changes with the width and the text size: the page keeps that much free below
  // and the browser keeps what has the keyboard above it (--creation-bar-h, read by the stylesheet), not under the bar
  const barHeight = typeof ResizeObserver === 'function' ? new ResizeObserver(() => document.documentElement.style.setProperty('--creation-bar-h', bar.offsetHeight + 'px')) : null;
  const padPage = (on) => {
    if (document.body && document.body.classList) document.body.classList.toggle('has-creation-bar', on);
    if (barHeight) { if (on) barHeight.observe(bar); else barHeight.disconnect(); }
  };

  async function waitingText(draft) {
    const waiting = draft.state && draft.state.waiting;
    if (!waiting || !waiting.result) return 'Можно продолжить.';
    try {
      const r = await get(`/creation/readiness?result=${waiting.result}`);
      return r.ready ? 'Недостающее добавлено: можно продолжить.' : waiting.for === 'starter_test' ? 'Ждёт стартовый тест и приём его измерений.' : 'Ждёт настройки оборудования.';
    } catch (_) { return 'Можно продолжить.'; }
  }

  /** Redraws the bar: the newest open task with «Продолжить» and «Отменить задачу». It is hidden on the creation screen itself and when no task is open. */
  async function refreshBar() {
    const mine = ++barToken;
    let drafts = [];
    try { drafts = await get('/creation/drafts'); } catch (_) { drafts = []; }
    if (mine !== barToken) return;
    if (!drafts.length || onWizard()) { bar.hidden = true; fill(bar); padPage(false); return; }
    const draft = drafts[0];
    const note = await waitingText(draft);
    if (mine !== barToken) return;
    fill(bar, h('div', {class: 'row'}, h('strong', {}, `Не закончена работа «${draft.name || (draft.image && baseName(draft.image.name)) || 'без названия'}».`),
      h('span', {class: 'small'}, drafts.length > 1 ? `${note} Всего незавершённых: ${drafts.length}.` : note), h('span', {class: 'spacer'}),
      btn('Продолжить', () => start({draft: draft.id}), 'btn-small primary'), btn('Отменить задачу', () => discard(draft, refreshBar), 'btn-small')));
    bar.hidden = false;
    padPage(true);
  }

  function discard(draft, after) {
    return App.confirmBox(`Отменить задачу «${draft.name || 'без названия'}»?`,
      'Введённое и сохранённая картинка будут удалены; вернуть задачу будет нельзя. Созданные работы не затрагиваются.', 'Отменить задачу', async () => {
        await post(`/creation/drafts/${draft.id}/discard`);
        toast('Задача отменена', 'ok');
        if (after) await after();
      });
  }

  function mountBar() {
    const app = typeof document.getElementById === 'function' ? document.getElementById('app') : null;
    if (app && app.parentNode && typeof app.parentNode.insertBefore === 'function') app.parentNode.insertBefore(bar, app); else document.body.append(bar);
    if (typeof addEventListener === 'function') addEventListener('hashchange', () => refreshBar());
    refreshBar();
  }

  // -- the creation screen ------------------------------------------------------------------------------------------------------------------
  async function render(ctx) {
    const query = (ctx && ctx.query) || {};
    const [context, lists, drafts, plateTypes] = await Promise.all([get('/creation/context'), App.hardwareLists(), get('/creation/drafts'),
      get('/plate-types').catch(() => [])]);
    const S = {context, draft: null, step: 'picture', result: RESULT[query.result] ? query.result : null, waiting: null, uploaded: null, picture: 0,
      readiness: {}, rules: undefined, tiles: {}, busy: false, kind: null, hold: null};
    if (query.draft) {
      S.draft = drafts.find((d) => String(d.id) === String(query.draft)) || null;
      if (!S.draft) S.missingDraft = true;
    }
    const host = h('div', {class: 'stack'});
    const heading = (text) => h('h2', {tabindex: '-1'}, text);

    // inputs are made once and stay in the page's memory while the person goes back and forth: nothing typed is ever lost by a step
    const fileIn = h('input', {type: 'file', accept: 'image/*', 'aria-label': 'Картинка'});
    const filePicker = App.filePick(fileIn, 'Выбрать картинку');          // made once: going back to the first step shows the chosen file again
    const nameIn = h('input', {autocomplete: 'off', 'aria-label': 'Название работы', placeholder: 'по имени файла'});
    const widthIn = h('input', {type: 'number', min: '0', step: 'any', value: DEFAULT_WIDTH, 'aria-label': 'Ширина на титане, мм'});
    const M = {
      thr: h('input', {type: 'number', step: 'any', min: '0', placeholder: 'из правил'}),
      remember: h('input', {type: 'checkbox', checked: true}),
      tolerance: h('input', {type: 'number', step: 'any', min: '0', value: '0.08', 'aria-label': 'Сглаживание границ, мм'}),
      colours: h('input', {type: 'number', step: '1', min: '2', max: '29', value: 12}),
      detail: h('select', {'aria-label': 'Детальность'}, [['coarse', 'Крупно'], ['medium', 'Средне'], ['fine', 'Детально']].map(([v, l]) => h('option', {value: v, selected: v === 'medium'}, l))),
      algorithm: VectorSplit.picker((S.draft && S.draft.state && S.draft.state.method && S.draft.state.method.algorithm) || 'slic'),
      faces: h('input', {type: 'checkbox', checked: true}),
      maxTime: h('input', {type: 'number', step: 'any', min: '0', placeholder: 'без предела'}),
      asShot: h('input', {type: 'checkbox'}),
      markers: h('input', {type: 'checkbox'}),
      clean: h('input', {type: 'checkbox', checked: true}),
      grey: h('input', {type: 'number', step: '1', min: '0', max: '255', placeholder: 'авто (Оцу)'}),
    };
    M.algorithm.hint.setAttribute('style', 'grid-column:1 / -1');
    const methodState = () => ({thr: M.thr.value, remember: M.remember.checked, tolerance: M.tolerance.value, colours: M.colours.value, detail: M.detail.value,
      algorithm: M.algorithm.select.value, faces: M.faces.checked, maxTime: M.maxTime.value, asShot: M.asShot.checked, markers: M.markers.checked, clean: M.clean.checked, grey: M.grey.value});
    const restoreMethod = (m) => {
      if (!m) return;
      for (const k of ['thr', 'tolerance', 'colours', 'maxTime', 'grey']) if (m[k] != null) M[k].value = m[k];
      for (const k of ['remember', 'faces', 'asShot', 'markers', 'clean']) if (m[k] != null) M[k].checked = !!m[k];
      if (m.detail) M.detail.value = m.detail;
      if (m.algorithm) M.algorithm.select.value = m.algorithm;
    };
    const stateOf = () => ({v: 1, step: S.step, result: S.result, name: nameIn.value, width_mm: widthIn.value, method: methodState(), waiting: S.waiting, kind: S.kind, hold: S.hold});
    if (S.draft) {
      const st = S.draft.state || {};
      nameIn.value = S.draft.name || st.name || '';
      if (st.width_mm != null) widthIn.value = st.width_mm;
      restoreMethod(st.method);
      S.result = RESULT[st.result] ? st.result : S.result;
      S.waiting = st.waiting || null;
      S.kind = typeof st.kind === 'string' ? st.kind : null;                    // the kind of photo engraving the person last marked
      S.hold = st.hold && st.hold.id != null ? st.hold : null;                  // a work made only to show the kinds, if the window was closed meanwhile
      S.step = STEPS.some(([id]) => id === st.step) ? st.step : 'picture';
      if (!S.draft.image) S.step = 'picture';                       // without its picture a task can only go on from the first step
      else if (S.step === 'method' && !S.result) S.step = 'result';
    }

    // -- saving: one write after another, each carrying the whole form, so the last one is the form as it is ----------------------------------
    const note = h('p', {class: 'small muted', role: 'status', hidden: true});
    const tell = (text) => { note.textContent = text || ''; note.hidden = !text; };
    let queue = Promise.resolve(), timer = null;
    const enqueue = (job) => { const run = queue.then(job); queue = run.catch(() => {}); return run; };
    const send = (extra = {}) => enqueue(async () => {
      const fd = new FormData();
      fd.append('state', JSON.stringify(stateOf()));
      fd.append('name', nameIn.value);
      if (extra.file) fd.append('picture', extra.file, extra.file.name);
      if (S.draft) S.draft = await App.api('PUT', `/creation/drafts/${S.draft.id}`, fd, true);
      else { fd.append('flow', FLOW); S.draft = await form('/creation/drafts', fd); }
      if (extra.file) { S.uploaded = extra.file; S.picture++; }
      return S.draft;
    });
    /** Saves the task when it exists (it is made when the picture is chosen); a failure is told, never thrown at the person's typing. */
    const autosave = () => {
      clearTimeout(timer);
      if (!S.draft) return;
      timer = setTimeout(() => { send().then(() => tell('')).catch((e) => tell(`Задача не сохранена: ${e.message}`)); }, AUTOSAVE_MS);
    };
    const flush = async () => { clearTimeout(timer); if (S.draft) { try { await send(); tell(''); } catch (e) { tell(`Задача не сохранена: ${e.message}`); } } };
    for (const el of [nameIn, widthIn, ...Object.values(M).filter((v) => v && v.nodeType)]) { el.addEventListener('input', autosave); el.addEventListener('change', autosave); }
    M.algorithm.select.addEventListener('change', autosave);
    fileIn.addEventListener('change', () => {
      const file = fileIn.files && fileIn.files[0];
      if (file && !nameIn.value.trim()) nameIn.value = baseName(file.name);
    });

    // -- the context ----------------------------------------------------------------------------------------------------------------------
    const strip = WorkContext.strip(S.context, {onChange: async (saved) => {
      S.context = saved; S.readiness = {}; S.rules = undefined; S.starter = null;
      if (S.step !== 'picture') await loadReadiness();
      if (S.step === 'method' && S.result !== 'photo') await loadRules();
      drawStep();
      strip.focus();                                                   // the redraw moved the button the dialog gave the focus back to
    }});

    // -- readiness of the four results, tiles of the picture ------------------------------------------------------------------------------
    let readyToken = 0;
    async function loadReadiness() {
      const mine = ++readyToken;
      const answers = await Promise.all(RESULTS.map((r) => get(`/creation/readiness?result=${r.id}`).then((a) => [r.id, a]).catch((e) => [r.id, {error: e.message}])));
      if (mine !== readyToken) return;                                    // another context was chosen meanwhile: this answer is for the one before
      S.readiness = Object.fromEntries(answers);
    }
    const tileViews = {};                                              // result id -> {node, update}: a tile is updated in place, so the keyboard stays where it is
    async function loadTile(r) {
      const key = `${S.draft.id}|${S.picture}|${widthIn.value}|${r.id}`;
      S.tiles[r.id] = {key, state: 'loading'};
      if (tileViews[r.id]) tileViews[r.id].update();
      try {
        const res = await fetch(`/api/creation/drafts/${S.draft.id}/preview/${r.id}.png?width_mm=${encodeURIComponent(widthIn.value)}`);
        if (!res.ok) {
          let raw = `Ошибка сервера (${res.status})`;
          try { const d = await res.json(); raw = I18N.tr((d.detail || d).error || raw); } catch (_) { /* the status says it */ }
          throw new Error(raw);
        }
        let facts = {};
        try { facts = JSON.parse(res.headers.get('x-preview-facts') || '{}'); } catch (_) { facts = {}; }
        const blob = await res.blob();
        if (S.tiles[r.id] && S.tiles[r.id].key === key) S.tiles[r.id] = {key, state: 'ready', src: URL.createObjectURL(blob), facts};
      } catch (e) { if (S.tiles[r.id] && S.tiles[r.id].key === key) S.tiles[r.id] = {key, state: 'failed', error: e.message}; }
      if (tileViews[r.id]) tileViews[r.id].update();
    }
    const tileKey = (r) => `${S.draft.id}|${S.picture}|${widthIn.value}|${r.id}`;

    // -- rules: the delta E tolerance is never invented -----------------------------------------------------------------------------------------
    async function loadRules() {
      if (S.context.device_id == null) return;
      const asked = `${S.context.device_id}|${lensField(S.context)}`;
      let rules = null;
      try { rules = await get(`/rules?device_id=${S.context.device_id}&lens_id=${lensField(S.context)}`); } catch (_) { rules = null; }
      if (asked !== `${S.context.device_id}|${lensField(S.context)}`) return;
      S.rules = rules ? rules.delta_tolerance : undefined;              // a number, null when none is saved, undefined while not known
    }
    const toleranceHint = () => {
      const saved = S.rules, text = saved == null ? '' : String(+(+saved).toFixed(2));
      M.thr.setAttribute('placeholder', saved != null ? `из правил: ${text}` : saved === null ? 'задайте' : 'из правил');
      M.thr.setAttribute('aria-invalid', saved === null && M.thr.value === '' ? 'true' : 'false');
      return saved != null ? `пусто — ΔE ${text} из правил этого лазера с линзой; число здесь — только для этой работы`
        : saved === null ? 'Для этого лазера с линзой допуск не сохранён — задайте его. Внутри допуска берётся самый быстрый цвет; ΔE 1 едва заметно, 2–3 — мало, 5 — две гравировки одного рецепта ещё совпадают.'
          : 'пусто — допуск из правил этого лазера с линзой';
    };
    M.thr.addEventListener('input', () => { if (S.step === 'method') toleranceHint(); });

    // -- the view -----------------------------------------------------------------------------------------------------------------------------
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const show = (text) => { error.textContent = text || ''; error.hidden = !text; };
    const stepList = () => h('ol', {class: 'creation-steps', 'aria-label': 'Шаги создания работы'}, STEPS.map(([id, label], i) =>
      h('li', {'aria-current': id === S.step ? 'step' : null, class: id === S.step ? 'is-current' : ''}, `${i + 1}. ${label}`)));
    const stepNumber = () => STEPS.findIndex(([id]) => id === S.step) + 1;
    const pictureSrc = () => (S.draft && S.draft.image ? `/api/creation/drafts/${S.draft.id}/picture?v=${S.picture}` : null);
    const chosenFile = () => (fileIn.files && fileIn.files[0]) || null;
    let focusNext = false;
    const focusHeading = () => { const el = host.querySelector('h2'); if (el && el.focus) el.focus(); };

    function pictureStep() {
      const saved = S.draft && S.draft.image;
      const shownName = filePicker.querySelector('.file-name');
      if (shownName && saved && !chosenFile()) shownName.textContent = `${saved.name} · сохранена в задаче`;      // the task keeps the picture: the person need not choose it again
      return h('div', {class: 'stack'},
        h('div', {class: 'card stack'}, h('div', {class: 'grid g2'},
          field('Картинка', filePicker, saved && !chosenFile() ? 'выберите другую, чтобы заменить' : 'PNG, JPEG, TIFF'),
          field('Название работы', nameIn), field('Ширина на титане, мм', widthIn, 'высота — по пропорциям картинки')),
          saved && pictureSrc() ? h('figure', {class: 'creation-picture'}, h('img', {src: pictureSrc(), alt: `Картинка задачи: ${saved.name}`}),
            h('figcaption', {class: 'muted small'}, 'Сохранённая картинка')) : null),
        strip.el,
        error,
        h('p', {class: 'small muted'}, 'Нужны надпись или своя задача слоя? ', link('/vector?new=1&classic=1', 'Форма со всеми стратегиями')),
        h('div', {class: 'row'}, btn('Дальше →', toResult, 'primary')));
    }

    function tileView(r) {
      const slot = h('span', {class: 'creation-tile-slot'}), status = h('span', {}), facts = h('span', {class: 'small muted'});
      const node = h('button', {type: 'button', role: 'radio', class: 'creation-tile', onClick: () => choose(r.id)},
        slot, h('strong', {}, r.title), h('span', {class: 'small'}, r.about), facts, h('span', {class: 'small muted'}, r.file), status);
      const update = () => {
        const t = S.tiles[r.id] || {state: 'loading'}, ready = S.readiness[r.id], chosen = S.result === r.id;
        node.setAttribute('aria-checked', chosen ? 'true' : 'false');
        node.setAttribute('tabindex', (S.result || RESULTS[0].id) === r.id ? '0' : '-1');                 // one tab stop for the group, the arrows move inside it
        node.setAttribute('aria-busy', t.state === 'loading' ? 'true' : 'false');
        node.className = 'creation-tile' + (chosen ? ' is-chosen' : '');
        fill(slot, t.state === 'ready' ? h('img', {src: t.src, alt: `Ваша картинка: ${r.title.toLowerCase()}. ${FACTS[r.id](t.facts)}`})
          : h('span', {class: 'creation-tile-wait muted small', role: 'status'}, t.state === 'failed' ? `Не удалось нарисовать: ${t.error}` : 'Рисуем…'));
        fill(facts, t.state === 'ready' ? FACTS[r.id](t.facts) : '');
        fill(status, !ready ? pill('проверяем', '') : ready.error ? pill('не проверено', 'warn') : ready.ready ? pill('можно создать', 'ok')
          : ready.missing.includes('measurements') ? pill('нужны измерения', 'warn') : pill('не хватает: ' + ready.missing.map((k) => ({laser: 'лазер', titanium: 'титан', lens: 'линза'}[k] || k)).join(', '), 'warn'));
      };
      tileViews[r.id] = {node, update};
      update();
      return node;
    }
    let nextButton = null;
    const syncNext = () => { if (nextButton) nextButton.disabled = !S.result; };
    /** Choose a result; the choice is saved with the task. */
    function choose(id) {
      S.result = id;
      autosave();
      for (const v of Object.values(tileViews)) v.update();
      syncNext();
    }
    /** The group answers the arrows like a group of radio buttons: the choice moves with the keyboard. */
    function arrows(ev) {
      const at = RESULTS.findIndex((r) => (S.result || RESULTS[0].id) === r.id);
      const to = {ArrowRight: at + 1, ArrowDown: at + 1, ArrowLeft: at - 1, ArrowUp: at - 1, Home: 0, End: RESULTS.length - 1}[ev.key];
      if (to === undefined) return;
      ev.preventDefault();
      const next = RESULTS[(to + RESULTS.length) % RESULTS.length];
      choose(next.id);
      tileViews[next.id].node.focus();
    }

    function resultStep() {
      return h('div', {class: 'stack'},
        h('p', {class: 'muted small'}, 'Это ваша картинка шириной ' + `${widthIn.value} мм`.replace('.', ',') + ', как её сделает каждый способ. Цвета титана подбираются позже, по измерениям выбранной установки.'),
        h('div', {class: 'creation-tiles', role: 'radiogroup', 'aria-label': 'Что получится', onKeydown: arrows}, RESULTS.map(tileView)),
        strip.el, error,
        h('div', {class: 'row'}, btn('← Назад', () => goTo('picture')), (nextButton = btn('Дальше →', toMethod, 'primary', !S.result))));
    }

    function gate(r, ready) {
      const items = ready.missing.filter((k) => k !== 'measurements').map((k) => {
        const [text, to, label] = MISSING[k];
        return h('li', {}, text, ' ', link(to, label));
      });
      const test = ready.starter_test;
      return h('div', {class: 'alert warn stack', role: 'region', 'aria-label': 'Чего не хватает'},
        h('strong', {}, `Чтобы создать «${r.title.toLowerCase()}», пока не хватает:`),
        items.length ? h('ul', {}, items) : null,
        ready.missing.includes('measurements') ? starterCard(r, ready, test) : null,
        h('p', {class: 'small'}, 'Введённое сохранено в задаче. Когда всё будет готово, откройте её из полосы «Не закончена работа» вверху любого экрана — это можно сделать и после перезапуска приложения.'));
    }

    function starterCard(r, ready, test) {
      if (!test) return h('p', {}, 'Нужны измерения этого лазера, линзы и титана. Сначала добавьте недостающее выше: тест гравируется через линзу на заготовке.');
      const made = S.starter;
      return h('div', {class: 'stack'},
        h('p', {}, h('strong', {}, 'Нужны измерения. '), r.needs),
        h('p', {}, h('strong', {}, 'Начальный тест: '), test.test_type ? (S.plateNames[test.test_type] || test.test_type) : 'следующий шаг уже готов',
          test.guide && test.guide.message ? ` — ${test.guide.message}` : ''),
        test.guide && test.guide.next_step ? h('p', {class: 'small'}, test.guide.next_step) : null,
        h('p', {class: 'small'}, h('strong', {}, 'Что станет доступно: '), BECOMES[test.becomes] || ''),
        r.id === 'photo' || r.id === 'colour' ? h('p', {class: 'small muted'}, 'Если измерения есть в выпуске подключённой лаборатории, выберите его кнопкой «Изменить…» в контексте выше.') : null,
        test.needs_rig ? h('p', {class: 'small'}, 'Чтобы добавить фотографию теста, нужна установка съёмки: ', link('/setup?tab=rigs', 'Добавить установку съёмки')) : null,
        made ? h('p', {class: 'alert ok small', role: 'status'}, `Тест создан: ${made.name}. `, link('/experiment/plan-' + made.plan_id, 'Открыть тест')) : null,
        h('div', {class: 'row'}, test.guide && test.guide.pending_plan_id ? link('/plans/' + test.guide.pending_plan_id, 'Открыть уже созданный тест')
          : r.id === 'photo' ? btn('Создать тест «Шкалы серого»…', () => startTest(r, test), 'primary')
          : btn('Создать начальный тест', (ev) => { const self = ev.currentTarget; return makeStarter(r, self); }, 'primary', !test.test_type)));
    }

    async function startTest(r, test) {
      S.waiting = {for: 'starter_test', result: r.id};
      await flush();
      await refreshBar();
      await PlateDialog.open(lists.devices, null, null, {type: test.test_type, device: S.context.device_id, material: S.context.material_id});
    }
    async function makeStarter(r, button) {
      button.disabled = true;
      try {
        S.waiting = {for: 'starter_test', result: r.id};
        await flush();
        const made = await post('/creation/starter-plate', {result: r.id});
        S.starter = (made.parts && made.parts[0]) || made;
        toast('Тест создан: выгравируйте его и добавьте фотографию', 'ok');
        await loadReadiness();
        drawStep();
      } catch (e) { fail(e); button.disabled = false; }
    }

    const kindLine = () => {
      S.kindText = h('span', {}, PhotoPanels.kindName(S.kind || PhotoPanels.GRAYSCALE));          // follows the mark in the question, also after «← Назад»
      return h('p', {class: 'small'}, h('strong', {}, 'Вид гравировки: '), S.kindText,
        '. Следующее окно покажет вашу картинку в каждом виде: вид выбирается до того, как работа будет создана.');
    };

    function methodFields(r) {
      if (r.id === 'photo') {
        return h('p', {class: 'small muted'}, S.context.source
          ? 'Шкала — лучшая из измеренных в выпуске лаборатории; шкалу, Min, Max и ширину можно поменять в работе.'
          : 'Шкала — лучшая из измеренных, Min и Max — её измеренный диапазон; шкалу, Min, Max, ширину и подбор серых можно поменять в работе.');
      }
      const thr = h('label', {class: 'f'}, h('span', {}, 'Допуск ΔE'), M.thr, h('span', {class: 'small muted'}, toleranceHint()));
      const remember = h('label', {class: 'row small', hidden: S.rules !== null}, M.remember, h('span', {}, 'Запомнить для этого лазера с линзой'));
      const common = [h('div', {class: 'f'}, thr, remember), field(r.id === 'colour' ? 'Сглаживание границ, мм' : 'Точность контура, мм', M.tolerance),
        h('label', {class: 'row'}, M.markers, h('span', {}, 'Регистрационные маркеры и идентификатор вне изображения'))];
      if (r.id === 'colour') {
        return h('div', {class: 'grid g2'}, field('Алгоритм разбиения', M.algorithm.select), field('Число цветов', M.colours, '2–29, с маркерами 2–28: чистка — первый слой'),
          M.algorithm.hint, field('Детальность', M.detail, 'крупно — спокойные большие области, детально — мелкие'),
          field('Наибольшее время гравировки, с/см²', M.maxTime, 'пусто — без предела; медленные цвета автоматика не берёт'),
          h('label', {class: 'row'}, M.faces, h('span', {}, 'Искать лица: глаза и губы делятся подробнее')),
          h('label', {class: 'row'}, M.asShot, h('span', {}, 'Включить цвета без привязки (сняты без эталона и без чистого титана)')), ...common);
      }
      return h('div', {class: 'grid g2'}, field('Порог серого', M.grey, 'пусто — автоматически'), h('label', {class: 'row'}, M.clean, h('span', {}, 'Чистка первым слоем (C00)')), ...common);
    }

    function methodStep() {
      const r = RESULT[S.result], ready = S.readiness[S.result];
      const blocked = !ready || !ready.ready;
      const open = r.id !== 'photo' && S.rules === null;
      const details = r.id === 'photo' ? h('div', {class: 'stack'}, methodFields(r), kindLine()) : h('details', {class: 'creation-advanced', open: open ? '' : null},
        h('summary', {}, 'Дополнительно: алгоритм, допуск ΔE, сглаживание, время'), methodFields(r));
      return h('div', {class: 'stack'},
        h('div', {class: 'card stack'}, h('div', {class: 'row'}, pictureSrc() ? h('img', {class: 'creation-thumb', src: pictureSrc(), alt: 'Картинка задачи'}) : null,
          h('div', {}, h('strong', {}, nameIn.value.trim() || 'без названия'), h('p', {class: 'small muted'}, `${r.title} · ширина ${widthIn.value} мм`),
            h('p', {class: 'small'}, r.file))), details),
        strip.el,
        S.returned && ready && ready.ready ? h('p', {class: 'alert ok', role: 'status'}, 'Недостающее добавлено: можно создавать работу. Картинка, название и настройки остались как были.') : null,
        blocked && ready && !ready.error ? gate(r, ready) : null,
        ready && ready.error ? h('p', {class: 'alert bad', role: 'alert'}, `Не удалось проверить, чего не хватает: ${ready.error}`) : null,
        error,
        h('div', {class: 'row'}, btn('← Назад', () => goTo('result')), btn(r.id === 'photo' ? 'Дальше: какая гравировка →' : 'Создать работу', create, 'primary', blocked)));
    }

    function unfinished() {
      const others = drafts.filter((d) => !S.draft || d.id !== S.draft.id);
      if (!others.length || S.draft) return null;
      return h('section', {class: 'card stack', 'aria-label': 'Незавершённые задачи'}, h('h3', {}, `Незавершённые задачи: ${others.length}`),
        others.slice(0, 5).map((d) => h('div', {class: 'row'}, h('strong', {}, d.name || (d.image && baseName(d.image.name)) || 'без названия'),
          h('span', {class: 'small muted'}, (d.state && d.state.result && RESULT[d.state.result] ? RESULT[d.state.result].title : 'результат не выбран')),
          h('span', {class: 'spacer'}), btn('Продолжить', () => start({draft: d.id}), 'btn-small primary'), btn('Отменить задачу', () => discard(d, () => App.render()), 'btn-small'))),
        others.length > 5 ? h('p', {class: 'small muted'}, `и ещё ${others.length - 5}`) : null);
    }

    function drawStep() {
      const body = S.step === 'picture' ? pictureStep() : S.step === 'result' ? resultStep() : methodStep();
      fill(host, h('div', {class: 'row'}, h('div', {}, heading(`Новая работа · шаг ${stepNumber()} из ${STEPS.length}: ${STEPS[stepNumber() - 1][1]}`),
        h('p', {class: 'sub'}, 'Картинка, размер и что из неё получится. Пока работа не создана, всё введённое хранится в задаче и переживает перезапуск.')),
        h('span', {class: 'spacer'}), S.draft ? btn('Отменить задачу', () => discard(S.draft, async () => { S.draft = null; await refreshBar(); go('/vector'); }), 'btn-small') : null),
        stepList(), S.missingDraft ? h('p', {class: 'alert warn', role: 'status'}, 'Эта задача уже закончена или отменена, поэтому её нет в списке незавершённых. Начните новую.') : null,
        S.released ? h('p', {class: 'alert warn', role: 'status'}, 'Окно «Какая гравировка?» не было закончено: работа, сделанная только для него, удалена. Выберите вид ещё раз.') : null,
        note, unfinished(), body);
      if (focusNext) { focusNext = false; focusHeading(); }
    }

    async function goTo(step) {
      show('');
      S.step = step;
      focusNext = true;
      if (step === 'result') { await loadReadiness(); RESULTS.forEach((r) => { if (!S.tiles[r.id] || S.tiles[r.id].key !== tileKey(r)) loadTile(r); }); }
      if (step === 'method') {
        await loadReadiness();
        if (S.result !== 'photo') await loadRules();
        const ready = S.readiness[S.result];
        // what the person is going away to do is saved with the task: the bar reminds of it and, after a restart, the task says where it was left
        S.waiting = ready && ready.ready === false ? {for: ready.missing.includes('measurements') && !ready.missing.includes('lens') ? 'starter_test' : 'equipment', result: S.result} : null;
      }
      autosave();
      drawStep();
    }

    async function toResult() {
      show('');
      const file = chosenFile();
      if (!file && !(S.draft && S.draft.image)) { show('Выберите картинку (PNG, JPEG, TIFF)'); fileIn.focus(); return; }
      const width = numberOf(widthIn.value);
      if (!(width > 0)) { show('Ширина на титане должна быть положительным числом миллиметров'); widthIn.focus(); return; }
      if (!nameIn.value.trim() && file) nameIn.value = baseName(file.name);
      S.step = 'result';
      try { await send({file: file && file !== S.uploaded ? file : null}); }
      catch (e) { S.step = 'picture'; show(e.message); return; }                    // a picture that is no picture is told here, and nothing is kept
      await goTo('result');
    }

    async function toMethod() { if (S.result) await goTo('method'); }

    async function pictureBlob() {
      const res = await fetch(`/api/creation/drafts/${S.draft.id}/picture`);
      if (!res.ok) throw new Error('Картинка задачи не найдена: выберите её заново');
      return res.blob();
    }

    async function create(ev) {
      if (S.busy) return;
      show('');
      const r = RESULT[S.result], c = S.context, width = numberOf(widthIn.value);
      if (!(width > 0)) { show('Ширина на титане должна быть положительным числом миллиметров'); return; }
      if (r.work === 'vector' && M.thr.value === '' && S.rules === null) {
        M.thr.focus(); toleranceHint();
        show('Задайте допуск ΔE: для этого лазера с линзой он не сохранён');
        drawStep(); M.thr.focus();
        return;
      }
      S.busy = true;
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const blob = await pictureBlob();
        const fileName = S.draft.image.name, name = nameIn.value.trim() || baseName(fileName) || 'Работа';
        const made = r.work === 'photo' ? await createPhoto(blob, fileName, name, width) : await createVector(r, blob, fileName, name, width);
        // BUG-003: a photograph asks «Какая гравировка?» before it is kept; leaving the question deletes the work and the task stays as it was
        if (r.work === 'photo' && await askKind(made) === null) { self.disabled = false; self.focus(); return; }
        try { await post(`/creation/drafts/${S.draft.id}/complete`, {work_kind: r.work, work_id: made.id}); }
        catch (e) { toast('Работа создана, но задача осталась в списке незавершённых: отмените её', 'warn'); }
        await refreshBar();
        toast(r.work === 'photo' ? 'Работа фотогравировки создана' : 'Векторная работа создана', 'ok');
        go(r.work === 'photo' ? `/photo-engraving?work=${made.id}` : `/vector?plan=${made.id}`);
      } catch (e) { show(e.message); self.disabled = false; }
      finally { S.busy = false; }
    }

    /** «Какая гравировка?» for the photo work just made (PhotoKindStep, the same dialog as in photo engraving). Resolves with the kind the person keeps
        the work in, or null when they left it: the work is deleted and the form is as it was. The task records the work while the question is open
        (``hold``), so a window closed in the middle does not leave it behind: it is deleted when the task is opened again (``releaseHold``). */
    function askKind(made) {
      const held = {id: made.id, created_at: made.created_at};
      return new Promise((resolve) => {
        S.hold = held;
        flush();
        PhotoKindStep.open(made.id, {
          title: 'Новая работа · какая гравировка?', initial: S.kind || PhotoPanels.GRAYSCALE,
          onChoose: (key) => { S.kind = key; if (S.kindText) fill(S.kindText, PhotoPanels.kindName(key)); autosave(); },
          before: async () => {                       // from here the work is the person's: the task must no longer point at it
            S.hold = null;
            try { await send(); } catch (e) { S.hold = held; throw e; }
          },
          failed: async () => { S.hold = held; await flush(); },
          onKept: (key) => resolve(key),
          onLeft: () => { S.hold = null; flush(); resolve(null); }});
      });
    }

    /** Deletes the work a closed window left only for the question of the kind, if it is still that very work (the task says its number and time). */
    async function releaseHold() {
      const held = S.hold;
      if (!held) return;
      S.hold = null;
      try {
        const now = await get(`/photo-works/${held.id}`);
        if (now.created_at === held.created_at) { await del('/plans/' + held.id); S.released = true; }
      } catch (_) { /* the work is gone or is not the same one: nothing to delete */ }
      autosave();
    }

    async function createVector(r, blob, fileName, name, width) {
      const c = S.context, m = methodState();
      const fd = new FormData();
      fd.append('device_id', c.device_id); fd.append('lens_id', lensField(c)); fd.append('material_id', c.material_id); fd.append('name', name);
      fd.append('width_mm', width); fd.append('strategy', r.strategy); fd.append('tolerance_mm', m.tolerance); fd.append('markers', m.markers);
      fd.append('image', blob, fileName);
      if (m.thr !== '') fd.append('threshold', m.thr);
      if (r.id === 'colour') {
        fd.append('n_colors', m.colours); fd.append('algorithm', m.algorithm); fd.append('detail', m.detail); fd.append('faces', m.faces); fd.append('include_as_shot', m.asShot);
        if (m.maxTime !== '') fd.append('max_time', m.maxTime);
        if (c.source) { const {label, ...pin} = c.source; fd.append('source', JSON.stringify(pin)); }
      } else {
        fd.append('clean', m.clean);
        if (m.grey !== '') fd.append('grey_threshold', m.grey);
      }
      if (m.thr !== '' && S.rules === null && m.remember) {
        await put('/rules', {device_id: c.device_id, lens_id: c.lens_id, delta_tolerance: +m.thr});    // a tolerance typed while the rules hold none is saved to them, once
        S.rules = +m.thr;
      }
      return form('/vector', fd);
    }

    async function createPhoto(blob, fileName, name, width) {
      const c = S.context;
      const fd = new FormData();
      fd.append('picture', blob, fileName); fd.append('name', name); fd.append('width_mm', width);
      if (c.source) { const {label, ...pin} = c.source; fd.append('source', JSON.stringify({...pin, device_id: c.device_id, lens_id: c.lens_id})); }
      else {
        // the work is made on the best scale of the context's own laser, lens and titanium, not on whichever scale the workshop measured best
        const mode = await App.contextScale(c, width);
        if (!mode) throw new Error('Для выбранных лазера, линзы и титана нет измеренной шкалы серого. Откройте задачу заново: проверка недостающего покажет, что сделать');
        fd.append('scale', JSON.stringify(mode));
      }
      return form('/photo-works', fd);
    }

    S.plateNames = Object.fromEntries(plateTypes.map((row) => [row.id, row.name]));
    await releaseHold();
    if (S.step === 'result' && S.draft) { await loadReadiness(); RESULTS.forEach(loadTile); }
    if (S.step === 'method' && S.draft) {
      await loadReadiness();
      if (S.result !== 'photo') await loadRules();
      const ready = S.readiness[S.result];
      if (S.waiting && ready && ready.ready) { S.returned = true; S.waiting = null; autosave(); }          // came back from setting up what was missing
    }
    focusNext = false;
    drawStep();
    refreshBar();
    setTimeout(focusHeading, 0);                                       // after the router has placed the screen: the keyboard starts at the step's heading
    return host;
  }

  App.register({id: 'new', render});
  mountBar();
  return {start, url, render, refreshBar, RESULTS};
})();
