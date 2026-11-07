/* The business-card editor (feature-2, REQ-001..005): one screen for the whole window. The top bar holds the card's name, undo and redo, the
   state of saving, the Front and Back tabs, the card size and the two LightBurn files; the left column adds elements and lists the layers of
   the side; the centre is the card itself (CardCanvas draws what the server computed and reports what was done on it); the right column
   edits the selected element or, with nothing selected, the engraving settings and the review of each side.

   Every change is one ``POST /edit`` handed to the document tracker (save-state.js): changes are sent one after another in the order made,
   the screen is drawn from the answer to the last of them (an older answer never replaces a newer one), and a change that failed stays in
   its control with the error beside the card and a way to retry. The panels are in card-panels.js. */
'use strict';
const CardWork = (() => {
  const {h, fill, btn, field, get, post, toast, fail, modal, confirmBox} = App;
  const P = CardPanels;
  const {SIDE_NAME, TYPE_NAME, Q} = P;
  const SIDES = Object.keys(SIDE_NAME);
  const PRESETS = [['85x53', '85 × 53 mm'], ['85x54', '85 × 54 mm'], ['custom', 'Custom size']];          // card_work.PRESETS, and a card of any size
  const PICTURES = 'image/png,image/jpeg,image/gif,image/bmp,image/tiff,image/webp';
  const LIBRARY_KEY = {shape: 'kind', frame: 'style', icon: 'name'};                                        // the name of the item in the element's payload
  const ADD = [['text', 'Text'], ['shape', 'Shape'], ['frame', 'Frame'], ['icon', 'Icon'], ['image', 'Image'], ['generate', 'Generate'], ['qr', 'QR code']];
  const ORDER = [['front', 'To front'], ['forward', 'Forward'], ['backward', 'Backward'], ['back', 'To back']];
  const CARD_OPS = new Set(['settings_add', 'settings_set', 'settings_delete', 'set_size', 'settings_apply', 'settings_confirm', 'settings_custom', 'set_setup']);   // edits of the card, not of a side
  const FIELD_NAME = {name: 'Name', x: 'Center X, mm', y: 'Center Y, mm', width: 'Width, mm', height: 'Height, mm', rotation: 'Rotation, degrees', settings_id: 'Engraving settings',
    'text.text': 'Text', 'text.font': 'Font', 'text.height_mm': 'Letter height, mm', 'text.width_pct': 'Letter width, %', 'text.spacing_mm': 'Letter spacing, mm',
    'text.line_pct': 'Line spacing, %', 'text.align': 'Alignment', 'qr.kind': 'QR content type', 'qr.ecc': 'QR error correction', 'image.engrave': 'Engrave as'};
  const SETTING_NAME = {name: 'Name', mode: 'Mode', power: 'Power, %', speed: 'Speed, mm/s', frequency: 'Frequency, kHz', pulse_width: 'Pulse width, ns',
    line_interval: 'Line interval, mm', passes: 'Passes', min_power: 'Minimum power, %', scan_angle: 'Scan angle, degrees', dot_width: 'Dot width, mm', dither: 'Image mode'};
  const dig = (object, path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), object);
  const mm = (v) => String(+(+v).toFixed(1));
  let keys = null;                                           // keyboard shortcuts of the open card, as in the other work screens
  document.addEventListener('keydown', (ev) => { if (keys) keys(ev); });
  let sequence = 0;

  // ---- what a stored field is called and what it holds: for the messages of the tracker --------------------------------------------------
  /** The value the work has for a field the tracker names (``e3:text.text``, ``s2:power``), so that its messages can say “was” and “is”. */
  function valueAt(view, key) {
    const at = key.indexOf(':'), owner = key.slice(0, at), path = key.slice(at + 1);
    if (/^s\d+$/.test(owner)) { const set = view.settings.find((s) => `s${s.id}` === owner); return set ? set[path] : undefined; }
    for (const side of SIDES) { const e = view.sides[side].elements.find((x) => x.id === owner); if (e) return dig(e, path); }
    return undefined;
  }
  /** The parameters the library has for an element: a shape, frame or icon has them per item, a picture has one list. */
  function paramsOf(lib, element) {
    if (element.type === 'image') return (lib.image && lib.image.params) || [];
    const items = Array.isArray(lib[element.type]) ? lib[element.type] : [];
    const item = items.find((i) => i.name === (element[element.type] || {})[LIBRARY_KEY[element.type]]);
    return item ? item.params : [];
  }
  function nameOf(view, lib, key) {
    const at = key.indexOf(':');
    if (at < 0) return key;
    const owner = key.slice(0, at), path = key.slice(at + 1);
    if (/^s\d+$/.test(owner)) {
      const set = view.settings.find((s) => `s${s.id}` === owner);
      return `${set ? set.name : 'Settings'}: ${SETTING_NAME[path] || path}`;
    }
    const element = SIDES.flatMap((s) => view.sides[s].elements).find((x) => x.id === owner);
    const spec = element && paramsOf(lib, element).find((p) => `${element.type}.${p.name}` === path);
    const what = FIELD_NAME[path] || (spec && spec.label) || (path.startsWith('qr.fields.') ? path.slice(10) : path);
    return element ? `${element.name}: ${what}` : what;
  }
  /** The work as the tracker keeps it: the view itself, which also answers the field keys above. */
  const wrap = (view) => new Proxy(view, {get: (t, k) => (typeof k === 'string' && k.includes(':') ? valueAt(t, k) : t[k])});

  // ---- the size of a card: presets and a custom size, in the dialog of a new card and in the one of the editor ------------------------------------
  /** The size fields: a choice of presets and, for a custom size, a width and a height in mm. Registers in ``form`` (Forms.create). */
  function sizeFields(form, initial) {
    const group = `cw-size-${++sequence}`;
    let chosen = initial.preset;
    const width = Forms.numberInput(Q.cardWidth, {step: '0.1', value: mm(initial.width)}), height = Forms.numberInput(Q.cardHeight, {step: '0.1', value: mm(initial.height)});
    const custom = () => chosen === 'custom';
    const read = (input, q) => () => (custom() ? Forms.readNumber(input, q, {required: true}) : {ok: true, value: null});
    const pair = h('div', {class: 'toolbar'}, form.add('width_mm', 'Width', width, {quantity: Q.cardWidth, required: true, read: read(width, Q.cardWidth)}),
      form.add('height_mm', 'Height', height, {quantity: Q.cardHeight, required: true, read: read(height, Q.cardHeight)}));
    const radios = PRESETS.map(([id, label]) => h('label', {class: 'row small cw-radio'},
      h('input', {type: 'radio', name: group, value: id, 'aria-label': label, checked: id === chosen, onChange: () => { chosen = id; sync(); }}), h('span', {}, label)));
    function sync() {
      for (const r of radios) { const input = r.querySelector('input'); input.checked = input.value === chosen; }
      pair.hidden = !custom();
    }
    sync();
    return {el: h('div', {class: 'stack'}, h('div', {class: 'row', role: 'radiogroup', 'aria-label': 'Card size'}, radios), pair),
      body: (v) => ({preset: chosen, ...(custom() ? {width_mm: v.width_mm, height_mm: v.height_mm} : {})})};
  }

  /** The dialog of a new business card (opened from “New work” of the works list): a name and a size; the editor opens on the new card. */
  function newDialog() {
    const form = Forms.create();
    const input = h('input', {type: 'text', value: 'Business card', autocomplete: 'off', 'aria-label': 'Card name', onKeydown: (ev) => { if (ev.key === 'Enter' && !ev.isComposing) { ev.preventDefault(); save(box.close).catch(fail); } }});
    const name = form.add('name', 'Name', input, {required: true, read: () => (input.value.trim() ? {ok: true, value: input.value.trim()} : {ok: false, message: 'Enter a card name'})});
    const size = sizeFields(form, {preset: '85x53', width: 85, height: 54});
    let saving = false, box = null;
    async function save(close) {
      if (saving) return;
      const v = form.collect();
      if (!v) return;
      saving = true;
      try {
        const made = await post('/card-works', {name: v.name, ...size.body(v)});
        close();
        toast('Business card created', 'ok');
        App.go('/card-work?work=' + made.id);
      } catch (e) { saving = false; form.fail(e); }
    }
    box = modal('New business card', h('div', {class: 'stack'}, name, size.el, form.error),
      [{label: 'Cancel', run: (m) => m.close()}, {label: 'Create card', cls: 'primary', run: (m) => save(m.close)}]);
    if (input.select) input.select();
  }

  // ---- the screen ---------------------------------------------------------------------------------------------------------------------
  function screen(first, lib) {
    const id = first.id, base = `/card-works/${id}`;
    let view = first, side = 'front', selection = [], grid = true, pendingSelect = null, canvas = null, inspected = null, shownName = null, disposed = false;
    const root = h('div', {class: 'os cw'});

    // -- the document: every change goes through the tracker
    async function send(request) {
      let next;
      try { next = request.upload ? await App.form(request.path, request.upload) : await post(request.path, request.body); }
      catch (e) {
        if (!request.soft) throw e;
        request.refusal = e;                                 // told beside the form that asked, not as a failure of the card: nothing changed
        return wrap(view);
      }
      request.refusal = null;
      view = next;
      if (request.select && next.added && next.added.length) pendingSelect = {side: request.side, ids: next.added};
      return wrap(next);
    }
    const names = new Proxy({}, {get: (_, key) => (typeof key === 'string' ? nameOf(view, lib, key) : undefined)});
    const doc = SaveState.create({label: 'Card', confirmed: wrap(first), names, send, apply: () => paint(),
      reload: async () => { view = await get(base); doc.adopt(wrap(view)); },
      onOrphanFailure: (lost) => { if (typeof Operations !== 'undefined') Operations.report({title: `Card “${view.name}”: changes not saved`, message: `${lost.message} ${lost.describe}`.trim(),
        context: {route: `/card-work?work=${id}`, label: 'Business card'}, recover: {label: 'Open card', route: `/card-work?work=${id}`}, details: [['Card', `#${id}`]]}); }});
    const local = () => doc.local();

    /** One edit of the work, on the side shown. Resolves to the error, or to null when the server took it. ``local`` is the field as the person
        left it ({key: value}); only an edit that can be sent twice has it (a retry sends it again). */
    function edit(body, o = {}) {
      const request = {path: `${base}/edit`, body: CARD_OPS.has(body.op) ? body : {side, ...body}, side, select: !!o.select};
      return doc.edit(request, {local: o.local || null, keys: o.keys, calculates: true, retryable: o.retryable ?? !!o.local});
    }
    /** A request whose refusal is told beside the form that made it (a picture, a description, the card size): the error, or null. */
    async function soft(request, o = {}) {
      const asked = {...request, soft: true, side, select: true};
      const error = await doc.edit(asked, {calculates: true, retryable: false, ...o});
      return error || asked.refusal || null;
    }
    const step = (kind) => ((view[`can_${kind}`] || doc.status() !== 'saved') ? doc.edit({path: `${base}/${kind}`, body: {}}, {calculates: true, retryable: false}) : Promise.resolve(null));

    const sideElements = () => view.sides[side].elements;
    const elementById = (elementId) => SIDES.flatMap((s) => view.sides[s].elements).find((e) => e.id === elementId);
    const selected = () => sideElements().filter((e) => selection.includes(e.id));
    const settingsName = (settingsId) => (view.settings.find((s) => s.id === settingsId) || {}).name;
    const expand = (ids) => {                                  // choosing one member of a group chooses the group, as on the canvas
      const groups = new Set(sideElements().filter((e) => ids.includes(e.id) && e.group).map((e) => e.group));
      return sideElements().filter((e) => ids.includes(e.id) || (e.group && groups.has(e.group))).map((e) => e.id);
    };

    // -- editing one field of one element, and the engraving settings
    function setField(e, path, value) {
      const local_ = {[`${e.id}:${path}`]: value}, parts = path.split('.');
      if (path === 'width' || path === 'height') {            // the server keeps a QR code square at the larger of the two sides, so both go with it
        return edit({op: 'resize', id: e.id, ...(e.type === 'qr' ? {width: value, height: value} : {[path]: value})}, {local: local_});
      }
      if (path === 'rotation') return edit({op: 'rotate', id: e.id, rotation: value}, {local: local_});
      return edit({op: 'set', id: e.id, changes: parts.length === 1 ? {[path]: value} : {[parts[0]]: {[parts[1]]: value}}}, {local: local_});
    }
    /** One field of a QR code. The server takes the fields whole, so the others go with it: as stored, laid over by what is still on its way. */
    function setQr(e, name, value) {
      const fields = {...elementById(e.id).qr.fields}, prefix = `${e.id}:qr.fields.`;
      for (const [k, v] of Object.entries(local())) if (k.startsWith(prefix)) fields[k.slice(prefix.length)] = v;
      fields[name] = value;
      return edit({op: 'set', id: e.id, changes: {qr: {fields}}}, {local: {[prefix + name]: value}});
    }
    const setQrKind = (e, kind) => edit({op: 'set', id: e.id, changes: {qr: {kind, fields: {}}}}, {local: {[`${e.id}:qr.kind`]: kind}});
    const setSettings = (settingsId, changes) => {
      const [field_, value] = Object.entries(changes)[0];
      return edit({op: 'settings_set', id: settingsId, changes}, {local: {[`s${settingsId}:${field_}`]: value}});
    };
    function settingsDelete(settingsId) {
      const set = view.settings.find((s) => s.id === settingsId);
      confirmBox(`Delete engraving settings “${set.name}”?`, 'Elements that use them fall back to the default settings. You can undo this change.', 'Delete', async () => {
        const error = await edit({op: 'settings_delete', id: settingsId}, {retryable: false});
        if (error) throw error;
      });
    }
    const assign = (ids, value) => edit({op: 'assign_settings', ids, settings_id: value === '' || value == null ? null : Number(value)},
      ids.length === 1 ? {local: {[`${ids[0]}:settings_id`]: value === '' || value == null ? null : Number(value)}} : {retryable: false});

    // -- selection
    function select(ids) {
      selection = expand(ids);
      if (canvas) canvas.setSelection(selection);
      layers.update(sideElements(), selection);
      paintRight();
    }
    function reveal(where, elementId) {                        // the review names an element of either side
      if (where !== side) { side = where; selection = []; }
      selection = expand([elementId]);
      paint();
    }

    // -- the ready settings of the card's own laser, lens and material: asked for when a chooser first needs them, kept for the setup and the version of
    // the work they were asked for. What was measured for another setup is dropped at once and never shown, whatever answer is still on its way.
    const cache = {key: null, part: null, data: null, json: null, error: null, loading: false, promise: null};
    function choices() {
      const setup = view.setup || {}, part = JSON.stringify([setup.device_id ?? null, setup.lens_id ?? null, setup.material_id ?? null]), key = `${part}@${view.updated_at}`;
      if (cache.key !== key) {
        if (cache.part !== part) { cache.data = null; cache.json = null; }
        Object.assign(cache, {key, part, error: null, loading: true});
        cache.promise = get(`${base}/settings-choices`).then((data) => {
          if (cache.key !== key) return;                          // the card moved on while this was on its way
          cache.loading = false;
          if (data.setup && !CardSettings.sameSetup(data.setup, view.setup)) { cache.error = 'The ready settings do not belong to the laser, lens and material of this card.'; return; }
          const json = JSON.stringify(data);
          if (json !== cache.json) { cache.json = json; cache.data = data; }       // the same answer again changes nothing on the screen
        }, (e) => { if (cache.key === key) { cache.loading = false; cache.error = e.message || String(e); } });
      }
      return cache;
    }
    const env = {lib: () => lib, local, view: () => view, set: (e, path, value) => setField(e, path, value), setQr, setQrKind, select, reveal, settingsName,
      reorder: (elementId, to) => edit({op: 'reorder', id: elementId, to}, {retryable: false}),
      settingsAdd: () => edit({op: 'settings_add'}, {retryable: false}), setSettings: (settingsId, changes) => setSettings(settingsId, changes), settingsDelete,
      setup: () => view.setup, choices, reloadChoices: () => { cache.key = null; },
      applyChoice: (settingsId, choiceId) => edit({op: 'settings_apply', settings_id: settingsId, choice_id: choiceId}, {retryable: false}),
      confirmSettings: (settingsId) => edit({op: 'settings_confirm', settings_id: settingsId}, {retryable: false}),
      customSettings: (settingsId) => edit({op: 'settings_custom', settings_id: settingsId}, {retryable: false}),
      setSetup: (setup) => soft({path: `${base}/edit`, body: {op: 'set_setup', device_id: setup.device_id, lens_id: setup.lens_id, material_id: setup.material_id}})};

    // -- the left column: add, then the layers
    const layers = P.layerList(env);
    const add = (element) => edit({op: 'add', element}, {select: true, retryable: false});
    const addLibrary = (group, item) => add({type: group, [group]: {[LIBRARY_KEY[group]]: item.name}});

    function imagePanel() {
      const input = h('input', {type: 'file', accept: PICTURES, 'aria-label': 'Picture file'});
      const failure = h('p', {class: 'alert bad small', role: 'alert', hidden: true}), state = h('p', {class: 'small muted', role: 'status'});
      input.addEventListener('change', async () => {
        const file = input.files && input.files[0];
        if (!file) return;
        const body = new FormData();
        body.append('side', side);
        body.append('picture', file, file.name);
        failure.hidden = true;
        fill(state, 'Adding the picture…');
        const error = await soft({path: `${base}/images`, upload: body});
        fill(state, null);
        input.value = '';
        if (error) { failure.textContent = error.message || String(error); failure.hidden = false; }
      });
      return h('div', {class: 'stack'}, h('h4', {}, 'Add a picture'), App.filePick(input, 'Choose picture'), state, failure,
        h('p', {class: 'small muted'}, 'PNG, JPEG, GIF, BMP, TIFF or WebP. The picture is traced into shapes that can be engraved; adjust the tracing after it is added, or engrave it as a photo.'));
    }
    const generation = {};
    function generatePanel() {
      const text = h('textarea', {rows: '3', maxlength: '300', 'aria-label': 'Describe the picture'});
      const described = field('Describe the picture', text, null, {required: true, constraint: 'allowed: 3 to 300 characters'});
      let kind = 'icon';
      const kinds = h('div', {class: 'row', role: 'radiogroup', 'aria-label': 'Kind of picture'}, [['icon', 'Icon'], ['drawing', 'Drawing']].map(([value, label]) => h('label', {class: 'row small cw-radio'},
        h('input', {type: 'radio', name: 'cw-generate-kind', value, 'aria-label': label, checked: value === kind, onChange: () => { kind = value; }}), h('span', {}, label))));
      const reason = h('p', {class: 'alert warn small', role: 'status', hidden: true}), failure = h('p', {class: 'alert bad small', role: 'alert', hidden: true});
      const working = h('p', {class: 'small muted', role: 'status', hidden: true}, 'Generating the picture: this can take up to a minute.');
      const go = btn('Generate', async () => {
        const description = text.value.trim();
        described.clearError(); failure.hidden = true;
        if (description.length < 3 || description.length > 300) { described.setError(`Describe the picture in 3 to 300 characters. Entered: ${description.length}`); return; }
        go.disabled = true; go.setAttribute('aria-busy', 'true'); working.hidden = false;
        const error = await soft({path: `${base}/generate`, body: {side, description, kind}});
        go.removeAttribute('aria-busy'); working.hidden = true;
        paintAdd();
        if (error) { failure.textContent = error.message || String(error); failure.hidden = false; } else text.value = '';
      }, 'primary btn-small');
      Object.assign(generation, {reason, go});
      return h('div', {class: 'stack'}, h('h4', {}, 'Generate a picture'), reason, described, kinds, go, working, failure,
        h('p', {class: 'small muted'}, 'The description is sent to the OpenAI image service. The picture is added as an image and traced into shapes.'));
    }
    const stage = h('div', {class: 'cw-stage'});
    const stages = {};
    let open = null;
    const build = {shape: () => h('div', {class: 'stack'}, h('h4', {}, 'Add a shape'), P.picker('shape', lib.shape, (item) => addLibrary('shape', item))),
      frame: () => h('div', {class: 'stack'}, h('h4', {}, 'Add a frame'), P.picker('frame', lib.frame, (item) => addLibrary('frame', item))),
      icon: () => h('div', {class: 'stack'}, h('h4', {}, 'Add an icon'), P.picker('icon', lib.icon, (item) => addLibrary('icon', item))), image: imagePanel, generate: generatePanel};
    const toggles = new Map(ADD.map(([name, label]) => [name, h('button', {type: 'button', class: 'btn btn-small cw-add-btn', 'aria-expanded': name in build ? 'false' : null, onClick: () => {
      if (name === 'text') add({type: 'text'});
      else if (name === 'qr') add({type: 'qr'});
      else { open = open === name ? null : name; paintAdd(); }
    }}, label)]));
    function paintAdd() {
      for (const [name, button] of toggles) if (name in build) button.setAttribute('aria-expanded', String(open === name));
      if (open && !stages[open]) stages[open] = build[open]();
      fill(stage, open ? stages[open] : null);
      if (generation.go) {
        const g = view.generation || {available: false, reason: 'Generation is not available.'};
        generation.reason.textContent = g.available ? '' : g.reason;
        generation.reason.hidden = g.available;
        generation.go.disabled = !g.available || generation.go.getAttribute('aria-busy') === 'true';
      }
    }
    const left = h('div', {class: 'os-col cw-left'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Add')),
      h('div', {class: 'cw-add'}, h('div', {class: 'cw-add-grid', role: 'group', 'aria-label': 'Add to the card'}, [...toggles.values()]), stage),
      h('div', {class: 'os-col-head'}, h('h3', {}, 'Layers'), h('span', {class: 'small muted cw-layer-count'})), h('div', {class: 'os-scroll'}, layers.el));

    // -- the centre: the card
    const host = h('div', {class: 'cw-canvas'});
    const zoom = (factor) => { if (canvas && canvas.setZoom) canvas.setZoom((canvas.getZoom ? canvas.getZoom() : 1) * factor); };
    const gridBox = h('input', {type: 'checkbox', checked: true, 'aria-label': 'Show the grid', onChange: (ev) => { const self = ev.currentTarget; grid = self.checked; paintCanvas(); }});
    const summary = h('span', {class: 'small muted cw-summary'});
    const panel = h('div', {class: 'cw-panel', role: 'tabpanel', id: 'cw-panel'}, host);
    const centre = h('div', {class: 'os-col cw-centre'}, h('div', {class: 'os-col-head'}, summary, h('span', {class: 'spacer'}),
      h('div', {class: 'row cw-tools', role: 'group', 'aria-label': 'View'}, btn('Fit', () => canvas && canvas.fit(), 'btn-small'), btn('Zoom out', () => zoom(0.8), 'btn-small'),
        btn('Zoom in', () => zoom(1.25), 'btn-small'), h('label', {class: 'row small'}, gridBox, h('span', {}, 'Grid')))), panel);
    function paintCanvas() {
      if (canvas) canvas.show({size_mm: view.size_mm, elements: sideElements(), selection, grid});
    }
    const handlers = {
      onSelect: (ids) => { selection = ids; layers.update(sideElements(), selection); paintRight(); },
      onMove: (ids, dx, dy) => edit({op: 'move', ids, dx, dy}, {retryable: false}),
      onResize: (elementId, box) => edit({op: 'resize', id: elementId, ...box}, {retryable: false}),
      onRotate: (elementId, rotation) => edit({op: 'rotate', id: elementId, rotation}, {retryable: false}),
      onDelete: (ids) => edit({op: 'delete', ids}, {retryable: false}),
      onDuplicate: (ids) => edit({op: 'duplicate', ids}, {select: true, retryable: false}),
      onUndo: () => step('undo'), onRedo: () => step('redo'), onEscape: () => select([])};
    canvas = CardCanvas.create(host, handlers);

    // -- the right column: the selected element, or the engraving settings and the review
    const engraving = P.engravingPanel(env);
    const rightTitle = h('h3', {}), rightBody = h('div', {class: 'os-scroll'});
    const right = h('div', {class: 'os-col cw-right'}, h('div', {class: 'os-col-head'}, rightTitle), rightBody);

    function actionsFor(chosen) {
      const ids = chosen.map((e) => e.id), grouped = chosen.some((e) => e.group), alike = new Set(chosen.map((e) => e.group || '')).size === 1 && chosen[0].group;
      const small = (label, run, disabled = false, cls = '') => btn(label, run, `btn-small ${cls}`, disabled);
      return h('div', {class: 'stack cw-actions'},
        h('div', {class: 'row', role: 'group', 'aria-label': 'Layer order'}, ORDER.map(([to, label]) => small(label, () => edit({op: 'reorder', ids, to}, {retryable: false})))),
        h('div', {class: 'row'}, small('Duplicate', () => edit({op: 'duplicate', ids}, {select: true, retryable: false})), small('Delete', () => edit({op: 'delete', ids}, {retryable: false}), false, 'danger'),
          chosen.length > 1 ? small('Group', () => edit({op: 'group', ids}, {retryable: false}), !!alike) : null,
          grouped ? small('Ungroup', () => edit({op: 'ungroup', ids}, {retryable: false})) : null));
    }
    const settingsOptions = () => [['', `Default (${settingsName(view.default_settings_id)})`], ...view.settings.map((s) => [String(s.id), s.name])];

    /** The inspector of one element: built when the element (or the kind of its QR code) changes, then only brought up to date. */
    function buildInspector(e) {
      const K = (p) => `${e.id}:${p}`, number = (label, p, quantity) => P.numberControl({label, key: K(p), local, quantity, commit: (v) => setField(e, p, v)});
      const name = P.textControl({label: 'Name', key: K('name'), local, nonEmpty: true, commit: (v) => setField(e, 'name', v)});
      const [x, y, width, height, rotation] = [number('Center X', 'x', Q.x), number('Center Y', 'y', Q.y), number('Width', 'width', Q.width), number('Height', 'height', Q.height),
        number('Rotation', 'rotation', Q.rotation)];
      const settings = P.selectControl({label: 'Engraving settings', key: K('settings_id'), local, options: settingsOptions(), commit: (v) => assign([e.id], v)});
      const form_ = P.typeForm(e, env), notes = h('div', {class: 'stack'}), actions = h('div', {}), head = h('h4', {});
      let optionsKey = '';
      return {key: `${e.id}:${e.type}:${e.type === 'qr' ? e.qr.kind : ''}`,
        el: h('div', {class: 'stack cw-inspector'}, head, notes, name.el, h('div', {class: 'cw-pair'}, x.el, y.el), h('div', {class: 'cw-pair'}, width.el, height.el), rotation.el,
          settings.el, actions, form_.el),
        sync(next) {
          fill(head, `${TYPE_NAME[next.type]}${next.group ? ' · in a group' : ''}`);
          fill(notes, (next.problems || []).map((p) => h('p', {class: 'alert bad small'}, p)), next.type === 'qr' ? null : (next.warnings || []).map((w) => h('p', {class: 'alert warn small'}, w.message)));
          name.sync(next.name); x.sync(next.x); y.sync(next.y); width.sync(next.width); height.sync(next.height); rotation.sync(next.rotation);
          const options = settingsOptions(), signature = JSON.stringify(options);
          if (signature !== optionsKey) { optionsKey = signature; settings.setOptions(options); }
          settings.sync(next.settings_id == null ? '' : next.settings_id);
          fill(actions, actionsFor([next]));
          form_.sync(next);
        }};
    }
    function buildGroup(chosen) {
      const values = new Set(chosen.map((e) => (e.settings_id == null ? '' : String(e.settings_id))));
      const select_ = h('select', {'aria-label': 'Engraving settings of the selected elements', onChange: (ev) => { const self = ev.currentTarget; assign(chosen.map((e) => e.id), self.value); }},
        values.size > 1 ? h('option', {value: '__mixed', disabled: true}, 'Mixed: choose to set all') : null,
        settingsOptions().map(([value, label]) => h('option', {value}, label)));
      select_.value = values.size > 1 ? '__mixed' : [...values][0];
      return h('div', {class: 'stack cw-inspector'}, h('h4', {}, `${chosen.length} elements selected`), actionsFor(chosen), field('Engraving settings', select_));
    }
    /** Redraw ``body`` of the right column without taking the cursor from the control the person is in. */
    function keepFocus(rebuild) {
      const now = document.activeElement, label = now && rightBody.contains(now) ? now.getAttribute('aria-label') : null;
      rebuild();
      const again = label ? [...rightBody.querySelectorAll('input, select, textarea, button')].find((n) => n.getAttribute('aria-label') === label) : null;
      if (again && again.focus) again.focus();
    }
    function paintRight() {
      const chosen = selected();
      if (!chosen.length) {
        inspected = null;
        fill(rightTitle, 'Engraving');
        if (engraving.el.parentNode !== rightBody) fill(rightBody, engraving.el);
        engraving.sync(view);
      } else if (chosen.length === 1) {
        fill(rightTitle, 'Selected');
        const key = `${chosen[0].id}:${chosen[0].type}:${chosen[0].type === 'qr' ? chosen[0].qr.kind : ''}`;
        if (!inspected || inspected.key !== key) keepFocus(() => { inspected = buildInspector(chosen[0]); fill(rightBody, inspected.el); });
        inspected.sync(chosen[0]);
      } else {
        inspected = null;
        fill(rightTitle, 'Selected');
        keepFocus(() => fill(rightBody, buildGroup(chosen)));
      }
    }

    // -- the top bar
    const undo = btn('Undo', () => step('undo'), 'btn-small'), redo = btn('Redo', () => step('redo'), 'btn-small');
    const title = h('div', {class: 'cw-title'}), sizeButton = btn('', () => sizeDialog(), 'btn-small');
    const tabButtons = SIDES.map((s) => h('button', {type: 'button', role: 'tab', id: `cw-tab-${s}`, class: 'vw-tab', 'aria-controls': 'cw-panel', onClick: () => switchTo(s)}, SIDE_NAME[s]));
    const tabList = h('div', {role: 'tablist', class: 'vw-tabs cw-tabs', 'aria-label': 'Side of the card'}, tabButtons);
    tabList.addEventListener('keydown', (ev) => {
      const move = ev.key === 'ArrowRight' ? 1 : ev.key === 'ArrowLeft' ? -1 : 0;
      if (!move) return;
      ev.preventDefault();
      const next = SIDES[(SIDES.indexOf(side) + move + SIDES.length) % SIDES.length];
      switchTo(next);
      tabButtons[SIDES.indexOf(next)].focus();
    });
    const files = Object.fromEntries(SIDES.map((s) => [s, {slot: h('span', {class: 'cw-export'}), ready: null}]));
    function switchTo(next) { side = next; selection = []; paint(); if (canvas) canvas.fit(); }
    function sizeDialog() {
      const form = Forms.create();
      const size = sizeFields(form, {preset: view.preset, width: view.size_mm.width, height: view.size_mm.height});
      let saving = false;
      modal('Card size', h('div', {class: 'stack'}, h('p', {class: 'small muted'}, 'Elements keep their place and size; check that they still lie on the card. You can undo this change.'), size.el, form.error),
        [{label: 'Cancel', run: (m) => m.close()}, {label: 'Set size', cls: 'primary', run: async (m) => {
          if (saving) return;
          const v = form.collect();
          if (!v) return;
          saving = true;
          const error = await soft({path: `${base}/edit`, body: {op: 'set_size', ...size.body(v)}});
          saving = false;
          if (error) form.fail(error); else { m.close(); if (canvas) canvas.fit(); }
        }}]);
    }
    function paintHead() {
      if (shownName !== view.name) {
        shownName = view.name;
        fill(title, h('p', {class: 'small muted'}, 'Business card'), h('div', {class: 'vw-name-row'}, h('h2', {title: view.name}, view.name),
          VectorWorkspace.renameButton(id, view.name, (stored) => { view = {...view, name: stored}; doc.adopt(wrap(view)); paintHead(); }, '/card-works')));
      }
      undo.disabled = !view.can_undo; redo.disabled = !view.can_redo;
      undo.setAttribute('title', 'Undo (Ctrl+Z)'); redo.setAttribute('title', 'Redo (Ctrl+Shift+Z)');
      SIDES.forEach((s, i) => { tabButtons[i].setAttribute('aria-selected', String(s === side)); tabButtons[i].setAttribute('tabindex', s === side ? '0' : '-1'); tabButtons[i].classList.toggle('active', s === side); });
      panel.setAttribute('aria-labelledby', `cw-tab-${side}`);
      fill(sizeButton, `Card size: ${mm(view.size_mm.width)} × ${mm(view.size_mm.height)} mm`);
      sizeButton.setAttribute('aria-label', `Card size: ${mm(view.size_mm.width)} by ${mm(view.size_mm.height)} millimeters. Change`);
      for (const s of SIDES) {                                  // a button is made again only when the side becomes ready or stops being ready
        const review = view.review[s], slot = files[s];
        if (slot.ready === review.ready) continue;
        slot.ready = review.ready;
        const file = Lifecycle.downloadButton(`${base}/sides/${s}/export.lbrn2`, `card-${s}.lbrn2`, `Export ${s}`, {cls: 'btn-small primary', disabled: !review.ready,
          note: 'The LightBurn file was created and downloaded. Open it in LightBurn and check the layers and settings before engraving'});
        file.button.setAttribute('title', review.ready ? `Download the LightBurn file of the ${s}` : `The ${s} is not ready: ${review.problems.join('; ')}`);
        fill(slot.slot, file.el);
      }
    }
    const head = h('div', {class: 'os-head cw-head'}, h('a', {class: 'btn btn-small', href: '#/works'}, '← My works'), title,
      h('div', {class: 'row', role: 'group', 'aria-label': 'Undo and redo'}, undo, redo), doc.view.el, h('span', {class: 'spacer'}), tabList, sizeButton,
      ...SIDES.map((s) => files[s].slot));

    function paint() {
      if (disposed) return;
      if (!root.isConnected && !paint.first) { dispose(); return; }
      paint.first = false;
      if (pendingSelect) { if (pendingSelect.side === side) selection = pendingSelect.ids; pendingSelect = null; }
      selection = selection.filter((i) => sideElements().some((e) => e.id === i));
      paintHead();
      paintCanvas();
      layers.update(sideElements(), selection);
      fill(left.querySelector('.cw-layer-count'), `${sideElements().length} on the ${side}`);
      fill(summary, `${SIDE_NAME[side]} · ${sideElements().length} ${sideElements().length === 1 ? 'element' : 'elements'}`);
      paintAdd();
      paintRight();
    }
    function dispose() {
      disposed = true;
      if (keys === key) keys = null;
      if (canvas) { canvas.destroy(); canvas = null; }
    }
    const key = (ev) => {
      if (!root.isConnected) { dispose(); return; }
      if (document.querySelector('.modal-bg')) return;
      const t = ev.target;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '') || t.isContentEditable)) return;      // a box handles its own keys
      if (t && host.contains(t)) return;                                                              // the canvas reports undo and redo itself
      const letter = String(ev.key || '').toLowerCase();
      if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (letter === 'z' || letter === 'y')) { ev.preventDefault(); step(letter === 'z' && !ev.shiftKey ? 'undo' : 'redo'); }
    };
    keys = key;
    paint.first = true;
    paint();
    fill(root, head, h('div', {class: 'os-body cw-body'}, left, centre, right));
    setTimeout(() => { if (canvas) canvas.fit(); }, 0);
    return root;
  }

  App.register({id: 'card-work', async render(ctx) {
    const id = encodeURIComponent(ctx.query.work || '');
    const [first, lib] = await Promise.all([get(`/card-works/${id}`), get('/card-library')]);
    return screen(first, lib);
  }});

  return {newDialog, screen};
})();
