/* Analysis of an accepted engraving with on-demand measurement details. */
'use strict';
(() => {
  const {h, btn, link, pill, get, post, del, go, toast, fail, confirmBox, modal, table, num, labText, swatch} = App;
  const MODE = {'Calibration plate': 'Calibration plate', 'Laser capability test': 'Laser capability test',
    'Discrete color engraving': 'Discrete color engraving', 'Tonal photo engraving': 'Tonal photo engraving',
    'Color-path photo engraving': 'Color-path photo engraving', 'Restored from file': 'Restored from file',
    'Photo engraving work': 'Photo engraving work'};
  const PURPOSE = {line: 'Lines', text: 'Text', color: 'Color', image: 'Image'};
  const PURPOSE_STATUS = {candidate: ['Candidate', 'ok'], incomplete_settings: ['Missing settings', 'warn'],
    insufficient: ['Insufficient data', 'warn'], needs_text_test: ['Test needed', 'warn'],
    needs_color_test: ['Test needed', 'warn'], needs_image_test: ['Test needed', 'warn'],
    contrast_candidate: ['High-contrast sample', 'warn']};
  const GROUPS = [
    ['gap', 'Line spacing'], ['frequency', 'Frequency'], ['wobble', 'Wobble'],
    ['hatch', 'Hatch spacing'], ['text', 'Text'], ['surface', 'Cleaning and markings'], ['other', 'Other elements']];
  const LAYER_TYPE = {Cut: 'Line', Scan: 'Fill', OffsetFill: 'Offset fill', Image: 'Image'};
  const SOURCE_LABELS = {maxPower: 'Max power', maxPower2: 'Second power', speed: 'Speed',
    frequency: 'Frequency (Hz)', QPulseWidth: 'Q-Pulse (ns)', interval: 'Line interval (mm)',
    numPasses: 'Layer passes', globalRepeat: 'Global passes', bidir: 'Bidirectional',
    crossHatch: 'Cross-hatch', angle: 'Scan angle', anglePerPass: 'Angle increment',
    wobbleEnable: 'Wobble enabled', wobbleStep: 'Wobble step (mm)', wobbleSize: 'Wobble size (mm)',
    priority: 'Layer order', tabCount: 'Tab count', tabCountMax: 'Max tabs'};

  const kpi = (value, label, hint = '') => h('div', {class: 'analysis-kpi', title: hint},
    h('strong', {}, value), h('span', {}, label));
  const card = (title, body, extraClass = '') => h('section', {class: 'card analysis-panel ' + extraClass},
    h('h3', {}, title), body);
  const unique = (items) => [...new Set(items.filter(Boolean))];
  const firstSentence = (value) => (value || '').split(/(?<=[.!?])\s/)[0];

  function settingsLabel(s = {}) {
    const parts = [];
    const source = s.source_settings || {};
    const setting = (name) => source[name]?.Value;
    parts.push(LAYER_TYPE[s.layer_type] || s.layer_type || 'Mode not specified');
    if (s.power != null) parts.push(`${num(s.power, 1)} %`);
    if (s.frequency != null) parts.push(`${num(s.frequency, 1)} kHz`);
    if (s.speed != null) parts.push(`${num(s.speed, 0)} mm/s`);
    parts.push(s.pulse_width != null ? `Q-Pulse ${num(s.pulse_width, 0)} ns` : s.defaulted_settings?.pulse_width ? `Q-Pulse ${num(s.defaulted_settings.pulse_width.value, 0)} ns (laser default)` : 'Q-Pulse not set');
    if (s.layer_type !== 'Cut' && s.line_interval != null) parts.push(`interval ${num(s.line_interval, 4)} mm`);
    if (s.passes != null) parts.push(`${s.passes} passes${!source.numPasses ? ' (default)' : ''}`);
    if (s.global_passes != null) parts.push(`global passes ${s.global_passes}${!source.globalRepeat ? ' (default)' : ''}`);
    if (s.layer_type !== 'Cut') {
      parts.push(`direction: ${s.bidirectional ? 'bidirectional' : 'unidirectional'}${!source.bidir ? ' (default)' : ''}`);
      parts.push(`angle ${num(s.scan_angle ?? 0, 1)}°${!source.angle ? ' (default)' : ''}`);
      parts.push(`angle increment ${num(s.angle_increment ?? 0, 1)}°${!source.anglePerPass ? ' (default)' : ''}`);
      parts.push(`cross-hatch ${s.cross_hatch ? 'yes' : 'no'}${!source.crossHatch ? ' (default)' : ''}`);
    }
    if (setting('wobbleEnable') === '1') parts.push(setting('wobbleStep') != null && setting('wobbleSize') != null
      ? `Wobble: interval ${setting('wobbleStep')} mm · size ${setting('wobbleSize')} mm`
      : 'Wobble enabled; step and size are not recorded in the file');
    return parts.join(' · ') || 'Settings are not specified in the file';
  }

  function allSettings(s = {}) {
    const source = s.source_settings || {};
    const sourced = (tag, value) => source[tag] ? value : `${value} · default; absent from file`;
    const wobble = source.wobbleEnable?.Value;
    const normalized = [
      ['Mode', LAYER_TYPE[s.layer_type] || s.layer_type || 'not in file'],
      ['Power', s.power == null ? 'not in file' : `${num(s.power, 2)} %`],
      ['Frequency', s.frequency == null ? 'not in file' : `${num(s.frequency, 2)} kHz`],
      ['Speed', s.speed == null ? 'not in file' : `${num(s.speed, 2)} mm/s`],
      ['Q-Pulse', s.pulse_width != null ? `${num(s.pulse_width, 2)} ns` : s.defaulted_settings?.pulse_width ? `${num(s.defaulted_settings.pulse_width.value, 2)} ns (laser default)` : 'not set'],
      ['Line interval', s.layer_type === 'Cut' ? 'not applicable to a line' : s.line_interval == null ? 'not in file' : `${num(s.line_interval, 4)} mm`],
      ['Layer passes', s.passes == null ? 'not in file' : sourced('numPasses', String(s.passes))],
      ['Global passes', s.global_passes == null ? 'not in file' : sourced('globalRepeat', String(s.global_passes))],
      ['Pass direction', s.bidirectional == null ? 'not in file' : sourced('bidir', s.bidirectional ? 'bidirectional' : 'unidirectional')],
      ['Cross-hatch', s.cross_hatch == null ? 'not in file' : sourced('crossHatch', s.cross_hatch ? 'yes' : 'no')],
      ['Scan angle', s.scan_angle == null ? 'not in file' : sourced('angle', `${num(s.scan_angle, 2)}°`)],
      ['Angle increment', s.angle_increment == null ? 'not in file' : sourced('anglePerPass', `${num(s.angle_increment, 2)}°`)],
      ['Wobble', source.wobbleEnable ? ['1', 'true', 'yes'].includes(String(wobble).toLowerCase()) ? 'enabled' : 'disabled' : 'not recorded in file'],
      ['Wobble: step', source.wobbleStep?.Value == null ? 'not in file' : `${source.wobbleStep.Value} mm`],
      ['Wobble: size', source.wobbleSize?.Value == null ? 'not in file' : `${source.wobbleSize.Value} mm`],
    ];
    return h('div', {class: 'analysis-settings'},
      h('strong', {}, 'Read layer settings'),
      h('div', {class: 'analysis-settings-grid'}, ...normalized.map(([label, value]) => h('div', {}, h('span', {}, label), h('b', {}, value)))),
      h('details', {}, h('summary', {}, `All LightBurn fields in this layer (${Object.keys(source).length})`),
        h('div', {class: 'analysis-source-grid'}, ...Object.entries(source).map(([tag, raw]) => {
          const value = raw && typeof raw === 'object' && Object.keys(raw).length === 1 && raw.Value != null
            ? raw.Value : typeof raw === 'string' ? raw : JSON.stringify(raw);
          return h('div', {}, h('span', {}, SOURCE_LABELS[tag] || tag), h('code', {}, `${tag} = ${value}`));
        }))));
  }

  function groupOf(row) {
    const name = row.name || '';
    if (name.startsWith('LINE-GAP-')) return 'gap';
    if (name.startsWith('FREQUENCY-')) return 'frequency';
    if (name.startsWith('WOBBLE-')) return 'wobble';
    if (name.startsWith('HATCH-')) return 'hatch';
    if (name.startsWith('TEXT-')) return 'text';
    if (row.role === 'pre-test cleaning witness' || row.role === 'registration, QR and engraved labels') return 'surface';
    return 'other';
  }

  function detailBody(row, capability) {
    const m = row.line_metrics;
    const measurements = [];
    if (m) {
      measurements.push(kpi(`${m.visible_line_count}/${m.line_count}`, 'visible lines'));
      if (m.median_continuity_percent != null) measurements.push(kpi(`${num(m.median_continuity_percent, 0)}%`, 'continuity'));
      if (m.median_contrast_Lstar != null) measurements.push(kpi(num(m.median_contrast_Lstar, 1), 'contrast L*'));
      if (m.median_apparent_trace_width_mm != null) measurements.push(kpi(`${num(m.median_apparent_trace_width_mm, 3)} mm`, 'apparent trace width', 'Not the optical spot diameter'));
    }
    return h('div', {class: 'analysis-detail-body'},
      allSettings(row.parameters),
      measurements.length ? h('div', {class: 'analysis-detail-kpis'}, ...measurements) : null,
      row.measured_lab_against_clean ? h('p', {class: 'analysis-lab'}, swatch(row.measured_lab_against_clean),
        `Color relative to clean titanium: ${labText(row.measured_lab_against_clean)}`, h('span', {class: 'muted small'}, ` · as photographed: ${labText(row.measured_lab)}`))
      : row.measured_lab ? h('p', {class: 'analysis-lab'}, swatch(row.measured_lab),
        `${capability ? 'Camera response' : 'Measured color'}: ${labText(row.measured_lab)}`) : h('p', {class: 'muted small'}, 'Not measured in the photo'),
      // REQ-020: layer task and each metric with its method and basis; unavailable metrics include a reason
      row.task ? h('p', {class: 'small'}, 'Task: ', Tasks.badge(row.task)) : null,
      Tasks.metrics(row.metrics),
      row.planned_lab ? h('p', {class: 'small'}, 'Planned color: ', swatch(row.planned_lab), labText(row.planned_lab),
        row.delta_e != null ? ` · ΔE ${num(row.delta_e, 1)}` : '') : null,
      row.note ? h('p', {class: 'muted small'}, I18N.tr(row.note)) : null,
      row.name?.startsWith('TEXT-') ? h('p', {class: 'alert warn small'}, 'The photo measures the inscription response. Contrast alone does not establish character legibility or edge quality.') : null,
      row.name?.startsWith('WOBBLE-') ? h('p', {class: 'alert warn small'}, 'The area response was measured; trace geometry has not yet been assessed.') : null,
      m?.groups?.length ? h('div', {class: 'analysis-sublist'},
        h('strong', {}, 'Gap groups'), ...m.groups.map((g) => h('div', {},
          `${g.spacing_um} µm · ${g.visible_line_count}/${g.line_count} lines · continuity ${num(g.median_continuity_percent, 0)}%`))) : null,
      row.submeasurements?.length ? h('div', {class: 'analysis-sublist'},
        h('strong', {}, `Individual elements (${row.submeasurements.length})`),
        ...row.submeasurements.map((item) => h('div', {}, item.name, ' · ', item.measured_lab ? labText(item.measured_lab) : 'not measured'))) : null);
  }

  function showElement(row, capability) {
    modal(row.name || `Layer ${row.layer_index}`, detailBody(row, capability),
      [{label: 'Close', run: ({close}) => close()}]);
  }
  function showGroup(title, rows, capability) {
    const body = h('div', {class: 'analysis-detail-list'},
      ...rows.map((row) => h('details', {class: 'analysis-detail-item'},
        h('summary', {}, h('strong', {}, row.name || `Layer ${row.layer_index}`),
          row.line_metrics ? h('span', {class: 'muted small'}, `${row.line_metrics.visible_line_count}/${row.line_metrics.line_count} lines`) :
            row.measured_lab ? h('span', {class: 'muted small'}, `L* ${num((row.measured_lab_against_clean || row.measured_lab)[0], 1)}`) : null),
        detailBody(row, capability))));
    modal(title, body, [{label: 'Close', run: ({close}) => close()}]);
  }

  function useCases(c) {
    return h('div', {class: 'analysis-use-list'}, ...(c.use_cases || []).map((item) => {
      const [status, kind] = PURPOSE_STATUS[item.status] || [item.status, 'warn'];
      return h('button', {type: 'button', class: 'analysis-use', onClick: () => modal(PURPOSE[item.purpose] || item.purpose,
        h('div', {class: 'stack'}, h('p', {}, item.summary),
          item.parameters ? h('p', {class: 'analysis-params'}, settingsLabel(item.parameters)) : null,
          h('div', {class: 'alert'}, h('strong', {}, 'Next step'), h('p', {}, item.next_test)),
          item.evidence?.name ? h('p', {class: 'muted small'}, `Evidence: ${item.evidence.name}`) : null),
        [{label: 'Close', run: ({close}) => close()}])},
        h('span', {class: 'analysis-use-top'}, h('strong', {}, PURPOSE[item.purpose] || item.purpose), pill(status, kind)),
        h('span', {class: 'analysis-use-preview'}, firstSentence(item.summary)));
    }));
  }

  function matrix(rows) {
    const lineRows = rows.filter((row) => row.name?.startsWith('LINE-P'));
    if (!lineRows.length) return h('p', {class: 'muted'}, 'This file contains no single-line matrix.');
    const powers = unique(lineRows.map((row) => row.parameters?.power)).sort((a, b) => a - b);
    const speeds = unique(lineRows.map((row) => row.parameters?.speed)).sort((a, b) => a - b);
    const byCell = new Map(lineRows.map((row) => [`${row.parameters.power}/${row.parameters.speed}`, row]));
    return h('div', {class: 'analysis-matrix-wrap'},
      h('p', {class: 'muted small'}, 'Columns show power (%), rows show speed (mm/s). Select a cell for settings and measurements.'),
      h('div', {class: 'analysis-matrix', style: `--axis-columns:${powers.length}`},
        h('span', {class: 'analysis-axis'}, 'V / P'),
        ...powers.map((power) => h('strong', {class: 'analysis-axis'}, `${power}%`)),
        ...speeds.flatMap((speed) => [h('strong', {class: 'analysis-axis'}, speed), ...powers.map((power) => {
          const row = byCell.get(`${power}/${speed}`);
          const m = row?.line_metrics;
          const visible = (m?.visible_line_count || 0) > 0;
          const strong = visible && (m?.median_continuity_percent || 0) >= 90;
          const status = !row ? 'unknown' : strong ? 'strong' : visible ? 'partial' : 'absent';
          return h('button', {type: 'button', class: `analysis-cell ${status}`, disabled: !row,
            title: row ? `${row.name} · ${settingsLabel(row.parameters)}` : 'No element',
            'aria-label': `${power}% · ${speed} mm/s · ${strong ? 'continuous line' : visible ? 'partial trace' : 'line not confirmed'}`,
            onClick: () => showElement(row, true)}, row ? visible ? `${num(m.median_continuity_percent, 0)}%` : '—' : '');
        })])),
      h('div', {class: 'analysis-legend'},
        h('span', {}, h('i', {class: 'strong'}, ''), 'Continuous'),
        h('span', {}, h('i', {class: 'partial'}, ''), 'Partial'),
        h('span', {}, h('i', {class: 'absent'}, ''), 'Not confirmed')));
  }

  function groupSummary(id, rows) {
    if (id === 'gap') {
      const m = rows[0]?.line_metrics;
      return m ? `${m.visible_line_count}/${m.line_count} lines · ${m.groups?.length || 0} spacings` : 'Gaps measured';
    }
    if (id === 'frequency') {
      const visible = rows.filter((row) => row.line_metrics?.visible_line_count).length;
      const best = rows.reduce((top, row) => !top || (row.line_metrics?.median_continuity_percent || 0) >
        (top.line_metrics?.median_continuity_percent || 0) ? row : top, null);
      return `${visible}/${rows.length} lines visible${best ? ` · maximum ${num(best.line_metrics?.median_continuity_percent, 0)}%` : ''}`;
    }
    if (id === 'text') return `${rows.flatMap((row) => row.submeasurements || []).length || rows.length} sizes · legibility not assessed`;
    const lightness = rows.filter((row) => row.measured_lab).map((row) => row.measured_lab[0]);
    return lightness.length ? `${rows.length} areas · L* ${num(Math.min(...lightness), 1)}–${num(Math.max(...lightness), 1)}` : `${rows.length} elements`;
  }

  function capabilityDashboard(r) {
    const c = r.capability;
    const groups = new Map();
    for (const row of r.rows) {
      if (row.name?.startsWith('LINE-P')) continue;
      const group = groupOf(row);
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(row);
    }
    const modules = GROUPS.filter(([id]) => groups.has(id)).map(([id, title]) => {
      const rows = groups.get(id);
      return h('button', {type: 'button', class: 'analysis-module', onClick: () => showGroup(title, rows, true)},
        h('strong', {}, title), h('span', {}, groupSummary(id, rows)), h('small', {}, `Elements: ${rows.length} · open measurements →`));
    });
    const limitations = unique([...(r.limitations || []).map((text) => I18N.tr(text)), ...(c.limitations || [])]);
    const lightness = c.lightness_range ? `${num(c.lightness_range[0], 1)}–${num(c.lightness_range[1], 1)}` : '—';
    return [
      h('div', {class: 'analysis-kpi-grid'}, kpi(c.measured_features, 'test layers'),
        kpi(`${c.line_response?.visible || 0}/${c.line_response?.tested || 0}`, 'single lines visible'),
        kpi(c.gap_response ? `${c.gap_response.visible_line_count}/${c.gap_response.line_count}` : '—', 'lines in gap groups'),
        kpi(lightness, 'L* range in RAW')),
      h('div', {class: 'analysis-primary'},
        card('Power × speed', matrix(r.rows)),
        card('Task findings', useCases(c))),
      h('div', {class: 'analysis-modules'}, ...modules),
      h('div', {class: 'analysis-bottom'},
        card('What the photo showed', h('div', {class: 'analysis-conclusions'},
          h('p', {class: 'analysis-lead'}, c.finding),
          ...(c.signals || []).slice(0, 2).map((signal) => h('p', {}, signal)),
          (c.signals || []).length > 2 ? btn(`All observations (${c.signals.length})`, () => modal('Photo observations',
            h('div', {class: 'analysis-detail-list'}, ...c.signals.map((signal) => h('p', {}, signal))),
            [{label: 'Close', run: ({close}) => close()}]), 'btn-small') : null)),
        card('Next steps', h('div', {class: 'analysis-conclusions'},
          ...(c.next_steps || []).slice(0, 2).map((step, i) => h('p', {}, h('strong', {}, `${i + 1}. `), step)),
          (c.next_steps || []).length > 2 ? btn(`All steps (${c.next_steps.length})`, () => modal('Next checks',
            h('div', {class: 'analysis-detail-list'}, ...c.next_steps.map((step, i) => h('p', {}, `${i + 1}. ${step}`))),
            [{label: 'Close', run: ({close}) => close()}]), 'btn-small') : null))),
      h('details', {class: 'analysis-footnote'}, h('summary', {}, `Measurement limitations (${limitations.length})`),
        ...limitations.map((text) => h('p', {}, text)))
    ];
  }

  // -- the measured elements as a short list (findings-you-can-manage-short-lists-re-check, REQ-005, DEC-090) ----------------------
  // A parameter matrix has a hundred elements: one line each (colour, name, ΔE to the planned colour, a problem), the worst first, the
  // measurements and settings under the line on a click, twenty at a time.

  /** What is wrong with an element: out of the saved ΔE tolerance before not measured on the photograph before nothing. */
  const trouble = (row) => (row.within_tolerance === false ? {level: 2, kind: 'bad', label: 'outside tolerance'}
    : !row.measured_lab ? {level: 1, kind: 'warn', label: 'not measured'} : {level: 0, kind: 'ok', label: null});
  // how far the element is from what was planned: ΔE to the planned colour, else the distance from the planned colour path
  const deviation = (row) => row.delta_e ?? row.path_distance ?? null;

  /** The elements of the report; the pair keeps the order, filter, search and pages for the session. */
  function elementList(r) {
    const worst = (a, b) => trouble(b).level - trouble(a).level || (deviation(b) ?? -1) - (deviation(a) ?? -1) || a.layer_index - b.layer_index;
    const row = (x) => {
      const lab = x.measured_lab_against_clean || x.measured_lab, t = trouble(x);
      return [lab ? swatch(lab) : null, h('span', {class: 'lst-text', title: x.name || ''}, x.name || `Layer ${x.layer_index}`),
        lab ? h('span', {class: 'muted small'}, labText(lab)) : null,
        x.delta_e != null ? h('span', {class: 'small', title: 'ΔE to planned color'}, `ΔE ${num(x.delta_e, 1)}`)
          : x.path_distance != null ? h('span', {class: 'small', title: 'Deviation from color path'}, `from path ${num(x.path_distance, 1)}`) : null,
        t.label ? pill(t.label, t.kind) : null, x.taken_out ? pill('excluded from calculations by operator', 'warn') : null];
    };
    // a layer the operator took out of every calculation (act-on-findings REQ-001): dimmed, said why, «Restore» on its line
    const takenOut = (x) => h('p', {class: 'small'}, `Excluded from calculations by operator ${new Date(x.taken_out.created_at).toLocaleString('en-US')}`
      + (x.taken_out.note ? ` («${x.taken_out.note}»)` : '') + ': this layer is excluded from the recipe, color map, palette, and works.');
    const giveBack = (x) => btn('Restore', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { await post(`/exclusions/${x.taken_out.id}/revoke`, {}); toast('Layer included again', 'ok'); App.render({preserveScroll: true}); }
      catch (e) { fail(e); self.disabled = false; }
    }, 'btn-small');
    return App.list({id: `analysis-elements:${r.pair_id}`, items: r.rows, key: (x) => x.observation_id ?? x.layer_index, row,
      details: (x) => [x.taken_out ? takenOut(x) : null, detailBody(x, false)], search: (x) => x.name || `Layer ${x.layer_index}`,
      rowClass: (x) => (x.taken_out ? 'excluded' : ''), actions: (x) => (x.taken_out ? [giveBack(x)] : []),
      filters: r.rows.some((x) => trouble(x).level) ? [{key: 'problem', label: 'Result', test: (x, v) => trouble(x).kind === v,
        options: [['bad', 'Outside tolerance'], ['warn', 'Not measured'], ['ok', 'No issues']]}] : [],
      sorts: [['worst', 'Worst first', worst], ['order', 'Original order', (a, b) => a.layer_index - b.layer_index]],
      empty: 'No elements match the search and filters.'});
  }

  function genericDashboard(r) {
    const m = r.metrics || {};
    let values;
    if (m.kind === 'brightness_contrast') values = [[m.bands, 'bands'], [num(m.measured_contrast, 1), 'measured ΔL'],
      [num(m.planned_contrast, 1), 'planned ΔL'], [m.monotonic ? 'Yes' : 'No', 'monotonicity']];
    else if (m.kind === 'delta_e_along_path') values = [[m.bands, 'bands'], [num(m.mean_delta_e, 1), 'mean ΔE'],
      [num(m.max_delta_e, 1), 'maximum ΔE'], [num(m.mean_path_distance, 1), 'distance from path']];
    else if (m.kind === 'color_deviation') values = [[m.layers, 'layers'], [num(m.mean_delta_e, 1), 'mean ΔE'],
      [num(m.max_delta_e, 1), 'maximum ΔE'], [r.tolerance == null ? '—' : num(r.tolerance, 1), 'ΔE tolerance']];
    else values = [[r.rows.length, 'measured layers'], [r.photos?.length || 1, 'run photos'],
      [r.rows.filter((row) => row.measured_lab).length, 'areas with color'], ['—', 'planned color']];
    const ref = r.clean_reference;
    return [h('div', {class: 'analysis-kpi-grid'}, ...values.map(([value, label]) => kpi(value, label))),
      ...(ref ? [h('div', {class: 'alert ok', role: 'status'},
        `Colors are normalized to clean titanium in the same photograph: the cleaning layer was captured at L* ${num(ref.lab[0], 1)} and taken as L* ${num(ref.nominal[0], 0)}`
        + `${ref.nominal_source === 'chart' ? ' (from reference-card measurements)' : ' (default value)'}`
        + (Math.abs(ref.exposure_stops) >= 1 ? `; photo is ${num(Math.abs(ref.exposure_stops), 1)} exposure stops ${ref.exposure_stops > 0 ? 'darker' : 'lighter'} than nominal` : '')
        + '. The color ratio to clean titanium in linear light is independent of exposure; the as-photographed value is preserved as evidence.')] : []),
      ...(r.target_checks?.length ? [targetCard(r.target_checks)] : []),
      card('Measured elements', elementList(r).el),
      r.limitations?.length ? h('details', {class: 'analysis-footnote'}, h('summary', {}, `Measurement limitations (${r.limitations.length})`),
        ...r.limitations.map((text) => h('p', {}, I18N.tr(text)))) : null];
  }

  /** Plate cells made for the target color (REQ-006): measured color, ΔE to target, and verdict using the saved tolerance. */
  function targetCard(checks) {
    const verdict = (c) => (c.within_tolerance == null ? (c.comparable ? 'tolerance not set' : 'not comparable') : c.within_tolerance ? 'within tolerance' : 'outside tolerance');
    return card('Target colors', h('div', {class: 'stack'},
      h('p', {class: 'muted small'}, 'The planner proposed these cells for an unreachable work color; the result is recorded with the target color.'),
      table(['Cell', 'Target', 'Measured', 'ΔE to target', 'ΔE tolerance', 'Result'], checks.map((c) => [c.cell_id,
        h('span', {}, swatch(c.target_lab), labText(c.target_lab)), h('span', {}, swatch(c.measured_lab), labText(c.measured_lab)),
        c.delta_e == null ? '—' : num(c.delta_e, 1), c.tolerance == null ? '—' : num(c.tolerance, 1),
        h('span', {}, pill(verdict(c), c.within_tolerance ? 'ok' : 'warn'), c.note ? h('div', {class: 'muted small'}, I18N.tr(c.note)) : null)]))));
  }

  /** Rig repeatability for photographs of one engraving (REQ-009) contributes stability evidence, not separate engravings. */
  function rigCard(rig) {
    const value = rig?.assessed
      ? `ΔE ${num(rig.mean_delta_e, 2)} on average, up to ${num(rig.max_delta_e, 2)} · photos with reference card: ${rig.photos} · layers compared: ${rig.layers}`
      : 'not assessed';
    return h('div', {class: 'alert', role: 'status'}, h('strong', {}, 'Rig repeatability: '), value,
      h('p', {class: 'muted small'}, 'How much photographs of the same engraving differ. This is available only for repeat photos corrected using a reference card; '
        + 'photos without a card are not compared with one another. A repeat photo is not a separate engraving (DEC-021).'));
  }

  App.register({id: 'analysis', async render(ctx) {
    const id = ctx.arg;
    let r;
    try { r = await get(`/pairs/${id}/report`); }
    catch (e) { return h('div', {class: 'card empty'}, h('h3', {}, 'Report not found'), h('p', {}, e.message), link('/experiments', 'Back to experiments')); }
    const c = r.capability;
    const restored = r.mode === 'Restored from file';      // the plan of an imported work, restored from its file (REQ-005)
    const material = c ? [c.material?.name, c.material?.grade, c.material?.batch].filter(Boolean).join(' · ') : '';
    const device = c?.device?.name;
    const lens = c?.lens?.name;
    const align = {'markers': 'using markers', 'marker templates': 'using marker patterns', manual: 'manual',
      'manual shift': 'manual shift', 'manual rotation': 'manual rotation', 'manual transform': 'scale or mirror',
      'element anchor': 'using an element', 'element anchors': 'using anchor elements', picture: 'using embedded image', geometry: 'using design details',
      'single distinctive detail': 'using one distinctive detail', 'two marker + QR': 'using two markers and QR'}[r.alignment] || 'not specified';
    const revise = btn('Correct alignment', async (ev) => {
      const control = ev.currentTarget; control.disabled = true; control.textContent = 'Creating correction…';
      try { const revision = await post(`/pairs/${id}/alignment-revisions`);
        toast('Correction created from the same RAW; previous measurements remain until the new ones are accepted', 'ok');
        go('/ingest?pair=' + revision.id);
      } catch (error) { control.disabled = false; control.textContent = 'Correct alignment'; fail(error); }
    }, 'btn-small');
    const remeasure = btn('Remeasure', async (ev) => {
      const control = ev.currentTarget; control.disabled = true; control.textContent = 'Remeasuring…';
      const end = App.landing(control);                          // the measuring takes about half a minute: a person who has gone elsewhere is not brought back, the result waits in the task panel
      try {
        const out = await post(`/pairs/${id}/remeasure`);
        if (out.status === 'replaced') {
          if (end.stillHere()) toast('Remeasured with new calculations; the previous measurement was replaced', 'ok');
          end.go('/analysis/' + out.replaced_by, {title: 'Photo remeasured', message: 'Remeasured with new calculations; the previous measurement was replaced. Open the new analysis.',
            openLabel: 'Open analysis', goOptions: {}});
          return;
        }
        toast('Previous measurement retained: ' + I18N.tr(out.reason || ''), 'warn');
        control.disabled = false; control.textContent = 'Remeasure';
      } catch (error) { control.disabled = false; control.textContent = 'Remeasure'; fail(error); }
    }, 'btn-small');
    const remove = btn('Delete check', () => confirmBox('Delete check',
      'The photo and its measurements will be removed from the active database. Measurement history remains for audit, and other checks of the engraving remain.',
      'Delete', async () => { await del(`/pairs/${id}`); toast('Check deleted', 'ok'); go('/experiments'); }), 'btn-small danger');
    return h('div', {class: 'analysis-dashboard'},
      h('div', {class: 'analysis-hero'},
        h('div', {}, h('h2', {}, r.engraving_title || 'Engraving analysis'),
          h('p', {class: 'sub'}, [MODE[r.mode] || 'Engraving', device, lens, material].filter(Boolean).join(' · ')),
          h('p', {class: 'muted small'}, `Check #${id} · alignment ${align}${c?.measurement_modes?.includes('raw_camera_relative') ? ' · RAW without reference card' : ''}`),
          // «pair» and «basis» are the words of this report: said through the task, the number in the details (ux-save-feedback-p0, REQ-003)
          h('div', {class: 'stack kn-terms'}, Terms.note('pair', id), Terms.note('basis'))),
        h('div', {class: 'analysis-actions'}, link('/experiment/' + (r.plan_id && !restored ? 'plan-' + r.plan_id : 'eng-' + r.engraving_id), 'Back to experiment'),
          r.plan_id ? (r.mode === 'Photo engraving work' ? link('/photo-engraving?work=' + r.plan_id, 'Photo engraving work')
            : link('/plans/' + r.plan_id, restored ? 'Restored plan' : 'Plate')) : null,
          r.proposal ? link(`/designer?device=${r.proposal.device_id}&lens=${App.lensParam(r.proposal.lens_id)}&proposal=${r.proposal.id}`, `Proposal #${r.proposal.id}`) : null,
          link('/ingest?rephoto=' + id, '+ Photo'), remeasure, revise, remove)),
      r.photos?.length > 1 ? h('div', {class: 'analysis-photo-strip'},
        h('span', {}, `Checks for this run (${r.photos.length})`),
        ...r.photos.map((photo) => link(photo.status === 'Accepted' ? '/analysis/' + photo.id : '/ingest?pair=' + photo.id,
          `№${photo.id} · ${photo.photo_name}${photo.id === Number(id) ? ' · current' : ''}`))) : null,
      r.photos?.length > 1 ? rigCard(r.rig_repeatability) : null,
      VectorReview.reportCard(r.work_review),
      ...(c ? capabilityDashboard(r) : genericDashboard(r)));
  }});
})();
