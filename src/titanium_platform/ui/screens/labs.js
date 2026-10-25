/* Лаборатории (feature electron, REQ-083..085). «Моя лаборатория»: что мастерская говорит о себе публично, подготовка публикации (что войдёт в
   выпуск, что станет токеном, что не публикуется никогда), запись выпуска .tcelab под выбранными условиями, записанные выпуски и отзыв
   опубликованного. «Подключённые лаборатории»: файл .tcelab читается и показывается прежде, чем подключается; подключение идёт в фоне с
   ходом чтения и отменой; у каждой лаборатории карточка: выпуски, различия, отзывы, палитра и шкалы каждой измеренной установки, «Проверить у
   себя» (перенос рецепта на свой лазер) и сделанные переносы. Всё, что пришло из чужого выпуска, показывается только текстом (узлы h()).
   Облако (REQ-086, REQ-087; labs-cloud.js): блок «Облако» на «Моей лаборатории», вкладка «Каталог лабораторий», проверка обновлений
   подключённых из облака лабораторий. Адрес: #/labs, ?tab=own|sources|catalogue, ?source=<id> — карточка лаборатории. */
'use strict';
(() => {
  const {h, fill, btn, field, link, pill, get, post, put, del, form, go, toast, fail, modal, confirmBox, facts, table, num, labText, swatch, agreed, CAUTION} = App;
  const {short, day, when, laserName, lensName, materialName, setupName, releaseName, BASIS} = LabSource;
  const POLL_MS = 300;
  const mb = (bytes) => `${(bytes / 1024 / 1024).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0).replace('.', ',')} МБ`;
  const SECTION = {equipment: 'установок', materials: 'титана', captures: 'фотографий', measurements: 'измерений', tone_profiles: 'тональных профилей',
    provenance: 'записей происхождения', lab: 'лаборатория', withdrawals: 'отзывов'};
  const countsText = (counts) => Object.entries(counts || {}).filter(([, n]) => n).map(([k, n]) => `${SECTION[k] || k}: ${n}`).join(' · ') || 'пусто';
  const NEVER = {photographs: 'фотографии', raw: 'исходные файлы', previews: 'предпросмотры', lightburn_geometry: 'геометрия LightBurn', masks: 'маски',
    paths: 'пути к файлам', file_names: 'имена файлов', titles: 'названия', layer_names: 'имена слоёв', notes: 'заметки', ai: 'переписка с AI',
    credentials: 'ключи и пароли', email: 'почта', serial: 'серийные номера', batch: 'партии', surface: 'обработка поверхности',
    free_text_settings: 'настройки свободным текстом'};
  const TARGET = {release: 'выпуск', measurement: 'измерение', tone_profile: 'тональный профиль'};
  const PHASE = {waiting: 'ожидание', downloading: 'загрузка из облака', checking: 'проверка файла', building: 'сборка снимка', activating: 'подключение',
    done: 'подключено', unchanged: 'уже подключено', failed: 'не подключено', cancelled: 'отменено'};
  const STATUS = {connected: ['подключена', 'ok'], disconnected: ['отключена', 'warn']};
  const termsName = (t) => (t ? (t.name && t.name.ru) || t.id || '—' : '—');
  const termsOf = (list, id) => list.find((t) => t.id === id) || {id};
  const verifiedPill = (v) => (v ? pill('подпись проверена', 'ok') : pill('подпись не проверена', 'warn'));
  const recipeText = (r) => (r ? [`${num(r.power, 1)} %`, `${num(r.frequency, 1)} кГц`, `${num(r.speed, 0)} мм/с`, r.pulse_width == null ? null : `${num(r.pulse_width, 0)} нс`,
    r.line_interval == null ? null : `шаг ${num(r.line_interval, 4)} мм`, `проходов ${r.passes ?? 1}`, r.global_passes > 1 ? `глобально ${r.global_passes}×` : null,
    r.cross_hatch ? 'крест' : null, r.scan_angle == null ? null : `угол ${num(r.scan_angle, 0)}°`].filter(Boolean).join(' · ') : 'рецепт не записан');
  const safeLink = (url) => (url ? h('span', {class: 'lab-url'}, url) : null);      // a laboratory's link is shown as text, never followed from here
  // the orders of the short lists (DEC-090): by an ISO date, the newest or the oldest first
  const newest = (at) => (p, q) => String(at(q) || '').localeCompare(String(at(p) || ''));
  const oldest = (at) => (p, q) => String(at(p) || '').localeCompare(String(at(q) || ''));

  // ---- «Моя лаборатория» ---------------------------------------------------------------------------------------------------------

  function publicForm(pub, saved) {
    const text = (key, placeholder, multiline) => (multiline ? h('textarea', {rows: 3, placeholder, 'aria-label': placeholder}) : h('input', {placeholder, 'aria-label': placeholder}));
    const name = text('name', 'Публичное название лаборатории'), description = text('description', 'Описание', true), url = text('url', 'Ссылка лаборатории (https)');
    const author = text('author', 'Автор'), organization = text('organization', 'Организация'), authorUrl = text('author_url', 'Ссылка автора (https)');
    name.value = pub.name || ''; description.value = pub.description || ''; url.value = pub.url || '';
    author.value = pub.author || ''; organization.value = pub.organization || ''; authorUrl.value = pub.author_url || '';
    const lasers = Object.entries(pub.lasers || {}).map(([id, laser]) => {
      const publicName = h('input', {value: laser.public_name || '', 'aria-label': `Публичное название лазера ${id}`});
      const manufacturer = h('input', {value: laser.manufacturer || '', placeholder: 'производитель'}), model = h('input', {value: laser.model || '', placeholder: 'модель'});
      return {id, publicName, manufacturer, model, el: h('div', {class: 'grid g2 lab-laser'}, field(`Лазер № ${id}: публичное название`, publicName),
        field('Производитель и модель', h('div', {class: 'row'}, manufacturer, model)))};
    });
    const err = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const save = btn('Сохранить', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true; err.hidden = true;
      try {
        const made = await put('/labs/own', {name: name.value, description: description.value, url: url.value, author: author.value, organization: organization.value,
          author_url: authorUrl.value, lasers: Object.fromEntries(lasers.map((l) => [l.id, {public_name: l.publicName.value, manufacturer: l.manufacturer.value, model: l.model.value}]))});
        toast('Публичные сведения сохранены', 'ok');
        saved(made);
      } catch (e) { err.textContent = e.message; err.hidden = false; } finally { self.disabled = false; }
    }, 'primary');
    return h('div', {class: 'card stack'}, h('h3', {}, 'Публичные сведения'),
      h('p', {class: 'small muted'}, 'Это и только это о мастерской попадает в каждый выпуск: название, описание, ссылка, автор и публичные названия лазеров. '
        + 'Местные названия лазеров, имена файлов, фотографии и заметки не публикуются.'),
      h('div', {class: 'grid g2'}, field('Название лаборатории', name), field('Автор', author), field('Ссылка лаборатории', url, 'адрес https; пусто — без ссылки'),
        field('Организация', organization), field('Ссылка автора', authorUrl), field('Описание', description)),
      lasers.length ? lasers.map((l) => l.el) : h('p', {class: 'muted small'}, 'Лазеров пока нет: добавьте лазер в разделе «Лазеры».'), err, save);
  }

  /** What «Подготовка публикации» shows of a preview: the same for a file and for the cloud. */
  function previewBody(p) {
    return [facts([['Фотографий', p.photographs], ['Гравировок', p.engravings], ['Измерений', p.measurements], ['Тональных профилей', p.tone_profiles],
      ['Установок (лазер и линза)', p.setups], ['Титана', p.materials]]),
    h('p', {class: 'small'}, h('strong', {}, 'Публично: '), `${p.public.name || 'название не задано'}; автор ${p.public.author || 'не задан'}`
        + (p.public.organization ? `, ${p.public.organization}` : '') + '; лазеры: '
        + (Object.values(p.public.lasers || {}).map((l) => l.public_name).join(', ') || 'нет')),
    Object.keys(p.tokenised || {}).length ? h('details', {class: 'small'}, h('summary', {}, 'Настройки, которые станут токенами'),
      h('ul', {}, Object.entries(p.tokenised).map(([tag, values]) => h('li', {}, `${tag}: ${values.join(', ')}`)))) : h('p', {class: 'small muted'}, 'Текстовых настроек, которые пришлось бы заменить токенами, нет.'),
    h('p', {class: 'small muted'}, 'Никогда не публикуется: ' + (p.never || []).map((k) => NEVER[k] || k).join(', ') + '.'),
    p.ready ? h('p', {class: 'alert ok'}, 'Выпуск можно записать.') : h('p', {class: 'alert warn'}, p.photographs
      ? 'Перед публикацией укажите публичное название лаборатории и автора.' : 'Публиковать нечего: принятых фотографий ещё нет.')];
  }

  /** The written releases, a line each, the newest first: when, the hash, what it holds, whether it went to the cloud; its file at the end. */
  function exportsList(terms, exports) {
    const created = (e) => e.created_at;
    return App.list({id: 'labs-exports', items: exports, key: (e) => e.release_id,
      row: (e) => [h('span', {}, when(e.created_at)), h('span', {class: 'muted'}, short(e.content_sha256)), h('span', {class: 'lst-text small'}, countsText(e.counts)),
        e.published ? pill(`облако № ${e.published.release_number}`, 'ok') : null],
      details: (e) => facts([['Выпуск', short(e.content_sha256)], ['Содержимое', countsText(e.counts)], ['Условия', termsName(termsOf(terms, (e.terms || {}).id))],
        ['Размер', mb(e.bytes || 0)], ['Облако', e.published ? `№ ${e.published.release_number} · ${day(e.published.published_at)}` : 'не опубликован']]),
      actions: (e) => [e.file ? h('a', {class: 'btn btn-small', href: `/api/labs/own/releases/${encodeURIComponent(e.release_id)}/file`, download: ''}, 'Скачать')
        : h('span', {class: 'muted small'}, 'файл не сохранён')],
      filters: [{key: 'cloud', label: 'Облако', options: [['yes', 'в облаке'], ['no', 'только файлом']], test: (e, v) => !!e.published === (v === 'yes')}],
      sorts: [['new', 'Сначала новые', newest(created)], ['old', 'Сначала старые', oldest(created)]]}).el;
  }

  function previewCard(terms, exports, written) {
    const out = h('div', {class: 'stack'});
    const termsSelect = h('select', {'aria-label': 'Условия использования'}, terms.map((t) => h('option', {value: t.id}, `${termsName(t)} — ${(t.summary && t.summary.ru) || ''}`)));
    const result = h('div', {class: 'stack'});
    let ready = false;
    const prepare = btn('Подготовка публикации', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const p = await post('/labs/own/preview', {selection: null});
        ready = p.ready;
        write.disabled = !ready;
        fill(out, previewBody(p));
      } catch (e) { fill(out, h('p', {class: 'alert bad'}, e.message)); } finally { self.disabled = false; }
    });
    const write = btn('Записать выпуск', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const made = await post('/labs/own/releases', {selection: null, terms: termsSelect.value});
        const m = made.manifest;
        fill(result, h('p', {class: 'alert ok'}, `Выпуск записан: ${short(m.content_sha256)} · ${countsText(m.counts)} · ${termsName(termsOf(terms, (m.usage_terms || {}).id))}. `,
          h('a', {href: made.download, download: ''}, 'Скачать файл .tcelab')));
        toast('Выпуск записан', 'ok');
        written();
      } catch (e) { fill(result, h('p', {class: 'alert bad'}, e.message)); } finally { self.disabled = !ready; }
    }, 'primary', true);
    return h('div', {class: 'card stack'}, h('h3', {}, 'Публикация'),
      h('p', {class: 'small muted'}, 'Выпуск — файл .tcelab с числовыми результатами всех принятых фотографий: измеренные цвета, рецепты, тональные профили, установки и титан. '
        + 'Сначала посмотрите, что в него войдёт; выпуск не меняется после записи.'),
      h('div', {class: 'row'}, prepare, field('Условия использования', termsSelect), write), out, result,
      exports.length ? h('div', {class: 'stack'}, h('h4', {}, 'Записанные выпуски'), exportsList(terms, exports))
        : h('p', {class: 'muted small'}, 'Выпусков ещё нет.'));
  }

  function withdrawalCard(exports, withdrawals, declared) {
    const kind = h('select', {'aria-label': 'Что отзывается'}, Object.entries(TARGET).map(([id, name]) => h('option', {value: id}, name)));
    const target = h('input', {placeholder: 'идентификатор (UUID)', 'aria-label': 'Идентификатор'});
    const reason = h('textarea', {rows: 2, placeholder: 'Причина отзыва', 'aria-label': 'Причина отзыва'});
    const replacement = h('select', {'aria-label': 'Выпуск-замена'}, h('option', {value: ''}, 'без замены'),
      exports.map((e) => h('option', {value: e.release_id}, `${when(e.created_at)} · ${short(e.content_sha256)}`)));
    const released = h('select', {'aria-label': 'Записанный выпуск'}, h('option', {value: ''}, 'выберите выпуск'),
      exports.map((e) => h('option', {value: e.release_id}, `${when(e.created_at)} · ${short(e.content_sha256)}`)));
    released.addEventListener('change', () => { target.value = released.value; });
    const switchKind = () => { released.hidden = kind.value !== 'release'; };
    kind.addEventListener('change', switchKind);
    switchKind();
    const err = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const send = btn('Отозвать', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true; err.hidden = true;
      try {
        await post('/labs/own/withdrawals', {target_kind: kind.value, target_id: target.value.trim(), reason: reason.value, replacement_release_id: replacement.value || null});
        toast('Отзыв записан: он уйдёт с каждым следующим выпуском', 'ok');
        declared();
      } catch (e) { err.textContent = e.message; err.hidden = false; } finally { self.disabled = false; }
    }, 'danger');
    return h('div', {class: 'card stack'}, h('h3', {}, 'Отзыв опубликованного'),
      h('p', {class: 'small muted'}, 'Опубликованный выпуск не меняется. Если в нём ошибка, объявите отзыв выпуска, измерения или тонального профиля с причиной и, если есть, '
        + 'выпуском-заменой: заявление уходит с каждым следующим выпуском, и у получателей отозванное исключается из новых работ.'),
      h('div', {class: 'grid g2'}, field('Что отзывается', kind), h('div', {class: 'f'}, h('label', {class: 'f'}, h('span', {}, 'Идентификатор'), target), released),
        field('Причина', reason), field('Выпуск-замена', replacement)), err, send,
      withdrawals.length ? table(['Объявлен', 'Что', 'Идентификатор', 'Причина', 'Замена'], withdrawals.map((w) => [when(w.declared_at), TARGET[w.target_kind] || w.target_kind,
        short(w.target_id), w.reason, w.replacement_release_id ? short(w.replacement_release_id) : '—']), '', true) : h('p', {class: 'muted small'}, 'Отзывов нет.'));
  }

  async function ownTab() {
    const el = h('div', {class: 'stack'});
    async function show() {
      const data = await get('/labs/own');
      fill(el, publicForm(data.public, show), previewCard(data.terms, data.exports, show), await LabsCloud.ownCard(data.terms, show),
        withdrawalCard(data.exports, data.withdrawals, show));
    }
    await show();
    return el;
  }

  // ---- «Подключённые лаборатории»: a file --------------------------------------------------------------------------------------------

  /** What a chosen file declares, before anything is connected; «Подключить» starts the job, «Не подключать» forgets the file. */
  function inspectCard(info, done) {
    const lab = info.lab || {}, a = info.attribution || {}, r = info.release || {}, c = info.compatibility || {};
    const el = h('div', {class: 'card stack lab-inspect'});
    const progress = h('div', {class: 'stack', hidden: true});
    const connect = btn('Подключить', async () => {
      connect.disabled = true; forget.disabled = true;
      try { await connectJob(info.token, progress, done); } catch (e) { fail(e); } finally { connect.disabled = false; forget.disabled = false; }
    }, 'primary');
    const forget = btn('Не подключать', async () => {
      try { await del(`/labs/files/${encodeURIComponent(info.token)}`); el.remove(); } catch (e) { fail(e); }
    });
    return fill(el, h('h3', {}, 'Файл выпуска: ', h('span', {class: 'lab-name'}, lab.name || 'лаборатория без названия'), verifiedPill(info.verified)),
      facts([['Описание', lab.description], ['Ссылка', safeLink(lab.url)], ['Автор', [a.name, a.organization].filter(Boolean).join(', ') || null], ['Ссылка автора', safeLink(a.url)],
        ['Выпуск', `${r.release_number != null ? `№ ${r.release_number} · ` : ''}от ${day(r.created_at)} · ${short(r.content_sha256)}`],
        ['Содержимое', countsText(r.counts)], ['Размер', mb(info.bytes || 0)], ['Условия', termsName(info.terms)],
        ['Совместимость', c.newer_minor ? `выпуск новее этой версии (схема ${c.schema_version}): неизвестные поля сохраняются и не используются`
          : `читается полностью (схема ${c.schema_version || '—'})`],
        ['Установки', (info.equipment || []).map((e) => `${e.laser}${e.focal_length_mm == null ? '' : ` · линза ${+e.focal_length_mm} мм`}`).join('; ') || 'нет'],
        ['Титан', (info.materials || []).map(materialName).join('; ') || 'нет']]),
      info.own ? h('p', {class: 'alert warn'}, 'Это выпуск собственной лаборатории этой мастерской: её результаты уже здесь.') : null,
      info.connected ? h('p', {class: 'alert'}, info.connected.same ? 'Этот выпуск уже подключён: тот же файл.' : 'Выпуск с этим идентификатором уже подключён, но содержимое другое.') : null,
      h('p', {class: 'small muted'}, 'Пока ничего не подключено: файл только прочитан. Подключение проверяет каждую запись файла, идёт в фоне и его можно отменить.'),
      h('div', {class: 'row'}, connect, forget), progress);
  }

  /** A job in the background (a connection from a file or from the cloud, a publication): `start()` starts it, then it is polled at
      `jobs`/<id> every 300 ms with a bar of bytes; «Отменить» asks the server to stop. Resolves with the final job, null when it did not start. */
  function followJob({start, jobs = '/labs/jobs', box, done, label = 'Подключение выпуска', phases = PHASE, success = null}) {
    return new Promise((resolve) => {
      let job = null, timer = null;
      const bar = h('div', {class: 'lab-bar'}, h('div', {class: 'lab-bar-fill'}));
      const text = h('span', {class: 'small'});
      const cancel = btn('Отменить', async () => { if (job) { try { await post(`${jobs}/${job.id}/cancel`, {}); } catch (e) { fail(e); } } }, 'btn-small');
      const meter = h('div', {role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-label': label}, bar);
      box.hidden = false;
      fill(box, h('div', {class: 'row'}, text, h('span', {class: 'spacer'}), cancel), meter);
      const show = () => {
        const percent = job.total ? Math.round(job.read / job.total * 100) : 0;
        bar.firstChild.setAttribute('style', `width:${percent}%`);
        meter.setAttribute('aria-valuenow', String(percent));
        text.textContent = `${phases[job.phase] || PHASE[job.phase] || job.phase} · ${mb(job.read || 0)} из ${mb(job.total || 0)} (${percent} %)`;
      };
      const finish = () => {
        clearInterval(timer);
        cancel.disabled = true;
        if (job.error) fill(box, h('p', {class: 'alert bad', role: 'alert'}, I18N.tr(job.error.message)));
        else if (success) { fill(box, h('p', {class: 'alert ok'}, success(job))); done(job.result, job); }
        else {
          fill(box, h('p', {class: 'alert ok'}, job.phase === 'unchanged' ? 'Этот выпуск уже был подключён: ничего не изменилось.' : 'Лаборатория подключена: её выпуск можно выбирать источником новых работ.'));
          toast(job.phase === 'unchanged' ? 'Выпуск уже подключён' : 'Лаборатория подключена', 'ok');
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
    const input = h('input', {type: 'file', accept: '.tcelab', 'aria-label': 'Файл выпуска лаборатории'});
    const shown = h('div', {});
    const read = btn('Прочитать файл', async (ev) => {
      const file = input.files && input.files[0];
      if (!file) return fail(new Error('Выберите файл выпуска лаборатории (.tcelab)'));
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const fd = new FormData();
        fd.append('release', file, file.name);
        fill(shown, inspectCard(await form('/labs/files', fd), connected));
      } catch (e) { fill(shown, h('p', {class: 'alert bad', role: 'alert'}, e.message)); } finally { self.disabled = false; }
    }, 'primary');
    return h('div', {class: 'stack'}, h('div', {class: 'card stack'}, h('h3', {}, 'Подключить лабораторию из файла'),
      h('p', {class: 'small muted'}, 'Выпуск другой лаборатории — файл .tcelab. Сначала он читается и показывается: кто автор, какой выпуск, какие установки и титан, '
        + 'на каких условиях. Подключается только после вашего «Подключить».'),
      h('div', {class: 'row'}, App.filePick(input, 'Выбрать файл .tcelab'), read)), shown);
  }

  // ---- the connected laboratories ------------------------------------------------------------------------------------------------

  const releaseLine = (cur) => `${cur.release_number != null ? `№ ${cur.release_number} · ` : ''}${releaseName(cur)}`;

  /** What a connected laboratory holds, under its line: the current release, its signature, terms and author, since when it is here. */
  function sourceDetails(s) {
    const cur = s.current;
    return h('div', {class: 'stack small'},
      cur ? h('p', {}, `${releaseLine(cur)} · ${countsText(cur.counts)}`) : h('p', {class: 'muted'}, 'Текущего выпуска нет: файлы удалены.'),
      cur ? h('p', {}, verifiedPill(cur.verified), ` · условия: ${termsName(cur.terms)} · автор: ${(cur.attribution || {}).name || '—'}`) : null,
      h('p', {class: 'muted'}, `подключена ${when(s.connected_at)} · выпусков на компьютере: ${s.kept} · отзывов: ${s.withdrawals}`));
  }

  /** The connected laboratories, a line each (name, state, current release), «Открыть» at the end; the details under a line. */
  function connectedList(list) {
    return App.list({id: 'labs-sources', items: list, key: (s) => s.id,
      row: (s) => {
        const [status, tone] = STATUS[s.status] || [s.status, ''];
        return [h('span', {class: 'lab-name lst-text'}, s.name), pill(status, tone), s.release_withdrawn ? pill('выпуск отозван владельцем', 'bad') : null,
          h('span', {class: 'muted small'}, s.current ? releaseLine(s.current) : 'текущего выпуска нет')];
      },
      details: sourceDetails,
      actions: (s) => [btn('Открыть', () => go(`/labs?tab=sources&source=${s.id}`), 'primary btn-small')],
      search: (s) => s.name,
      filters: [{key: 'status', label: 'Состояние', options: Object.entries(STATUS).map(([k, [text]]) => [k, text]), test: (s, v) => s.status === v}],
      sorts: [['name', 'По названию', (p, q) => String(p.name).localeCompare(String(q.name), 'ru')], ['recent', 'Сначала недавно подключённые', newest((s) => s.connected_at)]]}).el;
  }

  async function sourcesList() {
    const el = h('div', {class: 'stack'});
    async function show() {
      const list = await get('/labs/sources');
      fill(el, await LabsCloud.automaticNotices(show), LabsCloud.updatesCard(list, show), list.length ? connectedList(list)
        : h('div', {class: 'card empty'}, h('h3', {}, 'Подключённых лабораторий нет'), h('p', {class: 'muted'}, 'Подключите лабораторию из каталога облака или из файла .tcelab: её цвета и шкалы станут источником новых работ.')));
    }
    await show();
    return h('div', {class: 'stack'}, fileCard(show), el);
  }

  // ---- one laboratory: releases, palettes, transfers -------------------------------------------------------------------------------

  function differencesDialog(release) {
    get(`/labs/releases/${encodeURIComponent(release.release_id)}/differences`).then((d) => {
      const rows = (part) => Object.entries(d[part] || {}).filter(([, n]) => n).map(([k, n]) => `${SECTION[k] || k}: ${n}`).join(' · ') || 'ничего';
      modal(`Различия выпуска ${short(release.content_sha256)}`, h('div', {class: 'stack'},
        h('p', {class: 'small'}, d.against ? `Против выпуска ${short(d.against)}:` : 'Прежнего выпуска нет: всё содержимое новое.'),
        facts([['Добавлено', rows('added')], ['Изменено', rows('changed')], ['Удалено', rows('removed')], ['Отзывов в выпуске', d.withdrawn]])),
      [{label: 'Закрыть', run: (m) => m.close()}]);
    }).catch(fail);
  }

  /** The releases of one laboratory, a line each, the newest first: when, its number and hash, whether it is the current one, withdrawn or
      removed; the signature and the works that use it under the line; «Различия» and «Удалить файлы» at the end. */
  function releasesList(card, reload) {
    const created = (r) => r.created_at;
    const works = (r) => (r.works.length ? h('span', {}, r.works.map((w, i) => [i ? ', ' : null,
      link(w.mode === 'photo_work' ? `/photo-engraving?work=${w.plan_id}` : `/vector?plan=${w.plan_id}`, w.name)])) : 'ни одна работа его не использует');
    return App.list({id: 'labs-releases', items: card.releases, key: (r) => r.release_id, empty: 'Выпусков нет',
      row: (r) => [h('span', {}, when(r.created_at)), h('span', {class: 'muted'}, r.release_number == null ? '№ —' : `№ ${r.release_number}`),
        h('span', {class: 'lst-text muted small'}, short(r.content_sha256)), card.current && card.current.release_id === r.release_id ? pill('текущий', 'ok') : null,
        r.withdrawn ? pill('отозван', 'bad') : null, r.status === 'removed' ? pill('файлы удалены', '') : null, r.works.length ? pill(`работ: ${r.works.length}`) : null],
      details: (r) => facts([['Хеш', r.content_sha256], ['Подпись', verifiedPill(r.verified)], ['Файлы', r.status === 'removed' ? 'удалены' : 'на компьютере'], ['Работы', works(r)]]),
      actions: (r) => [btn('Различия', () => differencesDialog(r), 'btn-small'),
        r.status === 'removed' ? null : btn('Удалить файлы', () => confirmBox(`Удалить файлы выпуска ${short(r.content_sha256)}?`,
          'Запись о выпуске останется; его файлы исчезнут с компьютера. Пока выпуск использует сохранённая работа, он не удаляется.',
          'Удалить', async () => { await del(`/labs/releases/${encodeURIComponent(r.release_id)}`); toast('Файлы выпуска удалены', 'ok'); reload(); }), 'danger btn-small')],
      filters: [{key: 'files', label: 'Файлы', options: [['kept', 'на компьютере'], ['removed', 'файлы удалены']], test: (r, v) => (r.status === 'removed') === (v === 'removed')}],
      sorts: [['new', 'Сначала новые', newest(created)], ['old', 'Сначала старые', oldest(created)]]}).el;
  }

  function withdrawalsTable(list) {
    return table(['Объявлен', 'Что', 'Идентификатор', 'Причина', 'Замена', 'Узнали'], list.map((w) => [when(w.declared_at), TARGET[w.target_kind] || w.target_kind,
      short(w.target_id), w.reason, w.replacement_release_id ? short(w.replacement_release_id) : '—', `${when(w.learned_at)} · ${short(w.learned_from)}`]), 'Отзывов нет', true);
  }

  /** «Проверить у себя»: a test plate of one colour of the release on the own laser for the own titanium (POST /labs/transfers). */
  async function transferDialog(request, entry, made) {
    const [devices, materials] = await Promise.all([get('/devices'), get('/materials')]);
    if (!devices.length || !materials.length) throw new Error('Сначала добавьте лазер и заготовку титана этой мастерской');
    const laser = h('select', {'aria-label': 'Свой лазер'}, devices.map((d) => h('option', {value: d.id}, d.title || d.name)));
    const stock = h('select', {'aria-label': 'Свой титан'}, materials.map((m) => h('option', {value: m.id}, [m.name, m.grade, m.batch].filter(Boolean).join(' · '))));
    modal('Проверить цвет у себя', h('div', {class: 'stack'},
      h('p', {}, swatch(entry.lab), labText(entry.lab), h('span', {class: 'small muted'}, ` · ${recipeText(entry.recipe)}`)),
      h('p', {class: 'small'}, 'Рецепт выпуска гравируется одной ячейкой на вашем лазере с установленной сейчас линзой; настройки, которые ваш лазер не выполнит, '
        + 'отклоняются, а не подгоняются. Фото пластины измеряется как ваш эксперимент и сравнивается с цветом выпуска по ΔE; статистику выпуска оно не меняет.'),
      h('div', {class: 'grid g2'}, field('Свой лазер', laser), field('Свой титан', stock))), [
      {label: 'Отмена', run: (m) => m.close()},
      {label: 'Создать пластину', cls: 'primary', run: async (m) => {
        const plate = await post('/labs/transfers', {...request, entry_id: entry.id, device_id: +laser.value, material_id: +stock.value});
        toast('Пластина переноса создана', 'ok');
        m.close();
        made(plate);
      }}]);
  }

  /** The colours of fill of a setup, a line each (colour, basis, engravings, agreement, recipe), «Проверить у себя» at the end; in the
      release's order or by lightness or engravings, by basis and concern, twenty at a time. */
  function paletteList(request, offered, made) {
    const lightness = (e) => (e.lab ? +e.lab[0] : 0);
    const colours = offered.entries.length ? App.list({items: offered.entries, key: (e) => e.id, className: 'lab-colours',
      row: (e) => [swatch(e.lab), h('strong', {}, labText(e.lab)), pill(BASIS[e.basis] || e.basis || '—'),
        pill(`гравировок ${e.engravings}`), pill(agreed(e.agreement), e.caution || (e.agreement && e.agreement.differing) ? 'warn' : 'ok'),
        e.caution ? pill(CAUTION[e.caution] || e.caution, 'warn') : null, h('span', {class: 'lst-text small muted'}, recipeText(e.recipe))],
      actions: (e) => [btn('Проверить у себя', () => transferDialog(request, e, made).catch(fail), 'btn-small')],
      filters: [{key: 'basis', label: 'Основа измерения', options: Object.entries(BASIS), test: (e, v) => e.basis === v},
        {key: 'caution', label: 'Оговорки', options: [['none', 'без оговорок'], ['some', 'с оговоркой']], test: (e, v) => !e.caution === (v === 'none')}],
      sorts: [['release', 'Как в выпуске'], ['light', 'Сначала светлые', (p, q) => lightness(q) - lightness(p)], ['dark', 'Сначала тёмные', (p, q) => lightness(p) - lightness(q)],
        ['engravings', 'Больше гравировок', (p, q) => (q.engravings || 0) - (p.engravings || 0)]]}).el : null;
    return h('div', {class: 'stack'},
      h('p', {class: 'small'}, `Цветов заливки: ${offered.entries.length}` + (offered.conditions && offered.conditions.length ? '. ' + offered.conditions.map((c) => I18N.tr(c)).join(' ') : '')),
      colours || h('p', {class: 'muted small'}, 'Цветов заливки с этой установкой в выпуске нет.'));
  }

  function scalesList(offered) {
    const scales = offered.scales || [];
    return h('div', {class: 'stack'}, h('p', {class: 'small'}, `Шкал серого: ${scales.length}`),
      scales.length ? h('ul', {class: 'stack small'}, scales.map((sc) => h('li', {}, PhotoPanels.settingsText(sc.mode, sc.dpi),
        sc.span ? ` · ${num(sc.span[0], 1)}–${num(sc.span[1], 1)} %` : '', sc.size && sc.size.measured_mm ? ` · ширина ${sc.size.measured_mm.map((v) => num(v, 1)).join(', ')} мм` : '',
        sc.material ? ` · ${[sc.material.family, sc.material.grade].filter(Boolean).join(' ')}` : ''))) : null);
  }

  function setupBlock(choice, setup, made) {
    const request = {release_id: choice.release.release_id, laser: setup.laser.uuid, lens: setup.lens ? setup.lens.uuid : null, material: setup.material ? setup.material.uuid : null};
    const out = h('div', {});
    const palette = setup.material ? btn('Палитра', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { fill(out, paletteList(request, await post('/labs/palette', request), made)); } catch (e) { fill(out, h('p', {class: 'alert bad'}, e.message)); } finally { self.disabled = false; }
    }, 'btn-small') : null;
    const scales = btn('Шкалы серого', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { fill(out, scalesList(await post('/labs/scales', {release_id: request.release_id, laser: request.laser, lens: request.lens}))); }
      catch (e) { fill(out, h('p', {class: 'alert bad'}, e.message)); } finally { self.disabled = false; }
    }, 'btn-small');
    return h('div', {class: 'card stack lab-setup-card'}, h('div', {class: 'row'}, h('strong', {}, setupName(setup)), pill(`фото ${setup.photographs}`), h('span', {class: 'spacer'}), palette, scales), out);
  }

  /** The transfer plates made from a release, a line each (the release's colour, the plate, the measured ΔE), the newest first; the recipe,
      the own titanium and every measurement under the line; the plate at the end. */
  function transfersList(list) {
    const measured = (t) => t.measurements.length > 0;
    return App.list({id: 'labs-transfers', items: list, key: (t) => t.plan_id,
      row: (t) => [swatch(t.source.lab), h('span', {class: 'lst-text'}, `${t.name} · ${t.identifier}`),
        measured(t) ? pill(`измерений ${t.measurements.length} · средняя ΔE ${num(t.mean_delta_e, 1)}`, t.mean_delta_e <= 5 ? 'ok' : 'warn') : pill('ждёт фото', 'warn'),
        h('span', {class: 'muted small'}, day(t.created_at))],
      details: (t) => h('div', {class: 'stack small'},
        h('p', {}, `цвет выпуска ${labText(t.source.lab)} · ${[t.own_material.name, t.own_material.grade].filter(Boolean).join(' · ')} · ${when(t.created_at)}`),
        h('p', {class: 'muted'}, recipeText(t.recipe)),
        measured(t) ? h('p', {}, t.measurements.map((m, i) => [i ? ' · ' : null, swatch(m.lab), link(`/analysis/${m.pair_id}`, `ΔE ${num(m.delta_e, 1)}`), ` (${day(m.measured_at)})`]))
          : h('p', {class: 'muted'}, 'Фото пластины ещё не принято: гравируйте её и добавьте фотографию в «Эксперименты».')),
      actions: (t) => [h('a', {class: 'btn btn-small', href: `#/plans/${t.plan_id}`}, 'Открыть')],
      filters: [{key: 'measured', label: 'Измерено', options: [['yes', 'измерены'], ['no', 'ждут фото']], test: (t, v) => measured(t) === (v === 'yes')}],
      sorts: [['new', 'Сначала новые', newest((t) => t.created_at)], ['delta', 'Сначала большая ΔE', (p, q) => (q.mean_delta_e ?? -1) - (p.mean_delta_e ?? -1)]]}).el;
  }

  async function transfersBlock(releaseId) {
    const el = h('div', {class: 'stack'});
    const notice = h('div', {});
    async function show() {
      let list;
      try { list = await get(`/labs/transfers?release_id=${encodeURIComponent(releaseId)}`); } catch (e) { return fill(el, h('p', {class: 'alert bad'}, e.message)); }
      fill(el, list.length ? transfersList(list) : h('p', {class: 'muted small'}, 'Переносов с этого выпуска ещё нет.'));
    }
    await show();
    return {el: h('div', {class: 'stack'}, notice, el), made: (plate) => {
      fill(notice, h('p', {class: 'alert ok'}, 'Пластина переноса создана: ', link(`/plans/${plate.plan_id}`, plate.name || `план ${plate.plan_id}`), '. Гравируйте её и добавьте фото.'));
      show();
    }};
  }

  async function sourceScreen(id) {
    const [card, choices] = await Promise.all([get(`/labs/sources/${id}`), get('/labs/choices').catch(() => [])]);
    const lab = card.lab || {}, cur = card.current, [status, tone] = STATUS[card.status] || [card.status, ''];
    const reload = () => App.render({preserveScroll: true});
    const toggle = card.status === 'connected'
      ? btn('Отключить', () => confirmBox(`Отключить лабораторию «${card.name}»?`, 'Она перестанет предлагаться источником новых работ; её выпуски остаются для работ, которые их используют.',
        'Отключить', async () => { await post(`/labs/sources/${id}/disconnect`, {}); toast('Лаборатория отключена', 'ok'); reload(); }), 'danger btn-small')
      : btn('Подключить снова', async () => { try { await post(`/labs/sources/${id}/reconnect`, {}); toast('Лаборатория снова подключена', 'ok'); reload(); } catch (e) { fail(e); } }, 'primary btn-small');
    const choice = choices.find((c) => c.source_id === card.id) || null;
    const transfers = cur ? await transfersBlock(cur.release_id) : null;
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('a', {class: 'btn btn-small', href: '#/labs?tab=sources'}, '← Подключённые лаборатории'),
        h('div', {}, h('h2', {}, h('span', {class: 'lab-name'}, card.name), ' ', pill(status, tone)),
          h('p', {class: 'sub'}, [lab.description, cur ? `автор: ${(cur.attribution || {}).name || '—'}` : null, lab.url ? `ссылка: ${lab.url}` : null].filter(Boolean).join(' · '))),
        h('span', {class: 'spacer'}), toggle),
      LabsCloud.sourceCard(card, reload),
      h('div', {class: 'card stack'}, h('h3', {}, 'Выпуски'), releasesList(card, reload)),
      h('div', {class: 'card stack'}, h('h3', {}, 'Отзывы лаборатории'), withdrawalsTable(card.withdrawal_list || [])),
      h('div', {class: 'card stack'}, h('h3', {}, 'Палитра и шкалы текущего выпуска'),
        choice ? h('div', {class: 'stack'}, h('p', {class: 'small muted'}, 'Каждая установка, измеренная выпуском: её цвета заливки с рецептами и шкалы серого. Цвет показан с Lab и основой измерения; '
          + 'экранный цвет — только отображение. «Проверить у себя» гравирует рецепт на вашем лазере.'),
          choice.setups.map((s) => setupBlock(choice, s, transfers ? transfers.made : () => {})))
          : h('p', {class: 'muted small'}, 'Лаборатория не предлагается источником новых работ: она отключена, её выпуск отозван или удалён.')),
      transfers ? h('div', {class: 'card stack'}, h('h3', {}, 'Проверено у себя'), transfers.el) : null);
  }

  // ---- the screen ------------------------------------------------------------------------------------------------------------------

  App.register({id: 'labs', async render(ctx) {
    if (ctx.query.source) return sourceScreen(encodeURIComponent(ctx.query.source));
    const [own, sources, catalogue] = await Promise.all([ownTab(), sourcesList(), LabsCloud.catalogueTab()]);
    const tabs = App.tabs([['own', 'Моя лаборатория', own], ['sources', 'Подключённые лаборатории', sources], ['catalogue', 'Каталог лабораторий', catalogue]],
      {initial: ['sources', 'catalogue'].includes(ctx.query.tab) ? ctx.query.tab : 'own', remember: ctx.query.tab ? null : 'labs.tab', label: 'Лаборатории', prefix: 'labs-tab'});
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Лаборатории'),
        h('p', {class: 'sub'}, 'Переносимые результаты: выпуск своей лаборатории файлом .tcelab или в облако и подключённые выпуски других мастерских — из каталога облака или из файла — '
          + 'как источник измерений для новых работ.'))),
      tabs.list, h('div', {class: 'labs-panels'}, tabs.panels));
  }});

  LabsCloud.install({followJob, previewBody, countsText, termsName, differencesDialog, mb});
})();
