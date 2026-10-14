/* Таблицы и окна проверки пары: расхождения с платой, слои файла, исправление пары, подтверждение файла (DEC-017). */
'use strict';
const IngestDialogs = (() => {
  const {h, field, pill, post, form, toast, modal, table, num} = App;
  const FIELD = {power: 'Мощность', frequency: 'Частота', speed: 'Скорость'};

  const discrepancyTable = (list) => table(['Ячейка', 'Поле', 'Определение платы', 'Файл LightBurn'],
    list.map((d) => [d.cell_id, FIELD[d.field] || d.field, d.defined, d.from_file ?? 'нет в файле']));

  const layersTable = (layers) => table(['Слой', 'Мощность, %', 'Частота, кГц', 'Скорость, мм/с', 'Областей', 'Результат'],
    layers.map((l) => [l.name, num(l.power, 1), num(l.frequency_khz, 0), num(l.speed, 0), l.regions,
      l.measured_lab ? pill('измерен', 'ok') : h('span', {}, pill(l.readable ? 'пропущен' : 'нечитаем', 'warn'), ' ', l.notes.map((n) => I18N.tr(n)).join('; '))]), 'Слоёв нет');

  /** «Исправить пару»: другой файл LightBurn. Проверка, подтверждение и проверка масок сбрасываются на сервере. */
  function fixFile(pair, reload) {
    const file = h('input', {type: 'file', accept: '.lbrn,.lbrn2'});
    modal('Исправить пару', field('Другой файл LightBurn', file), [
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
