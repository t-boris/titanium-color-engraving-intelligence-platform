/* Add an observation: upload and review a pair (REQ-001, REQ-015). Without a pair parameter, start a new pair. */
'use strict';
(() => {
  const {h, btn, link, get} = App;
  App.register({id: 'ingest', async render(ctx) {
    const title = (isRephoto) => isRephoto
      ? h('div', {}, h('h2', {}, 'Repeat photograph'), h('p', {class: 'sub'}, 'The same experiment and engraving; only a new RAW photograph is required.'))
      : h('div', {}, h('h2', {}, 'Add experiment'), h('p', {class: 'sub'}, 'The actual LightBurn file, photograph, laser, lens and titanium stock used.'));
    const back = link('/experiments', 'Back to experiments');
    const backTo = (pair) => link('/experiment/' + (pair.plan_id && pair.plan_mode !== 'Restored from file' ? 'plan-' + pair.plan_id : 'eng-' + pair.engraving_id),
      'Back to experiment');
    if (ctx.query.pair) {
      let pair;
      try { pair = await get('/pairs/' + ctx.query.pair); }
      catch (e) { return h('div', {class: 'card empty'}, h('h3', {}, 'Pair not found'), h('p', {}, 'You can start again.'), link('/ingest', 'New pair')); }
      return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(Boolean(pair.rephoto_of)), h('span', {class: 'spacer'}), backTo(pair)), await IngestReview.render(pair, () => App.render({preserveScroll: true})));
    }
    // every photograph names the rig it was taken on (REQ-009); the placeholder of old pairs is not offered
    const rigsOf = async () => (await get('/setups')).filter((r) => !r.legacy);
    if (ctx.query.rephoto) {
      try {
        const [source, rigs] = await Promise.all([get('/pairs/' + ctx.query.rephoto), rigsOf()]);
        return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(true), h('span', {class: 'spacer'}), backTo(source)), IngestStages.upload(), IngestUpload.rephoto(source, rigs));
      } catch (e) {
        return h('div', {class: 'card empty'}, h('h3', {}, 'Original pair not found'), link('/experiments', 'Return to experiments'));
      }
    }
    const [lists, stocks, rigs] = await Promise.all([App.hardwareLists(), MaterialPicker.total(), rigsOf()]);       // only whether any stock record exists
    if (!lists.devices.length || !stocks || !rigs.length) {
      const [heading, add] = !lists.devices.length ? ['A laser is required', link('/devices', 'Add laser')]
        : !stocks ? ['Add the titanium stock used', link('/setup?tab=material', 'Add stock')]
          : ['Describe the capture setup', link('/setup?tab=rigs', 'Add capture setup')];
      return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(false), h('span', {class: 'spacer'}), back),
        h('div', {class: 'card empty'}, h('h3', {}, heading),
          h('p', {}, 'Each measured experiment records the laser, specific titanium stock and capture setup used for its photograph.'),
          add));
    }
    return h('div', {class: 'stack'}, h('div', {class: 'row'}, title(false), h('span', {class: 'spacer'}), back), IngestStages.upload(), await IngestUpload.render(ctx, lists, rigs));
  }});
})();
