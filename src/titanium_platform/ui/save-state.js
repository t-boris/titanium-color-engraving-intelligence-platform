/* The state of a document that is changed on the screen and stored by the server (feature ux-save-feedback-p0, REQ-001).
   A document is in one of five states: «saved», «waiting» (a change exists only on the screen), «saving» (a request is on its way),
   «calculating» (the request also recomputes a result, for example the prediction) and «failed» (a change was refused or lost).
   The screen hands every change to ``edit``; the tracker sends them one after another in the order made, and
   - gives each change a revision number; an answer to a change is shown only when it is the newest one and nothing is queued behind it,
     so a late answer can neither mark a newer change saved nor put an older state over it (the screen's ``apply`` runs once the line is empty);
   - keeps a failed change beside the object until it is corrected (a newer change of the same fields), retried, put back to the saved value
     or closed; the value the person typed stays in the control (``local()`` is what the screen shows over the saved state);
   - tells the saved state from the one on the screen: «saved» is never claimed while a change is unsaved, and a short success can never hide
     an error that is still there.
   What the server stores is the owner's business: ``send(request, edit)`` returns the document as the server has it after the change. */
'use strict';
const SaveState = (() => {
  const {h, btn} = App;
  const STATUS_TEXT = {saved: 'Сохранено', waiting: 'Изменения ждут отправки', saving: 'Сохраняем…', calculating: 'Сохраняем и считаем…', failed: 'Не сохранено'};
  const pick = (object, keys) => Object.fromEntries(keys.filter((k) => object && k in object).map((k) => [k, object[k]]));
  const plain = (value) => value === null || value === undefined || typeof value !== 'object';
  const shortText = (value) => {
    if (value === undefined || value === null || value === '') return '—';
    if (typeof value === 'boolean') return value ? 'да' : 'нет';
    const text = String(value);
    return text.length > 60 ? text.slice(0, 57) + '…' : text;
  };
  const clock = () => new Date();
  const timeOf = (date) => `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;

  /** A tracker. ``opts``: send(request, edit) -> the document after the change; apply(document, {local, edits, failed, reverted}) -> shows the
      stored document (called when the line of changes is empty and the stored document changed); confirmed: the document as stored now;
      label: what the document is called in messages; names: {field: name} for the messages; reload(): reads the document again (for a change
      that cannot be repeated); announce(text): a polite message for a screen reader; onOrphanFailure(failure): a failure that came when the
      document's view was already off the screen; now(): the clock. */
  function create(opts) {
    const {send, apply, label = 'Документ', names = {}, reload = null, announce = null, onOrphanFailure = null, now = clock} = opts;
    let revision = 0;                      // the number of the newest change
    let acknowledged = 0;                  // the newest change the server answered
    let current = opts.confirmed ?? null;  // the document as the server has it
    let applied = current;                 // the stored document the screen shows
    let sending = null;                    // the change on its way
    const queue = [];                      // changes waiting for the one on its way, in the order made
    let failures = [];                     // {edit, keys, error, shown, retrying}: refused or lost changes not corrected yet
    let acknowledgedSince = [];            // the changes the server accepted since the screen was last shown the stored document
    let savedAt = null, manual = false, hadFailure = false, touched = false;
    const listeners = new Set();
    const waiters = [];

    const status = () => (sending ? (sending.calculates ? 'calculating' : 'saving') : queue.length || manual ? 'waiting' : failures.length ? 'failed' : 'saved');
    /** What is on the screen and not stored: the failed, queued and sent changes laid over each other in the order made. */
    function local() {
      const parts = failures.filter((f) => f.edit.local).map((f) => [f.edit.revision, pick(f.edit.local, f.keys)]);
      for (const e of [sending, ...queue]) if (e && e.local) parts.push([e.revision, e.local]);
      return Object.assign({}, ...parts.sort((a, b) => a[0] - b[0]).map(([, v]) => v));
    }
    // «Ширина, мм: 0 (сохранено: 100)»; for a value that is not a single figure or word, only that it differs
    const describeLocal = () => Object.entries(local()).map(([k, v]) => (plain(v) && plain(current && current[k])
      ? `${names[k] || k}: ${shortText(v)} (сохранено: ${shortText(current && current[k])})` : `${names[k] || k}: изменено, не сохранено`)).join('; ');
    function snapshot() {
      return {status: status(), revision, acknowledged, queued: queue.length, local: local(), confirmed: current, savedAt, describe: describeLocal(),
        failures: failures.map((f) => ({revision: f.edit.revision, keys: [...f.keys], message: f.error.message, retryable: f.edit.retryable, shown: f.shown, retrying: f.retrying}))};
    }
    function notify() {
      const now_ = snapshot();
      for (const fn of [...listeners]) { try { fn(now_); } catch (_) { /* a listener never stops saving */ } }
    }

    /** Nothing is queued or on its way: show the stored document once (the screen drew «calculating» while changes were on their way, so it
        is drawn again even when the answer changed nothing), tell a recovery, wake those who wait. */
    function settle() {
      const batch = acknowledgedSince;
      acknowledgedSince = [];
      if (touched) {
        touched = false;
        applied = current;
        apply(current, {local: local(), edits: batch, failed: failures.length > 0, reverted: false});
      }
      if (hadFailure && !failures.length) { hadFailure = false; if (announce) announce(`${label}: изменения сохранены`); }
      notify();
      for (const wake of waiters.splice(0)) wake();
    }
    function pump() {
      if (sending) return;
      if (!queue.length) { settle(); return; }
      const edit = sending = queue.shift();
      notify();
      Promise.resolve().then(() => send(edit.request, edit)).then((answer) => landed(edit, answer), (error) => lost(edit, error));
    }
    function landed(edit, answer) {
      sending = null;
      acknowledged = edit.revision;
      current = answer;
      savedAt = now();
      acknowledgedSince.push(edit);
      for (const f of failures) f.keys = f.keys.filter((k) => !edit.keys.includes(k));           // a newer change of the same fields corrects them
      failures = failures.filter((f) => f.keys.length);
      edit.settle(null);
      pump();
    }
    function lost(edit, error) {
      sending = null;
      for (const f of failures) f.keys = f.keys.filter((k) => !edit.keys.includes(k));           // this failure replaces the older one on the same fields
      failures = failures.filter((f) => f.keys.length);
      for (const f of failures) if (f.retrying === edit) f.retrying = null;
      failures.push({edit, keys: [...edit.keys], error, shown: true, retrying: null});
      hadFailure = true;
      edit.settle(error);
      if (onOrphanFailure && api.view && api.view.el && api.view.el.isConnected === false) {
        try { onOrphanFailure({label, message: error.message, describe: describeLocal(), retryable: edit.retryable}); } catch (_) { /* reported elsewhere */ }
      }
      pump();
    }

    /** A change of the document. ``request`` is what ``send`` gets; ``local`` the fields it sets ({field: value}: absolute values, so the change can
        be repeated); ``keys`` the fields it settles (the keys of ``local`` by default); ``calculates`` that the answer is a recomputed result;
        ``retryable`` false for a change that must not be sent twice (an undo, an added item); ``meta`` is handed back to ``apply``.
        Resolves to null when the server took the change, else to the error. */
    function edit(request, o = {}) {
      const item = {revision: ++revision, request, local: o.local || null, keys: o.keys || (o.local ? Object.keys(o.local) : [`@${revision}`]),
        calculates: !!o.calculates, retryable: o.retryable ?? !!o.local, meta: o.meta || {}};
      item.done = new Promise((resolve) => { item.settle = resolve; });
      manual = false;
      touched = true;
      queue.push(item);
      notify();
      pump();
      return item.done;
    }
    /** Send the failed changes again, except what a newer change has covered since. Resolves to null, or to the first error. */
    function retry() {
      const covering = (f, key) => [sending, ...queue].some((e) => e && e.revision > f.edit.revision && e.keys.includes(key));
      const sent = [];
      for (const f of failures.slice()) {
        if (!f.edit.retryable || (f.retrying && (f.retrying === sending || queue.includes(f.retrying)))) continue;
        const keys = f.keys.filter((k) => !covering(f, k));
        if (!keys.length) { failures = failures.filter((x) => x !== f); continue; }             // a newer change has settled these fields
        const request = f.edit.local && f.edit.request && typeof f.edit.request.body === 'object' && keys.length < f.edit.keys.length
          ? {...f.edit.request, body: pick(f.edit.request.body, keys)} : f.edit.request;
        const again = edit(request, {local: pick(f.edit.local, keys), keys, calculates: f.edit.calculates, retryable: true, meta: f.edit.meta});
        f.retrying = queue[queue.length - 1] || sending;
        sent.push(again);
      }
      if (!sent.length) { notify(); return Promise.resolve(null); }
      return Promise.all(sent).then((results) => results.find(Boolean) || null);
    }
    function dismiss() { for (const f of failures) f.shown = false; notify(); }
    /** Put the stored document back on the screen over the failed changes. False while changes are on their way. */
    function revert() {
      if (sending || queue.length) return false;
      failures = [];
      hadFailure = false;
      touched = false;
      acknowledgedSince = [];
      applied = current;
      apply(current, {local: {}, edits: [], failed: false, reverted: true});
      notify();
      return true;
    }
    /** The person has typed something that is not sent yet (a pause before a slider is saved): the document waits. */
    function waiting(on = true) { manual = !!on; notify(); }
    /** The document was replaced by something other than a change of ours (a confirmed step of a laboratory release): it is the stored one now. */
    function adopt(document) { current = document; applied = document; }
    const idle = () => (sending || queue.length ? new Promise((resolve) => waiters.push(resolve)) : Promise.resolve());

    const api = {edit, retry, dismiss, revert, waiting, adopt, idle, local, snapshot, status, view: null,
      onChange: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
      dismissed: () => failures.length > 0 && failures.every((f) => !f.shown),
      reload: reload ? () => reload() : null};
    api.view = createView(api, {label, names, reload});
    listeners.add((snap) => api.view.update(snap));
    api.view.update(snapshot());
    return api;
  }

  /** The status line and, beside it, the error with what can be done: «Повторить», «Вернуть сохранённое», «Закрыть». The line is not a live
      region (a slider would chatter); the error is an alert, drawn again only when its words change. */
  function createView(tracker, {label, reload}) {
    const line = h('p', {class: 'save-line small', tabindex: '-1'});
    const message = h('p', {});
    const diff = h('p', {class: 'small'});
    const close = btn('Закрыть', () => tracker.dismiss(), 'btn-small');
    const box = h('div', {class: 'alert bad save-error', role: 'alert', hidden: true}, message, diff, close);
    const again = btn('Повторить сохранение', async () => {
      const result = await tracker.retry();
      if (!result) line.focus && line.focus();
    }, 'btn-small primary');
    const back = btn('Вернуть сохранённое', () => { tracker.revert(); line.focus && line.focus(); }, 'btn-small');
    back.setAttribute('title', 'Заменить то, что набрано, сохранённым значением');
    const refresh = btn('Показать сохранённое', async () => { if (tracker.reload) await tracker.reload(); tracker.revert(); }, 'btn-small');
    const actions = h('div', {class: 'row save-actions', hidden: true}, again, back, refresh);
    const el = h('div', {class: 'save-state', 'data-state': 'saved'}, line, box, actions);
    let shownFor = '';
    function update(snap) {
      el.setAttribute('data-state', snap.status);
      const failed = snap.failures.length > 0;
      const busy = snap.status === 'saving' || snap.status === 'calculating' || snap.status === 'waiting';
      let text = STATUS_TEXT[snap.status];
      if (busy && snap.queued) text += ` · ещё ${snap.queued} в очереди`;
      if (snap.status === 'saved') text += snap.savedAt ? ` в ${timeOf(snap.savedAt)}` : '';
      if (failed && busy) text = 'Повторяем сохранение… ' + text;
      if (snap.status === 'failed') text = Object.keys(snap.local).length ? 'Не сохранено: на экране не то, что хранится' : 'Не сохранено';
      line.textContent = `${label}: ${text}`;
      box.hidden = !(failed && snap.failures.some((f) => f.shown));
      actions.hidden = !failed;
      const first = snap.failures[0];
      if (first) {
        const signature = snap.failures.map((f) => `${f.revision}:${f.message}`).join('|');
        if (signature !== shownFor) {
          shownFor = signature;
          message.textContent = snap.failures.length > 1 ? `Не удалось сохранить изменений: ${snap.failures.length}. ${first.message}` : `Не удалось сохранить. ${first.message}`;
          diff.textContent = snap.describe ? `Набрано, но не сохранено — ${snap.describe}.` : 'Работа осталась такой, как была сохранена.';
        }
      } else shownFor = '';
      const retryable = snap.failures.some((f) => f.retryable);
      again.hidden = !retryable;
      again.disabled = busy;
      back.hidden = !Object.keys(snap.local).length;
      back.disabled = busy;
      refresh.hidden = retryable || !failed;
      refresh.disabled = busy;
      close.disabled = false;
    }
    return {el, update};
  }

  return {create, STATUS_TEXT, pick};
})();
