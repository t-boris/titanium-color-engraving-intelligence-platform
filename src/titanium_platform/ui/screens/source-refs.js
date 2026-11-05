/* Source numbers behind a count: «Наблюдения-основания: 24» instead of a line of twenty-four numbers (ux-growing-collections-p0, REQ-002).
   A count and, on request, a list of links: every number stays reachable (each one is a link to the analysis of its photograph) and none is
   dropped, however long the list. Long lists are shown fifty at a time. A short list (up to five numbers) is open from the start.
   The numbers are plain ids; a screen gives either ``href`` (a route for an id) or ``resolve`` (the ids of a page -> the routes and names,
   asked of the server only for the page that is shown). */
'use strict';
const SourceRefs = (() => {
  const {h, fill, btn, get} = App;
  const SHORT = 5;                  // up to this many numbers are shown at once, without a button
  const PAGE = 50;                  // numbers shown at a time in a long list
  let serial = 0;                   // makes the id a button controls unique on the page

  /** The photograph and layer behind observation numbers: one request for the page of numbers shown (GET /observations/refs). */
  async function resolveObservations(ids) {
    const found = await get('/observations/refs?ids=' + ids.join(','));
    return found.map((r) => ({id: r.id, route: r.pair_id == null ? null : '/analysis/' + r.pair_id,
      note: r.pair_id == null ? 'не найдено' : [r.photo_name, r.layer_name || (r.layer_index == null ? null : `слой ${r.layer_index}`)].filter(Boolean).join(' · ')}));
  }

  /** A count and a list of links for ``ids``. ``opts``: label («Наблюдения-основания»), mark («№»), href(id) -> route, resolve(ids) ->
      [{id, route, note}] (when it fails the numbers stay as plain text and a retry is offered), toggle: [shown, hidden] captions of the
      button, short (numbers shown without a button), page (numbers per click of «Показать ещё»), open (start expanded), className.
      Returns the node. */
  function refs(input, opts = {}) {
    const ids = [...new Set((input || []).map((id) => String(id)))];
    const label = opts.label || 'Источники';
    const mark = opts.mark == null ? '№' : opts.mark;
    const short = opts.short == null ? SHORT : opts.short;
    const size = opts.page || PAGE;
    const [showText, hideText] = opts.toggle || ['Показать номера', 'Скрыть номера'];
    const box = h('div', {class: 'srefs' + (opts.className ? ' ' + opts.className : '')});
    if (!ids.length) return fill(box, h('span', {class: 'muted small'}, `${label}: нет`));

    const listId = 'srefs-' + (++serial);
    const long = ids.length > short;
    let expanded = opts.open == null ? !long : Boolean(opts.open);
    let shown = 0;                                   // how many numbers are drawn in the list
    let busy = false;                                // one request at a time: a second click while one is on its way does nothing
    let failure = null;                              // the text of the last request that failed
    const known = new Map();                         // id -> {id, route, note}: what the server said of the numbers drawn so far
    const unresolved = () => (opts.resolve ? ids.slice(0, shown).filter((id) => !known.has(id)) : []);

    const toggle = long ? h('button', {type: 'button', class: 'btn btn-small srefs-toggle', 'aria-controls': listId, 'aria-expanded': String(expanded),
      onClick: () => flip()}, expanded ? hideText : showText) : null;
    const head = h('p', {class: 'srefs-head'}, h('span', {class: 'srefs-label'}, label + ': '), h('strong', {class: 'srefs-count'}, String(ids.length)), ' ', toggle);
    const list = h('ul', {class: 'srefs-list', id: listId, 'aria-label': label, hidden: !expanded});
    const status = h('span', {class: 'muted small srefs-status', role: 'status'});
    const actions = h('span', {class: 'srefs-actions'});
    const foot = h('div', {class: 'srefs-foot', hidden: !expanded}, status, actions);
    box.append(head, list, foot);

    const item = (id) => {
      const info = known.get(id);
      const text = `${mark}${id}`;
      const route = info ? info.route : (opts.href ? opts.href(id) : null);
      return h('li', {class: 'srefs-item'}, route ? h('a', {href: '#' + route, title: info && info.note ? `${text} · ${info.note}` : text}, text) : h('span', {}, text),
        info && info.note ? h('span', {class: 'muted small srefs-note'}, ` ${info.note}`) : null);
    };
    function draw() {
      const rest = ids.length - shown;
      fill(list, ids.slice(0, shown).map(item));
      status.textContent = busy ? 'Загружаем…' : `показано ${shown} из ${ids.length}`;
      fill(actions, failure ? h('span', {class: 'alert bad srefs-fail', role: 'alert'}, `Не удалось получить ссылки: ${failure} `,
        btn('Повторить', () => retry(), 'btn-small srefs-retry', busy)) : null,
      rest > 0 ? btn(`Показать ещё ${Math.min(size, rest)}`, () => more(), 'btn-small srefs-more', busy) : null);
    }
    /** Ask the server about ``wanted`` a page at a time; a failure leaves the numbers as plain text and says so. */
    async function ask(wanted) {
      if (!opts.resolve || !wanted.length) return;
      busy = true;
      failure = null;
      draw();
      try {
        for (let at = 0; at < wanted.length; at += size) for (const info of await opts.resolve(wanted.slice(at, at + size))) known.set(String(info.id), info);
      } catch (e) { failure = e.message || String(e); }
      busy = false;
    }
    async function more() {
      if (busy) return;
      const from = shown;
      const chunk = ids.slice(from, from + size);
      shown = from + chunk.length;                   // drawn now as plain text, then named by the server: no number is ever missing
      await ask(chunk);
      draw();
      const first = from ? list.querySelectorAll('li')[from] : null;
      const link = first && (first.querySelector('a') || first);
      if (link && link.focus) link.focus();          // the keyboard continues where the new numbers begin
    }
    async function retry() {
      if (busy) return;
      await ask(unresolved());
      draw();
    }
    function flip() {
      expanded = !expanded;
      toggle.setAttribute('aria-expanded', String(expanded));
      fill(toggle, expanded ? hideText : showText);
      list.hidden = foot.hidden = !expanded;
      if (expanded && shown === 0) more();
    }
    if (expanded) more();
    return box;
  }

  /** The observations behind a result, as links to the analysis of their photographs. */
  const observations = (ids, opts = {}) => refs(ids, {label: 'Наблюдения-основания', resolve: resolveObservations, ...opts});
  /** Photographs (pairs) by their numbers, as links to their analysis. */
  const photos = (ids, opts = {}) => refs(ids, {label: 'Фото', href: (id) => '/analysis/' + id, ...opts});

  return {refs, observations, photos, SHORT, PAGE};
})();
