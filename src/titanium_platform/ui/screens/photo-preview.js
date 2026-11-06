/* Preview measured photo engraving colors with the selected laser, lens and stock (REQ-030, DEC-057, DEC-062). */
'use strict';
(() => {
  const {h, fill, btn, link, pill, get, form, num, swatch, labText, table} = App;
  const REFERENCE = {chart: ['reference chart corrected', 'ok'], 'clean titanium': ['camera-relative, adjusted to clean titanium in the same photograph', 'warn'],
    'as photographed': ['camera-relative, as photographed', 'warn']};
  const SOURCE_REFERENCE = {chart: 'chart corrected', 'clean titanium': 'relative to clean titanium', 'as photographed': 'as photographed'};
  const SPREAD_LIMIT = 5;                     // ΔE within which independent engravings agree (agreement.AGREEMENT_DE, DEC-083)
  const OVERRIDES = [['min_power', 'Min power, %'], ['max_power', 'Max power, %'], ['speed', 'Speed, mm/s'], ['frequency', 'Frequency, kHz'],
    ['pulse_width', 'Pulse duration, ns'], ['line_interval', 'Line spacing, mm'], ['passes', 'Passes']];
  const value = (v, d = 2) => (v == null ? '—' : String(+(+v).toFixed(d)));
  const materialLabel = (m) => [m.name, m.grade, m.thickness_mm != null ? `${m.thickness_mm} mm` : null, m.batch].filter(Boolean).join(' · ');

  function sourceLine(s) {
    return h('div', {class: 'small'}, link('/experiment/' + encodeURIComponent(s.experiment), s.title), ' · ',
      s.layer_name || `layer ${s.layer}`, ' · ', s.how === 'tonal profile' ? `tonal profile, gray ${value(s.gray)}` : 'fill', ' · ',
      `photo ${s.photo}`, ' · ', link(`/analysis/${s.pair_id}`, 'analysis'), ' ',
      pill(SOURCE_REFERENCE[s.reference] || s.reference, s.reference === 'chart' ? 'ok' : 'warn'));
  }

  const TONE = (info) => info.axis === 'darkness';       // a dot mode: the curve runs over the darkness of the grey, not over a power

  const spreadCell = (p) => (p.spread_de == null ? h('span', {class: 'muted'}, p.engravings === 1 ? 'one engraving' : '—')
    : h('span', {}, pill(`${value(p.spread_de, 1)} ΔE`, p.spread_de > SPREAD_LIMIT ? 'warn' : 'ok'), ` · engravings ${p.engravings}`));

  function curveTable(info) {
    const tone = TONE(info);
    return table(['Image gray', tone ? 'Tone (gray darkness), %' : 'Power, %', 'Measured color', 'Engraving variation', 'Measurement source'], info.curve.points.map((p) => [
      p.grey == null ? h('span', {class: 'muted'}, tone ? 'outside image' : 'outside Min–Max') : value(p.grey, 3), value(p.power),
      h('span', {}, swatch(p.lab), labText(p.lab)), spreadCell(p), h('div', {class: 'stack'}, p.sources.map(sourceLine))]));
  }

  function restsOn(info) {
    const s = info.mode, experiments = new Set(info.curve.points.flatMap((p) => p.sources.map((x) => x.experiment)));
    const [reference] = REFERENCE[info.reference] || [info.reference];
    const tone = TONE(info);
    const pictureMode = `${value(s.speed, 1)} mm/s · ${value(s.frequency, 1)} kHz · `
      + `${s.pulse_width == null ? 'pulse not specified' : value(s.pulse_width, 0) + ' ns'} · spacing ${value(s.line_interval, 4)} mm · `
      + `passes ${s.passes ?? '—'}${s.global_passes > 1 ? ` · global ${s.global_passes}×` : ''}`
      + (tone ? ` · dot power ${value(s.power, 1)} %${s.dot_width != null ? ` · dot width ${value(s.dot_width, 3)} mm` : ''}` : '');
    return h('div', {class: 'stack'},
      h('p', {}, h('strong', {}, 'Prediction basis. '),
        `Measured ${tone ? 'tones' : 'powers'} for this mode: ${info.curve.points.length}, from ${value(info.span[0])} to ${value(info.span[1])} %, `
        + `from experiments: ${experiments.size}. Colors ${reference}. Mode: ${pictureMode}. `
        + (tone ? 'Image gray controls dot density; each dot fires at layer power. Colors between measured tones are linear in Lab.'
          : 'Image gray maps linearly to power: lightest to Min and darkest to Max. Colors between measured powers are linear in Lab.')),
      h('p', {}, h('strong', {}, 'Prediction limits. '),
        info.outside_share > 0 ? `${value(info.outside_share * 100, 1)} % of the image requires ${tone ? 'tones' : 'powers'} outside the measured range. Those areas have no prediction and are hatched. `
          : `The entire image is within the measured ${tone ? 'tone' : 'power'} range. `,
        tone ? 'Dithering is not simulated: each tone color comes from a photograph of this mode and settings at that tone.'
          : 'Dithering and beam motion are not simulated; the color shown is for the power set by gray.',
        info.spread && info.spread.max_de != null ? ` Independent engravings differ by up to ${value(info.spread.max_de, 0)} ΔE; in ${value(info.spread.uncertain * 100, 0)} % of the predicted image they differ by more than ${SPREAD_LIMIT} ΔE. Treat those colors as a range.` : ''),
      h('ul', {class: 'small'}, info.notes.map((n) => h('li', {}, I18N.tr(n)))));
  }

  function layerCard(layer, cacheId, elsewhere) {
    const head = h('div', {class: 'row'}, h('h3', {}, `Layer ${layer.name}`), pill(layer.dither ? PhotoModes.label(layer.dither) : 'mode not specified'),
      (layer.settings.overridden || []).length ? pill('settings changed', 'warn') : null);
    if (layer.refused) return h('section', {class: 'card stack'}, head, h('div', {class: 'alert warn', role: 'status'}, I18N.tr(layer.refused)), elsewhere(layer));
    const img = h('img', {class: 'pp-image', alt: `Layer ${layer.name} image and its titanium prediction`});
    const banner = h('div', {class: 'pp-banner', role: 'note'});
    const lost = h('div', {class: 'alert warn', role: 'status', hidden: true}, 'The preview is no longer stored; upload the file again.');
    img.addEventListener('error', () => { lost.hidden = false; });
    img.addEventListener('load', () => { lost.hidden = true; });
    const about = h('div', {class: 'stack'}), curve = h('div', {});
    const slider = (key, label) => {
      const range = h('input', {type: 'range', min: 0, max: 100, step: 0.1, value: layer.settings[key], 'aria-label': label});
      const exact = h('input', {type: 'number', min: 0, max: 100, step: 'any', value: layer.settings[key], 'aria-label': label, style: 'width:6em'});
      range.addEventListener('input', () => { exact.value = range.value; exact.removeAttribute('aria-invalid'); note.textContent = ''; schedule(); });
      exact.addEventListener('input', () => { ++seq; clearTimeout(timer); status.textContent = 'Showing the previous prediction; check the new settings.'; });
      // prediction_store.check_power_range: 0 to 100 %; a value outside is kept in the box with the reason beside it and is not applied
      const note = Forms.watch(exact, 'photoPower', (v) => { range.value = v; schedule(); });
      return {exact, box: h('div', {class: 'stack'}, h('label', {class: 'f'}, h('span', {}, label), h('span', {class: 'row'}, range, Forms.describe(range, 'photoPower'),
        exact, Forms.describe(exact, 'photoPower'))), note)};
    };
    const tone = TONE(layer);
    const low = slider('min_power', 'Min power, %'), high = slider('max_power', 'Max power, %');
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const status = h('p', {class: 'small', role: 'status', 'aria-live': 'polite'});
    const retry = btn('Retry calculation', () => { retry.hidden = true; schedule(); }, 'btn-small');
    retry.hidden = true;
    const previewUrl = (info, lo, hi) => tone ? info.preview : `${info.preview}?min_power=${lo}&max_power=${hi}`;

    function draw(info, lo = +low.exact.value, hi = +high.exact.value) {
      img.src = previewUrl(info, lo, hi);
      // DEC-062: a prediction from camera-relative colours says so on the picture itself
      banner.hidden = info.referenced;
      banner.textContent = info.referenced ? '' : 'Camera-relative colors as seen under that lighting, without reference-chart correction'
        + (info.reference === 'as photographed' ? '; no clean titanium appears in the photo, so colors are as photographed.' : '; adjusted to clean titanium in the same photo.');
      fill(about, restsOn(info));
      fill(curve, h('h4', {}, tone ? 'Tone → color curve for this mode' : 'Power → color curve for this mode'), curveTable(info));
    }
    let timer = null, seq = 0;
    async function rerender() {
      const bounds = [low, high].map((b) => Forms.readNumber(b.exact, Forms.QUANTITIES.photoPower, {required: true}));
      error.hidden = true;
      if (tone || !bounds.every((b) => b.ok)) return;                    // a wrong box keeps its text and says why beside itself
      const [lo, hi] = bounds.map((b) => b.value);
      if (!(lo <= hi)) { error.textContent = 'Min power must not exceed Max power.'; error.hidden = false; status.textContent = 'Showing the previous prediction; check the new settings.'; return; }
      const mine = seq;
      status.textContent = 'Showing the previous prediction; recalculating for the new settings…';
      try {
        const info = await get(`/predictions/photo/${cacheId}/${layer.index}?min_power=${lo}&max_power=${hi}`);
        if (mine !== seq) return;
        // Keep the old image until the new render is actually available, not merely until its metadata arrives.
        const next = new Image();
        next.onload = () => { if (mine === seq) { draw(info, lo, hi); status.textContent = ''; } };
        next.onerror = () => failed('Could not load the prediction image.');
        next.src = previewUrl(info, lo, hi);
      } catch (e) { failed(e.message); }
      function failed(message) { if (mine === seq) { error.textContent = message; error.hidden = false; retry.hidden = false; status.textContent = 'Showing the previous prediction; recalculation failed. Change a setting or retry.'; } }
    }
    function schedule() { ++seq; clearTimeout(timer); retry.hidden = true; status.textContent = 'Showing the previous prediction; recalculation pending.'; timer = setTimeout(rerender, 250); }
    draw(layer);
    return h('section', {class: 'card stack'}, head,
      tone ? h('p', {class: 'muted small'}, 'Each dot fires at layer power in this mode. Min and Max do not change the result, so there are no sliders. A different power is a different mode and must be measured separately.')
        : h('div', {class: 'grid g2'}, low.box, high.box), status, error, retry, lost,
      h('div', {class: 'pp-captions'}, h('span', {}, 'Image from file'), h('span', {}, 'Prediction on titanium')),
      h('div', {class: 'pp-stage'}, img, banner),
      about, curve);
  }

  App.register({id: 'photo-preview', async render(ctx) {
    const lists = await App.hardwareLists();
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Add a laser first'), link('/devices', 'Lasers'));
    let preloaded = null;                       // the LightBurn file of an accepted work, opened from its experiment, or of a photo work
    if (ctx.query.pair) {
      const pair = await get('/pairs/' + encodeURIComponent(ctx.query.pair));
      const blob = await get(`/pairs/${pair.id}/lightburn`);
      preloaded = {file: new File([blob], pair.lightburn_name), pair};
    } else if (ctx.query.work) {
      const work = (await get('/photo-works')).find((w) => String(w.id) === String(ctx.query.work));
      if (work) {
        const name = `${work.name}-P${work.min_power}-${work.max_power}.lbrn2`;
        const blob = await get(`/photo-works/${work.id}/export.lbrn2`);
        preloaded = {file: new File([blob], name),
          pair: {device_id: work.scale.device_id, lens_id: work.scale.lens_id, material_id: work.scale.material_id, lightburn_name: name}};
      }
    }
    const pick = App.laserLensPicker(lists, {device: preloaded ? preloaded.pair.device_id : ctx.query.device,
      lens: preloaded ? App.lensParam(preloaded.pair.lens_id) : ctx.query.lens, defaultLens: 'installed'});
    const form_ = Forms.create();
    // one concrete record, found by a search among the records used last and not in a list of all; none is chosen unless the file's work or the address names one
    // (ux-growing-collections-p0, REQ-001)
    const wantedMaterial = preloaded ? preloaded.pair.material_id : ctx.query.material;
    const mat = MaterialPicker.create({value: wantedMaterial, allowEmpty: true, clearLabel: 'Clear selection', empty: 'choose titanium', name: 'Stock'});
    const fileIn = h('input', {type: 'file', accept: '.lbrn,.lbrn2'});
    const fileNote = h('p', {class: 'muted small'}, preloaded ? `Work file “${preloaded.pair.lightburn_name}” is already selected; you can choose another.` : '');
    // the form: the file, the titanium and the laser are required; each override is a number or empty («as in the file»). The ranges are the server's where it
    // has them (the powers: prediction_store.check_power_range; the passes: a whole number from 1); the other overrides are only checked to be numbers
    const OVERRIDE_QUANTITY = {min_power: 'photoPower', max_power: 'photoPower', passes: 'passes'};
    const fileField = form_.add('file', 'LightBurn file', App.filePick(fileIn, 'Choose file'), {required: true,
      read: () => { const f = fileIn.files[0] || (preloaded && preloaded.file); return f ? {ok: true, value: f} : {ok: false, message: 'Choose a LightBurn file'}; }});
    const matField = form_.add('material', 'Stock', mat, {required: true,
      read: () => (mat.value ? {ok: true, value: mat.value} : {ok: false, message: 'Choose stock: the curve uses measurements on this titanium'})});
    const laserField = form_.add('laser', 'Laser', pick.laser, {required: true,
      read: () => (pick.deviceId() ? {ok: true, value: pick.deviceId()} : {ok: false, message: 'Choose a laser'})});
    const lensField = form_.add('lens', 'Lens', pick.lens, {help: 'the curve uses measurements from this laser and lens', read: () => ({ok: true, value: pick.lensValue()})});
    const overrides = OVERRIDES.map(([key, label]) => [key, form_.add(key, label, Forms.numberInput(Forms.QUANTITIES[OVERRIDE_QUANTITY[key]] || null, {placeholder: 'as in file'}),
      OVERRIDE_QUANTITY[key] ? {quantity: OVERRIDE_QUANTITY[key]} : {})]);
    const results = h('div', {class: 'stack'});
    const resultStatus = h('p', {class: 'small', role: 'status', 'aria-live': 'polite'});
    let predictionSeq = 0, hasResults = false;

    function invalidatePrediction() {
      ++predictionSeq;
      if (hasResults) resultStatus.textContent = 'Showing the previous prediction. Settings changed; select “Show prediction” to recalculate.';
      else resultStatus.textContent = '';
    }

    async function predict() {
      const mine = ++predictionSeq;
      const v = form_.collect();
      if (!v) { resultStatus.textContent = hasResults ? 'Showing the previous prediction; check settings before recalculating.' : ''; return; }
      const file = v.file;
      const fd = new FormData();
      fd.append('device_id', v.laser); fd.append('lens_id', v.lens); fd.append('material_id', v.material);
      for (const [key] of overrides) if (v[key] != null) fd.append(key, v[key]);
      fd.append('lightburn', file, file.name);
      resultStatus.textContent = hasResults ? 'Showing the previous prediction; calculating a new one…' : 'Calculating prediction…';
      try {
        const out = await form('/predictions/photo', fd);
        if (mine !== predictionSeq) return;
        await knowStocks(out.layers);
        if (mine !== predictionSeq) return;
        fill(results, h('p', {class: 'muted small'}, `File “${out.file}” · image layers: ${out.layers.length}. Min and Max sliders update the prediction without another upload.`),
          ...out.layers.map((layer) => layerCard(layer, out.cache_id, elsewhere)));
        hasResults = true;
        resultStatus.textContent = '';
      } catch (e) {
        if (mine !== predictionSeq) return;
        resultStatus.textContent = hasResults ? 'Showing the previous prediction; recalculation failed. Retry.' : 'Could not calculate the prediction. Retry.';
        form_.fail(e);
      }
    }
    /* Where the file's mode is measured, when the chosen laser, lens and titanium have no measurement of it: one button each switches to it. */
    const known = new Map();                                     // titanium id -> its record, read one by one for the lines below (never the whole catalogue)
    const knowStocks = async (layers) => {
      const wanted = [...new Set(layers.flatMap((layer) => (layer.measured_on || []).map((m) => m.material_id)).filter((id) => id != null && !known.has(id)))];
      await Promise.all(wanted.map(async (id) => { try { known.set(id, await MaterialPicker.one(id)); } catch (_) { /* the line says “titanium not specified” */ } }));
    };
    const setupLabel = (m) => {
      const d = lists.devices.find((x) => x.id === m.device_id), l = lists.lenses.find((x) => x.id === m.lens_id), t = known.get(m.material_id);
      return [t ? materialLabel(t) : 'titanium not specified', d ? (d.title || d.name) : `laser ${m.device_id}`, l ? App.lensLabel(l) : 'lens unknown'].join(' · ');
    };
    function switchTo(m) {
      pick.laser.value = String(m.device_id);
      pick.setLens(m.lens_id);
      mat.value = m.material_id == null ? '' : String(m.material_id);
      predict();
    }
    function elsewhere(layer) {
      const found = layer.measured_on;
      if (found == null) return null;
      if (!found.length) return h('p', {class: 'muted small'}, 'This mode has not been measured on any titanium, laser and lens. Engrave a gray scale with these settings.');
      return h('div', {class: 'stack'}, h('p', {class: 'small'}, 'This mode was measured here:'),
        ...found.map((m) => h('div', {class: 'row'}, h('span', {class: 'small'}, setupLabel(m)), btn('Show using this setup', () => switchTo(m), 'btn-small'))));
    }
    if (preloaded) predict();
    const setupForm = h('div', {class: 'card stack'},
      h('div', {class: 'grid g2'}, fileField, matField, laserField, lensField),
      fileNote,
      h('details', {}, h('summary', {class: 'small'}, 'Other layer settings (optional; blank uses the file)'),
        h('div', {class: 'grid g3'}, overrides.map(([, fieldEl]) => fieldEl))),
      form_.error, h('div', {class: 'toolbar'}, btn('Show prediction', predict, 'primary')));
    setupForm.addEventListener('input', invalidatePrediction);
    setupForm.addEventListener('change', invalidatePrediction);
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Photo engraving preview'),
        h('p', {class: 'sub'}, 'How an image layer will appear on titanium: grayscale uses Min and Max with a measured power → color curve; '
          + 'dot modes (Jarvis, Stucki and others) use tones measured in the same mode. Variation between independent engravings is shown.')),
        h('span', {class: 'spacer'}), link('/photo', 'Photo engraving'), link('/colors', 'Color map')),
      setupForm, resultStatus, results);
  }});
})();
