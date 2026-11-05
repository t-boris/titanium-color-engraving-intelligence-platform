/* Форма результата эксперимента: фактический файл, фотография, лазер, линза и использованный титан.
   Линза импортированной работы неизвестна, пока оператор её не выбрал: установленная сейчас не подставляется (REQ-016). */
'use strict';
const IngestUpload = (() => {
  const {h, btn, field, link, get, formProgress, post, toast, fail, go} = App;

  function progressView() {
    const label = h('p', {class: 'muted small', role: 'status', 'aria-live': 'polite', hidden: true});
    const bar = h('progress', {max: '100', value: '0', hidden: true});
    let timer = null, figure = null;
    // ux-save-feedback-p0 REQ-002: the live region says the stage once; the percent and the seconds change for the eyes only (aria-hidden), so a
    // screen reader is not read a number every second
    return {el: h('div', {class: 'upload-progress'}, label, bar),
      uploading: (percent) => {
        label.hidden = bar.hidden = false;
        bar.value = percent;
        if (!figure || figure.parentNode !== label) { figure = h('span', {'aria-hidden': 'true'}); label.replaceChildren('Загрузка фотографии: ', figure); }
        figure.textContent = `${percent} %`;
      },
      checking: (what) => {
        label.hidden = bar.hidden = false;
        bar.removeAttribute('value');
        const start = Date.now();
        const seconds = figure = h('span', {'aria-hidden': 'true'});
        label.replaceChildren(`${what || 'Файл сохранён. Совмещаем фотографию с LightBurn и измеряем гравировку…'} `, seconds);
        const tick = () => { seconds.textContent = `${Math.floor((Date.now() - start) / 1000)} с`; };
        if (timer) clearInterval(timer);
        tick(); timer = setInterval(tick, 1000);
      },
      stop: () => { if (timer) clearInterval(timer); timer = null; bar.hidden = true; },
      error: (message) => { label.hidden = false; label.textContent = message; label.className = 'alert bad'; },
    };
  }

  const landing = (control) => App.landing(control);                // the person goes on to the check, or the result goes to the task panel (app.js)
  const CHECK_READY = {title: 'Фотография загружена', message: 'Фотография загружена и проверена. Откройте проверку, посмотрите наложение и примите результат.', openLabel: 'Открыть проверку'};

  const fileRead = (input, message) => () => (input.files && input.files[0] ? {ok: true, value: input.files[0]} : {ok: false, message});

  /** Выбор установки съёмки: по умолчанию та, что была в прошлый раз (или указанная). Эталонные значения карты берутся из неё (DEC-025). */
  function rigPicker(rigs, preferred) {
    const pick = h('select', {'aria-label': 'Установка съёмки'},
      rigs.map((r) => h('option', {value: r.id}, I18N.name(r.name) + (r.last_used ? ' · как в прошлый раз' : ''))));
    const chosen = rigs.find((r) => r.id === preferred) || rigs.find((r) => r.last_used) || rigs[0];
    if (chosen) pick.value = chosen.id;
    return pick;
  }
  const rigHint = () => h('p', {class: 'muted small'}, 'Установка съёмки — камера, свет, угол и эталонная карта; коррекция цвета берёт эталонные значения карты из неё. ',
    link('/setup?tab=rigs', 'Установки съёмки'));

  function rephoto(source, rigs = []) {
    if (source.status !== 'Accepted') return h('div', {class: 'card empty'},
      h('h3', {}, 'Сначала примите исходное наблюдение'),
      h('p', {}, 'Повторная фотография должна относиться к уже проверенной гравировке.'),
      link('/ingest?pair=' + source.id, 'Открыть исходную пару'));
    const f = Forms.create();
    const photo = h('input', {type: 'file', accept: '.raw,.nef,.nrw,.cr2,.cr3,.arw,.dng,.raf,.rw2,.orf,.pef,.srw'});
    const progress = progressView();
    const laser = [source.hardware?.device?.name, source.hardware?.lens?.name].filter(Boolean).join(' · ') || 'связка исходной пары';
    const titanium = [source.context?.titanium_name, source.context?.titanium_grade, source.context?.batch].filter(Boolean).join(' · ') || 'титан исходной пары';
    const rig = rigPicker(rigs, source.stand_id);
    const photoField = f.add('photo', 'RAW-фото всей гравировки', App.filePick(photo, 'Выбрать RAW-фото'), {required: true, read: fileRead(photo, 'Выберите новую фотографию RAW')});
    const rigField = rigs.length ? f.add('rig', 'Установка съёмки (стенд)', rig, {}) : null;
    const send = btn('Добавить фотографию и проверить', async (ev) => {
      const v = f.collect();
      if (!v) return;
      const fd = new FormData();
      fd.append('photo', v.photo);
      if (rig.value) fd.append('stand_id', rig.value);
      const self = ev.currentTarget;
      const end = landing(self);
      self.disabled = true;
      try {
        progress.uploading(0);
        const pair = await formProgress(`/pairs/${source.id}/rephotos`, fd, progress.uploading);
        progress.checking();
        let ready = false;
        try {
          const checked = await post(`/pairs/${pair.id}/check`, {});
          ready = checked.status === 'Ready to accept';
          if (end.stillHere()) toast(ready ? 'Фотография загружена и проверена; посмотрите наложение.'
            : 'Фотография загружена. Для совмещения нужна проверка углов на снимке.', ready ? 'ok' : 'warn');
        } catch (e) { if (end.stillHere()) toast(`Фото сохранено; проверка не завершилась: ${e.message}`, 'warn'); }
        progress.stop();
        end.go('/ingest?pair=' + pair.id, ready ? CHECK_READY : {...CHECK_READY, message: 'Фотография загружена, но проверка не готова: откройте её, чтобы довести до принятия.'});
      } catch (e) { progress.stop(); f.fail(e); self.disabled = false; }
    }, 'primary');
    return h('div', {class: 'stack'},
      h('div', {class: 'card stack'}, h('h3', {}, 'Новая фотография той же гравировки'),
        h('p', {}, `Исходная принятая пара №${source.id} · файл ${source.lightburn_name}`),
        h('p', {class: 'muted small'}, `${laser} · ${titanium}`),
        source.plan_id ? (source.plan_mode === 'Photo engraving work' ? link('/photo-engraving?work=' + source.plan_id, 'Открыть работу фотогравировки')
          : link('/plans/' + source.plan_id, source.plan_mode === 'Restored from file' ? 'Открыть план, восстановленный из файла' : 'Открыть экспериментальную плату')) : null,
        h('p', {}, 'LightBurn, настройки слоёв, лазер, линза и титан будут взяты из исходной пары. Новое фото не считается отдельной гравировкой.')),
      h('div', {class: 'card stack'}, h('h3', {}, 'Только новая фотография'),
        photoField, rigField, rigs.length ? rigHint() : null,
        h('p', {class: 'muted small'}, 'После загрузки приложение проверит совмещение с тем же LightBurn-файлом. Перед принятием измерений вы увидите контуры на фото.'),
        f.error, progress.el, h('div', {class: 'row'}, send)));
  }

  // a parameter matrix (LightBurn Material Test): the photograph is the whole input; the settings are read from it
  async function sendMatrix(pick, rig, context, f, progress, self) {
    const v = f.collect();
    if (!v) return;
    const end = landing(self);
    const fd = new FormData();
    fd.append('device_id', pick.deviceId()); fd.append('lens_id', pick.lensValue()); fd.append('stand_id', rig.value);
    fd.append('context', JSON.stringify(context(v))); fd.append('photo', v.photo);
    self.disabled = true;
    try {
      progress.uploading(0);
      const upload = formProgress('/matrix-pairs', fd, (percent) => {
        if (percent < 100) progress.uploading(percent); else progress.checking('Фото загружено. Ищем матрицу и читаем выгравированные параметры…');
      });
      const pair = await upload;
      progress.checking('Матрица найдена. Корректируем цвет по карте и измеряем каждую ячейку…');
      try { await post(`/pairs/${pair.id}/check`, {}); } catch (e) { toast(`Проверка не завершилась: ${e.message}`, 'warn'); }
      progress.stop();
      if (end.stillHere()) toast('Матрица распознана. Проверьте прочитанные параметры и подтвердите их.', 'ok');
      end.go('/ingest?pair=' + pair.id, {title: 'Матрица распознана', message: 'Матрица распознана. Откройте проверку, посмотрите прочитанные параметры и подтвердите их.', openLabel: 'Открыть проверку'});
    } catch (e) { progress.stop(); f.fail(e); self.disabled = false; }
  }

  async function render(ctx, lists, rigs) {
    const matrixMode = ctx.query.kind === 'matrix';
    const kinds = h('div', {class: 'row'}, h('span', {class: 'muted small'}, 'Что добавляем:'),
      matrixMode ? link('/ingest?kind=file', 'Работа с файлом LightBurn') : h('strong', {}, 'Работа с файлом LightBurn'), ' · ',
      matrixMode ? h('strong', {}, 'Матрица параметров (Material Test)') : link('/ingest?kind=matrix', 'Матрица параметров (Material Test)'));
    // a result of a plan or plate keeps the lens the plan was made for; otherwise the lens stays unknown until chosen
    let planned = null;
    if (ctx.query.plan) { try { planned = await get('/plans/' + ctx.query.plan); } catch (_) { planned = null; } }
    const pick = App.laserLensPicker(lists, {device: planned ? planned.device_id : ctx.query.device,
      lens: planned ? App.lensParam(planned.lens_id) : ctx.query.lens, defaultLens: 'unknown'});
    const f = Forms.create();
    const lb = h('input', {type: 'file', accept: '.lbrn,.lbrn2'});
    const photo = h('input', {type: 'file', accept: '.raw,.nef,.nrw,.cr2,.cr3,.arw,.dng,.raf,.rw2,.orf,.pef,.srw'});
    // the titanium that was used: one concrete record, found by a search among the records used last and not in a list of all; none is chosen
    // unless the address names one (ux-growing-collections-p0, REQ-001)
    const mat = MaterialPicker.create({value: ctx.query.material, allowEmpty: true, clearLabel: 'Снять выбор', empty: 'выберите титан', name: 'Использованный титан / лист / партия'});
    const rig = rigPicker(rigs);
    // REQ-020: задача всей работы; по умолчанию каждый слой берёт задачу своего плана или своего режима LightBurn,
    // а на проверке пары её можно изменить для каждого слоя
    const task = Tasks.select('', {empty: planned ? 'по плану и слоям LightBurn' : 'по слою LightBurn', aria: 'Задача работы'});
    const c = {focus: Forms.numberInput(Forms.QUANTITIES.focus, {placeholder: 'необязательно'}),
      date: h('input', {type: 'date'}), note: h('input', {placeholder: 'необязательно'})};
    const progress = progressView();
    // the fields of the conditions, read once by the form: an empty optional box is nothing, not an empty text
    const lbField = matrixMode ? null : f.add('lb', 'Файл .lbrn или .lbrn2', App.filePick(lb, 'Выбрать файл LightBurn'), {required: true,
      help: 'параметры читаются из фактически запущенного файла',
      read: () => (!lb.files[0] ? {ok: false, message: 'Выберите файл .lbrn или .lbrn2'}
        : /\.lbrn2?$/i.test(lb.files[0].name) ? {ok: true, value: lb.files[0]} : {ok: false, message: 'Нужен файл .lbrn или .lbrn2'})});
    const photoField = f.add('photo', 'Фотография RAW', App.filePick(photo, 'Выбрать фотографию'), {required: true,
      help: matrixMode ? 'в кадре вся сетка с подписями и эталонная цветовая карта' : 'в кадре должна быть эталонная цветовая карта',
      read: fileRead(photo, 'Для измерения требуется фотография RAW')});
    const laserField = f.add('laser', 'Лазер', pick.laser, {required: true,
      read: () => (pick.deviceId() ? {ok: true, value: pick.deviceId()} : {ok: false, message: 'Выберите лазер, на котором гравировали'})});
    const lensField = f.add('lens', 'Линза, которой гравировали', pick.lens, {read: () => ({ok: true, value: pick.lensValue()})});
    const matField = f.add('material', 'Использованный титан / лист / партия', mat, {required: true,
      read: () => (mat.value ? {ok: true, value: +mat.value} : {ok: false, message: 'Выберите использованный титан'})});
    const rigField = f.add('rig', 'Установка съёмки (стенд)', rig, {});
    const taskField = matrixMode ? null : f.add('task', 'Задача гравировки', task, {help: 'для чего делалась работа: надписи, линии, заливка, изображение…; результаты разных задач не смешиваются'});
    const focusField = f.add('focus', 'Фокус', c.focus, {quantity: 'focus'});
    const dateField = f.add('date', 'Дата гравировки', c.date, {});
    const noteField = f.add('note', 'Примечание', c.note, {});
    const context = (v) => ({material_id: v.material, focus: v.focus, engraved_at: v.date, note: v.note});

    const same = btn('Как у предыдущей платы', async () => {
      try {
        const prev = await get(`/devices/${pick.deviceId()}/previous-context`);
        if (!Object.keys(prev).length) { toast('Для этого лазера ещё нет принятых экспериментов', 'warn'); return; }
        mat.value = prev.material_id ?? ''; c.focus.value = prev.focus ?? ''; c.date.value = prev.engraved_at ?? ''; c.note.value = prev.note ?? '';
        f.clear();                                                    // the old complaints are about boxes that now hold other values
        pick.setLens(prev.lens_id);
        toast('Подставлены линза и титан предыдущего эксперимента этого лазера', 'ok');
      } catch (e) { fail(e); }
    });
    const send = btn('Загрузить пару', async (ev) => {
      const v = f.collect();
      if (!v) return;                                                 // each wrong box says why, beside itself, and keeps what was typed
      const fd = new FormData();
      fd.append('device_id', pick.deviceId()); fd.append('lens_id', pick.lensValue()); fd.append('context', JSON.stringify(context(v)));
      fd.append('stand_id', rig.value);
      if (ctx.query.plan) fd.append('plan_id', ctx.query.plan);
      if (v.task) fd.append('task', v.task);
      fd.append('lightburn', v.lb); fd.append('photo', v.photo);
      const self = ev.currentTarget;
      const end = landing(self);
      self.disabled = true;
      try {
        progress.uploading(0);
        const p = await formProgress('/pairs', fd, progress.uploading);
        progress.stop();
        if (end.stillHere()) toast('Файлы загружены. Теперь выполните проверку', 'ok');
        end.go('/ingest?pair=' + p.id, {title: 'Пара загружена', message: 'Файл LightBurn и фотография загружены. Откройте проверку: совместите фотографию с файлом и примите результат.', openLabel: 'Открыть проверку'});
      } catch (e) { progress.stop(); f.fail(e); }
      finally { self.disabled = false; }
    }, 'primary');

    const hardware = () => [h('div', {class: 'grid g3'}, laserField, lensField, matField),
      h('div', {class: 'grid g3'}, rigField), rigHint(),
      h('p', {class: 'muted small'}, planned ? 'Линза взята из платы или плана, для которых сделана эта работа.'
        : 'Линза импортированной работы остаётся неизвестной, пока вы её не выберете: установленная сейчас линза не подставляется. Данные с неизвестной линзой не смешиваются с данными известной.'),
      h('p', {class: 'small'}, 'Не нашли лазер или титан? ', link('/devices', 'Лазеры и линзы'), ' · ', link('/setup?tab=material', 'Добавить титан'))];
    const conditions = h('div', {class: 'card stack'}, h('h3', {}, 'Условия'), hardware(),
      h('details', {}, h('summary', {}, 'Дополнительные условия'),
        h('div', {class: 'grid g3'}, focusField, dateField, noteField), same));
    if (matrixMode) {
      const sendM = btn('Загрузить фото матрицы', (ev) => { const self = ev.currentTarget; sendMatrix(pick, rig, context, f, progress, self); }, 'primary');
      return h('div', {class: 'stack'}, kinds,
        h('div', {class: 'card empty'}, h('h3', {}, 'Фотография матрицы параметров'),
          h('p', {}, 'Сетка квадратов, где каждый квадрат выгравирован своими настройками, а значения выгравированы рядом: по одной оси одна настройка, по другой другая, '
            + 'постоянные настройки написаны над сеткой (как печатает LightBurn Material Test). Файл LightBurn не нужен: настройки прочитаются с фотографии, '
            + 'а вы проверите и подтвердите их перед принятием.'),
          h('p', {class: 'muted small'}, 'В кадре: вся сетка с подписями и эталонная цветовая карта; снимайте прямо сверху. Если на снимке несколько матриц, каждая станет своим экспериментом.')),
        h('div', {class: 'card stack'}, h('h3', {}, 'Фотография'), photoField),
        conditions, f.error, progress.el, h('div', {class: 'row'}, sendM));
    }
    // a photograph opened from a work is linked to it; a file that names another work is linked to that one and the check says so
    const work = planned && planned.mode === 'Vector job' ? h('div', {class: 'alert ok'}, 'Фото для работы ', link('/vector?plan=' + planned.id, `«${planned.name}»`),
      ': лазер, линза и титан взяты из работы. Загрузите файл, выгруженный из неё, и фото его гравировки: вывод запишется в работу.')
      : planned && planned.mode === 'Photo engraving work' ? h('div', {class: 'alert ok'}, 'Фото для работы фотогравировки ',
        link('/photo-engraving?work=' + planned.id, `«${planned.name}»`), ': лазер, линза и титан взяты из работы. Загрузите файл LightBurn, '
        + 'выгруженный из неё, и фото его гравировки: когда проверку примут, каждый серый работы сравнится с прогнозом.') : null;
    return h('div', {class: 'stack'}, kinds, work,
      h('div', {class: 'card empty'}, h('h3', {}, 'Добавьте файл LightBurn и фотографию результата'),
        h('p', {}, 'Параметры наблюдения будут прочитаны из фактически использованного файла. Измерения появятся только после проверки и принятия.')),
      h('div', {class: 'grid g2'},
        h('div', {class: 'card stack'}, h('h3', {}, 'Файл LightBurn'), lbField),
        h('div', {class: 'card stack'}, h('h3', {}, 'Фотография результата'), photoField)),
      h('div', {class: 'card stack'}, h('h3', {}, 'Условия'), hardware(),
        h('div', {class: 'grid g3'}, taskField),
        h('p', {class: 'muted small'}, 'Лазер, линза и титан сохраняются у каждого эксперимента. Фокус, дата и примечание необязательны.'),
        h('details', {}, h('summary', {}, 'Дополнительные условия'),
          h('div', {class: 'grid g3'}, focusField, dateField, noteField), same)),
      f.error, progress.el, h('div', {class: 'row'}, send));
  }
  return {render, rephoto};
})();
