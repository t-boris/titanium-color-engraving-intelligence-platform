/* Форма непрерывной фотогравировки: режим, изображение, число полос, предпросмотр и создание плана (REQ-004, DEC-032).
   Предпросмотр и создание плана используют один расчёт на сервере; «Создать план» доступно только после предпросмотра
   с теми же значениями. Любое изменение значений предпросмотр сбрасывает. */
'use strict';
const PhotoForm = (() => {
  const {h, fill, btn, field, link, get, form, toast, fail, go} = App;

  async function render(ctx, lists, parts) {
    const {bandTable, pathPicker, MODES} = parts;
    const state = {mode: ctx.query.mode === 'color_path' ? 'color_path' : 'tonal', path: [], allowed: [], preview: null};
    const host = h('div', {class: 'stack'});
    const pick = App.laserLensPicker(lists, {device: ctx.query.device, lens: ctx.query.lens,
      onChange: async () => { state.path = []; state.allowed = []; await loadPalette(); invalidate(); }});
    const img = h('input', {type: 'file', accept: 'image/*', 'aria-label': 'Фотография для гравировки'});
    const name = h('input', {placeholder: 'Название плана'}), width = h('input', {type: 'number', step: 'any', value: 80});
    const bands = h('input', {type: 'number', step: '1', min: '1', value: 32, 'aria-describedby': 'bands-help'});
    const markers = h('input', {type: 'checkbox'});
    let palette = [];
    const err = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const show = (m) => { err.textContent = m; err.hidden = !m; };

    const body = (create) => {
      const fd = new FormData();
      fd.append('device_id', pick.deviceId()); fd.append('lens_id', pick.lensValue()); fd.append('mode', state.mode); fd.append('width_mm', width.value); fd.append('bands', bands.value);
      fd.append('path_ids', JSON.stringify(state.path)); fd.append('allowed_questioned', JSON.stringify(state.allowed)); fd.append('image', img.files[0]);
      if (create) { fd.append('name', name.value); fd.append('markers', markers.checked); }
      return fd;
    };
    const signature = () => JSON.stringify([pick.deviceId(), pick.lensValue(), state.mode, width.value, bands.value, state.path, state.allowed, img.files[0] && img.files[0].name + img.files[0].size]);
    let previewSig = null;

    async function loadPalette() {
      palette = await get(`/palette?${pick.query()}&include_questioned=${state.mode === 'tonal'}`);
    }
    function invalidate() { state.preview = null; previewSig = null; draw(); }

    async function doPreview() {
      show('');
      if (!img.files[0]) return show('Добавьте фотографию для гравировки');
      try { state.preview = await form('/continuous/preview', body(false)); previewSig = signature(); draw(); } catch (e) { show(e.message); }
    }
    async function doCreate(ev) {
      if (!state.preview || previewSig !== signature()) return show('Сначала сделайте актуальный предпросмотр');
      const self = ev.currentTarget;
      self.disabled = true;
      try { const p = await form('/continuous', body(true)); toast('План создан', 'ok'); go('/plans/' + p.id); } catch (e) { show(e.message); self.disabled = false; }
    }

    function draw() {
      const p = state.preview;
      const modeBtns = MODES.map(([id, label]) => h('button', {type: 'button', class: 'btn' + (state.mode === id ? ' primary' : ''), 'aria-pressed': state.mode === id,
        onClick: async () => { if (state.mode === id) return; state.mode = id; state.path = []; state.allowed = []; state.preview = null; await loadPalette(); draw(); }}, label));
      fill(host,
        h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Непрерывная фотогравировка'), h('p', {class: 'sub'}, 'Одна передаточная функция, два режима. Параметры между измеренными наборами не интерполируются.')),
          h('span', {class: 'spacer'}), h('div', {class: 'row', role: 'group', 'aria-label': 'Подрежим фотогравировки'}, modeBtns), link('/colors', 'Карта цветов')),
        h('div', {class: 'card stack'}, h('div', {class: 'grid g2'}, field('Лазер', pick.laser), field('Линза', pick.lens, 'палитра — измерения этого лазера с этой линзой'),
          field('Фотография', App.filePick(img, 'Выбрать фотографию')), field('Название плана', name), field('Ширина работы, мм', width),
          field('Число полос', bands, 'положительное целое; 1–255 (слоёв в LightBurn не больше 255)')),
        h('label', {class: 'row'}, markers, h('span', {}, 'Регистрационные маркеры и идентификатор вне изображения'))),
        state.mode === 'color_path' ? pathPicker(palette, state, () => invalidate()) : null,
        state.mode === 'tonal' && palette.some((e) => e.questioned) ? h('div', {class: 'alert warn'}, 'Среди допустимых цветов есть производственные «под вопросом». В тональном режиме они используются с предупреждением и без отдельного подтверждения.') : null,
        !palette.length ? h('div', {class: 'alert warn'}, 'Для выбранного режима нет калиброванной передаточной функции: нет валидированных или производственных цветов этого лазера с этой линзой.') : null,
        err,
        h('div', {class: 'row'}, btn('Предпросмотр', doPreview, 'primary'), btn('Создать план', doCreate, 'primary', !(p && previewSig === signature()))),
        p ? h('div', {class: 'stack'}, ...p.warnings.map((w) => h('div', {class: 'alert warn'}, [h('strong', {}, 'Используются производственные параметры под вопросом. '),
          'Отдельное подтверждение не требуется. ', link('/knowledge/' + w.knowledge_ids[0], 'Посмотреть наблюдения')])),
        h('div', {class: 'card'}, h('h3', {}, `Полосы: ${p.bands} · различных наборов параметров: ${p.distinct_entries} · пустых полос: ${p.empty_bands}`), bandTable(p))) : null);
    }
    [width, bands, markers, img, name].forEach((el) => el.addEventListener('input', () => { if (previewSig) invalidate(); }));
    await loadPalette();
    draw();
    return host;
  }
  return {render};
})();
