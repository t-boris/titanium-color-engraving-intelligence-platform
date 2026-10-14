/* Уведомления и окна. Окно закрывается по Escape и щелчку вне него; фокус возвращается к вызвавшему элементу;
   пока действие выполняется, его кнопка заблокирована. Уведомление закрывается само через шесть секунд,
   наведение приостанавливает таймер. */
'use strict';
Object.assign(App, (() => {
  const {h, btn} = App;

  function toast(text, kind = '') {
    let box = document.querySelector('.toasts');
    if (!box) { box = h('div', {class: 'toasts', role: 'status', 'aria-live': 'polite'}); document.body.append(box); }
    const t = h('div', {class: 'toast ' + kind}, text, ' ', h('button', {type: 'button', class: 'btn', 'aria-label': 'Закрыть', onClick: () => t.remove()}, '×'));
    box.append(t);
    let timer = setTimeout(() => t.remove(), 6000);
    t.addEventListener('mouseenter', () => clearTimeout(timer));
    t.addEventListener('mouseleave', () => { timer = setTimeout(() => t.remove(), 6000); });
  }
  const fail = (e) => toast(e.message || String(e), 'bad');

  function modal(title, body, actions) {
    const opener = document.activeElement;
    const bg = h('div', {class: 'modal-bg', onClick: (e) => { if (e.target === bg) close(); }});
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    const close = () => { bg.remove(); document.removeEventListener('keydown', onKey); if (opener && opener.focus) opener.focus(); };
    const buttons = (actions || []).map((a) => btn(a.label, async (ev) => {
      const b = ev.currentTarget;
      b.disabled = true;
      try { await a.run({close}); } catch (e) { fail(e); } finally { b.disabled = false; }
    }, a.cls || ''));
    const box = h('div', {class: 'modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': title},
      h('div', {class: 'row'}, h('h3', {}, title), h('span', {class: 'spacer'}), h('button', {type: 'button', class: 'btn', 'aria-label': 'Закрыть', onClick: close}, '×')),
      body, h('div', {class: 'row', style: 'margin-top:14px'}, buttons));
    bg.append(box);
    document.body.append(bg);
    document.addEventListener('keydown', onKey);
    (box.querySelector('input,select,textarea') || buttons[buttons.length - 1] || box.querySelector('button')).focus();
    return {close, el: box};
  }

  function confirmBox(title, text, okLabel, run) {
    return modal(title, h('p', {}, text), [{label: 'Отмена', run: (m) => m.close()},
      {label: okLabel, cls: 'primary', run: async (m) => { await run(); m.close(); }}]);
  }

  /** Список «подпись: значение» для небольших сводок. */
  function facts(rows) {
    return h('dl', {class: 'facts'}, rows.filter((r) => r && r[1] != null && r[1] !== '').map(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]));
  }

  /** Таблица из заголовков и строк (ячейка — строка, число или узел). */
  function table(head, rows, empty, compact) {
    if (!rows.length) return h('p', {class: 'muted'}, empty || 'Нет данных');
    return h('div', {class: 'tw' + (compact ? ' compact' : '')}, h('table', {}, h('thead', {}, h('tr', {}, head.map((t) => h('th', {}, t)))),
      h('tbody', {}, rows.map((r) => h('tr', {}, r.map((c) => h('td', {}, c)))))));
  }

  return {toast, fail, modal, confirmBox, facts, table};
})());
