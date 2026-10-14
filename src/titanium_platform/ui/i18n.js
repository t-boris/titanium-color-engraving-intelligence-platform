/* Перевод сообщений сервера на русский (DEC-034).
   Сервер отвечает по-английски. Известное сообщение получает русский вариант; сообщение без перевода
   показывается как есть с пометкой, а не скрывается. Правила добавляют файлы i18n-*.js через I18N.add.
   Запись: [регулярное выражение, строка или функция(совпадение)]. Перевод, оканчивающийся на «: »,
   получает хвост исходного сообщения после совпавшей части. */
'use strict';
const I18N = (() => {
  const rules = [];
  function add(list) { rules.push(...list); }
  function tr(message) {
    const text = String(message || '');
    for (const [re, to] of rules) {
      const m = text.match(re);
      if (m) {
        const out = typeof to === 'function' ? to(m) : to;
        return /: $/.test(out) ? out + text.replace(re, '').trim() : out;
      }
    }
    return text ? text + ' (сообщение сервера, без перевода)' : 'Неизвестная ошибка';
  }
  return {add, tr, count: () => rules.length};
})();

I18N.add([
  // загрузка и проверка пары
  [/^a RAW photograph is required for measurement$/i, 'Для измерения требуется фотография RAW'],
  [/^Select a \.lbrn or \.lbrn2 file$/i, 'Выберите файл .lbrn или .lbrn2'],
  [/^select a capture setup \(rig\)/i, 'Выберите установку съёмки (стенд)'],
  [/^choose the (.+) file$/i, (m) => 'Выберите файл: ' + ({LightBurn: 'LightBurn', photograph: 'фотография', image: 'изображение'}[m[1]] || m[1])],
  [/^the (.+) file is empty$/i, 'Файл пуст'],
  [/^the (.+) file is larger than (\d+) MB$/i, (m) => 'Файл больше ' + m[2] + ' МБ'],
  [/^the context is not valid JSON$/i, 'Дополнительный контекст записан неверно'],
  [/^both files must be non-empty/i, 'Оба файла должны быть непустыми'],
  [/^Photograph: a RAW photograph is required/i, 'Для измерения требуется фотография RAW'],
  [/^Photograph: cannot decode RAW file/i, 'Файл RAW не удалось прочитать'],
  [/^Reference chart not detected or not usable: no observations will be created\./i, 'Эталонная карта не обнаружена. Наблюдения не будут созданы.'],
  [/^no reference chart was detected/i, 'Эталонная карта не обнаружена: наблюдения создать нельзя'],
  [/^Alignment: no registration markers were detected: place the four image corners/i, 'Маркеры не найдены: поставьте четыре угла работы на фотографии'],
  [/^Alignment: registration markers not detected/i, 'Регистрационные маркеры не распознаны. Сопоставление остановлено, без догадок'],
  [/^Alignment: the experiment identifier QR code could not be read/i, 'Идентификатор эксперимента (QR) не прочитан. Сопоставление остановлено'],
  [/^Alignment: the photographed plate is (\S+) but the LightBurn file is (\S+)/i, (m) => 'На фотографии плата ' + m[1] + ', а в файле LightBurn — ' + m[2]],
  [/^Alignment: the four corners must lie inside the photograph/i, 'Углы должны лежать внутри фотографии'],
  [/^Alignment: the four corners must form a convex quadrilateral/i, 'Четыре угла должны образовывать выпуклый четырёхугольник по порядку: верхний левый, верхний правый, нижний правый, нижний левый'],
  [/^Alignment: the plate has no marker definition/i, 'У платы нет описания маркеров'],
  [/^The LightBurn file differs from the plate definition/i, 'Файл LightBurn отличается от определения платы: исправьте пару или подтвердите, что использовался этот файл'],
  [/^plate cells not found in the LightBurn file: (.+)$/i, (m) => 'Ячейки платы не найдены в файле LightBurn: ' + m[1]],
  [/^No readable, comparable layer could be measured/i, 'Ни один читаемый и сопоставимый слой не удалось измерить'],
  [/^this plate was generated for a different laser profile version/i, 'Плата создана для другой версии профиля лазера'],
  [/^experiment identifier (\S+) is not known to this system/i, (m) => 'Идентификатор эксперимента ' + m[1] + ' системе неизвестен'],
  [/^LightBurn file: /i, 'Файл LightBurn не читается: '],
]);
