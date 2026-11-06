/* Continuous photo engraving uses one transfer function for tonal and color path modes (REQ-004).
   Preview and plan use the same calculation; measured parameters are not interpolated. */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, form, toast, fail, go, table, num, labText, swatch} = App;
  const MODES = [['tonal', 'Tonal'], ['color_path', 'Color path']];
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 0)} kHz · ${num(p.speed, 0)} mm/s`;

  function bandTable(p) {
    return table(['Band', 'Image fraction', 'Parameters', 'Predicted color', 'Confidence', 'Expected error ΔE', 'Stability'], p.layers.map((l) => [
      l.name, (l.share * 100).toFixed(1) + ' %', params(l.parameters), h('span', {}, swatch(l.prediction.lab), labText(l.prediction.lab)),
      num(l.prediction.confidence), num(l.prediction.expected_delta_e), l.prediction.stability.assessed ? 'variance ' + num(l.prediction.stability.variance) : 'not assessed']));
  }

  function pathPicker(palette, state, redraw) {
    const list = h('div', {class: 'stack'});
    state.path.forEach((id, i) => {
      const e = palette.find((x) => x.id === id);
      if (!e) return;
      const swap = (a, b) => { [state.path[a], state.path[b]] = [state.path[b], state.path[a]]; redraw(); };
      list.append(h('div', {class: 'row'}, `${i + 1}.`, swatch(e.lab), labText(e.lab), h('span', {class: 'spacer'}),
        btn('Move up', () => swap(i - 1, i), '', i === 0), btn('Move down', () => swap(i, i + 1), '', i === state.path.length - 1),
        btn('Remove', () => { state.path.splice(i, 1); redraw(); })));
    });
    const free = palette.filter((e) => !state.path.includes(e.id));
    const adders = free.map((e) => {
      const b = h('button', {type: 'button', class: 'btn', onClick: () => { state.path.push(e.id); redraw(); }}, swatch(e.lab), 'Add ' + labText(e.lab));
      return b;
    });
    return h('div', {class: 'card stack'}, h('h3', {}, 'Path through the titanium color space'),
      h('p', {class: 'muted small'}, 'Choose at least two different colors and arrange them in order. Image brightness follows this path.'),
      state.path.length ? list : h('p', {class: 'muted'}, 'The path is empty'),
      free.length ? h('div', {class: 'row'}, adders) : h('p', {class: 'muted small'}, palette.length ? 'All available colors are already in the path' : 'No colors are available for this laser and lens'));
  }

  App.register({id: 'photo', async render(ctx) {
    const lists = await App.hardwareLists();
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Add a laser first'), link('/devices', 'Lasers'));
    return PhotoForm.render(ctx, lists, {bandTable, pathPicker, MODES});
  }});
})();
