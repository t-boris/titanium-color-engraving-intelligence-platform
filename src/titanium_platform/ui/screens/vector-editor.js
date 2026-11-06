/* Vector color editor: measured recipes, regions, photo zones, selection, and accessible controls. */
'use strict';
const VectorEditor = (() => {
  const {h, fill, btn, get, pill, toast, num, labText, steadiness, STEADY, originText} = App;
  const NS = 'http://www.w3.org/2000/svg';
  const EXCLUDED = '#e6e6e6';                 // excluded areas are not engraved; only cleaning remains
  const MISSING = '#d32f2f';                  // the selected titanium color is no longer measured: hatch it
  const BASIS = {chart: 'reference card', clean: 'clean titanium', 'as-shot': 'as photographed, unreferenced'};
  const TOOLS = [['brush', 'Brush'], ['pipette', 'Eyedropper'], ['select', 'Selection']];
  const SCOPES = [['region', 'Region'], ['colour', 'Entire source color'], ['fill', 'Fill similar']];
  const VIEWS = [['titanium', 'Titanium'], ['source', 'Source colors'], ['original', 'Original']];
  const PAN = [['←', 'left', -1, 0], ['↑', 'up', 0, -1], ['↓', 'down', 0, 1], ['→', 'right', 1, 0]];   // the view moves by a fifth of itself
  const SIMILARITY = 8;                       // default ΔE for filling similar regions
  const SEE_THROUGH = 'rgba(0,0,0,0)';        // photo-zone region: show the image beneath while keeping hover and click active
  const LASSO_STEP = 3;                       // screen pixels between lasso points
  const svgCache = new Map();
  const paletteCache = new Map();
  const nearCache = new Map();
  const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;
  const chip = (c, title) => h('span', {class: 'sw', style: `background:${rgb(c)}`, title: title || ''});
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 1)} kHz · ${num(p.speed, 0)} mm/s · Q-Pulse ${num(p.pulse_width, 0)} ns`
    + (p.line_interval == null ? '' : ` · interval ${num(p.line_interval, 3)} mm`) + ` · ${p.passes ?? 1} passes` + (p.cross_hatch ? ' · cross-hatch' : '');
  const seconds = (s) => (s == null ? 'not estimated' : num(s, 1) + ' s/cm²');
  const mmList = (list) => list.map((v) => num(v, 1)).join(' and ') + ' mm';
  /** Layer row length (DEC-107): a brief indicator warns when the recipe color was not measured at that length. */
  function sizeNote(size) {
    const says = sizeSays(size);
    // on a line of the layers' list: muted when the colour was measured at this length, in the warning colour when it was not
    return says ? h('span', {class: 'vw-rows ' + (size.how === 'measured' ? 'muted' : 'warn vw-bad'), title: says, 'aria-label': says}, `↔ ${num(size.row_mm, 1)} mm`) : null;
  }
  function sizeSays(size) {
    if (!size || size.row_mm == null) return null;
    const rows = `rows ${num(size.row_mm, 1)} mm`;
    return size.how === 'measured' ? `${rows}: recipe color measured at ${mmList(size.from_mm)}`
      : size.how === 'between' ? `${rows}: color interpolated between measurements at ${mmList(size.from_mm)}`
        : size.how === 'outside' ? `${rows}: recipe color measured at ${mmList(size.measured_mm)}, not at this length; the titanium color may differ`
          : `${rows}: the measurement row length for this recipe color is unknown`;
  }
  /** A control on a line of a list (a box to tick, a swatch to press) works by itself: its click, Enter or Space does not open the line. */
  function inRow(el) {
    el.addEventListener('click', (ev) => ev.stopPropagation());
    el.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') ev.stopPropagation(); });
    return el;
  }
  const titled = (el, text) => { el.title = text; return el; };
  const SIZE_ABOUT = 'Titanium color depends on fill-row length (DEC-107): the laser returns after each row, and for short rows the titanium '
    + 'has less time to cool. Layer color uses the measurement at its row length, an interpolation between measurements, or the nearest measurement outside the measured sizes; '
    + 'in the latter case the resulting titanium color may differ. The Fill size plate measures recipes at the needed widths.';
  const de = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);       // CIE76, as on the server
  const PALETTE_PAGE = 60;                         // squares of the palette shown at once, the nearest first
  const duration = (s) => (s == null ? 'not estimated' : s >= 3600 ? `${Math.floor(s / 3600)} h ${String(Math.round(s % 3600 / 60)).padStart(2, '0')} min`
    : s >= 60 ? `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s` : `${Math.round(s)} s`);
  const area = (mm2) => (mm2 == null ? '—' : mm2 >= 100 ? `${num(mm2 / 100, 2)} cm²` : `${num(mm2, 1)} mm²`);
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const setClass = (el, cls, on) => (on ? el.classList.add(cls) : el.classList.remove(cls));
  const mark = (set, value, on) => (on ? set.add(value) : set.delete(value));
  const same = (a, b) => a != null && b != null && String(a) === String(b);   // palette color identifiers are compared as strings
  const svgEl = (tag, attrs) => {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  };

  /** How a list of source colours is narrowed and sorted: the editor's «Colors» and the window «Color details» (DEC-090). */
  const COLOUR_FILTER = {key: 'state', label: 'Color status', options: [['far', 'outside tolerance'], ['hand', 'manual'], ['excluded', 'not engraved'], ['missing', 'titanium color missing']],
    test: (c, v) => (v === 'far' ? !!c.outside_tolerance : v === 'hand' ? c.status === 'hand' || c.status === 'accepted' : c.status === v)};
  const byIndex = (a, b) => Number(a.index) - Number(b.index);
  const COLOUR_SORTS = [['order', 'By number', byIndex], ['far', 'Largest ΔE first', (a, b) => (b.delta_e ?? -1) - (a.delta_e ?? -1) || byIndex(a, b)],
    ['area', 'Largest area first', (a, b) => (b.pixels ?? 0) - (a.pixels ?? 0) || byIndex(a, b)]];

  /** Split version and line smoothing change boundary geometry (REQ-052), while regions and colors remain. */
  const geometryKey = (j) => `${j.document.version}:${j.smoothing_mm || 0}`;

  /** Load the source-color SVG once per boundary geometry; it is not returned with every update. */
  async function splitSvg(j) {
    const key = `${j.id}:${geometryKey(j)}`;
    if (!svgCache.has(key)) {
      const res = await fetch(`/api/vector/${j.id}/split.svg`);
      if (!res.ok) throw new Error('Could not load segmentation');
      svgCache.set(key, await res.text());
    }
    const doc = new DOMParser().parseFromString(svgCache.get(key), 'image/svg+xml');
    const svg = document.importNode(doc.documentElement, true);
    svg.removeAttribute('width'); svg.removeAttribute('height');
    return svg;
  }

  /** All measured colors for the work setup; automatic eligibility depends on work filters. */
  async function palette(j) {
    const key = `${j.id}:${JSON.stringify(j.settings)}`;
    if (!paletteCache.has(key)) paletteCache.set(key, get(`/vector/${j.id}/palette`));
    try { return await paletteCache.get(key); } catch (e) { paletteCache.delete(key); throw e; }
  }

  /** Fetch neighboring regions once per document version; only connected selections can merge (DEC-080). */
  async function neighbours(j) {
    const key = `${j.id}:${j.document.version}`;
    if (!nearCache.has(key)) nearCache.set(key, get(`/vector/${j.id}/neighbours`));
    try { return await nearCache.get(key); } catch (e) { nearCache.delete(key); throw e; }
  }

  /** Resolve a region color: excluded regions have none; a region override takes precedence over its source color. */
  function resolver(j) {
    const colours = new Map(j.colours.map((c) => [Number(c.index), c]));
    const exColours = new Set((j.colouring.excluded_colours || []).map(Number)), exRegions = new Set(j.colouring.excluded_regions || []);
    const own = j.colouring.regions || {};
    const tol = j.settings.tolerance_de;
    const zones = new Map((j.zones || []).flatMap((z) => z.regions.map((rid) => [rid, z])));
    return (rid, k) => {
      const c = colours.get(k) || null;
      if (zones.has(rid)) return {c, zone: zones.get(rid)};               // photo zone: engraved as an image rather than a color
      if (exRegions.has(rid)) return {c, excluded: true};
      if (own[rid] != null) {
        const entry = j.entries[own[rid]];
        return entry ? {c, entry, entryId: own[rid], own: true, far: !!c && tol != null && de(c.lab, entry.lab) > tol} : {c, missing: true, own: true};
      }
      if (!c || exColours.has(k) || c.status === 'excluded') return {c, excluded: true};
      const entry = c.entry_id == null ? null : j.entries[c.entry_id];
      return entry ? {c, entry, entryId: c.entry_id, far: !!c.outside_tolerance} : {c, missing: true};
    };
  }

  // keyboard shortcuts apply only to the visible editor
  let current = null;
  document.addEventListener('keydown', (ev) => { if (current) current.key(ev); });
  document.addEventListener('keyup', (ev) => { if (current) current.keyup(ev); });

  /** Work editor; run(op) sends an action and updates the screen when accepted. */
  function create(j, run, tools = {}) {           // tools.pick(j, title, sourceLab, entryId, onPick): the window that chooses a titanium colour (vector-colours.js)
    const id = j.id;
    const state = {tool: 'brush', scope: 'region', similarity: SIMILARITY, active: null, view: 'titanium', far: false, ref: null,
      selection: new Set(), layers: new Set(), colours: new Set()};
    let lookup = resolver(j);
    let svg = null, loadedVersion = null, loadedWidth = null, missId = '';
    let paths = new Map(), colourOf = new Map(), byColour = new Map(), byEntry = new Map();
    let vb = {x: 0, y: 0, w: j.document.size_mm.width, h: j.document.size_mm.height};
    let entries = null, paletteError = null, paletteKey = null;
    let paletteShown = PALETTE_PAGE;
    let near = null, nearKey = null, nearFailed = false;     // region → edge neighbors in the current split version (DEC-080)
    let hover = null, hot = [], farCount = 0, pending = 0, spaceHeld = false, sideTab = null, ready = false, panelOpen = false;
    let zonePics = null;                                     // <g> with photo-zone images beneath the regions
    let borders = [], bordersOf = new Map();                 // every border of the split once: its path and the regions on its sides
    let lines = null;                                        // <g> of the outlines above the regions: the zones, the hover, the selection
    const reach = new Map();
    let reachTimer = null, sortTimer = null;

    // --- layout -------------------------------------------------------------------------------------------------------
    // the picture takes the keyboard (arrows move the view, + and − zoom, 0 fits it), and every region can be chosen from the list «Regions»
    const stage = h('div', {class: 'vw-ed-stage tool-brush', role: 'group', tabindex: '0',
      'aria-label': 'Work canvas. Hover over a region and click to edit it. Use arrow keys to pan, plus and minus to zoom, and 0 to fit. Select regions from the list on the Source colors tab.'});
    const tip = h('div', {class: 'vw-ed-tip', hidden: true, 'aria-hidden': 'true'});
    const loading = h('p', {class: 'vw-ed-loading muted small'}, 'Loading segmentation…');
    stage.append(loading, tip);
    const viewButtons = VIEWS.map(([v, label]) => btn(label, () => setView(v)));
    const zoomLabel = h('span', {class: 'vw-ed-zoom small muted'});
    const undoBtn = btn('Undo', () => undoRedo('undo')), redoBtn = btn('Redo', () => undoRedo('redo'));
    const bar = h('div', {class: 'vw-ed-bar'},
      h('div', {class: 'vw-ed-group', role: 'group', 'aria-label': 'Canvas view'}, viewButtons),
      h('div', {class: 'vw-ed-group', role: 'group', 'aria-label': 'Zoom'},
        h('button', {type: 'button', class: 'btn', 'aria-label': 'Zoom out', title: 'Zoom out', onClick: () => zoomBy(1 / 1.5)}, '−'), zoomLabel,
        h('button', {type: 'button', class: 'btn', 'aria-label': 'Zoom in', title: 'Zoom in', onClick: () => zoomBy(1.5)}, '+'),
        btn('Fit', () => fit())),
      h('div', {class: 'vw-ed-group', role: 'group', 'aria-label': 'Pan view'},
        PAN.map(([sign, word, fx, fy]) => h('button', {type: 'button', class: 'btn', 'aria-label': `Pan view ${word}`, title: `Pan view ${word}`,
          onClick: () => panBy(fx, fy)}, sign))),
      h('span', {class: 'spacer'}),
      h('div', {class: 'vw-ed-group', role: 'group', 'aria-label': 'Undo and redo'}, undoBtn, redoBtn));
    const totals = h('p', {class: 'vw-ed-totals small'});
    const toolStatus = h('p', {class: 'small vw-ed-tool-status', role: 'status', 'aria-live': 'polite'});

    const toolButtons = TOOLS.map(([t, label]) => { const button = btn(label, () => setTool(t)); button.setAttribute('data-tool', t); return button; });
    const scopeButtons = SCOPES.map(([s, label]) => btn(label, () => setScope(s)));
    // the server takes any delta E that is not negative (vector_job._similarity): the box takes the same and says so when it is not, keeping what was typed;
    // the slider has its own reach (0,5 to 30), told with it
    const simNumber = h('input', {type: 'number', step: '0.5', value: state.similarity, 'aria-label': 'Similarity, ΔE'});
    const simRange = h('input', {type: 'range', step: '0.5', min: String(Forms.VIEWS.similarityReach.min), max: String(Forms.VIEWS.similarityReach.max), value: state.similarity, 'aria-label': 'Similarity, ΔE, slider'});
    const simNote = Forms.watch(simNumber, 'similarity', (v) => setSimilarity(v));
    simRange.addEventListener('input', () => { simNumber.removeAttribute('aria-invalid'); simNote.textContent = ''; setSimilarity(simRange.value); });
    const simBox = h('div', {class: 'vw-ed-sim', hidden: true}, h('span', {class: 'small'}, 'Similarity, ΔE'),
      h('div', {class: 'row'}, simRange, Forms.describe(simRange, 'similarityReach', {extra: 'the adjacent field accepts any number at least 0'}), simNumber, Forms.describe(simNumber, 'similarity'), simNote),
      h('span', {class: 'small muted'}, 'fill follows neighbors whose source color is within this ΔE of the clicked region; excluded regions stop it'));
    const scopeBox = h('div', {class: 'vw-ed-scope'}, h('h4', {}, 'Brush click changes'),
      h('div', {class: 'vw-ed-group', role: 'group', 'aria-label': 'Brush click scope'}, scopeButtons), simBox);
    const selectionBox = h('section', {class: 'vw-ed-section'});
    const autoBtn = btn('Auto', () => setActive(null));
    autoBtn.setAttribute('title', 'The brush restores automatic color selection');
    const activeBox = h('div', {class: 'vw-ed-active'});
    const paletteHead = h('h4', {}, 'Palette'), paletteNote = h('p', {class: 'small muted'});
    const targetPicker = tools.pick ? btn('Choose brush color from a sample…', () => {
      const ref = refColour();
      return tools.pick(j, 'Brush color', ref ? ref.lab : [50, 0, 0], state.active, (entryId) => setActive(entryId));
    }, 'btn-small') : null;
    const grid = h('div', {class: 'vw-swatches vw-ed-palette', role: 'group', 'aria-label': 'Measured titanium colors'});
    const paletteFoot = h('div', {class: 'lst-foot'});
    // the layers and the source colours are short lists (DEC-090): one line each, what it is and its other actions under it on a click,
    // search and sort; pages of 30, so that a work's colours (29 at most) are edited on one page
    const layerList = App.list({id: 'vw.ed.layers', items: [], page: 30, key: (x) => x.key, row: layerRow, details: layerDetails, actions: layerActions, search: (x) => x.search,
      sorts: [['order', 'Original order', (a, b) => a.pos - b.pos], ['area', 'Largest area first', (a, b) => (b.area ?? -1) - (a.area ?? -1) || a.pos - b.pos],
        ['time', 'Longest engraving first', (a, b) => (b.seconds ?? -1) - (a.seconds ?? -1) || a.pos - b.pos]],
      empty: 'No color layers: everything is excluded.'});
    const colourList = App.list({id: 'vw.ed.colours', items: [], page: 30, key: (c) => String(c.index), row: colourRow, details: colourDetails,
      rowClass: (c) => (c.status === 'excluded' ? 'excluded' : ''),
      actions: colourActions, search: (c) => `№ ${Number(c.index) + 1}`, filters: [COLOUR_FILTER], sorts: COLOUR_SORTS, empty: 'No source colors match this selection.'});
    // every region as a line (ux-accessible-layout-p0, REQ-001): a region, or several, are chosen without the pointer, as the click, Shift+click
    // and the lasso on the picture choose them; what is done with the chosen ones is in the selection (the «Brush» tab, or «Photo»)
    const regionList = App.list({id: 'vw.ed.regions', items: [], page: 30, key: (x) => x.id, row: regionRow, actions: regionActions, search: (x) => x.search,
      rowClass: (x) => (state.selection.has(x.id) ? 'picked' : ''),
      filters: [{key: 'colour', label: 'Source color', select: true, all: 'Any', options: () => j.colours.map((c) => [String(c.index), `Source color #${Number(c.index) + 1}`]),
        test: (x, v) => String(x.k) === v}, {key: 'chosen', label: 'Selection', options: [['yes', 'Selected']], test: (x) => state.selection.has(x.id)}],
      sorts: [['order', 'Original order', (a, b) => a.pos - b.pos], ['colour', 'By source color', (a, b) => a.k - b.k || a.pos - b.pos]],
      empty: 'No regions: segmentation has not loaded yet.'});
    const regionNote = h('p', {class: 'small', role: 'status', 'aria-live': 'polite'});
    const regionBar = h('div', {class: 'row'}, btn('Select all', () => chooseOnly([...paths.keys()]), 'btn-small'), btn('Clear selection', () => clearSelection(), 'btn-small'),
      btn('Go to selection actions', () => showSelection(), 'btn-small'));
    const layersBox = h('div', {class: 'vw-ed-list vw-ed-layers'}, layerList.el), layerMerge = h('div', {}), layersAbout = h('div', {});
    const farBox = h('input', {type: 'checkbox', onChange: (ev) => { state.far = ev.target.checked; syncSvgClass(); }});
    const farNote = h('p', {class: 'small muted'});
    const coloursBox = h('div', {class: 'vw-ed-list'}, h('p', {class: 'small muted'}, 'The source color is the region color in your image; on the right is the titanium color that '
      + 'will be engraved. “Replace” chooses another titanium color, showing its sources (tests and work) and stability. Open a row for '
      + 'color evidence, “Automatic”, and “Do not engrave”: all regions of that color leave the file, with only cleaning remaining.'), colourList.el);
    const colourMerge = h('div', {});
    let layerRegions = new Map();                            // the key of a layer's line -> the regions it outlines on the picture
    outlineRows(layerList, (key) => (layerRegions.get(key) || (() => []))());
    outlineRows(colourList, (key) => byColour.get(Number(key)) || []);
    outlineRows(regionList, (key) => [key]);
    const photo = VectorPhoto.create(j, {act: (op) => act(op), select: (ids) => selectOnly(ids), outline: (ids) => (ids ? setHot(ids) : refreshHover())});
    // inscriptions are inset into the image: the layer draws the inset in clean titanium and the backing and lettering in their colors (inscriptions-in-works)
    const lettering = Lettering.create(j, {act: (op) => act(op), palette: () => palette(j), size: (v) => v.document.size_mm, scale: () => frame().s,
      drawn: true, clean: EXCLUDED, open: () => sideTab === 'texts', picked: () => { if (narrow()) openPanel(null); }, externalFields: true,
      selectionChanged: (textId) => {
        if (textId && state.selection.size) { state.selection = new Set(); outlineSelection(); syncSelection(); }
        syncInspector();
      },
      pick: tools.pick ? (title, lab, entryId, onPick) => tools.pick(j, title, lab, entryId, onPick) : null});
    const inspectorStatus = h('p', {class: 'sr-only', role: 'status', 'aria-live': 'polite'});
    const inspector = h('div', {class: 'vw-ed-inspector', role: 'region', 'aria-label': 'Selection inspector', hidden: true},
      h('h3', {}, 'Inspector'), inspectorStatus, selectionBox, lettering.fields);
    // five panel tabs: brush and color, titanium layers, source colors, photo zones, and lettering
    const sideTabs = App.tabs([
      ['brush', 'Brush', h('div', {class: 'vw-ed-pane'},
        h('section', {class: 'vw-ed-section'}, h('h4', {}, 'Tool'),
          h('div', {class: 'vw-ed-group', role: 'group', 'aria-label': 'Tool'}, toolButtons),
          h('p', {class: 'small muted'}, 'Alt+click with the brush uses the eyedropper.'), scopeBox),
        h('section', {class: 'vw-ed-section'}, h('div', {class: 'row'}, h('h4', {}, 'Active color'), h('span', {class: 'spacer'}), autoBtn), activeBox),
        h('section', {class: 'vw-ed-section'}, paletteHead, paletteNote, targetPicker, grid, paletteFoot))],
      ['layers', 'Layers', h('div', {class: 'vw-ed-pane'}, h('section', {class: 'vw-ed-section'}, h('h4', {}, 'Titanium layers'), layersAbout, layersBox, layerMerge))],
      ['colours', 'Source colors', h('div', {class: 'vw-ed-pane'}, h('section', {class: 'vw-ed-section'}, h('h4', {}, 'Source colors'),
        h('label', {class: 'row small'}, farBox, h('span', {}, 'Show colors far from the original')), farNote, coloursBox, colourMerge),
        h('section', {class: 'vw-ed-section'}, h('h4', {}, 'Regions'), regionNote, regionBar, regionList.el))],
      ['photo', 'Photo', h('div', {class: 'vw-ed-pane'}, photo.el)],
      ['texts', 'Lettering', lettering.el]],
      {initial: 'brush', remember: 'vw.edtab', label: 'Editor panel', prefix: 'vw-ed-tab', onSelect: (id) => {
        sideTab = id;
        syncSvgClass();
        lettering.opened();
        if (id === 'texts') { hover = null; tip.hidden = true; setHot([]); }
        if (ready && id === 'photo') setTool('select');       // on «Photo» a click selects (the brush is on «Brush», out of sight)
      }});
    // on a narrow screen the panel slides out over the picture (ux-accessible-layout-p0, REQ-002): a button in the bar opens it, a click that
    // selects something on the picture opens it on what was selected, Esc or «Close» shuts it and the focus goes back to the button
    const panelClose = h('button', {type: 'button', class: 'btn vw-ed-panel-close', onClick: () => closePanel(true)}, 'Close panel');
    const panel = h('aside', {class: 'vw-ed-panel', id: `vw-ed-panel-${id}`, 'aria-label': 'Tools and colors'},
      h('div', {class: 'vw-ed-panel-head'}, h('strong', {}, 'Editor panel'), h('span', {class: 'spacer'}), panelClose),
      inspector, sideTabs.list, h('div', {class: 'vw-ed-panes'}, sideTabs.panels));
    panel.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && narrow() && panelOpen) { ev.stopPropagation(); closePanel(true); } });
    const panelToggle = h('button', {type: 'button', class: 'btn vw-ed-panel-toggle', 'aria-expanded': 'false', 'aria-controls': `vw-ed-panel-${id}`,
      onClick: () => (panelOpen ? closePanel(true) : openPanel(null))}, 'Panel: brush, layers, colors, lettering');
    bar.append(panelToggle);
    const el = h('div', {class: 'vw-editor'},
      h('div', {class: 'vw-ed-main'}, bar, toolStatus, totals, stage,
        h('p', {class: 'small muted'}, 'Mouse wheel zooms at the cursor; drag pans (with Selection, drag draws a lasso; pan with Space+drag '
          + 'or the middle mouse button). Fit shows the whole image. ', 'Ctrl+Z undoes, Ctrl+Shift+Z redoes, Esc clears selection. ',
        'Keyboard: focus the canvas and use the arrow keys to pan, + and − to zoom, or 0 to fit. Select regions from the list on the Source colors tab.')),
      panel);

    // --- picture: loading, coloring, zoom ---------------------------------------------------------------------------
    async function load() {
      const version = geometryKey(j);
      if (loadedVersion === version) return;
      loadedVersion = version;
      let next;
      try { next = await splitSvg(j); } catch (e) {
        loadedVersion = null;
        loading.hidden = false;
        loading.setAttribute('class', 'vw-ed-loading alert bad');
        return fill(loading, e.message);
      }
      if (version !== geometryKey(j)) return;                 // a newer geometry arrived while loading and is already being fetched
      const {width: W, height: H} = j.document.size_mm;
      loadedWidth = W;
      const step = Math.max(W, H) / 80;
      missId = `vw-miss-${id}-${version}`.replace(/[^\w-]/g, '-');
      const pattern = svgEl('pattern', {id: missId, patternUnits: 'userSpaceOnUse', width: step, height: step, patternTransform: 'rotate(45)'});
      pattern.append(svgEl('rect', {width: step, height: step, fill: '#ffffff'}), svgEl('rect', {width: step / 3, height: step, fill: MISSING}));
      const defs = svgEl('defs', {});
      defs.append(pattern);
      // the original uses the split bounds and proportions; load it only when displayed
      zonePics = svgEl('g', {class: 'vw-zone-pics'});
      next.prepend(defs, svgEl('image', {x: 0, y: 0, width: W, height: H, preserveAspectRatio: 'none'}), zonePics);
      next.setAttribute('preserveAspectRatio', 'xMidYMid meet');
      paths = new Map(); colourOf = new Map(); byColour = new Map();
      for (const path of next.querySelectorAll('path[data-region]')) {
        const rid = path.getAttribute('data-region'), k = Number(path.getAttribute('data-color'));
        paths.set(rid, path);
        colourOf.set(rid, k);
        if (!byColour.has(k)) byColour.set(k, []);
        byColour.get(k).push(rid);
      }
      const group = next.querySelector('g.vw-borders');
      borders = group ? [...group.querySelectorAll('path')].map((b) => ({d: b.getAttribute('d'), sides: b.getAttribute('data-sides').split(' ')})) : [];
      if (group) group.remove();                               // kept as data only: the page does not carry them twice
      bordersOf = new Map();
      borders.forEach((b, i) => { for (const rid of b.sides) { if (!bordersOf.has(rid)) bordersOf.set(rid, []); bordersOf.get(rid).push(i); } });
      lines = svgEl('g', {class: 'vw-outlines'});
      for (const kind of ['vw-zone', 'vw-hot', 'vw-sel']) lines.append(svgEl('path', {class: `vw-outline vw-halo ${kind}`}), svgEl('path', {class: `vw-outline ${kind}`}));
      next.append(lettering.layer, lines);                    // the inscriptions over the regions, the outlines (no pointer) over all
      if (svg) svg.remove();
      stage.prepend(next);
      svg = next;
      loading.hidden = true;
      hot = [];
      state.selection = new Set([...state.selection].filter((rid) => paths.has(rid)));
      if (hover && !paths.has(hover)) hover = null;
      setBox(vb.x, vb.y, vb.w);
      paint();
      showZones();
      showImage();
      outlineSelection();
      syncSelection();
      renderLayers();
      renderColours();                                         // a line's «Select regions» is off while the colour has no region on the picture
      renderRegions();
      refreshHover();
    }

    function paint() {
      if (!svg) return;
      byEntry = new Map();
      farCount = 0;
      for (const [rid, path] of paths) {
        const r = lookup(rid, colourOf.get(rid));
        let colour;
        if (state.view === 'source') colour = r.c ? rgb(r.c.srgb) : '#ffffff';
        else if (r.zone) colour = SEE_THROUGH;
        else if (r.excluded) colour = EXCLUDED;
        else if (r.missing) colour = `url(#${missId})`;
        else colour = rgb(r.entry.srgb);
        path.setAttribute('fill', colour);
        path.setAttribute('stroke', r.missing && state.view !== 'source' ? MISSING : r.zone && state.view !== 'source' ? 'none' : colour);
        if (r.entry) {
          const key = String(r.entryId);
          if (!byEntry.has(key)) byEntry.set(key, []);
          byEntry.get(key).push(rid);
        }
        setClass(path, 'vw-far', !!r.far);
        if (r.far) farCount += 1;
      }
      syncSvgClass();
      syncFarNote();
    }

    function syncSvgClass() {
      if (svg) svg.setAttribute('class', ['vw-ed-svg', state.view === 'original' ? 'view-original' : '', state.far ? 'show-far' : '',
        sideTab === 'photo' ? 'show-zones' : '', sideTab === 'texts' ? 'show-texts' : ''].filter(Boolean).join(' '));
    }

    /** The outline of a set of regions as one shape: the borders with a region of the set on one side only (none between two of them). */
    function outlineOf(ids) {
      const inside = new Set(ids), parts = new Set();
      for (const rid of inside) {
        for (const i of bordersOf.get(rid) || []) if (borders[i].sides.length < 2 || !borders[i].sides.every((s) => inside.has(s))) parts.add(i);
      }
      return [...parts].map((i) => borders[i].d).join(' ');
    }

    /** One kind of outline (``vw-sel``, ``vw-hot``, ``vw-zone``) around each of ``groups`` (lists of regions): a light line on a dark halo,
        so it shows on light and dark titanium alike; ``data-regions`` names what it outlines. */
    function drawLine(kind, groups) {
      if (!lines) return;
      const d = groups.filter((g) => g.length).map(outlineOf).join(' '), named = groups.flat().sort().join(' ');
      for (const p of [...lines.querySelectorAll(`path.${kind}`)]) {
        if (d) p.setAttribute('d', d); else p.removeAttribute('d');
        if (!p.classList.contains('vw-halo')) p.setAttribute('data-regions', named);
      }
    }

    /** Each photo-zone image sits beneath its regions; its URL changes only with the image. */
    function showZones() {
      if (!zonePics) return;
      const shown = new Map([...zonePics.querySelectorAll('image')].map((im) => [im.getAttribute('data-zone'), im]));
      for (const z of j.zones || []) {
        if (!z.picture) continue;
        const key = String(z.number);
        const im = shown.get(key) || svgEl('image', {class: 'vw-zone-pic', 'data-zone': key, preserveAspectRatio: 'none'});
        for (const [k, v] of [['x', z.box.x], ['y', z.box.y], ['width', z.box.width], ['height', z.box.height]]) im.setAttribute(k, v);
        setPicture(im, z.picture);
        if (!shown.has(key)) zonePics.append(im);
        shown.delete(key);
      }
      for (const im of shown.values()) im.remove();
      drawLine('vw-zone', (j.zones || []).map((z) => z.regions.filter((rid) => paths.has(rid))));     // each zone one shape, shown on «Photo»
    }

    /** A zone's new picture replaces its old one only once it has loaded: the old one stays in place meanwhile, never a blank zone. */
    function setPicture(im, src) {
      if (im.getAttribute('href') === src || im.getAttribute('data-next') === src) return;
      if (!im.getAttribute('href') || typeof Image === 'undefined') return im.setAttribute('href', src);
      im.setAttribute('data-next', src);
      const next = new Image();
      next.onload = next.onerror = () => {
        if (im.getAttribute('data-next') !== src) return;                   // a newer picture was asked for meanwhile
        im.setAttribute('href', src);
        im.removeAttribute('data-next');
      };
      next.src = src;
    }

    function showImage() {
      const image = svg && svg.querySelector('image');
      if (image && state.view === 'original' && !image.getAttribute('href')) image.setAttribute('href', `/api/plans/${id}/source-image`);
    }

    function setView(v) {
      state.view = v;
      viewButtons.forEach((b, i) => b.setAttribute('aria-pressed', VIEWS[i][0] === v ? 'true' : 'false'));
      showImage();
      paint();
    }

    function setBox(x, y, w) {
      const {width: W, height: H} = j.document.size_mm;
      w = clamp(w, W / 64, W);
      const hh = w * H / W;
      vb = {x: clamp(x, Math.min(0, W - w), Math.max(0, W - w)), y: clamp(y, Math.min(0, H - hh), Math.max(0, H - hh)), w, h: hh};
      if (svg) svg.setAttribute('viewBox', [vb.x, vb.y, vb.w, vb.h].map((v) => +v.toFixed(4)).join(' '));
      fill(zoomLabel, `${Math.round(W / vb.w * 100)} %`);
      if (sideTab === 'texts') lettering.redraw();             // the handles keep their size on screen
    }

    // screen point → image point (mm) with preserveAspectRatio meet
    function frame() {
      const r = stage.getBoundingClientRect();
      const s = Math.min(r.width / vb.w, r.height / vb.h) || 1;
      return {r, s, ox: (r.width - vb.w * s) / 2, oy: (r.height - vb.h * s) / 2};
    }
    function zoomAt(factor, ux, uy) {
      const W = j.document.size_mm.width;
      const w = clamp(vb.w / factor, W / 64, W), k = w / vb.w;
      setBox(ux - (ux - vb.x) * k, uy - (uy - vb.y) * k, w);
    }
    const zoomBy = (factor) => zoomAt(factor, vb.x + vb.w / 2, vb.y + vb.h / 2);
    const fit = () => setBox(0, 0, j.document.size_mm.width);
    const panBy = (fx, fy) => setBox(vb.x + fx * vb.w / 5, vb.y + fy * vb.h / 5, vb.w);
    stage.addEventListener('keydown', (ev) => {
      if (ev.target !== stage || ev.ctrlKey || ev.metaKey || ev.altKey) return;       // a key of a control inside the picture is its own
      const way = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}[ev.key];
      if (way) panBy(...way);
      else if (ev.key === '+' || ev.key === '=') zoomBy(1.5);
      else if (ev.key === '-') zoomBy(1 / 1.5);
      else if (ev.key === '0') fit();
      else return;
      ev.preventDefault();
    });

    // --- mouse: wheel zooms, dragging over 4 px pans rather than clicking ---------------------------------------------
    let drag = null, dragged = false, lettered = false;
    stage.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      const f = frame();
      const delta = (ev.deltaY || 0) * (ev.deltaMode === 1 ? 16 : 1);
      zoomAt(clamp(Math.exp(-delta * 0.002), 0.5, 2), vb.x + (ev.clientX - f.r.left - f.ox) / f.s, vb.y + (ev.clientY - f.r.top - f.oy) / f.s);
    }, {passive: false});
    const toMm = (ev, f = frame()) => [vb.x + (ev.clientX - f.r.left - f.ox) / f.s, vb.y + (ev.clientY - f.r.top - f.oy) / f.s];
    stage.addEventListener('pointerdown', (ev) => {
      if (ev.button > 1) return;
      if (ev.button === 1) ev.preventDefault();               // middle button pans rather than autoscrolling
      dragged = false;
      if (ev.button === 0 && !spaceHeld && lettering.down(ev, toMm(ev))) {     // «Lettering»: inscription, its handle, or a path point
        lettered = true;
        try { stage.setPointerCapture(ev.pointerId); } catch (_) { /* pointer already released */ }
        return;
      }
      const lasso = ev.button === 0 && state.tool === 'select' && !spaceHeld && sideTab !== 'texts';
      drag = {x: ev.clientX, y: ev.clientY, vb: {...vb}, s: frame().s, pointer: ev.pointerId, moving: false, lasso, points: [], line: null};
    });
    stage.addEventListener('pointermove', (ev) => {
      if (lettered) return lettering.move(ev, toMm(ev));
      if (drag) {
        const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
        if (!drag.moving && Math.hypot(dx, dy) > 4) {
          drag.moving = true;
          try { stage.setPointerCapture(drag.pointer); } catch (_) { /* pointer already released */ }
          tip.hidden = true;
          if (drag.lasso) startLasso(ev);
          else stage.classList.add('panning');
        }
        if (drag.moving && drag.lasso) return drag.cancelled ? undefined : extendLasso(ev);
        if (drag.moving) return setBox(drag.vb.x - dx / drag.s, drag.vb.y - dy / drag.s, drag.vb.w);
      }
      if (sideTab !== 'texts') hoverAt(ev);
    });
    const endDrag = (ev) => {
      if (lettered) {
        lettered = false;
        if (lettering.up(ev, ev && ev.clientX != null ? toMm(ev) : null)) dragged = true;
        return;
      }
      if (drag && drag.moving) {
        dragged = true;
        stage.classList.remove('panning');
        if (drag.lasso && !drag.cancelled) finishLasso(drag, ev || {});
      }
      drag = null;
    };

    // --- lasso with Selection chooses regions at least half inside, as determined by the server ----------
    function startLasso(ev) {
      drag.line = svgEl('polyline', {class: 'vw-lasso', points: ''});
      if (svg) svg.append(drag.line);
      drag.points = [toMm({clientX: drag.x, clientY: drag.y})];
      drag.last = [drag.x, drag.y];
      extendLasso(ev);
    }
    function extendLasso(ev) {
      if (Math.hypot(ev.clientX - drag.last[0], ev.clientY - drag.last[1]) < LASSO_STEP) return;
      drag.last = [ev.clientX, ev.clientY];
      drag.points.push(toMm(ev));
      if (drag.line) drag.line.setAttribute('points', drag.points.map(([x, y]) => `${+x.toFixed(3)},${+y.toFixed(3)}`).join(' '));
    }
    function cancelLasso() {                                  // Escape while a lasso is drawn: it selects nothing
      if (!drag || !drag.lasso || !drag.moving) return;
      if (drag.line) drag.line.remove();
      drag.line = null;
      drag.cancelled = true;
    }
    async function finishLasso(done, ev) {
      if (done.line) done.line.remove();
      if (done.points.length < 3) return;
      const how = ev.altKey ? 'remove' : ev.shiftKey ? 'add' : 'replace';
      let got;
      try { got = await App.post(`/vector/${id}/lasso`, {points: done.points.map(([x, y]) => [+x.toFixed(3), +y.toFixed(3)])}); }
      catch (e) { return toast(e.message); }
      if (got.version !== j.document.version) return;          // split changed while the calculation was running
      const ids = got.regions.filter((rid) => paths.has(rid));
      if (how === 'replace') state.selection = new Set(ids);
      else for (const rid of ids) mark(state.selection, rid, how === 'add');
      outlineSelection();
      syncSelection();
      if (!ids.length) toast('The lasso did not enclose at least half of any region');
      else showChosen();
    }
    stage.addEventListener('pointerup', endDrag);
    stage.addEventListener('pointercancel', endDrag);
    stage.addEventListener('pointerleave', () => { if (!drag) setHover(null); });
    stage.addEventListener('click', (ev) => {
      if (dragged) { dragged = false; return; }               // ending a drag is not a click
      if (sideTab === 'texts') return lettering.click(ev, toMm(ev));      // on Lettering, clicks do not paint regions
      const path = ev.target && ev.target.closest ? ev.target.closest('path[data-region]') : null;
      if (path) clickRegion(path.getAttribute('data-region'), ev);
    });

    // --- hover outlines what a click changes and shows a tooltip ------------------------------------------------------
    function hoverAt(ev) {
      const path = ev.target && ev.target.closest ? ev.target.closest('path[data-region]') : null;
      const rid = path ? path.getAttribute('data-region') : null;
      if (rid !== hover) setHover(rid);
      if (rid) placeTip(ev);
    }

    function setHover(rid) {
      hover = rid;
      if (!rid) { tip.hidden = true; return setHot([]); }
      setRef(colourOf.get(rid));
      if (state.tool === 'brush' && state.scope === 'fill') wantReach(rid);
      setHot(clickSet(rid));
      showTip(rid);
    }
    const refreshHover = () => (hover ? setHover(hover) : setHot([]));

    function clickSet(rid) {
      if (state.tool !== 'brush' || state.scope === 'region') return [rid];
      if (state.scope === 'colour') return byColour.get(colourOf.get(rid)) || [rid];
      const r = reach.get(reachKey(rid));
      return r && r.regions ? r.regions : [rid];
    }

    function setHot(ids) {
      hot = ids.filter((rid) => paths.has(rid));
      drawLine('vw-hot', [hot]);
    }

    // fill asks the server which regions it reaches after 120 ms idle, once per region, similarity, and version
    const reachKey = (rid) => `${rid}|${state.similarity}|${j.document.version}`;
    function wantReach(rid) {
      clearTimeout(reachTimer);
      if (reach.has(reachKey(rid))) return;
      reachTimer = setTimeout(async () => {
        const key = reachKey(rid);
        try { reach.set(key, await get(`/vector/${id}/reach?region=${encodeURIComponent(rid)}&similarity_de=${state.similarity}`)); }
        catch (e) { reach.set(key, {error: e.message}); }
        if (hover === rid && reachKey(rid) === key && state.tool === 'brush' && state.scope === 'fill') { setHot(clickSet(rid)); showTip(rid); }
      }, 120);
    }

    function clickText(rid) {
      if (state.tool === 'pipette') return 'Click to make this region’s titanium color active';
      if (state.tool === 'select') return state.selection.has(rid) ? 'Click to select only this region; Shift+click removes it from the selection'
        : 'Click to select; Shift+click adds to selection';
      const what = (state.active == null ? 'restore automatic selection' : 'paint with active color')
        + (state.scope !== 'colour' && lookup(rid, colourOf.get(rid)).zone ? ' and remove from photo zone' : '');
      if (state.scope === 'colour') return `Click to ${what}: entire source color #${colourOf.get(rid) + 1}, ${(byColour.get(colourOf.get(rid)) || []).length} regions`;
      if (state.scope === 'fill') {
        const r = reach.get(reachKey(rid));
        return `Click to ${what}: fill similar (ΔE ${state.similarity}), ` + (!r ? 'calculating regions…' : r.error ? r.error : `${r.regions.length} regions`);
      }
      return `Click to ${what}: this region only`;
    }

    function showTip(rid) {
      const k = colourOf.get(rid), r = lookup(rid, k), e = r.entry;
      if (!r.c) { tip.hidden = true; return; }
      fill(tip, h('div', {}, `Region ${rid} · source color #${k + 1} · `, r.zone ? `photo zone ${r.zone.number}: ${VectorPhoto.zoneSummary(r.zone)}` : ['titanium: ',
        r.excluded ? 'excluded' : r.missing ? 'color no longer among measurements' : [chip(e.srgb, labText(e.lab)), `ΔE ${num(de(r.c.lab, e.lab))}`, r.own ? ' · region-specific color' : null]]),
      e ? h('div', {class: 'muted'}, `recipe: ${params(e.parameters)} · ${seconds(e.time_s_per_cm2)}`) : null,
      h('div', {class: 'vw-ed-tip-do'}, clickText(rid)));
      tip.hidden = false;
    }

    function placeTip(ev) {
      const r = stage.getBoundingClientRect();
      let x = ev.clientX - r.left + 16, y = ev.clientY - r.top + 16;
      if (x + 300 > r.width) x = Math.max(4, ev.clientX - r.left - 316);
      if (y + 110 > r.height) y = Math.max(4, ev.clientY - r.top - 120);
      tip.setAttribute('style', `left:${Math.round(x)}px;top:${Math.round(y)}px`);
    }

    // --- click: brush, eyedropper (also Alt+brush click), selection -------------------------------------------------------------
    function clickRegion(rid, ev) {
      setRef(colourOf.get(rid));
      if (state.tool === 'pipette' || (state.tool === 'brush' && ev.altKey)) return pipette(rid);
      if (state.tool === 'select') { select(rid, !!ev.shiftKey); return showChosen(); }
      const op = {op: 'paint', region: rid, scope: state.scope, entry_id: state.active};
      if (state.scope === 'fill') op.similarity_de = state.similarity;
      return act(op);
    }

    function pipette(rid) {
      const r = lookup(rid, colourOf.get(rid));
      if (r.entry) return setActive(r.entryId);
      toast(r.zone ? `Region ${rid} is in photo zone ${r.zone.number}: it is engraved as an image and has no titanium color`
        : r.excluded ? `Region ${rid} is excluded and has no titanium color` : `Region ${rid} has no measured titanium color`);
    }

    function select(rid, add) {
      lettering.deselect();
      if (add) mark(state.selection, rid, !state.selection.has(rid));
      else state.selection = new Set(state.selection.size === 1 && state.selection.has(rid) ? [] : [rid]);
      outlineSelection();
      syncSelection();
      if (hover) showTip(hover);
    }
    function clearSelection() { state.selection = new Set(); outlineSelection(); syncSelection(); }
    /** Escape: nothing stays outlined on the picture but the photo zones - the selection and a lasso being drawn go, and so does the line
        under the pointer (a region's or a zone card's) until the pointer moves again. */
    function dropSelection() {
      cancelLasso();
      hover = null;
      tip.hidden = true;
      setHot([]);
      if (state.selection.size) clearSelection();
    }
    /** The regions ``ids`` are the selection (the tool is «Selection»), wherever the person is. */
    function chooseOnly(ids) {
      lettering.deselect();
      setTool('select');
      state.selection = new Set(ids.filter((rid) => paths.has(rid)));
      outlineSelection();
      syncSelection();
    }
    /** The selection's own place, with the focus on it: its actions are there, and a key press that came from another tab must not leave the
        keyboard on a tab that is no longer shown. */
    function showSelection() {
      if (!state.selection.size && !lettering.selected()) { inspector.hidden = false; selectionBox.hidden = false; }
      selectionBox.setAttribute('tabindex', '-1');
      selectionBox.focus();
    }
    function selectOnly(ids) {
      chooseOnly(ids);
      showSelection();
    }
    // --- the panel as a slide-out on a narrow screen (the stylesheet shows it so below 1100 px; above, it is a column and these do nothing) -------------
    const narrow = () => typeof matchMedia === 'function' && matchMedia('(max-width:1100px)').matches;
    /** Open the panel, on ``tab`` when one is named, with the keyboard on the shown tab (or the selection's own box for «select»). */
    function openPanel(tab, focus = true) {
      if (tab) sideTabs.select(tab);
      panelOpen = true;
      panel.classList.add('is-open');
      panelToggle.setAttribute('aria-expanded', 'true');
      if (focus) {
        const on = [...sideTabs.list.querySelectorAll('button')].find((b) => b.getAttribute('aria-selected') === 'true');
        if (on) on.focus();
      }
    }
    function closePanel(back) {
      panelOpen = false;
      panel.classList.remove('is-open');
      panelToggle.setAttribute('aria-expanded', 'false');
      if (back) panelToggle.focus();
    }
    /** What was chosen on the picture has its actions in the panel: on a narrow screen it slides out to them. */
    function showChosen() {
      if (!narrow() || !state.selection.size) return;
      openPanel(null, false);
      if (stage.scrollIntoView && matchMedia('(max-width:480px)').matches) stage.scrollIntoView({block: 'start'});      // a phone: the sheet takes the lower part, the picture goes up
      selectionBox.setAttribute('tabindex', '-1');
      selectionBox.focus();
    }
    /** One region in or out of the selection without leaving the list it was chosen in (Shift+click on the picture). */
    function toggleRegion(rid) {
      if (state.tool !== 'select') setTool('select');
      select(rid, true);
    }

    function outlineSelection() {
      drawLine('vw-sel', [[...state.selection].filter((rid) => paths.has(rid))]);
    }

    // --- actions run one at a time in order; the screen updates run and the editor updates state -----------------------------------------------
    async function act(op, after, place) {
      pending += 1;
      el.classList.add('busy');
      const ok = await run(op, place);
      pending -= 1;
      if (!pending) el.classList.remove('busy');
      if (ok && after) after();
      return ok;
    }
    function undoRedo(kind) { if ((j[kind] || 0) > 0) act({op: kind}); }

    // --- panel -----------------------------------------------------------------------------------------------------------
    function showToolStatus() {
      const scopes = {region: 'one region', colour: 'all regions with the source color', fill: 'similar neighboring regions'};
      toolStatus.textContent = state.tool === 'brush' ? `Tool: brush. Clicking will change ${scopes[state.scope]}.`
        : state.tool === 'select' ? 'Tool: selection. Clicking selects a region.' : 'Tool: eyedropper. Clicking selects a color.';
    }
    function setTool(t) {
      state.tool = t;
      toolButtons.forEach((b, i) => b.setAttribute('aria-pressed', TOOLS[i][0] === t ? 'true' : 'false'));
      stage.setAttribute('class', `vw-ed-stage tool-${t}` + (spaceHeld ? ' pan-ready' : ''));
      scopeBox.hidden = t !== 'brush';
      showToolStatus();
      refreshHover();
    }

    function setScope(s) {
      state.scope = s;
      scopeButtons.forEach((b, i) => b.setAttribute('aria-pressed', SCOPES[i][0] === s ? 'true' : 'false'));
      simBox.hidden = s !== 'fill';
      showToolStatus();
      refreshHover();
    }

    function setSimilarity(value) {
      const v = Number(value);
      if (!Number.isFinite(v) || v < 0) return;                                  // the box refuses it before (Forms.watch); nothing is changed here
      state.similarity = v;
      simNumber.value = v; simRange.value = clamp(v, Forms.VIEWS.similarityReach.min, Forms.VIEWS.similarityReach.max);
      refreshHover();
    }

    function setActive(entryId) {
      state.active = entryId ?? null;
      syncActive();
      if (hover) showTip(hover);
    }

    // palette sorts by ΔE to the last hovered or clicked region’s source color after 150 ms idle
    function setRef(k) {
      if (k == null || k === state.ref) return;
      state.ref = k;
      clearTimeout(sortTimer);
      sortTimer = setTimeout(() => { renderPalette(); syncActive(); }, 150);
    }
    const refColour = () => (state.ref == null ? null : j.colours.find((c) => Number(c.index) === state.ref) || null);
    const activeEntry = () => (state.active == null ? null : (entries || []).find((e) => same(e.id, state.active)) || j.entries[state.active] || null);

    function syncActive() {
      const e = activeEntry(), ref = refColour();
      autoBtn.setAttribute('aria-pressed', state.active == null ? 'true' : 'false');
      fill(activeBox, e ? h('span', {class: 'vw-ed-big', style: `background:${rgb(e.srgb)}`, title: labText(e.lab)}) : h('span', {class: 'vw-ed-big auto', 'aria-hidden': 'true'}, 'A'),
        h('div', {class: 'small'}, e ? [h('div', {}, ref ? `ΔE ${num(de(e.lab, ref.lab))} to source color #${ref.index + 1}` : 'ΔE — hover over a region', ' · ', seconds(e.time_s_per_cm2)),
          h('div', {class: 'muted'}, params(e.parameters)),
          h('div', {class: 'muted'}, [BASIS[e.basis], e.automatic === false ? 'not selected automatically' : null].filter(Boolean).join(' · ')),
          e.sources ? h('div', {class: 'muted'}, pill(...STEADY[steadiness(e)]), ' ', originText(e.sources)) : null]
          : state.active != null ? 'Loading color…'
            : [h('strong', {}, 'Auto'), h('div', {class: 'muted'}, 'A brush click restores automatic color selection for regions. Choose a color from the palette or with the eyedropper.')]));
      for (const b of grid.querySelectorAll('button')) {
        const on = same(b.getAttribute('data-entry'), state.active);
        setClass(b, 'picked', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      }
    }

    async function loadPalette() {
      const key = `${j.id}:${JSON.stringify(j.settings)}`;
      if (key === paletteKey) return renderPalette();
      paletteKey = key;
      paletteError = null;
      if (!entries) renderPalette();
      try { const list = await palette(j); if (key === paletteKey) entries = list; } catch (e) { if (key === paletteKey) { entries = null; paletteError = e.message; } }
      if (key === paletteKey) { renderPalette(); syncActive(); }
    }

    function renderPalette() {
      const ref = refColour();
      fill(paletteHead, entries ? `Palette: ${entries.length}` : 'Palette');
      fill(paletteNote, 'All measured colors for this laser, lens, and titanium grade (from any plate). ',
        ref ? `Colors closest to source color #${ref.index + 1} appear first. ` : 'Hover over a region to sort by closeness to its source color. ',
        'Dashed means captured without a reference; a dot means excluded from automatic selection.');
      fill(paletteFoot);
      if (!entries) return fill(grid, h('p', {class: paletteError ? 'alert bad' : 'muted small'}, paletteError || 'Loading palette…'));
      const d = (e) => (ref ? de(e.lab, ref.lab) : null);
      const sorted = [...entries].sort(ref ? (a, b) => d(a) - d(b) : (a, b) => b.lab[0] - a.lab[0]);
      // the nearest first, a page at a time (DEC-090): hundreds of squares are not scrolled through; the chosen colour stays in view
      const shown = sorted.slice(0, paletteShown);
      const chosen = sorted.find((e) => same(e.id, state.active));
      if (chosen && !shown.includes(chosen)) shown.push(chosen);
      const rest = sorted.length - Math.min(paletteShown, sorted.length);
      if (rest > 0) {
        fill(paletteFoot, h('span', {class: 'muted small'}, `showing ${Math.min(paletteShown, sorted.length)} of ${sorted.length}`),
          btn(`Show ${Math.min(PALETTE_PAGE, rest)} more`, () => { paletteShown += PALETTE_PAGE; renderPalette(); syncActive(); }, 'btn-small'));
      }
      fill(grid, shown.map((e) => {
        const title = [d(e) == null ? null : `ΔE ${num(d(e))}`, seconds(e.time_s_per_cm2), e.basis === 'as-shot' ? 'captured without reference' : null,
          e.automatic ? null : 'excluded from automatic selection', e.sources ? `${STEADY[steadiness(e)][0]}; ${originText(e.sources)}` : null].filter(Boolean).join(' · ');
        return h('button', {type: 'button', class: `vw-swatch steady-${steadiness(e)}` + (e.basis === 'as-shot' ? ' as-shot' : '') + (e.automatic ? '' : ' not-auto') + (same(e.id, state.active) ? ' picked' : ''),
          style: `background:${rgb(e.srgb)}`, 'data-entry': e.id, title, 'aria-label': title, 'aria-pressed': same(e.id, state.active) ? 'true' : 'false',
          onClick: () => setActive(e.id)});
      }));
    }

    /** Edge neighbors in the current split version: one request per version; neighbors remain unknown while it runs (a corner is not an edge). */
    async function loadNear() {
      const key = `${id}:${j.document.version}`;
      if (key === nearKey) return;
      nearKey = key; near = null; nearFailed = false;
      syncSelection();
      let got = null, failed = false;
      try { got = (await neighbours(j)).neighbours; } catch (e) { failed = true; }
      if (key !== nearKey) return;                            // the version changed while loading
      near = got; nearFailed = failed;
      syncSelection();
    }

    /** Whether the selection shares connected edges; null while neighbors are unknown. */
    function connected(ids) {
      if (!near) return null;
      const wanted = new Set(ids), seen = new Set([ids[0]]), queue = [ids[0]];
      while (queue.length) {
        for (const other of near[queue.pop()] || []) {
          if (wanted.has(other) && !seen.has(other)) { seen.add(other); queue.push(other); }
        }
      }
      return seen.size === wanted.size;
    }

    /** The selection's source colour for choosing: the mean Lab of the selected regions' source colours (the window lists the nearest first). */
    function selectionLab(ids) {
      const labs = ids.map((rid) => (lookup(rid, colourOf.get(rid)).c || {}).lab).filter(Boolean);
      return labs.length ? [0, 1, 2].map((i) => labs.reduce((t, l) => t + l[i], 0) / labs.length) : [50, 0, 0];
    }
    /** The titanium colour all selected regions share, or null: the window marks it as the current one. */
    function commonEntry(ids) {
      const found = new Set(ids.map((rid) => lookup(rid, colourOf.get(rid)).entryId || null));
      return found.size === 1 ? [...found][0] : null;
    }

    /** One selected region split again into finer regions by colour (work-size-and-splitting-a-region-again, REQ-002): the window asks
        into how many colours; the largest part keeps the region's id and colour, the others take the nearest titanium colours. */
    function splitFiner(rid) {
      // a whole number from 2 to 8 (vector_job._split_region); a wrong one is refused beside the box and stays in it, and so is a refusal of the server
      const form = Forms.create();
      const count = Forms.numberInput(Forms.QUANTITIES.splitColours, {value: '3'});
      const countField = form.add('colours', 'Number of colors', count, {quantity: 'splitColours', required: true});
      const box = App.modal('Split region into smaller pieces', h('div', {class: 'stack'},
        h('p', {class: 'small muted'}, 'The image inside the region is divided into the specified number of colors using the finest grid; each connected piece '
          + 'becomes its own region. The outer boundary and neighbors remain unchanged. The largest piece retains the region number; pieces of its '
          + 'color retain the region color, and each other color becomes a new palette color with the nearest titanium color. Undo is available (Ctrl+Z).'),
        countField, form.error), [
        {label: 'Cancel', run: (m) => m.close()},
        {label: 'Split', cls: 'primary', run: async (m) => {
          const v = form.collect();
          if (!v) return;
          const before = j.document.regions;
          const ok = await act({op: 'split_region', region: rid, colours: v.colours}, null, form);
          if (ok) { toast(`Region split into ${j.document.regions - before + 1} pieces`, 'ok'); m.close(); }
        }}]);
      if (count.select) count.select();
      return box;
    }

    function syncInspector() {
      const textSelected = !!lettering.selected();
      const ids = [...state.selection];
      const zones = ids.map((rid) => lookup(rid, colourOf.get(rid)).zone);
      const zone = zones.length && zones.every((item) => item && item === zones[0]) ? zones[0] : null;
      inspector.hidden = !textSelected && !state.selection.size;
      selectionBox.hidden = textSelected;
      lettering.fields.hidden = !textSelected;
      inspectorStatus.textContent = textSelected ? 'Inscription selected' : zone ? `Photo zone ${zone.number} selected` : state.selection.size ?
        `${state.selection.size} ${state.selection.size === 1 ? 'region' : 'regions'} selected` : 'Nothing selected';
    }

    function syncSelection() {
      const ids = [...state.selection];
      const active = document.activeElement;
      const focusedLabel = active && selectionBox.contains(active) ? active.getAttribute('aria-label') : null;
      const openGroups = new Set([...selectionBox.querySelectorAll('details')].filter((node) => node.open)
        .map((node) => node.querySelector('summary')?.textContent));
      const link = ids.length > 1 ? connected(ids) : null;
      const checking = ids.length > 1 && link === null && !nearFailed;      // merge is offered only for a connected selection (DEC-080)
      const why = link === false ? 'Cannot merge: selected regions do not share connected edges; touching at a corner is not enough.'
        : checking ? 'Checking which regions share an edge…'
          : ids.length > 1 && nearFailed ? 'Could not check neighboring regions; the server will validate the merge.' : null;
      const zones = j.zones || [];
      const zoned = ids.filter((rid) => lookup(rid, colourOf.get(rid)).zone);
      const selectedZones = new Set(zoned.map((rid) => lookup(rid, colourOf.get(rid)).zone));
      const selectedZone = ids.length && zoned.length === ids.length && selectedZones.size === 1 ? [...selectedZones][0] : null;
      const region = ids.length === 1 && !selectedZone ? lookup(ids[0], colourOf.get(ids[0])) : null;
      fill(selectionBox, h('h4', {}, 'Selection'),
        selectedZone ? photo.inspect(selectedZone) : null,
        region ? h('div', {class: 'stack vw-ed-region-properties'}, h('strong', {}, `Region ${ids[0]}`),
          h('p', {class: 'small'}, `Source color #${Number(colourOf.get(ids[0])) + 1}`,
            region.c ? ` · ${labText(region.c.lab)}` : ''),
          h('p', {class: 'small'}, 'Engraving color: ', region.excluded ? 'Excluded' : region.missing || !region.entry ? 'No measured color' :
            [h('span', {class: 'sw', style: `background:${rgb(region.entry.srgb)}`}), ' ', labText(region.entry.lab)])) : null,
        ids.length ? h('p', {class: 'small'}, `Selected regions: ${ids.length}` + (zoned.length ? `, in photo zones: ${zoned.length}` : ''))
          : h('p', {class: 'small muted'}, 'Click a region to select it, Shift-click to add or remove it, or drag to use the lasso. '
            + 'Hold Shift to add, Alt to remove, and press Escape to clear the selection.'),
        ids.length ? h('div', {class: 'row'},
          tools.pick ? btn('Color selection…', () => tools.pick(j, `Titanium color for selected regions (${ids.length})`, selectionLab(ids), commonEntry(ids),
            (entryId) => act({op: 'paint', scope: 'region', regions: ids, entry_id: entryId})), 'primary') : null,
          btn('Merge regions', () => act({op: 'merge_regions', regions: ids}), '', ids.length < 2 || link === false || checking),
          btn('Split finer…', () => splitFiner(ids[0]), '', ids.length !== 1),
          btn('Exclude from engraving', () => act({op: 'exclude_region', regions: ids})), btn('Include in engraving', () => act({op: 'include_region', regions: ids})),
          btn('Clear selection', clearSelection)) : null,
        ids.length ? h('div', {class: 'row vw-ed-photo-acts'},
          btn('Create photo zone', () => act({op: 'photo_add', regions: ids}, () => sideTabs.select('photo')), 'primary'),
          zones.map((z) => btn(`Add to photo zone ${z.number}`, () => act({op: 'photo_add', regions: ids, zone: z.number}))),
          zoned.length ? btn('Return to colors', () => act({op: 'photo_remove', regions: zoned})) : null) : null,
        ids.length && !zones.length ? h('p', {class: 'small muted'}, 'Create a photo zone to engrave the image in the selected regions. '
          + 'Its engraving kind and scale are available on the Photo tab.') : null,
        ids.length === 1 ? h('p', {class: 'small muted'}, 'Merge requires at least two regions that share an edge. Split finer divides the selected region by color.') : null,
        ids.length > 1 ? h('p', {class: 'small muted'}, 'Select one region to split it finer.') : null,
        why ? h('p', {class: 'small muted'}, why) : null);
      for (const node of selectionBox.querySelectorAll('details')) if (openGroups.has(node.querySelector('summary')?.textContent)) node.open = true;
      if (focusedLabel) {
        const replacement = [...selectionBox.querySelectorAll('input, select, button')].find((node) => node.getAttribute('aria-label') === focusedLabel);
        if (replacement) replacement.focus();
      }
      if (ready) renderRegions();                              // the lines of the region list say which are chosen
      syncInspector();
    }

    function syncTotals() {
      const t = j.totals || {};
      const zones = (j.zones || []).length;
      fill(totals, `Layers ${(t.recipes ?? (j.layers || []).length) + zones} of ${j.layer_cap}` + (zones ? ` (photo zones ${zones})` : '')
        + ` · color layer time ${duration(t.seconds)} · mean ΔE ${num(t.mean_delta_e)}`,
        t.colours ? ` · colors within tolerance ${t.within_tolerance} of ${t.colours}` : null);
      undoBtn.disabled = !(j.undo > 0);
      redoBtn.disabled = !(j.redo > 0);
      undoBtn.setAttribute('title', `Undo (Ctrl+Z); steps: ${j.undo || 0}`);
      redoBtn.setAttribute('title', `Redo (Ctrl+Shift+Z); steps: ${j.redo || 0}`);
    }

    /** While the pointer is over a line of ``list``, the regions ``regionsOf(its key)`` are outlined on the picture (the list draws its lines
        anew, so the list itself listens). */
    function outlineRows(list, regionsOf) {
      let over = null;
      const enter = (ev) => {
        const line = ev.target && ev.target.closest ? ev.target.closest('.lst-row') : null;
        const key = line ? line.getAttribute('data-key') : null;
        if (key === over) return;
        over = key;
        if (key == null) refreshHover(); else setHot(regionsOf(key));
      };
      const leave = () => { over = null; refreshHover(); };
      list.el.addEventListener('mouseover', enter);
      list.el.addEventListener('focusin', enter);              // the keyboard outlines a line's regions as the pointer does
      list.el.addEventListener('mouseleave', leave);
      list.el.addEventListener('focusout', (ev) => { if (!ev.relatedTarget || !list.el.contains(ev.relatedTarget)) leave(); });
    }

    /** The colour layers, then the photo zones, as the lines of the layers' list: what each sorts and is searched by. */
    function layerItems() {
      const layers = j.layers || [];
      const regionsOf = (l) => (Array.isArray(l.regions) ? l.regions : byEntry.get(String(l.entry_id)) || []);
      const items = [...layers.map((l, pos) => {
        const e = j.entries[l.entry_id] || l, rate = e.time_s_per_cm2 ?? l.time_s_per_cm2;
        const name = l.index != null ? `C${String(l.index).padStart(2, '0')}` : '';
        return {key: 'layer:' + l.entry_id, pos, layer: l, regions: () => regionsOf(l), area: l.area_mm2,
          seconds: rate == null || l.area_mm2 == null ? null : rate * l.area_mm2 / 100, search: `${name} ${l.name || ''}`};
      }), ...(j.zones || []).map((z, i) => ({key: 'zone:' + z.number, pos: layers.length + i, zone: z, regions: () => z.regions, area: z.area_mm2,
        seconds: null, search: `Photo zone ${z.number} ${VectorPhoto.zoneSummary(z)}`}))];
      layerRegions = new Map(items.map((x) => [x.key, x.regions]));
      return items;
    }

    /** A layer on one line: the box that marks it for a merge, its colour (a press makes it the active colour), C01, the length of its rows,
        then its area, regions, inscriptions and time; a photo zone: its picture, its number, kind, area and regions. */
    function layerRow(x) {
      if (x.zone) {
        const z = x.zone;
        return [z.picture ? h('img', {class: 'vw-ed-zone-chip', src: z.picture, alt: ''}) : h('span', {class: 'sw'}),
          h('strong', {}, `Photo zone ${z.number}`), h('span', {class: 'lst-text muted'}, `${VectorPhoto.zoneSummary(z)} · ${area(z.area_mm2)} · regions ${z.regions.length}`)];
      }
      const l = x.layer, key = String(l.entry_id), e = j.entries[l.entry_id] || l;
      const count = Array.isArray(l.regions) ? l.regions.length : (l.region_count ?? x.regions().length);
      return [inRow(h('input', {type: 'checkbox', checked: state.layers.has(key), 'aria-label': `Mark layer ${l.name || key}`,
          onChange: (ev) => { mark(state.layers, key, ev.target.checked); syncLayerMerge(); }})),
        inRow(h('button', {type: 'button', class: 'vw-swatch', style: `background:${rgb(l.srgb || e.srgb)}`, title: 'Make active color',
          'aria-label': `Make layer color active ${l.name || key}`, onClick: () => setActive(l.entry_id)})),
        l.index != null ? h('strong', {}, `C${String(l.index).padStart(2, '0')}`) : null,
        sizeNote(l.size),
        h('span', {class: 'lst-text muted'}, `${area(l.area_mm2)} · regions ${count}` + ((l.texts || []).length ? ` · inscriptions ${l.texts.length}` : '')
          + ` · ${x.seconds == null ? 'time not estimated' : duration(x.seconds)}`)];
    }

    /** What a layer's line opens: the layer's name in the file, its recipe, the length of its rows and where its colour is known from. */
    function layerDetails(x) {
      if (x.zone) {
        return h('p', {class: 'small muted'}, `Photo zone ${x.zone.number}: ${VectorPhoto.zoneSummary(x.zone)}. Mode, scale, and powers are on the Photo tab.`);
      }
      const l = x.layer, e = j.entries[l.entry_id] || null, says = sizeSays(l.size);
      return h('div', {class: 'stack small'}, l.name ? h('div', {}, l.name) : null,
        e && e.parameters ? h('div', {class: 'muted'}, `recipe: ${params(e.parameters)}`) : null,
        says ? h('div', {class: l.size.how === 'measured' ? 'muted' : 'vw-bad'}, says) : null,
        e && e.sources ? h('div', {class: 'muted'}, pill(...STEADY[steadiness(e)]), ' ', `${originText(e.sources)} · ${App.agreed(e.agreement)}`) : null);
    }

    function renderLayers() {
      const layers = j.layers || [];
      layerList.items = layerItems();
      layerList.refresh();
      const away = layers.filter((l) => l.size && l.size.how !== 'measured').length;
      fill(layersAbout, away ? h('details', {class: 'small alert warn'},
        h('summary', {}, `${away} of ${layers.length} layers: color was not measured at their row length (↔)`), h('p', {}, SIZE_ABOUT)) : null);
      syncLayerMerge();
    }

    function syncLayerMerge() {
      const chosen = (j.layers || []).filter((l) => state.layers.has(String(l.entry_id)));
      if (chosen.length < 2) return fill(layerMerge, h('p', {class: 'small muted'}, 'Mark two or more layers to merge them into one titanium color.'));
      const biggest = chosen.reduce((a, b) => ((b.area_mm2 || 0) > (a.area_mm2 || 0) ? b : a));
      const target = h('select', {'aria-label': 'Titanium color for marked layers'}, chosen.map((l) => h('option',
        {value: String(l.entry_id), selected: l === biggest}, [l.index != null ? `C${String(l.index).padStart(2, '0')}` : `№ ${l.entry_id}`, area(l.area_mm2)].join(' · '))));
      fill(layerMerge, h('div', {class: 'vw-ed-merge'}, h('span', {class: 'small'}, 'Keep color:'), target,
        btn('Merge into one', () => act({op: 'merge_titanium', entries: chosen.map((l) => l.entry_id), into: chosen.find((l) => String(l.entry_id) === target.value).entry_id},
          () => { state.layers = new Set(); renderLayers(); }), 'primary')));
    }

    /** A source colour on one line: the box that marks it for a merge, the colour (a press puts the palette in order by it), the titanium
        colour it is engraved with, its number, ΔE, whether it is beyond the tolerance or chosen by hand, and its regions. */
    function colourRow(c) {
      const k = Number(c.index), e = c.entry_id == null ? null : j.entries[c.entry_id];
      const excluded = c.status === 'excluded', byHand = c.status === 'hand' || c.status === 'accepted';
      return [inRow(h('input', {type: 'checkbox', checked: state.colours.has(k), 'aria-label': `Mark source color #${k + 1}`,
          onChange: (ev) => { mark(state.colours, k, ev.target.checked); syncColourMerge(); }})),
        inRow(h('button', {type: 'button', class: 'vw-swatch', style: `background:${rgb(c.srgb)}`, title: `${labText(c.lab)} · sort palette by this color`,
          'aria-label': `Source color #${k + 1}: sort palette by it`, onClick: () => setRef(k)})),
        '→', e ? chip(e.srgb, labText(e.lab)) : h('span', {class: 'muted'}, excluded ? 'not engraved' : 'no color'),
        h('strong', {}, `№ ${k + 1}`),
        c.delta_e == null ? null : h('span', {}, `ΔE ${num(c.delta_e)}`),
        c.outside_tolerance ? pill('outside tolerance', 'bad') : null,
        byHand ? pill('manual') : c.status === 'missing' ? pill('titanium color no longer available', 'bad') : null,
        h('span', {class: 'lst-text muted'}, `regions ${c.regions}`)];
    }

    /** The action of a source colour's line: another titanium colour, or for a colour left out, engrave it again. */
    function colourActions(c) {
      const k = Number(c.index);
      const choose = titled(btn('Select regions', () => selectOnly(byColour.get(k) || []), '', !(byColour.get(k) || []).length), 'Select all regions of this source color on the canvas');
      if (c.status === 'excluded') return [choose, titled(btn('Engrave', () => act({op: 'include_colour', colour: k})), 'Return regions of this color to the file')];
      return [choose, ...(tools.pick ? [titled(btn('Replace', () => tools.pick(j, `Group color #${k + 1}`, c.lab, c.entry_id, (entryId) => act({op: 'set_colour', colour: k, entry_id: entryId}))),
        'Choose another titanium color, with its evidence and stability')] : [])];
    }

    /** A layer's (or a photo zone's) regions chosen on the picture, where the action on them is. */
    function layerActions(x) {
      const ids = x.regions();
      return [titled(btn('Select regions', () => selectOnly(ids), '', !ids.length), 'Select all regions of this layer on the canvas')];
    }

    /** A region on one line: its colour, its number, its source colour and what it is engraved with (or why it is not). */
    function regionRow(x) {
      const r = x.r, e = r.entry, on = state.selection.has(x.id);
      const shown = r.zone ? 'rgba(0,0,0,0)' : r.excluded ? EXCLUDED : r.missing || !e ? MISSING : rgb(e.srgb);
      return [h('span', {class: 'sw', style: `background:${shown}`, 'aria-hidden': 'true'}), h('strong', {}, x.id),
        h('span', {class: 'lst-text muted'}, [`source color #${x.k + 1}`,
          r.zone ? `photo zone ${r.zone.number}` : r.excluded ? 'not engraved' : r.missing || !e ? 'titanium color is no longer among measurements'
            : `titanium ${labText(e.lab)}` + (r.c ? `, ΔE ${num(de(r.c.lab, e.lab))}` : ''), on ? 'selected' : null].filter(Boolean).join(' · '))];
    }
    function regionActions(x) {
      const on = state.selection.has(x.id);
      const b = btn(on ? 'Deselect' : 'Select', () => toggleRegion(x.id), 'btn-small');
      b.setAttribute('aria-pressed', String(on));
      b.setAttribute('aria-label', `${on ? 'Deselect region' : 'Select region'} ${x.id}`);
      return [b];
    }
    function renderRegions() {
      regionList.items = [...paths.keys()].map((rid, pos) => { const k = colourOf.get(rid); return {id: rid, pos, k, r: lookup(rid, k), search: `${rid} source color #${k + 1}`}; });
      regionList.refresh();
      fill(regionNote, state.selection.size ? `Selected regions: ${state.selection.size}. Actions are on the Brush tab (Photo for photo zones); the button below opens them.`
        : 'Selected regions: 0. Select a region, layer, or source color to mark it on the canvas; the button below opens selection actions.');
    }

    /** What a source colour's line opens: where its titanium colour is known from and its recipe; the choice back to the automatic one and
        leaving the colour out of the file. */
    function colourDetails(c) {
      const k = Number(c.index), e = c.entry_id == null ? null : j.entries[c.entry_id];
      const excluded = c.status === 'excluded', byHand = c.status === 'hand' || c.status === 'accepted';
      return h('div', {class: 'stack small'},
        h('div', {class: 'muted'}, `Source color #${k + 1}: ${labText(c.lab)} · regions ${c.regions}`),
        e && !excluded ? h('div', {class: 'muted'}, pill(...STEADY[steadiness(e)]), ' ', `${originText(e.sources)} · ${App.agreed(e.agreement)}`) : null,
        e && !excluded && e.parameters ? h('div', {class: 'muted'}, `recipe: ${params(e.parameters)}`) : null,
        byHand || !excluded ? h('div', {class: 'row'},
          byHand ? titled(btn('Automatic', () => act({op: 'set_colour', colour: k, entry_id: null})), 'Restore automatic color selection') : null,
          excluded ? null : titled(btn('Do not engrave', () => act({op: 'exclude_colour', colour: k})), 'All regions of this color are excluded from the file; only cleaning remains'))
          : null);
    }

    function renderColours() {
      colourList.items = j.colours;
      colourList.refresh();
      syncColourMerge();
    }

    function syncColourMerge() {
      const chosen = j.colours.map((c) => Number(c.index)).filter((k) => state.colours.has(k));
      fill(colourMerge, chosen.length < 2 ? h('p', {class: 'small muted'}, 'Mark two or more source colors to merge them.')
        : h('div', {class: 'vw-ed-merge'}, btn('Merge source colors', () => act({op: 'merge_colours', colours: chosen},
          () => { state.colours = new Set(); renderColours(); }), 'primary'), h('span', {class: 'small muted'}, `marked: ${chosen.length}`)));
    }

    function syncFarNote() {
      const o = j.outside, tol = j.settings.tolerance_de;
      const limit = tol == null ? 'ΔE tolerance' : `ΔE tolerance ${tol}`;
      fill(farNote, o && o.colours ? `Beyond ${limit}: ${o.colours} colors, ${o.regions} regions (${num(o.share * 100, 1)}% of area). These do not block the file.`
        : farCount ? `Regions beyond ${limit}: ${farCount}. These do not block the file.` : `All colors are within ${limit}.`);
    }

    function syncPanel() {
      syncTotals();
      syncSelection();
      syncActive();
      loadPalette();
      renderLayers();
      renderColours();
      renderRegions();
      syncFarNote();
    }

    /** After an action, recolor in place or load the new split version. */
    function update(next) {
      j = next;
      lookup = resolver(j);
      reach.clear();
      const known = new Set(j.colours.map((c) => Number(c.index)));
      if (state.ref != null && !known.has(state.ref)) state.ref = null;
      state.colours = new Set([...state.colours].filter((k) => known.has(k)));
      const inUse = new Set((j.layers || []).map((l) => String(l.entry_id)));
      state.layers = new Set([...state.layers].filter((e) => inUse.has(e)));
      if (loadedVersion !== geometryKey(j)) {
        const resized = loadedWidth !== null && Math.abs(loadedWidth - j.document.size_mm.width) > 1e-6;   // the work's size changed (REQ-001)
        load().then(() => { if (resized && loadedVersion === geometryKey(j)) fit(); });
      } else { paint(); showZones(); refreshHover(); }
      loadNear();
      syncPanel();
      photo.update(j);
      lettering.update(j);
    }

    const editor = {el, update, key(ev) {
      if (!el.isConnected) { if (current === editor) current = null; return; }
      if (document.querySelector('.modal-bg')) return;
      if (ev.key === 'Escape' && panelOpen && narrow()) return closePanel(true);        // the slide-out first, the selection on a second press
      if (ev.key === 'Escape') return sideTab === 'texts' && lettering.escape() ? undefined : dropSelection();   // in a field too: Escape means nothing there
      const t = ev.target;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '') || t.isContentEditable)) return;   // input fields handle their own keys
      const z = ev.code === 'KeyZ' || (ev.key || '').toLowerCase() === 'z', y = ev.code === 'KeyY' || (ev.key || '').toLowerCase() === 'y';
      // Space is «pan with the drag» only for the pointer: on a button, a tab, a line of a list it presses it (preventing it here left every button dead)
      const roled = t && t.closest ? t.closest('[role]') : null;
      const onControl = !!(t && t.closest && (t.closest('button, summary, a[href]') || (roled && /^(tab|option|button|checkbox|radio|switch|menuitem)$/.test(roled.getAttribute('role')))));
      if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (z || y)) { ev.preventDefault(); undoRedo(z && !ev.shiftKey ? 'undo' : 'redo'); }
      else if (ev.code === 'Space' && onControl) return;
      else if (ev.code === 'Space' && !ev.repeat) { ev.preventDefault(); spaceHeld = true; stage.classList.add('pan-ready'); }
      else if (ev.code === 'Space') ev.preventDefault();
    }, keyup(ev) {
      if (ev.code === 'Space') { spaceHeld = false; stage.classList.remove('pan-ready'); }
    }};
    current = editor;

    setTool(sideTab === 'photo' ? 'select' : state.tool);
    ready = true;
    setScope(state.scope);
    setView(state.view);
    fit();
    load();
    loadNear();
    syncPanel();
    return editor;
  }

  return {create, splitSvg, palette, rgb, chip, params, seconds, de, duration, area, BASIS, COLOUR_FILTER, COLOUR_SORTS, inRow};
})();
