/* Pair review tables and dialogs: discrepancies, layers, replacement and file confirmation (DEC-017). */
'use strict';
const IngestDialogs = (() => {
  const {h, pill, post, form, toast, modal, table, num} = App;
  const FIELD = {power: 'Power', frequency: 'Frequency', speed: 'Speed'};
  const ROLE = {'test feature': 'test feature', 'pre-test cleaning witness': 'pre-test cleaning witness',
    'registration, QR and engraved labels': 'markers, QR and labels'};

  const discrepancyTable = (list) => table(['Cell', 'Field', 'Plate definition', 'LightBurn file'],
    list.map((d) => [d.cell_id, FIELD[d.field] || d.field, d.defined, d.from_file ?? 'not in file']));

  const labText = (lab) => lab ? `L* ${num(lab[0], 1)} · a* ${num(lab[1], 1)} · b* ${num(lab[2], 1)}` : 'no readable pixels';
  const layerResult = (l) => {
    if (!l.measured_lab) return h('span', {}, pill(l.readable ? 'skipped' : 'unreadable', 'warn'), ' ', l.notes.map((n) => I18N.tr(n)).join('; '));
    const details = [h('div', {}, pill('measured', 'ok'), ` · ${labText(l.measured_lab_against_clean || l.measured_lab)}`
      + `${l.measured_lab_against_clean ? ' relative to clean titanium' : ''} · ${num(l.pixels, 0)} pixels`)];
    if (l.role) details.push(h('div', {class: 'muted small'}, ROLE[l.role] || l.role));
    if (l.measurement) details.push(h('div', {class: 'muted small'}, I18N.tr(l.measurement)));
    if (l.submeasurements?.length) details.push(...l.submeasurements.map((m) => h('div', {class: 'muted small'}, `${m.name}: ${labText(m.measured_lab)} · ${num(m.pixels, 0)} pixels`)));
    if (l.line_metrics) {
      const m = l.line_metrics;
      details.push(h('div', {class: 'muted small'}, `Lines: visible ${m.visible_line_count}/${m.line_count} · continuity ${num(m.median_continuity_percent, 1)}% · contrast ${num(m.median_contrast_Lstar, 1)} L*${m.median_apparent_trace_width_mm == null ? '' : ` · apparent width ${num(m.median_apparent_trace_width_mm, 3)} mm`}`));
      if (m.groups?.length) details.push(h('div', {class: 'muted small'}, 'Spacing groups: ' + m.groups.map((g) =>
        `${g.spacing_um} µm — ${g.visible_line_count}/${g.line_count} lines, ${num(g.median_continuity_percent, 0)}% continuity`).join(' · ')));
    }
    const source = l.source_settings || {};
    const get = (name) => source[name]?.Value;
    if (get('wobbleEnable') != null && get('wobbleEnable') !== '0') details.push(h('div', {class: 'muted small'}, `Wobble: step ${get('wobbleStep')} mm · size ${get('wobbleSize')} mm`));
    if (l.notes?.length) details.push(h('div', {class: 'muted small'}, l.notes.map((n) => I18N.tr(n)).join('; ')));
    return h('div', {class: 'stack small'}, ...details);
  };
  // the layers of the file as a short list (findings-you-can-manage-short-lists-re-check, REQ-005, DEC-090): a matrix photograph has a
  // hundred. One line per layer (name, power · frequency · speed, areas, the result), those not measured first, the result under the line.
  const RESULT = {unreadable: ['unreadable', 'warn', 'Unreadable'], skipped: ['skipped', 'warn', 'Skipped'], measured: ['measured', 'ok', 'Measured']};
  const resultOf = (l) => (l.measured_lab ? 'measured' : l.readable ? 'skipped' : 'unreadable');
  const rank = (l) => Object.keys(RESULT).indexOf(resultOf(l));
  const settingsOf = (l) => [l.power == null ? null : `${num(l.power, 1)} %`, l.frequency_khz == null ? null : `${num(l.frequency_khz, 0)} kHz`,
    l.speed == null ? null : `${num(l.speed, 0)} mm/s`].filter(Boolean).join(' · ') || 'settings not read';
  const layersTable = (layers) => App.list({items: layers, key: (l) => l.index, empty: 'No layers',
    row: (l) => [h('span', {class: 'lst-text', title: I18N.name(l.name)}, I18N.name(l.name)), h('span', {class: 'muted small'}, settingsOf(l)),
      h('span', {class: 'muted small'}, `regions ${l.regions}`), pill(RESULT[resultOf(l)][0], RESULT[resultOf(l)][1])],
    details: layerResult, search: (l) => `${I18N.name(l.name)} ${l.name}`,
    filters: [{key: 'result', label: 'Result', options: Object.entries(RESULT).map(([k, [, , label]]) => [k, label]), test: (l, v) => resultOf(l) === v}],
    sorts: [['problems', 'Unmeasured first', (a, b) => rank(a) - rank(b) || a.index - b.index], ['order', 'Original order', (a, b) => a.index - b.index]]}).el;

  /** Replace the LightBurn file; review, confirmation and mask review are reset on the server. */
  function fixFile(pair, reload) {
    const f = Forms.create();
    const file = h('input', {type: 'file', accept: '.lbrn,.lbrn2'});
    modal('Correct pair', h('div', {class: 'stack'}, f.add('file', 'Different LightBurn file', App.filePick(file, 'Choose LightBurn file'), {required: true,
      read: () => (!file.files[0] ? {ok: false, message: 'Choose a .lbrn or .lbrn2 file'}
        : /\.lbrn2?$/i.test(file.files[0].name) ? {ok: true, value: file.files[0]} : {ok: false, message: 'A .lbrn or .lbrn2 file is required'})}), f.error), [
      {label: 'Cancel', run: (m) => m.close()},
      {label: 'Replace file', cls: 'primary', run: async (m) => {
        const v = f.collect();
        if (!v) return;                                                  // the dialog stays open; the reason is beside the file
        const fd = new FormData();
        fd.append('lightburn', v.file);
        try { await form(`/pairs/${pair.id}/lightburn`, fd); } catch (e) { f.fail(e); return; }
        m.close(); toast('File replaced. Run the review again', 'ok'); reload();
      }}]);
  }

  /** Explicit confirmation that the attached file was used for engraving; discrepancies are recorded with it. */
  function confirmFile(pair, check, reload) {
    const f = Forms.create();
    const ok = h('input', {type: 'checkbox'});
    const tick = f.add('ok', 'I confirm that the attached LightBurn file was used for the physical engraving', ok, {required: true,
      read: () => (ok.checked ? {ok: true, value: true} : {ok: false, message: 'Confirm that the file was used for engraving'})});
    // ingest.confirm_file: the words are required ("state in your own words that this file was used for the engraving")
    const text = f.add('text', 'Your confirmation', h('textarea', {rows: 3, placeholder: 'For example: this exact file was used for the engraving'}), {required: true,
      help: 'in your own words: this file was used for engraving'});
    modal('Confirm the file used', h('div', {class: 'stack'}, discrepancyTable(check.discrepancies), tick, text, f.error), [
      {label: 'Cancel', run: (m) => m.close()},
      {label: 'Confirm', cls: 'primary', run: async (m) => {
        const v = f.collect();
        if (!v) return;
        try { await post(`/pairs/${pair.id}/confirm-file`, {text: v.text}); } catch (e) { f.fail(e); return; }
        m.close(); toast('Confirmation recorded with discrepancies', 'ok'); reload();
      }}]);
  }

  return {discrepancyTable, layersTable, fixFile, confirmFile};
})();
