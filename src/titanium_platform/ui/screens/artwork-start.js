/* Цветная гравировка: форма начала (изображение, ширина, порог ΔE, предел времени, маркеры) и окна замены цвета и
   параметров под вопросом (REQ-004, REQ-042, DEC-009, DEC-018, DEC-075). Порог ΔE всегда явный: либо введён здесь, либо
   взят из правил выбранного лазера с линзой. Палитра — знания этого лазера и этой линзы (DEC-063); из цветов в пределах
   порога выбирается самый быстрый по времени гравировки. */
'use strict';
const ArtworkParts = (() => {
  const {h, btn, link, get, patch, go, modal, num, labText, swatch} = App;
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 0)} кГц · ${num(p.speed, 0)} мм/с`;
  const seconds = (s) => (s == null ? 'время не оценить' : `${num(s, 1)} с/см²`);
  // the reason of a doubt joins one message per broken threshold with '; ' (knowledge.refresh): each is translated
  const doubt = (reason) => reason.split('; ').map((part) => I18N.tr(part)).join('; ');

  function startForm(lists, ctx) {
    const begin = ctx.start || {device: ctx.query.device, lens: ctx.query.lens};         // the laser and lens the workshop chose last; the address wins (REQ-001)
    const pick = App.laserLensPicker(lists, {device: begin.device, lens: begin.lens});
    const img = h('input', {type: 'file', accept: 'image/*'});
    const name = h('input', {placeholder: 'Название плана'}), width = Forms.numberInput(Forms.QUANTITIES.workWidth, {value: 60});
    const thr = Forms.numberInput(Forms.QUANTITIES.deltaE, {placeholder: 'из правил'}), markers = h('input', {type: 'checkbox'});
    const maxTime = Forms.numberInput(Forms.QUANTITIES.maxTime, {placeholder: 'без предела'});
    // REQ-020: цветное изображение или плоские цветные области; задача записывается в план и переходит к измерениям его фото
    const task = Tasks.chooser('color_image', {hint: 'цветное изображение — по умолчанию; «Заливка» — если это плоские цветные области'});
    // every box says what it takes and, when it is wrong, why, beside itself with what was typed kept; a refusal of the server stands where the field it names is
    const f = Forms.create();
    const laserField = f.add('laser', 'Лазер', pick.laser, {read: () => ({ok: true, value: pick.deviceId()})});
    const lensField = f.add('lens', 'Линза', pick.lens, {help: 'палитра — измерения этого лазера с этой линзой', read: () => ({ok: true, value: pick.lensValue()})});
    const imageField = f.add('image', 'Изображение', App.filePick(img, 'Выбрать изображение'), {required: true,
      read: () => (img.files[0] ? {ok: true, value: img.files[0]} : {ok: false, message: 'Добавьте изображение для цветной гравировки'})});
    const nameField = f.add('name', 'Название плана', name, {required: true});               // conversion.start_discrete: «give the plan a name»
    const widthField = f.add('width_mm', 'Ширина работы', width, {quantity: 'workWidth', required: true});
    const thrField = f.add('threshold', 'Порог ΔE', thr, {quantity: 'deltaE', help: 'пусто — взять допуск из правил этого лазера с линзой; если его нет, порог нужно задать'});
    const timeField = f.add('max_time', 'Наибольшее время гравировки', maxTime, {quantity: 'maxTime', help: 'пусто — без предела; более медленные рецепты не выбираются автоматически'});
    const submit = btn('Сопоставить цвета', async (ev) => {
      const v = f.collect();
      if (!v) return;
      if (!task.check()) return f.fail(new Error('Цели задачи заполнены неверно: исправьте отмеченные поля'));
      const fd = new FormData();
      fd.append('device_id', v.laser); fd.append('lens_id', v.lens); fd.append('name', v.name); fd.append('width_mm', v.width_mm);
      fd.append('markers', markers.checked); fd.append('image', v.image);
      if (v.threshold != null) fd.append('threshold', v.threshold);
      if (v.max_time != null) fd.append('max_time', v.max_time);
      task.append(fd);
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const p = await App.form('/discrete', fd);
        App.rememberContext({device: pick.deviceId(), lens: pick.lensId()});
        go('/artwork?plan=' + p.id);
      } catch (e) { f.fail(e); self.disabled = false; }
    }, 'primary');
    return h('div', {class: 'stack'}, h('div', {class: 'card empty'}, h('h3', {}, 'Добавьте изображение для цветной гравировки')),
      h('div', {class: 'card stack'}, h('div', {class: 'grid g2'}, laserField, lensField, imageField, nameField, widthField, thrField, timeField), task.el,
        h('p', {class: 'muted small'}, 'Из цветов титана в пределах порога ΔE выбирается самый быстрый по оценке времени гравировки; если такого нет, цвет недостижим.'),
      h('label', {class: 'row'}, markers, h('span', {}, 'Регистрационные маркеры и идентификатор вне изображения')), f.error, submit));
  }

  function replaceDialog(plan, m, palette, reload) {
    let chosen = plan.replacements[m.source_key] || null;
    const rows = palette.map((e) => h('label', {class: 'row'}, h('input', {type: 'radio', name: 'rep', checked: e.id === chosen, onChange: () => { chosen = e.id; }}),
      swatch(e.lab), labText(e.lab), h('span', {class: 'muted small'}, `${params(e.parameters)} · ΔE ${num(e.expected_delta_e)} · уверенность ${num(e.confidence)} · ${seconds(e.time_s_per_cm2)}`)));
    const none = [h('p', {class: 'alert warn'}, 'Нет валидированных или производственных цветов для этого лазера с этой линзой')];
    const place = Forms.notice({what: 'Замена цвета', kept: 'Выбор остался в окне, цвет не заменён.'});
    modal('Заменить цвет', h('div', {class: 'stack'}, h('p', {}, 'Выберите цвет из допустимой палитры (валидированные и производственные).'), ...(rows.length ? rows : none), place.error), [
      {label: 'Отмена', run: (x) => x.close()},
      {label: 'Применить замену', cls: 'primary', run: async (x) => {
        place.clear();
        if (!chosen) return place.say('Выберите цвет из списка выше: без выбора заменять нечем.');
        try { await patch('/discrete/' + plan.id, {replacements: {...plan.replacements, [m.source_key]: chosen}}); } catch (e) { return place.fail(e); }
        x.close(); reload();
      }}]);
  }

  async function questionedDialog(plan, reload) {
    const all = (await get(`/palette?${App.hardwareQuery(plan.device_id, plan.lens_id)}&include_questioned=true`)).filter((e) => e.questioned);
    const picked = new Set(plan.allowed_questioned);
    const rows = all.map((e) => h('div', {class: 'alert warn'},
      h('label', {class: 'row'}, h('input', {type: 'checkbox', checked: picked.has(e.id), onChange: (ev) => { if (ev.target.checked) picked.add(e.id); else picked.delete(e.id); }}), swatch(e.lab), labText(e.lab)),
      h('p', {class: 'small'}, (e.doubt && doubt(e.doubt.reason)) || 'Параметры под вопросом'), link('/knowledge/' + e.id, 'Наблюдения')));
    const place = Forms.notice({what: 'Разрешение', kept: 'Отметки остались в окне, план не изменён.'});
    modal('Включить параметры под вопросом в этот план', h('div', {class: 'stack'},
      h('p', {}, 'Разрешение действует только для этого плана. Стадия знания и флаг не изменятся.'), ...(rows.length ? rows : [h('p', {}, 'Нет производственных параметров под вопросом')]), place.error), [
      {label: 'Отмена', run: (x) => x.close()},
      {label: 'Применить к этому плану', cls: 'primary', run: async (x) => {
        place.clear();
        try { await patch('/discrete/' + plan.id, {allowed_questioned: [...picked]}); } catch (e) { return place.fail(e); }
        x.close(); reload();
      }}]);
  }

  return {startForm, replaceDialog, questionedDialog, params, seconds};
})();
