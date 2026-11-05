/* Цвет титана — ядро интерфейса: DOM-помощники и обращения к API.
   Окна и уведомления — dialogs.js, маршруты — router.js. Язык интерфейса — русский (DEC-034);
   сообщения сервера переводит I18N. */
'use strict';
const App = (() => {
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === 'class') el.className = v;
      else if (k === 'value') el.value = v;
      else if (k === 'checked' || k === 'disabled' || k === 'hidden' || k === 'selected') el[k] = !!v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  // replace an element's children the way h() appends them: null, undefined and false are skipped, where the DOM's
  // replaceChildren would print them as the text "null"
  function fill(el, ...kids) {
    el.replaceChildren(...kids.flat(Infinity).filter((kid) => kid != null && kid !== false).map((kid) => (kid.nodeType ? kid : String(kid))));
    return el;
  }
  const btn = (label, onClick, cls = '', disabled = false) => h('button', {type: 'button', class: 'btn ' + cls, onClick, disabled}, label);
  /** A labelled field. ``input`` is the control (or a node that holds several), ``help`` an optional explanation under it. Called with three
      arguments it draws exactly what it always drew. ``opts`` (REQ-003 of ux-save-feedback-p0) makes it a field a screen reader can use:
      ``required`` (said in words and as aria-required), ``unit`` (drawn beside the control), ``constraint`` (the permitted range or rule, in
      words). The label text alone names the control (aria-labelledby); unit, constraint, help and error describe it (aria-describedby).
      Every field, with or without ``opts``, answers ``setError(text)`` and ``clearError()``: the message stays beside the input the person
      typed (aria-invalid, aria-describedby) and never changes the input; ``firstControl()`` is its first control, ``errorText()`` the message. */
  let fieldSeq = 0;
  const CONTROL = /^(input|select|textarea)$/;
  const controlsOf = (node) => (!node || node.nodeType !== 1 ? [] : CONTROL.test(node.localName) ? [node] : [...node.querySelectorAll('input, select, textarea')]);
  function field(label, input, help, opts) {
    const id = `f${++fieldSeq}`;
    const labelSpan = h('span', opts ? {id: `${id}-label`} : {}, label);
    const note = help ? h('span', {class: 'small muted', id: opts ? `${id}-help` : null}, help) : null;
    const facts = opts ? [opts.unit ? `единица: ${opts.unit}` : null, opts.constraint || null].filter(Boolean) : [];
    const hint = facts.length ? h('span', {class: 'small muted f-constraint', id: `${id}-hint`}, facts.join(' · ')) : null;
    const body = opts && opts.unit && input ? h('span', {class: 'f-with-unit'}, input, h('span', {class: 'f-unit', 'aria-hidden': 'true'}, opts.unit)) : input;
    const el = h('label', {class: 'f'}, labelSpan, opts && opts.required ? h('span', {class: 'f-required'}, 'обязательно') : null, body, hint, note);
    let failure = null;
    const controls = () => controlsOf(input);                              // read when needed: a screen may fill a composite control after the field is made
    const single = () => { const all = controls(); return all.length === 1 && all[0] === input; };
    const describe = () => {
      if (note && !note.getAttribute('id')) note.setAttribute('id', `${id}-help`);
      const ids = [hint, note, failure].filter(Boolean).map((n) => n.getAttribute('id'));
      for (const c of single() ? [input] : [input, ...controls()]) {
        if (!c || c.nodeType !== 1) continue;
        if (ids.length) c.setAttribute('aria-describedby', ids.join(' ')); else c.removeAttribute('aria-describedby');
      }
    };
    if (opts && input && input.nodeType === 1) {
      input.setAttribute('aria-labelledby', `${id}-label`);                 // the label text alone is the name, not the hints under it
      if (!single()) input.setAttribute('role', 'group');
      if (opts.required) for (const c of controls()) c.setAttribute('aria-required', 'true');
      describe();
    }
    el.setError = (text) => {
      if (!text) { el.clearError(); return; }
      if (!failure) failure = h('span', {class: 'small f-error', id: `${id}-error`});
      failure.textContent = text;
      if (failure.parentNode !== el) el.append(failure);                    // always the last thing in the field
      el.classList.add('has-error');
      for (const c of controls()) c.setAttribute('aria-invalid', 'true');
      describe();
    };
    el.clearError = () => {
      if (failure) failure.remove();
      failure = null;
      el.classList.remove('has-error');
      for (const c of controls()) c.removeAttribute('aria-invalid');
      describe();
    };
    el.firstControl = () => controls()[0] || null;                         // not ``control``: a label's own read-only property
    el.errorText = () => (failure ? failure.textContent : '');
    return el;
  }
  const link = (route, label) => h('a', {href: '#' + route}, label);
  const pill = (text, kind = '') => h('span', {class: 'pill ' + kind}, text);
  const labText = (lab) => (lab ? `L ${(+lab[0]).toFixed(1)} · a ${(+lab[1]).toFixed(1)} · b ${(+lab[2]).toFixed(1)}` : '—');
  const num = (v, d = 2) => (v == null ? '—' : (+v).toFixed(d));
  /** Оценка времени гравировки работы по её файлу LightBurn (REQ-060): итог, что в него не входит, время каждого слоя. */
  function timeBlock(t) {
    if (!t) return h('p', {class: 'muted small'}, 'Время гравировки не оценить: файл работы не читается или ещё не создаётся.');
    return h('div', {class: 'stack'},
      h('p', {}, h('strong', {}, `Время гравировки ≈ ${duration(t.seconds)}`), t.complete ? '' : ' (без слоёв, время которых не оценить)',
        h('span', {class: 'muted small'}, ' — оценка по файлу LightBurn: площадь или длина каждого слоя, скорость, шаг строк, проходы и повторы; переходы между объектами не учтены.')),
      h('details', {class: 'small'}, h('summary', {}, `По слоям (${t.layers.length})`),
        h('ul', {}, t.layers.map((r) => h('li', {}, `${r.name}: `, r.seconds == null ? I18N.tr(r.note) : duration(r.seconds))))));
  }
  /** Длительность в секундах по-русски: «2 ч 05 мин», «4 мин 07 с», «45 с». */
  const duration = (s) => (s == null ? '—' : s >= 3600 ? `${Math.floor(s / 3600)} ч ${String(Math.round(s % 3600 / 60)).padStart(2, '0')} мин`
    : s >= 60 ? `${Math.floor(s / 60)} мин ${String(Math.round(s % 60)).padStart(2, '0')} с` : `${Math.round(s)} с`);
  /** Сколько независимых гравировок настройки дали один цвет (REQ-045): «2 из 3 совпали»; одна гравировка не повторялась. */
  const agreed = (a) => (!a || a.engravings < 2 ? 'не повторялась' : a.differing ? `${a.agreeing} из ${a.engravings} совпали` : `все ${a.engravings} совпали`);
  /** Почему настройку не берёт автоматика: цвет менялся при тех же настройках или те же настройки измерены точнее. */
  const CAUTION = {contradicted: 'цвет менялся при тех же настройках', superseded: 'есть более точное измерение этих настроек'};

  const plural = (n, [one, few, many]) => `${n} ${n % 10 === 1 && n % 100 !== 11 ? one : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? few : many}`;
  /** Откуда взят цвет (REQ-051): тест (плита, проверка лазера, матрица параметров: гравировали, чтобы измерить цвет) или работа (векторная работа
      или любая готовая гравировка: гравировали, чтобы смотреть). */
  const ORIGIN = {test: ['тест', ['тест', 'теста', 'тестов']], work: ['работа', ['работа', 'работы', 'работ']]};
  const kindOf = (s) => (s && s.origin === 'test' ? 'test' : 'work');          // a source with no origin is taken for a work
  /** «2 теста, 1 работа»: из чего известен цвет. */
  const originParts = (sources) => ['test', 'work'].map((kind) => [kind, (sources || []).filter((s) => kindOf(s) === kind).length]).filter(([, n]) => n)
    .map(([kind, n]) => plural(n, ORIGIN[kind][1])).join(', ');
  /** «3 гравировки: 2 теста, 1 работа»: одной строкой, из чего известен цвет. */
  const originText = (sources) => ((sources || []).length ? `${plural(sources.length, ['гравировка', 'гравировки', 'гравировок'])}: ${originParts(sources)}` : 'источники не записаны');
  /** Можно ли верить цвету настройки (REQ-045, REQ-051): ``stable`` — повторён и совпал, ``single`` — одна гравировка, не повторялась,
      ``doubtful`` — гравировки расходятся (кружок на карте меньше, чем у одной гравировки, или цвет менялся). */
  function steadiness(e) {
    const a = e.agreement || {};
    if (a.engravings >= 2 && ((e.doubtful ?? (a.agreeing - 1 - (a.differing || 0) < 0)) || a.contradicted)) return 'doubtful';
    return a.engravings >= 2 && a.agreeing >= 2 ? 'stable' : 'single';
  }
  const STEADY = {stable: ['проверен повтором', 'ok'], single: ['одна гравировка, не повторялась', 'warn'], doubtful: ['сомнительный: гравировки расходятся', 'bad']};
  const day = (iso) => (iso || '').slice(0, 10);
  const MEASURED = {calibrated: ['по эталонной карте', 'ok'], relative: ['относительно камеры', 'warn']};
  /** Где мы знаем цвет (REQ-049, REQ-051): каждая независимая гравировка, откуда она (тест или работа), совпадает ли с цветом настроек и куда посмотреть. */
  function sourcesBlock(sources, a, agreedLab, open = true) {
    const n = sources.length;
    // a few photographs are named in the line; many are a count with a list of links (ux-growing-collections-p0, REQ-002)
    const many = (list) => typeof SourceRefs !== 'undefined' && list.length > SourceRefs.SHORT;
    const row = (s) => h('li', {class: 'cm-source'}, swatch(s.lab), ' ', h('strong', {}, s.title), ' ', pill(ORIGIN[kindOf(s)][0]), ' · ',
      link('/experiment/' + encodeURIComponent(s.experiment), 'эксперимент'), ...(s.work_id ? [' · ', link('/vector?plan=' + s.work_id, 'векторная работа')] : []),
      ...(s.provisional || many(s.pair_ids) ? (s.provisional ? [' · ', pill('предварительно', 'warn')] : []) : s.pair_ids.flatMap((id) => [' · ', link(`/analysis/${id}`, `разбор №${id}`)])),
      h('div', {class: 'muted'}, [day(s.date), s.photos.length && !many(s.photos) ? `фото ${s.photos.join(', ')}` : null, s.layers.length ? s.layers.join(', ') : null].filter(Boolean).join(' · '),
        ' · ', pill(...MEASURED[s.measurement]), ' ', n > 1 ? (s.agrees ? pill('совпадает', 'ok') : pill('расходится', 'warn')) : null,
        n > 1 ? ` · ΔE ${num(s.delta_e, 1)} от цвета настроек` : ''),
      !s.provisional && many(s.pair_ids) ? SourceRefs.refs(s.pair_ids, {label: 'Разборы фото', href: (id) => `/analysis/${id}`}) : null,
      many(s.photos) ? SourceRefs.refs(s.photos, {label: 'Фото', mark: ''}) : null);
    return h('details', {class: 'cm-sources', open},
      h('summary', {}, n > 1 ? `Откуда мы знаем этот цвет: ${n} независимые гравировки (${originParts(sources)})` : `Откуда мы знаем этот цвет: одна гравировка (${ORIGIN[kindOf(sources[0])][0]})`),
      agreedLab && n > 1 ? h('p', {class: 'small'}, 'Цвет настроек: ', swatch(agreedLab), ` ${labText(agreedLab)}`) : null,
      h('ul', {class: 'stack small cm-source-list'}, ...sources.map(row)),
      n > 1 ? h('p', {class: 'muted small'}, `Цвет настроек — среднее гравировок, которые совпали между собой (в пределах ΔE ${num(a && a.limit != null ? a.limit : 5, 0)}); `
        + 'повторное фото той же гравировки повтором не считается.') : null);
  }

  function swatch(lab) {
    const [L, a, b] = lab;
    const fy = (L + 16) / 116, fx = fy + a / 500, fz = fy - b / 200;
    const f = (t) => (t ** 3 > 216 / 24389 ? t ** 3 : (116 * t - 16) / (24389 / 27));
    const [X, Y, Z] = [f(fx) * 0.95047, f(fy), f(fz) * 1.08883];
    const lin = [3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z, -0.969266 * X + 1.8760108 * Y + 0.041556 * Z, 0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z];
    const c = lin.map((v) => Math.round(255 * Math.min(1, Math.max(0, v <= 0.0031308 ? 12.92 * v : 1.055 * Math.pow(v, 1 / 2.4) - 0.055))));
    return h('span', {class: 'sw', style: `background:rgb(${c[0]},${c[1]},${c[2]})`, title: labText(lab)});
  }

  // Seams other modules plug into without the screens knowing about them (operations.js, the task panel): ``observe(method, path, body)`` and
  // ``upload({path, fd, abort})`` each return a watcher or null. A watcher is told what happened and can never break a request.
  const hooks = {observe: null, upload: null};
  const watch = (name, arg) => { try { return hooks[name] ? hooks[name](arg) : null; } catch (_) { return null; } };
  const tell = (watcher, event, ...args) => { try { if (watcher && watcher[event]) watcher[event](...args); } catch (_) { /* a watcher never breaks a request */ } };

  const BODY_SOURCES = ['body', 'query', 'path', 'form', 'header', 'cookie'];
  const LIMIT_WORDS = {gt: (v) => `больше ${v}`, ge: (v) => `не меньше ${v}`, lt: (v) => `меньше ${v}`, le: (v) => `не больше ${v}`};
  const LIMIT_OF = {greater_than: 'gt', greater_than_equal: 'ge', less_than: 'lt', less_than_equal: 'le'};
  /** The text of one item of FastAPI's validation list, in Russian, from its ``type`` and ``ctx`` (nothing is made up: the limits are the server's). */
  function validationText(item) {
    const type = item && item.type;
    if (type === 'missing') return 'Заполните это поле';
    if (/^(float|int|decimal)_(parsing|type)$/.test(type || '')) return 'Введите число';
    if (type === 'int_from_float') return 'Введите целое число';
    if (LIMIT_OF[type] && item.ctx && item.ctx[LIMIT_OF[type]] != null) return `Значение должно быть ${LIMIT_WORDS[LIMIT_OF[type]](item.ctx[LIMIT_OF[type]])}`;
    if (type === 'string_too_short' && item.ctx) return `Слишком коротко: не меньше ${item.ctx.min_length} зн.`;
    if (type === 'string_too_long' && item.ctx) return `Слишком длинно: не больше ${item.ctx.max_length} зн.`;
    return 'Проверьте значение этого поля';
  }
  /** FastAPI's validation list as ``[{field, path, message, type, raw}]``: ``path`` is where the server found the fault (without «body»), ``field`` its last part. */
  function validationDetails(list) {
    return list.filter((item) => item && Array.isArray(item.loc)).map((item) => {
      const loc = BODY_SOURCES.includes(item.loc[0]) ? item.loc.slice(1) : item.loc;
      return {field: String(loc[loc.length - 1] ?? ''), path: loc.join('.'), message: validationText(item), type: item.type, raw: item.msg};
    });
  }

  async function api(method, path, body, isForm) {
    const opts = {method, headers: {}};
    if (body !== undefined) {
      if (isForm) opts.body = body;
      else { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    }
    const watcher = watch('observe', {method, path, body});
    let res;
    try { res = await fetch('/api' + path, opts); }
    catch (_) {
      const failure = Object.assign(new Error('Нет связи с локальным сервисом. Запущено ли приложение?'), {kind: 'network'});
      tell(watcher, 'fail', failure);
      throw failure;
    }
    if (res.status === 204) { tell(watcher, 'ok', null); return null; }
    const json = (res.headers.get('content-type') || '').includes('json');
    const data = json ? await res.json() : await res.blob();
    if (!res.ok) {
      const d = data && data.detail ? data.detail : data;
      const raw = d && d.error ? d.error : (Array.isArray(d) ? 'Проверьте заполнение полей формы'
        : typeof d === 'string' ? d : `Ошибка сервера (${res.status}). Проверка не завершилась.`);
      // ``details`` is what the server said about each field (only FastAPI's own validation list names fields; the application's own
      // refusals {error, kind} do not, and the form then keeps the message as one about the whole form)
      const failure = Object.assign(new Error(I18N.tr(raw)), {kind: d && d.kind, status: res.status}, Array.isArray(d) ? {details: validationDetails(d)} : {});
      tell(watcher, 'fail', failure);
      throw failure;
    }
    tell(watcher, 'ok', data);
    return data;
  }
  const get = (p) => api('GET', p);
  const post = (p, b) => api('POST', p, b === undefined ? {} : b);
  const put = (p, b) => api('PUT', p, b);
  const patch = (p, b) => api('PATCH', p, b);
  const del = (p) => api('DELETE', p);
  const form = (p, fd) => api('POST', p, fd, true);

  /** An upload with its progress (0-100). Besides ``onProgress`` the task panel (hooks.upload) follows it: it can stop it while the file is on its
      way (``xhr.abort``, the promise then fails with ``kind: 'cancelled'``) and show its end wherever the person is. */
  function formProgress(path, fd, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const watcher = watch('upload', {path, fd, abort: () => xhr.abort()});
      const fail = (error) => { tell(watcher, 'fail', error); reject(error); };
      xhr.open('POST', '/api' + path);
      xhr.responseType = 'json';
      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable) return;
        const percent = Math.round(event.loaded / event.total * 100);
        tell(watcher, 'progress', percent);
        onProgress(percent);
      };
      xhr.onerror = () => fail(Object.assign(new Error('Нет связи с локальным сервисом. Запущено ли приложение?'), {kind: 'network'}));
      xhr.onabort = () => { const stopped = Object.assign(new Error('Загрузка остановлена.'), {kind: 'cancelled'}); tell(watcher, 'cancelled'); reject(stopped); };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) { tell(watcher, 'ok', xhr.response); return resolve(xhr.response); }
        const data = xhr.response;
        const detail = data?.detail || data;
        const raw = detail?.error || (typeof detail === 'string' ? detail : `Ошибка сервера (${xhr.status}). Загрузка не завершилась.`);
        fail(Object.assign(new Error(I18N.tr(raw)), {status: xhr.status}, Array.isArray(detail) ? {details: validationDetails(detail)} : {}));
      };
      xhr.send(fd);
    });
  }

  /** The end of an action that takes the person on to ``route`` (an upload that ends in its check): they are taken there while they are still on the
      screen they pressed the button on; once they have left it, the result goes to the task panel with a button to open it, and the screen they are
      on now is not changed under them (ux-save-feedback-p0, REQ-002). Call it when the action starts, with the button that was pressed:
      ``const end = App.landing(button)``; then ``end.stillHere()`` (is a toast about this screen still right?) and
      ``end.go(route, {title, message, openLabel})`` when it is done. Where the task panel is not loaded, the person is always taken on. */
  function landing(control) {
    const ops = typeof Operations !== 'undefined' ? Operations : null;
    const origin = ops ? ops.startedAt(control) : null;
    return {stillHere: () => !origin || !origin.left(),
      go: (route, notice = {}) => (origin ? ops.finish(origin, {route, ...notice}) : (App.go(route, {preserveScroll: true}), true))};
  }

  return {h, fill, btn, field, link, pill, labText, num, duration, timeBlock, agreed, CAUTION, plural, originText, steadiness, STEADY, sourcesBlock, swatch, api, get, post, put, patch, del, form, formProgress, hooks, validationDetails, landing};
})();
