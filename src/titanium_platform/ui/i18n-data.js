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
    [/^no delta E tolerance is saved for this laser profile/i, 'Допуск ΔE для профиля не сохранён: отклонения показаны, но не оцениваются'],
    [/^stability is not assessed for parameter sets with fewer than two/i, 'Стабильность не оценена для наборов параметров, у которых меньше двух независимых гравировок'],
    [/^the photograph was aligned manually by four corners/i, 'Фотография выровнена вручную по четырём углам: уверенность выравнивания ниже, чем по маркерам'],
    [/^the plan does not store its trajectory colors/i, 'План не хранит цвета траектории: расстояние от пути вычислить нельзя'],
    [/^calibration plate cells have no planned color/i, 'У ячеек калибровочной платы нет планового цвета'],
    [/^the layer is not part of the original plan/i, 'Слой не входит в исходный план'],
    [/^Context is unknown for some repeats/i, 'Контекст части повторов неизвестен: отклонение нельзя отнести к партии материала или фокусу'],
    // планировщик
    [/^fewer than (\d+) measured parameter sets: the model is not fitted/i,
      (m) => 'Измерено меньше ' + m[1] + ' наборов параметров: модель не обучена, наборы выбраны только по пробелам; целевые цвета пока адресовать нельзя'],
    // слои файла
    [/^not comparable to the laser profile: (.+)$/i, (m) => 'Не сопоставим с профилем лазера: ' + t(m[1])],
    [/^the layer has no fill geometry/i, 'У слоя нет геометрии заливки'],
    [/^pulse width (\S+) in file, (\S+) in profile/i, (m) => 'длительность импульса ' + m[1] + ' в файле, ' + m[2] + ' в профиле'],
    [/^line interval (\S+) in file, (\S+) in profile/i, (m) => 'интервал линий ' + m[1] + ' в файле, ' + m[2] + ' в профиле'],
    [/^(\w+) (\S+) (\S+) is outside (\S+)-(\S+)$/i, (m) => (TAG[m[1]] || m[1]) + ' ' + m[2] + ' ' + m[3] + ' вне диапазона профиля ' + m[4] + '–' + m[5]],
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
})();
