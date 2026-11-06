/* Workshop maintenance, backup, restore and diagnostics (REQ-080, REQ-081). */
'use strict';
(() => {
  const {h, fill, btn, field, pill, get, post, put, toast, modal, facts} = App;
  const CONFIRM_WORD = 'overwrite';                       // the word the API expects before the open workshop is replaced
  const mb = (bytes) => (bytes == null ? '—' : bytes >= 1024 * 1024 * 1024 ? `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
    : `${(bytes / 1024 / 1024).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`);
  const when = (iso) => (iso ? `${iso.slice(0, 10)} ${iso.slice(11, 16)}` : '—');
  const errorBox = () => h('p', {class: 'alert bad', role: 'alert', hidden: true});
  const showError = (box, e) => { box.textContent = e.message || String(e); box.hidden = false; };
  const KIND = {schema: 'before schema change', release: 'before version update', other: 'database copy'};
  const PAGE = 10;                                        // backups are listed by pages of ten (DEC-090), the newest first
  const newest = (at) => (p, q) => String(at(q) || '').localeCompare(String(at(p) || ''));
  const oldest = (at) => (p, q) => String(at(p) || '').localeCompare(String(at(q) || ''));

  // ---- the workshop itself -------------------------------------------------------------------------------------------------------

  function workshopCard(w, changed) {
    const form = Forms.create();
    // the folder is sent exactly as typed; an empty box means the default folder, so it is not required
    const dir = form.add('path', 'Backup folder', h('input', {value: w.backup_dir || '', placeholder: w.default_backup_dir}),
      {raw: true, help: 'backups and diagnostics are saved here; leave empty for the default folder'});
    const change = btn('Change', async (ev) => {
      const self = ev.currentTarget;
      const v = form.collect();
      if (!v) return;
      self.disabled = true;
      try {
        const made = await put('/workshop/backup-dir', {path: v.path});
        toast('Backup folder saved', 'ok');
        changed(made.backup_dir);
      } catch (e) { form.fail(e); } finally { self.disabled = false; }
    });
    const schema = w.schema === w.schema_known ? pill(`schema ${w.schema}`, 'ok') : pill(`schema ${w.schema} of ${w.schema_known}`, 'warn');
    return h('div', {class: 'card stack'}, h('h3', {}, 'Workshop'),
      facts([['Data folder', w.data_dir], ['Application version', w.app], ['Database schema', schema],
        ['Opened by process', w.lock ? `${w.lock.program || 'titanium-platform'} (pid ${w.lock.pid})` : 'not locked'],
        ['Disk space available', `${mb(w.disk.free_bytes)} of ${mb(w.disk.total_bytes)}`]]),
      h('div', {class: 'row'}, dir, change), form.error);
  }

  // ---- backups -------------------------------------------------------------------------------------------------------------------

  function inspectDialog(b) {
    const body = h('div', {class: 'stack'}, h('p', {class: 'muted small'}, 'Checking the size and hash of each backup file…'));
    const m = modal('Inspect backup', body, [{label: 'Close', run: (d) => d.close()}]);
    post('/workshop/backups/inspect', {path: b.path, verify: true}).then((seen) => {
      const man = seen.manifest || {};
      fill(body, facts([['Folder', seen.path], ['Created', when(man.created_at)], ['Application version', man.app], ['Schema', man.schema],
        ['Files', man.files], ['Size', mb(man.bytes)], ['Workshop', man.data_dir]]),
      seen.complete ? h('p', {class: 'alert ok'}, 'The backup is complete: every file is present and matches its recorded hash.')
        : h('div', {class: 'stack'}, h('p', {class: 'alert bad'}, 'The backup is incomplete or damaged and cannot be restored.'),
          h('ul', {class: 'small'}, (seen.problems || []).map((p) => h('li', {}, I18N.tr(p))))));
    }).catch((e) => fill(body, h('p', {class: 'alert bad'}, e.message)));
    return m;
  }

  function restoreDialog(b, w, done) {
    const form = Forms.create();
    const target = form.add('target', 'Restore folder', h('input', {placeholder: 'for example, ~/titanium-restored'}),
      {required: true, help: 'use an empty or new folder; a nonempty folder will be rejected'});
    const body = h('div', {class: 'stack'},
      h('p', {class: 'small'}, `The backup from ${when((b.manifest || {}).created_at)} (${mb((b.manifest || {}).bytes)}) will be restored to a new folder: `
        + 'the database, work files, connected releases and fonts. Stored paths are updated for the new folder. The open workshop is unchanged.'),
      target, form.error);
    return modal('Restore to another folder', body, [{label: 'Cancel', run: (d) => d.close()},
      {label: 'Restore', cls: 'primary', run: async (d) => {
        const v = form.collect();
        if (!v) return;
        try {
          const made = await post('/workshop/restore', {path: b.path, target_dir: v.target});
          toast(`Workshop restored to ${made.path}`, 'ok');
          d.close();
          done(made);
        } catch (e) { form.fail(e); }
      }}]);
  }

  function replaceDialog(b, w, done) {
    const form = Forms.create();
    const wordBox = h('input', {placeholder: CONFIRM_WORD, autocomplete: 'off'});
    const typed = () => wordBox.value.trim();
    const word = form.add('word', `To continue, type ${CONFIRM_WORD}`, wordBox, {required: true,
      read: () => (typed() === CONFIRM_WORD ? {ok: true, value: typed()} : {ok: false, message: `Type ${CONFIRM_WORD} to replace the open workshop`})});
    const go = btn('Replace workshop', async (ev) => {
      const self = ev.currentTarget;
      const v = form.collect();
      if (!v) return;
      self.disabled = true;
      try {
        const made = await post('/workshop/restore', {path: b.path, target_dir: w.data_dir, overwrite: true, confirm: v.word});
        fill(body, h('p', {class: 'alert warn'}, `Workshop replaced from the backup; the previous workshop was moved to ${made.set_aside || '—'}. `
          + 'Restart the application: until then it still uses the previous data in memory.'));
        done(made);
      } catch (e) { form.fail(e); self.disabled = typed() !== CONFIRM_WORD; }
    }, 'danger', true);
    wordBox.addEventListener('input', () => { go.disabled = typed() !== CONFIRM_WORD; });
    const body = h('div', {class: 'stack'},
      h('p', {class: 'alert warn'}, `The open workshop ${w.data_dir} will be replaced by the backup from ${when((b.manifest || {}).created_at)}. `
        + `The current folder is not deleted: it will be moved to ${w.data_dir}.replaced-<date>. Changes made after this backup will exist only there.`),
      word, form.error, go);
    return modal('Replace open workshop', body, [{label: 'Close', run: (d) => d.close()}]);
  }

  function backupsCard(w, backups, refresh, notice) {
    const err = errorBox();
    const result = h('div', {class: 'stack'}, notice);
    const progress = h('p', {class: 'muted small', hidden: true}, 'Creating backup: copying the database, then work files, releases and fonts…');
    const make = btn('Create backup', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true; err.hidden = true; progress.hidden = false; fill(result);
      try {
        const made = await post('/workshop/backups', {});
        toast('Backup created', 'ok');
        refresh(h('p', {class: 'alert ok'}, `Backup created: ${made.path} · files ${Object.keys(made.files || {}).length} · ${mb(made.bytes)}.`));
      } catch (e) { showError(err, e); } finally { self.disabled = false; progress.hidden = true; }
    }, 'primary');
    // a backup a line: when, size, version, files and its folder; the checks and restores at the end of the line
    const created = (b) => (b.manifest || {}).created_at;
    const listed = backups.length ? App.list({id: 'workshop-backups', items: backups, key: (b) => b.path, page: PAGE,
      row: (b) => {
        const man = b.manifest || {};
        return [h('span', {}, when(man.created_at)), h('span', {}, mb(man.bytes)), h('span', {class: 'muted'}, man.app ? `${man.app} · schema ${man.schema}` : '—'),
          h('span', {class: 'muted'}, `${man.files ?? '—'} files`), b.complete ? null : pill('incomplete', 'bad'), h('span', {class: 'lst-text small muted', title: b.path}, b.path)];
      },
      actions: (b) => [btn('Inspect', () => inspectDialog(b)), btn('Restore…', () => restoreDialog(b, w, () => refresh())),
        btn('Replace open workshop…', () => replaceDialog(b, w, () => refresh()), 'danger')],
      search: (b) => `${when(created(b))} ${b.path}`,
      filters: [{key: 'state', label: 'Completeness', options: [['complete', 'complete'], ['partial', 'incomplete']], test: (b, v) => (v === 'complete') === !!b.complete}],
      sorts: [['new', 'Newest first', newest(created)], ['old', 'Oldest first', oldest(created)]]}).el
      : h('p', {class: 'muted'}, 'No backups yet.');
    return h('div', {class: 'card stack'}, h('h3', {}, 'Backups'),
      h('p', {class: 'small muted'}, 'A full workshop backup includes the database with unfinished journal entries, work and photo files, connected and own releases, and fonts, '
        + 'with a description and hash for each file. The manifest is written last, so an incomplete backup is never treated as complete.'),
      h('div', {class: 'row'}, make), progress, err, result,
      listed);
  }

  function recoveryCard(copies) {
    // dozens pile up over the releases: a copy a line, the newest first, ten at a time; the full path under a line
    const listed = copies.length ? App.list({id: 'workshop-recovery', items: copies, key: (c) => c.path, page: PAGE,
      row: (c) => [h('span', {}, when(c.modified_at)), h('span', {class: 'lst-text'}, c.name), h('span', {class: 'muted'}, mb(c.bytes)), pill(KIND[c.kind] || c.kind)],
      details: (c) => facts([['File', c.path], ['Saved', when(c.modified_at)], ['Size', mb(c.bytes)], ['Reason', KIND[c.kind] || c.kind]]),
      search: (c) => `${when(c.modified_at)} ${c.name}`,
      filters: [{key: 'kind', label: 'Reason', options: Object.entries(KIND), test: (c, v) => c.kind === v}],
      sorts: [['new', 'Newest first', newest((c) => c.modified_at)], ['old', 'Oldest first', oldest((c) => c.modified_at)],
        ['size', 'Largest first', (p, q) => q.bytes - p.bytes]]}).el
      : h('p', {class: 'muted'}, 'No recovery copies.');
    return h('div', {class: 'card stack'}, h('h3', {}, 'Copies before schema changes'),
      h('p', {class: 'small muted'}, 'Before changing the database schema, the application saves a copy in the backups folder beside the data and checks its integrity; '
        + 'only then is the schema changed. This is not a full backup (it excludes work files); it supports returning to the previous application version if the schema change fails.'),
      listed);
  }

  function diagnosticsCard() {
    const err = errorBox();
    const result = h('div', {class: 'stack'});
    const run = btn('Export diagnostics', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true; err.hidden = true;
      try {
        const made = await post('/workshop/diagnostics', {});
        fill(result, h('p', {class: 'alert ok'}, `Diagnostics file saved: ${made.path} (${mb(made.bytes)}; ${(made.members || []).join(', ')}). `,
          made.download ? h('a', {href: made.download, download: ''}, 'Download') : null));
        toast('Diagnostics file saved', 'ok');
      } catch (e) { showError(err, e); } finally { self.disabled = false; }
    });
    return h('div', {class: 'card stack'}, h('h3', {}, 'Diagnostics'),
      h('p', {class: 'small muted'}, 'The file contains application and schema versions, platform, table record counts, database integrity result, connected releases '
        + '(IDs and names), settings without key-like values, recent log lines and audit entries. '
        + 'The home folder, email addresses and key-like values and tokens are redacted. Photos, work files, the database and release files are excluded.'),
      h('div', {class: 'row'}, run), err, result);
  }

  App.register({id: 'workshop', async render() {
    const root = h('div', {class: 'stack'});
    const draw = async (notice = null) => {                 // ``notice``: the result of the last action, kept through the redraw
      const [w, backups, copies] = await Promise.all([get('/workshop'), get('/workshop/backups'), get('/workshop/recovery-copies')]);
      fill(root, h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Workshop'),
        h('p', {class: 'sub'}, 'Workshop data, schema and backups. Restoring to another folder leaves the open workshop unchanged; replacing it requires a separate explicit choice.'))),
      h('nav', {'aria-label': 'Workshop tasks', class: 'card stack'}, h('h3', {}, 'Workshop tasks'),
        h('div', {class: 'row'},
          btn('Backups and restore', () => { const card = root.querySelector('.workshop-backups'); if (card) { if (card.scrollIntoView) card.scrollIntoView({block: 'start'}); card.focus(); } }, 'btn-small'),
          App.link('/network', 'Connect a tablet or manage external services'),
          App.link('/labs', 'Connect or manage laboratories'),
          App.link('/setup', 'Materials and capture resources'))),
      workshopCard(w, () => draw()),
      (() => { const card = backupsCard(w, backups, draw, notice); card.classList.add('workshop-backups'); card.setAttribute('tabindex', '-1'); return card; })(),
      h('details', {class: 'card'}, h('summary', {}, 'Database recovery copies'), recoveryCard(copies)),
      h('details', {class: 'card'}, h('summary', {}, 'Diagnostics'), diagnosticsCard()));
    };
    await draw();
    return root;
  }});
})();
