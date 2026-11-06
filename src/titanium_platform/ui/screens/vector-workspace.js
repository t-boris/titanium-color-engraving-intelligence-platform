/* Vector work list, rename and size dialogs, and the workspace layout. */
'use strict';
const VectorWorkspace = (() => {
  const {h, fill, btn, num, field, get, post, del, go, toast, fail, modal, confirmBox} = App;
  const MODE_NAME = {closest: 'Closer to original', tonality: 'Preserve tonality', random: 'Random', fewer_layers: 'Fewer layers (legacy mode)'};
  const STRATEGY_NAME = {photo: 'Photo: color regions', fill: 'Silhouette fill', text: 'Text', line: 'Centerlines', color: 'Color regions (outline)'};
  const TAB_KEY = 'vw.tab';
  const when = (iso) => (iso || '').replace('T', ' ').slice(0, 16);


  // ---- rename ------------------------------------------------------------------------------------------------------------

  // the words of the dialog for what is renamed: a work (vector or photo engraving) or an experiment
  const WORDS = {work: {title: 'Rename work', field: 'Work name', blank: 'Enter a work name', done: 'Work renamed',
                        button: 'Rename work'},
                 experiment: {title: 'Rename experiment', field: 'Experiment name', blank: 'Enter an experiment name',
                              done: 'Experiment renamed', button: 'Rename experiment'}};

  /** The dialog with the name in a field. A blank name is refused before any request, the name as it is closes the dialog without one,
      Enter saves (not while an input method is composing), and a second press while the first is being saved does nothing. ``base`` is
      the API of the kind of work (a photo engraving work is renamed at ``/photo-works``, an experiment at ``/experiments``). */
  function renameDialog(id, current, done, base, words) {
    let saving = false, box = null;
    const input = h('input', {value: current, autocomplete: 'off', 'aria-label': words.field,
      onKeydown: (ev) => { if (ev.key === 'Enter' && !ev.isComposing) { ev.preventDefault(); save(box.close).catch(fail); } }});
    // the name is required; a blank one, and any refusal of the server, is said beside the field and the dialog stays open with the name as typed
    const form = Forms.create();
    const nameField = form.add('name', 'Name', input, {required: true, read: () => (input.value.trim() ? {ok: true, value: input.value.trim()} : {ok: false, message: words.blank})});
    async function save(close) {
      if (saving) return;
      const v = form.collect();
      if (!v) return;
      const title = v.name;
      if (title === current) { close(); return; }
      saving = true;
      try {
        const made = await post(`${base}/${encodeURIComponent(id)}/rename`, {name: title});
        toast(words.done, 'ok');
        close();
        done(made.name);
      } catch (e) { saving = false; form.fail(e); }
    }
    box = modal(words.title, h('div', {class: 'stack'}, nameField, form.error), [
      {label: 'Cancel', run: (m) => m.close()}, {label: 'Save', cls: 'primary', run: (m) => save(m.close)}]);
    if (input.select) input.select();
  }

  /** The pencil beside a work's name. ``renamed(name)`` is told the stored name once it is saved; the button keeps the name it shows,
      so its label and the dialog's field are right for the next rename too. ``kind`` is ``work`` or ``experiment`` (the words). */
  function renameButton(id, name, renamed, base = '/vector', kind = 'work') {
    let shown = name;
    const words = WORDS[kind];
    const label = () => `${words.button} «${shown}»`;
    const el = h('button', {type: 'button', class: 'btn btn-small vw-rename', title: 'Rename', 'aria-label': label(),
      onClick: () => renameDialog(id, shown, (stored) => { shown = stored; el.setAttribute('aria-label', label()); renamed(stored); }, base, words)}, '✎');
    return el;
  }

  // ---- saved works --------------------------------------------------------------------------------------------------

  /** Describe the selected coloring mode. */
  function colouringName(w) {
    if (w.mode === 'ai') return 'AI · ' + (w.ai_style === 'custom' ? `«${(w.ai_text || '').slice(0, 40)}»` : VectorColours.styleName(w.ai_style));
    return MODE_NAME[w.mode] || null;
  }

  function workCard(w) {
    const open = () => go('/vector?plan=' + w.id);
    const photo = w.strategy === 'photo';
    const how = colouringName(w);
    const copy = btn('Make a copy', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { const made = await post(`/vector/${w.id}/copy`, {}); toast('Copy created and opened; the original work is unchanged', 'ok'); go('/vector?plan=' + made.id); }
      catch (e) { fail(e); self.disabled = false; }
    }, 'btn-small');
    const remove = btn('Delete', () => confirmBox(`Delete work “${w.name}”?`,
      'The source image, split, and all coloring variants will be deleted permanently. Make a copy first if you want to keep them.',
      'Delete', async () => { await del('/plans/' + w.id); toast('Work deleted', 'ok'); App.render(); }), 'danger btn-small');
    const thumb = h('a', {class: 'vw-thumb', href: '#/vector?plan=' + w.id, 'aria-label': 'Open work ' + w.name},
      h('img', {src: `/api/vector/${w.id}/thumb.png?v=${encodeURIComponent(w.version + '-' + w.updated_at)}`, alt: '', loading: 'lazy'}));
    const title = h('h3', {}, w.name);
    const pencil = renameButton(w.id, w.name, (stored) => { w.name = stored; fill(title, stored); thumb.setAttribute('aria-label', 'Open work ' + stored); });
    return h('article', {class: 'card vw-work-card'}, thumb,
      h('div', {class: 'stack vw-work-info'}, h('div', {class: 'vw-name-row'}, title, pencil),
        h('p', {class: 'small'}, `${num(w.width_mm, 1)} × ${num(w.height_mm, 1)} mm · ` + (photo ? VectorSplit.name(w.algorithm) : STRATEGY_NAME[w.strategy] || w.strategy)),
        photo ? h('p', {class: 'small'}, `colors ${w.n_colours} · regions ${w.regions} · layers ${w.layers}` + (w.zones ? ` · photo zones ${w.zones}` : '')) : h('p', {class: 'small'}, `regions ${w.regions} · layers ${w.layers}`),
        h('p', {class: 'small'}, how ? `Coloring: ${how}` : 'Not colored yet', w.variants ? ` · variants ${w.variants}` : ''),
        ...VectorReview.cardLines(w),
        h('p', {class: 'small muted'}, `updated ${when(w.updated_at)}`),
        h('div', {class: 'row'}, btn('Open', open, 'primary btn-small'), copy, remove)));
  }

  /** List saved vector works and create a new one. */
  async function list() {
    const works = await get('/vector');
    const create = btn('New work', () => go('/vector?new=1'), 'primary');
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Vector work'),
        h('p', {class: 'sub'}, 'Saved works, selections, and their appearance are stored on this computer. Open a work to continue or make a copy to revise it while keeping the original.')),
        h('span', {class: 'spacer'}), create),
      works.length ? h('div', {class: 'vw-works'}, works.map(workCard))
        : h('div', {class: 'card empty'}, h('h3', {}, 'No works yet'), h('p', {class: 'muted'}, 'Upload an image to split it into color regions, color them, and export to LightBurn.'), create));
  }

  // ---- work layout --------------------------------------------------------------------------------------------------------

  // ---- work size ----------------------------------------------------------------------------------------------------------------

  const mm = (v) => String(Math.round(v * 10) / 10);           // a field's value: a dot, one decimal at most

  /** The dialog “Work size”: the width and the height in mm, linked by the picture's proportions; the side the operator typed last is
      what is sent (``resize({width_mm} | {height_mm})`` answers with the work, or null when the server refused and the error is shown).
      The size as it is closes the dialog without a request; Enter saves. */
  function sizeDialog(size, resize) {
    let saving = false, box = null, edited = 'width';
    const ratio = size.height / size.width;
    const onEnter = (ev) => { if (ev.key === 'Enter' && !ev.isComposing) { ev.preventDefault(); save(box.close).catch(fail); } };
    // the side typed last is sent, and it must be a positive number of millimetres (vector_job.resize); the other side only follows it, by the proportions
    const form = Forms.create();
    const sideRule = Forms.QUANTITIES.workWidth;
    const width = Forms.numberInput(sideRule, {step: '0.1', value: mm(size.width), onKeydown: onEnter});
    const height = Forms.numberInput(sideRule, {step: '0.1', value: mm(size.height), onKeydown: onEnter});
    const widthField = form.add('width', 'Width', width, {quantity: 'workWidth', required: true, read: () => (edited === 'width' ? Forms.readNumber(width, sideRule, {required: true}) : {ok: true, value: null})});
    const heightField = form.add('height', 'Height', height, {quantity: sideRule, required: true, read: () => (edited === 'height' ? Forms.readNumber(height, sideRule, {required: true}) : {ok: true, value: null})});
    width.addEventListener('input', () => { edited = 'width'; const w = parseFloat(width.value); height.value = w > 0 ? mm(w * ratio) : ''; });
    height.addEventListener('input', () => { edited = 'height'; const hh = parseFloat(height.value); width.value = hh > 0 ? mm(hh / ratio) : ''; });
    async function save(close) {
      if (saving) return;
      const v = form.collect();
      if (!v) return;                                                   // the side typed says what is wrong beside itself; the boxes keep what was typed
      const value = v[edited];
      if (Math.abs(value - size[edited]) < 0.05) { close(); return; }
      saving = true;
      try {
        const work = await resize(edited === 'width' ? {width_mm: value} : {height_mm: value}, form);           // a refusal is told in this dialog, the boxes keep what was typed
        if (!work) { saving = false; return; }
        toast(`Work size is now ${num(work.document.size_mm.width, 1)} × ${num(work.document.size_mm.height, 1)} mm; the split and colors are unchanged`, 'ok');
        close();
      } catch (e) { saving = false; throw e; }
    }
    box = modal('Work size', h('div', {class: 'stack'},
      h('p', {class: 'small muted'}, 'One side uses your value and the other follows the image proportions. Regions, colors, lettering, and photo zones stay in their '
        + 'positions; the split is not recalculated. You can undo this change (Ctrl+Z).'),
      h('div', {class: 'toolbar'}, widthField, heightField), form.error), [
      {label: 'Cancel', run: (m) => m.close()}, {label: 'Resize', cls: 'primary', run: (m) => save(m.close)}]);
    if (width.select) width.select();
  }

  /** Work heading, size, copy, plan, and LightBurn file actions. */
  function header(j, actions) {
    const title = h('div', {class: 'vw-work-title'});
    let current = j.document.size_mm;
    const size = actions.resize ? btn('Size…', () => sizeDialog(current, actions.resize), 'btn-small vw-size') : null;
    const copy = btn('Make a copy', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { const made = await post(`/vector/${j.id}/copy`, {}); toast('Copy created and opened; this work is unchanged', 'ok'); go('/vector?plan=' + made.id); }
      catch (e) { fail(e); self.disabled = false; }
    });
    const el = h('header', {class: 'vw-work-head'}, h('a', {class: 'btn btn-small', href: '#/vector'}, '← My works'), title, h('span', {class: 'spacer'}),
      h('a', {class: 'btn btn-small', href: '#/plans/' + j.id}, 'Engraving plan'), copy, btn('LightBurn file', actions.file, 'primary'));
    function update(next) {
      current = next.document.size_mm;
      const pencil = renameButton(next.id, next.name, (stored) => (actions.renamed ? actions.renamed(stored) : update({...next, name: stored})));
      fill(title, h('p', {class: 'small muted'}, 'Vector work'), h('div', {class: 'vw-name-row'}, h('h2', {}, next.name), pencil),
        h('p', {class: 'sub'}, `${num(current.width, 1)} × ${num(current.height, 1)} mm`, size ? [' ', size] : null,
          ` · split #${next.document.version} · layers ${next.layers.length + (next.zones || []).length} of ${next.layer_cap}`
          + ((next.zones || []).length ? `, including ${next.zones.length} photo zones` : '')));
    }
    update(j);
    return {el, update};
  }

  /** Three columns: tabs, editor image, and editor panel. */
  function frame({head, items, editor, initial}) {
    const box = App.tabs(items, {initial, remember: TAB_KEY, label: 'Work sections', prefix: 'vw-tab'});
    const left = h('aside', {class: 'vw-left', 'aria-label': 'Work settings'}, box.list, h('div', {class: 'vw-panels'}, box.panels));
    return {el: h('div', {class: 'vw-work workspace'}, head, h('div', {class: 'vw-work-body'}, left, editor.el)), select: box.select};
  }

  return {list, header, frame, renameButton};
})();
