/* The compact list (DEC-090, REQ-001 of findings-you-can-manage-short-lists-re-check): one line per item, its details under the line on a
   click (built only when opened, one line open at a time), a search, filter chips with counts, a sort, «показано N из M» and «Показать ещё»
   by pages. The application has no long lists: anything that can grow beyond a screen is shown with this list.
   The items are an array (``items``) or pages from the server (``load``). The choices (sort, filters, search, how many are shown) survive a
   redraw of the screen: kept in sessionStorage under ``id`` (a convenience of one viewer; without storage they are simply not kept) or
   given by the screen in ``initial`` and handed back in ``onChange`` (the screen's address). */
'use strict';
Object.assign(App, (() => {
  const {h, btn} = App;
  const PAGE = 20;
  const memory = {
    read(id) { try { return id ? JSON.parse(sessionStorage.getItem('list:' + id) || 'null') : null; } catch (_) { return null; } },
    write(id, state) { try { if (id) sessionStorage.setItem('list:' + id, JSON.stringify(state)); } catch (_) { /* a window without storage */ } },
  };

  /** A list. ``opts``:
      id, items | load({sort, filters, search, offset, limit}) -> {items, total, counts: {filter: {value: n}}},
      row(item) -> the nodes of the line (a box, field or link in it works by itself and does not open the line), key(item) -> the
      key of the line, rowClass(item) -> classes of the line (an excluded item dimmed), details(item, list) -> a node (or a promise of
      one) under the line, actions(item, list) -> buttons, search(item) -> the text searched (with ``load``: true
      sends the search field to the server),
      filters: [{key, label, options: [[value, label]] or options(answer) — the values from the last ``load`` answer (the server knows
      which there are), test(item, value), select, all, keepEmpty}] (the value '' is «all»; ``select``: a drop-down instead of chips),
      sorts: [[key, label, compare]], page, empty, initial: {sort, filters, search}, open: the key of a line open at once,
      onChange(state), className.
      Returns {el, refresh(), state(), open(key), ready}; ``open`` opens a line from the screen (a row action that needs the details)
      and resolves to its details once they are drawn. */
  function list(opts) {
    const page = opts.page || PAGE;
    const sorts = opts.sorts || [];
    const filters = opts.filters || [];
    const saved = memory.read(opts.id) || {};
    const initial = opts.initial || {};
    const state = {
      sort: sorts.some(([k]) => k === (initial.sort ?? saved.sort)) ? (initial.sort ?? saved.sort) : (sorts[0] ? sorts[0][0] : ''),
      filters: Object.fromEntries(filters.map((f) => [f.key, String((initial.filters || {})[f.key] ?? (saved.filters || {})[f.key] ?? '')])),
      search: String(initial.search ?? saved.search ?? ''),
      shown: Math.max(page, +saved.shown || 0),
    };
    let openKey = opts.open ?? null;
    let loaded = {items: [], total: 0, counts: {}};
    let busy = null;
    let opening = null;                              // the details of the open line, once drawn
    const keyOf = (item, i) => String(opts.key ? opts.key(item) : i);
    const optionsOf = (f) => (typeof f.options === 'function' ? f.options(loaded) || [] : f.options);

    const el = h('div', {class: 'lst' + (opts.className ? ' ' + opts.className : '')});
    const bar = h('div', {class: 'lst-bar'});
    const rows = h('div', {class: 'lst-rows', role: 'list'});
    const foot = h('div', {class: 'lst-foot'});
    el.append(bar, rows, foot);

    const changed = () => {
      memory.write(opts.id, {sort: state.sort, filters: state.filters, search: state.search, shown: state.shown});
      if (opts.onChange) opts.onChange({sort: state.sort, filters: {...state.filters}, search: state.search});
    };

    // -- client mode: what the search and filters let through; a chip's count is what it would show with the other filters as they are
    const passes = (item, except) => filters.every((f) => f.key === except || !state.filters[f.key] || f.test(item, state.filters[f.key]))
      && (!state.search || !opts.search || String(opts.search(item)).toLowerCase().includes(state.search.toLowerCase()));
    function local() {
      const all = opts.items || [];
      const matched = all.filter((item) => passes(item, null));
      const compare = (sorts.find(([k]) => k === state.sort) || [])[2];
      if (compare) matched.sort(compare);
      const counts = Object.fromEntries(filters.map((f) => [f.key, Object.fromEntries([['', all.filter((item) => passes(item, f.key)).length],
        ...optionsOf(f).map(([v]) => [String(v), all.filter((item) => passes(item, f.key) && f.test(item, String(v))).length])])]));
      return {items: matched.slice(0, state.shown), total: matched.length, counts};
    }
    async function remote(offset, limit) {
      return opts.load({sort: state.sort, filters: {...state.filters}, search: state.search, offset, limit});
    }

    function toolbar() {
      const parts = [];
      if (opts.search) {
        const input = h('input', {type: 'search', class: 'lst-search', placeholder: 'Найти…', value: state.search, 'aria-label': 'Поиск'});
        let timer = null;
        input.addEventListener('input', () => {
          clearTimeout(timer);
          timer = setTimeout(() => { state.search = input.value.trim(); state.shown = page; changed(); refresh(); }, opts.load ? 250 : 0);
        });
        parts.push(input);
      }
      for (const f of filters) {
        const counts = loaded.counts[f.key] || {};
        const label = (text, value) => (counts[value] == null ? text : `${text} · ${counts[value]}`);
        const choose = (value) => { state.filters[f.key] = value; state.shown = page; changed(); refresh(); };
        if (f.select) {
          // a value chosen earlier (remembered, or from the address) that is no longer among the options stays visible, so the list is
          // never narrowed by a choice the drop-down does not show, and «все» clears it
          const known = optionsOf(f);
          const chosen = state.filters[f.key];
          const stale = chosen && !known.some(([v]) => String(v) === chosen) ? [[chosen, 'выбранное ранее — его здесь нет']] : [];
          parts.push(h('label', {class: 'lst-select'}, h('span', {}, f.label),
            h('select', {onChange: (e) => choose(e.target.value)}, h('option', {value: ''}, label(f.all || 'все', '')),
              [...known, ...stale].map(([v, text]) => h('option', {value: v, selected: String(v) === chosen}, label(text, String(v)))))));
        } else {
          parts.push(h('div', {class: 'lst-chips', role: 'group', 'aria-label': f.label},
            [['', f.all || 'Все'], ...optionsOf(f)].filter(([v]) => v === '' || f.keepEmpty || counts[String(v)] == null || counts[String(v)] > 0 || String(v) === state.filters[f.key])
              .map(([v, text]) => h('button', {type: 'button', class: 'lst-chip' + (String(v) === state.filters[f.key] ? ' on' : ''),
                'aria-pressed': String(String(v) === state.filters[f.key]), onClick: () => choose(String(v))}, label(text, String(v))))));
        }
      }
      if (sorts.length > 1) {
        parts.push(h('label', {class: 'lst-select'}, h('span', {}, 'Порядок'),
          h('select', {'aria-label': 'Порядок', onChange: (e) => { state.sort = e.target.value; changed(); refresh(); }},
            sorts.map(([k, text]) => h('option', {value: k, selected: k === state.sort}, text)))));
      }
      parts.push(h('span', {class: 'lst-count muted small'}, `показано ${loaded.items.length} из ${loaded.total}`));
      App.fill(bar, parts);
    }

    function rowOf(item, i) {
      const key = keyOf(item, i);
      const open = key === openKey;
      const details = h('div', {class: 'lst-det', hidden: !open});
      const extra = opts.rowClass ? opts.rowClass(item) : '';
      const line = h('div', {class: 'lst-row' + (open ? ' open' : '') + (extra ? ' ' + extra : ''), role: 'listitem', 'data-key': key},
        h('div', {class: 'lst-main', role: opts.details ? 'button' : null, tabindex: opts.details ? '0' : null, 'aria-expanded': opts.details ? String(open) : null},
          opts.row(item)),
        opts.actions ? h('div', {class: 'lst-act'}, opts.actions(item, api)) : null);
      if (opts.details) {
        const main = line.querySelector('.lst-main');
        const toggle = () => { openKey = openKey === key ? null : key; render(); };
        // a field or a link in the line works by itself; a button opens the line too unless its screen stops it (a swatch that chooses)
        const control = (e) => e.target !== main && e.target.closest && e.target.closest('input, select, textarea, a, label');
        main.addEventListener('click', (e) => { if (!control(e)) toggle(); });
        main.addEventListener('keydown', (e) => { if ((e.key === 'Enter' || e.key === ' ') && !control(e)) { e.preventDefault(); toggle(); } });
        if (open) {
          opening = Promise.resolve(opts.details(item, api)).then((node) => { App.fill(details, node); return details; })
            .catch((e) => { App.fill(details, h('div', {class: 'alert bad'}, e.message || String(e))); return details; });
        }
      }
      return [line, details];
    }

    function render() {
      toolbar();
      App.fill(rows, loaded.items.length ? loaded.items.map(rowOf) : h('p', {class: 'muted lst-empty'}, opts.empty || 'Ничего нет'));
      const rest = loaded.total - loaded.items.length;
      App.fill(foot, rest > 0 ? btn(`Показать ещё ${Math.min(page, rest)}`, () => more(), 'btn-small') : null);
    }

    async function more() {
      if (opts.load) {
        const next = await remote(loaded.items.length, page);
        loaded = {...next, items: [...loaded.items, ...next.items]};
        state.shown = loaded.items.length;
      } else {
        state.shown += page;
        loaded = local();
      }
      changed();
      render();
    }

    /** Read the items again (after an action changed them) keeping what is shown. */
    async function refresh() {
      if (!opts.load) { loaded = local(); render(); return; }
      const ticket = busy = {};
      const next = await remote(0, Math.max(page, state.shown));
      if (ticket !== busy) return;                   // a newer request answers instead
      loaded = next;
      render();
    }

    function open(key) {
      openKey = String(key);
      opening = null;
      render();
      return opening || Promise.resolve(null);       // null: the line is not on the shown page
    }

    const api = {el, refresh, open, state: () => ({sort: state.sort, filters: {...state.filters}, search: state.search, shown: state.shown}),
      set items(next) { opts.items = next; }};
    api.ready = refresh().catch((e) => App.fill(rows, h('div', {class: 'alert bad'}, e.message || String(e))));
    return api;
  }

  return {list};
})());
