/* Сообщения о лазерах (паспорт, документы, расчёт рабочей точки) — REQ-017, DEC-034, DEC-035.
   Загружается после i18n-more.js; более раннее правило имеет приоритет. */
'use strict';
I18N.add([
  // паспорт
  [/^device name is required/i, 'Укажите название лазера'],
  [/^the passport must be an object/i, 'Паспорт лазера записан неверно'],
  [/^the repetition rate range must be an object/i, 'Диапазон частот повторения записан неверно'],
  [/^a passport section has the wrong type/i, 'Раздел паспорта записан неверно'],
  [/^a passport section is too large/i, 'Раздел паспорта слишком большой'],
  [/^maximum repetition rate must be above the minimum/i, 'Максимальная частота должна быть больше минимальной'],
  [/^the pulse width table needs at least one step/i, 'В таблице длительностей импульса нужна хотя бы одна строка'],
  [/^pulse widths must not repeat/i, 'Длительности импульса в таблице не должны повторяться'],
  [/^pulse width (\S+) ns is not a selectable step of this laser; the steps are (.+)$/i,
    (m) => 'Длительность импульса ' + m[1] + ' нс — не ступень этого лазера: лазер её проигнорирует и оставит прежнюю. Доступны (нс): ' + m[2]],
  [/^the laser device was not found/i, 'Лазер не найден'],
  [/^this laser is linked to (\d+) laser profile versions; unlink them first/i, (m) => 'Лазер привязан к версиям профиля (' + m[1] + '). Сначала отвяжите их'],
  [/^the laser template is not known/i, 'Шаблон лазера неизвестен'],
  [/^link a laser device to this profile to calculate pulse energy/i, 'Привяжите к профилю лазер, чтобы рассчитать энергию импульса'],
  [/^the controller settings are not valid/i, 'Настройки контроллера записаны неверно'],
  [/^the test report is not valid/i, 'Протокол испытаний записан неверно'],
  [/^a waveform is not valid/i, 'Форма импульса записана неверно: нужны время в возрастающем порядке и мощность для каждой точки'],
  // документы
  [/^the document kind is not recognised/i, 'Вид документа не распознан'],
  [/^the document must be a JPG, PNG, PDF or TXT file/i, 'Документ — файл JPG, PNG, PDF или TXT'],
  [/^the document is empty/i, 'Файл документа пуст'],
  [/^the document is larger than (\d+) MB/i, (m) => 'Документ больше ' + m[1] + ' МБ'],
  [/^the document content does not match its file type/i, 'Содержимое документа не соответствует типу файла'],
  [/^the stored document file is missing/i, 'Файл документа не найден на диске'],
  [/^choose the document file/i, 'Выберите файл документа'],
  // расчёт рабочей точки (приходят как данные)
  [/^power must not exceed 100 %/i, 'Мощность не может быть больше 100 %'],
  [/^frequency (\S+) kHz is outside the repetition rate range (\S+)-(\S+) kHz of this laser/i,
    (m) => 'Частота ' + m[1] + ' кГц вне диапазона лазера ' + m[2] + '–' + m[3] + ' кГц'],
  [/^frequency (\S+) kHz is below the cut-off frequency (\S+) kHz of the (\S+) ns step: the output power is (\S+) % of the power set/i,
    (m) => 'Частота ' + m[1] + ' кГц ниже частоты среза ' + m[2] + ' кГц для импульса ' + m[3] + ' нс: выходная мощность — ' + m[4] + ' % от заданной'],
  [/^CW setting: the laser does not pulse/i, 'Режим CW: лазер не импульсный, энергия и шаг импульсов не определены'],
  [/^spot diameter is not set for this laser/i, 'Диаметр пятна лазера не задан: плотность энергии и перекрытие импульсов не рассчитываются'],
]);
