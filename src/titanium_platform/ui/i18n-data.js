/* Тексты, которые сервер возвращает как данные: ограничения отчёта, заметки по слоям, основания переходов знания,
   пояснения планировщика (DEC-034). Загружается после остальных таблиц. Правила-обёртки («Фотография: …») переводят и
   вложенное сообщение. Текст, введённый пользователем (причина понижения, подтверждение файла), сюда не попадает:
   экраны показывают его без перевода. */
'use strict';
(() => {
  const TAG = {maxPower: 'Мощность', speed: 'Скорость', frequency: 'Частота', QPulseWidth: 'Длительность импульса', interval: 'Интервал линий',
    power: 'Мощность', focus: 'Фокус'};
  const t = (s) => I18N.tr(s);
  I18N.add([
    // отчёт после гравировки
    [/^no original plan is linked to this pair/i, 'План к этой паре не привязан: доступны только измерения и сравнение повторов'],
    [/^no delta E tolerance is saved for this laser and lens/i, 'Допуск ΔE для этого лазера с этой линзой не сохранён: отклонения показаны, но не оцениваются'],
    [/^stability is not assessed for parameter sets with fewer than two/i, 'Стабильность не оценена для наборов параметров, у которых меньше двух независимых гравировок'],
    [/^the photograph was aligned manually by four corners/i, 'Фотография выровнена вручную по четырём углам: уверенность выравнивания ниже, чем по маркерам'],
    [/^the photograph was aligned manually or corrected by hand: review its vector overlay before using these measurements$/i, 'Фотография совмещена или поправлена вручную. Проверьте векторное наложение, прежде чем использовать эти измерения.'],
    [/^the plan does not store its trajectory colors/i, 'План не хранит цвета траектории: расстояние от пути вычислить нельзя'],
    [/^calibration plate cells have no planned color/i, 'У ячеек калибровочной платы нет планового цвета'],
    [/^the layer is not part of the original plan/i, 'Слой не входит в исходный план'],
    [/^Context is unknown for some repeats/i, 'Контекст части повторов неизвестен: отклонение нельзя отнести к партии материала или фокусу'],
    // планировщик
    [/^fewer than (\d+) measured parameter sets with these job settings: the model is not fitted/i,
      (m) => 'С этими настройками работы измерено меньше ' + m[1] + ' наборов параметров: модель не обучена, наборы выбраны только по пробелам; целевые цвета пока адресовать нельзя'],
    [/^fewer than (\d+) measured parameter sets: the model is not fitted/i,
      (m) => 'Измерено меньше ' + m[1] + ' наборов параметров: модель не обучена, наборы выбраны только по пробелам; целевые цвета пока адресовать нельзя'],
    // слои файла
    [/^not comparable within this laser and lens: (.+)$/i, (m) => 'Не сопоставим в пределах этого лазера и линзы: ' + t(m[1])],
    // так эту заметку писали прежние версии; она хранится в проверках сохранённых пар
    [/^not comparable to this hardware\/search setup: (.+)$/i, (m) => 'Не сопоставим в пределах этого лазера и линзы: ' + t(m[1])],
    [/^the layer has no fill geometry/i, 'У слоя нет геометрии заливки'],
    [/^registration marker layer: not measured/i, 'Слой регистрационных маркеров: не измеряется'],
    [/^(\w+) (\S+) (\S+) is outside (\S+)-(\S+)$/i, (m) => (TAG[m[1]] || m[1]) + ' ' + m[2] + ' ' + m[3] + ' вне диапазона лазера ' + m[4] + '–' + m[5]],
    [/^(\w+): missing$/i, (m) => (TAG[m[1]] || m[1]) + ': нет в файле'],
    [/^(\w+): not a number \((.*)\)$/i, (m) => (TAG[m[1]] || m[1]) + ': не число (' + m[2] + ')'],
    [/^(\w+): not finite$/i, (m) => (TAG[m[1]] || m[1]) + ': не конечное число'],
    // обёртки проверки пары
    [/^Photograph: (.+)$/i, (m) => 'Фотография: ' + t(m[1])],
    [/^Alignment: (.+)$/i, (m) => 'Выравнивание: ' + t(m[1])],
    // основания переходов знания
    [/^single observation$/i, 'одно наблюдение'],
    [/^criteria not agreed: automatic promotion is disabled/i, 'критерии не согласованы: автоматическое продвижение отключено'],
    [/^(\d+) independent engravings within variance and tolerance/i, (m) => 'независимых гравировок: ' + m[1] + ', в пределах дисперсии и допуска'],
    [/^(\d+) independent engravings$/i, (m) => 'независимых гравировок: ' + m[1]],
    [/^more than one observation$/i, 'больше одного наблюдения'],
    [/^first eligible observation$/i, 'первое подходящее наблюдение'],
    [/^approved by the operator$/i, 'утверждено оператором'],
    [/^manual demotion$/i, 'ручное понижение'],
    [/^flag cleared by the operator: (.*)$/i, (m) => 'флаг снят оператором: ' + t(m[1])],
    [/^rolled back event (\d+)/i, (m) => 'откат события ' + m[1]],
    [/^variance (\S+) exceeds (\S+)$/i, (m) => 'дисперсия ' + m[1] + ' превышает порог ' + m[2]],
    [/^deviation (\S+) exceeds (\S+)$/i, (m) => 'отклонение ' + m[1] + ' превышает допуск ' + m[2]],
  ]);

  // предсказанный вид фотогравировки (REQ-030): отказы, заметки прогноза, предпросмотр
  const ADJUSTMENT = {Gamma: 'гамма', Contrast: 'контраст', Brightness: 'яркость', EnhanceAmount: 'усиление резкости',
    EnhanceRadius: 'радиус резкости', EnhanceDenoise: 'шумоподавление'};
  const adjustments = (s) => s.replace(/\b(Gamma|Contrast|Brightness|EnhanceAmount|EnhanceRadius|EnhanceDenoise)\b/g, (tag) => ADJUSTMENT[tag]);
  const WHY = {
    '3D slicing engraves depth in repeated passes, not a tone': '3D-срез гравирует глубину повторными проходами, а не тон',
    'it is a dithered mode: every dot is fired at full power or not at all, the grey sets the dot pattern and dithering is not modelled':
      'это режим растрирования: каждая точка прожигается полной мощностью или не прожигается вовсе, серый задаёт узор точек, а растрирование не моделируется',
    'the grey level does not set the power in this mode': 'в этом режиме уровень серого не задаёт мощность'};
  const GRAYSCALE = 'прогнозируется только режим Grayscale, в котором уровень серого задаёт мощность';
  I18N.add([
    [/^The prediction rests on (\d+) measured powers of this mode, (\S+)\.\.(\S+) %, (chart-corrected \(referenced\)|camera-relative)\.$/i,
      (m) => `Прогноз опирается на измеренные мощности этого режима (их ${m[1]}) от ${m[2]} до ${m[3]} %, цвет ${/chart/i.test(m[4]) ? 'с коррекцией по эталонной карте' : 'относительно камеры'}.`],
    [/^Camera-relative colours: they are as that camera saw them under that light/i,
      'Цвета относительно камеры: такими их увидела та камера при том освещении, без коррекции по эталонной карте.'],
    [/^(\d+) (camera-relative|referenced) points of this mode are left out: the two kinds are never mixed in one curve\.$/i,
      (m) => `Не использовано точек этого режима ${/referenced/i.test(m[2]) ? 'по эталонной карте' : 'относительно камеры'}: ${m[1]}. Измерения по карте и относительно камеры не смешиваются в одной кривой.`],
    [/^(\S+) % of the picture needs a power outside the measured span (\S+)\.\.(\S+) %: not predicted, hatched\.$/i,
      (m) => `${m[1]} % картинки требует мощности вне измеренного диапазона ${m[2]}–${m[3]} %: там прогноза нет, эти места заштрихованы.`],
    [/^Picture adjustments applied with standard formulas, assumed \(LightBurn does not publish its own\): (.+)\.$/i,
      (m) => `Настройки картинки применены по стандартным формулам, это допущение (LightBurn свои формулы не публикует): ${adjustments(m[1])}.`],
    [/^Picture adjustments not modelled and left out of the prediction: (.+)\.$/i,
      (m) => `Настройки картинки, которые не моделируются и в прогнозе не учтены: ${adjustments(m[1])}.`],
    [/^Camera-relative colours are expressed against the clean titanium of their own photograph/i,
      'Цвета относительно камеры приведены к чистому титану своей же фотографии: их можно сравнивать между снимками, но оттенок условный.'],
    [/^No photograph of this mode shows clean titanium/i,
      'Ни на одной фотографии этого режима нет чистого титана: цвета показаны как сняты, в экспозиции своей фотографии.'],
    [/^(\d+) camera-relative points without clean titanium in their photograph are left out/i,
      (m) => `Не использовано точек относительно камеры без чистого титана на своей фотографии: ${m[1]}. Они не смешиваются с цветами, приведёнными к чистому титану.`],
    [/^(\d+) tonal profiles of this mode relate their colour to the grey only weakly and are not used\.$/i,
      (m) => `Тональных профилей этого режима со слабой связью цвета и серого: ${m[1]}; они не использованы.`],
    [/^The layer holds (\d+) pictures; the largest one is shown\.$/i, (m) => `Картинок на слое: ${m[1]}; показана самая большая.`],
    [/^The picture is turned by an angle in the file; the preview shows it without that turn\.$/i,
      'В файле картинка повёрнута на произвольный угол; в предпросмотре она показана без этого поворота.'],
    [/^no colour has been measured at this mode: there is nothing to predict from$/i, 'В этом режиме цвет ещё не измерялся: прогнозу не на что опереться'],
    [/^picture adjustments out of range: gamma (\S+) \(must be above 0\), contrast (\S+) \(must be -100 or more\), brightness (\S+)$/i,
      (m) => `Настройки картинки вне допустимых значений: гамма ${m[1]} (должна быть больше 0), контраст ${m[2]} (не меньше −100), яркость ${m[3]}`],
    [/^Min and Max power must be numbers, got (.+) and (.+)$/i, (m) => `Мин. и макс. мощность должны быть числами, получено: ${m[1]} и ${m[2]}`],
    [/^Min power (\S+) % and Max power (\S+) % must lie within 0\.\.100 % with Min not above Max$/i,
      (m) => `Мин. мощность ${m[1]} % и макс. мощность ${m[2]} % должны лежать в пределах 0–100 %, минимальная не выше максимальной`],
    [/^the layer states no image mode: only grayscale mode/i, `У слоя не указан режим изображения: ${GRAYSCALE}`],
    [/^(.+) mode is not predicted: (.+); only grayscale mode, where the grey level sets the power, is predicted$/i,
      (m) => `Режим ${m[1]} не прогнозируется: ${WHY[m[2]] || m[2]}; ${GRAYSCALE}`],
    [/^the layer has no picture: there is nothing to predict$/i, 'У слоя нет картинки: прогнозировать нечего'],
    [/^the picture is empty or not a single grey channel/i, 'Картинка пуста или не является одним серым каналом: прогнозировать нечего'],
    [/^the grey levels of the picture must lie within 0\.\.1$/i, 'Уровни серого картинки должны лежать в пределах 0..1'],
    [/^the file has no image layer: there is no picture to predict$/i, 'В файле нет слоя изображения: прогнозировать нечего'],
    [/^the preview is no longer kept: upload the LightBurn file again$/i, 'Предпросмотр больше не хранится: загрузите файл LightBurn ещё раз'],
    [/^image layer (\d+) cannot be rendered in this upload$/i, (m) => `Слой изображения ${m[1]} в этой загрузке не отрисовать`],
    [/^titanium (\d+) not found$/i, (m) => `Титан №${m[1]} не найден`],
  ]);
})();
