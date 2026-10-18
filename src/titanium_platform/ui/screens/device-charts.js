/* Графики лазера: строятся только из паспорта, который вернул сервер (REQ-017). Ничего не вводится дважды.
   SVG рисуется здесь, без библиотек; внешний вид рамки задаёт styles.css (svg[role=img]). */
'use strict';
const DeviceCharts = (() => {
  const SVG = 'http://www.w3.org/2000/svg';
  const W = 640, H = 340, M = {l: 64, r: 22, t: 20, b: 50};
  const COLORS = ['#a9b8ff', '#7de0ba', '#f2ce8b', '#ff9eaf', '#8fc0be', '#c0a6ca'];

  function el(tag, attrs, text) {
    const n = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (text != null) n.textContent = text;
    return n;
  }

  /** Деления оси: 1-2-5 по степеням десяти для логарифмической оси, «круглые» числа для линейной. */
  function ticks(lo, hi, log) {
    const out = [];
    if (log) {
      for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
        for (const m of [1, 2, 5]) { const v = m * 10 ** e; if (v >= lo * 0.999 && v <= hi * 1.001) out.push(v); }
      }
      return out;
    }
    const raw = (hi - lo) / 5 || 1, mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 5, 10].map((k) => k * mag).find((s) => s >= raw) || 10 * mag;
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }
  const fmt = (v) => (v >= 1000 ? v / 1000 + 'k' : String(+v.toPrecision(3)));

  /**
   * График. series: [{name, points: [[x, y]], color, width, dash, markers, faint}],
   * marks: [{x, y, label, color}] — отдельные точки (рассчитанная рабочая точка, частота среза).
   */
  function plot({title, xLabel, yLabel, series, marks = [], xLog = false, yLog = false}) {
    const pts = series.flatMap((s) => s.points).concat(marks.map((m) => [m.x, m.y]));
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const y0 = yLog ? Math.min(...ys) / 1.3 : Math.min(0, ...ys), y1 = Math.max(...ys) * (yLog ? 1.3 : 1.08);
    const fx = (v) => (xLog ? Math.log(v / x0) / Math.log(x1 / x0) : (v - x0) / (x1 - x0 || 1));
    const fy = (v) => (yLog ? Math.log(v / y0) / Math.log(y1 / y0) : (v - y0) / (y1 - y0 || 1));
    const sx = (v) => M.l + fx(v) * (W - M.l - M.r), sy = (v) => H - M.b - fy(v) * (H - M.t - M.b);
    const svg = el('svg', {viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': title});
    svg.style.cssText = 'width:100%;max-width:760px';
    for (const t of ticks(x0, x1, xLog)) {
      svg.append(el('line', {x1: sx(t), x2: sx(t), y1: M.t, y2: H - M.b, stroke: '#8197bc', 'stroke-opacity': '.14'}),
        el('text', {x: sx(t), y: H - M.b + 18, fill: '#a0acc0', 'font-size': 11, 'text-anchor': 'middle'}, fmt(t)));
    }
    for (const t of ticks(y0, y1, yLog)) {
      svg.append(el('line', {x1: M.l, x2: W - M.r, y1: sy(t), y2: sy(t), stroke: '#8197bc', 'stroke-opacity': '.14'}),
        el('text', {x: M.l - 8, y: sy(t) + 4, fill: '#a0acc0', 'font-size': 11, 'text-anchor': 'end'}, fmt(t)));
    }
    const cy = (M.t + H - M.b) / 2;
    svg.append(el('text', {x: (M.l + W - M.r) / 2, y: H - 10, fill: '#c4d0e4', 'font-size': 12, 'text-anchor': 'middle'}, xLabel),
      el('text', {x: 14, y: cy, fill: '#c4d0e4', 'font-size': 12, 'text-anchor': 'middle', transform: `rotate(-90 14 ${cy})`}, yLabel));
    series.forEach((s, i) => {
      const color = s.color || COLORS[i % COLORS.length];
      svg.append(el('polyline', {points: s.points.map(([x, y]) => `${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join(' '), fill: 'none', stroke: color,
        'stroke-width': s.width || 2, 'stroke-dasharray': s.dash || '', 'stroke-linejoin': 'round', 'stroke-opacity': s.faint ? '.35' : '1'}));
      if (s.markers) {
        s.points.forEach(([x, y]) => { const c = el('circle', {cx: sx(x), cy: sy(y), r: 3.5, fill: color}); c.append(el('title', {}, `${s.name}: ${fmt(x)} → ${+y.toPrecision(4)}`)); svg.append(c); });
      }
    });
    marks.forEach((m) => {
      const c = el('circle', {cx: sx(m.x), cy: sy(m.y), r: 6, fill: m.color || '#ff9eaf', stroke: '#fff', 'stroke-width': 1.5});
      c.append(el('title', {}, m.label));
      const right = sx(m.x) > W - 130;
      svg.append(c, el('text', {x: sx(m.x) + (right ? -9 : 9), y: sy(m.y) - 9, fill: '#e9eef7', 'font-size': 11, 'text-anchor': right ? 'end' : 'start'}, m.label));
    });
    return svg;
  }
  return {plot, COLORS};
})();
