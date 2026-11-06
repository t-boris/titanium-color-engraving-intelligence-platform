/* Upload an experiment result with its LightBurn file, photograph, and hardware context. */
'use strict';
const IngestUpload = (() => {
  const {h, btn, field, link, get, formProgress, post, toast, fail, go} = App;

  function progressView() {
    const label = h('p', {class: 'muted small', role: 'status', 'aria-live': 'polite', hidden: true});
    const bar = h('progress', {max: '100', value: '0', hidden: true});
    let timer = null, figure = null;
    // ux-save-feedback-p0 REQ-002: the live region says the stage once; the percent and the seconds change for the eyes only (aria-hidden), so a
    // screen reader is not read a number every second
    return {el: h('div', {class: 'upload-progress'}, label, bar),
      uploading: (percent) => {
        label.hidden = bar.hidden = false;
        bar.value = percent;
        if (!figure || figure.parentNode !== label) { figure = h('span', {'aria-hidden': 'true'}); label.replaceChildren('Uploading photo: ', figure); }
        figure.textContent = `${percent} %`;
      },
      checking: (what) => {
        label.hidden = bar.hidden = false;
        bar.removeAttribute('value');
        const start = Date.now();
        const seconds = figure = h('span', {'aria-hidden': 'true'});
        label.replaceChildren(`${what || 'File saved. Aligning the photo with LightBurn and measuring the engraving…'} `, seconds);
        const tick = () => { seconds.textContent = `${Math.floor((Date.now() - start) / 1000)} s`; };
        if (timer) clearInterval(timer);
        tick(); timer = setInterval(tick, 1000);
      },
      stop: () => { if (timer) clearInterval(timer); timer = null; bar.hidden = true; },
      error: (message) => { label.hidden = false; label.textContent = message; label.className = 'alert bad'; },
    };
  }

  const landing = (control) => App.landing(control);                // the person goes on to the check, or the result goes to the task panel (app.js)
  const CHECK_READY = {title: 'Photo uploaded', message: 'Photo uploaded and checked. Open the review, inspect the overlay, and accept the result.', openLabel: 'Open review'};

  const fileRead = (input, message) => () => (input.files && input.files[0] ? {ok: true, value: input.files[0]} : {ok: false, message});

  /** Select the capture setup; its chart supplies reference values. */
  function rigPicker(rigs, preferred) {
    const pick = h('select', {'aria-label': 'Capture setup'},
      rigs.map((r) => h('option', {value: r.id}, I18N.name(r.name) + (r.last_used ? ' · same as last time' : ''))));
    const chosen = rigs.find((r) => r.id === preferred) || rigs.find((r) => r.last_used) || rigs[0];
    if (chosen) pick.value = chosen.id;
    return pick;
  }
  const rigHint = () => h('p', {class: 'muted small'}, 'The capture setup specifies camera, light, angle, and reference chart; color correction uses its chart reference values. ',
    link('/setup?tab=rigs', 'Capture setups'));

  function rephoto(source, rigs = []) {
    if (source.status !== 'Accepted') return h('div', {class: 'card empty'},
      h('h3', {}, 'Accept the original observation first'),
      h('p', {}, 'A new photo must belong to an already checked engraving.'),
      link('/ingest?pair=' + source.id, 'Open original pair'));
    const f = Forms.create();
    const photo = h('input', {type: 'file', accept: '.raw,.nef,.nrw,.cr2,.cr3,.arw,.dng,.raf,.rw2,.orf,.pef,.srw'});
    const progress = progressView();
    const laser = [source.hardware?.device?.name, source.hardware?.lens?.name].filter(Boolean).join(' · ') || 'original pair’s laser and lens';
    const titanium = [source.context?.titanium_name, source.context?.titanium_grade, source.context?.batch].filter(Boolean).join(' · ') || 'original pair’s titanium';
    const rig = rigPicker(rigs, source.stand_id);
    const photoField = f.add('photo', 'RAW photo of the entire engraving', App.filePick(photo, 'Choose RAW photo'), {required: true, read: fileRead(photo, 'Choose a new RAW photo')});
    const rigField = rigs.length ? f.add('rig', 'Capture setup', rig, {}) : null;
    const send = btn('Add photo and check', async (ev) => {
      const v = f.collect();
      if (!v) return;
      const fd = new FormData();
      fd.append('photo', v.photo);
      if (rig.value) fd.append('stand_id', rig.value);
      const self = ev.currentTarget;
      const end = landing(self);
      self.disabled = true;
      try {
        progress.uploading(0);
        const pair = await formProgress(`/pairs/${source.id}/rephotos`, fd, progress.uploading);
        progress.checking();
        let ready = false;
        try {
          const checked = await post(`/pairs/${pair.id}/check`, {});
          ready = checked.status === 'Ready to accept';
          if (end.stillHere()) toast(ready ? 'Photo uploaded and checked; inspect the overlay.'
            : 'Photo uploaded. Check the photo corners for alignment.', ready ? 'ok' : 'warn');
        } catch (e) { if (end.stillHere()) toast(`Photo saved; check failed: ${e.message}`, 'warn'); }
        progress.stop();
        end.go('/ingest?pair=' + pair.id, ready ? CHECK_READY : {...CHECK_READY, message: 'Photo uploaded, but review is not ready. Open it to finish before acceptance.'});
      } catch (e) { progress.stop(); f.fail(e); self.disabled = false; }
    }, 'primary');
    return h('div', {class: 'stack'},
      h('div', {class: 'card stack'}, h('h3', {}, 'New photo of the same engraving'),
        h('p', {}, `Original accepted pair #${source.id} · file ${source.lightburn_name}`),
        h('p', {class: 'muted small'}, `${laser} · ${titanium}`),
        source.plan_id ? (source.plan_mode === 'Photo engraving work' ? link('/photo-engraving?work=' + source.plan_id, 'Open photo engraving work')
          : link('/plans/' + source.plan_id, source.plan_mode === 'Restored from file' ? 'Open plan restored from file' : 'Open experiment plate')) : null,
        h('p', {}, 'LightBurn, layer settings, laser, lens, and titanium come from the original pair. The new photo is not a separate engraving.')),
      h('div', {class: 'card stack'}, h('h3', {}, 'New photo only'),
        photoField, rigField, rigs.length ? rigHint() : null,
        h('p', {class: 'muted small'}, 'After upload, the app checks alignment with the same LightBurn file. Review the outlines on the photo before accepting measurements.'),
        f.error, progress.el, h('div', {class: 'row'}, send)));
  }

  // a parameter matrix (LightBurn Material Test): the photograph is the whole input; the settings are read from it
  async function sendMatrix(pick, rig, context, f, progress, self) {
    const v = f.collect();
    if (!v) return;
    const end = landing(self);
    const fd = new FormData();
    fd.append('device_id', pick.deviceId()); fd.append('lens_id', pick.lensValue()); fd.append('stand_id', rig.value);
    fd.append('context', JSON.stringify(context(v))); fd.append('photo', v.photo);
    self.disabled = true;
    try {
      progress.uploading(0);
      const upload = formProgress('/matrix-pairs', fd, (percent) => {
        if (percent < 100) progress.uploading(percent); else progress.checking('Photo uploaded. Finding the matrix and reading engraved settings…');
      });
      const pair = await upload;
      progress.checking('Matrix found. Correcting color from the chart and measuring each cell…');
      try { await post(`/pairs/${pair.id}/check`, {}); } catch (e) { toast(`Check failed: ${e.message}`, 'warn'); }
      progress.stop();
      if (end.stillHere()) toast('Matrix recognized. Review and confirm the read settings.', 'ok');
      end.go('/ingest?pair=' + pair.id, {title: 'Matrix recognized', message: 'Matrix recognized. Open the review and confirm the read settings.', openLabel: 'Open review'});
    } catch (e) { progress.stop(); f.fail(e); self.disabled = false; }
  }

  async function render(ctx, lists, rigs) {
    const matrixMode = ctx.query.kind === 'matrix';
    const kinds = h('div', {class: 'row'}, h('span', {class: 'muted small'}, 'What are you adding:'),
      matrixMode ? link('/ingest?kind=file', 'Work with a LightBurn file') : h('strong', {}, 'Work with a LightBurn file'), ' · ',
      matrixMode ? h('strong', {}, 'Parameter matrix (Material Test)') : link('/ingest?kind=matrix', 'Parameter matrix (Material Test)'));
    // a result of a plan or plate keeps the lens the plan was made for; otherwise the lens stays unknown until chosen
    let planned = null;
    if (ctx.query.plan) { try { planned = await get('/plans/' + ctx.query.plan); } catch (_) { planned = null; } }
    const pick = App.laserLensPicker(lists, {device: planned ? planned.device_id : ctx.query.device,
      lens: planned ? App.lensParam(planned.lens_id) : ctx.query.lens, defaultLens: 'unknown'});
    const f = Forms.create();
    const lb = h('input', {type: 'file', accept: '.lbrn,.lbrn2'});
    const photo = h('input', {type: 'file', accept: '.raw,.nef,.nrw,.cr2,.cr3,.arw,.dng,.raf,.rw2,.orf,.pef,.srw'});
    // the titanium that was used: one concrete record, found by a search among the records used last and not in a list of all; none is chosen
    // unless the address names one (ux-growing-collections-p0, REQ-001)
    const mat = MaterialPicker.create({value: ctx.query.material, allowEmpty: true, clearLabel: 'Clear selection', empty: 'select titanium', name: 'Titanium / sheet / batch used'});
    const rig = rigPicker(rigs);
    // Each layer uses its plan or LightBurn mode by default; review can change the task per layer.
    const task = Tasks.select('', {empty: planned ? 'from plan and LightBurn layers' : 'from LightBurn layer', aria: 'Work task'});
    const c = {focus: Forms.numberInput(Forms.QUANTITIES.focus, {placeholder: 'optional'}),
      date: h('input', {type: 'date'}), note: h('input', {placeholder: 'optional'})};
    const progress = progressView();
    // the fields of the conditions, read once by the form: an empty optional box is nothing, not an empty text
    const lbField = matrixMode ? null : f.add('lb', '.lbrn or .lbrn2 file', App.filePick(lb, 'Choose LightBurn file'), {required: true,
      help: 'settings are read from the file actually used',
      read: () => (!lb.files[0] ? {ok: false, message: 'Choose a .lbrn or .lbrn2 file'}
        : /\.lbrn2?$/i.test(lb.files[0].name) ? {ok: true, value: lb.files[0]} : {ok: false, message: 'A .lbrn or .lbrn2 file is required'})});
    const photoField = f.add('photo', 'RAW photo', App.filePick(photo, 'Choose photo'), {required: true,
      help: matrixMode ? 'include the full labeled grid and reference color chart' : 'include a reference color chart',
      read: fileRead(photo, 'A RAW photo is required for measurement')});
    const laserField = f.add('laser', 'Laser', pick.laser, {required: true,
      read: () => (pick.deviceId() ? {ok: true, value: pick.deviceId()} : {ok: false, message: 'Select the laser used'})});
    const lensField = f.add('lens', 'Lens used', pick.lens, {read: () => ({ok: true, value: pick.lensValue()})});
    const matField = f.add('material', 'Titanium / sheet / batch used', mat, {required: true,
      read: () => (mat.value ? {ok: true, value: +mat.value} : {ok: false, message: 'Select the titanium used'})});
    const rigField = f.add('rig', 'Capture setup', rig, {});
    const taskField = matrixMode ? null : f.add('task', 'Engraving task', task, {help: 'purpose of the work: lettering, lines, fill, image, and so on; results for different tasks stay separate'});
    const focusField = f.add('focus', 'Focus', c.focus, {quantity: 'focus'});
    const dateField = f.add('date', 'Engraving date', c.date, {});
    const noteField = f.add('note', 'Note', c.note, {});
    const context = (v) => ({material_id: v.material, focus: v.focus, engraved_at: v.date, note: v.note});

    const same = btn('Same as previous plate', async () => {
      try {
        const prev = await get(`/devices/${pick.deviceId()}/previous-context`);
        if (!Object.keys(prev).length) { toast('This laser has no accepted experiments yet', 'warn'); return; }
        mat.value = prev.material_id ?? ''; c.focus.value = prev.focus ?? ''; c.date.value = prev.engraved_at ?? ''; c.note.value = prev.note ?? '';
        f.clear();                                                    // the old complaints are about boxes that now hold other values
        pick.setLens(prev.lens_id);
        toast('Lens and titanium filled from this laser’s previous experiment', 'ok');
      } catch (e) { fail(e); }
    });
    const send = btn('Upload pair', async (ev) => {
      const v = f.collect();
      if (!v) return;                                                 // each wrong box says why, beside itself, and keeps what was typed
      const fd = new FormData();
      fd.append('device_id', pick.deviceId()); fd.append('lens_id', pick.lensValue()); fd.append('context', JSON.stringify(context(v)));
      fd.append('stand_id', rig.value);
      if (ctx.query.plan) fd.append('plan_id', ctx.query.plan);
      if (v.task) fd.append('task', v.task);
      fd.append('lightburn', v.lb); fd.append('photo', v.photo);
      const self = ev.currentTarget;
      const end = landing(self);
      self.disabled = true;
      try {
        progress.uploading(0);
        const p = await formProgress('/pairs', fd, progress.uploading);
        progress.stop();
        if (end.stillHere()) toast('Files uploaded. Run the check next', 'ok');
        end.go('/ingest?pair=' + p.id, {title: 'Pair uploaded', message: 'LightBurn file and photo uploaded. Open the review, align the photo with the file, and accept the result.', openLabel: 'Open review'});
      } catch (e) { progress.stop(); f.fail(e); }
      finally { self.disabled = false; }
    }, 'primary');

    const hardware = () => [h('div', {class: 'grid g3'}, laserField, lensField, matField),
      h('div', {class: 'grid g3'}, rigField), rigHint(),
      h('p', {class: 'muted small'}, planned ? 'The lens comes from the plate or plan used for this work.'
        : 'An imported work’s lens remains unknown until selected; the currently installed lens is not substituted. Data from unknown and known lenses stay separate.'),
      h('p', {class: 'small'}, 'Cannot find the laser or titanium? ', link('/devices', 'Lasers and lenses'), ' · ', link('/setup?tab=material', 'Add titanium'))];
    const conditions = h('div', {class: 'card stack'}, h('h3', {}, 'Conditions'), hardware(),
      h('details', {}, h('summary', {}, 'Additional conditions'),
        h('div', {class: 'grid g3'}, focusField, dateField, noteField), same));
    if (matrixMode) {
      const sendM = btn('Upload matrix photo', (ev) => { const self = ev.currentTarget; sendMatrix(pick, rig, context, f, progress, self); }, 'primary');
      return h('div', {class: 'stack'}, kinds,
        h('div', {class: 'card empty'}, h('h3', {}, 'Parameter matrix photo'),
          h('p', {}, 'A grid of squares, each engraved with its own settings and labeled beside it: one setting on each axis, '
            + 'with fixed settings above the grid (as in LightBurn Material Test). No LightBurn file is needed: settings are read from the photo, '
            + 'and you review and confirm them before acceptance.'),
          h('p', {class: 'muted small'}, 'Include the entire labeled grid and reference color chart; photograph from directly above. Each matrix in a photo becomes a separate experiment.')),
        h('div', {class: 'card stack'}, h('h3', {}, 'Photo'), photoField),
        conditions, f.error, progress.el, h('div', {class: 'row'}, sendM));
    }
    // a photograph opened from a work is linked to it; a file that names another work is linked to that one and the check says so
    const work = planned && planned.mode === 'Vector job' ? h('div', {class: 'alert ok'}, 'Photo for work ', link('/vector?plan=' + planned.id, `«${planned.name}»`),
      ': laser, lens, and titanium come from the work. Upload its exported file and an engraving photo; the conclusion will be saved to the work.')
      : planned && planned.mode === 'Photo engraving work' ? h('div', {class: 'alert ok'}, 'Photo for photo engraving work ',
        link('/photo-engraving?work=' + planned.id, `«${planned.name}»`), ': laser, lens, and titanium come from the work. Upload the LightBurn file '
        + 'exported from it and an engraving photo; on acceptance, each gray is compared with the prediction.') : null;
    return h('div', {class: 'stack'}, kinds, work,
      h('div', {class: 'card empty'}, h('h3', {}, 'Add the LightBurn file and a photo of the result'),
        h('p', {}, 'Observation settings are read from the file actually used. Measurements appear after review and acceptance.')),
      h('div', {class: 'grid g2'},
        h('div', {class: 'card stack'}, h('h3', {}, 'LightBurn file'), lbField),
        h('div', {class: 'card stack'}, h('h3', {}, 'Result photo'), photoField)),
      h('div', {class: 'card stack'}, h('h3', {}, 'Conditions'), hardware(),
        h('div', {class: 'grid g3'}, taskField),
        h('p', {class: 'muted small'}, 'Laser, lens, and titanium are saved for each experiment. Focus, date, and note are optional.'),
        h('details', {}, h('summary', {}, 'Additional conditions'),
          h('div', {class: 'grid g3'}, focusField, dateField, noteField), same)),
      f.error, progress.el, h('div', {class: 'row'}, send));
  }
  return {render, rephoto};
})();
