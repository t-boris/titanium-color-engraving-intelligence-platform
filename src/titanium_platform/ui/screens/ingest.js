/* Добавить наблюдение: загрузка пары и её проверка (REQ-001, REQ-015). Без параметра pair — форма новой пары. */
'use strict';
(() => {
  const {h, btn, link, get} = App;
  App.register({id: 'ingest', async render(ctx) {
    const title = h('div', {}, h('h2', {}, 'Добавить наблюдение'), h('p', {class: 'sub'}, 'Пара «файл LightBurn + фотография со стенда с эталонной картой».'));
    const back = link('/experiments', 'Назад к экспериментам');
    if (ctx.query.pair) {
      let pair;
      try { pair = await get('/pairs/' + ctx.query.pair); }
      catch (e) { return h('div', {class: 'card empty'}, h('h3', {}, 'Пара не найдена'), h('p', {}, 'Её можно начать заново.'), link('/ingest', 'Новая пара')); }
      return h('div', {class: 'stack'}, h('div', {class: 'row'}, title, h('span', {class: 'spacer'}), back), await IngestReview.render(pair, () => App.render()));
    }
    const [profiles, setups, materials] = await Promise.all([get('/profiles'), get('/setups'), get('/materials')]);
    if (!profiles.length || !setups.length) {
      return h('div', {class: 'stack'}, h('div', {class: 'row'}, title, h('span', {class: 'spacer'}), back),
        h('div', {class: 'card empty'}, h('h3', {}, 'Нужны профиль лазера и стенд'), h('p', {}, 'Без них пару принять нельзя.'), link('/profiles', 'Профили')));
    }
    return h('div', {class: 'stack'}, h('div', {class: 'row'}, title, h('span', {class: 'spacer'}), back), await IngestUpload.render(ctx, profiles, setups, materials));
  }});
})();
