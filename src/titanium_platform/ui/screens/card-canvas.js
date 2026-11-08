/* Card canvas: one side of a business card drawn as a single SVG in millimetres (1 unit = 1 mm), where each element is selected, moved,
   resized, rotated, duplicated and deleted directly on the picture (feature-2, REQ-001 and REQ-002).

   The component draws what the server computed and reports what the operator did; it keeps no document of its own:

     const canvas = CardCanvas.create(hostElement, {onSelect, onMove, onResize, onRotate, onDelete, onDuplicate, onUndo, onRedo, onEscape});
     canvas.show({size_mm: {width, height}, elements: [...view elements...], selection: [ids], grid: true});

   A view element is {id, type, x, y, width, height, rotation, group, d, bounds, empty, problems, warnings, color?, raster?}: its centre, its box and
   its rotation in degrees (clockwise on screen) and the SVG path data (``d``, even-odd, card coordinates) of its final geometry. A picture engraved
   as a photo has ``raster`` ({url, width_px, height_px, dpi, dither, given}): it is drawn as that bitmap at its ``bounds`` (the rectangle of the
   picture; for a turned picture the bitmap is its bounding box), inside a dotted outline, instead of the path. List
   order is z-order (the last one is on top). Handlers are called only when a gesture finishes, with values in mm rounded to 0.01 and
   degrees rounded to 0.1. After each handler the screen sends the new state with ``show()``: it redraws everything and drops the
   provisional picture the canvas keeps after a gesture, so a refused edit is undone on the screen too. The drawing lives in an SVG whose
   viewBox starts PAD mm before the card (room for the rulers, the handles and the rotate handle). */
'use strict';
const CardCanvas = (() => {
  const NS = 'http://www.w3.org/2000/svg';
  const PAD = 10;                     // mm of room around the card inside the picture
  const CORNER_MM = 3;                // the rounded corners of the card outline
  const MIN_MM = 0.5;                 // the smallest width or height a resize leaves
  const MIN_PART_MM = 0.05;           // ... of a part of imported artwork, which may be a hairline (the server leaves 0.02)
  const GRID_MM = 0.1;                // a move is rounded to this grid (Alt switches it off)
  const SNAP_MM = 0.5;                // the card's edges and centre pull an element within this distance
  const MAJOR_MM = 10;                // the major lines of the grid and the ruler labels
  const DRAG_PX = 3;                  // the pointer must travel this far before a press becomes a drag
  const HIT_PX = 6;                   // the least tolerance (screen pixels) around thin outlines
  const HANDLE_PX = 10;               // the size of a handle on screen
  const HANDLE_PICK_PX = 8;           // the pointer takes a handle this near its centre
  const ROTATE_PX = 26;               // the distance of the rotate handle above the top edge, on screen
  const NUDGE_MM = 0.5;               // arrow keys; with Shift:
  const NUDGE_BIG_MM = 5;
  const ZOOM_MIN = 0.25, ZOOM_MAX = 16;
  const ASPECT_TYPES = new Set(['text', 'qr', 'icon', 'image']);   // these keep their proportions always, and offer corner handles only
  const BOX_TYPES = new Set(['text', 'qr', 'icon', 'image']);      // these are taken anywhere inside their box, not only on their ink
  const SIGNS = {nw: [-1, -1], n: [0, -1], ne: [1, -1], e: [1, 0], se: [1, 1], s: [0, 1], sw: [-1, 1], w: [-1, 0]};
  const CORNERS = ['nw', 'ne', 'se', 'sw'];
  const BASE_ANGLE = {n: 0, ne: 45, e: 90, se: 135, s: 180, sw: 225, w: 270, nw: 315};
  const CURSORS = ['ns', 'nesw', 'ew', 'nwse'];
  const LABEL = 'Card canvas. Click an element to select it and drag it to move it. Arrow keys move the selection by 0.5 mm, '
    + 'Shift with an arrow by 5 mm. Delete removes it, Ctrl+D duplicates it, Ctrl+Z undoes, Ctrl+Shift+Z redoes, Escape clears the selection.';

  // --- pure geometry: millimetres, y down, angles in degrees clockwise on screen ---------------------------------------------------
  const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const rad = (deg) => deg * Math.PI / 180;
  const r2 = (v) => Math.round(v * 100) / 100 || 0;                // 0.01 mm (and never -0)
  const r1 = (v) => Math.round(v * 10) / 10 || 0;                  // 0.1 degree
  const fmt = (v, digits = 3) => String(+Number(v).toFixed(digits));
  const turn = ([x, y], deg) => {
    const a = rad(deg), c = Math.cos(a), s = Math.sin(a);
    return [x * c - y * s, x * s + y * c];
  };
  const place = (el) => ({x: num(el.x), y: num(el.y), width: Math.max(0, num(el.width)), height: Math.max(0, num(el.height)), rotation: num(el.rotation)});
  /** A point of the element's own frame (centre 0, 0, unrotated) on the card. */
  const toWorld = (el, p) => {
    const [x, y] = turn(p, num(el.rotation));
    return [num(el.x) + x, num(el.y) + y];
  };
  /** A point of the card in the element's own frame. */
  const toLocal = (el, p) => turn([p[0] - num(el.x), p[1] - num(el.y)], -num(el.rotation));
  /** The four corners of an element's box on the card: top-left, top-right, bottom-right, bottom-left of the unrotated box. */
  function orientedBox(el) {
    const w = num(el.width) / 2, h = num(el.height) / 2;
    return [[-w, -h], [w, -h], [w, h], [-w, h]].map((p) => toWorld(el, p));
  }
  /** The smallest upright rectangle [x0, y0, x1, y1] around a list of points. */
  const rectOf = (points) => [Math.min(...points.map((p) => p[0])), Math.min(...points.map((p) => p[1])),
    Math.max(...points.map((p) => p[0])), Math.max(...points.map((p) => p[1]))];
  const aabb = (el) => rectOf(orientedBox(el));
  /** Where a pointer at client coordinates is on the card, in mm. ``rect`` is the client rectangle of the drawing, ``size_mm`` the card;
      ``zoom`` is the drawing's scale in screen pixels per mm (null: taken from ``rect`` and the card, as an SVG that meets its box does).
      The picture shows ``pad`` mm around the card. */
  function pointToMm(clientX, clientY, rect, size_mm, zoom, pad = PAD) {
    const vw = size_mm.width + 2 * pad, vh = size_mm.height + 2 * pad;
    const s = zoom > 0 ? zoom : (Math.min(rect.width / vw, rect.height / vh) || 1);
    return [(clientX - rect.left - (rect.width - vw * s) / 2) / s - pad, (clientY - rect.top - (rect.height - vh * s) / 2) / s - pad];
  }
  /** The client coordinates of a point of the card (the inverse of pointToMm). */
  function mmToClient(x, y, rect, size_mm, zoom, pad = PAD) {
    const vw = size_mm.width + 2 * pad, vh = size_mm.height + 2 * pad;
    const s = zoom > 0 ? zoom : (Math.min(rect.width / vw, rect.height / vh) || 1);
    return [rect.left + (rect.width - vw * s) / 2 + (x + pad) * s, rect.top + (rect.height - vh * s) / 2 + (y + pad) * s];
  }
  /** Where the handles of an element are on the card: the eight compass points of its box and ``rotate``, ``rotateMm`` above the top edge. */
  function handlePositions(el, rotateMm = 6) {
    const w = num(el.width) / 2, h = num(el.height) / 2, out = {};
    for (const [name, [sx, sy]] of Object.entries(SIGNS)) out[name] = toWorld(el, [sx * w, sy * h]);
    out.rotate = toWorld(el, [0, -h - rotateMm]);
    return out;
  }
  /** The handles an element offers at ``scale`` screen pixels per mm, rotate last: corners for every type, edges for the types that
      resize freely (and are long enough on screen not to bury the element under handles). */
  function handleNames(el, scale = 1) {
    const names = [...CORNERS];
    if (!ASPECT_TYPES.has(el.type)) {
      if (num(el.width) * scale >= 4 * HANDLE_PX) names.push('n', 's');
      if (num(el.height) * scale >= 4 * HANDLE_PX) names.push('e', 'w');
    }
    return [...names, 'rotate'];
  }
  /** The box an element has when its ``handle`` is dragged to ``pointMm``: the opposite handle (the anchor) stays where it is on the card,
      whatever the rotation. ``keepAspect`` keeps the proportions (a corner follows the diagonal); ``minMm`` is the least width and height. */
  function resizeFromHandle(el, handle, pointMm, opts = {}) {
    const here = place(el), sign = SIGNS[handle];
    if (!sign) return {x: here.x, y: here.y, width: here.width, height: here.height};
    const [sx, sy] = sign, minMm = opts.minMm == null ? MIN_MM : opts.minMm;
    const w = here.width, h = here.height;
    const keep = !!opts.keepAspect && w > 1e-6 && h > 1e-6;
    const p = toLocal(here, pointMm);
    const ax = -sx * w / 2, ay = -sy * h / 2;                  // the anchor, in the element's frame
    let nw = sx ? sx * (p[0] - ax) : w, nh = sy ? sy * (p[1] - ay) : h;
    if (keep) {
      let k;
      if (sx && sy) {                                           // the corner slides along its diagonal
        const dx = sx * w, dy = sy * h;
        k = ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy);
      } else k = sx ? nw / w : nh / h;
      k = Math.max(k, minMm / Math.min(w, h));
      nw = w * k; nh = h * k;
    } else {
      if (sx) nw = Math.max(nw, minMm);
      if (sy) nh = Math.max(nh, minMm);
    }
    const [x, y] = toWorld(here, [ax + sx * nw / 2, ay + sy * nh / 2]);
    return {x, y, width: nw, height: nh};
  }
  /** The angle in (-180, 180]. */
  function normalizeAngle(deg) {
    const a = ((deg % 360) + 360) % 360;
    return (a > 180 ? a - 360 : a) || 0;
  }
  /** The rotation that points the element's rotate handle at ``pointMm`` (0: up, 90: right), rounded to ``stepDeg`` when it is above 0.
      ``offsetDeg`` is how far the pointer was from the handle's own direction when it grabbed it, so that the box does not jump. */
  function rotationFromPoint(el, pointMm, stepDeg = 0, offsetDeg = 0) {
    const dx = pointMm[0] - num(el.x), dy = pointMm[1] - num(el.y);
    if (Math.hypot(dx, dy) < 1e-9) return num(el.rotation);
    let a = Math.atan2(dx, -dy) * 180 / Math.PI - offsetDeg;
    if (stepDeg > 0) a = Math.round(a / stepDeg) * stepDeg;
    return normalizeAngle(a);
  }
  /** One axis of a soft snap: the edges and the centre of the moving box against the card's edges and centre. */
  function pull(low, high, size) {
    let best = null;
    for (const edge of [low, (low + high) / 2, high]) {
      for (const at of [0, size / 2, size]) {
        const d = at - edge;
        if (Math.abs(d) <= SNAP_MM && (!best || Math.abs(d) < Math.abs(best.d))) best = {d, at};
      }
    }
    return best;
  }
  /** A move of ``el`` by (dx, dy) as the canvas allows it: the card's edges and centre pull the element's box within 0.5 mm (``guides``
      lists the lines it sits on), otherwise the movement is rounded to the 0.1 mm grid. ``enabled`` false (Alt held) leaves it as it is. */
  function snapMove(el, dx, dy, size_mm, enabled) {
    if (!enabled) return {dx, dy, guides: []};
    const box = aabb(el), guides = [];
    const axis = (low, high, size, delta, name) => {
      const hit = pull(low + delta, high + delta, size);
      if (hit) { guides.push({axis: name, at: hit.at}); return delta + hit.d; }
      return Math.round(delta / GRID_MM) * GRID_MM;
    };
    const ox = axis(box[0], box[2], size_mm.width, dx, 'x');
    const oy = axis(box[1], box[3], size_mm.height, dy, 'y');
    return {dx: +ox.toFixed(6), dy: +oy.toFixed(6), guides};
  }

  // --- paths: the server's even-odd path data, read for hit tests -------------------------------------------------------------------
  const TOKEN = /[a-zA-Z]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?/g;
  const ARGS = {m: 2, l: 2, h: 1, v: 1, c: 6, s: 4, q: 4, t: 2, a: 7, z: 0};
  /** The rings of SVG path data: lists of points, one per sub-path. Only straight edges are exact (what the server writes); a curve
      is read as the line to its end point. */
  function parsePath(d) {
    const tokens = String(d || '').match(TOKEN) || [];
    const rings = [];
    let ring = null, x = 0, y = 0, x0 = 0, y0 = 0, cmd = '', i = 0;
    const flush = () => { if (ring && ring.length > 1) rings.push(ring); ring = null; };
    while (i < tokens.length) {
      if (/^[a-zA-Z]$/.test(tokens[i])) {
        cmd = tokens[i]; i += 1;
        if (cmd === 'Z' || cmd === 'z') { flush(); x = x0; y = y0; }
        continue;
      }
      const lower = cmd.toLowerCase(), n = ARGS[lower];
      if (!n) { i += 1; continue; }                              // numbers before any command, or after Z
      const a = tokens.slice(i, i + n).map(Number);
      if (a.length < n || a.some(Number.isNaN)) break;
      i += n;
      const rel = cmd === lower;
      let nx = x, ny = y;
      if (lower === 'h') nx = rel ? x + a[0] : a[0];
      else if (lower === 'v') ny = rel ? y + a[0] : a[0];
      else { nx = rel ? x + a[n - 2] : a[n - 2]; ny = rel ? y + a[n - 1] : a[n - 1]; }
      if (lower === 'm') { flush(); ring = [[nx, ny]]; x0 = nx; y0 = ny; cmd = rel ? 'l' : 'L'; }   // pairs after the first are lines
      else { if (!ring) ring = [[x, y]]; ring.push([nx, ny]); }
      x = nx; y = ny;
    }
    flush();
    return rings;
  }
  const RINGS = new Map();
  const ringsOf = (d) => {
    if (!d) return [];
    let rings = RINGS.get(d);
    if (!rings) {
      if (RINGS.size >= 128) RINGS.clear();
      rings = parsePath(d);
      RINGS.set(d, rings);
    }
    return rings;
  };
  /** Even-odd: whether the point is inside an odd number of rings. */
  function insideRings(rings, [px, py]) {
    let inside = false;
    for (const ring of rings) {
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [xi, yi] = ring[i], [xj, yj] = ring[j];
        if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi) inside = !inside;
      }
    }
    return inside;
  }
  function nearRings(rings, [px, py], tol) {
    for (const ring of rings) {
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [ax, ay] = ring[j], [bx, by] = ring[i], dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
        const k = len2 ? clamp(((px - ax) * dx + (py - ay) * dy) / len2, 0, 1) : 0;
        if (Math.hypot(px - ax - k * dx, py - ay - k * dy) <= tol) return true;
      }
    }
    return false;
  }
  /** Whether an element is under a point, ``tol`` mm of slack all round. Where the element has path data the point must be inside its
      ink or within ``tol`` of an edge (a hollow frame is not taken in its middle); text, QR codes, icons and images are also taken
      anywhere in their box, and so is an element without ink (empty, or without path data). */
  function hitElement(el, pt, tol) {
    const near = (r) => pt[0] >= r[0] - tol && pt[0] <= r[2] + tol && pt[1] >= r[1] - tol && pt[1] <= r[3] + tol;
    const bounds = Array.isArray(el.bounds) && el.bounds.length === 4 ? el.bounds.map(Number) : null;
    if (!near(aabb(el)) && !(bounds && near(bounds))) return false;
    const rings = ringsOf(el.d);
    if (!rings.length || BOX_TYPES.has(el.type)) {
      const [lx, ly] = toLocal(el, pt);
      if (Math.abs(lx) <= num(el.width) / 2 + tol && Math.abs(ly) <= num(el.height) / 2 + tol) return true;
    }
    return rings.length > 0 && (insideRings(rings, pt) || nearRings(rings, pt, tol));
  }
  /** The id of the topmost element under ``pointMm`` (the last of the list is on top), or null. */
  function hitTest(elements, pointMm, toleranceMm = 0) {
    for (let i = elements.length - 1; i >= 0; i--) if (hitElement(elements[i], pointMm, toleranceMm)) return elements[i].id;
    return null;
  }
  /** The matrix [a, b, c, d, e, f] that carries the picture drawn for ``el`` onto the box ``next`` (centre, size, rotation): what a move,
      a resize or a rotation looks like before the server has answered. */
  function previewMatrix(el, next) {
    const a = place(el), b = {...a, ...next};
    const sx = a.width > 1e-9 ? b.width / a.width : 1, sy = a.height > 1e-9 ? b.height / a.height : 1;
    const [c0, s0] = [Math.cos(rad(a.rotation)), Math.sin(rad(a.rotation))], [c1, s1] = [Math.cos(rad(b.rotation)), Math.sin(rad(b.rotation))];
    // linear part = R(next) * S * R(-old)
    const m = [[c1 * sx * c0 + -s1 * sy * -s0, c1 * sx * s0 + -s1 * sy * c0], [s1 * sx * c0 + c1 * sy * -s0, s1 * sx * s0 + c1 * sy * c0]];
    const e = b.x - (m[0][0] * a.x + m[0][1] * a.y), f = b.y - (m[1][0] * a.x + m[1][1] * a.y);
    return [m[0][0], m[1][0], m[0][1], m[1][1], e, f].map((v) => Math.round(v * 1e9) / 1e9 || 0);
  }
  const math = {pointToMm, mmToClient, orientedBox, handlePositions, handleNames, resizeFromHandle, rotationFromPoint, snapMove, hitTest,
    parsePath, previewMatrix, normalizeAngle};

  // --- the drawing -----------------------------------------------------------------------------------------------------------------------
  const CSS = `
.cc-stage{--cc-bg:var(--surface-2,#1b2638);--cc-card:#d9dde3;--cc-card-edge:#7f8999;--cc-ink:#1c2431;--cc-grid:rgba(40,52,70,.16);
  --cc-grid-major:rgba(40,52,70,.34);--cc-ruler:var(--muted,#a0acc0);--cc-sel:#2f6bff;--cc-sel-halo:#ffffff;--cc-warn:#e08a00;
  --cc-ghost:#7f8999;--cc-guide:#e5287a;position:relative;box-sizing:border-box;display:flex;width:100%;height:min(72vh,780px);
  min-height:300px;overflow:auto;background:var(--cc-bg);border:1px solid var(--line-2,#35435a);border-radius:12px;color:var(--cc-ink);outline:none}
.cc-stage:focus-visible{box-shadow:0 0 0 2px var(--accent,#a9b8ff)}
.cc-svg{display:block;flex:none;margin:auto;overflow:visible;touch-action:none;user-select:none;-webkit-user-select:none}
.cc-svg *{pointer-events:none}
.cc-svg .cc-ink,.cc-svg .cc-raster{pointer-events:fill;cursor:pointer}
.cc-svg .cc-selected .cc-ink,.cc-svg .cc-selected .cc-raster{cursor:move}
.cc-svg .cc-handle{pointer-events:all}
.cc-card{fill:var(--cc-card);stroke:var(--cc-card-edge);stroke-width:1px;vector-effect:non-scaling-stroke}
.cc-grid-minor,.cc-grid-major,.cc-tick{fill:none;vector-effect:non-scaling-stroke}
.cc-grid-minor{stroke:var(--cc-grid);stroke-width:.5px}
.cc-grid-major{stroke:var(--cc-grid-major);stroke-width:.75px}
.cc-tick{stroke:var(--cc-ruler);stroke-width:1px}
.cc-ruler{fill:var(--cc-ruler);font-family:var(--font,system-ui,sans-serif)}
.cc-note{fill:var(--cc-ruler);font-family:var(--font,system-ui,sans-serif);font-weight:600}
.cc-warn-box,.cc-ghost,.cc-raster-outline{fill:none;vector-effect:non-scaling-stroke}
.cc-raster-outline{stroke:var(--cc-ghost);stroke-width:1px;stroke-dasharray:1 3;stroke-linecap:round}
.cc-warn-box{stroke:var(--cc-warn);stroke-width:1.5px;stroke-dasharray:6 3}
.cc-ghost{stroke:var(--cc-ghost);stroke-width:1px;stroke-dasharray:3 3;opacity:.75}
.cc-sel-halo,.cc-sel-box,.cc-member,.cc-multi,.cc-stem,.cc-guide{fill:none;vector-effect:non-scaling-stroke}
.cc-sel-halo{stroke:var(--cc-sel-halo);stroke-width:4px;opacity:.7}
.cc-sel-box,.cc-multi{stroke:var(--cc-sel);stroke-width:1.5px}
.cc-multi{stroke-dasharray:6 3}
.cc-member{stroke:var(--cc-sel);stroke-width:1px;opacity:.8}
.cc-stem{stroke:var(--cc-sel);stroke-width:1px}
.cc-guide{stroke:var(--cc-guide);stroke-width:1px;stroke-dasharray:4 3}
.cc-handle{fill:#ffffff;stroke:var(--cc-sel);stroke-width:1.5px;vector-effect:non-scaling-stroke}
.cc-cur-ns{cursor:ns-resize}.cc-cur-ew{cursor:ew-resize}.cc-cur-nesw{cursor:nesw-resize}.cc-cur-nwse{cursor:nwse-resize}.cc-cur-rotate{cursor:grab}
`;
  let sequence = 0;
  function ensureStyle() {
    if (document.getElementById('cc-style')) return;
    const sheet = document.createElement('style');
    sheet.setAttribute('id', 'cc-style');
    sheet.textContent = CSS;
    (document.head || document.body).append(sheet);
  }
  const svgEl = (tag, attrs = {}) => {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v != null && v !== false) el.setAttribute(k, v);
    return el;
  };
  const points = (list) => list.map(([x, y]) => `${fmt(x)},${fmt(y)}`).join(' ');
  const key = (id) => String(id);
  const sameSet = (a, b) => a.length === b.length && a.every((k) => b.includes(k));

  /** Draws the card side into ``host``. ``handlers`` is read when a gesture finishes, so the screen may change it later. */
  function create(host, handlers = {}) {
    ensureStyle();
    const clipId = `cc-clip-${++sequence}`;
    let size = {width: 85, height: 54}, elements = [], byKey = new Map(), sel = [], grid = true;
    let zoom = 1, dead = false, gesture = null, pending = null, guides = [];
    const preview = new Map();                    // key -> {x, y, width, height, rotation}: what a gesture made, until the screen answers
    const groups = new Map();                     // key -> the <g> of the element

    const stage = document.createElement('div');
    stage.setAttribute('class', 'cc-stage');
    stage.setAttribute('tabindex', '0');
    stage.setAttribute('role', 'group');
    stage.setAttribute('aria-label', LABEL);
    const svg = svgEl('svg', {class: 'cc-svg', preserveAspectRatio: 'xMidYMid meet', 'aria-hidden': 'true'});
    const clip = svgEl('clipPath', {id: clipId});
    const clipRect = svgEl('rect', {x: 0, y: 0, rx: CORNER_MM, ry: CORNER_MM});
    clip.append(clipRect);
    const defs = svgEl('defs');
    defs.append(clip);
    const layerBg = svgEl('g', {class: 'cc-bg'}), layerEls = svgEl('g', {class: 'cc-els'}), layerOver = svgEl('g', {class: 'cc-over'});
    svg.append(defs, layerBg, layerEls, layerOver);
    const live = document.createElement('div');
    live.setAttribute('class', 'sr-only');
    live.setAttribute('role', 'status');
    live.setAttribute('aria-live', 'polite');
    stage.append(svg, live);
    host.append(stage);

    const call = (name, ...args) => { if (typeof handlers[name] === 'function') handlers[name](...args); };
    const ordered = (keys) => elements.filter((el) => keys.includes(key(el.id))).map((el) => el.id);   // in z-order
    const sorted = (keys) => elements.map((el) => key(el.id)).filter((k) => keys.includes(k));
    const effective = (el) => { const p = preview.get(key(el.id)); return p ? {...el, ...p} : el; };
    /** The provisional box of an element: the box it had before the gesture, changed by ``patch``. Always a whole box. */
    const setBox = (k, from, patch) => preview.set(k, {...place(from), ...patch});
    const shown = () => elements.map(effective);
    const groupKeys = (k) => {
      const g = byKey.get(k) && byKey.get(k).group;
      return g ? elements.filter((el) => el.group === g).map((el) => key(el.id)) : [k];
    };

    /** Screen pixels per mm of the drawing as it is on the page. */
    function scale() {
      const vw = size.width + 2 * PAD, vh = size.height + 2 * PAD, r = svg.getBoundingClientRect();
      const s = Math.min(r.width / vw, r.height / vh);
      if (s > 0) return s;
      return Number(svg.getAttribute('width')) / vw || 1;
    }
    const toMm = (ev) => pointToMm(ev.clientX, ev.clientY, svg.getBoundingClientRect(), size, null);

    /** The picture's box and size: the card at the fit scale times the zoom. */
    function layout() {
      const vw = size.width + 2 * PAD, vh = size.height + 2 * PAD, r = stage.getBoundingClientRect();
      const room = {width: stage.clientWidth || r.width, height: stage.clientHeight || r.height};
      let fit = Math.min(room.width / vw, room.height / vh);
      if (!(fit > 0)) fit = 1;                     // not on screen yet: the observer lays it out again once it is
      svg.setAttribute('viewBox', `${-PAD} ${-PAD} ${fmt(vw)} ${fmt(vh)}`);
      svg.setAttribute('width', String(Math.max(1, Math.floor(vw * fit * zoom))));
      svg.setAttribute('height', String(Math.max(1, Math.floor(vh * fit * zoom))));
    }

    function drawBackground() {
      const {width: W, height: H} = size, s = scale(), px = (n) => n / s;
      clipRect.setAttribute('width', fmt(W));
      clipRect.setAttribute('height', fmt(H));
      const nodes = [svgEl('rect', {class: 'cc-card', x: 0, y: 0, width: fmt(W), height: fmt(H), rx: CORNER_MM, ry: CORNER_MM})];
      if (grid) {
        const minor = [], major = [];
        for (let x = 0; x <= W + 1e-9; x += 1) (x % MAJOR_MM === 0 ? major : minor).push(`M${fmt(x)} 0V${fmt(H)}`);
        for (let y = 0; y <= H + 1e-9; y += 1) (y % MAJOR_MM === 0 ? major : minor).push(`M0 ${fmt(y)}H${fmt(W)}`);
        const lines = (cls, parts) => svgEl('path', {class: cls, d: parts.join(''), 'clip-path': `url(#${clipId})`});
        if (s >= 8) nodes.push(lines('cc-grid-minor', minor));          // a millimetre grid only where the lines are apart enough to read
        nodes.push(lines('cc-grid-major', major));
      }
      const step = s >= 3 ? MAJOR_MM : 2 * MAJOR_MM, font = fmt(px(10), 4), ticks = [];
      const label = (attrs, content) => { const t = svgEl('text', attrs); t.textContent = content; return t; };
      for (let x = 0; x <= W + 1e-9; x += step) {
        ticks.push(`M${fmt(x)} ${fmt(-px(5))}V0`);
        nodes.push(label({class: 'cc-ruler', x: fmt(x), y: fmt(-px(8)), 'text-anchor': 'middle', 'font-size': font}, String(x)));
      }
      for (let y = step; y <= H + 1e-9; y += step) {
        ticks.push(`M${fmt(-px(5))} ${fmt(y)}H0`);
        nodes.push(label({class: 'cc-ruler', x: fmt(-px(8)), y: fmt(y), dy: '0.35em', 'text-anchor': 'end', 'font-size': font}, String(y)));
      }
      nodes.push(svgEl('path', {class: 'cc-tick', d: ticks.join('')}),
        label({class: 'cc-note', x: 0, y: fmt(H + px(20)), 'font-size': fmt(px(12), 4)}, `${fmt(W, 2)} × ${fmt(H, 2)} mm`));
      layerBg.replaceChildren(...nodes);
    }

    /** A picture engraved as a photo: its bitmap's url and the rectangle it lies on, or null (a traced picture, or nothing to engrave). */
    const rasterOf = (el) => {
      const r = el.raster, b = Array.isArray(el.bounds) && el.bounds.length === 4 ? el.bounds.map(Number) : null;
      return r && r.url && b && b.every(Number.isFinite) && b[2] > b[0] && b[3] > b[1] ? {url: String(r.url), box: b} : null;
    };
    const classesOf = (el, selected) => ['cc-el', `cc-el-${el.type}`, selected && 'cc-selected', Array.isArray(el.warnings) && el.warnings.length && 'cc-has-warning',
      el.empty && 'cc-empty', Array.isArray(el.problems) && el.problems.length && 'cc-has-problems', rasterOf(el) && 'cc-el-raster'].filter(Boolean).join(' ');
    function drawElements() {
      groups.clear();
      const nodes = elements.map((el) => {
        const k = key(el.id), warnings = Array.isArray(el.warnings) ? el.warnings : [], problems = Array.isArray(el.problems) ? el.problems : [];
        const g = svgEl('g', {class: classesOf(el, sel.includes(k)), 'data-id': String(el.id)});
        const raster = rasterOf(el);
        if (raster) {                                   // a photo: the dithered bitmap where the picture lies, not the filled rectangle of its path
          const [x0, y0, x1, y1] = raster.box;
          g.append(svgEl('image', {class: 'cc-raster', href: raster.url, x: fmt(x0), y: fmt(y0), width: fmt(x1 - x0), height: fmt(y1 - y0), preserveAspectRatio: 'none'}),
            svgEl('rect', {class: 'cc-raster-outline', x: fmt(x0), y: fmt(y0), width: fmt(x1 - x0), height: fmt(y1 - y0)}));
        } else if (el.d) g.append(svgEl('path', {class: 'cc-ink', d: el.d, 'fill-rule': 'evenodd', fill: el.color || 'currentColor'}));
        const note = [...problems, ...warnings.map((w) => w.message || w.code),
          raster && el.raster.given === false ? 'Plain grey preview: the engraving settings give no line interval or image mode yet' : null].filter(Boolean).join('; ');
        if (warnings.length) {
          const b = Array.isArray(el.bounds) && el.bounds.length === 4 ? el.bounds.map(Number) : aabb(el), m = 0.3;
          g.append(svgEl('rect', {class: 'cc-warn-box', x: fmt(b[0] - m), y: fmt(b[1] - m), width: fmt(b[2] - b[0] + 2 * m), height: fmt(b[3] - b[1] + 2 * m)}));
        }
        if (el.empty || problems.length || !el.d) g.append(svgEl('polygon', {class: 'cc-ghost', points: points(orientedBox(el))}));
        if (note) { const title = svgEl('title'); title.textContent = note; g.append(title); }
        groups.set(k, g);
        return g;
      });
      layerEls.replaceChildren(...nodes);
    }
    function applyPreview() {
      for (const [k, g] of groups) {
        const p = preview.get(k);
        if (p) g.setAttribute('transform', `matrix(${previewMatrix(byKey.get(k), p).map((v) => fmt(v, 6)).join(' ')})`);
        else g.removeAttribute('transform');
      }
    }
    function markSelection() {
      for (const [k, g] of groups) g.classList.toggle('cc-selected', sel.includes(k));
    }

    const unionBox = (list) => {
      const [x0, y0, x1, y1] = rectOf(list.flatMap(orientedBox));
      return {x: (x0 + x1) / 2, y: (y0 + y1) / 2, width: x1 - x0, height: y1 - y0, rotation: 0};
    };
    const chosen = () => sel.filter((k) => byKey.has(k)).map((k) => effective(byKey.get(k)));
    function drawOverlay() {
      const nodes = [], s = scale(), list = chosen();
      if (list.length === 1) {
        const el = list[0], corners = orientedBox(el), pos = handlePositions(el, ROTATE_PX / s), hs = HANDLE_PX / s, rot = num(el.rotation);
        nodes.push(svgEl('polygon', {class: 'cc-sel-halo', points: points(corners)}), svgEl('polygon', {class: 'cc-sel-box', points: points(corners)}));
        const top = toWorld(el, [0, -num(el.height) / 2]);
        nodes.push(svgEl('line', {class: 'cc-stem', x1: fmt(top[0]), y1: fmt(top[1]), x2: fmt(pos.rotate[0]), y2: fmt(pos.rotate[1])}));
        for (const name of handleNames(el, s)) {
          const [x, y] = pos[name], turned = rot ? `rotate(${fmt(rot)} ${fmt(x)} ${fmt(y)})` : null;
          if (name === 'rotate') nodes.push(svgEl('circle', {class: 'cc-handle cc-cur-rotate', 'data-handle': name, cx: fmt(x), cy: fmt(y), r: fmt(hs / 2 + 0.5 / s)}));
          else {
            const bucket = Math.round((BASE_ANGLE[name] + rot) / 45);
            nodes.push(svgEl('rect', {class: `cc-handle cc-cur-${CURSORS[((bucket % 4) + 4) % 4]}`, 'data-handle': name, x: fmt(x - hs / 2), y: fmt(y - hs / 2),
              width: fmt(hs), height: fmt(hs), transform: turned}));
          }
        }
      } else if (list.length > 1) {
        for (const el of list) nodes.push(svgEl('polygon', {class: 'cc-member', points: points(orientedBox(el))}));
        const b = unionBox(list);
        nodes.push(svgEl('rect', {class: 'cc-multi', x: fmt(b.x - b.width / 2), y: fmt(b.y - b.height / 2), width: fmt(b.width), height: fmt(b.height)}));
      }
      for (const g of guides) {
        nodes.push(g.axis === 'x' ? svgEl('line', {class: 'cc-guide', x1: fmt(g.at), y1: -PAD, x2: fmt(g.at), y2: fmt(size.height + PAD)})
          : svgEl('line', {class: 'cc-guide', x1: -PAD, y1: fmt(g.at), x2: fmt(size.width + PAD), y2: fmt(g.at)}));
      }
      layerOver.replaceChildren(...nodes);
    }
    function announce() {
      const list = chosen();
      live.textContent = !list.length ? '' : list.length > 1 ? `${list.length} elements selected`
        : `${list[0].name || list[0].type} selected: ${fmt(list[0].width, 2)} × ${fmt(list[0].height, 2)} mm at ${fmt(list[0].x, 2)}, ${fmt(list[0].y, 2)}, rotation ${fmt(num(list[0].rotation), 1)}°`;
    }
    const redrawScale = () => { drawBackground(); drawOverlay(); };

    /** The whole picture from a view: the card, the grid, the elements, the selection. */
    function apply(view) {
      if (view.size_mm && view.size_mm.width > 0 && view.size_mm.height > 0) size = {width: Number(view.size_mm.width), height: Number(view.size_mm.height)};
      elements = Array.isArray(view.elements) ? view.elements.filter(Boolean) : [];
      byKey = new Map(elements.map((el) => [key(el.id), el]));
      if (view.grid !== undefined) grid = !!view.grid;
      sel = sorted((Array.isArray(view.selection) ? view.selection.map(key) : sel).filter((k) => byKey.has(k)));
      preview.clear();
      layout();
      drawBackground();
      drawElements();
      drawOverlay();
      announce();
    }
    function show(view = {}) {
      if (dead) return;
      if (gesture) { pending = view; return; }       // never under the pointer that is dragging: it is drawn when the gesture ends
      apply(view);
    }
    function setSelection(ids) {
      if (dead) return;
      sel = sorted((ids || []).map(key).filter((k) => byKey.has(k)));
      markSelection();
      drawOverlay();
      announce();
    }

    // --- zoom ----------------------------------------------------------------------------------------------------------------------------
    function zoomAt(next, clientX, clientY) {
      next = clamp(next, ZOOM_MIN, ZOOM_MAX);
      if (next === zoom) return;
      const r0 = stage.getBoundingClientRect();
      const cx = clientX == null ? r0.left + r0.width / 2 : clientX, cy = clientY == null ? r0.top + r0.height / 2 : clientY;
      const at = pointToMm(cx, cy, svg.getBoundingClientRect(), size, null);
      zoom = next;
      layout();
      redrawScale();
      const back = mmToClient(at[0], at[1], svg.getBoundingClientRect(), size, null);       // the same millimetre stays under the pointer
      stage.scrollLeft = (stage.scrollLeft || 0) + back[0] - cx;
      stage.scrollTop = (stage.scrollTop || 0) + back[1] - cy;
      call('onZoom', zoom);
    }
    const setZoom = (factor) => { if (!dead) zoomAt(Number(factor) || 1); };
    function fit() {
      if (dead) return;
      zoom = 1;
      layout();
      redrawScale();
      stage.scrollLeft = 0;
      stage.scrollTop = 0;
      call('onZoom', zoom);
    }

    // --- gestures ------------------------------------------------------------------------------------------------------------------------
    const capture = (ev) => { try { stage.setPointerCapture(ev.pointerId); } catch (_) { /* the pointer is already gone */ } };
    const release = (id) => { try { if (stage.releasePointerCapture) stage.releasePointerCapture(id); } catch (_) { /* already released */ } };

    function onDown(ev) {
      if (dead || (ev.button != null && ev.button !== 0) || ev.isPrimary === false) return;
      if (gesture) {                                  // another finger is ignored; the same pointer pressing again means its release was lost
        if (ev.pointerId !== gesture.pointer) return;
        cancel();
      }
      if (stage.focus) stage.focus({preventScroll: true});
      const pt = toMm(ev), s = scale(), list = shown();
      const base = {pointer: ev.pointerId, x: ev.clientX, y: ev.clientY, startSel: [...sel], active: false, start: pt};
      const sole = sel.length === 1 && byKey.has(sel[0]) ? effective(byKey.get(sel[0])) : null;
      if (sole) {
        const pos = handlePositions(sole, ROTATE_PX / s);
        let name = null, best = HANDLE_PICK_PX / s;
        for (const candidate of handleNames(sole, s)) {
          const d = Math.hypot(pos[candidate][0] - pt[0], pos[candidate][1] - pt[1]);
          if (d <= best) { name = candidate; best = d; }
        }
        if (name) {
          gesture = {...base, kind: name === 'rotate' ? 'rotate' : 'resize', key: sel[0], handle: name, from: sole,
            grab: [pos[name][0] - pt[0], pos[name][1] - pt[1]], offset: name === 'rotate' ? rotationFromPoint({...sole, rotation: 0}, pt) - num(sole.rotation) : 0};
          capture(ev);
          return;
        }
      }
      const hit = hitTest(list, pt, HIT_PX / s);
      const toggle = !!(ev.shiftKey || ev.metaKey || ev.ctrlKey);
      gesture = {...base, kind: 'press', hit: hit == null ? null : key(hit), toggle};
      if (hit != null && !toggle && !sel.includes(key(hit))) {      // a press on an element that is not selected selects it at once
        sel = sorted(groupKeys(key(hit)));
        markSelection(); drawOverlay();
      }
      capture(ev);
    }

    /** The press has become a drag of the selection (or of the pressed element when it was not in it). */
    function beginMove(g) {
      if (g.hit != null) {
        const ids = groupKeys(g.hit);
        if (g.toggle) { if (!ids.every((k) => sel.includes(k))) sel = sorted([...new Set([...sel, ...ids])]); }
        else if (!ids.some((k) => sel.includes(k))) sel = sorted(ids);
        markSelection();
      }
      g.ids = [...sel];
      g.from = new Map(g.ids.map((k) => [k, effective(byKey.get(k))]));
      const list = [...g.from.values()];
      g.box = list.length === 1 ? list[0] : unionBox(list);
    }

    function onMove(ev) {
      if (dead || !gesture || ev.pointerId !== gesture.pointer) return;
      const g = gesture, pt = toMm(ev);
      if (!g.active) {
        if (Math.hypot(ev.clientX - g.x, ev.clientY - g.y) < DRAG_PX) return;
        g.active = true;
        if (g.kind === 'press') { if (g.hit == null) return; beginMove(g); }
      }
      if (g.kind === 'press') {
        if (g.hit == null) return;
        const snapped = snapMove(g.box, pt[0] - g.start[0], pt[1] - g.start[1], size, !ev.altKey);
        g.dx = snapped.dx; g.dy = snapped.dy; guides = snapped.guides;
        for (const [k, el] of g.from) setBox(k, el, {x: num(el.x) + g.dx, y: num(el.y) + g.dy});
      } else if (g.kind === 'resize') {
        const keep = ASPECT_TYPES.has(g.from.type) || !!ev.shiftKey;
        setBox(g.key, g.from, resizeFromHandle(g.from, g.handle, [pt[0] + g.grab[0], pt[1] + g.grab[1]], {keepAspect: keep, minMm: g.from.type === 'vector' ? MIN_PART_MM : MIN_MM}));
      } else setBox(g.key, g.from, {rotation: rotationFromPoint(g.from, pt, ev.shiftKey ? 15 : 1, g.offset)});
      applyPreview();
      drawOverlay();
    }

    /** What the finished gesture tells the screen, as [handler, ...arguments]; the picture keeps the result until the screen answers. */
    function conclude(g) {
      const calls = [];
      if (g.kind === 'press') {
        if (!g.active) {                                              // a click
          if (g.hit != null) {
            const ids = groupKeys(g.hit);
            sel = g.toggle ? (ids.every((k) => sel.includes(k)) ? sel.filter((k) => !ids.includes(k)) : [...sel, ...ids]) : ids;
          } else if (!g.toggle) sel = [];
          sel = sorted(sel);
        }
        if (!sameSet(sel, g.startSel)) calls.push(['onSelect', ordered(sel)]);
        if (g.active && g.hit != null) {
          if (r2(g.dx || 0) || r2(g.dy || 0)) calls.push(['onMove', ordered(g.ids), r2(g.dx), r2(g.dy)]);
          else for (const k of g.ids) preview.delete(k);
        }
      } else if (preview.has(g.key)) {
        const next = {...g.from, ...preview.get(g.key)};
        if (g.kind === 'resize') calls.push(['onResize', byKey.get(g.key).id, {x: r2(next.x), y: r2(next.y), width: r2(next.width), height: r2(next.height)}]);
        else if (next.rotation !== num(g.from.rotation)) calls.push(['onRotate', byKey.get(g.key).id, r1(next.rotation)]);
        else preview.delete(g.key);
      }
      return calls;
    }
    function finish(ev) {
      const g = gesture;
      gesture = null; guides = [];
      release(ev.pointerId);
      const calls = conclude(g);
      markSelection();
      if (pending) {                                                  // a screen update that came in during the gesture
        const next = pending, kept = new Map(preview);
        pending = null;
        apply(next);
        for (const [k, v] of kept) if (byKey.has(k)) preview.set(k, v);
      }
      applyPreview(); drawOverlay(); announce();
      for (const [name, ...args] of calls) call(name, ...args);
    }
    function onUp(ev) {
      if (dead || !gesture || ev.pointerId !== gesture.pointer) return;
      finish(ev);
    }
    /** The gesture is dropped (Escape, a lost pointer): nothing is reported and the picture goes back. */
    function cancel() {
      const g = gesture;
      gesture = null; guides = [];
      if (!g) return;
      release(g.pointer);
      for (const k of (g.ids || [g.key])) preview.delete(k);
      sel = sorted(g.startSel.filter((k) => byKey.has(k)));
      if (pending) { const next = pending; pending = null; apply(next); }
      markSelection(); applyPreview(); drawOverlay(); announce();
    }

    // --- keyboard and wheel --------------------------------------------------------------------------------------------------------------
    function onKey(ev) {
      if (dead) return;
      const ids = ordered(sel), mod = ev.ctrlKey || ev.metaKey, name = ev.key, letter = String(name || '').toLowerCase();
      if (name === 'Escape') {
        if (gesture) { cancel(); ev.preventDefault(); return; }
        const had = sel.length > 0;
        sel = [];
        markSelection(); drawOverlay(); announce();
        if (had) call('onSelect', []);
        call('onEscape');
        return;
      }
      if (gesture) return;
      const step = ev.shiftKey ? NUDGE_BIG_MM : NUDGE_MM;
      const arrow = {ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step]}[name];
      if (arrow && !mod && ids.length) {
        ev.preventDefault();
        for (const k of sel) { const el = effective(byKey.get(k)); setBox(k, el, {x: num(el.x) + arrow[0], y: num(el.y) + arrow[1]}); }
        applyPreview(); drawOverlay();
        call('onMove', ids, arrow[0], arrow[1]);
      } else if ((name === 'Delete' || name === 'Backspace') && ids.length && !mod) {
        ev.preventDefault();
        call('onDelete', ids);
      } else if (mod && (letter === 'd' || ev.code === 'KeyD') && !ev.shiftKey) {
        ev.preventDefault();                                          // not the browser's «bookmark this page»
        if (ids.length) call('onDuplicate', ids);
      } else if (mod && (letter === 'z' || ev.code === 'KeyZ')) {
        ev.preventDefault();
        call(ev.shiftKey ? 'onRedo' : 'onUndo');
      } else if (mod && (letter === 'y' || ev.code === 'KeyY') && !ev.shiftKey) {
        ev.preventDefault();
        call('onRedo');
      }
    }
    /** A double click picks the element under the pointer out of its group (a part of an imported artwork); on an element without a group it changes nothing. */
    function onDouble(ev) {
      if (dead || ev.isPrimary === false) return;
      const s = scale(), hit = hitTest(shown(), toMm(ev), HIT_PX / s);
      if (hit == null) return;
      const only = [key(hit)];
      if (sameSet(sel, only)) return;
      sel = sorted(only);
      markSelection(); drawOverlay(); announce();
      call('onSelect', ordered(sel));
    }
    function onWheel(ev) {
      if (dead || !(ev.ctrlKey || ev.metaKey)) return;               // a plain wheel scrolls the page, as everywhere
      ev.preventDefault();
      const delta = (ev.deltaY || 0) * (ev.deltaMode === 1 ? 16 : 1);
      zoomAt(zoom * Math.exp(-delta * 0.0025), ev.clientX, ev.clientY);
    }

    const bound = [[stage, 'pointerdown', onDown], [stage, 'pointermove', onMove], [stage, 'pointerup', onUp], [stage, 'pointercancel', cancel],
      [stage, 'lostpointercapture', cancel], [stage, 'dblclick', onDouble], [stage, 'keydown', onKey], [stage, 'wheel', onWheel, {passive: false}]];
    for (const [target, type, fn, opts] of bound) target.addEventListener(type, fn, opts);
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(() => { if (!dead) { layout(); redrawScale(); } }) : null;
    if (observer) observer.observe(stage);

    function destroy() {
      if (dead) return;
      dead = true;
      gesture = null; pending = null;
      for (const [target, type, fn, opts] of bound) target.removeEventListener(type, fn, opts);
      if (observer) observer.disconnect();
      stage.remove();
    }
    apply({});
    return {show, setSelection, getSelection: () => ordered(sel), fit, setZoom, getZoom: () => zoom, focus: () => stage.focus(), destroy, element: stage};
  }

  return {create, math};
})();
