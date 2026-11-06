/* Laboratory cloud sign-in, publishing, invitations, catalogue, and update checks. */
'use strict';
(() => {
  const {h, fill, btn, field, link, pill, get, post, del, toast, fail, confirmBox, facts, table} = App;
  const {short, day, when} = LabSource;
  const ACCOUNT_POLL_MS = 1000;
  const VISIBILITY = {public: 'Public', private: 'Private'};
  const STATE = {reserved: 'reserved', exported: 'release saved', uploading: 'uploading', finalized: 'published', failed: 'incomplete'};
  const PUBLISH_PHASE = {waiting: 'waiting', reserving: 'reserving in the cloud', exporting: 'saving release', uploading: 'uploading to the cloud',
    finalizing: 'finishing', done: 'published', failed: 'not published', cancelled: 'canceled'};
  const UPDATE_CHECKS = {manual: 'manual', auto: 'automatic (when enabled on the Network screen)'};
  let shared = null;                 // labs.js: {followJob, previewBody, countsText, termsName, differencesDialog, mb}
  const accountText = (a) => (a ? [a.name, a.email].filter(Boolean).join(' · ') : '');
  const releaseLine = (r) => `#${r.number} from ${day(r.created_at)} · ${short(r.content_sha256)}`;
  // the orders of the short lists (DEC-090): by an ISO date, the newest or the oldest first
  const newest = (at) => (p, q) => String(at(q) || '').localeCompare(String(at(p) || ''));
  const oldest = (at) => (p, q) => String(at(p) || '').localeCompare(String(at(q) || ''));

  // ---- the sign-in ---------------------------------------------------------------------------------------------------------------

  /** Open the sign-in page and poll for the account while this attempt remains active. */
  function signInButton(done) {
    const note = h('span', {class: 'small muted cloud-signin-note', role: 'status', 'aria-live': 'polite'});
    let timer = null, state = null, attempt = 0;
    const stop = () => { if (timer) { clearInterval(timer); timer = null; } };
    const cancel = btn('Cancel sign-in', async () => {
      const canceledState = state;
      state = null;
      ++attempt;
      stop(); button.disabled = false; cancel.hidden = true; fill(note, 'Sign-in canceled. Select Sign in to try again.');
      if (canceledState) try { await post('/cloud/signin/cancel', {state: canceledState}); } catch (_) { /* The pending state may already have expired. */ }
    }, 'btn-small');
    cancel.hidden = true;
    const button = btn('Sign in', async (ev) => {
      const self = ev.currentTarget;
      const mine = ++attempt;
      self.disabled = true;
      cancel.hidden = false;
      fill(note, 'Starting sign-in…');
      try {
        const started = await post('/cloud/signin', {});
        if (mine !== attempt) { try { await post('/cloud/signin/cancel', {state: started.state}); } catch (_) {} return; }
        state = started.state;
        const opened = window.open(started.url, '_blank', 'noopener');
        fill(note, 'Complete sign-in in your browser, then return here. ',
          opened ? null : h('a', {href: started.url, target: '_blank', rel: 'noopener'}, 'Open sign-in page'));
        const until = Date.now() + (started.expires_in_s || 600) * 1000;
        let checking = false;
        timer = setInterval(async () => {
          if (mine !== attempt || checking) return;
          checking = true;
          try {
            const account = await get('/cloud/account');
            if (mine !== attempt) return;
            if (account.signed_in) { ++attempt; stop(); fill(note, 'Signed in. Returning to your task…'); toast('Signed in to the cloud', 'ok'); done(account); }
            else if (Date.now() > until) { ++attempt; stop(); self.disabled = false; cancel.hidden = true; fill(note, 'Sign-in did not finish before the timeout. Select Sign in to try again.'); }
          } catch (e) { if (mine !== attempt) return; ++attempt; stop(); self.disabled = false; cancel.hidden = true; fill(note, `Sign-in could not be checked: ${e.message}. Select Sign in to try again.`); }
          finally { checking = false; }
        }, ACCOUNT_POLL_MS);
      } catch (e) { if (mine === attempt) { self.disabled = false; cancel.hidden = true; fill(note, `Could not start sign-in: ${e.message}. Select Sign in to try again.`); } }
    }, 'primary');
    return h('span', {class: 'row cloud-signin'}, button, cancel, note);
  }

  function accountRow(own, reload) {
    if (!own.switched_on) return h('p', {class: 'alert warn'}, 'Cloud access is disabled in this workshop’s network settings. The catalog, publishing and invitations are unavailable. ', link('/network', 'Open network settings'));
    if (!own.signed_in) {
      return h('div', {class: 'row'}, h('span', {class: 'small'}, 'You are signed out. Sign in to publish releases, invite members and access private laboratories. '
        + 'The public catalog is available without signing in.'), h('span', {class: 'spacer'}), signInButton(reload));
    }
    const out = btn('Sign out', () => confirmBox('Sign out of the cloud?', 'Published releases remain in the cloud, and connected laboratories continue to work here.', 'Sign out',
      async () => { await post('/cloud/signout', {}); toast('Signed out of the cloud', 'ok'); reload(); }), 'btn-small');
    return h('div', {class: 'row'}, h('span', {}, 'Signed in as ', h('strong', {class: 'cloud-account'}, accountText(own.account))),
      h('span', {class: 'small muted'}, `Cloud: ${own.api_url}`), h('span', {class: 'spacer'}), out);
  }

  // ---- cloud on My laboratory ----------------------------------------------------------------------------------------------

  function publishBlock(own, terms, reload) {
    const termsSelect = h('select', {}, terms.map((t) => h('option', {value: t.id}, `${shared.termsName(t)} — ${(t.summary && t.summary.en) || ''}`)));
    const visibility = h('select', {}, Object.entries(VISIBILITY).map(([id, name]) => h('option', {value: id}, name)));
    const out = h('div', {class: 'stack'}), progress = h('div', {class: 'stack', hidden: true});
    let ready = false;
    const prepare = btn('Prepare publication', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { const p = await post('/labs/own/preview', {selection: null}); ready = p.ready; publish.disabled = !ready; fill(out, shared.previewBody(p)); }
      catch (e) { fill(out, h('p', {class: 'alert bad'}, e.message)); } finally { self.disabled = false; }
    });
    const publish = btn('Publish to cloud', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true; prepare.disabled = true;
      await shared.followJob({start: () => post('/cloud/publish', {terms: termsSelect.value, visibility: visibility.value}), jobs: '/cloud/jobs', box: progress,
        label: 'Publishing release', phases: PUBLISH_PHASE, success: (job) => `Published release #${job.result.release.number} · ${shared.countsText(job.result.release.counts)}.`,
        done: (result) => { toast(`Release #${result.release.number} published to the cloud`, 'ok'); reload(); }});
      prepare.disabled = false; self.disabled = !ready;
    }, 'primary', true);
    return h('div', {class: 'stack cloud-publish'}, h('h4', {}, 'Publish to cloud'),
      h('p', {class: 'small muted'}, 'The same .tcelab release is sent to the cloud and kept locally. Review its contents first. '
        + (own.lab ? `This laboratory is ${VISIBILITY[own.lab.visibility] || own.lab.visibility}; visibility is selected during the first publication.`
          : 'Choose visibility during the first publication: public laboratories are visible to everyone, private ones only to invited members.')),
      h('div', {class: 'row'}, prepare, field('Cloud usage terms', termsSelect, null, {required: true}),
        own.lab ? null : field('Visibility', visibility, null, {required: true}), publish), out, progress);
  }

  function pendingBlock(p, reload) {
    const progress = h('div', {class: 'stack', hidden: true});
    const retry = btn('Continue publication', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      await shared.followJob({start: () => post('/cloud/publish/retry', {}), jobs: '/cloud/jobs', box: progress, label: 'Publishing release', phases: PUBLISH_PHASE,
        success: (job) => `Published release #${job.result.release.number}.`, done: () => { toast('Release published to the cloud', 'ok'); reload(); }});
      self.disabled = false;
    }, 'primary btn-small');
    const giveUp = btn('Abandon publication', () => confirmBox('Abandon publication?', 'The unfinished publication will be marked failed; nothing will appear in the cloud. '
      + 'The saved release file remains on this computer.', 'Abandon publication', async () => { await post('/cloud/publish/abandon', {}); toast('Publication canceled', 'ok'); reload(); }), 'danger btn-small');
    return h('div', {class: 'alert warn stack cloud-pending'},
      h('p', {}, `The publication started ${when(p.created_at)} is incomplete (${STATE[p.state] || p.state}${p.error ? `: ${I18N.tr(p.error)}` : ''}). `
        + 'Continue from the same point; this will not create a duplicate release.'),
      h('div', {class: 'row'}, retry, giveUp), progress);
  }

  function invitationsBlock(own, reload) {
    const made = h('div', {});
    const invite = btn('Create invitation', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const inv = await post('/cloud/invitations', {});
        fill(made, h('p', {class: 'alert ok stack'}, h('span', {}, `Invitation created, valid until ${when(inv.expires_at)}. Give the link to the recipient; it is shown only now.`),
          h('code', {class: 'cloud-link'}, inv.link)));
        toast('Invitation created', 'ok');
      } catch (e) { fail(e); } finally { self.disabled = false; }
    }, 'btn-small');
    // every invitation stays listed (accepted, revoked or waiting) and members come and go: both are short lists, the newest first
    const state = (i) => (i.revoked_at ? 'revoked' : i.accepted_by ? 'accepted' : 'waiting');
    const invitations = own.invitations.length ? App.list({id: 'cloud-invitations', items: own.invitations, key: (i) => i.id,
      row: (i) => [h('span', {}, when(i.created_at)), h('span', {class: 'muted small'}, `valid until ${when(i.expires_at)}`),
        i.revoked_at ? pill('revoked', 'bad') : i.accepted_by ? [pill('accepted', 'ok'), h('span', {class: 'small cloud-account lst-text'}, i.accepted_by)] : pill('waiting')],
      actions: (i) => [i.revoked_at || i.accepted_by ? null : btn('Revoke', () => confirmBox('Revoke invitation?', 'The link will stop working.', 'Revoke',
        async () => { await del(`/cloud/invitations/${encodeURIComponent(i.id)}`); toast('Invitation revoked', 'ok'); reload(); }), 'danger btn-small')],
      filters: [{key: 'state', label: 'Invitation status', options: [['waiting', 'waiting'], ['accepted', 'accepted'], ['revoked', 'revoked']], test: (i, v) => state(i) === v}],
      sorts: [['new', 'Newest first', newest((i) => i.created_at)], ['old', 'Oldest first', oldest((i) => i.created_at)]]}).el
      : h('p', {class: 'muted'}, 'No invitations');
    const members = own.members.length ? App.list({id: 'cloud-members', items: own.members, key: (m) => m.account_id,
      row: (m) => [h('span', {class: 'cloud-account lst-text'}, m.account_id), h('span', {class: 'muted small'}, `since ${when(m.created_at)}`)],
      actions: (m) => [btn('Remove', () => confirmBox('Remove member?', 'They will lose access to the private laboratory and its releases; releases already connected remain with them.',
        'Remove', async () => { await del(`/cloud/members/${encodeURIComponent(m.account_id)}`); toast('Member removed', 'ok'); reload(); }), 'danger btn-small')],
      search: (m) => m.account_id,
      sorts: [['new', 'Newest first', newest((m) => m.created_at)], ['old', 'Oldest first', oldest((m) => m.created_at)]]}).el
      : h('p', {class: 'muted'}, 'No members');
    return h('div', {class: 'stack'}, h('h4', {}, 'Invitations and members'),
      h('p', {class: 'small muted'}, own.lab.visibility === 'private' ? 'Only invitees can see a private laboratory. An invitation link is single-use and time-limited.'
        : 'A public laboratory is visible without an invitation. An invitation can still add it to the recipient’s laboratories.'),
      h('div', {class: 'row'}, invite), made,
      h('p', {class: 'small'}, h('strong', {}, 'Invitations')), invitations,
      h('p', {class: 'small'}, h('strong', {}, 'Members')), members);
  }

  function labBlock(own, reload) {
    const lab = own.lab;
    return h('div', {class: 'stack'}, h('h4', {}, 'Laboratory in cloud: ', h('span', {class: 'lab-name'}, lab.name), ' ', pill(VISIBILITY[lab.visibility] || lab.visibility)),
      own.releases.length ? App.list({id: 'cloud-releases', items: own.releases, key: (r) => r.id || r.number,
        row: (r) => [h('span', {}, `#${r.number}`), h('span', {class: 'muted'}, when(r.published_at)), h('span', {class: 'lst-text small'}, shared.countsText(r.counts)),
          h('span', {class: 'muted small'}, shared.termsName(r.usage_terms)), h('span', {class: 'muted small'}, shared.mb(r.byte_size))],
        sorts: [['new', 'Newest first', (p, q) => q.number - p.number], ['old', 'Oldest first', (p, q) => p.number - q.number]]}).el
        : h('p', {class: 'muted'}, 'No releases in the cloud yet'),
      invitationsBlock(own, reload));
  }

  function publicationsTable(list) {
    const rows = list.filter((p) => p.state !== 'finalized').map((p) => [when(p.created_at), STATE[p.state] || p.state, p.release_number == null ? '—' : String(p.release_number),
      p.error ? I18N.tr(p.error) : '—']);
    return rows.length ? h('details', {class: 'small'}, h('summary', {}, 'Incomplete and failed publications'), table(['Started', 'Status', '#', 'Reason'], rows, '', true)) : null;
  }

  /** The cloud card of My laboratory: /cloud/own is asked here, apart from /labs/own, so that the cloud's silence never hides the rest. */
  async function ownCard(terms, reload) {
    const el = h('div', {class: 'card stack cloud-own'}, h('h3', {}, 'Laboratory cloud'));
    let own;
    try { own = await get('/cloud/own'); } catch (e) { return fill(el, h('h3', {}, 'Laboratory cloud'), h('p', {class: 'alert bad', role: 'alert'}, e.message)); }
    const parts = [h('h3', {}, 'Laboratory cloud'),
      h('p', {class: 'small muted'}, 'The cloud catalog lets workshops connect published laboratory releases and discover updates. '
        + 'The application contacts it when you sign in, publish or check for updates.'),
      accountRow(own, reload)];
    if (!own.signed_in && own.pending) parts.push(h('p', {class: 'alert warn cloud-pending-signed-out'},
      `A publication is unfinished. ${own.switched_on ? 'Sign in' : 'Enable cloud access and sign in'} to continue the same publication; no new release will be created automatically.`));
    if (own.signed_in && own.switched_on) {
      if (own.pending) parts.push(pendingBlock(own.pending, reload));
      else parts.push(publishBlock(own, terms, reload));
      if (own.lab) parts.push(labBlock(own, reload));
      parts.push(publicationsTable(own.publications || []));
    }
    return fill(el, parts);
  }

  // ---- laboratory catalogue -------------------------------------------------------------------------------------------------------

  function connectButton(latest, connected, label, progress, reload) {
    return btn(label, async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      await shared.followJob({start: () => post(`/cloud/releases/${encodeURIComponent(latest.id)}/review`, {}), jobs: '/cloud/jobs', box: progress,
        label: 'Reviewing release', success: () => 'Release ready for review.', done: (info) => {
          const token = encodeURIComponent(info.token);
          fill(progress, shared.inspectCard(info, (result) => {
            if (connected && result && result.current && !result.unchanged) shared.differencesDialog(result.current);
            reload();
          }, {start: () => post(`/cloud/reviews/${token}/connect`, {}), jobs: '/cloud/jobs',
            discard: () => del(`/cloud/reviews/${token}`)}));
        }});
      self.disabled = false;
    }, 'primary btn-small');
  }

  /** What a laboratory of the catalogue says of itself, under its line: author, description, link, the latest release, what is here. */
  function labDetails(lab) {
    const latest = lab.latest_release, c = lab.connected;
    return h('div', {class: 'stack'},
      facts([['Author', lab.author], ['Description', lab.description], ['Link', lab.url ? h('span', {class: 'lab-url'}, lab.url) : null],
        ['Release', latest ? releaseLine(latest) : 'no releases yet'], ['Contents', latest ? shared.countsText(latest.counts) : null],
        ['Terms', latest ? shared.termsName(latest.usage_terms) : null], ['Size', latest ? shared.mb(latest.byte_size) : null],
        ['Your connection', c ? `${c.status === 'connected' ? 'connected' : 'disconnected'}${c.current_release_number == null ? '' : `, release #${c.current_release_number}`}` : null]]),
      lab.own ? h('p', {class: 'small muted'}, 'This laboratory’s results are already here: they are releases from your workshop.') : null);
  }

  /** The catalogue, a laboratory a line (name, visibility, whether it is the own one or connected here, its latest release), Connect
      (and Open when it is connected) at the end; a connection goes into ``progress``, which outlives the redraw after it. */
  function catalogueList(labs, progress, reload) {
    return App.list({id: 'labs-catalogue', items: labs, key: (lab) => lab.id,
      row: (lab) => {
        const latest = lab.latest_release, c = lab.connected;
        return [h('span', {class: 'lab-name lst-text'}, lab.name), pill(VISIBILITY[lab.visibility] || lab.visibility), lab.own ? pill('your laboratory', 'ok') : null,
          c ? pill(c.status === 'connected' ? 'connected' : 'disconnected', c.status === 'connected' ? 'ok' : 'warn') : null, c && c.newer ? pill('new release available', 'warn') : null,
          h('span', {class: 'muted small'}, latest ? releaseLine(latest) : 'no releases yet')];
      },
      details: labDetails,
      actions: (lab) => {
        const latest = lab.latest_release, c = lab.connected;
        if (!latest || lab.own) return [];
        return [connectButton(latest, c, c ? (c.newer ? `Review release #${latest.number}` : 'Review release again') : 'Review release', progress, reload),
          c ? btn('Open', () => App.go(`/labs?tab=sources&source=${c.source_id}`), 'btn-small') : null];
      },
      search: (lab) => [lab.name, lab.author, lab.description].filter(Boolean).join(' '),
      filters: [{key: 'here', label: 'Your connection', options: [['connected', 'connected'], ['new', 'not connected']],
        test: (lab, v) => (v === 'connected' ? !!lab.connected : !lab.connected && !lab.own)},
      {key: 'visibility', label: 'Visibility', options: Object.entries(VISIBILITY), test: (lab, v) => lab.visibility === v}],
      sorts: [['catalogue', 'Catalogue order'], ['name', 'By name', (p, q) => String(p.name).localeCompare(String(q.name), 'en')],
        ['recent', 'Newest releases first', newest((lab) => (lab.latest_release || {}).created_at)]]}).el;
  }

  function acceptBlock(signedIn, reload) {
    const form = Forms.create();
    const link = form.add('link', 'Invitation link', h('input', {placeholder: 'invitation link'}), {required: true, raw: true,
      help: 'link provided by the private laboratory owner'});
    const accept = btn('Accept invitation', async (ev) => {
      const self = ev.currentTarget;
      const v = form.collect();
      if (!v) return;
      self.disabled = true;
      try {
        const got = await post('/cloud/invitations/accept', {link: v.link});
        toast(`Invitation accepted: ${got.lab.name}`, 'ok');
        reload();
      } catch (e) { form.fail(e); } finally { self.disabled = false; }
    }, 'btn-small');
    return h('div', {class: 'card stack cloud-accept'}, h('h3', {}, 'Private laboratories'),
      h('p', {class: 'small muted'}, signedIn ? 'A private laboratory appears in the catalogue after an invitation. Paste the link provided by its owner.'
        : 'To see private laboratories and accept invitations, sign in to the cloud on the My laboratory tab.'),
      signedIn ? h('div', {class: 'toolbar'}, link, accept) : null, signedIn ? form.error : null);
  }

  async function catalogueTab() {
    const el = h('div', {class: 'stack'});
    const progress = h('div', {class: 'stack cloud-progress', hidden: true});        // the same node in every redraw: a connection's end stays shown
    async function show() {
      let cat;
      try { cat = await get('/cloud/catalogue'); } catch (e) { return fill(el, h('div', {class: 'card'}, h('p', {class: 'alert bad', role: 'alert'}, e.message), btn('Retry', show))); }
      fill(el, h('p', {class: 'small muted'}, `Cloud: ${cat.api_url}` + (cat.signed_in ? '' : ' · only public laboratories are shown while signed out')),
        progress, cat.labs.length ? catalogueList(cat.labs, progress, show)
          : h('div', {class: 'card empty'}, h('h3', {}, 'No laboratories in the catalogue yet'), h('p', {class: 'muted'}, 'Published releases appear here; private laboratories appear after an invitation.')),
        acceptBlock(cat.signed_in, show));
    }
    await show();
    return el;
  }

  // ---- updates of the laboratories connected from the cloud --------------------------------------------------------------------------

  function resultsList(results, reload) {
    if (!results.length) return h('p', {class: 'muted small'}, 'No cloud laboratories to check.');
    return h('ul', {class: 'stack small cloud-updates'}, results.map((r) => {
      const progress = h('div', {class: 'stack', hidden: true});
      const text = r.error ? h('span', {class: 'bad'}, I18N.tr(r.error)) : !r.found ? 'no longer listed in the cloud'
        : r.newer ? `new release #${r.latest.number} from ${day(r.latest.created_at)} · ${shared.countsText(r.latest.counts)}`
          : `no newer release${r.current_release_number == null ? '' : ` (current #${r.current_release_number})`}`;
      return h('li', {class: 'stack'}, h('div', {class: 'row'}, h('span', {class: 'lab-name'}, r.name), ' — ', text,
        r.newer ? connectButton(r.latest, {source_id: r.source_id}, 'Review release', progress, reload) : null), progress);
    }));
  }

  /** The card of Connected laboratories with Check updates (shown when a laboratory came from the cloud). */
  function updatesCard(sources, reload) {
    const cloud = sources.filter((s) => s.origin === 'cloud');
    if (!cloud.length) return null;
    const out = h('div', {class: 'stack'});
    const check = btn('Check updates', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { fill(out, resultsList(await post('/cloud/updates/check', {}), reload)); }
      catch (e) { fill(out, h('p', {class: 'alert bad', role: 'alert'}, e.message)); } finally { self.disabled = false; }
    }, 'btn-small');
    return h('div', {class: 'card stack cloud-updates-card'}, h('h3', {}, 'Cloud updates'),
      h('p', {class: 'small muted'}, `Cloud-connected laboratories: ${cloud.length}. Checking asks the cloud about new releases and does not connect anything automatically. `
        + 'Automatic checks run only for laboratories configured for them and when update checks are enabled on the Network screen.'),
      h('div', {class: 'row'}, check), out);
  }

  /** The automatic checks the server finds due (none unless both settings allow): a notice per laboratory with a newer release. */
  async function automaticNotices(reload) {
    let due;
    try { due = await post('/cloud/updates/automatic', {}); } catch (_) { return null; }
    const newer = (due || []).filter((r) => r.newer);
    return newer.length ? h('div', {class: 'alert stack cloud-auto'}, newer.map((r) => {
      const progress = h('div', {class: 'stack', hidden: true});
      return h('div', {class: 'stack'}, h('div', {class: 'row'}, h('span', {}, 'A new cloud release is available for “', h('span', {class: 'lab-name'}, r.name), `”: #${r.latest.number} from ${day(r.latest.created_at)}.`),
        connectButton(r.latest, {source_id: r.source_id}, 'Review release', progress, reload)), progress);
    })) : null;
  }

  /** On the card of one laboratory connected from the cloud: the check by the button and how it is checked by itself. */
  function sourceCard(card, reload) {
    if (card.origin !== 'cloud') return null;
    const mode = h('select', {}, Object.entries(UPDATE_CHECKS).map(([id, name]) => h('option', {value: id}, name)));
    mode.value = card.update_checks || 'manual';
    mode.addEventListener('change', async () => {
      try { await App.put(`/cloud/sources/${card.id}`, {update_checks: mode.value}); toast('Update checks: ' + UPDATE_CHECKS[mode.value], 'ok'); }
      catch (e) { mode.value = card.update_checks || 'manual'; fail(e); }
    });
    const out = h('div', {class: 'stack'});
    const check = btn('Check updates', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { fill(out, resultsList(await post('/cloud/updates/check', {source_id: card.id}), reload)); }
      catch (e) { fill(out, h('p', {class: 'alert bad', role: 'alert'}, e.message)); } finally { self.disabled = false; }
    }, 'btn-small');
    const last = card.last_check;
    return h('div', {class: 'card stack cloud-source'}, h('h3', {}, 'Cloud'),
      h('p', {class: 'small muted'}, `Laboratory connected from the cloud: ${card.url || '—'}. `
        + (card.last_checked_at ? `Last checked ${when(card.last_checked_at)}: ${last && last.newer ? `new release #${last.latest.number} available` : 'no newer release'}.` : 'Updates have not been checked yet.')),
      h('div', {class: 'row'}, check, card.status === 'connected' ? field('Update checks', mode) : null), out);
  }

  globalThis.LabsCloud = {install: (helpers) => { shared = helpers; }, ownCard, catalogueTab, updatesCard, automaticNotices, sourceCard, PUBLISH_PHASE};
})();
