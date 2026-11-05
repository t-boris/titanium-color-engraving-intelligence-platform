/* The sets of observations on the colour map: a search and pages instead of a button for every RAW pair (ux-growing-collections-p0, REQ-002, REQ-003).
   The sets of one laser and lens (the calibrated observations and every RAW pair) as the compact list: a search, pages of twenty and the set
   the page shows now kept in view as a pinned line when the search or the page leaves it out, with the reason and a way back. A set is the
   screen's own object ``{id, title, note}``; choosing one is the screen's business (``onSelect``), the list only draws and finds. */
'use strict';
const SetList = (() => {
  const {h} = App;

  /** ``sets``: [{id, title, note}] in the order they are listed. ``opts``: ``selected`` (the id of the set shown now, or a function that
      returns it), ``onSelect(id)``, ``id`` (the key the search and pages are kept under in the browser; without it they are not kept), ``empty``. Returns the list: ``el``, ``refresh()``
      (call it after the shown set changed, so that the pressed line follows), ``open``, ``reset``. */
  function list(sets, opts) {
    const current = () => {
      const now = typeof opts.selected === 'function' ? opts.selected() : opts.selected;
      return now == null ? null : String(now);
    };
    return App.list({
      id: opts.id, items: sets, key: (s) => s.id, selected: current, className: 'lm-sets-list',
      search: (s) => `${s.title} ${s.note || ''}`,
      row: (s) => {
        const on = String(s.id) === current();
        return [h('button', {type: 'button', class: 'lm-set' + (on ? ' active' : ''), 'aria-pressed': String(on), title: `${s.title} · ${s.note || ''}`,
          onClick: () => opts.onSelect(s.id)}, h('strong', {}, s.title), h('span', {class: 'muted small'}, s.note || ''))];
      },
      sorts: [['listed', 'Как в списке', (a, b) => sets.indexOf(a) - sets.indexOf(b)]],
      empty: opts.empty || 'Наборов нет', noResults: 'Наборов с таким названием нет.'});
  }

  return {list};
})();
