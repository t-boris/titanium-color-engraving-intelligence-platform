/* Мастерская (feature electron, REQ-080, REQ-081): где лежат данные, какая у них схема, кто их держит; папка резервных копий; полная
   резервная копия и список сделанных с проверкой и восстановлением в другую папку. Замена открытой мастерской копией — отдельный явный
   выбор: окно называет папку, которая будет отложена, и требует ввести слово подтверждения. Копии базы, которые приложение само делает
   перед сменой схемы, перечислены отдельно с объяснением. Экспорт диагностики — один небольшой zip без фотографий, базы и файлов работ.
   Адрес: #/workshop. */
'use strict';
(() => {
  const {h, fill, btn, field, pill, get, post, put, toast, modal, facts, table} = App;
  const CONFIRM_WORD = 'overwrite';                       // the word the API expects before the open workshop is replaced
  const mb = (bytes) => (bytes == null ? '—' : bytes >= 1024 * 1024 * 1024 ? `${(bytes / 1024 / 1024 / 1024).toFixed(1).replace('.', ',')} ГБ`
    : `${(bytes / 1024 / 1024).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0).replace('.', ',')} МБ`);
  const when = (iso) => (iso ? `${iso.slice(0, 10)} ${iso.slice(11, 16)}` : '—');
  const errorBox = () => h('p', {class: 'alert bad', role: 'alert', hidden: true});
  const showError = (box, e) => { box.textContent = e.message || String(e); box.hidden = false; };
  const KIND = {schema: 'перед сменой схемы', release: 'перед обновлением версии', other: 'копия базы'};

  // ---- the workshop itself -------------------------------------------------------------------------------------------------------

  function workshopCard(w, changed) {
    const dir = h('input', {value: w.backup_dir || '', placeholder: w.default_backup_dir, 'aria-label': 'Папка резервных копий'});
    const err = errorBox();
    const change = btn('Изменить', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true; err.hidden = true;
      try {
        const made = await put('/workshop/backup-dir', {path: dir.value});
        toast('Папка резервных копий сохранена', 'ok');
        changed(made.backup_dir);
      } catch (e) { showError(err, e); } finally { self.disabled = false; }
    });
    const schema = w.schema === w.schema_known ? pill(`схема ${w.schema}`, 'ok') : pill(`схема ${w.schema} из ${w.schema_known}`, 'warn');
    return h('div', {class: 'card stack'}, h('h3', {}, 'Мастерская'),
      facts([['Папка данных', w.data_dir], ['Версия приложения', w.app], ['Схема базы', schema],
        ['Открыта процессом', w.lock ? `${w.lock.program || 'titanium-platform'} (pid ${w.lock.pid})` : 'не заблокирована'],
        ['Свободно на диске', `${mb(w.disk.free_bytes)} из ${mb(w.disk.total_bytes)}`]]),
      field('Папка резервных копий', h('div', {class: 'row'}, dir, change), 'сюда записываются резервные копии и файлы диагностики; пусто — папка по умолчанию'),
      err);
  }

  // ---- backups -------------------------------------------------------------------------------------------------------------------

  function inspectDialog(b) {
    const body = h('div', {class: 'stack'}, h('p', {class: 'muted small'}, 'Проверяются размер и хеш каждого файла копии…'));
    const m = modal('Проверка резервной копии', body, [{label: 'Закрыть', run: (d) => d.close()}]);
    post('/workshop/backups/inspect', {path: b.path, verify: true}).then((seen) => {
      const man = seen.manifest || {};
      fill(body, facts([['Папка', seen.path], ['Сделана', when(man.created_at)], ['Версия приложения', man.app], ['Схема', man.schema],
        ['Файлов', man.files], ['Размер', mb(man.bytes)], ['Мастерская', man.data_dir]]),
      seen.complete ? h('p', {class: 'alert ok'}, 'Копия полная: каждый файл на месте и совпадает с записанным хешем.')
        : h('div', {class: 'stack'}, h('p', {class: 'alert bad'}, 'Копия неполная или повреждена: восстановление из неё будет отказано.'),
          h('ul', {class: 'small'}, (seen.problems || []).map((p) => h('li', {}, I18N.tr(p))))));
    }).catch((e) => fill(body, h('p', {class: 'alert bad'}, e.message)));
    return m;
  }

  function restoreDialog(b, w, done) {
    const target = h('input', {placeholder: 'например, ~/titanium-restored', 'aria-label': 'Папка для восстановления'});
    const err = errorBox();
    const body = h('div', {class: 'stack'},
      h('p', {class: 'small'}, `Копия от ${when((b.manifest || {}).created_at)} (${mb((b.manifest || {}).bytes)}) будет восстановлена в новую папку: `
        + 'база, файлы работ, подключённые выпуски и шрифты; пути в записях переписываются на новую папку. Открытая мастерская не меняется.'),
      field('Папка для восстановления', target, 'пустая или новая папка; непустая папка будет отказана'), err);
    return modal('Восстановить в другую папку', body, [{label: 'Отмена', run: (d) => d.close()},
      {label: 'Восстановить', cls: 'primary', run: async (d) => {
        err.hidden = true;
        try {
          const made = await post('/workshop/restore', {path: b.path, target_dir: target.value.trim()});
          toast(`Мастерская восстановлена в ${made.path}`, 'ok');
          d.close();
          done(made);
        } catch (e) { showError(err, e); }
      }}]);
  }

  function replaceDialog(b, w, done) {
    const word = h('input', {placeholder: CONFIRM_WORD, 'aria-label': 'Слово подтверждения', autocomplete: 'off'});
    const err = errorBox();
    const go = btn('Заменить мастерскую', async (ev) => {
      const self = ev.currentTarget;
      if (word.value.trim() !== CONFIRM_WORD) { showError(err, new Error(`Введите слово ${CONFIRM_WORD}, чтобы заменить открытую мастерскую`)); return; }
      self.disabled = true; err.hidden = true;
      try {
        const made = await post('/workshop/restore', {path: b.path, target_dir: w.data_dir, overwrite: true, confirm: word.value.trim()});
        fill(body, h('p', {class: 'alert warn'}, `Мастерская заменена копией; прежняя отложена в ${made.set_aside || '—'}. `
          + 'Перезапустите приложение: до перезапуска оно ещё работает с прежними данными в памяти.'));
        done(made);
      } catch (e) { showError(err, e); self.disabled = word.value.trim() !== CONFIRM_WORD; }
    }, 'danger', true);
    word.addEventListener('input', () => { go.disabled = word.value.trim() !== CONFIRM_WORD; });
    const body = h('div', {class: 'stack'},
      h('p', {class: 'alert warn'}, `Открытая мастерская ${w.data_dir} будет заменена копией от ${when((b.manifest || {}).created_at)}. `
        + `Нынешняя папка не удаляется: она будет отложена как ${w.data_dir}.replaced-<дата>. Всё, что сделано после этой копии, останется только там.`),
      field(`Чтобы продолжить, введите слово ${CONFIRM_WORD}`, word), err, go);
    return modal('Заменить открытую мастерскую', body, [{label: 'Закрыть', run: (d) => d.close()}]);
  }

  function backupsCard(w, list, refresh, notice) {
    const err = errorBox();
    const result = h('div', {class: 'stack'}, notice);
    const progress = h('p', {class: 'muted small', hidden: true}, 'Идёт запись резервной копии: база копируется целиком, затем файлы работ, выпуски и шрифты…');
    const make = btn('Сделать резервную копию', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true; err.hidden = true; progress.hidden = false; fill(result);
      try {
        const made = await post('/workshop/backups', {});
        toast('Резервная копия записана', 'ok');
        refresh(h('p', {class: 'alert ok'}, `Резервная копия записана: ${made.path} · файлов ${Object.keys(made.files || {}).length} · ${mb(made.bytes)}.`));
      } catch (e) { showError(err, e); } finally { self.disabled = false; progress.hidden = true; }
    }, 'primary');
    const rows = list.map((b) => {
      const man = b.manifest || {};
      return [when(man.created_at), mb(man.bytes), man.app ? `${man.app} · схема ${man.schema}` : '—',
        `${man.files ?? '—'} файлов${b.complete ? '' : ' · неполная'}`, h('span', {class: 'small muted'}, b.path),
        h('div', {class: 'row'}, btn('Проверить', () => inspectDialog(b)), btn('Восстановить…', () => restoreDialog(b, w, () => refresh())),
          btn('Заменить открытую мастерскую…', () => replaceDialog(b, w, () => refresh()), 'danger'))];
    });
    return h('div', {class: 'card stack'}, h('h3', {}, 'Резервные копии'),
      h('p', {class: 'small muted'}, 'Полная копия мастерской: база с незавершёнными записями журнала, файлы работ и фотографий, подключённые выпуски, собственные выпуски и шрифты, '
        + 'с описанием и хешем каждого файла. Описание записывается последним: незавершённая копия никогда не считается копией.'),
      h('div', {class: 'row'}, make), progress, err, result,
      table(['Сделана', 'Размер', 'Версия', 'Содержимое', 'Папка', ''], rows, 'Резервных копий пока нет.', true));
  }

  function recoveryCard(copies) {
    return h('div', {class: 'card stack'}, h('h3', {}, 'Копии перед сменой схемы'),
      h('p', {class: 'small muted'}, 'Прежде чем изменить устройство своей базы, приложение само записывает её копию в папку backups рядом с данными и проверяет её целостность; '
        + 'только после этого схема меняется. Это не полная резервная копия (без файлов работ): она нужна, чтобы вернуться к прежней версии приложения, если смена схемы не удалась.'),
      table(['Записана', 'Файл', 'Размер', 'Почему'], copies.map((c) => [when(c.modified_at), c.name, mb(c.bytes), KIND[c.kind] || c.kind]), 'Таких копий нет.', true));
  }

  function diagnosticsCard() {
    const err = errorBox();
    const result = h('div', {class: 'stack'});
    const run = btn('Экспорт диагностики', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true; err.hidden = true;
      try {
        const made = await post('/workshop/diagnostics', {});
        fill(result, h('p', {class: 'alert ok'}, `Файл диагностики записан: ${made.path} (${mb(made.bytes)}; ${(made.members || []).join(', ')}). `,
          made.download ? h('a', {href: made.download, download: ''}, 'Скачать') : null));
        toast('Файл диагностики записан', 'ok');
      } catch (e) { showError(err, e); } finally { self.disabled = false; }
    });
    return h('div', {class: 'card stack'}, h('h3', {}, 'Диагностика'),
      h('p', {class: 'small muted'}, 'В файл входят: версии приложения и схемы, платформа, число записей в таблицах, результат проверки целостности базы, список подключённых выпусков '
        + '(идентификаторы и названия), настройки без значений, похожих на ключи, последние строки журналов и последние записи журнала действий. '
        + 'Домашняя папка, адреса почты и всё похожее на ключи и токены заменяются. Не входят: фотографии, файлы работ, сама база и файлы выпусков.'),
      h('div', {class: 'row'}, run), err, result);
  }

  App.register({id: 'workshop', async render() {
    const root = h('div', {class: 'stack'});
    const draw = async (notice = null) => {                 // ``notice``: the result of the last action, kept through the redraw
      const [w, list, copies] = await Promise.all([get('/workshop'), get('/workshop/backups'), get('/workshop/recovery-copies')]);
      fill(root, h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Мастерская'),
        h('p', {class: 'sub'}, 'Данные этой мастерской, их схема и резервные копии. Восстановление в другую папку не трогает открытую мастерскую; её замена — отдельный явный выбор.'))),
      workshopCard(w, () => draw()), backupsCard(w, list, draw, notice), recoveryCard(copies), diagnosticsCard());
    };
    await draw();
    return root;
  }});
})();
