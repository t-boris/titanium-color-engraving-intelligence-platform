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
    // every photograph names the rig it was taken on (REQ-009); the placeholder of old pairs is not offered
    const rigsOf = async () => (await get('/setups')).filter((r) => !r.legacy);
    if (ctx.query.rephoto) {
      try {
        const [source, rigs] = await Promise.all([get('/pairs/' + ctx.query.rephoto), rigsOf()]);
        return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(true), h('span', {class: 'spacer'}), backTo(source)), IngestUpload.rephoto(source, rigs));
      } catch (e) {
        return h('div', {class: 'card empty'}, h('h3', {}, 'Исходная пара не найдена'), link('/experiments', 'Вернуться к экспериментам'));
      }
    }
    const [lists, materials, rigs] = await Promise.all([App.hardwareLists(), get('/materials'), rigsOf()]);
    if (!lists.devices.length || !materials.length || !rigs.length) {
      const [heading, add] = !lists.devices.length ? ['Нужен лазер', link('/devices', 'Добавить лазер')]
        : !materials.length ? ['Добавьте использованный титан', link('/setup?tab=material', 'Добавить титан')]
          : ['Опишите установку съёмки', link('/setup?tab=rigs', 'Добавить установку съёмки')];
      return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(false), h('span', {class: 'spacer'}), back),
        h('div', {class: 'card empty'}, h('h3', {}, heading),
          h('p', {}, 'Для каждого измеренного эксперимента сохраняются лазер, конкретная заготовка титана и установка съёмки, на которой сделана фотография.'),
          add));
    }
    return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(false), h('span', {class: 'spacer'}), back), await IngestUpload.render(ctx, lists, materials, rigs));
  }});
})();
