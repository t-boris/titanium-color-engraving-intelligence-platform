/* Continuous photo engraving previews and creates plans with matching settings (REQ-004, REQ-012, DEC-032). Revisions create a new plan. */
'use strict';
const PhotoForm = (() => {
  const {h, fill, btn, field, link, get, form, toast, go, modal, swatch, labText} = App;
  // the reason of a doubt joins one message per broken threshold with '; ' (knowledge.refresh): each is translated
  const doubt = (reason) => reason.split('; ').map((part) => I18N.tr(part)).join('; ');

  /** Tonal mode warning: each questioned record includes its reason and observations (DEC-018). */
  function questionedWarning(w, palette = []) {
    const entries = w.entries || w.knowledge_ids.map((id) => ({knowledge_id: id, lab: (palette.find((e) => e.id === id) || {}).lab}));
    return h('div', {class: 'alert warn stack'}, h('p', {}, h('strong', {}, 'Questioned production settings are in use. '),
      'Tonal mode does not require separate confirmation; review each record’s observations.'),
      entries.map((e) => h('div', {class: 'row'}, e.lab ? [swatch(e.lab), labText(e.lab)] : null, h('span', {class: 'small'}, e.reason ? doubt(e.reason) : 'Questioned settings'),
        link('/knowledge/' + e.knowledge_id, `Observations for record K${e.knowledge_id}`))));
  }

  /** Include questioned settings only in the new color-path plan (REQ-004). */
  function questionedDialog(all, state, done) {
    const picked = new Set(state.allowed);
    const rows = all.map((e) => h('div', {class: 'alert warn'},
      h('label', {class: 'row'}, h('input', {type: 'checkbox', checked: picked.has(e.id), onChange: (ev) => { if (ev.target.checked) picked.add(e.id); else picked.delete(e.id); }}), swatch(e.lab), labText(e.lab)),
      h('p', {class: 'small'}, (e.doubt && doubt(e.doubt.reason)) || 'Questioned settings'), link('/knowledge/' + e.id, 'Observations')));
    modal('Include questioned settings in this plan', h('div', {class: 'stack'},
      h('p', {}, 'Permission applies only to the new plan. The knowledge stage and flag do not change.'),
      ...(rows.length ? rows : [h('p', {}, 'No questioned production settings')])), [
      {label: 'Cancel', run: (x) => x.close()},
      {label: 'Apply to this plan', cls: 'primary', run: (x) => { state.allowed = [...picked]; state.path = state.path.filter((id) => !all.some((e) => e.id === id) || picked.has(id)); x.close(); done(); }}]);
  }

  async function render(ctx, lists, parts) {
    const {bandTable, pathPicker, MODES} = parts;
    const {max_bands: maxBands} = await get('/continuous/limits');
    const source = ctx.query.plan ? await get('/plans/' + ctx.query.plan).catch(() => null) : null;
    const revising = source && MODES.some(([id]) => id === source.continuous_mode) ? source : null;
    const state = {mode: revising ? revising.continuous_mode : ctx.query.mode === 'color_path' ? 'color_path' : 'tonal',
      path: revising ? [...revising.path_ids] : [], allowed: revising ? [...revising.allowed_questioned] : [], preview: null, image: null};
    const host = h('div', {class: 'stack'});
    const begin = revising ? null : await App.contextStart(ctx.query);                  // the laser and lens the workshop chose last; the address wins (REQ-001)
    const pick = App.laserLensPicker(lists, {device: revising ? revising.device_id : begin.device, lens: revising ? App.lensParam(revising.lens_id) : begin.lens,
      onChange: async () => { state.path = []; state.allowed = []; await loadPalette(); invalidate(); }});
    const img = h('input', {type: 'file', accept: 'image/*'});
    const name = h('input', {placeholder: 'Plan name', value: revising ? `${revising.name} — revision` : ''});
    // the width and the number of bands are read as the server reads them (conversion.raster: above 0; conversion._check_bands: a whole number from 1 to the
    // layers LightBurn has, which the screen asks the server for); a wrong one is said beside its box and kept, as is a refusal of the server
    const width = Forms.numberInput(Forms.QUANTITIES.workWidth, {value: revising && revising.size_mm ? revising.size_mm.width : 80});
    const bands = Forms.numberInput({...Forms.QUANTITIES.bandCount, max: maxBands}, {value: revising ? Math.min(revising.band_count, maxBands) : maxBands});
    let form_ = Forms.create();
    const markers = h('input', {type: 'checkbox', checked: revising ? revising.markers_enabled : false});
    // REQ-020: record a tonal-image or color-image task according to the selected mode.
    const DEFAULT_TASK = {tonal: 'tonal_image', color_path: 'color_image'};
    const task = Tasks.chooser((revising && revising.engraving_task && revising.engraving_task.kind) || DEFAULT_TASK[state.mode]);
    let all = [], palette = [];
    const err = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const show = (m) => { err.textContent = m; err.hidden = !m; };
    if (revising) {
      const res = await fetch(`/api/plans/${revising.id}/source-image`);
      if (res.ok) state.image = await res.blob();
    }
    const picture = () => img.files[0] || state.image;

    const body = (create) => {
      const fd = new FormData();
      fd.append('device_id', pick.deviceId()); fd.append('lens_id', pick.lensValue()); fd.append('mode', state.mode); fd.append('width_mm', width.value); fd.append('bands', bands.value);
      fd.append('path_ids', JSON.stringify(state.path)); fd.append('allowed_questioned', JSON.stringify(state.allowed));
      if (img.files[0]) fd.append('image', img.files[0]); else fd.append('image', state.image, 'source-image');
      if (create) { fd.append('name', name.value); fd.append('markers', markers.checked); if (revising) fd.append('revision_of', revising.id); task.append(fd); }
      return fd;
    };
    const signature = () => JSON.stringify([pick.deviceId(), pick.lensValue(), state.mode, width.value, bands.value, state.path, state.allowed,
      img.files[0] ? img.files[0].name + img.files[0].size : state.image ? 'plan-image' : null]);
    let previewSig = null, sourceUrl = null;

    async function loadPalette() {
      all = await get(`/palette?${pick.query()}&include_questioned=true`);
      // Tonal mode includes questioned records with a warning; color path includes only explicitly permitted records.
      palette = state.mode === 'tonal' ? all : all.filter((e) => !e.questioned || state.allowed.includes(e.id));
    }
    function invalidate() { state.preview = null; previewSig = null; draw(); }

    async function doPreview() {
      show('');
      if (!form_.collect()) return;                                          // the photo, the width and the bands: each wrong one says why beside itself
      try { state.preview = await form('/continuous/preview', body(false)); previewSig = signature(); draw(); } catch (e) { form_.fail(e); }
    }
    async function doCreate(ev) {
      if (!state.preview || previewSig !== signature()) return show('Create a current preview first');
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const p = await form('/continuous', body(true));
        if (!revising) App.rememberContext({device: pick.deviceId(), lens: pick.lensId()});
        toast(revising ? 'Revised plan created; the previous plan is unchanged' : 'Plan created', 'ok'); go('/plans/' + p.id);
      } catch (e) { form_.fail(e); self.disabled = false; }
    }

    function sourcePicture() {
      if (sourceUrl) URL.revokeObjectURL(sourceUrl);
      sourceUrl = picture() ? URL.createObjectURL(picture()) : null;
      return sourceUrl ? h('figure', {}, h('img', {src: sourceUrl, style: 'width:100%', alt: 'Source photograph'}), h('figcaption', {class: 'muted small'}, 'Source photograph')) : null;
    }

    function draw() {
      const p = state.preview;
      const questioned = all.filter((e) => e.questioned);
      const modeBtns = MODES.map(([id, label]) => h('button', {type: 'button', class: 'btn' + (state.mode === id ? ' primary' : ''), 'aria-pressed': state.mode === id,
        onClick: async () => { if (state.mode === id) return; state.mode = id; state.path = []; state.allowed = []; state.preview = null; task.set(DEFAULT_TASK[id]); await loadPalette(); draw(); }}, label));
      form_ = Forms.create();
      const photoField = form_.add('image', 'Photograph', App.filePick(img, 'Choose photograph'), {required: true, help: revising && !img.files[0] ? 'currently using the image from the plan being revised' : null,
        read: () => (picture() ? {ok: true, value: picture()} : {ok: false, message: 'Add a photograph for engraving'})});
      const widthField = form_.add('width_mm', 'Work width', width, {quantity: 'workWidth', required: true});
      const bandsField = form_.add('bands', 'Number of bands', bands, {quantity: {...Forms.QUANTITIES.bandCount, max: maxBands}, required: true,
        help: 'one of 30 LightBurn output layers is reserved for markers; the band preview updates when this changes'});
      fill(host,
        h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Continuous photo engraving'), h('p', {class: 'sub'}, 'One transfer function, two modes. Settings are not interpolated between measured sets.')),
          h('span', {class: 'spacer'}), h('div', {class: 'row', role: 'group', 'aria-label': 'Photo engraving mode'}, modeBtns), link('/colors', 'Color map')),
        revising ? h('div', {class: 'alert ok'}, 'Revising plan ', link('/plans/' + revising.id, `«${revising.name}»`),
          ': its values and image are used. A new plan will be created and the previous one remains unchanged. Choose another image to replace it.') : null,
        h('div', {class: 'card stack'}, h('div', {class: 'grid g2'}, field('Laser', pick.laser), field('Lens', pick.lens, 'palette measurements use this laser and lens'),
          photoField, field('Plan name', name), widthField, bandsField), form_.error,
        task.el, h('label', {class: 'row'}, markers, h('span', {}, 'Registration markers and identifier outside the image'))),
        state.mode === 'color_path' ? pathPicker(palette, state, () => invalidate()) : null,
        state.mode === 'color_path' ? h('div', {class: 'card toolbar'}, btn('Include questioned settings in this plan', () => questionedDialog(questioned, state, async () => { await loadPalette(); invalidate(); }), '', !questioned.length),
          h('span', {class: 'muted small'}, state.allowed.length ? `Included in this plan: ${state.allowed.map((id) => 'K' + id).join(', ')}` : questioned.length ? 'Questioned records are excluded by default' : 'No questioned records')) : null,
        state.mode === 'tonal' && all.some((e) => e.questioned) ? h('div', {class: 'alert warn'}, 'Eligible colors include questioned production records. Tonal mode uses them with a warning and no separate confirmation.') : null,
        !palette.length ? h('div', {class: 'alert warn'}, 'No calibrated transfer function is available for this mode: there are no validated or production colors for this laser and lens.') : null,
        err,
        h('div', {class: 'row'}, btn('Preview', doPreview, 'primary'), btn(revising ? 'Create revised plan' : 'Create plan', doCreate, 'primary', !(p && previewSig === signature()))),
        p ? h('div', {class: 'stack'}, ...p.warnings.map((w) => questionedWarning(w, all)),
          h('div', {class: 'card stack'}, h('h3', {}, `Bands: ${p.bands} · distinct setting sets: ${p.distinct_entries} · empty bands: ${p.empty_bands}`),
            h('div', {class: 'grid g2'}, sourcePicture(), h('figure', {}, h('img', {class: 'banding', src: p.banding_png, style: 'width:100%;image-rendering:pixelated', alt: 'Bands in predicted titanium colors'}),
              h('figcaption', {class: 'muted small'}, 'Each band shows the predicted color of its measured setting set'))),
            bandTable(p))) : null);
    }
    let timer = null;
    bands.addEventListener('input', () => {
      clearTimeout(timer);
      if (previewSig) invalidate();
      if (picture() && +bands.value >= 1 && +bands.value <= maxBands) timer = setTimeout(doPreview, 350);    // update the band preview for the new count
    });
    [width, markers, img, name].forEach((el) => el.addEventListener('input', () => { if (previewSig) invalidate(); }));
    img.addEventListener('change', () => { if (previewSig) invalidate(); });
    await loadPalette();
    draw();
    return host;
  }
  return {render, questionedWarning};
})();
