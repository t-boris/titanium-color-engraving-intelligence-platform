/* Сообщения проверок ввода, плана, платы, фотографии и файла LightBurn (DEC-034). Загружается после i18n-more.js:
   более раннее правило имеет приоритет. Название поля в сообщении переводит FIELD; неизвестное остаётся как есть. */
'use strict';
(() => {
  const FIELD = {power: 'Мощность', frequency: 'Частота', speed: 'Скорость', 'pulse width': 'Длительность импульса', 'line interval': 'Интервал линий',
    'cell width': 'Ширина ячейки', 'cell height': 'Высота ячейки', gap: 'Зазор', 'delta E tolerance': 'Допуск ΔE', 'variance threshold': 'Порог дисперсии',
    'repeat threshold': 'Порог повторов', focus: 'Фокус', 'profile name': 'Название профиля', name: 'Название', camera: 'Камера', lighting: 'Освещение',
    angle: 'Угол съёмки', 'reference chart': 'Эталонная карта', 'material name': 'Название материала'};
  const f = (s) => FIELD[String(s).replace(/ min$| max$/, '')] || s;
  I18N.add([
    // профили, оси, стенд, материал
    [/^(.+) must be a finite positive number$/i, (m) => f(m[1]) + ' — конечное положительное число'],
    [/^(.+) must be a finite number$/i, (m) => f(m[1]) + ' — конечное число'],
    [/^(.+) must be a number$/i, (m) => f(m[1]) + ' — число'],
    [/^(.+) must not be negative$/i, (m) => f(m[1]) + ' не может быть отрицательным'],
    [/^(.+) must be positive$/i, (m) => f(m[1]) + ' должно быть положительным'],
    [/^(.+) is required$/i, (m) => 'Заполните поле: ' + f(m[1])],
    [/^passes must be a positive integer/i, 'Проходы — положительное целое число'],
    [/^repeat threshold must be a positive integer/i, 'Порог повторов — положительное целое число'],
    [/^material name is required/i, 'Укажите название материала'],
    [/^a laser profile needs the power, frequency and speed axes/i, 'Профиль лазера требует осей: мощность, частота, скорость'],
    [/^axis keys must be unique/i, 'Ключи осей не должны повторяться'],
    [/^axis '(.+)' is required/i, (m) => 'Нужна ось: ' + f(m[1])],
    [/^axis '(.+)': min must be below max/i, (m) => 'Ось «' + f(m[1]) + '»: минимум должен быть меньше максимума'],
    [/^axis '(.+)' needs a unit/i, (m) => 'Для оси «' + f(m[1]) + '» нужна единица измерения'],
    // серия плат и план
    [/^(.+): enter at least one value$/i, (m) => f(m[1]) + ': введите хотя бы одно значение'],
    [/^(.+): values must not repeat$/i, (m) => f(m[1]) + ': значения не должны повторяться'],
    [/^(.+): '(.*)' is not a number$/i, (m) => f(m[1]) + ': «' + m[2] + '» — не число'],
    [/^(\d+) cells need more LightBurn layers/i, 'Слишком много ячеек для слоёв LightBurn'],
    [/^the plan has no layers to export/i, 'В плане нет слоёв: экспорт недоступен'],
    [/^(\d+) layers exceed the (\d+) LightBurn layers available/i, (m) => 'Слоёв больше, чем доступно в LightBurn (' + m[2] + ')'],
    [/^layer (.+) lacks power, frequency or speed/i, (m) => 'У слоя ' + m[1] + ' нет мощности, частоты или скорости'],
    [/^layer (.+) has an incomplete prediction/i, (m) => 'У слоя ' + m[1] + ' неполный прогноз: нужны уверенность, ожидаемая ошибка и стабильность'],
    [/^marker layer power, frequency and speed are not set/i, 'Не заданы мощность, частота и скорость слоя маркеров (вкладка «Профили»)'],
    [/^calibration plates always carry markers/i, 'Калибровочные платы всегда несут маркеры'],
    [/^the number of colors must be between 1 and (\d+)/i, (m) => 'Число цветов — от 1 до ' + m[1]],
    [/^this is not a discrete color plan/i, 'Это не план цветной гравировки'],
    [/^(\d+) distinct colors need more LightBurn layers/i, 'Слишком много различных цветов для слоёв LightBurn'],
    [/^unknown source color in the exclusions/i, 'Неизвестный исходный цвет среди исключений'],
    [/^a replacement must be a validated or production color/i, 'Замена должна быть валидированным или производственным цветом из допустимой палитры'],
    [/^mode must be 'tonal' or 'color_path'/i, 'Режим — «Тональный» или «Цветовой путь»'],
    [/^the trajectory colors are identical/i, 'Цвета траектории совпадают'],
    [/^the seed must be a whole number/i, 'Зерно — целое число'],
    [/^no candidate parameter sets are available/i, 'В доступном диапазоне параметров нет подходящих кандидатов'],
    [/^the explanation must be non-empty text/i, 'Пояснение должно быть непустым текстом'],
    [/^target color is not a valid Lab value/i, 'Целевой цвет задан неверно: L от 0 до 100, a и b от −128 до 127'],
  ]);
})();
