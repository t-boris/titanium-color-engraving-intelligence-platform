/* Перевод сообщений сервера на русский (DEC-034).
   Известное сообщение получает русский вариант; неизвестное английское показывается с пометкой.
   Уже локализованные сервером сообщения сохраняются без пометки. Правила добавляют файлы i18n-*.js через I18N.add.
   Запись: [регулярное выражение, строка или функция(совпадение)]. Перевод, оканчивающийся на «: »,
   получает хвост исходного сообщения после совпавшей части. Сообщение, вложенное в другое («Фотография: …»), правило
   переводит тем же I18N.tr; несколько сообщений, соединённых «; », переводятся по одному. */
'use strict';
const I18N = (() => {
  const rules = [];
  const RUSSIAN = /[\u0400-\u04ff]/i;
  const UNTRANSLATED = ' (сообщение сервера, без перевода)';
  const PIECE_PARTS = 3;           // одно сообщение сервера содержит не больше двух своих «; »
  function add(list) { rules.push(...list); }
  /** Перевод по первому подходящему правилу: {out, exact — правило охватывает всё сообщение (его выражение кончается на $),
      а не только начало, spans — изменяемая часть совпадения захватила «; », то есть границу между сообщениями}; null —
      если правила нет. */
  function rule(text) {
    for (const [re, to] of rules) {
      const m = text.match(re);
      if (m) {
        const out = typeof to === 'function' ? to(m) : to;
        const tail = /: $/.test(out) ? text.replace(re, '').trim() : '';
        return {out: out + tail, exact: !tail && re.source.endsWith('$'),
          spans: [...m.slice(1), tail].some((part) => (part || '').includes('; '))};
      }
    }
    return null;
  }
  /** Список сообщений сервера через «; » (так сервер соединяет несколько причин): каждое сообщение переводится своим
      правилом. Сообщение может содержать «; » и само, поэтому из всех разбиений на переводимые куски (не больше
      PIECE_PARTS частей, переведённых целиком, вместе с вложенным сообщением) берётся то, что требует меньше всего
      допущений. Кусок, правило которого охватывает его целиком и не захватывает «; » изменяемой частью, допущений не
      требует; иначе — одно допущение и ещё по одному на каждую «; », которую кусок поглотил; при равенстве берётся
      разбиение на большее число кусков. Уже русская часть остаётся как есть. null — если разбить нельзя. */
  function list(text) {
    const parts = text.split('; ');
    if (parts.length < 2) return null;
    const memo = new Map();
    const piece = (i, j) => {             // [перевод куска, число допущений] или null
      const s = parts.slice(i, j).join('; ');
      const found = rule(s);
      if (!found) return j - i === 1 && RUSSIAN.test(s) ? [s, 0] : null;      // уже русская часть — по одной
      return found.out.includes(UNTRANSLATED) ? null : [found.out, found.exact && !found.spans ? 0 : j - i];
    };
    const from = (i) => {                  // лучший перевод частей с i-й до конца: {out, cost, count} или null
      if (i === parts.length) return {out: [], cost: 0, count: 0};
      if (!memo.has(i)) {
        let best = null;
        for (let j = i + 1; j <= Math.min(parts.length, i + PIECE_PARTS); j++) {
          const done = piece(i, j);
          const rest = done && from(j);
          if (!rest) continue;
          const cost = done[1] + rest.cost, count = 1 + rest.count;
          if (!best || cost < best.cost || (cost === best.cost && count > best.count)) best = {out: [done[0], ...rest.out], cost, count};
        }
        memo.set(i, best);
      }
      return memo.get(i);
    };
    const best = from(0);
    return best && best.out.join('; ');
  }
  /** Сначала список: правило, подошедшее к началу текста или захватившее его хвост, не должно проглотить следующие
      сообщения. Одно сообщение с «; » внутри переводится своим правилом целиком. */
  /** Перевод известного сообщения сервера или null: текст, который написал оператор, показывается как есть. */
  function known(message) {
    const text = String(message || '');
    return list(text) ?? rule(text)?.out ?? null;
  }
  function tr(message) {
    const text = String(message || '');
    const found = known(text);
    if (found !== null) return found;
    if (RUSSIAN.test(text)) return text;
    return text ? text + UNTRANSLATED : 'Неизвестная ошибка';
  }
  return {add, tr, known, count: () => rules.length};
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
  [/^A reference-chart candidate was detected, but color correction failed: no observations will be created\./i, 'Найден участок, похожий на эталонную карту, но цветокоррекция не прошла проверку. Возможно, самой карты нет в кадре. Наблюдения не будут созданы.'],
  [/^Reference chart not detected: no observations will be created\./i, 'Эталонная карта не обнаружена. Наблюдения не будут созданы.'],
  [/^(Calibration plate|Finished work) measured from decoded RAW without reference-chart correction; Lab values are camera-relative, not standard-calibrated\. These values are stored for experiment analysis but excluded from standard-color predictions\.$/i, (m) => (/finished/i.test(m[1]) ? 'Готовая работа' : 'Плата') + ' измерена по декодированному RAW без коррекции по эталонной карте. Значения Lab относительны для этой камеры и не являются стандартной цветовой калибровкой; сравнивайте результаты при одинаковом освещении и одинаковой обработке RAW. Они сохраняются для анализа эксперимента, но не участвуют в рекомендациях стандартных цветов.'],
  [/^no reference chart was detected/i, 'Эталонная карта не обнаружена: наблюдения создать нельзя'],
  [/^Alignment: no registration markers were detected: place the four image corners/i, 'Маркеры не найдены: поставьте четыре угла работы на фотографии'],
  [/^Alignment: registration markers not detected/i, 'Регистрационные маркеры не распознаны. Сопоставление остановлено, без догадок'],
  // сообщения совмещения приходят и сами по себе, и внутри «Alignment: …» — перевод один и тот же
  [/^(?:Alignment: )?only (\d+) registration markers detected; at least three are needed$/i, (m) => `Распознано меток: ${m[1]}. Для надёжного совмещения нужны минимум три`],
  [/^(?:Alignment: )?the experiment identifier QR code could not be read in the aligned photograph$/i, 'QR-код не удалось прочитать после проверки вариантов совмещения'],
  [/^Alignment: the experiment identifier QR code could not be read/i, 'Идентификатор эксперимента (QR) не прочитан. Сопоставление остановлено'],
  [/^Alignment: the photographed plate is (\S+) but the LightBurn file is (\S+)/i, (m) => 'На фотографии плата ' + m[1] + ', а в файле LightBurn — ' + m[2]],
  [/^Alignment: the four corners must lie inside the photograph/i, 'Углы должны лежать внутри фотографии'],
  [/^Alignment: the adjustment lost too many previously recognized vectors/i, 'После правки слишком много ранее найденных фигур перестало совпадать. Верните контуры назад или уточните четыре угла всей работы.'],
  [/^The work corners were corrected manually; review every layer outline before accepting measurements\.$/i, 'Углы работы исправлены вручную. Перед принятием проверьте контуры всех слоёв.'],
  [/^The whole LightBurn drawing was shifted by hand; inspect every contour before accepting measurements\.$/i, 'Вся схема LightBurn перемещена вручную. Перед принятием проверьте каждый контур.'],
  [/^The whole LightBurn drawing was adjusted by hand; inspect every contour before accepting measurements\.$/i, 'Совмещение всей схемы LightBurn исправлено вручную. Перед принятием проверьте каждый контур.'],
  [/^move the entire overlay or set alignment corners, not both$/i, 'Переместите всё наложение или задайте углы работы; одновременно эти действия применять нельзя'],
  [/^adjust the entire overlay or set alignment corners, not both$/i, 'Исправьте совмещение всей схемы или задайте углы работы; одновременно эти действия применять нельзя'],
  [/^automatic reset cannot be combined with manual alignment changes$/i, 'Автоматический поиск и ручную правку совмещения нельзя запускать одновременно'],
  [/^the overlay displacement must stay inside the photograph$/i, 'Смещение контуров должно оставаться в пределах фотографии'],
  [/^the overlay rotation must be between 0 and 360 degrees$/i, 'Поворот схемы должен быть от 0 до 360°'],
  [/^the overlay scale must be between 10 and 800 percent$/i, 'Масштаб схемы должен быть от 10 до 800%'],
  [/^the overlay mirror settings must be boolean$/i, 'Параметры зеркального отражения некорректны'],
  [/^check and align the photograph before moving its contours$/i, 'Сначала проверьте и совместите фотографию, затем перемещайте контуры'],
  [/^check and align the photograph before adjusting its contours$/i, 'Сначала проверьте и совместите фотографию, затем исправляйте контуры'],
  [/^(?:Alignment: )?the saved overlay adjustment is invalid$/i, 'Сохранённое смещение контуров некорректно; поставьте углы работы заново'],
  [/^only an accepted, aligned photograph can be revised$/i, 'Исправить совмещение можно только у принятой фотографии с выполненным выравниванием'],
  [/^the colour basis of the photograph would change from (\S+) to (\S+)$/i, (m) => 'Основа цвета фотографии изменилась бы: было ' + m[1] + ', стало ' + m[2]],
  [/^the new measurement reads fewer layers than the accepted one$/i, 'Новое измерение читает меньше слоёв, чем принятое'],
  [/^the source photograph is no longer available$/i, 'Исходная фотография больше недоступна'],
  [/^(?:Alignment: )?the selected detail is too small for the four placed corners/i, 'Выбранная деталь слишком мала для поставленной рамки. Отметьте четыре угла всей работы в разделе «Углы работы на фотографии».'],
  [/^Alignment: the four corners must form a convex quadrilateral/i, 'Четыре угла должны образовывать выпуклый четырёхугольник по порядку: верхний левый, верхний правый, нижний правый, нижний левый'],
  [/^Alignment: the plate has no marker definition/i, 'У платы нет описания маркеров'],
  [/^The LightBurn file differs from the plate definition/i, 'Файл LightBurn отличается от определения платы: исправьте пару или подтвердите, что использовался этот файл'],
  [/^plate cells not found in the LightBurn file: (.+)$/i, (m) => 'Ячейки платы не найдены в файле LightBurn: ' + m[1]],
  [/^No readable, comparable layer could be measured/i, 'Ни один читаемый и сопоставимый слой не удалось измерить'],
  [/^this plate was made for a different laser than the one selected/i, 'Плата сделана для другого лазера, чем выбранный: выберите лазер платы'],
  [/^experiment identifier (\S+) is not known to this system/i, (m) => 'Идентификатор эксперимента ' + m[1] + ' системе неизвестен'],
  [/^LightBurn file: (.+)$/i, (m) => 'Файл LightBurn не читается: ' + I18N.tr(m[1])],
]);
