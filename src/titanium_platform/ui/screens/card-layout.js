/* The layout of the business-card editor (screens/card-work.js): the left column (Add, Layers) and the right column (the selected element or the
   engraving settings) can be dragged wider or narrower and hidden; the card in the centre takes what is left. The widths and the hidden flags
   are remembered in the browser (localStorage, one key). This file draws only the splitters and the hide/show buttons and sets two CSS custom
   properties on the body of the screen (--cw-left, --cw-right: the width of each column in px, 36 px for a hidden one); card.css does the rest.

   The pure parts (parse, clampWidths, limits) take and return plain objects {left, right, leftHidden, rightHidden}, so they are tested without a DOM.
   mount(body, {left, right, leftHead, rightHead}) -> {destroy(), refresh(), state()}
     body        the grid that holds the three columns; the splitters are put between them, in that order (so the Tab key meets them in place)
     left, right the columns; leftHead, rightHead the heads that get the "Hide panel" button (default: the first .os-col-head of the column)
     storage, win  for tests only: the localStorage and the window to use instead of the browser's own
     The widths asked for are kept as they are (a narrow window shows less, a wide one shows them again); a drag, a key or a reset replaces them.
   A narrow window stacks the columns (styles.css and card.css, max-width 1100px): there the splitters and the buttons are display:none in card.css. */
'use strict';
const CardLayout = (() => {
  const {h} = App;
  const KEY = 'cw.layout.v1';
  const SIDES = ['left', 'right'];
  const LIMITS = {left: [200, 520], right: [280, 720]};         // [narrowest, widest] in px
  const DEFAULTS = {left: 280, right: 420};
  const SPLIT = 10;                                           // the width of a splitter column: also its hit area
  const RAIL = 36;                                            // the width of a hidden column: a thin rail with a button that shows it again
  const CENTRE_MIN = 360;                                     // the card keeps this much when the window allows it
  const STEP = 16, BIG_STEP = 64;                             // the arrow keys, and with Shift

  const isNumber = (v) => typeof v === 'number' && Number.isFinite(v);
  /** A width of ``side``: rounded and kept inside its limits; anything that is not a number is the default. */
  const widthOf = (side, v) => (isNumber(v) ? Math.min(LIMITS[side][1], Math.max(LIMITS[side][0], Math.round(v))) : DEFAULTS[side]);
  const shown = (side, widths) => (widths[`${side}Hidden`] ? RAIL : widthOf(side, widths[side]));       // what the column takes in the grid

  /** The saved layout (a JSON text, an object or nothing) as a valid one: a bad or missing figure is the default, a figure out of range is clamped. */
  function parse(stored) {
    let data = stored;
    try { if (typeof stored === 'string') data = JSON.parse(stored); } catch (_) { data = null; }
    if (!data || typeof data !== 'object' || Array.isArray(data)) data = {};
    return {left: widthOf('left', data.left), right: widthOf('right', data.right), leftHidden: data.leftHidden === true, rightHidden: data.rightHidden === true};
  }

  /** The widths to draw in a container of ``containerWidth`` px: each inside its limits, and the card keeps CENTRE_MIN px. When it does not, both
      columns give up the same share of what they could still give; at the narrowest they stay (the card gets less than CENTRE_MIN rather than a
      column below its limit). A container that is not measured (0, NaN) leaves the widths as they are. A hidden column takes only its rail. */
  function clampWidths(widths, containerWidth) {
    const w = widths || {};
    let left = widthOf('left', w.left), right = widthOf('right', w.right);
    if (!(containerWidth > 0)) return {left, right};
    const over = shown('left', {...w, left}) + shown('right', {...w, right}) + 2 * SPLIT + CENTRE_MIN - Math.floor(containerWidth);
    const spareLeft = w.leftHidden ? 0 : left - LIMITS.left[0], spareRight = w.rightHidden ? 0 : right - LIMITS.right[0];
    if (over > 0 && spareLeft + spareRight > 0) {
      const cut = Math.min(over, spareLeft + spareRight), cutLeft = Math.round((cut * spareLeft) / (spareLeft + spareRight));
      left -= cutLeft;
      right -= cut - cutLeft;
    }
    return {left, right};
  }

  /** The narrowest and the widest ``side`` can be now, with the other column as it is: the widest leaves the card CENTRE_MIN px (never below the narrowest). */
  function limits(side, widths, containerWidth) {
    const [min, max] = LIMITS[side], other = side === 'left' ? 'right' : 'left';
    if (!(containerWidth > 0)) return {min, max};
    return {min, max: Math.max(min, Math.min(max, Math.floor(containerWidth) - 2 * SPLIT - CENTRE_MIN - shown(other, widths || {})))};
  }

  function mount(body, {left, right, leftHead, rightHead, storage, win} = {}) {
    const view = win || (typeof window === 'undefined' ? null : window);
    let dead = false, drag = null, seen = false;
    const bound = [], viewBound = [];
    const on = (el, type, fn) => { el.addEventListener(type, fn); bound.push([el, type, fn]); };

    // -- the memory: every access may fail (a private window, blocked site data, no localStorage at all) and then the layout is just not remembered
    const store = () => { try { return storage || globalThis.localStorage || null; } catch (_) { return null; } };
    let pref = parse((() => { try { const s = store(); return s ? s.getItem(KEY) : null; } catch (_) { return null; } })());
    const save = () => { try { const s = store(); if (s) s.setItem(KEY, JSON.stringify(pref)); } catch (_) { /* not remembered, still used */ } };

    // -- what is on the screen: the widths asked for, kept inside the window
    const measure = () => body.clientWidth || (body.getBoundingClientRect ? body.getBoundingClientRect().width : 0) || 0;
    const effective = () => clampWidths(pref, measure());
    const withFlags = (w) => ({left: w.left, right: w.right, leftHidden: pref.leftHidden, rightHidden: pref.rightHidden});

    const parts = {};
    for (const side of SIDES) {
      const col = side === 'left' ? left : right;
      const head = (side === 'left' ? leftHead : rightHead) || col.querySelector('.os-col-head');
      parts[side] = {
        col,
        split: h('div', {class: `cw-split cw-split-${side}`, role: 'separator', 'aria-orientation': 'vertical', 'aria-label': `Resize the ${side} panel`, tabindex: '0'}),
        hide: h('button', {type: 'button', class: 'btn btn-small cw-hide', title: `Hide the ${side} panel`}, 'Hide panel'),
        rail: h('button', {type: 'button', class: 'btn btn-small cw-rail', 'aria-label': `Show the ${side} panel`, title: `Show the ${side} panel`}, side === 'left' ? '»' : '«')};
      col.prepend(parts[side].rail);
      if (head) head.append(parts[side].hide);
    }
    const centre = Array.from(body.children).find((c) => c !== left && c !== right);
    body.replaceChildren(...[left, parts.left.split, centre, parts.right.split, right].filter(Boolean));

    function apply() {
      const w = effective(), size = measure();
      if (body.isConnected) seen = true;
      body.setAttribute('style', `--cw-left:${shown('left', withFlags(w))}px;--cw-right:${shown('right', withFlags(w))}px`);
      for (const side of SIDES) {
        const {col, split} = parts[side], hidden = pref[`${side}Hidden`], {min, max} = limits(side, withFlags(w), size);
        col.classList.toggle('cw-collapsed', hidden);
        split.classList.toggle('cw-split-off', hidden);
        split.setAttribute('aria-valuenow', w[side]);
        split.setAttribute('aria-valuemin', min);
        split.setAttribute('aria-valuemax', max);
      }
    }

    /** Make ``side`` ``wanted`` px wide, as far as its limits and the card allow; the other column stays as it is drawn now. */
    function resize(side, wanted) {
      const w = effective(), {min, max} = limits(side, withFlags(w), measure());
      pref = {...pref, left: w.left, right: w.right, [side]: Math.min(max, Math.max(min, Math.round(wanted)))};
      apply();
    }
    function toggle(side, hidden) {
      pref = {...pref, [`${side}Hidden`]: hidden};
      apply();
      save();
      parts[side][hidden ? 'rail' : 'hide'].focus();            // the button that was pressed is gone: the cursor goes to the one that takes its place
    }

    // -- the pointer: a drag moves the splitter with the pointer; the width is remembered when the pointer is let go
    function begin(side, ev) {
      if (dead || (ev.button != null && ev.button !== 0)) return;
      drag = {side, x: ev.clientX, width: effective()[side], id: ev.pointerId, moved: false};
      const {split} = parts[side];
      try { split.setPointerCapture(ev.pointerId); } catch (_) { /* the pointer is already gone */ }
      split.classList.add('cw-split-drag');
      body.classList.add('cw-dragging');                        // no text is selected while the pointer is down
      ev.preventDefault();
      split.focus();
    }
    function move(ev) {
      if (!drag || ev.pointerId !== drag.id) return;
      drag.moved = true;
      resize(drag.side, drag.width + (drag.side === 'left' ? 1 : -1) * (ev.clientX - drag.x));
    }
    function end(ev) {
      if (!drag || ev.pointerId !== drag.id) return;
      parts[drag.side].split.classList.remove('cw-split-drag');
      body.classList.remove('cw-dragging');
      if (drag.moved) save();
      drag = null;
    }

    // -- the keyboard: the arrows move the splitter (so Left makes the right column wider), Home and End go to the narrowest and the widest
    function key(side, ev) {
      if (ev.altKey || ev.ctrlKey || ev.metaKey) return;
      const w = effective(), {min, max} = limits(side, withFlags(w), measure()), step = ev.shiftKey ? BIG_STEP : STEP;
      const toward = (ev.key === 'ArrowRight' ? 1 : -1) * (side === 'left' ? 1 : -1);
      let wanted;
      if (ev.key === 'Home') wanted = min;
      else if (ev.key === 'End') wanted = max;
      else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') wanted = w[side] + toward * step;
      else return;
      ev.preventDefault();
      resize(side, wanted);
      save();
    }

    for (const side of SIDES) {
      const {split, hide, rail} = parts[side];
      on(split, 'pointerdown', (ev) => begin(side, ev));
      on(split, 'pointermove', move);
      for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) on(split, type, end);
      on(split, 'keydown', (ev) => key(side, ev));
      on(split, 'dblclick', () => { resize(side, DEFAULTS[side]); save(); });
      on(hide, 'click', () => toggle(side, true));
      on(rail, 'click', () => toggle(side, false));
    }

    // -- the window: show again what the window allows now. A screen that has left the page stops listening.
    function refresh() {
      if (dead) return;
      if (seen && !body.isConnected) { destroy(); return; }
      apply();
    }
    if (view && typeof view.addEventListener === 'function') { view.addEventListener('resize', refresh); viewBound.push(['resize', refresh]); }
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(refresh) : null;
    if (observer) observer.observe(body);

    function destroy() {
      if (dead) return;
      dead = true;
      drag = null;
      for (const [el, type, fn] of bound) el.removeEventListener(type, fn);
      for (const [type, fn] of viewBound) view.removeEventListener(type, fn);
      if (observer) observer.disconnect();
      for (const side of SIDES) { const {col, split, hide, rail} = parts[side]; col.classList.remove('cw-collapsed'); split.remove(); hide.remove(); rail.remove(); }
      body.classList.remove('cw-dragging');
      body.removeAttribute('style');
    }

    apply();
    return {destroy, refresh, state: () => ({...effective(), leftHidden: pref.leftHidden, rightHidden: pref.rightHidden})};
  }

  return {mount, parse, clampWidths, limits, KEY, LIMITS, DEFAULTS, SPLIT, RAIL, CENTRE_MIN};
})();
