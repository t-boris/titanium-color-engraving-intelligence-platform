/* Сообщения проверок ввода, плана, платы, фотографии и файла LightBurn (DEC-034). Загружается после i18n-more.js:
   более раннее правило имеет приоритет. Название поля в сообщении переводит FIELD; неизвестное остаётся как есть. */
'use strict';
(() => {
  const FIELD = {power: 'Мощность', frequency: 'Частота', speed: 'Скорость', 'pulse width': 'Длительность импульса', 'line interval': 'Интервал линий',
    'cell width': 'Ширина ячейки', 'cell height': 'Высота ячейки', gap: 'Зазор', 'delta E tolerance': 'Допуск ΔE', 'variance threshold': 'Порог дисперсии',
    'repeat threshold': 'Порог повторов', focus: 'Фокус', name: 'Название', camera: 'Камера', lighting: 'Освещение',
    angle: 'Угол съёмки', 'reference chart': 'Эталонная карта', 'material name': 'Название материала',
    bidirectional: 'Двунаправленная гравировка', cross_hatch: 'Перекрёстная штриховка', 'face search': 'Поиск лиц'};
  const f = (s) => FIELD[String(s).replace(/ min$| max$/, '')] || s;
  I18N.add([
    // числа, стенд, материал
    [/^(.+) must be a finite positive number$/i, (m) => f(m[1]) + ' — конечное положительное число'],
    [/^(.+) must be a finite number$/i, (m) => f(m[1]) + ' — конечное число'],
    [/^(.+) must be a number$/i, (m) => f(m[1]) + ' — число'],
    [/^(.+) must not be negative$/i, (m) => f(m[1]) + ' не может быть отрицательным'],
    [/^(.+) must be positive$/i, (m) => f(m[1]) + ' должно быть положительным'],
    [/^(.+) is required$/i, (m) => 'Заполните поле: ' + f(m[1])],
    [/^passes must be a positive integer/i, 'Проходы — положительное целое число'],
    [/^repeat threshold must be a positive integer/i, 'Порог повторов — положительное целое число'],
    [/^material name is required/i, 'Укажите название материала'],
    // серия плат и план
    [/^(.+): enter at least one value$/i, (m) => f(m[1]) + ': введите хотя бы одно значение'],
    [/^(.+): values must not repeat$/i, (m) => f(m[1]) + ': значения не должны повторяться'],
    [/^(.+): '(.*)' is not a number$/i, (m) => f(m[1]) + ': «' + m[2] + '» — не число'],
    [/^(\d+) cells need more LightBurn layers/i, 'Слишком много ячеек для слоёв LightBurn'],
    [/^the plan has no layers to export/i, 'В плане нет слоёв: экспорт недоступен'],
    [/^(\d+) layers exceed the (\d+) LightBurn layers available/i, (m) => 'Слоёв больше, чем доступно в LightBurn (' + m[2] + ')'],
    [/^layer (.+) lacks power, frequency or speed/i, (m) => 'У слоя ' + m[1] + ' нет мощности, частоты или скорости'],
    [/^layer (.+) has an incomplete prediction/i, (m) => 'У слоя ' + m[1] + ' неполный прогноз: нужны уверенность, ожидаемая ошибка и стабильность'],
    [/^marker layer power, frequency and speed are not set/i, 'Не заданы мощность, частота и скорость слоя маркеров (Настройки → «Метки для фото»)'],
    [/^calibration plates always carry markers/i, 'Калибровочные платы всегда несут маркеры'],
    [/^LightBurn layer indexes (\d+)–(\d+) are outside the standard output color range 00–29\. Their photo regions are still measured; the file alone cannot confirm whether those operations were emitted\.$/i,
      (m) => `Индексы слоёв LightBurn ${m[1]}–${m[2]} выходят за пределы стандартной палитры 00–29. Их участки на фотографии всё равно измерены; по одному файлу нельзя подтвердить, были ли эти операции выведены на лазер.`],
    [/^This layer index is outside LightBurn's 30 standard output colors; its photo measurement is retained\.$/i,
      'Индекс слоя вне 30 стандартных выходных цветов LightBurn; измерение по фотографии сохранено.'],
    [/^the number of colors must be between 1 and (\d+)/i, (m) => 'Число цветов — от 1 до ' + m[1]],
    [/^this is not a discrete color plan/i, 'Это не план цветной гравировки'],
    [/^(\d+) distinct colors need more LightBurn layers/i, 'Слишком много различных цветов для слоёв LightBurn'],
    [/^unknown source color in the exclusions/i, 'Неизвестный исходный цвет среди исключений'],
    [/^a replacement must be a validated or production color/i, 'Замена должна быть валидированным или производственным цветом из допустимой палитры'],
    [/^mode must be 'tonal' or 'color_path'/i, 'Режим — «Тональный» или «Цветовой путь»'],
    [/^the trajectory colors are identical/i, 'Цвета траектории совпадают'],
    [/^the seed must be a whole number/i, 'Зерно — целое число'],
    [/^no candidate parameter sets are available/i, 'В доступном диапазоне параметров нет подходящих кандидатов'],
    [/^the proposal was made for another lens than the one installed on the laser now/i,
      'Предложение сделано для другой линзы, чем установлена на лазере сейчас: поставьте ту линзу или сделайте предложение для установленной'],
    [/^the explanation must be non-empty text/i, 'Пояснение должно быть непустым текстом'],
    [/^target color is not a valid Lab value/i, 'Целевой цвет задан неверно: L от 0 до 100, a и b от −128 до 127'],
    [/^these Lab readings are camera-relative RAW measurements; they are preserved for experiment analysis but excluded from standard-color predictions$/i,
      'Эти значения Lab получены относительно камеры из RAW. Они сохранены для анализа эксперимента, но исключены из стандартных цветовых прогнозов.'],
    [/^the selected capture setup was not found$/i, 'Выбранная установка съёмки не найдена'],
    [/^select the titanium stock used for this engraving$/i, 'Выберите заготовку титана, использованную для этой гравировки'],
    [/^the selected titanium stock was not found; choose it again$/i, 'Выбранная заготовка титана не найдена; выберите её ещё раз'],
    [/^the photograph has no usable color measurement basis$/i, 'Для измерения цвета на фотографии нет подходящего основания'],
    [/^select a titanium stock from the list$/i, 'Выберите заготовку титана из списка'],
    [/^Manual alignment was used for this plate; its QR identifier could not be verified\. Check the layer overlay before accepting measurements\.$/i,
      'Плата совмещена вручную; QR-идентификатор не удалось проверить. Перед принятием измерений проверьте наложение контуров слоёв.'],
    [/^pulse width is missing from this LightBurn layer$/i, 'В этом слое LightBurn не задан Q-Pulse'],
    [/^line interval is missing from this LightBurn layer$/i, 'В этом слое LightBurn не задан интервал линий'],
    [/^pass count is missing from this LightBurn layer$/i, 'В этом слое LightBurn не задано число проходов'],
    [/^numPasses: expected a positive integer, got (\S+)$/i, (m) => `numPasses: ожидалось положительное целое число, получено ${m[1]}`],
    [/^globalRepeat: expected a positive integer, got (\S+)$/i, (m) => `globalRepeat: ожидалось положительное целое число, получено ${m[1]}`],
    [/^fewer than three registration markers detected; missing (.+)$/i, (m) => `Найдено меньше трёх регистрационных меток; не найдены метки ${m[1]}`],
    [/^global passes must be a whole number from 1 to 100$/i, 'Общее число проходов должно быть целым от 1 до 100'],
    [/^(\d+) cells need more than the (\d+) test layers available after cleaning and markers$/i, (m) => `${m[1]} ячейкам требуется больше тестовых слоёв, чем доступно после очистки и маркеров (${m[2]})`],
    [/^the engraving would exceed LightBurn's (\d+) output layers \(colors 00–29\); T1\/T2 are not output layers$/i, (m) => `Гравировка превышает лимит выходных слоёв LightBurn (${m[1]}, цвета 00–29); T1/T2 не являются выходными слоями`],
    [/^the LightBurn layer indices overlap; every output operation needs its own color layer$/i, 'Индексы слоёв LightBurn пересекаются; для каждой выходной операции нужен отдельный цветовой слой'],
    [/^(.+) must be true or false$/i, (m) => `${f(m[1])}: допустимо только «да» или «нет»`],
    [/^choose the lens or mark it unknown$/i, 'Выберите линзу или отметьте, что она неизвестна'],
  ]);

  // план, опознанный по файлу LightBurn, и его метки (REQ-013, REQ-003)
  const lens = (s) => s.replace(/, focal length unknown$/, ', фокус неизвестен').replace(/ mm$/, ' мм');
  const made = (kind) => (kind === 'plan' ? 'план делался' : 'плата делалась');
  I18N.add([
    [/^the plan or plate chosen for this photograph was not found$/i, 'План или плата, для которых загружается фотография, не найдены'],
    [/^experiment identifier (\S+) belongs to a deleted experiment$/i, (m) => `Идентификатор эксперимента ${m[1]} относится к удалённому эксперименту`],
    [/^this plan was made for a different laser than the one selected/i, 'План сделан для другого лазера, чем выбранный: выберите лазер плана'],
    [/^four registration markers match the LightBurn geometry, but the identifier QR code cannot be read/i,
      'Четыре метки совпадают с геометрией файла LightBurn, но QR-идентификатор не читается, поэтому не подтверждено, что на фотографии именно эта плата или работа. '
      + 'Поставьте четыре угла работы на фотографии или загрузите фотографию со страницы её платы или плана.'],
    [/^the lens installed now \((.+)\) differs from the lens of this plan \((.+)\)$/i, (m) => `Сейчас стоит линза ${lens(m[1])}, а план делался на ${lens(m[2])}: цвета нельзя считать сравнимыми`],
    [/^no lens is installed on the laser now; the plan was made with (.+)$/i, (m) => `Сейчас на лазере нет линзы, а план делался на ${lens(m[1])}`],
    [/^this plan has no record of its lens$/i, 'У этого плана нет записи о линзе'],
    [/^no lens was chosen for this photograph; the (plate|plan) was made with (.+): the measurements are kept with the (?:plate|plan)'s lens$/i,
      (m) => `Для фотографии линза не выбрана; ${made(m[1])} на ${lens(m[2])}: измерения записываются с этой линзой`],
    [/^the lens chosen for this photograph \((.+)\) differs from the lens of this (plate|plan) \((.+)\): the measurements are kept with the (?:plate|plan)'s lens$/i,
      (m) => `Для фотографии выбрана линза ${lens(m[1])}, а ${made(m[2])} на ${lens(m[3])}: измерения записываются с линзой ${m[2] === 'plan' ? 'плана' : 'платы'}`],
  ]);

  // удаление пары и плана: знание перестраивается, стадия не понижается (DEC-047, DEC-066)
  const STAGE = {measured: 'Измерено', candidate: 'Кандидат', repeated: 'Повторено', validated: 'Валидировано', production: 'Производственное'};
  I18N.add([
    [/^a removed photograph took away the evidence of this stage: no eligible observation is left$/i,
      'Удалённая фотография унесла основания этой стадии: подходящих наблюдений не осталось. Стадия сохранена, запись помечена «под вопросом».'],
    [/^a removed photograph took away the evidence of this stage: what remains supports only (\w+): (.+)$/i,
      (m) => `Удалённая фотография унесла основания этой стадии; стадия сохранена, запись помечена «под вопросом». `
        + `Оставшиеся данные подтверждают только «${STAGE[m[1]] || m[1]}»: ${I18N.tr(m[2])}`],
    [/^no eligible observation is left$/i, 'подходящих наблюдений не осталось'],
  ]);

  // установка съёмки у каждой фотографии и эталонные значения её карты (REQ-009, DEC-025)
  I18N.add([
    [/^add the capture setup \(rig\) of your photographs on the Settings screen before uploading one$/i,
      'Сначала опишите установку съёмки (стенд), на которой сделаны фотографии: Настройки → «Съёмка»'],
    [/^the placeholder capture setup describes only pairs uploaded before every photograph had a rig/i,
      'Установка-заглушка описывает только пары, загруженные до того, как у каждой фотографии появилась установка съёмки. Выберите стенд, на котором сделана эта фотография.'],
    [/^the white point must be one of (.+)$/i, (m) => `Белая точка эталонных значений: ${m[1]}`],
    [/^only the 2° standard observer is supported$/i, 'Поддерживается только стандартный наблюдатель 2°'],
    [/^say where the reference values come from$/i, 'Укажите, откуда взяты эталонные значения'],
    [/^the reference values must be 24 Lab triples/i, 'Эталонные значения — 24 тройки Lab (L от 0 до 100, a и b от −128 до 127)'],
  ]);

  // план, восстановленный из файла импортированной работы (REQ-005, REQ-006)
  I18N.add([
    [/^a plan restored from an imported file records the job that was engraved; it is not exported as a new job$/i,
      'План восстановлен из файла импортированной работы: это запись выполненного задания, её нельзя экспортировать как новое задание'],
    [/^no prediction: no knowledge entry of these settings had all three estimates when the plan was restored$/i,
      'Прогноза нет: когда план восстанавливался, для этих настроек не было записи знания со всеми тремя оценками'],
    [/^power, frequency or speed is missing from this LightBurn layer$/i, 'В этом слое LightBurn нет мощности, частоты или скорости'],
    [/^the plan was restored from the imported LightBurn file: a planned colour is the prediction its knowledge entry gave when the plan was restored$/i,
      'План восстановлен из импортированного файла LightBurn: плановый цвет — прогноз записи знания на момент восстановления плана'],
  ]);

  // проверка ячеек, сделанных для целевого цвета (REQ-006)
  I18N.add([
    [/^camera-relative measurement: it cannot be compared with a target colour$/i,
      'Измерено относительно камеры, без эталонной карты: с целевым цветом сравнивать нельзя'],
  ]);

  // слой меток и подписей: только сохранённые оператором параметры (DEC-027)
  I18N.add([
    [/^the saved marker layer settings are not offered by this laser: (.+)$/i,
      (m) => `Сохранённые параметры слоя меток не подходят этому лазеру (Настройки → «Метки для фото»): ${I18N.tr(m[1])}`],
  ]);

  // запись не найдена (ответ 404) и отказы маршрутов API
  const RECORD = {plan: ['План', 'не найден'], pair: ['Пара', 'не найдена'], proposal: ['Предложение', 'не найдено'],
    'laser device': ['Лазер', 'не найден'], document: ['Документ', 'не найден'], experiment: ['Эксперимент', 'не найден'],
    knowledge: ['Запись знания', 'не найдена'], lens: ['Линза', 'не найдена'], 'research session': ['Сеанс исследования', 'не найден'],
    'capture setup': ['Установка съёмки', 'не найдена']};
  I18N.add([
    [new RegExp(`^(${Object.keys(RECORD).join('|')}) (\\S+) not found$`, 'i'),
      (m) => { const [what, missing] = RECORD[m[1].toLowerCase()]; return `${what} ${/^\d+$/.test(m[2]) ? '№ ' : ''}${m[2]} ${missing}`; }],
    [/^the stored (source photograph|LightBurn file) is missing$/i,
      (m) => (/photograph/i.test(m[1]) ? 'Сохранённая исходная фотография' : 'Сохранённый файл LightBurn') + ' отсутствует на диске'],
    [/^observation (\d+) is immutable; model-derived values are stored separately$/i,
      (m) => `Наблюдение № ${m[1]} не меняется: значения, вычисленные моделью, хранятся отдельно`],
    [/^targets of this plan are already used by an experiment proposal$/i,
      'Целевые цвета этого плана уже используются в предложении эксперимента'],
    [/^the trajectory and the allowed entries must be JSON lists of whole numbers$/i,
      'Цветовой путь и разрешённые записи знаний должны быть JSON-списками целых чисел'],
  ]);
})();
