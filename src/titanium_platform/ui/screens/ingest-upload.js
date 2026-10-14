/* Форма новой пары: файл LightBurn + фотография со стенда + профиль лазера и необязательный контекст (REQ-015, REQ-016).
   Обязателен только профиль лазера; материал, партия, фокус, дата и примечание по умолчанию «неизвестно».
   «Как у предыдущей платы» подставляет контекст последней принятой пары этой версии профиля одним нажатием. */
'use strict';
const IngestUpload = (() => {
  const {h, btn, field, link, get, form, toast, fail, go} = App;

  async function render(ctx, profiles, setups, materials) {
    const prof = h('select', {'aria-label': 'Профиль лазера'}, profiles.map((p) => h('option', {value: p.id}, `${p.name} · версия ${p.version}`)));
    if (ctx.query.profile) prof.value = ctx.query.profile;
    const stand = h('select', {'aria-label': 'Стенд'}, setups.map((s) => h('option', {value: s.id}, s.name)));
    const lb = h('input', {type: 'file', accept: '.lbrn,.lbrn2', 'aria-label': 'Файл LightBurn'});
    const photo = h('input', {type: 'file', accept: '.raw,.nef,.nrw,.cr2,.cr3,.arw,.dng,.raf,.rw2,.orf,.pef,.srw', 'aria-label': 'Фотография RAW'});
    const mat = h('select', {'aria-label': 'Материал'}, h('option', {value: ''}, 'неизвестно'), materials.map((m) => h('option', {value: m.id}, m.name)));
    const c = {batch: h('input', {placeholder: 'неизвестно'}), focus: h('input', {type: 'number', step: 'any', placeholder: 'неизвестно'}),
      date: h('input', {type: 'date'}), note: h('input', {placeholder: 'необязательно'})};
    const err = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const context = () => ({material_id: mat.value ? +mat.value : null, batch: c.batch.value, focus: c.focus.value, engraved_at: c.date.value, note: c.note.value});
    const show = (m) => { err.textContent = m; err.hidden = !m; };

    const same = btn('Как у предыдущей платы', async () => {
      try {
        const prev = await get(`/profiles/${prof.value}/previous-context`);
        if (!Object.keys(prev).length) { toast('Для этой версии профиля ещё нет принятых пар', 'warn'); return; }
        mat.value = prev.material_id ?? ''; c.batch.value = prev.batch ?? ''; c.focus.value = prev.focus ?? ''; c.date.value = prev.engraved_at ?? ''; c.note.value = prev.note ?? '';
        toast('Подставлен контекст предыдущей принятой пары', 'ok');
      } catch (e) { fail(e); }
    });
    const send = btn('Загрузить пару', async (ev) => {
      show('');
      if (!lb.files[0]) return show('Выберите файл .lbrn или .lbrn2');
      if (!/\.lbrn2?$/i.test(lb.files[0].name)) return show('Выберите файл .lbrn или .lbrn2');
      if (!photo.files[0]) return show('Для измерения требуется фотография RAW');
      const fd = new FormData();
      fd.append('profile_id', prof.value); fd.append('stand_id', stand.value); fd.append('context', JSON.stringify(context()));
      if (ctx.query.plan) fd.append('plan_id', ctx.query.plan);
      if (ctx.query.rephoto) fd.append('rephoto_of', ctx.query.rephoto);
      fd.append('lightburn', lb.files[0]); fd.append('photo', photo.files[0]);
      const self = ev.currentTarget;
      self.disabled = true;
      try { const p = await form('/pairs', fd); toast('Пара загружена. Теперь выполните проверку', 'ok'); go('/ingest?pair=' + p.id); }
      catch (e) { show(e.message); } finally { self.disabled = false; }
    }, 'primary');

    return h('div', {class: 'stack'},
      h('div', {class: 'card empty'}, h('h3', {}, 'Добавьте файл LightBurn и фотографию со стенда'),
        h('p', {}, 'Параметры наблюдения будут прочитаны из фактически использованного файла. Измерения появятся только после проверки и принятия.')),
      h('div', {class: 'grid g2'},
        h('div', {class: 'card stack'}, h('h3', {}, 'Файл LightBurn'), field('.lbrn или .lbrn2 · параметры читаются из файла', lb),
          ctx.query.rephoto ? h('p', {class: 'alert'}, 'Повторная фотография уже принятой гравировки: она не считается независимым повтором (DEC-021).') : null),
        h('div', {class: 'card stack'}, h('h3', {}, 'Фотография со стенда'), field('RAW со стенда; эталонная карта в кадре обязательна', photo))),
      h('div', {class: 'card stack'}, h('h3', {}, 'Условия'),
        h('div', {class: 'grid g2'}, field('Профиль лазера (обязательно)', prof), field('Стенд (обязательно)', stand)),
        h('p', {class: 'small'}, 'Не настроено? ', link('/profiles', 'Настроить профили')),
        h('details', {}, h('summary', {}, 'Дополнительный контекст'),
          h('p', {class: 'muted small'}, 'В файлах LightBurn нет фокуса, партии материала и констант профиля. Отклонение можно отнести к партии или фокусу, только если они указаны.'),
          h('div', {class: 'grid g2'}, field('Материал', mat), field('Партия или лист', c.batch), field('Фокус', c.focus), field('Дата гравировки', c.date), field('Примечание', c.note)), same)),
      err, h('div', {class: 'row'}, send));
  }
  return {render};
})();
