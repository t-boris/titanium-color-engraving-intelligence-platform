/* A small DOM for running UI screens in node (tests only): elements with attributes, children, events that bubble,
   simple selectors (tag, .class, [attr], comma lists), an SVG/XML parser for the server's own SVG, fetch answered from a
   table of routes. Enough for the screens' own code; not a browser. */
'use strict';
const fs = require('fs'), vm = require('vm');

class Text_ {
  constructor(data) { this.nodeType = 3; this.data = String(data); this.parentNode = null; }
  get textContent() { return this.data; }
  cloneNode() { return new Text_(this.data); }
  remove() { if (this.parentNode) this.parentNode._detach(this); }
}

const SIMPLE = /^([a-zA-Z][\w-]*)?((?:\.[\w-]+)*)(?:\[([\w-]+)\])?$/;

class El {
  constructor(tag) {
    this.nodeType = 1; this.localName = tag; this.tagName = tag.toUpperCase(); this.attrs = new Map(); this.childNodes = [];
    this.parentNode = null; this.listeners = {}; this._value = ''; this.checked = false; this.disabled = false; this.hidden = false; this.selected = false;
  }
  /** A select's value is its selected option's (the first when none is), as in a browser. */
  get value() {
    if (this.localName !== 'select') return this._value;
    const option = this.options.find((o) => o.selected) || this.options[0];
    return option ? option.value : '';
  }
  set value(v) {
    if (this.localName === 'select') for (const o of this.options) o.selected = String(o.value) === String(v);
    else this._value = String(v);
  }
  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  removeAttribute(k) { this.attrs.delete(k); }
  hasAttribute(k) { return this.attrs.has(k); }
  get className() { return this.getAttribute('class') || ''; }
  set className(v) { this.setAttribute('class', v); }
  get classList() {
    const list = () => this.className.split(/\s+/).filter(Boolean);
    return {add: (c) => { if (!list().includes(c)) this.className = [...list(), c].join(' '); },
      remove: (c) => { this.className = list().filter((x) => x !== c).join(' '); }, contains: (c) => list().includes(c),
      toggle: (c, force) => { const on = force === undefined ? !list().includes(c) : !!force; this.classList[on ? 'add' : 'remove'](c); return on; }};
  }
  _adopt(kid) {
    const node = kid && kid.nodeType ? kid : new Text_(kid);
    if (node.parentNode) node.parentNode._detach(node);
    node.parentNode = this;
    return node;
  }
  append(...kids) { for (const k of kids) this.childNodes.push(this._adopt(k)); }
  prepend(...kids) { this.childNodes.unshift(...kids.map((k) => this._adopt(k))); }
  _detach(node) { this.childNodes = this.childNodes.filter((x) => x !== node); node.parentNode = null; }
  remove() { if (this.parentNode) this.parentNode._detach(this); }
  replaceChildren(...kids) { for (const c of [...this.childNodes]) this._detach(c); this.append(...kids); }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  get options() { return this.children.filter((c) => c.localName === 'option'); }
  get textContent() { return this.childNodes.map((n) => n.textContent).join(''); }
  set textContent(v) { this.replaceChildren(String(v)); }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  removeEventListener() {}
  /** Fire an event that bubbles; the promises of async handlers are returned so a test can wait for them. */
  dispatch(type, extra = {}) {
    const ev = {type, target: this, preventDefault() {}, stopPropagation() {}, pointerId: 1, ...extra};
    const done = [];
    for (let el = this; el; el = el.parentNode) for (const fn of el.listeners[type] || []) { ev.currentTarget = el; done.push(fn(ev)); }
    return Promise.all(done);
  }
  matches(selector) {
    return selector.split(',').map((s) => s.trim()).some((s) => {
      const m = s.match(SIMPLE);
      if (!m) throw new Error('selector not supported: ' + s);
      const [, tag, classes, attr] = m;
      return (!tag || this.localName === tag) && classes.split('.').filter(Boolean).every((c) => this.classList.contains(c))
        && (!attr || this.hasAttribute(attr)) && Boolean(tag || classes || attr);
    });
  }
  closest(selector) { for (let el = this; el && el.nodeType === 1; el = el.parentNode) if (el.matches(selector)) return el; return null; }
  querySelectorAll(selector) {
    const out = [];
    const walk = (n) => { for (const c of n.childNodes) if (c.nodeType === 1) { if (c.matches(selector)) out.push(c); walk(c); } };
    walk(this);
    return out;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  cloneNode(deep) {
    const c = new El(this.localName);
    for (const [k, v] of this.attrs) c.attrs.set(k, v);
    for (const p of ['value', 'checked', 'disabled', 'hidden']) c[p] = this[p];
    if (deep) for (const k of this.childNodes) c.append(k.cloneNode(true));
    return c;
  }
  focus() {}
  setPointerCapture() {}
  getBoundingClientRect() { return {left: 0, top: 0, width: 100, height: 100}; }
}

const ENTITIES = {'&quot;': '"', '&apos;': "'", '&lt;': '<', '&gt;': '>', '&amp;': '&'};
const unescape = (s) => s.replace(/&(quot|apos|lt|gt|amp);/g, (e) => ENTITIES[e]);

/** XML of the server's own SVG (elements, attributes in either quotes, no text content needed). */
function parseXml(text) {
  const root = new El('#document');
  let at = root;
  for (const m of text.matchAll(/<(\/?)([\w:-]+)((?:\s+[\w:-]+=(?:"[^"]*"|'[^']*'))*)\s*(\/?)>/g)) {
    const [, closing, tag, attrs, selfClosing] = m;
    if (closing) { at = at.parentNode; continue; }
    const el = new El(tag);
    for (const a of attrs.matchAll(/([\w:-]+)=(?:"([^"]*)"|'([^']*)')/g)) el.setAttribute(a[1], unescape(a[2] ?? a[3]));
    at.append(el);
    if (!selfClosing) at = el;
  }
  return {documentElement: root.children[0]};
}

/** A context with the DOM, fetch answered by ``routes`` (path -> {status, json} | {status, text, type}) and every request recorded
    (its path, its whole url with the query, method and body). */
function context(routes) {
  const body = new El('body');
  const requests = [];
  const document = {body, activeElement: null, createElement: (t) => new El(t), createElementNS: (_, t) => new El(t),
    createTextNode: (t) => new Text_(t), importNode: (n, deep) => n.cloneNode(deep), addEventListener() {}, removeEventListener() {},
    querySelector: (s) => body.querySelector(s)};
  async function fetch(url, opts = {}) {
    const path = String(url).split('?')[0];
    requests.push({path, url: String(url), method: opts.method || 'GET', body: opts.body});
    const r = routes[path] || {status: 404, json: {error: `${path} not found`, kind: 'not_found'}};
    const type = r.json !== undefined ? 'application/json' : (r.type || 'text/plain');
    return {ok: r.status < 300, status: r.status, headers: {get: (k) => (k.toLowerCase() === 'content-type' ? type : r.headers?.[k.toLowerCase()] ?? null)},
      json: async () => r.json, text: async () => (r.text ?? JSON.stringify(r.json)), blob: async () => ({size: (r.text || '').length})};
  }
  const ctx = {document, fetch, requests, DOMParser: class { parseFromString(text) { return parseXml(text); } }, URL: {createObjectURL: () => 'blob:x', revokeObjectURL() {}},
    URLSearchParams, console, setTimeout, clearTimeout, Promise, window: {scrollY: 0, scrollTo() {}, innerHeight: 800}, location: {hash: ''}};
  vm.createContext(ctx);
  return ctx;
}

/** Run the UI files (and glue code given as {code}) as one script, as the browser shares their top-level names. */
function load(ctx, ui, parts) {
  const code = parts.map((p) => (typeof p === 'string' ? fs.readFileSync(ui + p, 'utf8') : p.code)).join('\n;\n');
  vm.runInContext(code + '\n;globalThis.App = App; globalThis.I18N = I18N;', ctx);
}

module.exports = {context, load, El};
