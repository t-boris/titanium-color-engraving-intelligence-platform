/* Формы заготовок титана и установок съёмки (стенда). */
'use strict';
const SetupForms = (() => {
  const {h, btn, field, post, put, del, toast, fail, confirmBox} = App;
  const val = (el) => el.value.trim();

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
          try { if (m.id) await put('/materials/' + m.id, body()); else await post('/materials', body()); toast('Материал сохранён', 'ok'); reload('material'); }
          catch (e) { fail(e); }
        }, 'primary'));
    };
    return h('div', {class: 'stack'}, h('div', {class: 'alert'}, 'Добавьте отдельную запись для каждой партии или листа. При загрузке результата выберите именно выгравированную заготовку. Для других материалов сначала нужен свой рецепт очистки; титановая очистка к ним не применяется.'),
      ...items.map((m) => editor(m)), editor());
  }

  /** Эталонные значения карты установки: опубликованные по умолчанию; свои можно задать списком Lab и вернуть опубликованные (DEC-025). */
  function chartReference(r, reload) {
    const ref = r.chart_reference;
    const values = h('textarea', {rows: '5', 'aria-label': 'Эталонные значения Lab'}, JSON.stringify(ref.patches_lab));
    const white = h('select', {'aria-label': 'Белая точка'}, ['D65', 'D50'].map((w) => h('option', {value: w}, w)));
    white.value = ref.white_point;
    const source = h('input', {value: ref.published ? '' : ref.source, placeholder: 'например, X-Rite ColorChecker Classic после 2014 г., D50'});
    const save = btn('Сохранить эталонные значения', async () => {
      let patches;
      try { patches = JSON.parse(values.value); } catch (_) { fail(new Error('Эталонные значения записаны неверно: нужен список из 24 троек [L, a, b]')); return; }
      try {
        await put(`/setups/${r.id}/chart-reference`, {patches_lab: patches, white_point: white.value, observer: '2°', source: val(source)});
        toast('Эталонные значения сохранены', 'ok'); reload('rigs');
      } catch (e) { fail(e); }
    });
    const reset = ref.published ? null : btn('Вернуть опубликованные значения', async () => {
      try { await del(`/setups/${r.id}/chart-reference`); toast('Возвращены опубликованные значения', 'ok'); reload('rigs'); } catch (e) { fail(e); }
    });
    return h('details', {}, h('summary', {}, `Эталонные значения карты: ${ref.published ? 'опубликованные' : 'свои'} · ${ref.white_point} / ${ref.observer}`),
      h('p', {class: 'muted small'}, 'Источник: ' + (ref.published ? 'опубликованные значения ColorChecker Classic (sRGB, D65), пересчитанные в CIELAB D65 / 2°' : ref.source)
        + '. Фотографии этой установки корректируются по этим значениям; уже принятые измерения не меняются.'),
      field('24 значения Lab в порядке плашек карты (от коричневой до чёрной)', values),
      h('div', {class: 'grid g2'}, field('Белая точка значений', white), field('Откуда взяты значения', source)),
      h('div', {class: 'row'}, save, reset));
  }

  /** Установки съёмки: камера, свет, угол и эталонная карта. Каждая фотография хранит свою установку (DEC-066). */
  function rigsTab(items, reload) {
    const editor = (r = {}) => {
      const f = {name: h('input', {value: r.name || '', placeholder: 'Например, стол у окна · штатив'}),
        camera: h('input', {value: r.camera || '', placeholder: 'камера и объектив'}),
        lighting: h('input', {value: r.lighting || '', placeholder: 'например, LED 5600 K, два источника'}),
        angle: h('input', {value: r.angle || '', placeholder: 'например, 90°'}),
        chart: h('input', {value: r.reference_chart || 'ColorChecker Classic', placeholder: 'эталонная карта'})};
      const body = () => ({name: val(f.name), camera: val(f.camera), lighting: val(f.lighting), angle: val(f.angle), reference_chart: val(f.chart)});
      const save = btn(r.id ? 'Сохранить установку' : 'Добавить установку', async () => {
        try { if (r.id) await put('/setups/' + r.id, body()); else await post('/setups', body()); toast('Установка съёмки сохранена', 'ok'); reload('rigs'); }
        catch (e) { fail(e); }
      }, 'primary');
      const remove = r.id ? btn('Удалить', () => confirmBox('Удалить установку', `«${r.name}». Установку, на которую сняты сохранённые фотографии, удалить нельзя.`, 'Удалить',
        async () => { await del('/setups/' + r.id); toast('Установка удалена', 'ok'); reload('rigs'); }), 'danger') : null;
      return h('div', {class: 'card stack'}, h('strong', {}, r.id ? `Установка № ${r.id}${r.last_used ? ' · использовалась в прошлый раз' : ''}` : 'Добавить установку'),
        r.legacy ? h('div', {class: 'alert warn'}, 'Заглушка для пар, загруженных до того, как у каждой фотографии появилась установка съёмки. Новые фотографии на неё не загружаются.') : null,
        h('div', {class: 'grid g2'}, field('Название', f.name), field('Камера', f.camera), field('Освещение', f.lighting), field('Угол съёмки', f.angle), field('Эталонная карта', f.chart)),
        r.id ? chartReference(r, reload) : null,
        h('div', {class: 'row'}, save, remove));
    };
    return h('div', {class: 'stack'}, h('div', {class: 'alert'}, 'Установка съёмки описывает, как сделана фотография: камера, свет, угол и эталонная карта. Она хранится с каждой фотографией эксперимента; '
      + 'при загрузке по умолчанию выбирается установка прошлой фотографии.'),
      ...items.map((r) => editor(r)), editor());
  }

  return {materialTab, rigsTab};
})();
