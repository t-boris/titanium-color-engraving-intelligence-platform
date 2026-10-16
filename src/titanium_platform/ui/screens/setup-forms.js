/* Формы идентичности лазера с линзой и конкретных партий материалов. */
'use strict';
const SetupForms = (() => {
  const {h, btn, field, post, put, del, toast, fail, confirmBox} = App;
  const val = (el) => el.value.trim();

  /** Выпадающий список лазеров; пустое значение — «без лазера» (REQ-017). */
  function devicePicker(devices, current) {
    return h('select', {'aria-label': 'Лазер'}, [h('option', {value: ''}, 'без лазера')].concat((devices || []).map((d) => h('option', {value: d.id, selected: d.id === current}, d.name))));
  }

  function lensPicker(lenses, current) {
    return h('select', {'aria-label': 'Линза'}, [h('option', {value: ''}, 'без линзы')].concat((lenses || []).map((l) => h('option', {value: l.id, selected: l.id === current}, `${l.name} · ${l.focal_length_mm} мм`))));
  }

  function newProfileForm(reload, devices = [], lenses = []) {
    const device = devicePicker(devices, null);
    const lens = lensPicker(lenses, null);
    const name = h('input', {placeholder: 'Например, JPT M7 · F-Theta 174 мм'});
    return h('div', {class: 'stack'}, h('div', {class: 'grid g2'}, field('Название установки', name), field('Лазер', device), field('Конкретная линза', lens)),
      h('p', {class: 'muted small'}, 'Здесь сохраняется только связка оборудования. Мощность, частота, скорость, импульс, интервал и проходы задаются отдельно для каждой платы и слоя.'),
      btn('Сохранить лазер + линзу', async () => {
        try { const p = await post('/profiles', {name: val(name), device_id: device.value === '' ? null : +device.value, lens_id: lens.value === '' ? null : +lens.value}); toast('Связка лазера и линзы сохранена', 'ok'); reload(p.id); } catch (e) { fail(e); }
      }, 'primary'));
  }

  function materialTab(items, reload) {
    const editor = (m = {}) => {
      const f = {name: h('input', {value: m.name || '', placeholder: 'Например, Grade 2 · лист A'}),
        family: h('input', {value: m.family || 'Titanium', placeholder: 'Titanium, Steel, Brass…'}),
        grade: h('input', {value: m.grade || '', placeholder: 'Grade 2, Ti-6Al-4V…'}),
        batch: h('input', {value: m.batch || '', placeholder: 'номер партии или листа'}),
        thickness: h('input', {type: 'number', step: 'any', min: '0', value: m.thickness_mm ?? '', placeholder: 'мм'}),
        surface: h('input', {value: m.surface || '', placeholder: 'шлифовка, полировка…'})};
      const body = () => ({name: val(f.name), family: val(f.family), grade: val(f.grade) || null, batch: val(f.batch) || null,
        thickness_mm: f.thickness.value === '' ? null : +f.thickness.value, surface: val(f.surface) || null});
      return h('div', {class: 'card stack'}, m.id ? h('strong', {}, `Материал № ${m.id}`) : h('strong', {}, 'Добавить материал'),
        h('div', {class: 'grid g2'}, field('Название', f.name), field('Материал', f.family), field('Марка / сплав', f.grade), field('Партия или лист', f.batch),
          field('Толщина, мм', f.thickness), field('Поверхность / подготовка', f.surface)),
        btn(m.id ? 'Сохранить материал' : 'Добавить материал', async () => {
          try { if (m.id) await put('/materials/' + m.id, body()); else await post('/materials', body()); toast('Материал сохранён', 'ok'); reload(null, 'material'); }
          catch (e) { fail(e); }
        }, 'primary'));
    };
    return h('div', {class: 'stack'}, h('div', {class: 'alert'}, 'Добавьте отдельную запись для каждой партии или листа. При загрузке результата выберите именно выгравированную заготовку. Для других материалов сначала нужен свой рецепт очистки; титановая очистка к ним не применяется.'),
      ...items.map((m) => editor(m)), editor());
  }

  return {newProfileForm, devicePicker, lensPicker, materialTab};
})();
