/* Протокол испытаний и формы импульса лазера с пояснениями к каждой строке (REQ-017, DEC-037, DEC-038). */
'use strict';
const DeviceReport = (() => {
  const {h, pill, table} = App;
  const cell = (v) => (v == null || v === '' ? '—' : typeof v === 'number' ? String(+v.toPrecision(5)) : String(v));
  const ROW_RU = {'Mode of operation': 'Режим работы', 'Nominal average output power': 'Номинальная средняя мощность', 'Central emission wavelength': 'Центральная длина волны',
    'Emission bandwidth (FWHM)': 'Ширина спектра (FWHM)', 'Output power adjusting range': 'Диапазон регулировки мощности', 'Extended pulse repetition rate': 'Частота повторения импульсов',
    'Long-term average power instability': 'Долговременная нестабильность мощности', 'Output beam diameter': 'Диаметр выходного пучка', 'Control interfaces': 'Интерфейс управления'};

  function reportCard(d) {
    const r = d.passport.test_report;
    if (!r) return null;
    const rows = r.rows.map((x) => [h('div', {}, h('strong', {}, ROW_RU[x.key] || x.key), h('div', {class: 'small muted'}, GlossaryReport.ROWS[x.key] || x.key)),
      x.condition || '—', x.unit || '—', cell(x.min), cell(x.typ), cell(x.max), x.result == null ? pill('нет числа', 'warn') : h('strong', {}, cell(x.result))]);
    return h('div', {class: 'card stack'}, h('h3', {}, 'Протокол испытаний вашего экземпляра'),
      h('p', {class: 'muted small'}, `Серийный номер ${r.serial || '—'} · модель ${r.part_number || '—'} · испытан ${r.tested_on || '—'}. ${GlossaryReport.COLUMNS}`),
      table(['Характеристика и что это значит', 'Условия', 'Ед.', 'Мин.', 'Типичное', 'Макс.', 'Результат'], rows, undefined, true));
  }

  /** Формы импульса: те же оси, что на оригинале; рядом фото-источник и сверка энергии с паспортом. */
  function waveformsCard(d, charts) {
    if (!charts.waveforms.length) return null;
    const photo = d.documents.find((x) => x.kind === 'waveform');
    const blocks = charts.waveforms.map((w) => {
      const s = w.stats, ok = s.ratio != null && s.ratio > 0.7 && s.ratio < 1.3;
      return h('div', {class: 'stack'}, h('h3', {}, I18N.name(w.title)), DevicePlots.waveform(w),
        h('p', {class: 'muted small'}, `Пик ${+s.peak_kw.toPrecision(3)} кВт на ${+s.peak_t_ns.toPrecision(3)} нс. Энергия по кривой ≈ ${+s.energy_mj.toPrecision(3)} мДж`
          + (s.passport_energy_mj ? `, по паспорту (60 Вт ÷ ${w.frequency_khz} кГц) ${+s.passport_energy_mj.toPrecision(3)} мДж.` : '.')),
        s.ratio != null ? pill(ok ? 'оцифровка сходится с паспортом' : 'расхождение с паспортом: ×' + s.ratio, ok ? 'ok' : 'warn') : null,
        w.note ? h('p', {class: 'muted small'}, w.note) : null);
    });
    return h('div', {class: 'card stack'}, h('h3', {}, 'Формы импульса из протокола'),
      h('p', {class: 'muted small'}, 'Мощность в самом импульсе в киловаттах, время в наносекундах. Средняя мощность — это десятки ватт: импульс короткий, а пауза между импульсами длинная, '
        + 'поэтому пик в тысячи раз больше средней. Кривые оцифрованы с фотографии (приблизительно): оригинал открывается в блоке «Документы».'),
      h('div', {class: 'grid g2'}, blocks), photo ? h('a', {href: `/api/devices/${d.id}/documents/${photo.id}`, target: '_blank', rel: 'noopener'}, 'Открыть оригинал на фотографии') : null);
  }
  return {reportCard, waveformsCard};
})();
