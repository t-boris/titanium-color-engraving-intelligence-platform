/* Review a photo pair: reference, alignment, differences, layer masks, and acceptance. */
'use strict';
const IngestReview = (() => {
  const {h, btn, link, pill, post, del, toast, fail, go, confirmBox, num, swatch, labText} = App;

  /** The photograph with the contours drawn over it, and the controls that move the whole overlay. Returns the viewer (the review
      stage) and the card of the overlay controls (the «Move and rotate layout» tool). Both are drawn from the same state, so they stay in
      step while the operator moves between stages. Marking the masks as reviewed and accepting are not here: they are the primary
      actions of the review and accept stages. */
  function viewer(pair, reload, run) {
    // the picture the numbers come from is shown first: corrected by the chart when the chart is usable, as it is (the lifted dark RAW) otherwise
    let corrected = pair.check?.chart?.usable === true, visibility = corrected ? 'normal' : 'lifted', selectedLayer = 'all', editing = false;
    let shift = [0, 0], rotation = 0, schemeScale = 100, mirrorHorizontal = false,
      mirrorVertical = false, viewRotation = 0, zoom = 100, drag = null, highDetail = false;
    const photoSrc = () => `/api/pairs/${pair.id}/photo.png?corrected=${corrected}&visibility=${visibility}&full=${highDetail}&t=${Date.now()}`;
    const contourSrc = () => `/api/pairs/${pair.id}/vector-overlay.png?` +
      `${selectedLayer === 'all' ? '' : `layer_index=${encodeURIComponent(selectedLayer)}&`}full=${highDetail}&t=${Date.now()}`;
    const imageStatus = h('div', {class: 'alert warn', role: 'status'}, `Loading photo ${pair.photo_name} and measurement-area overlay…`);
    const img = h('img', {src: photoSrc(), alt: 'Engraving photograph', loading: 'eager', draggable: 'false'});
    const contours = h('img', {class: 'vector-contours', src: contourSrc(), alt: '', draggable: 'false'});
    const editor = h('div', {class: 'overlay-editor'}, img, contours);
    const frame = h('div', {class: 'overlay-rotated-frame'}, editor);
    const viewport = h('div', {class: 'overlay-viewport'}, frame);
    const editorStatus = h('p', {class: 'muted small', role: 'status', 'aria-live': 'polite'},
      'The outlines are linked by LightBurn geometry. Enable movement to adjust the entire overlay on the photo.');
    const snapStatus = h('p', {class: 'muted small', role: 'status', 'aria-live': 'polite'}, '');
    const snap = h('input', {type: 'checkbox', checked: true});
    const saveShift = btn('Apply alignment and recalculate', (ev) => {
      const self = ev.currentTarget;
      run({translation_fraction: shift, rotation_degrees: rotation, scale_factor: schemeScale / 100,
        mirror_horizontal: mirrorHorizontal, mirror_vertical: mirrorVertical}, self);
    }, '', true);
    const rotationRange = h('input', {type: 'range', min: 0, max: 360, step: .1, value: 0,
      'aria-label': 'Rotation of the entire layout relative to the photo, degrees'});
    const rotationNumber = h('input', {type: 'number', min: 0, max: 360, step: .1, value: 0,
      'aria-label': 'Exact rotation angle, degrees'});
    const scaleRange = h('input', {type: 'range', min: 10, max: 800, step: 1, value: 100,
      'aria-label': 'Layout scale relative to the photo, percent'});
    const scaleNumber = h('input', {type: 'number', min: 10, max: 800, step: .1, value: 100,
      'aria-label': 'Exact layout scale, percent'});
    const mirrorX = h('input', {type: 'checkbox', 'aria-label': 'Mirror layout horizontally'});
    const mirrorY = h('input', {type: 'checkbox', 'aria-label': 'Mirror layout vertically'});
    const showAdjustment = (match = null) => {
      const sx = (mirrorHorizontal ? -1 : 1) * schemeScale / 100;
      const sy = (mirrorVertical ? -1 : 1) * schemeScale / 100;
      contours.style.transform = `translate(${shift[0] * 100}%, ${shift[1] * 100}%) rotate(${rotation}deg) scale(${sx}, ${sy})`;
      saveShift.disabled = Math.hypot(...shift) < 1e-6 && (rotation % 360) === 0 &&
        schemeScale === 100 && !mirrorHorizontal && !mirrorVertical;
      const px = pair.check.image_size;
      editorStatus.textContent = match ? `Snapped to recognized detail “${match.element}”. All outlines moved together.`
        : `Layout: ${schemeScale.toFixed(1)}%, rotation ${rotation.toFixed(1)}°` +
          `${mirrorHorizontal ? ', mirrored horizontally' : ''}${mirrorVertical ? ', mirrored vertically' : ''}. ` +
          `Shift: ${(shift[0] * px[0]).toFixed(0)} × ${(shift[1] * px[1]).toFixed(0)} px. ` +
          'Dimensions in the LightBurn file are preserved.';
    };
    const baseSnapCandidates = (pair.check.alignment.snap_candidates || []).map((v) => ({
      element: `${v.element} · matching details: ${v.support_count}`,
      shift: [v.shift_px[0] / pair.check.image_size[0], v.shift_px[1] / pair.check.image_size[1]]}));
    const vectorSnapMatches = (pair.check.alignment.vector_matches || []).filter((v) =>
      v.status === 'found' && v.edge_support >= .42 && v.expected_center_px && v.found_center_px);
    const snapCandidates = () => {
      const [w, hh] = pair.check.image_size;
      const radians = rotation * Math.PI / 180, cosine = Math.cos(radians), sine = Math.sin(radians);
      const candidates = Math.abs(rotation % 360) < .01 && schemeScale === 100 &&
        !mirrorHorizontal && !mirrorVertical ? [...baseSnapCandidates] : [];
      for (const match of vectorSnapMatches) {
        const x = (match.expected_center_px[0] - w / 2) * schemeScale / 100 * (mirrorHorizontal ? -1 : 1);
        const y = (match.expected_center_px[1] - hh / 2) * schemeScale / 100 * (mirrorVertical ? -1 : 1);
        const rotatedX = w / 2 + x * cosine - y * sine;
        const rotatedY = hh / 2 + x * sine + y * cosine;
        candidates.push({element: match.element,
          shift: [(match.found_center_px[0] - rotatedX) / w,
            (match.found_center_px[1] - rotatedY) / hh]});
      }
      return candidates;
    };
    const nearestSnap = (proposed) => {
      if (!snap.checked || !img.clientWidth) return null;
      let closest = null;
      for (const candidate of snapCandidates()) {
        const distance = Math.hypot((proposed[0] - candidate.shift[0]) * img.clientWidth,
          (proposed[1] - candidate.shift[1]) * img.clientHeight);
        if (distance <= 14 && (!closest || distance < closest.distance)) closest = {...candidate, distance};
      }
      return closest;
    };
    let snapTimer = null, snapRequest = 0;
    const scheduleShapeSnap = (delay = 500) => {
      clearTimeout(snapTimer);
      const request = ++snapRequest;
      if (!snap.checked || !img.naturalWidth) { snapStatus.textContent = ''; return; }
      snapStatus.textContent = 'Checking matching shapes in the photograph…';
      snapTimer = setTimeout(async () => {
        const startingShift = [...shift];
        try {
          const result = await post(`/pairs/${pair.id}/snap`, {
            translation_fraction: startingShift, rotation_degrees: rotation,
            scale_factor: schemeScale / 100, mirror_horizontal: mirrorHorizontal,
            mirror_vertical: mirrorVertical,
          });
          if (request !== snapRequest) return;
          const nearby = (result.candidates || []).map((candidate) => ({
            ...candidate,
            distance: Math.hypot(candidate.shift_fraction[0] * img.clientWidth,
              candidate.shift_fraction[1] * img.clientHeight),
          })).filter((candidate) => candidate.distance <= 18)
            .sort((a, b) => b.support_count - a.support_count || a.shape_score - b.shape_score || a.distance - b.distance);
          if (nearby.length) {
            const best = nearby[0];
            shift = [startingShift[0] + best.shift_fraction[0], startingShift[1] + best.shift_fraction[1]];
            showAdjustment({element: best.element});
            snapStatus.textContent = `Outlines snapped by shape to “${best.element}”; matching shapes: ${best.support_count}.`;
          } else {
            snapStatus.textContent = 'No confirmed match of multiple shapes nearby. Move the layout closer to a detail.';
          }
        } catch (error) {
          if (request === snapRequest) snapStatus.textContent = `Shape snapping unavailable: ${error.message}`;
        }
      }, delay);
    };
    const snapAdjustment = () => {
      const match = nearestSnap(shift);
      if (match) shift = [...match.shift];
      showAdjustment(match);
      scheduleShapeSnap();
    };
    snap.addEventListener('change', () => scheduleShapeSnap(0));
    const setRotation = (value) => {
      const parsed = Number(value);
      if (!Number.isFinite(parsed)) return;
      rotation = parsed;                                                   // the slider, the buttons and the checked box keep it within 0 to 360
      rotationRange.value = rotation;
      rotationNumber.value = String(rotation);
      rotationNumber.removeAttribute('aria-invalid'); rotationNote.textContent = '';
      snapAdjustment();
    };
    rotationRange.addEventListener('input', () => setRotation(rotationRange.value));
    // the server accepts 0 to 360 degrees and 10 to 800 percent (ingest._overlay_override): a value outside that is kept in the box with the reason beside it,
    // never moved to the nearest allowed one without a word
    const rotationNote = Forms.watch(rotationNumber, 'schemeRotation', setRotation);
    const setScale = (value) => {
      const parsed = Number(value);
      if (!Number.isFinite(parsed)) return;
      schemeScale = parsed;                                                // the slider and the checked box keep it within 10 to 800
      scaleRange.value = schemeScale;
      scaleNumber.value = String(schemeScale);
      scaleNumber.removeAttribute('aria-invalid'); scaleNote.textContent = '';
      snapAdjustment();
    };
    scaleRange.addEventListener('input', () => setScale(scaleRange.value));
    const scaleNote = Forms.watch(scaleNumber, 'schemeScale', setScale);
    mirrorX.addEventListener('change', () => { mirrorHorizontal = mirrorX.checked; snapAdjustment(); });
    mirrorY.addEventListener('change', () => { mirrorVertical = mirrorY.checked; snapAdjustment(); });
    const zoomRange = h('input', {type: 'range', min: 25, max: 800, step: 25, value: 100,
      'aria-label': 'Photo view zoom, percent'});
    const zoomValue = h('span', {class: 'muted small', 'aria-live': 'polite'}, '100%');
    const zoomOut = btn('−', () => setZoom(zoom - 25)), zoomIn = btn('+', () => setZoom(zoom + 25));
    const viewRange = h('input', {type: 'range', min: 0, max: 360, step: .1, value: 0,
      'aria-label': 'Photo rotation for viewing, degrees'});
    const viewNumber = h('input', {type: 'number', min: 0, max: 360, step: .1, value: 0,
      'aria-label': 'Exact photo rotation angle, degrees'});
    const layoutView = () => {
      if (!editor.clientWidth || !editor.clientHeight) return;
      const w = editor.clientWidth, hh = editor.clientHeight;
      const radians = viewRotation * Math.PI / 180;
      const fw = Math.abs(w * Math.cos(radians)) + Math.abs(hh * Math.sin(radians));
      const fh = Math.abs(w * Math.sin(radians)) + Math.abs(hh * Math.cos(radians));
      frame.style.width = `${fw}px`;
      frame.style.height = `${fh}px`;
      editor.style.left = `${(fw - w) / 2}px`;
      editor.style.top = `${(fh - hh) / 2}px`;
      editor.style.transform = `rotate(${viewRotation}deg)`;
    };
    const setViewRotation = (value) => {
      const parsed = Number(value);
      if (!Number.isFinite(parsed)) return;
      viewRotation = parsed;                                               // the slider, the buttons and the checked box keep it within 0 to 360
      viewRange.value = viewRotation;
      viewNumber.value = String(viewRotation);
      viewNumber.removeAttribute('aria-invalid'); viewNote.textContent = '';
      layoutView();
    };
    viewRange.addEventListener('input', () => setViewRotation(viewRange.value));
    // how the photograph is looked at is no rule of the server: the box takes the turn the slider has (0 to 360 degrees) and says so beside itself when it is not
    const viewNote = Forms.watch(viewNumber, 'viewRotation', setViewRotation, {required: true});
    const setZoom = (value) => {
      zoom = Number(value);                                                // the slider and the buttons (disabled at the ends) keep it within 25 to 800
      zoomRange.value = zoom;
      zoomOut.disabled = zoom <= 25; zoomIn.disabled = zoom >= 800;
      const detailed = zoom > 125;
      zoomValue.textContent = `${zoom}%${detailed ? ' · full RAW' : ''}`;
      if (detailed !== highDetail) { highDetail = detailed; img.src = photoSrc(); contours.src = contourSrc(); }
      if (!img.naturalWidth || !viewport.clientWidth) return;
      const oldWidth = frame.clientWidth || 1, oldHeight = frame.clientHeight || 1;
      const cx = (viewport.scrollLeft + viewport.clientWidth / 2) / oldWidth;
      const cy = (viewport.scrollTop + viewport.clientHeight / 2) / oldHeight;
      const fitWidth = Math.min(img.naturalWidth, viewport.clientWidth - 2,
        window.innerHeight * .72 * img.naturalWidth / img.naturalHeight);
      editor.style.width = `${Math.max(1, fitWidth * zoom / 100)}px`;
      layoutView();
      viewport.scrollLeft = cx * frame.clientWidth - viewport.clientWidth / 2;
      viewport.scrollTop = cy * frame.clientHeight - viewport.clientHeight / 2;
    };
    zoomRange.addEventListener('input', () => setZoom(zoomRange.value));
    editor.addEventListener('pointerdown', (ev) => {
      if (!editing || ev.button !== 0) return;
      ev.preventDefault(); editor.setPointerCapture(ev.pointerId);
      drag = {x: ev.clientX, y: ev.clientY, shift: [...shift]};
    });
    editor.addEventListener('pointermove', (ev) => {
      if (!drag) return;
      const radians = viewRotation * Math.PI / 180;
      const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
      const imageDx = dx * Math.cos(radians) + dy * Math.sin(radians);
      const imageDy = -dx * Math.sin(radians) + dy * Math.cos(radians);
      const next = [Math.max(-1, Math.min(1, drag.shift[0] + imageDx / img.clientWidth)),
        Math.max(-1, Math.min(1, drag.shift[1] + imageDy / img.clientHeight))];
      const match = nearestSnap(next);
      shift = match ? [...match.shift] : next;
      showAdjustment(match);
    });
    const finishDrag = () => { if (drag) scheduleShapeSnap(0); drag = null; };
    editor.addEventListener('pointerup', finishDrag);
    editor.addEventListener('pointercancel', finishDrag);
    const toggleEdit = btn('Move outlines', () => {
      editing = !editing; editor.classList.toggle('editing', editing);
      toggleEdit.textContent = editing ? 'Finish moving' : 'Move outlines';
    });
    const resetShift = btn('Reset alignment', () => {
      shift = [0, 0]; rotation = 0; schemeScale = 100; mirrorHorizontal = mirrorVertical = false;
      rotationRange.value = 0; rotationNumber.value = '0';
      scaleRange.value = 100; scaleNumber.value = '100'; mirrorX.checked = mirrorY.checked = false;
      clearTimeout(snapTimer); ++snapRequest; snapStatus.textContent = '';
      showAdjustment();
    });
    img.addEventListener('load', () => {
      setZoom(zoom);
      imageStatus.className = 'alert ok';
      imageStatus.textContent = `Photo ${pair.photo_name} decoded (${pair.check.image_size.join(' × ')} px).`;
    });
    img.addEventListener('error', () => {
      imageStatus.className = 'alert bad';
      imageStatus.textContent = `Could not load the photo or overlay for ${pair.photo_name}. Review the pair again; measurement results are stored separately.`;
    });
    contours.addEventListener('error', () => {
      imageStatus.className = 'alert bad';
      imageStatus.textContent = 'Could not load LightBurn outlines. Review the photograph again.';
    });
    const refresh = () => { img.src = photoSrc(); contours.src = contourSrc(); };
    const layers = (pair.check?.layers || []).filter((l) => l.regions > 0);
    const layerPicker = h('select', {'aria-label': 'Layers shown on the photo', onChange: (ev) => { selectedLayer = ev.target.value; refresh(); }},
      [h('option', {value: 'all', selected: true}, 'All measured layers'),
        ...layers.map((l) => h('option', {value: l.index}, `${I18N.name(l.name)}${l.measured_lab ? '' : ' · measurement skipped'}`))]);
    const chartUsable = pair.check?.chart?.usable === true;
    const measuredLayers = layers.filter((l) => l.measured_lab != null);
    const skippedLayers = layers.filter((l) => l.measured_lab == null);
    const imageSize = pair.check?.image_size;
    const view = h('div', {class: 'card stack'}, h('h3', {}, 'What was measured in the photo'),
      imageStatus,
      h('div', {class: 'alert ' + (skippedLayers.length ? 'warn' : 'ok'), role: 'status'},
        `Recognition result: ${measuredLayers.length} of ${layers.length} layers measured` +
        (skippedLayers.length ? `; skipped: ${skippedLayers.map((l) => I18N.name(l.name)).join(', ')}.` : '.') +
        (imageSize ? ` Source photo size: ${imageSize[0]} × ${imageSize[1]} px.` : '')),
      h('p', {class: 'muted small'}, 'Colored outlines show complete LightBurn vectors at their original size. Color is measured inside shapes; edges and later engravings are excluded from the sample. Brightness adjustment affects the view only; results use the original RAW. ' + (pair.check?.alignment?.method === 'picture' ? 'Green lines are embedded-image outlines found in the photograph. The blue frame is the visible window that is measured; pink outlines continue beneath the frame and are inferred from distances, not measured.' : '')),
      h('div', {class: 'row'}, h('label', {class: 'f'}, h('span', {}, 'Show outlines'), layerPicker),
        btn('Before correction', () => { corrected = false; refresh(); }),
        chartUsable ? btn('After correction', () => { corrected = true; refresh(); })
          : h('span', {class: 'muted small'}, 'Color correction is unavailable: no separate calibration card was found in the photo. The photo itself was measured.'),
        btn(visibility === 'lifted' ? 'Normal brightness' : 'Increase brightness', () => { visibility = visibility === 'lifted' ? 'normal' : 'lifted'; refresh(); })),
      viewport,
      h('div', {class: 'row overlay-controls'}, h('span', {}, 'Rotate photo for viewing'), viewRange, Forms.describe(viewRange, 'viewRotation'),
        viewNumber, Forms.describe(viewNumber, 'viewRotation'), h('span', {}, '°'), viewNote,
        btn('−90°', () => setViewRotation((viewRotation + 270) % 360)),
        btn('+90°', () => setViewRotation((viewRotation + 90) % 360))),
      h('div', {class: 'row overlay-controls'}, h('span', {}, 'View zoom'), zoomRange, Forms.describe(zoomRange, 'viewZoom', {extra: 'step 25'}), zoomValue,
        zoomOut, zoomIn,
        btn('Fit', () => setZoom(100))));
    // the tool «Move and rotate layout»: it moves the whole overlay on the photograph and checks the pair again with the result
    const shiftCard = h('div', {class: 'card stack'}, h('h3', {}, 'Move, rotate, and scale the whole layout'),
      h('p', {class: 'muted small'}, 'All outlines move together; dimensions in the LightBurn file are preserved. You can also correct an alignment the program considers valid.'),
      h('div', {class: 'row overlay-controls'}, h('span', {}, 'Layout rotation on photo'), rotationRange, Forms.describe(rotationRange, 'schemeRotation'),
        rotationNumber, Forms.describe(rotationNumber, 'schemeRotation'), h('span', {}, '°'), rotationNote,
        btn('−90°', () => setRotation((rotation + 270) % 360)),
        btn('+90°', () => setRotation((rotation + 90) % 360))),
      h('div', {class: 'row overlay-controls'}, h('span', {}, 'Layout scale on photo'), scaleRange, Forms.describe(scaleRange, 'schemeScale'),
        scaleNumber, Forms.describe(scaleNumber, 'schemeScale'), h('span', {}, '%'), scaleNote,
        h('label', {class: 'row'}, mirrorX, h('span', {}, 'Mirror ↔')),
        h('label', {class: 'row'}, mirrorY, h('span', {}, 'Mirror ↕'))),
      h('div', {class: 'row'}, toggleEdit, h('label', {class: 'row'}, snap,
        h('span', {}, `Snap to recognized details (${baseSnapCandidates.length + vectorSnapMatches.length})`)),
        resetShift, saveShift),
      editorStatus,
      snapStatus);
    return {view, shiftCard};
  }

  function cornersCard(pair, run, existing = false) {
    let corners = null;
    const apply = btn('Apply alignment', () => run({corners_fraction: corners}, apply), '', true);
    const saved = pair.check?.alignment?.work_corners_fraction;
    const usableSaved = existing && Array.isArray(saved) && saved.length === 4 &&
      saved.every((point) => point.length === 2 && point.every((value) => Number.isFinite(value) && value >= 0 && value <= 1))
      ? saved : null;
    const initial = usableSaved ? (() => {
      const byY = [...usableSaved].sort((a, b) => a[1] - b[1]);
      const top = byY.slice(0, 2).sort((a, b) => a[0] - b[0]);
      const bottom = byY.slice(2).sort((a, b) => a[0] - b[0]);
      return [top[0], top[1], bottom[1], bottom[0]];
    })() : [[.08, .08], [.92, .08], [.92, .92], [.08, .92]];
    const picker = Corners.create(`/api/pairs/${pair.id}/photo.png`, initial,
      (c) => { corners = c; apply.disabled = !c; },
      existing ? 'These are the current corners of the entire work. Move an incorrect corner and apply; scale and perspective of all outlines are recalculated from the exact LightBurn dimensions.'
        : 'The initial frame is only a guide. Select each corner number and click its exact position or drag its point. Adjust all four corners.',
      {requireAllMoved: !existing, requireAnyMoved: existing});
    return {card: h('div', {class: 'card stack'}, h('h3', {}, 'Work corners on the photo'), picker.el, h('div', {class: 'row'}, apply)), get: () => corners};
  }

  /** The tool «Align by detail»: the operator puts four points on the corners of one detail of the file, and the rest of the drawing
      is placed from its known size and distances. Offered whether or not the automatic alignment succeeded: when it did, the details
      are listed where that alignment puts them, and the hand then decides (the server takes a detail placed by hand before any
      automatic method). The corners of a detail are numbered in the order its outline is walked, which the picker draws. */
  function elementAnchorCard(pair, candidates, run) {
    let selected = candidates[0], corners = selected.corners_fraction;
    const holder = h('div', {});
    const apply = btn('Align using selected detail', () => run({anchor: {
      layer_index: selected.layer_index, region_index: selected.region_index, corners_fraction: corners,
    }}, apply));
    const renderPicker = () => {
      corners = selected.corners_fraction;
      const picker = Corners.create(`/api/pairs/${pair.id}/photo.png`, corners,
        (value) => { corners = value; apply.disabled = !value; },
        'Move the four points to the corners of this specific detail. Their numbers follow the outline order. Its size and distances to other elements come from LightBurn.',
        {names: [1, 2, 3, 4].map((n) => `detail corner ${n}`)});
      holder.replaceChildren(picker.el);
      apply.disabled = false;
    };
    const describe = (item) => (item.shape_score != null ? `${item.element} · shape score ${num(item.shape_score, 3)}`
      : `${item.element} · ${num(item.area_mm2, 1)} mm²`);
    const choose = h('select', {'aria-label': 'Candidate detail', onChange: (ev) => {
      selected = candidates[Number(ev.target.value)]; renderPicker();
    }}, candidates.map((item, i) => h('option', {value: i}, describe(item))));
    renderPicker();
    const valid = pair.check?.alignment?.valid;
    return h('div', {class: 'card stack'}, h('h3', {}, 'Align using one detail'),
      h('p', {}, valid
        ? 'Alignment was found automatically. If a detail in the photo is not where the layout places it, mark its actual corners; the other outlines will be calculated from the file using that detail.'
        : 'Automatic verification of the whole geometry failed. Select the most recognizable detail and adjust its position on the photograph; the remaining outlines will be calculated from the file.'),
      choose, holder, h('div', {class: 'row'}, apply));
  }

  /** The tool's region: the details come from the server (``GET /pairs/{id}/anchor-candidates``) when the tool is opened, because they
      are drawn where the current alignment puts them. A matrix has no such tool (its grid is found whole), and a pair that was never
      checked has no photograph size to draw them on; both say so and point to the corners. */
  function anchorRegion(pair, run) {
    const host = h('div', {class: 'stack'});
    const say = (title, text, extra = null) => App.fill(host, h('div', {class: 'card stack'}, h('h3', {}, title), h('p', {class: 'small', role: 'status'}, text), extra));
    const title = 'Align using one detail';
    if (pair.matrix) say(title, 'A parameter matrix cannot be aligned by one detail: the entire grid is located together. Adjust its position using Work corners and its boundaries using Parameter matrix.');
    else if (!pair.check?.image_size) say(title, 'File details appear on the photograph after the first pair check. Check the pair first.');
    else {
      const load = async () => {
        say(title, 'Loading file details…');
        try {
          const found = (await App.get(`/pairs/${pair.id}/anchor-candidates`)).candidates || [];
          if (found.length) App.fill(host, elementAnchorCard(pair, found, run));
          else say(title, 'The file has no details large enough to mark four corners. Use “Work corners”.');
        } catch (e) { say(title, `Could not retrieve file details: ${I18N.tr(e.message)}`, btn('Retry', load)); }
      };
      load();
    }
    return host;
  }

  // -- what the frame hides, per side of the plate (REQ-024, REQ-027) ---------------------------------------------------
  const SIDES = [['left', 'left'], ['right', 'right'], ['top', 'top'], ['bottom', 'bottom']];

  /** Edges hidden by the frame by side, in mm. Missing frame edges use a disclosed 6% assumption for images or the plate edge for vectors; null indicates an older alignment record. */
  function hiddenMargins(alignment) {
    const mm = alignment && alignment.hidden_mm;
    if (!mm || typeof mm !== 'object' || Array.isArray(mm)) return null;
    if (alignment.method !== 'picture' && alignment.window_found === false) return null;     // no frame: nothing is hidden
    const found = alignment.frame_sides || {};
    return SIDES.filter(([k]) => mm[k] != null).map(([k, word]) => `${word} ${num(Math.max(mm[k], 0), 1)}`
      + (found[k] === false ? (alignment.method === 'picture' ? ' (frame edge not found; assumed 6%)' : ' (no frame)') : '')).join(' · ');
  }

  // -- settings the LightBurn file lacks, supplied by the operator with provenance (REQ-015, REQ-016) --------------------
  const SUPPLIED = {power: ['Power', '%'], frequency: ['Frequency', 'kHz'], speed: ['Speed', 'mm/s'],
    pulse_width: ['Pulse duration (Q-Pulse)', 'ns'], line_interval: ['Line spacing', 'mm'], passes: ['Passes', '']};
  const stamp = (iso) => (iso ? new Date(iso).toLocaleString('en-US', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : '');
  const shortName = (setting) => (setting === 'pulse_width' ? 'Q-Pulse' : SUPPLIED[setting][0].toLowerCase());
  let reopenSupplied = null;     // the layer whose value was just saved or removed: open again when the page is drawn after the check

  /** For each required setting absent from a layer file, the operator supplies a value. The server validates it and rechecks the pair; accepted observations retain the source of each setting. */
  async function suppliedSettingsCard(pair, reload) {
    // cleaning, markers and labels are never knowledge (DEC-027): only the layers measured as test features are offered
    const gaps = (pair.check?.layers || []).filter((l) => (l.missing_settings || []).length && (l.role || 'test feature') === 'test feature');
    if (!gaps.length || pair.matrix) return null;
    const device = gaps.some((l) => l.missing_settings.includes('pulse_width')) ? await App.get('/devices/' + pair.device_id).catch(() => null) : null;
    const steps = device ? device.passport.pulse_steps.map((s) => s.pulse_width_ns) : [];
    const listId = `pulse-steps-${pair.id}`;
    const opened = reopenSupplied && reopenSupplied.pair === pair.id ? reopenSupplied.key : null;
    reopenSupplied = null;
    const send = async (button, layer, setting, value, form = null) => {
      button.disabled = true;
      const status = h('span', {class: 'muted small', role: 'status'}, 'Saving and rechecking the pair…');
      button.after(status);
      try {
        await post(`/pairs/${pair.id}/supplied-settings`, {layer_index: layer.index, setting, value});
        reopenSupplied = {pair: pair.id, key: String(layer.index)};
        toast(value == null ? 'Entered value removed; pair rechecked' : 'Value saved as operator-entered; pair rechecked', 'ok');
        await reload();
      } catch (e) { status.remove(); button.disabled = false; if (form) form.fail(e); else fail(e); }
    };
    // the rule of each setting is the server's (ingest.supplied_value): power above 0 up to 100, speed and line interval above 0, passes from 1, the
    // frequency within the laser's own range and the pulse width among its steps (those two the server answers with the laser's numbers)
    const QUANTITY = {power: 'power', frequency: 'frequency', speed: 'speed', pulse_width: 'pulseWidth', line_interval: 'lineInterval', passes: 'passes'};
    const entry = (layer, setting) => {
      const [label, unit] = SUPPLIED[setting];
      const given = (layer.supplied_settings || {})[setting];
      if (given) {
        return h('div', {class: 'row small'}, h('strong', {}, `${label}: ${given.value}${unit ? ' ' + unit : ''}`),
          pill(`entered by operator${given.at ? ' · ' + stamp(given.at) : ''}`, 'warn'),
          btn('Remove', (ev) => { const self = ev.currentTarget; send(self, layer, setting, null); }, 'btn-small'));
      }
      const form = Forms.create();
      const input = Forms.numberInput(Forms.QUANTITIES[QUANTITY[setting]], {style: 'width:8em', list: setting === 'pulse_width' && steps.length ? listId : null});
      const byDefault = (layer.defaulted_settings || {})[setting];
      const boxed = form.add('value', byDefault ? `${label}, layer “${layer.name}”: not recorded in file; laser default ${byDefault.value}${unit ? ' ' + unit : ''}; another value`
        : `${label}, layer “${layer.name}”: absent from file`, input, {quantity: QUANTITY[setting], required: true});
      return h('div', {class: 'stack'}, h('div', {class: 'row small'}, boxed,
        btn('Save', (ev) => {
          const v = form.collect();
          if (!v) return;
          const self = ev.currentTarget;
          send(self, layer, setting, v.value, form);
        }, 'btn-small')), form.error);
    };
    return h('div', {class: 'card stack'}, h('h3', {}, 'Settings missing from the LightBurn file'),
      h('p', {class: 'muted small'}, 'Without these settings, the layer cannot be compared or included in the model. The app supplies only values specified in laser settings (currently the default Q-Pulse): LightBurn omits values equal to the default. '
        + 'If you know the setting used to engrave the layer, enter it. It is saved with an “entered by operator” label and timestamp, '
        + 'the pair is rechecked, and the accepted observation records which settings came from the file and which you entered. '
        + 'Values read from the file are unchanged.'
        + (steps.length ? ` The laser accepts pulse durations from ${Math.min(...steps)} to ${Math.max(...steps)} ns; manufacturer values: ${steps.join(', ')} ns.` : '')),
      steps.length ? h('datalist', {id: listId}, ...steps.map((v) => h('option', {value: v}))) : null,
      // a line per layer with what its file lacks, the fields under the line (findings-you-can-manage-short-lists-re-check, REQ-005)
      App.list({id: `ingest-supplied:${pair.id}`, items: gaps, key: (layer) => layer.index, open: gaps.length === 1 ? String(gaps[0].index) : opened,
        search: (layer) => layer.name, details: (layer) => h('div', {class: 'stack'}, ...layer.missing_settings.map((s) => entry(layer, s))),
        row: (layer) => {
          const given = layer.missing_settings.filter((s) => (layer.supplied_settings || {})[s]).length;
          return [h('span', {class: 'lst-text', title: layer.name}, layer.name), h('span', {class: 'muted small'}, 'not in file: ' + layer.missing_settings.map(shortName).join(', ')),
            given ? pill(`entered by operator: ${given}`, 'warn') : null];
        }}).el);
  }

  // -- a parameter matrix (LightBurn Material Test) read from its photograph (REQ-031) --------------------------------
  const MATRIX_PARAMS = [['power', 'Power, %'], ['speed', 'Speed, mm/s'], ['frequency', 'Frequency, kHz'], ['pulse_width', 'Q-Pulse, ns'],
    ['line_interval', 'Line spacing, mm'], ['passes', 'Passes']];
  const paramName = (p) => (MATRIX_PARAMS.find(([k]) => k === p) || [null, '—'])[1];

  function matrixGrid(pair) {
    const m = pair.matrix, s = m.spec, layers = (pair.check && pair.check.layers) || [];
    const fmt = (v, d) => (v == null ? '?' : num(v, d));
    const head = h('tr', {}, h('th', {}, `${paramName(s.y.param)} \\ ${paramName(s.x.param)}`),
      ...Array.from({length: m.cols}, (_, c) => h('th', {}, s.x.values ? fmt(s.x.values[c], s.x.decimals) : `${c + 1}`)));
    const rows = Array.from({length: m.rows}, (_, r) => h('tr', {}, h('th', {}, s.y.values ? fmt(s.y.values[r], s.y.decimals) : `${r + 1}`),
      ...Array.from({length: m.cols}, (_, c) => {
        const layer = layers.find((l) => l.index === r * m.cols + c);
        const lab = layer && (layer.measured_lab_against_clean || layer.measured_lab);
        return h('td', {title: lab ? `${I18N.name(layer.name)}: ${labText(lab)}` : 'not measured'}, lab ? swatch(lab) : '—');
      })));
    return h('div', {class: 'matrix-grid', style: 'overflow-x:auto'}, h('table', {class: 'small'}, h('thead', {}, head), h('tbody', {}, ...rows)));
  }

  function matrixCard(pair, reload) {
    const m = pair.matrix, s = m.spec;
    const f = Forms.create();
    const Q = Forms.QUANTITIES;
    const input = (q, value, attrs = {}) => Forms.numberInput(Q[q], {value: value == null ? '' : value, style: 'width:8em', ...attrs});
    const select = (current) => h('select', {}, h('option', {value: ''}, '— unknown —'),
      ...MATRIX_PARAMS.map(([k, label]) => h('option', {value: k, selected: k === current}, label)));
    const axis = (key, count, word) => {
      const a = s[key];
      const el = {param: select(a.param), first: input('matrixSetting', a.values ? a.values[0] : null), last: input('matrixSetting', a.values ? a.values[a.values.length - 1] : null)};
      el.row = h('div', {class: 'row small'}, h('strong', {}, `${word} (${count}):`), f.add(`${key}_param`, `${word}: setting`, el.param, {}),
        f.add(`${key}_first`, `${word}: ${count > 1 ? 'first value' : 'value'}`, el.first, {quantity: 'matrixSetting'}),
        ...(count > 1 ? [f.add(`${key}_last`, `${word}: last value`, el.last, {quantity: 'matrixSetting'})] : []));
      return el;
    };
    const x = axis('x', m.cols, 'Columns'), y = axis('y', m.rows, 'Rows');
    // the fixed settings: one box for each, drawn only for the settings that are not on an axis; a box that is not drawn is not read
    const fixed = {};
    const fixedField = {};
    const onAxis = (k) => k === (x.param.value || s.x.param) || k === (y.param.value || s.y.param);
    for (const [k, label] of MATRIX_PARAMS) {
      fixed[k] = input('matrixSetting', s.fixed ? s.fixed[k] : null);
      fixedField[k] = f.add(`fixed_${k}`, `Fixed setting: ${label}`, fixed[k], {quantity: 'matrixSetting',
        read: () => (onAxis(k) ? {ok: true, value: null} : Forms.readNumber(fixed[k], Q.matrixSetting, {}))});
    }
    const fixedRow = h('div', {class: 'row small'});
    const drawFixed = () => {
      fixedRow.replaceChildren(h('strong', {}, 'Fixed:'));
      for (const [k] of MATRIX_PARAMS) if (!onAxis(k)) fixedRow.append(fixedField[k]);
    };
    drawFixed();
    x.param.addEventListener('change', drawFixed); y.param.addEventListener('change', drawFixed);
    const wide = {style: 'width:5em'};
    const extent = {cols: input('matrixCount', m.cols, wide), rows: input('matrixCount', m.rows, wide), col_shift: input('matrixShift', 0, wide), row_shift: input('matrixShift', 0, wide),
      pitch: input('matrixPitch', s.pitch_mm)};
    // matrix.apply_edit: 1 to 900 cells in all, so the product of the two counts is the rule that no single box can state
    const cellsRead = () => {
      const cols = Forms.readNumber(extent.cols, Q.matrixCount, {required: true}), rows = Forms.readNumber(extent.rows, Q.matrixCount, {required: true});
      if (!cols.ok || !rows.ok) return {cols, rows};
      return cols.value * rows.value > 900 ? {cols, rows, product: `A matrix must have 1 to 900 cells: ${cols.value} × ${rows.value} = ${cols.value * rows.value}`} : {cols, rows};
    };
    const extentFields = {
      cols: f.add('cols', 'Columns', extent.cols, {quantity: 'matrixCount', required: true, read: () => { const r = cellsRead(); return r.product ? {ok: false, message: r.product} : r.cols; }}),
      rows: f.add('rows', 'Rows', extent.rows, {quantity: 'matrixCount', required: true, read: () => cellsRead().rows}),
      col_shift: f.add('col_shift', 'First cell shift right', extent.col_shift, {quantity: 'matrixShift', required: true}),
      row_shift: f.add('row_shift', 'First cell shift down', extent.row_shift, {quantity: 'matrixShift', required: true}),
      pitch: f.add('pitch', 'Cell pitch', extent.pitch, {quantity: 'matrixPitch'})};
    const edit = (v) => {
      const axisEdit = (key, count) => ({param: v[`${key}_param`] || null, first: v[`${key}_first`],
        last: count > 1 ? v[`${key}_last`] : v[`${key}_first`]});
      return {x: axisEdit('x', v.cols), y: axisEdit('y', v.rows),
        fixed: Object.fromEntries(MATRIX_PARAMS.map(([k]) => k).filter((k) => k !== x.param.value && k !== y.param.value).map((k) => [k, v[`fixed_${k}`]])),
        extent: {cols: v.cols, rows: v.rows, col_shift: v.col_shift, row_shift: v.row_shift}, pitch_mm: v.pitch};
    };
    const send = async (confirm, button) => {
      const v = f.collect();
      if (!v) return;
      button.disabled = true;
      const status = h('span', {class: 'muted small', role: 'status'}, 'Rebuilding the file and rechecking the photo…');
      button.after(status);
      try { await post(`/pairs/${pair.id}/matrix`, {edit: edit(v), confirm}); toast(confirm ? 'Settings confirmed and applied' : 'Corrections applied; photo rechecked', 'ok'); await reload(); }
      catch (e) { status.remove(); button.disabled = false; f.fail(e); }
    };
    const apply = btn('Apply corrections', (ev) => { const self = ev.currentTarget; send(false, self); });
    const confirmBtn = btn('Settings are correct', (ev) => { const self = ev.currentTarget; send(true, self); });
    const fit = m.axis_fit || {x: {}, y: {}};
    const labels = m.labels || {};
    const readings = (obj) => Object.entries(obj || {}).map(([k, v]) => `${+k + 1}: ${(v || []).join(' / ') || '—'}`).join(' · ');
    const others = (m.others || []);
    return h('div', {class: 'card stack'}, h('div', {class: 'row'}, h('h3', {}, 'Parameter matrix'), h('span', {class: 'spacer'}),
        m.confirmed ? pill(m.confirmed_at ? `settings confirmed ${stamp(m.confirmed_at)}` : 'settings confirmed', 'ok') : pill('settings await confirmation', 'warn')),
      // the generated file is a record of what the photograph and the operator said, never evidence of its own (REQ-036)
      h('p', {class: 'muted small'}, 'Cell settings were reconstructed from the matrix photograph and are confirmed by the operator; this pair’s LightBurn file was created from them '
        + 'and is not the original file. Observations record them as an operator-confirmed reconstruction.'),
      h('p', {class: 'small'}, `Grid ${m.cols} × ${m.rows}; outlines were found for ${m.outlined_cells} cells, and the rest were inferred from the grid. `
        + `Row labels: ${fit.y.read ?? 0} read, ${fit.y.agreeing ?? 0} agree; column labels: ${fit.x.read ?? 0} read, ${fit.x.agreeing ?? 0} agree. `
        + 'LightBurn spaces axis values evenly between first and last, so a misread label is reconstructed from the others.'
        + (m.ocr ? '' : ' Text recognition (Tesseract) is not installed on this computer; enter values yourself.')),
      s.missing && s.missing.length ? h('div', {class: 'alert warn'}, 'Missing: ', s.missing.map((x) => I18N.tr(x)).join('; '), '. Enter the missing values and select “Apply corrections”.') : null,
      s.unusual && s.unusual.length ? h('div', {class: 'alert warn'}, 'Unusual value, likely misread: ', s.unusual.map(paramName).join(', '), '. Check against the engraving.') : null,
      x.row, y.row, fixedRow,
      h('details', {}, h('summary', {}, 'Grid bounds and cell size'),
        h('div', {class: 'row small'}, extentFields.cols, extentFields.rows, extentFields.col_shift, extentFields.row_shift, extentFields.pitch),
        h('p', {class: 'muted small'}, 'If the grid is incomplete (pale edge cells) or includes extra cells, adjust row and column counts and the first-cell shift. Pitch changes only the appearance of the generated LightBurn file.')),
      f.error,
      h('div', {class: 'row'}, apply, confirmBtn),
      h('details', {}, h('summary', {}, 'Read from the photo'),
        h('p', {class: 'small'}, h('strong', {}, 'Above grid: '), (labels.header || []).join(' | ') || 'not read'),
        h('p', {class: 'small'}, h('strong', {}, 'Axis labels: '), [...(labels.x_title || []), ...(labels.y_title || [])].join(' | ') || 'not read'),
        h('p', {class: 'small'}, h('strong', {}, 'Rows: '), readings(labels.rows) || '—'),
        h('p', {class: 'small'}, h('strong', {}, 'Columns: '), readings(labels.cols) || '—')),
      pair.check ? h('div', {class: 'stack'}, h('h4', {}, 'Measured color of each cell'), matrixGrid(pair)) : null,
      others.length ? h('div', {class: 'stack'}, h('p', {class: 'small'}, `This photo has ${others.length} additional ${others.length === 1 ? 'matrix' : 'matrices'}; each can become a separate experiment.`),
        h('div', {class: 'row'}, ...others.map((o, k) => o.created_pair_id ? link('/ingest?pair=' + o.created_pair_id, `Matrix ${o.cols} × ${o.rows}: experiment #${o.created_pair_id}`)
          : btn(`Create experiment from matrix ${o.cols} × ${o.rows}`, async (ev) => {
            const self = ev.currentTarget;
            self.disabled = true;
            const end = App.landing(self);
            try {
              const created = await post(`/pairs/${pair.id}/matrix/others/${k}`);
              await post(`/pairs/${created.id}/check`, {});
              end.go('/ingest?pair=' + created.id, {title: 'Experiment created from matrix', message: `Experiment #${created.id} was created from the ${o.cols} × ${o.rows} matrix and checked. Open it, review its settings, and confirm.`, openLabel: 'Open experiment', goOptions: {}});
            } catch (e) { self.disabled = false; fail(e); }
          })))) : null);
  }

  /** How the photograph was aligned with the file, in words (the alignment method of the check). */
  const methodLabel = (alignment) => alignment.method === 'markers'
        ? `using markers${alignment.marker_count != null ? ` (${alignment.marker_count})` : ''}`
        : alignment.method === 'marker templates' ? 'using four marker patterns'
        : alignment.method === 'two marker + QR' ? (alignment.qr_used_as_anchor === false
          ? 'using two markers; QR confirmed the plate' : 'using two markers and the plate QR code')
        : alignment.method === 'picture' ? `using the embedded image (correlation ${num((alignment.picture || {}).zncc, 2)})`
        : alignment.method === 'picture at ruler scale' ? `using file images and ruler scale (matched images: ${((alignment.located || {}).pictures || []).length})`
        : alignment.method === 'element anchors' ? `using anchor elements (${(alignment.element_matches || []).length})`
        : alignment.method === 'geometry' ? `using design details (${(alignment.element_matches || []).length})`
        : alignment.method === 'single distinctive detail' ? 'using one distinctive detail'
        : alignment.method === 'element anchor' ? 'using a manually placed detail'
        : alignment.method === 'manual shift' ? 'corrected by moving the whole layout'
        : alignment.method === 'manual rotation' ? 'corrected by rotating the whole layout'
        : alignment.method === 'manual transform' ? 'corrected by scaling or mirroring the whole layout'
        : 'manually using corners';

  /** The long record of what the check found: the colour chart, the alignment and everything it was based on. Warnings and problems are not
      here: they are the header's blockers and notes (pair.review). */
  function resultsCard(check) {
    const relative = check.color_measurement && check.color_measurement.mode === 'raw_camera_relative';
    return h('div', {class: 'card stack'}, h('h3', {}, 'Check results'),
      h('p', {}, 'Color calibration card: ', relative ? pill(check.chart.detected ? 'not used; Lab relative to RAW camera' : 'not found; Lab relative to RAW camera', 'warn')
        : !check.chart.detected ? pill('not detected', 'bad')
        : check.chart.usable === false ? pill('candidate found; card not confirmed', 'bad') : pill('detected and verified', 'ok'),
        !relative && check.chart.residual != null ? ` · residual correction error ΔE ${num(check.chart.residual, 1)}${check.chart.max_residual != null ? ` (threshold ${num(check.chart.max_residual, 1)})` : ''}` : '',
        !relative && check.chart.grey_ramp ? h('span', {class: 'muted small'},
          ` · gray scale after correction L* ${check.chart.grey_ramp.corrected.map((v) => num(v, 0)).join(' · ')} (reference ${check.chart.grey_ramp.reference.map((v) => num(v, 0)).join(' · ')})`) : ''),
      h('p', {}, 'Alignment: ', check.alignment.valid ? pill(methodLabel(check.alignment), 'ok')
        : pill('not completed', 'warn')),
      ...(check.alignment.valid && check.alignment.residual_px != null ? [h('p', {},
        `Residual at reference marker edges: ${num(check.alignment.residual_px, 1)} px. · Dimensions come from LightBurn in millimeters${check.alignment.reflected ? ' · photo mirrored' : ''}.`)] : []),
      ...(check.alignment.valid && check.alignment.method === 'element anchors' && check.alignment.anchoring && check.alignment.anchoring.details ? (() => {
        const d = check.alignment.anchoring.details, c = d.counts, o = d.orientation;
        return [h('p', {},
          `File elements: ${c.anchor} anchors, ${c.confirmed} independently confirmed, ${c.computed} determined by calculation only, ${c['partly hidden']} partly and ${c.hidden} fully hidden under the frame. `
          + `Outline residual: median ${num(d.residual_median_mm, 2)} mm, 90% ${num(d.residual_p90_mm, 2)} mm. `
          + `Orientation: ${o.mirror ? 'mirrored' : 'normal'}${o.rotation_degrees ? `, rotation ${o.rotation_degrees}°` : ''}`
          + (o.margin != null ? `, margin over next candidate ${num(1 / o.margin, 1)}×.` : '; initialized from complete shapes and confirmed by elements.')),
          h('p', {class: 'small'},
            (d.window_found === false
              ? 'No frame was found in the photograph: the whole plate is measured. '
              : (hiddenMargins(check.alignment) ? `The frame hides plate edges, mm (approximately ±1): ${hiddenMargins(check.alignment)}. `
                : `The frame hides plate edges (mm, by corner, approximately ±1): ${d.plate_hidden_mm.map((v) => num(Math.round(Math.max(v, 0) * 2) / 2, 1)).join(' · ')}. `)
                + `Hidden areas are not measured; their position is calculated from distances between found elements, with statistical uncertainty up to ${num(d.hidden_uncertainty_mm, 2)} mm.`)
            + (d.extrapolation_mm && d.extrapolation_mm.median != null ? ` Holdout check: hiding the outer ${num(d.extrapolation_mm.ring * 100, 0)}% of the window and predicting it from the rest yields ${num(d.extrapolation_mm.median, 2)} mm median and ${num(d.extrapolation_mm.p90, 2)} mm 90th-percentile error. The strip under the frame is much narrower, so this is an upper estimate.` : ''))];
      })() : []),
      ...(check.alignment.valid && check.alignment.method === 'picture' && hiddenMargins(check.alignment) ? [h('p', {class: 'small'},
        `The frame hides image edges, mm (approximately ±1.5): ${hiddenMargins(check.alignment)}. Hidden areas are not measured.`)] : []),
      ...(check.alignment.anchoring && check.alignment.anchoring.refused && check.alignment.method !== 'element anchors' ? [h('p', {class: 'small'},
        `Automatic alignment using elements was not completed: ${I18N.tr(check.alignment.anchoring.refused)}.`)] : []),
      ...(check.alignment.geometry_confirmation && check.alignment.geometry_confirmation.refused && !check.alignment.valid ? [h('p', {class: 'small'},
        `A whole-shape match was found but not confirmed by file elements, so it was not used: ${I18N.tr(check.alignment.geometry_confirmation.refused)}.`)] : []),
      ...(check.alignment.valid && check.alignment.qr_used_as_anchor === false &&
          Math.hypot(...(check.alignment.qr_offset_px || [0, 0])) > 10 ? [h('p', {class: 'alert warn'},
        `The QR code confirms this file but is displaced from the main matrix by ${check.alignment.qr_offset_px.map((v) => num(v, 1)).join(', ')} px in the photo. Its outline and measurement were corrected separately; the rest of the layout uses markers and found vectors.`)] : []),
      ...(Object.keys(check.alignment.layer_offsets_px || {}).length ? [h('p', {},
        `Vector shapes separately refined ${Object.keys(check.alignment.layer_offsets_px).length} layers. Shifts apply to outlines and measurements; LightBurn shape dimensions are preserved.`),
        h('details', {}, h('summary', {}, 'Layer adjustments from photo'),
          ...Object.entries(check.alignment.layer_offsets_px).map(([index, value]) => h('p', {class: 'small'},
            `Layer ${index}: ${value.offset_px.join(', ')} px. · shape match ${num(value.shape_match, 3)} instead of ${num(value.baseline_match, 3)}`)))] : []),
      ...(Object.keys(check.alignment.marker_feature_adjustments || {}).length ? [h('p', {},
        `Corner markers and small inscriptions were refined from ${Object.keys(check.alignment.marker_feature_adjustments).length} visible fragments. A surviving edge suffices for right markers; invisible parts are not treated as found.`)] : []),
      ...((check.alignment.visible_right_surface_edge || []).length ? [h('p', {},
        'The right titanium edge was found in the photograph: outlines and measurements beyond it were excluded. Original LightBurn vector dimensions are unchanged.')] : []),
      ...(check.alignment.valid && check.alignment.vector_total != null ? [h('p', {},
        `Closed vectors: ${check.alignment.vector_found} of ${check.alignment.vector_total} distinguishable shapes found in the photo; each was checked separately by shape and fill, and the layer retains its settings.`),
        h('details', {}, h('summary', {}, 'Check of each closed vector'),
          ...((check.alignment.vector_matches || []).map((item) => h('p', {class: 'small'},
            `${item.element} · ${item.size_mm.join(' × ')} mm · ${item.status === 'found' ? 'found' : 'not confirmed'} · outline match ${num(item.edge_support, 3)} · fill contrast ${num(item.fill_contrast, 1)} · shift ${item.offset_px.join(', ')} px.`))))] : []),
      ...((check.alignment.marker_matches || check.alignment.element_matches || []).length ? [h('details', {},
        h('summary', {}, 'Matches found between file and photo'),
        ...(check.alignment.marker_matches || check.alignment.element_matches).map((item) => h('p', {},
          item.id != null ? `Marker ${item.id}: photo (${item.center_px.join(', ')}) · similarity ${num(item.score, 3)}`
            : `${item.element}: file (${item.center_mm.join(', ')} mm) → photo (${item.center_px.join(', ')} px.)`)))] : []));
  }

  function imageLayersCard(check) {
    const imageLayers = (check.layers || []).filter((l) => l.image);
    if (!imageLayers.length) return null;
    return (h('div', {class: 'card stack'}, h('h3', {}, 'Image layers'),
        ...imageLayers.map((l) => {
          const i = l.image, t = l.tonal;
          return h('div', {class: 'stack'},
            h('p', {}, `${l.name}: ${i.kind === 'depth' ? 'depth (3D slice)' : 'photo engraving'}, mode “${PhotoModes.label(i.dither)}”`
              + (i.dpi ? `, ${num(i.dpi, 0)} DPI` : '') + (i.line_interval_mm ? `, line spacing ${num(i.line_interval_mm, 4)} mm` : '')
              + (i.dot_width_mm != null ? `, dot width ${num(i.dot_width_mm, 3)} mm` : '')
              + (i.dot_correction ? ', dot correction enabled' : '') + (i.cleanup_pass ? ', cleaning pass included' : '')
              + (i.passes ? `, passes ${num(i.passes, 0)}` : '')
              + (i.min_power != null ? `, Min ${num(i.min_power, 1)}%` : '') + (i.max_power != null ? `, Max ${num(i.max_power, 1)}%` : '')
              + (i.cells_per_inch ? `, ${num(i.cells_per_inch, 0)} lines per inch, angle ${num(i.halftone_angle, 0)}°` : '')
              + (i.negative ? ', negative' : '') + (i.pass_through ? ', without LightBurn dithering (pass-through)' : '')
              + (i.overscan ? ', overscan enabled' : '') + '.'),
            PhotoModes.get(i.dither) ? h('p', {class: 'small muted'}, `${PhotoModes.get(i.dither).controls} Important settings: ${PhotoModes.get(i.dither).settings}. `
              + `Result ${PhotoModes.PREDICT[PhotoModes.get(i.dither).predict]}.`)
              : h('p', {class: 'small muted'}, 'This version does not recognize the mode: no description is invented, and layer settings are preserved as recorded.'),
            t ? h('p', {class: 'small'}, `Tone on metal: L* from ${num(t.dark_L, 0)} (dark image areas) to ${num(t.light_L, 0)} (light areas), range ${num(t.range_L, 0)}. `
              + `Gray-level correlation with lightness ${num(t.rho, 2)} (${t.evidence === 'clear' ? 'strong' : 'weak'}). `
              + 'Gray levels come from the image in the file, before LightBurn brightness, contrast, and gamma adjustments; dithering is not modeled. '
              + (i.kind === 'depth' ? 'For depth, lightness does not measure the outcome. ' : '')
              + (t.vertical_flip ? 'The image is overlaid vertically flipped for a better match to the photograph. ' : '')
              + (Object.keys(t.adjustments || {}).length
                ? `LightBurn image adjustments: ${Object.entries(t.adjustments).map(([k, v]) => `${{Gamma: 'gamma', Contrast: 'contrast', Brightness: 'brightness', EnhanceAmount: 'enhancement', EnhanceRadius: 'enhancement radius', EnhanceDenoise: 'denoising'}[k] || k} ${num(v, 2)}`).join(', ')}. `
                  + (t.adjustments_keep_order ? 'These preserve gray-level order, so correlation and lightness range remain valid; the gray scale is shown before adjustments.'
                    : 'Enhancement filters the image locally and is not modeled, so comparison with original gray levels is approximate.') : ''))
              : h('p', {class: 'muted small'}, 'No tonal profile was built: the file has no image or too few pixels are visible.'),
            t && t.bins && t.bins.length >= 4 ? (() => {
              const hasPower = t.bins.some((b) => b.power_pct != null);
              const pick = t.bins.filter((_, k) => k % Math.max(1, Math.ceil(t.bins.length / 8)) === 0);
              const cell = (text) => h('td', {}, text);
              return h('div', {class: 'stack'},
                h('p', {class: 'small muted'}, `Image gray level${hasPower ? ' → power (linear between the layer settings Min and Max: lightest gray is Min, darkest is Max)' : ''} → color on metal `
                  + `(L*a*b* relative to camera; correlation with gray: L* ${num(t.rho, 2)}, a* ${num(t.rho_a, 2)}, b* ${num(t.rho_b, 2)}, chroma ${num(t.rho_chroma, 2)}).`),
                h('table', {class: 'small'}, h('thead', {}, h('tr', {}, ...['Gray', hasPower ? 'Power, %' : null, 'L*', 'a*', 'b*', 'C*'].filter(Boolean).map((x) => h('th', {}, x)))),
                  h('tbody', {}, ...pick.map((b) => h('tr', {}, cell(num(b.gray, 2)), ...(hasPower ? [cell(num(b.power_pct, 1))] : []),
                    cell(num(b.L, 1)), cell(num(b.a, 1)), cell(num(b.b, 1)), cell(num(b.C, 1)))))));
            })() : null);
        })));
  }

  // -- what the acceptance records ------------------------------------------------------------------------------------------
  const COLOUR_BASIS = {reference_chart_corrected: 'calibrated against the reference chart in the photo',
    raw_camera_relative: 'relative to the RAW camera; excluded from standard predictions'};

  /** HOOK(ux-engraving-lifecycle-p0). The ONE place where an accepted pair hands over to what comes next. Today it says what was
      written and opens the analysis of the pair. The feature that returns to the originating work with a summary of prediction
      changes adds one call here, before the final ``go``: ``outcome`` is the answer of ``POST /pairs/{id}/accept`` (``work_review``
      is the conclusion written into the vector or photo-engraving work). Nothing else in this file needs to change for it. */
  async function afterAccepted(pair, outcome) {
    // ux-engraving-lifecycle-p0 REQ-002: a result that belongs to a vector work takes the operator back to that work with the summary
    if (typeof Lifecycle !== 'undefined' && Lifecycle.returnToWork(outcome.work_review)) return;
    toast(outcome.work_review ? `Observations accepted. The conclusion was saved to “${outcome.work_review.work}”` : 'Observations accepted', 'ok');
    go('/analysis/' + pair.id);
  }

  /** What the acceptance records, said before it happens and kept in view after it: where the result comes from (the files, what the
      operator confirmed or supplied), the rules the colour was measured by, and the engraved version it belongs to. Rejection keeps the
      same record: the pair stays in the audit with its check, its confirmations and the version, only the uploaded files go. */
  function provenanceCard(pair) {
    const check = pair.check || {}, layers = check.layers || [], confirmed = pair.file_confirmation;
    const measured = layers.filter((l) => l.measured_lab != null);
    const supplied = layers.reduce((n, l) => n + Object.keys(l.supplied_settings || {}).length, 0);
    const mode = check.color_measurement && check.color_measurement.mode;
    const experiment = link('/experiment/' + (pair.plan_id && pair.plan_mode !== 'Restored from file' ? 'plan-' + pair.plan_id : 'eng-' + pair.engraving_id),
      'open experiment');
    const fact = (label, ...body) => h('li', {}, h('strong', {}, label + ': '), ...body);
    const accepted = pair.status === 'Accepted';
    return h('div', {class: 'card stack'}, h('h3', {}, accepted ? 'What was recorded on acceptance' : 'What will be recorded on acceptance'),
      h('ul', {class: 'rv-facts'},
        fact('Engraving version', `${pair.engraving_title ? I18N.name(pair.engraving_title) : 'Engraving'} · ID ${String(pair.engraving_id || '').slice(0, 8)} · `, experiment),
        fact('Source files', `LightBurn «${pair.lightburn_name}», photo “${pair.photo_name}”`),
        confirmed ? fact('File confirmation', `«${confirmed.text}»${confirmed.at ? ' · ' + confirmed.at.slice(0, 16).replace('T', ' ') : ''}`) : null,
        fact('Alignment', check.alignment && check.alignment.valid ? methodLabel(check.alignment) : 'not completed'),
        fact('Measurement rules', `color ${COLOUR_BASIS[mode] || 'without a defined basis'}; measured layers: ${measured.length} of ${layers.length}. `
          + 'Cleaning, markers, and labels are recorded as auxiliary and excluded from the knowledge model.'),
        fact('Operator-supplied settings', supplied ? `${supplied}, marked “operator-supplied”` : 'none')));
  }

  /** An accepted pair: immutable. The stage bar shows everything done; the manual tools are in the correction, which is a new pair. */
  function acceptedView(pair) {
    return h('div', {class: 'stack'}, IngestStages.bar(pair.review.stages),
      h('div', {class: 'alert ok'}, 'Accepted measurements are immutable and contribute to laser knowledge.'),
      provenanceCard(pair),
      h('p', {class: 'muted small'}, 'Manual tools (corners, detail alignment, layout movement, matrix, layers, tasks) are available in a correction. It creates a new pair, '
        + 'while the accepted pair stays unchanged until the correction is accepted.'),
      h('div', {class: 'row'}, link('/analysis/' + pair.id, 'Open analysis'), link('/ingest?rephoto=' + pair.id, 'Photograph this work again'),
        btn('Correct this photo’s alignment', async (ev) => {
          const control = ev.currentTarget; control.disabled = true; control.textContent = 'Creating correction…';
          try { const revision = await post(`/pairs/${pair.id}/alignment-revisions`); go('/ingest?pair=' + revision.id); }
          catch (error) { control.disabled = false; control.textContent = 'Correct this photo’s alignment'; fail(error); }
        }),
        btn('Delete pair', () => confirmBox('Delete accepted pair',
          'The pair will be removed from the color map and recommendations. Uploaded file copies will be deleted; immutable measurements will remain in the audit.', 'Delete',
          async () => { await del('/pairs/' + pair.id); toast('Record deleted', 'ok'); go('/experiments'); }), 'danger')));
  }

  /** The tool regions that are not drawn from the check: what a manual tool says when the pair has nothing for it. */
  const explained = (title, text, ...more) => h('div', {class: 'card stack'}, h('h3', {}, title), h('p', {class: 'small'}, text), ...more);

  async function render(pair, reload) {
    if (pair.status === 'Accepted') return acceptedView(pair);
    const review = pair.review, check = pair.check;
    let stages = null;                 // the stage machine (ingest-stages.js); the actions below reach it once the page is built
    const status = h('p', {class: 'muted small', role: 'status', 'aria-live': 'polite'});
    // Every change of the alignment goes through here: the server recomputes the check and clears the review of the masks (see
    // pair_review.INVALIDATED_BY). While it runs nothing on the page can accept the pair; when it is done the page is drawn again from
    // the new state, so a stage left earlier never keeps an acceptance that the new result has not earned.
    const run = async (body, button) => {
      if (button) button.disabled = true;
      stages.setBusy(true);
      const start = Date.now();
      const tick = () => { status.className = 'muted small'; status.textContent = `Aligning photo and measuring layers… ${Math.floor((Date.now() - start) / 1000)} s`; };
      tick(); const timer = setInterval(tick, 1000);
      try {
        const checked = await post(`/pairs/${pair.id}/check`, body || {});
        clearInterval(timer);
        await reload();
        const problem = checked.check?.problems?.[0];
        toast(checked.status === 'Ready to accept' ? 'Alignment complete. Review the outlines on the photo and accept the observations.'
          : problem ? `Check complete: ${I18N.tr(problem)}` : 'Check complete; clarification is needed.',
        checked.status === 'Ready to accept' ? 'ok' : 'warn');
      } catch (e) {
        clearInterval(timer); status.className = 'alert bad'; status.textContent = `Check failed: ${e.message}`;
        stages.setBusy(false);
        if (button) button.disabled = false;
        fail(e);
      }
    };
    const identity = h('div', {class: 'card'}, h('h3', {}, pair.engraving_title ? I18N.name(pair.engraving_title) : (pair.rephoto_of ? 'Another photo of the same engraving' : 'Engraving')),
      h('p', {}, `LightBurn: ${pair.lightburn_name} · Photo: ${pair.photo_name}`),
      pair.plan_mode === 'Vector job' ? h('p', {class: 'small'}, 'Work: ', link('/vector?plan=' + pair.plan_id, `«${pair.plan_name}»`), '; the engraving conclusion will be saved to it on acceptance.') : null,
      pair.plan_mode === 'Photo engraving work' ? h('p', {class: 'small'}, 'Photo engraving work: ', link('/photo-engraving?work=' + pair.plan_id, `«${pair.plan_name}»`),
        '; on acceptance, each gray will be compared with the prediction on the Confirmation tab.') : null,
      pair.rephoto_of ? h('p', {class: 'muted small'}, `Original pair #${pair.rephoto_of} · LightBurn file, laser, lens, and titanium inherited.`,
        pair.plan_id ? ' ' : null, pair.plan_id ? link('/plans/' + pair.plan_id, pair.plan_mode === 'Restored from file' ? 'Plan restored from file' : 'Experiment plate') : null) : null,
      pair.correction_of ? h('p', {class: 'alert warn'}, `Alignment correction for photo #${pair.correction_of}. The previous result remains active until this correction is accepted; afterward it is excluded from conclusions and its history remains in the audit.`) : null,
      h('div', {class: 'row'},
        check ? btn('Check again', (ev) => { const self = ev.currentTarget; run({}, self); }) : null,
        check ? btn('Find again using RAW and LightBurn', (ev) => { const self = ev.currentTarget; run({reset_alignment: true}, self); }) : null,
        btn('Delete pair', () => confirmBox('Delete pair', 'This action cannot be undone.', 'Delete', async () => { await del('/pairs/' + pair.id); toast('Record deleted', 'ok'); go('/experiments'); }), 'danger')));

    // -- the panels of the four stages, built once; the stage bar only shows and hides them, so nothing typed into one is lost ------------
    const panels = {files: [], alignment: [], review: [], accept: []};
    const aligned = Boolean(check && check.alignment.image_to_mm);
    const view = aligned ? viewer(pair, reload, run) : null;
    // Older checks could mistake a LightBurn-omitted setting for a changed value. The original audit is preserved, but only measured
    // differences are shown as mismatches.
    const realDifferences = check ? (check.discrepancies || []).filter((d) => d.from_file != null) : [];
    const supplied = check ? await suppliedSettingsCard(pair, reload) : null;
    const suppliedBox = supplied ? h('details', {class: 'rv-more', open: (review.advisories || []).some((a) => a.code === 'settings_missing')},
      h('summary', {}, 'Enter missing layer settings'), supplied) : null;

    if (!check) {
      panels.files.push(h('p', {class: 'muted'}, 'Select “Check pair” to read layer settings, align the photo, and measure engraved areas.'));
      panels.alignment.push(h('p', {class: 'muted'}, 'Alignment appears after the first check. You can set work corners or align by a detail before checking.'));
      panels.review.push(h('p', {class: 'muted'}, 'Outlines and results appear on the photo after alignment.'));
      panels.accept.push(h('p', {class: 'muted'}, 'Only a checked pair can be accepted.'));
    } else {
      if (realDifferences.length) {
        const conf = pair.file_confirmation;
        panels.files.push(h('div', {class: 'card stack'}, h('h3', {}, 'Comparison with plate definition'),
          conf ? h('div', {class: 'alert ok'}, 'The file used has been confirmed. Actual differences in settings are retained below.')
            : h('div', {class: 'alert warn'}, 'File settings differ from the plate definition. Correct the pair or confirm the file used.'),
          IngestDialogs.discrepancyTable(realDifferences),
          conf ? h('p', {class: 'alert ok'}, `Confirmed: «${conf.text}» · ${conf.at.slice(0, 16).replace('T', ' ')}`)
            : h('div', {class: 'row'}, btn('Correct pair', () => IngestDialogs.fixFile(pair, reload)),
              btn('Confirm the file used', () => IngestDialogs.confirmFile(pair, {...check, discrepancies: realDifferences}, reload)))));
      }
      if (suppliedBox) panels.files.push(suppliedBox);
      if (!realDifferences.length && !suppliedBox) panels.files.push(h('p', {class: 'muted'}, 'Both files can be read. No differences from the plate or missing settings were found.'));
      panels.alignment.push(h('div', {class: 'card stack'}, h('h3', {}, 'Photo alignment with file'),
        h('p', {}, 'Alignment: ', check.alignment.valid ? pill(methodLabel(check.alignment), 'ok') : pill('not completed', 'warn'),
          check.alignment.valid && check.alignment.residual_px != null ? ` · marker edge residual ${num(check.alignment.residual_px, 1)} px` : ''),
        h('p', {class: 'muted small'}, check.alignment.valid
          ? 'You can adjust alignment manually even when it appears correct: use Work corners, Align by detail, or Move and rotate layout.'
          : 'The photo could not be aligned with the file. Set four work corners or align by one detail.'),
        h('details', {class: 'rv-more'}, h('summary', {}, 'Alignment and reference chart details'), resultsCard(check))));
      if (view) {
        panels.review.push(view.view);
        const composed = Composition.card(check, pair.id), images = imageLayersCard(check);
        panels.review.push(h('details', {class: 'card rv-more'}, h('summary', {}, 'Measured layers and metrics'),
          h('div', {class: 'stack'}, h('p', {class: 'small'}, 'File layers, their results, and engraving tasks are available in the tools above.'),
            h('div', {class: 'row'}, btn('Open file layers', () => stages.open('layers'))), composed, images)));
      } else panels.review.push(h('div', {class: 'alert warn'}, 'The photo is not aligned with the file yet. Outlines appear after alignment.'));
      panels.review.push(IngestStages.invalidation());
      panels.accept.push(provenanceCard(pair));
      panels.accept.push(h('div', {class: 'card stack'}, h('h3', {}, 'Reject result'),
        h('p', {class: 'small'}, 'If the photo or check is unsuitable, you can reject the result; it will be excluded from conclusions and laser knowledge. The pair record, check, '
          + 'confirmations, and engraving version remain in the audit; uploaded file copies are deleted.'),
        h('div', {class: 'row'}, btn('Reject result', () => confirmBox('Reject result',
          'This result will be excluded from conclusions and laser knowledge. The pair will be marked deleted and uploaded file copies removed. The pair record, check, confirmations, engraving version, and file names remain in the audit.',
          'Reject', async () => { await del('/pairs/' + pair.id); toast('Result rejected', 'ok'); go('/experiments'); }), 'danger'))));
      panels.accept.push(IngestStages.invalidation());
    }

    // -- the manual tools: always present, with or without a warning (DEC-001) -------------------------------------------------------------
    const layersCard = h('div', {class: 'card stack'}, h('h3', {}, 'File layers'),
      check ? IngestDialogs.layersTable(check.layers) : h('p', {class: 'muted small'}, 'Layers appear after the first check.'));
    const regions = {
      corners: {build: () => cornersCard(pair, run, aligned).card},
      anchor: {build: () => anchorRegion(pair, run)},
      shift: {el: view ? view.shiftCard : explained('Move, rotate, and scale the whole layout',
        'The layout can be moved once it is overlaid on the photo. Check the pair or set four work corners first.', btn('Open work corners', () => stages.open('corners')))},
      matrix: {el: pair.matrix ? matrixCard(pair, reload) : explained('Parameter matrix',
        'This pair is not a photo of a parameter matrix. Layer settings come from the LightBurn file; see File layers and enter any missing settings.',
        btn('Open file layers', () => stages.open('layers')))},
      layers: {el: layersCard},
      tasks: {el: IngestTasks.card(pair, reload)},          // REQ-020: task and evidence-backed metrics for each layer
    };
    const needsManualCorners = Boolean(check && !check.alignment.image_to_mm && !check.alignment.valid && Array.isArray(check.image_size));
    const opened = [...(needsManualCorners ? ['corners'] : []), ...(pair.matrix && !pair.matrix.confirmed ? ['matrix'] : [])];

    const actions = {
      check: (button) => run({}, button),
      restart: () => run({reset_alignment: true}),
      file: () => IngestDialogs.fixFile(pair, reload),
      file_confirm: () => IngestDialogs.confirmFile(pair, {...check, discrepancies: realDifferences}, reload),
      supplied: () => {
        if (!suppliedBox) { stages.open('layers'); return; }
        stages.show('files'); suppliedBox.open = true;
        const summary = suppliedBox.querySelector('summary'); if (summary) summary.focus();
      },
      masks: () => { stages.show('review'); stages.focusPrimary(); },
      reviewMasks: async (button) => {
        button.disabled = true;
        try { await post(`/pairs/${pair.id}/review-masks`); await reload(); } catch (e) { button.disabled = false; fail(e); }
      },
      // The server decides. A refusal (the pair changed since this page was drawn) is shown and the page is drawn again from the new state.
      accept: async (button) => {
        button.disabled = true;
        try { await afterAccepted(pair, await post(`/pairs/${pair.id}/accept`)); }
        catch (e) { fail(e); await reload(); }
      },
    };
    stages = IngestStages.shell({review, panels, regions, actions, status, open: opened,
      state: {checked: Boolean(check), ready: pair.status === 'Ready to accept', masksReviewed: Boolean(pair.masks_reviewed)}});
    return h('div', {class: 'stack'}, identity, stages.el);
  }
  return {render, matrixGrid, hiddenMargins};
})();
