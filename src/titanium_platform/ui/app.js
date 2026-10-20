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
  const field = (label, input, help) => h('label', {class: 'f'}, h('span', {}, label), input, help ? h('span', {class: 'small muted'}, help) : null);
  const link = (route, label) => h('a', {href: '#' + route}, label);
  const pill = (text, kind = '') => h('span', {class: 'pill ' + kind}, text);
  const labText = (lab) => (lab ? `L ${(+lab[0]).toFixed(1)} · a ${(+lab[1]).toFixed(1)} · b ${(+lab[2]).toFixed(1)}` : '—');
  const num = (v, d = 2) => (v == null ? '—' : (+v).toFixed(d));
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
    const row = (s) => h('li', {class: 'cm-source'}, swatch(s.lab), ' ', h('strong', {}, s.title), ' ', pill(ORIGIN[kindOf(s)][0]), ' · ',
      link('/experiment/' + encodeURIComponent(s.experiment), 'эксперимент'), ...(s.work_id ? [' · ', link('/vector?plan=' + s.work_id, 'векторная работа')] : []),
      ...(s.provisional ? [' · ', pill('предварительно', 'warn')] : s.pair_ids.flatMap((id) => [' · ', link(`/analysis/${id}`, `разбор №${id}`)])),
      h('div', {class: 'muted'}, [day(s.date), s.photos.length ? `фото ${s.photos.join(', ')}` : null, s.layers.length ? s.layers.join(', ') : null].filter(Boolean).join(' · '),
        ' · ', pill(...MEASURED[s.measurement]), ' ', n > 1 ? (s.agrees ? pill('совпадает', 'ok') : pill('расходится', 'warn')) : null,
        n > 1 ? ` · ΔE ${num(s.delta_e, 1)} от цвета настроек` : ''));
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

  async function api(method, path, body, isForm) {
    const opts = {method, headers: {}};
    if (body !== undefined) {
      if (isForm) opts.body = body;
      else { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    }
    let res;
    try { res = await fetch('/api' + path, opts); }
    catch (_) { throw Object.assign(new Error('Нет связи с локальным сервисом. Запущено ли приложение?'), {kind: 'network'}); }
    if (res.status === 204) return null;
    const json = (res.headers.get('content-type') || '').includes('json');
    const data = json ? await res.json() : await res.blob();
    if (!res.ok) {
      const d = data && data.detail ? data.detail : data;
      const raw = d && d.error ? d.error : (Array.isArray(d) ? 'Проверьте заполнение полей формы'
        : typeof d === 'string' ? d : `Ошибка сервера (${res.status}). Проверка не завершилась.`);
      throw Object.assign(new Error(I18N.tr(raw)), {kind: d && d.kind, status: res.status});
    }
    return data;
  }
  const get = (p) => api('GET', p);
  const post = (p, b) => api('POST', p, b === undefined ? {} : b);
  const put = (p, b) => api('PUT', p, b);
  const patch = (p, b) => api('PATCH', p, b);
  const del = (p) => api('DELETE', p);
  const form = (p, fd) => api('POST', p, fd, true);

  function formProgress(path, fd, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api' + path);
      xhr.responseType = 'json';
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100));
      };
      xhr.onerror = () => reject(new Error('Нет связи с локальным сервисом. Запущено ли приложение?'));
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) return resolve(xhr.response);
        const data = xhr.response;
        const detail = data?.detail || data;
        const raw = detail?.error || (typeof detail === 'string' ? detail : `Ошибка сервера (${xhr.status}). Загрузка не завершилась.`);
        reject(new Error(I18N.tr(raw)));
      };
      xhr.send(fd);
    });
  }

  return {h, fill, btn, field, link, pill, labText, num, agreed, CAUTION, plural, originText, steadiness, STEADY, sourcesBlock, swatch, api, get, post, put, patch, del, form, formProgress};
})();
