/* Paged catalog of vector, photo and business-card work. Existing work routes and operations remain its source of truth (REQ-001, REQ-002). */
'use strict';
const Works = (() => {
  const {h, btn, pill, num, field, get, post, del, toast, fail, modal, confirmBox} = App;
  const VIEW_KEY = 'works.view';
  const FILTERS = ['type', 'laser', 'lens', 'material'];
  const DEFAULT_SORT = 'modified';
  const TYPE = {vector: 'Vector', mixed: 'Mixed', photo: 'Photo engraving', card: 'Business card'};
  const TYPE_CHIPS = [['vector', 'Vector'], ['mixed', 'Mixed'], ['photo', 'Photo engraving'], ['card', 'Cards']];
  // the same words as the chain of an engraving: prepared -> file received -> result added -> checked
  const STATE = {prepared: ['Prepared', ''], exported: ['File exported', ''], result: ['Result added', 'warn'], checked: ['Checked', 'ok']};
  const SORTS = [['modified', 'Recently modified'], ['oldest', 'Oldest modified'], ['name', 'Name']];
  const NONE_LABEL = {laser: 'laser not specified', lens: 'lens unknown', material: 'stock not specified'};
  const NOUN = {laser: 'laser', lens: 'lens', material: 'stock'};
  const KINDS = {vector: ['Vector work', 'color regions, fill, lettering and lines'], photo: ['Photo engraving', 'grayscale image'],
    card: ['Business card', 'two sides, text, shapes, icons and QR codes']};
  const when = (iso) => (iso ? String(iso).replace('T', ' ').slice(0, 16) : '—');

  const stored = {
    read() { try { return localStorage.getItem(VIEW_KEY); } catch (_) { return null; } },
    write(view) { try { localStorage.setItem(VIEW_KEY, view); } catch (_) { /* a window without storage: the view is simply not remembered */ } },
  };
  const later = (fn) => (typeof requestAnimationFrame === 'function' ? requestAnimationFrame(fn) : setTimeout(fn, 0));

  // ---- creating a work: one entry, so that the creation flows can be pointed elsewhere without touching the catalog ----------------

  /** Start a new work of ``kind`` (``vector``, ``photo`` or ``card``). The catalog creates nothing itself: it hands over to the creation screen (Creation.start,
      feature ux-work-creation-p0), the one entry for every work. A photograph starts with «Photo engraving» chosen as the result; a vector work
      leaves the choice (colour areas, silhouette, lines) to the person, who sees their own picture in each. A business card has no picture to start
      from: its own dialog (card-work.js) asks for the name and the size and opens the editor. */
  function startCreation(kind) {
    if (kind === 'card') { CardWork.newDialog(); return; }
    Creation.start({result: kind === 'photo' ? 'photo' : null});
  }

  // ---- the menu of a row ----------------------------------------------------------------------------------------------------------

  let openMenu = null;                                         // the menu that is open now: only one is
  /** A button that opens a menu of ``items`` ({label, run, danger, disabled}): Down, Up, Home and End move in it, Escape closes it and gives
      the focus back to the button, a click outside closes it. ``run`` is called after the menu is closed and the focus is on the button. */
  function menu({label, text, items, cls = '', caret = false}) {
    let shown = false;
    const button = h('button', {type: 'button', class: 'btn works-menu-btn ' + cls, 'aria-haspopup': 'menu', 'aria-expanded': 'false', 'aria-label': label}, text, caret ? ' ▾' : null);
    const buttons = items.map((item) => h('button', {type: 'button', role: 'menuitem', tabindex: '-1', disabled: !!item.disabled,
      class: 'works-menu-item' + (item.danger ? ' danger' : ''), onClick: () => { close(true); item.run(); }}, item.label));
    const popup = h('div', {class: 'works-menu', role: 'menu', 'aria-label': label, hidden: true}, buttons);
    const wrap = h('div', {class: 'works-menu-wrap'}, button, popup);
    const reachable = () => buttons.filter((b) => !b.disabled);
    const outside = (ev) => { if (!wrap.contains(ev.target)) close(false); };
    function close(focusButton) {
      if (!shown) return;
      shown = false;
      popup.hidden = true;
      button.setAttribute('aria-expanded', 'false');
      document.removeEventListener('click', outside);
      if (openMenu === handle) openMenu = null;
      if (focusButton && button.focus) button.focus();
    }
    function show() {
      if (openMenu && openMenu !== handle) openMenu.close(false);
      shown = true;
      popup.hidden = false;
      button.setAttribute('aria-expanded', 'true');
      document.addEventListener('click', outside);
      openMenu = handle;
      const first = reachable()[0];
      if (first && first.focus) first.focus();
    }
    const handle = {close, button};
    button.addEventListener('click', () => (shown ? close(true) : show()));
    button.addEventListener('keydown', (ev) => { if (ev.key === 'ArrowDown' && !shown) { ev.preventDefault(); show(); } });
    popup.addEventListener('keydown', (ev) => {
      const enabled = reachable();
      const index = enabled.indexOf(document.activeElement);
      const move = {ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: enabled.length - 1}[ev.key];
      if (ev.key === 'Escape') { ev.preventDefault(); close(true); return; }
      if (ev.key === 'Tab') { close(true); return; }
      if (move == null) return;
      ev.preventDefault();
      const target = enabled[(move + enabled.length) % enabled.length];
      if (target && target.focus) target.focus();
    });
    return {el: wrap, button, close};
  }

  // ---- one screen -----------------------------------------------------------------------------------------------------------------

  /** The catalog for the address ``query`` (``view``, ``q``, ``type``, ``laser``, ``lens``, ``material``, ``sort``, ``at``). */
  function build(query) {
    const addressed = ['view', 'q', ...FILTERS, 'sort', 'at'].some((k) => k in query);       // an address that says nothing leaves the remembered choices
    let view = query.view === 'gallery' || query.view === 'list' ? query.view : (stored.read() === 'gallery' ? 'gallery' : 'list');
    let at = query.at || null;                         // the work the person opened last, kept in the address until the query changes
    let reach = at;                                    // the work the first answer must reach (the person came back to it); asked for by the list's first read
    let depth = {key: null, count: 0};                 // how many works the current query showed, so that a refresh does not shrink it
    let busy = new Set();                              // keys of the works an operation is running on
    let list = null;

    const fill = (box, ...kids) => App.fill(box, kids);
    const el = h('div', {class: 'stack works'});
    const notice = h('div', {class: 'works-notice', role: 'status'});
    const viewButtons = {};

    // -- the address: the state of the catalog, kept without a new entry of the history
    function address() {
      const s = list ? list.state() : {sort: DEFAULT_SORT, filters: {}, search: ''};
      const p = new URLSearchParams();
      if (view !== 'list') p.set('view', view);
      if (s.search) p.set('q', s.search);
      for (const key of FILTERS) if (s.filters[key]) p.set(key, s.filters[key]);
      if (s.sort !== DEFAULT_SORT) p.set('sort', s.sort);
      if (at) p.set('at', at);
      const text = p.toString();
      return '/works' + (text ? '?' + text : '');
    }
    // a screen that was left (the person went on to another address while it was loading) never rewrites the address of the one that came after it
    const here = () => String(location.hash || '').startsWith('#/works');
    function sync() {
      try { if (here() && history.replaceState) history.replaceState(null, '', '#' + address()); } catch (_) { /* an address that cannot be rewritten stays as it is */ }
    }
    const remember = (key) => { at = key; sync(); };
    function changed() { at = null; fill(notice); sync(); }                  // another search, filter or order: the old place means nothing

    // -- what the server answers
    async function load(s) {
      const q = new URLSearchParams();
      if (s.search) q.set('q', s.search);
      for (const key of FILTERS) if (s.filters[key]) q.set(key, s.filters[key]);
      q.set('sort', s.sort);
      const same = JSON.stringify([s.search, s.filters, s.sort]);
      if (depth.key !== same) depth = {key: same, count: 0};
      const mine = depth;                                                  // an answer to an older query never changes the depth of a newer one
      q.set('offset', String(s.offset));
      q.set('limit', String(s.offset === 0 ? Math.max(s.limit, mine.count) : s.limit));
      if (reach && s.offset === 0) q.set('through', reach);
      const answer = await get('/works?' + q.toString());
      mine.count = s.offset + answer.items.length;
      if (s.offset === 0) reach = null;                                     // the place the person came back to is asked for until one answer has come
      return answer;
    }
    const options = (name) => (answer) => ((answer.facets || {})[name] || []).map(({value, name: label}) => [value,
      value === 'none' ? NONE_LABEL[name] : (label || `${NOUN[name]} #${value}`)]);

    // -- a row
    function thumb(w) {
      const img = h('img', {src: w.thumb, alt: '', loading: 'lazy'});
      const place = h('span', {class: 'works-thumb', 'aria-hidden': 'true'}, img);
      img.addEventListener('error', () => { place.classList.add('empty'); img.remove(); place.append((w.name || '?').trim().slice(0, 1).toUpperCase()); });
      return place;
    }
    function parts(w) {
      const bits = [];
      if (w.zones) bits.push(`${w.zones} ${w.zones === 1 ? 'photo zone' : 'photo zones'}`);
      if (w.texts) bits.push(`${w.texts} ${w.texts === 1 ? 'lettering item' : 'lettering items'}`);
      return bits.length ? h('span', {class: 'works-parts small muted'}, bits.join(' · ')) : null;
    }
    function equipment(w) {
      const text = [w.laser ? (w.laser.name || `laser #${w.laser.id}`) : NONE_LABEL.laser,
        w.lens ? (w.lens.name || `lens #${w.lens.id}`) : NONE_LABEL.lens,
        w.material ? (w.material.name || `stock #${w.material.id}`) : NONE_LABEL.material].join(' · ');
      return h('span', {class: 'works-equipment small muted', title: text}, text);
    }
    function row(w) {
      const [stateName, stateKind] = STATE[w.state] || [w.state, ''];
      const size = w.width_mm == null || w.height_mm == null ? '—' : `${num(w.width_mm, 1)} × ${num(w.height_mm, 1)} mm`;
      if (w.broken) {
        return [h('span', {class: 'works-thumb empty', 'aria-hidden': 'true'}, '!'), h('span', {class: 'lst-text works-name'}, w.name), pill('Work data cannot be read', 'bad'),
          h('span', {class: 'works-size small'}, size), equipment(w), h('span', {class: 'works-date small muted'}, when(w.updated_at))];
      }
      // a plain click leaves for the editor and the catalog keeps the place; a click that opens a new tab or window leaves the catalog as it is
      const here_ = (ev) => { if (!(ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey || ev.button)) remember(w.key); };
      const link = (cls, kids, extra = {}) => h('a', {class: cls, href: '#' + w.open, onClick: here_, ...extra}, kids);
      return [link('works-thumb-link', thumb(w), {tabindex: '-1', 'aria-hidden': 'true'}), link('lst-text works-name', w.name, {title: w.name}),
        pill(TYPE[w.type] || w.type), parts(w), h('span', {class: 'works-size small', title: 'Size'}, size), pill(stateName, stateKind), equipment(w),
        h('span', {class: 'works-date small muted', title: 'Modified'}, when(w.updated_at))];
    }

    // -- the operations of a row: the owners' own routes, then the catalog is read again whether they worked or not
    const rowOf = (key) => [...list.el.querySelectorAll('.lst-row')].find((r) => r.getAttribute('data-key') === key) || null;
    const focusMenu = (key) => { const r = rowOf(key); const b = r && r.querySelector('.works-menu-btn'); if (b && b.focus) b.focus(); };
    const keysShown = () => [...list.el.querySelectorAll('.lst-row')].map((r) => r.getAttribute('data-key'));
    function focusNear(key, neighbours) {
      const target = [key, ...neighbours].map(rowOf).find(Boolean);
      const place = target ? (target.getAttribute('data-key') === key ? target.querySelector('.works-menu-btn') : target.querySelector('.works-name'))
        : (list.el.querySelector('.lst-search') || document.getElementById('main'));
      if (place && place.focus) place.focus();
    }
    async function operate(w, work) {
      if (busy.has(w.key)) return;                                         // one operation at a time on a work: a second click does nothing
      busy.add(w.key);
      try { await work(); } finally { busy.delete(w.key); }
    }

    function renameDialog(w) {
      let saving = false, box = null;
      const input = h('input', {value: w.name, autocomplete: 'off', 'aria-label': 'Work name',
        onKeydown: (ev) => { if (ev.key === 'Enter' && !ev.isComposing) { ev.preventDefault(); save(box.close).catch(fail); } }});
      async function save(close) {
        if (saving) return;
        const title = input.value.trim();
        if (!title) throw new Error('Enter a work name');
        if (title === w.name) { close(); return; }
        saving = true;
        try {
          await post(`${w.base}/${w.id}/rename`, {name: title});
          toast('Work renamed', 'ok');
          close();
          await list.refresh();
        } catch (e) {
          saving = false;
          await list.refresh();                                            // the work may be gone or changed elsewhere
          if (e && e.status === 404) close();
          throw e;
        }
      }
      box = modal('Rename work', h('div', {class: 'stack'}, field('Name', input)),
        [{label: 'Cancel', run: (m) => m.close()}, {label: 'Save', cls: 'primary', run: (m) => save(m.close)}], () => focusMenu(w.key));
      if (input.select) input.select();
    }

    function copyWork(w) {
      return operate(w, async () => {
        try {
          await post(`${w.base}/${w.id}/copy`, {});
          toast('Copy created; the original work remains unchanged', 'ok');
        } catch (e) { fail(e); }
        await list.refresh();
        focusMenu(w.key);
      });
    }

    const WARNING = {vector: 'The source image, segmentation and all coloring variants will be deleted and cannot be restored. Make a copy first to preserve them.',
      photo: 'The image and work settings will be deleted and cannot be restored. Make a copy first to preserve them.',
      card: 'The card, both sides, is deleted; exported files stay with you.'};
    function deleteWork(w) {
      const index = keysShown().indexOf(w.key);
      const all = keysShown();
      const neighbours = [all[index + 1], all[index - 1]].filter(Boolean);
      const photographed = w.checks ? ' This work has engraving photographs and cannot be deleted until they are removed.' : '';
      confirmBox(`Delete work “${w.name}”?`, (WARNING[w.kind] || WARNING.vector) + photographed, 'Delete', () => operate(w, async () => {
        try {
          await del('/plans/' + w.id);
          toast('Work deleted', 'ok');
          if (at === w.key) at = null;
        } catch (e) { fail(e); }                                           // refused (a photograph is linked) or already gone: said, then read again
        await list.refresh();
        setTimeout(() => { sync(); focusNear(w.key, neighbours); }, 0);    // after the dialog has closed and given the focus away
      }));
    }

    function actions(w) {
      if (w.broken) return [];                                             // the owners' operations read the data of the work: none of them can act on this one
      return [menu({label: `Actions for work “${w.name}”`, text: '⋯', cls: 'btn-small', items: [
        {label: 'Rename…', run: () => renameDialog(w)}, {label: 'Make a copy', run: () => copyWork(w)},
        {label: 'Delete…', run: () => deleteWork(w), danger: true}]}).el];
    }

    // -- the view: the same list, drawn compactly or as a gallery
    function setView(next) {
      view = next;
      stored.write(view);
      el.classList.toggle('works-gallery', view === 'gallery');
      for (const [name, button] of Object.entries(viewButtons)) button.setAttribute('aria-pressed', String(name === view));
      sync();
    }
    const viewSwitch = h('div', {class: 'works-view', role: 'group', 'aria-label': 'Catalog view'},
      ...[['list', 'List'], ['gallery', 'Gallery']].map(([name, text]) => {
        viewButtons[name] = h('button', {type: 'button', class: 'btn btn-small', 'aria-pressed': 'false', onClick: () => setView(name)}, text);
        return viewButtons[name];
      }));
    const create = menu({label: 'New work', text: 'New work', cls: 'primary', caret: true,
      items: Object.entries(KINDS).map(([kind, [name, hint]]) => ({label: `${name}: ${hint}`, run: () => startCreation(kind)}))});

    // -- the list
    const given = addressed ? {sort: query.sort || DEFAULT_SORT, search: query.q || '', filters: Object.fromEntries(FILTERS.map((k) => [k, query[k] || '']))} : {};
    list = App.list({id: 'works', className: 'works-list', key: (w) => w.key, load, search: true, initial: given, onChange: changed,
      filters: [
        {key: 'type', label: 'Type', all: 'All', options: TYPE_CHIPS},
        {key: 'laser', label: 'Laser', select: true, all: 'any', options: options('laser')},
        {key: 'lens', label: 'Lens', select: true, all: 'any', options: options('lens')},
        {key: 'material', label: 'Stock', select: true, all: 'any', options: options('material')}],
      sorts: SORTS, row, actions,
      rowClass: (w) => (w.broken ? 'works-broken' : ''),
      empty: 'No work yet. Use “New work” to create vector artwork from an image, a photo engraving or a business card.',
      noResults: 'No work matches these conditions.'});

    el.append(
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Works'),
        h('p', {class: 'sub'}, 'Vector work, photo engravings and business cards share one list. Each opens in its editor; mixed work is one document with regions, '
          + 'photo zones and lettering. Work is stored on this computer.')),
        h('span', {class: 'spacer'}), viewSwitch, create.el),
      notice, list.el);
    setView(view);

    /** After the first read: the list is drawn, the address says what it shows, and the work the person came back to is in view or its absence is said. */
    async function ready() {
      await list.ready;
      const wanted = at;
      sync();
      if (!wanted) return;
      const line = rowOf(wanted);
      if (line) {
        later(() => {
          if (line.scrollIntoView) line.scrollIntoView({block: 'center'});
          const target = line.querySelector('.works-name') || line.querySelector('.works-menu-btn');
          if (target && target.focus) target.focus({preventScroll: true});
        });
        return;
      }
      await explain(wanted);
    }
    /** The work the person came back to is not among the rows: gone, or hidden by the search and filters, or too far down. */
    async function explain(wanted) {
      let found = null;
      try { found = await get('/works/' + encodeURIComponent(wanted)); } catch (e) { if (!e || e.status !== 404) return; }      // no answer: the list says so itself
      at = null;
      sync();
      const actions_ = [];
      let text;
      if (found === null) text = 'The work you returned from no longer exists. The list starts at the beginning.';
      else {
        text = `Work “${found.name}” is not shown: it is later in the list or does not match the current search and filters. The list starts at the beginning.`;
        actions_.push(h('a', {class: 'btn btn-small', href: '#' + found.open}, 'Open work'));
        const s = list.state();
        if (s.search || FILTERS.some((k) => s.filters[k])) actions_.push(btn('Clear search and filters', () => { fill(notice); list.reset(); }, 'btn-small'));
      }
      fill(notice, h('div', {class: 'alert warn works-gone'}, h('span', {}, text, ' '), ...actions_,
        btn('Close', () => fill(notice), 'btn-small')));
    }

    return {el, list, ready, address, startCreation, state: () => ({view, at})};
  }

  App.register({id: 'works', async render(ctx) {
    const screen = build(ctx.query || {});
    await screen.ready();
    return screen.el;
  }});

  return {startCreation, build};
})();
