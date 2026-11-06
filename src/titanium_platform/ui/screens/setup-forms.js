/* Формы установок съёмки (стенда). Заготовки титана — каталог в material-catalog.js. */
'use strict';
const SetupForms = (() => {
  const {h, btn, post, put, del, toast, fail, confirmBox} = App;

  /** Эталонные значения карты установки: опубликованные по умолчанию; свои можно задать списком Lab и вернуть опубликованные (DEC-025). */
  function chartReference(r, reload) {
    const ref = r.chart_reference;
    const values = h('textarea', {rows: '5', 'aria-label': 'Эталонные значения Lab'}, JSON.stringify(ref.patches_lab));
    const white = h('select', {'aria-label': 'Белая точка'}, ['D65', 'D50'].map((w) => h('option', {value: w}, w)));
    white.value = ref.white_point;
    const source = h('input', {value: ref.published ? '' : ref.source, placeholder: 'например, X-Rite ColorChecker Classic после 2014 г., D50'});
    // the rules of setup.save_chart_reference: 24 triples (L 0 to 100, a and b -128 to 127), a source; a wrong text stays as typed with the reason beside it
    const form = Forms.create();
    const triples = form.add('patches_lab', 'Эталонные значения Lab', values, {required: true, help: 'список из 24 троек [L, a, b]: L от 0 до 100, a и b от -128 до 127',
      read: () => {
        let list;
        try { list = JSON.parse(values.value); } catch (_) { return {ok: false, message: 'Нужен список из 24 троек [L, a, b], записанный как в примере: [[37.5, 12, 14], ...]'}; }
        if (!Array.isArray(list) || list.length !== 24 || list.some((t) => !Array.isArray(t) || t.length !== 3 || t.some((n) => typeof n !== 'number' || !Number.isFinite(n)))) {
          return {ok: false, message: `Нужно ровно 24 тройки чисел [L, a, b]. Сейчас: ${Array.isArray(list) ? list.length : 'не список'}`};
        }
        const at = list.findIndex(([L, a, b]) => L < 0 || L > 100 || a < -128 || a > 127 || b < -128 || b > 127);
        return at >= 0 ? {ok: false, message: `Тройка ${at + 1}: L от 0 до 100, a и b от -128 до 127. Введено: [${list[at].join(', ')}]`} : {ok: true, value: list};
      }});
    const whiteField = form.add('white_point', 'Белая точка значений', white, {required: true, read: () => ({ok: true, value: white.value})});
    const sourceField = form.add('source', 'Откуда взяты значения', source, {required: true});
    const save = btn('Сохранить эталонные значения', async () => {
      const v = form.collect();
      if (!v) return;
      try {
        await put(`/setups/${r.id}/chart-reference`, {patches_lab: v.patches_lab, white_point: v.white_point, observer: '2°', source: v.source});
        toast('Эталонные значения сохранены', 'ok'); reload('rigs');
      } catch (e) { form.fail(e); }
    });
    const reset = ref.published ? null : btn('Вернуть опубликованные значения', async () => {
      try { await del(`/setups/${r.id}/chart-reference`); toast('Возвращены опубликованные значения', 'ok'); reload('rigs'); } catch (e) { fail(e); }
    });
    return h('details', {}, h('summary', {}, `Эталонные значения карты: ${ref.published ? 'опубликованные' : 'свои'} · ${ref.white_point} / ${ref.observer}`),
      h('p', {class: 'muted small'}, 'Источник: ' + (ref.published ? 'опубликованные значения ColorChecker Classic (sRGB, D65), пересчитанные в CIELAB D65 / 2°' : ref.source)
        + '. Фотографии этой установки корректируются по этим значениям; уже принятые измерения не меняются.'),
      triples,
      h('div', {class: 'grid g2'}, whiteField, sourceField),
      form.error,
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
      // setup.save_capture_setup: every one of the five is required; a refusal is said beside the box it names or above the buttons
      const form = Forms.create();
      const fields = [['name', 'Название', f.name], ['camera', 'Камера', f.camera], ['lighting', 'Освещение', f.lighting], ['angle', 'Угол съёмки', f.angle],
        ['reference_chart', 'Эталонная карта', f.chart]].map(([name, label, input]) => form.add(name, label, input, {required: true}));
      const save = btn(r.id ? 'Сохранить установку' : 'Добавить установку', async () => {
        const body = form.collect();
        if (!body) return;
        try { if (r.id) await put('/setups/' + r.id, body); else await post('/setups', body); toast('Установка съёмки сохранена', 'ok'); reload('rigs'); }
        catch (e) { form.fail(e); }
      }, 'primary');
      const remove = r.id ? btn('Удалить', () => confirmBox('Удалить установку', `«${I18N.name(r.name)}». Установку, на которую сняты сохранённые фотографии, удалить нельзя.`, 'Удалить',
        async () => { await del('/setups/' + r.id); toast('Установка удалена', 'ok'); reload('rigs'); }), 'danger') : null;
      return h('div', {class: 'card stack'}, h('strong', {}, r.id ? `Установка № ${r.id}${r.last_used ? ' · использовалась в прошлый раз' : ''}` : 'Добавить установку'),
        r.legacy ? h('div', {class: 'alert warn'}, 'Заглушка для пар, загруженных до того, как у каждой фотографии появилась установка съёмки. Новые фотографии на неё не загружаются.') : null,
        h('div', {class: 'grid g2'}, ...fields),
        r.id ? chartReference(r, reload) : null,
        form.error,
        h('div', {class: 'row'}, save, remove));
    };
    return h('div', {class: 'stack'}, h('div', {class: 'alert'}, 'Установка съёмки описывает, как сделана фотография: камера, свет, угол и эталонная карта. Она хранится с каждой фотографией эксперимента; '
      + 'при загрузке по умолчанию выбирается установка прошлой фотографии.'),
      ...items.map((r) => editor(r)), editor());
  }

  return {rigsTab};
})();
