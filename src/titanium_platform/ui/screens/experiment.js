/* Experiment detail: photo overlay, results, plate, checks, work, and findings. */
'use strict';
(() => {
  const {h, fill, btn, link, pill, get, post, del, toast, confirmBox, go, fail, num, swatch, labText} = App;
  const KIND = {'Awaiting check': ['Awaiting review', ''], 'Needs correction': ['Needs correction', 'warn'],
    'Ready to accept': ['Ready to accept', 'ok'], Accepted: ['Accepted', 'ok']};
  const STATUS_KIND = {plate_ready: 'warn', needs_review: 'warn', accepted: 'ok'};
  const ALIGN = {markers: 'using markers', 'marker templates': 'using marker patterns', 'two marker + QR': 'using two markers and QR',
    geometry: 'using image details', 'element anchors': 'using anchor elements', picture: 'using embedded image',
    'single distinctive detail': 'using one distinctive detail', 'element anchor': 'using a detail', manual: 'manually by corners',
    'manual shift': 'manual shift', 'manual rotation': 'manual rotation', 'manual transform': 'scale or mirror'};
  const MEASURE = {raw_camera_relative: 'relative to camera', reference_chart_corrected: 'using reference chart'};
  // a setting the file lacks and the operator supplied is shown as the operator's (REQ-016)
  const supplied = (p, k) => (p.supplied_settings || {})[k];
  const params = (p) => [p.power == null ? null : `${num(p.power, 1)}%`, p.frequency_khz == null ? null : `${num(p.frequency_khz, 0)} kHz`,
    p.speed == null ? null : `${num(p.speed, 0)} mm/s`,
    p.pulse_width != null ? `${num(p.pulse_width, 0)} ns` : supplied(p, 'pulse_width') ? `${num(supplied(p, 'pulse_width').value, 0)} ns (entered by operator)` : (p.defaulted_settings || {}).pulse_width ? `${num(p.defaulted_settings.pulse_width.value, 0)} ns (laser default)` : 'Q-Pulse not set',
    p.line_interval == null ? null : `interval ${num(p.line_interval, 4)} mm`, p.passes == null ? null : `${p.passes} passes`].filter(Boolean).join(' · ');
  const when = (iso) => (iso ? new Date(iso).toLocaleString('en-US', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—');

  /** Frame occlusion per side in mm, from the review alignment. */
  function frameNote(check) {
    const sides = IngestReview.hiddenMargins(check.alignment);
    return sides ? h('p', {class: 'small'}, `Frame covers the edges, mm (approximate): ${sides}. Covered areas are not measured.`) : null;
  }

  // -- the measured layers as a short list (findings-you-can-manage-short-lists-re-check, REQ-005, DEC-090) -------------------------
  // A parameter matrix has a hundred layers: one line each (colour, name, how uneven the sample is, a problem), the worst first, the
  // card of the layer under its line on a click, twenty at a time.

  /** What is wrong with a measured layer: “not comparable” (kept as a measurement, left out of the model) before notes before nothing. */
  function trouble(l) {
    const notes = (l.notes || []).map((n) => I18N.tr(n));
    const remarks = notes.length + (l.covered_by || []).length;
    if (l.compatible === false) return {level: 2, kind: 'bad', label: 'not comparable', notes};
    return remarks ? {level: 1, kind: 'warn', label: `notes: ${remarks}`, notes} : {level: 0, kind: 'ok', label: null, notes};
  }
  // how uneven the colour of the sample is (L*); a picture layer varies by its own tones, so it has none
  const unevenness = (l) => (l.image || !l.spread ? null : l.spread.L);

  /** The card of one layer under its line: the colour (also as shot), the task, the settings, the metrics and the notes (REQ-020). */
  function layerCard(l) {
    return h('div', {class: 'stack small'},
      h('div', {}, l.measured_lab_against_clean
        ? [swatch(l.measured_lab_against_clean), labText(l.measured_lab_against_clean), h('span', {class: 'muted small'}, ` · as photographed: ${labText(l.measured_lab)}`)]
        : [swatch(l.measured_lab), labText(l.measured_lab)], ' ', Tasks.badge(l.task)),
      Tasks.colourBasis(l.metrics) ? h('div', {class: 'muted small'}, Tasks.colourBasis(l.metrics)) : null,
      h('div', {class: 'small muted'}, params(l)),
      Tasks.metrics(l.metrics, {skip: ['lab']}), (l.notes || []).length ? h('span', {}, l.notes.map((n) => I18N.tr(n)).join(' · ')) : null,
      ...Composition.layerNotes(l));
  }

  /** The measured layers of one check. ``pairId`` keeps the order, filter, search and pages for the session while the screen is drawn
      again (the overlay switched, another check and back). */
  function layerList(layers, pairId) {
    const problems = new Map(layers.map((l) => [l, trouble(l)]));
    const worst = (a, b) => problems.get(b).level - problems.get(a).level || (unevenness(b) ?? -1) - (unevenness(a) ?? -1) || a.index - b.index;
    const row = (l) => {
      const lab = l.measured_lab_against_clean || l.measured_lab, t = problems.get(l), spread = unevenness(l);
      return [swatch(lab), h('span', {class: 'lst-text', title: I18N.name(l.name)}, I18N.name(l.name)), h('span', {class: 'muted small'}, labText(lab)),
        spread != null ? h('span', {class: 'small', title: 'Lightness variation in sample'}, `±${num(spread, 1)} L*`) : null,
        t.label ? h('span', {title: t.notes.join(' · ')}, pill(t.label, t.kind)) : null];
    };
    return App.list({id: `ep-layers:${pairId}`, items: layers, key: (l) => l.index, row, details: layerCard,
      search: (l) => `${I18N.name(l.name)} ${l.name}`,
      filters: layers.some((l) => problems.get(l).level) ? [{key: 'problem', label: 'Issues', test: (l, v) => problems.get(l).kind === v,
        options: [['bad', 'Not comparable'], ['warn', 'With issues'], ['ok', 'No issues']]}] : [],
      sorts: [['worst', 'Worst first', worst], ['order', 'In order', (a, b) => a.index - b.index]],
      empty: 'No layers match the search and filter.'});
  }

  App.register({id: 'experiment', async render(ctx) {
    const key = decodeURIComponent(ctx.arg || '');
    const exp = await get('/experiments/' + encodeURIComponent(key));
    const reload = () => App.render({preserveScroll: true});
    // the path of the plan's file (prepared, file received, result added, checked) and its files; a photograph work keeps no file records
    const lifecycle = exp.plan_id && !(exp.plate && exp.plate.mode === 'Photo engraving work') ? await get(`/plans/${exp.plan_id}/lifecycle`).catch(() => null) : null;
    const pairs = exp.pairs;
    const wanted = Number(ctx.query.check);
    let current = pairs.find((p) => p.id === wanted) || pairs.find((p) => p.id === exp.main_pair_id) || pairs[pairs.length - 1] || null;
    // null until the operator chooses: the corrected photograph is shown as it is, the uncorrected (dark) RAW is lifted
    const storedLift = sessionStorage.getItem('experiment-lifted');
    let lifted = storedLift === null ? null : storedLift !== '0';
    let contours = sessionStorage.getItem('experiment-contours') !== '0';

    // -- photo overlay: always the first block ----------------------------------------------
    const stage = h('div', {class: 'ep-stage'});
    const caption = h('p', {class: 'muted small ep-caption'});
    const photoTools = h('div', {class: 'ep-tools'});
    const checks = h('div', {class: 'ep-checks'});
    const result = h('div', {class: 'stack'});          // the alerts and the measured layers of the shown check
    const matrixBox = h('div', {class: 'stack'});       // its parameter matrix, when it has one
    // the photograph is shown the way its colours were measured: corrected by the chart when a chart was used,
    // so that the swatches and the picture share one exposure (the RAW as shot is darker)
    const shownCorrected = (pair) => pair.measurement === 'reference_chart_corrected';
    const isLifted = (pair) => lifted === null ? !(pair && shownCorrected(pair)) : lifted;
    function url(pair) {
      const base = '/api/pairs/' + pair.id, stamp = pair.accepted_at || pair.created_at || '';
      const view = `corrected=${shownCorrected(pair)}&visibility=${isLifted(pair) ? 'lifted' : 'normal'}&full=false&t=${encodeURIComponent(stamp)}`;
      return contours && pair.alignment ? `${base}/overlay.png?${view}` : `${base}/photo.png?${view}`;
    }
    function showPhoto() {
      if (!current) {
        stage.replaceChildren(h('div', {class: 'card empty ep-nophoto'}, h('h3', {}, 'No photo yet'),
          h('p', {class: 'muted'}, 'The plate is ready. Engrave it and add a photo to see it here with an outline overlay.'),
          exp.plan_id ? link('/ingest?plan=' + exp.plan_id, 'Add photo') : null));
        caption.textContent = '';
        return;
      }
      const img = h('img', {class: 'ep-photo', alt: `Photo “${current.photo_name}” with outline overlay`, src: url(current)});
      img.addEventListener('error', () => {       // the review has not aligned the photo yet; show it without outlines
        if (!img.dataset.plain) { img.dataset.plain = '1'; img.src = `/api/pairs/${current.id}/photo.png?corrected=${shownCorrected(current)}&visibility=${isLifted(current) ? 'lifted' : 'normal'}&full=false`; }
      });
      stage.replaceChildren(h('a', {href: `/api/pairs/${current.id}/overlay.png?corrected=${shownCorrected(current)}&full=true&visibility=${isLifted(current) ? 'lifted' : 'normal'}`,
        target: '_blank', rel: 'noopener', title: 'Open full size'}, img));
      const method = current.alignment ? `Alignment ${ALIGN[current.alignment] || current.alignment}` : 'Photo not aligned yet';
      caption.textContent = `${current.photo_name} · review #${current.id} · ${method}`
        + (current.measurement ? ` · color ${MEASURE[current.measurement] || current.measurement}` : '')
        + (shownCorrected(current) ? ' · photo is chart-corrected and shown at the same exposure as the swatches' : ' · photo shown as captured');
    }
    function showTools() {
      fill(photoTools,
        btn(contours ? 'Hide outlines' : 'Show outlines', () => { contours = !contours; sessionStorage.setItem('experiment-contours', contours ? '1' : '0'); refreshAll(); }, 'btn-small'),
        btn(isLifted(current) ? 'Normal brightness' : 'Increase brightness', () => { lifted = !isLifted(current); sessionStorage.setItem('experiment-lifted', lifted ? '1' : '0'); refreshAll(); }, 'btn-small'),
        current && current.status === 'Accepted' ? btn('Re-measure', async (ev) => {
          const control = ev.currentTarget; control.disabled = true; control.textContent = 'Re-measuring…';
          const end = App.landing(control);                      // the measuring takes about half a minute: a person who has gone elsewhere is not brought back, the result waits in the task panel
          try {
            const out = await post(`/pairs/${current.id}/remeasure`);
            if (out.status === 'replaced') {
              if (end.stillHere()) toast('Re-measured using the new calculations; the previous measurement was replaced', 'ok');
              end.go('/experiment/' + encodeURIComponent(key) + '?check=' + out.replaced_by, {title: 'Photo re-measured',
                message: 'Re-measured using the new calculations; the previous measurement was replaced. Open the new review.', openLabel: 'Open review', goOptions: {}});
              return;
            }
            toast('Previous measurement retained: ' + I18N.tr(out.reason || ''), 'warn');
            control.disabled = false; control.textContent = 'Re-measure';
          } catch (error) { control.disabled = false; control.textContent = 'Re-measure'; fail(error); }
        }, 'btn-small') : null,
        h('details', {class: 'ep-legend small muted'}, h('summary', {}, 'What the lines mean'),
          h('p', {}, 'Green lines are image outlines found in the photo; colored lines are LightBurn vectors; pink lines continue under the frame.')));
    }
    function showChecks() {
      checks.replaceChildren(...pairs.slice().reverse().map((p) => {
        const [label, kind] = KIND[p.status] || [p.status, ''];
        return h('div', {class: 'ep-check' + (current && p.id === current.id ? ' is-current' : '')},
          btn(`Review #${p.id}`, () => { current = p; refreshAll(); }, 'btn-small'),
          h('span', {class: 'ep-check-name', title: p.photo_name}, p.photo_name), pill(label, kind),
          h('span', {class: 'muted small'}, when(p.accepted_at || p.created_at)),
          h('span', {class: 'spacer'}),
          link(p.status === 'Accepted' ? `/analysis/${p.id}` : `/ingest?pair=${p.id}`, p.status === 'Accepted' ? 'Analysis' : 'Review and accept'),
          btn('Delete', () => confirmBox('Delete review', `Review #${p.id} and its measurements will be removed from the active database.`, 'Delete',
            async () => { await del('/pairs/' + p.id); toast('Review deleted', 'ok'); reload(); }), 'btn-small danger'));
      }));
    }
    async function showResult() {
      if (!current) { result.replaceChildren(); matrixBox.replaceChildren(); return; }
      const shown = current.id;
      const pair = await get('/pairs/' + shown);
      if (!current || current.id !== shown) return;
      const check = pair.check || {};
      const layers = (check.layers || []).filter((l) => l.measured_lab);
      const ref = check.clean_reference;
      const images = (check.layers || []).filter((l) => l.image && l.tonal);
      // each photographed photo engraving judged as a picture, and the copies of a “Find settings” plate side by side
      // (photo-engraving-quality REQ-003, DEC-001, DEC-003)
      const judged = images.filter((l) => l.photo_quality).map((l) => PhotoQuality.layerBox(l.name, l.photo_quality));
      const quality = pair.variations ? h('div', {class: 'stack'}, PhotoQuality.variationsBox(pair.variations, shown, pair.status === 'Accepted'),
        judged.length ? h('details', {}, h('summary', {class: 'small'}, `Findings by layer · ${judged.length}`), h('div', {class: 'stack'}, judged)) : null)
        : judged.length ? h('div', {class: 'stack'}, h('h3', {}, 'Photo engraving findings'), ...judged) : null;
      // an accepted photo engraving: what the grey scale predicted before it against what came out (DEC-117), loaded after the rest
      const review = images.length && pair.status === 'Accepted' ? h('div', {class: 'stack'}, h('p', {class: 'muted small'}, 'Comparing with prediction…')) : null;
      fill(result,
        ...(check.problems || []).map((m) => h('div', {class: 'alert bad', role: 'alert'}, I18N.tr(m))),
        ...(check.warnings || []).map((m) => h('div', {class: 'alert warn', role: 'status'}, I18N.tr(m))),
        frameNote(check),
        ...(check.composition ? [Composition.card(check, pair.id)] : []),
        ...(ref ? [h('div', {class: 'alert ok', role: 'status'},
          `Colors are normalized to clean titanium in this photo (cleaning layer: L* ${num(ref.lab[0], 1)} as captured, treated as L* ${num(ref.nominal[0], 0)}`
          + `${ref.nominal_source === 'chart' ? ', measured using the chart' : ', default value'}). `
          + (Math.abs(ref.exposure_stops) >= 1 ? `Photo is ${num(Math.abs(ref.exposure_stops), 1)} exposure stops ${ref.exposure_stops > 0 ? 'darker' : 'lighter'} than nominal; ` : '')
          + 'the color ratio to clean titanium in linear light does not depend on exposure.')] : []),
        review,
        quality,
        layers.length ? h('div', {class: 'stack'}, h('h3', {}, `Measured layers · ${layers.length}`),
          h('p', {class: 'muted small'}, (ref ? 'Color relative to clean titanium' : 'Color in photo')
            + ', lightness variation in the sample, and issues. Open a layer for its task, settings, metrics, and notes.'),
          layerList(layers, shown).el) : h('p', {class: 'muted'}, 'No measurements yet; open the review.'),
        ...images.map((l) => h('p', {class: 'small'}, `${l.name}: tonal profile — correlation of image gray level with lightness ${num(l.tonal.rho, 2)}, `
          + `L* range ${num(l.tonal.range_L, 0)}. `, link(`/ingest?pair=${shown}`, 'Gray → power → color table'))));
      if (review) PredictionReview.load(shown, review, () => !!current && current.id === shown);
      fill(matrixBox, pair.matrix ? [h('h3', {}, `Parameter matrix ${pair.matrix.cols} × ${pair.matrix.rows}`),
        h('p', {class: 'muted small'}, pair.matrix.confirmed ? 'Settings were read from the photo and confirmed.' : 'Settings were read from the photo and are not yet confirmed.'),
        IngestReview.matrixGrid(pair)] : null);
      showMatrixTab(!!pair.matrix);
    }
    function refreshAll() { showTools(); showPhoto(); showChecks(); showResult().catch(fail); }

    // -- plate, findings, and actions -------------------------------------------------------------------------------------
    // a photo work is not a plate: it is opened, changed and exported on its own screen (0.19.3)
    const photoWork = exp.plate && exp.plate.mode === 'Photo engraving work';
    const plate = photoWork ? h('div', {class: 'stack'}, h('h3', {}, 'Photo engraving work'),
      h('p', {}, h('strong', {}, exp.plate.name)), h('p', {class: 'muted small'}, exp.plate.identifier || ''),
      h('div', {class: 'row'}, link('/photo-engraving?work=' + exp.plate.plan_id, 'Open work'),
        Lifecycle.downloadButton(`/photo-works/${exp.plate.plan_id}/export.lbrn2`, 'photo-work.lbrn2', 'Download LightBurn', {cls: 'btn-small'}).el))
      : exp.plate ? h('div', {class: 'stack'}, h('h3', {}, 'Plate'),
      h('p', {}, h('strong', {}, I18N.name(exp.plate.name))),
      h('p', {class: 'muted small'}, [exp.plate.test_name || I18N.name(exp.plate.mode), `${exp.plate.layers} layers`, exp.plate.band_count ? `${exp.plate.band_count} strips` : null,
        exp.plate.identifier].filter(Boolean).join(' · ')),
      exp.plate.description ? h('p', {class: 'small'}, exp.plate.description) : null,
      App.timeBlock(exp.time),
      // a plate of the experiment designer answers its proposal (REQ-022): the proposal shows this plate's result
      exp.plate.proposal ? h('p', {class: 'small'}, 'Created from ', link(`/designer?device=${exp.plate.proposal.device_id}&lens=${App.lensParam(exp.plate.proposal.lens_id)}&proposal=${exp.plate.proposal.id}`,
        `planner proposal #${exp.plate.proposal.id}`)) : null,
      exp.plate.engraving_task ? h('p', {class: 'small'}, h('strong', {}, 'Task: '), Tasks.name(exp.plate.engraving_task.kind),
        exp.plate.engraving_task.basis === 'explicit' ? '' : ' (from plan mode)',
        Object.keys(exp.plate.engraving_task.goals || {}).length ? ` · ${Tasks.goalsText(exp.plate.engraving_task.goals)}` : '') : null,
      lifecycle ? Lifecycle.readiness(lifecycle, {designer: null}) : null,
      h('div', {class: 'row'}, link('/plans/' + exp.plate.plan_id, 'Open and edit plate'),
        Lifecycle.downloadButton(`/plans/${exp.plate.plan_id}/export.lbrn2`, 'plate.lbrn2', 'Download LightBurn',
          {cls: 'btn-small', disabled: lifecycle ? !lifecycle.readiness.ready : false, onDone: reload}).el,
        exp.plate.research_session_id ? link(`/research/${exp.plate.research_session_id}`, 'Open research history')
          : link('/research', 'Open AI researcher')),
      lifecycle ? h('details', {class: 'small'}, h('summary', {}, `Previous files${lifecycle.files.length ? ` (${lifecycle.files.length})` : ''}`), Lifecycle.files(lifecycle, {onDone: reload})) : null) : null;
    const work = pairs[pairs.length - 1];
    // REQ-030: an accepted grayscale photo engraving opens its own file in the preview at other Min and Max power
    const photoEngraving = pairs.slice().reverse().find((p) => p.status === 'Accepted' && (p.grayscale_image || p.tonal_image));
    const files = !exp.plate && work ? h('div', {class: 'stack'}, h('h3', {}, 'Completed work'),
      h('p', {class: 'muted small'}, `LightBurn file: ${work.lightburn_name}`), App.timeBlock(exp.time),
      h('div', {class: 'row'}, h('a', {class: 'btn btn-small', href: work.lightburn_url, download: work.lightburn_name}, 'Download this engraving file'),
        photoEngraving ? link(`/photo-preview?pair=${photoEngraving.id}`, 'Preview with different Min/Max') : null)) : null;
    const findings = exp.findings.length ? h('div', {class: 'stack'}, h('h3', {}, 'Findings for this experiment'),
      ...exp.findings.map((f) => h('div', {class: 'stack'}, h('p', {}, h('strong', {}, ({line: 'Lines', text: 'Text', color: 'Color', image: 'Image'})[f.purpose] || f.purpose),
        ' ', pill(f.status === 'candidate' ? 'Candidate' : 'Test needed', f.status === 'candidate' ? 'ok' : 'warn')),
        h('p', {class: 'small'}, f.summary), f.next_test ? h('p', {class: 'muted small'}, f.next_test) : null,
        // a recalculated conclusion keeps what it said before (REQ-022): earlier versions with the time they were in force
        f.history?.length ? h('details', {class: 'small'}, h('summary', {}, `Previous finding versions: ${f.history.length}`),
          ...f.history.map((v) => h('p', {class: 'muted'}, `${when(v.valid_from)} — ${when(v.replaced_at)}: `, v.summary))) : null))) : null;
    const acceptedPair = pairs.slice().reverse().find((p) => p.status === 'Accepted');
    const photoLink = (route) => h('a', {class: 'btn btn-small', href: '#' + route}, 'Add photo');
    const addPhoto = exp.plan_id ? photoLink('/ingest?plan=' + exp.plan_id)
      : acceptedPair ? photoLink('/ingest?rephoto=' + acceptedPair.id)
        : h('span', {class: 'muted small'}, 'A photo can be added after the review is accepted');
    const remove = btn('Delete experiment', () => confirmBox('Delete experiment',
      `“${I18N.name(exp.title)}”: ${exp.plan_id ? 'the plate and ' : ''}all reviews (${pairs.length}) and uploaded file copies will be deleted. Measurement history will remain but will no longer affect recommendations.`,
      'Delete', async () => {
        for (const p of pairs) await del('/pairs/' + p.id);       // each check on its own, then the plate (DEC-047)
        if (exp.plan_id) await del(`/plans/${exp.plan_id}`);
        toast('Experiment deleted', 'ok'); go('/experiments');
      }), 'btn-small danger');

    // -- tabs on the right: only the sections this experiment has -------------------------------------------------------------
    const items = [
      ...(pairs.length ? [['result', 'Result', result], ['matrix', 'Matrix', matrixBox], ['checks', `Reviews (${pairs.length})`, checks]] : []),
      ...(plate ? [['plate', photoWork ? 'Photo engraving work' : 'Plate', plate]] : []), ...(files ? [['work', 'Work', files]] : []),
      ...(findings ? [['findings', `Findings (${exp.findings.length})`, findings]] : [])];
    const box = App.tabs(items, {initial: items[0][0], remember: 'ep.tab', label: 'Experiment sections', prefix: 'ep-tab'});
    // the matrix tab is there only while the shown check has a parameter matrix
    const matrixTab = [...box.list.querySelectorAll('button')].find((b) => b.getAttribute('id') === 'ep-tab-matrix');
    if (matrixTab) matrixTab.hidden = true;
    function showMatrixTab(on) {
      if (!matrixTab) return;
      matrixTab.hidden = !on;
      if (!on && matrixTab.classList.contains('active')) box.select('result');
    }
    refreshAll();
    const sub = [I18N.name(exp.kind), exp.laser, exp.lens, exp.material].filter(Boolean).join(' · ') + (exp.created_at ? ` · ${when(exp.created_at)}` : '');
    const name = h('h2', {}, I18N.name(exp.title));
    const titleBox = h('div', {class: 'ep-title', title: `${I18N.name(exp.title)} · ${sub}`});
    // only the name changes; the list of experiments shows the new one when it is opened again
    const pencil = VectorWorkspace.renameButton(exp.key, exp.title, (stored) => {
      exp.title = stored; fill(name, I18N.name(stored)); titleBox.setAttribute('title', `${I18N.name(stored)} · ${sub}`);
    }, '/experiments', 'experiment');
    const head = h('header', {class: 'os-head ep-head'}, h('a', {class: 'btn btn-small', href: '#/experiments'}, '← Experiments'),
      fill(titleBox, h('div', {class: 'ep-name'}, name, pencil),
        h('div', {class: 'ep-sub'}, h('span', {class: 'sub'}, sub),
          (exp.tasks || []).length ? [h('span', {class: 'muted small'}, 'Tasks:'), ...exp.tasks.map((k) => pill(Tasks.name(k)))] : null)),
      h('span', {class: 'spacer'}), pill(exp.status_text, STATUS_KIND[exp.status] || ''), addPhoto, remove);
    return h('div', {class: 'os experiment'}, head, lifecycle ? h('div', {class: 'ep-chain'}, Lifecycle.chain(lifecycle, {onAction: (a) => {
      const tab = a.code === 'compare' ? 'result' : 'plate';                      // the result tab compares; the file is made on the plate's tab
      if (items.some(([key]) => key === tab)) box.select(tab);
    }})) : null,
      h('div', {class: 'os-body ep-body'},
        h('section', {class: 'os-col ep-photo-col', 'aria-label': 'Photo overlay'}, photoTools, stage, caption),
        h('aside', {class: 'os-col ep-side', 'aria-label': 'Experiment details'}, box.list, h('div', {class: 'os-scroll ep-panels'}, box.panels))));
  }});
})();
