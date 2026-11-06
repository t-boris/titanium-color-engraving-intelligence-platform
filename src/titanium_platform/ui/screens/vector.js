/* Vector work: trace an image, match measured recipes, and export a LightBurn file. */
'use strict';
(() => {
  const {h, fill, btn, field, link, pill, get, post, put, form, toast, fail, go, modal, table, num, labText, swatch, facts} = App;
  const STRATEGIES = [['photo', 'Photo: color regions'], ['fill', 'Silhouette fill'], ['text', 'Text'], ['line', 'Lines (centerline)']];
  const STRATEGY_NAME = {...Object.fromEntries(STRATEGIES), color: 'Color regions (tracing)'};
  const DETAIL = [['coarse', 'Coarse'], ['medium', 'Medium'], ['fine', 'Fine']];
  const TASKS = [['color', 'Color'], ['fill', 'Fill'], ['text', 'Text'], ['line', 'Line'], ['tonal', 'Tone']];
  const STATUS = {matched: ['Recipe available', 'ok'], chosen: ['Recipe selected manually', 'ok'], weak: ['Insufficient data', 'bad'], excluded: ['No recipe: excluded', '']};
  const WEAK_FIRST = {weak: 0, excluded: 1, chosen: 2, matched: 3};             // «Missing data first»: what still keeps the file from export first
  const MODE = {Scan: 'fill (Fill)', Cut: 'line (Line)', OffsetFill: 'outline fill (Offset Fill)', 'Offset Fill': 'outline fill (Offset Fill)'};
  const OPS = {trace: 'image tracing', set_task: 'region task', set_layer: 'region settings group', delete: 'region deletion',
    merge: 'merge regions', set_tolerance: 'outline precision', revert: 'restore version', set_settings: 'group settings',
    exclude: 'exclude region', include: 'restore excluded region', set_threshold: 'ΔE threshold', allow_questioned: 'questioned settings',
    to_designer: 'color sent to planner', copy: 'copy of another work'};
  const DOCUMENT_OPS = ['trace', 'set_task', 'set_layer', 'delete', 'merge', 'set_tolerance', 'revert'];
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 1)} kHz · ${num(p.speed, 0)} mm/s · Q-Pulse ${num(p.pulse_width, 0)} ns`
    + (p.line_interval == null ? '' : ` · interval ${num(p.line_interval, 3)} mm`) + ` · ${p.passes ?? 1} passes`;
  const stability = (s) => (s.assessed ? 'variance ' + num(s.variance) : 'stability not assessed');
  const material = (m) => [m.name, m.grade, m.batch && `batch ${m.batch}`].filter(Boolean).join(' · ');
  const svgSrc = (svg) => 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);

  function startForm(lists, ctx) {
    const pick = App.laserLensPicker(lists, {device: ctx.query.device, lens: ctx.query.lens, onChange: () => { loadPalette(); loadRules(); }});
    const f = Forms.create();
    const Q = Forms.QUANTITIES;
    // the titanium is one concrete record chosen by a search among the records used last, never from a list of all (ux-growing-collections-p0, REQ-001);
    // it starts with the workshop's last choice (ux-work-creation-p0) and else with the record used last
    const stock = MaterialPicker.create({value: ctx.start && ctx.start.material != null ? ctx.start.material : undefined, initial: 'recent', name: 'Titanium',
      onChange: () => loadPalette()});
    // feature electron, REQ-085: a photograph work may take its colours from a connected laboratory release instead of the own measurements;
    // the own measurements are the default, a laboratory is never chosen for the operator
    const source = LabSource.picker('vector', {onChange: () => loadPalette()});
    const img = h('input', {type: 'file', accept: 'image/*'});
    const name = h('input', {placeholder: 'Work name'}), width = Forms.numberInput(Q.workWidth, {value: 60});
    const strategy = h('select', {}, STRATEGIES.map(([id, label]) => h('option', {value: id}, label)));
    const colours = Forms.numberInput(Q.photoColours, {value: 12});
    const detail = h('select', {}, DETAIL.map(([v, l]) => h('option', {value: v, selected: v === 'medium'}, l)));
    const algorithm = VectorSplit.picker('slic');
    algorithm.hint.setAttribute('style', 'grid-column:1 / -1');
    const faces = h('input', {type: 'checkbox', checked: true});
    const maxTime = Forms.numberInput(Q.maxTime, {placeholder: 'no limit'});
    const asShot = h('input', {type: 'checkbox'});
    const thr = Forms.numberInput(Q.deltaE, {placeholder: 'from rules'});
    // the delta E tolerance is never invented (conversion._threshold): the form shows at once whether the rules of the laser and lens hold one,
    // and a tolerance typed while they hold none is saved to them, once («Remember», on by default)
    const thrHint = h('span', {class: 'small muted'});
    const remember = h('input', {type: 'checkbox', checked: true});
    const rememberRow = h('label', {class: 'row small', hidden: true}, remember, h('span', {}, 'Remember for this laser and lens'));
    let savedTolerance;                                   // in the rules: a number, null when none is saved, undefined while not known
    const grey = Forms.numberInput(Q.greyThreshold, {placeholder: 'auto (Otsu)'});
    const tolerance = Forms.numberInput(Q.vectorTolerance, {value: 0.08});
    const markers = h('input', {type: 'checkbox'}), clean = h('input', {type: 'checkbox', checked: true});
    // REQ-020: the main work task follows the strategy until the operator chooses another; each region has its own task
    const STRATEGY_TASK = {photo: 'color_image', fill: 'fill', text: 'text', line: 'line'};
    const task = Tasks.chooser(STRATEGY_TASK[strategy.value], {hint: 'main work task; each region task can be changed after tracing'});
    const info = h('div', {});
    // the fields of the form: each says what it is, whether it is required, its unit and its permitted values (from the server's own rules), and a wrong one
    // says why beside itself; the form keeps everything typed (ux-save-feedback-p0, REQ-003)
    const phoPhoto = () => strategy.value === 'photo';
    // a field of the group that is not shown (the photograph's or the tracing's) is not read: it cannot be wrong where it cannot be seen
    const onlyPhoto = (read) => () => (phoPhoto() ? read() : {ok: true, value: null});
    const onlyTrace = (read) => () => (phoPhoto() ? {ok: true, value: null} : read());
    const laserField = f.add('laser', 'Laser', pick.laser, {required: true,
      read: () => (pick.deviceId() ? {ok: true, value: pick.deviceId()} : {ok: false, message: 'Select a laser'})});
    const lensField = f.add('lens', 'Lens', pick.lens, {help: 'colors and recipes are measurements from this laser and lens', read: () => ({ok: true, value: pick.lensValue()})});
    const imageField = f.add('image', 'Image', App.filePick(img, 'Choose image'), {required: true,
      read: () => (img.files[0] ? {ok: true, value: img.files[0]} : {ok: false, message: 'Add an image for the vector work'})});
    const nameField = f.add('name', 'Work name', name, {required: true});               // conversion: «give the plan a name»
    const widthField = f.add('width', 'Work width', width, {quantity: 'workWidth', required: true});
    const strategyField = f.add('strategy', 'Strategy', strategy, {required: true, help: 'photo uses color regions from the image; fill, text and lines use the dark silhouette'});
    const stockHint = h('span', {class: 'small muted'});      // «Photo» takes every plate of this grade (palette.vector_palette), the others this plate only
    const stockField = f.add('material', 'Titanium', stock, {required: true, help: stockHint,
      read: () => (stock.value ? {ok: true, value: stock.value} : {ok: false, message: 'Select titanium'})});
    // the tolerance is required only while the rules of the laser and lens hold none (conversion._threshold)
    const thrField = f.add('threshold', 'ΔE tolerance', thr, {quantity: 'deltaE', help: thrHint,
      read: () => (thr.value === '' ? (savedTolerance === null ? {ok: false, message: 'Set a ΔE tolerance: none is saved for this laser and lens'} : {ok: true, value: null})
        : Forms.readNumber(thr, Q.deltaE, {}))});
    const tolLabelText = () => (phoPhoto() ? 'Boundary smoothing' : 'Outline precision');
    const toleranceField = f.add('tolerance', tolLabelText(), tolerance, {quantity: 'vectorTolerance', required: true});
    const coloursField = f.add('colours', 'Number of colors', colours, {quantity: 'photoColours', required: true, constraint: '', help: '2–29, or 2–28 with markers: cleaning is the first layer',
      read: onlyPhoto(() => Forms.readNumber(colours, {...Q.photoColours, max: markers.checked ? 28 : 29}, {required: true}))});
    const detailField = f.add('detail', 'Detail', detail, {required: true, help: 'coarse produces larger, simpler regions; fine produces smaller regions',
      read: onlyPhoto(() => ({ok: true, value: detail.value}))});
    const algorithmField = f.add('algorithm', 'Segmentation algorithm', algorithm.select, {required: true, read: onlyPhoto(() => ({ok: true, value: algorithm.select.value}))});
    const maxTimeField = f.add('max_time', 'Maximum engraving time', maxTime, {quantity: 'maxTime', help: 'leave empty for no limit; slow colors are excluded automatically',
      read: onlyPhoto(() => Forms.readNumber(maxTime, Q.maxTime, {}))});
    const greyField = f.add('grey', 'Gray threshold', grey, {quantity: 'greyThreshold', help: 'leave empty for automatic', read: onlyTrace(() => Forms.readNumber(grey, Q.greyThreshold, {}))});
    // photo and tracing fields follow the strategy; photo cleaning is always first (DEC-073)
    const photoFields = h('div', {class: 'grid g2'}, algorithmField, coloursField,
      algorithm.hint, detailField,
      maxTimeField,
      h('label', {class: 'row'}, faces, h('span', {}, 'Detect faces: eyes and lips receive finer segmentation')),
      h('label', {class: 'row'}, asShot, h('span', {}, 'Include unreferenced colors (photographed without a reference or clean titanium)')));
    const traceFields = h('div', {class: 'grid g2'}, greyField,
      h('label', {class: 'row'}, clean, h('span', {}, 'Clean as the first layer (C00)')));
    const photo = phoPhoto;
    const switchFields = () => {
      photoFields.hidden = !photo(); traceFields.hidden = photo(); source.el.hidden = !photo();
      toleranceField.firstChild.textContent = tolLabelText();
      stockHint.textContent = photo() ? 'colors are measurements of this titanium grade from any plate'
        : 'recipes are limited to those measured on this stock';
      tolerance.value = photo() ? 0.08 : 0.05;
      colours.max = markers.checked ? '28' : '29';
      task.set(STRATEGY_TASK[strategy.value]);
      loadPalette();
    };
    strategy.addEventListener('change', switchFields);
    markers.addEventListener('change', () => { colours.max = markers.checked ? '28' : '29'; });

    async function loadPalette() {
      if (!stock.value) return fill(info);
      if (photo()) {
        const src = source.value(), asked = JSON.stringify(src);
        let p;
        try { p = src ? await post('/labs/palette', src) : await get(`/vector-palette?${pick.query()}&material_id=${stock.value}`); }
        catch (e) { return fill(info, h('p', {class: 'alert bad'}, e.message)); }
        if (asked !== JSON.stringify(source.value())) return;      // the source changed meanwhile
        const asShotCount = p.entries.filter((e) => e.basis === 'as-shot').length;
        const whose = src ? `laboratory “${p.source.lab_name}” (${LabSource.releaseName(p.source)}; ${LabSource.setupName(p.source)})`
          : 'this laser, lens, and titanium grade (from any plate)';
        return fill(info, p.entries.length
          ? h('p', {class: 'muted small'}, `Measured fill colors for ${whose}: ${p.entries.length}`,
            asShotCount ? `, without reference: ${asShotCount}` : '', '. Each image color receives the fastest color within the ΔE tolerance.',
            src && p.conditions && p.conditions.length ? ' ' + p.conditions.map((c) => I18N.tr(c)).join(' ') : '')
          : h('div', {class: 'alert warn'}, `No measured fill colors are available for ${whose}: segmentation is possible, but colors cannot be assigned.`));
      }
      let palette;
      try { palette = await get(`/vector/palette?${pick.query()}&material_id=${stock.value}`); } catch (e) { return fill(info, h('p', {class: 'alert bad'}, e.message)); }
      const lines = palette.filter((e) => e.mode === 'Cut').length;
      fill(info, palette.length
        ? h('p', {class: 'muted small'}, `Recipes for this laser, lens, and titanium: ${palette.length} (fill: ${palette.length - lines}, line: ${lines}). `,
          'Regions without a recipe will be marked and can be sent to the experiment planner.')
        : h('div', {class: 'alert warn'}, 'No validated or production recipes exist for this laser, lens, and titanium: all regions will lack data. ',
          link(`/designer?${pick.route()}`, 'Experiment planner')));
    }
    async function loadRules() {
      const asked = pick.query();
      let rules = null;
      try { rules = await get('/rules?' + asked); } catch (_) { rules = null; }
      if (asked !== pick.query()) return;                // the laser or the lens changed meanwhile
      savedTolerance = rules ? rules.delta_tolerance : undefined;
      showTolerance();
    }
    function showTolerance() {
      const none = savedTolerance === null, de = savedTolerance == null ? '' : String(+(+savedTolerance).toFixed(2));   // 5, not 5.00
      thr.setAttribute('placeholder', savedTolerance != null ? `from rules: ${de}` : none ? 'enter value' : 'from rules');
      thr.setAttribute('aria-invalid', none && thr.value === '' ? 'true' : 'false');
      rememberRow.hidden = !none;
      fill(thrHint, savedTolerance != null
        ? `leave empty for ΔE ${de} from this laser and lens rules; an entered value applies only to this work`
        : none ? 'No tolerance is saved for this laser and lens; enter one. The fastest color within the tolerance is chosen; ΔE 1 is barely noticeable, '
          + '2–3 is small, and 5 still matches two engravings of the same recipe.'
          : 'leave empty for the tolerance from this laser and lens rules');
    }
    thr.addEventListener('input', showTolerance);

    const submit = btn('Create work', async (ev) => {
      const v = f.collect();
      if (!v) return;                                                // every wrong box says why beside itself; the dialog of the work keeps all that was typed
      if (!task.check()) return f.fail(new Error('Task targets are invalid: correct the marked fields'));
      const fd = new FormData();
      fd.append('device_id', v.laser); fd.append('lens_id', v.lens); fd.append('material_id', v.material); fd.append('name', v.name);
      fd.append('width_mm', v.width); fd.append('strategy', v.strategy); fd.append('tolerance_mm', v.tolerance);
      fd.append('markers', markers.checked); fd.append('image', v.image);
      if (v.threshold != null) fd.append('threshold', v.threshold);
      task.append(fd);
      if (photo()) {
        fd.append('n_colors', v.colours); fd.append('algorithm', v.algorithm); fd.append('detail', v.detail); fd.append('faces', faces.checked); fd.append('include_as_shot', asShot.checked);
        if (v.max_time != null) fd.append('max_time', v.max_time);
        if (source.value()) fd.append('source', JSON.stringify(source.value()));
      } else {
        fd.append('clean', clean.checked);
        if (v.grey != null) fd.append('grey_threshold', v.grey);
      }
      const self = ev.currentTarget;
      const end = App.landing(self);
      self.disabled = true;
      if (v.threshold != null && savedTolerance === null && remember.checked) {
        try {
          await put('/rules', {device_id: pick.deviceId(), lens_id: pick.lensId(), delta_tolerance: v.threshold});
          savedTolerance = v.threshold;
          showTolerance();
        } catch (e) { self.disabled = false; return f.fail(e); }
      }
      try {
        const j = await form('/vector', fd);
        App.rememberContext({device: pick.deviceId(), lens: pick.lensId(), material: stock.value, source: photo() ? source.value() : undefined});
        if (end.stillHere()) toast('Vector work created', 'ok');
        end.go('/vector?plan=' + j.id, {title: 'Vector work created', message: `Work “${v.name}” created. Open it to review regions and export a LightBurn file.`, openLabel: 'Open work', goOptions: {}});
      } catch (e) { f.fail(e); self.disabled = false; }
    }, 'primary');
    switchFields();
    loadRules();
    // ux-work-creation-p0, REQ-001: the shared choice is changed from here by the dialog of the creation screen (it shows what the change makes
    // unavailable before «Apply»); the source of measurements stays this form's own picker, so the dialog leaves it out
    const shared = ctx.start && ctx.start.context ? WorkContext.strip(ctx.start.context, {heading: 'Workshop selection', source: false, onChange: (c) => {
      pick.setDevice(c.device_id, c.lens_id == null ? 'unknown' : c.lens_id);
      if (c.material_id != null) stock.value = String(c.material_id);
      loadPalette(); loadRules();
    }}) : null;
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'New vector work'), h('p', {class: 'sub'}, 'Photos are divided into regions colored with measured titanium colors; fill, text, and lines are traced from the silhouette. The result is a standard LightBurn file.')), h('span', {class: 'spacer'}), h('a', {class: 'btn btn-small', href: '#/vector'}, '← My works')),
      shared ? shared.el : null,
      h('div', {class: 'card stack'}, h('div', {class: 'grid g2'},
        laserField, lensField, stockField, source.el, imageField,
        nameField, widthField, strategyField,
        h('div', {class: 'f'}, thrField, rememberRow),
        toleranceField),
        photoFields, traceFields, task.el,
        h('label', {class: 'row'}, markers, h('span', {}, 'Registration markers and identifier outside the image')),
        info, f.error, submit));
  }

  function settingsDialog(j, group, run) {
    const byId = Object.fromEntries(j.palette.map((e) => [e.id, e]));
    let chosen = group.chosen ? group.knowledge_id : null;
    const option = (value, label, extra) => h('label', {class: 'row'}, h('input', {type: 'radio', name: 'settings', checked: chosen === value, onChange: () => { chosen = value; }}), label, extra);
    const rows = [option(null, 'Closest suitable recipe (automatic)')].concat(group.candidates.map((c) => {
      const e = byId[c.knowledge_id];
      return option(e.id, h('span', {}, swatch(e.lab), `K${e.id} · ${MODE[e.mode] || e.mode || 'mode not recorded'}`),
        h('span', {class: 'muted small'}, `${params(e.parameters)} · distance ${num(c.distance)} · expected ΔE error ${num(e.expected_delta_e)} · confidence ${num(e.confidence)}`));
    }));
    const place = Forms.notice({what: 'Choose settings', kept: 'The group retains its previous settings.'});
    modal(`Settings for group “${group.key}”`, h('div', {class: 'stack'},
      h('p', {}, 'Only validated and production recipes for this laser, lens, and titanium whose LightBurn mode matches the group task.'),
      group.candidates.length ? rows : h('p', {class: 'alert warn'}, 'No suitable recipes: the group regions will remain without data.'), place.error), [
      {label: 'Cancel', run: (x) => x.close()},
      {label: 'Apply', cls: 'primary', run: async (x) => { if (await run({op: 'set_settings', group: group.key, knowledge_id: chosen}, place)) x.close(); }}]);
  }

  /** Summarize regions without data; show their identifiers on demand. */
  function weakSummary(weak) {
    const ids = h('p', {class: 'small', hidden: true}, weak.join(', '));
    const toggle = btn('show', () => { ids.hidden = !ids.hidden; toggle.textContent = ids.hidden ? 'show' : 'hide'; });
    return h('div', {class: 'alert bad stack'}, h('div', {class: 'row'}, h('span', {}, `Regions without enough data: ${weak.length}. A recipe is not fabricated: `
      + 'delete or exclude the region, choose settings for its group, or send its color to the planner. These regions are hatched in the image.'), toggle), ids);
  }

  function jobView(j) {
    const id = j.id;
    const reload = () => App.render({preserveScroll: true});
    // a refusal of the server is told beside the controls that asked, with what stayed as it was: ``place`` is a form or a notice (Forms.create, Forms.notice);
    // a toast stays only for an action with nothing beside it (ux-save-feedback-p0, REQ-003). Answers whether the edit was accepted.
    const run = async (op, place) => {
      if (place) place.clear();
      try { await post(`/vector/${id}/edit`, op); reload(); return true; } catch (e) { if (place) place.fail(e); else fail(e); return false; }
    };
    const barPlace = Forms.notice({what: 'Edit', kept: 'The work remains unchanged.'});                  // under the bar of the work
    const listPlace = Forms.notice({what: 'Region change', kept: 'The region remains unchanged.'});    // above the list of regions
    const historyPlace = Forms.notice({what: 'Restore version', kept: 'The work remains at its previous version.'});
    const selected = new Set();
    const size = j.document.size_mm;
    const exp = j.experiment || {};
    // the tolerance of the outline and the ΔE threshold are two forms of one box each: a wrong number is refused here with its reason beside the box and stays
    // in it; a refusal of the server stands under the box too (ux-save-feedback-p0, REQ-003)
    const toleranceForm = Forms.create(), thresholdForm = Forms.create();
    const tolerance = toleranceForm.add('tolerance', 'Outline precision', Forms.numberInput(Forms.QUANTITIES.vectorTolerance, {value: j.document.tolerance_mm}),
      {quantity: 'vectorTolerance', required: true});
    const thr = thresholdForm.add('threshold', 'ΔE threshold', Forms.numberInput(Forms.QUANTITIES.deltaE, {value: j.threshold}), {quantity: 'deltaE', required: true});
    const apply = (form, box, op) => async () => {
      const v = form.collect();
      if (!v) return;
      try { await post(`/vector/${id}/edit`, op(v)); reload(); } catch (e) { box.setError((e && e.message) || String(e)); }      // the server's words stand under the box
    };

    // the regions as a short list (DEC-090): a line each — the box for a merge, its colour, status, task, size, group and recipe; the
    // actions on the line; the task, the group and the recipe and prediction under it on a click; pages of 30, so editing stays on a page
    const order = new Map(j.regions.map((r, i) => [r.id, i]));
    const byOrder = (a, b) => order.get(a.id) - order.get(b.id);
    const regions = App.list({id: 'vw.job.regions', items: j.regions, page: 30, key: (r) => r.id,
      row: (r) => [VectorEditor.inRow(h('input', {type: 'checkbox', checked: selected.has(r.id), 'aria-label': 'Select ' + r.id,
          onChange: (ev) => { if (ev.target.checked) selected.add(r.id); else selected.delete(r.id); }})),
        swatch(r.lab), h('strong', {}, r.id), pill(...STATUS[r.status]),
        h('span', {class: 'lst-text muted small'}, [(TASKS.find(([t]) => t === r.task) || [r.task, r.task])[1],
          r.outline === 'closed' ? `${num(r.area_mm2, 2)} mm²` : 'centerline', `group ${r.layer_key}`, r.knowledge_id ? 'K' + r.knowledge_id : 'no recipe'].join(' · ')),
        r.target_sent ? pill('color sent to planner') : null],
      actions: (r) => [btn('Delete', () => run({op: 'delete', region: r.id}, listPlace), 'danger'),
        r.status === 'excluded' ? btn('Restore', () => run({op: 'include', region: r.id}, listPlace)) : btn('Exclude (no recipe)', () => run({op: 'exclude', region: r.id}, listPlace)),
        r.status === 'weak' && r.kind === 'fill' && !r.target_sent ? btn('Send to planner', () => run({op: 'to_designer', region: r.id}, listPlace)) : null],
      details: (r) => {
        const pr = r.prediction;
        // the task is chosen at once; a refusal stands under the choice. The group is a name that must not be empty (vectorize.edit); its refusal stands under the box, the name stays
        const taskPlace = Forms.notice({what: 'Change task', kept: 'The region retains its previous task.'});
        const task = h('select', {'aria-label': 'Region task ' + r.id, style: 'min-width:130px', onChange: (ev) => run({op: 'set_task', region: r.id, task: ev.target.value}, taskPlace)},
          TASKS.filter(([t]) => r.outline === 'closed' || t === 'line').map(([t, l]) => h('option', {value: t, selected: t === r.task}, l)));
        const move = Forms.create();
        const group = move.add('layer_key', `Settings group for region ${r.id}`, h('input', {value: r.layer_key, style: 'min-width:90px;width:90px'}), {required: true});
        return h('div', {class: 'stack small'},
          h('div', {class: 'toolbar'}, field('Task', task), group,
            btn('Move', async () => { const v = move.collect(); if (v) await run({op: 'set_layer', region: r.id, layer_key: v.layer_key}, move); })),
          taskPlace.error, move.error,
          h('div', {}, r.outline === 'closed' ? `Outline · ${num(r.area_mm2, 2)} mm²` : 'Centerline'),
          r.knowledge_id ? h('div', {}, 'Recipe ', link('/knowledge/' + r.knowledge_id, 'K' + r.knowledge_id), ` · ${MODE[r.mode] || r.mode || 'mode not recorded'} · ${params(r.parameters)}`)
            : h('div', {class: 'muted'}, 'No recipe'),
          pr ? h('div', {}, swatch(pr.lab), ` Prediction (REQ-002): confidence ${num(pr.confidence)} · expected ΔE error ${num(pr.expected_delta_e)} · ${stability(pr.stability)}`,
            h('div', {class: 'muted'}, (r.task === 'tonal' ? 'lightness difference ' : 'ΔE to region color ') + num(r.distance) + ' · matching error ' + num(r.match_error))) : null,
          r.note ? h('div', {}, I18N.tr(r.note)) : null);
      },
      search: (r) => [r.id, r.layer_key, r.knowledge_id ? 'K' + r.knowledge_id : ''].join(' '),
      filters: [{key: 'status', label: 'Data', options: Object.entries(STATUS).map(([k, [text]]) => [k, text]), test: (r, v) => r.status === v},
        {key: 'task', label: 'Task', select: true, options: TASKS, test: (r, v) => r.task === v}],
      sorts: [['order', 'Original order', byOrder], ['weak', 'Missing data first', (a, b) => (WEAK_FIRST[a.status] ?? 9) - (WEAK_FIRST[b.status] ?? 9) || byOrder(a, b)],
        ['area', 'Largest area first', (a, b) => (b.area_mm2 ?? 0) - (a.area_mm2 ?? 0) || byOrder(a, b)]],
      empty: 'No regions match this selection.'});

    const groups = j.groups.map((g) => [g.key, g.kind === 'line' ? 'line' : g.kind ? 'fill' : '—',
      g.knowledge_id ? h('span', {}, link('/knowledge/' + g.knowledge_id, 'K' + g.knowledge_id), g.chosen ? ' · selected manually' : ' · closest') : 'no recipe',
      g.choice_unavailable ? pill('selected recipe no longer applies', 'warn') : '', `${g.regions.length}`, `${g.candidates.length}`,
      btn('Choose settings', () => settingsDialog(j, g, run), '', !g.kind)]);

    /** The chain's action for a file: the export card is further down this page, so bring it to the eye and put the cursor on its action. */
    const toFile = () => {
      const card = document.getElementById('vw-job-export');
      if (!card) return;
      if (card.scrollIntoView) card.scrollIntoView({block: 'start'});
      const action = [...card.querySelectorAll('button')].find((b) => b.textContent === 'Download LightBurn');
      if (action && !action.disabled) action.focus();
    };

    /** A blocker names a region: open it in the list of regions, scrolled into view and focused, so that the fix is one step away. */
    const openTarget = async (b) => {
      if (!b.target || b.target.kind !== 'region') return;
      await regions.open(b.target.id);
      const row = [...regions.el.querySelectorAll('.lst-row')].find((r) => r.getAttribute('data-key') === b.target.id);
      if (row && row.scrollIntoView) row.scrollIntoView({block: 'center'});
      const main = row && row.querySelector('.lst-main');
      if (main && main.focus) main.focus();
    };

    // the history of edits as a short list: the newest first, a version a line, «Restore this version» on the line
    const history = App.list({id: 'vw.job.history', items: j.history.map((e, pos) => ({...e, pos})), key: (e) => String(e.pos),
      row: (e) => [h('strong', {}, `v${e.version}`), h('span', {class: 'lst-text'}, OPS[e.op.op] || e.op.op), h('span', {class: 'muted small'}, e.at.replace('T', ' ').slice(0, 16))],
      actions: (e) => (DOCUMENT_OPS.includes(e.op.op) && e.version !== j.document.version ? [btn('Restore this version', () => run({op: 'revert', version: e.version}, historyPlace))] : []),
      search: (e) => `v${e.version} ${OPS[e.op.op] || e.op.op}`,
      sorts: [['new', 'Newest first', (a, b) => b.pos - a.pos], ['old', 'Oldest first', (a, b) => a.pos - b.pos]], empty: 'No edits yet'});

    const heading = h('h2', {}, 'Vector work · ' + j.name);
    const pencil = VectorWorkspace.renameButton(j.id, j.name, (stored) => { j.name = stored; fill(heading, 'Vector work · ' + stored); });
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('div', {class: 'vw-name-row'}, heading, pencil),
        h('p', {class: 'sub'}, `Document version ${j.document.version} · ${num(size.width, 1)} × ${num(size.height, 1)} mm · ΔE threshold ${j.threshold}`)),
        h('span', {class: 'spacer'}), link('/plans/' + id, 'Engraving plan'), link(`/designer?device=${j.device_id}&lens=${App.lensParam(j.lens_id)}`, 'Experiment targets')),
      h('div', {class: 'card'}, Lifecycle.chain(j.lifecycle, {onAction: toFile})),
      h('div', {class: 'card stack'}, facts([['Identifier', j.plan_identifier], ['Laser', exp.device && (exp.device.title || exp.device.name)],
        ['Lens', j.lens ? App.lensLabel(j.lens) : 'unknown'], ['Titanium', exp.material && material(exp.material)],
        ['Strategy', STRATEGY_NAME[j.document.strategy] || j.document.strategy],
        ['Work task', j.engraving_task ? Tasks.name(j.engraving_task.kind) + (j.engraving_task.basis === 'explicit' ? '' : ' · from strategy') : '—'],
        ['Cleaning', j.clean_layer ? 'first layer C00' : 'no'], ['Markers', j.markers_enabled ? 'enabled' : 'disabled'],
        ['LightBurn layers', `${j.layers.length} of ${j.layer_cap} available`]])),
      h('div', {class: 'card stack'}, h('h3', {}, 'Image and outlines'), h('div', {class: 'grid g2'},
        h('figure', {}, h('img', {src: `/api/plans/${id}/source-image`, style: 'width:100%', alt: 'Source image'}), h('figcaption', {class: 'muted small'}, 'Source image')),
        h('figure', {}, h('img', {src: svgSrc(j.svg), style: 'width:100%;background:#fff', alt: 'Vector outlines'}),
          h('figcaption', {class: 'muted small'}, 'Outlines use image colors; regions without enough data are hatched red')))),
      h('div', {class: 'card toolbar'}, tolerance, btn('Apply precision', apply(toleranceForm, tolerance, (v) => ({op: 'set_tolerance', tolerance_mm: v.tolerance}))),
        thr, btn('Apply threshold', apply(thresholdForm, thr, (v) => ({op: 'set_threshold', threshold: v.threshold}))), toleranceForm.error, thresholdForm.error,
        btn('Merge selected', () => (selected.size === 2 ? run({op: 'merge', regions: [...selected]}, barPlace) : barPlace.say('Select exactly two regions in the list below. The work remains unchanged.'))),
        btn(j.markers_enabled ? 'Disable markers' : 'Enable markers', async () => {
          barPlace.clear();
          try { await put(`/plans/${id}/markers`, {enabled: !j.markers_enabled}); reload(); } catch (e) { barPlace.fail(e); }
        }), barPlace.error),
      j.weak.length ? weakSummary(j.weak) : null,
      h('div', {class: 'card'}, h('h3', {}, `Regions: ${j.regions.length}`),
        listPlace.error, regions.el),
      h('div', {class: 'card'}, h('h3', {}, 'Settings groups'), h('p', {class: 'muted small'}, 'Each group uses one recipe; identical recipes across groups are exported as one LightBurn layer.'),
        table(['Group', 'Required', 'Recipe', '', 'Regions', 'Suitable recipes', ''], groups)),
      h('div', {class: 'card stack', id: 'vw-job-export'}, h('h3', {}, 'Export'),
        // REQ-020: task used to measure the layer photo; a mixed-task layer is measured by its LightBurn mode
        Lifecycle.exportCard(j.lifecycle, {path: `/vector/${id}/export.lbrn2`, name: 'vector.lbrn2', reload, onTarget: openTarget, withChain: false,
          designer: `/designer?device=${j.device_id}&lens=${App.lensParam(j.lens_id)}`,
          recipe: table(['Layer', 'Mode', 'Task', 'Regions', 'Predicted color', 'Confidence · error'], j.layers.map((l) => [`C${String(l.index).padStart(2, '0')} · ${l.name}`, MODE[l.mode] || l.mode || '—',
            l.task ? Tasks.name(l.task) : h('span', {class: 'muted small'}, 'mixed: ' + (l.region_tasks || []).map((t) => (TASKS.find(([k]) => k === t) || [t, t])[1]).join(', ') + ' — by LightBurn layer'),
            `${l.region_ids.length}`, h('span', {}, swatch(l.prediction.lab), labText(l.prediction.lab)), `${num(l.prediction.confidence)} · ΔE ${num(l.prediction.expected_delta_e)}`]), 'No layers')})),
      h('div', {class: 'card'}, h('h3', {}, 'Edit history'), historyPlace.error, history.el));
  }

  const duration = (s) => (s == null ? '—' : s >= 3600 ? `${Math.floor(s / 3600)} h ${String(Math.round(s % 3600 / 60)).padStart(2, '0')} min`
    : s >= 60 ? `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s` : `${Math.round(s)} s`);

  /** File tab: estimate total time before export and show recipes, files, and export availability (REQ-042, REQ-043). */
  function photoExport(j, refresh, onTarget) {
    const t = j.time, zones = j.zones || [];
    const layers = t.layers.map((row) => {
      const layer = j.layers.find((l) => l.index === row.index), zone = layer ? null : zones.find((z) => z.index === row.index);
      const part = layer || zone;                                       // neither a color layer nor a photo zone means cleaning
      return h('div', {class: 'vw-line'}, h('span', {}, `C${String(row.index).padStart(2, '0')} `,
        layer ? h('span', {class: 'sw', style: `background:rgb(${layer.srgb.join(',')})`}) : zone && zone.picture ? h('img', {class: 'vw-ed-zone-chip', src: zone.picture, alt: ''}) : null,
        layer ? layer.name : zone ? `Photo zone ${zone.number}: ${VectorPhoto.kindName(zone.kind)}` : 'Cleaning (cross-hatch)'),
        h('span', {class: 'muted small'}, [part ? `regions ${layer ? layer.region_count : zone.regions.length}` : 'whole work', part ? `${num(part.area_mm2 / 100, 2)} cm²` : null,
          row.seconds == null ? I18N.tr(row.note) : duration(row.seconds)].filter(Boolean).join(' · ')));
    });
    const estimate = h('p', {}, h('strong', {}, `Estimated time for the whole work: ${duration(t.seconds)}`), t.complete ? '' : ' (excluding layers whose time cannot be estimated)',
      h('span', {class: 'muted small'}, ' — estimated from each recipe’s speed, line spacing, passes, and cross-hatching; movements between regions are not included.'));
    const recipe = h('div', {class: 'stack'}, estimate, h('div', {class: 'vw-lines'}, layers),
      h('p', {class: 'small'}, `Color layers: ${j.layers.length}` + (zones.length ? `, photo zones: ${zones.length}` : '') + ` of ${j.layer_cap}: C00 is cleaning`
        + (j.markers_enabled ? ', C01 is markers' : '') + '; each layer is one recipe with all settings'
        + (zones.length ? '; photo zones are image layers after color layers, transparent outside their regions.' : '.')));
    return h('div', {class: 'stack'}, Lifecycle.exportCard(j.lifecycle, {path: `/vector/${j.id}/export.lbrn2`, name: 'vector.lbrn2', reload: refresh, onTarget, recipe,
      withChain: false, recipeLabel: `Full recipe and layers (${t.layers.length})`,
      designer: `/designer?device=${j.device_id}&lens=${App.lensParam(j.lens_id)}`}));
  }

  /** One-screen photo work (REQ-042, REQ-044, REQ-054): updates preserve editor state and actions are queued in operator order. */
  function photoView(j, accepted) {
    const reload = () => App.render({preserveScroll: true});
    const exp = j.experiment || {};
    const about = h('div', {class: 'stack'}), split = h('div', {}), file = h('div', {}), review = h('div', {class: 'stack'});
    let shown = null, queue = Promise.resolve(), parts = null, frame = null;
    /** Where a refusal of the server is told. ``place`` is a form or a notice beside the controls that asked (``Forms.create()``, ``Forms.notice()``: both
        have ``clear`` and ``fail``); it is cleared when the request goes out. Without one, the refusal is a toast, which is right only for an action
        that has no control of its own, such as a click on the picture (ux-save-feedback-p0, REQ-003). */
    const refuse = (place, e) => (place ? place.fail(e) : fail(e));
    /** Size changes share the action queue; return the updated work or null on refusal. */
    const resize = (body, place) => (queue = queue.then(async () => {
      if (place) place.clear();
      try { const work = await post(`/vector/${j.id}/size`, body); show(work); return work; } catch (e) { refuse(place, e); return null; }
    }));
    const head = VectorWorkspace.header(j, {file: () => frame.select('file'), renamed: (name) => { shown = {...shown, name}; head.update(shown); }, resize});
    // feature electron, REQ-085: a work pinned to a laboratory release shows its source under the head; a confirmed step returns the whole work
    const banner = LabSource.banner(`/vector/${j.id}`, 'vector', (work) => show(work));
    const applic = h('div', {});                                      // how far the preview can be trusted at this size (ux-evidence-summaries-p0)
    const evidence = h('div', {class: 'small'});
    const chainBox = h('div', {class: 'vw-chain'});                  // the path of the work's file: prepared, file received, result added, checked
    const summaryBox = h('div', {});                                  // what an accepted result did to the work, when the operator came back from accepting it
    const status = Lifecycle.strip({chain: chainBox, forecast: applic, preview: evidence});    // the three above as one fold on a narrow screen (ux-accessible-layout-p0)
    function show(next) {
      const resplit = !shown || next.document.version !== shown.document.version;
      shown = next;
      head.update(next);
      fill(chainBox, Lifecycle.chain(next.lifecycle, {onAction: (a) => frame.select(a.code === 'compare' ? 'review' : 'file')}));
      banner.update(next);
      fill(applic, EvidenceSummary.applicability(next.applicability));
      const p = next.preview_evidence;
      evidence.className = 'small' + (p && (p.estimated_layers || p.estimated_zones || p.ramp_only_zones) ? ' alert warn' : ' muted');
      fill(evidence, !p ? null : p.ramp_only_zones
        ? `Estimated view: ${p.ramp_only_zones} photo zones use test scales. The database has no photo-engraving measurements for these modes; color and contrast accuracy are unverified.`
        : p.estimated_layers || p.estimated_zones
        ? `Preview: ${p.estimated_layers} of ${p.layers} color layers and ${p.estimated_zones || 0} photo zones use measurements at a different width. Accuracy for this work is unverified.`
        : `Preview: colors for ${p.layers} layers were measured at this size. Photo zones are checked against their own scales.`);
      fill(about, h('details', {class: 'vw-details'}, h('summary', {}, 'Work details'), facts([['Identifier', next.plan_identifier], ['Laser', exp.device && (exp.device.title || exp.device.name)],
        ['Lens', next.lens ? App.lensLabel(next.lens) : 'unknown'], ['Titanium', exp.material && material(exp.material)],
        ['Measurements', next.source && next.source.kind === 'release' ? `laboratory ${next.source.lab_name}` : 'this workshop'],      // the work's own, whatever the workshop chooses next
        ['Cleaning', 'first layer C00'], ['Markers', next.markers_enabled ? 'enabled (C01)' : 'disabled'],
        ['Color layers', `${next.layers.length}` + ((next.zones || []).length ? ` and photo zones ${next.zones.length}` : '') + ` of ${next.layer_cap} available`]]),
        h('div', {class: 'row'}, btn(next.markers_enabled ? 'Disable markers' : 'Enable markers', async () => {
          try { await put(`/plans/${next.id}/markers`, {enabled: !next.markers_enabled}); await refresh(); } catch (e) { fail(e); }
        }))));
      if (resplit) fill(split, VectorSplit.card(next, reload, smooth));     // segmentation counts change only with its version
      fill(file, photoExport(next, refresh, () => frame.select('colours')));
      fill(review, VectorReview.view(next, run));
      status.sync();
      if (parts) parts.update(next);
    }
    async function send(op, place) {
      if (place) place.clear();
      try { show(await post(`/vector/${j.id}/colouring`, op)); return true; } catch (e) { refuse(place, e); return false; }
    }
    const run = (op, place) => (queue = queue.then(() => send(op, place)));
    /** Smoothing shares the editor queue; boundaries are redrawn and colors retained (REQ-052). */
    const smooth = (mm, place) => (queue = queue.then(async () => {
      if (place) place.clear();
      try { show(await post(`/vector/${j.id}/smoothing`, {mm})); return true; } catch (e) { refuse(place, e); return false; }
    }));
    /** The work remembers permission to send a reduced photo to AI (DEC-084); this action shares the queue and preserves colors. */
    const permit = (allowed, place) => (queue = queue.then(async () => {
      if (place) place.clear();
      try { show(await post(`/vector/${j.id}/ai-photo`, {allowed})); return true; } catch (e) { refuse(place, e); return false; }
    }));
    async function refresh() {
      try { show(await get('/vector/' + j.id)); } catch (e) { fail(e); }
    }
    show(j);
    parts = VectorColours.parts(j, run, permit);
    frame = VectorWorkspace.frame({head: [head.el, status.el, summaryBox, banner.el], editor: parts.editor, initial: 'colours', items: [
      ['split', 'Segmentation', split], ['colours', 'Document colors', parts.colours], ['ai', 'AI', parts.ai], ['variants', 'Variants', parts.variants],
      ['review', VectorReview.tabLabel(j), review], ['file', 'File', h('div', {class: 'stack'}, file, about)]]});
    if (accepted) {                                                   // back from accepting a result: what it did to this work (kept in the work, so it is told again)
      get(`/pairs/${accepted}/work-summary`).then((found) => {
        fill(summaryBox, Lifecycle.summary(found, {onNext: () => frame.select('review'), onClose: () => fill(summaryBox)}));
      }).catch(() => fill(summaryBox, h('p', {class: 'muted small'}, 'Accepted result summary not found; the photograph may have been deleted.')));
    }
    return frame.el;
  }

  App.register({id: 'vector', async render(ctx) {
    if (ctx.query.plan) {
      const j = await get('/vector/' + ctx.query.plan);
      return j.strategy === 'photo' ? photoView(j, ctx.query.accepted) : jobView(j);
    }
    if (!ctx.query.new) return VectorWorkspace.list();
    if (!ctx.query.classic) return Creation.render(ctx);             // ux-work-creation-p0: the three-step creation; the one-page form stays at &classic=1 (text and a task of its own)
    const [lists, stocks] = await Promise.all([App.hardwareLists(), MaterialPicker.total()]);       // only whether any record exists, not all of them
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'First add a laser'), link('/devices', 'Lasers'));
    if (!stocks) return h('div', {class: 'card empty'}, h('h3', {}, 'First add titanium stock'), link('/setup', 'Settings'));
    const start = await App.contextStart(ctx.query);                // the laser, lens and titanium the workshop chose last; the address wins
    return startForm(lists, {...ctx, start, query: {...ctx.query, ...(start.device != null ? {device: start.device, lens: start.lens ?? ctx.query.lens} : {})}});
  }});
})();
