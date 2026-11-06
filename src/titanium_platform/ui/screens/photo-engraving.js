/* Photo engraving works, measured scales, previews, and engraving review. */
'use strict';
(() => {
  const {h, fill, btn, link, pill, get, post, del, form, field, go, toast, modal, confirmBox, duration, table, fail} = App;
  const {value, when, materialLabel, titaniumLabel, settingsText, modeQuery, GRAYSCALE, dotted, fromMap, firedSettings, kindName, hexChip, mm, mmList, scaleBar, scaleCard, newSlots, emptySlots,
    scaleDetail, sameScale, workPicture, colourTab, aiTab, kindChooser} = PhotoPanels;
  let keys = null;                                     // keyboard shortcuts for the open work, as in the vector editor
  document.addEventListener('keydown', (ev) => { if (keys) keys(ev); });
  const PICTURES = 'image/png,image/jpeg,image/tiff,image/bmp,image/webp';
  const PREVIEW_GAP = 8;                     // px of white between the picture and its look in the preview (prediction.GAP)
  // ux-save-feedback-p0: what a change of the work is called when it could not be saved, and which of its fields the controls draw (a field
  // that was not saved stays in its control; the others are redrawn from the work as the server has it)
  const SAVED_NAMES = {width_mm: 'Width, mm', by_colour: 'Match grayscale to colors', colour_choice: 'How to match grayscale', contours: 'Contours',
    tone: 'Brightness, contrast, gamma', sharpness: 'Sharpness', kind: 'Engraving mode', scale: 'Scale', min_power: 'Min, %', max_power: 'Max, %',
    dot_power: 'Dot power, %', dot_width: 'Dot width, mm', ai_photo: 'AI can see the image', rules: 'AI rules', colouring: 'Coloring'};
  const KEPT_IN_CONTROLS = ['width_mm', 'by_colour', 'colour_choice', 'contours', 'tone', 'sharpness', 'dot_width', 'ai_photo'];
  /** Save a server file locally and show errors without navigating to the API URL. */
  async function download(path, fallbackName) {
    let res;
    try { res = await fetch('/api' + path); } catch (_) { throw new Error('Cannot reach the local service. Is the application running?'); }
    if (!res.ok) {
      let raw = null;
      try { const d = await res.json(); raw = (d.detail || d).error; } catch (_) { raw = null; }
      throw new Error(raw ? I18N.tr(raw) : `Server error (${res.status}). The file was not received.`);
    }
    const name = decodeURIComponent((res.headers.get('content-disposition') || '').split("UTF-8''")[1] || fallbackName);
    const url = URL.createObjectURL(await res.blob());
    const a = h('a', {href: url, download: name});
    document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }

  const PAIR_STATUS = {'Awaiting check': ['awaiting review', 'warn'], 'Needs correction': ['needs correction', 'warn'], 'Ready to accept': ['ready to accept', 'warn'],
    Accepted: ['accepted', 'ok']};
  const NOT_COMPARED = {no_points: 'The photo did not yield clear colors for these settings: the layer was not found or its grays could not be distinguished.',
    kind: 'The photo has no reference chart but the scale colors are chart-corrected, or vice versa, so they cannot be compared.',
    alone: 'There are no other engravings with these settings to compare; this engraving itself became the scale.',
    outside: 'This engraving’s power is outside the range measured by other engravings.',
    other_size: (c) => `No other engravings with these settings have a width near ${mm(c.row_mm)} (the scale was measured at ${mmList(c.size.measured_mm)}); color at another `
      + 'width cannot predict this one. This engraving itself became the scale for its width.'};
  const notCompared = (c) => (typeof NOT_COMPARED[c.reason] === 'function' ? NOT_COMPARED[c.reason](c) : NOT_COMPARED[c.reason] || c.reason);

  /** Compare accepted engravings with predictions from other measurements. */
  function engravingsBlock(id) {
    const el = h('div', {class: 'stack'}, h('p', {class: 'muted small'}, 'Loading work engravings…'));
    let seq = 0;
    function strip(bands, key, label) {
      return h('div', {class: 'ge-strip-row'}, h('span', {class: 'small muted'}, label),
        h('div', {class: 'ge-strip ge-compare'}, bands.map((b) => h('span', {style: `background:${b[key]}`, title: `gray ${Math.round(b.gray * 255)} · ${value(b.power, 1)} % · ΔE ${value(b.de, 1)}`}))));
    }
    function entry(e) {
      const [label, tone] = PAIR_STATUS[e.status] || [e.status, 'warn'];
      const where = e.status === 'Accepted' ? '/analysis/' + e.pair_id : '/ingest?pair=' + e.pair_id;
      const c = e.check;
      const bands = c ? [...c.bands].sort((a, b) => a.power - b.power) : [];
      return h('li', {class: 'ge-entry stack'},
        h('div', {class: 'ge-entry-head'}, h('span', {}, link(where, `#${e.pair_id} · ${e.photo_name}`), ` · ${when(e.accepted_at || e.created_at)}`), pill(label, tone)),
        e.same_scale === false ? h('p', {class: 'small alert warn'}, `Engraved with settings different from the work’s scale: ${settingsText(e.mode)}; compared with engravings using those settings.`) : null,
        e.settings && e.settings.power_range ? h('p', {class: 'small muted'}, `Min ${value(e.settings.power_range[0], 1)} % · Max ${value(e.settings.power_range[1], 1)} % in file`
          + (e.row_mm != null ? ` · width ${mm(e.row_mm)}` : '')) : null,
        e.status !== 'Accepted' ? h('p', {class: 'small muted'}, 'Comparison will appear after the photo review is accepted; open it using the link.') : null,
        c && c.reason ? h('p', {class: 'small'}, notCompared(c)) : null,
        c && !c.reason ? h('div', {class: 'stack'},
          h('p', {class: 'small'}, pill(c.confirmed ? `confirms prediction: median ${value(c.median_de, 1)} ΔE` : `does not confirm: median ${value(c.median_de, 1)} ΔE`, c.confirmed ? 'ok' : 'warn'),
            ` ${c.compared} grays compared; ${value(c.within * 100, 0)} % within ${c.tolerance_de} ΔE; maximum difference ${value(c.max_de, 1)} ΔE; `
            + `prediction uses ${c.others} other ${c.others === 1 ? 'engraving' : 'engravings'} with these settings`
            + (c.size && c.size.how === 'between' ? `, between measurements at widths ${mmList(c.size.from_mm)}.` : c.size && c.size.from_mm.length ? ` at width ${mm(c.size.from_mm[0])}.` : '.')),
          strip(bands, 'predicted_hex', 'Prediction'), strip(bands, 'hex', 'Actual'),
          h('details', {}, h('summary', {class: 'small'}, 'By gray'),
            table(['Gray', 'Power, %', 'Prediction', 'Actual', 'ΔE'], bands.map((b) => [String(Math.round(b.gray * 255)), value(b.power, 1),
              hexChip(b.predicted_hex), hexChip(b.hex), b.de > c.tolerance_de ? pill(value(b.de, 1), 'warn') : value(b.de, 1)]), '', true))) : null);
    }
    async function load(view) {
      const mine = ++seq;
      const upload = link(`/ingest?plan=${id}` + (view.scale && view.scale.material_id ? `&material=${view.scale.material_id}` : ''), 'Upload an engraving photo');
      try {
        const list = await get(`/photo-works/${id}/engravings`);
        if (mine !== seq) return;
        fill(el, h('h4', {}, 'Engravings of this work'),
          h('p', {class: 'small'}, 'Each gray in the engraved work is compared with the color predicted by other engravings using these settings; this lets an '
            + 'experiment confirm the prediction or adjust the scale. The LightBurn file carries the work name, so a photo uploaded with it links to the work automatically.'),
          h('p', {}, upload),
          list.length ? h('ul', {class: 'ge-entries'}, list.map(entry)) : h('p', {class: 'muted small'}, 'There are no engraving photos for this work yet.'));
      } catch (e) { if (mine === seq) fill(el, h('p', {class: 'alert bad'}, e.message), h('p', {}, upload)); }
    }
    return {el, load};
  }

  /** Render work heading and actions. */
  function workHead(first, step) {
    const title = h('div', {class: 'ge-title'});
    const undo = btn('Undo', () => step('undo'), 'btn-small'), redo = btn('Redo', () => step('redo'), 'btn-small');
    const copy = btn('Make a copy', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { const made = await post(`/photo-works/${first.id}/copy`, {}); toast('Copy created and opened; this work remains unchanged', 'ok'); go('/photo-engraving?work=' + made.id); }
      catch (e) { fail(e); self.disabled = false; }
    }, 'btn-small');
    // the one wording and behaviour of a file download (ux-engraving-lifecycle-p0): one press at a time, a failure stays beside the button with a retry
    const file = Lifecycle.downloadButton(`/photo-works/${first.id}/export.lbrn2`, 'picture.lbrn2', 'Download LightBurn', {cls: 'primary btn-small'}).el;
    const check = h('a', {class: 'btn btn-small', href: `#/photo-preview?work=${first.id}`,
      title: 'Open the work file in Photo engraving preview with its scale’s titanium, laser, and lens'}, 'Preview file');
    const context = h('p', {class: 'sub muted', 'aria-label': 'Laser, lens, and titanium for this work'});     // the work's own, saved in it (ux-work-creation-p0)
    const el = h('div', {class: 'os-head'}, h('a', {class: 'btn btn-small', href: '#/photo-engraving'}, '← My works'), title,
      h('div', {class: 'row', role: 'group', 'aria-label': 'Undo and redo'}, undo, redo),
      h('a', {class: 'btn btn-small', href: '#/photo-engraving?scales=1'}, 'Grayscale scales'), copy, check, file);
    let shown = first;
    function update(next) {
      shown = next;
      undo.disabled = !(next.undo > 0);
      redo.disabled = !(next.redo > 0);
      undo.setAttribute('title', `Undo (Ctrl+Z); steps: ${next.undo || 0}`);
      redo.setAttribute('title', `Redo (Ctrl+Shift+Z); steps: ${next.redo || 0}`);
      const pencil = VectorWorkspace.renameButton(next.id, next.name, (stored) => update({...shown, name: stored}), '/photo-works');
      fill(title, h('p', {class: 'small muted'}, 'Photo engraving'), h('div', {class: 'vw-name-row'}, h('h2', {title: next.name}, next.name), pencil),
        h('p', {class: 'sub'}, `${next.image_name || 'image'} · ${next.image_size[0]} × ${next.image_size[1]} px · ${value(next.width_mm, 1)} × ${value(next.height_mm, 1)} mm`
          + ` · updated ${when(next.updated_at)}`), context);
      App.workContextText(next).then((text) => { context.textContent = text; });
    }
    update(first);
    return {el, update};
  }

  const DOT_WIDTH_ABOUT = 'LightBurn Dot Width Correction accounts for a laser dot wider than an image pixel; without correction '
    + 'the image comes out darker. LightBurn reduces each dot by this width. It is recorded in the file layer and the test for this mode; tones '
    + 'measured at one dot width do not apply to another. Dot modes only.';
  /** The dot width correction of a dot kind (0.28.0): a check box and the laser's dot width in mm, saved in the work by ``save({dot_width})``.
      A width turns the correction on, an empty field or a cleared box turns it off; a ticked box on an empty field waits for a width. In
      greyscale there is no correction: the field is hidden and the width waits in the work. */
  function dotWidthBox(save) {
    const on = h('input', {type: 'checkbox', 'aria-label': 'Dot width correction'});
    const width = Forms.numberInput(Forms.QUANTITIES.dotWidth, {step: '0.001', 'aria-label': 'Laser dot width'});
    const given = () => { const r = Forms.parse(width.value, Forms.QUANTITIES.dotWidth); return r.ok ? r.value : null; };
    on.addEventListener('change', () => {
      if (!on.checked) save({dot_width: null});
      else if (given() != null) save({dot_width: given()});
    });
    // a width outside what LightBurn takes is kept in the box with the reason beside it and is not saved; an empty box switches the correction off
    const wrong = Forms.watch(width, 'dotWidth', (value) => { on.checked = value != null; save({dot_width: value}); });
    const rules = Forms.describe(width, 'dotWidth');
    const el = h('label', {class: 'ge-power ge-dotwidth', title: DOT_WIDTH_ABOUT}, on, h('span', {class: 'small'}, 'Dot width correction'), width,
      h('span', {class: 'small'}, 'mm'), rules, wrong);
    function show(view) {
      el.hidden = !dotted(view) || !!view.problem;
      on.checked = view.dot_width != null;
      if (view.dot_width != null) width.value = String(view.dot_width);
    }
    return {el, show};
  }

  /** The measured grey scales as a short list (DEC-090): a line a scale — its colour bar, its settings and “selected” on the chosen one — the
      best first (the server's order: scales a recipe refers to, then the most engraved and measured), pages of 20. A line opens the scale's
      card (its titanium, engravings, widths, confirmation); pressing the card chooses the scale. ``chosen()`` is the scale chosen now: the list
      opens on it. */
  function scaleList(id, scales, chosen, choose, display = (sc) => sc) {
    const key = (sc) => modeQuery(sc.mode);
    const rank = new Map(scales.map((sc, i) => [sc, i]));
    const best = (a, b) => rank.get(a) - rank.get(b);
    const now = chosen();
    const list = App.list({id, items: scales, key, open: now ? key(now) : null, className: 'ge-scale-list',
      row: (sc) => [scaleBar(display(sc)),
        h('span', {class: 'lst-text', title: `${settingsText(sc.mode, sc.dpi)} · ${titaniumLabel(sc)}`}, settingsText(sc.mode, sc.dpi)),
        sc === chosen() ? pill('selected', 'ok') : null],
      details: (sc) => scaleCard(display(sc), sc === chosen(), () => choose(sc)),
      search: (sc) => `${settingsText(sc.mode, sc.dpi)} ${titaniumLabel(sc)}`,
      sorts: [['best', 'Best first', best], ['fast', 'Fastest', (a, b) => (a.time_s_per_cm2 ?? Infinity) - (b.time_s_per_cm2 ?? Infinity) || best(a, b)],
        ['wide', 'Widest power range', (a, b) => (b.span[1] - b.span[0]) - (a.span[1] - a.span[0]) || best(a, b)]],
      empty: 'No scales match this search.'});
    list.setScales = (next) => { rank.clear(); next.forEach((sc, i) => rank.set(sc, i)); list.items = next; };
    return list;
  }

  /** Render the work and serialize changes in their original order. */
  async function workScreen(id) {
    const first = await get('/photo-works/' + id);
    let scales = [];
    let view = first, detail = null, shownKey = null, current = null;
    let scalesWidth = null, scalesRequest = null, selectedDetail = null;
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const slots = newSlots();
    const base = `/photo-works/${id}`;
    // Every change of the work goes through ``doc`` (save-state.js, BUG-002, BUG-011): one after another in the order made, an answer is shown
    // only when it is the answer to the newest change, a change that failed stays in its control with the error beside the work.
    const doc = SaveState.create({label: 'Work', confirmed: first, names: SAVED_NAMES,
      send: async (request) => { const previous = view; const next = await post(request.path, request.body); picture.compare(previous, next); view = next; return next; },
      apply: (next, info) => { if (info.reverted || info.edits.some((e) => e.meta.again)) shownKey = null; shown(); },
      reload: async () => { view = await get(base); doc.adopt(view); },
      onOrphanFailure: (lost) => { if (typeof Operations !== 'undefined') Operations.report({title: `Work “${view.name}”: changes not saved`, message: `${lost.message} ${lost.describe}`.trim(),
        context: {route: `/photo-engraving?work=${id}`, label: 'Photo engraving'}, recover: {label: 'Open work', route: `/photo-engraving?work=${id}`}, details: [['Work', `#${id}`]]}); }});
    /** The work as the controls draw it: as the server has it, with the fields that could not be saved as they were typed. */
    const drawn = () => {
      const own = doc.local();
      const kept = KEPT_IN_CONTROLS.filter((k) => k in own);
      return kept.length ? {...view, ...SaveState.pick(own, kept)} : view;
    };
    // inscriptions are included in the server prediction; the overlay supplies handles and outlines
    let tab = null;
    const lettering = Lettering.create(view, {act: async (op) => !(await send(`${base}/texts`, op)), palette: () => get(`${base}/palette`),
      size: (v) => ({width: v.width_mm, height: v.height_mm}), drawn: false, open: () => tab === 'texts',
      pick: (title, lab, entryId, onPick) => VectorColours.pickFrom(() => get(`${base}/palette`), title, lab, entryId, onPick,
        {imageUrl: `/api${base}/picture`})});
    const picture = workPicture(save, () => kindChooser(base, view.kind || GRAYSCALE, (kind) => save({kind})),
      {ramp: `${base}/width-ramp`, variations: `${base}/variations`, advice: base, original: `/api${base}/picture`, stage: (el, cols) => lettering.attach(el, cols, PREVIEW_GAP)});
    doc.onChange((state) => {
      if (state.status === 'calculating' || state.status === 'saving') picture.waiting();
      else if (state.status === 'failed') picture.failed();
    });
    const head = workHead(view, step);
    // feature electron, REQ-085: a work pinned to a laboratory release shows its source under the head; a confirmed step brings the work anew
    const banner = LabSource.banner(base, 'photo', (next) => { view = next; doc.adopt(next); shownKey = null; shown(); });
    const dotWidth = dotWidthBox(save);
    const ai = aiTab(base, save, (wish, fresh) => send(`${base}/ai`, {wish, fresh}));
    const colour = colourTab(base, save, (path, body) => send(path, body));
    const engraved = engravingsBlock(id);
    const tabs = App.tabs([['picture', 'Image', picture.details], ['colour', 'Coloring', colour.el], ['ai', 'AI', ai.el], ['scale', 'Scale', slots.scale],
      ['confirm', 'Confirmation', h('div', {class: 'stack'}, engraved.el, slots.confirm)],
      ['points', 'Dots', slots.points], ['texts', 'Inscriptions', lettering.el]],
    {initial: 'picture', remember: 'ge.work.tab', label: 'Image and scale', prefix: 'ge-tab', onSelect: (id) => { tab = id; lettering.opened(); }});
    const chosen = () => scales.find((sc) => sameScale(sc, view.scale)) || null;
    // at the work's width, for its kind and where its dots' colour comes from (the scale or a recipe of the colour map)
    const scaleKey = (v, mode = v.scale) => `${modeQuery(mode)}&row_mm=${v.width_mm}&kind=${v.kind || GRAYSCALE}&dots=${fromMap(v) ? v.dot_recipe.entry : ''}`;
    current = chosen();
    let list = null;
    const scaleHeading = h('h3', {}, 'Work scales');
    const scaleStatus = h('div', {'aria-live': 'polite'});
    const scaleListHost = h('div', {hidden: true});
    const scaleArea = h('div', {class: 'os-scroll'}, scaleStatus, scaleListHost);
    const cards = (sc) => { current = sc; if (list) list.refresh(); };

    function showScale() {
      if (detail) detail.stop();
      selectedDetail = null;
      if (scalesWidth !== view.width_mm) {
        if (scalesRequest && scalesRequest.width === view.width_mm) return;
        const request = scalesRequest = {width: view.width_mm};
        const width = request.width;
        emptySlots(slots, 'Loading scales for the work width…');
        scaleListHost.hidden = true;
        fill(scaleStatus, h('p', {class: 'small muted', role: 'status'}, 'Loading measured scales…'));
        get(`/grey-scales?row_mm=${width}`).then((next) => {
          if (scalesRequest !== request || view.width_mm !== width) return;
          scalesRequest = null;
          scalesWidth = width;
          scales = next.scales;
          if (!list && scales.length) {
            current = chosen();
            list = scaleList('ge.work.scales', scales, () => current, (item) => pick(item),
              (sc) => sc === current && selectedDetail ? {...sc, ...selectedDetail} : sc);
          } else if (list) list.setScales(scales);
          fill(scaleHeading, `Work scales (${scales.length} measured)`);
          fill(scaleStatus, scales.length ? null : h('p', {class: 'muted small'}, 'No measured scales are available. Engrave a grayscale plate and add its photograph.'));
          if (scales.length) { if (list.el.parentNode !== scaleListHost) fill(scaleListHost, list.el); scaleListHost.hidden = false; }
          showScale();
        }).catch((e) => {
          if (scalesRequest === request) {
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
      engraved.load(view);
      const dot = dotted(view) && view.dot_power != null ? {power: view.dot_power, changed: (p) => save({dot_power: p}),
        recipe: fromMap(view) ? view.dot_recipe : null, hex: view.picture && view.picture.dots ? view.picture.dots.hex : null, dpi: view.dpi,
        map: () => go(DotPick.address(view))} : null;
      if (sc) detail = scaleDetail(sc, slots, {initial: [view.min_power, view.max_power], changed: (lo, hi) => save({min_power: lo, max_power: hi}), rowMm: view.width_mm, dot,
        loaded: (data) => { selectedDetail = data; cards(chosen()); }});
      else { detail = null; emptySlots(slots, 'This work’s scale has not been measured; select a scale on the left.'); }
    }
    function shown() {
      head.update(view);
      banner.update(view);
      lettering.update(view);
      const typed = drawn();
      picture.show(typed, chosen());
      dotWidth.show(typed);
      colour.show(typed);
      ai.show(typed);
      if (scaleKey(view) !== shownKey) showScale();
    }
    /** One change of the work (``path`` with ``body``): sent after those before it; the answer to the last one is shown. With ``again``
        the scale is shown anew from the answer (an undo or redo can bring back other Min and Max on the same scale). ``unsaved`` is the
        change as fields of the work (absolute values: it can be sent again); without it the change cannot be repeated (an undo, a text).
        The promise gives the error of this change, or null. */
    function send(path, body, again = false, unsaved = null) {
      error.hidden = true;
      picture.waiting();
      return doc.edit({path, body}, {local: unsaved, calculates: true, retryable: !!unsaved, meta: {again}});
    }
    function save(changes) { return send(`/photo-works/${id}/settings`, changes, false, changes); }
    /** Undo or redo the latest work change. */
    function step(kind) { return (view[kind] || 0) > 0 ? send(`/photo-works/${id}/${kind}`, {}, true) : Promise.resolve(null); }
    /** Selecting another scale preserves the image and uses its measured Min and Max. */
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
      if (document.querySelector('.modal-bg')) return;
      if (ev.key === 'Escape' && tab === 'texts' && lettering.escape()) return;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '') || t.isContentEditable)) return;   // input fields handle their own keys
      const z = ev.code === 'KeyZ' || (ev.key || '').toLowerCase() === 'z', y = ev.code === 'KeyY' || (ev.key || '').toLowerCase() === 'y';
      if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (z || y)) { ev.preventDefault(); step(z && !ev.shiftKey ? 'undo' : 'redo'); }
    };
    keys = key;
    return fill(root, head.el, banner.el, h('div', {class: 'os-body ge-body'},
      h('div', {class: 'os-col'}, h('div', {class: 'os-col-head'}, scaleHeading), scaleArea),
      h('div', {class: 'os-col ge-centre'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Image on scale'), slots.title),
        h('div', {class: 'ge-work'}, picture.inputs, picture.tone, PhotoPanels.calibrationControls(slots.powers, dotWidth.el), doc.view.el, slots.error, error, slots.bar, picture.out, picture.comparison, picture.foot)),
      h('div', {class: 'os-col ge-right'}, tabs.list, h('div', {class: 'os-scroll'}, tabs.panels))));
  }

  // ---- список работ, новая работа, шкалы серого ----------------------------------------------------------------------------------------

  /** «Новая работа» in two steps of one dialog. Step 1: the picture, the name and the width on titanium; «Дальше» makes the work on ``scale``
      (from the scales page) or the best measured scale, Min and Max its measured span. Step 2: «Какая гравировка?» with the picture in each
      kind, grayscale chosen; a click on a tile chooses its kind and «Создать» keeps the work in it and opens the work. Leaving step 2 any
      other way («Назад», ×, Escape, a click outside) deletes the work step 1 made; «Назад» returns to step 1 with its fields as they were. */
  async function newWork(scale) {
    // ux-work-creation-p0: with nothing measured to make a work on, the creation screen says what is missing and offers the starter test
    if (!scale && await App.handOverToCreation('photo')) return;
    const begun = scale ? {context: null} : await App.contextStart({});       // the laser, lens and titanium new work starts from; null when it cannot be read
    const fileIn = h('input', {type: 'file', accept: PICTURES, 'aria-label': 'Картинка'});
    const name = h('input', {autocomplete: 'off', 'aria-label': 'Название работы', placeholder: 'по имени файла'});
    // the width is read strictly with the server's own rule; a wrong one is marked beside its box and stays as typed (ux-save-feedback-p0, REQ-003)
    const picture = Forms.create();
    const widthField = picture.add('width_mm', 'Ширина на титане', Forms.numberInput(Forms.QUANTITIES.pictureWidth, {value: '50'}), {quantity: 'pictureWidth', required: true});
    fileIn.addEventListener('change', () => {
      const file = fileIn.files && fileIn.files[0];
      if (file && !name.value.trim()) name.value = file.name.replace(/\.[^.]+$/, '');
    });
    // feature electron, REQ-085: the scales may come from a connected laboratory release; the own measurements are the default and a laboratory is
    // never chosen for the operator. With a release the own laser and lens the work is engraved with are asked, and the release's scale chosen.
    const source = LabSource.picker('photo', {onChange: switchSource});
    const own = h('div', {class: 'stack', hidden: true});
    const scaleSelect = h('select', {'aria-label': 'Шкала выпуска'});
    let pick = null, releaseScales = [];
    async function switchSource(src) {
      own.hidden = !src;
      if (shared) shared.hidden = !!src;
      releaseScales = [];
      if (!src) return;
      try {
        if (!pick) {
          pick = App.laserLensPicker(await App.hardwareLists());
          fill(own, h('div', {class: 'grid g2'}, field('Свой лазер', pick.laser, 'на нём гравируется работа'), field('Своя линза', pick.lens),
            field('Шкала выпуска', scaleSelect, 'первая — лучшая измеренная')));
        }
        const asked = JSON.stringify(src);
        const offered = await post('/labs/scales', src);
        if (asked !== JSON.stringify(source.value())) return;      // the source changed meanwhile
        releaseScales = offered.scales || [];
        fill(scaleSelect, releaseScales.map((sc, i) => h('option', {value: String(i)}, settingsText(sc.mode, sc.dpi) + (sc.span ? ` · ${value(sc.span[0], 1)}–${value(sc.span[1], 1)} %` : ''))));
        scaleSelect.disabled = !releaseScales.length;
        if (!releaseScales.length) fill(scaleSelect, h('option', {value: ''}, 'выпуск не измерил шкал серого с этой установкой'));
      } catch (e) { fail(e); }
    }
    // the work is made on the best scale of the shared laser, lens and titanium (REQ-001): they are shown here and a laboratory release below replaces them
    // «Изменить…» opens the dialog of the creation screen (what the change makes unavailable is shown before «Применить»); the source is chosen below
    const sharedStrip = begun.context && begun.context.device_id != null && begun.context.material_id != null
      ? WorkContext.strip(begun.context, {heading: 'Работа делается на', source: false, onChange: (saved) => { begun.context = saved; }}) : null;
    const shared = sharedStrip ? sharedStrip.el : null;
    const fields = h('div', {class: 'stack'}, App.filePick(fileIn, 'Выбрать картинку'), field('Название', name), widthField, shared, source.el, own,
      h('p', {class: 'small muted'}, (scale ? `Шкала: ${settingsText(scale)}. Min и Max — её измеренный диапазон; шкалу, Min, Max, ширину и подбор серых можно поменять в работе.`
        : 'Шкала — лучшая из измеренных, Min и Max — её измеренный диапазон; шкалу, Min, Max, ширину и подбор серых можно поменять в работе.')
        + ' Шаг 2 — какая гравировка: ваша картинка в каждом виде.'), picture.error);
    const pictureStep = () => modal('Новая работа · шаг 1 из 2: картинка', fields, [
      {label: 'Отмена', run: (m) => m.close()},
      {label: 'Дальше →', cls: 'primary', run: async (m) => {
        const values = picture.collect();
        if (!values) return;                       // the wrong box is marked beside itself; the dialog stays with everything typed
        const file = fileIn.files && fileIn.files[0];
        if (!file) { picture.fail(new Error('Выберите картинку (PNG, JPEG, TIFF)')); return; }
        let made, src;
        try {
          const fd = new FormData();
          fd.append('picture', file, file.name);
          fd.append('name', name.value);
          fd.append('width_mm', String(values.width_mm));
          src = source.value();
          if (src) {
            fd.append('source', JSON.stringify({...src, device_id: pick.deviceId(), lens_id: pick.lensId()}));
            const sc = releaseScales[+scaleSelect.value];
            if (sc) fd.append('scale', JSON.stringify(sc.mode));
          } else if (scale) fd.append('scale', JSON.stringify(scale));
          else if (shared) {
            // the work is made on a scale of the laser, lens and titanium shown above, never silently on another laser's
            const own = await App.contextScale(begun.context, values.width_mm);
            if (!own) throw new Error('Для выбранных лазера, линзы и титана нет измеренной шкалы серого: выберите другие кнопкой «Изменить…» или добавьте тест в мастере создания работы');
            fd.append('scale', JSON.stringify(own));
          }
          made = await form('/photo-works', fd);
        } catch (e) { picture.fail(e); return; }   // said in the dialog, beside the box the server names or above the buttons
        if (src && begun.context && begun.context.material_id != null) App.rememberContext({device: pick.deviceId(), lens: pick.lensId(), material: begun.context.material_id, source: src});
        m.close();
        kindStep(made.id);
      }}]);
    // step 2 is shared with the creation screen (PhotoKindStep): the question and the rule that leaving it deletes the work are written once
    const kindStep = (id) => PhotoKindStep.open(id, {onKept: () => go(`/photo-engraving?work=${id}`), onLeft: ({back}) => { if (back) pictureStep(); }});
    pictureStep();
  }

  const plateButton = (devices, cls) => btn('Пластина «Шкалы серого»', () => PlateDialog.open(devices, null, null, {type: 'grey_scales'}), cls,
    !devices.some((d) => d.lens));

  function workCard(w) {
    const open = () => go('/photo-engraving?work=' + w.id);
    const copy = btn('Сделать копию', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { const made = await post(`/photo-works/${w.id}/copy`, {}); toast('Копия создана и открыта: старая работа осталась как была', 'ok'); go('/photo-engraving?work=' + made.id); }
      catch (e) { fail(e); self.disabled = false; }
    }, 'btn-small');
    const remove = btn('Удалить', () => confirmBox(`Удалить работу «${w.name}»?`,
      'Исчезнут картинка и настройки работы; вернуть работу будет нельзя. Чтобы сохранить её, сначала нажмите «Сделать копию».',
      'Удалить', async () => { await del('/plans/' + w.id); toast('Работа удалена', 'ok'); App.render(); }), 'danger btn-small');
    const thumb = h('a', {class: 'vw-thumb', href: '#/photo-engraving?work=' + w.id, 'aria-label': 'Открыть работу ' + w.name},
      h('img', {src: `/api/photo-works/${w.id}/thumb.png?v=${encodeURIComponent(w.updated_at)}`, alt: '', loading: 'lazy'}));
    const title = h('h3', {}, w.name);
    const pencil = VectorWorkspace.renameButton(w.id, w.name, (stored) => { w.name = stored; fill(title, stored); thumb.setAttribute('aria-label', 'Открыть работу ' + stored); }, '/photo-works');
    return h('article', {class: 'card vw-work-card'}, thumb,
      h('div', {class: 'stack vw-work-info'}, h('div', {class: 'vw-name-row'}, title, pencil),
        h('p', {class: 'small'}, `${value(w.width_mm, 1)} × ${value(w.height_mm, 1)} мм · картинка ${w.image_size[0]} × ${w.image_size[1]} пикс.`),
        h('p', {class: 'small'}, settingsText(firedSettings(w), w.dpi)),
        dotted(w) ? h('p', {class: 'small'}, `${materialLabel(w.material)} · ${kindName(w.kind)} · `
          + (fromMap(w) ? `точки ${value(w.dot_recipe.settings.power, 1)} % ${PhotoQuality.recipeFrom(w.dot_recipe)}` : `точки ${value(w.dot_power, 1)} % (оценка по шкале)`))
          : h('p', {class: 'small'}, `${materialLabel(w.material)} · Min ${value(w.min_power, 1)} % · Max ${value(w.max_power, 1)} %${w.by_colour ? ` · серые подобраны под цвета: ${w.colour_choice === 'nearest' ? 'ближайший цвет' : w.colour_choice === 'objects' ? 'раскраска по объектам' : 'рисунок сохранён'}` : ''}`
            + (w.rules && w.rules.length ? ` · правил для частей: ${w.rules.length}` : '')),
        h('p', {class: 'small'}, `Гравировка ≈ ${duration(w.time.seconds)}`),
        h('p', {class: 'small muted'}, `изменена ${when(w.updated_at)}`),
        h('div', {class: 'row'}, btn('Открыть', open, 'primary btn-small'), copy, remove)));
  }

  /** «Мои работы»: сохранённые работы и «Новая работа»; оттуда же — шкалы серого и пластина для их измерения. */
  async function listScreen() {
    const [works, devices] = await Promise.all([get('/photo-works'), get('/devices')]);
    const create = () => btn('Новая работа', () => newWork(null), 'primary');
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Фотогравировка'),
        h('p', {class: 'sub'}, 'Мои работы: картинка в режиме градаций серого на измеренной шкале — какой она выйдет на титане, сколько гравируется, файл LightBurn. '
          + 'Хранятся на этом компьютере. Откройте работу, чтобы продолжить, или сделайте копию, чтобы переделать, не потеряв прежнюю.')),
        h('span', {class: 'spacer'}), h('a', {class: 'btn', href: '#/photo-engraving?scales=1'}, 'Шкалы серого'), plateButton(devices, ''), create()),
      h('p', {class: 'small muted'}, 'Другие виды: ', link('/photo-preview', 'прогноз по файлу LightBurn'), ' · ', link('/photo', 'непрерывная полосами'), '.'),
      works.length ? h('div', {class: 'vw-works'}, works.map(workCard))
        : h('div', {class: 'card empty'}, h('h3', {}, 'Работ пока нет'),
          h('p', {class: 'muted'}, 'Выберите картинку, её ширину на титане и название: работа покажет картинку рядом с прогнозом на лучшей измеренной шкале. '
            + 'Если шкал ещё нет, сначала выгравируйте пластину «Шкалы серого» и добавьте её фотографию в «Эксперименты».'), create()));
  }

  function kindsBlock() {
    const rows = Object.entries(PhotoModes.MODES).map(([key, m]) => h('li', {class: 'ge-entry'},
      h('div', {class: 'ge-entry-head'}, h('strong', {}, m.label),
        key === 'grayscale' ? pill('здесь: по шкалам «серый → цвет»', 'ok') : m.family === 'depth' ? h('span', {class: 'muted small'}, PhotoModes.PREDICT[m.predict])
          : pill('в работе — оценка по шкале: точка цвета шкалы при своей мощности', 'warn')),
      h('div', {class: 'small'}, h('span', {class: 'muted'}, 'Серый задаёт: '), PhotoModes.FAMILY[m.family]),
      h('div', {class: 'small'}, h('span', {class: 'muted'}, 'Важно в настройках: '), m.settings)));
    return h('div', {class: 'stack'}, h('p', {class: 'small'}, ABOUT), h('h4', {}, 'Виды фотогравировки LightBurn и что здесь предсказывается'),
      h('ul', {class: 'ge-entries'}, rows),
      h('p', {class: 'small muted'}, 'Шаг строк: в градациях серого он один на всю картинку (dpi = 25,4 / шаг). Слишком частые строки, как у цветных заливок, перегревают металл, '
        + 'и серый перестаёт давать разные цвета; пластина «Шкалы серого» по умолчанию сравнивает 2000, 1500, 1200 и 1000 dpi (0,0127–0,0254 мм).'));
  }

  const ABOUT = 'Режим градаций серого: все настройки постоянны, кроме мощности. Серый картинки задаёт мощность от Min до Max, а мощность на титане даёт цвет — '
    + 'поэтому одна серая картинка выходит несколькими цветами. Шкала показывает, какой серый каким цветом выходит при ваших настройках, по вашим измерениям.';

  /** «Шкалы серого» на один экран: шкалы слева, Min, Max, полоса и таблица серых посередине, подтверждение, точки и виды справа. */
  async function scalesScreen(wanted) {
    const [{scales}, devices] = await Promise.all([get('/grey-scales'), get('/devices')]);
    let current = null, detail = null, selectedDetail = null;
    const create = btn('Новая работа на этой шкале', () => newWork(current.mode), 'primary btn-small');
    const head = h('div', {class: 'os-head'}, h('a', {class: 'btn btn-small', href: '#/photo-engraving'}, '← Мои работы'),
      h('div', {class: 'ge-title'}, h('h2', {}, 'Шкалы серого'), h('p', {class: 'sub'}, ABOUT)), plateButton(devices, 'btn-small'),
      scales.length ? create : null);
    if (!scales.length) {
      return h('div', {class: 'os ge'}, head, h('div', {class: 'os-body ge-empty'},
        h('div', {class: 'os-col'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Шкал пока нет')),
          h('div', {class: 'os-scroll stack'}, h('p', {}, 'Шкала появляется, когда принята фотография гравировки в режиме градаций серого: пластины «Шкалы серого» '
            + 'или вашей фотогравировки (слой-изображение в файле LightBurn).'), kindsBlock()))));
    }
    const slots = newSlots();
    const tabs = App.tabs([['confirm', 'Подтверждение', slots.confirm], ['points', 'Точки', slots.points], ['kinds', 'Виды', kindsBlock()]],
      {initial: 'confirm', remember: 'ge.tab', label: 'Шкала', prefix: 'ge-tab'});
    current = scales.find((sc) => modeQuery(sc.mode) === wanted) || scales[0];
    const list = scaleList('ge.scales', scales, () => current, (sc) => choose(sc),
      (sc) => sc === current && selectedDetail ? {...sc, ...selectedDetail} : sc);
    const choose = (sc) => {
      if (detail) detail.stop();
      current = sc;
      selectedDetail = null;
      list.refresh();
      detail = scaleDetail(sc, slots, {loaded: (data) => { selectedDetail = data; list.refresh(); }});
    };
    choose(current);
    return h('div', {class: 'os ge'}, head, h('div', {class: 'os-body ge-body'},
      h('div', {class: 'os-col'}, h('div', {class: 'os-col-head'}, h('h3', {}, `Измеренные шкалы (${scales.length})`)), h('div', {class: 'os-scroll'}, list.el)),
      h('div', {class: 'os-col ge-centre'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Серый → цвет'), slots.title),
        h('div', {class: 'ge-work'}, slots.powers, slots.error, slots.bar, h('div', {class: 'ge-table'}, slots.scale))),
      h('div', {class: 'os-col ge-right'}, tabs.list, h('div', {class: 'os-scroll'}, tabs.panels))));
  }

  App.register({id: 'photo-engraving', async render(ctx) {
    if (ctx.query.work) return workScreen(encodeURIComponent(ctx.query.work));
    if (ctx.query.scales || ctx.query.scale) return scalesScreen(ctx.query.scale);
    return listScreen();
  }});
})();
