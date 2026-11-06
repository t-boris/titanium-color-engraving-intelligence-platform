/* Engraving plan, layers, predictions, markers, and LightBurn export. */
'use strict';
(() => {
  const {h, btn, link, pill, get, put, del, toast, fail, go, confirmBox, num, labText, swatch, facts} = App;
  const MODE = {'Calibration plate': 'Calibration plate', 'Laser capability test': 'Laser capability test', 'Discrete color engraving': 'Color engraving', 'Tonal photo engraving': 'Tonal photo engraving',
    'Color-path photo engraving': 'Color-path photo engraving', 'Restored from file': 'Restored from file', 'Vector job': 'Vector work'};
  const PICTURED = ['Discrete color engraving', 'Tonal photo engraving', 'Color-path photo engraving'];
  const STATUS = {Draft: 'Draft', 'Ready to export': 'Ready to export', Exported: 'Exported',
    Superseded: 'Superseded by a new test', Cancelled: 'Cancelled', Restored: 'Completed job record'};
  const STAGE = {measured: 'Measured', candidate: 'Candidate', repeated: 'Repeated', validated: 'Validated', production: 'Production'};

  /** Datasheet estimate, not a measurement: pulse energy and a below-cutoff warning. */
  function operating(l) {
    const o = l.operating_point;
    if (!o) return '';
    const energy = o.pulse_energy_mj == null ? '' : ` · ${+o.pulse_energy_mj.toPrecision(3)} mJ`;
    return h('div', {class: 'muted small', title: 'Estimated from the laser datasheet; not measured'}, `≈ ${+o.output_power_w.toPrecision(3)} W${energy}`,
      o.below_cutoff ? [' ', pill('below cutoff: ' + Math.round(o.power_factor * 100) + '% power', 'warn')] : '');
  }

  /** The parameters of a layer as LightBurn engraves it: power, frequency, speed, pulse, fill interval and passes; the way of the fill, its
      angle, global passes and wobble under them, then the datasheet estimate. */
  function layerParams(p, l) {
    const recipe = l.parameters.layer_type != null;           // a knowledge entry: the LightBurn mode and settings come from its file
    const s = l.lightburn_settings || p.lightburn_settings || (recipe ? l.parameters : {});
    const mode = l.cut_type || l.parameters.layer_type;
    const offset = mode === 'OffsetFill' || mode === 'Offset Fill';
    const hatch = s.cross_hatch ? 'cross-hatch' : s.bidirectional === false ? 'unidirectional' : 'bidirectional';
    const interval = mode === 'Cut' && l.parameters.line_interval == null ? 'fill interval does not apply' : `fill interval ${num(l.parameters.line_interval, 4)} mm`;
    const engravingMode = mode === 'Cut' ? 'Vector line (Line mode)' : offset ? 'Offset Fill' : `Fill: ${hatch}`;
    const wobble = s.wobble_enabled ? `Wobble: diameter ${num(s.wobble_size, 3)} mm · interval ${num(s.wobble_step, 3)} mm`
      : s.wobble_size === 0 ? 'Wobble: off' : '';
    return h('div', {}, `${num(l.parameters.power, 1)} % · ${num(l.parameters.frequency, 1)} kHz · ${num(l.parameters.speed, 0)} mm/s · Q-Pulse ${num(l.parameters.pulse_width, 0)} ns · ${interval} · ${l.parameters.passes} passes`,
      h('div', {class: 'muted small'}, engravingMode, offset ? '' : `, angle ${s.scan_angle ?? 0}°, increment ${s.angle_increment ?? 0}°`, `, global passes ${s.global_passes ?? 1}`, wobble ? ` · ${wobble}` : '',
        recipe ? ' · other LightBurn settings match the measured file' : ''), operating(l));
  }

  const regionCount = (l) => (l.region_ids ? l.region_ids.length : l.region_count);

  /** A colour layer on one line: its predicted colour, name, expected error, stage and areas; a laser below its cutoff is said at once. */
  function layerRow(l) {
    const pr = l.prediction;
    return [pr ? swatch(pr.lab) : null, h('span', {class: 'lst-text'}, l.name),
      pr ? h('span', {class: 'small', title: 'Expected ΔE error'}, `ΔE ${num(pr.expected_delta_e)}`) : null,
      l.stage ? h('span', {class: 'muted small'}, STAGE[l.stage]) : null, l.questioned ? pill('questioned', 'bad') : null,
      l.operating_point && l.operating_point.below_cutoff ? pill('below cutoff', 'warn') : null,
      h('span', {class: 'muted small'}, `regions ${regionCount(l)}`)];
  }

  /** What a colour layer's line opens: its parameters and LightBurn settings, the predicted colour with its confidence, error and stability. */
  function layerDetails(p, l) {
    const pr = l.prediction;
    return h('div', {class: 'stack small'}, layerParams(p, l),
      facts([['Predicted color', pr ? h('span', {}, swatch(pr.lab), ' ', labText(pr.lab)) : '—'], ['Confidence', pr ? num(pr.confidence) : '—'],
        ['Expected ΔE error', pr ? num(pr.expected_delta_e) : '—'],
        ['Stability', pr ? (pr.stability.assessed ? 'variance ' + num(pr.stability.variance) : 'not assessed') : '—'],
        ['Stage', l.stage ? h('span', {}, STAGE[l.stage], l.questioned ? [' ', pill('questioned', 'bad')] : '') : '—'], ['Regions', String(regionCount(l))]]),
      // the words of the line, explained through what the person is doing (ux-save-feedback-p0, REQ-003); the layer's recipe is a knowledge entry
      l.stage ? h('div', {class: 'stack kn-terms'}, Terms.note('stage'), l.parameters && l.parameters.layer_type != null ? Terms.note('knowledge') : null, pr ? Terms.note('basis') : null) : null);
  }

  /** The photo zones of a vector work (REQ-073): an Image layer each, after the colour layers - the work's picture engraved in the zone's
      kind on its scale, transparent outside the zone; the picture is what the zone is predicted to look like. On one line: the picture,
      the layer, the zone and its kind, or that it cannot be engraved. */
  function zoneRow(z) {
    return [z.picture ? h('img', {class: 'vw-ed-zone-chip', src: z.picture, alt: ''}) : null, h('span', {class: 'lst-text'}, z.name || `Photo zone ${z.number}`),
      h('span', {class: 'muted small'}, `Photo zone ${z.number} · ${VectorPhoto.kindName(z.kind)}`), z.parameters ? null : pill('cannot be engraved', 'bad'),
      h('span', {class: 'muted small'}, `regions ${z.regions.length}`)];
  }

  /** What a photo zone's line opens: its powers and settings and how its greys are chosen, or why it cannot be engraved; its picture. */
  function zoneDetails(z) {
    const s = z.parameters, kind = VectorPhoto.kindName(z.kind);
    const powers = !s ? '' : z.kind === 'grayscale' ? `Min ${num(s.min_power, 1)} % – Max ${num(s.power, 1)} %` : `dots ${num(s.power, 1)} %`;
    return h('div', {class: 'stack small'},
      s ? h('div', {}, `${powers} · ${num(s.frequency, 1)} kHz · ${num(s.speed, 0)} mm/s · Q-Pulse ${num(s.pulse_width, 0)} ns · line interval ${num(s.line_interval, 4)} mm · ${s.passes} passes`,
        h('div', {class: 'muted small'}, [`Image layer, “${kind}” mode: the work image inside the zone and transparent outside`,
          VectorPhoto.greysText(z)].filter(Boolean).join('; ')))
        : h('div', {class: 'alert bad small'}, I18N.tr(z.problem)),
      z.picture ? h('img', {class: 'plan-zone-pic', src: z.picture, alt: `Photo zone ${z.number}`}) : null);
  }

  /** The layers of the plan and then its photo zones as a short list (DEC-090): one line each, in the order of the file; the parameters,
      the LightBurn settings and the prediction open under a line. Sorted by the file's order, the larger expected error or the more areas. */
  function layerList(p) {
    const items = [...p.layers.map((layer) => ({layer})), ...(p.photo_zones || []).map((zone) => ({zone}))].map((x, pos) => ({...x, pos}));
    const areas = (x) => (x.layer ? regionCount(x.layer) : x.zone.regions.length);
    const error = (x) => (x.layer && x.layer.prediction ? x.layer.prediction.expected_delta_e ?? -1 : -1);
    return App.list({items, id: 'plan.layers', key: (x) => (x.layer ? `layer:${x.pos}` : `zone:${x.zone.number}`),
      row: (x) => (x.layer ? layerRow(x.layer) : zoneRow(x.zone)),
      details: (x) => (x.layer ? layerDetails(p, x.layer) : zoneDetails(x.zone)),
      search: items.length > 20 ? (x) => (x.layer ? x.layer.name : `${x.zone.name || ''} Photo zone ${x.zone.number}`) : null,
      sorts: [['order', 'Layer order', (a, b) => a.pos - b.pos], ['error', 'Largest ΔE error first', (a, b) => error(b) - error(a) || a.pos - b.pos],
        ['areas', 'Most regions first', (a, b) => areas(b) - areas(a) || a.pos - b.pos]]});
  }

  /** Show the source alongside predicted colors before export. */
  function banding(p) {
    if (!PICTURED.includes(p.mode)) return null;
    const discrete = p.mode === 'Discrete color engraving';
    return h('div', {class: 'card stack'}, h('h3', {}, discrete ? 'Plan colors' : `Plan bands: ${p.band_count}`),
      h('div', {class: 'grid g2'},
        h('figure', {}, h('img', {src: `/api/plans/${p.id}/source-image`, style: 'width:100%', alt: 'Source image'}), h('figcaption', {class: 'muted small'}, 'Source image')),
        h('figure', {}, h('img', {src: `/api/plans/${p.id}/banding.png`, style: 'width:100%;image-rendering:pixelated', alt: discrete ? 'Plan colors' : 'Bands in predicted colors'}),
          h('figcaption', {class: 'muted small'}, discrete ? 'Matched titanium colors; unreachable colors are hatched red and excluded colors are white'
            : 'Each band shows the predicted color of its measured settings'))));
  }

  App.register({id: 'plan', async render(ctx) {
    let p;
    try { p = await get('/plans/' + ctx.arg); } catch (e) { return h('div', {class: 'card empty'}, h('h3', {}, 'Engraving plan not found'), link('/experiments', 'Back to experiments')); }
    const draft = p.status === 'Draft';
    const vector = p.mode === 'Vector job';
    // a plan restored from an imported file records the job that was engraved: never exported, nothing to add to it (REQ-005)
    const restored = p.mode === 'Restored from file';
    // ... it is the record of a finished work, so its experiment is that of the work's engraving (REQ-041)
    const work = restored ? await get('/pairs/' + p.restored.pair_id).catch(() => null) : null;
    // a vector work nobody has photographed is not an experiment yet (REQ-044, DEC-082)
    const toExperiment = !restored ? (vector && !p.active_pairs ? null : link('/experiment/plan-' + p.id, 'Open experiment'))
      : work && work.status !== 'Deleted' ? link('/experiment/eng-' + encodeURIComponent(work.engraving_id), 'Open experiment') : null;
    const [editRoute, editLabel] = p.mode === 'Discrete color engraving' ? ['/artwork?plan=' + p.id, 'Edit conversion']
      : p.mode.includes('photo engraving') ? ['/photo?plan=' + p.id, 'Correct: create a new plan from this'] : vector ? ['/vector?plan=' + p.id, 'Open vector work'] : [null, null];
    // the one place a plan's file is made: the chain of its life, whether it can be made now, «Download LightBurn» and the files made before
    const exportCard = restored ? null : Lifecycle.exportCard(p.lifecycle, {path: `/plans/${p.id}/export.lbrn2`, name: p.name.replace(/[^\w.-]+/g, '_') + '.lbrn2',
      reload: () => App.render({preserveScroll: true}), designer: p.device_id ? `/designer?device=${p.device_id}&lens=${App.lensParam(p.lens_id)}` : null});
    const warnings = (p.warnings || []).map((w) => PhotoForm.questionedWarning(w));
    const markers = p.markers_enabled ? 'enabled' : 'disabled';
    const toggle = ['Calibration plate', 'Laser capability test', 'Restored from file'].includes(p.mode) ? null : btn(p.markers_enabled ? 'Disable registration markers' : 'Enable registration markers', async () => {
      try { await put(`/plans/${p.id}/markers`, {enabled: !p.markers_enabled}); App.render(); } catch (e) { fail(e); }
    });
    const exp = p.experiment || {};
    const mat = exp.material || {};
    const materialLabel = [mat.name, mat.grade, mat.batch && `batch ${mat.batch}`].filter(Boolean).join(' · ');
    // REQ-018: an unknown work field leaves the placement unchecked, and the plate says so
    const field = p.work_field || (exp.summary || {}).work_field;
    const fieldLabel = !field ? null : field.checked ? `fits: ${num(field.needed_mm.width, 0)} × ${num(field.needed_mm.height, 0)} mm in field ${num(field.field_mm.width, 0)} × ${num(field.field_mm.height, 0)} mm`
      : 'lens field is unknown; placement was not checked';
    const clean = p.clean_layer;
    const cleanLabel = clean ? `${num(clean.power, 1)} % · ${num(clean.frequency, 0)} kHz · ${num(clean.speed, 0)} mm/s · Q-Pulse ${num(clean.pulse_width, 0)} ns · interval ${num(clean.interval ?? clean.line_interval, 3)} mm · ${clean.passes ?? 1} pass · ${clean.cross_hatch ? 'cross-hatch fill' : clean.bidirectional ? 'bidirectional fill' : 'unidirectional fill'}` : 'C00 is the first LightBurn layer';
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, I18N.name(p.name)), h('p', {class: 'sub'}, `${MODE[p.mode] || p.mode} · ${STATUS[p.status] || p.status}`)), h('span', {class: 'spacer'}), toExperiment, restored ? link('/ingest?pair=' + p.restored.pair_id, 'Open work photo') : null,
        editRoute ? link(editRoute, editLabel) : null,
        // the plan of a vector work is the work itself: it is deleted only in «Vector work», with its own confirmation (DEC-082)
        vector ? null : btn('Delete test', () => confirmBox('Delete test', p.active_pairs
          ? `Delete the plate and its ${p.active_pairs} checks? Uploaded RAW and LightBurn copies will be deleted. Measurement history remains but will no longer influence recommendations.`
          : 'The plate will be removed from the experiment list. Measurement history will remain.', 'Delete test', async () => {
            // each check leaves active use on its own (its knowledge is rebuilt); then the plan has only archived checks (DEC-047)
            if (p.active_pairs) for (const pair of (await get('/pairs')).filter((x) => x.plan_id === p.id)) await del('/pairs/' + pair.id);
            await del(`/plans/${p.id}`);
            toast('Test removed from active experiments', 'ok'); go('/experiments');
          }), 'danger')),
      draft ? h('div', {class: 'alert warn'}, vector ? [p.strategy === 'photo' ? 'Some colors lack a titanium match within tolerance; export is unavailable. '
        : 'Some regions lack sufficient data; export is unavailable. ', link('/vector?plan=' + p.id, 'Open vector work')]
        : 'Complete the conversion before exporting this plan.') : null,
      p.revision_of ? h('div', {class: 'alert ok'}, 'Plan correction ', link('/plans/' + p.revision_of, '#' + p.revision_of), '; the original plan is unchanged.') : null,
      restored ? h('div', {class: 'alert'}, `Plan restored from imported file “${p.restored.lightburn_name}”: layers, settings, and fill geometry come from the file; `
        + 'the planned layer color is the knowledge prediction at restoration, if available. This records a completed job; export is unavailable.') : null,
      ['Superseded', 'Cancelled'].includes(p.status) ? h('div', {class: 'alert warn'},
        'This plate is no longer current for engraving. Its settings remain in the research history.') : null, ...warnings,
      h('div', {class: 'card stack'}, facts([['Identifier', p.plan_identifier], ['Bands', p.band_count], ['Size, mm', p.size_mm ? `${num(p.size_mm.width, 1)} × ${num(p.size_mm.height, 1)}` : null],
        ['Plate type', exp.test_name], ['Laser', exp.device?.title || exp.device?.name], ['Lens', exp.lens || p.lens ? App.lensLabel(exp.lens || p.lens) : p.lens_id == null ? 'unknown' : null],
        ['Titanium', materialLabel], ['Work field', fieldLabel], ['Cleaning is the first layer C00', cleanLabel],
        ['Labels and markers', markers + (['Calibration plate', 'Laser capability test'].includes(p.mode) ? ' · layer C01, ArUco + QR ID' : '')]]),
        exp.test_description ? h('p', {class: 'muted small'}, exp.test_description) : null,
        p.time ? App.timeBlock(p.time) : null,
        h('p', {class: 'muted small'}, 'Cleaning is the first layer C00.'), toggle ? h('div', {class: 'row'}, toggle) : null),
      exportCard ? h('div', {class: 'card'}, exportCard) : null,
      banding(p),
      h('div', {class: 'card'}, h('h3', {}, 'Layers and settings'), p.layers.length || (p.photo_zones || []).length
        ? layerList(p).el
        : h('p', {class: 'muted'}, 'No layers: export is unavailable.')),
      restored ? null : h('div', {class: 'card'}, h('h3', {}, 'Engraving result'), h('p', {class: 'muted small'}, 'After engraving, add the LightBurn file actually used and a RAW photo, and select the laser, lens, and titanium stock. Plate markers help align the photo with the file.'),
        link('/ingest?plan=' + p.id, 'Add engraving result')));
  }});
})();
