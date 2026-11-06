/* Independent evidence signals and prediction applicability (ux-evidence-summaries-p0, REQ-001). */
'use strict';
const EvidenceSummary = (() => {
  const {h, pill, steadiness, STEADY, agreed, originText} = App;
  const MEASURED = {calibrated: ['reference chart corrected', 'ok'], relative: ['camera relative', 'warn']};
  const mm = (v) => `${+(+v).toFixed(1)} mm`;
  const mmList = (list) => (list || []).map(mm).join(' and ');
  const count = (n, singular, plural) => `${n} ${n === 1 ? singular : plural}`;
  const LEVEL = {
    measured_here: ['measured at this size', 'ok', 'The colors in this prediction were measured at the same row width.'],
    other_width: ['measured at another width', 'warn', 'The colors were measured at another row width and may differ at this size.'],
    test_scale_only: ['test scale only', 'warn', 'The prediction uses only test scales; color and contrast accuracy for photo engraving is unverified.'],
    unknown: ['measurement width unknown', 'warn', 'The row width used for the color measurements is unknown: their LightBurn files are unavailable.']};

  function signalsOf(e) {
    const out = [];
    const a = e.agreement;
    if (a) {
      const steady = steadiness(e);
      out.push({key: 'repeat', text: STEADY[steady][0], tone: STEADY[steady][1], title: `Color agreement: ${agreed(a)}`});
    }
    if (e.measurement && MEASURED[e.measurement]) {
      out.push({key: 'source', text: MEASURED[e.measurement][0], tone: MEASURED[e.measurement][1], title: 'Measurement source: how the photo color was corrected'});
    }
    if (e.referenced === false) out.push({key: 'reference', text: 'as photographed, unreferenced', tone: 'warn', title: 'Color is not referenced to clean titanium'});
    const sources = e.sources && e.sources.length ? e.sources : e.origin ? [{origin: e.origin}] : null;
    if (sources) out.push({key: 'basis', text: originText(sources), tone: '', title: 'Color evidence: tests and works'});
    else if (e.engravings != null) out.push({key: 'basis', text: count(e.engravings, 'independent engraving', 'independent engravings'), tone: '', title: 'Color evidence'});
    return out;
  }

  function summary(e, {lead = null, label = 'Evidence summary'} = {}) {
    const signals = signalsOf(e || {});
    if (!signals.length && !lead) return null;
    return h('div', {class: 'ev-summary', role: 'group', 'aria-label': label}, lead,
      ...signals.map((s) => h('span', {class: 'pill ev-signal ev-' + s.key + (s.tone ? ' ' + s.tone : ''), title: s.title}, s.text)));
  }

  function disclosure(title, content, open = false) {
    return h('details', {class: 'ev-more', open}, h('summary', {}, title), h('div', {class: 'stack small ev-more-body'}, content));
  }

  function sentences(a) {
    const size = a.size || {}, c = a.counts || null;
    const out = [];
    for (const limit of a.limits && a.limits.length ? a.limits : [a.level]) {
      if (limit === 'test_scale_only') {
        out.push(c && c.ramp_only_zones ? `${count(c.ramp_only_zones, 'photo zone is', 'photo zones are')} predicted using test scales only: `
          + 'these settings have no photo engraving measurements, and color and contrast accuracy are unverified.' : LEVEL.test_scale_only[2]);
      } else if (limit === 'other_width') {
        if (c) out.push(`Measurements at another width: ${c.estimated_layers} of ${c.layers} color layers${c.estimated_zones ? ` and ${count(c.estimated_zones, 'photo zone', 'photo zones')}` : ''}. `
          + 'Accuracy for this work has not been verified.');
        else if (size.how === 'between') out.push(`A row width of ${mm(size.row_mm)} was not measured: colors are interpolated between measurements at ${mmList(size.from_mm)}.`);
        else if (size.how === 'outside') out.push(`Measured at ${mmList(size.measured_mm)}, but not at ${mm(size.row_mm)}: colors use measurements at ${mmList(size.from_mm)} without extrapolation.`);
        else out.push(LEVEL.other_width[2]);
      } else if (limit === 'unknown') out.push(LEVEL.unknown[2]);
      else if (limit === 'measured_here') out.push(c ? `Colors of ${c.layers} color layers were measured at this size. Photo zones are checked against their own scales.`
        : size.from_mm && size.from_mm.length ? `Colors were measured at a row width of ${mm(size.from_mm[0])}.` : LEVEL.measured_here[2]);
    }
    return out;
  }

  function applicability(a) {
    if (!a || !LEVEL[a.level]) return null;
    const [text, tone] = LEVEL[a.level];
    const lines = sentences(a);
    const size = a.size && (a.size.measured_mm || []).length ? `Row width: ${a.size.row_mm == null ? '—' : mm(a.size.row_mm)}; measured at: ${mmList(a.size.measured_mm)}.` : null;
    return h('div', {class: 'ev-applic ev-applic-' + a.level + (tone === 'ok' ? '' : ' alert warn'), role: 'note', 'data-level': a.level},
      h('div', {class: 'row ev-applic-head'}, h('strong', {class: 'small'}, 'Prediction:'), pill(text, tone), h('span', {class: 'small ev-applic-text'}, lines[0])),
      lines.length > 1 || size ? disclosure('Prediction evidence', [...lines.slice(1).map((line) => h('p', {}, line)), size ? h('p', {class: 'muted'}, size) : null]) : null);
  }

  return {summary, signalsOf, disclosure, applicability, LEVEL};
})();
