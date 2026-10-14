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
  const btn = (label, onClick, cls = '', disabled = false) => h('button', {type: 'button', class: 'btn ' + cls, onClick, disabled}, label);
  const field = (label, input, help) => h('label', {class: 'f'}, h('span', {}, label), input, help ? h('span', {class: 'small muted'}, help) : null);
  const link = (route, label) => h('a', {href: '#' + route}, label);
  const pill = (text, kind = '') => h('span', {class: 'pill ' + kind}, text);
  const labText = (lab) => (lab ? `L ${(+lab[0]).toFixed(1)} · a ${(+lab[1]).toFixed(1)} · b ${(+lab[2]).toFixed(1)}` : '—');
  const num = (v, d = 2) => (v == null ? '—' : (+v).toFixed(d));

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
      const raw = d && d.error ? d.error : (Array.isArray(d) ? 'Проверьте заполнение полей формы' : JSON.stringify(d));
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

  return {h, btn, field, link, pill, labText, num, swatch, api, get, post, put, patch, del, form};
})();
