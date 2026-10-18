/* Цветная гравировка: форма начала (изображение, ширина, порог ΔE, маркеры) и окна замены цвета и параметров под вопросом
   (REQ-004, DEC-009, DEC-018). Порог ΔE всегда явный: либо введён здесь, либо взят из правил выбранного лазера с линзой.
   Палитра — знания этого лазера и этой линзы (DEC-063). */
'use strict';
const ArtworkParts = (() => {
  const {h, btn, field, link, get, patch, go, modal, num, labText, swatch} = App;
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 0)} кГц · ${num(p.speed, 0)} мм/с`;
  // the reason of a doubt joins one message per broken threshold with '; ' (knowledge.refresh): each is translated
  const doubt = (reason) => reason.split('; ').map((part) => I18N.tr(part)).join('; ');

  function startForm(lists, ctx) {
    const pick = App.laserLensPicker(lists, {device: ctx.query.device, lens: ctx.query.lens});
    const img = h('input', {type: 'file', accept: 'image/*', 'aria-label': 'Изображение'});
    const name = h('input', {placeholder: 'Название плана'}), width = h('input', {type: 'number', step: 'any', value: 60});
    const thr = h('input', {type: 'number', step: 'any', min: '0', placeholder: 'из правил'}), markers = h('input', {type: 'checkbox'});
    // REQ-020: цветное изображение или плоские цветные области; задача записывается в план и переходит к измерениям его фото
    const task = Tasks.chooser('color_image', {hint: 'цветное изображение — по умолчанию; «Заливка» — если это плоские цветные области'});
    const err = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const show = (m) => { err.textContent = m; err.hidden = !m; };
    const submit = btn('Сопоставить цвета', async (ev) => {
      show('');
      if (!img.files[0]) return show('Добавьте изображение для цветной гравировки');
      const fd = new FormData();
      fd.append('device_id', pick.deviceId()); fd.append('lens_id', pick.lensValue()); fd.append('name', name.value); fd.append('width_mm', width.value);
      fd.append('markers', markers.checked); fd.append('image', img.files[0]);
      if (thr.value !== '') fd.append('threshold', thr.value);
      task.append(fd);
      const self = ev.currentTarget;
      self.disabled = true;
      try { const p = await App.form('/discrete', fd); go('/artwork?plan=' + p.id); } catch (e) { show(e.message); self.disabled = false; }
    }, 'primary');
    return h('div', {class: 'stack'}, h('div', {class: 'card empty'}, h('h3', {}, 'Добавьте изображение для цветной гравировки')),
      h('div', {class: 'card stack'}, h('div', {class: 'grid g2'}, field('Лазер', pick.laser), field('Линза', pick.lens, 'палитра — измерения этого лазера с этой линзой'),
        field('Изображение', App.filePick(img, 'Выбрать изображение')), field('Название плана', name), field('Ширина работы, мм', width),
        field('Порог ΔE', thr, 'пусто — взять допуск из правил этого лазера с линзой; если его нет, порог нужно задать')), task.el,
      h('label', {class: 'row'}, markers, h('span', {}, 'Регистрационные маркеры и идентификатор вне изображения')), err, submit));
  }

  function replaceDialog(plan, m, palette, reload) {
    let chosen = plan.replacements[m.source_key] || null;
    const rows = palette.map((e) => h('label', {class: 'row'}, h('input', {type: 'radio', name: 'rep', checked: e.id === chosen, onChange: () => { chosen = e.id; }}),
      swatch(e.lab), labText(e.lab), h('span', {class: 'muted small'}, `${params(e.parameters)} · ΔE ${num(e.expected_delta_e)} · уверенность ${num(e.confidence)}`)));
    const none = [h('p', {class: 'alert warn'}, 'Нет валидированных или производственных цветов для этого лазера с этой линзой')];
    modal('Заменить цвет', h('div', {class: 'stack'}, h('p', {}, 'Выберите цвет из допустимой палитры (валидированные и производственные).'), ...(rows.length ? rows : none)), [
      {label: 'Отмена', run: (x) => x.close()},
      {label: 'Применить замену', cls: 'primary', run: async (x) => {
        if (!chosen) throw new Error('Выберите цвет');
        await patch('/discrete/' + plan.id, {replacements: {...plan.replacements, [m.source_key]: chosen}});
        x.close(); reload();
      }}]);
  }

  async function questionedDialog(plan, reload) {
    const all = (await get(`/palette?${App.hardwareQuery(plan.device_id, plan.lens_id)}&include_questioned=true`)).filter((e) => e.questioned);
    const picked = new Set(plan.allowed_questioned);
    const rows = all.map((e) => h('div', {class: 'alert warn'},
      h('label', {class: 'row'}, h('input', {type: 'checkbox', checked: picked.has(e.id), onChange: (ev) => { if (ev.target.checked) picked.add(e.id); else picked.delete(e.id); }}), swatch(e.lab), labText(e.lab)),
      h('p', {class: 'small'}, (e.doubt && doubt(e.doubt.reason)) || 'Параметры под вопросом'), link('/knowledge/' + e.id, 'Наблюдения')));
    modal('Включить параметры под вопросом в этот план', h('div', {class: 'stack'},
      h('p', {}, 'Разрешение действует только для этого плана. Стадия знания и флаг не изменятся.'), ...(rows.length ? rows : [h('p', {}, 'Нет производственных параметров под вопросом')])), [
      {label: 'Отмена', run: (x) => x.close()},
      {label: 'Применить к этому плану', cls: 'primary', run: async (x) => { await patch('/discrete/' + plan.id, {allowed_questioned: [...picked]}); x.close(); reload(); }}]);
  }

  return {startForm, replaceDialog, questionedDialog, params};
})();
