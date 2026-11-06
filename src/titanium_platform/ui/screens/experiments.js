/* Experiments with a local catalog and independently loaded task and material findings. */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, toast} = App;
  const KIND = {'Awaiting check': ['Awaiting review', ''], 'Needs correction': ['Needs correction', 'warn'],
    'Ready to accept': ['Ready to accept', 'ok'], Accepted: ['Accepted', 'ok']};
  const MODE = {'Calibration plate': 'Calibration plate', 'Laser capability test': 'Laser capability test',
    'Discrete color engraving': 'Color engraving', 'Tonal photo engraving': 'Tonal photo engraving',
    'Color-path photo engraving': 'Color-path photo engraving', 'Restored from file': 'Restored from file'};
  const PURPOSE = {line: 'Lines', text: 'Text', color: 'Color', image: 'Image'};
  const PLATE_TYPE = {text_readability: 'lettering 3 × 3, three sizes', material_matrix: '3 × 3 matrix', compact_capability: 'compact capability test',
    calibration: 'calibration plate', hatch_interval: 'hatch spacing'};
  const settingSummary = (p) => p ? [
    p.power == null ? null : `${p.power}%`, p.frequency == null ? null : `${p.frequency} kHz`,
    p.speed == null ? null : `${p.speed} mm/s`,
    `Q-Pulse ${p.pulse_width == null ? 'not recorded' : p.pulse_width + ' ns'}`,
    p.line_interval == null ? null : `spacing ${p.line_interval} mm`,
    p.passes == null ? null : `${p.passes} pass(es)`,
    p.global_passes == null ? null : `global ${p.global_passes}×`,
    p.scan_angle == null ? null : `angle ${p.scan_angle}°`,
    p.angle_increment == null ? null : `increment ${p.angle_increment}°`,
    p.bidirectional == null ? null : `bidirectional ${p.bidirectional ? 'yes' : 'no'}`,
    p.cross_hatch == null ? null : `cross-hatch ${p.cross_hatch ? 'yes' : 'no'}`,
    p.source_settings?.wobbleEnable?.Value === '1'
      ? `Wobble: size ${p.source_settings.wobbleSize?.Value ?? '—'} mm, spacing ${p.source_settings.wobbleStep?.Value ?? '—'} mm` : null,
  ].filter(Boolean).join(' · ') : null;
  const checks = (n) => `${n} ${n === 1 ? 'review' : 'reviews'}`;
  const stat = (value, label, kind = '') => h('div', {class: `dashboard-stat ${kind}`}, h('strong', {}, value), h('span', {}, label));
  const panel = (title, count, items, empty, action) => h('section', {class: 'os-col ex-find'},
    h('div', {class: 'os-col-head'}, h('h3', {}, title), pill(count), h('span', {class: 'spacer'}), action),
    h('div', {class: 'os-scroll'}, items.length ? h('div', {class: 'ex-insights'}, ...items) : h('p', {class: 'muted small'}, empty)));
  const action = (route, label, primary) => h('a', {class: 'btn btn-small' + (primary ? ' primary' : ''), href: '#' + route}, label);

  App.register({id: 'experiments', async render(ctx) {
    const [experiments, devices] = await Promise.all([get('/experiments'), get('/devices')]);
    const rememberedDevice = Number(sessionStorage.getItem('experiment-dashboard-device'));
    const selectedDevice = devices.find((device) => device.id === rememberedDevice) || devices[0];
    const reload = () => App.render({preserveScroll: true});
    const hero = h('div', {class: 'os-head ex-head'},
      h('div', {class: 'ex-title'}, h('h2', {}, 'Experiments'), h('p', {class: 'sub'}, 'Each experiment opens with its plate, photo overlay and result')),
      h('span', {class: 'spacer'}),
      h('div', {class: 'ex-actions'},
        action('/research', 'AI researcher'),
        action('/colors', 'Color map'),
        btn('Advanced plate options', () => PlateDialog.open(devices, null, reload), 'btn-small', !devices.length),
        action('/ingest', 'Add work and photo')));
    if (!devices.length) return h('div', {class: 'os'}, hero,
      h('div', {class: 'card empty'}, h('h3', {}, 'First add a laser and install a lens'), link('/devices', 'Lasers')));

    // ?device=<id>: the experiments of one laser, the list its page links to (no separate list there). The search, the state, the
    // engraving task (REQ-020), the order and the pages are the shared list's (ExperimentCards.list, DEC-090), the same as on the laser's page.
    const laser = devices.find((device) => String(device.id) === String(ctx.query.device)) || null;
    const shown = laser ? experiments.filter((e) => e.device_id === laser.id) : experiments;
    const scope = laser ? h('div', {class: 'ex-filters'},
      h('span', {class: 'row'}, pill(`Laser: ${laser.title || laser.name}`, 'ok'), link('/experiments', 'All lasers'))) : null;

    const taskSlot = h('section', {class: 'os-col ex-task'});
    const findingsSlot = h('section', {class: 'os-col ex-find'});
    const photoSlot = h('section', {class: 'os-col ex-find'});
    const loading = (slot, title) => App.fill(slot, h('h3', {}, title), h('p', {role: 'status'}, 'Loading…'));
    const failed = (slot, title, error, retry) => App.fill(slot, h('h3', {}, title),
      h('p', {class: 'alert bad', role: 'alert'}, error.message), btn('Retry', retry, 'btn-small'));
    const put = (slot, contents) => App.fill(slot, ...Array.from(contents.childNodes));
    loading(taskSlot, 'Work goal'); loading(findingsSlot, 'Material findings'); loading(photoSlot, 'Photo engraving');
    let goals, selectedMaterial, selectedGoal, setup, findings = [], photoKinds = null;
    let findingsReady = false;
    function showFindings() {
      if (!findingsReady) return;
      const latest = new Map();
      for (const finding of findings.filter((f) => f.material_id === selectedMaterial?.id && f.lens_id === selectedDevice?.lens?.id))
        if (!latest.has(finding.purpose)) latest.set(finding.purpose, finding);
    // the image purpose of a capability plate cannot judge a picture; the photographed photo engravings of this titanium can
    const photoBest = (photoKinds?.kinds || []).filter((k) => k.best && k.best.score != null).sort((a, b) => b.best.score - a.best.score)[0];
    const insightCards = [...latest.values()].sort((a, b) =>
      ['line', 'text', 'color', 'image'].indexOf(a.purpose) - ['line', 'text', 'color', 'image'].indexOf(b.purpose)).map((finding) => {
      const photo = finding.purpose === 'image' && finding.status !== 'candidate' ? photoBest : null;
      const preview = photo ? `Photo engraving was measured: the best result was “${PhotoModes.label(photo.kind)}” (score `
        + `${photo.best.score.toFixed(2)} from photo #${photo.best.source.pair_id}). See Photo engraving for settings and the next plate.`
        : finding.summary;
      return h('article', {class: 'dashboard-insight'},
        h('div', {class: 'dashboard-item-top'}, h('strong', {}, PURPOSE[finding.purpose] || finding.purpose),
          photo ? pill('Photo measured', 'ok') : pill(finding.status === 'candidate' ? 'Candidate' : 'Test needed', finding.status === 'candidate' ? 'ok' : 'warn')),
        h('p', {class: 'dashboard-insight-preview', title: preview}, preview),
        h('details', {class: 'dashboard-details'}, h('summary', {}, 'Full finding and next step'),
          h('p', {}, finding.summary), h('p', {}, finding.next_test),
          settingSummary(finding.parameters || finding.evidence?.parameters)
            ? h('p', {}, 'Measured settings: ' + settingSummary(finding.parameters || finding.evidence?.parameters)) : null,
          link(`/analysis/${finding.pair_id}`, `Measurements · review #${finding.pair_id}`)));
    });
      put(findingsSlot, panel('Material findings', latest.size, insightCards,
        'An accepted capability test will add findings about lines, text, color and images.', link(`/devices/${selectedDevice.id}`, selectedDevice.name)));
    }
    function showTask(guide) {
    const devicePicker = devices.length > 1 ? h('select', {class: 'dashboard-device', 'aria-label': 'Laser for findings',
      onChange: (event) => { sessionStorage.setItem('experiment-dashboard-device', event.target.value); reload(); }},
      devices.map((device) => h('option', {value: device.id, selected: device.id === selectedDevice.id}, device.name))) : null;
    const goalPicker = h('select', {'aria-label': 'Research goal', onChange: (event) => {
      sessionStorage.setItem('experiment-dashboard-goal', event.target.value); reload();
    }}, goals.map((goal) => h('option', {value: goal.id, selected: goal.id === selectedGoal.id}, goal.name)));
    const materialPicker = MaterialPicker.create({value: selectedMaterial ? selectedMaterial.id : undefined, name: 'Material and stock', onChange: (record) => {
      if (!record) return;
      sessionStorage.setItem('experiment-dashboard-material', record.id); reload();
    }});
    // Offer 200 ns only if the laser supports it; otherwise the operator chooses the pulse width (DEC-043).
    const askPulse = guide?.plate && guide.plate.settings?.pulse_width == null;
    const plateForm = Forms.create();
    const pulseSelect = askPulse ? h('select', {}, h('option', {value: ''}, 'select'),
      (selectedDevice?.passport?.pulse_steps || []).map((s) => h('option', {value: s.pulse_width_ns}, `${s.pulse_width_ns} ns`))) : null;
    const pulseChoice = askPulse ? plateForm.add('pulse', 'Pulse width', pulseSelect, {required: true, help: 'this laser has no 200 ns setting',
      read: () => (pulseSelect.value === '' ? {ok: false, message: 'Select a pulse width supported by the laser'} : {ok: true, value: +pulseSelect.value})}) : null;
    const preview = h('div', {class: 'dashboard-plate-preview', 'aria-live': 'polite'});
    let previewRevision = null, previewSequence = 0;
    const nextPlate = guide?.plate ? btn('Create next test', async (ev) => {
      const self = ev.currentTarget;
      const v = plateForm.collect();
      if (!v) return;                                                  // the reason stands beside the box
      if (!previewRevision) return;
      self.disabled = true; self.textContent = 'Creating plate…';
      try {
        const made = await App.post('/application-guide/next-plate', {
          device_id: selectedDevice.id, material_id: selectedMaterial.id, goal: selectedGoal.id, pulse_width: askPulse ? v.pulse : null,
          preview_revision: previewRevision});
        toast(`Plate ${made.name} created`, 'ok'); App.go('/experiment/plan-' + made.plan_id);
      } catch (error) { self.textContent = 'Create next test'; plateForm.fail(error); loadPlatePreview(); }
    }, 'primary', true) : null;
    async function loadPlatePreview() {
      const mine = ++previewSequence;
      previewRevision = null;
      nextPlate.disabled = true;
      if (askPulse && !pulseSelect.value) return App.fill(preview, h('p', {class: 'small muted'}, 'Select a pulse width to estimate this plate.'));
      App.fill(preview, h('p', {class: 'small muted', role: 'status'}, 'Calculating plate size and time…'));
      const query = new URLSearchParams({device_id: String(selectedDevice.id), material_id: String(selectedMaterial.id), goal: selectedGoal.id});
      if (askPulse) query.set('pulse_width', pulseSelect.value);
      try {
        const result = await get('/application-guide/preview?' + query);
        if (mine !== previewSequence) return;
        const size = result.summary.size_mm, time = result.time;
        previewRevision = result.revision;
        nextPlate.disabled = !previewRevision;
        App.fill(preview, h('p', {class: 'small'}, `Plate including registration marks: ${size.width} × ${size.height} mm · ${result.summary.test_features} test features.`),
          h('p', {class: 'small'}, time ? `Estimated engraving time: ${App.duration(time.seconds)}${time.complete ? '' : ' (known layers only; some time is unavailable)'}.`
            : `Engraving time unavailable: ${result.time_reason || 'the available settings do not support an estimate.'}`),
          result.summary.work_field && !result.summary.work_field.checked ? h('p', {class: 'small alert warn'},
            result.summary.work_field.note || 'The laser work field is unknown; fit has not been checked.') : null);
      } catch (error) {
        if (mine !== previewSequence) return;
        App.fill(preview, h('p', {class: 'small alert bad', role: 'alert'}, `Plate preview unavailable: ${error.message}`),
          btn('Retry plate preview', loadPlatePreview, 'btn-small'));
      }
    }
    if (pulseSelect) pulseSelect.addEventListener('change', loadPlatePreview);
    // REQ-020: evidence, independent engravings and photos, and missing context.
    const manyObservations = Boolean(guide?.support) && guide.support.observation_ids.length > SourceRefs.SHORT;    // a count and a list, not a sentence (ux-growing-collections-p0)
    const evidence = [
      guide?.support ? h('p', {class: 'muted small'}, `Task: ${Tasks.name(guide.task.kind)} · evidence: review #${guide.support.pair_id}`,
        guide.support.observation_ids.length && !manyObservations ? `, observations #${guide.support.observation_ids.join(', #')}` : '',
        ` · engravings: ${guide.support.engravings}, photos: ${guide.support.photographs} · repeatability not assessed`,
        ...(guide.support.missing_context.length ? [' · missing: ', ...Tasks.missing(guide.support.missing_context)] : [])) : null,
      manyObservations ? SourceRefs.observations(guide.support.observation_ids, {label: 'Evidence observations'}) : null,
      settingSummary(guide?.finding?.parameters || guide?.finding?.evidence?.parameters)
        ? h('p', {class: 'muted small'}, 'Observation settings: ' + settingSummary(guide.finding.parameters || guide.finding.evidence.parameters)) : null].filter(Boolean);
    const taskNote = 'One material and one goal: test → RAW photo → finding → next test.';
    const taskPanel = h('section', {class: 'os-col ex-task'},
      h('div', {class: 'os-col-head'}, h('h3', {title: taskNote}, 'Work goal'), h('span', {class: 'muted small ex-note', title: taskNote}, taskNote), h('span', {class: 'spacer'}),
      guide?.finding ? pill(guide.finding.status === 'candidate' ? 'Candidate' : 'Review needed',
        guide.finding.status === 'candidate' ? 'ok' : 'warn') : pill('No ready settings', 'warn')),
      h('div', {class: 'os-scroll ex-task-body'},
      h('div', {class: 'dashboard-task-selectors'},
        field('Goal', goalPicker),
        field('Material', materialPicker),
        devices.length > 1 ? field('Laser', devicePicker) : h('div', {class: 'dashboard-task-fixed'},
          h('small', {}, 'Laser and lens'), h('strong', {}, [selectedDevice?.name, selectedDevice?.lens?.name].filter(Boolean).join(' · ')))),
      h('div', {class: 'dashboard-task-result'},
        h('div', {}, h('strong', {}, selectedGoal?.objective || 'Select a goal and material'),
          h('p', {}, guide?.message || 'Add a specific stock record to get the next test.'),
          guide?.finding ? h('p', {class: 'muted small ex-last'}, `Latest finding: ${guide.finding.summary}`) : null,
          evidence.length ? h('details', {class: 'dashboard-details ex-evidence'}, h('summary', {}, 'Finding evidence and settings'), ...evidence) : null),
        h('div', {class: 'dashboard-task-next'}, h('small', {}, 'Next step'),
          h('p', {}, guide?.next_step || 'Create a material and the first plate.'),
          pulseChoice, guide?.plate ? preview : null, nextPlate, guide?.plate ? plateForm.error : null,
          guide?.pending_plan_id ? link('/plans/' + guide.pending_plan_id, 'Open created plate') : null)),
      guide?.plate ? h('p', {class: 'dashboard-task-foot'},
        `Plate: ${PLATE_TYPE[guide.plate.test_type] || guide.plate.test_type} · cleanup before test · source review ${guide.plate.source_pair_id ? '#' + guide.plate.source_pair_id : 'not yet created'}`) : null));
      put(taskSlot, taskPanel);
      if (guide?.plate) loadPlatePreview();
    }
    async function loadFindings() {
      loading(findingsSlot, 'Material findings');
      try { findings = await get(`/devices/${selectedDevice.id}/findings`); findingsReady = true; showFindings(); }
      catch (e) { failed(findingsSlot, 'Material findings', e, loadFindings); }
    }
    async function loadPhoto() {
      if (!setup) { photoSlot.hidden = true; return; }
      photoSlot.hidden = false; loading(photoSlot, 'Photo engraving');
      try {
        photoKinds = await get(`/photo-knowledge?device_id=${setup.device_id}${setup.lens_id == null ? '' : `&lens_id=${setup.lens_id}`}&material_id=${setup.material_id}`);
        put(photoSlot, panel('Photo engraving: laboratory recommendations', photoKinds.kinds.filter((k) => k.proposal).length,
          PhotoQuality.kindCards(photoKinds, setup), 'No photo engraving types.'));
        // Do not replace a finding while someone is reading or operating its disclosure.
        if (!findingsSlot.contains(document.activeElement) && !Array.from(findingsSlot.querySelectorAll('details')).some((d) => d.open)) showFindings();
      } catch (e) { failed(photoSlot, 'Photo engraving', e, loadPhoto); }
    }
    async function loadGuide() {
      if (!selectedMaterial || !selectedGoal) { showTask(null); return; }
      loading(taskSlot, 'Work goal');
      try { showTask(await get(`/application-guide?device_id=${selectedDevice.id}&material_id=${selectedMaterial.id}&goal=${selectedGoal.id}`)); }
      catch (e) { failed(taskSlot, 'Work goal', e, loadGuide); }
    }
    async function loadGoals() {
      loading(taskSlot, 'Work goal');
      try {
        goals = await get('/application-goals');
        selectedGoal = goals.find((goal) => goal.id === sessionStorage.getItem('experiment-dashboard-goal')) || goals[0];
        loadGuide();
      } catch (e) { failed(taskSlot, 'Work goal', e, loadGoals); }
    }
    async function loadContext() {
      loading(taskSlot, 'Work goal'); loading(findingsSlot, 'Material findings'); loading(photoSlot, 'Photo engraving');
      try {
        const rememberedMaterial = Number(sessionStorage.getItem('experiment-dashboard-material'));
        selectedMaterial = (rememberedMaterial ? await MaterialPicker.one(rememberedMaterial).catch(() => null) : null) || await MaterialPicker.lastUsed();
        setup = selectedMaterial ? {device_id: selectedDevice.id, lens_id: selectedDevice.lens?.id ?? null, material_id: selectedMaterial.id} : null;
        loadFindings(); loadPhoto(); loadGoals();
      } catch (e) {
        failed(taskSlot, 'Work goal', e, loadContext);
        App.fill(findingsSlot, h('p', {class: 'small'}, 'Material data is required.'));
        photoSlot.hidden = true;
      }
    }
    loadContext();
    return h('div', {class: 'os ex'}, hero,
      h('div', {class: 'os-body ex-body'},
        h('section', {class: 'os-col ex-list'},
          h('div', {class: 'os-col-head'}, h('h3', {}, 'Experiments'), pill(laser ? `${shown.length} of ${experiments.length}` : experiments.length),
            pill(`${experiments.filter((e) => e.needs_review).length} to review`, experiments.some((e) => e.needs_review) ? 'warn' : '')),
          scope,
          h('div', {class: 'os-scroll'}, ExperimentCards.list(shown, {id: 'experiments', noResults: 'No results: change the search, status or laser.',
            empty: experiments.length ? 'No results: change the search, status or laser.' : 'No experiments yet. Create a plate or add a work and photo.'}))),
        h('div', {class: 'ex-right'}, taskSlot, findingsSlot, photoSlot)));
  }});
})();
