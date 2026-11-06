/* The review of a pair as four stages: Files → Alignment → Review → Acceptance (ux-photo-review-p0: REQ-001, REQ-002, DEC-001).

   What the screen shows is what the server derived (``pair.review``, src/titanium_platform/pair_review.py): the stage to work on, the
   blocking conditions (exactly those ``accept_pair`` refuses on) with the tools that resolve them, and the advisory notes. This file
   draws it: a stage bar, a header per stage (completeness, blockers, notes, exactly one primary action), and the row of manual tools
   that is on the screen at every stage whether or not automation warned (DEC-001).

   The panels of the stages and the regions of the tools are built once by the caller and only shown or hidden here, so what an operator
   typed into one survives a visit to another stage. Nothing here decides whether a pair may be accepted: the accept button is enabled
   only while the server says ``acceptable``, and is disabled while a re-check is running. */
'use strict';
const IngestStages = (() => {
  const {h, fill, btn, pill} = App;

  const STAGES = [['files', 'Files'], ['alignment', 'Alignment'], ['review', 'Review'], ['accept', 'Acceptance']];
  const KEYS = STAGES.map(([key]) => key);
  const NAME = Object.fromEntries(STAGES);
  const HINT = {
    files: 'The LightBurn file and photograph are readable, the file matches the plate definition, and layer settings are known.',
    alignment: 'File outlines align with the photograph. Adjust alignment manually if automatic alignment failed or is uncertain.',
    review: 'Review the photograph, outlines and short summary. Check that outlines cover the correct details; metrics and layers are collapsed.',
    accept: 'Accepted observations are immutable and enter the laser’s knowledge. Review exactly what will be recorded and its source.',
  };
  const MANUAL = ['corners', 'anchor', 'shift', 'matrix', 'layers', 'tasks'];
  const TOOLS = {corners: 'Work corners', anchor: 'Align by detail', shift: 'Move and rotate layout', matrix: 'Parameter matrix',
    layers: 'File layers', tasks: 'Engraving tasks'};
  const CONTEXT = {check: 'Review pair', restart: 'Find again using RAW and LightBurn', file: 'Correct pair',
    file_confirm: 'Confirm the file used', supplied: 'Enter missing settings', masks: 'Review layer masks'};

  // What stands in the way of acceptance, said for the operator; the codes are those of pair_review.py. The server's own sentence (if it
  // has one) is printed under it, translated, so nothing the check said is lost.
  const BLOCKER = {
    not_checked: 'The pair has not been reviewed: the photograph is not aligned with the file and layers are not measured.',
    file_unreadable: 'The LightBurn file cannot be read.',
    photo_unreadable: 'The photograph could not be read.',
    identifier_unknown: 'The experiment identifier on the plate is unknown to this system.',
    identifier_deleted: 'The identifier on the plate belongs to a deleted experiment.',
    other_laser: 'The plate was made for a different laser than the one selected for the pair.',
    matrix_incomplete: 'The matrix settings were not fully read.',
    matrix_pulse_width: 'The matrix pulse duration is outside this laser’s range.',
    matrix_unconfirmed: 'The matrix settings have not been confirmed.',
    no_chart: 'The calibration chart in the photograph has not been confirmed.',
    no_colour_basis: 'The photograph has no basis for color measurement.',
    plate_cells_missing: 'No plate cells were found in the LightBurn file.',
    file_unconfirmed: 'The file differs from the plate definition. Correct the pair or confirm that this exact file was used for engraving.',
    alignment_lost: 'The alignment adjustment lost too many detected details.',
    alignment_failed: 'The photograph is not aligned with the file.',
    masks_unreviewed: 'Layer masks have not been reviewed on this photograph.',
    no_measured_layer: 'No readable, comparable layer was measured.',
    not_ready: 'The pair is not ready to accept.',
  };
  const advisoryText = (a) => {
    const names = (a.names || []).map((n) => I18N.name(n)).join(', ');
    const more = a.count > (a.names || []).length ? ' and others' : '';
    switch (a.code) {
      case 'layers_skipped': return `Unmeasured layers: ${a.count} (${names}${more}).`;
      case 'layers_incomparable': return `Layers with non-comparable settings, excluded from the model: ${a.count} (${names}${more}).`;
      case 'settings_missing': return `Settings are missing from the file for ${a.count} layers (${names}${more}). You can enter them manually.`;
      case 'qr_offset': return 'The QR code is offset from the main matrix in the photograph; its outline and measurement were adjusted separately.';
      default: return a.detail ? I18N.tr(a.detail) : 'The review reported a note.';
    }
  };

  const toolName = (key) => TOOLS[key] || CONTEXT[key] || key;
  const stateText = (state, count) => (state === 'done' ? 'done' : state === 'current'
    ? (count ? `needs resolution: ${count}` : 'current') : count ? `upcoming, issues: ${count}` : 'upcoming');

  /** The stage bar. ``onSelect`` null draws it for reading only (the upload pages, an accepted pair). */
  function bar(stages, {shown = null, onSelect = null} = {}) {
    const items = stages.map(({key, state, blockers}, i) => {
      const body = [h('span', {class: 'rv-num', 'aria-hidden': 'true'}, String(i + 1)), h('span', {class: 'rv-name'}, NAME[key]),
        h('span', {class: 'rv-state'}, stateText(state, (blockers || []).length))];
      const attrs = {class: `rv-step ${state}${key === shown ? ' shown' : ''}`, 'aria-current': key === shown ? 'step' : null};
      return h('li', {}, onSelect
        ? h('button', {type: 'button', ...attrs, 'aria-controls': `rv-panel-${key}`, onClick: () => onSelect(key)}, body)
        : h('span', {...attrs, tabindex: null}, body));
    });
    return h('nav', {'aria-label': 'Review stages'}, h('ol', {class: 'rv-steps'}, items));
  }

  /** The stage bar of the pages that come before a review (a new pair, a re-photograph): the files stage is the one in progress. */
  const upload = () => bar(KEYS.map((key) => ({key, state: key === 'files' ? 'current' : 'todo', blockers: []})), {shown: 'files'});

  /** What invalidates a review, said to the operator (the same list as ``INVALIDATED_BY`` in pair_review.py). */
  const invalidation = () => h('details', {class: 'rv-note'}, h('summary', {}, 'What resets mask review'),
    h('p', {class: 'muted small'}, 'Mask review applies to a specific measurement result. It resets if you replace the LightBurn file, '
      + 'recalculate alignment (corners, detail alignment, layout movement, Find again or recheck), add or remove a layer setting, '
      + 'or correct the parameter matrix. If plate discrepancies differ after recheck, file confirmation is also cleared. '
      + 'Choosing an engraving task and confirming the file do not reset mask review. An accepted pair is immutable; an alignment correction creates a new pair.'));

  /** The review screen. ``panels`` {stage: [nodes]}, ``regions`` {tool: {el} | {build}}, ``actions`` the things the stages do
      (check, restart, file, file_confirm, supplied, masks, reviewMasks, accept), ``state`` {checked, ready, masksReviewed}, ``status`` a
      line the caller keeps under the header (the progress of a re-check), ``open`` the tools to show from the start. */
  function shell({review, panels, regions, actions, state, status = null, open = []}) {
    let shown = KEYS.includes(review.stage) ? review.stage : 'accept', busy = false;
    const barHost = h('div'), headHost = h('div'), announce = h('p', {class: 'rv-sr', role: 'status', 'aria-live': 'polite'});
    const wrappers = {}, filled = {}, buttons = {};

    const panelEls = Object.fromEntries(KEYS.map((key) => [key, h('section', {class: 'stack rv-panel', id: `rv-panel-${key}`,
      'aria-label': NAME[key], hidden: key !== shown}, ...(panels[key] || []))]));

    const fillRegion = (key) => {
      if (filled[key]) return;
      filled[key] = true;
      wrappers[key].append(regions[key].el || regions[key].build());
    };
    const setOpen = (key, on) => {
      if (on) fillRegion(key);
      wrappers[key].hidden = !on;
      buttons[key].setAttribute('aria-expanded', String(on));
      buttons[key].classList.toggle('on', on);
    };
    const openTool = (key) => {
      setOpen(key, true);
      wrappers[key].focus();
      if (wrappers[key].scrollIntoView) wrappers[key].scrollIntoView({block: 'nearest'});
    };
    const toggleTool = (key) => { if (wrappers[key].hidden) openTool(key); else setOpen(key, false); };

    const toolsBar = h('nav', {class: 'rv-tools', 'aria-label': 'Manual tools'},
      h('span', {class: 'muted small'}, 'Manual tools:'),
      ...MANUAL.map((key) => (buttons[key] = h('button', {type: 'button', class: 'btn rv-tool', 'aria-expanded': 'false',
        'aria-controls': `rv-region-${key}`, onClick: () => toggleTool(key)}, TOOLS[key]))));
    const regionsHost = h('div', {class: 'stack rv-regions'}, ...MANUAL.map((key) => (wrappers[key] = h('div', {class: 'rv-region',
      id: `rv-region-${key}`, tabindex: '-1', role: 'region', 'aria-label': TOOLS[key], hidden: true}))));
    for (const key of MANUAL) if (regions[key] && regions[key].el) fillRegion(key);          // inputs exist from the start, hidden
    for (const key of open) if (regions[key]) setOpen(key, true);

    const has = (stage) => review.blockers.some((b) => b.stage === stage);
    const use = (key) => (MANUAL.includes(key) ? openTool(key) : actions[key] && actions[key]());
    const toolButton = (key) => h('button', {type: 'button', class: 'btn btn-small', onClick: () => use(key)}, toolName(key));

    const primary = () => {
      if (shown === 'files' && !state.checked) return {label: 'Review pair', run: actions.check};
      if (shown === 'files') return {label: 'Next: alignment', run: () => show('alignment'), disabled: has('files')};
      if (shown === 'alignment') return {label: 'Next: review', run: () => show('review'), disabled: has('files') || has('alignment')};
      if (shown === 'review' && state.masksReviewed) return {label: 'Next: acceptance', run: () => show('accept'), disabled: KEYS.slice(0, 3).some(has)};
      if (shown === 'review') return {label: 'Masks reviewed: outlines cover the correct details', run: actions.reviewMasks, disabled: !state.ready};
      return {label: 'Accept observations', run: actions.accept, disabled: !review.acceptable};
    };

    const blockerRow = (b) => {
      const known = BLOCKER[b.code];
      return h('li', {class: 'rv-blocker'},
        h('div', {class: 'rv-what'}, h('strong', {}, known || (b.detail ? I18N.tr(b.detail) : 'The review found a problem.')),
          known && b.detail ? h('span', {class: 'muted small'}, I18N.tr(b.detail)) : null,
          shown === 'accept' ? h('span', {class: 'muted small'}, `Stage: ${NAME[b.stage]}`) : null),
        h('div', {class: 'rv-fix'}, ...b.tools.map((key) => h('button', {type: 'button', class: 'btn btn-small',
          onClick: () => { if (b.stage !== shown && !MANUAL.includes(key)) show(b.stage); use(key); }}, toolName(key)))));
    };
    const advisoryRow = (a) => h('li', {class: 'rv-advisory'}, h('div', {class: 'rv-what'}, advisoryText(a)),
      h('div', {class: 'rv-fix'}, ...a.tools.map((key) => toolButton(key))));

    function drawHead() {
      const at = KEYS.indexOf(shown), here = review.blockers.filter((b) => shown === 'accept' || b.stage === shown);
      const earlier = shown === 'accept' ? [] : [...new Set(review.blockers.filter((b) => KEYS.indexOf(b.stage) < at).map((b) => b.stage))];
      const done = review.stages.filter((s) => s.state === 'done').length;
      const act = primary(), off = act.disabled || busy;
      const reason = busy ? 'Recalculation is in progress; wait until it finishes.' : act.disabled && here.length ? 'Available once the issues above are resolved.'
        : act.disabled ? 'First resolve the issue in the earlier stage.' : null;
      const notes = review.advisories || [];
      fill(headHost, h('section', {class: 'card stack rv-head', 'aria-labelledby': 'rv-head-title'},
        h('div', {class: 'row'}, h('h3', {id: 'rv-head-title'}, `Stage ${at + 1} of ${KEYS.length}: ${NAME[shown]}`), h('span', {class: 'spacer'}),
          pill(`stages complete: ${done} of ${KEYS.length}`, done === KEYS.length ? 'ok' : '')),
        h('p', {class: 'muted small'}, HINT[shown]),
        here.length ? h('div', {class: 'stack'}, h('strong', {}, 'What prevents acceptance'), h('ul', {class: 'rv-list'}, here.map(blockerRow)))
          : h('div', {class: 'alert ok', role: 'status'}, shown === 'accept' ? 'Everything is reviewed; observations can be accepted.' : 'Nothing in this stage prevents acceptance.'),
        earlier.length ? h('div', {class: 'alert warn', role: 'status'}, 'An earlier stage has unresolved issues: ',
          earlier.map((key, i) => [i ? ', ' : '', h('button', {type: 'button', class: 'btn btn-small', onClick: () => show(key)}, NAME[key])])) : null,
        notes.length ? h('div', {class: 'stack'}, h('strong', {}, 'Items to review'),
          h('ul', {class: 'rv-list'}, notes.slice(0, 4).map(advisoryRow)),
          notes.length > 4 ? h('details', {}, h('summary', {}, `${notes.length - 4} more`), h('ul', {class: 'rv-list'}, notes.slice(4).map(advisoryRow))) : null) : null,
        h('div', {class: 'row'}, btn(act.label, (ev) => { const self = ev.currentTarget; act.run(self); }, 'primary', off), reason ? h('span', {class: 'muted small'}, reason) : null)));
    }

    function show(stage) {
      shown = stage;
      for (const key of KEYS) panelEls[key].hidden = key !== stage;
      fill(barHost, bar(review.stages, {shown, onSelect: show}));
      drawHead();
      const count = review.blockers.filter((b) => stage === 'accept' || b.stage === stage).length;
      announce.textContent = `Stage ${KEYS.indexOf(stage) + 1} of ${KEYS.length}: ${NAME[stage]}. ${count
        ? `Unresolved issues: ${count}.` : 'No issues in this stage.'}`;
    }
    show(shown);

    const el = h('div', {class: 'stack rv'}, barHost, announce, headHost, status, toolsBar, regionsHost, ...KEYS.map((key) => panelEls[key]));
    return {el, show, open: openTool, stage: () => shown, setBusy(on) { busy = on; drawHead(); },
      focusPrimary() { const first = headHost.querySelector('button.primary'); if (first) first.focus(); }};
  }

  return {shell, bar, upload, invalidation, KEYS, MANUAL, CONTEXT, TOOLS, BLOCKER};
})();
