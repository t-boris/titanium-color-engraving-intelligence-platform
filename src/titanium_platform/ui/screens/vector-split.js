/* Image splitting, algorithm choice, and editable important regions in a vector work. */
/* vector-detail-and-colour-control: the density is a slider beside the number of regions it would give, counted by the server before the
   split (I-2, its DEC-093). An eye, the lips and a marked area have a detail of their own, a marked area its kind (eye, lips, other), and
   any area's boundary can be moved or drawn again (I-3, its DEC-094); when only the detail, boundary or kind of areas changed, the colours
   outside the changed areas stay as they were after «Split again». */
'use strict';
const VectorSplit = (() => {
  const {h, fill, btn, field, post, toast, confirmBox} = App;
  const NS = 'http://www.w3.org/2000/svg';
  const DENSITY = {min: 30, max: 250, step: 5};                     // vector_job.DENSITY
  const LEVELS = {coarse: 70, medium: 100, fine: 150};                // the former levels of detail, points of the same scale
  const KIND = {face: 'Face', eye: 'Eye', lips: 'Lips', manual: 'Marked manually'};
  const FINE = ['eye', 'lips', 'manual'];                                            // faces.FINE_KINDS: these have a detail of their own
  const DETAILS = [['fine', 'fine'], ['finer', 'very fine'], ['finest', 'maximum'], ['face', 'same as face']];   // faces.DETAILS
  const MARKED = [['eye', 'eye'], ['lips', 'lips'], ['manual', 'other']];           // vector_job.MARKED_KINDS
  /** Splitting algorithms, their visual tradeoffs, and approximate processing time. */
  const ALGORITHMS = [
    ['slic', 'Mosaic', 'General-purpose default. Divides the image into even regions of similar size, preserving faces and soft transitions with smooth boundaries. About 1.5 seconds for a 1200-pixel portrait.'],
    ['tonal', 'By tone', 'Regions follow light and shadow; eyebrows, lips, highlights, and folds become separate patches rather than a grid. Most detailed in tonal shading. About 3 seconds for a 1200-pixel portrait.'],
    ['planes', 'Large planes', 'Large uniform planes and strips along lines, without fixed-size regions. About 40% fewer regions than Mosaic: simpler artwork with fewer subtle tonal transitions. Faces, eyes, and lips retain smaller regions.'],
    ['seeds', 'SEEDS', 'Similar even regions to Mosaic but faster (about one second) and slightly fewer regions. Preserves fine lines and text, especially in noisy or unevenly lit images. Portrait boundaries are slightly rougher and color error slightly higher.']];
  const RESET = 'Regions will be found again and coloring will restart: manually selected colors, coloring variants, and undo history for this split '
    + 'will be lost. Lettering and photo zones move to the new split. Previous LightBurn files and engraving results remain.';
  const algorithmName = (v) => (ALGORITHMS.find(([id]) => id === v) || ALGORITHMS[0])[1];

  /** Describe the selected algorithm. */
  function picker(current) {
    const select = h('select', {'aria-label': 'Splitting algorithm'}, ALGORITHMS.map(([v, name]) => h('option', {value: v, selected: v === current}, name)));
    const hint = h('p', {class: 'toolbar-hint'});
    const explain = () => fill(hint, h('strong', {}, algorithmName(select.value) + ': '), (ALGORITHMS.find(([id]) => id === select.value) || ALGORITHMS[0])[2]);
    select.addEventListener('change', explain);
    explain();
    return {select, hint};
  }
  /** Redraw boundaries immediately; coalesce intermediate smoothing requests. */
  function smoothness(j, apply) {
    const rule = {...Forms.QUANTITIES.smoothing, max: j.smoothing_max_mm || Forms.QUANTITIES.smoothing.max};       // the end is the work's own (vector_job.SMOOTHING_MAX_MM)
    const input = h('input', {type: 'range', min: '0', max: String(rule.max), step: '0.05', value: String(j.smoothing_mm || 0), 'aria-label': 'Line smoothing, mm'});
    const say = (v) => (+v === 0 ? 'as detected' : `${App.num(+v, 2)} mm`);
    const readout = h('output', {class: 'vw-slider-value'}, say(input.value));
    // a refusal of the server is told under the slider; the slider stays where it was put, the drawing is as it was
    const place = Forms.notice({what: 'Smoothing', kept: 'Boundaries remain unchanged; the slider keeps your position.'});
    let sent = +input.value, busy = false, timer = null;
    async function pump() {
      if (busy) return;
      busy = true;
      try {
        while (+input.value !== sent) { sent = +input.value; place.clear(); await apply(sent, place); }
      } catch (e) { place.fail(e); sent = +input.value; } finally { busy = false; }
    }
    input.addEventListener('input', () => { readout.textContent = say(input.value); clearTimeout(timer); timer = setTimeout(pump, 120); });
    return h('div', {}, h('div', {class: 'vw-slider'}, input, readout, Forms.describe(input, rule)), place.error);
  }
  /** The density (I-2): how many coarse superpixels lie along the picture's longer side, apart from the number of colours. The server counts
      the regions it would give with the same settings, the work unchanged (``count``); one request at a time, for the last position. */
  function densityControl(j, settings) {
    const s = j.split, start = s.density || LEVELS[s.detail] || LEVELS.medium;
    const input = h('input', {type: 'range', min: String(DENSITY.min), max: String(DENSITY.max), step: String(DENSITY.step), value: String(start),
      'aria-label': 'Region density'});
    const readout = h('output', {class: 'vw-slider-value'}, String(start));
    const count = h('p', {class: 'small vw-density-count'}, `current regions: ${j.document.regions}`);
    // the server counts the regions of the settings before the split; a refusal of that count is told under the slider (the count shown is the work's own)
    const place = Forms.notice({what: 'Region count', kept: 'The current region count is shown.'});
    let asked = null, busy = false, timer = null;
    async function pump() {
      if (busy) return;
      busy = true;
      try {
        while (JSON.stringify(settings()) !== asked) {
          place.clear();
          if (settings().n_colors == null) { fill(count, `current regions: ${j.document.regions}`); return; }          // the colours are wrong: the box says so, nothing is asked
          asked = JSON.stringify(settings());
          fill(count, 'Counting resulting regions…');
          const r = await post(`/vector/${j.id}/split/preview`, settings());
          if (JSON.stringify(settings()) === asked) fill(count, `resulting regions: ${r.regions} (currently ${j.document.regions}) · smallest ${App.num(r.min_area_mm2, 2)} mm²`);
        }
      } catch (e) { place.fail(e); fill(count, `current regions: ${j.document.regions}`); asked = null; } finally { busy = false; }
    }
    const recount = () => { clearTimeout(timer); timer = setTimeout(pump, 400); };
    input.addEventListener('input', () => { readout.textContent = input.value; recount(); });
    return {input, count, recount, el: h('div', {}, h('div', {class: 'vw-slider'}, input, readout, Forms.describe(input, 'density')), place.error)};
  }
  const svgEl = (tag, attrs) => {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  };

  /** An area's boundary alone: an ellipse or a polygon. */
  const outline = (a) => (a.ellipse ? {ellipse: a.ellipse} : {polygon: a.polygon});
  /** An area moved by (dx, dy) pixels. */
  function moved(a, dx, dy) {
    if (a.ellipse) return {ellipse: {...a.ellipse, center: [a.ellipse.center[0] + dx, a.ellipse.center[1] + dy]}};
    return {polygon: a.polygon.map(([x, y]) => [x + dx, y + dy])};
  }
  /** Whether a point lies inside an area (a turned ellipse or a polygon). */
  function inside(a, [x, y]) {
    if (a.ellipse) {
      const e = a.ellipse, t = -(e.angle || 0) * Math.PI / 180, dx = x - e.center[0], dy = y - e.center[1];
      const u = dx * Math.cos(t) - dy * Math.sin(t), v = dx * Math.sin(t) + dy * Math.cos(t);
      return (u / e.axes[0]) ** 2 + (v / e.axes[1]) ** 2 <= 1;
    }
    let hit = false;
    const p = a.polygon;
    for (let i = 0, k = p.length - 1; i < p.length; k = i++) {
      if ((p[i][1] > y) !== (p[k][1] > y) && x < (p[k][0] - p[i][0]) * (y - p[i][1]) / (p[k][1] - p[i][1]) + p[i][0]) hit = !hit;
    }
    return hit;
  }
  /** A detected area's changes in one form, to compare them with the saved ones. */
  const norm = (c) => ({number: c.number, detail: c.detail || null, ellipse: c.ellipse || null, polygon: c.polygon || null});

  /** Region shape in image pixels: ellipse or polygon. */
  function shape(area, cls) {
    if (area.ellipse) {
      const e = area.ellipse;
      return svgEl('ellipse', {cx: e.center[0], cy: e.center[1], rx: e.axes[0], ry: e.axes[1], transform: `rotate(${e.angle || 0} ${e.center[0]} ${e.center[1]})`, class: cls});
    }
    return svgEl('polygon', {points: area.polygon.map((p) => p.join(',')).join(' '), class: cls});
  }

  /** Split settings and editable important regions. */
  function card(j, reload, smooth) {
    const doc = j.document, s = j.split;
    const W = doc.image_px.width, H = doc.image_px.height;
    const manual = s.manual.map((a) => ({...a}));
    const removed = new Set(s.removed);
    const adjusted = new Map((s.adjusted || []).map((c) => [c.number, {...c}]));   // detected areas with the operator's detail or boundary
    let editing = null;                                                           // the area whose boundary is edited: {found: number} or {manual: index}
    // the colours: a whole number from 2 to what the layers of the work allow (the server's rule, vector_job._split_settings); a wrong number is refused
    // beside the box, stays in it, and no count of regions is asked for it
    const coloursRule = {...Forms.QUANTITIES.photoColours, max: j.layer_cap};
    const colours = Forms.numberInput(coloursRule, {value: s.n_colors});
    const splitForm = Forms.create();
    const coloursField = splitForm.add('colours', 'Number of colors', colours, {quantity: coloursRule, required: true,
      help: 'cleaning is the first layer' + (j.markers_enabled ? ', markers use another layer' : '')});
    const algorithm = picker(s.algorithm || 'slic');
    const settings = () => ({n_colors: Forms.parse(colours.value, coloursRule, {required: true}).value ?? null, algorithm: algorithm.select.value, density: +density.input.value, faces: faces.checked,
      manual, removed: [...removed], adjusted: [...adjusted.values()].sort((a, b) => a.number - b.number)});
    /** A detected area as the split will use it: with the operator's detail and boundary. */
    const effective = (a) => {
      const c = adjusted.get(a.number) || {};
      return {...a, ...(c.ellipse || c.polygon ? {ellipse: undefined, polygon: undefined, ...outline(c)} : {}), detail: c.detail};
    };
    const adjust = (number, change) => {
      const c = {number, ...(adjusted.get(number) || {}), ...change};
      if (!c.detail || c.detail === 'fine') delete c.detail;
      if (c.detail || c.ellipse || c.polygon) adjusted.set(number, c); else adjusted.delete(number);
    };
    const edited = () => (editing == null ? null : 'found' in editing ? effective(j.areas.detected[editing.found]) : manual[editing.manual]);
    const reshape = (area) => {
      if ('found' in editing) adjust(editing.found, {ellipse: undefined, polygon: undefined, ...area});
      else manual[editing.manual] = {...manual[editing.manual], ellipse: undefined, polygon: undefined, ...area};
      for (const a of [adjusted.get(editing.found), manual[editing.manual]]) {
        if (a) for (const k of ['ellipse', 'polygon']) if (a[k] === undefined) delete a[k];
      }
    };
    const density = densityControl(j, settings);
    const smoothing = smoothness(j, smooth || (async () => {}));
    const faces = h('input', {type: 'checkbox', checked: s.faces});
    const tool = h('select', {'aria-label': 'New region shape'}, h('option', {value: 'rect'}, 'Rectangle'), h('option', {value: 'ellipse'}, 'Ellipse'));
    const overlay = svgEl('svg', {viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', class: 'vw-areas', role: 'img',
      'aria-label': 'Important regions over the image; drag to mark your own'});
    const list = h('div', {class: 'stack'});
    // the same areas by numbers (ux-accessible-layout-p0, REQ-001): a drag on the picture is not the only way to mark an area or to
    // reshape one; the frame is given in percent of the picture and becomes a rectangle or an ellipse as the shape list says
    const FRAME = [['left', 'Left, %', 25, 0], ['top', 'Top, %', 25, 0], ['width', 'Width, %', 50, 0.1], ['height', 'Height, %', 50, 0.1]];
    const frame = Object.fromEntries(FRAME.map(([key, label, value]) => [key, h('input', {type: 'number', step: '0.1', min: '0', max: '100', value: String(value), 'aria-label': `Region: ${label}`})]));
    // each of the four says beside itself what is wrong with it (the frame must lie inside the picture); what was typed stays
    const frameFields = Object.fromEntries(FRAME.map(([key, label]) => [key, App.field(label, frame[key], null, {required: true, constraint: key === 'left' || key === 'top' ? 'from 0 to 100' : 'greater than 0, at most 100'})]));
    for (const key of Object.keys(frame)) frame[key].addEventListener('input', () => frameFields[key].clearError());
    const numNote = h('p', {class: 'small vw-area-note', role: 'status', 'aria-live': 'polite'});
    const numActs = h('div', {class: 'row'});
    const applyBtn = btn('Add region by coordinates', applyFrame, 'primary');            // never replaced: a replaced button drops the keyboard
    numActs.append(applyBtn);
    let nudges = [];                                                                  // the four move buttons, there while a boundary is being edited
    const makeNudges = () => [['←', 'left', -1, 0], ['→', 'right', 1, 0], ['↑', 'up', 0, -1], ['↓', 'down', 0, 1]].map(([sign, word, dx, dy]) => {
      const b = btn(sign, () => nudge(dx, dy), 'btn-small');
      b.setAttribute('aria-label', `Move boundary ${word} by 1%`);
      return b;
    });
    const pending = h('p', {class: 'muted small', hidden: true}, 'Region changes apply after Split again.');
    const editHint = h('p', {class: 'small', hidden: true});
    const areasTitle = h('summary', {});
    let areasKey = null;                                               // the areas as last drawn: a change of them recounts the regions

    /** An area's detail, one of four; a face has none of its own. */
    const detailPicker = (value, set, name, which) => {
      const select = h('select', {'aria-label': `Region detail: ${which}`}, DETAILS.map(([v, l]) => h('option', {value: v, selected: v === (value || 'fine')}, l)));
      select.addEventListener('change', () => { set(select.value); draw(); });
      return mark(select, `${name}:detail`);
    };
    const isEditing = (which) => editing != null && JSON.stringify(editing) === JSON.stringify(which);
    const borderButton = (which) => mark(btn(isEditing(which) ? 'Done' : 'Boundary', () => { editing = isEditing(which) ? null : which; draw(); }),
      'found' in which ? `found${which.found}:border` : `manual${which.manual}:border`);
    /** A control of the list of areas, named so that the list drawn again puts the keyboard back on the same control. */
    const mark = (el, name) => { el.setAttribute('data-focus', name); return el; };
    /** ``rebuild()`` draws the list again; the keyboard stays on the control it was on (or on the add button when that control is gone). */
    function keepFocus(rebuild) {
      const was = typeof document !== 'undefined' ? document.activeElement : null;
      const name = was && was.getAttribute && list.contains(was) ? was.getAttribute('data-focus') : null;
      rebuild();
      if (!name) return;
      const again = [...list.querySelectorAll('[data-focus]')].find((e) => e.getAttribute('data-focus') === name);
      (again || applyBtn).focus();
    }

    /** The frame the four fields describe as an area in pixels of the picture, or the reason it cannot be one. */
    function framed() {
      for (const f of Object.values(frameFields)) f.clearError();
      const [l, t, w, hh] = ['left', 'top', 'width', 'height'].map((k) => parseFloat(frame[k].value));
      const single = {left: l >= 0 && l <= 100, top: t >= 0 && t <= 100, width: w > 0 && w <= 100, height: hh > 0 && hh <= 100};
      const wrong = Object.keys(frame).filter((k) => !Number.isFinite(parseFloat(frame[k].value)) || !single[k]);
      if (wrong.length) {
        for (const k of wrong) frameFields[k].setError(Number.isFinite(parseFloat(frame[k].value)) ? `Allowed: ${k === 'left' || k === 'top' ? 'from 0 to 100' : 'greater than 0, at most 100'} %. Entered: ${frame[k].value}` : 'Enter a number, %');
        frameFields[wrong[0]].firstControl().focus();
        return {error: 'Enter all four region bounds: left and top from 0 to 100; width and height greater than 0 and at most 100%.'};
      }
      if (l + w > 100.0001 || t + hh > 100.0001) {
        for (const k of l + w > 100.0001 ? ['left', 'width'] : ['top', 'height']) frameFields[k].setError('The bounds extend beyond the image: left plus width and top plus height must not exceed 100%.');
        return {error: 'The bounds must lie inside the image: left and top at least 0, width and height above 0, and each position plus size at most 100%.'};
      }
      const area = areaOf([l * W / 100, t * H / 100], [(l + w) * W / 100, (t + hh) * H / 100]);
      return area ? {area} : {error: 'The bounds are too small: each side must be at least 2 image pixels.'};
    }
    /** The frame fields take the box of the area being edited, so the numbers start from what is there. */
    function frameOf(area) {
      const xs = area.ellipse ? [area.ellipse.center[0] - area.ellipse.axes[0], area.ellipse.center[0] + area.ellipse.axes[0]] : area.polygon.map((p) => p[0]);
      const ys = area.ellipse ? [area.ellipse.center[1] - area.ellipse.axes[1], area.ellipse.center[1] + area.ellipse.axes[1]] : area.polygon.map((p) => p[1]);
      const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
      const pct = (v, whole) => String(Math.round(Math.min(100, Math.max(0, v / whole * 100)) * 10) / 10);
      frame.left.value = pct(x0, W); frame.top.value = pct(y0, H);
      frame.width.value = pct(x1 - x0, W); frame.height.value = pct(y1 - y0, H);
    }
    function applyFrame() {
      const got = framed();
      if (got.error) { fill(numNote, got.error); numNote.setAttribute('class', 'small vw-area-note alert bad'); return; }
      numNote.setAttribute('class', 'small vw-area-note');
      if (editing) { reshape(got.area); fill(numNote, 'Region boundary changed; it will apply after Split again'); }
      else { manual.push(got.area); fill(numNote, `Region added: manually marked #${manual.length}; it will apply after Split again`); }
      draw();
    }
    /** The edited area's boundary moved by one percent of the picture. */
    function nudge(dx, dy) {
      const area = edited();
      if (!area) return;
      reshape(moved(outline(area), dx * W / 100, dy * H / 100));
      fill(numNote, 'Boundary moved by 1%');
      numNote.setAttribute('class', 'small vw-area-note');
      draw();
      frameOf(edited());                                                // the fields follow the boundary
    }
    let framedFor = null;                                              // the area the fields were last filled from

    function draw() {
      const key = JSON.stringify([manual, [...removed].sort(), faces.checked, settings().adjusted]);
      if (areasKey !== null && key !== areasKey) density.recount();
      areasKey = key;
      if (editing && (('found' in editing && (!faces.checked || removed.has(editing.found))) || ('manual' in editing && !manual[editing.manual]))) editing = null;
      overlay.replaceChildren();
      j.areas.detected.forEach((a) => {
        if (!faces.checked) return;
        overlay.append(shape(effective(a), (removed.has(a.number) ? 'vw-area removed' : 'vw-area ' + a.kind) + (isEditing({found: a.number}) ? ' editing' : '')));
      });
      manual.forEach((a, i) => overlay.append(shape(a, 'vw-area manual' + (isEditing({manual: i}) ? ' editing' : ''))));
      const was = JSON.stringify((s.adjusted || []).map(norm)), now = JSON.stringify(settings().adjusted.map(norm));
      const changed = JSON.stringify(manual) !== JSON.stringify(s.manual) || removed.size !== s.removed.length
        || [...removed].some((n) => !s.removed.includes(n)) || was !== now;
      pending.hidden = !changed;
      editHint.hidden = editing == null;
      fill(editHint, 'Drag inside the selected region to move it, or beside it to redraw its boundary using the new-region shape. Select Done to finish.');
      const editedNow = edited();
      if (editedNow && JSON.stringify(editing) !== framedFor) frameOf(editedNow);              // a new area to edit: its box in the fields
      framedFor = editedNow ? JSON.stringify(editing) : null;
      fill(applyBtn, editing ? 'Set boundary by coordinates' : 'Add region by coordinates');
      if (!!editing !== nudges.length > 0) { nudges.forEach((b) => b.remove()); nudges = editing ? makeNudges() : []; numActs.append(...nudges); }
      fill(areasTitle, `Important regions: faces, eyes, lips, and manually marked (found ${faces.checked ? j.areas.detected.length : 0}, marked ${manual.length}, removed ${removed.size})`);
      const rows = (faces.checked ? j.areas.detected : []).map((a) => {
        const gone = removed.has(a.number), changedHere = adjusted.has(a.number);
        return h('div', {class: 'row'},
          h('span', {}, `${KIND[a.kind]} · found`, a.score == null ? '' : ` (score ${App.num(a.score)})`, gone ? ' · removed' : changedHere ? ' · changed' : ''),
          !gone && FINE.includes(a.kind) ? detailPicker(effective(a).detail, (v) => adjust(a.number, {detail: v}), `found${a.number}`, `${KIND[a.kind].toLowerCase()}, found`) : null,
          !gone ? borderButton({found: a.number}) : null,
          !gone && changedHere ? mark(btn('As detected', () => { adjusted.delete(a.number); draw(); }), `found${a.number}:asfound`) : null,
          gone ? mark(btn('Restore', () => { removed.delete(a.number); draw(); }), `found${a.number}:toggle`)
            : mark(btn('Remove', () => { removed.add(a.number); draw(); }), `found${a.number}:toggle`));
      });
      manual.forEach((a, i) => {
        const kind = h('select', {'aria-label': `Region type: manually marked #${i + 1}`}, MARKED.map(([v, l]) => h('option', {value: v, selected: v === (a.kind || 'manual')}, l)));
        kind.addEventListener('change', () => { manual[i] = {...manual[i], kind: kind.value}; draw(); });
        mark(kind, `manual${i}:kind`);
        rows.push(h('div', {class: 'row'}, h('span', {}, `Marked manually #${i + 1}`), kind,
          detailPicker(a.detail, (v) => { manual[i] = {...manual[i], detail: v === 'fine' ? undefined : v}; if (!manual[i].detail) delete manual[i].detail; }, `manual${i}`, `marked manually #${i + 1}`),
          borderButton({manual: i}),
          mark(btn('Remove', () => { manual.splice(i, 1); if (editing && 'manual' in editing) editing = null; draw(); }), `manual${i}:toggle`)));
      });
      keepFocus(() => fill(list, rows.length ? rows : h('p', {class: 'muted small'}, 'No important regions. Drag on the image to mark one.')));
    }

    // dragging on the picture: a rectangle or an ellipse in pixels of the working picture, a new area or the edited area's new boundary;
    // dragging inside the edited area moves its boundary
    let start = null, ghost = null, grabbed = null;
    const at = (ev) => {
      const r = overlay.getBoundingClientRect();
      return [Math.min(W, Math.max(0, (ev.clientX - r.left) / r.width * W)), Math.min(H, Math.max(0, (ev.clientY - r.top) / r.height * H))];
    };
    const areaOf = (a, b) => {
      const [x0, x1] = [Math.min(a[0], b[0]), Math.max(a[0], b[0])], [y0, y1] = [Math.min(a[1], b[1]), Math.max(a[1], b[1])];
      if (x1 - x0 < 2 || y1 - y0 < 2) return null;
      return tool.value === 'ellipse' ? {ellipse: {center: [(x0 + x1) / 2, (y0 + y1) / 2], axes: [(x1 - x0) / 2, (y1 - y0) / 2], angle: 0}}
        : {polygon: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]};
    };
    const drawn = (p) => {
      if (!grabbed) return areaOf(start, p);
      const [dx, dy] = [p[0] - start[0], p[1] - start[1]];
      return dx || dy ? moved(grabbed, dx, dy) : null;
    };
    overlay.addEventListener('pointerdown', (ev) => {
      start = at(ev);
      const area = edited();
      grabbed = area && inside(area, start) ? outline(area) : null;
      overlay.setPointerCapture(ev.pointerId); ev.preventDefault();
    });
    overlay.addEventListener('pointermove', (ev) => {
      if (!start) return;
      const area = drawn(at(ev));
      if (ghost) ghost.remove();
      ghost = area ? shape(area, 'vw-area manual editing') : null;
      if (ghost) overlay.append(ghost);
    });
    overlay.addEventListener('pointerup', (ev) => {
      if (!start) return;
      const area = drawn(at(ev));
      start = null; grabbed = null;
      if (ghost) { ghost.remove(); ghost = null; }
      if (!area) return;
      if (editing) reshape(area); else manual.push(area);
      draw();
    });
    faces.addEventListener('change', draw);
    for (const el of [colours, algorithm.select]) el.addEventListener('change', () => density.recount());
    draw();

    // split again: the colouring, its variants and its undo steps start anew, so the operator is asked first (I-8)
    const run = btn('Split again', () => {
      if (!splitForm.collect()) return;                                // the wrong number says why beside its box; no question is asked about it
      confirmBox('Split the image again?', RESET, 'Split again', async () => {
        try {
          await post(`/vector/${j.id}/split`, settings());
          toast('Image split again; colors reassigned', 'ok');
          reload();
        } catch (e) { splitForm.fail(e); }
      });
    }, 'primary');
    const found = !doc.faces.searched ? 'face detection off' : j.areas.search_failed ? 'face detection failed; mark important regions manually'
      : doc.faces.found ? `faces found: ${doc.faces.found}` : 'no face found';
    return h('div', {class: 'stack vw-split'}, h('h4', {}, 'Split'),
      h('div', {class: 'vw-split-fields'}, field('Splitting algorithm', algorithm.select),
        coloursField, splitForm.error,
        field('Region density', density.el, 'lower values give fewer, larger regions; higher values give finer regions. 70, 100, and 150 match the former coarse, medium, and fine settings'),
        field('Line smoothing', smoothing, 'the slider redraws boundaries immediately; regions and colors stay the same')),
      density.count,
      h('div', {class: 'vw-split-actions'}, h('label', {class: 'row'}, faces, h('span', {}, 'Find faces (more detail for eyes and lips)')), run),
      algorithm.hint,
      h('p', {class: 'small'}, `Algorithm ${algorithmName(doc.algorithm)} · colors: ${doc.colours} · regions: ${doc.regions} · ${found}` + (doc.important_regions ? ` · regions in important areas: ${doc.important_regions}` : '')
        + ` · smallest region ${App.num(doc.min_area_mm2, 2)} mm²`),
      h('details', {class: 'vw-details vw-areas-box'}, areasTitle,
        h('div', {class: 'grid g2'},
          h('figure', {}, h('div', {class: 'vw-stage'}, h('img', {src: `/api/plans/${j.id}/source-image`, alt: 'Source image'}), overlay),
            h('figcaption', {class: 'muted small'}, 'The image is split into color regions without gaps; adjacent regions share one boundary. Faces, eyes, lips, and marked regions are split more finely. ',
              'Faces are blue, eyes and lips yellow, and manually marked regions green. Removed regions are dashed and the selected boundary is thicker. Drag to mark a region. ',
              'Eyes, lips, and marked regions have their own detail settings. If only detail, boundary, or kind changes, colors outside changed regions remain after Split again.')),
          h('div', {class: 'stack'}, field('New region', tool),
            h('div', {class: 'vw-area-num', role: 'group', 'aria-label': 'Region bounds as percentages of the image'}, Object.values(frameFields)),
            numActs, numNote, list, editHint, pending))));
  }

  return {card, ALGORITHMS, picker, name: algorithmName};
})();
