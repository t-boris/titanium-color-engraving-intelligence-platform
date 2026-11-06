/* Guided work creation, draft recovery, readiness, and photo engraving selection. */
'use strict';
const Creation = (() => {
  const {h, fill, btn, field, link, pill, get, post, put, del, form, toast, fail, go} = App;

  // -- the four results -----------------------------------------------------------------------------------------------------------------
  const RESULTS = [
    {id: 'colour', title: 'Color regions', strategy: 'photo', work: 'vector',
      about: 'The image is split into smooth color regions, each assigned a measured titanium color.',
      file: 'LightBurn file: one layer for each fill color used.', needs: 'Requires measured fill colors for this laser, lens, and titanium.'},
    {id: 'photo', title: 'Photo engraving', strategy: null, work: 'photo',
      about: 'The image remains continuous tone; each point’s brightness sets power on a measured scale.',
      file: 'LightBurn file: an image layer with its own scale.', needs: 'Requires a measured grayscale scale for this laser, lens, and titanium.'},
    {id: 'silhouette', title: 'Silhouette', strategy: 'fill', work: 'vector',
      about: 'The dark image shape is filled with one recipe.',
      file: 'LightBurn file: a fill layer.', needs: 'Requires a verified fill recipe.'},
    {id: 'lines', title: 'Lines', strategy: 'line', work: 'vector',
      about: 'Dark image strokes become lines along their centers.',
      file: 'LightBurn file: line layers (Line mode).', needs: 'Requires a verified line recipe.'}];
  const RESULT = Object.fromEntries(RESULTS.map((r) => [r.id, r]));
  const STEPS = [['picture', 'Image and size'], ['result', 'Choose a result'], ['method', 'Settings and creation']];
  const FACTS = {colour: (f) => `regions: ${f.areas} · colors: ${f.colours}`, photo: (f) => `grayscale levels in image: ${f.levels}`,
    silhouette: (f) => `regions: ${f.areas}`, lines: (f) => `lines: ${f.strokes}`};
  const DEFAULT_WIDTH = '60';                                         // a starting value in the field, the same as the vector form's
  const FLOW = 'new';
  const AUTOSAVE_MS = 500;
  const MISSING = {
    laser: ['No laser has been added.', '/devices', 'Add laser'],
    titanium: ['No titanium blank has been added.', '/setup', 'Add blank'],
    lens: ['The selected laser has no lens; the test requires one.', '/devices', 'Install lens'],
  };
  const BECOMES = {measured_scale: 'Once the test measurements are accepted, a measured grayscale scale will become available for photo engraving.',
    validated_recipes: 'Accepted test measurements are added to the measured colors for this laser, lens, and titanium. A recipe can be used in work once it is '
      + 'verified by repeats under the laser’s rules, so the test may need repeating.'};

  const url = ({result = null, draft = null} = {}) => {
    const query = [draft ? `draft=${draft}` : null, result ? `result=${result}` : null].filter(Boolean);
    return '/new' + (query.length ? '?' + query.join('&') : '');
  };
  /** The one way to start a work from anywhere (the works list, a menu, an empty state): ``result`` preselects a result, ``draft`` resumes a task. */
  const start = (options = {}) => go(url(options));

  const baseName = (file) => String(file || '').replace(/\.[^.]+$/, '');
  const numberOf = (text) => (String(text).trim() === '' ? NaN : +text);
  const lensField = (context) => (context.lens_id == null ? 'unknown' : String(context.lens_id));

  // -- the bar of an unfinished task, on every screen --------------------------------------------------------------------------------------
  const bar = h('aside', {id: 'creation-bar', class: 'alert warn creation-bar', 'aria-label': 'Unfinished work', hidden: true});
  let barToken = 0;
  const onWizard = () => /^#\/(new|vector\?(.*&)?new=)/.test(String((typeof location === 'object' && location.hash) || '')) && !/[?&]classic=/.test(location.hash);
  // the bar is fixed over the lower edge of the window and its height changes with the width and the text size: the page keeps that much free below
  // and the browser keeps what has the keyboard above it (--creation-bar-h, read by the stylesheet), not under the bar
  const barHeight = typeof ResizeObserver === 'function' ? new ResizeObserver(() => document.documentElement.style.setProperty('--creation-bar-h', bar.offsetHeight + 'px')) : null;
  const padPage = (on) => {
    if (document.body && document.body.classList) document.body.classList.toggle('has-creation-bar', on);
    if (barHeight) { if (on) barHeight.observe(bar); else barHeight.disconnect(); }
  };

  async function waitingText(draft) {
    const waiting = draft.state && draft.state.waiting;
    if (!waiting || !waiting.result) return 'You can continue.';
    try {
      const r = await get(`/creation/readiness?result=${waiting.result}`);
      return r.ready ? 'The missing prerequisites are available; you can continue.' : waiting.for === 'starter_test' ? 'Waiting for the starter test and acceptance of its measurements.' : 'Waiting for equipment setup.';
    } catch (_) { return 'You can continue.'; }
  }

  /** Redraws the bar: the newest open task with “Continue” and “Cancel task”. It is hidden on the creation screen itself and when no task is open. */
  async function refreshBar() {
    const mine = ++barToken;
    let drafts = [];
    try { drafts = await get('/creation/drafts'); } catch (_) { drafts = []; }
    if (mine !== barToken) return;
    if (!drafts.length || onWizard()) { bar.hidden = true; fill(bar); padPage(false); return; }
    const draft = drafts[0];
    const note = await waitingText(draft);
    if (mine !== barToken) return;
    fill(bar, h('div', {class: 'row'}, h('strong', {}, `Unfinished work “${draft.name || (draft.image && baseName(draft.image.name)) || 'untitled'}”.`),
      h('span', {class: 'small'}, drafts.length > 1 ? `${note} Total unfinished: ${drafts.length}.` : note), h('span', {class: 'spacer'}),
      btn('Continue', () => start({draft: draft.id}), 'btn-small primary'), btn('Cancel task', () => discard(draft, refreshBar), 'btn-small')));
    bar.hidden = false;
    padPage(true);
  }

  function discard(draft, after) {
    return App.confirmBox(`Cancel task “${draft.name || 'untitled'}”?`,
      'The entered data and saved image will be deleted and the task cannot be restored. Created works are unaffected.', 'Cancel task', async () => {
        await post(`/creation/drafts/${draft.id}/discard`);
        toast('Task canceled', 'ok');
        if (after) await after();
      });
  }

  function mountBar() {
    const app = typeof document.getElementById === 'function' ? document.getElementById('app') : null;
    if (app && app.parentNode && typeof app.parentNode.insertBefore === 'function') app.parentNode.insertBefore(bar, app); else document.body.append(bar);
    if (typeof addEventListener === 'function') addEventListener('hashchange', () => refreshBar());
    refreshBar();
  }

  // -- the creation screen ------------------------------------------------------------------------------------------------------------------
  async function render(ctx) {
    const query = (ctx && ctx.query) || {};
    const [context, lists, drafts, plateTypes] = await Promise.all([get('/creation/context'), App.hardwareLists(), get('/creation/drafts'),
      get('/plate-types').catch(() => [])]);
    const S = {context, draft: null, step: 'picture', result: RESULT[query.result] ? query.result : null, waiting: null, uploaded: null, picture: 0,
      readiness: {}, rules: undefined, tiles: {}, busy: false, kind: null, hold: null};
    if (query.draft) {
      S.draft = drafts.find((d) => String(d.id) === String(query.draft)) || null;
      if (!S.draft) S.missingDraft = true;
    }
    const host = h('div', {class: 'stack'});
    const heading = (text) => h('h2', {tabindex: '-1'}, text);

    // inputs are made once and stay in the page's memory while the person goes back and forth: nothing typed is ever lost by a step
    const fileIn = h('input', {type: 'file', accept: 'image/*', 'aria-label': 'Image'});
    const filePicker = App.filePick(fileIn, 'Choose image');          // made once: going back to the first step shows the chosen file again
    const nameIn = h('input', {autocomplete: 'off', 'aria-label': 'Work name', placeholder: 'from file name'});
    const Q = Forms.QUANTITIES;
    const widthIn = Forms.numberInput(Q.workWidth, {value: DEFAULT_WIDTH});
    const M = {
      thr: Forms.numberInput(Q.deltaE, {placeholder: 'from rules'}),
      remember: h('input', {type: 'checkbox', checked: true}),
      tolerance: Forms.numberInput(Q.vectorTolerance, {value: '0.08'}),
      colours: Forms.numberInput(Q.photoColours, {value: 12}),
      detail: h('select', {'aria-label': 'Detail'}, [['coarse', 'Coarse'], ['medium', 'Medium'], ['fine', 'Fine']].map(([v, l]) => h('option', {value: v, selected: v === 'medium'}, l))),
      algorithm: VectorSplit.picker((S.draft && S.draft.state && S.draft.state.method && S.draft.state.method.algorithm) || 'slic'),
      faces: h('input', {type: 'checkbox', checked: true}),
      maxTime: Forms.numberInput(Q.maxTime, {placeholder: 'no limit'}),
      asShot: h('input', {type: 'checkbox'}),
      markers: h('input', {type: 'checkbox'}),
      clean: h('input', {type: 'checkbox', checked: true}),
      grey: Forms.numberInput(Q.greyThreshold, {placeholder: 'auto (Otsu)'}),
    };
    // a step's fields are read as the server reads them; a wrong box says why beside itself and keeps what was typed, a refusal of the server stands where the field it
    // names is. The boxes persist between the steps, the controllers are made again with each drawing of a step (ux-save-feedback-p0, REQ-003)
    let pictureForm = Forms.create(), methodForm = Forms.create();
    M.algorithm.hint.setAttribute('style', 'grid-column:1 / -1');
    const methodState = () => ({thr: M.thr.value, remember: M.remember.checked, tolerance: M.tolerance.value, colours: M.colours.value, detail: M.detail.value,
      algorithm: M.algorithm.select.value, faces: M.faces.checked, maxTime: M.maxTime.value, asShot: M.asShot.checked, markers: M.markers.checked, clean: M.clean.checked, grey: M.grey.value});
    const restoreMethod = (m) => {
      if (!m) return;
      for (const k of ['thr', 'tolerance', 'colours', 'maxTime', 'grey']) if (m[k] != null) M[k].value = m[k];
      for (const k of ['remember', 'faces', 'asShot', 'markers', 'clean']) if (m[k] != null) M[k].checked = !!m[k];
      if (m.detail) M.detail.value = m.detail;
      if (m.algorithm) M.algorithm.select.value = m.algorithm;
    };
    const stateOf = () => ({v: 1, step: S.step, result: S.result, name: nameIn.value, width_mm: widthIn.value, method: methodState(), waiting: S.waiting, kind: S.kind, hold: S.hold});
    if (S.draft) {
      const st = S.draft.state || {};
      nameIn.value = S.draft.name || st.name || '';
      if (st.width_mm != null) widthIn.value = st.width_mm;
      restoreMethod(st.method);
      S.result = RESULT[st.result] ? st.result : S.result;
      S.waiting = st.waiting || null;
      S.kind = typeof st.kind === 'string' ? st.kind : null;                    // the kind of photo engraving the person last marked
      S.hold = st.hold && st.hold.id != null ? st.hold : null;                  // a work made only to show the kinds, if the window was closed meanwhile
      S.step = STEPS.some(([id]) => id === st.step) ? st.step : 'picture';
      if (!S.draft.image) S.step = 'picture';                       // without its picture a task can only go on from the first step
      else if (S.step === 'method' && !S.result) S.step = 'result';
    }

    // -- saving: one write after another, each carrying the whole form, so the last one is the form as it is ----------------------------------
    const note = h('p', {class: 'small muted', role: 'status', hidden: true});
    const tell = (text) => { note.textContent = text || ''; note.hidden = !text; };
    let queue = Promise.resolve(), timer = null;
    const enqueue = (job) => { const run = queue.then(job); queue = run.catch(() => {}); return run; };
    const send = (extra = {}) => enqueue(async () => {
      const fd = new FormData();
      fd.append('state', JSON.stringify(stateOf()));
      fd.append('name', nameIn.value);
      if (extra.file) fd.append('picture', extra.file, extra.file.name);
      if (S.draft) S.draft = await App.api('PUT', `/creation/drafts/${S.draft.id}`, fd, true);
      else { fd.append('flow', FLOW); S.draft = await form('/creation/drafts', fd); }
      if (extra.file) { S.uploaded = extra.file; S.picture++; }
      return S.draft;
    });
    /** Saves the task when it exists (it is made when the picture is chosen); a failure is told, never thrown at the person's typing. */
    const autosave = () => {
      clearTimeout(timer);
      if (!S.draft) return;
      timer = setTimeout(() => { send().then(() => tell('')).catch((e) => tell(`Task not saved: ${e.message}`)); }, AUTOSAVE_MS);
    };
    const flush = async () => { clearTimeout(timer); if (S.draft) { try { await send(); tell(''); } catch (e) { tell(`Task not saved: ${e.message}`); } } };
    for (const el of [nameIn, widthIn, ...Object.values(M).filter((v) => v && v.nodeType)]) { el.addEventListener('input', autosave); el.addEventListener('change', autosave); }
    M.algorithm.select.addEventListener('change', autosave);
    fileIn.addEventListener('change', () => {
      const file = fileIn.files && fileIn.files[0];
      if (file && !nameIn.value.trim()) nameIn.value = baseName(file.name);
    });

    // -- the context ----------------------------------------------------------------------------------------------------------------------
    const strip = WorkContext.strip(S.context, {onChange: async (saved) => {
      S.context = saved; S.readiness = {}; S.rules = undefined; S.starter = null;
      if (S.step !== 'picture') await loadReadiness();
      if (S.step === 'method' && S.result !== 'photo') await loadRules();
      drawStep();
      strip.focus();                                                   // the redraw moved the button the dialog gave the focus back to
    }});

    // -- readiness of the four results, tiles of the picture ------------------------------------------------------------------------------
    let readyToken = 0;
    async function loadReadiness() {
      const mine = ++readyToken;
      const answers = await Promise.all(RESULTS.map((r) => get(`/creation/readiness?result=${r.id}`).then((a) => [r.id, a]).catch((e) => [r.id, {error: e.message}])));
      if (mine !== readyToken) return;                                    // another context was chosen meanwhile: this answer is for the one before
      S.readiness = Object.fromEntries(answers);
    }
    const tileViews = {};                                              // result id -> {node, update}: a tile is updated in place, so the keyboard stays where it is
    async function loadTile(r) {
      const key = `${S.draft.id}|${S.picture}|${widthIn.value}|${r.id}`;
      S.tiles[r.id] = {key, state: 'loading'};
      if (tileViews[r.id]) tileViews[r.id].update();
      try {
        const res = await fetch(`/api/creation/drafts/${S.draft.id}/preview/${r.id}.png?width_mm=${encodeURIComponent(widthIn.value)}`);
        if (!res.ok) {
          let raw = `Server error (${res.status})`;
          try { const d = await res.json(); raw = I18N.tr((d.detail || d).error || raw); } catch (_) { /* the status says it */ }
          throw new Error(raw);
        }
        let facts = {};
        try { facts = JSON.parse(res.headers.get('x-preview-facts') || '{}'); } catch (_) { facts = {}; }
        const blob = await res.blob();
        if (S.tiles[r.id] && S.tiles[r.id].key === key) S.tiles[r.id] = {key, state: 'ready', src: URL.createObjectURL(blob), facts};
      } catch (e) { if (S.tiles[r.id] && S.tiles[r.id].key === key) S.tiles[r.id] = {key, state: 'failed', error: e.message}; }
      if (tileViews[r.id]) tileViews[r.id].update();
    }
    const tileKey = (r) => `${S.draft.id}|${S.picture}|${widthIn.value}|${r.id}`;

    // -- rules: the delta E tolerance is never invented -----------------------------------------------------------------------------------------
    async function loadRules() {
      if (S.context.device_id == null) return;
      const asked = `${S.context.device_id}|${lensField(S.context)}`;
      let rules = null;
      try { rules = await get(`/rules?device_id=${S.context.device_id}&lens_id=${lensField(S.context)}`); } catch (_) { rules = null; }
      if (asked !== `${S.context.device_id}|${lensField(S.context)}`) return;
      S.rules = rules ? rules.delta_tolerance : undefined;              // a number, null when none is saved, undefined while not known
    }
    const toleranceHint = () => {
      const saved = S.rules, text = saved == null ? '' : String(+(+saved).toFixed(2));
      M.thr.setAttribute('placeholder', saved != null ? `from rules: ${text}` : saved === null ? 'enter a value' : 'from rules');
      M.thr.setAttribute('aria-invalid', saved === null && M.thr.value === '' ? 'true' : 'false');
      return saved != null ? `leave empty for ΔE ${text} from this laser and lens’s rules; an entered value applies only to this work`
        : saved === null ? 'No tolerance is saved for this laser and lens; enter one. The fastest color within tolerance is selected. ΔE 1 is barely noticeable, 2–3 is small, and 5 can still match two engravings of one recipe.'
          : 'leave empty to use the tolerance in this laser and lens’s rules';
    };
    M.thr.addEventListener('input', () => { if (S.step === 'method') toleranceHint(); });

    // -- the view -----------------------------------------------------------------------------------------------------------------------------
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const show = (text) => { error.textContent = text || ''; error.hidden = !text; };
    const stepList = () => h('ol', {class: 'creation-steps', 'aria-label': 'Work creation steps'}, STEPS.map(([id, label], i) =>
      h('li', {'aria-current': id === S.step ? 'step' : null, class: id === S.step ? 'is-current' : ''}, `${i + 1}. ${label}`)));
    const stepNumber = () => STEPS.findIndex(([id]) => id === S.step) + 1;
    const pictureSrc = () => (S.draft && S.draft.image ? `/api/creation/drafts/${S.draft.id}/picture?v=${S.picture}` : null);
    const chosenFile = () => (fileIn.files && fileIn.files[0]) || null;
    let focusNext = false;
    const focusHeading = () => { const el = host.querySelector('h2'); if (el && el.focus) el.focus(); };

    function pictureStep() {
      const saved = S.draft && S.draft.image;
      const shownName = filePicker.querySelector('.file-name');
      if (shownName && saved && !chosenFile()) shownName.textContent = `${saved.name} · saved in task`;      // the task keeps the picture: the person need not choose it again
      pictureForm = Forms.create();
      const imageField = pictureForm.add('image', 'Image', filePicker, {required: true, help: saved && !chosenFile() ? 'choose another to replace it' : 'PNG, JPEG, TIFF',
        read: () => (chosenFile() || (S.draft && S.draft.image) ? {ok: true, value: chosenFile()} : {ok: false, message: 'Choose an image (PNG, JPEG, TIFF)'})});
      const widthField = pictureForm.add('width', 'Width on titanium', widthIn, {quantity: 'workWidth', required: true, help: 'height follows the image proportions'});
      return h('div', {class: 'stack'},
        h('div', {class: 'card stack'}, h('div', {class: 'grid g2'}, imageField, field('Work name', nameIn), widthField), pictureForm.error,
          saved && pictureSrc() ? h('figure', {class: 'creation-picture'}, h('img', {src: pictureSrc(), alt: `Task image: ${saved.name}`}),
            h('figcaption', {class: 'muted small'}, 'Saved image')) : null),
        strip.el,
        error,
        h('p', {class: 'small muted'}, 'Need an inscription or a custom layer task? ', link('/vector?new=1&classic=1', 'Form with all strategies')),
        h('div', {class: 'row'}, btn('Next →', toResult, 'primary')));
    }

    function tileView(r) {
      const slot = h('span', {class: 'creation-tile-slot'}), status = h('span', {}), facts = h('span', {class: 'small muted'});
      const node = h('button', {type: 'button', role: 'radio', class: 'creation-tile', onClick: () => choose(r.id)},
        slot, h('strong', {}, r.title), h('span', {class: 'small'}, r.about), facts, h('span', {class: 'small muted'}, r.file), status);
      const update = () => {
        const t = S.tiles[r.id] || {state: 'loading'}, ready = S.readiness[r.id], chosen = S.result === r.id;
        node.setAttribute('aria-checked', chosen ? 'true' : 'false');
        node.setAttribute('tabindex', (S.result || RESULTS[0].id) === r.id ? '0' : '-1');                 // one tab stop for the group, the arrows move inside it
        node.setAttribute('aria-busy', t.state === 'loading' ? 'true' : 'false');
        node.className = 'creation-tile' + (chosen ? ' is-chosen' : '');
        fill(slot, t.state === 'ready' ? h('img', {src: t.src, alt: `Your image: ${r.title.toLowerCase()}. ${FACTS[r.id](t.facts)}`})
          : h('span', {class: 'creation-tile-wait muted small', role: 'status'}, t.state === 'failed' ? `Could not render: ${t.error}` : 'Rendering…'));
        fill(facts, t.state === 'ready' ? FACTS[r.id](t.facts) : '');
        fill(status, !ready ? pill('checking', '') : ready.error ? pill('not checked', 'warn') : ready.ready ? pill('ready to create', 'ok')
          : ready.missing.includes('measurements') ? pill('measurements needed', 'warn') : pill('missing: ' + ready.missing.map((k) => ({laser: 'laser', titanium: 'titanium', lens: 'lens'}[k] || k)).join(', '), 'warn'));
      };
      tileViews[r.id] = {node, update};
      update();
      return node;
    }
    let nextButton = null;
    const syncNext = () => { if (nextButton) nextButton.disabled = !S.result; };
    /** Choose a result; the choice is saved with the task. */
    function choose(id) {
      S.result = id;
      autosave();
      for (const v of Object.values(tileViews)) v.update();
      syncNext();
    }
    /** The group answers the arrows like a group of radio buttons: the choice moves with the keyboard. */
    function arrows(ev) {
      const at = RESULTS.findIndex((r) => (S.result || RESULTS[0].id) === r.id);
      const to = {ArrowRight: at + 1, ArrowDown: at + 1, ArrowLeft: at - 1, ArrowUp: at - 1, Home: 0, End: RESULTS.length - 1}[ev.key];
      if (to === undefined) return;
      ev.preventDefault();
      const next = RESULTS[(to + RESULTS.length) % RESULTS.length];
      choose(next.id);
      tileViews[next.id].node.focus();
    }

    function resultStep() {
      return h('div', {class: 'stack'},
        h('p', {class: 'muted small'}, 'Your image at a width of ' + `${widthIn.value} mm`.replace('.', ',') + ', shown using each method. Titanium colors are selected later from the chosen setup’s measurements.'),
        h('div', {class: 'creation-tiles', role: 'radiogroup', 'aria-label': 'Choose a result', onKeydown: arrows}, RESULTS.map(tileView)),
        strip.el, error,
        h('div', {class: 'row'}, btn('← Back', () => goTo('picture')), (nextButton = btn('Next →', toMethod, 'primary', !S.result))));
    }

    function gate(r, ready) {
      const items = ready.missing.filter((k) => k !== 'measurements').map((k) => {
        const [text, to, label] = MISSING[k];
        return h('li', {}, text, ' ', link(to, label));
      });
      const test = ready.starter_test;
      return h('div', {class: 'alert warn stack', role: 'region', 'aria-label': 'Missing prerequisites'},
        h('strong', {}, `To create “${r.title.toLowerCase()}”, the following is still missing:`),
        items.length ? h('ul', {}, items) : null,
        ready.missing.includes('measurements') ? starterCard(r, ready, test) : null,
        h('p', {class: 'small'}, 'Your entries are saved in the task. When ready, reopen it from the unfinished-work bar on any screen, including after restarting the application.'));
    }

    function starterCard(r, ready, test) {
      if (!test) return h('p', {}, 'Measurements are needed for this laser, lens, and titanium. Add the missing prerequisites above first; the test requires a lens and blank.');
      const made = S.starter;
      return h('div', {class: 'stack'},
        h('p', {}, h('strong', {}, 'Measurements needed. '), r.needs),
        h('p', {}, h('strong', {}, 'Starter test: '), test.test_type ? (S.plateNames[test.test_type] || test.test_type) : 'the next step is ready',
          test.guide && test.guide.message ? ` — ${test.guide.message}` : ''),
        test.guide && test.guide.next_step ? h('p', {class: 'small'}, test.guide.next_step) : null,
        h('p', {class: 'small'}, h('strong', {}, 'What becomes available: '), BECOMES[test.becomes] || ''),
        r.id === 'photo' || r.id === 'colour' ? h('p', {class: 'small muted'}, 'If measurements are available in a connected laboratory release, select it using Change… in the context above.') : null,
        test.needs_rig ? h('p', {class: 'small'}, 'A capture setup is required to add a test photograph: ', link('/setup?tab=rigs', 'Add capture setup')) : null,
        made ? h('p', {class: 'alert ok small', role: 'status'}, `Test created: ${made.name}. `, link('/experiment/plan-' + made.plan_id, 'Open test')) : null,
        h('div', {class: 'row'}, test.guide && test.guide.pending_plan_id ? link('/plans/' + test.guide.pending_plan_id, 'Open existing test')
          : r.id === 'photo' ? btn('Create grayscale scales test…', () => startTest(r, test), 'primary')
          : btn('Create starter test', (ev) => { const self = ev.currentTarget; return makeStarter(r, self); }, 'primary', !test.test_type)));
    }

    async function startTest(r, test) {
      S.waiting = {for: 'starter_test', result: r.id};
      await flush();
      await refreshBar();
      await PlateDialog.open(lists.devices, null, null, {type: test.test_type, device: S.context.device_id, material: S.context.material_id});
    }
    async function makeStarter(r, button) {
      button.disabled = true;
      try {
        S.waiting = {for: 'starter_test', result: r.id};
        await flush();
        const made = await post('/creation/starter-plate', {result: r.id});
        S.starter = (made.parts && made.parts[0]) || made;
        toast('Test created: engrave it and add a photograph', 'ok');
        await loadReadiness();
        drawStep();
      } catch (e) { fail(e); button.disabled = false; }
    }

    const kindLine = () => {
      S.kindText = h('span', {}, PhotoPanels.kindName(S.kind || PhotoPanels.GRAYSCALE));          // follows the mark in the question, also after “← Back”
      return h('p', {class: 'small'}, h('strong', {}, 'Engraving mode: '), S.kindText,
        '. The next window shows your image in each mode; choose a mode before the work is created.');
    };

    function methodFields(r) {
      if (r.id === 'photo') {
        return h('p', {class: 'small muted'}, S.context.source
          ? 'The scale is the best measured in the laboratory release; you can change the scale, Min, Max, and width in the work.'
          : 'The scale is the best measured one, and Min and Max use its measured range. You can change the scale, Min, Max, width, and grayscale matching in the work.');
      }
      methodForm = Forms.create();
      // the tolerance is required only while the rules of the laser and lens hold none (conversion._threshold)
      const thr = methodForm.add('threshold', 'ΔE tolerance', M.thr, {quantity: 'deltaE', help: toleranceHint(),
        read: () => (M.thr.value === '' ? (S.rules === null ? {ok: false, message: 'Enter a ΔE tolerance; none is saved for this laser and lens'} : {ok: true, value: null})
          : Forms.readNumber(M.thr, Q.deltaE, {}))});
      const remember = h('label', {class: 'row small', hidden: S.rules !== null}, M.remember, h('span', {}, 'Remember for this laser and lens'));
      const common = [h('div', {class: 'f'}, thr, remember),
        methodForm.add('tolerance', r.id === 'colour' ? 'Boundary smoothing' : 'Contour precision', M.tolerance, {quantity: 'vectorTolerance', required: true}),
        h('label', {class: 'row'}, M.markers, h('span', {}, 'Registration markers and identifier outside the image'))];
      if (r.id === 'colour') {
        return h('div', {class: 'grid g2'}, field('Splitting algorithm', M.algorithm.select),
          methodForm.add('colours', 'Number of colors', M.colours, {quantity: 'photoColours', required: true, constraint: '', help: '2–29, or 2–28 with markers; cleaning is the first layer',
            read: () => Forms.readNumber(M.colours, {...Q.photoColours, max: M.markers.checked ? 28 : 29}, {required: true})}),
          M.algorithm.hint, field('Detail', M.detail, 'coarse produces larger smooth regions; fine produces smaller regions'),
          methodForm.add('max_time', 'Maximum engraving time', M.maxTime, {quantity: 'maxTime', help: 'leave empty for no limit; automatic selection excludes slower colors'}),
          h('label', {class: 'row'}, M.faces, h('span', {}, 'Detect faces: split eyes and lips in more detail')),
          h('label', {class: 'row'}, M.asShot, h('span', {}, 'Include uncalibrated colors (captured without a reference or clean titanium)')), ...common);
      }
      return h('div', {class: 'grid g2'}, methodForm.add('grey', 'Grayscale threshold', M.grey, {quantity: 'greyThreshold', help: 'leave empty for automatic'}),
        h('label', {class: 'row'}, M.clean, h('span', {}, 'Cleaning as first layer (C00)')), ...common);
    }

    function methodStep() {
      const r = RESULT[S.result], ready = S.readiness[S.result];
      const blocked = !ready || !ready.ready;
      const open = r.id !== 'photo' && S.rules === null;
      const details = r.id === 'photo' ? h('div', {class: 'stack'}, methodFields(r), kindLine()) : h('details', {class: 'creation-advanced', open: open ? '' : null},
        h('summary', {}, 'Advanced: algorithm, ΔE tolerance, smoothing, time'), methodFields(r));
      return h('div', {class: 'stack'},
        h('div', {class: 'card stack'}, h('div', {class: 'row'}, pictureSrc() ? h('img', {class: 'creation-thumb', src: pictureSrc(), alt: 'Task image'}) : null,
          h('div', {}, h('strong', {}, nameIn.value.trim() || 'untitled'), h('p', {class: 'small muted'}, `${r.title} · width ${widthIn.value} mm`),
            h('p', {class: 'small'}, r.file))), details),
        strip.el,
        S.returned && ready && ready.ready ? h('p', {class: 'alert ok', role: 'status'}, 'The missing prerequisites are available. You can create the work; the image, name, and settings are unchanged.') : null,
        blocked && ready && !ready.error ? gate(r, ready) : null,
        ready && ready.error ? h('p', {class: 'alert bad', role: 'alert'}, `Could not check missing prerequisites: ${ready.error}`) : null,
        methodForm.error, error,
        h('div', {class: 'row'}, btn('← Back', () => goTo('result')), btn(r.id === 'photo' ? 'Next: engraving mode →' : 'Create work', create, 'primary', blocked)));
    }

    function unfinished() {
      const others = drafts.filter((d) => !S.draft || d.id !== S.draft.id);
      if (!others.length || S.draft) return null;
      return h('section', {class: 'card stack', 'aria-label': 'Unfinished tasks'}, h('h3', {}, `Unfinished tasks: ${others.length}`),
        others.slice(0, 5).map((d) => h('div', {class: 'row'}, h('strong', {}, d.name || (d.image && baseName(d.image.name)) || 'untitled'),
          h('span', {class: 'small muted'}, (d.state && d.state.result && RESULT[d.state.result] ? RESULT[d.state.result].title : 'result not selected')),
          h('span', {class: 'spacer'}), btn('Continue', () => start({draft: d.id}), 'btn-small primary'), btn('Cancel task', () => discard(d, () => App.render()), 'btn-small'))),
        others.length > 5 ? h('p', {class: 'small muted'}, `and ${others.length - 5} more`) : null);
    }

    function drawStep() {
      const body = S.step === 'picture' ? pictureStep() : S.step === 'result' ? resultStep() : methodStep();
      fill(host, h('div', {class: 'row'}, h('div', {}, heading(`New work · step ${stepNumber()} of ${STEPS.length}: ${STEPS[stepNumber() - 1][1]}`),
        h('p', {class: 'sub'}, 'Choose an image, size, and result. Until the work is created, entries are saved in the task and persist across restarts.')),
        h('span', {class: 'spacer'}), S.draft ? btn('Cancel task', () => discard(S.draft, async () => { S.draft = null; await refreshBar(); go('/vector'); }), 'btn-small') : null),
        stepList(), S.missingDraft ? h('p', {class: 'alert warn', role: 'status'}, 'This task has already been completed or canceled and is no longer in the unfinished list. Start a new one.') : null,
        S.released ? h('p', {class: 'alert warn', role: 'status'}, 'The engraving mode selection was not completed; the temporary work was deleted. Choose a mode again.') : null,
        note, unfinished(), body);
      if (focusNext) { focusNext = false; focusHeading(); }
    }

    async function goTo(step) {
      show('');
      S.step = step;
      focusNext = true;
      if (step === 'result') { await loadReadiness(); RESULTS.forEach((r) => { if (!S.tiles[r.id] || S.tiles[r.id].key !== tileKey(r)) loadTile(r); }); }
      if (step === 'method') {
        await loadReadiness();
        if (S.result !== 'photo') await loadRules();
        const ready = S.readiness[S.result];
        // what the person is going away to do is saved with the task: the bar reminds of it and, after a restart, the task says where it was left
        S.waiting = ready && ready.ready === false ? {for: ready.missing.includes('measurements') && !ready.missing.includes('lens') ? 'starter_test' : 'equipment', result: S.result} : null;
      }
      autosave();
      drawStep();
    }

    async function toResult() {
      show('');
      if (!pictureForm.collect()) return;                                           // the picture and the width: each wrong one says why beside itself
      const file = chosenFile();
      if (!nameIn.value.trim() && file) nameIn.value = baseName(file.name);
      S.step = 'result';
      try { await send({file: file && file !== S.uploaded ? file : null}); }
      catch (e) { S.step = 'picture'; pictureForm.fail(e); return; }                // a picture that is no picture is told beside it, and nothing is kept
      await goTo('result');
    }

    async function toMethod() { if (S.result) await goTo('method'); }

    async function pictureBlob() {
      const res = await fetch(`/api/creation/drafts/${S.draft.id}/picture`);
      if (!res.ok) throw new Error('Task image not found; choose it again');
      return res.blob();
    }

    async function create(ev) {
      if (S.busy) return;
      show('');
      const r = RESULT[S.result], c = S.context, width = numberOf(widthIn.value);
      if (!(width > 0)) { show('Width on titanium must be a positive number of millimeters. Return to the image step and correct it.'); return; }
      if (r.work === 'vector') {
        toleranceHint();
        if (!methodForm.collect()) return;                                         // every wrong box says why beside itself; nothing typed is lost
      }
      S.busy = true;
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const blob = await pictureBlob();
        const fileName = S.draft.image.name, name = nameIn.value.trim() || baseName(fileName) || 'Work';
        const made = r.work === 'photo' ? await createPhoto(blob, fileName, name, width) : await createVector(r, blob, fileName, name, width);
        // BUG-003: a photograph asks “Which engraving mode?” before it is kept; leaving the question deletes the work and the task stays as it was
        if (r.work === 'photo' && await askKind(made) === null) { self.disabled = false; self.focus(); return; }
        try { await post(`/creation/drafts/${S.draft.id}/complete`, {work_kind: r.work, work_id: made.id}); }
        catch (e) { toast('Work created, but the task remains unfinished; cancel it', 'warn'); }
        await refreshBar();
        toast(r.work === 'photo' ? 'Photo engraving work created' : 'Vector work created', 'ok');
        go(r.work === 'photo' ? `/photo-engraving?work=${made.id}` : `/vector?plan=${made.id}`);
      } catch (e) { if (r.work === 'vector') methodForm.fail(e); else show(e.message); self.disabled = false; }
      finally { S.busy = false; }
    }

    /** “Which engraving mode?” for the photo work just made (PhotoKindStep, the same dialog as in photo engraving). Resolves with the kind the person keeps
        the work in, or null when they left it: the work is deleted and the form is as it was. The task records the work while the question is open
        (``hold``), so a window closed in the middle does not leave it behind: it is deleted when the task is opened again (``releaseHold``). */
    function askKind(made) {
      const held = {id: made.id, created_at: made.created_at};
      return new Promise((resolve) => {
        S.hold = held;
        flush();
        PhotoKindStep.open(made.id, {
          title: 'New work · engraving mode', initial: S.kind || PhotoPanels.GRAYSCALE,
          onChoose: (key) => { S.kind = key; if (S.kindText) fill(S.kindText, PhotoPanels.kindName(key)); autosave(); },
          before: async () => {                       // from here the work is the person's: the task must no longer point at it
            S.hold = null;
            try { await send(); } catch (e) { S.hold = held; throw e; }
          },
          failed: async () => { S.hold = held; await flush(); },
          onKept: (key) => resolve(key),
          onLeft: () => { S.hold = null; flush(); resolve(null); }});
      });
    }

    /** Deletes the work a closed window left only for the question of the kind, if it is still that very work (the task says its number and time). */
    async function releaseHold() {
      const held = S.hold;
      if (!held) return;
      S.hold = null;
      try {
        const now = await get(`/photo-works/${held.id}`);
        if (now.created_at === held.created_at) { await del('/plans/' + held.id); S.released = true; }
      } catch (_) { /* the work is gone or is not the same one: nothing to delete */ }
      autosave();
    }

    async function createVector(r, blob, fileName, name, width) {
      const c = S.context, m = methodState();
      const fd = new FormData();
      fd.append('device_id', c.device_id); fd.append('lens_id', lensField(c)); fd.append('material_id', c.material_id); fd.append('name', name);
      fd.append('width_mm', width); fd.append('strategy', r.strategy); fd.append('tolerance_mm', m.tolerance); fd.append('markers', m.markers);
      fd.append('image', blob, fileName);
      if (m.thr !== '') fd.append('threshold', m.thr);
      if (r.id === 'colour') {
        fd.append('n_colors', m.colours); fd.append('algorithm', m.algorithm); fd.append('detail', m.detail); fd.append('faces', m.faces); fd.append('include_as_shot', m.asShot);
        if (m.maxTime !== '') fd.append('max_time', m.maxTime);
        if (c.source) { const {label, ...pin} = c.source; fd.append('source', JSON.stringify(pin)); }
      } else {
        fd.append('clean', m.clean);
        if (m.grey !== '') fd.append('grey_threshold', m.grey);
      }
      if (m.thr !== '' && S.rules === null && m.remember) {
        await put('/rules', {device_id: c.device_id, lens_id: c.lens_id, delta_tolerance: +m.thr});    // a tolerance typed while the rules hold none is saved to them, once
        S.rules = +m.thr;
      }
      return form('/vector', fd);
    }

    async function createPhoto(blob, fileName, name, width) {
      const c = S.context;
      const fd = new FormData();
      fd.append('picture', blob, fileName); fd.append('name', name); fd.append('width_mm', width);
      if (c.source) { const {label, ...pin} = c.source; fd.append('source', JSON.stringify({...pin, device_id: c.device_id, lens_id: c.lens_id})); }
      else {
        // the work is made on the best scale of the context's own laser, lens and titanium, not on whichever scale the workshop measured best
        const mode = await App.contextScale(c, width);
        if (!mode) throw new Error('No grayscale scale is measured for the selected laser, lens, and titanium. Reopen the task to see the missing prerequisites.');
        fd.append('scale', JSON.stringify(mode));
      }
      return form('/photo-works', fd);
    }

    S.plateNames = Object.fromEntries(plateTypes.map((row) => [row.id, row.name]));
    await releaseHold();
    if (S.step === 'result' && S.draft) { await loadReadiness(); RESULTS.forEach(loadTile); }
    if (S.step === 'method' && S.draft) {
      await loadReadiness();
      if (S.result !== 'photo') await loadRules();
      const ready = S.readiness[S.result];
      if (S.waiting && ready && ready.ready) { S.returned = true; S.waiting = null; autosave(); }          // came back from setting up what was missing
    }
    focusNext = false;
    drawStep();
    refreshBar();
    setTimeout(focusHeading, 0);                                       // after the router has placed the screen: the keyboard starts at the step's heading
    return host;
  }

  App.register({id: 'new', render});
  mountBar();
  return {start, url, render, refreshBar, RESULTS};
})();
