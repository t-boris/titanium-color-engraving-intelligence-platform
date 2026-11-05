/* The shared register of long operations and the task panel (feature ux-save-feedback-p0, REQ-002).
   An upload, a re-check of the photographs, the connection of a laboratory release and the check of a photograph are written here by the
   transport itself (``App.hooks``, app.js), so no screen has to be rewritten to be seen. Every operation keeps its stage, its progress when the
   server knows it, its result or its error, the way to go on and the section it was started in; the panel is the button at the bottom of every
   page and the operations stay in it when the person goes elsewhere and comes back.
   - Closing the panel closes a list. It never stops an operation.
   - «Остановить» is offered only where the server can stop the operation (an upload before its last byte, a re-check between photographs, the
     connection of a release), after saying what the stop does and does not undo.
   - A screen reader hears the start, each change of stage and the end of an operation (a polite message in the notification area, which stays
     reachable while a dialog is open) and never a clock: the elapsed time is drawn for the eyes only.
   - What the page forgets when it is reloaded or the application is restarted is not kept: a re-check that runs on is on the server, but this
     list does not find it again. That is an open question of the feature, not a decision. */
'use strict';
const Operations = (() => {
  const {h, btn, get, post, fill} = App;
  const config = {pollMs: 1000, giveUpAfter: 5, announceMs: 15000};
  const items = [];                                   // newest first
  const views = new Map();                            // operation id -> its row
  const heard = [];                                   // what a screen reader was told (the tests read it)
  let seq = 0, dock = null, ticker = null, opener = null;                  // opener: the header button that opened the panel last, where the keyboard returns

  const STATE = {running: 'идёт', done: 'готово', failed: 'не удалось', cancelled: 'остановлено'};
  const here = () => {
    const route = (typeof location !== 'undefined' && location.hash ? location.hash : '').replace(/^#/, '') || '/experiments';
    const link = document.querySelector('a.nav-link[aria-current]');
    return {route, label: link ? (link.getAttribute('title') || link.textContent) : route};
  };
  const later = (fn) => { const t = setTimeout(fn, config.pollMs); if (t && t.unref) t.unref(); return t; };
  const clock = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };

  // ---- the announcement --------------------------------------------------------------------------------------------------------------
  /** Say ``text`` to a screen reader, politely. The line lives in the notification area (``.toasts``, as dialogs.js draws it), which a dialog
      leaves reachable when it makes the page inert. */
  function announce(text) {
    heard.push(text);
    if (typeof document === 'undefined' || !document.body) return;
    let box = document.querySelector('.toasts');
    if (!box) { box = h('div', {class: 'toasts', role: 'status', 'aria-live': 'polite'}); document.body.append(box); }
    const line = h('p', {class: 'sr-only'}, text);
    box.append(line);
    const t = setTimeout(() => line.remove(), config.announceMs);
    if (t && t.unref) t.unref();
  }

  // ---- the register ------------------------------------------------------------------------------------------------------------------
  /** Start an operation. ``spec``: kind, title, stage, key (a stable name: a second start with the same key is the same operation), context
      ({route, label}, the section it was started in), details ([[name, value]]: the technical ids), cancel ({effect, run()}: what the stop
      does, and how to do it; none where the server cannot stop it), recover ({label, route}: where to go on after a failure). */
  function begin(spec) {
    if (spec.key) { const same = items.find((o) => o.key === spec.key); if (same) return handle(same); }
    const op = {id: `op${++seq}`, key: spec.key || null, kind: spec.kind, title: spec.title, state: 'running', stage: spec.stage || 'Начинаем…',
      stageKey: spec.stageKey || spec.stage || 'start', progress: spec.progress ?? null, startedAt: Date.now(), endedAt: null, result: null, error: null,
      context: spec.context || here(), details: spec.details || [], cancel: spec.cancel || null, recover: spec.recover || null, open: spec.open || null, stopping: false};
    items.unshift(op);
    mount(op);
    refresh(op);
    if (!spec.quiet) announce(`${op.title}: ${op.stage}`);
    return handle(op);
  }

  /** The hand an owner of an operation holds: ``update`` for its stage and progress, then one of ``succeed``, ``fail`` or ``cancelled``. */
  function handle(op) {
    const end = (state, patch, say) => {
      if (op.state !== 'running') return false;
      Object.assign(op, patch, {state, endedAt: Date.now(), stopping: false});
      refresh(op);
      announce(say);
      return true;
    };
    return {op,
      update(change) {
        if (op.state !== 'running') return;
        if (change.stage !== undefined && change.stage !== op.stage) {
          op.stage = change.stage;
          const key = change.key ?? change.stage;
          if (key !== op.stageKey) { op.stageKey = key; announce(`${op.title}: ${op.stage}`); }
        }
        for (const k of ['progress', 'details', 'cancel', 'stopping']) if (k in change) op[k] = change[k];
        refresh(op);
      },
      succeed(text = 'Готово') { return end('done', {result: text, progress: op.progress == null ? null : 100}, `${op.title}: ${text}`); },
      fail(text, recover) { return end('failed', {error: text, recover: recover || op.recover}, `${op.title}: не удалось. ${text}`); },
      cancelled(text = 'Остановлено') { return end('cancelled', {result: text}, `${op.title}: остановлено. ${text}`); }};
  }

  /** A result the person has to be told about although the screen that asked for it is gone (an upload that ended after they went elsewhere):
      a finished item in the panel with a button to open the result, and a polite announcement. ``open``: {label, route}. */
  function notify({title, message, context, open: opener, details, kind = 'result'}) {
    const owner = begin({kind, title, stage: message, context, details, open: opener, quiet: true});
    owner.succeed(message);
    return owner;
  }
  /** Where a long action began: ``origin.left()`` is true once the person has gone to another screen (the address changed, or the control they
      pressed was taken off the page). A screen that is not on the page at all (a test, a preview) is never «left». */
  function startedAt(control) {
    const hash = typeof location !== 'undefined' ? location.hash : '';
    const attached = !!(control && control.isConnected);
    return {left: () => (typeof location !== 'undefined' && location.hash !== hash) || (attached && !control.isConnected)};
  }
  /** The end of an action that normally takes the person on to ``route``: they are taken there when they are still on the screen; otherwise the
      result goes to the panel and the screen they are on now is left alone. Returns true when the person was taken on. */
  function finish(origin, {route, title, message, openLabel = 'Открыть результат', context, details, goOptions = {preserveScroll: true}}) {
    if (!origin.left()) { App.go(route, goOptions); return true; }
    notify({title, message, context, details, open: {label: openLabel, route}});
    return false;
  }

  /** A failure that has no operation behind it (a change of a document that could not be saved when its screen was gone). */
  function report({kind = 'save', title, message, context, recover, details}) {
    const owner = begin({kind, title, stage: 'Не удалось', context, recover, details, quiet: true});
    owner.fail(message);
    return owner;
  }
  const forget = (id) => {
    const at = items.findIndex((o) => o.id === id && o.state !== 'running');
    if (at < 0) return;
    items.splice(at, 1);
    const view = views.get(id);
    if (view) view.el.remove();
    views.delete(id);
    paint();
  };
  const clearFinished = () => { for (const o of items.filter((x) => x.state !== 'running')) forget(o.id); };

  // ---- the panel -----------------------------------------------------------------------------------------------------------------------
  function ensureDock() {
    if (dock && dock.el.isConnected) return dock;
    const list = h('ul', {class: 'ops-list'});
    const empty = h('p', {class: 'small ops-empty'}, 'Сейчас нет ни одной задачи. Загрузка файла, перепроверка и подключение выпуска появятся здесь.');
    const toggle = h('button', {type: 'button', class: 'btn ops-toggle', 'aria-expanded': 'false', 'aria-controls': 'ops-panel'});
    const back = () => { (opener && opener.isConnected ? opener : toggle).focus(); };
    const close = h('button', {type: 'button', class: 'btn', 'aria-label': 'Свернуть список задач', onClick: () => { open(false); back(); }}, '×');
    const panel = h('section', {class: 'ops-panel', id: 'ops-panel', 'aria-label': 'Фоновые задачи', hidden: true},
      h('div', {class: 'row'}, h('h3', {}, 'Фоновые задачи'), h('span', {class: 'spacer'}), close),
      h('p', {class: 'small muted'}, 'Закрыть список — не значит остановить задачу: она идёт дальше. Список не сохраняется, если страницу перезагрузить или закрыть приложение.'),
      empty, list, h('div', {class: 'row'}, btn('Убрать завершённые', clearFinished, 'btn-small')));
    const el = h('div', {class: 'ops-dock', hidden: true}, panel, toggle);
    toggle.addEventListener('click', () => open(panel.hidden));
    panel.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') { open(false); back(); } });
    document.body.append(el);
    dock = {el, list, toggle, panel, empty};
    for (const op of [...items].reverse()) mount(op, true);
    return dock;
  }
  function open(on) {
    const d = ensureDock();
    d.panel.hidden = !on;
    d.toggle.setAttribute('aria-expanded', String(on));
    paint();
    tick();
  }
  /** The button: how many operations run and how many ended badly (or need a look), in words. */
  function paint() {
    paintEntries();
    if (!dock) return;
    const running = items.filter((o) => o.state === 'running').length;
    const bad = items.filter((o) => o.state === 'failed').length;
    const parts = [running ? `идёт: ${running}` : null, bad ? `требуют внимания: ${bad}` : null,
      !running && !bad ? `завершено: ${items.length}` : null].filter(Boolean);
    dock.toggle.textContent = `Задачи — ${parts.join(', ')}`;
    dock.empty.hidden = items.length > 0;
    dock.el.hidden = items.length === 0 && dock.panel.hidden;               // an empty list is drawn only while the person has asked to see it
    dock.el.setAttribute('data-state', bad ? 'attention' : running ? 'running' : 'idle');
  }

  // ---- the entry in the page header ---------------------------------------------------------------------------------------------------
  /** The header button that opens the task panel (the panel's own button stays at the bottom of the page). It says how many tasks run, in words
      and not only by a number, so it is not just a coloured dot. The page header is drawn anew with every screen, so the buttons made here are
      remembered only while they are on the page. */
  const entries = new Set();
  function entry() {
    const button = h('button', {type: 'button', class: 'btn ops-entry', 'aria-controls': 'ops-panel', 'aria-expanded': 'false'});
    button.addEventListener('click', () => {                    // the panel stands at the end of the page: the keyboard goes into it when it opens and back when it shuts
      const on = !(dock && !dock.panel.hidden);
      opener = button;
      open(on);
      if (on) dock.panel.querySelector('button').focus(); else button.focus();
    });
    for (const old of [...entries]) if (!old.isConnected) entries.delete(old);       // the buttons of screens that are gone
    entries.add(button);
    paintEntries();
    return button;
  }
  function paintEntries() {
    const running = items.filter((o) => o.state === 'running').length;
    const bad = items.filter((o) => o.state === 'failed').length;
    const opened = !!(dock && !dock.panel.hidden);
    for (const button of [...entries]) {
      button.textContent = running ? `Задачи: идёт ${running}` : bad ? `Задачи: требуют внимания ${bad}` : 'Задачи';
      button.setAttribute('aria-expanded', String(opened));
      button.setAttribute('data-state', bad ? 'attention' : running ? 'running' : 'idle');
    }
  }
  /** The clock of the rows runs while the list is open and something runs: a visual aid only, never announced. */
  function tick() {
    const watching = dock && !dock.panel.hidden && items.some((o) => o.state === 'running');
    if (watching && !ticker) {
      ticker = setInterval(() => { for (const o of items) if (o.state === 'running') refresh(o); if (!items.some((o) => o.state === 'running')) tick(); }, 1000);
      if (ticker.unref) ticker.unref();
    } else if (!watching && ticker) { clearInterval(ticker); ticker = null; }
  }

  function mount(op, again = false) {
    const d = ensureDock();
    if (views.has(op.id) && !again) return;
    const stage = h('p', {class: 'small ops-stage'});
    const bar = h('progress', {max: '100', 'aria-label': `Ход: ${op.title}`});
    const elapsed = h('span', {class: 'small muted', 'aria-hidden': 'true'});
    const where = h('span', {class: 'small muted'});
    const outcome = h('p', {class: 'small'});
    const badge = h('span', {class: 'pill'});
    const stop = btn('Остановить', () => askToStop(op), 'btn-small');
    const goOn = btn('', () => App.go(op.recover.route), 'btn-small primary');
    const back = btn('Открыть раздел', () => App.go(op.context.route), 'btn-small');
    const openIt = btn('', () => App.go(op.open.route), 'btn-small primary');
    const dismiss = btn('Убрать из списка', () => forget(op.id), 'btn-small');
    const facts = h('details', {class: 'small ops-details'}, h('summary', {}, 'Подробности'), h('dl', {class: 'facts'}));
    const el = h('li', {class: 'ops-item', 'data-state': op.state},
      h('div', {class: 'row'}, h('strong', {}, op.title), h('span', {class: 'spacer'}), badge), stage, bar,
      h('div', {class: 'row'}, elapsed, where), outcome, h('div', {class: 'row'}, stop, goOn, openIt, back, dismiss), facts);
    views.set(op.id, {el, stage, bar, elapsed, where, outcome, badge, stop, goOn, openIt, back, dismiss, facts});
    d.list.prepend(el);                                 // the newest on top
  }
  function refresh(op) {
    const v = views.get(op.id);
    if (!v) { paint(); return; }
    const running = op.state === 'running';
    v.el.setAttribute('data-state', op.state);
    fill(v.badge, STATE[op.state]);
    v.badge.className = 'pill ' + (op.state === 'done' ? 'ok' : op.state === 'failed' ? 'bad' : op.state === 'cancelled' ? 'warn' : '');
    fill(v.stage, op.stopping ? `${op.stage} (остановка запрошена)` : op.stage);
    v.stage.hidden = !running;
    v.bar.hidden = !running;
    if (op.progress == null) v.bar.removeAttribute('value'); else v.bar.setAttribute('value', String(Math.round(op.progress)));
    fill(v.elapsed, `${running ? 'Идёт' : 'Заняло'} ${clock((op.endedAt || Date.now()) - op.startedAt)}`);
    fill(v.where, `Начато в разделе «${op.context.label}»`);
    fill(v.outcome, op.state === 'failed' ? `Не удалось: ${op.error}` : op.state === 'cancelled' ? op.result : op.state === 'done' ? op.result : '');
    v.outcome.className = 'small ' + (op.state === 'failed' ? 'alert bad' : '');
    v.outcome.hidden = running;
    v.stop.hidden = !(running && op.cancel);
    v.stop.disabled = !!op.stopping;
    v.goOn.hidden = !(op.state === 'failed' && op.recover);
    if (op.recover) fill(v.goOn, op.recover.label);
    v.openIt.hidden = !(op.state === 'done' && op.open);                    // the way to the result of something that ended while the person was elsewhere
    if (op.open) fill(v.openIt, op.open.label);
    // «Открыть раздел» next to a recovery action that goes to the same place says the same thing twice
    if (v.back) v.back.hidden = !!((op.state === 'failed' && op.recover && op.recover.route === op.context.route) || (op.state === 'done' && op.open && op.open.route === op.context.route));
    v.dismiss.hidden = running;
    const rows = op.details.filter(([, value]) => value != null && value !== '');
    v.facts.hidden = !rows.length;
    fill(v.facts.querySelector('dl'), rows.map(([k, value]) => [h('dt', {}, k), h('dd', {}, String(value))]));
    paint();
    tick();
  }

  /** «Остановить»: first what the stop does, then the stop. The row says it was asked for until the server confirms the end. */
  function askToStop(op) {
    if (!op.cancel || op.state !== 'running') return;
    App.confirmBox(`Остановить: ${op.title}?`, op.cancel.effect, 'Остановить', async () => {
      if (op.state !== 'running') return;
      await op.cancel.run();
      if (op.state === 'running') { op.stopping = true; refresh(op); announce(`${op.title}: остановка запрошена`); }
    });
  }

  // ---- what the transport tells ------------------------------------------------------------------------------------------------------
  const FILE_KINDS = [
    [/^\/pairs\/(\d+)\/rephotos$/, (m) => ({title: 'Загрузка повторной фотографии', details: [['Исходная пара', `№ ${m[1]}`]]})],
    [/^\/matrix-pairs$/, () => ({title: 'Загрузка фотографии пластины с матрицей', details: []})],
    [/^\/pairs$/, () => ({title: 'Загрузка фотографии гравировки', details: []})],
    [/^\/labs\/files$/, () => ({title: 'Чтение файла выпуска лаборатории', details: []})]];
  const fileNameOf = (fd) => {
    try { for (const [, v] of (fd && fd.entries ? fd.entries() : [])) if (v && typeof v === 'object' && v.name) return v.name; } catch (_) { /* not a form */ }
    return null;
  };
  const RECOVER_UPLOAD = 'Выбрать файл снова';

  /** An upload (``App.formProgress``): it can be stopped until its last byte is sent; after that the server is working and cannot be stopped. */
  function watchUpload({path, fd, abort}) {
    const known = FILE_KINDS.map(([re, make]) => { const m = path.match(re); return m ? make(m) : null; }).find(Boolean) || {title: 'Загрузка файла', details: []};
    const name = fileNameOf(fd);
    const owner = begin({kind: 'upload', title: known.title, stage: 'Передаём файл на сервер', stageKey: 'sending', progress: 0, details: [...known.details, ['Файл', name], ['Адрес', path]],
      cancel: {run: () => abort(), effect: 'Передача прервётся, пока сервер не получил файл целиком, поэтому фотография в базу не попадёт. Выбрать файл придётся заново.'},
      recover: {label: RECOVER_UPLOAD, route: here().route}});
    return {
      progress(percent) {
        if (percent >= 100) owner.update({stage: 'Файл передан, сервер разбирает его', key: 'processing', progress: null, cancel: null});
        else owner.update({stage: `Передаём файл на сервер: ${percent} %`, key: 'sending', progress: percent});
      },
      ok() { owner.succeed('Файл загружен'); },
      fail(error) { owner.fail(error.message); },
      cancelled() { owner.cancelled('Загрузка остановлена, файл не добавлен.'); }};
  }

  /** Poll ``read`` until ``onData`` says «stop»; a server that does not answer is waited for, then reported. */
  function follow(read, onData, onLost, onTrouble) {
    let misses = 0;
    const step = async () => {
      let data;
      try { data = await read(); misses = 0; }
      catch (e) {
        misses += 1;
        if (misses >= config.giveUpAfter) { onLost(e); return; }
        if (onTrouble) onTrouble(e);
        later(step);
        return;
      }
      if (onData(data) !== 'stop') later(step);
    };
    later(step);
  }
  const LOST = 'Не удаётся узнать, чем закончилась задача: сервис не отвечает. Откройте раздел и проверьте результат.';

  // the re-check of every photograph (findings): backup, then the photographs one by one, then the findings drawn anew
  const RECHECK_END = {done: 'Перепроверка закончена', cancelled: 'Перепроверка остановлена', failed: 'Перепроверка не удалась',
    interrupted: 'Перепроверка прервана: приложение было закрыто. Запустите её снова.'};
  const count = (r, status) => (r.photos || []).filter((p) => p.status === status).length;
  const recheckStage = (s) => {
    const c = s.current;
    const left = s.done && s.total > s.done ? ` · осталось ≈ ${clock(s.elapsed_s / s.done * (s.total - s.done) * 1000)}` : '';
    return s.phase === 'remeasure' ? `Перемеряю фотографию ${Math.min(s.done + 1, s.total)} из ${s.total}` + (c ? ` · ${c.title || c.photo_name}` : '') + left
      : s.phase === 'backup' ? 'Делаю резервную копию мастерской' : s.phase === 'analysis' ? 'Пересчитываю выводы по новым измерениям' : String(s.phase);
  };
  function followRecheck(r, context) {
    const owner = begin({kind: 'recheck', key: `recheck:${r.id}`, title: 'Перепроверка всех работ', context, details: [['Номер перепроверки', r.id]],
      stage: recheckStage(r), stageKey: r.phase, progress: r.phase === 'remeasure' && r.total ? r.done / r.total * 100 : null,
      cancel: {run: () => post(`/recheck/${r.id}/stop`, {}),
        effect: 'Перепроверка остановится после фотографии, которая измеряется сейчас. Уже перемеренные фотографии останутся заменёнными, выводы будут сделаны по ним. '
          + 'Вернуть прежнее можно только из резервной копии, которую программа делает в начале.'},
      recover: {label: 'Открыть и запустить снова', route: (context || here()).route}});
    if (owner.op.state !== 'running' || owner.op.polling) return;
    owner.op.polling = true;
    const show = (s) => owner.update({stage: recheckStage(s), key: s.phase, progress: s.phase === 'remeasure' && s.total ? s.done / s.total * 100 : null});
    const end = (s) => {
      const line = `заменено ${count(s, 'replaced')}, оставлено прежних ${count(s, 'kept')}, не удалось ${count(s, 'failed')}`;
      if (s.status === 'done') owner.succeed(`${RECHECK_END.done}: ${line}. Выводы пересчитаны.`);
      else if (s.status === 'cancelled') owner.cancelled(`${RECHECK_END.cancelled}: ${line}. Выводы сделаны по тому, что успели измерить.`);
      else owner.fail(`${RECHECK_END[s.status] || s.status}${s.error ? ` (${s.error})` : ''}. ${line}.`);
    };
    show(r);
    if (r.status && r.status !== 'running') { end(r); return; }
    follow(() => get(`/recheck/${r.id}`), (s) => { if (s.status === 'running') { show(s); return null; } end(s); return 'stop'; },
      () => owner.fail(LOST), () => owner.update({stage: 'Нет ответа от сервиса, жду…', key: 'waiting'}));
  }

  // the connection of a laboratory release (a file, or the cloud) and the publication of a release
  const JOB_PHASE = {waiting: 'ожидание', downloading: 'загрузка из облака', checking: 'проверка файла', building: 'сборка снимка', activating: 'подключение',
    connecting: 'подключение на этом компьютере', reserving: 'резервирование места в облаке', exporting: 'запись выпуска', uploading: 'передача в облако',
    finalizing: 'завершение'};
  const JOBS = {
    file: {title: 'Подключение выпуска лаборатории', jobs: '/labs/jobs', done: 'Выпуск подключён: его можно выбирать источником новых работ.', unchanged: 'Этот выпуск уже был подключён: ничего не изменилось.',
      effect: 'Подключение остановится. Ничего не будет подключено: прочитанный файл удалится, а данные мастерской останутся такими, какими были.', recover: 'Выбрать файл снова'},
    cloud: {title: 'Подключение выпуска из облака', jobs: '/cloud/jobs', done: 'Выпуск подключён: его можно выбирать источником новых работ.', unchanged: 'Этот выпуск уже был подключён: ничего не изменилось.',
      effect: 'Подключение остановится. Ничего не будет подключено: загруженное удалится, а данные мастерской останутся такими, какими были.', recover: 'Открыть и подключить снова'},
    publish: {title: 'Публикация выпуска в облако', jobs: '/cloud/jobs', done: 'Выпуск опубликован.', unchanged: 'Выпуск опубликован.',
      effect: 'Публикация остановится; по сообщению программы, ничего не изменится. Начать заново можно в разделе «Лаборатории».', recover: 'Открыть и опубликовать снова'}};
  const mb = (n) => `${((n || 0) / 1048576).toFixed(1)} МБ`;
  const jobStage = (s) => `${JOB_PHASE[s.phase] || JOB_PHASE[s.stage] || s.phase}${s.total ? ` · ${mb(s.read)} из ${mb(s.total)}` : ''}`;
  function followJob(job, kind, context) {
    const spec = JOBS[kind];
    const owner = begin({kind: 'import', key: `${spec.jobs}:${job.id}`, title: spec.title, context, details: [['Номер задачи', job.id]],
      stage: jobStage(job), stageKey: job.phase, progress: job.total ? Math.min(100, job.read / job.total * 100) : null,
      cancel: {run: () => post(`${spec.jobs}/${job.id}/cancel`, {}), effect: spec.effect}, recover: {label: spec.recover, route: (context || here()).route}});
    if (owner.op.polling) return;
    owner.op.polling = true;
    const show = (s) => owner.update({stage: jobStage(s), key: s.phase, progress: s.total ? Math.min(100, s.read / s.total * 100) : null});
    const end = (s) => {
      if (s.error && s.phase === 'cancelled') owner.cancelled('Подключение остановлено, ничего не изменилось.');
      else if (s.error) owner.fail(I18N.tr(s.error.message));
      else owner.succeed(s.phase === 'unchanged' ? spec.unchanged : spec.done);
    };
    show(job);
    if (job.done) { end(job); return; }
    follow(() => get(`${spec.jobs}/${job.id}`), (s) => { show(s); if (s.done) { end(s); return 'stop'; } return null; },
      () => owner.fail(LOST), () => owner.update({stage: 'Нет ответа от сервиса, жду…', key: 'waiting'}));
  }

  /** A request that is answered at the end of its work (the check of a photograph): it runs while the request is open; it cannot be stopped. */
  function watchSlow(title, details, recoverLabel) {
    const owner = begin({kind: 'check', title, stage: 'Идёт проверка, пока сервис не ответит', details, recover: {label: recoverLabel, route: here().route}});
    return {ok() { owner.succeed('Проверка закончена'); }, fail(error) { owner.fail(error.message); }};
  }

  const WATCHED = [
    [(m, p) => m === 'POST' && p === '/recheck', (data) => followRecheck(data, here())],
    [(m, p) => m === 'POST' && /^\/labs\/files\/[^/]+\/connect$/.test(p), (data) => followJob(data, 'file', here())],
    [(m, p) => m === 'POST' && /^\/cloud\/releases\/[^/]+\/connect$/.test(p), (data) => followJob(data, 'cloud', here())],
    [(m, p) => m === 'POST' && (p === '/cloud/publish' || p === '/cloud/publish/retry'), (data) => followJob(data, 'publish', here())]];
  function watchRequest({method, path}) {
    const known = WATCHED.find(([test]) => test(method, path));
    if (known) return {ok(data) { if (data && data.id !== undefined) known[1](data); }};
    const photo = method === 'POST' && path.match(/^\/pairs\/(\d+)\/check$/);
    if (photo) return watchSlow('Проверка загруженной фотографии', [['Пара (фото и гравировка)', `№ ${photo[1]}`]], 'Открыть и проверить снова');
    return null;
  }

  App.hooks.upload = watchUpload;
  App.hooks.observe = watchRequest;

  return {begin, report, notify, startedAt, finish, entry, forget, announce, open, config, items: () => items.slice(), heard: () => heard.slice(), followRecheck, followJob};
})();
