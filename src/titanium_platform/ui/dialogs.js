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

  // The dialogs open now, the last is on top: only it answers Escape and Tab, and everything behind the top one is inert.
  const open = [];
  const FOCUSABLE = 'a, button, input, select, textarea, [tabindex]';
  const reachable = (box) => [...box.querySelectorAll(FOCUSABLE)].filter((el) => {
    if (el.disabled || el.getAttribute('tabindex') === '-1' || (el.localName === 'a' && !el.hasAttribute('href'))) return false;
    for (let n = el; n && n !== box; n = n.parentNode) if (n.hidden) return false;
    return true;
  });

  /** A dialog: ``title``, ``body`` and a row of ``actions`` ({label, cls, run(m), initial}). ``onClose`` is called once when the dialog is
      closed, however it is: by an action, ×, Escape or a click outside. Tab and Shift+Tab stay inside it and the page behind it is inert
      (BUG-014); the focus starts on the first field, else on the action marked ``initial``, else on the last action; closing gives the
      focus back to whoever opened it, or to the main area when that element is gone. */
  function modal(title, body, actions, onClose = null) {
    const opener = document.activeElement;
    let closed = false;
    const bg = h('div', {class: 'modal-bg', onClick: (e) => { if (e.target === bg) close(); }});
    const inerted = [];
    const onKey = (e) => {
      if (open[open.length - 1] !== self) return;               // a dialog above this one answers
      if (e.key === 'Escape') { close(); return; }
      if (e.key !== 'Tab') return;
      const items = reachable(box);
      if (!items.length) { e.preventDefault(); return; }
      const now = document.activeElement;
      const inside = !!now && box.contains(now);
      if (e.shiftKey && (!inside || now === items[0])) { e.preventDefault(); items[items.length - 1].focus(); }
      else if (!e.shiftKey && (!inside || now === items[items.length - 1])) { e.preventDefault(); items[0].focus(); }
    };
    const close = () => {
      if (closed) return;
      closed = true;
      bg.remove(); document.removeEventListener('keydown', onKey);
      open.splice(open.indexOf(self), 1);
      for (const part of inerted) part.removeAttribute('inert');
      const back = opener && opener.focus && opener.isConnected !== false ? opener : (document.getElementById ? document.getElementById('main') : null);
      if (back && back.focus) back.focus();
      if (onClose) onClose();
    };
    const self = {close};
    const buttons = (actions || []).map((a) => btn(a.label, async (ev) => {
      const b = ev.currentTarget;
      b.disabled = true;
      try { await a.run({close}); } catch (e) { fail(e); } finally { b.disabled = false; }
    }, a.cls || ''));
    const box = h('div', {class: 'modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': title},
      h('div', {class: 'row'}, h('h3', {}, title), h('span', {class: 'spacer'}), h('button', {type: 'button', class: 'btn', 'aria-label': 'Закрыть', onClick: close}, '×')),
      body, h('div', {class: 'row', style: 'margin-top:14px'}, buttons));
    // the page behind the dialog (and a dialog under this one) can be reached neither by the keyboard nor by the pointer
    for (const part of [...document.body.children]) {
      if (part !== bg && !part.hasAttribute('inert') && !(part.classList && part.classList.contains('toasts'))) { part.setAttribute('inert', ''); inerted.push(part); }
    }
    bg.append(box);
    document.body.append(bg);
    open.push(self);
    document.addEventListener('keydown', onKey);
    const marked = (actions || []).findIndex((a) => a.initial);
    (box.querySelector('input,select,textarea') || buttons[marked >= 0 ? marked : buttons.length - 1] || box.querySelector('button')).focus();
    return {close, el: box};
  }

  /** A confirmation. Its focus starts on «Отмена», so a quick Enter never confirms a deletion. */
  function confirmBox(title, text, okLabel, run) {
    return modal(title, h('p', {}, text), [{label: 'Отмена', initial: true, run: (m) => m.close()},
      {label: okLabel, cls: 'primary', run: async (m) => { await run(); m.close(); }}]);
  }

  /** Вкладки: ``items`` — [id, подпись, узел]; возвращает ``list`` (полоса вкладок), ``panels`` (по одной панели на вкладку) и ``select``.
      Открыта вкладка, запомненная браузером под ``remember`` (удобство одного зрителя: без хранилища просто не запоминается), иначе
      ``initial``; стрелки влево и вправо переключают вкладки; ``onSelect(id)`` is called on every switch, the first one included. */
  function tabs(items, {initial, remember, label, prefix = 'tab', onSelect}) {
    const ids = items.map(([id]) => id);
    const saved = () => { try { return remember ? localStorage.getItem(remember) : null; } catch (_) { return null; } };
    let current = ids.includes(saved()) ? saved() : initial;
    const buttons = items.map(([id, name]) => h('button', {type: 'button', role: 'tab', class: 'vw-tab', id: `${prefix}-${id}`, 'aria-controls': `${prefix}-panel-${id}`,
      onClick: () => select(id)}, name));
    const panels = items.map(([id, , node]) => h('div', {role: 'tabpanel', class: 'vw-tabpanel', id: `${prefix}-panel-${id}`, 'aria-labelledby': `${prefix}-${id}`}, node));
    function select(id) {
      current = id;
      items.forEach(([key], i) => {
        const on = key === id;
        buttons[i].setAttribute('aria-selected', String(on));
        buttons[i].setAttribute('tabindex', on ? '0' : '-1');
        if (on) buttons[i].classList.add('active'); else buttons[i].classList.remove('active');
        panels[i].hidden = !on;
      });
      try { if (remember) localStorage.setItem(remember, id); } catch (_) { /* окно без хранилища */ }
      if (onSelect) onSelect(id);
    }
    const list = h('div', {role: 'tablist', class: 'vw-tabs', 'aria-label': label}, buttons);
    list.addEventListener('keydown', (ev) => {
      const step = ev.key === 'ArrowRight' ? 1 : ev.key === 'ArrowLeft' ? -1 : 0;
      if (!step) return;
      const shown = ids.filter((_, i) => !buttons[i].hidden);         // a tab a screen hides is skipped
      const next = shown[(shown.indexOf(current) + step + shown.length) % shown.length];
      select(next);
      buttons[ids.indexOf(next)].focus();
      ev.preventDefault();
    });
    select(current);
    return {list, panels, select};
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

  return {toast, fail, modal, confirmBox, facts, table, tabs};
})());
