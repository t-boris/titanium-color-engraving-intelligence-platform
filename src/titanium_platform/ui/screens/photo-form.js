/* Форма непрерывной фотогравировки: режим, изображение, число полос, предпросмотр и создание плана (REQ-004, REQ-012, DEC-032).
   Предпросмотр и создание плана используют один расчёт на сервере; «Создать план» доступно только после предпросмотра
   с теми же значениями. Любое изменение значений предпросмотр сбрасывает; смена числа полос сразу перерисовывает картину полос.
   Число полос ограничено палитрой LightBurn: 30 выходных слоёв, один остаётся маркерам (DEC-044, DEC-066).
   ?plan=<id> открывает форму, заполненную по существующему плану: исправление создаёт новый план, старый не меняется. */
'use strict';
const PhotoForm = (() => {
  const {h, fill, btn, field, link, get, form, toast, go, modal, swatch, labText} = App;
  // the reason of a doubt joins one message per broken threshold with '; ' (knowledge.refresh): each is translated
  const doubt = (reason) => reason.split('; ').map((part) => I18N.tr(part)).join('; ');

  /** Предупреждение тонального режима: каждая запись под вопросом с причиной и ссылкой на её наблюдения (DEC-018). */
  function questionedWarning(w, palette = []) {
    const entries = w.entries || w.knowledge_ids.map((id) => ({knowledge_id: id, lab: (palette.find((e) => e.id === id) || {}).lab}));
    return h('div', {class: 'alert warn stack'}, h('p', {}, h('strong', {}, 'Используются производственные параметры под вопросом. '),
      'В тональном режиме отдельное подтверждение не требуется; посмотрите наблюдения каждой записи.'),
      entries.map((e) => h('div', {class: 'row'}, e.lab ? [swatch(e.lab), labText(e.lab)] : null, h('span', {class: 'small'}, e.reason ? doubt(e.reason) : 'Параметры под вопросом'),
        link('/knowledge/' + e.knowledge_id, `Наблюдения записи K${e.knowledge_id}`))));
  }

  /** Окно включения параметров под вопросом в этот план цветового пути: разрешение только для создаваемого плана (REQ-004). */
  function questionedDialog(all, state, done) {
    const picked = new Set(state.allowed);
    const rows = all.map((e) => h('div', {class: 'alert warn'},
      h('label', {class: 'row'}, h('input', {type: 'checkbox', checked: picked.has(e.id), onChange: (ev) => { if (ev.target.checked) picked.add(e.id); else picked.delete(e.id); }}), swatch(e.lab), labText(e.lab)),
      h('p', {class: 'small'}, (e.doubt && doubt(e.doubt.reason)) || 'Параметры под вопросом'), link('/knowledge/' + e.id, 'Наблюдения')));
    modal('Включить параметры под вопросом в этот план', h('div', {class: 'stack'},
      h('p', {}, 'Разрешение действует только для создаваемого плана и не переходит в другие. Стадия знания и флаг не изменятся.'),
      ...(rows.length ? rows : [h('p', {}, 'Нет производственных параметров под вопросом')])), [
      {label: 'Отмена', run: (x) => x.close()},
      {label: 'Применить к этому плану', cls: 'primary', run: (x) => { state.allowed = [...picked]; state.path = state.path.filter((id) => !all.some((e) => e.id === id) || picked.has(id)); x.close(); done(); }}]);
  }

  async function render(ctx, lists, parts) {
    const {bandTable, pathPicker, MODES} = parts;
    const {max_bands: maxBands} = await get('/continuous/limits');
    const source = ctx.query.plan ? await get('/plans/' + ctx.query.plan).catch(() => null) : null;
    const revising = source && MODES.some(([id]) => id === source.continuous_mode) ? source : null;
    const state = {mode: revising ? revising.continuous_mode : ctx.query.mode === 'color_path' ? 'color_path' : 'tonal',
      path: revising ? [...revising.path_ids] : [], allowed: revising ? [...revising.allowed_questioned] : [], preview: null, image: null};
    const host = h('div', {class: 'stack'});
    const pick = App.laserLensPicker(lists, {device: revising ? revising.device_id : ctx.query.device, lens: revising ? App.lensParam(revising.lens_id) : ctx.query.lens,
      onChange: async () => { state.path = []; state.allowed = []; await loadPalette(); invalidate(); }});
    const img = h('input', {type: 'file', accept: 'image/*', 'aria-label': 'Фотография для гравировки'});
    const name = h('input', {placeholder: 'Название плана', value: revising ? `${revising.name} — исправление` : ''});
    const width = h('input', {type: 'number', step: 'any', value: revising && revising.size_mm ? revising.size_mm.width : 80});
    const bands = h('input', {type: 'number', step: '1', min: '1', max: String(maxBands), value: revising ? Math.min(revising.band_count, maxBands) : maxBands, 'aria-describedby': 'bands-help'});
    const markers = h('input', {type: 'checkbox', checked: revising ? revising.markers_enabled : false});
    // REQ-020: тоновое изображение для тонового режима, цветное — для цветового пути; задача записывается в план
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
      // тональный режим берёт и записи под вопросом (с предупреждением); цветовой путь — только явно включённые в этот план
      palette = state.mode === 'tonal' ? all : all.filter((e) => !e.questioned || state.allowed.includes(e.id));
    }
    function invalidate() { state.preview = null; previewSig = null; draw(); }

    async function doPreview() {
      show('');
      if (!picture()) return show('Добавьте фотографию для гравировки');
      try { state.preview = await form('/continuous/preview', body(false)); previewSig = signature(); draw(); } catch (e) { show(e.message); }
    }
    async function doCreate(ev) {
      if (!state.preview || previewSig !== signature()) return show('Сначала сделайте актуальный предпросмотр');
      const self = ev.currentTarget;
      self.disabled = true;
      try { const p = await form('/continuous', body(true)); toast(revising ? 'Исправленный план создан; прежний план не изменён' : 'План создан', 'ok'); go('/plans/' + p.id); } catch (e) { show(e.message); self.disabled = false; }
    }

    function sourcePicture() {
      if (sourceUrl) URL.revokeObjectURL(sourceUrl);
      sourceUrl = picture() ? URL.createObjectURL(picture()) : null;
      return sourceUrl ? h('figure', {}, h('img', {src: sourceUrl, style: 'width:100%', alt: 'Исходная фотография'}), h('figcaption', {class: 'muted small'}, 'Исходная фотография')) : null;
    }

    function draw() {
      const p = state.preview;
      const questioned = all.filter((e) => e.questioned);
      const modeBtns = MODES.map(([id, label]) => h('button', {type: 'button', class: 'btn' + (state.mode === id ? ' primary' : ''), 'aria-pressed': state.mode === id,
        onClick: async () => { if (state.mode === id) return; state.mode = id; state.path = []; state.allowed = []; state.preview = null; task.set(DEFAULT_TASK[id]); await loadPalette(); draw(); }}, label));
      fill(host,
        h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Непрерывная фотогравировка'), h('p', {class: 'sub'}, 'Одна передаточная функция, два режима. Параметры между измеренными наборами не интерполируются.')),
          h('span', {class: 'spacer'}), h('div', {class: 'row', role: 'group', 'aria-label': 'Подрежим фотогравировки'}, modeBtns), link('/colors', 'Карта цветов')),
        revising ? h('div', {class: 'alert ok'}, 'Исправление плана ', link('/plans/' + revising.id, `«${revising.name}»`),
          ': значения и изображение взяты из него. Будет создан новый план; прежний останется без изменений. Чтобы взять другое изображение, выберите его.') : null,
        h('div', {class: 'card stack'}, h('div', {class: 'grid g2'}, field('Лазер', pick.laser), field('Линза', pick.lens, 'палитра — измерения этого лазера с этой линзой'),
          field('Фотография', App.filePick(img, 'Выбрать фотографию'), revising && !img.files[0] ? 'сейчас — изображение исправляемого плана' : null), field('Название плана', name), field('Ширина работы, мм', width),
          field('Число полос', bands, `целое от 1 до ${maxBands}: из 30 выходных слоёв LightBurn один остаётся для маркеров; картина полос обновляется при изменении`)),
        task.el, h('label', {class: 'row'}, markers, h('span', {}, 'Регистрационные маркеры и идентификатор вне изображения'))),
        state.mode === 'color_path' ? pathPicker(palette, state, () => invalidate()) : null,
        state.mode === 'color_path' ? h('div', {class: 'card toolbar'}, btn('Включить параметры под вопросом в этот план', () => questionedDialog(questioned, state, async () => { await loadPalette(); invalidate(); }), '', !questioned.length),
          h('span', {class: 'muted small'}, state.allowed.length ? `Включено в этот план: ${state.allowed.map((id) => 'K' + id).join(', ')}` : questioned.length ? 'Записи под вопросом по умолчанию исключены' : 'Записей под вопросом нет')) : null,
        state.mode === 'tonal' && all.some((e) => e.questioned) ? h('div', {class: 'alert warn'}, 'Среди допустимых цветов есть производственные «под вопросом». В тональном режиме они используются с предупреждением и без отдельного подтверждения.') : null,
        !palette.length ? h('div', {class: 'alert warn'}, 'Для выбранного режима нет калиброванной передаточной функции: нет валидированных или производственных цветов этого лазера с этой линзой.') : null,
        err,
        h('div', {class: 'row'}, btn('Предпросмотр', doPreview, 'primary'), btn(revising ? 'Создать исправленный план' : 'Создать план', doCreate, 'primary', !(p && previewSig === signature()))),
        p ? h('div', {class: 'stack'}, ...p.warnings.map((w) => questionedWarning(w, all)),
          h('div', {class: 'card stack'}, h('h3', {}, `Полосы: ${p.bands} · различных наборов параметров: ${p.distinct_entries} · пустых полос: ${p.empty_bands}`),
            h('div', {class: 'grid g2'}, sourcePicture(), h('figure', {}, h('img', {class: 'banding', src: p.banding_png, style: 'width:100%;image-rendering:pixelated', alt: 'Полосы в прогнозных цветах титана'}),
              h('figcaption', {class: 'muted small'}, 'Каждая полоса — в прогнозном цвете её измеренного набора параметров'))),
            bandTable(p))) : null);
    }
    let timer = null;
    bands.addEventListener('input', () => {
      clearTimeout(timer);
      if (previewSig) invalidate();
      if (picture() && +bands.value >= 1 && +bands.value <= maxBands) timer = setTimeout(doPreview, 350);    // картина полос для нового N
    });
    [width, markers, img, name].forEach((el) => el.addEventListener('input', () => { if (previewSig) invalidate(); }));
    img.addEventListener('change', () => { if (previewSig) invalidate(); });
    await loadPalette();
    draw();
    return host;
  }
  return {render, questionedWarning};
})();
