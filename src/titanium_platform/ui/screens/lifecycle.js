/* File lifecycle, readiness, download, and accepted-result navigation. */
'use strict';
const Lifecycle = (() => {
  const {h, fill, btn, link, pill, num, duration} = App;           // toast, fail and go are read when called: this file loads before the router's
  const STAGES = [['prepared', 'Prepared'], ['file', 'File downloaded'], ['result', 'Result added'], ['verified', 'Verified']];
  const STAGE_NAME = Object.fromEntries(STAGES);
  const STATE_WORD = {done: 'done', current: 'current', todo: 'upcoming'};
  const when = (iso) => (iso || '').replace('T', ' ').slice(0, 16);
  const mm = (size) => (size ? `${num(size.width, 1)} × ${num(size.height, 1)} mm` : null);

  /** Fetch a file for browser download without navigating to the API URL. */
  async function download(path, fallbackName) {
    let res;
    try { res = await fetch('/api' + path); } catch (_) { throw new Error('Cannot reach the local service. Is the application running?'); }
    if (!res.ok) {
      let raw = null;
      try { const d = await res.json(); raw = (d.detail || d).error; } catch (_) { raw = null; }
      throw new Error(raw ? I18N.tr(raw) : `Server error (${res.status}). The file was not received.`);
    }
    const name = decodeURIComponent((res.headers.get('content-disposition') || '').split("UTF-8''")[1] || fallbackName);
    const url = URL.createObjectURL(await res.blob());
    const a = h('a', {href: url, download: name});
    document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }

  /** Download once at a time, retaining errors and allowing retry. */
  function downloadButton(path, name, label, {onDone = null, disabled = false, cls = '', note = null} = {}) {
    const failure = h('div', {class: 'alert bad small', role: 'alert', hidden: true});
    let busy = false;
    const key = `lc:${path}:${label}`;
    const button = btn(label, save, cls, disabled);
    button.setAttribute('data-lc-key', key);
    /** The keyboard goes back to the button it was on: the card is drawn again after a download (``onDone``), and a disabled button gives
        the focus up while the file is made. The new button when there is one, the card's heading when the button is gone or off. */
    function keepKeyboard() {
      const again = [...document.body.querySelectorAll('[data-lc-key]')].find((e) => e.getAttribute('data-lc-key') === key && !e.disabled);
      if (again) { again.focus(); return; }
      const card = document.body.querySelector('.lc-export'), heading = card && card.querySelector('h4');
      if (heading) { heading.setAttribute('tabindex', '-1'); heading.focus(); }
    }
    async function save() {
      if (busy) return;
      const had = document.activeElement === button;
      busy = true; button.disabled = true; button.setAttribute('aria-busy', 'true'); failure.hidden = true;
      try {
        await download(path, name);
        if (note) App.toast(note, 'ok');
        if (onDone) await onDone();
      } catch (e) {
        App.fail(e);
        fill(failure, `File not received: ${e.message}`, ' ', btn('Retry', save, 'btn-small'));
        failure.hidden = false;
      } finally { busy = false; button.disabled = disabled; button.removeAttribute('aria-busy'); if (had) keepKeyboard(); }
    }
    return {el: h('span', {class: 'lc-download'}, button, failure), button, failure};
  }

  // -- the chain ------------------------------------------------------------------------------------------------------------------------
  /** Show the four file stages and the next action. */
  function chain(lc, {id = 'lc-chain', onAction = null} = {}) {
    if (!lc) return null;
    const c = lc.chain;
    const items = c.steps.map((s, i) => h('li', {class: `lc-step lc-${s.state}`, 'aria-current': s.state === 'current' ? 'step' : null},
      h('span', {class: 'lc-mark', 'aria-hidden': 'true'}, s.state === 'done' ? '✓' : String(i + 1)), h('span', {class: 'lc-name'}, STAGE_NAME[s.id]),
      h('span', {class: 'lc-word'}, ` (${STATE_WORD[s.state]})`)));
    const hint = nextText(lc), act = action(lc, onAction);
    return h('div', {class: 'lc', id}, h('ol', {class: 'lc-chain', 'aria-label': 'Work file lifecycle'}, items),
      hint ? h('p', {class: 'lc-next small'}, h('span', {class: 'lc-hint'}, hint), act ? [' ', act] : null) : act);
  }

  const ACTION_LABEL = {download: 'Go to file', fix: 'What to fix', compare: 'Compare with expected'};
  /** Show the current stage action as a link or callback button. */
  function action(lc, onAction) {
    const a = lc.chain.next;
    if (a.code === 'add_result') return link(`/ingest?plan=${lc.plan_id}`, 'Add result');
    if (a.code === 'check_result') return link(`/ingest?pair=${a.pair_id}`, 'Review and accept result');
    if (!onAction) return a.code === 'compare' ? link(`/analysis/${a.pair_id}`, 'Open analysis') : null;
    return btn(ACTION_LABEL[a.code], () => onAction(a), 'btn-small');
  }

  /** Describe the next action in plain language. */
  function nextText(lc) {
    const c = lc.chain, a = c.next;
    const lead = c.edited_after != null ? `The work changed after file ${fileLabel(c.edited_after)}. The earlier file remains in history; this version needs a new file. ` : '';
    const loose = c.unlinked ? ` Results without a file: ${c.unlinked}; these were photographed before a file was recorded.` : '';
    if (a.code === 'download') return lead + 'Download the file and open it in LightBurn.' + loose;
    if (a.code === 'fix') return lead + 'The file cannot be created yet. See what to fix below.' + loose;
    if (a.code === 'add_result') return `File ${fileLabel(c.file)} downloaded. After engraving, add the result: the file and a photograph.` + loose;
    if (a.code === 'check_result') return 'The result was added but not accepted. Review and accept the measurements.' + loose;
    if (a.code === 'compare') return 'The result has been reviewed. Compare it with the expected result.' + loose;
    return null;
  }
  const fileLabel = (n) => (n ? `#${n}` : '(before MarkView recorded exports)');

  // -- readiness ------------------------------------------------------------------------------------------------------------------------
  /** Describe a server-provided reason why the file cannot be created. */
  function blockerText(b) {
    switch (b.code) {
      case 'weak_regions': return `Regions without sufficient data: ${b.count}. Remove or exclude the region, select its group settings, or send its color to the planner.`;
      case 'nothing_to_engrave': return 'Nothing to engrave: all regions are excluded.';
      case 'too_many_layers': return `LightBurn layers required: ${b.count}; available: ${b.cap}. Merge colors or zones.`;
      case 'no_palette': return 'No measured color is available for this laser, lens, and titanium. Measure colors or select another blank.';
      case 'missing_colours': return `The titanium color for ${b.count} regions is no longer measured for this laser, lens, and titanium. Select another color.`;
      case 'text': return `Inscription ${b.number} cannot be engraved: ${I18N.tr(b.problem)}. Open it and fix the issue.`;
      case 'zone': return `Photo zone ${b.number} cannot be engraved: ${I18N.tr(b.problem)}.`;
      case 'draft': return 'The plan is a draft. Complete conversion to enable export.';
      case 'closed': return 'This plate was replaced or canceled. Open the current research plate.';
      case 'no_layers': return 'There are no layers to export.';
      case 'restored': return 'This is a record of a completed task, so the file cannot be exported.';
      default: return 'The file cannot be created yet.';
    }
  }
  const TARGET_LABEL = {region: 'Show region', tab: 'Open Colors tab'};
  const MISSING_DATA = ['no_palette', 'missing_colours', 'weak_regions'];

  /** Render file readiness and its related actions. */
  function readiness(lc, {onTarget = null, designer = null} = {}) {
    const r = lc.readiness;
    const time = r.seconds == null ? 'time cannot be estimated' : `≈ ${duration(r.seconds)}${r.time_complete ? '' : ' (incomplete estimate)'}`;
    const facts = [mm(r.size_mm), time, r.layers == null ? null : `${r.layers} of ${r.layer_cap} layers`].filter(Boolean).join(' · ');
    const checks = [`colors ${r.checks.colours ? 'reachable' : 'some unreachable'}`, `layers ${r.checks.layers.used} of ${r.checks.layers.cap}`,
      r.kind === 'plain' ? null : `C00 cleaning ${r.checks.cleanup ? 'present' : 'absent'}`, `markers ${r.checks.markers ? 'on' : 'off'}`].filter(Boolean).join(' · ');
    const rows = r.blockers.map((b) => h('li', {class: 'lc-blocker'}, h('span', {}, blockerText(b)), ' ',
      onTarget && b.target && TARGET_LABEL[b.target.kind] ? btn(TARGET_LABEL[b.target.kind], () => onTarget(b), 'btn-small') : null,
      designer && MISSING_DATA.includes(b.code) ? [' ', link(designer, 'Experiment goals')] : null));
    return h('div', {class: 'stack lc-ready'}, h('p', {}, h('strong', {}, 'LightBurn file: '), r.ready ? pill('ready to export', 'ok') : pill('not ready', 'bad'), ' ', facts),
      h('p', {class: 'muted small'}, 'Checks: ' + checks), rows.length ? h('ul', {class: 'lc-blockers alert warn', role: 'status'}, rows) : null,
      r.reason ? h('details', {class: 'small'}, h('summary', {}, 'Exact check details'), h('p', {}, I18N.tr(r.reason))) : null);
  }

  // -- files ----------------------------------------------------------------------------------------------------------------------------
  const PROMISE = {saved: 'prediction saved with file', none: 'prediction not saved with file'};

  /** Render file readiness and its related actions. */
  function files(lc, {onDone = null} = {}) {
    if (!lc.files.length) return h('p', {class: 'muted small'}, 'No file has been created yet.');
    const rows = lc.files.map((f) => {
      const results = f.results.map((r) => h('li', {}, r.photo_name, ' · ', r.status === 'Accepted' ? 'accepted' : 'awaiting review', ' · ',
        link(r.status === 'Accepted' ? `/analysis/${r.pair_id}` : `/ingest?pair=${r.pair_id}`, r.status === 'Accepted' ? 'analysis' : 'review and accept'),
        r.linked_by === 'time' ? h('span', {class: 'muted'}, ' · linked by time') : null));
      return h('li', {class: 'lc-file'}, h('div', {class: 'vw-line'}, h('span', {}, h('strong', {}, `File ${fileLabel(f.number)}`), f.name ? ` · ${f.name}` : '',
        h('div', {class: 'muted small'}, [f.recorded ? when(f.at) : 'date unknown', f.layers == null ? null : `${f.layers} layers`, f.regions == null ? null : `${f.regions} regions`,
          f.seconds == null ? null : duration(f.seconds), PROMISE[f.promise], f.current ? 'current for work' : 'work has since changed or been exported again'].filter(Boolean).join(' · '))),
        h('span', {class: 'row'}, pill(STAGE_NAME[f.stage], f.stage === 'verified' ? 'ok' : ''),
          f.download_url ? downloadButton(f.download_url.replace(/^\/api/, ''), f.name, 'Download', {cls: 'btn-small', disabled: !f.downloadable, onDone}).el
            : h('span', {class: 'muted small'}, 'file not retained'))),
        results.length ? h('ul', {class: 'lc-results small'}, results) : null);
    });
    const loose = lc.unlinked.map((r) => h('li', {}, `${r.photo_name} · ${r.status === 'Accepted' ? 'accepted' : 'awaiting review'} · photographed before the first file record `,
      link(r.status === 'Accepted' ? `/analysis/${r.pair_id}` : `/ingest?pair=${r.pair_id}`, r.status === 'Accepted' ? 'analysis' : 'review and accept')));
    return h('div', {class: 'stack'}, h('ul', {class: 'lc-files'}, rows),
      loose.length ? h('div', {}, h('h4', {}, 'Results without a file'), h('ul', {class: 'small'}, loose)) : null);
  }

  /** Render file readiness and its related actions. */
  function exportCard(lc, {path, name, reload = null, recipe = null, recipeLabel = 'Full recipe and layers', onTarget = null, designer = null, heading = 'LightBurn file',
                         withChain = true} = {}) {
    const r = lc.readiness;
    const got = downloadButton(path, name, 'Download LightBurn', {cls: 'primary', disabled: !r.ready, onDone: reload,
      note: 'File created, saved in the work, and downloaded to this computer. Open it in LightBurn and check the layers'});
    return h('div', {class: 'stack lc-export'}, h('h4', {}, heading), withChain ? chain(lc) : null, readiness(lc, {onTarget, designer}),
      h('div', {class: 'row'}, got.el),
      h('p', {class: 'muted small'}, 'The file downloads to this computer. Open and run it in LightBurn when ready.'),
      recipe ? h('details', {class: 'vw-details'}, h('summary', {}, recipeLabel), recipe) : null,
      h('details', {class: 'vw-details'}, h('summary', {}, `Previous files${lc.files.length ? ` (${lc.files.length})` : ''}`), files(lc, {onDone: reload})));
  }

  // -- the strip under a work's head ------------------------------------------------------------------------------------------------------------
  /** Collapse lifecycle, forecast, and preview details on narrow screens. */
  function strip({chain, forecast, preview}, {query = '(max-width:600px)'} = {}) {
    const line = h('span', {class: 'lc-strip-line small'});
    const sum = h('summary', {class: 'lc-strip-sum'}, h('strong', {}, 'File lifecycle and prediction'), line);
    const box = h('details', {class: 'lc-strip'}, sum, chain, forecast, preview);
    const text = (root, selector) => { const e = root.querySelector(selector); return e ? e.textContent.trim() : ''; };
    const narrow = typeof matchMedia === 'function' ? matchMedia(query) : null;
    const fit = () => { box.open = !(narrow && narrow.matches); };       // wide: nothing is folded; narrow: folded until it is opened
    fit();
    if (narrow && narrow.addEventListener) narrow.addEventListener('change', fit);
    function sync() {
      const step = chain.querySelector('[aria-current]'), level = text(forecast, '.pill'), caution = preview.classList.contains('alert');
      const parts = [step ? `current: ${text(step, '.lc-name')}` : '', level ? `prediction: ${level}` : '', caution ? 'preview has a caveat' : ''].filter(Boolean);
      fill(line, parts.length ? parts.join(' · ') : 'no file lifecycle data');
      if (caution || forecast.querySelector('.alert')) sum.setAttribute('data-caution', 'true'); else sum.removeAttribute('data-caution');
    }
    sync();
    return {el: box, sync};
  }

  // -- the basis of a comparison ------------------------------------------------------------------------------------------------------------
  /** Describe the comparison basis without presenting reconstruction as the file’s original prediction. */
  function basisNote(basis) {
    const n = basis.export_number, date = basis.exported_at ? ` (exported ${when(basis.exported_at)})` : '';
    const tie = (basis.ambiguous || []).length ? ` Layers in files ${[...basis.ambiguous, n].sort((a, b) => a - b).map((x) => '#' + x).join(', ')} match the engraving equally; file #${n} was chosen as the latest before the photograph.` : '';
    if (basis.kind === 'saved') return `Basis: prediction saved with file #${n}${date}. This is what the file itself predicted.${tie}`;
    if (basis.kind === 'reconstructed' && n) return `Basis: reconstruction. No prediction was saved with file #${n}${date}; colors were reconstructed from the work layers as currently recorded. This is not the file’s original prediction.`;
    if (basis.kind === 'reconstructed') return 'Basis: reconstruction. The work has not been exported, so the engraving is compared with its current layer colors. This is not a file prediction.';
    return `Basis: none. No prediction was saved for file${n ? ' #' + n : ''}, and the work was recolored or split since then, so no comparison is available. Only colors measured from the photo are shown below.`;
  }

  // -- the return to the work -------------------------------------------------------------------------------------------------------------
  /** Summarize an accepted result and changes to the current prediction. */
  function summary(s, {onNext = null, onClose = null} = {}) {
    const res = s.result, p = s.prediction;
    const line = res.matched == null ? 'Layers were not matched to the file.' : `Matched layers: ${res.matched} of ${res.promised}`
      + (res.beyond_layers ? `, noticeably different (${res.beyond_layers})` : ', no noticeable differences')
      + (res.mean_delta_e == null ? '' : `, mean ΔE ${num(res.mean_delta_e, 1)}`) + '.';
    const move = !p.known ? 'Changes to the current work prediction were not recorded for this result.'
      : p.after == null ? 'The work has no file against which to calculate color drift, so the prediction cannot be compared.'
      : `Current work prediction: ${p.after.layers} layer colors shifted since the file`
        + (p.before == null ? '' : ` (was ${p.before.layers})`) + (p.after.proposals ? `; closer color replacements available: ${p.after.proposals}` : '') + '. File #' + (s.export_number ?? '—') + ' is unchanged.';
    return h('section', {class: 'card stack lc-summary', role: 'status', 'aria-label': 'Accepted result summary'}, h('h3', {}, `Result accepted: “${s.work}”`),
      h('p', {class: 'small'}, basisNote(s.basis)), h('p', {class: 'small'}, line), h('p', {class: 'small'}, move),
      onNext || onClose ? h('div', {class: 'row'}, onNext ? btn(s.next === 'replace' ? 'View color replacements' : 'Compare with expected', () => onNext(s.next), 'primary') : null,
        onClose ? btn('Close summary', onClose) : null) : null);
  }

  /** Return to the associated vector work after accepting a result. */
  function returnToWork(concluded) {
    if (!concluded || !concluded.summary) return false;
    const s = concluded.summary;
    App.toast(`Result accepted. Returning to “${s.work}”: ${concluded.review.summary.beyond_layers ? 'noticeable differences found' : 'no noticeable differences'}`, 'ok');
    App.go(s.route);
    return true;
  }

  return {STAGES, STAGE_NAME, download, downloadButton, chain, strip, readiness, files, exportCard, basisNote, summary, returnToWork, blockerText, nextText};
})();
