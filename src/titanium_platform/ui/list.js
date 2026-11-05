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
      sorts: [[key, label, compare]], page, empty (the collection has nothing), noResults (the search or filters let nothing through), initial: {sort, filters, search}, open: the key of a line open at once,
      onChange(state), className,
      selected: the key of the object the screen works with now (a recipe, a scale, a document), or a function that returns it, and
      selectedItem: that object when it may be outside the shown page ((key) -> item | promise of it; with ``items`` it is found there):
      the list keeps it in view as a pinned line above the rows, says when the search or a filter excludes it and offers the reset.
      Returns {el, refresh(), state(), open(key), reset(), ready}; ``open`` opens a line from the screen (a row action that needs the
      details) and resolves to its details once they are drawn; when the line cannot be shown it says why beside the list (hidden by the
      search or filters, with the reset, or unavailable) and resolves to null. */
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
    let busy = null;                                 // the ticket of the newest read: an older answer is dropped (a search, a filter, a refresh)
    let moreBusy = false;                            // one next page at a time: a second click while one is on its way does nothing
    let opening = null;                              // the details of the open line, once drawn
    let failure = null;                              // {text, retry}: the last read that failed, shown beside the list with a retry
    let pinKey = null;                               // a line a screen asked to open that is not among the shown rows
    let pinned = null;                               // {key, item, why}: the object the screen works with, kept in view outside the rows
    const keyOf = (item, i) => String(opts.key ? opts.key(item) : i);
    const optionsOf = (f) => (typeof f.options === 'function' ? f.options(loaded) || [] : f.options);
    const selectedKey = () => {
      const chosen = typeof opts.selected === 'function' ? opts.selected() : opts.selected;
      return chosen == null || chosen === '' ? null : String(chosen);
    };
    const conditions = () => Boolean(state.search) || filters.some((f) => state.filters[f.key]);

    const el = h('div', {class: 'lst' + (opts.className ? ' ' + opts.className : '')});
    const bar = h('div', {class: 'lst-bar'});
    const side = h('div', {class: 'lst-side'});
    const pin = h('div', {class: 'lst-pin-box'});
    const rows = h('div', {class: 'lst-rows', role: 'list'});
    const foot = h('div', {class: 'lst-foot'});
    el.append(bar, side, pin, rows, foot);

    const changed = () => {
      memory.write(opts.id, {sort: state.sort, filters: state.filters, search: state.search, shown: state.shown});
      if (opts.onChange) opts.onChange({sort: state.sort, filters: {...state.filters}, search: state.search});
    };

    // A redraw must not take the cursor from the control the person is using (BUG-012): the field and the selects live as long as the list,
    // and what is rebuilt (chips, rows, options) gives the focus back to the same control.
    const activeIn = (box) => {
      const now = typeof document !== 'undefined' ? document.activeElement : null;
      return now && box.contains && box.contains(now) ? now : null;
    };
    function keepFocus(box, mark, find, rebuild) {
      const was = activeIn(box);
      const where = was ? mark(was) : null;
      rebuild();
      if (where == null) return;
      const again = find(where);
      if (again && again.focus) again.focus({preventScroll: true});
    }

    // -- client mode: what the search and filters let through; a chip's count is what it would show with the other filters as they are
    const passes = (item, except) => filters.every((f) => f.key === except || !state.filters[f.key] || f.test(item, state.filters[f.key]))
      && (!state.search || !opts.search || String(opts.search(item)).toLowerCase().includes(state.search.toLowerCase()));
    function matchedAll() {
      const matched = (opts.items || []).filter((item) => passes(item, null));
      const compare = (sorts.find(([k]) => k === state.sort) || [])[2];
      if (compare) matched.sort(compare);
      return matched;
    }
    function local() {
      const all = opts.items || [];
      const matched = matchedAll();
      const counts = Object.fromEntries(filters.map((f) => [f.key, Object.fromEntries([['', all.filter((item) => passes(item, f.key)).length],
        ...optionsOf(f).map(([v]) => [String(v), all.filter((item) => passes(item, f.key) && f.test(item, String(v))).length])])]));
      return {items: matched.slice(0, state.shown), total: matched.length, counts};
    }
    async function remote(offset, limit) {
      return opts.load({sort: state.sort, filters: {...state.filters}, search: state.search, offset, limit});
    }

    // -- the toolbar: built once, then updated in place
    const ui = {built: false, search: null, chips: new Map(), selects: new Map(), sort: null, count: null, reset: null};
    function buildBar() {
      ui.built = true;
      const parts = [];
      if (opts.search) {
        ui.search = h('input', {type: 'search', class: 'lst-search', placeholder: 'Найти…', value: state.search, 'aria-label': 'Поиск'});
        let timer = null;
        ui.search.addEventListener('input', () => {
          clearTimeout(timer);
          timer = setTimeout(() => { state.search = ui.search.value.trim(); state.shown = page; changed(); refresh(); }, opts.load ? 250 : 0);
        });
        parts.push(ui.search);
      }
      for (const f of filters) {
        if (f.select) {
          const select = h('select', {onChange: (e) => choose(f, e.target.value)});
          ui.selects.set(f.key, select);
          parts.push(h('label', {class: 'lst-select'}, h('span', {}, f.label), select));
        } else {
          const box = h('div', {class: 'lst-chips', role: 'group', 'aria-label': f.label});
          ui.chips.set(f.key, box);
          parts.push(box);
        }
      }
      if (sorts.length > 1) {
        ui.sort = h('select', {'aria-label': 'Порядок', onChange: (e) => { state.sort = e.target.value; changed(); refresh(); }},
          sorts.map(([k, text]) => h('option', {value: k, selected: k === state.sort}, text)));
        parts.push(h('label', {class: 'lst-select'}, h('span', {}, 'Порядок'), ui.sort));
      }
      ui.count = h('span', {class: 'lst-count muted small', role: 'status', 'aria-live': 'polite'});
      ui.reset = h('button', {type: 'button', class: 'btn btn-small lst-reset', hidden: true, onClick: () => reset()}, 'Сбросить поиск и фильтры');
      parts.push(ui.count, ui.reset);
      App.fill(bar, parts);
    }
    function choose(f, value) { state.filters[f.key] = value; state.shown = page; changed(); refresh(); }

    function toolbar() {
      if (!ui.built) buildBar();
      for (const f of filters) {
        const counts = loaded.counts[f.key] || {};
        const label = (text, value) => (counts[value] == null ? text : `${text} · ${counts[value]}`);
        if (f.select) {
          // a value chosen earlier (remembered, or from the address) that is no longer among the options stays visible, so the list is
          // never narrowed by a choice the drop-down does not show, and «все» clears it
          const select = ui.selects.get(f.key);
          const known = optionsOf(f);
          const chosen = state.filters[f.key];
          const stale = chosen && !known.some(([v]) => String(v) === chosen) ? [[chosen, 'выбранное ранее — его здесь нет']] : [];
          select.replaceChildren(h('option', {value: '', selected: chosen === ''}, label(f.all || 'все', '')),
            ...[...known, ...stale].map(([v, text]) => h('option', {value: v, selected: String(v) === chosen}, label(text, String(v)))));
        } else {
          const box = ui.chips.get(f.key);
          keepFocus(box, (node) => node.getAttribute('data-value'), (value) => [...box.querySelectorAll('.lst-chip')].find((c) => c.getAttribute('data-value') === value),
            () => App.fill(box, [['', f.all || 'Все'], ...optionsOf(f)]
              .filter(([v]) => v === '' || f.keepEmpty || counts[String(v)] == null || counts[String(v)] > 0 || String(v) === state.filters[f.key])
              .map(([v, text]) => h('button', {type: 'button', class: 'lst-chip' + (String(v) === state.filters[f.key] ? ' on' : ''), 'data-value': String(v),
                'aria-pressed': String(String(v) === state.filters[f.key]), onClick: () => choose(f, String(v))}, label(text, String(v))))));
        }
      }
      if (ui.sort) ui.sort.value = state.sort;
      ui.count.textContent = `показано ${loaded.items.length} из ${loaded.total}`;
      ui.reset.hidden = !conditions();
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

    // -- the object the screen works with stays findable: pinned above the rows when it is outside them, with the reason
    const FOCUSABLE = 'button, input, select, textarea, a, [tabindex]';
    const inLoaded = (key) => loaded.items.some((item, i) => keyOf(item, i) === key);
    let fetched = new Map();                          // key -> the item a screen's ``selectedItem`` returned (asked once)
    /** Decide which object is pinned. Synchronous unless the screen has to fetch the object (``selectedItem``): then a promise. */
    function settle() {
      pinned = null;
      const key = selectedKey() ?? pinKey;
      if (key == null || inLoaded(key)) return null;
      const decide = (found) => {
        let item = found;
        if (!item && opts.selectedItem) item = fetched.get(key) || null;
        let why = 'unavailable';
        if (item) why = !opts.load && !passes(item, null) ? 'excluded' : (opts.load && conditions() ? 'maybe-excluded' : 'beyond');
        pinned = {key, item, why};
      };
      const known = opts.load ? null : (opts.items || []).find((x, i) => keyOf(x, i) === key) || null;
      if (!known && opts.selectedItem && !fetched.has(key)) {
        return Promise.resolve().then(() => opts.selectedItem(key)).then((got) => fetched.set(key, got), () => fetched.set(key, null))
          .then(() => decide(null));
      }
      decide(known);
      return null;
    }
    function pinnedBox() {
      if (!pinned) return null;
      const {item, why} = pinned;
      const text = {
        excluded: 'Выбранная строка скрыта: она не подходит под поиск или фильтры.',
        'maybe-excluded': 'Выбранная строка вне показанных: возможно, её скрывают поиск или фильтры.',
        beyond: 'Выбранная строка вне показанной части списка.',
        unavailable: 'Выбранный объект недоступен: его нет в этом списке или он не загрузился.',
      }[why];
      const acts = [];
      if ((why === 'excluded' || why === 'maybe-excluded') && conditions()) acts.push(btn('Сбросить поиск и фильтры', () => reset(), 'btn-small'));
      if (why === 'beyond' && !opts.load) acts.push(btn('Показать в списке', () => reveal(pinned.key), 'btn-small'));
      if (opts.clearSelection) acts.push(btn('Снять выбор', async () => { await opts.clearSelection(); pinKey = null; await refresh(); }, 'btn-small'));
      return h('div', {class: 'lst-pin', role: 'group', 'aria-label': 'Выбранное'}, h('p', {class: 'small muted lst-pin-note'}, text, ' ', acts),
        item ? rowOf(item, 0) : null);
    }
    /** Client mode: shows enough rows for the line ``key`` to be among them. */
    function reveal(key) {
      const at = matchedAll().findIndex((item, i) => keyOf(item, i) === key);
      if (at < 0) return false;
      if (at >= state.shown) state.shown = Math.ceil((at + 1) / page) * page;
      loaded = local();
      changed();
      const wait = settle();
      render();
      if (wait) wait.then(render);
      return true;
    }

    function render() {
      const where = typeof window !== 'undefined' ? window.scrollY : 0;
      toolbar();
      App.fill(side, failure ? h('div', {class: 'alert bad lst-fail', role: 'alert'}, h('span', {}, `Не удалось загрузить список: ${failure.text} `),
        h('button', {type: 'button', class: 'btn btn-small lst-retry', onClick: () => retry()}, 'Повторить')) : null);
      App.fill(pin, pinnedBox());
      keepFocus(rows, (node) => {
        const line = node.closest('.lst-row');
        if (!line) return null;
        const at = [...line.querySelectorAll(FOCUSABLE)].indexOf(node);
        return {key: line.getAttribute('data-key'), at};
      }, (mark) => {
        const line = [...rows.querySelectorAll('.lst-row')].find((r) => r.getAttribute('data-key') === mark.key);
        return line ? (mark.at < 0 ? line.querySelector('.lst-main') : line.querySelectorAll(FOCUSABLE)[mark.at]) : null;
      }, () => {
        if (loaded.items.length) App.fill(rows, loaded.items.map(rowOf));
        else if (failure) App.fill(rows, null);
        else if (conditions()) App.fill(rows, h('div', {class: 'lst-none'}, h('p', {class: 'muted lst-empty'}, opts.noResults || 'Ничего не найдено по заданным условиям.'),
          h('p', {class: 'small muted'}, noneText()), btn('Сбросить поиск и фильтры', () => reset(), 'btn-small')));
        else App.fill(rows, h('p', {class: 'muted lst-empty'}, opts.empty || 'Ничего нет'));
      });
      const rest = loaded.total - loaded.items.length;
      App.fill(foot, rest > 0 ? h('button', {type: 'button', class: 'btn btn-small', disabled: moreBusy, onClick: () => more()},
        moreBusy ? 'Загружаем…' : `Показать ещё ${Math.min(page, rest)}`) : null);
      if (typeof window !== 'undefined' && window.scrollY !== where && window.scrollTo) window.scrollTo(0, where);
    }
    function noneText() {
      const parts = [];
      if (state.search) parts.push(`поиск «${state.search}»`);
      for (const f of filters) {
        const value = state.filters[f.key];
        if (!value) continue;
        const named = optionsOf(f).find(([v]) => String(v) === value);
        parts.push(`${f.label}: ${named ? named[1] : value}`);
      }
      return 'Условия: ' + parts.join('; ') + '.';
    }

    async function more() {
      if (moreBusy) return;
      if (!opts.load) {
        state.shown += page;
        loaded = local();
        changed();
        const wait = settle();
        render();
        if (wait) await wait.then(render);
        return;
      }
      const ticket = busy;
      moreBusy = true;
      failure = null;
      render();
      try {
        const next = await remote(loaded.items.length, page);
        if (ticket !== busy) return;                 // a newer search, filter or refresh answers instead
        const have = new Set(loaded.items.map(keyOf));
        const fresh = opts.key ? next.items.filter((item) => !have.has(keyOf(item))) : next.items;
        loaded = {...next, items: [...loaded.items, ...fresh]};
        state.shown = loaded.items.length;
        changed();
        const wait = settle();
        if (wait) await wait;
      } catch (e) {
        if (ticket === busy) failure = {text: e.message || String(e), retry: more};
      } finally {
        moreBusy = false;
        render();
      }
    }

    /** Read the items again (after an action changed them) keeping what is shown. */
    async function refresh() {
      if (!opts.load) {
        loaded = local();
        fetched = new Map();
        const wait = settle();
        render();                                    // a list of items in hand draws at once
        if (wait) await wait.then(render);
        return;
      }
      const ticket = busy = {};
      fetched = new Map();                           // the data may have changed (a save): a pinned object is asked for again
      try {
        const next = await remote(0, Math.max(page, state.shown));
        if (ticket !== busy) return;                 // a newer request answers instead
        loaded = next;
        failure = null;
        const wait = settle();
        if (wait) await wait;
      } catch (e) {
        if (ticket !== busy) return;
        failure = {text: e.message || String(e), retry: refresh};
      }
      if (ticket === busy) render();
    }
    /** Try the failed read again; the rows already shown, the typed search and the focus stay. */
    async function retry() {
      const again = failure && failure.retry;
      if (!again) return;
      failure = null;
      render();
      await again();
      const target = failure ? el.querySelector('.lst-retry') : (ui.search || el.querySelector('.lst-main'));
      if (target && target.focus) target.focus();
    }

    /** Clear the search and every filter: the first page again, the sort and the current selection stay as they are. */
    function reset() {
      state.search = '';
      for (const f of filters) state.filters[f.key] = '';
      state.shown = page;
      if (ui.search) ui.search.value = '';
      changed();
      return refresh();
    }

    function drawOpened() {
      const wait = settle();
      render();
      return wait ? wait.then(() => { render(); return opening; }) : Promise.resolve(opening);
    }
    function open(key) {
      const wanted = String(key);
      openKey = wanted;
      opening = null;
      pinKey = null;
      if (!opts.load) {
        const at = matchedAll().findIndex((item, i) => keyOf(item, i) === wanted);
        if (at >= state.shown) { state.shown = Math.ceil((at + 1) / page) * page; loaded = local(); }
        if (at < 0) pinKey = wanted;                 // hidden by the search or a filter, or not in the list at all: said beside the list
        return drawOpened();
      }
      if (inLoaded(wanted)) { render(); return Promise.resolve(opening); }
      pinKey = wanted;                               // not on the shown page: kept in view if the screen can fetch it, else said
      return drawOpened();
    }

    const api = {el, refresh, open, reset, state: () => ({sort: state.sort, filters: {...state.filters}, search: state.search, shown: state.shown}),
      set items(next) { opts.items = next; }};
    api.ready = refresh();
    return api;
  }

  return {list};
})());
