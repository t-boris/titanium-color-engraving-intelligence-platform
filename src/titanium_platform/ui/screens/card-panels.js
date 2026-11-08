/* Panels of the business-card editor (card-work.js): number, text, choice and check controls bound to one field of an element, the forms of
   the six element types, the physical-suitability box of a QR code, the library pickers, the list of layers and the engraving panel with
   its review (the choice of ready engraving settings itself is card-settings.js). They draw what the screen hands them and report every edit
   through ``env``; they never talk to the server themselves.
   A control shows the value the server has, laid under what the person typed that is not stored yet (``local()``, save-state.js), and never
   rewrites a box the person is typing in. An edit resolves to its error (shown beside the control) or to null. */
'use strict';
const CardPanels = (() => {
  const {h, fill, btn, pill, field, num} = App;
  const NS = 'http://www.w3.org/2000/svg';
  const DEBOUNCE_MS = 700;                                  // the pause after typing before a text is sent (as lettering.js)
  const SIDE_NAME = {front: 'Front', back: 'Back'};

  // The limits are the server's: card_work._checked (position, size, rotation), SETTING_FIELDS, EXTRA_NUMBERS and the passes (engraving settings), _card_size (card).
  const Q = {
    x: {label: 'Center X', unit: 'mm', min: -1000, max: 1000}, y: {label: 'Center Y', unit: 'mm', min: -1000, max: 1000},
    width: {label: 'Width', unit: 'mm', min: 0.2, max: 500}, height: {label: 'Height', unit: 'mm', min: 0.2, max: 500},
    rotation: {label: 'Rotation', unit: 'degrees', min: -3600, max: 3600},
    cardWidth: {label: 'Card width', unit: 'mm', min: 10, max: 300}, cardHeight: {label: 'Card height', unit: 'mm', min: 10, max: 300},
    power: {label: 'Power', unit: '%', min: 0, minOpen: true, max: 100}, speed: {label: 'Speed', unit: 'mm/s', min: 0, minOpen: true, max: 100000},
    frequency: {label: 'Frequency', unit: 'kHz', min: 0, minOpen: true, max: 10000},
    pulse_width: {label: 'Pulse width (optional)', unit: 'ns', min: 0, minOpen: true, max: 10000},
    line_interval: {label: 'Line interval', unit: 'mm', min: 0, minOpen: true, max: 10},
    passes: {label: 'Passes', unit: '', integer: true, min: 1, max: 100},
    min_power: {label: 'Minimum power', unit: '%', min: 0, max: 100}, scan_angle: {label: 'Scan angle', unit: 'degrees', min: -360, max: 360},
    dot_width: {label: 'Dot width', unit: 'mm', min: 0, max: 5},
    partWidth: {label: 'Width', unit: 'mm', min: 0.02, max: 500}, partHeight: {label: 'Height', unit: 'mm', min: 0.02, max: 500}};      // an imported part may be a hairline (card_work.MIN_VECTOR_MM)
  const KIND_NAME = {link: 'Link', vcard: 'Contact card (vCard)', text: 'Text', wifi: 'Wi-Fi network', email: 'Email', phone: 'Phone number'};
  const OPTION_NAME = {nopass: 'No password'};
  const ECC_NAME = {L: 'L: about 7 % of the code can be damaged', M: 'M: about 15 %', Q: 'Q: about 25 %', H: 'H: about 30 %'};
  const TYPE_MARK = {text: 'T', shape: '◆', frame: '▢', icon: '★', image: '▣', qr: 'QR', vector: '✦'};
  const TYPE_NAME = {text: 'Text', shape: 'Shape', frame: 'Frame', icon: 'Icon', image: 'Image', qr: 'QR code', vector: 'Vector part'};
  const NO_GUARANTEE = 'Passing the checks does not guarantee that the engraved code will scan.';

  const fixed = (v) => String(+(+v).toFixed(3));
  const pick = (local, key, value) => (local && key in local ? local[key] : value);
  const message = (error) => (error ? error.message || String(error) : '');
  const cap = (text) => String(text).charAt(0).toUpperCase() + String(text).slice(1).replace(/_/g, ' ');
  const stepFor = (span) => (span > 200 ? 1 : span > 20 ? 0.5 : span > 2 ? 0.1 : 0.01);
  /** A choice list as [value, label] pairs, from strings, pairs or {value, label} objects. */
  const choices = (list) => list.map((o) => (Array.isArray(o) ? o : o && typeof o === 'object' ? [o.value, o.label || cap(o.value)] : [o, cap(o)]));

  /** The drawing of a library item: its path in a 24 × 24 box, filled even-odd. */
  function thumb(d, cls = 'cw-thumb') {
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('class', cls); svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(NS, 'path');
    path.setAttribute('d', d || ''); path.setAttribute('fill', 'currentColor'); path.setAttribute('fill-rule', 'evenodd');
    svg.append(path);
    return svg;
  }

  // ---- controls ------------------------------------------------------------------------------------------------------------------

  /** A number box, with a slider on the same value when ``slider``. ``commit(value)`` resolves to the error or null; an empty box sends nothing
      unless ``clearable``. A wrong value stays in the box with the reason beside it (forms.js) and is not sent. */
  function numberControl({label, quantity, key, local, slider = false, clearable = false, commit}) {
    const q = {...quantity, label};
    const input = Forms.numberInput(q, {'aria-label': label});
    const range = slider && q.min != null && q.max != null
      ? h('input', {type: 'range', class: 'cw-range', min: String(q.min), max: String(q.max), step: q.integer ? '1' : String(stepFor(q.max - q.min)), 'aria-label': `${label}, slider`}) : null;
    let saved = null, node = null;
    async function submit(value) {
      if (range && value != null) range.value = String(value);
      node.setError(message(await commit(value)));
    }
    const wrong = Forms.watch(input, q, (value) => { if (value != null || clearable) submit(value); });
    // the note of a wrong value goes in as the field's help, so that it stays among the texts that describe the box
    node = field(label, h('span', {class: 'cw-num'}, range, input), wrong, {unit: q.unit, unitless: !q.unit, constraint: `allowed: ${Forms.constraint(q)}`});
    const paint = () => {
      const value = pick(local(), key, saved);
      input.value = value == null ? '' : fixed(value);
      if (range) range.value = value == null ? String(q.min) : String(value);
    };
    if (range) {
      range.addEventListener('input', () => { input.value = fixed(range.value); });
      range.addEventListener('change', () => submit(Number(range.value)));
    }
    input.addEventListener('blur', () => { if (input.getAttribute('aria-invalid') !== 'true') paint(); });
    return {el: node, input, range, setError: node.setError,
      sync(value) { saved = value; if (document.activeElement !== input && (!range || document.activeElement !== range)) paint(); },
      setDisabled(off) { input.disabled = off; if (range) range.disabled = off; }};
  }

  /** A text box (or text area). With ``debounce`` the text is sent a moment after the last key; a change (leaving the box) sends it at once. */
  function textControl({label, key, local, multiline = false, password = false, debounce = false, nonEmpty = false, mark = false, commit}) {
    const input = multiline ? h('textarea', {rows: '3', 'aria-label': label}) : h('input', {type: password ? 'password' : 'text', autocomplete: 'off', 'aria-label': label});
    const node = field(label, input, null, mark ? {required: true} : undefined);
    let saved = '', sent = null, timer = null;
    async function submit() {
      clearTimeout(timer);
      const text = input.value;
      if (nonEmpty && !text.trim()) { node.setError('Complete this field'); return; }
      if (text === sent || (sent === null && text === saved)) return;
      sent = text;
      node.setError(message(await commit(text)));
    }
    const paint = () => { input.value = String(pick(local(), key, saved) ?? ''); };
    input.addEventListener('change', submit);
    if (debounce) input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(submit, DEBOUNCE_MS); });
    input.addEventListener('blur', () => { if (!node.errorText()) paint(); });
    return {el: node, input, setError: node.setError, sync(value) { saved = value ?? ''; sent = null; if (document.activeElement !== input) paint(); }};
  }

  /** A choice of ``options`` ([value, label]). */
  function selectControl({label, key, local, options, commit}) {
    const select = h('select', {'aria-label': label});
    const node = field(label, select);
    let saved = '';
    const paint = () => { select.value = String(pick(local(), key, saved) ?? ''); };
    const setOptions = (list) => { fill(select, choices(list).map(([value, text]) => h('option', {value: String(value)}, text))); paint(); };
    setOptions(options);
    select.addEventListener('change', async () => node.setError(message(await commit(select.value))));
    return {el: node, select, setError: node.setError, setOptions, sync(value) { saved = value; if (document.activeElement !== select) paint(); }};
  }

  /** A check box. */
  function checkControl({label, key, local, commit}) {
    const input = h('input', {type: 'checkbox', 'aria-label': label});
    const note = h('p', {class: 'small f-error', hidden: true, role: 'alert'});
    let saved = false;
    const paint = () => { input.checked = !!pick(local(), key, saved); };
    input.addEventListener('change', async () => {
      const error = message(await commit(input.checked));
      note.textContent = error; note.hidden = !error;
    });
    return {el: h('div', {class: 'cw-check'}, h('label', {class: 'row small'}, input, h('span', {}, label)), note), input,
      sync(value) { saved = !!value; if (document.activeElement !== input) paint(); }};
  }

  /** The control of one parameter of a library item, from its spec ({name, label, type, min, max, unit, options}). */
  function paramControl(spec, e, path, env) {
    const key = `${e.id}:${path}`, label = spec.label || cap(spec.name);
    const commit = (value) => env.set(e, path, value, label);
    const options = spec.options ? spec.options.map((o) => [o, (spec.option_labels || {})[o] || cap(o)]) : null;
    if (spec.type === 'bool') return checkControl({label, key, local: env.local, commit});
    if (options) return selectControl({label, key, local: env.local, options, commit});
    return numberControl({label, key, local: env.local, slider: true, commit,
      quantity: {unit: spec.unit || '', min: spec.min, max: spec.max, integer: spec.type === 'int'}});
  }

  // ---- the forms of the element types ----------------------------------------------------------------------------------------------

  function textForm(e, env) {
    const K = (p) => `${e.id}:text.${p}`, local = env.local;
    const text = textControl({label: 'Text', key: K('text'), local, multiline: true, debounce: true, commit: (v) => env.set(e, 'text.text', v, 'Text')});
    const number = ([p, q, label]) => numberControl({label, key: K(p), local, quantity: Forms.QUANTITIES[q], commit: (v) => env.set(e, `text.${p}`, v, label)});
    const sizes = [['height_mm', 'letterHeight', 'Letter height'], ['width_pct', 'letterWidth', 'Letter width'], ['spacing_mm', 'letterSpacing', 'Letter spacing'],
      ['line_pct', 'lineSpacing', 'Line spacing']].map((spec) => [spec[0], number(spec)]);
    const align = selectControl({label: 'Alignment', key: K('align'), local, options: [['left', 'Left'], ['center', 'Center'], ['right', 'Right']],
      commit: (v) => env.set(e, 'text.align', v, 'Alignment')});
    const family = h('span', {class: 'small'});
    const error = h('p', {class: 'small f-error', role: 'alert', hidden: true});
    let current = e;
    const font = typeof Lettering !== 'undefined' && Lettering.fontWindow
      ? h('div', {class: 'row'}, h('span', {class: 'small muted'}, 'Font:'), family, btn('Choose font…', () => Lettering.fontWindow(current.text.font, current.text.text, async (picked) => {
        const failed = message(await env.set(current, 'text.font', picked, 'Font'));
        error.textContent = failed; error.hidden = !failed;
      }), 'btn-small')) : null;
    return {el: h('div', {class: 'stack cw-form'}, text.el, font, error, sizes.map(([, c]) => c.el), align.el),
      sync(next) {
        current = next;
        text.sync(next.text.text);
        for (const [p, c] of sizes) c.sync(next.text[p]);
        align.sync(next.text.align);
        fill(family, next.text.font ? `${next.text.font.family}${next.text.font.style ? ` ${next.text.font.style}` : ''}` : 'the default font');
      }};
  }

  /** A shape, frame or icon: its drawing and name and the parameters of the library item. The item itself is not changed here: ``set`` merges
      the parameters into the old ones, and the parameters differ from item to item, so another shape is a new element. */
  function libraryForm(e, env, group, nameKey) {
    const items = env.lib()[group] || [], item = items.find((i) => i.name === e[group][nameKey]);
    const params = (item ? item.params : []).map((spec) => [spec, paramControl(spec, e, `${group}.${spec.name}`, env)]);
    return {el: h('div', {class: 'stack cw-form'}, h('div', {class: 'row'}, item ? thumb(item.preview) : null, h('strong', {}, item ? item.label : e[group][nameKey])),
      params.map(([, c]) => c.el), item ? null : h('p', {class: 'small muted'}, 'This item is not in the library, so its parameters cannot be edited.')),
    sync(next) { for (const [spec, c] of params) c.sync(next[group][spec.name]); }};
  }

  /** How a picture is engraved: as traced shapes (the vector settings of its engraving settings) or as a photo (raster: image mode, line interval and
      minimum power of its engraving settings). A segmented choice of two; ``set(value)`` resolves to the error or null. */
  function engraveControl(e, set) {
    const name = `cw-engrave-${e.id}`, error = h('p', {class: 'alert bad small', role: 'alert', hidden: true});
    const radios = [['vector', 'Traced shapes'], ['raster', 'Photo (raster)']].map(([value, text]) => {
      const input = h('input', {type: 'radio', class: 'sr-only', name, value, 'aria-label': text, onChange: async () => {
        const failed = message(await set(value));
        error.textContent = failed; error.hidden = !failed;
      }});
      return {input, value, label: h('label', {class: 'cw-seg', 'data-engrave': value}, input, h('span', {}, text))};
    });
    const group = h('div', {class: 'cw-segmented', role: 'radiogroup', 'aria-label': 'Engrave as'}, radios.map((r) => r.label));
    return {el: h('div', {class: 'stack cw-engrave'}, h('span', {class: 'small'}, 'Engrave as'), group, error),
      sync(value) { for (const r of radios) { r.input.checked = r.value === value; r.label.classList.toggle('on', r.value === value); } }};
  }

  /** A picture: how it was added, how it is engraved (traced shapes or a photo) and the tracing parameters (the canvas shows the traced shapes, or
      the dithered photo, after every change). A photo is not traced, so only "invert" of the tracing remains for it. */
  function imageForm(e, env) {
    const params = (((env.lib().image || {}).params) || []).map((spec) => [spec, paramControl(spec, e, `image.${spec.name}`, env)]);
    const info = h('p', {class: 'small muted'});
    const engrave = engraveControl(e, (value) => env.set(e, 'image.engrave', value, 'Engrave as'));
    const hint = h('p', {class: 'small muted cw-raster-hint', hidden: true},
      'Engraved as a photo with the photo settings of the chosen engraving settings (image mode, line interval, minimum power).');
    const plain = h('p', {class: 'alert warn small cw-raster-plain', role: 'status', hidden: true},
      'The engraving settings of this picture give no line interval or image mode yet, so the preview is plain grey at a default resolution.');
    return {el: h('div', {class: 'stack cw-form'}, info, engrave.el, hint, plain, params.map(([, c]) => c.el)),
      sync(next) {
        const image = next.image, local = env.local(), own = (name) => pick(local, `${e.id}:image.${name}`, image[name]);
        const raster = own('engrave') === 'raster';
        fill(info, `${image.name || 'picture'} · ${image.size ? `${image.size[0]} × ${image.size[1]} px · ` : ''}`
          + (image.origin === 'generated' ? `generated from “${image.prompt || ''}”` : 'imported graphic'));
        engrave.sync(raster ? 'raster' : 'vector');
        hint.hidden = !raster;
        plain.hidden = !(raster && next.raster && next.raster.given === false);
        for (const [spec, c] of params) {
          c.sync(image[spec.name]);
          if (spec.name === 'threshold') c.setDisabled(!!own('auto_threshold'));              // the grey level is found by the program while the box is ticked
          // a photo is not traced: only "invert" applies; the pencil look is shaped by detail and strength only
          c.el.hidden = raster ? spec.name !== 'invert' : (spec.name === 'detail' || spec.name === 'strength') && own('treatment') !== 'pencil';
        }
      }};
  }

  /** What the placed QR code was measured to be, against the thresholds, and each warning. Warnings never block anything. */
  function suitability(e, lib) {
    const info = e.qr_info || null, limits = (info && info.thresholds) || (lib && lib.qr && lib.qr.thresholds) || {};
    const rows = [
      ['Symbol', info && typeof info.modules === 'number' ? `${info.modules} modules across` : '—'],
      ['Module size', info && info.module_mm != null ? `${num(info.module_mm, 2)} mm (at least ${num(limits.module_mm, 2)} mm)` : '—'],
      ['Quiet zone', info && info.quiet_modules != null ? `${num(info.quiet_modules, 1)} modules (at least ${num(limits.quiet_modules, 0)} modules)` : '—']];
    return h('div', {class: 'stack cw-suit', role: 'group', 'aria-label': 'Physical suitability of the QR code'},
      h('h4', {}, 'Physical suitability'),
      h('dl', {class: 'facts'}, rows.map(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])),
      ...(e.warnings || []).map((w) => h('p', {class: 'alert warn small cw-warning'}, w.message)),
      h('p', {class: 'small cw-no-guarantee'}, NO_GUARANTEE));
  }

  function qrForm(e, env) {
    const lib = env.lib().qr || {kinds: [], fields: {}, ecc: []}, local = env.local, K = (p) => `${e.id}:qr.${p}`;
    const kind = selectControl({label: 'Content type', key: K('kind'), local, options: lib.kinds.map((k) => [k, KIND_NAME[k] || cap(k)]), commit: (v) => env.setQrKind(e, v)});
    const fields = (lib.fields[e.qr.kind] || []).map((spec) => {
      const label = spec.label || cap(spec.name), commit = (v) => env.setQr(e, spec.name, v, label), key = K(`fields.${spec.name}`);
      const control = spec.type === 'bool' || spec.type === 'checkbox' ? checkControl({label, key, local, commit})
        : spec.options ? selectControl({label, key, local, options: spec.options.map((o) => [o, OPTION_NAME[o] || o]), commit})
          : textControl({label, key, local, debounce: true, mark: !!spec.required, multiline: spec.type === 'multiline', password: spec.type === 'password', commit});
      return [spec, control];
    });
    const ecc = selectControl({label: 'Error correction', key: K('ecc'), local, options: lib.ecc.map((l) => [l, ECC_NAME[l] || l]), commit: (v) => env.set(e, 'qr.ecc', v, 'Error correction')});
    const box = h('div', {});
    return {el: h('div', {class: 'stack cw-form'}, kind.el, fields.map(([, c]) => c.el), ecc.el, box),
      sync(next) {
        kind.sync(next.qr.kind);
        for (const [spec, c] of fields) c.sync((next.qr.fields || {})[spec.name] ?? spec.default ?? '');
        ecc.sync(next.qr.ecc);
        fill(box, suitability(next, env.lib()));
      }};
  }

  // ---- imported vector artwork (feature-3) ------------------------------------------------------------------------------------------
  const HEX6 = /^#[0-9a-f]{6}$/i;
  const dot = (colour, label) => h('span', {class: 'sw cw-swatch', style: `background:${colour}`, role: 'img', 'aria-label': label || `Colour ${colour}`});
  const parts_ = (n) => `${n} ${n === 1 ? 'part' : 'parts'}`;

  /** The colours of imported vector parts, one row for each design colour among ``parts``: the colour the file drew (changeable, with a way back),
      the engraving colour the parts engrave with now, and the measured engraving colour that is nearest to the design colour, with its distance.
      The two are kept apart: recolouring never changes what is engraved, and choosing an engraving never recolours the drawing (REQ-004).
      ``env``: colourMatches(colours) → {data, error, loading}, recolour(ids, fill, reset), assignChoiceTo(ids, choiceId), engravingOf(e), reloadChoices,
      and what card-settings.js asks of it (pickerDialog). */
  function artworkColours(env) {
    const box = h('section', {class: 'stack cw-art', 'aria-label': 'Colours of the imported artwork'});
    let signature = null;
    const failure = h('p', {class: 'alert bad small', role: 'alert', hidden: true});
    const show = (error) => { const text = message(error); failure.textContent = text; failure.hidden = !text; };
    function engravingLine(group, found) {
      const sets = new Set(group.map((e) => env.engravingOf(e)).map((x) => (x ? x.id : null)));
      const set = sets.size === 1 ? env.engravingOf(group[0]) : null, colour = CardSettings.swatchOf(set);
      const origin = set && set.origin;
      const name = !set ? 'Mixed engravings' : origin && origin.kind === 'choice' ? origin.label : set.name;
      return {set, line: h('p', {class: 'row small cw-art-engraves'}, h('span', {class: 'muted'}, 'Engraved with'), colour ? dot(colour, `Engraving colour ${name}`) : null, h('strong', {}, name)),
        choiceId: origin && origin.kind === 'choice' ? origin.choice_id : null};
    }
    function row(colour, group, cache) {
      const ids = group.map((e) => e.id), changed = group.some((e) => e.vector.fill !== e.vector.source);
      const input = h('input', {type: 'color', class: 'cw-colour-input', value: HEX6.test(colour) ? colour : '#000000', 'aria-label': `Design colour ${colour} of ${parts_(group.length)}`});
      input.addEventListener('change', async () => show(await env.recolour(ids, input.value)));
      const back = changed ? btn('Back to the colour of the file', async () => show(await env.recolour(ids, null, true)), 'btn-small') : null;
      const engraves = engravingLine(group);
      const data = cache.data, found = data && data.matches ? data.matches[colour] : null;
      let suggestion;
      if (cache.error) suggestion = h('p', {class: 'alert warn small', role: 'status'}, cache.error);
      else if (!data) suggestion = h('p', {class: 'small muted', role: 'status'}, 'Looking for the engraving colours measured for this card…');
      else if (!data.available) suggestion = h('p', {class: 'small muted cw-art-none', role: 'status'}, data.reason || 'No engraving colour is measured for this card yet.');
      else if (!found || !found.best) suggestion = h('p', {class: 'small muted cw-art-none', role: 'status'}, 'No measured engraving colour is available for this card.');
      else {
        const best = found.best, on = engraves.choiceId === best.choice_id;
        const use = btn(on ? 'In use' : found.close ? 'Use' : 'Use nearest', async () => show(await env.assignChoiceTo(ids, best.choice_id)), `btn-small cw-art-use${on ? '' : ' primary'}`);
        use.setAttribute('aria-label', on ? `${best.label}: in use for ${colour}` : `Use ${best.label} for ${parts_(group.length)} of ${colour}`);
        use.setAttribute('aria-pressed', String(on));
        suggestion = h('div', {class: 'stack'},
          h('div', {class: 'row small cw-art-suggest'}, h('span', {class: 'muted'}, found.close ? 'Closest engraving colour' : 'Nearest, but not close'), HEX6.test(best.swatch) ? dot(best.swatch, `Engraving colour ${best.label}`) : null,
            h('strong', {}, best.label), h('span', {class: 'muted'}, `ΔE ${best.delta_e}`), use),
          found.close ? null : h('p', {class: 'alert warn small cw-art-far', role: 'status'}, `No measured engraving colour is close to ${colour} (the nearest is ${best.delta_e} ΔE away; ${data.close_delta_e} or less is close). Choose one yourself or keep the card’s default settings.`));
      }
      const another = btn('Choose another…', () => CardSettings.pickerDialog(env, {subject: `${parts_(group.length)} of ${colour}`, inUse: engraves.choiceId ? {id: engraves.choiceId, type: 'color'} : null,
        prefer: 'color', onPick: (item) => env.assignChoiceTo(ids, item.id)}), 'btn-small');
      another.setAttribute('aria-label', `Choose another engraving colour for ${parts_(group.length)} of ${colour}`);
      return h('div', {class: 'stack cw-art-row', 'data-colour': colour},
        h('div', {class: 'row'}, h('span', {class: 'small muted'}, 'Design colour'), input, h('strong', {class: 'small'}, colour), h('span', {class: 'small muted'}, parts_(group.length)), h('span', {class: 'spacer'}), back),
        engraves.line, suggestion, h('div', {class: 'row'}, another));
    }
    return {el: box, sync(parts) {
      const groups = new Map();
      for (const e of parts) { const key = e.vector.fill; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(e); }
      const colours = [...groups.keys()], cache = env.colourMatches(colours);
      const next = JSON.stringify([[...groups].map(([colour, group]) => [colour, group.map((e) => [e.id, e.vector.source, e.settings_id])]), cache.data, cache.error, cache.loading, env.view().settings.map((x) => [x.id, x.name, x.origin && x.origin.choice_id])]);
      if (next === signature) return;
      signature = next;
      fill(box, h('h4', {}, parts.length === 1 ? 'Colour of this part' : 'Colours of the artwork'),
        h('p', {class: 'small muted'}, 'The design colour is what the file draws. The engraving colour is what the laser makes; it is chosen separately.'), failure,
        [...groups].map(([colour, group]) => row(colour, group, cache)));
    }};
  }

  /** One imported part: where it comes from, its design colour and engraving colour, and what cannot be done with it. */
  function vectorForm(e, env) {
    const info = h('p', {class: 'small muted'}), colours = artworkColours(env);
    return {el: h('div', {class: 'stack cw-form'}, info, colours.el,
      h('p', {class: 'small muted cw-nodes-note'}, 'The shape of an imported part cannot be edited (no path nodes). Move, resize, rotate, copy or delete it, or change its colour. Double-click a part of a group to select only that part.')),
    sync(next) {
      fill(info, `Part ${next.vector.part + 1} of “${next.vector.file}” (${next.vector.kind === 'ai' ? 'Illustrator' : 'SVG'})`);
      colours.sync([next]);
    }};
  }

  /** The form of the type of element ``e``: {el, sync(element)}. */
  function typeForm(e, env) {
    return {text: textForm, shape: (x, v) => libraryForm(x, v, 'shape', 'kind'), frame: (x, v) => libraryForm(x, v, 'frame', 'style'),
      icon: (x, v) => libraryForm(x, v, 'icon', 'name'), image: imageForm, qr: qrForm, vector: vectorForm}[e.type](e, env);
  }

  // ---- the library and the layers ---------------------------------------------------------------------------------------------------

  /** A compact searchable grid of library items; pressing one calls ``onPick(item)``. */
  function picker(kind, items, onPick) {
    return App.list({id: `cw.pick.${kind}`, items, key: (i) => i.name, search: (i) => `${i.label} ${i.name}`, page: kind === 'icon' ? 30 : 18, className: `cw-pick cw-pick-${kind}`,
      row: (i) => [h('button', {type: 'button', class: 'cw-pick-item', title: i.label, 'aria-label': `Add ${i.label}`, onClick: () => onPick(i)},
        thumb(i.preview), h('span', {class: 'cw-pick-label small'}, i.label))],
      empty: 'The library has no items of this kind.', noResults: 'Nothing in the library matches this search.'}).el;
  }

  /** The layers of the side, the top one first: a row selects, two small buttons move it one place. ``env``: select(ids), reorder(id, to). */
  function layerList(env) {
    let on = [], shown = [];
    const groupSize = (e) => shown.filter((x) => x.group && x.group === e.group).length;
    /** What the layer engraves with: the swatch of its colour and, when it has settings of its own, their name. */
    function engravingMark(e) {
      const set = env.engravingOf ? env.engravingOf(e) : null, colour = CardSettings.swatchOf(set);
      const swatch = colour ? h('span', {class: 'sw cw-swatch cw-layer-swatch', style: `background:${colour}`, role: 'img', 'aria-label': `Engraves in ${set.origin.label}`}) : null;
      const own = e.settings_id != null ? pill(env.settingsName(e.settings_id) || 'settings') : null;
      return swatch || own ? h('span', {class: 'cw-layer-engraving'}, swatch, own) : null;
    }
    const list = App.list({id: 'cw.layers', items: [], key: (e) => e.id, search: (e) => `${e.name} ${TYPE_NAME[e.type]}`, page: 12, className: 'cw-layers-list',
      selected: () => (on.length ? on[on.length - 1] : null), rowClass: (e) => (on.includes(e.id) ? 'cw-on' : ''),
      row: (e) => {
        const bad = (e.problems || []).length || (e.warnings || []).length;
        return [h('button', {type: 'button', class: 'cw-layer', 'aria-pressed': String(on.includes(e.id)), title: `${TYPE_NAME[e.type]}: ${e.name}`, onClick: () => env.select([e.id])},
          h('span', {class: 'cw-layer-type', 'aria-hidden': 'true'}, TYPE_MARK[e.type]), h('span', {class: 'sr-only'}, `${TYPE_NAME[e.type]}: `),
          e.type === 'vector' && e.vector && HEX6.test(e.vector.fill) ? h('span', {class: 'cw-layer-design', style: `background:${e.vector.fill}`, role: 'img', 'aria-label': `Design colour ${e.vector.fill}`}) : null,
          h('span', {class: 'lst-text cw-layer-name'}, e.name)),
        e.group ? pill(`Group of ${groupSize(e)}`) : null,
        engravingMark(e),
        bad ? h('span', {class: 'cw-dot', role: 'img', 'aria-label': 'Has a warning', title: [...(e.problems || []), ...(e.warnings || []).map((w) => w.message)].join('\n')}, '●') : null];
      },
      actions: (e) => {
        const at = shown.indexOf(e), up = btn('↑', () => env.reorder(e.id, 'forward'), 'btn-small', at === 0), down = btn('↓', () => env.reorder(e.id, 'backward'), 'btn-small', at === shown.length - 1);
        up.setAttribute('aria-label', `Move ${e.name} forward`); down.setAttribute('aria-label', `Move ${e.name} backward`);
        const remove = btn('×', () => env.deleteLayer(e.id), 'btn-small');
        remove.setAttribute('aria-label', `Delete ${e.name}`); remove.title = `Delete ${e.name}`;
        return [up, down, remove];
      },
      empty: 'Nothing on this side yet. Add text, a shape, an icon or a QR code.', noResults: 'No layer matches this search.'});
    return {el: list.el, update(elements, selection) { on = selection; shown = [...elements].reverse(); list.items = shown; return list.refresh(); }};
  }

  // ---- engraving settings and the review ---------------------------------------------------------------------------------------------

  /** The panel shown with nothing selected: the laser, lens and material of the card, the sets of engraving settings (each a choice of ready
      settings, card-settings.js) and the review of each side. ``env``: view(), local(), setup(), select(id, side), settingsAdd(), setSettings,
      settingsDelete, and what card-settings.js asks of it (choices, applyChoice, confirmSettings, customSettings, setSetup). */
  function engravingPanel(env) {
    const rows = new Map(), setsBox = h('div', {class: 'cw-sets'}), reviewBox = h('div', {class: 'stack cw-review'});
    const previews = Object.fromEntries(Object.keys(SIDE_NAME).map((s) => [s, h('img', {class: 'cw-preview', alt: `${SIDE_NAME[s]}: the shapes that will be engraved (imported artwork is drawn in its design colours)`})]));
    const heading = h('h4', {}, 'Engraving settings'), failure = h('p', {class: 'alert bad small', role: 'alert', hidden: true});
    const add = btn('Add settings', async () => { const text = message(await env.settingsAdd()); failure.textContent = text; failure.hidden = !text; }, 'btn-small');
    const setup = CardSettings.setupBar(env);
    const more = {front: false, back: false};
    let ids = null, known = new Set();
    /** Which elements use a set (from the review the server made). */
    function usageOf(view, id) {
      const names = [];
      for (const side of Object.keys(SIDE_NAME)) names.push(...view.review[side].elements.filter((x) => x.effective_settings_id === id).map((x) => x.name));
      return {names, defaultId: view.default_settings_id};
    }
    function reviewOf(view, side) {
      const r = view.review[side], elements = view.sides[side].elements;
      const rowsOf = r.elements.filter((x) => !x.complete || x.empty);
      /** What a set still needs, in the server's words: from the review of the side, else from the set itself. */
      const needsOf = (settingsId) => {
        const inReview = r.sets.find((s) => s.settings_id === settingsId), set = view.settings.find((s) => s.id === settingsId);
        const list = (inReview && inReview.needs) || (set && set.status && set.status.needs) || [];
        return list.length ? list.join('; ') : 'figures';
      };
      const why = (x) => {
        const bits = [];
        if (x.empty) bits.push(((elements.find((el) => el.id === x.id) || {}).problems || [])[0] || 'nothing to engrave');
        if (!x.complete) bits.push(`its engraving settings still need ${needsOf(x.effective_settings_id)}`);
        return bits.join('; ');
      };
      const shownRows = more[side] ? rowsOf : rowsOf.slice(0, 5);
      previews[side].setAttribute('src', `/api/card-works/${view.id}/sides/${side}/preview.svg?v=${encodeURIComponent(view.updated_at || '')}`);
      return h('section', {class: 'stack cw-review-side', 'aria-label': `${SIDE_NAME[side]} review`},
        h('div', {class: 'row'}, h('strong', {}, SIDE_NAME[side]), r.ready ? pill('ready to export', 'ok') : pill('not ready', 'warn')), previews[side],
        r.ready ? h('p', {class: 'small muted'}, 'Open the exported file in LightBurn and check the layers and settings before engraving.') : null,
        r.problems.length ? h('ul', {class: 'small cw-problems'}, r.problems.map((p) => h('li', {}, p))) : null,
        shownRows.length ? h('ul', {class: 'cw-attention'}, shownRows.map((x) => h('li', {class: 'row small'}, h('span', {class: 'lst-text'}, `${x.name} (${TYPE_NAME[x.type]}): ${why(x)}`),
          btn('Select', () => env.reveal(side, x.id), 'btn-small')))) : null,
        rowsOf.length > 5 ? btn(more[side] ? 'Show fewer' : `Show all ${rowsOf.length}`, () => { more[side] = !more[side]; draw(env.view()); }, 'btn-small') : null);
    }
    function draw(view) {
      fill(reviewBox, h('h4', {}, 'Review before export'), Object.keys(SIDE_NAME).map((side) => reviewOf(view, side)));
    }
    const controls = {numberControl, textControl, Q};
    return {el: h('div', {class: 'stack cw-engraving'}, setup.el, h('div', {class: 'row'}, heading, h('span', {class: 'spacer'}), add), failure, setsBox, reviewBox),
      open(id) { const row = rows.get(id); if (row) row.open(); },
      sync(view) {
        setup.sync(view.setup || {device: null, lens: null, material: null, complete: false, missing: []});
        const key = view.settings.map((s) => s.id).join(',');
        if (key !== ids) {
          // the sets that were open stay open, a set that has just been added opens, and so does the only set of a card
          const was = new Set([...rows.values()].filter((r) => r.isOpen()).map((r) => r.id));
          rows.clear();
          for (const s of view.settings) rows.set(s.id, CardSettings.setRow(s, env, controls));
          fill(setsBox, [...rows.values()].map((r) => r.el));
          for (const r of rows.values()) if (was.has(r.id) || (ids !== null && !known.has(r.id)) || (ids === null && view.settings.length === 1)) r.open();
          ids = key;
          known = new Set(view.settings.map((s) => s.id));
        }
        fill(heading, `Engraving settings (${view.settings.length})`);
        for (const s of view.settings) rows.get(s.id).sync(s, usageOf(view, s.id), view.settings.length);
        draw(view);
      }};
  }

  return {Q, SIDE_NAME, TYPE_NAME, TYPE_MARK, NO_GUARANTEE, thumb, numberControl, textControl, selectControl, checkControl, typeForm, suitability, picker, layerList, engravingPanel, choices, artworkColours};
})();
