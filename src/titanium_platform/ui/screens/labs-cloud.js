/* Облако лабораторий (feature electron, REQ-086, REQ-087, DEC-058) — части экрана «Лаборатории», которые говорят с облаком через локальный
   API (/api/cloud): вход и выход (страница входа открывается в новом окне, приложение ждёт ответа /api/cloud/account), блок «Облако» на
   «Моей лаборатории» (публикация выпуска с той же подготовкой, что и в файл; незавершённая публикация продолжается тем же ключом; своя
   лаборатория в облаке с выпусками, приглашениями и участниками), вкладка «Каталог лабораторий» (открытые без входа, закрытые — по
   приглашению; «Подключить» ведёт в ту же полосу хода, что и файл) и проверка обновлений подключённых из облака лабораторий. Всё, что
   пришло из облака (названия, авторы, ссылки, учётные записи), показывается только текстом (узлы h()). labs.js подключает модуль через
   LabsCloud.install(...) со своими помощниками: полоса хода задачи, тело подготовки публикации, названия условий, окно различий. */
'use strict';
(() => {
  const {h, fill, btn, field, link, pill, get, post, del, toast, fail, confirmBox, facts, table} = App;
  const {short, day, when} = LabSource;
  const ACCOUNT_POLL_MS = 1000;
  const VISIBILITY = {public: 'открытая', private: 'закрытая'};
  const STATE = {reserved: 'зарезервирована', exported: 'выпуск записан', uploading: 'передача', finalized: 'опубликована', failed: 'не завершена'};
  const PUBLISH_PHASE = {waiting: 'ожидание', reserving: 'резервирование в облаке', exporting: 'запись выпуска', uploading: 'передача в облако',
    finalizing: 'завершение', done: 'опубликовано', failed: 'не опубликовано', cancelled: 'отменено'};
  const UPDATE_CHECKS = {manual: 'по кнопке', auto: 'автоматически (если разрешено на экране «Сеть»)'};
  let shared = null;                 // labs.js: {followJob, previewBody, countsText, termsName, differencesDialog, mb}
  const accountText = (a) => (a ? [a.name, a.email].filter(Boolean).join(' · ') : '');
  const releaseLine = (r) => `№ ${r.number} от ${day(r.created_at)} · ${short(r.content_sha256)}`;

  // ---- the sign-in ---------------------------------------------------------------------------------------------------------------

  /** «Войти»: the cloud's sign-in page opens in a new window; the screen asks /cloud/account every second until the sign-in arrives. */
  function signInButton(done) {
    const note = h('span', {class: 'small muted cloud-signin-note'});
    let timer = null, state = null;
    const stop = () => { if (timer) { clearInterval(timer); timer = null; } };
    const cancel = btn('Отменить вход', async () => {
      stop(); button.disabled = false; cancel.hidden = true; fill(note);
      try { await post('/cloud/signin/cancel', {state}); } catch (_) { /* the state is gone already */ }
    }, 'btn-small');
    cancel.hidden = true;
    const button = btn('Войти', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const started = await post('/cloud/signin', {});
        state = started.state;
        const opened = window.open(started.url, '_blank', 'noopener');
        fill(note, 'Войдите в открывшемся окне браузера; после входа окно можно закрыть. ',
          opened ? null : h('a', {href: started.url, target: '_blank', rel: 'noopener'}, 'Открыть страницу входа'));
        cancel.hidden = false;
        const until = Date.now() + (started.expires_in_s || 600) * 1000;
        timer = setInterval(async () => {
          try {
            const account = await get('/cloud/account');
            if (account.signed_in) { stop(); toast('Вход в облако выполнен', 'ok'); done(account); }
            else if (Date.now() > until) { stop(); self.disabled = false; cancel.hidden = true; fill(note, 'Вход не завершён: время ожидания вышло. Нажмите «Войти» ещё раз.'); }
          } catch (e) { stop(); self.disabled = false; cancel.hidden = true; fill(note, e.message); }
        }, ACCOUNT_POLL_MS);
      } catch (e) { self.disabled = false; fail(e); }
    }, 'primary');
    return h('span', {class: 'row cloud-signin'}, button, cancel, note);
  }

  function accountRow(own, reload) {
    if (!own.switched_on) return h('p', {class: 'alert warn'}, 'Облако выключено в настройках сети этой мастерской: каталог, публикация и приглашения недоступны. ', link('/network', 'Открыть «Сеть»'));
    if (!own.signed_in) {
      return h('div', {class: 'row'}, h('span', {class: 'small'}, 'Вы не вошли в облако. Вход нужен, чтобы публиковать выпуски, приглашать в закрытую лабораторию и видеть закрытые лаборатории; '
        + 'каталог открытых лабораторий доступен и без входа.'), h('span', {class: 'spacer'}), signInButton(reload));
    }
    const out = btn('Выйти', () => confirmBox('Выйти из облака?', 'Опубликованное останется в облаке; подключённые лаборатории продолжат работать здесь.', 'Выйти',
      async () => { await post('/cloud/signout', {}); toast('Выход из облака выполнен', 'ok'); reload(); }), 'btn-small');
    return h('div', {class: 'row'}, h('span', {}, 'Вы вошли как ', h('strong', {class: 'cloud-account'}, accountText(own.account))),
      h('span', {class: 'small muted'}, `облако: ${own.api_url}`), h('span', {class: 'spacer'}), out);
  }

  // ---- «Облако» on «Моя лаборатория» ----------------------------------------------------------------------------------------------

  function publishBlock(own, terms, reload) {
    const termsSelect = h('select', {'aria-label': 'Условия использования в облаке'}, terms.map((t) => h('option', {value: t.id}, `${shared.termsName(t)} — ${(t.summary && t.summary.ru) || ''}`)));
    const visibility = h('select', {'aria-label': 'Видимость'}, Object.entries(VISIBILITY).map(([id, name]) => h('option', {value: id}, name)));
    const out = h('div', {class: 'stack'}), progress = h('div', {class: 'stack', hidden: true});
    let ready = false;
    const prepare = btn('Подготовка публикации', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { const p = await post('/labs/own/preview', {selection: null}); ready = p.ready; publish.disabled = !ready; fill(out, shared.previewBody(p)); }
      catch (e) { fill(out, h('p', {class: 'alert bad'}, e.message)); } finally { self.disabled = false; }
    });
    const publish = btn('Опубликовать в облаке', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true; prepare.disabled = true;
      await shared.followJob({start: () => post('/cloud/publish', {terms: termsSelect.value, visibility: visibility.value}), jobs: '/cloud/jobs', box: progress,
        label: 'Публикация выпуска', phases: PUBLISH_PHASE, success: (job) => `Опубликовано: выпуск № ${job.result.release.number} · ${shared.countsText(job.result.release.counts)}.`,
        done: (result) => { toast(`Выпуск № ${result.release.number} опубликован в облаке`, 'ok'); reload(); }});
      prepare.disabled = false; self.disabled = !ready;
    }, 'primary', true);
    return h('div', {class: 'stack cloud-publish'}, h('h4', {}, 'Публикация в облаке'),
      h('p', {class: 'small muted'}, 'В облако уходит тот же выпуск .tcelab, что и в файл: сначала посмотрите, что в него войдёт. Файл выпуска остаётся и в «Записанных выпусках». '
        + (own.lab ? `Лаборатория в облаке ${VISIBILITY[own.lab.visibility] || own.lab.visibility}: видимость выбирается при первой публикации.`
          : 'Видимость выбирается при первой публикации: открытую лабораторию видят все, закрытую — только приглашённые.')),
      h('div', {class: 'row'}, prepare, field('Условия использования', termsSelect), own.lab ? null : field('Видимость', visibility), publish), out, progress);
  }

  function pendingBlock(p, reload) {
    const progress = h('div', {class: 'stack', hidden: true});
    const retry = btn('Продолжить публикацию', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      await shared.followJob({start: () => post('/cloud/publish/retry', {}), jobs: '/cloud/jobs', box: progress, label: 'Публикация выпуска', phases: PUBLISH_PHASE,
        success: (job) => `Опубликовано: выпуск № ${job.result.release.number}.`, done: () => { toast('Выпуск опубликован в облаке', 'ok'); reload(); }});
      self.disabled = false;
    }, 'primary btn-small');
    const giveUp = btn('Отказаться', () => confirmBox('Отказаться от публикации?', 'Незавершённая публикация будет помечена неудавшейся; в облаке ничего не появится. '
      + 'Записанный файл выпуска остаётся на компьютере.', 'Отказаться', async () => { await post('/cloud/publish/abandon', {}); toast('Публикация отменена', 'ok'); reload(); }), 'danger btn-small');
    return h('div', {class: 'alert warn stack cloud-pending'},
      h('p', {}, `Публикация от ${when(p.created_at)} не завершена (${STATE[p.state] || p.state}${p.error ? `: ${I18N.tr(p.error)}` : ''}). `
        + 'Её можно продолжить с того же места: в облаке появится один выпуск, не два.'),
      h('div', {class: 'row'}, retry, giveUp), progress);
  }

  function invitationsBlock(own, reload) {
    const made = h('div', {});
    const invite = btn('Создать приглашение', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const inv = await post('/cloud/invitations', {});
        fill(made, h('p', {class: 'alert ok stack'}, h('span', {}, `Приглашение создано, действует до ${when(inv.expires_at)}. Передайте ссылку получателю: она показывается только сейчас.`),
          h('code', {class: 'cloud-link'}, inv.link)));
        toast('Приглашение создано', 'ok');
      } catch (e) { fail(e); } finally { self.disabled = false; }
    }, 'btn-small');
    const rows = own.invitations.map((i) => [when(i.created_at), when(i.expires_at),
      i.revoked_at ? pill('отозвано', 'bad') : i.accepted_by ? h('span', {}, pill('принято', 'ok'), ' ', h('span', {class: 'small cloud-account'}, i.accepted_by)) : pill('ждёт'),
      i.revoked_at || i.accepted_by ? null : btn('Отозвать', () => confirmBox('Отозвать приглашение?', 'Ссылка перестанет действовать.', 'Отозвать',
        async () => { await del(`/cloud/invitations/${encodeURIComponent(i.id)}`); toast('Приглашение отозвано', 'ok'); reload(); }), 'danger btn-small')]);
    const members = own.members.map((m) => [h('span', {class: 'cloud-account'}, m.account_id), when(m.created_at),
      btn('Исключить', () => confirmBox('Исключить участника?', 'Он перестанет видеть закрытую лабораторию и скачивать её выпуски; то, что он уже подключил, у него остаётся.',
        'Исключить', async () => { await del(`/cloud/members/${encodeURIComponent(m.account_id)}`); toast('Участник исключён', 'ok'); reload(); }), 'danger btn-small')]);
    return h('div', {class: 'stack'}, h('h4', {}, 'Приглашения и участники'),
      h('p', {class: 'small muted'}, own.lab.visibility === 'private' ? 'Закрытую лабораторию видят только приглашённые: ссылка приглашения действует один раз и ограниченное время.'
        : 'Лаборатория открытая: её видят все и без приглашения. Приглашение всё же можно создать — так лаборатория появится у получателя среди его.'),
      h('div', {class: 'row'}, invite), made,
      table(['Создано', 'Действует до', 'Состояние', ''], rows, 'Приглашений нет', true),
      table(['Участник', 'С', ''], members, 'Участников нет', true));
  }

  function labBlock(own, reload) {
    const lab = own.lab;
    return h('div', {class: 'stack'}, h('h4', {}, 'Лаборатория в облаке: ', h('span', {class: 'lab-name'}, lab.name), ' ', pill(VISIBILITY[lab.visibility] || lab.visibility)),
      table(['№', 'Опубликован', 'Содержимое', 'Условия', 'Размер'], own.releases.map((r) => [String(r.number), when(r.published_at), shared.countsText(r.counts),
        shared.termsName(r.usage_terms), shared.mb(r.byte_size)]), 'Выпусков в облаке ещё нет', true),
      invitationsBlock(own, reload));
  }

  function publicationsTable(list) {
    const rows = list.filter((p) => p.state !== 'finalized').map((p) => [when(p.created_at), STATE[p.state] || p.state, p.release_number == null ? '—' : String(p.release_number),
      p.error ? I18N.tr(p.error) : '—']);
    return rows.length ? h('details', {class: 'small'}, h('summary', {}, 'Незавершённые и неудавшиеся публикации'), table(['Начата', 'Состояние', '№', 'Причина'], rows, '', true)) : null;
  }

  /** The «Облако» card of «Моя лаборатория»: /cloud/own is asked here, apart from /labs/own, so that the cloud's silence never hides the rest. */
  async function ownCard(terms, reload) {
    const el = h('div', {class: 'card stack cloud-own'}, h('h3', {}, 'Облако'));
    let own;
    try { own = await get('/cloud/own'); } catch (e) { return fill(el, h('h3', {}, 'Облако'), h('p', {class: 'alert bad', role: 'alert'}, e.message)); }
    const parts = [h('h3', {}, 'Облако'),
      h('p', {class: 'small muted'}, 'Облако лабораторий — каталог выпусков: опубликованный выпуск другие мастерские подключают оттуда, а не из файла, и узнают о новых выпусках. '
        + 'Приложение обращается к облаку только когда вы входите, публикуете или проверяете обновления.'),
      accountRow(own, reload)];
    if (own.signed_in && own.switched_on) {
      if (own.pending) parts.push(pendingBlock(own.pending, reload));
      else parts.push(publishBlock(own, terms, reload));
      if (own.lab) parts.push(labBlock(own, reload));
      parts.push(publicationsTable(own.publications || []));
    }
    return fill(el, parts);
  }

  // ---- «Каталог лабораторий» -------------------------------------------------------------------------------------------------------

  function connectButton(latest, connected, label, progress, reload) {
    return btn(label, async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      await shared.followJob({start: () => post(`/cloud/releases/${encodeURIComponent(latest.id)}/connect`, {}), jobs: '/cloud/jobs', box: progress,
        done: (result) => { if (connected && result && result.current && !result.unchanged) shared.differencesDialog(result.current); reload(); }});
      self.disabled = false;
    }, 'primary btn-small');
  }

  function labCard(lab, reload) {
    const latest = lab.latest_release, c = lab.connected;
    const progress = h('div', {class: 'stack', hidden: true});
    const connect = latest && !lab.own ? connectButton(latest, c, c ? (c.newer ? `Подключить выпуск № ${latest.number}` : 'Подключить снова') : 'Подключить', progress, reload) : null;
    return h('article', {class: 'card stack cloud-lab'},
      h('h3', {}, h('span', {class: 'lab-name'}, lab.name), ' ', pill(VISIBILITY[lab.visibility] || lab.visibility), lab.own ? [' ', pill('ваша лаборатория', 'ok')] : null,
        c ? [' ', pill(c.status === 'connected' ? 'подключена' : 'отключена', c.status === 'connected' ? 'ok' : 'warn')] : null, c && c.newer ? [' ', pill('есть новый выпуск', 'warn')] : null),
      facts([['Автор', lab.author], ['Описание', lab.description], ['Ссылка', lab.url ? h('span', {class: 'lab-url'}, lab.url) : null],
        ['Выпуск', latest ? releaseLine(latest) : 'выпусков ещё нет'], ['Содержимое', latest ? shared.countsText(latest.counts) : null],
        ['Условия', latest ? shared.termsName(latest.usage_terms) : null], ['Размер', latest ? shared.mb(latest.byte_size) : null],
        ['У вас', c ? `${c.status === 'connected' ? 'подключена' : 'отключена'}${c.current_release_number == null ? '' : `, выпуск № ${c.current_release_number}`}` : null]]),
      lab.own ? h('p', {class: 'small muted'}, 'Результаты этой лаборатории уже здесь: это выпуски вашей мастерской.') : null,
      connect ? h('div', {class: 'row'}, connect, c ? btn('Открыть', () => App.go(`/labs?tab=sources&source=${c.source_id}`), 'btn-small') : null) : null, progress);
  }

  function acceptBlock(signedIn, reload) {
    const input = h('input', {placeholder: 'ссылка приглашения', 'aria-label': 'Ссылка приглашения'});
    const err = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const accept = btn('Принять приглашение', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true; err.hidden = true;
      try {
        const got = await post('/cloud/invitations/accept', {link: input.value});
        toast(`Приглашение принято: ${got.lab.name}`, 'ok');
        reload();
      } catch (e) { err.textContent = e.message; err.hidden = false; } finally { self.disabled = false; }
    }, 'btn-small');
    return h('div', {class: 'card stack cloud-accept'}, h('h3', {}, 'Закрытые лаборатории'),
      h('p', {class: 'small muted'}, signedIn ? 'Закрытая лаборатория появляется в каталоге после приглашения: вставьте ссылку, которую передал её владелец.'
        : 'Чтобы видеть закрытые лаборатории и принимать приглашения, войдите в облако на вкладке «Моя лаборатория».'),
      signedIn ? h('div', {class: 'toolbar'}, field('Ссылка приглашения', input), accept) : null, err);
  }

  async function catalogueTab() {
    const el = h('div', {class: 'stack'});
    async function show() {
      let cat;
      try { cat = await get('/cloud/catalogue'); } catch (e) { return fill(el, h('div', {class: 'card'}, h('p', {class: 'alert bad', role: 'alert'}, e.message))); }
      fill(el, h('p', {class: 'small muted'}, `Облако: ${cat.api_url}` + (cat.signed_in ? '' : ' · без входа показываются только открытые лаборатории')),
        cat.labs.length ? h('div', {class: 'vw-works'}, cat.labs.map((lab) => labCard(lab, show)))
          : h('div', {class: 'card empty'}, h('h3', {}, 'В каталоге пока нет лабораторий'), h('p', {class: 'muted'}, 'Опубликованные выпуски появятся здесь; закрытые лаборатории — после приглашения.')),
        acceptBlock(cat.signed_in, show));
    }
    await show();
    return el;
  }

  // ---- updates of the laboratories connected from the cloud --------------------------------------------------------------------------

  function resultsList(results, reload) {
    if (!results.length) return h('p', {class: 'muted small'}, 'Лабораторий из облака нет: проверять нечего.');
    return h('ul', {class: 'stack small cloud-updates'}, results.map((r) => {
      const progress = h('div', {class: 'stack', hidden: true});
      const text = r.error ? h('span', {class: 'bad'}, I18N.tr(r.error)) : !r.found ? 'в облаке больше не значится'
        : r.newer ? `новый выпуск № ${r.latest.number} от ${day(r.latest.created_at)} · ${shared.countsText(r.latest.counts)}`
          : `новее нет${r.current_release_number == null ? '' : ` (текущий № ${r.current_release_number})`}`;
      return h('li', {class: 'stack'}, h('div', {class: 'row'}, h('span', {class: 'lab-name'}, r.name), ' — ', text,
        r.newer ? connectButton(r.latest, {source_id: r.source_id}, 'Подключить', progress, reload) : null), progress);
    }));
  }

  /** The card of «Подключённые лаборатории» with «Проверить обновления» (shown when a laboratory came from the cloud). */
  function updatesCard(sources, reload) {
    const cloud = sources.filter((s) => s.origin === 'cloud');
    if (!cloud.length) return null;
    const out = h('div', {class: 'stack'});
    const check = btn('Проверить обновления', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { fill(out, resultsList(await post('/cloud/updates/check', {}), reload)); }
      catch (e) { fill(out, h('p', {class: 'alert bad', role: 'alert'}, e.message)); } finally { self.disabled = false; }
    }, 'btn-small');
    return h('div', {class: 'card stack cloud-updates-card'}, h('h3', {}, 'Обновления из облака'),
      h('p', {class: 'small muted'}, `Лабораторий, подключённых из облака: ${cloud.length}. Проверка спрашивает облако, вышел ли новый выпуск, и ничего не подключает сама. `
        + 'Сама по себе она идёт только у лабораторий с автоматической проверкой и только когда проверка обновлений разрешена на экране «Сеть».'),
      h('div', {class: 'row'}, check), out);
  }

  /** The automatic checks the server finds due (none unless both settings allow): a notice per laboratory with a newer release. */
  async function automaticNotices(reload) {
    let due;
    try { due = await post('/cloud/updates/automatic', {}); } catch (_) { return null; }
    const newer = (due || []).filter((r) => r.newer);
    return newer.length ? h('div', {class: 'alert stack cloud-auto'}, newer.map((r) => {
      const progress = h('div', {class: 'stack', hidden: true});
      return h('div', {class: 'stack'}, h('div', {class: 'row'}, h('span', {}, 'В облаке вышел новый выпуск лаборатории «', h('span', {class: 'lab-name'}, r.name), `»: № ${r.latest.number} от ${day(r.latest.created_at)}.`),
        connectButton(r.latest, {source_id: r.source_id}, 'Подключить', progress, reload)), progress);
    })) : null;
  }

  /** On the card of one laboratory connected from the cloud: the check by the button and how it is checked by itself. */
  function sourceCard(card, reload) {
    if (card.origin !== 'cloud') return null;
    const mode = h('select', {'aria-label': 'Проверка обновлений'}, Object.entries(UPDATE_CHECKS).map(([id, name]) => h('option', {value: id}, name)));
    mode.value = card.update_checks || 'manual';
    mode.addEventListener('change', async () => {
      try { await App.put(`/cloud/sources/${card.id}`, {update_checks: mode.value}); toast('Проверка обновлений: ' + UPDATE_CHECKS[mode.value], 'ok'); }
      catch (e) { mode.value = card.update_checks || 'manual'; fail(e); }
    });
    const out = h('div', {class: 'stack'});
    const check = btn('Проверить обновления', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { fill(out, resultsList(await post('/cloud/updates/check', {source_id: card.id}), reload)); }
      catch (e) { fill(out, h('p', {class: 'alert bad', role: 'alert'}, e.message)); } finally { self.disabled = false; }
    }, 'btn-small');
    const last = card.last_check;
    return h('div', {class: 'card stack cloud-source'}, h('h3', {}, 'Облако'),
      h('p', {class: 'small muted'}, `Лаборатория подключена из облака: ${card.url || '—'}. `
        + (card.last_checked_at ? `Последняя проверка ${when(card.last_checked_at)}: ${last && last.newer ? `есть новый выпуск № ${last.latest.number}` : 'новее нет'}.` : 'Обновления ещё не проверялись.')),
      h('div', {class: 'row'}, check, card.status === 'connected' ? field('Проверка обновлений', mode) : null), out);
  }

  globalThis.LabsCloud = {install: (helpers) => { shared = helpers; }, ownCard, catalogueTab, updatesCard, automaticNotices, sourceCard, PUBLISH_PHASE};
})();
