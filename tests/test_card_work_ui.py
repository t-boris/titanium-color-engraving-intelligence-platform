"""The business-card editor screen (feature-2, REQ-001..005): ``screens/card-work.js`` and ``card-panels.js`` run in node over the small DOM of the
other screen tests, with a stand-in for the canvas (it records what the screen shows it and lets a test fire its handlers) and a small fake
of the card server that answers the way the real one does (the edit operations, the view with its review, the library, the refusals).
So what is read here is the screen's own behaviour: what it posts for each action and how it draws the answers. The look of the page, the
real canvas and the real server are covered elsewhere. The ready engraving settings (the setup bar, the choice by type, the raster picture) are in
test_card_settings_ui.py, which runs on this same harness."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

GLUE = r"""
const __screens = {}, __went = [], __canvases = [], __fonts = [];
App.register = (d) => { __screens[d.id] = d; };
App.go = (route) => { __went.push(route); };
globalThis.__screens = __screens; globalThis.__went = __went; globalThis.__canvases = __canvases; globalThis.__fonts = __fonts;
// the canvas is another file: here it only records what it is shown and keeps the handlers the screen gave it
const CardCanvas = {create(host, handlers) {
  const c = {host, handlers, shows: [], selection: [], fits: 0, zoom: 1, destroyed: false,
    show(state) { c.shows.push(JSON.parse(JSON.stringify(state))); if (Array.isArray(state.selection)) c.selection = state.selection.slice(); }, setSelection(ids) { c.selection = ids; }, fit() { c.fits += 1; },
    setZoom(f) { c.zoom = f; }, getZoom() { return c.zoom; }, destroy() { c.destroyed = true; }};
  __canvases.push(c);
  return c;
}};
const Lettering = {fontWindow(current, sample, onPick) { __fonts.push({current, sample, onPick}); }};
"""

SERVER = r"""
const mkParam = (name, label, type, min, max, def, unit = '') => ({name, label, type, min, max, default: def, unit});
const FILLED = mkParam('filled', 'Filled', 'bool', null, null, false), STROKE = mkParam('stroke_mm', 'Line width', 'number', 0.05, 3, 0.3, 'mm');
const item = (name, label, params) => ({name, label, params, default_size: {width: 20, height: 12}, preview: 'M2 2H22V22H2Z'});
const LIB = {
  shape: [item('rectangle', 'Rectangle', [FILLED, STROKE]), item('star', 'Star', [mkParam('points', 'Points', 'int', 3, 12, 5), FILLED, STROKE])],
  frame: [item('single', 'Single line', [STROKE]), item('double', 'Double line', [mkParam('gap_mm', 'Gap between the lines', 'number', 0.1, 5, 0.6, 'mm'), STROKE])],
  icon: [item('phone', 'Phone', [FILLED, STROKE]), item('mail', 'Mail', [FILLED, STROKE]), item('globe', 'Globe', [FILLED, STROKE])],
  qr: {kinds: ['link', 'vcard', 'text', 'wifi', 'email', 'phone'], ecc: ['L', 'M', 'Q', 'H'], thresholds: {module_mm: 0.4, quiet_modules: 4},
    fields: {link: [{name: 'url', label: 'Web address', type: 'text', required: true}], text: [{name: 'text', label: 'Text', type: 'multiline', required: true}],
      wifi: [{name: 'ssid', label: 'Network name (SSID)', type: 'text', required: true}, {name: 'password', label: 'Password', type: 'password', required: false},
        {name: 'security', label: 'Security', type: 'select', required: false, options: ['WPA', 'WEP', 'nopass'], default: 'WPA'},
        {name: 'hidden', label: 'Hidden network', type: 'bool', required: false, default: false}],
      phone: [{name: 'number', label: 'Phone number', type: 'text', required: true}], email: [{name: 'address', label: 'Email address', type: 'text', required: true}],
      vcard: [{name: 'first_name', label: 'First name', type: 'text', required: false}]}},
  image: {params: [{name: 'auto_threshold', label: 'Find the grey level automatically', type: 'bool', min: null, max: null, default: true, unit: ''},
    mkParam('threshold', 'Grey level', 'int', 0, 255, 128, 'grey level'), {name: 'invert', label: 'Invert (engrave the light parts)', type: 'bool', min: null, max: null, default: false, unit: ''},
    {name: 'treatment', label: 'Treatment', type: 'choice', min: null, max: null, default: 'none', unit: '', options: ['none', 'pencil'], option_labels: {none: 'As drawn', pencil: 'Pencil drawing'}},
    mkParam('detail', 'Detail', 'int', 0, 100, 50, '%'), mkParam('strength', 'Pencil strength', 'int', 0, 100, 60, '%'), mkParam('min_feature_mm', 'Smallest feature', 'number', 0.05, 1, 0.15, 'mm')]},
  presets: [{id: '85x53', width: 85, height: 53, label: '85 × 53 mm'}, {id: '85x54', width: 85, height: 54, label: '85 × 54 mm'}]};
const TEXT_DEFAULT = {text: 'Text', font: null, height_mm: 5, align: 'center', width_pct: 100, spacing_mm: 0, line_pct: 100};
const QR_FIELDS = {link: {url: 'https://example.com'}, text: {text: ''}, wifi: {ssid: '', password: '', security: 'WPA', hidden: false}, phone: {number: ''}, email: {address: ''}, vcard: {first_name: ''}};
const SETTING_LIMITS = {power: [0, 100, 'power (%)'], speed: [0, 100000, 'speed (mm/s)'], frequency: [0, 10000, 'frequency (kHz)'], pulse_width: [0, 10000, 'pulse width (ns)'],
  line_interval: [0, 10, 'line interval (mm)']};
const EXTRA_LIMITS = {min_power: [0, 100, 'minimum power (%)'], scan_angle: [-360, 360, 'scan angle (degrees)'], dot_width: [0, 5, 'dot width (mm)']};
const deep = (v) => JSON.parse(JSON.stringify(v));
// a set with nothing chosen: no value, no origin (the editor offers choices, it does not offer a blank form)
const blank = (id, name) => ({id, name, mode: 'fill', power: null, speed: null, frequency: null, pulse_width: null, line_interval: null, passes: 1, global_passes: null,
  bidirectional: null, cross_hatch: null, scan_angle: null, min_power: null, dither: null, dot_width: null, origin: null, confirmed: false});
const NAMES = {device: {1: 'Laser A', 2: 'Laser B'}, lens: {1: 'Lens 100 mm'}, material: {3: 'Titanium grade 2', 4: 'Titanium grade 5'}};
const named = (kind, id) => (id == null || !NAMES[kind][id] ? null : {id, name: NAMES[kind][id]});
const sameSetup = (a, b) => !!a && !!b && ['device_id', 'lens_id', 'material_id'].every((k) => a[k] === b[k]);

const srv = {refuse: [], generation: {available: false, reason: 'No OpenAI key is set: add it in the workshop AI settings to generate pictures.'}, w: null};
srv.choices = null;                                           // the types of GET settings-choices; null: all four unknown, each with its reason
srv.reset = () => {
  srv.w = {id: 7, name: 'Visit card', preset: '85x53', size_mm: {width: 85, height: 53}, sides: {front: {elements: []}, back: {elements: []}}, settings: [blank(1, 'Engraving 1')],
    setup: {device_id: 1, lens_id: null, material_id: 3}, default: 1, next: 1, nextSettings: 2, undo: [], redo: [], rev: 0};
  srv.choices = null;
};
srv.reset();
const STATE = ['size_mm', 'preset', 'sides', 'settings', 'setup', 'default', 'next', 'nextSettings'];
const snapshot = () => deep(Object.fromEntries(STATE.map((k) => [k, srv.w[k]])));
const fail = (text) => { throw new Error(text); };
const number = (v, label, lo, hi) => { if (typeof v !== 'number' || !Number.isFinite(v) || v < lo || v > hi) fail(`${label} must be a number from ${lo} to ${hi}`); return Math.round(v * 10000) / 10000; };
const isEmpty = (e) => e.type === 'text' && !e.text.text.trim();
const labelOf = (type) => (type === 'qr' ? 'QR code' : type[0].toUpperCase() + type.slice(1));
const find = (side, ids) => {
  const found = srv.w.sides[side].elements.filter((e) => ids.includes(e.id));
  if (!ids.length || found.length !== new Set(ids).size) fail('an element you chose is no longer on this side of the card');
  return found;
};
function build(side, spec) {
  const w = srv.w, els = w.sides[side].elements, type = spec.type;
  const e = {id: 'e' + w.next++, type, name: spec.name || `${labelOf(type)} ${els.filter((x) => x.type === type).length + 1}`, x: spec.x ?? w.size_mm.width / 2, y: spec.y ?? w.size_mm.height / 2,
    rotation: 0, group: null, settings_id: null, width: spec.width, height: spec.height};
  if (type === 'text') Object.assign(e, {text: {...TEXT_DEFAULT, ...(spec.text || {})}, width: 20, height: 5});
  else if (type === 'qr') Object.assign(e, {qr: spec.qr || {kind: 'link', fields: deep(QR_FIELDS.link), ecc: 'M'}, width: 18, height: 18});
  else if (type === 'image') Object.assign(e, {image: spec.image, width: spec.width, height: spec.height});
  else if (type === 'vector') Object.assign(e, {vector: spec.vector, width: spec.width, height: spec.height, group: spec.group || null});
  else {
    const key = {shape: 'kind', frame: 'style', icon: 'name'}[type], chosen = (spec[type] || {})[key];
    const found = LIB[type].find((i) => i.name === chosen);
    if (!found) fail(`there is no ${type} named '${chosen}' in the library`);
    e[type] = {[key]: chosen, ...Object.fromEntries(found.params.map((p) => [p.name, p.default]))};
    e.width = type === 'frame' ? w.size_mm.width - 4 : 20; e.height = type === 'frame' ? w.size_mm.height - 4 : 12;
  }
  return e;
}
function checkEdited(e) {
  if (!e.name.trim()) fail('give the element\'s name some text');
  number(e.x, 'the position x (mm)', -1000, 1000); number(e.y, 'the position y (mm)', -1000, 1000);
  number(e.width, 'the width (mm)', e.type === 'vector' ? 0.02 : 0.2, 500); number(e.height, 'the height (mm)', e.type === 'vector' ? 0.02 : 0.2, 500);
  if (e.type === 'text') number(e.text.height_mm, 'the letter height (mm)', 0.3, 500);
  if (['shape', 'frame', 'icon'].includes(e.type)) {
    const key = {shape: 'kind', frame: 'style', icon: 'name'}[e.type], found = LIB[e.type].find((i) => i.name === e[e.type][key]);
    for (const p of found.params) if (p.type !== 'bool') number(e[e.type][p.name], `the setting '${p.label.toLowerCase()}' of an element`, p.min, p.max);
    for (const k of Object.keys(e[e.type])) if (k !== key && !found.params.some((p) => p.name === k)) fail(`the ${e.type} '${e[e.type][key]}' has no setting '${k}'`);
  }
  if (e.type === 'qr') {                                   // card_qr.checked: every field of the kind present, one the kind does not have refused
    const specs = LIB.qr.fields[e.qr.kind], given = e.qr.fields || {}, unknown = Object.keys(given).filter((k) => !specs.some((s) => s.name === k));
    if (unknown.length) fail(`the QR type '${e.qr.kind}' has no field '${unknown[0]}'`);
    e.qr.fields = Object.fromEntries(specs.map((s) => [s.name, given[s.name] ?? (s.default ?? (s.type === 'bool' ? false : ''))]));
  }
  if (e.type === 'image') {
    for (const p of LIB.image.params) if (['int', 'number'].includes(p.type)) number(e.image[p.name], p.label, p.min, p.max);
    if (!['vector', 'raster'].includes(e.image.engrave)) fail('a picture is engraved as traced shapes or as a photo');
  }
  return e;
}
srv.apply = (b) => {
  const w = srv.w, before = JSON.stringify(snapshot()), added = [];
  const op = b.op;
  if (op === 'set_size') {
    const preset = LIB.presets.find((p) => p.id === b.preset);
    if (preset) { w.preset = preset.id; w.size_mm = {width: preset.width, height: preset.height}; }
    else if (b.preset === 'custom') { w.preset = 'custom'; w.size_mm = {width: number(b.width_mm, 'the card width (mm)', 10, 300), height: number(b.height_mm, 'the card height (mm)', 10, 300)}; }
    else fail('choose a card size: 85 × 53 mm, 85 × 54 mm or a custom size');
  } else if (op === 'settings_add') {
    w.settings.push(blank(w.nextSettings, b.name || `Engraving ${w.nextSettings}`)); w.nextSettings += 1;
  } else if (op === 'set_setup') {
    if (!NAMES.device[b.device_id]) fail('choose the laser of this card.');
    if (b.lens_id !== null && !NAMES.lens[b.lens_id]) fail('choose a lens, or the unknown lens.');
    if (!NAMES.material[b.material_id]) fail('choose the material of this card.');
    const next = {device_id: b.device_id, lens_id: b.lens_id, material_id: b.material_id};
    if (!sameSetup(next, w.setup)) {                               // card_work._resetup: what was chosen for the old setup never carries over
      w.settings = w.settings.map((set) => {
        if (!set.origin) return set;
        if (set.origin.kind === 'custom') return {...set, confirmed: false};
        return {...blank(set.id, set.name)};
      });
    }
    w.setup = next;
  } else if (['settings_set', 'settings_delete', 'settings_apply', 'settings_confirm', 'settings_custom'].includes(op)) {
    const set = w.settings.find((s) => s.id === (b.settings_id ?? b.id));
    if (!set) fail('these engraving settings no longer exist');
    if (op === 'settings_delete') {
      if (w.settings.length < 2) fail('a card keeps at least one set of engraving settings');
      w.settings = w.settings.filter((s) => s !== set);
      if (w.default === set.id) w.default = w.settings[0].id;
      for (const s of ['front', 'back']) for (const e of w.sides[s].elements) if (e.settings_id === set.id) e.settings_id = null;
    } else if (op === 'settings_apply') {
      const found = srv.items().find((i) => i.id === b.choice_id);
      if (!found) fail('these settings are not measured for this laser, lens and material.');
      const fresh = blank(set.id, set.name);
      fresh.passes = null;
      for (const [k, v] of Object.entries(found.settings)) if (v !== null) fresh[k] = v;
      Object.assign(set, fresh, {origin: {kind: 'choice', choice_id: found.id, type: found.type, source: found.source, label: found.label, detail: found.detail, evidence: found.evidence,
        swatch: found.swatch ? found.swatch.srgb : null, setup: {...w.setup}, at: 'now', note: null, proposed: false}, confirmed: true});
    } else if (op === 'settings_confirm') {
      if (!set.origin) fail('there are no settings to confirm: choose some first.');
      if (set.origin.kind === 'choice' && !sameSetup(set.origin.setup, w.setup)) fail('these settings were chosen for another laser, lens or material: choose them again.');
      set.origin = {...set.origin, setup: {...w.setup}, proposed: false}; set.confirmed = true;
    } else if (op === 'settings_custom') {
      const before = set.origin;
      set.origin = {kind: 'custom', choice_id: null, type: null, source: 'Custom', label: 'Typed by the operator', detail: 'The values were typed by hand, not taken from a measurement.',
        evidence: null, setup: {...w.setup}, at: 'now', note: before && before.kind === 'choice' ? `Started from ${before.label}.` : null, proposed: false};
      set.confirmed = true;
    } else {
      for (const [k, v] of Object.entries(b.changes)) {
        if (k === 'name') set.name = v;
        else if (k === 'mode') set.mode = v;
        else if (k === 'passes') set.passes = number(v, 'the passes', 1, 100);
        else if (k === 'dither') set.dither = v;
        else if (v === null) set[k] = null;
        else if (EXTRA_LIMITS[k]) { const [lo, hi, label] = EXTRA_LIMITS[k]; set[k] = number(v, label, lo, hi); }
        else { const [lo, hi, label] = SETTING_LIMITS[k]; set[k] = number(v, label, lo, hi); }
      }
      if (Object.keys(b.changes).some((k) => k !== 'name')) {            // a number was typed: the set is the operator's own now
        const before = set.origin;
        set.origin = {kind: 'custom', choice_id: null, type: null, source: 'Custom', label: 'Typed by the operator', detail: 'The values were typed by hand, not taken from a measurement.',
          evidence: null, setup: {...w.setup}, at: 'now', note: before && before.kind === 'choice' ? `Started from ${before.label}.` : null, proposed: false};
        set.confirmed = true;
      }
    }
  } else {
    const side = b.side;
    if (!['front', 'back'].includes(side)) fail('choose a side of the card: front or back');
    const els = w.sides[side].elements;
    if (op === 'add') { const e = build(side, b.element); els.push(e); added.push(e.id); }
    else if (op === 'set') {
      const e = find(side, [b.id])[0], next = deep(e);
      for (const [k, v] of Object.entries(b.changes)) {
        if (k === e.type) next[k] = {...next[k], ...v};
        else if (['name', 'x', 'y', 'width', 'height', 'rotation', 'group', 'settings_id'].includes(k)) next[k] = v;
        else fail(`an element has no field '${k}'`);
      }
      els[els.indexOf(e)] = checkEdited(next);
    } else if (op === 'move') { for (const e of find(side, b.ids)) { e.x += b.dx; e.y += b.dy; } }
    else if (op === 'resize') {
      const e = find(side, [b.id])[0], least = e.type === 'vector' ? 0.02 : 0.2, width = number(b.width ?? e.width, 'the width (mm)', least, 500), height = number(b.height ?? e.height, 'the height (mm)', least, 500);
      if ('x' in b) e.x = b.x;
      if ('y' in b) e.y = b.y;
      if (e.type === 'text') e.text.height_mm = Math.round(e.text.height_mm * width / e.width * 10000) / 10000;
      if (e.type === 'qr') e.width = e.height = Math.max(width, height); else { e.width = width; e.height = height; }
    } else if (op === 'rotate') { find(side, [b.id])[0].rotation = number(b.rotation, 'the rotation (degrees)', -3600, 3600); }
    else if (op === 'reorder') {
      const ids = b.ids || [b.id], chosen = find(side, ids), rest = els.filter((e) => !ids.includes(e.id));
      if (b.to === 'front') w.sides[side].elements = [...rest, ...chosen];
      else if (b.to === 'back') w.sides[side].elements = [...chosen, ...rest];
      else {
        const out = [...els];
        if (b.to === 'forward') { for (let i = out.length - 2; i >= 0; i--) if (ids.includes(out[i].id) && !ids.includes(out[i + 1].id)) [out[i], out[i + 1]] = [out[i + 1], out[i]]; }
        else for (let i = 1; i < out.length; i++) if (ids.includes(out[i].id) && !ids.includes(out[i - 1].id)) [out[i], out[i - 1]] = [out[i - 1], out[i]];
        w.sides[side].elements = out;
      }
    } else if (op === 'duplicate') {
      for (const e of find(side, b.ids)) { const twin = deep(e); twin.id = 'e' + w.next++; twin.x += 2; twin.y += 2; twin.name = e.name + ' copy'; els.push(twin); added.push(twin.id); }
    } else if (op === 'delete') { const gone = find(side, b.ids).map((e) => e.id); w.sides[side].elements = els.filter((e) => !gone.includes(e.id)); }
    else if (op === 'group') { if (b.ids.length < 2) fail('choose at least two elements to group'); const g = 'g' + w.next++; for (const e of find(side, b.ids)) e.group = g; }
    else if (op === 'ungroup') { const labels = new Set(find(side, b.ids).map((e) => e.group)); for (const e of els) if (labels.has(e.group)) e.group = null; }
    else if (op === 'assign_settings') {
      if (b.settings_id !== null && !w.settings.some((s) => s.id === b.settings_id)) fail('the engraving settings you chose no longer exist');
      for (const e of find(side, b.ids)) e.settings_id = b.settings_id;
    } else if (op === 'assign_choice') {                           // card_work._set_of_choice: the card's own set for this choice, made when there is none
      const found = srv.items().find((i) => i.id === b.choice_id);
      if (!found) fail('these settings are not measured for this laser, lens and material.');
      if (!(b.ids || []).length) fail('choose the elements or the group to give these engraving settings');
      let set = w.settings.find((s) => s.origin && s.origin.kind === 'choice' && s.origin.choice_id === found.id && s.confirmed && sameSetup(s.origin.setup, w.setup));
      if (!set) {
        set = blank(w.nextSettings, found.label); w.nextSettings += 1;
        set.passes = null;
        for (const [k, v] of Object.entries(found.settings)) if (v !== null) set[k] = v;
        Object.assign(set, {origin: {kind: 'choice', choice_id: found.id, type: found.type, source: found.source, label: found.label, detail: found.detail, evidence: found.evidence,
          swatch: found.swatch ? found.swatch.srgb : null, setup: {...w.setup}, at: 'now', note: null, proposed: false}, confirmed: true});
        w.settings.push(set);
      }
      for (const e of find(side, b.ids)) e.settings_id = set.id;
    } else if (op === 'recolour') {
      const hex = /^#[0-9a-f]{6}$/i;
      if (!b.reset && !hex.test(b.fill || '')) fail('a design colour is written like #c08040');
      for (const e of find(side, b.ids)) { if (e.type !== 'vector') fail('only the parts of imported artwork have a design colour'); e.vector.fill = b.reset ? e.vector.source : b.fill.toLowerCase(); }
    } else if (op === 'scale') {
      const f = number(b.factor, 'the scale', 0.05, 20), chosen = find(side, b.ids);
      const x0 = Math.min(...chosen.map((e) => e.x - e.width / 2)), x1 = Math.max(...chosen.map((e) => e.x + e.width / 2)), y0 = Math.min(...chosen.map((e) => e.y - e.height / 2)), y1 = Math.max(...chosen.map((e) => e.y + e.height / 2));
      const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
      for (const e of chosen) { e.x = cx + (e.x - cx) * f; e.y = cy + (e.y - cy) * f; e.width *= f; e.height *= f; }
    } else fail('this edit is not known');
  }
  if (JSON.stringify(snapshot()) !== before) { w.undo.push(JSON.parse(before)); w.redo = []; w.rev += 1; }
  return added;
};
srv.step = (direction) => {
  const w = srv.w, from = direction === 'undo' ? w.undo : w.redo, to = direction === 'undo' ? w.redo : w.undo;
  if (!from.length) fail(direction === 'undo' ? 'there is no earlier change of the card to undo' : 'there is no undone change to redo');
  const there = from.pop(); to.push(snapshot()); Object.assign(w, there); w.rev += 1;
};
// card_work._need, _state, _status and _review: where a set stands and what it still needs
const need = (set, raster) => ['power', 'speed', 'frequency', ...(set.mode === 'fill' || raster ? ['line_interval'] : []), ...(raster ? ['min_power', 'dither'] : [])].filter((k) => set[k] == null);
function stateOf(set) {
  const w = srv.w, o = set.origin;
  if (!o) return 'unknown';
  if (!sameSetup(o.setup, w.setup) || w.setup.material_id === null) return 'other_setup';
  if (o.kind === 'custom') return 'custom';
  return set.confirmed ? 'chosen' : 'proposed';
}
const SUMMARY = {unknown: 'No settings are chosen yet.', proposed: 'Proposed from the workshop\'s measurements. Confirm them or choose others.', chosen: 'Chosen from the workshop\'s measurements.',
  custom: 'Typed by hand, the last resort.', other_setup: 'Chosen for another laser, lens or material.'};
function statusOf(set, raster) {
  const state = stateOf(set), needs = [];
  if (srv.w.setup.material_id === null) needs.push('the material of this card');
  if (state === 'unknown') needs.push('settings chosen for this laser, lens and material');
  else if (state === 'other_setup') needs.push('settings chosen again, or confirmed, for this laser, lens and material');
  else if ((state === 'proposed' || state === 'custom') && !set.confirmed) needs.push('your confirmation');
  const missing = state !== 'unknown' ? need(set, raster) : [];
  if (missing.length) needs.push(missing.map((k) => k.replace('_', ' ')).join(', '));
  return {state, ready: !needs.length, needs, summary: SUMMARY[state]};
}
const effectiveId = (e) => (srv.w.settings.some((s) => s.id === e.settings_id) ? e.settings_id : srv.w.default);
const isRaster = (e) => e.type === 'image' && e.image.engrave === 'raster';
const rasterSets = () => new Set(['front', 'back'].flatMap((side) => srv.w.sides[side].elements.filter(isRaster).map(effectiveId)));
function review(side) {
  const w = srv.w, rows = [], sets = {}, problems = [], raster = rasterSets();
  for (const e of w.sides[side].elements) {
    const eff = effectiveId(e), set = w.settings.find((s) => s.id === eff), status = statusOf(set, raster.has(eff));
    rows.push({id: e.id, name: e.name, type: e.type, settings_id: e.settings_id, effective_settings_id: eff, complete: status.ready, empty: isEmpty(e), raster: isRaster(e)});
    if (!isEmpty(e)) {
      sets[eff] = sets[eff] || {settings_id: eff, name: set.name, elements: [], state: status.state, needs: status.needs, missing: status.state !== 'unknown' ? need(set, raster.has(eff)) : [], complete: status.ready};
      sets[eff].elements.push(e.id);
    }
  }
  for (const s of Object.values(sets)) if (s.needs.length) problems.push(`The engraving settings “${s.name}” still need ${s.needs.join('; ')}.`);
  if (!w.sides[side].elements.some((e) => !isEmpty(e))) problems.push(`There is nothing to engrave on the ${side}`);
  return {ready: !problems.length, problems, sets: Object.values(sets), elements: rows, empty: !rows.length};
}
srv.matches = (colours) => {
  const items = srv.items().filter((i) => i.type === 'color');
  const out = {available: items.length > 0, reason: items.length ? null : 'No colour is measured for this laser, lens and material yet.', close_delta_e: 25, matches: {}};
  for (const c of colours) {
    const near = items.map((i) => ({choice_id: i.id, label: i.label, swatch: i.swatch ? i.swatch.srgb : null, delta_e: srv.deltaE && srv.deltaE[c] ? (srv.deltaE[c][i.id] ?? 99) : 10})).sort((a, b) => a.delta_e - b.delta_e);
    out.matches[c] = {best: near[0] || null, close: !!near[0] && near[0].delta_e <= 25, alternatives: near.slice(1, 3)};
  }
  return out;
};
srv.items = () => (srv.choices || []).flatMap((t) => t.groups.flatMap((g) => g.items));
srv.setupView = () => {
  const s = srv.w.setup, device = named('device', s.device_id), material = named('material', s.material_id);
  return {set: s.material_id !== null, device_id: s.device_id, lens_id: s.lens_id, material_id: s.material_id, device, lens: named('lens', s.lens_id), material,
    complete: !!device && !!material, missing: [...(device ? [] : ['device']), ...(material ? [] : ['material'])]};
};
srv.choicesAnswer = () => ({setup: srv.setupView(), types: srv.choices || [['color', 'Colour'], ['photo', 'Photo'], ['line_text', 'Lines and text'], ['deep', 'Deep engraving']]
  .map(([type, label]) => ({type, label, known: false, reason: `Nothing of type ${type} has been measured for this laser, lens and material.`, groups: []}))});
function elementView(e, els) {
  const out = deep(e), warnings = [];
  out.d = 'M0 0L1 0L1 1Z'; if (e.type === 'vector') out.color = e.vector.fill; out.bounds = [e.x - e.width / 2, e.y - e.height / 2, e.x + e.width / 2, e.y + e.height / 2]; out.empty = isEmpty(e);
  out.problems = isEmpty(e) ? ['Nothing to engrave: the text is empty'] : [];
  if (e.type === 'qr') {
    const modules = 25, moduleMm = e.width / modules, quiet = els.some((o) => o !== e && !isEmpty(o)) ? 1.5 : 10;
    if (moduleMm < 0.4) warnings.push({code: 'module_size', message: `The modules are ${moduleMm.toFixed(2)} mm wide, below the 0.40 mm that engraves reliably.`});
    if (quiet < 4) warnings.push({code: 'quiet_zone', message: `The quiet zone is ${quiet.toFixed(1)} modules, below the 4 modules a scanner needs.`});
    out.qr_info = {content: 'x', modules, module_mm: +moduleMm.toFixed(3), quiet_modules: quiet, clearance_mm: quiet * moduleMm, thresholds: {module_mm: 0.4, quiet_modules: 4},
      note: 'Passing these checks does not guarantee that the engraved code will scan.'};
  }
  if (e.x - e.width / 2 < 0) warnings.push({code: 'outside_card', message: 'Part of this element lies outside the card and would not be engraved on it.'});
  out.warnings = warnings;
  if (e.type === 'image') {
    const set = srv.w.settings.find((s) => s.id === effectiveId(e));
    out.image.engrave = e.image.engrave || 'vector';
    out.raster = isRaster(e) ? {url: `/api/card-works/7/elements/${e.id}/raster.png?v=${srv.w.rev}`, width_px: Math.round(e.width * 10), height_px: Math.round(e.height * 10), dpi: 254,
      dither: set.dither || 'grayscale', given: !!(set.line_interval && set.dither)} : null;
  }
  return out;
}
srv.view = (added) => {
  const w = srv.w, raster = rasterSets(), out = {id: w.id, name: w.name, size_mm: deep(w.size_mm), preset: w.preset, presets: LIB.presets, sides: {},
    settings: deep(w.settings).map((set) => ({...set, status: statusOf(set, raster.has(set.id))})), default_settings_id: w.default, review: {}, setup: srv.setupView(),
    can_undo: w.undo.length > 0, can_redo: w.redo.length > 0, updated_at: 'rev' + w.rev, laser: {id: 1, name: 'Laser'}, generation: srv.generation, qr: {thresholds: LIB.qr.thresholds}};
  for (const side of ['front', 'back']) { out.sides[side] = {elements: w.sides[side].elements.map((e, i, all) => elementView(e, all))}; out.review[side] = review(side); }
  if (added) out.added = added;
  return out;
};
srv.seed = (side, type, count) => { for (let i = 0; i < count; i++) srv.w.sides[side].elements.push(build(side, {type, ...(type === 'text' ? {text: {text: 'Line ' + (i + 1)}} : {})})); };

const log = [];
const reply = (status, json, type) => ({ok: status < 300, status, headers: {get: (k) => (k.toLowerCase() === 'content-type' ? (json === undefined ? (type || 'text/plain') : 'application/json') : null)},
  json: async () => json, blob: async () => ({size: 10}), text: async () => ''});
ctx.fetch = async (url, opts = {}) => {
  const method = opts.method || 'GET', path = String(url).split('?')[0], raw = opts.body;
  const body = typeof raw === 'string' ? JSON.parse(raw) : raw instanceof FormData ? {side: raw.get('side'), ...(raw.get('picture') ? {picture: raw.get('picture').name} : {picture: null}), ...(raw.get('artwork') ? {artwork: raw.get('artwork').name} : {})} : null;
  log.push({method, path, url: String(url), body});
  await Promise.resolve();
  const refused = srv.refuse.findIndex((r) => r.when(method, path, body));
  if (refused >= 0) { const r = srv.refuse.splice(refused, 1)[0]; return reply(r.status || 400, {error: r.error, kind: r.kind || 'invalid'}); }
  try {
    if (method === 'GET' && path === '/api/card-library') return reply(200, LIB);
    if (method === 'GET' && path === '/api/card-works/7') return reply(200, srv.view());
    if (method === 'GET' && path === '/api/card-works/7/settings-choices') return reply(200, srv.choicesAnswer());
    if (method === 'GET' && path.endsWith('/export.lbrn2')) return reply(200, undefined, 'application/octet-stream');
    if (method === 'GET' && path === '/api/works') return reply(200, srv.catalog());
    if (method === 'POST' && path === '/api/card-works') {
      if (body.preset === 'custom') { number(body.width_mm, 'the card width (mm)', 10, 300); number(body.height_mm, 'the card height (mm)', 10, 300); }
      if (!srv.w.laser && srv.noLaser) fail('add the laser first: a card is engraved with a laser of the workshop');
      return reply(201, {...srv.view(), id: 8, name: body.name});
    }
    if (method === 'POST' && path === '/api/card-works/7/edit') { const added = srv.apply(body); return reply(200, srv.view(added)); }
    if (method === 'POST' && path === '/api/card-works/7/undo') { srv.step('undo'); return reply(200, srv.view()); }
    if (method === 'POST' && path === '/api/card-works/7/redo') { srv.step('redo'); return reply(200, srv.view()); }
    if (method === 'POST' && path === '/api/card-works/7/rename') { srv.w.name = body.name.trim(); return reply(200, {name: srv.w.name}); }
    if (method === 'POST' && path === '/api/card-works/7/copy') return reply(201, {...srv.view(), id: 9});
    if (method === 'POST' && path === '/api/card-works/7/images') {
      const stem = body.picture.replace(/\.[^.]+$/, '');
      const e = build(body.side, {type: 'image', name: stem, width: 30, height: 15, image: {name: stem, size: [200, 100], auto_threshold: true, threshold: 128, invert: false, treatment: 'none',
        detail: 50, strength: 60, min_feature_mm: 0.15, origin: 'import', prompt: null, engrave: 'vector'}});
      srv.w.sides[body.side].elements.push(e); srv.w.undo.push(snapshot()); return reply(200, srv.view([e.id]));
    }
    if (method === 'GET' && path === '/api/card-works/7/colour-matches') {
      const wanted = decodeURIComponent((String(url).split('colours=')[1] || '')).split(',').filter(Boolean);
      return reply(200, srv.matches(wanted));
    }
    if (method === 'POST' && path === '/api/card-works/7/vector') {
      const stem = body.artwork.replace(/\.[^.]+$/, ''), kind = /\.ai$/i.test(body.artwork) ? 'ai' : 'svg';
      if (srv.vectorFile && srv.vectorFile.fail) fail(srv.vectorFile.fail);
      const parts = (srv.vectorFile && srv.vectorFile.parts) || [['body', '#a05a2c', 20, 12, 40, 26], ['ear', '#a05a2c', 6, 6, 30, 18], ['eye', '#101010', 4, 4, 44, 24]];
      const label = 'gv' + srv.w.undo.length, ids = [];
      for (const [name, fill, width, height, x, y] of parts) {
        const e = build(body.side, {type: 'vector', name, width, height, x, y, group: parts.length > 1 ? label : null, vector: {artwork: 'vector-0123456789ab.json', part: ids.length, fill, source: fill, file: body.artwork, kind}});
        srv.w.sides[body.side].elements.push(e); ids.push(e.id);
      }
      srv.w.undo.push(snapshot());
      const report = {kind, parts: parts.length, colours: new Set(parts.map((q) => q[1])).size, merged: 0, dropped: 0, background: false, notes: (srv.vectorFile && srv.vectorFile.notes) || [],
        size_mm: {width: 30, height: 20}, file: body.artwork, engraving: (srv.vectorFile && srv.vectorFile.engraving) || {available: false, reason: 'No engraving colour is measured for this card yet.', assigned: 0, colours: 2}};
      return reply(200, {...srv.view(ids), import: report});
    }
    if (method === 'POST' && path === '/api/card-works/7/generate') {
      if (!srv.generation.available) fail(srv.generation.reason);
      const e = build(body.side, {type: 'image', name: `${body.kind} ${body.description}`.slice(0, 30), width: 30, height: 30, image: {name: body.description, size: [1024, 1024], auto_threshold: true,
        threshold: 128, invert: false, treatment: 'none', detail: 50, strength: 60, min_feature_mm: 0.15, origin: 'generated', prompt: body.description, engrave: 'vector'}});
      srv.w.sides[body.side].elements.push(e); return reply(200, srv.view([e.id]));
    }
  } catch (e) { return reply(400, {error: e.message, kind: 'invalid'}); }
  return reply(404, {error: path + ' not found', kind: 'not_found'});
};
"""

HARNESS = r"""
const {context, load, El} = require(__DOM__);
const ctx = context({});
ctx.FormData = FormData; ctx.File = File; ctx.Blob = Blob;
ctx.setInterval = () => 0;
const downloads = [];
El.prototype.click = function () { downloads.push(this.getAttribute('download')); };
__SERVER__
load(ctx, __UI__, [...__TABLES__, 'app.js', 'save-state.js', 'dialogs.js', 'list.js', 'filepick.js', 'hardware.js', 'screens/material-picker.js', 'screens/lifecycle.js',
  'screens/vector-workspace.js', {code: __GLUE__}, 'screens/card-settings.js', 'screens/card-panels.js', 'screens/card-layout.js', 'screens/card-work.js', 'screens/works.js',
  {code: 'globalThis.CardWork = CardWork; globalThis.CardPanels = CardPanels; globalThis.CardSettings = CardSettings; globalThis.Works = Works;'}]);
const App = ctx.App, doc = ctx.document, Works = ctx.Works;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
/** Wait until ``fn()`` is true (a request takes a few ticks); fail the test when it never is. */
const until = async (fn, what = 'a condition', ms = 4000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { try { if (fn()) return; } catch (_) { /* not drawn yet */ } await sleep(4); }
  throw new Error('timed out waiting for ' + what + '; requests: ' + log.slice(-5).map((x) => x.method + ' ' + x.path + ' ' + JSON.stringify(x.body)).join(' | '));
};
const main = doc.createElement('div'); main.setAttribute('id', 'main'); doc.body.append(main);
let root = null;
/** The card screen as the router mounts it. */
const open = async (query = {work: '7'}) => {
  const tree = await ctx.__screens['card-work'].render({query});
  main.replaceChildren(tree);
  root = tree;
  await sleep(2);
  return tree;
};
const canvas = () => ctx.__canvases[ctx.__canvases.length - 1];
const lastShow = () => canvas().shows[canvas().shows.length - 1];
const line = () => root.querySelector('.save-line').textContent;
/** Every change sent has been answered and the screen is drawn from the last answer. */
const saved = async () => { await sleep(0); await until(() => /^Card: Saved/.test(line()), 'the card to be saved (' + line() + ')'); };
const buttons = (scope = root) => scope.querySelectorAll('button');
const button = (text, scope = root) => buttons(scope).find((b) => b.textContent === text) || buttons(scope).find((b) => b.getAttribute('aria-label') === text);
const press = async (text, scope = root) => { const b = button(text, scope); if (!b) throw new Error('no button ' + text); await b.dispatch('click'); await sleep(0); };
const labelled = (text, scope = root) => scope.querySelectorAll('label').find((l) => l.textContent === text || (l.childNodes[0] && l.childNodes[0].textContent === text));
const control = (text, scope = root) => { const l = labelled(text, scope); if (!l) throw new Error('no field ' + text); return l.querySelectorAll('input, select, textarea').find((c) => c.getAttribute('type') !== 'range') ; };
const slider = (text, scope = root) => labelled(text, scope).querySelectorAll('input').find((c) => c.getAttribute('type') === 'range');
const typeInto = async (input, value) => { input.value = String(value); await input.dispatch('input'); await input.dispatch('change'); };
const fill_ = async (text, value, scope = root) => typeInto(control(text, scope), value);
const choose = async (text, value, scope = root) => { const s = control(text, scope); s.value = value; await s.dispatch('change'); };
const tick = async (text, on, scope = root) => { const c = control(text, scope); c.checked = on; await c.dispatch('change'); };
const posts = (suffix = '/edit') => log.filter((x) => x.method === 'POST' && x.path.endsWith(suffix)).map((x) => x.body);
const lastPost = (suffix = '/edit') => posts(suffix).slice(-1)[0];
const layerNames = () => root.querySelectorAll('.cw-layer-name').map((n) => n.textContent);
const rightTitle = () => root.querySelector('.cw-right').querySelector('h3').textContent;
const dialog = () => doc.body.querySelector('.modal');
const text = (el) => (el ? el.textContent : null);
const tabs = () => root.querySelectorAll('button').filter((b) => b.getAttribute('role') === 'tab' && (b.getAttribute('id') || '').startsWith('cw-tab-'));    // the sides, not the types of engraving
/** Open the "Custom values" of a set (the number boxes are built when it opens). */
const openCustom = async (scope = root) => { const box = scope.querySelector('.cw-custom'); box.open = true; await box.dispatch('toggle'); return box; };
const addElement = async (label, expected) => { await press(label); await saved(); return expected; };
const errorOf = (label, scope = root) => { const l = labelled(label, scope); return l ? text(l.querySelectorAll('span').find((s) => s.classList.contains('f-error'))) : null; };
(async () => {
  const out = {};
__BODY__
  console.log(JSON.stringify(out));
  process.exit(0);
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, body: str) -> dict:
    """Run ``body`` in node against the card screen; it fills ``out`` (JSON)."""
    script = tmp_path / "card_work_ui.js"
    code = HARNESS
    for token, value in (("__DOM__", json.dumps(str(Path(__file__).with_name("ui_dom.js")))), ("__UI__", json.dumps(str(UI) + "/")), ("__TABLES__", json.dumps(TABLES)),
                         ("__GLUE__", json.dumps(GLUE)), ("__SERVER__", SERVER), ("__BODY__", body)):
        code = code.replace(token, value)
    script.write_text(code, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, (done.stderr or done.stdout)[-4000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


# -- the screen, the two sides, the size --------------------------------------------------------------------------------------------------------------
@node
def test_the_screen_is_registered_and_draws_the_front_and_the_back_in_tabs(tmp_path):
    out = run(tmp_path, """
  out.registered = Object.keys(ctx.__screens);
  srv.seed('back', 'text', 1);
  await open();
  out.rootClass = root.className;
  out.tabs = tabs().map((t) => [t.textContent, t.getAttribute('aria-selected'), t.getAttribute('tabindex')]);
  out.first = lastShow();
  out.state = line();
  await press('Back');
  out.afterBack = {tabs: tabs().map((t) => t.getAttribute('aria-selected')), shown: lastShow().elements.map((e) => e.name), panel: root.querySelector('.cw-panel').getAttribute('aria-labelledby')};
  const bar = root.querySelectorAll('div').find((d) => d.getAttribute('role') === 'tablist');
  await bar.dispatch('keydown', {key: 'ArrowLeft'});
  out.afterArrow = tabs().map((t) => t.getAttribute('aria-selected'));
  out.fitted = canvas().fits >= 2;
  out.size = text(button('Card size: 85 × 53 mm'));
  out.title = text(root.querySelector('h2'));
""")
    assert out["registered"] == ["card-work", "works"] and "os" in out["rootClass"].split()
    assert out["tabs"] == [["Front", "true", "0"], ["Back", "false", "-1"]]
    assert out["first"]["size_mm"] == {"width": 85, "height": 53} and out["first"]["elements"] == [] and out["first"]["grid"] is True
    assert out["state"].startswith("Card: Saved")
    assert out["afterBack"] == {"tabs": ["false", "true"], "shown": ["Text 1"], "panel": "cw-tab-back"}
    assert out["afterArrow"] == ["true", "false"] and out["fitted"] is True
    assert out["size"] == "Card size: 85 × 53 mm" and out["title"] == "Visit card"


@node
def test_the_size_dialog_offers_the_presets_and_a_custom_size_and_tells_a_refusal_beside_its_fields(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('Card size: 85 × 53 mm');
  const box = dialog();
  out.radios = box.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'radio').map((i) => [i.getAttribute('aria-label'), i.checked]);
  const custom = box.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'Custom size');
  out.hiddenFirst = box.querySelector('.toolbar').hidden;
  custom.checked = true; await custom.dispatch('change');
  out.hiddenAfter = box.querySelector('.toolbar').hidden;
  await fill_('Width', 5, box);
  await press('Set size', box);
  out.small = {error: errorOf('Width', box), posts: posts().length};
  await fill_('Width', 90, box); await fill_('Height', 55, box);
  srv.refuse.push({when: (m, p, b) => b && b.op === 'set_size', error: 'the card width (mm) must be a number from 10 to 300'});
  await press('Set size', box);
  out.refused = {open: !!dialog(), form: text(box.querySelector('.f-form-error')), state: line()};
  await press('Set size', box);
  await saved();
  out.done = {closed: !dialog(), body: lastPost(), shown: lastShow().size_mm, button: buttons().some((b) => b.textContent === 'Card size: 90 × 55 mm')};
""")
    assert out["radios"] == [["85 × 53 mm", True], ["85 × 54 mm", False], ["Custom size", False]]
    assert out["hiddenFirst"] is True and out["hiddenAfter"] is False
    assert out["small"]["error"].startswith("Allowed: from 10 to 300 mm") and out["small"]["posts"] == 0
    assert out["refused"]["open"] is True and "must be a number from 10 to 300" in out["refused"]["form"] and out["refused"]["state"].startswith("Card: Saved")
    assert out["done"] == {"closed": True, "body": {"op": "set_size", "preset": "custom", "width_mm": 90, "height_mm": 55}, "shown": {"width": 90, "height": 55}, "button": True}


@node
def test_renaming_the_card_posts_the_new_name_and_redraws_the_title(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('✎');
  const input = dialog().querySelectorAll('input')[0];
  await typeInto(input, 'Boris Tsekinovsky');
  await press('Save', dialog());
  await until(() => text(root.querySelector('h2')) === 'Boris Tsekinovsky', 'the title');
  out.rename = lastPost('/rename'); out.title = text(root.querySelector('h2'));
""")
    assert out == {"rename": {"name": "Boris Tsekinovsky"}, "title": "Boris Tsekinovsky"}


# -- adding elements ----------------------------------------------------------------------------------------------------------------------------------
@node
def test_each_kind_of_element_is_added_with_one_edit_and_the_new_element_is_selected(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('Text'); await saved();
  out.text = {body: lastPost(), selected: canvas().shows.slice(-1)[0].selection, title: rightTitle(), name: control('Name').value};
  await press('QR code'); await saved();
  out.qr = {body: lastPost(), title: rightTitle(), selected: lastShow().selection};
  await press('Shape');
  out.shapeOpen = button('Shape').getAttribute('aria-expanded');
  out.shapeItems = buttons().filter((b) => (b.getAttribute('aria-label') || '').startsWith('Add ')).map((b) => b.getAttribute('aria-label'));
  await press('Add Star'); await saved();
  out.star = lastPost();
  await press('Frame'); await press('Add Double line'); await saved();
  out.frame = lastPost();
  out.shapeClosed = button('Shape').getAttribute('aria-expanded');
  await press('Icon'); await press('Add Mail'); await saved();
  out.icon = lastPost();
  out.layers = layerNames();
  out.count = text(root.querySelector('.cw-layer-count'));
  out.canvas = lastShow().elements.map((e) => e.type);
  out.rows = root.querySelectorAll('.cw-layer-type').map((n) => n.textContent);
""")
    assert out["text"] == {"body": {"op": "add", "side": "front", "element": {"type": "text"}}, "selected": ["e1"], "title": "Selected", "name": "Text 1"}
    assert out["qr"] == {"body": {"op": "add", "side": "front", "element": {"type": "qr"}}, "title": "Selected", "selected": ["e2"]}
    assert out["shapeOpen"] == "true" and out["shapeItems"] == ["Add Rectangle", "Add Star"]
    assert out["star"] == {"op": "add", "side": "front", "element": {"type": "shape", "shape": {"kind": "star"}}}
    assert out["frame"] == {"op": "add", "side": "front", "element": {"type": "frame", "frame": {"style": "double"}}} and out["shapeClosed"] == "false"
    assert out["icon"] == {"op": "add", "side": "front", "element": {"type": "icon", "icon": {"name": "mail"}}}
    assert out["layers"] == ["Icon 1", "Frame 1", "Shape 1", "QR code 1", "Text 1"] and out["count"] == "5 on the front"
    assert out["canvas"] == ["text", "qr", "shape", "frame", "icon"] and out["rows"] == ["★", "▢", "◆", "QR", "T"]


@node
def test_adding_to_the_back_posts_the_back_side(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('Back');
  await press('Text'); await saved();
  out.body = lastPost();
  out.front = srv.w.sides.front.elements.length; out.back = srv.w.sides.back.elements.length;
  out.shown = lastShow().elements.map((e) => e.name);
""")
    assert out == {"body": {"op": "add", "side": "back", "element": {"type": "text"}}, "front": 0, "back": 1, "shown": ["Text 1"]}


# -- editing the selected element ---------------------------------------------------------------------------------------------------------------------
@node
def test_the_inspector_posts_one_edit_per_field_and_redraws_from_the_answer(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('Text'); await saved();
  await fill_('Name', 'Title'); await saved();
  out.name = lastPost();
  await fill_('Center X', 30.5); await saved();
  out.x = lastPost();
  await fill_('Center Y', 12); await saved();
  out.y = lastPost();
  await fill_('Width', 40); await saved();
  out.width = lastPost();
  await fill_('Rotation', 15); await saved();
  out.rotation = lastPost();
  out.afterResize = {height: control('Letter height').value, canvas: lastShow().elements[0].width};
  await fill_('Text', 'Boris'); await saved();
  out.text = lastPost();
  await fill_('Letter height', 7); await saved();
  out.letter = lastPost();
  await fill_('Letter spacing', 1.5); await saved();
  out.spacing = lastPost();
  await choose('Alignment', 'left'); await saved();
  out.align = lastPost();
  await press('Choose font…');
  out.fontCall = {sample: ctx.__fonts[0].sample, current: ctx.__fonts[0].current};
  await ctx.__fonts[0].onPick({face: 'f1', family: 'Inter', style: 'Regular'}); await saved();
  out.font = lastPost();
  out.fontShown = root.querySelectorAll('span').some((s) => s.textContent === 'Inter Regular');
  out.layerAfter = layerNames();
  out.units = root.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'number').length;
""")
    assert out["name"] == {"op": "set", "side": "front", "id": "e1", "changes": {"name": "Title"}}
    assert out["x"] == {"op": "set", "side": "front", "id": "e1", "changes": {"x": 30.5}}
    assert out["y"] == {"op": "set", "side": "front", "id": "e1", "changes": {"y": 12}}
    assert out["width"] == {"op": "resize", "side": "front", "id": "e1", "width": 40}
    assert out["rotation"] == {"op": "rotate", "side": "front", "id": "e1", "rotation": 15}
    assert out["afterResize"] == {"height": "10", "canvas": 40}                      # a text scales with its width: the server answered a letter height of 10
    assert out["text"]["changes"] == {"text": {"text": "Boris"}} and out["letter"]["changes"] == {"text": {"height_mm": 7}}
    assert out["spacing"]["changes"] == {"text": {"spacing_mm": 1.5}} and out["align"]["changes"] == {"text": {"align": "left"}}
    assert out["fontCall"] == {"sample": "Boris", "current": None}
    assert out["font"]["changes"] == {"text": {"font": {"face": "f1", "family": "Inter", "style": "Regular"}}} and out["fontShown"] is True
    assert out["layerAfter"] == ["Title"] and out["units"] >= 8


@node
def test_library_parameters_are_sliders_with_boxes_and_units_and_a_wrong_value_is_not_sent(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('Shape'); await press('Add Star'); await saved();
  const stroke = labelled('Line width');
  out.units = text(stroke.querySelectorAll('span').find((s) => s.classList.contains('f-unit')));
  out.range = [slider('Line width').getAttribute('min'), slider('Line width').getAttribute('max')];
  out.points = [slider('Points').getAttribute('step'), control('Points').getAttribute('step')];
  const s = slider('Line width'); s.value = '0.8'; await s.dispatch('input'); await s.dispatch('change'); await saved();
  out.slider = lastPost();
  out.box = control('Line width').value;
  const before = posts().length;
  await fill_('Line width', 9);
  await sleep(10);
  out.wrong = {posts: posts().length - before, note: text(labelled('Line width').querySelectorAll('span').find((x) => x.classList.contains('f-error'))), shown: control('Line width').value};
  await fill_('Points', 7); await saved();
  out.points7 = lastPost();
  await tick('Filled', true); await saved();
  out.filled = lastPost();
  out.kindFixed = !labelled('Shape');
""")
    assert out["units"] == "mm" and out["range"] == ["0.05", "3"]
    assert out["points"] == ["1", "1"]
    assert out["slider"] == {"op": "set", "side": "front", "id": "e1", "changes": {"shape": {"stroke_mm": 0.8}}} and out["box"] == "0.8"
    assert out["wrong"]["posts"] == 0 and "Allowed: from 0.05 to 3 mm" in out["wrong"]["note"] and out["wrong"]["shown"] == "9"
    assert out["points7"]["changes"] == {"shape": {"points": 7}} and out["filled"]["changes"] == {"shape": {"filled": True}}
    assert out["kindFixed"] is True


@node
def test_two_quick_edits_are_sent_in_order_and_the_last_answer_is_what_the_screen_shows(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('Text'); await saved();
  const name = control('Name'), x = control('Center X');
  const first = typeInto(name, 'First'), second = typeInto(x, 44);
  await Promise.all([first, second]);
  out.during = line();
  await saved();
  out.order = posts().slice(-2).map((b) => Object.keys(b.changes)[0]);
  out.shown = {name: control('Name').value, x: control('Center X').value, layer: layerNames()};
""")
    assert out["order"] == ["name", "x"] and out["shown"] == {"name": "First", "x": "44", "layer": ["First"]}
    assert out["during"].startswith("Card: Saving")


# -- the canvas -----------------------------------------------------------------------------------------------------------------------------------------
@node
def test_what_is_done_on_the_canvas_is_posted_and_the_canvas_is_shown_the_answer(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('Text'); await saved(); await press('QR code'); await saved(); await press('Shape'); await press('Add Rectangle'); await saved();
  const h = canvas().handlers, shows = canvas().shows.length;
  h.onSelect(['e1']);
  out.selectE1 = {title: rightTitle(), name: control('Name').value, posts: posts().length};
  h.onMove(['e1', 'e2'], 2.5, -1); await saved();
  out.move = lastPost();
  h.onResize('e3', {x: 10, y: 12, width: 24, height: 6}); await saved();
  out.resize = lastPost();
  h.onRotate('e3', 30); await saved();
  out.rotate = lastPost();
  h.onDuplicate(['e3']); await saved();
  out.duplicate = {body: lastPost(), selected: lastShow().selection, layers: layerNames()};
  h.onDelete(['e4']); await saved();
  out.delete = {body: lastPost(), layers: layerNames(), selection: lastShow().selection, title: rightTitle()};
  h.onSelect(['e2']); h.onEscape();
  out.escape = {title: rightTitle(), selection: canvas().selection};
  out.redrawn = canvas().shows.length > shows;
  out.after = lastShow().elements.map((e) => [e.id, e.x, e.y]);
""")
    assert out["selectE1"] == {"title": "Selected", "name": "Text 1", "posts": 3}
    assert out["move"] == {"op": "move", "side": "front", "ids": ["e1", "e2"], "dx": 2.5, "dy": -1}
    assert out["resize"] == {"op": "resize", "side": "front", "id": "e3", "x": 10, "y": 12, "width": 24, "height": 6}
    assert out["rotate"] == {"op": "rotate", "side": "front", "id": "e3", "rotation": 30}
    assert out["duplicate"] == {"body": {"op": "duplicate", "side": "front", "ids": ["e3"]}, "selected": ["e4"], "layers": ["Shape 1 copy", "Shape 1", "QR code 1", "Text 1"]}
    assert out["delete"] == {"body": {"op": "delete", "side": "front", "ids": ["e4"]}, "layers": ["Shape 1", "QR code 1", "Text 1"], "selection": [], "title": "Engraving"}
    assert out["escape"] == {"title": "Engraving", "selection": []} and out["redrawn"] is True
    assert out["after"] == [["e1", 45, 25.5], ["e2", 45, 25.5], ["e3", 10, 12]]


@node
def test_a_refused_canvas_gesture_is_shown_as_a_failed_save_and_the_canvas_is_drawn_from_the_card_as_stored(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('Text'); await saved();
  const before = canvas().shows.length;
  srv.refuse.push({when: (m, p, b) => b && b.op === 'move', status: 500, error: 'The disk is full'});
  canvas().handlers.onMove(['e1'], 5, 5);
  await until(() => /Not saved/.test(line()), 'the failure');
  out.state = line();
  out.alert = text(root.querySelector('.save-error'));
  out.redrawn = canvas().shows.length > before;
  out.retry = buttons().find((b) => b.textContent === 'Retry saving').hidden;
  out.restore = buttons().find((b) => b.textContent === 'Show saved values').hidden;
  out.stored = lastShow().elements[0].x;
""")
    assert out["state"].startswith("Card: Not saved") and "The disk is full" in out["alert"] and out["redrawn"] is True
    assert out["retry"] is True and out["restore"] is False and out["stored"] == 42.5       # a move cannot be repeated: only the stored card can be shown again


# -- layers, groups, engraving settings ---------------------------------------------------------------------------------------------------------------
@node
def test_layers_are_listed_top_first_and_reordered_grouped_and_given_settings(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('Text'); await saved(); await press('QR code'); await saved(); await press('Shape'); await press('Add Rectangle'); await saved();
  out.names = layerNames();
  await press('Move Text 1 forward'); await saved();
  out.up = {body: lastPost(), names: layerNames()};
  await press('Move Text 1 backward'); await saved();
  out.down = {body: lastPost(), names: layerNames()};
  out.edges = {topForward: button('Move Shape 1 forward').disabled, bottomBackward: button('Move Text 1 backward').disabled};
  await root.querySelectorAll('.cw-layer').find((b) => b.textContent.includes('QR code 1')).dispatch('click');
  out.clicked = {selected: canvas().selection, name: control('Name').value};
  canvas().handlers.onSelect(['e1', 'e2']);
  out.multi = {title: rightTitle(), heading: text(root.querySelector('.cw-inspector').querySelector('h4')), group: !!button('Group'), ungroup: !!button('Ungroup')};
  await press('To front'); await saved();
  out.order = lastPost();
  await press('Group'); await saved();
  out.group = lastPost();
  out.grouped = {ungroup: !!button('Ungroup'), groupDisabled: button('Group').disabled, layerPills: root.querySelectorAll('.pill').map((p) => p.textContent)};
  await press('Ungroup'); await saved();
  out.ungroup = lastPost();
  out.afterUngroup = root.querySelectorAll('.pill').map((p) => p.textContent);
  canvas().handlers.onEscape();
  await press('Add settings'); await saved();
  out.added = lastPost();
  canvas().handlers.onSelect(['e3']);
  out.options = control('Use another set of this card').options.map((o) => [o.value, o.textContent]);
  await choose('Use another set of this card', '2'); await saved();
  out.assign = lastPost();
  out.badge = root.querySelectorAll('.cw-layer-engraving').map((p) => text(p));              // the layers' own badges, not the state chip of the engraving block
  canvas().handlers.onSelect(['e1', 'e3']);
  const both = () => root.querySelector('.cw-inspector').querySelectorAll('select')[0];
  out.mixed = {value: both().value, options: both().options.map((o) => [o.value, o.disabled, o.textContent])};
  both().value = '1'; await both().dispatch('change'); await saved();
  out.assignMany = lastPost();
  out.after = {value: both().value, shown: srv.w.sides.front.elements.map((e) => [e.id, e.settings_id])};
""")
    assert out["names"] == ["Shape 1", "QR code 1", "Text 1"]
    assert out["up"] == {"body": {"side": "front", "op": "reorder", "id": "e1", "to": "forward"}, "names": ["Shape 1", "Text 1", "QR code 1"]}
    assert out["down"] == {"body": {"side": "front", "op": "reorder", "id": "e1", "to": "backward"}, "names": ["Shape 1", "QR code 1", "Text 1"]}
    assert out["edges"] == {"topForward": True, "bottomBackward": True}
    assert out["clicked"] == {"selected": ["e2"], "name": "QR code 1"}
    assert out["multi"] == {"title": "Selected", "heading": "2 elements selected", "group": True, "ungroup": False}
    assert out["order"] == {"side": "front", "op": "reorder", "ids": ["e1", "e2"], "to": "front"}
    assert out["group"] == {"side": "front", "op": "group", "ids": ["e1", "e2"]}
    assert out["grouped"]["ungroup"] is True and out["grouped"]["groupDisabled"] is True and out["grouped"]["layerPills"].count("Group of 2") == 2
    assert out["ungroup"] == {"side": "front", "op": "ungroup", "ids": ["e1", "e2"]} and "Group of 2" not in out["afterUngroup"]
    assert out["added"] == {"op": "settings_add"}
    assert out["options"] == [["", "Default (Engraving 1)"], ["1", "Engraving 1"], ["2", "Engraving 2"]]
    assert out["assign"] == {"side": "front", "op": "assign_settings", "ids": ["e3"], "settings_id": 2} and out["badge"] == ["Engraving 2"]
    assert out["mixed"] == {"value": "__mixed", "options": [["__mixed", True, "Mixed: choose to set all"], ["", False, "Default (Engraving 1)"], ["1", False, "Engraving 1"], ["2", False, "Engraving 2"]]}
    assert out["assignMany"] == {"side": "front", "op": "assign_settings", "ids": ["e3", "e1"], "settings_id": 1}   # in the order of the layers
    assert out["after"] == {"value": "1", "shown": [["e3", 1], ["e1", 1], ["e2", None]]}


@node
def test_a_layer_row_has_a_delete_button_beside_the_move_buttons(tmp_path):
    """ui-studio-3 REQ-001/002: every row of the layer list can delete its own layer, in the same row as up and down, and a deleted layer is gone."""
    out = run(tmp_path, """
  await open();
  await press('Text'); await saved(); await press('QR code'); await saved(); await press('Shape'); await press('Add Rectangle'); await saved();
  const row = root.querySelectorAll('.lst-row').find((r) => r.textContent.includes('QR code 1'));
  out.actions = row.querySelectorAll('button').filter((b) => !b.classList.contains('cw-layer')).map((b) => b.getAttribute('aria-label'));
  out.before = layerNames();
  await press('Delete QR code 1'); await saved();
  out.post = lastPost();
  out.after = layerNames();
  out.gone = srv.w.sides.front.elements.map((e) => e.id);
""")
    assert out["actions"] == ["Move QR code 1 forward", "Move QR code 1 backward", "Delete QR code 1"]
    assert out["before"] == ["Shape 1", "QR code 1", "Text 1"]
    assert out["post"] == {"side": "front", "op": "delete", "ids": ["e2"]}
    assert out["after"] == ["Shape 1", "Text 1"] and out["gone"] == ["e1", "e3"]


@node
def test_the_engraving_panel_edits_each_set_and_says_what_uses_it(tmp_path):
    out = run(tmp_path, """
  await open();
  out.empty = {title: rightTitle(), sets: text(root.querySelector('.cw-engraving').querySelector('h4'))};
  await press('Text'); await saved(); await press('Shape'); await press('Add Rectangle'); await saved();
  canvas().handlers.onEscape();
  const set = root.querySelector('.cw-set');
  out.open = set.open;
  out.summary = text(set.querySelector('summary'));
  out.used = text(root.querySelectorAll('p').find((p) => (p.textContent || '').startsWith('Used by')));
  await fill_('Name', 'Fine text', set); await saved();
  out.name = lastPost();
  out.beforeCustom = set.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'number').length;
  await openCustom(set);
  const line_ = control('Line interval', set).closest('label');
  const mode = set.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'radio');
  out.modes = mode.map((i) => [i.getAttribute('aria-label'), i.checked]);
  await fill_('Power', 35, set); await saved();
  out.power = lastPost();
  await fill_('Speed', 800, set); await saved(); await fill_('Frequency', 40, set); await saved();
  await fill_('Line interval', 0.03, set); await saved();
  await fill_('Pulse width (optional)', 200, set); await saved();
  out.pulse = lastPost();
  await fill_('Pulse width (optional)', '', set); await saved();
  out.pulseCleared = lastPost();
  await fill_('Passes', 2, set); await saved();
  out.passes = lastPost();
  const before = posts().length;
  await fill_('Power', 150, set); await sleep(10);
  out.bad = {posts: posts().length - before, note: errorOf('Power', set)};
  await fill_('Power', 35, set); await saved();
  mode[1].checked = true; await mode[1].dispatch('change'); await saved();
  out.line = {body: lastPost(), hidden: line_.hidden};
  out.units = ['Power', 'Speed', 'Frequency', 'Pulse width (optional)', 'Line interval', 'Passes'].map((l) => text(labelled(l, set).querySelectorAll('span').find((s) => s.classList.contains('f-unit')) || {textContent: 'unitless'}));
  out.deleteDisabled = button('Delete settings').disabled;
  out.origin = {chip: text(set.querySelector('.cw-chip')), line: text(set.querySelector('.cw-origin'))};
""")
    assert out["empty"] == {"title": "Engraving", "sets": "Engraving settings (1)"}
    assert out["open"] is True and "Engraving 1" in out["summary"] and "default" in out["summary"]
    assert out["beforeCustom"] == 0                                                              # no number box until "Custom values" is opened
    assert out["origin"] == {"chip": "Typed by hand, the last resort.", "line": "Typed by hand"}   # the numbers typed above made the set the operator's own
    assert out["used"] == "Used by: Text 1, Shape 1."
    assert out["name"] == {"op": "settings_set", "id": 1, "changes": {"name": "Fine text"}}
    assert out["modes"] == [["Fill", True], ["Line", False]]
    assert out["power"] == {"op": "settings_set", "id": 1, "changes": {"power": 35}}
    assert out["pulse"]["changes"] == {"pulse_width": 200} and out["pulseCleared"]["changes"] == {"pulse_width": None} and out["passes"]["changes"] == {"passes": 2}
    assert out["bad"]["posts"] == 0 and "Allowed: greater than 0 and at most 100 %" in out["bad"]["note"]
    assert out["line"]["body"]["changes"] == {"mode": "line"} and out["line"]["hidden"] is True
    assert out["units"] == ["%", "mm/s", "kHz", "ns", "mm", "unitless"] and out["deleteDisabled"] is True


@node
def test_a_set_of_engraving_settings_is_added_and_deleted_after_a_confirmation(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('Add settings'); await saved();
  out.add = lastPost();
  const sets = root.querySelectorAll('.cw-set');
  out.sets = sets.map((s) => [text(s.querySelector('summary')).split(' ')[0], s.open]);
  await press('Delete settings', sets[1]);
  out.confirm = text(dialog().querySelector('p'));
  await press('Cancel', dialog());
  out.noPost = posts().length;
  await press('Delete settings', sets[1]);
  await press('Delete', dialog()); await saved();
  out.delete = lastPost();
  out.left = root.querySelectorAll('.cw-set').length;
""")
    assert out["add"] == {"op": "settings_add"}
    assert out["sets"] == [["Engraving", True], ["Engraving", True]]
    assert "Elements that use them fall back to the default settings" in out["confirm"] and out["noPost"] == 1
    assert out["delete"] == {"op": "settings_delete", "id": 2} and out["left"] == 1


# -- the review and the files ---------------------------------------------------------------------------------------------------------------------------
@node
def test_a_side_is_exported_only_when_its_review_is_ready_and_the_review_names_what_is_missing(tmp_path):
    out = run(tmp_path, """
  await open();
  const exportButtons = () => ({front: button('Export front'), back: button('Export back')});
  out.empty = {front: exportButtons().front.disabled, back: exportButtons().back.disabled, title: exportButtons().front.getAttribute('title'),
    review: root.querySelectorAll('.cw-review-side').map((s) => text(s.querySelector('.pill')))};
  await press('Text'); await saved();
  canvas().handlers.onEscape();
  const front = root.querySelector('.cw-review-side');
  out.problems = {list: text(front.querySelector('ul')), attention: text(front.querySelectorAll('li').slice(-1)[0]), disabled: exportButtons().front.disabled,
    title: exportButtons().front.getAttribute('title')};
  await press('Select', front);
  out.selected = {title: rightTitle(), ids: canvas().selection};
  canvas().handlers.onEscape();
  const set = root.querySelector('.cw-set');
  out.missing = text(set.querySelector('summary'));
  await openCustom(set);
  await fill_('Power', 30, set); await saved(); await fill_('Speed', 900, set); await saved(); await fill_('Frequency', 30, set); await saved();
  out.stillNot = exportButtons().front.disabled;
  await fill_('Line interval', 0.05, set); await saved();
  out.ready = {disabled: exportButtons().front.disabled, back: exportButtons().back.disabled, pill: text(root.querySelector('.cw-review-side').querySelector('.pill')), title: exportButtons().front.getAttribute('title')};
  await exportButtons().front.dispatch('click');
  await until(() => downloads.length > 0, 'the download');
  out.download = {names: downloads, url: log.filter((x) => x.path.endsWith('export.lbrn2')).map((x) => x.path)};
  await press('Back');
  out.back = {disabled: exportButtons().back.disabled, problems: text(root.querySelectorAll('.cw-review-side')[1].querySelector('ul'))};
""")
    assert out["empty"]["front"] is True and out["empty"]["back"] is True and "There is nothing to engrave on the front" in out["empty"]["title"]
    assert out["empty"]["review"] == ["not ready", "not ready"]
    assert "still need settings chosen for this laser, lens and material" in out["problems"]["list"] and out["problems"]["disabled"] is True
    assert out["problems"]["attention"].startswith("Text 1 (Text): its engraving settings still need settings chosen for this laser, lens and material")
    assert out["selected"] == {"title": "Selected", "ids": ["e1"]}
    assert "Needs: settings chosen for this laser, lens and material" in out["missing"] and "No settings are chosen yet." in out["missing"]
    assert out["stillNot"] is True
    assert out["ready"]["disabled"] is False and out["ready"]["back"] is True and out["ready"]["pill"] == "ready to export" and "Download the LightBurn file" in out["ready"]["title"]
    assert out["download"] == {"names": ["card-front.lbrn2"], "url": ["/api/card-works/7/sides/front/export.lbrn2"]}
    assert out["back"]["disabled"] is True and "There is nothing to engrave on the back" in out["back"]["problems"]


# -- the QR code -----------------------------------------------------------------------------------------------------------------------------------------
@node
def test_the_qr_form_shows_the_checks_and_the_warnings_and_never_blocks(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('QR code'); await saved();
  const box = () => root.querySelector('.cw-suit');
  out.alone = {sentence: text(box().querySelector('.cw-no-guarantee')), warnings: box().querySelectorAll('.cw-warning').length, facts: box().querySelectorAll('dd').map((d) => d.textContent)};
  out.kinds = control('Content type').options.map((o) => o.textContent);
  out.ecc = control('Error correction').options.map((o) => o.value);
  await press('Text'); await saved();
  canvas().handlers.onSelect(['e1']);
  out.crowded = {warnings: box().querySelectorAll('.cw-warning').map((w) => w.textContent), sentence: text(box().querySelector('.cw-no-guarantee'))};
  await fill_('Width', 8); await saved();
  out.small = {warnings: box().querySelectorAll('.cw-warning').map((w) => w.textContent), facts: box().querySelectorAll('dd').map((d) => d.textContent), sentences: root.querySelectorAll('.cw-no-guarantee').length,
    resize: lastPost()};
  await fill_('Web address', 'https://titanium.example/card'); await saved();
  out.url = lastPost();
  await choose('Error correction', 'Q'); await saved();
  out.ecc = lastPost();
  await choose('Content type', 'wifi'); await saved();
  out.kind = {body: lastPost(), fields: labelled('Network name (SSID)') != null, passwordType: control('Password').getAttribute('type'), security: control('Security').options.map((o) => o.textContent)};
  await fill_('Network name (SSID)', 'Cafe'); await saved();
  out.ssid = lastPost();
  await tick('Hidden network', true); await saved();
  out.hidden = lastPost();
  out.exportBlocked = button('Export front').disabled;
""")
    assert out["alone"]["sentence"] == "Passing the checks does not guarantee that the engraved code will scan."
    assert out["alone"]["warnings"] == 0 and out["alone"]["facts"][0] == "25 modules across" and out["alone"]["facts"][1].startswith("0.72 mm (at least 0.40 mm)")
    assert out["kinds"][:4] == ["Link", "Contact card (vCard)", "Text", "Wi-Fi network"]
    assert out["crowded"]["warnings"] == ["The quiet zone is 1.5 modules, below the 4 modules a scanner needs."]
    assert out["crowded"]["sentence"] == "Passing the checks does not guarantee that the engraved code will scan."
    assert out["small"]["warnings"][0].startswith("The modules are 0.32 mm wide, below the 0.40 mm") and len(out["small"]["warnings"]) == 2
    assert out["small"]["resize"] == {"op": "resize", "side": "front", "id": "e1", "width": 8, "height": 8} and out["small"]["sentences"] == 1
    assert out["url"]["changes"] == {"qr": {"fields": {"url": "https://titanium.example/card"}}}
    assert out["ecc"]["changes"] == {"qr": {"ecc": "Q"}}
    assert out["kind"]["body"]["changes"] == {"qr": {"kind": "wifi", "fields": {}}} and out["kind"]["passwordType"] == "password" and out["kind"]["security"] == ["WPA", "WEP", "No password"]
    assert out["ssid"]["changes"] == {"qr": {"fields": {"ssid": "Cafe", "password": "", "security": "WPA", "hidden": False}}}
    assert out["hidden"]["changes"] == {"qr": {"fields": {"ssid": "Cafe", "password": "", "security": "WPA", "hidden": True}}}


# -- pictures ---------------------------------------------------------------------------------------------------------------------------------------------
@node
def test_an_imported_picture_is_posted_with_its_side_and_its_tracing_is_adjusted_with_the_image_controls(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('Image');
  const input = root.querySelectorAll('input').find((i) => i.getAttribute('type') === 'file');
  out.accept = input.getAttribute('accept');
  input.files = [new File(['png'], 'logo.png', {type: 'image/png'})];
  await input.dispatch('change');
  await saved();
  out.post = lastPost('/images');
  out.selected = {title: rightTitle(), layers: layerNames(), info: text(root.querySelector('.cw-form').querySelector('p'))};
  const visible = (label) => { const l = labelled(label); return !!l && !l.hidden; };
  out.initial = {treatment: control('Treatment').options.map((o) => [o.value, o.textContent]), detail: visible('Detail'), strength: visible('Pencil strength'), threshold: control('Grey level').disabled};
  await choose('Treatment', 'pencil'); await saved();
  out.pencil = {body: lastPost(), detail: visible('Detail'), strength: visible('Pencil strength')};
  await fill_('Detail', 70); await saved();
  out.detail = lastPost();
  await fill_('Pencil strength', 30); await saved();
  out.strength = lastPost();
  await tick('Find the grey level automatically', false); await saved();
  out.auto = {body: lastPost(), threshold: control('Grey level').disabled};
  await fill_('Grey level', 90); await saved();
  out.threshold = lastPost();
  await tick('Invert (engrave the light parts)', true); await saved();
  out.invert = lastPost();
  await fill_('Smallest feature', 0.3); await saved();
  out.feature = lastPost();
  const unit = (l) => text(labelled(l).querySelectorAll('span').find((s) => s.classList.contains('f-unit')));
  out.units = [unit('Detail'), unit('Grey level'), unit('Smallest feature')];
""")
    assert "image/png" in out["accept"] and out["post"] == {"side": "front", "picture": "logo.png"}
    assert out["selected"]["title"] == "Selected" and out["selected"]["layers"] == ["logo"] and "200 × 100 px" in out["selected"]["info"] and "imported graphic" in out["selected"]["info"]
    assert out["initial"] == {"treatment": [["none", "As drawn"], ["pencil", "Pencil drawing"]], "detail": False, "strength": False, "threshold": True}
    assert out["pencil"]["body"]["changes"] == {"image": {"treatment": "pencil"}} and out["pencil"]["detail"] is True and out["pencil"]["strength"] is True
    assert out["detail"]["changes"] == {"image": {"detail": 70}} and out["strength"]["changes"] == {"image": {"strength": 30}}
    assert out["auto"]["body"]["changes"] == {"image": {"auto_threshold": False}} and out["auto"]["threshold"] is False
    assert out["threshold"]["changes"] == {"image": {"threshold": 90}} and out["invert"]["changes"] == {"image": {"invert": True}}
    assert out["feature"]["changes"] == {"image": {"min_feature_mm": 0.3}} and out["units"] == ["%", "grey level", "mm"]


@node
def test_a_refused_picture_is_told_beside_the_form_and_does_not_make_the_card_unsaved(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('Image');
  srv.refuse.push({when: (m, p) => p.endsWith('/images'), error: 'the file is not a picture that can be traced'});
  const input = root.querySelectorAll('input').find((i) => i.getAttribute('type') === 'file');
  input.files = [new File(['x'], 'notes.txt', {type: 'text/plain'})];
  await input.dispatch('change');
  await until(() => root.querySelectorAll('p').some((p) => (p.textContent || '').includes('not a picture')), 'the refusal');
  out.shown = text(root.querySelectorAll('p').find((p) => (p.textContent || '').includes('not a picture')));
  await saved();
  out.state = line(); out.alerts = root.querySelector('.save-error').hidden; out.layers = layerNames();
""")
    assert "the file is not a picture that can be traced" in out["shown"] and out["state"].startswith("Card: Saved") and out["alerts"] is True and out["layers"] == []


@node
def test_generation_is_disabled_with_its_reason_when_unavailable(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('Generate');
  const go = button('Generate', root.querySelector('.cw-stage'));
  out.state = {disabled: go.disabled, reason: text(root.querySelector('.cw-stage').querySelector('.alert')), hidden: root.querySelector('.cw-stage').querySelector('.alert').hidden};
  await go.dispatch('click');
  out.posts = log.filter((x) => x.path.endsWith('/generate')).length;
""")
    assert out["state"]["disabled"] is True and out["state"]["hidden"] is False and "No OpenAI key is set" in out["state"]["reason"] and out["posts"] == 0


@node
def test_generation_posts_the_description_and_the_kind_when_available_and_tells_a_refusal_beside_the_form(tmp_path):
    out = run(tmp_path, """
  srv.generation = {available: true, reason: null};
  await open();
  await press('Generate');
  const stage = root.querySelector('.cw-stage');
  out.enabled = {disabled: button('Generate', stage).disabled, reason: stage.querySelector('.alert').hidden};
  await press('Generate', stage);
  out.short = {error: errorOf('Describe the picture', stage), posts: log.filter((x) => x.path.endsWith('/generate')).length};
  await fill_('Describe the picture', 'a small anchor', stage);
  const drawing = stage.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'Drawing');
  drawing.checked = true; await drawing.dispatch('change');
  srv.refuse.push({when: (m, p) => p.endsWith('/generate'), error: 'The image service refused this description: describe the picture differently.'});
  await press('Generate', stage);
  await until(() => stage.querySelectorAll('p').some((p) => (p.textContent || '').includes('refused this description')), 'the refusal');
  out.refused = {state: line(), described: control('Describe the picture', stage).value};
  await press('Generate', stage);
  await saved();
  out.post = lastPost('/generate');
  out.after = {selected: canvas().selection, title: rightTitle(), layers: layerNames(), cleared: control('Describe the picture', root.querySelector('.cw-stage')).value};
""")
    assert out["enabled"] == {"disabled": False, "reason": True}
    assert out["short"]["error"].startswith("Describe the picture in 3 to 300 characters") and out["short"]["posts"] == 0
    assert out["refused"]["state"].startswith("Card: Saved") and out["refused"]["described"] == "a small anchor"
    assert out["post"] == {"side": "front", "description": "a small anchor", "kind": "drawing"}
    assert out["after"]["title"] == "Selected" and len(out["after"]["layers"]) == 1 and out["after"]["cleared"] == ""


# -- undo, redo, a failed save ------------------------------------------------------------------------------------------------------------------------------
@node
def test_undo_and_redo_by_button_and_by_keys(tmp_path):
    out = run(tmp_path, """
  await open();
  out.start = [button('Undo').disabled, button('Redo').disabled];
  await press('Text'); await saved();
  out.titles = [button('Undo').getAttribute('title'), button('Redo').getAttribute('title')];
  out.afterAdd = [button('Undo').disabled, button('Redo').disabled, layerNames()];
  await press('Undo'); await saved();
  out.undone = {post: posts('/undo').length, layers: layerNames(), redo: button('Redo').disabled, title: rightTitle()};
  await press('Redo'); await saved();
  out.redone = {post: posts('/redo').length, layers: layerNames()};
  await doc.dispatch('keydown', {key: 'z', ctrlKey: true}); await saved();
  out.keyUndo = {posts: posts('/undo').length, layers: layerNames()};
  await doc.dispatch('keydown', {key: 'Z', ctrlKey: true, shiftKey: true}); await saved();
  out.keyRedo = {posts: posts('/redo').length, layers: layerNames()};
  const input = control('Name');
  await doc.dispatch('keydown', {key: 'z', ctrlKey: true, target: input});
  await doc.dispatch('keydown', {key: 'z', ctrlKey: true, target: canvas().host});
  await sleep(10);
  out.ignored = posts('/undo').length;
  canvas().handlers.onUndo(); await saved();
  out.canvasUndo = posts('/undo').length;
""")
    assert out["start"] == [True, True] and out["titles"] == ["Undo (Ctrl+Z)", "Redo (Ctrl+Shift+Z)"]
    assert out["afterAdd"] == [False, True, ["Text 1"]]
    assert out["undone"] == {"post": 1, "layers": [], "redo": False, "title": "Engraving"}
    assert out["redone"] == {"post": 1, "layers": ["Text 1"]}
    assert out["keyUndo"] == {"posts": 2, "layers": []} and out["keyRedo"] == {"posts": 2, "layers": ["Text 1"]}
    assert out["ignored"] == 2 and out["canvasUndo"] == 3


@node
def test_a_failed_edit_stays_in_its_box_with_the_error_and_a_retry_that_saves_it(tmp_path):
    out = run(tmp_path, """
  await open();
  await press('Text'); await saved();
  srv.refuse.push({when: (m, p, b) => b && b.op === 'set', status: 500, error: 'The disk is full'});
  await fill_('Name', 'Renamed');
  await until(() => /Not saved/.test(line()), 'the failure');
  out.failed = {line: line(), alert: text(root.querySelector('.save-error')), box: control('Name').value, layer: layerNames(), retry: !buttons().find((b) => b.textContent === 'Retry saving').hidden};
  await press('Retry saving');
  await saved();
  out.retried = {line: line(), box: control('Name').value, layer: layerNames(), posts: posts().filter((b) => b.op === 'set').length};
""")
    assert out["failed"]["line"].startswith("Card: Not saved") and "The disk is full" in out["failed"]["alert"]
    assert out["failed"]["box"] == "Renamed" and out["failed"]["layer"] == ["Text 1"] and out["failed"]["retry"] is True
    assert out["retried"] == {"line": out["retried"]["line"], "box": "Renamed", "layer": ["Renamed"], "posts": 2} and out["retried"]["line"].startswith("Card: Saved")


# -- the layout rules -----------------------------------------------------------------------------------------------------------------------------------------
@node
def test_every_control_has_a_name_every_number_a_unit_and_a_long_list_is_paged(tmp_path):
    out = run(tmp_path, """
  srv.seed('front', 'text', 30);
  await open();
  const named = (el) => {
    if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.getAttribute('title')) return true;
    if (el.localName === 'button') return (el.textContent || '').trim().length > 0;
    for (let n = el.parentNode; n; n = n.parentNode) if (n.localName === 'label' && (n.textContent || '').trim()) return true;
    return false;
  };
  const audit = () => root.querySelectorAll('button, input, select, textarea').filter((el) => !named(el)).map((el) => el.localName + ' ' + el.className);
  out.rows = {shown: root.querySelectorAll('.cw-layer-name').length, count: text(root.querySelector('.lst-count'))};
  const kinds = ['Text', 'QR code'];
  await press('Shape'); await press('Add Star'); await saved();
  await press('Image');
  await press('Generate');
  out.unnamed = [audit()];
  for (const id of ['e31', 'e32']) { canvas().handlers.onSelect([id]); out.unnamed.push(audit()); }
  await press('QR code'); await saved();
  out.unnamed.push(audit());
  canvas().handlers.onEscape();
  out.unnamed.push(audit());
  await openCustom();
  out.unnamed.push(audit());
  const numbers = root.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'number' && !i.hidden);
  const hasUnit = (i) => { for (let n = i.parentNode; n; n = n.parentNode) if (n.localName === 'label') return n.querySelectorAll('span').some((s) => s.classList.contains('f-unit') || s.classList.contains('sr-only')); return false; };
  out.numbers = {total: numbers.length, withoutUnit: numbers.filter((i) => !hasUnit(i)).length};
""")
    assert out["rows"] == {"shown": 12, "count": "showing 12 of 30"}
    assert all(group == [] for group in out["unnamed"]), out["unnamed"]
    assert out["numbers"]["total"] > 0 and out["numbers"]["withoutUnit"] == 0


# -- the works list ---------------------------------------------------------------------------------------------------------------------------------------------
WORKS = """
  srv.catalog = () => ({items: [{key: 'card-7', id: 7, kind: 'card', type: 'card', name: 'Visit card', width_mm: 85, height_mm: 53, state: 'prepared', created_at: '2026-11-05T10:00:00', updated_at: '2026-11-05T10:00:00',
      checks: 0, zones: 0, texts: 0, laser: {id: 1, name: 'Laser'}, lens: null, material: null, missing: [], broken: false, thumb: '/api/card-works/7/thumb.svg?v=1', open: '/card-work?work=7', base: '/card-works'}],
    total: 1, counts: {type: {'': 1, card: 1}, laser: {'': 1}, lens: {'': 1}, material: {'': 1}}, facets: {type: ['vector', 'mixed', 'photo', 'card'], laser: [{value: '1', name: 'Laser'}], lens: [], material: []}, all: 1});
  const s = Works.build({});
  main.replaceChildren(s.el);
  await s.ready();
"""


@node
def test_the_works_list_shows_a_card_entry_and_a_cards_chip_and_the_card_menu_item(tmp_path):
    out = run(tmp_path, WORKS + """
  const row = s.el.querySelectorAll('.lst-row')[0];
  out.row = {name: text(row.querySelector('.works-name')), href: row.querySelector('.works-name').getAttribute('href'), pills: row.querySelectorAll('.pill').map((p) => p.textContent),
    size: text(row.querySelector('.works-size')), img: row.querySelector('img').getAttribute('src')};
  out.chips = s.el.querySelectorAll('.lst-chip').map((c) => c.textContent);
  const create = s.el.querySelectorAll('button').find((b) => b.textContent === 'New work ▾');
  await create.dispatch('click');
  const menu = s.el.querySelectorAll('.works-menu').find((m) => m.getAttribute('aria-label') === 'New work');
  out.items = menu.querySelectorAll('.works-menu-item').map((b) => b.textContent);
  await menu.querySelectorAll('.works-menu-item').find((b) => b.textContent.startsWith('Business card')).dispatch('click');
  out.dialog = {title: text(dialog().querySelector('h3')), radios: dialog().querySelectorAll('input').filter((i) => i.getAttribute('type') === 'radio').map((i) => [i.getAttribute('aria-label'), i.checked]),
    name: dialog().querySelectorAll('input')[0].value};
""")
    assert out["row"] == {"name": "Visit card", "href": "#/card-work?work=7", "pills": ["Business card", "Prepared"], "size": "85.0 × 53.0 mm", "img": "/api/card-works/7/thumb.svg?v=1"}
    assert "Cards · 1" in out["chips"]
    assert out["items"][-1].startswith("Business card") and out["items"][0].startswith("Vector work")
    assert out["dialog"]["title"] == "New business card" and out["dialog"]["name"] == "Business card"
    assert out["dialog"]["radios"] == [["85 × 53 mm", True], ["85 × 54 mm", False], ["Custom size", False]]


@node
def test_the_new_card_dialog_validates_beside_its_fields_creates_the_card_and_opens_the_editor(tmp_path):
    out = run(tmp_path, WORKS + """
  Works.startCreation('card');
  const box = dialog();
  const name = box.querySelectorAll('input')[0];
  await typeInto(name, '   ');
  await press('Create card', box);
  out.blank = {error: errorOf('Name', box), posts: posts('/card-works').length, form: text(box.querySelector('.f-form-error'))};
  await typeInto(name, 'Bank card');
  const radios = box.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'radio');
  radios[2].checked = true; await radios[2].dispatch('change');
  await fill_('Width', 5, box); await fill_('Height', 400, box);
  await press('Create card', box);
  out.custom = {width: errorOf('Width', box), height: errorOf('Height', box), posts: posts('/card-works').length, open: !!dialog()};
  await fill_('Width', 86, box); await fill_('Height', 54, box);
  await press('Create card', box);
  await until(() => ctx.__went.length > 0, 'the editor');
  out.created = {body: posts('/card-works').slice(-1)[0], went: [...ctx.__went], closed: !dialog()};
  Works.startCreation('card');
  const again = dialog();
  radios2 = again.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'radio');
  radios2[1].checked = true; await radios2[1].dispatch('change');
  await press('Create card', again);
  await until(() => ctx.__went.length > 1, 'the second editor');
  out.preset = {body: posts('/card-works').slice(-1)[0], went: ctx.__went[1]};
  Works.startCreation('card');
  srv.refuse.push({when: (m, p) => p === '/api/card-works' && m === 'POST', error: 'add the laser first: a card is engraved with a laser of the workshop'});
  await press('Create card', dialog());
  await until(() => dialog() && dialog().querySelector('.f-form-error') && !dialog().querySelector('.f-form-error').hidden, 'the refusal');
  out.refused = {form: text(dialog().querySelector('.f-form-error')), open: !!dialog()};
""".replace("radios2 =", "const radios2 ="))
    assert out["blank"]["error"] == "Enter a card name" and out["blank"]["posts"] == 0
    assert out["custom"]["width"].startswith("Allowed: from 10 to 300 mm") and out["custom"]["height"].startswith("Allowed: from 10 to 300 mm")
    assert out["custom"]["posts"] == 0 and out["custom"]["open"] is True
    assert out["created"] == {"body": {"name": "Bank card", "preset": "custom", "width_mm": 86, "height_mm": 54}, "went": ["/card-work?work=8"], "closed": True}
    assert out["preset"] == {"body": {"name": "Business card", "preset": "85x54"}, "went": "/card-work?work=8"}
    assert "add the laser first" in out["refused"]["form"] and out["refused"]["open"] is True


@node
def test_deleting_renaming_and_copying_a_card_from_the_list_use_the_card_routes_and_words(tmp_path):
    out = run(tmp_path, WORKS + """
  const row = s.el.querySelectorAll('.lst-row')[0];
  const menu = row.querySelector('.works-menu-btn');
  await menu.dispatch('click');
  await row.querySelectorAll('.works-menu-item').find((b) => b.textContent === 'Make a copy').dispatch('click');
  await sleep(10);
  out.copy = log.filter((x) => x.method === 'POST' && x.path.endsWith('/copy')).map((x) => x.path);
  await menu.dispatch('click');
  await row.querySelectorAll('.works-menu-item').find((b) => b.textContent === 'Rename…').dispatch('click');
  const input = dialog().querySelectorAll('input')[0];
  await typeInto(input, 'Renamed card');
  await press('Save', dialog());
  await sleep(10);
  out.rename = log.filter((x) => x.method === 'POST' && x.path.endsWith('/rename')).map((x) => [x.path, x.body]);
  await menu.dispatch('click');
  await row.querySelectorAll('.works-menu-item').find((b) => b.textContent === 'Delete…').dispatch('click');
  out.confirm = {title: text(dialog().querySelector('h3')), text: text(dialog().querySelector('p'))};
""")
    assert out["copy"] == ["/api/card-works/7/copy"] and out["rename"] == [["/api/card-works/7/rename", {"name": "Renamed card"}]]
    assert out["confirm"] == {"title": "Delete work “Visit card”?", "text": "The card, both sides, is deleted; exported files stay with you."}
