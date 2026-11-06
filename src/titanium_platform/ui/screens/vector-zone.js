/* Photo zone editor: shared photo panels, scale selection, and vector work history (DEC-116). */
'use strict';
(() => {
  const {h, fill, btn, get, post, go, toast} = App;
  const {value, GRAYSCALE, dotted, fromMap, firedSettings, kindName, settingsText, modeQuery, sameScale, scaleCard, newSlots, emptySlots, scaleDetail,
    workPicture, kindChooser} = PhotoPanels;
  let keys = null; // Undo and redo belong to the vector work.
  document.addEventListener('keydown', (ev) => { if (keys) keys(ev); });

  /** Work title and vector history controls. */
  function zoneHead(first, step) {
    const title = h('div', {class: 'ge-title'});
    const undo = btn('Undo', () => step('undo'), 'btn-small'), redo = btn('Redo', () => step('redo'), 'btn-small');
    const el = h('div', {class: 'os-head'}, h('a', {class: 'btn btn-small', href: `#/vector?plan=${first.work.id}`}, '← Back to work'), title,
      h('div', {class: 'row', role: 'group', 'aria-label': 'Undo and redo'}, undo, redo));
    function update(next) {
      undo.disabled = !(next.work.undo > 0);
      redo.disabled = !(next.work.redo > 0);
      undo.setAttribute('title', `Undo (Ctrl+Z) — vector work steps: ${next.work.undo}`);
      redo.setAttribute('title', `Redo (Ctrl+Shift+Z) — vector work steps: ${next.work.redo}`);
      fill(title, h('h2', {}, `Photo zone ${next.number}`),
        h('p', {class: 'sub'}, [`Work “${next.work.name}”`, next.name, `Regions: ${next.regions.length}`,
          `${value(next.box.width, 1)} × ${value(next.box.height, 1)} mm`].filter(Boolean).join(' · ')));
    }
    update(first);
    return {el, update};
  }

  /** Send changes in order and display the latest response. Each scale has its own limits. */
  async function zoneScreen(work, number) {
    const base = `/vector/${work}/photo/${number}`;
    const first = await get(base);
    const query = new URLSearchParams({device_id: first.work.device_id, material_id: first.work.material_id ?? ''});
    if (first.work.lens_id != null) query.set('lens_id', String(first.work.lens_id));
    query.set('row_mm', String(first.width_mm));
    let scales = [];
    let view = first, detail = null, shownKey = null, seq = 0, queue = Promise.resolve(), left = false;
    let scalesWidth = null, scalesRequest = null, selectedDetail = null;
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const list = h('div', {class: 'ge-scales'});
    const scaleHeading = h('h3', {}, 'Zone scale');
    const scaleStatus = h('div', {'aria-live': 'polite'});
    const scaleListHost = h('div', {hidden: true}, list);
    const scaleArea = h('div', {class: 'os-scroll'}, scaleStatus, scaleListHost);
    const slots = newSlots();
    /** Describe the zone's layer in the exported work. */
    const layer = (info) => (dotted(view)
      ? `LightBurn file: layer ${view.name} is an image in ${kindName(view.kind)} mode, at ${value(info.dots.power, 1)} % power (Min = Max for every dot), `
        + `${settingsText(firedSettings(view), info.dpi)}${!fromMap(view) ? '' : PhotoQuality.fromPhoto(view.dot_recipe) ? ` — dot settings ${PhotoQuality.recipeFrom(view.dot_recipe)}` : ' — color map settings'}. `
        + 'The image occupies the zone and is transparent outside its regions. LightBurn places the dots.'
      : `LightBurn file: layer ${view.name} is a grayscale image after the color layers: Min ${value(info.power_range[0], 1)} %, `
        + `Max ${value(info.power_range[1], 1)} %, ${settingsText(view.scale, info.dpi)}. The image occupies the zone and is transparent outside its regions.`);
    const picture = workPicture(save, () => kindChooser(base, view.kind || GRAYSCALE, (kind) => save({kind})), {width: false, objects: false, layer, variations: `${base}/variations`, advice: base});
    const head = zoneHead(view, step);
    const tabs = App.tabs([['picture', 'Image', picture.details], ['results', 'Results', PhotoPanels.exportedResults(view.work.id, view.number)], ['scale', 'Scale', slots.scale], ['confirm', 'Confirmation', slots.confirm],
      ['points', 'Points', slots.points]], {initial: 'picture', remember: 'vz.zone.tab', label: 'Image and scale', prefix: 'vz-tab'});
    const chosen = () => scales.find((sc) => sameScale(sc, view.scale)) || null;
    // at the zone's width, for its kind and where its dots' colour comes from (the scale or a recipe of the colour map)
    const scaleKey = (v, mode = v.scale) => `${modeQuery(mode)}&row_mm=${v.width_mm}&kind=${v.kind || GRAYSCALE}&dots=${fromMap(v) ? v.dot_recipe.entry : ''}`;
    const cards = (current) => fill(list, scales.map((item) => scaleCard(
      item === current && selectedDetail ? {...item, ...selectedDetail} : item, item === current, () => pick(item))));

    function showScale() {
      if (detail) detail.stop();
      selectedDetail = null;
      if (scalesWidth !== view.width_mm) {
        if (scalesRequest && scalesRequest.width === view.width_mm) return;
        const request = scalesRequest = {width: view.width_mm};
        const width = request.width;
        query.set('row_mm', String(width));
        emptySlots(slots, 'Loading scales for the zone width…');
        scaleListHost.hidden = true;
        fill(scaleStatus, h('p', {class: 'small muted', role: 'status'}, 'Loading measured scales…'));
        get(`/grey-scales?${query}`).then((next) => {
          if (left || scalesRequest !== request || view.width_mm !== width) return;
          scalesRequest = null;
          scalesWidth = width;
          scales = next.scales;
          fill(scaleHeading, `Zone scale (${scales.length} measured)`);
          fill(scaleStatus, scales.length ? null : h('p', {class: 'muted small'},
            'No grayscale scales exist for this laser, lens, and titanium. Engrave a grayscale test plate and add its photograph.'));
          scaleListHost.hidden = !scales.length;
          showScale();
        }).catch((e) => {
          if (!left && scalesRequest === request) {
            scalesRequest = null;
            fill(scaleStatus, h('p', {class: 'alert bad', role: 'alert'}, `Could not load measured scales: ${e.message}`),
              btn('Retry scales', showScale, 'btn-small'));
          }
        });
        return;
      }
      scalesRequest = null;
      const sc = chosen();
      shownKey = scaleKey(view);
      cards(sc);
      const dot = dotted(view) && view.dot_power != null ? {power: view.dot_power, changed: (p) => save({dot_power: p}),
        recipe: fromMap(view) ? view.dot_recipe : null, hex: view.picture && view.picture.dots ? view.picture.dots.hex : null, dpi: view.dpi,
        map: () => go(DotPick.zoneAddress(view.work, view.number))} : null;
      if (sc) detail = scaleDetail(sc, slots, {initial: [view.min_power, view.max_power], changed: (lo, hi) => save({min_power: lo, max_power: hi}), rowMm: view.width_mm, dot,
        loaded: (data) => { selectedDetail = data; cards(chosen()); }});
      else { detail = null; emptySlots(slots, 'This zone’s scale has not been measured. Choose a scale on the left.'); }
    }
    function shown() {
      head.update(view);
      picture.show(view, chosen());
      if (scaleKey(view) !== shownKey) showScale();
    }
    /** Return to the work if undo removed the zone. */
    function leave() {
      left = true;
      if (detail) detail.stop();
      toast('Undo removed the photo zone. The work is open.', 'ok');
      go(`/vector?plan=${work}`);
    }
    /** One change of the zone (``path`` with ``body``): sent after those before it; the answer to the last one is shown. With ``again``
        the scale is shown anew from the answer (an undo or redo can bring back other Min and Max on the same scale). The promise gives the
        error of this change, or null. */
    function send(path, body, again = false) {
      if (left) return Promise.resolve(null);
      const mine = ++seq;
      error.hidden = true;
      picture.waiting();
      queue = queue.then(() => post(path, body)).then((next) => {
        if (next.gone) { leave(); return null; }
        picture.compare(view, next);
        view = next;
        if (mine === seq) { if (again) shownKey = null; shown(); }
        return null;
      }, (e) => { if (mine === seq) { error.textContent = e.message; error.hidden = false; shown(); picture.failed(); } return e; });
      return queue;
    }
    function save(changes) { return send(`${base}/settings`, changes); }
    /** Undo or redo a step in the containing vector work. */
    function step(kind) { return (view.work[kind] || 0) > 0 ? send(`${base}/${kind}`, {}, true) : Promise.resolve(null); }
    /** Selecting a scale uses its measured power range. */
    function pick(item) {
      if (scaleKey(view, item.mode) === shownKey) return;
      if (detail) detail.stop();
      detail = null;
      shownKey = null;
      selectedDetail = null;
      cards(item);
      emptySlots(slots, 'Loading scale…');
      save({scale: item.mode});
    }
    shown();
    const root = h('div', {class: 'os ge'});
    const key = (ev) => {
      if (!root.isConnected) { if (keys === key) keys = null; return; }
      const t = ev.target;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '') || t.isContentEditable)) return; // Keep keyboard input in the field.
      if (document.querySelector('.modal-bg')) return;
      const z = ev.code === 'KeyZ' || (ev.key || '').toLowerCase() === 'z', y = ev.code === 'KeyY' || (ev.key || '').toLowerCase() === 'y';
      if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (z || y)) { ev.preventDefault(); step(z && !ev.shiftKey ? 'undo' : 'redo'); }
    };
    keys = key;
    return fill(root, head.el, h('div', {class: 'os-body ge-body'},
      h('div', {class: 'os-col'}, h('div', {class: 'os-col-head'}, scaleHeading), scaleArea),
      h('div', {class: 'os-col ge-centre'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Zone on scale'), slots.title),
        h('div', {class: 'ge-work'}, picture.inputs, picture.tone, PhotoPanels.calibrationControls(slots.powers), slots.error, error, slots.bar, picture.out, picture.comparison, picture.foot)),
      h('div', {class: 'os-col ge-right'}, tabs.list, h('div', {class: 'os-scroll'}, tabs.panels))));
  }

  App.register({id: 'vector-zone', async render(ctx) {
    if (!ctx.query.work || !ctx.query.zone) { go('/vector'); return h('div'); }
    return zoneScreen(encodeURIComponent(ctx.query.work), encodeURIComponent(ctx.query.zone));
  }});
})();
