/* Vector work color selection, variants, and AI coloring controls. */
'use strict';
const VectorColours = (() => {
  const {h, fill, btn, field, pill, fail, modal, facts, num, labText, agreed, CAUTION, steadiness, STEADY, originText, sourcesBlock} = App;
  const {chip, params, seconds, palette, de, duration, BASIS} = VectorEditor;
  const MODES = [['closest', 'Closer to original'], ['tonality', 'Preserve tonality'], ['contrast', 'Contrast neighbors'], ['random', 'Random']];
  const MODE = {...Object.fromEntries(MODES), artistic: 'Artistic', fewer_layers: 'Fewer layers (legacy mode)', ai: 'AI'};   // the old mode only names variants saved with it
  /** Palette groups for «Artistic» (vector-detail I-6): the measured colours its hues are laid out from. */
  const SUBSETS = [['all', 'all colors'], ['warm', 'warm'], ['cool', 'cool'], ['bright', 'bright']];
  const SUBSET = Object.fromEntries(SUBSETS);
  /** AI coloring styles and their expected effects; custom descriptions are supplied by the operator. */
  const STYLES = [
    ['realistic', 'Realistic', 'Match the photo as closely as the palette allows, keeping adjacent regions distinct.'],
    ['artistic', 'Artistic', 'Keep the subject recognizable with a harmonious palette and warm highlights against cool shadows.'],
    ['impressionism', 'Impressionism', 'Emphasize light and color over lines, with warm highlights, colorful shadows, and no flat black.'],
    ['cubism', 'Cubism', 'Use flat earth-tone facets and strong contrast at every boundary, even when colors differ from life.'],
    ['custom', 'Custom description', 'Describe the desired appearance; AI follows it within measured colors.']];
  const STYLE = Object.fromEntries(STYLES.map(([id, name]) => [id, name]));
  const aiName = (ai) => 'AI · ' + (ai.style === 'custom' ? `«${(ai.text || '').slice(0, 40)}»` : STYLE[ai.style] || ai.style)
    + (ai.free_lightness ? ' · free lightness' : '') + (ai.photo ? ' · with photo' : '');
  const STATUS = {automatic: ['selected automatically', 'ok'], hand: ['selected manually', 'ok'], accepted: ['selected manually', 'ok'],
    missing: ['titanium color no longer measured', 'bad'], excluded: ['not engraved', '']};
  const HOW = {fastest_within_tolerance: 'fastest within tolerance', nearest: 'nearest', tonality: 'by tonality', random: 'random',
    contrast: 'contrasts with neighbors', artistic: 'artistic, preserving lightness order',
    cover: 'shared layer', nearest_outside_tolerance: 'nearest, outside tolerance', kept: 'operator choice', hand: 'operator choice', ai: 'AI choice'};
  const stability = (e) => (e.stability && e.stability.assessed ? 'variance ' + num(e.stability.variance) : 'not assessed');
  /** Color confidence, agreement count, and a warning when automatic selection excludes it. */
  const confidence = (e) => h('span', {}, e.confidence == null ? 'not assessed' : num(e.confidence), h('div', {class: 'muted small'}, agreed(e.agreement)),
    e.caution ? pill(e.caution === 'superseded' ? 'superseded' : 'color changed', 'bad') : null);

  const ORDERS = [['near', 'Closest to original color'], ['stable', 'Most stable'], ['fast', 'Fastest']];
  const RANK = {stable: 2, single: 1, doubtful: 0};
  const BETTER = 6;                                               // maximum number of more stable replacement colors

  /** Choose measured titanium colors, showing provenance and stability. */
  const pick = (j, title, sourceLab, current, onPick) => pickFrom(() => palette(j), title, sourceLab, current, onPick,
    {imageUrl: `/api/plans/${j.id}/source-image`});
  /** The same window over any list of measured colours (``load``: a promise of them), as the photo work's inscriptions need it. */
  async function pickFrom(load, title, sourceLab, current, onPick, options = {}) {
    let entries;
    try { entries = await load(); } catch (e) { return fail(e); }
    const now = entries.find((e) => e.id === current) || null;
    let chosen = now;
    let targetLab = [...sourceLab];
    const idOrder = (a, b) => String(a.id).localeCompare(String(b.id));
    const near = (a, b) => de(a.lab, targetLab) - de(b.lab, targetLab) || idOrder(a, b);
    const rate = (e) => Number.isFinite(e.time_s_per_cm2) ? e.time_s_per_cm2 : Infinity;
    const confidence = (e) => Number.isFinite(e.confidence) ? e.confidence : -Infinity;
    const compare = {near, fast: (a, b) => (rate(a) === rate(b) ? near(a, b) : rate(a) - rate(b)),
      stable: (a, b) => RANK[steadiness(b)] - RANK[steadiness(a)] || (confidence(a) === confidence(b) ? 0 : confidence(b) - confidence(a)) || near(a, b)};
    const better = h('div', {}), choice = h('p', {class: 'small'});
    const swatchOf = (e, text) => h('button', {type: 'button',
      class: `vw-swatch steady-${steadiness(e)}` + (e.basis === 'as-shot' ? ' as-shot' : '') + (e.automatic ? '' : ' not-auto') + (chosen && e.id === chosen.id ? ' picked' : ''),
      style: `background:rgb(${e.srgb.join(',')})`, 'data-entry': e.id, title: text, 'aria-label': text, onClick: () => choose(e)});
    const text = (e) => `${labText(e.lab)} · ΔE ${num(de(e.lab, targetLab))} · ${STEADY[steadiness(e)][0]} · ${originText(e.sources)} · ${seconds(e.time_s_per_cm2)}`;
    const detail = (e) => h('div', {class: 'stack small'},
      h('div', {}, chip(e.srgb), ' ', labText(e.lab), ` · ΔE ${num(de(e.lab, targetLab))} from the target sample`,
        now && now.id !== e.id ? ` · ΔE ${num(de(e.lab, now.lab))} from current` : ''),
      h('div', {}, pill(...STEADY[steadiness(e)]), ' ', `Confidence ${e.confidence == null ? 'not assessed' : num(e.confidence)} · ${agreed(e.agreement)}`,
        e.caution ? [' ', pill(CAUTION[e.caution], 'warn')] : null),
      h('div', {class: 'muted'}, `${BASIS[e.basis] || ''} · engravings ${e.engravings}, photos ${e.photographs} · ${seconds(e.time_s_per_cm2)}`),
      h('div', {class: 'muted'}, params(e.parameters)),
      e.automatic ? null : h('div', {class: 'muted'}, e.caution ? `Automatic selection excludes this color: ${CAUTION[e.caution]}; you can select it manually.`
        : 'Automatic selection excludes this color (uncalibrated or slower than the time limit); you can select it manually.'),
      sourcesBlock(e.sources || [], e.agreement, e.lab, true),
      chosen && chosen.id === e.id ? null : h('div', {}, btn('Select this color', () => choose(e), 'btn-small')));
    const colours = App.list({items: entries, page: 30, key: (e) => String(e.id), open: now ? String(now.id) : null,
      row: (e) => [swatchOf(e, text(e)), h('span', {class: 'lst-text'}, `ΔE ${num(de(e.lab, targetLab))} · ${STEADY[steadiness(e)][0]}`),
        h('span', {class: 'muted small'}, seconds(e.time_s_per_cm2))],
      details: detail, search: (e) => [labText(e.lab), originText(e.sources), ...(e.sources || []).map((s) => s.title)].join(' '),
      filters: [{key: 'steady', label: 'Repeatability', options: [['stable', 'verified by repeat'], ['single', 'one engraving'], ['doubtful', 'uncertain']],
        test: (e, v) => steadiness(e) === v},
        {key: 'time', label: 'Time per cm²', select: true, options: [['60', 'up to 1 minute'], ['300', 'up to 5 minutes'], ['unknown', 'time not estimated']],
          test: (e, v) => v === 'unknown' ? !Number.isFinite(e.time_s_per_cm2) : Number.isFinite(e.time_s_per_cm2) && e.time_s_per_cm2 <= Number(v)}],
      sorts: ORDERS.map(([k, name]) => [k, name, compare[k]]), empty: 'No colors match this filter.'});
    function choose(e) { chosen = e; paint(); colours.refresh(); }
    function paint() {
      const stabler = now && steadiness(now) !== 'stable'
        ? entries.filter((e) => e.id !== now.id && steadiness(e) === 'stable').sort((a, b) => de(a.lab, now.lab) - de(b.lab, now.lab)).slice(0, BETTER) : [];
      fill(better, now && steadiness(now) !== 'stable' ? h('div', {class: 'stack small vw-better'},
        h('strong', {}, 'More stable and similar to the current color'),
        stabler.length ? h('div', {class: 'vw-swatches'}, stabler.map((e) => swatchOf(e, `ΔE ${num(de(e.lab, now.lab))} from current · ${text(e)}`)))
          : h('span', {class: 'muted'}, 'The palette has no colors verified by repeat.')) : null);
      fill(choice, chosen ? ['Selected measured titanium color: ', chip(chosen.srgb), ' ', labText(chosen.lab), ` · ΔE ${num(de(chosen.lab, targetLab))} from the target sample · ${STEADY[steadiness(chosen)][0]}`]
        : h('span', {class: 'muted'}, 'Select a color'));
    }
    const target = App.targetColor({initial: targetLab, imageUrl: options.imageUrl, submitLabel: 'Find recipes', onSelect: (lab) => {
      targetLab = lab; paint(); colours.refresh();
    }});
    paint();
    modal(title, h('div', {class: 'stack'},
      target.el,
      h('p', {class: 'muted small'}, `All measured colors for this laser, lens, and titanium grade (from any plate): ${entries.length}. A green dot means verified by repeat; red means engravings differ; `
        + 'the others have one engraving. Sources shows the tests and works behind each color. Select a square to choose a color or open its row for details.'),
      now ? h('p', {class: 'small'}, 'Current: ', chip(now.srgb), ' ', pill(...STEADY[steadiness(now)]), ` ${originText(now.sources)}`) : null,
      better, colours.el, choice), [{label: 'Cancel', run: (m) => m.close()},
      {label: 'Apply', cls: 'primary', run: async (m) => { if (!chosen) return; m.close(); await onPick(chosen.id); }}]);
  }

  /** “Color details” as a short list (DEC-090): a line per source colour — its colour and number, the titanium colour, how it was chosen,
      the recipe and ΔE, with the actions on the whole colour; how the titanium colour was measured, where it is known from, its confidence,
      stability and time open under the line. Pages of 30: every colour of a work is edited on one page. */
  function colourTable(run) {
    let j = null;
    // a refusal of the server is told above the list that asked, not in a toast that goes away (ux-save-feedback-p0, REQ-003)
    const place = Forms.notice({what: 'Color change', kept: 'Work colors remain unchanged.'});
    const titanium = (c) => (c.entry_id == null ? null : j.entries[c.entry_id]);
    const list = App.list({id: 'vw.colour-table', items: [], page: 30, key: (c) => String(c.index),
      row: (c) => {
        const e = titanium(c), [label, kind] = STATUS[c.status] || [null, ''];
        return [chip(c.srgb, labText(c.lab)), h('strong', {}, `#${c.index + 1}`), '→', e ? chip(e.srgb, labText(e.lab)) : '—', label ? pill(label, kind) : null,
          h('span', {class: 'lst-text small'}, e ? params(e.parameters) : '—'),
          c.delta_e == null ? null : h('span', {}, `ΔE ${num(c.delta_e)}`), c.outside_tolerance ? pill('outside tolerance', 'bad') : null,
          h('span', {class: 'muted small'}, `regions ${c.regions}`)];
      },
      actions: (c) => [btn('Change', () => pick(j, `Group color #${c.index + 1}`, c.lab, c.entry_id, (id) => run({op: 'set_colour', colour: c.index, entry_id: id}, place))),
        c.status === 'hand' || c.status === 'accepted' ? btn('Automatic', () => run({op: 'set_colour', colour: c.index, entry_id: null}, place)) : null,
        c.status === 'excluded' ? btn('Engrave', () => run({op: 'include_colour', colour: c.index}, place))
          : btn('Do not engrave', () => run({op: 'exclude_colour', colour: c.index}, place))],
      details: (c) => {
        const e = titanium(c);
        return facts([['Original color', `${labText(c.lab)} · regions ${c.regions}`],
          ['Titanium color', e ? h('span', {}, chip(e.srgb), ' ', labText(e.lab), c.how && HOW[c.how] ? ` · ${HOW[c.how]}` : '') : STATUS[c.status] ? STATUS[c.status][0] : '—'],
          ['Recipe', e ? params(e.parameters) : null], ['Measurement basis', e ? BASIS[e.basis] || '—' : null],
          ['Sources', e ? `${originText(e.sources)} · photos ${e.photographs}` : null], ['Confidence', e ? confidence(e) : null],
          ['Stability', e ? stability(e) : null], ['Time', e ? seconds(e.time_s_per_cm2) : null]]);
      },
      search: (c) => [`#${c.index + 1}`, titanium(c) ? params(titanium(c).parameters) : '', titanium(c) ? originText(titanium(c).sources) : ''].join(' '),
      filters: [VectorEditor.COLOUR_FILTER],
      sorts: [...VectorEditor.COLOUR_SORTS, ['fast', 'Fastest', (a, b) => ((titanium(a) || {}).time_s_per_cm2 ?? Infinity) - ((titanium(b) || {}).time_s_per_cm2 ?? Infinity)
        || a.index - b.index]],
      empty: 'No source colors match this selection.'});
    const el = h('div', {class: 'vw-wide stack'}, h('p', {class: 'muted small'}, 'Each row shows an original color, its titanium color, recipe, and ΔE. '
      + 'Open a row to see measurement basis, sources, confidence, stability, and time.'), place.error, list.el);
    return {el, show(next) { j = next; list.items = j.colours; list.refresh(); }};
  }

  /** The colouring variants as a list (the tab is narrow); a variant of another split version cannot be restored until undo brings that
      version back. A short list
      (DEC-090): a line per variant — its number and way, mean ΔE and “current” or “Restore”; its totals open under the line; the newest first. */
  function variantList(run) {
    let j = null;
    const place = Forms.notice({what: 'Restore variant', kept: 'The work keeps its previous coloring.'});
    const way = (v) => (v.mode === 'ai' && v.ai ? aiName(v.ai) : (MODE[v.mode] || '—') + (v.mode === 'artistic' ? ` · ${SUBSET[v.subset] || SUBSET.all}` : '')
      + (v.mode === 'random' || v.mode === 'artistic' ? ` (variant ${v.seed})` : ''));
    // the server says whether a variant is restorable (a size change keeps the regions, DEC-002 of work-size-and-splitting-a-region-again);
    // a view without the flag goes by the split version
    const elsewhere = (v) => (v.restorable != null ? v.restorable === false : v.version != null && v.version !== j.document.version);
    const current = (v) => v.number === j.colouring.variant;
    const list = App.list({id: 'vw.variants', items: [], key: (v) => String(v.number), className: 'vw-variants',
      row: (v) => [h('strong', {class: 'lst-text'}, `#${v.number} · ${way(v)}`), h('span', {class: 'muted small'}, `ΔE ${num(v.totals.mean_delta_e)}`),
        current(v) ? pill('current', 'ok') : elsewhere(v) ? h('span', {class: 'muted small'}, `on split #${v.version}`) : null],
      actions: (v) => (current(v) || elsewhere(v) ? [] : [btn('Restore', () => run({op: 'restore', variant: v.number}, place))]),
      details: (v) => h('div', {class: 'stack small'},
        h('div', {}, `recipes ${v.totals.recipes} · ΔE ${num(v.totals.mean_delta_e)} · within tolerance ${v.totals.within_tolerance} of ${v.totals.colours} · `
          + (v.totals.seconds == null ? 'time not estimated' : duration(v.totals.seconds)) + ` · ${v.at.replace('T', ' ').slice(0, 16)}`),
        elsewhere(v) ? h('div', {class: 'muted'}, `On split #${v.version}; undo to return to it.`) : null),
      search: (v) => `#${v.number} ${way(v)}`,
      sorts: [['new', 'Newest first', (a, b) => b.number - a.number],
        ['de', 'Lowest ΔE', (a, b) => (a.totals.mean_delta_e ?? Infinity) - (b.totals.mean_delta_e ?? Infinity) || b.number - a.number],
        ['fast', 'Fastest', (a, b) => (a.totals.seconds ?? Infinity) - (b.totals.seconds ?? Infinity) || b.number - a.number]],
      empty: 'No variants yet'});
    return {el: h('div', {class: 'stack'}, place.error, list.el), show(next) { j = next; list.items = j.variants; list.refresh(); }};
  }

  /** “Artistic” (DEC-079): each press a new layout of hues from the chosen palette group; light places stay light. */
  function artisticRow(run, place) {
    const group = h('select', {'aria-label': 'Color group'}, SUBSETS.map(([v, name]) => h('option', {value: v}, name)));
    return h('div', {class: 'row'}, btn(MODE.artistic, () => run({op: 'assign', mode: 'artistic', subset: group.value}, place), 'btn-small'),
      h('label', {class: 'row small'}, 'from ', group),
      h('span', {class: 'muted small'}, 'a new hue arrangement on each click, preserving the original lightness order'));
  }

  /** AI coloring controls preserve inputs while the work updates. */
  function aiBlock(j, run, permit) {
    const style = h('select', {'aria-label': 'AI coloring style'}, STYLES.map(([v, name]) => h('option', {value: v}, name)));
    const hint = h('span', {class: 'small muted'});
    const text = h('input', {type: 'text', placeholder: 'for example: stained glass with lots of blue'});
    // the description is asked for only with the style of the operator's own, and then it must be there and short enough (ai_colouring.request)
    const aiForm = Forms.create();
    const own = aiForm.add('text', 'Custom description', text, {required: true, maxLength: j.ai.max_text,
      read: () => (style.value !== 'custom' ? {ok: true, value: null}
        : (text.value.trim() === '' ? {ok: false, message: 'Describe the desired coloring'}
          : text.value.trim().length > j.ai.max_text ? {ok: false, message: `Maximum ${j.ai.max_text} characters. Entered: ${text.value.trim().length}`} : {ok: true, value: text.value.trim()}))});
    const free = h('input', {type: 'checkbox'}), photo = h('input', {type: 'checkbox'});
    const off = h('p', {class: 'alert warn', hidden: true});
    const WHY = {key: 'AI coloring is disabled because no OpenAI key is configured. Set one on the Network screen; other coloring methods remain available.',
      library: 'AI coloring is disabled because the language model library is not installed. Install the application dependencies as described in the README; other methods remain available.'};
    const current = h('p', {class: 'small'});
    let busy = false;
    const go = btn('Color with AI', async (ev) => {
      const self = ev.currentTarget;
      const v = aiForm.collect();
      if (!v) return;                                                // the description says what is wrong beside itself and stays as typed
      busy = true; self.disabled = true; self.textContent = 'AI is selecting colors…';
      try {
        await run({op: 'ai_colour', style: style.value, ...(style.value === 'custom' ? {text: v.text} : {}), free_lightness: free.checked}, aiForm);   // a refusal stays above the button
      } finally { busy = false; self.textContent = 'Color with AI'; sync(j); }
    }, 'primary');
    function sync(next) {
      j = next;
      fill(hint, (STYLES.find(([v]) => v === style.value) || STYLES[0])[2]);
      own.hidden = style.value !== 'custom';
      photo.checked = j.ai.photo_allowed;
      go.disabled = busy || !j.ai.available;
      off.hidden = j.ai.available;
      fill(off, WHY[j.ai.missing] || WHY.key);
      const now = j.colouring.mode === 'ai' && j.colouring.ai ? j.colouring.ai : null;
      fill(current, now ? ['Currently colored by AI: ', h('strong', {}, aiName(now).slice(5)), now.note ? ` — ${now.note}` : ''] : null);
      current.hidden = !now;
    }
    style.addEventListener('change', () => sync(j));
    photo.addEventListener('change', () => permit(photo.checked, aiForm));
    sync(j);
    const el = h('div', {class: 'stack vw-ai'}, h('h4', {}, 'AI coloring'),
      h('div', {class: 'vw-split-fields'}, field('Style', style, null), own),
      aiForm.error,
      hint,
      h('div', {class: 'vw-split-actions'},
        h('label', {class: 'row'}, free, h('span', {}, 'Free lightness: AI may change the light-to-dark order (preserved by default)')),
        h('label', {class: 'row'}, photo, h('span', {}, `Allow sending a reduced photo (up to ${j.ai.photo_px} px) for this work`)), go),
      off, current,
      h('p', {class: 'muted small'}, 'AI selects measured titanium colors for each image color according to the chosen style. It receives only numerical data: image colors (Lab) '
        + 'and their proportions, adjacent colors, and measured titanium colors. It does not receive the photo unless you allow it. Manual color choices remain. '
        + 'AI choices are saved in the variant and are not recalculated when restored.'));
    return {el, update: sync};
  }

  function settingsBar(j, run) {
    const s = j.settings;
    // the tolerance and the longest time are read as the server's rules state them (conversion._threshold, colormap.time_limit); an empty ΔE box leaves
    // the work's own tolerance and an empty time box means no limit; a wrong one is refused beside its box and stays in it
    const form = Forms.create();
    const Q = Forms.QUANTITIES;
    const tol = Forms.numberInput(Q.deltaE, {value: s.tolerance_de});
    const maxTime = Forms.numberInput(Q.maxTime, {value: s.max_time ?? '', placeholder: 'no limit'});
    const asShot = h('input', {type: 'checkbox', checked: s.include_as_shot});
    const tolField = form.add('tolerance_de', 'ΔE tolerance', tol, {quantity: 'deltaE'});
    const timeField = form.add('max_time', 'Maximum time', maxTime, {quantity: 'maxTime'});
    return h('div', {class: 'toolbar'}, tolField, timeField,
      h('label', {class: 'row'}, asShot, h('span', {}, 'Include uncalibrated colors (captured without a reference)')),
      btn('Apply', () => {
        const v = form.collect();
        if (v) run({op: 'settings', tolerance_de: v.tolerance_de, max_time: v.max_time, include_as_shot: asShot.checked}, form);     // a refusal is told beside its box, the typed values stay
      }), form.error);
  }

  /** Build the color and AI tabs and update them with the current work. */
  function parts(j, run, permit) {
    const editor = VectorEditor.create(j, run, {pick});
    const ai = aiBlock(j, run, permit);
    const intro = h('p', {class: 'muted small'}), empty = h('div', {}), bar = h('div', {});
    const detailed = colourTable(run), kept = variantList(run), rows = detailed.el;
    let settings = null;
    function show(next) {
      j = next;
      fill(intro, `Palette: ${j.palette_size} measured colors. Each original color uses the fastest color within ΔE tolerance, or the nearest otherwise; `
        + 'colors far from the original can be outlined in the image and do not block the file.');
      fill(empty, j.palette_size ? null : h('div', {class: 'alert warn'}, 'No measured fill colors are available for this laser, lens, and titanium grade.'));
      const key = JSON.stringify(j.settings);
      if (key !== settings) { settings = key; fill(bar, settingsBar(j, run)); }       // fields are retained while settings are unchanged
      detailed.show(j);
      kept.show(j);
    }
    show(j);
    const modesPlace = Forms.notice({what: 'Recolor', kept: 'The work keeps its previous coloring.'});
    const colours = h('div', {class: 'stack vw-colours'}, intro, empty, bar,
      h('div', {class: 'vw-modes'}, h('span', {class: 'muted small'}, 'Automatically recolor the entire work:'),
        h('div', {class: 'row'}, MODES.map(([mode, label]) => btn(label, () => run({op: 'assign', mode}, modesPlace), 'btn-small'))), artisticRow(run, modesPlace), modesPlace.error),
      h('div', {class: 'row'}, btn('Color details…', () => modal('Color details', rows, [{label: 'Close', run: (m) => m.close()}]))));
    const saved = h('div', {class: 'stack'}, h('h4', {}, 'Coloring variants'),
      h('p', {class: 'muted small'}, 'Every whole-work coloring, whether automatic, AI-generated, or edited, is saved as a variant you can restore.'), kept.el);
    return {colours, variants: saved, ai: ai.el, editor, update(next) { show(next); ai.update(next); editor.update(next); }};
  }

  return {parts, pickFrom, styleName: (style) => STYLE[style] || style};
})();
