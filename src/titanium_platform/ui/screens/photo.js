/* Непрерывная фотогравировка: Тональный и «Цветовой путь» на одной передаточной функции (REQ-004, DEC-007, DEC-018, DEC-032).
   Предпросмотр считает N полос без сохранения; план создаётся по тому же расчёту. Параметры между измеренными не интерполируются. */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, form, toast, fail, go, table, num, labText, swatch} = App;
  const MODES = [['tonal', 'Тональный'], ['color_path', 'Цветовой путь']];
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 0)} кГц · ${num(p.speed, 0)} мм/с`;

  function bandTable(p) {
    return table(['Полоса', 'Доля кадра', 'Параметры', 'Прогнозный цвет', 'Уверенность', 'Ожидаемая ошибка ΔE', 'Стабильность'], p.layers.map((l) => [
      l.name, (l.share * 100).toFixed(1) + ' %', params(l.parameters), h('span', {}, swatch(l.prediction.lab), labText(l.prediction.lab)),
      num(l.prediction.confidence), num(l.prediction.expected_delta_e), l.prediction.stability.assessed ? 'дисперсия ' + num(l.prediction.stability.variance) : 'не оценена']));
  }

  function pathPicker(palette, state, redraw) {
    const list = h('div', {class: 'stack'});
    state.path.forEach((id, i) => {
      const e = palette.find((x) => x.id === id);
      if (!e) return;
      const swap = (a, b) => { [state.path[a], state.path[b]] = [state.path[b], state.path[a]]; redraw(); };
      list.append(h('div', {class: 'row'}, `${i + 1}.`, swatch(e.lab), labText(e.lab), h('span', {class: 'spacer'}),
        btn('Выше', () => swap(i - 1, i), '', i === 0), btn('Ниже', () => swap(i, i + 1), '', i === state.path.length - 1),
        btn('Убрать', () => { state.path.splice(i, 1); redraw(); })));
    });
    const free = palette.filter((e) => !state.path.includes(e.id));
    const adders = free.map((e) => {
      const b = h('button', {type: 'button', class: 'btn', onClick: () => { state.path.push(e.id); redraw(); }}, swatch(e.lab), 'Добавить ' + labText(e.lab));
      return b;
    });
    return h('div', {class: 'card stack'}, h('h3', {}, 'Траектория в цветовом пространстве титана'),
      h('p', {class: 'muted small'}, 'Выберите минимум два разных цвета и расположите их по порядку: яркость изображения будет двигаться вдоль этого пути.'),
      state.path.length ? list : h('p', {class: 'muted'}, 'Траектория пуста'),
      free.length ? h('div', {class: 'row'}, adders) : h('p', {class: 'muted small'}, palette.length ? 'Все допустимые цвета уже в траектории' : 'Нет допустимых цветов для этого лазера с этой линзой'));
  }

  App.register({id: 'photo', async render(ctx) {
    const lists = await App.hardwareLists();
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте лазер'), link('/devices', 'Лазеры'));
    return PhotoForm.render(ctx, lists, {bandTable, pathPicker, MODES});
  }});
})();
