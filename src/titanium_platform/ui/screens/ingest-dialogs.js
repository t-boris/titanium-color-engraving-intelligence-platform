/* Таблицы и окна проверки пары: расхождения с платой, слои файла, исправление пары, подтверждение файла (DEC-017). */
'use strict';
const IngestDialogs = (() => {
  const {h, field, pill, post, form, toast, modal, table, num} = App;
  const FIELD = {power: 'Мощность', frequency: 'Частота', speed: 'Скорость'};
  const ROLE = {'test feature': 'тестовый участок', 'pre-test cleaning witness': 'свидетель чистки перед тестом',
    'registration, QR and engraved labels': 'метки, QR и подписи'};

  const discrepancyTable = (list) => table(['Ячейка', 'Поле', 'Определение платы', 'Файл LightBurn'],
    list.map((d) => [d.cell_id, FIELD[d.field] || d.field, d.defined, d.from_file ?? 'нет в файле']));

  const labText = (lab) => lab ? `L* ${num(lab[0], 1)} · a* ${num(lab[1], 1)} · b* ${num(lab[2], 1)}` : 'нет читаемых пикселей';
  const layerResult = (l) => {
    if (!l.measured_lab) return h('span', {}, pill(l.readable ? 'пропущен' : 'нечитаем', 'warn'), ' ', l.notes.map((n) => I18N.tr(n)).join('; '));
    const details = [h('div', {}, pill('измерен', 'ok'), ` · ${labText(l.measured_lab_against_clean || l.measured_lab)}`
      + `${l.measured_lab_against_clean ? ' относительно чистого титана' : ''} · ${num(l.pixels, 0)} пикс.`)];
    if (l.role) details.push(h('div', {class: 'muted small'}, ROLE[l.role] || l.role));
    if (l.measurement) details.push(h('div', {class: 'muted small'}, I18N.tr(l.measurement)));
    if (l.submeasurements?.length) details.push(...l.submeasurements.map((m) => h('div', {class: 'muted small'}, `${m.name}: ${labText(m.measured_lab)} · ${num(m.pixels, 0)} пикс.`)));
    if (l.line_metrics) {
      const m = l.line_metrics;
      details.push(h('div', {class: 'muted small'}, `Линии: видны ${m.visible_line_count}/${m.line_count} · непрерывность ${num(m.median_continuity_percent, 1)}% · контраст ${num(m.median_contrast_Lstar, 1)} L*${m.median_apparent_trace_width_mm == null ? '' : ` · видимая ширина ${num(m.median_apparent_trace_width_mm, 3)} мм`}`));
      if (m.groups?.length) details.push(h('div', {class: 'muted small'}, 'Группы зазора: ' + m.groups.map((g) =>
        `${g.spacing_um} мкм — ${g.visible_line_count}/${g.line_count} линий, ${num(g.median_continuity_percent, 0)}% непрерывности`).join(' · ')));
    }
    const source = l.source_settings || {};
    const get = (name) => source[name]?.Value;
    if (get('wobbleEnable') != null && get('wobbleEnable') !== '0') details.push(h('div', {class: 'muted small'}, `Wobble: шаг ${get('wobbleStep')} мм · размер ${get('wobbleSize')} мм`));
    if (l.notes?.length) details.push(h('div', {class: 'muted small'}, l.notes.map((n) => I18N.tr(n)).join('; ')));
    return h('div', {class: 'stack small'}, ...details);
  };
  const layersTable = (layers) => table(['Слой', 'Мощность, %', 'Частота, кГц', 'Скорость, мм/с', 'Областей', 'Результат'],
    layers.map((l) => [I18N.name(l.name), num(l.power, 1), num(l.frequency_khz, 0), num(l.speed, 0), l.regions, layerResult(l)]), 'Слоёв нет');

  /** «Исправить пару»: другой файл LightBurn. Проверка, подтверждение и проверка масок сбрасываются на сервере. */
  function fixFile(pair, reload) {
    const file = h('input', {type: 'file', accept: '.lbrn,.lbrn2'});
    modal('Исправить пару', field('Другой файл LightBurn', App.filePick(file, 'Выбрать файл LightBurn')), [
      {label: 'Отмена', run: (m) => m.close()},
      {label: 'Заменить файл', cls: 'primary', run: async (m) => {
        if (!file.files[0]) throw new Error('Выберите файл .lbrn или .lbrn2');
        const fd = new FormData();
        fd.append('lightburn', file.files[0]);
        await form(`/pairs/${pair.id}/lightburn`, fd);
        m.close(); toast('Файл заменён. Выполните проверку заново', 'ok'); reload();
      }}]);
  }

  /** Явное подтверждение, что приложенный файл использовался при гравировке; расхождения записываются вместе с ним. */
  function confirmFile(pair, check, reload) {
    const text = h('textarea', {rows: 3, placeholder: 'Например: гравировка выполнялась именно с этим файлом'});
    const ok = h('input', {type: 'checkbox'});
    modal('Подтвердить использованный файл', h('div', {class: 'stack'}, discrepancyTable(check.discrepancies),
      h('label', {class: 'row'}, ok, h('span', {}, 'Подтверждаю, что приложенный файл LightBurn использовался для физической гравировки')), field('Ваше подтверждение', text)), [
      {label: 'Отмена', run: (m) => m.close()},
      {label: 'Подтвердить', cls: 'primary', run: async (m) => {
        if (!ok.checked) throw new Error('Отметьте, что файл использовался для гравировки');
        await post(`/pairs/${pair.id}/confirm-file`, {text: text.value});
        m.close(); toast('Подтверждение записано вместе с расхождениями', 'ok'); reload();
      }}]);
  }

  return {discrepancyTable, layersTable, fixFile, confirmFile};
})();
