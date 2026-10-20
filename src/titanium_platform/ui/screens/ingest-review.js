/* Проверка пары: эталон, выравнивание, расхождения с платой, маски слоёв, принятие (REQ-001, REQ-009, REQ-015, DEC-017).
   Принять можно только после проверки без проблем, подтверждения файла при расхождении и проверки масок. */
'use strict';
const IngestReview = (() => {
  const {h, btn, link, pill, post, del, toast, fail, go, confirmBox, num, swatch, labText} = App;

  function masks(pair, reload, run) {
    const ready = pair.status === 'Ready to accept';
    const flag = h('input', {type: 'checkbox', checked: pair.masks_reviewed, disabled: !ready || pair.masks_reviewed});
    const accept = btn('Принять наблюдения', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const out = await post(`/pairs/${pair.id}/accept`);
        toast(out.work_review ? `Наблюдения приняты. Вывод записан в работу «${out.work_review.work}»` : 'Наблюдения приняты', 'ok');
        go('/analysis/' + pair.id);
      }
      catch (e) { fail(e); self.disabled = false; }
    }, 'primary', !ready || !pair.masks_reviewed);
    flag.addEventListener('change', async () => {
      if (!flag.checked) return;
      try { await post(`/pairs/${pair.id}/review-masks`); reload(); } catch (e) { flag.checked = false; fail(e); }
    });
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
    }, 'primary', true);
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
      rotation = Math.max(0, Math.min(360, parsed));
      rotationRange.value = rotation;
      rotationNumber.value = rotation.toFixed(1);
      snapAdjustment();
    };
    rotationRange.addEventListener('input', () => setRotation(rotationRange.value));
    rotationNumber.addEventListener('change', () => setRotation(rotationNumber.value));
    const setScale = (value) => {
      const parsed = Number(value);
      if (!Number.isFinite(parsed)) return;
      schemeScale = Math.max(10, Math.min(800, parsed));
      scaleRange.value = schemeScale;
      scaleNumber.value = schemeScale.toFixed(1);
      snapAdjustment();
    };
    scaleRange.addEventListener('input', () => setScale(scaleRange.value));
    scaleNumber.addEventListener('change', () => setScale(scaleNumber.value));
    mirrorX.addEventListener('change', () => { mirrorHorizontal = mirrorX.checked; snapAdjustment(); });
    mirrorY.addEventListener('change', () => { mirrorVertical = mirrorY.checked; snapAdjustment(); });
    const zoomRange = h('input', {type: 'range', min: 25, max: 800, step: 25, value: 100,
      'aria-label': 'Масштаб просмотра фотографии, проценты'});
    const zoomValue = h('span', {class: 'muted small', 'aria-live': 'polite'}, '100%');
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
      viewRotation = Math.max(0, Math.min(360, parsed));
      viewRange.value = viewRotation;
      viewNumber.value = viewRotation.toFixed(1);
      layoutView();
    };
    viewRange.addEventListener('input', () => setViewRotation(viewRange.value));
    viewNumber.addEventListener('change', () => setViewRotation(viewNumber.value));
    const setZoom = (value) => {
      zoom = Math.max(25, Math.min(800, Number(value) || 100));
      zoomRange.value = zoom;
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
      rotationRange.value = 0; rotationNumber.value = '0.0';
      scaleRange.value = 100; scaleNumber.value = '100.0'; mirrorX.checked = mirrorY.checked = false;
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
    return h('div', {class: 'card stack'}, h('h3', {}, 'Что измерено на фотографии'),
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
      h('div', {class: 'row overlay-controls'}, h('span', {}, 'Поворот схемы на фото'), rotationRange,
        rotationNumber, h('span', {}, '°'),
        btn('−90°', () => setRotation((rotation + 270) % 360)),
        btn('+90°', () => setRotation((rotation + 90) % 360))),
      h('div', {class: 'row overlay-controls'}, h('span', {}, 'Масштаб схемы на фото'), scaleRange,
        scaleNumber, h('span', {}, '%'),
        h('label', {class: 'row'}, mirrorX, h('span', {}, 'Зеркально ↔')),
        h('label', {class: 'row'}, mirrorY, h('span', {}, 'Зеркально ↕'))),
      h('div', {class: 'row overlay-controls'}, h('span', {}, 'Повернуть фото для просмотра'), viewRange,
        viewNumber, h('span', {}, '°'),
        btn('−90°', () => setViewRotation((viewRotation + 270) % 360)),
        btn('+90°', () => setViewRotation((viewRotation + 90) % 360))),
      h('div', {class: 'row overlay-controls'}, h('span', {}, 'Масштаб просмотра'), zoomRange, zoomValue,
        btn('−', () => setZoom(zoom - 25)), btn('+', () => setZoom(zoom + 25)),
        btn('Вписать', () => setZoom(100))),
      h('div', {class: 'row'}, toggleEdit, h('label', {class: 'row'}, snap,
        h('span', {}, `Привязка к распознанным деталям (${baseSnapCandidates.length + vectorSnapMatches.length})`)),
        resetShift, saveShift),
      editorStatus,
      snapStatus,
      h('label', {class: 'row'}, flag, h('span', {}, 'Маски слоёв проверены: контуры лежат на нужных деталях')),
      ready ? null : h('p', {class: 'muted small'}, 'Принять можно после проверки без проблем и подтверждения файла при расхождении.'),
      h('div', {class: 'row'}, accept));
  }

  function cornersCard(pair, run, existing = false) {
    let corners = null;
    const apply = btn('Применить выравнивание', () => run({corners_fraction: corners}, apply), 'primary', true);
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

  function elementAnchorCard(pair, suggestions, run) {
    let selected = suggestions[0], corners = selected.corners_fraction;
    const holder = h('div', {});
    const apply = btn('Привязать по выбранной детали', () => run({anchor: {
      layer_index: selected.layer_index, region_index: selected.region_index, corners_fraction: corners,
    }}, apply), 'primary');
    const renderPicker = () => {
      corners = selected.corners_fraction;
      const picker = Corners.create(`/api/pairs/${pair.id}/photo.png`, corners,
        (value) => { corners = value; apply.disabled = !value; },
        'Передвиньте четыре точки на углы этой конкретной детали, в порядке верхний левый → верхний правый → нижний правый → нижний левый. Размер детали и расстояния до остальных элементов известны из LightBurn.');
      holder.replaceChildren(picker.el);
      apply.disabled = false;
    };
    const choose = h('select', {'aria-label': 'Кандидат на деталь', onChange: (ev) => {
      selected = suggestions[Number(ev.target.value)]; renderPicker();
    }}, suggestions.map((item, i) => h('option', {value: i},
      `${item.element} · оценка формы ${num(item.shape_score, 3)}`)));
    renderPicker();
    return h('div', {class: 'card stack'}, h('h3', {}, 'Привязать по одной детали'),
      h('p', {}, 'Автоматическая проверка всей геометрии не прошла. Выберите наиболее узнаваемую деталь и уточните её положение на фотографии; остальные контуры будут рассчитаны из файла.'),
      choose, holder, h('div', {class: 'row'}, apply));
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
    const send = async (button, layer, setting, value) => {
      button.disabled = true;
      const status = h('span', {class: 'muted small', role: 'status'}, 'Сохраняем и перепроверяем пару…');
      button.after(status);
      try {
        await post(`/pairs/${pair.id}/supplied-settings`, {layer_index: layer.index, setting, value});
        toast(value == null ? 'Введённое значение убрано, пара перепроверена' : 'Значение сохранено как введённое оператором, пара перепроверена', 'ok');
        await reload();
      } catch (e) { status.remove(); button.disabled = false; fail(e); }
    };
    const entry = (layer, setting) => {
      const [label, unit] = SUPPLIED[setting];
      const given = (layer.supplied_settings || {})[setting];
      if (given) {
        return h('div', {class: 'row small'}, h('strong', {}, `${label}: ${given.value}${unit ? ' ' + unit : ''}`),
          pill(`введено оператором${given.at ? ' · ' + stamp(given.at) : ''}`, 'warn'),
          btn('Убрать', (ev) => { const self = ev.currentTarget; send(self, layer, setting, null); }, 'btn-small'));
      }
      const input = h('input', {type: 'number', step: 'any', min: 0, style: 'width:8em', 'aria-label': `${label}, слой ${layer.name}`,
        list: setting === 'pulse_width' && steps.length ? listId : null});
      const byDefault = (layer.defaulted_settings || {})[setting];
      return h('div', {class: 'row small'}, h('span', {}, byDefault ? `${label}: в файле не записан, по умолчанию лазера ${byDefault.value}${unit ? ' ' + unit : ''}; другое значение:` : `${label}${unit ? ', ' + unit : ''}: нет в файле`), input,
        btn('Сохранить', (ev) => {
          const self = ev.currentTarget;
          if (input.value.trim() === '') { fail(new Error('Введите значение')); return; }
          send(self, layer, setting, Number(input.value));
        }, 'btn-small primary'));
    };
    return h('div', {class: 'card stack'}, h('h3', {}, 'Настройки, которых нет в файле LightBurn'),
      h('p', {class: 'muted small'}, 'Без них слой не сопоставим и не попадает в модель. Приложение подставляет только то, что задано в параметрах лазера (сейчас — Q-Pulse по умолчанию): LightBurn не записывает значение, равное умолчанию. '
        + 'Если вы знаете, с какой настройкой гравировался слой, впишите её. Она сохранится с пометкой «введено оператором» и временем, '
        + 'пара будет проверена заново, а принятое наблюдение запомнит, какие настройки взяты из файла, а какие введены вами. '
        + 'Значения, прочитанные из файла, не меняются.'
        + (steps.length ? ` Лазер принимает длительность импульса от ${Math.min(...steps)} до ${Math.max(...steps)} нс; в таблице производителя: ${steps.join(', ')} нс.` : '')),
      steps.length ? h('datalist', {id: listId}, ...steps.map((v) => h('option', {value: v}))) : null,
      ...gaps.map((layer) => h('div', {class: 'stack'}, h('strong', {}, layer.name), ...layer.missing_settings.map((s) => entry(layer, s)))));
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
    const input = (value, attrs = {}) => h('input', {type: 'number', step: 'any', value: value == null ? '' : value, style: 'width:8em', ...attrs});
    const select = (current) => h('select', {}, h('option', {value: ''}, '— не знаю —'),
      ...MATRIX_PARAMS.map(([k, label]) => h('option', {value: k, selected: k === current}, label)));
    const axis = (key, count, word) => {
      const a = s[key];
      const el = {param: select(a.param), first: input(a.values ? a.values[0] : null), last: input(a.values ? a.values[a.values.length - 1] : null)};
      el.row = h('div', {class: 'row small'}, h('strong', {}, `${word} (${count}):`), el.param,
        h('span', {}, count > 1 ? 'первое' : 'значение'), el.first, ...(count > 1 ? [h('span', {}, 'последнее'), el.last] : []));
      return el;
    };
    const x = axis('x', m.cols, 'По столбцам'), y = axis('y', m.rows, 'По строкам');
    const fixed = {};
    const fixedRow = h('div', {class: 'row small'});
    const drawFixed = () => {
      fixedRow.replaceChildren(h('strong', {}, 'Постоянные:'));
      for (const [k, label] of MATRIX_PARAMS) {
        if (k === (x.param.value || s.x.param) || k === (y.param.value || s.y.param)) continue;
        fixed[k] = fixed[k] || input(s.fixed ? s.fixed[k] : null);
        fixedRow.append(h('label', {class: 'row'}, h('span', {}, label), fixed[k]));
      }
    };
    drawFixed();
    x.param.addEventListener('change', drawFixed); y.param.addEventListener('change', drawFixed);
    const extent = {cols: input(m.cols, {step: 1, min: 1, style: 'width:5em'}), rows: input(m.rows, {step: 1, min: 1, style: 'width:5em'}),
      col_shift: input(0, {step: 1, style: 'width:5em'}), row_shift: input(0, {step: 1, style: 'width:5em'}), pitch: input(s.pitch_mm)};
    const edit = () => {
      const axisEdit = (el, count) => ({param: el.param.value || null, first: el.first.value === '' ? null : +el.first.value,
        last: count > 1 ? (el.last.value === '' ? null : +el.last.value) : (el.first.value === '' ? null : +el.first.value)});
      const cols = +extent.cols.value, rows = +extent.rows.value;
      return {x: axisEdit(x, cols), y: axisEdit(y, rows),
        fixed: Object.fromEntries(Object.entries(fixed).filter(([k]) => k !== x.param.value && k !== y.param.value).map(([k, el]) => [k, el.value === '' ? null : +el.value])),
        extent: {cols, rows, col_shift: +extent.col_shift.value, row_shift: +extent.row_shift.value}, pitch_mm: extent.pitch.value === '' ? null : +extent.pitch.value};
    };
    const send = async (confirm, button) => {
      button.disabled = true;
      const status = h('span', {class: 'muted small', role: 'status'}, 'Пересобираем файл и перепроверяем фото…');
      button.after(status);
      try { await post(`/pairs/${pair.id}/matrix`, {edit: edit(), confirm}); toast(confirm ? 'Параметры подтверждены и применены' : 'Исправления применены, фото перепроверено', 'ok'); await reload(); }
      catch (e) { status.remove(); button.disabled = false; fail(e); }
    };
    const apply = btn('Применить исправления', (ev) => { const self = ev.currentTarget; send(false, self); });
    const confirmBtn = btn('Параметры верны', (ev) => { const self = ev.currentTarget; send(true, self); }, 'primary');
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
        h('div', {class: 'row small'}, h('span', {}, 'Столбцов'), extent.cols, h('span', {}, 'строк'), extent.rows,
          h('span', {}, 'сдвиг первой ячейки: вправо'), extent.col_shift, h('span', {}, 'вниз'), extent.row_shift, h('span', {}, 'шаг ячеек, мм'), extent.pitch),
        h('p', {class: 'muted small'}, 'Если сетка найдена не целиком (бледные ячейки у края) или захватила лишнее, поправьте число столбцов и строк и сдвиг первой ячейки. Шаг влияет только на вид созданного файла LightBurn.')),
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
            try { const created = await post(`/pairs/${pair.id}/matrix/others/${k}`); await post(`/pairs/${created.id}/check`, {}); go('/ingest?pair=' + created.id); }
            catch (e) { self.disabled = false; fail(e); }
          })))) : null);
  }

  async function render(pair, reload) {
    if (pair.status === 'Accepted') {
      return h('div', {class: 'stack'}, h('div', {class: 'alert ok'}, 'Принятые измерения неизменяемы и участвуют в знаниях лазера.'),
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
    const check = pair.check;
    const run = async (body, button) => {
      if (button) button.disabled = true;
      const status = h('span', {class: 'muted small', role: 'status', 'aria-live': 'polite'});
      if (button) button.after(status);
      const start = Date.now();
      const tick = () => { status.textContent = `Совмещаем фото и измеряем слои… ${Math.floor((Date.now() - start) / 1000)} с`; };
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
        clearInterval(timer); status.textContent = `Проверка не завершилась: ${e.message}`;
        status.className = 'alert bad';
        if (button) button.disabled = false;
        fail(e);
      }
    };
    const out = h('div', {class: 'stack'});
    out.append(h('div', {class: 'card'}, h('h3', {}, pair.engraving_title ? I18N.name(pair.engraving_title) : (pair.rephoto_of ? 'Повторная фотография той же гравировки' : 'Гравировка')),
      h('p', {}, `LightBurn: ${pair.lightburn_name} · Фото: ${pair.photo_name}`),
      pair.rephoto_of ? h('p', {class: 'muted small'}, `Исходная пара №${pair.rephoto_of} · LightBurn, лазер, линза и титан унаследованы.`,
        pair.plan_id ? ' ' : null, pair.plan_id ? link('/plans/' + pair.plan_id, pair.plan_mode === 'Restored from file' ? 'План, восстановленный из файла' : 'Экспериментальная плата') : null) : null,
      pair.correction_of ? h('p', {class: 'alert warn'}, `Исправление совмещения снимка №${pair.correction_of}. До принятия этой коррекции прежний результат активен; после принятия он уйдёт из выводов, а история останется в журнале.`) : null,
      h('div', {class: 'row'}, btn(check ? 'Повторить проверку' : 'Проверить пару', (ev) => {
        const self = ev.currentTarget;
        run({}, self);
      }, 'primary'),
        check ? btn('Найти заново по RAW и LightBurn', (ev) => {
          const self = ev.currentTarget;
          run({reset_alignment: true}, self);
        }) : null,
        btn('Удалить пару', () => confirmBox('Удалить пару', 'Действие необратимо.', 'Удалить', async () => { await del('/pairs/' + pair.id); toast('Запись удалена', 'ok'); go('/experiments'); }), 'danger'))));
    if (pair.matrix) out.append(matrixCard(pair, reload));
    if (!check) {
      out.append(h('p', {class: 'muted'}, 'Нажмите «Проверить пару»: будут прочитаны параметры слоёв, выровнена фотография и измерены области гравировки.'));
      return out;
    }
    const relative = check.color_measurement && check.color_measurement.mode === 'raw_camera_relative';
    out.append(h('div', {class: 'card stack'}, h('h3', {}, 'Результаты проверки'),
      h('p', {}, 'Калибровочная карта цвета: ', relative ? pill(check.chart.detected ? 'не использована; Lab относительно RAW-камеры' : 'не найдена; Lab относительно RAW-камеры', 'warn')
        : !check.chart.detected ? pill('не обнаружена', 'bad')
        : check.chart.usable === false ? pill('кандидат найден, карта не подтверждена', 'bad') : pill('обнаружена и проверена', 'ok'),
        !relative && check.chart.residual != null ? ` · остаточная ошибка коррекции ΔE ${num(check.chart.residual, 1)}${check.chart.max_residual != null ? ` (порог ${num(check.chart.max_residual, 1)})` : ''}` : '',
        !relative && check.chart.grey_ramp ? h('span', {class: 'muted small'},
          ` · серая шкала после коррекции L* ${check.chart.grey_ramp.corrected.map((v) => num(v, 0)).join(' · ')} (эталон ${check.chart.grey_ramp.reference.map((v) => num(v, 0)).join(' · ')})`) : ''),
      h('p', {}, 'Выравнивание: ', check.alignment.valid ? pill(check.alignment.method === 'markers'
        ? `по маркерам${check.alignment.marker_count != null ? ` (${check.alignment.marker_count})` : ''}`
        : check.alignment.method === 'marker templates' ? 'по узорам 4 меток'
        : check.alignment.method === 'two marker + QR' ? (check.alignment.qr_used_as_anchor === false
          ? 'по двум меткам; QR подтвердил плату' : 'по двум меткам и QR-коду платы')
        : check.alignment.method === 'picture' ? `по вложенной картинке (корреляция ${num((check.alignment.picture || {}).zncc, 2)})`
        : check.alignment.method === 'element anchors' ? `по элементам-якорям (${(check.alignment.element_matches || []).length})`
        : check.alignment.method === 'geometry' ? `по деталям рисунка (${(check.alignment.element_matches || []).length})`
        : check.alignment.method === 'single distinctive detail' ? 'по одной характерной детали'
        : check.alignment.method === 'element anchor' ? 'по детали, поставленной вручную'
        : check.alignment.method === 'manual shift' ? 'поправлено перемещением всей схемы'
        : check.alignment.method === 'manual rotation' ? 'поправлено поворотом всей схемы'
        : check.alignment.method === 'manual transform' ? 'поправлено масштабом или зеркалом всей схемы'
        : 'вручную по углам', 'ok')
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
            : `${item.element}: файл (${item.center_mm.join(', ')} мм) → фото (${item.center_px.join(', ')} пикс.)`)))] : []),
      ...((check.warnings || []).map((m) => h('div', {class: 'alert warn', role: 'status'}, I18N.tr(m)))),
      ...check.problems.map((m) => h('div', {class: 'alert bad', role: 'alert'}, I18N.tr(m))),
      ...((check.lens && check.lens.warnings) || []).map((m) => h('div', {class: 'alert warn', role: 'status'}, I18N.tr(m)))));
    const supplied = await suppliedSettingsCard(pair, reload);
    if (supplied) out.append(supplied);
    const imageLayers = (check.layers || []).filter((l) => l.image);
    if (imageLayers.length) {
      const DITHER = {stucki: 'Стаки', jarvis: 'Джарвис', threshold: 'порог', grayscale: 'градации серого', sketch: 'эскиз', '3dslice': '3D-слайс',
        atkinson: 'Аткинсон', dither: 'растр', halftone: 'полутона', newsprint: 'газетный растр', passthrough: 'без растрирования'};
      out.append(h('div', {class: 'card stack'}, h('h3', {}, 'Слои-изображения'),
        ...imageLayers.map((l) => {
          const i = l.image, t = l.tonal;
          return h('div', {class: 'stack'},
            h('p', {}, `${l.name}: ${i.kind === 'depth' ? 'глубина (3D-слайс)' : 'фотогравировка'}, режим «${DITHER[i.dither] || i.dither || 'не указан'}»`
              + (i.dpi ? `, ${num(i.dpi, 0)} DPI` : '') + (i.dot_width_mm != null ? `, ширина точки ${num(i.dot_width_mm, 3)} мм` : '')
              + (i.dot_correction ? ', поправка точки включена' : '') + (i.cleanup_pass ? ', есть проход очистки' : '')
              + (i.passes ? `, проходов ${num(i.passes, 0)}` : '') + '.'),
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
    if (check.alignment.image_to_mm) {
      out.append(masks(pair, reload, run));
      out.append(h('details', {class: 'card'}, h('summary', {}, 'Точная правка масштаба и перспективы по четырём углам'),
        cornersCard(pair, run, true).card));
    }
    const needsManualCorners = !check.alignment.image_to_mm && !check.alignment.valid && Array.isArray(check.image_size);
    const suggestions = (check.alignment.suggestions || []).filter((item) => {
      const points = item.corners_fraction || [];
      if (points.length !== 4 || !check.image_size) return false;
      const xs = points.map((p) => p[0] * check.image_size[0]);
      const ys = points.map((p) => p[1] * check.image_size[1]);
      return Math.min(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) >=
        .035 * Math.min(...check.image_size);
    });
    if (needsManualCorners) out.append(cornersCard(pair, run).card);
    // A marked plate already has a known outer frame. Placing that frame on a
    // tiny candidate vector would produce a huge, incorrect global transform.
    if (!check.alignment.valid && suggestions.length && !pair.plate_id) out.append(elementAnchorCard(pair, suggestions, run));
    // Older checks could mistake a LightBurn-omitted setting for a changed value.
    // The original audit is preserved, but only measured differences are shown as mismatches.
    const realDifferences = (check.discrepancies || []).filter((d) => d.from_file != null);
    if (realDifferences.length) {
      const conf = pair.file_confirmation;
      out.append(h('div', {class: 'card stack'}, h('h3', {}, 'Сравнение с определением платы'),
        conf ? h('div', {class: 'alert ok'}, 'Использованный файл подтверждён. Ниже сохранены реальные отличия параметров.')
          : h('div', {class: 'alert warn'}, 'Параметры файла отличаются от определения платы. Исправьте пару или подтвердите использованный файл.'),
        IngestDialogs.discrepancyTable(realDifferences),
        conf ? h('p', {class: 'alert ok'}, `Подтверждено: «${conf.text}» · ${conf.at.slice(0, 16).replace('T', ' ')}`)
          : h('div', {class: 'row'}, btn('Исправить пару', () => IngestDialogs.fixFile(pair, reload)),
            btn('Подтвердить использованный файл', () => IngestDialogs.confirmFile(pair, {...check, discrepancies: realDifferences}, reload)))));
    }
    out.append(h('div', {class: 'card stack'}, h('h3', {}, 'Слои файла'), IngestDialogs.layersTable(check.layers)));
    out.append(IngestTasks.card(pair, reload));          // REQ-020: задача каждого слоя и метрики с основанием
    return out;
  }
  return {render, matrixGrid, hiddenMargins};
})();
