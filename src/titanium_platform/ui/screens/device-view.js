/* Карточки лазера: паспорт, ступени, документы, профили (REQ-017). Расчёт рабочей точки — device-calc.js, экран — device.js. */
'use strict';
const DeviceView = (() => {
  const {h, btn, link, del, toast, confirmBox, table, facts} = App;
  const g = (v, d = 3) => (v == null ? '—' : String(+(+v).toPrecision(d)));
  const size = (n) => (n < 1024 * 1024 ? Math.max(1, Math.round(n / 1024)) + ' КБ' : (n / 1024 / 1024).toFixed(1).replace('.', ',') + ' МБ');

  function passportCard(d) {
    const p = d.passport, r = p.repetition_rate_khz;
    return h('div', {class: 'card stack'}, h('h3', {}, 'Паспорт'),
      d.description ? h('details', {}, h('summary', {class: 'small muted'}, 'Описание лазера'), h('p', {class: 'muted'}, d.description)) : null,
      facts([['Производитель', d.manufacturer], ['Модель', d.model], ['Серийный номер', d.serial || 'не указан'], ['Номинальная мощность', p.rated_power_w + ' Вт' + (d.characterization.power_basis === 'measured' ? ` (у вашего экземпляра измерено ${d.characterization.effective_power_w} Вт)` : '')],
        ['Длина волны', p.wavelength_nm ? p.wavelength_nm + ' нм' : null], ['Частота повторения', `${r.min}–${r.max} кГц`],
        ['Наибольшая энергия импульса', p.max_pulse_energy_mj ? p.max_pulse_energy_mj + ' мДж' : null],
        ['Диаметр пятна на металле', p.spot_diameter_um ? p.spot_diameter_um + ' мкм' : 'не задан: плотность энергии не считается']]),
      DeviceQuestions.card(d));
  }

  function stepsCard(d) {
    const rows = d.passport.pulse_steps.map((s) => [s.pulse_width_ns + ' нс', s.cutoff_khz == null ? 'CW: без среза' : s.cutoff_khz + ' кГц',
      s.cutoff_khz == null ? '—' : g(d.passport.rated_power_w / s.cutoff_khz) + ' мДж']);
    return h('details', {class: 'card stack'}, h('summary', {}, h('strong', {}, `Ступени длительности импульса и частоты среза: ${d.passport.pulse_steps.length}`)),
      h('p', {class: 'muted small'}, 'Лазер принимает только эти значения. Любое другое он игнорирует и оставляет прежнее, поэтому профиль с другой длительностью не создаётся. '
        + 'Ниже частоты среза мощность падает пропорционально частоте. Энергия — расчёт по паспорту, не измерение.'),
      table(['Длительность импульса', 'Частота среза', 'Наибольшая энергия импульса'], rows, undefined, true));
  }

  function documentsCard(d, reload) {
    const items = d.documents.map((x) => {
      const url = `/api/devices/${d.id}/documents/${x.id}`;
      const preview = x.media_type.startsWith('image/')
        ? h('a', {href: url, target: '_blank', rel: 'noopener'}, h('img', {src: url, alt: x.title, loading: 'lazy', style: 'max-width:220px;max-height:160px;object-fit:cover'})) : null;
      return h('div', {class: 'card stack', style: 'min-width:0'}, preview, h('strong', {}, x.title),
        h('p', {class: 'muted small'}, `${DeviceForms.KIND[x.kind] || x.kind} · ${x.filename} · ${size(x.size)}`),
        h('div', {class: 'row'}, h('a', {href: url, target: '_blank', rel: 'noopener'}, 'Открыть'),
          btn('Удалить', () => confirmBox('Удалить документ', `«${x.title}». Файл будет удалён с диска, паспорт останется.`, 'Удалить',
            async () => { await del(`/devices/${d.id}/documents/${x.id}`); toast('Документ удалён', 'ok'); reload(d.id); }), 'danger')));
    });
    return h('div', {class: 'card stack'}, h('h3', {}, 'Документы'),
      h('p', {class: 'muted small'}, 'Исходные фотографии и файлы хранятся без изменений: значения, прочитанные с них, можно сверить с оригиналом.'),
      items.length ? h('div', {class: 'grid g3'}, items) : h('p', {class: 'muted'}, 'Документов пока нет'), DeviceForms.uploadForm(d, reload));
  }

  function profilesCard(d) {
    const rows = d.profiles.map((p) => [link('/profiles?profile=' + p.id, `${p.name} · версия ${p.version}`), p.pulse_width + ' нс']);
    return h('div', {class: 'card stack'}, h('h3', {}, 'Профили на этом лазере'),
      rows.length ? table(['Профиль', 'Длительность импульса'], rows) : h('p', {class: 'muted'}, 'Профили не привязаны. Привяжите лазер на вкладке «Профили» → «Лазер».'));
  }
  return {passportCard, stepsCard, documentsCard, profilesCard, g};
})();
