/* Форма результата эксперимента: фактический файл, фотография, лазер+линза и использованный титан. */
'use strict';
const IngestUpload = (() => {
  const {h, btn, field, link, get, formProgress, post, toast, fail, go} = App;

  function progressView() {
    const label = h('p', {class: 'muted small', role: 'status', 'aria-live': 'polite', hidden: true});
    const bar = h('progress', {max: '100', value: '0', hidden: true});
    let timer = null;
    return {el: h('div', {class: 'upload-progress'}, label, bar),
      uploading: (percent) => {
        label.hidden = bar.hidden = false;
        bar.value = percent;
        label.textContent = `Загрузка фотографии: ${percent} %`;
      },
      checking: () => {
        label.hidden = bar.hidden = false;
        bar.removeAttribute('value');
        const start = Date.now();
        const tick = () => { label.textContent = `Файл сохранён. Совмещаем фотографию с LightBurn и измеряем гравировку… ${Math.floor((Date.now() - start) / 1000)} с`; };
        tick(); timer = setInterval(tick, 1000);
      },
      stop: () => { if (timer) clearInterval(timer); timer = null; bar.hidden = true; },
      error: (message) => { label.hidden = false; label.textContent = message; label.className = 'alert bad'; },
    };
  }

  function rephoto(source) {
    if (source.status !== 'Accepted') return h('div', {class: 'card empty'},
      h('h3', {}, 'Сначала примите исходное наблюдение'),
      h('p', {}, 'Повторная фотография должна относиться к уже проверенной гравировке.'),
      link('/ingest?pair=' + source.id, 'Открыть исходную пару'));
    const photo = h('input', {type: 'file', accept: '.raw,.nef,.nrw,.cr2,.cr3,.arw,.dng,.raf,.rw2,.orf,.pef,.srw',
      'aria-label': 'Новая фотография RAW'});
    const err = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const progress = progressView();
    const show = (message) => { err.textContent = message; err.hidden = !message; };
    const laser = [source.hardware?.device?.name, source.hardware?.lens?.name].filter(Boolean).join(' · ') || 'связка исходной пары';
    const titanium = [source.context?.titanium_name, source.context?.titanium_grade, source.context?.batch].filter(Boolean).join(' · ') || 'титан исходной пары';
    const send = btn('Добавить фотографию и проверить', async (ev) => {
      show('');
      if (!photo.files[0]) return show('Выберите новую фотографию RAW');
      const fd = new FormData();
      fd.append('photo', photo.files[0]);
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        progress.uploading(0);
        const pair = await formProgress(`/pairs/${source.id}/rephotos`, fd, progress.uploading);
        progress.checking();
        try {
          const checked = await post(`/pairs/${pair.id}/check`, {});
          toast(checked.status === 'Ready to accept' ? 'Фотография загружена и проверена; посмотрите наложение.'
            : 'Фотография загружена. Для совмещения нужна проверка углов на снимке.', checked.status === 'Ready to accept' ? 'ok' : 'warn');
        } catch (e) { toast(`Фото сохранено; проверка не завершилась: ${e.message}`, 'warn'); }
        progress.stop();
        go('/ingest?pair=' + pair.id, {preserveScroll: true});
      } catch (e) { progress.stop(); progress.error(e.message); show(e.message); self.disabled = false; }
    }, 'primary');
    return h('div', {class: 'stack'},
      h('div', {class: 'card stack'}, h('h3', {}, 'Новая фотография той же гравировки'),
        h('p', {}, `Исходная принятая пара №${source.id} · файл ${source.lightburn_name}`),
        h('p', {class: 'muted small'}, `${laser} · ${titanium}`),
        source.plan_id ? link('/plans/' + source.plan_id, 'Открыть экспериментальную плату') : null,
        h('p', {}, 'LightBurn, настройки слоёв, лазер, линза и титан будут взяты из исходной пары. Новое фото не считается отдельной гравировкой.')),
      h('div', {class: 'card stack'}, h('h3', {}, 'Только новая фотография'),
        field('RAW-фото всей гравировки', App.filePick(photo, 'Выбрать RAW-фото')),
        h('p', {class: 'muted small'}, 'После загрузки приложение проверит совмещение с тем же LightBurn-файлом. Перед принятием измерений вы увидите контуры на фото.'),
        err, progress.el, h('div', {class: 'row'}, send)));
  }

  async function render(ctx, profiles, materials) {
    const prof = h('select', {'aria-label': 'Лазер и линза'}, profiles.map((p) => h('option', {value: p.id}, `${p.name}${p.device ? ` · ${p.device.name}` : ''}${p.lens ? ` · ${p.lens.name}` : ''}`)));
    if (ctx.query.profile) prof.value = ctx.query.profile;
    const lb = h('input', {type: 'file', accept: '.lbrn,.lbrn2', 'aria-label': 'Файл LightBurn'});
    const photo = h('input', {type: 'file', accept: '.raw,.nef,.nrw,.cr2,.cr3,.arw,.dng,.raf,.rw2,.orf,.pef,.srw', 'aria-label': 'Фотография RAW'});
    const materialLabel = (m) => [m.name, m.grade, m.thickness_mm != null ? `${m.thickness_mm} мм` : null, m.batch].filter(Boolean).join(' · ');
    const mat = h('select', {'aria-label': 'Использованный титан'}, [h('option', {value: ''}, 'выберите титан')].concat(materials.map((m) => h('option', {value: m.id}, materialLabel(m)))));
    if (ctx.query.material) mat.value = ctx.query.material;
    const c = {focus: h('input', {type: 'number', step: 'any', placeholder: 'необязательно'}),
      date: h('input', {type: 'date'}), note: h('input', {placeholder: 'необязательно'})};
    const err = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const progress = progressView();
    const context = () => ({material_id: mat.value ? +mat.value : null, focus: c.focus.value, engraved_at: c.date.value, note: c.note.value});
    const show = (m) => { err.textContent = m; err.hidden = !m; };

    const same = btn('Как у предыдущей платы', async () => {
      try {
        const prev = await get(`/profiles/${prof.value}/previous-context`);
        if (!Object.keys(prev).length) { toast('Для этой связки ещё нет принятых экспериментов', 'warn'); return; }
        mat.value = prev.material_id ?? ''; c.focus.value = prev.focus ?? ''; c.date.value = prev.engraved_at ?? ''; c.note.value = prev.note ?? '';
        toast('Подставлены лазер и титан предыдущего эксперимента', 'ok');
      } catch (e) { fail(e); }
    });
    const send = btn('Загрузить пару', async (ev) => {
      show('');
      if (!lb.files[0]) return show('Выберите файл .lbrn или .lbrn2');
      if (!/\.lbrn2?$/i.test(lb.files[0].name)) return show('Выберите файл .lbrn или .lbrn2');
      if (!photo.files[0]) return show('Для измерения требуется фотография RAW');
      const fd = new FormData();
      if (!mat.value) return show('Выберите использованный титан');
      fd.append('profile_id', prof.value); fd.append('context', JSON.stringify(context()));
      if (ctx.query.plan) fd.append('plan_id', ctx.query.plan);
      fd.append('lightburn', lb.files[0]); fd.append('photo', photo.files[0]);
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        progress.uploading(0);
        const p = await formProgress('/pairs', fd, progress.uploading);
        progress.stop(); toast('Файлы загружены. Теперь выполните проверку', 'ok');
        go('/ingest?pair=' + p.id, {preserveScroll: true});
      } catch (e) { progress.stop(); progress.error(e.message); show(e.message); }
      finally { self.disabled = false; }
    }, 'primary');

    return h('div', {class: 'stack'},
      h('div', {class: 'card empty'}, h('h3', {}, 'Добавьте файл LightBurn и фотографию результата'),
        h('p', {}, 'Параметры наблюдения будут прочитаны из фактически использованного файла. Измерения появятся только после проверки и принятия.')),
      h('div', {class: 'grid g2'},
        h('div', {class: 'card stack'}, h('h3', {}, 'Файл LightBurn'), field('.lbrn или .lbrn2 · параметры читаются из фактически запущенного файла', App.filePick(lb, 'Выбрать файл LightBurn'))),
        h('div', {class: 'card stack'}, h('h3', {}, 'Фотография результата'), field('Фотография RAW; в кадре должна быть эталонная цветовая карта', App.filePick(photo, 'Выбрать фотографию')))),
      h('div', {class: 'card stack'}, h('h3', {}, 'Условия'),
        h('div', {class: 'grid g2'}, field('Лазер + установленная линза (обязательно)', prof), field('Использованный титан / лист / партия (обязательно)', mat)),
          h('p', {class: 'small'}, 'Не нашли оборудование или титан? ', link('/profiles', 'Настроить установки и добавить титан')),
        h('p', {class: 'muted small'}, 'Эти две записи будут сохранены у каждого эксперимента. Фокус, дата и примечание необязательны.'),
        h('details', {}, h('summary', {}, 'Дополнительные условия'),
          h('div', {class: 'grid g3'}, field('Фокус', c.focus), field('Дата гравировки', c.date), field('Примечание', c.note)), same)),
      err, progress.el, h('div', {class: 'row'}, send));
  }
  return {render, rephoto};
})();
