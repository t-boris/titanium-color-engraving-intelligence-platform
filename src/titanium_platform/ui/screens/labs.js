/* Laboratory publication and connected source management. */
'use strict';
(() => {
  const {h, fill, btn, field, link, pill, get, post, put, del, form, go, toast, fail, modal, confirmBox, facts, table, num, labText, swatch, agreed, CAUTION} = App;
  const {short, day, when, laserName, lensName, materialName, setupName, releaseName, BASIS} = LabSource;
  const POLL_MS = 300;
  const mb = (bytes) => `${(bytes / 1024 / 1024).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0).replace('.', ',')} MB`;
  const SECTION = {equipment: 'setups', materials: 'titanium materials', captures: 'photographs', measurements: 'measurements', tone_profiles: 'tone profiles',
    provenance: 'provenance records', lab: 'laboratory', withdrawals: 'withdrawals'};
  const countsText = (counts) => Object.entries(counts || {}).filter(([, n]) => n).map(([k, n]) => `${SECTION[k] || k}: ${n}`).join(' · ') || 'empty';
  const NEVER = {photographs: 'photographs', raw: 'source files', previews: 'previews', lightburn_geometry: 'LightBurn geometry', masks: 'masks',
    paths: 'file paths', file_names: 'file names', titles: 'names', layer_names: 'layer names', notes: 'notes', ai: 'AI conversations',
    credentials: 'keys and passwords', email: 'email', serial: 'serial numbers', batch: 'batches', surface: 'surface treatment',
    free_text_settings: 'free-text settings'};
  const TARGET = {release: 'release', measurement: 'measurement', tone_profile: 'tone profile'};
  const PHASE = {waiting: 'waiting', downloading: 'downloading from cloud', checking: 'checking file', building: 'building snapshot', activating: 'connecting',
    done: 'connected', unchanged: 'already connected', failed: 'not connected', cancelled: 'cancelled'};
  const STATUS = {connected: ['connected', 'ok'], disconnected: ['disconnected', 'warn']};
  const termsName = (t) => (t ? (t.name && t.name.en) || t.id || '—' : '—');
  const termsOf = (list, id) => list.find((t) => t.id === id) || {id};
  const verifiedPill = (v) => (v ? pill('signature verified', 'ok') : pill('signature not verified', 'warn'));
  const recipeText = (r) => (r ? [`${num(r.power, 1)} %`, `${num(r.frequency, 1)} kHz`, `${num(r.speed, 0)} mm/s`, r.pulse_width == null ? null : `${num(r.pulse_width, 0)} ns`,
    r.line_interval == null ? null : `interval ${num(r.line_interval, 4)} mm`, `passes ${r.passes ?? 1}`, r.global_passes > 1 ? `global ${r.global_passes}×` : null,
    r.cross_hatch ? 'cross-hatch' : null, r.scan_angle == null ? null : `angle ${num(r.scan_angle, 0)}°`].filter(Boolean).join(' · ') : 'recipe not recorded');
  const safeLink = (url) => (url ? h('span', {class: 'lab-url'}, url) : null);      // a laboratory's link is shown as text, never followed from here
  // the orders of the short lists (DEC-090): by an ISO date, the newest or the oldest first
  const newest = (at) => (p, q) => String(at(q) || '').localeCompare(String(at(p) || ''));
  const oldest = (at) => (p, q) => String(at(p) || '').localeCompare(String(at(q) || ''));

  // ---- «My laboratory» ---------------------------------------------------------------------------------------------------------

  function publicForm(pub, saved) {
    const f = Forms.create();
    // every box is sent as typed (``raw``); an unsaved sentence stays in its box when the server refuses, with the reason under the form
    const box = (name, label, value, o = {}) => f.add(name, label, o.multiline ? h('textarea', {rows: 3, value}) : h('input', {value}), {raw: true, help: o.help});
    const fields = {name: box('name', 'Laboratory name', pub.name || ''), author: box('author', 'Author', pub.author || ''),
      url: box('url', 'Laboratory URL', pub.url || '', {help: 'HTTPS URL; leave empty for no link'}), organization: box('organization', 'Organization', pub.organization || ''),
      authorUrl: box('author_url', 'Author URL', pub.author_url || '', {help: 'HTTPS URL; leave empty for no link'}), description: box('description', 'Description', pub.description || '', {multiline: true})};
    const lasers = Object.entries(pub.lasers || {}).map(([id, laser]) => {
      const manufacturer = h('input', {value: laser.manufacturer || '', 'aria-label': `Laser manufacturer ${id}`}), model = h('input', {value: laser.model || '', 'aria-label': `Laser model ${id}`});
      const publicName = f.add(`laser_${id}`, `Laser #${id}: public name`, h('input', {value: laser.public_name || ''}), {raw: true});
      return {id, publicName, manufacturer, model, el: h('div', {class: 'grid g2 lab-laser'}, publicName,
        field('Manufacturer and model', h('div', {class: 'row'}, manufacturer, model)))};
    });
    const save = btn('Save', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const v = f.collect();
        if (!v) return;
        const made = await put('/labs/own', {name: v.name, description: v.description, url: v.url, author: v.author, organization: v.organization, author_url: v.author_url,
          lasers: Object.fromEntries(lasers.map((l) => [l.id, {public_name: v[`laser_${l.id}`], manufacturer: l.manufacturer.value, model: l.model.value}]))});
        toast('Public details saved', 'ok');
        saved(made);
      } catch (e) { f.fail(e); } finally { self.disabled = false; }
    }, 'primary');
    return h('div', {class: 'card stack'}, h('h3', {}, 'Public details'),
      h('p', {class: 'small muted'}, 'Only these workshop details are included in every release: name, description, URL, author, and public laser names. '
        + 'Local laser names, file names, photographs, and notes are never published.'),
      h('div', {class: 'grid g2'}, fields.name, fields.author, fields.url, fields.organization, fields.authorUrl, fields.description),
      lasers.length ? lasers.map((l) => l.el) : h('p', {class: 'muted small'}, 'No lasers yet: add one in Lasers.'), f.error, save);
  }

  /** What «Prepare publication» shows of a preview: the same for a file and for the cloud. */
  function previewBody(p) {
    return [facts([['Photographs', p.photographs], ['Engravings', p.engravings], ['Measurements', p.measurements], ['Tone profiles', p.tone_profiles],
      ['Setups (laser and lens)', p.setups], ['Titanium materials', p.materials]]),
    h('p', {class: 'small'}, h('strong', {}, 'Public: '), `${p.public.name || 'name not set'}; author ${p.public.author || 'not set'}`
        + (p.public.organization ? `, ${p.public.organization}` : '') + '; lasers: '
        + (Object.values(p.public.lasers || {}).map((l) => l.public_name).join(', ') || 'none')),
    Object.keys(p.tokenised || {}).length ? h('details', {class: 'small'}, h('summary', {}, 'Settings that will be tokenized'),
      h('ul', {}, Object.entries(p.tokenised).map(([tag, values]) => h('li', {}, `${tag}: ${values.join(', ')}`)))) : h('p', {class: 'small muted'}, 'No text settings require tokenization.'),
    h('p', {class: 'small muted'}, 'Never published: ' + (p.never || []).map((k) => NEVER[k] || k).join(', ') + '.'),
    p.ready ? h('p', {class: 'alert ok'}, 'The release can be saved.') : h('p', {class: 'alert warn'}, p.photographs
      ? 'Enter the public laboratory name and author before publishing.' : 'Nothing to publish: there are no accepted photographs yet.')];
  }

  /** The written releases, a line each, the newest first: when, the hash, what it holds, whether it went to the cloud; its file at the end. */
  function exportsList(terms, exports) {
    const created = (e) => e.created_at;
    return App.list({id: 'labs-exports', items: exports, key: (e) => e.release_id,
      row: (e) => [h('span', {}, when(e.created_at)), h('span', {class: 'muted'}, short(e.content_sha256)), h('span', {class: 'lst-text small'}, countsText(e.counts)),
        e.published ? pill(`cloud #${e.published.release_number}`, 'ok') : null],
      details: (e) => facts([['Release', short(e.content_sha256)], ['Contents', countsText(e.counts)], ['Terms', termsName(termsOf(terms, (e.terms || {}).id))],
        ['Size', mb(e.bytes || 0)], ['Cloud', e.published ? `# ${e.published.release_number} · ${day(e.published.published_at)}` : 'not published']]),
      actions: (e) => [e.file ? h('a', {class: 'btn btn-small', href: `/api/labs/own/releases/${encodeURIComponent(e.release_id)}/file`, download: ''}, 'Download')
        : h('span', {class: 'muted small'}, 'file not saved')],
      filters: [{key: 'cloud', label: 'Cloud', options: [['yes', 'in cloud'], ['no', 'file only']], test: (e, v) => !!e.published === (v === 'yes')}],
      sorts: [['new', 'Newest first', newest(created)], ['old', 'Oldest first', oldest(created)]]}).el;
  }

  function previewCard(terms, exports, written) {
    const out = h('div', {class: 'stack'});
    const termsSelect = h('select', {'aria-label': 'Usage terms'}, terms.map((t) => h('option', {value: t.id}, `${termsName(t)} — ${(t.summary && t.summary.en) || ''}`)));
    const result = h('div', {class: 'stack'});
    let ready = false;
    const prepare = btn('Prepare publication', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const p = await post('/labs/own/preview', {selection: null});
        ready = p.ready;
        write.disabled = !ready;
        fill(out, previewBody(p));
      } catch (e) { fill(out, h('p', {class: 'alert bad'}, e.message)); } finally { self.disabled = false; }
    });
    const write = btn('Save release', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const made = await post('/labs/own/releases', {selection: null, terms: termsSelect.value});
        const m = made.manifest;
        fill(result, h('p', {class: 'alert ok'}, `Release saved: ${short(m.content_sha256)} · ${countsText(m.counts)} · ${termsName(termsOf(terms, (m.usage_terms || {}).id))}. `,
          h('a', {href: made.download, download: ''}, 'Download .tcelab file')));
        toast('Release saved', 'ok');
        written();
      } catch (e) { fill(result, h('p', {class: 'alert bad'}, e.message)); } finally { self.disabled = !ready; }
    }, 'primary', true);
    return h('div', {class: 'card stack'}, h('h3', {}, 'Publication'),
      h('p', {class: 'small muted'}, 'A release is a .tcelab file containing numerical results from all accepted photographs: measured colors, recipes, tone profiles, setups, and titanium materials. '
        + 'Review the contents first; a release cannot be changed after saving.'),
      h('div', {class: 'row'}, prepare, field('Usage terms', termsSelect), write), out, result,
      exports.length ? h('div', {class: 'stack'}, h('h4', {}, 'Saved releases'), exportsList(terms, exports))
        : h('p', {class: 'muted small'}, 'No releases yet.'));
  }

  function withdrawalCard(exports, withdrawals, declared) {
    const f = Forms.create();
    const kind = h('select', {}, Object.entries(TARGET).map(([id, name]) => h('option', {value: id}, name)));
    const target = h('input', {placeholder: 'identifier (UUID)'});
    const reason = h('textarea', {rows: 2, placeholder: 'Reason for withdrawal'});
    const replacement = h('select', {}, h('option', {value: ''}, 'no replacement'),
      exports.map((e) => h('option', {value: e.release_id}, `${when(e.created_at)} · ${short(e.content_sha256)}`)));
    const released = h('select', {'aria-label': 'Saved release'}, h('option', {value: ''}, 'select release'),
      exports.map((e) => h('option', {value: e.release_id}, `${when(e.created_at)} · ${short(e.content_sha256)}`)));
    released.addEventListener('change', () => { target.value = released.value; });
    const switchKind = () => { released.hidden = kind.value !== 'release'; };
    kind.addEventListener('change', switchKind);
    switchKind();
    const kindField = f.add('kind', 'What to withdraw', kind, {required: true});
    const targetField = f.add('target', 'Identifier', target, {required: true});
    const reasonField = f.add('reason', 'Reason', reason, {raw: true, required: true, constraint: 'at most 500 characters, plain text only (lab_export.withdraw)'});
    const replacementField = f.add('replacement', 'Replacement release', replacement, {empty: null});
    const send = btn('Withdraw', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const v = f.collect();
        if (!v) return;
        await post('/labs/own/withdrawals', {target_kind: v.kind, target_id: v.target, reason: v.reason, replacement_release_id: v.replacement || null});
        toast('Withdrawal recorded: it will be included in every subsequent release', 'ok');
        declared();
      } catch (e) { f.fail(e); } finally { self.disabled = false; }
    }, 'danger');
    return h('div', {class: 'card stack'}, h('h3', {}, 'Withdraw published data'),
      h('p', {class: 'small muted'}, 'Published releases cannot be changed. If one contains an error, declare a withdrawal of the release, measurement, or tone profile with a reason and, if available, '
        + 'a replacement release. The declaration accompanies every subsequent release and recipients exclude withdrawn data from new work.'),
      h('div', {class: 'grid g2'}, kindField, h('div', {class: 'f'}, targetField, released), reasonField, replacementField), f.error, send,
      withdrawals.length ? table(['Declared', 'Target', 'Identifier', 'Reason', 'Replacement'], withdrawals.map((w) => [when(w.declared_at), TARGET[w.target_kind] || w.target_kind,
        short(w.target_id), w.reason, w.replacement_release_id ? short(w.replacement_release_id) : '—']), '', true) : h('p', {class: 'muted small'}, 'No withdrawals.'));
  }

  async function ownTab() {
    const el = h('div', {class: 'stack'});
    async function show() {
      const data = await get('/labs/own');
      const cloud = h('div', {'aria-live': 'polite'}, 'Loading cloud…');
      fill(el, publicForm(data.public, show), previewCard(data.terms, data.exports, show), cloud, withdrawalCard(data.exports, data.withdrawals, show));
      LabsCloud.ownCard(data.terms, show).then((card) => fill(cloud, card)).catch((e) => fill(cloud, h('p', {class: 'alert bad'}, e.message)));
    }
    await show();
    return el;
  }

  // ---- «Connected laboratories»: a file --------------------------------------------------------------------------------------------

  /** What a chosen file declares, before anything is connected; «Connect» starts the job, «Do not connect» forgets the file. */
  function inspectCard(info, done, options = {}) {
    const lab = info.lab || {}, a = info.attribution || {}, r = info.release || {}, c = info.compatibility || {};
    const terms = info.terms || {};
    const permission = (key) => terms[key] === true ? 'Allowed' : terms[key] === false ? 'Not allowed' : 'Not specified';
    const counts = Object.entries(r.counts || {}).map(([key, count]) => `${key.replace(/_/g, ' ')}: ${count}`).join(' · ') || 'No contents listed';
    const equipment = (info.equipment || []).map((e) => [e.laser, e.manufacturer, e.model,
      e.rated_power_w == null ? null : `${e.rated_power_w} W`, e.wavelength_nm == null ? null : `${e.wavelength_nm} nm`,
      e.focal_length_mm == null ? null : `${e.focal_length_mm} mm lens`].filter(Boolean).join(' · ')).join('; ') || 'None listed';
    const materials = (info.materials || []).map((m) => [m.family, m.grade, m.thickness_mm == null ? null : `${m.thickness_mm} mm`].filter(Boolean).join(' · ')).join('; ') || 'None listed';
    const el = h('div', {class: 'card stack lab-inspect'});
    const progress = h('div', {class: 'stack', hidden: true});
    const connect = btn('Connect laboratory', async () => {
      connect.disabled = true; forget.disabled = true;
      try {
        if (options.start) await followJob({start: options.start, jobs: options.jobs, box: progress, done});
        else await connectJob(info.token, progress, done);
      } catch (e) { fail(e); } finally { connect.disabled = false; forget.disabled = false; }
    }, 'primary');
    const forget = btn('Do not connect', async () => {
      try { if (options.discard) await options.discard(); else await del(`/labs/files/${encodeURIComponent(info.token)}`); el.remove(); } catch (e) { fail(e); }
    });
    return fill(el, h('h3', {}, 'Release file: ', h('span', {class: 'lab-name'}, lab.name || 'Unnamed laboratory'),
      info.verified ? pill('Verified cloud source', 'ok') : pill('Source not verified', 'warn')),
      facts([['Description', lab.description], ['Laboratory URL', safeLink(lab.url)], ['Author', [a.name, a.organization].filter(Boolean).join(', ') || null], ['Author URL', safeLink(a.url)],
        ['Release', `${r.release_number != null ? `#${r.release_number} · ` : ''}${day(r.created_at)} · ${short(r.content_sha256)}`],
        ['Available measurements', counts], ['Size', `${(Number(info.bytes || 0) / 1024 / 1024).toFixed(1)} MB`], ['Usage terms', termsName(terms)],
        ['Format compatibility', c.newer_minor ? `Newer format version (${c.schema_version}): unknown fields are retained but not used.`
          : `Readable format (schema ${c.schema_version || '—'}).`], ['Equipment', equipment], ['Material', materials]]),
      h('p', {class: 'small muted'}, 'Compare the listed equipment and material with your workshop. Format compatibility does not establish that a recipe is suitable for your machine.'),
      h('div', {class: 'lab-terms stack'}, h('strong', {}, 'Usage permissions'),
        h('p', {class: 'small'}, (terms.summary && terms.summary.en) || 'See the terms and permissions below.'),
        facts([['Commercial use', permission('commercial')], ['Modification', permission('modify')], ['Redistribution', permission('redistribute')],
          ['Attribution', [a.name, a.organization].filter(Boolean).join(', ') || 'Not specified'], ['Terms URL', safeLink(terms.url)]])),
      h('details', {class: 'lab-release-details'}, h('summary', {}, 'Full release details'),
        facts([['Content SHA-256', r.content_sha256 || 'Not supplied'], ['Release ID', r.release_id || 'Not supplied'], ['Full contents', counts],
          ['Capabilities', r.capabilities ? JSON.stringify(r.capabilities) : 'Not supplied'],
          ['Algorithm versions', r.algorithm_versions ? JSON.stringify(r.algorithm_versions) : 'Not supplied']])),
      info.own ? h('p', {class: 'alert warn'}, 'This is a release of this workshop’s own laboratory; its results are already here.') : null,
      info.connected ? h('p', {class: 'alert'}, info.connected.same ? 'This exact release is already connected.' : 'A release with this identifier is connected, but its contents differ.') : null,
      h('p', {class: 'small muted'}, 'Nothing is connected yet. Connecting checks each record in the background and can be canceled.'),
      h('div', {class: 'row'}, connect, forget), progress);
  }

  /** A job in the background (a connection from a file or from the cloud, a publication): `start()` starts it, then it is polled at
      `jobs`/<id> every 300 ms with a bar of bytes; «Cancel» asks the server to stop. Resolves with the final job, null when it did not start. */
  function followJob({start, jobs = '/labs/jobs', box, done, label = 'Connecting release', phases = PHASE, success = null}) {
    return new Promise((resolve) => {
      let job = null, timer = null;
      const bar = h('div', {class: 'lab-bar'}, h('div', {class: 'lab-bar-fill'}));
      const text = h('span', {class: 'small'});
      const cancel = btn('Cancel', async () => { if (job) { try { await post(`${jobs}/${job.id}/cancel`, {}); } catch (e) { fail(e); } } }, 'btn-small');
      const meter = h('div', {role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-label': label}, bar);
      box.hidden = false;
      fill(box, h('div', {class: 'row'}, text, h('span', {class: 'spacer'}), cancel), meter);
      const show = () => {
        const percent = job.total ? Math.round(job.read / job.total * 100) : 0;
        bar.firstChild.setAttribute('style', `width:${percent}%`);
        meter.setAttribute('aria-valuenow', String(percent));
        text.textContent = `${phases[job.phase] || PHASE[job.phase] || job.phase} · ${mb(job.read || 0)} of ${mb(job.total || 0)} (${percent} %)`;
      };
      const finish = () => {
        clearInterval(timer);
        cancel.disabled = true;
        if (job.error) fill(box, h('p', {class: 'alert bad', role: 'alert'}, I18N.tr(job.error.message)));
        else if (success) { fill(box, h('p', {class: 'alert ok'}, success(job))); done(job.result, job); }
        else {
          fill(box, h('p', {class: 'alert ok'}, job.phase === 'unchanged' ? 'This release was already connected; nothing changed.' : 'Laboratory connected: its release can be selected as a source for new work.'));
          toast(job.phase === 'unchanged' ? 'Release already connected' : 'Laboratory connected', 'ok');
          done(job.result, job);
        }
        resolve(job);
      };
      const poll = async () => {
        try { job = await get(`${jobs}/${job.id}`); } catch (e) { clearInterval(timer); fill(box, h('p', {class: 'alert bad'}, e.message)); return resolve(null); }
        show();
        if (job.done) finish();
      };
      start().then((started) => {
        job = started;
        show();
        if (job.done) return finish();
        timer = setInterval(poll, POLL_MS);
      }).catch((e) => { fill(box, h('p', {class: 'alert bad', role: 'alert'}, e.message)); resolve(null); });
    });
  }

  /** The connection of a read file in the background. */
  const connectJob = (token, box, done) => followJob({start: () => post(`/labs/files/${encodeURIComponent(token)}/connect`, {}), box, done});

  function fileCard(connected) {
    const input = h('input', {type: 'file', accept: '.tcelab', 'aria-label': 'Laboratory release file'});
    const shown = h('div', {});
    const read = btn('Read release file', async (ev) => {
      const file = input.files && input.files[0];
      if (!file) return fail(new Error('Choose a laboratory release file (.tcelab).'));
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const fd = new FormData();
        fd.append('release', file, file.name);
        fill(shown, inspectCard(await form('/labs/files', fd), connected));
      } catch (e) { fill(shown, h('p', {class: 'alert bad', role: 'alert'}, e.message)); } finally { self.disabled = false; }
    }, 'primary');
    return h('div', {class: 'stack'}, h('div', {class: 'card stack'}, h('h3', {}, 'Connect a laboratory from a file'),
      h('p', {class: 'small muted'}, 'Read a .tcelab release to review its author, equipment, materials and usage terms before connecting it.'),
      h('div', {class: 'row'}, App.filePick(input, 'Choose .tcelab file'), read)), shown);
  }

  // ---- the connected laboratories ------------------------------------------------------------------------------------------------

  const releaseLine = (cur) => `${cur.release_number != null ? `№ ${cur.release_number} · ` : ''}${releaseName(cur)}`;

  /** What a connected laboratory holds, under its line: the current release, its signature, terms and author, since when it is here. */
  function sourceDetails(s) {
    const cur = s.current;
    return h('div', {class: 'stack small'},
      cur ? h('p', {}, `${releaseLine(cur)} · ${countsText(cur.counts)}`) : h('p', {class: 'muted'}, 'No current release: files were removed.'),
      cur ? h('p', {}, verifiedPill(cur.verified), ` · terms: ${termsName(cur.terms)} · author: ${(cur.attribution || {}).name || '—'}`) : null,
      h('p', {class: 'muted'}, `connected ${when(s.connected_at)} · releases on this computer: ${s.kept} · withdrawals: ${s.withdrawals}`));
  }

  /** The connected laboratories, a line each (name, state, current release), «Open» at the end; the details under a line. */
  function connectedList(list) {
    return App.list({id: 'labs-sources', items: list, key: (s) => s.id,
      row: (s) => {
        const [status, tone] = STATUS[s.status] || [s.status, ''];
        return [h('span', {class: 'lab-name lst-text'}, s.name), pill(status, tone), s.release_withdrawn ? pill('release withdrawn by owner', 'bad') : null,
          h('span', {class: 'muted small'}, s.current ? releaseLine(s.current) : 'no current release')];
      },
      details: sourceDetails,
      actions: (s) => [btn('Open', () => go(`/labs?tab=sources&source=${s.id}`), 'primary btn-small')],
      search: (s) => s.name,
      filters: [{key: 'status', label: 'Status', options: Object.entries(STATUS).map(([k, [text]]) => [k, text]), test: (s, v) => s.status === v}],
      sorts: [['name', 'By name', (p, q) => String(p.name).localeCompare(String(q.name), 'en')], ['recent', 'Recently connected first', newest((s) => s.connected_at)]]}).el;
  }

  async function sourcesList() {
    const el = h('div', {class: 'stack'});
    async function show() {
      const list = await get('/labs/sources');
      const notices = h('div', {'aria-live': 'polite'});
      fill(el, notices, LabsCloud.updatesCard(list, show), list.length ? connectedList(list)
        : h('div', {class: 'card empty'}, h('h3', {}, 'No connected laboratories'), h('p', {class: 'muted'}, 'Connect a laboratory from the cloud catalog or a .tcelab file to use its colors and scales as sources for new work.')));
      LabsCloud.automaticNotices(show).then((node) => fill(notices, node)).catch(() => {});
    }
    await show();
    return h('div', {class: 'stack'}, fileCard(show), el);
  }

  // ---- one laboratory: releases, palettes, transfers -------------------------------------------------------------------------------

  function differencesDialog(release) {
    get(`/labs/releases/${encodeURIComponent(release.release_id)}/differences`).then((d) => {
      const rows = (part) => Object.entries(d[part] || {}).filter(([, n]) => n).map(([k, n]) => `${SECTION[k] || k}: ${n}`).join(' · ') || 'none';
      modal(`Release differences ${short(release.content_sha256)}`, h('div', {class: 'stack'},
        h('p', {class: 'small'}, d.against ? `Compared with release ${short(d.against)}:` : 'No previous release: all contents are new.'),
        facts([['Added', rows('added')], ['Changed', rows('changed')], ['Removed', rows('removed')], ['Withdrawals in release', d.withdrawn]])),
      [{label: 'Close', run: (m) => m.close()}]);
    }).catch(fail);
  }

  /** The releases of one laboratory, a line each, the newest first: when, its number and hash, whether it is the current one, withdrawn or
      removed; the signature and the works that use it under the line; «Differences» and «Remove files» at the end. */
  function releasesList(card, reload) {
    const created = (r) => r.created_at;
    const works = (r) => (r.works.length ? h('span', {}, r.works.map((w, i) => [i ? ', ' : null,
      link(w.mode === 'photo_work' ? `/photo-engraving?work=${w.plan_id}` : `/vector?plan=${w.plan_id}`, w.name)])) : 'no work uses it');
    return App.list({id: 'labs-releases', items: card.releases, key: (r) => r.release_id, empty: 'No releases',
      row: (r) => [h('span', {}, when(r.created_at)), h('span', {class: 'muted'}, r.release_number == null ? '№ —' : `№ ${r.release_number}`),
        h('span', {class: 'lst-text muted small'}, short(r.content_sha256)), card.current && card.current.release_id === r.release_id ? pill('current', 'ok') : null,
        r.withdrawn ? pill('withdrawn', 'bad') : null, r.status === 'removed' ? pill('files removed', '') : null, r.works.length ? pill(`works: ${r.works.length}`) : null],
      details: (r) => facts([['Hash', r.content_sha256], ['Signature', verifiedPill(r.verified)], ['Files', r.status === 'removed' ? 'removed' : 'on this computer'], ['Works', works(r)]]),
      actions: (r) => [btn('Differences', () => differencesDialog(r), 'btn-small'),
        r.status === 'removed' ? null : btn('Remove files', () => confirmBox(`Remove the files for release ${short(r.content_sha256)}?`,
          'The release record remains, but its files are removed from this computer. A release cannot be removed while a saved work uses it.',
          'Remove', async () => { await del(`/labs/releases/${encodeURIComponent(r.release_id)}`); toast('Release files removed', 'ok'); reload(); }), 'danger btn-small')],
      filters: [{key: 'files', label: 'Files', options: [['kept', 'on this computer'], ['removed', 'files removed']], test: (r, v) => (r.status === 'removed') === (v === 'removed')}],
      sorts: [['new', 'Newest first', newest(created)], ['old', 'Oldest first', oldest(created)]]}).el;
  }

  function withdrawalsTable(list) {
    return table(['Declared', 'Target', 'Identifier', 'Reason', 'Replacement', 'Learned'], list.map((w) => [when(w.declared_at), TARGET[w.target_kind] || w.target_kind,
      short(w.target_id), w.reason, w.replacement_release_id ? short(w.replacement_release_id) : '—', `${when(w.learned_at)} · ${short(w.learned_from)}`]), 'No withdrawals', true);
  }

  /** «Test in your workshop»: a test plate of one colour of the release on the own laser for the own titanium (POST /labs/transfers). */
  async function transferDialog(request, entry, made) {
    const [devices, stocks] = await Promise.all([get('/devices'), MaterialPicker.total()]);       // only whether any record exists, not all of them
    if (!devices.length || !stocks) throw new Error('First add a laser and titanium stock for this workshop');
    const laser = h('select', {'aria-label': 'Your laser'}, devices.map((d) => h('option', {value: d.id}, d.title || d.name)));
    const stock = MaterialPicker.create({initial: 'recent', name: 'Your titanium'});          // the record used last, or another found by a search (ux-growing-collections-p0, REQ-001)
    modal('Test color in your workshop', h('div', {class: 'stack'},
      h('p', {}, swatch(entry.lab), labText(entry.lab), h('span', {class: 'small muted'}, ` · ${recipeText(entry.recipe)}`)),
      h('p', {class: 'small'}, 'The release recipe is engraved in one cell on your laser with its currently installed lens; settings your laser cannot execute '
        + 'are rejected rather than adjusted. The plate photo is measured as your experiment and compared with the release color by ΔE; it does not change the release statistics.'),
      h('div', {class: 'grid g2'}, field('Your laser', laser), field('Your titanium', stock))), [
      {label: 'Cancel', run: (m) => m.close()},
      {label: 'Create plate', cls: 'primary', run: async (m) => {
        if (!stock.value) throw new Error('Select your titanium: a specific batch or sheet');
        const plate = await post('/labs/transfers', {...request, entry_id: entry.id, device_id: +laser.value, material_id: +stock.value});
        toast('Transfer plate created', 'ok');
        m.close();
        made(plate);
      }}]);
  }

  /** The colours of fill of a setup, a line each (colour, basis, engravings, agreement, recipe), «Test in your workshop» at the end; in the
      release's order or by lightness or engravings, by basis and concern, twenty at a time. */
  function paletteList(request, offered, made) {
    const lightness = (e) => (e.lab ? +e.lab[0] : 0);
    const colours = offered.entries.length ? App.list({items: offered.entries, key: (e) => e.id, className: 'lab-colours',
      row: (e) => [swatch(e.lab), h('strong', {}, labText(e.lab)), pill(BASIS[e.basis] || e.basis || '—'),
        pill(`engravings ${e.engravings}`), pill(agreed(e.agreement), e.caution || (e.agreement && e.agreement.differing) ? 'warn' : 'ok'),
        e.caution ? pill(CAUTION[e.caution] || e.caution, 'warn') : null, h('span', {class: 'lst-text small muted'}, recipeText(e.recipe))],
      actions: (e) => [btn('Test in your workshop', () => transferDialog(request, e, made).catch(fail), 'btn-small')],
      filters: [{key: 'basis', label: 'Measurement basis', options: Object.entries(BASIS), test: (e, v) => e.basis === v},
        {key: 'caution', label: 'Cautions', options: [['none', 'without cautions'], ['some', 'with caution']], test: (e, v) => !e.caution === (v === 'none')}],
      sorts: [['release', 'Release order'], ['light', 'Lightest first', (p, q) => lightness(q) - lightness(p)], ['dark', 'Darkest first', (p, q) => lightness(p) - lightness(q)],
        ['engravings', 'Most engravings', (p, q) => (q.engravings || 0) - (p.engravings || 0)]]}).el : null;
    return h('div', {class: 'stack'},
      h('p', {class: 'small'}, `Fill colors: ${offered.entries.length}` + (offered.conditions && offered.conditions.length ? '. ' + offered.conditions.map((c) => I18N.tr(c)).join(' ') : '')),
      colours || h('p', {class: 'muted small'}, 'No fill colors for this setup in the release.'));
  }

  function scalesList(offered) {
    const scales = offered.scales || [];
    return h('div', {class: 'stack'}, h('p', {class: 'small'}, `Grayscale scales: ${scales.length}`),
      scales.length ? h('ul', {class: 'stack small'}, scales.map((sc) => h('li', {}, PhotoPanels.settingsText(sc.mode, sc.dpi),
        sc.span ? ` · ${num(sc.span[0], 1)}–${num(sc.span[1], 1)} %` : '', sc.size && sc.size.measured_mm ? ` · width ${sc.size.measured_mm.map((v) => num(v, 1)).join(', ')} mm` : '',
        sc.material ? ` · ${[sc.material.family, sc.material.grade].filter(Boolean).join(' ')}` : ''))) : null);
  }

  function setupBlock(choice, setup, made) {
    const request = {release_id: choice.release.release_id, laser: setup.laser.uuid, lens: setup.lens ? setup.lens.uuid : null, material: setup.material ? setup.material.uuid : null};
    const out = h('div', {});
    const palette = setup.material ? btn('Palette', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { fill(out, paletteList(request, await post('/labs/palette', request), made)); } catch (e) { fill(out, h('p', {class: 'alert bad'}, e.message)); } finally { self.disabled = false; }
    }, 'btn-small') : null;
    const scales = btn('Grayscale scales', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { fill(out, scalesList(await post('/labs/scales', {release_id: request.release_id, laser: request.laser, lens: request.lens}))); }
      catch (e) { fill(out, h('p', {class: 'alert bad'}, e.message)); } finally { self.disabled = false; }
    }, 'btn-small');
    return h('div', {class: 'card stack lab-setup-card'}, h('div', {class: 'row'}, h('strong', {}, setupName(setup)), pill(`photos ${setup.photographs}`), h('span', {class: 'spacer'}), palette, scales), out);
  }

  /** The transfer plates made from a release, a line each (the release's colour, the plate, the measured ΔE), the newest first; the recipe,
      the own titanium and every measurement under the line; the plate at the end. */
  function transfersList(list) {
    const measured = (t) => t.measurements.length > 0;
    return App.list({id: 'labs-transfers', items: list, key: (t) => t.plan_id,
      row: (t) => [swatch(t.source.lab), h('span', {class: 'lst-text'}, `${t.name} · ${t.identifier}`),
        measured(t) ? pill(`measurements ${t.measurements.length} · mean ΔE ${num(t.mean_delta_e, 1)}`, t.mean_delta_e <= 5 ? 'ok' : 'warn') : pill('awaiting photo', 'warn'),
        h('span', {class: 'muted small'}, day(t.created_at))],
      details: (t) => h('div', {class: 'stack small'},
        h('p', {}, `release color ${labText(t.source.lab)} · ${[t.own_material.name, t.own_material.grade].filter(Boolean).join(' · ')} · ${when(t.created_at)}`),
        h('p', {class: 'muted'}, recipeText(t.recipe)),
        measured(t) ? h('p', {}, t.measurements.map((m, i) => [i ? ' · ' : null, swatch(m.lab), link(`/analysis/${m.pair_id}`, `ΔE ${num(m.delta_e, 1)}`), ` (${day(m.measured_at)})`]))
          : h('p', {class: 'muted'}, 'The plate photo has not yet been accepted: engrave it and add a photo in Experiments.')),
      actions: (t) => [h('a', {class: 'btn btn-small', href: `#/plans/${t.plan_id}`}, 'Open')],
      filters: [{key: 'measured', label: 'Measured', options: [['yes', 'measured'], ['no', 'awaiting photo']], test: (t, v) => measured(t) === (v === 'yes')}],
      sorts: [['new', 'Newest first', newest((t) => t.created_at)], ['delta', 'Largest ΔE first', (p, q) => (q.mean_delta_e ?? -1) - (p.mean_delta_e ?? -1)]]}).el;
  }

  async function transfersBlock(releaseId) {
    const el = h('div', {class: 'stack'});
    const notice = h('div', {});
    async function show() {
      let list;
      try { list = await get(`/labs/transfers?release_id=${encodeURIComponent(releaseId)}`); } catch (e) { return fill(el, h('p', {class: 'alert bad'}, e.message)); }
      fill(el, list.length ? transfersList(list) : h('p', {class: 'muted small'}, 'No transfers from this release yet.'));
    }
    await show();
    return {el: h('div', {class: 'stack'}, notice, el), made: (plate) => {
      fill(notice, h('p', {class: 'alert ok'}, 'Transfer plate created: ', link(`/plans/${plate.plan_id}`, plate.name || `plan ${plate.plan_id}`), '. Engrave it and add a photo.'));
      show();
    }};
  }

  async function sourceScreen(id) {
    const [card, choices] = await Promise.all([get(`/labs/sources/${id}`), get('/labs/choices').catch(() => [])]);
    const lab = card.lab || {}, cur = card.current, [status, tone] = STATUS[card.status] || [card.status, ''];
    const reload = () => App.render({preserveScroll: true});
    const toggle = card.status === 'connected'
      ? btn('Disconnect', () => confirmBox(`Disconnect laboratory “${card.name}”?`, 'It will no longer be offered as a source for new work; its releases remain available to work that uses them.',
        'Disconnect', async () => { await post(`/labs/sources/${id}/disconnect`, {}); toast('Laboratory disconnected', 'ok'); reload(); }), 'danger btn-small')
      : btn('Reconnect', async () => { try { await post(`/labs/sources/${id}/reconnect`, {}); toast('Laboratory reconnected', 'ok'); reload(); } catch (e) { fail(e); } }, 'primary btn-small');
    const choice = choices.find((c) => c.source_id === card.id) || null;
    const transfers = cur ? await transfersBlock(cur.release_id) : null;
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('a', {class: 'btn btn-small', href: '#/labs?tab=sources'}, '← Connected laboratories'),
        h('div', {}, h('h2', {}, h('span', {class: 'lab-name'}, card.name), ' ', pill(status, tone)),
          h('p', {class: 'sub'}, [lab.description, cur ? `author: ${(cur.attribution || {}).name || '—'}` : null, lab.url ? `URL: ${lab.url}` : null].filter(Boolean).join(' · '))),
        h('span', {class: 'spacer'}), toggle),
      LabsCloud.sourceCard(card, reload),
      h('div', {class: 'card stack'}, h('h3', {}, 'Releases'), releasesList(card, reload)),
      h('div', {class: 'card stack'}, h('h3', {}, 'Laboratory withdrawals'), withdrawalsTable(card.withdrawal_list || [])),
      h('div', {class: 'card stack'}, h('h3', {}, 'Palette and scales of the current release'),
        choice ? h('div', {class: 'stack'}, h('p', {class: 'small muted'}, 'Each setup measured in the release: its fill colors with recipes and grayscale scales. Each color shows Lab and its measurement basis; '
          + 'the on-screen color is only a display. “Test in your workshop” engraves the recipe on your laser.'),
          choice.setups.map((s) => setupBlock(choice, s, transfers ? transfers.made : () => {})))
          : h('p', {class: 'muted small'}, 'This laboratory is not offered as a source for new work: it is disconnected, or its release was withdrawn or removed.')),
      transfers ? h('div', {class: 'card stack'}, h('h3', {}, 'Tested in your workshop'), transfers.el) : null);
  }

  // ---- the screen ------------------------------------------------------------------------------------------------------------------

  App.register({id: 'labs', async render(ctx) {
    if (ctx.query.source) return sourceScreen(encodeURIComponent(ctx.query.source));
    const loaders = {own: ownTab, sources: sourcesList, catalogue: LabsCloud.catalogueTab};
    const boxes = Object.fromEntries(Object.keys(loaders).map((id) => [id, h('div', {'aria-live': 'polite'})]));
    const state = {};
    function load(id) {
      if (state[id]) return; // Includes an in-flight request; switching tabs does not start it twice.
      state[id] = 'loading';
      fill(boxes[id], h('p', {role: 'status'}, 'Loading…'));
      loaders[id]().then((node) => { state[id] = 'ready'; fill(boxes[id], node); }).catch((e) => {
        state[id] = null;
        fill(boxes[id], h('div', {class: 'alert bad', role: 'alert'}, h('p', {}, e.message), btn('Retry', () => load(id))));
      });
    }
    const tabs = App.tabs([['own', 'My laboratory', boxes.own], ['sources', 'Connected laboratories', boxes.sources], ['catalogue', 'Laboratory catalog', boxes.catalogue]],
      {initial: ['sources', 'catalogue'].includes(ctx.query.tab) ? ctx.query.tab : 'own', remember: ctx.query.tab ? null : 'labs.tab', label: 'Laboratories', prefix: 'labs-tab', onSelect: load});
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Laboratories'),
        h('p', {class: 'sub'}, 'Portable results: publish your laboratory as a .tcelab file or to the cloud, and connect other workshops’ releases from the cloud catalog or a file '
          + 'as measurement sources for new work.'))),
      tabs.list, h('div', {class: 'labs-panels'}, tabs.panels));
  }});

  LabsCloud.install({followJob, previewBody, countsText, termsName, differencesDialog, inspectCard, mb});
})();
