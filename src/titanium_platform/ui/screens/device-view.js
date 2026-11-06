/* Laser specification, documents, results and experiment cards (REQ-017). */
'use strict';
const DeviceView = (() => {
  const {h, btn, field, link, pill, del, post, toast, fail, confirmBox, table, facts, labText, num} = App;
  const g = (v, d = 3) => (v == null ? '—' : String(+(+v).toPrecision(d)));
  const size = (n) => (n < 1024 * 1024 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1024 / 1024).toFixed(1) + ' MB');

  function passportCard(d) {
    const p = d.passport, r = p.repetition_rate_khz;
    return h('div', {class: 'card stack'}, h('h3', {}, 'Specifications'),
      d.description ? h('details', {}, h('summary', {class: 'small muted'}, 'Laser description'), h('p', {class: 'muted'}, d.description)) : null,
      facts([['Manufacturer', d.manufacturer], ['Model', d.model], ['Serial number', d.serial || 'not specified'], ['Rated power', p.rated_power_w + ' W' + (d.characterization.power_basis === 'measured' ? ` (this unit measured ${d.characterization.effective_power_w} W)` : '')],
        ['Wavelength', p.wavelength_nm ? p.wavelength_nm + ' nm' : null], ['Repetition frequency', `${r.min}–${r.max} kHz`],
        ['Default Q-Pulse', p.default_pulse_width_ns != null ? p.default_pulse_width_ns + ' ns (LightBurn omits this from the layer file)' : 'not specified: a layer without Q-Pulse in the file cannot be matched'],
        ['Maximum pulse energy', p.max_pulse_energy_mj ? p.max_pulse_energy_mj + ' mJ' : null],
        // the spot is the installed lens's: measured with it, or calculated from it (REQ-019)
        ['Spot diameter on metal', d.characterization.spot_diameter_um != null
          ? `${g(d.characterization.spot_diameter_um)} µm (${d.characterization.spot_basis === 'measured' ? 'measured with installed lens' : 'calculated from lens'})`
          : 'not specified: fluence is not calculated']]),
      DeviceQuestions.card(d));
  }

  function stepsCard(d) {
    const rows = d.passport.pulse_steps.map((s) => [s.pulse_width_ns + ' ns', s.cutoff_khz == null ? 'CW: no cutoff' : s.cutoff_khz + ' kHz',
      s.cutoff_khz == null ? '—' : g(d.passport.rated_power_w / s.cutoff_khz) + ' mJ']);
    return h('details', {class: 'card stack'}, h('summary', {}, h('strong', {}, `Pulse duration steps and cutoff frequencies: ${d.passport.pulse_steps.length}`)),
      h('p', {class: 'muted small'}, 'The laser accepts only these values. It ignores other values and retains the previous setting, so a plate or plan with another duration cannot be created. '
        + 'Below cutoff frequency power falls in proportion to frequency. Energy is calculated from specifications, not measured.'),
      table(['Pulse duration', 'Cutoff frequency', 'Maximum pulse energy'], rows, undefined, true));
  }

  /** The documents of a laser as the compact list (ux-growing-collections-p0, REQ-002): a line each, a search, the kind as a filter, an order,
      pages of twenty. A line opens to the file's preview and facts only when asked, so a hundred scans are not loaded at once; the document
      opened last stays in view as the pinned line when a search or a filter leaves it out. Every document stays reachable by “Open”. */
  function documentsCard(d, reload) {
    let current = null;                                    // the document the operator opened last
    const url = (x) => `/api/devices/${d.id}/documents/${x.id}`;
    const day = (iso) => (iso || '').slice(0, 10);
    const open = (x) => h('a', {class: 'btn btn-small', href: url(x), target: '_blank', rel: 'noopener'}, 'Open');
    const items = App.list({id: 'device-documents.' + d.id, items: d.documents, key: (x) => x.id, className: 'doc-list',
      search: (x) => `${x.title} ${x.filename} ${DeviceForms.KIND[x.kind] || x.kind}`,
      row: (x) => [h('span', {class: 'lst-text', title: x.title}, x.title), pill(DeviceForms.KIND[x.kind] || x.kind),
        h('span', {class: 'muted small'}, x.filename), h('span', {class: 'muted small'}, size(x.size))],
      details: (x) => {
        current = x.id;
        const preview = x.media_type.startsWith('image/')
          ? h('a', {href: url(x), target: '_blank', rel: 'noopener'}, h('img', {src: url(x), alt: x.title, loading: 'lazy', style: 'max-width:220px;max-height:160px;object-fit:cover'})) : null;
        return h('div', {class: 'stack small'}, preview,
          facts([['Type', DeviceForms.KIND[x.kind] || x.kind], ['File', x.filename], ['Size', size(x.size)], ['Added', day(x.created_at)]]));
      },
      actions: (x) => [open(x), btn('Delete', () => confirmBox('Delete document', `“${x.title}”. The file will be deleted from disk; the specifications remain.`, 'Delete',
        async () => { await del(`/devices/${d.id}/documents/${x.id}`); toast('Document deleted', 'ok'); reload(d.id); }), 'btn-small danger')],
      filters: [{key: 'kind', label: 'Type', select: true, options: DeviceForms.KINDS, test: (x, v) => x.kind === v}],
      sorts: [['newest', 'Newest first', (p, q) => q.id - p.id], ['title', 'Name', (p, q) => p.title.localeCompare(q.title) || p.id - q.id],
        ['size', 'Largest first', (p, q) => q.size - p.size || p.id - q.id]],
      selected: () => current, clearSelection: () => { current = null; },
      empty: 'No documents yet', noResults: 'No documents match this name or type.'});
    return h('div', {class: 'card stack'}, h('h3', {}, 'Documents'),
      h('p', {class: 'muted small'}, 'Original photographs and files are preserved so extracted values can be checked against them.'),
      d.documents.length ? items.el : h('p', {class: 'muted'}, 'No documents yet'), DeviceForms.uploadForm(d, reload));
  }

  function capabilityResultsCard(results, deviceId) {
    const items = (results || []).map((r) => {
      const lens = r.lens ? App.lensLabel(r.lens) : 'lens not recorded';
      const material = [r.material?.name, r.material?.grade, r.material?.batch && `batch ${r.material.batch}`].filter(Boolean).join(' · ') || 'titanium not specified';
      return h('div', {class: 'card stack'},
        h('div', {class: 'row'}, link('/analysis/' + r.pair_id, r.test_name), h('span', {class: 'spacer'}), pill(`${r.measured_features} measured`, 'ok')),
        h('p', {class: 'muted small'}, `${r.accepted_at ? r.accepted_at.slice(0, 10) + ' · ' : ''}${lens} · ${material}`),
        h('p', {}, r.finding),
        ...(r.use_cases || []).filter((item) => item.purpose === 'line' || item.purpose === 'text').map((item) =>
          h('p', {class: 'muted small'}, `${item.purpose === 'line' ? 'Lines' : 'Text'}: ${item.summary}`)),
        link('/analysis/' + r.pair_id, 'Open full analysis'));
    });
    return h('div', {class: 'card stack'}, h('h3', {}, 'Test results for this laser'),
      h('p', {class: 'muted small'}, 'Accepted test plate measurements appear here. Each result retains its lens and titanium stock; details and limitations are in the full analysis.'),
      items.length ? items : h('div', {class: 'empty'}, h('p', {}, 'No accepted test plate results yet.'), link('/experiments', 'Open experiment plates')));
  }

  // The experiments of this laser are the one experiment list filtered by it (REQ-028): no list of plates, engravings or
  // photographs of its own; the same short list with the same search, filters and order as the experiments screen (DEC-090).
  // Beside it, the lookup of a measured result by its settings.
  function experimentsCard(experiments, device, lenses) {
    const byLens = new Map();
    for (const item of experiments) {          // the lens of each work is its lens record (lens_id), not a stored snapshot
      const key = item.lens_id == null ? '' : String(item.lens_id);
      const lens = lenses.find((l) => l.id === item.lens_id);
      if (!byLens.has(key)) byLens.set(key, lens ? App.lensLabel(lens) : 'Historical lens unknown');
    }
    if (device.lens && !byLens.has(String(device.lens.id))) byLens.set(String(device.lens.id), `${App.lensLabel(device.lens)} (currently installed)`);
    const lensPicker = h('select', {}, [...byLens].map(([id, label]) => h('option', {value: id}, label)));
    // the lookup compares exact settings: the server takes any number here (a whole one for the passes), so no end is told and no value is adjusted;
    // an empty or a non-number box is said beside it, and the other typed values stay (ux-save-feedback-p0, REQ-003)
    const lookup = Forms.create();
    const inputs = [['power', 'Power', 'lookupPower'], ['frequency', 'Frequency', 'lookupFrequency'], ['speed', 'Speed', 'lookupSpeed'],
      ['pulse_width', 'Pulse', 'lookupPulse'], ['line_interval', 'Line spacing', 'lookupInterval'], ['passes', 'Passes', 'lookupPasses']]
      .map(([key, label, quantity]) => lookup.add(key, label, Forms.numberInput(Forms.QUANTITIES[quantity]), {quantity, required: true}));
    const result = h('div', {});
    // REQ-020: different engraving tasks remain separate; search one task at a time.
    const taskPicker = Tasks.select('', {empty: 'all tasks, each separate', aria: 'Engraving task'});
    const form = h('form', {class: 'stack', onsubmit: async (event) => {
      event.preventDefault();
      const values = lookup.collect();
      if (!values) return;
      try {
        const found = await post(`/devices/${device.id}/result-lookup`, {lens_id: lensPicker.value === '' ? null : +lensPicker.value, ...values,
          task: taskPicker.value || null});
        if (!found.matches.length) result.replaceChildren(h('div', {class: 'empty'}, h('p', {}, 'No accepted measurements for this lens and these settings yet.')));
        else {
          const cards = found.matches.map((m) => {
            const contexts = m.material_contexts.map((c) => h('p', {class: 'muted small'},
              `Titanium: ${[c.titanium_name, c.titanium_grade, c.titanium_thickness_mm && `${c.titanium_thickness_mm} mm`, c.titanium_surface, c.batch && `batch ${c.batch}`].filter(Boolean).join(' · ') || 'not recorded'} · focus ${c.focus ?? 'not recorded'} · ${c.observations} measurements`));
            const sources = m.source_pair_ids.map((pairId) => link('/analysis/' + pairId, `Photo/analysis for pair ${pairId}`));
            return h('div', {class: 'card stack'},
              h('p', {}, `${labText(m.lab)} · ${m.available_for_prediction ? 'independent repeats available' : 'one observation so far; repeatability not assessed'}`),
              h('p', {class: 'small'}, Tasks.badge(m.task), ` Measured (not predicted): observations ${m.sample.observations} · independent engravings ${m.sample.independent_engravings}`
                + ` · photographs ${m.sample.photographs}`, ...(m.missing_context.length ? [' · missing: ', ...Tasks.missing(m.missing_context)] : [])),
              h('p', {class: 'muted small'}, `LightBurn operation: ${m.parameters.layer_type || 'mode not recorded'} · global passes: ${m.parameters.global_passes ?? '—'} · additional settings are saved with the result.`),
              ...contexts, h('p', {class: 'muted small'}, `Confidence: ${num(m.confidence)} · expected ΔE error: ${num(m.expected_delta_e)}`),
              h('div', {class: 'row'}, ...sources));
          });
          result.replaceChildren(h('div', {class: 'stack'}, h('h4', {}, `Mode and titanium combinations found: ${found.matches.length}`), ...cards));
        }
      } catch (error) { lookup.fail(error); }
    }},
      h('div', {class: 'grid g3'}, field('Historical lens', lensPicker), ...inputs, field('Task', taskPicker)),
      lookup.error, h('button', {type: 'submit', class: 'btn primary'}, 'Find measured result'), result);

    return h('div', {class: 'stack'}, h('div', {class: 'card stack'}, h('h3', {}, 'Measurement database: settings → result'),
      h('p', {class: 'muted small'}, 'Find measured results by six main settings. Matching uses only accepted measurements; each links to its experiment.'), form),
      h('section', {class: 'card dashboard-panel'},
        h('div', {class: 'dashboard-panel-head'}, h('h3', {}, 'Experiments for this laser'), pill(experiments.length),
          link('/experiments?device=' + device.id, 'Open in all experiments')),
        experiments.length ? ExperimentCards.list(experiments, {id: 'laser-experiments', empty: 'No results: change the search, status or task.'})
          : h('div', {class: 'empty'}, h('p', {}, 'No experiments for this laser yet.'), link('/experiments', 'Create experiment'))));
  }
  return {passportCard, stepsCard, documentsCard, capabilityResultsCard, experimentsCard, g};
})();
