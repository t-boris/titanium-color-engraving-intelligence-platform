/* Проверка пары: эталон, выравнивание, расхождения с платой, маски слоёв, принятие (REQ-001, REQ-009, REQ-015, DEC-017).
   Принять можно только после проверки без проблем, подтверждения файла при расхождении и проверки масок. */
'use strict';
const IngestReview = (() => {
  const {h, btn, link, pill, post, del, toast, fail, go, confirmBox, num, swatch, labText} = App;

  /** The photograph with the contours drawn over it, and the controls that move the whole overlay. Returns the viewer (the review
      stage) and the card of the overlay controls (the «Сдвиг и поворот схемы» tool). Both are drawn from the same state, so they stay in
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
    const imageStatus = h('div', {class: 'alert warn', role: 'status'}, `Загружается фото ${pair.photo_name} и наложение областей измерения…`);
    const img = h('img', {src: photoSrc(), alt: 'Фотография гравировки', loading: 'eager', draggable: 'false'});
    const contours = h('img', {class: 'vector-contours', src: contourSrc(), alt: '', draggable: 'false'});
    const editor = h('div', {class: 'overlay-editor'}, img, contours);
    const frame = h('div', {class: 'overlay-rotated-frame'}, editor);
    const viewport = h('div', {class: 'overlay-viewport'}, frame);
    const editorStatus = h('p', {class: 'muted small', role: 'status', 'aria-live': 'polite'},
      'Контуры связаны геометрией LightBurn. Включите перемещение, чтобы поправить всё наложение на фотографии.');
    const snapStatus = h('p', {class: 'muted small', role: 'status', 'aria-live': 'polite'}, '');
    const snap = h('input', {type: 'checkbox', checked: true});
    const saveShift = btn('Применить совмещение и пересчитать', (ev) => {
      const self = ev.currentTarget;
      run({translation_fraction: shift, rotation_degrees: rotation, scale_factor: schemeScale / 100,
        mirror_horizontal: mirrorHorizontal, mirror_vertical: mirrorVertical}, self);
    }, '', true);
    const rotationRange = h('input', {type: 'range', min: 0, max: 360, step: .1, value: 0,
      'aria-label': 'Поворот всей схемы относительно фотографии, градусы'});
    const rotationNumber = h('input', {type: 'number', min: 0, max: 360, step: .1, value: 0,
      'aria-label': 'Точный угол поворота, градусы'});
    const scaleRange = h('input', {type: 'range', min: 10, max: 800, step: 1, value: 100,
      'aria-label': 'Масштаб схемы относительно фотографии, проценты'});
    const scaleNumber = h('input', {type: 'number', min: 10, max: 800, step: .1, value: 100,
      'aria-label': 'Точный масштаб схемы, проценты'});
    const mirrorX = h('input', {type: 'checkbox', 'aria-label': 'Зеркально отразить схему по горизонтали'});
    const mirrorY = h('input', {type: 'checkbox', 'aria-label': 'Зеркально отразить схему по вертикали'});
    const showAdjustment = (match = null) => {
      const sx = (mirrorHorizontal ? -1 : 1) * schemeScale / 100;
      const sy = (mirrorVertical ? -1 : 1) * schemeScale / 100;
      contours.style.transform = `translate(${shift[0] * 100}%, ${shift[1] * 100}%) rotate(${rotation}deg) scale(${sx}, ${sy})`;
      saveShift.disabled = Math.hypot(...shift) < 1e-6 && (rotation % 360) === 0 &&
        schemeScale === 100 && !mirrorHorizontal && !mirrorVertical;
      const px = pair.check.image_size;
      editorStatus.textContent = match ? `Привязано к распознанной детали «${match.element}». Все контуры перемещены вместе.`
        : `Схема: ${schemeScale.toFixed(1)}%, поворот ${rotation.toFixed(1)}°` +
          `${mirrorHorizontal ? ', зеркало по горизонтали' : ''}${mirrorVertical ? ', зеркало по вертикали' : ''}. ` +
          `Сдвиг: ${(shift[0] * px[0]).toFixed(0)} × ${(shift[1] * px[1]).toFixed(0)} пикс. ` +
          'Размеры в файле LightBurn сохраняются.';
    };
    const baseSnapCandidates = (pair.check.alignment.snap_candidates || []).map((v) => ({
      element: `${v.element} · совпало деталей: ${v.support_count}`,
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
      snapStatus.textContent = 'Проверяем совпадение фигур на фотографии…';
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
            snapStatus.textContent = `Контуры привязаны по форме к «${best.element}»; совпало фигур: ${best.support_count}.`;
          } else {
            snapStatus.textContent = 'Рядом нет подтверждённого совпадения нескольких фигур. Передвиньте схему ближе к детали.';
          }
        } catch (error) {
          if (request === snapRequest) snapStatus.textContent = `Привязка по форме недоступна: ${error.message}`;
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
      'aria-label': 'Масштаб просмотра фотографии, проценты'});
    const zoomValue = h('span', {class: 'muted small', 'aria-live': 'polite'}, '100%');
    const zoomOut = btn('−', () => setZoom(zoom - 25)), zoomIn = btn('+', () => setZoom(zoom + 25));
    const viewRange = h('input', {type: 'range', min: 0, max: 360, step: .1, value: 0,
      'aria-label': 'Поворот фотографии для просмотра, градусы'});
    const viewNumber = h('input', {type: 'number', min: 0, max: 360, step: .1, value: 0,
      'aria-label': 'Точный угол поворота фотографии, градусы'});
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
      zoomValue.textContent = `${zoom}%${detailed ? ' · полный RAW' : ''}`;
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
    const toggleEdit = btn('Переместить контуры', () => {
      editing = !editing; editor.classList.toggle('editing', editing);
      toggleEdit.textContent = editing ? 'Завершить перемещение' : 'Переместить контуры';
    });
    const resetShift = btn('Сбросить совмещение', () => {
      shift = [0, 0]; rotation = 0; schemeScale = 100; mirrorHorizontal = mirrorVertical = false;
      rotationRange.value = 0; rotationNumber.value = '0';
      scaleRange.value = 100; scaleNumber.value = '100'; mirrorX.checked = mirrorY.checked = false;
      clearTimeout(snapTimer); ++snapRequest; snapStatus.textContent = '';
      showAdjustment();
    });
    img.addEventListener('load', () => {
      setZoom(zoom);
      imageStatus.className = 'alert ok';
      imageStatus.textContent = `Фото ${pair.photo_name} декодировано (${pair.check.image_size.join(' × ')} пикс.).`;
    });
    img.addEventListener('error', () => {
      imageStatus.className = 'alert bad';
      imageStatus.textContent = `Не удалось загрузить фото или наложение для ${pair.photo_name}. Повторите проверку пары; результаты измерений сохранены отдельно.`;
    });
    contours.addEventListener('error', () => {
      imageStatus.className = 'alert bad';
      imageStatus.textContent = 'Не удалось загрузить контуры LightBurn. Повторите проверку фотографии.';
    });
    const refresh = () => { img.src = photoSrc(); contours.src = contourSrc(); };
    const layers = (pair.check?.layers || []).filter((l) => l.regions > 0);
    const layerPicker = h('select', {'aria-label': 'Слои, показанные на фотографии', onChange: (ev) => { selectedLayer = ev.target.value; refresh(); }},
      [h('option', {value: 'all', selected: true}, 'Все измеренные слои'),
        ...layers.map((l) => h('option', {value: l.index}, `${I18N.name(l.name)}${l.measured_lab ? '' : ' · измерение пропущено'}`))]);
    const chartUsable = pair.check?.chart?.usable === true;
    const measuredLayers = layers.filter((l) => l.measured_lab != null);
    const skippedLayers = layers.filter((l) => l.measured_lab == null);
    const imageSize = pair.check?.image_size;
    const view = h('div', {class: 'card stack'}, h('h3', {}, 'Что измерено на фотографии'),
      imageStatus,
      h('div', {class: 'alert ' + (skippedLayers.length ? 'warn' : 'ok'), role: 'status'},
        `Результат распознавания: измерены ${measuredLayers.length} из ${layers.length} слоёв` +
        (skippedLayers.length ? `; пропущен: ${skippedLayers.map((l) => I18N.name(l.name)).join(', ')}.` : '.') +
        (imageSize ? ` Размер исходного фото: ${imageSize[0]} × ${imageSize[1]} пикс.` : '')),
      h('p', {class: 'muted small'}, 'Цветные контуры показывают полные векторы из LightBurn в их исходном размере. Цвет измеряется внутри фигур: края и последующие гравировки исключаются из пробы. Поднятие яркости меняет только просмотр; результаты рассчитаны по исходному RAW. ' + (pair.check?.alignment?.method === 'picture' ? 'Зелёные линии — контуры вложенной картинки, найденные на фото. Голубая рамка — видимое окно, оно и измеряется; розовым показано продолжение контуров под рамкой, это вывод по расстояниям, а не измерение.' : '')),
      h('div', {class: 'row'}, h('label', {class: 'f'}, h('span', {}, 'Показать контуры'), layerPicker),
        btn('До коррекции', () => { corrected = false; refresh(); }),
        chartUsable ? btn('После коррекции', () => { corrected = true; refresh(); })
          : h('span', {class: 'muted small'}, 'Цветовая коррекция недоступна: на фото не найдена отдельная калибровочная карта. Само фото при этом измерено.'),
        btn(visibility === 'lifted' ? 'Обычная яркость' : 'Поднять яркость', () => { visibility = visibility === 'lifted' ? 'normal' : 'lifted'; refresh(); })),
      viewport,
      h('div', {class: 'row overlay-controls'}, h('span', {}, 'Повернуть фото для просмотра'), viewRange, Forms.describe(viewRange, 'viewRotation'),
        viewNumber, Forms.describe(viewNumber, 'viewRotation'), h('span', {}, '°'), viewNote,
        btn('−90°', () => setViewRotation((viewRotation + 270) % 360)),
        btn('+90°', () => setViewRotation((viewRotation + 90) % 360))),
      h('div', {class: 'row overlay-controls'}, h('span', {}, 'Масштаб просмотра'), zoomRange, Forms.describe(zoomRange, 'viewZoom', {extra: 'шаг 25'}), zoomValue,
        zoomOut, zoomIn,
        btn('Вписать', () => setZoom(100))));
    // the tool «Сдвиг и поворот схемы»: it moves the whole overlay on the photograph and checks the pair again with the result
    const shiftCard = h('div', {class: 'card stack'}, h('h3', {}, 'Сдвиг, поворот и масштаб всей схемы'),
      h('p', {class: 'muted small'}, 'Все контуры двигаются вместе, размеры в файле LightBurn сохраняются. Можно поправить и совмещение, которое программа считает верным.'),
      h('div', {class: 'row overlay-controls'}, h('span', {}, 'Поворот схемы на фото'), rotationRange, Forms.describe(rotationRange, 'schemeRotation'),
        rotationNumber, Forms.describe(rotationNumber, 'schemeRotation'), h('span', {}, '°'), rotationNote,
        btn('−90°', () => setRotation((rotation + 270) % 360)),
        btn('+90°', () => setRotation((rotation + 90) % 360))),
      h('div', {class: 'row overlay-controls'}, h('span', {}, 'Масштаб схемы на фото'), scaleRange, Forms.describe(scaleRange, 'schemeScale'),
        scaleNumber, Forms.describe(scaleNumber, 'schemeScale'), h('span', {}, '%'), scaleNote,
        h('label', {class: 'row'}, mirrorX, h('span', {}, 'Зеркально ↔')),
        h('label', {class: 'row'}, mirrorY, h('span', {}, 'Зеркально ↕'))),
      h('div', {class: 'row'}, toggleEdit, h('label', {class: 'row'}, snap,
        h('span', {}, `Привязка к распознанным деталям (${baseSnapCandidates.length + vectorSnapMatches.length})`)),
        resetShift, saveShift),
      editorStatus,
      snapStatus);
    return {view, shiftCard};
  }

  function cornersCard(pair, run, existing = false) {
    let corners = null;
    const apply = btn('Применить выравнивание', () => run({corners_fraction: corners}, apply), '', true);
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
      existing ? 'Это текущие углы всей работы. Передвиньте неверный угол и примените: масштаб и перспектива всех контуров пересчитаются по точным размерам из LightBurn.'
        : 'Начальная рамка только для удобства. Выберите номер угла и щёлкните по точному углу работы либо перетащите точку. Нужно уточнить все четыре угла.',
      {requireAllMoved: !existing, requireAnyMoved: existing});
    return {card: h('div', {class: 'card stack'}, h('h3', {}, 'Углы работы на фотографии'), picker.el, h('div', {class: 'row'}, apply)), get: () => corners};
  }

  /** The tool «Привязка по детали»: the operator puts four points on the corners of one detail of the file, and the rest of the drawing
      is placed from its known size and distances. Offered whether or not the automatic alignment succeeded: when it did, the details
      are listed where that alignment puts them, and the hand then decides (the server takes a detail placed by hand before any
      automatic method). The corners of a detail are numbered in the order its outline is walked, which the picker draws. */
  function elementAnchorCard(pair, candidates, run) {
    let selected = candidates[0], corners = selected.corners_fraction;
    const holder = h('div', {});
    const apply = btn('Привязать по выбранной детали', () => run({anchor: {
      layer_index: selected.layer_index, region_index: selected.region_index, corners_fraction: corners,
    }}, apply));
    const renderPicker = () => {
      corners = selected.corners_fraction;
      const picker = Corners.create(`/api/pairs/${pair.id}/photo.png`, corners,
        (value) => { corners = value; apply.disabled = !value; },
        'Передвиньте четыре точки на углы этой конкретной детали. Номера точек идут в том порядке, в каком обходится её контур. Размер детали и расстояния до остальных элементов известны из LightBurn.',
        {names: [1, 2, 3, 4].map((n) => `угол ${n} детали`)});
      holder.replaceChildren(picker.el);
      apply.disabled = false;
    };
    const describe = (item) => (item.shape_score != null ? `${item.element} · оценка формы ${num(item.shape_score, 3)}`
      : `${item.element} · ${num(item.area_mm2, 1)} мм²`);
    const choose = h('select', {'aria-label': 'Кандидат на деталь', onChange: (ev) => {
      selected = candidates[Number(ev.target.value)]; renderPicker();
    }}, candidates.map((item, i) => h('option', {value: i}, describe(item))));
    renderPicker();
    const valid = pair.check?.alignment?.valid;
    return h('div', {class: 'card stack'}, h('h3', {}, 'Привязать по одной детали'),
      h('p', {}, valid
        ? 'Совмещение найдено автоматически. Если одна из деталей на фотографии лежит не там, где её нарисовала схема, поставьте точки на её настоящие углы: остальные контуры будут рассчитаны из файла по этой детали.'
        : 'Автоматическая проверка всей геометрии не прошла. Выберите наиболее узнаваемую деталь и уточните её положение на фотографии; остальные контуры будут рассчитаны из файла.'),
      choose, holder, h('div', {class: 'row'}, apply));
  }

  /** The tool's region: the details come from the server (``GET /pairs/{id}/anchor-candidates``) when the tool is opened, because they
      are drawn where the current alignment puts them. A matrix has no such tool (its grid is found whole), and a pair that was never
      checked has no photograph size to draw them on; both say so and point to the corners. */
  function anchorRegion(pair, run) {
    const host = h('div', {class: 'stack'});
    const say = (title, text, extra = null) => App.fill(host, h('div', {class: 'card stack'}, h('h3', {}, title), h('p', {class: 'small', role: 'status'}, text), extra));
    const title = 'Привязать по одной детали';
    if (pair.matrix) say(title, 'У матрицы параметров нет привязки по детали: сетка находится целиком. Поправьте её положение в «Углы работы», а границы сетки — в «Матрица параметров».');
    else if (!pair.check?.image_size) say(title, 'Детали файла показываются на фотографии после первой проверки пары. Сначала проверьте пару.');
    else {
      const load = async () => {
        say(title, 'Загружаем детали файла…');
        try {
          const found = (await App.get(`/pairs/${pair.id}/anchor-candidates`)).candidates || [];
          if (found.length) App.fill(host, elementAnchorCard(pair, found, run));
          else say(title, 'В файле нет деталей, достаточно крупных, чтобы поставить на их углы четыре точки. Используйте «Углы работы».');
        } catch (e) { say(title, `Не удалось получить детали файла: ${I18N.tr(e.message)}`, btn('Повторить', load)); }
      };
      load();
    }
    return host;
  }

  // -- what the frame hides, per side of the plate (REQ-024, REQ-027) ---------------------------------------------------
  const SIDES = [['left', 'слева'], ['right', 'справа'], ['top', 'сверху'], ['bottom', 'снизу']];

  /** Скрытые рамкой края по сторонам, мм. Где край рамки не найден: у картинки принято 6 % и так и сказано, у вектора
      это край пластины («рамки нет»). null — запись выравнивания старая и сторон не знает. */
  function hiddenMargins(alignment) {
    const mm = alignment && alignment.hidden_mm;
    if (!mm || typeof mm !== 'object' || Array.isArray(mm)) return null;
    if (alignment.method !== 'picture' && alignment.window_found === false) return null;     // no frame: nothing is hidden
    const found = alignment.frame_sides || {};
    return SIDES.filter(([k]) => mm[k] != null).map(([k, word]) => `${word} ${num(Math.max(mm[k], 0), 1)}`
      + (found[k] === false ? (alignment.method === 'picture' ? ' (край рамки не найден — принято 6 %)' : ' (рамки нет)') : '')).join(' · ');
  }

  // -- settings the LightBurn file lacks, supplied by the operator with provenance (REQ-015, REQ-016) --------------------
  const SUPPLIED = {power: ['Мощность', '%'], frequency: ['Частота', 'кГц'], speed: ['Скорость', 'мм/с'],
    pulse_width: ['Длительность импульса (Q-Pulse)', 'нс'], line_interval: ['Шаг линий', 'мм'], passes: ['Проходы', '']};
  const stamp = (iso) => (iso ? new Date(iso).toLocaleString('ru-RU', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : '');
  const shortName = (setting) => (setting === 'pulse_width' ? 'Q-Pulse' : SUPPLIED[setting][0].toLowerCase());
  let reopenSupplied = null;     // the layer whose value was just saved or removed: open again when the page is drawn after the check

  /** Слой, в файле которого нет обязательной настройки, получает поле ровно для неё. Само ничего не подставляется:
      оператор вводит значение, сервер проверяет его (ступени длительности, диапазон частот лазера), пара проверяется
      заново, а принятое наблюдение запоминает, какие настройки из файла и какие введены оператором. До принятия
      введённое можно убрать. */
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
      const status = h('span', {class: 'muted small', role: 'status'}, 'Сохраняем и перепроверяем пару…');
      button.after(status);
      try {
        await post(`/pairs/${pair.id}/supplied-settings`, {layer_index: layer.index, setting, value});
        reopenSupplied = {pair: pair.id, key: String(layer.index)};
        toast(value == null ? 'Введённое значение убрано, пара перепроверена' : 'Значение сохранено как введённое оператором, пара перепроверена', 'ok');
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
          pill(`введено оператором${given.at ? ' · ' + stamp(given.at) : ''}`, 'warn'),
          btn('Убрать', (ev) => { const self = ev.currentTarget; send(self, layer, setting, null); }, 'btn-small'));
      }
      const form = Forms.create();
      const input = Forms.numberInput(Forms.QUANTITIES[QUANTITY[setting]], {style: 'width:8em', list: setting === 'pulse_width' && steps.length ? listId : null});
      const byDefault = (layer.defaulted_settings || {})[setting];
      const boxed = form.add('value', byDefault ? `${label}, слой «${layer.name}»: в файле не записан, по умолчанию лазера ${byDefault.value}${unit ? ' ' + unit : ''}; другое значение`
        : `${label}, слой «${layer.name}»: нет в файле`, input, {quantity: QUANTITY[setting], required: true});
      return h('div', {class: 'stack'}, h('div', {class: 'row small'}, boxed,
        btn('Сохранить', (ev) => {
          const v = form.collect();
          if (!v) return;
          const self = ev.currentTarget;
          send(self, layer, setting, v.value, form);
        }, 'btn-small')), form.error);
    };
    return h('div', {class: 'card stack'}, h('h3', {}, 'Настройки, которых нет в файле LightBurn'),
      h('p', {class: 'muted small'}, 'Без них слой не сопоставим и не попадает в модель. Приложение подставляет только то, что задано в параметрах лазера (сейчас — Q-Pulse по умолчанию): LightBurn не записывает значение, равное умолчанию. '
        + 'Если вы знаете, с какой настройкой гравировался слой, впишите её. Она сохранится с пометкой «введено оператором» и временем, '
        + 'пара будет проверена заново, а принятое наблюдение запомнит, какие настройки взяты из файла, а какие введены вами. '
        + 'Значения, прочитанные из файла, не меняются.'
        + (steps.length ? ` Лазер принимает длительность импульса от ${Math.min(...steps)} до ${Math.max(...steps)} нс; в таблице производителя: ${steps.join(', ')} нс.` : '')),
      steps.length ? h('datalist', {id: listId}, ...steps.map((v) => h('option', {value: v}))) : null,
      // a line per layer with what its file lacks, the fields under the line (findings-you-can-manage-short-lists-re-check, REQ-005)
      App.list({id: `ingest-supplied:${pair.id}`, items: gaps, key: (layer) => layer.index, open: gaps.length === 1 ? String(gaps[0].index) : opened,
        search: (layer) => layer.name, details: (layer) => h('div', {class: 'stack'}, ...layer.missing_settings.map((s) => entry(layer, s))),
        row: (layer) => {
          const given = layer.missing_settings.filter((s) => (layer.supplied_settings || {})[s]).length;
          return [h('span', {class: 'lst-text', title: layer.name}, layer.name), h('span', {class: 'muted small'}, 'нет в файле: ' + layer.missing_settings.map(shortName).join(', ')),
            given ? pill(`введено оператором: ${given}`, 'warn') : null];
        }}).el);
  }

  // -- a parameter matrix (LightBurn Material Test) read from its photograph (REQ-031) --------------------------------
  const MATRIX_PARAMS = [['power', 'Мощность, %'], ['speed', 'Скорость, мм/с'], ['frequency', 'Частота, кГц'], ['pulse_width', 'Q-Pulse, нс'],
    ['line_interval', 'Шаг строк, мм'], ['passes', 'Проходы']];
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
        return h('td', {title: lab ? `${I18N.name(layer.name)}: ${labText(lab)}` : 'не измерено'}, lab ? swatch(lab) : '—');
      })));
    return h('div', {class: 'matrix-grid', style: 'overflow-x:auto'}, h('table', {class: 'small'}, h('thead', {}, head), h('tbody', {}, ...rows)));
  }

  function matrixCard(pair, reload) {
    const m = pair.matrix, s = m.spec;
    const f = Forms.create();
    const Q = Forms.QUANTITIES;
    const input = (q, value, attrs = {}) => Forms.numberInput(Q[q], {value: value == null ? '' : value, style: 'width:8em', ...attrs});
    const select = (current) => h('select', {}, h('option', {value: ''}, '— не знаю —'),
      ...MATRIX_PARAMS.map(([k, label]) => h('option', {value: k, selected: k === current}, label)));
    const axis = (key, count, word) => {
      const a = s[key];
      const el = {param: select(a.param), first: input('matrixSetting', a.values ? a.values[0] : null), last: input('matrixSetting', a.values ? a.values[a.values.length - 1] : null)};
      el.row = h('div', {class: 'row small'}, h('strong', {}, `${word} (${count}):`), f.add(`${key}_param`, `${word}: настройка`, el.param, {}),
        f.add(`${key}_first`, `${word}: ${count > 1 ? 'первое значение' : 'значение'}`, el.first, {quantity: 'matrixSetting'}),
        ...(count > 1 ? [f.add(`${key}_last`, `${word}: последнее значение`, el.last, {quantity: 'matrixSetting'})] : []));
      return el;
    };
    const x = axis('x', m.cols, 'По столбцам'), y = axis('y', m.rows, 'По строкам');
    // the fixed settings: one box for each, drawn only for the settings that are not on an axis; a box that is not drawn is not read
    const fixed = {};
    const fixedField = {};
    const onAxis = (k) => k === (x.param.value || s.x.param) || k === (y.param.value || s.y.param);
    for (const [k, label] of MATRIX_PARAMS) {
      fixed[k] = input('matrixSetting', s.fixed ? s.fixed[k] : null);
      fixedField[k] = f.add(`fixed_${k}`, `Постоянная настройка: ${label}`, fixed[k], {quantity: 'matrixSetting',
        read: () => (onAxis(k) ? {ok: true, value: null} : Forms.readNumber(fixed[k], Q.matrixSetting, {}))});
    }
    const fixedRow = h('div', {class: 'row small'});
    const drawFixed = () => {
      fixedRow.replaceChildren(h('strong', {}, 'Постоянные:'));
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
      return cols.value * rows.value > 900 ? {cols, rows, product: `В матрице от 1 до 900 ячеек: ${cols.value} × ${rows.value} = ${cols.value * rows.value}`} : {cols, rows};
    };
    const extentFields = {
      cols: f.add('cols', 'Столбцов', extent.cols, {quantity: 'matrixCount', required: true, read: () => { const r = cellsRead(); return r.product ? {ok: false, message: r.product} : r.cols; }}),
      rows: f.add('rows', 'Строк', extent.rows, {quantity: 'matrixCount', required: true, read: () => cellsRead().rows}),
      col_shift: f.add('col_shift', 'Сдвиг первой ячейки вправо', extent.col_shift, {quantity: 'matrixShift', required: true}),
      row_shift: f.add('row_shift', 'Сдвиг первой ячейки вниз', extent.row_shift, {quantity: 'matrixShift', required: true}),
      pitch: f.add('pitch', 'Шаг ячеек', extent.pitch, {quantity: 'matrixPitch'})};
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
      const status = h('span', {class: 'muted small', role: 'status'}, 'Пересобираем файл и перепроверяем фото…');
      button.after(status);
      try { await post(`/pairs/${pair.id}/matrix`, {edit: edit(v), confirm}); toast(confirm ? 'Параметры подтверждены и применены' : 'Исправления применены, фото перепроверено', 'ok'); await reload(); }
      catch (e) { status.remove(); button.disabled = false; f.fail(e); }
    };
    const apply = btn('Применить исправления', (ev) => { const self = ev.currentTarget; send(false, self); });
    const confirmBtn = btn('Параметры верны', (ev) => { const self = ev.currentTarget; send(true, self); });
    const fit = m.axis_fit || {x: {}, y: {}};
    const labels = m.labels || {};
    const readings = (obj) => Object.entries(obj || {}).map(([k, v]) => `${+k + 1}: ${(v || []).join(' / ') || '—'}`).join(' · ');
    const others = (m.others || []);
    return h('div', {class: 'card stack'}, h('div', {class: 'row'}, h('h3', {}, 'Матрица параметров'), h('span', {class: 'spacer'}),
        m.confirmed ? pill(m.confirmed_at ? `параметры подтверждены ${stamp(m.confirmed_at)}` : 'параметры подтверждены', 'ok') : pill('параметры ждут подтверждения', 'warn')),
      // the generated file is a record of what the photograph and the operator said, never evidence of its own (REQ-036)
      h('p', {class: 'muted small'}, 'Настройки ячеек восстановлены по фотографии матрицы и подтверждаются оператором; файл LightBurn этой пары создан из них '
        + 'и не является исходным файлом. В наблюдениях они записываются как восстановление, подтверждённое оператором.'),
      h('p', {class: 'small'}, `Сетка ${m.cols} × ${m.rows}; очертания найдены у ${m.outlined_cells} ячеек, остальные достроены по решётке. `
        + `Подписи строк: прочитано ${fit.y.read ?? 0}, согласуются ${fit.y.agreeing ?? 0}; подписи столбцов: прочитано ${fit.x.read ?? 0}, согласуются ${fit.x.agreeing ?? 0}. `
        + 'Значения по осям LightBurn делит равномерно между первым и последним, поэтому неверно прочитанная подпись восстанавливается по остальным.'
        + (m.ocr ? '' : ' Распознавание текста (tesseract) на этом компьютере не установлено: введите значения сами.')),
      s.missing && s.missing.length ? h('div', {class: 'alert warn'}, 'Не хватает: ', s.missing.map((x) => I18N.tr(x)).join('; '), '. Введите недостающее и нажмите «Применить исправления».') : null,
      s.unusual && s.unusual.length ? h('div', {class: 'alert warn'}, 'Необычное значение, вероятно прочитано неверно: ', s.unusual.map(paramName).join(', '), '. Сверьте с гравировкой.') : null,
      x.row, y.row, fixedRow,
      h('details', {}, h('summary', {}, 'Границы сетки и размер ячейки'),
        h('div', {class: 'row small'}, extentFields.cols, extentFields.rows, extentFields.col_shift, extentFields.row_shift, extentFields.pitch),
        h('p', {class: 'muted small'}, 'Если сетка найдена не целиком (бледные ячейки у края) или захватила лишнее, поправьте число столбцов и строк и сдвиг первой ячейки. Шаг влияет только на вид созданного файла LightBurn.')),
      f.error,
      h('div', {class: 'row'}, apply, confirmBtn),
      h('details', {}, h('summary', {}, 'Что прочитано с фотографии'),
        h('p', {class: 'small'}, h('strong', {}, 'Над сеткой: '), (labels.header || []).join(' | ') || 'не прочитано'),
        h('p', {class: 'small'}, h('strong', {}, 'Подписи осей: '), [...(labels.x_title || []), ...(labels.y_title || [])].join(' | ') || 'не прочитаны'),
        h('p', {class: 'small'}, h('strong', {}, 'Строки: '), readings(labels.rows) || '—'),
        h('p', {class: 'small'}, h('strong', {}, 'Столбцы: '), readings(labels.cols) || '—')),
      pair.check ? h('div', {class: 'stack'}, h('h4', {}, 'Измеренный цвет каждой ячейки'), matrixGrid(pair)) : null,
      others.length ? h('div', {class: 'stack'}, h('p', {class: 'small'}, `На этом снимке ещё ${others.length} ${others.length === 1 ? 'матрица' : 'матрицы'}: каждая может стать своим экспериментом.`),
        h('div', {class: 'row'}, ...others.map((o, k) => o.created_pair_id ? link('/ingest?pair=' + o.created_pair_id, `Матрица ${o.cols} × ${o.rows}: эксперимент №${o.created_pair_id}`)
          : btn(`Создать эксперимент из матрицы ${o.cols} × ${o.rows}`, async (ev) => {
            const self = ev.currentTarget;
            self.disabled = true;
            const end = App.landing(self);
            try {
              const created = await post(`/pairs/${pair.id}/matrix/others/${k}`);
              await post(`/pairs/${created.id}/check`, {});
              end.go('/ingest?pair=' + created.id, {title: 'Эксперимент из матрицы создан', message: `Эксперимент №${created.id} создан из матрицы ${o.cols} × ${o.rows} и проверен. Откройте его, проверьте параметры и подтвердите.`, openLabel: 'Открыть эксперимент', goOptions: {}});
            } catch (e) { self.disabled = false; fail(e); }
          })))) : null);
  }

  /** How the photograph was aligned with the file, in words (the alignment method of the check). */
  const methodLabel = (alignment) => alignment.method === 'markers'
        ? `по маркерам${alignment.marker_count != null ? ` (${alignment.marker_count})` : ''}`
        : alignment.method === 'marker templates' ? 'по узорам 4 меток'
        : alignment.method === 'two marker + QR' ? (alignment.qr_used_as_anchor === false
          ? 'по двум меткам; QR подтвердил плату' : 'по двум меткам и QR-коду платы')
        : alignment.method === 'picture' ? `по вложенной картинке (корреляция ${num((alignment.picture || {}).zncc, 2)})`
        : alignment.method === 'picture at ruler scale' ? `по картинкам файла и масштабу линейки (совпало картинок: ${((alignment.located || {}).pictures || []).length})`
        : alignment.method === 'element anchors' ? `по элементам-якорям (${(alignment.element_matches || []).length})`
        : alignment.method === 'geometry' ? `по деталям рисунка (${(alignment.element_matches || []).length})`
        : alignment.method === 'single distinctive detail' ? 'по одной характерной детали'
        : alignment.method === 'element anchor' ? 'по детали, поставленной вручную'
        : alignment.method === 'manual shift' ? 'поправлено перемещением всей схемы'
        : alignment.method === 'manual rotation' ? 'поправлено поворотом всей схемы'
        : alignment.method === 'manual transform' ? 'поправлено масштабом или зеркалом всей схемы'
        : 'вручную по углам';

  /** The long record of what the check found: the colour chart, the alignment and everything it was based on. Warnings and problems are not
      here: they are the header's blockers and notes (pair.review). */
  function resultsCard(check) {
    const relative = check.color_measurement && check.color_measurement.mode === 'raw_camera_relative';
    return h('div', {class: 'card stack'}, h('h3', {}, 'Результаты проверки'),
      h('p', {}, 'Калибровочная карта цвета: ', relative ? pill(check.chart.detected ? 'не использована; Lab относительно RAW-камеры' : 'не найдена; Lab относительно RAW-камеры', 'warn')
        : !check.chart.detected ? pill('не обнаружена', 'bad')
        : check.chart.usable === false ? pill('кандидат найден, карта не подтверждена', 'bad') : pill('обнаружена и проверена', 'ok'),
        !relative && check.chart.residual != null ? ` · остаточная ошибка коррекции ΔE ${num(check.chart.residual, 1)}${check.chart.max_residual != null ? ` (порог ${num(check.chart.max_residual, 1)})` : ''}` : '',
        !relative && check.chart.grey_ramp ? h('span', {class: 'muted small'},
          ` · серая шкала после коррекции L* ${check.chart.grey_ramp.corrected.map((v) => num(v, 0)).join(' · ')} (эталон ${check.chart.grey_ramp.reference.map((v) => num(v, 0)).join(' · ')})`) : ''),
      h('p', {}, 'Выравнивание: ', check.alignment.valid ? pill(methodLabel(check.alignment), 'ok')
        : pill('не выполнено', 'warn')),
      ...(check.alignment.valid && check.alignment.residual_px != null ? [h('p', {},
        `Остаток по краям опорных меток: ${num(check.alignment.residual_px, 1)} пикс. · Размеры взяты из LightBurn в миллиметрах${check.alignment.reflected ? ' · фотография отражена' : ''}.`)] : []),
      ...(check.alignment.valid && check.alignment.method === 'element anchors' && check.alignment.anchoring && check.alignment.anchoring.details ? (() => {
        const d = check.alignment.anchoring.details, c = d.counts, o = d.orientation;
        return [h('p', {},
          `Элементы файла: ${c.anchor} опорных, ${c.confirmed} подтверждены независимо, ${c.computed} определены только расчётом, ${c['partly hidden']} частично и ${c.hidden} целиком под рамкой. `
          + `Остаток контуров: медиана ${num(d.residual_median_mm, 2)} мм, 90% ${num(d.residual_p90_mm, 2)} мм. `
          + `Ориентация: ${o.mirror ? 'зеркальная' : 'прямая'}${o.rotation_degrees ? `, поворот ${o.rotation_degrees}°` : ''}`
          + (o.margin != null ? `, запас над следующим вариантом ${num(1 / o.margin, 1)}×.` : '; старт по целым фигурам, подтверждён элементами.')),
          h('p', {class: 'small'},
            (d.window_found === false
              ? 'Рамка на фотографии не найдена: измеряется вся пластина. '
              : (hiddenMargins(check.alignment) ? `Рамка закрывает края пластины, мм (ориентировочно ±1): ${hiddenMargins(check.alignment)}. `
                : `Рамка закрывает края пластины (мм, по углам, ориентировочно ±1): ${d.plate_hidden_mm.map((v) => num(Math.round(Math.max(v, 0) * 2) / 2, 1)).join(' · ')}. `)
                + `Скрытое не измеряется: его положение вычислено по расстояниям между найденными элементами, статистическая погрешность до ${num(d.hidden_uncertainty_mm, 2)} мм.`)
            + (d.extrapolation_mm && d.extrapolation_mm.median != null ? ` Строгая проверка: если спрятать внешние ${num(d.extrapolation_mm.ring * 100, 0)}% окна и предсказать их по остальным, ошибка предсказания ${num(d.extrapolation_mm.median, 2)} мм (медиана), ${num(d.extrapolation_mm.p90, 2)} мм (90%). Полоса под рамкой намного уже, так что это оценка сверху.` : ''))];
      })() : []),
      ...(check.alignment.valid && check.alignment.method === 'picture' && hiddenMargins(check.alignment) ? [h('p', {class: 'small'},
        `Рамка закрывает края картинки, мм (ориентировочно ±1,5): ${hiddenMargins(check.alignment)}. Скрытое не измеряется.`)] : []),
      ...(check.alignment.anchoring && check.alignment.anchoring.refused && check.alignment.method !== 'element anchors' ? [h('p', {class: 'small'},
        `Автоматическое выравнивание по элементам не выполнено: ${I18N.tr(check.alignment.anchoring.refused)}.`)] : []),
      ...(check.alignment.geometry_confirmation && check.alignment.geometry_confirmation.refused && !check.alignment.valid ? [h('p', {class: 'small'},
        `Совпадение целых фигур найдено, но элементы файла его не подтвердили, и оно не использовано: ${I18N.tr(check.alignment.geometry_confirmation.refused)}.`)] : []),
      ...(check.alignment.valid && check.alignment.qr_used_as_anchor === false &&
          Math.hypot(...(check.alignment.qr_offset_px || [0, 0])) > 10 ? [h('p', {class: 'alert warn'},
        `QR-код подтверждает этот файл, но на фото он сдвинут относительно основной матрицы на ${check.alignment.qr_offset_px.map((v) => num(v, 1)).join(', ')} пикс. Его контур и измерение поправлены отдельно; остальная схема совмещена по меткам и найденным векторам.`)] : []),
      ...(Object.keys(check.alignment.layer_offsets_px || {}).length ? [h('p', {},
        `По форме векторов отдельно уточнены ${Object.keys(check.alignment.layer_offsets_px).length} слоёв. Сдвиги применены и к контурам, и к измерениям; размеры фигур LightBurn сохранены.`),
        h('details', {}, h('summary', {}, 'Поправки слоёв по фотографии'),
          ...Object.entries(check.alignment.layer_offsets_px).map(([index, value]) => h('p', {class: 'small'},
            `Слой ${index}: ${value.offset_px.join(', ')} пикс. · совпадение формы ${num(value.shape_match, 3)} вместо ${num(value.baseline_match, 3)}`)))] : []),
      ...(Object.keys(check.alignment.marker_feature_adjustments || {}).length ? [h('p', {},
        `Угловые метки и мелкие надписи уточнены по ${Object.keys(check.alignment.marker_feature_adjustments).length} видимым фрагментам. Для правых меток достаточно сохранившейся кромки; невидимая часть не считается найденной.`)] : []),
      ...((check.alignment.visible_right_surface_edge || []).length ? [h('p', {},
        'Правый край титана найден на фотографии: контуры и измерения за этим краем исключены. Размеры исходных векторов LightBurn не изменены.')] : []),
      ...(check.alignment.valid && check.alignment.vector_total != null ? [h('p', {},
        `Замкнутые векторы: найдены на фото ${check.alignment.vector_found} из ${check.alignment.vector_total} различимых фигур; каждая проверена отдельно по форме и заливке, слой хранит её параметры.`),
        h('details', {}, h('summary', {}, 'Проверка каждого замкнутого вектора'),
          ...((check.alignment.vector_matches || []).map((item) => h('p', {class: 'small'},
            `${item.element} · ${item.size_mm.join(' × ')} мм · ${item.status === 'found' ? 'найден' : 'не подтверждён'} · совпадение контура ${num(item.edge_support, 3)} · контраст заливки ${num(item.fill_contrast, 1)} · сдвиг ${item.offset_px.join(', ')} пикс.`))))] : []),
      ...((check.alignment.marker_matches || check.alignment.element_matches || []).length ? [h('details', {},
        h('summary', {}, 'Найденные соответствия файла и фотографии'),
        ...(check.alignment.marker_matches || check.alignment.element_matches).map((item) => h('p', {},
          item.id != null ? `Метка ${item.id}: фото (${item.center_px.join(', ')}) · сходство ${num(item.score, 3)}`
            : `${item.element}: файл (${item.center_mm.join(', ')} мм) → фото (${item.center_px.join(', ')} пикс.)`)))] : []));
  }

  function imageLayersCard(check) {
    const imageLayers = (check.layers || []).filter((l) => l.image);
    if (!imageLayers.length) return null;
    return (h('div', {class: 'card stack'}, h('h3', {}, 'Слои-изображения'),
        ...imageLayers.map((l) => {
          const i = l.image, t = l.tonal;
          return h('div', {class: 'stack'},
            h('p', {}, `${l.name}: ${i.kind === 'depth' ? 'глубина (3D-слайс)' : 'фотогравировка'}, режим «${PhotoModes.label(i.dither)}»`
              + (i.dpi ? `, ${num(i.dpi, 0)} DPI` : '') + (i.line_interval_mm ? `, интервал строк ${num(i.line_interval_mm, 4)} мм` : '')
              + (i.dot_width_mm != null ? `, ширина точки ${num(i.dot_width_mm, 3)} мм` : '')
              + (i.dot_correction ? ', поправка точки включена' : '') + (i.cleanup_pass ? ', есть проход очистки' : '')
              + (i.passes ? `, проходов ${num(i.passes, 0)}` : '')
              + (i.min_power != null ? `, Min ${num(i.min_power, 1)}%` : '') + (i.max_power != null ? `, Max ${num(i.max_power, 1)}%` : '')
              + (i.cells_per_inch ? `, ${num(i.cells_per_inch, 0)} линий на дюйм, угол ${num(i.halftone_angle, 0)}°` : '')
              + (i.negative ? ', негатив' : '') + (i.pass_through ? ', без растрирования LightBurn (pass-through)' : '')
              + (i.overscan ? ', перебег за края строки (overscan) включён' : '') + '.'),
            PhotoModes.get(i.dither) ? h('p', {class: 'small muted'}, `${PhotoModes.get(i.dither).controls} Важные настройки: ${PhotoModes.get(i.dither).settings}. `
              + `Результат ${PhotoModes.PREDICT[PhotoModes.get(i.dither).predict]}.`)
              : h('p', {class: 'small muted'}, 'Этот режим версия не знает: описание не придумывается, настройки слоя сохранены как есть.'),
            t ? h('p', {class: 'small'}, `Тон на металле: L* от ${num(t.dark_L, 0)} (тёмные места картинки) до ${num(t.light_L, 0)} (светлые), размах ${num(t.range_L, 0)}. `
              + `Связь серого уровня с яркостью ${num(t.rho, 2)} (${t.evidence === 'clear' ? 'уверенная' : 'слабая'}). `
              + 'Серые уровни взяты из картинки в файле, до яркости, контраста и гаммы LightBurn; растрирование не моделируется. '
              + (i.kind === 'depth' ? 'Для глубины яркость не мера результата. ' : '')
              + (t.vertical_flip ? 'Картинка наложена перевёрнутой по вертикали: так лучше совпадает с фото. ' : '')
              + (Object.keys(t.adjustments || {}).length
                ? `Поправки LightBurn к картинке: ${Object.entries(t.adjustments).map(([k, v]) => `${{Gamma: 'гамма', Contrast: 'контраст', Brightness: 'яркость', EnhanceAmount: 'усиление', EnhanceRadius: 'радиус усиления', EnhanceDenoise: 'шумоподавление'}[k] || k} ${num(v, 2)}`).join(', ')}. `
                  + (t.adjustments_keep_order ? 'Они не меняют порядок серых уровней, поэтому связь и размах яркости верны; шкала серого указана до поправок.'
                    : 'Усиление фильтрует картинку по месту и не моделируется: сравнение с исходными серыми уровнями приблизительное.') : ''))
              : h('p', {class: 'muted small'}, 'Тональный профиль не построен: нет картинки в файле или слишком мало видимых пикселей.'),
            t && t.bins && t.bins.length >= 4 ? (() => {
              const hasPower = t.bins.some((b) => b.power_pct != null);
              const pick = t.bins.filter((_, k) => k % Math.max(1, Math.ceil(t.bins.length / 8)) === 0);
              const cell = (text) => h('td', {}, text);
              return h('div', {class: 'stack'},
                h('p', {class: 'small muted'}, `Серый уровень картинки${hasPower ? ' → мощность (линейно между Min и Max из настроек слоя: самый светлый серый — Min, самый тёмный — Max)' : ''} → цвет на металле `
                  + `(L*a*b* относительно камеры; связь с серым: L* ${num(t.rho, 2)}, a* ${num(t.rho_a, 2)}, b* ${num(t.rho_b, 2)}, цветность ${num(t.rho_chroma, 2)}).`),
                h('table', {class: 'small'}, h('thead', {}, h('tr', {}, ...['Серый', hasPower ? 'Мощность, %' : null, 'L*', 'a*', 'b*', 'C*'].filter(Boolean).map((x) => h('th', {}, x)))),
                  h('tbody', {}, ...pick.map((b) => h('tr', {}, cell(num(b.gray, 2)), ...(hasPower ? [cell(num(b.power_pct, 1))] : []),
                    cell(num(b.L, 1)), cell(num(b.a, 1)), cell(num(b.b, 1)), cell(num(b.C, 1)))))));
            })() : null);
        })));
  }

  // -- what the acceptance records ------------------------------------------------------------------------------------------
  const COLOUR_BASIS = {reference_chart_corrected: 'по калибровочной карте на фотографии',
    raw_camera_relative: 'относительно RAW камеры; в стандартные прогнозы не входит'};

  /** HOOK(ux-engraving-lifecycle-p0). The ONE place where an accepted pair hands over to what comes next. Today it says what was
      written and opens the analysis of the pair. The feature that returns to the originating work with a summary of prediction
      changes adds one call here, before the final ``go``: ``outcome`` is the answer of ``POST /pairs/{id}/accept`` (``work_review``
      is the conclusion written into the vector or photo-engraving work). Nothing else in this file needs to change for it. */
  async function afterAccepted(pair, outcome) {
    // ux-engraving-lifecycle-p0 REQ-002: a result that belongs to a vector work takes the operator back to that work with the summary
    if (typeof Lifecycle !== 'undefined' && Lifecycle.returnToWork(outcome.work_review)) return;
    toast(outcome.work_review ? `Наблюдения приняты. Вывод записан в работу «${outcome.work_review.work}»` : 'Наблюдения приняты', 'ok');
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
      'открыть эксперимент');
    const fact = (label, ...body) => h('li', {}, h('strong', {}, label + ': '), ...body);
    const accepted = pair.status === 'Accepted';
    return h('div', {class: 'card stack'}, h('h3', {}, accepted ? 'Что записано при принятии' : 'Что будет записано при принятии'),
      h('ul', {class: 'rv-facts'},
        fact('Версия гравировки', `${pair.engraving_title ? I18N.name(pair.engraving_title) : 'Гравировка'} · код ${String(pair.engraving_id || '').slice(0, 8)} · `, experiment),
        fact('Исходные файлы', `LightBurn «${pair.lightburn_name}», фотография «${pair.photo_name}»`),
        confirmed ? fact('Подтверждение файла', `«${confirmed.text}»${confirmed.at ? ' · ' + confirmed.at.slice(0, 16).replace('T', ' ') : ''}`) : null,
        fact('Совмещение', check.alignment && check.alignment.valid ? methodLabel(check.alignment) : 'не выполнено'),
        fact('Правила измерения', `цвет ${COLOUR_BASIS[mode] || 'без определённой основы'}; измерено слоёв: ${measured.length} из ${layers.length}. `
          + 'Чистка, метки и подписи записываются как служебные и в модель знаний не входят.'),
        fact('Настройки, введённые оператором', supplied ? `${supplied}, с пометкой «введено оператором»` : 'нет')));
  }

  /** An accepted pair: immutable. The stage bar shows everything done; the manual tools are in the correction, which is a new pair. */
  function acceptedView(pair) {
    return h('div', {class: 'stack'}, IngestStages.bar(pair.review.stages),
      h('div', {class: 'alert ok'}, 'Принятые измерения неизменяемы и участвуют в знаниях лазера.'),
      provenanceCard(pair),
      h('p', {class: 'muted small'}, 'Ручные инструменты (углы, привязка по детали, сдвиг схемы, матрица, слои, задачи) работают в исправлении: оно создаёт новую пару, '
        + 'а принятая остаётся неизменной, пока исправление не принято.'),
      h('div', {class: 'row'}, link('/analysis/' + pair.id, 'Открыть анализ'), link('/ingest?rephoto=' + pair.id, 'Повторная фотография этого изделия'),
        btn('Поправить совмещение этого фото', async (ev) => {
          const control = ev.currentTarget; control.disabled = true; control.textContent = 'Создаём исправление…';
          try { const revision = await post(`/pairs/${pair.id}/alignment-revisions`); go('/ingest?pair=' + revision.id); }
          catch (error) { control.disabled = false; control.textContent = 'Поправить совмещение этого фото'; fail(error); }
        }),
        btn('Удалить пару', () => confirmBox('Удалить принятую пару',
          'Пара исчезнет из карты цветов и перестанет участвовать в рекомендациях. Загруженные копии файлов будут удалены; неизменяемые измерения останутся в аудите.', 'Удалить',
          async () => { await del('/pairs/' + pair.id); toast('Запись удалена', 'ok'); go('/experiments'); }), 'danger')));
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
      const tick = () => { status.className = 'muted small'; status.textContent = `Совмещаем фото и измеряем слои… ${Math.floor((Date.now() - start) / 1000)} с`; };
      tick(); const timer = setInterval(tick, 1000);
      try {
        const checked = await post(`/pairs/${pair.id}/check`, body || {});
        clearInterval(timer);
        await reload();
        const problem = checked.check?.problems?.[0];
        toast(checked.status === 'Ready to accept' ? 'Совмещение выполнено. Проверьте контуры на фото и примите наблюдения.'
          : problem ? `Проверка завершена: ${I18N.tr(problem)}` : 'Проверка завершена; требуется уточнение.',
        checked.status === 'Ready to accept' ? 'ok' : 'warn');
      } catch (e) {
        clearInterval(timer); status.className = 'alert bad'; status.textContent = `Проверка не завершилась: ${e.message}`;
        stages.setBusy(false);
        if (button) button.disabled = false;
        fail(e);
      }
    };
    const identity = h('div', {class: 'card'}, h('h3', {}, pair.engraving_title ? I18N.name(pair.engraving_title) : (pair.rephoto_of ? 'Повторная фотография той же гравировки' : 'Гравировка')),
      h('p', {}, `LightBurn: ${pair.lightburn_name} · Фото: ${pair.photo_name}`),
      pair.plan_mode === 'Vector job' ? h('p', {class: 'small'}, 'Работа: ', link('/vector?plan=' + pair.plan_id, `«${pair.plan_name}»`), '; после принятия вывод по гравировке запишется в неё.') : null,
      pair.plan_mode === 'Photo engraving work' ? h('p', {class: 'small'}, 'Работа фотогравировки: ', link('/photo-engraving?work=' + pair.plan_id, `«${pair.plan_name}»`),
        '; после принятия каждый её серый сравнится с прогнозом на вкладке «Подтверждение».') : null,
      pair.rephoto_of ? h('p', {class: 'muted small'}, `Исходная пара №${pair.rephoto_of} · LightBurn, лазер, линза и титан унаследованы.`,
        pair.plan_id ? ' ' : null, pair.plan_id ? link('/plans/' + pair.plan_id, pair.plan_mode === 'Restored from file' ? 'План, восстановленный из файла' : 'Экспериментальная плата') : null) : null,
      pair.correction_of ? h('p', {class: 'alert warn'}, `Исправление совмещения снимка №${pair.correction_of}. До принятия этой коррекции прежний результат активен; после принятия он уйдёт из выводов, а история останется в журнале.`) : null,
      h('div', {class: 'row'},
        check ? btn('Повторить проверку', (ev) => { const self = ev.currentTarget; run({}, self); }) : null,
        check ? btn('Найти заново по RAW и LightBurn', (ev) => { const self = ev.currentTarget; run({reset_alignment: true}, self); }) : null,
        btn('Удалить пару', () => confirmBox('Удалить пару', 'Действие необратимо.', 'Удалить', async () => { await del('/pairs/' + pair.id); toast('Запись удалена', 'ok'); go('/experiments'); }), 'danger')));

    // -- the panels of the four stages, built once; the stage bar only shows and hides them, so nothing typed into one is lost ------------
    const panels = {files: [], alignment: [], review: [], accept: []};
    const aligned = Boolean(check && check.alignment.image_to_mm);
    const view = aligned ? viewer(pair, reload, run) : null;
    // Older checks could mistake a LightBurn-omitted setting for a changed value. The original audit is preserved, but only measured
    // differences are shown as mismatches.
    const realDifferences = check ? (check.discrepancies || []).filter((d) => d.from_file != null) : [];
    const supplied = check ? await suppliedSettingsCard(pair, reload) : null;
    const suppliedBox = supplied ? h('details', {class: 'rv-more', open: (review.advisories || []).some((a) => a.code === 'settings_missing')},
      h('summary', {}, 'Ввести недостающие настройки слоёв'), supplied) : null;

    if (!check) {
      panels.files.push(h('p', {class: 'muted'}, 'Нажмите «Проверить пару»: будут прочитаны параметры слоёв, выровнена фотография и измерены области гравировки.'));
      panels.alignment.push(h('p', {class: 'muted'}, 'Совмещение появится после первой проверки пары. Углы работы и привязку по детали можно задать и до неё.'));
      panels.review.push(h('p', {class: 'muted'}, 'Контуры на фотографии и итог появятся после совмещения.'));
      panels.accept.push(h('p', {class: 'muted'}, 'Принять можно только проверенную пару.'));
    } else {
      if (realDifferences.length) {
        const conf = pair.file_confirmation;
        panels.files.push(h('div', {class: 'card stack'}, h('h3', {}, 'Сравнение с определением платы'),
          conf ? h('div', {class: 'alert ok'}, 'Использованный файл подтверждён. Ниже сохранены реальные отличия параметров.')
            : h('div', {class: 'alert warn'}, 'Параметры файла отличаются от определения платы. Исправьте пару или подтвердите использованный файл.'),
          IngestDialogs.discrepancyTable(realDifferences),
          conf ? h('p', {class: 'alert ok'}, `Подтверждено: «${conf.text}» · ${conf.at.slice(0, 16).replace('T', ' ')}`)
            : h('div', {class: 'row'}, btn('Исправить пару', () => IngestDialogs.fixFile(pair, reload)),
              btn('Подтвердить использованный файл', () => IngestDialogs.confirmFile(pair, {...check, discrepancies: realDifferences}, reload)))));
      }
      if (suppliedBox) panels.files.push(suppliedBox);
      if (!realDifferences.length && !suppliedBox) panels.files.push(h('p', {class: 'muted'}, 'К файлам замечаний нет: оба читаются, расхождений с платой и недостающих настроек не найдено.'));
      panels.alignment.push(h('div', {class: 'card stack'}, h('h3', {}, 'Совмещение фотографии с файлом'),
        h('p', {}, 'Выравнивание: ', check.alignment.valid ? pill(methodLabel(check.alignment), 'ok') : pill('не выполнено', 'warn'),
          check.alignment.valid && check.alignment.residual_px != null ? ` · остаток по краям опорных меток ${num(check.alignment.residual_px, 1)} пикс.` : ''),
        h('p', {class: 'muted small'}, check.alignment.valid
          ? 'Совмещение можно поправить вручную, даже если программа считает его верным: «Углы работы», «Привязка по детали», «Сдвиг и поворот схемы».'
          : 'Программа не смогла совместить фотографию с файлом. Поставьте четыре угла работы или привязку по одной детали.'),
        h('details', {class: 'rv-more'}, h('summary', {}, 'Подробности совмещения и калибровочной карты'), resultsCard(check))));
      if (view) {
        panels.review.push(view.view);
        const composed = Composition.card(check, pair.id), images = imageLayersCard(check);
        panels.review.push(h('details', {class: 'card rv-more'}, h('summary', {}, 'Измеренные слои и метрики'),
          h('div', {class: 'stack'}, h('p', {class: 'small'}, 'Слои файла, их результат и задачи гравировки — в инструментах выше («Слои файла», «Задачи гравировки»).'),
            h('div', {class: 'row'}, btn('Открыть слои файла', () => stages.open('layers'))), composed, images)));
      } else panels.review.push(h('div', {class: 'alert warn'}, 'Фотография ещё не совмещена с файлом: контуры появятся после совмещения.'));
      panels.review.push(IngestStages.invalidation());
      panels.accept.push(provenanceCard(pair));
      panels.accept.push(h('div', {class: 'card stack'}, h('h3', {}, 'Отклонить результат'),
        h('p', {class: 'small'}, 'Если фотография или проверка не годятся, результат можно отклонить: он не попадёт в выводы и знания лазера. Запись пары, её проверка, '
          + 'подтверждения и версия гравировки остаются в журнале; загруженные копии файлов удаляются.'),
        h('div', {class: 'row'}, btn('Отклонить результат', () => confirmBox('Отклонить результат',
          'Результат этой пары не попадёт в выводы и знания лазера. Пара будет помечена удалённой, загруженные копии файлов удалены. В журнале останутся запись пары с проверкой и подтверждениями, версия гравировки и имена файлов.',
          'Отклонить', async () => { await del('/pairs/' + pair.id); toast('Результат отклонён', 'ok'); go('/experiments'); }), 'danger'))));
      panels.accept.push(IngestStages.invalidation());
    }

    // -- the manual tools: always present, with or without a warning (DEC-001) -------------------------------------------------------------
    const layersCard = h('div', {class: 'card stack'}, h('h3', {}, 'Слои файла'),
      check ? IngestDialogs.layersTable(check.layers) : h('p', {class: 'muted small'}, 'Слои появятся после первой проверки пары.'));
    const regions = {
      corners: {build: () => cornersCard(pair, run, aligned).card},
      anchor: {build: () => anchorRegion(pair, run)},
      shift: {el: view ? view.shiftCard : explained('Сдвиг, поворот и масштаб всей схемы',
        'Схему можно двигать, когда она уже наложена на фотографию. Сначала проверьте пару или поставьте четыре угла работы.', btn('Открыть углы работы', () => stages.open('corners')))},
      matrix: {el: pair.matrix ? matrixCard(pair, reload) : explained('Матрица параметров',
        'Эта пара — не фотография матрицы параметров: настройки слоёв заданы файлом LightBurn. Их видно в «Слои файла», а недостающие вводятся в «Ввести недостающие настройки слоёв».',
        btn('Открыть слои файла', () => stages.open('layers')))},
      layers: {el: layersCard},
      tasks: {el: IngestTasks.card(pair, reload)},          // REQ-020: задача каждого слоя и метрики с основанием
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
