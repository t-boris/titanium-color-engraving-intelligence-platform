/* Добавить наблюдение: загрузка пары и её проверка (REQ-001, REQ-015). Без параметра pair — форма новой пары. */
'use strict';
(() => {
  const {h, btn, link, get} = App;
  App.register({id: 'ingest', async render(ctx) {
    const title = (isRephoto) => isRephoto
      ? h('div', {}, h('h2', {}, 'Повторная фотография'), h('p', {class: 'sub'}, 'Тот же эксперимент и та же гравировка; требуется только новый RAW-снимок.'))
      : h('div', {}, h('h2', {}, 'Добавить эксперимент'), h('p', {class: 'sub'}, 'Фактический файл LightBurn, фотография, связка лазер+линза и использованный титан.'));
    const back = link('/experiments', 'Назад к экспериментам');
    if (ctx.query.pair) {
      let pair;
      try { pair = await get('/pairs/' + ctx.query.pair); }
      catch (e) { return h('div', {class: 'card empty'}, h('h3', {}, 'Пара не найдена'), h('p', {}, 'Её можно начать заново.'), link('/ingest', 'Новая пара')); }
      return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(Boolean(pair.rephoto_of)), h('span', {class: 'spacer'}), back), await IngestReview.render(pair, () => App.render({preserveScroll: true})));
    }
    if (ctx.query.rephoto) {
      try {
        const source = await get('/pairs/' + ctx.query.rephoto);
        return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(true), h('span', {class: 'spacer'}), back), IngestUpload.rephoto(source));
      } catch (e) {
        return h('div', {class: 'card empty'}, h('h3', {}, 'Исходная пара не найдена'), link('/experiments', 'Вернуться к экспериментам'));
      }
    }
    const [profiles, materials] = await Promise.all([get('/profiles'), get('/materials')]);
    if (!profiles.length || !materials.length) {
      return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(false), h('span', {class: 'spacer'}), back),
        h('div', {class: 'card empty'}, h('h3', {}, !profiles.length ? 'Нужна связка лазер + линза' : 'Добавьте использованный титан'),
          h('p', {}, 'Для каждого измеренного эксперимента необходимо сохранить аппаратную связку и конкретную заготовку титана.'), link('/profiles', 'Настройки оборудования и титана')));
    }
    return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(false), h('span', {class: 'spacer'}), back), await IngestUpload.render(ctx, profiles, materials));
  }});
})();
