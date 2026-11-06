/* Measured titanium colors, confidence, matching, and film-model estimates. */
'use strict';
const ColorMap = (() => {
  const {h, fill, btn, field, link, pill, get, num, swatch, labText} = App;
  const SVG = 'http://www.w3.org/2000/svg';

  const hexToLab = App.hexToLab; // sRGB to D65 Lab, shared with the editor's target selector
  const settings = (p) => [p.power == null ? null : `${num(p.power, 1)}%`, p.frequency == null ? null : `${num(p.frequency, 0)} kHz`,
    p.speed == null ? null : `${num(p.speed, 0)} mm/s`, p.pulse_width == null ? 'Q-Pulse not recorded' : `${num(p.pulse_width, 0)} ns`,
    p.line_interval == null ? null : `interval ${num(p.line_interval, 4)} mm`, p.passes == null ? null : `${p.passes} passes`].filter(Boolean).join(' · ');
  const when = (iso) => (iso || '').slice(0, 10);
  // REQ-035, DEC-075: recipe engraving time is estimated from settings; the filter stores seconds and displays minutes:seconds
  const mmss = (seconds) => { const t = Math.round(seconds); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`; };
  const perArea = (s) => (s < 60 ? `${num(s, 1)} s` : `${mmss(s)} min`);
  function timeText(p) {
    const note = p.time && p.time.note ? ` · ${I18N.tr(p.time.note)}` : '';
    if (p.time_s_per_cm2 != null) return `time ≈ ${perArea(p.time_s_per_cm2)} per cm² (estimate)${note}`;
    if (p.time_s_per_cm != null) return `time ≈ ${num(p.time_s_per_cm, 2)} s per cm of line (estimate)${note}`;
    return `time cannot be estimated: ${I18N.tr((p.time && p.time.note) || '')}`;
  }
  /** Parse a time limit in minutes:seconds or decimal minutes; empty means no limit. */
  function parseLimit(text) {
    const s = String(text || '').trim().replace(',', '.');
    if (!s) return null;
    const m = s.match(/^(\d+):([0-5]?\d)$/);
    const seconds = m ? +m[1] * 60 + +m[2] : /^\d*\.?\d+$/.test(s) ? +s * 60 : NaN;
    return seconds > 0 ? seconds : NaN;
  }
  const colours = (n) => `${n} ${n === 1 ? 'color' : 'colors'}`;
  const times = (n) => `${n} ${n === 1 ? 'time' : 'times'}`;

  // the three planes of Lab: which coordinate goes right and which goes up
  const PLANES = {ab: {x: 1, y: 2, right: 'a*  red →', up: 'b*  yellow ↑', zero: true}, La: {x: 1, y: 0, right: 'a*  red →', up: 'L*  lighter ↑', zero: false},
    Lb: {x: 2, y: 0, right: 'b*  yellow →', up: 'L*  lighter ↑', zero: false}};

  /** Circle radius reflects agreement across independent engravings. */
  const RADIUS = {base: 4, step: 1.5, least: 2, most: 14};
  const radius = (p) => {
    const a = p.agreement || {};
    return Math.min(RADIUS.most, Math.max(RADIUS.least, RADIUS.base * RADIUS.step ** (Math.max(a.agreeing || 1, 1) - 1 - (a.differing || 0))));
  };

  /** The circle of a colour at the size it has on the map, beside the words that tell the confidence (REQ-049). */
  function dot(p) {
    const svg = document.createElementNS(SVG, 'svg'), c = document.createElementNS(SVG, 'circle');
    for (const [k, v] of Object.entries({viewBox: `${-RADIUS.most - 1} ${-RADIUS.most - 1} ${2 * RADIUS.most + 2} ${2 * RADIUS.most + 2}`, width: 2 * RADIUS.most + 2,
      height: 2 * RADIUS.most + 2, class: 'cm-dot', 'aria-hidden': 'true'})) svg.setAttribute(k, v);
    for (const [k, v] of Object.entries({cx: 0, cy: 0, r: radius(p), fill: swatch(p.display_lab).style.background || '#888', stroke: '#dfe7f5', 'stroke-width': 1.4})) c.setAttribute(k, v);
    svg.append(c);
    return svg;
  }
  /** How far a colour is trusted (REQ-045, REQ-049): its circle, the confidence, how many engravings agree, and the warnings. */
  function trustLine(p) {
    const a = p.agreement || {};
    return h('p', {class: 'cm-trust'}, dot(p), h('span', {}, h('strong', {}, 'Confidence: '),
      p.confidence == null ? 'not assessed; engraving not repeated' : `${num(p.confidence)} (${App.agreed(a)})`,
      p.doubtful ? ' ' : null, p.doubtful ? pill('uncertain', 'warn') : null, p.caution ? ` · ${App.CAUTION[p.caution]}` : ''));
  }
  const ONE_ENGRAVING = (p) => ({title: p.title, experiment: p.experiment, origin: p.origin, work_id: p.work_id, date: p.date, pair_ids: [p.pair_id], photos: p.photo ? [p.photo] : [],
    layers: p.layer_name ? [p.layer_name] : [], lab: p.display_lab, delta_e: 0, agrees: true, measurement: p.measurement, provisional: !!p.provisional});
  const sourcesBlock = App.sourcesBlock;             // shared with the picker of the vector work (REQ-051)

  // -- zoom and pan of the map (plain SVG, no library). A view is the scale ``s`` (1 = the whole map) and the offset of the picture in the
  // 640 x 460 frame; it is kept for each plane while the page is open, so a click on a colour or a new search does not throw it away.
  const ZOOM = {least: 1, most: 60, step: 1.5};
  const views = {};
  const clampView = (v, W, H) => {
    const s = Math.min(ZOOM.most, Math.max(ZOOM.least, v.s));
    return {s, tx: Math.min(0, Math.max(W * (1 - s), v.tx)), ty: Math.min(0, Math.max(H * (1 - s), v.ty))};
  };
  /** Scale the view by ``factor`` keeping the point (px, py) of the frame where it is. */
  const zoomView = (v, factor, px, py, W, H) => {
    const s = Math.min(ZOOM.most, Math.max(ZOOM.least, v.s * factor)), k = s / v.s;
    return clampView({s, tx: px - (px - v.tx) * k, ty: py - (py - v.ty) * k}, W, H);
  };
  const panView = (v, dx, dy, W, H) => clampView({s: v.s, tx: v.tx + dx, ty: v.ty + dy}, W, H);

  function plot(points, onPick, target, picked, plane, spiral, faint = null) {
    if (!points.length) return h('p', {class: 'muted'}, 'No colors match these conditions.');
    const P = PLANES[plane] || PLANES.ab;
    const W = 640, H = 460, pad = 34;
    const xs = points.map((p) => p.display_lab[P.x]).concat(target ? [target[P.x]] : []), ys = points.map((p) => p.display_lab[P.y]).concat(target ? [target[P.y]] : []);
    const lo = [Math.min(...xs, P.zero ? -4 : Infinity) - 4, Math.min(...ys, P.zero ? -4 : Infinity) - 4], hi = [Math.max(...xs, P.zero ? 4 : -Infinity) + 4, Math.max(...ys, P.zero ? 4 : -Infinity) + 4];
    const x = (v) => pad + ((v - lo[0]) / (hi[0] - lo[0])) * (W - 2 * pad), y = (v) => H - pad - ((v - lo[1]) / (hi[1] - lo[1])) * (H - 2 * pad);
    const svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('role', 'img'); svg.setAttribute('tabindex', '0');
    svg.setAttribute('aria-label', `Measured color map: ${P.right} and ${P.up}. Use the mouse wheel to zoom, drag or arrow keys to pan, and 0 for the full view`);
    svg.style.cssText = 'width:100%;height:100%;cursor:grab;touch-action:none;outline:none';       // the box around it sets the size; the viewBox keeps the proportions
    const g = document.createElementNS(SVG, 'g');            // everything that moves and scales with the view
    svg.append(g);
    const add = (tag, attrs, text, parent = g) => { const el = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); if (text) el.textContent = text; parent.append(el); return el; };
    const steady = [];       // sizes that stay the same on the screen however far the map is zoomed: each is told the scale
    const fixed = (cx, cy, build) => { const holder = add('g', {}); build(holder); steady.push((s) => holder.setAttribute('transform', `translate(${cx} ${cy}) scale(${1 / s})`)); return holder; };
    const thin = {'vector-effect': 'non-scaling-stroke'};
    if (P.zero) { add('line', {x1: x(lo[0]), x2: x(hi[0]), y1: y(0), y2: y(0), stroke: '#44556e', 'stroke-width': 1, ...thin});
      add('line', {x1: x(0), x2: x(0), y1: y(lo[1]), y2: y(hi[1]), stroke: '#44556e', 'stroke-width': 1, ...thin}); }
    if (spiral && spiral.length) {           // the film model: colour against the oxide thickness, drawn under the points
      const inside = (l) => l[P.x] >= lo[0] && l[P.x] <= hi[0] && l[P.y] >= lo[1] && l[P.y] <= hi[1];
      let d = '';
      spiral.forEach((s, i) => { const l = s.lab; d += (i && inside(l) && inside(spiral[i - 1].lab) ? 'L' : 'M') + `${x(l[P.x]).toFixed(1)} ${y(l[P.y]).toFixed(1)} `; });
      add('path', {d, fill: 'none', stroke: '#8fa3c4', 'stroke-width': 1.2, 'stroke-opacity': 0.7, 'stroke-dasharray': '4 3', ...thin});
      spiral.filter((s) => s.thickness_nm % 50 === 0 && inside(s.lab)).forEach((s) => fixed(x(s.lab[P.x]), y(s.lab[P.y]), (holder) => {
        add('circle', {cx: 0, cy: 0, r: 2.5, fill: '#8fa3c4'}, null, holder);
        add('text', {x: 5, y: -4, fill: '#8fa3c4', 'font-size': 10}, `${s.thickness_nm} nm`, holder); }));
    }
    points.slice().sort((p, q) => radius(q) - radius(p) || q.display_lab[0] - p.display_lab[0]).forEach((p) => {       // larger below, so no confident colour hides a small one
      const r = radius(p), on = picked && picked.id === p.id, pale = !!faint && faint(p);        // pale: cannot be what is being picked
      const c = add('circle', {cx: x(p.display_lab[P.x]), cy: y(p.display_lab[P.y]), r: on ? r + 3 : r,
        fill: swatch(p.display_lab).style.background || '#888', 'fill-opacity': pale ? 0.18 : p.referenced && !p.provisional ? 1 : 0.45,
        ...(pale ? {'stroke-opacity': 0.35} : {}),
        stroke: picked && picked.id === p.id ? '#ffffff' : p.provisional ? '#c9a2ff' : !p.referenced ? '#e0b050' : p.measurement === 'calibrated' ? '#dfe7f5' : '#7d8aa3',
        'stroke-width': picked && picked.id === p.id ? 3 : 1.4, 'stroke-dasharray': p.provisional ? '6 2 1 2' : !p.referenced ? '1.5 3' : p.approximate ? '3 2' : '', style: 'cursor:pointer', ...thin});
      steady.push((s) => c.setAttribute('r', (on ? r + 3 : r) / s));        // the diameter tells the confidence, so it does not grow with the zoom
      c.append(Object.assign(document.createElementNS(SVG, 'title'), {textContent: `${p.title} · ${p.layer_name || 'layer ' + p.layer_index} · ${labText(p.display_lab)}${p.provisional ? ' · provisional' : ''} · confidence ${p.confidence == null ? 'not assessed (one engraving)' : num(p.confidence)} (${App.agreed(p.agreement)})`}));
      c.addEventListener('click', () => onPick(p));
    });
    if (target) fixed(x(target[P.x]), y(target[P.y]), (holder) => {
      add('circle', {cx: 0, cy: 0, r: 13, fill: 'none', stroke: '#ffd166', 'stroke-width': 2.5}, null, holder);
      add('line', {x1: -18, x2: 18, y1: 0, y2: 0, stroke: '#ffd166', 'stroke-width': 1.5}, null, holder);
      add('line', {x1: 0, x2: 0, y1: -18, y2: 18, stroke: '#ffd166', 'stroke-width': 1.5}, null, holder); });
    add('text', {x: W - pad, y: H - pad + 16, fill: '#9fb0c8', 'font-size': 12, 'text-anchor': 'end'}, P.right, svg);          // the axis names stay where they are
    add('text', {x: pad, y: pad - 10, fill: '#9fb0c8', 'font-size': 12}, P.up, svg);

    let view = clampView(views[plane] || {s: 1, tx: 0, ty: 0}, W, H);
    const scaleText = h('span', {class: 'cm-scale'});
    const apply = () => {
      g.setAttribute('transform', `translate(${view.tx} ${view.ty}) scale(${view.s})`);
      steady.forEach((fn) => fn(view.s));
      scaleText.textContent = view.s > 1 ? `×${(Math.round(view.s * 10) / 10).toString().replace('.', ',')}` : '';
      views[plane] = view;
    };
    // the frame of the picture inside the box that holds it (the picture is centred and keeps its proportions)
    const frame = () => { const r = svg.getBoundingClientRect(), k = Math.min(r.width / W, r.height / H) || 1; return {r, k, ox: (r.width - W * k) / 2, oy: (r.height - H * k) / 2}; };
    const at = (e) => { const f = frame(); return [(e.clientX - f.r.left - f.ox) / f.k, (e.clientY - f.r.top - f.oy) / f.k]; };
    const zoomAt = (factor, px, py) => { view = zoomView(view, factor, px, py, W, H); apply(); };
    svg.addEventListener('wheel', (e) => {
      e.preventDefault();
      if (!e.ctrlKey && (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY))) {              // sideways: move the map
        const k = frame().k; view = panView(view, -(e.deltaX || e.deltaY) / k, 0, W, H); apply(); return;
      }
      const [px, py] = at(e);
      zoomAt(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), px, py);                       // a pinch on a trackpad arrives as a wheel with ctrl
    }, {passive: false});
    svg.addEventListener('dblclick', (e) => { const [px, py] = at(e); zoomAt(2, px, py); });
    // drag with the mouse or a finger; two fingers pinch. A click that ends a drag picks nothing.
    const down = new Map();
    let moved = false, pinch = null;
    svg.addEventListener('pointerdown', (e) => { down.set(e.pointerId, {x: e.clientX, y: e.clientY}); moved = false;
      if (down.size === 2) { const [a, b] = [...down.values()]; pinch = Math.hypot(a.x - b.x, a.y - b.y) || 1; } });
    svg.addEventListener('pointermove', (e) => {
      const was = down.get(e.pointerId);
      if (!was) return;
      const f = frame();
      if (down.size === 2) {                                                                    // pinch: scale about the middle of the two fingers
        down.set(e.pointerId, {x: e.clientX, y: e.clientY});
        const [a, b] = [...down.values()], now = Math.hypot(a.x - b.x, a.y - b.y) || 1;
        const px = ((a.x + b.x) / 2 - f.r.left - f.ox) / f.k, py = ((a.y + b.y) / 2 - f.r.top - f.oy) / f.k;
        zoomAt(now / pinch, px, py); pinch = now; moved = true; return;
      }
      const dx = e.clientX - was.x, dy = e.clientY - was.y;
      if (!moved && Math.hypot(dx, dy) < 4) return;                                             // a click is not a drag
      if (!moved) { moved = true; svg.style.cursor = 'grabbing'; if (svg.setPointerCapture) svg.setPointerCapture(e.pointerId); }
      down.set(e.pointerId, {x: e.clientX, y: e.clientY});
      view = panView(view, dx / f.k, dy / f.k, W, H); apply();
    });
    const up = (e) => { down.delete(e.pointerId); pinch = null; svg.style.cursor = 'grab'; };
    svg.addEventListener('pointerup', up); svg.addEventListener('pointercancel', up);
    svg.addEventListener('click', (e) => { if (moved) { e.stopPropagation(); moved = false; } }, true);
    svg.addEventListener('keydown', (e) => {
      const k = {ArrowLeft: [60, 0], ArrowRight: [-60, 0], ArrowUp: [0, 60], ArrowDown: [0, -60]}[e.key];
      if (k) view = panView(view, k[0], k[1], W, H);
      else if (e.key === '+' || e.key === '=') view = zoomView(view, ZOOM.step, W / 2, H / 2, W, H);
      else if (e.key === '-') view = zoomView(view, 1 / ZOOM.step, W / 2, H / 2, W, H);
      else if (e.key === '0') view = {s: 1, tx: 0, ty: 0};
      else return;
      e.preventDefault(); apply();
    });
    apply();
    const zoomIn = btn('+', () => zoomAt(ZOOM.step, W / 2, H / 2), 'btn-small'), zoomOut = btn('−', () => zoomAt(1 / ZOOM.step, W / 2, H / 2), 'btn-small');
    zoomIn.setAttribute('aria-label', 'Zoom in'); zoomOut.setAttribute('aria-label', 'Zoom out');
    // the circles one by one, left to right, for a person who cannot aim at one (ux-accessible-layout-p0): a step picks the next circle as a click does
    const order = points.slice().sort((p, q) => p.display_lab[P.x] - q.display_lab[P.x] || p.display_lab[P.y] - q.display_lab[P.y] || String(p.id).localeCompare(String(q.id)));
    const stepTo = (dir) => {
      const at = picked ? order.findIndex((q) => q.id === picked.id) : -1;
      const n = at < 0 ? (dir > 0 ? 0 : order.length - 1) : (at + dir + order.length) % order.length;
      onPick(order[n], {step: dir > 0 ? 'next' : 'previous', n: n + 1, of: order.length});
    };
    const stepButtons = [['previous', '◀', 'Previous color on map', -1], ['next', '▶', 'Next color on map', 1]].map(([key, sign, name, dir]) => {
      const b = btn(sign, () => stepTo(dir), 'btn-small');
      b.setAttribute('aria-label', name); b.setAttribute('title', name); b.setAttribute('data-step', key);
      return b;
    });
    const bar = h('div', {class: 'cm-zoombar'}, scaleText, ...stepButtons, zoomIn, zoomOut, btn('Full view', () => { view = {s: 1, tx: 0, ty: 0}; apply(); }, 'btn-small'));
    return h('div', {class: 'cm-zoom'}, svg, bar);
  }

  // the film model's reading of one measured colour
  function filmOf(p, model) {
    if (!model) return null;
    const m = (model.points || []).find((q) => q.pair_id === p.pair_id && q.layer_index === p.layer_index);
    if (!m) return null;
    const alt = m.alternative ? ` or ${num(m.alternative.thickness_nm, 0)} nm (ΔE ${num(m.alternative.residual_de, 1)})` : '';
    return h('p', {class: 'small'}, h('strong', {}, 'Oxide film according to the model: '),
      m.thickness_determined ? `${num(m.thickness_nm, 0)} nm, difference ΔE ${num(m.residual_de, 1)}${m.ramp ? '; interference order selected using the whole plate' : ''}`
        : m.dark_share >= 0.6 ? `mostly dark oxide (${num(m.dark_share * 100, 0)}% share); film thickness cannot be determined from color`
        : `${num(m.thickness_nm, 0)} nm${alt}, difference ΔE ${num(m.residual_de, 1)}; interference order is ambiguous`,
      m.dark_share > 0 && m.dark_share < 0.6 ? ` · dark oxide ${num(m.dark_share * 100, 0)} %` : '');
  }

  /** Show computed settings only with confidence, expected color error, and stability. */
  function estimatesText(r) {
    const e = r.estimates;
    if (r.settings && e) {
      return ` · confidence ${num(e.confidence, 2)} · expected color error ΔE ${num(e.expected_delta_e, 1)}`
        + ` · stability: variance ${num(e.stability.variance, 1)} across ${e.stability.cells} nearest cells`;
    }
    return ` · settings not calculated: ${I18N.tr(r.note || '')}`;
  }

  // what the film model says about a wanted colour; settings are computed only for one laser and lens (DEC-063)
  function filmCard(r) {
    const cand = (c) => h('article', {class: 'card stack'},
      h('p', {}, h('strong', {}, `Film ${num(c.thickness_nm, 0)} nm`), c.dark_share > 0 ? ` with dark oxide share ${num(c.dark_share * 100, 0)} %` : '', ` · difference from target ΔE ${num(c.residual_de, 1)}`),
      (c.by_regime || []).length ? h('div', {class: 'stack small'}, h('span', {class: 'muted'}, 'Calculated from the thickness-versus-dose law, not measured; only within the regime’s measured doses:'),
        ...c.by_regime.map((r) => h('p', {}, h('strong', {}, `${num(r.frequency, 0)} kHz, ${num(r.pulse_width, 0)} ns`), `: approximately ${num(r.areal_energy_j_cm2, 0)} J/cm²`,
          r.settings ? ` · ${settings(r.settings)}` : '',
          estimatesText(r),
          ' · nearest measured: ', swatch(r.nearest_measured.lab), ` ${r.nearest_measured.work} · ${r.nearest_measured.layer || ''}`))) : null,
      c.same_film_measured.length ? h('div', {class: 'stack small'}, h('span', {class: 'muted'}, 'Measured regimes producing this film:'),
        ...c.same_film_measured.map((m) => h('p', {}, swatch(m.lab), ` ${m.work} · ${m.layer || ''} · ${settings(m.parameters)} · film ${num(m.thickness_nm, 0)} nm${m.ambiguous ? ' (interference order ambiguous)' : ''}`,
          ' · ', link(`/analysis/${m.pair_id}`, 'analysis'))))
        : h('p', {class: 'muted small'}, 'No measured regimes have produced this film yet.'));
    return h('div', {class: 'stack'}, h('h3', {}, 'What the film model says'),
      h('p', {class: 'small'}, r.reachable_by_a_film ? 'The model places the color on the interference spiral and estimates the film thicknesses below. Any supporting measured regimes are identified separately.'
        : 'The color lies more than 8 ΔE from the interference spiral; this model finds no titanium oxide film that produces it.'),
      ...r.candidates.map(cand),
      h('p', {class: 'muted small'}, !r.partition ? 'Thickness-versus-dose settings are calculated for one laser and lens; select them in the Laser and lens filter.'
        : r.kinetics.usable ? `Kinetics: the thickness-versus-dose law was fitted for ${r.kinetics.regimes} pulse regimes.` : `Kinetics cannot yet calculate settings: ${I18N.tr(r.kinetics.note)}.`));
  }

  function where(p) {
    // a provisional colour (DEC-045) comes from a check not accepted yet: its link leads to that check, not to an analysis
    return h('div', {class: 'stack small'},
      h('p', {}, h('strong', {}, `${p.layer_name || 'layer ' + p.layer_index}`), p.source === 'tonal' ? pill('gray → power') : null,
        Tasks.badge(p.task),
        p.provisional ? pill('provisional', 'warn') : null, p.referenced ? null : pill('not referenced to clean titanium', 'warn'),
        ' · ', link('/experiment/' + encodeURIComponent(p.experiment), p.title),
        ' · ', p.provisional ? link(p.review, 'pair review: accept or correct') : link(`/analysis/${p.pair_id}`, 'measurement analysis')),
      h('p', {class: 'muted'}, [p.setup_label, p.material, `photo ${p.photo}`, when(p.date)].filter(Boolean).join(' · ')),
      h('p', {}, settings(p.parameters)), h('p', {class: 'muted'}, timeText(p)));
  }

  async function render(ctx) {
    const state = JSON.parse(sessionStorage.getItem('color-map') || '{}');
    const f = {setup: state.setup || '', material: state.material || '', measurement: state.measurement || '', task: state.task || '', hide: !!state.hide, doubtful: !!state.doubtful,
      within: !!state.within, provisional: !!state.provisional, maxTime: state.maxTime || null, tolerance: state.tolerance ?? '', sort: state.sort || 'recommended'};
    const dotsOf = ctx.query.dots || null;                 // picking the colour of a photo work's dots: the map is that of its laser and lens
    if (dotsOf && ctx.query.setup) f.setup = ctx.query.setup;
    const q = new URLSearchParams();
    if (dotsOf) q.set('dots', dotsOf);
    if (dotsOf && ctx.query.zone) q.set('zone', ctx.query.zone);           // a photo zone of the vector work ``dots``
    if (f.setup) q.set('setup', f.setup);
    if (f.material) q.set('material', f.material);
    if (f.measurement) q.set('measurement', f.measurement);
    if (f.task) q.set('task', f.task);                 // REQ-020: colors from one engraving task
    if (f.maxTime) q.set('max_time_s_per_cm2', f.maxTime);   // REQ-035: maximum time per cm² in seconds
    if (f.hide) q.set('include_unreferenced', 'false');
    if (f.doubtful) q.set('hide_doubtful', 'true');            // REQ-049: not the colours whose circle is smaller than that of one engraving
    const data = await get('/colors' + (q.toString() ? '?' + q : ''));
    const pick = data.dots ? {...data.dots, from: ctx.query.from || null} : null;     // ``from``: where the map was opened, to go back to
    if (pick) f.setup = pick.setup;                  // the server shows the work's laser and lens whatever the address says
    // the laser and lens chosen in the filter: the film model, its laws and computed settings are theirs alone
    const chosen = data.options.setups.find((o) => o.key === f.setup) || null;
    if (f.setup && !chosen) {                 // a filter remembered from before the laser and lens were keyed by their records
      sessionStorage.setItem('color-map', JSON.stringify({...state, setup: ''}));
      return render(ctx);
    }
    const partition = chosen ? `device_id=${chosen.device_id}&lens_id=${App.lensParam(chosen.lens_id)}` : '';
    let model = null;
    const modelRequest = get('/oxide/model' + (partition ? '?' + partition : '')).catch(() => null);
    const plane = state.plane || 'ab', band = state.band || [0, 100];
    const shown = () => data.points.filter((p) => p.display_lab[0] >= band[0] && p.display_lab[0] <= band[1]);
    const remember = (patch) => { sessionStorage.setItem('color-map', JSON.stringify({...f, target, plane, band, ...patch})); App.render({preserveScroll: true}); };
    const select = (label, key, values, current, names) => h('label', {class: 'f'}, h('span', {}, label),
      h('select', {onChange: (e) => remember({[key]: e.target.value})}, h('option', {value: ''}, 'All'),
        ...values.map((v) => h('option', {value: v, selected: v === current}, names ? names[v] : v))));

    let target = state.target || null, picked = null;
    let searchSeq = 0;
    const results = h('div', {class: 'stack'}), detail = h('div', {class: 'cm-detail stack', hidden: true}), plotBox = h('div', {class: 'cm-plot'});
    const stepNote = h('p', {class: 'small cm-step-note', role: 'status', 'aria-live': 'polite'});           // which circle a key press picked
    // REQ-001 of ux-evidence-summaries-p0: the picked colour shows its swatch and the independent signals (repeat, where measured, what it rests
    // on) and its settings; Lab, the confidence figures and the engravings it is known from are one fold away
    const drawPlot = () => plotBox.replaceChildren(plot(shown(), (p, how) => { picked = p; detail.hidden = false;
      const recipe = data.recipes && data.recipes[p.group], known = recipe ? recipe.sources : [ONE_ENGRAVING(p)];
      fill(detail, h('h3', {}, 'Selected color'), EvidenceSummary.summary({...p, sources: known}, {lead: swatch(p.display_lab)}),
        pick ? DotPick.action(pick, p) : null, where(p), filmOf(p, model),
        EvidenceSummary.disclosure('Details: Lab color, confidence, sources', [
          h('p', {}, `${labText(p.display_lab)}${p.approximate ? ' · approximate shade' : ''}`), trustLine(p), sourcesBlock(known, p.agreement, recipe ? recipe.lab : null)]),
        btn('Find this color among all', () => { setTarget(tidy(p.display_lab)); }, 'btn-small')); drawPlot();
      if (how) {                                                // a step by the buttons: say which circle it is and keep the focus on the button that was pressed
        fill(stepNote, `Color ${how.n} of ${how.of}: ${p.title} · ${p.layer_name || 'layer ' + p.layer_index} · ${labText(p.display_lab)}`);
        const again = [...plotBox.querySelectorAll('button')].find((b) => b.getAttribute('data-step') === how.step);
        if (again) again.focus();
      } else fill(stepNote); }, target, picked, plane,
      model ? model.spiral : null, pick ? (p) => !DotPick.can(pick, p) : null));
    // a colour taken from the picker or from a circle of the map is tidied to a tenth; a colour typed into the boxes is searched exactly as typed
    const tidy = (lab) => lab.map((v) => +(+v).toFixed(1));
    async function setTarget(lab) {
      const mine = ++searchSeq;
      target = lab.map(Number);
      searchForm.clear();
      targetSelector.set(target);
      sessionStorage.setItem('color-map', JSON.stringify({...f, target}));
      const p = new URLSearchParams({L: target[0], a: target[1], b: target[2], limit: '12'});
      for (const k of ['setup', 'material', 'measurement', 'task']) if (f[k]) p.set(k, f[k]);
      if (f.maxTime) p.set('max_time_s_per_cm2', f.maxTime);
      if (f.tolerance !== '') p.set('tolerance_de', f.tolerance);
      if (f.sort !== 'recommended') p.set('sort', f.sort);
      if (f.within) p.set('include_unreferenced', 'true');
      if (f.provisional) p.set('include_provisional', 'true');
      if (f.doubtful) p.set('hide_doubtful', 'true');
      let r, film;
      try {
        [r, film] = await Promise.all([get('/colors/search?' + p),
          get(`/colors/settings?L=${target[0]}&a=${target[1]}&b=${target[2]}${partition ? '&' + partition : ''}`).catch(() => null)]);
      } catch (e) { if (mine === searchSeq) searchForm.fail(e); return; }      // old searches cannot report errors over the current target
      if (mine !== searchSeq) return;
      drawPlot();
      // one entry per recipe: the same settings, laser and lens, titanium stock and kind of measurement; a re-photograph of one
      // engraving is not another repetition (DEC-021), so engravings and photographs are counted apart
      const often = (m) => (m.repeats > 1 ? `produced ${times(m.repeats)} (independent engravings)` : 'produced in one engraving')
        + ` · photos: ${m.photographs} · experiments: ${m.experiments.length}`;
      // REQ-020: measured evidence, not a prediction: observations, repeatability, and missing context
      const evidence = (m) => h('p', {class: 'muted small'},
        m.repeatability && m.repeatability.assessed ? `Repeatability: independent engravings differ by up to ΔE ${num(m.repeatability.max_delta_e, 1)}`
          : 'Repeatability not assessed: one independent engraving',
        (m.observation_ids || []).length ? ` · observations #${m.observation_ids.join(', #')}` : '',
        (m.provisional_checks || []).length ? ` · checks under review #${m.provisional_checks.join(', #')}` : '',
        ...(m.missing_context || []).length ? [' · missing: ', ...Tasks.missing(m.missing_context)] : []);
      // DEC-075: within the ΔE tolerance the fastest recipes come first; the server says how its answer is ordered.
      // At most 12 recipes are asked for (``limit``), so the results stay a plain list; the engravings each recipe is known from are
      // folded under its card (REQ-005, DEC-090), while the one colour picked on the map shows them open.
      const o = r.order || {};
      const order = o.by === 'time' ? 'Sorted by estimated time per area; recipes without a time estimate are last.'
        : o.by === 'stability' ? 'Sorted by confidence in repeatability, then by color difference.'
        : f.sort === 'distance' ? 'Sorted by color difference from the target sample.'
        : o.by === 'time_within_tolerance'
        ? `Within ΔE tolerance ${num(o.tolerance_de, 1)}${o.tolerance_source === 'rules' ? ' (from laser and lens rules)' : ''} recipes: ${o.within_tolerance}; `
          + 'the fastest by estimated time come first, followed by the rest in order of distance.'
        : 'No ΔE tolerance is set: entries are sorted by distance. Set a tolerance to show the fastest close colors first.';
      fill(results, h('h3', {}, 'Where this color was found'), h('p', {class: 'muted small'}, 'Measurements, not predictions: each entry is one recipe for one engraving task.'),
        h('p', {class: 'small'}, order),
        !r.matches.length ? h('p', {class: 'muted'}, 'No matching colors yet.') : h('div', {class: 'stack'}, ...r.matches.map((m) => h('article', {class: 'card stack color-hit'},
          h('div', {class: 'row'}, swatch(m.display_lab), h('strong', {}, `ΔE ${num(m.distance, 1)}`),
            m.within_tolerance ? pill('within tolerance', 'ok') : null,
            m.approximate ? pill(m.referenced ? 'relative to clean titanium, approximate shade' : 'as photographed, without reference', 'warn') : null,
            m.provisional ? pill('provisional', 'warn') : null,
            h('span', {class: 'muted small'}, often(m))),
          EvidenceSummary.summary({...m, sources: m.sources || [ONE_ENGRAVING(m)]}), pick ? DotPick.action(pick, m) : null, where(m),
          EvidenceSummary.disclosure('Details: confidence, sources, repeatability',
            [trustLine(m), sourcesBlock(m.sources || [ONE_ENGRAVING(m)], m.agreement, m.display_lab, false), evidence(m)])))),
        r.counts.unreferenced && !f.within ? h('div', {class: 'alert warn'}, `${colours(r.counts.unreferenced)} without a clean titanium reference are excluded from search because their distance to other colors would not be meaningful. `,
          btn('Include these in search', () => remember({within: true}), 'btn-small')) : null,
        r.counts.provisional && !f.provisional ? h('div', {class: 'alert warn'}, `${colours(r.counts.provisional)} from checks not yet accepted are excluded from search because they are provisional. `,
          btn('Include provisional colors in search', () => remember({provisional: true}), 'btn-small')) : null,
        r.counts.doubtful ? h('div', {class: 'alert warn'}, f.doubtful ? `${r.counts.doubtful} recipes with uncertain colors are excluded from search because repeated engravings produced different colors. `
          : `Uncertain recipes among the results (colors changed across repeats): ${r.counts.doubtful}; these are marked. `,
          f.doubtful ? btn('Show these too', () => remember({doubtful: false}), 'btn-small') : null) : null,
        r.counts.slower && f.maxTime ? h('div', {class: 'alert warn'}, `${colours(r.counts.slower)} taking longer than ${mmss(f.maxTime)} min per cm² or without a time-per-area estimate are excluded from search. `,
          btn('Remove time limit', () => remember({maxTime: null}), 'btn-small')) : null,
        film ? h('div', {class: 'stack'}, pill('Model prediction, not a measurement', 'warn'), filmCard(film)) : null);
    }
    const imageUrl = pick ? (pick.work.zone == null ? `/api/photo-works/${encodeURIComponent(pick.work.id)}/picture`
      : `/api/plans/${encodeURIComponent(pick.work.id)}/source-image`) : null;
    const targetSelector = App.targetColor({initial: target, onSelect: setTarget, imageUrl});
    const searchForm = targetSelector.form;
    const sort = h('select', {'aria-label': 'Sort recipes', onChange: (e) => {
      f.sort = e.target.value; sessionStorage.setItem('color-map', JSON.stringify({...f, target}));
      if (target) setTarget(target);
    }}, ...[['recommended', 'Recommended'], ['distance', 'Closest color'], ['time', 'Fastest'], ['stability', 'Most stable']]
      .map(([value, label]) => h('option', {value, selected: f.sort === value}, label)));
    // DEC-075: within the ΔE tolerance the fastest recipes come first; an empty value uses the selected laser and lens rules
    // colormap.delta_tolerance: not negative; a wrong one stays in the box with the reason beside it, and the search is not changed
    const tolerance = Forms.numberInput(Forms.QUANTITIES.searchTolerance, {value: f.tolerance, placeholder: 'from rules', 'aria-label': 'ΔE tolerance'});
    const toleranceNote = Forms.watch(tolerance, 'searchTolerance', (v) => { f.tolerance = v === null ? '' : String(v); if (target) setTarget(target); });
    const toleranceRules = Forms.describe(tolerance, 'searchTolerance', {extra: 'leave empty to use the selected laser and lens rules'});
    // colormap.time_limit: above 0 seconds; the box takes minutes:seconds («0:30») or minutes as a number; empty is no limit
    const timeNote = Forms.notice({what: 'Time limit', kept: 'The search remains unchanged.'});
    const maxTime = h('input', {type: 'text', inputmode: 'decimal', placeholder: 'm:ss', value: f.maxTime ? mmss(f.maxTime) : '',
      'aria-label': 'Maximum time, minutes:seconds per square centimeter', onChange: (e) => {
        const seconds = parseLimit(e.target.value);
        if (Number.isNaN(seconds)) timeNote.say(`Enter a time greater than zero as minutes:seconds (for example, 0:30) or a number of minutes. Entered: “${e.target.value.trim()}”. The search remains unchanged.`);
        else { timeNote.clear(); remember({maxTime: seconds}); }
      }});
    timeNote.attach(maxTime);
    const timeRules = Forms.describe(maxTime, {unit: 'min:s per cm²', min: 0, minOpen: true}, {extra: 'minutes:seconds (0:30) or minutes as a number; leave empty for no limit'});
    drawPlot();
    if (target) setTarget(target);

    const total = data.points.length;
    const counts = `Colors shown: ${total} · calibrated with reference card ${data.counts.calibrated} · relative to camera ${data.counts.relative}`
      + (data.counts.unreferenced && !f.hide ? ` · without clean titanium reference ${data.counts.unreferenced}` : '')
      + (data.counts.provisional ? ` · provisional (check not yet accepted) ${data.counts.provisional}` : '')
      + (data.counts.slower ? ` · hidden as slower (or without time-per-area estimate) ${data.counts.slower}` : '')
      + (data.counts.doubtful ? (f.doubtful ? ` · uncertain hidden (circle smaller than for one engraving) ${data.counts.doubtful}` : ` · uncertain (circle smaller than for one engraving) ${data.counts.doubtful}`) : '');
    const head = h('div', {class: 'os-head'}, h('div', {class: 'cm-title'}, h('h2', {}, 'Color map'), h('p', {class: 'sub', title: counts}, counts)), h('span', {class: 'spacer'}),
      chosen ? link(`/colors?device=${chosen.device_id}&lens=${App.lensParam(chosen.lens_id)}`, 'Model and predicted settings for this laser and lens')
        : h('span', {class: 'muted small'}, 'Select a laser and lens to view their model and predictions'));
    // the filters in one narrow column; the long explanation is folded away
    const filters = h('div', {class: 'os-col'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Filters')),
      h('div', {class: 'os-scroll'}, h('div', {class: 'cm-filters'},
        pick ? h('div', {class: 'f', title: 'Laser and lens of the work receiving the dot color'}, h('span', {}, 'Laser and lens'),
          h('span', {class: 'small'}, (chosen || {}).label || f.setup))
          : select('Laser and lens', 'setup', data.options.setups.map((o) => o.key), f.setup, Object.fromEntries(data.options.setups.map((o) => [o.key, o.label]))),
        select('Material', 'material', data.options.materials, f.material),
        select('Measurement method', 'measurement', ['calibrated', 'relative'], f.measurement, {calibrated: 'Reference card', relative: 'Relative to camera'}),
        select('Task', 'task', data.options.tasks || [], f.task, Object.fromEntries((data.options.tasks || []).map((k) => [k, Tasks.name(k)]))),
        h('fieldset', {class: 'cm-evidence-filters stack'}, h('legend', {}, 'Evidence and time'),
          h('label', {class: 'f'}, h('span', {}, 'Maximum time, min/cm²'), maxTime, timeRules), timeNote.error,
          h('label', {class: 'row small'}, h('input', {type: 'checkbox', checked: f.hide, onChange: (e) => remember({hide: e.target.checked})}),
            'Hide colors without clean titanium in the photo'),
          h('label', {class: 'row small', title: 'Repeated engravings produced different colors'},
            h('input', {type: 'checkbox', checked: f.doubtful, onChange: (e) => remember({doubtful: e.target.checked})}), 'Hide uncertain colors')),

        h('details', {class: 'cm-about'}, h('summary', {}, 'How this is calculated'),
          h('p', {class: 'muted small'}, 'All measured colors from all experiments. Select a color to see where it occurred and the settings used. '
            + 'Engraving time is estimated from recipe settings: 100 / (speed × line spacing) seconds per cm² per pass plus a turnaround on each line, '
            + 'multiplied by passes, repeats and by 2 for cross-hatching; frequency and pulse duration do not affect time. '
            + (data.counts.provisional ? 'Provisional colors have a purple dashed outline and link to the pair check. They are excluded from predictions and included in search only on request until the check is accepted. ' : '')
            + 'Colors without a reference card are normalized to clean titanium in the same photo, allowing comparison across photos, but the shade is approximate (dashed outline). '
            + 'If the photo has no clean titanium, the color is shown as photographed (pale circle with dotted outline) and excluded from search by default. '
            + 'Circle diameter represents confidence in the color for these settings: one engraving starts at a medium size; each repeat with the same color increases it by a factor of 1.5 (up to a limit), and each different result decreases it by 1.5 (down to a limit). A circle smaller than one engraving indicates color changed across repeats; these colors are marked uncertain and can be hidden. Select a color to see its confidence and all supporting engravings. The settings color is the color shared by engravings; a later redo replaces the old color.')))));
    // the map fills the middle; the colour picked on it is described in a strip under it
    // the band only narrows which circles are drawn (a view, no server rule): L* itself runs from 0 to 100; a number outside is said beside its box and kept
    const bandFrom = h('input', {type: 'number', step: 'any', min: 0, max: 100, value: band[0], 'aria-label': 'Lightness from'});
    const bandTo = h('input', {type: 'number', step: 'any', min: 0, max: 100, value: band[1], 'aria-label': 'Lightness to'});
    const bandFromNote = Forms.watch(bandFrom, 'lightnessBand', (v) => remember({band: [v, band[1]]}), {required: true});
    const bandToNote = Forms.watch(bandTo, 'lightnessBand', (v) => remember({band: [band[0], v]}), {required: true});
    const modelCaption = h('p', {class: 'cm-caption muted small', hidden: true});
    const mapCol = h('div', {class: 'os-col'},
      h('div', {class: 'os-col-head'}, h('h3', {}, 'Color map'), h('span', {class: 'spacer'}),
        ...[['ab', 'a* × b*'], ['La', 'a* × L*'], ['Lb', 'b* × L*']].map(([k, label]) => btn(label, () => remember({plane: k}), plane === k ? 'primary btn-small' : 'btn-small'))),
      h('div', {class: 'cm-bar small'}, h('span', {}, 'Lightness L* from'), bandFrom, Forms.describe(bandFrom, 'lightnessBand'), bandFromNote,
        h('span', {}, 'to'), bandTo, Forms.describe(bandTo, 'lightnessBand'), bandToNote,
        h('span', {class: 'muted'}, ` · showing ${shown().length} of ${data.points.length} · wheel to zoom, drag to pan, double-click to zoom in`)),
      modelCaption,
      stepNote, plotBox, detail);
    modelRequest.then((loaded) => {
      model = loaded;
      if (model && model.summary && model.summary.observations) {
        modelCaption.hidden = false;
        modelCaption.textContent = `Dashed line: modeled oxide-film spiral (median deviation ${num(model.summary.median_de_coloured, 1)} ΔE across ${model.summary.coloured} colors)`;
      }
      const focused = document.activeElement;
      const step = [...plotBox.querySelectorAll('button')].find((button) => button === focused)?.getAttribute('data-step');
      const plotFocused = plotBox.querySelector('svg') === focused;
      drawPlot();
      const replacement = step ? [...plotBox.querySelectorAll('button')].find((button) => button.getAttribute('data-step') === step)
        : plotFocused ? plotBox.querySelector('svg') : null;
      if (replacement) replacement.focus();
    });
    // the wanted colour on top (always in view), the found recipes below (the only part that scrolls)
    const search = h('div', {class: 'os-col'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Target color')),
      h('div', {class: 'cm-target'}, targetSelector.el, field('Sort recipes', sort),
        h('div', {class: 'cm-target-row'}, h('label', {class: 'f'}, h('span', {}, 'ΔE tolerance'), tolerance, toleranceRules, toleranceNote)),
        h('p', {class: 'muted small'}, 'Choose a color in the picker or enter L, a, b. You can also select a color on the map and choose “Find this color among all”.')),
      h('div', {class: 'os-scroll'}, results));
    return h('div', {class: 'os cm' + (pick ? ' cm-picking' : '')}, head, pick ? DotPick.banner(pick) : null, h('div', {class: 'os-body cm-body'}, filters, mapCol, search));
  }
  return {render, hexToLab, zoomView, panView, clampView};
})();
