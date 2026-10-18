/* Добавить наблюдение: загрузка пары и её проверка (REQ-001, REQ-015). Без параметра pair — форма новой пары. */
'use strict';
(() => {
  const {h, btn, link, get} = App;
  App.register({id: 'ingest', async render(ctx) {
    const title = (isRephoto) => isRephoto
      ? h('div', {}, h('h2', {}, 'Повторная фотография'), h('p', {class: 'sub'}, 'Тот же эксперимент и та же гравировка; требуется только новый RAW-снимок.'))
      : h('div', {}, h('h2', {}, 'Добавить эксперимент'), h('p', {class: 'sub'}, 'Фактический файл LightBurn, фотография, лазер, линза и использованный титан.'));
    const back = link('/experiments', 'Назад к экспериментам');
    const backTo = (pair) => link('/experiment/' + (pair.plan_id ? 'plan-' + pair.plan_id : 'eng-' + pair.engraving_id), 'Назад к эксперименту');
    if (ctx.query.pair) {
      let pair;
      try { pair = await get('/pairs/' + ctx.query.pair); }
      catch (e) { return h('div', {class: 'card empty'}, h('h3', {}, 'Пара не найдена'), h('p', {}, 'Её можно начать заново.'), link('/ingest', 'Новая пара')); }
      return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(Boolean(pair.rephoto_of)), h('span', {class: 'spacer'}), backTo(pair)), await IngestReview.render(pair, () => App.render({preserveScroll: true})));
    }
    if (ctx.query.rephoto) {
      try {
        const source = await get('/pairs/' + ctx.query.rephoto);
        return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(true), h('span', {class: 'spacer'}), backTo(source)), IngestUpload.rephoto(source));
      } catch (e) {
        return h('div', {class: 'card empty'}, h('h3', {}, 'Исходная пара не найдена'), link('/experiments', 'Вернуться к экспериментам'));
      }
    }
    const [lists, materials] = await Promise.all([App.hardwareLists(), get('/materials')]);
    if (!lists.devices.length || !materials.length) {
      return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(false), h('span', {class: 'spacer'}), back),
        h('div', {class: 'card empty'}, h('h3', {}, !lists.devices.length ? 'Нужен лазер' : 'Добавьте использованный титан'),
          h('p', {}, 'Для каждого измеренного эксперимента сохраняются лазер и конкретная заготовка титана.'),
          !lists.devices.length ? link('/devices', 'Добавить лазер') : link('/setup?tab=material', 'Добавить титан')));
    }
    return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(false), h('span', {class: 'spacer'}), back), await IngestUpload.render(ctx, lists, materials));
  }});
})();
